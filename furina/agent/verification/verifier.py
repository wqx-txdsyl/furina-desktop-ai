"""Phase 16F — IndependentVerifier：任务级独立校验器（VERIFIED 唯一授权入口）。

权威模型（16F 任务书 §1/§3 + 关键锁定 1–3 + Reviewer Patch 1 + Reviewer Patch 2
+ Reviewer Patch 3（blocker B2/B5））：

- **单路径单快照（Patch 3 B2）**：每次 ``verify()`` 建立 canonical-path
  snapshot cache（:class:`_PathSnapshotCache`）——expectation / declared /
  exists / sha / text / regex 对同一路径复用同一不可变完整快照（一次打开、
  同一句柄、完整有界内容 + 全文文本合法性 + 1 MiB 解码窗口），任何检查
  不得重新按路径打开已缓存文件；criterion-only 文件同样完整读取并先证明
  整体为合法文本，empty/unreadable/oversize/mutated/path escape 一律
  required FAIL。
- **公开模型身份验证（Patch 3 B5）**：``artifact_id`` / ``event_id`` /
  ``run_id`` / ``backend_id`` / ``contract_id`` 在 public 模型
  ``__post_init__`` 统一经 canonical ``validate_identity``——秘密形态直接
  拒绝，绝不清洗后继续作为身份；秘密路径异常回显一律脱敏（禁止
  ``{path!r}`` 原文），raw secret 不进入异常/诊断/报告导出。

- **VERIFIED 只能由本类在真实执行全部确定性检查且全部通过后产生**。任何其它
  代码路径构造 verdict=VERIFIED 的报告要么被 :class:`VerificationAuthorityError`
  拒绝（无 seal / 非 16F 身份），要么携带的 seal 无法通过
  :meth:`seal_is_authentic` 真实性复核（seal 是验证器构造期随机密钥对
  report_digest 的 HMAC-SHA256——与 16D broker 密钥 HMAC 同模式，绝不依赖
  _private / 对象身份 / 调用方自报字段冒充 authority）。
- **substantive gate（blocker 1）**：verifier_ref 只表示"选择/支持哪个
  verifier"，terminal claim 只表示"可以开始校验"，backend allowlist 只表示
  "证据可归属"——三者全 PASS **不构成成功证据**。没有至少一项真实
  substantive deterministic check（WorkContract 判据本地确定性 PASS 或
  required artifact 真实本地检查 PASS）时，最终裁定强制 INCONCLUSIVE，
  绝不 VERIFIED、绝不签 seal。
- **完整内容真实性（blocker B1）**：产物 MIME 与有效性判定基于**同一稳定、
  完整、有界快照**（≤ MAX_ARTIFACT_BYTES 的全部字节，
  :func:`~checks.full_content_verdict`）——JSON 完整严格解析、text 完整严格
  解码、PDF 偏移 0 + 封闭结构、PNG/JPEG Pillow 结构验证、binary 显式接受、
  空/畸形/截断/不可读一律 required FAIL；绝不只检查文件头后默认剩余内容
  可信，绝不把无法验证降级为 PASS。
- **句柄锚定 containment（blocker B3）**：artifact 与判据文件的安全判断绝不
  只依赖 open 前的 ``realpath``——先受约束打开，再依据**该句柄**的 OS 级
  真实目标证明其位于 workspace root 内；hash/size/MIME/内容/判据读取全部
  来自同一已证明句柄或同一不可变快照；验证期间路径替换/inode 变化/截断/
  增长一律失败；平台无法给出句柄目标证明 → 拒绝该检查，绝不退回不安全
  路径模式。
- **artifact type 策略（blocker B2）**：``ARTIFACT_TYPE_CONTENT_RULES`` 在
  API 层不可变（MappingProxyType + tuple 嵌套），验证器不持有可被调用方
  修改的共享可变引用；未知 artifact_type 始终 fail-closed。
- **optional artifact（blocker 3）**：optional 只豁免"不存在"；一旦存在，
  path escape / symlink 逃逸 / oversize / empty / unreadable / malformed /
  unsupported MIME / non-regular / 声明矛盾任一发生都是 required FAIL，
  最终不得 VERIFIED。
- **稳定快照（blocker 7）**：同一次 verify 内 size/hash/MIME 判据来自同一
  句柄的有界本地快照，前后 fstat/stat 一致性证明——验证期间文件被替换、
  截断、增长、inode 变化 → artifact_mutated_during_verification → FAIL。
- backend completed / exit 0 / 成功文本 / backend 自报 verified **不是证明**：
  证据提交的 exact-schema 里根本没有这些字段（未知键 fail-closed）；本地
  观察与本地重跑才是真值。
- 每次校验：exact-schema 解析（fail-closed，身份字段显式 lexical contract，
  绝不 normalize 后重新绑定）→ defensive-copy 冻结 → 本地证据收集 →
  确定性检查 → 聚合 → 报告 + 密封。
- 报告与导出零共享可变引用；raw secret text 不进入报告、诊断与身份载荷
  （解释文本/路径记录面一律脱敏；秘密形态身份/路径直接拒绝）。

聚合规则：任一 required 检查 FAIL → FAILED；否则任一 required
NOT_EVALUABLE（含 substantive gate 否定分支）→ INCONCLUSIVE；全部 required
PASS → VERIFIED。INCONCLUSIVE 绝不映射 VERIFIED。

本模块零 DB / 零 C1–C7 / 零事件总线 / 零持久化（C6/C7/C3 写入属 16G）。
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import secrets as _secrets
import time
import uuid
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from furina.agent.events.models import TERMINAL_KINDS, EventKind
from furina.agent.work_contract import WorkContract, compute_content_hash

from . import checks as _checks
from .models import (
    ARTIFACT_TYPE_CONTENT_RULES,
    MAX_ARTIFACT_BYTES,
    MAX_DECLARED_ARTIFACTS,
    MAX_DIAGNOSTICS,
    MAX_EVIDENCE_EVENTS,
    MAX_ID_CHARS,
    MAX_PATH_CHARS,
    MAX_PROCESS_TIMEOUT_SECONDS,
    MAX_REPORT_CHECKS,
    DEFAULT_PROCESS_TIMEOUT_SECONDS,
    SUPPORTED_MIME_TYPES,
    VERIFICATION_INPUT_KEYS,
    VERIFIER_ID,
    ArtifactObservation,
    CheckResult,
    EvidenceBundle,
    TerminalObservation,
    VerificationCheck,
    VerificationError,
    VerificationInputError,
    VerificationReport,
    VerificationVerdict,
    compute_report_digest,
    declared_mime_consistent,
    mime_for_suffix,
    scrub_secrets,
    validate_identity,
)

_TERMINAL_KIND_VALUES = frozenset(k.value for k in TERMINAL_KINDS)
_EVENT_KIND_VALUES = frozenset(k.value for k in EventKind)


class _PathSnapshotCache:
    """单次 verify 内的 canonical-path → 不可变快照（Patch 3 B2）。

    同一 canonical 路径（normcase + normpath + expanduser）在单次 verify
    中只捕获一次 :class:`~checks.FileSnapshot`——expectation / declared /
    exists / sha / text / regex 全部复用同一完整快照，任何检查都不得重新
    按路径打开已缓存文件（"同路径只打开一次"）。捕获一律经句柄锚定
    containment 证明（writable=True 观察语义）。
    """

    def __init__(self, contains_path: Callable[[str, bool], bool]) -> None:
        self._contains_path = contains_path
        self._entries: Dict[str, Any] = {}

    def get(self, claimed_path: str) -> Any:
        key = os.path.normcase(os.path.normpath(os.path.expanduser(claimed_path)))
        snap = self._entries.get(key)
        if snap is None:
            snap = _checks.capture_file_contained(claimed_path,
                                                  self._contains_path, True)
            self._entries[key] = snap
        return snap


class IndependentVerifier:
    """绑定单个不可变 WorkContract 的任务级独立校验器。

    构造期生成随机 seal 密钥（仅内存）；``verify(evidence)`` 可重复调用
    （repair loop 每次 attempt 独立评估新证据），每次产出全新不可变报告。
    """

    def __init__(self, contract: WorkContract, *, now_fn=time.time,
                 process_timeout_seconds: float = DEFAULT_PROCESS_TIMEOUT_SECONDS) -> None:
        if not isinstance(contract, WorkContract):
            raise VerificationError(
                f"verifier 必须绑定 16A WorkContract，得到 {type(contract).__name__}")
        pt = process_timeout_seconds
        if isinstance(pt, bool) or not isinstance(pt, (int, float)) \
                or not math.isfinite(float(pt)) \
                or not (0 < float(pt) <= MAX_PROCESS_TIMEOUT_SECONDS):
            raise VerificationError(
                f"process_timeout_seconds 必须在 (0, {MAX_PROCESS_TIMEOUT_SECONDS}] 内，"
                f"得到 {pt!r}")
        # 秘密边界（blocker 6）：契约侧身份/期望路径带秘密形态会造成脱敏歧义
        # （两个不同秘密值清洗成同一身份）——构造期 fail-closed，零报告零 seal。
        if scrub_secrets(contract.contract_id) != contract.contract_id:
            raise VerificationError("contract_id 带秘密形态（fail-closed）")
        for exp in contract.artifact_expectations:
            if scrub_secrets(exp.expected_path) != exp.expected_path:
                # Patch 3 B5：身份回显先脱敏（raw secret 绝不进入异常）。
                raise VerificationError(
                    f"artifact expected_path 带秘密形态（fail-closed）: "
                    f"{scrub_secrets(exp.artifact_id)[:MAX_ID_CHARS]}")
        self._contract = contract
        self._now_fn = now_fn
        self._process_timeout = float(pt)
        self._seal_key = _secrets.token_bytes(32)

    # -- 身份 ----------------------------------------------------------------
    @property
    def verifier_id(self) -> str:
        return VERIFIER_ID

    @property
    def contract(self) -> WorkContract:
        return self._contract

    @property
    def contract_id(self) -> str:
        return self._contract.contract_id

    @property
    def contract_hash(self) -> str:
        return self._contract.content_hash

    @property
    def standard_hash(self) -> str:
        return compute_content_hash(self._contract.verification_standard.to_dict())

    # -- 主入口 ----------------------------------------------------------------
    def verify(self, evidence: Mapping[str, Any]) -> VerificationReport:
        started = float(self._now_fn())
        submission = self._parse_submission(evidence)
        # Patch 3 B2：每次 verify() 建立 canonical-path snapshot cache——
        # 同一路径的 expectation/declared/exists/sha/text/regex 复用同一
        # 不可变快照，任何检查不得重新按路径打开已缓存文件。
        snapshots = _PathSnapshotCache(self._contains_path)
        bundle = self._collect_bundle(submission, snapshots)
        check_list, substantive_ids = self._run_checks(bundle, submission, snapshots)
        # substantive gate（blocker 1）：没有至少一项真实 substantive
        # deterministic check PASS → 强制 NOT_EVALUABLE → INCONCLUSIVE。
        if not any(c.check_id in substantive_ids and c.result is CheckResult.PASS
                   for c in check_list):
            check_list.append(_checks.check_no_substantive())
        if len(check_list) > MAX_REPORT_CHECKS:
            raise VerificationError(
                f"检查数量 {len(check_list)} 超过报告上限 {MAX_REPORT_CHECKS}")
        verdict = self._aggregate(check_list)
        diagnostics = self._diagnostics(bundle, check_list)
        finished = float(self._now_fn())
        checks = tuple(check_list)
        report_id = f"vrp_{uuid.uuid4().hex}"
        digest = compute_report_digest(
            report_id=report_id, verifier_id=VERIFIER_ID,
            contract_id=self._contract.contract_id,
            contract_hash=self._contract.content_hash,
            standard_hash=self.standard_hash, run_id=bundle.run_id,
            backend_id=bundle.backend_id, verdict=verdict, checks=checks,
            diagnostics=diagnostics, evidence_digest=bundle.evidence_digest(),
            started_at_epoch=started, finished_at_epoch=finished)
        seal = ""
        if verdict is VerificationVerdict.VERIFIED:
            seal = hmac.new(self._seal_key, digest.encode("utf-8"),
                            hashlib.sha256).hexdigest()
        return VerificationReport(
            report_id=report_id, verifier_id=VERIFIER_ID,
            contract_id=self._contract.contract_id,
            contract_hash=self._contract.content_hash,
            standard_hash=self.standard_hash, run_id=bundle.run_id,
            backend_id=bundle.backend_id, verdict=verdict, checks=checks,
            diagnostics=diagnostics, evidence=bundle,
            started_at_epoch=started, finished_at_epoch=finished,
            authority_seal=seal)

    # -- 权威复核 ----------------------------------------------------------------
    def seal_is_authentic(self, report: Any) -> bool:
        """VERIFIED 报告真实性的唯一复核通道：digest 一致 + seal 与本验证器密钥匹配。"""
        if not isinstance(report, VerificationReport):
            return False
        if report.verdict is not VerificationVerdict.VERIFIED:
            return False
        recomputed = compute_report_digest(
            report_id=report.report_id, verifier_id=report.verifier_id,
            contract_id=report.contract_id, contract_hash=report.contract_hash,
            standard_hash=report.standard_hash, run_id=report.run_id,
            backend_id=report.backend_id, verdict=report.verdict,
            checks=report.checks, diagnostics=report.diagnostics,
            evidence_digest=report.evidence.evidence_digest(),
            started_at_epoch=report.started_at_epoch,
            finished_at_epoch=report.finished_at_epoch)
        if not hmac.compare_digest(recomputed, report.report_digest):
            return False
        expected = hmac.new(self._seal_key, report.report_digest.encode("utf-8"),
                            hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, report.authority_seal)

    # -- 输入 exact-schema 解析（fail-closed + defensive-copy 冻结） --------------
    def _parse_submission(self, evidence: Any) -> Dict[str, Any]:
        if not isinstance(evidence, Mapping):
            raise VerificationInputError(
                f"evidence 提交必须是 Mapping，得到 {type(evidence).__name__}")
        keys = set()
        for k in evidence.keys():
            if not isinstance(k, str):
                raise VerificationInputError(f"输入键必须全为 str，得到 {k!r}")
            keys.add(k)
        unknown = sorted(keys - set(VERIFICATION_INPUT_KEYS))
        missing = sorted(set(VERIFICATION_INPUT_KEYS) - keys)
        if unknown:
            raise VerificationInputError(
                f"输入拒绝未知键: {[scrub_secrets(k)[:64] for k in unknown]}")
        if missing:
            raise VerificationInputError(f"输入缺失必需键: {missing}")

        # canonical identity（blocker 8）：显式 lexical contract——控制字符/
        # 首尾空白/静默 trim/秘密形态全部拒绝，绝不 normalize 后重新绑定；
        # 身份比较一律 exact。
        run_id = validate_identity(evidence["run_id"], "run_id")
        backend_id = validate_identity(evidence["backend_id"], "backend_id")

        events_raw = evidence["terminal_events"]
        if not isinstance(events_raw, (list, tuple)):
            raise VerificationInputError(
                f"terminal_events 必须是序列，得到 {type(events_raw).__name__}")
        if len(events_raw) > MAX_EVIDENCE_EVENTS:
            raise VerificationInputError(
                f"terminal_events 数量 {len(events_raw)} 超界 {MAX_EVIDENCE_EVENTS}")
        terminal: List[Mapping[str, Any]] = []
        seen_event_ids = set()
        for item in events_raw:
            d = self._parse_terminal_claim(item)
            if d["event_id"] in seen_event_ids:
                raise VerificationInputError(f"terminal_events 重复 event_id: {d['event_id']!r}")
            seen_event_ids.add(d["event_id"])
            terminal.append(MappingProxyType(dict(d)))   # defensive copy + 冻结

        arts_raw = evidence["declared_artifacts"]
        if not isinstance(arts_raw, (list, tuple)):
            raise VerificationInputError(
                f"declared_artifacts 必须是序列，得到 {type(arts_raw).__name__}")
        if len(arts_raw) > MAX_DECLARED_ARTIFACTS:
            raise VerificationInputError(
                f"declared_artifacts 数量 {len(arts_raw)} 超界 {MAX_DECLARED_ARTIFACTS}")
        declared: List[Mapping[str, Any]] = []
        seen_artifact_ids = set()
        for item in arts_raw:
            d = self._parse_artifact_claim(item)
            if d["artifact_id"] in seen_artifact_ids:
                raise VerificationInputError(
                    f"declared_artifacts 重复 artifact_id: {d['artifact_id']!r}")
            seen_artifact_ids.add(d["artifact_id"])
            declared.append(MappingProxyType(dict(d)))

        return {"run_id": run_id, "backend_id": backend_id,
                "terminal": tuple(terminal), "declared": tuple(declared)}

    @staticmethod
    def _parse_terminal_claim(item: Any) -> Dict[str, Any]:
        from .models import TERMINAL_CLAIM_KEYS
        if not isinstance(item, Mapping):
            raise VerificationInputError(
                f"terminal_events 条目必须是 Mapping，得到 {type(item).__name__}")
        keys = set()
        for k in item.keys():
            if not isinstance(k, str):
                raise VerificationInputError(f"terminal claim 键必须全为 str，得到 {k!r}")
            keys.add(k)
        if keys != set(TERMINAL_CLAIM_KEYS):
            raise VerificationInputError(
                f"terminal claim 键集必须恰为 {sorted(TERMINAL_CLAIM_KEYS)}，"
                f"未知 {[scrub_secrets(k)[:64] for k in sorted(keys - set(TERMINAL_CLAIM_KEYS))]} / "
                f"缺失 {sorted(set(TERMINAL_CLAIM_KEYS) - keys)}")
        event_id = validate_identity(item["event_id"], "event_id")
        kind = item["kind"]
        if not isinstance(kind, str) or kind not in _EVENT_KIND_VALUES:
            raise VerificationInputError(
                f"kind 必须是 16E 规范化词表值，得到 {kind!r}")
        ts = item["observed_at_epoch"]
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(float(ts)):
            raise VerificationInputError(
                f"observed_at_epoch 必须是有限数值（bool/NaN/Inf 拒绝），得到 {ts!r}")
        out: Dict[str, Any] = {"event_id": event_id, "kind": kind,
                               "observed_at_epoch": float(ts)}
        for name in ("run_id", "contract_id", "backend_id"):
            out[name] = validate_identity(item[name], f"terminal claim {name}")
        return out

    @staticmethod
    def _parse_artifact_claim(item: Any) -> Dict[str, Any]:
        from .models import ARTIFACT_CLAIM_KEYS, _SHA256_PATTERN
        if not isinstance(item, Mapping):
            raise VerificationInputError(
                f"declared_artifacts 条目必须是 Mapping，得到 {type(item).__name__}")
        keys = set()
        for k in item.keys():
            if not isinstance(k, str):
                raise VerificationInputError(f"artifact claim 键必须全为 str，得到 {k!r}")
            keys.add(k)
        if keys != set(ARTIFACT_CLAIM_KEYS):
            raise VerificationInputError(
                f"artifact claim 键集必须恰为 {sorted(ARTIFACT_CLAIM_KEYS)}，"
                f"未知 {[scrub_secrets(k)[:64] for k in sorted(keys - set(ARTIFACT_CLAIM_KEYS))]} / "
                f"缺失 {sorted(set(ARTIFACT_CLAIM_KEYS) - keys)}")
        aid = validate_identity(item["artifact_id"], "artifact_id")
        path = item["path"]
        if not isinstance(path, str) or not path or path != path.strip() \
                or len(path) > MAX_PATH_CHARS:
            # Patch 3 B5：异常回显一律先脱敏——raw secret 绝不进入异常消息。
            raise VerificationInputError(
                f"path 必须是非空 str(<=1024) 且无首尾空白（不静默 trim）: "
                f"{scrub_secrets(path)[:MAX_PATH_CHARS]!r}")
        if scrub_secrets(path) != path:
            raise VerificationInputError(
                f"artifact path 带秘密形态（fail-closed）: "
                f"{scrub_secrets(path)[:MAX_PATH_CHARS]!r}")
        expanded = os.path.expanduser(path)
        if not os.path.isabs(expanded):
            raise VerificationInputError(
                f"artifact path 必须是绝对路径: "
                f"{scrub_secrets(path)[:MAX_PATH_CHARS]!r}")
        d_sha = item["declared_sha256"]
        if d_sha is not None and (not isinstance(d_sha, str)
                                  or not _SHA256_PATTERN.match(d_sha)):
            raise VerificationInputError(
                f"declared_sha256 必须是 None 或 64 位小写 hex，得到 {d_sha!r}")
        d_mime = item["declared_mime"]
        if d_mime is not None and (not isinstance(d_mime, str) or not d_mime.strip()
                                   or len(d_mime) > MAX_ID_CHARS):
            raise VerificationInputError(
                f"declared_mime 必须是 None 或非空 str(<=128)，得到 "
                f"{scrub_secrets(str(d_mime))[:MAX_ID_CHARS]!r}")
        d_size = item["declared_size_bytes"]
        if d_size is not None:
            if isinstance(d_size, bool) or not isinstance(d_size, int) or d_size <= 0:
                raise VerificationInputError(
                    "declared_size_bytes 必须是 None 或正 int（bool/float/负数/0 拒绝），"
                    f"得到 {d_size!r}")
        return {"artifact_id": aid, "path": path,
                "declared_sha256": d_sha, "declared_mime": d_mime,
                "declared_size_bytes": d_size}

    # -- 本地证据收集（realpath containment + 稳定快照观察） -----------------------
    def _collect_bundle(self, submission: Dict[str, Any],
                        snapshots: _PathSnapshotCache) -> EvidenceBundle:
        diagnostics: List[str] = []
        terminal_obs: List[TerminalObservation] = []
        for t in submission["terminal"]:
            kind = t["kind"]
            if kind not in _TERMINAL_KIND_VALUES:
                diagnostics.append(f"terminal_claim_non_terminal_ignored:{t['event_id'][:64]}")
                bound = False
            else:
                bound = (t["run_id"] == submission["run_id"]
                         and t["contract_id"] == self._contract.contract_id
                         and t["backend_id"] == submission["backend_id"])
                if not bound:
                    diagnostics.append(f"terminal_claim_unbound:{t['event_id'][:64]}")
            terminal_obs.append(TerminalObservation(
                event_id=t["event_id"], kind=kind,
                observed_at_epoch=t["observed_at_epoch"], bound=bound))

        artifacts_obs: List[ArtifactObservation] = []
        for exp in self._contract.artifact_expectations:
            artifacts_obs.append(self._observe(
                "expectation", exp.artifact_id, exp.expected_path, snapshots))
        for d in submission["declared"]:
            artifacts_obs.append(self._observe(
                "declared", d["artifact_id"], d["path"], snapshots))

        return EvidenceBundle(
            contract_id=self._contract.contract_id,
            contract_hash=self._contract.content_hash,
            run_id=submission["run_id"], backend_id=submission["backend_id"],
            terminal=tuple(terminal_obs), artifacts=tuple(artifacts_obs),
            diagnostics=tuple(diagnostics))

    def _observe(self, source: str, artifact_id: str, path: str,
                 snapshots: _PathSnapshotCache) -> ArtifactObservation:
        claimed = os.path.normpath(os.path.expanduser(path))
        # Patch 3 B2：observation 与 criterion 共用同一 canonical-path 快照
        # 缓存——同一路径只捕获（打开）一次；快照内已含预筛（missing-最近
        # 现存祖先逃逸分类，不读取内容）与句柄级 containment 证明（blocker
        # B3：真实安全判断在句柄层）。hash/size/完整内容 MIME/文本全部来自
        # 同一不可变快照。
        snap = snapshots.get(claimed)
        name_mime = mime_for_suffix(snap.final_path or claimed)
        if snap.rejection == "path_escape":
            if not snap.within_workspace:
                # prefilter 逃逸（final_path 是 realpath 预筛值，非句柄目标）
                return ArtifactObservation(source, artifact_id, claimed,
                                           snap.final_path, snap.target_exists,
                                           snap.is_regular_file, False, None, "", "",
                                           "path_escape", name_mime)
            # open 之后句柄目标逃逸（TOCTOU 竞态被句柄证明拦截）——高声拒绝
            return ArtifactObservation(source, artifact_id, claimed, snap.final_path,
                                       True, True, False, None, "", "",
                                       "path_escape", name_mime)
        if snap.rejection == "missing":
            return ArtifactObservation(source, artifact_id, claimed, snap.final_path,
                                       False, False, True, None, "", "",
                                       "missing", name_mime)
        if snap.rejection == "not_regular_file":
            return ArtifactObservation(source, artifact_id, claimed, snap.final_path,
                                       True, False, True, None, "", "",
                                       "not_regular_file", name_mime)
        if snap.rejection:   # unreadable / handle_target_unprovable / oversize / mutated
            return ArtifactObservation(source, artifact_id, claimed, snap.final_path,
                                       True, True, True, snap.size_bytes, "", "",
                                       snap.rejection, name_mime)
        # rejection == "" —— 完整内容快照在手（blocker B1：observed_mime 是
        # 完整内容识别真值；content_rejection 是结构验证拒绝原因）
        return ArtifactObservation(source, artifact_id, claimed, snap.final_path,
                                   True, True, True, snap.size_bytes,
                                   snap.content_mime, snap.sha256_hex, "",
                                   name_mime, snap.content_rejection)

    # -- 检查构建 ----------------------------------------------------------------
    def _run_checks(self, bundle: EvidenceBundle,
                    submission: Dict[str, Any],
                    snapshots: _PathSnapshotCache) -> Tuple[List[VerificationCheck], Set[str]]:
        out: List[VerificationCheck] = []
        substantive_ids: Set[str] = set()

        bound_kinds = tuple(t.kind for t in bundle.terminal if t.bound)
        unbound = sum(1 for t in bundle.terminal if not t.bound)
        out.append(_checks.check_terminal_claim(bound_kinds, unbound))
        out.append(_checks.check_backend_authorized(
            bundle.backend_id, self._contract.allowed_backends))
        for ref in self._contract.verification_standard.verifier_refs:
            out.append(_checks.check_verifier_ref(ref))

        for c in self._contract.verification_standard.criteria:
            substantive_ids.add(f"criterion:{c.criterion_id}")
            out.append(_checks.check_criterion(
                criterion_id=c.criterion_id, kind=c.kind, params=c.params,
                contains_path=self._contains_path,
                workspace_root=self._workspace_root(),
                process_timeout_seconds=self._process_timeout,
                snapshot_cache=snapshots))

        declared_by_id = {d["artifact_id"]: d for d in submission["declared"]}
        obs_exp = {o.artifact_id: o for o in bundle.artifacts if o.source == "expectation"}
        obs_dec = {o.artifact_id: o for o in bundle.artifacts if o.source == "declared"}

        for exp in self._contract.artifact_expectations:
            exp_checks = self._expectation_checks(
                exp, obs_exp.get(exp.artifact_id), declared_by_id.get(exp.artifact_id))
            out.extend(exp_checks)
            if exp.required:
                # required artifact 的真实本地检查是 substantive 成功证据的
                # 两大来源之一（blocker 1）；optional artifact 的检查只是
                # fail-closed 防线，绝不充当成功证据。
                substantive_ids.update(c.check_id for c in exp_checks)
        for d in submission["declared"]:
            out.extend(self._declared_checks(d, obs_dec.get(d["artifact_id"])))
        expectations_by_id = {e.artifact_id: e for e in self._contract.artifact_expectations}
        for d in submission["declared"]:
            aid = d["artifact_id"]
            exp = expectations_by_id.get(aid)
            if exp is None:
                continue
            if os.path.normcase(os.path.normpath(os.path.expanduser(d["path"]))) \
                    != os.path.normcase(exp.expected_path):
                out.append(VerificationCheck(
                    check_id=f"artifact_expectation:{aid}:location",
                    kind="artifact_location", required=True,
                    result=CheckResult.FAIL,
                    explanation="declared_path_differs_from_expected",
                    inputs=(("expected", exp.expected_path), ("declared", d["path"]))))
        return out, substantive_ids

    def _expectation_checks(self, exp, obs: Optional[ArtifactObservation],
                            decl: Optional[Mapping[str, Any]]) -> List[VerificationCheck]:
        aid = exp.artifact_id
        prefix = f"artifact_expectation:{aid}"
        atype_allowed = ARTIFACT_TYPE_CONTENT_RULES.get(exp.artifact_type)
        if atype_allowed is None:
            # blocker 2：未知 artifact_type 绝不静默通过（16F 封闭类型表）。
            return [VerificationCheck(
                check_id=f"{prefix}:artifact_type", kind="artifact_type",
                required=True, result=CheckResult.FAIL,
                explanation=f"unknown_artifact_type:{exp.artifact_type[:64]}")]
        if obs is None:   # 结构上不可达（expectation 必产生观察）——防御性兜底
            if exp.required:
                return [VerificationCheck(
                    check_id=f"{prefix}:present", kind="artifact_present",
                    required=True, result=CheckResult.FAIL,
                    explanation="required_artifact_missing")]
            return []
        if not obs.within_workspace:
            # 逃逸（blocker 3）：optional 也一样——path/symlink/junction 逃逸
            # 一律 required FAIL（containment 先于存在性，绝不降级 missing）。
            return [VerificationCheck(
                check_id=f"{prefix}:containment", kind="artifact_containment",
                required=True, result=CheckResult.FAIL,
                explanation="path_escape")]
        if not obs.target_exists:
            if exp.required:
                return [VerificationCheck(
                    check_id=f"{prefix}:present", kind="artifact_present",
                    required=True, result=CheckResult.FAIL,
                    explanation="required_artifact_missing")]
            return []          # optional 真正不存在 → 唯一豁免（允许通过）
        # blocker 3：optional 一旦存在，任何问题都按 required 处理——
        # escape/oversize/unsupported MIME/non-regular/声明矛盾任一 → FAIL。
        req = True
        out = [
            VerificationCheck(
                check_id=f"{prefix}:containment", kind="artifact_containment",
                required=req, result=CheckResult.PASS,
                explanation="within_workspace_write_roots"),
            VerificationCheck(
                check_id=f"{prefix}:present", kind="artifact_present",
                required=req,
                result=CheckResult.PASS if obs.is_regular_file else CheckResult.FAIL,
                explanation="artifact_observed" if obs.is_regular_file else "not_regular_file"),
        ]
        if obs.rejection == "mutated":
            out.append(VerificationCheck(
                check_id=f"{prefix}:stability", kind="artifact_stability",
                required=req, result=CheckResult.FAIL,
                explanation="artifact_mutated_during_verification"))
            return out
        if not (obs.is_regular_file and obs.within_workspace):
            return out
        d_sha = decl["declared_sha256"] if decl else None
        d_mime = decl["declared_mime"] if decl else None
        d_size = decl["declared_size_bytes"] if decl else None
        # blocker B1：unreadable / 句柄目标不可证明 绝不跳过为"剩余检查通过"——
        # required FAIL，最终不得 VERIFIED。
        if obs.rejection in ("unreadable", "handle_target_unprovable"):
            out.append(VerificationCheck(
                check_id=f"{prefix}:readable", kind="artifact_readable",
                required=req, result=CheckResult.FAIL,
                explanation=("artifact_unreadable" if obs.rejection == "unreadable"
                             else "handle_target_unprovable")))
            return out
        if obs.rejection == "oversize":
            out.append(VerificationCheck(
                check_id=f"{prefix}:size", kind="artifact_size", required=req,
                result=CheckResult.FAIL, explanation="artifact_oversize"))
            if d_sha is not None:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:hash", kind="artifact_hash", required=req,
                    result=CheckResult.NOT_EVALUABLE,
                    explanation="hash_unavailable:oversize"))
            return out
        # blocker B1：空文件绝不是有效 artifact（含 binary_blob）。
        if obs.size_bytes == 0 or obs.content_rejection == "empty_artifact":
            out.append(VerificationCheck(
                check_id=f"{prefix}:content", kind="artifact_content",
                required=req, result=CheckResult.FAIL,
                explanation="artifact_empty"))
            return out
        if d_size is not None:
            if obs.size_bytes is None:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=req,
                    result=CheckResult.FAIL, explanation="artifact_oversize"))
            elif obs.size_bytes != d_size:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=req,
                    result=CheckResult.FAIL, explanation="declared_size_mismatch",
                    inputs=(("declared", str(d_size)), ("observed", str(obs.size_bytes)))))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=req,
                    result=CheckResult.PASS, explanation="size_observed",
                    inputs=(("observed", str(obs.size_bytes)),)))
        # blocker B1：完整内容结构验证失败（malformed/截断/畸形）→ required
        # FAIL，绝不 VERIFIED（与声明 hash 是否一致无关）。
        if obs.content_rejection:
            out.append(VerificationCheck(
                check_id=f"{prefix}:content", kind="artifact_content",
                required=req, result=CheckResult.FAIL,
                explanation=obs.content_rejection))
            return out
        if obs.observed_mime:
            out.extend(self._content_channel_checks(
                prefix, req, obs, artifact_type=exp.artifact_type, d_mime=d_mime))
        elif d_mime is not None:
            # 内容不可观察时的声明 MIME 无法被内容佐证
            if d_mime not in SUPPORTED_MIME_TYPES:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:mime", kind="artifact_mime", required=req,
                    result=CheckResult.FAIL, explanation="unsupported_mime",
                    inputs=(("declared", d_mime),)))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:mime", kind="artifact_mime", required=req,
                    result=CheckResult.FAIL, explanation="mime_unobservable",
                    inputs=(("declared", d_mime),)))
        if d_sha is not None:
            if not obs.observed_sha256:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:hash", kind="artifact_hash", required=req,
                    result=CheckResult.NOT_EVALUABLE,
                    explanation=f"hash_unavailable:{obs.rejection or 'unknown'}"))
            elif obs.observed_sha256 != d_sha:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:hash", kind="artifact_hash", required=req,
                    result=CheckResult.FAIL,
                    explanation="declared_hash_mismatch_artifact_tampered"))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:hash", kind="artifact_hash", required=req,
                    result=CheckResult.PASS, explanation="declared_hash_corroborated"))
        return out

    def _declared_checks(self, d: Mapping[str, Any],
                         obs: Optional[ArtifactObservation]) -> List[VerificationCheck]:
        aid = d["artifact_id"]
        prefix = f"declared_artifact:{aid}"
        if obs is None:   # 结构上不可达——防御性兜底
            return [VerificationCheck(
                check_id=f"{prefix}:present", kind="declared_present", required=True,
                result=CheckResult.FAIL, explanation="declared_artifact_missing")]
        if not obs.within_workspace:
            return [VerificationCheck(
                check_id=f"{prefix}:containment", kind="artifact_containment",
                required=True, result=CheckResult.FAIL,
                explanation="path_escape")]
        if not obs.target_exists:
            return [VerificationCheck(
                check_id=f"{prefix}:present", kind="declared_present", required=True,
                result=CheckResult.FAIL, explanation="declared_artifact_missing")]
        out = [
            VerificationCheck(
                check_id=f"{prefix}:containment", kind="artifact_containment",
                required=True, result=CheckResult.PASS,
                explanation="within_workspace_write_roots"),
            VerificationCheck(
                check_id=f"{prefix}:present", kind="declared_present", required=True,
                result=CheckResult.PASS if obs.is_regular_file else CheckResult.FAIL,
                explanation="declared_artifact_observed" if obs.is_regular_file
                else "not_regular_file"),
        ]
        if obs.rejection == "mutated":
            out.append(VerificationCheck(
                check_id=f"{prefix}:stability", kind="artifact_stability",
                required=True, result=CheckResult.FAIL,
                explanation="artifact_mutated_during_verification"))
            return out
        if not (obs.is_regular_file and obs.within_workspace):
            return out
        d_sha = d["declared_sha256"]
        d_mime = d["declared_mime"]
        d_size = d["declared_size_bytes"]
        # blocker B1：unreadable / 句柄目标不可证明 → required FAIL
        if obs.rejection in ("unreadable", "handle_target_unprovable"):
            out.append(VerificationCheck(
                check_id=f"{prefix}:readable", kind="artifact_readable",
                required=True, result=CheckResult.FAIL,
                explanation=("artifact_unreadable" if obs.rejection == "unreadable"
                             else "handle_target_unprovable")))
            return out
        if obs.rejection == "oversize":
            out.append(VerificationCheck(
                check_id=f"{prefix}:size", kind="artifact_size", required=True,
                result=CheckResult.FAIL, explanation="artifact_oversize"))
            if d_sha is not None:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:hash", kind="artifact_hash", required=True,
                    result=CheckResult.NOT_EVALUABLE,
                    explanation="hash_unavailable:oversize"))
            return out
        # blocker B1：空文件绝不是有效 artifact。
        if obs.size_bytes == 0 or obs.content_rejection == "empty_artifact":
            out.append(VerificationCheck(
                check_id=f"{prefix}:content", kind="artifact_content",
                required=True, result=CheckResult.FAIL,
                explanation="artifact_empty"))
            return out
        if d_size is not None:
            if obs.size_bytes is None:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=True,
                    result=CheckResult.FAIL, explanation="artifact_oversize"))
            elif obs.size_bytes != d_size:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=True,
                    result=CheckResult.FAIL, explanation="declared_size_mismatch",
                    inputs=(("declared", str(d_size)), ("observed", str(obs.size_bytes)))))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=True,
                    result=CheckResult.PASS, explanation="size_observed",
                    inputs=(("observed", str(obs.size_bytes)),)))
        if obs.content_rejection:
            out.append(VerificationCheck(
                check_id=f"{prefix}:content", kind="artifact_content",
                required=True, result=CheckResult.FAIL,
                explanation=obs.content_rejection))
            return out
        if obs.observed_mime:
            out.extend(self._content_channel_checks(
                prefix, True, obs, artifact_type=None, d_mime=d_mime))
        elif d_mime is not None:
            if d_mime not in SUPPORTED_MIME_TYPES:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:mime", kind="artifact_mime", required=True,
                    result=CheckResult.FAIL, explanation="unsupported_mime",
                    inputs=(("declared", d_mime),)))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:mime", kind="artifact_mime", required=True,
                    result=CheckResult.FAIL, explanation="mime_unobservable",
                    inputs=(("declared", d_mime),)))
        if d_sha is not None:
            if not obs.observed_sha256:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:hash", kind="artifact_hash", required=True,
                    result=CheckResult.NOT_EVALUABLE,
                    explanation=f"hash_unavailable:{obs.rejection or 'unknown'}"))
            elif obs.observed_sha256 != d_sha:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:hash", kind="artifact_hash", required=True,
                    result=CheckResult.FAIL,
                    explanation="declared_hash_mismatch_artifact_tampered"))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:hash", kind="artifact_hash", required=True,
                    result=CheckResult.PASS, explanation="declared_hash_corroborated"))
        return out

    def _content_channel_checks(self, prefix: str, req: bool, obs: ArtifactObservation,
                                *, artifact_type: Optional[str],
                                d_mime: Optional[str]) -> List[VerificationCheck]:
        """blocker 2 的内容通道检查（present 且内容可观察时执行）：

        - 命名通道：后缀必须是已知后缀，且命名 MIME 与内容一致（后缀不是
          真实 MIME，只是交叉核对——未知后缀/矛盾一律 FAIL）；
        - artifact_type 通道（expectation 侧）：内容 MIME 必须命中封闭
          ``ARTIFACT_TYPE_CONTENT_RULES`` 允许集（未知类型早已 fail-closed）；
        - binary 通道（declared 侧）：binary/octet-stream 内容只能被显式
          ``declared_mime=application/octet-stream`` 接受；
        - 声明 MIME：白名单 + 与内容一致（exact + 文本族窄例外）。
        """
        out: List[VerificationCheck] = []
        if not obs.name_mime:
            out.append(VerificationCheck(
                check_id=f"{prefix}:mime", kind="artifact_mime", required=req,
                result=CheckResult.FAIL, explanation="unknown_artifact_suffix",
                inputs=(("observed", obs.observed_mime),)))
        elif not declared_mime_consistent(obs.name_mime, obs.observed_mime):
            out.append(VerificationCheck(
                check_id=f"{prefix}:mime", kind="artifact_mime", required=req,
                result=CheckResult.FAIL, explanation="suffix_mime_mismatch",
                inputs=(("name", obs.name_mime), ("observed", obs.observed_mime))))
        else:
            out.append(VerificationCheck(
                check_id=f"{prefix}:mime", kind="artifact_mime", required=req,
                result=CheckResult.PASS, explanation="name_mime_consistent",
                inputs=(("name", obs.name_mime), ("observed", obs.observed_mime))))
        if artifact_type is not None:
            atype_allowed = ARTIFACT_TYPE_CONTENT_RULES[artifact_type]
            if obs.observed_mime not in atype_allowed:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:artifact_type", kind="artifact_type",
                    required=req, result=CheckResult.FAIL,
                    explanation="artifact_type_mime_mismatch",
                    inputs=(("artifact_type", artifact_type),
                            ("observed", obs.observed_mime))))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:artifact_type", kind="artifact_type",
                    required=req, result=CheckResult.PASS,
                    explanation="artifact_type_consistent"))
        else:
            # declared 侧：binary 内容必须被显式 octet-stream 声明接受
            if obs.observed_mime == "application/octet-stream" \
                    and d_mime != "application/octet-stream":
                out.append(VerificationCheck(
                    check_id=f"{prefix}:mime", kind="artifact_mime", required=req,
                    result=CheckResult.FAIL,
                    explanation="binary_content_requires_explicit_type",
                    inputs=(("observed", obs.observed_mime),)))
        if d_mime is not None:
            if d_mime not in SUPPORTED_MIME_TYPES:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:declared_mime", kind="artifact_mime",
                    required=req, result=CheckResult.FAIL,
                    explanation="unsupported_mime",
                    inputs=(("declared", d_mime),)))
            elif not declared_mime_consistent(d_mime, obs.observed_mime):
                out.append(VerificationCheck(
                    check_id=f"{prefix}:declared_mime", kind="artifact_mime",
                    required=req, result=CheckResult.FAIL,
                    explanation="declared_mime_mismatch",
                    inputs=(("declared", d_mime), ("observed", obs.observed_mime))))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:declared_mime", kind="artifact_mime",
                    required=req, result=CheckResult.PASS,
                    explanation="mime_observed",
                    inputs=(("declared", d_mime), ("observed", obs.observed_mime))))
        return out

    # -- 聚合 / 诊断 --------------------------------------------------------------
    @staticmethod
    def _aggregate(checks: List[VerificationCheck]) -> VerificationVerdict:
        required = [c for c in checks if c.required]
        if any(c.result is CheckResult.FAIL for c in required):
            return VerificationVerdict.FAILED
        if any(c.result is CheckResult.NOT_EVALUABLE for c in required):
            return VerificationVerdict.INCONCLUSIVE
        return VerificationVerdict.VERIFIED

    @staticmethod
    def _diagnostics(bundle: EvidenceBundle,
                     checks: List[VerificationCheck]) -> Tuple[str, ...]:
        diags: List[str] = [d for d in bundle.diagnostics]
        for c in checks:
            if c.required and c.result is not CheckResult.PASS:
                diags.append(f"{c.check_id}:{c.result.value}:{c.explanation}")
        if len(diags) > MAX_DIAGNOSTICS:
            diags = diags[:MAX_DIAGNOSTICS]
        return tuple(diags)

    # -- 工具 ----------------------------------------------------------------
    def _contains_path(self, real_path: str, writable: bool) -> bool:
        return self._contract.workspace_scope.contains_path(real_path, writable=writable)

    def _workspace_root(self) -> Optional[str]:
        roots = self._contract.workspace_scope.write_roots
        return roots[0] if roots else None
