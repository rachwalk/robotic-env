"""
Multi-robot controller — two communicating agents (lab2).

Each agent controls one robot and can exchange messages with the other agent
via HTTP services created with connector.create_service.

Usage:
    python lab2.py "task for robot_red" "task for robot_blue"
    python lab2.py   # uses default cooperative delivery tasks
"""

import json
import sys
import threading
from typing import List, Literal, Optional, Tuple, Type

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from rai.agents.langchain.react_agent import ReActAgent
from rai.communication.hri_connector import HRIMessage
from rai.communication.http.api import HTTPConnectorMode
from rai.communication.http.connectors import HTTPConnector
from rai.communication.http.messages import HTTPMessage
from rai.initialization import get_llm_model
from rai.messages import MultimodalArtifact

BASE_URL = "http://localhost:8000"

# Ports on which each agent's HTTP server listens for incoming messages
AGENT_PORTS = {
    "robot_red": 9001,
    "robot_blue": 9002,
}


class ChatHistory:
    """Thread-safe per-agent message log.

    Records both messages sent by this agent and messages received from the peer,
    so get_chat_history always returns the full two-way conversation.
    """

    def __init__(self) -> None:
        self._messages: List[dict] = []
        self._lock = threading.Lock()

    def append(self, sender: str, recipient: str, message: str) -> None:
        with self._lock:
            self._messages.append(
                {"from": sender, "to": recipient, "message": message}
            )

    def get_all(self) -> List[dict]:
        with self._lock:
            return list(self._messages)


class BaseHTTPTool(BaseTool):
    """Base class for tools that communicate with the robot HTTP API.

    ``robot_id`` is automatically injected into every POST request body so
    that each agent only ever commands its own robot.
    """

    connector: HTTPConnector
    base_url: str
    robot_id: str

    name: str = ""
    description: str = ""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _get(self, path: str, timeout_sec: float = 10.0) -> dict | str:
        msg = HTTPMessage(method="GET", payload=None)
        resp = self.connector.service_call(
            msg, f"{self.base_url}{path}", timeout_sec=timeout_sec
        )
        try:
            return json.loads(resp.payload)
        except Exception:
            return resp.payload

    def _post(
        self, path: str, body: dict | None = None, timeout_sec: float = 10.0
    ) -> dict | str:
        full_body = {"robot_id": self.robot_id, **(body or {})}
        msg = HTTPMessage(method="POST", payload=full_body)
        resp = self.connector.service_call(
            msg, f"{self.base_url}{path}", timeout_sec=timeout_sec
        )
        try:
            return json.loads(resp.payload)
        except Exception:
            return resp.payload


class _NoArgs(BaseModel):
    pass


class _GoToPositionInput(BaseModel):
    x: float = Field(..., description="Target X coordinate")
    y: float = Field(..., description="Target Y coordinate")


class _RotateInput(BaseModel):
    angle: float = Field(
        ..., description="Absolute heading in degrees (0=north, clockwise)"
    )


class _SendMessageInput(BaseModel):
    message: str = Field(
        ..., description="Message text to send to the other robot agent"
    )


class GetVisibleObjectsTool(BaseHTTPTool):
    name: str = "get_visible_objects"
    description: str = (
        "Get all objects currently in this robot's camera field of view. "
        "Returns id, type, position, distance, and angle from FOV centre for each."
    )
    args_schema: Type[_NoArgs] = _NoArgs # type: ignore

    def _run(self) -> str:
        return json.dumps(
            self._get(f"/visible_objects?robot_id={self.robot_id}")
        )


class GetOwnStateTool(BaseHTTPTool):
    name: str = "get_own_state"
    description: str = (
        "Get this robot's own state: position (x, y), rotation, held object, color, "
        "and camera range. Use this instead of get_state when you only need to know "
        "where you are or what you are carrying."
    )
    args_schema: Type[_NoArgs] = _NoArgs # type: ignore

    def _run(self) -> str:
        state = self._get("/state")
        assert isinstance(state, dict)
        robots = state.get("robots", {})
        own = None
        for robot in robots:
            if robot["id"] == self.robot_id:
                own = robot
        if own is None:
            return json.dumps({"error": f"robot {self.robot_id!r} not found in state"})
        return json.dumps(own)


class GoToPositionTool(BaseHTTPTool):
    name: str = "go_to_position"
    description: str = (
        "Move the robot to (x, y). Movement happens over time; returns immediately."
    )
    args_schema: Type[_GoToPositionInput] = _GoToPositionInput # type: ignore

    def _run(self, x: float, y: float) -> str:
        return json.dumps(self._post("/go_to_position", {"x": x, "y": y}))


class RotateTool(BaseHTTPTool):
    name: str = "rotate"
    description: str = "Rotate the robot to an absolute heading. 0=north, clockwise."
    args_schema: Type[_RotateInput] = _RotateInput # type: ignore

    def _run(self, angle: float) -> str:
        return json.dumps(self._post("/rotate", {"angle": angle}))


class GrabTool(BaseHTTPTool):
    name: str = "grab"
    description: str = "Pick up the nearest grabbable object within grab_range."
    args_schema: Type[_NoArgs] = _NoArgs # type: ignore

    def _run(self) -> str:
        return json.dumps(self._post("/grab"))


class ReleaseTool(BaseHTTPTool):
    name: str = "release"
    description: str = "Drop the currently held object in front of the robot."
    args_schema: Type[_NoArgs] = _NoArgs # type: ignore

    def _run(self) -> str:
        return json.dumps(self._post("/release"))

class GetCameraTool(BaseHTTPTool):
    name: str = "get_camera"
    description: str = (
        "Capture a PNG frame from the robot's POV camera. Returns the image for visual inspection."
    )
    args_schema: Type[_NoArgs] = _NoArgs # type: ignore
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"

    def _run(self) -> Tuple[str, MultimodalArtifact]:
        result = self._get(f"/camera?robot_id={self.robot_id}")
        if isinstance(result, dict) and "image" in result:
            return "Camera image from robot POV:", MultimodalArtifact(
                images=[result["image"]], audios=[]
            )
        return json.dumps(result), MultimodalArtifact(images=[], audios=[])


# ---------------------------------------------------------------------------
# Inter-agent communication tools
# ---------------------------------------------------------------------------


class SendMessageTool(BaseTool):
    # TODO: implement!
    ...


class GetChatHistoryTool(BaseTool):
    # TODO: implement!
    ...


def _make_system_prompt(robot_id: str, peer_robot_id: str) -> str:
    return (
        f"You are a robot controller agent for robot '{robot_id}'. "
        f"There is another agent '{peer_robot_id}' operating in the same environment. "
        f"You can communicate with '{peer_robot_id}' using the send_message and "
        "get_chat_history tools. "
        "Use the available tools to interact with your robot and complete the assigned task. "
        "go_to_position tool goes directly to a specific position, if there is a wall you will stop at it."
        "you should verify if you succeeded by using the get_own_state tool"
        "Coordinate with the other agent when it would be beneficial."
    )


def _build_tools(
    connector: HTTPConnector,
    base_url: str,
    robot_id: str,
    peer_robot_id: str,
    peer_url: str,
    chat_history: ChatHistory,
) -> List[BaseTool]:
    api_kwargs = dict(connector=connector, base_url=base_url, robot_id=robot_id)
    return [
        GetOwnStateTool(**api_kwargs), # type: ignore
        GetVisibleObjectsTool(**api_kwargs), # type: ignore
        GoToPositionTool(**api_kwargs), # type: ignore
        RotateTool(**api_kwargs), # type: ignore
        GrabTool(**api_kwargs), # type: ignore
        ReleaseTool(**api_kwargs), # type: ignore
        # GetCameraTool(**api_kwargs), # type: ignore
        # SendMessageTool(
        #     connector=connector,
        #     robot_id=robot_id,
        #     peer_robot_id=peer_robot_id,
        #     peer_url=peer_url,
        #     chat_history=chat_history,
        # ),
        # GetChatHistoryTool(chat_history=chat_history),
    ]


class RobotControllerAgent(ReActAgent):
    """ReActAgent pre-configured for one robot in a multi-robot environment."""

    def __init__(
        self,
        connector: HTTPConnector,
        base_url: str,
        robot_id: str,
        peer_robot_id: str,
        peer_url: str,
        chat_history: ChatHistory,
    ):
        tools = _build_tools(connector, base_url, robot_id, peer_robot_id, peer_url, chat_history)
        llm = get_llm_model("complex_model", config_path="./config.toml")
        super().__init__(
            target_connectors={},
            llm=llm,
            tools=tools,
            system_prompt=_make_system_prompt(robot_id, peer_robot_id),
        )


# ---------------------------------------------------------------------------
# Per-agent runner (executed in its own thread)
# ---------------------------------------------------------------------------


def _run_agent(
    robot_id: str,
    peer_robot_id: str,
    task: str,
    own_port: int,
    peer_port: int,
) -> None:
    chat_history = ChatHistory()
    connector = HTTPConnector(
        host="localhost",
        port=own_port,
        mode=HTTPConnectorMode.client_server,
    )

    # Register /inbox so the peer can deliver messages to this agent
    def on_inbox(data: dict) -> dict:
        sender = data.get("from", "unknown")
        message = data.get("message", "")
        chat_history.append(sender, robot_id, message)
        return {"status": "message received... considering response"}

    connector.create_service("/inbox", on_inbox, method="POST")

    peer_url = f"http://localhost:{peer_port}/inbox"

    agent = RobotControllerAgent(
        connector=connector,
        base_url=BASE_URL,
        robot_id=robot_id,
        peer_robot_id=peer_robot_id,
        peer_url=peer_url,
        chat_history=chat_history,
    )

    print(f"\n[{robot_id}] Task: {task}\n{'=' * 60}")

    agent.run()
    agent(HRIMessage(text=task, message_author="human"))
    agent.wait()
    agent.stop()

    for msg in reversed(agent.state["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        print(f"\n[{robot_id}] {block['text']}")
            else:
                print(f"\n[{robot_id}] {content}")
            break

    connector.shutdown()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(task_red: str, task_blue: str) -> None:
    t_red = threading.Thread(
        target=_run_agent,
        args=(
            "robot_red", "robot_blue", task_red,
            AGENT_PORTS["robot_red"], AGENT_PORTS["robot_blue"],
        ),
        name="agent-robot_red",
    )
    t_blue = threading.Thread(
        target=_run_agent,
        args=(
            "robot_blue", "robot_red", task_blue,
            AGENT_PORTS["robot_blue"], AGENT_PORTS["robot_red"],
        ),
        name="agent-robot_blue",
    )

    t_red.start()
    t_blue.start()
    t_red.join()
    t_blue.join()


if __name__ == "__main__":
    _default_red = (
        "Deliver the red ball to the red dropzone. "
        "Coordinate with robot_blue if it would help."
    )
    _default_blue = (
        "Deliver the blue ball to the blue dropzone. "
        "Coordinate with robot_red if it would help."
    )
    task_red = sys.argv[1] if len(sys.argv) > 1 else _default_red
    task_blue = sys.argv[2] if len(sys.argv) > 2 else _default_blue
    run(task_red, task_blue)
