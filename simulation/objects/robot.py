import math
from typing import Optional

from .base import SimObject


class Robot(SimObject):
    """
    The controllable robot agent.

    Coordinate conventions
    ----------------------
    - rotation=0   → facing +Y (north)
    - rotation=90  → facing +X (east)
    - rotation increases clockwise (degrees)
    """

    RADIUS = 0.4  # collision radius

    def __init__(
        self,
        id: str,
        x: float,
        y: float,
        rotation: float = 0.0,
        speed: float = 3.0,
        rotation_speed: float = 180.0,
        grab_range: float = 1.5,
        camera_fov: float = 60.0,
        camera_range: float = 15.0,
        color: str = "#1565C0",
    ):
        super().__init__(id, x, y)
        self.color = color
        self.camera_range = camera_range
        self.rotation = rotation % 360          # degrees
        self.speed = speed                      # world-units / sec
        self.rotation_speed = rotation_speed    # degrees / sec
        self.grab_range = grab_range
        self.camera_fov = camera_fov
        self.held_object: Optional[str] = None

        self._target_x: Optional[float] = None
        self._target_y: Optional[float] = None
        self._target_rotation: Optional[float] = None

    # ------------------------------------------------------------------ #
    #  SimObject interface                                                 #
    # ------------------------------------------------------------------ #

    @property
    def type(self) -> str:
        return "robot"

    def get_aabb(self):
        r = self.RADIUS
        return (self.x - r, self.y - r, self.x + r, self.y + r)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "color": self.color,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "speed": self.speed,
            "rotation_speed": self.rotation_speed,
            "grab_range": self.grab_range,
            "camera_fov": self.camera_fov,
            "camera_range": self.camera_range,
            "held_object": self.held_object,
            "is_moving": self.is_moving,
            "is_rotating": self.is_rotating,
            "radius": self.RADIUS,
        }

    # ------------------------------------------------------------------ #
    #  Commands                                                            #
    # ------------------------------------------------------------------ #

    def set_target(self, x: float, y: float):
        """Begin moving toward (x, y).  Robot immediately faces the target."""
        self._target_x = x
        self._target_y = y
        dx, dy = x - self.x, y - self.y
        if abs(dx) > 1e-3 or abs(dy) > 1e-3:
            self._target_rotation = math.degrees(math.atan2(dx, dy)) % 360

    def set_rotation_target(self, angle: float):
        """Begin rotating to the given absolute heading (degrees)."""
        self._target_rotation = angle % 360

    # ------------------------------------------------------------------ #
    #  Simulation tick                                                     #
    # ------------------------------------------------------------------ #

    def tick(self, dt: float):
        if self._target_x is not None:
            dx = self._target_x - self.x
            dy = self._target_y - self.y
            dist = math.sqrt(dx * dx + dy * dy)
            step = self.speed * dt
            if dist <= step:
                self.x, self.y = self._target_x, self._target_y
                self._target_x = self._target_y = None
            else:
                self.x += (dx / dist) * step
                self.y += (dy / dist) * step

        if self._target_rotation is not None:
            diff = (self._target_rotation - self.rotation + 180) % 360 - 180
            step = self.rotation_speed * dt
            if abs(diff) <= step:
                self.rotation = self._target_rotation
                self._target_rotation = None
            else:
                self.rotation = (self.rotation + math.copysign(step, diff)) % 360

    # ------------------------------------------------------------------ #
    #  Properties                                                          #
    # ------------------------------------------------------------------ #

    @property
    def is_moving(self) -> bool:
        return self._target_x is not None

    @property
    def is_rotating(self) -> bool:
        return self._target_rotation is not None
