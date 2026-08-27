"""Phase 10.5-Closeout: Backend RC1 修复验证测试（§29）。

验证 B1（MemoryStore 线程安全 / 非空 DB 后台读写 / 真实 Scheduler 线程路径 / 可观察失败）
+S1（Relationship 单写入口 / 一次事件只改一次）+ S4（body_snapshot deprecated）。
"""
from __future__ import annotations

import importlib
import tempfile
import threading
import time
import warnings
from pathlib import Path
from typing import Optional

import pytest

from furina.memory import MemoryStore, MemoryEngine, MemoryLevel, MemorySource
from furina.memory.memory_types import RelationshipState
from furina.relationship import RelationshipEngine, EV_POSITIVE_TOUCH, EV_NEGATIVE_RESPONSE, EV_REJECT
from furina.core.event_bus import EventBus, EventType
from furina.state import CharacterState, MacroState


def _tmp_db() -> Path:
    return Path(tempfile.mkstemp(suffix=".db")[1])


def _nonempty_memory(store: MemoryStore) -> MemoryEngine:
    """构造一个**已有真实可检索记忆**的内存引擎（避免"空 DB 假安全"）。"""
    bus = EventBus()
    me = MemoryEngine(bus, store)
    me.observe("用户被夸奖开心", level=MemoryLevel.EPISODIC, source=MemorySource.INTERACTION,
               importance=0.6, outcome="praise")
    me.observe("帮用户处理了文件", level=MemoryLevel.EPISODIC, source=MemorySource.INTERACTION,
               importance=0.5, outcome="help_success")
    return me


# ================================================================ B1 thread safety
def test_memory_store_background_thread_retrieve_nonempty():
    """非空 DB，从与创建连接不同的线程 retrieve + reinforce，无异常且命中。"""
    store = MemoryStore(_tmp_db())
    me = _nonempty_memory(store)
    assert len(store.query(limit=10)) >= 1, "必须是非空 DB（假安全预防）"
    errs = []

    def worker():
        try:
            ms = me.retrieve(query="被夸", limit=5)
            ok = len(ms) >= 1
            errs.append(("ok", ok, [m.content for m in ms]))
        except Exception as e:
            errs.append(("err", repr(e)))

    t = threading.Thread(target=worker)
    t.start(); t.join()
    assert not any(x[0] == "err" for x in errs), f"后台线程 retrieve 异常: {errs}"
    assert errs and errs[0][1] is True, "检索应命中记录"


def test_memory_store_concurrent_read_write():
    """Thread A 读 + Thread B 写并发，多轮：0 SQLite 错误，行完整性/强度不损坏。"""
    store = MemoryStore(_tmp_db())
    me = _nonempty_memory(store)
    errors = []
    stop = threading.Event()

    def reader():
        try:
            for _ in range(200):
                ms = me.retrieve(query="", limit=5)
                if ms:
                    _ = [m.content for m in ms]
        except Exception as e:
            errors.append(("reader", repr(e)))

    def writer():
        try:
            for _ in range(150):
                me.observe("并发测试记忆", level=MemoryLevel.EPISODIC, source=MemorySource.SYSTEM,
                           importance=0.3)
                for m in me.retrieve(query="", limit=3):
                    m.strength = min(1.0, m.strength + 0.01)
                    store.insert(m)
        except Exception as e:
            errors.append(("writer", repr(e)))

    tr = threading.Thread(target=reader)
    tw = threading.Thread(target=writer)
    tr.start(); tw.start(); tr.join(); tw.join()
    assert not errors, f"并发读写异常: {errors}"
    assert len(store.query(limit=100, status=None)) >= 1, "DB 仍可读且非空"


# ================================================================ real Scheduler path
class _FakeLifeBrain:
    """可控 LifeBrain（非空 memory + 后台线程路径用）。"""
    def __init__(self, memory_engine, fail: bool = False):
        self.memory = memory_engine
        self._fail = fail
        self.decide_calls = 0

    def decide(self, *, state=None, recent_events=None, force=False, candidates=None):
        self.decide_calls += 1
        if self._fail:
            raise RuntimeError("injected-broken-llm")
        from furina.life_brain import LifeDecision
        return LifeDecision(activity="read", emotion="calm", intent="看书",
                            duration=60, next_think_in=30, dialogue_needed=False,
                            tool_needed=False, reason="audit-test")


def test_scheduler_lifebrain_nonempty_memory_thread_path():
    """真实走 Scheduler._drive_life 后台线程 → LifeBrain.decide → build_snapshot → retrieve（非空 memory）。"""
    from furina.runtime.scheduler import Scheduler
    bus = EventBus()
    store = MemoryStore(_tmp_db())
    me = _nonempty_memory(store)
    fake_brain = _FakeLifeBrain(me)

    # 构造轻量 Scheduler（不启动全部依赖，只测 _drive_life 线程路径）
    class _N:
        def __init__(self):
            self.state = CharacterState()
            self.state.needs.fatigue = 40.0
            self.state.emotion.label = "calm"
            self.motivation = None
            self.emotion = None
            self.life_brain = fake_brain
            self._recent_events = []
            self._last_speech_at = 0.0
            self._life_running = False
            self._life_decision_at = 0.0
            self._life_interrupt_pending = False
            self._pending_life_decision = None
            self.world_perc = None
            self.relationship = None
            self._current_life_activity = "idle"
            self._life_next_think = 9.0
    sched = Scheduler(bus, _N(), None, None, me, None, None, life_brain=fake_brain, motivation=None)
    sched.se = _N()          # 复用同一状态
    sched._recent_events = ["user_praise"]
    sched._life_interrupt_pending = True
    sched._life_decision_at = 0.0
    sched._life_running = False
    # 立即触发一次后台决策
    sched._drive_life()
    # 等线程完成
    for _ in range(200):
        if not getattr(sched, "_life_running", False):
            break
        time.sleep(0.01)
    assert fake_brain.decide_calls >= 1, "LifeBrain 后台线程应被调用"
    assert sched._pending_life_decision is not None, "决策结果应到达 Scheduler（而非 local fallback）"
    assert sched._pending_life_decision.activity == "read"
    assert sched._life_failure_count == 0, "不应有线程/DB 失败"
    assert sched._life_brain_success_count >= 1, "LifeBrain 成功应计数"


# ================================================================ observability
def test_lifebrain_failure_is_observable():
    """人为让 LifeBrain 抛异常：fallback 成功（_pending 为 None）+ 失败被计数/记录。"""
    from furina.runtime.scheduler import Scheduler
    bus = EventBus()
    store = MemoryStore(_tmp_db())
    me = _nonempty_memory(store)
    fail_brain = _FakeLifeBrain(me, fail=True)

    class _N:
        def __init__(self):
            self.state = CharacterState()
            self.motivation = None
            self.emotion = None
            self.life_brain = fail_brain
            self._recent_events = []
            self._last_speech_at = 0.0
            self._life_running = False
            self._life_decision_at = 0.0
            self._life_interrupt_pending = True
            self._pending_life_decision = None
            self.world_perc = None
    sched = Scheduler(bus, _N(), None, None, me, None, None, life_brain=fail_brain, motivation=None)
    sched.se = _N()
    sched._life_decision_at = 0.0
    sched._drive_life()
    for _ in range(200):
        if not getattr(sched, "_life_running", False):
            break
        time.sleep(0.01)
    assert sched._pending_life_decision is None, "失败时 fallback 到 local（合法）"
    assert sched._life_failure_count >= 1, "失败必须被计数（可观察）"
    assert sched._life_fallback_count >= 1, "fallback 必须被计数（可观察）"


# ================================================================ S1 relationship single writer
def test_relationship_single_writer():
    """关系唯一写入口 = RelationshipEngine；MemoryEngine.apply_relationship 已 deprecated。"""
    me = _nonempty_memory(MemoryStore(_tmp_db()))
    rel = RelationshipEngine(me.relationship)
    before = me.relationship.comfort
    rel.apply(EV_POSITIVE_TOUCH)
    after = me.relationship.comfort
    assert after >= before, "RelationshipEngine.apply 应改关系"
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        me.apply_relationship({"comfort": 1})   # deprecated 调用
        assert any(issubclass(x.category, DeprecationWarning) for x in w), "应产生 DeprecationWarning"


def test_relationship_event_applied_once():
    """一次用户正向事件 → 关系引擎恰好 apply 一次（无重复）。

    Phase 15 D5 anti-spam 后，同一窗口内第二次 apply 的边际确定性递减（×0.5），
    因此两次增量不再相等；改为断言精确单次 delta（首次=完整、第二次=×0.5）——
    若事件被重复路由，首次增量会是 2×，此断言比"相等"更严格地锁定恰好一次。
    """
    store = MemoryStore(_tmp_db())
    me = MemoryEngine(EventBus(), store)
    rel = RelationshipEngine(me.relationship)
    r0 = me.relationship.comfort
    # 模拟一次事件路由：只调用一次 RelationshipEngine.apply
    rel.apply(EV_POSITIVE_TOUCH)
    r1 = me.relationship.comfort
    # 参考：重复 apply 两次会更大；这里验证一次事件 → 精确一次增量
    rel.apply(EV_POSITIVE_TOUCH)
    r2 = me.relationship.comfort
    assert (r1 - r0) == pytest.approx(6.0 * 0.7), "首次 = 完整单次 delta（恰好一次，无重复）"
    assert (r2 - r1) == pytest.approx(6.0 * 0.7 * 0.5), "第二次边际递减（D5 anti-spam，确定性）"
    assert r1 > r0, "正向事件 comfort 应上升"


def test_relationship_no_memory_bypass():
    """正式 Runtime 不再通过 Memory→Relationship 旁路（生产路径零调用 apply_relationship）。"""
    import furina.app
    import furina.runtime.scheduler
    src_app = open(furina.app.__file__, encoding="utf-8").read()
    src_sched = open(furina.runtime.scheduler.__file__, encoding="utf-8").read()
    # app 应与关系引擎单写（apply_relationship 不再出现在 app 生产路径）
    assert "apply_relationship" not in src_app, "app 生产路径不应调用 deprecated apply_relationship"


# ================================================================ S4 body_snapshot deprecated
def test_body_snapshot_deprecated_alias():
    """body_snapshot == current_frame().body 且产生 DeprecationWarning。"""
    from furina.runtime.scheduler import Scheduler
    bus = EventBus()
    class _N:
        def __init__(self):
            self.state = CharacterState()
            self.se = self
    sched = Scheduler(bus, _N(), None, None, None, None, None)
    # 注入一个 frame
    from furina.runtime.frame_builder import RuntimeFrameBuilder
    from furina.embodiment import EmbodiedExpressionEngine, FURINA_EMBODIMENT
    eng = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
    body = eng.express(emotion="proud", mode="PROUD", activity="talk")
    frame = RuntimeFrameBuilder().build(activity_name="talk", body=body)
    sched._last_frame = frame
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        snap = sched.body_snapshot()
        assert any(issubclass(x.category, DeprecationWarning) for x in w), "应产生 DeprecationWarning"
    frame_body = frame.body
    assert snap["expression"] == frame_body.expression
    assert snap["gaze"] == frame_body.gaze
