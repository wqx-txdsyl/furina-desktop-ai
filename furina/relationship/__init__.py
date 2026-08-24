"""Relationship 包（Phase 04）：关系动态演化引擎（确定性）。"""
from .engine import (
    RelationshipEngine,
    EV_POSITIVE_RESPONSE, EV_USER_INITIATED, EV_ACCEPTED_INVITATION, EV_POSITIVE_TOUCH,
    EV_SUCCESSFUL_HELP, EV_LONG_POSITIVE_SESSION, EV_REJECT, EV_IGNORE, EV_CANCEL,
    EV_FAILED_HELP, EV_NEGATIVE_RESPONSE,
)
from furina.memory.memory_types import RelationshipState

__all__ = [
    "RelationshipEngine", "RelationshipState",
    "EV_POSITIVE_RESPONSE", "EV_USER_INITIATED", "EV_ACCEPTED_INVITATION", "EV_POSITIVE_TOUCH",
    "EV_SUCCESSFUL_HELP", "EV_LONG_POSITIVE_SESSION", "EV_REJECT", "EV_IGNORE", "EV_CANCEL",
    "EV_FAILED_HELP", "EV_NEGATIVE_RESPONSE",
]
