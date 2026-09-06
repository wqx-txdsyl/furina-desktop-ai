"""Phase 16H v2 — Durable Work Ledger（Review Patch 1 结构性封闭版）。

权威边界（16H 任务书 §1–3 + Reviewer Patch 1 B1–B3/B6）：

- 本 ledger 是**工作执行域**的唯一持久化真值；不是 cognition store，不能成为
  Persona/Memory/Relationship truth；WorkExecutionState 只进入工作域表；
  truth-commit 只提供 claim/CAS API，零 C7/C6/C3 写入。
- **VERIFIED 唯一入口**：:meth:`WorkLedger.mark_verified_by_outcome`——verifier
  必须 exact :class:`IndependentVerifier`、outcome 必须 exact
  :class:`RepairOutcome`、seal 复核经**类拥有**的
  ``IndependentVerifier.outcome_is_authentic``（禁止实例动态分派/shadow/
  subclass override）、outcome contract_id/hash/run_id 与 ledger 冻结身份
  完全一致、report_digest 64-hex 并与持久化 marker 一致。
  generic :meth:`transition` **不得**写 VERIFIED、不得写 TOOL_RUNNING
  primary、不得做 16E 之外的任意迁移（显式合法迁移表）。
- **truth-commit claim** 仅允许已 VERIFIED（verification_verified=1 且
  marker 非空）的 execution；claim 绑定 contract_id/hash/report_digest；
  STARTING/UNKNOWN/FAILED/CANCELLED/BACKEND_DONE_UNVERIFIED 一律拒绝。
- **跨连接真 CAS**：全部 mutation 为
  ``UPDATE ... WHERE ... state_version=?``（或状态/认领谓词）并检查
  ``rowcount == 1``——两个 WorkLedger 实例并发同 version 更新恰一成功；
  active claim 并发冲突（partial UNIQUE INDEX）折为类型化
  :class:`DuplicateActiveExecution`，绝不泄漏 sqlite3.IntegrityError。
- **run/backend 绑定 write-once**：首绑成功；同 run/backend 重放幂等；
  不同 run/backend 拒绝覆盖。
- **event 身份按 (execution_id, event_id) 隔离**：不同 execution 同 event_id
  各自保留；同 execution 同内容幂等、异内容类型化冲突。
- **payload canonical**：exact builtin dict、16E sanitize_payload 有界脱敏、
  canonical JSON（allow_nan=False → NaN/Inf fail-closed）、字节上限（安全
  最大值封顶，不能传 10^12 关闭有界性）。
- migration 在显式事务中完成：future/未知 user_version 拒绝、必需表结构
  复核、幂等 reopen。
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
    "CriticalBufferOverflow",
    "DuplicateActiveExecution",
    "EventBufferOutcome",
    "EventContentConflict",
    "ExecutionRecord",
    "IllegalTransition",
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

#: P13-R1/B1：generic transition 的**显式合法迁移表**——VERIFIED 与
#: TOOL_RUNNING（子相位）永不在目标集内；UNKNOWN 不得恢复 RUNNING。
_ALLOWED_TRANSITIONS: Dict[WorkExecutionState, frozenset] = {
    WorkExecutionState.STARTING: frozenset({
        WorkExecutionState.RUNNING, WorkExecutionState.WAITING_PERMISSION,
        WorkExecutionState.BLOCKED_APPROVAL, WorkExecutionState.CANCELLING,
        WorkExecutionState.UNKNOWN, WorkExecutionState.FAILED,
        WorkExecutionState.BACKEND_DONE_UNVERIFIED, WorkExecutionState.CANCELLED,
    }),
    WorkExecutionState.RUNNING: frozenset({
        WorkExecutionState.WAITING_PERMISSION,
        WorkExecutionState.BLOCKED_APPROVAL, WorkExecutionState.VERIFYING,
        WorkExecutionState.REPAIRING, WorkExecutionState.CANCELLING,
        WorkExecutionState.UNKNOWN, WorkExecutionState.FAILED,
        WorkExecutionState.BACKEND_DONE_UNVERIFIED, WorkExecutionState.CANCELLED,
    }),
    WorkExecutionState.WAITING_PERMISSION: frozenset({
        WorkExecutionState.RUNNING, WorkExecutionState.BLOCKED_APPROVAL,
        WorkExecutionState.CANCELLING, WorkExecutionState.UNKNOWN,
        WorkExecutionState.FAILED, WorkExecutionState.CANCELLED,
        WorkExecutionState.BACKEND_DONE_UNVERIFIED,
    }),
    WorkExecutionState.BLOCKED_APPROVAL: frozenset({
        WorkExecutionState.RUNNING, WorkExecutionState.CANCELLING,
        WorkExecutionState.UNKNOWN, WorkExecutionState.FAILED,
        WorkExecutionState.CANCELLED, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
    }),
    WorkExecutionState.VERIFYING: frozenset({
        WorkExecutionState.REPAIRING, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
        WorkExecutionState.FAILED, WorkExecutionState.CANCELLING,
        WorkExecutionState.UNKNOWN, WorkExecutionState.CANCELLED,
    }),
    WorkExecutionState.REPAIRING: frozenset({
        WorkExecutionState.VERIFYING, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
        WorkExecutionState.FAILED, WorkExecutionState.CANCELLING,
        WorkExecutionState.UNKNOWN, WorkExecutionState.CANCELLED,
    }),
    WorkExecutionState.BACKEND_DONE_UNVERIFIED: frozenset({
        WorkExecutionState.VERIFYING, WorkExecutionState.REPAIRING,
        WorkExecutionState.FAILED, WorkExecutionState.CANCELLING,
        WorkExecutionState.UNKNOWN, WorkExecutionState.CANCELLED,
    }),
    WorkExecutionState.CANCELLING: frozenset({
        WorkExecutionState.CANCELLED, WorkExecutionState.UNKNOWN,
        WorkExecutionState.FAILED,
    }),
    WorkExecutionState.UNKNOWN: frozenset({
        WorkExecutionState.BACKEND_DONE_UNVERIFIED, WorkExecutionState.FAILED,
        WorkExecutionState.CANCELLED,
    }),
}

#: P13-R1/B6-9：counter 名封闭词表（禁止公开任意 name 制造无界 rows）。
_COUNTER_NAMES = frozenset({
    "critical_overflow", "progress_dropped", "coalesced", "duplicates",
    "progress_upserts",
})

#: 有界配置的安全最大值（不能传 10^12 关闭有界性）。
_MAX_EVENTS_PER_RUN_LIMIT = 10_000
_MAX_GLOBAL_EVENTS_LIMIT = 100_000
_MAX_PAYLOAD_BYTES_LIMIT = 1 << 20          # 1 MiB

DEFAULT_EVENTS_PER_RUN = 256
DEFAULT_MAX_GLOBAL_EVENTS = 4096
DEFAULT_MAX_PAYLOAD_BYTES = 4096

_SCHEMA_VERSION = "16H.2"
_KNOWN_USER_VERSIONS = (1, 2)

_WORK_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_schema_meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_contracts(
    contract_id TEXT PRIMARY KEY,
    contract_hash TEXT NOT NULL,
    transport_json TEXT NOT NULL,
    registered_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS work_executions(
    execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id TEXT NOT NULL,
    contract_hash TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    backend_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
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
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_work_one_active
    ON work_executions(contract_id) WHERE is_active = 1;
CREATE TABLE IF NOT EXISTS work_attempts(
    attempt_id TEXT PRIMARY KEY,
    execution_id INTEGER NOT NULL,
    contract_id TEXT NOT NULL,
    contract_hash TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    backend_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 1,
    started_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_work_attempts_run
    ON work_attempts(run_id) WHERE run_id <> '';
CREATE TABLE IF NOT EXISTS work_events(
    execution_id INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    critical INTEGER NOT NULL,
    received_at REAL NOT NULL,
    PRIMARY KEY (execution_id, event_id)
);
CREATE TABLE IF NOT EXISTS work_counters(
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
"""

#: reopen 时的必需表/关键列结构复核（同名不兼容表 → fail-closed）。
_REQUIRED_COLUMNS = {
    "work_contracts": ("contract_id", "contract_hash", "transport_json"),
    "work_executions": ("execution_id", "contract_id", "contract_hash",
                        "attempt_id", "state", "state_version", "is_active",
                        "verification_marker", "overflow_marker"),
    "work_attempts": ("attempt_id", "execution_id", "run_id"),
    "work_events": ("execution_id", "event_id", "payload_json"),
    "work_counters": ("name", "value"),
}


class WorkLedgerError(FurinaError):
    """16H 工作域 ledger 统一异常基类（类型化 fail-closed）。"""


class ContractIdentityConflict(WorkLedgerError):
    """同 contract_id、不同 contract_hash（不可变身份冲突）。"""


class DuplicateActiveExecution(WorkLedgerError):
    """同 contract 已存在 active execution claim。"""


class StaleStateVersion(WorkLedgerError):
    """CAS 失败：跨连接/跨事务 version 过期（零状态修改）。"""


class EventContentConflict(WorkLedgerError):
    """同 (execution_id, event_id)、不同内容（类型化冲突）。"""


class UnknownExecution(WorkLedgerError):
    """execution_id 不存在。"""


class CriticalBufferOverflow(WorkLedgerError):
    """critical 缓冲容量耗尽（fail-closed + durable overflow marker）。"""


class CommitClaimConflict(WorkLedgerError):
    """truth-commit claim 前置条件不满足（未 VERIFIED/无 marker）或已被认领。"""


class IllegalTransition(WorkLedgerError):
    """generic transition 目标不在合法迁移表内（VERIFIED/TOOL_RUNNING 等）。"""


class RunBindingConflict(WorkLedgerError):
    """run/backend 绑定 write-once 冲突（禁止覆盖为不同身份）。"""


class WorkContractReloadError(WorkLedgerError):
    """持久化契约 transport JSON 损坏/缺字段/未知字段/hash 失配（fail-closed）。"""


def _reject_non_finite(value: Any, depth: int = 0) -> None:
    """P13-R1/B6：NaN/Inf 明确拒绝（16E sanitize 会静默剥离——认证/持久化
    面要求显式 fail-closed，绝不"stored 也算通过"）。"""
    if depth > 8:
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise WorkLedgerError("payload 含 NaN/Inf（明确拒绝，绝不静默剥离）")
    if isinstance(value, dict):
        for k, v in value.items():
            _reject_non_finite(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _reject_non_finite(v, depth + 1)


def _canonical_json(payload: Any, max_bytes: int) -> str:
    """exact schema/type、canonical JSON、尺寸有界；NaN/Inf/敌意对象 fail-closed。"""
    if payload is None:
        payload = {}
    if type(payload) is not dict:
        raise WorkLedgerError("payload 必须是 builtin dict（exact schema）")
    for key in payload:
        if type(key) is not str:
            raise WorkLedgerError("payload 键必须全为 builtin str")
    _reject_non_finite(payload)
    try:
        if len(json.dumps(payload, ensure_ascii=True,
                          allow_nan=False).encode("utf-8")) > max_bytes:
            raise WorkLedgerError(
                f"payload 原始体积超过 {max_bytes} 字节上限（sanitize 截断前"
                f"拒绝，绝不静默吞大对象）")
    except WorkLedgerError:
        raise
    except (TypeError, ValueError) as exc:
        raise WorkLedgerError(
            f"payload 无法序列化（{type(exc).__name__}）") from None
    clean = sanitize_payload(payload, max_bytes=max_bytes)
    try:
        blob = json.dumps(clean, sort_keys=True, ensure_ascii=True,
                          allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError) as exc:
        raise WorkLedgerError(
            f"payload 无法 canonical 化（{type(exc).__name__}；NaN/Inf 拒绝）") from None
    return blob


def _is_terminal(state: WorkExecutionState) -> bool:
    return state in _TERMINAL_STATES


@dataclass(frozen=True)
class ExecutionRecord:
    """execution 的不可变快照（公开查询返回防御性副本）。"""

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
    """工作域 durable ledger v2（独立 SQLite；跨连接真 CAS；显式迁移事务）。"""

    def __init__(self, db_path, *, now_fn=time.time,
                 max_events_per_run: int = DEFAULT_EVENTS_PER_RUN,
                 max_global_events: int = DEFAULT_MAX_GLOBAL_EVENTS,
                 max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES) -> None:
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
                    f"封顶，不能传超大值关闭有界性）")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._path = Path(db_path)
        self._now = now_fn
        self._max_events_per_run = max_events_per_run
        self._max_global_events = max_global_events
        self._max_payload_bytes = max_payload_bytes
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False,
                                     timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    # -------------------------------------------------- migration（显式事务）
    def _migrate(self) -> None:
        with self._lock:
            try:
                # P13-R1/B3-6：migration 在显式事务中完成（中途异常整体回滚）。
                self._conn.execute("BEGIN IMMEDIATE")
                version = int(self._conn.execute(
                    "PRAGMA user_version").fetchone()[0])
                if version > _KNOWN_USER_VERSIONS[-1]:
                    raise WorkLedgerError(
                        f"work ledger user_version {version} 高于本实现已知版本"
                        f" {max(_KNOWN_USER_VERSIONS)}（future schema 拒绝，"
                        f"绝不降级覆盖）")
                self._conn.executescript(_WORK_SCHEMA)
                # 必需表/关键列结构复核（同名但结构不兼容的表 → fail-closed）。
                for table, columns in _REQUIRED_COLUMNS.items():
                    cols = {r["name"] for r in self._conn.execute(
                        f"PRAGMA table_info({table})").fetchall()}
                    missing = [c for c in columns if c not in cols]
                    if missing:
                        raise WorkLedgerError(
                            f"work 表 {table} 结构不兼容（缺列 {missing}）——"
                            f"同名异构表拒绝")
                if version < 2:
                    self._conn.execute("PRAGMA user_version = 2")
                self._conn.execute(
                    "INSERT OR REPLACE INTO work_schema_meta(key,value) "
                    "VALUES('schema_version',?)", (_SCHEMA_VERSION,))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _execution_row(self, conn: sqlite3.Connection,
                       execution_id: int) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM work_executions WHERE execution_id=?",
            (execution_id,)).fetchone()
        if row is None:
            raise UnknownExecution(f"execution {execution_id} 不存在")
        return row

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ExecutionRecord:
        def _json(text: str) -> Dict[str, Any]:
            if not text:
                return {}
            try:
                value = json.loads(text)
            except Exception:
                return {}
            return value if isinstance(value, dict) else {}

        return ExecutionRecord(
            execution_id=int(row["execution_id"]),
            contract_id=str(row["contract_id"]),
            contract_hash=str(row["contract_hash"]),
            attempt_id=str(row["attempt_id"]),
            run_id=str(row["run_id"]),
            backend_id=str(row["backend_id"]),
            state=WorkExecutionState(str(row["state"])),
            state_version=int(row["state_version"]),
            is_active=bool(row["is_active"]),
            cancel_intent=bool(row["cancel_intent"]),
            stop_dispatched=bool(row["stop_dispatched"]),
            approval_id=str(row["approval_id"]),
            approval_invalidated=bool(row["approval_invalidated"]),
            submit_intent=_json(str(row["submit_intent_json"])),
            submit_intent_at=float(row["submit_intent_at"]),
            run_bound_at=float(row["run_bound_at"]),
            terminal_evidence=_json(str(row["terminal_evidence_json"])),
            verification_marker=str(row["verification_marker"]),
            verification_verified=bool(row["verification_verified"]),
            overflow_marker=str(row["overflow_marker"]),
            truth_commit_owner=str(row["truth_commit_owner"]),
            truth_commit_digest=str(row["truth_commit_digest"]),
            truth_commit_status=str(row["truth_commit_status"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def _incr_counter_locked(self, conn: sqlite3.Connection, name: str,
                             n: int = 1) -> None:
        # P13-R1/B6-9：counter 名封闭词表（禁止公开任意 name 制造无界 rows）。
        if name not in _COUNTER_NAMES:
            raise WorkLedgerError(f"counter name 必须在封闭词表内，得到 {name!r}")
        conn.execute(
            "INSERT INTO work_counters(name,value) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET value = value + ?",
            (name, n, n))

    def incr_counter(self, name: str, n: int = 1) -> None:
        with self._lock:
            with self._conn:
                self._incr_counter_locked(self._conn, name, n)

    def counter(self, name: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM work_counters WHERE name=?", (name,)).fetchone()
            return int(row["value"]) if row is not None else 0

    # -------------------------------------------------- 契约身份（完整持久 + 可重载）
    def register_contract(self, contract: WorkContract) -> None:
        """注册完整 canonical WorkContract（transport JSON 持久化）；同 id 异
        hash → :class:`ContractIdentityConflict`；同 id 同 hash 幂等。"""
        if type(contract) is not WorkContract:
            raise WorkLedgerError(
                f"contract 必须是 exact WorkContract，得到 "
                f"{type(contract).__name__}")
        transport = contract.to_transport_json()
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._conn.execute(
                    "SELECT contract_hash FROM work_contracts WHERE contract_id=?",
                    (contract.contract_id,)).fetchone()
                if row is not None:
                    if str(row["contract_hash"]) != contract.content_hash:
                        raise ContractIdentityConflict(
                            f"contract_id {contract.contract_id} 已绑定不同 "
                            f"contract_hash（不可变身份冲突）")
                    return
                self._conn.execute(
                    "INSERT INTO work_contracts(contract_id,contract_hash,"
                    "transport_json,registered_at) VALUES(?,?,?,?)",
                    (contract.contract_id, contract.content_hash, transport, now))

    def load_contract(self, contract_id: str) -> WorkContract:
        """reopen 后从持久化 transport JSON 重验重建 WorkContract——损坏/
        缺字段/hash 失配一律 :class:`WorkContractReloadError` fail-closed
        （绝不带病恢复）。"""
        if type(contract_id) is not str:
            raise WorkLedgerError("contract_id 必须是 builtin str")
        with self._lock:
            row = self._conn.execute(
                "SELECT contract_hash, transport_json FROM work_contracts "
                "WHERE contract_id=?", (contract_id,)).fetchone()
        if row is None:
            raise WorkContractReloadError(
                f"contract {contract_id} 未在 ledger 注册")
        blob = str(row["transport_json"])
        try:
            contract = WorkContract.from_transport_json(blob)
        except Exception as exc:
            raise WorkContractReloadError(
                f"contract {contract_id} transport JSON 损坏"
                f"（{type(exc).__name__}）——fail-closed 拒绝带病恢复") from None
        if contract.contract_id != contract_id \
                or contract.content_hash != str(row["contract_hash"]):
            raise WorkContractReloadError(
                f"contract {contract_id} 重载身份失配（fail-closed）")
        return contract

    # -------------------------------------------------- submit intent
    def submit_intent(self, contract: WorkContract, attempt_id: str,
                      submit_payload: Optional[Mapping[str, Any]] = None) -> int:
        """submit intent 先持久化（先于远端副作用）。同 contract 已有 active
        execution（含跨连接并发，partial UNIQUE INDEX 兜底）→
        :class:`DuplicateActiveExecution`（类型化，绝不泄漏
        sqlite3.IntegrityError）。"""
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
                        f"{int(row['execution_id'])}（reconciliation 结束前禁止"
                        f"二次 submit）")
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
                self._conn.execute(
                    "INSERT OR IGNORE INTO work_attempts(attempt_id,"
                    "execution_id,contract_id,contract_hash,state,"
                    "state_version,started_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (attempt_id, eid, contract.contract_id,
                     contract.content_hash,
                     WorkExecutionState.STARTING.value, 1, now, now))
                return eid

    def bind_run(self, execution_id: int, run_id: str, backend_id: str, *,
                 expected_version: int) -> int:
        """POST 成功后绑定 run/backend——**write-once**：同 run/backend 重放
        幂等；不同 run/backend → :class:`RunBindingConflict` 禁止覆盖。CAS。"""
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
                        return int(row["state_version"])     # 幂等重放
                    raise RunBindingConflict(
                        f"execution {execution_id} 已绑定 run={bound_run!r}/"
                        f"backend={row['backend_id']!r}（write-once，禁止覆盖）")
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败："
                        f"expected {expected_version}，"
                        f"actual {int(row['state_version'])}")
                cur = self._conn.execute(
                    "UPDATE work_executions SET run_id=?, backend_id=?, "
                    "run_bound_at=?, state_version=state_version+1, "
                    "updated_at=? WHERE execution_id=? AND state_version=?",
                    (run_id, backend_id, now, now, execution_id,
                     expected_version))
                if cur.rowcount != 1:
                    raise StaleStateVersion(
                        f"execution {execution_id} 跨连接 CAS 失败"
                        f"（rowcount=0）")
                self._conn.execute(
                    "UPDATE work_attempts SET run_id=?, backend_id=?, "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE attempt_id=?",
                    (run_id, backend_id, now, str(row["attempt_id"])))
                return expected_version + 1

    # -------------------------------------------------- CAS 状态迁移（显式合法表）
    def transition(self, execution_id: int, new_state: WorkExecutionState, *,
                   expected_version: int) -> int:
        """CAS 状态迁移（**显式合法迁移表**）：VERIFIED/TOOL_RUNNING 等非法
        目标 → :class:`IllegalTransition`；stale/跨连接 →
        :class:`StaleStateVersion`；终态吸收。VERIFIED 唯一入口是
        :meth:`mark_verified_by_outcome`。"""
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
                        f"execution {execution_id} 已终态 {current.value}"
                        f"（终态吸收，零迁移）")
                allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
                if new_state not in allowed:
                    raise IllegalTransition(
                        f"非法状态迁移 {current.value} → {new_state.value}"
                        f"（16E 之外的任意迁移拒绝）")
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败："
                        f"expected {expected_version}，"
                        f"actual {int(row['state_version'])}")
                cur = self._conn.execute(
                    "UPDATE work_executions SET state=?, state_version="
                    "state_version+1, is_active=?, updated_at=? "
                    "WHERE execution_id=? AND state_version=?",
                    (new_state.value,
                     0 if _is_terminal(new_state) else 1,
                     now, execution_id, expected_version))
                if cur.rowcount != 1:
                    raise StaleStateVersion(
                        f"execution {execution_id} 跨连接 CAS 失败"
                        f"（rowcount=0）")
                self._conn.execute(
                    "UPDATE work_attempts SET state=?, state_version="
                    "state_version+1, updated_at=? WHERE attempt_id=?",
                    (new_state.value, now, str(row["attempt_id"])))
                return expected_version + 1

    def begin_reconciliation(self, execution_id: int, *,
                             expected_version: int) -> int:
        """恢复期：持久化 reconciliation/UNKNOWN 状态（不写 C7；UNKNOWN 不得
        经 generic transition 恢复 RUNNING——verify-on-recovery 走
        :meth:`mark_verified_by_outcome` 专用权威路径）。已处于 UNKNOWN →
        幂等零迁移。"""
        with self._lock:
            row = self._execution_row(self._conn, execution_id)
            if WorkExecutionState(str(row["state"]))                     is WorkExecutionState.UNKNOWN:
                return int(row["state_version"])
        return self.transition(execution_id, WorkExecutionState.UNKNOWN,
                               expected_version=expected_version)

    # -------------------------------------------------- 证据 / 16F 权威验证
    def mark_terminal_evidence(self, execution_id: int,
                               evidence: Mapping[str, Any], *,
                               expected_version: int) -> int:
        """terminal/recovery evidence 与状态版本同事务原子持久化。"""
        blob = _canonical_json(evidence, self._max_payload_bytes)
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败")
                cur = self._conn.execute(
                    "UPDATE work_executions SET terminal_evidence_json=?, "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=?",
                    (blob, now, execution_id, expected_version))
                if cur.rowcount != 1:
                    raise StaleStateVersion(
                        f"execution {execution_id} 跨连接 CAS 失败")
                return expected_version + 1

    def mark_verified_by_outcome(self, execution_id: int, verifier, outcome,
                                 *, expected_version: int) -> int:
        """**VERIFIED 唯一入口**（P13-R1/B1）：verifier exact
        IndependentVerifier、outcome exact RepairOutcome、seal 复核经类拥有
        的 outcome_is_authentic（禁止实例动态分派/shadow/subclass override）、
        outcome 身份与 ledger 冻结身份（contract_id/hash/run_id）完全一致、
        report_digest 64-hex——全部通过后同事务写入 VERIFIED + marker
        （rowcount CAS）。"""
        from furina.agent.verification import IndependentVerifier
        from furina.agent.verification.repair import RepairOutcome
        if type(verifier) is not IndependentVerifier:
            raise WorkLedgerError(
                f"verifier 必须是 exact IndependentVerifier（子类/代理不得"
                f"进入权威路径），得到 {type(verifier).__name__}")
        if type(outcome) is not RepairOutcome:
            raise WorkLedgerError(
                f"outcome 必须是 exact RepairOutcome，得到 "
                f"{type(outcome).__name__}")
        authentic_fn = IndependentVerifier.outcome_is_authentic.__get__(verifier)
        try:
            ok = authentic_fn(outcome)
        except Exception as exc:
            # 结构/canonical 复核的 VerificationError 等一律折叠为类型化
            # WorkLedgerError（绝不让非 WorkLedgerError 逃出权威入口）。
            raise WorkLedgerError(
                f"outcome 真实性复核异常（{type(exc).__name__}）——零泄漏拒绝"
            ) from None
        if not ok:
            raise WorkLedgerError(
                "16F outcome 未通过类拥有的 outcome_is_authentic 复核"
                "（VERIFIED 标记拒绝，零状态修改）")
        marker = outcome.final_report.report_digest
        if type(marker) is not str or len(marker) != 64:
            raise WorkLedgerError("report_digest 必须是 64-hex")
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                if outcome.contract_id != str(row["contract_id"]):
                    raise WorkLedgerError(
                        "outcome contract_id 与 ledger 冻结身份不一致")
                if outcome.contract_hash != str(row["contract_hash"]):
                    raise WorkLedgerError(
                        "outcome contract_hash 与 ledger 冻结身份不一致")
                bound_run = str(row["run_id"])
                if bound_run and outcome.final_report.run_id != bound_run:
                    raise WorkLedgerError(
                        "outcome run_id 与 ledger 绑定 run 不一致（跨 run "
                        "拒绝）")
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败")
                cur = self._conn.execute(
                    "UPDATE work_executions SET state=?, "
                    "verification_marker=?, verification_verified=1, "
                    "is_active=0, state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=?",
                    (WorkExecutionState.VERIFIED.value, marker, now,
                     execution_id, expected_version))
                if cur.rowcount != 1:
                    raise StaleStateVersion(
                        f"execution {execution_id} 跨连接 CAS 失败")
                self._conn.execute(
                    "UPDATE work_attempts SET state='VERIFIED', "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE attempt_id=?", (now, str(row["attempt_id"])))
                return expected_version + 1

    # -------------------------------------------------- 取消（PART 5）
    def cancel_intent(self, execution_id: int, *,
                      expected_version: int) -> int:
        """cancel intent 先落盘（重复幂等）：pre-submit（run 未绑定）→ 直接
        CANCELLED 零 backend run；活动执行 → CANCELLING 等真实 terminal
        evidence 或 timeout policy。"""
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                current = WorkExecutionState(str(row["state"]))
                if _is_terminal(current):
                    return int(row["state_version"])            # 幂等
                if int(row["cancel_intent"]) == 1:
                    return expected_version                     # 幂等
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败")
                run_bound = bool(str(row["run_id"]))
                if not run_bound:
                    self._conn.execute(
                        "UPDATE work_executions SET cancel_intent=1, state=?, "
                        "is_active=0, state_version=state_version+1, "
                        "updated_at=? WHERE execution_id=? AND state_version=?",
                        (WorkExecutionState.CANCELLED.value, now,
                         execution_id, expected_version))
                    self._conn.execute(
                        "UPDATE work_attempts SET state='CANCELLED', "
                        "state_version=state_version+1, updated_at=? "
                        "WHERE attempt_id=?",
                        (now, str(row["attempt_id"])))
                    return expected_version + 1
                self._conn.execute(
                    "UPDATE work_executions SET cancel_intent=1, state=?, "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=?",
                    (WorkExecutionState.CANCELLING.value, now,
                     execution_id, expected_version))
                self._conn.execute(
                    "UPDATE work_attempts SET state='CANCELLING', "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE attempt_id=?", (now, str(row["attempt_id"])))
                return expected_version + 1

    def dispatch_stop_once(self, execution_id: int) -> bool:
        """backend stop 每活动 run 恰好派发一次（幂等）；run 未绑定 → False。"""
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                if not str(row["run_id"]):
                    return False        # pre-submit：零 backend run → 零 stop
                if int(row["stop_dispatched"]) == 1:
                    return False
                self._conn.execute(
                    "UPDATE work_executions SET stop_dispatched=1 "
                    "WHERE execution_id=?", (execution_id,))
                return True

    def record_outstanding_approval(self, execution_id: int,
                                    approval_id: str, *,
                                    expected_version: int) -> int:
        """持久化 outstanding approval_id（B5：不再只有 bool）。"""
        if type(approval_id) is not str or not approval_id or len(approval_id) > 128:
            raise WorkLedgerError("approval_id 必须是非空短 builtin str")
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败")
                cur = self._conn.execute(
                    "UPDATE work_executions SET approval_id=?, "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=?",
                    (approval_id, now, execution_id, expected_version))
                if cur.rowcount != 1:
                    raise StaleStateVersion(
                        f"execution {execution_id} 跨连接 CAS 失败")
                return expected_version + 1

    def invalidate_approval(self, execution_id: int) -> None:
        """approval wait 被取消后旧 approval 失效（迟到 approve 不得恢复）。"""
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "UPDATE work_executions SET approval_invalidated=1 "
                    "WHERE execution_id=?", (execution_id,))

    def approval_invalidated(self, execution_id: int) -> bool:
        with self._lock:
            row = self._execution_row(self._conn, execution_id)
            return bool(row["approval_invalidated"])

    # -------------------------------------------------- 事件（(execution_id, event_id) 隔离）
    def record_event(self, execution_id: int, event_id: str, kind: EventKind,
                     payload: Optional[Mapping[str, Any]] = None) -> str:
        """持久化 normalized event——身份按 **(execution_id, event_id)** 隔离：
        不同 execution 同 event_id 各自保留；同 execution 同内容幂等
        （"duplicate"）、异内容 → :class:`EventContentConflict`。critical 永不
        丢弃（容量耗尽 → durable execution-bound overflow marker + 计数 →
        :class:`CriticalBufferOverflow` fail-closed）；droppable progress 在
        容量耗尽时以确定性后备键 UPSERT 覆盖写（保留最新、行数有界、计数
        持久化——绝不只"填满后永久 drop"）。"""
        if not isinstance(kind, EventKind):
            raise WorkLedgerError("kind 必须是 EventKind")
        if type(event_id) is not str or not event_id or len(event_id) > 128:
            raise WorkLedgerError("event_id 必须是非空短 builtin str")
        blob = _canonical_json(payload, self._max_payload_bytes)
        priority = classify_priority(kind)
        now = self._now()
        with self._lock:
            self._execution_row(self._conn, execution_id)
            row = self._conn.execute(
                "SELECT kind, payload_json FROM work_events "
                "WHERE execution_id=? AND event_id=?",
                (execution_id, event_id)).fetchone()
            if row is not None:
                if str(row["kind"]) != kind.value \
                        or str(row["payload_json"]) != blob:
                    raise EventContentConflict(
                        f"event {event_id!r} 同 execution 异内容（类型化冲突）")
                return "duplicate"
            per_run = int(self._conn.execute(
                "SELECT COUNT(*) AS c FROM work_events WHERE execution_id=?",
                (execution_id,)).fetchone()["c"])
            global_n = int(self._conn.execute(
                "SELECT COUNT(*) AS c FROM work_events").fetchone()["c"])
            # P13-R1/B6-8：critical 保留槽——droppable/coalescible 在容量只剩
            # 最后 1 格时即拒绝（progress 占满后 terminal critical 仍被保留）。
            if priority.value != "critical":
                at_capacity = (per_run >= self._max_events_per_run - 1
                               or global_n >= self._max_global_events - 1)
            else:
                at_capacity = (per_run >= self._max_events_per_run
                               or global_n >= self._max_global_events)
            if priority.value == "critical" and at_capacity:
                # durable execution-bound overflow marker（B6-8：不是只加计数）
                with self._conn:
                    self._conn.execute(
                        "UPDATE work_executions SET overflow_marker=?, "
                        "updated_at=? WHERE execution_id=?",
                        (f"critical_overflow:{kind.value}:{event_id[:64]}:"
                         f"{int(now)}", now, execution_id))
                    self._incr_counter_locked(self._conn,
                                              "critical_overflow", 1)
                raise CriticalBufferOverflow(
                    f"critical 缓冲容量耗尽（per_run={per_run}, "
                    f"global={global_n}）——durable overflow marker 已落盘，"
                    f"fail-closed 停止摄取，进入 UNKNOWN/reconcile")
            if at_capacity and priority.value == "droppable":
                # B6-7：droppable 用确定性后备键 UPSERT 覆盖写（保留最新、
                # 行数有界、绝不只"填满后永久 drop"）。
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO work_events(execution_id,event_id,kind,"
                        "payload_json,critical,received_at) VALUES(?,?,?,?,0,?) "
                        "ON CONFLICT(execution_id,event_id) DO UPDATE SET "
                        "kind=excluded.kind, payload_json=excluded.payload_json,"
                        " received_at=excluded.received_at",
                        (execution_id, f"progress:latest:{execution_id}",
                         kind.value, blob, now))
                    self._incr_counter_locked(self._conn, "progress_dropped", 1)
                    self._incr_counter_locked(self._conn, "progress_upserts", 1)
                return "dropped"
            if at_capacity:
                with self._conn:
                    self._incr_counter_locked(self._conn, "coalesced", 1)
                return "dropped"
            with self._conn:
                self._conn.execute(
                    "INSERT INTO work_events(execution_id,event_id,kind,"
                    "payload_json,critical,received_at) VALUES(?,?,?,?,?,?)",
                    (execution_id, event_id, kind.value, blob,
                     1 if priority.value == "critical" else 0, now))
            return "stored"

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
                    payload = {}
                out.append({"event_id": str(row["event_id"]),
                            "kind": str(row["kind"]),
                            "payload": payload if isinstance(payload, dict) else {},
                            "critical": bool(row["critical"]),
                            "received_at": float(row["received_at"])})
            return tuple(out)

    # -------------------------------------------------- truth-commit claim（B1）
    def claim_truth_commit(self, execution_id: int,
                           owner_token: str) -> Tuple[bool, str]:
        """truth-commit claim（B1-4/5）：仅允许已由权威入口 VERIFIED
        （verification_verified=1 且 marker 非空）的 execution；claim 绑定
        contract_id/hash/report_digest；并发恰一 owner、stale 拒绝。返回
        ``(是否成功, 绑定的 report_digest)``。"""
        if type(owner_token) is not str or not owner_token or len(owner_token) > 128:
            raise WorkLedgerError("owner_token 必须是非空短 builtin str")
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                if str(row["state"]) != WorkExecutionState.VERIFIED.value \
                        or int(row["verification_verified"]) != 1:
                    raise CommitClaimConflict(
                        f"execution {execution_id} 未经验权 VERIFIED"
                        f"（STARTING/UNKNOWN/FAILED/CANCELLED/"
                        f"BACKEND_DONE_UNVERIFIED 不得 claim）")
                marker = str(row["verification_marker"])
                if not marker:
                    raise CommitClaimConflict(
                        "verification_marker 为空（未经权威验证）不得 claim")
                if str(row["truth_commit_status"]) != "":
                    return False, marker            # 已认领（stale claim 拒绝）
                cur = self._conn.execute(
                    "UPDATE work_executions SET truth_commit_owner=?, "
                    "truth_commit_digest=?, truth_commit_status='CLAIMED' "
                    "WHERE execution_id=? AND truth_commit_status='' "
                    "AND state='VERIFIED' AND verification_verified=1",
                    (owner_token, marker, execution_id))
                return (cur.rowcount == 1, marker)

    def resolve_truth_commit(self, execution_id: int, owner_token: str) -> bool:
        """resolve claim（仅 claim owner 可 resolve；CAS 到 COMMITTED）。"""
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

    # -------------------------------------------------- 查询 / 恢复
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
        """attempt ledger 快照（attempt_id/run_id/backend_id/state/version）。"""
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
    """WorkEventBuffer.offer 的确定性结果。"""

    ACCEPTED = "accepted"
    DROPPED_TICK = "dropped_tick"
    DUPLICATE = "duplicate"


class WorkEventBuffer:
    """纯内存有界事件缓冲 v2（tick 路径安全：offer 零 DB/vector/network I/O）。

    B6：offer 携带稳定 **run 身份**——per_run_cap 按 run 统计（不同 run 互不
    干扰/互不合并）、global_cap 对全部 entry 生效；payload 进入前经 exact
    dict 校验 + 16E sanitize + UTF-8 字节上限 + canonical JSON 深拷贝
    （修改原始对象/snapshot 绝不影响内部）；NaN/Inf/非 JSON fail-closed；
    droppable tick per-run 容量耗尽确定性丢弃；critical 永不丢弃——global
    容量耗尽 fail-closed 抛 :class:`CriticalBufferOverflow`（durable overflow
    marker 由调用方经 ledger 落盘）；drain/flush 后容量恢复。
    """

    _MAX_PAYLOAD_BYTES = 4096

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
        self._events: Dict[str, Dict[str, Any]] = {}   # event_id → entry
        self._order: List[str] = []
        self._per_run: Dict[str, int] = {}             # run_id → count
        self._dropped_ticks = 0
        self._duplicates = 0

    def offer(self, run_id: str, event_id: str, kind: EventKind,
              payload: Optional[Mapping[str, Any]] = None) -> EventBufferOutcome:
        """确定性入队（纯内存；payload canonical 深拷贝；字节有界）。"""
        if type(run_id) is not str or not run_id:
            raise WorkLedgerError("run_id 必须是非空 builtin str（稳定身份）")
        if type(event_id) is not str or not event_id:
            raise WorkLedgerError("event_id 必须是非空 builtin str")
        if not isinstance(kind, EventKind):
            raise WorkLedgerError("kind 必须是 EventKind")
        if payload is None:
            payload = {}
        if type(payload) is not dict:
            raise WorkLedgerError("payload 必须是 builtin dict")
        _reject_non_finite(payload)
        if len(json.dumps(payload, ensure_ascii=True,
                          allow_nan=False).encode("utf-8"))                 > self._MAX_PAYLOAD_BYTES:
            raise WorkLedgerError(
                "payload 原始体积超过 4096 字节上限（拒绝 2MiB 级对象常驻）")
        clean = sanitize_payload(payload, max_bytes=self._MAX_PAYLOAD_BYTES)
        try:
            blob = json.dumps(clean, sort_keys=True, ensure_ascii=True,
                              allow_nan=False, separators=(",", ":"))
        except (ValueError, TypeError) as exc:
            raise WorkLedgerError(
                f"payload 无法 canonical 化（{type(exc).__name__}；NaN/Inf "
                f"拒绝）") from None
        if len(blob.encode("utf-8")) > self._MAX_PAYLOAD_BYTES:
            raise WorkLedgerError("payload 超过字节上限（canonical 后仍超界）")
        entry = {"run_id": run_id, "event_id": event_id, "kind": kind,
                 "payload": json.loads(blob)}
        with self._lock:
            if event_id in self._events:
                self._duplicates += 1
                return EventBufferOutcome.DUPLICATE
            priority = classify_priority(kind)
            if priority.value == "critical" \
                    and len(self._order) >= self._global_cap:
                raise CriticalBufferOverflow(
                    f"critical 缓冲容量耗尽（global={len(self._order)}）——"
                    f"fail-closed（durable overflow marker 由调用方落盘）")
            if priority.value == "droppable" \
                    and self._per_run.get(run_id, 0) >= self._per_run_cap:
                self._dropped_ticks += 1
                return EventBufferOutcome.DROPPED_TICK
            self._per_run[run_id] = self._per_run.get(run_id, 0) + 1
            self._events[event_id] = entry
            self._order.append(event_id)
            return EventBufferOutcome.ACCEPTED

    def snapshot(self) -> Tuple[Dict[str, Any], ...]:
        with self._lock:
            return tuple(json.loads(json.dumps(self._events[eid]))
                         for eid in self._order)

    def drain(self) -> Tuple[Dict[str, Any], ...]:
        """有界 drain/flush：返回快照并清空已接受 entry（容量恢复）。"""
        with self._lock:
            out = tuple(json.loads(json.dumps(self._events[eid]))
                        for eid in self._order)
            self._events.clear()
            self._order.clear()
            self._per_run.clear()
            return out

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
