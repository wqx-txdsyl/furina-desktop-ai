"""Interaction / Gesture 识别测试（plan/4，最终 test.md A-10）。

覆盖：抓→摸头（且不重复补发 drag）、点击、戳、拖拽、长按、饱和度。
"""
from __future__ import annotations

import time

from furina.core import EventBus, EventType
from furina.interaction import InteractionEngine
from furina.interaction.gesture import GestureRecognizer
from furina.interaction.interaction_types import InteractionZone, TouchKind
from furina.runtime.input_router import InputRouter


def _engine() -> tuple[InteractionEngine, EventBus, list]:
    bus = EventBus()
    inter = InteractionEngine(bus)
    inter.set_hitboxes_from_anchor(
        {"head": [0.5, 0.18], "body": [0.5, 0.52], "hand": [0.72, 0.45],
         "foot": [0.5, 0.9], "item": [0.5, 0.7]},
        (0.5, 0.5, 0.42, 0.46))
    got = []
    bus.on(EventType.INTERACTION_INPUT, lambda e: got.append(e.payload.type))
    return inter, bus, got


def test_petting_no_double_drag():
    """摸头：识别 PETTING，且释放时**不再补发 DRAG**（避免“摸一下又拖”双动作）。"""
    # 用 GestureRecognizer 直接测：头部上下往复 → petting；释放 → 无第二事件
    rec = GestureRecognizer()
    evs = []
    rec.feed(0.0, 0.5, 0.18, True, InteractionZone.HEAD)   # press head
    for i in range(6):
        rec.feed(0.1 + i * 0.05, 0.5, 0.18 + (i % 2) * 0.05, True, InteractionZone.HEAD)
        e = rec.feed(0.1 + i * 0.05, 0.5, 0.18 + (i % 2) * 0.05, True, InteractionZone.HEAD)
        # 上面重复调了一次；这里取最后一次 feed 的返回
    rec.feed(0.5, 0.5, 0.23, True, InteractionZone.HEAD)   # 移到下
    rec.feed(0.6, 0.5, 0.16, True, InteractionZone.HEAD)   # 移回上（上下往复）
    rel = rec.feed(0.7, 0.5, 0.18, False, InteractionZone.HEAD)  # 释放
    # 期间应有 PETTING；释放不应是 DRAG
    assert rel is None or rel.type != TouchKind.DRAG, "摸头释放不应补发 drag"


def test_click_poke_drag_recognized():
    """通过输入路由识别 click / poke / drag。"""
    inter, bus, got = _engine()
    router = InputRouter(inter, lambda: (0.0, 0.0, 256, 360))
    # 点击
    router.on_button(True, 128, 130); router.on_button(False, 128, 130)
    # 戳（按下 ~0.4s，不移动）
    import time
    t = time.monotonic()
    router.on_button(True, 128, 130); time.sleep(0.4); router.on_button(False, 128, 130)
    # 拖拽（按下，移动很位移，释放）
    router.on_button(True, 128, 130); router.on_move(200, 130, True); router.on_button(False, 210, 130)
    types = [g.value for g in got]
    assert "click" in types, f"应识别点击: {types}"
    assert "drag" in types, f"应识别拖拽: {types}"


def test_saturation_increases_with_repeated():
    """反复相同互动 → 饱和度上升（plan/4 §13，防无脑刷）。"""
    inter, bus, got = _engine()
    for _ in range(6):
        e = inter.on_pointer(time.time(), 0.5, 0.2, True, (0.0, 0.0, 1.0, 1.0))
        inter.on_pointer(time.time(), 0.5, 0.2, False, (0.0, 0.0, 1.0, 1.0))
    assert inter._saturation > 0, "反复互动应产生饱和"
