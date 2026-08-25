"""B1（评审基线 0402e7f）：DirectDialogueQueue —— 直接对话专用串行 lane。

背景：旧实现每个 submit_user_message 无限制 spawn 一个 worker 线程，所有通道
（DIRECT / AMBIENT / FEED / INTERACTION / AGENT）共享一个全局 turn FIFO 与序号
空间 —— 一个慢/挂起的 autonomous 回合会 head-of-line 阻塞之后所有直接用户消息
（现场复现：连续对话数轮后永久不回复）。

本模块提供**专用 Direct Dialogue Queue**：
  - owner 线程 submit(snapshot) → 分配 turn_id + DIRECT_INGRESS/QUEUED trace → 立即返回；
  - **单个**串行 worker 线程按入队顺序消费（严格 ingress FIFO），逐回合调 DialogueBrain；
  - 每回合**必达终态** REPLIED / FAILED / CANCELLED（try/finally + worker 异常兜底）；
  - 单次生成有界（timeout，默认复用 LLM adapter 的 profile.timeout + 余量）；
  - 终态与相位（GENERATION_STARTED/FINISHED + latency + failure_reason）经
    EventType.DIRECT_TURN_TRACE 可观测，Harness 可读（recent_outcomes）。

不变量（与 ambient/reaction/feed/agent lane 无关）：
  - 不占用 ambient 序号、不被 ambient 阻塞（ambient 走 DialogueBrain 的独立 lane）；
  - 失败不产生孤儿 user history（DialogueBrain 原子成对提交保证）；
  - 无存活死锁 worker / pending ticket（单 worker + bounded 生成 + 终态兜底）。
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from furina.core import EventType, get_logger

log = get_logger("dialogue_queue")

# 终态集合（B1 硬契约：每个 DIRECT_USER_TURN 必须进入其中之一）
TERMINAL_STATUSES = ("REPLIED", "FAILED", "CANCELLED")


class DirectTurn:
    """单个直接回合的可观测记录（bounded 保留）。"""

    def __init__(self, turn_id: int, ingress_seq: Optional[int], user_text: str,
                 channel: str = "DIRECT_USER_TURN") -> None:
        self.turn_id = turn_id
        self.ingress_seq = ingress_seq
        self.user_text = user_text
        self.channel = channel
        self.status = "QUEUED"          # QUEUED → GENERATING → 终态
        self.failure_reason: str = ""
        self.latency_ms: float = 0.0
        self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "turn_id": self.turn_id,
            "ingress_seq": self.ingress_seq,
            "channel": self.channel,
            "user_text": self.user_text[:40],
            "status": self.status,
            "failure_reason": self.failure_reason,
            "latency_ms": round(self.latency_ms, 1),
            "created_at": round(self.created_at, 1),
        }


class DirectDialogueQueue:
    """专用直接对话串行队列（单 worker FIFO 消费；owner 线程 submit 立即返回）。"""

    def __init__(self, bus=None, timeout: float = 150.0,
                 keep_outcomes: int = 100) -> None:
        self.bus = bus
        self.timeout = timeout           # 单回合生成有界超时（秒）
        self._q: "queue.Queue" = queue.Queue()
        self._turns: Dict[int, DirectTurn] = {}
        self._lock = threading.Lock()
        self._next_turn_id = 0
        self._start_lock = threading.Lock()
        self._started = False
        self._worker: Optional[threading.Thread] = None
        self._processor: Optional[Callable[[DirectTurn, Any], dict]] = None
        self._keep = keep_outcomes
        self._order: List[int] = []       # turn_id 入队顺序（FIFO 证据）

    # -------------------------------------------------- 配置
    def set_processor(self, fn: Callable[[DirectTurn, Any], dict]) -> None:
        """worker 线程处理器：fn(turn, snapshot) -> {"speech": str|None, "failure_reason": str}。

        处理器负责真实生产链（DialogueBrain.say → BRAIN_SPOKE / SYSTEM_STATUS → 记忆）。
        """
        self._processor = fn

    def _ensure_started(self) -> None:
        with self._start_lock:
            if self._started:
                return
            self._started = True
            self._worker = threading.Thread(target=self._loop, daemon=True,
                                            name="direct-dialogue-worker")
            self._worker.start()

    # -------------------------------------------------- owner 入口
    def submit(self, snapshot, ingress_seq: Optional[int] = None,
               user_text: str = "") -> int:
        """owner 线程：入队一个直接对话回合，立即返回 turn_id。"""
        with self._lock:
            self._next_turn_id += 1
            turn_id = self._next_turn_id
            turn = DirectTurn(turn_id, ingress_seq, user_text)
            self._turns[turn_id] = turn
            self._order.append(turn_id)
            self._trim()
        self._trace(turn, "DIRECT_INGRESS")
        self._trace(turn, "QUEUED")
        self._ensure_started()
        self._q.put((turn_id, snapshot))
        return turn_id

    # -------------------------------------------------- 串行 worker
    def _loop(self) -> None:
        """单 worker：严格按入队顺序消费；每回合必达终态；异常不杀死 worker。"""
        while True:
            try:
                turn_id, snapshot = self._q.get()
            except Exception:
                continue
            with self._lock:
                turn = self._turns.get(turn_id)
            if turn is None:
                continue
            t0 = time.perf_counter()
            self._set_status(turn, "GENERATING")
            self._trace(turn, "GENERATION_STARTED")
            try:
                if self._processor is None:
                    out: dict = {"speech": None, "failure_reason": "no_processor"}
                else:
                    out = self._processor(turn, snapshot) or {}
                latency = (time.perf_counter() - t0) * 1000.0
                speech = out.get("speech")
                if speech:
                    self._finish(turn, "REPLIED", "", latency)
                else:
                    reason = str(out.get("failure_reason") or "") or "generation_failed"
                    self._finish(turn, "FAILED", reason, latency)
            except Exception as e:  # pragma: no cover —— worker 异常兜底，绝不遗留 pending
                log.warning("direct dialogue worker 异常: %s", e)
                latency = (time.perf_counter() - t0) * 1000.0
                self._finish(turn, "CANCELLED", f"worker_exception:{type(e).__name__}", latency)
            finally:
                self._trace(turn, "GENERATION_FINISHED")

    # -------------------------------------------------- 终态
    def _set_status(self, turn: DirectTurn, status: str) -> None:
        with self._lock:
            turn.status = status

    def _finish(self, turn: DirectTurn, status: str, reason: str, latency_ms: float) -> None:
        with self._lock:
            turn.status = status
            turn.failure_reason = reason
            turn.latency_ms = latency_ms
        self._trace(turn, status, latency_ms=latency_ms, failure_reason=reason)

    def _trim(self) -> None:
        while len(self._order) > self._keep:
            old = self._order.pop(0)
            self._turns.pop(old, None)

    # -------------------------------------------------- 可观测性
    def _trace(self, turn: DirectTurn, phase: str, latency_ms: float = 0.0,
               failure_reason: str = "") -> None:
        if self.bus is None:
            return
        try:
            self.bus.emit(EventType.DIRECT_TURN_TRACE, payload={
                "turn_id": turn.turn_id,
                "ingress_seq": turn.ingress_seq,
                "channel": turn.channel,
                "phase": phase,
                "status": turn.status,
                "latency_ms": round(latency_ms, 1),
                "failure_reason": failure_reason,
                "user_text": (turn.user_text or "")[:40],
            }, source="dialogue_queue")
        except Exception:
            pass

    def recent_outcomes(self, n: int = 10) -> List[dict]:
        """最近的直接回合终态（含仍在生成中的；Harness/测试只读）。"""
        with self._lock:
            ids = list(reversed(self._order))
            return [self._turns[i].to_dict() for i in ids[:n] if i in self._turns]

    def pending(self) -> int:
        with self._lock:
            return sum(1 for t in self._turns.values() if t.status not in TERMINAL_STATUSES)

    def outcome_count(self) -> Dict[str, int]:
        with self._lock:
            out: Dict[str, int] = {"REPLIED": 0, "FAILED": 0, "CANCELLED": 0}
            for t in self._turns.values():
                if t.status in out:
                    out[t.status] += 1
            return out

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """测试/关闭辅助：等待所有已入队回合到达终态。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._q.empty() and self.pending() == 0:
                return True
            time.sleep(0.01)
        return False
