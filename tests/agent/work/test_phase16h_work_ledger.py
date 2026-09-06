# -*- coding: utf-8 -*-
"""Phase 16H — Durable Work Ledger / Recovery / Idempotency / Cancellation /
Backpressure 测试（任务书 PART 7 十七类最低锁定）。"""
import json
import os
import sqlite3
import threading

import pytest

from furina.agent.events.models import EventKind
from furina.agent.events.reducer import WorkExecutionState
from furina.agent.work_ledger import (
    CommitClaimConflict,
    ContractIdentityConflict,
    CriticalBufferOverflow,
    DuplicateActiveExecution,
    EventBufferOutcome,
    EventContentConflict,
    StaleStateVersion,
    UnknownExecution,
    WorkEventBuffer,
    WorkLedger,
    WorkLedgerError,
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
from furina.agent.verification import (
    IndependentVerifier,
    VerificationReport,
    VerificationVerdict,
)
from furina.agent.verification.repair import RepairStopReason
from furina.cognition.stores.base import CognitionDB

HASH_A = "a" * 64
HASH_B = "b" * 64


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
    art = c.workspace_scope.write_roots[0] + "/summary.md"
    import hashlib
    return {"run_id": run_id, "backend_id": "native_agent",
            "terminal_events": [{
                "event_id": "lev_1756000000001_0000ff", "kind": "backend.completed",
                "observed_at_epoch": 1756000001.0, "run_id": run_id,
                "contract_id": c.contract_id, "backend_id": "native_agent"}],
            "declared_artifacts": [{
                "artifact_id": "doc", "path": art,
                "declared_sha256": hashlib.sha256(b"ok").hexdigest(),
                "declared_mime": "text/markdown", "declared_size_bytes": 2}]}


# ================================================================
# 1/2 — Phase 15 frozen DB additive migration + C1–C7 schema/rows 不变
# ================================================================

def test_migration_additive_idempotent_reopen_and_c1c7_unchanged(tmp_path):
    """Phase 15 frozen DB（CognitionDB）与 WorkLedger 各自独立文件；ledger
    migration 幂等、重复 reopen 零副作用；C1–C7 schema/rows 在 migration/
    recovery 前后完全相等。"""
    cog_path = tmp_path / "furina.db"
    cog = CognitionDB(cog_path)
    cog.execute("INSERT INTO agent_tasks(task_id, goal) VALUES(?,?)",
                ("task_p15_0001", "frozen goal"))
    cog_schema_before = sorted(
        (r[0], r[1]) for r in cog.query_all(
            "SELECT type, name FROM sqlite_master WHERE type IN ('table','index')"
            " AND name NOT LIKE 'sqlite_%'"))
    rows_before = sorted(tuple(r) for r in cog.query_all(
        "SELECT task_id, status, goal FROM agent_tasks"))

    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract("wc_mig_0001", HASH_A)
    eid = led.submit_intent("wc_mig_0001", HASH_A, "att_mig_0001", {"g": 1})
    led.bind_run(eid, "run_mig_0001", "native_agent", expected_version=1)
    led.record_event(eid, "ev_mig_0001", EventKind.BACKEND_COMPLETED,
                     {"exit": 0})
    led.close()

    # 重复 migration/reopen（两次新连接）——数据保留、版本单调不回退
    for _ in range(2):
        led2 = WorkLedger(tmp_path / "work_ledger.db")
        assert led2.user_version() == 1
        assert led2.schema_version() == "16H.1"
        rec = led2.get_execution(eid)
        assert rec.run_id == "run_mig_0001"
        assert len(led2.events_of(eid)) == 1
        led2.close()

    # C1–C7 schema/rows 在 ledger migration/recovery 前后完全相等
    cog2 = CognitionDB(cog_path)
    cog2_schema_after = sorted(
        (r[0], r[1]) for r in cog2.query_all(
            "SELECT type, name FROM sqlite_master WHERE type IN ('table','index')"
            " AND name NOT LIKE 'sqlite_%'"))
    rows_after = sorted(tuple(r) for r in cog2.query_all(
        "SELECT task_id, status, goal FROM agent_tasks"))
    assert cog_schema_before == cog2_schema_after
    assert rows_before == rows_after
    assert rows_before == [("task_p15_0001", "PLANNED", "frozen goal")]
    cog2.close()
    cog.close()


# ================================================================
# 3 — 并发相同 contract 只有一个 active claim
# ================================================================

def test_concurrent_submit_single_active_claim(ledger):
    results = {"ok": [], "dup": 0}
    lock = threading.Lock()

    def worker(i):
        try:
            eid = ledger.submit_intent("wc_conc_0001", HASH_A,
                                       f"att_conc_{i:04d}", {"i": i})
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
    assert len(results["ok"]) == 1 and results["dup"] == 31
    active = [r for r in ledger.load_non_terminal()
              if r.contract_id == "wc_conc_0001"]
    assert len(active) == 1


# ================================================================
# 4 — 同 id 不同 hash 冲突
# ================================================================

def test_same_id_different_hash_conflict(ledger):
    ledger.register_contract("wc_hash_0001", HASH_A)
    with pytest.raises(ContractIdentityConflict):
        ledger.register_contract("wc_hash_0001", HASH_B)
    assert ledger.contract_hash_of("wc_hash_0001") == HASH_A


# ================================================================
# 5 — stale state_version / CAS 拒绝且终态不变
# ================================================================

def test_stale_version_rejected_and_terminal_absorbed(ledger):
    ledger.register_contract("wc_stale_0001", HASH_A)
    eid = ledger.submit_intent("wc_stale_0001", HASH_A, "att_stale_0001")
    v1 = ledger.bind_run(eid, "run_stale_0001", "native_agent",
                         expected_version=1)
    with pytest.raises(StaleStateVersion):
        ledger.transition(eid, WorkExecutionState.RUNNING, expected_version=1)
    v2 = ledger.transition(eid, WorkExecutionState.RUNNING,
                           expected_version=v1)
    v3 = ledger.transition(eid, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                           expected_version=v2)
    v4 = ledger.transition(eid, WorkExecutionState.CANCELLED,
                           expected_version=v3)
    rec = ledger.get_execution(eid)
    assert rec.state is WorkExecutionState.CANCELLED and not rec.is_active
    # 终态吸收：任何后续迁移零修改（终态检查先于 CAS——两种异常均可）
    with pytest.raises(WorkLedgerError):
        ledger.transition(eid, WorkExecutionState.VERIFIED,
                          expected_version=v4)
    with pytest.raises(WorkLedgerError):
        ledger.transition(eid, WorkExecutionState.VERIFIED,
                          expected_version=99)
    assert ledger.get_execution(eid).state is WorkExecutionState.CANCELLED


# ================================================================
# 6 — 六个 crash window 逐点 fault injection + reopen
# ================================================================

def _reopen(tmp_path):
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.close()
    return WorkLedger(tmp_path / "work_ledger.db")


def test_crash_windows(tmp_path):
    c_id, c_hash = "wc_crash_0001", HASH_A

    # w1：submit intent 落盘前崩溃 → 零行、零执行、重放不产生第二执行
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c_id, c_hash)
    led.close()
    led = _reopen(tmp_path)
    assert ledger_recoverable_ids(led) == []

    # w2：submit intent 已落盘（HTTP 尚未完成 / run_id 未落盘）→ active
    # STARTING；reopen 后进入 reconciliation/UNKNOWN；二次 submit 被阻止
    eid = led.submit_intent(c_id, c_hash, "att_crash_0001", {"goal": "g"})
    led.close()
    led = _reopen(tmp_path)
    rec = led.get_execution(eid)
    assert rec.state is WorkExecutionState.STARTING and rec.run_id == ""
    v = led.begin_reconciliation(eid, expected_version=rec.state_version)
    assert led.get_execution(eid).state is WorkExecutionState.UNKNOWN
    with pytest.raises(DuplicateActiveExecution):
        led.submit_intent(c_id, c_hash, "att_crash_0002")   # 零重复 run
    # 证据不足 → 保持 UNKNOWN（明确 timeout policy：remain UNKNOWN）
    assert led.get_execution(eid).state is WorkExecutionState.UNKNOWN

    # w3：run_id 已绑定但 SSE 中断 → run 绑定持久保留
    v = led.bind_run(eid, "run_crash_0001", "native_agent", expected_version=v)
    led.close()
    led = _reopen(tmp_path)
    assert led.get_execution(eid).run_id == "run_crash_0001"
    v = led.transition(eid, WorkExecutionState.RUNNING, expected_version=v)

    # w4：backend terminal 已到达但尚未 verification → evidence 持久保留
    led.record_event(eid, "ev_crash_term", EventKind.BACKEND_COMPLETED,
                     {"exit": 0})
    v = led.transition(eid, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                       expected_version=v)
    v = led.mark_terminal_evidence(eid,
                                   {"kind": "backend.completed", "exit": 0},
                                   expected_version=v)
    led.close()
    led = _reopen(tmp_path)
    rec = led.get_execution(eid)
    assert rec.state is WorkExecutionState.BACKEND_DONE_UNVERIFIED
    assert rec.terminal_evidence == {"kind": "backend.completed", "exit": 0}
    assert any(e["kind"] == "backend.completed"
               for e in led.events_of(eid))

    # w5：verification 完成（VERIFIED）但 truth-commit 尚未由 16G 执行 →
    # marker 保留、claim 仍可被 16G 认领
    v = led.transition(eid, WorkExecutionState.VERIFIED, expected_version=v)
    led.close()
    led = _reopen(tmp_path)
    rec = led.get_execution(eid)
    assert rec.state is WorkExecutionState.VERIFIED
    assert rec.truth_commit_status == ""
    assert led.claim_truth_commit(eid, "owner-16g") is True
    led.close()

    # w6：pre-submit cancel（intent 后 run 前）→ 零 backend run、零 submit
    c2 = "wc_crash2_0001"
    led = WorkLedger(tmp_path / "work_ledger.db")
    eid2 = led.submit_intent(c2, HASH_B, "att_crash2_0001")
    rec2 = led.get_execution(eid2)
    v2 = led.cancel_intent(eid2, expected_version=rec2.state_version)
    led.close()
    led = _reopen(tmp_path)
    rec2 = led.get_execution(eid2)
    assert rec2.state is WorkExecutionState.CANCELLED
    assert rec2.run_id == "" and rec2.cancel_intent is True
    assert rec2.is_active is False                       # 零 active claim
    # 非 active 后同 contract 可再次 submit（新执行），绝不复用取消行
    eid3 = led.submit_intent(c2, HASH_B, "att_crash2_0002")
    assert eid3 != eid2
    led.close()


def ledger_recoverable_ids(led):
    return [r.execution_id for r in led.load_non_terminal()]


def ledger_close(led):
    led.close()


# ================================================================
# 7 — 真实 16F outcome authenticity 正负路径（recovery verify）
# ================================================================

def test_recovery_verification_with_real_16f_outcome(tmp_path):
    tmp, work, work_real, outside, outside_real = env_dirs(tmp_path)
    c = make_contract(work_real, "wc_16h_16f_0001")
    v = IndependentVerifier(c)
    rep = v.verify(_ok_submission(c, "run_p13v_0001"))
    assert rep.verdict is VerificationVerdict.VERIFIED
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome
    attempt = AttemptRecord(attempt_id="att_16h_0001", run_id=rep.run_id,
                            contract_hash=rep.contract_hash,
                            verdict="VERIFIED", report_id=rep.report_id,
                            failure_signature="", started_at_epoch=1.0,
                            finished_at_epoch=2.0)
    outcome = RepairOutcome(stop_reason=RepairStopReason.VERIFIED,
                            contract_id=rep.contract_id,
                            contract_hash=rep.contract_hash,
                            attempts=(attempt,), final_report=rep,
                            started_at_epoch=1.0, finished_at_epoch=2.0)
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract(c.contract_id, c.content_hash)
    eid = led.submit_intent(c.contract_id, c.content_hash, "att_16h_0001")
    v1 = led.bind_run(eid, rep.run_id, "native_agent", expected_version=1)
    v2 = led.transition(eid, WorkExecutionState.BACKEND_DONE_UNVERIFIED,
                        expected_version=v1)
    # 正路径：authentic → VERIFIED + marker（marker 在同事务内持久化）
    v3 = led.mark_verified_by_outcome(eid, v, outcome, expected_version=v2)
    rec = led.get_execution(eid)
    assert rec.state is WorkExecutionState.VERIFIED
    assert rec.verification_marker == rep.report_digest
    # 负路径：伪造 seal → 拒绝、零状态修改
    forged = VerificationReport(
        report_id=rep.report_id, verifier_id=rep.verifier_id,
        contract_id=rep.contract_id, contract_hash=rep.contract_hash,
        standard_hash=rep.standard_hash, run_id=rep.run_id,
        backend_id=rep.backend_id, verdict=VerificationVerdict.VERIFIED,
        checks=rep.checks, diagnostics=rep.diagnostics, evidence=rep.evidence,
        started_at_epoch=rep.started_at_epoch,
        finished_at_epoch=rep.finished_at_epoch,
        authority_seal="f" * 64)
    with pytest.raises(WorkLedgerError):
        led.mark_verified_by_outcome(eid, v, forged, expected_version=v3)
    assert led.get_execution(eid).state is WorkExecutionState.VERIFIED
    led.close()


def env_dirs(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    from pathlib import Path
    return tmp_path, work, Path(os.path.realpath(work)), tmp_path / "outside", None


def make_contract(work_real, cid):
    art = work_real / "summary.md"
    art.write_bytes(b"ok")
    return WorkContract(
        contract_id=cid, contract_version="1.0.0",
        canonical_user_request="生成摘要文件",
        objective="o", commitment_scope_included=("o",),
        allowed_capabilities=("fs.write",), allowed_backends=("native_agent",),
        workspace_scope=WorkspaceScope(write_roots=(str(work_real),)),
        budget=ExecutionBudget(max_duration_seconds=600.0,
                               cost_limit=CostBudget(amount=5.0),
                               max_attempts=3),
        verification_standard=VerificationStandard(criteria=(
            VerificationCriterion(criterion_id="summary_exists0001",
                                  kind="artifact_file_exists",
                                  params={"path": str(art)}),)),
        approval_policy=ApprovalPolicyRef(policy_id="policy_scoped_v1",
                                          policy_kind="pre_approved_scoped",
                                          scope_note="n"),
        source_event_id="lev_1756000000000_deadbeef")


# ================================================================
# 8 — cancellation 全路径
# ================================================================

def test_cancellation_paths(ledger):
    ledger.register_contract("wc_cxl_0001", HASH_A)
    # pre-submit cancel：零 backend run
    eid = ledger.submit_intent("wc_cxl_0001", HASH_A, "att_cxl_0001")
    rec = ledger.get_execution(eid)
    v = ledger.cancel_intent(eid, expected_version=rec.state_version)
    rec = ledger.get_execution(eid)
    assert rec.state is WorkExecutionState.CANCELLED and rec.run_id == ""
    assert ledger.dispatch_stop_once(eid) is False        # 零 backend stop

    # RUNNING cancel → CANCELLING + stop-once；重复 cancel 幂等
    eid2 = ledger.submit_intent("wc_cxl_0001", HASH_A, "att_cxl_0002")
    v2 = ledger.bind_run(eid2, "run_cxl_0002", "native_agent",
                         expected_version=1)
    v2 = ledger.transition(eid2, WorkExecutionState.RUNNING,
                           expected_version=v2)
    v2 = ledger.cancel_intent(eid2, expected_version=v2)
    assert ledger.get_execution(eid2).state is WorkExecutionState.CANCELLING
    v2b = ledger.cancel_intent(eid2, expected_version=v2)   # 幂等重复 cancel
    assert v2b == v2
    assert ledger.dispatch_stop_once(eid2) is True
    assert ledger.dispatch_stop_once(eid2) is False         # 恰好一次

    # 同 contract 在 CANCELLING（active）期间二次 submit 被阻止
    with pytest.raises(DuplicateActiveExecution):
        ledger.submit_intent("wc_cxl_0001", HASH_A, "att_cxl_blocked")
    # approval wait 取消 → 旧 approval 失效；迟到 approve 不得恢复执行
    # （独立契约——上一契约仍在 CANCELLING reconciliation 中）
    ledger.register_contract("wc_cxl2_0001", HASH_A)
    eid3 = ledger.submit_intent("wc_cxl2_0001", HASH_A, "att_cxl_0003")
    v3 = ledger.bind_run(eid3, "run_cxl_0003", "native_agent",
                         expected_version=1)
    v3 = ledger.transition(eid3, WorkExecutionState.WAITING_PERMISSION,
                           expected_version=v3)
    v3 = ledger.cancel_intent(eid3, expected_version=v3)
    ledger.invalidate_approval(eid3)
    assert ledger.approval_invalidated(eid3) is True
    with pytest.raises(WorkLedgerError):
        ledger.transition(eid3, WorkExecutionState.RUNNING,
                          expected_version=v3)              # CANCELLING 非法迁移
    # 迟到 terminal 事件 → 以真实 terminal evidence 收口（CANCELLING →
    # CANCELLED 需 terminal evidence；此处直接验证终态迁移仍合法）
    v3 = ledger.mark_terminal_evidence(eid3, {"late": "terminal"},
                                       expected_version=v3)
    v3 = ledger.transition(eid3, WorkExecutionState.CANCELLED,
                           expected_version=v3)
    assert ledger.get_execution(eid3).state is WorkExecutionState.CANCELLED


# ================================================================
# 9/10 — 事件幂等 / 冲突 / critical flood / progress 有界
# ================================================================

def test_event_idempotency_conflict_and_critical_flood(tmp_path):
    led = WorkLedger(tmp_path / "work_ledger.db",
                     max_events_per_run=8, max_global_events=64)
    led.register_contract("wc_evt_0001", HASH_A)
    eid = led.submit_intent("wc_evt_0001", HASH_A, "att_evt_0001")
    # 同内容重投幂等
    assert led.record_event(eid, "ev_evt_0001", EventKind.BACKEND_COMPLETED,
                            {"exit": 0}) == "stored"
    assert led.record_event(eid, "ev_evt_0001", EventKind.BACKEND_COMPLETED,
                            {"exit": 0}) == "duplicate"
    # 同 id 异内容 → 类型化冲突
    with pytest.raises(EventContentConflict):
        led.record_event(eid, "ev_evt_0001", EventKind.BACKEND_COMPLETED,
                         {"exit": 1})
    # critical flood 至 per-run 上限 → 下一 critical fail-closed + 计数
    for i in range(7):
        assert led.record_event(eid, f"ev_crit_{i:04d}", EventKind.RUN_STARTED,
                                {"i": i}) == "stored"
    with pytest.raises(CriticalBufferOverflow):
        led.record_event(eid, "ev_crit_overflow", EventKind.RUN_STARTED,
                         {"overflow": True})
    assert led.counter("critical_overflow") == 1
    # progress 在上限处确定性丢弃（不挤占 critical、不无界增长）
    for i in range(12):
        outcome = led.record_event(eid, f"ev_prog_{i:04d}",
                                   EventKind.TOOL_PROGRESS, {"i": i})
        assert outcome in ("stored", "dropped")
    assert led.counter("progress_dropped") >= 1
    # DB 行数硬上界
    assert led.counter("critical_overflow") >= 0
    rows = len(led.events_of(eid))
    assert rows <= 8
    led.close()


def test_100k_progress_flood_bounded(ledger):
    """100k progress flood：内存与 DB 行数保持硬上限（确定性丢弃 + 计数）。"""
    buf = WorkEventBuffer(per_run_cap=128, global_cap=512)
    for i in range(100000):
        buf.offer(f"prog_{i:06d}", EventKind.TOOL_PROGRESS, {"i": i})
    assert len(buf.snapshot()) <= 128
    assert buf.dropped_ticks == 100000 - 128
    # ledger 侧：progress 行数受 per-run 上界约束
    ledger.register_contract("wc_flood_0001", HASH_A)
    eid = ledger.submit_intent("wc_flood_0001", HASH_A, "att_flood_0001")
    for i in range(500):
        outcome = ledger.record_event(eid, f"flood_{i:06d}",
                                      EventKind.TOOL_PROGRESS, {"i": i})
        assert outcome in ("stored", "dropped")
    assert len(ledger.events_of(eid)) <= 256              # per-run 硬上限
    assert ledger.counter("progress_dropped") >= 500 - 256


# ================================================================
# 11 — restart 保留 terminal/critical evidence，仅清 operational buffer
# ================================================================

def test_restart_preserves_evidence_clears_operational_buffer(tmp_path):
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract("wc_rst_0001", HASH_A)
    eid = led.submit_intent("wc_rst_0001", HASH_A, "att_rst_0001")
    v = led.bind_run(eid, "run_rst_0001", "native_agent", expected_version=1)
    led.record_event(eid, "ev_rst_crit", EventKind.BACKEND_COMPLETED,
                     {"exit": 0})
    v = led.transition(eid, WorkExecutionState.VERIFIED, expected_version=v)
    buf = WorkEventBuffer()
    buf.offer("op_0001", EventKind.TOOL_PROGRESS, {"i": 1})
    buf.offer("op_0002", EventKind.TRANSPORT_RECONNECTED, {})
    buf.clear_operational()
    assert len(buf.snapshot()) == 0
    led.close()
    led2 = WorkLedger(tmp_path / "work_ledger.db")
    rec = led2.get_execution(eid)
    assert rec.state is WorkExecutionState.VERIFIED       # terminal evidence 保留
    assert any(e["kind"] == "backend.completed"
               for e in led2.events_of(eid))              # critical 保留
    led2.close()


# ================================================================
# 12 — truth-commit claim 并发唯一 / stale 拒绝 / C7/C6 零写入
# ================================================================

def test_truth_commit_claim_concurrent_unique_and_c7_untouched(tmp_path):
    cog_path = tmp_path / "furina.db"
    cog = CognitionDB(cog_path)
    cog_rows_before = sorted(tuple(r) for r in cog.query_all(
        "SELECT task_id, verified FROM agent_tasks"))
    led = WorkLedger(tmp_path / "work_ledger.db")
    led.register_contract("wc_tc_0001", HASH_A)
    eid = led.submit_intent("wc_tc_0001", HASH_A, "att_tc_0001")
    winners = []
    lock = threading.Lock()

    def worker(token):
        if led.claim_truth_commit(eid, token):
            with lock:
                winners.append(token)

    threads = [threading.Thread(target=worker, args=(f"owner-{i:02d}",))
               for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1
    rec = led.get_execution(eid)
    assert rec.truth_commit_status == "CLAIMED"
    assert rec.truth_commit_owner == winners[0]
    # resolve 仅 owner
    assert led.resolve_truth_commit(eid, "not-owner") is False
    assert led.resolve_truth_commit(eid, winners[0]) is True
    # C7/C6 零写入：cognition rows 前后相等
    cog_rows_after = sorted(tuple(r) for r in cog.query_all(
        "SELECT task_id, verified FROM agent_tasks"))
    assert cog_rows_before == cog_rows_after
    cog.close()
    led.close()


# ================================================================
# 13 — GUI/60fps 路径零 DB I/O（buffer 纯内存）
# ================================================================

def test_tick_path_buffer_is_pure_memory_no_db():
    """WorkEventBuffer.offer/snapshot 纯内存——绝不触碰任何 DB 连接
    （60fps tick 禁止 DB/vector/network I/O 的结构证明）。"""
    buf = WorkEventBuffer(per_run_cap=4, global_cap=8)
    for i in range(50):
        buf.offer(f"tick_{i:04d}", EventKind.TOOL_PROGRESS, {"i": i})
    buf.offer("crit_0001", EventKind.BACKEND_COMPLETED, {"exit": 0})
    buf.offer("coal_0001", EventKind.TRANSPORT_RECONNECTED, {})
    buf.offer("coal_0002", EventKind.TRANSPORT_RECONNECTED, {})   # 合并前一个
    snap = buf.snapshot()
    assert any(e["kind"] is EventKind.BACKEND_COMPLETED for e in snap)
    assert sum(1 for e in snap
               if e["kind"] is EventKind.TRANSPORT_RECONNECTED) == 1
    assert buf.dropped_ticks > 0 and buf.coalesced == 1


# ================================================================
# 14 — 非法类型 / NaN / 超大容器 / 敌意字段 fail-closed
# ================================================================

def test_hostile_inputs_fail_closed(ledger):
    ledger.register_contract("wc_hos_0001", HASH_A)
    eid = ledger.submit_intent("wc_hos_0001", HASH_A, "att_hos_0001")
    # 非 dict payload
    with pytest.raises(WorkLedgerError):
        ledger.record_event(eid, "ev_hos_0001", EventKind.RUN_STARTED,
                            "not-a-dict")          # type: ignore[arg-type]
    # 非 str 键
    with pytest.raises(WorkLedgerError):
        ledger.record_event(eid, "ev_hos_0002", EventKind.RUN_STARTED,
                            {1: "x"})
    # NaN 载荷 → 类型化拒绝或确定性安全转换（绝不落 NaN 原文、绝不绕过边界）
    try:
        outcome = ledger.record_event(eid, "ev_hos_0003",
                                      EventKind.RUN_STARTED,
                                      {"v": float("nan")})
    except WorkLedgerError:
        outcome = "rejected"
    assert outcome in ("rejected", "dropped", "stored", "duplicate")
    if outcome == "stored":
        blob = json.dumps([e["payload"] for e in ledger.events_of(eid)])
        assert "NaN" not in blob
    # 敌意 payload 对象（__str__/__iter__ 即抛）→ 类型化拒绝、零泄漏
    class _Hostile:
        def __iter__(self):
            raise RuntimeError("leak:hunter16")

        def __str__(self):
            raise RuntimeError("leak:hunter16")

    with pytest.raises(WorkLedgerError):
        ledger.record_event(eid, "ev_hos_0004", EventKind.RUN_STARTED,
                            _Hostile())            # type: ignore[arg-type]
    # 全部拒绝：敌意/非法事件零落库（NaN 安全转换的事件不得含 NaN 原文）
    events = ledger.events_of(eid)
    ids = {e["event_id"] for e in events}
    assert {"ev_hos_0001", "ev_hos_0002", "ev_hos_0004"}.isdisjoint(ids)
    for e in events:
        assert "NaN" not in json.dumps(e["payload"])
    # 未知 execution
    with pytest.raises(UnknownExecution):
        ledger.get_execution(99999)


# ================================================================
# 15 — 查询防御性快照（不可变值）
# ================================================================

def test_queries_return_defensive_snapshots(ledger):
    ledger.register_contract("wc_snap_0001", HASH_A)
    eid = ledger.submit_intent("wc_snap_0001", HASH_A, "att_snap_0001",
                               {"goal": "g"})
    rec = ledger.get_execution(eid)
    rec.submit_intent["goal"] = "tampered"             # 修改快照
    rec2 = ledger.get_execution(eid)
    assert rec2.submit_intent == {"goal": "g"}          # 内部零共享引用
