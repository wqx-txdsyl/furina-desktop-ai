"""Cognition 共享存储基座：SQLite 连接 + schema version + redaction。

- 复用现有 furina.db（或 configured DB）；全部 CREATE TABLE IF NOT EXISTS。
- 无 destructive migration：只加表/列，绝不删除/清空用户数据。
- busy_timeout + RLock 串行化（线程安全）；明确 transaction boundary。
- 隐私：redact_args / redact_text 用于 Tool args / Event payload 落库前清洗。
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from furina.core import get_logger

log = get_logger("cognition.store")

# 敏感 token 模式（写库前必须从 args/文本中剔除；匹配即整段替换为 <REDACTED>）
_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|apikey|token|secret|password|passwd|pwd|cookie|session[_-]?secret)"
               r"\s*[=:]\s*\S+"),
    re.compile(r"(?i)(authorization|bearer)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(sk-[A-Za-z0-9]{8,}|zhipu[_-]?[A-Za-z0-9]{8,})"),
]

_COGNITION_SCHEMA = """
CREATE TABLE IF NOT EXISTS cognition_meta(
    key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS user_model_items(
    item_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.5,
    source_event_id TEXT NOT NULL DEFAULT '',
    source_text_excerpt TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    valid_from REAL NOT NULL DEFAULT 0,
    valid_to REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS life_events(
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    timestamp_wall REAL NOT NULL DEFAULT 0,
    timestamp_monotonic_session REAL NOT NULL DEFAULT 0,
    session_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    turn_id INTEGER,
    task_id TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    importance REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS agent_tasks(
    task_id TEXT PRIMARY KEY,
    original_request TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'PLANNED',
    started_at REAL NOT NULL DEFAULT 0,
    finished_at REAL NOT NULL DEFAULT 0,
    permission_summary TEXT NOT NULL DEFAULT '',
    plan_json TEXT NOT NULL DEFAULT '{}',
    verified INTEGER NOT NULL DEFAULT 0,
    result_summary TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS agent_task_steps(
    task_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    capability TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL DEFAULT '',
    args_redacted_json TEXT NOT NULL DEFAULT '{}',
    permission_level TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'PLANNED',
    verified INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (task_id, step_index)
);
CREATE TABLE IF NOT EXISTS agent_artifacts(
    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    exists_verified INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS relationship_milestones(
    milestone_id INTEGER PRIMARY KEY AUTOINCREMENT,
    milestone_type TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    timestamp REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS event_processing(
    event_id TEXT PRIMARY KEY,
    process_version TEXT NOT NULL,
    processed_at REAL NOT NULL DEFAULT 0
);
"""

_SCHEMA_VERSION = "1"


def redact_text(text: str) -> str:
    """从自由文本中剔除敏感 token（API keys / passwords / tokens / cookies / secrets）。"""
    out = str(text or "")
    for pat in _SENSITIVE_PATTERNS:
        out = pat.sub("<REDACTED>", out)
    return out


def redact_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """Tool args 写 Task History 前 redaction：剔除敏感键 + 敏感值模式。

    路径可以记录（用户任务的 artifact 定位需要），但不读入无关文件内容。
    """
    out: Dict[str, Any] = {}
    for k, v in (args or {}).items():
        kl = str(k).lower()
        if any(s in kl for s in ("key", "token", "secret", "password", "passwd", "pwd",
                                 "cookie", "auth", "session")):
            out[k] = "<REDACTED>"
            continue
        if isinstance(v, str):
            rv = redact_text(v)
            out[k] = rv if len(rv) <= 2000 else rv[:2000] + "...<truncated>"
        elif isinstance(v, (dict, list)):
            try:
                s = json.dumps(v, ensure_ascii=False, default=str)
                out[k] = redact_text(s)[:2000]
            except Exception:
                out[k] = "<unserializable>"
        elif v is None or isinstance(v, (bool, int, float)):
            out[k] = v
        else:
            out[k] = str(v)[:200]
    return out


def _json_safe_payload(payload: Dict[str, Any], max_len: int = 2000) -> str:
    """Event payload whitelist/normalize：只允许 JSON-safe 原始类型；长度受限；绝不 repr(object)。"""
    def _norm(v: Any, depth: int = 0) -> Any:
        if depth > 4:
            return "<too-deep>"
        if v is None or isinstance(v, (bool, int, float, str)):
            return v
        if isinstance(v, dict):
            return {str(k): _norm(val, depth + 1) for k, val in list(v.items())[:32]}
        if isinstance(v, (list, tuple)):
            return [_norm(x, depth + 1) for x in list(v)[:32]]
        return str(v)[:200]
    normalized = _norm(payload or {})
    try:
        s = json.dumps(normalized, ensure_ascii=False, default=str)
    except Exception:
        s = "{}"
    return s if len(s) <= max_len else s[:max_len] + "...<truncated>"


_COGNITION_MIGRATIONS = [
    # Phase 15D：C4 temporal scope（forward migration，幂等：列已存在则跳过）
    ("ALTER TABLE user_model_items ADD COLUMN temporal_uncertain INTEGER NOT NULL DEFAULT 0",
     "temporal_uncertain"),
    ("ALTER TABLE user_model_items ADD COLUMN declared_at REAL NOT NULL DEFAULT 0",
     "declared_at"),
    # Phase 15.1：C5 milestone → C6 evidence provenance（forward，幂等，非破坏）
    ("ALTER TABLE relationship_milestones ADD COLUMN source_event_id TEXT NOT NULL DEFAULT ''",
     "source_event_id"),
]


class CognitionDB:
    """共享 SQLite 连接（与 MemoryStore 同库不同连接；busy_timeout + RLock）。"""

    def __init__(self, db_path: Path) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._path = Path(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False,
                                     timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_COGNITION_SCHEMA)
            for sql, _col in _COGNITION_MIGRATIONS:
                try:
                    self._conn.execute(sql)
                    self._conn.commit()
                except sqlite3.OperationalError:
                    pass          # 列已存在
            self._conn.commit()
        self._version = self._load_version()

    # -------------------------------------------------- schema version
    def _load_version(self) -> str:
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT value FROM cognition_meta WHERE key='schema_version'").fetchone()
                if row is not None:
                    return str(row["value"])
                self._conn.execute(
                    "INSERT OR REPLACE INTO cognition_meta(key,value) VALUES('schema_version',?)",
                    (_SCHEMA_VERSION,))
                self._conn.commit()
                return _SCHEMA_VERSION
        except Exception:
            return _SCHEMA_VERSION

    @property
    def schema_version(self) -> str:
        return self._version

    # -------------------------------------------------- 查询/写入 helpers
    def execute(self, sql: str, args: Sequence = ()) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(sql, args)

    def executemany(self, sql: str, seq_args: List[tuple]) -> None:
        with self._lock:
            with self._conn:
                self._conn.executemany(sql, seq_args)

    def query_all(self, sql: str, args: Sequence = ()) -> List[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, args).fetchall())

    def query_one(self, sql: str, args: Sequence = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def count(self, table: str) -> int:
        with self._lock:
            row = self._conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
            return int(row["c"]) if row is not None else 0

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
