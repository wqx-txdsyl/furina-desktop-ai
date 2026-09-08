"""Phase 16H v3 — Durable Work Ledger（Reviewer Patch 2 结构性封闭版）。

权威边界（16H 任务书 §1–3 + Reviewer Patch 1 B1–B6 + Patch 2 十组 blocker）：

- 独立 work-domain SQLite 持久化；不是 cognition store；WorkExecutionState
  只进入工作域表；truth-commit 只提供 claim/CAS API，零 C7/C6/C3 写入。
- **VERIFIED 唯一入口**：mark_verified_by_outcome——exact IndependentVerifier /
  exact RepairOutcome / 类拥有 outcome_is_authentic / run 已绑定非空 / 当前
  状态属于明确授权验证前驱（BACKEND_DONE_UNVERIFIED 或 recovery-UNKNOWN）/
  持久化 terminal evidence 非空且与传入 evidence 精确绑定 / report_digest
  64-hex / execution+attempt 同事务更新（两边谓词+rowcount）。
- **generic transition 显式合法迁移表**：VERIFIED/TOOL_RUNNING 永不合法；
  UNKNOWN absorbing（generic 不得迁出——恢复走 recovery-only authority
  method begin_reconciliation）；CANCELLING 只能收口 CANCELLED/FAILED。
- **跨连接真 CAS**：全部 mutation 单事务 UPDATE...WHERE version/谓词 +
  rowcount==1；attempt 同步失配 → CorruptionError。
- **migration**：显式事务（不用 executescript）、真实 v1→v3 数据保留
  （legacy 契约 transport 不可恢复 → legacy_unrecoverable 标记）、
  v2→v3 补列、future 拒绝、结构复核（表/列/索引）、幂等 reopen。
- **corruption fail-closed**：读取面损坏 JSON/state/version/time →
  CorruptionError；now_fn 严格校验。
- **attempt ledger**：attempt_id write-once（冲突类型化拒绝）；execution+
  attempt 同事务同步（两边谓词+rowcount，失配 → CorruptionError）。
"""
from __future__ import annotations

import enum
import json
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from furina.agent.backend.protocol import ExecutionBackend
from furina.agent.events.models import (
    EventKind,
    classify_priority,
    sanitize_payload,
)
from furina.agent.events.reducer import WorkExecutionState
from furina.agent.work_contract import WorkContract
from furina.core import FurinaError

__all__ = [
    "CommitClaimConflict",
    "ContractIdentityConflict",
    "CorruptionError",
    "CriticalBufferOverflow",
    "DuplicateActiveExecution",
    "EventBufferOutcome",
    "EventContentConflict",
    "ExecutionRecord",
    "IllegalTransition",
    "LegacyContractUnrecoverable",
    "RunBindingConflict",
    "StaleStateVersion",
    "UnknownExecution",
    "WorkContractReloadError",
    "WorkEventBuffer",
    "WorkLedger",
    "WorkLedgerError",
]

_TERMINAL_STATES = frozenset({
    WorkExecutionState.CANCELLED,
    WorkExecutionState.VERIFIED,
    WorkExecutionState.FAILED,
})

_ALLOWED_TRANSITIONS: Dict[WorkExecutionState, frozenset] = {
    WorkExecutionState.STARTING: frozenset({
        WorkExecutionState.RUNNING, WorkExecutionState.WAITING_PERMISSION,
        WorkExecutionState.BLOCKED_APPROVAL, WorkExecutionState.CANCELLING,
        WorkExecutionState.FAILED,
        WorkExecutionState.BACKEND_DONE_UNVERIFIED, WorkExecutionState.CANCELLED,
    }),
    WorkExecutionState.RUNNING: frozenset({
        WorkExecutionState.WAITING_PERMISSION,
        WorkExecutionState.BLOCKED_APPROVAL, WorkExecutionState.VERIFYING,
        WorkExecutionState.REPAIRING, WorkExecutionState.CANCELLING,
        WorkExecutionState.FAILED,
        WorkExecutionState.BACKEND_DONE_UNVERIFIED, WorkExecutionState.CANCELLED,
    }),
    WorkExecutionState.WAITING_PERMISSION: frozenset({
        WorkExecutionState.RUNNING, WorkExecutionState.BLOCKED_APPROVAL,
        WorkExecutionState.CANCELLING, WorkExecutionState.FAILED,
        WorkExecutionState.CANCELLED,
        WorkExecutionState.BACKEND_DONE_UNVERIFIED,
    }),
    WorkExecutionState.BLOCKED_APPROVAL: frozenset({
        WorkExecutionState.CANCELLING, WorkExecutionState.FAILED,
        WorkExecutionState.CANCELLED,
        WorkExecutionState.BACKEND_DONE_UNVERIFIED,
    }),
    WorkExecutionState.VERIFYING: frozenset({
        WorkExecutionState.REPAIRING, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
        WorkExecutionState.FAILED, WorkExecutionState.CANCELLING,
        WorkExecutionState.CANCELLED,
    }),
    WorkExecutionState.REPAIRING: frozenset({
        WorkExecutionState.VERIFYING, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
        WorkExecutionState.FAILED, WorkExecutionState.CANCELLING,
        WorkExecutionState.CANCELLED,
    }),
    WorkExecutionState.BACKEND_DONE_UNVERIFIED: frozenset({
        WorkExecutionState.VERIFYING, WorkExecutionState.REPAIRING,
        WorkExecutionState.FAILED, WorkExecutionState.CANCELLING,
        WorkExecutionState.CANCELLED,
    }),
    WorkExecutionState.CANCELLING: frozenset({
        WorkExecutionState.CANCELLED, WorkExecutionState.FAILED,
    }),
    WorkExecutionState.UNKNOWN: frozenset(),   # absorbing
}

_COUNTER_NAMES = frozenset({
    "critical_overflow", "progress_dropped", "progress_upserts",
    "coalesced", "duplicates",
})

_MAX_EVENTS_PER_RUN_LIMIT = 10_000
_MAX_GLOBAL_EVENTS_LIMIT = 100_000
_MAX_PAYLOAD_BYTES_LIMIT = 1 << 20

DEFAULT_EVENTS_PER_RUN = 256
DEFAULT_MAX_GLOBAL_EVENTS = 4096
DEFAULT_MAX_PAYLOAD_BYTES = 4096

_SCHEMA_VERSION = "16H.3"
_KNOWN_USER_VERSIONS = (1, 2, 3)
_CURRENT_USER_VERSION = 3

_CURRENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_schema_meta(
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_contracts(
    contract_id TEXT PRIMARY KEY, contract_hash TEXT NOT NULL,
    transport_json TEXT NOT NULL DEFAULT '',
    legacy_unrecoverable INTEGER NOT NULL DEFAULT 0,
    registered_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS work_executions(
    execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id TEXT NOT NULL, contract_hash TEXT NOT NULL DEFAULT '',
    attempt_id TEXT NOT NULL, run_id TEXT NOT NULL DEFAULT '',
    backend_id TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    cancel_intent INTEGER NOT NULL DEFAULT 0,
    stop_dispatched INTEGER NOT NULL DEFAULT 0,
    approval_id TEXT NOT NULL DEFAULT '',
    approval_invalidated INTEGER NOT NULL DEFAULT 0,
    submit_intent_json TEXT NOT NULL DEFAULT '{}',
    submit_intent_at REAL NOT NULL DEFAULT 0,
    run_bound_at REAL NOT NULL DEFAULT 0,
    terminal_evidence_json TEXT NOT NULL DEFAULT '',
    verification_marker TEXT NOT NULL DEFAULT '',
    verification_verified INTEGER NOT NULL DEFAULT 0,
    overflow_marker TEXT NOT NULL DEFAULT '',
    truth_commit_owner TEXT NOT NULL DEFAULT '',
    truth_commit_digest TEXT NOT NULL DEFAULT '',
    truth_commit_status TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_work_one_active
    ON work_executions(contract_id) WHERE is_active = 1;
CREATE TABLE IF NOT EXISTS work_attempts(
    attempt_id TEXT PRIMARY KEY, execution_id INTEGER NOT NULL,
    contract_id TEXT NOT NULL, contract_hash TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '', backend_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL, state_version INTEGER NOT NULL DEFAULT 1,
    started_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_work_attempts_run
    ON work_attempts(run_id) WHERE run_id <> '';
CREATE TABLE IF NOT EXISTS work_events(
    execution_id INTEGER NOT NULL, event_id TEXT NOT NULL,
    kind TEXT NOT NULL, payload_json TEXT NOT NULL,
    critical INTEGER NOT NULL, received_at REAL NOT NULL,
    PRIMARY KEY (execution_id, event_id)
);
CREATE TABLE IF NOT EXISTS work_progress(
    execution_id INTEGER PRIMARY KEY,
    payload_json TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS work_counters(
    name TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0
);
"""

_REQUIRED_TABLES = ("work_contracts", "work_executions", "work_events",
                    "work_counters", "work_attempts", "work_progress",
                    "work_schema_meta")

_REQUIRED_COLUMNS = {
    "work_contracts": ("contract_id", "contract_hash", "transport_json",
                       "legacy_unrecoverable"),
    "work_executions": ("execution_id", "contract_id", "contract_hash",
                        "attempt_id", "state", "state_version", "is_active",
                        "verification_marker", "verification_verified",
                        "overflow_marker", "approval_id"),
    "work_attempts": ("attempt_id", "execution_id", "run_id", "state"),
    "work_events": ("execution_id", "event_id"),
    "work_progress": ("execution_id", "payload_json"),
    "work_counters": ("name", "value"),
}


class WorkLedgerError(FurinaError):
    """16H 工作域 ledger 统一异常基类。"""


class ContractIdentityConflict(WorkLedgerError):
    """同 contract_id、不同 contract_hash。"""


class LegacyContractUnrecoverable(WorkLedgerError):
    """v1 legacy 契约缺少 transport JSON（manual recovery 状态）。"""


class DuplicateActiveExecution(WorkLedgerError):
    """同 contract 已存在 active execution claim。"""


class StaleStateVersion(WorkLedgerError):
    """CAS 失败：version/谓词过期（零状态修改）。"""


class EventContentConflict(WorkLedgerError):
    """同 (execution_id, event_id)、不同内容。"""


class UnknownExecution(WorkLedgerError):
    """execution_id 不存在。"""


class CriticalBufferOverflow(WorkLedgerError):
    """critical 容量耗尽（fail-closed + durable overflow marker）。"""


class CommitClaimConflict(WorkLedgerError):
    """truth-commit claim 前置不满足或已被认领。"""


class IllegalTransition(WorkLedgerError):
    """generic transition 目标不在合法迁移表内。"""


class RunBindingConflict(WorkLedgerError):
    """run/backend 绑定 write-once 冲突。"""


class WorkContractReloadError(WorkLedgerError):
    """持久化契约损坏/失配（fail-closed）。"""


class CorruptionError(WorkLedgerError):
    """持久化行损坏（typed fail-closed）。"""


def _reject_non_finite(value: Any, depth: int = 0) -> None:
    """NaN/Inf 明确拒绝（绝不"stored 也算通过"）。"""
    if depth > 8:
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise WorkLedgerError("payload 含 NaN/Inf（明确拒绝）")
    if isinstance(value, dict):
        for v in value.values():
            _reject_non_finite(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _reject_non_finite(v, depth + 1)


def _canonical_json(payload: Any, max_bytes: int) -> str:
    """exact dict、16E sanitize、canonical JSON（allow_nan=False）、尺寸有界
    （raw 体积前置拒绝——2MiB 级对象绝不静默截断常驻）。"""
    if payload is None:
        payload = {}
    if type(payload) is not dict:
        raise WorkLedgerError("payload 必须是 builtin dict（exact schema）")
    for key in payload:
        if type(key) is not str:
            raise WorkLedgerError("payload 键必须全为 builtin str")
    _reject_non_finite(payload)
    try:
        raw_len = len(json.dumps(payload, ensure_ascii=False,
                                 allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise WorkLedgerError(
            f"payload 无法序列化（{type(exc).__name__}）") from None
    if raw_len > max_bytes:
        raise WorkLedgerError(
            f"payload 原始体积 {raw_len} 字节超过 {max_bytes} 上限"
            f"（截断前拒绝）")
    clean = sanitize_payload(payload, max_bytes=max_bytes)
    try:
        blob = json.dumps(clean, sort_keys=True, ensure_ascii=True,
                          allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError) as exc:
        raise WorkLedgerError(
            f"payload 无法 canonical 化（{type(exc).__name__}）") from None
    return blob


def _is_terminal(state: WorkExecutionState) -> bool:
    return state in _TERMINAL_STATES


# Patch 6：terminal evidence exact 六键 schema（写入与验证双重执行）
_TERMINAL_EVIDENCE_KEYS = frozenset({
    "event_id", "kind", "run_id", "backend_id", "contract_id", "payload"})


def _finite_time(value: Any, field_name: str) -> float:
    if type(value) not in (int, float):
        raise CorruptionError(
            f"{field_name} 必须是 builtin int/float，得到 "
            f"{type(value).__name__}")
    v = float(value)
    if not math.isfinite(v):
        raise CorruptionError(f"{field_name} 必须是有限数值")
    return v


@dataclass(frozen=True)
class ExecutionRecord:
    """execution 的不可变快照。"""

    execution_id: int
    contract_id: str
    contract_hash: str
    attempt_id: str
    run_id: str
    backend_id: str
    state: WorkExecutionState
    state_version: int
    is_active: bool
    cancel_intent: bool
    stop_dispatched: bool
    approval_id: str
    approval_invalidated: bool
    submit_intent: Dict[str, Any] = field(default_factory=dict)
    submit_intent_at: float = 0.0
    run_bound_at: float = 0.0
    terminal_evidence: Dict[str, Any] = field(default_factory=dict)
    verification_marker: str = ""
    verification_verified: bool = False
    overflow_marker: str = ""
    truth_commit_owner: str = ""
    truth_commit_digest: str = ""
    truth_commit_status: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0


class WorkLedger:
    """工作域 durable ledger v3（独立 SQLite；跨连接真 CAS；真实 migration）。"""

    def __init__(self, db_path, *, now_fn=time.time,
                 max_events_per_run: int = DEFAULT_EVENTS_PER_RUN,
                 max_global_events: int = DEFAULT_MAX_GLOBAL_EVENTS,
                 max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES) -> None:
        if not callable(now_fn):
            raise WorkLedgerError("now_fn 必须是 callable")
        for name, value, limit in (
                ("max_events_per_run", max_events_per_run,
                 _MAX_EVENTS_PER_RUN_LIMIT),
                ("max_global_events", max_global_events,
                 _MAX_GLOBAL_EVENTS_LIMIT),
                ("max_payload_bytes", max_payload_bytes,
                 _MAX_PAYLOAD_BYTES_LIMIT)):
            if type(value) is not int or value < 1 or value > limit:
                raise WorkLedgerError(
                    f"{name} 必须是 [1, {limit}] 内的 builtin int（安全最大值"
                    f"封顶）")
        self._validate_now_fn(now_fn)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._path = Path(db_path)
        self._now_fn = now_fn
        self._max_events_per_run = max_events_per_run
        self._max_global_events = max_global_events
        self._max_payload_bytes = max_payload_bytes
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False,
                                     timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    @staticmethod
    def _validate_now_fn(fn) -> float:
        try:
            raw = fn()
        except Exception as exc:
            raise WorkLedgerError(
                f"now_fn 异常（{type(exc).__name__}）") from None
        if type(raw) not in (int, float):
            raise WorkLedgerError(
                f"now_fn 必须返回 builtin int/float，得到 {type(raw).__name__}")
        v = float(raw)
        if not math.isfinite(v):
            raise WorkLedgerError("now_fn 必须返回有限数值")
        return v

    def _now(self) -> float:
        raw = self._now_fn()
        if type(raw) not in (int, float):
            raise CorruptionError(
                f"clock 必须是 builtin int/float，得到 {type(raw).__name__}")
        v = float(raw)
        if not math.isfinite(v):
            raise CorruptionError("clock 必须是有限数值（NaN/Inf 拒绝）")
        return v

    # -------------------------------------------------- migration
    def _migrate(self) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                version = int(self._conn.execute(
                    "PRAGMA user_version").fetchone()[0])
                if version > _KNOWN_USER_VERSIONS[-1]:
                    raise WorkLedgerError(
                        f"work ledger user_version {version} 高于已知版本"
                        f" {max(_KNOWN_USER_VERSIONS)}（future schema 拒绝）")
                self._create_current_schema()
                if version == 1:
                    self._migrate_v1_to_v3()
                elif version == 2:
                    self._migrate_v2_to_v3()
                self._verify_structure()
                self._conn.execute(
                    f"PRAGMA user_version = {_CURRENT_USER_VERSION}")
                self._conn.execute(
                    "INSERT OR REPLACE INTO work_schema_meta(key,value) "
                    "VALUES('schema_version',?)", (_SCHEMA_VERSION,))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _create_current_schema(self) -> None:
        for stmt in _CURRENT_SCHEMA.split(";"):
            stmt = stmt.strip()
            if stmt:
                self._conn.execute(stmt)

    @staticmethod
    def _table_columns(conn, table: str) -> Dict[str, str]:
        return {r["name"]: str(r["type"] or "").upper()
                for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    def _migrate_v1_to_v3(self) -> None:
        """真实 16H.1 → 16H.3：保留全部数据行；v1 无法补出的契约 transport
        标记 legacy-unrecoverable（manual recovery）；旧 work_events
        (event_id PK) 迁移为复合身份。"""
        cols = self._table_columns(self._conn, "work_contracts")
        if "transport_json" not in cols:
            self._conn.execute(
                "ALTER TABLE work_contracts ADD COLUMN transport_json "
                "TEXT NOT NULL DEFAULT ''")
        if "legacy_unrecoverable" not in cols:
            self._conn.execute(
                "ALTER TABLE work_contracts ADD COLUMN legacy_unrecoverable "
                "INTEGER NOT NULL DEFAULT 0")
        self._conn.execute(
            "UPDATE work_contracts SET legacy_unrecoverable=1 "
            "WHERE transport_json=''")
        self._add_missing_execution_columns()
        rows = self._conn.execute(
            "SELECT event_id, execution_id, kind, payload_json, critical, "
            "received_at FROM work_events").fetchall()
        self._conn.execute("DROP TABLE work_events")
        self._conn.execute(
            "CREATE TABLE work_events("
            "execution_id INTEGER NOT NULL, event_id TEXT NOT NULL,"
            "kind TEXT NOT NULL, payload_json TEXT NOT NULL,"
            "critical INTEGER NOT NULL, received_at REAL NOT NULL,"
            "PRIMARY KEY (execution_id, event_id))")
        for r in rows:
            self._conn.execute(
                "INSERT INTO work_events(execution_id,event_id,kind,"
                "payload_json,critical,received_at) VALUES(?,?,?,?,?,?)",
                (int(r["execution_id"]), str(r["event_id"]), str(r["kind"]),
                 str(r["payload_json"]), int(r["critical"]),
                 float(r["received_at"])))
        self._create_attempts_table()
        for r in self._conn.execute(
                "SELECT attempt_id, execution_id, contract_id, run_id, "
                "backend_id, state, state_version, created_at, updated_at "
                "FROM work_executions").fetchall():
            # 获取 contract_hash
            ch = self._conn.execute(
                "SELECT contract_hash FROM work_contracts WHERE contract_id=?",
                (str(r["contract_id"]),)).fetchone()
            contract_hash = str(ch["contract_hash"]) if ch else ""
            self._conn.execute(
                "INSERT INTO work_attempts(attempt_id,execution_id,"
                "contract_id,contract_hash,run_id,backend_id,state,"
                "state_version,started_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (str(r["attempt_id"]), int(r["execution_id"]),
                 str(r["contract_id"]), contract_hash, str(r["run_id"]),
                 str(r["backend_id"]), str(r["state"]),
                 int(r["state_version"]), float(r["created_at"]),
                 float(r["updated_at"])))

    def _migrate_v2_to_v3(self) -> None:
        self._add_missing_execution_columns()
        # v2→v3：work_contracts 补 legacy_unrecoverable 列
        cols = self._table_columns(self._conn, "work_contracts")
        if "legacy_unrecoverable" not in cols:
            self._conn.execute(
                "ALTER TABLE work_contracts ADD COLUMN legacy_unrecoverable "
                "INTEGER NOT NULL DEFAULT 0")
        # v2→v3：真实 backfill work_attempts（v2 无独立 attempt 表）
        self._create_attempts_table()
        for r in self._conn.execute(
                "SELECT attempt_id, execution_id, contract_id, run_id, "
                "backend_id, state, state_version, created_at, updated_at "
                "FROM work_executions").fetchall():
            exists = self._conn.execute(
                "SELECT 1 FROM work_attempts WHERE attempt_id=?",
                (str(r["attempt_id"]),)).fetchone()
            if exists:
                continue
            ch = self._conn.execute(
                "SELECT contract_hash FROM work_contracts WHERE contract_id=?",
                (str(r["contract_id"]),)).fetchone()
            contract_hash = str(ch["contract_hash"]) if ch else ""
            self._conn.execute(
                "INSERT INTO work_attempts(attempt_id,execution_id,"
                "contract_id,contract_hash,run_id,backend_id,state,"
                "state_version,started_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (str(r["attempt_id"]), int(r["execution_id"]),
                 str(r["contract_id"]), contract_hash, str(r["run_id"]),
                 str(r["backend_id"]), str(r["state"]),
                 int(r["state_version"]), float(r["created_at"]),
                 float(r["updated_at"])))

    def _add_missing_execution_columns(self) -> None:
        cols = self._table_columns(self._conn, "work_executions")
        for col, decl in (
                ("contract_hash", "TEXT NOT NULL DEFAULT ''"),
                ("approval_id", "TEXT NOT NULL DEFAULT ''"),
                ("verification_verified", "INTEGER NOT NULL DEFAULT 0"),
                ("overflow_marker", "TEXT NOT NULL DEFAULT ''"),
                ("truth_commit_digest", "TEXT NOT NULL DEFAULT ''")):
            if col not in cols:
                self._conn.execute(
                    f"ALTER TABLE work_executions ADD COLUMN {col} {decl}")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS work_progress("
            "execution_id INTEGER PRIMARY KEY, payload_json TEXT NOT NULL,"
            "updated_at REAL NOT NULL)")
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_work_one_active "
            "ON work_executions(contract_id) WHERE is_active = 1")

    def _create_attempts_table(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS work_attempts("
            "attempt_id TEXT PRIMARY KEY, execution_id INTEGER NOT NULL,"
            "contract_id TEXT NOT NULL, contract_hash TEXT NOT NULL,"
            "run_id TEXT NOT NULL DEFAULT '', backend_id TEXT NOT NULL DEFAULT '',"
            "state TEXT NOT NULL, state_version INTEGER NOT NULL DEFAULT 1,"
            "started_at REAL NOT NULL, updated_at REAL NOT NULL)")
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_work_attempts_run "
            "ON work_attempts(run_id) WHERE run_id <> ''")

    def _verify_structure(self) -> None:
        tables = {r["name"] for r in self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for t in _REQUIRED_TABLES:
            if t not in tables:
                raise WorkLedgerError(f"work 表 {t} 缺失")
        for table, columns in _REQUIRED_COLUMNS.items():
            cols = {r["name"] for r in self._conn.execute(
                f"PRAGMA table_info({table})").fetchall()}
            missing = [c for c in columns if c not in cols]
            if missing:
                raise WorkLedgerError(
                    f"work 表 {table} 结构不兼容（缺列 {missing}）")
        idx = {r["name"] for r in self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        if "idx_work_one_active" not in idx:
            raise WorkLedgerError("idx_work_one_active 缺失")

    # -------------------------------------------------- 读取（corruption fail-closed）
    def _execution_row(self, conn: sqlite3.Connection,
                       execution_id: int) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM work_executions WHERE execution_id=?",
            (execution_id,)).fetchone()
        if row is None:
            raise UnknownExecution(f"execution {execution_id} 不存在")
        state = str(row["state"])
        try:
            WorkExecutionState(state)
        except ValueError:
            raise CorruptionError(
                f"execution {execution_id} 持久化 state 损坏: {state!r}"
            ) from None
        sv = row["state_version"]
        if type(sv) is not int or sv < 0:
            raise CorruptionError(
                f"execution {execution_id} state_version 损坏")
        return row

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ExecutionRecord:
        def _json(text: str) -> Dict[str, Any]:
            if not text:
                return {}
            try:
                value = json.loads(text)
            except Exception:
                raise CorruptionError("持久化 JSON 损坏（fail-closed）") from None
            if not isinstance(value, dict):
                raise CorruptionError("持久化 JSON 必须是 object")
            return value

        def _bool(name: str) -> bool:
            v = row[name]
            if type(v) is not int or v not in (0, 1):
                raise CorruptionError(f"{name} 持久化值损坏: {v!r}")
            return bool(v)

        state_raw = str(row["state"])
        try:
            state = WorkExecutionState(state_raw)
        except ValueError:
            raise CorruptionError(
                f"持久化 state 损坏: {state_raw!r}") from None
        sv = row["state_version"]
        if type(sv) is not int or sv < 0:
            raise CorruptionError("state_version 损坏")
        created = _finite_time(row["created_at"], "created_at")
        updated = _finite_time(row["updated_at"], "updated_at")
        sia = _finite_time(row["submit_intent_at"], "submit_intent_at")
        rba = _finite_time(row["run_bound_at"], "run_bound_at")
        return ExecutionRecord(
            execution_id=int(row["execution_id"]),
            contract_id=str(row["contract_id"]),
            contract_hash=str(row["contract_hash"]),
            attempt_id=str(row["attempt_id"]),
            run_id=str(row["run_id"]),
            backend_id=str(row["backend_id"]),
            state=state,
            state_version=int(sv),
            is_active=_bool("is_active"),
            cancel_intent=_bool("cancel_intent"),
            stop_dispatched=_bool("stop_dispatched"),
            approval_id=str(row["approval_id"]),
            approval_invalidated=_bool("approval_invalidated"),
            submit_intent=_json(str(row["submit_intent_json"])),
            submit_intent_at=sia,
            run_bound_at=rba,
            terminal_evidence=_json(str(row["terminal_evidence_json"])),
            verification_marker=str(row["verification_marker"]),
            verification_verified=_bool("verification_verified"),
            overflow_marker=str(row["overflow_marker"]),
            truth_commit_owner=str(row["truth_commit_owner"]),
            truth_commit_digest=str(row["truth_commit_digest"]),
            truth_commit_status=str(row["truth_commit_status"]),
            created_at=created,
            updated_at=updated,
        )

    def _incr_counter_locked(self, conn: sqlite3.Connection, name: str,
                             n: int = 1) -> None:
        if name not in _COUNTER_NAMES:
            raise WorkLedgerError(f"counter name 必须在封闭词表内，得到 {name!r}")
        if type(n) is not int or n < 1 or n > 1_000_000:
            raise WorkLedgerError("counter 增量必须是 [1, 1000000] 内的 int")
        conn.execute(
            "INSERT INTO work_counters(name,value) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET value = value + ?",
            (name, n, n))

    def incr_counter(self, name: str, n: int = 1) -> None:
        if type(n) is not int or n < 1 or n > 1_000_000:
            raise WorkLedgerError("counter 增量必须是 [1, 1000000] 内的 int")
        with self._lock:
            with self._conn:
                self._incr_counter_locked(self._conn, name, n)

    def counter(self, name: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM work_counters WHERE name=?", (name,)).fetchone()
            return int(row["value"]) if row is not None else 0

    # -------------------------------------------------- 契约身份
    def register_contract(self, contract: WorkContract) -> None:
        if type(contract) is not WorkContract:
            raise WorkLedgerError(
                f"contract 必须是 exact WorkContract，得到 "
                f"{type(contract).__name__}")
        transport = contract.to_transport_json()
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._conn.execute(
                    "SELECT contract_hash, transport_json, "
                    "legacy_unrecoverable FROM work_contracts "
                    "WHERE contract_id=?", (contract.contract_id,)).fetchone()
                if row is not None:
                    if str(row["contract_hash"]) != contract.content_hash:
                        raise ContractIdentityConflict(
                            f"contract_id {contract.contract_id} 已绑定不同 "
                            f"contract_hash（不可变身份冲突）")
                    if int(row["legacy_unrecoverable"]) == 1:
                        self._conn.execute(
                            "UPDATE work_contracts SET transport_json=?, "
                            "legacy_unrecoverable=0 WHERE contract_id=?",
                            (transport, contract.contract_id))
                        return
                    stored = str(row["transport_json"])
                    if stored and stored != transport:
                        raise CorruptionError(
                            f"contract {contract.contract_id} 持久化 transport "
                            f"与 canonical 不一致（损坏拒绝）")
                    if not stored:
                        self._conn.execute(
                            "UPDATE work_contracts SET transport_json=? "
                            "WHERE contract_id=?", (transport,
                                                    contract.contract_id))
                    return
                self._conn.execute(
                    "INSERT INTO work_contracts(contract_id,contract_hash,"
                    "transport_json,legacy_unrecoverable,registered_at) "
                    "VALUES(?,?,?,0,?)",
                    (contract.contract_id, contract.content_hash, transport,
                     now))

    def load_contract(self, contract_id: str) -> WorkContract:
        if type(contract_id) is not str:
            raise WorkLedgerError("contract_id 必须是 builtin str")
        with self._lock:
            row = self._conn.execute(
                "SELECT contract_hash, transport_json, legacy_unrecoverable "
                "FROM work_contracts WHERE contract_id=?",
                (contract_id,)).fetchone()
        if row is None:
            raise WorkContractReloadError(
                f"contract {contract_id} 未在 ledger 注册")
        if int(row["legacy_unrecoverable"]) == 1 or not str(row["transport_json"]):
            raise LegacyContractUnrecoverable(
                f"contract {contract_id} 为 v1 legacy（无 transport JSON）"
                f"——manual recovery 状态，禁止伪造恢复")
        blob = str(row["transport_json"])
        try:
            contract = WorkContract.from_transport_json(blob)
        except Exception as exc:
            raise WorkContractReloadError(
                f"contract {contract_id} transport JSON 损坏"
                f"（{type(exc).__name__}）") from None
        if contract.contract_id != contract_id \
                or contract.content_hash != str(row["contract_hash"]):
            raise WorkContractReloadError(
                f"contract {contract_id} 重载身份失配")
        return contract

    # -------------------------------------------------- submit intent
    def submit_intent(self, contract: WorkContract, attempt_id: str,
                      submit_payload: Optional[Mapping[str, Any]] = None) -> int:
        self.register_contract(contract)
        if type(attempt_id) is not str or not attempt_id or len(attempt_id) > 128:
            raise WorkLedgerError("attempt_id 必须是非空短 builtin str")
        blob = _canonical_json(submit_payload, self._max_payload_bytes)
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._conn.execute(
                    "SELECT execution_id FROM work_executions "
                    "WHERE contract_id=? AND is_active=1",
                    (contract.contract_id,)).fetchone()
                if row is not None:
                    raise DuplicateActiveExecution(
                        f"contract {contract.contract_id} 已有 active execution "
                        f"{int(row['execution_id'])}")
                attempt_exists = self._conn.execute(
                    "SELECT 1 FROM work_attempts WHERE attempt_id=?",
                    (attempt_id,)).fetchone()
                if attempt_exists:
                    raise WorkLedgerError(
                        f"attempt_id {attempt_id!r} 已存在（write-once 冲突，"
                        f"回滚 execution insert）")
                try:
                    cur = self._conn.execute(
                        "INSERT INTO work_executions(contract_id,contract_hash,"
                        "attempt_id,state,state_version,is_active,"
                        "submit_intent_json,submit_intent_at,created_at,"
                        "updated_at) VALUES(?,?,?,?,?,1,?,?,?,?)",
                        (contract.contract_id, contract.content_hash, attempt_id,
                         WorkExecutionState.STARTING.value, 1, blob, now, now,
                         now))
                except sqlite3.IntegrityError as exc:
                    raise DuplicateActiveExecution(
                        f"contract {contract.contract_id} active claim 并发冲突"
                        f"（{exc}）") from None
                eid = int(cur.lastrowid)
                try:
                    self._conn.execute(
                        "INSERT INTO work_attempts(attempt_id,execution_id,"
                        "contract_id,contract_hash,state,state_version,"
                        "started_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (attempt_id, eid, contract.contract_id,
                         contract.content_hash,
                         WorkExecutionState.STARTING.value, 1, now, now))
                except sqlite3.IntegrityError:
                    raise WorkLedgerError(
                        f"attempt_id {attempt_id!r} 已存在（write-once）"
                    ) from None
                return eid

    # -------------------------------------------------- attempt 统一 CAS
    @staticmethod
    def _validate_terminal_evidence(evidence: Any,
                                    row: sqlite3.Row) -> None:
        """terminal evidence exact 六键 schema + ledger 冻结身份校验
        （mark_terminal_evidence / recover_terminal 写入时与
        mark_verified_by_outcome 验证时三重执行）。"""
        if type(evidence) is not dict \
                or set(evidence.keys()) != _TERMINAL_EVIDENCE_KEYS:
            raise WorkLedgerError(
                "terminal evidence 必须是 exact 六键 schema"
                "（event_id/kind/run_id/backend_id/contract_id/payload）")
        for f in ("event_id", "kind", "run_id", "backend_id", "contract_id"):
            v = evidence[f]
            if type(v) is not str or not v or len(v) > 256:
                raise WorkLedgerError(
                    f"terminal evidence {f} 必须是非空短 builtin str")
        if type(evidence["payload"]) is not dict:
            raise WorkLedgerError("terminal evidence payload 必须是 dict")
        bound_run = str(row["run_id"])
        if not bound_run or evidence["run_id"] != bound_run:
            raise WorkLedgerError(
                "terminal evidence run_id 与 ledger 冻结绑定不一致")
        if evidence["backend_id"] != str(row["backend_id"]):
            raise WorkLedgerError(
                "terminal evidence backend_id 与 ledger 冻结绑定不一致")
        if evidence["contract_id"] != str(row["contract_id"]):
            raise WorkLedgerError(
                "terminal evidence contract_id 与 ledger 冻结绑定不一致")

    def _attempt_cas_locked(self, conn: sqlite3.Connection,
                            row: sqlite3.Row, *, new_state: str,
                            old_state: str, old_version: int, now: float,
                            extra_assigns: str = "",
                            extra_params: Tuple[Any, ...] = ()) -> None:
        """attempt ledger 唯一同步通道：attempt_id + execution_id +
        contract_id + contract_hash + 旧 state + 旧 state_version 全谓词 +
        rowcount==1（任一失配 → CorruptionError，零部分写入）。"""
        sql = ("UPDATE work_attempts SET state=?, state_version="
               "state_version+1"
               + (", " + extra_assigns if extra_assigns else "")
               + ", updated_at=? WHERE attempt_id=? AND execution_id=? "
               "AND contract_id=? AND contract_hash=? AND state=? "
               "AND state_version=?")
        params = (new_state, *extra_params, now, str(row["attempt_id"]),
                  int(row["execution_id"]), str(row["contract_id"]),
                  str(row["contract_hash"]), old_state, old_version)
        cur = conn.execute(sql, params)
        if cur.rowcount != 1:
            raise CorruptionError(
                "attempt CAS 同步失配（身份/状态/版本谓词不匹配）")

    # -------------------------------------------------- CAS 迁移
    def transition(self, execution_id: int, new_state: WorkExecutionState, *,
                   expected_version: int) -> int:
        if not isinstance(new_state, WorkExecutionState):
            raise WorkLedgerError("new_state 必须是 WorkExecutionState")
        if new_state is WorkExecutionState.VERIFIED:
            raise IllegalTransition(
                "generic transition 不得写 VERIFIED（唯一入口 "
                "mark_verified_by_outcome）")
        if new_state is WorkExecutionState.TOOL_RUNNING:
            raise IllegalTransition(
                "TOOL_RUNNING 是子相位，不得作 primary 状态迁移目标")
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                current = WorkExecutionState(str(row["state"]))
                if _is_terminal(current):
                    raise WorkLedgerError(
                        f"execution {execution_id} 已终态 {current.value}")
                if current is WorkExecutionState.UNKNOWN:
                    raise IllegalTransition(
                        "UNKNOWN absorbing（generic 不得迁出；恢复走 "
                        "recovery-only authority）")
                allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
                if new_state not in allowed:
                    raise IllegalTransition(
                        f"非法状态迁移 {current.value} → {new_state.value}")
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败")
                cur = self._conn.execute(
                    "UPDATE work_executions SET state=?, state_version="
                    "state_version+1, is_active=?, updated_at=? "
                    "WHERE execution_id=? AND state_version=? AND state=?",
                    (new_state.value,
                     0 if _is_terminal(new_state) else 1,
                     now, execution_id, expected_version, current.value))
                if cur.rowcount != 1:
                    raise StaleStateVersion("CAS rowcount=0")
                self._attempt_cas_locked(
                    self._conn, row, new_state=new_state.value,
                    old_state=current.value, old_version=expected_version,
                    now=now)
                return expected_version + 1

    def begin_reconciliation(self, execution_id: int, *,
                             expected_version: int) -> int:
        """recovery-only authority：非终态 → UNKNOWN（幂等）。"""
        with self._lock:
            row = self._execution_row(self._conn, execution_id)
            current = WorkExecutionState(str(row["state"]))
            if current is WorkExecutionState.UNKNOWN:
                return int(row["state_version"])
            if _is_terminal(current):
                raise WorkLedgerError(
                    f"execution {execution_id} 已终态（零迁移）")
            if int(row["state_version"]) != expected_version:
                raise StaleStateVersion("reconciliation CAS 失败")
        now = self._now()
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    "UPDATE work_executions SET state='UNKNOWN', "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=? AND state=?",
                    (now, execution_id, expected_version, current.value))
                if cur.rowcount != 1:
                    raise StaleStateVersion("reconciliation rowcount=0")
                self._attempt_cas_locked(
                    self._conn, row, new_state="UNKNOWN",
                    old_state=current.value, old_version=expected_version,
                    now=now)
            return expected_version + 1

    # -------------------------------------------------- 绑定 / 证据 / 16F
    def bind_run(self, execution_id: int, run_id: str, backend_id: str, *,
                 expected_version: int) -> int:
        for name, value in (("run_id", run_id), ("backend_id", backend_id)):
            if type(value) is not str or not value or len(value) > 128:
                raise WorkLedgerError(f"{name} 必须是非空短 builtin str")
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                bound_run = str(row["run_id"])
                if bound_run:
                    if bound_run == run_id \
                            and str(row["backend_id"]) == backend_id:
                        return int(row["state_version"])
                    raise RunBindingConflict(
                        f"execution {execution_id} 已绑定 run={bound_run!r}/"
                        f"backend={row['backend_id']!r}（write-once）")
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion("bind CAS 失败")
                cur = self._conn.execute(
                    "UPDATE work_executions SET run_id=?, backend_id=?, "
                    "run_bound_at=?, state_version=state_version+1, "
                    "updated_at=? WHERE execution_id=? AND state_version=? "
                    "AND run_id=''",
                    (run_id, backend_id, now, now, execution_id,
                     expected_version))
                if cur.rowcount != 1:
                    raise StaleStateVersion("bind CAS rowcount=0")
                self._attempt_cas_locked(
                    self._conn, row, new_state=str(row["state"]),
                    old_state=str(row["state"]),
                    old_version=expected_version, now=now,
                    extra_assigns="run_id=?, backend_id=?",
                    extra_params=(run_id, backend_id))
                return expected_version + 1

    def mark_terminal_evidence(self, execution_id: int,
                               evidence: Mapping[str, Any], *,
                               expected_version: int) -> int:
        blob = _canonical_json(evidence, self._max_payload_bytes)
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                self._validate_terminal_evidence(evidence, row)
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion("evidence CAS 失败")
                cur = self._conn.execute(
                    "UPDATE work_executions SET terminal_evidence_json=?, "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=?",
                    (blob, now, execution_id, expected_version))
                if cur.rowcount != 1:
                    raise StaleStateVersion("evidence CAS rowcount=0")
                self._attempt_cas_locked(
                    self._conn, row, new_state=str(row["state"]),
                    old_state=str(row["state"]),
                    old_version=expected_version, now=now)
                return expected_version + 1

    def mark_verified_by_outcome(self, execution_id: int, verifier, outcome,
                                 *, expected_version: int,
                                 terminal_evidence: Optional[Mapping[str, Any]] = None
                                 ) -> int:
        """VERIFIED 唯一入口（P13-R2 前置强化）：run 已绑定非空、状态属于
        合法验证前驱（BACKEND_DONE_UNVERIFIED 或 recovery-UNKNOWN）、持久化
        terminal evidence 非空且与传入 evidence 精确绑定、execution+attempt
        同事务更新（两边谓词+rowcount）。"""
        from furina.agent.verification import IndependentVerifier
        from furina.agent.verification.repair import RepairOutcome
        if type(verifier) is not IndependentVerifier:
            raise WorkLedgerError(
                f"verifier 必须是 exact IndependentVerifier，得到 "
                f"{type(verifier).__name__}")
        if type(outcome) is not RepairOutcome:
            raise WorkLedgerError(
                f"outcome 必须是 exact RepairOutcome，得到 "
                f"{type(outcome).__name__}")
        authentic_fn = IndependentVerifier.outcome_is_authentic.__get__(verifier)
        try:
            ok = authentic_fn(outcome)
        except Exception as exc:
            raise WorkLedgerError(
                f"outcome 真实性复核异常（{type(exc).__name__}）") from None
        if not ok:
            raise WorkLedgerError(
                "16F outcome 未通过 outcome_is_authentic 复核")
        rep = outcome.final_report
        marker = rep.report_digest
        if type(marker) is not str or len(marker) != 64:
            raise WorkLedgerError("report_digest 必须是 64-hex")
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                current = WorkExecutionState(str(row["state"]))
                if _is_terminal(current):
                    raise WorkLedgerError(
                        f"execution {execution_id} 已终态（零迁移）")
                if current not in (WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                                   WorkExecutionState.UNKNOWN):
                    raise IllegalTransition(
                        f"状态 {current.value} 不是合法验证前驱")
                if outcome.contract_id != str(row["contract_id"]) \
                        or outcome.contract_hash != str(row["contract_hash"]):
                    raise WorkLedgerError(
                        "outcome contract 身份与 ledger 冻结身份不一致")
                bound_run = str(row["run_id"])
                if not bound_run:
                    raise WorkLedgerError(
                        "run 未绑定（STARTING+空 run 不得 VERIFIED）")
                if rep.run_id != bound_run:
                    raise WorkLedgerError(
                        "outcome run_id 与 ledger 绑定 run 不一致")
                evidence_blob = str(row["terminal_evidence_json"])
                if not evidence_blob:
                    raise WorkLedgerError(
                        "无持久化 terminal evidence 不得 VERIFIED")
                # Patch 6：传入 terminal_evidence 必须与持久化 evidence
                # canonical 相等（六键 schema + 冻结身份三重校验）——
                # 绝不允许调用时传完全不同的 evidence 仍进入 VERIFIED。
                if terminal_evidence is None:
                    raise WorkLedgerError(
                        "mark_verified_by_outcome 必须传入与持久化一致的 "
                        "terminal_evidence")
                self._validate_terminal_evidence(terminal_evidence, row)
                passed_blob = _canonical_json(terminal_evidence,
                                              self._max_payload_bytes)
                if passed_blob != evidence_blob:
                    raise WorkLedgerError(
                        "传入 terminal_evidence 与持久化 evidence 不一致"
                        "（canonical 不等，evidence 绑定失败）")
                # P13-R2/B2：从 authentic report 的 EvidenceBundle 提取
                # terminal observation 并与 ledger persisted evidence 的
                # event_id 精确匹配（不能只验证调用方传入的 evidence）。
                report_term_events = [
                    t for t in outcome.final_report.evidence.terminal
                    if t.bound]
                if not report_term_events:
                    raise WorkLedgerError(
                        "authentic report 无 bound terminal observation")
                # P14-R2：report terminal event 必须与 ledger persisted
                # evidence 的 event_id 精确匹配（不同 event → 拒绝）。
                import json as _json
                stored_ev_raw = json.loads(evidence_blob)
                if not isinstance(stored_ev_raw, dict):
                    raise CorruptionError(
                        "持久化 terminal evidence 必须是 object")
                # Patch 6：evidence 全身份绑定——run/backend/contract 身份
                # 必须与 ledger 冻结绑定逐值一致（全错 evidence 不得 VERIFIED）。
                bound_backend = str(row["backend_id"])
                for fname, expected in (
                        ("run_id", bound_run),
                        ("backend_id", bound_backend),
                        ("contract_id", str(row["contract_id"]))):
                    val = stored_ev_raw.get(fname)
                    if type(val) is not str or val != expected:
                        raise WorkLedgerError(
                            f"stored terminal evidence {fname} 与 ledger "
                            f"冻结身份不一致（evidence 绑定失败）")
                stored_kind = str(stored_ev_raw.get("kind", ""))
                stored_event_id = str(stored_ev_raw.get("event_id", ""))
                if stored_kind:
                    report_kinds = {t.kind for t in report_term_events}
                    if stored_kind not in report_kinds:
                        raise WorkLedgerError(
                            f"stored terminal kind {stored_kind!r} 不在 "
                            f"authentic report terminal observations 中")
                if stored_event_id:
                    report_event_ids = {t.event_id for t in report_term_events}
                    if stored_event_id not in report_event_ids:
                        raise WorkLedgerError(
                            f"stored event {stored_event_id!r} 不在 report "
                            f"terminal observations（evidence 绑定失败）")
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion("verify CAS 失败")
                cur = self._conn.execute(
                    "UPDATE work_executions SET state='VERIFIED', "
                    "verification_marker=?, verification_verified=1, "
                    "is_active=0, state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=? AND state=?",
                    (marker, now, execution_id, expected_version, current.value))
                if cur.rowcount != 1:
                    raise StaleStateVersion("verify CAS rowcount=0")
                self._attempt_cas_locked(
                    self._conn, row, new_state="VERIFIED",
                    old_state=current.value, old_version=expected_version,
                    now=now)
                return expected_version + 1

    def recover_terminal(self, execution_id: int,
                         terminal_evidence: Mapping[str, Any],
                         new_state: WorkExecutionState, *,
                         expected_version: int) -> int:
        """P13-R2/B6 recovery-only authority：UNKNOWN → 终态/BACKEND_DONE_UNVERIFIED
        的唯一合法路径（generic transition 不得从 UNKNOWN 迁出）。
        evidence+状态同事务原子提交。new_state 仅接受
        BACKEND_DONE_UNVERIFIED/FAILED/CANCELLED。"""
        if new_state not in (WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                             WorkExecutionState.FAILED,
                             WorkExecutionState.CANCELLED):
            raise IllegalTransition(
                f"recover_terminal 仅接受 BACKEND_DONE_UNVERIFIED/FAILED/"
                f"CANCELLED，得到 {new_state.value}")
        blob = _canonical_json(terminal_evidence, self._max_payload_bytes)
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                self._validate_terminal_evidence(terminal_evidence, row)
                current = WorkExecutionState(str(row["state"]))
                if current is not WorkExecutionState.UNKNOWN:
                    raise IllegalTransition(
                        f"recover_terminal 仅适用于 UNKNOWN，得到 "
                        f"{current.value}")
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion("recover CAS 失败")
                cur = self._conn.execute(
                    "UPDATE work_executions SET terminal_evidence_json=?, "
                    "state=?, is_active=?, state_version=state_version+1, "
                    "updated_at=? WHERE execution_id=? AND state_version=? "
                    "AND state='UNKNOWN'",
                    (blob, new_state.value,
                     0 if _is_terminal(new_state) else 1,
                     now, execution_id, expected_version))
                if cur.rowcount != 1:
                    raise StaleStateVersion("recover rowcount=0")
                self._attempt_cas_locked(
                    self._conn, row, new_state=new_state.value,
                    old_state="UNKNOWN", old_version=expected_version,
                    now=now)
                return expected_version + 1

    # -------------------------------------------------- 取消
    def cancel_intent(self, execution_id: int, *, expected_version: int) -> int:
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                current = WorkExecutionState(str(row["state"]))
                if _is_terminal(current):
                    return int(row["state_version"])
                if int(row["cancel_intent"]) == 1:
                    return int(row["state_version"])  # 返回 DB 真实 version
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion("cancel CAS 失败")
                run_bound = bool(str(row["run_id"]))
                if not run_bound:
                    cur = self._conn.execute(
                        "UPDATE work_executions SET cancel_intent=1, state=?, "
                        "is_active=0, state_version=state_version+1, "
                        "updated_at=? WHERE execution_id=? AND state_version=? "
                        "AND state=? AND cancel_intent=0",
                        (WorkExecutionState.CANCELLED.value, now,
                         execution_id, expected_version, current.value))
                    if cur.rowcount != 1:
                        raise StaleStateVersion("cancel CAS rowcount=0")
                    self._attempt_cas_locked(
                        self._conn, row, new_state="CANCELLED",
                        old_state=current.value, old_version=expected_version,
                        now=now)
                    return expected_version + 1
                cur = self._conn.execute(
                    "UPDATE work_executions SET cancel_intent=1, state=?, "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=? AND state=?",
                    (WorkExecutionState.CANCELLING.value, now,
                     execution_id, expected_version, current.value))
                if cur.rowcount != 1:
                    raise StaleStateVersion("cancel CAS rowcount=0")
                self._attempt_cas_locked(
                    self._conn, row, new_state="CANCELLING",
                    old_state=current.value, old_version=expected_version,
                    now=now)
                return expected_version + 1

    def dispatch_stop_once(self, execution_id: int, *, backend,
                           expected_version: int) -> bool:
        """backend stop claim（Patch 6 全谓词）：backend 必须是真实
        ExecutionBackend 实例（isinstance）+ descriptor/capabilities 合法
        （builtin str backend_id + supports_stop 恰为 True）+ descriptor ID
        与 ledger 冻结绑定一致 + execution 处于 CANCELLING 且 cancel_intent=1
        + run 已绑定 + CAS 版本匹配 + rowcount==1。任一不满足 → False
        零副作用（绝不提前消耗 durable at-most-once stop claim）。"""
        if not isinstance(backend, ExecutionBackend):
            return False
        desc = getattr(backend, "descriptor", None)
        desc_id = getattr(desc, "backend_id", None)
        if type(desc_id) is not str or not desc_id:
            return False
        caps = getattr(backend, "capabilities", None)
        if caps is None or getattr(caps, "supports_stop", None) is not True:
            return False
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                bound_run = str(row["run_id"])
                bound_backend = str(row["backend_id"])
                if not bound_run:
                    return False        # 零 backend run → 零 stop
                if desc_id != bound_backend:
                    return False        # descriptor ID 与冻结绑定不一致
                if str(row["state"]) != WorkExecutionState.CANCELLING.value \
                        or int(row["cancel_intent"]) != 1:
                    return False        # 仅 CANCELLING+cancel intent 允许 stop
                if int(row["stop_dispatched"]) == 1:
                    return False        # 幂等：已派发
                if int(row["state_version"]) != expected_version:
                    return False        # CAS 失败
                current = str(row["state"])
                cur = self._conn.execute(
                    "UPDATE work_executions SET stop_dispatched=1, "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=? AND run_id=? "
                    "AND stop_dispatched=0 AND state=? AND cancel_intent=1",
                    (now, execution_id, expected_version, bound_run,
                     current))
                if cur.rowcount != 1:
                    return False        # CAS rowcount=0
                self._attempt_cas_locked(
                    self._conn, row, new_state=current, old_state=current,
                    old_version=expected_version, now=now)
                return True

    def record_outstanding_approval(self, execution_id: int,
                                    approval_id: str, *,
                                    expected_version: int) -> int:
        if type(approval_id) is not str or not approval_id or len(approval_id) > 128:
            raise WorkLedgerError("approval_id 必须是非空短 builtin str")
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion("approval CAS 失败")
                cur = self._conn.execute(
                    "UPDATE work_executions SET approval_id=?, "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=? AND approval_id=''",
                    (approval_id, now, execution_id, expected_version))
                if cur.rowcount != 1:
                    raise StaleStateVersion("approval CAS rowcount=0")
                self._attempt_cas_locked(
                    self._conn, row, new_state=str(row["state"]),
                    old_state=str(row["state"]),
                    old_version=expected_version, now=now)
                return expected_version + 1

    def invalidate_approval(self, execution_id: int, *,
                            expected_version: int) -> int:
        """approval 失效同样是状态改写：CAS 版本 + attempt 同步（绝不无版本
        谓词静默改写持久化行）。幂等：已失效 → 返回当前 DB 真实 version。"""
        with self._lock:
            row = self._execution_row(self._conn, execution_id)
            if int(row["approval_invalidated"]) == 1:
                return int(row["state_version"])
            if int(row["state_version"]) != expected_version:
                raise StaleStateVersion("invalidate CAS 失败")
        now = self._now()
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    "UPDATE work_executions SET approval_invalidated=1, "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=? "
                    "AND approval_invalidated=0",
                    (now, execution_id, expected_version))
                if cur.rowcount != 1:
                    raise StaleStateVersion("invalidate CAS rowcount=0")
                self._attempt_cas_locked(
                    self._conn, row, new_state=str(row["state"]),
                    old_state=str(row["state"]),
                    old_version=expected_version, now=now)
                return expected_version + 1

    def approval_invalidated(self, execution_id: int) -> bool:
        with self._lock:
            row = self._execution_row(self._conn, execution_id)
            return bool(row["approval_invalidated"])

    # -------------------------------------------------- 事件（(execution_id, event_id)）
    def record_event(self, execution_id: int, event_id: str, kind: EventKind,
                     payload: Optional[Mapping[str, Any]] = None) -> str:
        """单事务完成 lookup/容量判断/insert。critical 溢出时 overflow
        marker + 计数 + UNKNOWN 状态同一事务（绝不分离）。droppable progress
        落独立受控槽 work_progress（不与 event_id 冲突）。"""
        if not isinstance(kind, EventKind):
            raise WorkLedgerError("kind 必须是 EventKind")
        if type(event_id) is not str or not event_id or len(event_id) > 128:
            raise WorkLedgerError("event_id 必须是非空短 builtin str")
        blob = _canonical_json(payload, self._max_payload_bytes)
        priority = classify_priority(kind)
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                cur_state = str(row["state"])
                cur_version = int(row["state_version"])
                dup = self._conn.execute(
                    "SELECT kind, payload_json FROM work_events "
                    "WHERE execution_id=? AND event_id=?",
                    (execution_id, event_id)).fetchone()
                if dup is not None:
                    if str(dup["kind"]) != kind.value \
                            or str(dup["payload_json"]) != blob:
                        raise EventContentConflict(
                            f"event {event_id!r} 同 execution 异内容")
                    return "duplicate"
                per_run = int(self._conn.execute(
                    "SELECT COUNT(*) AS c FROM work_events WHERE execution_id=?",
                    (execution_id,)).fetchone()["c"])
                global_n = int(self._conn.execute(
                    "SELECT COUNT(*) AS c FROM work_events").fetchone()["c"])
                if priority.value != "critical":
                    at_capacity = (per_run >= self._max_events_per_run - 1
                                   or global_n >= self._max_global_events - 1)
                else:
                    at_capacity = (per_run >= self._max_events_per_run
                                   or global_n >= self._max_global_events)
                if priority.value == "critical" and at_capacity:
                    if cur_state in ("CANCELLED", "VERIFIED", "FAILED"):
                        raise CriticalBufferOverflow(
                            "critical 容量耗尽且已终态——拒绝落 marker")
                    self._conn.execute(
                        "UPDATE work_executions SET overflow_marker=?, "
                        "state='UNKNOWN', is_active=1, "
                        "state_version=state_version+1, updated_at=? "
                        "WHERE execution_id=? AND state=? AND state_version=? "
                        "AND state NOT IN ('CANCELLED','VERIFIED','FAILED')",
                        (f"critical_overflow:{kind.value}:{event_id[:64]}:"
                         f"{int(now)}", now, execution_id, cur_state,
                         cur_version))
                    chk = self._conn.execute(
                        "SELECT state FROM work_executions "
                        "WHERE execution_id=?", (execution_id,)).fetchone()
                    if chk is None or str(chk["state"]) != "UNKNOWN":
                        raise CriticalBufferOverflow(
                            "overflow marker 落盘失败（CAS rowcount=0 等价）")
                    self._attempt_cas_locked(
                        self._conn, row, new_state="UNKNOWN",
                        old_state=cur_state, old_version=cur_version, now=now)
                    self._incr_counter_locked(self._conn,
                                              "critical_overflow", 1)
                    self._conn.commit()             # marker 独立提交（不被 raise 回滚）
                    raise CriticalBufferOverflow(
                        f"critical 容量耗尽——durable overflow marker 已落盘"
                        f"（execution 进入 UNKNOWN/reconcile）")
                if at_capacity and priority.value == "droppable":
                    self._conn.execute(
                        "INSERT INTO work_progress(execution_id,payload_json,"
                        "updated_at) VALUES(?,?,?) "
                        "ON CONFLICT(execution_id) DO UPDATE SET "
                        "payload_json=excluded.payload_json, "
                        "updated_at=excluded.updated_at",
                        (execution_id, blob, now))
                    self._incr_counter_locked(self._conn, "progress_dropped", 1)
                    self._incr_counter_locked(self._conn, "progress_upserts", 1)
                    return "dropped"
                if at_capacity:
                    self._incr_counter_locked(self._conn, "coalesced", 1)
                    return "dropped"
                self._conn.execute(
                    "INSERT INTO work_events(execution_id,event_id,kind,"
                    "payload_json,critical,received_at) VALUES(?,?,?,?,?,?)",
                    (execution_id, event_id, kind.value, blob,
                     1 if priority.value == "critical" else 0, now))
                return "stored"

    def progress_latest(self, execution_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json, updated_at FROM work_progress "
                "WHERE execution_id=?", (execution_id,)).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload_json"]))
        except Exception:
            raise CorruptionError(
                "work_progress payload JSON 损坏（fail-closed）") from None
        if not isinstance(payload, dict):
            raise CorruptionError("work_progress payload 必须是 object")
        return {"payload": payload,
                "updated_at": _finite_time(row["updated_at"], "updated_at")}

    def events_of(self, execution_id: int) -> Tuple[Dict[str, Any], ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_id, kind, payload_json, critical, received_at "
                "FROM work_events WHERE execution_id=? ORDER BY received_at, "
                "event_id", (execution_id,)).fetchall()
            out = []
            for row in rows:
                try:
                    payload = json.loads(str(row["payload_json"]))
                except Exception:
                    raise CorruptionError(
                        f"work_events {str(row['event_id'])!r} payload JSON "
                        f"损坏（fail-closed）") from None
                if not isinstance(payload, dict):
                    raise CorruptionError(
                        f"work_events {str(row['event_id'])!r} payload 必须"
                        f"是 object")
                crit = row["critical"]
                if type(crit) is not int or crit not in (0, 1):
                    raise CorruptionError("work_events critical 值损坏")
                out.append({"event_id": str(row["event_id"]),
                            "kind": str(row["kind"]),
                            "payload": payload,
                            "critical": bool(crit),
                            "received_at": _finite_time(row["received_at"],
                                                        "received_at")})
            return tuple(out)

    # -------------------------------------------------- truth-commit claim
    def claim_truth_commit(self, execution_id: int,
                           owner_token: str) -> Tuple[bool, str]:
        if type(owner_token) is not str or not owner_token or len(owner_token) > 128:
            raise WorkLedgerError("owner_token 必须是非空短 builtin str")
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                if str(row["state"]) != WorkExecutionState.VERIFIED.value \
                        or int(row["verification_verified"]) != 1:
                    raise CommitClaimConflict(
                        f"execution {execution_id} 未经验权 VERIFIED")
                marker = str(row["verification_marker"])
                if not marker:
                    raise CommitClaimConflict("verification_marker 为空")
                if str(row["truth_commit_status"]) != "":
                    return False, marker
                cur = self._conn.execute(
                    "UPDATE work_executions SET truth_commit_owner=?, "
                    "truth_commit_digest=?, truth_commit_status='CLAIMED' "
                    "WHERE execution_id=? AND truth_commit_status='' "
                    "AND state='VERIFIED' AND verification_verified=1",
                    (owner_token, marker, execution_id))
                return (cur.rowcount == 1, marker)

    def resolve_truth_commit(self, execution_id: int, owner_token: str) -> bool:
        if type(owner_token) is not str or not owner_token:
            raise WorkLedgerError("owner_token 必须是非空 builtin str")
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    "UPDATE work_executions SET truth_commit_status='COMMITTED' "
                    "WHERE execution_id=? AND truth_commit_owner=? "
                    "AND truth_commit_status='CLAIMED'",
                    (execution_id, owner_token))
                return cur.rowcount == 1

    # -------------------------------------------------- 查询
    def get_execution(self, execution_id: int) -> ExecutionRecord:
        with self._lock:
            return self._record_from_row(
                self._execution_row(self._conn, execution_id))

    def load_non_terminal(self) -> Tuple[ExecutionRecord, ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM work_executions WHERE is_active=1 "
                "ORDER BY execution_id").fetchall()
            return tuple(self._record_from_row(r) for r in rows)

    def attempts_of(self, execution_id: int) -> Tuple[Dict[str, Any], ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT attempt_id, run_id, backend_id, state, state_version "
                "FROM work_attempts WHERE execution_id=? ORDER BY started_at",
                (execution_id,)).fetchall()
            return tuple(dict(r) for r in rows)

    def schema_version(self) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM work_schema_meta WHERE key='schema_version'"
            ).fetchone()
            return str(row["value"]) if row is not None else ""

    def user_version(self) -> int:
        with self._lock:
            return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


class EventBufferOutcome(enum.Enum):
    ACCEPTED = "accepted"
    DROPPED_TICK = "dropped_tick"
    DUPLICATE = "duplicate"


class WorkEventBuffer:
    """纯内存有界事件缓冲 v3（P13-R2/B7 真有界）。"""

    _MAX_PAYLOAD_BYTES = 4096
    _MAX_DEPTH = 8
    _MAX_ITEMS = 64
    # raw 预检上限（sanitize 之前）：2MiB 级原始对象在截断/清洗前即拒绝，
    # 绝不让 sanitize 的静默截断掩盖超大 payload。
    _RAW_PRECHECK_BYTES = 64 * 1024

    def __init__(self, *, per_run_cap: int = 128,
                 global_cap: int = 1024) -> None:
        limit = _MAX_EVENTS_PER_RUN_LIMIT
        for name, value in (("per_run_cap", per_run_cap),
                            ("global_cap", global_cap)):
            if type(value) is not int or value < 1 or value > limit:
                raise WorkLedgerError(
                    f"{name} 必须是 [1, {limit}] 内的 builtin int")
        self._per_run_cap = per_run_cap
        self._global_cap = global_cap
        self._lock = threading.Lock()
        self._events: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._order: List[Tuple[str, str]] = []
        self._per_run: Dict[str, int] = {}
        self._peeked: set = set()
        self._dropped_ticks = 0
        self._duplicates = 0

    def offer(self, run_id: str, event_id: str, kind: EventKind,
              payload: Optional[Mapping[str, Any]] = None) -> EventBufferOutcome:
        """确定性入队。身份 = (run_id, event_id)；global_cap 与 per_run_cap
        对全部 priority 生效（critical 超限 fail-closed）；payload exact dict
        + 深度/条目/字节预算 + canonical 深拷贝（修改原对象/snapshot 不影响
        内部）+ NaN/Inf 显式拒绝。"""
        for name, value in (("run_id", run_id), ("event_id", event_id)):
            if type(value) is not str or not value or len(value) > 128:
                raise WorkLedgerError(f"{name} 必须是非空短 builtin str")
        if not isinstance(kind, EventKind):
            raise WorkLedgerError("kind 必须是 EventKind")
        if payload is None:
            payload = {}
        if type(payload) is not dict:
            raise WorkLedgerError("payload 必须是 builtin dict")
        _reject_non_finite(payload)
        try:
            raw_len = len(json.dumps(payload, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise WorkLedgerError(
                f"payload 无法序列化（{type(exc).__name__}）") from None
        if raw_len > self._RAW_PRECHECK_BYTES:
            raise WorkLedgerError(
                f"payload 原始体积 {raw_len} 字节超过 raw 预检上限 "
                f"{self._RAW_PRECHECK_BYTES}（sanitize 截断前拒绝）")
        clean = sanitize_payload(payload, max_bytes=self._MAX_PAYLOAD_BYTES)
        clean = self._bounded_copy(clean)
        key = (run_id, event_id)
        with self._lock:
            if key in self._events:
                self._duplicates += 1
                return EventBufferOutcome.DUPLICATE
            priority = classify_priority(kind)
            global_n = len(self._order)
            per_n = self._per_run.get(run_id, 0)
            if global_n >= self._global_cap:
                if priority.value == "critical":
                    raise CriticalBufferOverflow(
                        f"global critical 容量耗尽（{global_n}）")
                self._dropped_ticks += 1
                return EventBufferOutcome.DROPPED_TICK
            if per_n >= self._per_run_cap:
                if priority.value == "critical":
                    raise CriticalBufferOverflow(
                        f"per-run critical 容量耗尽（run={run_id!r}）")
                self._dropped_ticks += 1
                return EventBufferOutcome.DROPPED_TICK
            entry = {"run_id": run_id, "event_id": event_id, "kind": kind,
                     "payload": clean}
            self._events[key] = entry
            self._order.append(key)
            self._per_run[run_id] = per_n + 1
            return EventBufferOutcome.ACCEPTED

    def _bounded_copy(self, payload: dict, depth: int = 0) -> dict:
        if depth > self._MAX_DEPTH:
            raise WorkLedgerError("payload 嵌套超深（>8）")
        out = {}
        total = 0
        for k, v in payload.items():
            if type(k) is not str:
                raise WorkLedgerError("payload 键必须全为 builtin str")
            if len(out) >= self._MAX_ITEMS:
                raise WorkLedgerError(
                    f"payload 条目数超界（>{self._MAX_ITEMS}）")
            if isinstance(v, dict):
                child = self._bounded_copy(v, depth + 1)
                total += len(json.dumps(child, ensure_ascii=True))
                out[k] = child
            elif isinstance(v, list):
                if len(v) > self._MAX_ITEMS:
                    raise WorkLedgerError(
                        f"payload 列表超界（>{self._MAX_ITEMS}）")
                child = []
                for item in v:
                    if isinstance(item, dict):
                        child.append(self._bounded_copy(item, depth + 1))
                    else:
                        if isinstance(item, float) and not math.isfinite(item):
                            raise WorkLedgerError("payload 含 NaN/Inf")
                        child.append(item)
                        total += len(str(item))
                out[k] = child
            elif isinstance(v, float):
                if not math.isfinite(v):
                    raise WorkLedgerError("payload 含 NaN/Inf")
                out[k] = v
                total += len(str(v))
            elif isinstance(v, (int, str, bool)) or v is None:
                out[k] = v
                total += len(str(v))
            else:
                raise WorkLedgerError(
                    f"payload 值必须是 JSON-native，得到 {type(v).__name__}")
        if total > self._MAX_PAYLOAD_BYTES:
            raise WorkLedgerError("payload 字节预算超界")
        return out

    def snapshot(self) -> Tuple[Dict[str, Any], ...]:
        with self._lock:
            return tuple(json.loads(json.dumps(self._events[k]))
                         for k in self._order)

    # Patch 6：公开破坏性 drain() 已移除——事件消费只能走
    # peek→persist→ack（peek 不清空、ack 只移除已确认持久化 key），
    # 绝不允许一步清空绕过持久化协议。

    def peek(self, max_items: int = 256) -> Tuple[Dict[str, Any], ...]:
        """peek→persist→ack 协议第一步：返回前 max_items 条快照但**不清空**
        （持久化成功前零丢失窗口；crash 后 peek 可重复）。peek 返回的 key
        进入 peeked 注册表——ack 只接受已 peek 的 key。"""
        if type(max_items) is not int or max_items < 1:
            raise WorkLedgerError("max_items 必须是正 int")
        with self._lock:
            out = tuple(json.loads(json.dumps(self._events[k]))
                        for k in self._order[:max_items])
            self._peeked.update(self._order[:max_items])
            return out

    def ack(self, keys) -> int:
        """peek→persist→ack 协议第二步：仅移除**已 peek 且已确认持久化**的
        (run_id, event_id)；存在但未 peek 的 key 与未 peek 到的 key 一律
        类型化拒绝（零静默吞没）。"""
        key_list = list(keys)
        for k in key_list:
            if (type(k) is not tuple or len(k) != 2
                    or type(k[0]) is not str or type(k[1]) is not str):
                raise WorkLedgerError("ack key 必须是 (run_id, event_id) 二元组")
        with self._lock:
            for k in key_list:
                if k not in self._peeked:
                    raise WorkLedgerError(
                        f"ack key {k[1]!r} 未曾 peek（必须先 peek 再 ack）")
            removed = 0
            for k in key_list:
                if k in self._events:
                    del self._events[k]
                    self._order.remove(k)
                    n = self._per_run.get(k[0], 1) - 1
                    if n <= 0:
                        self._per_run.pop(k[0], None)
                    else:
                        self._per_run[k[0]] = n
                    removed += 1
                self._peeked.discard(k)
            return removed

    @property
    def dropped_ticks(self) -> int:
        return self._dropped_ticks

    @property
    def duplicates(self) -> int:
        return self._duplicates

    def clear_operational(self) -> None:
        with self._lock:
            self._events.clear()
            self._order.clear()
            self._per_run.clear()
            self._peeked.clear()
