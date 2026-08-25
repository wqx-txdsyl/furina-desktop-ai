"""Director（legacy-plan/8）—— 唯一允许解决“谁拥有行动控制权”的模块。

优先级（legacy-plan/8 §1）：
Safety/User Control > Direct User Interaction > Active Agent Task
> Important Internal Need > Autonomous Behavior > Idle/Micro。

铁律：只有 Director 能把动作路由到 Character Runtime（legacy-plan/8 §3）。
其它模块只发 ActionRequest。
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from furina.core import EventBus, EventType, get_logger
from .action_queue import ActionRequest

log = get_logger("director")

# legacy-plan/8 §1 优先级（数字越小越高）
P_SAFETY = 0
P_USER_INTERACTION = 1
P_AGENT_TASK = 2
P_INTERNAL_NEED = 3
P_AUTONOMOUS = 4
P_IDLE_MICRO = 5


class Director:
    """仲裁竞态动作，产出唯一“当前应执行”的动作。"""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._queue: List[ActionRequest] = []
        self._current: Optional[ActionRequest] = None
        self._on_execute: Optional[Callable[[ActionRequest], None]] = None
        # H1 §8：实际替换回调（on_before_replace(old, new)）—— 高优先级请求接管当前动作时触发，
        # 让运行时能立即 finalize 被抢占的活动实例（elapsed 停在接管时刻）。
        self.on_before_replace: Optional[Callable[[Optional[ActionRequest], ActionRequest], None]] = None
        # 订阅其它模块的 ActionRequest
        bus.on(EventType.ACTION_REQUEST, lambda ev: self.submit(
            ActionRequest(source=ev.payload.get("source", ev.source),
                          action=ev.payload["action"],
                          priority=ev.payload.get("priority", P_AUTONOMOUS),
                          interruptible=ev.payload.get("interruptible", True),
                          reason=ev.payload.get("reason", ""))))

    def set_executor(self, fn: Callable[[ActionRequest], None]) -> None:
        """注册真正执行动作的 Runtime handler（仅 Director 能调用它）。"""
        self._on_execute = fn

    def submit(self, req: ActionRequest) -> None:
        # 只入队，不立即执行；真正的竞态仲裁在 drain()（legacy-plan/8 §2-3）
        heapq.heappush(self._queue, (req.priority, _seq(), req))

    def cancel(self, source: str | None = None) -> None:
        if source:
            self._queue = [r for r in self._queue if r[2].source != source]
        heapq.heapify(self._queue)
        log.info("director: cancel(%s), queue=%d", source, len(self._queue))

    def drain(self) -> None:
        """仲裁：从队列取最高优先级请求执行。

        优先级契约（数字越小越高；legacy-plan/3 §18 + Final Gate §1）：
          - **严格更低优先级（req.priority > current.priority）永不替换更高优先级当前动作**
            （与 interruptible 无关 —— 否则 active Agent 会被排队中的低优先级 mind 顶掉）。
          - 同优先级：保留既有语义（current.interruptible=False 时不可替换；
            Agent 阶段→阶段等 interruptible=True 的同级请求可继续替换）。
          - 更高优先级（req.priority < current.priority）：按既有策略抢占。
        系统每 Medium Tick 调用一次（app/scheduler 注入）。
        """
        if not self._queue:
            return
        req = heapq.heappop(self._queue)[2]
        if self._current is not None:
            if req.priority > self._current.priority:
                # 严格更低优先级 → 放回队列等待（Agent 必须保持 current）
                heapq.heappush(self._queue, (req.priority, _seq(), req))
                return
            if req.priority == self._current.priority and self._current.interruptible is False:
                heapq.heappush(self._queue, (req.priority, _seq(), req))
                return
            # req.priority < current.priority → 更高优先级可抢占（既有策略）
        # H1 §8：真正发生**替换**（旧动作被新动作接管）→ 先通知回调（finalize 被抢占的活动）
        if self._current is not None and self._current is not req and self.on_before_replace is not None:
            try:
                self.on_before_replace(self._current, req)
            except Exception:  # pragma: no cover
                pass
        self._current = req
        log.debug("director: -> %s", req.describe())
        if self._on_execute:
            self._on_execute(req)
        self.bus.emit(EventType.ACTION_STARTED, payload=req.describe(), source="director")

    def current(self) -> Optional[ActionRequest]:
        return self._current

    def clear_current(self) -> None:
        """当前动作已完成/被接管 → 释放，允许下一轮重新仲裁。

        否则 `_current` 永不清空：一个不可中断的当前动作会永久压制后续请求（死锁隐患）。
        """
        self._current = None

    def finish(self, source: str | None = None) -> None:
        """当前动作结束：若是该 source 的动作，则释放接管权。"""
        if source is None or (self._current and self._current.source == source):
            self._current = None


# 稳定编号，避免 priority 相同时 heapq 比较 ActionRequest 出错
_seq_counter = [0]


def _seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]
