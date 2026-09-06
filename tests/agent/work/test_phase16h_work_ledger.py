# -*- coding: utf-8 -*-
"""Phase 16H v2 — Durable Work Ledger / Recovery / Cancellation / Backpressure
测试（任务书 PART 7 + Reviewer Patch 1 二十项 reviewer-locked）。"""
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
    CriticalBufferOverflow,
    DuplicateActiveExecution,
    EventBufferOutcome,
    EventContentConflict,
    IllegalTransition,
    RunBindingConflict,
    StaleStateVersion,
    WorkEventBuffer,
    WorkLedger,
    WorkLedgerError,
)
from furina.agent.verification import (
    IndependentVerifier,
    VerificationReport,
    VerificationVerdict,
)
from furina.agent.verification.repair import (
    AttemptRecord,
    RepairOutcome,
    RepairStopReason,
)
from furina.cognition.stores.base import CognitionDB

HASH_A = "a" * 64


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
    """最小 fake backend：events 面回放记录事件；submit 计数（必须恒 0）。"""

    def __init__(self, backend_id="native_agent", *, events=None,
                 supports_stop=True, stop_error=False):
        self._descriptor = BackendDescriptor(backend_id=backend_id,
                                             display_name="fake backend")
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
        raise AssertionError("recovery/cancellation 绝不重新 submit")

    def events(self, run_handle):
        return list(self._events)

    def stop(self, run_handle):
        self.stop_calls += 1
        if self.stop_error:
            raise RuntimeError("stop network uncertain")


def _verified_outcome(c, v, run_id):
    rep = v.verify(_ok_submission(c, run_id))
    attempt = AttemptRecord(attempt_id="att_out_0001", run_id=rep.run_id,
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


def _registry_with(backend):
    reg = ExecutionBackendRegistry()
    reg.register(backend)
    return reg


# ================================================================
# B1 — VERIFIED 权威唯一入口 / truth-commit 绑定
# ================================================================

def test_b1_direct_transition_verified_and_tool_running_rejected(tmp_path):
    """锁定 1：generic transition 不得写 VERIFIED/TOOL_RUNNING primary。"""
    c = _contract(tmp_path, "wc_b1_0001")
    ledger = WorkLedger(tmp_path / "work_ledger.db")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_b1_0001")
    v = ledger.bind_run(eid, "run_b1_0001", "native_agent", expected_version=1)
    with pytest.raises(IllegalTransition):
        ledger.transition(eid, WorkExecutionState.VERIFIED,
                          expected_version=v)
    with pytest.raises(IllegalTransition):
        ledger.transition(eid, WorkExecutionState.TOOL_RUNNING,
                          expected_version=v)
    assert ledger.get_execution(eid).state is WorkExecutionState.STARTING
    ledger.close()


def test_b1_fake_verifier_and_shadow_rejected(tmp_path):
    """锁定 2/3：fake verifier.outcome_is_authentic=True / 实例 shadow /
    子类 / 跨契约 outcome → 全部拒绝、零状态修改；真实 outcome → VERIFIED。"""
    c = _contract(tmp_path, "wc_b1_fake_0001")
    v = IndependentVerifier(c)
    ledger = WorkLedger(tmp_path / "work_ledger.db")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_b1f_0001")
    v1 = ledger.bind_run(eid, "run_b1f_0001", "native_agent", expected_version=1)
    v1 = ledger.transition(eid, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                           expected_version=v1)

    class ForgingVerifier(IndependentVerifier):
        def verify(self, evidence):
            raise AssertionError("forged verify must not run")

        def outcome_is_authentic(self, outcome):
            return True

    rep, outcome = _verified_outcome(c, v, "run_b1f_0001")
    with pytest.raises(WorkLedgerError):
        ledger.mark_verified_by_outcome(eid, ForgingVerifier(c), outcome,
                                        expected_version=v1)
    # 实例 shadow：seal_is_authentic 注入后，普通实例调用通过、类入口拒绝
    v_shadow = IndependentVerifier(c)
    v_shadow.seal_is_authentic = lambda report: True
    forged = VerificationReport(
        report_id=rep.report_id, verifier_id=rep.verifier_id,
        contract_id=rep.contract_id, contract_hash=rep.contract_hash,
        standard_hash=rep.standard_hash, run_id=rep.run_id,
        backend_id=rep.backend_id, verdict=VerificationVerdict.VERIFIED,
        checks=rep.checks, diagnostics=rep.diagnostics, evidence=rep.evidence,
        started_at_epoch=rep.started_at_epoch,
        finished_at_epoch=rep.finished_at_epoch,
        authority_seal="b" * 64)
    attempt = AttemptRecord(attempt_id="att_b1f_0009", run_id=rep.run_id,
                            contract_hash=rep.contract_hash,
                            verdict="VERIFIED", report_id=rep.report_id,
                            failure_signature="", started_at_epoch=1.0,
                            finished_at_epoch=2.0)
    forged_outcome = RepairOutcome(
        stop_reason=RepairStopReason.VERIFIED,
        contract_id=rep.contract_id, contract_hash=rep.contract_hash,
        attempts=(attempt,), final_report=forged,
        started_at_epoch=1.0, finished_at_epoch=2.0)
    # P12 封闭保持：实例 shadow 无法绕过类拥有的 outcome_is_authentic——
    # 普通/类入口调用对伪造 seal outcome 一律拒绝
    assert v_shadow.outcome_is_authentic(forged_outcome) is False
    assert IndependentVerifier.outcome_is_authentic(
        v_shadow, forged_outcome) is False
    with pytest.raises(WorkLedgerError):
        ledger.mark_verified_by_outcome(eid, v_shadow, forged_outcome,
                                        expected_version=v1)
    # 跨契约 outcome → 拒绝
    c_other = _contract(tmp_path, "wc_b1_other_0001")
    v_other = IndependentVerifier(c_other)
    rep_other, outcome_other = _verified_outcome(c_other, v_other,
                                                 "run_b1f_other_0001")
    with pytest.raises(WorkLedgerError):
        ledger.mark_verified_by_outcome(eid, IndependentVerifier(c_other),
                                        outcome_other, expected_version=v1)
    # 正例：真实 outcome → VERIFIED + marker（零弱化）
    v1 = ledger.mark_verified_by_outcome(eid, v, outcome,
                                         expected_version=v1)
    rec = ledger.get_execution(eid)
    assert rec.state is WorkExecutionState.VERIFIED
    assert rec.verification_marker == rep.report_digest
    assert rec.verification_verified is True
    ledger.close()


def test_b1_truth_commit_requires_authentic_verified(tmp_path):
    """锁定 4：STARTING/UNKNOWN/FAILED truth claim → 拒绝；真实 VERIFIED →
    claim 成功并绑定 report_digest。"""
    c = _contract(tmp_path, "wc_b1_tc_0001")
    v = IndependentVerifier(c)
    ledger = WorkLedger(tmp_path / "work_ledger.db")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_tc_0001")
    with pytest.raises(CommitClaimConflict):
        ledger.claim_truth_commit(eid, "owner-x")        # STARTING 不得 claim
    v1 = ledger.bind_run(eid, "run_tc_0001", "native_agent", expected_version=1)
    v1 = ledger.begin_reconciliation(eid, expected_version=v1)
    with pytest.raises(CommitClaimConflict):
        ledger.claim_truth_commit(eid, "owner-x")        # UNKNOWN 不得 claim
    rep, outcome = _verified_outcome(c, v, "run_tc_0001")
    v1 = ledger.mark_verified_by_outcome(eid, v, outcome,
                                         expected_version=v1)
    ok, digest = ledger.claim_truth_commit(eid, "owner-real")
    assert ok is True and digest == rep.report_digest
    assert ledger.claim_truth_commit(eid, "owner-2") == (False, digest)
    assert ledger.resolve_truth_commit(eid, "owner-2") is False
    assert ledger.resolve_truth_commit(eid, "owner-real") is True
    ledger.close()


# ================================================================
# B2 — 跨连接真 CAS / write-once 绑定
# ================================================================

def test_b2_cross_connection_cas_exactly_one_wins(tmp_path):
    """锁定 5：两个独立 WorkLedger 连接同 version 并发更新 → 恰一成功、
    恰一 stale（绝不能双方返回成功）。"""
    c = _contract(tmp_path, "wc_b2_cas_0001")
    led_a = WorkLedger(tmp_path / "work_ledger.db")
    led_a.register_contract(c)
    eid = led_a.submit_intent(c, "att_b2_0001")
    v = led_a.bind_run(eid, "run_init_0001", "native_agent", expected_version=1)
    led_b = WorkLedger(tmp_path / "work_ledger.db")       # 第二独立连接
    ok_a = ok_b = None
    try:
        ok_a = led_a.transition(eid, WorkExecutionState.RUNNING,
                                expected_version=v)
    except StaleStateVersion:
        ok_a = None
    try:
        ok_b = led_b.transition(eid, WorkExecutionState.WAITING_PERMISSION,
                                expected_version=v)
    except StaleStateVersion:
        ok_b = None
    results = [r for r in (ok_a, ok_b) if r is not None]
    assert len(results) == 1                              # 恰一成功、恰一 stale
    final = led_a.get_execution(eid)
    assert final.state in (WorkExecutionState.RUNNING,
                           WorkExecutionState.WAITING_PERMISSION)
    assert final.state_version == v + 1
    with pytest.raises(StaleStateVersion):
        led_a.transition(eid, WorkExecutionState.FAILED,
                         expected_version=v)              # 双方旧 version 均已失效
    led_a.close()
    led_b.close()


def test_b2_cross_connection_concurrent_submit_typed(tmp_path):
    """锁定 6：两连接并发 submit 同 contract → 恰一 active、异常类型封闭。"""
    c = _contract(tmp_path, "wc_b2_sub_0001")
    led_a = WorkLedger(tmp_path / "work_ledger.db")
    led_b = WorkLedger(tmp_path / "work_ledger.db")
    outcomes = []
    for led in (led_a, led_b):
        try:
            eid = led.submit_intent(c, "att_b2s_0001", {"g": 1})
            outcomes.append(("ok", eid))
        except DuplicateActiveExecution as exc:
            outcomes.append(("dup", exc))
    states = [o[0] for o in outcomes]
    assert sorted(states) == ["dup", "ok"]
    assert len(led_a.load_non_terminal()) == 1
    led_a.close()
    led_b.close()


def test_b2_run_binding_write_once(ledger, tmp_path):
    """锁定 7：不同 run/backend 二次 bind 拒绝；相同绑定幂等。"""
    c = _contract(tmp_path, "wc_b2_wo_0001")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_wo_0001")
    v = ledger.bind_run(eid, "run_wo_0001", "native_agent", expected_version=1)
    v2 = ledger.bind_run(eid, "run_wo_0001", "native_agent",
                         expected_version=v)               # 幂等重放
    assert v2 == v
    with pytest.raises(RunBindingConflict):
        ledger.bind_run(eid, "run_wo_9999", "native_agent",
                        expected_version=v)                # 不同 run 拒绝
    with pytest.raises(RunBindingConflict):
        ledger.bind_run(eid, "run_wo_0001", "other_backend",
                        expected_version=v)                # 不同 backend 拒绝


# ================================================================
# B3 — durable contract / attempt ledger / event 隔离 / migration
# ================================================================

def test_b3_durable_contract_reload_fail_closed(tmp_path):
    """B3-1/2：完整 transport JSON 持久化；损坏 → fail-closed。"""
    c = _contract(tmp_path, "wc_b3_c_0001")
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    led.close()
    conn = sqlite3.connect(tmp_path / "work_ledger.db")
    conn.execute("UPDATE work_contracts SET transport_json='{\"broken\": 1}'")
    conn.commit()
    conn.close()
    led2 = WorkLedger(tmp_path / "work_ledger.db")
    with pytest.raises(WorkLedgerError):
        led2.load_contract("wc_b3_c_0001")
    led2.close()


def test_b3_attempt_ledger_write_once_and_event_scope(ledger, tmp_path):
    """B3-4/5：attempt ledger write-once；event 身份按 execution 隔离。"""
    c1 = _contract(tmp_path, "wc_b3_al_0001")
    c2 = _contract(tmp_path, "wc_b3_al_0002")
    ledger.register_contract(c1)
    ledger.register_contract(c2)
    e1 = ledger.submit_intent(c1, "att_al_0001")
    e2 = ledger.submit_intent(c2, "att_al_0002")
    ledger.bind_run(e1, "run_al_0001", "native_agent", expected_version=1)
    assert ledger.record_event(e1, "shared_event", EventKind.RUN_STARTED,
                               {"i": 1}) == "stored"
    assert ledger.record_event(e1, "shared_event", EventKind.RUN_STARTED,
                               {"i": 1}) == "duplicate"
    assert ledger.record_event(e2, "shared_event", EventKind.RUN_STARTED,
                               {"i": 2}) == "stored"       # 不同 execution 各自保留
    ids1 = {e["event_id"] for e in ledger.events_of(e1)}
    ids2 = {e["event_id"] for e in ledger.events_of(e2)}
    assert "shared_event" in ids1 and "shared_event" in ids2
    with pytest.raises(EventContentConflict):
        ledger.record_event(e1, "shared_event", EventKind.RUN_STARTED,
                            {"i": 99})
    attempts = ledger.attempts_of(e1)
    assert attempts[0]["attempt_id"] == "att_al_0001"
    assert attempts[0]["run_id"] == "run_al_0001"


def test_b3_migration_future_version_and_incompatible_rejected(tmp_path):
    """B3-6：future schema / 不兼容同名表 / 正常 reopen 幂等——全部 fail-closed。"""
    c = _contract(tmp_path, "wc_b3_mig_0001")
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
    conn.execute("PRAGMA user_version = 1")
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
    assert led2.user_version() == 2
    led2.close()


def test_b3_config_caps_safe_maximum(tmp_path):
    """B3-7：配置上限有安全最大值——超大值构造期拒绝。"""
    with pytest.raises(WorkLedgerError):
        WorkLedger(tmp_path / "x1.db", max_events_per_run=10**12)
    with pytest.raises(WorkLedgerError):
        WorkLedger(tmp_path / "x2.db", max_payload_bytes=10**12)


# ================================================================
# B4 — 真实 Recovery Coordinator
# ================================================================

def test_b4_recovery_via_coordinator_with_fake_backend(tmp_path):
    """锁定 9/10：restart 后经生产 recovery coordinator 重建——fake backend
    submit_calls==0、events 被调用；terminal evidence → 16F 验证 → VERIFIED。"""
    c = _contract(tmp_path, "wc_b4_0001")
    v = IndependentVerifier(c)
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    eid = led.submit_intent(c, "att_b4_0001")
    led.bind_run(eid, "run_b4_0001", "native_agent", expected_version=1)
    led.close()
    backend = _FakeBackend(events=[BackendEvent(
        backend_id="native_agent", run_id="run_b4_0001",
        event_type="backend.completed", payload={"exit": 0})])
    led2 = WorkLedger(tmp_path / "work_ledger.db")
    coord = RecoveryCoordinator(
        led2, backend_registry=_registry_with(backend), verifier=v,
        submission_builder=lambda rec, ev: _ok_submission(c, rec.run_id))
    result = coord.recover_execution(eid)
    assert result.status == "verified"
    assert result.submit_calls == 0 and backend.submit_calls == 0
    rec = led2.get_execution(eid)
    assert rec.state is WorkExecutionState.VERIFIED
    assert rec.verification_verified is True
    led2.close()


def test_b4_recovery_unknown_paths_zero_submit(tmp_path):
    """锁定 10：无 backend / 无 terminal evidence → typed UNKNOWN、
    submit_calls==0、二次 submit 仍被阻止。"""
    c = _contract(tmp_path, "wc_b4_u_0001")
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    eid = led.submit_intent(c, "att_b4u_0001")
    led.bind_run(eid, "run_b4u_0001", "native_agent", expected_version=1)
    led.close()
    led2 = WorkLedger(tmp_path / "work_ledger.db")
    coord = RecoveryCoordinator(led2)                     # 无 registry
    result = coord.recover_execution(eid)
    assert result.status == "unknown_no_backend"
    assert result.submit_calls == 0
    assert led2.get_execution(eid).state is WorkExecutionState.UNKNOWN
    with pytest.raises(DuplicateActiveExecution):
        led2.submit_intent(c, "att_b4u_0002")             # 零重复 run
    backend = _FakeBackend(events=[])
    coord2 = RecoveryCoordinator(led2, backend_registry=_registry_with(backend))
    result2 = coord2.recover_execution(eid)
    assert result2.status == "unknown_no_events"
    assert backend.submit_calls == 0
    led2.close()


# ================================================================
# B5 — 真实 cancellation 链路
# ================================================================

def test_b5_cancellation_real_broker_and_backend_path(tmp_path):
    """锁定 11/12：approval wait cancel 调用真实注入 broker.cancel；stop
    派发恰一次；stop 异常/不确定 → UNKNOWN/reconcile 且不重发；迟到 approve
    不恢复。"""
    c = _contract(tmp_path, "wc_b5_0001")
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c)
    backend = _FakeBackend(events=[], supports_stop=True)
    registry = _registry_with(backend)
    cancelled_ids = []
    coord = CancellationCoordinator(
        led, backend_registry=registry,
        approval_canceller=lambda aid: cancelled_ids.append(aid))
    eid = led.submit_intent(c, "att_b5_0001")
    v = led.bind_run(eid, "run_b5_0001", "native_agent", expected_version=1)
    v = led.transition(eid, WorkExecutionState.WAITING_PERMISSION,
                       expected_version=v)
    v = led.record_outstanding_approval(eid, "apv_b5_0001", expected_version=v)
    outcome = coord.cancel(eid)
    assert cancelled_ids == ["apv_b5_0001"]               # 真实 broker 通道被调
    assert outcome.approval_cancelled is True
    assert outcome.stop_dispatched is True and backend.stop_calls == 1
    assert led.approval_invalidated(eid) is True
    with pytest.raises(WorkLedgerError):
        rec = led.get_execution(eid)
        led.transition(eid, WorkExecutionState.RUNNING,
                       expected_version=rec.state_version)   # 迟到 approve 不恢复
    outcome2 = coord.cancel(eid)                          # 重复 cancel 幂等
    assert backend.stop_calls == 1 and outcome2.stop_dispatched is False
    # stop 异常/不确定 → UNKNOWN/reconcile 且绝不重发
    c2 = _contract(tmp_path, "wc_b5_x_0001")
    led.register_contract(c2)
    eid2 = led.submit_intent(c2, "att_b5_0002")
    led.bind_run(eid2, "run_b5_0002", "native_agent", expected_version=1)
    bad_backend = _FakeBackend(events=[], supports_stop=True, stop_error=True)
    coord2 = CancellationCoordinator(
        led, backend_registry=_registry_with(bad_backend),
        approval_canceller=None)
    outcome3 = coord2.cancel(eid2)
    assert outcome3.status == "stop_uncertain_reconcile"
    assert bad_backend.stop_calls == 1                    # 恰一次，不重发
    assert led.get_execution(eid2).state is WorkExecutionState.UNKNOWN
    led.close()


def test_b5_pre_submit_cancel_zero_submit_zero_run_zero_stop(tmp_path):
    """锁定（B5-6）：pre-submit cancel 零 submit、零 backend run、零 stop。"""
    c = _contract(tmp_path, "wc_b5_pre_0001")
    led = WorkLedger(tmp_path / "work_ledger.db")
    backend = _FakeBackend(events=[], supports_stop=True)
    coord = CancellationCoordinator(
        led, backend_registry=_registry_with(backend))
    led.register_contract(c)
    eid = led.submit_intent(c, "att_b5pre_0001")
    outcome = coord.cancel(eid)
    assert outcome.status == "cancelled_pre_submit"
    assert outcome.stop_dispatched is False and backend.stop_calls == 0
    assert backend.submit_calls == 0
    assert led.get_execution(eid).state is WorkExecutionState.CANCELLED
    led.close()


# ================================================================
# B6 — 真 per-run/global backpressure / payload 有界 / counter 词表
# ================================================================

def test_b6_per_run_caps_independent_and_payload_bounds():
    """锁定 13/14：两个 run 各自 per-run cap 互不干扰；payload canonical
    深拷贝（修改原对象/snapshot 不影响内部）；超大 payload 拒绝。"""
    buf = WorkEventBuffer(per_run_cap=3, global_cap=64)
    for i in range(3):
        assert buf.offer("run_a", f"a_{i}", EventKind.TOOL_PROGRESS,
                         {"i": i}) is EventBufferOutcome.ACCEPTED
    assert buf.offer("run_a", "a_overflow", EventKind.TOOL_PROGRESS,
                     {"over": True}) is EventBufferOutcome.DROPPED_TICK
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
    snap[0]["payload"] = {"tampered": True}
    snap2 = buf.snapshot()
    assert snap2[0]["payload"] != {"tampered": True}


def test_b6_critical_overflow_durable_marker(tmp_path):
    """锁定 15：progress 占满后 terminal critical 仍被保留；critical overflow
    有 durable execution-bound marker（不是只加计数）。"""
    led = WorkLedger(tmp_path / "work_ledger.db", max_events_per_run=5)
    c = _contract(tmp_path, "wc_b6_0001")
    led.register_contract(c)
    eid = led.submit_intent(c, "att_b6_0001")
    for i in range(4):
        assert led.record_event(eid, f"prog_{i}", EventKind.TOOL_PROGRESS,
                                {"i": i}) in ("stored", "dropped")
    assert led.record_event(eid, "term_0001", EventKind.BACKEND_COMPLETED,
                            {"exit": 0}) == "stored"      # terminal critical 保留
    with pytest.raises(CriticalBufferOverflow):
        led.record_event(eid, "term_0002", EventKind.BACKEND_FAILED,
                         {"exit": 1})
    rec = led.get_execution(eid)
    assert rec.overflow_marker.startswith("critical_overflow:")
    assert led.counter("critical_overflow") == 1
    led.close()


def test_b6_counter_names_closed_vocabulary(ledger):
    """锁定 16：任意 counter name 攻击不能增长 DB rows（封闭词表）。"""
    for i in range(200):
        with pytest.raises(WorkLedgerError):
            ledger.incr_counter(f"attacker_name_{i:06d}")
    assert ledger.counter("critical_overflow") == 0
    conn = sqlite3.connect(ledger._path)
    rows = int(conn.execute(
        "SELECT COUNT(*) FROM work_counters").fetchone()[0])
    conn.close()
    assert rows == 0


# ================================================================
# 修正旧锁错语义 + 全表快照
# ================================================================

def test_c1c7_full_snapshot_unchanged(tmp_path):
    """锁定 19：C1–C7 用 Phase 15 真实 native API 全表 schema+rows 快照
    （不只 agent_tasks）。"""
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


def test_legacy_semantics_corrected(ledger, tmp_path):
    """修正初版锁错语义：无 direct VERIFIED 正例、无 STARTING truth-claim
    正例；基础 CAS/身份语义保持。"""
    c = _contract(tmp_path, "wc_leg_0001")
    ledger.register_contract(c)
    eid = ledger.submit_intent(c, "att_leg_0001")
    with pytest.raises(IllegalTransition):
        ledger.transition(eid, WorkExecutionState.VERIFIED,
                          expected_version=1)
    with pytest.raises(CommitClaimConflict):
        ledger.claim_truth_commit(eid, "owner")
    v = ledger.bind_run(eid, "run_leg_0001", "native_agent", expected_version=1)
    v = ledger.transition(eid, WorkExecutionState.RUNNING, expected_version=v)
    v = ledger.transition(eid, WorkExecutionState.FAILED, expected_version=v)
    assert ledger.get_execution(eid).state is WorkExecutionState.FAILED
    with pytest.raises(WorkLedgerError):
        ledger.transition(eid, WorkExecutionState.RUNNING,
                          expected_version=v)             # 终态吸收


def test_b100k_progress_flood_bounded(ledger):
    """10 万 progress flood：buffer/DB 行数保持硬上限（确定性丢弃+计数）。"""
    buf = WorkEventBuffer(per_run_cap=128, global_cap=512)
    for i in range(100000):
        buf.offer("run_flood", f"prog_{i:06d}", EventKind.TOOL_PROGRESS,
                  {"i": i})
    assert len(buf.snapshot()) <= 128
    assert buf.dropped_ticks == 100000 - 128
    import tempfile
    from pathlib import Path
    c_flood = _contract(Path(tempfile.mkdtemp()), "wc_flood_0001")
    ledger.register_contract(c_flood)
    eid = ledger.submit_intent(c_flood, "att_flood_0001")
    for i in range(500):
        outcome = ledger.record_event(eid, f"flood_{i:06d}",
                                      EventKind.TOOL_PROGRESS, {"i": i})
        assert outcome in ("stored", "dropped")
    assert len(ledger.events_of(eid)) <= 256              # per-run 硬上限
    assert ledger.counter("progress_dropped") >= 500 - 256
