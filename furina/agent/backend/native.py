"""Phase 16B — Native AgentRuntime backend（首个 conformance 实现，薄包装 + 真 scope 约束）。

包装既有 :class:`furina.agent.agent_runtime.AgentRuntime.execute`，**语义不变**：

- 任务记录（task_record）、ToolResult 验证（ok ∧ verified）、权限行为全部原样透传；
- native “completed” 结果在 Phase 16 backend 边界仍属 **unverified**（16F 拥有 verifier）。

**真 scope 约束（Reviewer Patch 1 + Patch 2）**：

1. **单次 build_plan**（Patch 2）：本模块**不**调用 planner 预检（消除"双 planner 调用"
   安全模型）；build_plan 只在 AgentRuntime.execute 内发生一次。scope/capability 检查
   通过两个真实边界在每次 step 的 ``tool.run`` **之前**执行：
   a. **Native 专属 task-scoped AuthorizationContext**（allowed_tools = 冻结快照 ∩ 契约
      allowed_capabilities；max_permission = L1）→ 既有 PermissionManager 在工具边界
      拒绝 allowed_tools 之外的 step（越权 capability / 无归属工具 → task_scope_mismatch
      → permission_denied）；L2/L3 因 max_permission=L1 **继续拒绝**（不实现 16D 异步
      审批，不削弱既有权限语义）。
   b. **execution_guard**（AgentRuntime 默认关闭的窄钩子，每调用传入，并发安全）→
      真实路径封闭：resolved path（realpath + 不存在目标的最近现存祖先解析）必须在
      workspace 内；workspace 内 symlink/junction 指向外部 → tool.run 前拒绝；
      新文件目标 / 读路径 / 写路径均覆盖。
2. **postflight 只作诊断**（Patch 2）：执行后对实际 task_record 做只读复核，发现越界仅
   ``log.warning``，**不**作为阻止副作用的安全门（安全门由 guard 在 tool.run 前承担）。

**冻结 capability ownership（Patch 2）**：构造时建立不可变 tool→capability 快照；
外部 CapabilityRegistry 后续修改**不得**改变既有 backend 的授权；重复 tool owner、
available 但 runtime 无对应工具等不一致事实在构造时 fail-closed；Native 只声明实际
AgentRuntime 可执行的能力（available 且工具真实存在）。
"""
from __future__ import annotations

import math
import os
import time
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from furina.agent.agent_runtime import AgentRuntime
from furina.agent.capabilities.models import CapabilityRegistry
from furina.agent.permission import AuthorizationContext, Permission
from furina.agent.work_contract import WorkspaceScope
from furina.core import get_logger

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

log = get_logger("agent.backend.native")


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
        # 冻结 tool→capability 所有权快照（构造时刻固化；外部 registry 后续修改不影响授权）。
        self._cap_snapshot = self._build_capability_snapshot(capability_registry, runtime)
        self._descriptor = BackendDescriptor(
            backend_id="native",
            display_name="Native AgentRuntime",
            description="包装既有 AgentRuntime.execute 的本地 backend（Phase 16B conformance）",
            protocol_version=PROTOCOL_VERSION,
        )
        # 只声明实际 AgentRuntime 可执行的能力：available 且声明了真实存在的工具。
        # （构造校验已保证 available 能力的工具全部存在；空工具集能力不声明。）
        registered = set(runtime.tools.list())
        self._capabilities = BackendCapabilities(
            capability_ids=tuple(sorted(
                c.capability_id for c in capability_registry.all()
                if c.available and c.tools and all(t in registered for t in c.tools))),
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

    # -- capability ownership 冻结 -------------------------------------------------
    @staticmethod
    def _build_capability_snapshot(registry: CapabilityRegistry,
                                   runtime: AgentRuntime) -> Mapping[str, str]:
        """构造时刻固化 tool→capability 所有权；不一致事实 fail-closed。

        - 同一 tool 被两个不同 capability 声明（重复 owner）→ BackendError；
        - available 能力声明的工具在 runtime 不存在 → BackendError。
        返回 MappingProxyType 不可变快照（外部 registry 后续修改不影响授权）。
        """
        registered = set(runtime.tools.list())
        snapshot: Dict[str, str] = {}
        for cap in registry.all():
            for tool in cap.tools:
                prev = snapshot.get(tool)
                if prev is not None and prev != cap.capability_id:
                    raise BackendError(
                        f"重复 tool owner: {tool!r} 同时被 '{prev}' 与 '{cap.capability_id}' "
                        "声明（不一致事实 fail-closed）")
                snapshot[tool] = cap.capability_id
        for cap in registry.all():
            if cap.available:
                missing = [t for t in cap.tools if t not in registered]
                if missing:
                    raise BackendError(
                        f"capability '{cap.capability_id}' available 但 runtime 无对应工具: "
                        f"{missing}（不一致事实 fail-closed）")
        return MappingProxyType(dict(snapshot))

    # -- scope 解析与单步检查 -------------------------------------------------------
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

    @staticmethod
    def _resolve_path(path: str) -> str:
        """realpath 语义 + 不存在目标的**最近现存祖先**解析。

        - 已存在路径：os.path.realpath 完整解析 symlink/junction（Windows junction 同样）；
        - 新文件目标（不存在）：逐级上溯到最近现存祖先再 realpath，之后按名字逐级拼回
          —— workspace 内 symlink/junction 指向外部 → 解析结果越出根 → 拒绝。
        """
        ap = os.path.abspath(os.path.expanduser(str(path)))
        cur = ap
        suffix = []
        while not os.path.exists(cur):
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            suffix.append(os.path.basename(cur))
            cur = parent
        real = os.path.realpath(cur)
        for name in reversed(suffix):
            real = os.path.join(real, name)
        return real

    @staticmethod
    def _within(real_path: str, real_roots: Tuple[str, ...]) -> bool:
        rp = os.path.normcase(real_path)
        for rr in real_roots:
            root = os.path.normcase(rr)
            if rp == root or rp.startswith(root + os.sep):
                return True
        return False

    def _check_path_closed(self, path: str, ws: WorkspaceScope, writable: bool) -> None:
        """真实路径封闭：resolved path 必须在 workspace 内（写工具限 write roots）。"""
        real = self._resolve_path(path)
        roots = ws.write_roots if writable else (ws.read_roots + ws.write_roots)
        real_roots = tuple(self._resolve_path(r) for r in roots)
        if not self._within(real, real_roots):
            kind = "write" if writable else "read"
            raise BackendScopeViolation(
                f"execution_guard: 路径越界（{kind} scope, realpath）: {path!r} -> {real!r}"
                "（含 symlink/junction 解析；新文件目标按最近现存祖先解析）")

    def _check_step(self, tool_name: str, args: Mapping[str, Any],
                    allowed_caps: frozenset, ws: WorkspaceScope) -> None:
        """单步 scope 门（tool.run 前）：能力归属 ∈ allowed_capabilities，路径真实封闭。"""
        if not tool_name:
            raise BackendScopeViolation("execution_guard: step 缺失 tool 名（fail-closed）")
        cap = self._cap_snapshot.get(tool_name)
        if cap is None:
            raise BackendScopeViolation(
                f"execution_guard: tool '{tool_name}' 无法归属任何 capability（fail-closed）")
        if cap not in allowed_caps:
            raise BackendScopeViolation(
                f"execution_guard: 越权 capability: tool '{tool_name}' 属于 '{cap}'，"
                f"超出契约 allowed_capabilities {sorted(allowed_caps)}")
        try:
            tool = self._runtime.tools.get(tool_name)
        except Exception as exc:
            raise BackendScopeViolation(
                f"execution_guard: tool '{tool_name}' 未注册（fail-closed）") from exc
        perm = getattr(tool, "permission", None)
        if not isinstance(perm, Permission):
            raise BackendScopeViolation(
                f"execution_guard: tool '{tool_name}' 权限声明缺失（fail-closed）")
        writable = perm.value >= Permission.L1_LOW_WRITE.value
        for p in AgentRuntime._step_paths(tool_name, dict(args or {})):
            self._check_path_closed(p, ws, writable)

    def _make_guard(self, allowed_caps: frozenset, ws: WorkspaceScope):
        """构造每 submit 专属 guard 闭包（AgentRuntime 在每次 tool.run 前调用）。

        闭包只捕获构造时刻的契约事实（allowed_caps/ws）与冻结快照 → 并发安全，
        无任何跨调用共享可变状态，也不 monkeypatch planner。
        """
        def _guard(step, tool) -> None:
            self._check_step(step.tool, step.args, allowed_caps, ws)
        return _guard

    def _diagnostic_postflight(self, result: Dict[str, Any],
                               allowed_caps: frozenset, ws: WorkspaceScope) -> None:
        """诊断性后验：只读复核实际执行，越界仅记日志（**不**阻止副作用——安全门由 guard 承担）。"""
        for step in (result.get("task_record") or {}).get("steps") or []:
            error = step.get("error") or ""
            if (error == "permission_denied" or error.startswith("execution_guard:")
                    or error.startswith("unknown_tool")):
                continue   # 工具未执行：无实际越界风险
            try:
                self._check_step(step.get("tool") or "", step.get("args") or {},
                                 allowed_caps, ws)
            except BackendScopeViolation as exc:
                log.warning("native postflight 诊断：实际执行越过契约 scope（guard 应已拦截）: %s", exc)

    # -- 执行 -------------------------------------------------------------------
    def submit(self, contract_projection: Mapping[str, Any], *,
               run_id: Optional[str] = None) -> BackendRunHandle:
        """以既有 AgentRuntime.execute 语义执行契约 projection；scope 真实约束。

        - 请求主体取 canonical_user_request；workspace write root 作为路径上下文
          （与 App 既有调用一致：``{"path": ...}``）；
        - build_plan 只发生一次（execute 内部）；本方法不做任何 planner 预检；
        - task_auth = Native 专属 task-scoped AuthorizationContext（allowed_tools 白名单 +
          max_permission=L1）：PermissionManager 在真实工具边界拒绝越权 capability /
          无归属工具；L2/L3 继续拒绝（不实现 16D 审批，不削弱既有权限语义）；
        - execution_guard 在每次 tool.run 前做真实路径封闭（symlink/junction 逃逸拒绝）。
        """
        # 1) 解析契约 scope（无法准确表达 → submit 前 fail-closed，零执行）
        try:
            request, allowed_caps, ws, extra = self._extract_scope(contract_projection)
        except BackendScopeViolation:
            raise
        except Exception as exc:
            raise BackendScopeViolation(
                f"契约 scope 解析失败（fail-closed）: {exc}") from exc
        # 2) 每 submit 专属 guard + task-scoped AuthorizationContext（并发安全，无共享可变态）
        guard = self._make_guard(allowed_caps, ws)
        allowed_tools = tuple(sorted(
            t for t, cap in self._cap_snapshot.items() if cap in allowed_caps))
        task_auth = AuthorizationContext(
            authorization_id=f"auth_native_{contract_projection.get('contract_id','')}",
            max_permission=Permission.L1_LOW_WRITE,
            allowed_tools=allowed_tools,
            allowed_path_root="",     # 多 root workspace 由 guard 做真实路径封闭
            source="native_backend",
            is_default=False,
        )
        # 3) 执行：build_plan 仅一次；guard 在每次 tool.run 前检查
        result = self._runtime.execute(
            request, extra if extra else None, task_auth=task_auth, execution_guard=guard)
        # 4) 诊断性后验（只记日志，不阻止）
        self._diagnostic_postflight(result, allowed_caps, ws)
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
