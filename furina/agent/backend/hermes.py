"""Phase 16C — Hermes API Backend Adapter（本机 Hermes API Server Runs 面的唯一执行通道）。

权威依据（本机实测 + 源码，Hermes Agent v0.20.6 / upstream 4e7eb399）：

- ``GET  /health``                       → ``{"status":"ok","platform":"hermes-agent","version":…}``（无认证）；
- ``GET  /v1/capabilities``              → Bearer 认证；``model`` 即 active profile 身份
  （``_resolve_model_name``：非 default/custom profile 名进入广告 model —— 每个 profile
  广告不同 model）；``features.run_submission / run_status / run_events_sse / run_stop /
  run_steer / run_approval_response`` 布尔广告；
- ``GET  /v1/toolsets``                  → Bearer 认证；``{"object":"list","platform":
  "api_server","data":[{name,label,description,enabled,configured,tools:[…]}]}`` ——
  api_server 平台**实际暴露给 run agent 的工具面**（enabled + 解析后的具体工具名），
  这是 dedicated profile/toolset 边界的权威服务器端证据（源码 docstring 原文：
  "Returns the toolset surface the api_server platform actually exposes to its agent"）；
- ``POST /v1/runs``                      → ``{"input": …}`` → **202** ``{"run_id":"run_<hex>","status":"started"}``
  （请求体无任何 toolset/profile 限定参数 → run 侧工具面由服务器 profile 决定，
  适配器侧以 probe 快照 + 审批面封闭映射双向封闭）；
- ``GET  /v1/runs/{id}``                 → ``{"object":"hermes.run","run_id","status","created_at",
  "updated_at",…}``；status ∈ queued/running/waiting_for_approval/stopping/completed/cancelled/failed；
- ``GET  /v1/runs/{id}/events``          → SSE：``data: {json}\\n\\n`` 帧 + ``: keepalive`` 心跳 +
  ``: stream closed`` 关闭哨兵；事件词表 run.completed/run.failed/run.cancelled/
  approval.request/approval.responded/tool.started/tool.completed/message.delta/
  reasoning.available/run.steered；
- ``POST /v1/runs/{id}/approval``        → ``{"choice":"once|session|always|deny"}`` → 200
  ``{"object":"hermes.run.approval_response",…}`` / 400 invalid_approval_choice /
  409 approval_not_pending / 404 run_not_found；
- ``POST /v1/runs/{id}/stop``            → 200 ``{"run_id","status":"stopping"}`` /
  404 run_not_found —— **stop 成功不是 CANCELLED**；权威终态只来自 status 轮询 /
  SSE run.cancelled；
- 不存在 run_id 上四个 runs 面端点（status/events GET + approval/stop POST）全部
  **404 run_not_found 且零副作用**（源码：approval/stop 在状态查索后、任何状态变更前
  返回 404）→ probe 的无副作用主动握手面。

安全边界（任务书 §5 + 16C Reviewer Patch 1 约束）：

- **默认仅 loopback**：base_url 必须是 ``http://127.0.0.1|localhost|::1[:port]``；userinfo
  （URL 内凭证）、query、fragment、非 http scheme、非空路径、非法端口一律构造期
  HermesConfigurationError；
- **follow_redirects=False**：任何 3xx 视为协议错误（非本地 redirect fail-closed）；
- API key 只经构造注入、只进 ``Authorization: Bearer`` 头；绝不入契约、绝不入日志/错误文本
  （错误文本**先按精确 key 值脱敏、再做秘密形态脱敏**——服务端裸回显 key 也不得进入异常）；
- 端点封闭集（8 个 method+path）：本模块只请求上列端点；run_id 进入 URL 前过词法校验
  （防路径注入）；
- **不发送 Persona/SOUL/Memory**：submit 只携带 ``canonical_user_request`` 文本；不用
  自然语言 instructions 假装权限隔离（``instructions`` 字段绝不发送）；
- **submit 只接受完整 WorkContract**：16A ``WorkContract.from_dict`` exact-schema +
  content_hash 复核（缺字段/未知字段/篡改 hash/自签扩权 submit 前拒绝）；契约
  allowed_capabilities 必须与本 backend 不可变 capability envelope **封闭相等**（不只是子集）；
- **profile identity 绑定**：probe 把 ``/v1/capabilities.model`` 与构造期
  ``expected_profile_identity`` 精确比对，缺失/不一致 → unhealthy；
- **completed ≠ VERIFIED**：Hermes 终态一律映射 16B ``run.completed`` 等 BackendEvent，
  16E reducer 折算 ``BACKEND_DONE_UNVERIFIED``；本模块不产生任何验证语义；
- **断线零重复 submit**：submit 幂等账本按 contract_id 原子 reservation（同 id 同 hash
  幂等返回既有 handle，同 id 异 hash 类型化冲突；POST 已发出而结果不确定 → reservation
  中毒，绝不自动重提）；events/reconcile 路径零 POST /v1/runs；
- **approval 只走 16D 公开接口**：SSE approval.request 的 tool 必须映射到构造期
  tool→capability 封闭映射、且该 capability ∈ 契约 allowed_capabilities，否则
  **自动 deny（fail-closed，不向用户制造 16D 审批请求）**；映射成功经
  ``broker.get_or_create_request`` 原子 get-or-create（完整身份含 operation_digest——
  同 tool 同 preview 不同 command ⇒ 不同 approval）；决议只消费
  ``broker.wait_for_resolution`` 的**真实 Furina 决议**；转发只允许 ``once``/``deny``——
  **绝不发送 always/session**（不放宽 16D 决议）；同一 approval 只向 Hermes 转发一次
  （并发 resolve 单请求获胜；第二次调用 typed no-op）；``once`` 转发成功后真实消费 16D
  approval；``resolved==1`` 精确才声明成功；409 仅在错误码精确为
  ``approval_not_pending`` 时视为 no-op；
- ``hermes proxy`` 不注册、CLI 仅诊断、webhook 不作为结果通道：本模块没有任何对应代码路径。

全部 buffer 有硬上限（SSE 行 256 KiB、单事件 payload 有界、JSON body 有界、
run/contract/approval 账本硬容量满则 fail-closed 不淘汰）；资源显式清理
（response/client 上下文关闭）；健康/能力探针正负结果同 TTL 缓存。
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Mapping, Optional, Set, Tuple
from urllib.parse import urlsplit

import httpx

from furina.agent.approval import ApprovalBroker, ApprovalStateError
from furina.agent.approval.models import ApprovalDecisionKind, ResolutionStatus
from furina.agent.permission import Permission
from furina.agent.work_contract import WorkContract, WorkContractValidationError
from furina.core import get_logger

from .models import (
    PROTOCOL_VERSION,
    BackendCapabilities,
    BackendCapabilityError,
    BackendDescriptor,
    BackendError,
    BackendEvent,
    BackendHealth,
    BackendRunHandle,
    BackendScopeViolation,
)
from .protocol import ExecutionBackend

log = get_logger("agent.backend.hermes")

#: 本 backend 稳定身份（契约 allowed_backends 词法同形）。
BACKEND_ID = "hermes"

#: Hermes run_id 词法（进入 URL 前强制校验；防路径注入）。
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

#: 允许的 loopback 主机（任务书 §5：默认仅 loopback；远端需要本 brief 之外的显式 TLS 策略）。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: 端点封闭集（method, path 模板）。任何其它路径本模块绝不请求。
_PATH_HEALTH = "/health"
_PATH_CAPABILITIES = "/v1/capabilities"
_PATH_TOOLSETS = "/v1/toolsets"
_PATH_RUNS = "/v1/runs"
_PATH_RUN = "/v1/runs/{run_id}"
_PATH_EVENTS = "/v1/runs/{run_id}/events"
_PATH_APPROVAL = "/v1/runs/{run_id}/approval"
_PATH_STOP = "/v1/runs/{run_id}/stop"

#: 必须为 True 的 capabilities 广告特征（广告是必要条件，非充分——另有主动握手）。
_REQUIRED_FEATURES = ("run_submission", "run_status", "run_events_sse",
                      "run_stop", "run_approval_response")

#: Hermes 运行状态词表（status 轮询实测/源码对齐）。
_HERMES_STATUSES = frozenset({"queued", "running", "waiting_for_approval", "stopping",
                              "completed", "failed", "cancelled"})
_HERMES_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

#: SSE 行 buffer 硬上限（单行超限 = 帧定界不可信 → fail-closed 断流）。
_MAX_SSE_LINE_BYTES = 256 * 1024
#: 单事件 payload 硬上限（交付 16E 前的预界；16E 信封仍有自己的预算）。
_MIN_EVENT_BYTES = 1024
_MAX_EVENT_BYTES = 1 << 20
#: JSON endpoint 响应 body 硬上限（有限 body；超限 = 协议错误，不解析）。
_MAX_JSON_BODY_BYTES = 4 * (1 << 20)

#: 账本硬容量（满容量 fail-closed；绝不淘汰——淘汰会诱导旧 contract 被重新执行）。
_MAX_TRACKED_CONTRACTS = 512
_MAX_TRACKED_RUNS = 512
_MAX_TRACKED_APPROVALS = 2048

#: 数值上界（防呆：一切超时/窗口必须有界）。
_MAX_TIMEOUT_SECONDS = 3600.0

#: approval.request 帧中的传输层字段（不参与操作身份；其余字段全部进入 canonical
#: operation args —— 同 tool 同 preview 不同 command 必然不同 approval）。
_NON_OPERATION_FRAME_FIELDS = frozenset({"event", "run_id", "timestamp"})

#: 秘密值形态脱敏（本地最小实现；错误文本入 typed error 前先按精确 key 值、再按形态脱敏）。
_SECRET_TEXT_RE = re.compile(
    r"(?i)(?<![a-z0-9_])((?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|private[_-]?key|auth[_-]?token|password|passwd|pwd|"
    r"secret|token|cookie|authorization)\s*[\"']?[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s\"'{}\[\]();,]+))")
_BEARER_TEXT_RE = re.compile(r"(?i)(?<![a-z0-9_])(bearer|basic)\s+[^\s\"'{}\[\]();,]+")


def _redact_text(text: str) -> str:
    """错误文本形态脱敏：键值秘密形态与 Bearer 凭证形态替换为 [REDACTED]。"""
    text = _SECRET_TEXT_RE.sub("[REDACTED]", text)
    text = _BEARER_TEXT_RE.sub(r"\1 [REDACTED]", text)
    return text


# ---------------------------------------------------------------------------
# 类型化错误（全部 BackendError 子类；fail-closed，绝不静默换路径）
# ---------------------------------------------------------------------------
class HermesConfigurationError(BackendError):
    """构造配置非法（非 loopback / URL 凭证 / 非法端口 / 非法数值 / broker 缺失 /
    profile 身份缺失 / tool 映射越权）。"""


class HermesTransportError(BackendError):
    """传输层失败（连接/超时/认证拒绝/限流）；不含任何秘密文本。"""


class HermesProtocolError(BackendError):
    """协议坏响应（形状/身份/状态词表/content-type/redirect 不合 16C 实测契约）。"""


# ---------------------------------------------------------------------------
# 端点配置（frozen；构造期全部校验）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HermesEndpoint:
    """已校验 loopback 端点（origin 形态；无 path/query/userinfo）。"""

    base_url: str

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str) or not self.base_url.strip():
            raise HermesConfigurationError("base_url 必须是非空 str")
        raw = self.base_url.strip()
        parts = urlsplit(raw)
        if parts.scheme != "http":
            raise HermesConfigurationError(
                f"base_url scheme 必须是 http（本 brief 默认仅无 TLS loopback），得到 {parts.scheme!r}")
        host = (parts.hostname or "").strip().lower()
        if host not in _LOOPBACK_HOSTS:
            raise HermesConfigurationError(
                f"base_url 主机必须是 loopback {sorted(_LOOPBACK_HOSTS)}，得到 {host!r}"
                "（远端端点需要本 brief 之外的显式配置与 TLS 策略）")
        if parts.username is not None or parts.password is not None:
            raise HermesConfigurationError("base_url 禁止携带 URL 凭证（userinfo）")
        if parts.query or parts.fragment:
            raise HermesConfigurationError("base_url 禁止携带 query/fragment")
        if parts.path not in ("", "/"):
            raise HermesConfigurationError(f"base_url 不允许携带路径，得到 {parts.path!r}")
        try:
            port = parts.port   # 非法端口（非数字/越界）→ ValueError
        except ValueError as exc:
            raise HermesConfigurationError(f"base_url 端口非法: {exc}") from exc
        if port is None:
            port = 8642   # Hermes API Server 默认端口（源码 DEFAULT_PORT）
        if isinstance(port, bool) or not (1 <= int(port) <= 65535):
            raise HermesConfigurationError(f"base_url 端口非法: {port!r}")
        object.__setattr__(self, "base_url", f"http://[{host}]:{int(port)}"
                           if ":" in host else f"http://{host}:{int(port)}")

    @property
    def origin(self) -> str:
        return self.base_url


def _finite_positive(name: str, value: Any, *, upper: float = _MAX_TIMEOUT_SECONDS) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HermesConfigurationError(f"{name} 必须是非 bool 数值，得到 {value!r}")
    f = float(value)
    if not math.isfinite(f) or f <= 0 or f > upper:
        raise HermesConfigurationError(
            f"{name} 必须有限且 0 < {name} <= {upper}，得到 {value!r}")
    return f


def _plain_tree(obj: Any) -> Any:
    """frozen projection（MappingProxyType/tuple 树）→ 纯 dict/list/plain 树
    （16A from_dict 的 exact-mapping 输入域；零共享引用）。"""
    if isinstance(obj, Mapping):
        return {k: _plain_tree(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain_tree(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# 内部 run 记录 / submit reservation（进程内 correlation 账本；16H 之前无任何持久化）
# ---------------------------------------------------------------------------
class _RunRecord:
    """hermes run_id → 契约身份（进程内；无持久化；无审批缓存——审批身份唯一权威
    在 16D broker 的完整身份原子 get-or-create）。"""

    __slots__ = ("contract_id", "content_hash", "allowed_capabilities", "stopped",
                 "slot_released")

    def __init__(self, contract_id: str, content_hash: str,
                 allowed_capabilities: Tuple[str, ...]) -> None:
        self.contract_id = contract_id
        self.content_hash = content_hash
        self.allowed_capabilities = tuple(allowed_capabilities)
        self.stopped = False
        self.slot_released = False


class _SubmitReservation:
    """contract_id 的原子 submit reservation（并发同契约单 POST 的所有权凭据）。

    状态机（全部在 backend 锁内迁移）：

    - ``RESERVED``  ：已占位、HTTP POST 尚未成功分派；
    - ``COMMITTED`` ：服务器已受理（202 + 合法身份）→ handle 权威；
    - ``FAILED``    ：服务器**明确拒绝**（非 202 响应已收到）→ 无 run 产生，
                      reservation 从账本移除（后续 submit 可重新尝试）；
    - ``AMBIGUOUS`` ：POST 已发出但结果不确定（传输异常 / 202 但身份形状损坏）→
                      **中毒**：账本永久保留占位，同 contract 后续 submit 一律
                      类型化失败，绝不自动重提（防双跑）。
    """

    __slots__ = ("content_hash", "state", "event", "handle", "error")

    RESERVED = "reserved"
    COMMITTED = "committed"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"

    def __init__(self, content_hash: str) -> None:
        self.content_hash = content_hash
        self.state = self.RESERVED
        self.event = threading.Event()
        self.handle: Optional[BackendRunHandle] = None
        self.error: Optional[BackendError] = None

    def finish(self, *, handle: Optional[BackendRunHandle] = None,
               error: Optional[BackendError] = None, remove: bool = False) -> None:
        self.handle = handle
        self.error = error
        if handle is not None:
            self.state = self.COMMITTED
        elif error is not None:
            self.state = self.FAILED if remove else self.AMBIGUOUS
        self.event.set()


# ---------------------------------------------------------------------------
# HermesExecutionBackend
# ---------------------------------------------------------------------------
class HermesExecutionBackend(ExecutionBackend):
    """Hermes API Server Runs 面适配器（16B ExecutionBackend conformance）。

    - ``probe``：/health + /v1/capabilities（Bearer，含 **profile identity 精确绑定**）
      + /v1/toolsets（Bearer，**完整工具面 envelope 快照**）+ 不存在 probe run 上的
      status/events/approval/stop **四端点无副作用主动握手**（全部必须
      404 + 精确 ``run_not_found`` 错误码）；正负结果同 TTL 缓存；认证失败/坏载荷/
      矛盾广告/端点缺失/超时 fail-closed；
    - ``submit``：完整 16A WorkContract projection（from_dict exact-schema +
      content_hash 复核 + capability envelope 封闭相等）→ POST /v1/runs；幂等账本由
      本 backend 拥有（Hermes 不是幂等所有者）：contract_id 原子 reservation 先于
      POST，并发同契约单 POST 同结果；max_concurrent_runs 真实信号量执行；
    - ``events``：SSE → 16B BackendEvent 流（16E 拥有规范化/状态机）；断线 →
      status 轮询 reconcile，**绝不重复 submit**；不可恢复 → transport.disconnected
      （16E UNKNOWN 策略边界）；status/reconcile 身份（object/run_id/状态词表）
      不精确即绝不产生终态；
    - ``stop``：POST stop 只请求；**不产生 CANCELLED**（权威终态只来自 Hermes）；
    - ``resolve_approval``：等待 16D 真实决议 → 只转发 ``once``/``deny``，单 approval
      恰好一次转发。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        approval_broker: ApprovalBroker,
        expected_profile_identity: str,
        tool_capability_map: Mapping[str, str],
        capability_ids: Tuple[str, ...] = (),
        probe_ttl_seconds: float = 30.0,
        max_concurrent_runs: int = 1,
        max_tracked_contracts: int = _MAX_TRACKED_CONTRACTS,
        max_tracked_runs: int = _MAX_TRACKED_RUNS,
        max_tracked_approvals: int = _MAX_TRACKED_APPROVALS,
        request_timeout_seconds: float = 10.0,
        sse_heartbeat_timeout_seconds: float = 45.0,
        max_event_bytes: int = 64 * 1024,
        reconnect_poll_interval_seconds: float = 2.0,
        reconnect_poll_budget_seconds: float = 300.0,
        approval_wait_seconds: float = 110.0,
        now_fn: Any = None,
    ) -> None:
        endpoint = HermesEndpoint(base_url=base_url)
        if not isinstance(api_key, str) or not api_key.strip():
            raise HermesConfigurationError("api_key 必须是非空 str（经既有 secret 机制注入）")
        if not isinstance(approval_broker, ApprovalBroker):
            raise HermesConfigurationError(
                f"approval_broker 必须是 ApprovalBroker（16D 唯一审批通道），"
                f"得到 {type(approval_broker).__name__}")
        if not isinstance(expected_profile_identity, str) or not expected_profile_identity.strip():
            raise HermesConfigurationError(
                "expected_profile_identity 必须是非空 str（probe 与 /v1/capabilities.model "
                "精确绑定；缺失即拒绝构造）")
        if not isinstance(tool_capability_map, Mapping) or not tool_capability_map:
            raise HermesConfigurationError(
                "tool_capability_map 必须是非空 Mapping（Hermes tool → Furina capability "
                "封闭映射；无映射的审批工具一律 fail-closed deny）")
        envelope = tuple(capability_ids)
        frozen_map: Dict[str, str] = {}
        for tool, cap in tool_capability_map.items():
            if not isinstance(tool, str) or not tool.strip():
                raise HermesConfigurationError(f"tool_capability_map 键非法: {tool!r}")
            if not isinstance(cap, str) or not cap.strip():
                raise HermesConfigurationError(f"tool_capability_map[{tool!r}] 值非法: {cap!r}")
            if cap not in envelope:
                raise HermesConfigurationError(
                    f"tool_capability_map[{tool!r}] → {cap!r} 不在本 backend 显式 envelope "
                    f"{sorted(envelope)} 内（映射越权，构造期拒绝）")
            frozen_map[tool] = cap
        if (isinstance(max_concurrent_runs, bool)
                or not isinstance(max_concurrent_runs, int) or max_concurrent_runs < 1
                or max_concurrent_runs > 1024):
            raise HermesConfigurationError(
                f"max_concurrent_runs 必须是 1..1024 的 int，得到 {max_concurrent_runs!r}")
        capacities = {
            "max_tracked_contracts": (max_tracked_contracts, _MAX_TRACKED_CONTRACTS),
            "max_tracked_runs": (max_tracked_runs, _MAX_TRACKED_RUNS),
            "max_tracked_approvals": (max_tracked_approvals, _MAX_TRACKED_APPROVALS),
        }
        for name, (value, upper) in capacities.items():
            if isinstance(value, bool) or not isinstance(value, int) or not (1 <= value <= upper):
                raise HermesConfigurationError(f"{name} 必须是 1..{upper} 的 int，得到 {value!r}")
        if (isinstance(max_event_bytes, bool) or not isinstance(max_event_bytes, int)
                or not (_MIN_EVENT_BYTES <= max_event_bytes <= _MAX_EVENT_BYTES)):
            raise HermesConfigurationError(
                f"max_event_bytes 必须是 {_MIN_EVENT_BYTES}..{_MAX_EVENT_BYTES} 的 int，"
                f"得到 {max_event_bytes!r}")
        self._endpoint = endpoint
        self._api_key = api_key
        self._broker = approval_broker
        self._expected_profile = expected_profile_identity.strip()
        self._tool_capability_map: Dict[str, str] = frozen_map
        self._probe_ttl = _finite_positive("probe_ttl_seconds", probe_ttl_seconds, upper=600.0)
        self._request_timeout = _finite_positive("request_timeout_seconds", request_timeout_seconds)
        self._sse_heartbeat_timeout = _finite_positive(
            "sse_heartbeat_timeout_seconds", sse_heartbeat_timeout_seconds)
        self._max_event_bytes = int(max_event_bytes)
        self._poll_interval = _finite_positive(
            "reconnect_poll_interval_seconds", reconnect_poll_interval_seconds, upper=60.0)
        self._poll_budget = _finite_positive(
            "reconnect_poll_budget_seconds", reconnect_poll_budget_seconds)
        self._approval_wait = _finite_positive("approval_wait_seconds", approval_wait_seconds)
        self._now_fn = now_fn if now_fn is not None else time.time

        self._descriptor = BackendDescriptor(
            backend_id=BACKEND_ID,
            display_name="Hermes API Server",
            description="本机 Hermes API Server Runs 面适配器（Phase 16C；loopback + Bearer + SSE）",
            protocol_version=PROTOCOL_VERSION,
        )
        # 诚实声明：workspace_scoped=False —— Hermes 在其专属 profile/workspace 执行，
        # 不执行 Furina 的路径 scope（带路径 scope 的契约由 router 机制性拒绝）。
        self._capabilities = BackendCapabilities(
            capability_ids=envelope,
            supports_events=True,
            supports_stop=True,
            supports_resolve_approval=True,
            max_concurrent_runs=max_concurrent_runs,
            workspace_scoped=False,
        )
        self._lock = threading.RLock()
        self._contract_index: Dict[str, _SubmitReservation] = {}
        self._runs: Dict[str, _RunRecord] = {}
        self._approval_run_index: Dict[str, str] = {}   # approval_id → run_id（身份精确索引）
        self._approval_forwarded: Set[str] = set()      # exactly-once 转发守卫
        self._max_tracked_contracts = int(max_tracked_contracts)
        self._max_tracked_runs = int(max_tracked_runs)
        self._max_tracked_approvals = int(max_tracked_approvals)
        self._run_slots = threading.BoundedSemaphore(max_concurrent_runs)
        self._probe_cache: Optional[BackendHealth] = None
        self._profile_tools_snapshot: Tuple[str, ...] = ()   # probe 权威工具面快照（不可变派生数据）
        self._client: Optional[httpx.Client] = None

    # -- 身份与能力 --------------------------------------------------------------
    @property
    def descriptor(self) -> BackendDescriptor:
        return self._descriptor

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

    @property
    def capability_envelope(self) -> Tuple[str, ...]:
        """不可变 capability envelope（构造期冻结；契约必须与其**封闭相等**）。"""
        return tuple(self._capabilities.capability_ids)

    @property
    def profile_tools_snapshot(self) -> Tuple[str, ...]:
        """最近一次成功 probe 捕获的 Hermes profile 工具面快照（服务器端
        /v1/toolsets enabled 工具名；不可变派生操作数据，非 C7 真相）。"""
        return self._profile_tools_snapshot

    # -- HTTP 客户端（显式生命周期） ------------------------------------------------
    def _get_client(self) -> httpx.Client:
        with self._lock:
            if self._client is None:
                self._client = httpx.Client(
                    base_url=self._endpoint.origin,
                    headers={"Authorization": f"Bearer {self._api_key}",
                             "Accept": "application/json"},
                    timeout=httpx.Timeout(self._request_timeout),
                    follow_redirects=False,   # 非本地 redirect fail-closed（3xx → 协议错误）
                    trust_env=False,          # loopback 流量绝不经过环境代理
                )
            return self._client

    def close(self) -> None:
        """显式资源清理（幂等；关闭共享 HTTP 客户端）。"""
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            client.close()

    # -- 错误文本纪律（先按精确 key 值脱敏，再做秘密形态脱敏） -----------------------
    def _redact(self, text: str) -> str:
        if not isinstance(text, str):
            text = str(text)
        text = text.replace(self._api_key, "[REDACTED]")
        return _redact_text(text)

    @staticmethod
    def _transport_failure(stage: str, exc: Exception) -> HermesTransportError:
        return HermesTransportError(
            f"hermes {stage} 传输失败: {type(exc).__name__}（细节脱敏）")

    def _redact_body_snippet(self, body: str, *, cap: int = 200) -> str:
        return self._redact(str(body))[:cap]

    def _require_json_object(self, stage: str, response: httpx.Response) -> Dict[str, Any]:
        """2xx + application/json + 有限 body + JSON object 严格解析；
        3xx/非 2xx/content-type 不符/body 超限/坏 JSON 一律类型化错误。"""
        if 300 <= response.status_code < 400:
            raise HermesProtocolError(
                f"hermes {stage} 返回 redirect {response.status_code}"
                "（非本地重定向 fail-closed）")
        if response.status_code // 100 != 2:
            snippet = self._redact_body_snippet(response.text)
            raise HermesTransportError(
                f"hermes {stage} HTTP {response.status_code}: {snippet}")
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            raise HermesProtocolError(
                f"hermes {stage} content-type 必须 application/json，得到 {content_type!r}")
        if len(response.content) > _MAX_JSON_BODY_BYTES:
            raise HermesProtocolError(
                f"hermes {stage} 响应 body 超过硬上限 {_MAX_JSON_BODY_BYTES} bytes")
        try:
            body = response.json()
        except Exception as exc:
            raise HermesProtocolError(
                f"hermes {stage} 响应不是合法 JSON: {type(exc).__name__}") from exc
        if not isinstance(body, dict):
            raise HermesProtocolError(
                f"hermes {stage} 响应必须是 JSON object，得到 {type(body).__name__}")
        return body

    def _error_code_of(self, response: httpx.Response) -> Optional[str]:
        """404/409 特殊路径的真实错误码提取（形状损坏 → None，绝不当作已知码吞掉）。"""
        try:
            body = response.json()
        except Exception:
            return None
        if not isinstance(body, dict):
            return None
        err = body.get("error")
        if not isinstance(err, Mapping):
            return None
        code = err.get("code")
        return code if isinstance(code, str) else None

    # -- 发现：主动握手 probe -----------------------------------------------------
    def probe(self) -> BackendHealth:
        """主动握手健康事实（/health + /capabilities(profile 绑定) + /toolsets(envelope)
        + runs 四端点 404 握手）；正负结果同 TTL 缓存。"""
        now = self._now_fn()
        with self._lock:
            cached = self._probe_cache
        if cached is not None and now < cached.expiry:
            return cached
        health = self._active_probe()
        with self._lock:
            self._probe_cache = health
        return health

    def _active_probe(self) -> BackendHealth:
        now = self._now_fn()
        expiry = now + self._probe_ttl
        installed = True   # 端点配置存在即 installed（installed != reachable）

        def _fail(reason: str, *, reachable: bool = True) -> BackendHealth:
            return BackendHealth(installed=installed, reachable=reachable, healthy=False,
                                 checked_at=now, reason=reason, expiry=expiry)

        client = self._get_client()
        # 1) /health（无认证面）
        try:
            resp = client.get(_PATH_HEALTH)
        except Exception as exc:
            return _fail(f"health_unreachable:{type(exc).__name__}", reachable=False)
        try:
            body = self._require_json_object("health", resp)
        except BackendError as exc:
            return _fail(f"health_bad_response:{type(exc).__name__}")
        if body.get("status") != "ok" or body.get("platform") != "hermes-agent" \
                or not isinstance(body.get("version"), str) or not body.get("version"):
            return _fail("health_shape_contradiction")
        # 2) /v1/capabilities（Bearer；广告是必要条件 + profile identity 精确绑定）
        try:
            resp = client.get(_PATH_CAPABILITIES)
        except Exception as exc:
            return _fail(f"capabilities_unreachable:{type(exc).__name__}", reachable=False)
        if resp.status_code == 401:
            return _fail("auth_rejected")
        try:
            body = self._require_json_object("capabilities", resp)
        except BackendError as exc:
            return _fail(f"capabilities_bad_response:{type(exc).__name__}")
        if body.get("object") != "hermes.api_server.capabilities":
            return _fail("capabilities_object_contradiction")
        auth = body.get("auth")
        if not isinstance(auth, Mapping) or auth.get("type") != "bearer" \
                or auth.get("required") is not True:
            return _fail("capabilities_auth_contradiction")
        advertised_profile = body.get("model")
        if not isinstance(advertised_profile, str) or not advertised_profile.strip():
            return _fail("profile_identity_missing")
        if advertised_profile != self._expected_profile:
            return _fail(
                f"profile_identity_mismatch:expected={self._expected_profile!r},"
                f"advertised={advertised_profile!r}")
        features = body.get("features")
        if not isinstance(features, Mapping):
            return _fail("capabilities_features_missing")
        for name in _REQUIRED_FEATURES:
            if features.get(name) is not True:
                return _fail(f"capability_missing:{name}")
        # 3) /v1/toolsets（Bearer）：dedicated profile/toolset 边界的权威证据面 ——
        #    api_server 平台实际暴露给 run agent 的工具集（enabled + 具体工具名）。
        try:
            resp = client.get(_PATH_TOOLSETS)
        except Exception as exc:
            return _fail(f"toolsets_unreachable:{type(exc).__name__}", reachable=False)
        if resp.status_code == 401:
            return _fail("auth_rejected")
        if resp.status_code != 200:
            return _fail(f"toolsets_endpoint_missing:{resp.status_code}")
        try:
            body = self._require_json_object("toolsets", resp)
        except BackendError as exc:
            return _fail(f"toolsets_bad_response:{type(exc).__name__}")
        if body.get("object") != "list" or not isinstance(body.get("data"), list):
            return _fail("toolsets_shape_contradiction")
        enabled_tools: Set[str] = set()
        for entry in body["data"]:
            if not isinstance(entry, Mapping):
                return _fail("toolsets_entry_contradiction")
            if entry.get("enabled") is True:
                tools = entry.get("tools")
                if not isinstance(tools, list):
                    return _fail("toolsets_tools_contradiction")
                for tool in tools:
                    if isinstance(tool, str) and tool.strip():
                        enabled_tools.add(tool)
        # 4) runs 面四端点无副作用主动握手：必定不存在的 probe run_id →
        #    全部必须 404 + 精确 run_not_found（required feature 广告与实际 endpoint
        #    一一对应；缺失/认证异常/形状矛盾 → unhealthy）。
        probe_run_id = f"prb_{uuid.uuid4().hex}"
        handshakes = (
            ("run_status", "GET", _PATH_RUN.format(run_id=probe_run_id), None),
            ("run_events", "GET", _PATH_EVENTS.format(run_id=probe_run_id), None),
            ("run_approval", "POST", _PATH_APPROVAL.format(run_id=probe_run_id),
             {"choice": "deny"}),
            ("run_stop", "POST", _PATH_STOP.format(run_id=probe_run_id), None),
        )
        for stage, method, path, json_body in handshakes:
            try:
                resp = client.request(method, path, json=json_body)
            except Exception as exc:
                return _fail(f"{stage}_unreachable:{type(exc).__name__}", reachable=False)
            if resp.status_code == 401:
                return _fail("auth_rejected")
            if resp.status_code != 404:
                return _fail(f"{stage}_endpoint_contradiction:{resp.status_code}")
            if self._error_code_of(resp) != "run_not_found":
                return _fail(f"{stage}_handshake_contradiction")
        with self._lock:
            self._profile_tools_snapshot = tuple(sorted(enabled_tools))
        return BackendHealth(installed=True, reachable=True, healthy=True,
                             checked_at=now, reason="", expiry=expiry)

    # -- 执行：submit（幂等账本在本 backend，Hermes 不是幂等所有者） -----------------
    def submit(self, contract_projection: Mapping[str, Any], *,
               run_id: Optional[str] = None) -> BackendRunHandle:
        contract = self._parse_contract(contract_projection)
        reservation = self._acquire_reservation(contract)
        if isinstance(reservation, BackendRunHandle):
            return reservation   # 幂等重放：同契约 → 同 handle，零重复 submit
        # 并发同契约的输家已在 _acquire_reservation 内等待并拿到与赢家相同的结果。
        if not self._run_slots.acquire(blocking=False):
            error = BackendScopeViolation(
                f"max_concurrent_runs={self._capabilities.max_concurrent_runs} 已满"
                "（真实并发执行上限，fail-closed）")
            self._settle_reservation(contract.contract_id, reservation,
                                     error=error, remove=True)
            raise error
        client = self._get_client()
        try:
            resp = client.post(_PATH_RUNS, json={"input": contract.canonical_user_request})
        except Exception as exc:
            # POST 已发出但结果不确定（连接/读/超时无法区分是否到达服务器）→
            # reservation 中毒，绝不自动重提（防 Hermes 双跑）。
            error = HermesTransportError(
                f"hermes submit 结果不确定（{type(exc).__name__}）：是否已到达服务器"
                "不可判；同 contract 后续 submit 绝不自动重提")
            self._settle_reservation(contract.contract_id, reservation,
                                     error=error, remove=False)
            self._run_slots.release()
            raise error from exc
        # 零 fallback、零重试：非 202（含 3xx/401/429/5xx）= 服务器明确拒绝（无 run 产生）
        # → reservation 释放（可由操作方重新尝试）；202 但身份形状损坏 = 不确定 → 中毒。
        if resp.status_code != 202:
            if resp.status_code // 100 == 2 or 300 <= resp.status_code < 400:
                error = HermesProtocolError(
                    f"hermes submit 必须 202，得到 {resp.status_code}"
                    + ("（redirect 非本地重定向 fail-closed）" if 300 <= resp.status_code < 400
                       else "（实测契约）"))
            else:
                error = self._transport_failure_status("submit", resp)
            self._settle_reservation(contract.contract_id, reservation,
                                     error=error, remove=True)
            self._run_slots.release()
            raise error
        try:
            body = self._require_json_object("submit", resp)
            hermes_run_id = body.get("run_id")
            status = body.get("status")
            if not isinstance(hermes_run_id, str) or not _RUN_ID_RE.match(hermes_run_id):
                raise HermesProtocolError(f"hermes submit run_id 非法: {hermes_run_id!r}")
            if status != "started":
                raise HermesProtocolError(
                    f"hermes submit status 必须 'started'，得到 {status!r}")
        except BackendError as exc:
            self._settle_reservation(contract.contract_id, reservation,
                                     error=HermesTransportError(
                                         "hermes submit 202 身份形状损坏：结果不确定，"
                                         "不自动重提；同 contract 后续 submit 一律拒绝"),
                                     remove=False)
            self._run_slots.release()
            raise exc
        handle = BackendRunHandle(backend_id=BACKEND_ID, run_id=hermes_run_id,
                                  correlation=contract.contract_id)
        with self._lock:
            if len(self._runs) >= self._max_tracked_runs and hermes_run_id not in self._runs:
                # run 已在服务器侧启动，但账本硬容量已满 → 拒绝交付（fail-closed，
                # 不淘汰既有记录）；reservation 中毒防重提。
                self._settle_reservation_locked(contract.contract_id, reservation,
                                                error=HermesTransportError(
                                                    "run 账本硬容量已满（不淘汰既有记录）"
                                                    "：结果不确定，不自动重提"),
                                                remove=False)
                self._run_slots.release()
                raise self._runs_full_error()
            self._runs[hermes_run_id] = _RunRecord(contract.contract_id, contract.content_hash,
                                                   contract.allowed_capabilities)
            reservation.finish(handle=handle)
        return handle

    def _runs_full_error(self) -> HermesTransportError:
        return HermesTransportError("hermes run 账本硬容量已满（fail-closed，不淘汰）")

    def _transport_failure_status(self, stage: str, resp: httpx.Response) -> HermesTransportError:
        snippet = self._redact_body_snippet(resp.text)
        return HermesTransportError(f"hermes {stage} HTTP {resp.status_code}: {snippet}")

    def _settle_reservation(self, contract_id: str, reservation: _SubmitReservation, *,
                            error: BackendError, remove: bool) -> None:
        with self._lock:
            self._settle_reservation_locked(contract_id, reservation, error=error, remove=remove)

    def _settle_reservation_locked(self, contract_id: str, reservation: _SubmitReservation, *,
                                   error: BackendError, remove: bool) -> None:
        reservation.finish(error=error, remove=remove)
        if remove and self._contract_index.get(contract_id) is reservation:
            del self._contract_index[contract_id]

    def _acquire_reservation(self, contract: WorkContract
                             ) -> Any:   # BackendRunHandle（重放）| _SubmitReservation（赢家）
        """原子 reservation 获取：并发同契约单 POST；输家阻塞等待并复用赢家结果。"""
        with self._lock:
            existing = self._contract_index.get(contract.contract_id)
            if existing is not None:
                if existing.content_hash != contract.content_hash:
                    raise BackendScopeViolation(
                        f"contract_id {contract.contract_id!r} 已绑定不同内容摘要"
                        f"（old={existing.content_hash[:12]}… new={contract.content_hash[:12]}…）："
                        "冲突而非更新，拒绝重复提交")
                if existing.state == _SubmitReservation.COMMITTED:
                    return existing.handle
                if existing.state == _SubmitReservation.AMBIGUOUS:
                    raise HermesTransportError(
                        "hermes submit 先前结果不确定（已中毒）：同 contract 绝不自动重提")
                if existing.state == _SubmitReservation.RESERVED:
                    pass   # 并发在途：锁外等待赢家结果
                else:   # FAILED（正在被移除的瞬态）→ 视同新建
                    existing = None
            if existing is None:
                if len(self._contract_index) >= self._max_tracked_contracts:
                    raise BackendScopeViolation(
                        f"contract 账本硬容量已满（{self._max_tracked_contracts}，"
                        "fail-closed，不淘汰既有记录）")
                reservation = _SubmitReservation(contract.content_hash)
                self._contract_index[contract.contract_id] = reservation
                return reservation
            reservation = existing
        # 并发输家：等待赢家 settle（有界），随后复用其结果（同契约 ⇒ 同结果）。
        if not reservation.event.wait(timeout=self._request_timeout + 5.0):
            raise HermesTransportError(
                "并发同 contract submit 在途等待超窗（fail-closed；未发起任何 POST）")
        with self._lock:
            if reservation.state == _SubmitReservation.COMMITTED:
                assert reservation.handle is not None
                return reservation.handle
            if reservation.state == _SubmitReservation.FAILED and \
                    self._contract_index.get(contract.contract_id) is not reservation:
                # 赢家已明确失败并释放占位：输家拿到与赢家相同的类型化失败。
                assert reservation.error is not None
                raise type(reservation.error)(str(reservation.error))
            if reservation.state == _SubmitReservation.FAILED:
                self._contract_index.pop(contract.contract_id, None)
                assert reservation.error is not None
                raise type(reservation.error)(str(reservation.error))
            if reservation.state == _SubmitReservation.AMBIGUOUS:
                assert reservation.error is not None
                raise HermesTransportError(
                    "hermes submit 先前结果不确定（已中毒）：同 contract 绝不自动重提")
        raise HermesTransportError("并发 submit 状态不可判（fail-closed）")

    # -- WorkContract 权威解析（submit 前全部拒绝面） --------------------------------
    def _parse_contract(self, projection: Any) -> WorkContract:
        """submit 输入唯一权威入口：16A exact-schema + content_hash 复核 + 后端授权。

        - 非完整 WorkContract projection（缺字段/未知字段/schema marker 不符）→ 拒绝；
        - content_hash 篡改（from_dict 从不重新签名，摘要不符即拒绝）→ 拒绝；
        - allowed_backends 不含 hermes（自签扩权）→ 拒绝；
        - 携带路径 scope（workspace_scoped=False 诚实声明）→ 拒绝；
        - allowed_capabilities 与本 backend envelope 非**封闭相等**（多、少、未知任何
          一侧不匹配）→ 拒绝——不只证明"契约是 backend 声明的子集"。
        """
        if not isinstance(projection, Mapping):
            raise BackendScopeViolation(
                f"contract_projection 必须是 Mapping，得到 {type(projection).__name__}")
        try:
            contract = WorkContract.from_dict(_plain_tree(projection))
        except WorkContractValidationError as exc:
            raise BackendScopeViolation(
                f"contract_projection 未通过 16A canonical 校验（exact-schema + "
                f"content_hash 复核）: {exc}") from exc
        if BACKEND_ID not in contract.allowed_backends:
            raise BackendScopeViolation(
                f"contract.allowed_backends {sorted(contract.allowed_backends)} 不含 "
                f"'{BACKEND_ID}'（契约不允许本 backend；自签扩权 submit 前拒绝）")
        ws = contract.workspace_scope
        if tuple(ws.read_roots) or tuple(ws.write_roots):
            raise BackendScopeViolation(
                "contract.workspace_scope 携带路径 scope：hermes backend 不执行 Furina "
                "路径 scope（workspace_scoped=False，诚实声明）")
        envelope = set(self._capabilities.capability_ids)
        requested = set(contract.allowed_capabilities)
        if requested != envelope:
            raise BackendScopeViolation(
                f"contract.allowed_capabilities {sorted(requested)} 与本 backend 不可变 "
                f"capability envelope {sorted(envelope)} 非封闭相等（closed match；"
                "子集/超集/未知能力一律拒绝）")
        if not contract.canonical_user_request.strip():
            raise BackendScopeViolation("contract.canonical_user_request 为空")
        return contract

    # -- 事件：SSE → BackendEvent（16E 拥有规范化） --------------------------------
    def events(self, run_handle: BackendRunHandle) -> Iterator[BackendEvent]:
        if not self.capabilities.supports_events:
            raise BackendCapabilityError("hermes 未声明 supports_events")
        if not isinstance(run_handle, BackendRunHandle):
            raise HermesProtocolError(
                f"events 需要 BackendRunHandle，得到 {type(run_handle).__name__}")
        if run_handle.backend_id != BACKEND_ID:
            raise HermesProtocolError(
                f"handle.backend_id {run_handle.backend_id!r} != '{BACKEND_ID}'（身份精确绑定）")
        with self._lock:
            record = self._runs.get(run_handle.run_id)
        if record is None:
            raise HermesProtocolError(
                f"未知 hermes run: {run_handle.run_id!r}（仅接受本 backend submit 的 run）")
        # 权威生命周期同步：Hermes SSE 面不含 queued/running 生命周期事件（只有
        # tool/approval/终态帧），而权威 status 记录 + 源码次序（先 queued 后 running）
        # 是确认过的事实——同步最小前缀，供 16E 状态机建立合法上下文；绝不臆造终态。
        for event in self._lifecycle_sync(run_handle.run_id):
            yield event
        # 主循环：SSE 订阅 → 断线 reconcile（绝不重提 submit）。SSE 流消费至自然
        # 结束（重复终态帧交由 16E 终态吸收），出现权威终态后收口释放并发槽位。
        while True:
            terminal_seen = False
            for event in self._consume_sse(run_handle.run_id, record):
                yield event
                if event.event_type in ("run.completed", "run.failed", "run.cancelled"):
                    terminal_seen = True
            if terminal_seen:
                self._release_run_slot(run_handle.run_id)
                return
            # SSE 结束但未达权威终态（断线 / 404 传输缓冲被清）→ status 轮询 reconcile。
            for event in self._reconcile_by_status(run_handle.run_id):
                yield event
                if event.event_type in ("run.completed", "run.failed", "run.cancelled"):
                    self._release_run_slot(run_handle.run_id)
                    return
                if event.event_type == "transport.disconnected":
                    # 非终态（run 可能仍在服务器侧活跃）：并发槽位诚实保留不释放。
                    return

    def _release_run_slot(self, run_id: str) -> None:
        """权威终态交付时释放 max_concurrent_runs 槽位（恰一次；断线不释放）。"""
        with self._lock:
            record = self._runs.get(run_id)
            if record is None or record.slot_released:
                return
            record.slot_released = True
        try:
            self._run_slots.release()
        except ValueError:   # 防御：信号量计数异常绝不外泄
            log.error("hermes run=%s 并发槽位重复释放（防御性吞没）", run_id)

    def _lifecycle_sync(self, run_id: str) -> Iterator[BackendEvent]:
        """权威 status 记录 → 最小生命周期前缀（queued[/running]）。

        只使用 Hermes 权威 status 记录与源码保证的次序事实（run 创建即 queued，
        running 先于一切 tool/approval 活动）；completed/failed 必然经过 running；
        cancelled 可能发生在 queued 阶段（不补 running）。身份/形状不精确 →
        protocol.error，绝不臆造生命周期。
        """
        status = self._read_authoritative_status(run_id, allow=None)
        if status is None:
            return
        yield self._make_event(run_id, "queued", {"source": "lifecycle_sync"})
        if status in ("running", "waiting_for_approval", "stopping", "completed", "failed"):
            yield self._make_event(run_id, "running", {"source": "lifecycle_sync"})

    def _read_authoritative_status(self, run_id: str, *, allow: Optional[frozenset],
                                   ) -> Optional[str]:
        """status GET 严格解析：200 + application/json + 有限 body + object==hermes.run
        + run_id 精确相等 + 状态词表。违反 → None（调用方自行 protocol.error；
        **绝不产生终态**）。``allow`` 限定可接受状态（None = 全词表）。"""
        client = self._get_client()
        try:
            resp = client.get(_PATH_RUN.format(run_id=run_id))
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        try:
            body = self._require_json_object("status", resp)
        except BackendError:
            return None
        if body.get("object") != "hermes.run":
            return None
        frame_run = body.get("run_id")
        if frame_run != run_id:
            return None
        status = body.get("status")
        if not isinstance(status, str) or status not in _HERMES_STATUSES:
            return None
        if allow is not None and status not in allow:
            return None
        return status

    def _make_event(self, run_id: str, event_type: str, payload: Mapping[str, Any]) -> BackendEvent:
        return BackendEvent(backend_id=BACKEND_ID, run_id=run_id,
                            event_type=event_type, payload=dict(payload))

    def _consume_sse(self, run_id: str, record: _RunRecord) -> Iterator[BackendEvent]:
        """订阅一次 SSE 流并逐帧交付 BackendEvent。

        - 行**增量**消费（一个 chunk 多条合法短行绝不误判单行超限；单行上限只作用于
          残余不完整 buffer）；
        - 事件 payload 按**原始 UTF-8 bytes** 计数；超限 → protocol.error 一次 +
          **discard-until-blank**：同一超限事件的后续 data 行绝不重新解释，空行后
          流继续；
        - UTF-8 严格解码：非法字节 → protocol.error + fail-closed 断流（绝不形成
          业务/终态事件）；
        - 帧界/身份冲突 fail-closed。
        """
        client = self._get_client()
        try:
            stream_cm = client.stream(
                "GET", _PATH_EVENTS.format(run_id=run_id),
                headers={"Accept": "text/event-stream"},
                timeout=httpx.Timeout(self._sse_heartbeat_timeout))
            response = stream_cm.__enter__()
        except Exception as exc:
            raise self._transport_failure("sse_connect", exc) from exc
        try:
            if response.status_code == 404:
                # 传输缓冲已被清除（此前断线/终态清扫）→ 交由 status reconcile。
                # 404 必须携带精确 run_not_found 错误码，否则按协议矛盾可观察。
                try:
                    response.read()
                except Exception:
                    pass
                if self._error_code_of(response) not in (None, "run_not_found"):
                    yield self._make_event(run_id, "protocol.error",
                                           {"reason": "sse_404_wrong_code"})
                return
            if response.status_code == 401:
                raise HermesTransportError("hermes sse 认证拒绝（401）")
            if response.status_code != 200:
                raise HermesProtocolError(
                    f"hermes sse 必须 200，得到 {response.status_code}")
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type:
                raise HermesProtocolError(
                    f"hermes sse content-type 必须 text/event-stream，得到 {content_type!r}")
            buffer = bytearray()
            data_lines: List[bytes] = []
            data_bytes = 0
            discarding = False
            over_limit_reported = False
            try:
                for chunk in response.iter_bytes():
                    buffer.extend(chunk)
                    while True:
                        nl = buffer.find(b"\n")
                        if nl < 0:
                            break
                        raw_line = bytes(buffer[:nl])
                        del buffer[:nl + 1]
                        line = raw_line.rstrip(b"\r")
                        if len(line) > _MAX_SSE_LINE_BYTES:
                            # 单行超硬上限（即便定界完整）：fail-closed 断流。
                            yield self._make_event(run_id, "protocol.error",
                                                   {"reason": "sse_line_over_limit"})
                            return
                        if line.startswith(b":"):
                            continue   # 心跳 / 关闭哨兵：非权威帧标记，绝不折算状态
                        if line.startswith(b"data:"):
                            payload = line[5:]
                            if payload.startswith(b" "):
                                payload = payload[1:]
                            if discarding:
                                continue   # 同一超限事件的后续 data 行不得重新解释
                            data_lines.append(payload)
                            data_bytes += len(payload)   # 原始 UTF-8 bytes 计数
                            if data_bytes > self._max_event_bytes:
                                data_lines = []
                                data_bytes = 0
                                discarding = True
                                if not over_limit_reported:
                                    over_limit_reported = True
                                    yield self._make_event(
                                        run_id, "protocol.error",
                                        {"reason": "sse_event_over_limit"})
                            continue
                        if not line:
                            if discarding:
                                discarding = False
                                over_limit_reported = False
                                continue
                            if data_lines:
                                joined = b"\n".join(data_lines)
                                data_lines = []
                                data_bytes = 0
                                try:
                                    data_text = joined.decode("utf-8")   # 严格解码
                                except UnicodeDecodeError:
                                    yield self._make_event(run_id, "protocol.error",
                                                           {"reason": "sse_invalid_utf8"})
                                    return   # fail-closed 断流；交由 status reconcile
                                event = self._dispatch_frame(run_id, record, data_text)
                                if event is not None:
                                    yield event
                        # 其余非空行（event:/id:/retry: 等）——本端点实测不存在，忽略。
                    # 残余不完整行才是单行上限的判定对象（完整行已增量消费）。
                    if len(buffer) > _MAX_SSE_LINE_BYTES:
                        yield self._make_event(run_id, "protocol.error",
                                               {"reason": "sse_line_over_limit"})
                        return   # 帧定界不可信：fail-closed 断流
                if data_lines and not discarding:
                    joined = b"\n".join(data_lines)
                    try:
                        data_text = joined.decode("utf-8")
                    except UnicodeDecodeError:
                        yield self._make_event(run_id, "protocol.error",
                                               {"reason": "sse_invalid_utf8"})
                        return
                    event = self._dispatch_frame(run_id, record, data_text)
                    if event is not None:
                        yield event
            except HermesProtocolError:
                raise
            except Exception as exc:
                # 连接中断/读超时：不是终态。交由 reconcile（本轮 SSE 静默结束）。
                log.debug("hermes sse 断线 run=%s: %s", run_id, type(exc).__name__)
                return
        finally:
            # 显式资源清理：response 关闭（取消安全——生成器被 close()/GC 时同样执行）。
            try:
                stream_cm.__exit__(None, None, None)
            except Exception:
                pass

    def _dispatch_frame(self, run_id: str, record: _RunRecord,
                        data_text: str) -> Optional[BackendEvent]:
        """单帧 JSON → BackendEvent；坏帧 → protocol.error（流继续）；身份冲突 fail-closed。"""
        try:
            frame = json.loads(data_text)
        except Exception:
            return self._make_event(run_id, "protocol.error", {"reason": "sse_frame_bad_json"})
        if not isinstance(frame, dict):
            return self._make_event(run_id, "protocol.error", {"reason": "sse_frame_not_object"})
        token = frame.get("event")
        if not isinstance(token, str) or not token.strip():
            return self._make_event(run_id, "protocol.error", {"reason": "sse_frame_no_event"})
        frame_run = frame.get("run_id")
        if frame_run is not None and frame_run != run_id:
            # 身份精确绑定：携带不一致 run_id 的帧绝不折算为本 run 的事件。
            return self._make_event(run_id, "protocol.error",
                                    {"reason": "run_id_mismatch"})
        payload = dict(frame)
        if token.strip() == "approval.request":
            approval_id, deny_reason = self._handle_approval_request(run_id, record, frame)
            if approval_id is None:
                return self._make_event(run_id, "protocol.error",
                                        {"reason": deny_reason or "approval_forwarding_failed"})
            payload = {**payload, "approval_id": approval_id}
        return self._make_event(run_id, token.strip(), payload)

    # -- 断线 reconcile：status 轮询（零重复 submit；有界窗口） ----------------------
    def _reconcile_by_status(self, run_id: str) -> Iterator[BackendEvent]:
        client = self._get_client()
        deadline = self._now_fn() + self._poll_budget
        reconnected_sent = False
        stopping_sent = False
        approval_gap_sent = False
        identity_error_sent = False
        while self._now_fn() < deadline:
            try:
                resp = client.get(_PATH_RUN.format(run_id=run_id))
            except Exception:
                time.sleep(self._poll_interval)
                continue
            if resp.status_code == 404:
                # 终态记录已被 Hermes 清扫（终态 + TTL 3600s 后）：仅当错误码**精确**
                # 为 run_not_found 才可判 swept；其余 404 形状按协议矛盾继续轮询。
                if self._error_code_of(resp) == "run_not_found":
                    yield self._make_event(run_id, "transport.disconnected",
                                           {"reason": "run_record_swept"})
                    return
                if not identity_error_sent:
                    identity_error_sent = True
                    yield self._make_event(run_id, "protocol.error",
                                           {"reason": "status_404_wrong_code"})
                time.sleep(self._poll_interval)
                continue
            if resp.status_code == 401:
                yield self._make_event(run_id, "transport.disconnected",
                                       {"reason": "auth_rejected"})
                return
            if resp.status_code != 200:
                time.sleep(self._poll_interval)
                continue
            try:
                body = self._require_json_object("status", resp)
            except BackendError:
                time.sleep(self._poll_interval)
                continue
            # 身份封闭：object/run_id 不精确（缺失/冲突）→ 绝不产生终态，仅可观察。
            if body.get("object") != "hermes.run" or body.get("run_id") != run_id:
                if not identity_error_sent:
                    identity_error_sent = True
                    yield self._make_event(run_id, "protocol.error",
                                           {"reason": "status_identity_conflict"})
                time.sleep(self._poll_interval)
                continue
            status = body.get("status")
            if not isinstance(status, str) or status not in _HERMES_STATUSES:
                if not identity_error_sent:
                    identity_error_sent = True
                    yield self._make_event(run_id, "protocol.error",
                                           {"reason": "status_word_unknown"})
                time.sleep(self._poll_interval)
                continue
            if status in _HERMES_TERMINAL_STATUSES:
                payload = {k: body[k] for k in ("output", "usage", "error") if k in body}
                yield self._make_event(run_id, f"run.{status}", payload)
                return
            if status == "stopping":
                if not stopping_sent:
                    stopping_sent = True
                    yield self._make_event(run_id, "stopping", {})
            elif status == "waiting_for_approval":
                # 审批身份无法从 status 轮询重建（命令身份不在状态记录里）——
                # fail-closed 可观察；绝不伪造 approval_id。
                if not approval_gap_sent:
                    approval_gap_sent = True
                    yield self._make_event(run_id, "protocol.error",
                                           {"reason": "approval_pending_not_recoverable_via_poll"})
            else:
                # queued/running：非权威重连观察（16E 不复活终态）。
                if not reconnected_sent:
                    reconnected_sent = True
                    yield self._make_event(run_id, "transport.reconnected", {})
            time.sleep(self._poll_interval)
        yield self._make_event(run_id, "transport.disconnected",
                               {"reason": "reconcile_budget_exhausted"})

    # -- 停止：只请求，绝不提前 CANCELLED -------------------------------------------
    def stop(self, run_handle: BackendRunHandle) -> None:
        if not self.capabilities.supports_stop:
            raise BackendCapabilityError("hermes 未声明 supports_stop")
        if not isinstance(run_handle, BackendRunHandle):
            raise HermesProtocolError(
                f"stop 需要 BackendRunHandle，得到 {type(run_handle).__name__}")
        if run_handle.backend_id != BACKEND_ID:
            raise HermesProtocolError(
                f"stop handle.backend_id {run_handle.backend_id!r} != '{BACKEND_ID}'"
                "（身份精确绑定）")
        with self._lock:
            record = self._runs.get(run_handle.run_id)
        if record is None:
            raise HermesProtocolError(f"未知 hermes run: {run_handle.run_id!r}")
        client = self._get_client()
        try:
            resp = client.post(_PATH_STOP.format(run_id=run_handle.run_id))
        except Exception as exc:
            raise self._transport_failure("stop", exc) from exc
        if resp.status_code == 404:
            # 404 特殊语义只在错误码精确为 run_not_found 时成立；其余 404 形状 = 协议矛盾。
            if self._error_code_of(resp) != "run_not_found":
                raise HermesProtocolError(
                    f"hermes stop 404 错误码非 run_not_found: "
                    f"{self._redact_body_snippet(resp.text)}")
            raise HermesTransportError(
                "hermes stop 404：run 当前无活跃 agent/task（可能已终态）——"
                "以 status/SSE 权威终态为准，本方法不声明 CANCELLED")
        body = self._require_json_object("stop", resp)
        if resp.status_code != 200 or body.get("status") != "stopping" \
                or body.get("run_id") != run_handle.run_id:
            raise HermesProtocolError("hermes stop 响应形状非法（实测契约：stopping）")
        with self._lock:
            record.stopped = True
        # 注意：此处**绝不**产生 run.cancelled —— CANCELLED 只能来自 Hermes 权威终态。

    # -- 审批：SSE approval.request → 16D；决议只来自真实 Furina 决议 -----------------
    def _handle_approval_request(self, run_id: str, record: _RunRecord,
                                 frame: Mapping[str, Any]
                                 ) -> Tuple[Optional[str], Optional[str]]:
        """approval.request → 16D 请求（完整身份原子 get-or-create）或 fail-closed 自动 deny。

        扩权拒绝面（绝不向用户制造可扩权审批）：

        - frame 工具缺失/非 str → 自动 deny（``approval_tool_missing``）；
        - 工具不在构造期封闭 tool→capability 映射内 → 自动 deny
          （``approval_tool_unmapped``）；
        - 映射 capability 不在本 run 契约 allowed_capabilities 内（防御性复检）
          → 自动 deny（``approval_capability_not_in_contract``）；
        - approval 身份索引硬容量已满 → 自动 deny（``approval_ledger_full``）。

        自动 deny 只向 Hermes 转发 ``deny``，**不创建任何 16D 审批请求**。
        映射成功 → ``broker.get_or_create_request``（producer 公开面）：完整身份
        （contract/hash/run/tool/capability/scope/risk/policy/operation_digest，其中
        operation digest 由 16D broker 对**原始完整 args** 现场计算）原子去重——
        同 tool 同 preview 不同 command 必然不同 approval_id。绝不伪造 USER evidence、
        绝不签发 grant/permit；决议由 Furina 决策面（broker owner）做出。
        """
        tool = frame.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            self._forward_auto_deny(run_id)
            return None, "approval_tool_missing"
        tool = tool.strip()
        capability = self._tool_capability_map.get(tool)
        if capability is None:
            self._forward_auto_deny(run_id)
            return None, "approval_tool_unmapped"
        if capability not in record.allowed_capabilities:
            self._forward_auto_deny(run_id)
            return None, "approval_capability_not_in_contract"
        with self._lock:
            full = len(self._approval_run_index) >= self._max_tracked_approvals
        if full:
            self._forward_auto_deny(run_id)
            return None, "approval_ledger_full"
        # canonical operation args = frame 全量减传输层字段（零 str() coercion、零截断；
        # 任何 command/args 差异 ⇒ 不同 operation digest ⇒ 不同 approval）。
        op_args = {k: v for k, v in frame.items() if k not in _NON_OPERATION_FRAME_FIELDS}
        reason = str(frame.get("preview") or frame.get("command") or "")[:200]   # 仅展示面
        try:
            request, _created = self._broker.get_or_create_request(
                contract_id=record.contract_id,
                run_id=run_id,
                tool=tool,
                capability=capability,
                args=op_args,
                reason=reason,
                risk_level=Permission.L2_HIGH_RISK,
                requested_scope=(),
                provenance="hermes_adapter",
                policy_kind="approval_required_each_step",
                contract_hash=record.content_hash,
            )
        except ApprovalStateError:
            return None, "approval_forwarding_failed"
        with self._lock:
            self._approval_run_index.setdefault(request.approval_id, run_id)
        return request.approval_id, None

    def _forward_auto_deny(self, run_id: str) -> None:
        """fail-closed 自动 deny：直接向 Hermes 转发 deny（不建立 16D 请求）。

        转发失败仅记录（可观察），绝不重试、绝不出 fallback 通道。
        """
        client = self._get_client()
        try:
            resp = client.post(_PATH_APPROVAL.format(run_id=run_id), json={"choice": "deny"})
            if resp.status_code not in (200, 409):
                log.warning("hermes run=%s 自动 deny 转发异常 HTTP %s", run_id, resp.status_code)
        except Exception as exc:
            log.warning("hermes run=%s 自动 deny 转发失败: %s", run_id, type(exc).__name__)

    def resolve_approval(self, approval_ref: str) -> Dict[str, Any]:
        """等待 16D 真实决议并**恰好一次**转发 Hermes（choice 只允许 once/deny）。

        - ``approval_ref`` 必须是本 backend 经 16D 建立过的 approval_id（身份精确绑定）；
        - Furina 决议 APPROVE_ONCE / APPROVE_SESSION → ``once``（会话级决议**收窄**为
          单步转发，绝不放宽到 Hermes session/always）；
        - DENY / TIMEOUT / REVOKED / 未决（LATE/UNKNOWN）→ ``deny``（fail-closed）；
        - **exactly-once**：同一 approval 无论顺序重复还是并发 resolve，只有首个调用
          会 POST；其余调用返回 typed no-op（``forwarded=False``），绝不二次 POST；
        - ``once`` 转发成功后真实消费 16D approval（approve_once 标记消费）；
        - 成功必须 ``resolved == 1`` 精确成立，否则类型化协议错误（绝不虚报成功）；
        - 409 仅当错误码**精确**为 ``approval_not_pending`` 才视为 typed no-op。
        """
        if not self.capabilities.supports_resolve_approval:
            raise BackendCapabilityError("hermes 未声明 supports_resolve_approval")
        if not isinstance(approval_ref, str) or not approval_ref.strip():
            raise HermesProtocolError("approval_ref 必须是非空 str")
        approval_id = approval_ref.strip()
        with self._lock:
            run_id = self._approval_run_index.get(approval_id)
            if run_id is None:
                raise HermesProtocolError(
                    f"未知 approval_ref: {approval_id!r}（仅接受本 backend 经 16D 建立的审批）")
            if approval_id in self._approval_forwarded:
                # typed no-op：该 approval 已（正在）转发，绝不二次 POST。
                return {"choice": None, "resolved": 0, "forwarded": False,
                        "resolution_status": "already_forwarded",
                        "reason": "approval_forward_exactly_once"}
            self._approval_forwarded.add(approval_id)   # 先占位：并发只有一个请求获胜
        resolution = self._broker.wait_for_resolution(approval_id,
                                                      timeout=self._approval_wait)
        approved = bool(resolution.ok) and resolution.decision in (
            ApprovalDecisionKind.APPROVE_ONCE, ApprovalDecisionKind.APPROVE_SESSION)
        choice = "once" if approved else "deny"
        resolution_status = str(resolution.status.value
                                if isinstance(resolution.status, ResolutionStatus)
                                else resolution.status)
        client = self._get_client()
        try:
            resp = client.post(_PATH_APPROVAL.format(run_id=run_id),
                               json={"choice": choice})
        except Exception as exc:
            raise self._transport_failure("approval", exc) from exc
        if resp.status_code == 409:
            if self._error_code_of(resp) != "approval_not_pending":
                raise HermesProtocolError(
                    f"hermes approval 409 错误码非 approval_not_pending: "
                    f"{self._redact_body_snippet(resp.text)}")
            # Hermes 侧已无挂起审批（已解析/已过期）：类型化 no-op，绝不重试。
            return {"choice": choice, "resolved": 0, "forwarded": True,
                    "resolution_status": resolution_status}
        body = self._require_json_object("approval", resp)
        if resp.status_code != 200 or body.get("object") != "hermes.run.approval_response" \
                or body.get("run_id") != run_id:
            raise HermesProtocolError("hermes approval 响应形状非法（实测契约）")
        resolved = body.get("resolved")
        if isinstance(resolved, bool) or not isinstance(resolved, int):
            raise HermesProtocolError(f"hermes approval resolved 非法: {resolved!r}")
        if resolved != 1:
            raise HermesProtocolError(
                f"hermes approval resolved 必须 == 1 才算成功，得到 {resolved!r}")
        consumed = False
        if choice == "once":
            # APPROVE_ONCE 成功转发后必须真实消费 16D approval（exactly-once 标记）。
            try:
                consumed = bool(self._broker.consume(approval_id))
            except ApprovalStateError:
                consumed = False
            if not consumed:
                log.warning("hermes approval=%s 转发 once 后消费未成立（16D 状态复核）",
                            approval_id)
        return {"choice": choice, "resolved": resolved, "forwarded": True,
                "consumed": consumed, "resolution_status": resolution_status}
