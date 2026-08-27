"""D3 — Retrieval Exposure Ledger（session-local、derived、非权威）。

- 仅记录“最近哪些 C3 记忆被成功装配进上下文”，用于对**自动注入**的重复曝光做
  有界冷却（suppress/penalize）。它不是遗忘，更不是真值 —— C3 权威行一字不动。
- 结构：LRU 字典 {ref_key: last_exposed_monotonic}（Bounded + TTL 到期自动失效）。
- 重启即清空（session-local；无持久化），source truth 完全不受影响。
- 显式用户召回（``is_recall_intent``）绕过冷却。

mark-after-success 契约由调用方（context.assemble）保证：只有真正进入最终
CognitiveContext 的对象才会被 mark；候选生成/装配失败不产生任何记录。
"""
from __future__ import annotations

import re
import time
from collections import OrderedDict
from typing import Dict, Optional, Tuple

DEFAULT_EXPOSURE_TTL_SECONDS = 900.0     # 15 分钟：同一记忆冷却窗口
DEFAULT_EXPOSURE_CAPACITY = 256          # LRU 上限（有界）

# D3 显式召回意图（deterministic/bounded；绝不做自由 LLM 分类）
_RECALL_INTENT_RE = re.compile(
    r"你还记得|刚才(?:你)?(?:说|提|讲)|再说说|再说一次|重复一下"
    r"|之前(?:你)?(?:说|提)(?:的|过)|我之前(?:说|提)过|想起来了吗")


def is_recall_intent(text: str) -> bool:
    """确定性显式召回意图判定（bounded regex；绝不调 LLM）。"""
    t = (text or "").strip()
    return bool(t and _RECALL_INTENT_RE.search(t))


class RetrievalExposureLedger:
    """有界 session-local 曝光账本（OPERATIONAL / DERIVED / NON-AUTHORITATIVE）。"""

    def __init__(self, *, ttl_seconds: float = DEFAULT_EXPOSURE_TTL_SECONDS,
                 capacity: int = DEFAULT_EXPOSURE_CAPACITY,
                 time_fn=None) -> None:
        self._ttl = float(max(0.0, ttl_seconds))
        self._capacity = int(max(1, capacity))
        self._time_fn = time_fn or _time_monotonic
        self._store: "OrderedDict[str, float]" = OrderedDict()

    # -------------------------------------------------- internals
    def _now(self) -> float:
        try:
            return float(self._time_fn())
        except Exception:
            return 0.0

    def _purge_expired(self) -> None:
        now = self._now()
        cutoff = now - self._ttl
        expired = [k for k, ts in self._store.items() if ts < cutoff]
        for k in expired:
            self._store.pop(k, None)

    # -------------------------------------------------- public API
    @staticmethod
    def key_for(ref_id: str, store: str = "C3") -> str:
        return f"{store}:{ref_id}"

    def mark(self, ref_key: str, *, now: Optional[float] = None) -> None:
        """标记一次成功曝光（调用方仅在对象进入最终 context 后调用）。"""
        if not ref_key:
            return
        ts = now if now is not None else self._now()
        self._store.pop(ref_key, None)                  # 刷新位置（LRU）
        self._store[ref_key] = float(ts)
        while len(self._store) > self._capacity:         # LRU 淘汰最旧
            self._store.popitem(last=False)

    def cooled(self, ref_key: str, *, now: Optional[float] = None) -> bool:
        """是否处于冷却窗口内（TTL 内被成功曝光过）。"""
        if not ref_key or self._ttl <= 0:
            return False
        n = now if now is not None else self._now()
        ts = self._store.get(ref_key)
        if ts is None:
            return False
        return (n - ts) < self._ttl

    def snapshot(self) -> Dict[str, float]:
        """只读视图（诊断/测试；不构成 truth）。"""
        self._purge_expired()
        return dict(self._store)

    def reset(self) -> None:
        self._store.clear()


def _time_monotonic() -> float:
    import time
    return time.monotonic()
