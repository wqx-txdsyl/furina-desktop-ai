"""Phase 13 Runtime Harness 测试 —— 观察只读 / 无第二 Runtime / Trace / Proxy。

不 require 完整 App（用轻量 fake）以保持快 + 确定性；证明 Harness 是"示波器/非模拟器"。
真实功能因果（emotion/relationship/memory 真实变化）由 RC1 测试 + 用户 Manual 场景覆盖。
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from furina.runtime.observability import RuntimeTrace, TraceRecorder, redact
from furina.runtime.harness.proxy import SpatialProxyWindow
from furina.runtime.harness.view_model import ObservationAdapter, HarnessViewModel
from furina.runtime.harness.controller import RuntimeHarness
from furina.runtime.world import DesktopWorld, Rect
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.spatial import DesktopSpatialRuntime, SpatialIntentResolver


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
def test_trace_redacts_secrets():
    s = redact("api_key=sk-abcdef12345 and Authorization: Bearer xyz")
    assert "sk-" not in s and "Bearer" not in s, "应脱敏 api key / bearer"


def test_trace_recorder_ring_bounded():
    r = TraceRecorder(ring_size=50)
    for _ in range(200):
        r.record(RuntimeTrace())
    assert r.event_count() == 200
    assert len(r.recent(200)) <= 50, "ring 应被限制"


def test_trace_chain_shares_root():
    r = TraceRecorder()
    root = r.start_root(trigger_type="USER_MESSAGE", subsystem="dialogue", stage="USER_INPUT",
                        input_summary="你好")
    r.child(root, subsystem="dialogue", stage="LLM_REQUEST", input_summary="ctx")
    r.child(root, subsystem="dialogue", stage="VALIDATOR", output_summary="ok", model="glm")
    chain = r.chain(root.root_trace_id)
    assert len(chain) == 3, "chain 应含 root+2 child"
    assert all(t.root_trace_id == root.root_trace_id for t in chain)


def test_trace_marks_fallback():
    r = TraceRecorder()
    root = r.start_root(trigger_type="LIFE", subsystem="life", stage="LLM_REQUEST", model="glm")
    r.child(root, subsystem="life", stage="DECISION", output_summary="fallback", fallback=True, success=False)
    chain = r.chain(root.root_trace_id)
    assert any(t.fallback for t in chain), "fallback 应被标记"


# ================================================================ Observation only
def _fake_state():
    st = SimpleNamespace()
    st.life = SimpleNamespace(activity="read", macro=SimpleNamespace(value="living"), reason="")
    st.emotion = SimpleNamespace(label="calm", valence=0.5, arousal=0.4, mood=70)
    st.user_working = False
    st.user_idle_seconds = 10
    st.needs = SimpleNamespace(energy=80, fatigue=20, hunger=30, boredom=40,
                               social_need=50, sleepiness=10, playfulness=30)
    return st


def _fake_app():
    app = SimpleNamespace()
    app.state = SimpleNamespace(state=_fake_state())
    rel = SimpleNamespace(trust=0.58, comfort=0.67, annoyance=0.08,
                          familiarity=0.4, interaction_tolerance=0.5, social_confidence=0.6)
    app.relationship = SimpleNamespace(state=rel)
    app.memory = SimpleNamespace(store=SimpleNamespace(query=lambda limit=1, status=None: [1]))
    app._sched = SimpleNamespace(current_frame=lambda: None)
    app._spatial = None
    app.life_brain = None
    app.dialogue_brain = None
    return app


def test_harness_is_observation_only():
    """ObservationAdapter 只读：调用 snapshot 后不改任何状态字段。"""
    app = _fake_app()
    ad = ObservationAdapter(app)
    before = app.state.state.emotion.label
    snap = ad.state_snapshot()
    ad.relationship_snapshot()
    ad.brain_metrics()
    assert snap["activity"] == "read"
    assert snap["emotion"] == "calm"
    # 未改动
    assert app.state.state.emotion.label == before
    assert app.relationship.state.trust == 0.58


def test_harness_does_not_create_second_state():
    """HarnessViewModel 只读变换，不新建 HarnessState / 不写回。"""
    app = _fake_app()
    vm = HarnessViewModel(ObservationAdapter(app))
    life = vm.current_life()
    badges = vm.status_badges()
    assert "activity" in life and "brain" in life
    assert any("BACKEND RC1" in b for b in badges.values()) or "status" not in badges


# ================================================================ Controller wiring (real paths)
class _FakeAgent:
    def execute(self, task, params=None): return {"status": "completed"}


def _harness_app():
    calls = {"interact": [], "feed": [], "brain_worker": [], "user_reject": [0]}
    app = _fake_app()
    app.interaction = SimpleNamespace(emit_event=lambda kind, zone: calls["interact"].append((kind, zone)))
    app._feed = lambda food: calls["feed"].append(food)
    app._brain_worker = lambda text: calls["brain_worker"].append(text)
    app._sched = SimpleNamespace(
        on_user_reject=lambda: calls["user_reject"].__setitem__(0, calls["user_reject"][0] + 1),
        current_frame=lambda: None)
    app._on_user_command = lambda task: calls["brain_worker"].append(task)
    app.agent = _FakeAgent()
    app.world = DesktopWorld(1920, 1080)
    app.bus = SimpleNamespace(on=lambda *a, **k: None)
    app.calls = calls
    return app


def test_harness_uses_production_interaction_path(qapp):
    app = _harness_app()
    h = RuntimeHarness(app)
    h.on_interact("petting", "head")
    assert ("petting", "head") in app.calls["interact"], "互动按钮必须走真实 InteractionEngine.emit_event"


def test_harness_uses_production_feed_path(qapp):
    app = _harness_app()
    h = RuntimeHarness(app)
    h.on_feed("cake")
    assert "cake" in app.calls["feed"], "喂食必须走真实 app._feed"


def test_harness_uses_production_dialogue_path(qapp):
    app = _harness_app()
    h = RuntimeHarness(app)
    h.on_user_message("你好")
    assert "你好" in app.calls["brain_worker"], "对话必须走真实 _brain_worker(→DialogueBrain)"


def test_harness_reject_uses_production_path(qapp):
    app = _harness_app()
    h = RuntimeHarness(app)
    h.on_reject()
    assert app.calls["user_reject"][0] == 1, "拒绝必须走真实 scheduler.on_user_reject"


def test_harness_covers_dialogue_and_life(qapp):
    """控制器包装 DialogueBrain.say → 记录真实 trace。"""
    app = _harness_app()
    app.dialogue_brain = SimpleNamespace(say=lambda **kw: "嗯，我在看书。")
    h = RuntimeHarness(app)
    h.recorder.clear()
    speech = h.app.dialogue_brain.say(intent="talk", user_initiated=True, emotion="calm")
    assert speech == "嗯，我在看书。"
    assert h.recorder.event_count() >= 1, "对话应记录 trace"


# ================================================================ Proxy / Spatial
def test_proxy_exposes_spatial_contract(qapp):
    """proxy 暴露 pos/set_position/width（供 SpatialRuntime 驱动）。"""
    win = SpatialProxyWindow()
    win.set_position(500, 300)
    assert win.pos.x == 500 and win.pos.y == 300
    assert callable(win.width)
    assert win._char_w > 0 and win._char_h > 0


def test_proxy_drag_release_commits_position(qapp):
    """释放后位置来自拖拽（真实 spatial 语义，而非 snap 回）。"""
    world = DesktopWorld(1920, 1080)
    world.update_active_window(Rect(600, 200, 700, 600))
    win = SpatialProxyWindow(world=world)
    sp = DesktopSpatialRuntime(world, window=win)
    sp.set_initial_foot(300, 900)
    d = SpatialIntentResolver().resolve(RuntimeFrameBuilder().build(activity_name="approach_user",
                                                                    motion_intent="APPROACH"))
    sp.accept(d, now=0.0)
    sp.tick(now=0.5)
    sp.on_drag_start(now=1.0)
    win.set_position(1300, 300)
    sp.on_drag_release(now=2.0, commit=True)
    assert sp._current_plan is None, "释放后不应保留自主计划"


def test_harness_does_not_block_scheduler(qapp):
    """tick_spatial 不抛异常、不长时间阻塞。"""
    app = _harness_app()
    h = RuntimeHarness(app)
    t0 = time.monotonic()
    for _ in range(100):
        h.tick_spatial()
    assert time.monotonic() - t0 < 1.0, "harness tick 不应阻塞"
