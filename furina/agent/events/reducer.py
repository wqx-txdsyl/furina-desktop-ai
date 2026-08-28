"""Phase 16E — WorkExecutionReducer：工作域状态机（唯一状态所有者）。

Master Plan §5A/§10 词表（工作域状态，**绝不写 C7**）：

    IDLE / STARTING / RUNNING / WAITING_PERMISSION / BLOCKED_APPROVAL /
    TOOL_RUNNING(子相位) / VERIFYING / REPAIRING / CANCELLING / CANCELLED /
    BACKEND_DONE_UNVERIFIED / VERIFIED / FAILED / UNKNOWN

规则（任务书 §4 + reviewer patch1）：

- backend completed **只**折算为 ``BACKEND_DONE_UNVERIFIED``；**任何 backend 事件
  都不能产生 ``VERIFIED``**。16E 阶段无 verifier authority，公开 reducer 对
  ``VERIFICATION_BOUNDARY(verified)`` 一律 fail-closed（``unauthorized_verification``
  typed diagnostic，零状态变更）——不得以 provenance 字符串或 Python _private 属性
  冒充 authority；16F 建立真实 verifier 后由组合根注入权威通道再开放。
- duplicate event_id 幂等：``event_id → canonical fingerprint`` 去重——同 id 同内容
  为 duplicate、同 id 不同内容为 ``event_id_conflict``；**payload 清洗 lossy
  （Reviewer Patch 4）时同 id 同 sanitized 内容保守返回 ``event_id_ambiguous``
  （无法确认 raw 是否相同——秘密脱敏/截断/丢弃不得静默当作幂等重投）**；
  **被拒绝的事件（非法转移/终态吸收/冲突等）不烧毁 id**——前置条件满足后同一
  事件可重放；乱序不能回退终态（终态吸收：CANCELLED/FAILED/VERIFIED/UNKNOWN
  不接受任何转移，reconnect/progress 不得复活）；
- 身份绑定：构造绑定 backend_id/run_id/contract_id，事件任一不匹配 raise
  ``WorkExecutionError``（normalizer 对身份不一致同样拒绝，禁止静默改绑）；
- approval.requested/resolved **必须绑定 approval_id**（**精确绑定，无 [:128] 截断**：
  显式非法/超长/control-char/别名冲突 ID 直接 approval_id_invalid 拒绝；
  **Reviewer Patch 3 增加明确 lexical contract：以字母/数字开头、仅含
  [A-Za-z0-9._:-]、总长 <=128——内部空白一律词法非法，control-char 经信封
  sanitizer 变成空格后同样被拒**；resolved 只能作用于当前挂起的请求；deny/timeout
  后同 approval_id 的 approve 不得恢复 RUNNING，不相关 approval_id 不得改变状态
  （approval_id_mismatch typed diagnostic，零变更）；**WAITING_PERMISSION 中
  幂等观察 = 同 approval_id + 同请求内容（除 approval_id 外保存 canonical
  sanitized request fingerprint；同 id 异内容 → approval_request_conflict 零变更
  —绝不覆盖 pending；**payload 清洗 lossy（Reviewer Patch 4）时同 id 同 sanitized
  内容保守返回 approval_request_ambiguous（秘密脱敏/第 256 字符后截断/整体截断/
  深度或非法值丢弃不得静默当作幂等重投）**；resolution 后同时清除 pending id 与
  fingerprint）**；不同
  approval_id 请求为 approval_id_conflict（零变更，绝不覆盖 pending）；
  **outcome/decision/resolution/result 所有已出现别名规范化一致（approve≈approved
  等价；approve 与 deny/timeout 冲突 → outcome_conflict typed rejection 零状态
  变化；非 str/空/未知值 fail-closed；verification outcome 别名同样一致性检查，
  避免相邻 first-key-wins）**；BLOCKED_APPROVAL 仍允许新合法请求）；
- 非法转移返回 typed diagnostic，**零状态变更**；
- ``TOOL_RUNNING`` 是**子相位**（primary + tool_subphase/active_tool 分离快照），
  绝不覆盖/销毁 enclosing run state；TOOL_STARTED/TOOL_COMPLETED 是不可丢/不可
  合并的生命周期边界（critical）；**工具身份配对**：TOOL_STARTED 必须建立非空
  active_tool；TOOL_COMPLETED 的工具身份必须与 active_tool 一致；**工具身份
  明确 lexical contract（Reviewer Patch 4）**：tool/tool_name/name/toolId 所有
  别名 strip 后必须规范化一致，且以字母/数字开头、仅含 [A-Za-z0-9._:-]、总长
  <=128——内部空白（含 control-char 经 sanitizer 变为空格后）、斜杠、下划线
  开头及其它非法字符一律 tool_identity_invalid（TOOL_STARTED/显式 TOOL_PROGRESS/
  TOOL_COMPLETED 共用同一规则）；**TOOL_PROGRESS
  （Reviewer Patch 3）：payload 显式携带工具身份时必须与 active_tool 精确匹配
  （缺失/不同 → tool_identity_invalid/tool_identity_mismatch typed diagnostic、
  零状态变更——fs.read active 时 fs.delete completed 不得关闭子相位）；payload
  未携带任何工具身份时作为 generic stream/progress tick（message.delta/reasoning/
  reasoning.delta 无 tool 字段的真实 fixture）——RUNNING 中合法 self-loop，不建立、
  不关闭、不改变 tool_subphase，永不产生终态或 VERIFIED**；
- 同一事件流重放结果完全一致（确定性：非敏感字段派生的 fallback id + 纯转移表
  + 注入时钟；lossy 判据只影响同一会话内的去重/幂等裁决，不改变状态转移本身）。

本模块不执行 Hermes、不写 C6/C7、不实现 verifier/repair/recovery（16F/16H/16G 拥有）。
"""
from __future__ import annotations

import enum
import json
import re
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

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
        EventKind.APPROVAL_REQUESTED: WorkExecutionState.WAITING_PERMISSION,  # 新请求重新挂起
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


#: outcome 别名一致性标记（普通值绝不可能与 `<...>` 形态冲突——词表里没有尖括号）。
_OUTCOME_INVALID = "<invalid>"
_OUTCOME_CONFLICT = "<conflict>"

_APPROVAL_OUTCOME_KEYS = ("outcome", "decision", "resolution", "result")
_APPROVAL_OUTCOME_ALIASES = {
    "approve": "approve", "approved": "approve", "allow": "approve", "granted": "approve",
    "deny": "deny", "denied": "deny", "reject": "deny", "rejected": "deny",
    "timeout": "timeout", "expired": "timeout", "late": "timeout",
}

_VB_OUTCOME_KEYS = ("outcome", "phase", "result", "kind")
_VB_OUTCOME_ALIASES = {
    "start": "start", "begin": "start", "retry": "start", "reverify": "start",
    "enter": "start",
    "verified": "verified", "pass": "verified", "passed": "verified",
    "failed": "failed", "fail": "failed",
    "repair": "repair", "repair_start": "repair",
}


def _consensus_outcome(mapping: Mapping[str, Any], keys: Tuple[str, ...],
                       aliases: Mapping[str, str]) -> str:
    """结果类别名一致性（Reviewer Patch 3）：所有**已出现**的键必须是非空 str 且
    规范化后一致（approve≈approved 等词表内等价视为同值）。

    - 缺省（无任何键出现）→ ``""``（调用方 fail-closed）；
    - 任一出现键非 str / 空 / 不在词表（未知值）→ ``_OUTCOME_INVALID``（fail-closed）；
    - 规范化后互不一致（如 outcome=approve 与 decision=deny 同时出现）→
      ``_OUTCOME_CONFLICT``（typed rejection、零状态变化）——**避免相邻 first-key-wins**。
    """
    present = [(k, mapping[k]) for k in keys if k in mapping]
    if not present:
        return ""
    canon: Optional[str] = None
    for k, v in present:
        if not isinstance(v, str) or not v.strip():
            return _OUTCOME_INVALID
        c = aliases.get(v.strip().lower())
        if c is None:
            return _OUTCOME_INVALID
        if canon is None:
            canon = c
        elif c != canon:
            return _OUTCOME_CONFLICT
    assert canon is not None
    return canon


def _approval_outcome(payload: Mapping[str, Any]) -> str:
    """审批结果：outcome/decision/resolution/result 所有已出现别名规范化一致
    （approve/approved/allow/granted 等价；deny/denied/reject/rejected 等价；
    timeout/expired/late 等价）。非 str/空/未知 → ``<invalid>``；别名规范化冲突
    （approve vs deny/timeout）→ ``<conflict>``；缺省 → ``""``。"""
    return _consensus_outcome(payload, _APPROVAL_OUTCOME_KEYS, _APPROVAL_OUTCOME_ALIASES)


def _vb_outcome(payload: Mapping[str, Any]) -> str:
    """校验边界结果：outcome/phase/result/kind 所有已出现别名规范化一致
    （start/begin/retry/reverify/enter 等价；verified/pass/passed 等价；
    failed/fail 等价；repair/repair_start 等价）。非法/未知/冲突同上返回 typed 标志。"""
    return _consensus_outcome(payload, _VB_OUTCOME_KEYS, _VB_OUTCOME_ALIASES)


_TOOL_IDENTITY_KEYS = ("tool", "tool_name", "name", "toolId")
_TOOL_IDENTITY_MAX_LEN = 128
#: 工具身份明确 lexical contract（Reviewer Patch 4）：以字母/数字开头，仅含
#: ``[A-Za-z0-9._:-]``，总长 <=128（兼容 app.launch / browser.open / fs.read_file /
#: fs.write_text / doc.create / comm.send_message 等真实工具名）。内部空白一律词法
#: 非法——control-char 经信封 sanitizer 变成空格后同样被拒（``"fs.read\\x00file"``
#: 清洗为 ``"fs.read file"`` → 拒绝）；斜杠/下划线开头/其它非法字符一律拒绝。
_TOOL_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")
_APPROVAL_ID_KEYS = ("approval_id", "approvalId", "request_id", "requestId")
_APPROVAL_ID_MAX_LEN = 128
#: approval_id 明确 lexical contract（Reviewer Patch 3）：以字母/数字开头，仅含
#: ``[A-Za-z0-9._:-]``，总长 <=128。内部空白一律词法非法——control-char 经信封
#: sanitizer 变成空格后同样被拒（``"ap\\x00bad"`` 清洗为 ``"ap bad"`` → 拒绝），
#: 不接受内部空白、截断或别名冲突。
_APPROVAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")


def _tool_identity(payload: Mapping[str, Any]) -> Tuple[bool, Optional[str]]:
    """payload 中的工具身份：返回 ``(present, value)``（Reviewer Patch 3 三态）。

    **明确 lexical contract（Reviewer Patch 4）**：以字母/数字开头、仅含
    ``[A-Za-z0-9._:-]``、总长 <=128；内部空白（control-char 经信封 sanitizer
    变为空格后同样词法非法）、斜杠、下划线开头及其它非法字符一律拒绝；所有
    别名（tool/tool_name/name/toolId）strip 后必须规范化一致。TOOL_STARTED /
    显式 TOOL_PROGRESS / TOOL_COMPLETED 共用同一规则。

    - ``(False, None)``：payload **未携带任何**工具身份字段（generic progress tick）；
    - ``(True, str)``：唯一合法身份（非空 str、词法合法、<=128、多别名等值）；
    - ``(True, None)``：显式携带但**非法**（非 str / 空 / 词法非法 / 超长 /
      多别名冲突）。
    """
    present = [k for k in _TOOL_IDENTITY_KEYS if k in payload]
    if not present:
        return False, None
    value: Optional[str] = None
    for k in present:
        v = payload[k]
        if not isinstance(v, str) or not v.strip():
            return True, None
        s = v.strip()
        if len(s) > _TOOL_IDENTITY_MAX_LEN or not _TOOL_IDENTITY_PATTERN.match(s):
            return True, None
        if value is not None and s != value:
            return True, None
        value = s
    return True, value


def _approval_id(payload: Mapping[str, Any], event_id: str) -> Optional[str]:
    """审批身份：payload 显式合法 approval_id 优先；缺省回退到请求事件自身的
    canonical event_id（确定性绑定，绝不虚构——回退身份即该请求事件的恒等）。

    显式出现但非法（非 str / 空 / 超长 >128 / **词法非法**——含内部空白，
    control-char 经信封清洗为空格后同样词法非法 / 多别名冲突）→ None，
    调用方转 typed diagnostic 拒绝——**绝不静默截断、绝不接受内部空白**，
    也不当作缺失补值。
    """
    present = [k for k in _APPROVAL_ID_KEYS if k in payload]
    if not present:
        return event_id
    value: Optional[str] = None
    for k in present:
        v = payload[k]
        if not isinstance(v, str) or not v.strip():
            return None
        s = v.strip()
        if len(s) > _APPROVAL_ID_MAX_LEN or not _APPROVAL_ID_PATTERN.match(s):
            return None
        if value is not None and s != value:
            return None
        value = s
    return value


def _request_fingerprint(payload: Mapping[str, Any]) -> str:
    """挂起请求内容指纹（Reviewer Patch 3）：payload 中**除 approval_id 别名外**的
    规范化内容（已 sanitized、JSON-safe、确定性排序）。WAITING_PERMISSION 中
    『同 approval_id + 同请求内容』才是幂等观察；同 approval_id 但 tool/scope/
    args/其它 payload 不同必须 conflict，**不得覆盖 pending**。"""
    tree = {k: _plain_tree(v) for k, v in payload.items() if k not in _APPROVAL_ID_KEYS}
    return json.dumps(tree, sort_keys=True, ensure_ascii=False, default=str)


def _plain_tree(obj: Any) -> Any:
    """MappingProxyType → dict、tuple → list（fingerprint 序列化前解冻）。"""
    if isinstance(obj, Mapping):
        return {k: _plain_tree(v) for k, v in obj.items()}
    if isinstance(obj, tuple):
        return [_plain_tree(v) for v in obj]
    return obj


def _event_fingerprint(event: NormalizedEvent) -> str:
    """event_id → canonical fingerprint（同 id 同内容 = duplicate 的判据）。

    只取**语义内容**（身份 + kind + 清洗后 payload），排除 sequence/时间戳等
    投递元数据——上游稳定 event_id 的重投（到达时间/补序位置不同）仍视为同内容；
    同一 id 复用为不同语义事件（kind/payload/身份变化）则判定 event_id_conflict。
    **payload 清洗 lossy 时（Reviewer Patch 4），同 id 同 fingerprint 保守判定为
    event_id_ambiguous 而非 duplicate**——清洗结果相同不代表 raw 相同。
    """
    canon = json.dumps(_plain_tree(event.payload), sort_keys=True, ensure_ascii=False,
                       default=str)
    return "|".join((event.backend_id, event.contract_id, event.run_id,
                     event.kind.value, canon))


class WorkExecutionReducer:
    """每 run 一个的确定性工作域状态机（构造绑定 backend_id+run_id+contract_id）。

    ``reduce(event)`` 处理一个 canonical 信封：event_id→fingerprint 去重（同 id
    同内容 duplicate、同 id 不同内容 conflict、**lossy payload 同 id 同内容 →
    event_id_ambiguous**）；非法转移/终态吸收/审批身份不匹配
    返回 typed diagnostic 且**零状态变更、不烧毁 event_id**（前置条件满足后可重放）；
    审批 resolved 必须匹配当前挂起 approval_id（精确绑定、词法校验、无截断；
    WAITING 中同 id **且同请求内容**重投幂等观察（**lossy 内容 →
    approval_request_ambiguous，不判定幂等**）、同 id 异内容 typed conflict、
    异 id conflict，均零变更不覆盖 pending）；outcome 别名一致性（冲突
    outcome_conflict、非法/未知 fail-closed、approve≈approved 等价）；工具事件按
    active_tool 精确配对（**工具身份明确 lexical contract**；TOOL_PROGRESS 无身份
    = generic tick self-loop、显式身份必须匹配）；``VERIFICATION_BOUNDARY(verified)``
    在 16E 阶段 fail-closed（VERIFIED 不可由公开事件抵达）。同一事件流在全新
    reducer 上重放结果完全一致。
    """

    def __init__(self, run_id: str, contract_id: str, *,
                 backend_id: str, now_fn=None) -> None:
        for name, v in (("backend_id", backend_id), ("run_id", run_id),
                        ("contract_id", contract_id)):
            if not isinstance(v, str) or not v.strip():
                raise WorkExecutionError(f"{name} 必须是非空 str，得到 {v!r}")
        self._backend_id = backend_id.strip()
        self._run_id = run_id.strip()
        self._contract_id = contract_id.strip()
        self._now_fn = now_fn or (lambda: time.time())
        self._view = WorkExecutionView(primary=WorkExecutionState.IDLE)
        self._seen: Dict[str, str] = {}
        #: 已接受事件是否 lossy 清洗（Reviewer Patch 4）：与 _seen 同步记录——
        #: lossy 内容的重投不得静默判定 duplicate。
        self._seen_lossy: Dict[str, bool] = {}
        self._pending_approval_id: Optional[str] = None
        #: 挂起请求的 canonical sanitized fingerprint（Reviewer Patch 3）：除
        #: approval_id 外保存请求内容——WAITING 中『同 approval_id + 同请求内容』
        #: 才是幂等观察；resolution 后与 pending id 一并清除。
        self._pending_approval_fingerprint: Optional[str] = None
        #: 挂起请求是否 lossy 清洗（Reviewer Patch 4）：lossy 请求（秘密脱敏/截断/
        #: 深度或非法值丢弃）的重投保守返回 approval_request_ambiguous，不判定幂等。
        self._pending_approval_lossy: bool = False

    # -- 身份与快照 --------------------------------------------------------------
    @property
    def backend_id(self) -> str:
        return self._backend_id

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
        if event.backend_id != self._backend_id:
            raise WorkExecutionError(
                f"backend_id 不匹配：reducer 绑定 {self._backend_id!r}，"
                f"事件为 {event.backend_id!r}（禁止跨 backend 混用）")
        if event.run_id != self._run_id:
            raise WorkExecutionError(
                f"run_id 不匹配：reducer 绑定 {self._run_id!r}，事件为 {event.run_id!r}"
                "（每 run 一个 reducer，禁止跨 run 混用）")
        if event.contract_id != self._contract_id:
            raise WorkExecutionError(
                f"contract_id 不匹配：reducer 绑定 {self._contract_id!r}，"
                f"事件为 {event.contract_id!r}")
        seen_fp = self._seen.get(event.event_id)
        if seen_fp is not None:
            if seen_fp == _event_fingerprint(event):
                if self._seen_lossy.get(event.event_id, False) or event.lossy_payload:
                    # Reviewer Patch 4：同 id 同 sanitized 内容但任一侧经过 lossy
                    # 清洗（秘密脱敏/截断/深度或非法值丢弃）——无法确认 raw 是否
                    # 相同，保守 ambiguous 而非 duplicate（低熵秘密不得被静默去重）。
                    return ReduceResult(view=self._view, applied=False,
                                        diagnostic=f"event_id_ambiguous:{event.event_id}",
                                        kind=event.kind)
                return ReduceResult(view=self._view, applied=False,
                                    diagnostic=f"duplicate_event:{event.event_id}",
                                    kind=event.kind)
            return ReduceResult(view=self._view, applied=False,
                                diagnostic=f"event_id_conflict:{event.event_id}",
                                kind=event.kind)
        primary, subphase, tool, applied, diag = self._apply(event)
        if not applied:
            # 拒绝：零状态变更（快照对象与计数均不变；id 不烧毁——先非法后满足
            # 前置条件的同事件可重放）。
            return ReduceResult(view=self._view, applied=False, diagnostic=diag,
                                kind=event.kind)
        self._seen[event.event_id] = _event_fingerprint(event)
        self._seen_lossy[event.event_id] = event.lossy_payload
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

        # 审批请求：绑定 approval_id 并进入挂起态（BLOCKED 收到新请求 → 重新挂起）。
        if kind is EventKind.APPROVAL_REQUESTED:
            if primary not in (WorkExecutionState.STARTING, WorkExecutionState.RUNNING,
                               WorkExecutionState.BLOCKED_APPROVAL,
                               WorkExecutionState.WAITING_PERMISSION):
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}"
            rid = _approval_id(event.payload, event.event_id)
            if rid is None:
                # 显式非法 approval_id（词法非法/内部空白/超长/别名冲突）：拒绝且
                # **不建立/不覆盖** pending，零状态变更。
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"approval_id_invalid:{primary.value}:{kind.value}"
            if primary in (WorkExecutionState.STARTING, WorkExecutionState.RUNNING,
                           WorkExecutionState.BLOCKED_APPROVAL):
                self._pending_approval_id = rid
                self._pending_approval_fingerprint = _request_fingerprint(event.payload)
                self._pending_approval_lossy = event.lossy_payload
                return WorkExecutionState.WAITING_PERMISSION, False, "", True, ""
            # WAITING_PERMISSION：幂等观察 = **同 approval_id 且同请求内容**
            # （Reviewer Patch 3）；异 id → approval_id_conflict、同 id 异内容 →
            # approval_request_conflict，均零状态变更，**绝不覆盖** pending。
            if rid != self._pending_approval_id:
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"approval_id_conflict:{primary.value}:{kind.value}"
            if _request_fingerprint(event.payload) != self._pending_approval_fingerprint:
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"approval_request_conflict:{primary.value}:{kind.value}"
            # Reviewer Patch 4：同 id 同 sanitized 内容但任一侧经过 lossy 清洗
            # （secret 字段 → [REDACTED]、第 256 字符后截断、整体截断/深度/非法值
            # 丢弃）——无法确认 raw 是否相同，保守 ambiguous、零状态变更、绝不覆盖
            # pending（低熵秘密不得被静默当作幂等重投）。
            if self._pending_approval_lossy or event.lossy_payload:
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"approval_request_ambiguous:{primary.value}:{kind.value}"
            return primary, v.tool_subphase, v.active_tool, True, ""

        # 审批结果（approval_id 精确绑定；outcome 别名一致性——Reviewer Patch 3）。
        if kind is EventKind.APPROVAL_RESOLVED:
            outcome = _approval_outcome(event.payload)
            if primary in (WorkExecutionState.WAITING_PERMISSION,
                           WorkExecutionState.BLOCKED_APPROVAL):
                rid = _approval_id(event.payload, event.event_id)
                if rid is None:
                    # 显式非法 approval_id：直接拒绝（不得截断后匹配任何挂起身份）。
                    return primary, v.tool_subphase, v.active_tool, False, \
                        f"approval_id_invalid:{primary.value}:{kind.value}"
                if self._pending_approval_id is None or rid != self._pending_approval_id:
                    return primary, v.tool_subphase, v.active_tool, False, \
                        f"approval_id_mismatch:{primary.value}:{kind.value}"
                if outcome == _OUTCOME_CONFLICT:
                    # approve 与 deny/timeout 等别名冲突：typed rejection、零状态
                    # 变化、**不消费**挂起请求（pending 保留，可重试）。
                    return primary, v.tool_subphase, v.active_tool, False, \
                        f"outcome_conflict:{primary.value}:{kind.value}"
                if outcome in (_OUTCOME_INVALID, ""):
                    # 非 str / 空 / 未知值：fail-closed 拒绝且不消费挂起请求。
                    return primary, v.tool_subphase, v.active_tool, False, \
                        f"illegal_transition:{primary.value}:{kind.value}:outcome:{outcome}"
                assert outcome in ("approve", "deny", "timeout")
                # 合法消费即销毁（一次性）：同时清除 pending id / fingerprint / lossy。
                self._pending_approval_id = None
                self._pending_approval_fingerprint = None
                self._pending_approval_lossy = False
                if outcome == "approve":
                    return WorkExecutionState.RUNNING, False, "", True, ""
                return WorkExecutionState.BLOCKED_APPROVAL, False, "", True, ""
            return primary, v.tool_subphase, v.active_tool, False, \
                f"illegal_transition:{primary.value}:{kind.value}:outcome:{outcome}"

        # 校验边界（16F 唯一合法进入 VERIFYING/REPAIRING 的通道；normalizer 永不
        # 产出此 kind——backend 词表无法自造验证）。16E 阶段无 verifier authority：
        # outcome=verified 一律 fail-closed，VERIFIED 不可由公开事件抵达。
        if kind is EventKind.VERIFICATION_BOUNDARY:
            outcome = _vb_outcome(event.payload)
            if outcome == "verified":
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"unauthorized_verification:{primary.value}:{kind.value}"
            if outcome == _OUTCOME_CONFLICT:
                # start/failed/repair 等别名冲突：typed rejection、零状态变化。
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"outcome_conflict:{primary.value}:{kind.value}"
            if outcome in (_OUTCOME_INVALID, ""):
                # 非 str / 空 / 未知值：fail-closed 拒绝（零状态变化）。
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}:outcome:{outcome}"
            if primary is WorkExecutionState.BACKEND_DONE_UNVERIFIED:
                if outcome == "start":
                    return WorkExecutionState.VERIFYING, False, "", True, ""
                if outcome == "repair":
                    return WorkExecutionState.REPAIRING, False, "", True, ""
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}:outcome:{outcome}"
            if primary is WorkExecutionState.VERIFYING:
                if outcome == "failed":
                    return WorkExecutionState.FAILED, False, "", True, ""
                if outcome == "repair":
                    return WorkExecutionState.REPAIRING, False, "", True, ""
                if outcome == "start":
                    return primary, v.tool_subphase, v.active_tool, True, \
                        "verification_restarted"
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}:outcome:{outcome}"
            if primary is WorkExecutionState.REPAIRING:
                if outcome == "start":
                    return WorkExecutionState.VERIFYING, False, "", True, ""
                if outcome == "failed":
                    return WorkExecutionState.FAILED, False, "", True, ""
                if outcome == "repair":
                    return primary, v.tool_subphase, v.active_tool, True, \
                        "repair_continues"
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}:outcome:{outcome}"
            return primary, v.tool_subphase, v.active_tool, False, \
                f"illegal_transition:{primary.value}:{kind.value}"

        # 工具子相位（仅 RUNNING 下有效；TOOL_RUNNING 绝不覆盖 primary）。
        # Reviewer Patch 3：TOOL_STARTED/TOOL_COMPLETED 必须有合法且匹配的工具
        # 身份（生命周期配对不放宽）；TOOL_PROGRESS 显式携带身份时必须与
        # active_tool 精确匹配，未携带任何身份时作为 generic stream/progress tick
        # （RUNNING 中合法 self-loop，不建立/不关闭/不改变 tool_subphase）。
        if kind in (EventKind.TOOL_STARTED, EventKind.TOOL_PROGRESS,
                    EventKind.TOOL_COMPLETED):
            if primary is not WorkExecutionState.RUNNING:
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}"
            present, identity = _tool_identity(event.payload)
            if kind is EventKind.TOOL_PROGRESS:
                if not present:
                    # generic stream/progress tick（message.delta/reasoning 等无
                    # tool 身份的真实 fixture）：RUNNING 中合法 self-loop，零状态
                    # 变化，永远不能产生终态或 VERIFIED。
                    return primary, v.tool_subphase, v.active_tool, True, ""
                if identity is None:
                    # 显式携带但类型非法/别名冲突 → 拒绝（零变更）。
                    return primary, v.tool_subphase, v.active_tool, False, \
                        f"illegal_transition:{primary.value}:{kind.value}:tool_identity_invalid"
                if not v.tool_subphase or identity != v.active_tool:
                    return primary, v.tool_subphase, v.active_tool, False, \
                        f"illegal_transition:{primary.value}:{kind.value}:tool_identity_mismatch"
                return primary, v.tool_subphase, v.active_tool, True, ""   # tick
            # TOOL_STARTED / TOOL_COMPLETED：必须携带合法工具身份（缺省/非法一律
            # tool_identity_invalid；TOOL_STARTED 不得建立空 active_tool、TOOL_
            # COMPLETED 不得在无身份时关闭子相位）。
            if identity is None:
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}:tool_identity_invalid"
            if kind is EventKind.TOOL_STARTED:
                if v.tool_subphase:
                    return primary, v.tool_subphase, v.active_tool, False, \
                        f"illegal_transition:{primary.value}:{kind.value}:tool_already_active"
                return primary, True, identity, True, ""
            # TOOL_COMPLETED：身份必须与 active_tool 一致（缺失/不同均拒绝、零变更，
            # 不得关闭子相位——fs.read active 时 fs.delete completed 不得清场）。
            if not v.tool_subphase:
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}:no_active_tool"
            if identity != v.active_tool:
                return primary, v.tool_subphase, v.active_tool, False, \
                    f"illegal_transition:{primary.value}:{kind.value}:tool_identity_mismatch"
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
