import copy
import json
import math
from typing import Optional

from .objects.ball import Ball
from .objects.base import SimObject
from .objects.dropzone import DropZone
from .objects.robot import Robot
from .objects.wall import Wall

# Register object types here to make them available in JSON configs.
# Extend this dict when you add new SimObject subclasses.
OBJECT_REGISTRY: dict[str, type] = {
    "wall": Wall,
    "ball": Ball,
    "dropzone": DropZone,
}


class World:
    """
    Holds the full simulation state and advances it each tick.

    Loading / reset
    ---------------
    The world is initialised from a JSON config file.  Calling `reset()`
    restores everything to the state described in that file.

    Multi-robot
    -----------
    Config supports a "robots" list.  Legacy single-"robot" configs still work.
    All action endpoints require a robot_id to identify which robot to command.

    Extending
    ---------
    - Register new object types in OBJECT_REGISTRY.
    - Add them to the JSON config under "objects".
    """

    def __init__(self, config_path: str):
        self.config_path = config_path
        self._initial_config: dict = {}
        self.robots: dict[str, Robot] = {}
        self.objects: dict[str, SimObject] = {}
        self.size_x = 20.0
        self.size_y = 20.0
        self.background_color = "#87CEEB"
        self._load(config_path)

    # ------------------------------------------------------------------ #
    #  Loading                                                             #
    # ------------------------------------------------------------------ #

    def _load(self, path: str):
        with open(path) as f:
            config = json.load(f)
        self._initial_config = copy.deepcopy(config)
        self._apply_config(config)

    def _apply_config(self, config: dict):
        w = config.get("world", {})
        self.size_x = float(w.get("size_x", 20.0))
        self.size_y = float(w.get("size_y", 20.0))
        self.background_color = w.get("background_color", "#87CEEB")

        # Support "robots" list (new) and legacy "robot" object
        robots_cfg = config.get("robots") or (
            [config["robot"]] if config.get("robot") else []
        )
        self.robots = {}
        for r in robots_cfg:
            robot = Robot(
                id=r.get("id", "robot"),
                x=float(r.get("x", 0.0)),
                y=float(r.get("y", 0.0)),
                rotation=float(r.get("rotation", 0.0)),
                speed=float(r.get("speed", 3.0)),
                rotation_speed=float(r.get("rotation_speed", 180.0)),
                grab_range=float(r.get("grab_range", 1.5)),
                camera_fov=float(r.get("camera_fov", 60.0)),
                camera_range=float(r.get("camera_range", 15.0)),
                color=r.get("color", "#1565C0"),
            )
            self.robots[robot.id] = robot

        self.objects = {}
        for obj_cfg in config.get("objects", []):
            obj = self._create_object(obj_cfg)
            if obj:
                self.objects[obj.id] = obj

    def _create_object(self, cfg: dict) -> Optional[SimObject]:
        cls = OBJECT_REGISTRY.get(cfg.get("type", ""))
        if cls is None:
            return None
        kwargs = {k: v for k, v in cfg.items() if k != "type"}
        return cls(**kwargs)

    def _robot(self, robot_id: str) -> Optional[Robot]:
        return self.robots.get(robot_id)

    # ------------------------------------------------------------------ #
    #  Simulation tick                                                     #
    # ------------------------------------------------------------------ #

    def tick(self, dt: float):
        for robot in self.robots.values():
            old_x, old_y = robot.x, robot.y
            robot.tick(dt)

            # Revert robot on wall collision
            for obj in self.objects.values():
                if obj.type == "wall" and robot.overlaps(obj):
                    robot.x = old_x
                    robot.y = old_y
                    robot._target_x = None
                    robot._target_y = None
                    break

            # Clamp to world bounds
            r = robot.RADIUS
            robot.x = max(-self.size_x / 2 + r, min(self.size_x / 2 - r, robot.x))
            robot.y = max(-self.size_y / 2 + r, min(self.size_y / 2 - r, robot.y))

            # Drag held object with robot
            if robot.held_object and robot.held_object in self.objects:
                held = self.objects[robot.held_object]
                held.x = robot.x
                held.y = robot.y

    # ------------------------------------------------------------------ #
    #  Actions                                                             #
    # ------------------------------------------------------------------ #

    def grab(self, robot_id: str) -> dict:
        robot = self._robot(robot_id)
        if not robot:
            return {"status": "error", "message": f"Unknown robot: {robot_id}"}
        if robot.held_object:
            return {"status": "error", "message": "Already holding an object"}

        best: Optional[SimObject] = None
        best_dist = float("inf")

        for obj in self.objects.values():
            if not getattr(obj, "is_grabbable", False):
                continue
            if getattr(obj, "grabbed", False):
                continue
            dx, dy = obj.x - robot.x, obj.y - robot.y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist <= robot.grab_range and dist < best_dist:
                best, best_dist = obj, dist

        if best is None:
            return {"status": "error", "message": "No grabbable object in range"}

        best.grabbed = True  # type: ignore[attr-defined]
        robot.held_object = best.id
        return {"status": "ok", "grabbed": best.id}

    def release(self, robot_id: str) -> dict:
        robot = self._robot(robot_id)
        if not robot:
            return {"status": "error", "message": f"Unknown robot: {robot_id}"}
        if not robot.held_object:
            return {"status": "error", "message": "Not holding anything"}

        obj_id = robot.held_object
        robot.held_object = None

        if obj_id not in self.objects:
            return {"status": "ok", "released": obj_id}

        obj = self.objects[obj_id]
        obj.grabbed = False  # type: ignore[attr-defined]

        # Drop slightly in front of the robot
        rot_rad = math.radians(robot.rotation)
        drop_dist = robot.RADIUS + getattr(obj, "radius", 0.3) + 0.15
        obj.x = robot.x + math.sin(rot_rad) * drop_dist
        obj.y = robot.y + math.cos(rot_rad) * drop_dist

        # Check if dropped onto a matching dropzone
        for dz in self.objects.values():
            if dz.type != "dropzone" or dz.delivered:  # type: ignore[attr-defined]
                continue
            if not dz.contains(obj.x, obj.y):  # type: ignore[attr-defined]
                continue
            accepted = dz.accepted_color  # type: ignore[attr-defined]
            obj_color = getattr(obj, "color", None)
            if accepted is None or accepted == obj_color:
                dz.delivered = True  # type: ignore[attr-defined]
                dz.delivered_object_id = obj_id  # type: ignore[attr-defined]
                obj.x, obj.y = dz.x, dz.y  # snap to zone centre
                return {"status": "ok", "released": obj_id, "delivered_to": dz.id}

        return {"status": "ok", "released": obj_id}

    def get_visible_objects(self, robot_id: str) -> list:
        """
        Return all non-wall objects whose centre falls within the robot's
        camera FOV cone and camera_range distance.

        Note: occlusion by walls is not modelled — this is a pure angular check.

        Each entry includes:
          id, type, x, y, distance (units), angle (degrees from FOV centre)
        """
        robot = self.robots[robot_id]

        rot_rad = math.radians(robot.rotation)
        fwd_x = math.sin(rot_rad)
        fwd_y = math.cos(rot_rad)
        half_fov = robot.camera_fov / 2.0

        visible = []

        # Check world objects
        for obj in self.objects.values():
            if obj.type == "wall":
                continue
            dx, dy = obj.x - robot.x, obj.y - robot.y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 1e-3 or dist > robot.camera_range:
                continue
            dot = max(-1.0, min(1.0, (fwd_x * dx + fwd_y * dy) / dist))
            angle_deg = math.degrees(math.acos(dot))
            if angle_deg <= half_fov:
                visible.append({
                    "id": obj.id,
                    "type": obj.type,
                    "x": round(obj.x, 3),
                    "y": round(obj.y, 3),
                    "distance": round(dist, 3),
                    "angle": round(angle_deg, 2),
                })

        # Check other robots
        for other in self.robots.values():
            if other.id == robot_id:
                continue
            dx, dy = other.x - robot.x, other.y - robot.y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 1e-3 or dist > robot.camera_range:
                continue
            dot = max(-1.0, min(1.0, (fwd_x * dx + fwd_y * dy) / dist))
            angle_deg = math.degrees(math.acos(dot))
            if angle_deg <= half_fov:
                visible.append({
                    "id": other.id,
                    "type": "robot",
                    "x": round(other.x, 3),
                    "y": round(other.y, 3),
                    "distance": round(dist, 3),
                    "angle": round(angle_deg, 2),
                })

        return visible

    def reset(self):
        self._apply_config(copy.deepcopy(self._initial_config))

    # ------------------------------------------------------------------ #
    #  Serialisation                                                       #
    # ------------------------------------------------------------------ #

    def get_state(self) -> dict:
        return {
            "robots": [r.to_dict() for r in self.robots.values()],
            "objects": [obj.to_dict() for obj in self.objects.values()],
            "world": {
                "size_x": self.size_x,
                "size_y": self.size_y,
                "background_color": self.background_color,
            },
        }

    def get_objects(self) -> list:
        return [obj.to_dict() for obj in self.objects.values()]
