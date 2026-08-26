"""C6 — Life / Event Timeline（append-only ledger）。

- 存客观事实；**不得把 interpretation 写进 payload**（"用户可能讨厌我" 是 interpretation）。
- payload whitelist/normalize + 长度限制；禁止 raw screenshots / API keys / 完整 system prompts。
- 同一 event_id 不可悄悄 overwrite（INSERT 而非 REPLACE）。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from furina.core import get_logger
from ..models import LifeEvent
from .base import CognitionDB, _json_safe_payload, redact_text

log = get_logger("cognition.event_timeline")

# 允许的 event_type 白名单（客观事件；新类型须显式登记，防任意字符串污染）
_EVENT_TYPES = (
    "USER_MESSAGE", "DIRECT_TURN_STARTED", "DIRECT_TURN_TERMINAL", "FURINA_SPOKE",
    "USER_PET", "USER_POKE", "USER_CLICK", "USER_DRAG",
    "USER_FEED", "USER_STATEMENT_OBSERVED",
    "ACTIVITY_STARTED", "ACTIVITY_FINISHED", "ACTIVITY_INTERRUPTED",
    "MEANINGFUL_INTERACTION",
    "AGENT_STARTED", "AGENT_COMPLETED", "AGENT_FAILED", "AGENT_UNVERIFIED",
    "AGENT_CANCELLED",
    "FILE_CREATED", "FILE_MOVED", "FILE_MODIFIED", "FILE_DELETED",
    "DOCUMENT_CREATED", "APP_LAUNCHED", "BROWSER_OPENED",
    "USER_PLAN_DECLARED", "USER_PREFERENCE_DECLARED",
    "RELATIONSHIP_MILESTONE", "MEMORY_FORMED", "SYSTEM_EVENT",
)


class EventTimelineStore:
    """C6 唯一写 owner（append-only）。"""

    def __init__(self, db: CognitionDB, session_id: str = "") -> None:
        self._db = db
        self._session_id = session_id

    # -------------------------------------------------- append（append-only）
    def append(self, *, event_type: str, payload: Optional[Dict[str, Any]] = None,
               source: str = "runtime", actor: str = "furina", channel: str = "",
               turn_id: Optional[int] = None, task_id: str = "",
               importance: float = 0.0, event_id: str = "",
               timestamp_wall: Optional[float] = None,
               timestamp_monotonic_session: Optional[float] = None) -> LifeEvent:
        """追加一条客观事件。event_id 给定且已存在 → 抛错（不可悄悄 overwrite）。"""
        etype = event_type if event_type in _EVENT_TYPES else "SYSTEM_EVENT"
        wall = time.time() if timestamp_wall is None else float(timestamp_wall)
        mono = time.monotonic() if timestamp_monotonic_session is None else float(timestamp_monotonic_session)
        eid = event_id or f"lev_{int(wall*1000)}_{uuid.uuid4().hex[:8]}"
        # payload 清洗：whitelist/normalize + redaction（长文本截断）
        safe_payload = _json_safe_payload(payload or {}, max_len=2000)
        if isinstance(payload, dict):
            for k in ("content", "text", "note", "summary", "excerpt"):
                if k in payload and isinstance(payload[k], str):
                    safe = redact_text(payload[k])[:500]
                    try:
                        d = json.loads(safe_payload)
                        d[k] = safe
                        safe_payload = json.dumps(d, ensure_ascii=False)
                    except Exception:
                        pass
        row = (eid, etype, wall, mono, self._session_id, source, actor, channel,
               turn_id, task_id, safe_payload, float(importance), wall)
        try:
            self._db.execute(
                "INSERT INTO life_events(event_id,event_type,timestamp_wall,"
                "timestamp_monotonic_session,session_id,source,actor,channel,turn_id,"
                "task_id,payload_json,importance,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                row)
        except Exception as e:
            if "UNIQUE" in str(e).upper():
                raise ValueError(f"event_id 已存在，append-only 不允许 overwrite: {eid}") from e
            raise
        return LifeEvent(
            event_id=eid, event_type=etype, timestamp_wall=wall,
            timestamp_monotonic_session=mono, session_id=self._session_id,
            source=source, actor=actor, channel=channel, turn_id=turn_id,
            task_id=task_id, payload_json=safe_payload, importance=float(importance),
            created_at=wall)

    # -------------------------------------------------- queries
    def query_recent(self, limit: int = 5, event_type: Optional[str] = None) -> List[LifeEvent]:
        sql = "SELECT * FROM life_events"
        args: List = []
        if event_type:
            sql += " WHERE event_type=?"
            args.append(event_type)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        return [LifeEvent.from_row(r) for r in self._db.query_all(sql, args)]

    def query_by_type(self, event_type: str, limit: int = 20) -> List[LifeEvent]:
        return self.query_recent(limit=limit, event_type=event_type)

    def query_by_turn(self, turn_id: int) -> List[LifeEvent]:
        rows = self._db.query_all(
            "SELECT * FROM life_events WHERE turn_id=? ORDER BY created_at ASC", (turn_id,))
        return [LifeEvent.from_row(r) for r in rows]

    def query_by_task(self, task_id: str) -> List[LifeEvent]:
        rows = self._db.query_all(
            "SELECT * FROM life_events WHERE task_id=? ORDER BY created_at ASC", (task_id,))
        return [LifeEvent.from_row(r) for r in rows]

    def query_time_range(self, start_wall: float, end_wall: float) -> List[LifeEvent]:
        rows = self._db.query_all(
            "SELECT * FROM life_events WHERE timestamp_wall BETWEEN ? AND ? "
            "ORDER BY timestamp_wall ASC", (start_wall, end_wall))
        return [LifeEvent.from_row(r) for r in rows]

    # -------------------------------------------------- deletion API
    def clear(self) -> int:
        """清空事件历史（deletion API）。返回删除条数。"""
        n = self._db.count("life_events")
        self._db.execute("DELETE FROM life_events")
        return n

    def count(self) -> int:
        return self._db.count("life_events")

    @staticmethod
    def register_event_type(event_type: str) -> None:
        """运行时登记新 event_type（白名单扩展点；避免任意字符串）。"""
        if event_type not in _EVENT_TYPES:
            _EVENT_TYPES += (event_type,)
