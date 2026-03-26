from typing import Optional

from .base import SimObject


class DropZone(SimObject):
    """
    A floor region that registers delivery when a matching ball is released onto it.

    Has no collision — the robot can walk over it freely.
    `delivered` becomes True the first time a matching ball is dropped inside.
    Set `accepted_color` to restrict which ball colour is accepted; None accepts any.
    """

    def __init__(
        self,
        id: str,
        x: float,
        y: float,
        width: float,
        height: float,
        color: str = "#FFD700",
        accepted_color: Optional[str] = None,
    ):
        super().__init__(id, x, y)
        self.width = width
        self.height = height
        self.color = color
        self.accepted_color = accepted_color
        self.delivered = False
        self.delivered_object_id: Optional[str] = None

    @property
    def type(self) -> str:
        return "dropzone"

    def get_aabb(self):
        hw, hh = self.width / 2, self.height / 2
        return (self.x - hw, self.y - hh, self.x + hw, self.y + hh)

    def contains(self, px: float, py: float) -> bool:
        ax1, ay1, ax2, ay2 = self.get_aabb()
        return ax1 <= px <= ax2 and ay1 <= py <= ay2

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "color": self.color,
            "accepted_color": self.accepted_color,
            "delivered": self.delivered,
            "delivered_object_id": self.delivered_object_id,
        }
