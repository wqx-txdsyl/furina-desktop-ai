"""C3 — Runtime Autobiographical Memory（adapter on existing MemoryEngine）。

**禁止新建第二张 memory 表。** C3 只写 desktop-era experiences 到既有 `memories` 表，
一切持久化/检索/治理都委托 existing MemoryEngine/MemoryStore。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from furina.core import get_logger
from furina.memory import MemoryEngine, MemoryLevel, MemorySource

log = get_logger("cognition.autobiography")


class AutobiographicalMemoryStore:
    """C3 adapter：包装 MemoryEngine，暴露认知层需要的最小接口（不复制写两遍）。"""

    def __init__(self, engine: MemoryEngine) -> None:
        self._engine = engine

    # -------------------------------------------------- write（delegate，单一 owner = MemoryEngine）
    def observe(self, content: str, *, level: MemoryLevel = MemoryLevel.EPISODIC,
                source: MemorySource = MemorySource.SYSTEM, importance: float = 0.4,
                context: str = "", outcome: str = ""):
        """桌面时代经历 → existing MemoryEngine.observe（未达阈值则不入库）。"""
        return self._engine.observe(content, level=level, source=source,
                                    importance=importance, context=context, outcome=outcome)

    def consolidate(self, exp) -> Optional[object]:
        """委托 existing MemoryEngine.consolidate（Experience → 长期记忆）。"""
        return self._engine.consolidate(exp)

    # -------------------------------------------------- read
    def retrieve(self, *, query: str = "", limit: int = 3, context: Optional[str] = None):
        return self._engine.retrieve(query=query, limit=limit, context=context)

    def count(self, *, status=None) -> int:
        return self._engine.store.count(status=status)

    def recent(self, n: int = 5):
        return self._engine.store.recall_recent(n)

    # -------------------------------------------------- deletion（复用现有 MemoryEngine 能力）
    def delete(self, mem_id: str) -> None:
        self._engine.store.delete(mem_id)

    # -------------------------------------------------- 不变式证明
    @property
    def backing_table(self) -> str:
        return "memories"
