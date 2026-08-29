"""Phase 16F — Furina-owned 任务级独立验证与有界修复（independent verification）。

公开面（16F 任务书 §3）：

- :class:`IndependentVerifier` —— **VERIFIED 唯一授权入口**：绑定不可变
  WorkContract，对 exact-schema 证据提交做独立评估（本地哈希/realpath
  containment/有界读取/契约判据本地重跑），产出密封的
  :class:`VerificationReport`。
- :class:`EvidenceBundle` / :class:`VerificationCheck` —— 有界不可变证据与
  确定性检查记录。
- :class:`BoundedRepairLoop` —— 同一不可变契约上的严格有界修复循环
  （新 attempt/run id、attempts/time/cost 精确停止、重复失败断路、
  cancellation/approval denial 立停）。

边界：不写 C6/C7/C3（16G）、不做 durable recovery（16H）、不改 C1–C7
schema/writer、不改 16A/16B/16D/16E/16C frozen contracts。backend 自报
completed/exit 0/成功文本/verified 一律不是证明（16E：completed →
BACKEND_DONE_UNVERIFIED；本地独立验证才是真值）。
"""
from .checks import (
    observe_file,
    open_contained,
    process_containment_guaranteed,
    read_text_window,
    read_text_window_contained,
    regex_match_bounded,
    run_process_bounded,
    sha256_file_bounded,
    snapshot_file_contained,
)
from .models import (
    ARTIFACT_CLAIM_KEYS,
    ARTIFACT_TYPE_CONTENT_RULES,
    MAX_ARTIFACT_BYTES,
    MAX_DECLARED_ARTIFACTS,
    MAX_DIAGNOSTICS,
    MAX_EVIDENCE_EVENTS,
    MAX_EXPLANATION_CHARS,
    MAX_REPORT_CHECKS,
    MAX_REPORT_JSON_BYTES,
    MIME_SNIFF_WINDOW,
    SUPPORTED_MIME_TYPES,
    TERMINAL_CLAIM_KEYS,
    VERIFICATION_INPUT_KEYS,
    VERIFIER_ID,
    ArtifactObservation,
    CheckResult,
    EvidenceBundle,
    TerminalObservation,
    VerificationAuthorityError,
    VerificationCheck,
    VerificationError,
    VerificationInputError,
    VerificationReport,
    VerificationVerdict,
    compute_report_digest,
    declared_mime_consistent,
    full_content_verdict,
    sniff_content_mime,
    scrub_secrets,
    validate_identity,
)
from .repair import (
    AttemptRecord,
    BoundedRepairLoop,
    HardBackendFailure,
    RepairOutcome,
    RepairStopReason,
)
from .verifier import IndependentVerifier

__all__ = [
    "ARTIFACT_CLAIM_KEYS",
    "ARTIFACT_TYPE_CONTENT_RULES",
    "AttemptRecord",
    "BoundedRepairLoop",
    "CheckResult",
    "EvidenceBundle",
    "HardBackendFailure",
    "IndependentVerifier",
    "MAX_ARTIFACT_BYTES",
    "MAX_DECLARED_ARTIFACTS",
    "MAX_DIAGNOSTICS",
    "MAX_EVIDENCE_EVENTS",
    "MAX_EXPLANATION_CHARS",
    "MAX_REPORT_CHECKS",
    "MAX_REPORT_JSON_BYTES",
    "MIME_SNIFF_WINDOW",
    "RepairOutcome",
    "RepairStopReason",
    "SUPPORTED_MIME_TYPES",
    "TERMINAL_CLAIM_KEYS",
    "TerminalObservation",
    "VERIFICATION_INPUT_KEYS",
    "VERIFIER_ID",
    "VerificationAuthorityError",
    "VerificationCheck",
    "VerificationError",
    "VerificationInputError",
    "VerificationReport",
    "VerificationVerdict",
    "compute_report_digest",
    "declared_mime_consistent",
    "full_content_verdict",
    "observe_file",
    "open_contained",
    "process_containment_guaranteed",
    "read_text_window",
    "read_text_window_contained",
    "regex_match_bounded",
    "run_process_bounded",
    "sniff_content_mime",
    "scrub_secrets",
    "sha256_file_bounded",
    "snapshot_file_contained",
    "validate_identity",
]
