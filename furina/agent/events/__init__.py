"""Phase 16E — Backend Event Normalization（backend-neutral 事件信封 + 确定性工作域状态机）。

模块边界（任务书 §6）：不执行 Hermes(16C)、不实现 verifier/repair/recovery(16F)、
不写 C6/C7(16G)、不实现 durable queue/ledger(16H)；不修改 16A/16B/16D frozen
contracts；C1–C7 零接触。本包为纯数据 + 纯函数 + 进程内状态机。
"""
from .models import (
    COALESCIBLE_KINDS,
    CRITICAL_KINDS,
    DROPPABLE_KINDS,
    TERMINAL_KINDS,
    EventBackpressurePolicy,
    EventKind,
    EventNormalizationError,
    EventPriority,
    NormalizedEvent,
    WorkExecutionError,
    classify_priority,
    deep_freeze,
    sanitize_payload,
)
from .normalizer import BackendEventNormalizer, map_kind
from .reducer import (
    LEGAL_TRANSITIONS,
    TERMINAL_PRIMARY_STATES,
    ReduceResult,
    WorkExecutionReducer,
    WorkExecutionState,
    WorkExecutionView,
)

__all__ = [
    "COALESCIBLE_KINDS",
    "CRITICAL_KINDS",
    "DROPPABLE_KINDS",
    "LEGAL_TRANSITIONS",
    "TERMINAL_KINDS",
    "TERMINAL_PRIMARY_STATES",
    "BackendEventNormalizer",
    "EventBackpressurePolicy",
    "EventKind",
    "EventNormalizationError",
    "EventPriority",
    "NormalizedEvent",
    "ReduceResult",
    "WorkExecutionError",
    "WorkExecutionReducer",
    "WorkExecutionState",
    "WorkExecutionView",
    "classify_priority",
    "deep_freeze",
    "map_kind",
    "sanitize_payload",
]
