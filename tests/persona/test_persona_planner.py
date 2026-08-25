"""R2.2 FINAL — PersonaPlan / UserTurnFrame / Autobiographical 测试（tests/persona/ 02）。

覆盖（R2.2 §27）：
  - PersonaPlan >= 8
  - Autobiographical activation >= 8
  - Seriousness transition >= 5
  - Dialogue coherence >= 8（语义帧：主客体/指代/纠正/安静）
"""
from __future__ import annotations

import pytest

from furina.persona.persona_planner import (
    OPENING_STYLES, PersonaPlan, UserTurnFrame, parse_user_turn, plan_for,
)
from furina.persona.autobiographical import (
    EXPLICIT_REFERENCE, INDIRECT_REFERENCE, NONE, SHAPED_BY_HISTORY,
    ANCHORS, activation_level, lore_overexposition, match_anchors, prompt_guide,
)


# ================================================================ UserTurnFrame 语义帧
def test_frame_act_classification_basic():
    """基础 act 路由：问题/夸/逗/安静/陪伴/动作。"""
    assert parse_user_turn("你在干嘛？").act == "ANSWER"
    assert parse_user_turn("你今天真可爱").act == "PRAISE"
    assert parse_user_turn("怎么，不服？").act == "TEASE"
    assert parse_user_turn("我突然有点困").act == "QUIET"
    assert parse_user_turn("你陪我一会儿").act == "LISTEN_WANT"
    assert parse_user_turn("帮我打开记事本").act == "REQUEST_ACTION"


def test_frame_correction_detected():
    """'我是认真问的' → correction + seriousness 升。"""
    f = parse_user_turn("我是认真问的。")
    assert f.correction is True
    assert f.seriousness >= 0.9


def test_frame_constraint_extracted():
    """'只能回答会或者不会' → explicit_constraint。"""
    f = parse_user_turn("只能回答会或者不会。")
    assert f.explicit_constraint == ("会", "不会")


def test_frame_referent_deictic():
    """'那现在呢' → has_referent_deictic + referent 绑定前文。"""
    f = parse_user_turn("那现在呢？", history_topic="前文话题")
    assert f.has_referent_deictic is True
    assert f.referent == "前文话题"


def test_frame_confide_subject():
    """'我担心做出来没人喜欢' → CONFIDE + 情绪需求被理解。"""
    f = parse_user_turn("我担心自己花很多时间做的东西最后根本没人喜欢。")
    assert f.act == "CONFIDE"
    assert f.emotional_need == "被理解"


# ================================================================ PersonaPlan（>=8）
def test_plan_praise_mode_proud():
    plan = plan_for("你今天真可爱")
    assert plan.mode == "PROUD"
    assert "servile" in plan.social_goal or "接受赞美" in plan.social_goal
    assert plan.forbidden_moves, "被夸应有 forbidden（不得'谢谢夸奖'式）"


def test_plan_challenge_guarded():
    plan = plan_for("你是不是其实特别喜欢别人夸你，只是嘴上不承认？")
    assert plan.mode in ("GUARDED", "PLAYFUL")
    assert "立即承认" not in plan.social_goal
    assert any("护" in m or "姿态" in m for m in plan.forbidden_moves + [plan.social_goal])


def test_plan_serious_correction_transition():
    """R2.2 §13：'我是认真问的' → 戏剧强度下降（seriousness transition）。"""
    playful = plan_for("如果大家不关注你了，你会怎么办？", emotion="happy")
    serious = plan_for("如果大家不关注你了，你会怎么办？我是认真问的。", emotion="happy")
    assert serious.mode == "SINCERE", f"纠正后必须 SINCERE: {serious.mode}"
    assert serious.dramatic_intensity <= playful.dramatic_intensity + 1e-9, \
        "纠正后戏剧强度必须下降"


def test_plan_quiet_micro():
    plan = plan_for("我突然有点困，但又不想睡，你陪我一会儿")
    assert plan.mode == "SINCERE"
    assert plan.response_length in ("MICRO", "SHORT")
    assert any("不安排" in m or "安静" in m or "陪着" in m for m in plan.forbidden_moves + [plan.social_goal])


def test_plan_listen_want_no_analysis():
    plan = plan_for("这种时候我其实不太需要大道理，你陪我说两句就好。")
    assert plan.mode == "SINCERE"
    assert any("不分析" in m or "陪着" in m or "不解决问题" in m
               for m in plan.forbidden_moves + [plan.social_goal])


def test_plan_no_one_watches_not_generic():
    """'大家都不关注你了' → 禁止 generic '提升自己'。"""
    plan = plan_for("如果有一天大家都不再关注你了，你会怎么办？")
    assert any("提升自己" in m or "generic" in m for m in plan.forbidden_moves)


def test_plan_self_intro_specific():
    plan = plan_for("给我介绍一下你自己。")
    assert plan.mode == "SINCERE"
    assert any("舞台" in m or "stage" in m for m in plan.forbidden_moves + [plan.social_goal])
    assert any("百科" in m or "功能" in m for m in plan.forbidden_moves)


def test_plan_flaw_no_interview_answer():
    plan = plan_for("你觉得自己最大的缺点是什么？")
    assert any("完美主义" in m for m in plan.forbidden_moves)


def test_plan_action_request_responsible():
    plan = plan_for("帮我打开记事本")
    assert plan.mode == "RESPONSIBLE"
    assert any("事实" in m or "结果" in m or "编造" in m for m in plan.forbidden_moves + [plan.social_goal])


def test_plan_opening_style_variety():
    """opening styles 覆盖多种；重复同款会轮换。"""
    assert len(OPENING_STYLES) >= 8
    p1 = plan_for("今天好无聊", recent_openings=["DIRECT", "DIRECT"])
    assert p1.opening_style != "DIRECT" or "轮换" in p1.opening_style_reason


def test_plan_must_answer_constraint():
    plan = plan_for("只能回答会或者不会。")
    assert plan.must_answer is True
    assert any("只能回答" in m for m in plan.must_include_semantics)


# ================================================================ Autobiographical（>=8）
def test_auto_level_none_ordinary():
    """'今天吃什么？' → level 0（不调用历史）。"""
    assert activation_level("今天吃什么？") == NONE
    assert prompt_guide("今天吃什么？") == ""


def test_auto_level_shaped_by_history():
    """'为什么你这么喜欢别人注意你？' → ≥1（受历史影响但不强制名词）。"""
    lvl = activation_level("为什么你这么喜欢别人注意你？")
    assert lvl >= SHAPED_BY_HISTORY


def test_auto_level_indirect_reference():
    """'如果突然没人看你了呢？' → ≥2（可个人化引用）。"""
    lvl = activation_level("如果突然没人看你了呢？")
    assert lvl >= INDIRECT_REFERENCE


def test_auto_level_explicit_focalors():
    """'你和芙卡洛斯是什么关系？' → 3（可明确谈 Focalors）。"""
    lvl = activation_level("你和芙卡洛斯是什么关系？")
    assert lvl == EXPLICIT_REFERENCE, f"芙卡洛斯话题必须 level 3: {lvl}"


def test_auto_level_task_mode_zero():
    """task_mode（agent 报告）→ 0（不掺历史）。"""
    assert activation_level("你和芙卡洛斯是什么关系？", task_mode=True) == NONE


def test_auto_anchor_registry_complete():
    """至少 8 个 anchor（R2.2 §7.2）。"""
    required = ("FONT_AUDIENCE", "HYDRO_PUBLIC_ROLE", "FOCALORS", "LONG_PERFORMANCE",
                "TRIAL_END", "ORDINARY_LIFE", "CHOSEN_STAGE", "FEAR_OF_EXPOSURE")
    for a in required:
        assert a in ANCHORS, f"缺 anchor: {a}"


def test_auto_match_anchors():
    matched = match_anchors("如果大家都不关注你了")
    assert any(aid == "FONT_AUDIENCE" for aid, _s in matched)
    matched2 = match_anchors("你和芙卡洛斯是什么关系")
    assert any(aid == "FOCALORS" for aid, _s in matched2)


def test_lore_overexposition_not_triggered_when_relevant():
    """level≥2 且相关性高：谈芙卡洛斯不算 overexposition。"""
    ok, _reason = lore_overexposition("芙卡洛斯是我的另一面，镜子里的我。",
                                      matched=True, level=3)
    assert ok is False


def test_lore_overexposition_triggered_when_irrelevant():
    """普通闲聊（level≤1）无端历史名词 → overexposition。"""
    ok, reason = lore_overexposition("我今天心情不错，想起枫丹的水神和芙卡洛斯的故事了。",
                                     matched=False, level=0)
    assert ok is True and "历史名词" in reason


def test_auto_sincere_trust_raises_level():
    """SINCERE + 高信任 → 允许更显式。"""
    lvl_low = activation_level("你是不是在装？", mode="CASUAL", trust=0.3)
    lvl_high = activation_level("你是不是在装？", mode="SINCERE", trust=0.8)
    assert lvl_high >= lvl_low


# ================================================================ Seriousness transition（>=5）
def test_seriousness_transition_plan_vs_playful():
    """同一话题：playful → 认真问 → SINCERE 且戏剧下降、本神 off。"""
    p1 = plan_for("如果大家不关注你了，你会怎么办？", emotion="excited")
    p2 = plan_for("如果大家不关注你了，你会怎么办？我是认真问的。", emotion="excited")
    assert p2.mode == "SINCERE"
    assert p2.dramatic_intensity < p1.dramatic_intensity
    assert p2.god_register in ("off",) or p1.god_register != "off"


def test_seriousness_transition_forbidden_generic():
    """认真问'没人关注' → forbidden 含'提升自己'式 generic。"""
    plan = plan_for("我是认真问的，如果大家都不再关注你了你会怎么办？")
    assert any("提升自己" in m for m in plan.forbidden_moves)


def test_seriousness_transition_comfort_no_lecture():
    plan = plan_for("我花很多时间做的东西可能没人喜欢，我很担心。")
    assert plan.mode in ("SINCERE", "CASUAL")
    assert any("鼓励" in m or "鸡汤" in m or "抢" in m for m in plan.forbidden_moves)


def test_seriousness_transition_quiet_stays_short():
    plan = plan_for("不用说什么特别的。")
    assert plan.response_length in ("MICRO", "SHORT")
    assert "MICRO" == plan.response_length or len(plan.forbidden_moves) >= 3


def test_seriousness_intensity_bounds():
    """每个 mode 的 dramatic_intensity 都在 furina_canon 强度带内。"""
    from furina.persona.furina_canon import DRAMATIC_INTENSITY
    # 通过不同 act 触发不同 mode，再检查强度带
    cases = {
        "QUIET": "我突然有点困",
        "LISTEN_WANT": "你陪我说两句",
        "CONFIDE": "我担心做出来没人喜欢",
        "CHALLENGE": "你是不是在装？",
        "PRAISE": "你今天真可爱",
        "TEASE": "怎么，不服？",
        "REQUEST_ACTION": "帮我打开记事本",
        "ASK_SELF": "介绍一下你自己",
        "ANSWER": "你在干嘛？",
    }
    seen = set()
    for want_mode, text in cases.items():
        plan = plan_for(text)
        lo, hi = DRAMATIC_INTENSITY.get(plan.mode, (0.3, 0.5))
        assert lo - 0.01 <= plan.dramatic_intensity <= hi + 0.01, \
            f"{plan.mode} 强度应在 [{lo},{hi}]: {plan.dramatic_intensity}"
        seen.add(plan.mode)
    # 至少覆盖 4 种不同 mode（不同 act 路由到不同强度带）
    assert len(seen) >= 4, f"应覆盖多种 mode: {seen}"


# ================================================================ R2.2.1 §1/§2：Production Truth
def _real_new_user_factors():
    """真实 RelationshipState() 初始 factors（trust=0, familiarity=0, annoyance=0 的 0..1 契约）。"""
    from furina.relationship.engine import RelationshipEngine, relationship_factors
    fac = relationship_factors(RelationshipEngine().state)
    return (fac["trust"], fac["familiarity"], fac["annoyance"])


def test_r221_real_relationship_initial_not_all_guarded():
    """R2.2.1 §1：真实 RelationshipState 初值不得让所有 act 都 GUARDED。"""
    t, fam, ann = _real_new_user_factors()
    assert t == 0.0 and fam == 0.0 and ann == 0.0, "新用户关系初值应为 0"
    cases = {
        "correction": "我是认真问的，没人看你你会怎么办？",
        "confide": "我担心自己做的没人喜欢。",
        "quiet": "不用说什么特别的。",
        "action": "帮我打开记事本。",
        "tease": "怎么，不服？",
    }
    modes = {label: plan_for(text, trust=t, familiarity=fam, annoyance=ann).mode
             for label, text in cases.items()}
    assert modes["correction"] == "SINCERE", f"correction 不得被低 trust 覆盖: {modes}"
    assert modes["confide"] == "SINCERE", f"confide 不得被低 trust 覆盖: {modes}"
    assert modes["quiet"] == "SINCERE", f"quiet 不得被低 trust 覆盖: {modes}"
    assert modes["action"] == "RESPONSIBLE", f"RESPONSIBLE 不得被关系覆盖: {modes}"
    assert len({m for m in modes.values()}) >= 3, f"mode 应多样化: {modes}"


def test_r221_low_trust_reduces_intimacy_vuln_auto():
    """R2.2.1 §1：低 trust 降低 intimacy/vulnerability/autobiography explicitness。"""
    t0, fam, ann = _real_new_user_factors()
    hi = plan_for("你和芙卡洛斯是什么关系？", trust=0.8, familiarity=0.8, annoyance=0.05)
    lo = plan_for("你和芙卡洛斯是什么关系？", trust=t0, familiarity=fam, annoyance=ann)
    assert lo.intimacy_level <= 0.35, f"低 trust intimacy 应受限: {lo.intimacy_level}"
    assert hi.intimacy_level > lo.intimacy_level
    assert lo.autobiography_activation <= 1, f"低 trust 自传显式度应受限: {lo.autobiography_activation}"


def test_r221_high_annoyance_only_affects_social_modes():
    """R2.2.1 §1：高 annoyance 只影响适合被关系影响的社交 mode。"""
    hi_ann = plan_for("你陪我一会儿。", trust=0.0, familiarity=0.0, annoyance=0.8)
    assert hi_ann.mode == "SINCERE", f"LISTEN_WANT 不得被高烦覆盖: {hi_ann.mode}"
    resp = plan_for("帮我打开记事本。", trust=0.0, familiarity=0.0, annoyance=0.8)
    assert resp.mode == "RESPONSIBLE", f"RESPONSIBLE 不得被高烦覆盖: {resp.mode}"
    social = plan_for("你今天真可爱。", trust=0.0, familiarity=0.0, annoyance=0.8)
    assert social.mode == "GUARDED", "高烦下 PRAISE 社交 mode 可压 GUARDED"


def test_r221_correction_sincere_at_trust_zero():
    """R2.2.1 §2：trust=0 下 correction → SINCERE + dramatic intensity 下降。"""
    t, fam, ann = _real_new_user_factors()
    playful = plan_for("如果大家不关注你了，你会怎么办？", trust=t, familiarity=fam, annoyance=ann,
                       emotion="happy")
    serious = plan_for("如果大家不关注你了，你会怎么办？我是认真问的。", trust=t, familiarity=fam,
                       annoyance=ann, emotion="happy")
    assert serious.mode == "SINCERE", f"correction 在 trust=0 必须 SINCERE: {serious.mode}"
    assert serious.dramatic_intensity <= playful.dramatic_intensity + 1e-9, \
        f"correction 后戏剧强度必须下降: {serious.dramatic_intensity} vs {playful.dramatic_intensity}"
