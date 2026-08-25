"""furina/cognition —— 认知层（Phase 14B）。

7 个逻辑 Store（C1-C7）+ ContextAssembler + Consolidator + Canon Retrieval。
权威契约见 docs/architecture/COGNITIVE_ARCHITECTURE.md。
"""
from .hub import CognitionHub, UserModelExtractor
from .models import (
    AgentArtifact,
    AgentTask,
    AgentTaskStep,
    CanonEpisode,
    CognitiveContext,
    LifeEvent,
    UserModelItem,
    WorkDisposition,
    WorkWillingnessInput,
    WorkWillingnessModel,
    WorkWillingnessResult,
)

__all__ = [
    "CognitionHub", "UserModelExtractor",
    "CanonEpisode", "LifeEvent", "UserModelItem",
    "AgentTask", "AgentTaskStep", "AgentArtifact",
    "CognitiveContext",
    "WorkDisposition", "WorkWillingnessInput", "WorkWillingnessResult", "WorkWillingnessModel",
]
