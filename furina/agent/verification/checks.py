"""Phase 16F — 确定性检查器（deterministic checkers，全部本地真相）。

16F 任务书 §3/§4 + 关键锁定 1/7 + Reviewer Patch 1（blocker 1/5/7）：

- 所有判据由本模块**在本地独立执行**：文件存在性 / realpath 归属 / 大小 /
  MIME / SHA-256 全部本地观察；``process_exit_zero`` **本地重跑**契约判据
  命令（有界超时），backend 自报的 exit code / 测试通过 / 日志只是 claim——
  本模块的输入里根本没有这些字段。
- **稳定产物快照（blocker 7）**：size/hash/MIME 判据来自同一打开文件句柄的
  单次有界读取，句柄前后 ``fstat`` 一致且 close 后 ``stat(path)`` 一致——
  设备/inode/大小/mtime_ns 任一漂移即 ``mutated``（artifact 在验证期间被
  替换/截断/增长）→ FAIL，绝不 VERIFIED。
- **进程输出真正有界（blocker 5）**：stdout/stderr/stdin 一律 DEVNULL——
  输出内容零读取、零聚合、零存储；禁止 PIPE + communicate 无界聚合；
  超时后可靠终止整棵进程树（Windows taskkill /T，POSIX 进程组）。
- **substantive gate（blocker 1）**：terminal claim / backend allowlist /
  verifier_ref 全 PASS 不构成成功证据——:func:`check_no_substantive` 在缺
  乏真实 substantive deterministic check 时强制 NOT_EVALUABLE → INCONCLUSIVE。
- 判据 kind 与 16A :data:`WorkContract` 的 ``VERIFICATION_CRITERION_KINDS``
  白名单一一对应，复用契约判据，不另立成功标准。
- 文本判据有界读取（MAX_TEXT_READ_BYTES 窗口）且同样受 MAX_ARTIFACT_BYTES
  硬上限约束——criterion-only 文件不允许 100 MB 大文件靠前 1 MiB 命中
  needle 而 PASS；哈希有界（超界即 oversize 拒绝）。
- 每个检查器返回 :class:`VerificationCheck`：确定性 check_id、冻结输入、
  PASS/FAIL/NOT_EVALUABLE 与脱敏解释。NOT_EVALUABLE 只用于"无法执行检查"
  （spawn 失败 / 无法读取 / 模式无法编译），绝不表示通过。
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from typing import Any, Callable, Optional, Tuple

from .models import (
    MAX_ARTIFACT_BYTES,
    MAX_TEXT_READ_BYTES,
    MIME_SNIFF_WINDOW,
    PROCESS_CHUNK_BYTES,
    CheckResult,
    VerificationCheck,
    VerificationError,
)

__all__ = [
    "observe_file",
    "sha256_file_bounded",
    "read_text_window",
    "run_process_bounded",
    "check_terminal_claim",
    "check_backend_authorized",
    "check_verifier_ref",
    "check_no_substantive",
    "check_criterion",
]

_TERMINAL_KIND_PASS = "backend.completed"
_TERMINAL_KIND_FAIL = frozenset({"backend.failed", "backend.cancelled"})


# ---------------------------------------------------------------------------
# 稳定产物快照（单句柄有界观察 + 前后一致性证明）
# ---------------------------------------------------------------------------

def _stat_id(st: os.stat_result) -> Tuple[Any, ...]:
    """快照一致性身份：device / inode / size / mtime_ns。"""
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def observe_file(path: str) -> Tuple[int, str, bytes, str]:
    """单句柄有界观察快照：返回 ``(size, sha256_hex, head_bytes, rejection)``。

    - 流式 SHA-256 带 ``MAX_ARTIFACT_BYTES`` 硬界（超界 oversize，零哈希零存储）；
    - ``head``（前 MIME_SNIFF_WINDOW 字节）供有界 MIME 内容识别；
    - **一致性证明**：同一句柄前后 ``fstat`` 一致，且 close 后 ``stat(path)``
      与最后 ``fstat`` 一致——任一漂移即验证期间文件被替换/截断/增长
      （rejection=``"mutated"``）→ artifact_mutated_during_verification FAIL。
    rejection ∈ {"", "unreadable", "oversize", "mutated"}。
    """
    try:
        with open(path, "rb") as f:
            st0 = os.fstat(f.fileno())
            head = f.read(MIME_SNIFF_WINDOW)
            h = hashlib.sha256()
            total = 0
            chunk = head
            while chunk:
                total += len(chunk)
                if total > MAX_ARTIFACT_BYTES:
                    break
                h.update(chunk)
                chunk = f.read(PROCESS_CHUNK_BYTES)
            st1 = os.fstat(f.fileno())
    except OSError:
        return 0, "", b"", "unreadable"
    if total > MAX_ARTIFACT_BYTES:
        return int(st0.st_size), "", head, "oversize"
    if _stat_id(st0) != _stat_id(st1):
        return int(st0.st_size), "", head, "mutated"
    try:
        st2 = os.stat(path)
    except OSError:
        return int(st0.st_size), "", head, "mutated"
    if _stat_id(st1) != _stat_id(st2):
        return int(st0.st_size), "", head, "mutated"
    return int(st0.st_size), h.hexdigest(), head, ""


def sha256_file_bounded(path: str) -> Tuple[str, str]:
    """流式 SHA-256 快照哈希；超过 MAX_ARTIFACT_BYTES / 验证期间变异 /
    IO 失败返回 ("", rejection)。"""
    _size, digest, _head, rejection = observe_file(path)
    return digest, rejection


def read_text_window(path: str) -> Tuple[str, bool, str]:
    """有界读取文本窗口（至多 MAX_TEXT_READ_BYTES），返回 (text, truncated, rejection)。

    同样来自稳定快照：fstat 大小先受 MAX_ARTIFACT_BYTES 硬上限（criterion-only
    文件不允许 100 MB 大文件靠窗口命中而 PASS）；句柄前后 fstat/stat 一致性
    证明同 :func:`observe_file`。rejection ∈ {"", "unreadable", "oversize", "mutated"}。
    """
    try:
        with open(path, "rb") as f:
            st0 = os.fstat(f.fileno())
            if st0.st_size > MAX_ARTIFACT_BYTES:
                return "", False, "oversize"
            data = f.read(MAX_TEXT_READ_BYTES + 1)
            st1 = os.fstat(f.fileno())
    except OSError:
        return "", False, "unreadable"
    try:
        st2 = os.stat(path)
    except OSError:
        return "", False, "mutated"
    if _stat_id(st0) != _stat_id(st1) or _stat_id(st1) != _stat_id(st2):
        return "", False, "mutated"
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
    """verifier_ref —— 16F 只实现自身 verifier ref；未知引用 fail-closed。

    ref 只表示"选择/支持哪个 verifier"，**绝不构成成功证据**（blocker 1：
    substantive gate 单独强制）。
    """
    from .models import VERIFIER_ID
    ok = ref == VERIFIER_ID
    return VerificationCheck(
        check_id=f"evidence:verifier_ref:{ref[:64]}", kind="verifier_ref",
        required=True,
        result=CheckResult.PASS if ok else CheckResult.NOT_EVALUABLE,
        explanation="supported_verifier_ref" if ok else f"unsupported_verifier_ref:{ref[:64]}")


def check_no_substantive() -> VerificationCheck:
    """evidence:substantive_check（blocker 1）——substantive gate 否定分支。

    即使 terminal claim、backend allowlist、verifier_ref 全 PASS，只要没有
    至少一项真实 substantive deterministic check（契约判据本地确定性 PASS 或
    required artifact 真实本地检查 PASS），最终裁定必须是 INCONCLUSIVE——
    绝不 VERIFIED、绝不签 seal。
    """
    return VerificationCheck(
        check_id="evidence:substantive_check", kind="evidence_substantive",
        required=True, result=CheckResult.NOT_EVALUABLE,
        explanation="no_substantive_deterministic_check")


# ---------------------------------------------------------------------------
# 契约判据检查器（16A VERIFICATION_CRITERION_KINDS 一一对应）
# ---------------------------------------------------------------------------

def check_criterion(*, criterion_id: str, kind: str, params: Tuple[Tuple[str, str], ...],
                    contains_path: Callable[[str, bool], bool],
                    workspace_root: Optional[str],
                    process_timeout_seconds: float) -> VerificationCheck:
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
                                        process_timeout_seconds, inputs)

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
            if rejection == "mutated":
                return _with(check, CheckResult.FAIL,
                             "artifact_mutated_during_verification", inputs)
            if rejection == "unreadable":
                return _with(check, CheckResult.NOT_EVALUABLE, "unreadable", inputs)
            if digest == expected:
                return _with(check, CheckResult.PASS, "sha256_match", inputs)
            return _with(check, CheckResult.FAIL, "sha256_mismatch", inputs)

        text, truncated, rejection = read_text_window(real)
        if rejection == "oversize":
            return _with(check, CheckResult.FAIL, "artifact_oversize", inputs)
        if rejection == "mutated":
            return _with(check, CheckResult.FAIL,
                         "artifact_mutated_during_verification", inputs)
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


# ---------------------------------------------------------------------------
# 有界进程重跑（blocker 5：输出真正有界 + 可靠终止）
# ---------------------------------------------------------------------------

def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """可靠终止整棵进程树：Windows 上 shell=True 的直接子进程是 cmd.exe，
    ``kill()`` 只终止 shell——必须**先** ``taskkill /F /T`` 递归终止（树完整时
    枚举；先 kill 会让树断根、孙进程存活）；POSIX 终止进程组。随后 kill 兜底
    并有界 wait 收尾。终止尽力而为，exit 事实仍以 wait 结果为准。"""
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
        except Exception:   # pragma: no cover —— 终止兜底失败不影响事实裁定
            pass
    else:
        try:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:   # pragma: no cover
            pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:   # pragma: no cover
        pass


def run_process_bounded(command: str, cwd: Optional[str],
                        timeout_seconds: float) -> Tuple[Optional[int], bool, str]:
    """本地有界进程重跑。stdout/stderr/stdin 一律 **DEVNULL**——输出内容零
    读取、零聚合、零存储（禁止 PIPE + communicate 无界聚合，blocker 5）。

    返回 ``(exit_code, timed_out, rejection)``；rejection ∈ {"", "spawn_error:<Exc>"}。
    超时路径：kill + taskkill /T（进程组）+ 有界 wait——进程被可靠终止。
    """
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=(sys.platform != "win32"))
    except (OSError, ValueError) as exc:
        return None, False, f"spawn_error:{type(exc).__name__}"
    timed_out = False
    try:
        rc = proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(proc)
        rc = None
    return rc, timed_out, ""


def _check_process_exit_zero(check: VerificationCheck, command: str,
                             workspace_root: Optional[str], timeout_seconds: float,
                             inputs: Tuple[Tuple[str, str], ...]) -> VerificationCheck:
    """本地重跑契约判据命令（有界超时；输出内容零存储，只保留 exit code 事实）。"""
    if not command:
        return _with(check, CheckResult.NOT_EVALUABLE, "empty_command", inputs)
    if not workspace_root or not os.path.isdir(workspace_root):
        return _with(check, CheckResult.NOT_EVALUABLE, "workspace_root_missing", inputs)
    rc, timed_out, rejection = run_process_bounded(command, workspace_root,
                                                   timeout_seconds)
    if rejection:
        return _with(check, CheckResult.NOT_EVALUABLE, rejection, inputs)
    if timed_out:
        return _with(check, CheckResult.FAIL, "process_timeout", inputs)
    if rc == 0:
        return _with(check, CheckResult.PASS, "exit_zero", inputs)
    return _with(check, CheckResult.FAIL, f"exit_code:{rc}", inputs)
