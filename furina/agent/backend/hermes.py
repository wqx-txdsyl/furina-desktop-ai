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

安全边界（任务书 §5 + 16C Reviewer Patch 1/2 约束）：

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
  content_hash **完整性摘要**复核（缺字段/未知字段/摘要与内容不符 submit 前拒绝）；
  content_hash 是 integrity hash，**不声明 signature/授权真实性**——授权真实性来自构造期
  注入的可信 contract authorizer（contract_id + content_hash 精确确认该契约已由组合根
  授权；未知 id、hash 不同、authorizer 异常或返回非 True → submit 前拒绝、零 HTTP）；
  契约 allowed_capabilities 必须与本 backend 不可变 capability envelope **封闭相等**
  （不只是子集）；
- **profile/toolset 精确封闭（Patch 2）**：构造期冻结不可变 ``expected_profile_tools``
  （每个 expected tool 必须有 tool→capability 归属、归属 capability 集与 envelope 封闭
  一致）；成功 probe 必须同时满足 ``capabilities.model == expected_profile_identity``、
  ``toolsets.platform == api_server``、enabled 工具全部合法非空 str、实际 enabled 集 ==
  expected 集**精确相等**（多/少/未知/坏类型一律 unhealthy）；submit 要求最近一次 probe
  healthy、未过期且快照精确匹配——未 probe / probe 失败 / probe 过期 → 零 POST
  （submit 不自动补 probe）；
- **completed ≠ VERIFIED**：Hermes 终态一律映射 16B ``run.completed`` 等 BackendEvent，
  16E reducer 折算 ``BACKEND_DONE_UNVERIFIED``；本模块不产生任何验证语义；
- **断线零重复 submit**：submit 幂等账本按 contract_id 原子 reservation（同 id 同 hash
  幂等返回既有 handle，同 id 异 hash 类型化冲突；POST 已发出而结果不确定 → reservation
  中毒，绝不自动重提）；**run 账本容量在 POST 前原子预留**（容量满 → 零 POST）；202 返回
  的 run_id 已属另一契约 → 不覆盖既有归属（原 owner/槽位/事件归属不变），本契约 reservation
  中毒 + typed conflict；events/stop 校验 ``handle.correlation == 契约 id``；events/
  reconcile 路径零 POST /v1/runs；
- **approval 只走 16D 四层 Gate（Reviewer Patch 3）**：SSE approval.request 的 tool
  必须通过**工具面三重封闭**（tool ∈ 最近 probe 快照 / 构造期 expected_profile_tools /
  封闭 tool→capability 映射）且映射 capability ∈ 契约 allowed_capabilities，否则
  **自动 deny（fail-closed，不向用户制造 16D 审批请求）**；此后经**对应契约的
  ApprovalGate**（构造期注入 ``approval_gates: contract_id → ApprovalGate``）四层判定
  （WorkContract scope ∩ 实时 PermissionManager decision ∩ explicit approval/grant ∩
  backend capability）——``permission_decider``（构造期注入，签名
  (tool, capability, raw_args, contract_id, run_id) → PermissionDecision）返回**真实
  PermissionDecision**（decider 缺失/异常/非 PermissionDecision/granted=false 一律
  deny，绝不手造 PM 结果）；Gate 的 ``check_step`` 使用 submit 账本冻结的**完整
  WorkContract** + **真实原始 args** + 实时 PermissionDecision + 冻结 capability
  envelope，risk 下界 L2（PM 结果仍为下界上限，调用方不得降级）、wait_for_approval=
  false；**仅 APPROVAL_PENDING 建立待审批记录**（approval 账本容量/预留/入账封闭
  状态机，并发 cap=1 最终索引 ≤1）；**resolve 时重新取得实时 PermissionDecision 并
  再次调用同一 Gate.check_step**——只有 GateResult=ALLOW 且携带 permit、随后
  **主 broker**（构造期注入 ``approval_broker``）公开 producer API
  ``self._broker.consume_permit`` 在发送 once 的**立即边界**原子复核（permit 属主
  broker 台账 + contract_id/hash + run_id + tool + capability + 原始 args +
  approval/grant 状态，全部在 broker 唯一消费锁内重查）+ 单点提交成功，才
  POST once；Gate 任何 DENY（PM 降级/拒绝、契约/hash 不匹配、撤销、超时、已消费）、
  permit 消费失败 → fail-closed deny，绝不发送 once；**本适配器不直接持有/注册/调用
  PermitIssuer**（permit 签发只存在于 Gate 内部，Patch 3 删除 issuer 注入面），
  **最终消费也绝不 ``gate.consume_permit``**（Reviewer Patch 6 blocker 一：Gate 恒
  委托其自身 broker——foreign Gate 会把 permit 消费到 foreign broker 台账，构成
  跨 broker TOCTOU；两处真实远端副作用边界——新操作 grant-covered once 与
  resolve 后 once——的 permit 一律由主 broker 原子消费，foreign Gate 签发的 permit
  即使 grant_id/approval_id/契约/tool/capability/scope 全同且主 broker 存在同名
  有效授权，也因 permit 不在主 broker 台账被拒绝，零 once）；
  APPROVE_SESSION 决议仍只收窄转发 once（不放宽 16D 决议）；转发只允许
  ``once``/``deny``——**绝不发送 always/session**；同一 approval 只向 Hermes 转发一次
  （并发 resolve 单请求获胜；第二次调用 typed no-op）；``resolved==1`` 精确才声明成功；
  409 仅在错误码精确为 ``approval_not_pending`` 时视为 no-op；
- **approval 幂等/冻结/绑定（Reviewer Patch 4）**：相同 (run_id, tool, capability,
  完整原始 args) 操作身份 digest 的 approval.request 重投**幂等复用原 approval_id**
  （先于容量检查——不新建 broker request、不占审批容量、不发 deny；PENDING/已决议
  未 forward 交唯一 resolve 路径；已 forward 零再次 POST once/deny；并发相同操作
  in-flight 单飞只产生一个 approval_id）；resolve 只认真实 APPROVE_ONCE/
  APPROVE_SESSION 决议——DENY/TIMEOUT/REVOKED/CANCELLED/LATE/UNKNOWN/CONFLICT 一律
  固定 deny 且不触碰 Gate（**绝不因后出现的 session grant 升级**，不签发/不消费
  permit、零 once）；操作身份在帧时刻**严格递归 defensive copy**（非 JSON 值
  fail-closed），账本快照与事件 payload / permission_decider / Gate / permit 消费
  零共享嵌套引用，批准后只能消费帧时刻冻结的原操作；Gate 判定结果进入 adapter
  审批账本或产生 once 前（**含 resolve 边界**），必须经 16D **公开 API** 证明其
  产生于构造期注入的 approval_broker 且与真实操作**完整身份一致**（Patch 5
  blocker 一：仅"同名 ID 存在/激活"不构成证明——approval 经 claimed
  ApprovalRequest 字段独立重算（scope/risk/policy 不信任 Gate 自报）+ 主 broker
  ``matching_request`` 全身份查询（含 broker 密钥 HMAC operation_digest）、命中
  approval_id **精确等于** Gate 返回值；grant 经主 broker ``covering_grant``
  全匹配（契约/tool/capability/paths/write_paths）、有效 grant_id **精确等于**
  Gate 返回值；UUID 碰撞 / 换 args / 换 run_id / 换契约 hash / 换 scope 一律
  fail-closed deny：不进账本、不消费 permit、零 once、原记录不覆盖不串用；
  不触碰任何 _private 属性，frozen 16D 公开 API 可完整表达证明）；
  ``_deep_freeze_json`` 只接受真正 JSON 值域（tuple 不得静默转换为 list →
  ``approval_args_not_canonical``）；approval frame 的 tool **精确匹配**
  （零 strip 规范化）；content-type charset 参数**真正 token 校验**（拒绝重复
  charset/空值/引号/非法参数，只承诺实际践行的 UTF-8 解码）；
- **HTTP 严格边界（Patch 2 + Patch 3 收紧）**：只接受精确媒体类型
  ``application/json``（可带 ``; charset=…`` 参数；application/jsonp、
  text/application/json-evil、非 charset 参数一律拒绝；Patch 4：charset 值必须为
  合法 token 且只能声明本 adapter 实际践行的 UTF-8、拒绝重复 charset）；全部普通
  JSON 响应**流式/
  有界读取**（> 4 MiB 立即拒绝，超限内容不入异常）；**错误码/诊断片段读取同样有界
  （64 KiB；超限只留标记）且同样要求精确 application/json**——text/plain 承载的
  run_not_found/approval_not_pending 绝不当作已知错误码；单 chunk 在 extend **前**
  检查余量（绝不先分配超限内存）；读取中断绝不接受已读前缀（即使前缀恰好是合法
  JSON 也一律类型化拒绝）；
- ``hermes proxy`` 不注册、CLI 仅诊断、webhook 不作为结果通道：本模块没有任何对应代码路径。

全部 buffer 有硬上限（SSE 行 256 KiB、单事件 payload 有界、JSON body 有界、
run/contract/approval 账本硬容量满则 fail-closed 不淘汰）；资源显式清理
（response/client 上下文关闭）；健康/能力探针正负结果同 TTL 缓存。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Set, Tuple
from urllib.parse import urlsplit

import httpx

from furina.agent.agent_runtime import AgentRuntime
from furina.agent.approval import (
    ApprovalBroker,
    ApprovalDecisionKind,
    ApprovalGate,
    ApprovalRequest,
    ApprovalState,
    ApprovalStateError,
    AuthorizationGrant,
    GateVerdict,
    classify_step_paths,
)
from furina.agent.approval.models import ResolutionStatus
from furina.agent.permission import Permission, PermissionDecision
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
#: JSON endpoint 响应 body 硬上限（流式/有界读取；超限 = 协议错误，立即停止读取，
#: 超限内容绝不进入异常文本）。
_MAX_JSON_BODY_BYTES = 4 * (1 << 20)
#: 非 2xx 错误体读取硬上限（错误码/诊断片段同样有界；超限只留标记，不留内容）。
_MAX_ERROR_BODY_BYTES = 64 * 1024
#: 唯一合法 JSON 媒体类型（type/subtype 精确相等；参数仅容 charset=<token>）。
_JSON_MEDIA_TYPE = "application/json"
#: RFC 9110 token 词法（content-type 参数名与 charset 值的严格校验，Patch 4 blocker 六）。
_MEDIA_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
#: 本 adapter 实际践行的响应字符集（响应体一律严格 UTF-8 解码——声明任何其它
#: charset 都与实际解码方式矛盾，fail-closed 拒绝；Patch 4 blocker 六）。
_ALLOWED_CHARSET_VALUES = frozenset({"utf-8", "utf8"})

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


def _deep_freeze_json(value: Any, path: str = "$") -> Any:
    """严格递归 defensive copy（Patch 4 blocker 四；Patch 5 收紧值域声明）：仅接受
    真正 JSON 值域（dict / list / str / int / float / bool / None），键必须为 str；
    任何非 JSON 值（含非有限浮点与 **tuple**——JSON 文档不存在 tuple，不得静默
    转换为 list）→ HermesProtocolError fail-closed（调用方折为
    ``approval_args_not_canonical``）。输出树与输入树零共享嵌套引用（dict/list
    全部重建；标量不可变原样传递）。无 repr/default=str 兜底，异常文本只含路径
    与类型名（零原始值、零秘密导出）。"""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HermesProtocolError(
                f"审批操作参数含非有限数值（fail-closed）@ {path}")
        return float(value)
    if isinstance(value, Mapping):
        frozen: Dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise HermesProtocolError(
                    f"审批操作参数键非 str（fail-closed）@ {path}")
            frozen[k] = _deep_freeze_json(v, f"{path}.{k}")
        return frozen
    if isinstance(value, list):
        return [_deep_freeze_json(v, f"{path}[{i}]") for i, v in enumerate(value)]
    raise HermesProtocolError(
        f"审批操作参数含非 JSON 值（fail-closed；tuple 等 Python 扩展类型不得"
        f"静默转换）@ {path}: {type(value).__name__}")


def _operation_identity_digest(run_id: str, tool: str, capability: str,
                               op_args: Mapping[str, Any]) -> str:
    """完整审批操作身份 digest（Patch 4 blocker 二/三）：run_id + tool + capability +
    完整原始 canonical args 的确定性摘要（严格 JSON canonical、sort_keys、
    allow_nan=False）。幂等重投与并发单飞以 digest 为唯一身份键——任何
    command/args 差异 ⇒ 不同 digest ⇒ 不同操作。非 JSON 值 fail-closed。"""
    try:
        blob = json.dumps(
            {"run_id": run_id, "tool": tool, "capability": capability,
             "args": op_args},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise HermesProtocolError(
            "审批操作参数不可 canonical（非 JSON 值 fail-closed）") from exc
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 内部 run 记录 / submit reservation（进程内 correlation 账本；16H 之前无任何持久化）
# ---------------------------------------------------------------------------
class _RunRecord:
    """hermes run_id → 契约身份（进程内；无持久化；无审批缓存——审批身份唯一权威
    在 16D broker 的完整身份原子 get-or-create）。``contract`` 保留 submit 时经 16A
    校验的完整 WorkContract，供审批面 Gate 四层判定使用（Reviewer Patch 3）。"""

    __slots__ = ("contract_id", "content_hash", "allowed_capabilities", "stopped",
                 "slot_released", "contract")

    def __init__(self, contract_id: str, content_hash: str,
                 allowed_capabilities: Tuple[str, ...],
                 contract: Optional[WorkContract] = None) -> None:
        self.contract_id = contract_id
        self.content_hash = content_hash
        self.allowed_capabilities = tuple(allowed_capabilities)
        self.stopped = False
        self.slot_released = False
        self.contract = contract


class _ApprovalOpRecord:
    """approval_id → 帧时刻冻结的完整操作身份（run_id + tool + capability + 原始
    canonical operation args 的严格递归 defensive copy + 完整操作身份 digest）——
    resolve 边界 permit 签发/原子消费的唯一身份来源（禁止在转发时刻重新解释帧或
    改用 permit 自身字段自证）。Patch 4（blocker 四）：op_args 为 ``_deep_freeze_json``
    输出的深冻结副本，与帧 payload / permission_decider / Gate / permit 消费收到的
    副本零共享嵌套引用；批准后只能消费帧时刻冻结的原操作。"""

    __slots__ = ("run_id", "tool", "capability", "op_args", "digest")

    def __init__(self, run_id: str, tool: str, capability: str,
                 op_args: Mapping[str, Any], digest: str) -> None:
        self.run_id = run_id
        self.tool = tool
        self.capability = capability
        self.op_args = op_args   # 调用方必须已深冻结（_deep_freeze_json 输出）
        self.digest = digest


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
        expected_profile_tools: Iterable[str],
        tool_capability_map: Mapping[str, str],
        contract_authorizer: Callable[[str, str], bool],
        capability_ids: Tuple[str, ...] = (),
        approval_gates: Optional[Mapping[str, ApprovalGate]] = None,
        permission_decider: Optional[
            Callable[[str, str, Mapping[str, Any], str, str], PermissionDecision]
        ] = None,
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
            if tool != tool.strip() or cap != cap.strip():
                raise HermesConfigurationError(
                    f"tool_capability_map 键/值未规范化: {tool!r}→{cap!r}"
                    "（空白/未规范化名字一律拒绝）")
            if cap not in envelope:
                raise HermesConfigurationError(
                    f"tool_capability_map[{tool!r}] → {cap!r} 不在本 backend 显式 envelope "
                    f"{sorted(envelope)} 内（映射越权，构造期拒绝）")
            frozen_map[tool] = cap
        # -- expected profile tools（不可变）：probe 工具面封闭比对的构造期权威 ----------
        try:
            tools_materialized = tuple(expected_profile_tools)
        except TypeError as exc:
            raise HermesConfigurationError(
                f"expected_profile_tools 必须是 str 可迭代，得到 "
                f"{type(expected_profile_tools).__name__}") from exc
        if not tools_materialized:
            raise HermesConfigurationError(
                "expected_profile_tools 必须非空（dedicated profile 的完整 enabled 工具面；"
                "空工具面不可证明，拒绝构造）")
        seen_tools: Set[str] = set()
        for tool in tools_materialized:
            if not isinstance(tool, str) or not tool.strip():
                raise HermesConfigurationError(
                    f"expected_profile_tools 条目必须是非空 str，得到 {tool!r}")
            if tool != tool.strip():
                raise HermesConfigurationError(
                    f"expected_profile_tools 条目未规范化: {tool!r}"
                    "（空白/未规范化名字一律拒绝）")
            if tool in seen_tools:
                raise HermesConfigurationError(
                    f"expected_profile_tools 出现重复条目 {tool!r}（封闭集合语义，拒绝）")
            seen_tools.add(tool)
        unattributed = sorted(seen_tools - set(frozen_map))
        if unattributed:
            raise HermesConfigurationError(
                f"expected_profile_tools 中存在无 tool→capability 归属的工具 {unattributed}"
                "（每个 expected tool 都必须有封闭映射归属，构造期拒绝）")
        attributed = {frozen_map[t] for t in seen_tools}
        if attributed != set(envelope):
            raise HermesConfigurationError(
                f"expected 工具的 capability 归属集 {sorted(attributed)} 与本 backend "
                f"capability envelope {sorted(envelope)} 非封闭一致（每个 envelope 能力都必须"
                "由至少一个 expected tool 归属，且归属不得越出 envelope）")
        extra_mapped = sorted(set(frozen_map) - seen_tools)
        if extra_mapped:
            raise HermesConfigurationError(
                f"tool_capability_map 存在超出 expected_profile_tools 的映射键 {extra_mapped}"
                "（工具面必须精确封闭相等：set(映射键) == set(expected_profile_tools)，"
                "多/少/未知映射一律构造期拒绝）")
        # -- 可信 contract authorizer（组合根注入；submit 前按 id+integrity hash 精确确认）--
        if not callable(contract_authorizer):
            raise HermesConfigurationError(
                "contract_authorizer 必须是 callable（contract_id, content_hash）→ bool："
                "由可信组合根确认该契约已获授权；缺失即拒绝构造（integrity hash 不声明"
                "授权真实性）")
        # -- permit issuers 删除（Reviewer Patch 3）：本适配器不直接持有/注册/调用
        #    PermitIssuer——permit 签发只存在于 16D ApprovalGate 内部（四层判定 ALLOW
        #    后由 Gate 经内部 issuer 签发）；构造期只注入 ``contract_id → ApprovalGate``
        #    判定器与实时 ``permission_decider``（真实 PermissionManager 决策来源）。
        #    Reviewer Patch 6（blocker 一）：permit 的**最终消费**也绝不委托 Gate
        #    （``gate.consume_permit`` 恒转发 Gate 自身 broker——foreign Gate 会把
        #    permit 消费到 foreign broker 台账，跨 broker TOCTOU）；两处真实远端
        #    副作用边界（新操作 grant-covered once / resolve 后 once）一律由
        #    ``self._broker.consume_permit``（构造期注入的主 broker 公开 producer
        #    API）在唯一消费锁内复核并原子消费。--
        if approval_gates is not None and not isinstance(approval_gates, Mapping):
            raise HermesConfigurationError(
                f"approval_gates 必须是 contract_id → ApprovalGate Mapping 或 None，"
                f"得到 {type(approval_gates).__name__}")
        frozen_gates: Dict[str, ApprovalGate] = {}
        if approval_gates:
            for cid, gate in approval_gates.items():
                if not isinstance(cid, str) or not cid.strip():
                    raise HermesConfigurationError(f"approval_gates 键非法: {cid!r}")
                if not isinstance(gate, ApprovalGate):
                    raise HermesConfigurationError(
                        f"approval_gates[{cid!r}] 必须是 ApprovalGate（16D 四层判定器，"
                        "由可信组合根以 owner 线程经 broker.create_permit_issuer 创建的"
                        " issuer 构造），得到 "
                        f"{type(gate).__name__}")
                frozen_gates[cid] = gate
        if permission_decider is not None and not callable(permission_decider):
            raise HermesConfigurationError(
                "permission_decider 必须是 callable"
                "（tool, capability, raw_args, contract_id, run_id）→ PermissionDecision；"
                "缺失/非法 → 审批一律 fail-closed deny（绝不手造 PM 结果）")
        self._approval_gates: Dict[str, ApprovalGate] = frozen_gates
        self._permission_decider = permission_decider
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
        self._expected_profile_tools: Tuple[str, ...] = tuple(sorted(seen_tools))
        self._contract_authorizer = contract_authorizer
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
        self._runs_reserved = 0   # POST 前已预留、尚未入账的 run 槽位（容量原子预留）
        self._approval_ops: Dict[str, _ApprovalOpRecord] = {}   # approval_id → 操作身份
        #: 完整操作身份 digest → approval_id（Patch 4 blocker 二/三：幂等重投唯一
        #: 复用键；先于容量检查——重投绝不新建 broker request、不占容量、零 deny）。
        self._approval_op_index: Dict[str, str] = {}
        #: digest → in-flight Event（Patch 4：并发相同操作单飞——只有 leader 走
        #: Gate 判定，follower 等待后复用同一 approval_id）。
        self._approval_inflight: Dict[str, threading.Event] = {}
        self._approvals_reserved = 0   # broker 请求创建在途的容量预留（封闭状态机）
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

    @property
    def expected_profile_tools(self) -> Tuple[str, ...]:
        """构造期冻结的 expected profile 工具面（probe 精确比对的封闭基准；不可变）。"""
        return self._expected_profile_tools

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

    # -- HTTP 严格边界（Patch 2）：流式/有界读取 + 精确媒体类型 ----------------------
    def _open_stream(self, stage: str, method: str, path: str, *,
                     json_body: Optional[Mapping[str, Any]] = None
                     ) -> Tuple[httpx.Response, Any]:
        """打开流式请求（响应体绝不整体缓冲；调用方以 cm.__exit__ 显式关闭）。
        连接/发送失败 → HermesTransportError（POST 语义下"是否到达服务器"不可判，
        由调用方按其 reservation 状态机处置）。"""
        client = self._get_client()
        cm = client.stream(method, path,
                           json=dict(json_body) if json_body is not None else None)
        try:
            response = cm.__enter__()
        except Exception as exc:
            try:
                cm.__exit__(None, None, None)
            except Exception:
                pass
            raise self._transport_failure(stage, exc) from exc
        return response, cm

    @staticmethod
    def _close_stream(cm: Any) -> None:
        try:
            cm.__exit__(None, None, None)
        except Exception:
            pass

    def _bounded_body(self, response: httpx.Response, limit: int) -> bytes:
        """有界读取（Reviewer Patch 3 收紧）：

        - 单 chunk 在 ``extend`` **前**检查余量：``len(chunk) > remaining`` → 立即
          拒绝（绝不先分配超限内存；超限内容绝不进入异常文本/日志/保留缓冲）；
        - 读取过程任何异常（连接中断/超时/解码）→ 抛类型化 transport 错误，
          **绝不返回已读前缀**——即使前缀恰好是合法 JSON 也不得接受；
        - 超限 → 类型化 protocol 错误（消息固定形态，不含任何响应内容）。
        """
        buf = bytearray()
        remaining = limit
        try:
            for chunk in response.iter_bytes():
                if len(chunk) > remaining:
                    raise HermesProtocolError(
                        f"hermes 响应 body 超过硬上限 {limit} bytes（流式有界读取，"
                        "单 chunk 在 extend 前拒绝；超限内容不入异常）")
                buf.extend(chunk)
                remaining -= len(chunk)
        except HermesProtocolError:
            raise
        except Exception as exc:
            raise HermesTransportError(
                f"hermes 响应体读取中断（已读前缀即使合法也绝不接受，fail-closed）: "
                f"{type(exc).__name__}") from exc
        return bytes(buf)

    def _check_json_media_type(self, stage: str, response: httpx.Response) -> None:
        """精确媒体类型（Patch 4 blocker 六收紧）：type/subtype 必须 ==
        application/json（大小写不敏感）；参数**仅**允许 ``charset=<token>`` 且
        **真正校验 token**——参数名必须精确 ``charset``（RFC 9110 token 词法，
        零 OWS 容忍）、值必须为合法 token（拒绝空值/引号/空白/非法字符）、拒绝
        重复 charset 参数；且声明值必须是本 adapter 实际践行的 UTF-8（响应体一律
        严格 UTF-8 解码——声明其它 charset 即矛盾）。application/jsonp、
        text/application/json-evil、非 charset 参数一律类型化拒绝；
        ``application/json`` 与 ``application/json; charset=utf-8``（任意大小写）
        保持通过。"""
        raw = response.headers.get("content-type", "")
        parts = [p.strip() for p in raw.split(";")] if raw.strip() else []
        if not parts or not parts[0]:
            raise HermesProtocolError(
                f"hermes {stage} content-type 缺失，得到 {raw!r}")
        if parts[0].lower() != _JSON_MEDIA_TYPE:
            raise HermesProtocolError(
                f"hermes {stage} content-type 必须精确 '{_JSON_MEDIA_TYPE}'"
                f"（仅可带 charset 参数），得到 {raw!r}")
        seen_charset = False
        for param in parts[1:]:
            name, sep, value = param.partition("=")
            if not sep or not _MEDIA_TOKEN_RE.match(name) \
                    or name.lower() != "charset":
                raise HermesProtocolError(
                    f"hermes {stage} content-type 参数仅允许 charset=<token>，"
                    f"得到 {raw!r}")
            if seen_charset:
                raise HermesProtocolError(
                    f"hermes {stage} content-type 出现重复 charset 参数"
                    f"（fail-closed），得到 {raw!r}")
            seen_charset = True
            if not value or not _MEDIA_TOKEN_RE.match(value):
                raise HermesProtocolError(
                    f"hermes {stage} content-type charset 值必须是合法 token"
                    f"（拒绝空值/引号/空白/非法字符），得到 {raw!r}")
            if value.lower() not in _ALLOWED_CHARSET_VALUES:
                raise HermesProtocolError(
                    f"hermes {stage} content-type 声明 charset={value!r} 与本 adapter"
                    f" 严格 UTF-8 解码矛盾（fail-closed），得到 {raw!r}")

    def _read_json_object(self, stage: str, response: httpx.Response) -> Dict[str, Any]:
        """2xx 已确认的流式响应体严格解析：精确媒体类型 + 有界读取
        （> _MAX_JSON_BODY_BYTES 立即拒绝，超限内容不入异常；读取中断/前缀一律
        类型化拒绝）+ 严格 UTF-8/JSON object；任一违反 → 类型化协议错误。"""
        self._check_json_media_type(stage, response)
        raw = self._bounded_body(response, _MAX_JSON_BODY_BYTES)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise HermesProtocolError(
                f"hermes {stage} 响应不是合法 JSON: {type(exc).__name__}") from exc
        if not isinstance(body, dict):
            raise HermesProtocolError(
                f"hermes {stage} 响应必须是 JSON object，得到 {type(body).__name__}")
        return body

    def _read_error_payload(self, response: httpx.Response, *,
                            stage: str = "error") -> Tuple[Optional[str], str]:
        """非 2xx 错误体的**有界**读取与解析（Reviewer Patch 3 收紧）。

        - **普通/错误码 JSON 一律要求精确 application/json 媒体类型**（Patch 3）：
          text/plain 承载的 run_not_found / approval_not_pending **绝不**当作已知
          错误码——非严格媒体类型 → (None, 固定标记)，不读取、不保留错误体；
        - 错误体超 _MAX_ERROR_BODY_BYTES → (None, 固定标记)（内容不留存，不入
          异常文本/日志/缓冲）；
        - 读取中断 → (None, 固定标记)（已读前缀即使合法也不接受）；
        - JSON 严格解析，形状损坏 → code=None（绝不当作已知码吞掉）。
        """
        try:
            self._check_json_media_type(stage, response)
        except HermesProtocolError:
            return None, "[error body media type invalid]"
        try:
            raw = self._bounded_body(response, _MAX_ERROR_BODY_BYTES)
        except HermesProtocolError:
            return None, "[error body over limit]"
        except HermesTransportError as exc:
            return None, f"[error body unavailable: {type(exc).__name__}]"
        if not raw:
            return None, ""
        code: Optional[str] = None
        try:
            body = json.loads(raw.decode("utf-8"))
            if isinstance(body, dict):
                err = body.get("error")
                if isinstance(err, Mapping):
                    c = err.get("code")
                    code = c if isinstance(c, str) else None
        except Exception:
            code = None
        snippet = self._redact(raw.decode("utf-8", "replace"))[:200]
        return code, snippet

    def _error_code_of(self, response: httpx.Response, *,
                       stage: str = "error") -> Optional[str]:
        """404/409 特殊路径的真实错误码提取（严格媒体类型 + 有界读取；text/plain
        承载或形状损坏/超限/读取中断 → None，绝不当作已知码吞掉，绝不无界读取
        response.text/json）。"""
        code, _snippet = self._read_error_payload(response, stage=stage)
        return code

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

        # 1) /health（无认证面；流式有界读取）
        try:
            response, cm = self._open_stream("health", "GET", _PATH_HEALTH)
        except HermesTransportError as exc:
            return _fail(f"health_unreachable:{type(exc).__name__}", reachable=False)
        try:
            if response.status_code != 200:
                return _fail(f"health_http_{response.status_code}")
            try:
                body = self._read_json_object("health", response)
            except BackendError:
                return _fail("health_bad_response")
        finally:
            self._close_stream(cm)
        if body.get("status") != "ok" or body.get("platform") != "hermes-agent" \
                or not isinstance(body.get("version"), str) or not body.get("version"):
            return _fail("health_shape_contradiction")
        # 2) /v1/capabilities（Bearer；广告是必要条件 + profile identity 精确绑定）
        try:
            response, cm = self._open_stream("capabilities", "GET", _PATH_CAPABILITIES)
        except HermesTransportError as exc:
            return _fail(f"capabilities_unreachable:{type(exc).__name__}", reachable=False)
        try:
            if response.status_code == 401:
                return _fail("auth_rejected")
            if response.status_code != 200:
                return _fail(f"capabilities_http_{response.status_code}")
            try:
                body = self._read_json_object("capabilities", response)
            except BackendError:
                return _fail("capabilities_bad_response")
        finally:
            self._close_stream(cm)
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
        #    Patch 2：platform 必须 api_server；enabled 工具必须全部合法非空 str；
        #    实际工具面与构造期 expected_profile_tools **精确相等**（多/少/未知/坏
        #    类型一律 unhealthy）。
        try:
            response, cm = self._open_stream("toolsets", "GET", _PATH_TOOLSETS)
        except HermesTransportError as exc:
            return _fail(f"toolsets_unreachable:{type(exc).__name__}", reachable=False)
        try:
            if response.status_code == 401:
                return _fail("auth_rejected")
            if response.status_code != 200:
                return _fail(f"toolsets_endpoint_missing:{response.status_code}")
            try:
                body = self._read_json_object("toolsets", response)
            except BackendError:
                return _fail("toolsets_bad_response")
        finally:
            self._close_stream(cm)
        if body.get("object") != "list" or not isinstance(body.get("data"), list):
            return _fail("toolsets_shape_contradiction")
        if body.get("platform") != "api_server":
            return _fail("toolsets_platform_contradiction")
        enabled_tools: Set[str] = set()
        for entry in body["data"]:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("enabled"), bool):
                return _fail("toolsets_entry_contradiction")
            tools = entry.get("tools")
            if not isinstance(tools, list):
                return _fail("toolsets_tools_contradiction")
            if entry.get("enabled") is True:
                for tool in tools:
                    if not isinstance(tool, str) or not tool.strip():
                        return _fail("toolsets_tool_invalid")
                    enabled_tools.add(tool)
        expected_tools = set(self._expected_profile_tools)
        if enabled_tools != expected_tools:
            missing = sorted(expected_tools - enabled_tools)[:8]
            extra = sorted(enabled_tools - expected_tools)[:8]
            return _fail(f"toolset_surface_mismatch:"
                         f"missing={missing},extra={extra}")
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
                response, cm = self._open_stream(stage, method, path, json_body=json_body)
            except HermesTransportError as exc:
                return _fail(f"{stage}_unreachable:{type(exc).__name__}", reachable=False)
            try:
                if response.status_code == 401:
                    return _fail("auth_rejected")
                if response.status_code != 404:
                    return _fail(f"{stage}_endpoint_contradiction:{response.status_code}")
                if self._error_code_of(response, stage=stage) != "run_not_found":
                    return _fail(f"{stage}_handshake_contradiction")
            finally:
                self._close_stream(cm)
        with self._lock:
            self._profile_tools_snapshot = tuple(sorted(enabled_tools))
        return BackendHealth(installed=True, reachable=True, healthy=True,
                             checked_at=now, reason="", expiry=expiry)

    # -- 执行：submit（幂等账本在本 backend，Hermes 不是幂等所有者） -----------------
    def _require_fresh_healthy_probe(self) -> None:
        """submit 前置门（Patch 2）：最近一次 probe 必须 healthy 且未过期，且 profile/
        tool 快照与构造期 expected **精确匹配**。无任何 probe / probe 失败 / probe
        过期 → 类型化拒绝、零 POST（submit **不自动补 probe**——新鲜事实由调用方
        主动建立，submit 只消费既有事实）。"""
        now = self._now_fn()
        with self._lock:
            cached = self._probe_cache
            snapshot = self._profile_tools_snapshot
        if cached is None:
            raise HermesProtocolError(
                "submit 前必须先 probe（本 backend 无任何 probe 事实；fail-closed 零 POST）")
        if not cached.healthy:
            raise HermesProtocolError(
                f"最近一次 probe unhealthy（{cached.reason}）——submit 拒绝，零 POST")
        if now >= cached.expiry:
            raise HermesProtocolError(
                "最近一次 probe 已过期——submit 拒绝（不自动补 probe），零 POST")
        if snapshot != self._expected_profile_tools:
            raise HermesProtocolError(
                "probe 工具面快照与构造期 expected_profile_tools 不精确匹配"
                "——submit 拒绝，零 POST")

    def submit(self, contract_projection: Mapping[str, Any], *,
               run_id: Optional[str] = None) -> BackendRunHandle:
        contract = self._parse_contract(contract_projection)
        self._require_fresh_healthy_probe()
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
        # run 账本容量必须在 POST **前**原子预留（Patch 2）：容量满 → 零 POST。
        # 预留计数与账本同锁，len(runs) + reserved > cap 的窗口不存在。
        with self._lock:
            if len(self._runs) + self._runs_reserved >= self._max_tracked_runs:
                error = BackendScopeViolation(
                    f"run 账本硬容量已满（{self._max_tracked_runs}，POST 前预留失败，"
                    "零 POST；fail-closed 不淘汰既有记录）")
                self._settle_reservation_locked(contract.contract_id, reservation,
                                                error=error, remove=True)
                self._run_slots.release()
                raise error
            self._runs_reserved += 1
        try:
            try:
                response, cm = self._open_stream(
                    "submit", "POST", _PATH_RUNS,
                    json_body={"input": contract.canonical_user_request})
            except HermesTransportError as exc:
                # POST 已发出但结果不确定（连接/读/超时无法区分是否到达服务器）→
                # reservation 中毒，绝不自动重提（防 Hermes 双跑）。
                error = HermesTransportError(
                    f"hermes submit 结果不确定（{exc}）：是否已到达服务器不可判；"
                    "同 contract 后续 submit 绝不自动重提")
                self._settle_reservation(contract.contract_id, reservation,
                                         error=error, remove=False)
                raise error from exc
            try:
                return self._submit_response_to_handle(contract, reservation, response)
            finally:
                self._close_stream(cm)
        except BaseException:
            # 失败/不确定路径：归还 POST 前预留的 run 槽位计数与并发信号量
            #（成功路径在 _submit_response_to_handle 内已归还计数并保留信号量）。
            with self._lock:
                self._runs_reserved -= 1
            self._run_slots.release()
            raise

    def _submit_response_to_handle(self, contract: WorkContract,
                                   reservation: _SubmitReservation,
                                   response: httpx.Response) -> BackendRunHandle:
        """submit 响应 → handle（在流关闭前完成有界解析与账本提交；成功路径在账本
        锁内归还预留计数并保留并发信号量——run 已在服务器侧活跃）。

        - 零 fallback、零重试：非 202（含 3xx/401/429/5xx）= 服务器明确拒绝（无 run
          产生）→ reservation 释放（可由操作方重新尝试）；
        - 202 但身份形状损坏（content-type/body/JSON/run_id/status）= 不确定 →
          reservation 中毒（绝不自动重提）；
        - 202 返回的 run_id 已属于**另一**契约 → 不覆盖既有归属（原 owner、槽位
          计数、事件归属不变）；本 reservation 中毒 + typed conflict。
        """
        status = response.status_code
        if status != 202:
            _code, snippet = self._read_error_payload(response)
            if status // 100 == 2 or 300 <= status < 400:
                error: BackendError = HermesProtocolError(
                    f"hermes submit 必须 202，得到 {status}"
                    + ("（redirect 非本地重定向 fail-closed）" if 300 <= status < 400
                       else "（实测契约）")
                    + (f": {snippet}" if snippet else ""))
            else:
                error = HermesTransportError(
                    f"hermes submit HTTP {status}: {snippet}")
            self._settle_reservation(contract.contract_id, reservation,
                                     error=error, remove=True)
            raise error
        try:
            body = self._read_json_object("submit", response)
            hermes_run_id = body.get("run_id")
            status_word = body.get("status")
            if not isinstance(hermes_run_id, str) or not _RUN_ID_RE.match(hermes_run_id):
                raise HermesProtocolError(f"hermes submit run_id 非法: {hermes_run_id!r}")
            if status_word != "started":
                raise HermesProtocolError(
                    f"hermes submit status 必须 'started'，得到 {status_word!r}")
        except BackendError as exc:
            self._settle_reservation(contract.contract_id, reservation,
                                     error=HermesTransportError(
                                         "hermes submit 202 身份形状损坏：结果不确定，"
                                         "不自动重提；同 contract 后续 submit 一律拒绝"),
                                     remove=False)
            raise exc
        handle = BackendRunHandle(backend_id=BACKEND_ID, run_id=hermes_run_id,
                                  correlation=contract.contract_id)
        with self._lock:
            existing = self._runs.get(hermes_run_id)
            if existing is not None and existing.contract_id != contract.contract_id:
                # run_id 已属于另一契约：绝不覆盖（原 owner/槽位/事件归属不变）；
                # 服务器侧确已受理（202）→ 本契约 reservation 中毒，防重提双跑。
                conflict = HermesProtocolError(
                    f"hermes submit 202 返回的 run_id {hermes_run_id!r} 已属于另一契约 "
                    f"{existing.contract_id!r}（typed conflict：不覆盖既有归属；本契约"
                    "结果不确定，不自动重提）")
                self._settle_reservation_locked(contract.contract_id, reservation,
                                                error=conflict, remove=False)
                raise conflict
            if existing is None:
                self._runs[hermes_run_id] = _RunRecord(contract.contract_id,
                                                       contract.content_hash,
                                                       contract.allowed_capabilities,
                                                       contract=contract)
            self._runs_reserved -= 1
            reservation.finish(handle=handle)
        return handle

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
        """submit 输入唯一权威入口：16A exact-schema + content_hash **完整性摘要**复核
        + 可信组合根 authorizer 精确授权确认 + 后端授权边界。

        - 非完整 WorkContract projection（缺字段/未知字段/schema marker 不符）→ 拒绝；
        - content_hash 是 **integrity hash**（摘要与内容一致才通过；from_dict 从不
          重新计算或背书摘要）——**不声明 signature/授权真实性**：授权真实性只来自
          构造期注入的可信 contract authorizer（contract_id + content_hash 精确确认
          该契约已由组合根授权；未知 id、hash 不同、authorizer 异常或返回非 True →
          submit 前拒绝、零 HTTP）；
        - allowed_backends 不含 hermes（越权自报）→ 拒绝；
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
                f"content_hash 完整性摘要复核）: {exc}") from exc
        if BACKEND_ID not in contract.allowed_backends:
            raise BackendScopeViolation(
                f"contract.allowed_backends {sorted(contract.allowed_backends)} 不含 "
                f"'{BACKEND_ID}'（契约不允许本 backend；越权自报 submit 前拒绝）")
        try:
            authorized = self._contract_authorizer(contract.contract_id, contract.content_hash)
        except Exception as exc:
            raise BackendScopeViolation(
                f"contract authorizer 异常（fail-closed，submit 前拒绝、零 HTTP）: "
                f"{type(exc).__name__}") from exc
        if authorized is not True:
            raise BackendScopeViolation(
                f"契约 {contract.contract_id!r}@{contract.content_hash[:12]}… 未经可信组合根"
                "authorizer 精确确认（未知 contract_id / content_hash 不符 / 返回非 True）"
                "——submit 前拒绝，零 HTTP")
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
        if run_handle.correlation != record.contract_id:
            raise HermesProtocolError(
                f"events handle.correlation {run_handle.correlation!r} != run 账本契约 "
                f"{record.contract_id!r}（伪造 correlation 拒绝；事件归属精确绑定）")
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
        """status GET 严格解析：200 + 精确 application/json + 有界 body + object==
        hermes.run + run_id 精确相等 + 状态词表。违反 → None（调用方自行
        protocol.error；**绝不产生终态**）。``allow`` 限定可接受状态（None = 全词表）。"""
        try:
            response, cm = self._open_stream("status", "GET", _PATH_RUN.format(run_id=run_id))
        except HermesTransportError:
            return None
        try:
            if response.status_code != 200:
                return None
            try:
                body = self._read_json_object("status", response)
            except BackendError:
                return None
        finally:
            self._close_stream(cm)
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
                # 404 必须携带精确 run_not_found 错误码，否则按协议矛盾可观察
                #（错误码经有界严格读取提取；text/plain 承载 → None，不得当作
                # 已知码）。
                if self._error_code_of(response, stage="sse_404") not in (None, "run_not_found"):
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
    def _reconcile_poll_once(self, run_id: str) -> Tuple[str, Any]:
        """单次 status 轮询（流式有界；流在返回前关闭）。

        返回 (kind, data)：kind ∈
        ``swept`` / ``auth_rejected`` / ``terminal``(data=(status_word, payload)) /
        ``stopping`` / ``approval_gap`` / ``identity_conflict`` / ``bad_word`` /
        ``reconnected`` / ``retry``。
        """
        try:
            response, cm = self._open_stream("status", "GET",
                                             _PATH_RUN.format(run_id=run_id))
        except HermesTransportError:
            return "retry", None
        try:
            if response.status_code == 404:
                # 终态记录已被 Hermes 清扫（终态 + TTL 3600s 后）：仅当错误码**精确**
                # 为 run_not_found 才可判 swept；其余 404 形状（含 text/plain 承载的
                # 伪 run_not_found）按协议矛盾继续轮询。
                if self._error_code_of(response, stage="status_404") == "run_not_found":
                    return "swept", None
                return "identity_conflict_404", None
            if response.status_code == 401:
                return "auth_rejected", None
            if response.status_code != 200:
                return "retry", None
            try:
                body = self._read_json_object("status", response)
            except BackendError:
                return "retry", None
        finally:
            self._close_stream(cm)
        # 身份封闭：object/run_id 不精确（缺失/冲突）→ 绝不产生终态，仅可观察。
        if body.get("object") != "hermes.run" or body.get("run_id") != run_id:
            return "identity_conflict", None
        status = body.get("status")
        if not isinstance(status, str) or status not in _HERMES_STATUSES:
            return "bad_word", None
        if status in _HERMES_TERMINAL_STATUSES:
            payload = {k: body[k] for k in ("output", "usage", "error") if k in body}
            return "terminal", (status, payload)
        if status == "stopping":
            return "stopping", None
        if status == "waiting_for_approval":
            # 审批身份无法从 status 轮询重建（命令身份不在状态记录里）——
            # fail-closed 可观察；绝不伪造 approval_id。
            return "approval_gap", None
        return "reconnected", None   # queued/running：非权威重连观察（16E 不复活终态）

    def _reconcile_by_status(self, run_id: str) -> Iterator[BackendEvent]:
        deadline = self._now_fn() + self._poll_budget
        reconnected_sent = False
        stopping_sent = False
        approval_gap_sent = False
        identity_error_sent = False
        while self._now_fn() < deadline:
            kind, data = self._reconcile_poll_once(run_id)
            if kind == "swept":
                yield self._make_event(run_id, "transport.disconnected",
                                       {"reason": "run_record_swept"})
                return
            if kind == "auth_rejected":
                yield self._make_event(run_id, "transport.disconnected",
                                       {"reason": "auth_rejected"})
                return
            if kind == "terminal":
                status_word, payload = data
                yield self._make_event(run_id, f"run.{status_word}", payload)
                return
            if kind == "identity_conflict_404":
                if not identity_error_sent:
                    identity_error_sent = True
                    yield self._make_event(run_id, "protocol.error",
                                           {"reason": "status_404_wrong_code"})
            elif kind == "identity_conflict":
                if not identity_error_sent:
                    identity_error_sent = True
                    yield self._make_event(run_id, "protocol.error",
                                           {"reason": "status_identity_conflict"})
            elif kind == "bad_word":
                if not identity_error_sent:
                    identity_error_sent = True
                    yield self._make_event(run_id, "protocol.error",
                                           {"reason": "status_word_unknown"})
            elif kind == "stopping":
                if not stopping_sent:
                    stopping_sent = True
                    yield self._make_event(run_id, "stopping", {})
            elif kind == "approval_gap":
                if not approval_gap_sent:
                    approval_gap_sent = True
                    yield self._make_event(run_id, "protocol.error",
                                           {"reason": "approval_pending_not_recoverable_via_poll"})
            elif kind == "reconnected":
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
        if run_handle.correlation != record.contract_id:
            raise HermesProtocolError(
                f"stop handle.correlation {run_handle.correlation!r} != run 账本契约 "
                f"{record.contract_id!r}（伪造 correlation 拒绝；停止操作身份精确绑定）")
        try:
            response, cm = self._open_stream(
                "stop", "POST", _PATH_STOP.format(run_id=run_handle.run_id))
        except HermesTransportError as exc:
            raise self._transport_failure("stop", exc) from exc
        try:
            if response.status_code == 404:
                # 404 特殊语义只在错误码精确为 run_not_found 时成立；其余 404 形状 =
                # 协议矛盾（错误码经有界严格读取提取）。
                code, snippet = self._read_error_payload(response)
                if code != "run_not_found":
                    raise HermesProtocolError(
                        f"hermes stop 404 错误码非 run_not_found: {snippet}")
                raise HermesTransportError(
                    "hermes stop 404：run 当前无活跃 agent/task（可能已终态）——"
                    "以 status/SSE 权威终态为准，本方法不声明 CANCELLED")
            if response.status_code != 200:
                _code, snippet = self._read_error_payload(response)
                raise HermesTransportError(
                    f"hermes stop HTTP {response.status_code}: {snippet}")
            try:
                body = self._read_json_object("stop", response)
            except BackendError as exc:
                raise HermesProtocolError(
                    f"hermes stop 响应形状非法（实测契约：stopping）: {type(exc).__name__}"
                ) from exc
            if body.get("status") != "stopping" or body.get("run_id") != run_handle.run_id:
                raise HermesProtocolError("hermes stop 响应形状非法（实测契约：stopping）")
        finally:
            self._close_stream(cm)
        with self._lock:
            record.stopped = True
        # 注意：此处**绝不**产生 run.cancelled —— CANCELLED 只能来自 Hermes 权威终态。

    # -- 审批：SSE approval.request → 16D；决议只来自真实 Furina 决议 -----------------
    def _handle_approval_request(self, run_id: str, record: _RunRecord,
                                 frame: Mapping[str, Any]
                                 ) -> Tuple[Optional[str], Optional[str]]:
        """approval.request → 16D 四层 Gate（唯一判定器）或 fail-closed 自动 deny。

        Reviewer Patch 4 判定路径（在 Patch 3 四层 Gate 基础上收紧六组 blocker）：

        1. 工具词法（缺失/非 str/纯空白）→ 自动 deny（``approval_tool_missing``）；
        2. **tool 精确匹配**（blocker 六：绝不用 strip() 规范化——``" terminal "`` ≠
           ``"terminal"``）+ **工具面三重封闭**（tool ∈ 最近 probe 快照 / 构造期
           expected_profile_tools / 封闭 tool→capability 映射）任一不满足 → 自动
           deny（``approval_tool_unmapped``），零 16D 请求；
        3. 映射 capability ∉ 本 run 契约 allowed_capabilities（防御性复检）→ 自动
           deny（``approval_capability_not_in_contract``）；
        4. 契约对应 ApprovalGate 缺失（``approval_gate_missing``）→ 自动 deny；
        5. **操作身份深度冻结**（blocker 四）：帧进入审批域即对完整 JSON 操作参数
           做严格递归 defensive copy（非 JSON 值 fail-closed
           ``approval_args_not_canonical``；tuple 等 Python 扩展类型不得静默转
           list）+ 完整操作身份 digest；账本快照、permission_decider、Gate、
           permit 消费各持独立副本，零共享嵌套引用；
        6. **幂等重投 exactly-once**（blocker 二/三）：相同 (run_id, tool,
           capability, 完整原始 args) digest 的重投 → 复用原 approval_id——PENDING /
           已决议未 forward 一律交唯一 resolve 路径；已 forward 零再次 POST
           once/deny（``_approval_forwarded`` 权威不旁路）；重投**先于容量检查**：
           不新建 broker request、不占审批容量、不发 deny；并发相同操作经
           in-flight 单飞只产生一个 approval_id；
        7. 实时 PermissionManager 决策（``permission_decider`` 构造期注入）→ 容量
           预留（**仅新操作**；满 → ``approval_ledger_full`` + deny）→
           ``gate.check_step``（wait_for_approval=False，完整 WorkContract + 冻结
           原始 args 独立副本 + 冻结 envelope + risk 下界 L2）；
        8. **Gate 绑定证明（完整身份）**（blocker 五；Patch 5 blocker 一）：Gate
           判定结果进入本 adapter 审批账本前，必须经 16D 公开 API 证明其产生于
           构造期注入的 approval_broker **且与本操作完整身份一致**——claimed
           ApprovalRequest 字段独立重算（scope/risk/policy 不信任 Gate 自报）+
           主 broker ``matching_request`` 全身份查询、命中 approval_id 精确等于
           Gate 返回值（外部 broker 的 Gate / 同名 ID 不同身份 → fail-closed
           deny，不进账本、不产生 once）；
        9. **ALLOW 来源区分**（blocker 二）：``result.approval`` 非空 → 属已有
           approval，必须进入统一 exactly-once 路径（绝不立即 POST）；仅
           ``result.grant`` 非空才允许作为新的 grant-covered action 立即边界
           **主 broker**（``self._broker.consume_permit``，Reviewer Patch 6）原子
           消费成功后转发 once（grant 绑定先经主 broker 公开查询面
           ``covering_grant`` 全匹配证明：契约/tool/capability/paths/write_paths
           全部匹配且有效 grant_id 精确等于 Gate 返回值——证明失败在 consume
           **之前**拦截，零 permit 消费；foreign Gate 的 permit 因不在主 broker
           台账在 consume 处拒绝，零 once）。

        自动 deny 只向 Hermes 转发 ``deny``，不创建任何 16D 审批请求（决议由
        Furina 决策面（broker owner）做出；绝不伪造 USER evidence、绝不签发 grant/
        permit）。
        """
        tool = frame.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            self._forward_choice(run_id, "deny")
            return None, "approval_tool_missing"
        # -- blocker 六：tool 精确匹配（零 strip 规范化；三重封闭用原始词形）----------
        snapshot = self._profile_tools_snapshot
        if tool not in snapshot or tool not in self._expected_profile_tools \
                or tool not in self._tool_capability_map:
            self._forward_choice(run_id, "deny")
            return None, "approval_tool_unmapped"
        capability = self._tool_capability_map[tool]
        if capability not in record.allowed_capabilities:
            self._forward_choice(run_id, "deny")
            return None, "approval_capability_not_in_contract"
        gate = self._approval_gates.get(record.contract_id)
        if gate is None:
            self._forward_choice(run_id, "deny")
            return None, "approval_gate_missing"
        # -- blocker 四：帧时刻操作身份深度冻结 + 完整身份 digest ---------------------
        # canonical operation args = frame 全量减传输层字段（零 str() coercion、零截断；
        # 任何 command/args 差异 ⇒ 不同操作身份 digest ⇒ 不同操作）。
        raw_op_args = {k: v for k, v in frame.items()
                       if k not in _NON_OPERATION_FRAME_FIELDS}
        try:
            op_args = _deep_freeze_json(raw_op_args)
            digest = _operation_identity_digest(run_id, tool, capability, op_args)
        except HermesProtocolError:
            self._forward_choice(run_id, "deny")
            return None, "approval_args_not_canonical"
        # -- blocker 二/三：幂等重投 + 并发单飞（先于容量与 Gate）----------------------
        while True:
            with self._lock:
                replay_id = self._approval_op_index.get(digest)
                inflight = None if replay_id is not None \
                    else self._approval_inflight.get(digest)
                leader = replay_id is None and inflight is None
                if leader:
                    inflight = threading.Event()
                    self._approval_inflight[digest] = inflight
            if replay_id is not None:
                # 完全相同操作重投：复用原 approval_id。PENDING / 已决议未 forward
                # → 仍交唯一 resolve 路径；已 forward → 零再次 POST once/deny；
                # 零新 broker request、零容量占用。
                return replay_id, None
            if leader:
                break
            if not inflight.wait(timeout=self._request_timeout + 5.0):
                self._forward_choice(run_id, "deny")
                return None, "approval_replay_inflight_timeout"
            # leader 已收口：重新查索引——命中即复用；未命中（leader 未能建立
            # approval）则本线程作为新 leader 自行走完整判定路径。
        try:
            return self._approval_new_operation(run_id, record, tool, capability,
                                                gate, op_args, digest)
        finally:
            with self._lock:
                done = self._approval_inflight.pop(digest, None)
            if done is not None:
                done.set()

    @staticmethod
    def _gate_effective_risk(pm_decision: PermissionDecision) -> Permission:
        """``ApprovalGate.check_step`` effective risk 的镜像（同一规则）：
        effective = max(PM level（若为 Permission）, 调用方声明的 risk 下界)。
        本 adapter 恒以 ``risk_level=L2`` 调用 Gate，故 effective 恒 ≥ L2。
        仅用于绑定证明对请求身份的**独立重算**（不信任 Gate 自报）；四层判定
        权威仍在 Gate。"""
        pm_level = pm_decision.level if isinstance(pm_decision.level, Permission) else None
        return max(lv for lv in (pm_level, Permission.L2_HIGH_RISK) if lv is not None)

    def _prove_approval_binding(self, claimed: Any, *, contract: WorkContract,
                                run_id: str, tool: str, capability: str,
                                op_args: Mapping[str, Any],
                                pm_decision: PermissionDecision) -> Optional[str]:
        """Gate 绑定证明（Patch 4 blocker 五；Patch 5 blocker 一完整身份版）——
        approval 路径。

        Gate 判定产生的 approval 进入本 adapter 审批账本或产生 once 前，必须经
        16D **公开 API** 证明其确为构造期注入的 approval_broker 针对**本操作**
        建立的记录——仅"主 broker 存在同名 ID"不构成证明（同名记录可能是完全
        不同的操作）：

        1. Gate 返回的 :class:`ApprovalRequest` 自身字段必须与真实操作完整身份
           逐维一致：contract_id / content_hash / run_id / tool / capability /
           requested_scope / risk / policy——其中 requested_scope / risk / policy
           由本 adapter 以与 Gate/broker 相同的公共规则**独立重算**
           （``AgentRuntime._step_paths`` + broker scope 归一化、effective risk
           max(PM, L2) 镜像、契约 approval_policy），不信任 Gate 自报；
        2. 经主 broker 公开全身份查询面 ``ApprovalBroker.matching_request``
           （contract_id / contract_hash / run_id / tool / capability /
           requested_scope / risk_level / policy_kind / operation_digest 全部
           精确过滤）检索；**命中的 approval_id 必须精确等于 Gate 返回值**。
           ``operation_digest`` 是主 broker 随机密钥 HMAC over 原始 args——
           外部 broker 的 Gate 无法伪造出能在主 broker 台账命中的 digest，
           "同名 ID 不同身份"（UUID 碰撞 / 换 args / 换 run_id / 换契约 hash）
           一律不命中 → fail-closed。

        仅使用公开查询面，不触碰任何 Python ``_private`` 属性（frozen 16D 公开
        API 可完整表达本证明，未触发 BLOCKED_BY_16D_GATE_BROKER_BINDING_GAP）。
        返回 None = 证明成立；非 None = deny 原因（fail-closed：不进 adapter
        账本、不消费 permit、零 once、原记录不覆盖不串用）。"""
        try:
            expected_scope = tuple(
                str(p).strip()
                for p in AgentRuntime._step_paths(tool, dict(op_args))
                if str(p).strip())
            expected_risk = self._gate_effective_risk(pm_decision)
            expected_policy = contract.approval_policy.policy_kind
        except Exception as exc:   # noqa: BLE001 —— 身份重算异常 fail-closed
            return f"approval_binding_identity_error:{type(exc).__name__}"
        if (not isinstance(claimed, ApprovalRequest)
                or claimed.contract_id != contract.contract_id
                or claimed.contract_hash != contract.content_hash
                or claimed.run_id != run_id
                or claimed.tool != tool
                or claimed.capability != capability
                or claimed.requested_scope != expected_scope
                or claimed.risk_level != expected_risk
                or claimed.policy_kind != expected_policy):
            return "approval_binding_identity_mismatch"
        try:
            bound = self._broker.matching_request(
                contract_id=contract.contract_id,
                contract_hash=contract.content_hash,
                run_id=run_id, tool=tool, capability=capability,
                requested_scope=expected_scope, risk_level=expected_risk,
                policy_kind=expected_policy,
                operation_digest=claimed.operation_digest)
        except Exception as exc:   # noqa: BLE001 —— 查询面异常同样 fail-closed
            return f"approval_gate_broker_binding_error:{type(exc).__name__}"
        if bound is None or bound.approval_id != claimed.approval_id:
            return "approval_gate_broker_binding"
        return None

    def _prove_grant_binding(self, claimed: Any, *, contract: WorkContract,
                             tool: str, capability: str,
                             op_args: Mapping[str, Any]) -> Optional[str]:
        """Gate 绑定证明（Patch 4 blocker 五；Patch 5 blocker 一完整身份版）——
        grant 路径。

        Gate 判定返回的 grant-covered ALLOW 进入 permit 消费 / once 前，必须经
        主 broker 公开查询面证明其 grant 确为注入的 approval_broker 中**有效且
        精确覆盖本操作**的记录——仅"存在同名激活 grant"不构成证明：

        1. Gate 返回的 :class:`AuthorizationGrant` 自身契约 / capability 绑定
           必须与真实操作一致（contract_id / contract_hash / capability）；
        2. 经主 broker 公开查询面 ``ApprovalBroker.covering_grant``（激活窗口
           + 契约 id/hash 精确过滤 + capability 精确 + tool_pattern glob +
           全部路径入 workspace + **写目标入 write_roots**）检索——paths /
           write_paths 由本 adapter 以与 Gate/broker 相同的公共规则独立重算；
           **返回的有效 grant_id 必须精确等于 Gate 返回值**。

        同名 grant 但 scope / contract / tool 不同（UUID 碰撞）不命中 →
        fail-closed deny：不消费 permit、零 once。仅使用公开查询面，不触碰任何
        Python ``_private`` 属性。返回 None = 证明成立；非 None = deny 原因。"""
        if (not isinstance(claimed, AuthorizationGrant)
                or claimed.contract_id != contract.contract_id
                or claimed.contract_hash != contract.content_hash
                or claimed.capability != capability):
            return "approval_grant_identity_mismatch"
        try:
            paths = tuple(AgentRuntime._step_paths(tool, dict(op_args)))
            write_paths, _read_paths = classify_step_paths(tool, paths)
            covering = self._broker.covering_grant(
                tool=tool, capability=capability,
                contract_id=contract.contract_id,
                contract_hash=contract.content_hash,
                paths=paths, write_paths=write_paths, now=self._broker.now())
        except Exception as exc:   # noqa: BLE001 —— 查询面异常同样 fail-closed
            return f"approval_gate_broker_binding_error:{type(exc).__name__}"
        if covering is None or covering.grant_id != claimed.grant_id:
            return "approval_gate_broker_binding_grant"
        return None

    def _approval_new_operation(self, run_id: str, record: _RunRecord, tool: str,
                                capability: str, gate: ApprovalGate,
                                op_args: Mapping[str, Any], digest: str
                                ) -> Tuple[Optional[str], Optional[str]]:
        """新操作（digest 未入账本）的 16D 四层 Gate 判定主路径（Patch 4）。"""
        pm = self._live_permission_decision(tool, capability,
                                            _deep_freeze_json(op_args),
                                            record.contract_id, run_id)
        if pm is None:
            self._forward_choice(run_id, "deny")
            return None, "approval_pm_unavailable"
        # 原子容量预留（仅新操作；封闭状态机第一步；网络 I/O 一律在锁外）
        with self._lock:
            full = len(self._approval_ops) + self._approvals_reserved \
                >= self._max_tracked_approvals
            if not full:
                self._approvals_reserved += 1
        if full:
            self._forward_choice(run_id, "deny")
            return None, "approval_ledger_full"
        try:
            result = gate.check_step(
                tool=tool, args=_deep_freeze_json(op_args), contract=record.contract,
                pm_decision=pm,
                backend_capability_ids=self._capabilities.capability_ids,
                run_id=run_id, risk_level=Permission.L2_HIGH_RISK,
                wait_for_approval=False)
        except Exception as exc:   # noqa: BLE001 —— Gate 异常 fail-closed（零 once）
            with self._lock:
                self._approvals_reserved -= 1
            self._forward_choice(run_id, "deny")
            return None, f"approval_gate_error:{type(exc).__name__}"
        if result.verdict is GateVerdict.APPROVAL_PENDING and result.approval is not None:
            # 唯一建立待审批记录的路径：Gate 已创建 16D 请求且状态 PENDING；
            # 入账本前必须先证明该 approval 产生于本 adapter 的 approval_broker
            # 且与本操作完整身份一致（Patch 5：仅同名 ID 存在不构成证明）。
            approval_id = result.approval.approval_id
            binding = self._prove_approval_binding(
                result.approval, contract=record.contract, run_id=run_id,
                tool=tool, capability=capability, op_args=op_args, pm_decision=pm)
            if binding is not None:
                with self._lock:
                    self._approvals_reserved -= 1
                self._forward_choice(run_id, "deny")
                return None, binding
            with self._lock:
                self._approval_ops.setdefault(
                    approval_id, _ApprovalOpRecord(
                        run_id=run_id, tool=tool, capability=capability,
                        op_args=op_args, digest=digest))
                self._approval_op_index.setdefault(digest, approval_id)
                self._approvals_reserved -= 1
            return approval_id, None
        with self._lock:
            self._approvals_reserved -= 1   # 非 PENDING 路径：归还预留（未入账）
        if result.verdict is GateVerdict.ALLOW:
            if result.approval is not None:
                # blocker 二：ALLOW 源于**已有 approval**（approve_once/session 终态）
                # → 绝不立即 POST once/deny，进入统一 exactly-once resolve 路径；
                # 入账本前同样先经完整身份绑定证明（Patch 5）。
                approval_id = result.approval.approval_id
                binding = self._prove_approval_binding(
                    result.approval, contract=record.contract, run_id=run_id,
                    tool=tool, capability=capability, op_args=op_args,
                    pm_decision=pm)
                if binding is not None:
                    self._forward_choice(run_id, "deny")
                    return None, binding
                with self._lock:
                    self._approval_ops.setdefault(
                        approval_id, _ApprovalOpRecord(
                            run_id=run_id, tool=tool, capability=capability,
                            op_args=op_args, digest=digest))
                    self._approval_op_index.setdefault(digest, approval_id)
                return approval_id, None
            if result.grant is not None and result.permit is not None:
                # blocker 二/五：仅 grant 来源允许作为**新的** grant-covered action
                # 立即边界消费（session grant 本义为多次放行）；grant 绑定先经
                # 主 broker 公开查询面完整身份证明（Patch 5：covering_grant
                # 全匹配 + 有效 grant_id 精确相等，仅 is_grant_active 不构成证明）
                # ——证明失败在 consume **之前**拦截：零 permit 消费、零 once。
                binding = self._prove_grant_binding(
                    result.grant, contract=record.contract, tool=tool,
                    capability=capability, op_args=op_args)
                if binding is not None:
                    self._forward_choice(run_id, "deny")
                    return None, binding
                # Patch 6（blocker 一）：最终消费必须由构造期注入的**主 broker** 经
                # 公开 producer API 原子完成（绝不 gate.consume_permit——外部 Gate
                # 会转而消费其自身 broker 的 permit，跨 broker TOCTOU）；foreign
                # permit 即使同名 grant_id/同契约同操作在主 broker 有同名有效授权，
                # 也因 permit 不在主 broker 台账被拒绝（单锁内先复核来源状态后
                # 单点提交，零 once）。
                outcome = self._broker.consume_permit(
                    result.permit, tool=tool, capability=capability,
                    args=_deep_freeze_json(op_args))
                if outcome.ok:
                    self._forward_choice(run_id, "once")
                    return None, "approval_covered_by_grant_once"
                self._forward_choice(run_id, "deny")
                return None, "approval_grant_permit_denied"
            # 无 approval / grant 来源的 ALLOW（adapter 下不可达：risk 下界 L2 硬性
            # 审批）→ fail-closed deny（来源不可证明即不放行）。
            self._forward_choice(run_id, "deny")
            return None, "approval_allow_source_unproven"
        self._forward_choice(run_id, "deny")
        return None, f"approval_gate_{result.verdict.value}"

    def _live_permission_decision(self, tool: str, capability: str,
                                  raw_args: Mapping[str, Any], contract_id: str,
                                  run_id: str) -> Optional[PermissionDecision]:
        """实时 PermissionManager 决策（构造期注入 ``permission_decider``）。

        decider 缺失/异常/返回非 PermissionDecision → None（调用方 fail-closed deny，
        零 once）——**绝不手造 PermissionDecision 冒充 PM 结果**（Reviewer Patch 3
        要求 9）。
        """
        if self._permission_decider is None:
            return None
        try:
            decision = self._permission_decider(tool, capability, dict(raw_args),
                                                contract_id, run_id)
        except Exception as exc:   # noqa: BLE001
            log.warning("hermes run=%s permission_decider 异常（fail-closed deny）: %s",
                        run_id, type(exc).__name__)
            return None
        if not isinstance(decision, PermissionDecision):
            log.warning("hermes run=%s permission_decider 返回非 PermissionDecision"
                        "（fail-closed deny）: %s", run_id, type(decision).__name__)
            return None
        return decision

    def _forward_choice(self, run_id: str, choice: str) -> None:
        """fail-closed 自动决策转发（deny/once）：直接向 Hermes 转发（不建立 16D
        请求时唯一通道）。转发失败仅记录（可观察），绝不重试、绝不出 fallback 通道；
        响应体不读取（流式打开、只取状态码、立即关闭——零无界缓冲）。"""
        try:
            response, cm = self._open_stream(
                "auto_forward", "POST", _PATH_APPROVAL.format(run_id=run_id),
                json_body={"choice": choice})
        except HermesTransportError as exc:
            log.warning("hermes run=%s 自动转发 %s 失败: %s", run_id, choice, exc)
            return
        try:
            if response.status_code not in (200, 409):
                log.warning("hermes run=%s 自动转发 %s 异常 HTTP %s",
                            run_id, choice, response.status_code)
        finally:
            self._close_stream(cm)

    def resolve_approval(self, approval_ref: str) -> Dict[str, Any]:
        """等待 16D 真实决议并**恰好一次**转发 Hermes（choice 只允许 once/deny）。

        Reviewer Patch 3 边界重构——顺序为 **等待决议 → 同一 Gate 重新判定（实时 PM）
        → Gate 绑定证明（Patch 5：完整身份）→ 立即边界原子 permit 消费 → POST**：

        - 先经 ``broker.wait_for_resolution``（有界）等待**真实 Furina 决议**；
        - **Patch 4（blocker 一）：决议不得被后出现的 grant 升级**——先检查原
          approval 的真实 resolution，仅真实 APPROVE_ONCE / APPROVE_SESSION 有资格
          继续执行；DENY / TIMEOUT / REVOKED / CANCELLED / LATE / UNKNOWN / CONFLICT
          / decision=None → 固定 choice=deny 且完全不触碰 Gate（绝不因 matching
          session grant 重新变成 ALLOW，不签发、不消费 permit、零 once）；
        - 有资格路径：resolve 时**重新取得实时 PermissionDecision**（构造期注入
          ``permission_decider``；缺失/异常/非决策 → fail-closed deny），并**再次调用
          同一 ``ApprovalGate.check_step``**（完整 WorkContract + 帧时刻冻结原始 args
          的独立深冻结副本 + 冻结 envelope + risk 下界 L2，wait_for_approval=False）：
          - GateResult=ALLOW 且携带 permit → **先经 Gate 绑定证明（Patch 5）**：
            ``result.approval`` / ``result.grant`` 必须证明产生于主 broker 且与
            帧时刻冻结的完整操作身份一致（外部 Gate / 同名 ID 不同身份在
            consume **之前**拦截），随后**主 broker** 公开 producer API
            ``self._broker.consume_permit``（Reviewer Patch 6：绝不
            ``gate.consume_permit``——Gate 恒委托其自身 broker，foreign Gate 会把
            permit 消费到 foreign broker 台账）在发送 once 的**立即边界**原子复核
            （permit 属主 broker 台账 + contract_id/hash + run_id + tool +
            capability + 原始 args + approval/grant 状态，全部在 broker 唯一消费锁
            内重查）并单点提交消费；**仅消费成功才 POST once**。决议与远端边界
            之间的撤销/状态漂移/PM 降级 → 绑定证明失败、消费失败或 Gate 重判
            DENY → fail-closed 转发 deny，绝不发送 once；
          - Gate 任何 DENY（PM 拒绝、契约/hash 不匹配、撤销、超时、已消费）、契约
            Gate 缺失、permit 消费失败 → ``deny``（fail-closed）；
          - APPROVE_SESSION 决议仍只收窄转发 once（不放宽 16D 决议）；
        - DENY / TIMEOUT / REVOKED / 未决（LATE/UNKNOWN）→ ``deny``（fail-closed）；
        - **exactly-once**：同一 approval 无论顺序重复还是并发 resolve，只有首个调用
          会 POST；其余调用返回 typed no-op（``forwarded=False``），绝不二次 POST；
        - ``resolved == 1`` 精确才声明成功，否则类型化协议错误（绝不虚报成功）；
        - 409 仅当错误码**精确**为 ``approval_not_pending`` 才视为 typed no-op。
        """
        if not self.capabilities.supports_resolve_approval:
            raise BackendCapabilityError("hermes 未声明 supports_resolve_approval")
        if not isinstance(approval_ref, str) or not approval_ref.strip():
            raise HermesProtocolError("approval_ref 必须是非空 str")
        approval_id = approval_ref.strip()
        with self._lock:
            op = self._approval_ops.get(approval_id)
            if op is None:
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
        resolution_status = str(resolution.status.value
                                if isinstance(resolution.status, ResolutionStatus)
                                else resolution.status)
        decision = resolution.decision \
            if isinstance(resolution.decision, ApprovalDecisionKind) else None
        choice = "deny"
        consumed = False
        permit_id = ""
        boundary_reason = ""
        # -- Patch 4（blocker 一）：决议不得被后出现的 grant 升级 ----------------------
        # 先检查原 approval 的真实 resolution：**仅真实 APPROVE_ONCE /
        # APPROVE_SESSION 决议有资格继续执行**。DENY / TIMEOUT / REVOKED / CANCELLED
        # / LATE / UNKNOWN / CONFLICT / decision=None → 固定 choice=deny，**完全不
        # 触碰 Gate**——绝不因 resolve 时新出现的 matching session grant 重新变成
        # ALLOW（不签发、不消费 permit、零 once）。
        eligible = decision in (ApprovalDecisionKind.APPROVE_ONCE,
                                ApprovalDecisionKind.APPROVE_SESSION)
        if not eligible:
            boundary_reason = "resolution_not_approvable:" + resolution_status + (
                f":{decision.value}" if decision is not None else "")
        else:
            # -- resolve 时重新取得实时 PM 决策 + 同一 Gate 重新判定（Reviewer Patch 3）
            with self._lock:
                run_rec = self._runs.get(op.run_id)
            if run_rec is None:
                boundary_reason = "boundary_run_unknown"
            else:
                gate = self._approval_gates.get(run_rec.contract_id)
                if gate is None:
                    boundary_reason = "boundary_gate_missing"
                else:
                    pm = self._live_permission_decision(
                        op.tool, op.capability, _deep_freeze_json(op.op_args),
                        run_rec.contract_id, op.run_id)
                    if pm is None:
                        boundary_reason = "boundary_permission_decider_unavailable"
                    else:
                        try:
                            result = gate.check_step(
                                tool=op.tool, args=_deep_freeze_json(op.op_args),
                                contract=run_rec.contract,
                                pm_decision=pm,
                                backend_capability_ids=self._capabilities.capability_ids,
                                run_id=op.run_id, risk_level=Permission.L2_HIGH_RISK,
                                wait_for_approval=False)
                        except Exception as exc:   # noqa: BLE001 —— Gate 异常 fail-closed
                            boundary_reason = f"boundary_gate_error:{type(exc).__name__}"
                            result = None
                        if result is not None and result.verdict is GateVerdict.ALLOW \
                                and result.permit is not None:
                            # -- Patch 5（blocker 一）：once 前绑定证明同样适用——
                            # resolve 边界的 Gate 判定结果必须证明仍产生于主 broker
                            # 且与帧时刻冻结的完整操作身份一致；外部 Gate / UUID
                            # 碰撞在 consume **之前**拦截（零 permit 消费零 once）。
                            if result.approval is not None:
                                binding = self._prove_approval_binding(
                                    result.approval, contract=run_rec.contract,
                                    run_id=op.run_id, tool=op.tool,
                                    capability=op.capability, op_args=op.op_args,
                                    pm_decision=pm)
                            elif result.grant is not None:
                                binding = self._prove_grant_binding(
                                    result.grant, contract=run_rec.contract,
                                    tool=op.tool, capability=op.capability,
                                    op_args=op.op_args)
                            else:
                                binding = "approval_allow_source_unproven"
                            outcome = None
                            if binding is not None:
                                boundary_reason = f"boundary_{binding}"
                            else:
                                # Patch 6（blocker 一）：resolve 边界的最终消费同样
                                # 只由**主 broker** 公开 producer API 原子完成——
                                # foreign Gate 签发的 permit 不在主 broker 台账，
                                # 一律拒绝（绝不经 gate.consume_permit 委托到
                                # foreign broker 的台账）。
                                try:
                                    outcome = self._broker.consume_permit(
                                        result.permit, tool=op.tool,
                                        capability=op.capability,
                                        args=_deep_freeze_json(op.op_args))
                                except ApprovalStateError as exc:
                                    boundary_reason = \
                                        f"boundary_permit_consume_error:{type(exc).__name__}"
                                    outcome = None
                            if outcome is not None and outcome.ok:
                                # permit 已在发送边界**原子消费**（POST 前最后一道状态性
                                # 操作）；此后 POST 失败也绝不回滚消费/绝不重发。
                                choice = "once"
                                consumed = True
                                permit_id = result.permit.permit_id
                            else:
                                boundary_reason = boundary_reason or "boundary_permit_denied"
                                log.warning(
                                    "hermes approval=%s 决议 %s 但远端边界 permit 消费未成立"
                                    "（fail-closed deny）: %s", approval_id,
                                    resolution.decision.value if resolution.decision else "?",
                                    boundary_reason)
                        else:
                            boundary_reason = boundary_reason or (
                                f"boundary_gate_{result.verdict.value}"
                                if result is not None else "boundary_gate_error")
        client = self._get_client()
        try:
            response, cm = self._open_stream(
                "approval", "POST", _PATH_APPROVAL.format(run_id=op.run_id),
                json_body={"choice": choice})
        except HermesTransportError as exc:
            raise self._transport_failure("approval", exc) from exc
        try:
            if response.status_code == 409:
                code, snippet = self._read_error_payload(response, stage="approval_409")
                if code != "approval_not_pending":
                    raise HermesProtocolError(
                        f"hermes approval 409 错误码非 approval_not_pending: {snippet}")
                # Hermes 侧已无挂起审批（已解析/已过期）：类型化 no-op，绝不重试。
                return {"choice": choice, "resolved": 0, "forwarded": True,
                        "consumed": consumed, "permit_id": permit_id,
                        "resolution_status": resolution_status}
            if response.status_code != 200:
                _code, snippet = self._read_error_payload(response, stage="approval")
                raise HermesTransportError(
                    f"hermes approval HTTP {response.status_code}: {snippet}")
            try:
                body = self._read_json_object("approval", response)
            except BackendError as exc:
                raise HermesProtocolError(
                    "hermes approval 响应形状非法（实测契约）: "
                    f"{type(exc).__name__}") from exc
            if body.get("object") != "hermes.run.approval_response" \
                    or body.get("run_id") != op.run_id:
                raise HermesProtocolError("hermes approval 响应形状非法（实测契约）")
            resolved = body.get("resolved")
            if isinstance(resolved, bool) or not isinstance(resolved, int):
                raise HermesProtocolError(f"hermes approval resolved 非法: {resolved!r}")
            if resolved != 1:
                raise HermesProtocolError(
                    f"hermes approval resolved 必须 == 1 才算成功，得到 {resolved!r}")
        finally:
            self._close_stream(cm)
        result: Dict[str, Any] = {"choice": choice, "resolved": resolved,
                                  "forwarded": True, "consumed": consumed,
                                  "permit_id": permit_id,
                                  "resolution_status": resolution_status}
        if boundary_reason:
            result["boundary"] = boundary_reason
        return result
