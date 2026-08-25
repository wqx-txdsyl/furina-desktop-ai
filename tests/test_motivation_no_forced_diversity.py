"""Phase 13 Pre-Manual Blocker Repair R1 — B4 Motivation No Forced Diversity（MOT-L1..L7）。

契约（评审基线 0402e7f）：production anti-collapse = OFF。
  - 重复行为不得仅因 repetition 被强制换类（真实人可连续读书）；
  - 换行为只能来自真实因果：needs outcome / 用户拒绝 / world 可行性 / 条件改变；
  - 同 state + 同输入 → 确定性。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation
from furina.memory.memory_types import RelationshipState
from furina.relationship.engine import RelationshipEngine, EV_REJECT


def _mot(state, history_acts=()):
    m = BehaviorMotivation()
    t = 100.0
    for a in history_acts:
        m.mark_done(a, t)
        t += 60.0
    ee = EmotionEngine(state.emotion)
    cands = m.candidates(state, ee)
    return cands[0].activity, cands[0].score, cands


# ================================================================ MOT-L1/L2
def test_mot_l1_repeated_read_remains_top_candidate():
    """L1：反复 read 后 read 仍保持 top（Windows regression 原失败点）。"""
    st = CharacterState(); st.needs.curiosity = 90; st.needs.boredom = 80
    top, _, _ = _mot(st, ("read",) * 5)
    assert top == "read", f"read 不应因做过多次被强制换掉: {top}"


def test_mot_l2_repetition_alone_never_changes_scores():
    """L2：连续 read 不因 repetition 被强制换 explore；仅历史不同 → 分数完全相同。"""
    st1 = CharacterState(); st1.needs.curiosity = 90; st1.needs.boredom = 80
    st2 = CharacterState(); st2.needs.curiosity = 90; st2.needs.boredom = 80
    _, s1, c1 = _mot(st1, ("read",) * 5)
    _, s2, c2 = _mot(st2, ())
    assert s1 == s2, f"仅历史不同不得改分: {s1} vs {s2}"
    d1 = {c.activity: c.score for c in c1}
    d2 = {c.activity: c.score for c in c2}
    assert d1 == d2, "所有候选分数都必须与历史无关（无重复惩罚）"


# ================================================================ MOT-L3
def test_mot_l3_condition_change_allows_natural_switch():
    """L3：read 的真实条件改变（curiosity 低、boredom 高）→ 自然换 explore/play。"""
    st = CharacterState(); st.needs.curiosity = 20; st.needs.boredom = 95; st.needs.playfulness = 90
    top, _, _ = _mot(st, ("read",) * 3)
    assert top in ("play", "explore"), f"需求变化应自然换行为: {top}"


# ================================================================ MOT-L4
def test_mot_l4_extreme_hunger_eat_beats_read():
    """L4：极高 hunger → eat 超过 read（不是'read 永远第一'）。"""
    st = CharacterState(); st.needs.curiosity = 90; st.needs.boredom = 80; st.needs.hunger = 98
    cands = _mot(st, ("read",) * 3)[2]
    eat = next(c for c in cands if c.activity == "eat")
    read = next(c for c in cands if c.activity == "read")
    assert eat.score > read.score, f"极高饥饿应让 eat 超过 read: eat={eat.score} read={read.score}"


# ================================================================ MOT-L5
def test_mot_l5_user_rejection_causally_suppresses_social():
    """L5：用户明确拒绝后 social 候选真实下降（因果抑制，必须保留）。"""
    rel_hi = RelationshipEngine(state=RelationshipState())
    rel_hi.state.interaction_tolerance = 90.0
    st_hi = CharacterState(); st_hi.needs.social_need = 90; st_hi.relationship = rel_hi.state
    ee_hi = EmotionEngine(st_hi.emotion)
    rel_lo = RelationshipEngine(state=RelationshipState())
    for _ in range(6):
        rel_lo.apply(EV_REJECT)
    st_lo = CharacterState(); st_lo.needs.social_need = 90; st_lo.relationship = rel_lo.state
    ee_lo = EmotionEngine(st_lo.emotion)
    talk_hi = next(c for c in BehaviorMotivation().candidates(st_hi, ee_hi)
                   if c.activity == "talk").score
    talk_lo = next(c for c in BehaviorMotivation().candidates(st_lo, ee_lo)
                   if c.activity == "talk").score
    assert talk_lo < talk_hi, f"拒绝后 talk 必须因果下降: {talk_hi} -> {talk_lo}"


# ================================================================ MOT-L6
def test_mot_l6_user_absent_user_directed_infeasible():
    """L6：user absent 时 user-directed 候选不可行（world 可行性，必须保留）。"""
    from furina.world_perception import WorldPerception
    wp = WorldPerception()
    wp.update(app="code", title="", idle_seconds=600.0, hour=14, minute=0,
              idle_available=True, process="code")     # away（有效 OS world）
    st = CharacterState()
    st.world = wp
    st.needs.social_need = 90
    ee = EmotionEngine(st.emotion)
    cands = BehaviorMotivation().candidates(st, ee, ctx={"world": wp.factors()})
    talk = next((c for c in cands if c.activity == "talk"), None)
    assert talk is not None and not talk.feasible, "user absent → talk 不可行"
    self_ok = [c for c in cands if c.feasible and c.activity in ("read", "wander", "rest")]
    assert self_ok, "SELF 保持可行"


# ================================================================ MOT-L7
def test_mot_l7_motivation_deterministic():
    """L7：同样 state + 同输入 → Motivation 完全确定性（两次运行逐候选同分）。"""
    st = CharacterState(); st.needs.curiosity = 90; st.needs.boredom = 80; st.needs.social_need = 70
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation()
    a = [(c.activity, c.score) for c in m.candidates(st, ee)]
    b = [(c.activity, c.score) for c in m.candidates(st, ee)]
    assert a == b, "同 state 必须确定性（逐候选同分同序）"
