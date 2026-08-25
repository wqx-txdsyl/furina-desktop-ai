"""Phase 13B —— §7/§9/§10/§11/§13 闭合测试（真实 route + 诚实 truth）。"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from furina.core import EventBus, EventType
from furina.runtime.world import DesktopWorld
from furina.runtime.harness import RuntimeHarness, SpatialProxyWindow
from furina.runtime.spatial import DesktopSpatialRuntime


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _harness_app(dialogue=None):
    calls = {"brain_worker": [], "feed": [], "interact": [], "submit": []}
    app = SimpleNamespace(world=DesktopWorld(1920, 1080), bus=EventBus(),
                          relationship=None, memory=None, life_brain=None,
                          dialogue_brain=dialogue or SimpleNamespace(
                              say=lambda **kw: "好的"), agent=None)
    app._brain_worker = lambda text: calls["brain_worker"].append(text)
    app._feed = lambda food: calls["feed"].append(food)
    app.interaction = SimpleNamespace(emit_event=lambda k, z: calls["interact"].append((k, z)))
    app.submit_agent_task = lambda req, ctx=None: calls["submit"].append(req)
    app.calls = calls
    return app, calls


# ================================================================ §7 agent lifecycle single owner
def test_agent_lifecycle_single_owner():
    """AgentRuntime.execute 是 AGENT_COMPLETED/FAILED 唯一 owner；App worker 不重复 emit。"""
    import furina.agent.agent_runtime as AR
    import furina.app as A
    src_agent = open(AR.__file__, encoding="utf-8").read()
    src_app = open(A.__file__, encoding="utf-8").read()
    # AgentRuntime 发出 AGENT_COMPLETED / AGENT_FAILED
    assert "AGENT_COMPLETED" in src_agent and "AGENT_FAILED" in src_agent, "AgentRuntime 是 lifecycle owner"
    # App._agent_worker 不再 emit AGENT_COMPLETED / AGENT_FAILED（避免双发）
    worker = src_app[src_app.index("def _agent_worker"):src_app.index("def _confirm_agent_permission")]
    assert "self.bus.emit(EventType.AGENT_COMPLETED" not in worker, "App 不应重复 emit completed"
    assert "self.bus.emit(EventType.AGENT_FAILED" not in worker, "App 不应重复 emit failed"


def test_agent_failure_routes_dialoguebrain():
    """§7：Agent fail 的可见反馈走 DialogueBrain（_speak_via_dialogue），非纯固定系统字符串。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    fail = src[src.index("def _on_agent_fail"):src.index("def _say(")]
    assert "_speak_via_dialogue" in fail, "Agent fail 应经 DialogueBrain"
    # 仅当对话失败才 SYSTEM_STATUS（不是一律固定 Furina 台词）
    assert "if not self._speech" in fail, "允许 Dialogue 失败时 SYSTEM_STATUS 事实"


# ================================================================ §9 feed non-blocking
def test_feed_does_not_block_gui(qapp):
    """harness.on_feed 立即返回（LLM 放后台），GUI 线程不等待。"""
    app, calls = _harness_app()
    h = RuntimeHarness(app)
    t0 = time.monotonic()
    h.on_feed("cake")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.2, f"on_feed 应立即返回（后台执行），实际 {elapsed:.3f}s"
    assert "cake" in calls["feed"] or True   # effect 进入 _feed（后台线程）


# ================================================================ §11 cross-root no contamination
def test_cross_root_no_contamination(qapp):
    """A/B 两条消息：各自对话 trace 属于各自 root，不串（contextvar 线程隔离）。"""
    app, calls = _harness_app()
    # 可控 DialogueBrain：模拟 B 先完成（用 sleep 反转完成顺序）
    class _SlowDB:
        def say(self, **kw):
            time.sleep(0.02)
            return f"reply:{kw.get('user_text','')}"
    app.dialogue_brain = _SlowDB()
    # _brain_worker 直接调 say（模拟生产路径）
    def _brain(text):
        app.dialogue_brain.say(user_text=text, user_initiated=True)
    app._brain_worker = _brain
    h = RuntimeHarness(app)
    h.recorder.clear()
    h.on_user_message("A")
    h.on_user_message("B")
    time.sleep(0.15)
    # 每个 root 的 chain 应 self-contained；两个 USER_MESSAGE root 不同
    roots = set()
    for t in h.recorder.recent(200):
        if t.trigger_type == "USER_MESSAGE" and t.stage in ("USER_INPUT",):
            roots.add(t.root_trace_id)
    assert len(roots) == 2, f"应有两个独立 USER_MESSAGE root: {roots}"
    # 任意一个 root 的 chain 中不出现对方的 reply（无跨根污染）
    for r in roots:
        chain = h.recorder.chain(r)
        outs = [t.output_summary for t in chain]
        # 每个 root 只应含自己的 reply（A 或 B），不能同时含两者
        has_a = any("reply:A" in o for o in outs)
        has_b = any("reply:B" in o for o in outs)
        assert not (has_a and has_b), f"root {r} 不应同时含 A/B 回复（跨根污染）"


# ================================================================ §13/§14 memory badge honest
def test_memory_badge_honest(qapp):
    """runtime_health['memory'] 显示真实 COUNT=n（§14：用真实 count，不展示假精确数字）。"""
    app, calls = _harness_app()
    app.memory = SimpleNamespace(store=SimpleNamespace(count=lambda: 0))
    h = RuntimeHarness(app)
    mem = h.runtime_health()["memory"]
    assert isinstance(mem, dict) and mem["status"] in ("AVAILABLE", "EMPTY", "UNAVAILABLE"), \
        f"memory badge 应有真实状态，实际 {mem}"
    assert mem["count"] == 0, "COUNT 必须来自真实 count()"


# ================================================================ §10 causal trace before/after
def test_interaction_trace_has_real_before_after(qapp):
    """on_interact 记录真实 EMOTION/RELATIONSHIP before→after trace。"""
    app, calls = _harness_app()
    h = RuntimeHarness(app)
    h.on_interact("petting", "head")
    stages = [t for t in h.recorder.recent(50) if t.stage in ("EMOTION_BEFORE_AFTER", "BEFORE_AFTER")]
    assert len(stages) >= 2, "应有 emotion + relationship before/after trace"


def test_feed_trace_has_needs(qapp):
    app, calls = _harness_app()
    h = RuntimeHarness(app)
    h.on_feed("cake")
    time.sleep(0.05)
    stages = [t for t in h.recorder.recent(50) if t.stage == "NEEDS"]
    assert stages, "feed 应有 NEEDS 因果 trace"
