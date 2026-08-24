"""互动类型（plan/4 §4-6, §26）。

Hitbox 跟随当前素材锚点，不能写死（plan/4 §5）。
InteractionEvent 是核心语义单元，Behavior 只收到这个，不接收原始鼠标像素。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class HitboxShape(str, enum.Enum):
    ELLIPSE = "ellipse"
    RECT = "rect"
    POLYGON = "polygon"


class InteractionZone(str, enum.Enum):
    HEAD = "head"
    FACE = "face"
    BODY = "body"
    HAND = "hand"
    FOOT = "foot"
    ITEM = "item"
    WHOLE = "whole"


class TouchKind(str, enum.Enum):
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    LONG_PRESS = "long_press"
    PETTING = "petting"        # 摸头
    POKE = "poke"              # 戳
    DRAG = "drag"
    RELEASE = "release"
    HOVER = "hover"
    APPROACH = "approach"
    LEAVE = "leave"
    GRAB = "grab"


@dataclass
class Hitbox:
    zone: InteractionZone
    shape: HitboxShape = HitboxShape.ELLIPSE
    # 归一化 [x,y] 中心 + 半宽/半高（相对角色包围盒）
    cx: float = 0.5
    cy: float = 0.5
    rx: float = 0.2
    ry: float = 0.2
    # 多边形顶点（归一化）当 shape=polygon
    points: List[List[float]] = field(default_factory=list)

    def contains(self, nx: float, ny: float) -> bool:
        """nx/ny 是相对角色包围盒的归一化坐标。"""
        if self.shape == HitboxShape.ELLIPSE:
            dx = (nx - self.cx) / self.rx
            dy = (ny - self.cy) / self.ry
            return dx * dx + dy * dy <= 1.0
        if self.shape == HitboxShape.RECT:
            return (abs(nx - self.cx) <= self.rx) and (abs(ny - self.cy) <= self.ry)
        return False


@dataclass
class InteractionEvent:
    """用户对芙宁娜做的事，已识别为一个语义事件（plan/4 §26）。"""

    type: TouchKind
    target: InteractionZone
    duration: float = 0.0
    intensity: float = 0.5
    direction: str = ""           # left_to_right / up_down / ...
    count: int = 1
    meta: Dict[str, object] = field(default_factory=dict)
