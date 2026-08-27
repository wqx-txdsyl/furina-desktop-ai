"""Phase 16D — ApprovalBroker：一等异步审批通道的状态所有者。

位置：位于既有同步 PermissionManager **之上**。线程边界显式：

- **owner 只在构造时绑定**（``owner_thread_id``，由可信组合根传入）。decision 面
  （``resolve`` / ``cancel`` / ``revoke`` / ``create_grant`` / ``revoke_grant`` /
  ``request_user_evidence`` / ``create_permit_issuer``）只允许 owner 线程；
  backend/executor 线程拿到 broker 引用后**无法抢占或改绑 owner**；
- **producer 面（executor / agent / backend 线程，锁保护，任意线程可调）**：
  ``create_request`` / ``get_or_create_request`` / ``wait_for_resolution`` /
  ``state_of`` / ``consume`` / ``operation_digest`` / ``consume_permit``（消费侧）/
  各只读查询。

Reviewer Patch 3 关键收紧（本文件）：

1. **issuer/consumer API 重拆**：公开 ``issue_permit`` 与 ``GateSeal`` **已删除**
   ——不再以"broker/gate 普通属性中的 seal 对象"作为权限边界（Python 对象属性/
   ``_private`` 约定**不是**安全隔离，不作此声明）。permit 签发能力收拢到独立的
   :class:`PermitIssuer`：内部绑定唯一 ``gate_id`` + expected ``contract_id`` /
   ``content_hash``，**只能**由 :meth:`create_permit_issuer`（decision 面，
   owner 线程）创建并注入 Gate——producer 可见对象（broker/gate 公开 API）不
   携带任何 permit 签发能力；任何未经四层 Gate 判定的 permit 均无法进入本
   broker 台账、消费必拒（gate_id 注册表 + 台账 + 字段复核三重）；
2. **typed USER 证据上下文（exact-equality）**：``request_user_evidence`` 接受
   :class:`~furina.agent.approval.models.EvidenceContext`（严格不可变 typed
   context）；消费（approve_session / create_grant）从**真实操作记录**派生
   expected context，要求 stored context **完全相等**（禁止忽略 stored
   context），且 nonce **取出即销毁（一次性）+ 有界生命周期**
   （≤ ``MAX_EVIDENCE_NONCE_TTL_SECONDS``）——跨上下文/跨操作/重复/超窗重放
   一律拒绝；消费时刻仍**重新查询可信记录**；
3. **原子 permit 消费**：``consume_permit`` 在单锁内**先完成全部校验**（来源
   互斥、窗口、身份、approval/grant 状态），**最后单点提交** consumed 状态——
   任何失败不改变 approval/grant/permit 任何状态。

Reviewer Patch 2（保留）：操作摘要 ``operation_digest``（每 broker 随机密钥
HMAC-SHA256 over 严格 canonical 原始 args，不保存原文）；grant 有效窗口
``issued_at <= now < expiry``；事件载荷递归 sanitize + 冻结。

状态机：PENDING → APPROVED_ONCE / APPROVED_SESSION / DENIED / TIMED_OUT /
REVOKED / CANCELLED；终态不可逆。resolve exactly once（DUPLICATE / CONFLICT /
LATE / UNKNOWN 类型化）。
"""
from __future__ import annotations

import hmac
import hashlib
import math
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Union

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
    EvidenceContext,
    MAX_EVIDENCE_NONCE_TTL_SECONDS,
    MAX_PERMIT_TTL_SECONDS,
    PermitOutcome,
    ResolutionStatus,
    ToolPermit,
    USER_EVENT_ID_PATTERN,
    USER_EVIDENCE_NONCE_PATTERN,
    audit_args_digest,
    _canonical_json,
    _CONTRACT_HASH_PATTERN,
    redact_args,
    sanitize_text,
    sanitize_tree,
)

__all__ = ["ApprovalBroker", "PermitIssuer"]

UserEvidenceVerifier = Callable[[str, Mapping[str, Any]], Any]


@dataclass
class _RequestRecord:
    request: ApprovalRequest
    state: ApprovalState
    decision: Optional[ApprovalDecisionKind] = None
    decided_at: float = 0.0
    consumed_at: Optional[float] = None   # approve_once 消费时刻（exactly once）
    detail: str = ""
    #: APPROVE_SESSION 决议的 canonical USER 事件 id（消费时刻经可信入口重查确认）。
    decided_by_user_event: str = ""


@dataclass
class _GrantRecord:
    grant: AuthorizationGrant
    revoked_at: Optional[float] = None
    revoked_reason: str = ""
    #: 铸造该 grant 的可信验证器名（审计用；真实性靠消费时刻重查，不靠该字符串）。
    verified_by: str = ""


@dataclass
class _PermitRecord:
    permit: ToolPermit
    consumed_at: Optional[float] = None


class _PermitRegistrar:
    """broker 内部的 permit 入账能力（只随 :meth:`create_permit_issuer` 分发）。

    这是实现细节而非安全边界声明：Python 进程内不存在硬隔离，本仓库的威胁模型是
    "producer/runtime 只使用 broker/gate 的**公开 API**"。入账能力对象不进入任何
    producer 可见对象图（broker/gate 公开属性均不可达），且消费侧另有 gate_id
    注册表 + 台账 + 字段复核三重校验。
    """

    __slots__ = ("_broker",)

    def __init__(self, broker: "ApprovalBroker") -> None:
        self._broker = broker

    def register(self, permit: ToolPermit) -> None:
        broker = self._broker
        with broker._lock:
            broker._permits[permit.permit_id] = _PermitRecord(permit)


class PermitIssuer:
    """permit 签发器（issuer 半边；Patch 3）。

    - **内部绑定唯一 ``gate_id`` + expected ``contract_id`` / ``content_hash``**：
      ``issue()`` 不接受调用方自报的 gate/契约字段——签出的 permit 恒绑定构造期
      绑定值（本 issuer 所属 Gate 的身份与可信组合根核可的契约内容）；
    - **只能**经 :meth:`ApprovalBroker.create_permit_issuer`（decision 面，
      owner 线程）创建并由可信组合根注入 Gate；直接构造（无入账能力）一律
      :class:`ApprovalStateError`。producer 可见对象（broker/gate 公开 API）
      无任何 permit 签发能力；
    - ``issue()`` 是签发的唯一入口，仅供 Gate 在四层判定 ALLOW 后调用：
      授权来源互斥（approval/grant 不得同时）、operation digest 由 broker 密钥对
      **原始 args** 内部计算（不信任调用方自报）、TTL 有界
      （≤ ``MAX_PERMIT_TTL_SECONDS``）、非严格 JSON 域 fail-closed。
    """

    def __init__(self, *, registrar: _PermitRegistrar, gate_id: str,
                 expected_contract_id: str, expected_content_hash: str,
                 ttl_seconds: float) -> None:
        if not isinstance(registrar, _PermitRegistrar):
            raise ApprovalStateError(
                "PermitIssuer 只能经 ApprovalBroker.create_permit_issuer 创建"
                "（decision 面/owner 线程）——直接构造的 issuer 不具入账能力，拒绝")
        if not isinstance(gate_id, str) or not gate_id:
            raise ApprovalStateError(f"gate_id 必须是非空 str，得到 {gate_id!r}")
        if not isinstance(expected_contract_id, str) or not expected_contract_id.strip():
            raise ApprovalStateError(
                f"expected_contract_id 必须是非空 str，得到 {expected_contract_id!r}")
        if not isinstance(expected_content_hash, str) or len(expected_content_hash) != 64:
            raise ApprovalStateError(
                f"expected_content_hash 必须是 64 位 hex，得到 {expected_content_hash!r}")
        if (isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float))
                or not math.isfinite(float(ttl_seconds)) or ttl_seconds <= 0
                or ttl_seconds > MAX_PERMIT_TTL_SECONDS):
            raise ApprovalStateError(
                f"permit TTL 必须在 (0, {MAX_PERMIT_TTL_SECONDS}] 内，得到 {ttl_seconds!r}")
        self._registrar = registrar
        self._gate_id = gate_id
        self._expected_contract_id = expected_contract_id.strip()
        self._expected_content_hash = expected_content_hash
        self._ttl = float(ttl_seconds)

    @property
    def gate_id(self) -> str:
        return self._gate_id

    @property
    def expected_contract_id(self) -> str:
        return self._expected_contract_id

    @property
    def expected_content_hash(self) -> str:
        return self._expected_content_hash

    def issue(self, *, tool: str, capability: str, args: Optional[Mapping[str, Any]],
              run_id: str, approval_id: str = "", grant_id: str = "") -> ToolPermit:
        """签发工具边界许可（仅 Gate 的 ALLOW 路径调用）。

        gate/契约绑定来自**内部**（调用方不可指定）；approval_id 与 grant_id 互斥；
        operation digest 由 broker 密钥对原始 args 内部计算；TTL 有界。
        """
        for name, v in (("tool", tool), ("capability", capability), ("run_id", run_id)):
            if not isinstance(v, str):
                raise ApprovalStateError(f"issue() 的 {name} 必须是 str，得到 {v!r}")
        if approval_id and grant_id:
            raise ApprovalStateError(
                "permit 授权来源互斥（Patch 3）：approval 与 grant 不得同时存在——"
                "来源只能是 免审批（均空）/ approval / grant 三者之一")
        broker = self._registrar._broker
        op_digest = broker.operation_digest(args)
        now = broker.now()
        permit = ToolPermit(
            permit_id=f"pmt_{secrets.token_hex(6)}",
            gate_id=self._gate_id, tool=tool, capability=capability,
            operation_digest=op_digest,
            contract_id=self._expected_contract_id,
            contract_hash=self._expected_content_hash, run_id=run_id,
            approval_id=approval_id, grant_id=grant_id,
            not_before=now, valid_until=now + self._ttl)
        self._registrar.register(permit)
        return permit


class ApprovalBroker:
    """审批状态所有者：exactly-once 决议 / 超时 / 撤销 / 会话 grant / redacted 事件。

    构造参数（可信组合根所有）：

    - ``owner_thread_id``：owner 线程**只在构造时绑定**（backend 不得抢占；构造后
      无任何改绑 API）。None = decision 面永久锁定（fail-closed）；
    - ``user_evidence_verifier``：canonical USER 事件真实性验证器
      ``verifier(user_event_id, context) -> truthy``（可信入口，如 C6 台账查询）。
      **approve_session 与 grant 无它一律 fail-closed**；验证在**消费时刻**执行并
      绑定具体操作上下文。
    """

    def __init__(self, *, clock: Optional[Callable[[], float]] = None,
                 owner_thread_id: Optional[int] = None,
                 user_evidence_verifier: Optional[UserEvidenceVerifier] = None,
                 user_evidence_source: str = "trusted_entry",
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
        self._emit = emit
        #: 每 broker 随机密钥（Patch 2）：operation digest 的 HMAC 密钥，不落盘、不导出。
        self._op_key = secrets.token_bytes(32)
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._requests: Dict[str, _RequestRecord] = {}
        self._grants: Dict[str, _GrantRecord] = {}
        self._permits: Dict[str, _PermitRecord] = {}
        #: 经 create_permit_issuer 注册的 gate_id（Patch 3：消费侧复核 permit 的
        #: 签发者确为本 broker 决策面创建的 issuer，而非任意未注册 gate）。
        self._known_gate_ids: Dict[str, bool] = {}
        #: opaque USER 证据 nonce → (user_event_id, 预验证时的 typed 上下文, created_at)。
        self._evidence_nonces: Dict[str, Tuple[str, EvidenceContext, float]] = {}
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

    # -------------------------------------------------- 操作摘要（Patch 2）
    def operation_digest(self, args: Optional[Mapping[str, Any]]) -> str:
        """**operation digest**：每 broker 随机密钥的 HMAC-SHA256 over 严格 canonical
        **原始** args（``_canonical_json``，无 repr 兜底，非 JSON 类型 fail-closed）。

        - 不保存原文、不可逆、不可导出（密钥只在本 broker 内存中）；
        - 不同敏感值 ⇒ 不同摘要 ⇒ 不同操作身份（audit digest 脱敏后碰撞，不能作身份）。
        """
        raw = _canonical_json(dict(args or {}))
        return hmac.new(self._op_key, raw.encode("utf-8"), hashlib.sha256).hexdigest()

    # -------------------------------------------------- canonical USER 证据（Patch 3：typed context）
    def request_user_evidence(self, user_event_id: str, *,
                              context: EvidenceContext) -> str:
        """决策入口（owner 线程）对指定**类型化操作上下文**预验证 canonical USER
        事件，返回内部 opaque nonce（``uev_*``）。

        - ``context`` 必须是 :class:`EvidenceContext`（严格不可变 typed context）：
          grant 侧绑定 contract_id/hash、capability、tool_pattern、workspace、
          issued_at、expiry、scope_note、decision；approve_session 侧绑定完整
          ApprovalRequest 身份；
        - nonce 生命周期（Patch 3）：**取出即销毁（一次性）** + 预验证后
          ``MAX_EVIDENCE_NONCE_TTL_SECONDS`` 内有效——消费时 stored context 与
          消费时刻派生的 expected context 必须**完全相等**，且仍会**重新查询可信
          记录**；跨上下文/跨操作/重复/超窗重放一律拒绝。
        """
        self.require_owner("user_evidence 预验证")
        if not isinstance(user_event_id, str) or not USER_EVENT_ID_PATTERN.match(user_event_id):
            raise ApprovalStateError(
                f"USER 事件 id 必须匹配 lev_<ms>_<hex>，得到 {user_event_id!r}")
        if not isinstance(context, EvidenceContext):
            raise ApprovalStateError(
                f"context 必须是 EvidenceContext（严格 typed 操作上下文，Patch 3），"
                f"得到 {type(context).__name__}")
        self._verify_user_event(user_event_id, context.to_payload())
        nonce = f"uev_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._evidence_nonces[nonce] = (user_event_id, context, self._clock())
        return nonce

    def _verify_user_event(self, user_event_id: str, context_payload: Mapping[str, Any]) -> None:
        """**消费时刻**重新查询可信记录：验证器必须确认该 USER 事件真实存在 **且**
        属于当前操作上下文（typed EvidenceContext 的 payload 投影）。格式正则只是
        必要条件。"""
        if self._verifier is None:
            raise ApprovalStateError(
                "canonical USER 证据验证器未配置（user_evidence_verifier=None）——"
                "approve_session / grant 一律 fail-closed：格式正则不是真实性证明")
        try:
            authentic = self._verifier(user_event_id, dict(context_payload or {}))
        except Exception as exc:
            raise ApprovalStateError(
                f"USER 证据验证器异常（fail-closed，不泄漏细节）: {type(exc).__name__}") from exc
        if not authentic:
            raise ApprovalStateError(
                f"USER 事件 {sanitize_text(user_event_id, max_len=120)} 未通过可信入口在"
                f"当前操作上下文下的重查（事件不存在或与操作无关：格式合法 ≠ 真实性，"
                "backend/LLM 无法伪造验证器确认）")

    def _consume_user_evidence(self, what: str,
                               user_evidence: Union[str, Any, None],
                               *, expected: EvidenceContext) -> str:
        """消费入口统一证据校验（Patch 3：typed exact-equality + 一次性 nonce）。

        - None / 非 str（含手工构造的 VerifiedUserEvidence）→ 拒绝；
        - ``uev_*`` nonce：**单锁内原子取出（取出即销毁，一次性）**；必须在
          ``MAX_EVIDENCE_NONCE_TTL_SECONDS`` 内；stored context 必须与 expected
          **完全相等**（禁止忽略 stored context——任何一维变化即拒绝）；随后
          **重新查询**可信记录绑定当前上下文；
        - 原始 event id：消费时刻直接重新查询可信记录（绑定 expected payload）。
        """
        if user_evidence is None:
            raise ApprovalStateError(
                f"'{what}' 必须携带 canonical USER 证据（user_evidence）："
                "经可信入口在操作上下文下验证的存在性证明，不接受任何缺省/推断")
        if not isinstance(user_evidence, str):
            raise ApprovalStateError(
                f"'{what}' 的 user_evidence 只接受本 broker 签发的 opaque nonce（uev_*）"
                f"或原始事件 id str，得到 {type(user_evidence).__name__}——手工构造的"
                "VerifiedUserEvidence 一律拒绝（不得公开自铸）")
        if USER_EVIDENCE_NONCE_PATTERN.match(user_evidence):
            now = self._clock()
            with self._lock:
                # 原子取出：此后该 nonce 不再可用（一次性；验证失败亦作废，fail-closed）
                stored = self._evidence_nonces.pop(user_evidence, None)
            if stored is None:
                raise ApprovalStateError(
                    f"'{what}' 的 user_evidence nonce 非本 broker 签发或已被消费"
                    "（跨 broker/伪造/重复使用，拒绝）")
            ev_id, stored_ctx, created_at = stored
            if now < created_at or now - created_at > MAX_EVIDENCE_NONCE_TTL_SECONDS:
                raise ApprovalStateError(
                    f"'{what}' 的 user_evidence nonce 超出有界生命周期"
                    f"（{MAX_EVIDENCE_NONCE_TTL_SECONDS}s，now-created="
                    f"{now - created_at:.1f}s）——超窗重放拒绝")
            if stored_ctx != expected:
                raise ApprovalStateError(
                    f"'{what}' 的 user_evidence nonce 与当前操作上下文不完全一致"
                    "（stored context ≠ 消费时刻派生的 expected context：capability/"
                    "expiry/workspace/scope_note/操作身份任一变化即拒绝——跨上下文"
                    "重放封死）")
            self._verify_user_event(ev_id, expected.to_payload())
            return ev_id
        if not USER_EVENT_ID_PATTERN.match(user_evidence):
            raise ApprovalStateError(
                f"'{what}' 的 user_evidence 必须匹配 lev_<ms>_<hex> 事件 id，得到 {user_evidence!r}")
        # 原始 event id：消费时直接重新查询可信记录（绑定 expected 上下文）
        self._verify_user_event(user_evidence, expected.to_payload())
        return user_evidence

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
                                  policy_kind: str) -> Tuple[Dict[str, Any], str, str]:
        """请求构造参数归一（redact + audit digest + operation digest）；返回
        (base_kwargs, audit_digest, op_digest)。operation digest 由本 broker 密钥
        现场对**原始 args** 计算（单一权威，不信任调用方自报）。"""
        redacted = redact_args(dict(args or {}))
        audit = audit_args_digest(redacted)
        op = self.operation_digest(args)
        scope = tuple(str(p).strip() for p in (requested_scope or ()) if str(p).strip())
        kwargs = dict(contract_id=contract_id, run_id=run_id, tool=tool, capability=capability,
                      args_redacted=redacted, audit_args_digest=audit,
                      operation_digest=op, requested_scope=scope, policy_kind=policy_kind)
        return kwargs, audit, op

    def _identity_of(self, r: ApprovalRequest) -> Tuple[Any, ...]:
        """请求身份（Reviewer Patch 1/2）：不同操作不得复用同一审批——
        操作身份含 operation_digest（HMAC over 原始 args，敏感值不同即不同）。"""
        return (r.contract_id, r.contract_hash, r.run_id, r.tool, r.capability,
                r.requested_scope, r.risk_level, r.policy_kind, r.operation_digest)

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
        base, _audit, _op = self._normalize_request_params(
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

    def get_or_create_request(self, *, contract_id: str, run_id: str, tool: str,
                              capability: str, args: Optional[Mapping[str, Any]] = None,
                              reason: str = "",
                              risk_level: Permission = Permission.L1_LOW_WRITE,
                              requested_scope: Tuple[str, ...] = (),
                              expires_at: Optional[float] = None,
                              provenance: str = "executor",
                              policy_kind: str = "approval_required_each_step",
                              contract_hash: str = "") -> Tuple[ApprovalRequest, bool]:
        """**原子** get-or-create（Reviewer Patch 1）：单锁内按完整身份
        （含 operation_digest）查找，命中即复用，未命中才创建——并发同一步只能产生
        一个请求。返回 (request, created)。"""
        base, _audit, op = self._normalize_request_params(
            contract_id=contract_id, run_id=run_id, tool=tool, capability=capability,
            args=args, requested_scope=requested_scope, policy_kind=policy_kind)
        if not isinstance(risk_level, Permission):
            raise ApprovalStateError(
                f"risk_level 必须是 Permission（int enum），得到 {type(risk_level).__name__}")
        now = self._clock()
        with self._lock:
            identity_probe = (base["contract_id"], contract_hash, base["run_id"],
                              base["tool"], base["capability"], base["requested_scope"],
                              risk_level, base["policy_kind"], op)
            for rec in self._requests.values():
                if self._identity_of(rec.request) == identity_probe:
                    return rec.request, False
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
                reason=reason, risk_level=risk_level,
                created_at=now, expires_at=exp, provenance=provenance,
                contract_hash=contract_hash, **base,
            )
            self._requests[request.approval_id] = _RequestRecord(request, ApprovalState.PENDING)
        # 事件发射在锁外（create_request 同构）
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
                         operation_digest: Optional[str] = None) -> Optional[ApprovalRequest]:
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
                        and (operation_digest is None or r.operation_digest == operation_digest)):
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
                user_evidence: Union[str, Any, None] = None
                ) -> ApprovalResolution:
        """决议（owner 线程）：exactly-once；重复 → DUPLICATE，冲突 → CONFLICT，
        迟于 timeout/cancel → LATE，未知 → UNKNOWN。

        **APPROVE_SESSION 必须携带 canonical USER 证据**（本 broker opaque nonce 或
        原始 event id），且绑定**完整 ApprovalRequest 身份**（Patch 3：typed
        :class:`EvidenceContext`——approval_id/contract_id/contract_hash/run_id/
        tool/capability/requested_scope/risk_level/policy_kind/operation_digest），
        消费时刻经可信入口重新查询——缺失/验证失败/上下文不完全一致 →
        ApprovalStateError（决议不生效）。
        """
        if not isinstance(decision, ApprovalDecisionKind):
            raise ApprovalStateError(f"decision 必须是 ApprovalDecisionKind，得到 {decision!r}")
        self.require_owner("resolve")
        evidence_id: Optional[str] = None
        if decision == ApprovalDecisionKind.APPROVE_SESSION:
            with self._cv:
                rec = self._requests.get(approval_id)
                if rec is None:
                    return ApprovalResolution(False, ResolutionStatus.UNKNOWN, approval_id,
                                              decision=decision, detail="approval_id 不存在")
                self._maybe_timeout_locked(rec)
                # expected context 从请求记录派生（完整审批身份；不信任调用方自报）
                r = rec.request
                expected = EvidenceContext(
                    decision="approve_session", approval_id=approval_id,
                    contract_id=r.contract_id, contract_hash=r.contract_hash,
                    run_id=r.run_id, tool=r.tool, capability=r.capability,
                    requested_scope=r.requested_scope, risk_level=r.risk_level.name,
                    policy_kind=r.policy_kind, operation_digest=r.operation_digest)
            evidence_id = self._consume_user_evidence("approve_session 决议", user_evidence,
                                                      expected=expected)
        elif user_evidence is not None:
            # 其他决议种类不接受随手附带证据（避免语义混淆）
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
                if evidence_id is not None:
                    rec.decided_by_user_event = evidence_id
                self._cv.notify_all()
                payload: Dict[str, Any] = {**rec.request.to_audit_dict(),
                                           "decision": decision.value,
                                           "decided_at": rec.decided_at,
                                           "detail": rec.detail}
                if evidence_id is not None:
                    payload["user_event_id"] = evidence_id
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
        """approve_once 标记消费（producer 面）。**工具边界必须**经
        :meth:`consume_permit` 原子复核+消费（撤销 TOCTOU 封闭；本方法只做标记，
        不产生任何 permit）。"""
        now = self._clock()
        with self._lock:
            rec = self._requests.get(approval_id)
            if rec is None or rec.state != ApprovalState.APPROVED_ONCE or rec.consumed_at is not None:
                return False
            rec.consumed_at = now
            return True

    # -------------------------------------------------- permit 签发（Patch 3：issuer/consumer 拆分）
    def create_permit_issuer(self, *, expected_contract_id: str,
                             expected_content_hash: str,
                             permit_ttl_seconds: float = 30.0) -> PermitIssuer:
        """创建 permit 签发器（**decision 面：仅 owner 线程**；Patch 3）。

        - 公开 ``issue_permit`` / ``GateSeal`` 已删除：broker 的 producer 面**不再
          携带任何 permit 签发能力**——签发能力只存在于返回的
          :class:`PermitIssuer` 对象中，由可信组合根注入 Gate；
        - issuer **内部绑定**唯一 ``gate_id`` + expected ``contract_id`` /
          ``content_hash``（Gate 的契约绑定同一来源）；签出的 permit 恒绑定这些
          值，调用方不可自报 gate/契约字段；
        - producer/runtime 线程调用 → ApprovalStateError（非 owner 线程不得创建
          签发能力；有否证测试锁定）。
        """
        self.require_owner("create_permit_issuer")
        if not isinstance(expected_contract_id, str) or not expected_contract_id.strip():
            raise ApprovalStateError(
                f"expected_contract_id 必须是非空 str，得到 {expected_contract_id!r}")
        if not isinstance(expected_content_hash, str) or len(expected_content_hash) != 64:
            raise ApprovalStateError(
                f"expected_content_hash 必须是 64 位 hex，得到 {expected_content_hash!r}")
        if (isinstance(permit_ttl_seconds, bool)
                or not isinstance(permit_ttl_seconds, (int, float))
                or not math.isfinite(float(permit_ttl_seconds)) or permit_ttl_seconds <= 0
                or permit_ttl_seconds > MAX_PERMIT_TTL_SECONDS):
            raise ApprovalStateError(
                f"permit_ttl_seconds 必须在 (0, {MAX_PERMIT_TTL_SECONDS}] 内，"
                f"得到 {permit_ttl_seconds!r}")
        gate_id = f"gate_{secrets.token_hex(8)}"
        issuer = PermitIssuer(registrar=_PermitRegistrar(self), gate_id=gate_id,
                              expected_contract_id=expected_contract_id,
                              expected_content_hash=expected_content_hash,
                              ttl_seconds=permit_ttl_seconds)
        with self._lock:
            self._known_gate_ids[gate_id] = True
        return issuer

    def consume_permit(self, permit: ToolPermit, *, tool: str, capability: str,
                       args: Mapping[str, Any]) -> PermitOutcome:
        """**真实工具边界**的原子消费/复核（消除 ALLOW → tool.run 的撤销 TOCTOU）。

        - ``tool`` / ``capability`` / ``args`` **必填**（真实操作身份）；本方法用
          broker 密钥对**原始 args** 内部重新计算 operation digest 与 permit 比对
          ——**禁止调用方传 permit 自身字段完成自证**；
        - **单锁内先完成全部校验，最后单点提交**（Patch 3）：

          1. permit 必须在本 broker 台账（伪造/篡改任意字段拒绝）且 gate_id 属于
             本 broker 决策面注册的 issuer；
          2. 未消费且在有效窗口；tool/capability/operation digest 逐项一致；
          3. **授权来源互斥**：approval_id 与 grant_id 同时非空 → 拒绝；
          4. approval 绑定：APPROVE_ONCE → 仍待消费（消费标记在提交点原子写入）、
             APPROVE_SESSION → 仍处 APPROVED_SESSION（撤销/超时/拒绝一律失败）；
             grant 绑定：未撤销且 ``issued_at <= now < expiry`` 且 grant 的
             contract_id/contract_hash 与 permit 完全一致（Contract A 的 grant
             不得放行 Contract B 的操作）；
          5. 全部通过 → **唯一提交点**：approve_once 标记 + permit consumed 一次
             写入。任何失败 → ok=False 且**不改变** approval/grant/permit 任何
             状态，零 tool call。
        """
        if not isinstance(permit, ToolPermit):
            raise ApprovalStateError(f"permit 必须是 ToolPermit，得到 {type(permit).__name__}")
        if not isinstance(tool, str) or not isinstance(capability, str):
            raise ApprovalStateError("consume_permit 必须携带真实 tool/capability（str）")
        if not isinstance(args, Mapping):
            raise ApprovalStateError("consume_permit 必须携带真实原始 args（Mapping）")
        try:
            op_digest = self.operation_digest(dict(args))
        except ApprovalStateError as exc:
            return PermitOutcome(False, f"操作参数不可 canonical（fail-closed）: {exc}",
                                 permit_id=permit.permit_id)
        now = self._clock()
        with self._lock:
            rec = self._permits.get(permit.permit_id)
            if rec is None or rec.permit != permit:
                return PermitOutcome(False, "permit 非本 broker 签发或字段已被篡改"
                                     "（伪造/换 id/改字段/改时间窗一律拒绝）",
                                     permit_id=permit.permit_id)
            if not self._known_gate_ids.get(permit.gate_id):
                return PermitOutcome(False, "permit 的签发 gate 未在本 broker 决策面注册"
                                     "（未经 create_permit_issuer 创建的 issuer，拒绝）",
                                     permit_id=permit.permit_id)
            if rec.consumed_at is not None:
                return PermitOutcome(False, "permit 已被消费（恰好一次）",
                                     permit_id=permit.permit_id, consumed_at=rec.consumed_at)
            if not (permit.not_before <= now < permit.valid_until):
                return PermitOutcome(False,
                                     f"permit 超出有效窗口（now={now}, "
                                     f"window=[{permit.not_before},{permit.valid_until})）",
                                     permit_id=permit.permit_id)
            if tool != permit.tool:
                return PermitOutcome(False, "permit 身份复核失败（tool 不匹配）",
                                     permit_id=permit.permit_id)
            if capability != permit.capability:
                return PermitOutcome(False, "permit 身份复核失败（capability 不匹配）",
                                     permit_id=permit.permit_id)
            if op_digest != permit.operation_digest:
                return PermitOutcome(False, "permit 身份复核失败（operation digest 不匹配："
                                     "被放行的操作 ≠ 即将执行的操作）", permit_id=permit.permit_id)
            if permit.approval_id and permit.grant_id:
                return PermitOutcome(False, "permit 授权来源互斥违规（approval+grant 双来源）",
                                     permit_id=permit.permit_id)
            # ---- 来源校验（互斥：免审批=均空 / approval / grant）----
            approval_rec: Optional[_RequestRecord] = None
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
                    approval_rec = arec
                elif arec.state != ApprovalState.APPROVED_SESSION:
                    return PermitOutcome(
                        False, f"审批决议已不再是放行态（{arec.state.value}）",
                        permit_id=permit.permit_id)
            elif permit.grant_id:
                grec = self._grants.get(permit.grant_id)
                if grec is None or not self._grant_active(grec, now):
                    return PermitOutcome(False, "grant 已撤销/过期/未生效"
                                         "（issued_at <= now < expiry 不满足）",
                                         permit_id=permit.permit_id)
                g = grec.grant
                if (g.contract_id != permit.contract_id
                        or g.contract_hash != permit.contract_hash):
                    return PermitOutcome(False, "grant 契约绑定与 permit 不一致"
                                         "（Contract A 的 grant 不得放行 Contract B 的操作）",
                                         permit_id=permit.permit_id)
            # ---- 唯一提交点：全部校验通过，一次性写入 consumed 状态 ----
            if approval_rec is not None:
                approval_rec.consumed_at = now
            rec.consumed_at = now
            return PermitOutcome(True, "permit 消费成功", permit_id=permit.permit_id,
                                 consumed_at=now)

    def permit_state(self, permit_id: str) -> Dict[str, Any]:
        with self._lock:
            rec = self._permits.get(permit_id)
            if rec is None:
                raise ApprovalStateError(f"unknown permit_id: {permit_id}")
            return {**rec.permit.to_dict(), "consumed_at": rec.consumed_at}

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
    def create_grant(self, *, user_evidence: Union[str, Any],
                     contract_id: str, contract_hash: str,
                     capability: str, tool_pattern: str,
                     workspace_scope: WorkspaceScope, expiry: float, scope_note: str = "",
                     issued_at: Optional[float] = None) -> AuthorizationGrant:
        """创建会话/持久授权（owner 线程）。

        Reviewer Patch 3 收紧：

        - **grant 必须绑定 contract_id + contract_hash（必填）**：create/list/
          match/cover/permit 全链携带；Contract A 的 grant 绝不覆盖 Contract B
          （即使 tool/capability/workspace 相同——covering/matching 按契约精确过滤、
          consume_permit 复核 grant 与 permit 的契约绑定一致）；
        - ``user_evidence`` 必须与**完整 grant 上下文**（typed
          :class:`EvidenceContext`：decision/contract_id/hash/capability/
          tool_pattern/workspace/issued_at/expiry/scope_note）**完全相等**——
          nonce 跨上下文/重复/超窗一律拒绝，消费时刻重查可信记录；手工构造
          VerifiedUserEvidence / 跨 broker nonce / 无关真实事件 → 拒绝；未配置
          验证器 fail-closed；
        - 拒绝**未来签发**（``issued_at > now``）与**已过期新 grant**
          （``expiry <= now``）；有效窗口 ``issued_at <= now < expiry``。
        """
        self.require_owner("create_grant")
        now = self._clock()
        # 契约绑定先于证据消费（Patch 3：格式非法不烧 nonce）
        if not isinstance(contract_id, str) or not contract_id.strip():
            raise ApprovalStateError(
                f"contract_id 必须是非空 str（grant 必须绑定契约，Patch 3），得到 {contract_id!r}")
        if not isinstance(contract_hash, str) or not _CONTRACT_HASH_PATTERN.match(contract_hash):
            raise ApprovalStateError(
                f"contract_hash 必须是 64 位小写 hex（grant 必须绑定契约内容，Patch 3），"
                f"得到 {contract_hash!r}")
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
        expected = EvidenceContext(
            decision="grant", contract_id=contract_id, contract_hash=contract_hash,
            capability=capability, tool_pattern=tool_pattern,
            workspace_read_roots=tuple(workspace_scope.read_roots),
            workspace_write_roots=tuple(workspace_scope.write_roots),
            issued_at=issued, expiry=exp, scope_note=scope_note)
        evidence_id = self._consume_user_evidence("grant 创建", user_evidence, expected=expected)
        grant = AuthorizationGrant(
            grant_id=f"gr_{uuid.uuid4().hex[:12]}",
            user_event_id=evidence_id, contract_id=contract_id,
            contract_hash=contract_hash, capability=capability,
            tool_pattern=tool_pattern, workspace_scope=workspace_scope,
            issued_at=issued, expiry=exp, scope_note=scope_note,
        )
        with self._lock:
            self._grants[grant.grant_id] = _GrantRecord(grant, verified_by=self._verifier_name)
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

    def is_grant_active(self, grant_id: str, *, now: Optional[float] = None) -> bool:
        """指定 grant 是否激活（Gate 消费 permit 时复核用）。"""
        now = self._clock() if now is None else now
        with self._lock:
            rec = self._grants.get(grant_id)
            if rec is None:
                return False
            return self._grant_active(rec, now)

    def covering_grant(self, *, tool: str, capability: str,
                       contract_id: str, contract_hash: str,
                       paths: Tuple[str, ...] = (),
                       write_paths: Tuple[str, ...] = (),
                       now: Optional[float] = None) -> Optional[AuthorizationGrant]:
        """返回覆盖该 step 的**激活** grant（未撤销且 ``issued_at <= now < expiry``，
        latest 优先；write_paths 必须落入 grant write_roots）。

        Patch 3：**契约精确过滤**——grant 的 contract_id 与 contract_hash 必须与
        当前 step 的契约**完全一致**；Contract A 的 grant 绝不覆盖 Contract B
        （即使 tool/capability/workspace 相同），同 id 不同 hash 的换约内容同样
        不覆盖。无 → None。"""
        now = self._clock() if now is None else now
        paths = tuple(str(p) for p in (paths or ()))
        write_paths = tuple(str(p) for p in (write_paths or ()))
        best: Optional[AuthorizationGrant] = None
        with self._lock:
            for rec in self._grants.values():
                if not self._grant_active(rec, now):
                    continue
                g = rec.grant
                if g.contract_id != contract_id or g.contract_hash != contract_hash:
                    continue
                if not g.matches(tool, capability, paths, write_paths=write_paths):
                    continue
                if best is None or (g.issued_at, g.grant_id) > (best.issued_at, best.grant_id):
                    best = g
        return best

    def matching_grants(self, *, tool: str, capability: str,
                        contract_id: str, contract_hash: str,
                        paths: Tuple[str, ...] = (),
                        write_paths: Tuple[str, ...] = ()) -> List[AuthorizationGrant]:
        """所有**匹配**该 step 的 grant（同契约绑定；含已过期/已撤销；供 gate 诊断
        inactive 拒绝）。Patch 3：契约精确过滤——跨契约 grant 不参与匹配。"""
        paths = tuple(str(p) for p in (paths or ()))
        write_paths = tuple(str(p) for p in (write_paths or ()))
        with self._lock:
            return [rec.grant for rec in self._grants.values()
                    if rec.grant.contract_id == contract_id
                    and rec.grant.contract_hash == contract_hash
                    and rec.grant.matches(tool, capability, paths, write_paths=write_paths)]

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
