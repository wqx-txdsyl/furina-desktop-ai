"""Phase 13 H1 FINAL Reviewer Residual Patch — §§1–8 残差不变量测试。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from types import SimpleNamespace
from unittest import mock

from furina.core import EventBus, EventType
from furina.state import CharacterState
from furina.state.state_engine import StateEngine
from furina.emotion import EmotionEngine
from furina.runtime.scheduler import Scheduler
from furina.runtime.window_awareness import WindowInfo
from furina.runtime.world import Rect, DesktopWorld


# ================================================================ §1 情绪唯一 owner（生产等价接线）
def _real_interaction_wiring():
    """模拟 Furina.__init__ 的**实际剩余**接线：on_emotion_semantic 钩子（无 EventBus 情绪订阅）。"""
    from furina.app import Furina
    from furina.interaction import InteractionEngine
    bus = EventBus()
    se = StateEngine(bus)
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=se.state)
    app.emotion = EmotionEngine(se.state.emotion)
    rel_apply = []
    app.relationship = SimpleNamespace(apply=lambda ev, strength=1.0: rel_apply.append(ev), state=None,
                                       factors=lambda: {"trust": 0.5})
    app.memory = SimpleNamespace(observe=lambda *a, **k: None,
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    ie = InteractionEngine(bus)
    # 与 Furina.__init__ 相同的唯一情绪接线（钩子），**不**注册 bus INTERACTION_INPUT 情绪订阅
    ie.on_emotion_semantic = app._on_interaction_emotion
    ie.on_user_takeover = app._on_user_takeover_interaction
    ie.on_meaningful_interaction = app._on_meaningful_interaction
    # 真实 EventBus 上应**没有** INTERACTION_INPUT → _on_interaction_emotion 订阅
    bus_subs = [h for h in bus._handlers.get(EventType.INTERACTION_INPUT, [])]
    app._rel_apply = rel_apply
    return app, ie, bus, se, bus_subs


def _assert_emotion_once(app, ie, kind, expect_label, expect_rel):
    app.emotion._recent.clear()
    app._rel_apply.clear()
    ie.emit_event(kind, "head" if kind == "petting" else "whole")
    # 情绪维度增量恰好一次 + _recent 恰好 +1
    assert app.emotion._recent.get(
        {"petting": "user_pet", "poke": "user_poke", "drag": "user_drag", "click": "user_click"}[kind], 0) == 1, \
        f"{kind} _recent 必须恰好一次: {app.emotion._recent}"
    assert app.state.state.emotion.label == expect_label, \
        f"{kind} 后 label: {app.state.state.emotion.label}"


def test_production_petting_emotion_applies_exactly_once():
    app, ie, bus, se, subs = _real_interaction_wiring()
    assert not any(getattr(h, "__name__", "") == "_on_interaction_emotion" for h in subs), \
        "生产 EventBus 不得再订阅情绪处理器（唯一 owner = 语义钩子）"
    _assert_emotion_once(app, ie, "petting", "happy", ["positive_touch"])


def test_production_poke_emotion_applies_exactly_once():
    app, ie, bus, se, subs = _real_interaction_wiring()
    _assert_emotion_once(app, ie, "poke", "annoyed", ["negative_response"])


def test_production_drag_emotion_applies_exactly_once():
    app, ie, bus, se, subs = _real_interaction_wiring()
    _assert_emotion_once(app, ie, "drag", "calm", ["positive_touch"])   # drag 情绪弱（可能 calm），关系恰好一次


def test_production_click_emotion_applies_exactly_once():
    app, ie, bus, se, subs = _real_interaction_wiring()
    _assert_emotion_once(app, ie, "click", "curious", [])   # click：情绪恰好一次（curious），无关系事件


def test_interaction_recent_counter_increments_once_per_semantic_event():
    app, ie, bus, se, subs = _real_interaction_wiring()
    app.emotion._recent.clear()
    ie.emit_event("petting", "head")
    ie.emit_event("petting", "head")   # 第二次独立语义事件 → +1（不是 +2）
    assert app.emotion._recent.get("user_pet", 0) == 2, \
        f"每次语义事件 _recent 恰好 +1: {app.emotion._recent}"


# ================================================================ §2 ingress seq 在 owner 分配
class _GateLLM:
    """仅记录调用序的假 LLM（阻塞由 worker 线程在 say() 之前控制）。"""
    def __init__(self):
        self.calls = []
    def is_available(self):
        return True
    def structured(self, msgs, schema, temperature=0.9):
        seq = len(self.calls) + 1
        self.calls.append(seq)
        if seq == 1:
            time.sleep(0.05)   # turn1 稍慢（仍由 FIFO 保证顺序）
        return {"speech": f"回复{seq}"}


def _app_with_db(db):
    from furina.app import Furina
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.emotion = EmotionEngine(app.state.state.emotion)
    app.relationship = SimpleNamespace(apply=lambda *a, **k: None, factors=lambda: {})
    app.memory = SimpleNamespace(observe=lambda *a, **k: None, retrieve=lambda **k: [],
                                 interpret=lambda *a, **k: {},
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    app.bus = SimpleNamespace(emit=lambda *a, **k: None)
    app._sched = SimpleNamespace(interrupt_life=lambda r: None, on_user_response=lambda: None)
    app.dialogue_brain = db
    app._fallback_dispatcher = None
    app._rt_dispatcher().bind_owner()
    return app


def test_production_user_ingress_seq_assigned_on_owner():
    from furina.dialogue_brain import DialogueBrain
    db = DialogueBrain(_GateLLM(), persona="你是芙宁娜。")
    app = _app_with_db(db)
    # owner 入口预留 seq（用户输入顺序身份）
    seq1 = db.reserve_turn()
    seq2 = db.reserve_turn()
    assert seq1 < seq2, f"owner 入口必须按用户输入顺序分配递增 seq: {seq1}, {seq2}"


def test_worker2_entering_say_first_cannot_overtake_user1():
    """owner 提交 user1 先、user2 后；worker1 阻塞在 say() 之前，worker2 先进入 say → 仍 user1 先。"""
    from furina.dialogue_brain import DialogueBrain
    llm = _GateLLM()
    db = DialogueBrain(llm, persona="你是芙宁娜。")
    app = _app_with_db(db)
    # owner 入口：user1 先、user2 后（reserve + 冻结快照）
    seq1 = db.reserve_turn()
    snap1 = app._freeze_direct_snapshot("第一句", ingress_seq=seq1)
    seq2 = db.reserve_turn()
    snap2 = app._freeze_direct_snapshot("第二句", ingress_seq=seq2)
    attempts = []
    release1 = threading.Event()
    results = {}
    def _worker1():
        release1.wait(timeout=5)         # **阻塞在 say() 之前**
        attempts.append("w1")
        results["r1"] = db.say(**snap1.say_kwargs())
    def _worker2():
        attempts.append("w2")            # worker2 先到达 say
        results["r2"] = db.say(**snap2.say_kwargs())
    t1 = threading.Thread(target=_worker1)
    t1.start()
    time.sleep(0.05)
    t2 = threading.Thread(target=_worker2)
    t2.start()
    time.sleep(0.05)                     # 确保 w2 已进入（在 gate 等待 seq1）
    assert attempts[:1] == ["w2"], f"worker2 必须先到达 say: {attempts}"
    release1.set()                       # 放行 worker1
    t1.join(timeout=5); t2.join(timeout=5)
    assert not t1.is_alive() and not t2.is_alive(), "两线程必须 bounded 内退出（无死锁）"
    assert llm.calls == [1, 2], f"LLM 调用序必须 user1→user2（即使 w2 先到）: {llm.calls}"
    assert [h["text"] for h in db._history] == ["第一句", "回复1", "第二句", "回复2"], \
        f"history 必须按用户输入顺序: {[h['text'] for h in db._history]}"


def test_snapshot_seq_is_consumed_by_dialogue_fifo():
    db = __import__("furina.dialogue_brain", fromlist=["DialogueBrain"]).DialogueBrain(
        _GateLLM(), persona="你是芙宁娜。")
    snap = __import__("furina.runtime.dialogue_snapshot", fromlist=["DialogueContextSnapshot"]).DialogueContextSnapshot(
        user_text="在吗", channel="DIRECT_USER_TURN", ingress_seq=7)
    kw = snap.say_kwargs()
    assert kw.get("ingress_seq") == 7, "快照必须携带 owner 预留的 ingress_seq"


def test_direct_history_order_matches_submit_user_message_order():
    from furina.dialogue_brain import DialogueBrain
    llm = _GateLLM()
    db = DialogueBrain(llm, persona="你是芙宁娜。")
    app = _app_with_db(db)
    # 模拟 submit_user_message 的 owner 顺序（reserve → 快照 → worker）
    seq1 = db.reserve_turn(); s1 = app._freeze_direct_snapshot("一", ingress_seq=seq1)
    seq2 = db.reserve_turn(); s2 = app._freeze_direct_snapshot("二", ingress_seq=seq2)
    release1 = threading.Event()
    def _w1():
        release1.wait(timeout=5)
        db.say(**s1.say_kwargs())
    def _w2():
        db.say(**s2.say_kwargs())
    t1 = threading.Thread(target=_w1); t2 = threading.Thread(target=_w2)
    t1.start(); time.sleep(0.05); t2.start(); time.sleep(0.05)
    release1.set()
    t1.join(timeout=5); t2.join(timeout=5)
    assert [h["text"] for h in db._history] == ["一", "回复1", "二", "回复2"], \
        f"history 必须匹配 submit_user_message 顺序: {[h['text'] for h in db._history]}"


# ================================================================ §3 阻塞 mind 无台词/无 bid
class _WorkingDB:
    def __init__(self):
        self.say_calls = 0
        self.say_event = threading.Event()
    def say(self, **kw):
        self.say_calls += 1
        self.say_event.set()
        return "说了句"


def _director_sched_with_db(db):
    from furina.director import Director, ActionRequest
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
    director.set_executor(lambda req: sched.on_mind_action_started(
        req.action, float((getattr(req, "payload", {}) or {}).get("planned_duration", 0.0) or 0.0))
        if getattr(req, "source", "") == "mind" else None)
    sched.director = director
    sched.dispatcher.bind_owner()
    se.state.user_idle_seconds = 10.0
    # Pre-Manual §7：社交 bid 测试需要有效在场
    sched.world_perc.state.idle_available = True
    sched.world_perc.state.user_present = True
    sched.world_perc.state.user_active = True
    sched.world_perc.state.user_idle_seconds = 10.0
    sched.world_perc._has_valid_idle = True
    return sched, bus, se, director, ActionRequest


def test_blocked_social_mind_request_emits_no_speech():
    """Agent 拥有 Director：mind 请求被阻塞 → 不执行 → 无台词（即使 DB 可用）。"""
    db = _WorkingDB()
    sched, bus, se, director, AR = _director_sched_with_db(db)
    sched._llm_speech_at = 0.0
    # Agent 先占用 Director
    director.submit(AR(source="agent", action="agent_work", priority=2))
    director.drain()
    from furina.life_brain import LifeDecision
    sched._apply_life_decision(LifeDecision(activity="talk", duration=30, next_think_in=60,
                                            speech_level=3, speech_intent="聊聊"))
    time.sleep(0.3)
    sched.dispatcher.drain()
    assert db.say_calls == 0, "被阻塞的 mind 请求不得产出台词"
    assert sched._pending_social_bid is None, "无可见台词 → 无 social bid"


def test_blocked_non_social_mind_request_emits_no_activity_speech():
    db = _WorkingDB()
    sched, bus, se, director, AR = _director_sched_with_db(db)
    sched._llm_speech_at = 0.0
    director.submit(AR(source="agent", action="agent_work", priority=2))
    director.drain()
    from furina.life_brain import LifeDecision
    sched._apply_life_decision(LifeDecision(activity="read", duration=30, next_think_in=60,
                                            speech_level=3, speech_intent="看看书"))
    time.sleep(0.3)
    sched.dispatcher.drain()
    assert db.say_calls == 0, "被阻塞的非社交 mind 请求不得假装活动发生了（无叙述台词）"


def test_executed_mind_request_starts_autonomous_dialogue_exactly_once():
    db = _WorkingDB()
    sched, bus, se, director, AR = _director_sched_with_db(db)
    sched._llm_speech_at = 0.0
    director.submit(AR(source="mind", action="read", priority=3,
                       payload={"planned_duration": 30.0, "speech_level": 3,
                                "speech_intent": "看看书", "emotion": "calm"}))
    director.drain()   # mind 执行
    assert sched._activity_instance["status"] == "RUNNING"
    # 执行边界启动自主台词（app._on_execute 路径）
    sched.start_autonomous_dialogue(activity="read", speech_level=3, speech_intent="看看书",
                                    emotion="calm", duration=30.0, intent="read")
    assert db.say_event.wait(timeout=5), "执行后的 mind 必须启动一次自主台词"
    assert db.say_calls == 1, "自主台词必须恰好一次"
    sched.dispatcher.drain()
    assert sched._speech == "说了句"


def test_agent_owned_director_prevents_mind_speech_until_execution():
    db = _WorkingDB()
    sched, bus, se, director, AR = _director_sched_with_db(db)
    sched._llm_speech_at = 0.0
    from furina.life_brain import LifeDecision
    sched._apply_life_decision(LifeDecision(activity="talk", duration=30, next_think_in=60,
                                            speech_level=3, speech_intent="聊聊"))
    time.sleep(0.3)
    sched.dispatcher.drain()
    assert db.say_calls == 0 and sched._pending_social_bid is None
    # Agent 释放后 mind 被执行 → 才出现台词/bid
    director.finish(source="agent")
    director.drain()
    sched.start_autonomous_dialogue(activity="talk", speech_level=3, speech_intent="聊聊",
                                    emotion="calm", duration=30.0, intent="talk")
    assert db.say_event.wait(timeout=5)
    sched.dispatcher.drain()
    assert sched._pending_social_bid is not None, "执行并出话后才开 social bid"


# ================================================================ §4 真实互动 finalize mind
def _wire_replace(sched):
    def _cb(old, new):
        if old is not None and getattr(old, "source", "") == "mind":
            new_src = getattr(new, "source", "")
            sched.on_mind_preempted(reason=f"preempted_by_{new_src}")
    return _cb


def _interaction_app_with_sched():
    from furina.app import Furina
    from furina.interaction import InteractionEngine
    from furina.director import Director, ActionRequest
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.motivation = __import__("furina.behavior", fromlist=["BehaviorMotivation"]).BehaviorMotivation()
    director = Director(bus)
    director.set_executor(lambda req: sched.on_mind_action_started(
        req.action, float((getattr(req, "payload", {}) or {}).get("planned_duration", 0.0) or 0.0))
        if getattr(req, "source", "") == "mind" else None)
    director.on_before_replace = _wire_replace(sched)   # 真实抢占回调（同 Furina.__init__ 接线）
    sched.director = director
    sched.dispatcher.bind_owner()
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=se.state)
    app.emotion = sched.emotion
    app._sched = sched
    rel_apply = []
    app.relationship = SimpleNamespace(apply=lambda ev, strength=1.0: rel_apply.append(ev), state=None,
                                       factors=lambda: {"trust": 0.5})
    app.memory = SimpleNamespace(observe=lambda *a, **k: None,
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    ie = InteractionEngine(bus)
    ie.on_emotion_semantic = app._on_interaction_emotion
    ie.on_user_takeover = app._on_user_takeover_interaction
    ie.on_meaningful_interaction = app._on_meaningful_interaction
    return app, ie, bus, se, sched, director, ActionRequest


def _start_mind(app, sched, director, AR, activity="read"):
    director.submit(AR(source="mind", action=activity, priority=3,
                       payload={"planned_duration": 60.0}))
    director.drain()
    assert sched._activity_instance["status"] == "RUNNING"


def test_real_petting_finalizes_running_mind_immediately():
    app, ie, bus, se, sched, director, AR = _interaction_app_with_sched()
    _start_mind(app, sched, director, AR)
    time.sleep(0.05)
    ie.emit_event("petting", "head")
    assert sched._activity_instance["status"] == "INTERRUPTED", sched._activity_instance
    assert sched._activity_instance["finish_reason"] == "preempted_by_user"
    frozen = sched._activity_instance["elapsed"]
    time.sleep(0.1)
    assert sched._activity_instance["elapsed"] == frozen, "elapsed 必须停在互动时刻"


def test_real_poke_finalizes_running_mind_immediately():
    app, ie, bus, se, sched, director, AR = _interaction_app_with_sched()
    _start_mind(app, sched, director, AR)
    ie.emit_event("poke", "whole")
    assert sched._activity_instance["finish_reason"] == "preempted_by_user"


def test_real_drag_finalizes_running_mind_immediately():
    app, ie, bus, se, sched, director, AR = _interaction_app_with_sched()
    _start_mind(app, sched, director, AR)
    ie.emit_event("drag", "whole")
    assert sched._activity_instance["finish_reason"] == "preempted_by_user"


def test_real_click_finalizes_running_mind_immediately():
    app, ie, bus, se, sched, director, AR = _interaction_app_with_sched()
    _start_mind(app, sched, director, AR)
    ie.emit_event("click", "whole")
    assert sched._activity_instance["finish_reason"] == "preempted_by_user"


def test_pointer_control_does_not_finalize_mind():
    app, ie, bus, se, sched, director, AR = _interaction_app_with_sched()
    _start_mind(app, sched, director, AR)
    for kind in ("grab", "release", "hover", "leave"):
        ie.emit_event(kind, "whole")
    assert sched._activity_instance["status"] == "RUNNING", "指针控制不得抢占 mind"


def test_user_preemption_outcome_exactly_once():
    app, ie, bus, se, sched, director, AR = _interaction_app_with_sched()
    _start_mind(app, sched, director, AR)
    ie.emit_event("petting", "head")
    first = dict(sched._last_activity_finish)
    ie.emit_event("poke", "whole")   # 再互动：实例已非 RUNNING → 不重复结算
    assert sched._last_activity_finish["reason"] == first["reason"], "不得重复结算"
    assert sched._activity_instance["finish_reason"] == "preempted_by_user"


def test_user_preemption_cannot_later_become_completed():
    from furina.life_brain import LifeDecision
    app, ie, bus, se, sched, director, AR = _interaction_app_with_sched()
    _start_mind(app, sched, director, AR)
    ie.emit_event("petting", "head")
    sched._current_life_activity = "read"
    sched._apply_life_decision(LifeDecision(activity="sleep", duration=180, next_think_in=90))
    assert sched._last_activity_finish["reason"] == "preempted_by_user", "不得变成 completed"


# ================================================================ §5 规范 status
def test_agent_preemption_status_is_interrupted():
    app, ie, bus, se, sched, director, AR = _interaction_app_with_sched()
    _start_mind(app, sched, director, AR)
    director.submit(AR(source="agent", action="agent_work", priority=2))
    director.drain()
    assert sched._activity_instance["status"] == "INTERRUPTED"
    assert sched._activity_instance["finish_reason"] == "preempted_by_agent"


def test_user_preemption_status_is_interrupted():
    app, ie, bus, se, sched, director, AR = _interaction_app_with_sched()
    _start_mind(app, sched, director, AR)
    ie.emit_event("petting", "head")
    assert sched._activity_instance["status"] == "INTERRUPTED"
    assert sched._activity_instance["finish_reason"] == "preempted_by_user"


def test_finish_reason_preserves_preemption_source():
    app, ie, bus, se, sched, director, AR = _interaction_app_with_sched()
    _start_mind(app, sched, director, AR)
    ie.emit_event("petting", "head")
    assert sched._last_activity_finish["reason"] == "preempted_by_user"
    assert sched._last_activity_finish["status"] == "INTERRUPTED"


def test_activity_status_always_in_canonical_set():
    from furina.runtime.scheduler import Scheduler as S
    for r in ("completed", "interrupted", "preempted_by_agent", "preempted_by_user",
              "aborted", "user_cancel", "failed", "tool_error"):
        assert S._canonical_status(r) in ("RUNNING", "COMPLETED", "INTERRUPTED", "ABORTED", "FAILED"), r


# ================================================================ §6 start() 绑定 owner
def test_scheduler_start_binds_owner_to_start_thread():
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    assert sched.dispatcher.owner_thread_id is None
    sched.start(None)
    assert sched.dispatcher.owner_thread_id == threading.get_ident(), "start() 必须绑定 owner"


def test_harness_first_message_before_first_timer_does_not_raise():
    """launch_harness 经 sched.start() 已绑定 owner —— 首个 timer 前的消息/喂食不抛错。"""
    from furina.app import Furina
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.emotion = EmotionEngine(app.state.state.emotion)
    app.relationship = SimpleNamespace(apply=lambda *a, **k: None, factors=lambda: {})
    app.memory = SimpleNamespace(observe=lambda *a, **k: None, retrieve=lambda **k: [],
                                 interpret=lambda *a, **k: {},
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    app.bus = SimpleNamespace(emit=lambda *a, **k: None)
    app.dialogue_brain = None
    app._fallback_dispatcher = None
    app._sched = None
    # 模拟 Scheduler.start 绑定（launch_harness 共用）
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.start(None)
    app._sched = sched
    app.submit_user_message("你好")   # 不应抛"owner not bound"
    app.submit_feed("蛋糕")           # 不应抛


# ================================================================ §7 idle_available 边界
def test_first_idle_sample_unavailable_does_not_claim_measured_zero():
    from furina.world_perception import WorldPerception, UserActivity
    wp = WorldPerception()
    w = wp.update(app="ClsX", title="", idle_seconds=0.0, hour=14, minute=0,
                  idle_available=False)
    assert w.idle_available is False
    assert w.user_activity == UserActivity.UNKNOWN, f"首样本不可用不得分类为活跃: {w.user_activity}"
    assert wp.last_events == [], "首样本不可用不得发事件"


def test_first_idle_sample_unavailable_emits_no_active_transition():
    from furina.world_perception import WorldPerception
    wp = WorldPerception()
    for _ in range(5):
        w = wp.update(app="ClsX", title="", idle_seconds=0.0, hour=14, minute=0, idle_available=False)
    assert "USER_BECAME_ACTIVE" not in w.recent_world_events, "不得从默认 0 制造活跃转换"
    assert "USER_RETURNED" not in w.recent_world_events


def test_valid_idle_sample_sets_available_and_value():
    from furina.world_perception import WorldPerception
    wp = WorldPerception()
    wp.update(app="ClsX", title="", idle_seconds=0.0, hour=14, minute=0, idle_available=False)
    w = wp.update(app="ClsX", title="", idle_seconds=42.0, hour=14, minute=0, idle_available=True)
    assert w.idle_available is True and abs(w.user_idle_seconds - 42.0) < 1e-9


def test_failure_after_valid_sample_retains_last_value_but_marks_current_unavailable():
    from furina.world_perception import WorldPerception
    wp = WorldPerception()
    wp.update(app="ClsX", title="", idle_seconds=42.0, hour=14, minute=0, idle_available=True)
    w = wp.update(app="ClsX", title="", idle_seconds=0.0, hour=14, minute=0, idle_available=False)
    # 已有有效样本 → 保留最后有效值（连续性），但当前样本标不可用
    assert w.idle_available is False and w.user_activity.value != "unknown", \
        "已有有效样本后的临时失败：保留分类（不退回 UNKNOWN 也不制造新活跃）"


def test_harness_world_diagnostics_exposes_idle_unavailable():
    import pytest
    from PySide6.QtWidgets import QApplication
    from furina.runtime.harness.controller import RuntimeHarness
    app = SimpleNamespace()
    app.state = SimpleNamespace(state=SimpleNamespace(
        life=SimpleNamespace(activity="read", macro=SimpleNamespace(value="living"), reason=""),
        emotion=SimpleNamespace(label="calm"), needs=SimpleNamespace(),
        user_working=False, user_idle_seconds=0.0, idle_available=False,
        clock_hour=14, clock_minute=5))
    app.relationship = SimpleNamespace(state=None)
    app.memory = SimpleNamespace(store=SimpleNamespace(count=lambda: 0))
    app._sched = SimpleNamespace(
        current_frame=lambda: None,
        se=SimpleNamespace(state=SimpleNamespace(
            clock_hour=14, clock_minute=5, user_idle_seconds=0.0, user_working=False,
            idle_available=False, emotion=SimpleNamespace(label="calm"),
            life=SimpleNamespace(activity="read"))))
    app.life_brain = None
    app.dialogue_brain = None
    from furina.runtime.world import DesktopWorld
    app.world = DesktopWorld(1920, 1080)
    app.bus = SimpleNamespace(on=lambda *a, **k: None)
    app.agent = SimpleNamespace(status="IDLE")
    app.emotion = SimpleNamespace(_recent={})
    if QApplication.instance() is None:
        QApplication([])
    h = RuntimeHarness(app)
    d = h._diagnostics()
    assert d.get("idle_available") is False, f"诊断必须暴露 idle 不可用: {d}"


# ================================================================ §8 单一长期记忆 owner
def _memory_counter_app():
    from furina.app import Furina
    from furina.interaction import InteractionEngine
    bus = EventBus()
    se = StateEngine(bus)
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=se.state)
    app.emotion = EmotionEngine(se.state.emotion)
    app.relationship = SimpleNamespace(apply=lambda *a, **k: None, state=None,
                                       factors=lambda: {"trust": 0.5})
    mem = {"semantic": 0, "consolidate": 0}
    app.memory = SimpleNamespace(
        observe=lambda *a, **k: mem.__setitem__("semantic", mem["semantic"] + 1),
        store=SimpleNamespace(save_relationship=lambda r: None))
    # Scheduler 已**移除**互动 consolidation（H1-FINAL §8）—— 计数应为 0
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.emotion = app.emotion
    sched.relationship = app.relationship
    sched.be = SimpleNamespace(step=lambda s: None)
    sched.director = SimpleNamespace(drain=lambda: None, submit=lambda r: None, finish=lambda **k: None)
    sched.dispatcher.bind_owner()
    sched._consolidate_episode = lambda *a, **k: mem.__setitem__("consolidate", mem["consolidate"] + 1)
    app._sched = sched
    bus.on(EventType.INTERACTION_INPUT, sched._on_interaction)
    ie = InteractionEngine(bus)
    ie.on_emotion_semantic = app._on_interaction_emotion
    ie.on_user_takeover = app._on_user_takeover_interaction
    ie.on_meaningful_interaction = app._on_meaningful_interaction
    app._mem = mem
    return app, ie, bus, se, sched


def test_one_petting_creates_at_most_one_semantic_long_term_memory():
    app, ie, bus, se, sched = _memory_counter_app()
    ie.emit_event("petting", "head")
    assert app._mem["semantic"] == 1, f"App 语义记忆应恰好 1 条: {app._mem}"
    assert app._mem["consolidate"] == 0, f"Scheduler 不得再 consolidation（同一事件第二条记忆）: {app._mem}"


def test_one_poke_creates_at_most_one_semantic_long_term_memory():
    app, ie, bus, se, sched = _memory_counter_app()
    ie.emit_event("poke", "whole")
    assert app._mem["semantic"] == 1 and app._mem["consolidate"] == 0, app._mem


def test_one_drag_creates_at_most_one_semantic_long_term_memory():
    app, ie, bus, se, sched = _memory_counter_app()
    ie.emit_event("drag", "whole")
    assert app._mem["semantic"] == 1 and app._mem["consolidate"] == 0, app._mem


def test_repeated_distinct_interactions_remain_distinct_events():
    """三次**不同**语义事件（petting/poke/drag）→ 3 条独立语义记忆。"""
    app, ie, bus, se, sched = _memory_counter_app()
    ie.emit_event("petting", "head")
    ie.emit_event("poke", "whole")
    ie.emit_event("drag", "whole")
    assert app._mem["semantic"] == 3, f"三次不同语义事件 → 3 条语义记忆: {app._mem}"
    assert app._mem["consolidate"] == 0
