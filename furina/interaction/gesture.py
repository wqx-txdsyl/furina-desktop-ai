"""手势识别（legacy-plan/4 §3, §6, §30）。

把原始鼠标轨迹(坐标+按下状态)识别成语义事件：
hover / touch / stroke(petting) / grab / drag / release / poke / tap / approach / leave。
骨架实现核心逻辑：petting(上下往复轨迹)与 click/drag/poke。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .interaction_types import InteractionEvent, InteractionZone, TouchKind


@dataclass
class _Point:
    t: float
    x: float
    y: float


class GestureRecognizer:
    def __init__(self, max_trail: int = 8, pet_amplitude: float = 8.0) -> None:
        self.trail: List[_Point] = []
        self._down = False
        self._down_time = 0.0
        self._down_zone: Optional[InteractionZone] = None
        self._max_trail = max_trail
        self._pet_amp = pet_amplitude
        self._petted = False     # 本次按下期间是否已识别为摸头（避免释放再补一个 drag）

    def feed(self, t: float, x: float, y: float, pressed: bool,
             zone: Optional[InteractionZone]) -> Optional[InteractionEvent]:
        self.trail.append(_Point(t, x, y))
        if len(self.trail) > self._max_trail:
            self.trail = self.trail[-self._max_trail:]

        if pressed and not self._down:
            self._down = True
            self._down_time = t
            self._down_zone = zone
            self._petted = False
            if zone:
                return InteractionEvent(TouchKind.GRAB, zone)
            return None

        if not pressed and self._down:
            self._down = False
            ev = self._classify_release(t)
            self.trail.clear()
            return ev

        if self._down and zone and len(self.trail) >= 4:
            pet = self._detect_petting()
            if pet and zone is InteractionZone.HEAD:
                self._petted = True
                return InteractionEvent(TouchKind.PETTING, zone, direction=pet)
        return None

    # -------------------------------------------------- 释放：click / poke / drag
    def _classify_release(self, t: float) -> Optional[InteractionEvent]:
        if not self._down_zone:
            return None
        # 摸头手势已消费本次按下 → 释放时不再补发 drag/click（避免“摸一下又拖”双动作）
        if self._petted:
            return None
        dur = t - self._down_time
        moved = self._moved() > 5.0
        zone = self._down_zone
        if moved:
            return InteractionEvent(TouchKind.DRAG, zone, duration=dur, intensity=min(1.0, dur / 2))
        if dur < 0.25:
            return InteractionEvent(TouchKind.CLICK, zone, duration=dur)
        if dur < 0.8:
            return InteractionEvent(TouchKind.POKE, zone, duration=dur)
        return InteractionEvent(TouchKind.LONG_PRESS, zone, duration=dur)

    def _moved(self) -> float:
        if len(self.trail) < 2:
            return 0.0
        a, b = self.trail[0], self.trail[-1]
        return ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5

    def _detect_petting(self) -> str:
        """检测上下往复轨迹（↕），用于摸头。返回方向字符串或空串。"""
        ys = [p.y for p in self.trail[-6:]]
        if len(ys) < 4:
            return ""
        spread = max(ys) - min(ys)
        if spread < self._pet_amp:
            return ""
        # 简单判定左右/上下主导
        xs = [p.x for p in self.trail[-6:]]
        x_spread = max(xs) - min(xs)
        if x_spread > spread:
            return "left_to_right" if (xs[-1] - xs[0]) > 0 else "right_to_left"
        return "up_down"
