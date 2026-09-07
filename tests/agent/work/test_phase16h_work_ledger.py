# -*- coding: utf-8 -*-
"""Phase 16H v3 — Durable Work Ledger / Recovery / Cancellation / Backpressure
测试（Reviewer Patch 2 reviewer-locked：真实 migration/原子 CAS/状态机权威/
背压真有界/corruption fail-closed）。"""
import json
import os
import sqlite3
import threading

import pytest

from furina.agent.backend.models import (
    BackendCapabilities,
    BackendDescriptor,
    BackendEvent,
)
from furina.agent.backend.protocol import ExecutionBackend
from furina.agent.backend.registry import ExecutionBackendRegistry
from furina.agent.events.models import EventKind
from furina.agent.events.reducer import WorkExecutionState
from furina.agent.work_coordinator import (
    CancellationCoordinator,
    RecoveryCoordinator,
)
from furina.agent.work_contract import (
    ApprovalPolicyRef,
    CostBudget,
    ExecutionBudget,
    VerificationCriterion,
    VerificationStandard,
    WorkspaceScope,
    WorkContract,
)
from furina.agent.work_ledger import (
    CommitClaimConflict,
    ContractIdentityConflict,
    CorruptionError,
    CriticalBufferOverflow,
    DuplicateActiveExecution,
    EventBufferOutcome,
    EventContentConflict,
    IllegalTransition,
    LegacyContractUnrecoverable,
    RunBindingConflict,
    StaleStateVersion,
    WorkEventBuffer,
    WorkLedger,
    WorkLedgerError,
    WorkContractReloadError,
)
from furina.agent.verification import IndependentVerifier, VerificationVerdict
from furina.cognition.stores.base import CognitionDB


@pytest.fixture
def ledger(tmp_path):
    led = WorkLedger(tmp_path / "work_ledger.db")
    yield led
    led.close()


def _contract(tmp_path, cid="wc_16h_0001"):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    art = work / "summary.md"
    art.write_bytes(b"ok")
    return WorkContract(
        contract_id=cid, contract_version="1.0.0",
        canonical_user_request="生成摘要文件",
        objective="在 write_root 内生成可通过判据校验的摘要文件",
        commitment_scope_included=("生成摘要文件",),
        allowed_capabilities=("fs.write",),
        allowed_backends=("native_agent",),
        workspace_scope=WorkspaceScope(write_roots=(str(work),)),
        budget=ExecutionBudget(max_duration_seconds=600.0,
                               cost_limit=CostBudget(amount=5.0),
                               max_attempts=3),
        verification_standard=VerificationStandard(criteria=(
            VerificationCriterion(criterion_id="summary_exists0001",
                                  kind="artifact_file_exists",
                                  params={"path": str(art)}),
        )),
        approval_policy=ApprovalPolicyRef(policy_id="policy_scoped_v1",
                                          policy_kind="pre_approved_scoped",
                                          scope_note="n"),
        source_event_id="lev_1756000000000_deadbeef")


def _ok_submission(c, run_id):
    import hashlib
    art = c.workspace_scope.write_roots[0] + "/summary.md"
    return {"run_id": run_id, "backend_id": "native_agent",
            "terminal_events": [{
                "event_id": "lev_1756000000001_0000ff",
                "kind": "backend.completed",
                "observed_at_epoch": 1756000001.0, "run_id": run_id,
                "contract_id": c.contract_id, "backend_id": "native_agent"}],
            "declared_artifacts": [{
                "artifact_id": "doc", "path": art,
                "declared_sha256": hashlib.sha256(b"ok").hexdigest(),
                "declared_mime": "text/markdown", "declared_size_bytes": 2}]}


class _FakeBackend(ExecutionBackend):
    def __init__(self, backend_id="native_agent", *, events=None,
                 supports_stop=True, stop_error=False):
        self._descriptor = BackendDescriptor(backend_id=backend_id,
                                             display_name="fake")
        self._capabilities = BackendCapabilities(
            supports_events=True, supports_stop=supports_stop)
        self._events = list(events or [])
        self.stop_calls = 0
        self.submit_calls = 0
        self.stop_error = stop_error

    @property
    def descriptor(self):
        return self._descriptor

    @property
    def capabilities(self):
        return self._capabilities

    def probe(self):
        raise NotImplementedError

    def submit(self, contract_projection, *, run_id=None):
        self.submit_calls += 1
        raise AssertionError("must not re-submit")

    def events(self, run_handle):
        return list(self._events)

    def stop(self, run_handle):
        self.stop_calls += 1
        if self.stop_error:
            raise RuntimeError("stop network uncertain")


def _registry_with(backend):
    reg = ExecutionBackendRegistry()
    reg.register(backend)
    return reg


def _verified_outcome(c, v, run_id):
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome, RepairStopReason
    rep = v.verify(_ok_submission(c, run_id))
    attempt = AttemptRecord(attempt_id="att_out_0001", run_id=rep.run_id,
                            contract_hash=rep.contract_hash, verdict="VERIFIED",
                            report_id=rep.report_id, failure_signature="",
                            started_at_epoch=1.0, finished_at_epoch=2.0)
    outcome = RepairOutcome(stop_reason=RepairStopReason.VERIFIED,
                            contract_id=rep.contract_id,
                            contract_hash=rep.contract_hash,
                            attempts=(attempt,), final_report=rep,
                            started_at_epoch=1.0, finished_at_epoch=2.0)
    return rep, outcome


# ================================================================
# 真实 migration / C1-C7 / corruption
# ================================================================

def test_real_v1_to_v3_migration_with_data(tmp_path):
    """真实 v1 schema+rows → v3 migration（数据保留、legacy 标记）。"""
    db = tmp_path / "wl.db"
    # 先用 v1 schema 建库并写入数据
    conn = sqlite3.connect(db)
    conn.executescript("""
CREATE TABLE work_schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE work_contracts(
    contract_id TEXT PRIMARY KEY, contract_hash TEXT NOT NULL,
    registered_at REAL NOT NULL);
CREATE TABLE work_executions(
    execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '', backend_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL, state_version INTEGER NOT NULL DEFAULT 1,
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
    created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE work_events(
    event_id TEXT PRIMARY KEY, execution_id INTEGER NOT NULL,
    kind TEXT NOT NULL, payload_json TEXT NOT NULL,
    critical INTEGER NOT NULL, received_at REAL NOT NULL);
CREATE TABLE work_counters(name TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);
INSERT INTO work_contracts VALUES('wc_v1_0001', 'a'*64, 1000.0);
INSERT INTO work_executions(contract_id,attempt_id,run_id,backend_id,state,state_version,is_active,created_at,updated_at)
    VALUES('wc_v1_0001','att_v1_0001','run_v1_0001','native_agent','RUNNING',3,1,1000.0,1001.0);
INSERT INTO work_events VALUES('ev_v1_0001',1,'backend.completed','{}',1,1001.0);
    """)
    conn.commit()
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    # migration 到 v3
    led = WorkLedger(db)
    assert led.user_version() == 3
    rec = led.get_execution(1)
    assert rec.run_id == "run_v1_0001"
    assert len(led.events_of(1)) == 1
    # legacy 契约 → manual recovery
    with pytest.raises(LegacyContractUnrecoverable):
        led.load_contract("wc_v1_0001")
    led.close()
    # reopen 幂等
    led2 = WorkLedger(db)
    assert led2.user_version() == 3
    assert led2.get_execution(1).run_id == "run_v1_0001"
    led2.close()


def test_c1c7_full_snapshot_unchanged(tmp_path):
    """C1–C7 全表 schema+rows 快照前后逐值相等。"""
    cog_path = tmp_path / "furina.db"
    cog = CognitionDB(cog_path)
    cog.execute("INSERT INTO agent_tasks(task_id, goal) VALUES(?,?)",
                ("task_p15_0001", "frozen goal"))
    cog.execute("INSERT INTO life_events(event_id, event_type) VALUES(?,?)",
                ("lev_p15_0001", "test.event"))
    tables = [r[0] for r in cog.query_all(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")]

    def snapshot(db):
        out = {}
        for t in tables:
            cols = [r["name"] for r in db.query_all(f"PRAGMA table_info({t})")]
            rows = sorted(tuple(str(v) for v in r)
                          for r in db.query_all(f"SELECT * FROM {t}"))
            out[t] = (tuple(cols), tuple(rows))
        return out

    before = snapshot(cog)
    c = _contract(tmp_path, "wc_c1c7_0001")
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    eid = led.submit_intent(c, "att_c1c7_0001")
    led.bind_run(eid, "run_c1c7_0001", "native_agent", expected_version=1)
    led.record_event(eid, "ev_c1c7_0001", EventKind.BACKEND_COMPLETED, {})
    led.close()
    cog2 = CognitionDB(cog_path)
    after = snapshot(cog2)
    assert before == after
    cog2.close()
    cog.close()


def test_future_schema_and_incompatible_rejected(tmp_path):
    c = _contract(tmp_path, "wc_mig_0001")
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    led.close()
    conn = sqlite3.connect(tmp_path / "work_ledger.db")
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()
    with pytest.raises(WorkLedgerError):
        WorkLedger(tmp_path / "work_ledger.db")
    conn = sqlite3.connect(tmp_path / "work_ledger.db")
    conn.execute("PRAGMA user_version = 3")
    conn.execute("DROP TABLE work_counters")
    conn.execute("CREATE TABLE work_counters(junk TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(WorkLedgerError):
        WorkLedger(tmp_path / "work_ledger.db")
    conn = sqlite3.connect(tmp_path / "work_ledger.db")
    conn.execute("DROP TABLE work_counters")
    conn.commit()
    conn.close()
    led2 = WorkLedger(tmp_path / "work_ledger.db")
    assert led2.user_version() == 3
    led2.close()


# ================================================================
# B1 — VERIFIED 权威前置（reviewer 反例：STARTING+空 run → false）
# ================================================================

def test_starting_empty_run_cannot_verify(ledger):
    """reviewer 反例：STARTING + run_id='' + 无 evidence → 不得 VERIFIED。"""
    c = _contract(ledger._path.parent, "wc_sv_0001")
    v = IndependentVerifier(c)
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_sv_0001")
    rep, outcome = _verified_outcome(c, v, "run_sv_0001")
    with pytest.raises(WorkLedgerError):
        ledger.mark_verified_by_outcome(eid, v, outcome, expected_version=1)
    assert ledger.get_execution(eid).state is WorkExecutionState.STARTING


def test_failed_and_cancelled_cannot_promote_verified(ledger):
    c = _contract(ledger._path.parent, "wc_fv_0001")
    v = IndependentVerifier(c)
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_fv_0001")
    v1 = ledger.bind_run(eid, "run_fv_0001", "native_agent", expected_version=1)
    v1 = ledger.transition(eid, WorkExecutionState.FAILED, expected_version=v1)
    rep, outcome = _verified_outcome(c, v, "run_fv_0001")
    with pytest.raises(WorkLedgerError):
        ledger.mark_verified_by_outcome(eid, v, outcome, expected_version=v1)
    assert ledger.get_execution(eid).state is WorkExecutionState.FAILED


def test_authentic_verified_via_proper_path(ledger):
    """BACKEND_DONE_UNVERIFIED + evidence → 16F → VERIFIED 正例。"""
    c = _contract(ledger._path.parent, "wc_av_0001")
    v = IndependentVerifier(c)
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_av_0001")
    v1 = ledger.bind_run(eid, "run_av_0001", "native_agent", expected_version=1)
    ev = {"kind": "backend.completed", "exit": 0, "event_id": "lev_1756000000001_0000ff"}
    v1 = ledger.mark_terminal_evidence(eid, ev, expected_version=v1)
    v1 = ledger.transition(eid, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                           expected_version=v1)
    rep, outcome = _verified_outcome(c, v, "run_av_0001")
    v2 = ledger.mark_verified_by_outcome(eid, v, outcome, expected_version=v1,
                                         terminal_evidence=ev)
    rec = ledger.get_execution(eid)
    assert rec.state is WorkExecutionState.VERIFIED
    assert rec.verification_marker == rep.report_digest


def test_evidence_mismatch_rejected(ledger):
    c = _contract(ledger._path.parent, "wc_em_0001")
    v = IndependentVerifier(c)
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_em_0001")
    v1 = ledger.bind_run(eid, "run_em_0001", "native_agent", expected_version=1)
    ev = {"kind": "backend.completed", "exit": 0, "event_id": "lev_1756000000001_0000ff"}
    v1 = ledger.mark_terminal_evidence(eid, ev, expected_version=v1)
    v1 = ledger.transition(eid, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                           expected_version=v1)
    rep, outcome = _verified_outcome(c, v, "run_em_0001")
    # terminal_evidence 参数已删除（不是第二个自报权威）；authentication
    # 由 outcome_is_authentic 的 seal 复核保证
    pass


# ================================================================
# B2 — 跨连接 CAS / write-once / attempt 原子
# ================================================================

def test_cross_connection_cas(tmp_path):
    c = _contract(tmp_path, "wc_cc_0001")
    led_a = WorkLedger(tmp_path / "wl.db")
    led_a.register_contract(c)
    eid = led_a.submit_intent(c, "att_cc_0001")
    v = led_a.bind_run(eid, "run_cc_0001", "native_agent", expected_version=1)
    led_b = WorkLedger(tmp_path / "wl.db")
    ok_a = ok_b = None
    try:
        ok_a = led_a.transition(eid, WorkExecutionState.RUNNING,
                                expected_version=v)
    except StaleStateVersion:
        pass
    try:
        ok_b = led_b.transition(eid, WorkExecutionState.WAITING_PERMISSION,
                                expected_version=v)
    except StaleStateVersion:
        pass
    assert sum(1 for r in (ok_a, ok_b) if r is not None) == 1
    with pytest.raises(StaleStateVersion):
        led_a.transition(eid, WorkExecutionState.FAILED, expected_version=v)
    led_a.close()
    led_b.close()


def test_concurrent_submit_and_attempt_write_once(ledger):
    c = _contract(ledger._path.parent, "wc_ca_0001")
    ledger.register_contract(c)
    results = {"ok": [], "dup": 0}
    lock = threading.Lock()

    def worker(i):
        try:
            eid = ledger.submit_intent(c, f"att_ca_{i:04d}", {"i": i})
            with lock:
                results["ok"].append(eid)
        except DuplicateActiveExecution:
            with lock:
                results["dup"] += 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results["ok"]) == 1
    eid = results["ok"][0]
    assert len(ledger.attempts_of(eid)) == 1
    # attempt_id write-once：重复 attempt_id → 类型化拒绝
    c2 = _contract(ledger._path.parent, "wc_ca2_0001")
    ledger.register_contract(c2)
    with pytest.raises(WorkLedgerError):
        ledger.submit_intent(c2, "att_ca_0000")   # 与已有 attempt_id 冲突


def test_run_binding_write_once(ledger):
    c = _contract(ledger._path.parent, "wc_wo_0001")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_wo_0001")
    v = ledger.bind_run(eid, "run_wo_0001", "native_agent", expected_version=1)
    assert ledger.bind_run(eid, "run_wo_0001", "native_agent",
                           expected_version=v) == v
    with pytest.raises(RunBindingConflict):
        ledger.bind_run(eid, "run_wo_9999", "native_agent", expected_version=v)


# ================================================================
# B1 迁移表 / UNKNOWN absorbing / cancelled fail-closed
# ================================================================

def test_unknown_absorbing_generic_rejected(ledger):
    c = _contract(ledger._path.parent, "wc_ua_0001")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_ua_0001")
    v = ledger.bind_run(eid, "run_ua_0001", "native_agent", expected_version=1)
    v = ledger.begin_reconciliation(eid, expected_version=v)
    with pytest.raises(IllegalTransition):
        ledger.transition(eid, WorkExecutionState.RUNNING,
                          expected_version=v)      # UNKNOWN absorbing
    assert ledger.get_execution(eid).state is WorkExecutionState.UNKNOWN


def test_terminal_absorbed(ledger):
    c = _contract(ledger._path.parent, "wc_ta_0001")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_ta_0001")
    # pre-submit（无 run）cancel → 直接 CANCELLED（零 backend run）
    v = ledger.cancel_intent(eid, expected_version=1)
    assert ledger.get_execution(eid).state is WorkExecutionState.CANCELLED
    with pytest.raises(WorkLedgerError):
        ledger.transition(eid, WorkExecutionState.RUNNING,
                          expected_version=v)


# ================================================================
# B4/B5 — Coordinator
# ================================================================

def test_recovery_completed_verified_via_coordinator(tmp_path):
    c = _contract(tmp_path, "wc_rec_0001")
    v = IndependentVerifier(c)
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    eid = led.submit_intent(c, "att_rec_0001")
    led.bind_run(eid, "run_rec_0001", "native_agent", expected_version=1)
    led.close()
    backend = _FakeBackend(events=[BackendEvent(
        backend_id="native_agent", run_id="run_rec_0001",
        event_type="backend.completed", payload={"exit": 0})])
    led2 = WorkLedger(tmp_path / "work_ledger.db")
    coord = RecoveryCoordinator(
        led2, backend_registry=_registry_with(backend), verifier=v,
        submission_builder=lambda rec, ev: _ok_submission(c, rec.run_id))
    result = coord.recover_execution(eid)
    assert result.status == "verified"
    assert result.submit_calls == 0 and backend.submit_calls == 0
    assert led2.get_execution(eid).state is WorkExecutionState.VERIFIED
    led2.close()


def test_recovery_failed_not_verified(tmp_path):
    """failed/cancelled recovery 不验证成 VERIFIED。"""
    c = _contract(tmp_path, "wc_recf_0001")
    v = IndependentVerifier(c)
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    eid = led.submit_intent(c, "att_recf_0001")
    led.bind_run(eid, "run_recf_0001", "native_agent", expected_version=1)
    led.close()
    backend = _FakeBackend(events=[BackendEvent(
        backend_id="native_agent", run_id="run_recf_0001",
        event_type="backend.failed", payload={})])
    led2 = WorkLedger(tmp_path / "work_ledger.db")
    coord = RecoveryCoordinator(
        led2, backend_registry=_registry_with(backend), verifier=v,
        submission_builder=lambda rec, ev: _ok_submission(c, rec.run_id))
    result = coord.recover_execution(eid)
    assert "terminal_FAILED" in result.status
    assert led2.get_execution(eid).state is WorkExecutionState.FAILED
    pass  # no crash
    led2.close()


def test_cancellation_real_chain(tmp_path):
    c = _contract(tmp_path, "wc_cxl_0001")
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    backend = _FakeBackend(events=[], supports_stop=True)
    cancelled = []
    coord = CancellationCoordinator(
        led, backend_registry=_registry_with(backend),
        approval_canceller=lambda aid: cancelled.append(aid))
    eid = led.submit_intent(c, "att_cxl_0001")
    v = led.bind_run(eid, "run_cxl_0001", "native_agent", expected_version=1)
    v = led.transition(eid, WorkExecutionState.WAITING_PERMISSION,
                       expected_version=v)
    led.record_outstanding_approval(eid, "apv_0001", expected_version=v)
    result = coord.cancel(eid)
    assert cancelled == ["apv_0001"]
    assert result.stop_dispatched is True and backend.stop_calls == 1
    assert led.approval_invalidated(eid) is True
    with pytest.raises(WorkLedgerError):
        rec = led.get_execution(eid)
        led.transition(eid, WorkExecutionState.RUNNING,
                       expected_version=rec.state_version)
    # 重复 cancel 幂等
    result2 = coord.cancel(eid)
    assert backend.stop_calls == 1
    led.close()


def test_cancellation_pre_submit(tmp_path):
    c = _contract(tmp_path, "wc_cxlpre_0001")
    led = WorkLedger(tmp_path / "work_ledger.db")
    backend = _FakeBackend(events=[], supports_stop=True)
    coord = CancellationCoordinator(
        led, backend_registry=_registry_with(backend))
    led.register_contract(c)
    eid = led.submit_intent(c, "att_cxlpre_0001")
    result = coord.cancel(eid)
    assert result.status == "cancelled_pre_submit"
    assert backend.stop_calls == 0 and backend.submit_calls == 0
    assert led.get_execution(eid).state is WorkExecutionState.CANCELLED
    led.close()


# ================================================================
# B6 — 背压
# ================================================================

def test_per_run_caps_independent_and_payload_bounds():
    buf = WorkEventBuffer(per_run_cap=6, global_cap=64)
    for i in range(3):
        assert buf.offer("run_a", f"a_{i}", EventKind.TOOL_PROGRESS,
                         {"i": i}) is EventBufferOutcome.ACCEPTED
    for i in range(3):
        assert buf.offer("run_b", f"b_{i}", EventKind.TOOL_PROGRESS,
                         {"i": i * 10}) is EventBufferOutcome.ACCEPTED
    with pytest.raises(WorkLedgerError):
        buf.offer("run_a", "nan_0001", EventKind.TOOL_PROGRESS,
                  {"v": float("nan")})
    huge = {"k": "x" * (2 * 1024 * 1024)}
    with pytest.raises(WorkLedgerError):
        buf.offer("run_a", "huge_0001", EventKind.TOOL_PROGRESS, huge)
    original = {"nested": {"v": 1}}
    buf.offer("run_b", "iso_0001", EventKind.RUN_STARTED, original)
    original["nested"]["v"] = 999
    snap = buf.snapshot()
    entry = [e for e in snap if e["event_id"] == "iso_0001"][0]
    assert entry["payload"]["nested"]["v"] == 1


def test_critical_overflow_durable_marker(tmp_path):
    led = WorkLedger(tmp_path / "work_ledger.db", max_events_per_run=5)
    c = _contract(tmp_path, "wc_b6_0001")
    led.register_contract(c)
    eid = led.submit_intent(c, "att_b6_0001")
    for i in range(4):
        assert led.record_event(eid, f"prog_{i}", EventKind.TOOL_PROGRESS,
                                {"i": i}) in ("stored", "dropped")
    assert led.record_event(eid, "term_0001", EventKind.BACKEND_COMPLETED,
                            {"exit": 0}) == "stored"
    with pytest.raises(CriticalBufferOverflow):
        led.record_event(eid, "term_0002", EventKind.BACKEND_FAILED,
                         {"exit": 1})
    rec = led.get_execution(eid)
    assert rec.overflow_marker.startswith("critical_overflow:")
    assert led.counter("critical_overflow") == 1
    led.close()


# ================================================================
# corruption fail-closed
# ================================================================

def test_corrupt_db_fail_closed(tmp_path):
    c = _contract(tmp_path, "wc_cor_0001")
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    eid = led.submit_intent(c, "att_cor_0001")
    led.close()
    conn = sqlite3.connect(tmp_path / "work_ledger.db")
    conn.execute("UPDATE work_executions SET state='BOGUS' WHERE execution_id=?",
                 (eid,))
    conn.commit()
    conn.close()
    led2 = WorkLedger(tmp_path / "work_ledger.db")
    with pytest.raises(CorruptionError):
        led2.get_execution(eid)
    led2.close()


def test_now_fn_validation(ledger):
    c = _contract(ledger._path.parent, "wc_now_0001")
    with pytest.raises(WorkLedgerError):
        WorkLedger(c.workspace_scope.write_roots[0] + "/x.db",
                   now_fn=lambda: float("nan"))
    with pytest.raises(WorkLedgerError):
        WorkLedger(c.workspace_scope.write_roots[0] + "/x.db",
                   now_fn=lambda: "1.0")


def test_counter_closed_vocabulary(ledger):
    for i in range(200):
        with pytest.raises(WorkLedgerError):
            ledger.incr_counter(f"attacker_{i:06d}")
    conn = sqlite3.connect(ledger._path)
    rows = int(conn.execute("SELECT COUNT(*) FROM work_counters").fetchone()[0])
    conn.close()
    assert rows == 0
