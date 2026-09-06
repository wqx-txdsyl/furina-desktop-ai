"""Phase 16H — Durable Work Ledger：工作域持久化 / 幂等 / 崩溃恢复 / 背压。

权威边界（16H 任务书 §1–3）：

- 本 ledger 是**工作执行域**的唯一持久化真值（immutable contract identity、
  execution claim、attempt/run/backend 绑定、单调 state_version、normalized
  critical/terminal evidence、cancellation intent、verification/recovery
  marker、供 16G 使用的 truth-commit claim/marker）。
- **不是**新的 cognition store，不能成为 Persona/Memory/Relationship truth；
  WorkExecutionState 只进入本工作域表，UNKNOWN/BLOCKED_APPROVAL/VERIFYING/
  REPAIRING/BACKEND_DONE_UNVERIFIED 等禁止写入 C7；本阶段 truth-commit 只提供
  claim/CAS API，不写 C7/C6（16G 拥有最终投影）。

存储决策（Recon Gate 记录）：**独立 work-domain SQLite 数据库**（独立文件、
独立连接、独立 schema versioning）——与 Phase 15 的 furina.db（C1–C7 归属
CognitionDB/MemoryStore）零表接触、零 writer 共享；migration additive、
versioned、幂等（CREATE TABLE IF NOT EXISTS + PRAGMA user_version 单调推进，
重复 reopen 零副作用）。

硬约束（任务书 §3 / 关键锁定）：

- 同 contract_id、不同 contract_hash → :class:`ContractIdentityConflict`。
- 每个 contract 最多一个 active execution claim（partial UNIQUE INDEX 硬约束
  + 应用层前置检查）。
- 所有 claim/CAS/version 更新在 SQLite 事务内原子完成；stale worker
  （state_version 不匹配）→ :class:`StaleStateVersion`，零状态修改，终态
  绝不被覆盖。
- event_id 同内容重投幂等；同 id 异内容 → :class:`EventContentConflict`。
- 持久化载荷 exact schema/type、canonical JSON（sort_keys/allow_nan=False）、
  尺寸有界；只持久化 16E 已清洗数据，不保存 raw secret。
- 终态（CANCELLED/VERIFIED/FAILED）吸收：终态后零状态迁移。

背压（任务书 §6）：:class:`WorkEventBuffer` 为纯内存 tick 路径安全结构
（offer 零 DB/vector/network I/O）；critical 永不丢弃——容量耗尽 fail-closed
抛 :class:`CriticalBufferOverflow`（调用方停止摄取并进入 UNKNOWN/reconcile）；
progress/token tick 可确定性丢弃、reconnect/unknown 可合并，计数持久化于
work_counters。
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
from furina.core import FurinaError

__all__ = [
    "CommitClaimConflict",
    "ContractIdentityConflict",
    "CriticalBufferOverflow",
    "DuplicateActiveExecution",
    "EventBufferOutcome",
    "EventContentConflict",
    "ExecutionRecord",
    "StaleStateVersion",
    "UnknownExecution",
    "WorkEventBuffer",
    "WorkLedger",
    "WorkLedgerError",
]

#: 终态集合（终态吸收：进入后零状态迁移）。
_TERMINAL_STATES = frozenset({
    WorkExecutionState.CANCELLED,
    WorkExecutionState.VERIFIED,
    WorkExecutionState.FAILED,
})

#: 默认有界参数。
DEFAULT_MAX_EVENTS_PER_RUN = 256
DEFAULT_MAX_GLOBAL_EVENTS = 4096
DEFAULT_MAX_PAYLOAD_BYTES = 4096

_SCHEMA_VERSION = "16H.1"

_WORK_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_schema_meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_contracts(
    contract_id TEXT PRIMARY KEY,
    contract_hash TEXT NOT NULL,
    registered_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS work_executions(
    execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    backend_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    cancel_intent INTEGER NOT NULL DEFAULT 0,
    stop_dispatched INTEGER NOT NULL DEFAULT 0,
    approval_invalidated INTEGER NOT NULL DEFAULT 0,
    submit_intent_json TEXT NOT NULL DEFAULT '{}',
    submit_intent_at REAL NOT NULL DEFAULT 0,
    run_bound_at REAL NOT NULL DEFAULT 0,
    terminal_evidence_json TEXT NOT NULL DEFAULT '',
    verification_marker TEXT NOT NULL DEFAULT '',
    truth_commit_owner TEXT NOT NULL DEFAULT '',
    truth_commit_status TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_work_one_active
    ON work_executions(contract_id) WHERE is_active = 1;
CREATE TABLE IF NOT EXISTS work_events(
    event_id TEXT PRIMARY KEY,
    execution_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    critical INTEGER NOT NULL,
    received_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_work_events_execution
    ON work_events(execution_id);
CREATE TABLE IF NOT EXISTS work_counters(
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
"""


class WorkLedgerError(FurinaError):
    """16H 工作域 ledger 统一异常基类（类型化 fail-closed）。"""


class ContractIdentityConflict(WorkLedgerError):
    """同 contract_id、不同 contract_hash（不可变身份冲突）。"""


class DuplicateActiveExecution(WorkLedgerError):
    """同 contract 已存在 active execution claim（复用或拒绝，绝不第二执行）。"""


class StaleStateVersion(WorkLedgerError):
    """CAS 失败：state_version 过期（stale worker 零状态修改）。"""


class EventContentConflict(WorkLedgerError):
    """同 event_id、不同内容（类型化冲突）。"""


class UnknownExecution(WorkLedgerError):
    """execution_id 不存在。"""


class CriticalBufferOverflow(WorkLedgerError):
    """critical 缓冲容量耗尽（fail-closed：停止摄取，进入 UNKNOWN/reconcile）。"""


class CommitClaimConflict(WorkLedgerError):
    """truth-commit claim 冲突（已被人认领/stale owner）。"""


def _canonical_json(payload: Any, max_bytes: int) -> str:
    """exact schema/type、canonical JSON、尺寸有界（绝不 pickle、绝不 repr）。

    敌意 payload（__iter__/__bool__/__str__ 即抛的对象）与 NaN/Inf 在此
    类型化拒绝——零协议方法调用逃逸、零 NaN/Inf 落库。"""
    if payload is None:
        payload = {}
    if type(payload) is not dict:
        raise WorkLedgerError("payload 必须是 builtin dict（exact schema）")
    for key in payload:
        if type(key) is not str:
            raise WorkLedgerError("payload 键必须全为 builtin str")
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


@dataclass(frozen=True)
class ExecutionRecord:
    """execution 的不可变快照（公开查询返回防御性副本）。"""

    execution_id: int
    contract_id: str
    attempt_id: str
    run_id: str
    backend_id: str
    state: WorkExecutionState
    state_version: int
    is_active: bool
    cancel_intent: bool
    stop_dispatched: bool
    approval_invalidated: bool
    submit_intent: Dict[str, Any] = field(default_factory=dict)
    submit_intent_at: float = 0.0
    run_bound_at: float = 0.0
    terminal_evidence: Dict[str, Any] = field(default_factory=dict)
    verification_marker: str = ""
    truth_commit_owner: str = ""
    truth_commit_status: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0


class WorkLedger:
    """工作域 durable ledger（独立 SQLite；RLock 串行化；事务原子 CAS）。"""

    def __init__(self, db_path, *, now_fn=time.time,
                 max_events_per_run: int = DEFAULT_MAX_EVENTS_PER_RUN,
                 max_global_events: int = DEFAULT_MAX_GLOBAL_EVENTS,
                 max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES) -> None:
        for name, value in (("max_events_per_run", max_events_per_run),
                            ("max_global_events", max_global_events),
                            ("max_payload_bytes", max_payload_bytes)):
            if type(value) is not int or value < 1:
                raise WorkLedgerError(f"{name} 必须是正 int")
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
        with self._lock:
            self._conn.executescript(_WORK_SCHEMA)
            # P13-H migration：additive、versioned、幂等——user_version 单调
            # 推进，重复 reopen 零副作用。
            if self._conn.execute("PRAGMA user_version").fetchone()[0] < 1:
                self._conn.execute("PRAGMA user_version = 1")
            self._conn.execute(
                "INSERT OR REPLACE INTO work_schema_meta(key,value) "
                "VALUES('schema_version',?)", (_SCHEMA_VERSION,))
            self._conn.commit()

    # -------------------------------------------------- 内部工具
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
            attempt_id=str(row["attempt_id"]),
            run_id=str(row["run_id"]),
            backend_id=str(row["backend_id"]),
            state=WorkExecutionState(str(row["state"])),
            state_version=int(row["state_version"]),
            is_active=bool(row["is_active"]),
            cancel_intent=bool(row["cancel_intent"]),
            stop_dispatched=bool(row["stop_dispatched"]),
            approval_invalidated=bool(row["approval_invalidated"]),
            submit_intent=_json(str(row["submit_intent_json"])),
            submit_intent_at=float(row["submit_intent_at"]),
            run_bound_at=float(row["run_bound_at"]),
            terminal_evidence=_json(str(row["terminal_evidence_json"])),
            verification_marker=str(row["verification_marker"]),
            truth_commit_owner=str(row["truth_commit_owner"]),
            truth_commit_status=str(row["truth_commit_status"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def _incr_counter_locked(self, conn: sqlite3.Connection, name: str,
                             n: int = 1) -> None:
        conn.execute(
            "INSERT INTO work_counters(name,value) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET value = value + ?",
            (name, n, n))

    def incr_counter(self, name: str, n: int = 1) -> None:
        """持久化计数器（coalesce/drop/overflow 计数可查询且有界）。"""
        if type(name) is not str or not name or len(name) > 128:
            raise WorkLedgerError("counter name 必须是非空短 builtin str")
        with self._lock:
            with self._conn:
                self._incr_counter_locked(self._conn, name, n)

    def counter(self, name: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM work_counters WHERE name=?", (name,)).fetchone()
            return int(row["value"]) if row is not None else 0

    # -------------------------------------------------- 契约身份（不可变）
    def register_contract(self, contract_id: str, contract_hash: str) -> None:
        """注册不可变 (contract_id, contract_hash)；同 id 异 hash → 类型化冲突
        （幂等：同 id 同 hash 重复注册零副作用）。"""
        for name, value in (("contract_id", contract_id),
                            ("contract_hash", contract_hash)):
            if type(value) is not str or not value or len(value) > 256:
                raise WorkLedgerError(f"{name} 必须是非空短 builtin str")
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._conn.execute(
                    "SELECT contract_hash FROM work_contracts WHERE contract_id=?",
                    (contract_id,)).fetchone()
                if row is not None:
                    if str(row["contract_hash"]) != contract_hash:
                        raise ContractIdentityConflict(
                            f"contract_id {contract_id} 已绑定不同 contract_hash"
                            f"（不可变身份冲突）")
                    return                       # 幂等：同 id 同 hash
                self._conn.execute(
                    "INSERT INTO work_contracts(contract_id,contract_hash,"
                    "registered_at) VALUES(?,?,?)",
                    (contract_id, contract_hash, now))

    def contract_hash_of(self, contract_id: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT contract_hash FROM work_contracts WHERE contract_id=?",
                (contract_id,)).fetchone()
            return str(row["contract_hash"]) if row is not None else None

    # -------------------------------------------------- submit intent（先于远端副作用）
    def submit_intent(self, contract_id: str, contract_hash: str,
                      attempt_id: str,
                      submit_payload: Optional[Mapping[str, Any]] = None) -> int:
        """**submit intent 先持久化，再产生远端副作用**（crash window 1/2 的
        封闭基础）。同 contract 已有 active execution → DuplicateActiveExecution
        （调用方复用该 execution 或放弃，绝不创建第二执行/绝不自动重发 POST）。
        返回新 execution_id。"""
        self.register_contract(contract_id, contract_hash)
        if type(attempt_id) is not str or not attempt_id or len(attempt_id) > 128:
            raise WorkLedgerError("attempt_id 必须是非空短 builtin str")
        blob = _canonical_json(dict(submit_payload or {}),
                               self._max_payload_bytes)
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._conn.execute(
                    "SELECT execution_id FROM work_executions "
                    "WHERE contract_id=? AND is_active=1",
                    (contract_id,)).fetchone()
                if row is not None:
                    raise DuplicateActiveExecution(
                        f"contract {contract_id} 已有 active execution "
                        f"{int(row['execution_id'])}（reconciliation 结束前禁止"
                        f"二次 submit）")
                cur = self._conn.execute(
                    "INSERT INTO work_executions(contract_id,attempt_id,state,"
                    "state_version,is_active,submit_intent_json,submit_intent_at,"
                    "created_at,updated_at) VALUES(?,?,?,?,1,?,?,?,?)",
                    (contract_id, attempt_id,
                     WorkExecutionState.STARTING.value, 1, blob, now, now, now))
                return int(cur.lastrowid)

    # -------------------------------------------------- run 绑定（POST 成功后）
    def bind_run(self, execution_id: int, run_id: str, backend_id: str, *,
                 expected_version: int) -> int:
        """POST 成功后绑定 run/backend（crash window 3/4：intent 已落盘、
        run_id 尚未落盘的窗口由此封闭）。CAS 语义。"""
        for name, value in (("run_id", run_id), ("backend_id", backend_id)):
            if type(value) is not str or not value or len(value) > 128:
                raise WorkLedgerError(f"{name} 必须是非空短 builtin str")
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败："
                        f"expected {expected_version}，"
                        f"actual {int(row['state_version'])}")
                self._conn.execute(
                    "UPDATE work_executions SET run_id=?, backend_id=?, "
                    "run_bound_at=?, state_version=state_version+1, "
                    "updated_at=? WHERE execution_id=? AND state_version=?",
                    (run_id, backend_id, now, now, execution_id,
                     expected_version))
                return expected_version + 1

    # -------------------------------------------------- CAS 状态迁移
    def transition(self, execution_id: int, new_state: WorkExecutionState, *,
                   expected_version: int) -> int:
        """CAS 状态迁移：stale version → :class:`StaleStateVersion`（零状态
        修改）；终态吸收（终态后零迁移，stale worker 绝不能覆盖终态）。"""
        if not isinstance(new_state, WorkExecutionState):
            raise WorkLedgerError("new_state 必须是 WorkExecutionState")
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                current = WorkExecutionState(str(row["state"]))
                if _is_terminal(current):
                    raise WorkLedgerError(
                        f"execution {execution_id} 已终态 {current.value}"
                        f"（终态吸收，零迁移）")
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败："
                        f"expected {expected_version}，"
                        f"actual {int(row['state_version'])}")
                # P13 任务书 §5：取消不可恢复执行——CANCELLING 只能走向终态
                # 或 reconciliation 收口；approval 失效后迟到 approve 不得
                # 复活执行。
                if current is WorkExecutionState.CANCELLING and new_state in (
                        WorkExecutionState.STARTING,
                        WorkExecutionState.RUNNING,
                        WorkExecutionState.WAITING_PERMISSION,
                        WorkExecutionState.BLOCKED_APPROVAL,
                        WorkExecutionState.TOOL_RUNNING,
                        WorkExecutionState.VERIFYING,
                        WorkExecutionState.REPAIRING):
                    raise WorkLedgerError(
                        "CANCELLING 不可恢复执行（迟到 approve/事件不得复活；"
                        "仅真实 terminal evidence 或 timeout policy 收口）")
                if int(row["approval_invalidated"]) == 1 and new_state in (
                        WorkExecutionState.RUNNING,
                        WorkExecutionState.WAITING_PERMISSION,
                        WorkExecutionState.BLOCKED_APPROVAL):
                    raise WorkLedgerError(
                        "approval 已失效（迟到 approve 不得恢复执行）")
                if _is_terminal(new_state):
                    self._conn.execute(
                        "UPDATE work_executions SET state=?, state_version="
                        "state_version+1, is_active=0, updated_at=? "
                        "WHERE execution_id=? AND state_version=?",
                        (new_state.value, now, execution_id, expected_version))
                else:
                    self._conn.execute(
                        "UPDATE work_executions SET state=?, state_version="
                        "state_version+1, updated_at=? "
                        "WHERE execution_id=? AND state_version=?",
                        (new_state.value, now, execution_id, expected_version))
                return expected_version + 1

    def begin_reconciliation(self, execution_id: int, *,
                             expected_version: int) -> int:
        """恢复期：持久化 reconciliation/UNKNOWN 状态（不写 C7）。"""
        return self.transition(execution_id, WorkExecutionState.UNKNOWN,
                               expected_version=expected_version)

    # -------------------------------------------------- 终态证据 / 16F 验证
    def mark_terminal_evidence(self, execution_id: int,
                               evidence: Mapping[str, Any], *,
                               expected_version: int) -> int:
        """持久化 terminal/critical evidence（与终态迁移同事务原子完成）。"""
        blob = _canonical_json(dict(evidence or {}), self._max_payload_bytes)
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败")
                self._conn.execute(
                    "UPDATE work_executions SET terminal_evidence_json=?, "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=?",
                    (blob, now, execution_id, expected_version))
                return expected_version + 1

    def mark_verified_by_outcome(self, execution_id: int, verifier, outcome,
                                 *, expected_version: int) -> int:
        """16F 结果只有经 IndependentVerifier 类拥有的
        ``outcome_is_authentic`` 入口通过，才能在工作域标记 VERIFIED（并持久
        化 verification marker = report_digest）。非 authentic → 类型化拒绝、
        零状态修改。"""
        if not verifier.outcome_is_authentic(outcome):
            raise WorkLedgerError(
                "16F outcome 未通过 outcome_is_authentic 复核"
                "（VERIFIED 标记拒绝，零状态修改）")
        marker = outcome.final_report.report_digest
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                current = WorkExecutionState(str(row["state"]))
                if _is_terminal(current):
                    raise WorkLedgerError(
                        f"execution {execution_id} 已终态 {current.value}"
                        f"（终态吸收，零迁移）")
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败："
                        f"expected {expected_version}，"
                        f"actual {int(row['state_version'])}")
                self._conn.execute(
                    "UPDATE work_executions SET state=?, verification_marker=?, "
                    "is_active=0, state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=?",
                    (WorkExecutionState.VERIFIED.value, marker, now,
                     execution_id, expected_version))
                return expected_version + 1

    # -------------------------------------------------- 取消（PART 5）
    def cancel_intent(self, execution_id: int, *,
                      expected_version: int) -> int:
        """cancel intent 先落盘（重复 cancel 幂等）：pre-submit（run 未绑定）
        → 直接 CANCELLED 终态（零 backend run）；RUNNING/WAITING/REPAIRING/
        VERIFYING → CANCELLING（等真实 terminal evidence 或 timeout policy，
        绝不立即伪造 CANCELLED）。"""
        now = self._now()
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                current = WorkExecutionState(str(row["state"]))
                if _is_terminal(current):
                    return int(row["state_version"])       # 幂等：已终态
                if int(row["state_version"]) != expected_version:
                    raise StaleStateVersion(
                        f"execution {execution_id} CAS 失败")
                if int(row["cancel_intent"]) == 1:
                    return expected_version                # 幂等：intent 已落盘
                run_bound = bool(str(row["run_id"]))
                if not run_bound:
                    # pre-submit cancel：零 backend run、零 submit 副作用。
                    self._conn.execute(
                        "UPDATE work_executions SET cancel_intent=1, state=?, "
                        "is_active=0, state_version=state_version+1, "
                        "updated_at=? WHERE execution_id=? AND state_version=?",
                        (WorkExecutionState.CANCELLED.value, now,
                         execution_id, expected_version))
                    return expected_version + 1
                self._conn.execute(
                    "UPDATE work_executions SET cancel_intent=1, state=?, "
                    "state_version=state_version+1, updated_at=? "
                    "WHERE execution_id=? AND state_version=?",
                    (WorkExecutionState.CANCELLING.value, now,
                     execution_id, expected_version))
                return expected_version + 1

    def dispatch_stop_once(self, execution_id: int) -> bool:
        """backend stop 每活动 run 恰好派发一次（重复 cancel 幂等）：首次
        返回 True（调用方执行远端 stop），之后一律 False（stop 结果不确定时
        由调用方 reconcile，绝不盲目重发）。"""
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                if not str(row["run_id"]):
                    return False        # pre-submit cancel：零 backend run →
                    # 零 backend stop（绝不向不存在的 run 派发）
                if int(row["stop_dispatched"]) == 1:
                    return False
                self._conn.execute(
                    "UPDATE work_executions SET stop_dispatched=1 "
                    "WHERE execution_id=?", (execution_id,))
                return True

    def invalidate_approval(self, execution_id: int) -> None:
        """approval wait 被取消后旧 approval 失效（迟到 approve 不得恢复
        执行）。"""
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "UPDATE work_executions SET approval_invalidated=1 "
                    "WHERE execution_id=?", (execution_id,))

    def approval_invalidated(self, execution_id: int) -> bool:
        with self._lock:
            row = self._execution_row(self._conn, execution_id)
            return bool(row["approval_invalidated"])

    # -------------------------------------------------- 事件（幂等 + 有界）
    def record_event(self, execution_id: int, event_id: str, kind: EventKind,
                     payload: Optional[Mapping[str, Any]] = None) -> str:
        """持久化 normalized event：event_id 同内容重投幂等（返回
        "duplicate"）；同 id 异内容 → :class:`EventContentConflict`；critical
        永不丢弃（per-run/global 容量耗尽 →
        :class:`CriticalBufferOverflow` fail-closed）；droppable tick 在
        per-run/global 容量耗尽时确定性丢弃（计数持久化）。返回
        "stored"/"duplicate"/"dropped" 。"""
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
                "SELECT kind, payload_json FROM work_events WHERE event_id=?",
                (event_id,)).fetchone()
            if row is not None:
                if str(row["kind"]) != kind.value \
                        or str(row["payload_json"]) != blob:
                    raise EventContentConflict(
                        f"event {event_id} 同 id 异内容（类型化冲突）")
                return "duplicate"
            per_run = int(self._conn.execute(
                "SELECT COUNT(*) AS c FROM work_events WHERE execution_id=?",
                (execution_id,)).fetchone()["c"])
            global_n = int(self._conn.execute(
                "SELECT COUNT(*) AS c FROM work_events").fetchone()["c"])
            at_capacity = (per_run >= self._max_events_per_run
                           or global_n >= self._max_global_events)
            if priority.value == "critical" and at_capacity:
                # 溢出计数独立事务持久化（不随 fail-closed 异常回滚），随后
                # 抛出——调用方停止摄取并进入 UNKNOWN/reconcile。
                with self._conn:
                    self._incr_counter_locked(self._conn,
                                              "critical_overflow", 1)
                raise CriticalBufferOverflow(
                    f"critical 缓冲容量耗尽（per_run={per_run}, "
                    f"global={global_n}）——fail-closed 停止摄取，"
                    f"进入 UNKNOWN/reconcile")
            if at_capacity:
                counter = ("progress_dropped" if priority.value == "droppable"
                           else "coalescible_dropped")
                with self._conn:
                    self._incr_counter_locked(self._conn, counter, 1)
                return "dropped"
            with self._conn:
                self._conn.execute(
                    "INSERT INTO work_events(event_id,execution_id,kind,"
                    "payload_json,critical,received_at) VALUES(?,?,?,?,?,?)",
                    (event_id, execution_id, kind.value, blob,
                     1 if priority.value == "critical" else 0, now))
            return "stored"

    def events_of(self, execution_id: int) -> Tuple[Dict[str, Any], ...]:
        """execution 的持久化事件（防御性快照；critical/terminal evidence
        restart 后保留）。"""
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

    # -------------------------------------------------- truth-commit claim（16G 接口）
    def claim_truth_commit(self, execution_id: int,
                           owner_token: str) -> bool:
        """truth-commit claim（CAS）：并发下恰一 owner 胜出；stale claim 拒绝。
        只提供 claim/marker API——本阶段零 C7/C6 写入。"""
        if type(owner_token) is not str or not owner_token or len(owner_token) > 128:
            raise WorkLedgerError("owner_token 必须是非空短 builtin str")
        with self._lock:
            with self._conn:
                row = self._execution_row(self._conn, execution_id)
                if str(row["truth_commit_status"]) != "":
                    return False                    # 已被认领（stale claim 拒绝）
                cur = self._conn.execute(
                    "UPDATE work_executions SET truth_commit_owner=?, "
                    "truth_commit_status='CLAIMED' WHERE execution_id=? "
                    "AND truth_commit_status=''",
                    (owner_token, execution_id))
                return cur.rowcount == 1

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
        """启动恢复：加载全部非终态执行（reconciliation 输入；防御性快照）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM work_executions WHERE is_active=1 "
                "ORDER BY execution_id").fetchall()
            return tuple(self._record_from_row(r) for r in rows)

    def all_executions(self) -> Tuple[ExecutionRecord, ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM work_executions ORDER BY execution_id").fetchall()
            return tuple(self._record_from_row(r) for r in rows)

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
    COALESCED = "coalesced"
    DUPLICATE = "duplicate"


class WorkEventBuffer:
    """纯内存有界事件缓冲（tick 路径安全：offer 零 DB/vector/network I/O）。

    - critical 永不丢弃：容量耗尽 fail-closed 抛
      :class:`CriticalBufferOverflow`（调用方停止摄取并进入 UNKNOWN/
      reconcile；overflow 计数由调用方经 WorkLedger.incr_counter 持久化）；
    - droppable（TOOL_PROGRESS/tokens）per-run 容量耗尽时确定性丢弃；
    - coalescible（reconnect/unknown）合并（同 run 只保留最新观察）；
    - 重复 critical 按稳定身份（event_id）去重，不无限增长。
    """

    def __init__(self, *, per_run_cap: int = 128,
                 global_cap: int = 1024) -> None:
        for name, value in (("per_run_cap", per_run_cap),
                            ("global_cap", global_cap)):
            if type(value) is not int or value < 1:
                raise WorkLedgerError(f"{name} 必须是正 int")
        self._per_run_cap = per_run_cap
        self._global_cap = global_cap
        self._lock = threading.Lock()
        self._events: Dict[str, Dict[str, Any]] = {}       # event_id → event
        self._order: List[str] = []
        self._per_run_count: Dict[str, int] = {}
        self._dropped_ticks = 0
        self._coalesced = 0
        self._duplicates = 0

    def offer(self, event_id: str, kind: EventKind,
              payload: Optional[Mapping[str, Any]] = None) -> EventBufferOutcome:
        """确定性入队（纯内存；绝不阻塞、绝不 I/O）。"""
        if type(event_id) is not str or not event_id:
            raise WorkLedgerError("event_id 必须是非空 builtin str")
        if not isinstance(kind, EventKind):
            raise WorkLedgerError("kind 必须是 EventKind")
        with self._lock:
            if event_id in self._events:
                self._duplicates += 1
                return EventBufferOutcome.DUPLICATE
            priority = classify_priority(kind)
            global_n = len(self._order)
            if priority.value == "critical" and global_n >= self._global_cap:
                raise CriticalBufferOverflow(
                    f"critical 缓冲容量耗尽（global={global_n}）——fail-closed")
            per_key = f"{kind.value}"
            if priority.value == "droppable":
                if self._per_run_count.get(per_key, 0) >= self._per_run_cap:
                    self._dropped_ticks += 1
                    return EventBufferOutcome.DROPPED_TICK
                self._per_run_count[per_key] = \
                    self._per_run_count.get(per_key, 0) + 1
            elif priority.value == "coalescible":
                # 合并：同 kind 的旧观察被最新观察替换（确定性 coalesce）。
                for eid in reversed(self._order):
                    old = self._events.get(eid)
                    if old is not None and old["kind"] is kind:
                        del self._events[eid]
                        self._order.remove(eid)
                        self._coalesced += 1
                        break
            entry = {"event_id": event_id, "kind": kind,
                     "payload": dict(payload or {})}
            self._events[event_id] = entry
            self._order.append(event_id)
            return EventBufferOutcome.ACCEPTED

    def snapshot(self) -> Tuple[Dict[str, Any], ...]:
        """防御性快照（owner 线程批量 flush 到 ledger 用；不暴露内部引用）。"""
        with self._lock:
            return tuple(dict(self._events[eid]) for eid in self._order)

    @property
    def dropped_ticks(self) -> int:
        return self._dropped_ticks

    @property
    def coalesced(self) -> int:
        return self._coalesced

    @property
    def duplicates(self) -> int:
        return self._duplicates

    def clear_operational(self) -> None:
        """清空 operational buffer（restart 后仅此缓冲清空；critical/terminal
        evidence 由 ledger 持久化保留）。"""
        with self._lock:
            self._events.clear()
            self._order.clear()
            self._per_run_count.clear()
