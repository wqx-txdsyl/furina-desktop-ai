"""状态包：五维状态模型 Life → Emotion → Needs → Attention → Intent。"""
from .state_model import (
    AttentionTarget,
    CharacterState,
    EmotionState,
    Intent,
    IntentCategory,
    LifeState,
    MacroState,
    NeedsState,
)
from .state_engine import StateEngine

__all__ = [
    "AttentionTarget",
    "CharacterState",
    "EmotionState",
    "Intent",
    "IntentCategory",
    "LifeState",
    "MacroState",
    "NeedsState",
    "StateEngine",
]
