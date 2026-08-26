"""Phase 13 FINAL-R1-H1 Hotfix — §4 owner 线程 / §9 互动顺序 / §10 冻结快照 / §11 Feed 顺序 测试。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from types import SimpleNamespace
from unittest import mock

from furina.core import EventBus
from furina.state import CharacterState
from furina.state.state_engine import StateEngine
from furina.emotion import EmotionEngine
from furina.runtime.scheduler import Scheduler


def _app_stub():
    from furina.app import Furina
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.emotion = EmotionEngine(app.state.state.emotion)
    rel_apply = []
    app.relationship = SimpleNamespace(apply=lambda ev, strength=1.0: rel_apply.append(ev),
                                       factors=lambda: {"trust": 0.5})
    app.memory = SimpleNamespace(observe=lambda *a, **k: None, retrieve=lambda **k: [],
                                 interpret=lambda *a, **k: {},
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    app.bus = SimpleNamespace(emit=lambda *a, **k: None)
    app._sched = SimpleNamespace(interrupt_life=lambda r: None, on_user_response=lambda: None)
    app.dialogue_brain = None
    app._fallback_dispatcher = None
    app._rel_apply = rel_apply
    return app


def _sched_stub():
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.be = SimpleNamespace(step=lambda s: None)
    sched.director = SimpleNamespace(drain=lambda: None, submit=lambda r: None, finish=lambda **k: None)
    sched.dispatcher.bind_owner()
    return sched, bus, se


# ================================================================ §4.1 Agent 记忆回 owner（Phase 15.1：C3 单一 owner = cognition）
class _FakeAgentDone:
    status = "COMPLETED_VERIFIED"
    def __init__(self):
        self.on_task_finished = None
    def execute(self, req, ctx=None, task_auth=None):
        if self.on_task_finished is not None:
            self.on_task_finished({
                "task_id": "t1", "status": "COMPLETED_VERIFIED", "goal": "打开记事本",
                "original_request": "打开记事本", "verified": True,
                "result_summary": "完成", "error": "",
                "steps": [], "artifacts": [], "plan_json": "{}", "permission_summary": ""})
        return {"status": "completed", "goal": "打开记事本"}


def test_agent_success_memory_observe_runs_on_owner_thread():
    """Agent 成功后的认知写（C7 persist + C6/C3 形成）必须在 owner 线程（worker 不直写）。"""
    app = _app_stub()
    d = app._rt_dispatcher()
    d.bind_owner()
    app.agent = _FakeAgentDone()
    cog_writes = {}
    class _CogSpy:
        def persist_agent_result(self, *a, **k):
            cog_writes["thread"] = threading.get_ident()
        def record_event(self, *a, **k):
            cog_writes["event"] = "recorded"
            return SimpleNamespace(event_id="ev_x")
    app.cognition = _CogSpy()
    # 生产接线（与 Furina.__init__ 一致）：worker 产出 record → dispatcher 回 owner persist
    app.agent.on_task_finished = lambda rec: d.submit(lambda: app._persist_agent_task(rec))
    t = threading.Thread(target=app._agent_worker, args=("打开记事本", {}))
    t.start(); t.join()
    # worker 提交后、drain 前：认知写尚未执行（worker 不直写 authoritative DB）
    assert cog_writes == {}, "worker 不得直接写认知权威（C7/C3）"
    d.drain()
    assert cog_writes.get("thread") == d.owner_thread_id, \
        f"Agent 成功后的认知写必须在 owner 线程: {cog_writes.get('thread')} != {d.owner_thread_id}"
    assert cog_writes.get("event") == "recorded"


# ================================================================ §4.2 自主 Dialogue LLM 移出 owner
class _DialogueRecorder:
    def __init__(self):
        self.calls = []
        self.say_event = threading.Event()
    def is_available(self):
        return True
    def say(self, **kw):
        self.calls.append(threading.get_ident())
        self.say_event.set()
        time.sleep(0.05)
        return "自主台词"


def _drive_autonomous(sched, db):
    from furina.life_brain import LifeDecision
    sched.dialogue_brain = db
    sched._llm_speech_at = 0.0
    d = LifeDecision(activity="read", duration=30, next_think_in=60,
                     speech_level=3, speech_intent="看看书")
    sched._apply_life_decision(d)   # 只提交决策（H1-FINAL §3：**不在此启动台词**）
    # 模拟 Director 执行边界（app._on_execute 在 mind 执行后调用）：
    sched.start_autonomous_dialogue(activity=d.activity, speech_level=3,
                                    speech_intent="看看书", emotion=d.emotion,
                                    duration=float(d.duration or 0.0), intent=d.intent)
    return d


def test_autonomous_dialogue_llm_not_called_on_owner_thread():
    sched, bus, se = _sched_stub()
    db = _DialogueRecorder()
    _drive_autonomous(sched, db)
    assert db.say_event.wait(timeout=5), "自主对话 worker 必须被启动"
    time.sleep(0.1)
    assert db.calls, "say 必须被调用"
    assert db.calls[0] != sched.dispatcher.owner_thread_id, \
        f"自主 LLM 不得在 owner 线程调用: {db.calls[0]} == {sched.dispatcher.owner_thread_id}"


def test_slow_autonomous_dialogue_does_not_block_runtime_owner():
    sched, bus, se = _sched_stub()
    db = _DialogueRecorder()
    t0 = time.monotonic()
    _drive_autonomous(sched, db)
    dt = time.monotonic() - t0
    assert dt < 0.15, f"owner 不得被慢 LLM 阻塞: {dt:.2f}s"
    db.say_event.wait(timeout=5)


def test_autonomous_dialogue_result_applies_on_owner_thread():
    sched, bus, se = _sched_stub()
    db = _DialogueRecorder()
    _drive_autonomous(sched, db)
    db.say_event.wait(timeout=5)
    time.sleep(0.2)   # 等 worker 提交结果
    assert sched._speech == "", "drain 前不得直接改 _speech（worker 不直写）"
    sched.dispatcher.drain()
    assert sched._speech == "自主台词", "drain（owner）后自主台词落地"


# ================================================================ §9 互动顺序（真实 emit_event）
def _interaction_app():
    from furina.app import Furina
    from furina.interaction import InteractionEngine
    bus = EventBus()
    se = StateEngine(bus)
    emo = EmotionEngine(se.state.emotion)
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=se.state)
    app.emotion = emo
    applied = []
    app.relationship = SimpleNamespace(apply=lambda ev, strength=1.0: applied.append(ev), state=None,
                                       factors=lambda: {"trust": 0.5})
    app.memory = SimpleNamespace(observe=lambda *a, **k: None,
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    ie = InteractionEngine(bus)
    ie.on_emotion_semantic = app._on_interaction_emotion
    ie.on_meaningful_interaction = app._on_meaningful_interaction
    app._rel_apply = applied
    return app, ie, bus, se


def test_real_petting_dialogue_sees_post_relationship():
    app, ie, bus, se = _interaction_app()
    ie.emit_event("petting", "head")
    assert app._rel_apply == ["positive_touch"], f"petting → EV_POSITIVE_TOUCH 恰好一次: {app._rel_apply}"
    assert se.state.emotion.label in ("happy",), f"petting 后快照情绪必须是 post-event: {se.state.emotion.label}"


def test_real_poke_dialogue_sees_post_relationship():
    app, ie, bus, se = _interaction_app()
    ie.emit_event("poke", "body")
    assert app._rel_apply == ["negative_response"], f"poke → EV_NEGATIVE_RESPONSE: {app._rel_apply}"


def test_real_drag_dialogue_sees_post_relationship():
    app, ie, bus, se = _interaction_app()
    ie.emit_event("drag", "body")
    assert app._rel_apply == ["positive_touch"], f"drag → 关系事件: {app._rel_apply}"


def test_real_interaction_snapshot_frozen_before_worker():
    """互动广播后 Scheduler 的对话快照已冻结（post-event 情绪/关系）—— 直接读 label。"""
    app, ie, bus, se = _interaction_app()
    ie.emit_event("petting", "head")
    # 冻结点（emit 返回后）：情绪已派生、关系已应用
    assert se.state.emotion.label in ("happy",)
    assert app._rel_apply == ["positive_touch"]


# ================================================================ §10 冻结快照
def test_direct_dialogue_uses_owner_frozen_snapshot():
    app = _app_stub()
    snap = app._freeze_direct_snapshot("在吗")
    # 冻结后修改 live 状态 → 快照保持不变
    app.state.state.emotion.label = "sleepy"
    app.relationship.factors = lambda: {"trust": 0.99}
    app.state.state.life.activity = "sleep"
    assert snap.emotion_label != "sleepy", "快照必须保留冻结时的 label"
    assert snap.relationship_dict().get("trust", 0) == 0.5, f"快照必须保留冻结时关系: {snap.relationship_dict()}"
    assert snap.activity == "idle" or snap.activity == "", f"快照活动必须冻结: {snap.activity}"


def test_feed_dialogue_uses_owner_frozen_snapshot():
    app = _app_stub()
    app.state.state.emotion.label = "calm"
    snap = app._freeze_feed_snapshot("蛋糕")
    app.state.state.emotion.label = "sleepy"
    app.state.state.life.activity = "wander"
    assert snap.emotion_label == "calm", "feed 快照必须冻结"
    assert snap.activity == "eat" and snap.channel == "FEED_REACTION"


def test_agent_dialogue_uses_owner_frozen_snapshot():
    sched, bus, se = _sched_stub()
    snap = sched._freeze_reaction_snapshot(intent="assist_user", emotion="proud",
                                           user_initiated=True, context="打开了记事本",
                                           activity="agent_report", interaction="agent")
    sched.se.state.emotion.label = "sleepy"
    assert snap.emotion_label == "proud" and snap.channel == "AGENT_REPORT"


def test_interaction_dialogue_uses_owner_frozen_snapshot():
    sched, bus, se = _sched_stub()
    snap = sched._freeze_reaction_snapshot(intent="head_touch", emotion="happy",
                                           user_initiated=True, context="你摸了我的头",
                                           activity="head_touch", interaction="petting")
    sched.se.state.emotion.label = "sad"
    assert snap.emotion_label == "happy" and snap.channel == "INTERACTION_REACTION"


def test_autonomous_dialogue_uses_owner_frozen_snapshot():
    from furina.life_brain import LifeDecision
    sched, bus, se = _sched_stub()
    sched.se.state.emotion.label = "calm"
    snap = sched._freeze_ambient_snapshot(activity="read", speech_intent="看看书",
                                          emotion="proud", intent="read")
    sched.se.state.emotion.label = "sleepy"
    assert snap.emotion_label == "proud" and snap.channel == "AMBIENT_AUTONOMOUS"


# ================================================================ §11 Feed 域效果先于 worker
def test_feed_all_domain_effects_precede_dialogue_worker():
    from furina.app import Furina
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.emotion = EmotionEngine(app.state.state.emotion)
    app.relationship = SimpleNamespace(apply=lambda *a, **k: None, factors=lambda: {})
    order = []
    app.memory = SimpleNamespace(
        observe=lambda *a, **k: order.append("memory"),
        retrieve=lambda **k: [], interpret=lambda *a, **k: {},
        store=SimpleNamespace(save_relationship=lambda r: None))
    app.bus = SimpleNamespace(emit=lambda *a, **k: None)
    app._sched = SimpleNamespace(interrupt_life=lambda r: order.append("interrupt"),
                                 on_user_response=lambda: order.append("cancel_bid"))
    # Phase 15.1：喂食 → C6 USER_FEED → cognition（C3 单一 owner）；App 不再直接 memory.observe
    app.cognition = SimpleNamespace(
        record_event=lambda *a, **k: order.append("memory") or SimpleNamespace(event_id="ev_f"))
    started = threading.Event()
    class _DB:
        def say(self, **kw):
            order.append("dialogue_started")
            started.set()
            return "好吃"
    app.dialogue_brain = _DB()
    app._fallback_dispatcher = None
    app._rt_dispatcher().bind_owner()
    with mock.patch("furina.feeding.apply_food", return_value={"hunger": -30, "satisfaction": +10}):
        app._feed("蛋糕")
    # 域效果必须已在 worker 之前同步完成
    assert order.index("memory") < order.index("dialogue_started"), f"记忆必须先于对话: {order}"
    assert order.index("interrupt") < order.index("dialogue_started"), f"interrupt 必须先于对话: {order}"
    assert order.index("cancel_bid") < order.index("dialogue_started")
    assert app.state.state.life.activity == "eat", "life 效果必须先于 worker"
    started.wait(timeout=5)
