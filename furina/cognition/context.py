"""Cognitive Context Assembler。

在 owner ingress 构造 plain immutable（bounded）CognitiveContext；worker/DialogueBrain 只消费快照。
权威顺序（冲突真值优先，非全部塞进 prompt）：
CURRENT FACTS > RECENT EVENT > AGENT TASK FACT > USER MODEL FACT > AUTOBIO MEMORY > CANON CONTEXT
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from furina.core import get_logger
from .models import CognitiveContext
from .retrieval.retriever import CanonLifeRetriever
from .stores.autobiography import AutobiographicalMemoryStore
from .stores.canon_history import CanonHistoryStore
from .stores.canon_identity import CanonIdentityStore
from .stores.event_timeline import EventTimelineStore
from .stores.agent_history import AgentTaskHistoryStore
from .stores.relationship import RelationshipStore
from .stores.user_model import UserModelStore

log = get_logger("cognition.context")

DEFAULT_BOUNDS = {"canon": 2, "memories": 3, "user": 5, "agent": 2, "events": 5}


class CognitiveContextAssembler:
    """组装有界 CognitiveContext（owner 线程调用；输出为 plain 数据快照）。"""

    def __init__(self, *, canon_identity: CanonIdentityStore,
                 canon_history: CanonHistoryStore,
                 autobiography: AutobiographicalMemoryStore,
                 user_model: UserModelStore,
                 relationship: RelationshipStore,
                 events: EventTimelineStore,
                 agent_history: AgentTaskHistoryStore,
                 bounds: Optional[Dict[str, int]] = None) -> None:
        self._stores = {
            "canon_identity": canon_identity,
            "canon_history": canon_history,
            "autobiography": autobiography,
            "user_model": user_model,
            "relationship": relationship,
            "events": events,
            "agent_history": agent_history,
        }
        self._bounds = dict(bounds or DEFAULT_BOUNDS)
        self._retriever = CanonLifeRetriever(canon_history)

    def assemble(self, *, query: str = "", topic: str = "",
                 current_facts: Optional[Dict[str, Any]] = None,
                 trust: float = 0.5) -> CognitiveContext:
        b = self._bounds
        canon_id = self._stores["canon_identity"]
        hist = self._stores["canon_history"]
        auto = self._stores["autobiography"]
        um = self._stores["user_model"]
        rel = self._stores["relationship"]
        ev = self._stores["events"]
        ag = self._stores["agent_history"]

        episodes, activation = self._retriever.retrieve(query, topic=topic, trust=trust)

        mems: List[str] = []
        try:
            mems = [m.content for m in auto.retrieve(query=query, limit=b["memories"])]
        except Exception:
            mems = []

        ctx = CognitiveContext(
            current_facts=dict(current_facts or {}),
            recent_events=ev.query_recent(limit=b["events"]),
            relevant_agent_tasks=ag.query_recent(limit=b["agent"]),
            user_model_items=um.query_active(limit=b["user"]),
            autobiographical_memories=mems[: b["memories"]],
            canon_identity=canon_id.snapshot(),
            relevant_canon_episodes=episodes[: b["canon"]],
            relationship=rel.factors(),
            canon_activation=activation,
        )
        # 断言有界（防未来改动把整库 dump 给 LLM）
        assert ctx.is_bounded(b), f"cognitive context 超出 bounds: {ctx.is_bounded(b)}"
        return ctx
