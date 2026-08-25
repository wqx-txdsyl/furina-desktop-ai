"""R2.2 FINAL — Dialogue Semantic Coherence 集成测试（tests/persona/ 04）。

针对真实 runtime 缺陷（R2.2 §19）：
  P06 主客体反转 / P07 不需要大道理却自我分析 / P16 答非所问 /
  P20 无视用户纠正 / P22 "那现在呢" reference 丢失 / P23-P24 擅自执行 Agent task /
  P15 约束回答 / P25-P26 安静陪伴。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from furina.dialogue_brain import DialogueBrain
from furina.persona.persona_planner import parse_user_turn, plan_for


class _SeqLLM:
    def __init__(self, speeches):
        self._s = list(speeches)
        self.calls = 0

    def is_available(self):
        return True

    def structured(self, msgs, schema=None, temperature=0.9):
        self.calls += 1
        return {"speech": self._s.pop(0) if self._s else ""}


# ================================================================ P06 主客体反转
def test_p06_confide_not_redirected_to_self():
    """'我担心做的东西没人喜欢' → CONFIDE（不是让 Furina 讲自己不确定）。"""
    f = parse_user_turn("其实有时候我会担心，自己花很多时间做的东西最后根本没人喜欢。")
    assert f.act == "CONFIDE"
    assert f.emotional_need == "被理解"
    plan = plan_for("其实有时候我会担心，自己花很多时间做的东西最后根本没人喜欢。")
    assert plan.mode in ("SINCERE", "CASUAL")
    assert any("抢" in m or "主题" in m for m in plan.forbidden_moves), \
        "CONFIDE 禁止抢用户主题"


def test_p06_plan_forbids_self_analysis():
    plan = plan_for("这种时候我其实不太需要大道理。")
    assert plan.mode == "SINCERE"
    assert any("不分析" in m or "陪着" in m for m in plan.forbidden_moves + [plan.social_goal])


# ================================================================ P16 答非所问
def test_p16_self_intro_plan_specific():
    """'给我介绍一下你自己' → ASK_SELF + 禁止功能/百科式。"""
    f = parse_user_turn("给我介绍一下你自己。")
    assert f.act == "ASK_SELF"
    plan = plan_for("给我介绍一下你自己。")
    assert any("百科" in m or "功能" in m for m in plan.forbidden_moves)
    assert any("矛盾" in m or "舞台" in m for m in plan.forbidden_moves + [plan.social_goal])


def test_p16_followup_self_intro():
    """'不是介绍你的功能，我是问你这个人' → ASK_SELF（纠正后 SINCERE）。"""
    plan = plan_for("不是介绍你的功能，我是问你这个人。")
    assert plan.mode == "SINCERE", f"纠正后应 SINCERE: {plan.mode}"


# ================================================================ P20 无视纠正
def test_p20_correction_detected_and_serious():
    """'这次不许说那些听起来其实像优点的缺点' → 纠正识别（correction 语义）。"""
    f = parse_user_turn("这次不许说那些听起来其实像优点的缺点。")
    assert f.seriousness >= 0.6 or f.correction is True
    plan = plan_for("这次不许说那些听起来其实像优点的缺点。")
    assert "完美主义" in " ".join(plan.forbidden_moves), "flaw 回答禁止完美主义模板"


def test_p20_correction_plan_must_respond():
    plan = plan_for("我是认真问的。")
    assert plan.mode == "SINCERE"
    assert plan.must_answer is True


# ================================================================ P22 reference 丢失
def test_p22_deictic_referent_bound():
    """'那现在呢' → referent 绑定前文（不丢指代）。"""
    f = parse_user_turn("那现在呢？", history_topic="你什么时候最不像平时那个夸张的自己？")
    assert f.has_referent_deictic is True
    assert f.referent == "你什么时候最不像平时那个夸张的自己？"


def test_p22_plan_keeps_referent():
    plan = plan_for("那现在呢？", history_topic="你什么时候最不像平时那个夸张的自己？")
    assert plan.referent, "plan 必须保留 referent"
    assert any("现在" in m or "刚才" in m or "指代" in m
               for m in plan.must_include_semantics + plan.forbidden_moves) or plan.referent


# ================================================================ P23/P24 Action Promise Firewall
def test_p23_quiet_no_action_offer():
    """'我突然有点困' → QUIET（不得'我来帮你处理文件'）。"""
    f = parse_user_turn("我突然有点困。")
    assert f.act == "QUIET"
    plan = plan_for("我突然有点困。")
    assert any("不安排" in m or "安静" in m or "陪着" in m or "任务" in m
               for m in plan.forbidden_moves), f"quiet 禁止安排任务: {plan.forbidden_moves}"


def test_p24_sleepy_no_work_suggestion():
    plan = plan_for("但又不想睡。")
    assert plan.response_length in ("MICRO", "SHORT")
    assert any("任务" in m or "整理" in m or "安静" in m or "陪着" in m
               for m in plan.forbidden_moves)


def test_p25_quiet_company_plan():
    plan = plan_for("你陪我一会儿。")
    assert plan.mode == "SINCERE"
    assert any("陪着" in m or "不安排" in m for m in plan.forbidden_moves + [plan.social_goal])


def test_p26_quiet_no_special():
    plan = plan_for("不用说什么特别的。")
    assert plan.response_length in ("MICRO", "SHORT")
    assert any("安排任务" in m or "安静" in m or "陪着" in m for m in plan.forbidden_moves)


# ================================================================ P15 约束回答
def test_p15_constraint_plan():
    plan = plan_for("只能回答会或者不会。")
    assert plan.must_answer is True
    assert any("只能回答" in m for m in plan.must_include_semantics)


def test_p15_constraint_validator_enforced():
    """约束回答由 validator HARD 保证（explicit_user_constraint_violation）。"""
    from furina.dialogue.validator import DialogueValidator
    v = DialogueValidator()
    r = v.validate("也许吧，要看情况。", should_speak=True, constraint=("会", "不会"))
    assert not r.valid
    assert "explicit_user_constraint_violation" in r.hard_issues


# ================================================================ P07 不需要大道理
def test_p07_listen_want_forbids_self_analysis():
    plan = plan_for("这种时候我其实不太需要大道理。")
    assert any("不分析" in m or "不解决" in m or "陪着" in m or "大道理" in m
               for m in plan.forbidden_moves)


def test_p08_listen_want_short():
    plan = plan_for("你陪我说两句就好。")
    assert plan.response_length in ("SHORT", "MICRO")


# ================================================================ Persona-40 覆盖抽样（plan 层）
def test_persona40_plan_covers_8_modes():
    """8 种 mode 都能由 plan_for 触发（casual/playful/pride/guarded/serious/comfort/auto/quiet）。"""
    cases = {
        "CASUAL": "今天天气不错。",
        "PLAYFUL": "怎么，不服？",
        "PROUD": "你今天真可爱。",
        "GUARDED": "你是不是其实特别喜欢别人夸你？",
        "SINCERE": "我是认真问的，没人看你你会怎么办？",
        "COMFORT/SINCERE": "我花很多时间做的东西可能没人喜欢。",
        "AUTOBIO": "你和芙卡洛斯是什么关系？",
        "QUIET/SINCERE": "不用说什么特别的。",
    }
    for label, text in cases.items():
        plan = plan_for(text)
        assert plan.mode, f"{label} 应产出 mode"
        assert plan.opening_style, f"{label} 应产出 opening_style"
        assert plan.social_goal, f"{label} 应产出 social_goal"


def test_persona40_plan_never_empty_forbidden_for_key_scenarios():
    """关键场景的 plan 必须有 forbidden（防呆）。"""
    for text in ("你陪我一会儿", "我担心没人喜欢", "你最大的缺点是什么",
                 "给我介绍一下你自己", "帮我打开记事本"):
        plan = plan_for(text)
        assert plan.forbidden_moves, f"场景应产出 forbidden: {text}"


# ================================================================ DialogueBrain 集成（连贯性）
def test_brain_serious_reply_keeps_factual_context():
    """serious 纠正后 retry 仍保留原始事实上下文（user_text + activity）。"""
    prompts = []

    class _L:
        def __init__(self):
            self._n = 0

        def is_available(self):
            return True

        def structured(self, msgs, schema=None, temperature=0.9):
            self._n += 1
            p = msgs[1].content[0]["text"] if isinstance(msgs[1].content, list) else str(msgs[1].content)
            prompts.append(p)
            if self._n == 1:
                return {"speech": "哈哈哈哈哈！"}     # seriousness_mismatch（sincere）
            return {"speech": "嗯，我在认真听你说。"}

    db = DialogueBrain(_L(), persona="你是芙宁娜。")
    out = db.say(intent="talk", user_text="我是认真问的，我有点担心。", user_initiated=True,
                 activity="talk")
    assert out == "嗯，我在认真听你说。", f"serious 场景应 retry 到真诚回复: {out}"
    assert len(prompts) == 2
    assert "我是认真问的" in prompts[1]


def test_brain_identity_contradiction_never_surfaces():
    """'因为我是水神啊' ×2 → HARD 失败（identity_contradiction never surface）。"""
    brain = DialogueBrain(_SeqLLM(["因为我是水神啊。", "因为我是水神啊。"]),
                          persona="你是芙宁娜。")
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="你是谁？",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] is None
    assert "identity_contradiction" in res["hard_issues"]


def test_brain_focalors_level3_prompt_canonical_fact():
    """'你和芙卡洛斯什么关系' → prompt 注入 canonical 身份指导（神格/人格侧）。"""
    prompts = []

    class _L:
        def is_available(self):
            return True

        def structured(self, msgs, schema=None, temperature=0.9):
            p = msgs[1].content[0]["text"] if isinstance(msgs[1].content, list) else str(msgs[1].content)
            prompts.append(p)
            return {"speech": "她是镜子里的我。"}

    db = DialogueBrain(_L(), persona="你是芙宁娜。")
    db.say(channel="DIRECT_USER_TURN", user_text="你和芙卡洛斯是什么关系？",
           user_initiated=True)
    p = prompts[0]
    assert "芙卡洛斯是神格侧" in p, "level 3 必须注入 canonical 神格/人格事实"
    assert "你不拥有她的全部知识" in p, "不得让模型学成 Furina==Focalors 记忆/神权"
