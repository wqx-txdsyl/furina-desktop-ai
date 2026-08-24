"""Phase 12 空间层（Desktop Spatial Life / Movement Runtime）。

暴露对外 API：SpatialIntentResolver / SpatialPlanner / DesktopSpatialRuntime /
PositionAdapter / 模型枚举与 dataclass。
"""
from __future__ import annotations

from .model import (
    Facing, FrontendSpatialState, MovementPlan, ResolvedIntent, SpatialConfig,
    SpatialIntent, SpatialPoint, SpatialState, SpeedSemantic, TargetType,
)
from .resolver import SpatialIntentResolver
from .planner import SpatialPlanner
from .runtime import DesktopSpatialRuntime, PositionAdapter

__all__ = [
    "Facing", "FrontendSpatialState", "MovementPlan", "ResolvedIntent", "SpatialConfig",
    "SpatialIntent", "SpatialPoint", "SpatialState", "SpeedSemantic", "TargetType",
    "SpatialIntentResolver", "SpatialPlanner", "DesktopSpatialRuntime", "PositionAdapter",
]
