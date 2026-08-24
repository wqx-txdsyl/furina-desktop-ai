"""行为引擎（plan/3 §8-9, §15-19）。

- Utility AI：对候选行为打分（不止需求，含 context/cooldown/interruption）。
- LLM 只赐高价值决策；本地环路处理日常。
- 行为最终通过 ActionRequest 提交 Director，本层**不直接驱动渲染**（plan/8 §3）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from furina.core import EventBus, EventType, get_logger
from furina.state.state_model import Intent, IntentCategory, MacroState
from .behavior_types import BehaviorDefinition, BehaviorResult, BehaviorState

log = get_logger("behavior")

# plan/8 §9 —— LLM 只能在这些枚举里选
ALLOWED_INTENTS: Dict[IntentCategory, List[str]] = {
    IntentCategory.SURVIVE: ["eat", "drink", "sleep"],
    IntentCategory.INTERACT: ["greet", "talk", "play", "seek_attention"],
    IntentCategory.SELF: ["explore", "read", "relax", "wander"],
    IntentCategory.USER: ["observe", "help", "remind", "accompany"],
    IntentCategory.AGENT: ["understand", "plan", "execute", "report"],
}


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

    # -------------------------------------------------- 生命周期（带时长滞回）
    # -------------------------------------------------- 生命周期（带时长滞回 + 行为链）
    def step(self, state: dict, now: float | None = None) -> Optional[str]:
        """调度：当前行为未到 duration/最短停留则保持；结束时可衔接行为链，否则重新选。"""
        now = time.monotonic() if now is None else now
        if self.current and self.current in self.behaviors:
            dur = max(self.behaviors[self.current].duration, self._min_stay)
            if now - self._entered_at < dur:
                return self.current            # 仍在执行，保持
            done = self.current
            self.complete(done)                 # 时长到，结束
            defn = self.behaviors[done]
            # 行为链（plan/3 §22）：若定义了衔接且条件满足，直接进入，而不是重新 utility 选
            if defn.chain_to and defn.chain_to in self.behaviors and (not defn.chain_if or defn.chain_if(state)):
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
        # 近期行为抑制（plan/3 §20）：刚刚做过的降权，避免机械重复
        rec = self._recent.get(defn.action)
        if rec:
            since = time.monotonic() - rec.at
            base -= max(0.0, 30.0 - since) * 0.5
            if rec.count >= 3:
                base -= 10
        # 打扰成本（plan/3 §10）：用户忙碌时,主动打扰类行为降权
        user_working = state.get("user_working", False)
        interrupting = ("talk", "play", "seek", "greet", "call", "ask")
        if user_working and any(k in defn.action.lower() for k in interrupting):
            base -= 60
        # 记忆偏置（plan/6 §28：记忆参与行为，而非只注入 prompt）
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
        # 只发 ActionRequest，不由本层驱动渲染（plan/8 §3）
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
