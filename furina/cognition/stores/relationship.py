"""C5 — Relationship（adapter on existing RelationshipEngine）。

current relationship dimensions 只有现有 RelationshipEngine 可写（唯一写入口）。
Cognition 只做 read/write adapter + 可选 milestones 历史（不复制一套 trust 数值）。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from furina.core import get_logger
from .base import CognitionDB

log = get_logger("cognition.relationship")


class RelationshipStore:
    """C5 adapter：包装 RelationshipEngine（truth owner）+ milestones 表（历史 note）。"""

    def __init__(self, db: CognitionDB, engine) -> None:
        self._db = db
        self._engine = engine

    # -------------------------------------------------- current truth（只读，来自 engine）
    def factors(self) -> Dict[str, float]:
        return dict(self._engine.factors())

    def state_dict(self) -> Dict[str, Any]:
        st = self._engine.state
        return {k: getattr(st, k) for k in (
            "familiarity", "trust", "comfort", "attachment", "respect", "dependency",
            "annoyance", "interaction_tolerance", "social_confidence",
            "user_response_rate", "user_rejection_rate") if hasattr(st, k)}

    # -------------------------------------------------- write（唯一入口 = engine.apply）
    def apply(self, event: str, strength: float = 1.0, reason: str = "") -> Dict[str, float]:
        """委托 RelationshipEngine.apply —— current truth 只有 engine 可写。"""
        return self._engine.apply(event, strength=strength, reason=reason)

    # -------------------------------------------------- milestones（历史 note，非 current truth）
    def record_milestone(self, milestone_type: str, note: str = "") -> None:
        self._db.execute(
            "INSERT INTO relationship_milestones(milestone_type,note,timestamp) VALUES(?,?,?)",
            (milestone_type, (note or "")[:500], time.time()))

    def milestones(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._db.query_all(
            "SELECT milestone_id,milestone_type,note,timestamp FROM relationship_milestones "
            "ORDER BY timestamp DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    # -------------------------------------------------- 不变式证明
    @property
    def truth_owner(self) -> str:
        return "RelationshipEngine"
