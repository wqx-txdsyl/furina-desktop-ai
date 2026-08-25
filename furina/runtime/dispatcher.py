"""Phase 13 FINAL-R1 §3：运行时 owner 线程分发边界。

契约：
  owner 线程（GUI/main / step() / drain() 调用者）：
    确定性域变更（Emotion/Relationship/Memory/Life）、Director 队列变更、最终事件应用
  worker 线程：
    LLM 网络 I/O、工具执行 / 慢 OS I/O、只读快照计算

worker 把"域变更/最终应用"提交为可调用对象，由 owner 在 drain() 时统一执行。
用 `queue.SimpleQueue`（显式队列，非 list.append+GIL 依赖）。
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Callable, List, Optional


class RuntimeDispatcher:
    """owner 线程分发器：submit(fn)（任意线程）→ drain()（owner 线程执行）。"""

    def __init__(self) -> None:
        self._q: "queue.SimpleQueue" = queue.SimpleQueue()
        self._owner: Optional[int] = None
        self._owner_lock = threading.Lock()
        self._violations: List[str] = []      # 非 owner 调用 guard 的记录（诊断）
        self._violations_lock = threading.Lock()

    # -------------------------------------------------- owner 绑定
    def bind_owner(self) -> int:
        """owner 线程 = 第一次绑定/排空时的线程（GUI/main 或测试主线程）。"""
        with self._owner_lock:
            if self._owner is None:
                self._owner = threading.get_ident()
            return self._owner

    @property
    def owner_thread_id(self) -> Optional[int]:
        return self._owner

    def is_owner(self) -> bool:
        return self._owner is not None and threading.get_ident() == self._owner

    def require_owner(self, what: str) -> None:
        """域变更守卫：非 owner 线程调用 → 记录违规并抛错（生产契约，测试可断言）。"""
        self.bind_owner()
        if threading.get_ident() != self._owner:
            with self._violations_lock:
                self._violations.append(f"{what}@thread{threading.get_ident()}")
            raise RuntimeError(
                f"domain mutation '{what}' must run on owner thread "
                f"(owner={self._owner}, current={threading.get_ident()})")

    def violations(self) -> List[str]:
        with self._violations_lock:
            return list(self._violations)

    # -------------------------------------------------- 队列
    def submit(self, fn: Callable[[], Any]) -> None:
        """任意线程提交"owner 执行"的工作项。"""
        self._q.put(fn)

    def drain(self) -> int:
        """owner 线程逐条执行（当前线程）；返回执行条数。"""
        self.bind_owner()
        n = 0
        while True:
            try:
                fn = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
                n += 1
            except Exception:  # pragma: no cover — 单项失败不拖垮 drain
                pass
        return n

    def pending(self) -> int:
        return self._q.qsize()
