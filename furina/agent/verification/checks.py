"""Phase 16F — 确定性检查器（deterministic checkers，全部本地真相）。

16F 任务书 §3/§4 + 关键锁定 1/7 + Reviewer Patch 1（blocker 1/5/7）
+ Reviewer Patch 2（blocker B1/B3/B7）+ Reviewer Patch 3（blocker B2/B4）：

- **单路径单快照（Patch 3 B2）**：:func:`capture_file_contained` 是唯一
  读取入口——一次 open → 同一句柄完整有界读取 → SHA-256 +
  :func:`full_content_verdict` + 全文文本合法性 + 1 MiB 解码窗口；同一
  canonical 路径在单次 verify 内只捕获一次（:class:`FileSnapshot`），
  expectation/declared/exists/sha/text/regex 全部复用，任何检查不得重新
  按路径打开已缓存文件；criterion-only 文件同样完整读取（≤ 8 MiB）且先
  证明整体为合法文本（NUL/UTF-8）——empty/unreadable/oversize/mutated/
  path escape 一律 required FAIL，绝不跳过检查后放行。
- **POSIX regex worker 独立 session（Patch 3 B4）**：worker 以
  ``start_new_session=True`` 自建进程组/会话；timeout 终止仅当其 pgid 归属
  worker 自身才 ``killpg``，绝不触碰宿主进程组（worker 必死、宿主必活）。

- 所有判据由本模块**在本地独立执行**：文件存在性 / 归属 / 大小 / MIME /
  SHA-256 全部本地观察；``process_exit_zero`` **本地重跑**契约判据命令
  （有界超时），backend 自报的 exit code / 测试通过 / 日志只是 claim——
  本模块的输入里根本没有这些字段。
- **句柄锚定 containment（blocker B3）**：安全判断绝不只依赖 open 前的
  ``realpath``——先以只读方式取得句柄，再依据**该句柄**的 OS 级真实目标
  （Windows ``GetFinalPathNameByHandle`` / Linux ``/proc/self/fd`` /
  macOS ``F_GETPATH``）证明其位于 workspace 内；hash/size/MIME/文本全部
  来自同一已证明句柄或同一不可变快照。验证期间路径替换 / inode 变化 /
  截断 / 增长 → ``mutated`` → FAIL；平台无法给出句柄目标证明 →
  ``handle_target_unprovable`` → 拒绝该检查，绝不退回不安全路径模式。
- **完整内容验证（blocker B1）**：MIME 识别与 artifact 有效性基于同一
  稳定、完整、有界快照（≤ MAX_ARTIFACT_BYTES 的全部字节）——
  :func:`full_content_verdict`：PNG/JPEG Pillow 结构验证、PDF 偏移 0 +
  封闭结构（版本 + 尾部 %%EOF）、JSON 完整严格解析、text 完整严格解码、
  空/畸形/截断一律 fail-closed；绝不只看前 1 KiB 后默认剩余可信。
- **正则真实资源边界（blocker B7 §9.1）**：调用方提供的 pattern 绝不在
  主验证线程执行回溯——在可强制终止的隔离 worker 子进程中执行，硬超时 +
  输入上限 + 零输出聚合（stdout/stderr DEVNULL，唯一通道是 exit code）。
- **进程树硬约束（blocker B7 §9.2）**：Windows 用 Job Object
  （KILL_ON_JOB_CLOSE + 挂起态收编 + 拒绝 breakaway）提供 OS 级、
  "从启动起"的树级 containment——正常退出/超时/异常路径都终止一切仍受
  管辖的后代；POSIX 无 unprivileged 等价保证 → process 判据在该平台
  **fail-closed 拒绝评估**（``process_containment_guaranteed``），绝不
  best-effort 后报告 PASS。进程输出保持 DEVNULL 零读取零聚合。
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
  （spawn 失败 / 无法读取 / 模式无法编译 / 平台能力缺失），绝不表示通过。
"""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable, Optional, Tuple

from .models import (
    MAX_ARTIFACT_BYTES,
    MAX_TEXT_READ_BYTES,
    MIME_SNIFF_WINDOW,
    PROCESS_CHUNK_BYTES,
    CheckResult,
    VerificationCheck,
    VerificationError,
    full_content_verdict,
)

__all__ = [
    "FileSnapshot",
    "observe_file",
    "sha256_file_bounded",
    "read_text_window",
    "open_contained",
    "capture_file_contained",
    "snapshot_file_contained",
    "read_text_window_contained",
    "regex_match_bounded",
    "process_containment_guaranteed",
    "run_process_bounded",
    "check_terminal_claim",
    "check_backend_authorized",
    "check_verifier_ref",
    "check_no_substantive",
    "check_criterion",
]

_TERMINAL_KIND_PASS = "backend.completed"
_TERMINAL_KIND_FAIL = frozenset({"backend.failed", "backend.cancelled"})

#: CREATE_SUSPENDED（subprocess 模块未导出该常量）：子进程挂起态创建 →
#: 收编进 Job Object 后再恢复——保证"从启动起"即受树级硬约束（blocker B7）。
_CREATE_SUSPENDED = 0x00000004


# ---------------------------------------------------------------------------
# 句柄级 OS 证明（blocker B3）
# ---------------------------------------------------------------------------

def _final_path_of_handle(fd: int) -> Optional[str]:
    """已打开句柄的 OS 级真实最终目标（解析 symlink / junction / reparse point）。

    Windows ``GetFinalPathNameByHandleW``；Linux ``/proc/self/fd/<fd>``；
    macOS ``fcntl(F_GETPATH)``。平台无法证明 → ``None``——调用方必须
    fail-closed，绝不退回"先解析路径、后按路径打开"的不安全模式。
    """
    try:
        if sys.platform == "win32":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            k32 = ctypes.windll.kernel32
            k32.GetFinalPathNameByHandleW.argtypes = [
                wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
            k32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
            handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
            cap = 32768
            buf = ctypes.create_unicode_buffer(cap)
            size = k32.GetFinalPathNameByHandleW(handle, buf, wintypes.DWORD(cap),
                                                 wintypes.DWORD(0))
            if size == 0 or size > cap:
                return None
            p = buf.value
            if p.startswith("\\\\?\\"):
                p = p[4:]
            return p or None
        proc_fd = f"/proc/self/fd/{fd}"
        if os.path.exists(proc_fd):                      # Linux
            return os.readlink(proc_fd) or None
        if sys.platform == "darwin":                     # macOS F_GETPATH
            import ctypes

            buf = ctypes.create_string_buffer(1024)
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.fcntl(fd, 103, buf) == 0:            # F_GETPATH == 103
                return buf.value.decode("utf-8", "replace") or None
        return None
    except Exception:
        return None


def open_contained(path: str, contains_path: Callable[[str, bool], bool],
                   writable: bool) -> Tuple[Optional[BinaryIO], str, str]:
    """受约束打开 + **句柄级** containment 证明（blocker B3 唯一入口）。

    先以只读、无写方式取得句柄，再依据**该句柄**的 OS 级真实目标判定归属；
    证明失败一律拒绝。返回 ``(fileobj|None, final_path, rejection)``；
    rejection ∈ {"", "missing", "not_regular_file", "unreadable",
    "path_escape", "handle_target_unprovable"}。调用方负责 close。
    """
    try:
        f = open(path, "rb")            # 只读句柄；读取有界由调用方保证
    except FileNotFoundError:
        return None, "", "missing"
    except IsADirectoryError:
        return None, "", "not_regular_file"
    except OSError:
        try:
            if os.path.isdir(path):     # Windows 打开目录同样报 PermissionError
                return None, "", "not_regular_file"
        except OSError:
            pass
        return None, "", "unreadable"
    try:
        final_path = _final_path_of_handle(f.fileno())
    except Exception:
        final_path = None
    if not final_path:
        f.close()
        return None, "", "handle_target_unprovable"
    if not contains_path(os.path.normpath(final_path), writable):
        f.close()
        return None, final_path, "path_escape"
    return f, final_path, ""


# ---------------------------------------------------------------------------
# 稳定快照（单句柄有界观察 + 前后一致性证明，blocker 7 / B1 / B3）
# ---------------------------------------------------------------------------

def _stat_id(st: os.stat_result) -> Tuple[Any, ...]:
    """快照一致性身份：device / inode / size / mtime_ns。"""
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _read_full_bounded(f: BinaryIO) -> Tuple[bytes, int, Optional[os.stat_result], str]:
    """从已证明句柄读取**完整有界内容**（≤ MAX_ARTIFACT_BYTES，单快照）。

    返回 ``(data, size, last_fstat, rejection)``；rejection ∈
    {"", "not_regular_file", "oversize", "mutated", "unreadable"}。句柄前后
    fstat 一致（设备/inode/大小/mtime 任一漂移即 mutated）；任何 IO 失败
    （含区域锁/权限拒绝）一律 ``unreadable``——绝不异常逃逸、绝不降级 PASS。
    """
    try:
        st0 = os.fstat(f.fileno())
        if not stat.S_ISREG(st0.st_mode):
            return b"", int(st0.st_size), st0, "not_regular_file"
        chunks: list = []
        total = 0
        while True:
            chunk = f.read(PROCESS_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                return b"", int(st0.st_size), st0, "oversize"
            chunks.append(chunk)
        st1 = os.fstat(f.fileno())
    except OSError:
        return b"", 0, None, "unreadable"
    if _stat_id(st0) != _stat_id(st1):
        return b"", int(st0.st_size), st1, "mutated"
    return b"".join(chunks), int(st0.st_size), st1, ""


def _post_close_consistent(st_last: os.stat_result, path: str) -> bool:
    """close 前 stat(证明路径) 与最后 fstat 一致——读取期间路径被替换 /
    inode 变化 → False（mutated）。"""
    try:
        st2 = os.stat(path)
    except OSError:
        return False
    return _stat_id(st_last) == _stat_id(st2)


@dataclass(frozen=True)
class FileSnapshot:
    """单次句柄锚定捕获的**完整不可变快照**（Patch 3 B2）。

    一次 open → 同一句柄完整有界读取 → SHA-256 + :func:`full_content_verdict`
    + 全文文本合法性（NUL / 严格 UTF-8）+ 1 MiB 文本窗口。同一 canonical
    路径在单次 verify 内只捕获一次，expectation / declared / exists / sha /
    text / regex 全部复用同一快照；任何检查都不得重新按路径打开已缓存文件。
    ``rejection`` ∈ {"", "missing", "path_escape", "not_regular_file",
    "handle_target_unprovable", "unreadable", "oversize", "mutated"}。
    """

    claimed_path: str
    final_path: str                 # 句柄真实目标；prefilter 逃逸/missing 时为 realpath 预筛值
    target_exists: bool
    is_regular_file: bool
    within_workspace: bool
    size_bytes: Optional[int]
    sha256_hex: str
    content_mime: str               # full_content_verdict 识别真值（不可观察 ""）
    content_rejection: str          # 完整内容结构验证拒绝（""=通过）
    full_text_valid: bool           # 完整内容为合法文本（无 NUL + 严格 UTF-8）
    text_window: str                # 前 MAX_TEXT_READ_BYTES 解码文本（full_text_valid 时）
    rejection: str


def capture_file_contained(path: str, contains_path: Callable[[str, bool], bool],
                           writable: bool) -> FileSnapshot:
    """句柄锚定的完整快照捕获（Patch 3 B2 唯一读取入口）。

    先以 realpath 预筛分类 missing/逃逸（不读取任何内容；非安全判断依据，
    真实 containment 证明在句柄层），再 open_contained 证明 → 同一句柄完整
    有界读取 → SHA-256 + :func:`full_content_verdict` + 全文文本合法性 +
    1 MiB 解码窗口 → close 前后一致性证明。空 / 不可读 / 超界 / 变异 / 逃逸 /
    句柄目标不可证明一律在 rejection 中 fail-closed，绝不降级 PASS。
    """
    claimed = os.path.normpath(os.path.expanduser(path))
    real_prefilter = os.path.realpath(claimed)
    if not contains_path(real_prefilter, writable):
        exists = os.path.exists(real_prefilter)
        is_file = bool(exists) and os.path.isfile(real_prefilter)
        return FileSnapshot(claimed, real_prefilter, exists, is_file, False,
                            None, "", "", "", False, "", "path_escape")
    f, final_path, rej = open_contained(claimed, contains_path, writable)
    if rej == "missing":
        return FileSnapshot(claimed, real_prefilter, False, False, True,
                            None, "", "", "", False, "", "missing")
    if rej == "not_regular_file":
        return FileSnapshot(claimed, final_path, True, False, True,
                            None, "", "", "", False, "", "not_regular_file")
    if rej == "path_escape":
        return FileSnapshot(claimed, final_path, True, True, False,
                            None, "", "", "", False, "", "path_escape")
    if rej:     # unreadable / handle_target_unprovable
        return FileSnapshot(claimed, final_path, True, True, True,
                            None, "", "", "", False, "", rej)
    try:
        data, size, st_last, rj = _read_full_bounded(f)
        if rj == "" and not _post_close_consistent(st_last, final_path):
            rj = "mutated"
    finally:
        f.close()
    if rj:      # oversize / mutated / unreadable（读取期 IO 失败）
        return FileSnapshot(claimed, final_path, True, True, True,
                            size, "", "", "", False, "", rj)
    digest = hashlib.sha256(data).hexdigest()
    content_mime, content_rejection = full_content_verdict(data)
    full_text_valid = _is_full_text(data)
    window = ""
    if full_text_valid:
        window = _decode_text_window(data[:MAX_TEXT_READ_BYTES]) or ""
    return FileSnapshot(claimed, final_path, True, True, True, size, digest,
                        content_mime, content_rejection, full_text_valid,
                        window, "")


def snapshot_file_contained(path: str, contains_path: Callable[[str, bool], bool],
                            writable: bool
                            ) -> Tuple[Optional[int], str, str, str, str, str]:
    """句柄锚定的完整 artifact 快照（兼容 API，底层即
    :func:`capture_file_contained`）：open_contained 证明 → 同一句柄读取
    完整有界内容 → SHA-256 + :func:`full_content_verdict` → close 前后
    一致性证明。返回 ``(size_bytes, sha256_hex, content_mime,
    content_rejection, final_path, rejection)``；rejection ∈ {"", "missing",
    "path_escape", "not_regular_file", "handle_target_unprovable",
    "unreadable", "oversize", "mutated"}。
    """
    snap = capture_file_contained(path, contains_path, writable)
    return (snap.size_bytes, snap.sha256_hex, snap.content_mime,
            snap.content_rejection, snap.final_path, snap.rejection)


def _decode_text_window(window: bytes) -> Optional[str]:
    """严格文本解码（容忍窗口边界截断的多字节尾字符，至多回退 3 字节）；
    NUL 或非法 UTF-8 → ``None``（content_not_text）。"""
    if b"\x00" in window:
        return None
    for cut in range(4):
        blob = window[:len(window) - cut] if cut else window
        try:
            return blob.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def _is_full_text(data: bytes) -> bool:
    """完整内容是否为合法文本：无 NUL 且严格 UTF-8 可解码（Patch 3 B2——
    criterion-only 文件必须整体先证明是合法文本，搜索才限 1 MiB 窗口）。"""
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _text_window_from_handle(f: BinaryIO,
                             postcheck_path: str) -> Tuple[str, bool, str]:
    """从已证明句柄读取有界文本窗口（≤ MAX_TEXT_READ_BYTES，同一快照）。

    先按 MAX_ARTIFACT_BYTES 硬上限拒绝（criterion-only 文件不允许 100 MB
    大文件靠窗口命中而 PASS）；返回 ``(text, truncated, rejection)``；
    rejection ∈ {"", "unreadable", "oversize", "mutated", "content_not_text"}。
    """
    try:
        st0 = os.fstat(f.fileno())
        if st0.st_size > MAX_ARTIFACT_BYTES:
            return "", False, "oversize"
        data = f.read(MAX_TEXT_READ_BYTES + 1)
        st1 = os.fstat(f.fileno())
    except OSError:
        return "", False, "unreadable"
    if _stat_id(st0) != _stat_id(st1):
        return "", False, "mutated"
    if not _post_close_consistent(st1, postcheck_path):
        return "", False, "mutated"
    truncated = len(data) > MAX_TEXT_READ_BYTES
    text = _decode_text_window(data[:MAX_TEXT_READ_BYTES])
    if text is None:
        return "", truncated, "content_not_text"
    return text, truncated, ""


# -- 公开兼容工具（uncontained 独立观察；16F 验证路径一律走 contained 变体） ----

def read_text_window_contained(path: str, contains_path: Callable[[str, bool], bool],
                               writable: bool) -> Tuple[str, bool, str, str]:
    """句柄锚定的有界文本窗口读取（blocker B3/B7 公开面）：受约束打开 +
    句柄真实目标 containment 证明，窗口来自同一已证明句柄快照。
    返回 ``(text, truncated, final_path, rejection)``；rejection ∈
    open_contained 集 ∪ {"oversize", "mutated", "content_not_text"}。"""
    f, final_path, rej = open_contained(path, contains_path, writable)
    if rej:
        return "", False, final_path, rej
    try:
        text, truncated, rj = _text_window_from_handle(f, final_path)
    finally:
        f.close()
    return text, truncated, final_path, rj


def observe_file(path: str) -> Tuple[int, str, bytes, str]:
    """未含 containment 的独立观察工具（兼容 API）。16F 验证路径一律使用
    :func:`snapshot_file_contained`（blocker B3：安全判断不依赖 open 前路径
    解析）。返回 ``(size, sha256_hex, head, rejection)``；任一 rejection
    时 sha256 为空。"""
    try:
        f = open(path, "rb")
    except OSError:
        return 0, "", b"", "unreadable"
    try:
        data, size, st_last, rj = _read_full_bounded(f)
        if rj == "" and not _post_close_consistent(st_last, path):
            rj = "mutated"
    finally:
        f.close()
    if rj:
        return size, "", b"", rj
    return size, hashlib.sha256(data).hexdigest(), data[:MIME_SNIFF_WINDOW], ""


def sha256_file_bounded(path: str) -> Tuple[str, str]:
    """流式 SHA-256 快照哈希（兼容 API；超过 MAX_ARTIFACT_BYTES / 变异 /
    IO 失败返回 ("", rejection)）。"""
    _size, digest, _head, rejection = observe_file(path)
    return digest, rejection


def read_text_window(path: str) -> Tuple[str, bool, str]:
    """有界读取文本窗口（兼容 API；(text, truncated, rejection)）。
    16F 验证路径使用句柄锚定的 contained 变体。"""
    try:
        f = open(path, "rb")
    except OSError:
        return "", False, "unreadable"
    try:
        text, truncated, rj = _text_window_from_handle(f, path)
    finally:
        f.close()
    return text, truncated, rj


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
                    process_timeout_seconds: float,
                    snapshot_cache: Optional[Any] = None) -> VerificationCheck:
    """按判据 kind 分派到确定性本地检查；check_id = ``criterion:<criterion_id>``。

    文件类判据全部句柄锚定（blocker B3）：受约束打开 + 句柄真实目标
    containment 证明，读取只来自已证明句柄/同一不可变快照。**Patch 3 B2**：
    传入 ``snapshot_cache``（:class:`~verifier._PathSnapshotCache`，提供
    ``get(path) -> FileSnapshot``）时，同一 canonical 路径复用同一完整快照，
    绝不重新按路径打开；criterion-only 文件同样完整读取（≤ 8 MiB）并先证明
    整体为合法文本（NUL/UTF-8），empty/unreadable/oversize/mutated/path
    escape 一律 required FAIL（绝不跳过检查后放行）。
    """
    check = VerificationCheck(
        check_id=f"criterion:{criterion_id}", kind=kind, required=True,
        result=CheckResult.NOT_EVALUABLE, explanation="pending")
    p = dict(params)

    if kind == "process_exit_zero":
        command = p.get("command", "")
        inputs = (("command", command), ("timeout_seconds", repr(process_timeout_seconds)))
        return _check_process_exit_zero(check, command, workspace_root,
                                        process_timeout_seconds, inputs)

    if kind in ("artifact_file_exists", "artifact_sha256", "text_contains", "regex_matches"):
        path = p.get("path", "")
        inputs = (("path", path),)
        if snapshot_cache is not None:
            snap = snapshot_cache.get(path)
        else:
            # 无缓存（直接调用）：每次判据独立捕获一次（仍单句柄单快照）。
            snap = capture_file_contained(os.path.expanduser(path),
                                          contains_path, False)
        rej = snap.rejection
        if rej in ("missing", "not_regular_file"):
            return _with(check, CheckResult.FAIL, "file_missing", inputs)
        if rej == "path_escape":
            return _with(check, CheckResult.FAIL,
                         f"path_escape:{snap.final_path[:256]}", inputs)
        if rej == "handle_target_unprovable":
            return _with(check, CheckResult.NOT_EVALUABLE,
                         "handle_target_unprovable", inputs)
        if rej == "unreadable":
            # Patch 3 B2：criterion-only 文件 unreadable 必须失败（绝不跳过）。
            return _with(check, CheckResult.FAIL, "unreadable", inputs)

        if kind == "artifact_file_exists":
            if rej == "oversize":
                return _with(check, CheckResult.FAIL, "artifact_oversize", inputs)
            if rej == "mutated":
                return _with(check, CheckResult.FAIL,
                             "artifact_mutated_during_verification", inputs)
            if snap.size_bytes == 0:
                # Patch 3 B2：空文件 artifact_file_exists 必须 FAIL（绝非存在）。
                return _with(check, CheckResult.FAIL, "artifact_empty", inputs)
            return _with(check, CheckResult.PASS, "file_exists", inputs)

        if kind == "artifact_sha256":
            expected = p.get("sha256_hex", "")
            inputs = inputs + (("sha256_hex", expected),)
            if rej == "oversize":
                return _with(check, CheckResult.FAIL, "artifact_oversize", inputs)
            if rej == "mutated":
                return _with(check, CheckResult.FAIL,
                             "artifact_mutated_during_verification", inputs)
            if snap.sha256_hex == expected:
                return _with(check, CheckResult.PASS, "sha256_match", inputs)
            return _with(check, CheckResult.FAIL, "sha256_mismatch", inputs)

        # text_contains / regex_matches
        if rej == "oversize":
            return _with(check, CheckResult.FAIL, "artifact_oversize", inputs)
        if rej == "mutated":
            return _with(check, CheckResult.FAIL,
                         "artifact_mutated_during_verification", inputs)
        if not snap.full_text_valid:
            # Patch 3 B2：文件整体必须先证明是合法文本（无 NUL + 严格 UTF-8），
            # 搜索才限 1 MiB 窗口——NUL/二进制尾不得被前 1 MiB 掩盖。
            return _with(check, CheckResult.FAIL, "content_not_text", inputs)
        text = snap.text_window
        truncated = (snap.size_bytes or 0) > MAX_TEXT_READ_BYTES
        if kind == "text_contains":
            needle = p.get("needle", "")
            inputs = inputs + (("needle", needle),)
            if needle in text:
                return _with(check, CheckResult.PASS,
                             f"needle_found window_truncated={truncated}", inputs)
            return _with(check, CheckResult.FAIL,
                         f"needle_not_found window_truncated={truncated}", inputs)
        # regex_matches（blocker B7 §9.1：隔离 worker 有界执行）
        pattern = p.get("pattern", "")
        inputs = inputs + (("pattern", pattern),)
        if len(pattern) > 2048:
            return _with(check, CheckResult.NOT_EVALUABLE,
                         "pattern_oversize", inputs)
        matched, rj = regex_match_bounded(pattern, text, process_timeout_seconds)
        if rj:
            return _with(check, CheckResult.NOT_EVALUABLE, rj, inputs)
        if matched:
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
# 有界正则执行（blocker B7 §9.1：隔离 worker + 硬超时 + 零输出聚合）
# ---------------------------------------------------------------------------

_REGEX_WORKER_CODE = (
    "import re, sys\n"
    "try:\n"
    "    pat = sys.argv[1]\n"
    "    data = sys.stdin.buffer.read()\n"
    "except Exception:\n"
    "    sys.exit(3)\n"
    "try:\n"
    "    rx = re.compile(pat)\n"
    "except Exception:\n"
    "    sys.exit(2)\n"
    "try:\n"
    "    sys.exit(0 if rx.search(data.decode('utf-8', 'replace')) else 1)\n"
    "except Exception:\n"
    "    sys.exit(3)\n"
)

_REGEX_EXIT_MATCH = 0
_REGEX_EXIT_NO_MATCH = 1
_REGEX_EXIT_INVALID = 2


def regex_match_bounded(pattern: str, text: str,
                        timeout_seconds: float) -> Tuple[Optional[bool], str]:
    """任意调用方 pattern 的**隔离有界执行**（blocker B7 §9.1 + Patch 3 B4）。

    pattern 绝不在主验证线程执行回溯：在可强制终止的独立 worker 子进程中
    编译+匹配，硬超时（超时即终止进程树）、输入上限（上游 ≤ 1 MiB 窗口）、
    零输出聚合（stdout/stderr 一律 DEVNULL，唯一通道是 exit code：
    0=match / 1=no-match / 2=invalid pattern / 3=worker error）。
    **Patch 3 B4**：POSIX worker 以 ``start_new_session=True`` 自建独立
    session/进程组——timeout 终止时仅当其 pgid 归属 worker 自身才 ``killpg``，
    绝不触碰宿主进程组（worker 必死、宿主必活）；Windows 保持有界终止。
    返回 ``(matched|None, rejection)``；rejection ∈ {"", "regex_timeout",
    "regex_worker_spawn_error:<Exc>", "regex_worker_error", "invalid_pattern"}。
    timeout / invalid / worker error 一律 NOT_EVALUABLE（最终绝不 VERIFIED）。
    """
    popen_kwargs = dict(shell=False, stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", _REGEX_WORKER_CODE, pattern], **popen_kwargs)
    except (OSError, ValueError) as exc:
        return None, f"regex_worker_spawn_error:{type(exc).__name__}"
    try:
        proc.communicate(input=text.encode("utf-8"), timeout=max(float(timeout_seconds), 0.1))
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        return None, "regex_timeout"
    rc = proc.returncode
    if rc == _REGEX_EXIT_MATCH:
        return True, ""
    if rc == _REGEX_EXIT_NO_MATCH:
        return False, ""
    if rc == _REGEX_EXIT_INVALID:
        return None, "invalid_pattern"
    return None, "regex_worker_error"


# ---------------------------------------------------------------------------
# 进程树硬约束（blocker B7 §9.2）+ 有界进程重跑
# ---------------------------------------------------------------------------

def process_containment_guaranteed() -> bool:
    """平台能否提供 OS 级、"从启动起"的进程树硬约束证明。

    Windows：Job Object（KILL_ON_JOB_CLOSE + CREATE_SUSPENDED 挂起态收编 +
    拒绝 breakaway）→ True——后代无论 detached / 新进程组 / 新会话都留在
    job 内，任何路径（正常退出/超时/异常）关闭 job 句柄即全部终止。
    POSIX：killpg 无法约束自行 ``setsid`` 的后代且无 unprivileged 容器
    保证 → False——process 判据在该平台 **fail-closed 拒绝评估**，绝不
    best-effort 后报告 PASS。
    """
    return sys.platform == "win32"


def _win_create_kill_on_close_job() -> Optional[int]:
    """创建 KILL_ON_JOB_CLOSE 的 Job Object；失败返回 None（fail-closed：
    无硬约束即不启动进程）。"""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_LIMITS(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _EXTENDED_LIMITS(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMITS),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    k32 = ctypes.windll.kernel32
    k32.CreateJobObjectW.argtypes = [wintypes.LPWSTR, wintypes.LPWSTR]
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    k32.SetInformationJobObject.restype = wintypes.BOOL
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _EXTENDED_LIMITS()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                       ctypes.byref(info),
                                       wintypes.DWORD(ctypes.sizeof(info))):
        k32.CloseHandle(job)
        return None
    return int(job)


def _win_assign_job(job: int, proc_handle: int) -> bool:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    return bool(k32.AssignProcessToJobObject(wintypes.HANDLE(job),
                                             wintypes.HANDLE(proc_handle)))


def _win_resume_process(proc: subprocess.Popen) -> bool:
    """恢复 CREATE_SUSPENDED 子进程（先 NtResumeProcess，失败则逐线程
    ResumeThread 兜底）；无法恢复 → False（调用方终止并 fail-closed）。"""
    try:
        import ctypes

        ntdll = ctypes.windll.ntdll
        ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
        ntdll.NtResumeProcess.restype = ctypes.c_long
        if int(ntdll.NtResumeProcess(ctypes.c_void_p(int(proc._handle)))) == 0:
            return True
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPTHREAD = 0x4
        THREAD_SUSPEND_RESUME = 0x0002
        k32 = ctypes.windll.kernel32

        class _THREADENTRY32(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ThreadID", wintypes.DWORD),
                        ("th32OwnerProcessID", wintypes.DWORD),
                        ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD)]

        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if not snap or snap == wintypes.HANDLE(-1).value:
            return False
        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(_THREADENTRY32)
        k32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
        k32.Thread32First.restype = wintypes.BOOL
        k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
        k32.Thread32Next.restype = wintypes.BOOL
        k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenThread.restype = wintypes.HANDLE
        k32.ResumeThread.argtypes = [wintypes.HANDLE]
        k32.ResumeThread.restype = wintypes.DWORD
        resumed = 0
        ok = bool(k32.Thread32First(snap, ctypes.byref(entry)))
        while ok:
            if entry.th32OwnerProcessID == proc.pid:
                h = k32.OpenThread(THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if h:
                    if k32.ResumeThread(h) != wintypes.DWORD(-1).value:
                        resumed += 1
                    k32.CloseHandle(h)
            ok = bool(k32.Thread32Next(snap, ctypes.byref(entry)))
        k32.CloseHandle(snap)
        return resumed > 0
    except Exception:
        return False


def _win_terminate_job(job: int) -> None:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.TerminateJobObject.restype = wintypes.BOOL
    k32.TerminateJobObject(wintypes.HANDLE(job), 1)


def _win_close_job(job: int) -> None:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    k32.CloseHandle(wintypes.HANDLE(job))


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """终止目标进程及其后代（低层兜底工具）。

    Windows ``taskkill /F /T`` 递归终止（先 kill 会断根致孙进程存活——
    顺序修正）；POSIX **仅当目标进程的 pgid 归属其自身（自建 session/进程组
    的 leader）时才 ``killpg``**——绝不触碰宿主进程组（Patch 3 B4：regex
    worker 若被误杀宿主进程组，测试宿主会被连带终止）。随后 kill + 有界
    wait 收尾。此工具是**低层兜底**，树级硬约束声明只属于 Windows Job
    Object 路径（见 :func:`process_containment_guaranteed`）。
    """
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
            pgid = os.getpgid(proc.pid)
        except (OSError, ProcessLookupError):   # pragma: no cover
            pgid = None
        if pgid is not None and pgid == proc.pid:
            # 目标自建进程组/会话：该组完全属于我们 → 整组终止。
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (OSError, ProcessLookupError):   # pragma: no cover
                pass
        else:
            # 无法证明 pgid 归属 → 绝不 killpg（可能命中宿主进程组），只终止
            # worker 本身（Patch 3 B4 fail-closed）。
            try:
                proc.kill()
            except OSError:   # pragma: no cover
                pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:   # pragma: no cover
        pass


def _run_process_bounded_windows(command: str, cwd: Optional[str],
                                 timeout_seconds: float) -> Tuple[Optional[int], bool, str]:
    """Windows：Job Object 硬 containment 的有界进程执行（blocker B7 §9.2）。

    子进程以 CREATE_SUSPENDED 创建 → 挂起态收编进 KILL_ON_JOB_CLOSE 的
    job（后代默认禁 breakaway）→ 恢复执行——**从启动起即受约束**。
    超时 → TerminateJobObject；正常退出/异常 → 关闭 job 句柄，KILL_ON_
    JOB_CLOSE 终止一切仍受管辖的后代（含 detached/新会话/新进程组）。
    stdin/stdout/stderr 一律 DEVNULL（零读取零聚合）。job 创建失败 →
    拒绝启动（``spawn_error:job_unavailable``，fail-closed）。
    """
    job = _win_create_kill_on_close_job()
    if not job:
        return None, False, "spawn_error:job_unavailable"
    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_CREATE_SUSPENDED)
    except (OSError, ValueError) as exc:
        _win_close_job(job)
        return None, False, f"spawn_error:{type(exc).__name__}"
    timed_out = False
    try:
        if not _win_assign_job(job, int(proc._handle)) or not _win_resume_process(proc):
            return None, False, "spawn_error:containment_setup_failed"
        try:
            rc = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _win_terminate_job(job)      # 整个 job（含 detached 后代）立即终止
            rc = None
        return rc, timed_out, ""
    finally:
        # KILL_ON_JOB_CLOSE：任何路径关闭句柄即终止一切仍受管辖的后代
        try:
            proc.kill()
        except OSError:
            pass
        _win_close_job(job)


def run_process_bounded(command: str, cwd: Optional[str],
                        timeout_seconds: float) -> Tuple[Optional[int], bool, str]:
    """本地有界进程重跑。stdout/stderr/stdin 一律 **DEVNULL**——输出内容零
    读取、零聚合、零存储（禁止 PIPE + communicate 无界聚合）。

    返回 ``(exit_code, timed_out, rejection)``；rejection ∈
    {"", "spawn_error:<Exc>"}。Windows 路径提供 Job Object 树级硬约束
    （见 :func:`process_containment_guaranteed`）；POSIX 路径为进程组
    best-effort 兜底，**该平台的 process 判据由 checker 层 fail-closed
    拒绝评估**（不得据此报告 PASS）。
    """
    if sys.platform == "win32":
        return _run_process_bounded_windows(command, cwd, timeout_seconds)
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True)
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
    """本地重跑契约判据命令（有界超时；输出内容零存储，只保留 exit code 事实）。

    blocker B7 §9.2：平台无法提供树级硬约束证明时 fail-closed 拒绝评估
    （NOT_EVALUABLE → 绝不 VERIFIED），绝不回退 best-effort 后报告 PASS。
    """
    if not command:
        return _with(check, CheckResult.NOT_EVALUABLE, "empty_command", inputs)
    if not process_containment_guaranteed():
        return _with(check, CheckResult.NOT_EVALUABLE,
                     "process_containment_unavailable", inputs)
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
