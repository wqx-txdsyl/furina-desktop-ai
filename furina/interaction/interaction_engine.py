"""互动引擎（plan/4）。

职责：只负责“理解用户做了什么”，不负责“芙宁娜该怎么反应”
（反应由 Behavior/Director 决定，plan/4 §26）。
三层结果：即时(animation/speech) / 短期(状态) / 长期(关系/记忆)（plan/4 §27）。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from furina.core import EventBus, EventType, get_logger
from .gesture import GestureRecognizer
from .interaction_types import Hitbox, InteractionEvent, InteractionZone, TouchKind

log = get_logger("interaction")


class InteractionEngine:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.recognizer = GestureRecognizer()
        self.hitboxes: Dict[InteractionZone, Hitbox] = {}
        # 过度互动饱和（plan/4 §13）
        self._counts: Dict[Tuple[TouchKind, InteractionZone], int] = {}
        self._saturation = 0.0
        # 关系/记忆接入点（由 app 注入，可选）
        self.on_meaningful_interaction = None   # callable(InteractionEvent) -> 长期层

    # -------------------------------------------------- hitbox
    def set_hitboxes_from_anchor(self, anchors: Dict[str, List[float]], body_box: Tuple[float, float, float, float]) -> None:
        """从素材锚点[归一化x,y]生成 hitbox（plan/4 §5）。

        body_box = (cx, cy, half_w, half_h) 归一化。锚点值通常在 0..1。
        """
        cx, cy, hw, hh = body_box
        self.hitboxes = {}
        for zone_name, a in anchors.items():
            zone = InteractionZone(zone_name)
            self.hitboxes[zone] = Hitbox(zone=zone, cx=float(a[0]), cy=float(a[1]), rx=0.18, ry=0.18)

    def hit_test(self, nx: float, ny: float) -> Optional[InteractionZone]:
        for zone, hb in self.hitboxes.items():
            if hb.contains(nx, ny):
                return zone
        return None

    # -------------------------------------------------- 输入管道
    def on_pointer(self, t: float, x: float, y: float, pressed: bool,
                   char_rect: Tuple[float, float, float, float]) -> Optional[InteractionEvent]:
        """char_rect=(left, top, width, height) 角色在桌面(逻辑坐标)的包围盒。"""
        left, top, w, h = char_rect
        nx = (x - left) / w if w else 0.5
        ny = (y - top) / h if h else 0.5
        zone = self.hit_test(nx, ny) if self._inside(nx, ny) else None
        ev = self.recognizer.feed(t, x, y, pressed, zone)
        if ev:
            self._apply(ev)
        return ev

    @staticmethod
    def _inside(nx: float, ny: float) -> bool:
        return -0.2 <= nx <= 1.2 and -0.2 <= ny <= 1.2

    # -------------------------------------------------- 公共事件入口（Harness/按钮 与 真实鼠标 同一路径）
    def emit_event(self, kind: str, zone: str = "whole", **meta) -> Optional[InteractionEvent]:
        """以"用户对该区做了 kind"的语义事件进入生产应用路径（与 on_pointer 完全相同）。

        构造 InteractionEvent 后走 `_apply`（bus.emit INTERACTION_INPUT / HEAD_TOUCHED /
        on_meaningful_interaction），不绕过任何生产逻辑。kind ∈ TouchKind，zone ∈ InteractionZone。
        """
        try:
            ev = InteractionEvent(type=TouchKind(kind), target=InteractionZone(zone),
                                  count=0, meta=dict(meta))
            self._apply(ev)
            return ev
        except Exception:
            log.debug("emit_event failed: kind=%s zone=%s", kind, zone)
            return None

    # -------------------------------------------------- 应用结果
    def _apply(self, ev: InteractionEvent) -> None:
        key = (ev.type, ev.target)
        self._counts[key] = self._counts.get(key, 0) + 1
        ev.count = self._counts[key]
        # 饱和：反复同类互动 → 厌烦上升
        cur = self._counts[key]
        if cur > 3:
            self._saturation = min(1.0, self._saturation + 0.15)
        # 发事件给 Behavior / Director
        self.bus.emit(EventType.INTERACTION_INPUT, payload=ev, source="interaction")
        if ev.type == TouchKind.PETTING:
            # 摸头作为独立语义事件
            self.bus.emit(EventType.HEAD_TOUCHED, payload=ev, source="interaction")
        # 长期层：有意义的互动交给记忆/关系（plan/4 §27）
        if self.on_meaningful_interaction and ev.type in (TouchKind.PETTING, TouchKind.POKE, TouchKind.DRAG):
            self.on_meaningful_interaction(ev)
        log.debug("interaction: %s on %s (count=%d sat=%.2f)", ev.type.value, ev.target.value, ev.count, self._saturation)
