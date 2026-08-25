"""Phase 13 Pre-Manual Blocker Repair R1 — B3 Persona Surface Guard（PERSONA-L1..L9）。

机制测试（不测 exact output，不靠 hardcoded 问答映射）：
  - validator 可解释 issue：generic_assistant_identity / nonhuman_user_framing /
    repetitive_opening / ungrounded_activity；describe() 给 retry 明确反馈；
  - 重复"哎呀"式 opener 有界 guard（连 3 触发，单次合法）；
  - activity grounding 硬约束（read 不得声称探索；rest 合法自然描述通过）；
  - SYSTEM_STATUS 不做 Persona validation；retry 保持原始事实上下文。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from furina.dialogue.validator import DialogueValidator
from furina.dialogue_brain import DialogueBrain


_v = DialogueValidator()


# ================================================================ PERSONA-L1
def test_persona_l1_validator_detects_generic_ai_identity():
    """L1：'作为AI，我可以帮助你完成任务。' → generic_assistant_identity。"""
    r = _v.validate("作为AI，我可以帮助你完成任务。", should_speak=True, context="casual")
    assert not r.valid
    assert "generic_assistant_identity" in r.issues, r.issues
    assert r.describe() and "AI" in r.describe(), "describe 必须给出可解释反馈"


def test_persona_l1_detects_my_function_is():
    r = _v.validate("我的功能是帮你管理桌面。", should_speak=True, context="casual")
    assert "generic_assistant_identity" in r.issues


# ================================================================ PERSONA-L2
def test_persona_l2_validator_detects_nonhuman_user_framing():
    """L2：'你们人类的生活真有趣。' → nonhuman_user_framing（把自己放观察者位置）。"""
    r = _v.validate("你们人类的生活真有趣。", should_speak=True, context="casual")
    assert not r.valid
    assert "nonhuman_user_framing" in r.issues, r.issues


def test_persona_l2_word_human_alone_is_not_banned():
    """'人类'一词本身不禁（可说'人'）；只拘非人类观察者框架。"""
    r = _v.validate("我最近在看一本关于人的书。", should_speak=True, context="casual")
    assert r.valid, r.issues


# ================================================================ PERSONA-L3/L4
def test_persona_l3_third_repeated_opener_triggers_feedback():
    """L3：'哎呀'×3 连续 direct replies → 第三个触发 repetitive_opening。"""
    recent = ["哎呀，我在看书。", "哎呀，今天天气不错。"]
    r = _v.validate("哎呀，你来了。", should_speak=True, context="casual",
                    recent_surface=recent)
    assert not r.valid
    assert "repetitive_opening" in r.issues, r.issues
    assert r.describe() and "开场" in r.describe()


def test_persona_l4_single_opener_is_legal():
    """L4：一次'哎呀'（前面是不同的开场）必须合法。"""
    recent = ["嗯，我在呢。", "哼，你又来啦。"]
    r = _v.validate("哎呀，你来了。", should_speak=True, context="casual",
                    recent_surface=recent)
    assert r.valid, r.issues


def test_persona_l3_via_dialogue_brain_retry():
    """L3 集成：第 3 个'哎呀'触发 retry，retry 换开场后通过（不静音、不硬删）。"""
    class _LLM:
        def __init__(self):
            self._s = ["哎呀，我在看书。", "哎呀，今天天气不错。",
                       "哎呀，你来了。", "嗯，我在呢。"]
        def is_available(self): return True
        def structured(self, msgs, schema=None, temperature=0.9):
            return {"speech": self._s.pop(0) if self._s else ""}
    db = DialogueBrain(_LLM(), persona="你是芙宁娜。")
    out1 = db.say(intent="talk", user_text="一", user_initiated=True)
    out2 = db.say(intent="talk", user_text="二", user_initiated=True)
    assert out1 and out2, "前两个'哎呀'合法（不永久禁止）"
    out3 = db.say(intent="talk", user_text="三", user_initiated=True)
    assert out3 == "嗯，我在呢。", f"第三个'哎呀'必须 retry 换开场: {out3}"


# ================================================================ PERSONA-L5/L6
def test_persona_l5_activity_read_grounding_rejects_explore_claim():
    """L5：activity=read，声称在探索 → ungrounded_activity（拒绝/retry）。"""
    r = _v.validate("我在探索新事物呢，你怎么知道？", should_speak=True,
                    activity="read", context="casual")
    assert not r.valid
    assert "ungrounded_activity" in r.issues, r.issues
    # 经 DialogueBrain：read 下 LLM 声称 explore → 双重失败 → None（不泄漏 invalid 输出）
    class _LLM:
        def __init__(self):
            self._s = ["我在探索新事物呢。", "我在探索新事物呢。"]
        def is_available(self): return True
        def structured(self, msgs, schema=None, temperature=0.9):
            return {"speech": self._s.pop(0) if self._s else ""}
    db = DialogueBrain(_LLM(), persona="你是芙宁娜。")
    out = db.say(intent="talk", user_text="你在干嘛？", user_initiated=True, activity="read")
    assert out is None
    assert db.last_failure_reason == "validation_twice_invalid"


def test_persona_l6_rest_natural_description_passes():
    """L6：activity=rest，合法自然描述（无'休息'字样）必须通过（semantic，非 substring）。"""
    r = _v.validate("刚把书放下，打算发会儿呆。", should_speak=True,
                    activity="rest", context="casual")
    assert r.valid, r.issues


# ================================================================ PERSONA-L7
def test_persona_l7_system_status_not_persona_validated():
    """L7：SYSTEM_STATUS 不做 Persona validation（should_speak=False → 直接跳过）。"""
    r = _v.validate("（系统状态：刚才的回复生成失败。）", should_speak=False)
    assert r.valid, "系统状态文本不做 Persona 校验"
    # 生产路径：失败 → app 发 SYSTEM_STATUS，不经 DialogueBrain 台词校验
    import furina.app as A
    src = open(A.__file__, encoding="utf-8").read()
    bw = src[src.index("def _brain_worker"):src.index("def _recent_memories")]
    assert "system_status" in bw.lower() or "SYSTEM_STATUS" in bw or "系统状态" in bw, \
        "失败必须走 SYSTEM_STATUS 路径"


# ================================================================ PERSONA-L8
def test_persona_l8_retry_keeps_original_factual_context():
    """L8：direct user question 的 retry 仍保持原始事实上下文（user_text + activity）。"""
    prompts = []

    class _LLM:
        def __init__(self):
            self._n = 0
        def is_available(self): return True
        def structured(self, msgs, schema=None, temperature=0.9):
            self._n += 1
            prompts.append(msgs[1].content[0]["text"] if isinstance(msgs[1].content, list)
                           else str(msgs[1].content))
            if self._n == 1:
                return {"speech": "（叹气）好吧"}     # invalid → retry
            return {"speech": "在看书，怎么，你有事？"}  # retry valid
    db = DialogueBrain(_LLM(), persona="你是芙宁娜。")
    out = db.say(intent="talk", user_text="你在干嘛？", user_initiated=True, activity="read")
    assert out == "在看书，怎么，你有事？"
    assert len(prompts) == 2, "必须有 retry"
    assert "你在干嘛？" in prompts[1], "retry prompt 必须保留原始 user_text"
    assert "read" in prompts[1] and "正在做的事" in prompts[1], "retry 必须保留活动事实"


# ================================================================ PERSONA-L9
def test_persona_l9_no_hardcoded_question_answer_mapping():
    """L9：生产代码不得含'测试问题 → 固定回答'的映射（无 if/==/dict 特判）。

    prompt 指令里提及问题文本（如 grounding 说明）是合法的；禁止的是把它当 key 映射到回答。
    """
    import re
    import furina.dialogue_brain as D
    src = open(D.__file__, encoding="utf-8").read()
    phrases = ("你在干嘛", "还挺悠闲", "没人管你", "会自己找事情做", "无聊到趴在桌面上")
    eq_map = re.findall(r'(user_text|text)\s*==\s*["\'](' + "|".join(phrases) + r")", src)
    assert not eq_map, f"不得把测试问题当条件特判: {eq_map}"
    dict_map = re.findall(r'["\'](' + "|".join(phrases) + r')["\']\s*[:=]', src)
    assert not dict_map, f"不得把测试问题映射到回答: {dict_map}"
    # classify_act 是 act 路由（COMMENT/QUESTION…），不是逐句答案表
    assert "classify_act" in src
