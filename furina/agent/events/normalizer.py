"""Phase 16E — BackendEventNormalizer：外部 backend 词表 → canonical 事件信封。

- **外部词表是输入**（16B BackendEvent / 任意 Mapping；Hermes-shaped fixture 只作
  输入映射测试，生产类型无 Hermes 专属字段）；
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
from typing import Any, Mapping, Optional

from furina.agent.backend.models import BackendEvent

from .models import (
    EventKind,
    EventNormalizationError,
    NormalizedEvent,
    _default_now,
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


def _first_str(mapping: Mapping[str, Any], keys: tuple) -> Optional[str]:
    for k in keys:
        v = mapping.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def _first_int(mapping: Mapping[str, Any], keys: tuple) -> Optional[int]:
    for k in keys:
        v = mapping.get(k)
        if isinstance(v, bool):
            continue
        if type(v) is int and v >= 0:
            return v
    return None


def _first_float(mapping: Mapping[str, Any], keys: tuple) -> Optional[float]:
    for k in keys:
        v = mapping.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _first_mapping(mapping: Mapping[str, Any], keys: tuple) -> Optional[Mapping[str, Any]]:
    for k in keys:
        v = mapping.get(k)
        if isinstance(v, Mapping):
            return v
    return None


def _derive_event_id(backend_id: str, run_id: str, token: str, payload: Any) -> str:
    """内容寻址的派生事件 id：同一逻辑事件重复投递 → 同一 id（幂等去重基础）。"""
    try:
        canon = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except Exception as exc:  # noqa: BLE001 —— 防御性：非 JSON-safe 载荷退化
        canon = f"<unserializable:{type(exc).__name__}>"
    digest = hashlib.sha256(f"{token}|{canon}".encode()).hexdigest()[:16]
    return f"bev_{backend_id[:16]}_{run_id[:16]}_{digest}"


class BackendEventNormalizer:
    """backend-neutral 归一器：16B BackendEvent / Mapping → NormalizedEvent。

    构造绑定 backend_id/contract_id/run_id（信封恒等；缺 event_id 时派生稳定 id，
    缺 sequence 时按到达顺序补序——同一输入流重复归一结果完全一致）。
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
        self._max_payload_bytes = int(max_payload_bytes)
        self._seq_counter = 0

    # -- 公共入口 ----------------------------------------------------------------
    def normalize(self, raw: Any) -> NormalizedEvent:
        """任意外部事件 → canonical 信封。未知类型 → UNKNOWN_EVENT（非权威，不抛）。"""
        if isinstance(raw, BackendEvent):
            return self._from_backend_event(raw)
        if isinstance(raw, Mapping):
            return self._from_mapping(raw)
        raise EventNormalizationError(
            f"raw 必须是 BackendEvent 或 Mapping，得到 {type(raw).__name__}")

    # -- 16B typed 引用 ----------------------------------------------------------
    def _from_backend_event(self, be: BackendEvent) -> NormalizedEvent:
        token = be.event_type if isinstance(be.event_type, str) else ""
        kind = map_kind(token)
        payload = be.payload if isinstance(be.payload, Mapping) else {}
        now = self._now_fn()
        return NormalizedEvent(
            event_id=_derive_event_id(be.backend_id, be.run_id, token, payload),
            backend_id=be.backend_id,
            contract_id=self._contract_id,
            run_id=be.run_id,
            sequence=self._next_seq(),
            occurred_at=now,
            received_at=now,
            kind=kind,
            payload=payload,
            provenance=f"backend_event:{be.backend_id}",
            max_payload_bytes=self._max_payload_bytes,
        )

    # -- 通用 Mapping 形状（含 Hermes-shaped fixture）-----------------------------
    def _from_mapping(self, raw: Mapping[str, Any]) -> NormalizedEvent:
        token = _first_str(raw, _KIND_KEYS) or ""
        kind = map_kind(token)
        payload = _first_mapping(raw, _PAYLOAD_KEYS) or {}
        now = self._now_fn()
        event_id = _first_str(raw, _EVENT_ID_KEYS)
        if event_id is None:
            event_id = _derive_event_id(self._backend_id, self._run_id, token, payload)
        sequence = _first_int(raw, _SEQ_KEYS)
        if sequence is None:
            sequence = self._next_seq()
        occurred_at = _first_float(raw, _TS_KEYS)
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
