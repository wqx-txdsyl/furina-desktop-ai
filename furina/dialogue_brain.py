"""DialogueBrain —— 「语言」：只负责“既然我要表达这个意图，作为芙宁娜应该怎么说”。

三脑架构：与 LifeBrain/Tool Agent 严格隔离。
- 不决定：要不要说、何时说、要不要走/打断/睡觉（那是 LifeBrain）。
- 不决定：怎么操作电脑（那是 Tool Agent）。
- 只做：给一个意图 + 上下文 + 人格，产出符合芙宁娜口吻的一句话/一段话。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from furina.core import get_logger
from furina.llm import LLMAdapter, LLMMessage, content
from furina.persona import FURINA_PERSONA

log = get_logger("dialogue_brain")

_DIALOGUE_SCHEMA = {
    "type": "object",
    "properties": {
        "speech": {"type": "string"},
        "emotion_hint": {"type": "string"},
    },
    "required": ["speech"],
}


class DialogueBrain:
    def __init__(self, llm: LLMAdapter, persona: str = FURINA_PERSONA, identity=None) -> None:
        self.llm = llm
        self.persona = persona
        self.identity = identity
        # 表达引擎（确定性：ShouldSpeak/Mode/Intent/Strategy；不占决策）
        from furina.dialogue import ExpressionEngine, DialogueValidator
        self.expression = ExpressionEngine(identity)
        self.validator = DialogueValidator()
        # 短期重复控制（§40）
        self._recent_acts: List[str] = []
        self._recent_modes: List[str] = []
        # Phase 13C §24-26：有界短期对话上下文（内存，非数据库）
        self._history: List[Dict[str, Any]] = []
        self._history_limit = 8
        # "本神" Micro-Calibration Gate（Phase 10：情境化，非强制，短生命周期，不进 Memory）
        from furina.dialogue.god_calibration import GodCalibrationGate
        self.god_gate = GodCalibrationGate()

    def push_history(self, role: str, text: str) -> None:
        """短期对话上下文（bounded）。只存发言，不存系统 prompt。"""
        if not text:
            return
        self._hist_seq = getattr(self, "_hist_seq", 0) + 1
        self._history.append({"role": role, "text": str(text), "seq": self._hist_seq})
        self._history = self._history[-self._history_limit:]

    def recent_turns(self, n: int = 4) -> List[Dict[str, Any]]:
        return list(self._history[-n:])

    # -------------------------------------------------- Phase 13C §19-20：确定性 DialogueAct 路由
    def classify_act(self, user_text: str = "") -> str:
        """高置信地把常见用户输入路由到有意义的 act（不新增 LLM）。默认 COMMENT。"""
        import re
        t = (user_text or "").strip()
        if not t:
            return "COMMENT"
        if re.search(r"[?？]|吗|呢|干嘛|什么|几|哪|是不是|怎么样", t):
            return "RESPONSE_TO_QUESTION"
        if re.search(r"别烦|别吵|走开|别打扰|要忙|没空|安静|离我远点", t):
            return "DECLINE"
        if re.search(r"累|难过|伤心|压力|辛苦|烦死|不开心", t):
            return "COMFORT"
        if re.search(r"可爱|好看|喜欢|棒|厉害|真好|爱你|厉害呀", t):
            return "REACT"
        if re.search(r"谢谢|感谢|多谢", t):
            return "REFLECT"
        return "COMMENT"

    def say(self, *, intent: str = "", emotion: str = "", user_text: str = "",
            context: Optional[str] = "", memories: Optional[List[str]] = None,
            world: Optional[dict] = None, activity: str = "",
            relationship: Optional[dict] = None, memory_interp: Optional[dict] = None,
            user_initiated: bool = False, task_mode: bool = False,
            solitude: bool = False, user_present: bool = True) -> Optional[str]:
        """生成一句符合人格、有真实上下文的中文台词，或 None（沉默，§5/§39）。

        world/relationship/memory_interp 提供具体细节。可通过 expression 层决定 should_speak。
        """
        # 1) Expression Appraisal（确定性）：ShouldSpeak / Mode / Intent / Strategy
        app = self.expression.appraise(
            emotion=emotion, intent=intent, user_text=user_text,
            relationship=relationship, world=world, memory=memory_interp,
            activity=activity, user_initiated=user_initiated,
            task_mode=task_mode, solitude=solitude, user_present=user_present,
            user_working=bool((world or {}).get("user_working", False)),
            recent_dialogue=self._recent_acts)
        # 2) Should Speak? —— Silence 是正式行为（§5）
        if not app.should_speak:
            return None
        # Phase 13C §19-20：用户发起的对话用确定性 act 路由覆盖（question/praise/reject/comfort 不再全 COMMENT）
        if user_text:
            app.dialogue_act = self.classify_act(user_text)
        # 2b) "本神" 情境化校准（Phase 10）：只改 prompt 引导，不强制；给出语境偏好
        from furina.dialogue.god_calibration import (
            GodCalibrationGate, PREFERRED_MODES, PREFERRED_ACTS)
        god_cal = self.god_gate.calibrate(mode=app.mode, dialogue_act=app.dialogue_act,
                                          emotion=emotion, user_text=user_text)
        # 3) 相关 synthetic examples（Top-K=3，C-R1.6 按 act→example context 路由，不全靠 ex.context==act.lower()）
        examples = self._select_examples(app, emotion, activity=activity, user_text=user_text)
        # 4) 生成 prompt + LLM。C-R1.3.1：history 只含**当前轮之前**的发言，当前 user_text 单独附一次，
        #    避免"最近对话"与"用户：..."重复当前内容。
        hist = self.recent_turns(4)
        prompt = _dialogue_prompt_v2(app, intent=intent, emotion=emotion,
                                     user_text=user_text, context=context,
                                     memories=memories, world=world,
                                     examples=examples, person=self.persona,
                                     activity=activity,
                                     history=hist)
        if user_text:
            self.push_history("user", user_text)   # 当前轮入历史（供下一轮），但本 prompt 不含它
        # 4b) 注入"本神"语境 advice（非强制）
        prompt += "\n" + self.god_gate.prompt_advice(god_cal)
        try:
            if not self.llm.is_available():
                return None
            msgs = [
                LLMMessage("system", content(self.persona)),
                LLMMessage("user", content(prompt)),
            ]
            out = self.llm.structured(msgs, schema=_DIALOGUE_SCHEMA, temperature=0.9)
            speech = str(out.get("speech", "")).strip()
        except Exception as e:  # pragma: no cover
            log.warning("DialogueBrain 失败: %s", e)
            speech = ""
        if not speech:
            return None   # 沉默优先于 Generic fallback（§39）
        # 5) Deterministic Validation（§38）
        v = self.validator.validate(speech, should_speak=True,
                                    example_phrases=[ex["speech"] for ex in examples],
                                    activity=activity, context=app.mode.lower())
        if not v.valid and "generic_assistant_voice" in v.issues:
            return None
        # 5b) "本神" 校准 Gate（§21-25）：抑制语境出现"本神"或触发 cooldown → 软拦截（不强制替换）
        gated = self.god_gate.gate_output(speech, cal=god_cal)
        if gated is None:
            self.god_gate.note_spoke_god(speech)   # 仍记录，避免下一轮立刻又出
            return None
        speech = gated
        # 6) 短期重复控制（§40 / Phase 13C §21）：避免连续同 act / same句式。
        #    **用户发起的直接对话必须收到回应**（不能因 act 标签重复而永久静音）；
        #    重复控制只影响自主发言的措辞/节奏，不影响给用户的回应。
        self._recent_acts.append(app.dialogue_act)
        self._recent_acts = self._recent_acts[-3:]
        if not user_initiated and len(self._recent_acts) >= 3 and len(set(self._recent_acts)) == 1:
            return None
        self.push_history("furina", speech)   # §24-26 短期上下文
        return speech

    # -------------------------------------------------- synthetic example 检索（§29 / C-R1.6 路由）
    @staticmethod
    def _route_example_context(act: str, activity: str, user_text: str) -> str:
        """act/activity/user_text → 目标 example context（for few-shot routing）。"""
        t = user_text or ""
        if act == "RESPONSE_TO_QUESTION":
            if re.search(r"记|说|刚才|上次|之前|准备|打算", t):
                return "memory_callback"
            return "question_activity"
        if act == "DECLINE":
            return "rejection"
        if act == "REACT":
            return "praise"
        if act == "COMFORT":
            return "comfort"
        # §11.1：Agent 失败 → agent_failure；成功/报告 → agent_success（不再一律 agent_success）
        a = f"{act} {activity}".lower()
        if "fail" in a or "unable" in a:
            return "agent_failure"
        if "agent" in a or act in ("agent_report", "assist_user"):
            return "agent_success"
        if act == "REFLECT":
            return "high_trust"
        return ""

    def _select_examples(self, app, emotion: str = "", activity: str = "",
                         user_text: str = "") -> list:
        try:
            from furina.persona.expression_examples import get_examples
            pool = get_examples()
        except Exception:
            return []
        mode = app.mode; act = app.dialogue_act
        target = self._route_example_context(act, activity, user_text)   # C-R1.6
        _em = {"proud": "praise", "embarrassed": "embarrassment", "sad": "ignored",
               "annoyed": "user_busy", "happy": "praise", "calm": "casual",
               "excited": "performing", "curious": "casual", "lonely": "user_return",
               "tired": "casual", "neutral": "casual", "sincere": "casual"}
        emot_ctx = _em.get((emotion or "").lower(), "casual")
        scored = []
        for ex in pool:
            score = 0.0
            if target and ex["context"] == target:
                score += 3.0
            if ex["context"] == mode.lower():
                score += 1.5
            if ex.get("context") == emot_ctx:
                score += 0.5
            scored.append((score, ex))
        scored.sort(key=lambda x: -x[0])
        return [ex for _, ex in scored[:3]]

    def interpret(self, user_text: str) -> Dict[str, Any]:
        """理解用户一句话（如需，返回结构化意图提示给 Brain）。预留，不承担决策。"""
        return {"user_text": user_text}


def _fallback_line(intent: str, emotion: str) -> str:
    pool = {
        "observe_user": ["你在忙什么呀？", "唔…今天也要加油哦。"],
        "talk": ["哼，本神可忙着呢。", "有话快说~"],
        "sleep": ["哈欠……本神先闭目养神了。", "晚安……"],
        "eat": ["嗯…味道不错嘛。", "多谢款待~"],
        "play": ["陪我玩一会儿嘛~", "嘿嘿，看好了！"],
        "approach_user": ["喂——", "本神来了。"],
        "rest": ["本神歇会儿。", "呼……"],
    }
    import random
    return random.choice(pool.get(intent, ["嗯，知道了。"]))


def _dialogue_prompt(*, intent: str, emotion: str, user_text: str, context: str,
                     memories: Optional[List[str]], world: Optional[dict]) -> str:
    parts = []
    # 具体世界细节（让语言“有真实上下文理由”，而非 AI 套话）
    if world:
        parts.append("当前世界：")
        if world.get("user_working"):
            parts.append(f"- 用户正在{world.get('user_app','工作')}（{world.get('user_title','')}）")
        elif world.get("user_idle_seconds", 0) and world["user_idle_seconds"] >= 180:
            parts.append("- 用户已经离开/空闲好一会儿了")
        else:
            parts.append("- 用户现在没在忙")
        parts.append(f"- 时间：{world.get('time','')}（{world.get('day_phase','')}）")
        if world.get("self_state"):
            parts.append(f"- 你自己：{world['self_state']}")
        if world.get("recent_events"):
            parts.append("- 最近发生：" + "；".join(world["recent_events"][-4:]))
        parts.append("")
    if user_text:
        parts.append(f"用户刚才说：{user_text}")
    if intent:
        parts.append(f"你当前想表达的意图：{intent}")
    if emotion:
        parts.append(f"你当前的情绪：{emotion}")
    if context:
        parts.append(f"你想说的话的核心：{context}")
    if memories:
        parts.append("你记得：" + "；".join(memories[:3]))
    parts.append(
        "请作为芙宁娜只说**一句话**自然的口语化回应，遵守：\n"
        "- 必须基于上面的具体世界细节/最近事件，说出**具体内容**，不要空泛。\n"
        "- 禁止：'你好呀''需要帮忙吗''今天过得怎么样''我一直都在哦'这类万金油话术；\n"
        "- 禁止每句都喊用户/卖萌/解释自己是AI；语气自然、有个性。\n"
        '- 严格只输出 JSON：{"speech":"一句话"}。只输出 JSON。')
    return "\n".join(parts)


def _dialogue_prompt_v2(app, *, intent: str, emotion: str, user_text: str, context: str,
                        memories: Optional[List[str]], world: Optional[dict],
                        examples: list, person: str, activity: str = "",
                        history: Optional[List[dict]] = None) -> str:
    """Phase 08B 结构化 prompt：Compact Contract + Mode + Intent + Strategy + Context + Examples + Constraints。
    Phase 13C：加"说话机制"引导（§43-44）与短期对话上下文（§24-26）。"""
    ap = app.to_prompt()
    parts = []
    parts.append("【你的角色（精简）】\n你是一个已经卸下'水神'职责、正在以普通人身份重新生活的芙宁娜。"
                 "依然鲜明、戏剧化、爱表演、爱被关注，但这是你主动的选择，不是维持神职的面具；"
                 "你自尊、要强、嘴硬，但底子有点不安，很在乎真心对你的人；"
                 "你正在学着不靠表演也能真诚地和人连接。自称'本神'，但**有度**，日常多数时候就是自然的你自己。")
    # §43-44：角色语言机制（指导**如何组织语言**，不是固定模板）
    parts.append(
        "【说话机制（不是模板，是用语言达成这些的方式）】\n"
        "1. 表演是**主动选择的社会工具**：想要控制/被关注时可来一小段，但别一直演。\n"
        "2. 尊严先于直接示弱：需求/窘迫常先以间接方式出现，再慢慢承认。\n"
        "3. 暴露后的快速找回：被看穿/尴尬后，往往试着重新稳住姿态，而不是一直害羞。\n"
        "4. 注意力敏感：被夸/被无视/被认真对待，措辞会不一样。\n"
        "5. 公开自信 vs 私下真诚的对照：认真/帮助时收住表演，不是简单降低'俏皮'。\n"
        "6. 具体社交节奏：可以转移、打折扣、自我更正、先夸大再弱化、或假装某句本是有意。\n"
        "7. 卸任后的默认：不总演旧神职；表演是选择，不是必须戴的面具。")
    parts.append(f"【当前表达姿态】mode={ap['mode']}" +
                 (f" (次级 {ap['secondary_mode']})" if ap["secondary_mode"] else "") +
                 f" | dialogue_act={ap['dialogue_act']}")
    parts.append(f"【表达策略】{ap['strategy']}")
    ctx = []
    if activity:                      # Phase 13C §22：活动 grounding 必须进 prompt（回答"你在干嘛"由真实活动驱动）
        ctx.append(f"- 正在做的事: {activity}")
    if context:                      # FIX I：speech_intent/具体语境真正写入 prompt
        ctx.append(f"- 想说的话核心: {context}")
    if world:
        ctx.append(f"- 世界: 用户{'正在'+world.get('user_activity','') if world.get('user_activity') else ''}"
                   f"{'（专注工作，不该打扰）' if world.get('interruption_cost',0)>0.6 else ''}")
        if world.get("recent_events"):
            ctx.append("- 最近: " + "；".join(world["recent_events"][-3:]))
    if emotion:
        ctx.append(f"- 情绪: {emotion}")
    if memories:
        ctx.append("- 记得: " + "；".join(memories[:3]))
    if ctx:
        parts.append("【当前情境】\n" + "\n".join(ctx))
    if examples:
        parts.append("【语气范例（只学表达方式，不要背句子）】")
        for e in examples:
            parts.append(f"  {e['speech']}")
    if history:
        parts.append("【最近对话（仅作延续参考，不要复述）】")
        for h in history[-3:]:
            role = "用户" if h["role"] == "user" else "芙宁娜"
            parts.append(f"  {role}: {h['text']}")
    if user_text:
        parts.append(f"用户：{user_text}")
    elif intent:
        parts.append(f"（你正想表达：{intent}）")
    parts.append(
        "请作为芙宁娜说一句自然、有真实感的中文回应。遵守：\n"
        "- 只根据上面情境说**具体内容**，不空泛；可以骄傲、可以嘴硬、可以真诚，但要自然有起伏。\n"
        "- 普通闲聊不要突然聊'五百年/孤独/水神'；被夸可以得意但别每句都'本神'。\n"
        "- 禁止：'你好呀''需要帮忙吗''今天过得怎么样''有什么可以帮你'这类万金油；禁止舞台动作描写（*叹气* 等）。\n"
        '- 严格只输出 JSON：{"speech":"一句话"}。')
    return "\n".join(parts)
