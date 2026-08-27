"""Phase 16D — ApprovalBroker：一等异步审批通道的状态所有者。

位置：位于既有同步 PermissionManager **之上**。线程边界显式：

- **producer 面（executor / agent / backend 线程，锁保护，任意线程可调）**：
  ``create_request`` / ``wait_for_resolution`` / ``state_of`` / ``consume`` / 各只读查询；
- **decision 面（owner 线程 = canonical USER 决策入口，显式 ``bind_owner``）**：
  ``resolve`` / ``cancel`` / ``revoke`` / ``create_grant`` / ``revoke_grant``。
  未绑定 / 非 owner → :class:`ApprovalStateError`（backend/executor 不得做出决议）。

状态机（:class:`ApprovalState`）：PENDING → APPROVED_ONCE / APPROVED_SESSION /
DENIED / TIMED_OUT / REVOKED / CANCELLED；终态不可逆。resolve **exactly once**：
- 相同决议重复 → ``DUPLICATE``（幂等 no-op，不重复消费）；
- 与既有用户决议冲突 → ``CONFLICT``（类型化拒绝）；
- 迟于 timeout/cancel → ``LATE``（类型化拒绝）；
- 未知 id → ``UNKNOWN``。

approve_once 只消费一次：``consume`` 标记消费后 ``matching_request`` 仍可见但 gate 拒绝
重复消费。timeout：PENDING 且 now ≥ expires_at → TIMED_OUT，每个请求只发**一个**终态
事件；``sweep_timeouts`` / 各读路径惰性推进。撤销（revoke / revoke_grant）在下一个工具
边界前生效（gate 判定时已不覆盖）。

事件：``broker.events`` 为类型化 **redacted** 域事件日志（approval.requested / decided /
timed_out / cancelled / grant_created / grant_revoked）；可选外部 ``emit(etype, payload)``
回调同步转发（best-effort，失败不影响审批状态；回调不得重入本 broker）。
"""
from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from furina.agent.permission import Permission
from furina.agent.work_contract import APPROVAL_POLICY_KINDS, WorkspaceScope

from .models import (
    ApprovalDecisionKind,
    ApprovalEvent,
    ApprovalRequest,
    ApprovalResolution,
    ApprovalState,
    ApprovalStateError,
    AuthorizationGrant,
    ResolutionStatus,
    redact_args,
)

__all__ = ["ApprovalBroker"]


@dataclass
class _RequestRecord:
    request: ApprovalRequest
    state: ApprovalState
    decision: Optional[ApprovalDecisionKind] = None
    decided_at: float = 0.0
    consumed_at: Optional[float] = None   # approve_once 消费时刻（exactly once）
    detail: str = ""


@dataclass
class _GrantRecord:
    grant: AuthorizationGrant
    revoked_at: Optional[float] = None
    revoked_reason: str = ""


class ApprovalBroker:
    """审批状态所有者：exactly-once 决议 / 超时 / 撤销 / 会话 grant / redacted 事件。"""

    def __init__(self, *, clock: Optional[Callable[[], float]] = None,
                 default_approval_timeout_seconds: float = 120.0,
                 max_approval_timeout_seconds: float = 86400.0,
                 max_grant_duration_seconds: float = 86400.0 * 365,
                 emit: Optional[Callable[[str, Dict[str, Any]], None]] = None) -> None:
        for name, v in (("default_approval_timeout_seconds", default_approval_timeout_seconds),
                        ("max_approval_timeout_seconds", max_approval_timeout_seconds),
                        ("max_grant_duration_seconds", max_grant_duration_seconds)):
            if (isinstance(v, bool) or not isinstance(v, (int, float))
                    or not math.isfinite(float(v)) or v <= 0):
                raise ApprovalStateError(f"{name} 必须有限正数，得到 {v!r}")
        self._clock = clock if clock is not None else time.time
        self._default_timeout = float(default_approval_timeout_seconds)
        self._max_timeout = float(max_approval_timeout_seconds)
        self._max_grant_duration = float(max_grant_duration_seconds)
        self._emit = emit
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._owner: Optional[int] = None
        self._requests: Dict[str, _RequestRecord] = {}
        self._grants: Dict[str, _GrantRecord] = {}
        self._events: List[ApprovalEvent] = []

    # -------------------------------------------------- 时钟
    def now(self) -> float:
        return self._clock()

    # -------------------------------------------------- owner 线程（decision 面）
    def bind_owner(self, thread_id: Optional[int] = None) -> int:
        """显式绑定 owner 线程（canonical USER 决策入口）。只绑定一次。"""
        with self._lock:
            if self._owner is None:
                self._owner = thread_id if thread_id is not None else threading.get_ident()
            return self._owner

    @property
    def owner_thread_id(self) -> Optional[int]:
        return self._owner

    def is_owner(self) -> bool:
        return self._owner is not None and threading.get_ident() == self._owner

    def require_owner(self, what: str) -> None:
        """决策面变更守卫：未绑定或非 owner 线程 → ApprovalStateError。"""
        if self._owner is None:
            raise ApprovalStateError(
                f"approval 变更 '{what}' 前必须 bind_owner（owner 线程 = canonical USER 决策入口）")
        if threading.get_ident() != self._owner:
            raise ApprovalStateError(
                f"approval 变更 '{what}' 必须发生在 owner 线程（owner={self._owner}, "
                f"current={threading.get_ident()}）——backend/executor 线程不得做出决议")

    # -------------------------------------------------- 事件（redacted）
    def _log_event(self, etype: str, *, approval_id: str = "", grant_id: str = "",
                   payload: Optional[Dict[str, Any]] = None) -> None:
        ev = ApprovalEvent(etype=etype, approval_id=approval_id, grant_id=grant_id,
                           payload=dict(payload or {}), timestamp=self._clock())
        with self._lock:
            self._events.append(ev)
        if self._emit is not None:
            try:
                self._emit(etype, dict(ev.payload))
            except Exception:   # best-effort：外部 emit 失败不影响审批状态
                pass

    @property
    def events(self) -> List[ApprovalEvent]:
        with self._lock:
            return list(self._events)

    # -------------------------------------------------- producer 面：create_request
    def create_request(self, *, contract_id: str, run_id: str, tool: str, capability: str,
                       args: Optional[Mapping[str, Any]] = None, reason: str = "",
                       risk_level: Permission = Permission.L1_LOW_WRITE,
                       requested_scope: Tuple[str, ...] = (), expires_at: Optional[float] = None,
                       provenance: str = "executor",
                       policy_kind: str = "approval_required_each_step") -> ApprovalRequest:
        """executor 侧（任意线程）创建异步审批请求；参数**立即 redact**，原始参数不进入审批域。

        ``expires_at`` 缺省为 now + default_approval_timeout_seconds；必须 > now 且
        ≤ now + max_approval_timeout_seconds（有界审批窗口，无无限等待）。
        """
        if not isinstance(risk_level, Permission):
            raise ApprovalStateError(
                f"risk_level 必须是 Permission（int enum），得到 {type(risk_level).__name__}")
        if policy_kind not in APPROVAL_POLICY_KINDS:
            raise ApprovalStateError(f"policy_kind 必须 ∈ {list(APPROVAL_POLICY_KINDS)}，得到 {policy_kind!r}")
        now = self._clock()
        if expires_at is None:
            expires_at = now + self._default_timeout
        if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
            raise ApprovalStateError(f"expires_at 必须是非 bool 数值，得到 {expires_at!r}")
        exp = float(expires_at)
        if not math.isfinite(exp) or exp <= now:
            raise ApprovalStateError(f"expires_at 必须是 > now 的有限时刻，得到 {expires_at!r}")
        if exp - now > self._max_timeout:
            raise ApprovalStateError(f"expires_at 超出来自审批窗口上限 {self._max_timeout}s")
        scope = tuple(str(p).strip() for p in (requested_scope or ()) if str(p).strip())
        request = ApprovalRequest(
            approval_id=f"apv_{uuid.uuid4().hex[:12]}",
            contract_id=contract_id, run_id=run_id, tool=tool, capability=capability,
            args_redacted=redact_args(dict(args or {})),
            requested_scope=scope, reason=reason, risk_level=risk_level,
            created_at=now, expires_at=exp, policy_kind=policy_kind, provenance=provenance,
        )
        with self._lock:
            self._requests[request.approval_id] = _RequestRecord(request, ApprovalState.PENDING)
        self._log_event("approval.requested", approval_id=request.approval_id,
                        payload=request.to_audit_dict())
        return request

    # -------------------------------------------------- producer 面：只读查询
    def matching_request(self, *, contract_id: str, run_id: str, tool: str,
                         requested_scope: Tuple[str, ...] = ()) -> Optional[ApprovalRequest]:
        """同一步（contract/run/tool/scope 全等）的**最近**请求（任意终态）；无 → None。

        gate 用它复用既有请求：终态请求不重复创建（审批被拒后重检仍拒绝，零新请求）。
        """
        scope = tuple(str(p).strip() for p in (requested_scope or ()) if str(p).strip())
        with self._lock:
            found: Optional[ApprovalRequest] = None
            for rec in self._requests.values():
                r = rec.request
                if (r.contract_id == contract_id and r.run_id == run_id
                        and r.tool == tool and r.requested_scope == scope):
                    found = r   # 插入序 = 创建序 → 覆盖后即最近
            return found

    def state_of(self, approval_id: str) -> ApprovalState:
        """读状态（任意线程）；到期 PENDING 惰性推进为 TIMED_OUT。"""
        with self._lock:
            rec = self._requests.get(approval_id)
            if rec is None:
                raise ApprovalStateError(f"unknown approval_id: {approval_id}")
            self._maybe_timeout_locked(rec)
            return rec.state

    def is_consumed(self, approval_id: str) -> bool:
        """approve_once 是否已被消费（exactly once 判定）。"""
        with self._lock:
            rec = self._requests.get(approval_id)
            if rec is None or rec.state != ApprovalState.APPROVED_ONCE:
                return False
            return rec.consumed_at is not None

    def wait_for_resolution(self, approval_id: str, timeout: Optional[float] = None) -> ApprovalResolution:
        """阻塞等待至终态（任意线程；wait/observe 面）；返回类型化 resolution。

        ``timeout=None`` 时由请求 expiry 兜底（到期即 TIMED_OUT，绝不无限阻塞）；
        显式 ``timeout`` 耗尽仍未获决议 → ``LATE``（fail-closed）。
        """
        deadline_real = None if timeout is None else time.monotonic() + float(timeout)
        with self._cv:
            while True:
                rec = self._requests.get(approval_id)
                if rec is None:
                    return ApprovalResolution(False, ResolutionStatus.UNKNOWN, approval_id,
                                              detail="approval_id 不存在")
                self._maybe_timeout_locked(rec)
                if rec.state != ApprovalState.PENDING:
                    return self._resolution_locked(rec)
                if deadline_real is not None and time.monotonic() >= deadline_real:
                    return ApprovalResolution(
                        False, ResolutionStatus.LATE, approval_id,
                        detail="观察窗口耗尽仍未获得决议（fail-closed 视为拒绝）")
                self._cv.wait(0.05)

    # -------------------------------------------------- decision 面：resolve
    def resolve(self, approval_id: str, decision: ApprovalDecisionKind, *,
                reason: str = "") -> ApprovalResolution:
        """决议（owner 线程）：exactly-once；重复 → DUPLICATE，冲突 → CONFLICT，
        迟于 timeout/cancel → LATE，未知 → UNKNOWN。"""
        if not isinstance(decision, ApprovalDecisionKind):
            raise ApprovalStateError(f"decision 必须是 ApprovalDecisionKind，得到 {decision!r}")
        self.require_owner("resolve")
        with self._cv:
            rec = self._requests.get(approval_id)
            if rec is None:
                return ApprovalResolution(False, ResolutionStatus.UNKNOWN, approval_id,
                                          decision=decision, detail="approval_id 不存在")
            self._maybe_timeout_locked(rec)
            if rec.state == ApprovalState.PENDING:
                rec.state = decision.to_state()
                rec.decision = decision
                rec.decided_at = self._clock()
                rec.detail = reason
                self._cv.notify_all()
                self._log_event(
                    "approval.decided", approval_id=approval_id,
                    payload={**rec.request.to_audit_dict(), "decision": decision.value,
                             "decided_at": rec.decided_at, "detail": reason})
                return ApprovalResolution(True, ResolutionStatus.RESOLVED, approval_id,
                                          decision=decision, decided_at=rec.decided_at,
                                          detail=reason)
            if rec.decision == decision:
                return ApprovalResolution(True, ResolutionStatus.DUPLICATE, approval_id,
                                          decision=decision, decided_at=rec.decided_at,
                                          detail="重复决议幂等（已生效，不重复消费）")
            if rec.state in (ApprovalState.TIMED_OUT, ApprovalState.CANCELLED):
                return ApprovalResolution(False, ResolutionStatus.LATE, approval_id,
                                          decision=decision, decided_at=rec.decided_at,
                                          detail=f"决议迟于 {rec.state.value}（无效果，类型化拒绝）")
            return ApprovalResolution(False, ResolutionStatus.CONFLICT, approval_id,
                                      decision=decision, decided_at=rec.decided_at,
                                      detail=f"与既有决议 {rec.state.value} 冲突（类型化拒绝）")

    def revoke(self, approval_id: str, *, reason: str = "") -> ApprovalResolution:
        """撤销审批（owner 线程）：PENDING / APPROVED_* → REVOKED；下一工具边界前生效。"""
        self.require_owner("revoke")
        with self._cv:
            rec = self._requests.get(approval_id)
            if rec is None:
                return ApprovalResolution(False, ResolutionStatus.UNKNOWN, approval_id,
                                          detail="approval_id 不存在")
            self._maybe_timeout_locked(rec)
            if rec.state in (ApprovalState.PENDING, ApprovalState.APPROVED_ONCE,
                             ApprovalState.APPROVED_SESSION):
                rec.state = ApprovalState.REVOKED
                rec.decision = ApprovalDecisionKind.REVOKED
                rec.decided_at = self._clock()
                rec.detail = reason
                rec.consumed_at = None   # 撤销后不可再消费
                self._cv.notify_all()
                self._log_event(
                    "approval.decided", approval_id=approval_id,
                    payload={**rec.request.to_audit_dict(),
                             "decision": ApprovalDecisionKind.REVOKED.value,
                             "decided_at": rec.decided_at, "detail": reason})
                return ApprovalResolution(True, ResolutionStatus.RESOLVED, approval_id,
                                          decision=ApprovalDecisionKind.REVOKED,
                                          decided_at=rec.decided_at, detail=reason)
            if rec.state == ApprovalState.REVOKED:
                return ApprovalResolution(True, ResolutionStatus.DUPLICATE, approval_id,
                                          decision=ApprovalDecisionKind.REVOKED,
                                          decided_at=rec.decided_at,
                                          detail="已撤销（幂等 no-op）")
            if rec.state in (ApprovalState.TIMED_OUT, ApprovalState.CANCELLED):
                return ApprovalResolution(False, ResolutionStatus.LATE, approval_id,
                                          decision=ApprovalDecisionKind.REVOKED,
                                          decided_at=rec.decided_at,
                                          detail=f"撤销迟于 {rec.state.value}（无效果）")
            return ApprovalResolution(False, ResolutionStatus.CONFLICT, approval_id,
                                      decision=ApprovalDecisionKind.REVOKED,
                                      decided_at=rec.decided_at,
                                      detail=f"与既有决议 {rec.state.value} 冲突")

    def cancel(self, approval_id: str, *, reason: str = "") -> ApprovalResolution:
        """取消等待中的审批（owner 线程）：PENDING → CANCELLED，解阻所有等待者。"""
        self.require_owner("cancel")
        with self._cv:
            rec = self._requests.get(approval_id)
            if rec is None:
                return ApprovalResolution(False, ResolutionStatus.UNKNOWN, approval_id,
                                          detail="approval_id 不存在")
            self._maybe_timeout_locked(rec)
            if rec.state == ApprovalState.PENDING:
                rec.state = ApprovalState.CANCELLED
                rec.decided_at = self._clock()
                rec.detail = reason
                self._cv.notify_all()
                self._log_event("approval.cancelled", approval_id=approval_id,
                                payload={**rec.request.to_audit_dict(), "detail": reason})
                return ApprovalResolution(True, ResolutionStatus.RESOLVED, approval_id,
                                          decision=None, decided_at=rec.decided_at, detail=reason)
            if rec.state == ApprovalState.CANCELLED:
                return ApprovalResolution(True, ResolutionStatus.DUPLICATE, approval_id,
                                          decision=None, decided_at=rec.decided_at,
                                          detail="已取消（幂等 no-op）")
            if rec.state in (ApprovalState.TIMED_OUT, ApprovalState.REVOKED):
                return ApprovalResolution(False, ResolutionStatus.LATE, approval_id,
                                          decision=None, decided_at=rec.decided_at,
                                          detail=f"取消迟于 {rec.state.value}（无效果）")
            return ApprovalResolution(False, ResolutionStatus.CONFLICT, approval_id,
                                      decision=None, decided_at=rec.decided_at,
                                      detail=f"与既有决议 {rec.state.value} 冲突")

    def consume(self, approval_id: str) -> bool:
        """approve_once **恰好消费一次**（producer 面）：APPROVED_ONCE 未消费 → 标记并 True。"""
        now = self._clock()
        with self._lock:
            rec = self._requests.get(approval_id)
            if rec is None or rec.state != ApprovalState.APPROVED_ONCE or rec.consumed_at is not None:
                return False
            rec.consumed_at = now
            return True

    # -------------------------------------------------- timeout
    def _maybe_timeout_locked(self, rec: _RequestRecord) -> bool:
        """PENDING 且 now ≥ expires_at → TIMED_OUT（只从 PENDING 转移 → 事件恰好一次）。"""
        if rec.state != ApprovalState.PENDING:
            return False
        if self._clock() < rec.request.expires_at:
            return False
        rec.state = ApprovalState.TIMED_OUT
        rec.decision = ApprovalDecisionKind.TIMEOUT
        rec.decided_at = self._clock()
        rec.detail = "approval_timeout"
        self._cv.notify_all()
        self._log_event("approval.timed_out", approval_id=rec.request.approval_id,
                        payload=rec.request.to_audit_dict())
        return True

    def sweep_timeouts(self) -> List[str]:
        """推进所有到期 PENDING → TIMED_OUT；返回本轮新超时的 approval_id 列表。"""
        timed_out: List[str] = []
        with self._lock:
            for approval_id, rec in list(self._requests.items()):
                if self._maybe_timeout_locked(rec):
                    timed_out.append(approval_id)
        return timed_out

    # -------------------------------------------------- decision 面：会话 grant
    def create_grant(self, *, user_event_id: str, capability: str, tool_pattern: str,
                     workspace_scope: WorkspaceScope, expiry: float, scope_note: str = "",
                     issued_at: Optional[float] = None) -> AuthorizationGrant:
        """创建会话/持久授权（owner 线程）：**必须**携带 canonical USER 事件 id
        （模型层强制；backend/LLM 无此能力）；expiry 有界（无永久 grant）。"""
        self.require_owner("create_grant")
        now = self._clock()
        if issued_at is None:
            issued = now
        else:
            if isinstance(issued_at, bool) or not isinstance(issued_at, (int, float)):
                raise ApprovalStateError(f"issued_at 必须是非 bool 数值或 None，得到 {issued_at!r}")
            issued = float(issued_at)
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
            raise ApprovalStateError(f"expiry 必须是非 bool 数值，得到 {expiry!r}")
        exp = float(expiry)
        if not math.isfinite(exp):
            raise ApprovalStateError(f"expiry 必须有限（无永久 grant）: {expiry!r}")
        if exp - issued > self._max_grant_duration:
            raise ApprovalStateError(
                f"grant 时长超过上限 {self._max_grant_duration}s（无永久 grant）")
        grant = AuthorizationGrant(
            grant_id=f"gr_{uuid.uuid4().hex[:12]}",
            user_event_id=user_event_id, capability=capability, tool_pattern=tool_pattern,
            workspace_scope=workspace_scope, issued_at=issued, expiry=exp, scope_note=scope_note,
        )
        with self._lock:
            self._grants[grant.grant_id] = _GrantRecord(grant)
        self._log_event("approval.grant_created", grant_id=grant.grant_id, payload=grant.to_dict())
        return grant

    def revoke_grant(self, grant_id: str, *, reason: str = "") -> AuthorizationGrant:
        """撤销授权（owner 线程）：记录 revoked_at；下一工具边界前生效。"""
        self.require_owner("revoke_grant")
        with self._lock:
            rec = self._grants.get(grant_id)
            if rec is None:
                raise ApprovalStateError(f"unknown grant_id: {grant_id}")
            if rec.revoked_at is None:
                rec.revoked_at = self._clock()
                rec.revoked_reason = reason
                self._log_event("approval.grant_revoked", grant_id=grant_id,
                                payload={**rec.grant.to_dict(), "revoked_at": rec.revoked_at,
                                         "revoked_reason": reason})
            return rec.grant

    def covering_grant(self, *, tool: str, capability: str, paths: Tuple[str, ...] = (),
                       now: Optional[float] = None) -> Optional[AuthorizationGrant]:
        """返回覆盖该 step 的**激活** grant（未撤销且未过期，latest 优先）；无 → None。"""
        now = self._clock() if now is None else now
        paths = tuple(str(p) for p in (paths or ()))
        best: Optional[AuthorizationGrant] = None
        with self._lock:
            for rec in self._grants.values():
                if rec.revoked_at is not None or now >= rec.grant.expiry:
                    continue
                g = rec.grant
                if not g.matches(tool, capability, paths):
                    continue
                if best is None or (g.issued_at, g.grant_id) > (best.issued_at, best.grant_id):
                    best = g
        return best

    def matching_grants(self, *, tool: str, capability: str,
                        paths: Tuple[str, ...] = ()) -> List[AuthorizationGrant]:
        """所有**匹配**该 step 的 grant（含已过期/已撤销；供 gate 诊断 inactive 拒绝）。"""
        paths = tuple(str(p) for p in (paths or ()))
        with self._lock:
            return [rec.grant for rec in self._grants.values()
                    if rec.grant.matches(tool, capability, paths)]

    def grant_state(self, grant_id: str, *, now: Optional[float] = None) -> Dict[str, Any]:
        now = self._clock() if now is None else now
        with self._lock:
            rec = self._grants.get(grant_id)
            if rec is None:
                raise ApprovalStateError(f"unknown grant_id: {grant_id}")
            g = rec.grant
            return {**g.to_dict(),
                    "active": rec.revoked_at is None and now < g.expiry,
                    "revoked_at": rec.revoked_at,
                    "revoked_reason": rec.revoked_reason}

    def list_grants(self) -> List[AuthorizationGrant]:
        with self._lock:
            return [rec.grant for rec in self._grants.values()]

    # -------------------------------------------------- 内部
    def _resolution_locked(self, rec: _RequestRecord) -> ApprovalResolution:
        ok = rec.state in (ApprovalState.APPROVED_ONCE, ApprovalState.APPROVED_SESSION)
        return ApprovalResolution(
            ok=ok,
            status=ResolutionStatus.RESOLVED,
            approval_id=rec.request.approval_id,
            decision=rec.decision,
            decided_at=rec.decided_at,
            detail=rec.detail or rec.state.value,
        )
