"""Phase 16C — Hermes API Backend Adapter（本机 Hermes API Server Runs 面的唯一执行通道）。

权威依据（本机实测 + 源码，Hermes Agent v0.20.6 / upstream 4e7eb399）：

- ``GET  /health``                       → ``{"status":"ok","platform":"hermes-agent","version":…}``（无认证）；
- ``GET  /v1/capabilities``              → Bearer 认证；``features.run_submission / run_status /
  run_events_sse / run_stop / run_steer / run_approval_response`` 布尔广告；
- ``POST /v1/runs``                      → ``{"input": …}`` → **202** ``{"run_id":"run_<hex>","status":"started"}``；
- ``GET  /v1/runs/{id}``                 → ``{"object":"hermes.run","run_id","status","created_at",
  "updated_at",…}``；status ∈ queued/running/waiting_for_approval/stopping/completed/cancelled/failed；
- ``GET  /v1/runs/{id}/events``          → SSE：``data: {json}\\n\\n`` 帧 + ``: keepalive`` 心跳 +
  ``: stream closed`` 关闭哨兵；事件词表 run.completed/run.failed/run.cancelled/
  approval.request/approval.responded/tool.started/tool.completed/message.delta/
  reasoning.available/run.steered；
- ``POST /v1/runs/{id}/approval``        → ``{"choice":"once|session|always|deny"}`` → 200
  ``{"object":"hermes.run.approval_response",…}`` / 400 invalid / 409 not_pending；
- ``POST /v1/runs/{id}/stop``            → 200 ``{"run_id","status":"stopping"}`` —— **stop 成功不是
  CANCELLED**；权威终态只来自 status 轮询 / SSE run.cancelled。

安全边界（任务书 §5 + 16C 约束）：

- **默认仅 loopback**：base_url 必须是 ``http://127.0.0.1|localhost|::1[:port]``；userinfo
  （URL 内凭证）、query、fragment、非 http scheme、非空路径一律构造期拒绝；
- **follow_redirects=False**：任何 3xx 视为协议错误（非本地 redirect fail-closed）；
- API key 只经构造注入、只进 ``Authorization: Bearer`` 头；绝不入契约、绝不入日志/错误文本
  （错误文本过本地脱敏）；
- 端点封闭集：本模块只请求上列 7 个 method+path；run_id 进入 URL 前过词法校验（防路径注入）；
- **不发送 Persona/SOUL/Memory**：submit 只携带 ``canonical_user_request`` 文本；
- **completed ≠ VERIFIED**：Hermes 终态一律映射 16B ``run.completed`` 等 BackendEvent，
  16E reducer 折算 ``BACKEND_DONE_UNVERIFIED``；本模块不产生任何验证语义；
- **断线零重复 submit**：submit 幂等账本按 contract_id 拥有 correlation（同 id 同 hash 幂等
  返回既有 handle，同 id 异 hash 类型化冲突）；events/reconcile 路径零 POST /v1/runs；
- **approval 只走 16D 公开接口**：SSE approval.request → ``broker.get_or_create_request``
  （producer 面）；决议只消费 ``broker.wait_for_resolution`` 的**真实 Furina 决议**；
  转发 choice 只允许 ``once``/``deny``——**绝不发送 always/session**（不放宽 16D 决议）；
  不伪造 USER evidence、不签发 grant/permit、不触碰 broker private 字段；
- ``hermes proxy`` 不注册、CLI 仅诊断、webhook 不作为结果通道：本模块没有任何对应代码路径。

全部 buffer 有硬上限（SSE 行 256 KiB、单事件 payload 有界、轮询有界窗口/间隔）；
资源显式清理（response/client 上下文关闭）；健康/能力探针正负结果同 TTL 缓存。
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from furina.agent.approval import ApprovalBroker, ApprovalStateError
from furina.agent.approval.models import ApprovalDecisionKind, ResolutionStatus
from furina.agent.permission import Permission
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
_PATH_RUNS = "/v1/runs"
_PATH_RUN = "/v1/runs/{run_id}"
_PATH_EVENTS = "/v1/runs/{run_id}/events"
_PATH_APPROVAL = "/v1/runs/{run_id}/approval"
_PATH_STOP = "/v1/runs/{run_id}/stop"

#: 必须为 True 的 capabilities 广告特征（广告是必要条件，非充分——另有主动握手）。
_REQUIRED_FEATURES = ("run_submission", "run_status", "run_events_sse",
                      "run_stop", "run_approval_response")

#: Hermes 运行状态词表（status 轮询实测/源码对齐）。
_HERMES_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

#: SSE 行 buffer 硬上限（单帧超限 = 帧定界不可信 → fail-closed 断流）。
_MAX_SSE_LINE_BYTES = 256 * 1024
#: 单事件 payload 硬上限（交付 16E 前的预界；16E 信封仍有自己的预算）。
_MIN_EVENT_BYTES = 1024
_MAX_EVENT_BYTES = 1 << 20

#: 数值上界（防呆：一切超时/窗口必须有界）。
_MAX_TIMEOUT_SECONDS = 3600.0

#: 秘密值形态脱敏（本地最小实现；错误文本入 typed error 前先过此处）。
_SECRET_TEXT_RE = re.compile(
    r"(?i)(?<![a-z0-9_])((?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|private[_-]?key|auth[_-]?token|password|passwd|pwd|"
    r"secret|token|cookie|authorization)\s*[\"']?[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s\"'{}\[\]();,]+))")
_BEARER_TEXT_RE = re.compile(r"(?i)(?<![a-z0-9_])(bearer|basic)\s+[^\s\"'{}\[\]();,]+")


def _redact_text(text: str) -> str:
    """错误文本最小脱敏：键值秘密形态与 Bearer 凭证形态替换为 [REDACTED]。"""
    text = _SECRET_TEXT_RE.sub("[REDACTED]", text)
    text = _BEARER_TEXT_RE.sub(r"\1 [REDACTED]", text)
    return text


# ---------------------------------------------------------------------------
# 类型化错误（全部 BackendError 子类；fail-closed，绝不静默换路径）
# ---------------------------------------------------------------------------
class HermesConfigurationError(BackendError):
    """构造配置非法（非 loopback / URL 凭证 / 非法数值 / broker 缺失）。"""


class HermesTransportError(BackendError):
    """传输层失败（连接/超时/认证拒绝/限流）；不含任何秘密文本。"""


class HermesProtocolError(BackendError):
    """协议坏响应（形状/身份/状态词表/redirect 不合 16C 实测契约）。"""


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
        port = parts.port
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


def _redact_body_snippet(body: str, *, cap: int = 200) -> str:
    return _redact_text(str(body))[:cap]


# ---------------------------------------------------------------------------
# 内部 run 记录（进程内 correlation 账本；16H 之前无任何持久化）
# ---------------------------------------------------------------------------
class _RunRecord:
    """hermes run_id → 契约身份 + 审批 correlation（进程内；无持久化）。"""

    __slots__ = ("contract_id", "content_hash", "approval_keys", "stopped")

    def __init__(self, contract_id: str, content_hash: str) -> None:
        self.contract_id = contract_id
        self.content_hash = content_hash
        #: (tool, command 预览) → 16D approval_id（同一步重复 approval.request 幂等复用）
        self.approval_keys: Dict[Tuple[str, str], str] = {}
        self.stopped = False


# ---------------------------------------------------------------------------
# HermesExecutionBackend
# ---------------------------------------------------------------------------
class HermesExecutionBackend(ExecutionBackend):
    """Hermes API Server Runs 面适配器（16B ExecutionBackend conformance）。

    - ``probe``：/health + /v1/capabilities（Bearer）+ runs 状态面 404 握手三段
      **主动握手**；正负结果同 TTL 缓存；认证失败/坏载荷/矛盾广告/超时 fail-closed；
    - ``submit``：最小 projection（仅 canonical_user_request 文本）→ POST /v1/runs；
      幂等账本由本 backend 拥有（Hermes 不是幂等所有者）；
    - ``events``：SSE → 16B BackendEvent 流（16E 拥有规范化/状态机）；断线 →
      status 轮询 reconcile，**绝不重复 submit**；不可恢复 → transport.disconnected
      （16E UNKNOWN 策略边界）；
    - ``stop``：POST stop 只请求；**不产生 CANCELLED**（权威终态只来自 Hermes）；
    - ``resolve_approval``：等待 16D 真实决议 → 只转发 ``once``/``deny``。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        approval_broker: ApprovalBroker,
        capability_ids: Tuple[str, ...] = (),
        probe_ttl_seconds: float = 30.0,
        max_concurrent_runs: int = 1,
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
        if (isinstance(max_concurrent_runs, bool)
                or not isinstance(max_concurrent_runs, int) or max_concurrent_runs < 1
                or max_concurrent_runs > 1024):
            raise HermesConfigurationError(
                f"max_concurrent_runs 必须是 1..1024 的 int，得到 {max_concurrent_runs!r}")
        if (isinstance(max_event_bytes, bool) or not isinstance(max_event_bytes, int)
                or not (_MIN_EVENT_BYTES <= max_event_bytes <= _MAX_EVENT_BYTES)):
            raise HermesConfigurationError(
                f"max_event_bytes 必须是 {_MIN_EVENT_BYTES}..{_MAX_EVENT_BYTES} 的 int，"
                f"得到 {max_event_bytes!r}")
        self._endpoint = endpoint
        self._api_key = api_key
        self._broker = approval_broker
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
            capability_ids=tuple(capability_ids),
            supports_events=True,
            supports_stop=True,
            supports_resolve_approval=True,
            max_concurrent_runs=max_concurrent_runs,
            workspace_scoped=False,
        )
        self._lock = threading.RLock()
        self._runs: Dict[str, _RunRecord] = {}
        self._contract_index: Dict[str, Tuple[str, str]] = {}   # contract_id -> (run_id, content_hash)
        self._probe_cache: Optional[BackendHealth] = None
        self._client: Optional[httpx.Client] = None

    # -- 身份与能力 --------------------------------------------------------------
    @property
    def descriptor(self) -> BackendDescriptor:
        return self._descriptor

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

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

    # -- 错误文本纪律 ------------------------------------------------------------
    @staticmethod
    def _transport_failure(stage: str, exc: Exception) -> HermesTransportError:
        return HermesTransportError(
            f"hermes {stage} 传输失败: {type(exc).__name__}（细节脱敏）")

    def _require_json_object(self, stage: str, response: httpx.Response) -> Dict[str, Any]:
        """2xx JSON object 严格解析；3xx/非 2xx/坏 JSON 一律类型化协议错误。"""
        if 300 <= response.status_code < 400:
            raise HermesProtocolError(
                f"hermes {stage} 返回 redirect {response.status_code}"
                "（非本地重定向 fail-closed）")
        if response.status_code // 100 != 2:
            snippet = _redact_body_snippet(response.text)
            raise HermesTransportError(
                f"hermes {stage} HTTP {response.status_code}: {snippet}")
        try:
            body = response.json()
        except Exception as exc:
            raise HermesProtocolError(
                f"hermes {stage} 响应不是合法 JSON: {type(exc).__name__}") from exc
        if not isinstance(body, dict):
            raise HermesProtocolError(
                f"hermes {stage} 响应必须是 JSON object，得到 {type(body).__name__}")
        return body

    # -- 发现：主动握手 probe -----------------------------------------------------
    def probe(self) -> BackendHealth:
        """主动握手健康事实（/health + /capabilities + runs 404 握手）；正负结果同 TTL 缓存。"""
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
        # 2) /v1/capabilities（Bearer；广告是必要条件）
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
        features = body.get("features")
        if not isinstance(features, Mapping):
            return _fail("capabilities_features_missing")
        for name in _REQUIRED_FEATURES:
            if features.get(name) is not True:
                return _fail(f"capability_missing:{name}")
        # 3) runs 状态面主动握手：必定不存在的 probe run_id → 404 run_not_found
        probe_run_id = f"prb_{uuid.uuid4().hex}"
        try:
            resp = client.get(_PATH_RUN.format(run_id=probe_run_id))
        except Exception as exc:
            return _fail(f"runs_unreachable:{type(exc).__name__}", reachable=False)
        if resp.status_code == 401:
            return _fail("auth_rejected")
        if resp.status_code != 404:
            return _fail("runs_handshake_contradiction")
        try:
            body = resp.json()
        except Exception:
            return _fail("runs_handshake_bad_response")
        if not isinstance(body, dict):
            return _fail("runs_handshake_bad_response")
        err = body.get("error")
        if not isinstance(err, Mapping) or err.get("code") != "run_not_found":
            return _fail("runs_handshake_contradiction")
        return BackendHealth(installed=True, reachable=True, healthy=True,
                             checked_at=now, reason="", expiry=expiry)

    # -- 执行：submit（幂等账本在本 backend，Hermes 不是幂等所有者） -----------------
    def submit(self, contract_projection: Mapping[str, Any], *,
               run_id: Optional[str] = None) -> BackendRunHandle:
        request, contract_id, content_hash, allowed_caps = self._extract_projection(
            contract_projection)
        if not set(allowed_caps).issubset(set(self._capabilities.capability_ids)):
            raise BackendScopeViolation(
                f"projection.allowed_capabilities {sorted(allowed_caps)} 超出本 backend "
                f"显式声明 {sorted(self._capabilities.capability_ids)}"
                "（backend 不能诚实承诺未声明的能力）")
        with self._lock:
            existing = self._contract_index.get(contract_id)
            if existing is not None:
                prior_run, prior_hash = existing
                if prior_hash == content_hash:
                    # 幂等重放：同契约 → 同 handle，**零重复 submit**。
                    return BackendRunHandle(backend_id=BACKEND_ID, run_id=prior_run,
                                            correlation=contract_id)
                raise BackendScopeViolation(
                    f"contract_id {contract_id!r} 已绑定不同内容摘要"
                    f"（old={prior_hash[:12]}… new={content_hash[:12]}…）："
                    "冲突而非更新，拒绝重复提交")
        client = self._get_client()
        try:
            resp = client.post(_PATH_RUNS, json={"input": request})
        except Exception as exc:
            raise self._transport_failure("submit", exc) from exc
        # 零 fallback、零重试：非 202（含 3xx/401/429/5xx）一律 fail-closed。
        body = self._require_json_object("submit", resp)
        if resp.status_code != 202:
            raise HermesProtocolError(
                f"hermes submit 必须 202，得到 {resp.status_code}（实测契约）")
        hermes_run_id = body.get("run_id")
        status = body.get("status")
        if not isinstance(hermes_run_id, str) or not _RUN_ID_RE.match(hermes_run_id):
            raise HermesProtocolError(f"hermes submit run_id 非法: {hermes_run_id!r}")
        if status != "started":
            raise HermesProtocolError(f"hermes submit status 必须 'started'，得到 {status!r}")
        with self._lock:
            # 双检：并发 submit 同契约时账本只保留首个（后到者视为幂等重放）。
            existing = self._contract_index.get(contract_id)
            if existing is not None:
                prior_run, prior_hash = existing
                if prior_hash == content_hash:
                    return BackendRunHandle(backend_id=BACKEND_ID, run_id=prior_run,
                                            correlation=contract_id)
                raise BackendScopeViolation(
                    f"contract_id {contract_id!r} 已绑定不同内容摘要（并发冲突）")
            self._contract_index[contract_id] = (hermes_run_id, content_hash)
            self._runs[hermes_run_id] = _RunRecord(contract_id, content_hash)
        return BackendRunHandle(backend_id=BACKEND_ID, run_id=hermes_run_id,
                                correlation=contract_id)

    @staticmethod
    def _extract_projection(projection: Mapping[str, Any]
                            ) -> Tuple[str, str, str, Tuple[str, ...]]:
        """只读 projection 严格解析；无法准确表达 → BackendScopeViolation（submit 前 fail-closed）。"""
        if not isinstance(projection, Mapping):
            raise BackendScopeViolation(
                f"contract_projection 必须是 Mapping，得到 {type(projection).__name__}")
        request = projection.get("canonical_user_request")
        if not isinstance(request, str) or not request.strip():
            raise BackendScopeViolation("projection.canonical_user_request 缺失或非法")
        contract_id = projection.get("contract_id")
        if not isinstance(contract_id, str) or not contract_id.strip():
            raise BackendScopeViolation("projection.contract_id 缺失或非法")
        content_hash = projection.get("content_hash")
        if not isinstance(content_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            raise BackendScopeViolation("projection.content_hash 缺失或非法（64 位小写 hex）")
        allowed_backends = projection.get("allowed_backends") or ()
        if BACKEND_ID not in {str(b).strip() for b in allowed_backends}:
            raise BackendScopeViolation(
                f"projection.allowed_backends 不含 '{BACKEND_ID}'（契约不允许本 backend）")
        caps_raw = projection.get("allowed_capabilities") or ()
        caps = tuple(str(c).strip() for c in caps_raw if str(c).strip())
        if not caps:
            raise BackendScopeViolation("projection.allowed_capabilities 为空")
        # 诚实能力边界（capabilities.workspace_scoped=False）：本 backend 在 Hermes 专属
        # profile/workspace 执行，不执行 Furina 路径 scope —— 携带路径 scope 的契约
        # 一律 submit 前拒绝（router 的 workspace_incompatible 之外的直接面 fail-closed）。
        ws = projection.get("workspace_scope") or {}
        if isinstance(ws, Mapping):
            if (tuple(ws.get("read_roots") or ()) or tuple(ws.get("write_roots") or ())):
                raise BackendScopeViolation(
                    "projection.workspace_scope 携带路径 scope：hermes backend 不执行"
                    " Furina 路径 scope（workspace_scoped=False，诚实声明）")
        # 最小 projection：只发送请求文本。Persona/SOUL/Memory/预算/验证判据一概不出域。
        return request, contract_id.strip(), content_hash, caps

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
        # 主循环：SSE 订阅 → 断线 reconcile（绝不重提 submit）。
        while True:
            terminal_emitted = False
            for event in self._consume_sse(run_handle.run_id, record):
                yield event
                if event.event_type in ("run.completed", "run.failed", "run.cancelled"):
                    terminal_emitted = True
            if terminal_emitted:
                return
            # SSE 结束但未达权威终态（断线 / 404 传输缓冲被清）→ status 轮询 reconcile。
            for event in self._reconcile_by_status(run_handle.run_id):
                yield event
                if event.event_type in ("run.completed", "run.failed", "run.cancelled"):
                    return
                if event.event_type == "transport.disconnected":
                    return

    def _lifecycle_sync(self, run_id: str) -> Iterator[BackendEvent]:
        """权威 status 记录 → 最小生命周期前缀（queued[/running]）。

        只使用 Hermes 权威 status 记录与源码保证的次序事实（run 创建即 queued，
        running 先于一切 tool/approval 活动）；completed/failed 必然经过 running；
        cancelled 可能发生在 queued 阶段（不补 running）。终态种类绝不在此臆造。
        """
        client = self._get_client()
        try:
            resp = client.get(_PATH_RUN.format(run_id=run_id))
        except Exception:
            return
        if resp.status_code != 200:
            return
        try:
            body = resp.json()
        except Exception:
            return
        status = body.get("status") if isinstance(body, dict) else None
        if status in ("queued", "running", "waiting_for_approval", "stopping",
                      "completed", "failed", "cancelled"):
            yield self._make_event(run_id, "queued", {"source": "lifecycle_sync"})
            if status in ("running", "waiting_for_approval", "stopping",
                          "completed", "failed"):
                yield self._make_event(run_id, "running", {"source": "lifecycle_sync"})

    def _make_event(self, run_id: str, event_type: str, payload: Mapping[str, Any]) -> BackendEvent:
        return BackendEvent(backend_id=BACKEND_ID, run_id=run_id,
                            event_type=event_type, payload=dict(payload))

    def _consume_sse(self, run_id: str, record: _RunRecord) -> Iterator[BackendEvent]:
        """订阅一次 SSE 流并逐帧交付 BackendEvent；帧界/身份/大小全部 fail-closed。"""
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
            data_lines: List[str] = []
            try:
                for chunk in response.iter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > _MAX_SSE_LINE_BYTES:
                        # 帧定界不可信：fail-closed 断流（资源即释；由 reconcile 接管）。
                        yield self._make_event(run_id, "protocol.error",
                                               {"reason": "sse_line_over_limit"})
                        return
                    while b"\n" in buffer:
                        raw_line, _, rest = bytes(buffer).partition(b"\n")
                        buffer = bytearray(rest)
                        line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
                        if line.startswith(":"):
                            continue   # 心跳 / 关闭哨兵：非权威帧标记，绝不折算状态
                        if line.startswith("data:"):
                            data_lines.append(line[5:].strip())
                            if sum(len(s) for s in data_lines) > self._max_event_bytes:
                                data_lines = []
                                yield self._make_event(run_id, "protocol.error",
                                                       {"reason": "sse_event_over_limit"})
                            continue
                        if not line:
                            if data_lines:
                                event = self._dispatch_frame(run_id, record, "\n".join(data_lines))
                                data_lines = []
                                if event is not None:
                                    yield event
                        # 其余非空行（event:/id:/retry: 等）——本端点实测不存在，忽略。
                if data_lines:
                    event = self._dispatch_frame(run_id, record, "\n".join(data_lines))
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
        if token == "approval.request":
            approval_id = self._open_16d_approval(run_id, record, frame)
            if approval_id is None:
                return self._make_event(run_id, "protocol.error",
                                        {"reason": "approval_forwarding_failed"})
            payload = {**payload, "approval_id": approval_id}
        return self._make_event(run_id, token.strip(), payload)

    # -- 断线 reconcile：status 轮询（零重复 submit；有界窗口） ----------------------
    def _reconcile_by_status(self, run_id: str) -> Iterator[BackendEvent]:
        client = self._get_client()
        deadline = self._now_fn() + self._poll_budget
        reconnected_sent = False
        stopping_sent = False
        approval_gap_sent = False
        while self._now_fn() < deadline:
            try:
                resp = client.get(_PATH_RUN.format(run_id=run_id))
            except Exception:
                time.sleep(self._poll_interval)
                continue
            if resp.status_code == 404:
                # 终态记录已被 Hermes 清扫（终态 + TTL 3600s 后）：终态种类不可权威获知
                # → UNKNOWN 策略边界（绝不臆造终态、绝不重复 submit）。
                yield self._make_event(run_id, "transport.disconnected",
                                       {"reason": "run_record_swept"})
                return
            if resp.status_code == 401:
                yield self._make_event(run_id, "transport.disconnected",
                                       {"reason": "auth_rejected"})
                return
            if resp.status_code != 200:
                time.sleep(self._poll_interval)
                continue
            try:
                body = resp.json()
            except Exception:
                time.sleep(self._poll_interval)
                continue
            if not isinstance(body, dict):
                time.sleep(self._poll_interval)
                continue
            status = body.get("status")
            if status in ("completed", "failed", "cancelled"):
                payload = {k: body[k] for k in
                           ("output", "usage", "error") if k in body}
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
    def _open_16d_approval(self, run_id: str, record: _RunRecord,
                           frame: Mapping[str, Any]) -> Optional[str]:
        """approval.request → broker.get_or_create_request（producer 公开面）；幂等复用。

        绝不伪造 USER evidence、绝不签发 grant/permit；决议由 Furina 决策面
        （broker owner）做出，本方法只建立请求。
        """
        tool = str(frame.get("tool") or "").strip() or "hermes.remote_tool"
        preview = str(frame.get("preview") or frame.get("command") or "")[:200]
        key = (tool, preview)
        with self._lock:
            cached = record.approval_keys.get(key)
        if cached is not None:
            return cached
        try:
            request, _created = self._broker.get_or_create_request(
                contract_id=record.contract_id,
                run_id=run_id,
                tool=tool,
                capability="hermes.remote",
                args={"command": frame.get("command")} if frame.get("command") else None,
                reason=preview,
                risk_level=Permission.L2_HIGH_RISK,
                requested_scope=(),
                provenance="hermes_adapter",
                policy_kind="approval_required_each_step",
                contract_hash=record.content_hash,
            )
        except ApprovalStateError:
            return None
        with self._lock:
            record.approval_keys[key] = request.approval_id
        return request.approval_id

    def resolve_approval(self, approval_ref: str) -> Dict[str, Any]:
        """等待 16D 真实决议并转发 Hermes（choice 只允许 once/deny；绝不 always/session）。

        - ``approval_ref`` 必须是本 backend 经 16D 建立过的 approval_id（身份精确绑定）；
        - Furina 决议 APPROVE_ONCE / APPROVE_SESSION → ``once``（会话级决议**收窄**为
          单步转发，绝不放宽到 Hermes session/always）；
        - DENY / TIMEOUT / REVOKED / 未决（LATE/UNKNOWN）→ ``deny``（fail-closed）；
        - Hermes 409 approval_not_pending → resolved=0 类型化返回（非错误）。
        """
        if not self.capabilities.supports_resolve_approval:
            raise BackendCapabilityError("hermes 未声明 supports_resolve_approval")
        if not isinstance(approval_ref, str) or not approval_ref.strip():
            raise HermesProtocolError("approval_ref 必须是非空 str")
        approval_id = approval_ref.strip()
        with self._lock:
            located = None
            for run_id, record in self._runs.items():
                for key, aid in record.approval_keys.items():
                    if aid == approval_id:
                        located = (run_id, record, key)
                        break
                if located is not None:
                    break
        if located is None:
            raise HermesProtocolError(
                f"未知 approval_ref: {approval_id!r}（仅接受本 backend 经 16D 建立的审批）")
        run_id, _record, _key = located
        resolution = self._broker.wait_for_resolution(approval_id,
                                                      timeout=self._approval_wait)
        approved = bool(resolution.ok) and resolution.decision in (
            ApprovalDecisionKind.APPROVE_ONCE, ApprovalDecisionKind.APPROVE_SESSION)
        choice = "once" if approved else "deny"
        client = self._get_client()
        try:
            resp = client.post(_PATH_APPROVAL.format(run_id=run_id),
                               json={"choice": choice})
        except Exception as exc:
            raise self._transport_failure("approval", exc) from exc
        if resp.status_code == 409:
            # Hermes 侧已无挂起审批（已解析/已过期）：类型化 no-op，绝不重试。
            return {"choice": choice, "resolved": 0,
                    "resolution_status": str(resolution.status.value
                                              if isinstance(resolution.status, ResolutionStatus)
                                              else resolution.status)}
        body = self._require_json_object("approval", resp)
        if resp.status_code != 200 or body.get("object") != "hermes.run.approval_response" \
                or body.get("run_id") != run_id:
            raise HermesProtocolError("hermes approval 响应形状非法（实测契约）")
        resolved = body.get("resolved")
        if isinstance(resolved, bool) or not isinstance(resolved, int) or resolved < 0:
            raise HermesProtocolError(f"hermes approval resolved 非法: {resolved!r}")
        return {"choice": choice, "resolved": resolved,
                "resolution_status": str(resolution.status.value
                                         if isinstance(resolution.status, ResolutionStatus)
                                         else resolution.status)}
