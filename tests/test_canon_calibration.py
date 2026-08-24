"""Phase 08A: Canon Persona Calibration 测试（trait activation + anti-caricature + current vs mask）。"""
from __future__ import annotations

from furina.persona.character_identity import (
    FURINA_IDENTITY, NEUTRAL_CHARACTER_IDENTITY, appraise, activation_gain,
)


def _appraise(events, user_present=True, user_working=False, user_idle=60,
              rel=None, emotion="calm"):
    rel = rel or {"comfort": 0.4, "familiarity": 0.4, "annoyance": 0.1}
    return appraise(FURINA_IDENTITY, user_present=user_present, user_working=user_working,
                    recent_events=events, user_idle=user_idle,
                    relationship_factors=rel, emotion_label=emotion)


def test_historical_trait_has_era():
    """fear_of_being_exposed 是 historical_latent（非 always_active_core）。"""
    assert FURINA_IDENTITY.trait_eras.get("fear_of_being_exposed") in (
        "historical_latent", "historical", "latent")
    assert FURINA_IDENTITY.trait_eras.get("dramatic_self_presentation") == "stable"


def test_trait_activation_gating():
    """默认背景级激活；触发情境才显著。"""
    base = activation_gain(FURINA_IDENTITY, "fear_of_being_exposed")
    boosted = activation_gain(FURINA_IDENTITY, "fear_of_being_exposed",
                              boost_if=True, boost=0.9)
    assert base < boosted, f"触发应提高激活: {base} vs {boosted}"
    assert base <= 0.4, "普通场景背景级（不 always-on 悲剧化）"


def test_ordinary_context_not_sad():
    """普通情境（'你干嘛''今天好热'）不产生高 dignity_threat / vulnerability。"""
    ap = _appraise(events=[], user_idle=60, emotion="calm")
    # 普通情境：历史创伤激活低 → 不应显著高
    assert ap.dignity_threat < 0.4, f"普通场景不应高dignity_threat: {ap.dignity_threat}"
    assert ap.vulnerability_pressure < 0.4


def test_historical_trigger_context_activates():
    """被质疑/被逼解释 → 历史创伤激活升高。"""
    ap = _appraise(events=["expose", "质疑", "explain"], user_idle=60)
    plain = _appraise(events=[], user_idle=60)
    assert ap.dignity_threat > plain.dignity_threat, "触发情境应提高 dignity_threat"


def test_loneliness_sensitivity_not_automatic():
    """孤独敏感是 triggered，不是每晚自动悲伤：普通安静场景不产生高 vulnerability。"""
    # 用户在场、关系好、情绪 calm、无触发事件 → 不应出现历史创伤式高脆弱
    ap = _appraise(events=[], user_present=True, user_idle=60,
                   rel={"comfort": 0.8, "familiarity": 0.8, "annoyance": 0.05},
                   emotion="calm")
    # vulnerability_pressure 依赖"失败/显得无能"触发；普通安静场景应低
    assert ap.vulnerability_pressure < 0.5, f"普通安静场景不应高脆弱: {ap.vulnerability_pressure}"
    # 孤独/被冷落历史创伤默认背景级，不因一个 ignore 就爆表
    ap_ignore = _appraise(events=["ignore"], user_present=True, user_idle=60,
                          rel={"comfort": 0.8, "familiarity": 0.8, "annoyance": 0.05},
                          emotion="calm")
    assert ap_ignore.dignity_threat < 0.9, "单独 ignore 不应把历史创伤拉到极高"


def test_current_vs_mask_differs_from_neutral():
    """Current Furina ≠ Neutral（在 praise/recognition 场景）。"""
    rel = {"comfort": 0.4, "familiarity": 0.4, "annoyance": 0.1}
    f = appraise(FURINA_IDENTITY, user_present=True, user_working=False,
                 recent_events=["praise"], user_idle=60, relationship_factors=rel, emotion_label="calm")
    n = appraise(NEUTRAL_CHARACTER_IDENTITY, user_present=True, user_working=False,
                 recent_events=["praise"], user_idle=60, relationship_factors=rel, emotion_label="calm")
    assert f.recognition_opportunity > n.recognition_opportunity, "Furina 应更在意认可"


def test_not_perpetual_archon_mask():
    """普通场景 Furina 不会永远高 dignity_threat（非 always-on 水神面具）。"""
    ap = _appraise(events=[], user_present=True, user_idle=60, emotion="calm")
    # 普通场景 dignity_threat 应明显低于"被质疑"场景
    triggered = _appraise(events=["expose"], user_idle=60)
    assert ap.dignity_threat < triggered.dignity_threat, "普通场景应明显低于触发场景"


def test_current_growth_present():
    """current growth trait（craves_genuine_connection）是 post_story_growth，非历史。"""
    assert FURINA_IDENTITY.trait_eras.get("craves_genuine_connection") in (
        "post_story_growth", "stable")
    assert FURINA_IDENTITY.craves_genuine_connection >= 0.7, "应渴望真实连接"


def test_anti_caricature_rules_exist():
    """契约含 anti-caricature（防简化成傲娇/孤独）。"""
    import furina.persona.furina_character_contract as c
    assert any("傲娇" not in x for x in c.ANTI_CARICATURE) is False or len(c.ANTI_CARICATURE) >= 5
    assert len(c.CONTRADICTIONS) >= 5, "应有多个对立面（不是单一傲娇）"
    assert any("孤独" in x for x in c.ANTI_CARICATURE), "应禁'骄傲+孤独'独占"
