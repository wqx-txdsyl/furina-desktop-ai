"""Phase 16E — WorkExecutionReducer：工作域状态机（唯一状态所有者）。

Master Plan §5A/§10 词表（工作域状态，**绝不写 C7**）：

    IDLE / STARTING / RUNNING / WAITING_PERMISSION / BLOCKED_APPROVAL /
    TOOL_RUNNING(子相位) / VERIFYING / REPAIRING / CANCELLING / CANCELLED /
    BACKEND_DONE_UNVERIFIED / VERIFIED / FAILED / UNKNOWN

规则（任务书 §4）：

- backend completed **只**折算为 ``BACKEND_DONE_UNVERIFIED``；**任何 backend 事件
  都不能产生 ``VERIFIED``**（VERIFIED 只预留给 16F 的校验边界事件）；
- duplicate event_id 幂等；乱序不能回退终态（终态吸收：CANCELLED/FAILED/VERIFIED/
  UNKNOWN 不接受任何转移，reconnect/progress 不得复活）；
- 非法转移返回 typed diagnostic，**零状态变更**；
- ``TOOL_RUNNING`` 是**子相位**（primary + tool_subphase/active_tool 分离快照），
  绝不覆盖/销毁 enclosing run state；
- 同一事件流重放结果完全一致（确定性：内容寻址 id + 纯转移表 + 注入时钟）。

本模块不执行 Hermes、不写 C6/C7、不实现 verifier/repair/recovery（16F/16H/16G 拥有）。
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, Mapping, Tuple

from .models import (
    EventKind,
    NormalizedEvent,
    WorkExecutionError,
)


class WorkExecutionState(str, enum.Enum):
    """工作域状态（Master Plan §5A；TOOL_RUNNING 为子相位标志，非 primary）。"""

    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING_PERMISSION = "WAITING_PERMISSION"
    BLOCKED_APPROVAL = "BLOCKED_APPROVAL"
    TOOL_RUNNING = "TOOL_RUNNING"                    # 子相位（不可作 primary）
    VERIFYING = "VERIFYING"
    REPAIRING = "REPAIRING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    BACKEND_DONE_UNVERIFIED = "BACKEND_DONE_UNVERIFIED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


#: 16E 内的终态（吸收）：任何事件（除精确重复 event_id）都不得改变它们。
TERMINAL_PRIMARY_STATES = frozenset({
    WorkExecutionState.CANCELLED,
    WorkExecutionState.FAILED,
    WorkExecutionState.VERIFIED,
    WorkExecutionState.UNKNOWN,
})

#: 允许作 primary 的状态（TOOL_RUNNING 不在其中——它只能出现在子相位）。
_PRIMARY_STATES = frozenset(s for s in WorkExecutionState
                            if s is not WorkExecutionState.TOOL_RUNNING)


# ---------------------------------------------------------------------------
# 状态快照 / 转移结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WorkExecutionView:
    """不可变状态快照：primary + TOOL_RUNNING 子相位分离。

    - ``primary``：enclosing run state（TOOL_RUNNING 永不覆盖它）；
    - ``tool_subphase``：是否有工具正在执行；
    - ``active_tool``：当前活动工具名（子相位观察）；
    - ``max_sequence`` / ``processed_count``：确定性进度观测。
    """

    primary: WorkExecutionState
    tool_subphase: bool = False
    active_tool: str = ""
    max_sequence: int = -1
    processed_count: int = 0

    def __post_init__(self) -> None:
        if self.primary not in _PRIMARY_STATES:
            raise WorkExecutionError(
                f"primary 不能是 {self.primary.value}（TOOL_RUNNING 是子相位，"
                "由 tool_subphase 表达）")

    @property
    def state(self) -> WorkExecutionState:
        """可观察状态：子相位激活时呈现 TOOL_RUNNING，primary 保持不变。"""
        return WorkExecutionState.TOOL_RUNNING if self.tool_subphase else self.primary

    @property
    def is_terminal(self) -> bool:
        return self.primary in TERMINAL_PRIMARY_STATES


@dataclass(frozen=True)
class ReduceResult:
    """一次 reduce 的结果：完整新快照 + applied + typed diagnostic + kind。

    - ``diagnostic == ""``：事件被接受（可能 self-loop 无状态变化）；
    - ``diagnostic`` 以 ``illegal_transition:`` / ``duplicate_event:`` /
      ``terminal_absorbing:`` 前缀开头：事件被拒绝且**零状态变更**。
    """

    view: WorkExecutionView
    applied: bool
    diagnostic: str = ""
    kind: EventKind = EventKind.UNKNOWN_EVENT


# ---------------------------------------------------------------------------
# 合法转移表（plain 表；outcome 依赖的 approval/VB 由 _apply 单独处理）
# ---------------------------------------------------------------------------
_TRANSITIONS: Dict[WorkExecutionState, Dict[EventKind, WorkExecutionState]] = {
    WorkExecutionState.IDLE: {
        EventKind.RUN_ACCEPTED: WorkExecutionState.STARTING,
        EventKind.STOP_REQUESTED: WorkExecutionState.CANCELLING,
        EventKind.STOPPING: WorkExecutionState.CANCELLING,
        EventKind.BACKEND_FAILED: WorkExecutionState.FAILED,
        EventKind.BACKEND_CANCELLED: WorkExecutionState.CANCELLED,
        EventKind.TRANSPORT_DISCONNECTED: WorkExecutionState.UNKNOWN,
    },
    WorkExecutionState.STARTING: {
        EventKind.RUN_STARTED: WorkExecutionState.RUNNING,
        EventKind.APPROVAL_REQUESTED: WorkExecutionState.WAITING_PERMISSION,
        EventKind.STOP_REQUESTED: WorkExecutionState.CANCELLING,
        EventKind.STOPPING: WorkExecutionState.CANCELLING,
        EventKind.BACKEND_COMPLETED: WorkExecutionState.BACKEND_DONE_UNVERIFIED,
        EventKind.BACKEND_FAILED: WorkExecutionState.FAILED,
        EventKind.BACKEND_CANCELLED: WorkExecutionState.CANCELLED,
        EventKind.TRANSPORT_DISCONNECTED: WorkExecutionState.UNKNOWN,
    },
    WorkExecutionState.RUNNING: {
        EventKind.RUN_STARTED: WorkExecutionState.RUNNING,          # self-loop
        EventKind.APPROVAL_REQUESTED: WorkExecutionState.WAITING_PERMISSION,
        EventKind.STOP_REQUESTED: WorkExecutionState.CANCELLING,
        EventKind.STOPPING: WorkExecutionState.CANCELLING,
        EventKind.BACKEND_COMPLETED: WorkExecutionState.BACKEND_DONE_UNVERIFIED,
        EventKind.BACKEND_FAILED: WorkExecutionState.FAILED,
        EventKind.BACKEND_CANCELLED: WorkExecutionState.CANCELLED,
        EventKind.TRANSPORT_DISCONNECTED: WorkExecutionState.UNKNOWN,
    },
    WorkExecutionState.WAITING_PERMISSION: {
        EventKind.APPROVAL_REQUESTED: WorkExecutionState.WAITING_PERMISSION,  # self-loop
        EventKind.STOP_REQUESTED: WorkExecutionState.CANCELLING,
        EventKind.STOPPING: WorkExecutionState.CANCELLING,
        EventKind.BACKEND_COMPLETED: WorkExecutionState.BACKEND_DONE_UNVERIFIED,
        EventKind.BACKEND_FAILED: WorkExecutionState.FAILED,
        EventKind.BACKEND_CANCELLED: WorkExecutionState.CANCELLED,
        EventKind.TRANSPORT_DISCONNECTED: WorkExecutionState.UNKNOWN,
    },
    WorkExecutionState.BLOCKED_APPROVAL: {
        EventKind.STOP_REQUESTED: WorkExecutionState.CANCELLING,
        EventKind.STOPPING: WorkExecutionState.CANCELLING,
        EventKind.BACKEND_COMPLETED: WorkExecutionState.BACKEND_DONE_UNVERIFIED,
        EventKind.BACKEND_FAILED: WorkExecutionState.FAILED,
        EventKind.BACKEND_CANCELLED: WorkExecutionState.CANCELLED,
        EventKind.TRANSPORT_DISCONNECTED: WorkExecutionState.UNKNOWN,
    },
    WorkExecutionState.CANCELLING: {
        EventKind.STOPPING: WorkExecutionState.CANCELLING,          # self-loop
        EventKind.STOP_REQUESTED: WorkExecutionState.CANCELLING,    # self-loop
        EventKind.BACKEND_CANCELLED: WorkExecutionState.CANCELLED,
        EventKind.BACKEND_FAILED: WorkExecutionState.FAILED,
        EventKind.TRANSPORT_DISCONNECTED: WorkExecutionState.UNKNOWN,
    },
    WorkExecutionState.BACKEND_DONE_UNVERIFIED: {
        EventKind.BACKEND_COMPLETED: WorkExecutionState.BACKEND_DONE_UNVERIFIED,  # 确认自环
        EventKind.TRANSPORT_DISCONNECTED: WorkExecutionState.UNKNOWN,
    },
    WorkExecutionState.VERIFYING: {
        EventKind.BACKEND_FAILED: WorkExecutionState.FAILED,
        EventKind.BACKEND_CANCELLED: WorkExecutionState.CANCELLED,
        EventKind.TRANSPORT_DISCONNECTED: WorkExecutionState.UNKNOWN,
    },
    WorkExecutionState.REPAIRING: {
        EventKind.BACKEND_FAILED: WorkExecutionState.FAILED,
        EventKind.BACKEND_CANCELLED: WorkExecutionState.CANCELLED,
        EventKind.TRANSPORT_DISCONNECTED: WorkExecutionState.UNKNOWN,
    },
}

#: 只读导出（文档/测试用；禁止外部改写）。
LEGAL_TRANSITIONS: Mapping[WorkExecutionState, Mapping[EventKind, WorkExecutionState]] = \
    MappingProxyType({
        s: MappingProxyType(dict(row)) for s, row in _TRANSITIONS.items()
    })


def _outcome(mapping: Mapping[str, Any], keys: Tuple[str, ...]) -> str:
    for k in keys:
        v = mapping.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    return ""


def _approval_outcome(payload: Mapping[str, Any]) -> str:
    """审批结果：approve/deny/timeout（归一化小写；未知 → 'unknown'）。"""
    raw = _outcome(payload, ("outcome", "decision", "resolution", "result"))
    if raw in ("approve", "approved", "allow", "granted"):
        return "approve"
    if raw in ("deny", "denied", "reject", "rejected"):
        return "deny"
    if raw in ("timeout", "expired", "late"):
        return "timeout"
    return "unknown"


def _vb_outcome(payload: Mapping[str, Any]) -> str:
    """校验边界结果：start/verified/failed/repair（未知 → 'unknown'）。"""
    raw = _outcome(payload, ("outcome", "phase", "result", "kind"))
    if raw in ("start", "begin", "retry", "reverify", "enter"):
        return "start"
    if raw in ("verified", "pass", "passed"):
        return "verified"
    if raw in ("failed", "fail"):
        return "failed"
    if raw in ("repair", "repair_start"):
        return "repair"
    return "unknown"


def _tool_name(payload: Mapping[str, Any]) -> str:
    for k in ("tool", "tool_name", "name", "toolId"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:128]
    return ""


class WorkExecutionReducer:
    """每 run 一个的确定性工作域状态机（构造绑定 run_id + contract_id 身份）。

    ``reduce(event)`` 处理一个 canonical 信封：duplicate event_id 幂等；
    非法转移返回 typed diagnostic 且零状态变更；终态吸收；子相位与 primary
    分离存储。同一事件流在全新 reducer 上重放结果完全一致。
    """

    def __init__(self, run_id: str, contract_id: str, *,
                 backend_id: str = "", now_fn=None) -> None:
        for name, v in (("run_id", run_id), ("contract_id", contract_id)):
            if not isinstance(v, str) or not v.strip():
                raise WorkExecutionError(f"{name} 必须是非空 str，得到 {v!r}")
        if not isinstance(backend_id, str):
            raise WorkExecutionError(f"backend_id 必须是 str，得到 {backend_id!r}")
        self._run_id = run_id.strip()
        self._contract_id = contract_id.strip()
        self._backend_id = backend_id.strip()
        self._now_fn = now_fn or (lambda: time.time())
        self._view = WorkExecutionView(primary=WorkExecutionState.IDLE)
        self._seen: set = set()

    # -- 身份与快照 --------------------------------------------------------------
    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def contract_id(self) -> str:
        return self._contract_id

    @property
    def view(self) -> WorkExecutionView:
        return self._view

    # -- 归约 -------------------------------------------------------------------
    def reduce(self, event: NormalizedEvent) -> ReduceResult:
        if not isinstance(event, NormalizedEvent):
            raise WorkExecutionError(
                f"reduce 只接受 NormalizedEvent，得到 {type(event).__name__}"
                "（外部词表必须先经 BackendEventNormalizer 归一）")
        if event.run_id != self._run_id:
            raise WorkExecutionError(
                f"run_id 不匹配：reducer 绑定 {self._run_id!r}，事件为 {event.run_id!r}"
                "（每 run 一个 reducer，禁止跨 run 混用）")
        if event.contract_id != self._contract_id:
            raise WorkExecutionError(
                f"contract_id 不匹配：reducer 绑定 {self._contract_id!r}，"
                f"事件为 {event.contract_id!r}")
        if event.event_id in self._seen:
            return ReduceResult(view=self._view, applied=False,
                                diagnostic=f"duplicate_event:{event.event_id}", kind=event.kind)
        self._seen.add(event.event_id)
        primary, subphase, tool, applied, diag = self._apply(event)
        if not applied:
            # 拒绝：零状态变更（快照对象与计数均不变；diagnostic 说明原因）。
            return ReduceResult(view=self._view, applied=False, diagnostic=diag, kind=event.kind)
        v = self._view
        self._view = WorkExecutionView(
            primary=primary,
            tool_subphase=subphase,
            active_tool=tool,
            max_sequence=max(v.max_sequence, event.sequence),
            processed_count=v.processed_count + 1,
        )
        return ReduceResult(view=self._view, applied=True, diagnostic=diag, kind=event.kind)

    # -- 转移引擎 ----------------------------------------------------------------
    def _apply(self, event: NormalizedEvent) -> Tuple[WorkExecutionState, bool, str,
                                                      bool, str]:
        v = self._view
        primary = v.primary
        kind = event.kind

        # 非转移事件（**任何状态**下都是纯观察：未知/协议错误绝不产生转移，也绝不
        # 因为状态机已终态而被当成问题——它们本来就是非权威/诊断性的）。
        if kind in (EventKind.UNKNOWN_EVENT, EventKind.PROTOCOL_ERROR):
            return primary, v.tool_subphase, v.active_tool, True, ""

        # 终态吸收：任何事件（除精确重复 id 与上述非转移事件）都不得改变终态。
        if primary in TERMINAL_PRIMARY_STATES:
            return primary, v.tool_subphase, v.active_tool, False, \
                f"terminal_absorbing:{primary.value}:{kind.value}"

        # reconnect 在非终态是合法无状态变化观察（不得复活终态——上面已吸收）。
        if kind is EventKind.TRANSPORT_RECONNECTED:
            return primary, v.tool_subphase, v.active_tool, True, ""

        # 审批结果（outcome 依赖）。
        if kind is EventKind.APPROVAL_RESOLVED:
            outcome = _approval_outcome(event.payload)
            if primary in (WorkExecutionState.WAITING_PERMISSION,
                           WorkExecutionState.BLOCKED_APPROVAL):
                if outcome == "approve":
                    return WorkExecutionState.RUNNING, False, "", True, ""
                if primary is WorkExecutionState.WAITING_PERMISSION:
                    return WorkExecutionState.BLOCKED_APPROVAL, False, "", True, ""
                return primary, v.tool_subphase, v.active_tool, True, "approval_already_blocked"
            return primary, v.tool_subphase, v.active_tool, False, \
                f"illegal_transition:{primary.value}:{kind.value}:outcome:{outcome}"

        # 校验边界（16F 唯一合法进入 VERIFYING/REPAIRING/VERIFIED 的通道；
        # normalizer 永不产出此 kind——backend 词表无法自造验证）。
        if kind is EventKind.VERIFICATION_BOUNDARY:
            outcome = _vb_outcome(event.payload)
            if primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED:
                if outcome == "start":
                    return WorkExecutionState.VERIFYING, False, "", True, ""
                if outcome == "repair":
                    return WorkExecutionState.REPAIRING, False, "", True, ""
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}:outcome:{outcome}"
            if primary is WorkExecutionState.VERIFYING:
                if outcome == "verified":
                    return WorkExecutionState.VERIFIED, False, "", True, ""
                if outcome == "failed":
                    return WorkExecutionState.FAILED, False, "", True, ""
                if outcome == "repair":
                    return WorkExecutionState.REPAIRING, False, "", True, ""
                return primary, v.tool_subphase, v.active_tool, True, "verification_restarted"
            if primary is WorkExecutionState.REPAIRING:
                if outcome == "start":
                    return WorkExecutionState.VERIFYING, False, "", True, ""
                if outcome == "failed":
                    return WorkExecutionState.FAILED, False, "", True, ""
                if outcome == "repair":
                    return primary, v.tool_subphase, v.active_tool, True, "repair_continues"
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}:outcome:{outcome}"
            return primary, v.tool_subphase, v.active_tool, False, \
                f"illegal_transition:{primary.value}:{kind.value}"

        # 工具子相位（仅 RUNNING 下有效；TOOL_RUNNING 绝不覆盖 primary）。
        if kind in (EventKind.TOOL_STARTED, EventKind.TOOL_PROGRESS,
                    EventKind.TOOL_COMPLETED):
            if primary is not WorkExecutionState.RUNNING:
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}"
            if kind is EventKind.TOOL_PROGRESS:
                return primary, v.tool_subphase, v.active_tool, True, ""   # tick
            if kind is EventKind.TOOL_STARTED:
                if v.tool_subphase:
                    return primary, v.tool_subphase, v.active_tool, False, \
                        f"illegal_transition:{primary.value}:{kind.value}:tool_already_active"
                return primary, True, _tool_name(event.payload), True, ""
            # TOOL_COMPLETED
            if not v.tool_subphase:
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}:no_active_tool"
            return primary, False, "", True, ""

        # 普通转移表。
        row = _TRANSITIONS.get(primary)
        if row is None:
            return primary, v.tool_subphase, v.active_tool, False, \
                f"illegal_transition:{primary.value}:{kind.value}"
        target = row.get(kind)
        if target is None:
            return primary, v.tool_subphase, v.active_tool, False, \
                f"illegal_transition:{primary.value}:{kind.value}"
        if target == primary:
            return primary, v.tool_subphase, v.active_tool, True, ""   # self-loop
        # primary 变化 → 工具子相位随之清空（工具属于 enclosing run）。
        return target, False, "", True, ""
