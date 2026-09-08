# -*- coding: utf-8 -*-
"""Phase 16H Reviewer Patch 5 WIP-continuation reviewer-locked 测试。

- 统一 attempt CAS：attempt_id + execution_id + contract_id + contract_hash
  + 旧 state + 旧 state_version 全谓词 + rowcount==1（外部改写 → CorruptionError
  零部分写入）。
- execution/attempt version 全程 lockstep。
- 真实 backend 实例证明（布尔信任参数废除）。
- invalidate_approval CAS + 幂等。
- events_of/progress_latest corruption fail-closed。
- 真实 v2→v3 additive migration fixture。
- WorkEventBuffer raw UTF-8 预检（sanitize 截断前拒绝）+ peek→persist→ack
  + 秘密 sanitize at-rest。
- coordinator evidence 全身份绑定（builder 忽略 evidence → fail-closed）。
"""
import json
import sqlite3

import pytest

from furina.agent.backend.models import BackendEvent
from furina.agent.events.models import EventKind
from furina.agent.events.reducer import WorkExecutionState
from furina.agent.backend.registry import ExecutionBackendRegistry
from furina.agent.work_coordinator import (
    CancellationCoordinator,
    RecoveryCoordinator,
)
from furina.agent.work_ledger import (
    CorruptionError,
    CriticalBufferOverflow,
    EventBufferOutcome,
    StaleStateVersion,
    WorkEventBuffer,
    WorkLedger,
    WorkLedgerError,
)
from furina.agent.verification import IndependentVerifier

from tests.agent.work.test_phase16h_work_ledger import (
    _contract,
    _evidence_bound_builder,
    _FakeBackend,
    _ok_submission,
    _registry_with,
)


@pytest.fixture
def ledger(tmp_path):
    led = WorkLedger(tmp_path / "work_ledger.db")
    yield led
    led.close()


# ================================================================
# 统一 attempt CAS
# ================================================================

def test_attempt_cas_tampered_state_rejected(ledger, tmp_path):
    """attempt 行 state 被外部改写 → 下一次 mutation CorruptionError 零部分写入。"""
    c = _contract(tmp_path, "wc_acs_0001")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_acs_0001")
    v = ledger.bind_run(eid, "run_acs_0001", "native_agent", expected_version=1)
    conn = sqlite3.connect(ledger._path)
    conn.execute("UPDATE work_attempts SET state='RUNNING' WHERE attempt_id=?",
                 ("att_acs_0001",))
    conn.commit()
    conn.close()
    with pytest.raises(CorruptionError):
        ledger.transition(eid, WorkExecutionState.RUNNING, expected_version=v)
    rec = ledger.get_execution(eid)      # execution 零部分写入（事务回滚）
    assert rec.state is WorkExecutionState.STARTING
    assert rec.state_version == v


def test_attempt_cas_tampered_version_rejected(ledger, tmp_path):
    c = _contract(tmp_path, "wc_acs_0002")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_acs_0002")
    v = ledger.bind_run(eid, "run_acs_0002", "native_agent", expected_version=1)
    conn = sqlite3.connect(ledger._path)
    conn.execute("UPDATE work_attempts SET state_version=state_version+5 "
                 "WHERE attempt_id=?", ("att_acs_0002",))
    conn.commit()
    conn.close()
    with pytest.raises(CorruptionError):
        ledger.cancel_intent(eid, expected_version=v)
    rec = ledger.get_execution(eid)
    assert rec.state is WorkExecutionState.STARTING
    assert rec.cancel_intent is False


def test_attempt_cas_tampered_identity_rejected(ledger, tmp_path):
    """attempt contract_hash 被改写 → 全谓词 CAS 拒绝（身份绑定）。"""
    c = _contract(tmp_path, "wc_acs_0003")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_acs_0003")
    v = ledger.bind_run(eid, "run_acs_0003", "native_agent", expected_version=1)
    conn = sqlite3.connect(ledger._path)
    conn.execute("UPDATE work_attempts SET contract_hash=? WHERE attempt_id=?",
                 ("f" * 64, "att_acs_0003"))
    conn.commit()
    conn.close()
    with pytest.raises(CorruptionError):
        ledger.transition(eid, WorkExecutionState.RUNNING, expected_version=v)


def test_execution_attempt_versions_stay_in_lockstep(ledger, tmp_path):
    """全部 mutation 后 execution 与 attempt state/version 逐值一致。"""
    c = _contract(tmp_path, "wc_lck_0001")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_lck_0001")
    v = ledger.bind_run(eid, "run_lck_0001", "native_agent", expected_version=1)
    v = ledger.record_outstanding_approval(eid, "apv_lck_0001",
                                           expected_version=v)
    v = ledger.invalidate_approval(eid, expected_version=v)
    v = ledger.transition(eid, WorkExecutionState.WAITING_PERMISSION,
                          expected_version=v)
    v = ledger.mark_terminal_evidence(
        eid, {"kind": "backend.completed", "event_id": "e1"},
        expected_version=v)
    v = ledger.transition(eid, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                          expected_version=v)
    rec = ledger.get_execution(eid)
    at = ledger.attempts_of(eid)[0]
    assert rec.state_version == at["state_version"]
    assert rec.state.value == at["state"]


# ================================================================
# 真实 backend 证明 / approval CAS
# ================================================================

def test_dispatch_stop_requires_real_backend_instance(ledger, tmp_path):
    """布尔信任参数已废除：None/不支持 stop 的 backend → False 零副作用。"""
    c = _contract(tmp_path, "wc_stp_0001")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_stp_0001")
    v = ledger.bind_run(eid, "run_stp_0001", "native_agent", expected_version=1)
    no_stop = _FakeBackend(supports_stop=False)
    assert ledger.dispatch_stop_once(eid, backend=None,
                                     expected_version=v) is False
    assert ledger.dispatch_stop_once(eid, backend=no_stop,
                                     expected_version=v) is False
    ok = _FakeBackend(supports_stop=True)
    assert ledger.dispatch_stop_once(eid, backend=ok,
                                     expected_version=v) is True
    assert ledger.dispatch_stop_once(eid, backend=ok,
                                     expected_version=v) is False   # 幂等
    at = ledger.attempts_of(eid)[0]
    rec = ledger.get_execution(eid)
    assert rec.stop_dispatched is True
    assert rec.state_version == at["state_version"]


def test_invalidate_approval_cas_and_idempotent(ledger, tmp_path):
    c = _contract(tmp_path, "wc_iap_0001")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_iap_0001")
    v = ledger.record_outstanding_approval(eid, "apv_iap_0001",
                                           expected_version=1)
    with pytest.raises(StaleStateVersion):
        ledger.invalidate_approval(eid, expected_version=v + 99)
    v2 = ledger.invalidate_approval(eid, expected_version=v)
    assert ledger.approval_invalidated(eid) is True
    v3 = ledger.invalidate_approval(eid, expected_version=v2)
    assert v3 == v2      # 幂等：返回 DB 真实 version，零改写
    with pytest.raises(WorkLedgerError):
        ledger.record_outstanding_approval(eid, "apv_iap_0002",
                                           expected_version=v3)


# ================================================================
# corruption fail-closed 读取面
# ================================================================

def test_events_and_progress_corruption_fail_closed(tmp_path):
    c = _contract(tmp_path, "wc_evc_0001")
    led = WorkLedger(tmp_path / "wl_evc.db")
    led.register_contract(c)
    eid = led.submit_intent(c, "att_evc_0001")
    led.record_event(eid, "ev_0001", EventKind.BACKEND_COMPLETED, {"exit": 0})
    led.record_event(eid, "prog_0001", EventKind.TOOL_PROGRESS, {"i": 1})
    led.close()
    conn = sqlite3.connect(tmp_path / "wl_evc.db")
    conn.execute("UPDATE work_events SET payload_json='{broken' "
                 "WHERE event_id='ev_0001'")
    conn.commit()
    conn.close()
    led2 = WorkLedger(tmp_path / "wl_evc.db")
    with pytest.raises(CorruptionError):
        led2.events_of(eid)
    led2.close()
    conn = sqlite3.connect(tmp_path / "wl_evc.db")
    # 直接注入损坏 progress 行（work_progress 是单槽 coalesce 表）
    conn.execute("INSERT OR REPLACE INTO work_progress(execution_id,"
                 "payload_json,updated_at) VALUES(?,?,?)",
                 (eid, "[1,2]", 1234.0))
    conn.commit()
    conn.close()
    led3 = WorkLedger(tmp_path / "wl_evc.db")
    with pytest.raises(CorruptionError):
        led3.progress_latest(eid)
    led3.close()


def test_v2_to_v3_migration_additive(tmp_path):
    """真实 v2 schema（无 legacy_unrecoverable / work_attempts）→ v3。"""
    db = tmp_path / "wl2.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
CREATE TABLE work_schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE work_contracts(
    contract_id TEXT PRIMARY KEY, contract_hash TEXT NOT NULL,
    transport_json TEXT NOT NULL DEFAULT '', registered_at REAL NOT NULL);
CREATE TABLE work_executions(
    execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id TEXT NOT NULL, contract_hash TEXT NOT NULL DEFAULT '',
    attempt_id TEXT NOT NULL, run_id TEXT NOT NULL DEFAULT '',
    backend_id TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
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
    created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE work_events(
    execution_id INTEGER NOT NULL, event_id TEXT NOT NULL,
    kind TEXT NOT NULL, payload_json TEXT NOT NULL,
    critical INTEGER NOT NULL, received_at REAL NOT NULL,
    PRIMARY KEY (execution_id, event_id));
CREATE TABLE work_counters(name TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0);
INSERT INTO work_contracts VALUES('wc_v2_0001', 'b'*64, '{}', 2000.0);
INSERT INTO work_executions(contract_id,contract_hash,attempt_id,state,
    state_version,is_active,created_at,updated_at)
    VALUES('wc_v2_0001','b'*64,'att_v2_0001','RUNNING',2,1,2000.0,2001.0);
    """)
    conn.commit()
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()
    led = WorkLedger(db)
    assert led.user_version() == 3
    rec = led.get_execution(1)
    assert rec.attempt_id == "att_v2_0001"
    ats = led.attempts_of(1)
    assert len(ats) == 1 and ats[0]["attempt_id"] == "att_v2_0001"
    row = led._conn.execute(
        "SELECT legacy_unrecoverable FROM work_contracts").fetchone()
    assert int(row["legacy_unrecoverable"]) == 0   # v2 有 transport → 可恢复
    led.close()
    led2 = WorkLedger(db)
    assert led2.user_version() == 3
    led2.close()


# ================================================================
# 背压：raw 预检 / peek→persist→ack / 秘密 at-rest
# ================================================================

def test_buffer_peek_persist_ack_protocol():
    buf = WorkEventBuffer(per_run_cap=2, global_cap=8)
    for i in range(2):
        assert buf.offer("run_p", f"p_{i}", EventKind.TOOL_PROGRESS,
                         {"i": i}) is EventBufferOutcome.ACCEPTED
    snap = buf.peek()
    assert len(snap) == 2
    assert buf.peek() == snap          # peek 不清空：crash 后可重复
    with pytest.raises(WorkLedgerError):
        buf.ack([("run_p", "nope_0001")])   # 未 peek 的 key 类型化拒绝
    assert buf.ack([("run_p", "p_0"), ("run_p", "p_1")]) == 2
    assert buf.peek() == ()
    assert buf.offer("run_p", "p_2", EventKind.TOOL_PROGRESS,
                     {}) is EventBufferOutcome.ACCEPTED   # 容量已释放


def test_buffer_raw_bytes_precheck_before_sanitize():
    buf = WorkEventBuffer()
    huge = {"k": "x" * (2 * 1024 * 1024)}
    with pytest.raises(WorkLedgerError):
        buf.offer("run_r", "huge_0001", EventKind.TOOL_PROGRESS, huge)
    assert buf.peek() == ()            # 零残留
    mid = {"k": "y" * (80 * 1024)}
    with pytest.raises(WorkLedgerError):
        buf.offer("run_r", "mid_0001", EventKind.TOOL_PROGRESS, mid)
    assert buf.offer("run_r", "ok_0001", EventKind.TOOL_PROGRESS,
                     {"v": 1}) is EventBufferOutcome.ACCEPTED


def test_buffer_secret_payload_sanitized_at_rest():
    buf = WorkEventBuffer()
    assert buf.offer("run_s", "sec_0001", EventKind.BACKEND_COMPLETED,
                     {"api_key": "sk_abcdefghijklmnop1234",
                      "note": "token=supersecretvalue"}) \
        is EventBufferOutcome.ACCEPTED
    blob = json.dumps(buf.snapshot(), ensure_ascii=True)
    assert "sk_abcdefghijklmnop1234" not in blob
    assert "supersecretvalue" not in blob


# ================================================================
# coordinator evidence 全身份绑定 / 无 backend 取消
# ================================================================

def test_recovery_builder_ignoring_evidence_fails_closed(tmp_path):
    """submission_builder 若不用同一 terminal evidence → 验证失败，
    绝不 VERIFIED（evidence 绑定 fail-closed）。"""
    c = _contract(tmp_path, "wc_evb_0001")
    v = IndependentVerifier(c)
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    eid = led.submit_intent(c, "att_evb_0001")
    led.bind_run(eid, "run_evb_0001", "native_agent", expected_version=1)
    led.close()
    backend = _FakeBackend(events=[BackendEvent(
        backend_id="native_agent", run_id="run_evb_0001",
        event_type="backend.completed", payload={"exit": 0})])
    led2 = WorkLedger(tmp_path / "work_ledger.db")
    coord = RecoveryCoordinator(
        led2, backend_registry=_registry_with(backend), verifier=v,
        submission_builder=lambda rec, ev: _ok_submission(c, rec.run_id))
    result = coord.recover_execution(eid)
    assert result.status == "verification_failed"
    assert led2.get_execution(eid).state is not WorkExecutionState.VERIFIED
    led2.close()


def test_recovery_verified_with_evidence_bound_builder(tmp_path):
    c = _contract(tmp_path, "wc_evb_0002")
    v = IndependentVerifier(c)
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    eid = led.submit_intent(c, "att_evb_0002")
    led.bind_run(eid, "run_evb_0002", "native_agent", expected_version=1)
    led.close()
    backend = _FakeBackend(events=[BackendEvent(
        backend_id="native_agent", run_id="run_evb_0002",
        event_type="backend.completed", payload={"exit": 0})])
    led2 = WorkLedger(tmp_path / "work_ledger.db")
    coord = RecoveryCoordinator(
        led2, backend_registry=_registry_with(backend), verifier=v,
        submission_builder=_evidence_bound_builder(c))
    result = coord.recover_execution(eid)
    assert result.status == "verified"
    assert backend.submit_calls == 0
    rec = led2.get_execution(eid)
    assert rec.state is WorkExecutionState.VERIFIED
    at = led2.attempts_of(eid)[0]
    assert rec.state_version == at["state_version"]
    led2.close()


def test_cancellation_no_stop_without_backend(tmp_path):
    """registry 无 backend → dispatch False、零 stop 调用、保持 CANCELLING。"""
    c = _contract(tmp_path, "wc_nsb_0001")
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    backend = _FakeBackend(events=[], supports_stop=True)
    coord = CancellationCoordinator(
        led, backend_registry=ExecutionBackendRegistry())
    eid = led.submit_intent(c, "att_nsb_0001")
    led.bind_run(eid, "run_nsb_0001", "native_agent", expected_version=1)
    result = coord.cancel(eid)
    assert result.stop_dispatched is False
    assert backend.stop_calls == 0
    assert led.get_execution(eid).state is WorkExecutionState.CANCELLING
    led.close()
