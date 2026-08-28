"""Phase 16E — Backend Event Normalization：数据模型（backend-neutral 事件信封 + 分类）。

设计纪律（任务书 §3/§5/§6）：

- **外部 backend 词表是输入，只有归一层产出 canonical 事件**；生产类型不得出现
  Hermes 专属字段（Hermes-shaped fixture 只作为输入映射测试）。
- 信封字段至少含 event_id/backend_id/contract_id/run_id/sequence/occurred_at/
  received_at/kind/sanitized payload/terminal/critical/provenance。
- **背压只做分类**（critical/coalescible/droppable），durable queue/ledger 属 16H；
  token/progress/tool 高频流**不得**写成 cognition truth。
- 本模块无任何 DB / C6 / C7 / schema 行为；只定义类型与纯函数。

terminal/critical 是**派生**字段（由 kind 决定），调用方不得自报——防止"完成/成功"
由事件来源方自证。
"""
from __future__ import annotations

import enum
import json
import math
import re
import time
from types import MappingProxyType
from typing import Any, Mapping, Optional

from furina.core import FurinaError


# ---------------------------------------------------------------------------
# 类型化错误
# ---------------------------------------------------------------------------
class EventNormalizationError(FurinaError):
    """事件归一层拒绝（非法信封 / 非法输入形状）。"""


class WorkExecutionError(FurinaError):
    """工作域状态机拒绝（run/契约身份不匹配等程序性错误）。"""


# ---------------------------------------------------------------------------
# canonical 事件类型（外部词表经 normalizer 映射到此；生产类型只认此枚举）
# ---------------------------------------------------------------------------
class EventKind(str, enum.Enum):
    """backend-neutral canonical 事件类型（任务书 §3 的语义类别的等价物）。"""

    RUN_ACCEPTED = "run.accepted"                # backend 接受 run（queued）
    RUN_STARTED = "run.started"                  # backend 开始执行（running）
    APPROVAL_REQUESTED = "approval.requested"    # 挂起等待审批（waiting_for_approval）
    APPROVAL_RESOLVED = "approval.resolved"      # 审批 approve/deny/timeout
    TOOL_STARTED = "tool.started"                # 工具开始（驱动 TOOL_RUNNING 子相位）
    TOOL_PROGRESS = "tool.progress"              # 进度/token 类 tick（可合并/丢弃）
    TOOL_COMPLETED = "tool.completed"            # 工具完成（退出 TOOL_RUNNING 子相位）
    BACKEND_COMPLETED = "backend.completed"      # backend 说 completed → BACKEND_DONE_UNVERIFIED
    BACKEND_FAILED = "backend.failed"            # backend 失败
    BACKEND_CANCELLED = "backend.cancelled"      # backend 取消
    STOP_REQUESTED = "stop.requested"            # 停止已请求（未达终态）
    STOPPING = "stop.stopping"                   # 正在停止（过渡态）
    TRANSPORT_DISCONNECTED = "transport.disconnected"  # 传输断开 → UNKNOWN 策略边界
    TRANSPORT_RECONNECTED = "transport.reconnected"    # 重连（非权威；不得复活终态）
    PROTOCOL_ERROR = "protocol.error"            # 协议错误（诊断性，不改状态）
    VERIFICATION_BOUNDARY = "verification.boundary"    # 16F 校验边界（16E 只定义转移规则；
                                                        # outcome=verified 在 16E 阶段
                                                        # fail-closed——VERIFIED 不可由
                                                        # 公开事件抵达，见 reducer）
    UNKNOWN_EVENT = "unknown.event"              # 未知外部类型：可观察但非权威


#: backend 终态信号（terminal 派生字段的真值来源）。
TERMINAL_KINDS = frozenset({
    EventKind.BACKEND_COMPLETED,
    EventKind.BACKEND_FAILED,
    EventKind.BACKEND_CANCELLED,
})

#: critical 事件（任务书 §5：terminal/approval/cancellation/disconnect/
#: verification-boundary 永不丢弃；另含生命周期与协议完整性信号）。
#: TOOL_STARTED/TOOL_COMPLETED 是**不可丢、不可合并**的工具生命周期边界——
#: 丢/合并它们会破坏工具子相位的成对语义，故归入 critical（见 reviewer
#: patch1: 只有 TOOL_PROGRESS/token delta 可 drop/coalesce）。
CRITICAL_KINDS = frozenset({
    EventKind.BACKEND_COMPLETED,
    EventKind.BACKEND_FAILED,
    EventKind.BACKEND_CANCELLED,
    EventKind.APPROVAL_REQUESTED,
    EventKind.APPROVAL_RESOLVED,
    EventKind.STOP_REQUESTED,
    EventKind.STOPPING,
    EventKind.TRANSPORT_DISCONNECTED,
    EventKind.VERIFICATION_BOUNDARY,
    EventKind.RUN_ACCEPTED,
    EventKind.RUN_STARTED,
    EventKind.PROTOCOL_ERROR,
    EventKind.TOOL_STARTED,
    EventKind.TOOL_COMPLETED,
})

#: droppable 事件（progress/token 高频 tick：压力下可丢弃，绝不写成 cognition truth）。
DROPPABLE_KINDS = frozenset({EventKind.TOOL_PROGRESS})

#: coalescible 事件（压力下可合并；未列出的非 critical 事件默认 coalescible）。
#: 仅 reconnect/unknown 这类无生命周期语义的观察可合并；TOOL_* 生命周期边界
#: 已上移为 critical（不可丢亦不可合并）。
COALESCIBLE_KINDS = frozenset({
    EventKind.TRANSPORT_RECONNECTED,
    EventKind.UNKNOWN_EVENT,
})


# ---------------------------------------------------------------------------
# 背压分类（只定义策略；durable queue/ledger 属 16H）
# ---------------------------------------------------------------------------
class EventPriority(str, enum.Enum):
    """16E 背压优先级分类（16H 负责 durable 实现）。"""

    CRITICAL = "critical"        # 永不丢弃
    COALESCIBLE = "coalescible"  # 压力下可合并
    DROPPABLE = "droppable"      # 压力下可丢弃


def classify_priority(kind: EventKind) -> EventPriority:
    """确定性优先级分类：critical ⊇ 终态/审批/取消/断开/校验边界/工具生命周期边界。"""
    if not isinstance(kind, EventKind):
        raise EventNormalizationError(f"kind 必须是 EventKind，得到 {kind!r}")
    if kind in CRITICAL_KINDS:
        return EventPriority.CRITICAL
    if kind in DROPPABLE_KINDS:
        return EventPriority.DROPPABLE
    return EventPriority.COALESCIBLE


class EventBackpressurePolicy:
    """16E 背压策略（纯策略，无队列/无持久化）。

    - ``never_droppable(kind)``：CRITICAL 永不丢弃（含工具生命周期边界）；
    - ``drop_allowed(kind, under_pressure)``：压力下只允许丢弃 DROPPABLE
      （仅 TOOL_PROGRESS/token delta）；
    - ``coalesce_allowed(kind)``：仅 COALESCIBLE（reconnect/unknown 观察）可合并；
      TOOL_STARTED/TOOL_COMPLETED 既不可丢也不可合并。
    """

    @staticmethod
    def never_droppable(kind: EventKind) -> bool:
        return classify_priority(kind) is EventPriority.CRITICAL

    @staticmethod
    def drop_allowed(kind: EventKind, *, under_pressure: bool) -> bool:
        if not under_pressure:
            return False
        return classify_priority(kind) is EventPriority.DROPPABLE

    @staticmethod
    def coalesce_allowed(kind: EventKind) -> bool:
        return classify_priority(kind) is EventPriority.COALESCIBLE


# ---------------------------------------------------------------------------
# payload 脱敏与有界（确定性；16E 自带，不依赖 16D/16B 内部）
# ---------------------------------------------------------------------------
_SECRET_KEY_PARTS = frozenset({
    "password", "passwd", "pwd", "secret", "apikey", "api_key", "api-key",
    "access_token", "refresh_token", "authorization", "bearer",
    "cookie", "private_key", "client_secret",
    "token", "auth_token", "passphrase", "credential", "xapikey", "xauthtoken",
    "xauthorization", "proxyauthorization",
})

_MAX_DEPTH = 8
_STRING_CAP = 256
_DEFAULT_MAX_BYTES = 4096
#: 最小预算：必须能容纳 truncation marker 自身（ASCII，最坏 ~64B，留余量取 128）。
#: 低于最小预算直接 fail-closed——不允许"声称允许 1 byte 却返回超过 1 byte 的 JSON"。
_MIN_PAYLOAD_BUDGET = 128
_MAX_PAYLOAD_BUDGET = 1 << 20     # 1 MiB：防呆上限（拒绝任意巨大预算）
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _is_secret_key(key: str) -> bool:
    """标准秘密键名判定：精确匹配词表（含去分隔符的紧凑形，如 api_key→apikey）。

    不做宽泛子串匹配，避免误伤 token_count/author 等合法字段。
    """
    norm = key.lower()
    compact = re.sub(r"[^a-z0-9]+", "", norm)
    return norm in _SECRET_KEY_PARTS or compact in _SECRET_KEY_PARTS


#: 秘密**值**形态（嵌在 message/stdout/error 字符串内的键值/头/凭证形态）。
#: 键值形态的标签允许 `_`/`-` 分隔（api_key/api-key/apikey 同义），键名允许被
#: JSON 引号包裹（``{"access_token":"atk"}``），避免泄漏 "Authorization: Bearer
#: xyz" / "password=hunter2" / 'token: abc123' 等形态。
_AUTHORIZATION_LINE_RE = re.compile(
    r"(?i)(?<![a-z0-9_])(authorization)\s*[:=]\s*([^\r\n]+)")
_KEY_VALUE_SECRET_RE = re.compile(
    r"(?i)(?<![a-z0-9_])(password|passwd|pwd|secret|bearer|"
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"private[_-]?key|cookie|token|auth[_-]?token)\s*[\"']?([:=])\s*[\"']?"
    r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[a-z0-9._~+/=-]{3,})")
_AUTH_SCHEME_TOKEN_RE = re.compile(
    r"(?i)(?<![a-z0-9_])(bearer|basic|digest)\s+([a-z0-9._~+/=-]{3,})")


def _redact_secret_values(text: str) -> str:
    """字符串内的秘密值形态脱敏（保留标签、替换秘密部分为 [REDACTED]）。

    顺序：authorization 整行优先（贪婪吞掉头值）→ 键值形态 → 独立
    Bearer/Basic 凭证形态。任何替换后都不含原文秘密。
    """
    text = _AUTHORIZATION_LINE_RE.sub(r"\1: [REDACTED]", text)
    text = _KEY_VALUE_SECRET_RE.sub(r"\1\2 [REDACTED]", text)
    text = _AUTH_SCHEME_TOKEN_RE.sub(r"\1 [REDACTED]", text)
    return text


def _validate_payload_budget(value: Any) -> int:
    """max_payload_bytes 严格校验：type-is-int（bool 不算）、不低于最小预算、不超上限。

    最小预算保证 truncation marker 自身也落在预算内（fail-closed：不允许声称允许
    1 byte 却返回超过 1 byte 的 JSON）。
    """
    if type(value) is not int or not (_MIN_PAYLOAD_BUDGET <= value <= _MAX_PAYLOAD_BUDGET):
        raise EventNormalizationError(
            f"max_payload_bytes 必须是 type-int 且 {_MIN_PAYLOAD_BUDGET} <= n <= "
            f"{_MAX_PAYLOAD_BUDGET}（bool/float/低于最小预算/超上限一律拒绝），得到 {value!r}")
    return value


def _sanitize_value(value: Any, depth: int) -> Any:
    """递归清洗：秘密脱敏 / 控制字符清除 / 字符串限长 / JSON-safe 化 / 深度有界。"""
    if depth > _MAX_DEPTH:
        return None
    if isinstance(value, str):
        s = _redact_secret_values(value)
        s = _CTRL_RE.sub(" ", s)
        return s[:_STRING_CAP] if len(s) > _STRING_CAP else s
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None:
        return None
    if isinstance(value, Mapping):
        out: dict = {}
        for k, v in value.items():
            if not isinstance(k, str):
                continue
            key = _CTRL_RE.sub(" ", k)[:128]
            if _is_secret_key(key):
                out[key] = "[REDACTED]"
            else:
                cleaned = _sanitize_value(v, depth + 1)
                if cleaned is None and v is not None:
                    continue   # 非 JSON-safe 值丢弃整键（不把任意 repr 泄入信封）
                out[key] = cleaned
        return out
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(v, depth + 1) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return _sanitize_value(value.decode("utf-8", errors="replace"), depth + 1)
    return None   # 其它对象一律丢弃（不把任意 repr 泄入信封）


def sanitize_payload(payload: Any, *, max_bytes: int = _DEFAULT_MAX_BYTES) -> Mapping[str, Any]:
    """payload 脱敏 + 有界大小：返回 JSON-safe dict（总序列化 **UTF-8 字节** <= max_bytes）。

    - 超限判据是 ``len(encoded.encode("utf-8"))``（真实 UTF-8 字节），不是字符数——
      多字节字符（如 é）不得以字符数绕过预算；
    - ``original_bytes`` 记录真实 UTF-8 字节数；
    - truncation marker 自身也落在预算内（ASCII 形态最坏 ~64B < 最小预算 128）。
    """
    budget = _validate_payload_budget(max_bytes)
    tree = _sanitize_value(payload if isinstance(payload, Mapping) else {}, 0)
    if not isinstance(tree, dict):
        tree = {}
    try:
        encoded = json.dumps(tree, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                             default=str)
    except Exception as exc:  # noqa: BLE001 —— 防御性：确定性清洗树不应序列化失败
        return {"_truncated": True, "byte_budget": budget,
                "original_bytes": -1, "reason": type(exc).__name__}
    encoded_bytes = encoded.encode("utf-8")
    if len(encoded_bytes) > budget:
        return {
            "_truncated": True,
            "byte_budget": budget,
            "original_bytes": len(encoded_bytes),
        }
    return tree


def deep_freeze(obj: Any) -> Any:
    """递归冻结：Mapping → MappingProxyType，list/tuple → tuple（信封载荷不可变）。"""
    if isinstance(obj, Mapping):
        return MappingProxyType({k: deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(deep_freeze(v) for v in obj)
    return obj


# ---------------------------------------------------------------------------
# NormalizedEvent —— backend-neutral 事件信封
# ---------------------------------------------------------------------------
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")


def _clean_id(value: Any, field: str, pattern: Any = None, *, max_len: int = 128) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventNormalizationError(f"{field} 必须是非空 str，得到 {value!r}")
    s = value.strip()
    if _CTRL_RE.search(s):
        raise EventNormalizationError(f"{field} 含控制字符，得到 {s!r}")
    if len(s) > max_len:
        raise EventNormalizationError(f"{field} 超长（>{max_len}），得到 {len(s)} 字符")
    if pattern is not None and not pattern.match(s):
        raise EventNormalizationError(f"{field} 词法非法: {s!r}")
    return s


def _finite_ts(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EventNormalizationError(f"{field} 必须是非 bool 数值，得到 {value!r}")
    f = float(value)
    if not math.isfinite(f) or f < 0:
        raise EventNormalizationError(f"{field} 必须有限且 >= 0，得到 {value!r}")
    return f


class NormalizedEvent:
    """不可变 canonical 事件信封（16E 唯一对外事件类型）。

    - ``terminal`` / ``critical`` 由 kind **派生**（构造时计算，来源方不可自证）；
    - payload 构造时自动脱敏 + 递归冻结 + 大小有界；
    - 未知外部类型仍以 ``kind=UNKNOWN_EVENT`` 可观察，但**绝不可能产生成功转移**。
    """

    __slots__ = (
        "_backend_id",
        "_contract_id",
        "_critical",
        "_event_id",
        "_kind",
        "_occurred_at",
        "_payload",
        "_provenance",
        "_received_at",
        "_run_id",
        "_sequence",
        "_terminal",
    )

    def __init__(
        self,
        *,
        event_id: str,
        backend_id: str,
        contract_id: str,
        run_id: str,
        sequence: int,
        occurred_at: float,
        received_at: float,
        kind: EventKind,
        payload: Optional[Mapping[str, Any]] = None,
        provenance: str = "normalized",
        max_payload_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        if not isinstance(kind, EventKind):
            raise EventNormalizationError(f"kind 必须是 EventKind，得到 {kind!r}")
        if isinstance(sequence, bool) or type(sequence) is not int or sequence < 0:
            raise EventNormalizationError(
                f"sequence 必须是 >=0 的 int（bool 不算），得到 {sequence!r}")
        self._event_id = _clean_id(event_id, "event_id", _ID_PATTERN)
        self._backend_id = _clean_id(backend_id, "backend_id", _ID_PATTERN)
        self._contract_id = _clean_id(contract_id, "contract_id")
        self._run_id = _clean_id(run_id, "run_id", _ID_PATTERN)
        self._sequence = sequence
        self._occurred_at = _finite_ts(occurred_at, "occurred_at")
        self._received_at = _finite_ts(received_at, "received_at")
        self._kind = kind
        self._payload = deep_freeze(sanitize_payload(
            payload or {}, max_bytes=_validate_payload_budget(max_payload_bytes)))
        self._terminal = kind in TERMINAL_KINDS
        self._critical = classify_priority(kind) is EventPriority.CRITICAL
        self._provenance = _clean_id(provenance, "provenance")

    # -- 只读访问（信封不可变）---------------------------------------------------
    @property
    def event_id(self) -> str:
        return self._event_id

    @property
    def backend_id(self) -> str:
        return self._backend_id

    @property
    def contract_id(self) -> str:
        return self._contract_id

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def occurred_at(self) -> float:
        return self._occurred_at

    @property
    def received_at(self) -> float:
        return self._received_at

    @property
    def kind(self) -> EventKind:
        return self._kind

    @property
    def payload(self) -> Mapping[str, Any]:
        return self._payload

    @property
    def terminal(self) -> bool:
        return self._terminal

    @property
    def critical(self) -> bool:
        return self._critical

    @property
    def provenance(self) -> str:
        return self._provenance

    # -- 便利 -------------------------------------------------------------------
    def to_dict(self) -> Mapping[str, Any]:
        """防御复制导出（tests / 审计引用；不暴露内部可变引用）。"""
        return MappingProxyType({
            "event_id": self._event_id,
            "backend_id": self._backend_id,
            "contract_id": self._contract_id,
            "run_id": self._run_id,
            "sequence": self._sequence,
            "occurred_at": self._occurred_at,
            "received_at": self._received_at,
            "kind": self._kind.value,
            "payload": deep_freeze(dict(self._payload)),
            "terminal": self._terminal,
            "critical": self._critical,
            "provenance": self._provenance,
        })

    def __repr__(self) -> str:  # pragma: no cover —— 调试辅助
        return (f"NormalizedEvent(kind={self._kind.value}, run={self._run_id}, "
                f"seq={self._sequence}, id={self._event_id!r})")


def _default_now() -> float:
    return time.time()
