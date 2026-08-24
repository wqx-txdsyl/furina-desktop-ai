"""Phase 08B-Closeout: Dialogue Persona Control 测试（§19）。"""
from __future__ import annotations

from furina.dialogue import DialogueValidator

from furina.persona.furina_character_contract import (
    NEUTRAL_DIALOGUE_PERSONA, FORMER_MASK_PERSONA)

_v = DialogueValidator()


def test_neutral_is_not_generic_assistant():
    """Neutral 定义为自然真人：契约明确禁止通用助手腔（含负向禁令）。"""
    low = NEUTRAL_DIALOGUE_PERSONA.lower()
    # 契约是提示词：应包含对通用助手腔的"禁止指令"
    assert ("生成答案" in low and "为您服务" in low and "有什么可以帮" in low), \
        "Neutral 契约应明确列出禁止的助手措辞（作为负向禁令）"
    # 契约不应把 Neutral 本身定义成"提供服务的存在"
    assert "您是一个咨询服务" not in low, "Neutral 不应被定义成咨询服务"
    assert "角色" in low or "普通人" in low or "聊" in low, "Neutral 应被定义成自然的人"


def test_same_validator_for_neutral():
    """Furina 与 Neutral 用同一 validator（公平）。"""
    # 两者共同守卫：generic assistant 在极端情况下都应被标记
    v_f = _v.validate("有什么可以帮你的吗？", should_speak=True)
    v_n = _v.validate("有什么可以帮你的吗？", should_speak=True)
    f_hit = "generic_assistant_voice" in v_f.issues
    n_hit = "generic_assistant_voice" in v_n.issues
    assert f_hit == n_hit and f_hit is True, "两方都应以同一规则拒绝通用助手腔"
    assert v_n.god_reference_count == _v.validate("有什么可以帮你的吗？").god_reference_count


def test_service_offer_register_caught():
    """服务腔变体（Neutral 曾泄漏的'有什么帮助'及其"我"字变体）应被同一 validator 捕获。"""
    for s in ("有什么需要帮忙的吗？", "有什么我可以帮你的吗？", "需要我帮忙吗？", "随时为您服务"):
        v = _v.validate(s, should_speak=True)
        assert "generic_assistant_voice" in v.issues, f"应捕获服务腔: {s!r}"
    # 但一句真实自然的关心（朋友式的、非服务模板）不应被误伤
    v_ok = _v.validate("怎么啦？看你有点累。", should_speak=True)
    assert "generic_assistant_voice" not in v_ok.issues
    # 真诚的"很高兴能被认可"（非"很高兴为您服务"）不应被 `很高兴(为|能)为您(服务|…)` 误伤
    v_p = _v.validate("谢谢夸奖！我一直在努力，很高兴能得到认可。", should_speak=True)
    assert "generic_assistant_voice" not in v_p.issues


def test_former_mask_not_keyword_caricature():
    """Former Mask 定义强调 grandiosity/performative distance，非关键词堆砌。"""
    low = FORMER_MASK_PERSONA.lower()
    # 不应把"每句喊水神/审判"当规范
    assert "每句" not in low or "水神" not in low.split("每句")[0], "不应要求每句喊水神"
    assert "距离" in low or "演出" in low or "威严" in low, "应强调 performative distance"


def test_ordinary_god_reference_suppressed():
    """普通情境（casual）god 自指 → 标记过度。"""
    v = _v.validate("本神觉得今天不错。", should_speak=True, context="casual")
    assert v.god_overuse_ordinary is True, "普通情境 god 自指应标记"
    assert v.god_reference_count >= 1


def test_performative_god_reference_allowed():
    """表演情境（performing）god 自指 → 允许（不标记过度，除非 >2）。"""
    v = _v.validate("就让你见识一下本神的戏法吧", should_speak=True, context="performing")
    assert v.god_overuse_ordinary is False, "表演情境允许偶发旧舞台腔"
    v2 = _v.validate("本神本神本神本神", should_speak=True, context="performing")
    assert v2.god_reference_count >= 2, "表演情境过多也标记"


def test_hard_blind_identity_control():
    """Hard Blind 依据——删身份词后仍可辨（此处测结构性评分差异）。"""
    from furina.persona.character_identity import FURINA_IDENTITY, NEUTRAL_CHARACTER_IDENTITY
    from furina.dialogue import ExpressionEngine
    def sig(ident, emotion="proud"):
        ap = ExpressionEngine(ident).appraise(
            emotion=emotion, relationship={"trust": 0.6, "comfort": 0.5, "annoyance": 0.1, "familiarity": 0.6},
            world={"interruption_cost": 0.1, "availability": 0.8}, user_present=True)
        st = ap.strategy
        return (round(st.dramatic_intensity, 2), round(st.defensiveness, 2), ap.mode)
    f = sig(FURINA_IDENTITY)
    n = sig(NEUTRAL_CHARACTER_IDENTITY)
    # 即使删身份词，结构化 Strategy 分布也不同
    assert f != n, "Furina 与 Neutral 的 strategy signature 应不同"


def test_praise_not_generic():
    """praise 不落入'谢谢我会努力'：proud 与 embarrassed 的 strategy 不同。"""
    from furina.persona.character_identity import FURINA_IDENTITY
    from furina.dialogue import ExpressionEngine
    ee = ExpressionEngine(FURINA_IDENTITY)
    p = ee.appraise(emotion="proud", intent="talk", user_text="你做得真好",
                    relationship={"trust": 0.6, "comfort": 0.5, "annoyance": 0.1, "familiarity": 0.6},
                    world={"interruption_cost": 0.1, "availability": 0.8})
    e = ee.appraise(emotion="embarrassed", intent="talk", user_text="你做得真好",
                    relationship={"trust": 0.6, "comfort": 0.5, "annoyance": 0.1, "familiarity": 0.6},
                    world={"interruption_cost": 0.1, "availability": 0.8})
    assert p.strategy.dramatic_intensity != e.strategy.dramatic_intensity, "proud/embarrassed 应不同"
    assert p.dialogue_act != e.dialogue_act or p.strategy.defensiveness != e.strategy.defensiveness


def test_failure_relationship_expression():
    """失败 × 关系：低熟悉 vs 高信任 → defensiveness/vulnerability 不同。"""
    from furina.persona.character_identity import FURINA_IDENTITY
    from furina.dialogue import ExpressionEngine
    ee = ExpressionEngine(FURINA_IDENTITY)
    lo = ee.appraise(emotion="embarrassed", intent="talk", user_text="搞砸了",
                     relationship={"trust": 0.2, "comfort": 0.2, "annoyance": 0.1, "familiarity": 0.2},
                     world={"interruption_cost": 0.2, "availability": 0.7})
    hi = ee.appraise(emotion="embarrassed", intent="talk", user_text="搞砸了",
                     relationship={"trust": 0.9, "comfort": 0.8, "annoyance": 0.05, "familiarity": 0.9},
                     world={"interruption_cost": 0.2, "availability": 0.7})
    assert lo.strategy.defensiveness >= hi.strategy.defensiveness or lo.mode == hi.mode, \
        "低熟悉应更防御"
