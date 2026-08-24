"""Phase 08B: Dialogue Expression Persona 测试（§57）。"""
from __future__ import annotations

from furina.dialogue import ExpressionEngine, DialogueValidator, DialogueAct, PersonaMode
from furina.dialogue.expression import SpeechLength, ExpressionAppraisal
from furina.persona.character_identity import FURINA_IDENTITY, NEUTRAL_CHARACTER_IDENTITY

_ee = ExpressionEngine(FURINA_IDENTITY)
_v = DialogueValidator()


def _appraise(**kw):
    defaults = dict(emotion="calm", intent="talk", relationship={"trust": 0.5, "comfort": 0.5,
                   "annoyance": 0.1, "familiarity": 0.5}, world={"interruption_cost": 0.1,
                   "availability": 0.8, "user_working": False}, user_present=True)
    defaults.update(kw)
    return _ee.appraise(**defaults)


def test_should_speak_deep_focus():
    """深度工作 → 应抑制主动说话。"""
    ap = _appraise(world={"interruption_cost": 0.9, "availability": 0.15, "user_working": True}, user_initiated=False)
    assert ap.should_speak is False, "深度工作应沉默"
    assert ap.speech_drive < 0.4


def test_user_initiated_overrides_passive_suppression():
    """用户主动 → 即使深度工作也应响应（§6）。"""
    ap = _appraise(world={"interruption_cost": 0.9, "availability": 0.15, "user_working": True}, user_initiated=True)
    assert ap.should_speak is True, "用户主动应说话"
    assert ap.speech_drive >= 0.8


def test_silence_valid():
    """should_speak=False 是合法结果（silence 是行为）。"""
    ap = _appraise(world={"interruption_cost": 0.9, "availability": 0.1}, user_initiated=False)
    assert ap.should_speak is False


def test_persona_mode_selection():
    """proud → PROUD；excited → PERFORMATIVE；high-annoyance → GUARDED。"""
    assert _appraise(emotion="proud").mode == PersonaMode.PROUD.value
    assert _appraise(emotion="excited").mode == PersonaMode.PERFORMATIVE.value
    ap = _appraise(relationship={"trust": 0.1, "comfort": 0.2, "annoyance": 0.9, "familiarity": 0.3})
    assert ap.mode == PersonaMode.GUARDED.value, "高烦应收敛"


def test_historical_trait_triggered_only():
    """历史创伤（fear/孤独）不 always-on：普通 calm 不产生高 defensiveness/低开放。"""
    ap = _appraise(emotion="calm")
    assert ap.strategy.defensiveness < 0.7, "普通 calm 不应高防御"
    assert ap.strategy.vulnerability_visibility >= 0.2


def test_current_growth_casual_mode():
    """普通场景可 CASUAL / 真诚（POST_ARCHON_QUEST 成长，非永远戏剧）。"""
    modes = set()
    for emo in ["calm", "happy"]:
        modes.add(_appraise(emotion=emo).mode)
    assert PersonaMode.CASUAL.value in modes or PersonaMode.SINCERE.value in modes, modes


def test_emotion_expression_divergence():
    """不同 Emotion → 策略明显不同（§20-21）。"""
    st_proud = _appraise(emotion="proud").strategy
    st_sad = _appraise(emotion="sad").strategy
    st_annoyed = _appraise(emotion="annoyed").strategy
    assert abs(st_proud.dramatic_intensity - st_sad.dramatic_intensity) > 0.2, "proud vs sad drama 应不同"
    assert st_annoyed.warmth < st_proud.warmth, "annoyed 应比 proud 更冷"
    assert st_annoyed.brevity > st_proud.brevity, "annoyed 应更简洁"


def test_relationship_expression_divergence():
    """低熟悉 vs 高信任 → openness/warmth 差异（§22）。"""
    lo = _appraise(relationship={"trust": 0.1, "comfort": 0.1, "annoyance": 0.1, "familiarity": 0.1}, emotion="happy")
    hi = _appraise(relationship={"trust": 0.9, "comfort": 0.9, "annoyance": 0.05, "familiarity": 0.9}, emotion="happy")
    assert hi.strategy.emotional_openness >= lo.strategy.emotional_openness or hi.strategy.warmth >= lo.strategy.warmth


def test_genuine_care_mode():
    """用户求助+高信任 → RESPONSIBLE/SINCERE，戏剧性降、温暖升（§27）。"""
    ap = _ee.appraise(emotion="calm", intent="offer_help", user_text="能帮帮我吗",
                      relationship={"trust": 0.9, "comfort": 0.8, "annoyance": 0.05, "familiarity": 0.8},
                      world={"interruption_cost": 0.2, "availability": 0.8})
    assert ap.dialogue_act == DialogueAct.OFFER_HELP.value or ap.dialogue_act == DialogueAct.COMFORT.value
    assert ap.strategy.dramatic_intensity < 0.6, "帮忙时戏剧性应降"


def test_contradiction_expression():
    """想被注意 vs 不想显得需要 → medium/low directness（§28）。"""
    ap = _ee.appraise(emotion="lonely", intent="seek_attention",
                      relationship={"trust": 0.5, "comfort": 0.4, "annoyance": 0.3, "familiarity": 0.5},
                      world={"interruption_cost": 0.3, "availability": 0.7}, user_present=True)
    # 矛盾：有说话欲望但不愿直接
    assert ap.seed_intent.initiative > 0.3  # 有主动
    assert ap.strategy.directness <= 0.7    # 但有所保留


def test_generic_assistant_guard():
    """Validator 检测通用助手腔。"""
    v = _v.validate("有什么可以帮你的吗？", should_speak=True)
    assert "generic_assistant_voice" in v.issues


def test_stage_direction_guard():
    v = _v.validate("（轻轻叹气）好吧。", should_speak=True)
    assert "stage_direction" in v.issues


def test_archon_mask_guard():
    """"本神"过多被计数（god_reference），且可被检测。"""
    v = _v.validate("本神本神本神天下无敌", should_speak=True)
    assert v.god_reference_count >= 1


def test_god_reference_frequency():
    """普通场景 god 自指低频由 expression 层控制（非 validator 硬禁）。"""
    ap = _appraise(emotion="calm")
    assert ap.strategy.dramatic_intensity < 0.6, "普通 calm 不应高戏剧化"


def test_dialogue_length_guard():
    v = _v.validate("很" * 200, should_speak=True)   # 超长
    assert "too_long" in v.issues


def test_example_copy_guard():
    v = _v.validate("这句和范例一模一样的长句子在这里", should_speak=True,
                    example_phrases=["这句和范例一模一样的长句子在这里"])
    assert "example_copy" in v.issues


def test_fallback_silence():
    """空台词 → None（沉默优先于 Generic fallback，§39）。"""
    # say 返回 None 的逻辑由 DialogueBrain 处理；这里测 validator 空态
    assert _v.validate("", should_speak=True).valid is False


def test_furina_vs_neutral_strategy():
    """Furina 身份 → 更戏剧化/关注认可，较 Neutral 明显。"""
    f = ExpressionEngine(FURINA_IDENTITY).appraise(
        emotion="proud", relationship={"trust": 0.6, "comfort": 0.5, "annoyance": 0.1, "familiarity": 0.6},
        world={"interruption_cost": 0.1, "availability": 0.8}, user_present=True)
    n = ExpressionEngine(NEUTRAL_CHARACTER_IDENTITY).appraise(
        emotion="proud", relationship={"trust": 0.6, "comfort": 0.5, "annoyance": 0.1, "familiarity": 0.6},
        world={"interruption_cost": 0.1, "availability": 0.8}, user_present=True)
    assert f.mode == PersonaMode.PROUD.value or f.mode == PersonaMode.PERFORMATIVE.value, "Furina 应能表演"
    assert f.strategy.dramatic_intensity >= n.strategy.dramatic_intensity - 0.1
