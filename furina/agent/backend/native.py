"""Phase 16B — Native AgentRuntime backend（首个 conformance 实现，薄包装 + 真 scope 约束）。

包装既有 :class:`furina.agent.agent_runtime.AgentRuntime.execute`，**语义不变**：

- 任务记录（task_record）、ToolResult 验证（ok ∧ verified）、权限行为全部原样透传；
  ``task_auth=None`` → AgentRuntime 默认 L0/L1 任务上下文 —— **不实现 16D 异步审批，
  也不削弱既有 PermissionManager**（L2/L3 依旧由默认上下文/on_confirm 拒绝）。
- native “completed” 结果在 Phase 16 backend 边界仍属 **unverified**（16F 拥有 verifier）；
  结果中的 verified 字段只反映 AgentRuntime 自身的验证语义，不是 16F 背书。

**真 scope 约束（Reviewer Patch 1）**：Native 真正执行 WorkContract scope——

1. **实际工具不得越过 allowed_capabilities**：submit 前用 runtime 自身 planner 构建计划，
   逐个步骤校验其工具归属的 capability 必须在契约 ``allowed_capabilities`` 内；
   工具无法归属任何 capability / 未注册 / 权限声明缺失 → **scope 无法准确表达，
   submit 前 fail-closed**（抛 :class:`BackendScopeViolation`）。
2. **实际文件路径不得越过 workspace_scope**：每个步骤的路径参数（复用
   AgentRuntime._step_paths 的规范路径提取）必须落在契约 workspace 内；写工具
   （permission ≥ L1）路径必须在 write roots，只读工具路径在 read∪write roots。
3. **执行后二次校验**：对实际 task_record 中真正执行过的步骤再查一遍（LLM planner
   可能偏离预检计划；permission_denied / unknown_tool 步骤未执行工具，跳过）。

**真实能力/健康声明**：runtime 必须确实是 AgentRuntime；events/stop/resolve_approval
均未实现 → 一律不声明支持（supports_*=False，调用即能力门控拒绝）；workspace_scoped
只在真正执行 scope 时才为 true（本实现确实执行 → true）；probe TTL 必须有限正数。
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, Mapping, Optional, Tuple

from furina.agent.agent_runtime import AgentRuntime
from furina.agent.capabilities.models import CapabilityRegistry
from furina.agent.permission import Permission
from furina.agent.work_contract import WorkspaceScope

from .models import (
    PROTOCOL_VERSION,
    BackendCapabilities,
    BackendDescriptor,
    BackendError,
    BackendHealth,
    BackendRunHandle,
    BackendScopeViolation,
)
from .protocol import ExecutionBackend

#: 未执行工具（无法产生实际路径/工具越界风险）的 step 错误标记。
_SKIP_POSTFLIGHT_ERRORS = ("permission_denied",)


class NativeAgentRuntimeBackend(ExecutionBackend):
    """本地 Native backend：直接执行既有 AgentRuntime（进程内，确定性健康 + 真 scope）。"""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        capability_registry: CapabilityRegistry,
        probe_ttl_seconds: float = 60.0,
    ) -> None:
        # 假 runtime 拒绝：只接受真实 AgentRuntime（类型严格校验）。
        if not isinstance(runtime, AgentRuntime):
            raise BackendError(
                f"runtime 必须是 AgentRuntime，得到 {type(runtime).__name__}（假 runtime 拒绝）")
        # scope 约束依赖 tool→capability 映射；缺失则无法准确表达 → 构造即拒绝。
        if not isinstance(capability_registry, CapabilityRegistry):
            raise BackendError(
                f"capability_registry 必须是 CapabilityRegistry（scope 约束依赖），"
                f"得到 {type(capability_registry).__name__}")
        if (isinstance(probe_ttl_seconds, bool)
                or not isinstance(probe_ttl_seconds, (int, float))
                or not math.isfinite(float(probe_ttl_seconds)) or probe_ttl_seconds <= 0):
            raise BackendError(f"probe_ttl_seconds 必须有限正数，得到 {probe_ttl_seconds!r}")
        self._runtime = runtime
        self._cap_reg = capability_registry
        self._probe_ttl_seconds = float(probe_ttl_seconds)
        self._descriptor = BackendDescriptor(
            backend_id="native",
            display_name="Native AgentRuntime",
            description="包装既有 AgentRuntime.execute 的本地 backend（Phase 16B conformance）",
            protocol_version=PROTOCOL_VERSION,
        )
        # 能力声明全部真实：events/stop/resolve_approval 未实现 → 一律 False；
        # workspace_scoped 只在真正执行 scope 时才为 true（本实现 pre+post 双校验确实执行）。
        self._capabilities = BackendCapabilities(
            capability_ids=tuple(sorted(
                c.capability_id for c in capability_registry.all() if c.available)),
            supports_events=False,
            supports_stop=False,
            supports_resolve_approval=False,
            max_concurrent_runs=1,
            max_cost_limit=None,
            max_duration_seconds=None,
            workspace_scoped=True,
        )
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

    # -- scope 解析与校验 ---------------------------------------------------------
    def _extract_scope(self, projection: Mapping[str, Any]):
        """从只读 projection 重建契约 scope；无法表达 → BackendScopeViolation（fail-closed）。"""
        request = projection.get("canonical_user_request")
        if not isinstance(request, str) or not request.strip():
            raise BackendScopeViolation("projection.canonical_user_request 缺失或非法（scope 无法准确表达）")
        allowed_caps = frozenset(projection.get("allowed_capabilities") or ())
        if not allowed_caps:
            raise BackendScopeViolation("projection.allowed_capabilities 为空（scope 无法准确表达）")
        ws_raw = projection.get("workspace_scope") or {}
        try:
            ws = WorkspaceScope(
                read_roots=tuple(ws_raw.get("read_roots") or ()),
                write_roots=tuple(ws_raw.get("write_roots") or ()),
            )
        except Exception as exc:
            raise BackendScopeViolation(
                f"projection.workspace_scope 非法（scope 无法准确表达）: {exc}") from exc
        extra: Dict[str, Any] = {}
        if ws.write_roots:
            extra["path"] = str(ws.write_roots[0])
        return request, allowed_caps, ws, extra

    def _check_step(self, tool_name: str, args: Mapping[str, Any],
                    allowed_caps: frozenset, ws: WorkspaceScope) -> None:
        """单步 scope 门：工具 ∈ allowed_capabilities，路径 ∈ workspace（写工具限 write roots）。"""
        if not tool_name:
            raise BackendScopeViolation("plan step 缺失 tool 名（scope 无法准确表达）")
        owner = self._cap_reg.tool_owner(tool_name)
        if owner is None:
            raise BackendScopeViolation(
                f"tool '{tool_name}' 无法归属任何 capability：scope 无法准确表达（fail-closed）")
        if owner.capability_id not in allowed_caps:
            raise BackendScopeViolation(
                f"tool '{tool_name}' 属于 '{owner.capability_id}'，超出契约 "
                f"allowed_capabilities {sorted(allowed_caps)}（越权 capability）")
        try:
            tool = self._runtime.tools.get(tool_name)
        except Exception as exc:
            raise BackendScopeViolation(
                f"tool '{tool_name}' 未注册：scope 无法准确表达（fail-closed）") from exc
        perm = getattr(tool, "permission", None)
        if not isinstance(perm, Permission):
            raise BackendScopeViolation(
                f"tool '{tool_name}' 权限声明缺失/非法：scope 无法准确表达（fail-closed）")
        writable = perm.value >= Permission.L1_LOW_WRITE.value
        for p in AgentRuntime._step_paths(tool_name, dict(args or {})):
            if not ws.contains_path(p, writable=writable):
                kind = "write" if writable else "read"
                raise BackendScopeViolation(f"路径越界（{kind} scope）: {p}")

    def _preflight(self, request: str, extra: Dict[str, Any],
                   allowed_caps: frozenset, ws: WorkspaceScope) -> None:
        """submit 前 fail-closed：用 runtime 自身 planner 预检计划（与实际执行同一路径）。"""
        try:
            plan = self._runtime.planner.build_plan(request, extra or {})
        except Exception as exc:
            raise BackendScopeViolation(
                f"无法构建计划，scope 无法准确表达（fail-closed）: {exc}") from exc
        for step in plan.steps:
            self._check_step(step.tool, step.args, allowed_caps, ws)

    def _postflight(self, result: Dict[str, Any],
                    allowed_caps: frozenset, ws: WorkspaceScope) -> None:
        """执行后二次校验实际 task_record（LLM planner 可能偏离预检；未执行步骤跳过）。"""
        record = result.get("task_record") or {}
        for step in record.get("steps") or []:
            error = step.get("error") or ""
            if error in _SKIP_POSTFLIGHT_ERRORS or error.startswith("unknown_tool"):
                continue   # 工具未执行，无实际路径/工具越界风险
            self._check_step(step.get("tool") or "", step.get("args") or {},
                             allowed_caps, ws)

    # -- 执行 -------------------------------------------------------------------
    def submit(self, contract_projection: Mapping[str, Any], *,
               run_id: Optional[str] = None) -> BackendRunHandle:
        """以既有 AgentRuntime.execute 语义执行契约 projection；scope 真实约束。

        - 请求主体取 canonical_user_request（客观内容）；workspace write root 作为
          路径上下文（与 App 既有调用一致：``{"path": ...}``）；
        - ``task_auth=None``：沿用 AgentRuntime 默认 L0/L1 任务上下文 —— **不削弱**
          既有权限语义，也不在此伪造 16D 授权；
        - run_id 由 AgentRuntime 内部生成（stable task_id），调用方 run_id 参数不覆盖
          runtime 任务身份（身份真相归 runtime）。
        """
        # 1) 解析 + 预检（任何无法准确表达 → submit 前 fail-closed，零执行）
        try:
            request, allowed_caps, ws, extra = self._extract_scope(contract_projection)
            self._preflight(request, extra, allowed_caps, ws)
        except BackendScopeViolation:
            raise
        except Exception as exc:
            raise BackendScopeViolation(
                f"契约 scope 解析/预检失败（fail-closed）: {exc}") from exc
        # 2) 执行（语义原样透传；L2/L3 仍由 PermissionManager 默认拒绝）
        result = self._runtime.execute(request, extra if extra else None)
        # 3) 后验实际执行不得越过契约 scope
        self._postflight(result, allowed_caps, ws)
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
