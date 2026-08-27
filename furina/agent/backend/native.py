"""Phase 16B — Native AgentRuntime backend（首个 conformance 实现，薄包装）。

包装既有 :class:`furina.agent.agent_runtime.AgentRuntime.execute`，**语义不变**：

- 任务记录（task_record）、ToolResult 验证（ok ∧ verified）、权限行为全部原样透传；
  本 adapter **不做任何二次验证，也不削弱 AgentRuntime 既有验证**。
- ``submit`` 只消费 WorkContract 只读 projection；``task_auth=None`` → AgentRuntime
  默认 L0/L1 任务上下文（16D 拥有 approval channel，本层不伪造授权）。
- native “completed” 结果在 Phase 16 backend 边界仍属 **unverified**（16F 拥有 verifier）；
  结果中的 verified 字段只反映 AgentRuntime 自身的验证语义，不是 16F 背书。
- 现有 AgentRuntime **无取消面** → ``supports_stop=False``（诚实声明，不假装可停）；
  ``events`` 由 16E 拥有；结果引用经 ``last_result(run_id)`` 原生访问器取得
  （16E 拥有统一结果引用语义）。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Mapping, Optional, Tuple

from furina.agent.agent_runtime import AgentRuntime

from .models import PROTOCOL_VERSION, BackendCapabilities, BackendDescriptor, BackendHealth, BackendRunHandle
from .protocol import ExecutionBackend


class NativeAgentRuntimeBackend(ExecutionBackend):
    """本地 Native backend：直接执行既有 AgentRuntime（进程内，确定性健康）。"""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        backend_id: str = "native",
        capability_ids: Optional[Tuple[str, ...]] = None,
        capability_registry=None,
        supports_events: bool = False,
        supports_stop: bool = False,
        supports_resolve_approval: bool = False,
        max_concurrent_runs: int = 1,
        max_cost_limit: Optional[float] = None,
        max_duration_seconds: Optional[float] = None,
        workspace_scoped: bool = True,
        probe_ttl_seconds: float = 60.0,
    ) -> None:
        self._runtime = runtime
        # 显式 capability_ids 优先；否则从 CapabilityRegistry 派生"available"能力
        # （诚实声明：只声明确实可用、非 provider 占位的能力）。
        if capability_ids is None:
            ids: Tuple[str, ...] = ()
            if capability_registry is not None:
                ids = tuple(sorted(
                    c.capability_id for c in capability_registry.all() if c.available))
        else:
            ids = tuple(capability_ids)
        self._descriptor = BackendDescriptor(
            backend_id=backend_id,
            display_name="Native AgentRuntime",
            description="包装既有 AgentRuntime.execute 的本地 backend（Phase 16B conformance）",
            protocol_version=PROTOCOL_VERSION,
        )
        self._capabilities = BackendCapabilities(
            capability_ids=ids,
            supports_events=supports_events,
            supports_stop=supports_stop,
            supports_resolve_approval=supports_resolve_approval,
            max_concurrent_runs=max_concurrent_runs,
            max_cost_limit=max_cost_limit,
            max_duration_seconds=max_duration_seconds,
            workspace_scoped=workspace_scoped,
        )
        if not isinstance(probe_ttl_seconds, (int, float)) or isinstance(probe_ttl_seconds, bool) \
                or probe_ttl_seconds <= 0:
            raise ValueError(f"probe_ttl_seconds 必须是正数值，得到 {probe_ttl_seconds!r}")
        self._probe_ttl_seconds = float(probe_ttl_seconds)
        # run_id → AgentRuntime 原始结果（进程内引用；16H 拥有持久化，16E 拥有结果引用语义）。
        self._results: Dict[str, Dict[str, Any]] = {}

    # -- 身份与能力 --------------------------------------------------------------
    @property
    def descriptor(self) -> BackendDescriptor:
        return self._descriptor

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

    # -- 发现 -------------------------------------------------------------------
    def probe(self) -> BackendHealth:
        now = time.time()
        installed = self._runtime is not None
        reachable = installed          # 进程内 runtime：构造即可达
        healthy = installed and reachable
        return BackendHealth(
            installed=installed, reachable=reachable, healthy=healthy,
            checked_at=now,
            reason="" if healthy else "runtime_unavailable",
            expiry=now + self._probe_ttl_seconds,
        )

    # -- 执行 -------------------------------------------------------------------
    def submit(self, contract_projection: Mapping[str, Any], *,
               run_id: Optional[str] = None) -> BackendRunHandle:
        """以既有 AgentRuntime.execute 语义执行契约 projection。

        - 请求主体取 canonical_user_request（客观内容）；workspace write root 作为
          路径上下文（与 App 既有调用一致：``{"path": ...}``）；
        - ``task_auth=None``：沿用 AgentRuntime 默认 L0/L1 任务上下文 —— **不削弱**
          既有权限语义，也不在此伪造 16D 授权；
        - run_id 由 AgentRuntime 内部生成（stable task_id），调用方 run_id 参数不覆盖
          runtime 任务身份（身份真相归 runtime）。
        """
        request = contract_projection.get("canonical_user_request")
        if not isinstance(request, str) or not request.strip():
            raise ValueError("projection.canonical_user_request 缺失或非法")
        ws = contract_projection.get("workspace_scope") or {}
        write_roots = tuple(ws.get("write_roots") or ())
        extra: Dict[str, Any] = {}
        if write_roots:
            extra["path"] = str(write_roots[0])
        result = self._runtime.execute(request, extra if extra else None)
        rid = str(result.get("task_id") or "")
        if not rid:
            raise RuntimeError("AgentRuntime.execute 未返回 task_id")
        self._results[rid] = result
        return BackendRunHandle(
            backend_id=self._descriptor.backend_id,
            run_id=rid,
            correlation=str(contract_projection.get("contract_id") or ""),
        )

    def last_result(self, run_id: str) -> Optional[Dict[str, Any]]:
        """原生访问器：按 run_id 取 AgentRuntime 原始结果（16E 拥有统一结果引用语义）。"""
        return self._results.get(run_id)
