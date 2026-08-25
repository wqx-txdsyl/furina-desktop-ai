"""状态系统健壮性测试（FINAL_TEST_V1 (docs/archive/legacy) A-6）。"""
from __future__ import annotations

import math

from furina.core import EventBus
from furina.state import StateEngine, NeedsState, MacroState
from furina.state.state_engine import classify_activity


def test_needs_clamp_range():
    """需求值不能越界（0..100），且无 NaN。"""
    n = NeedsState()
    n.energy = 500
    n.hunger = -10
    n.sleepiness = 999
    n.clamp()
    for f in n.__dataclass_fields__:
        v = getattr(n, f)
        assert 0.0 <= v <= 100.0, f
        assert not math.isnan(v) and not math.isinf(v)


def test_update_needs_tick_no_nan():
    bus = EventBus()
    se = StateEngine(bus)
    se.update_needs(3.0, user_working=True, user_idle=0.0)
    se.update_needs(3.0, user_working=False, user_idle=120.0)
    n = se.state.needs
    for f in ["energy", "fatigue", "boredom", "hunger", "social_need"]:
        v = getattr(n, f)
        assert 0.0 <= v <= 100.0 and not math.isnan(v), f


def test_state_snapshot_serializable():
    bus = EventBus()
    se = StateEngine(bus)
    se.state.user_working = True
    snap = se.state.snapshot()
    # 无 NaN / 无不可序列化
    import math as m
    for k, v in snap.items():
        assert not (isinstance(v, float) and (m.isnan(v) or m.isinf(v))), k


def test_classify_activity():
    assert classify_activity("Code")["category"] == "coding"
    assert classify_activity("WINWORD", "我的文档")["category"] == "writing"
    assert classify_activity("chrome", "bilibili")["working"] is False
    assert classify_activity("", "")["working"] is False
