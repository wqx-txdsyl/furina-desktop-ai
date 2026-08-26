"""Derived Semantic Vector Index（Phase 15E）。

严格标记：
- **DERIVED**：只索引 selected C2/C3/C4/C7 的摘要文本；
- **REBUILDABLE**：可由 source stores 完整重建（build/rebuild 幂等）；
- **NON-AUTHORITATIVE**：向量结果**永远不能覆盖** authoritative structured truth
  （C1-C7 是唯一 truth；index 只是检索提示）。
- 缺失/损坏/embedding 不可用 → 系统退化到 deterministic lexical/metadata retrieval，
  cognition 不 broken（调用方 fallback）。

不索引：API key / 完整 private DB dump / raw screenshot / secret env。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from furina.core import get_logger

log = get_logger("cognition.index")

INDEX_MARKER = {"derived": True, "rebuildable": True, "non_authoritative": True,
                "not_an_eighth_truth_store": True}
INDEX_VERSION = "15E.1"


class SemanticVectorIndex:
    """DERIVED 语义索引（可删除/重建；无权威）。"""

    def __init__(self, index_path: Optional[Path] = None,
                 embed_fn: Optional[Callable[[str], List[float]]] = None) -> None:
        self._path = Path(index_path) if index_path else None
        self._embed_fn = embed_fn
        self._items: List[Dict[str, Any]] = []       # [{store, ref_id, text, keywords}]
        self._loaded = False

    # -------------------------------------------------- build / rebuild（DERIVED + REBUILDABLE）
    def build(self, *, canon_episodes=None, memories=None, user_items=None,
              agent_tasks=None) -> int:
        """从 source stores 的**选中**条目重建索引（幂等：先清空再重建）。"""
        self._items = []
        for ep in (canon_episodes or []):
            self._items.append({
                "store": "C2", "ref_id": ep.episode_id,
                "text": f"{ep.objective_summary} {' '.join(ep.trigger_topics or [])}",
                "keywords": list(ep.trigger_topics or [])[:10],
            })
        for m in (memories or []):
            self._items.append({
                "store": "C3", "ref_id": getattr(m, "mem_id", ""),
                "text": str(getattr(m, "content", ""))[:200],
                "keywords": [],
            })
        for it in (user_items or []):
            self._items.append({
                "store": "C4", "ref_id": getattr(it, "item_id", ""),
                "text": f"{getattr(it, 'category', '')} {getattr(it, 'value', '')}",
                "keywords": [str(getattr(it, "value", ""))[:20]],
            })
        for t in (agent_tasks or []):
            self._items.append({
                "store": "C7", "ref_id": getattr(t, "task_id", ""),
                "text": str(getattr(t, "goal", "") or getattr(t, "result_summary", ""))[:200],
                "keywords": [],
            })
        if self._path is not None:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(json.dumps({
                    "marker": INDEX_MARKER, "version": INDEX_VERSION,
                    "built_at": time.time(), "items": self._items,
                }, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                log.warning("index persist failed: %s", e)
        self._loaded = True
        return len(self._items)

    def rebuild(self, **kw) -> int:
        return self.build(**kw)

    def delete(self) -> None:
        """删除 derived index（**绝不触碰 source stores**）。"""
        self._items = []
        self._loaded = False
        if self._path is not None:
            try:
                if self._path.exists():
                    self._path.unlink()
            except Exception as e:
                log.warning("index delete failed: %s", e)

    # -------------------------------------------------- load / status
    def _ensure_loaded(self) -> None:
        if self._loaded or self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._items = list(data.get("items", []))
            self._loaded = True
        except Exception as e:
            log.warning("index load failed（视为缺失 → fallback）: %s", e)
            self._items = []
            self._loaded = True

    def exists(self) -> bool:
        if self._path is not None and self._path.exists():
            return True
        return bool(self._items)

    def count(self) -> int:
        self._ensure_loaded()
        return len(self._items)

    def status(self) -> Dict[str, Any]:
        self._ensure_loaded()
        return {"derived": True, "rebuildable": True, "non_authoritative": True,
                "exists": self.exists(), "item_count": self.count(),
                "version": INDEX_VERSION}

    # -------------------------------------------------- lookup（NON-AUTHORITATIVE 提示）
    def lookup(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """语义/词法提示（无 authority；调用方必须结合 structured truth 裁决）。"""
        self._ensure_loaded()
        q = re.sub(r"[\s，。？！?!、：:；;]", "", query or "").lower()
        if not q:
            return []
        terms = {q[i:i + 2] for i in range(max(0, len(q) - 1))} if len(q) >= 2 else {q}
        scored = []
        for it in self._items:
            hay = (it.get("text", "") + " " + " ".join(it.get("keywords", []))).lower()
            hits = sum(1 for t in terms if t and t in hay)
            if hits > 0:
                scored.append((hits, it))
        scored.sort(key=lambda x: -x[0])
        return [{"store": it["store"], "ref_id": it["ref_id"]} for _h, it in scored[:top_k]]


def default_index_path(db_path) -> Path:
    """默认 derived index 位置（与 DB 同目录；独立于 source stores）。"""
    p = Path(db_path)
    return p.parent / "cognition_index.json"
