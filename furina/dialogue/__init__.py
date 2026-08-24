"""Dialogue 包（Phase 08B）：表达评估器 + 校验器 + 数据类型。"""
from .expression import (
    PersonaMode, DialogueAct, SpeechLength, SpeechIntent, ExpressionStrategy,
    ExpressionAppraisal, ShouldSpeakDecision,
)
from .expressive import ExpressionEngine
from .validator import DialogueValidator, ValidationResult
from .god_calibration import GodCalibrationGate, GodCalibration

__all__ = [
    "PersonaMode", "DialogueAct", "SpeechLength", "SpeechIntent",
    "ExpressionStrategy", "ExpressionAppraisal", "ShouldSpeakDecision",
    "ExpressionEngine", "DialogueValidator", "ValidationResult",
    "GodCalibrationGate", "GodCalibration",
]
