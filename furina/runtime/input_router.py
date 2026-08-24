"""输入路由（plan/4 §3, §29, plan/7 §17）。

把 Qt 鼠标事件 → InteractionEngine（识别的语义事件）。
角色包围盒由桌面窗口提供（get_char_rect）。
互动优先级高于自主行为（plan/4 §29）。
"""
from __future__ import annotations

import time
from typing import Callable, Optional, Tuple

from furina.interaction import InteractionEngine


class InputRouter:
    def __init__(self, interaction: InteractionEngine,
                 char_rect_provider: Callable[[], Tuple[float, float, float, float]]) -> None:
        self.interaction = interaction
        self.get_char_rect = char_rect_provider

    def on_button(self, pressed: bool, x: float, y: float) -> bool:
        """返回是否命中角色(可拖拽)。"""
        ev = self.interaction.on_pointer(time.monotonic(), x, y, pressed, self.get_char_rect())
        return bool(ev and ev.type.value == "grab")

    def on_move(self, x: float, y: float, pressed: bool) -> None:
        self.interaction.on_pointer(time.monotonic(), x, y, pressed, self.get_char_rect())
