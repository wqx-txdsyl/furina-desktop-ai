"""时钟与三档 Tick（legacy-plan/7 §42）。

- Fast   ~60 FPS：render / animation / input
- Medium ~1-5s：state update / idle behavior / window awareness
- Slow   ~1-10min：memory / relationship / long-term behavior
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, List


@dataclass
class Ticker:
    interval: float
    callback: Callable[[float], None]       # 参数为 dt（秒）
    _last: float = 0.0

    def tick(self, now: float) -> bool:
        if now - self._last >= self.interval:
            dt = (now - self._last) if self._last else self.interval
            self._last = now
            self.callback(dt)
            return True
        return False


class Clock:
    """手动驱动的时钟：由主渲染循环调用 ``step()``。

    骨架版用单调时钟；后续可加“游戏时间/真实时间”双时间轴。
    """

    def __init__(self, fast: float = 1 / 60, medium: float = 3.0, slow: float = 120.0) -> None:
        self.fast_interval = fast
        self.medium_interval = medium
        self.slow_interval = slow
        self._fast: List[Ticker] = []
        self._medium: List[Ticker] = []
        self._slow: List[Ticker] = []
        self._now = 0.0

    @property
    def now(self) -> float:
        return self._now

    def schedule(self, bucket: str, interval: float, callback: Callable[[float], None]) -> None:
        ticker = Ticker(interval=interval, callback=callback)
        target = {"fast": self._fast, "medium": self._medium, "slow": self._slow}[bucket]
        target.append(ticker)

    def step(self, dt: float | None = None) -> None:
        """推进一帧；dt 缺省用真实时间差。"""
        real = time.monotonic()
        if self._now <= 0:
            self._now = real
        dt = dt if dt is not None else (real - self._now)
        self._now = real
        for t in self._fast:
            t.tick(real)
        for t in self._medium:
            t.tick(real)
        for t in self._slow:
            t.tick(real)
