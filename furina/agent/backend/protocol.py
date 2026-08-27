"""Phase 16B — ExecutionBackend 协议（backend-neutral 执行后端接口）。

接口面：``probe`` / ``submit`` / ``events`` / ``stop`` + 可选 ``resolve_approval``。

- 可选能力一律**显式布尔门控**：capability-gated 方法在 backend 未声明该能力时
  直接抛 :class:`BackendCapabilityError`（fail-closed，绝不在未声明能力上假装工作）。
- ``submit`` 输入是 WorkContract 的**只读 projection**（backend 只能读，不能反向改约）；
  返回 :class:`BackendRunHandle` —— 只承载 run 身份，不偷带结果。
- BackendEvent 由 16E 拥有；16B 只定义类型化引用。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Mapping, Optional

from .models import (
    BackendCapabilities,
    BackendCapabilityError,
    BackendDescriptor,
    BackendEvent,
    BackendHealth,
    BackendRunHandle,
)


class ExecutionBackend(ABC):
    """执行后端协议（结构性约定；registry 只接受本类的实现）。"""

    # -- 身份与能力（只读事实） ------------------------------------------------
    @property
    @abstractmethod
    def descriptor(self) -> BackendDescriptor:
        """稳定身份 / 展示元数据 / 协议版本。"""

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities:
        """显式能力声明（布尔/有限集合/数值上限）。"""

    # -- 发现 -----------------------------------------------------------------
    @abstractmethod
    def probe(self) -> BackendHealth:
        """建立一次性健康事实（installed / reachable / healthy / checked_at / expiry）。

        只读发现，无副作用；router 只消费 registry 缓存后的健康事实，
        绝不在路由路径里现场探测。
        """

    # -- 执行 -----------------------------------------------------------------
    @abstractmethod
    def submit(self, contract_projection: Mapping[str, Any], *,
               run_id: Optional[str] = None) -> BackendRunHandle:
        """提交一次执行；输入为 WorkContract 只读 projection，输出只承载 run 身份。

        语义约束：backend 不得自行批准、不得修改契约、不得越过输入中的约束。
        16D 拥有 approval channel；本方法不消费也不伪造授权。
        """

    def events(self, run_handle: BackendRunHandle) -> Iterable[BackendEvent]:
        """backend 原生事件流（16E 拥有规范化；16B 仅类型化引用）。

        未声明 supports_events 的 backend 调用本方法 → 能力门控拒绝。
        """
        if not self.capabilities.supports_events:
            raise BackendCapabilityError(
                f"backend '{self.descriptor.backend_id}' 未声明 supports_events（16E 拥有事件面）")
        raise NotImplementedError

    def stop(self, run_handle: BackendRunHandle) -> None:
        """请求停止一个 run。未声明 supports_stop → 能力门控拒绝。

        现有 Native AgentRuntime 无取消面 → 其 supports_stop=False（诚实声明，不假装可停）。
        """
        if not self.capabilities.supports_stop:
            raise BackendCapabilityError(
                f"backend '{self.descriptor.backend_id}' 未声明 supports_stop")
        raise NotImplementedError

    def resolve_approval(self, approval_ref: str) -> Any:
        """可选能力：解析 16D 授权引用。未声明 → 能力门控拒绝。"""
        if not self.capabilities.supports_resolve_approval:
            raise BackendCapabilityError(
                f"backend '{self.descriptor.backend_id}' 未声明 supports_resolve_approval（16D 拥有）")
        raise NotImplementedError
