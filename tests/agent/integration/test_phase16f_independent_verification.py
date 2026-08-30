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

Reviewer Patch 2 否证（7 组 blocker，reviewer-locked，P2-A..P2-T）：
B1 完整内容真实性：malformed JSON（合法前导）/ 前导垃圾后 %PDF / sniff 窗口
   后 NUL/二进制尾 / 空 required / unreadable required / 截断 PNG·JPEG·PDF
   一律 required FAIL；六类合法内容正例；optional 存在即完整检查；
B2 artifact_type 策略 API 层不可变（mutation 不可能且事后策略事实不变）；
B3 句柄锚定 containment：symlink/junction 交换（含 declared 与 criterion-only
   两条路径）不能逃逸；
B4 RepairLoop 只接受当前验证器真实报告：foreign signer / 陈旧 run /
   异 contract 报告 → REPORT_REJECTED / final_report=None；
B5 全部外部回调后新鲜状态复核：factory 期间取消/超时/成本耗尽阻止 collect；
   cost 回调推进时钟阻止 VERIFIED；
B6 canonical identity 统一：嵌入下划线秘密身份拒绝；秘密 run_id_factory
   输出绝不存储；
B7 regex 隔离 worker 硬超时；detached 后代无法存活（或平台 fail-closed）。

Reviewer Patch 3 否证（6 组 blocker，reviewer-locked，P3-A..P3-L）：
B1 PDF 真实封闭结构：伪 PDF（marker+%%EOF 无结构）/ 错误 startxref / 截断
   xref / trailer 缺 Root / xref 条目偏移造假 一律拒绝；合法最小 PDF（真实
   xref 表 + startxref 偏移）必须 PASS（夹具升级为自洽最小 PDF）；
B2 单路径单快照：同一路径 expectation/declared/exists/text 只打开一次；
   criterion-only 文件完整读取（≤8MiB）+ 整体合法文本证明（NUL 尾 FAIL）；
   空/超界 artifact_file_exists FAIL；JSON 快照后换纯文本拼接攻击被缓存阻断；
B3 接受 VERIFIED 前最终稳定边界：接受门后 ≥2 轮完整安全扫描
   （hash→cost→cancel→新鲜时间），cancellation 改 cost / cost 推时钟 /
   seal 认证翻取消 / standard_hash 推 deadline / 回调异常 → 全部
   final_report=None（BUDGET_EXHAUSTED/TIMEOUT/CANCELLED/UNSTABLE_BOUNDARY）；
B4 POSIX regex worker start_new_session + pgid 归属守卫：timeout 后 worker
   必死、宿主进程组必活；stdout/stderr DEVNULL、输入有界；
B5 公开模型身份验证：TerminalObservation/ArtifactObservation/EvidenceBundle/
   VerificationReport 直接构造秘密形态身份拒绝；秘密路径异常回显脱敏
   （禁止 {path!r} 原文）；
B6 安全测试禁止 skip：PowerShell 枚举不可用 → FAIL（P2-T/进程树终止测试），
   process 证明不可用 → fail-closed NOT_EVALUABLE（绝不 skip/best-effort）。
"""

import base64
import builtins
import dataclasses
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
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
    MAX_REPORT_CHECKS,
    MAX_REPORT_JSON_BYTES,
    MAX_TEXT_READ_BYTES,
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
        # Patch 2：预检现在在身份分配后复核两次（0.0 × 2），attempt 完成后的
        # 后置复核读到 6.0 > 5.0 上限 → BUDGET_EXHAUSTED，零 further collect。
        return 0.0 if calls["n"] <= 2 else 6.0

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
        # Patch 2：预检在身份分配后复核——前两次预检（attempt 1 前）为 False，
        # 第三次复核（attempt 1 完成后的后置边界）起为 True → 第 2 次 attempt
        # 被取消阻止，恰好 1 个 attempt。
        return flags["checked"] > 2

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

# 结构合法的最小图像/PDF 夹具（Patch 2 blocker B1：内容必须通过确定性结构
# 验证——PNG/JPEG 经 Pillow verify+load；PDF 需真实封闭结构）。
# Patch 3 B1：PDF 夹具升级为含真实 xref 表 + startxref 偏移 + trailer
# （/Size,/Root）+ %%EOF 的自洽最小 PDF——偏移关系程序化计算，杜绝手算漂移。
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC")
JPEG_BYTES = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDo6KKK/nk/lQ//2Q==")


def _minimal_pdf() -> bytes:
    """结构合法的最小 PDF（Patch 3 B1）：header + 对象 + 真实 xref 表 +
    startxref 偏移 + trailer(/Size,/Root) + %%EOF——所有偏移关系程序化自洽。"""
    parts = [b"%PDF-1.4\n"]
    offsets: dict = {}

    def add_obj(num: int, body: bytes) -> None:
        offsets[num] = sum(len(p) for p in parts)
        parts.append(b"%d 0 obj\n" % num)
        parts.append(body)
        parts.append(b"endobj\n")

    add_obj(1, b"<</Type/Catalog/Pages 2 0 R>>\n")
    add_obj(2, b"<</Type/Pages/Kids[3 0 R]/Count 1>>\n")
    add_obj(3, b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>\n")
    xref_pos = sum(len(p) for p in parts)
    parts.append(b"xref\n0 4\n")
    for num in (0, 1, 2, 3):
        if num == 0:
            parts.append(b"%010d 65535 f \n" % 0)
        else:
            parts.append(b"%010d 00000 n \n" % offsets[num])
    parts.append(b"trailer\n<</Size 4/Root 1 0 R>>\n")
    parts.append(b"startxref\n%d\n" % xref_pos)
    parts.append(b"%%EOF\n")
    return b"".join(parts)


PDF_BYTES = _minimal_pdf()


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
        # Patch 2：前两次预检（0.0×2）允许 attempt 执行；attempt 完成后的
        # 后置边界复核读到 6.0 > 5.0 上限 → BUDGET_EXHAUSTED，VERIFIED
        # report 不成为成功结果。
        return 0.0 if calls["n"] <= 2 else 6.0

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
    # Patch 3 B6：枚举/证明能力不可用时测试必须 FAIL，不得 SKIP。
    assert count is not None, "PowerShell 进程枚举不可用——枚举能力缺失必须 FAIL（不得 SKIP）"
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

        def close(self):
            return self._h.close()

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


# ================================================================
# Reviewer Patch 2 — B1: 完整内容真实性（P2-A..P2-H）
# ================================================================

TRUNC_JSON = b'{"k": 1,'                       # 合法前导 + 截断
TRAILING_JSON = b'{"k": 1} trailing garbage'   # 完整 JSON + 尾随垃圾
LEAD_JUNK_PDF = b"plain notes then %PDF-1.7\n%%EOF\n"   # marker 非偏移 0


def _expectation_contract(work_real: Path, cid: str, *, atype: str, path: Path,
                          required: bool = True, criteria=()):
    exp = ArtifactExpectation(artifact_id="prod_doc", artifact_type=atype,
                              expected_path=str(path), required=required)
    return _content_contract(work_real, cid, expectations=(exp,), criteria=criteria)


def test_p2_a_malformed_json_with_valid_lead_fails(env):
    """P2-A 否证：JSON 合法前导 { 后语法错误/截断/尾随垃圾 → FAIL（完整解析）。"""
    tmp, work, work_real, outside, outside_real = env
    for tag, blob in (("trunc", TRUNC_JSON), ("garbage", TRAILING_JSON)):
        art = work_real / "data.json"
        art.write_bytes(blob)
        c = _expectation_contract(work_real, f"wc_16f_p2a_{tag}_0001",
                                  atype="json_data", path=art)
        rep = IndependentVerifier(c).verify(_submission(
            c, f"run_p2a_{tag}_0001",
            declared=[_declared(art, sha_hex=_sha(blob), mime="application/json",
                                artifact_id="prod_doc")]))
        assert rep.verdict is VerificationVerdict.FAILED
        assert rep.authority_seal == ""
        assert any(ch.result is CheckResult.FAIL
                   and ch.explanation.startswith("malformed_content:json")
                   for ch in rep.checks), \
            [(ch.check_id, ch.explanation) for ch in rep.checks]


def test_p2_b_pdf_marker_after_leading_junk_fails(env):
    """P2-B 否证：任意窗口中出现 %PDF marker 不构成 PDF——前导垃圾 + marker
    → 内容判为 text/plain → 命名/类型/声明通道全部矛盾 FAIL。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "doc.pdf"
    art.write_bytes(LEAD_JUNK_PDF)
    exp = ArtifactExpectation(artifact_id="prod_doc", artifact_type="pdf_document",
                              expected_path=str(art), required=True)
    c = _content_contract(work_real, "wc_16f_p2b_0001", expectations=(exp,))
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_p2b_0001",
        declared=[_declared(art, sha_hex=_sha(LEAD_JUNK_PDF),
                            mime="application/pdf", artifact_id="prod_doc")]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    fails = " ".join(ch.explanation for ch in rep.checks if ch.result is CheckResult.FAIL)
    assert "suffix_mime_mismatch" in fails and "artifact_type_mime_mismatch" in fails \
        and "declared_mime_mismatch" in fails


def test_p2_c_binary_tail_after_sniff_window_fails(env):
    """P2-C 否证：前 1 KiB 是纯文本、其后才是 NUL/二进制 → FAIL（完整内容
    验证，前缀不得掩盖尾部）。"""
    tmp, work, work_real, outside, outside_real = env
    blob = b"lorem ipsum summary " * 80 + b"\x00\x01\x02binary\x00tail"
    assert len(blob) > 1024
    art = work_real / "note.txt"
    art.write_bytes(blob)
    c = _expectation_contract(work_real, "wc_16f_p2c_0001",
                              atype="plain_text", path=art)
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_p2c_0001",
        declared=[_declared(art, sha_hex=_sha(blob), mime="text/plain",
                            artifact_id="prod_doc")]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    fails = " ".join(ch.explanation for ch in rep.checks if ch.result is CheckResult.FAIL)
    assert "suffix_mime_mismatch" in fails and "declared_mime_mismatch" in fails


def test_p2_d_empty_required_artifact_fails(env):
    """P2-D 否证：空 required artifact → required FAIL artifact_empty（含
    binary_blob——空文件绝不是有效 binary artifact）。"""
    tmp, work, work_real, outside, outside_real = env
    for tag, atype, suffix in (("text", "plain_text", "note.txt"),
                               ("bin", "binary_blob", "blob.bin")):
        art = work_real / suffix
        art.write_bytes(b"")
        c = _expectation_contract(work_real, f"wc_16f_p2d_{tag}_0001",
                                  atype=atype, path=art)
        rep = IndependentVerifier(c).verify(_submission(c, f"run_p2d_{tag}_0001"))
        assert rep.verdict is VerificationVerdict.FAILED
        assert rep.authority_seal == ""
        assert any(ch.result is CheckResult.FAIL and ch.explanation == "artifact_empty"
                   for ch in rep.checks)


def _deny_reads_for(monkeypatch, target: Path) -> None:
    """POSIX 确定性 unreadable：对目标路径的只读 open 一律 PermissionError
    （advisory 锁不阻止读取；win32 测试走真实 msvcrt 区域锁）。"""
    real_open = builtins.open
    tgt = os.path.normcase(os.path.realpath(str(target)))

    def denying_open(file, mode="r", *a, **k):
        if "r" in str(mode) and os.path.normcase(os.path.realpath(str(file))) == tgt:
            raise PermissionError(13, "simulated unreadable (test)")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", denying_open)


@contextmanager
def _locked_unreadable(path: Path):
    """win32 确定性 unreadable：区域锁（LockFile 语义）使任何其他句柄读取
    PermissionError——生产真实 IO 失败路径，非模拟。"""
    import msvcrt
    size = max(os.path.getsize(path), 1)
    lock = open(path, "r+b")
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, size)
    try:
        yield
    finally:
        try:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, size)
        finally:
            lock.close()


def test_p2_e_unreadable_required_artifact_fails(env, monkeypatch):
    """P2-E 否证：required artifact unreadable → required FAIL artifact_
    unreadable——绝不跳过 MIME/hash/size 后让剩余检查通过（含声明 hash）。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"locked content")
    c = _expectation_contract(work_real, "wc_16f_p2e_0001",
                              atype="markdown_document", path=art)
    sub = _submission(c, "run_p2e_0001",
                      declared=[_declared(art, sha_hex=_sha(b"locked content"),
                                          mime="text/markdown",
                                          artifact_id="prod_doc")])
    if sys.platform == "win32":
        with _locked_unreadable(art):
            rep = IndependentVerifier(c).verify(sub)
    else:
        _deny_reads_for(monkeypatch, art)
        rep = IndependentVerifier(c).verify(sub)
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    assert any(ch.result is CheckResult.FAIL and ch.explanation == "artifact_unreadable"
               for ch in rep.checks)


@pytest.mark.parametrize("tag,atype,suffix,cut", [
    ("png", "png_image", "pic.png", 8),   # Pillow 容忍尾部 ≤4 字节截断——截到结构破坏
    ("jpeg", "jpeg_image", "pic.jpg", 10),
    ("pdf", "pdf_document", "doc.pdf", 6),
])
def test_p2_f_truncated_image_and_pdf_fail(env, tag, atype, suffix, cut):
    """P2-F 否证：截断 PNG/JPEG（Pillow verify+load）/ 截断 PDF（缺 %%EOF）
    一律 malformed FAIL——最短魔数绝不接受截断/畸形文件。"""
    tmp, work, work_real, outside, outside_real = env
    full = {"png": PNG_BYTES, "jpeg": JPEG_BYTES, "pdf": PDF_BYTES}[tag]
    blob = full[:-cut]
    art = work_real / suffix
    art.write_bytes(blob)
    c = _expectation_contract(work_real, f"wc_16f_p2f_{tag}_0001",
                              atype=atype, path=art)
    rep = IndependentVerifier(c).verify(_submission(
        c, f"run_p2f_{tag}_0001",
        declared=[_declared(art, sha_hex=_sha(blob), artifact_id="prod_doc")]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    assert any(ch.result is CheckResult.FAIL
               and ch.explanation.startswith("malformed_content:")
               for ch in rep.checks), \
        [(ch.check_id, ch.explanation) for ch in rep.checks]


@pytest.mark.parametrize("name,content,mime,atype", [
    ("note.txt", b"hello world", "text/plain", "plain_text"),
    ("note.md", b"# title\ntext", "text/markdown", "markdown_document"),
    ("data.json", b'{"k": 1}', "application/json", "json_data"),
    ("doc.pdf", PDF_BYTES, "application/pdf", "pdf_document"),
    ("pic.png", PNG_BYTES, "image/png", "png_image"),
    ("pic.jpg", JPEG_BYTES, "image/jpeg", "jpeg_image"),
])
def test_p2_g_valid_content_positive_controls(env, name, content, mime, atype):
    """P2-G 正例：六类合法内容（JSON/text/PDF/PNG/JPEG，完整结构验证通过）
    + 一致命名/声明/类型 → VERIFIED + 可认证 seal + content_rejection 为空。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / name
    art.write_bytes(content)
    c = _expectation_contract(work_real, f"wc_16f_p2g_{atype}_0001",
                              atype=atype, path=art)
    v = IndependentVerifier(c)
    rep = v.verify(_submission(
        c, f"run_p2g_{atype}_0001",
        declared=[_declared(art, sha_hex=_sha(content), mime=mime,
                            size=len(content), artifact_id="prod_doc")]))
    assert rep.verdict is VerificationVerdict.VERIFIED
    assert rep.authority_seal and v.seal_is_authentic(rep) is True
    obs = [a for a in rep.evidence.artifacts if a.artifact_id == "prod_doc"]
    assert obs and all(a.content_rejection == "" and a.rejection == "" for a in obs)


def test_p2_h_optional_existing_malformed_or_unreadable_fails(env, monkeypatch):
    """P2-H 否证：optional 只豁免"不存在"——存在但 malformed/unreadable 一律
    required FAIL；真正不存在仍 VERIFIED（对照）。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    # (a) optional 存在但 JSON 截断
    bad = work_real / "extra.json"
    bad.write_bytes(TRUNC_JSON)
    c = _expectation_contract(work_real, "wc_16f_p2h_a_0001", atype="json_data",
                              path=bad, required=False)
    rep = IndependentVerifier(c).verify(_submission(c, "run_p2h_a_0001"))
    assert rep.verdict is VerificationVerdict.FAILED and rep.authority_seal == ""
    assert any(ch.required and ch.result is CheckResult.FAIL
               and ch.explanation.startswith("malformed_content:")
               for ch in rep.checks)
    # (b) optional 存在但 unreadable
    lock_art = work_real / "extra2.txt"
    lock_art.write_bytes(b"locked optional")
    c2 = _expectation_contract(work_real, "wc_16f_p2h_b_0001", atype="plain_text",
                               path=lock_art, required=False)
    sub2 = _submission(c2, "run_p2h_b_0001")
    if sys.platform == "win32":
        with _locked_unreadable(lock_art):
            rep2 = IndependentVerifier(c2).verify(sub2)
    else:
        _deny_reads_for(monkeypatch, lock_art)
        rep2 = IndependentVerifier(c2).verify(sub2)
    assert rep2.verdict is VerificationVerdict.FAILED and rep2.authority_seal == ""
    assert any(ch.required and ch.result is CheckResult.FAIL
               and ch.explanation == "artifact_unreadable" for ch in rep2.checks)
    # (c) 对照：optional 真正不存在 → VERIFIED（唯一豁免；锚定判据满足
    #     substantive gate）
    c3 = _expectation_contract(work_real, "wc_16f_p2h_c_0001", atype="plain_text",
                               path=work_real / "ghost.txt", required=False,
                               criteria=(VerificationCriterion(
                                   criterion_id="p2h_anchor",
                                   kind="artifact_file_exists",
                                   params={"path": str(work_real / "summary.md")}),))
    rep3 = IndependentVerifier(c3).verify(_submission(c3, "run_p2h_c_0001"))
    assert rep3.verdict is VerificationVerdict.VERIFIED


# ================================================================
# Reviewer Patch 2 — B2: artifact_type 策略不可变（P2-I/P2-J）
# ================================================================


def test_p2_i_artifact_policy_mutation_is_impossible(env):
    """P2-I 否证：导出策略对象任何修改路径都失败，且修改尝试后验证事实
    不变（json_data 仍只收 JSON、未知类型仍 fail-closed）。"""
    import types

    from furina.agent.verification import ARTIFACT_TYPE_CONTENT_RULES as rules
    assert isinstance(rules, types.MappingProxyType)
    with pytest.raises(TypeError):
        rules["rogue_type"] = ("text/plain",)                 # 追加
    with pytest.raises(TypeError):
        rules["json_data"] = ("text/plain",)                  # 放宽既有类型
    with pytest.raises(TypeError):
        del rules["json_data"]                                # 删除
    with pytest.raises((AttributeError, TypeError)):
        rules.pop("json_data", None)                          # mappingproxy 无 pop
    with pytest.raises((AttributeError, TypeError)):
        rules.setdefault("rogue", ())                         # 无 setdefault
    with pytest.raises((AttributeError, TypeError)):
        rules["json_data"].append("text/plain")               # 嵌套 tuple 不可变
    with pytest.raises((AttributeError, TypeError)):
        rules.clear()                                         # 无 clear
    # 修改尝试后策略事实不变（production API 复核）
    tmp, work, work_real, outside, outside_real = env
    ok = work_real / "data.json"
    ok.write_bytes(b'{"k": 1}')
    c_ok = _expectation_contract(work_real, "wc_16f_p2i_ok_0001",
                                 atype="json_data", path=ok)
    rep_ok = IndependentVerifier(c_ok).verify(_submission(c_ok, "run_p2i_ok_0001"))
    assert rep_ok.verdict is VerificationVerdict.VERIFIED
    art = work_real / "doc.txt"
    art.write_bytes(b"hello")
    c_bad = _expectation_contract(work_real, "wc_16f_p2i_bad_0001",
                                  atype="rogue_type", path=art)
    rep_bad = IndependentVerifier(c_bad).verify(_submission(c_bad, "run_p2i_bad_0001"))
    assert rep_bad.verdict is VerificationVerdict.FAILED
    assert any("unknown_artifact_type" in ch.explanation for ch in rep_bad.checks)


def test_p2_j_unknown_artifact_type_remains_fail_closed(env):
    """P2-J 否证：未知/变体 artifact_type 始终 fail-closed（大小写/空格变体
    不放宽）。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "doc.txt"
    art.write_bytes(b"hello")
    for i, atype in enumerate(("rogue_type_1", "JSON_DATA", "plain text",
                               "json_data;x")):
        exp = ArtifactExpectation(artifact_id="prod_doc", artifact_type=atype,
                                  expected_path=str(art), required=True)
        c = _content_contract(work_real, f"wc_16f_p2j_{i:02d}_0001",
                              expectations=(exp,))
        rep = IndependentVerifier(c).verify(_submission(c, f"run_p2j_{i:02d}_0001"))
        assert rep.verdict is VerificationVerdict.FAILED
        assert rep.authority_seal == ""
        assert any("unknown_artifact_type" in ch.explanation
                   for ch in rep.checks if ch.result is CheckResult.FAIL)


# ================================================================
# Reviewer Patch 2 — B4: 当前验证器真实报告门（P2-K/P2-L）
# ================================================================


class _ForeignSignerVerifier(IndependentVerifier):
    """对抗性代理：verify() 转发给另一独立验证器实例（外来签发者）。"""

    def __init__(self, contract, signer: IndependentVerifier) -> None:
        super().__init__(contract)
        self._signer = signer

    def verify(self, evidence):
        return self._signer.verify(evidence)


class _ReplayVerifier(IndependentVerifier):
    """对抗性代理：verify() 返回预置报告（陈旧 attempt / 异契约来源）。"""

    def __init__(self, contract, replay=None) -> None:
        super().__init__(contract)
        self._replay = replay

    def verify(self, evidence):
        if self._replay is not None:
            return self._replay
        return super().verify(evidence)


def _ok_summary_submission(c: WorkContract, run_id: str) -> dict:
    art = Path(c.workspace_scope.write_roots[0]) / "summary.md"
    return _submission(c, run_id,
                       declared=[_declared(art, sha_hex=_sha(b"ok"),
                                           mime="text/markdown",
                                           artifact_id="doc")])


def _verified_summary_contract(work_real: Path, cid: str) -> WorkContract:
    (work_real / "summary.md").write_bytes(b"ok")
    return _contract(work_real, contract_id=cid, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0),
        max_attempts=5))


def test_p2_k_foreign_verifier_seal_rejected_by_repair_loop(env):
    """P2-K 否证：子类代理把另一 IndependentVerifier 实例签发的有效格式
    VERIFIED 报告递给 RepairLoop → REPORT_REJECTED / final_report=None，
    绝不修补或重签。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p2k_0001")
    foreign = IndependentVerifier(c)          # 另一密钥的真实验证器
    loop = BoundedRepairLoop(
        contract=c, verifier=_ForeignSignerVerifier(c, foreign),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r))
    out = loop.run()
    assert out.stop_reason is RepairStopReason.REPORT_REJECTED
    assert out.final_report is None
    assert out.attempts[0].verdict == "VERIFIED"     # 报告本身格式真实产出
    assert "seal_not_authentic_for_current_verifier" in out.diagnostic


def test_p2_l_stale_or_foreign_contract_report_rejected(env):
    """P2-L 否证：seal 真实但 run_id 属旧 attempt 的报告、以及异契约验证器
    签发的报告都被精确身份复核拒绝（REPORT_REJECTED / final_report=None）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p2l_0001")
    # (a) 陈旧 run：报告由 loop 绑定验证器真实签发（seal 可过），但
    #     run_id 是早前 attempt 的 → run_id 精确不一致拒绝。
    proxy = _ReplayVerifier(c)
    stale = IndependentVerifier.verify(proxy, _ok_summary_submission(c, "run_stale_0001"))
    assert stale.verdict is VerificationVerdict.VERIFIED
    proxy._replay = stale
    out = BoundedRepairLoop(
        contract=c, verifier=proxy,
        collect_evidence=lambda a, r: _ok_summary_submission(c, r)).run()
    assert out.stop_reason is RepairStopReason.REPORT_REJECTED
    assert out.final_report is None
    assert "run_id_mismatch" in out.diagnostic
    # (b) 异契约：另一契约验证器签发的 VERIFIED 报告（seal/契约身份全不符；
    #     c2 使用不同判据 → standard_hash 也不一致）。
    c2 = _contract(work_real, contract_id="wc_16f_p2l_other_0001",
                   budget=ExecutionBudget(max_duration_seconds=600.0,
                                          cost_limit=CostBudget(amount=5.0),
                                          max_attempts=5),
                   verification_standard=VerificationStandard(criteria=(
                       VerificationCriterion(criterion_id="p2l_sha_anchor",
                                             kind="artifact_sha256",
                                             params={"path": str(work_real / "summary.md"),
                                                     "sha256_hex": _sha(b"ok")}),
                   )))
    foreign_rep = IndependentVerifier(c2).verify(_ok_summary_submission(c2, "run_p2l_x"))
    assert foreign_rep.verdict is VerificationVerdict.VERIFIED
    assert foreign_rep.standard_hash != IndependentVerifier(c).standard_hash
    proxy2 = _ReplayVerifier(c, replay=foreign_rep)
    out2 = BoundedRepairLoop(
        contract=c, verifier=proxy2,
        collect_evidence=lambda a, r: _ok_summary_submission(c, r)).run()
    assert out2.stop_reason is RepairStopReason.REPORT_REJECTED
    assert out2.final_report is None
    assert "contract_id_mismatch" in out2.diagnostic \
        and "standard_hash_mismatch" in out2.diagnostic \
        and "run_id_mismatch" in out2.diagnostic


# ================================================================
# Reviewer Patch 2 — B5: 回调后新鲜状态复核（P2-Q/P2-R）
# ================================================================


def test_p2_q_factory_side_effects_block_collect(env):
    """P2-Q 否证：run_id_factory 回调期间出现的 cancellation / 超时 / 成本
    耗尽必须阻止 collect（零 collect 零 attempt）。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) factory 期间取消
    c = _contract(work_real)
    ran = {"n": 0}
    flags = {"cancel": False}

    def factory_cancel(attempt_id):
        flags["cancel"] = True
        return f"run_factory_c_{attempt_id[-8:]}"

    def collector(attempt_id, run_id):
        ran["n"] += 1
        return _submission(c, run_id)

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=collector,
                            cancel_requested=lambda: flags["cancel"],
                            run_id_factory=factory_cancel).run()
    assert out.stop_reason is RepairStopReason.CANCELLED
    assert ran["n"] == 0 and len(out.attempts) == 0

    # (b) factory 期间时钟越过 deadline
    clock = FakeClock(1000.0)
    c2 = _contract(work_real, contract_id="wc_16f_p2q_b_0001", budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))

    def factory_deadline(attempt_id):
        clock.advance(100000.0)
        return f"run_factory_d_{attempt_id[-8:]}"

    out2 = BoundedRepairLoop(contract=c2, verifier=IndependentVerifier(c2, now_fn=clock),
                             collect_evidence=collector, now_fn=clock,
                             run_id_factory=factory_deadline).run()
    assert out2.stop_reason is RepairStopReason.TIMEOUT
    assert ran["n"] == 0 and len(out2.attempts) == 0    # factory 后零 collect

    # (c) factory 期间成本耗尽
    c3 = _contract(work_real, contract_id="wc_16f_p2q_c_0001", budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    box = {"used": 0.0}

    def factory_cost(attempt_id):
        box["used"] = 6.0
        return f"run_factory_e_{attempt_id[-8:]}"

    ran["n"] = 0
    out3 = BoundedRepairLoop(contract=c3, verifier=IndependentVerifier(c3),
                             collect_evidence=collector, cost_used=lambda: box["used"],
                             run_id_factory=factory_cost).run()
    assert out3.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert ran["n"] == 0 and len(out3.attempts) == 0


def test_p2_r_cost_callback_advancing_clock_prevents_verified(env):
    """P2-R 否证（任务书复现用例）：attempt_finished=10 < deadline=15，但
    cost meter 回调把时钟推进到 20 → 后置边界必须用**新鲜时间**判定 TIMEOUT，
    越界 VERIFIED 丢弃（final_report=None）。"""
    tmp, work, work_real, outside, outside_real = env
    clock = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c = _contract(work_real, contract_id="wc_16f_p2r_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v = IndependentVerifier(c, now_fn=clock)
    art = work_real / "summary.md"

    def collector(attempt_id, run_id):
        clock.advance(10.0)                # attempt 完成时刻 10 < deadline 15
        return _submission(c, run_id,
                           declared=[_declared(art, sha_hex=_sha(b"ok"))])

    reads = {"n": 0}

    def cost_used():
        reads["n"] += 1
        if reads["n"] >= 3:                # 后置边界内的 cost 回调推进时钟
            clock.advance(10.0)            # 10 → 20 > deadline 15
        return 0.0

    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector,
                            cost_used=cost_used, now_fn=clock).run()
    assert out.attempts[0].verdict == "VERIFIED"      # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.TIMEOUT
    assert out.final_report is None                    # 绝不作为成功结果
    assert clock.t == 20.0


# ================================================================
# Reviewer Patch 2 — B6: canonical identity 统一（P2-O/P2-P）
# ================================================================


def test_p2_o_embedded_underscore_secret_identity_rejected(env):
    """P2-O 否证：嵌入下划线等合法分隔前缀的秘密形态身份（scrubber 与
    identity rejector 共享同一秘密边界）→ VerificationInputError，且异常
    不含 raw secret。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    bad_ids = ("token:supersecret", "run_password:hunter2", "x.api_key=abc",
               "prefix-client_secret:value", "authorization:BearerValue")
    for bid in bad_ids:
        with pytest.raises(VerificationInputError) as ei:
            v.verify(_submission(c, bid))
        secret_value = bid.split(":", 1)[-1].split("=", 1)[-1]
        assert secret_value not in str(ei.value)
    # terminal claim 身份字段同样拒绝
    for field in ("backend_id", "contract_id", "run_id"):
        t = _bound_terminal(c, "run_ok_p2o")
        t[field] = "run_password:hunter2"
        with pytest.raises(VerificationInputError):
            v.verify(_submission(c, "run_ok_p2o", terminal=[t]))


def test_p2_p_secret_bearing_run_id_factory_output_never_stored(env):
    """P2-P 否证：run_id_factory 输出直接经 canonical validate_identity——
    秘密形态拒绝（异常脱敏）、非字符串拒绝（绝不 str() 强转）、绝不进入
    AttemptRecord（拒绝先于存储）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    for bad in ("run_password:hunter2", "token:supersecret", 123, None):
        def factory(attempt_id, _b=bad):
            return _b
        with pytest.raises(VerificationError) as ei:
            BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                              collect_evidence=lambda a, r: _submission(c, r),
                              run_id_factory=factory).run()
        msg = str(ei.value)
        assert "hunter2" not in msg and "supersecret" not in msg


# ================================================================
# Reviewer Patch 2 — B7: regex 隔离有界 + 进程树硬约束（P2-S/P2-T）
# ================================================================


def test_p2_s_catastrophic_regex_is_forcibly_bounded(env):
    """P2-S 否证：经典灾难性回溯 pattern + 长近似匹配输入 → 隔离 worker
    硬超时 → NOT_EVALUABLE（绝不 VERIFIED）；同报告内普通 pattern 仍 PASS
    （不是全面禁用）；测试自身有硬耗时上限断言。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"HEAD_" + b"a" * 30000 + b"!tail")
    c = _contract(work_real, contract_id="wc_16f_p2s_0001",
                  verification_standard=VerificationStandard(criteria=(
                      VerificationCriterion(criterion_id="p2s_evil", kind="regex_matches",
                                            params={"path": str(art),
                                                    "pattern": "(a+)+$"}),
                      VerificationCriterion(criterion_id="p2s_ok", kind="regex_matches",
                                            params={"path": str(art),
                                                    "pattern": "HEAD_"}),
                  ), verifier_refs=(VERIFIER_ID,)))
    t0 = time.monotonic()
    rep = IndependentVerifier(c, process_timeout_seconds=2.0).verify(
        _submission(c, "run_p2s_0001"))
    elapsed = time.monotonic() - t0
    assert elapsed < 60                      # 测试自身硬上限（worker 超时 2s）
    results = {ch.check_id: ch.result for ch in rep.checks}
    assert results["criterion:p2s_ok"] is CheckResult.PASS          # 正常 pattern 不受影响
    assert results["criterion:p2s_evil"] is CheckResult.NOT_EVALUABLE
    assert any("regex_timeout" in ch.explanation for ch in rep.checks)
    assert rep.verdict is VerificationVerdict.INCONCLUSIVE
    assert rep.authority_seal == ""


P2T_PARENT_TEMPLATE = """import subprocess, sys
desc = [sys.executable, "-c", "import time; time.sleep(30)  # P16FDESC16f"]
kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL, close_fds=True)
try:
    # 先尝试脱离 job/breakaway——失败再普通 detached 启动（两种都不应存活）
    subprocess.Popen(desc, creationflags=0x00000008 | 0x00000200 | 0x01000000, **kw)
except (OSError, ValueError):
    subprocess.Popen(desc, creationflags=0x00000008 | 0x00000200, **kw)
sys.exit(0)
"""


def _p16f_descendant_count():
    import subprocess as sp
    ps_script = ("@(Get-CimInstance Win32_Process | Where-Object { "
                 "$_.CommandLine -like '*P16FDESC16f*' -and $_.Name -ne "
                 "'powershell.exe' }).Count")

    def count():
        try:
            r = sp.run(["powershell", "-NoProfile", "-Command", ps_script],
                       capture_output=True, text=True, timeout=60)
        except (OSError, sp.TimeoutExpired):
            return None
        try:
            return int(r.stdout.strip() or "0")
        except ValueError:
            return None

    deadline = time.monotonic() + 25
    n = count()
    while time.monotonic() < deadline and n:
        time.sleep(0.5)
        n = count()
    return n


def test_p2_t_detached_descendant_cannot_survive_or_checker_fails_closed(env, tmp_path):
    """P2-T 否证：Windows——尝试 breakaway/detached 的孙进程从启动起被 Job
    收编，criterion 正常退出路径结束后有界轮询证明零存活后代；POSIX——无
    树级硬约束证明时 checker fail-closed 拒绝评估（绝不 PASS）。"""
    tmp, work, work_real, outside, outside_real = env
    parent = tmp_path / "p2t_parent.py"
    parent.write_text(P2T_PARENT_TEMPLATE, encoding="utf-8")
    c = _contract(work_real, contract_id="wc_16f_p2t_0001",
                  verification_standard=VerificationStandard(criteria=(
                      VerificationCriterion(
                          criterion_id="proc", kind="process_exit_zero",
                          params={"command": f'"{sys.executable}" "{parent}"'}),
                  )))
    rep = IndependentVerifier(c).verify(_submission(c, "run_p2t_0001"))
    if sys.platform == "win32":
        assert rep.verdict is VerificationVerdict.VERIFIED      # 父进程 exit 0
        survivors = _p16f_descendant_count()
        # Patch 3 B6：枚举/证明能力不可用时测试必须 FAIL，不得 SKIP。
        assert survivors is not None, \
            "PowerShell 进程枚举不可用——枚举能力缺失必须 FAIL（不得 SKIP）"
        assert survivors == 0                    # detached 后代无法在 job 外存活
    else:
        assert rep.verdict is VerificationVerdict.INCONCLUSIVE
        assert rep.authority_seal == ""
        assert any("process_containment_unavailable" in ch.explanation
                   for ch in rep.checks)
# ================================================================
# Reviewer Patch 2 — B3: 句柄锚定 containment（P2-M/P2-N）
# ================================================================


def _swap_parent_during_open(monkeypatch, target: Path, parent: Path,
                             outside_dir: Path) -> dict:
    """确定性同步点（blocker B3 否证工具）：目标路径第一次被打开时，把其
    父目录替换为指向 outside_dir 的 symlink/junction——即"containment 检查
    后、读取前替换"。返回 state（swapped 标志）。"""
    real_open = builtins.open
    state = {"swapped": False}
    tgt = os.path.normcase(os.path.realpath(str(target)))

    def swapping_open(file, mode="r", *a, **k):
        try:
            same = os.path.normcase(os.path.realpath(str(file))) == tgt
        except OSError:
            same = False
        if not state["swapped"] and same and "r" in str(mode) and "b" in str(mode):
            state["swapped"] = True
            os.rename(parent, parent.with_name(parent.name + "_bak16f"))
            assert _make_dir_link(parent, outside_dir), "symlink/junction 不可用"
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", swapping_open)
    return state


def _restore_swapped_parent(parent: Path) -> None:
    """清理：移除替换出的链接，把备份父目录改名还原（避免 tmp 清理递归）。"""
    bak = parent.with_name(parent.name + "_bak16f")
    try:
        if bak.exists():
            if parent.exists():
                os.rmdir(parent)          # 移除 symlink/junction reparse point
            os.rename(bak, parent)
    except OSError:
        pass


def test_p2_m_handle_anchored_symlink_junction_swap_cannot_escape(env, monkeypatch):
    """P2-M 否证：declared/expectation 观察的"containment 检查后、读取前
    替换"（父目录换成指向 workspace 外的链接）→ 句柄级真实目标证明拦截
    path_escape，绝不读取 workspace 外内容（外部文件 hash 一致也不放行）。"""
    tmp, work, work_real, outside, outside_real = env
    subdir = work_real / "sub16f"
    subdir.mkdir()
    target = subdir / "f.md"
    target.write_bytes(b"inside-stale-content")
    outside_dir = tmp / "outside16f"
    outside_dir.mkdir()
    outside_file = outside_dir / "f.md"
    outside_file.write_bytes(b"escaped-secret-content")
    (work_real / "summary.md").write_bytes(b"ok")
    exp = ArtifactExpectation(artifact_id="doc", artifact_type="markdown_document",
                              expected_path=str(target), required=True)
    c = _content_contract(work_real, "wc_16f_p2m_0001", expectations=(exp,))
    # 声明 hash 与 workspace 外内容一致——旧"先 realpath 后按路径 open"实现
    # 会读取外部内容并 VERIFIED；句柄锚定实现必须 path_escape 拒绝。
    sub = _submission(c, "run_p2m_0001",
                      declared=[_declared(target, sha_hex=_sha(b"escaped-secret-content"),
                                          mime="text/markdown", artifact_id="doc")])
    try:
        _swap_parent_during_open(monkeypatch, target, subdir, outside_dir)
        rep = IndependentVerifier(c).verify(sub)
    finally:
        _restore_swapped_parent(subdir)
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    assert any(ch.required and ch.result is CheckResult.FAIL
               and "path_escape" in ch.explanation for ch in rep.checks),         [(ch.check_id, ch.explanation) for ch in rep.checks]
    assert all(ch.result is not CheckResult.PASS
               for ch in rep.checks if ch.check_id.endswith(":hash"))


def test_p2_n_criterion_only_path_swap_cannot_escape(env, monkeypatch):
    """P2-N 否证：criterion-only 文件（text_contains 判据路径）在检查与读取
    之间被替换为指向 workspace 外的链接 → 句柄锚定 containment 拦截
    path_escape，needle 命中外部内容也绝不 PASS。"""
    tmp, work, work_real, outside, outside_real = env
    subdir = work_real / "sub16fn"
    subdir.mkdir()
    target = subdir / "f.md"
    target.write_bytes(b"no needle here inside")
    outside_dir = tmp / "outside16fn"
    outside_dir.mkdir()
    (outside_dir / "f.md").write_bytes(b"NEEDLE_16FN escaped content")
    c = _contract(work_real, contract_id="wc_16f_p2n_0001",
                  verification_standard=VerificationStandard(criteria=(
                      VerificationCriterion(criterion_id="win", kind="text_contains",
                                            params={"path": str(target),
                                                    "needle": "NEEDLE_16FN"}),
                  ), verifier_refs=(VERIFIER_ID,)))
    try:
        _swap_parent_during_open(monkeypatch, target, subdir, outside_dir)
        rep = IndependentVerifier(c).verify(_submission(c, "run_p2n_0001"))
    finally:
        _restore_swapped_parent(subdir)
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    crit = [ch for ch in rep.checks if ch.check_id == "criterion:win"]
    assert crit and crit[0].result is CheckResult.FAIL         and "path_escape" in crit[0].explanation


# ================================================================
# ================================================================
# Reviewer Patch 3 — B1: PDF 真实封闭结构（P3-A/P3-B）
# ================================================================


def test_p3_a_fake_pdf_rejected(env):
    """P3-A 否证：伪 PDF（%PDF- marker + %%EOF 但无任何结构）→ full_content_
    verdict 必须拒绝（绝非 ("application/pdf", "")）；作为 pdf_document 期望
    验证同样 required FAIL。"""
    from furina.agent.verification import full_content_verdict
    fake = b"%PDF-1.7\nnot a PDF\n%%EOF"
    mime, rejection = full_content_verdict(fake)
    assert mime == "application/pdf"                 # 魔数识别仍是 PDF 族
    assert rejection.startswith("malformed_content:")   # 但结构验证必须失败
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "doc.pdf"
    art.write_bytes(fake)
    c = _expectation_contract(work_real, "wc_16f_p3a_0001",
                              atype="pdf_document", path=art)
    rep = IndependentVerifier(c).verify(_submission(c, "run_p3a_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    assert any(ch.result is CheckResult.FAIL
               and ch.explanation.startswith("malformed_content:")
               for ch in rep.checks)


def test_p3_b_broken_xref_startxref_rejected(env):
    """P3-B 否证：错误 startxref / 截断 xref / 缺失 trailer-Root / xref 条目
    偏移造假 全部 full_content_verdict 拒绝（封闭结构 + 偏移关系，fail-closed）。"""
    from furina.agent.verification import full_content_verdict
    pdf = PDF_BYTES
    # xref 表关键字位置（注意 rfind 会命中 startxref 内部的 "xref"——必须 find）
    xref_pos = pdf.find(b"xref")
    # (a) startxref 指向对象中间（非 xref 表）
    sx = pdf.rfind(b"startxref")
    bad_a = pdf[:sx] + b"startxref\n10\n%%EOF\n"
    # (b) xref 表截断（缺 %%EOF）
    bad_b = pdf[:xref_pos + 20]
    # (c) trailer 缺 /Root
    bad_c = pdf.replace(b"/Size 4/Root 1 0 R", b"/Size 4")
    # (d) xref 条目记录的对象字节偏移造假
    bad_d = pdf.replace(b"%010d 00000 n" % 54, b"%010d 00000 n" % 99)
    # (e) xref 子段 count 与条目数不符（截断 xref 表）
    bad_e = pdf.replace(b"xref\n0 4\n", b"xref\n0 3\n")
    for tag, blob in (("startxref", bad_a), ("trunc_xref", bad_b),
                      ("no_root", bad_c), ("offset_forgery", bad_d),
                      ("count_mismatch", bad_e)):
        mime, rejection = full_content_verdict(blob)
        assert mime == "application/pdf"
        assert rejection.startswith("malformed_content:"), (tag, rejection)
    # 正对照：合法最小 PDF 必须 PASS
    mime, rejection = full_content_verdict(pdf)
    assert mime == "application/pdf" and rejection == ""


# ================================================================
# Reviewer Patch 3 — B2: 单路径单快照 + criterion 完整内容（P3-C..P3-F）
# ================================================================


def test_p3_c_oversize_empty_exists_rejected(env):
    """P3-C 否证：criterion artifact_file_exists 对空文件 → FAIL artifact_empty、
    对 >8MiB 文件 → FAIL artifact_oversize（存在本身不是有效证据）。"""
    tmp, work, work_real, outside, outside_real = env
    empty = work_real / "empty.md"
    empty.write_bytes(b"")
    c = _contract(work_real, contract_id="wc_16f_p3c_a_0001",
                  verification_standard=VerificationStandard(criteria=(
                      VerificationCriterion(criterion_id="empty_exists",
                                            kind="artifact_file_exists",
                                            params={"path": str(empty)}),)))
    rep = IndependentVerifier(c).verify(_submission(c, "run_p3c_a_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    crit = [ch for ch in rep.checks if ch.check_id == "criterion:empty_exists"][0]
    assert crit.result is CheckResult.FAIL and "artifact_empty" in crit.explanation

    big = work_real / "big.md"
    big.write_bytes(b"\x00" * (MAX_ARTIFACT_BYTES + 1))
    c2 = _contract(work_real, contract_id="wc_16f_p3c_b_0001",
                   verification_standard=VerificationStandard(criteria=(
                       VerificationCriterion(criterion_id="big_exists",
                                             kind="artifact_file_exists",
                                             params={"path": str(big)}),)))
    rep2 = IndependentVerifier(c2).verify(_submission(c2, "run_p3c_b_0001"))
    assert rep2.verdict is VerificationVerdict.FAILED
    crit2 = [ch for ch in rep2.checks if ch.check_id == "criterion:big_exists"][0]
    assert crit2.result is CheckResult.FAIL and "artifact_oversize" in crit2.explanation


def test_p3_d_binary_tail_after_text_window_rejected(env):
    """P3-D 否证：criterion-only 文件前 1 MiB 是合法文本、其后接 NUL/二进制 →
    整体不是合法文本 → content_not_text FAIL——NUL 尾不得被前 1 MiB 窗口掩盖。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "note.md"
    blob = b"NEEDLE_P3D " + b"a" * (MAX_TEXT_READ_BYTES - 11) + b"\x00binary\x00tail"
    assert len(blob) > MAX_TEXT_READ_BYTES and len(blob) <= MAX_ARTIFACT_BYTES
    art.write_bytes(blob)
    c = _contract(work_real, contract_id="wc_16f_p3d_0001",
                  verification_standard=VerificationStandard(criteria=(
                      VerificationCriterion(criterion_id="win", kind="text_contains",
                                            params={"path": str(art),
                                                    "needle": "NEEDLE_P3D"}),)))
    rep = IndependentVerifier(c).verify(_submission(c, "run_p3d_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    crit = [ch for ch in rep.checks if ch.check_id == "criterion:win"][0]
    assert crit.result is CheckResult.FAIL and "content_not_text" in crit.explanation


def test_p3_e_one_canonical_snapshot_per_path(env, monkeypatch):
    """P3-E 否证：同一路径被 expectation/declared/exists/text 同时引用时，
    单次 verify 只打开一次——canonical-path snapshot cache 复用同一不可变快照。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    content = b"# summary\nsnapshot single open test"
    art.write_bytes(content)
    opens = {"n": 0}
    real_open = builtins.open
    tgt = os.path.normcase(os.path.realpath(str(art)))

    def counting_open(file, mode="r", *a, **k):
        if "r" in str(mode) and "b" in str(mode) \
                and os.path.normcase(os.path.realpath(str(file))) == tgt:
            opens["n"] += 1
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", counting_open)
    exp = ArtifactExpectation(artifact_id="doc", artifact_type="markdown_document",
                              expected_path=str(art), required=True)
    c = _content_contract(work_real, "wc_16f_p3e_0001", expectations=(exp,),
                          criteria=(
                              VerificationCriterion(
                                  criterion_id="exists", kind="artifact_file_exists",
                                  params={"path": str(art)}),
                              VerificationCriterion(
                                  criterion_id="text", kind="text_contains",
                                  params={"path": str(art), "needle": "single"}),))
    v = IndependentVerifier(c)
    rep = v.verify(_submission(
        c, "run_p3e_0001",
        declared=[_declared(art, sha_hex=_sha(content), mime="text/markdown",
                            artifact_id="doc")]))
    assert rep.verdict is VerificationVerdict.VERIFIED
    assert v.seal_is_authentic(rep) is True
    assert opens["n"] == 1          # 同一路径只打开一次（缓存复用）


def test_p3_f_cross_snapshot_json_text_attack_rejected(env, monkeypatch):
    """P3-F 否证：expectation 先观察合法 JSON、criterion 再读同一路径——若允许
    第二次打开（旧实现），攻击者可在其间把文件换成含 needle 的纯文本拼接出
    VERIFIED；snapshot cache 使 criterion 复用同一 JSON 快照（只打开一次）→
    needle 未命中 → FAIL，绝不 VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "data.json"
    art.write_bytes(b'{"k": "json value"}')
    opens = {"n": 0}
    real_open = builtins.open
    tgt = os.path.normcase(os.path.realpath(str(art)))

    def swapping_open(file, mode="r", *a, **k):
        h = real_open(file, mode, *a, **k)
        if "r" in str(mode) and "b" in str(mode) \
                and os.path.normcase(os.path.realpath(str(file))) == tgt:
            opens["n"] += 1
            if opens["n"] >= 2:
                # 第二次打开（旧实现会发生）：文件已被替换为含 needle 的文本
                with real_open(str(art), "wb") as g:
                    g.write(b"NEEDLE_P3F text version")
        return h

    monkeypatch.setattr(builtins, "open", swapping_open)
    exp = ArtifactExpectation(artifact_id="prod_doc", artifact_type="json_data",
                              expected_path=str(art), required=True)
    c = _content_contract(work_real, "wc_16f_p3f_0001", expectations=(exp,),
                          criteria=(
                              VerificationCriterion(
                                  criterion_id="cross", kind="text_contains",
                                  params={"path": str(art),
                                          "needle": "NEEDLE_P3F"}),))
    rep = IndependentVerifier(c).verify(_submission(c, "run_p3f_0001"))
    assert opens["n"] == 1          # 同一路径只打开一次——攻击者无第二次打开机会
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    crit = [ch for ch in rep.checks if ch.check_id == "criterion:cross"][0]
    assert crit.result is CheckResult.FAIL


# ================================================================
# Reviewer Patch 3 — B3: 接受 VERIFIED 前最终稳定边界（P3-G/P3-H）
# ================================================================


def test_p3_g_cancellation_mutates_cost_before_accept(env):
    """P3-G 否证（任务书复现用例）：最终稳定复核中 cancellation 回调把 cost
    从 0 改成 6（limit=5）→ 第二轮完整安全扫描捕获 → BUDGET_EXHAUSTED /
    final_report=None（绝不 VERIFIED）；cost 回调在最终复核内推进时钟 →
    新鲜时间越过 deadline → TIMEOUT；最终复核内回调异常 → UNSTABLE_BOUNDARY
    fail-closed。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) cancellation 回调修改 cost（limit=5，cost 0→6）
    c = _verified_summary_contract(work_real, "wc_16f_p3g_a_0001")
    box = {"used": 0.0, "cancel_calls": 0}

    def cost_used_a():
        return box["used"]

    def cancel_flips_cost():
        box["cancel_calls"] += 1
        if box["cancel_calls"] == 4:    # 最终复核第 1 轮：cancel 回调把 cost 改成 6
            box["used"] = 6.0
        return False

    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        cost_used=cost_used_a, cancel_requested=cancel_flips_cost).run()
    assert out.attempts[0].verdict == "VERIFIED"     # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out.final_report is None

    # (b) cost 回调在最终复核内推进时钟 → 新鲜时间越过 deadline → TIMEOUT
    clock = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c2 = _contract(work_real, contract_id="wc_16f_p3g_b_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v2 = IndependentVerifier(c2, now_fn=clock)
    reads = {"n": 0}

    def cost_advances_clock():
        reads["n"] += 1
        if reads["n"] == 4:             # 最终复核第 1 轮的 cost 读取推进时钟
            clock.advance(20.0)         # 0 → 20 > deadline 15
        return 0.0

    out2 = BoundedRepairLoop(
        contract=c2, verifier=v2,
        collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
        cost_used=cost_advances_clock, now_fn=clock).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.TIMEOUT
    assert out2.final_report is None
    assert clock.t == 20.0

    # (c) 最终复核内回调异常 → 无法取得稳定安全结果 → fail-closed
    c3 = _verified_summary_contract(work_real, "wc_16f_p3g_c_0001")
    cancel_calls = {"n": 0}

    def cancel_boom():
        cancel_calls["n"] += 1
        if cancel_calls["n"] >= 4:      # 最终复核第 1 轮回调抛异常
            raise RuntimeError("cancel callback exploded")
        return False

    out3 = BoundedRepairLoop(
        contract=c3, verifier=IndependentVerifier(c3),
        collect_evidence=lambda a, r: _ok_summary_submission(c3, r),
        cancel_requested=cancel_boom).run()
    assert out3.attempts[0].verdict == "VERIFIED"
    assert out3.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out3.final_report is None
    assert "final_boundary_unstable" in out3.diagnostic


def test_p3_h_authentication_mutates_deadline_or_cancel(env):
    """P3-H 否证：接受门（seal 认证 / standard_hash 属性访问）内的回调副作用
    必须被最终稳定边界复核捕获——(a) seal_is_authentic 翻转取消标志 →
    CANCELLED / final_report=None；(b) standard_hash 属性推进时钟越过 deadline
    → TIMEOUT / final_report=None。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) seal 认证回调翻转 cancellation
    c = _verified_summary_contract(work_real, "wc_16f_p3h_a_0001")
    flags = {"cancel": False}

    class _SealSideEffectVerifier(IndependentVerifier):
        def seal_is_authentic(self, report):
            flags["cancel"] = True       # 认证回调副作用：翻转取消标志
            return super().seal_is_authentic(report)

    out = BoundedRepairLoop(
        contract=c, verifier=_SealSideEffectVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        cancel_requested=lambda: flags["cancel"]).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.CANCELLED
    assert out.final_report is None

    # (b) standard_hash 属性回调推进时钟越过 deadline（接受门内访问时触发）
    clock = FakeClock(1000.0)
    c2 = _verified_summary_contract(work_real, "wc_16f_p3h_b_0001")

    class _HashAdvancingVerifier(IndependentVerifier):
        def __init__(self, contract, clock):
            super().__init__(contract, now_fn=clock)
            self._clock = clock
            self._calls = 0

        @property
        def standard_hash(self):
            self._calls += 1
            if self._calls >= 3:         # 接受门内（seal/身份复核）的访问推进时钟
                self._clock.advance(100000.0)
            return super().standard_hash

    v2 = _HashAdvancingVerifier(c2, clock)
    out2 = BoundedRepairLoop(
        contract=c2, verifier=v2,
        collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
        now_fn=clock).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.TIMEOUT
    assert out2.final_report is None


# ================================================================
# Reviewer Patch 3 — B4: POSIX regex worker 独立 session（P3-I）
# ================================================================


def test_p3_i_posix_regex_timeout_preserves_parent_group(env, monkeypatch):
    """P3-I 否证：POSIX regex worker 必须 start_new_session 自建进程组/会话；
    timeout 终止仅当 pgid 归属 worker 自身才 killpg——绝不触碰宿主进程组
    （worker 必死、测试进程必活）；Windows 保持有界终止。stdout/stderr 继续
    DEVNULL、输入继续有界。"""
    import subprocess as sp

    from furina.agent.verification import checks as vchecks
    from furina.agent.verification import regex_match_bounded
    worker_kwargs = {}
    worker_proc = {"p": None}
    real_popen = sp.Popen

    def spy_popen(*args, **kwargs):
        # 第一个 Popen 是 regex worker；timeout 终止路径的 taskkill Popen
        # 会随后出现（同样 DEVNULL）——只记录 worker 的调用与句柄。
        p = real_popen(*args, **kwargs)
        if worker_proc["p"] is None:
            worker_kwargs.update(kwargs)
            worker_proc["p"] = p
        return p

    monkeypatch.setattr(vchecks.subprocess, "Popen", spy_popen)
    parent_pgid = os.getpgid(0) if os.name == "posix" else None
    t0 = time.monotonic()
    matched, rejection = regex_match_bounded("(a+)+$", "a" * 30000 + "!", 0.5)
    elapsed = time.monotonic() - t0
    assert rejection == "regex_timeout"           # 灾难性回溯硬超时
    assert elapsed < 60                           # 有界返回
    assert worker_kwargs["stdin"] is sp.PIPE      # 输入有界（上游 ≤1MiB 窗口）
    assert worker_kwargs["stdout"] is sp.DEVNULL \
        and worker_kwargs["stderr"] is sp.DEVNULL
    if os.name == "posix":
        assert worker_kwargs.get("start_new_session") is True   # 独立 session/进程组
        assert os.getpgid(0) == parent_pgid             # 宿主进程组未被 killpg 触碰
    assert worker_proc["p"].poll() is not None    # worker 已死（timeout 后终止）


# ================================================================
# Reviewer Patch 3 — B5: 公开模型身份验证 + 秘密路径脱敏（P3-J/P3-K）
# ================================================================


def test_p3_j_public_model_secret_identities_rejected(env):
    """P3-J 否证：public 模型（TerminalObservation/ArtifactObservation/
    EvidenceBundle/VerificationReport）直接构造时身份字段走 canonical
    validate_identity——秘密形态直接拒绝（绝不清洗后继续作为身份）；
    to_dict()/to_json() 因此不可能导出 raw secret 身份。"""
    from furina.agent.verification import (
        ArtifactObservation,
        EvidenceBundle,
        TerminalObservation,
    )
    with pytest.raises(VerificationError):
        TerminalObservation(event_id="token:supersecret", kind="backend.completed",
                            observed_at_epoch=1.0, bound=True)
    with pytest.raises(VerificationError):
        ArtifactObservation("expectation", "api_key:sk-abc123", "/p/a.md",
                            "/p/a.md", True, True, True, 3, "text/plain",
                            "0" * 64, "", "text/markdown")
    with pytest.raises(VerificationError):
        EvidenceBundle(contract_id="wc_16f_p3j_0001", contract_hash="0" * 64,
                       run_id="run_password:x", backend_id="native_agent",
                       terminal=(), artifacts=())
    ev = EvidenceBundle(contract_id="wc_16f_p3j_0001", contract_hash="0" * 64,
                        run_id="run_p3j_0001", backend_id="native_agent",
                        terminal=(), artifacts=())
    base = dict(report_id="vrp_" + "a" * 32, verifier_id=VERIFIER_ID,
                contract_id="wc_16f_p3j_0001", contract_hash="0" * 64,
                standard_hash="0" * 64, run_id="run_p3j_0001",
                backend_id="native_agent", verdict=VerificationVerdict.FAILED,
                checks=(), diagnostics=(), evidence=ev,
                started_at_epoch=1.0, finished_at_epoch=2.0)
    for field in ("contract_id", "run_id", "backend_id"):
        kw = dict(base)
        kw[field] = "password:hunter2"
        with pytest.raises(VerificationError):
            VerificationReport(**kw)


def test_p3_k_secret_path_exception_redacted(env):
    """P3-K 否证：秘密形态 artifact path 的 VerificationInputError 回显一律
    脱敏——raw secret 绝不进入异常消息（禁止 {path!r} 原文）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    evil = str(work_real / "password=hunter2secret.md")
    with pytest.raises(VerificationInputError) as ei:
        v.verify(_submission(c, "run_p3k_0001", declared=[_declared(evil)]))
    msg = str(ei.value)
    assert "hunter2secret" not in msg
    assert "[REDACTED]" in msg
    # 非绝对路径（且带秘密形态）的异常同样不回显 raw 原文（纵深防御）
    rel = "work/relative/password=hunter2secret.md"
    with pytest.raises(VerificationInputError) as ei2:
        v.verify(_submission(c, "run_p3k_0002", declared=[_declared(rel)]))
    assert "hunter2secret" not in str(ei2.value)


# ================================================================
# Reviewer Patch 3 — B6: 进程证明不可 skip（P3-L）
# ================================================================


def test_p3_l_process_proof_cannot_skip(env, monkeypatch):
    """P3-L 否证：进程树 containment 证明能力被剥除（模拟 POSIX 无树级硬
    约束）→ process 判据 fail-closed NOT_EVALUABLE → INCONCLUSIVE / 零 seal，
    绝不 best-effort PASS、绝不 skip；证明可用（win32 Job Object）时真实
    评估。"""
    from furina.agent.verification import checks as vchecks
    tmp, work, work_real, outside, outside_real = env
    py = sys.executable
    command = f'"{py}" -c "import sys; sys.exit(0)"'
    c = _contract(work_real, contract_id="wc_16f_p3l_0001",
                  verification_standard=VerificationStandard(criteria=(
                      VerificationCriterion(criterion_id="proc",
                                            kind="process_exit_zero",
                                            params={"command": command}),)))
    original_guard = vchecks.process_containment_guaranteed
    monkeypatch.setattr(vchecks, "process_containment_guaranteed", lambda: False)
    rep = IndependentVerifier(c).verify(_submission(c, "run_p3l_0001"))
    crit = [ch for ch in rep.checks if ch.check_id == "criterion:proc"][0]
    assert crit.result is CheckResult.NOT_EVALUABLE
    assert "process_containment_unavailable" in crit.explanation
    assert rep.verdict is VerificationVerdict.INCONCLUSIVE
    assert rep.authority_seal == ""
    # 恢复真实实现后：真实平台（win32：Job Object 树级硬约束可用）→ 正常评估
    # exit 0 → VERIFIED（证明能力可用时必须真实评估，不得跳过）。
    monkeypatch.setattr(vchecks, "process_containment_guaranteed", original_guard)
    if sys.platform == "win32":
        assert vchecks.process_containment_guaranteed() is True
        rep2 = IndependentVerifier(c).verify(_submission(c, "run_p3l_0002"))
        assert rep2.verdict is VerificationVerdict.VERIFIED
        assert rep2.authority_seal


# ================================================================


# ================================================================
# Reviewer Patch 4 — P4-A/P4-B: PDF 对象图 + Root 图 + trailer 尾
# ================================================================


def _pdf_with_body(pdf: bytes, obj_num: int, new_body: bytes) -> bytes:
    """长度保持的对象体替换（新 body 短于旧 body 时以空白补齐）——保持全部
    xref 偏移自洽，只验证目标对象体本身。"""
    marker = b"%d 0 obj\n" % obj_num
    start = pdf.find(marker)
    assert start >= 0, f"对象 {obj_num} 不存在"
    body_start = start + len(marker)
    end = pdf.find(b"endobj", body_start)
    assert end >= 0, f"对象 {obj_num} 缺 endobj"
    old = pdf[body_start:end]
    assert len(new_body) <= len(old), "新 body 必须不短于旧 body（保持偏移）"
    pad = b" " * (len(old) - len(new_body))
    return pdf[:body_start] + new_body + pad + pdf[end:]


def test_p4_a_fake_root_object_rejected(env):
    """P4-A 否证：带真实 xref 的伪对象仍必须被拒绝——Root 对象体是文本
    （任意文本对象）→ pdf_obj_not_dict；Root 是字典但 /Type 不是 Catalog
    （伪 Catalog）→ pdf_root_not_catalog——都 fail-closed；合法最小 PDF
    正对照仍 PASS。"""
    from furina.agent.verification import full_content_verdict
    tmp, work, work_real, outside, outside_real = env
    pdf = PDF_BYTES
    assert full_content_verdict(pdf) == ("application/pdf", "")     # 正对照
    text_root = _pdf_with_body(pdf, 1, b"not a PDF")
    mime, rejection = full_content_verdict(text_root)
    assert mime == "application/pdf"
    assert "malformed_content:pdf_obj_not_dict" in rejection, rejection
    fake_catalog = _pdf_with_body(pdf, 1, b"<</Type/Notes/Pages 2 0 R>>")
    mime2, rejection2 = full_content_verdict(fake_catalog)
    assert mime2 == "application/pdf"
    assert "malformed_content:pdf_root_not_catalog" in rejection2, rejection2
    # 端到端：文本 Root 伪对象作为 pdf_document 期望验证 → required FAIL
    art = work_real / "doc.pdf"
    art.write_bytes(text_root)
    c = _expectation_contract(work_real, "wc_16f_p4a_0001",
                              atype="pdf_document", path=art)
    rep = IndependentVerifier(c).verify(_submission(c, "run_p4a_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    assert any(ch.result is CheckResult.FAIL
               and ch.explanation.startswith("malformed_content:pdf_")
               for ch in rep.checks), [(ch.check_id, ch.explanation) for ch in rep.checks]


def test_p4_b_missing_endobj_and_free_root_rejected(env):
    """P4-B 否证：n 条目对象缺 endobj → pdf_obj_missing_endobj；Root xref
    条目被改成 free → pdf_root_free；/Size 与 xref 覆盖不一致 →
    pdf_size_mismatch；trailer 之后出现文本对象（只允许 startxref/EOF/空白）
    → pdf_trailer_tail——全部 fail-closed，绝不 VERIFIED。"""
    from furina.agent.verification import full_content_verdict
    tmp, work, work_real, outside, outside_real = env
    pdf = PDF_BYTES
    # (a) 对象 2 缺 endobj（长度保持：endobj 6 字符被空白替换）
    missing_endobj = pdf.replace(b">>\nendobj\n3 0 obj", b">>\n      \n3 0 obj")
    mime, rejection = full_content_verdict(missing_endobj)
    assert mime == "application/pdf"
    assert "malformed_content:pdf_obj_missing_endobj" in rejection, rejection
    # (b) Root(1) 的 xref 条目由 n 改成 free（长度保持）
    obj1_pos = pdf.find(b"1 0 obj\n")
    free_root = pdf.replace(b"%010d 00000 n " % obj1_pos,
                            b"%010d 65535 f " % 0)
    mime2, rejection2 = full_content_verdict(free_root)
    assert mime2 == "application/pdf"
    assert "malformed_content:pdf_root_free" in rejection2, rejection2
    # (c) /Size 与 xref 覆盖不一致（最高对象号 + 1 = 4，伪造 5）
    size_bad = pdf.replace(b"/Size 4/Root 1 0 R", b"/Size 5/Root 1 0 R")
    mime3, rejection3 = full_content_verdict(size_bad)
    assert mime3 == "application/pdf"
    assert "malformed_content:pdf_size_mismatch" in rejection3, rejection3
    # (d) trailer 之后出现文本对象
    tail_bad = pdf.replace(b">>\nstartxref", b">>\ntext object\nstartxref")
    mime4, rejection4 = full_content_verdict(tail_bad)
    assert mime4 == "application/pdf"
    assert "malformed_content:pdf_trailer_tail" in rejection4, rejection4


# ================================================================
# Reviewer Patch 4 — P4-C: 空文件判据统一拒绝
# ================================================================


def test_p4_c_empty_sha_and_regex_rejected(env):
    """P4-C 否证：所有文件类判据在 kind 分支分流前统一拒绝空文件——空文件
    SHA（即使等于空串 e3b0c… 哈希）与空文件 ^$ regex 都不得 PASS → 全部
    artifact_empty required FAIL → 绝不 VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    empty = work_real / "empty.md"
    empty.write_bytes(b"")
    criteria = (
        VerificationCriterion(criterion_id="empty_sha", kind="artifact_sha256",
                              params={"path": str(empty), "sha256_hex": _sha(b"")}),
        VerificationCriterion(criterion_id="empty_regex", kind="regex_matches",
                              params={"path": str(empty), "pattern": "^$"}),
        VerificationCriterion(criterion_id="empty_exists", kind="artifact_file_exists",
                              params={"path": str(empty)}),
        VerificationCriterion(criterion_id="empty_text", kind="text_contains",
                              params={"path": str(empty), "needle": "x"}),
    )
    c = _contract(work_real, contract_id="wc_16f_p4c_0001",
                  verification_standard=VerificationStandard(criteria=criteria))
    rep = IndependentVerifier(c).verify(_submission(c, "run_p4c_0001"))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    for cid in ("empty_sha", "empty_regex", "empty_exists", "empty_text"):
        crit = [ch for ch in rep.checks if ch.check_id == f"criterion:{cid}"][0]
        assert crit.result is CheckResult.FAIL, (cid, crit.result)
        assert "artifact_empty" in crit.explanation, (cid, crit.explanation)


# ================================================================
# Reviewer Patch 4 — P4-D: 物理文件单快照（hardlink 别名）
# ================================================================


def _make_file_link(link: Path, target: Path) -> bool:
    """文件硬链接（同卷普通文件无需特权；os.link 失败返回 False——由测试
    前提断言保证可用）。"""
    try:
        os.link(target, link)
        return True
    except (OSError, NotImplementedError):
        return False


def test_p4_d_hardlink_alias_cross_snapshot_rejected(env, monkeypatch):
    """P4-D 否证：hardlink 别名指向同一物理文件——expectation 观察 JSON 后，
    验证期间经任一别名把同一 inode 改写为含 needle 的文本；第二别名捕获到
    不同事实（size/sha/mtime）→ 全局 required snapshot_alias_mutated FAIL，
    绝不组合不同版本、绝不 VERIFIED；未改写的别名正对照复用同一事实快照
    （两个别名各打开一次、判定用首快照）→ VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    a = work_real / "data.json"
    a.write_bytes(b'{"k": "json value"}')
    b = work_real / "alias.json"
    assert _make_file_link(b, a), "hardlink 不可用（测试前提）"
    assert os.stat(a).st_ino == os.stat(b).st_ino
    exp = ArtifactExpectation(artifact_id="prod_doc", artifact_type="json_data",
                              expected_path=str(a), required=True)
    crit = VerificationCriterion(criterion_id="cross", kind="text_contains",
                                 params={"path": str(b), "needle": "NEEDLE_P4D"})
    c = _content_contract(work_real, "wc_16f_p4d_0001", expectations=(exp,),
                          criteria=(crit,))
    opens = {"n": 0}
    real_open = builtins.open
    tgt = {os.path.normcase(os.path.realpath(str(p))) for p in (a, b)}

    def swapping_open(file, mode="r", *args, **kwargs):
        h = real_open(file, mode, *args, **kwargs)
        try:
            same = os.path.normcase(os.path.realpath(str(file))) in tgt
        except OSError:
            same = False
        if "r" in str(mode) and "b" in str(mode) and same:
            opens["n"] += 1
            if opens["n"] >= 2:
                # 第二别名捕获前把同一物理文件（同一 inode）改写为含 needle
                # 的文本——硬链接 JSON→文本复现攻击。
                with real_open(str(a), "wb") as g:
                    g.write(b"NEEDLE_P4D text version")
        return h

    monkeypatch.setattr(builtins, "open", swapping_open)
    rep = IndependentVerifier(c).verify(_submission(c, "run_p4d_0001"))
    assert opens["n"] == 2          # 两个别名各打开一次（不产生第三份快照）
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    alias = [ch for ch in rep.checks
             if ch.check_id == "evidence:snapshot_alias_mutated"]
    assert alias and alias[0].result is CheckResult.FAIL
    # 正对照：未改写的别名 → 同一物理文件同一事实 → 复用首快照 VERIFIED
    a2 = work_real / "data2.json"
    a2.write_bytes(b'{"k": "NEEDLE_P4D ok"}')
    b2 = work_real / "alias2.json"
    assert _make_file_link(b2, a2)
    exp2 = ArtifactExpectation(artifact_id="prod_doc", artifact_type="json_data",
                               expected_path=str(a2), required=True)
    crit2 = VerificationCriterion(criterion_id="cross2", kind="text_contains",
                                  params={"path": str(b2), "needle": "NEEDLE_P4D"})
    c2 = _content_contract(work_real, "wc_16f_p4d_ok_0001", expectations=(exp2,),
                           criteria=(crit2,))
    opens2 = {"n": 0}
    real_open2 = builtins.open
    tgt2 = {os.path.normcase(os.path.realpath(str(p))) for p in (a2, b2)}

    def counting_open2(file, mode="r", *args, **kwargs):
        h = real_open2(file, mode, *args, **kwargs)
        try:
            same = os.path.normcase(os.path.realpath(str(file))) in tgt2
        except OSError:
            same = False
        if "r" in str(mode) and "b" in str(mode) and same:
            opens2["n"] += 1
        return h

    monkeypatch.setattr(builtins, "open", counting_open2)
    rep2 = IndependentVerifier(c2).verify(_submission(c2, "run_p4d_ok_0001"))
    assert rep2.verdict is VerificationVerdict.VERIFIED
    assert opens2["n"] == 2          # 别名各打开一次但只允许一个事实快照
    assert not any(ch.check_id == "evidence:snapshot_alias_mutated"
                   for ch in rep2.checks)


# ================================================================
# Reviewer Patch 4 — P4-E/P4-F: 原子最终边界（BoundarySnapshot）
# ================================================================


def test_p4_e_last_callback_cannot_escape(env):
    """P4-E 否证：最终边界快照是唯一权威读取——最后一次回调的副作用必须被
    捕获且不可逃逸：(a) 最终边界内 cost 回调把 cost 0→6（limit=5）→
    BUDGET_EXHAUSTED；(b) 最终边界内 cancel 回调翻转为 True → CANCELLED；
    (c) 最终边界内 now 越过 deadline → TIMEOUT；(d) 最终边界内回调抛异常 →
    UNSTABLE_BOUNDARY——全部 final_report=None，VERIFIED 绝不成为成功结果。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) 最终边界（第 4 次 cost 读取）内 cost 0→6
    c = _verified_summary_contract(work_real, "wc_16f_p4e_a_0001")
    box = {"used": 0.0, "calls": 0}

    def cost_flip():
        box["calls"] += 1
        if box["calls"] == 4:
            box["used"] = 6.0
        return box["used"]

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            cost_used=cost_flip).run()
    assert out.attempts[0].verdict == "VERIFIED"      # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out.final_report is None

    # (b) 最终边界（第 4 次 cancel 读取）内翻转为 True
    c2 = _verified_summary_contract(work_real, "wc_16f_p4e_b_0001")
    flags = {"cancel": False, "calls": 0}

    def cancel_flip():
        flags["calls"] += 1
        if flags["calls"] == 4:
            flags["cancel"] = True
        return flags["cancel"]

    out2 = BoundedRepairLoop(contract=c2, verifier=IndependentVerifier(c2),
                             collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
                             cancel_requested=cancel_flip).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.CANCELLED
    assert out2.final_report is None

    # (c) 最终边界内的 now 读取越过 deadline（最终结果构造时越过 deadline）
    clock = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c3 = _contract(work_real, contract_id="wc_16f_p4e_c_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v3 = IndependentVerifier(c3, now_fn=clock)
    reads = {"n": 0}

    def now_cross_deadline():
        reads["n"] += 1
        if reads["n"] == 8:           # 最终边界内的 now 读取推进时钟越过 deadline
            clock.advance(20.0)
        return clock.t

    out3 = BoundedRepairLoop(contract=c3, verifier=v3,
                             collect_evidence=lambda a, r: _ok_summary_submission(c3, r),
                             now_fn=now_cross_deadline).run()
    assert out3.attempts[0].verdict == "VERIFIED"
    assert out3.stop_reason is RepairStopReason.TIMEOUT
    assert out3.final_report is None
    assert clock.t == 20.0

    # (d) 最终边界内回调抛异常 → 无法取得稳定安全结果 → fail-closed
    c4 = _verified_summary_contract(work_real, "wc_16f_p4e_d_0001")
    cancel_calls = {"n": 0}

    def cancel_boom():
        cancel_calls["n"] += 1
        if cancel_calls["n"] >= 4:    # 最终边界内 cancel 回调抛异常
            raise RuntimeError("final boundary callback exploded")
        return False

    out4 = BoundedRepairLoop(contract=c4, verifier=IndependentVerifier(c4),
                             collect_evidence=lambda a, r: _ok_summary_submission(c4, r),
                             cancel_requested=cancel_boom).run()
    assert out4.attempts[0].verdict == "VERIFIED"
    assert out4.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out4.final_report is None
    assert "final_boundary_unstable" in out4.diagnostic


def test_p4_f_no_post_boundary_now_callback(env):
    """P4-F 否证：接受 VERIFIED 前只原子读取**一次**最终 BoundarySnapshot——
    此后不再调用任何 now/cost/cancel/verifier 回调；RepairOutcome.finished_
    at_epoch 直接用 snapshot.now 构造（最后一个 now 值，零回调再发生）。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    c = _verified_summary_contract(work_real, "wc_16f_p4f_0001")
    now_calls: list = []
    clock = {"t": 0.0}

    def now_fn():
        now_calls.append(clock["t"])
        return clock["t"]

    cost_calls = {"n": 0}
    boundary_cost_idx = {"n": None}

    def cost_used():
        cost_calls["n"] += 1
        if cost_calls["n"] == 4:      # 最终边界内的 cost 读取
            boundary_cost_idx["n"] = len(now_calls)
        return 0.0

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c, now_fn=now_fn),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            cost_used=cost_used, now_fn=now_fn).run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert out.final_report is not None
    # 最终边界 cost 读取之后只允许边界自身的唯一一次 now 读取——零回调可再发生
    assert cost_calls["n"] == 4
    assert len(now_calls) == boundary_cost_idx["n"] + 1
    assert out.finished_at_epoch == now_calls[-1]


# ================================================================
# Reviewer Patch 4 — P4-G/P4-H: 完整秘密边界
# ================================================================


def test_p4_g_long_secret_fully_redacted(env):
    """P4-G 否证：600 字符秘密值必须**匹配至真实分隔符**整体脱敏——旧量词
    {0,512} 只匹配前 512 字符、尾部 88 字符泄漏；现在尾部零泄漏。键值对 /
    授权头 / 引号三种形态 + 端到端秘密形态路径异常回显。"""
    from furina.agent.verification import scrub_secrets
    secret = "sk-live-" + "A" * 600
    assert len(secret) > 512
    # 键值对形态
    s1 = scrub_secrets(f"x.api_key={secret} ok")
    assert secret not in s1 and "[REDACTED]" in s1
    # 授权头形态
    s2 = scrub_secrets(f"authorization: Bearer {secret}")
    assert secret not in s2 and "[REDACTED]" in s2
    # 引号形态
    s3 = scrub_secrets(f'password="{secret}"')
    assert secret not in s3 and "[REDACTED]" in s3
    # 端到端：秘密形态路径异常回显不得含长秘密尾部
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    evil = str(work_real / f"password={secret}.md")
    with pytest.raises(VerificationInputError) as ei:
        v.verify(_submission(c, "run_p4g_0001", declared=[_declared(evil)]))
    msg = str(ei.value)
    assert secret not in msg and "[REDACTED]" in msg


def test_p4_h_public_string_surfaces_secret_safe(env):
    """P4-H 否证：公开导出字符串类型封闭或脱敏——TerminalObservation.kind
    （16E 封闭词表）/ ArtifactObservation.source（expectation|declared）词表
    外值（含秘密形态）直接拒绝；rejection/name_mime/content_rejection/路径面
    统一脱敏——任意 to_dict()/to_digest_dict() 导出不含 raw secret；
    verifier_id 走 canonical validate_identity。"""
    from furina.agent.verification import (
        ArtifactObservation,
        EvidenceBundle,
        TerminalObservation,
    )
    secret = "api_key=sk-" + "B" * 40
    # kind 类型封闭（秘密形态/词表外值拒绝）
    with pytest.raises(VerificationError):
        TerminalObservation(event_id="evt_0001", kind=secret,
                            observed_at_epoch=1.0, bound=True)
    # source 类型封闭
    with pytest.raises(VerificationError):
        ArtifactObservation(secret, "doc", "/p/a.md", "/p/a.md", True, True,
                            True, 3, "text/plain", "0" * 64, "", "text/markdown")
    # 合法构造：字符串面带秘密形态 → 构造面脱敏，导出无 raw secret
    ao = ArtifactObservation("expectation", "doc", "/p/" + secret + ".md",
                             "/p/" + secret + ".md", True, True, True, 3,
                             "text/plain", "0" * 64,
                             "rejected:" + secret, "mime:" + secret,
                             "content:" + secret)
    ev = EvidenceBundle(contract_id="wc_16f_p4h_0001", contract_hash="0" * 64,
                        run_id="run_p4h_0001", backend_id="native_agent",
                        terminal=(), artifacts=(ao,))
    blob = json.dumps(ev.to_dict()) + json.dumps(ev.to_digest_dict())
    assert secret not in blob
    assert "[REDACTED]" in blob
    # verifier_id canonical（秘密形态直接拒绝，绝不脱敏后继续导出）
    base = dict(report_id="vrp_" + "a" * 32, verifier_id=VERIFIER_ID,
                contract_id="wc_16f_p4h_0001", contract_hash="0" * 64,
                standard_hash="0" * 64, run_id="run_p4h_0001",
                backend_id="native_agent", verdict=VerificationVerdict.FAILED,
                checks=(), diagnostics=(), evidence=ev,
                started_at_epoch=1.0, finished_at_epoch=2.0)
    kw = dict(base)
    kw["verifier_id"] = "password:hunter2"
    with pytest.raises(VerificationError):
        VerificationReport(**kw)


# ================================================================
# Reviewer Patch 4 — P4-I/P4-J: 执行前资源门 + 图像解码上界
# ================================================================


def test_p4_i_excessive_criteria_rejected_before_execution(env, monkeypatch):
    """P4-I 否证：契约判据数量使 check 估计超过 MAX_REPORT_CHECKS 时，在
    **任何文件读取或进程启动之前**拒绝（VerificationInputError）——零文件
    打开、零进程启动。"""
    import subprocess as sp

    tmp, work, work_real, outside, outside_real = env
    criteria = tuple(
        VerificationCriterion(criterion_id=f"crit_{i:03d}",
                              kind="artifact_file_exists",
                              params={"path": str(work_real / "x.md")})
        for i in range(MAX_REPORT_CHECKS + 1))
    c = _contract(work_real, contract_id="wc_16f_p4i_0001",
                  verification_standard=VerificationStandard(criteria=criteria))
    opens = {"n": 0}
    real_open = builtins.open
    tgt = os.path.normcase(os.path.realpath(str(work_real)))

    def counting_open(file, mode="r", *a, **k):
        try:
            if "r" in str(mode) and "b" in str(mode) \
                    and os.path.normcase(os.path.realpath(str(file))).startswith(tgt):
                opens["n"] += 1
        except OSError:
            pass
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", counting_open)
    popens = {"n": 0}
    real_popen = sp.Popen

    def counting_popen(*a, **k):
        popens["n"] += 1
        return real_popen(*a, **k)

    monkeypatch.setattr(sp, "Popen", counting_popen)
    with pytest.raises(VerificationInputError):
        IndependentVerifier(c).verify(_submission(c, "run_p4i_0001"))
    assert opens["n"] == 0            # 零文件读取
    assert popens["n"] == 0           # 零进程启动


def _png_header_bomb(width: int = 100000, height: int = 100000) -> bytes:
    """只含 IHDR（声明超大尺寸）的 PNG 头——解压炸弹；绝不被实际解码。"""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def test_p4_j_decompression_bomb_rejected_before_load(env):
    """P4-J 否证：头部声明超大尺寸的 PNG（解压炸弹）在 load() 前被 width/
    height/像素数上界拒绝（malformed_content:image_dimension / image_pixels /
    image_structure，Pillow DecompressionBombError 路径同样 fail-closed）——
    required FAIL、绝不 VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    for tag, blob in (("dimension", _png_header_bomb(9000, 9000)),
                      ("bomb_error", _png_header_bomb(100000, 100000)),
                      ("pixels", _png_header_bomb(5000, 100))):
        art = work_real / "bomb.png"
        art.write_bytes(blob)
        c = _expectation_contract(work_real, f"wc_16f_p4j_{tag}_0001",
                                  atype="png_image", path=art)
        rep = IndependentVerifier(c).verify(_submission(c, f"run_p4j_{tag}_0001"))
        assert rep.verdict is VerificationVerdict.FAILED, tag
        assert rep.authority_seal == ""
        assert any(ch.result is CheckResult.FAIL
                   and ch.explanation.startswith("malformed_content:image_")
                   for ch in rep.checks), tag


# ================================================================
# Reviewer Patch 5 — P5-A: 真正封闭最终边界（版本一致性协议）
# ================================================================

def test_p5_a_final_now_callback_mutating_cost_cannot_verify(env):
    """P5-A 锁定 1：最终边界内的 now 回调把 cost 0→6 —— 旧单次顺序读取
    （cancel→cost→now）下最后的 now_fn 改写已读取的 cost 会让越界 VERIFIED
    逃逸；版本一致性协议下必须不得 VERIFIED（final_report=None）。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) 改写发生在权威采集的 now₂（夹逼起点）——其后的 cost₂ 读取捕获
    clock = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c = _contract(work_real, contract_id="wc_16f_p5a_a_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    box = {"used": 0.0}
    nows = {"n": 0}

    def now_mutates_at_now2():
        nows["n"] += 1
        if nows["n"] == 10:           # acq2 的 now₂（权威采集夹逼起点）
            box["used"] = 6.0
        return clock.t

    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c, now_fn=now_mutates_at_now2),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        cost_used=lambda: box["used"], now_fn=now_mutates_at_now2).run()
    assert out.attempts[0].verdict == "VERIFIED"      # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out.final_report is None

    # (b) 改写发生在见证采集的 now₁——权威采集的 cost₂ 读取捕获
    clock2 = FakeClock(0.0)
    c2 = _contract(work_real, contract_id="wc_16f_p5a_b_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    box2 = {"used": 0.0}
    nows2 = {"n": 0}

    def now_mutates_at_now1():
        nows2["n"] += 1
        if nows2["n"] == 9:           # acq1 的 now₁（见证采集最后读取项）
            box2["used"] = 6.0
        return clock2.t

    out2 = BoundedRepairLoop(
        contract=c2, verifier=IndependentVerifier(c2, now_fn=now_mutates_at_now1),
        collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
        cost_used=lambda: box2["used"], now_fn=now_mutates_at_now1).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out2.final_report is None


def test_p5_a_last_read_rewrite_cannot_verify(env):
    """P5-A 锁定 2：最终边界采集内**任意读取项**改写其它边界状态 → 不得
    VERIFIED（worst-wins 聚合 + now 夹逼 cost/cancel 读取 + 尾随 cancel 见证
    全部拦截；越界后的 VERIFIED report 绝不成为成功结果）。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) cost 回调（见证采集）改写取消标志 → 权威采集 cancel 捕获 → CANCELLED
    c = _verified_summary_contract(work_real, "wc_16f_p5a_c_0001")
    flags = {"cancel": False}
    cost_calls = {"n": 0}

    def cost_rewrites_cancel():
        cost_calls["n"] += 1
        if cost_calls["n"] == 3:      # 见证采集的 cost₁
            flags["cancel"] = True
        return 0.0

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            cost_used=cost_rewrites_cancel,
                            cancel_requested=lambda: flags["cancel"]).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.CANCELLED
    assert out.final_report is None

    # (b) cost 回调（权威采集 cost₂）推进时钟 → 其后的 now₃ 捕获 → TIMEOUT
    clock = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c2 = _contract(work_real, contract_id="wc_16f_p5a_d_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    adv = {"n": 0}

    def cost_advances_at_cost2():
        adv["n"] += 1
        if adv["n"] == 4:             # 权威采集的 cost₂
            clock.advance(20.0)       # 0 → 20 > deadline 15
        return 0.0

    out2 = BoundedRepairLoop(contract=c2, verifier=IndependentVerifier(c2, now_fn=clock),
                             collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
                             cost_used=cost_advances_at_cost2, now_fn=clock).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.TIMEOUT
    assert out2.final_report is None
    assert clock.t == 20.0

    # (c) cancel 回调（权威采集 cancel₂）改写 cost → 其后的 cost₂ 捕获 →
    #     BUDGET_EXHAUSTED
    c3 = _verified_summary_contract(work_real, "wc_16f_p5a_e_0001")
    box3 = {"used": 0.0}
    cancels = {"n": 0}

    def cancel_rewrites_cost():
        cancels["n"] += 1
        if cancels["n"] == 4:         # 权威采集的 cancel₂
            box3["used"] = 6.0
        return False

    out3 = BoundedRepairLoop(contract=c3, verifier=IndependentVerifier(c3),
                             collect_evidence=lambda a, r: _ok_summary_submission(c3, r),
                             cost_used=lambda: box3["used"],
                             cancel_requested=cancel_rewrites_cost).run()
    assert out3.attempts[0].verdict == "VERIFIED"
    assert out3.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out3.final_report is None

    # (d) now 回调（权威采集 now₃）改写取消标志 → 尾随 cancel 见证捕获 →
    #     CANCELLED（"最后读取项改写其它状态"不再不可见）
    clock4 = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c4 = _contract(work_real, contract_id="wc_16f_p5a_f_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    flags4 = {"cancel": False}
    nows4 = {"n": 0}

    def now_rewrites_cancel():
        nows4["n"] += 1
        if nows4["n"] == 11:          # 权威采集的 now₃（最后的 now 读取）
            flags4["cancel"] = True
        return clock4.t

    out4 = BoundedRepairLoop(contract=c4,
                             verifier=IndependentVerifier(c4, now_fn=now_rewrites_cancel),
                             collect_evidence=lambda a, r: _ok_summary_submission(c4, r),
                             cancel_requested=lambda: flags4["cancel"],
                             now_fn=now_rewrites_cancel).run()
    assert out4.attempts[0].verdict == "VERIFIED"
    assert out4.stop_reason is RepairStopReason.CANCELLED
    assert out4.final_report is None


def test_p5_a_unprovable_snapshot_fail_closed(env):
    """P5-A 锁定 3：快照异常 / 版本变化（重入 → epoch 记账失配）/ 无法证明
    一致（时钟回拨 / 采集中途契约漂移）→ UNSTABLE_BOUNDARY fail-closed，
    final_report=None，VERIFIED 绝不成为成功结果。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) 权威采集内 now 回调抛异常 → 传播 → UNSTABLE_BOUNDARY
    clock = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c = _contract(work_real, contract_id="wc_16f_p5a_g_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    nows = {"n": 0}

    def now_boom():
        nows["n"] += 1
        if nows["n"] == 10:           # 权威采集的 now₂
            raise RuntimeError("now callback exploded")
        return clock.t

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c, now_fn=now_boom),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            now_fn=now_boom).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None
    assert "final_boundary_unstable" in out.diagnostic

    # (b) 版本变化：now 回调经仪表通道重入 cost 回调 → epoch 记账失配 →
    #     无法证明一致 → UNSTABLE_BOUNDARY
    c2 = _verified_summary_contract(work_real, "wc_16f_p5a_h_0001")
    nows2 = {"n": 0}
    loop2 = BoundedRepairLoop(
        contract=c2, verifier=IndependentVerifier(c2),
        collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
        cost_used=lambda: 0.0)

    def now_reenters():
        nows2["n"] += 1
        if nows2["n"] == 10:          # 最终边界采集内的 now 读取
            loop2._w_cost_used()      # 经仪表通道重入 → epoch 多记一次
        return 1000.0

    loop2._w_now = now_reenters       # 注入重入型 now 回调（同一仪表层）
    out2 = loop2.run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out2.final_report is None
    assert "final_boundary_unstable" in out2.diagnostic

    # (c) 时钟回拨：权威采集 now₂=5.0 → now₃=1.0（非单调）→ 无法证明一致
    clock3 = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c3 = _contract(work_real, contract_id="wc_16f_p5a_i_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    nows3 = {"n": 0}

    def now_backwards():
        nows3["n"] += 1
        if nows3["n"] == 10:          # 权威采集 now₂
            return 5.0
        if nows3["n"] == 11:          # 权威采集 now₃ —— 回拨
            return 1.0
        return clock3.t

    out3 = BoundedRepairLoop(contract=c3,
                             verifier=IndependentVerifier(c3, now_fn=now_backwards),
                             collect_evidence=lambda a, r: _ok_summary_submission(c3, r),
                             now_fn=now_backwards).run()
    assert out3.attempts[0].verdict == "VERIFIED"
    assert out3.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out3.final_report is None

    # (d) 采集中途契约漂移（两次采集 hash 不一致）→ 无法证明一致
    c4 = _verified_summary_contract(work_real, "wc_16f_p5a_j_0001")
    c_other = _contract(work_real, contract_id="wc_16f_p5a_j_other_0001")
    nows4 = {"n": 0}
    loop4 = BoundedRepairLoop(
        contract=c4, verifier=IndependentVerifier(c4),
        collect_evidence=lambda a, r: _ok_summary_submission(c4, r))

    def now_swaps_contract():
        nows4["n"] += 1
        if nows4["n"] == 10:          # 权威采集 now₂ 时改写契约
            loop4._contract = c_other
        return 1000.0

    loop4._w_now = now_swaps_contract
    out4 = loop4.run()
    assert out4.attempts[0].verdict == "VERIFIED"
    assert out4.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out4.final_report is None
    assert "final_boundary_unstable" in out4.diagnostic


def test_p5_a_stable_snapshot_verifies_with_snapshot_now(env, monkeypatch):
    """P5-A 锁定 4：正常稳定快照仍 VERIFIED，finished_at_epoch ==
    snapshot.now；成功边界之后零 cost/cancel/now/verifier 回调（P4-F 语义
    在新协议下保持：cost 恰 4 次、最终 cost 读取后恰一次 now 读取）。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    c = _verified_summary_contract(work_real, "wc_16f_p5a_k_0001")
    now_calls: list = []
    clock = {"t": 0.0}

    def now_fn():
        now_calls.append(clock["t"])
        return clock["t"]

    cost_calls = {"n": 0}
    boundary_cost_idx = {"n": None}

    def cost_used():
        cost_calls["n"] += 1
        if cost_calls["n"] == 4:      # 权威采集的 cost₂（最终边界内 cost 读取）
            boundary_cost_idx["n"] = len(now_calls)
        return 0.0

    captured: list = []
    orig_take = BoundedRepairLoop._take_final_boundary

    def spy_take(self):
        result = orig_take(self)
        captured.append(result)
        return result

    monkeypatch.setattr(BoundedRepairLoop, "_take_final_boundary", spy_take)
    loop = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c, now_fn=now_fn),
                             collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                             cost_used=cost_used, now_fn=now_fn)
    out = loop.run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert out.final_report is not None
    assert loop._verifier.seal_is_authentic(out.final_report) is True
    # 快照权威：finished_at_epoch == snapshot.now（最新权威 now 读数）
    bsnap, pre_reason, pre_diag = captured[0]
    assert pre_reason is None
    assert out.finished_at_epoch == bsnap.now
    assert bsnap.version > 0
    # 成功边界之后零回调：cost 恰 4 次；最终 cost 读取之后恰一次 now 读取
    assert cost_calls["n"] == 4
    assert len(now_calls) == boundary_cost_idx["n"] + 1
    assert out.finished_at_epoch == now_calls[-1]


# ================================================================
# Reviewer Patch 5 — P5-B: PDF 结构化字典键（去正则认定 Catalog/Pages）
# ================================================================

def _p5_pdf(root_body: bytes,
            pages_body: bytes = b"<</Type/Pages/Kids[3 0 R]/Count 1>>\n",
            page_body: bytes = b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>\n",
            trailer: bytes = b"trailer\n<</Size 4/Root 1 0 R>>\n") -> bytes:
    """程序化自洽最小 PDF（对象体可任意构造，偏移关系零手算漂移）。"""
    parts = [b"%PDF-1.4\n"]
    offsets: dict = {}
    for i, body in enumerate((root_body, pages_body, page_body), start=1):
        offsets[i] = sum(len(p) for p in parts)
        parts.append(b"%d 0 obj\n" % i)
        parts.append(body)
        parts.append(b"endobj\n")
    xref_pos = sum(len(p) for p in parts)
    parts.append(b"xref\n0 4\n")
    parts.append(b"0000000000 65535 f \n")
    for i in (1, 2, 3):
        parts.append(b"%010d 00000 n \n" % offsets[i])
    parts.append(trailer)
    parts.append(b"startxref\n%d\n" % xref_pos)
    parts.append(b"%%EOF\n")
    return b"".join(parts)


def test_p5_b_structured_dict_keys_reject_pseudo_keys(env):
    """P5-B 锁定：literal string / 注释 / 嵌套字典 / hex string 中的
    `/Type /Catalog`、`/Pages`、`/Type /Pages` token 不构成当前对象直接键；
    字典括号必须真实平衡；Root 直接 /Type 必须为 /Catalog、直接 /Pages 必须
    引用有效 Pages 对象、Pages 直接 /Type 必须为 /Pages；合法最小 PDF 正例
    与含嵌套字典值的合法 PDF 仍 PASS。"""
    tmp, work, work_real, outside, outside_real = env
    from furina.agent.verification import full_content_verdict
    # 正对照：合法最小 PDF
    assert full_content_verdict(_p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n")) \
        == ("application/pdf", "")
    # 正对照：Root 含嵌套字典值（括号真实平衡）仍 PASS——嵌套值不参与直接键
    assert full_content_verdict(_p5_pdf(b"<</Type/Catalog/Pages 2 0 R/Ext<</A 1>>>>\n")) \
        == ("application/pdf", "")
    cases = {
        # literal string 伪 /Type /Catalog（无直接 /Type 键）
        "string_pseudo_type":
            (b"<</X(/Type /Catalog)/Pages 2 0 R>>\n", "pdf_root_not_catalog"),
        # literal string 伪 /Pages（有直接 /Type /Catalog，无直接 /Pages 键）
        "string_pseudo_pages":
            (b"<</Type/Catalog/X(/Pages 2 0 R)>>\n", "pdf_root_no_pages"),
        # 注释伪键（注释内 token 绝不进入 token 流）
        "comment_pseudo_keys":
            (b"<</X 1% /Type /Catalog % /Pages 2 0 R\n>>\n", "pdf_root_not_catalog"),
        # 嵌套字典伪键
        "nested_pseudo_type":
            (b"<</X<</Type/Catalog/Pages 2 0 R>>>>\n", "pdf_root_not_catalog"),
        # /Type 的值是 literal string 而非 name
        "type_string_value":
            (b"<</Type(/Catalog)/Pages 2 0 R>>\n", "pdf_root_not_catalog"),
        # hex string 伪 name 值
        "type_hex_value":
            (b"<</Type<2F436174616C6F673E>/Pages 2 0 R>>\n", "pdf_root_not_catalog"),
        # 字典括号不平衡
        "unbalanced_dict":
            (b"<</Type/Catalog/Pages 2 0 R>\n", "pdf_obj_not_dict"),
    }
    for tag, (root_body, expect_rej) in cases.items():
        blob = _p5_pdf(root_body)
        mime, rejection = full_content_verdict(blob)
        assert mime == "application/pdf", tag
        assert rejection == f"malformed_content:{expect_rej}", (tag, rejection)
    # Pages 对象的 /Type 藏在嵌套字典里（无直接 /Type /Pages）→ fail-closed
    blob = _p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n",
                   pages_body=b"<</X<</Type/Pages>>/Count 1>>\n")
    assert full_content_verdict(blob) == ("application/pdf",
                                          "malformed_content:pdf_pages_not_pages")
    # trailer 的 /Root 藏在 literal string 里（无直接 /Root 键）→ fail-closed
    bad_trailer = _p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n",
                          trailer=b"trailer\n<</Size 4/(Root 1 0 R)>>\n")
    assert full_content_verdict(bad_trailer) == ("application/pdf",
                                                 "malformed_content:pdf_trailer_dict")
    # 端到端：string 伪键 PDF 作为 pdf_document 期望验证 → required FAIL
    art = work_real / "doc.pdf"
    art.write_bytes(_p5_pdf(b"<</X(/Type /Catalog)/Pages 2 0 R>>\n"))
    exp = ArtifactExpectation(artifact_id="prod_doc", artifact_type="pdf_document",
                              expected_path=str(art), required=True)
    c = _content_contract(work_real, "wc_16f_p5b_0001", expectations=(exp,))
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_p5b_0001",
        declared=[_declared(art, sha_hex=_sha(art.read_bytes()),
                            mime="application/pdf", artifact_id="prod_doc")]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    assert any(ch.result is CheckResult.FAIL
               and ch.explanation.startswith("malformed_content:pdf_root")
               for ch in rep.checks), [(ch.check_id, ch.explanation) for ch in rep.checks]


# ================================================================
# Reviewer Patch 5 — P5-C: 封闭全部公开导出字符串（逐字段审计）
# ================================================================

_P5_SHORT_SECRET = "password:hunter2"
_P5_LONG_SECRET = "api_key=" + "B" * 600

_P5_BUNDLE_KW = dict(contract_id="wc_16f_p5c_0001", contract_hash="0" * 64,
                     run_id="run_p5c_0001", backend_id="native_agent",
                     terminal=(), artifacts=())
_P5_REPORT_KW = dict(report_id="vrp_" + "a" * 32, verifier_id=VERIFIER_ID,
                     contract_id="wc_16f_p5c_0001", contract_hash="0" * 64,
                     standard_hash="0" * 64, run_id="run_p5c_0001",
                     backend_id="native_agent", verdict=VerificationVerdict.FAILED,
                     checks=(), diagnostics=(), started_at_epoch=1.0,
                     finished_at_epoch=2.0)


def _p5_export_blob(obj) -> str:
    """模型的全部导出面序列化（to_dict / to_digest_dict / digest_payload /
    to_json）——审计 raw secret 的唯一判定面。"""
    import json as _json
    chunks = []
    if hasattr(obj, "to_dict"):
        chunks.append(_json.dumps(obj.to_dict(), default=str))
    if hasattr(obj, "to_digest_dict"):
        chunks.append(_json.dumps(obj.to_digest_dict(), default=str))
    if hasattr(obj, "digest_payload"):
        chunks.append(str(obj.digest_payload()))
    if hasattr(obj, "to_json"):
        chunks.append(str(obj.to_json()))
    return "\n".join(chunks)


@pytest.mark.parametrize("secret", [_P5_SHORT_SECRET, _P5_LONG_SECRET])
def test_p5_c_public_export_surfaces_sealed(env, secret):
    """P5-C 锁定：五个公开模型的**每个可写字符串面**注入短/600 字符秘密——
    构造必须拒绝，或所有 to_dict()/to_digest_dict()/digest_payload()/to_json()
    导出均无 raw secret（每字段恰好属于：封闭词表 / canonical identity /
    严格格式值 / 存储前完整脱敏并限长）。"""
    from furina.agent.verification import (
        ArtifactObservation,
        EvidenceBundle,
        TerminalObservation,
        VerificationCheck,
    )

    def expect_reject(factory):
        with pytest.raises(VerificationError):
            factory()

    def expect_scrubbed(factory):
        obj = factory()
        # 观察模型的导出面在 EvidenceBundle 树上——单独构造时嵌入 bundle 审计
        if isinstance(obj, (TerminalObservation, ArtifactObservation)):
            container = "terminal" if isinstance(obj, TerminalObservation)                 else "artifacts"
            obj = EvidenceBundle(**{**_P5_BUNDLE_KW, container: (obj,)})
        blob = _p5_export_blob(obj)
        assert secret not in blob, blob[:400]
        assert "[REDACTED]" in blob

    # -- TerminalObservation：event_id=identity（拒）；kind=封闭词表（拒）
    expect_reject(lambda: TerminalObservation(event_id=secret, kind="backend.completed",
                                              observed_at_epoch=1.0, bound=True))
    expect_reject(lambda: TerminalObservation(event_id="evt_0001", kind=secret,
                                              observed_at_epoch=1.0, bound=True))

    # -- ArtifactObservation：source=封闭词表（拒）；artifact_id=identity（拒）；
    #    observed_mime=封闭 MIME 词表（拒）；observed_sha256=严格格式（拒）；
    #    路径/rejection/name_mime/content_rejection=脱敏限长
    expect_reject(lambda: ArtifactObservation(secret, "doc", "/p/a.md", "/p/a.md",
                                              True, True, True, 3, "text/plain",
                                              "0" * 64, ""))
    expect_reject(lambda: ArtifactObservation("expectation", secret, "/p/a.md",
                                              "/p/a.md", True, True, True, 3,
                                              "text/plain", "0" * 64, ""))
    expect_reject(lambda: ArtifactObservation("expectation", "doc", "/p/a.md",
                                              "/p/a.md", True, True, True, 3,
                                              secret, "0" * 64, ""))
    expect_reject(lambda: ArtifactObservation("expectation", "doc", "/p/a.md",
                                              "/p/a.md", True, True, True, 3,
                                              "text/plain", secret, ""))
    expect_scrubbed(lambda: ArtifactObservation(
        "expectation", "doc", "/p/" + secret + ".md", "/p/a.md", True, True,
        True, 3, "text/plain", "0" * 64, ""))
    expect_scrubbed(lambda: ArtifactObservation(
        "expectation", "doc", "/p/a.md", "/p/" + secret + ".md", True, True,
        True, 3, "text/plain", "0" * 64, ""))
    expect_scrubbed(lambda: ArtifactObservation(
        "expectation", "doc", "/p/a.md", "/p/a.md", True, True, True, 3,
        "text/plain", "0" * 64, rejection=secret))
    expect_scrubbed(lambda: ArtifactObservation(
        "expectation", "doc", "/p/a.md", "/p/a.md", True, True, True, 3,
        "text/plain", "0" * 64, rejection="", name_mime=secret))
    expect_scrubbed(lambda: ArtifactObservation(
        "expectation", "doc", "/p/a.md", "/p/a.md", True, True, True, 3,
        "text/plain", "0" * 64, rejection="", content_rejection=secret))

    # -- EvidenceBundle：身份（拒）/ contract_hash=严格格式（拒）/ 诊断（脱敏）
    expect_reject(lambda: EvidenceBundle(**{**_P5_BUNDLE_KW, "contract_id": secret}))
    expect_reject(lambda: EvidenceBundle(**{**_P5_BUNDLE_KW, "contract_hash": secret}))
    expect_reject(lambda: EvidenceBundle(**{**_P5_BUNDLE_KW, "run_id": secret}))
    expect_reject(lambda: EvidenceBundle(**{**_P5_BUNDLE_KW, "backend_id": secret}))
    expect_scrubbed(lambda: EvidenceBundle(
        **{**_P5_BUNDLE_KW, "diagnostics": (f"collect failed: {secret}",)}))

    # -- VerificationCheck：check_id/kind=identity（拒）；input 键（拒）；
    #    explanation/input 值（脱敏）
    expect_reject(lambda: VerificationCheck(check_id=secret, kind="artifact_mime",
                                            required=True, result=CheckResult.FAIL))
    expect_reject(lambda: VerificationCheck(check_id="criterion:x_0001", kind=secret,
                                            required=True, result=CheckResult.FAIL))
    expect_reject(lambda: VerificationCheck(
        check_id="criterion:x_0001", kind="artifact_mime", required=True,
        result=CheckResult.FAIL, inputs=((secret, "v"),)))
    expect_scrubbed(lambda: VerificationCheck(
        check_id="criterion:x_0001", kind="artifact_mime", required=True,
        result=CheckResult.FAIL, explanation=f"needle {secret} leaked"))
    expect_scrubbed(lambda: VerificationCheck(
        check_id="criterion:x_0001", kind="artifact_mime", required=True,
        result=CheckResult.FAIL, inputs=(("path", secret),)))

    # -- VerificationReport：身份/hash/seal（拒）；诊断（脱敏）
    def _report(**over):
        ev = EvidenceBundle(**_P5_BUNDLE_KW)
        return VerificationReport(**{**_P5_REPORT_KW, "evidence": ev, **over})

    expect_reject(lambda: _report(report_id=secret))
    expect_reject(lambda: _report(verifier_id=secret))
    expect_reject(lambda: _report(contract_id=secret))
    expect_reject(lambda: _report(contract_hash=secret))
    expect_reject(lambda: _report(standard_hash=secret))
    expect_reject(lambda: _report(run_id=secret))
    expect_reject(lambda: _report(backend_id=secret))
    expect_reject(lambda: _report(authority_seal=secret))   # 非 VERIFIED 不得携带 seal
    expect_scrubbed(lambda: _report(diagnostics=(f"boom: {secret}",)))


def test_p5_c_secret_rejection_messages_redacted(env):
    """P5-C 纵深：拒绝面的异常消息同样不得回显 raw secret（canonical
    rejector 与 scrubber 共享同一秘密边界）。"""
    from furina.agent.verification import VerificationCheck
    check_id_secret = "password:" + "S" * 600
    with pytest.raises(VerificationError) as ei:
        VerificationCheck(check_id=check_id_secret, kind="artifact_mime",
                          required=True, result=CheckResult.FAIL)
    assert "SSSS" not in str(ei.value)
    key_secret = "api_key=" + "K" * 600
    with pytest.raises(VerificationError) as ei2:
        VerificationCheck(check_id="criterion:x_0001", kind="artifact_mime",
                          required=True, result=CheckResult.FAIL,
                          inputs=((key_secret, "v"),))
    assert "KKKK" not in str(ei2.value)
