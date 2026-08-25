"""R2.2 FINAL — Canon Identity / Evidence / Model 测试（tests/persona/ 01）。

覆盖（R2.2 §27）：
  - Canon identity >= 5
  - Persona evidence/model >= 5
  - CN voice/register >= 5
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from furina.persona.furina_canon import (
    ANTI_IDENTITY, BEHAVIOR_PATTERNS, CORE_CONTRADICTIONS, DRAMATIC_INTENSITY,
    IDENTITY_FACTS, PERSONALITY_AXES, VOICE_FINGERPRINT, axis,
    contradiction_descriptions, evidence_for,
)

REPO = Path(__file__).resolve().parents[2]
EVIDENCE_DOC = REPO / "docs" / "persona" / "FURINA_CANON_EVIDENCE.md"
MODEL_DOC = REPO / "docs" / "persona" / "FURINA_PERSONA_MODEL.md"
VOICE_DOC = REPO / "docs" / "persona" / "FURINA_CN_VOICE_PROFILE.md"


# ================================================================ Canon Identity（>=5）
def test_canon_identity_facts_present_and_correct():
    """身份事实齐全且 Furina≠Focalors canonical truth 正确。"""
    texts = " ".join(f["fact"] for f in IDENTITY_FACTS)
    assert len(IDENTITY_FACTS) >= 5, "至少 5 条身份事实"
    # Furina = 人格侧人类；Focalors = 神格侧
    assert any("人格侧" in f["fact"] for f in IDENTITY_FACTS), "必须有'人格侧'身份事实"
    assert any("神格侧" in f["fact"] for f in IDENTITY_FACTS), "必须有'神格侧'身份事实"
    assert any("扮演公众认为的水神" in f["fact"] for f in IDENTITY_FACTS), \
        "Furina 真实经历=扮演公众认为的水神（不是拥有神权执政）"


def test_canon_identity_no_furina_equals_focalors():
    """禁止'Furina == Focalors 记忆/神权'式错误表述。"""
    for f in IDENTITY_FACTS:
        assert "拥有芙卡洛斯" not in f["fact"] or "全部知识" in f["fact"], \
            f"不得声称拥有 Focalors 全部知识/记忆: {f['fact']}"
    # 全部 identity 事实都不含"我是神/拥有神力"自居
    for f in IDENTITY_FACTS:
        assert "我就是神" not in f["fact"] and "拥有神权" not in f["fact"]


def test_canon_periods_defined():
    """时期定义齐全且默认是 POST_AQ_CURRENT。"""
    from furina.persona.furina_canon import DEFAULT_PERIOD, PERIODS
    for p in ("PUBLIC_MASK", "PRIVATE_MASK_CRACK", "POST_AQ_EARLY",
              "POST_AQ_CURRENT", "CHOSEN_PERFORMANCE", "QUIET_PRIVATE"):
        assert p in PERIODS, f"缺少时期 {p}"
    assert DEFAULT_PERIOD == "POST_AQ_CURRENT", "默认时期必须是主线+传说任务后的当前芙宁娜"


def test_canon_anti_identity_not_generic():
    """'她不是哪些东西'齐全（不含 generic 模板）。"""
    assert len(ANTI_IDENTITY) >= 8
    joined = " ".join(ANTI_IDENTITY)
    for bad in ("generic tsundere", "therapist", "客服", "哎呀", "本神", "完美主义人格测试模板"):
        assert bad in joined, f"ANTI_IDENTITY 应包含: {bad}"


def test_canon_personality_axes_complete():
    """人格轴齐全且都附 Evidence（source traceability）。"""
    required = ("theatricality", "pride", "dignity", "attention_sensitivity",
                "performative_impulse", "social_boldness", "insecurity",
                "vulnerability_disclosure", "resilience", "curiosity",
                "ordinary_life_enjoyment")
    for r in required:
        assert r in PERSONALITY_AXES, f"缺人格轴: {r}"
        assert PERSONALITY_AXES[r].get("evidence"), f"{r} 必须附 Evidence IDs"


# ================================================================ Evidence / Model（>=5）
def test_evidence_doc_has_40_plus_units():
    """FURINA_CANON_EVIDENCE.md 至少 40 evidence units（FUR-001 ~ FUR-056）。"""
    txt = EVIDENCE_DOC.read_text(encoding="utf-8")
    ids = re.findall(r"FUR-\d{3}", txt)
    uniq = sorted(set(ids), key=lambda x: int(x.split("-")[1]))
    assert len(uniq) >= 40, f"evidence units 不足 40: {len(uniq)}"
    assert uniq[0] == "FUR-001", "必须从 FUR-001 开始"
    assert len(uniq) == int(uniq[-1].split("-")[1]), "ID 应连续"


def test_evidence_doc_has_all_required_fields():
    """evidence 表格含 ID/SOURCE/PERIOD/SCENE/OBSERVED_BEHAVIOR/…/RUNTIME_USE 列头。"""
    txt = EVIDENCE_DOC.read_text(encoding="utf-8")
    for col in ("ID", "SOURCE", "PERIOD", "SCENE", "OBSERVED_BEHAVIOR", "SPEECH_FEATURE",
                "INNER_STATE", "SOCIAL_STRATEGY", "PERSONA_INFERENCE", "CONFIDENCE",
                "RUNTIME_USE"):
        assert f"| {col} |" in txt, f"evidence 表缺列: {col}"


def test_model_doc_has_traceability():
    """FURINA_PERSONA_MODEL.md 有 Traceability 表（Model 结论 → Evidence IDs）。"""
    txt = MODEL_DOC.read_text(encoding="utf-8")
    assert "Traceability" in txt and "Evidence IDs" in txt
    assert "attention_sensitivity" in txt and "chosen_performance" in txt


def test_voice_profile_cn_patterns():
    """FURINA_CN_VOICE_PROFILE.md 覆盖 A-J 项（中文语音 pattern）。"""
    txt = VOICE_DOC.read_text(encoding="utf-8")
    for sec in ("## A.", "## B.", "## C.", "## D.", "## E.", "## F.", "## G.",
                "## H.", "## I.", "## J."):
        assert sec in txt, f"语音画像缺节: {sec}"
    # 关键结论：自称"我"主导；"本神"不作为 Canon 自称规律
    assert "本神" in txt and "压倒性用" in txt
    assert "哎呀" in txt and "不是核心口头禅" in txt


def test_voice_fingerprint_first_person():
    """VOICE_FINGERPRINT：自称基准是'我'；'本神'标记为极稀有。"""
    fp = VOICE_FINGERPRINT["first_person"]
    assert fp["default"] == "我"
    assert "本神" in fp["note"] and "极稀有" in fp["note"]


def test_evidence_for_mapping():
    """evidence_for() 给出已知结论的 Evidence IDs。"""
    assert "FUR-020" in evidence_for("attention_sensitivity")
    assert "FUR-022" in evidence_for("chosen_performance")
    assert "FUR-041" in evidence_for("focalors_relation")


def test_dramatic_intensity_ranges():
    """强度带齐全且 SINCERE < PERFORMATIVE（认真时降戏剧）。"""
    assert DRAMATIC_INTENSITY["SINCERE"][1] < DRAMATIC_INTENSITY["PERFORMATIVE"][0], \
        "SINCERE 上界必须低于 PERFORMATIVE 下界"
    assert DRAMATIC_INTENSITY["VULNERABLE"][1] <= 0.20
    assert DRAMATIC_INTENSITY["CASUAL"][0] >= 0.25


# ================================================================ Contradictions / Behavior
def test_core_contradictions_10():
    """至少 10 条核心矛盾（R2.2 §4.3 A-J）。"""
    assert len(CORE_CONTRADICTIONS) >= 10
    descs = contradiction_descriptions()
    assert any("焦点" in d for d in descs), "矛盾 A（焦点↔靠焦点存在）应存在"
    assert any("表演" in d and "认真" in d for d in descs), "矛盾 B（会表演↔认真时收住）"


def test_behavior_patterns_cover_key_scenarios():
    """行为模式覆盖被夸/被戳中/被质疑/安慰/安静陪伴等。"""
    for k in ("praise_received", "called_out", "challenged", "user_vulnerable",
              "no_one_watches", "self_intro", "greatest_strength", "greatest_flaw",
              "quiet_accompany"):
        assert k in BEHAVIOR_PATTERNS, f"缺行为模式: {k}"
    # 最大缺点禁止面试答案（surface 明确列出禁止项；自述方向是"爱撑场面/嘴硬"）
    assert "爱撑场面" in BEHAVIOR_PATTERNS["greatest_flaw"]["surface"]
    assert "嘴硬" in BEHAVIOR_PATTERNS["greatest_flaw"]["surface"]
    assert "完美主义" in BEHAVIOR_PATTERNS["greatest_flaw"]["surface"].split("禁止：")[1], \
        "禁止项应明确列出完美主义"
    # 最大优点方向是"撑得住/舞台感/不让场面冷场"；禁止 generic
    assert "乐观" in BEHAVIOR_PATTERNS["greatest_strength"]["surface"].split("禁止：")[1]
    assert "善于倾听" in BEHAVIOR_PATTERNS["greatest_strength"]["surface"].split("禁止：")[1]
    assert "撑得住" in BEHAVIOR_PATTERNS["greatest_strength"]["inner"]
