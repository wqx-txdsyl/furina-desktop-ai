"""Phase 16F — IndependentVerifier：任务级独立校验器（VERIFIED 唯一授权入口）。

权威模型（16F 任务书 §1/§3 + 关键锁定 1–3）：

- **VERIFIED 只能由本类在真实执行全部确定性检查且全部通过后产生**。任何其它
  代码路径构造 verdict=VERIFIED 的报告要么被 :class:`VerificationAuthorityError`
  拒绝（无 seal / 非 16F 身份），要么携带的 seal 无法通过
  :meth:`seal_is_authentic` 真实性复核（seal 是验证器构造期随机密钥对
  report_digest 的 HMAC-SHA256——与 16D broker 密钥 HMAC 同模式，绝不依赖
  _private / 对象身份 / 调用方自报字段冒充 authority）。
- backend completed / exit 0 / 成功文本 / backend 自报 verified **不是证明**：
  证据提交的 exact-schema 里根本没有这些字段（未知键 fail-closed）；本地
  观察与本地重跑才是真值。
- 每次校验：exact-schema 解析（fail-closed）→ defensive-copy 冻结 → 本地
  证据收集（realpath containment / 有界哈希 / 有界读取）→ 确定性检查
  （契约判据一一对应，本地重跑）→ 聚合 → 报告 + 密封。
- 报告与导出零共享可变引用；秘密不存储/不哈希/不导出（解释文本一律脱敏）。

聚合规则：任一 required 检查 FAIL → FAILED；否则任一 required
NOT_EVALUABLE → INCONCLUSIVE；全部 required PASS → VERIFIED。
INCONCLUSIVE 绝不映射 VERIFIED。

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
from typing import Any, Dict, List, Mapping, Optional, Tuple

from furina.agent.events.models import TERMINAL_KINDS, EventKind
from furina.agent.work_contract import WorkContract, compute_content_hash

from . import checks as _checks
from .models import (
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
    mime_for_suffix,
)

_TERMINAL_KIND_VALUES = frozenset(k.value for k in TERMINAL_KINDS)
_EVENT_KIND_VALUES = frozenset(k.value for k in EventKind)


class IndependentVerifier:
    """绑定单个不可变 WorkContract 的任务级独立校验器。

    构造期生成随机 seal 密钥（仅内存）；``verify(evidence)`` 可重复调用
    （repair loop 每次 attempt 独立评估新证据），每次产出全新不可变报告。
    """

    def __init__(self, contract: WorkContract, *, now_fn=time.time,
                 monotonic_fn=time.monotonic,
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
        self._contract = contract
        self._now_fn = now_fn
        self._monotonic_fn = monotonic_fn
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
        bundle = self._collect_bundle(submission)
        check_list = self._run_checks(bundle, submission)
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
            raise VerificationInputError(f"输入拒绝未知键: {unknown}")
        if missing:
            raise VerificationInputError(f"输入缺失必需键: {missing}")

        run_id = evidence["run_id"]
        if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > MAX_ID_CHARS:
            raise VerificationInputError(f"run_id 必须是非空 str(<=128)，得到 {run_id!r}")
        run_id = run_id.strip()
        import re as _re
        from .models import _RUN_ID_PATTERN
        if not _RUN_ID_PATTERN.match(run_id):
            raise VerificationInputError(f"run_id 词法非法: {run_id!r}")
        backend_id = evidence["backend_id"]
        if not isinstance(backend_id, str) or not backend_id.strip() \
                or len(backend_id) > MAX_ID_CHARS:
            raise VerificationInputError(
                f"backend_id 必须是非空 str(<=128)，得到 {backend_id!r}")

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

        return {"run_id": run_id, "backend_id": backend_id.strip(),
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
                f"未知 {sorted(keys - set(TERMINAL_CLAIM_KEYS))} / "
                f"缺失 {sorted(set(TERMINAL_CLAIM_KEYS) - keys)}")
        event_id = item["event_id"]
        if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > MAX_ID_CHARS:
            raise VerificationInputError(f"event_id 必须是非空 str(<=128)，得到 {event_id!r}")
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
            v = item[name]
            if not isinstance(v, str) or not v.strip() or len(v) > MAX_ID_CHARS:
                raise VerificationInputError(
                    f"terminal claim {name} 必须是非空 str(<=128)，得到 {v!r}")
            out[name] = v
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
                f"未知 {sorted(keys - set(ARTIFACT_CLAIM_KEYS))} / "
                f"缺失 {sorted(set(ARTIFACT_CLAIM_KEYS) - keys)}")
        aid = item["artifact_id"]
        if not isinstance(aid, str) or not aid.strip() or len(aid) > MAX_ID_CHARS:
            raise VerificationInputError(f"artifact_id 必须是非空 str(<=128)，得到 {aid!r}")
        path = item["path"]
        if not isinstance(path, str) or not path.strip() or len(path) > MAX_PATH_CHARS:
            raise VerificationInputError(f"path 必须是非空 str(<=1024)，得到 {path!r}")
        import os as _os
        expanded = _os.path.expanduser(path.strip())
        if not _os.path.isabs(expanded):
            raise VerificationInputError(f"artifact path 必须是绝对路径: {path!r}")
        d_sha = item["declared_sha256"]
        if d_sha is not None and (not isinstance(d_sha, str)
                                  or not _SHA256_PATTERN.match(d_sha)):
            raise VerificationInputError(
                f"declared_sha256 必须是 None 或 64 位小写 hex，得到 {d_sha!r}")
        d_mime = item["declared_mime"]
        if d_mime is not None and (not isinstance(d_mime, str) or not d_mime.strip()
                                   or len(d_mime) > MAX_ID_CHARS):
            raise VerificationInputError(
                f"declared_mime 必须是 None 或非空 str(<=128)，得到 {d_mime!r}")
        d_size = item["declared_size_bytes"]
        if d_size is not None:
            if isinstance(d_size, bool) or not isinstance(d_size, int) or d_size <= 0:
                raise VerificationInputError(
                    "declared_size_bytes 必须是 None 或正 int（bool/float/负数/0 拒绝），"
                    f"得到 {d_size!r}")
        return {"artifact_id": aid.strip(), "path": path.strip(),
                "declared_sha256": d_sha, "declared_mime": d_mime,
                "declared_size_bytes": d_size}

    # -- 本地证据收集（realpath containment + 有界哈希/观察） -----------------------
    def _collect_bundle(self, submission: Dict[str, Any]) -> EvidenceBundle:
        diagnostics: List[str] = []
        terminal_obs: List[TerminalObservation] = []
        bound_kinds: List[str] = []
        for t in submission["terminal"]:
            kind = t["kind"]
            if kind not in _TERMINAL_KIND_VALUES:
                diagnostics.append(f"terminal_claim_non_terminal_ignored:{t['event_id'][:64]}")
                bound = False
            else:
                bound = (t["run_id"] == submission["run_id"]
                         and t["contract_id"] == self._contract.contract_id
                         and t["backend_id"] == submission["backend_id"])
                if bound:
                    bound_kinds.append(kind)
                else:
                    diagnostics.append(f"terminal_claim_unbound:{t['event_id'][:64]}")
            terminal_obs.append(TerminalObservation(
                event_id=t["event_id"], kind=kind,
                observed_at_epoch=t["observed_at_epoch"], bound=bound))

        artifacts_obs: List[ArtifactObservation] = []
        for exp in self._contract.artifact_expectations:
            artifacts_obs.append(
                self._observe("expectation", exp.artifact_id, exp.expected_path))
        for d in submission["declared"]:
            artifacts_obs.append(self._observe("declared", d["artifact_id"], d["path"]))

        return EvidenceBundle(
            contract_id=self._contract.contract_id,
            contract_hash=self._contract.content_hash,
            run_id=submission["run_id"], backend_id=submission["backend_id"],
            terminal=tuple(terminal_obs), artifacts=tuple(artifacts_obs),
            diagnostics=tuple(diagnostics))

    def _observe(self, source: str, artifact_id: str, path: str) -> ArtifactObservation:
        claimed = os.path.normpath(os.path.expanduser(path))
        # realpath 同时覆盖两类逃逸：目标存在时的 symlink 链，与目标尚不存在时
        # 最近现存祖先（含 junction/挂点）的链接逃逸（Python 3.8+ 解析现存前缀）。
        # containment **先于存在性**判定：逃逸路径即使目标不存在也报 path_escape，
        # 绝不降级为 missing（fail-closed 高声拒绝）。
        real = os.path.realpath(claimed)
        within = self._contract.workspace_scope.contains_path(real, writable=True)
        exists = os.path.exists(real)
        if not within:
            is_file = bool(exists) and os.path.isfile(real)
            return ArtifactObservation(source, artifact_id, claimed, real,
                                       exists, is_file, False, None, "", "",
                                       "path_escape")
        if not exists:
            return ArtifactObservation(source, artifact_id, claimed, real,
                                       False, False, True, None, "", "", "missing")
        is_file = os.path.isfile(real)
        if not is_file:
            return ArtifactObservation(source, artifact_id, claimed, real,
                                       True, False, True, None, "", "",
                                       "not_regular_file")
        try:
            size = os.path.getsize(real)
        except OSError:
            return ArtifactObservation(source, artifact_id, claimed, real,
                                       True, True, True, None, "", "", "unreadable")
        if size > MAX_ARTIFACT_BYTES:
            return ArtifactObservation(source, artifact_id, claimed, real,
                                       True, True, True, None, "", "", "oversize")
        digest, rejection = _checks.sha256_file_bounded(real)
        mime = mime_for_suffix(real)
        if rejection:
            return ArtifactObservation(source, artifact_id, claimed, real,
                                       True, True, True, size, mime, "", rejection)
        return ArtifactObservation(source, artifact_id, claimed, real,
                                   True, True, True, size, mime, digest, "")

    # -- 检查构建 ----------------------------------------------------------------
    def _run_checks(self, bundle: EvidenceBundle,
                    submission: Dict[str, Any]) -> List[VerificationCheck]:
        out: List[VerificationCheck] = []

        bound_kinds = tuple(t.kind for t in bundle.terminal if t.bound)
        unbound = sum(1 for t in bundle.terminal if not t.bound)
        out.append(_checks.check_terminal_claim(bound_kinds, unbound))
        out.append(_checks.check_backend_authorized(
            bundle.backend_id, self._contract.allowed_backends))
        for ref in self._contract.verification_standard.verifier_refs:
            out.append(_checks.check_verifier_ref(ref))

        for c in self._contract.verification_standard.criteria:
            out.append(_checks.check_criterion(
                criterion_id=c.criterion_id, kind=c.kind, params=c.params,
                contains_path=self._contains_path,
                workspace_root=self._workspace_root(),
                process_timeout_seconds=self._process_timeout,
                monotonic=self._monotonic_fn))

        declared_by_id = {d["artifact_id"]: d for d in submission["declared"]}
        obs_exp = {o.artifact_id: o for o in bundle.artifacts if o.source == "expectation"}
        obs_dec = {o.artifact_id: o for o in bundle.artifacts if o.source == "declared"}

        for exp in self._contract.artifact_expectations:
            out.extend(self._expectation_checks(
                exp, obs_exp.get(exp.artifact_id), declared_by_id.get(exp.artifact_id)))
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
        return out

    def _expectation_checks(self, exp, obs: Optional[ArtifactObservation],
                            decl: Optional[Mapping[str, Any]]) -> List[VerificationCheck]:
        aid = exp.artifact_id
        required = exp.required
        prefix = f"artifact_expectation:{aid}"
        if obs is None:   # 结构上不可达（expectation 必产生观察）——防御性兜底
            if required:
                return [VerificationCheck(
                    check_id=f"{prefix}:present", kind="artifact_present",
                    required=True, result=CheckResult.FAIL,
                    explanation="required_artifact_missing")]
            return []
        if not obs.target_exists and not obs.within_workspace:
            # 逃逸路径：containment FAIL 已足够响亮；不再产出现存性检查。
            return [VerificationCheck(
                check_id=f"{prefix}:containment", kind="artifact_containment",
                required=required, result=CheckResult.FAIL,
                explanation="path_escape")]
        if not obs.target_exists:
            if required:
                return [VerificationCheck(
                    check_id=f"{prefix}:present", kind="artifact_present",
                    required=True, result=CheckResult.FAIL,
                    explanation="required_artifact_missing")]
            return []
        out = [
            VerificationCheck(
                check_id=f"{prefix}:containment", kind="artifact_containment",
                required=required,
                result=CheckResult.PASS if obs.within_workspace else CheckResult.FAIL,
                explanation="within_workspace_write_roots" if obs.within_workspace
                else "path_escape"),
            VerificationCheck(
                check_id=f"{prefix}:present", kind="artifact_present",
                required=required,
                result=CheckResult.PASS if obs.is_regular_file else CheckResult.FAIL,
                explanation="artifact_observed" if obs.is_regular_file else "not_regular_file"),
        ]
        if not (obs.is_regular_file and obs.within_workspace):
            return out
        d_sha = decl["declared_sha256"] if decl else None
        d_mime = decl["declared_mime"] if decl else None
        d_size = decl["declared_size_bytes"] if decl else None
        if obs.rejection == "oversize" or d_size is not None:
            if obs.rejection == "oversize" or obs.size_bytes is None:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=required,
                    result=CheckResult.FAIL, explanation="artifact_oversize"))
            elif d_size is not None and obs.size_bytes != d_size:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=required,
                    result=CheckResult.FAIL, explanation="declared_size_mismatch",
                    inputs=(("declared", str(d_size)), ("observed", str(obs.size_bytes)))))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=required,
                    result=CheckResult.PASS, explanation="size_observed",
                    inputs=(("observed", str(obs.size_bytes)),)))
        if d_mime is not None:
            if d_mime not in SUPPORTED_MIME_TYPES:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:mime", kind="artifact_mime", required=required,
                    result=CheckResult.FAIL, explanation="unsupported_mime",
                    inputs=(("declared", d_mime),)))
            elif obs.observed_mime != d_mime:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:mime", kind="artifact_mime", required=required,
                    result=CheckResult.FAIL, explanation="declared_mime_mismatch",
                    inputs=(("declared", d_mime), ("observed", obs.observed_mime))))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:mime", kind="artifact_mime", required=required,
                    result=CheckResult.PASS, explanation="mime_observed",
                    inputs=(("observed", obs.observed_mime),)))
        if d_sha is not None:
            if not obs.observed_sha256:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:hash", kind="artifact_hash", required=required,
                    result=CheckResult.NOT_EVALUABLE,
                    explanation=f"hash_unavailable:{obs.rejection or 'unknown'}"))
            elif obs.observed_sha256 != d_sha:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:hash", kind="artifact_hash", required=required,
                    result=CheckResult.FAIL,
                    explanation="declared_hash_mismatch_artifact_tampered"))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:hash", kind="artifact_hash", required=required,
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
        if not obs.target_exists and not obs.within_workspace:
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
                required=True,
                result=CheckResult.PASS if obs.within_workspace else CheckResult.FAIL,
                explanation="within_workspace_write_roots" if obs.within_workspace
                else "path_escape"),
            VerificationCheck(
                check_id=f"{prefix}:present", kind="declared_present", required=True,
                result=CheckResult.PASS if obs.is_regular_file else CheckResult.FAIL,
                explanation="declared_artifact_observed" if obs.is_regular_file
                else "not_regular_file"),
        ]
        if not (obs.is_regular_file and obs.within_workspace):
            return out
        d_sha = d["declared_sha256"]
        d_mime = d["declared_mime"]
        d_size = d["declared_size_bytes"]
        if obs.rejection == "oversize" or d_size is not None:
            if obs.rejection == "oversize" or obs.size_bytes is None:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=True,
                    result=CheckResult.FAIL, explanation="artifact_oversize"))
            elif d_size is not None and obs.size_bytes != d_size:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=True,
                    result=CheckResult.FAIL, explanation="declared_size_mismatch",
                    inputs=(("declared", str(d_size)), ("observed", str(obs.size_bytes)))))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:size", kind="artifact_size", required=True,
                    result=CheckResult.PASS, explanation="size_observed",
                    inputs=(("observed", str(obs.size_bytes)),)))
        if d_mime is not None:
            if d_mime not in SUPPORTED_MIME_TYPES:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:mime", kind="artifact_mime", required=True,
                    result=CheckResult.FAIL, explanation="unsupported_mime",
                    inputs=(("declared", d_mime),)))
            elif obs.observed_mime != d_mime:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:mime", kind="artifact_mime", required=True,
                    result=CheckResult.FAIL, explanation="declared_mime_mismatch",
                    inputs=(("declared", d_mime), ("observed", obs.observed_mime))))
            else:
                out.append(VerificationCheck(
                    check_id=f"{prefix}:mime", kind="artifact_mime", required=True,
                    result=CheckResult.PASS, explanation="mime_observed",
                    inputs=(("observed", obs.observed_mime),)))
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
