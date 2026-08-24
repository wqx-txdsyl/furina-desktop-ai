"""Expression Appraisal 引擎（Phase 08B 核心）—— 从 Runtime 状态确定性算出 ExpressionAppraisal。

Inputs（由调度器/调用方传入）：
    emotion / relationship(factors) / world(factors + events) / memory(interpretation)
    activity / user_text(user initiated?) / identity(activation)

Outputs：mode / dialogue_act / should_speak / speech_drive / SpeechIntent / ExpressionStrategy。
全部确定性，不用 LLM 猜测。LLM 只负责把 strategy 变成自然语言。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from furina.persona.character_identity import CharacterIdentity, activation_gain
from furina.persona.furina_character_contract import mode_for as _contract_mode
from .expression import (
    ExpressionAppraisal, ExpressionStrategy, PersonaMode, DialogueAct,
    SpeechIntent, SpeechLength, ShouldSpeakDecision,
)

# 情感类（确定性：identity 稳定 trait → 各维度基线，由 context 调节，非硬编码台词）
_EMOTION_BASE = {
    "proud":    {"confidence": 0.75, "dramatic_intensity": 0.7, "directness": 0.65,
                 "defensiveness": 0.4, "playfulness": 0.45},
    "happy":    {"confidence": 0.65, "dramatic_intensity": 0.5, "playfulness": 0.65,
                 "warmth": 0.7, "sincerity": 0.6},
    "excited":  {"dramatic_intensity": 0.75, "confidence": 0.7, "playfulness": 0.7,
                 "emotional_openness": 0.6},
    "curious":  {"dramatic_intensity": 0.5, "directness": 0.5, "playfulness": 0.5},
    "calm":     {"dramatic_intensity": 0.25, "sincerity": 0.55, "warmth": 0.5},
    "sleepy":   {"dramatic_intensity": 0.15, "brevity": 0.8, "warmth": 0.4},
    "embarrassed": {"confidence": 0.55, "defensiveness": 0.7, "vulnerability_visibility": 0.3,
                    "directness": 0.4, "dramatic_intensity": 0.4},
    "annoyed":  {"warmth": 0.25, "brevity": 0.75, "defensiveness": 0.6,
                 "dramatic_intensity": 0.3},
    "sad":      {"dramatic_intensity": 0.3, "confidence": 0.4, "brevity": 0.6,
                 "emotional_openness": 0.6},
    "lonely":   {"emotional_openness": 0.4, "dramatic_intensity": 0.35, "brevity": 0.5},
}


class ExpressionEngine:
    """确定性表达评估器。"""

    def __init__(self, identity: Optional[CharacterIdentity] = None) -> None:
        self.identity = identity

    # -------------------------------------------------- Should Speak（§4-§6）
    def should_speak(self, *, emotion: str, world: Optional[Dict] = None,
                     memory: Optional[Dict] = None, user_initiated: bool = False,
                     recent_dialogue: Optional[List[str]] = None) -> ShouldSpeakDecision:
        w = world or {}
        cost = float(w.get("interruption_cost", 0.0))
        avail = float(w.get("availability", 1.0))
        risk = float((memory or {}).get("risk", 0.0))
        drive = 0.5
        reasons: List[str] = []
        supp: List[str] = []
        # 用户主动 → 高优先（§6）
        if user_initiated:
            return ShouldSpeakDecision(True, 0.85, ["user_initiated"], [])
        # 深度工作 → 降 initiative（§25）
        if cost > 0.6:
            drive -= 0.35; supp.append("user_deep_focus")
        if avail < 0.3:
            drive -= 0.2; supp.append("low_availability")
        # 记忆风险（§24）：上次类似情境被拒 → 降主动
        if risk > 0.4:
            drive -= 0.25; supp.append("memory_interaction_risk")
        # 情绪低落 → 轻微降主动但不沉默
        if emotion in ("sad", "lonely"):
            drive -= 0.1
        drive = max(0.05, min(0.9, drive))
        should = drive >= 0.35
        if not should:
            supp.append("low_speech_drive")
        return ShouldSpeakDecision(should, drive, reasons, supp)

    # -------------------------------------------------- Mode（§7-§8）
    def mode(self, *, emotion: str, relationship: Dict, solitude: bool,
             user_present: bool, user_working: bool, activation: Dict) -> tuple[str, str]:
        # C-R1.2：关系 dict 已是 0..1 归一化契约，直接传给 mode_for（不再 *100 混成 0-100）。
        m = _contract_mode(emotion, float(relationship.get("familiarity", 0)),
                           float(relationship.get("trust", 0)),
                           float(relationship.get("annoyance", 0)),
                           solitude, user_present)
        second = ""
        # 历史创伤激活（§18）：只有 activation 高才允许 VULNERABLE/GUARDED 浮现
        fear_gain = activation_gain(self.identity, "fear_of_being_exposed",
                                    boost_if=False) if self.identity else 0.3
        if emotion in ("sad", "lonely", "embarrassed"):
            if float(relationship.get("trust", 0)) > 0.55 or float(relationship.get("familiarity", 0)) > 0.6:
                second = PersonaMode.SINCERE.value
            else:
                second = PersonaMode.GUARDED.value
        if m == PersonaMode.CASUAL.value and user_present and emotion in ("happy", "excited"):
            second = PersonaMode.PLAYFUL.value
        return m, second

    # -------------------------------------------------- Dialogue Act（§13）
    def dialogue_act(self, *, emotion: str, intent: str, user_text: str,
                     mode: str, user_working: bool) -> str:
        ut = (user_text or "").lower()
        if "帮助" in ut or "帮我" in ut or "帮忙" in ut or "求助" in ut:
            return DialogueAct.OFFER_HELP.value
        if "夸" in ut or "赞" in ut or "厉害" in ut or "不错" in ut or "good" in ut:
            return DialogueAct.BOAST.value if emotion in ("proud", "happy") else DialogueAct.REACT.value
        if "错" in ut or "弄错" in ut or "失误" in ut or "失败" in ut:
            return DialogueAct.ADMIT.value if emotion in ("sad", "embarrassed") else DialogueAct.DEFLECT.value
        if intent == "approach_user":
            return DialogueAct.GREET.value
        if intent == "offer_help":
            return DialogueAct.OFFER_HELP.value
        if intent == "comfort":
            return DialogueAct.COMFORT.value
        if intent == "invite_user":
            return DialogueAct.INVITE.value
        if intent == "celebrate":
            return DialogueAct.CELEBRATE.value
        if intent == "talk":
            return DialogueAct.COMMENT.value
        if mode == PersonaMode.PERFORMATIVE.value:
            return DialogueAct.REACT.value
        return DialogueAct.COMMENT.value

    # -------------------------------------------------- ExpressionStrategy（§15-§17）
    def strategy(self, *, emotion: str, mode: str, relationship: Dict,
                 task_mode: bool = False, activation: Dict,
                 user_working: bool = False) -> ExpressionStrategy:
        base = dict(_EMOTION_BASE.get(emotion, {}))
        s = ExpressionStrategy()
        for k, v in base.items():
            setattr(s, k, float(v))
        # Stable core：戏剧性基线（由 context 调节）
        if self.identity is not None:
            s.dramatic_intensity = min(1.0, s.dramatic_intensity * (0.6 + self.identity.dramatic_self_presentation * 0.5))
        # Relationship（§22）
        rel = relationship
        openness = float(s.emotional_openness)
        if float(rel.get("trust", 0)) > 0.6: openness += 0.2
        if float(rel.get("comfort", 0)) > 0.6: s.playfulness += 0.15
        if float(rel.get("annoyance", 0)) > 0.6: s.warmth -= 0.25; s.brevity += 0.2   # C-R2 hotfix: normalized 0..1
        if float(rel.get("familiarity", 0)) < 0.3:
            s.self_guarding = True  # noqa
            s.defensiveness += 0.15
        # Historical scars triggered（§18）：只在高 activation 才提高防御/隐藏脆弱
        fear_gain = activation_gain(self.identity, "fear_of_being_exposed", boost_if=False) if self.identity else 0.3
        if float(rel.get("trust", 0)) < 0.4 or activation.get("fear", 0) > 0.5:
            s.defensiveness = min(1.0, s.defensiveness + 0.2)
            s.vulnerability_visibility = max(0.1, s.vulnerability_visibility - 0.2)
        # Task mode（§37）：清晰/简洁，戏剧性降
        if task_mode:
            s.dramatic_intensity = min(s.dramatic_intensity, 0.2)
            s.brevity = min(1.0, s.brevity + 0.3)
            s.directness = min(1.0, s.directness + 0.2)
        # 深度工作 → 简洁
        if user_working:
            s.brevity = min(1.0, s.brevity + 0.2)
        # 归一化
        for f in ("directness", "warmth", "confidence", "emotional_openness", "dramatic_intensity",
                  "playfulness", "defensiveness", "vulnerability_visibility", "sincerity", "brevity"):
            setattr(s, f, max(0.0, min(1.0, float(getattr(s, f)))))
        return s

    # -------------------------------------------------- Orchestrator
    def appraise(self, *, emotion: str = "calm", intent: str = "", user_text: str = "",
                 relationship: Optional[Dict] = None, world: Optional[Dict] = None,
                 memory: Optional[Dict] = None, activity: str = "",
                 user_initiated: bool = False, task_mode: bool = False,
                 solitude: bool = False, user_present: bool = True,
                 user_working: bool = False, recent_dialogue: Optional[List[str]] = None,
                 activation: Optional[Dict] = None) -> ExpressionAppraisal:
        rel = relationship or {}
        w = world or {}
        act = activation or {}
        sd = self.should_speak(emotion=emotion, world=w, memory=memory,
                               user_initiated=user_initiated, recent_dialogue=recent_dialogue)
        m, second = self.mode(emotion=emotion, relationship=rel, solitude=solitude,
                              user_present=user_present, user_working=user_working, activation=act)
        da = self.dialogue_act(emotion=emotion, intent=intent, user_text=user_text,
                               mode=m, user_working=user_working)
        st = self.strategy(emotion=emotion, mode=m, relationship=rel,
                           task_mode=task_mode, activation=act, user_working=user_working)
        # 计算 initiative / brevity
        drive = sd.speech_drive
        brevity = 0.5 + (0.3 if user_working else 0.0) + (0.2 if w.get("interruption_cost", 0) > 0.6 else 0.0)
        response_length = (SpeechLength.NORMAL.value if st.dramatic_intensity > 0.6 and st.playfulness > 0.5
                           else SpeechLength.SHORT.value)
        si = SpeechIntent(
            should_speak=sd.should_speak, dialogue_act=da,
            initiative=round(drive, 2), response_length=response_length,
            directness=round(st.directness, 2), warmth=round(st.warmth, 2),
            confidence=round(st.confidence, 2), emotional_openness=round(st.emotional_openness, 2),
            dramatic_intensity=round(st.dramatic_intensity, 2), playfulness=round(st.playfulness, 2),
            defensiveness=round(st.defensiveness, 2),
            vulnerability_visibility=round(st.vulnerability_visibility, 2),
            sincerity=round(st.sincerity, 2), brevity=round(min(1.0, brevity), 2),
            topic=activity,
        )
        app = ExpressionAppraisal(mode=m, secondary_mode=second, dialogue_act=da,
                                  should_speak=sd.should_speak, speech_drive=drive,
                                  seed_intent=si, strategy=st,
                                  reasons=sd.reasons + sd.suppression_reasons)
        return app
