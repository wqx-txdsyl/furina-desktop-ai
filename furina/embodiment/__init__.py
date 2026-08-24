"""Embodiment 包（Phase 09）：语义身体层，确定性投影，0 次 LLM 调用。

链路：Runtime state → EmbodiedExpressionEngine → BodyExpressionState（semantic intents）
      → BodyValidator（兼容校验）→ 后续 Asset Resolver / Renderer。

不修改 Dialogue / Identity / 等冻结模块；不生成素材；不实现 Walk/Pathfinding。
"""
from .model import (
    BodyExpressionState, ExpressionIntent, GazeIntent, PostureIntent, ProximityIntent,
    TempoIntent, TransitionStyle, MicroMotionIntent, SpeechSync,
    EmbodimentPersona, FURINA_EMBODIMENT, NEUTRAL_EMBODIMENT, FORMER_MASK_EMBODIMENT,
    EMBODIMENT_PERSONAS,
)
from .engine import EmbodiedExpressionEngine
from .validator import BodyValidator

__all__ = [
    "BodyExpressionState",
    "ExpressionIntent", "GazeIntent", "PostureIntent", "ProximityIntent",
    "TempoIntent", "TransitionStyle", "MicroMotionIntent", "SpeechSync",
    "EmbodimentPersona", "FURINA_EMBODIMENT", "NEUTRAL_EMBODIMENT", "FORMER_MASK_EMBODIMENT",
    "EMBODIMENT_PERSONAS",
    "EmbodiedExpressionEngine",
    "BodyValidator",
]
