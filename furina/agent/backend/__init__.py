"""Phase 16B — ExecutionBackend protocol & registry（backend-neutral 执行后端面）。

模块边界（任务书 §6）：不实现 Hermes(16C)、approval channel(16D)、事件状态机(16E)、
verifier(16F)、持久化 ledger(16H)、C7 commit(16G)；无 MCP backend；无安装/卸载；
无 C1–C7 / DB 变更。本包为纯数据 + 协议 + 确定性路由，无任何持久化行为。
"""
from .models import (
    PROTOCOL_VERSION,
    BackendCapabilities,
    BackendCapabilityError,
    BackendDescriptor,
    BackendError,
    BackendEvent,
    BackendHealth,
    BackendRegistrationError,
    BackendRunHandle,
    BackendScopeViolation,
    BackendSubmitFailure,
    BackendUnknownError,
)
from .native import NativeAgentRuntimeBackend
from .protocol import ExecutionBackend
from .registry import ExecutionBackendRegistry
from .router import DispatchResult, RouteDecision, RoutingPolicy, TechnicalRouter

__all__ = [
    "PROTOCOL_VERSION",
    "BackendCapabilities",
    "BackendCapabilityError",
    "BackendDescriptor",
    "BackendError",
    "BackendEvent",
    "BackendHealth",
    "BackendRegistrationError",
    "BackendRunHandle",
    "BackendScopeViolation",
    "BackendSubmitFailure",
    "BackendUnknownError",
    "DispatchResult",
    "ExecutionBackend",
    "ExecutionBackendRegistry",
    "NativeAgentRuntimeBackend",
    "RouteDecision",
    "RoutingPolicy",
    "TechnicalRouter",
]
