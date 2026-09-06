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
    BoundarySnapshot,
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


class _BoundarySource:
    """P6-A 受控共享边界状态：**单一权威边界快照源**（version 协议）。

    ``snapshot()`` 单次调用原子返回冻结、严格类型校验的
    :class:`BoundarySnapshot`（P7-A 精确类型协议）——内部回调
    （``on_read`` 钩子，可注入对抗性副作用）可改写共享状态，但快照值一律
    在全部内部回调完成后一次性读取（改写随快照整体可见——这正是独立回调
    组成的有限读取序列做不到的）；任何状态变更递增 version（协议义务）。
    ``fail_reads``/``bump_on_read`` 用于锁定"源异常 / 版本不一致 →
    fail-closed"。
    """

    def __init__(self, contract: WorkContract, *, cost=None, cancel=False,
                 now: float = 1000.0, version: int = 1, on_read=None,
                 fail_reads: tuple = (), bump_on_read: tuple = ()) -> None:
        self.contract = contract
        self.cost = cost
        self.cancel = cancel
        self.now = float(now)
        self.version = int(version)
        self.on_read = on_read
        self.fail_reads = tuple(fail_reads)
        self.bump_on_read = tuple(bump_on_read)
        self.reads = 0

    def snapshot(self) -> BoundarySnapshot:
        self.reads += 1
        if self.reads in self.fail_reads:
            raise RuntimeError("boundary snapshot source exploded")
        before = (self.cancel, self.cost)
        if self.on_read is not None:
            self.on_read(self)
        if (self.cancel, self.cost) != before:
            self.version += 1          # 协议：状态任何变更必须递增 version
        if self.reads in self.bump_on_read:
            self.version += 1          # 注入版本不一致（无状态变更也递增）
        return BoundarySnapshot(contract_hash=self.contract.content_hash,
                                cancelled=bool(self.cancel),
                                cost_used=self.cost,
                                now=float(self.now), version=self.version)


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

    loop = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector2,
                             now_fn=FakeClock(500.0),
                             boundary_snapshot=_BoundarySource(c).snapshot)
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
    report 不得成为成功结果（final_report=None）。P6-A：取消事实经单一权威
    快照源在最终边界原子可见（改写在值读取前完成、随快照整体暴露）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_run_contract(work_real, "wc_16f_b4cancel_0001")
    v = IndependentVerifier(c)
    art = work_real / "summary.md"
    flags = {"cancelled": False}

    def collector(attempt_id, run_id):
        flags["cancelled"] = True          # collect/verify 期间出现取消
        return _submission(c, run_id, declared=[_declared(art, sha_hex=_sha(b"ok"))])

    src = _BoundarySource(c)
    src.on_read = lambda s: setattr(s, "cancel", flags["cancelled"])
    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector,
                            cancel_requested=lambda: flags["cancelled"],
                            boundary_snapshot=src.snapshot).run()
    assert out.attempts[0].verdict == "VERIFIED"      # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.CANCELLED
    assert out.final_report is None                   # 绝不作为成功结果
    assert len(out.attempts) == 1


def test_post_attempt_cost_overrun_blocks_verified(env):
    """B4 否证：attempt 完成后 used > limit → BUDGET_EXHAUSTED，VERIFIED
    report 不成为成功结果。P6-A：成本越界事实经单一权威快照源在最终边界
    原子可见（见证读取即暴露，零第二读取）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_run_contract(work_real, "wc_16f_b4cost_0001")
    v = IndependentVerifier(c)
    art = work_real / "summary.md"
    calls = {"n": 0}

    def cost_used():
        calls["n"] += 1
        # 前两次预检（0.0×2）允许 attempt 执行。
        return 0.0 if calls["n"] <= 2 else 6.0

    src = _BoundarySource(c)
    src.on_read = lambda s: setattr(s, "cost", 6.0)   # 最终边界内 cost 0→6
    out = BoundedRepairLoop(
        contract=c, verifier=v,
        collect_evidence=lambda a, r: _submission(
            c, r, declared=[_declared(art, sha_hex=_sha(b"ok"))]),
        cost_used=cost_used, boundary_snapshot=src.snapshot).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out.final_report is None
    assert len(out.attempts) == 1


def test_post_attempt_deadline_blocks_verified(env):
    """B4 否证：完成时间 > deadline → TIMEOUT，VERIFIED report 不成为成功
    结果。P6-A：超时事实经单一权威快照源在最终边界原子可见。"""
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

    src = _BoundarySource(c)
    src.on_read = lambda s: setattr(s, "now", clock.t)   # 快照读取实时时钟
    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector,
                            now_fn=clock, boundary_snapshot=src.snapshot).run()
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


def test_p2_k_foreign_verifier_subclass_rejected_at_assembly(env):
    """P2-K 否证（P10-B1 装配期拒绝协议适配）：子类代理 verifier（可覆盖
    verify()/seal_is_authentic()）在装配阶段即被 exact trusted type 拒绝；
    外来签发的 VERIFIED 报告也无法通过绑定验证器的 seal 复核——绝不修补或
    重签外来报告，本验证器正常验证路径不受影响。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p2k_0001")
    foreign = IndependentVerifier(c)          # 另一密钥的真实验证器
    with pytest.raises(VerificationError):
        BoundedRepairLoop(
            contract=c, verifier=_ForeignSignerVerifier(c, foreign),
            collect_evidence=lambda a, r: _ok_summary_submission(c, r))
    # 外来签发的 VERIFIED 报告无法通过绑定验证器 seal 复核
    bound = IndependentVerifier(c)
    foreign_rep = foreign.verify(_ok_summary_submission(c, "run_p2k_0001"))
    assert foreign_rep.verdict is VerificationVerdict.VERIFIED
    assert bound.seal_is_authentic(foreign_rep) is False
    # 绑定验证器自身的权威路径正常工作
    out = BoundedRepairLoop(
        contract=c, verifier=bound,
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        now_fn=FakeClock(500.0),
        boundary_snapshot=_BoundarySource(c, cost=0.0).snapshot).run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert out.final_report is not None
    assert bound.seal_is_authentic(out.final_report) is True


def test_p2_l_stale_or_foreign_contract_report_rejected(env):
    """P2-L 否证（P10-B1 协议适配）：seal 真实但 run_id 属旧 attempt 的
    报告、以及异契约验证器签发的报告，都在精确身份复核面被拒绝（经真实验
    证器产出报告 + 接受门直接复核证明；子类代理已在装配期拒绝）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p2l_0001")
    v = IndependentVerifier(c)
    # (a) 陈旧 run：报告由绑定验证器真实签发（seal 可过），但 run_id 不属于
    #     本次 attempt → run_id 精确不一致拒绝。
    stale = v.verify(_ok_summary_submission(c, "run_stale_0001"))
    assert stale.verdict is VerificationVerdict.VERIFIED
    loop = BoundedRepairLoop(
        contract=c, verifier=v,
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        now_fn=FakeClock(500.0),
        boundary_snapshot=_BoundarySource(c, cost=0.0).snapshot)
    accepted, why = loop._accept_verified_report(stale, "run_actual_0001")
    assert accepted is False
    assert "run_id_mismatch" in why
    # (b) 异契约：另一契约验证器签发的 VERIFIED 报告（seal/契约身份全不符；
    #     c2 使用不同判据 → standard_hash 也不一致）——经接受门直接复核拒绝。
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
    accepted2, why2 = loop._accept_verified_report(foreign_rep, "run_actual_0001")
    assert accepted2 is False
    assert "contract_id_mismatch" in why2 \
        and "standard_hash_mismatch" in why2 \
        and "run_id_mismatch" in why2


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
    cost meter 回调把时钟推进到 20 → 最终边界（P6-A 单一权威快照源——快照
    源内部的 cost 回调推时钟，改写随快照整体可见）必须用**新鲜时间**判定
    TIMEOUT，越界 VERIFIED 丢弃（final_report=None）。"""
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

    src = _BoundarySource(c)

    def cost_read_advances_clock(s):
        if s.reads == 1:                   # 见证读取内的 cost 回调推进时钟
            clock.advance(10.0)            # 10 → 20 > deadline 15
        s.now = clock.t

    src.on_read = cost_read_advances_clock
    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector,
                            now_fn=clock, boundary_snapshot=src.snapshot).run()
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
    """P3-G 否证（任务书复现用例）：接受 VERIFIED 前的最终边界（P6-A 单一
    权威快照源——源内部回调的改写在快照值读取前完成、随快照整体可见）中
    cancellation 回调把 cost 从 0 改成 6（limit=5）→ 见证读取捕获 →
    BUDGET_EXHAUSTED / final_report=None（绝不 VERIFIED）；cost 回调在快照
    读取内推进时钟 → 快照时间越过 deadline → TIMEOUT；快照源回调异常 →
    UNSTABLE_BOUNDARY fail-closed。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) 快照源内部的 cancellation 回调修改 cost（limit=5，cost 0→6）
    c = _verified_summary_contract(work_real, "wc_16f_p3g_a_0001")

    def cancel_flips_cost(s):
        s.cancel = False                    # cancel 回调返回 False
        s.cost = 6.0                        # ……但内部改写 cost 0→6（随快照可见）

    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        boundary_snapshot=_BoundarySource(c, cost=0.0,
                                          on_read=cancel_flips_cost).snapshot).run()
    assert out.attempts[0].verdict == "VERIFIED"     # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out.final_report is None

    # (b) 快照源内部的 cost 回调推进时钟 → 快照时间越过 deadline → TIMEOUT
    clock = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c2 = _contract(work_real, contract_id="wc_16f_p3g_b_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v2 = IndependentVerifier(c2, now_fn=clock)

    def cost_advances_clock(s):
        if s.reads == 1:                    # 见证读取内的 cost 回调推进时钟
            clock.advance(20.0)             # 0 → 20 > deadline 15
        s.now = clock.t

    out2 = BoundedRepairLoop(
        contract=c2, verifier=v2,
        collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
        boundary_snapshot=_BoundarySource(c2, cost=0.0,
                                          on_read=cost_advances_clock).snapshot,
        now_fn=clock).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.TIMEOUT
    assert out2.final_report is None
    assert clock.t == 20.0

    # (c) 快照源内部回调异常 → 无法取得稳定安全结果 → fail-closed
    c3 = _verified_summary_contract(work_real, "wc_16f_p3g_c_0001")
    out3 = BoundedRepairLoop(
        contract=c3, verifier=IndependentVerifier(c3),
        collect_evidence=lambda a, r: _ok_summary_submission(c3, r),
        boundary_snapshot=_BoundarySource(c3, fail_reads=(1,)).snapshot).run()
    assert out3.attempts[0].verdict == "VERIFIED"
    assert out3.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out3.final_report is None
    assert "final_boundary_unstable" in out3.diagnostic


def test_p3_h_authentication_mutates_deadline_or_cancel(env):
    """P3-H 否证（P10-B1 装配期拒绝协议适配）：seal 认证 / standard_hash 的
    子类 override 副作用通道已在装配阶段被 exact trusted type 关闭——两类
    攻击 verifier 均拒绝进入权威路径（接受门内的残余副作用面由 P6-A/P7-D
    单一权威快照协议锁定保持：认证只发生在快照之前，其后零回调）。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) seal 认证回调翻转 cancellation 的攻击 verifier
    c = _verified_summary_contract(work_real, "wc_16f_p3h_a_0001")
    flags = {"cancel": False}

    class _SealSideEffectVerifier(IndependentVerifier):
        def seal_is_authentic(self, report):
            flags["cancel"] = True       # 认证回调副作用：翻转取消标志
            return super().seal_is_authentic(report)

    src = _BoundarySource(c)
    src.on_read = lambda s: setattr(s, "cancel", flags["cancel"])
    with pytest.raises(VerificationError):
        BoundedRepairLoop(
            contract=c, verifier=_SealSideEffectVerifier(c),
            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
            cancel_requested=lambda: flags["cancel"],
            boundary_snapshot=src.snapshot)

    # (b) standard_hash 属性回调推进时钟越过 deadline 的攻击 verifier
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
    src2 = _BoundarySource(c2)
    src2.on_read = lambda s: setattr(s, "now", clock.t)
    with pytest.raises(VerificationError):
        BoundedRepairLoop(
            contract=c2, verifier=v2,
            collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
            now_fn=clock, boundary_snapshot=src2.snapshot)


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
    """P4-E 否证：最终边界快照是唯一权威读取（P6-A 单一权威快照源——源内部
    最后一个回调的改写在快照值读取前完成、随快照整体可见，绝不可见副作用
    逃逸）：(a) 快照源内部 cost 0→6（limit=5）→ BUDGET_EXHAUSTED；
    (b) 快照源内部 cancel 翻转为 True → CANCELLED；(c) 快照源内部时钟越过
    deadline → TIMEOUT；(d) 快照源回调抛异常 → UNSTABLE_BOUNDARY——全部
    final_report=None，VERIFIED 绝不成为成功结果。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) 快照源内部 cost 0→6
    c = _verified_summary_contract(work_real, "wc_16f_p4e_a_0001")

    def cost_flip(s):
        s.cost = 6.0

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            boundary_snapshot=_BoundarySource(
                                c, cost=0.0, on_read=cost_flip).snapshot).run()
    assert out.attempts[0].verdict == "VERIFIED"      # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out.final_report is None

    # (b) 快照源内部 cancel 翻转为 True
    c2 = _verified_summary_contract(work_real, "wc_16f_p4e_b_0001")

    def cancel_flip(s):
        s.cancel = True

    out2 = BoundedRepairLoop(contract=c2, verifier=IndependentVerifier(c2),
                             collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
                             boundary_snapshot=_BoundarySource(
                                 c2, on_read=cancel_flip).snapshot).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.CANCELLED
    assert out2.final_report is None

    # (c) 快照源内部时钟越过 deadline
    clock = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c3 = _contract(work_real, contract_id="wc_16f_p4e_c_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v3 = IndependentVerifier(c3, now_fn=clock)

    def now_cross_deadline(s):
        if s.reads == 1:                  # 快照源内部推进时钟越过 deadline
            clock.advance(20.0)
        s.now = clock.t

    out3 = BoundedRepairLoop(contract=c3, verifier=v3,
                             collect_evidence=lambda a, r: _ok_summary_submission(c3, r),
                             now_fn=clock,
                             boundary_snapshot=_BoundarySource(
                                 c3, on_read=now_cross_deadline).snapshot).run()
    assert out3.attempts[0].verdict == "VERIFIED"
    assert out3.stop_reason is RepairStopReason.TIMEOUT
    assert out3.final_report is None
    assert clock.t == 20.0

    # (d) 快照源回调抛异常 → 无法取得稳定安全结果 → fail-closed
    c4 = _verified_summary_contract(work_real, "wc_16f_p4e_d_0001")
    out4 = BoundedRepairLoop(contract=c4, verifier=IndependentVerifier(c4),
                             collect_evidence=lambda a, r: _ok_summary_submission(c4, r),
                             boundary_snapshot=_BoundarySource(
                                 c4, fail_reads=(1,)).snapshot).run()
    assert out4.attempts[0].verdict == "VERIFIED"
    assert out4.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out4.final_report is None
    assert "final_boundary_unstable" in out4.diagnostic


def test_p4_f_no_post_boundary_now_callback(env):
    """P4-F 否证（P6-A 单一权威快照源下保持）：接受 VERIFIED 前只对快照源
    恰好读取**两次**（见证 + 权威，均为原子单调用）——两次读取之间与权威
    快照之后**零** now/cost/cancel/verifier 回调；RepairOutcome.finished_
    at_epoch 直接用 snapshot.now 构造（快照时间，零回调再发生）。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    c = _verified_summary_contract(work_real, "wc_16f_p4f_0001")
    events: list = []
    clock = {"t": 0.0}

    def now_fn():
        events.append("now")
        return clock["t"]

    def cost_used():
        events.append("cost")
        return 0.0

    def cancel_requested():
        events.append("cancel")
        return False

    src = _BoundarySource(c, cost=0.0, now=500.0)   # 快照时间在 deadline 内

    def snap(_s):
        events.append("snap")

    src.on_read = snap
    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c, now_fn=now_fn),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            cost_used=cost_used, cancel_requested=cancel_requested,
                            now_fn=now_fn, boundary_snapshot=src.snapshot).run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert out.final_report is not None
    # 恰好两次快照读取（见证 + 权威）；第一次快照之后只剩第二次快照——
    # 零 now/cost/cancel 回调再发生；完成时间取快照时间。
    assert src.reads == 2
    after_first_snap = events[events.index("snap"):]
    assert after_first_snap == ["snap", "snap"]
    assert out.finished_at_epoch == 500.0


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
# Reviewer Patch 5 — P5-A（P6-A 单一权威快照源协议下保留并适配）：
# 最终边界只信任单一权威快照源——独立 effectful 回调的有限读取序列
# （含 P4-D 单次顺序读取与 P5-A 双重采集 + epoch 记账）都是伪原子，
# 已被 P6-A 移除；本组测试在源协议下锁定同等对抗语义。
# ================================================================

def test_p5_a_final_now_callback_mutating_cost_cannot_verify(env):
    """P5-A 锁定 1（P6-A 源协议适配）：快照源内部的 now 回调把 cost 0→6 ——
    (a) 改写发生在见证读取内 → 见证值随快照整体暴露 → BUDGET_EXHAUSTED；
    (b) 改写发生在权威读取内（version 随状态变更递增）→ 两次读取版本不一致
    → UNSTABLE_BOUNDARY。全部不得 VERIFIED（final_report=None）。"""
    tmp, work, work_real, outside, outside_real = env
    clock = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c = _contract(work_real, contract_id="wc_16f_p5a_a_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))

    def now_mutates_cost_in_witness(s):
        s.now = clock.t
        if s.reads == 1:                  # 见证读取内的最终回调改写 cost
            s.cost = 6.0

    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c, now_fn=clock),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        now_fn=clock,
        boundary_snapshot=_BoundarySource(c, cost=0.0,
                                          on_read=now_mutates_cost_in_witness).snapshot).run()
    assert out.attempts[0].verdict == "VERIFIED"      # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out.final_report is None

    # (b) 改写发生在权威读取内 → version 随变更递增 → 两次读取版本不一致
    c2 = _contract(work_real, contract_id="wc_16f_p5a_b_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    clock2 = FakeClock(0.0)

    def now_mutates_cost_in_authority(s):
        s.now = clock2.t
        if s.reads == 2:                  # 权威读取内的最终回调改写 cost
            s.cost = 6.0                  # （version 协议义务：随变更递增）

    out2 = BoundedRepairLoop(
        contract=c2, verifier=IndependentVerifier(c2, now_fn=clock2),
        collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
        now_fn=clock2,
        boundary_snapshot=_BoundarySource(c2, cost=0.0,
                                          on_read=now_mutates_cost_in_authority).snapshot).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out2.final_report is None
    assert "final_boundary_unstable" in out2.diagnostic


def test_p5_a_last_read_rewrite_cannot_verify(env):
    """P5-A 锁定 2（P6-A 源协议适配）：快照源内部**最后一个回调**改写其它
    边界状态 → 改写随快照整体可见 → 不得 VERIFIED（见证读取即捕获）。
    (a) cost 回调改写取消标志 → CANCELLED；(b) cost 回调推进时钟 → TIMEOUT；
    (c) cancel 回调改写 cost → BUDGET_EXHAUSTED；(d) now 回调改写取消标志 →
    CANCELLED——全部 final_report=None。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) cost 回调改写取消标志
    c = _verified_summary_contract(work_real, "wc_16f_p5a_c_0001")

    def cost_rewrites_cancel(s):
        s.cost = 0.0
        s.cancel = True

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            boundary_snapshot=_BoundarySource(
                                c, cost=0.0, on_read=cost_rewrites_cancel).snapshot).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.CANCELLED
    assert out.final_report is None

    # (b) cost 回调推进时钟
    clock = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c2 = _contract(work_real, contract_id="wc_16f_p5a_d_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))

    def cost_advances_clock(s):
        s.cost = 0.0
        if s.reads == 1:
            clock.advance(20.0)           # 0 → 20 > deadline 15
        s.now = clock.t

    out2 = BoundedRepairLoop(contract=c2, verifier=IndependentVerifier(c2, now_fn=clock),
                             collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
                             now_fn=clock,
                             boundary_snapshot=_BoundarySource(
                                 c2, cost=0.0, on_read=cost_advances_clock).snapshot).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.TIMEOUT
    assert out2.final_report is None
    assert clock.t == 20.0

    # (c) cancel 回调改写 cost
    c3 = _verified_summary_contract(work_real, "wc_16f_p5a_e_0001")

    def cancel_rewrites_cost(s):
        s.cancel = False
        s.cost = 6.0

    out3 = BoundedRepairLoop(contract=c3, verifier=IndependentVerifier(c3),
                             collect_evidence=lambda a, r: _ok_summary_submission(c3, r),
                             boundary_snapshot=_BoundarySource(
                                 c3, cost=0.0, on_read=cancel_rewrites_cost).snapshot).run()
    assert out3.attempts[0].verdict == "VERIFIED"
    assert out3.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out3.final_report is None

    # (d) now 回调改写取消标志
    clock4 = FakeClock(0.0)
    (work_real / "summary.md").write_bytes(b"ok")
    c4 = _contract(work_real, contract_id="wc_16f_p5a_f_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))

    def now_rewrites_cancel(s):
        s.now = clock4.t
        s.cancel = True

    out4 = BoundedRepairLoop(contract=c4,
                             verifier=IndependentVerifier(c4, now_fn=clock4),
                             collect_evidence=lambda a, r: _ok_summary_submission(c4, r),
                             now_fn=clock4,
                             boundary_snapshot=_BoundarySource(
                                 c4, on_read=now_rewrites_cancel).snapshot).run()
    assert out4.attempts[0].verdict == "VERIFIED"
    assert out4.stop_reason is RepairStopReason.CANCELLED
    assert out4.final_report is None


def test_p5_a_unprovable_snapshot_fail_closed(env):
    """P5-A 锁定 3（P6-A 源协议适配）：快照源异常 / 版本不一致 / 值漂移 /
    时钟回拨 / 采集中途契约漂移 → UNSTABLE_BOUNDARY fail-closed，
    final_report=None，VERIFIED 绝不成为成功结果。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    # P9-B4 时钟协议适配：repair 时钟（FakeClock 990）与快照时钟（now=1000）
    # 同一可比时间轴——快照 now ∈ [可信时钟, deadline]，时钟回退否证只考察
    # 快照内部两次读取的单调性（语义断言零改动）。
    # (a) 权威读取内快照源回调抛异常 → 传播 → UNSTABLE_BOUNDARY
    c = _contract(work_real, contract_id="wc_16f_p5a_g_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            now_fn=FakeClock(990.0),
                            boundary_snapshot=_BoundarySource(
                                c, fail_reads=(2,)).snapshot).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None
    assert "final_boundary_unstable" in out.diagnostic

    # (b) 版本不一致：两次读取间 version 递增（无对应状态变更证明）→
    #     无法取得同一状态版本 → UNSTABLE_BOUNDARY
    c2 = _verified_summary_contract(work_real, "wc_16f_p5a_h_0001")
    out2 = BoundedRepairLoop(contract=c2, verifier=IndependentVerifier(c2),
                             collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
                             now_fn=FakeClock(990.0),
                             boundary_snapshot=_BoundarySource(
                                 c2, bump_on_read=(2,)).snapshot).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out2.final_report is None
    assert "final_boundary_unstable" in out2.diagnostic

    # (c) 时钟回拨：权威读取 now < 见证 now（非单调）→ UNSTABLE_BOUNDARY
    c3 = _contract(work_real, contract_id="wc_16f_p5a_i_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))

    def now_backwards(s):
        s.now = 5.0 if s.reads == 2 else 1000.0   # 权威读取回拨

    out3 = BoundedRepairLoop(contract=c3, verifier=IndependentVerifier(c3),
                             collect_evidence=lambda a, r: _ok_summary_submission(c3, r),
                             now_fn=FakeClock(990.0),
                             boundary_snapshot=_BoundarySource(
                                 c3, on_read=now_backwards).snapshot).run()
    assert out3.attempts[0].verdict == "VERIFIED"
    assert out3.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out3.final_report is None

    # (d) 采集中途契约漂移（两次读取 hash 不一致）→ UNSTABLE_BOUNDARY
    c4 = _verified_summary_contract(work_real, "wc_16f_p5a_j_0001")
    c_other = _contract(work_real, contract_id="wc_16f_p5a_j_other_0001")

    def swap_contract(s):
        if s.reads == 2:
            s.contract = c_other

    out4 = BoundedRepairLoop(contract=c4, verifier=IndependentVerifier(c4),
                             collect_evidence=lambda a, r: _ok_summary_submission(c4, r),
                             now_fn=FakeClock(990.0),
                             boundary_snapshot=_BoundarySource(
                                 c4, on_read=swap_contract).snapshot).run()
    assert out4.attempts[0].verdict == "VERIFIED"
    assert out4.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out4.final_report is None
    assert "final_boundary_unstable" in out4.diagnostic


def test_p5_a_stable_snapshot_verifies_with_snapshot_now(env, monkeypatch):
    """P5-A 锁定 4（P6-A 源协议适配）：稳定快照（两次读取同版本、逐值一致、
    时钟单调）仍 VERIFIED，finished_at_epoch == snapshot.now；权威快照之后
    零 cost/cancel/now/verifier 回调、零快照读取。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    c = _verified_summary_contract(work_real, "wc_16f_p5a_k_0001")
    events: list = []

    def now_fn():
        events.append("now")
        return 0.0

    def cost_used():
        events.append("cost")
        return 0.0

    src = _BoundarySource(c, cost=0.0, now=500.0)   # 快照时间在 deadline 内

    def snap(_s):
        events.append("snap")

    src.on_read = snap
    captured: list = []
    orig_take = BoundedRepairLoop._take_final_boundary

    def spy_take(self):
        result = orig_take(self)
        captured.append(result)
        return result

    monkeypatch.setattr(BoundedRepairLoop, "_take_final_boundary", spy_take)
    loop = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c, now_fn=now_fn),
                             collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                             cost_used=cost_used, now_fn=now_fn,
                             boundary_snapshot=src.snapshot)
    out = loop.run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert out.final_report is not None
    assert loop._verifier.seal_is_authentic(out.final_report) is True
    # 快照权威：finished_at_epoch == snapshot.now，版本一致
    bsnap, pre_reason, pre_diag = captured[0]
    assert pre_reason is None
    assert out.finished_at_epoch == bsnap.now
    assert bsnap.version > 0
    # 恰好两次快照读取（见证 + 权威）；第一次快照之后只剩第二次快照——
    # 零 cost/now 回调再发生。
    assert src.reads == 2
    after_first_snap = events[events.index("snap"):]
    assert after_first_snap == ["snap", "snap"]
    assert out.finished_at_epoch == 500.0


# ================================================================
# Reviewer Patch 5 — P5-B: PDF 结构化字典键（去正则认定 Catalog/Pages）
# ================================================================

def _p5_pdf(root_body: bytes,
            pages_body: bytes = b"<</Type/Pages/Kids[3 0 R]/Count 1>>\n",
            page_body: bytes = b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>\n",
            trailer: bytes = b"trailer\n<</Size 4/Root 1 0 R>>\n",
            gens: tuple = (0, 0, 0),
            xref_gen: int = 0) -> bytes:
    """程序化自洽最小 PDF（对象体/对象 generation/xref generation 可任意构造，
    偏移关系零手算漂移）。"""
    parts = [b"%PDF-1.4\n"]
    offsets: dict = {}
    for i, body in enumerate((root_body, pages_body, page_body), start=1):
        offsets[i] = sum(len(p) for p in parts)
        parts.append(b"%d %d obj\n" % (i, gens[i - 1]))
        parts.append(body)
        parts.append(b"endobj\n")
    xref_pos = sum(len(p) for p in parts)
    parts.append(b"xref\n0 4\n")
    parts.append(b"0000000000 65535 f \n")
    for i in (1, 2, 3):
        parts.append(b"%010d %05d n \n" % (offsets[i], xref_gen))
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


# ================================================================
# Reviewer Patch 6 — P6-A: 移除伪原子有限回调协议（单一权威快照源）
# ================================================================

def test_p6_a_lock1_last_cancel_false_with_cost_rewrite_not_verified(env):
    """P6-A 锁定 1：最后 cancel 返回 False、同时 cost 0→6 —— 快照源内部最后
    一个回调的改写在快照值读取前完成、随快照整体可见 → 见证读取即捕获 →
    BUDGET_EXHAUSTED，绝不 VERIFIED（final_report=None）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p6a_l1_0001")

    def last_cancel_rewrites_cost(s):
        s.cancel = False                   # cancel 回调返回 False
        s.cost = 6.0                       # ……同时把 cost 0→6（limit=5）

    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        boundary_snapshot=_BoundarySource(c, cost=0.0,
                                          on_read=last_cancel_rewrites_cost).snapshot).run()
    assert out.attempts[0].verdict == "VERIFIED"      # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert out.final_report is None


def test_p6_a_lock2_last_read_advances_deadline_not_verified(env):
    """P6-A 锁定 2：最后读取项推进 deadline —— 快照读取原子返回推进后的
    时间 → 见证读取即捕获 → TIMEOUT，绝不 VERIFIED（final_report=None）。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    c = _contract(work_real, contract_id="wc_16f_p6a_l2_0001", budget=ExecutionBudget(
        max_duration_seconds=15.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    clock = FakeClock(0.0)

    def last_read_advances_deadline(s):
        if s.reads == 1:
            clock.advance(20.0)                # 0 → 20 > deadline 15
        s.now = clock.t

    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c, now_fn=clock),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        now_fn=clock,
        boundary_snapshot=_BoundarySource(c, on_read=last_read_advances_deadline).snapshot).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.TIMEOUT
    assert out.final_report is None
    assert clock.t == 20.0


def test_p6_a_lock3_broken_source_fail_closed(env):
    """P6-A 锁定 3：快照源异常 / schema 违约 / 类型违约 / 版本不一致 →
    fail-closed（UNSTABLE_BOUNDARY，final_report=None）——绝不对源返回值
    补默认值或强转，绝不取较乐观值。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p6a_l3a_0001")
    # (a) 见证读取即异常 → UNSTABLE_BOUNDARY
    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            boundary_snapshot=_BoundarySource(
                                c, fail_reads=(1,)).snapshot).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None
    assert "final_boundary_unstable" in out.diagnostic

    def broken(_s):
        # P7-A：任意 Mapping（dict）返回值按精确类型拒绝——权威快照只能是
        # Furina 自有冻结 BoundarySnapshot（schema 违约语义在精确类型协议下
        # 同样 fail-closed）。
        return {"contract_hash": c.content_hash, "cancelled": False,
                "cost_used": None, "now": 0.0, "version": 1,
                "extra_key": True}

    # (b) schema 违约（任意 Mapping）→ UNSTABLE_BOUNDARY
    c2 = _verified_summary_contract(work_real, "wc_16f_p6a_l3b_0001")
    out2 = BoundedRepairLoop(contract=c2, verifier=IndependentVerifier(c2),
                             collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
                             boundary_snapshot=broken).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out2.final_report is None

    def bad_cancel(_s):
        # P7-A：dict 返回值（cancelled 亦非 bool）→ 非精确 BoundarySnapshot
        # 类型 → fail-closed。
        return {"contract_hash": c.content_hash, "cancelled": "no",
                "cost_used": None, "now": 0.0, "version": 1}

    # (c) 类型违约（任意 Mapping）→ UNSTABLE_BOUNDARY
    c3 = _verified_summary_contract(work_real, "wc_16f_p6a_l3c_0001")
    out3 = BoundedRepairLoop(contract=c3, verifier=IndependentVerifier(c3),
                             collect_evidence=lambda a, r: _ok_summary_submission(c3, r),
                             boundary_snapshot=bad_cancel).run()
    assert out3.attempts[0].verdict == "VERIFIED"
    assert out3.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out3.final_report is None

    # (d) 版本不一致（两次读取 version 不同）→ UNSTABLE_BOUNDARY
    c4 = _verified_summary_contract(work_real, "wc_16f_p6a_l3d_0001")
    out4 = BoundedRepairLoop(contract=c4, verifier=IndependentVerifier(c4),
                             collect_evidence=lambda a, r: _ok_summary_submission(c4, r),
                             boundary_snapshot=_BoundarySource(
                                 c4, bump_on_read=(2,)).snapshot).run()
    assert out4.attempts[0].verdict == "VERIFIED"
    assert out4.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out4.final_report is None


def test_p6_a_lock4_stable_snapshot_verifies_finished_at_snapshot_now(env):
    """P6-A 锁定 4：稳定快照（同版本、逐值一致、时钟单调）正常 VERIFIED，
    完成时间取快照时间；权威快照之后零 cost/cancel/now/verifier 回调、零
    快照读取。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p6a_l4_0001")
    events: list = []

    def now_fn():
        events.append("now")
        return 0.0

    def cost_used():
        events.append("cost")
        return 0.0

    def cancel_requested():
        events.append("cancel")
        return False

    src = _BoundarySource(c, cost=0.0, now=500.0, version=7)

    def snap(_s):
        events.append("snap")

    src.on_read = snap
    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            cost_used=cost_used, cancel_requested=cancel_requested,
                            now_fn=now_fn, boundary_snapshot=src.snapshot).run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert out.final_report is not None
    assert out.final_report.verdict is VerificationVerdict.VERIFIED
    # 完成时间取快照时间（version 原样进入快照）
    assert out.finished_at_epoch == 500.0
    # 恰好两次快照读取（见证 + 权威）；第一次快照之后只剩第二次快照——
    # 零 now/cost/cancel 回调再发生。
    assert src.reads == 2
    after_first_snap = events[events.index("snap"):]
    assert after_first_snap == ["snap", "snap"]


def test_p6_a_no_snapshot_source_independent_callbacks_never_verified(env):
    """P6-A 核心锁定：独立的 effectful cost/cancel/now 回调**不得**被包装后
    宣称为原子快照——未提供单一权威快照源时无法取得同一状态版本的
    contract/cancel/cost/now → VERIFIED 绝不被接受（UNSTABLE_BOUNDARY /
    final_report=None）。任何对抗性"最后回调改写其它状态"的配置（乃至完全
    良性的配置）都绝不 VERIFIED——伪原子有限回调协议（读取顺序排列 / epoch
    调用计数包装）已被移除。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    budget = ExecutionBudget(max_duration_seconds=600.0,
                             cost_limit=CostBudget(amount=5.0), max_attempts=5)

    # (a) 最后的 cancel 回调返回 False、同时把 cost 0→6
    c = _contract(work_real, contract_id="wc_16f_p6a_ns_a_0001", budget=budget)
    box = {"used": 0.0, "calls": 0}

    def cancel_rewrites_cost():
        box["calls"] += 1
        if box["calls"] >= 3:              # 预检（×2）之后才改写——attempt 照常执行
            box["used"] = 6.0
        return False

    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        cost_used=lambda: box["used"],
        cancel_requested=cancel_rewrites_cost).run()
    assert out.attempts[0].verdict == "VERIFIED"      # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None
    assert "boundary_snapshot_source_unavailable" in out.diagnostic

    # (b) 最后的 cost 回调翻转取消标志
    c2 = _contract(work_real, contract_id="wc_16f_p6a_ns_b_0001", budget=budget)
    flags = {"cancel": False, "calls": 0}

    def cost_rewrites_cancel():
        flags["calls"] += 1
        if flags["calls"] >= 3:            # 预检（×2）之后才改写——attempt 照常执行
            flags["cancel"] = True
        return 0.0

    out2 = BoundedRepairLoop(
        contract=c2, verifier=IndependentVerifier(c2),
        collect_evidence=lambda a, r: _ok_summary_submission(c2, r),
        cancel_requested=lambda: flags["cancel"],
        cost_used=cost_rewrites_cancel).run()
    assert out2.attempts[0].verdict == "VERIFIED"
    assert out2.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out2.final_report is None

    # (c) 最后的 now 回调推进 deadline（乃至良性配置）——同样绝不 VERIFIED
    c3 = _contract(work_real, contract_id="wc_16f_p6a_ns_c_0001", budget=budget)
    clock = FakeClock(0.0)
    out3 = BoundedRepairLoop(
        contract=c3, verifier=IndependentVerifier(c3, now_fn=clock),
        collect_evidence=lambda a, r: _ok_summary_submission(c3, r),
        now_fn=clock).run()
    assert out3.attempts[0].verdict == "VERIFIED"
    assert out3.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out3.final_report is None


# ================================================================
# Reviewer Patch 6 — P6-B: PDF generation 精确绑定
# ================================================================

def test_p6_b_generation_binding_exact(env):
    """P6-B 锁定：indirect ref 保存 (object_number, generation) 并与对象定义
    generation 精确一致——当前封闭子集只支持 ``n 0 obj``，因此 /Root、
    /Pages 引用与 xref n-entry 的 generation 都必须为 0：/Root 1 9 R 指向
    1 0 obj → FAIL；/Pages 2 9 R 指向 2 0 obj → FAIL；xref n-entry generation
    非零而对象为 n 0 obj → FAIL；对象定义 n 9 obj 与 xref 00000 偏移指向
    不一致 → FAIL；generation-0 合法 PDF 保持 PASS。"""
    tmp, work, work_real, outside, outside_real = env
    from furina.agent.verification import full_content_verdict
    # 正对照：generation-0 合法 PDF 仍 PASS
    assert full_content_verdict(_p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n")) \
        == ("application/pdf", "")
    # /Root 1 9 R 指向 1 0 obj → 引用与定义 generation 不一致 → FAIL
    blob = _p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n",
                   trailer=b"trailer\n<</Size 4/Root 1 9 R>>\n")
    assert full_content_verdict(blob) == ("application/pdf",
                                          "malformed_content:pdf_root_generation")
    # /Pages 2 9 R 指向 2 0 obj → FAIL
    blob = _p5_pdf(b"<</Type/Catalog/Pages 2 9 R>>\n")
    assert full_content_verdict(blob) == ("application/pdf",
                                          "malformed_content:pdf_pages_generation")
    # xref n-entry generation 非零而对象为 n 0 obj → FAIL
    blob = _p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n", xref_gen=9)
    assert full_content_verdict(blob) == ("application/pdf",
                                          "malformed_content:pdf_xref_generation")
    # 对象定义 3 9 obj 而 xref 条目 generation 00000 → 偏移指向的
    # ``3 0 obj`` marker 不存在 → FAIL（对象定义 generation 与引用不一致）
    blob = _p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n", gens=(0, 0, 9))
    assert full_content_verdict(blob) == ("application/pdf",
                                          "malformed_content:pdf_xref_offset")
    # 端到端：generation 不一致 PDF 作为 pdf_document 期望验证 → required FAIL
    art = work_real / "gen.pdf"
    art.write_bytes(_p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n",
                            trailer=b"trailer\n<</Size 4/Root 1 9 R>>\n"))
    exp = ArtifactExpectation(artifact_id="gen_doc", artifact_type="pdf_document",
                              expected_path=str(art), required=True)
    c = _content_contract(work_real, "wc_16f_p6b_0001", expectations=(exp,))
    rep = IndependentVerifier(c).verify(_submission(
        c, "run_p6b_0001",
        declared=[_declared(art, sha_hex=_sha(art.read_bytes()),
                            mime="application/pdf", artifact_id="gen_doc")]))
    assert rep.verdict is VerificationVerdict.FAILED
    assert rep.authority_seal == ""
    assert any(ch.result is CheckResult.FAIL
               and ch.explanation.startswith("malformed_content:pdf_root_generation")
               for ch in rep.checks), [(ch.check_id, ch.explanation) for ch in rep.checks]


# ================================================================
# Reviewer Patch 6 — P6-C: 公开模型按真实运行时类型逐字段封闭
# ================================================================

_P6_SHORT_SECRET = "password:hunter2"
_P6_LONG_SECRET = "api_key=" + "B" * 600


def _p6_base_kwargs() -> dict:
    """五个公开模型各自**合法**基础构造参数（逐字段注入迭代的基底）。"""
    from furina.agent.verification import (
        ArtifactObservation,
        EvidenceBundle,
        TerminalObservation,
        VerificationCheck,
    )
    bundle = EvidenceBundle(contract_id="wc_16f_p6c_0001", contract_hash="0" * 64,
                            run_id="run_p6c_0001", backend_id="native_agent",
                            terminal=(), artifacts=())
    return {
        TerminalObservation: dict(event_id="evt_p6c_0001", kind="backend.completed",
                                  observed_at_epoch=1.0, bound=True),
        ArtifactObservation: dict(source="expectation", artifact_id="doc",
                                  claimed_path="/p/a.md", resolved_path="/p/a.md",
                                  target_exists=True, is_regular_file=True,
                                  within_workspace=True, size_bytes=3,
                                  observed_mime="text/plain",
                                  observed_sha256="0" * 64, rejection="",
                                  name_mime="", content_rejection=""),
        EvidenceBundle: dict(contract_id="wc_16f_p6c_0001", contract_hash="0" * 64,
                             run_id="run_p6c_0001", backend_id="native_agent",
                             terminal=(), artifacts=(), diagnostics=()),
        VerificationCheck: dict(check_id="check_exists_p6c_0001",
                                kind="artifact_file_exists", required=True,
                                result=CheckResult.PASS, explanation="ok",
                                inputs=(("path", "/p/a.md"),)),
        VerificationReport: dict(report_id="vrp_" + "a" * 32, verifier_id=VERIFIER_ID,
                                 contract_id="wc_16f_p6c_0001", contract_hash="0" * 64,
                                 standard_hash="0" * 64, run_id="run_p6c_0001",
                                 backend_id="native_agent",
                                 verdict=VerificationVerdict.FAILED, checks=(),
                                 diagnostics=(), evidence=bundle,
                                 started_at_epoch=1.0, finished_at_epoch=2.0),
    }


@pytest.mark.parametrize("secret", [_P6_SHORT_SECRET, _P6_LONG_SECRET])
def test_p6_c_every_dataclass_field_typed_or_scrubbed(env, secret):
    """P6-C 锁定：遍历五个公开模型**全部 dataclass 字段**（不只"声明为字符串"
    的字段），向每个字段注入短秘密与 600 字符秘密——构造必须拒绝（异常消息
    零 raw secret 回显），或所有 to_dict()/to_digest_dict()/digest_payload()/
    to_json() 导出均无 raw secret。"""
    from furina.agent.verification import (
        ArtifactObservation,
        EvidenceBundle,
        TerminalObservation,
        VerificationCheck,
    )
    bases = _p6_base_kwargs()
    for model, base in bases.items():
        for f in dataclasses.fields(model):
            kw = dict(base)
            kw[f.name] = secret
            try:
                obj = model(**kw)
            except VerificationError as exc:
                # 构造拒绝：异常消息同样零 raw secret 回显（纵深）
                assert secret not in str(exc), (model.__name__, f.name)
                continue
            # 构造成功：全部导出面零 raw secret
            blob = _p5_export_blob(obj)
            if isinstance(obj, (TerminalObservation, ArtifactObservation)):
                container = ("terminal" if isinstance(obj, TerminalObservation)
                             else "artifacts")
                obj = EvidenceBundle(**{**bases[EvidenceBundle],
                                        container: (obj,)})
                blob += "\n" + _p5_export_blob(obj)
            elif isinstance(obj, VerificationCheck):
                report_kw = dict(bases[VerificationReport])
                report_kw["checks"] = (obj,)
                report = VerificationReport(**report_kw)
                blob += "\n" + _p5_export_blob(report)
            assert secret not in blob, (model.__name__, f.name, blob[:400])


def test_p6_c_strict_runtime_type_gates(env):
    """P6-C 锁定（逐字段最小集）：observed_at_epoch 有限数值（bool/NaN/Inf/
    str 拒绝）；bound/target_exists/is_regular_file/within_workspace 严格
    bool；size_bytes None 或非负 int（bool/负数/浮点/str 拒绝）；声明为
    字符串的字段非 str 拒绝（绝不静默变 ""）。"""
    from furina.agent.verification import (
        ArtifactObservation,
        TerminalObservation,
        VerificationCheck,
    )
    # observed_at_epoch：有限数值，bool 拒绝
    for bad in (True, float("nan"), float("inf"), float("-inf"), "1.0", None):
        with pytest.raises(VerificationError):
            TerminalObservation(event_id="evt_p6c_t_0001", kind="backend.completed",
                                observed_at_epoch=bad, bound=True)
    # bound：严格 bool
    for bad in (1, "yes", None, 1.0):
        with pytest.raises(VerificationError):
            TerminalObservation(event_id="evt_p6c_t_0001", kind="backend.completed",
                                observed_at_epoch=1.0, bound=bad)
    base_ao = dict(source="expectation", artifact_id="doc", claimed_path="/p/a.md",
                   resolved_path="/p/a.md", target_exists=True, is_regular_file=True,
                   within_workspace=True, size_bytes=3, observed_mime="text/plain",
                   observed_sha256="0" * 64, rejection="")
    # target_exists / is_regular_file / within_workspace：严格 bool
    for field in ("target_exists", "is_regular_file", "within_workspace"):
        for bad in (1, "yes", None):
            kw = dict(base_ao)
            kw[field] = bad
            with pytest.raises(VerificationError):
                ArtifactObservation(**kw)
    # size_bytes：None 或非负 int（bool/负数/浮点/str 拒绝）
    for bad in (True, -1, 3.0, "3"):
        kw = dict(base_ao)
        kw["size_bytes"] = bad
        with pytest.raises(VerificationError):
            ArtifactObservation(**kw)
    ok_none = dict(base_ao)
    ok_none["size_bytes"] = None
    ArtifactObservation(**ok_none)               # None 合法
    # 声明为字符串的字段非 str 拒绝（绝不静默转 ""）
    for field in ("claimed_path", "resolved_path", "rejection", "name_mime",
                  "content_rejection", "observed_mime"):
        kw = dict(base_ao)
        kw[field] = 123
        with pytest.raises(VerificationError):
            ArtifactObservation(**kw)
    with pytest.raises(VerificationError):
        VerificationCheck(check_id="check_x_p6c_0001", kind="artifact_file_exists",
                          required=True, result=CheckResult.PASS,
                          explanation=None)


def test_p6_c_enum_and_report_id_rejection_messages_scrubbed(env):
    """P6-C 锁定：report_id 拒绝、verdict / CheckResult 枚举字符串转换错误
    （ValueError 回显 raw value）——异常消息一律先脱敏，raw secret 绝不进入
    异常消息。"""
    from furina.agent.verification import VerificationCheck
    secret = _P6_SHORT_SECRET
    long_secret = _P6_LONG_SECRET
    base = dict(_p6_base_kwargs()[VerificationReport])
    # report_id 词法非法：异常回显脱敏
    for rid in (secret, long_secret, 123):
        kw = dict(base)
        kw["report_id"] = rid
        with pytest.raises(VerificationError) as ei:
            VerificationReport(**kw)
        assert secret not in str(ei.value) and long_secret not in str(ei.value)
    # verdict 枚举字符串转换错误：ValueError 捕获并脱敏
    for vd in (secret, long_secret):
        kw = dict(base)
        kw["verdict"] = vd
        with pytest.raises(VerificationError) as ei:
            VerificationReport(**kw)
        assert secret not in str(ei.value) and long_secret not in str(ei.value)
        assert "[REDACTED]" in str(ei.value)
    # CheckResult 枚举字符串转换错误：ValueError 捕获并脱敏
    for res in (secret, long_secret):
        with pytest.raises(VerificationError) as ei:
            VerificationCheck(check_id="check_x_p6c_0001", kind="artifact_file_exists",
                              required=True, result=res)
        assert secret not in str(ei.value) and long_secret not in str(ei.value)
        assert "[REDACTED]" in str(ei.value)
    # result 非法对象：统一 VerificationError（绝不裸 ValueError 回显 raw value）
    with pytest.raises(VerificationError):
        VerificationCheck(check_id="check_x_p6c_0001", kind="artifact_file_exists",
                          required=True, result=object())


# ================================================================
# Reviewer Patch 7 — P7-A: 权威快照必须是真正不可变值（精确类型封闭）
# ================================================================

def test_p7_a_arbitrary_mapping_snapshot_rejected(env):
    """P7-A 锁定：权威快照只接受 Furina 自有、冻结、严格类型校验的
    BoundarySnapshot **精确类型**——任意 Mapping（plain dict / 动态 Mapping
    ABC / MappingProxyType）一律拒绝（UNSTABLE_BOUNDARY / final_report=None）。
    拒绝路径绝不调用外部 mapping 的 keys()/__getitem__()/str()/repr()
    （敌意动态 mapping 的协议方法一旦被调用即抛出携带秘密的异常——绝不
    传播），见证读取拒绝后零第二读取。"""
    from collections.abc import Mapping as ABCMapping
    from types import MappingProxyType

    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p7a_map_0001")
    secret = "password:hunter2"

    class _HostileDynamicMapping(ABCMapping):
        """动态 Mapping：任何协议方法被调用即抛出携带秘密的异常。"""

        def __getitem__(self, k):
            raise RuntimeError(f"leak:{secret}")

        def __iter__(self):
            raise RuntimeError(f"leak:{secret}")

        def __len__(self):
            raise RuntimeError(f"leak:{secret}")

        def keys(self):
            raise RuntimeError(f"leak:{secret}")

    reads = {"n": 0}

    def dict_source():
        reads["n"] += 1
        return {"contract_hash": c.content_hash, "cancelled": False,
                "cost_used": None, "now": 500.0, "version": 1}

    def proxy_source():
        return MappingProxyType({"contract_hash": c.content_hash,
                                 "cancelled": False, "cost_used": None,
                                 "now": 500.0, "version": 1})

    def dynamic_source():
        return _HostileDynamicMapping()

    for tag, src in (("dict", dict_source), ("proxy", proxy_source),
                     ("dynamic", dynamic_source)):
        out = BoundedRepairLoop(
            contract=c, verifier=IndependentVerifier(c),
            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
            boundary_snapshot=src).run()
        assert out.attempts[0].verdict == "VERIFIED", tag   # 报告本身真实产出
        assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY, tag
        assert out.final_report is None, tag
        assert "final_boundary_unstable" in out.diagnostic, tag
        assert "leak:" not in out.diagnostic, tag
    # 见证读取即拒绝 → 恰一次源调用（零第二读取）
    assert reads["n"] == 1


def test_p7_b_snapshot_subclass_proxy_and_bypass_rejected(env):
    """P7-A 锁定：BoundarySnapshot 子类、字段级代理均按**精确类型**拒绝；
    经 ``object.__new__`` 旁路构造期校验交付的字段违约实例在权威读取期被
    严格类型校验捕获（零默认值/零强转）——全部 UNSTABLE_BOUNDARY /
    final_report=None。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p7b_sub_0001")

    class _SubSnapshot(BoundarySnapshot):
        pass

    class _ProxySnapshot:
        """代理：暴露与 BoundarySnapshot 完全同名的字段——但非精确类型。"""

        def __init__(self, real):
            self._real = real

        @property
        def contract_hash(self):
            return self._real.contract_hash

        @property
        def cancelled(self):
            return self._real.cancelled

        @property
        def cost_used(self):
            return self._real.cost_used

        @property
        def now(self):
            return self._real.now

        @property
        def version(self):
            return self._real.version

    real = BoundarySnapshot(contract_hash=c.content_hash, cancelled=False,
                            cost_used=None, now=500.0, version=1)
    subclass_snap = _SubSnapshot(contract_hash=c.content_hash, cancelled=False,
                                 cost_used=None, now=500.0, version=1)
    proxy_snap = _ProxySnapshot(real)
    # 旁路构造：绕过 __post_init__ 的字段违约实例（cancelled 非 bool）
    bypass = object.__new__(BoundarySnapshot)
    object.__setattr__(bypass, "contract_hash", c.content_hash)
    object.__setattr__(bypass, "cancelled", "no")
    object.__setattr__(bypass, "cost_used", None)
    object.__setattr__(bypass, "now", 500.0)
    object.__setattr__(bypass, "version", 1)

    for tag, snap in (("subclass", subclass_snap), ("proxy", proxy_snap),
                      ("bypass", bypass)):
        out = BoundedRepairLoop(
            contract=c, verifier=IndependentVerifier(c),
            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
            boundary_snapshot=lambda s=snap: s).run()
        assert out.attempts[0].verdict == "VERIFIED", tag
        assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY, tag
        assert out.final_report is None, tag
        assert "final_boundary_unstable" in out.diagnostic, tag


def test_p7_c_exact_immutable_snapshot_positive(env):
    """P7-A 锁定：精确类型的合法 BoundarySnapshot（冻结不可变、字段严格
    校验）是唯一可被接受的权威快照——同版本双读取证明成立 → VERIFIED，
    finished_at_epoch == snapshot.now，快照源恰被读取两次。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p7c_0001")
    snap = BoundarySnapshot(contract_hash=c.content_hash, cancelled=False,
                            cost_used=0.0, now=500.0, version=3)
    # 冻结不可变：任何字段赋值都失败且快照事实不变
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.cancelled = True
    assert snap.cancelled is False and snap.version == 3
    # 构造期严格类型校验（静态失败码）
    for bad in (dict(contract_hash="", cancelled=False, cost_used=None,
                     now=500.0, version=3),
                dict(contract_hash=c.content_hash, cancelled=1, cost_used=None,
                     now=500.0, version=3),
                dict(contract_hash=c.content_hash, cancelled=False,
                     cost_used=True, now=500.0, version=3),
                dict(contract_hash=c.content_hash, cancelled=False,
                     cost_used=None, now=float("nan"), version=3),
                dict(contract_hash=c.content_hash, cancelled=False,
                     cost_used=None, now=500.0, version=True)):
        with pytest.raises(VerificationError):
            BoundarySnapshot(**bad)
    calls = {"n": 0}

    def source():
        calls["n"] += 1
        return snap

    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        now_fn=FakeClock(100.0),           # P9-B4 时钟协议适配：快照 now(500)
        boundary_snapshot=source).run()    # ∈ [可信时钟 100, deadline 700]
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert out.final_report is not None
    assert out.finished_at_epoch == 500.0
    assert calls["n"] == 2


def test_p7_d_post_snapshot_zero_callbacks_preserved(env, monkeypatch):
    """P7-A 锁定（P10-B1 类级 spy 协议适配）：权威快照（精确类型）之后的零
    回调语义保持——恰两次快照读取（见证 + 权威），第一次快照之后零 now/
    cost/cancel 回调、零快照读取、零 verifier 回调（seal 认证只发生在接受
    门内、快照之前）；完成时间取快照时间。"""
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    c = _verified_summary_contract(work_real, "wc_16f_p7d_0001")
    events: list = []

    def now_fn():
        events.append("now")
        return 0.0

    def cost_used():
        events.append("cost")
        return 0.0

    def cancel_requested():
        events.append("cancel")
        return False

    # P10-B1：verifier 必须 exact trusted type——seal spy 改为类级
    # monkeypatch（在 loop 构造之前安装，类级绑定即取得 spy；语义与子类
    # spy 等价）。
    seal_calls = {"n": 0}
    original_seal = IndependentVerifier.seal_is_authentic

    def _counting_seal(self, report):
        seal_calls["n"] += 1
        events.append("seal")
        return original_seal(self, report)

    monkeypatch.setattr(IndependentVerifier, "seal_is_authentic", _counting_seal)

    v = IndependentVerifier(c)
    src = _BoundarySource(c, cost=0.0, now=500.0)

    def snap(_s):
        events.append("snap")

    src.on_read = snap
    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            cost_used=cost_used, cancel_requested=cancel_requested,
                            now_fn=now_fn, boundary_snapshot=src.snapshot).run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert out.final_report is not None
    # seal 认证只发生在接受门内（快照之前恰一次）
    assert seal_calls["n"] == 1
    # 恰两次快照读取；第一次快照之后只剩第二次快照——零回调再发生
    assert src.reads == 2
    after_first_snap = events[events.index("snap"):]
    assert after_first_snap == ["snap", "snap"]
    assert out.finished_at_epoch == 500.0


# ================================================================
# Reviewer Patch 7 — P7-B: PDF 全图 generation 绑定
# ================================================================

def test_p7_e_pdf_kids_nonzero_generation_rejected(env):
    """P7-B 锁定：Pages 的 /Kids 数组引用 generation 非零（``/Kids [3 9 R]``
    指向 ``3 0 obj``）→ 全图扫描捕获 → malformed_content:pdf_ref_generation
    fail-closed（此前 /Kids 引用的 generation 不被核对）。"""
    from furina.agent.verification import full_content_verdict
    blob = _p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n",
                   pages_body=b"<</Type/Pages/Kids[3 9 R]/Count 1>>\n")
    assert full_content_verdict(blob) == ("application/pdf",
                                          "malformed_content:pdf_ref_generation")


def test_p7_f_pdf_parent_nonzero_generation_rejected(env):
    """P7-B 锁定：Page 的 /Parent 引用 generation 非零（``/Parent 2 9 R``
    指向 ``2 0 obj``）→ 全图扫描捕获 → malformed_content:pdf_ref_generation。"""
    from furina.agent.verification import full_content_verdict
    blob = _p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n",
                   page_body=b"<</Type/Page/Parent 2 9 R/MediaBox[0 0 200 200]>>\n")
    assert full_content_verdict(blob) == ("application/pdf",
                                          "malformed_content:pdf_ref_generation")


def test_p7_g_nested_array_dict_nonzero_ref_rejected(env):
    """P7-B 锁定：嵌套数组、数组内嵌套字典及 trailer 非键引用的 generation
    非零一律 fail-closed（数组项不再被整体 opacity 丢弃）。"""
    from furina.agent.verification import full_content_verdict
    # 嵌套数组 [[3 9 R]]
    blob = _p5_pdf(b"<</Type/Catalog/Pages 2 0 R/N[[3 9 R]]>>\n")
    assert full_content_verdict(blob) == ("application/pdf",
                                          "malformed_content:pdf_ref_generation")
    # 数组内嵌套字典 [<< /K 3 9 R >>]
    blob = _p5_pdf(b"<</Type/Catalog/Pages 2 0 R/N[<</K 3 9 R>>]>>\n")
    assert full_content_verdict(blob) == ("application/pdf",
                                          "malformed_content:pdf_ref_generation")
    # trailer 字典的非键引用 /Info 3 9 R（/Root generation 合法）
    blob = _p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n",
                   trailer=b"trailer\n<</Size 4/Root 1 0 R/Info 3 9 R>>\n")
    assert full_content_verdict(blob) == ("application/pdf",
                                          "malformed_content:pdf_ref_generation")


def test_p7_h_generation_zero_legal_pdf_passes(env):
    """P7-B 正对照：generation-0 合法 PDF（含 /Kids [3 0 R]、/Parent 2 0 R、
    嵌套数组/嵌套字典中的 gen-0 引用）保持 PASS；literal string / hex
    string / 注释中的伪引用（``3 9 R`` 形态）绝不被误判。"""
    from furina.agent.verification import full_content_verdict
    # 默认夹具：/Kids[3 0 R] + /Parent 2 0 R
    assert full_content_verdict(_p5_pdf(b"<</Type/Catalog/Pages 2 0 R>>\n")) \
        == ("application/pdf", "")
    # 嵌套结构 gen-0 引用 + 三种伪引用形态（literal/hex/注释）全部不误判
    blob = _p5_pdf(
        b"<</Type/Catalog/Pages 2 0 R/N<</K[3 0 R]/M[[2 0 R]]/D[<</E 3 0 R>>]>>"
        b"/X(/fake 3 9 R)/Y<33203920>/Z 1% 3 9 R\n>>\n")
    assert full_content_verdict(blob) == ("application/pdf", "")


# ================================================================
# Reviewer Patch 7 — P7-C/P7-D: authority_seal 类型封闭 + 拒绝路径
# 不可信字符串转换封闭
# ================================================================

_P7_SHORT_SECRET = "password:hunter2"
_P7_LONG_SECRET = "api_key=" + "C" * 600


class _FalseyHostile:
    """falsey 且任何字符串化/真值化都抛出携带秘密异常的敌意对象。"""

    def __init__(self, secret):
        self._secret = secret

    def __bool__(self):
        raise RuntimeError(f"leak:{self._secret}")

    def __str__(self):
        raise RuntimeError(f"leak:{self._secret}")

    def __repr__(self):
        raise RuntimeError(f"leak:{self._secret}")


def _p7_report_kwargs(**overrides) -> dict:
    from furina.agent.verification import EvidenceBundle
    ev = EvidenceBundle(**_P5_BUNDLE_KW)
    kw = dict(_P5_REPORT_KW)
    kw["evidence"] = ev
    kw.update(overrides)
    return kw


@pytest.mark.parametrize("bad", [0, False, None, [], {}, (), set()])
def test_p7_i_falsey_non_string_authority_seal_rejected(bad):
    """P7-C 锁定：所有 verdict 下 authority_seal 先验证为 str——falsey 非字符串
    （0/False/None/空容器）在 VERIFIED 与非 VERIFIED 下都被拒绝（绝不因
    truthiness 通过）；非 VERIFIED 必须**精确等于** ""。"""
    # VERIFIED（合法 16F verifier_id）携带非 str seal → 拒绝
    with pytest.raises(VerificationAuthorityError):
        VerificationReport(**_p7_report_kwargs(
            verdict=VerificationVerdict.VERIFIED, authority_seal=bad))
    # 非 VERIFIED 携带 falsey 非字符串 seal → 拒绝（旧实现 truthiness 通过）
    with pytest.raises(VerificationAuthorityError):
        VerificationReport(**_p7_report_kwargs(
            verdict=VerificationVerdict.FAILED, authority_seal=bad))
    with pytest.raises(VerificationAuthorityError):
        VerificationReport(**_p7_report_kwargs(
            verdict=VerificationVerdict.INCONCLUSIVE, authority_seal=bad))
    # 合法空字符串 seal（非 VERIFIED）保持可构造
    VerificationReport(**_p7_report_kwargs(
        verdict=VerificationVerdict.FAILED, authority_seal=""))


def test_p7_i_falsey_hostile_object_authority_seal_rejected():
    """P7-C 纵深：falsey 自定义敌意对象（__bool__ 为 False、__str__/__repr__
    抛出携带秘密的异常）在所有 verdict 下都被拒绝——类型验证先于 truthiness/
    字符串化，敌意异常绝不传播、秘密绝不泄漏。"""
    for hostile in (_FalseyHostile(_P7_SHORT_SECRET),
                    _FalseyHostile(_P7_LONG_SECRET)):
        for verdict in (VerificationVerdict.VERIFIED,
                        VerificationVerdict.FAILED,
                        VerificationVerdict.INCONCLUSIVE):
            with pytest.raises(VerificationAuthorityError) as ei:
                VerificationReport(**_p7_report_kwargs(
                    verdict=verdict, authority_seal=hostile))
            msg = str(ei.value)
            assert "hunter2" not in msg and "CCCC" not in msg
            assert "leak:" not in msg


class _HostileStrRepr:
    """__str__/__repr__/__bool__ 全部抛出携带秘密异常的敌意对象。"""

    def __init__(self, secret):
        self._secret = secret

    def __str__(self):
        raise RuntimeError(f"leak:{self._secret}")

    def __repr__(self):
        raise RuntimeError(f"leak:{self._secret}")

    def __bool__(self):
        raise RuntimeError(f"leak:{self._secret}")


@pytest.mark.parametrize("secret", [_P7_SHORT_SECRET, _P7_LONG_SECRET])
def test_p7_j_hostile_str_repr_cannot_leak_secrets(env, secret):
    """P7-D 锁定：五个公开模型的全部构造拒绝路径对非字符串输入绝不调用其
    __str__/__repr__/__bool__（错误信息只用静态失败码或安全类型名）——把
    字符串化即抛出携带秘密异常的敌意对象注入每个字段，构造一律以
    VerificationError（含 VerificationAuthorityError）拒绝，敌意 RuntimeError
    绝不传播、秘密绝不进入异常消息。"""
    from furina.agent.verification import (
        ArtifactObservation,
        EvidenceBundle,
        TerminalObservation,
        VerificationCheck,
    )
    hostile = _HostileStrRepr(secret)
    bases = _p6_base_kwargs()
    for model, base in bases.items():
        for f in dataclasses.fields(model):
            kw = dict(base)
            kw[f.name] = hostile
            if f.name == "report_digest":
                # 派生字段：__post_init__ 无条件重算（digest 覆盖构造值）——
                # 敌意对象绝不被字符串化，构造成功且导出面零泄漏。
                obj = model(**kw)
                blob = _p5_export_blob(obj)
                assert "leak:" not in blob and secret not in blob
                continue
            with pytest.raises(VerificationError) as ei:
                model(**kw)
            msg = str(ei.value)
            assert "leak:" not in msg and secret not in msg, \
                (model.__name__, f.name, msg)
    # VerificationCheck inputs 键/值特化注入（键：类型名拒绝；值：str()
    # 转换被敌意 __str__ 破坏 → 一律拒绝，敌意异常绝不传播）
    with pytest.raises(VerificationError) as ek:
        VerificationCheck(check_id="check_p7j_k_0001",
                          kind="artifact_file_exists", required=True,
                          result=CheckResult.PASS, inputs=((hostile, "v"),))
    assert "leak:" not in str(ek.value) and secret not in str(ek.value)
    with pytest.raises(VerificationError) as ev_:
        VerificationCheck(check_id="check_p7j_v_0001",
                          kind="artifact_file_exists", required=True,
                          result=CheckResult.PASS, inputs=(("path", hostile),))
    assert "leak:" not in str(ev_.value) and secret not in str(ev_.value)


def test_p7_j_string_enum_values_still_reported_scrubbed():
    """P7-D 语义保持：合法字符串的非法枚举值/词表外值仍在脱敏后报告
    （[REDACTED]），非字符串才走安全类型名路径——不因 P7 收紧而丢失
    字符串拒绝面的可观察性。"""
    from furina.agent.verification import VerificationCheck
    for verdict_bad in (_P7_SHORT_SECRET, _P7_LONG_SECRET):
        with pytest.raises(VerificationError) as ei:
            VerificationReport(**_p7_report_kwargs(verdict=verdict_bad))
        assert "[REDACTED]" in str(ei.value)
        assert "hunter2" not in str(ei.value) and "CCCC" not in str(ei.value)
    for res_bad in (_P7_SHORT_SECRET, _P7_LONG_SECRET):
        with pytest.raises(VerificationError) as ei:
            VerificationCheck(check_id="check_p7j_s_0001",
                              kind="artifact_file_exists", required=True,
                              result=res_bad)
        assert "[REDACTED]" in str(ei.value)
        assert "hunter2" not in str(ei.value) and "CCCC" not in str(ei.value)


# ================================================================
# Reviewer Patch 8 — B1 消费 post-attempt 边界结果 / B2 BoundarySnapshot
# 真正 builtin 值语义 / B3 全部时钟读取 fail-closed / B4 非字符串与敌意
# 对象封闭补全（外部 Reviewer 确认的 4 组 blocker，reviewer-locked）
# ================================================================

_P8_SECRET = "password:hunter2"


class _P8Hostile:
    """__eq__/__str__/__repr__/__bool__ 全部抛出携带秘密异常的敌意对象
    （带调用计数——锁定"零调用"）。``__hash__`` 不计数（仅使本对象可作
    dict 键注入）。"""

    def __init__(self, secret):
        self._secret = secret
        self.calls = {"eq": 0, "str": 0, "repr": 0, "bool": 0}

    __hash__ = object.__hash__

    def __eq__(self, other):
        self.calls["eq"] += 1
        raise RuntimeError(f"leak:{self._secret}")

    def __str__(self):
        self.calls["str"] += 1
        raise RuntimeError(f"leak:{self._secret}")

    def __repr__(self):
        self.calls["repr"] += 1
        raise RuntimeError(f"leak:{self._secret}")

    def __bool__(self):
        self.calls["bool"] += 1
        raise RuntimeError(f"leak:{self._secret}")

    def reset(self):
        self.calls = {"eq": 0, "str": 0, "repr": 0, "bool": 0}


def test_p8_b1_lock1_failed_overrun_timeout_single_attempt(env):
    """P8-B1 锁定 1：max_attempts=1，FAILED attempt 内越过 deadline →
    TIMEOUT（旧实现丢弃 post 边界结果 → 错误 ATTEMPTS_EXHAUSTED）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=1))
    v = IndependentVerifier(c)
    clock = FakeClock(0.0)
    failing = _failing_collector(c, distinct=True)

    def collector(attempt_id, run_id):
        clock.advance(700.0)          # attempt 内把时钟推过 deadline（600）
        return failing(attempt_id, run_id)

    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector,
                            now_fn=clock).run()
    assert out.stop_reason is RepairStopReason.TIMEOUT
    assert len(out.attempts) == 1
    assert out.attempts[0].verdict == "FAILED"
    assert out.final_report is None


def test_p8_b1_lock2_failed_attempt_cancelled_single_attempt(env):
    """P8-B1 锁定 2：max_attempts=1，FAILED attempt 内触发 cancellation →
    CANCELLED（绝非 ATTEMPTS_EXHAUSTED）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=1))
    v = IndependentVerifier(c)
    flags = {"checked": 0}

    def cancel_requested():
        flags["checked"] += 1
        return flags["checked"] > 2   # 第 3 次（attempt 1 完成后的 post）翻转

    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=True),
                            cancel_requested=cancel_requested).run()
    assert out.stop_reason is RepairStopReason.CANCELLED
    assert len(out.attempts) == 1
    assert out.final_report is None


def test_p8_b1_lock3_failed_attempt_cost_overrun_single_attempt(env):
    """P8-B1 锁定 3：max_attempts=1，FAILED attempt 内 cost 从 0 越过 limit →
    BUDGET_EXHAUSTED。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=1))
    v = IndependentVerifier(c)
    costs = [0.0, 0.0]                # pre1/pre2 读 0；post 起读 6（> limit 5）

    def cost_used():
        return costs.pop(0) if costs else 6.0

    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=True),
                            cost_used=cost_used).run()
    assert out.stop_reason is RepairStopReason.BUDGET_EXHAUSTED
    assert len(out.attempts) == 1
    assert out.final_report is None


def test_p8_b1_lock4_inconclusive_overrun_timeout(env):
    """P8-B1 锁定 4：INCONCLUSIVE attempt 同样消费 post 边界结果——越过
    deadline → TIMEOUT。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p8b1_inc_0001")
    c = c  # 文件已存在——判据全部可过，仅缺终态 claim → INCONCLUSIVE
    clock = FakeClock(0.0)
    art = work_real / "summary.md"

    def collector(attempt_id, run_id):
        clock.advance(700.0)
        # 有声明 artifact（判据可过）但零终态 claim → substantive gate 之外的
        # INCONCLUSIVE（terminal claim NOT_EVALUABLE）
        return _submission(c, run_id, terminal=[],
                           declared=[_declared(art, sha_hex=_sha(b"ok"),
                                               mime="text/markdown",
                                               artifact_id="doc")])

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=collector, now_fn=clock).run()
    assert out.stop_reason is RepairStopReason.TIMEOUT
    assert len(out.attempts) == 1
    assert out.attempts[0].verdict == "INCONCLUSIVE"
    assert out.final_report is None


def test_p8_b1_lock5_boundary_stop_zero_extra_collect(env):
    """P8-B1 锁定 5：max_attempts>1 时边界停止不烧剩余 attempts——越界即停，
    零额外 collect（绝不依赖下一轮 pre-check 偶然补抓）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=5))
    v = IndependentVerifier(c)
    clock = FakeClock(0.0)
    ran = {"n": 0}

    def collector(attempt_id, run_id):
        ran["n"] += 1
        clock.advance(700.0)
        return _failing_collector(c, distinct=True)(attempt_id, run_id)

    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector,
                            now_fn=clock).run()
    assert out.stop_reason is RepairStopReason.TIMEOUT
    assert ran["n"] == 1 and len(out.attempts) == 1
    assert out.final_report is None


def test_p8_b1_lock6_boundary_reason_beats_hard_and_repeated(env):
    """P8-B1 锁定 6：与 hard failure / repeated failure 同时发生时，安全边界
    原因优先（TIMEOUT 压过 HARD_FAILURE；CANCELLED 压过 REPEATED_FAILURE）。"""
    tmp, work, work_real, outside, outside_real = env
    # (a) hard + 越过 deadline → TIMEOUT
    c1 = _contract(work_real, contract_id="wc_16f_p8b1_hard_0001",
                   budget=ExecutionBudget(max_duration_seconds=600.0,
                                          cost_limit=CostBudget(amount=5.0),
                                          max_attempts=1))
    clock = FakeClock(0.0)

    def hard_collector(attempt_id, run_id):
        clock.advance(700.0)
        raise HardBackendFailure("backend runtime crashed")

    out1 = BoundedRepairLoop(contract=c1, verifier=IndependentVerifier(c1),
                             collect_evidence=hard_collector, now_fn=clock).run()
    assert out1.stop_reason is RepairStopReason.TIMEOUT
    assert len(out1.attempts) == 1 and out1.final_report is None

    # (b) repeated（同签名失败）+ cancellation → CANCELLED（恰 1 个 attempt，
    #     第二个 attempt 绝不启动）
    c2 = _contract(work_real, contract_id="wc_16f_p8b1_rep_0001",
                   budget=ExecutionBudget(max_duration_seconds=600.0,
                                          cost_limit=CostBudget(amount=5.0),
                                          max_attempts=5))
    flags = {"checked": 0}
    ran = {"n": 0}
    failing = _failing_collector(c2, distinct=False)

    def cancel_requested():
        flags["checked"] += 1
        return flags["checked"] > 2

    def collector(attempt_id, run_id):
        ran["n"] += 1
        return failing(attempt_id, run_id)

    out2 = BoundedRepairLoop(contract=c2, verifier=IndependentVerifier(c2),
                             collect_evidence=collector,
                             cancel_requested=cancel_requested).run()
    assert out2.stop_reason is RepairStopReason.CANCELLED
    assert ran["n"] == 1 and len(out2.attempts) == 1
    assert out2.final_report is None


def test_p8_b2_numeric_subclass_construction_rejected():
    """P8-B2 锁定：敌意数值/字符串子类（重载比较/转换）在 BoundarySnapshot
    构造面即拒绝——校验绝不调用其 __gt__/__lt__/__float__/__eq__。"""
    calls = {"cmp": 0, "float": 0, "eq": 0}

    class _LyingFloat(float):
        def __gt__(self, other):
            calls["cmp"] += 1
            return False

        def __lt__(self, other):
            calls["cmp"] += 1
            return False

        def __float__(self):
            calls["float"] += 1
            return 0.0

        def __eq__(self, other):
            calls["eq"] += 1
            return False

    class _LyingInt(int):
        def __lt__(self, other):
            calls["cmp"] += 1
            return False

    class _LyingStr(str):
        def __eq__(self, other):
            calls["eq"] += 1
            return True               # 谎报与任何 contract_hash 相等

    h = "a" * 64
    for over in ({"cost_used": _LyingFloat(999.0)},
                 {"now": _LyingFloat(999.0)},
                 {"version": _LyingInt(9)},
                 {"contract_hash": _LyingStr(h)}):
        kw = dict(contract_hash=h, cancelled=False, cost_used=None,
                  now=1000.0, version=1)
        kw.update(over)
        with pytest.raises(VerificationError):
            BoundarySnapshot(**kw)
    assert calls == {"cmp": 0, "float": 0, "eq": 0}


def test_p8_b2_hostile_cost_snapshot_source_fail_closed(env):
    """P8-B2 锁定（reviewer 复现面）：float 子类重载 __gt__/__lt__ 恒 False、
    cost=999/now=999 vs limit=5 —— 快照源构造 BoundarySnapshot 即被拒绝 →
    UNSTABLE_BOUNDARY，绝不 VERIFIED（旧实现 isinstance 放行后由敌意比较
    接管越界判定 → VERIFIED）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p8b2_e2e_0001")
    calls = {"cmp": 0}

    class _LyingFloat(float):
        def __gt__(self, other):
            calls["cmp"] += 1
            return False

        def __lt__(self, other):
            calls["cmp"] += 1
            return False

    def source():
        return BoundarySnapshot(contract_hash=c.content_hash, cancelled=False,
                                cost_used=_LyingFloat(999.0), now=999.0,
                                version=1)

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            boundary_snapshot=source).run()
    assert out.attempts[0].verdict == "VERIFIED"     # 报告本身真实产出
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None
    assert calls["cmp"] == 0                          # 敌意比较零调用


def test_p8_b2_bypass_instance_subclass_values_rejected(env):
    """P8-B2 锁定：object.__new__ 旁路实例携带敌意子类字段值 → 权威读取期
    精确类型校验拒绝 → UNSTABLE_BOUNDARY，绝不 VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p8b2_byp_0001")

    class _LyingFloat(float):
        def __gt__(self, other):
            return False

    def source():
        s = object.__new__(BoundarySnapshot)
        object.__setattr__(s, "contract_hash", c.content_hash)
        object.__setattr__(s, "cancelled", False)
        object.__setattr__(s, "cost_used", _LyingFloat(999.0))
        object.__setattr__(s, "now", 999.0)
        object.__setattr__(s, "version", 1)
        return s

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            boundary_snapshot=source).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None


def test_p8_b2_builtin_int_inputs_normalized_still_verifies(env):
    """P8-B2 锁定（正例）：合法 builtin int 输入构造期规范化为 builtin float，
    快照值语义恒为 builtin——验证路径照常 VERIFIED，完成时间取快照 now。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p8b2_ok_0001")

    def source():
        return BoundarySnapshot(contract_hash=c.content_hash, cancelled=False,
                                cost_used=2, now=500, version=3)

    snap = source()
    assert type(snap.cost_used) is float and snap.cost_used == 2.0
    assert type(snap.now) is float and snap.now == 500.0
    assert type(snap.version) is int and type(snap.cancelled) is bool

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                            now_fn=FakeClock(100.0),   # P9-B4 时钟协议适配
                            boundary_snapshot=source).run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert out.final_report is not None
    assert out.finished_at_epoch == 500.0
    assert type(out.finished_at_epoch) is float


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"),
                                 "1.0", True, False, None, object()])
def test_p8_b3_invalid_initial_clock_construct_fails(env, bad):
    """P8-B3 锁定：构造期时钟（deadline 派生）非有限 builtin 数值 →
    VerificationError（bool/子类/NaN/±Inf/非数值全部拒绝）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    with pytest.raises(VerificationError):
        BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                          collect_evidence=lambda a, r: _submission(c, r),
                          now_fn=lambda: bad)


def test_p8_b3_nan_clock_clean_snapshot_never_verified(env):
    """P8-B3 锁定（reviewer 反例）：now_fn=NaN + 干净 BoundarySnapshot 绝不
    VERIFIED——非法时钟在构造面即被拒绝，循环从未启动。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p8b3_nan_0001")
    with pytest.raises(VerificationError):
        BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                          collect_evidence=lambda a, r: _ok_summary_submission(c, r),
                          now_fn=lambda: float("nan"),
                          boundary_snapshot=_BoundarySource(c, cost=0.0).snapshot)


def test_p8_b3_clock_breaks_at_attempt_finish_unstable_boundary(env):
    """P8-B3 锁定：collect 后时钟变 NaN → attempt_finished 读取失效 →
    UNSTABLE_BOUNDARY / final_report=None / 不启动下一 attempt / 快照源零
    读取；已发生副作用的 attempt 保留记录且全部时间戳有限。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p8b3_mid_0001")
    state = {"broken": False}
    src = _BoundarySource(c, cost=0.0)

    def now_fn():
        return float("nan") if state["broken"] else 0.0

    def collector(attempt_id, run_id):
        state["broken"] = True        # collect 期间时钟失效
        return _ok_summary_submission(c, run_id)

    out = BoundedRepairLoop(contract=c, verifier=IndependentVerifier(c),
                            collect_evidence=collector, now_fn=now_fn,
                            boundary_snapshot=src.snapshot).run()
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None
    assert len(out.attempts) == 1
    assert src.reads == 0             # 未走到 VERIFIED 接受门——快照源零读取
    import math
    assert math.isfinite(out.started_at_epoch)
    assert math.isfinite(out.finished_at_epoch)
    assert math.isfinite(out.attempts[0].started_at_epoch)
    assert math.isfinite(out.attempts[0].finished_at_epoch)


def test_p8_b3_clock_breaks_at_post_boundary_unstable_boundary(env):
    """P8-B3 锁定：attempt 完成后（post boundary 新鲜时间读取）时钟失效 →
    UNSTABLE_BOUNDARY / final_report=None / 不启动下一 attempt。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=3))
    v = IndependentVerifier(c)
    reads = {"n": 0}

    def now_fn():
        reads["n"] += 1
        # run started→pre1→pre2→attempt_started→attempt_finished 恰 5 次；
        # 第 6 次（post boundary 新鲜时间）起返回 NaN。
        return float("nan") if reads["n"] > 5 else 0.0

    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=True),
                            now_fn=now_fn).run()
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None
    assert len(out.attempts) == 1
    assert "clock_read_failed" in out.diagnostic


def test_p8_b4_hostile_approval_result_fail_closed(env):
    """P8-B4 锁定：approval_authority 返回敌意对象（__eq__/__str__/__repr__/
    __bool__ 全部抛秘密异常）→ APPROVAL_DENIED 静态 fail-closed——协议方法
    零调用、敌意异常零传播、诊断只含安全类型名、零 collect。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    hostile = _P8Hostile(_P8_SECRET)
    ran = {"n": 0}

    def collector(attempt_id, run_id):
        ran["n"] += 1
        return _submission(c, run_id)

    def authority(attempt_id, run_id):
        return hostile

    out = BoundedRepairLoop(contract=c, verifier=v, collect_evidence=collector,
                            approval_authority=authority).run()
    assert out.stop_reason is RepairStopReason.APPROVAL_DENIED
    assert out.final_report is None
    assert ran["n"] == 0 and len(out.attempts) == 0
    assert "non_string" in out.diagnostic
    assert hostile.calls == {"eq": 0, "str": 0, "repr": 0, "bool": 0}
    assert _P8_SECRET not in out.diagnostic and "leak:" not in out.diagnostic


def test_p8_b4_approval_authority_exception_fail_closed(env):
    """P8-B4 锁定：approval_authority 回调抛出携带秘密的异常 → APPROVAL_DENIED
    静态 fail-closed（诊断脱敏），异常绝不逃出 repair loop。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)

    def authority(attempt_id, run_id):
        raise RuntimeError(f"leak:{_P8_SECRET}")

    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=lambda a, r: _submission(c, r),
                            approval_authority=authority).run()
    assert out.stop_reason is RepairStopReason.APPROVAL_DENIED
    assert out.final_report is None
    assert "authority_error" in out.diagnostic
    assert "hunter2" not in out.diagnostic and "leak:password=hunter2" not in out.diagnostic


@pytest.mark.parametrize("bad", [1, 0, "", "no", None, 1.0])
def test_p8_b4_non_bool_cancel_never_treated_false(env, bad):
    """P8-B4 锁定：cancel_requested 非 builtin bool 返回值绝不当作 False →
    UNSTABLE_BOUNDARY（VERIFIED-capable 场景绝不 VERIFIED）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p8b4_cnl_0001")
    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        cancel_requested=lambda: bad,
        boundary_snapshot=_BoundarySource(c, cost=0.0).snapshot).run()
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None
    assert "cancel_flag_invalid_type" in out.diagnostic


def test_p8_b4_hostile_cancel_object_and_exception_fail_closed(env):
    """P8-B4 锁定：cancel_requested 返回敌意对象 / 抛出携带秘密异常 →
    UNSTABLE_BOUNDARY——__bool__ 零调用、秘密零泄漏。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p8b4_hcnl_0001")
    hostile = _P8Hostile(_P8_SECRET)
    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        cancel_requested=lambda: hostile).run()
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None
    assert hostile.calls["bool"] == 0 and hostile.calls["str"] == 0
    assert _P8_SECRET not in out.diagnostic

    def exploding():
        raise RuntimeError(f"leak:{_P8_SECRET}")

    out2 = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        cancel_requested=exploding).run()
    assert out2.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out2.final_report is None
    assert "cancel_flag_error" in out2.diagnostic
    assert "hunter2" not in out2.diagnostic


def test_p8_b4_hostile_collect_exception_diag_closed(env):
    """P8-B4 锁定：collect 抛出 __str__ 即爆 / args 非字符串的异常 → 循环
    有界失败收尾——诊断面只记类型名或脱敏 args，绝不崩溃、秘密零泄漏
    （禁止无条件 str(exc)）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=1))
    v = IndependentVerifier(c)

    class _BoomStrExc(Exception):
        def __str__(self):
            raise RuntimeError(f"leak:{_P8_SECRET}")

    class _BoomNonStrArgs(Exception):
        pass

    def boom_collector(attempt_id, run_id):
        raise _BoomStrExc("x")        # args 全 builtin str → 脱敏导出；__str__ 零调用

    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=boom_collector).run()
    assert out.stop_reason is RepairStopReason.ATTEMPTS_EXHAUSTED
    assert "collect_or_verify_error:_BoomStrExc" in out.attempts[0].diagnostic
    assert "hunter2" not in out.attempts[0].diagnostic

    def non_str_collector(attempt_id, run_id):
        raise _BoomNonStrArgs(123)    # args=(123,) 非全 builtin str → 只记类型名

    out2 = BoundedRepairLoop(contract=c, verifier=v,
                             collect_evidence=non_str_collector).run()
    assert out2.stop_reason is RepairStopReason.ATTEMPTS_EXHAUSTED
    assert "collect_or_verify_error:_BoomNonStrArgs" in out2.attempts[0].diagnostic
    assert "123" not in out2.attempts[0].diagnostic


def test_p8_b4_hostile_declared_and_terminal_fields_fail_closed(env):
    """P8-B4 锁定：declared_mime / declared_sha256 / declared_size_bytes /
    terminal kind / observed_at_epoch / 非 str 输入键注入敌意对象 →
    verify() 一律 VerificationInputError/VerificationError——敌意对象协议
    方法零调用、raw secret 零进入异常消息（reviewer 的 str(d_mime) 逃逸
    通道关闭）。"""
    tmp, work, work_real, outside, outside_real = env
    content = b"ok"
    art = work_real / "summary.md"
    art.write_bytes(content)
    c = _contract(work_real)
    v = IndependentVerifier(c)
    base_decl = _declared(art, sha_hex=_sha(content), mime="text/markdown",
                          size=len(content))

    def expect_input_reject(sub):
        with pytest.raises(VerificationError) as ei:
            v.verify(sub)
        assert all(n == 0 for n in attrs_snapshot.values()), dict(attrs_snapshot)
        blob = str(ei.value)
        assert _P8_SECRET not in blob and "leak:" not in blob

    # declared 字段三连
    for field in ("declared_mime", "declared_sha256", "declared_size_bytes"):
        hostile = _P8Hostile(_P8_SECRET)
        d = dict(base_decl)
        d[field] = hostile
        attrs_snapshot = hostile.calls
        sub = _submission(c, f"run_p8b4_d_{field[:6]}", declared=[d])
        expect_input_reject(sub)

    # terminal claim 字段
    for field in ("kind", "observed_at_epoch"):
        hostile = _P8Hostile(_P8_SECRET)
        ev = dict(_bound_terminal(c, "run_p8b4_t_0001"))
        ev[field] = hostile
        attrs_snapshot = hostile.calls
        sub = _submission(c, "run_p8b4_t_0001", terminal=[ev])
        expect_input_reject(sub)

    # 非 str 顶层输入键
    hostile = _P8Hostile(_P8_SECRET)
    attrs_snapshot = hostile.calls
    sub = _submission(c, "run_p8b4_k_0001")
    sub[hostile] = "x"
    hostile.reset()                   # dict 插入本身不计入（hash 不计数、零碰撞）
    expect_input_reject(sub)


def test_p8_b4_check_input_non_string_value_rejected():
    """P8-B4 锁定（reviewer 反例）：VerificationCheck.inputs 值=123 必须
    拒绝（旧实现 str() 静默强转成 "123"——与"非字符串一律拒绝"声明冲突）。"""
    from furina.agent.verification import VerificationCheck
    with pytest.raises(VerificationError):
        VerificationCheck(check_id="check_p8b4_v_0001", kind="artifact_file_exists",
                          required=True, result=CheckResult.PASS,
                          inputs=(("count", 123),))
    with pytest.raises(VerificationError):
        VerificationCheck(check_id="check_p8b4_v_0002", kind="artifact_file_exists",
                          required=True, result=CheckResult.PASS,
                          inputs=((123, "x"),))


# ================================================================
# Reviewer Patch 9 — B1 optional callback is-None / B2 敌意异常属性观察 /
# B3 公开值模型 exact-builtin 全扫描 / B4 时钟防回退（reviewer-locked）
# ================================================================

class _P9FalseyCallable:
    """__bool__ 返回 False 的可调用对象（P9-B1：不得被 `or` 静默替换）。"""

    def __init__(self, result):
        self._result = result
        self.calls = 0
        self.bools = 0

    def __bool__(self):
        self.bools += 1
        return False

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self._result


class _P9BoolBoom:
    """__bool__ 主动抛出携密异常的可调用对象（P9-B1：构造与运行零触发）。"""

    def __init__(self, result=False):
        self._result = result
        self.bools = 0

    def __bool__(self):
        self.bools += 1
        raise RuntimeError(f"leak:{_P8_SECRET}")

    def __call__(self, *args, **kwargs):
        return self._result


class _P9ArgsBoom(Exception):
    """P9-B2 reviewer 反例：``args`` 是 property，访问即抛携密 RuntimeError。"""

    def __init__(self):
        super().__init__("static-marker")

    @property
    def args(self):          # 敌意形态本体：数据描述符优先于实例字典
        raise RuntimeError(f"leak:{_P8_SECRET}")


def _p9_lying(value, calls):
    """按基底值的 builtin 类型构造对应"谎言子类"实例——比较/转换/迭代/长度
    方法全部计数并撒谎（P9-B3：子类在拒绝前任何魔术方法都必须零调用）。
    bool 不可子类化、枚举字段另行覆盖——返回 None 表示跳过。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        class _LyingStr(str):
            def __eq__(s, o):
                calls["eq"] = calls.get("eq", 0) + 1
                return False

            def __ne__(s, o):
                calls["ne"] = calls.get("ne", 0) + 1
                return False

            def __hash__(s):
                calls["hash"] = calls.get("hash", 0) + 1
                return str.__hash__(s)

            def __str__(s):
                calls["str"] = calls.get("str", 0) + 1
                return "x"

            def __bool__(s):
                calls["bool"] = calls.get("bool", 0) + 1
                return False
        return _LyingStr(value)
    if isinstance(value, tuple):
        class _LyingTuple(tuple):
            def __iter__(s):
                calls["iter"] = calls.get("iter", 0) + 1
                return iter(())

            def __len__(s):
                calls["len"] = calls.get("len", 0) + 1
                return 0

            def __eq__(s, o):
                calls["eq"] = calls.get("eq", 0) + 1
                return False

            def __bool__(s):
                calls["bool"] = calls.get("bool", 0) + 1
                return False
        return _LyingTuple(value)
    if isinstance(value, int):
        class _LyingInt(int):
            def __lt__(s, o):
                calls["cmp"] = calls.get("cmp", 0) + 1
                return False

            def __gt__(s, o):
                calls["cmp"] = calls.get("cmp", 0) + 1
                return False

            def __float__(s):
                calls["float"] = calls.get("float", 0) + 1
                return 0.0

            def __eq__(s, o):
                calls["eq"] = calls.get("eq", 0) + 1
                return False
        return _LyingInt(value)
    if isinstance(value, float):
        class _LyingFloat(float):
            def __lt__(s, o):
                calls["cmp"] = calls.get("cmp", 0) + 1
                return False

            def __gt__(s, o):
                calls["cmp"] = calls.get("cmp", 0) + 1
                return False

            def __float__(s):
                calls["float"] = calls.get("float", 0) + 1
                return 0.0

            def __eq__(s, o):
                calls["eq"] = calls.get("eq", 0) + 1
                return False
        return _LyingFloat(value)
    return None


def test_p9_b1_falsey_cancel_callable_not_replaced(env):
    """P9-B1 锁定（reviewer 反例）：falsey callable 的 __call__ 返回 True
    （取消）——旧实现 `cancel_requested or default` 调用其 __bool__ 后把它
    静默替换为默认函数（结果 ATTEMPTS_EXHAUSTED 且烧掉 1 次 attempt）；新
    实现必须 CANCELLED、零 attempt、__bool__ 零调用。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p9b1_cnl_0001")
    cancel = _P9FalseyCallable(True)
    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        cancel_requested=cancel).run()
    assert out.stop_reason is RepairStopReason.CANCELLED
    assert len(out.attempts) == 0 and out.final_report is None
    assert cancel.calls >= 1 and cancel.bools == 0


def test_p9_b1_falsey_run_id_factory_actually_called(env):
    """P9-B1 锁定：falsey run_id_factory 必须被真实调用（绝不换成默认
    factory）——其产出 run_id 原样进入 attempt 记录。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p9b1_fac_0001")
    factory = _P9FalseyCallable("run_p9_falsey_factory_0001")
    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        run_id_factory=factory, now_fn=FakeClock(500.0),
        boundary_snapshot=_BoundarySource(c, cost=0.0).snapshot).run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert out.attempts[0].run_id == "run_p9_falsey_factory_0001"
    assert factory.calls == 1 and factory.bools == 0


def test_p9_b1_bool_boom_callable_never_triggered(env):
    """P9-B1 锁定：__bool__ 主动抛携密异常的 callable 在构造与运行全程零
    触发——optional 回调只经 is None 判定、经 __call__ 调用。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p9b1_boom_0001")
    boom = _P9BoolBoom(result=False)
    loop = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        cancel_requested=boom, now_fn=FakeClock(500.0),
        boundary_snapshot=_BoundarySource(c, cost=0.0).snapshot)
    assert boom.bools == 0
    out = loop.run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert boom.bools == 0


def test_p9_b2_hostile_args_property_cannot_escape(env):
    """P9-B2 reviewer 反例锁定：args 为 property（访问即抛携密 RuntimeError）
    的异常从 collect / approval / cancel / boundary source 四个入口注入 →
    全部类型化 fail-closed——诊断零 args 观察、零秘密、零异常逃逸。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=1))
    v = IndependentVerifier(c)
    # (a) collect 抛敌意 args 异常 → 有界失败收尾（不逃逸、零秘密）
    def boom_collect(attempt_id, run_id):
        raise _P9ArgsBoom()

    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=boom_collect).run()
    assert out.stop_reason is RepairStopReason.ATTEMPTS_EXHAUSTED
    blob = out.diagnostic + (out.attempts[0].diagnostic if out.attempts else "")
    assert _P8_SECRET not in blob and "leak:" not in blob

    # (b) approval 回调抛敌意 args 异常 → APPROVAL_DENIED 静态 fail-closed
    def boom_authority(attempt_id, run_id):
        raise _P9ArgsBoom()

    out2 = BoundedRepairLoop(contract=c, verifier=v,
                             collect_evidence=lambda a, r: _submission(c, r),
                             approval_authority=boom_authority).run()
    assert out2.stop_reason is RepairStopReason.APPROVAL_DENIED
    assert _P8_SECRET not in out2.diagnostic and "leak:" not in out2.diagnostic

    # (c) cancel 回调抛敌意 args 异常 → UNSTABLE_BOUNDARY（绝不当作 False）
    def boom_cancel():
        raise _P9ArgsBoom()

    out3 = BoundedRepairLoop(contract=c, verifier=v,
                             collect_evidence=lambda a, r: _submission(c, r),
                             cancel_requested=boom_cancel).run()
    assert out3.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert _P8_SECRET not in out3.diagnostic and "leak:" not in out3.diagnostic

    # (d) 权威快照源抛敌意 args 异常 → UNSTABLE_BOUNDARY（零秘密）
    def boom_snap():
        raise _P9ArgsBoom()

    c9 = _verified_summary_contract(work_real, "wc_16f_p9b2_snap_0001")
    out4 = BoundedRepairLoop(contract=c9, verifier=IndependentVerifier(c9),
                             collect_evidence=lambda a, r: _ok_summary_submission(c9, r),
                             boundary_snapshot=boom_snap).run()
    assert out4.attempts[0].verdict == "VERIFIED"
    assert out4.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert "boundary_snapshot_error" in out4.diagnostic
    assert _P8_SECRET not in out4.diagnostic and "leak:" not in out4.diagnostic


def test_p9_b2_hostile_exception_class_name_sanitized():
    """P9-B2 锁定：动态异常类名未经清洗不得进入诊断——元类把 __name__ 做成
    抛密 property → 占位符；类名字面携带秘密 token → 占位符。"""
    from furina.agent.verification.repair import _safe_exc_diag

    class _P9Meta(type):
        @property
        def __name__(cls):
            raise RuntimeError(f"leak:{_P8_SECRET}")

    class _BoomName(Exception, metaclass=_P9Meta):
        pass

    d1 = _safe_exc_diag(_BoomName("x"))
    assert _P8_SECRET not in d1 and "leak:" not in d1

    _SecretNamed = type("token_abc123_secret", (Exception,), {})
    d2 = _safe_exc_diag(_SecretNamed("x"))
    assert "token_abc123_secret" not in d2
    assert "abc123" not in d2


def test_p9_b3_lying_str_authority_seal_rejected():
    """P9-B3 reviewer 反例锁定：FAILED 报告的 authority_seal 注入重载
    __ne__ 的非空 LyingStr → 构造拒绝（VerificationAuthorityError），
    __ne__/__eq__ 零调用——非空内容绝不进入导出树。"""
    from furina.agent.verification import VerificationReport
    calls = {}
    lying = _p9_lying("f" * 64, calls)
    kw = dict(_p6_base_kwargs()[VerificationReport])
    kw["authority_seal"] = lying
    with pytest.raises(VerificationError):
        VerificationReport(**kw)
    assert calls == {}


def test_p9_b3_lying_str_observed_sha256_rejected():
    """P9-B3 reviewer 反例锁定：observed_sha256 注入 LyingStr → 构造拒绝、
    比较魔术方法零调用（绝不从 to_dict/digest 导出）。"""
    from furina.agent.verification import ArtifactObservation
    calls = {}
    base = dict(source="expectation", artifact_id="doc", claimed_path="/p/a.md",
                resolved_path="/p/a.md", target_exists=True, is_regular_file=True,
                within_workspace=True, size_bytes=3, observed_mime="text/plain",
                observed_sha256=_p9_lying("0" * 64, calls), rejection="")
    with pytest.raises(VerificationError):
        ArtifactObservation(**base)
    assert calls == {}


def test_p9_b3_hostile_verdict_str_zero_calls():
    """P9-B3 锁定：非法 verdict（敌意对象）——compute_report_digest 绝不
    str() 强转（构造面在 digest 之前拒绝）、__str__/__repr__ 零调用。"""
    from furina.agent.verification import VerificationReport
    hostile = _P8Hostile(_P8_SECRET)
    kw = dict(_p6_base_kwargs()[VerificationReport])
    kw["verdict"] = hostile
    with pytest.raises(VerificationError) as ei:
        VerificationReport(**kw)
    assert hostile.calls["str"] == 0 and hostile.calls["repr"] == 0
    assert _P8_SECRET not in str(ei.value)


def test_p9_b3_hostile_diagnostic_zero_calls():
    """P9-B3 锁定：AttemptRecord/RepairOutcome 的 diagnostic 注入 falsey
    敌意对象 → 构造拒绝（绝不 `value or ""` truthiness）、__bool__/__str__
    零调用。"""
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome
    hostile = _P8Hostile(_P8_SECRET)
    with pytest.raises(VerificationError):
        AttemptRecord(attempt_id="att_p9_diag_0001", run_id="run_p9_diag_0001",
                      contract_hash="0" * 64, verdict="", report_id="",
                      failure_signature="", started_at_epoch=1.0,
                      finished_at_epoch=2.0, diagnostic=hostile)
    assert hostile.calls["bool"] == 0 and hostile.calls["str"] == 0
    with pytest.raises(VerificationError):
        RepairOutcome(stop_reason=RepairStopReason.ATTEMPTS_EXHAUSTED,
                      contract_id="wc_16f_p9_diag_0001", contract_hash="0" * 64,
                      attempts=(), final_report=None, started_at_epoch=1.0,
                      finished_at_epoch=2.0, diagnostic=hostile)
    assert hostile.calls["bool"] == 0 and hostile.calls["str"] == 0


def test_p9_b3_exact_builtin_subclass_matrix():
    """P9-B3 系统审计锁定：七个公开冻结值模型逐字段注入对应 builtin 类型的
    "谎言子类"——构造一律拒绝（report_digest 派生字段除外：无条件重算、
    零泄漏），且任何魔术方法在拒绝之前零调用。"""
    import dataclasses as _dc

    from furina.agent.verification import (
        ArtifactObservation,
        EvidenceBundle,
        TerminalObservation,
        VerificationCheck,
        VerificationReport,
    )
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome

    bases = dict(_p6_base_kwargs())
    bases[AttemptRecord] = dict(
        attempt_id="att_p9m_0001", run_id="run_p9m_0001", contract_hash="0" * 64,
        verdict="FAILED", report_id="", failure_signature="1" * 64,
        started_at_epoch=1.0, finished_at_epoch=2.0, diagnostic="")
    bases[RepairOutcome] = dict(
        stop_reason=RepairStopReason.ATTEMPTS_EXHAUSTED,
        contract_id="wc_16f_p9m_0001", contract_hash="0" * 64, attempts=(),
        final_report=None, started_at_epoch=1.0, finished_at_epoch=2.0,
        diagnostic="")
    for model, base in bases.items():
        for f in _dc.fields(model):
            base_val = base.get(f.name)
            if base_val is None and f.name == "authority_seal":
                base_val = ""                 # 缺省字段按 str 契约注入子类
            calls = {}
            lying = _p9_lying(base_val, calls)
            if lying is None:
                continue                      # bool（不可子类化）/None/枚举派生
            kw = dict(base)
            kw[f.name] = lying
            try:
                obj = model(**kw)
            except VerificationError:
                assert calls == {}, (model.__name__, f.name, calls)
                continue
            # 仅派生字段（report_digest——__post_init__ 无条件重算）可构造成功
            assert calls == {}, (model.__name__, f.name, calls)
            if hasattr(obj, "to_dict"):
                assert lying not in str(obj.to_dict())


def test_p9_b4_lock_a_construct_100_run_0_never_verified(env):
    """P9-B4 锁定 A：构造期时钟 100、run 起点时钟 0（回退）→ UNSTABLE_
    BOUNDARY / final_report=None / 零 attempt——绝不 VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p9b4_a_0001")
    reads = {"n": 0}

    def now_fn():
        reads["n"] += 1
        return 100.0 if reads["n"] == 1 else 0.0

    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        now_fn=now_fn,
        boundary_snapshot=_BoundarySource(c, cost=0.0, now=0.0).snapshot).run()
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None and len(out.attempts) == 0
    assert "clock_read_failed" in out.diagnostic


def test_p9_b4_lock_b_mid_attempt_regression_unstable(env):
    """P9-B4 锁定 B：attempt 中途时钟回退（attempt_finished=100 之后新鲜
    时间 50）→ UNSTABLE_BOUNDARY / final_report=None / 不启动下一 attempt。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=3))
    v = IndependentVerifier(c)
    seq = [0.0, 0.0, 0.0, 0.0, 0.0, 100.0, 50.0]

    def now_fn():
        return seq.pop(0) if seq else 0.0

    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=_failing_collector(c, distinct=True),
                            now_fn=now_fn).run()
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None and len(out.attempts) == 1
    assert "clock_regressed" in out.diagnostic


def test_p9_b4_lock_c_final_snapshot_now_regressed_never_verified(env):
    """P9-B4 锁定 C：repair 时钟正常但最终 BoundarySnapshot.now 早于最后
    可信时钟（回退）→ UNSTABLE_BOUNDARY / 绝不 VERIFIED；见证读取即拦截、
    零第二读取。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p9b4_c_0001")
    clock = FakeClock(1000.0)
    src = _BoundarySource(c, cost=0.0, now=0.0)     # 快照时钟回退到 0
    out = BoundedRepairLoop(
        contract=c, verifier=IndependentVerifier(c),
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        now_fn=clock, boundary_snapshot=src.snapshot).run()
    assert out.attempts[0].verdict == "VERIFIED"
    assert out.stop_reason is RepairStopReason.UNSTABLE_BOUNDARY
    assert out.final_report is None
    assert "clock_regressed" in out.diagnostic
    assert src.reads == 1


def test_p9_b4_lock_d_verifier_finished_before_started_rejected(env):
    """P9-B4 锁定 D：verifier finished < started → 类型化拒绝、零报告零
    seal。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p9b4_d_0001")
    seq = [100.0, 50.0]

    def now_fn():
        return seq.pop(0) if seq else 0.0

    v = IndependentVerifier(c, now_fn=now_fn)
    with pytest.raises(VerificationError) as ei:
        v.verify(_ok_summary_submission(c, "run_p9b4_d_0001"))
    assert "verifier_clock_regressed" in str(ei.value)


def test_p9_b4_lock_e_process_timeout_subclass_rejected(env):
    """P9-B4 锁定 E：process_timeout_seconds 注入数值子类 → 构造拒绝且其
    __float__/比较/__bool__ 魔术方法零调用（错误消息零 repr）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    calls = {"n": 0}

    class _LyingFloat(float):
        def __float__(self):
            calls["n"] += 1
            return 30.0

        def __gt__(self, other):
            calls["n"] += 1
            return False

        def __lt__(self, other):
            calls["n"] += 1
            return False

        def __ge__(self, other):
            calls["n"] += 1
            return False

        def __le__(self, other):
            calls["n"] += 1
            return False

        def __bool__(self):
            calls["n"] += 1
            return True

    with pytest.raises(VerificationError) as ei:
        IndependentVerifier(c, process_timeout_seconds=_LyingFloat(30.0))
    assert calls["n"] == 0
    # 错误消息零 repr：清洗后的类型名（安全词法 token）可出现，但对象值
    # （30.0）与动态消息绝不出现
    assert "30.0" not in str(ei.value)


# ================================================================
# Reviewer Patch 10 — B1 verifier 权威替换封闭 / B2 AttemptRecord·
# RepairOutcome 语义闭环 / B3 evidence 容器 exact builtin（reviewer-locked）
# ================================================================

def test_p10_b1_forging_verifier_subclass_rejected(env):
    """P10-B1 锁定（reviewer 反例）：ForgingVerifier 子类覆盖 verify（返回
    正确 contract/run/hash、假 64-hex seal、零 checks 的伪 VERIFIED）与
    seal_is_authentic（固定 True）→ 装配阶段即拒绝，绝不能 VERIFIED。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p10b1_0001")

    class ForgingVerifier(IndependentVerifier):
        def verify(self, evidence):
            from furina.agent.verification import EvidenceBundle
            bundle = EvidenceBundle(
                contract_id=c.contract_id, contract_hash=c.content_hash,
                run_id="run_p10b1_0001", backend_id="native_agent",
                terminal=(), artifacts=())
            return VerificationReport(
                report_id="vrp_" + "0" * 32, verifier_id=VERIFIER_ID,
                contract_id=c.contract_id, contract_hash=c.content_hash,
                standard_hash=self.standard_hash, run_id="run_p10b1_0001",
                backend_id="native_agent", verdict=VerificationVerdict.VERIFIED,
                checks=(), diagnostics=(), evidence=bundle,
                started_at_epoch=1.0, finished_at_epoch=2.0,
                authority_seal="a" * 64)

        def seal_is_authentic(self, report):
            return True

    with pytest.raises(VerificationError):
        BoundedRepairLoop(contract=c, verifier=ForgingVerifier(c),
                          collect_evidence=lambda a, r: _ok_summary_submission(c, r))


def test_p10_b1_work_contract_subclass_rejected(env):
    """P10-B1 锁定：WorkContract 子类（伪造契约身份状态）在 verifier 与
    repair 两个权威装配边界都被 exact trusted type 拒绝。"""
    import dataclasses as _dc

    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p10b1_wc_0001")

    class _SubContract(WorkContract):
        pass

    sub = _SubContract.__new__(_SubContract)
    sub.__dict__.update(c.__dict__)
    with pytest.raises(VerificationError):
        IndependentVerifier(sub)
    with pytest.raises(VerificationError):
        BoundedRepairLoop(contract=sub, verifier=IndependentVerifier(c),
                          collect_evidence=lambda a, r: _ok_summary_submission(c, r))


def test_p10_b1_instance_attribute_shadowing_cannot_replace_authority(env):
    """P10-B1 锁定：exact IndependentVerifier 实例上的 verify/seal_is_authentic
    实例属性 shadowing 无法替换权威行为——repair 经类级绑定调用真实验证；
    shadowing 存在时伪造/外来报告仍被真实 seal 复核拒绝。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p10b1_sh_0001")
    v = IndependentVerifier(c)
    calls = {"verify": 0, "seal": 0}

    def _fake_verify(evidence):
        calls["verify"] += 1
        raise AssertionError("shadowed verify must not be used")

    def _fake_seal(report):
        calls["seal"] += 1
        return True

    v.verify = _fake_verify
    v.seal_is_authentic = _fake_seal
    out = BoundedRepairLoop(
        contract=c, verifier=v,
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        now_fn=FakeClock(500.0),
        boundary_snapshot=_BoundarySource(c, cost=0.0).snapshot).run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert out.final_report is not None
    assert IndependentVerifier.seal_is_authentic(v, out.final_report) is True
    assert calls == {"verify": 0, "seal": 0}
    # shadowing 存在时外来签发报告仍被真实 seal 复核拒绝
    foreign = IndependentVerifier(c)
    foreign_rep = foreign.verify(_ok_summary_submission(c, "run_p10b1_x_0001"))
    loop = BoundedRepairLoop(
        contract=c, verifier=v,
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        now_fn=FakeClock(500.0),
        boundary_snapshot=_BoundarySource(c, cost=0.0).snapshot)
    ok, why = loop._accept_verified_report(foreign_rep, "run_other_0001")
    assert ok is False and calls["seal"] == 0
    assert "seal_not_authentic_for_current_verifier" in why


def test_p10_b1_seal_check_malformed_report_false_no_raise(env):
    """P10-B1 锁定：seal_is_authentic 对 object.__new__ 旁路畸形报告 /
    非报告对象 / None 一律返回 False，绝不抛异常。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    bypass = object.__new__(VerificationReport)
    assert v.seal_is_authentic(bypass) is False
    assert v.seal_is_authentic(object()) is False
    assert v.seal_is_authentic(None) is False


def _p10_failed_report(c):
    v = IndependentVerifier(c)
    return v.verify(_submission(c, "run_p10b2_f_0001"))


def _p10_verified_report(c):
    v = IndependentVerifier(c)
    return v.verify(_ok_summary_submission(c, "run_p10b2_v_0001"))


def test_p10_b2_repair_outcome_semantic_closure(env):
    """P10-B2 锁定（reviewer 反例全表）：VERIFIED+final_report=None /
    VERIFIED+FAILED 报告 / 非 VERIFIED 终局携带 VERIFIED 报告 / bad
    contract hash / finished<started / 最后 attempt 与报告身份不一致 /
    空 attempts——全部构造拒绝。"""
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome
    tmp, work, work_real, outside, outside_real = env
    verfied_rep = _p10_verified_report(_verified_summary_contract(
        work_real, "wc_16f_p10b2_v_0001"))
    failed_rep = _p10_failed_report(_contract(work_real))
    # 正例基线：attempt 身份与 VERIFIED 报告精确一致（run/report/hash）
    good_attempt = AttemptRecord(
        attempt_id="att_p10b2_0001", run_id=verfied_rep.run_id,
        contract_hash=verfied_rep.contract_hash, verdict="VERIFIED",
        report_id=verfied_rep.report_id, failure_signature="",
        started_at_epoch=1.0, finished_at_epoch=2.0)

    def outcome(**over):
        base = dict(stop_reason=RepairStopReason.VERIFIED,
                    contract_id=verfied_rep.contract_id,
                    contract_hash=verfied_rep.contract_hash,
                    attempts=(good_attempt,), final_report=verfied_rep,
                    started_at_epoch=1.0, finished_at_epoch=2.0, diagnostic="")
        base.update(over)
        return RepairOutcome(**base)

    outcome()                                     # 一致的正例可构造
    with pytest.raises(VerificationError):
        outcome(final_report=None)                # VERIFIED + final_report=None
    with pytest.raises(VerificationError):
        outcome(final_report=failed_rep)          # VERIFIED + FAILED 报告
    with pytest.raises(VerificationError):
        outcome(stop_reason=RepairStopReason.ATTEMPTS_EXHAUSTED,
                final_report=verfied_rep)         # 非 VERIFIED 终局携带 VERIFIED
    with pytest.raises(VerificationError):
        outcome(stop_reason=RepairStopReason.UNSTABLE_BOUNDARY,
                final_report=verfied_rep)
    with pytest.raises(VerificationError):
        outcome(contract_hash="not-a-hash")       # bad contract hash
    with pytest.raises(VerificationError):
        outcome(started_at_epoch=2.0, finished_at_epoch=1.0)   # finished < started
    with pytest.raises(VerificationError):
        outcome(attempts=())                      # VERIFIED + 空 attempts
    stale_attempt = AttemptRecord(
        attempt_id="att_p10b2_0002", run_id="run_other_0001",
        contract_hash=verfied_rep.contract_hash, verdict="VERIFIED",
        report_id="vrp_" + "a" * 32,
        failure_signature="", started_at_epoch=1.0, finished_at_epoch=2.0)
    with pytest.raises(VerificationError):
        outcome(attempts=(stale_attempt,))        # 最后 attempt 与报告 run 不一致


def test_p10_b2_attempt_record_semantic_closure():
    """P10-B2 锁定：AttemptRecord 的 canonical identity / 64-hex contract
    hash / verdict 封闭词表 / verdict↔report_id·failure_signature 一致性 /
    时序单调——全部构造拒绝面。"""
    from furina.agent.verification.repair import AttemptRecord

    def rec(**over):
        base = dict(attempt_id="att_p10b2r_0001", run_id="run_p10b2r_0001",
                    contract_hash="0" * 64, verdict="FAILED",
                    report_id="vrp_" + "b" * 32, failure_signature="1" * 64,
                    started_at_epoch=1.0, finished_at_epoch=2.0, diagnostic="")
        base.update(over)
        return AttemptRecord(**base)

    rec()                                         # 一致的正例可构造
    with pytest.raises(VerificationError):
        rec(run_id=" run_x ")                     # canonical identity
    with pytest.raises(VerificationError):
        rec(contract_hash="not-a-hash")
    with pytest.raises(VerificationError):
        rec(verdict="MAYBE")                      # verdict 封闭词表
    with pytest.raises(VerificationError):
        rec(verdict="", report_id="", failure_signature="")   # 失败记录需签名
    with pytest.raises(VerificationError):
        rec(verdict="", report_id="vrp_" + "b" * 32, failure_signature="1" * 64)
    with pytest.raises(VerificationError):
        rec(verdict="VERIFIED", failure_signature="1" * 64)   # VERIFIED 零签名
    with pytest.raises(VerificationError):
        rec(started_at_epoch=2.0, finished_at_epoch=1.0)      # 时序


def test_p10_b3_lying_list_container_subclass_rejected(env):
    """P10-B3 锁定（reviewer 反例）：LyingList（__len__=0、__iter__ 产出
    65 条）注入 terminal_events / declared_artifacts → VerificationInputError
    且 len/iter/bool/getitem 零调用——cardinality 建立在 exact builtin
    容器上，绝不经"先遍历后查长度"实现有界。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)

    class _LyingList(list):
        def __init__(self, items, calls):
            super().__init__(items)
            self._calls = calls

        def __len__(self):
            self._calls["len"] += 1
            return 0

        def __iter__(self):
            self._calls["iter"] += 1
            return list.__iter__(self)

        def __bool__(self):
            self._calls["bool"] += 1
            return False

        def __getitem__(self, index):
            self._calls["getitem"] += 1
            raise AssertionError("getitem must not be called")

    events = [dict(_bound_terminal(c, f"run_p10b3_t_{i:04d}"),
                   event_id=f"lev_p10b3_{i:04d}_deadbeef")
              for i in range(65)]
    calls = {"len": 0, "iter": 0, "bool": 0, "getitem": 0}
    sub = _submission(c, "run_p10b3_t_0000")
    sub["terminal_events"] = _LyingList(events, calls)
    with pytest.raises(VerificationInputError):
        v.verify(sub)
    assert calls == {"len": 0, "iter": 0, "bool": 0, "getitem": 0}

    declares = [dict(_declared(work_real / "ghost.md", artifact_id=f"lie_{i:04d}"))
                for i in range(65)]
    calls2 = {"len": 0, "iter": 0, "bool": 0, "getitem": 0}
    sub2 = _submission(c, "run_p10b3_d_0000")
    sub2["declared_artifacts"] = _LyingList(declares, calls2)
    with pytest.raises(VerificationInputError):
        v.verify(sub2)
    assert calls2 == {"len": 0, "iter": 0, "bool": 0, "getitem": 0}


def test_p10_b3_mapping_subclass_and_nested_entry_rejected(env):
    """P10-B3 锁定：顶层 evidence 的 Mapping 子类（keys 访问即抛密）与
    嵌套条目 dict 子类 → 全部在敌意魔术方法零调用下 fail-closed；plain
    dict/list 正例不回归。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)

    class _BoomKeysDict(dict):
        def __init__(self, *a, calls=None, **k):
            super().__init__(*a, **k)
            self._calls = calls if calls is not None else {"keys": 0}

        @property
        def keys(self):
            self._calls["keys"] += 1
            raise RuntimeError(f"leak:{_P8_SECRET}")

    hostile = _BoomKeysDict({"run_id": "run_x"}, calls={"keys": 0})
    with pytest.raises(VerificationInputError) as ei:
        v.verify(hostile)
    assert hostile._calls["keys"] == 0
    assert _P8_SECRET not in str(ei.value)

    class _LyingEventDict(dict):
        def __init__(self, *a, calls=None, **k):
            super().__init__(*a, **k)
            self._calls = calls if calls is not None else {"keys": 0}

        def keys(self):
            self._calls["keys"] += 1
            return iter(())

    calls = {"keys": 0}
    ev = _LyingEventDict(_bound_terminal(c, "run_p10b3_n_0001"), calls=calls)
    sub = _submission(c, "run_p10b3_n_0001", terminal=[ev])
    with pytest.raises(VerificationInputError):
        v.verify(sub)
    assert calls["keys"] == 0
    # plain dict/list 正例不回归
    v.verify(_submission(c, "run_p10b3_ok_0001",
                         terminal=[dict(_bound_terminal(c, "run_p10b3_ok_0001"))]))


def test_p10_b3_collect_non_dict_closed_in_loop(env):
    """P10-B3 锁定：collect_evidence 返回非 builtin dict（MappingProxyType）
    → 在调用 get()/解析前封闭为 collect 层失败（零 verify 调用、有界收尾）。"""
    from types import MappingProxyType

    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real, budget=ExecutionBudget(
        max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=1))
    v = IndependentVerifier(c)
    out = BoundedRepairLoop(contract=c, verifier=v,
                            collect_evidence=lambda a, r: MappingProxyType({})).run()
    assert out.stop_reason is RepairStopReason.ATTEMPTS_EXHAUSTED
    assert len(out.attempts) == 1
    assert out.attempts[0].verdict == ""
    assert "collect_not_mapping" in out.attempts[0].diagnostic


# ================================================================
# Reviewer Patch 11 — B1 outcome 完整身份绑定 + verifier 真实性 API /
# B2 attempt 账本语义闭合 / B3 evidence 有界快照（reviewer-locked）
# ================================================================

def test_p11_b1_cross_contract_outcome_rejected(env):
    """P11-B1 锁定（reviewer 反例）：真实报告 + 跨 contract_id → 构造拒绝
    （final_report 与终局的完整身份绑定）。"""
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome
    tmp, work, work_real, outside, outside_real = env
    c_v = _verified_summary_contract(work_real, "wc_16f_p11b1_v_0001")
    rep = _p10_verified_report(c_v)
    other = _verified_summary_contract(work_real, "wc_16f_p11b1_other_0001")
    good_attempt = AttemptRecord(
        attempt_id="att_p11b1_0001", run_id=rep.run_id,
        contract_hash=rep.contract_hash, verdict="VERIFIED",
        report_id=rep.report_id, failure_signature="",
        started_at_epoch=1.0, finished_at_epoch=2.0)
    with pytest.raises(VerificationError):
        RepairOutcome(stop_reason=RepairStopReason.VERIFIED,
                      contract_id=other.contract_id,
                      contract_hash=other.content_hash,
                      attempts=(good_attempt,), final_report=rep,
                      started_at_epoch=1.0, finished_at_epoch=2.0)


def test_p11_b1_forged_seal_outcome_authenticity_false(env):
    """P11-B1 锁定（reviewer 反例）：假 64-hex seal + 全部结构字段一致 →
    结构可构造（RepairOutcome 只负责结构绑定），但
    verifier.outcome_is_authentic == false；当前 verifier 的真实 outcome
    → true（FORGED_SEAL_OUTCOME_ACCEPTED=false）。"""
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p11b1_forged_0001")
    v = IndependentVerifier(c)
    real = _p10_verified_report(c)
    forged = VerificationReport(
        report_id=real.report_id, verifier_id=real.verifier_id,
        contract_id=real.contract_id, contract_hash=real.contract_hash,
        standard_hash=real.standard_hash, run_id=real.run_id,
        backend_id=real.backend_id, verdict=VerificationVerdict.VERIFIED,
        checks=real.checks, diagnostics=real.diagnostics, evidence=real.evidence,
        started_at_epoch=real.started_at_epoch,
        finished_at_epoch=real.finished_at_epoch,
        authority_seal="b" * 64)          # 假 64-hex seal：格式合法、内容伪造
    attempt = AttemptRecord(
        attempt_id="att_p11b1f_0001", run_id=forged.run_id,
        contract_hash=forged.contract_hash, verdict="VERIFIED",
        report_id=forged.report_id, failure_signature="",
        started_at_epoch=1.0, finished_at_epoch=2.0)
    outcome = RepairOutcome(
        stop_reason=RepairStopReason.VERIFIED,
        contract_id=forged.contract_id, contract_hash=forged.contract_hash,
        attempts=(attempt,), final_report=forged,
        started_at_epoch=1.0, finished_at_epoch=2.0)
    assert v.outcome_is_authentic(outcome) is False
    # 当前 verifier 真实 run 产出 → 真实 outcome → true
    out = BoundedRepairLoop(
        contract=c, verifier=v,
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        now_fn=FakeClock(500.0),
        boundary_snapshot=_BoundarySource(c, cost=0.0).snapshot).run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert v.outcome_is_authentic(out) is True


def test_p11_b1_foreign_verifier_outcome_false(env):
    """P11-B1 锁定：外来验证器（另一密钥）签发报告组成的 outcome →
    当前 verifier 真实性复核 false。"""
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p11b1_foreign_0001")
    foreign = IndependentVerifier(c)          # 另一密钥、同一契约
    rep = foreign.verify(_ok_summary_submission(c, "run_p11b1_f_0001"))
    attempt = AttemptRecord(
        attempt_id="att_p11b1fo_0001", run_id=rep.run_id,
        contract_hash=rep.contract_hash, verdict="VERIFIED",
        report_id=rep.report_id, failure_signature="",
        started_at_epoch=1.0, finished_at_epoch=2.0)
    outcome = RepairOutcome(
        stop_reason=RepairStopReason.VERIFIED,
        contract_id=c.contract_id, contract_hash=c.content_hash,
        attempts=(attempt,), final_report=rep,
        started_at_epoch=1.0, finished_at_epoch=2.0)
    assert IndependentVerifier(c).outcome_is_authentic(outcome) is False


def test_p11_b1_malformed_outcome_false_no_raise(env):
    """P11-B1 锁定：object.__new__ 旁路畸形 outcome / 任意对象 / None →
    outcome_is_authentic 一律 False，绝不抛异常。"""
    from furina.agent.verification.repair import RepairOutcome
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    bypass_outcome = object.__new__(RepairOutcome)
    assert v.outcome_is_authentic(bypass_outcome) is False
    assert v.outcome_is_authentic(object()) is False
    assert v.outcome_is_authentic(None) is False


def test_p11_b2_attempt_ledger_semantic_closure(env):
    """P11-B2 锁定（reviewer 反例全表）：FAILED/INCONCLUSIVE 空签名、
    attempt 时间窗外（[100,200] vs [0,10]）、未按时间非递减、attempt_id/
    run_id 重复——全部构造拒绝。"""
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p11b2_0001")
    rep = _p10_verified_report(c)

    def attempt(**over):
        base = dict(attempt_id="att_p11b2_0001", run_id=rep.run_id,
                    contract_hash=rep.contract_hash, verdict="VERIFIED",
                    report_id=rep.report_id, failure_signature="",
                    started_at_epoch=1.0, finished_at_epoch=2.0)
        base.update(over)
        return AttemptRecord(**base)

    def outcome(attempts, **over):
        base = dict(stop_reason=RepairStopReason.VERIFIED,
                    contract_id=rep.contract_id, contract_hash=rep.contract_hash,
                    attempts=attempts, final_report=rep,
                    started_at_epoch=0.0, finished_at_epoch=10.0, diagnostic="")
        base.update(over)
        return RepairOutcome(**base)

    outcome((attempt(),))                     # 一致的正例可构造
    with pytest.raises(VerificationError):
        attempt(verdict="FAILED", report_id="vrp_" + "c" * 32,
                failure_signature="")         # FAILED 空签名（reviewer 反例）
    with pytest.raises(VerificationError):
        attempt(verdict="INCONCLUSIVE", report_id="vrp_" + "c" * 32,
                failure_signature="")         # INCONCLUSIVE 空签名
    with pytest.raises(VerificationError):
        outcome((attempt(started_at_epoch=100.0,
                         finished_at_epoch=200.0),))   # 时间窗外（reviewer 反例）
    a_early = attempt(attempt_id="att_p11b2_0002",
                      started_at_epoch=5.0, finished_at_epoch=6.0)
    a_late = attempt(attempt_id="att_p11b2_0003",
                     started_at_epoch=3.0, finished_at_epoch=4.0)
    with pytest.raises(VerificationError):
        outcome((a_early, a_late))            # 未按时间非递减
    with pytest.raises(VerificationError):
        outcome((attempt(), attempt()))       # attempt_id/run_id 重复
    with pytest.raises(VerificationError):
        outcome((attempt(),
                 attempt(attempt_id="att_p11b2_0009")))   # run_id 重复


def test_p11_b3_unknown_keys_fast_reject_bounded_diag(env):
    """P11-B3 锁定：大量未知顶层键 / 大量未知 claim 键 → O(1) 数量前置
    快速拒绝、诊断有界（绝不枚举全部敌意键）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    hostile = {f"unknown_key_{i:04d}": i for i in range(500)}
    with pytest.raises(VerificationInputError) as ei:
        v.verify(hostile)
    assert len(str(ei.value)) < 600
    claim = {f"claim_key_{i:04d}": "x" for i in range(500)}
    sub = {"run_id": "run_p11b3_0001", "backend_id": "native_agent",
           "terminal_events": [claim], "declared_artifacts": []}
    with pytest.raises(VerificationInputError) as ei2:
        v.verify(sub)
    assert len(str(ei2.value)) < 600


def test_p11_b3_snapshot_bounded_under_mutation(env):
    """P11-B3 锁定：解析期间原始 list 被并发追加超过上限——追加项不进入
    本轮解析、总处理量保持上界（builtin tuple 快照语义；若追加先于快照
    落地，则数量前置检查拒绝——两条路径都有界）。"""
    import threading

    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p11b3_0001")
    v = IndependentVerifier(c)
    events = [dict(_bound_terminal(c, f"run_p11b3_m_{i:04d}"),
                   event_id=f"lev_p11_m_{i:04d}_deadbeef") for i in range(64)]
    sub = {"run_id": "run_p11b3_m_0000", "backend_id": "native_agent",
           "terminal_events": events, "declared_artifacts": []}

    def append_more():
        for i in range(300):
            events.append(dict(events[0],
                               event_id=f"lev_p11_x_{i:04d}_deadbeef"))

    t = threading.Thread(target=append_more)
    t.start()
    try:
        rep = v.verify(sub)
    except VerificationInputError as exc:
        t.join()
        assert "超界" in str(exc)          # 追加先于快照 → 数量前置拒绝
        return
    t.join()
    assert rep.verdict is VerificationVerdict.VERIFIED
    assert len(rep.evidence.terminal) <= 64   # 追加项绝不进入本轮解析
    assert len(rep.evidence.terminal) == 64


# ================================================================
# Reviewer Patch 12 — B1 outcome 权威 API 禁实例 shadowing /
# B2 attempt 数量双层硬上限（reviewer-locked）
# ================================================================

def _p12_forged_outcome(c):
    """构造结构一致、seal 伪造的 VERIFIED outcome（假 64-hex seal）。"""
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome
    real = _p10_verified_report(c)
    forged = VerificationReport(
        report_id=real.report_id, verifier_id=real.verifier_id,
        contract_id=real.contract_id, contract_hash=real.contract_hash,
        standard_hash=real.standard_hash, run_id=real.run_id,
        backend_id=real.backend_id, verdict=VerificationVerdict.VERIFIED,
        checks=real.checks, diagnostics=real.diagnostics, evidence=real.evidence,
        started_at_epoch=real.started_at_epoch,
        finished_at_epoch=real.finished_at_epoch,
        authority_seal="b" * 64)
    attempt = AttemptRecord(
        attempt_id="att_p12_0001", run_id=forged.run_id,
        contract_hash=forged.contract_hash, verdict="VERIFIED",
        report_id=forged.report_id, failure_signature="",
        started_at_epoch=1.0, finished_at_epoch=2.0)
    return RepairOutcome(
        stop_reason=RepairStopReason.VERIFIED,
        contract_id=forged.contract_id, contract_hash=forged.contract_hash,
        attempts=(attempt,), final_report=forged,
        started_at_epoch=1.0, finished_at_epoch=2.0)


def test_p12_b1_seal_shadowing_cannot_bypass_outcome_authenticity(env):
    """P12-B1 锁定（reviewer 反例）：实例注入 seal_is_authentic=lambda: True
    后，普通调用与类入口调用的 outcome_is_authentic 都仍为 false——seal
    复核经类级绑定，实例 shadowing 无法替换权威行为。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p12b1_0001")
    v = IndependentVerifier(c)
    forged = _p12_forged_outcome(c)
    assert v.outcome_is_authentic(forged) is False      # shadow 之前即 false
    v.seal_is_authentic = lambda report: True           # 实例 shadowing
    assert v.outcome_is_authentic(forged) is False      # 普通调用仍 false
    assert IndependentVerifier.outcome_is_authentic(
        v, forged) is False                             # 类入口仍 false
    # shadow 本身确实生效（仅证明注入成功——对比上面的 false）
    assert v.seal_is_authentic(object.__new__(VerificationReport)) is True


def test_p12_b1_class_entry_unaffected_by_verify_shadow(env):
    """P12-B1 锁定：实例注入 verify/outcome_is_authentic shadow 属性 →
    类入口对真实 outcome 的判定不受影响（真实 outcome → true）。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p12b1_cls_0001")
    v = IndependentVerifier(c)
    out = BoundedRepairLoop(
        contract=c, verifier=v,
        collect_evidence=lambda a, r: _ok_summary_submission(c, r),
        now_fn=FakeClock(500.0),
        boundary_snapshot=_BoundarySource(c, cost=0.0).snapshot).run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    v.verify = lambda evidence: None
    v.outcome_is_authentic = lambda outcome: False
    assert IndependentVerifier.outcome_is_authentic(v, out) is True
    assert IndependentVerifier.seal_is_authentic(v, out.final_report) is True


def test_p12_b1_hostile_stop_reason_value_property_zero_calls(env):
    """P12-B1 锁定：object.__new__ 旁路 outcome 携带敌意 stop_reason.value
    property → false 且 property 调用次数为 0（exact RepairStopReason 先于
    identity 比较，禁止 getattr 动态分派）。"""
    from furina.agent.verification.repair import RepairOutcome
    tmp, work, work_real, outside, outside_real = env
    c = _contract(work_real)
    v = IndependentVerifier(c)
    calls = {"value": 0}

    class _HostileStop:
        @property
        def value(self):
            calls["value"] += 1
            raise RuntimeError(f"leak:{_P8_SECRET}")

    bypass = object.__new__(RepairOutcome)
    object.__setattr__(bypass, "stop_reason", _HostileStop())
    assert v.outcome_is_authentic(bypass) is False
    assert calls["value"] == 0


def test_p12_b2_global_attempt_cap_enforced(env):
    """P12-B2 锁定（reviewer 反例）：100 个身份唯一、时序合法的 attempts →
    构造拒绝（WorkContract 全局上限 99）；上限拒绝发生在元素遍历之前
    （100 个非 AttemptRecord 元素同样以数量错误拒绝）；99 个合法 attempts
    不因数量误拒。"""
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p12b2_0001")
    rep = _p10_verified_report(c)

    def mk(i):
        return AttemptRecord(
            attempt_id=f"att_p12b2_{i:04d}", run_id=f"run_p12b2_{i:04d}",
            contract_hash=rep.contract_hash, verdict="FAILED",
            report_id="vrp_" + f"{i:032d}",
            failure_signature="2" * 64,
            started_at_epoch=i * 0.1, finished_at_epoch=i * 0.1 + 0.09)

    hundred = tuple(mk(i) for i in range(100))
    with pytest.raises(VerificationError) as ei:
        RepairOutcome(stop_reason=RepairStopReason.ATTEMPTS_EXHAUSTED,
                      contract_id=rep.contract_id,
                      contract_hash=rep.contract_hash,
                      attempts=hundred, final_report=None,
                      started_at_epoch=0.0, finished_at_epoch=10.0)
    assert "超界硬上限" in str(ei.value)
    # 元素遍历之前拒绝：100 个非 AttemptRecord 元素同样以数量错误拒绝
    with pytest.raises(VerificationError) as ei2:
        RepairOutcome(stop_reason=RepairStopReason.ATTEMPTS_EXHAUSTED,
                      contract_id=rep.contract_id,
                      contract_hash=rep.contract_hash,
                      attempts=tuple(range(100)), final_report=None,
                      started_at_epoch=0.0, finished_at_epoch=10.0)
    assert "超界硬上限" in str(ei2.value)
    # 全局边界 99 不因数量误拒（其余字段合法）
    ninetynine = tuple(mk(i) for i in range(99))
    outcome = RepairOutcome(stop_reason=RepairStopReason.ATTEMPTS_EXHAUSTED,
                            contract_id=rep.contract_id,
                            contract_hash=rep.contract_hash,
                            attempts=ninetynine, final_report=None,
                            started_at_epoch=0.0, finished_at_epoch=10.0)
    assert len(outcome.attempts) == 99


def test_p12_b2_contract_attempt_cap_in_authenticity(env):
    """P12-B2 锁定：当前契约 budget.max_attempts=1、outcome 含 2 个
    attempts → outcome_is_authentic=false；边界内真实 outcome → true。"""
    from furina.agent.verification.repair import AttemptRecord, RepairOutcome
    tmp, work, work_real, outside, outside_real = env
    (work_real / "summary.md").write_bytes(b"ok")
    c1 = _contract(work_real, contract_id="wc_16f_p12b2_c1_0001",
                   budget=ExecutionBudget(max_duration_seconds=600.0,
                                          cost_limit=CostBudget(amount=5.0),
                                          max_attempts=1))
    v = IndependentVerifier(c1)
    real = v.verify(_ok_summary_submission(c1, "run_p12c1_v_0001"))

    a0 = AttemptRecord(attempt_id="att_p12c1_0001", run_id="run_p12c1_early_0001",
                       contract_hash=c1.content_hash, verdict="FAILED",
                       report_id="vrp_" + "d" * 32, failure_signature="3" * 64,
                       started_at_epoch=1.0, finished_at_epoch=2.0)
    a1 = AttemptRecord(attempt_id="att_p12c1_0002", run_id=real.run_id,
                       contract_hash=real.contract_hash, verdict="VERIFIED",
                       report_id=real.report_id, failure_signature="",
                       started_at_epoch=3.0, finished_at_epoch=4.0)
    two = RepairOutcome(stop_reason=RepairStopReason.VERIFIED,
                        contract_id=c1.contract_id,
                        contract_hash=c1.content_hash,
                        attempts=(a0, a1), final_report=real,
                        started_at_epoch=0.0, finished_at_epoch=10.0)
    assert v.outcome_is_authentic(two) is False        # 契约级上限（2 > 1）
    one = RepairOutcome(stop_reason=RepairStopReason.VERIFIED,
                        contract_id=c1.contract_id,
                        contract_hash=c1.content_hash,
                        attempts=(a1,), final_report=real,
                        started_at_epoch=0.0, finished_at_epoch=10.0)
    assert v.outcome_is_authentic(one) is True         # 边界内真实 outcome


# ================================================================
# Reviewer Patch 13 — P0：outcome_is_authentic 完整复核（单一可信结构
# helper 共享；绝不只抽查最后一个 attempt）（reviewer-locked）
# ================================================================

class _P13HostileObj:
    """全部协议方法计数并抛携密异常的敌意对象。"""

    def __init__(self):
        self.calls = {"eq": 0, "ne": 0, "str": 0, "repr": 0, "bool": 0,
                      "hash": 0}

    def __eq__(self, other):
        self.calls["eq"] += 1
        raise RuntimeError(f"leak:{_P8_SECRET}")

    def __ne__(self, other):
        self.calls["ne"] += 1
        raise RuntimeError(f"leak:{_P8_SECRET}")

    def __hash__(self):
        self.calls["hash"] += 1
        raise RuntimeError(f"leak:{_P8_SECRET}")

    def __str__(self):
        self.calls["str"] += 1
        raise RuntimeError(f"leak:{_P8_SECRET}")

    def __repr__(self):
        self.calls["repr"] += 1
        raise RuntimeError(f"leak:{_P8_SECRET}")

    def __bool__(self):
        self.calls["bool"] += 1
        raise RuntimeError(f"leak:{_P8_SECRET}")


def _p13_bypass_outcome(c, **fields):
    """object.__new__(RepairOutcome) 旁路构造（绕过 __post_init__）。"""
    from furina.agent.verification.repair import RepairOutcome
    o = object.__new__(RepairOutcome)
    defaults = dict(stop_reason=RepairStopReason.VERIFIED,
                    contract_id=c.contract_id, contract_hash=c.content_hash,
                    attempts=(), final_report=None,
                    started_at_epoch=0.0, finished_at_epoch=10.0, diagnostic="")
    defaults.update(fields)
    for key, value in defaults.items():
        object.__setattr__(o, key, value)
    return o


def _p13_bypass_attempt(**fields):
    """object.__new__(AttemptRecord) 旁路构造（绕过 __post_init__）。"""
    from furina.agent.verification.repair import AttemptRecord
    a = object.__new__(AttemptRecord)
    defaults = dict(attempt_id="att_p13_0001", run_id="run_p13_0001",
                    contract_hash="0" * 64, verdict="VERIFIED", report_id="",
                    failure_signature="", started_at_epoch=0.0,
                    finished_at_epoch=1.0, diagnostic="")
    defaults.update(fields)
    for key, value in defaults.items():
        object.__setattr__(a, key, value)
    return a


def test_p13_hostile_earlier_attempt_authentic_false(env):
    """P13 锁定（reviewer 反例 1）：attempts=(敌意对象, 合法 VERIFIED
    last) → outcome_is_authentic=false，敌意对象协议方法零调用。"""
    from furina.agent.verification.repair import AttemptRecord
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p13_a_0001")
    v = IndependentVerifier(c)
    rep = v.verify(_ok_summary_submission(c, "run_p13_a_0001"))
    last = AttemptRecord(attempt_id="att_p13_a_0002", run_id=rep.run_id,
                         contract_hash=rep.contract_hash, verdict="VERIFIED",
                         report_id=rep.report_id, failure_signature="",
                         started_at_epoch=1.0, finished_at_epoch=2.0)
    hostile = _P13HostileObj()
    bypass = _p13_bypass_outcome(c, attempts=(hostile, last), final_report=rep)
    assert v.outcome_is_authentic(bypass) is False
    assert all(n == 0 for n in hostile.calls.values()), hostile.calls


def test_p13_bad_contract_hash_earlier_attempt_false(env):
    """P13 锁定（reviewer 反例 2）：前置 attempt contract_hash 错误 →
    outcome_is_authentic=false。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p13_b_0001")
    v = IndependentVerifier(c)
    rep = v.verify(_ok_summary_submission(c, "run_p13_b_0001"))
    bad = _p13_bypass_attempt(attempt_id="att_p13_b_0001",
                              run_id="run_p13_b_early_0001",
                              contract_hash="not-a-hash")
    last = _p13_bypass_attempt(attempt_id="att_p13_b_0002", run_id=rep.run_id,
                               contract_hash=rep.contract_hash,
                               verdict="VERIFIED", report_id=rep.report_id,
                               started_at_epoch=1.0, finished_at_epoch=2.0)
    bypass = _p13_bypass_outcome(c, attempts=(bad, last), final_report=rep)
    assert v.outcome_is_authentic(bypass) is False


def test_p13_out_of_window_and_out_of_order_earlier_attempts_false(env):
    """P13 锁定（reviewer 反例 3）：前置 attempt 时间越界 / 乱序 →
    outcome_is_authentic=false。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p13_c_0001")
    v = IndependentVerifier(c)
    rep = v.verify(_ok_summary_submission(c, "run_p13_c_0001"))
    last = _p13_bypass_attempt(attempt_id="att_p13_c_0002", run_id=rep.run_id,
                               contract_hash=rep.contract_hash,
                               verdict="VERIFIED", report_id=rep.report_id,
                               started_at_epoch=1.0, finished_at_epoch=2.0)
    out_of_window = _p13_bypass_attempt(
        attempt_id="att_p13_c_0001", run_id="run_p13_c_early_0001",
        started_at_epoch=100.0, finished_at_epoch=200.0)
    bypass = _p13_bypass_outcome(c, attempts=(out_of_window, last),
                                 final_report=rep)
    assert v.outcome_is_authentic(bypass) is False
    out_of_order = _p13_bypass_attempt(
        attempt_id="att_p13_c_0003", run_id="run_p13_c_early_0002",
        started_at_epoch=5.0, finished_at_epoch=6.0)
    bypass2 = _p13_bypass_outcome(c, attempts=(out_of_order, last),
                                  final_report=rep)
    assert v.outcome_is_authentic(bypass2) is False


def test_p13_duplicate_earlier_attempt_identity_false(env):
    """P13 锁定（reviewer 反例 4）：前置 attempt 与最后 attempt 重复
    attempt_id / run_id → outcome_is_authentic=false。"""
    tmp, work, work_real, outside, outside_real = env
    c = _verified_summary_contract(work_real, "wc_16f_p13_d_0001")
    v = IndependentVerifier(c)
    rep = v.verify(_ok_summary_submission(c, "run_p13_d_0001"))
    last = _p13_bypass_attempt(attempt_id="att_p13_d_0001", run_id=rep.run_id,
                               contract_hash=rep.contract_hash,
                               verdict="VERIFIED", report_id=rep.report_id,
                               started_at_epoch=1.0, finished_at_epoch=2.0)
    dup_id = _p13_bypass_attempt(attempt_id="att_p13_d_0001",
                                 run_id="run_p13_d_early_0001",
                                 started_at_epoch=0.0, finished_at_epoch=0.5)
    dup_run = _p13_bypass_attempt(attempt_id="att_p13_d_0002",
                                  run_id=rep.run_id,
                                  started_at_epoch=0.0, finished_at_epoch=0.5)
    bypass = _p13_bypass_outcome(c, attempts=(dup_id, last), final_report=rep)
    assert v.outcome_is_authentic(bypass) is False
    bypass2 = _p13_bypass_outcome(c, attempts=(dup_run, last), final_report=rep)
    assert v.outcome_is_authentic(bypass2) is False


def test_p13_hostile_bypass_attempt_fields_zero_calls(env):
    """P13 锁定（reviewer 反例 5）：object.__new__(AttemptRecord) 旁路携带
    敌意字段 → 复核 false 且敌意协议调用次数为 0（exact type 先于任何
    比较/词法校验）。"""
    tmp, work, work_real, outside, outside_real = env
    from furina.agent.verification.repair import AttemptRecord
    c = _verified_summary_contract(work_real, "wc_16f_p13_e_0001")
    v = IndependentVerifier(c)
    rep = v.verify(_ok_summary_submission(c, "run_p13_e_0001"))
    last = AttemptRecord(attempt_id="att_p13_e_0002", run_id=rep.run_id,
                         contract_hash=rep.contract_hash, verdict="VERIFIED",
                         report_id=rep.report_id, failure_signature="",
                         started_at_epoch=1.0, finished_at_epoch=2.0)
    hostile = _P13HostileObj()
    bad = _p13_bypass_attempt(attempt_id=hostile)
    bypass = _p13_bypass_outcome(c, attempts=(bad, last), final_report=rep)
    assert v.outcome_is_authentic(bypass) is False
    assert all(n == 0 for n in hostile.calls.values()), hostile.calls


def test_p13_real_multi_attempt_outcome_authentic_true(env):
    """P13 锁定（正例）：完整真实多 attempt outcome（FAILED→VERIFIED）→
    outcome_is_authentic=true——合法 BoundedRepairLoop 输出零改变。"""
    tmp, work, work_real, outside, outside_real = env
    art = work_real / "summary.md"
    art.write_bytes(b"stale")
    c = _contract(work_real, contract_id="wc_16f_p13_f_0001",
                  budget=ExecutionBudget(max_duration_seconds=600.0,
                                         cost_limit=CostBudget(amount=5.0),
                                         max_attempts=5))
    v = IndependentVerifier(c)
    good = b"fresh content p13"
    stale_sha = _sha(b"stale")
    good_sha = _sha(good)
    state = {"attempt": 0}

    def collector(attempt_id, run_id):
        state["attempt"] += 1
        if state["attempt"] == 1:
            art.write_bytes(b"tampered-p13")
            return _submission(c, run_id,
                               declared=[_declared(art, sha_hex=stale_sha)])
        art.write_bytes(good)
        return _submission(c, run_id,
                           declared=[_declared(art, sha_hex=good_sha)])

    out = BoundedRepairLoop(
        contract=c, verifier=v, collect_evidence=collector,
        now_fn=FakeClock(500.0),
        boundary_snapshot=_BoundarySource(c, cost=0.0).snapshot).run()
    assert out.stop_reason is RepairStopReason.VERIFIED
    assert len(out.attempts) == 2
    assert v.outcome_is_authentic(out) is True
