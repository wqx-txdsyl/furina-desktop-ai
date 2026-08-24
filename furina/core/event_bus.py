"""事件总线 —— 芙宁娜的“神经系统”（plan/8 §12）。

所有重要事情都变成 Event，模块之间通过显式事件通信，禁止硬编码相互调用
（工程铁律 #1 / #2 / #12）。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


class EventType(str, enum.Enum):
    """系统级事件枚举。

    各子系统可扩展自己的子类型，但统一走这个总线。首版先定义
    plan/8 §12 里列出的核心事件，后续按需扩充。
    """

    # ---- 交互输入 ----
    USER_CLICK = "user.click"
    USER_DRAG = "user.drag"
    USER_SPEAK = "user.speak"
    HEAD_TOUCHED = "interaction.head_touched"
    INTERACTION_INPUT = "interaction.input"

    # ---- 环境 ----
    WINDOW_CHANGED = "window.changed"
    WINDOW_FOCUSED = "window.focused"
    USER_IDLE = "user.idle"
    USER_RETURNED = "user.returned"
    ACTIVE_WINDOW_UPDATED = "perception.active_window"

    # ---- 状态 ----
    STATE_CHANGED = "state.changed"
    NEEDS_UPDATED = "state.needs_updated"
    INTENT_CHANGED = "state.intent_changed"

    # ---- Agent ----
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    AGENT_ASK_PERMISSION = "agent.ask_permission"

    # ---- 记忆 ----
    MEMORY_CREATED = "memory.created"
    MEMORY_RECALLED = "memory.recalled"

    # ---- 大脑/对话 ----
    BRAIN_SPOKE = "brain.spoke"

    # ---- 生命周期 ----
    SLEEP_STARTED = "life.sleep_started"
    WAKE_UP = "life.wake_up"
    SESSION_STARTED = "life.session_started"
    SESSION_ENDED = "life.session_ended"

    # ---- 行为 ----
    BEHAVIOR_STARTED = "behavior.started"
    BEHAVIOR_COMPLETED = "behavior.completed"
    BEHAVIOR_INTERRUPTED = "behavior.interrupted"
    ACTION_REQUEST = "action.request"
    ACTION_STARTED = "action.started"

    # ---- 运行时帧（Phase 10：唯一前端契约发布事件）----
    CHARACTER_FRAME_UPDATED = "runtime.character_frame_updated"

    # ---- 动画生命周期（Phase 11B）：completion exactly-once ----
    ANIMATION_COMPLETED = "runtime.animation_completed"
    TRANSITION_COMPLETED = "runtime.transition_completed"

    # ---- 空间生命周期（Phase 12）：movement exactly-once ----
    MOVEMENT_STARTED = "runtime.movement_started"
    SPATIAL_TARGET_REACHED = "runtime.target_reached"
    MOVEMENT_INTERRUPTED = "runtime.movement_interrupted"


@dataclass
class Event:
    type: EventType
    payload: Any = None
    source: str = ""                      # 来源模块，如 "interaction"
    timestamp: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Event], None]


class EventBus:
    """同步事件总线（骨架版）。

    后续可替换为基于 ``anyio``/线程队列的异步总线，接口保持不变（拔插）。
    """

    def __init__(self) -> None:
        self._handlers: Dict[EventType, List[Handler]] = {}
        self._wildcard: List[Handler] = []
        self._history: List[Event] = []
        self._history_limit = 500

    # -- 订阅 --
    def on(self, etype: EventType, handler: Handler) -> None:
        self._handlers.setdefault(etype, []).append(handler)

    def on_any(self, handler: Handler) -> None:
        self._wildcard.append(handler)

    def off(self, etype: EventType, handler: Handler) -> None:
        if etype in self._handlers:
            self._handlers[etype] = [h for h in self._handlers[etype] if h is not handler]

    # -- 发布 --
    def emit(self, etype: EventType, payload: Any = None, source: str = "", **meta: Any) -> Event:
        ev = Event(type=etype, payload=payload, source=source, meta=meta)
        self._history.append(ev)
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit :]
        for h in list(self._handlers.get(etype, [])):
            h(ev)
        for h in list(self._wildcard):
            h(ev)
        return ev

    def publish(self, event: Event) -> Event:
        """直接发布一个构造好的 Event。"""
        self._history.append(event)
        for h in list(self._handlers.get(event.type, [])):
            h(event)
        for h in list(self._wildcard):
            h(event)
        return event

    def recent(self, n: int = 50) -> List[Event]:
        return self._history[-n:]

    def clear(self) -> None:
        self._history.clear()
