"""行为引擎（legacy-plan/3 §8-9, §15-19）。

- Utility AI：对候选行为打分（不止需求，含 context/cooldown/interruption）。
- LLM 只赐高价值决策；本地环路处理日常。
- 行为最终通过 ActionRequest 提交 Director，本层**不直接驱动渲染**（legacy-plan/8 §3）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from furina.core import EventBus, EventType, get_logger
from furina.state.state_model import Intent, IntentCategory, MacroState
from .behavior_types import BehaviorDefinition, BehaviorResult, BehaviorState

log = get_logger("behavior")

# legacy-plan/8 §9 —— LLM 只能在这些枚举里选
ALLOWED_INTENTS: Dict[IntentCategory, List[str]] = {
    IntentCategory.SURVIVE: ["eat", "drink", "sleep"],
    IntentCategory.INTERACT: ["greet", "talk", "play", "seek_attention"],
    IntentCategory.SELF: ["explore", "read", "relax", "wander"],
    IntentCategory.USER: ["observe", "help", "remind", "accompany"],
    IntentCategory.AGENT: ["understand", "plan", "execute", "report"],
}

# FINAL Fallback Presence（评审基线 e5ce9fb）：本地回退（无 LifeBrain）下"依赖用户已知在场"
# 的 fallback 行为 —— 匹配生产注册的实际动作名（app._register_behaviors）。
# 只列语义上**必须用户在场**的现有 fallback 行为，不扩大产品范围（play 是自主玩耍，不算）。
_FALLBACK_USER_DEPENDENT = frozenset({"observe_user", "talk_to_user", "approach_user"})


def _fallback_presence_known(state: dict) -> bool:
    """fallback 在场可行性：**只认 idle_available 位**（CharacterState.snapshot() 恒携带）。

    缺失/非 True = 在场未知（不得当 known/True；缺失意味着 unknown）。
    绝不从 state 里的 user_idle / user_working / active_window 重建在场。
    """
    return state.get("idle_available") is True


@dataclass
class _Recent:
    action: str
    at: float = 0.0
    count: int = 0


class BehaviorEngine:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.behaviors: Dict[str, BehaviorDefinition] = {}
        self._recent: Dict[str, _Recent] = {}
        self.current: Optional[str] = None
        self.current_state: BehaviorState = BehaviorState.INTENT
        self._entered_at: float = 0.0
        self._min_stay: float = 6.0    # 滞回：行为最短停留，避免每 tick 翻车

    # -------------------------------------------------- 注册
    def register(self, defn: BehaviorDefinition) -> None:
        self.behaviors[defn.action] = defn

    # -------------------------------------------------- 生命周期（带时长滞回 + 行为链）
    def step(self, state: dict, now: float | None = None) -> Optional[str]:
        """调度：当前行为未到 duration/最短停留则保持；结束时可衔接行为链，否则重新选。

        FINAL Fallback Presence：在场未知（idle_available 非 True）时，user-dependent
        fallback 行为（observe_user/talk_to_user/approach_user）**不得**新选 / 延续 / 链入 ——
        本地回退（无 LifeBrain）不能绕过 World Truth（评审基线 e5ce9fb §3.1/§3.2/§3.3）。
        """
        now = time.monotonic() if now is None else now
        # §3.2：**已有** user-dependent fallback 行为 + 在场变未知 → 立即按现有 lifecycle
        # 语义中断（不等 duration/min-stay 结束 —— 不得继续假装用户已知在场），
        # 之后由 choose() 转入 SELF/survival。
        if self.current in _FALLBACK_USER_DEPENDENT and not _fallback_presence_known(state):
            self.interrupt(self.current, reason="user_presence_unknown")
            self.current = None
        if self.current and self.current in self.behaviors:
            dur = max(self.behaviors[self.current].duration, self._min_stay)
            if now - self._entered_at < dur:
                return self.current            # 仍在执行，保持
            done = self.current
            self.complete(done)                 # 时长到，结束
            defn = self.behaviors[done]
            # 行为链（legacy-plan/3 §22）：若定义了衔接且条件满足，直接进入，而不是重新 utility 选。
            # §3.3：链目标在**转场时重查 fallback 可行性** —— 未知在场不得因 chain_if 读到
            # 旧/原始字段（user_working/user_idle）而 observe_user→approach_user。
            if (defn.chain_to and defn.chain_to in self.behaviors
                    and (not defn.chain_if or defn.chain_if(state))
                    and not (defn.chain_to in _FALLBACK_USER_DEPENDENT
                             and not _fallback_presence_known(state))):
                self._entered_at = now
                nxt = defn.chain_to
                self.request_execution(nxt, self.behaviors[nxt].priority, reason=f"chain {done}->{nxt}")
                return nxt
        action = self.choose(state)
        if action and action != self.current:
            self._entered_at = now
            defn = self.behaviors.get(action)
            self.request_execution(action, defn.priority if defn else 4,
                                   reason=f"utility 选 {action}")
        return self.current

    # -------------------------------------------------- Utility 打分
    def utility_of(self, defn: BehaviorDefinition, state: dict) -> float:
        base = defn.base_utility
        if defn.utility_fn:
            base += defn.utility_fn(state)
        # 近期行为抑制（legacy-plan/3 §20）：刚刚做过的降权，避免机械重复
        rec = self._recent.get(defn.action)
        if rec:
            since = time.monotonic() - rec.at
            base -= max(0.0, 30.0 - since) * 0.5
            if rec.count >= 3:
                base -= 10
        # 打扰成本（legacy-plan/3 §10）：用户忙碌时,主动打扰类行为降权
        user_working = state.get("user_working", False)
        interrupting = ("talk", "play", "seek", "greet", "call", "ask")
        if user_working and any(k in defn.action.lower() for k in interrupting):
            base -= 60
        # 记忆偏置（legacy-plan/6 §28：记忆参与行为，而非只注入 prompt）
        bias = state.get("memory_bias") or {}
        if bias.get("social_penalty"):
            if any(k in defn.action.lower() for k in ("talk", "play", "seek", "greet", "call", "ask", "approach")):
                base -= bias["social_penalty"]
        if bias.get("approach_bonus") and "approach" in defn.action:
            base += bias["approach_bonus"]
        return base

    # -------------------------------------------------- 选择
    def choose(self, state: dict) -> Optional[str]:
        best: Optional[str] = None
        best_score = -1e9
        for action, defn in self.behaviors.items():
            # §3.1：**新选择** —— 在场未知时 user-dependent fallback 行为不进入选择空间
            # （utility 再高也不能选；否则 social_need 高时会在运行时明确不知道用户是否在场时
            # 发出 talk_to_user/observe_user/approach_user 的 ACTION_REQUEST —— 绕过 World Truth）。
            if action in _FALLBACK_USER_DEPENDENT and not _fallback_presence_known(state):
                continue
            score = self.utility_of(defn, state)
            if score > best_score:
                best_score = score
                best = action
        return best

    # -------------------------------------------------- 执行（骨架：提交 ActionRequest）
    def request_execution(self, action: str, priority: int, reason: str = "") -> None:
        self.current = action
        self.current_state = BehaviorState.INTENT
        rec = self._recent.setdefault(action, _Recent(action))
        rec.at = time.monotonic()
        rec.count += 1
        self.bus.emit(EventType.BEHAVIOR_STARTED, payload={"action": action, "reason": reason},
                      source="behavior")
        # 只发 ActionRequest，不由本层驱动渲染（legacy-plan/8 §3）
        self.bus.emit(EventType.ACTION_REQUEST,
                      payload={"source": "behavior", "action": action, "priority": priority,
                               "interruptible": self.behaviors[action].interruptible if action in self.behaviors else True},
                      source="behavior")

    def complete(self, action: str, result: BehaviorResult | None = None) -> None:
        self.current = None
        self.current_state = BehaviorState.COMPLETE
        self.bus.emit(EventType.BEHAVIOR_COMPLETED,
                      payload={"action": action, "result": (result.note if result else "")},
                      source="behavior")

    def interrupt(self, action: str, reason: str) -> None:
        self.current_state = BehaviorState.INTERRUPTED
        self.bus.emit(EventType.BEHAVIOR_INTERRUPTED, payload={"action": action, "reason": reason},
                      source="behavior")
