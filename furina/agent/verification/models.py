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
  魔数 + Pillow 结构验证、PDF 偏移 0 + 封闭结构、JSON/text 完整有界解析、
  二进制显式接受；空/畸形/截断一律 fail-closed），扩展名只是命名层交叉核对；
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

from furina.core import FurinaError

# ---------------------------------------------------------------------------
# 身份 / 词表
# ---------------------------------------------------------------------------

#: 16F 独立验证器唯一身份（VerificationStandard.verifier_refs 仅接受本 id 时才可判 PASS）。
VERIFIER_ID = "furina.verifier.16f.independent"

_REPORT_ID_PATTERN = re.compile(r"^vrp_[0-9a-f]{32}$")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")   # 与 16B run_id 同形
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CHECK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")


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

_PDF_HEADER_RE = re.compile(rb"%PDF-\d+\.\d+")


def _validate_pdf_structure(full: bytes) -> str:
    """封闭、确定性的受支持 PDF 结构：``%PDF-`` 位于偏移 0 + 版本号 +
    尾部 1 KiB 内存在 ``%%EOF``。截断/缺 EOF/前导垃圾一律 fail-closed。"""
    if not _PDF_HEADER_RE.match(full[:32]) or b"%%EOF" not in full[-1024:]:
        return "malformed_content:pdf_structure"
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
    异常、缺少 decoder 或无法确认时一律失败（B1 §3.1.7，fail-closed）。"""
    try:
        import io

        from PIL import Image
    except Exception:      # decoder 缺失 → 无法确认 → fail-closed
        return "malformed_content:image_verifier_unavailable"
    try:
        with Image.open(io.BytesIO(full)) as im:
            if (im.format or "") != expected_format:
                return "malformed_content:image_structure"
            im.verify()
        with Image.open(io.BytesIO(full)) as im2:
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
      不构成 PDF）+ 封闭受支持结构（版本 + 尾部 ``%%EOF``）；
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
    r"(?i)(?<![a-z0-9])(password|passwd|secret|token|api[_\-]?key|access[_\-]?key|"
    r"private[_\-]?key|client[_\-]?secret|authorization)(\s*[=:]\s*)"
    r"(\"[^\"]{0,512}\"|'[^']{0,512}'|[^\s;,&()\[\]{}]{1,512})")
_SECRET_SCHEME_RE = re.compile(
    r"(?i)(?<![a-z0-9_])(bearer|basic|digest)\s+([^\s\"'{}\[\]();,]{1,512})")


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
        object.__setattr__(self, "claimed_path", scrub_secrets(self.claimed_path))
        object.__setattr__(self, "resolved_path", scrub_secrets(self.resolved_path))


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
        if len(self.terminal) > MAX_EVIDENCE_EVENTS:
            raise VerificationError("evidence 终态事件数量超界")
        if len(self.artifacts) > MAX_DECLARED_ARTIFACTS:
            raise VerificationError("evidence artifact 观察数量超界")
        if len(self.diagnostics) > MAX_DIAGNOSTICS:
            raise VerificationError("evidence 诊断数量超界")
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
        cid = self.check_id
        if not isinstance(cid, str) or not cid.strip() or len(cid) > MAX_ID_CHARS \
                or not _CHECK_ID_PATTERN.match(cid):
            raise VerificationError(f"check_id 词法非法: {cid!r}")
        kind = self.kind
        if not isinstance(kind, str) or not kind.strip() or len(kind) > 64:
            raise VerificationError(f"check kind 非法: {kind!r}")
        if not isinstance(self.required, bool):
            raise VerificationError(f"check {cid} required 必须是严格 bool")
        result = self.result
        if isinstance(result, str):
            result = CheckResult(result)
        if not isinstance(result, CheckResult):
            raise VerificationError(f"check {cid} result 非法: {self.result!r}")
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "explanation", _bounded_text(self.explanation or "",
                                                              MAX_EXPLANATION_CHARS))
        frozen_inputs = []
        for pair in self.inputs:
            k, v = pair
            if not isinstance(k, str) or not k.strip() or len(k) > 64:
                raise VerificationError(f"check {cid} input 键非法: {k!r}")
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
        if not isinstance(self.report_id, str) or not _REPORT_ID_PATTERN.match(self.report_id):
            raise VerificationError(f"report_id 词法非法: {self.report_id!r}")
        if not isinstance(self.verifier_id, str) or not self.verifier_id.strip() \
                or len(self.verifier_id) > MAX_ID_CHARS:
            raise VerificationError("verifier_id 必须是非空 str")
        if not isinstance(self.contract_id, str) or not self.contract_id.strip():
            raise VerificationError("contract_id 必须是非空 str")
        for name in ("contract_hash", "standard_hash"):
            v = getattr(self, name)
            if not isinstance(v, str) or not _SHA256_PATTERN.match(v):
                raise VerificationError(f"{name} 必须是 64 位小写 hex")
        if not isinstance(self.run_id, str) or not _RUN_ID_PATTERN.match(self.run_id):
            raise VerificationError(f"run_id 词法非法: {self.run_id!r}")
        if not isinstance(self.backend_id, str) or not self.backend_id.strip() \
                or len(self.backend_id) > MAX_ID_CHARS:
            raise VerificationError("backend_id 必须是非空 str")
        verdict = self.verdict
        if isinstance(verdict, str):
            verdict = VerificationVerdict(verdict)
        if not isinstance(verdict, VerificationVerdict):
            raise VerificationError(f"verdict 非法: {self.verdict!r}")
        object.__setattr__(self, "verdict", verdict)

        checks = tuple(self.checks)
        if not all(isinstance(c, VerificationCheck) for c in checks):
            raise VerificationError("checks 必须全部是 VerificationCheck")
        if len(checks) > MAX_REPORT_CHECKS:
            raise VerificationError("报告检查数量超界")
        object.__setattr__(self, "checks", checks)
        diags = tuple(_bounded_text(d, MAX_DIAGNOSTIC_CHARS) for d in self.diagnostics
                      if isinstance(d, str) and d.strip())
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
    "ARTIFACT_TYPE_CONTENT_RULES",
    "ArtifactObservation",
    "CheckResult",
    "DEFAULT_PROCESS_TIMEOUT_SECONDS",
    "EvidenceBundle",
    "MAX_ARTIFACT_BYTES",
    "MAX_DECLARED_ARTIFACTS",
    "MAX_DIAGNOSTICS",
    "MAX_EVIDENCE_EVENTS",
    "MAX_EXPLANATION_CHARS",
    "MAX_REPORT_CHECKS",
    "MAX_REPORT_JSON_BYTES",
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
