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
    """单个直接回合的可观测记录（terminal 历史 bounded 保留；活跃 turn 绝不丢弃）。"""

    def __init__(self, turn_id: int, ingress_seq: Optional[int], user_text: str,
                 channel: str = "DIRECT_USER_TURN") -> None:
        self.turn_id = turn_id
        # R1.2-2：turn_id 是完整用户 ingress identity；未显式给 ingress_seq 时以 turn_id 充当
        self.ingress_seq = ingress_seq if ingress_seq is not None else turn_id
        self.user_text = user_text
        self.channel = channel
        # R10（Phase 14 R6–R12）：两阶段 ingress —— RESERVED（identity 已分配、deadline 已起算、
        # 未入队）→ QUEUED → GENERATING → 终态。reserved 后被 cancel_reserved 的 turn 直接
        # 进入终态 CANCELLED（可观察，无 sequence hole）。
        self.status = "RESERVED"        # RESERVED → QUEUED → GENERATING → 终态
        self.failure_reason: str = ""
        self.latency_ms: float = 0.0
        self.created_at = time.time()
        # R2.1 P0-3：validation telemetry（为什么被拦/被放行）
        self.validation_issues: list = []
        self.hard_issues: list = []
        self.soft_issues: list = []
        # R1.2-1：deadline 在 **ingress/reserve 时刻** 设定（ingress→terminal 全生命周期预算，
        # 排队时间计入）；worker 绝不重置 —— 轮到 worker 时已过 deadline 必须快速 FAILED。
        self.created_monotonic: float = 0.0
        self.deadline: float = 0.0

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
            "validation_issues": list(self.validation_issues),
            "hard_issues": list(self.hard_issues),
            "soft_issues": list(self.soft_issues),
        }


class DirectDialogueQueue:
    """专用直接对话串行队列（单 worker FIFO 消费；owner 线程 submit 立即返回）。

    R1.2-1：`timeout` = **从 ingress（submit 时刻）到 terminal 的整个直接回合总预算**
    —— submit 时为 turn 设 `deadline = created_monotonic + timeout`，覆盖 queue wait +
    生成 + retry；worker **绝不重置** deadline（排队时间计入预算；已过 deadline 的回合
    快速 FAILED，不得再获得新预算）。processor 把它传给 DialogueBrain。
    R1.1-2/R1.2-4：`keep_outcomes` 只限制 **terminal 历史** 的保留条数（submit 与
    终态转换后都 trim）；QUEUED/GENERATING 的活跃 turn 永远保留。
    R1.2-2：`turn_id` 是完整用户 ingress identity；未显式给 ingress_seq 时以 turn_id 充当。
    """

    def __init__(self, bus=None, timeout: float = 30.0,
                 keep_outcomes: int = 100) -> None:
        self.bus = bus
        self.timeout = timeout           # R1.2-1：整回合 ingress→terminal 总预算（submit 时定 deadline）
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
        """owner 线程：入队一个直接对话回合，立即返回 turn_id。

        R1.2-1：deadline 在此（ingress 时刻）设定 = created_monotonic + timeout，
        覆盖 queue wait + 生成 + retry 的**整个**直接回合生命周期（用户可见总预算）。
        """
        with self._lock:
            self._next_turn_id += 1
            turn_id = self._next_turn_id
            turn = DirectTurn(turn_id, ingress_seq, user_text)
            turn.created_monotonic = time.monotonic()
            turn.deadline = turn.created_monotonic + self.timeout
            turn.status = "QUEUED"
            self._turns[turn_id] = turn
            self._order.append(turn_id)
            self._trim_locked()
        self._trace(turn, "DIRECT_INGRESS")
        self._trace(turn, "QUEUED")
        self._ensure_started()
        self._q.put((turn_id, snapshot))
        return turn_id

    # -------------------------------------------------- R10：两阶段 ingress（Phase 14 R6–R12）
    def reserve_turn(self, user_text: str = "") -> int:
        """owner：reserve 一个 direct turn identity（ingress 即起算 deadline；不启动 worker）。

        R10 用途：owner 语义效果（record USER_MESSAGE → apply C4）需要**先于**入队拿到
        turn_id —— 这样 transition 事件能精确绑定 canonical USER_MESSAGE 事件与 turn。
        之后必须调用 ``submit_reserved``（正常）或 ``cancel_reserved``（准备失败）——
        保证无 sequence hole / 无永久 pending。
        """
        with self._lock:
            self._next_turn_id += 1
            turn_id = self._next_turn_id
            turn = DirectTurn(turn_id, None, user_text)
            turn.created_monotonic = time.monotonic()
            turn.deadline = turn.created_monotonic + self.timeout
            self._turns[turn_id] = turn
            self._order.append(turn_id)
            self._trim_locked()
        self._trace(turn, "DIRECT_INGRESS")
        return turn_id

    def submit_reserved(self, turn_id: int, snapshot, user_text: str = "") -> None:
        """owner：把已 reserve 的 turn 入队（严格按 reserve 顺序 FIFO；deadline 保持 reserve 时刻）。"""
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                return
            if turn.status != "RESERVED":
                return                    # 已入队/已终态 → 幂等跳过
            turn.status = "QUEUED"
            if user_text:
                turn.user_text = user_text
        self._trace(turn, "QUEUED")
        self._ensure_started()
        self._q.put((turn_id, snapshot))

    def cancel_reserved(self, turn_id: int, reason: str = "owner_prep_failed") -> None:
        """owner：reserve 后 owner 侧准备失败 → 该 turn 到达可观察终态 CANCELLED。

        R10-T7：失败不得留下永久 pending / sequence hole —— 后续 reserve 照常分配新 id。
        """
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None or turn.status != "RESERVED":
                return                    # 幂等：仅 RESERVED 可取消
            turn.status = "CANCELLED"
            turn.failure_reason = reason
        self._trace(turn, "CANCELLED", failure_reason=reason)

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
                continue   # R1.1-2：活跃 turn 永不 trim → 此分支实际不可达（防御）
            t0 = time.perf_counter()
            self._set_status(turn, "GENERATING")
            self._trace(turn, "GENERATION_STARTED")
            try:
                if self._processor is None:
                    out: dict = {"speech": None, "failure_reason": "no_processor"}
                else:
                    # R1.2-1：绝不重置 deadline —— processor/brain 用 turn.deadline 的
                    # remaining（已过 deadline → 立即 generation_timeout，不给新预算）
                    out = self._processor(turn, snapshot) or {}
                latency = (time.perf_counter() - t0) * 1000.0
                speech = out.get("speech")
                if speech:
                    self._finish(turn, "REPLIED", "", latency, out=out)
                else:
                    reason = str(out.get("failure_reason") or "") or "generation_failed"
                    self._finish(turn, "FAILED", reason, latency, out=out)
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

    def _finish(self, turn: DirectTurn, status: str, reason: str, latency_ms: float,
                out: Optional[dict] = None) -> None:
        with self._lock:
            turn.status = status
            turn.failure_reason = reason
            turn.latency_ms = latency_ms
            if out:
                # R2.1 P0-3：validation telemetry（为什么被拦/被放行）
                turn.validation_issues = list(out.get("validation_issues") or [])
                turn.hard_issues = list(out.get("hard_issues") or [])
                turn.soft_issues = list(out.get("soft_issues") or [])
            # R1.2-4：终态转换后立即 trim terminal history —— retained terminal ≤ keep_outcomes
            # （活跃 turn 永不 trim；trim 只移除 registry，本 turn 局部引用仍可发 terminal trace）
            self._trim_locked()
        self._trace(turn, status, latency_ms=latency_ms, failure_reason=reason)

    def _trim_locked(self) -> None:
        """R1.1-2：只清理 **terminal** 历史观测；QUEUED/GENERATING 活跃 turn 绝不删除。

        单 worker 串行消费 → 终态按入队顺序形成前缀；从最旧开始移除超出 keep_outcomes
        的 terminal 记录，遇到活跃 turn（或已删除）立即停止。keep_outcomes 只限
        terminal history 条数，不影响活跃 turn（否则 worker 取到 None → 丢消息 +
        direct seq 永久缺口）。
        """
        if len(self._order) <= self._keep:
            return
        removed = 0
        while removed < len(self._order) and len(self._order) - removed > self._keep:
            tid = self._order[removed]
            t = self._turns.get(tid)
            if t is None or t.status not in TERMINAL_STATUSES:
                break
            self._turns.pop(tid, None)
            removed += 1
        if removed:
            self._order = self._order[removed:]

    # -------------------------------------------------- 可观测性
    def _trace(self, turn: DirectTurn, phase: str, latency_ms: float = 0.0,
               failure_reason: str = "") -> None:
        if self.bus is None:
            return
        try:
            # R2.1.1 P0-3：validation telemetry 进入 DIRECT_TURN_TRACE（EventBus 直读，不依赖 private）
            self.bus.emit(EventType.DIRECT_TURN_TRACE, payload={
                "turn_id": turn.turn_id,
                "ingress_seq": turn.ingress_seq,
                "channel": turn.channel,
                "phase": phase,
                "status": turn.status,
                "latency_ms": round(latency_ms, 1),
                "failure_reason": failure_reason,
                "user_text": (turn.user_text or "")[:40],
                "validation_issues": list(getattr(turn, "validation_issues", []) or []),
                "hard_issues": list(getattr(turn, "hard_issues", []) or []),
                "soft_issues": list(getattr(turn, "soft_issues", []) or []),
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
