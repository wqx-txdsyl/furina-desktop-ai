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


# ================================================================ §6/FINAL-R1 §5 Activity 生命周期
def _start_mind(sched, activity, planned=60.0, elapsed_ago=0.0):
    """模拟 Director 实际执行：先提交决策，再 on_mind_action_started 启动实例（FINAL-R1 §5）。"""
    sched._current_life_activity = activity
    sched._activity_instance = {
        "activity": activity, "started_at": time.time() - elapsed_ago,
        "planned_duration": planned, "instance_id": f"{activity}-1",
        "status": "RUNNING", "elapsed": 0.0, "progress": 0.0,
        "finish_reason": None, "source": "mind",
    }
    return sched._activity_instance


def test_queued_mind_action_does_not_start_activity_instance():
    """仅提交 mind 决策（被阻塞/未执行）→ **不创建实例**、不 mark_done。"""
    sched, bus, se = _sched()
    d = LifeDecision(activity="sleep", duration=180, next_think_in=90, reason="困")
    sched._apply_life_decision(d)
    assert getattr(sched, "_activity_instance", None) is None, \
        "未执行的 mind 请求不得创建活动实例"
    assert sched.motivation._activity_history == [], \
        "未执行的请求不得 mark_done（recency 不被污染）"
    assert getattr(sched, "_last_activity_finish", None) is None, "未执行 → 无结算"


def test_activity_instance_starts_on_director_execution():
    """Director 执行器确认（on_mind_action_started）时才创建 RUNNING 实例 + mark_done。"""
    sched, bus, se = _sched()
    sched.on_mind_action_started("read", planned_duration=60.0)
    inst = sched._activity_instance
    assert inst is not None and inst["status"] == "RUNNING"
    assert inst["activity"] == "read" and "instance_id" in inst
    assert sched.motivation._activity_history == ["read"], "实际开始才记 recency"


def test_mark_done_not_called_for_unexecuted_request():
    sched, bus, se = _sched()
    sched._apply_life_decision(LifeDecision(activity="wander", duration=30, next_think_in=60))
    assert "wander" not in sched.motivation._activity_history


def test_activity_replacement_is_not_automatic_completion():
    """新决策替换旧活动：未到计划时长 → INTERRUPTED（success=False），不是自动 COMPLETED。"""
    sched, bus, se = _sched()
    _start_mind(sched, "read", planned=60.0, elapsed_ago=0.0)   # 真正执行过，几乎没跑
    d = LifeDecision(activity="sleep", duration=180, next_think_in=90, reason="困了")
    sched._apply_life_decision(d)
    fin = getattr(sched, "_last_activity_finish", {})
    assert fin.get("reason") == "interrupted", f"替换未完成不得记为 completed: {fin}"
    # 新决策**不**自动创建 sleep 实例（等 Director 执行 on_mind_action_started）
    assert sched._activity_instance.get("activity") == "read", \
        "未执行的 sleep 决策不得创建实例"


def test_activity_completion_when_duration_elapsed():
    """实际运行时长 ≥ 计划时长 → COMPLETED（全额）。"""
    sched, bus, se = _sched()
    _start_mind(sched, "rest", planned=60.0, elapsed_ago=120.0)
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
    apply_outcome(st_b, "rest", ee_b, success=False, progress=0.5)
    assert st_a.needs.fatigue < st_b.needs.fatigue, "完成的 rest 应比被打断的 rest 恢复更多疲劳"


def test_outcome_spec_not_shared_mutable():
    o1 = outcome_for("rest", success=True)
    o2 = outcome_for("rest", success=False)
    assert o1.success is True and o2.success is False, "每次调用必须是独立副本"
    assert OUTCOMES["rest"].success is True, "全局 spec 不得被 success=False 污染"


def test_outcome_nested_specs_not_shared_mutable():
    """FINAL-R1 §5：needs/emotion 嵌套 dict 必须深拷贝（改副本不得污染全局 OUTCOMES）。"""
    o = outcome_for("eat")
    o.needs["hunger"] = -999.0
    o.emotion["happiness"] = 999.0
    assert OUTCOMES["eat"].needs.get("hunger") != -999.0, "嵌套 needs dict 不得共享"
    assert OUTCOMES["eat"].emotion.get("happiness") != 999.0, "嵌套 emotion dict 不得共享"


def test_interrupted_10pct_less_reward_than_70pct():
    """进度感知：10% 中断收益 < 70% 中断收益。"""
    def fatigue_after(progress):
        st = CharacterState(); st.needs.fatigue = 80.0
        apply_outcome(st, "rest", EmotionEngine(st.emotion), success=False, progress=progress)
        return st.needs.fatigue
    f10 = fatigue_after(0.1)
    f70 = fatigue_after(0.7)
    assert f10 > f70, f"10% 中断恢复应少于 70%: {f10} vs {f70}"


def test_interrupted_70pct_less_reward_than_completed():
    """进度感知：70% 中断收益 < 完成收益。"""
    st70 = CharacterState(); st70.needs.fatigue = 80.0
    apply_outcome(st70, "rest", EmotionEngine(st70.emotion), success=False, progress=0.7)
    stc = CharacterState(); stc.needs.fatigue = 80.0
    apply_outcome(stc, "rest", EmotionEngine(stc.emotion), success=True, progress=1.0)
    assert st70.needs.fatigue > stc.needs.fatigue, \
        f"70% 中断恢复应少于完成: {st70.needs.fatigue} vs {stc.needs.fatigue}"


def test_activity_status_completed_interrupted_failed_aborted():
    """实例状态机：RUNNING → COMPLETED/INTERRUPTED/FAILED/ABORTED。"""
    sched, bus, se = _sched()
    # completed
    _start_mind(sched, "rest", planned=60.0, elapsed_ago=120.0)
    sched._apply_life_decision(LifeDecision(activity="wander", duration=30, next_think_in=60))
    assert sched._last_activity_finish["reason"] == "completed"
    # aborted（用户打断）
    _start_mind(sched, "read", planned=60.0, elapsed_ago=5.0)
    sched._activity_instance["pending_finish"] = "aborted"
    sched._apply_life_decision(LifeDecision(activity="sleep", duration=180, next_think_in=90))
    assert sched._last_activity_finish["reason"] == "aborted"
    # failed
    _start_mind(sched, "explore", planned=60.0, elapsed_ago=5.0)
    sched._activity_instance["pending_finish"] = "failed"
    sched._apply_life_decision(LifeDecision(activity="read", duration=30, next_think_in=60))
    assert sched._last_activity_finish["reason"] == "failed"


def test_blocked_mind_action_cannot_receive_outcome():
    """被阻塞（从未执行）的 mind 请求：无实例 → 无结算、无 outcome。"""
    sched, bus, se = _sched()
    # 提交两个不同决策，但从未 on_mind_action_started（模拟被更高优先级阻塞）
    sched._apply_life_decision(LifeDecision(activity="play", duration=30, next_think_in=60))
    sched._apply_life_decision(LifeDecision(activity="sleep", duration=180, next_think_in=90))
    assert getattr(sched, "_last_activity_finish", None) is None, "从未执行 → 不得结算"
    assert getattr(sched, "_activity_instance", None) is None


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
    _start_mind(sched, "read", planned=60.0, elapsed_ago=5.0)
    d = LifeDecision(activity="sleep", duration=180, next_think_in=90, reason="困")
    sched._apply_life_decision(d)
    fin = getattr(sched, "_last_activity_finish", {})
    assert fin.get("activity") == "read", "结算对象是上一个活动"
    # 再决策同一个活动（continue 语义不应再结算）
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
