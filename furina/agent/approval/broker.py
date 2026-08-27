"""Phase 16D — ApprovalBroker：一等异步审批通道的状态所有者。

位置：位于既有同步 PermissionManager **之上**。线程边界显式：

- **owner 只在构造时绑定**（``owner_thread_id``，由可信组合根传入）。decision 面
  （``resolve`` / ``cancel`` / ``revoke`` / ``create_grant`` / ``revoke_grant``）
  只允许 owner 线程；backend/executor 线程拿到 broker 引用后**无法抢占或改绑
  owner**（无 ``bind_owner``，first-come-first-served 抢占向量已删除）；
- **producer 面（executor / agent / backend 线程，锁保护，任意线程可调）**：
  ``create_request`` / ``get_or_create_request`` / ``wait_for_resolution`` /
  ``state_of`` / ``consume`` / ``issue_permit`` / ``consume_permit`` / 各只读查询。

Reviewer Patch 关键收紧（本文件）：

1. ``get_or_create_request``：**单锁内**查找或创建——并发同一步（完整身份相同）
   只能产生一个请求；
2. ``resolve(APPROVE_SESSION)`` 与 ``create_grant`` **必须**携带经可信入口验证器
   （构造注入 ``user_evidence_verifier``）确认的 canonical USER 证据；格式正则
   只是必要条件，不是真实性证明；未配置验证器一律 fail-closed；
3. grant 有效窗口 ``issued_at <= now < expiry``：``create_grant`` 拒绝未来签发
   （``issued_at > now``）与已过期新 grant（``expiry <= now``）；
4. ``issue_permit`` / ``consume_permit``：gate ALLOW → 真实工具边界**原子**消费/
   复核（approve_once 恰好一次、session 未被撤销、grant 未撤销且在有效窗口、
   permit 自身未消费且在 TTL 内）——消除 ALLOW 到 tool.run 的撤销 TOCTOU；
5. 事件载荷递归 sanitize + 递归冻结；导出/emit 防御复制。

状态机（:class:`ApprovalState`）：PENDING → APPROVED_ONCE / APPROVED_SESSION /
DENIED / TIMED_OUT / REVOKED / CANCELLED；终态不可逆。resolve **exactly once**：
- 相同决议重复 → ``DUPLICATE``（幂等 no-op，不重复消费）；
- 与既有用户决议冲突 → ``CONFLICT``（类型化拒绝）；
- 迟于 timeout/cancel → ``LATE``（类型化拒绝）；
- 未知 id → ``UNKNOWN``。

timeout：PENDING 且 now ≥ expires_at → TIMED_OUT，每个请求只发**一个**终态事件；
``sweep_timeouts`` / 各读路径惰性推进。撤销（revoke / revoke_grant）在下一个工具
边界前生效（consume_permit 复核时已不覆盖）。
"""
from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from furina.agent.permission import Permission
from furina.agent.work_contract import APPROVAL_POLICY_KINDS, WorkspaceScope

from .models import (
    MAX_PERMIT_TTL_SECONDS,
    ApprovalDecisionKind,
    ApprovalEvent,
    ApprovalRequest,
    ApprovalResolution,
    ApprovalState,
    ApprovalStateError,
    AuthorizationGrant,
    PermitOutcome,
    ResolutionStatus,
    ToolPermit,
    VerifiedUserEvidence,
    canonical_args_digest,
    redact_args,
    sanitize_text,
    sanitize_tree,
)

__all__ = ["ApprovalBroker"]

UserEvidenceVerifier = Callable[[str], Any]


@dataclass
class _RequestRecord:
    request: ApprovalRequest
    state: ApprovalState
    decision: Optional[ApprovalDecisionKind] = None
    decided_at: float = 0.0
    consumed_at: Optional[float] = None   # approve_once 消费时刻（exactly once）
    detail: str = ""
    #: APPROVE_SESSION 决议的 canonical USER 证据 id（经可信入口验证）。
    decided_by_user_event: str = ""


@dataclass
class _GrantRecord:
    grant: AuthorizationGrant
    revoked_at: Optional[float] = None
    revoked_reason: str = ""
    #: 铸造该 grant 的可信验证器名（VerifiedUserEvidence.verified_by）。
    verified_by: str = ""


@dataclass
class _PermitRecord:
    permit: ToolPermit
    consumed_at: Optional[float] = None


class ApprovalBroker:
    """审批状态所有者：exactly-once 决议 / 超时 / 撤销 / 会话 grant / permit / redacted 事件。

    构造参数（可信组合根所有）：

    - ``owner_thread_id``：owner 线程**只在构造时绑定**（backend 不得抢占；构造后
      无任何改绑 API）。None = decision 面永久锁定（fail-closed）；
    - ``user_evidence_verifier``：canonical USER 事件真实性验证器（可信入口，如
      C6 事件台账查询）。**approve_session 与 grant 无它一律 fail-closed**。
    """

    def __init__(self, *, clock: Optional[Callable[[], float]] = None,
                 owner_thread_id: Optional[int] = None,
                 user_evidence_verifier: Optional[UserEvidenceVerifier] = None,
                 user_evidence_source: str = "trusted_entry",
                 default_approval_timeout_seconds: float = 120.0,
                 max_approval_timeout_seconds: float = 86400.0,
                 max_grant_duration_seconds: float = 86400.0 * 365,
                 permit_ttl_seconds: float = 30.0,
                 emit: Optional[Callable[[str, Dict[str, Any]], None]] = None) -> None:
        for name, v in (("default_approval_timeout_seconds", default_approval_timeout_seconds),
                        ("max_approval_timeout_seconds", max_approval_timeout_seconds),
                        ("max_grant_duration_seconds", max_grant_duration_seconds)):
            if (isinstance(v, bool) or not isinstance(v, (int, float))
                    or not math.isfinite(float(v)) or v <= 0):
                raise ApprovalStateError(f"{name} 必须有限正数，得到 {v!r}")
        if (isinstance(permit_ttl_seconds, bool) or not isinstance(permit_ttl_seconds, (int, float))
                or not math.isfinite(float(permit_ttl_seconds)) or permit_ttl_seconds <= 0
                or permit_ttl_seconds > MAX_PERMIT_TTL_SECONDS):
            raise ApprovalStateError(
                f"permit_ttl_seconds 必须在 (0, {MAX_PERMIT_TTL_SECONDS}] 内，得到 {permit_ttl_seconds!r}")
        if not callable(user_evidence_verifier) and user_evidence_verifier is not None:
            raise ApprovalStateError("user_evidence_verifier 必须是可调用或 None")
        if not isinstance(user_evidence_source, str) or not user_evidence_source.strip():
            raise ApprovalStateError("user_evidence_source 必须是非空 str")
        self._clock = clock if clock is not None else time.time
        self._owner = owner_thread_id   # 构造期唯一绑定点；此后不可变
        self._verifier = user_evidence_verifier
        self._verifier_name = sanitize_text(user_evidence_source.strip(), max_len=120)
        self._default_timeout = float(default_approval_timeout_seconds)
        self._max_timeout = float(max_approval_timeout_seconds)
        self._max_grant_duration = float(max_grant_duration_seconds)
        self._permit_ttl = float(permit_ttl_seconds)
        self._emit = emit
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._requests: Dict[str, _RequestRecord] = {}
        self._grants: Dict[str, _GrantRecord] = {}
        self._permits: Dict[str, _PermitRecord] = {}
        self._events: List[ApprovalEvent] = []

    # -------------------------------------------------- 时钟
    def now(self) -> float:
        return self._clock()

    # -------------------------------------------------- owner 线程（decision 面）
    @property
    def owner_thread_id(self) -> Optional[int]:
        """owner 线程 id（构造期绑定；无 bind API——backend 不得抢占 owner）。"""
        return self._owner

    @property
    def user_evidence_configured(self) -> bool:
        return self._verifier is not None

    def is_owner(self) -> bool:
        return self._owner is not None and threading.get_ident() == self._owner

    def require_owner(self, what: str) -> None:
        """决策面变更守卫：未绑定或非 owner 线程 → ApprovalStateError。"""
        if self._owner is None:
            raise ApprovalStateError(
                f"approval 变更 '{what}' 需要 owner 线程，但 broker 构造时未绑定 "
                "(owner_thread_id=None → decision 面永久锁定，fail-closed)")
        if threading.get_ident() != self._owner:
            raise ApprovalStateError(
                f"approval 变更 '{what}' 必须发生在 owner 线程（owner={self._owner}, "
                f"current={threading.get_ident()}）——backend/executor 线程不得做出决议；"
                "owner 仅在构造时由可信组合根绑定，无运行期改绑 API")

    # -------------------------------------------------- canonical USER 证据
    def verify_user_evidence(self, user_event_id: str) -> VerifiedUserEvidence:
        """经**可信入口验证器**确认 canonical USER 事件（唯一铸造 VerifiedUserEvidence 的路径）。

        - 未配置验证器 → fail-closed（ApprovalStateError）；
        - 格式正则只是必要条件；验证器返回假值/抛错 → fail-closed。
        """
        if not isinstance(user_event_id, str):
            raise ApprovalStateError(f"user_event_id 必须是 str，得到 {user_event_id!r}")
        if self._verifier is None:
            raise ApprovalStateError(
                "canonical USER 证据验证器未配置（user_evidence_verifier=None）——"
                "approve_session / grant 一律 fail-closed：格式正则不是真实性证明")
        now = self._clock()
        try:
            authentic = self._verifier(user_event_id)
        except Exception as exc:
            raise ApprovalStateError(
                f"USER 证据验证器异常（fail-closed，不泄漏细节）: {type(exc).__name__}") from exc
        if not authentic:
            raise ApprovalStateError(
                f"USER 事件 {sanitize_text(user_event_id, max_len=120)} 未能通过可信入口验证"
                "（格式合法 ≠ 真实存在：backend/LLM 无法伪造验证器确认）")
        return VerifiedUserEvidence(
            user_event_id=user_event_id, verified_at=now, verified_by=self._verifier_name)

    def _require_user_evidence(self, what: str,
                               user_evidence: Union[str, VerifiedUserEvidence, None]
                               ) -> VerifiedUserEvidence:
        """决议/授权入口的统一证据校验：None → fail-closed；str → 过验证器；
        VerifiedUserEvidence → 校验铸造者与本 broker 的可信验证器一致。"""
        if user_evidence is None:
            raise ApprovalStateError(
                f"'{what}' 必须携带 canonical USER 证据（user_evidence）："
                "经可信入口验证的存在性证明，不接受任何缺省/推断")
        if isinstance(user_evidence, str):
            return self.verify_user_evidence(user_evidence)
        if isinstance(user_evidence, VerifiedUserEvidence):
            if user_evidence.verified_by != self._verifier_name or self._verifier is None:
                raise ApprovalStateError(
                    f"'{what}' 的 USER 证据非本 broker 可信入口铸造"
                    f"（verified_by={user_evidence.verified_by!r} ≠ {self._verifier_name!r}）")
            return user_evidence
        raise ApprovalStateError(
            f"'{what}' 的 user_evidence 必须是 str 或 VerifiedUserEvidence，"
            f"得到 {type(user_evidence).__name__}")

    # -------------------------------------------------- 事件（redacted + 不可变）
    def _log_event(self, etype: str, *, approval_id: str = "", grant_id: str = "",
                   payload: Optional[Dict[str, Any]] = None) -> None:
        ev = ApprovalEvent(etype=etype, approval_id=sanitize_text(approval_id, max_len=64),
                           grant_id=sanitize_text(grant_id, max_len=64),
                           payload=sanitize_tree(dict(payload or {})),   # type: ignore[arg-type]
                           timestamp=self._clock())
        with self._lock:
            self._events.append(ev)
        if self._emit is not None:
            try:
                self._emit(etype, ev.to_payload())
            except Exception:   # best-effort：外部 emit 失败不影响审批状态
                pass

    @property
    def events(self) -> List[ApprovalEvent]:
        with self._lock:
            return list(self._events)

    # -------------------------------------------------- producer 面：请求创建
    def _normalize_request_params(self, *, contract_id: str, run_id: str, tool: str,
                                  capability: str, args: Optional[Mapping[str, Any]],
                                  requested_scope: Tuple[str, ...],
                                  policy_kind: str) -> Tuple[Dict[str, Any], str]:
        """请求构造参数归一（redact + digest + scope 清洗）；返回 (kwargs, args_digest)。"""
        redacted = redact_args(dict(args or {}))
        digest = canonical_args_digest(redacted)
        scope = tuple(str(p).strip() for p in (requested_scope or ()) if str(p).strip())
        kwargs = dict(contract_id=contract_id, run_id=run_id, tool=tool, capability=capability,
                      args_redacted=redacted, args_digest=digest, requested_scope=scope,
                      policy_kind=policy_kind)
        return kwargs, digest

    def _identity_of(self, r: ApprovalRequest) -> Tuple[Any, ...]:
        """请求身份（Reviewer Patch）：不同操作不得复用同一审批。"""
        return (r.contract_id, r.contract_hash, r.run_id, r.tool, r.capability,
                r.requested_scope, r.risk_level, r.policy_kind, r.args_digest)

    def create_request(self, *, contract_id: str, run_id: str, tool: str, capability: str,
                       args: Optional[Mapping[str, Any]] = None, reason: str = "",
                       risk_level: Permission = Permission.L1_LOW_WRITE,
                       requested_scope: Tuple[str, ...] = (), expires_at: Optional[float] = None,
                       provenance: str = "executor",
                       policy_kind: str = "approval_required_each_step",
                       contract_hash: str = "") -> ApprovalRequest:
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
        base, _digest = self._normalize_request_params(
            contract_id=contract_id, run_id=run_id, tool=tool, capability=capability,
            args=args, requested_scope=requested_scope, policy_kind=policy_kind)
        request = ApprovalRequest(
            approval_id=f"apv_{uuid.uuid4().hex[:12]}",
            reason=reason, risk_level=risk_level,
            created_at=now, expires_at=exp, provenance=provenance,
            contract_hash=contract_hash, **base,
        )
        with self._lock:
            self._requests[request.approval_id] = _RequestRecord(request, ApprovalState.PENDING)
        self._log_event("approval.requested", approval_id=request.approval_id,
                        payload=request.to_audit_dict())
        return request

    def get_or_create_request(self, **kwargs: Any) -> Tuple[ApprovalRequest, bool]:
        """**原子** get-or-create（Reviewer Patch 5）：单锁内按完整身份查找，命中即复用，
        未命中才创建——并发同一步只能产生一个请求。参数与 :meth:`create_request` 相同；
        返回 (request, created)。"""
        base, _digest = self._normalize_request_params(
            contract_id=kwargs.get("contract_id", ""), run_id=kwargs.get("run_id", ""),
            tool=kwargs.get("tool", ""), capability=kwargs.get("capability", ""),
            args=kwargs.get("args"), requested_scope=kwargs.get("requested_scope") or (),
            policy_kind=kwargs.get("policy_kind", "approval_required_each_step"))
        risk_level = kwargs.get("risk_level", Permission.L1_LOW_WRITE)
        if not isinstance(risk_level, Permission):
            raise ApprovalStateError(
                f"risk_level 必须是 Permission（int enum），得到 {type(risk_level).__name__}")
        contract_hash = kwargs.get("contract_hash", "")
        now = self._clock()
        with self._lock:
            identity_probe = (base["contract_id"], contract_hash, base["run_id"],
                              base["tool"], base["capability"], base["requested_scope"],
                              risk_level, base["policy_kind"], base["args_digest"])
            for rec in self._requests.values():
                if self._identity_of(rec.request) == identity_probe:
                    return rec.request, False
            expires_at = kwargs.get("expires_at")
            if expires_at is None:
                expires_at = now + self._default_timeout
            if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
                raise ApprovalStateError(f"expires_at 必须是非 bool 数值，得到 {expires_at!r}")
            exp = float(expires_at)
            if not math.isfinite(exp) or exp <= now:
                raise ApprovalStateError(f"expires_at 必须是 > now 的有限时刻，得到 {expires_at!r}")
            if exp - now > self._max_timeout:
                raise ApprovalStateError(f"expires_at 超出来自审批窗口上限 {self._max_timeout}s")
            request = ApprovalRequest(
                approval_id=f"apv_{uuid.uuid4().hex[:12]}",
                reason=kwargs.get("reason", ""), risk_level=risk_level,
                created_at=now, expires_at=exp,
                provenance=kwargs.get("provenance", "executor"),
                contract_hash=contract_hash, **base,
            )
            self._requests[request.approval_id] = _RequestRecord(request, ApprovalState.PENDING)
        # 事件发射在锁外（create_request 同构；RLock 下锁内亦安全，此处缩短临界区）
        self._log_event("approval.requested", approval_id=request.approval_id,
                        payload=request.to_audit_dict())
        return request, True

    # -------------------------------------------------- producer 面：只读查询
    def matching_request(self, *, contract_id: str, run_id: str, tool: str,
                         requested_scope: Tuple[str, ...] = (),
                         contract_hash: Optional[str] = None,
                         capability: Optional[str] = None,
                         risk_level: Optional[Permission] = None,
                         policy_kind: Optional[str] = None,
                         args_digest: Optional[str] = None) -> Optional[ApprovalRequest]:
        """同一步的**最近**请求（任意终态）；无 → None。

        省略的身份维度（None）按通配处理（诊断用途）；gate 的复用路径走
        :meth:`get_or_create_request` 的**完整身份**原子匹配。
        """
        scope = tuple(str(p).strip() for p in (requested_scope or ()) if str(p).strip())
        with self._lock:
            found: Optional[ApprovalRequest] = None
            for rec in self._requests.values():
                r = rec.request
                if (r.contract_id == contract_id and r.run_id == run_id
                        and r.tool == tool and r.requested_scope == scope
                        and (contract_hash is None or r.contract_hash == contract_hash)
                        and (capability is None or r.capability == capability)
                        and (risk_level is None or r.risk_level == risk_level)
                        and (policy_kind is None or r.policy_kind == policy_kind)
                        and (args_digest is None or r.args_digest == args_digest)):
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
                reason: str = "",
                user_evidence: Union[str, VerifiedUserEvidence, None] = None
                ) -> ApprovalResolution:
        """决议（owner 线程）：exactly-once；重复 → DUPLICATE，冲突 → CONFLICT，
        迟于 timeout/cancel → LATE，未知 → UNKNOWN。

        **APPROVE_SESSION 必须携带经可信入口验证的 canonical USER 证据**
        （``user_evidence``：事件 id str → 过验证器，或 broker 铸造的
        VerifiedUserEvidence）；缺失/验证失败 → ApprovalStateError（决议不生效）。
        """
        if not isinstance(decision, ApprovalDecisionKind):
            raise ApprovalStateError(f"decision 必须是 ApprovalDecisionKind，得到 {decision!r}")
        self.require_owner("resolve")
        evidence: Optional[VerifiedUserEvidence] = None
        if decision == ApprovalDecisionKind.APPROVE_SESSION:
            evidence = self._require_user_evidence("approve_session 决议", user_evidence)
        elif user_evidence is not None:
            # 其他决议种类不接受随手附带证据（避免语义混淆）；要验证请显式调用
            raise ApprovalStateError(
                "user_evidence 只用于 approve_session 决议（approve_once/deny 为单步决议，"
                "不建立持久授权）")
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
                rec.detail = sanitize_text(reason)
                if evidence is not None:
                    rec.decided_by_user_event = evidence.user_event_id
                self._cv.notify_all()
                payload: Dict[str, Any] = {**rec.request.to_audit_dict(),
                                           "decision": decision.value,
                                           "decided_at": rec.decided_at,
                                           "detail": rec.detail}
                if evidence is not None:
                    payload["user_event_id"] = evidence.user_event_id
                self._log_event("approval.decided", approval_id=approval_id, payload=payload)
                return ApprovalResolution(True, ResolutionStatus.RESOLVED, approval_id,
                                          decision=decision, decided_at=rec.decided_at,
                                          detail=rec.detail)
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
        reason_s = sanitize_text(reason)
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
                rec.detail = reason_s
                rec.consumed_at = None   # 撤销后不可再消费
                self._cv.notify_all()
                self._log_event(
                    "approval.decided", approval_id=approval_id,
                    payload={**rec.request.to_audit_dict(),
                             "decision": ApprovalDecisionKind.REVOKED.value,
                             "decided_at": rec.decided_at, "detail": reason_s})
                return ApprovalResolution(True, ResolutionStatus.RESOLVED, approval_id,
                                          decision=ApprovalDecisionKind.REVOKED,
                                          decided_at=rec.decided_at, detail=reason_s)
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
        reason_s = sanitize_text(reason)
        with self._cv:
            rec = self._requests.get(approval_id)
            if rec is None:
                return ApprovalResolution(False, ResolutionStatus.UNKNOWN, approval_id,
                                          detail="approval_id 不存在")
            self._maybe_timeout_locked(rec)
            if rec.state == ApprovalState.PENDING:
                rec.state = ApprovalState.CANCELLED
                rec.decided_at = self._clock()
                rec.detail = reason_s
                self._cv.notify_all()
                self._log_event("approval.cancelled", approval_id=approval_id,
                                payload={**rec.request.to_audit_dict(), "detail": reason_s})
                return ApprovalResolution(True, ResolutionStatus.RESOLVED, approval_id,
                                          decision=None, decided_at=rec.decided_at, detail=reason_s)
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
        """approve_once 标记消费（producer 面；旧窄 API）。**推荐**工具边界经
        :meth:`consume_permit` 原子复核+消费（revocation TOCTOU 封闭）。"""
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
    def create_grant(self, *, user_evidence: Union[str, VerifiedUserEvidence],
                     capability: str, tool_pattern: str,
                     workspace_scope: WorkspaceScope, expiry: float, scope_note: str = "",
                     issued_at: Optional[float] = None) -> AuthorizationGrant:
        """创建会话/持久授权（owner 线程）。

        Reviewer Patch 收紧：

        - ``user_evidence`` **必须**是经可信入口验证器确认的 canonical USER 证据
          （事件 id str → broker 过验证器；或本 broker 铸造的 VerifiedUserEvidence）。
          格式正则不是真实性证明；未配置验证器 fail-closed；
        - 拒绝**未来签发**（``issued_at > now``）与**已过期新 grant**
          （``expiry <= now``）；
        - 有效窗口 ``issued_at <= now < expiry``（covering_grant / grant_state /
          consume_permit 一致执行）。
        """
        self.require_owner("create_grant")
        evidence = self._require_user_evidence("grant 创建", user_evidence)
        now = self._clock()
        if issued_at is None:
            issued = now
        else:
            if isinstance(issued_at, bool) or not isinstance(issued_at, (int, float)):
                raise ApprovalStateError(f"issued_at 必须是非 bool 数值或 None，得到 {issued_at!r}")
            issued = float(issued_at)
        if not math.isfinite(issued):
            raise ApprovalStateError(f"issued_at 必须有限，得到 {issued!r}")
        if issued > now:
            raise ApprovalStateError(
                f"拒绝未来签发的 grant：issued_at {issued} > now {now}")
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
            raise ApprovalStateError(f"expiry 必须是非 bool 数值，得到 {expiry!r}")
        exp = float(expiry)
        if not math.isfinite(exp):
            raise ApprovalStateError(f"expiry 必须有限（无永久 grant）: {expiry!r}")
        if exp <= now:
            raise ApprovalStateError(
                f"拒绝已过期的新 grant：expiry {exp} <= now {now}")
        if exp - issued > self._max_grant_duration:
            raise ApprovalStateError(
                f"grant 时长超过上限 {self._max_grant_duration}s（无永久 grant）")
        grant = AuthorizationGrant(
            grant_id=f"gr_{uuid.uuid4().hex[:12]}",
            user_event_id=evidence.user_event_id, capability=capability,
            tool_pattern=tool_pattern, workspace_scope=workspace_scope,
            issued_at=issued, expiry=exp, scope_note=scope_note,
        )
        with self._lock:
            self._grants[grant.grant_id] = _GrantRecord(grant, verified_by=evidence.verified_by)
        self._log_event("approval.grant_created", grant_id=grant.grant_id, payload=grant.to_dict())
        return grant

    def revoke_grant(self, grant_id: str, *, reason: str = "") -> AuthorizationGrant:
        """撤销授权（owner 线程）：记录 revoked_at；下一工具边界前生效。"""
        self.require_owner("revoke_grant")
        reason_s = sanitize_text(reason)
        with self._lock:
            rec = self._grants.get(grant_id)
            if rec is None:
                raise ApprovalStateError(f"unknown grant_id: {grant_id}")
            if rec.revoked_at is None:
                rec.revoked_at = self._clock()
                rec.revoked_reason = reason_s
                self._log_event("approval.grant_revoked", grant_id=grant_id,
                                payload={**rec.grant.to_dict(), "revoked_at": rec.revoked_at,
                                         "revoked_reason": reason_s})
            return rec.grant

    def _grant_active(self, rec: _GrantRecord, now: float) -> bool:
        """有效窗口 ``issued_at <= now < expiry`` 且未撤销。"""
        g = rec.grant
        return (rec.revoked_at is None
                and g.issued_at <= now < g.expiry)

    def covering_grant(self, *, tool: str, capability: str, paths: Tuple[str, ...] = (),
                       write_paths: Tuple[str, ...] = (),
                       now: Optional[float] = None) -> Optional[AuthorizationGrant]:
        """返回覆盖该 step 的**激活** grant（未撤销且 ``issued_at <= now < expiry``，
        latest 优先；write_paths 必须落入 grant write_roots）；无 → None。"""
        now = self._clock() if now is None else now
        paths = tuple(str(p) for p in (paths or ()))
        write_paths = tuple(str(p) for p in (write_paths or ()))
        best: Optional[AuthorizationGrant] = None
        with self._lock:
            for rec in self._grants.values():
                if not self._grant_active(rec, now):
                    continue
                g = rec.grant
                if not g.matches(tool, capability, paths, write_paths=write_paths):
                    continue
                if best is None or (g.issued_at, g.grant_id) > (best.issued_at, best.grant_id):
                    best = g
        return best

    def matching_grants(self, *, tool: str, capability: str,
                        paths: Tuple[str, ...] = (),
                        write_paths: Tuple[str, ...] = ()) -> List[AuthorizationGrant]:
        """所有**匹配**该 step 的 grant（含已过期/已撤销；供 gate 诊断 inactive 拒绝）。"""
        paths = tuple(str(p) for p in (paths or ()))
        write_paths = tuple(str(p) for p in (write_paths or ()))
        with self._lock:
            return [rec.grant for rec in self._grants.values()
                    if rec.grant.matches(tool, capability, paths, write_paths=write_paths)]

    def grant_state(self, grant_id: str, *, now: Optional[float] = None) -> Dict[str, Any]:
        now = self._clock() if now is None else now
        with self._lock:
            rec = self._grants.get(grant_id)
            if rec is None:
                raise ApprovalStateError(f"unknown grant_id: {grant_id}")
            g = rec.grant
            return {**g.to_dict(),
                    "active": self._grant_active(rec, now),
                    "revoked_at": rec.revoked_at,
                    "revoked_reason": rec.revoked_reason}

    def list_grants(self) -> List[AuthorizationGrant]:
        with self._lock:
            return [rec.grant for rec in self._grants.values()]

    # -------------------------------------------------- producer 面：ToolPermit
    def issue_permit(self, *, tool: str, capability: str, args_digest: str,
                     approval_id: str = "", grant_id: str = "",
                     ttl_seconds: Optional[float] = None) -> ToolPermit:
        """签发工具边界许可（gate ALLOW 时调用；producer 面任意线程）。

        TTL 有界（默认 ``permit_ttl_seconds``，上限 ``MAX_PERMIT_TTL_SECONDS``）——
        长窗口等于重新打开撤销 TOCTOU。
        """
        now = self._clock()
        ttl = self._permit_ttl if ttl_seconds is None else float(ttl_seconds)
        if (isinstance(ttl_seconds, bool) or not isinstance(ttl, (int, float))
                or not math.isfinite(float(ttl)) or ttl <= 0
                or ttl > MAX_PERMIT_TTL_SECONDS):
            raise ApprovalStateError(
                f"permit TTL 必须在 (0, {MAX_PERMIT_TTL_SECONDS}] 内，得到 {ttl_seconds!r}")
        permit = ToolPermit(
            permit_id=f"pmt_{uuid.uuid4().hex[:12]}",
            tool=tool, capability=capability, args_digest=args_digest,
            approval_id=approval_id, grant_id=grant_id,
            not_before=now, valid_until=now + ttl)
        with self._lock:
            self._permits[permit.permit_id] = _PermitRecord(permit)
        return permit

    def consume_permit(self, permit: ToolPermit, *,
                       tool: Optional[str] = None,
                       capability: Optional[str] = None,
                       args_digest: Optional[str] = None) -> PermitOutcome:
        """**真实工具边界**的原子消费/复核（消除 ALLOW → tool.run 的撤销 TOCTOU）。

        单锁内一次完成全部检查（任何失败 → ok=False，零 tool call）：

        - permit 必须是本 broker 签发（未知/伪造 → 拒绝）；
        - 可选身份复核：传入 tool/capability/args_digest 时必须与 permit 一致；
        - permit 未消费过且在有效窗口内（``not_before <= now < valid_until``）；
        - approval 绑定：APPROVE_ONCE → **此刻**原子标记消费（恰好一次）；
          APPROVE_SESSION → 仍处 APPROVED_SESSION（被撤销/未决 → 拒绝）；
        - grant 绑定：未撤销且 ``issued_at <= now < expiry``。
        """
        if not isinstance(permit, ToolPermit):
            raise ApprovalStateError(f"permit 必须是 ToolPermit，得到 {type(permit).__name__}")
        now = self._clock()
        with self._lock:
            rec = self._permits.get(permit.permit_id)
            if rec is None or rec.permit != permit:
                return PermitOutcome(False, "permit 未经本 broker 签发（伪造/未知凭证）",
                                     permit_id=permit.permit_id)
            if rec.consumed_at is not None:
                return PermitOutcome(False, "permit 已被消费（恰好一次）",
                                     permit_id=permit.permit_id, consumed_at=rec.consumed_at)
            if not (permit.not_before <= now < permit.valid_until):
                return PermitOutcome(False,
                                     f"permit 超出有效窗口（now={now}, "
                                     f"window=[{permit.not_before},{permit.valid_until})）",
                                     permit_id=permit.permit_id)
            if tool is not None and tool != permit.tool:
                return PermitOutcome(False, f"permit 身份复核失败（tool 不匹配）",
                                     permit_id=permit.permit_id)
            if capability is not None and capability != permit.capability:
                return PermitOutcome(False, "permit 身份复核失败（capability 不匹配）",
                                     permit_id=permit.permit_id)
            if args_digest is not None and args_digest != permit.args_digest:
                return PermitOutcome(False, "permit 身份复核失败（args_digest 不匹配："
                                     "被放行的操作 ≠ 即将执行的操作）",
                                     permit_id=permit.permit_id)
            if permit.approval_id:
                arec = self._requests.get(permit.approval_id)
                if arec is None:
                    return PermitOutcome(False, "permit 绑定的审批请求不存在",
                                         permit_id=permit.permit_id)
                if arec.state == ApprovalState.APPROVED_ONCE:
                    if arec.consumed_at is not None:
                        return PermitOutcome(False, "approve_once 已被消费（恰好一次）",
                                             permit_id=permit.permit_id,
                                             consumed_at=arec.consumed_at)
                    arec.consumed_at = now
                elif arec.state == ApprovalState.APPROVED_SESSION:
                    pass   # 会话决议仍生效（撤销/未决在下方统一拒绝）
                else:
                    return PermitOutcome(
                        False, f"审批决议已不再是放行态（{arec.state.value}）",
                        permit_id=permit.permit_id)
            if permit.grant_id:
                grec = self._grants.get(permit.grant_id)
                if grec is None or not self._grant_active(grec, now):
                    return PermitOutcome(False, "grant 已撤销/过期/未生效"
                                         "（issued_at <= now < expiry 不满足）",
                                         permit_id=permit.permit_id)
            rec.consumed_at = now
            return PermitOutcome(True, "permit 消费成功", permit_id=permit.permit_id,
                                 consumed_at=now)

    def permit_state(self, permit_id: str) -> Dict[str, Any]:
        with self._lock:
            rec = self._permits.get(permit_id)
            if rec is None:
                raise ApprovalStateError(f"unknown permit_id: {permit_id}")
            return {**rec.permit.to_dict(), "consumed_at": rec.consumed_at}

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
