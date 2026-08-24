"""Phase 04 Relationship 动态测试（§14 要求）。"""
from __future__ import annotations

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality
from furina.memory.memory_types import RelationshipState
from furina.relationship import RelationshipEngine
from furina.relationship.engine import (EV_REJECT, EV_IGNORE, EV_POSITIVE_RESPONSE,
    EV_POSITIVE_TOUCH, EV_SUCCESSFUL_HELP, EV_USER_INITIATED)

SOCIAL = Personality(0.5, 1.0, 0.2, 0.5, 0.8, 0.5, 0.9, 0.2)
EXPLORER = Personality(0.5, 0.2, 1.0, 0.5, 0.5, 1.0, 0.1, 0.9)


def _talk_score(rel_state):
    st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 70
    st.relationship = rel_state
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation(personality=SOCIAL)
    c = m.candidates(st, ee)
    return next((x.score for x in c if x.activity == "talk"), 0.0)


def test_positive_adaptation_raises_relationship():
    """正向互动 → familiarity/comfort/confidence 渐进上升（不是一次跳满）。"""
    re = RelationshipEngine()
    re.apply(EV_POSITIVE_RESPONSE)
    f1, c1 = re.state.familiarity, re.state.comfort
    re.apply(EV_POSITIVE_RESPONSE)
    f2, c2 = re.state.familiarity, re.state.comfort
    assert f2 > f1 > 0 and c2 > c1 > 0, "渐进上升"


def test_rejection_adaptation_progressive():
    """连续拒绝 → 主动社交**渐进**下降（不是瞬间归零）。"""
    re = RelationshipEngine()
    talk_progression = []
    for _ in range(5):
        re.apply(EV_REJECT)
        talk_progression.append(_talk_score(re.state))
    # 每次都比上次更弱（递减），且第1次不归零
    assert talk_progression[0] > 0.05, "第1次拒绝不应瞬间归零"
    assert all(talk_progression[i] > talk_progression[i+1] for i in range(4)), f"应渐进下降: {talk_progression}"
    assert talk_progression[-1] < talk_progression[0], "最终应显著下降"


def test_relationship_decay_recovers():
    """负向状态能随时间自然恢复。"""
    re = RelationshipEngine()
    for _ in range(5):
        re.apply(EV_REJECT)
    annoy_after = re.state.annoyance
    for _ in range(30):
        re.decay(dt=120)
    assert re.state.annoyance < annoy_after, "annoyance 应回落"


def test_relationship_recovery_via_positive():
    """positive interaction 能修复 confidence/comfort。"""
    re = RelationshipEngine()
    for _ in range(5):
        re.apply(EV_REJECT)
    pre_conf = re.state.social_confidence
    for _ in range(5):
        re.apply(EV_POSITIVE_TOUCH)
    assert re.state.social_confidence > pre_conf, "积极互动应重建 confidence"
    assert re.state.comfort > 0, "comfort 应回升"


def test_trust_not_rapidly_boosted():
    """trust 不能被轻微互动快速刷满（需慢速/长期）。"""
    re = RelationshipEngine()
    for _ in range(20):
        re.apply(EV_POSITIVE_RESPONSE)   # 20 次积极回应
    assert re.state.trust < 15, f"轻微互动不应快速刷满 trust: {re.state.trust:.1f}"


def test_relationship_to_motivation():
    """关系 → 动机：高 annoy 显著压低 talk,高 comfort 抬升 talk。"""
    rel_annoy = RelationshipState(); rel_annoy.annoyance = 80; rel_annoy.interaction_tolerance = 20
    rel_comfort = RelationshipState(); rel_comfort.comfort = 80; rel_comfort.interaction_tolerance = 60
    annoy_talk = _talk_score(rel_annoy)
    comfort_talk = _talk_score(rel_comfort)
    assert annoy_talk < comfort_talk, "高annoy应压talk, 高comfort应抬talk"


def test_personality_x_relationship_no_convergence():
    """高 trust 不应让所有人格行为趋同（Relationship 改变表达,不覆盖人格）。"""
    def top(per, trust):
        re = RelationshipEngine(); re.state.trust = 90; re.state.comfort = 80; re.state.familiarity = 80
        re.state.social_confidence = 80; re.state.interaction_tolerance = 80
        st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 70; st.relationship = re.state
        ee = EmotionEngine(st.emotion); m = BehaviorMotivation(personality=per)
        return m.candidates(st, ee)[0].activity
    social_top = top(SOCIAL, True)
    explorer_top = top(EXPLORER, True)
    # 高 trust 下 Social 应偏社交,Explorer 不应也被拉成 approach(仍保持探索)
    assert social_top in ("talk", "approach_user", "invite_user"), f"Social高trust应社交: {social_top}"
    assert explorer_top in ("explore", "read", "wander"), f"Explorer高trust不应被拉成approach: {explorer_top}"


def test_relationship_history_counterfactual():
    """关系 History 差异 → Motivation 差异 → 行为差异（两个相同角色,只差过往）。"""
    def make(history=""):
        re = RelationshipEngine()
        if history == "positive":
            for _ in range(12):
                re.apply(EV_POSITIVE_RESPONSE)
        elif history == "reject":
            for _ in range(12):
                re.apply(EV_REJECT)
        st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 70; st.relationship = re.state
        ee = EmotionEngine(st.emotion)
        m = BehaviorMotivation(personality=SOCIAL)
        c = m.candidates(st, ee)
        return {x.activity: x.score for x in c}, re.state
    a, ra = make("positive")
    b, rb = make("reject")
    assert ra.social_confidence > rb.social_confidence, "正向经历应更高confidence"
    assert a["talk"] > b["talk"] + 0.1, f"正向经历 talk 应更高: {a['talk']:.2f} vs {b['talk']:.2f}"
    assert a["approach_user"] > b["approach_user"] + 0.1, f"正向经历 approach 应更高"
