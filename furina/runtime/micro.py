"""Micro 生命调度（Phase 11）—— 呼吸/眨眼/视线/微动作，独立于 paintEvent 的真实时钟。

把当前 FurinaWindow 里"paintEvent 自己推进 _breath_t / 随机 gaze / 算 blink"迁出。
    QTimer → AnimationRuntime.tick → MicroScheduler.step(now) → 更新 blink/gaze/micro
    paintEvent 只读当前 blink/gaze/micro 值来画。

blink 用真实 next_at / started_at / duration / phase（不沿用旧的 `now - 未来时间` bug）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class MicroState:
    breath: float = 0.5          # 0..1 呼吸强度（sin 波形）
    blink: float = 0.0           # 0..1 闭眼强度（三角波）
    gaze: str = "front"          # front/left/right/up/down/user
    active_micro: List[str] = field(default_factory=list)  # 本帧命中的 micro 语义


class MicroScheduler:
    """呼吸 + 眨眼 + 视线变化 + 微动作偏好，全部独立时钟（确定性可测）。"""

    def __init__(self, fps: float = 30.0) -> None:
        self.fps = fps
        self.state = MicroState()
        self._t = 0.0                 # 呼吸相位（由 dt 累计，不假设 paint==16ms）
        # blink（真实生命：next_at / started_at / duration）
        self._blink_next = time.monotonic() + 3.0
        self._blink_start = 0.0
        self._blink_dur = 0.15
        # gaze
        self._gaze_next = time.monotonic() + 5.0
        self._gaze_pool = ["front", "front", "left", "right", "front", "up", "down"]
        self._gaze_i = 0
        # micro 偏好（来自 Frame.body.micro_preferences），带 recency 抑制
        self._micro_pref: List[str] = []
        self._micro_recent: List[str] = []
        self._micro_next = time.monotonic() + 4.0

    # -------------------------------------------------- 由 AnimationRuntime.tick 驱动
    def step(self, dt: float, now: float | None = None,
             micro_pref: Optional[List[str]] = None,
             tempo: str = "normal") -> MicroState:
        now = now or time.monotonic()
        self._t += max(0.0, dt)
        if micro_pref is not None:
            self._micro_pref = list(micro_pref)
        # 呼吸：sin，情绪/tempo 调制轻微
        self.state.breath = 0.5 + 0.5 * _sin(self._t * 2.4 + _sin(self._t * 0.7))
        # 眨眼：到达 next 则开始，按 started+dur 三角波
        if now >= self._blink_next:
            self._blink_next = now + 2.5 + ((now * 7) % 5.0)
            self._blink_start = now
        t = now - self._blink_start
        dur = self._blink_dur
        self.state.blink = (1.0 - abs(t - dur / 2) / (dur / 2)) if 0 <= t < dur else 0.0
        # 视线：到 next 则换一个（权重池，避免连续相同）
        if now >= self._gaze_next:
            self._gaze_next = now + 6.0 + ((now * 5) % 8.0)
            self._gaze_i = (self._gaze_i + 1) % len(self._gaze_pool)
            self.state.gaze = self._gaze_pool[self._gaze_i]
        # 微动作：从偏好里挑一个（recency 抑制 + tempo 调制频率），每 ~4-9s 一次
        self.state.active_micro = []
        if self._micro_pref and now >= self._micro_next:
            gap = self._micro_gap(tempo)
            self._micro_next = now + gap
            pick = self._pick_micro()
            if pick and pick != "NONE":
                self.state.active_micro = [pick]
        return self.state

    def _micro_gap(self, tempo: str) -> float:
        base = {"very_slow": 9.0, "slow": 7.0, "normal": 5.0, "lively": 3.5, "energetic": 2.5}.get(tempo, 5.0)
        return base + ((time.monotonic() * 3) % 2.0)

    def _pick_micro(self) -> str:
        # 基础生命：把 BREATH/BLINK 当作常驻（不由本层调度打断）；这里挑"装饰性"偏好
        cands = [m for m in self._micro_pref if m not in ("BLINK", "BREATH", "NONE")]
        cands = [m for m in cands if m not in self._micro_recent[-3:]] or cands or ["NONE"]
        self._micro_recent = (self._micro_recent + [cands[0]])[-6:]
        return cands[0]


def _sin(x: float) -> float:
    import math
    return math.sin(x)
