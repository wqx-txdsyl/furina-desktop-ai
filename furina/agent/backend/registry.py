"""Phase 16B — ExecutionBackendRegistry（显式注册；注册不是执行）。

- **显式注册**：``register()`` 只登记身份与能力，绝不 probe / 不执行 / 无任何副作用；
- **重复 id 拒绝**：同 id 二次注册直接抛 :class:`BackendRegistrationError`；
- **健康事实由 registry 持有**：``probe()`` 显式建立并缓存；router 只读缓存，
  未 probe 的 backend 视为不可路由（fail-closed：installed != healthy）；
- **无安装/卸载**：本 registry 只有 register / lookup / snapshot，没有 install /
  uninstall / upgrade / remove —— 外部 agent 安装/卸载是 16 系列禁止面；
- **snapshot 不可变**：返回与内部状态解耦的只读映射副本，调用方改动不影响 registry。
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Dict, Mapping, Optional, Tuple

from .models import (
    PROTOCOL_VERSION,
    BackendCapabilities,
    BackendDescriptor,
    BackendHealth,
    BackendRegistrationError,
    BackendUnknownError,
)
from .protocol import ExecutionBackend


class ExecutionBackendRegistry:
    """执行后端注册表（backend-neutral；唯一执行后端注册面，避免平行 registry）。"""

    def __init__(self) -> None:
        self._backends: Dict[str, ExecutionBackend] = {}
        self._health: Dict[str, BackendHealth] = {}

    # -- 显式注册（注册不是执行） ----------------------------------------------
    def register(self, backend: ExecutionBackend) -> None:
        if not isinstance(backend, ExecutionBackend):
            raise BackendRegistrationError(
                f"只接受 ExecutionBackend 实现，得到 {type(backend).__name__}")
        # 坏实现不得把 AttributeError/TypeError 泄漏给调用方：元数据读取全部折为注册错误
        try:
            descriptor = backend.descriptor
            capabilities = backend.capabilities
        except Exception as exc:
            raise BackendRegistrationError(
                f"backend 元数据不可读（{type(backend).__name__} 实现损坏）: {exc}") from exc
        if not isinstance(descriptor, BackendDescriptor):
            raise BackendRegistrationError(
                f"descriptor 必须是 BackendDescriptor，得到 {type(descriptor).__name__}")
        if not isinstance(capabilities, BackendCapabilities):
            raise BackendRegistrationError(
                f"capabilities 必须是 BackendCapabilities，得到 {type(capabilities).__name__}")
        bid = descriptor.backend_id
        if not bid:
            raise BackendRegistrationError("backend_id 不能为空")
        if descriptor.protocol_version != PROTOCOL_VERSION:
            raise BackendRegistrationError(
                f"protocol_version 不兼容: {descriptor.protocol_version!r}"
                f"（registry 支持 {PROTOCOL_VERSION}，类型化拒绝）")
        if bid in self._backends:
            raise BackendRegistrationError(f"重复 backend id: {bid!r}（注册是显式幂等，不覆盖）")
        self._backends[bid] = backend
        # 注册不建立健康事实；未 probe 的 backend 由 router fail-closed 拒绝。
        # 同时清除旧健康缓存，避免"旧健康事实"残留到同 id 新实例上。
        self._health.pop(bid, None)

    # -- 查找 -----------------------------------------------------------------
    def get(self, backend_id: str) -> Optional[ExecutionBackend]:
        return self._backends.get(backend_id)

    def get_required(self, backend_id: str) -> ExecutionBackend:
        b = self._backends.get(backend_id)
        if b is None:
            raise BackendUnknownError(f"未知 backend: {backend_id!r}（已注册: {sorted(self._backends)}）")
        return b

    def list_ids(self) -> Tuple[str, ...]:
        """确定性 id 列表（排序），供 router 候选迭代使用。"""
        return tuple(sorted(self._backends))

    def snapshot(self) -> Mapping[str, ExecutionBackend]:
        """调用方安全的不可变快照（副本 + 只读投影；后续注册不影响旧快照）。"""
        return MappingProxyType(dict(self._backends))

    def __len__(self) -> int:
        return len(self._backends)

    def __contains__(self, backend_id: str) -> bool:
        return backend_id in self._backends

    # -- 健康事实（显式建立 / 只读消费） ---------------------------------------
    def probe(self, backend_id: str) -> BackendHealth:
        """显式执行一次只读发现并缓存健康事实（router 路由路径不得调用本方法）。"""
        backend = self.get_required(backend_id)
        health = backend.probe()
        if not isinstance(health, BackendHealth):
            raise BackendRegistrationError(
                f"backend '{backend_id}' 的 probe() 必须返回 BackendHealth，得到 {type(health).__name__}")
        self._health[backend_id] = health
        return health

    def set_health(self, backend_id: str, health: BackendHealth) -> None:
        """显式注入健康事实（测试/外部健康信号用；路由只认缓存事实）。

        只接受 BackendHealth（坏健康值不得进入路由输入面）。未知 backend 抛
        BackendUnknownError。
        """
        self.get_required(backend_id)
        if not isinstance(health, BackendHealth):
            raise BackendRegistrationError(
                f"set_health 只接受 BackendHealth，得到 {type(health).__name__}")
        self._health[backend_id] = health

    def health_of(self, backend_id: str) -> Optional[BackendHealth]:
        """路由读缓存（只读；未 probe → None，fail-closed 视为不可路由）。"""
        return self._health.get(backend_id)

    def health_snapshot(self) -> Mapping[str, BackendHealth]:
        return MappingProxyType(dict(self._health))
