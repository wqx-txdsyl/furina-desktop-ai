"""记忆存储：SQLite 结构化 + 向量（legacy-plan/6 §24-25）。

结构化：时间/类型/强度/关系/来源/状态（SQL 擅长）；
向量：语义检索。骨架先落结构化，向量用 JSON 列占位，后续接 embedding 模型。

Phase 10.5 (RC1)：线程安全修复。
- check_same_thread=False：允许后台线程（LifeBrain 决策线程）访问同一连接。
- threading.RLock 保护**所有**连接/游标操作（query/insert/delete/commit/close）：
  因为即使关闭同线程检查，共享连接并发操作 cursor/transaction 状态仍会出错
  （OperationalError / InterfaceError）。校验读中可能写（retrieve→reinforce），RLock 防自死锁。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from furina.core import get_logger
from .memory_types import Memory, MemoryLevel, MemorySource, MemoryStatus, RelationshipState

log = get_logger("memory.store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories(
    mem_id TEXT PRIMARY KEY,
    level TEXT, content TEXT, source TEXT,
    importance REAL, confidence REAL,
    timestamp REAL, context TEXT, outcome TEXT, participants TEXT,
    strength REAL, last_recalled REAL, last_reinforced REAL,
    valid_from REAL, valid_to REAL, status TEXT,
    relationship_delta TEXT, embedding TEXT
);
CREATE TABLE IF NOT EXISTS relationship(
    name TEXT PRIMARY KEY, value REAL
);
"""

_MIGRATIONS = [
    ("ALTER TABLE memories ADD COLUMN tags TEXT", "tags"),
    ("ALTER TABLE memories ADD COLUMN event_type TEXT", "event_type"),
    ("ALTER TABLE memories ADD COLUMN world_context TEXT", "world_context"),
    ("ALTER TABLE memories ADD COLUMN recurrence_count INTEGER DEFAULT 0", "recurrence_count"),
    ("ALTER TABLE memories ADD COLUMN summary TEXT", "summary"),
]


class MemoryStore:
    """记忆存储（线程安全：共享连接 + RLock 串行化所有操作）。"""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = db_path
        # RC1：允许后台线程访问同一连接（LifeBrain 决策线程、并发读写）。
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row       # query() 需要按列名访问
        with self._lock:
            self._conn.executescript(_SCHEMA)
            # Phase 07 最小 schema 扩展：仅当列不存在才 ADD（兼容旧 DB）
            for sql, col in _MIGRATIONS:
                try:
                    self._conn.execute(sql)
                    self._conn.commit()
                except sqlite3.OperationalError:
                    pass   # 列已存在
            self._conn.commit()

    # -------------------------------------------------- write
    def insert(self, m: Memory) -> str:
        if not m.mem_id:
            m.mem_id = f"mem_{int(time.time()*1000)}_{abs(hash(m.content)) % 10**6}"
        row = {
            "mem_id": m.mem_id, "level": m.level.value, "content": m.content,
            "source": m.source.value, "importance": m.importance, "confidence": m.confidence,
            "timestamp": m.timestamp, "context": m.context, "outcome": m.outcome,
            "participants": m.participants, "strength": m.strength,
            "last_recalled": m.last_recalled, "last_reinforced": m.last_reinforced,
            "valid_from": m.valid_from, "valid_to": m.valid_to, "status": m.status.value,
            "relationship_delta": json.dumps(m.relationship_delta, ensure_ascii=False),
            "embedding": json.dumps(m.embedding),
            "tags": json.dumps(getattr(m, "tags", []), ensure_ascii=False),
            "event_type": getattr(m, "event_type", ""),
            "world_context": getattr(m, "world_context", ""),
            "recurrence_count": int(getattr(m, "recurrence_count", 0)),
            "summary": getattr(m, "summary", ""),
        }
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO memories(mem_id,level,content,source,importance,confidence,"
                    "timestamp,context,outcome,participants,strength,last_recalled,last_reinforced,"
                    "valid_from,valid_to,status,relationship_delta,embedding,tags,event_type,"
                    "world_context,recurrence_count,summary) "
                    "VALUES(:mem_id,:level,:content,:source,:importance,:confidence,:timestamp,:context,"
                    ":outcome,:participants,:strength,:last_recalled,:last_reinforced,:valid_from,:valid_to,"
                    ":status,:relationship_delta,:embedding,:tags,:event_type,:world_context,"
                    ":recurrence_count,:summary)", row)
        return m.mem_id

    # -------------------------------------------------- read
    def count(self, *, status: Optional[MemoryStatus] = MemoryStatus.ACTIVE) -> int:
        """真实记忆条数（Phase 13 终审 §14：Harness 展示 COUNT=n 用真数，不用 query(limit=1) 的 0/1）。"""
        sql = "SELECT COUNT(*) FROM memories WHERE 1=1"
        args: List = []
        if status is not None:
            sql += " AND status=?"
            args.append(status.value)
        with self._lock:
            cur = self._conn.execute(sql, args)
            return int(cur.fetchone()[0])

    def query(self, *, level: Optional[MemoryLevel] = None, status: Optional[MemoryStatus] = MemoryStatus.ACTIVE,
              source: Optional[MemorySource] = None, limit: int = 50,
              content_like: Optional[str] = None) -> List[Memory]:
        sql = "SELECT * FROM memories WHERE 1=1"
        args: List = []
        if level:
            sql += " AND level=?"
            args.append(level.value)
        if source:
            sql += " AND source=?"
            args.append(source.value)
        if status is not None:
            sql += " AND status=?"
            args.append(status.value)
        if content_like:
            sql += " AND content LIKE ?"
            args.append(f"%{content_like}%")
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            cur = self._conn.execute(sql, args)
            rows = [self._to_memory(r) for r in cur.fetchall()]
        return rows

    def delete(self, mem_id: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM memories WHERE mem_id=?", (mem_id,))

    def recall_recent(self, n: int = 10) -> List[Memory]:
        return self.query(limit=n)

    # -------------------------------------------------- relationship
    def save_relationship(self, rel: RelationshipState) -> None:
        with self._lock:
            with self._conn:
                for k, v in rel.as_dict().items():
                    self._conn.execute(
                        "INSERT OR REPLACE INTO relationship(name,value) VALUES(?,?)", (k, v))

    def load_relationship(self) -> RelationshipState:
        rel = RelationshipState()
        with self._lock:
            for name, value in self._conn.execute("SELECT name,value FROM relationship"):
                if hasattr(rel, name):
                    setattr(rel, name, value)
        return rel

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _to_memory(row: sqlite3.Row) -> Memory:
        try:
            tags = json.loads(row["tags"] or "[]")
        except Exception:
            tags = []
        return Memory(
            mem_id=row["mem_id"], level=MemoryLevel(row["level"]), content=row["content"],
            source=MemorySource(row["source"]), importance=row["importance"],
            confidence=row["confidence"], timestamp=row["timestamp"], context=row["context"],
            outcome=row["outcome"], participants=row["participants"], strength=row["strength"],
            last_recalled=row["last_recalled"], last_reinforced=row["last_reinforced"],
            valid_from=row["valid_from"], valid_to=row["valid_to"], status=MemoryStatus(row["status"]),
            relationship_delta=json.loads(row["relationship_delta"] or "{}"),
            embedding=json.loads(row["embedding"] or "[]"),
            tags=tags,
            event_type=row["event_type"] if "event_type" in row.keys() else "",
            world_context=row["world_context"] if "world_context" in row.keys() else "",
            recurrence_count=int(row["recurrence_count"] or 0) if "recurrence_count" in row.keys() else 0,
            summary=row["summary"] if "summary" in row.keys() else "",
        )
