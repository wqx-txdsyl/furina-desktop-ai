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
        eid, {"event_id": "e1", "kind": "backend.completed",
              "run_id": "run_lck_0001", "backend_id": "native_agent",
              "contract_id": c.contract_id, "payload": {}},
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
    """真实 backend 证明 + CANCELLING/cancel_intent 前置：任一缺失 → False
    零副作用（stop claim 绝不提前消耗）。"""
    c = _contract(tmp_path, "wc_stp_0001")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_stp_0001")
    v = ledger.bind_run(eid, "run_stp_0001", "native_agent", expected_version=1)
    ok = _FakeBackend(supports_stop=True)
    # 非 CANCELLING（STARTING、无 cancel intent）→ False
    assert ledger.dispatch_stop_once(eid, backend=ok,
                                     expected_version=v) is False
    assert ledger.get_execution(eid).stop_dispatched is False
    vc = ledger.cancel_intent(eid, expected_version=v)   # → CANCELLING
    assert ledger.dispatch_stop_once(eid, backend=None,
                                     expected_version=vc) is False
    no_stop = _FakeBackend(supports_stop=False)
    assert ledger.dispatch_stop_once(eid, backend=no_stop,
                                     expected_version=vc) is False
    wrong_id = _FakeBackend(backend_id="other_backend", supports_stop=True)
    assert ledger.dispatch_stop_once(eid, backend=wrong_id,
                                     expected_version=vc) is False
    assert ledger.dispatch_stop_once(eid, backend=ok,
                                     expected_version=vc) is True
    assert ledger.dispatch_stop_once(eid, backend=ok,
                                     expected_version=vc) is False   # 幂等
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
    """真实 v2 schema（无 legacy_unrecoverable / work_attempts）→ v3。
    Python 参数绑定写入真实 64-hex（绝不 SQL 内 '*64' 文本算术）；迁移前后
    与二次 reopen 对 contract/execution/attempt 全关键字段逐值断言。"""
    db = tmp_path / "wl2.db"
    contract_hash = "b" * 64
    ev_id = "lev_1756000002000_00abcd"
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
    """)
    conn.execute(
        "INSERT INTO work_contracts(contract_id,contract_hash,"
        "transport_json,registered_at) VALUES(?,?,?,?)",
        ("wc_v2_0001", contract_hash, '{"v":2}', 2000.0))
    conn.execute(
        "INSERT INTO work_executions(contract_id,contract_hash,attempt_id,"
        "run_id,backend_id,state,state_version,is_active,created_at,"
        "updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("wc_v2_0001", contract_hash, "att_v2_0001", "run_v2_0001",
         "native_agent", "RUNNING", 2, 1, 2000.0, 2001.0))
    conn.execute(
        "INSERT INTO work_events(execution_id,event_id,kind,payload_json,"
        "critical,received_at) VALUES(?,?,?,?,?,?)",
        (1, ev_id, "backend.completed", '{"exit":0}', 1, 2001.0))
    conn.commit()
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    # 迁移前快照
    pre = {
        "contract": conn.execute(
            "SELECT contract_id, contract_hash, transport_json "
            "FROM work_contracts").fetchone(),
        "execution": conn.execute(
            "SELECT contract_id, contract_hash, attempt_id, run_id, "
            "backend_id, state, state_version, is_active, created_at, "
            "updated_at FROM work_executions").fetchone(),
        "event": conn.execute(
            "SELECT execution_id, event_id, kind, payload_json, critical, "
            "received_at FROM work_events").fetchone(),
    }
    conn.close()
    assert len(pre["contract"][1]) == 64
    led = WorkLedger(db)
    assert led.user_version() == 3
    # contract 逐值
    row = led._conn.execute(
        "SELECT contract_id, contract_hash, transport_json, "
        "legacy_unrecoverable FROM work_contracts").fetchone()
    assert row["contract_id"] == pre["contract"][0]
    assert row["contract_hash"] == contract_hash
    assert row["transport_json"] == pre["contract"][2]
    assert int(row["legacy_unrecoverable"]) == 0   # v2 有 transport → 可恢复
    # execution 逐值
    rec = led.get_execution(1)
    e = pre["execution"]
    assert (rec.contract_id, rec.contract_hash, rec.attempt_id, rec.run_id,
            rec.backend_id) == (e[0], e[1], e[2], e[3], e[4])
    assert rec.state.value == e[5]
    assert rec.state_version == e[6] and rec.is_active == bool(e[7])
    assert rec.created_at == e[8] and rec.updated_at == e[9]
    # attempt backfill 逐值
    ats = led.attempts_of(1)
    assert len(ats) == 1
    assert (ats[0]["attempt_id"], ats[0]["run_id"], ats[0]["backend_id"],
            ats[0]["state"], ats[0]["state_version"]) == (
        "att_v2_0001", "run_v2_0001", "native_agent", "RUNNING", 2)
    # event 逐值
    evs = led.events_of(1)
    assert len(evs) == 1
    assert (evs[0]["event_id"], evs[0]["kind"], evs[0]["payload"],
            evs[0]["critical"], evs[0]["received_at"]) == (
        ev_id, "backend.completed", {"exit": 0}, True, 2001.0)
    led.close()
    # 二次 reopen 幂等 + 数据仍逐值一致
    led2 = WorkLedger(db)
    assert led2.user_version() == 3
    rec2 = led2.get_execution(1)
    assert (rec2.contract_id, rec2.contract_hash, rec2.attempt_id,
            rec2.run_id, rec2.state.value, rec2.state_version) == (
        e[0], e[1], e[2], e[3], e[5], e[6])
    assert len(led2.attempts_of(1)) == 1
    assert len(led2.events_of(1)) == 1
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
    # 存在但未 peek 的 key → ack 类型化拒绝（peek 注册表追踪）
    with pytest.raises(WorkLedgerError):
        buf.ack([("run_p", "p_2")])
    assert buf.peek() != ()          # 拒绝路径零副作用
    assert buf.ack([("run_p", "p_2")]) == 1   # peek 后可 ack


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


def test_dispatch_stop_rejects_wrong_backend_identity(ledger, tmp_path):
    """Reviewer 否证：鸭子对象/错误 backend_id 不得置 stop_dispatched。"""
    c = _contract(tmp_path, "wc_stp_0002")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_stp_0002")
    v = ledger.bind_run(eid, "run_stp_0002", "native_agent", expected_version=1)
    vc = ledger.cancel_intent(eid, expected_version=v)   # → CANCELLING
    class _Duck:
        capabilities = type("C", (), {"supports_stop": True})()
    assert ledger.dispatch_stop_once(eid, backend=_Duck(),
                                     expected_version=vc) is False
    wrong_id = _FakeBackend(backend_id="other_backend", supports_stop=True)
    assert ledger.dispatch_stop_once(eid, backend=wrong_id,
                                     expected_version=vc) is False
    assert ledger.get_execution(eid).stop_dispatched is False


def test_verified_rejects_evidence_identity_mismatch(ledger, tmp_path):
    """Reviewer 否证闭环：① 身份错误的 evidence 在写入即拒（exact 六键 +
    冻结身份）；② 写入正确 evidence 后传不同 evidence 验证 → canonical
    不等拒绝。两条路径都不得 VERIFIED。"""
    c = _contract(tmp_path, "wc_eid_0001")
    v = IndependentVerifier(c)
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_eid_0001")
    v1 = ledger.bind_run(eid, "run_eid_0001", "native_agent", expected_version=1)
    # ① 身份全错的 evidence（run/backend/contract 与冻结绑定不一致）写入即拒
    bad_ev = {"event_id": "lev_1756000000001_0000ff",
              "kind": "backend.completed", "run_id": "run_attacker_9999",
              "backend_id": "attacker_backend",
              "contract_id": "wc_attacker_9999", "payload": {"exit": 0}}
    with pytest.raises(WorkLedgerError):
        ledger.mark_terminal_evidence(eid, bad_ev, expected_version=v1)
    # ② 正确 evidence 写入后，验证时传完全不同的 evidence → 拒绝
    good_ev = {"event_id": "lev_1756000000001_0000ff",
               "kind": "backend.completed", "run_id": "run_eid_0001",
               "backend_id": "native_agent", "contract_id": c.contract_id,
               "payload": {"exit": 0}}
    v1 = ledger.mark_terminal_evidence(eid, good_ev, expected_version=v1)
    v1 = ledger.transition(eid, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                           expected_version=v1)
    rep, outcome = _verified_outcome_for(c, v, "run_eid_0001")
    divergent = dict(good_ev)
    divergent["payload"] = {"exit": 0, "forged": True}
    with pytest.raises(WorkLedgerError):
        ledger.mark_verified_by_outcome(eid, v, outcome,
                                        expected_version=v1,
                                        terminal_evidence=divergent)
    assert ledger.get_execution(eid).state is         WorkExecutionState.BACKEND_DONE_UNVERIFIED


def _verified_outcome_for(c, v, run_id):
    from furina.agent.verification.repair import (
        AttemptRecord,
        RepairOutcome,
        RepairStopReason,
    )
    rep = v.verify(_ok_submission(c, run_id))
    attempt = AttemptRecord(attempt_id="att_out_eid", run_id=rep.run_id,
                            contract_hash=rep.contract_hash,
                            verdict="VERIFIED", report_id=rep.report_id,
                            failure_signature="", started_at_epoch=1.0,
                            finished_at_epoch=2.0)
    outcome = RepairOutcome(stop_reason=RepairStopReason.VERIFIED,
                            contract_id=rep.contract_id,
                            contract_hash=rep.contract_hash,
                            attempts=(attempt,), final_report=rep,
                            started_at_epoch=1.0, finished_at_epoch=2.0)
    return rep, outcome


def test_buffer_drain_removed_public_api():
    """Patch 6：公开破坏性 drain() 已移除——消费只能走 peek→persist→ack。"""
    buf = WorkEventBuffer()
    assert not hasattr(buf, "drain")
    buf.offer("run_d", "d_0001", EventKind.TOOL_PROGRESS, {"i": 1})
    snap = buf.peek()
    assert len(snap) == 1          # peek 不清空
    assert buf.ack([("run_d", "d_0001")]) == 1


def test_buffer_raw_utf8_real_byte_accounting():
    """Patch 6：raw 预检按 ensure_ascii=False 真实 UTF-8 字节计数——
    多字节字符不再被转义计数错杀（真实 ≤ 上限 → 接受）。"""
    buf = WorkEventBuffer()
    # 20000 个 '€'：真实 UTF-8 = 60000 字节 ≤ 65536（转义计数会是 12000+）
    payload = {"k": "€" * 20000}
    assert buf.offer("run_u", "u_0001", EventKind.TOOL_PROGRESS,
                     payload) is EventBufferOutcome.ACCEPTED
    # 真实超限仍然拒绝
    with pytest.raises(WorkLedgerError):
        buf.offer("run_u", "u_0002", EventKind.TOOL_PROGRESS,
                  {"k": "€" * 30000})


def test_terminal_evidence_exact_six_key_schema(ledger, tmp_path):
    """Patch 6：terminal evidence exact 六键 schema——缺键/多键/类型错
    一律拒绝。"""
    c = _contract(tmp_path, "wc_6k_0001")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_6k_0001")
    v = ledger.bind_run(eid, "run_6k_0001", "native_agent", expected_version=1)
    base = {"event_id": "ev_6k_0001", "kind": "backend.completed",
            "run_id": "run_6k_0001", "backend_id": "native_agent",
            "contract_id": c.contract_id, "payload": {"exit": 0}}
    missing = {k: val for k, val in base.items() if k != "payload"}
    with pytest.raises(WorkLedgerError):
        ledger.mark_terminal_evidence(eid, missing, expected_version=v)
    extra = dict(base)
    extra["junk"] = 1
    with pytest.raises(WorkLedgerError):
        ledger.mark_terminal_evidence(eid, extra, expected_version=v)
    wrong_type = dict(base)
    wrong_type["run_id"] = 123
    with pytest.raises(WorkLedgerError):
        ledger.mark_terminal_evidence(eid, wrong_type, expected_version=v)
    unbound_run = dict(base)
    unbound_run["event_id"] = "ev_6k_0002"
    unbound_run["run_id"] = "run_not_bound"
    with pytest.raises(WorkLedgerError):
        ledger.mark_terminal_evidence(eid, unbound_run, expected_version=v)
    # 正确六键接受
    assert ledger.mark_terminal_evidence(eid, base,
                                         expected_version=v) == v + 1
