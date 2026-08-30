"""Phase 16F — Independent Verification 数据模型与权威密封（Furina-owned）。

任务级独立校验的类型化词汇（16F 任务书 §3）：

- :class:`EvidenceBundle` —— **有界、不可变**的证据观察集：本地 artifact 观察
  （realpath 归属、大小、MIME、SHA-256 均为 verifier 本地计算的真值，绝不信
  backend 自报）+ 归一化终态事件引用（**只是 claim**，仅用于绑定"验证的是哪
  一次 run"）+ 规范化 evidence_digest。
- :class:`VerificationCheck` —— 确定性 checker 的单一结果（checker id / 输入 /
  结果 / 解释），解释文本经秘密脱敏与限长。
- :class:`VerificationReport` —— 一次独立校验的完整报告（contract/run 身份、
  standard hash、逐项证据、verdict、时间戳）。

权威锁定（16F 任务书 §1/关键锁定 1–2）：

- **VERIFIED 只能由 16F 独立验证成功产生**。verdict=VERIFIED 的报告必须携带
  ``authority_seal`` —— 由 :class:`~verifier.IndependentVerifier` 在**真实执行
  全部确定性检查并全部通过后**，用其构造期生成的随机密钥对 ``report_digest``
  做 HMAC-SHA256 签发的 64 位 hex 密封；报告构造面只做格式校验，**真实性只能
  经 ``IndependentVerifier.seal_is_authentic`` 用签发方密钥复核**。伪造报告
  （假 seal / 无 seal）要么构造被拒、要么无法通过真实性复核——与 16D broker
  HMAC / 16C operation_digest 现场重算同一模式，不依赖 _private / 对象身份 /
  调用方自报字段冒充 authority。
- backend 说 completed / exit code 0 / 流畅文本 / 自报 verified **都不是证明**
  （16E 已把 completed 折算为 BACKEND_DONE_UNVERIFIED；本模块的证据模型里
  根本不存在 backend 自报 verified/success 文本的字段——未知键 fail-closed）。

输入/证据边界（关键锁定 4–5/8）：

- 输入 mapping **exact-schema**：未知键 / 缺键 / 非 str 键 / NaN / Inf /
  bool 冒充数值 / 非绝对路径 / 重复 id 全部 :class:`VerificationInputError`
  fail-closed；解析后立即 defensive-copy 并冻结（MappingProxyType 树）。
- 报告与导出**零共享可变引用**：frozen dataclass + tuple + 每次导出全新
  plain dict；秘密值形态（password/token/api_key/authorization/bearer 等）
  的 **raw secret text 不进入报告、诊断与身份载荷**（evidence digest payload /
  failure signature 前置载荷一律脱敏或拒绝）；身份字段走显式 lexical contract
  （控制字符/首尾空白/静默 trim/秘密形态一律 :class:`VerificationInputError`
  fail-closed，绝不 normalize 后重新绑定）。
- 产物 MIME 是**完整内容**识别真值（:func:`full_content_verdict`：PNG/JPEG
  魔数 + Pillow 结构验证、PDF 偏移 0 + **封闭结构验证**（header/对象/xref/
  startxref/trailer/EOF 与偏移关系，Patch 3 B1——伪 PDF/截断 xref/错误
  startxref 一律 fail-closed）、JSON/text 完整有界解析、二进制显式接受；
  空/畸形/截断一律 fail-closed），扩展名只是命名层交叉核对；
  ``ArtifactExpectation.artifact_type`` 经 16F 显式封闭且 **API 层不可变**
  （blocker B2）的 :data:`ARTIFACT_TYPE_CONTENT_RULES` 进入验证策略——未知
  artifact_type 绝不静默通过，binary/octet-stream 内容只能被显式允许的
  artifact 类型接受。

本模块零 DB / 零 C1–C7 / 零 schema / 零持久化；不写 C6/C7/C3（16G 拥有）。
"""
from __future__ import annotations

import enum
import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from furina.agent.events.models import EventKind
from furina.core import FurinaError

# ---------------------------------------------------------------------------
# 身份 / 词表
# ---------------------------------------------------------------------------

#: 16F 独立验证器唯一身份（VerificationStandard.verifier_refs 仅接受本 id 时才可判 PASS）。
VERIFIER_ID = "furina.verifier.16f.independent"

#: P4-E：TerminalObservation.kind 的**封闭词表**（16E EventKind 值）——公开
#: 导出字符串类型封闭，任何词表外值（含秘密形态）在构造面直接拒绝。
EVENT_KIND_VALUES = frozenset(k.value for k in EventKind)

#: P4-E：ArtifactObservation.source 的封闭取值（expectation | declared）。
ARTIFACT_SOURCE_VALUES = frozenset({"expectation", "declared"})

_REPORT_ID_PATTERN = re.compile(r"^vrp_[0-9a-f]{32}$")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")   # 与 16B run_id 同形
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class VerificationError(FurinaError):
    """16F 校验域统一异常基类。"""


class VerificationInputError(VerificationError):
    """证据提交 mapping 未通过 exact-schema / 严格类型校验（fail-closed，无报告）。"""


class VerificationAuthorityError(VerificationError):
    """伪造 VERIFIED 报告的构造被拒（无 seal / seal 格式非法 / 非 16F 身份）。"""


class VerificationVerdict(str, enum.Enum):
    """三值裁定：只有 16F 独立验证成功可产生 VERIFIED（INCONCLUSIVE 绝不映射 VERIFIED）。"""

    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


class CheckResult(str, enum.Enum):
    """单条确定性检查结果；NOT_EVALUABLE（证据不足以判定）绝不计为通过。"""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT_EVALUABLE"


# ---------------------------------------------------------------------------
# 有界常量（evidence/report 严格限数量与字节）
# ---------------------------------------------------------------------------

MAX_EVIDENCE_EVENTS = 64
MAX_DECLARED_ARTIFACTS = 32
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_REPORT_CHECKS = 128
MAX_DIAGNOSTICS = 32
MAX_EXPLANATION_CHARS = 512
MAX_DIAGNOSTIC_CHARS = 512
MAX_INPUT_VALUE_CHARS = 512
MAX_PATH_CHARS = 1024
MAX_ID_CHARS = 128
MAX_REPORT_JSON_BYTES = 64 * 1024
MAX_TEXT_READ_BYTES = 1024 * 1024
PROCESS_CHUNK_BYTES = 1024 * 1024
DEFAULT_PROCESS_TIMEOUT_SECONDS = 60.0
MAX_PROCESS_TIMEOUT_SECONDS = 600.0
#: P4-F：单次 verify 的**快照总字节上界**（执行前资源门）。每个唯一路径快照
#: ≤ MAX_ARTIFACT_BYTES（8 MiB），因此唯一路径数 × 8 MiB 必须 ≤ 64 MiB——
#: 超限在零文件读取、零进程启动前直接拒绝。
MAX_SNAPSHOT_TOTAL_BYTES = 64 * 1024 * 1024
#: P4-F：图像结构验证的解码上界——width/height 有界、解码像素数有界，
#: 超限在 load() 前按 malformed_content:image_* 拒绝（解压炸弹绝不解码）。
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 4096 * 4096

#: 产物 MIME 白名单（声明值必须命中白名单；观察值来自**内容识别**而非扩展名）。
SUPPORTED_MIME_TYPES = frozenset({
    "text/plain", "text/markdown", "text/csv", "text/html",
    "application/json", "application/octet-stream",
    "application/pdf", "image/png", "image/jpeg",
})

_MIME_BY_SUFFIX = {
    ".txt": "text/plain", ".log": "text/plain",
    ".md": "text/markdown", ".csv": "text/csv", ".html": "text/html",
    ".json": "application/json",
    ".pdf": "application/pdf", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".bin": "application/octet-stream",
}


def mime_for_suffix(path: str) -> str:
    """命名层 MIME（仅由扩展名推断）；未知扩展名返回 ``""``——后缀不是真实
    MIME，未知命名一律 fail-closed，绝不冒充 application/octet-stream。"""
    dot = path.rfind(".")
    if dot < 0:
        return ""
    return _MIME_BY_SUFFIX.get(path[dot:].lower(), "")


# ---------------------------------------------------------------------------
# 有界内容识别（blocker 2）：MIME 观察真值来自内容，不来自扩展名
# ---------------------------------------------------------------------------

#: 内容识别窗口（字节）；所有规则只看该窗口，明确且有界。
MIME_SNIFF_WINDOW = 1024

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_PDF_MAGIC = b"%PDF-"
_JSON_LEAD_BYTES = b" \t\r\n"

#: 16F 显式、封闭的 ``artifact_type → 允许的内容 MIME 集``（验证策略的一部分）。
#: 未知 artifact_type 不在表内 → 一律 fail-closed，绝不静默通过；
#: binary/application/octet-stream 内容只能被 binary_blob 显式接受。
#: **API 层不可变（blocker B2）**：外层是 MappingProxyType（键不可增删改），
#: 值是 tuple（嵌套结构不可原地修改）——任何修改尝试都抛 TypeError，且进程内
#: 不存在可放宽策略的可变引用。
ARTIFACT_TYPE_CONTENT_RULES: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    "plain_text": ("text/plain", "text/markdown", "text/csv", "text/html"),
    "markdown_document": ("text/markdown", "text/plain"),
    "csv_data": ("text/csv", "text/plain"),
    "html_document": ("text/html", "text/plain"),
    "json_data": ("application/json",),
    "pdf_document": ("application/pdf",),
    "png_image": ("image/png",),
    "jpeg_image": ("image/jpeg",),
    "binary_blob": ("application/octet-stream",),
})


def _utf8_decodable(head: bytes) -> bool:
    """UTF-8 严格可解码（容忍窗口边界截断的多字节尾字符——至多回退 3 字节）。"""
    for cut in range(4):
        blob = head[:len(head) - cut] if cut else head
        try:
            blob.decode("utf-8")
        except UnicodeDecodeError:
            continue
        return True
    return False


def sniff_content_mime(head: bytes) -> str:
    """有界**引导窗口**分类器（只看前 MIME_SNIFF_WINDOW 字节；独立验证的真实
    判定走 :func:`full_content_verdict`——完整有界内容 + 结构验证）：

    - PNG/JPEG/PDF 按魔数（PDF marker 必须位于偏移 0 的合法起始位置——
      任意窗口中出现 marker 不构成 PDF）；
    - JSON：BOM/空白后首字符 ∈ ``{``/``[``（仅引导分类，不做完整解析）；
    - text：窗口内无 NUL 且严格 UTF-8 可解码 → text/plain；
    - 其余 → application/octet-stream（二进制——只能被显式允许的
      artifact 类型接受）；空窗口 → ``""``（不可观察，fail-closed）。
    """
    if not isinstance(head, (bytes, bytearray)) or not head:
        return ""
    head = bytes(head)
    if head[:8] == _PNG_MAGIC:
        return "image/png"
    if head[:3] == _JPEG_MAGIC:
        return "image/jpeg"
    if head[:5] == _PDF_MAGIC:
        return "application/pdf"
    body = head[3:] if head.startswith(b"\xef\xbb\xbf") else head
    if body.lstrip(_JSON_LEAD_BYTES)[:1] in (b"{", b"["):
        return "application/json"
    if b"\x00" not in head and _utf8_decodable(head):
        return "text/plain"
    return "application/octet-stream"


# ---------------------------------------------------------------------------
# 完整内容验证（blocker B1）：MIME 识别与有效性判定基于同一完整、有界快照
# ---------------------------------------------------------------------------

_PDF_HEADER_RE = re.compile(rb"%PDF-[0-9]+\.[0-9]+(?!\d)")
_PDF_XREF_ENTRY_RE = re.compile(rb"\d{10} \d{5} [nf][ \r][\n]")
_PDF_OBJ_DEFINED_RE = re.compile(rb"(?m)^(\d+)\s+0\s+obj\b")

#: 受支持 PDF 封闭子集的确定性验证界限（任何超界即 fail-closed）。
_MAX_PDF_XREF_ENTRIES = 8192

# ---------------------------------------------------------------------------
# P5-B：PDF 结构化 token 解析——Catalog/Pages/trailer 键认定一律基于
# **结构化字典直接键**，绝不在对象原始字节上用正则认定（literal string /
# hex string / 注释 / 嵌套字典中的 `/Type /Catalog`、`/Pages` token 不得
# 充当当前对象的直接键；字典括号必须真实平衡）。
# ---------------------------------------------------------------------------

_PDF_WS_BYTES = b" \t\r\n\x00\f"
_PDF_DELIM_BYTES = b"()<>[]{}/%"
#: 字典/数组嵌套深度上界（病态深嵌套 → 解析失败 fail-closed）。
_MAX_PDF_DICT_DEPTH = 16
_INT_TOKEN_RE = re.compile(rb"\A[0-9]+\Z")
_REAL_TOKEN_RE = re.compile(rb"\A[+-]?([0-9]+|[0-9]*\.[0-9]+|[0-9]+\.[0-9]*)\Z")
_PDF_VALUE_KINDS = ("name", "ref", "int", "dict", "other")


def _skip_pdf_ws(full: bytes, pos: int) -> int:
    n = len(full)
    while pos < n and full[pos:pos + 1] in b" \t\r\n":
        pos += 1
    return pos


def _pdf_skip_ws_comment(full: bytes, pos: int) -> int:
    """跳过空白与注释（``%`` 至行尾）——注释内 token 绝不出现在 token 流。"""
    n = len(full)
    while pos < n:
        c = full[pos:pos + 1]
        if c in _PDF_WS_BYTES:
            pos += 1
        elif c == b"%":
            while pos < n and full[pos:pos + 1] not in b"\r\n":
                pos += 1
        else:
            break
    return pos


def _pdf_scan_token(full: bytes, pos: int) -> Tuple[Optional[bytes], int]:
    """扫描一个 regular token（至空白/分隔符止）；返回 ``(token, next_pos)``。"""
    n = len(full)
    start = pos
    while pos < n:
        c = full[pos:pos + 1]
        if c in _PDF_WS_BYTES or c in _PDF_DELIM_BYTES:
            break
        pos += 1
    if pos == start:
        return None, pos
    return full[start:pos], pos


def _pdf_scan_literal_string(full: bytes, pos: int) -> Optional[int]:
    """literal string（平衡括号 + 反斜杠转义）；返回结束位置或 ``None``。"""
    n = len(full)
    depth = 0
    i = pos
    while i < n:
        c = full[i:i + 1]
        if c == b"\\":
            i += 2
            continue
        if c == b"(":
            depth += 1
        elif c == b")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _pdf_scan_hex_string(full: bytes, pos: int) -> Optional[int]:
    """hex string（``<...>``，内部只允许 hex 数字与空白）；返回结束位置。"""
    n = len(full)
    i = pos + 1
    while i < n:
        c = full[i:i + 1]
        if c == b">":
            return i + 1
        if c not in b"0123456789abcdefABCDEF" and c not in _PDF_WS_BYTES:
            return None
        i += 1
    return None


def _parse_pdf_value(full: bytes, pos: int,
                     depth: int) -> Tuple[Optional[Tuple[str, Any]], int]:
    """解析一个 PDF 对象值；返回 ``((kind, value), next_pos)`` 或 ``(None, pos)``。

    kind ∈ {"name", "ref", "int", "dict", "other"}——受支持子集只需要区分：
    name（``/Type`` 值）、indirect ref（``n g R``）、整数（``/Size``）、字典
    （结构化直接键表）；literal/hex string、数组、布尔等整体视为不透明
    "other"，但其括号/字典必须真实平衡，注释绝不进入 token 流。
    """
    if depth > _MAX_PDF_DICT_DEPTH:
        return None, pos
    pos = _pdf_skip_ws_comment(full, pos)
    n = len(full)
    if pos >= n:
        return None, pos
    c = full[pos:pos + 1]
    if full[pos:pos + 2] == b"<<":
        return _parse_pdf_dict_at(full, pos, depth + 1)
    if c == b"<":
        end = _pdf_scan_hex_string(full, pos)
        if end is None:
            return None, pos
        return ("other", None), end
    if c == b"(":
        end = _pdf_scan_literal_string(full, pos)
        if end is None:
            return None, pos
        return ("other", None), end
    if c == b"[":
        pos = _pdf_skip_ws_comment(full, pos + 1)
        while True:
            if pos >= n:
                return None, pos
            if full[pos:pos + 1] == b"]":
                return ("other", None), pos + 1
            item, pos = _parse_pdf_value(full, pos, depth + 1)
            if item is None:
                return None, pos
    if c == b"/":
        tok, pos2 = _pdf_scan_token(full, pos + 1)
        if tok is None:
            return None, pos
        return ("name", tok), pos2
    tok, pos2 = _pdf_scan_token(full, pos)
    if tok is None:
        return None, pos
    if _INT_TOKEN_RE.match(tok):
        value = int(tok)
        # indirect ref 形态：``int int R``（前瞻第三个 token，不匹配则回退）。
        # P6-B：indirect ref 必须保存 (object_number, generation) 二元组——
        # generation 绝不丢弃（消费方据此与对象定义 generation 精确核对）。
        g, pos3 = _pdf_scan_token(full, _pdf_skip_ws_comment(full, pos2))
        if g is not None and _INT_TOKEN_RE.match(g):
            r, pos4 = _pdf_scan_token(full, _pdf_skip_ws_comment(full, pos3))
            if r == b"R":
                return ("ref", (value, int(g))), pos4
        return ("int", value), pos2
    if tok in (b"true", b"false", b"null", b"R") or _REAL_TOKEN_RE.match(tok):
        return ("other", None), pos2
    return None, pos


def _parse_pdf_dict_at(full: bytes, pos: int,
                       depth: int) -> Tuple[Optional[Tuple[str, Any]], int]:
    """解析 ``<< ... >>`` 字典（顶层**直接键** → 值）；重复直接键、键非 name、
    括号不平衡、嵌套超深一律解析失败（fail-closed）。"""
    if depth > _MAX_PDF_DICT_DEPTH:
        return None, pos
    n = len(full)
    pos += 2
    out: Dict[bytes, Tuple[str, Any]] = {}
    while True:
        pos = _pdf_skip_ws_comment(full, pos)
        if pos >= n:
            return None, pos
        if full[pos:pos + 2] == b">>":
            return ("dict", out), pos + 2
        kv, pos = _parse_pdf_value(full, pos, depth + 1)
        if kv is None or kv[0] != "name":
            return None, pos
        key = kv[1]
        if key in out:
            return None, pos          # 重复直接键 → 结构歧义 → fail-closed
        vv, pos = _parse_pdf_value(full, pos, depth + 1)
        if vv is None:
            return None, pos
        out[key] = vv


def _parse_pdf_dict_strict(body: bytes) -> Optional[Dict[bytes, Tuple[str, Any]]]:
    """body 必须是**恰好一个**完整平衡字典（前后仅空白/注释）——返回顶层
    直接键表；否则 ``None``（fail-closed）。"""
    start = _pdf_skip_ws_comment(body, 0)
    if body[start:start + 2] != b"<<":
        return None
    val, end = _parse_pdf_value(body, start, 0)
    if val is None or val[0] != "dict":
        return None
    if _pdf_skip_ws_comment(body, end) != len(body):
        return None
    return val[1]


def _parse_pdf_int(full: bytes, pos: int) -> Tuple[Optional[int], Optional[int]]:
    """解析非负整数；返回 ``(value, next_pos)``；失败返回 ``(None, None)``。"""
    n = len(full)
    start = pos
    while pos < n and full[pos:pos + 1].isdigit():
        pos += 1
    if pos == start:
        return None, None
    return int(full[start:pos]), pos


def _validate_pdf_structure(full: bytes) -> str:
    """封闭、确定性的受支持 PDF 结构验证（Patch 3 B1 + Patch 4 P4-A）——
    **绝不只检查** ``%PDF-`` 与 ``%%EOF`` 两个 marker，而是验证 header / 对象
    图 / xref / startxref / trailer / EOF 及其偏移关系：

    - header：``%PDF-<major>.<minor>`` 必须位于偏移 0（版本号后不得紧跟数字）；
    - EOF：``%%EOF`` 必须位于尾部 1 KiB 内且为其后唯一内容（仅允许空白）；
    - startxref：必须存在且携带指向 xref 表的十进制字节偏移；
    - xref：该偏移处必须是经典 ``xref`` 表——子段（start/count）+ 定长 20 字节
      条目（``nnnnnnnnnn ggggg n|f``），``n`` 条目记录的字节偏移必须精确指向
      文件中对应 ``<num> 0 obj`` 的位置（偏移关系，非仅对象存在）；
    - **generation 精确绑定（P6-B）**：indirect ref 一律保存
      ``(object_number, generation)``——本封闭子集只支持 ``n 0 obj`` 对象定义，
      因此 xref ``n`` 条目、trailer ``/Root``、Catalog ``/Pages`` 引用的
      generation 都必须为 0，非零即引用与定义不一致 → fail-closed；
    - **对象图（P4-A）**：每个 ``n`` 条目对象必须有匹配的 ``obj ... endobj``
      （缺 ``endobj`` 或对象间存在非空白内容一律 fail-closed），对象体必须是
      完整平衡字典 ``<<...>>``（任意文本/流对象体不被受支持子集接受）；定义
      于文件中的对象号必须恰为 ``n`` 条目对象号（多余对象定义 fail-closed）；
    - **Root 图（P4-A + P5-B）**：Root 的 xref 条目必须是 ``n``（不得是 free）、
      Root 对象体必须是字典且**直接键** ``/Type`` 为 ``/Catalog``（结构化
      token 解析——literal/hex string、注释、嵌套字典中的同名 token 绝不
      充当直接键，伪 Catalog fail-closed）、Catalog 的直接键 ``/Pages`` 必须
      引用有效 ``/Pages`` 对象（``n`` 条目 + 字典 + 直接键 ``/Type /Pages``）；
    - **/Size 一致性（P4-A）**：``/Size`` 必须等于 xref 覆盖的最高对象号 + 1；
    - **trailer 尾（P4-A）**：trailer 字典 ``>>`` 之后只允许合法 ``startxref``
      + 十进制偏移 + 空白 + ``%%EOF``——任何文本对象/多余内容即 fail-closed；
    - 截断 xref / 错误 startxref / 随机内容 / 伪 PDF 一律 fail-closed；
      交叉引用流（/XRef stream）与本封闭子集不支持 → 同样 fail-closed。
    """
    if not _PDF_HEADER_RE.match(full[:32]):
        return "malformed_content:pdf_header"
    eof = full.rfind(b"%%EOF")
    if eof < 0 or len(full) - eof > 1024:
        return "malformed_content:pdf_eof_missing"
    if full[eof + 5:].strip(b" \t\r\n"):
        return "malformed_content:pdf_eof_trailing"
    sx = full.rfind(b"startxref", 0, eof)
    if sx < 0:
        return "malformed_content:pdf_startxref_missing"
    value, pos = _parse_pdf_int(full, _skip_pdf_ws(full, sx + len(b"startxref")))
    if value is None or pos is None or value < 0 or value >= eof:
        return "malformed_content:pdf_startxref_invalid"
    xref_pos = value
    # xref 表（经典格式；/XRef stream 不支持 → fail-closed）
    if full[xref_pos:xref_pos + 4] != b"xref":
        return "malformed_content:pdf_xref_missing"
    pos = _skip_pdf_ws(full, xref_pos + 4)
    covered: set = set()
    n_offsets: dict = {}               # obj_num → n 条目记录的字节偏移
    total_entries = 0
    while True:
        start_num, pos = _parse_pdf_int(full, pos)
        if start_num is None:
            return "malformed_content:pdf_xref_subsection"
        pos = _skip_pdf_ws(full, pos)
        count, pos = _parse_pdf_int(full, pos)
        if count is None or start_num < 0 or count < 1 \
                or start_num + count > _MAX_PDF_XREF_ENTRIES:
            return "malformed_content:pdf_xref_subsection"
        pos = _skip_pdf_ws(full, pos)
        for i in range(count):
            entry = full[pos:pos + 20]
            if len(entry) < 20 or not _PDF_XREF_ENTRY_RE.match(entry):
                return "malformed_content:pdf_xref_entry"
            obj_num = start_num + i
            if obj_num in covered:     # 同一对象号被两条 xref 条目覆盖 → fail-closed
                return "malformed_content:pdf_xref_entry"
            covered.add(obj_num)
            if entry[17:18] == b"n":
                total_entries += 1
                if total_entries > _MAX_PDF_XREF_ENTRIES:
                    return "malformed_content:pdf_xref_too_large"
                # P6-B：xref n-entry 的 generation 字段必须为 00000——本封闭
                # 子集只支持 ``n 0 obj`` 对象定义，非零 generation 条目指向
                # 本子集不存在的对象版本 → fail-closed（free 条目的 65535
                # 惯例头不受影响）。
                if entry[11:16] != b"00000":
                    return "malformed_content:pdf_xref_generation"
                offset10 = int(entry[:10])
                marker = b"%d 0 obj" % obj_num
                # 对象偏移必须位于文件内且落在 xref 表之前（经典布局：对象 →
                # xref → trailer → startxref；指向 xref/trailer 区域或更后的
                # 偏移不属于本封闭子集 → fail-closed）。
                if offset10 >= eof or offset10 >= xref_pos \
                        or full[offset10:offset10 + len(marker)] != marker:
                    return "malformed_content:pdf_xref_offset"
                n_offsets[obj_num] = offset10
            pos += 20
        pos = _skip_pdf_ws(full, pos)
        if pos < len(full) and full[pos:pos + 1].isdigit():
            continue              # 下一个子段
        break
    if not covered:
        return "malformed_content:pdf_xref_subsection"
    xref_end = pos
    # trailer（/Size + /Root 及对象覆盖关系）——P5-B：结构化字典直接键认定，
    # literal/hex string、注释、嵌套字典中的 /Root //Size token 不构成直接键。
    if full[xref_end:xref_end + 7] != b"trailer":
        return "malformed_content:pdf_trailer_missing"
    pos = _skip_pdf_ws(full, xref_end + 7)
    tval, dpos = _parse_pdf_value(full, pos, 0)
    if tval is None or tval[0] != "dict":
        return "malformed_content:pdf_trailer_dict"
    tmap = tval[1]
    end = dpos - 2                      # `>>` 起始（tail 检查基准）
    root_val = tmap.get(b"Root")
    size_val = tmap.get(b"Size")
    if root_val is None or root_val[0] != "ref" \
            or size_val is None or size_val[0] != "int":
        return "malformed_content:pdf_trailer_dict"
    # P6-B：indirect ref 携带 (object_number, generation)——trailer /Root 的
    # generation 必须为 0（封闭子集只支持 n 0 obj；``/Root 1 9 R`` 指向
    # ``1 0 obj`` 即引用与定义 generation 不一致 → fail-closed）。
    root_num, root_gen = root_val[1]
    size = size_val[1]
    if size < 1 or root_num <= 0 or root_num >= size:
        return "malformed_content:pdf_trailer_dict"
    if root_gen != 0:
        return "malformed_content:pdf_root_generation"
    # P4-A：/Size 必须与 xref 覆盖一致（最高对象号 + 1）。
    if size != max(covered) + 1:
        return "malformed_content:pdf_size_mismatch"
    # P4-A：Root 的 xref 条目必须是 n（free Root 一律拒绝）。
    if root_num not in n_offsets:
        return "malformed_content:pdf_root_free"
    # 对象图（P4-A）：n 条目对象与文件中定义的对象一一对应；每个对象必须有
    # 匹配的 obj...endobj；对象体必须是完整平衡字典；对象间只允许空白。
    markers = [(m.start(), int(m.group(1)))
               for m in _PDF_OBJ_DEFINED_RE.finditer(full) if m.start() < xref_pos]
    if len(markers) != len({num for _, num in markers}):
        return "malformed_content:pdf_obj_duplicate"
    obj_marker_pos = {num: p for p, num in markers}
    if set(obj_marker_pos) != set(n_offsets):
        # 文件里定义的对象必须恰为 xref n 条目对象——多余对象定义 / 缺失定义
        # 都意味着对象图与 xref 不一致（含任意文本对象）→ fail-closed。
        return "malformed_content:pdf_obj_graph"
    positions = sorted(p for p, _ in markers)
    obj_dict_maps: dict = {}
    prev_end: Optional[int] = None
    for i, (p, num) in enumerate(sorted(markers)):
        nl = full.find(b"\n", p)
        if nl < 0:
            return "malformed_content:pdf_obj_missing_endobj"
        limit = positions[i + 1] if i + 1 < len(positions) else xref_pos
        e = full.find(b"endobj", nl + 1, limit)
        if e < 0:
            return "malformed_content:pdf_obj_missing_endobj"
        if prev_end is not None and full[prev_end:p].strip(b" \t\r\n"):
            # 对象之间出现非空白内容（文本对象/垃圾）→ 对象图不封闭。
            return "malformed_content:pdf_obj_graph"
        # P5-B：对象体必须是**结构化解析成功**的完整平衡字典（支持嵌套字典/
        # 数组/literal+hex string/注释 token；括号必须真实平衡）——任意文本
        # 对象体或结构破损不被受支持子集接受。
        parsed = _parse_pdf_dict_strict(full[nl + 1:e])
        if parsed is None:
            return "malformed_content:pdf_obj_not_dict"
        obj_dict_maps[num] = parsed
        prev_end = e + len(b"endobj")
    # 最后一个对象的 endobj 与 xref 表之间只允许空白。
    if full[prev_end:xref_pos].strip(b" \t\r\n"):
        return "malformed_content:pdf_obj_graph"
    # P4-A/P5-B：Root 必须是字典且**直接键** /Type == /Catalog（literal
    # string、hex string、注释、嵌套字典中的同名 token 不构成直接键）；
    # Catalog 的**直接键** /Pages 必须引用有效 Pages 对象；Pages 的直接键
    # /Type 必须为 /Pages。
    root_map = obj_dict_maps.get(root_num)
    if root_map is None:
        return "malformed_content:pdf_obj_not_dict"
    if root_map.get(b"Type") != ("name", b"Catalog"):
        return "malformed_content:pdf_root_not_catalog"
    pages_val = root_map.get(b"Pages")
    if pages_val is None or pages_val[0] != "ref":
        return "malformed_content:pdf_root_no_pages"
    # P6-B：Catalog /Pages 引用同样必须 generation 0（``/Pages 2 9 R`` 指向
    # ``2 0 obj`` → 引用与定义 generation 不一致 → fail-closed）。
    pages_num, pages_gen = pages_val[1]
    if pages_gen != 0:
        return "malformed_content:pdf_pages_generation"
    if pages_num not in n_offsets:
        return "malformed_content:pdf_pages_missing"
    pages_map = obj_dict_maps.get(pages_num)
    if pages_map is None or pages_map.get(b"Type") != ("name", b"Pages"):
        return "malformed_content:pdf_pages_not_pages"
    # P4-A：trailer 之后只允许合法 startxref + 偏移 + 空白 + EOF——任何文本
    # 对象/多余内容（startxref 与 trailer 之间出现其它 token）一律 fail-closed。
    tail = _skip_pdf_ws(full, end + 2)
    if full[tail:tail + len(b"startxref")] != b"startxref":
        return "malformed_content:pdf_trailer_tail"
    t2 = _skip_pdf_ws(full, tail + len(b"startxref"))
    v2, t2 = _parse_pdf_int(full, t2)
    if v2 is None or v2 != xref_pos:
        return "malformed_content:pdf_startxref_invalid"
    t3 = _skip_pdf_ws(full, t2)
    if full[t3:t3 + 5] != b"%%EOF":
        return "malformed_content:pdf_eof_after_startxref"
    return ""


def _validate_json_structure(body: bytes) -> str:
    """完整内容严格 UTF-8 解码 + 完整 JSON 解析：前导字符正确但语法错误、
    尾随垃圾或截断均失败（B1 §3.1.4）。"""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return "malformed_content:json_encoding"
    try:
        json.loads(text)
    except (ValueError, RecursionError):
        return "malformed_content:json_parse"
    return ""


def _validate_image_structure(full: bytes, expected_format: str) -> str:
    """确定性图像结构验证（Pillow）：verify() + 重新打开完整解码 load()——
    异常、缺少 decoder 或无法确认时一律失败（B1 §3.1.7，fail-closed）。
    **P4-F 解码上界**：width/height 有界（≤ MAX_IMAGE_DIMENSION）、解码像素
    数有界（≤ MAX_IMAGE_PIXELS），超限在 load() 前拒绝（解压炸弹绝不实际
    解码）；load() 期间 Pillow DecompressionBombWarning 升级为异常 → 同样
    fail-closed。"""
    try:
        import io
        import warnings

        from PIL import Image
    except Exception:      # decoder 缺失 → 无法确认 → fail-closed
        return "malformed_content:image_verifier_unavailable"
    try:
        with Image.open(io.BytesIO(full)) as im:
            if (im.format or "") != expected_format:
                return "malformed_content:image_structure"
            # P4-F：解码前（load() 前）的尺寸/像素上界——头部声明超大尺寸的
            # 解压炸弹在验证阶段即被拒绝，绝不进入解码。
            w, h = im.size
            if w <= 0 or h <= 0 or w > MAX_IMAGE_DIMENSION or h > MAX_IMAGE_DIMENSION:
                return "malformed_content:image_dimension"
            if w * h > MAX_IMAGE_PIXELS:
                return "malformed_content:image_pixels"
            im.verify()
        with Image.open(io.BytesIO(full)) as im2:
            w2, h2 = im2.size
            if w2 <= 0 or h2 <= 0 or w2 > MAX_IMAGE_DIMENSION \
                    or h2 > MAX_IMAGE_DIMENSION or w2 * h2 > MAX_IMAGE_PIXELS:
                return "malformed_content:image_pixels"
            with warnings.catch_warnings():
                # P4-F：DecompressionBombWarning 升级为异常 → FAIL（绝不
                # best-effort 解码继续）。
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                im2.load()
    except Exception:
        return "malformed_content:image_structure"
    return ""


def full_content_verdict(full: bytes) -> Tuple[str, str]:
    """**完整有界内容**（≤ MAX_ARTIFACT_BYTES，来自同一稳定快照）的 MIME
    识别与结构验证（blocker B1）：

    - 空内容 → ``("", "empty_artifact")``——空文件绝不是有效 artifact；
    - PNG/JPEG：魔数必须在偏移 0 + Pillow 结构验证（截断/畸形失败）；
    - PDF：``%PDF-`` 必须位于偏移 0 的合法起始位置（任意窗口中出现 marker
      不构成 PDF）+ **封闭结构验证**（header/对象/xref/startxref/trailer/
      EOF 与偏移关系，见 :func:`_validate_pdf_structure`——伪 PDF、截断
      xref、错误 startxref 一律 fail-closed）；
    - JSON：BOM 容忍 + 严格 UTF-8 + **完整** json.loads（尾随垃圾/截断失败）；
    - text：**完整**内容无 NUL 且严格 UTF-8 可解码——后半段 NUL/非法
      UTF-8/二进制不得被前 1 KiB 掩盖；
    - 其余 → application/octet-stream（二进制，只能被显式接受）。

    返回 ``(content_mime, rejection)``；rejection ∈ {"", "empty_artifact",
    "malformed_content:..."}。
    """
    if not isinstance(full, (bytes, bytearray)) or not full:
        return "", "empty_artifact"
    full = bytes(full)
    if full[:8] == _PNG_MAGIC:
        return "image/png", _validate_image_structure(full, "PNG")
    if full[:3] == _JPEG_MAGIC:
        return "image/jpeg", _validate_image_structure(full, "JPEG")
    if full[:5] == _PDF_MAGIC:
        return "application/pdf", _validate_pdf_structure(full)
    body = full[3:] if full.startswith(b"\xef\xbb\xbf") else full
    if body.lstrip(_JSON_LEAD_BYTES)[:1] in (b"{", b"["):
        return "application/json", _validate_json_structure(body)
    if b"\x00" not in full:
        try:
            full.decode("utf-8")
            return "text/plain", ""
        except UnicodeDecodeError:
            pass
    return "application/octet-stream", ""


def declared_mime_consistent(declared: str, observed: str) -> bool:
    """声明/命名 MIME 与内容观察的一致性判定（exact + 文本族窄例外）。

    内容级识别只能判到 text/plain——markdown/csv/html 是命名层语义，因此
    ``observed=text/plain`` 时接受文本族声明；其余一律精确相等
    （image/png 内容 + 声明 image/jpeg → False——精确相等拦截同族冒充）。
    """
    if declared == observed:
        return True
    return observed == "text/plain" and declared in (
        "text/plain", "text/markdown", "text/csv", "text/html")


# ---------------------------------------------------------------------------
# 证据提交 exact-schema 键集（16F 任务书 关键锁定 4）
# ---------------------------------------------------------------------------

#: verifier.verify(input) 顶层键集（精确：缺一不可、多一即拒）。
VERIFICATION_INPUT_KEYS = ("backend_id", "declared_artifacts", "run_id", "terminal_events")

#: 终态事件 claim 的精确键集（身份绑定四元组缺一不可——不绑定到本 run/contract/
#: backend 的 claim 一律不参与裁定）。
TERMINAL_CLAIM_KEYS = (
    "backend_id", "contract_id", "event_id", "kind", "observed_at_epoch", "run_id",
)

#: backend 声明的 artifact claim 精确键集；declared_* 为 None 表示"未声明"
#: （声明值只是 claim，本地观察才是真值，矛盾即篡改）。
ARTIFACT_CLAIM_KEYS = (
    "artifact_id", "declared_mime", "declared_sha256", "declared_size_bytes", "path",
)


# ---------------------------------------------------------------------------
# 秘密脱敏（进入报告/诊断的文本一律先经此处理；秘密不存储/不哈希/不导出）
# ---------------------------------------------------------------------------

_SECRET_KV_RE = re.compile(
    # lookbehind 只排除 [a-z0-9]（blocker B6）：合法身份分隔符 _/./-/: 前缀的
    # 秘密键（run_password: / x.api_key= / prefix-client_secret:）同样必须命中；
    # 仅当键紧贴字母/数字内部（keyword=x 的 "key" 类误报）才不触发。
    # **P4-E：值匹配到真实分隔符为止（+/* 而非 {0,512}）**——600 字符秘密的
    # 尾部不得因量词截断而泄漏；输出限长由调用方（_bounded_text / [:N]）完成。
    r"(?i)(?<![a-z0-9])(password|passwd|secret|token|api[_\-]?key|access[_\-]?key|"
    r"private[_\-]?key|client[_\-]?secret|authorization)(\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s;,&()\[\]{}]+)")
_SECRET_SCHEME_RE = re.compile(
    # P4-E：scheme token 同样匹配至真实分隔符（+ 而非 {1,512}）。
    r"(?i)(?<![a-z0-9_])(bearer|basic|digest)\s+([^\s\"'{}\[\]();,]+)")


def scrub_secrets(text: str) -> str:
    """秘密值形态脱敏（键值对 / bearer 等授权头形态 → [REDACTED]），其余原样。

    授权头形态**先**于键值对处理：`authorization: Bearer xyz` 若先被 KV 规则
    以 "Bearer" 为值整体替换，尾部 token 值将泄漏；先处理 scheme 才能完整覆盖。
    """
    if not isinstance(text, str) or not text:
        return ""
    t = _SECRET_SCHEME_RE.sub(lambda m: m.group(1) + " [REDACTED]", text)
    t = _SECRET_KV_RE.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", t)
    return t


def _bounded_text(text: str, cap: int) -> str:
    s = scrub_secrets(text)
    if len(s) > cap:
        return s[:cap] + "…<truncated>"
    return s


def validate_identity(value: Any, field_name: str) -> str:
    """身份字段 lexical contract（canonical identity，blocker B6 唯一入口）：

    - 显式词法：``^[A-Za-z0-9][A-Za-z0-9._:\\-]{0,127}$``——控制字符、首尾
      空白、非法字符全部拒绝，**绝不静默 trim / normalize 后重新绑定**；
    - 秘密形态（password:x / token=y / bearer …，含 ``_``/``.``/``-``/``:`` 分隔
      前缀）即使词法合法也拒绝（两个不同秘密值清洗成同一身份会造成歧义 →
      fail-closed，零报告零 seal）；
    - 身份比较一律 exact，不做大小写折叠或空白归一；
    - **异常消息不含 raw value**：回显一律先脱敏并限长——原始秘密不得进入
      异常/诊断（scrubber 与 identity rejector 共享同一秘密边界）。
    """
    if not isinstance(value, str):
        raise VerificationInputError(
            f"{field_name} 必须是 str（canonical identity），得到 {type(value).__name__}")
    if not _RUN_ID_PATTERN.match(value):
        raise VerificationInputError(
            f"{field_name} 词法非法（控制字符/首尾空白/非法字符拒绝，不静默 trim）: "
            f"{scrub_secrets(value)[:64]!r}")
    if scrub_secrets(value) != value:
        raise VerificationInputError(
            f"{field_name} 带秘密形态（fail-closed）: {scrub_secrets(value)[:64]!r}")
    return value


# ---------------------------------------------------------------------------
# 证据观察（verifier 本地构建；字段全部为本地真值或 claim 处置结果）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TerminalObservation:
    """归一化终态事件引用（**claim**：仅用于绑定被验证的 run，不构成任何证明）。"""

    event_id: str
    kind: str
    observed_at_epoch: float
    #: 身份绑定（run_id/contract_id/backend_id 与本 verifier 绑定值一致且 kind
    #: 属 16E TERMINAL_KINDS）——未绑定的 claim 不参与裁定。
    bound: bool

    def __post_init__(self) -> None:
        # P6-C：公开模型按**真实运行时类型**逐字段封闭——observed_at_epoch 必须
        # 是有限数值（bool 拒绝）、bound 必须是严格 bool。
        if isinstance(self.observed_at_epoch, bool) \
                or not isinstance(self.observed_at_epoch, (int, float)) \
                or not math.isfinite(float(self.observed_at_epoch)):
            raise VerificationError("observed_at_epoch 必须是有限数值（bool 拒绝）")
        if not isinstance(self.bound, bool):
            raise VerificationError("bound 必须是严格 bool")
        # Patch 3 B5：公开模型身份字段同样走 canonical validate_identity——
        # 秘密形态/词法非法直接拒绝，绝不清洗后继续作为身份。
        object.__setattr__(self, "event_id",
                           validate_identity(self.event_id, "event_id"))
        # P4-E：kind 是公开导出字符串——16E EventKind 封闭词表，类型封闭；
        # 词表外值（含秘密形态）构造面直接拒绝，绝不脱敏后继续导出。
        if not isinstance(self.kind, str) or self.kind not in EVENT_KIND_VALUES:
            raise VerificationError(
                f"kind 必须是 16E 封闭词表值，得到 "
                f"{scrub_secrets(str(self.kind))[:64]!r}")


@dataclass(frozen=True)
class ArtifactObservation:
    """单个 artifact 路径的本地观察（句柄锚定归属 + 大小 + MIME + SHA-256）。

    ``observed_mime`` 是**完整内容**识别真值（:func:`full_content_verdict`，
    基于同一稳定快照的全部有界字节）；``content_rejection`` 是完整内容结构
    验证的拒绝原因（``empty_artifact`` / ``malformed_content:...``）；``name_mime``
    是命名层交叉核对值（:func:`mime_for_suffix`，未知后缀 ""）。
    路径记录面在构造时统一脱敏（解析层已拒绝秘密形态路径——纵深防御）。
    """

    source: str                      # "expectation" | "declared"
    artifact_id: str
    claimed_path: str
    resolved_path: str               # 句柄派生真实目标（GetFinalPathNameByHandle /
                                     # /proc/self/fd / F_GETPATH；覆盖链接与最近现存祖先）
    target_exists: bool
    is_regular_file: bool
    within_workspace: bool
    size_bytes: Optional[int]
    observed_mime: str               # 完整内容识别；不可观察时为 ""
    observed_sha256: str             # 不可计算时为 ""
    rejection: str                   # "" | missing | path_escape | not_regular_file | oversize | unreadable | mutated | handle_target_unprovable
    name_mime: str = ""              # 命名层 MIME；未知扩展名为 ""
    content_rejection: str = ""      # 完整内容结构验证拒绝（""=通过）

    def __post_init__(self) -> None:
        # P6-C：公开模型按**真实运行时类型**逐字段封闭——声明为字符串的字段
        # 先验证确为 str（绝不把非 str 静默变成 ""）；bool 字段严格 bool；
        # size_bytes 必须是 None 或非负 int（bool 拒绝）。异常回显只带类型名，
        # 绝不回显字段值（raw secret 零回显）。
        for _name in ("claimed_path", "resolved_path", "rejection", "name_mime",
                      "content_rejection"):
            if not isinstance(getattr(self, _name), str):
                raise VerificationError(
                    f"{_name} 必须是 str，得到 {type(getattr(self, _name)).__name__}")
        if not isinstance(self.observed_mime, str):
            raise VerificationError(
                f"observed_mime 必须是 str，得到 {type(self.observed_mime).__name__}")
        if not isinstance(self.target_exists, bool) \
                or not isinstance(self.is_regular_file, bool) \
                or not isinstance(self.within_workspace, bool):
            raise VerificationError(
                "target_exists/is_regular_file/within_workspace 必须是严格 bool")
        if self.size_bytes is not None \
                and (isinstance(self.size_bytes, bool)
                     or not isinstance(self.size_bytes, int) or self.size_bytes < 0):
            raise VerificationError("size_bytes 必须是 None 或非负 int（bool 拒绝）")
        # Patch 3 B5：artifact_id 也是公开身份字段——canonical 拒绝秘密形态，
        # 绝不清洗后继续作为身份；路径记录面统一脱敏（解析层已拒绝秘密形态
        # 路径——纵深防御）。
        object.__setattr__(self, "artifact_id",
                           validate_identity(self.artifact_id, "artifact_id"))
        # P5-C：observed_mime 是严格格式值——封闭 MIME 词表（完整内容识别
        # 真值只可能来自 full_content_verdict 的封闭输出集），词表外值（含
        # 秘密形态）构造面直接拒绝，绝不脱敏后继续导出。
        if self.observed_mime != "" and self.observed_mime not in SUPPORTED_MIME_TYPES:
            raise VerificationError(
                f"observed_mime 必须是封闭 MIME 词表值或空，得到 "
                f"{scrub_secrets(str(self.observed_mime))[:64]!r}")
        # P5-C：observed_sha256 是严格格式值——空或 64 位小写 hex。
        if self.observed_sha256 != "" \
                and (not isinstance(self.observed_sha256, str)
                     or not _SHA256_PATTERN.match(self.observed_sha256)):
            raise VerificationError(
                f"observed_sha256 必须是空或 64 位小写 hex，得到 "
                f"{scrub_secrets(str(self.observed_sha256))[:64]!r}")
        object.__setattr__(self, "claimed_path",
                           scrub_secrets(self.claimed_path)[:MAX_PATH_CHARS])
        object.__setattr__(self, "resolved_path",
                           scrub_secrets(self.resolved_path)[:MAX_PATH_CHARS])
        # P4-E：公开导出字符串类型封闭或脱敏——source 是封闭取值（expectation|
        # declared，词表外值直接拒绝）；rejection / name_mime / content_rejection
        # 统一脱敏后限长（raw secret 绝不进入 to_dict()/to_digest_dict() 导出）。
        if not isinstance(self.source, str) or self.source not in ARTIFACT_SOURCE_VALUES:
            raise VerificationError(
                f"source 必须是 expectation|declared（类型封闭），得到 "
                f"{scrub_secrets(str(self.source))[:64]!r}")
        object.__setattr__(self, "rejection",
                           scrub_secrets(self.rejection)[:64])
        object.__setattr__(self, "name_mime",
                           scrub_secrets(self.name_mime)[:128])
        object.__setattr__(self, "content_rejection",
                           scrub_secrets(self.content_rejection)[:128])


@dataclass(frozen=True)
class EvidenceBundle:
    """有界不可变证据观察集 + 规范化 evidence_digest（不含任何文件内容字节）。"""

    contract_id: str
    contract_hash: str
    run_id: str
    backend_id: str
    terminal: Tuple[TerminalObservation, ...]
    artifacts: Tuple[ArtifactObservation, ...]
    diagnostics: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # P6-C：公开模型按**真实运行时类型**逐字段封闭——容器字段必须是
        # tuple（向容器字段注入标量/字符串绝不静默拆解或通过）。
        if not isinstance(self.terminal, tuple) or not isinstance(self.artifacts, tuple) \
                or not isinstance(self.diagnostics, tuple):
            raise VerificationError("evidence 容器字段必须是 tuple（封闭导出树）")
        if len(self.terminal) > MAX_EVIDENCE_EVENTS:
            raise VerificationError("evidence 终态事件数量超界")
        if len(self.artifacts) > MAX_DECLARED_ARTIFACTS:
            raise VerificationError("evidence artifact 观察数量超界")
        if len(self.diagnostics) > MAX_DIAGNOSTICS:
            raise VerificationError("evidence 诊断数量超界")
        # P5-C：封闭导出树——contract_hash 是严格格式值（64 位小写 hex），
        # 元素类型封闭（TerminalObservation/ArtifactObservation），诊断面
        # 必须全为 str；任何词表外/格式外值构造面直接拒绝。
        if not isinstance(self.contract_hash, str) \
                or not _SHA256_PATTERN.match(self.contract_hash):
            raise VerificationError("contract_hash 必须是 64 位小写 hex")
        if not all(isinstance(t, TerminalObservation) for t in self.terminal) \
                or not all(isinstance(a, ArtifactObservation) for a in self.artifacts):
            raise VerificationError("evidence 元素类型非法（封闭导出树）")
        if not all(isinstance(d, str) for d in self.diagnostics):
            raise VerificationError("diagnostics 必须全为 str（封闭导出树）")
        # Patch 3 B5：公开模型身份字段走 canonical validate_identity——秘密
        # 形态/词法非法直接拒绝（绝不清洗后继续作为身份），raw secret 不可能
        # 进入 evidence digest payload / 报告导出。
        object.__setattr__(self, "contract_id",
                           validate_identity(self.contract_id, "contract_id"))
        object.__setattr__(self, "run_id", validate_identity(self.run_id, "run_id"))
        object.__setattr__(self, "backend_id",
                           validate_identity(self.backend_id, "backend_id"))
        # 诊断字符串面统一脱敏（秘密形态不得进入 evidence digest payload / 导出）
        object.__setattr__(self, "diagnostics", tuple(
            scrub_secrets(d)[:MAX_DIAGNOSTIC_CHARS] for d in self.diagnostics))

    # -- digest ---------------------------------------------------------------

    def to_digest_dict(self) -> Dict[str, Any]:
        """规范化（可 JSON、无内容字节）观察树——evidence_digest 的唯一载荷。"""
        return {
            "backend_id": self.backend_id[:MAX_ID_CHARS],
            "contract_hash": self.contract_hash,
            "run_id": self.run_id[:MAX_ID_CHARS],
            "artifacts": [
                {
                    "artifact_id": a.artifact_id[:MAX_ID_CHARS],
                    "claimed_path": a.claimed_path[:MAX_PATH_CHARS],
                    "content_rejection": a.content_rejection[:64],
                    "is_regular_file": a.is_regular_file,
                    "name_mime": a.name_mime[:128],
                    "observed_mime": a.observed_mime[:128],
                    "observed_sha256": a.observed_sha256,
                    "rejected": a.rejection[:64],
                    "resolved_path": a.resolved_path[:MAX_PATH_CHARS],
                    "size_bytes": a.size_bytes,
                    "source": a.source[:16],
                    "target_exists": a.target_exists,
                    "within_workspace": a.within_workspace,
                }
                for a in self.artifacts
            ],
            "terminal": [
                {
                    "bound": t.bound,
                    "event_id": t.event_id[:MAX_ID_CHARS],
                    "kind": t.kind[:64],
                    "observed_at_epoch": t.observed_at_epoch,
                }
                for t in self.terminal
            ],
        }

    def digest_payload(self) -> str:
        return json.dumps(self.to_digest_dict(), sort_keys=True, ensure_ascii=True,
                          allow_nan=False, separators=(",", ":"))

    def evidence_digest(self) -> str:
        return hashlib.sha256(self.digest_payload().encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """全新 plain dict 导出（与 self 零共享可变引用）。"""
        return {
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "run_id": self.run_id,
            "backend_id": self.backend_id,
            "terminal": [{
                "event_id": t.event_id, "kind": t.kind,
                "observed_at_epoch": t.observed_at_epoch, "bound": t.bound,
            } for t in self.terminal],
            "artifacts": [{
                "source": a.source, "artifact_id": a.artifact_id,
                "claimed_path": a.claimed_path, "resolved_path": a.resolved_path,
                "target_exists": a.target_exists, "is_regular_file": a.is_regular_file,
                "within_workspace": a.within_workspace, "size_bytes": a.size_bytes,
                "observed_mime": a.observed_mime, "name_mime": a.name_mime,
                "observed_sha256": a.observed_sha256,
                "rejection": a.rejection,
                "content_rejection": a.content_rejection,
            } for a in self.artifacts],
            "diagnostics": list(self.diagnostics),
            "evidence_digest": self.evidence_digest(),
        }


# ---------------------------------------------------------------------------
# VerificationCheck
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerificationCheck:
    """单条确定性检查结果（checker id 确定性、输入冻结、解释脱敏限长）。"""

    check_id: str
    kind: str
    required: bool
    result: CheckResult
    explanation: str = ""
    inputs: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        # P5-C：check_id 与 kind 都是公开导出字符串——canonical identity 词法
        # contract + 秘密形态拒绝（构造面直接拒绝，绝不脱敏后继续导出）。
        cid = validate_identity(self.check_id, "check_id")
        if len(cid) > MAX_ID_CHARS:
            raise VerificationError(f"check_id 超界 {MAX_ID_CHARS}")
        object.__setattr__(self, "check_id", cid)
        kind = validate_identity(self.kind, "check kind")
        if len(kind) > 64:
            raise VerificationError("check kind 超界 64")
        object.__setattr__(self, "kind", kind)
        # P6-C：真实运行时类型逐字段封闭——required 严格 bool、explanation
        # 确为 str、inputs 是 (str, str) 二元组的 tuple；result 的枚举字符串
        # 转换错误（ValueError 回显 raw value）必须捕获并脱敏。
        if not isinstance(self.required, bool):
            raise VerificationError(f"check {cid} required 必须是严格 bool")
        if not isinstance(self.explanation, str):
            raise VerificationError(
                f"check {cid} explanation 必须是 str，得到 "
                f"{type(self.explanation).__name__}")
        result = self.result
        if isinstance(result, str):
            try:
                result = CheckResult(result)
            except ValueError:
                raise VerificationError(
                    f"check {cid} result 非法: "
                    f"{scrub_secrets(str(self.result))[:64]!r}") from None
        if not isinstance(result, CheckResult):
            raise VerificationError(
                f"check {cid} result 非法: {scrub_secrets(str(self.result))[:64]!r}")
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "explanation", _bounded_text(self.explanation or "",
                                                              MAX_EXPLANATION_CHARS))
        if not isinstance(self.inputs, tuple):
            raise VerificationError(f"check {cid} inputs 必须是 tuple")
        frozen_inputs = []
        for pair in self.inputs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise VerificationError(
                    f"check {cid} input 必须是 (键, 值) 二元组")
            k, v = pair
            if not isinstance(k, str) or not k.strip() or len(k) > 64:
                # P5-C：异常回显一律先脱敏——raw secret 绝不进入异常消息。
                raise VerificationError(
                    f"check {cid} input 键非法: {scrub_secrets(str(k))[:64]!r}")
            # P5-C：input 键同样是公开导出字符串——canonical 词法 + 秘密形态
            # 拒绝（值面经 _bounded_text 脱敏限长）。
            validate_identity(k, f"check {cid} input 键")
            if not isinstance(v, str):
                v = str(v)
            frozen_inputs.append((k, _bounded_text(v, MAX_INPUT_VALUE_CHARS)))
        object.__setattr__(self, "inputs", tuple(frozen_inputs))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id, "kind": self.kind, "required": self.required,
            "result": self.result.value, "explanation": self.explanation,
            "inputs": [[k, v] for k, v in self.inputs],
        }


# ---------------------------------------------------------------------------
# VerificationReport + 权威密封
# ---------------------------------------------------------------------------


def compute_report_digest(*, report_id: str, verifier_id: str, contract_id: str,
                          contract_hash: str, standard_hash: str, run_id: str,
                          backend_id: str, verdict: VerificationVerdict,
                          checks: Tuple[VerificationCheck, ...],
                          diagnostics: Tuple[str, ...], evidence_digest: str,
                          started_at_epoch: float, finished_at_epoch: float) -> str:
    """报告规范摘要：SHA-256 over canonical JSON（sort_keys / 紧凑 / ASCII / 严格域）。

    纯函数 —— verifier 在构造报告前用同一输入调用得到 digest 并据此签发 seal，
    ``VerificationReport.__post_init__`` 用自身字段重算；两侧必须一致。
    """
    payload = {
        "report_id": report_id,
        "verifier_id": verifier_id,
        "contract_id": contract_id,
        "contract_hash": contract_hash,
        "standard_hash": standard_hash,
        "run_id": run_id,
        "backend_id": backend_id,
        "verdict": verdict.value if isinstance(verdict, VerificationVerdict) else str(verdict),
        "checks": [c.to_dict() for c in checks],
        "diagnostics": list(diagnostics),
        "evidence_digest": evidence_digest,
        "started_at_epoch": started_at_epoch,
        "finished_at_epoch": finished_at_epoch,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VerificationReport:
    """一次独立校验的不可变报告。

    - verdict=VERIFIED 必须携带 64-hex ``authority_seal`` 且 verifier_id 为 16F
      唯一身份；非 VERIFIED 报告一律空 seal。seal 的**真实性**只能经签发方
      ``IndependentVerifier.seal_is_authentic`` 复核——本构造面只做格式锁定。
    - ``report_digest`` 由 __post_init__ 按自身字段重算（seal 签发对象）。
    - 报告不可变且导出（:meth:`to_dict`/:meth:`to_json`）每次构造全新对象图，
      与内部零共享可变引用。
    """

    report_id: str
    verifier_id: str
    contract_id: str
    contract_hash: str
    standard_hash: str
    run_id: str
    backend_id: str
    verdict: VerificationVerdict
    checks: Tuple[VerificationCheck, ...]
    diagnostics: Tuple[str, ...]
    evidence: EvidenceBundle
    started_at_epoch: float
    finished_at_epoch: float
    authority_seal: str = ""
    report_digest: str = ""

    # -------------------------------------------------- 校验
    def __post_init__(self) -> None:
        # P6-C：report_id 拒绝异常回显先脱敏——raw secret 绝不进入异常消息。
        if not isinstance(self.report_id, str) \
                or not _REPORT_ID_PATTERN.match(self.report_id):
            raise VerificationError(
                f"report_id 词法非法: {scrub_secrets(str(self.report_id))[:64]!r}")
        # P4-E：verifier_id 同样走 canonical validate_identity——秘密形态/
        # 词法非法（含 600 字符长秘密值）构造面直接拒绝，绝不脱敏后继续导出。
        if not isinstance(self.verifier_id, str):
            raise VerificationError(
                f"verifier_id 必须是 str（canonical identity），得到 "
                f"{type(self.verifier_id).__name__}")
        validate_identity(self.verifier_id, "verifier_id")
        # Patch 3 B5：公开身份字段（contract_id/run_id/backend_id）走 canonical
        # validate_identity——秘密形态直接拒绝，to_dict()/to_json() 因此不可能
        # 导出 raw secret 身份；绝不清洗秘密后继续作为身份。
        validate_identity(self.contract_id, "contract_id")
        validate_identity(self.run_id, "run_id")
        validate_identity(self.backend_id, "backend_id")
        for name in ("contract_hash", "standard_hash"):
            v = getattr(self, name)
            if not isinstance(v, str) or not _SHA256_PATTERN.match(v):
                raise VerificationError(f"{name} 必须是 64 位小写 hex")
        verdict = self.verdict
        if isinstance(verdict, str):
            # P6-C：枚举字符串转换错误（ValueError 回显 raw value）必须捕获
            # 并脱敏——raw secret 绝不进入异常消息。
            try:
                verdict = VerificationVerdict(verdict)
            except ValueError:
                raise VerificationError(
                    f"verdict 非法: {scrub_secrets(str(self.verdict))[:64]!r}") from None
        if not isinstance(verdict, VerificationVerdict):
            raise VerificationError(
                f"verdict 非法: {scrub_secrets(str(self.verdict))[:64]!r}")
        object.__setattr__(self, "verdict", verdict)

        # P6-C：真实运行时类型逐字段封闭——checks/diagnostics 容器类型与元素
        # 类型构造面拒绝（绝不静默丢弃或拆解非 str 诊断）。
        if not isinstance(self.checks, (tuple, list)):
            raise VerificationError("checks 必须是 tuple/list（封闭导出树）")
        checks = tuple(self.checks)
        if not all(isinstance(c, VerificationCheck) for c in checks):
            raise VerificationError("checks 必须全部是 VerificationCheck")
        if len(checks) > MAX_REPORT_CHECKS:
            raise VerificationError("报告检查数量超界")
        object.__setattr__(self, "checks", checks)
        if not isinstance(self.diagnostics, (tuple, list)):
            raise VerificationError("diagnostics 必须是 tuple/list（封闭导出树）")
        if not all(isinstance(d, str) for d in self.diagnostics):
            raise VerificationError("diagnostics 必须全为 str（封闭导出树）")
        diags = tuple(_bounded_text(d, MAX_DIAGNOSTIC_CHARS) for d in self.diagnostics
                      if d.strip())
        if len(diags) > MAX_DIAGNOSTICS:
            diags = diags[:MAX_DIAGNOSTICS]
        object.__setattr__(self, "diagnostics", diags)

        if not isinstance(self.evidence, EvidenceBundle):
            raise VerificationError("evidence 必须是 EvidenceBundle")
        if self.evidence.contract_id != self.contract_id \
                or self.evidence.contract_hash != self.contract_hash \
                or self.evidence.run_id != self.run_id:
            raise VerificationError("evidence 身份与报告身份不一致")
        evidence_digest = self.evidence.evidence_digest()

        for name in ("started_at_epoch", "finished_at_epoch"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not math.isfinite(float(v)):
                raise VerificationError(f"{name} 必须是有限数值")
        if float(self.started_at_epoch) > float(self.finished_at_epoch):
            raise VerificationError("报告时序非法：started > finished")
        object.__setattr__(self, "started_at_epoch", float(self.started_at_epoch))
        object.__setattr__(self, "finished_at_epoch", float(self.finished_at_epoch))

        digest = compute_report_digest(
            report_id=self.report_id, verifier_id=self.verifier_id,
            contract_id=self.contract_id, contract_hash=self.contract_hash,
            standard_hash=self.standard_hash, run_id=self.run_id,
            backend_id=self.backend_id, verdict=verdict, checks=checks,
            diagnostics=diags, evidence_digest=evidence_digest,
            started_at_epoch=float(self.started_at_epoch),
            finished_at_epoch=float(self.finished_at_epoch),
        )
        object.__setattr__(self, "report_digest", digest)

        if verdict is VerificationVerdict.VERIFIED:
            if self.verifier_id != VERIFIER_ID:
                raise VerificationAuthorityError(
                    "VERIFIED 报告只能由 16F 独立验证器产生")
            if not isinstance(self.authority_seal, str) \
                    or not _SHA256_PATTERN.match(self.authority_seal):
                raise VerificationAuthorityError(
                    "VERIFIED 报告必须携带 64-hex authority_seal（无 seal 的 VERIFIED "
                    "一律拒绝构造）")
        else:
            if self.authority_seal:
                raise VerificationAuthorityError(
                    "非 VERIFIED 报告不得携带 authority_seal")

    # -------------------------------------------------- 导出（零共享引用）
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "verifier_id": self.verifier_id,
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "standard_hash": self.standard_hash,
            "run_id": self.run_id,
            "backend_id": self.backend_id,
            "verdict": self.verdict.value,
            "checks": [c.to_dict() for c in self.checks],
            "diagnostics": list(self.diagnostics),
            "evidence": self.evidence.to_dict(),
            "started_at_epoch": self.started_at_epoch,
            "finished_at_epoch": self.finished_at_epoch,
            "authority_seal": self.authority_seal,
            "report_digest": self.report_digest,
        }

    def to_json(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False,
                          allow_nan=False, separators=(",", ":"))
        if len(blob.encode("utf-8")) > MAX_REPORT_JSON_BYTES:
            raise VerificationError("报告 JSON 超界（构造面有界约束被破坏）")
        return blob


__all__ = [
    "ARTIFACT_CLAIM_KEYS",
    "ARTIFACT_SOURCE_VALUES",
    "ARTIFACT_TYPE_CONTENT_RULES",
    "ArtifactObservation",
    "CheckResult",
    "DEFAULT_PROCESS_TIMEOUT_SECONDS",
    "EVENT_KIND_VALUES",
    "EvidenceBundle",
    "MAX_ARTIFACT_BYTES",
    "MAX_DECLARED_ARTIFACTS",
    "MAX_DIAGNOSTICS",
    "MAX_EVIDENCE_EVENTS",
    "MAX_EXPLANATION_CHARS",
    "MAX_IMAGE_DIMENSION",
    "MAX_IMAGE_PIXELS",
    "MAX_REPORT_CHECKS",
    "MAX_REPORT_JSON_BYTES",
    "MAX_SNAPSHOT_TOTAL_BYTES",
    "MAX_TEXT_READ_BYTES",
    "MIME_SNIFF_WINDOW",
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
    "mime_for_suffix",
    "sniff_content_mime",
    "scrub_secrets",
    "validate_identity",
]
