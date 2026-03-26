"""
Robotic Environment — FastAPI server
=====================================
Serves the Three.js viewer and exposes the robot control HTTP API.

Run with:
    uvicorn main:app --reload

API summary
-----------
GET  /state                  — full simulation snapshot (all robots + objects)
GET  /objects                — list of all non-robot objects
POST /go_to_position         — move robot toward {robot_id, x, y}
POST /rotate                 — rotate robot to absolute heading {robot_id, angle}
POST /grab                   — pick up nearest grabbable object {robot_id}
POST /release                — drop currently held object {robot_id}
POST /reset                  — restore world to config.json initial state
GET  /camera?robot_id=<id>   — render one frame from a robot's on-board camera
                               (requires a connected browser tab)
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from simulation.world import World

# --------------------------------------------------------------------------- #
#  Global state                                                                #
# --------------------------------------------------------------------------- #

world = World("config.json")
_clients: list[WebSocket] = []
_camera_future: Optional[asyncio.Future] = None

# --------------------------------------------------------------------------- #
#  Background simulation loop                                                  #
# --------------------------------------------------------------------------- #

TICK_DT = 0.05  # seconds  →  20 Hz


async def _simulation_loop():
    while True:
        world.tick(TICK_DT)
        await _broadcast({"type": "state", "data": world.get_state()})
        await asyncio.sleep(TICK_DT)


async def _broadcast(message: dict):
    dead = []
    for ws in _clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _clients:
            _clients.remove(ws)


# --------------------------------------------------------------------------- #
#  App lifecycle                                                               #
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_simulation_loop())
    yield
    task.cancel()


app = FastAPI(title="Robotic Environment", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
#  WebSocket                                                                   #
# --------------------------------------------------------------------------- #

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    global _camera_future
    await websocket.accept()
    _clients.append(websocket)
    await websocket.send_json({"type": "state", "data": world.get_state()})
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "camera_frame":
                if _camera_future and not _camera_future.done():
                    _camera_future.set_result(data["data"])
    except WebSocketDisconnect:
        if websocket in _clients:
            _clients.remove(websocket)

# --------------------------------------------------------------------------- #
#  Request models                                                              #
# --------------------------------------------------------------------------- #

class PositionBody(BaseModel):
    robot_id: str
    x: float
    y: float

class RotateBody(BaseModel):
    robot_id: str
    angle: float  # degrees, 0 = north (+Y), clockwise

class RobotBody(BaseModel):
    robot_id: str

# --------------------------------------------------------------------------- #
#  REST endpoints                                                              #
# --------------------------------------------------------------------------- #

@app.get("/state", summary="Full simulation snapshot")
async def get_state():
    """Returns all robot poses, all object states, and world metadata."""
    return world.get_state()


@app.get("/objects", summary="List all non-robot objects")
async def get_objects():
    """Returns current state of every object in the world."""
    return world.get_objects()


@app.post("/go_to_position", summary="Move a robot to a position")
async def go_to_position(body: PositionBody):
    """
    Begin moving the specified robot toward (x, y).  Returns immediately.
    Poll `is_moving` in /state (or subscribe via WebSocket) to detect arrival.
    """
    robot = world.robots.get(body.robot_id)
    if not robot:
        return JSONResponse(status_code=404, content={"error": f"Unknown robot: {body.robot_id}"})
    robot.set_target(body.x, body.y)
    return {"status": "ok", "robot_id": body.robot_id, "target": {"x": body.x, "y": body.y}}


@app.post("/rotate", summary="Rotate a robot to an absolute heading")
async def rotate(body: RotateBody):
    """
    Begin rotating to the given absolute heading in degrees.
    0 = north (+Y), 90 = east (+X), increases clockwise.
    Returns immediately; poll `is_rotating` in /state to detect completion.
    """
    robot = world.robots.get(body.robot_id)
    if not robot:
        return JSONResponse(status_code=404, content={"error": f"Unknown robot: {body.robot_id}"})
    robot.set_rotation_target(body.angle)
    return {"status": "ok", "robot_id": body.robot_id, "target_angle": body.angle}


@app.post("/grab", summary="Grab nearest grabbable object")
async def grab(body: RobotBody):
    """Attempt to pick up the closest grabbable object within grab_range."""
    return world.grab(body.robot_id)


@app.post("/release", summary="Release currently held object")
async def release(body: RobotBody):
    """
    Drop the currently held object slightly in front of the robot.
    If the drop position falls inside a matching DropZone, delivery is registered.
    """
    return world.release(body.robot_id)


@app.get("/visible_objects", summary="Objects visible in a robot's camera FOV")
async def visible_objects(robot_id: str = Query(..., description="ID of the observing robot")):
    """
    Returns all non-wall objects (and other robots) whose centre lies within
    the robot's camera FOV cone and within camera_range distance.

    Occlusion by walls is not modelled — purely angular + distance check.

    Each entry: { id, type, x, y, distance, angle }
    where `angle` is degrees from the centre of the FOV (0 = straight ahead).
    """
    if robot_id not in world.robots:
        return JSONResponse(status_code=404, content={"error": f"Unknown robot: {robot_id}"})
    return world.get_visible_objects(robot_id)


@app.post("/reset", summary="Reset world to initial config state")
async def reset():
    """Restores all positions and states from config.json."""
    world.reset()
    await _broadcast({"type": "state", "data": world.get_state()})
    return {"status": "ok"}


@app.get("/camera", summary="Render one frame from a robot's camera")
async def get_camera(robot_id: str = Query(..., description="ID of the robot whose camera to use")):
    """
    Requests a single rendered frame from the specified robot's on-board
    perspective camera.  Requires at least one browser tab connected.

    Response: { "image": "<base64 PNG>" }
    """
    global _camera_future

    if not _clients:
        return JSONResponse(
            status_code=503,
            content={"error": "No viewer connected — open the browser tab first"},
        )
    if robot_id not in world.robots:
        return JSONResponse(status_code=404, content={"error": f"Unknown robot: {robot_id}"})

    if _camera_future and not _camera_future.done():
        _camera_future.cancel()

    _camera_future = asyncio.get_running_loop().create_future()
    await _broadcast({"type": "camera_request", "robot_id": robot_id})

    try:
        image_data = await asyncio.wait_for(_camera_future, timeout=5.0)
        return {"image": image_data}
    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content={"error": "Camera render timed out"})


# --------------------------------------------------------------------------- #
#  Static files  (must be last — catches everything not matched above)        #
# --------------------------------------------------------------------------- #

app.mount("/", StaticFiles(directory="static", html=True), name="static")
