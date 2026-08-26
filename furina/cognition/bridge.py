"""C6 Runtime Event Bridge（Phase 14.1 §7）—— curated production event bridge。

- **不无脑 mirror 全 EventBus payload**：只记录白名单客观事件，payload redaction + bounded。
- 唯一 owner / no duplicate：`record_unique(key, ...)` 以稳定 key 去重（同一 turn_id / task_id
  只记一次）。
- turn_id / task_id linkage：USER_MESSAGE / DIRECT_TURN_STARTED / DIRECT_TURN_TERMINAL /
  FURINA_SPOKE 带 turn_id；AGENT_* 带 task_id。
- 不记录：system prompt / API key / screenshot raw bytes / secret env（payload 走
  event_timeline 的 whitelist/normalize/redaction）。
- 精确信息（artifact/file result）由 C7 保存；C6 只记 objective event reference。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from furina.core import get_logger

log = get_logger("cognition.bridge")

# 允许桥接的 event_type 白名单（curated；不含自由 payload 镜像）
_BRIDGE_TYPES = (
    "USER_MESSAGE", "DIRECT_TURN_STARTED", "DIRECT_TURN_TERMINAL", "FURINA_SPOKE",
    "MEANINGFUL_INTERACTION", "ACTIVITY_STARTED", "ACTIVITY_FINISHED", "ACTIVITY_INTERRUPTED",
    "AGENT_STARTED", "AGENT_COMPLETED", "AGENT_FAILED", "AGENT_UNVERIFIED", "AGENT_CANCELLED",
)


class EventBridge:
    """App owner 侧 curated 事件桥：dedupe + 落 C6（append-only）。"""

    def __init__(self, hub, max_seen: int = 4000) -> None:
        self._hub = hub
        self._seen: Dict[str, bool] = {}
        self._max_seen = max_seen

    # -------------------------------------------------- record
    def record(self, event_type: str, *, key: str, payload: Optional[Dict[str, Any]] = None,
               source: str = "runtime", channel: str = "", turn_id: Optional[int] = None,
               task_id: str = "", importance: float = 0.0) -> bool:
        """记录客观事件；同 key 已记录 → 跳过（exactly-once）。返回是否新记录。"""
        if event_type not in _BRIDGE_TYPES:
            log.debug("bridge: 未登记事件类型 %s（忽略）", event_type)
            return False
        if not key:
            key = f"{event_type}:{turn_id or task_id or id(payload)}"
        if key in self._seen:
            return False                       # no duplicate
        self._seen[key] = True
        if len(self._seen) > self._max_seen:
            self._trim()
        self._hub.events.append(
            event_type=event_type, payload=payload or {}, source=source,
            channel=channel, turn_id=turn_id, task_id=task_id, importance=importance)
        # Phase 15F：event terminal trigger —— 追加后由 owner 立即做 bounded 批处理
        # （idempotent：event_processing log 保证 restart/重复调用不重复 consolidation）。
        try:
            self._hub.process_pending(batch=5)
        except Exception:
            pass
        return True

    def _trim(self) -> None:
        # 有界去重缓存：保留最近一半（新事件不受影响）
        keys = list(self._seen.keys())
        for k in keys[: len(keys) // 2]:
            self._seen.pop(k, None)

    def query_recent(self, limit: int = 20):
        return self._hub.events.query_recent(limit=limit)

    def query_by_turn(self, turn_id: int):
        return self._hub.events.query_by_turn(turn_id)

    def query_by_task(self, task_id: str):
        return self._hub.events.query_by_task(task_id)
