"""Retrieval Ranker（Phase 15E）—— 权威、有界、相关、不过度回忆。

打分综合（§34）：authority / semantic relevance / recency / importance / confidence /
memory strength / status / temporal validity / redundancy penalty / diversity。
禁止纯 cosine topK 决定一切。
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional


class RetrievalRanker:
    """确定性记忆排序（C3 等回忆型 store 用；C1/C6/C7 走各自权威查询）。"""

    # status → authority 权重（§33）
    STATUS_AUTHORITY = {"active": 1.0, "superseded": 0.2, "archived": 0.05, "expired": 0.1}

    def rank_memories(self, memories: List[Any], query: str = "", *,
                      limit: int = 3, now: Optional[float] = None) -> List[Any]:
        now = time.time() if now is None else now
        q = re.sub(r"[\s，。？！?!、：:；;]", "", query or "").lower()
        terms = [q[i:i + 2] for i in range(max(0, len(q) - 1))] if len(q) >= 2 else ([q] if q else [])
        scored = []
        for m in memories:
            st = getattr(m, "status", "active")
            if hasattr(st, "value"):
                st = st.value
            status = str(st)
            auth = self.STATUS_AUTHORITY.get(status, 0.0)
            if status == "archived" and auth <= 0.0:
                continue
            # semantic relevance（词法 2-gram；无向量依赖）
            hay = f"{getattr(m, 'content', '')} {getattr(m, 'context', '')}".lower()
            relevance = sum(1 for t in terms if t and t in hay) * 0.8
            # recency（30 天线性衰减）
            age = max(0.0, now - float(getattr(m, "timestamp", now) or now))
            recency = max(0.0, 1.0 - age / (30 * 86400.0))
            # importance / confidence / strength
            importance = float(getattr(m, "importance", 0.0) or 0.0)
            confidence = float(getattr(m, "confidence", 0.0) or 0.0)
            strength = float(getattr(m, "strength", 0.0) or 0.0)
            score = (auth * 0.30 + relevance * 0.25 + recency * 0.15
                     + importance * 0.10 + confidence * 0.10 + strength * 0.10)
            scored.append((score, m))
        scored.sort(key=lambda x: -x[0])
        # diversity / redundancy penalty：同 content 前缀只取最高分一条
        picked, seen = [], set()
        for score, m in scored:
            key = str(getattr(m, "content", ""))[:20]
            if key in seen:
                continue
            seen.add(key)
            picked.append(m)
            if len(picked) >= limit:
                break
        return picked
