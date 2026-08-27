"""D2 — HybridRetriever（derived refs → 权威解析的窄门面）。

职责：
- 用 DerivedRetrievalIndex.hybrid_lookup 取 (store, ref_id) 候选；
- 对每个候选**回权威 store 解析**真实对象（缺失/删除 → 丢弃，绝不伪造真值）；
- C3 域：返回 Memory 对象供 RetrievalRanker 复用既有 authority/status/recency 重排；
- 向量失败 / 索引缺失 → 自动退化 lexical 路径（或由调用方回退原有 retrieve），
  退化可通过返回的 meta 观察（fail-soft + 可观测）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from furina.core import get_logger

log = get_logger("cognition.hybrid_retriever")

# 每域最终候选上限（context bucket 预算之上游缓冲；最终仍受 assemble 桶限额约束）
_PER_DOMAIN_CAP = 12


class HybridRetriever:
    """生产接线门面：derived index 提示 + 权威解析 + 有界返回。"""

    def __init__(self, index: Any, autobiography: Any) -> None:
        self._index = index
        self._auto = autobiography

    def candidates(self, query: str, *, limit: int = 6,
                   now: Optional[float] = None) -> Dict[str, Any]:
        """返回 {refs, objects, meta}：refs 已去重、objects 为权威解析结果。

        limit 为 C3 桶最终上限；候选池取 min(union_cap, limit*2) 再经权威解析。
        """
        now = now or 0.0
        meta: Dict[str, Any] = {"index_exists": self._index.exists(),
                                "vector_enabled": bool(self._index.status().get(
                                    "vector_enabled", False)),
                                "vector_invalid": bool(self._index.status().get(
                                    "vector_invalid", False)),
                                "degraded_to_lexical": False}
        refs: List[Dict[str, Any]] = []
        try:
            refs = self._index.hybrid_lookup(query, top_k=max(6, min(limit * 2, 30)))
            meta["candidate_union"] = len(refs)
            meta["paths"] = sorted({p for r in refs for p in r.get("paths", [])})
            if refs and all(r.get("paths") == ["lexical"] for r in refs):
                meta["degraded_to_lexical"] = "vector_unused" if not refs else (
                    "vector_absent")
        except Exception as e:
            log.warning("D2 hybrid lookup failed（fallback 空）: %s", e)
            meta["error"] = f"{type(e).__name__}: {e}"
            refs = []
        objects = []
        for r in refs[: _PER_DOMAIN_CAP]:
            if r.get("store") != "C3":
                continue                                # 本门面当前只服务 C3 桶
            obj = self._auto.get(r["ref_id"])
            if obj is None:
                meta.setdefault("dropped_stale_refs", []).append(r["ref_id"])
                continue                                # 权威缺失 → 丢弃（CE3/T17）
            st = getattr(obj, "status", "active")
            if hasattr(st, "value"):
                st = st.value
            if str(st) != "active":
                meta.setdefault("dropped_non_active", []).append(r["ref_id"])
                continue                                # 归档/失效记忆不得进当前上下文（T5）
            objects.append(obj)
        # 有界：不超过请求 limit
        return {"refs": refs, "objects": objects[: max(0, limit)], "meta": meta}
