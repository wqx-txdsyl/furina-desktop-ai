"""Phase 16B — ExecutionBackend 数据模型与类型化错误（backend-neutral）。

后端无关执行后端抽象的核心原则（任务书 §3/§4）：

- **注册不是执行**：把 backend 放进 registry 不代表它可路由；必须先 probe 建立健康事实。
- ``installed != reachable != healthy != capable``：四者必须逐层显式区分。
- 能力只允许显式布尔 / 有限集合 / 数值上限，**禁止 free-form 承诺**。
- BackendRunHandle 只承载 backend_id / run_id / correlation，不偷带任何结果语义；
  BackendEvent 在 16B 只作类型化引用占位（规范化/状态机由 16E 拥有）。

本模块无任何 DB / schema / 持久化行为（C1–C7 不动）。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from furina.core import FurinaError

#: 本 Phase 后端协议版本（backend 必须显式声明；用于未来协议演进否决）。
PROTOCOL_VERSION = "1.0.0"

#: backend_id / capability id 词法（与 WorkContract.allowed_backends 的 token 同形）。
_TOKEN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:\-/]{1,119}$")

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


# ---------------------------------------------------------------------------
# 类型化错误
# ---------------------------------------------------------------------------
class BackendError(FurinaError):
    """backend 域统一异常基类。"""


class BackendRegistrationError(BackendError):
    """注册被拒（重复 id / 非法 id / 非 ExecutionBackend）。"""


class BackendUnknownError(BackendError):
    """registry 中不存在该 backend_id。"""


class BackendCapabilityError(BackendError):
    """backend 未声明该能力（capability-gated 方法在未声明时被调用）。"""


class BackendSubmitFailure(BackendError):
    """backend submit 抛出的类型化失败（dispatch 层 fail-soft 承接，不静默换 backend）。"""


def _clean_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BackendError(f"{field_name} 必须是非空 str，得到 {value!r}")
    return value.strip()


# ---------------------------------------------------------------------------
# BackendDescriptor
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BackendDescriptor:
    """稳定身份 + 展示元数据 + 协议版本（身份不是能力，能力在 BackendCapabilities）。"""

    backend_id: str
    display_name: str = ""
    description: str = ""
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        bid = _clean_str(self.backend_id, "backend_id")
        if not _TOKEN_PATTERN.match(bid):
            raise BackendError(f"backend_id 必须匹配 {_TOKEN_PATTERN.pattern}，得到 {bid!r}")
        object.__setattr__(self, "backend_id", bid)
        object.__setattr__(self, "display_name", _clean_str(self.display_name, "display_name"))
        ver = _clean_str(self.protocol_version, "protocol_version")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", ver):
            raise BackendError(f"protocol_version 必须是 semver 三段式，得到 {ver!r}")
        object.__setattr__(self, "protocol_version", ver)


# ---------------------------------------------------------------------------
# BackendCapabilities
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BackendCapabilities:
    """显式能力声明：有限集合 + 布尔 + 数值上限，绝不 free-form。

    - ``capability_ids``：本 backend 可满足的 contract allowed_capabilities id（有限显式集合）；
    - ``supports_events / supports_stop / supports_resolve_approval``：显式布尔；
    - ``max_concurrent_runs``：并发 run 数上限（>=1）；
    - ``max_cost_limit / max_duration_seconds``：可承接的契约预算上限（None = 未声明后端级上限，
      视为不参与该维度的兼容性否决）；
    - ``workspace_scoped``：是否执行契约 WorkspaceScope（不执行 → 带 scope 的契约不兼容）。
    """

    capability_ids: Tuple[str, ...] = ()
    supports_events: bool = False
    supports_stop: bool = False
    supports_resolve_approval: bool = False
    max_concurrent_runs: int = 1
    max_cost_limit: Optional[float] = None
    max_duration_seconds: Optional[float] = None
    workspace_scoped: bool = True

    def __post_init__(self) -> None:
        caps = []
        for v in self.capability_ids:
            s = _clean_str(v, "capability_ids 条目")
            if not _TOKEN_PATTERN.match(s):
                raise BackendError(f"capability id 词法非法: {s!r}")
            caps.append(s)
        if len(caps) != len(set(caps)):
            raise BackendError("capability_ids 存在重复条目")
        object.__setattr__(self, "capability_ids", tuple(sorted(caps)))
        for flag in ("supports_events", "supports_stop", "supports_resolve_approval",
                     "workspace_scoped"):
            if not isinstance(getattr(self, flag), bool):
                raise BackendError(f"{flag} 必须是 bool")
        if not isinstance(self.max_concurrent_runs, int) or self.max_concurrent_runs < 1:
            raise BackendError(f"max_concurrent_runs 必须是 >=1 的 int，得到 {self.max_concurrent_runs!r}")
        if self.max_cost_limit is not None and (
                isinstance(self.max_cost_limit, bool) or not isinstance(self.max_cost_limit, (int, float))
                or self.max_cost_limit <= 0):
            raise BackendError(f"max_cost_limit 必须是正数值或 None，得到 {self.max_cost_limit!r}")
        if self.max_duration_seconds is not None and (
                isinstance(self.max_duration_seconds, bool)
                or not isinstance(self.max_duration_seconds, (int, float))
                or self.max_duration_seconds <= 0):
            raise BackendError(f"max_duration_seconds 必须是正数值或 None，得到 {self.max_duration_seconds!r}")

    def satisfies(self, required_capabilities: Tuple[str, ...]) -> bool:
        """契约所需能力集合是否被本 backend 显式覆盖。"""
        return set(required_capabilities).issubset(set(self.capability_ids))


# ---------------------------------------------------------------------------
# BackendHealth
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BackendHealth:
    """一次性健康事实（installed / reachable / healthy 三态严格分离）。

    - ``checked_at``：探测时刻（epoch 秒）；
    - ``expiry``：健康事实的**绝对过期时刻**（epoch 秒）；过期后不得当作 healthy 路由；
    - ``reason``：不健康原因（healthy=True 时可为空）。
    """

    installed: bool = False
    reachable: bool = False
    healthy: bool = False
    checked_at: float = 0.0
    reason: str = ""
    expiry: float = 0.0

    def __post_init__(self) -> None:
        for f in ("installed", "reachable", "healthy"):
            if not isinstance(getattr(self, f), bool):
                raise BackendError(f"health.{f} 必须是 bool")
        for f in ("checked_at", "expiry"):
            v = getattr(self, f)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise BackendError(f"health.{f} 必须是非 bool 数值")
            object.__setattr__(self, f, float(v))
        if not isinstance(self.reason, str):
            raise BackendError("health.reason 必须是 str（healthy 时可为空）")
        object.__setattr__(self, "reason", self.reason.strip())
        if self.healthy and not (self.installed and self.reachable):
            raise BackendError("healthy=True 时必须同时 installed=True 且 reachable=True")

    def is_stale(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return now > self.expiry

    def is_effective(self, now: Optional[float] = None) -> bool:
        """router 唯一健康判据：installed ∧ reachable ∧ healthy ∧ 未过期（fail-closed）。"""
        now = time.time() if now is None else now
        return self.installed and self.reachable and self.healthy and now <= self.expiry


# ---------------------------------------------------------------------------
# BackendRunHandle / BackendEvent
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BackendRunHandle:
    """run 身份载体：backend_id + run_id + correlation，仅此而已（不偷带结果语义）。"""

    backend_id: str
    run_id: str
    correlation: str = ""

    def __post_init__(self) -> None:
        bid = _clean_str(self.backend_id, "handle.backend_id")
        object.__setattr__(self, "backend_id", bid)
        rid = _clean_str(self.run_id, "handle.run_id")
        if not _RUN_ID_PATTERN.match(rid):
            raise BackendError(f"run_id 词法非法: {rid!r}")
        object.__setattr__(self, "run_id", rid)
        corr = self.correlation
        if not isinstance(corr, str):
            raise BackendError("handle.correlation 必须是 str")
        object.__setattr__(self, "correlation", corr)


@dataclass(frozen=True)
class BackendEvent:
    """backend 原生事件**引用**（16B 只作类型化占位；规范化与状态机由 16E 拥有）。"""

    backend_id: str
    run_id: str
    event_type: str
    payload: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.backend_id, str) or not self.backend_id.strip():
            raise BackendError("event.backend_id 必须是非空 str")
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise BackendError("event.run_id 必须是非空 str")
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise BackendError("event.event_type 必须是非空 str")
