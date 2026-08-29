"""Phase 16F — 确定性检查器（deterministic checkers，全部本地真相）。

16F 任务书 §3/§4 + 关键锁定 1/7：

- 所有判据由本模块**在本地独立执行**：文件存在性 / realpath 归属 / 大小 /
  MIME / SHA-256 全部本地观察；``process_exit_zero`` **本地重跑**契约判据
  命令（有界超时 + 有界捕获），backend 自报的 exit code / 测试通过 / 日志
  只是 claim——本模块的输入里根本没有这些字段。
- 判据 kind 与 16A :data:`WorkContract` 的 ``VERIFICATION_CRITERION_KINDS``
  白名单一一对应（process_exit_zero / artifact_file_exists / artifact_sha256 /
  text_contains / regex_matches），**复用契约判据，不另立成功标准，不分叉
  step 级真相**（AgentRuntime._verify 仍是 step 级硬门，任务级 truth 在此）。
- 文本判据有界读取（MAX_TEXT_READ_BYTES 窗口）；哈希有界（MAX_ARTIFACT_BYTES，
  超界即 oversize 拒绝）；进程重跑有界超时且只保留 exit code/超时事实，
  **输出内容零存储**。
- 每个检查器返回 :class:`VerificationCheck`：确定性 check_id、冻结输入、
  PASS/FAIL/NOT_EVALUABLE 与脱敏解释。NOT_EVALUABLE 只用于"无法执行检查"
  （spawn 失败 / 无法读取 / 模式无法编译），绝不表示通过。
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from typing import Callable, Optional, Tuple

from .models import (
    MAX_ARTIFACT_BYTES,
    MAX_TEXT_READ_BYTES,
    PROCESS_CHUNK_BYTES,
    CheckResult,
    VerificationCheck,
    VerificationError,
    mime_for_suffix,
)

__all__ = [
    "sha256_file_bounded",
    "read_text_window",
    "check_terminal_claim",
    "check_backend_authorized",
    "check_verifier_ref",
    "check_criterion",
]

_TERMINAL_KIND_PASS = "backend.completed"
_TERMINAL_KIND_FAIL = frozenset({"backend.failed", "backend.cancelled"})


# ---------------------------------------------------------------------------
# 有界文件原语
# ---------------------------------------------------------------------------

def sha256_file_bounded(path: str) -> Tuple[str, str]:
    """流式 SHA-256；超过 MAX_ARTIFACT_BYTES 返回 ("", "oversize")，IO 失败 ("", "unreadable")。"""
    h = hashlib.sha256()
    total = 0
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(PROCESS_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARTIFACT_BYTES:
                    return "", "oversize"
                h.update(chunk)
    except OSError:
        return "", "unreadable"
    return h.hexdigest(), ""


def read_text_window(path: str) -> Tuple[str, bool, str]:
    """有界读取文本窗口（至多 MAX_TEXT_READ_BYTES）；返回 (text, truncated, rejection)。"""
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_TEXT_READ_BYTES + 1)
    except OSError:
        return "", False, "unreadable"
    truncated = len(data) > MAX_TEXT_READ_BYTES
    return data[:MAX_TEXT_READ_BYTES].decode("utf-8", errors="replace"), truncated, ""


# ---------------------------------------------------------------------------
# 证据结构检查
# ---------------------------------------------------------------------------

def check_terminal_claim(bound_terminal_kinds: Tuple[str, ...],
                         unbound_claim_count: int) -> VerificationCheck:
    """evidence:terminal_claim —— 有绑定终态 claim 才可判定（否则 NOT_EVALUABLE）。

    backend.completed 只是"可以开始独立校验"的 claim（16E：completed →
    BACKEND_DONE_UNVERIFIED，绝不 VERIFIED）；failed/cancelled 的终态 claim
    直接 FAIL；多种终态 claim 并存 → 歧义 NOT_EVALUABLE。
    """
    kinds = sorted(set(bound_terminal_kinds))
    if not kinds:
        expl = "no_bound_terminal_claim"
        if unbound_claim_count:
            expl += f"（{unbound_claim_count} 条 claim 未绑定到本 run/contract/backend）"
        return VerificationCheck(
            check_id="evidence:terminal_claim", kind="evidence_terminal_claim",
            required=True, result=CheckResult.NOT_EVALUABLE, explanation=expl)
    if len(kinds) > 1:
        return VerificationCheck(
            check_id="evidence:terminal_claim", kind="evidence_terminal_claim",
            required=True, result=CheckResult.NOT_EVALUABLE,
            explanation="ambiguous_terminal_claims:" + "|".join(kinds))
    kind = kinds[0]
    if kind == _TERMINAL_KIND_PASS:
        return VerificationCheck(
            check_id="evidence:terminal_claim", kind="evidence_terminal_claim",
            required=True, result=CheckResult.PASS,
            explanation="backend_completed_claim_bound（claim 仅授权开始独立校验，"
                        "不构成证明）")
    if kind in _TERMINAL_KIND_FAIL:
        return VerificationCheck(
            check_id="evidence:terminal_claim", kind="evidence_terminal_claim",
            required=True, result=CheckResult.FAIL,
            explanation=f"backend_terminal_claim_{kind}")
    return VerificationCheck(
        check_id="evidence:terminal_claim", kind="evidence_terminal_claim",
        required=True, result=CheckResult.NOT_EVALUABLE,
        explanation=f"unsupported_terminal_claim:{kind}")


def check_backend_authorized(backend_id: str, allowed_backends: Tuple[str, ...],
                             *, check_id: str = "evidence:backend_authorized") -> VerificationCheck:
    """evidence:backend_authorized —— 证据必须可归属于契约允许的 backend。"""
    if backend_id in set(allowed_backends):
        return VerificationCheck(
            check_id=check_id, kind="backend_authorized", required=True,
            result=CheckResult.PASS, explanation="backend_in_contract_allowlist")
    return VerificationCheck(
        check_id=check_id, kind="backend_authorized", required=True,
        result=CheckResult.NOT_EVALUABLE,
        explanation=f"backend_not_allowed:{backend_id[:64]}")


def check_verifier_ref(ref: str) -> VerificationCheck:
    """verifier_ref —— 16F 只实现自身 verifier ref；未知引用 fail-closed。"""
    from .models import VERIFIER_ID
    ok = ref == VERIFIER_ID
    return VerificationCheck(
        check_id=f"evidence:verifier_ref:{ref[:64]}", kind="verifier_ref",
        required=True,
        result=CheckResult.PASS if ok else CheckResult.NOT_EVALUABLE,
        explanation="supported_verifier_ref" if ok else f"unsupported_verifier_ref:{ref[:64]}")


# ---------------------------------------------------------------------------
# 契约判据检查器（16A VERIFICATION_CRITERION_KINDS 一一对应）
# ---------------------------------------------------------------------------

def check_criterion(*, criterion_id: str, kind: str, params: Tuple[Tuple[str, str], ...],
                    contains_path: Callable[[str, bool], bool],
                    workspace_root: Optional[str],
                    process_timeout_seconds: float,
                    monotonic: Callable[[], float]) -> VerificationCheck:
    """按判据 kind 分派到确定性本地检查；check_id = ``criterion:<criterion_id>``。"""
    check = VerificationCheck(
        check_id=f"criterion:{criterion_id}", kind=kind, required=True,
        result=CheckResult.NOT_EVALUABLE, explanation="pending")
    p = dict(params)

    def _resolved(path: str) -> Tuple[str, bool]:
        real = os.path.realpath(os.path.expanduser(path))
        return real, contains_path(real, False)   # 判据 path 允许 read∪write

    if kind == "process_exit_zero":
        command = p.get("command", "")
        inputs = (("command", command), ("timeout_seconds", repr(process_timeout_seconds)))
        return _check_process_exit_zero(check, command, workspace_root,
                                        process_timeout_seconds, monotonic, inputs)

    if kind in ("artifact_file_exists", "artifact_sha256", "text_contains", "regex_matches"):
        path = p.get("path", "")
        real, within = _resolved(path)
        inputs = (("path", path),)
        if not within:
            return _with(check, CheckResult.FAIL, f"path_escape:{real[:256]}", inputs)
        if kind == "artifact_file_exists":
            if os.path.isfile(real):
                return _with(check, CheckResult.PASS, "file_exists", inputs)
            return _with(check, CheckResult.FAIL, "file_missing", inputs)

        if not os.path.isfile(real):
            return _with(check, CheckResult.FAIL, "file_missing", inputs)

        if kind == "artifact_sha256":
            expected = p.get("sha256_hex", "")
            digest, rejection = sha256_file_bounded(real)
            inputs = inputs + (("sha256_hex", expected),)
            if rejection == "oversize":
                return _with(check, CheckResult.FAIL, "artifact_oversize", inputs)
            if rejection == "unreadable":
                return _with(check, CheckResult.NOT_EVALUABLE, "unreadable", inputs)
            if digest == expected:
                return _with(check, CheckResult.PASS, "sha256_match", inputs)
            return _with(check, CheckResult.FAIL, "sha256_mismatch", inputs)

        text, truncated, rejection = read_text_window(real)
        if rejection == "unreadable":
            return _with(check, CheckResult.NOT_EVALUABLE, "unreadable", inputs)
        if kind == "text_contains":
            needle = p.get("needle", "")
            inputs = inputs + (("needle", needle),)
            if needle in text:
                return _with(check, CheckResult.PASS,
                             f"needle_found offsets>0 window_truncated={truncated}", inputs)
            return _with(check, CheckResult.FAIL,
                         f"needle_not_found window_truncated={truncated}", inputs)
        # regex_matches
        pattern = p.get("pattern", "")
        inputs = inputs + (("pattern", pattern),)
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return _with(check, CheckResult.NOT_EVALUABLE,
                         f"invalid_pattern:{type(exc).__name__}", inputs)
        if rx.search(text):
            return _with(check, CheckResult.PASS,
                         f"regex_matched window_truncated={truncated}", inputs)
        return _with(check, CheckResult.FAIL,
                     f"regex_not_matched window_truncated={truncated}", inputs)

    raise VerificationError(f"未知判据 kind（契约层应已拒绝）: {kind}")


def _with(check: VerificationCheck, result: CheckResult, explanation: str,
          inputs: Tuple[Tuple[str, str], ...]) -> VerificationCheck:
    return VerificationCheck(
        check_id=check.check_id, kind=check.kind, required=check.required,
        result=result, explanation=explanation, inputs=inputs)


def _check_process_exit_zero(check: VerificationCheck, command: str,
                             workspace_root: Optional[str], timeout_seconds: float,
                             monotonic: Callable[[], float],
                             inputs: Tuple[Tuple[str, str], ...]) -> VerificationCheck:
    """本地重跑契约判据命令（有界超时；输出内容零存储，只保留 exit code 事实）。"""
    if not command:
        return _with(check, CheckResult.NOT_EVALUABLE, "empty_command", inputs)
    if not workspace_root or not os.path.isdir(workspace_root):
        return _with(check, CheckResult.NOT_EVALUABLE, "workspace_root_missing", inputs)
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=workspace_root,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (OSError, ValueError) as exc:
        return _with(check, CheckResult.NOT_EVALUABLE,
                     f"spawn_error:{type(exc).__name__}", inputs)
    timed_out = False
    try:
        proc.communicate(timeout=timeout_seconds)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        try:
            proc.communicate(timeout=5)
        except Exception:   # pragma: no cover —— kill 后收尾失败不影响事实
            pass
        rc = None
    if timed_out:
        return _with(check, CheckResult.FAIL, "process_timeout", inputs)
    if rc == 0:
        return _with(check, CheckResult.PASS, "exit_zero", inputs)
    return _with(check, CheckResult.FAIL, f"exit_code:{rc}", inputs)
