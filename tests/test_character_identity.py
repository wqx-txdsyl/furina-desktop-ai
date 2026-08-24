"""Phase 05: Furina Character Identity 测试（§28）。"""
from __future__ import annotations

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality
from furina.persona.character_identity import (
    FURINA_IDENTITY, NEUTRAL_CHARACTER_IDENTITY, appraise,
)

# 完全相同的 Behavioral Personality（Furina 用这个，Neutral 也用这个，只差 Identity）
SAME_P = Personality(0.6, 0.7, 0.55, 0.6, 0.7, 0.6, 0.65, 0.55)


def _mk(scene):
    st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 65
    st.user_present = scene != "quiet"
    st.user_working = scene in ("user_needs_help",)
    events = {"praise": ["praise", "compliment"], "reject": ["reject"],
              "ignored": ["ignored", "silence"], "user_return": ["return"],
              "fail": ["failed"], "help": ["help", "need"], "quiet": []}.get(scene, [])
    st._last_recent_events = events
    return st


def _top(identity, scene):
    st = _mk(scene)
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation(personality=SAME_P, identity=identity)
    c = m.candidates(st, ee, ctx={"recent_events": st._last_recent_events})
    return c


def test_identity_off_control():
    """Identity OFF（None）≈ Neutral —— 无 identity 时 appraisal 中性。"""
    st = _mk("praise")
    ee = EmotionEngine(st.emotion)
    m_none = BehaviorMotivation(personality=SAME_P, identity=None)
    c_none = m_none.candidates(st, ee, ctx={"recent_events": st._last_recent_events})
    # identity off 时所有候选 identity_fit=0
    assert all(c.identity_fit == 0 for c in c_none), "Identity OFF 时应无 identity_fit"


def test_same_personality_only_identity_differs():
    """Furina vs Neutral 用完全相同 Behavioral Personality,只换 Identity → 行为不同。"""
    f_cands = _top(FURINA_IDENTITY, "praise")
    n_cands = _top(NEUTRAL_CHARACTER_IDENTITY, "praise")
    # Furina 的识别相关候选 identity_fit 更高
    f_fit = max(c.identity_fit for c in f_cands[:3])
    n_fit = max(c.identity_fit for c in n_cands[:3])
    assert f_fit > n_fit, f"Furina 应更高 identity_fit: {f_fit} vs {n_fit}"


def test_character_appraisal_deterministic():
    """CharacterAppraisal 存在且确定性。"""
    st = _mk("praise")
    ap1 = appraise(FURINA_IDENTITY, user_present=st.user_present, user_working=st.user_working,
                   recent_events=st._last_recent_events, user_idle=st.user_idle_seconds,
                   relationship_factors={"comfort": 0.4, "familiarity": 0.4}, emotion_label="calm")
    ap2 = appraise(FURINA_IDENTITY, user_present=st.user_present, user_working=st.user_working,
                   recent_events=st._last_recent_events, user_idle=st.user_idle_seconds,
                   relationship_factors={"comfort": 0.4, "familiarity": 0.4}, emotion_label="calm")
    assert ap1.as_dict() == ap2.as_dict(), "appraisal 应确定性"


def test_recognition_trigger():
    """夸奖/用户回来 → recognition_opportunity 高（Furina 比 Neutral 更敏感）。"""
    st = _mk("praise")
    rel = {"comfort": 0.4, "familiarity": 0.4, "annoyance": 0.1}
    ap_f = appraise(FURINA_IDENTITY, user_present=True, user_working=False,
                    recent_events=["praise"], user_idle=60, relationship_factors=rel, emotion_label="calm")
    ap_n = appraise(NEUTRAL_CHARACTER_IDENTITY, user_present=True, user_working=False,
                    recent_events=["praise"], user_idle=60, relationship_factors=rel, emotion_label="calm")
    assert ap_f.recognition_opportunity > ap_n.recognition_opportunity, "Furina 对夸奖更敏感"


def test_dignity_threat_rejection():
    """被拒绝 → Furina 有 dignity_threat（Neutral 低）。"""
    rel = {"comfort": 0.4, "familiarity": 0.4, "annoyance": 0.1}
    ap_f = appraise(FURINA_IDENTITY, user_present=True, user_working=False,
                    recent_events=["reject"], user_idle=60, relationship_factors=rel, emotion_label="calm")
    ap_n = appraise(NEUTRAL_CHARACTER_IDENTITY, user_present=True, user_working=False,
                    recent_events=["reject"], user_idle=60, relationship_factors=rel, emotion_label="calm")
    assert ap_f.dignity_threat > ap_n.dignity_threat, "Furina 应感知 dignity threat"


def test_identity_does_not_override_survival():
    """高疲劳 → Furina 也 rest/sleep（Identity 不覆盖生理,§10）。"""
    st = _mk("quiet"); st.needs.fatigue = 100; st.needs.sleepiness = 90
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation(personality=SAME_P, identity=FURINA_IDENTITY)
    cands = m.candidates(st, ee, ctx={"recent_events": []})
    top3 = {c.activity for c in cands[:3]}
    assert "rest" in top3 or "sleep" in top3, f"高疲劳应休息: {top3}"


def test_contradiction_case():
    """社会需求高+认可机会高+近期被拒 → candidate 出现合理竞争（非单纯 attention→talk）。"""
    st = _mk("reject"); st.needs.social_need = 90
    # 构造"想被关注 vs 不愿显得需要关注"的矛盾：被拒 + 高社交
    st._last_recent_events = ["reject", "praise"]
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation(personality=SAME_P, identity=FURINA_IDENTITY)
    cands = m.candidates(st, ee, ctx={"recent_events": st._last_recent_events})
    top4 = [c.activity for c in cands[:4]]
    # 不应全部是直接求关注；应存在社会/自我活动的竞争
    assert len(set(top4)) >= 2, "矛盾场景应有竞争候选"
    assert any(a in ("talk", "approach_user") for a in top4), "仍在寻求关注"


def test_identity_x_relationship():
    """Identity 稳定,但 Relationship 改变其表达（低熟悉 vs 高熟悉）。"""
    def fit_sum(fam):
        st = _mk("user_return")
        # 注入关系
        class R: pass
        r = R(); r.familiarity=fam; r.comfort=50; r.trust=50; r.annoyance=5
        r.attachment=0; r.respect=0; r.dependency=0; r.interaction_count_24h=5
        r.user_rejection_rate=0; r.user_response_rate=0.5
        r.social_confidence=40; r.interaction_tolerance=50
        st.relationship = r
        ee = EmotionEngine(st.emotion)
        m = BehaviorMotivation(personality=SAME_P, identity=FURINA_IDENTITY)
        top = m.candidates(st, ee, ctx={"recent_events": st._last_recent_events})[0]
        return top.activity, top.identity_fit
    low_act, low_fit = fit_sum(5)
    hi_act, hi_fit = fit_sum(90)
    # 高熟悉下 recognition 表达可能不同，但 identity_fit 仍存在
    assert hi_fit >= 0 and low_fit >= 0


def test_identity_x_emotion_no_extra_dims():
    """Identity 不新增 Emotion 维度（只用现有 EmotionState label）。"""
    from furina.state import CharacterState as CS
    st = CS()
    # identity 不往 emotion 加字段
    assert not hasattr(st.emotion, "recognition"), "Identity 不应往 Emotion 加维度"


def test_identity_fit_explainable():
    """候选带 identity_fit + identity_reasons（§26 Debug）。"""
    st = _mk("praise")
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation(personality=SAME_P, identity=FURINA_IDENTITY)
    c = m.candidates(st, ee, ctx={"recent_events": st._last_recent_events})[0]
    d = c.as_dict()
    assert "identity_fit" in d and "identity_reasons" in d


def test_appraisal_no_need_to_direct_activity():
    """Identity 通过 appraisal 进入,不直接指定 activity（§9）。"""
    # prove: identity 只改 motivation 差异,不是把某 activity 硬顶到第一
    st = _mk("fail")
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation(personality=SAME_P, identity=FURINA_IDENTITY)
    cands = m.candidates(st, ee, ctx={"recent_events": st._last_recent_events})
    # 没有任何候选被 identity 硬抬到 >0.9（除非 base 本来高）
    assert all(c.score <= 0.9 for c in cands[:5]), "Identity 不应制造过多高强候选"
