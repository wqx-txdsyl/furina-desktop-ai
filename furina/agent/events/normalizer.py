"""Phase 16E — BackendEventNormalizer：外部 backend 词表 → canonical 事件信封。

- **外部词表是输入**（16B BackendEvent / 任意 Mapping；Hermes-shaped fixture 只作
  输入映射测试，生产类型无 Hermes 专属字段）；
- **别名无歧义**（Reviewer Patch 2）：身份字段所有已出现别名逐一校验等于绑定值；
  event_id/sequence/时间戳/kind/payload 的多个别名同时出现时等值允许、冲突拒绝；
  显式出现但类型/范围非法不得当作缺失补值；
- **fallback event_id 每次到达唯一**（arrival ordinal 独立递增，显式/补序/重复
  sequence 均不得碰撞；fresh normalizer 重放同一输入流确定性一致）；
- 未知外部类型映射为 ``UNKNOWN_EVENT``（typed、可观察、**非权威**——normalizer
  绝不抛出、绝不把未知输入当成功）；
- **归一 ≠ 状态**：normalizer 只产出信封；状态转移唯一由
  :class:`~furina.agent.events.reducer.WorkExecutionReducer` 拥有；
- 词表对齐 Hermes ``_set_run_status``（queued/running/waiting_for_approval/
  stopping/completed/cancelled/failed）+ SSE 事件面（approval.request/tool.*/
  message.delta/reasoning*）；SSE done 哨兵按**非权威帧标记**处理（UNKNOWN_EVENT，
  provenance 注明 sentinel，绝不自造 completed）。
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Optional

from furina.agent.backend.models import BackendEvent

from .models import (
    EventKind,
    EventNormalizationError,
    NormalizedEvent,
    _default_now,
    _validate_payload_budget,
)

# ---------------------------------------------------------------------------
# 外部词表 → canonical 类型（确定性映射；未列出的 token → UNKNOWN_EVENT）
# ---------------------------------------------------------------------------
_KIND_ALIASES: dict = {
    # run accepted / started（Hermes: queued / running）
    "run.accepted": EventKind.RUN_ACCEPTED,
    "run_accepted": EventKind.RUN_ACCEPTED,
    "accepted": EventKind.RUN_ACCEPTED,
    "submitted": EventKind.RUN_ACCEPTED,
    "run.submitted": EventKind.RUN_ACCEPTED,
    "queued": EventKind.RUN_ACCEPTED,
    "run.started": EventKind.RUN_STARTED,
    "run_started": EventKind.RUN_STARTED,
    "started": EventKind.RUN_STARTED,
    "running": EventKind.RUN_STARTED,
    "run.running": EventKind.RUN_STARTED,
    # approval（Hermes: waiting_for_approval / approval.request）
    "approval.requested": EventKind.APPROVAL_REQUESTED,
    "approval_requested": EventKind.APPROVAL_REQUESTED,
    "approval.request": EventKind.APPROVAL_REQUESTED,
    "approval.requested.waiting": EventKind.APPROVAL_REQUESTED,
    "waiting_for_approval": EventKind.APPROVAL_REQUESTED,
    "waiting_for_approval_request": EventKind.APPROVAL_REQUESTED,
    "approval.resolved": EventKind.APPROVAL_RESOLVED,
    "approval_resolved": EventKind.APPROVAL_RESOLVED,
    "approval.resolve": EventKind.APPROVAL_RESOLVED,
    "approval.decision": EventKind.APPROVAL_RESOLVED,
    "approval": EventKind.APPROVAL_RESOLVED,
    # tool 生命周期
    "tool.started": EventKind.TOOL_STARTED,
    "tool_started": EventKind.TOOL_STARTED,
    "tool.progress": EventKind.TOOL_PROGRESS,
    "tool_progress": EventKind.TOOL_PROGRESS,
    "progress": EventKind.TOOL_PROGRESS,
    "message.delta": EventKind.TOOL_PROGRESS,
    "message_delta": EventKind.TOOL_PROGRESS,
    "reasoning": EventKind.TOOL_PROGRESS,
    "reasoning.delta": EventKind.TOOL_PROGRESS,
    "reasoning_update": EventKind.TOOL_PROGRESS,
    "tool.completed": EventKind.TOOL_COMPLETED,
    "tool_completed": EventKind.TOOL_COMPLETED,
    "tool.finished": EventKind.TOOL_COMPLETED,
    "tool_finished": EventKind.TOOL_COMPLETED,
    # backend 终态（Hermes: completed/cancelled/failed）
    "backend.completed": EventKind.BACKEND_COMPLETED,
    "backend_completed": EventKind.BACKEND_COMPLETED,
    "run.completed": EventKind.BACKEND_COMPLETED,
    "run_completed": EventKind.BACKEND_COMPLETED,
    "completed": EventKind.BACKEND_COMPLETED,
    "success": EventKind.BACKEND_COMPLETED,
    "backend.failed": EventKind.BACKEND_FAILED,
    "backend_failed": EventKind.BACKEND_FAILED,
    "run.failed": EventKind.BACKEND_FAILED,
    "run_failed": EventKind.BACKEND_FAILED,
    "failed": EventKind.BACKEND_FAILED,
    "failure": EventKind.BACKEND_FAILED,
    "error": EventKind.BACKEND_FAILED,
    "backend.cancelled": EventKind.BACKEND_CANCELLED,
    "backend_cancelled": EventKind.BACKEND_CANCELLED,
    "run.cancelled": EventKind.BACKEND_CANCELLED,
    "run_cancelled": EventKind.BACKEND_CANCELLED,
    "cancelled": EventKind.BACKEND_CANCELLED,
    "canceled": EventKind.BACKEND_CANCELLED,
    "cancel": EventKind.BACKEND_CANCELLED,
    # 停止
    "stop.requested": EventKind.STOP_REQUESTED,
    "stop_requested": EventKind.STOP_REQUESTED,
    "stop.request": EventKind.STOP_REQUESTED,
    "stop": EventKind.STOP_REQUESTED,
    "stopping": EventKind.STOPPING,
    "stop.stopping": EventKind.STOPPING,
    "stop_stopping": EventKind.STOPPING,
    # transport
    "transport.disconnected": EventKind.TRANSPORT_DISCONNECTED,
    "transport_disconnected": EventKind.TRANSPORT_DISCONNECTED,
    "disconnected": EventKind.TRANSPORT_DISCONNECTED,
    "disconnect": EventKind.TRANSPORT_DISCONNECTED,
    "sse.disconnected": EventKind.TRANSPORT_DISCONNECTED,
    "stream.disconnected": EventKind.TRANSPORT_DISCONNECTED,
    "transport.reconnected": EventKind.TRANSPORT_RECONNECTED,
    "transport_reconnected": EventKind.TRANSPORT_RECONNECTED,
    "reconnected": EventKind.TRANSPORT_RECONNECTED,
    "reconnect": EventKind.TRANSPORT_RECONNECTED,
    "sse.reconnected": EventKind.TRANSPORT_RECONNECTED,
    # 协议错误
    "protocol.error": EventKind.PROTOCOL_ERROR,
    "protocol_error": EventKind.PROTOCOL_ERROR,
    "error.protocol": EventKind.PROTOCOL_ERROR,
    "sse.error": EventKind.PROTOCOL_ERROR,
    "stream.error": EventKind.PROTOCOL_ERROR,
}

#: 非权威帧标记（SSE done 哨兵 / 心跳等）：可观察但**绝不**映射为 backend 终态。
_NON_AUTHORITATIVE_TOKENS = frozenset({
    "done", "[done]", "stream_done", "sse_done", "sentinel",
    "heartbeat", "ping", "keepalive",
})

#: 事件类型字段候选键（按优先级取第一个 str）。
_KIND_KEYS = ("kind", "event_type", "eventType", "type", "status")
_EVENT_ID_KEYS = ("event_id", "eventId", "id")
_SEQ_KEYS = ("sequence", "seq", "number")
_TS_KEYS = ("occurred_at", "occurredAt", "timestamp", "ts", "time")
_PAYLOAD_KEYS = ("payload", "data", "body", "result")

#: Mapping 形状中的身份字段候选键（normalizer 构造绑定；**携带即必须一致**，
#: 不一致直接拒绝——禁止静默改绑）。
_IDENTITY_KEYS: dict = {
    "backend_id": ("backend_id", "backendId"),
    "contract_id": ("contract_id", "contractId"),
    "run_id": ("run_id", "runId"),
}


def map_kind(token: Any) -> EventKind:
    """外部 token → canonical EventKind（未知/非权威 → UNKNOWN_EVENT，绝不抛错）。"""
    if isinstance(token, EventKind):
        return token
    if not isinstance(token, str) or not token.strip():
        return EventKind.UNKNOWN_EVENT
    norm = token.strip().lower()
    if norm in _NON_AUTHORITATIVE_TOKENS:
        return EventKind.UNKNOWN_EVENT
    return _KIND_ALIASES.get(norm, EventKind.UNKNOWN_EVENT)


def _present_aliases(mapping: Mapping[str, Any], keys: tuple) -> list:
    """keys 中所有**出现**的 (key, value)（无论值类型；显式出现即视为携带）。"""
    return [(k, mapping[k]) for k in keys if k in mapping]


def _kind_token(mapping: Mapping[str, Any]) -> str:
    """kind 类别名：所有出现的键必须是非空 str 且映射到同一 canonical kind。

    等值允许、冲突值拒绝；显式出现但非法（非 str / 空）直接拒绝——不得当作缺失补值。
    """
    present = _present_aliases(mapping, _KIND_KEYS)
    if not present:
        return ""
    token: Optional[str] = None
    mapped: Optional[EventKind] = None
    for k, v in present:
        if not isinstance(v, str) or not v.strip():
            raise EventNormalizationError(
                f"raw.{k} 显式出现但非法（必须是非空 str），得到 {v!r}；不得当作缺失补值")
        s = v.strip()
        m = map_kind(s)
        if token is None:
            token, mapped = s, m
        elif m is not mapped:
            raise EventNormalizationError(
                f"kind 别名冲突：raw.{k}={s!r} 映射 {m.value!r}，"
                f"与既有 {mapped.value!r} 不一致（等值允许，冲突拒绝）")
    assert token is not None
    return token


def _event_id_value(mapping: Mapping[str, Any]) -> Optional[str]:
    """event_id 类别名：所有出现的键必须是非空 str 且等值；冲突拒绝。

    显式出现但类型非法（非 str / 空）直接拒绝——不得当作缺失自动补值（非法值不
    回退到派生 id）。词法/长度由 NormalizedEvent 构造再校验。
    """
    present = _present_aliases(mapping, _EVENT_ID_KEYS)
    if not present:
        return None
    value: Optional[str] = None
    for k, v in present:
        if not isinstance(v, str) or not v.strip():
            raise EventNormalizationError(
                f"raw.{k} 显式出现但非法（必须是非空 str），得到 {v!r}；不得当作缺失补值")
        s = v.strip()
        if value is None:
            value = s
        elif s != value:
            raise EventNormalizationError(
                f"event_id 别名冲突：raw.{k}={s!r} != {value!r}（等值允许，冲突拒绝）")
    assert value is not None
    return value


def _sequence_value(mapping: Mapping[str, Any]) -> Optional[int]:
    """sequence 类别名：所有出现的键必须是非 bool int >= 0 且等值；冲突拒绝。

    显式出现但类型/范围非法直接拒绝——不得当作缺失自动补序。
    """
    present = _present_aliases(mapping, _SEQ_KEYS)
    if not present:
        return None
    value: Optional[int] = None
    for k, v in present:
        if isinstance(v, bool) or type(v) is not int or v < 0:
            raise EventNormalizationError(
                f"raw.{k} 显式出现但非法（必须是非 bool int >= 0），得到 {v!r}；"
                "不得当作缺失补值")
        if value is None:
            value = v
        elif v != value:
            raise EventNormalizationError(
                f"sequence 别名冲突：raw.{k}={v!r} != {value!r}（等值允许，冲突拒绝）")
    assert value is not None
    return value


def _ts_value(mapping: Mapping[str, Any]) -> Optional[float]:
    """时间戳类别名：所有出现的键必须是非 bool 有限数值 >= 0 且等值；冲突拒绝。

    显式出现但类型/范围非法直接拒绝——不得当作缺失自动取 now。
    """
    present = _present_aliases(mapping, _TS_KEYS)
    if not present:
        return None
    value: Optional[float] = None
    for k, v in present:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise EventNormalizationError(
                f"raw.{k} 显式出现但非法（必须是非 bool 数值），得到 {v!r}；"
                "不得当作缺失补值")
        f = float(v)
        if not math.isfinite(f) or f < 0:
            raise EventNormalizationError(
                f"raw.{k} 显式出现但非法（必须有限且 >= 0），得到 {v!r}；不得当作缺失补值")
        if value is None:
            value = f
        elif f != value:
            raise EventNormalizationError(
                f"时间戳别名冲突：raw.{k}={v!r} != {value!r}（等值允许，冲突拒绝）")
    assert value is not None
    return value


def _payload_mapping(mapping: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """payload 类别名：所有出现的键必须是 Mapping 且等值；冲突拒绝。

    显式出现但类型非法直接拒绝——不得当作缺失自动取空。
    """
    present = _present_aliases(mapping, _PAYLOAD_KEYS)
    if not present:
        return None
    value: Optional[Mapping[str, Any]] = None
    for k, v in present:
        if not isinstance(v, Mapping):
            raise EventNormalizationError(
                f"raw.{k} 显式出现但非法（必须是 Mapping），得到 {type(v).__name__!r}；"
                "不得当作缺失补值")
        if value is None:
            value = v
        elif v != value:
            raise EventNormalizationError(
                f"payload 别名冲突：raw.{k} 与既有 payload 不等（等值允许，冲突拒绝）")
    assert value is not None
    return value


def _derive_event_id(backend_id: str, run_id: str, token: str, payload: Any,
                     sequence: int, arrival: int) -> str:
    """内容寻址的派生事件 id（缺上游稳定 event_id 时的 fallback）。

    派生 id 纳入 **arrival ordinal**（每次 normalize 到达独立递增）：保证同一归一化
    会话内每次到达唯一——显式 sequence 后接缺 sequence（补序可能与显式值重复）、
    重复显式 sequence、混合流均不得碰撞；同内容的两次事件是两次**不同**事件，不得
    被误去重。fresh normalizer 重放同一完整输入流（arrival 递增顺序相同）→ 派生 id
    完全一致（确定性）。只有上游显式提供的稳定 event_id 才享有强重投幂等。
    """
    try:
        canon = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except Exception as exc:  # noqa: BLE001 —— 防御性：非 JSON-safe 载荷退化
        canon = f"<unserializable:{type(exc).__name__}>"
    digest = hashlib.sha256(
        f"{token}|{arrival}|{sequence}|{canon}".encode()).hexdigest()[:16]
    return f"bev_{backend_id[:16]}_{run_id[:16]}_{digest}"


def _check_mapping_identity(normalizer_backend_id: str, normalizer_contract_id: str,
                            normalizer_run_id: str, raw: Mapping[str, Any]) -> None:
    """Mapping 若携带身份字段，**所有已出现别名**都必须是非空 str 且等于绑定值。

    逐一校验全部别名（不得检查第一个后 break）：任一别名非 str / 值不一致一律
    EventNormalizationError，禁止静默改绑。
    """
    for field, keys in _IDENTITY_KEYS.items():
        for k in keys:
            if k not in raw:
                continue
            v = raw[k]
            bound = {"backend_id": normalizer_backend_id,
                     "contract_id": normalizer_contract_id,
                     "run_id": normalizer_run_id}[field]
            if not isinstance(v, str) or not v.strip():
                raise EventNormalizationError(
                    f"raw.{k} 必须是非空 str，得到 {v!r}（身份字段不得以非 str 携带）")
            if v.strip() != bound:
                raise EventNormalizationError(
                    f"raw.{k}={v.strip()!r} 与 normalizer 绑定 {field}={bound!r} 不一致"
                    "（禁止静默改绑）")


class BackendEventNormalizer:
    """backend-neutral 归一器：16B BackendEvent / Mapping → NormalizedEvent。

    构造绑定 backend_id/contract_id/run_id（信封恒等）；**身份不一致直接拒绝**：
    BackendEvent 的 backend_id/run_id、Mapping 携带的身份字段（所有已出现别名）
    都必须与绑定一致，不静默改绑。**别名无歧义**：event_id/sequence/时间戳/kind/
    payload 的多个别名同时出现时等值允许、冲突值拒绝；显式出现但类型/范围非法
    不得当作缺失补值。缺 event_id 时按到达顺序内容寻址派生（fallback id 含
    **arrival ordinal**——每次到达唯一，显式/补序/重复 sequence 均不得碰撞）；
    缺 sequence 时按到达顺序补序——同一输入流重复归一结果完全一致。
    """

    def __init__(
        self,
        *,
        backend_id: str,
        contract_id: str,
        run_id: str,
        now_fn=_default_now,
        max_payload_bytes: int = 4096,
    ) -> None:
        for name, v in (("backend_id", backend_id), ("contract_id", contract_id),
                        ("run_id", run_id)):
            if not isinstance(v, str) or not v.strip():
                raise EventNormalizationError(f"{name} 必须是非空 str，得到 {v!r}")
        self._backend_id = backend_id.strip()
        self._contract_id = contract_id.strip()
        self._run_id = run_id.strip()
        self._now_fn = now_fn
        self._max_payload_bytes = _validate_payload_budget(max_payload_bytes)
        self._seq_counter = 0
        self._arrival_counter = 0   # 每次 normalize 到达独立递增（fallback id 唯一性）

    # -- 公共入口 ----------------------------------------------------------------
    def normalize(self, raw: Any) -> NormalizedEvent:
        """任意外部事件 → canonical 信封。未知类型 → UNKNOWN_EVENT（非权威，不抛）。"""
        self._arrival_counter += 1
        if isinstance(raw, BackendEvent):
            return self._from_backend_event(raw, self._arrival_counter)
        if isinstance(raw, Mapping):
            return self._from_mapping(raw, self._arrival_counter)
        raise EventNormalizationError(
            f"raw 必须是 BackendEvent 或 Mapping，得到 {type(raw).__name__}")

    # -- 16B typed 引用 ----------------------------------------------------------
    def _from_backend_event(self, be: BackendEvent, arrival: int) -> NormalizedEvent:
        if be.backend_id != self._backend_id:
            raise EventNormalizationError(
                f"BackendEvent.backend_id={be.backend_id!r} 与 normalizer 绑定 "
                f"{self._backend_id!r} 不一致（禁止静默改绑）")
        if be.run_id != self._run_id:
            raise EventNormalizationError(
                f"BackendEvent.run_id={be.run_id!r} 与 normalizer 绑定 {self._run_id!r}"
                " 不一致（禁止静默改绑）")
        token = be.event_type if isinstance(be.event_type, str) else ""
        kind = map_kind(token)
        payload = be.payload if isinstance(be.payload, Mapping) else {}
        now = self._now_fn()
        sequence = self._next_seq()
        return NormalizedEvent(
            event_id=_derive_event_id(self._backend_id, self._run_id, token, payload,
                                      sequence, arrival),
            backend_id=self._backend_id,
            contract_id=self._contract_id,
            run_id=self._run_id,
            sequence=sequence,
            occurred_at=now,
            received_at=now,
            kind=kind,
            payload=payload,
            provenance=f"backend_event:{self._backend_id}",
            max_payload_bytes=self._max_payload_bytes,
        )

    # -- 通用 Mapping 形状（含 Hermes-shaped fixture）-----------------------------
    def _from_mapping(self, raw: Mapping[str, Any], arrival: int) -> NormalizedEvent:
        _check_mapping_identity(self._backend_id, self._contract_id, self._run_id, raw)
        token = _kind_token(raw)
        kind = map_kind(token)
        payload = _payload_mapping(raw) or {}
        now = self._now_fn()
        sequence = _sequence_value(raw)
        if sequence is None:
            sequence = self._next_seq()
        event_id = _event_id_value(raw)
        if event_id is None:
            event_id = _derive_event_id(self._backend_id, self._run_id, token, payload,
                                        sequence, arrival)
        occurred_at = _ts_value(raw)
        if occurred_at is None:
            occurred_at = now
        provenance = raw.get("provenance")
        if not isinstance(provenance, str) or not provenance.strip():
            if kind is EventKind.UNKNOWN_EVENT and token.lower() in _NON_AUTHORITATIVE_TOKENS:
                provenance = f"external:{token.strip().lower()}"
            else:
                provenance = f"external:{kind.value}"
        return NormalizedEvent(
            event_id=event_id,
            backend_id=self._backend_id,
            contract_id=self._contract_id,
            run_id=self._run_id,
            sequence=sequence,
            occurred_at=occurred_at,
            received_at=now,
            kind=kind,
            payload=payload,
            provenance=provenance.strip(),
            max_payload_bytes=self._max_payload_bytes,
        )

    # -- 内部 -------------------------------------------------------------------
    def _next_seq(self) -> int:
        seq = self._seq_counter
        self._seq_counter += 1
        return seq
