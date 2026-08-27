"""Cognitive Context Assembler。

在 owner ingress 构造 plain immutable（bounded）CognitiveContext；worker/DialogueBrain 只消费快照。
权威顺序（冲突真值优先，非全部塞进 prompt）：
CURRENT FACTS > RECENT EVENT > AGENT TASK FACT > USER MODEL FACT > AUTOBIO MEMORY > CANON CONTEXT
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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

DEFAULT_BOUNDS = {"canon": 2, "memories": 3, "user": 3, "agent": 2, "events": 3}


class CognitiveContextAssembler:
    """组装有界 CognitiveContext（owner 线程调用；输出为 plain 数据快照）。"""

    def __init__(self, *, canon_identity: CanonIdentityStore,
                 canon_history: CanonHistoryStore,
                 autobiography: AutobiographicalMemoryStore,
                 user_model: UserModelStore,
                 relationship: RelationshipStore,
                 events: EventTimelineStore,
                 agent_history: AgentTaskHistoryStore,
                 bounds: Optional[Dict[str, int]] = None,
                 index: Optional[Any] = None,
                 exposure_ledger: Optional[Any] = None) -> None:
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
        # D2：DERIVED 检索索引（非权威提示；None = 保持旧路径）。
        self._index = index
        # D3：session-local 曝光账本（DERIVED/非权威；None → 内部默认实例）。
        from .retrieval.exposure import RetrievalExposureLedger
        self._exposure = exposure_ledger or RetrievalExposureLedger()

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

        # Phase 15E：C3 回忆经 RetrievalRanker（authority/relevance/recency/importance/
        # strength/status/diversity），不 dump、不纯 cosine topK。
        # D2 + R6：hybrid 解析对象 与 权威 retrieve 候选 **合并去重**（mem_id）后交
        # ranker —— derived 是增强而非独占闸门。
        # D3：显式召回绕过冷却；自动注入对 TTL 内已曝光记忆做有界抑制；候选全部被
        # 冷却 → 本轮静默（绝不二次回退复活）；只有**成功装配进最终 context** 的对象
        # 才被标记曝光（mark-after-success）。
        from .retrieval.ranker import RetrievalRanker
        from .retrieval.hybrid import HybridRetriever
        from .retrieval.exposure import is_recall_intent
        ranker = RetrievalRanker()
        mems: List[Any] = []
        selected_objs: List[Any] = []
        recall = is_recall_intent(query)
        cooled_fn = (self._exposure.cooled
                     if (self._exposure and not recall) else None)

        def _key(m) -> str:
            return f"C3:{getattr(m, 'mem_id', '') or ''}"

        def _collect() -> Tuple[List[Any], bool]:
            pool: List[Any] = []
            if self._index is not None:
                res = HybridRetriever(self._index, auto).candidates(
                    query, limit=b["memories"] * 2)
                pool = list(res["objects"])
            legacy = list(auto.retrieve(query=query, limit=b["memories"] * 4))
            seen: set = set()
            merged: List[Any] = []
            for m in pool + legacy:
                mid = getattr(m, "mem_id", None)
                if mid in seen:
                    continue
                seen.add(mid)
                merged.append(m)
            had_merge = bool(merged)
            if cooled_fn:
                merged = [m for m in merged if not cooled_fn(_key(m))]
            return merged, had_merge

        try:
            candidate_input, had_merge = _collect()
            if candidate_input:
                selected_objs = list(ranker.rank_memories(
                    candidate_input, query=query, limit=b["memories"]))
                mems = [m.content for m in selected_objs]
            elif had_merge and cooled_fn:
                selected_objs = []                       # 全冷却：本轮静默，不复活
            if not mems and not (had_merge and cooled_fn):
                legacy_fallback = list(auto.retrieve(query=query,
                                                     limit=b["memories"]))
                selected_objs = legacy_fallback
                mems = [m.content for m in selected_objs]
        except Exception as e:
            log.warning("D3 C3 hybrid/fallback 失败（降级原路径；零曝光标记）: %s", e)
            selected_objs = []
            mems = []
            try:
                legacy_fallback = list(auto.retrieve(query=query, limit=b["memories"]))
                selected_objs = legacy_fallback
                mems = [m.content for m in selected_objs]
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
        # D3：mark-after-success —— 只标记成功装配且真正进入最终 context 的记忆；
        # 失败/中止绝不标记；标记不触碰任何 source truth。
        if self._exposure is not None:
            try:
                for m in selected_objs[: b["memories"]]:
                    mid = str(getattr(m, "mem_id", "") or "")
                    if mid:
                        self._exposure.mark(f"C3:{mid}")
            except Exception as e:                       # pragma: no cover
                log.warning("D3 exposure mark failed（不影响真值）: %s", e)
        return ctx
