"""Phase 13 终审 Batch C：§6 Activity 生命周期、§8 对话 FIFO + 运行时 apply 线程。"""
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
from furina.behavior import BehaviorMotivation
from furina.behavior.outcome import outcome_for, apply_outcome, OUTCOMES
from furina.life_brain import LifeDecision
from furina.runtime.scheduler import Scheduler


def _sched():
    se = StateEngine(EventBus())
    bus = EventBus()
    emo = EmotionEngine(se.state.emotion)
    mot = BehaviorMotivation()
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.emotion = emo
    sched.motivation = mot
    return sched, bus, se


# ================================================================ §6 Activity 生命周期
def test_activity_replacement_is_not_automatic_completion():
    """新决策替换旧活动：未到计划时长 → INTERRUPTED（success=False），不是自动 COMPLETED。"""
    sched, bus, se = _sched()
    sched._current_life_activity = "read"
    sched._activity_instance = {"activity": "read", "started_at": time.time(),
                                "planned_duration": 60.0, "instance_id": "read-1"}
    # 立即换成 sleep（elapsed≈0 < 60）→ interrupted
    d = LifeDecision(activity="sleep", duration=180, next_think_in=90, reason="困了")
    sched._apply_life_decision(d)
    fin = getattr(sched, "_last_activity_finish", {})
    assert fin.get("reason") == "interrupted_replaced", f"替换未完成不得记为 completed: {fin}"
    assert "instance_id" in sched._activity_instance, "新活动必须有实例 id"


def test_activity_completion_when_duration_elapsed():
    """实际运行时长 ≥ 计划时长 → COMPLETED（全额）。"""
    sched, bus, se = _sched()
    sched._current_life_activity = "rest"
    sched._activity_instance = {"activity": "rest", "started_at": time.time() - 120.0,
                                "planned_duration": 60.0, "instance_id": "rest-1"}
    d = LifeDecision(activity="wander", duration=30, next_think_in=60, reason="休息够了")
    sched._apply_life_decision(d)
    assert getattr(sched, "_last_activity_finish", {}).get("reason") == "completed", \
        "达到计划时长应 COMPLETED"


def test_interrupted_activity_not_full_reward():
    st_a = CharacterState(); st_a.needs.fatigue = 80.0
    ee_a = EmotionEngine(st_a.emotion)
    apply_outcome(st_a, "rest", ee_a, success=True)
    st_b = CharacterState(); st_b.needs.fatigue = 80.0
    ee_b = EmotionEngine(st_b.emotion)
    apply_outcome(st_b, "rest", ee_b, success=False)
    assert st_a.needs.fatigue < st_b.needs.fatigue, "完成的 rest 应比被打断的 rest 恢复更多疲劳"


def test_outcome_spec_not_shared_mutable():
    o1 = outcome_for("rest", success=True)
    o2 = outcome_for("rest", success=False)
    assert o1.success is True and o2.success is False, "每次调用必须是独立副本"
    assert OUTCOMES["rest"].success is True, "全局 spec 不得被 success=False 污染"


def test_social_need_not_double_applied():
    st = CharacterState(); st.needs.social_need = 60.0
    ee = EmotionEngine(st.emotion)
    before = st.needs.social_need
    apply_outcome(st, "approach_user", ee, recent_counts={})
    drop = before - st.needs.social_need
    # 单次 -40 × avail(0.72) ≈ -28.8；若双重结算会是 ~-57.6
    assert 20.0 <= drop <= 36.0, f"social_need 应恰好结算一次: drop={drop:.1f}"


def test_autonomous_social_activity_cannot_self_farm_relationship():
    from furina.memory.memory_types import RelationshipState
    st = CharacterState()
    rel = RelationshipState(trust=30.0, comfort=40.0, familiarity=20.0)
    ee = EmotionEngine(st.emotion)
    before = (rel.trust, rel.comfort, rel.familiarity)
    apply_outcome(st, "approach_user", ee, success=True, relationship=rel)
    apply_outcome(st, "talk", ee, success=True, relationship=rel)
    apply_outcome(st, "offer_help", ee, success=True, relationship=rel)
    after = (rel.trust, rel.comfort, rel.familiarity)
    assert after == before, f"自主社交活动不得自我农场关系: {before} -> {after}"


def test_activity_completion_exactly_once():
    """活动替换时结算恰好一次：_last_activity_finish 记录单个结局，不重复结算。"""
    sched, bus, se = _sched()
    sched._current_life_activity = "read"
    sched._activity_instance = {"activity": "read", "started_at": time.time() - 5.0,
                                "planned_duration": 60.0, "instance_id": "read-1"}
    d = LifeDecision(activity="sleep", duration=180, next_think_in=90, reason="困")
    sched._apply_life_decision(d)
    fin = getattr(sched, "_last_activity_finish", {})
    assert fin.get("activity") == "read", "结算对象是上一个活动"
    # 再决策同一个活动（continue 语义不应再结算）
    sched._current_life_activity = "sleep"
    sched._apply_life_decision(LifeDecision(activity="sleep", duration=180, next_think_in=90, reason="继续睡"))
    assert getattr(sched, "_last_activity_finish", {}).get("activity") == "read", \
        "同一活动延续不得重复结算"


def test_verified_help_can_emit_relationship_event_once():
    """已验证的 Agent 帮助 → EV_SUCCESSFUL_HELP 恰好一次；未验证不得发放。"""
    from types import SimpleNamespace
    bus = EventBus()
    se = StateEngine(bus)
    emo = EmotionEngine(se.state.emotion)
    applied = []
    rel = SimpleNamespace(apply=lambda ev, strength=1.0: applied.append(ev), state=None,
                          factors=lambda: {"trust": 0.5})
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.emotion = emo
    sched.relationship = rel
    # 未验证完成 → 不得发 EV_SUCCESSFUL_HELP
    sched._on_agent_done(SimpleNamespace(payload={"summary": "x", "verified": False}))
    assert applied == [], "未验证完成不得发放关系事件"
    # 已验证完成 → 恰好一次 EV_SUCCESSFUL_HELP
    sched._on_agent_done(SimpleNamespace(payload={"summary": "x", "verified": True}))
    assert len(applied) == 1 and applied[0] == "successful_help", f"已验证帮助应恰好一次: {applied}"


# ================================================================ §8 对话 FIFO + apply 线程
class _SlowLLM:
    """第一个调用慢、第二个快（复现 turn1 慢于 turn2 的竞态）。"""

    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    def structured(self, msgs, schema, temperature=0.9):
        self.calls += 1
        if self.calls == 1:
            time.sleep(0.25)   # turn1 慢
        return {"speech": f"回复{self.calls}"}


def test_two_fast_user_messages_preserve_reply_order():
    """turn1 模型比 turn2 慢时，history 仍必须是 user1→furina1→user2→furina2。"""
    from furina.dialogue_brain import DialogueBrain
    db = DialogueBrain(_SlowLLM(), persona="你是芙宁娜。")
    results = {}

    def _call(text, tag):
        out = db.say(intent="talk", user_text=text, user_initiated=True,
                     context="casual", user_present=True)
        results[tag] = out

    t1 = threading.Thread(target=_call, args=("第一句", "r1"))
    t2 = threading.Thread(target=_call, args=("第二句", "r2"))
    t1.start(); t2.start()
    t1.join(); t2.join()
    roles = [h["role"] for h in db._history]
    assert roles == ["user", "furina", "user", "furina"], f"history 必须串行: {roles}"
    texts = [h["text"] for h in db._history]
    assert texts == ["第一句", "回复1", "第二句", "回复2"], f"时序错乱: {texts}"


def test_brain_spoke_marshaled_to_runtime_apply_thread():
    """BRAIN_SPOKE 在 worker 线程 emit → 状态不得立刻改变；drain_apply() 后才落地。"""
    sched, bus, se = _sched()
    payload = SimpleNamespace(speech="你好呀", intent="talk", emotion="happy")
    bus.emit(EventType.BRAIN_SPOKE, payload=payload, source="worker")
    assert sched._speech == "", "worker emit 后不得立刻改状态（必须排队）"
    sched.drain_apply()
    assert sched._speech == "你好呀", "drain（owner 线程）后台词落地"


def test_agent_completion_marshaled_to_runtime_apply_thread():
    sched, bus, se = _sched()
    macro_before = se.state.life.macro.value
    bus.emit(EventType.AGENT_COMPLETED, payload={"summary": "打开了记事本"}, source="agent_worker")
    assert se.state.life.macro.value == macro_before, "worker emit 后不得立刻改状态（必须排队）"
    sched.drain_apply()
    assert se.state.life.macro.value == "idle", "drain（owner 线程）后宏状态落地为 idle"
