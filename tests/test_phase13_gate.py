"""Phase 13 Technical Final Gate Patch — §1 Director 优先级 / §2 idle 初始真相 测试。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from types import SimpleNamespace

from furina.core import EventBus, EventType
from furina.state import CharacterState
from furina.state.state_engine import StateEngine
from furina.emotion import EmotionEngine
from furina.runtime.scheduler import Scheduler
from furina.runtime.window_awareness import WindowInfo
from furina.runtime.world import Rect, DesktopWorld


# ================================================================ §1 Director 优先级契约
def _plain_director():
    from furina.director import Director, ActionRequest
    bus = EventBus()
    director = Director(bus)
    exec_calls = []
    director.set_executor(lambda req: exec_calls.append(req.action))
    return director, exec_calls, ActionRequest


def test_lower_priority_mind_cannot_preempt_active_agent():
    """严格更低优先级（mind=3）**永不**替换更高优先级 current（agent=2，interruptible=True）。"""
    director, exec_calls, AR = _plain_director()
    director.submit(AR(source="agent", action="agent_work", priority=2))   # interruptible 默认 True
    director.drain()
    assert director.current().source == "agent"
    director.submit(AR(source="mind", action="read", priority=3))
    # 多次 drain（生产每 medium tick 调用）
    for _ in range(5):
        director.drain()
    assert director.current().source == "agent", "低优先级 mind 不得替换 active agent"
    assert "read" not in exec_calls, "mind 不得执行"
    assert len(director._queue) == 1, "mind 必须保持排队（deferred）"


def test_higher_priority_agent_preempts_running_mind():
    """更高优先级（agent=2）可抢占运行中的 mind（3），抢占回调恰好一次。"""
    from furina.director import Director, ActionRequest
    bus = EventBus()
    director = Director(bus)
    replaced = []
    director.on_before_replace = lambda old, new: replaced.append((old.source, new.source))
    director.set_executor(lambda req: None)
    director.submit(ActionRequest(source="mind", action="read", priority=3))
    director.drain()
    director.submit(ActionRequest(source="agent", action="agent_work", priority=2))
    director.drain()
    assert director.current().source == "agent"
    assert replaced == [("mind", "agent")], f"抢占回调必须恰好一次: {replaced}"


def test_equal_priority_same_source_agent_phase_transition_still_works():
    """同优先级（2）同源 Agent 阶段→阶段（interruptible=True）仍可替换（不得冻结在首阶段）。"""
    director, exec_calls, AR = _plain_director()
    director.submit(AR(source="agent", action="agent_planning", priority=2))
    director.drain()
    director.submit(AR(source="agent", action="agent_work", priority=2))
    director.drain()
    director.submit(AR(source="agent", action="agent_report", priority=2))
    director.drain()
    assert exec_calls == ["agent_planning", "agent_work", "agent_report"], exec_calls
    assert director.current().action == "agent_report"


# ================================================================ §3 生产集成（真实 drain 多次）
class _GateWorkingDB:
    def __init__(self):
        self.say_calls = 0
        self.say_event = threading.Event()
    def say(self, **kw):
        self.say_calls += 1
        self.say_event.set()
        return "说了句"


def _gate_integration(db):
    from furina.director import Director, ActionRequest
    from furina.app import Furina
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.motivation = __import__("furina.behavior", fromlist=["BehaviorMotivation"]).BehaviorMotivation()
    sched.dialogue_brain = db
    sched.relationship = SimpleNamespace(apply=lambda *a, **k: None, state=None,
                                         factors=lambda: {"comfort": 0.5})
    sched.be = SimpleNamespace(step=lambda s: None)
    director = Director(bus)
    # 生产等价 executor（同 app._on_execute 的 mind 分支）
    def _executor(req):
        if getattr(req, "source", "") == "mind":
            payload = getattr(req, "payload", {}) or {}
            sched.on_mind_action_started(req.action, float(payload.get("planned_duration", 0.0) or 0.0))
            sched.start_autonomous_dialogue(
                activity=req.action,
                speech_level=int(payload.get("speech_level", 0) or 0),
                speech_intent=payload.get("speech_intent", "") or "",
                dialogue_needed=bool(payload.get("dialogue_needed", False)),
                emotion=payload.get("emotion", ""),
                duration=float(payload.get("planned_duration", 0.0) or 0.0),
                intent=payload.get("speech_intent", "") or req.action)
    director.set_executor(_executor)
    director.on_before_replace = lambda old, new: (
        sched.on_mind_preempted(reason=f"preempted_by_{getattr(new, 'source', '')}")
        if old is not None and getattr(old, "source", "") == "mind" else None)
    sched.director = director
    sched.dispatcher.bind_owner()
    se.state.user_idle_seconds = 10.0
    sched._llm_speech_at = 0.0
    return sched, bus, se, director, ActionRequest


def _submit_mind_talk(director, AR):
    director.submit(AR(source="mind", action="talk", priority=3,
                       payload={"planned_duration": 30.0, "speech_level": 3,
                                "speech_intent": "聊聊", "emotion": "calm"}))


def test_active_agent_blocks_lower_priority_mind_across_real_drains():
    """Agent=current 时，多次 director.drain()（真实生产节奏）后 mind 仍被挡。"""
    db = _GateWorkingDB()
    sched, bus, se, director, AR = _gate_integration(db)
    director.submit(AR(source="agent", action="agent_work", priority=2))
    director.drain()
    _submit_mind_talk(director, AR)
    for _ in range(8):
        director.drain()          # 关键：**多次真实 drain**（旧 false-green 测试省略了）
        sched.dispatcher.drain()
    assert director.current().source == "agent", "active Agent 必须保持 current"
    assert db.say_calls == 0, f"被挡的 mind 不得产出台词: {db.say_calls}"
    assert sched._pending_social_bid is None, "无可见台词 → 无 social bid"
    assert getattr(sched, "_activity_instance", None) is None, "被挡的 mind 不得启动 ActivityInstance"


def test_blocked_mind_has_no_activity_instance():
    db = _GateWorkingDB()
    sched, bus, se, director, AR = _gate_integration(db)
    director.submit(AR(source="agent", action="agent_work", priority=2))
    director.drain()
    _submit_mind_talk(director, AR)
    for _ in range(8):
        director.drain()
    assert getattr(sched, "_activity_instance", None) is None


def test_blocked_mind_has_no_autonomous_speech_or_bid():
    db = _GateWorkingDB()
    sched, bus, se, director, AR = _gate_integration(db)
    director.submit(AR(source="agent", action="agent_work", priority=2))
    director.drain()
    _submit_mind_talk(director, AR)
    for _ in range(8):
        director.drain()
        sched.dispatcher.drain()
    time.sleep(0.2)               # 等任何误启动的 worker
    sched.dispatcher.drain()
    assert db.say_calls == 0 and sched._pending_social_bid is None


def test_deferred_mind_executes_only_after_agent_finishes():
    """Agent finish 后 mind 才执行：实例启动、台词 1 次、可开一个 social bid。"""
    db = _GateWorkingDB()
    sched, bus, se, director, AR = _gate_integration(db)
    director.submit(AR(source="agent", action="agent_work", priority=2))
    director.drain()
    _submit_mind_talk(director, AR)
    for _ in range(5):
        director.drain()
    assert getattr(sched, "_activity_instance", None) is None
    director.finish(source="agent")
    director.drain()              # mind 现在执行
    assert director.current().source == "mind"
    assert sched._activity_instance is not None and sched._activity_instance["status"] == "RUNNING"
    assert db.say_event.wait(timeout=5), "执行后的 mind 必须启动自主台词"
    assert db.say_calls == 1, f"自主台词必须恰好一次: {db.say_calls}"
    sched.dispatcher.drain()
    assert sched._pending_social_bid is not None, "执行并出话后才开 social bid"


# ================================================================ §2 idle 初始真相
def test_character_state_idle_available_defaults_false():
    st = CharacterState()
    assert st.idle_available is False, "启动默认必须 False（尚无任何 OS 空闲样本）"


def test_world_state_idle_available_defaults_false():
    from furina.world_perception import WorldPerception
    wp = WorldPerception()
    assert wp.state.idle_available is False, "WorldState 默认必须 False"


def test_scheduler_idle_availability_missing_attr_defaults_false():
    """wa 缺 idle_available 属性 → Scheduler 回退 False（保守，不得默认 True）。"""
    bus = EventBus()
    se = StateEngine(bus)
    world = DesktopWorld(1920, 1080)
    wa = SimpleNamespace(poll=lambda: None)   # 无 idle_available 属性
    sched = Scheduler(bus, se, None, None, None, world, wa)
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.be = SimpleNamespace(step=lambda s: None)
    sched.director = SimpleNamespace(drain=lambda: None, submit=lambda r: None, finish=lambda **k: None)
    sched.dispatcher.bind_owner()
    sched._last_window_poll = 0.0
    sched._tick_medium(3.0)
    assert se.state.idle_available is False, "缺属性回退必须 False"


def test_harness_idle_availability_missing_attr_defaults_false():
    from furina.runtime.harness.controller import RuntimeHarness
    from furina.runtime.world import DesktopWorld
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication([])
    app = SimpleNamespace()
    st = SimpleNamespace(clock_hour=14, clock_minute=5, user_idle_seconds=0.0,
                         user_working=False, emotion=SimpleNamespace(label="calm"),
                         life=SimpleNamespace(activity="read"))   # 无 idle_available 属性
    app.state = SimpleNamespace(state=st)
    app.relationship = SimpleNamespace(state=None)
    app.memory = SimpleNamespace(store=SimpleNamespace(count=lambda: 0))
    app._sched = SimpleNamespace(current_frame=lambda: None, se=SimpleNamespace(state=st))
    app.life_brain = None
    app.dialogue_brain = None
    app.world = DesktopWorld(1920, 1080)
    app.bus = SimpleNamespace(on=lambda *a, **k: None)
    app.agent = SimpleNamespace(status="IDLE")
    app.emotion = SimpleNamespace(_recent={})
    h = RuntimeHarness(app)
    assert h._diagnostics().get("idle_available") is False, "诊断回退必须 False"


def test_character_snapshot_pairs_user_idle_with_availability():
    st = CharacterState()
    snap = st.snapshot()
    assert "user_idle" in snap and "idle_available" in snap
    assert snap["idle_available"] is False


def test_world_dict_exposes_idle_availability():
    from furina.world_perception import WorldPerception
    wp = WorldPerception()
    d = wp.state.to_dict()
    assert "idle_available" in d and d["idle_available"] is False


def test_first_unavailable_idle_sample_user_active_is_false():
    from furina.world_perception import WorldPerception
    wp = WorldPerception()
    w = wp.update(app="ClsX", title="", idle_seconds=0.0, hour=14, minute=0, idle_available=False)
    assert w.user_active is False, "未测量样本不得声称 active"
    assert w.interaction_availability == 0.0
    assert w.last_events if hasattr(w, "last_events") else wp.last_events == []


def test_startup_idle_unavailable_until_first_valid_sample():
    """Scheduler 构造 + start() 后 idle_available=False；失败 poll 后仍 False；有效样本后 True+测量值。"""
    from furina.runtime.window_awareness import WindowAwareness
    bus = EventBus()
    se = StateEngine(bus)
    world = DesktopWorld(1920, 1080)
    emitted = []
    wa = WindowAwareness(update_cb=lambda info: emitted.append(info))
    sched = Scheduler(bus, se, None, None, None, world, wa)
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.be = SimpleNamespace(step=lambda s: None)
    sched.director = SimpleNamespace(drain=lambda: None, submit=lambda r: None, finish=lambda **k: None)
    sched.start(None)
    # 启动后、首个 poll 前：idle_available 默认 False（state 默认）
    assert se.state.idle_available is False
    # 首次失败 poll（None）→ 仍 False
    import furina.runtime.window_awareness as WA
    with mock.patch.object(WA, "_active_window_windows",
                           return_value=WindowInfo(app="a", process="p", idle=None)), \
         mock.patch("sys.platform", "win32"):
        sched._last_window_poll = 0.0
        sched._tick_medium(3.0)
    assert se.state.idle_available is False, "首次失败后必须 False"
    # 有效样本 → True + 测量值
    with mock.patch.object(WA, "_active_window_windows",
                           return_value=WindowInfo(app="a", process="p", idle=42.0)), \
         mock.patch("sys.platform", "win32"):
        sched._last_window_poll = 0.0
        sched._tick_medium(3.0)
    assert se.state.idle_available is True, "有效样本后必须 True"
    assert abs(se.state.user_idle_seconds - 42.0) < 1e-9


from unittest import mock  # noqa: E402
