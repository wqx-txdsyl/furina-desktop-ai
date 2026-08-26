"""记忆引擎（legacy-plan/6）。

- 形成：记忆评分 importance/novelty/emotional/relationship/future/repetition（§9）。
- 巩固：夜间回顾，短期→长期（§13, §12）。
- 检索：融合 semantic+recency+importance+relationship+context（§21, §27）。
- 影响行为：检索结果进入 Behavior 决策（§28, §8）。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional

from furina.core import EventBus, EventType, get_logger
from .memory_store import MemoryStore
from .memory_types import Memory, MemoryLevel, MemorySource, MemoryStatus, RelationshipState

log = get_logger("memory")

# 检索加权（legacy-plan/6 §27）
_WEIGHTS = {"semantic": 0.30, "relevance": 0.20, "recency": 0.15,
            "importance": 0.15, "relationship": 0.10, "emotional": 0.10}


@dataclass
class FormedMemory:
    memory: Memory
    score: float


class MemoryEngine:
    def __init__(self, bus: EventBus, store: MemoryStore,
                 embed_fn: Optional[Callable[[str], List[float]]] = None,
                 threshold: float = 0.55) -> None:
        self.bus = bus
        self.store = store
        self.embed_fn = embed_fn
        self.relationship = store.load_relationship()
        self._threshold = threshold   # Phase 07：长期记忆 importance 阈值

    # -------------------------------------------------- 形成评分（§9）
    def score(self, importance: float = 0.3, novelty: float = 0.3, emotional: float = 0.2,
              relationship: float = 0.2, future: float = 0.3, repetition: float = 0.0) -> float:
        return importance + novelty + emotional + relationship + future + repetition

    def should_form(self, score: float, threshold: float = 1.2) -> bool:
        return score >= threshold

    # -------------------------------------------------- 记录事件（骨架）
    def observe(self, content: str, level: MemoryLevel = MemoryLevel.EPISODIC, *,
                source: MemorySource = MemorySource.SYSTEM,
                importance: float = 0.4, context: str = "", outcome: str = "",
                source_event_ids=None) -> Optional[Memory]:
        s = self.score(importance=importance, future=0.2, repetition=0.0, emotional=0.1)
        if not self.should_form(s):
            log.debug("memory: 未达形成阈值, discard: %s", content[:30])
            return None
        m = Memory(level=level, content=content, source=source, importance=importance,
                   context=context, outcome=outcome,
                   source_event_ids=list(source_event_ids or []))
        if self.embed_fn:
            m.embedding = self.embed_fn(content)
        mid = self.store.insert(m)
        self.bus.emit(EventType.MEMORY_CREATED, payload={"id": mid, "content": content},
                      source="memory")
        return m

    # -------------------------------------------------- Phase 15C：生命周期（遗忘=归档，不删 C6）
    def archive(self, mem_id: str, reason: str = "") -> Optional[Memory]:
        """遗忘 = 归档（recall 概率下降），**绝不 DELETE FROM life_events**。"""
        for m in self.store.query(limit=10000, status=None):
            if m.mem_id == mem_id:
                m.status = MemoryStatus.ARCHIVED
                self.store.insert(m)
                return m
        return None

    def supersede(self, mem_id: str, reason: str = "") -> Optional[Memory]:
        """旧记忆被新事实取代 → SUPERSEDED（历史保留，不再最高权重检索）。"""
        for m in self.store.query(limit=10000, status=None):
            if m.mem_id == mem_id:
                m.status = MemoryStatus.SUPERSEDED
                self.store.insert(m)
                return m
        return None

    # -------------------------------------------------- 关系更新（§18）【RC1 DEPRECATED】
    def apply_relationship(self, delta: Dict[str, float], reason: str = "") -> None:
        """⚠️ DEPRECATED —— 关系单一写入口是 RelationshipEngine.apply(event)。

        本方法直接 bump 关系维度，绕开 RelationshipEngine 的 trust-slow / 事件语义 / 衰减耦合，
        违反 "Relationship → RelationshipEngine owns" 原则（Phase 10.5 Audit S1）。
        保留仅为兼容旧调用；正式 Runtime 严禁调用。新调用请改走 RelationshipEngine。
        """
        import warnings
        warnings.warn(
            "MemoryEngine.apply_relationship is deprecated; use RelationshipEngine.apply() "
            "as the single relationship writer.", DeprecationWarning, stacklevel=2)
        self.relationship.apply(delta)
        self.store.save_relationship(self.relationship)
        log.debug("relationship %s: %s", delta, reason)

    # -------------------------------------------------- 检索（§21, §27）
    def retrieve(self, *, query: str = "", limit: int = 6,
                 context: Optional[str] = None, tags: Optional[List[str]] = None) -> List[Memory]:
        mems = self.store.query(limit=max(limit * 4, 60))
        # 检索分数（§13 relevance ≠ importance）：context 匹配 × importance × recency × tags
        terms = [t for t in query.replace("，", " ").split() if len(t) >= 2]
        # R2.1 P1-3：CJK 无空格查询 → 补 2-gram（"今天准备做什么" 命中含 今天/准备 的记忆；
        # 让"今天准备做什么？/做完以后会怎么样？"能检索到计划/后续事实）
        q = re.sub(r"[\s，。？！?!、：:；;]", "", query or "")
        if len(q) >= 4 and not any(" " in t for t in terms):
            terms = terms + [q[i:i + 2] for i in range(len(q) - 1)]
        terms = list(dict.fromkeys(terms))

        def _score(m: Memory) -> float:
            # context/world_context 精确匹配（情境化 §22）：不匹配则大幅降权，避免跨情境误用
            if context and getattr(m, "world_context", ""):
                if m.world_context == context:
                    context_hit = 2.0
                else:
                    context_hit = -2.0   # 跨情境 → 强烈偏移到排序末尾
            elif context:
                context_hit = 0.0
            else:
                context_hit = 0.0
            score = m.importance * 0.5 + _recency_score(m) * 0.25 + context_hit
            if terms:
                hay = f"{m.content} {m.context}".lower()
                hits = sum(1 for t in terms if t.lower() in hay)
                score += hits * 0.8
            if tags and getattr(m, "tags", None):
                score += sum(0.4 for t in tags if t in m.tags)
            return score

        ranked = sorted(mems, key=_score, reverse=True)
        # 情境强约束（§25）：给定 context 时，只返回匹配该 context 的记忆；
        # 无匹配 → 返回空（跨情境记忆不在无关系情境下扰动）。
        if context:
            picked = [m for m in ranked if getattr(m, "world_context", "") == context][:limit]
        else:
            picked = ranked[:limit]
        # 强化（§10）：只写有变化的（写放大控制）
        for m in picked:
            new_strength = min(1.0, m.strength + 0.02)
            if new_strength > m.strength:
                m.strength = new_strength
                m.last_recalled = time.time()
                self.store.insert(m)
        self.bus.emit(EventType.MEMORY_RECALLED, payload={"n": len(picked)}, source="memory")
        return picked

    # -------------------------------------------------- 长期记忆 consolidation（Phase 07）
    def consolidate(self, exp: Experience) -> Optional[Memory]:
        """把 Experience 沉淀为长期 Memory（去噪/去重/强化/容量治理）。

        阈值内事件不落库（§2 遗忘是能力）；重复事件合并/recurrence++（§9）；容量治理（§33）。
        """
        from .experience import importance_of, event_key
        score = importance_of(exp)
        if score < self._threshold:
            return None   # 低重要性 → 不长期保存
        # 去重：同 event_key + 时间窗口内 → 强化既有记忆（Phase 15C：累积 source_event_ids）
        key = event_key(exp.event_type, exp.world_context, exp.activity)
        dup = self._find_similar(key, window=86400.0)
        if dup is not None:
            dup.recurrence_count += 1
            dup.importance = max(dup.importance, score)
            dup.confidence = min(1.0, dup.confidence + 0.05)
            dup.last_reinforced = time.time()
            dup.strength = min(1.0, dup.strength + 0.05)
            for eid in (exp.source_event_ids or []):
                if eid and eid not in dup.source_event_ids:
                    dup.source_event_ids.append(eid)     # reinforcement 累积证据
            self.store.insert(dup)
            return dup
        m = Memory(
            level=MemoryLevel.EPISODIC,
            content=exp.summary,
            source=MemorySource.INTERACTION if exp.event_type.startswith("user") else MemorySource.BEHAVIOR,
            importance=score, confidence=0.6, context=exp.world_context,
            tags=[],
            event_type=exp.event_type, world_context=exp.world_context,
            recurrence_count=1,
            summary=exp.summary,
            # Phase 14 Final Closure（INV-C3-2）：新记忆必须保留 Experience 的
            # C6 事件溯源，禁止静默丢弃 provenance。
            source_event_ids=list(exp.source_event_ids or []),
        )
        # tag（供检索）
        m.tags = [exp.event_type]
        if exp.world_context:
            m.tags.append(exp.world_context)
        self.store.insert(m)
        self._enforce_capacity()
        self.bus.emit(EventType.MEMORY_CREATED, payload={"id": m.mem_id, "content": exp.summary}, source="memory")
        return m

    def _find_similar(self, key: str, window: float = 86400.0) -> Optional[Memory]:
        """找同 event_key + world_context 的最近记忆（避免重复污染 §9）。"""
        parts = key.split("|")
        etype = parts[0] if parts else ""
        wctx = parts[1] if len(parts) > 1 else ""
        for m in self.store.query(limit=200):
            if (getattr(m, "event_type", "") == etype
                    and getattr(m, "world_context", "") == wctx
                    and (time.time() - m.timestamp) < window):
                return m
        return None

    def _enforce_capacity(self, max_memories: int = 300) -> None:
        """容量治理：超出时淘汰 low importance / old / rarely recalled（§33）。"""
        allm = self.store.query(limit=max_memories * 3, status=None)
        if len(allm) <= max_memories:
            return
        def evict_key(m: Memory) -> float:
            return m.importance * 2.0 + (m.strength * 0.5) - _recency_score(m) * 0.3
        keep = sorted(allm, key=evict_key, reverse=True)[:max_memories]
        drop = [m for m in allm if m not in keep]
        for m in drop:
            try:
                self.store.delete(m.mem_id)
            except Exception:
                pass

    # -------------------------------------------------- Memory Interpretation（§14）
    def interpret(self, memories: List[Memory], *, context: str = "") -> Dict[str, float]:
        """确定性解释：把检索到的记忆 → 当前含义（§14-15）。

        绝不做第二套 Relationship —— 只输出 context-specific expectation：
        interaction_risk / positive_expectation / negative_expectation / help_expectation / memory_salience。
        """
        neg = 0.0; pos = 0.0; help_exp = 0.0; sal = 0.0
        for m in memories:
            w = m.importance * (1.0 + 0.1 * (getattr(m, "recurrence_count", 0) or 0))
            et = getattr(m, "event_type", "")
            if context and getattr(m, "world_context", "") and m.world_context != context:
                w *= 0.4   # 情境不匹配 → 影响减弱（§22 context specificity）
            if et in ("user_rejection", "user_ignore"):
                neg += w
            elif et in ("user_positive_response", "user_initiated", "praise"):
                pos += w
            elif et in ("help_success",):
                help_exp += w
            elif et in ("help_failure",):
                neg += w * 0.6
            sal += w
        # 归一化 + 情境修正
        total = max(1e-6, len(memories))
        return {
            "interaction_risk": min(1.0, neg / total * 2.0),
            "positive_expectation": min(1.0, pos / total * 2.0),
            "negative_expectation": min(1.0, neg / total * 2.0),
            "help_expectation": min(1.0, help_exp / total * 2.0),
            "memory_salience": min(1.0, sal / total),
        }

    # -------------------------------------------------- 待办：夜间巩固
    def nightly_consolidate(self, today_events: List[Memory]) -> Memory:
        """把当天事件概括成一条总结记忆（§13, §40）。

        骨架为拼接；仅保留高重要事件，并给总结记忆更高置信度（重要记忆会延续）。
        """
        important = [e for e in today_events if e.importance >= 0.4][-12:] or today_events[-12:]
        summary = "今天，" + "；".join(e.content for e in important)
        m = Memory(level=MemoryLevel.EPISODIC, content=summary, source=MemorySource.SYSTEM,
                   importance=0.6, confidence=0.7)
        self.store.insert(m)
        return m

    # -------------------------------------------------- 记忆 → 行为偏置（legacy-plan/6 §16, §28）
    def behavior_hint(self, *, context: str = "", user_context: Mapping[str, Any] | None = None) -> dict:
        """从近期/高重要记忆提炼对行为系统的偏置建议（不直接操控行为，只给偏置）。

        例：用户明说过“工作时不被打扰”，且当前在工作 → 建议压制社交类打扰行为。
        返回 dict 形如 {"social_penalty": 50, "approach_bonus": 0} 等，由行为引擎叠加到 Utility。
        无相关记忆时返回空 dict，行为完全走本地规则（不依赖 LLM）。
        """
        mems = self.retrieve(query=context, limit=8)
        used = " ".join(f"{m.content} {m.context}" for m in mems)
        bias: dict = {}

        # 用户偏好：不喜欢被打扰/需要安静（legacy-plan/6 §16 显式偏好）
        if "不" in used and any(k in used for k in ("打扰", "安静", "别吵", "不要说话", "别烦", "忙")):
            bias["social_penalty"] = 55      # 社交/打扰行为大幅降权
        # 关系（legacy-plan/6 §18）：高舒适 → 更愿意靠近用户。
        # Phase 13 终审 §13：unit debt —— 不再直接读 RelationshipState 原始 principal(0..100)，
        # 统一消费 canonical relationship_factors()（0..1 归一化），阈值保持 0.6。
        rel = self.relationship
        if rel is not None:
            try:
                from furina.relationship.engine import relationship_factors
                f = relationship_factors(rel)
            except Exception:
                f = {}
            if f.get("comfort", 0.0) > 0.6:
                bias["approach_bonus"] = 20
            if f.get("annoyance", 0.0) > 0.6:
                bias["social_penalty"] = max(bias.get("social_penalty", 0), 70)
        return bias


def _recency_score(m: Memory) -> float:
    age = time.time() - m.timestamp
    return max(0.0, 1.0 - age / (30 * 86400))  # 30 天线性衰减
