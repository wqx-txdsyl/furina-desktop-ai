# -*- coding: utf-8 -*-
"""Phase 16F — Independent Verification & Bounded Repair 测试。

任务书 §7 十二项最低锁定：
1. valid deterministic evidence verifies（VERIFIED + 唯一可认证 seal）；
2. forged completed/text/exit-zero remains unverified；
3. artifact tamper/path escape/symlink·最近现存祖先逃逸/oversize/unknown MIME rejected；
4. mixed checks fail if a required check fails；
5. inconclusive never maps to VERIFIED；
6. backend and verifier responsibilities separated（伪造 VERIFIED 无法认证；
   schema 无 backend 自报 verified/exit_code/final_text 字段）；
7. repair succeeds only after fresh evidence（陈旧证据不可复活）；
8. attempt/time/cost limits stop exactly；
9. repeated identical failure circuit-breaks；
10. cancellation/approval denial prevents repair；
11. contract hash unchanged across attempts（frozen 契约不可变）；
12. no C7/C6/C3 writes（源级 + 运行时 spy）。

额外否证（任务指令）：伪造成功 / artifact 篡改 / symlink escape（os.symlink 不可用时
回退 Windows junction——realpath 同样解析，覆盖"目标尚不存在时最近现存祖先"逃逸）/
预算边界 / 重复失败 / cancellation·denial / 契约 hash 不变 / 零 C7·C6·C3 写入；
exact-schema（未知键/缺键/NaN/Inf/bool 冒充数值/相对路径/重复 id/非 16E 词表 kind）；
defensive-copy 冻结与报告/导出零共享引用；repair 新 attempt/run id 绑定同契约。

Reviewer Patch 1 否证（8 组 blocker，每组 reviewer-locked）：
B1 substantive gate：terminal claim/allowlist/verifier_ref 全 PASS 但零
   substantive deterministic check → INCONCLUSIVE / seal=""；
B2 MIME/content：内容识别真值（magic/JSON/text 有界规则）+ suffix 交叉核对 +
   artifact_type 封闭规则 + binary 显式接受 + 合法正例；
B3 optional artifact：存在即 required FAIL（escape/oversize/声明矛盾），
   真正不存在才豁免；
B4 repair 边界复核：attempt 中 cancellation / 完成后 cost 超限 / 完成时间
   过 deadline 时 VERIFIED 报告不得成为成功结果（final_report=None）；
   cost meter 严格类型/NaN/Inf/负数/异常 fail-closed、启动前 >= limit 零 collect；
B5 process output：DEVNULL 零聚合 + 超时可靠终止整棵进程树；
B6 秘密边界：HardBackendFailure/approval 诊断脱敏、秘密形态路径/身份拒绝；
B7 稳定快照：验证期间文件变异 → artifact_mutated_during_verification；
   criterion-only 文件受 MAX_ARTIFACT_BYTES 上限；
B8 canonical identity：首尾空白/控制字符/秘密形态身份 → VerificationInputError。
"""

import builtins
import dataclasses
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

from furina.agent.verification import (
    ARTIFACT_CLAIM_KEYS,
    BoundedRepairLoop,
    CheckResult,
    HardBackendFailure,
    IndependentVerifier,
    MAX_ARTIFACT_BYTES,
    MAX_EXPLANATION_CHARS,
    MAX_REPORT_JSON_BYTES,
    RepairStopReason,
    TERMINAL_CLAIM_KEYS,
    VERIFICATION_INPUT_KEYS,
    VERIFIER_ID,
    VerificationAuthorityError,
    VerificationError,
    VerificationInputError,
    VerificationReport,
    VerificationVerdict,
)
from furina.agent.work_contract import (
    ArtifactExpectation,
    ApprovalPolicyRef,
    CostBudget,
    ExecutionBudget,
    VerificationCriterion,
    VerificationStandard,
    WorkspaceScope,
    WorkContract,
    compute_content_hash,
)

# ================================================================
# helpers
# ================================================================

EVENT_ID = "lev_1756000000001_0000ff"
BASE_TS = 1756000001.0


class FakeClock:
    """确定性时钟（time budget 精确停止测试）。"""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt)


def _make_dir_link(link: Path, target: Path) -> bool:
    """目录链接（symlink 优先，Windows 无特权时回退 junction——realpath 等价解析）。"""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return True
        except Exception:
            return False
    return False


@pytest.fixture
def env(tmp_path):
    """work（write root）/ outside（workspace 外）目录；契约 workspace 用 realpath
    归一，避免测试宿主 tmp 自身链接造成 containment 误判。"""
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    work_real = Path(os.path.realpath(work))
    outside_real = Path(os.path.realpath(outside))
    return tmp_path, work, work_real, outside, outside_real


def _contract(work_real: Path, **overrides) -> WorkContract:
    art = work_real / "summary.md"
    kw = dict(
        contract_id="wc_16f_test_0001",
        contract_version="1.0.0",
        canonical_user_request="生成摘要文件",
        objective="在 write_root 内生成可通过判据校验的摘要文件",
        commitment_scope_included=("生成摘要文件",),
        allowed_capabilities=("fs.write",),
        allowed_backends=("native_agent",),
        workspace_scope=WorkspaceScope(write_roots=(str(work_real),)),
        budget=ExecutionBudget(max_duration_seconds=600.0,
                               cost_limit=CostBudget(amount=5.0, currency="CNY"),
                               max_attempts=3),
        verification_standard=VerificationStandard(criteria=(
            VerificationCriterion(criterion_id="summary_exists",
                                  kind="artifact_file_exists",
                                  params={"path": str(art)}),
        )),
        approval_policy=ApprovalPolicyRef(policy_id="policy_scoped_v1",
                                          policy_kind="pre_approved_scoped",
                                          scope_note="仅限 write_root 内写入"),
        source_event_id="lev_1756000000000_deadbeef",
    )
    kw.update(overrides)
    return WorkContract(**kw)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _submission(contract: WorkContract, run_id: str, *, backend_id: str = "native_agent",
                kind: str = "backend.completed", declared=(), bind: bool = True,
                terminal=None) -> dict:
    events = terminal if terminal is not None else [{
        "event_id": EVENT_ID, "kind": kind, "observed_at_epoch": BASE_TS,
        "run_id": run_id if bind else "run_other_0001",
        "contract_id": contract.contract_id if bind else "wc_other_0001",
        "backend_id": backend_id if bind else "rogue_backend",
    }]
    return {"run_id": run_id, "backend_id": backend_id,
            "terminal_events": list(events), "declared_artifacts": list(declared)}


def _declared(path, sha_hex=None, mime=None, size=None, artifact_id="summary_doc"):
    return {"artifact_id": artifact_id, "path": str(path), "declared_sha256": sha_hex,
            "declared_mime": mime, "declared_size_bytes": size}


def _bound_terminal(contract: WorkContract, run_id: str, kind="backend.completed",
                    event_id: str = EVENT_ID):
    return {"event_id": event_id, "kind": kind, "observed_at_epoch": BASE_TS,
            "run_id": run_id, "contract_id": contract.contract_id,
            "backend_id": "native_agent"}


# ================================================================
# §7.1 — valid deterministic evidence verifies
# ================================================================


def test_valid_deterministic_evidence_verifies(env):
    tmp, work, work_real, outside, outside_real = env
    content = b"daily summary line alpha"
    art = work_real / "summary.md"
    art.write_bytes(content)
    c = _contract(work_real, verification_standard=VerificationStandard(criteria=(
        VerificationCriterion(criterion_id="summary_exists",
                              kind="artifact_file_exists", params={"path": str(art)}),
        VerificationCriterion(criterion_id="summary_sha",
                              kind="artifact_sha256",
                              params={"path": str(art), "sha256_hex": _sha(content)}),
        VerificationCriterion(criterion_id="summary_text",
                              kind="text_contains",
                              params={"path": str(art), "needle": "alpha"}),
    ), verifier_refs=(VERIFIER_ID,)))
    v = IndependentVerifier(c)
    sub = _submission(c, "run_ok_0001",
                      declared=[_declared(art, sha_hex=_sha(content),
                                          mime="text/markdown", size=len(content))])
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.VERIFIED
    assert rep.authority_seal and len(rep.authority_seal) == 64
    assert v.seal_is_authentic(rep) is True
    assert rep.contract_id == c.contract_id
    assert rep.contract_hash == c.content_hash
    assert rep.standard_hash == compute_content_hash(c.verification_standard.to_dict())
    assert len(rep.report_digest) == 64
    assert rep.evidence.evidence_digest() and len(rep.evidence.evidence_digest()) == 64
    results = {ch.check_id: ch.result for ch in rep.checks}
    assert results["criterion:summary_exists"] is CheckResult.PASS
    assert results["criterion:summary_sha"] is CheckResult.PASS
    assert results["criterion:summary_text"] is CheckResult.PASS
    assert len(rep.to_json().encode("utf-8")) <= MAX_REPORT_JSON_BYTES


# ================================================================
# §7.2 — forged completed / text / exit-zero remains unverified
# ================================================================


def test_backend_completed_claim_alone_never_verifies(env):
    """backend.completed 绑定 claim 也绝不产生 VERIFIED——必需 artifact 缺失即 FAILED。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)          # criterion: summary.md 存在——但文件不存在
    v = IndependentVerifier(c)
    sub = _submission(c, "run_claim_0001")
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    assert any(ch.check_id == "criterion:summary_exists"
               and ch.result is CheckResult.FAIL and "file_missing" in ch.explanation
               for ch in rep.checks)


def test_exit_zero_is_locally_rerun_not_trusted(env):
    """process_exit_zero 由 verifier 本地重跑裁定；backend 侧不存在 exit_code 自报字段。"""
    tmp, work, work_real, outside, outside_real = env
    py = sys.executable
    ok = _contract(work_real, contract_id="wc_16f_exit_ok_0001",
                   verification_standard=VerificationStandard(criteria=(
                       VerificationCriterion(criterion_id="proc",
                                             kind="process_exit_zero",
                                             params={"command": f'"{py}" -c "import sys; sys.exit(0)"'}),
                   )))
    bad = _contract(work_real, contract_id="wc_16f_exit_bad_0001",
                    verification_standard=VerificationStandard(criteria=(
                        VerificationCriterion(criterion_id="proc",
                                              kind="process_exit_zero",
                                              params={"command": f'"{py}" -c "import sys; sys.exit(3)"'}),
                    )))
    rep_ok = IndependentVerifier(ok).verify(_submission(ok, "run_exit_ok_0001"))
    rep_bad = IndependentVerifier(bad).verify(_submission(bad, "run_exit_bad_0001"))
    assert rep_ok.verdict is VerificationVerdict.VERIFIED
    assert rep_bad.verdict is VerificationVerdict.FAILED
    assert any("exit_code:3" in ch.explanation for ch in rep_bad.checks)


def test_forged_verified_report_cannot_authenticate(env):
    """伪造 VERIFIED 报告：格式面可构造，但 seal 无法通过真实性复核（唯一授权入口）。"""
    tmp, work, work_real, outside, outside_real = env
    content = b"data"
    art = work_real / "summary.md"
    art.write_bytes(content)
    c = _contract(work_real)
    v = IndependentVerifier(c)
    real = v.verify(_submission(c, "run_auth_0001",
                                declared=[_declared(art, sha_hex=_sha(content))]))
    assert real.verdict is VerificationVerdict.VERIFIED
    forged = VerificationReport(
        report_id="vrp_" + "0" * 32, verifier_id=VERIFIER_ID,
        contract_id=real.contract_id, contract_hash=real.contract_hash,
        standard_hash=real.standard_hash, run_id=real.run_id,
        backend_id=real.backend_id, verdict=VerificationVerdict.VERIFIED,
        checks=real.checks, diagnostics=real.diagnostics, evidence=real.evidence,
        started_at_epoch=real.started_at_epoch,
        finished_at_epoch=real.finished_at_epoch, authority_seal="f" * 64)
    assert v.seal_is_authentic(forged) is False
    v_other = IndependentVerifier(c)          # 另一验证器（另一密钥）
    assert v_other.seal_is_authentic(real) is False
    assert v.seal_is_authentic(real) is True


def test_verified_without_seal_rejected_at_construction(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    sub = _submission(c, "run_seal_0001")
    rep = v.verify(sub)
    with pytest.raises(VerificationAuthorityError):
        VerificationReport(
            report_id="vrp_" + "1" * 32, verifier_id=VERIFIER_ID,
            contract_id=rep.contract_id, contract_hash=rep.contract_hash,
            standard_hash=rep.standard_hash, run_id=rep.run_id,
            backend_id=rep.backend_id, verdict=VerificationVerdict.VERIFIED,
            checks=rep.checks, diagnostics=rep.diagnostics, evidence=rep.evidence,
            started_at_epoch=1.0, finished_at_epoch=2.0, authority_seal="")
    with pytest.raises(VerificationAuthorityError):
        VerificationReport(
            report_id="vrp_" + "1" * 32, verifier_id="rogue.verifier",
            contract_id=rep.contract_id, contract_hash=rep.contract_hash,
            standard_hash=rep.standard_hash, run_id=rep.run_id,
            backend_id=rep.backend_id, verdict=VerificationVerdict.VERIFIED,
            checks=rep.checks, diagnostics=rep.diagnostics, evidence=rep.evidence,
            started_at_epoch=1.0, finished_at_epoch=2.0, authority_seal="a" * 64)


def test_non_verified_verdict_must_not_carry_seal(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    rep = IndependentVerifier(c).verify(_submission(c, "run_noseal_0001"))
    assert rep.verdict is VerificationVerdict.FAILED and rep.authority_seal == ""
    with pytest.raises(VerificationAuthorityError):
        VerificationReport(
            report_id="vrp_" + "2" * 32, verifier_id=VERIFIER_ID,
            contract_id=rep.contract_id, contract_hash=rep.contract_hash,
            standard_hash=rep.standard_hash, run_id=rep.run_id,
            backend_id=rep.backend_id, verdict=VerificationVerdict.FAILED,
            checks=rep.checks, diagnostics=rep.diagnostics, evidence=rep.evidence,
            started_at_epoch=1.0, finished_at_epoch=2.0, authority_seal="b" * 64)


@pytest.mark.parametrize("extra", [
    {"verified": True},
    {"final_text": "task completed successfully"},
    {"exit_code": 0},
    {"status": "success"},
])
def test_backend_self_report_fields_are_unknown_keys(env, extra):
    """backend 自报 verified/exit_code/成功文本在 schema 里不存在——未知键 fail-closed。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    sub = _submission(c, "run_self_0001")
    sub.update(extra)
    with pytest.raises(VerificationInputError):
        v.verify(sub)


# ================================================================
# §7.3 — artifact tamper / path escape / oversize / unknown MIME rejected
# ================================================================


def test_tampered_artifact_declared_hash_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    original = b"original content"
    art = work_real / "summary.md"
    art.write_bytes(original)
    c = _contract(work_real)
    v = IndependentVerifier(c)
    art.write_bytes(original + b" TAMPERED")   # 声明 hash 对应旧内容
    sub = _submission(c, "run_tamper_0001",
                      declared=[_declared(art, sha_hex=_sha(original))])
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("declared_hash_mismatch_artifact_tampered" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


def test_relative_path_escape_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    evil = str(work_real / ".." / "outside" / "evil.md")
    sub = _submission(c, "run_esc_0001", declared=[_declared(evil)])
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert any(ch.result is CheckResult.FAIL and "path_escape" in ch.explanation
               for ch in rep.checks)


def test_absolute_outside_path_escape_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    (outside_real / "secret.md").write_bytes(b"s")
    c = _contract(work_real)
    v = IndependentVerifier(c)
    sub = _submission(c, "run_absesc_0001",
                      declared=[_declared(outside_real / "secret.md")])
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert any(ch.result is CheckResult.FAIL and "path_escape" in ch.explanation
               for ch in rep.checks)


def test_symlink_escape_rejected(env):
    """workspace 内链接指向 workspace 外的现存文件 → path_escape（realpath 真相）。"""
    tmp, work, work_real, outside, outside_real = env
    (outside_real / "f.md").write_bytes(b"escaped")
    link = work / "link"
    if not _make_dir_link(link, outside):
        pytest.skip("symlink/junction 在本机不可用")
    c = _contract(work_real)
    v = IndependentVerifier(c)
    sub = _submission(c, "run_link_0001", declared=[_declared(link / "f.md")])
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert any(ch.result is CheckResult.FAIL and "path_escape" in ch.explanation
               for ch in rep.checks)
    assert all(ch.result is not CheckResult.PASS
               for ch in rep.checks if ch.check_id.endswith(":hash"))


def test_ancestor_link_escape_rejected(env):
    """目标尚不存在、最近现存祖先是 workspace 内链接 → realpath 解析出逃逸。"""
    tmp, work, work_real, outside, outside_real = env
    link = work / "link2"
    if not _make_dir_link(link, outside):
        pytest.skip("symlink/junction 在本机不可用")
    c = _contract(work_real)
    v = IndependentVerifier(c)
    sub = _submission(c, "run_anc_0001",
                      declared=[_declared(link / "sub" / "new.md")])
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert any(ch.result is CheckResult.FAIL and "path_escape" in ch.explanation
               for ch in rep.checks), \
        [c_.check_id + ":" + c_.explanation for c_ in rep.checks]


def test_oversize_artifact_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    big = work_real / "summary.md"
    big.write_bytes(b"\0" * (MAX_ARTIFACT_BYTES + 1))
    c = _contract(work_real)
    v = IndependentVerifier(c)
    # 以 declared claim 提交该产物：观察在哈希/记录前先按有界规则拒绝（oversize）。
    sub = _submission(c, "run_big_0001", declared=[_declared(big)])
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("artifact_oversize" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)
    assert all(ch.result is not CheckResult.PASS
               for ch in rep.checks if ch.check_id.endswith(":hash"))


def test_unknown_declared_mime_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"x")
    c = _contract(work_real)
    v = IndependentVerifier(c)
    sub = _submission(c, "run_mime_0001",
                      declared=[_declared(art, mime="application/x-unknown-vendor")])
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("unsupported_mime" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


def test_declared_mime_mismatch_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.json"
    art.write_bytes(b"{}")
    c = _contract(work_real, contract_id="wc_16f_mime_0002")
    v = IndependentVerifier(c)
    sub = _submission(c, "run_mimemis_0001",
                      declared=[_declared(art, mime="text/markdown")])   # 观察是 application/json
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("declared_mime_mismatch" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


def test_declared_artifact_missing_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    sub = _submission(c, "run_dmiss_0001",
                      declared=[_declared(work_real / "ghost.md", sha_hex="0" * 64)])
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("declared_artifact_missing" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


def test_declared_path_differs_from_expected_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"x")
    c = _contract(work_real, artifact_expectations=(
        ArtifactExpectation(artifact_id="summary_doc", artifact_type="markdown_document",
                            expected_path=str(art), required=True),
    ))
    v = IndependentVerifier(c)
    other = work_real / "elsewhere.md"
    other.write_bytes(b"x")
    sub = _submission(c, "run_loc_0001",
                      declared=[_declared(other, artifact_id="summary_doc")])
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert any(ch.check_id == "artifact_expectation:summary_doc:location"
               and ch.result is CheckResult.FAIL for ch in rep.checks)


# ================================================================
# §7.4 — mixed checks fail if a required check fails
# ================================================================


def test_mixed_checks_fail_if_required_fails(env):
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"content without marker")
    c = _contract(work_real, verification_standard=VerificationStandard(criteria=(
        VerificationCriterion(criterion_id="exists_ok",
                              kind="artifact_file_exists", params={"path": str(art)}),
        VerificationCriterion(criterion_id="needle_missing",
                              kind="text_contains",
                              params={"path": str(art), "needle": "REQUIRED_MARKER"}),
    )))
    rep = IndependentVerifier(c).verify(_submission(c, "run_mixed_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    results = {ch.check_id: ch.result for ch in rep.checks}
    assert results["criterion:exists_ok"] is CheckResult.PASS
    assert results["criterion:needle_missing"] is CheckResult.FAIL


# ================================================================
# §7.5 — inconclusive never maps to VERIFIED
# ================================================================


@pytest.mark.parametrize("terminal", [
    [],                                       # 无终态 claim
    None,                                     # sentinel → 用 unbound claim
    "ambiguous",
    "non_terminal_kind",
])
def test_inconclusive_never_maps_to_verified(env, terminal):
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"ok")
    c = _contract(work_real)
    v = IndependentVerifier(c)
    run_id = "run_inc_0001"
    if terminal is None:
        claim = _bound_terminal(c, run_id)
        claim["run_id"] = "run_someone_else"     # 未绑定 → 不可判
        sub = _submission(c, run_id, terminal=[claim])
    elif terminal == "ambiguous":
        sub = _submission(c, run_id, terminal=[
            _bound_terminal(c, run_id, kind="backend.completed", event_id="lev_1_00000001"),
            _bound_terminal(c, run_id, kind="backend.failed", event_id="lev_1_00000002"),
        ])
    elif terminal == "non_terminal_kind":
        sub = _submission(c, run_id, terminal=[
            _bound_terminal(c, run_id, kind="run.started", event_id="lev_1_00000003")])
    else:
        sub = _submission(c, run_id, terminal=terminal)
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.INCONCLUSIVE
    assert rep.authority_seal == ""
    assert v.seal_is_authentic(rep) is False


def test_unsupported_verifier_ref_inconclusive(env):
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"ok")
    c = _contract(work_real, contract_id="wc_16f_ref_0002",
                  verification_standard=VerificationStandard(
                      criteria=(), verifier_refs=("some.third_party_verifier",)))
    rep = IndependentVerifier(c).verify(_submission(c, "run_ref_0001"))
    assert rep.verdict is VerificationVerdict.INCONCLUSIVE
    assert any("unsupported_verifier_ref" in d for d in rep.diagnostics)


def test_backend_not_allowed_inconclusive(env):
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"ok")
    c = _contract(work_real)
    v = IndependentVerifier(c)
    sub = _submission(c, "run_rogue_0001", backend_id="rogue_backend")
    rep = v.verify(sub)
    assert rep.verdict is VerificationVerdict.INCONCLUSIVE
    assert any("backend_not_allowed" in d for d in rep.diagnostics)


def test_invalid_regex_pattern_inconclusive(env):
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"ok")
    c = _contract(work_real, contract_id="wc_16f_regex_0002",
                  verification_standard=VerificationStandard(criteria=(
                      VerificationCriterion(criterion_id="regex_match", kind="regex_matches",
                                            params={"path": str(art), "pattern": "("}),
                  )))
    rep = IndependentVerifier(c).verify(_submission(c, "run_rx_0001"))
    assert rep.verdict is VerificationVerdict.INCONCLUSIVE
    assert any("invalid_pattern" in ch.explanation for ch in rep.checks)


def test_missing_workspace_root_process_inconclusive(env, tmp_path):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, contract_id="wc_16f_cwd_0002",
                  verification_standard=VerificationStandard(criteria=(
                      VerificationCriterion(criterion_id="proc", kind="process_exit_zero",
                                            params={"command": "echo hi"}),
                  )))
    v = IndependentVerifier(c)
    import shutil
    shutil.rmtree(work, ignore_errors=True)      # write root 消失 → cwd 缺失
    rep = v.verify(_submission(c, "run_cwd_0001"))
    assert rep.verdict is VerificationVerdict.INCONCLUSIVE
    assert any("workspace_root_missing" in ch.explanation for ch in rep.checks)


# ================================================================
# §7.6 — backend and verifier responsibilities separated
# ================================================================


def test_schema_carries_no_backend_self_report_semantics():
    all_keys = set(VERIFICATION_INPUT_KEYS) | set(TERMINAL_CLAIM_KEYS) | set(ARTIFACT_CLAIM_KEYS)
    for forbidden in ("verified", "exit_code", "status", "final_text", "success",
                      "result_summary", "output"):
        assert forbidden not in all_keys, forbidden


def test_verifier_requires_work_contract():
    with pytest.raises(VerificationError):
        IndependentVerifier("not-a-contract")


# ================================================================
# §7.7 — repair succeeds only after fresh evidence
# ================================================================


def test_repair_succeeds_only_after_fresh_evidence(env):
    tmp, work, work_real, outside, outside_real = env
    good = b"fresh content"
    art = work_real / "summary.md"
    art.write_bytes(b"stale")
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v = IndependentVerifier(c)
    stale_sha = _sha(b"stale")
    good_sha = _sha(good)
    state = {"attempt": 0}

    def collector2(attempt_id, run_id):
        state["attempt"] += 1
        if state["attempt"] == 1:
            art.write_bytes(b"tampered-by-backend")
            return _submission(c, run_id, declared=[_declared(art, sha_hex=stale_sha)])
        art.write_bytes(good)
        return _submission(c, run_id, declared=[_declared(art, sha_hex=good_sha)])

    loop = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector2)
    out = loop.run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert len(out.attempts) == 2
    assert out.attempts[0].verdict == "FAILED"
    assert out.attempts[1].verdict == "VERIFIED"
    assert out.final_report is not None
    assert out.final_report.verdict is VerificationVerdict.VERIFIED
    assert v.seal_is_authentic(out.final_report) is True


def test_repair_on_stale_evidence_cannot_revive(env):
    """陈旧证据（声明 hash 与本地内容永久矛盾）重复出现 → 断路，绝不 VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"actually-on-disk")
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v = IndependentVerifier(c)
    stale_sha = _sha(b"claimed-but-false")

    def collector(attempt_id, run_id):
        return _submission(c, run_id, declared=[_declared(art, sha_hex=stale_sha)])

    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector).run()
    assert out.stop_reason is RepairStopReason.REPEATED_FAILURE
    assert len(out.attempts) == 2
    assert out.final_report is not None
    assert out.final_report.verdict is VerificationVerdict.FAILED


# ================================================================
# §7.8 — attempt / time / cost limits stop exactly
# ================================================================


def _failing_collector(contract: WorkContract, distinct: bool):
    """可区分/不可区分失败证据的 collector 工厂。"""
    counter = {"n": 0}
    base = Path(contract.workspace_scope.write_roots[0])

    def collector(attempt_id, run_id):
        counter["n"] += 1
        aid = f"missing_{counter['n']:02d}" if distinct else "missing_fixed"
        return _submission(contract, run_id,
                           declared=[_declared(base / "ghost.md", artifact_id=aid)])

    return collector


def test_attempts_exhausted_stops_exactly(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=3))
    v = IndependentVerifier(c)
    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=True)).run()
    assert out.stop_reason is RepairStopReason.ATTEMPTS_EXHAUSTED
    assert len(out.attempts) == 3


def test_time_budget_stops_exactly(env):
    tmp, work, work_real, outside, outside_real = env
    clock = FakeClock(1000.0)
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=1000.0, cost_limit=CostBudget(amount=5.0), max_attempts=99))
    v = IndependentVerifier(c, now_fn=clock)

    def collector(attempt_id, run_id):
        clock.advance(400.0)                    # 每次执行推进 400s
        counter = getattr(collector, "n", 0) + 1
        setattr(collector, "n", counter)
        return _submission(c, run_id,
                           declared=[_declared(work_real / "ghost.md",
                                               artifact_id=f"m{counter:02d}")])

    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector,
                            now_fn=clock).run()
    deadline = 2000.0
    assert out.stop_reason is RepairStopReason.TIMEOUT
    assert len(out.attempts) == 3
    assert all(a.started_at_epoch < deadline for a in out.attempts)


def test_cost_budget_stops_exactly(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=99))
    v = IndependentVerifier(c)
    calls = {"n": 0}

    def cost_used():
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else 6.0   # 第二次预检时已超 5.0 上限

    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=True),
                            cost_used=cost_used).run()
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert len(out.attempts) == 1


# ================================================================
# §7.9 — repeated identical failure circuit-breaks
# ================================================================


def test_repeated_identical_failure_circuit_breaks(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v = IndependentVerifier(c)
    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=False)).run()
    assert out.stop_reason is RepairStopReason.REPEATED_FAILURE
    assert len(out.attempts) == 2
    assert out.attempts[0].failure_signature == out.attempts[1].failure_signature


def test_distinct_failures_do_not_circuit_break(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=3))
    v = IndependentVerifier(c)
    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=True)).run()
    assert out.stop_reason is RepairStopReason.ATTEMPTS_EXHAUSTED
    assert len(out.attempts) == 3
    sigs = [a.failure_signature for a in out.attempts]
    assert len(set(sigs)) == 3


def test_inconclusive_never_upgraded_in_repair(env):
    """INCONCLUSIVE（无终态 claim）在 repair 中绝不升级为 VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"ok")
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v = IndependentVerifier(c)

    def collector(attempt_id, run_id):
        return _submission(c, run_id, terminal=[])   # 永远无终态 claim

    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector).run()
    assert out.stop_reason is RepairStopReason.REPEATED_FAILURE
    assert out.final_report is not None
    assert out.final_report.verdict is VerificationVerdict.INCONCLUSIVE
    assert out.final_report.authority_seal == ""


# ================================================================
# §7.10 — cancellation / approval denial prevents repair
# ================================================================


def test_cancellation_prevents_next_attempt(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v = IndependentVerifier(c)
    flags = {"checked": 0}

    def cancel_requested():
        flags["checked"] += 1
        return flags["checked"] > 1             # 第二次预检起为 True

    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=True),
                            cancel_requested=cancel_requested).run()
    assert out.stop_reason is RepairStopReason.CANCELLED
    assert len(out.attempts) == 1


def test_cancellation_before_first_attempt_runs_nothing(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    ran = {"n": 0}

    def collector(attempt_id, run_id):
        ran["n"] += 1
        return _submission(c, run_id)

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=collector,
                            cancel_requested=lambda: True).run()
    assert out.stop_reason is RepairStopReason.CANCELLED
    assert len(out.attempts) == 0 and ran["n"] == 0


@pytest.mark.parametrize("second,first", [("deny", "approve"), ("timeout", "approve"),
                                          ("pending", "approve"), ("maybe", "approve"),
                                          ("", "approve")])
def test_approval_not_granted_prevents_repair(env, second, first):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v = IndependentVerifier(c)
    answers = [first, second]

    def authority(attempt_id, run_id):
        return answers.pop(0) if answers else "approve"

    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=True),
                            approval_authority=authority).run()
    assert out.stop_reason is RepairStopReason.APPROVAL_DENIED
    assert len(out.attempts) == 1


def test_approval_denial_blocks_first_attempt(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    ran = {"n": 0}

    def collector(attempt_id, run_id):
        ran["n"] += 1
        return _submission(c, run_id)

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=collector,
                            approval_authority=lambda a, r: "deny").run()
    assert out.stop_reason is RepairStopReason.APPROVAL_DENIED
    assert len(out.attempts) == 0 and ran["n"] == 0


def test_approval_gated_policy_requires_authority(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, approval_policy=ApprovalPolicyRef(
        policy_id="p_gate", policy_kind="approval_required_each_step"))
    with pytest.raises(VerificationError):
        BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                          collect_evidence=lambda a, r: _submission(c, r))


def test_hard_failure_stops_immediately(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v = IndependentVerifier(c)

    def collector(attempt_id, run_id):
        raise HardBackendFailure("backend runtime crashed")

    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector).run()
    assert out.stop_reason is RepairStopReason.HARD_FAILURE
    assert len(out.attempts) == 1
    assert "hard_backend_failure" in out.attempts[0].diagnostic


# ================================================================
# §7.11 — contract hash unchanged across attempts
# ================================================================


def test_contract_hash_unchanged_across_attempts_and_frozen(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=4))
    v = IndependentVerifier(c)
    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=True)).run()
    assert len(out.attempts) >= 2
    assert all(a.contract_hash == c.content_hash for a in out.attempts)
    if out.final_report is not None:
        assert out.final_report.contract_hash == c.content_hash
    assert out.contract_hash == c.content_hash
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.contract_id = "wc_mutated_0001"        # frozen 契约不可变（repair 无法改约）


def test_repair_binds_verifier_to_same_contract(env):
    tmp, work, work_real, outside, outside_real = env
    c1 = _contract(work_real, contract_id="wc_16f_bind_a_0001")
    c2 = _contract(work_real, contract_id="wc_16f_bind_b_0001")
    with pytest.raises(VerificationError):
        BoundedRepairLoop(contract=c1, verifier=IndependentVerifier(c2),
                          collect_evidence=lambda a, r: _submission(c1, r))


# ================================================================
# §7.12 — no C7/C6/C3 writes
# ================================================================


def test_no_c7_c6_c3_source_level():
    pkg_dir = Path(__file__).resolve().parents[3] / "furina" / "agent" / "verification"
    forbidden = ("furina.cognition", "CognitionHub", "persist_agent_result",
                 "MemoryEngine", "EventBus", "sqlite", "AGENT_COMPLETED",
                 "AGENT_FAILED", "agent_task", "AgentTask")
    for py in pkg_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{py.name} 含禁写 token: {token}"


def test_no_c7_c6_c3_runtime(env, monkeypatch):
    tmp, work, work_real, outside, outside_real = env
    import furina.cognition.hub as hub_mod
    from furina.core import EventBus

    def _boom(*args, **kwargs):
        raise AssertionError("C7/C6 写入被尝试（16F 禁止）")

    monkeypatch.setattr(hub_mod.CognitionHub, "persist_agent_result", _boom)
    monkeypatch.setattr(EventBus, "emit", _boom)

    art = work_real / "summary.md"
    art.write_bytes(b"ok")
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=3))
    v = IndependentVerifier(c)
    rep = v.verify(_submission(c, "run_c73_0001",
                               declared=[_declared(art, sha_hex=_sha(b"ok"))]))
    assert rep.verdict is VerificationVerdict.VERIFIED
    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=True)).run()
    assert out.stop_reason in (RepairStopReason.ATTEMPTS_EXHAUSTED,
                               RepairStopReason.REPEATED_FAILURE)


# ================================================================
# exact-schema / 严格类型 fail-closed
# ================================================================


def _base_sub(c, run_id="run_schema_0001"):
    return _submission(c, run_id,
                       declared=[_declared(Path(c.workspace_scope.write_roots[0]) / "summary.md")])


def test_input_missing_key_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    sub = _base_sub(c)
    sub.pop("declared_artifacts")
    with pytest.raises(VerificationInputError):
        v.verify(sub)


def test_input_nan_inf_bool_timestamp_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    for bad in (float("nan"), float("inf"), float("-inf"), True, False, "1756000001"):
        claim = _bound_terminal(c, "run_nan_0001")
        claim["observed_at_epoch"] = bad
        with pytest.raises(VerificationInputError):
            v.verify(_submission(c, "run_nan_0001", terminal=[claim]))


def test_input_bool_size_and_float_size_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    art = work_real / "summary.md"
    art.write_bytes(b"x")
    for bad in (True, False, 3.5, 0, -1, "10"):
        with pytest.raises(VerificationInputError):
            v.verify(_submission(c, "run_size_0001",
                                 declared=[_declared(art, size=bad)]))


def test_input_relative_artifact_path_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    with pytest.raises(VerificationInputError):
        IndependentVerifier(c).verify(_submission(
            c, "run_rel_0001", declared=[_declared("relative/summary.md")]))


def test_input_duplicate_ids_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    d = _declared(work_real / "summary.md")
    with pytest.raises(VerificationInputError):
        v.verify(_submission(c, "run_dup_0001", declared=[d, dict(d)]))
    t1 = _bound_terminal(c, "run_dup_0002", event_id="lev_1_00000001")
    t2 = _bound_terminal(c, "run_dup_0002", event_id="lev_1_00000001")
    with pytest.raises(VerificationInputError):
        v.verify(_submission(c, "run_dup_0002", terminal=[t1, t2]))


def test_input_unknown_event_kind_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    claim = _bound_terminal(c, "run_kind_0001", kind="backend.finished")   # 非 16E 词表
    with pytest.raises(VerificationInputError):
        IndependentVerifier(c).verify(_submission(c, "run_kind_0001", terminal=[claim]))


def test_input_non_mapping_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    with pytest.raises(VerificationInputError):
        IndependentVerifier(c).verify(["not", "a", "mapping"])


def test_input_count_bounds_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    from furina.agent.verification import MAX_EVIDENCE_EVENTS
    c = _contract(work_real)
    v = IndependentVerifier(c)
    claims = [_bound_terminal(c, "run_cnt_0001", event_id=f"lev_1_{i:08x}")
              for i in range(MAX_EVIDENCE_EVENTS + 1)]
    with pytest.raises(VerificationInputError):
        v.verify(_submission(c, "run_cnt_0001", terminal=claims))


# ================================================================
# defensive-copy / 冻结 / 导出零共享引用 / 有界
# ================================================================


def test_input_defensively_copied_then_frozen(env):
    """解析后冻结：报告生成后原地篡改输入，不影响既有报告，且新评估如实反映新值。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    content = b"stable content"
    art.write_bytes(content)
    c = _contract(work_real)
    v = IndependentVerifier(c)
    sub = _submission(c, "run_freeze_0001",
                      declared=[_declared(art, sha_hex=_sha(content))])
    rep1 = v.verify(sub)
    assert rep1.verdict is VerificationVerdict.VERIFIED
    # 原地篡改提交（调用方仍持有引用）
    sub["declared_artifacts"][0]["declared_sha256"] = "0" * 64
    sub["terminal_events"][0]["kind"] = "backend.failed"
    assert rep1.verdict is VerificationVerdict.VERIFIED          # 既有报告不受影响
    assert v.seal_is_authentic(rep1) is True
    rep2 = v.verify(_submission(c, "run_freeze_0002",
                                declared=[_declared(art, sha_hex="0" * 64)]))
    assert rep2.verdict is VerificationVerdict.FAILED            # 新评估如实反映新值
    assert rep2.report_digest != rep1.report_digest


def test_evidence_bundle_and_checks_immutable(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    rep = IndependentVerifier(c).verify(_submission(c, "run_imm_0001"))
    assert isinstance(rep.evidence.artifacts, tuple)
    assert isinstance(rep.checks, tuple)
    assert isinstance(rep.evidence.terminal, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rep.evidence.contract_id = "wc_hack"
    with pytest.raises(dataclasses.FrozenInstanceError):
        rep.checks[0].result = CheckResult.PASS


def test_export_zero_shared_references(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    rep = IndependentVerifier(c).verify(_submission(c, "run_export_0001"))
    d1 = rep.to_dict()
    d1["checks"][0]["explanation"] = "TAMPERED"
    d1["diagnostics"].append("TAMPERED")
    assert rep.checks[0].explanation != "TAMPERED"
    d2 = rep.to_dict()
    assert d2["checks"][0]["explanation"] != "TAMPERED"
    assert "TAMPERED" not in rep.to_json()
    assert d1["checks"] is not d2["checks"]


def test_long_input_values_bounded(env):
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    c = _contract(work_real, artifact_expectations=(
        ArtifactExpectation(artifact_id="summary_doc", artifact_type="markdown_document",
                            expected_path=str(art), required=True),
    ))
    v = IndependentVerifier(c)
    long_path = str(work_real / ("y" * 600) / "elsewhere.md")
    sub = _submission(c, "run_long_0001",
                      declared=[_declared(long_path, artifact_id="summary_doc")])
    rep = v.verify(sub)
    for ch in rep.checks:
        assert len(ch.explanation) <= MAX_EXPLANATION_CHARS + 20
        for _k, val in ch.inputs:
            assert len(val) <= 512 + 20


def test_secret_shapes_scrubbed_from_check_text(env):
    """判据/声明输入中携带秘密值形态时，检查文本一律 [REDACTED]（秘密不存储/不导出）。"""
    from furina.agent.verification import scrub_secrets
    text = "password=hunter2 token=ghp_abcdef1234567890 authorization: Bearer xyz"
    scrubbed = scrub_secrets(text)
    assert "hunter2" not in scrubbed and "ghp_abcdef" not in scrubbed and "xyz" not in scrubbed


# ================================================================
# repair 身份 / 无扩权
# ================================================================


def test_repair_distinct_attempt_and_run_ids_and_collect_args(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=3))
    v = IndependentVerifier(c)
    calls = []

    def collector(attempt_id, run_id):
        calls.append((attempt_id, run_id))
        return _submission(c, run_id,
                           declared=[_declared(work_real / "ghost.md",
                                               artifact_id=f"m{len(calls):02d}")])

    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector).run()
    assert len(calls) == 3
    attempt_ids = [a for a, _ in calls]
    run_ids = [r for _, r in calls]
    assert len(set(attempt_ids)) == 3 and len(set(run_ids)) == 3
    assert all(a.startswith("att_") for a in attempt_ids)
    # collect 只收到 (attempt_id, run_id)——无契约引用，结构上不可扩权
    assert all(isinstance(a, str) and isinstance(r, str) for a, r in calls)


def test_run_id_factory_duplicate_rejected(env):
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    with pytest.raises(VerificationError):
        BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                          collect_evidence=lambda a, r: _submission(c, r),
                          run_id_factory=lambda attempt_id: "run_same_id").run()


def test_process_timeout_fail(env):
    tmp, work, work_real, outside, outside_real = env
    py = sys.executable
    c = _contract(work_real, contract_id="wc_16f_ptimeout_0001",
                  verification_standard=VerificationStandard(criteria=(
                      VerificationCriterion(criterion_id="slow", kind="process_exit_zero",
                                            params={"command":
                                                    f'"{py}" -c "import time; time.sleep(5)"'}),
                  )))
    v = IndependentVerifier(c, process_timeout_seconds=0.5)
    rep = v.verify(_submission(c, "run_pto_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("process_timeout" in ch.explanation for ch in rep.checks)


def test_optional_artifact_absent_still_verifies(env):
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"ok")
    c = _contract(work_real, contract_id="wc_16f_opt_0001",
                  artifact_expectations=(
                      ArtifactExpectation(artifact_id="optional_extra",
                                          artifact_type="plain_text",
                                          expected_path=str(work_real / "extra.txt"),
                                          required=False),
                  ))
    rep = IndependentVerifier(c).verify(_submission(c, "run_opt_0001"))
    assert rep.verdict is VerificationVerdict.VERIFIED


# ================================================================
# Reviewer Patch 1 — B1: substantive verification gate
# ================================================================


def _content_contract(work_real: Path, cid: str, *, expectations=(), criteria=()):
    return _contract(work_real, contract_id=cid,
                     artifact_expectations=tuple(expectations),
                     verification_standard=VerificationStandard(
                         criteria=tuple(criteria), verifier_refs=(VERIFIER_ID,)))


def test_ref_only_all_pass_without_substantive_is_inconclusive(env):
    """B1 否证：criteria=() + artifact_expectations=() + verifier_refs=(VERIFIER_ID,)
    + backend.completed —— terminal claim / allowlist / verifier_ref 全 PASS，
    但零 substantive deterministic check → INCONCLUSIVE / seal=""。"""
    tmp, work, work_real, outside, outside_real = env
    c = _content_contract(work_real, "wc_16f_subst_0001")
    v = IndependentVerifier(c)
    rep = v.verify(_submission(c, "run_subst_0001"))
    results = {ch.check_id: ch.result for ch in rep.checks}
    assert results["evidence:terminal_claim"] is CheckResult.PASS
    assert results["evidence:backend_authorized"] is CheckResult.PASS
    assert results[f"evidence:verifier_ref:{VERIFIER_ID}"] is CheckResult.PASS
    assert rep.verdict is VerificationVerdict.INCONCLUSIVE
    assert rep.authority_seal == ""
    assert v.seal_is_authentic(rep) is False
    assert any("no_substantive_deterministic_check" in d for d in rep.diagnostics)


def test_declared_artifact_alone_is_not_substantive(env):
    """B1 否证补充：backend 声明 artifact 本地核对全 PASS 也不构成 substantive
    成功证据（契约无判据、无 required 期望 → INCONCLUSIVE）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _content_contract(work_real, "wc_16f_subst_0002")
    content = b"declared only, no contract anchor"
    art = work_real / "only.md"
    art.write_bytes(content)
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_subst_0002", declared=[_declared(art, sha_hex=_sha(content))]))
    assert rep.verdict is VerificationVerdict.INCONCLUSIVE
    assert rep.authority_seal == ""


# ================================================================
# Reviewer Patch 1 — B2: MIME / content / artifact_type
# ================================================================

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 24
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 24 + b"\xff\xd9"
PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + b"0" * 32


def test_text_bytes_png_suffix_declared_image_png_fail(env):
    """B2 否证：文本 bytes + .png 后缀 + 声明 image/png → FAIL（内容识别真值）。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "blob.png"
    art.write_bytes(b"plain text bytes, definitely not an image")
    c = _content_contract(work_real, "wc_16f_mime_png_0001")
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_mimepng_0001", declared=[_declared(art, mime="image/png")]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    fails = " ".join(ch.explanation for ch in rep.checks if ch.result is CheckResult.FAIL)
    assert "declared_mime_mismatch" in fails or "suffix_mime_mismatch" in fails


def test_png_bytes_jpg_suffix_declared_image_jpeg_fail(env):
    """B2 否证：PNG bytes + .jpg 后缀 + 声明 image/jpeg → FAIL（同族冒充被
    精确相等拦截）。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "img.jpg"
    art.write_bytes(PNG_BYTES)
    c = _content_contract(work_real, "wc_16f_mime_jpg_0001")
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_mimejpg_0001", declared=[_declared(art, mime="image/jpeg")]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    fails = " ".join(ch.explanation for ch in rep.checks if ch.result is CheckResult.FAIL)
    assert "suffix_mime_mismatch" in fails and "declared_mime_mismatch" in fails


def test_unknown_suffix_no_declared_mime_fail(env):
    """B2 否证：未知后缀 + 无声明 MIME → FAIL（命名不可观察 fail-closed）。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.xyz"
    art.write_bytes(b"text content")
    c = _content_contract(work_real, "wc_16f_mime_xyz_0001")
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_mimexyz_0001", declared=[_declared(art)]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("unknown_artifact_suffix" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


def test_artifact_type_png_with_non_png_content_fail(env):
    """B2 否证：artifact_type=png_image + 非 PNG 内容 → FAIL（封闭类型规则）。"""
    tmp, work, work_real, outside, outside_real = env
    exp = ArtifactExpectation(artifact_id="pic", artifact_type="png_image",
                              expected_path=str(work_real / "pic.png"), required=True)
    (work_real / "pic.png").write_bytes(b"not a png at all")
    c = _content_contract(work_real, "wc_16f_atype_0001", expectations=(exp,))
    rep = IndependentVerifier(c).verify(_submission(c, "run_atype_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("artifact_type_mime_mismatch" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


def test_unknown_artifact_type_fail_closed(env):
    """B2 否证：未知 artifact_type 绝不静默通过（16F 封闭表之外 → required FAIL）。"""
    tmp, work, work_real, outside, outside_real = env
    exp = ArtifactExpectation(artifact_id="doc", artifact_type="spreadsheet_v2",
                              expected_path=str(work_real / "doc.txt"), required=True)
    (work_real / "doc.txt").write_bytes(b"hello")
    c = _content_contract(work_real, "wc_16f_atype_unk_0001", expectations=(exp,))
    rep = IndependentVerifier(c).verify(_submission(c, "run_atypeunk_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("unknown_artifact_type" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


def test_binary_content_requires_explicit_acceptance(env):
    """B2 否证：binary 内容在 declared 侧无显式 octet-stream 声明 → FAIL。"""
    tmp, work, work_real, outside, outside_real = env
    content = b"\x00\x01binary\x00payload"
    art = work_real / "blob.bin"
    art.write_bytes(content)
    c = _content_contract(work_real, "wc_16f_bin_0001")
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_bin_0001", declared=[_declared(art, sha_hex=_sha(content))]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("binary_content_requires_explicit_type" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


def test_binary_content_accepted_with_explicit_octet_stream(env):
    """B2 正例：binary 内容 + 显式 application/octet-stream 声明 + 契约判据
    → 全部 PASS 且 VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    content = b"\x00\x01binary\x00payload"
    art = work_real / "blob.bin"
    art.write_bytes(content)
    c = _content_contract(work_real, "wc_16f_bin_ok_0001", criteria=(
        VerificationCriterion(criterion_id="bin_exists", kind="artifact_file_exists",
                              params={"path": str(art)}),
    ))
    v = IndependentVerifier(c)
    rep = v.verify(_submission(
        c, "run_binok_0001",
        declared=[_declared(art, sha_hex=_sha(content), mime="application/octet-stream")]))
    assert rep.verdict is VerificationVerdict.VERIFIED
    assert v.seal_is_authentic(rep) is True


@pytest.mark.parametrize("name,content,mime,atype", [
    ("note.txt", b"hello world", "text/plain", "plain_text"),
    ("note.md", b"# title\ntext", "text/markdown", "markdown_document"),
    ("data.json", b'{"k": 1}', "application/json", "json_data"),
    ("doc.pdf", PDF_BYTES, "application/pdf", "pdf_document"),
    ("pic.png", PNG_BYTES, "image/png", "png_image"),
    ("pic.jpg", JPEG_BYTES, "image/jpeg", "jpeg_image"),
])
def test_valid_content_mime_positive_cases(env, name, content, mime, atype):
    """B2 正例：合法 PNG/JPEG/PDF/JSON/text 内容 + 一致命名/声明/类型 → VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / name
    art.write_bytes(content)
    exp = ArtifactExpectation(artifact_id="prod", artifact_type=atype,
                              expected_path=str(art), required=True)
    c = _content_contract(work_real, f"wc_16f_pos_{atype}_0001", expectations=(exp,))
    v = IndependentVerifier(c)
    rep = v.verify(_submission(
        c, f"run_pos_{atype}_0001",
        declared=[_declared(art, sha_hex=_sha(content), mime=mime)]))
    assert rep.verdict is VerificationVerdict.VERIFIED
    assert rep.authority_seal and v.seal_is_authentic(rep) is True


# ================================================================
# Reviewer Patch 1 — B3: optional artifact 语义
# ================================================================


def test_optional_artifact_path_escape_is_required_fail(env):
    """B3 否证：optional artifact 一旦存在但 symlink/junction 逃逸 →
    required FAIL → FAILED（16A 契约层本身禁止期望路径逃逸，逃逸只可能
    经运行期链接发生——realpath 真相先于存在性）。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    (outside_real / "f.txt").write_bytes(b"escaped optional artifact")
    link = work / "opt_link"
    if not _make_dir_link(link, outside):
        pytest.skip("symlink/junction 在本机不可用")
    exp = ArtifactExpectation(artifact_id="optional_extra", artifact_type="plain_text",
                              expected_path=str(work_real / "opt_link"),
                              required=False)
    c = _contract(work_real, contract_id="wc_16f_optesc_0001",
                  artifact_expectations=(exp,))
    rep = IndependentVerifier(c).verify(_submission(c, "run_optesc_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    assert any(ch.required and ch.result is CheckResult.FAIL
               and "path_escape" in ch.explanation for ch in rep.checks)


def test_optional_artifact_oversize_is_required_fail(env):
    """B3 否证：optional artifact 存在但 oversize → required FAIL → FAILED。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    (work_real / "extra.txt").write_bytes(b"word " * (MAX_ARTIFACT_BYTES // 4))
    exp = ArtifactExpectation(artifact_id="optional_extra", artifact_type="plain_text",
                              expected_path=str(work_real / "extra.txt"), required=False)
    c = _contract(work_real, contract_id="wc_16f_optbig_0001",
                  artifact_expectations=(exp,))
    rep = IndependentVerifier(c).verify(_submission(c, "run_optbig_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    assert any(ch.required and ch.result is CheckResult.FAIL
               and "artifact_oversize" in ch.explanation for ch in rep.checks)


def test_optional_artifact_declared_hash_contradiction_is_required_fail(env):
    """B3 否证：optional artifact 存在且声明 hash 矛盾 → required FAIL → FAILED。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    extra = work_real / "extra.txt"
    extra.write_bytes(b"real content on disk")
    exp = ArtifactExpectation(artifact_id="optional_extra", artifact_type="plain_text",
                              expected_path=str(extra), required=False)
    c = _contract(work_real, contract_id="wc_16f_opthash_0001",
                  artifact_expectations=(exp,))
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_opthash_0001",
        declared=[_declared(extra, sha_hex=_sha(b"claimed-but-false"),
                            artifact_id="optional_extra")]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("declared_hash_mismatch_artifact_tampered" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


def test_optional_artifact_unsupported_mime_is_required_fail(env):
    """B3 否证：optional artifact 存在且声明 MIME 不在白名单 → required FAIL。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    extra = work_real / "extra.txt"
    extra.write_bytes(b"plain")
    exp = ArtifactExpectation(artifact_id="optional_extra", artifact_type="plain_text",
                              expected_path=str(extra), required=False)
    c = _contract(work_real, contract_id="wc_16f_optmime_0001",
                  artifact_expectations=(exp,))
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_optmime_0001",
        declared=[_declared(extra, mime="application/x-unknown-vendor",
                            artifact_id="optional_extra")]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert any("unsupported_mime" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


# ================================================================
# Reviewer Patch 1 — B4: repair 边界复核 / 严格 cost meter
# ================================================================


def _verified_run_contract(work_real: Path, cid: str):
    (work_real / "summary.md").write_bytes(b"ok")
    return _contract(work_real, contract_id=cid, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))


def test_mid_attempt_cancellation_blocks_verified(env):
    """B4 否证：attempt 中出现 cancellation → CANCELLED；越界后的 VERIFIED
    report 不得成为成功结果（final_report=None）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_run_contract(work_real, "wc_16f_b4cancel_0001")
    v = IndependentVerifier(c)
    art = work_real / "summary.md"
    flags = {"cancelled": False}

    def collector(attempt_id, run_id):
        flags["cancelled"] = True          # collect/verify 期间出现取消
        return _submission(c, run_id, declared=[_declared(art, sha_hex=_sha(b"ok"))])

    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector,
                            cancel_requested=lambda: flags["cancelled"]).run()
    assert out.attempts[0].verdict == "VERIFIED"      # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.CANCELLED
    assert out.final_report is None                   # 绝不作为成功结果
    assert len(out.attempts) == 1


def test_post_attempt_cost_overrun_blocks_verified(env):
    """B4 否证：attempt 完成后 used > limit → BUDGET_EXHAUSTED，VERIFIED
    report 不成为成功结果。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_run_contract(work_real, "wc_16f_b4cost_0001")
    v = IndependentVerifier(c)
    art = work_real / "summary.md"
    calls = {"n": 0}

    def cost_used():
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else 6.0        # 完成后计量超 5.0 上限

    out = BoundedRepairLoop(
        contract=c, verifier=v,
        collect_evidence=lambda a, r: _submission(
            c, r, declared=[_declared(art, sha_hex=_sha(b"ok"))]),
        cost_used=cost_used).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out.final_report is None
    assert len(out.attempts) == 1


def test_post_attempt_deadline_blocks_verified(env):
    """B4 否证：完成时间 > deadline → TIMEOUT，VERIFIED report 不成为成功结果。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    c = _contract(work_real, contract_id="wc_16f_b4time_0001", budget=ExecutionBudget(
        max_duration_seconds=500.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    clock = FakeClock(1000.0)
    v = IndependentVerifier(c, now_fn=clock)
    art = work_real / "summary.md"

    def collector(attempt_id, run_id):
        clock.advance(600.0)               # attempt 完成时刻 1600 > deadline 1500
        return _submission(c, run_id, declared=[_declared(art, sha_hex=_sha(b"ok"))])

    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector,
                            now_fn=clock).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.TIMEOUT
    assert out.final_report is None


@pytest.mark.parametrize("bad", [True, "6.0", float("nan"), float("inf"),
                                 float("-inf"), -1.0])
def test_cost_meter_invalid_values_fail_closed(env, bad):
    """B4 否证：meter bool/str/NaN/Inf/负数 → fail-closed（BUDGET_EXHAUSTED，
    零 collect 零 attempt，零误判）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_run_contract(work_real, "wc_16f_b4meter_0001")
    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _submission(c, r),
        cost_used=lambda: bad).run()
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert len(out.attempts) == 0
    assert out.diagnostic.startswith("cost_meter")


def test_cost_meter_exception_fail_closed(env):
    tmp, work, work_real, outside, outside_real = env
    c = _verified_run_contract(work_real, "wc_16f_b4meterx_0001")

    def boom():
        raise RuntimeError("meter exploded")

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=lambda a, r: _submission(c, r),
                            cost_used=boom).run()
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert len(out.attempts) == 0
    assert "cost_meter_error" in out.diagnostic


def test_cost_meter_at_limit_pre_attempt_zero_collect(env):
    """B4 否证：attempt 启动前 used >= limit → 零 collect（0 attempt）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_run_contract(work_real, "wc_16f_b4pre_0001")
    ran = {"n": 0}

    def collector(attempt_id, run_id):
        ran["n"] += 1
        return _submission(c, run_id)

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=collector,
                            cost_used=lambda: 5.0).run()
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert len(out.attempts) == 0 and ran["n"] == 0


# ================================================================
# Reviewer Patch 1 — B5: process output 真正有界
# ================================================================


def test_process_output_devnull_not_aggregated(env, monkeypatch):
    """B5 否证：stdout/stderr/stdin 一律 DEVNULL（源面锁定）；8MB+ 输出零聚合、
    输出内容（含 marker）绝不进入 report/诊断。"""
    import subprocess as sp
    from furina.agent.verification import checks as vchecks
    tmp, work, work_real, outside, outside_real = env
    seen = {}
    real_popen = sp.Popen

    def spy_popen(*args, **kwargs):
        seen["stdin"] = kwargs.get("stdin")
        seen["stdout"] = kwargs.get("stdout")
        seen["stderr"] = kwargs.get("stderr")
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(vchecks.subprocess, "Popen", spy_popen)
    py = sys.executable
    out_marker = "OUTP16FMARK"     # 拼接构造——字面量不出现在命令里，只出现在输出里
    command = (f'"{py}" -c "import sys; sys.stdout.write(\'x\'*(8*1024*1024)); '
               f"sys.stderr.write('y'*(4*1024*1024)); "
               f"sys.stdout.write('OUT'+'P16F'+'MARK')\"")
    c = _contract(work_real, contract_id="wc_16f_b5devnull_0001",
                  verification_standard=VerificationStandard(criteria=(
                      VerificationCriterion(criterion_id="loud", kind="process_exit_zero",
                                            params={"command": command}),
                  )))
    rep = IndependentVerifier(c).verify(_submission(c, "run_b5_0001"))
    assert seen["stdout"] is sp.DEVNULL and seen["stderr"] is sp.DEVNULL \
        and seen["stdin"] is sp.DEVNULL
    assert rep.verdict is VerificationVerdict.VERIFIED        # exit code 判定保持正确
    blob = rep.to_json()
    assert out_marker not in blob and "xxxx" not in blob and "yyyy" not in blob


def test_process_timeout_terminates_process_tree(env):
    """B5 否证：timeout 后进程树（cmd shell + python 子进程）被可靠终止。"""
    import subprocess as sp
    from furina.agent.verification import run_process_bounded
    py = sys.executable
    marker = "P16F_KILL_MARKER_16f"
    command = f'"{py}" -c "import time; time.sleep(60)  #{marker}"'
    t0 = time.monotonic()
    rc, timed_out, rejection = run_process_bounded(command, None, 0.5)
    elapsed = time.monotonic() - t0
    assert timed_out is True and rc is None and rejection == ""
    assert elapsed < 30                        # 有界返回（不等待 60s sleeper）

    ps_script = (f'@(Get-CimInstance Win32_Process | '
                 f'Where-Object {{ $_.CommandLine -like "*{marker}*" '
                 f'-and $_.Name -ne "powershell.exe" }}).Count')

    def marker_count():
        try:
            out = sp.run(["powershell", "-NoProfile", "-Command", ps_script],
                         capture_output=True, text=True, timeout=60)
        except (OSError, sp.TimeoutExpired):
            return None
        try:
            return int(out.stdout.strip() or "0")
        except ValueError:
            return None

    deadline = time.monotonic() + 30
    count = marker_count()
    while time.monotonic() < deadline and count:
        time.sleep(0.5)
        count = marker_count()
    if count is None:
        pytest.skip("PowerShell 进程枚举不可用")
    assert count == 0


# ================================================================
# Reviewer Patch 1 — B6: secret boundary
# ================================================================


def test_hard_failure_message_scrubbed(env):
    """B6 否证：HardBackendFailure 消息中的秘密形态在 AttemptRecord/Outcome
    诊断面被 [REDACTED]。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)

    def collector(attempt_id, run_id):
        raise HardBackendFailure("runtime crashed with token=supersecret12345")

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=collector).run()
    assert out.stop_reason is RepairStopReason.HARD_FAILURE
    assert "supersecret12345" not in out.attempts[0].diagnostic
    assert "supersecret12345" not in out.diagnostic
    assert "[REDACTED]" in out.attempts[0].diagnostic


def test_approval_denial_message_scrubbed(env):
    """B6 否证：approval authority 返回值携带秘密形态 → 停止诊断脱敏。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _submission(c, r),
        approval_authority=lambda a, r: "deny password=hunter2secret").run()
    assert out.stop_reason is RepairStopReason.APPROVAL_DENIED
    assert "hunter2secret" not in out.diagnostic


def test_secret_shaped_artifact_path_rejected(env):
    """B6 否证：秘密形态 artifact path → VerificationInputError（零报告零 seal）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    evil = str(work_real / "password=hunter2.md")
    with pytest.raises(VerificationInputError):
        IndependentVerifier(c).verify(_submission(
            c, "run_secretpath_0001", declared=[_declared(evil)]))


# ================================================================
# Reviewer Patch 1 — B7: stable artifact snapshot
# ================================================================


def test_artifact_mutated_during_verification_fails(env, monkeypatch):
    """B7 否证：验证期间文件增长（size 漂移）→ artifact_mutated_during_
    verification → FAIL / seal=""，绝不 VERIFIED。"""
    content = b"stable content before mutation"
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(content)
    c = _contract(work_real)
    real_open = builtins.open
    target = str(art)

    class _MutateOnFirstRead:
        """在读路径上于前后 fstat 之间注入追加写（确定性变异注入器）。"""

        def __init__(self, handle):
            self._h = handle
            self._done = False

        def fileno(self):
            return self._h.fileno()

        def read(self, size=-1):
            data = self._h.read(size)
            if not self._done:
                self._done = True
                with real_open(target, "ab") as g:
                    g.write(b"-MUTATED-DURING-VERIFY")
            return data

        def __enter__(self):
            self._h.__enter__()
            return self

        def __exit__(self, *exc):
            return self._h.__exit__(*exc)

    def mutating_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        if "rb" in str(mode) and os.path.realpath(str(file)) == os.path.realpath(target):
            return _MutateOnFirstRead(handle)
        return handle

    monkeypatch.setattr(builtins, "open", mutating_open)
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_mut_0001", declared=[_declared(art, sha_hex=_sha(content))]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    assert any("artifact_mutated_during_verification" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


def test_criterion_text_window_oversize_artifact_fails(env):
    """B7 否证：criterion-only 文件也受 MAX_ARTIFACT_BYTES 上限——大文件不能
    靠前 1MiB 窗口命中 needle 而 PASS。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"NEEDLE_16F" + b"\x00" * (MAX_ARTIFACT_BYTES + 1))
    c = _contract(work_real, contract_id="wc_16f_bigwin_0001",
                  verification_standard=VerificationStandard(criteria=(
                      VerificationCriterion(criterion_id="win", kind="text_contains",
                                            params={"path": str(art),
                                                    "needle": "NEEDLE_16F"}),
                  )))
    rep = IndependentVerifier(c).verify(_submission(c, "run_bigwin_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    assert any("artifact_oversize" in ch.explanation
               for ch in rep.checks if ch.result is CheckResult.FAIL)


# ================================================================
# Reviewer Patch 1 — B8: canonical identity
# ================================================================


def test_identity_whitespace_and_control_chars_rejected(env):
    """B8 否证：首尾空白（不静默 trim）/控制字符身份 → VerificationInputError
    （零报告零 seal）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    bad = []
    s1 = _submission(c, "run_ok_0001")
    s1["run_id"] = " run_x "
    bad.append(s1)
    s2 = _submission(c, "run_ok_0002")
    s2["backend_id"] = " backend "
    bad.append(s2)
    s3 = _submission(c, "run_ok_0003")
    s3["run_id"] = "run_x\ttab"
    bad.append(s3)
    s4 = _submission(c, "run_ok_0004")
    t4 = _bound_terminal(c, "run_ok_0004")
    t4["event_id"] = "lev_1\nlinefeed"
    s4["terminal_events"] = [t4]
    bad.append(s4)
    s5 = _submission(c, "run_ok_0005",
                     declared=[_declared(work_real / "ghost.md")])
    s5["declared_artifacts"][0]["artifact_id"] = " summary_doc"
    bad.append(s5)
    for s in bad:
        with pytest.raises(VerificationInputError):
            v.verify(s)


def test_secret_shaped_identity_rejected(env):
    """B8 否证：词法合法但带秘密形态的身份（KV/授权形态）→ fail-closed，
    绝不用两个不同秘密值清洗成同一身份后继续 VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    s = _submission(c, "password:hunter2")          # 词法合法但秘密形态
    with pytest.raises(VerificationInputError):
        v.verify(s)
    s2 = _submission(c, "run_ok_0009")
    t2 = _bound_terminal(c, "run_ok_0009")
    t2["backend_id"] = "api_key:sk-abc123"
    s2["terminal_events"] = [t2]
    with pytest.raises(VerificationInputError):
        v.verify(s2)
