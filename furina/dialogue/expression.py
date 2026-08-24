"""Dialogue Expression Layer（Phase 08B）—— 把 Runtime 内部状态确定性转译成"表达策略"。

链路：
    Identity + Emotion + Relationship + Memory + World + Activity + User Event
        → ExpressionAppraisal
        → ShouldSpeak?
        → DialogueAct
        → ContextualPersonaMode
        → ExpressionStrategy
        → DialogueBrain（LLM 生成自然语言）
        → Validator

关键原则：
  - Mode 不是多套人格，是"同一 Furina 的当前表达姿态"（primary+secondary）。
  - Former Mask / Historical Scars 是 triggered，不是普通模式。
  - 普通场景允许自然/松弛/真诚（POST_ARCHON_QUEST 成长），不是永远戏剧化。
  - Silence 是正式行为（speech=None 合法）。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------- Persona Modes
class PersonaMode(str, enum.Enum):
    PERFORMATIVE = "PERFORMATIVE"
    CASUAL = "CASUAL"
    GUARDED = "GUARDED"
    SINCERE = "SINCERE"
    PROUD = "PROUD"
    VULNERABLE = "VULNERABLE"
    RESPONSIBLE = "RESPONSIBLE"
    PLAYFUL = "PLAYFUL"


# ---------------------------------------------------------------- Dialogue Acts
class DialogueAct(str, enum.Enum):
    ANSWER = "ANSWER"
    GREET = "GREET"
    COMMENT = "COMMENT"
    REACT = "REACT"
    TEASE = "TEASE"
    BOAST = "BOAST"
    INVITE = "INVITE"
    ASK = "ASK"
    OFFER_HELP = "OFFER_HELP"
    COMFORT = "COMFORT"
    CELEBRATE = "CELEBRATE"
    COMPLAIN = "COMPLAIN"
    DEFLECT = "DEFLECT"
    ADMIT = "ADMIT"
    REFLECT = "REFLECT"
    DECLINE = "DECLINE"


# ---------------------------------------------------------------- Speech Length
class SpeechLength(str, enum.Enum):
    MICRO = "MICRO"    # 极短反应
    SHORT = "SHORT"    # 1 句
    NORMAL = "NORMAL"  # 1~3 句
    TASK = "TASK"


# ---------------------------------------------------------------- ShouldSpeak
@dataclass
class ShouldSpeakDecision:
    should_speak: bool = True
    speech_drive: float = 0.5      # 0..1 主动说话的动力
    reasons: List[str] = field(default_factory=list)
    suppression_reasons: List[str] = field(default_factory=list)


# ---------------------------------------------------------------- SpeechIntent
@dataclass
class SpeechIntent:
    should_speak: bool = True
    dialogue_act: str = DialogueAct.COMMENT.value
    target: str = "user"
    initiative: float = 0.5          # 0..1 主动
    topic: str = ""
    response_length: str = SpeechLength.SHORT.value
    directness: float = 0.5          # 0..1 直说
    warmth: float = 0.5              # 0..1 对用户温度
    confidence: float = 0.5          # 0..1 表层自信
    emotional_openness: float = 0.5  # 0..1 愿意暴露真实情绪
    dramatic_intensity: float = 0.5  # 0..1 表演/戏剧程度
    playfulness: float = 0.5         # 0..1 玩笑程度
    defensiveness: float = 0.5       # 0..1 自我保护
    vulnerability_visibility: float = 0.5  # 0..1 脆弱是否可见
    sincerity: float = 0.5           # 0..1 真诚
    brevity: float = 0.5             # 0..1 简洁

    def to_dict(self) -> dict:
        return {
            "should_speak": self.should_speak, "dialogue_act": self.dialogue_act,
            "initiative": round(self.initiative, 2), "response_length": self.response_length,
            "directness": round(self.directness, 2), "warmth": round(self.warmth, 2),
            "confidence": round(self.confidence, 2), "emotional_openness": round(self.emotional_openness, 2),
            "dramatic_intensity": round(self.dramatic_intensity, 2), "playfulness": round(self.playfulness, 2),
            "defensiveness": round(self.defensiveness, 2),
            "vulnerability_visibility": round(self.vulnerability_visibility, 2),
            "sincerity": round(self.sincerity, 2), "brevity": round(self.brevity, 2),
        }


# ---------------------------------------------------------------- ExpressionStrategy
@dataclass
class ExpressionStrategy:
    directness: float = 0.5
    warmth: float = 0.5
    confidence: float = 0.5
    emotional_openness: float = 0.5
    dramatic_intensity: float = 0.5
    playfulness: float = 0.5
    defensiveness: float = 0.5
    vulnerability_visibility: float = 0.5
    sincerity: float = 0.5
    brevity: float = 0.5

    def to_dict(self) -> dict:
        return {k: round(v, 2) for k, v in self.__dict__.items()}


# ---------------------------------------------------------------- ExpressionAppraisal
@dataclass
class ExpressionAppraisal:
    """把运行时各状态汇成表达所需的浓缩上下文。"""
    mode: str = PersonaMode.CASUAL.value
    secondary_mode: str = ""
    dialogue_act: str = DialogueAct.COMMENT.value
    should_speak: bool = True
    speech_drive: float = 0.5
    seed_intent: SpeechIntent = field(default_factory=SpeechIntent)
    strategy: ExpressionStrategy = field(default_factory=ExpressionStrategy)
    reasons: List[str] = field(default_factory=list)

    def to_prompt(self) -> dict:
        return {
            "mode": self.mode, "secondary_mode": self.secondary_mode,
            "dialogue_act": self.dialogue_act, "should_speak": self.should_speak,
            "speech_drive": round(self.speech_drive, 2),
            "intent": self.seed_intent.to_dict(),
            "strategy": self.strategy.to_dict(),
        }
