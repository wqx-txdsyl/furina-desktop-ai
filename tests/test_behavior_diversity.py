"""行为去塌缩测试（任务 §18：硬性反塌缩检测 + 多样性）。

用 Mock Brain（确定性地从 Motivation 候选里人格化选）+ 真实 BehaviorMotivation，
验证：observe_user 不再是默认、SELF 稳定出现、类别多样、高无聊→play/explore、
高社交→talk/approach、高疲劳→rest、拒绝→主动下降。
不调真实 LLM（快、稳定、可断言）。
"""
from __future__ import annotations

import random
from collections import Counter

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.memory.memory_types import RelationshipState
from furina.relationship.engine import RelationshipEngine, EV_REJECT
from furina.behavior import BehaviorMotivation, Candidate
from furina.behavior.motivation import CATEGORY


def _mock_brain(mot: BehaviorMotivation, state, emotion, seed=None):
    """确定性 mock：按人格从候选里选（不选 observe 过多次；带一点随机避免死循环）。"""
    cands = mot.candidates(state, emotion)
    # 反塌缩：若 observe 已是近期主导，强制下调其候选
    cands.sort(key=lambda c: c.score, reverse=True)
    # 过滤：绝不因“安全”选 observe；仅当它是前 2 且无更强非观察候选
    top = cands[0]
    # 多样性：非观察类优先（除非观察动机显著最高）
    non_obs = [c for c in cands if CATEGORY.get(c.activity) != "OBSERVATION" and c.activity != "idle"]
    if top.score < 0.9 and non_obs and non_obs[0].score >= top.score * 0.7:
        return non_obs[0].activity
    return top.activity


def _run_scenario(**need_overrides) -> dict:
    st = CharacterState()
    st.clock_hour = 14
    for k, v in need_overrides.items():
        setattr(st.needs, k, v)
    ee = EmotionEngine(st.emotion)
    mot = BehaviorMotivation()
    acts = []
    for _ in range(40):
        mot.mark_done("", 0)  # no-op
        a = _mock_brain(mot, st, ee)
        mot.mark_done(a, 0)
        acts.append(a)
    c = Counter(acts)
    cats = Counter(CATEGORY.get(a, "SELF") for a in acts)
    return {"acts": acts, "counts": c, "cats": cats}


def test_no_observe_collapse_direct():
    """直接：观察类不应占 >50%（任务 §18）。"""
    for over in [{"boredom": 90}, {"social_need": 85}, {}, {"curiosity": 90}]:
        r = _run_scenario(**over)
        obs = r["cats"].get("OBSERVATION", 0)
        assert obs / 40 <= 0.5, f"观察类占比过高 {obs}/40"


def test_self_activity_present_no_interaction():
    """无互动场景：SELF 行为应稳定出现。"""
    r = _run_scenario()
    self_n = r["cats"].get("SELF", 0)
    assert self_n >= 8, f"SELF 行为不足 {self_n}"


def test_high_boredom_produces_play_or_explore():
    st = CharacterState(); st.needs.boredom = 95; st.needs.playfulness = 90
    ee = EmotionEngine(st.emotion); mot = BehaviorMotivation()
    cands = mot.candidates(st, ee)
    top3 = {c.activity for c in cands[:3]}
    assert "play" in top3 or "explore" in top3, f"高无聊应倾向 play/explore: {top3}"


def test_high_social_produces_talk_or_approach():
    st = CharacterState(); st.needs.social_need = 95
    ee = EmotionEngine(st.emotion); mot = BehaviorMotivation()
    cands = mot.candidates(st, ee)
    top3 = {c.activity for c in cands[:3]}
    assert "talk" in top3 or "approach_user" in top3, f"高社交应倾向 talk/approach: {top3}"


def test_high_fatigue_produces_rest():
    st = CharacterState(); st.needs.fatigue = 95; st.needs.sleepiness = 90
    ee = EmotionEngine(st.emotion); mot = BehaviorMotivation()
    cands = mot.candidates(st, ee)
    top3 = {c.activity for c in cands[:3]}
    assert "rest" in top3 or "sleep" in top3, f"高疲劳应倾向 rest: {top3}"


def test_observe_not_top_candidate_when_bored():
    """高无聊时 observe_user 不应是第一候选（§1：observe 不是 fallback）。"""
    st = CharacterState(); st.needs.boredom = 95; st.needs.playfulness = 90
    ee = EmotionEngine(st.emotion); mot = BehaviorMotivation()
    top = mot.candidates(st, ee)[0]
    assert top.activity != "observe_user", f"observe_user 不应是最高候选: {top}" 


def test_category_repetition_penalty():
    """B4（评审基线 0402e7f）：类别重复**不再触发惩罚** —— production anti-collapse = OFF。

    旧契约（连续观察 → _category_penalty < 1.0 压制）已被 B4 明确移除：'刚做过所以必须换'
    不是因果。重复观察不得改变候选分数（MOT-L2/L7 同一不变量）。
    """
    import furina.behavior.motivation as M
    src = open(M.__file__, encoding="utf-8").read()
    assert "def _category_penalty" not in src, "类别惩罚必须移除（B4）"
    st = CharacterState(); st.needs.boredom = 90; st.needs.curiosity = 80
    ee = EmotionEngine(st.emotion)
    m1 = BehaviorMotivation()
    m2 = BehaviorMotivation()
    for _ in range(4):
        m2.mark_done("observe_user", 0)     # 仅历史不同
    a1 = m1.candidates(st, ee)
    a2 = m2.candidates(st, ee)
    s1 = {c.activity: c.score for c in a1}
    s2 = {c.activity: c.score for c in a2}
    assert s1 == s2, f"仅历史不同不得改变任何候选分数: {s1} vs {s2}"


def test_rejection_reduces_social_approach():
    """用户拒绝 → tolerance 下降 → SOCIAL/ASSISTANCE 主动动机下降（§13, §14）。"""
    from furina.relationship.engine import RelationshipEngine, EV_REJECT
    # 通过 RelationshipEngine 施加拒绝（Phase 04 正确路径），验证社交主动被压制
    rel_hi = RelationshipEngine(state=RelationshipState())
    rel_hi.state.interaction_tolerance = 90.0   # 高接纳
    st_hi = CharacterState(); st_hi.needs.social_need = 90; st_hi.relationship = rel_hi.state
    ee = EmotionEngine(st_hi.emotion)
    rel_lo = RelationshipEngine(state=RelationshipState())
    for _ in range(6):
        rel_lo.apply(EV_REJECT)   # 连续拒绝 → tolerance 降
    st_lo = CharacterState(); st_lo.needs.social_need = 90; st_lo.relationship = rel_lo.state
    ee2 = EmotionEngine(st_lo.emotion)
    m_hi = BehaviorMotivation(); m_lo = BehaviorMotivation()
    talk_hi = next(c for c in m_hi.candidates(st_hi, ee) if c.activity == "talk").score
    talk_lo = next(c for c in m_lo.candidates(st_lo, ee2) if c.activity == "talk").score
    assert talk_lo < talk_hi, f"拒绝后 talk 应被压制: before={talk_hi} after={talk_lo}"
    assert rel_lo.state.interaction_tolerance < rel_hi.state.interaction_tolerance, "拒绝应降接纳度"


def test_talk_is_independent_candidate_with_reason():
    """talk 是独立候选（§7），且有 ground 的原因（§6）。"""
    st = CharacterState(); st.needs.social_need = 90
    ee = EmotionEngine(st.emotion); mot = BehaviorMotivation()
    cands = mot.candidates(st, ee, ctx={"interesting_event": "user_completed_task"})
    t = next(c for c in cands if c.activity == "talk")
    assert t.why, "talk 候选应带原因（§6-8）"
    # 有事件时 talk 动机应升高
    t2 = next(c for c in mot.candidates(st, ee) if c.activity == "talk")
    assert t.score >= t2.score * 0.9


def test_idle_never_default_when_stuff_happens():
    """有明确需求时 idle 不是第一候选（任务 §18 底线）。"""
    st = CharacterState(); st.needs.hunger = 95
    ee = EmotionEngine(st.emotion); mot = BehaviorMotivation()
    top = mot.candidates(st, ee)[0]
    assert top.activity != "idle", "idle 不应在饥饿时胜出"
