"""Derived Retrieval Index（Phase 15E + D2）。

严格标记：
- **DERIVED**：只索引 selected C2/C3/C4/C7 的摘要文本（绝不复制完整真值 schema）；
- **REBUILDABLE**：可由 source stores 完整重建（build/rebuild 幂等）；
- **NON-AUTHORITATIVE / NOT C8**：命中只返回 (store, ref_id) 引用，调用方必须回权威
  store 解析；向量结果永远不能覆盖 authority / lifecycle / temporal / provenance。
- **诚实命名（D2）**：本模块提供两条候选路径 —— ``lexical_lookup``（字符 bigram 词法
  重叠，LEGACY 即"2-gram 计数"）与 ``vector_lookup``（cosine 相似度；向量由注入的
  encoder 生成，默认 ``HashedLexicalVectorEncoder`` = 词法哈希向量，**不是**语义
  embedding）。绝不把 bigram 重叠称作 semantic embedding。

不索引：API key / 完整 private DB dump / raw screenshot / secret env / 无界 C6。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from furina.core import get_logger

from .encoders import HashedLexicalVectorEncoder

log = get_logger("cognition.index")

INDEX_MARKER = {"derived": True, "rebuildable": True, "non_authoritative": True,
                "not_an_eighth_truth_store": True}
INDEX_VERSION = "15E.2"

# D2 有界性（PART 15）：
MAX_INDEXED_ITEMS = 5000          # 单次 build 索引上限（超出丢弃最旧，status.truncated）
LEXICAL_TOP_K = 20                # 词法候选 top-k
VECTOR_TOP_K = 20                 # 向量候选 top-k
HYBRID_UNION_CAP = 30             # union 去重后上限
VECTOR_MIN_SIM = 0.10             # 向量候选最低余弦（弱信号过滤；0 表示不启用阈值）


def default_index_path(db_path) -> Path:
    """默认 derived index 位置（与 DB 同目录；独立于 source stores）。"""
    p = Path(db_path)
    return p.parent / "cognition_index.json"


def _clean(query: str) -> str:
    return re.sub(r"[\s，。？！?!、：:；;]", "", query or "").lower()


def _lexical_ngram_score(query: str, hay: str) -> int:
    """字符 bigram 词法重叠（DETERMINISTIC LEXICAL / NGRAM SIMILARITY —— 非语义）。"""
    q = _clean(query)
    if not q:
        return 0
    terms = {q[i:i + 2] for i in range(max(0, len(q) - 1))} if len(q) >= 2 else {q}
    hay = (hay or "").lower()
    return sum(1 for t in terms if t and t in hay)


class DerivedRetrievalIndex:
    """DERIVED 检索索引（lexical ∪ vector 双路径 + 权威无关提示）。"""

    def __init__(self, index_path: Optional[Path] = None,
                 encoder: Optional[Any] = None) -> None:
        self._path = Path(index_path) if index_path else None
        self._encoder = encoder or HashedLexicalVectorEncoder()
        self._items: List[Dict[str, Any]] = []       # [{store, ref_id, text, keywords, vec, ts, status}]
        self._loaded = False
        self._vector_invalid = False                 # 版本/后端/维度不符 → 向量路径关闭（lex 可用）
        self._vector_invalid_reason = ""
        self._vector_unavailable = False             # build 时编码失败/持久化标记 → 无可用向量
        self._corrupt = False                        # 加载损坏 → 视为缺失
        self._truncated = 0
        self._last_vector_error = ""

    # -------------------------------------------------- build / rebuild（DERIVED + REBUILDABLE）
    def build(self, *, canon_episodes=None, memories=None, user_items=None,
              agent_tasks=None) -> int:
        """从 source stores 的**选中**条目重建索引（幂等：先清空再重建，有界截断）。"""
        self._items = []
        self._truncated = 0
        self._vector_invalid = False
        self._vector_invalid_reason = ""
        self._vector_unavailable = False
        self._last_vector_error = ""
        raw: List[Dict[str, Any]] = []
        for ep in (canon_episodes or []):
            raw.append({
                "store": "C2", "ref_id": ep.episode_id,
                "text": f"{ep.objective_summary} {' '.join(ep.trigger_topics or [])}",
                "keywords": list(ep.trigger_topics or [])[:10],
                "ts": float(getattr(ep, "timeline_order", 0) or 0),
                "status": "canon",
            })
        for m in (memories or []):
            raw.append({
                "store": "C3", "ref_id": getattr(m, "mem_id", ""),
                "text": str(getattr(m, "content", ""))[:200],
                "keywords": [],
                "ts": float(getattr(m, "timestamp", 0) or 0),
                "status": str(getattr(m, "status", "active")),
            })
        for it in (user_items or []):
            raw.append({
                "store": "C4", "ref_id": getattr(it, "item_id", ""),
                "text": f"{getattr(it, 'category', '')} {getattr(it, 'value', '')}",
                "keywords": [str(getattr(it, "value", ""))[:20]],
                "ts": float(getattr(it, "updated_at", 0) or 0),
                "status": str(getattr(it, "status", "active")),
            })
        for t in (agent_tasks or []):
            raw.append({
                "store": "C7", "ref_id": getattr(t, "task_id", ""),
                "text": str(getattr(t, "goal", "") or getattr(t, "result_summary", ""))[:200],
                "keywords": [],
                "ts": float(getattr(t, "created_at", 0) or 0),
                "status": str(getattr(t, "status", "")),
            })
        # 有界索引：超限保留最新（按 ts 排序）
        raw.sort(key=lambda d: d["ts"], reverse=True)
        if len(raw) > MAX_INDEXED_ITEMS:
            self._truncated = len(raw) - MAX_INDEXED_ITEMS
            raw = raw[:MAX_INDEXED_ITEMS]
        # 向量编码（R4/R7：build 即校验/归一化 —— 畸形向量置 None 不落库；
        # 全部畸形 → vector_unavailable=True，诚实退化到 lexical）
        try:
            vecs = self._encoder.encode([d["text"] for d in raw])
            unusable = 0
            for d, v in zip(raw, vecs):
                dv = self._norm_vector(v)
                if dv is None:
                    d["vec"] = None
                    unusable += 1
                else:
                    d["vec"] = [float(x) for x in dv]
            if raw and unusable == len(raw):
                self._vector_unavailable = True
                self._last_vector_error = "no usable vectors encoded"
        except Exception as e:
            self._last_vector_error = f"{type(e).__name__}: {e}"
            self._vector_unavailable = True            # R7：诚实标记无可用向量（可持久化）
            log.warning("D2 vector encode failed（lexical 继续，vector 关闭）: %s", e)
            for d in raw:
                d["vec"] = None
        self._items = raw
        if self._path is not None:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(json.dumps({
                    "marker": INDEX_MARKER, "version": INDEX_VERSION,
                    "built_at": time.time(), "dim": self._dim(),
                    "backend": getattr(self._encoder, "kind", "UNKNOWN"),
                    "vector_ok": (not self._vector_unavailable
                                  and not self._vector_invalid),
                    "truncated": self._truncated,
                    "items": self._items,
                }, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                log.warning("index persist failed: %s", e)
        self._loaded = True
        return len(self._items)

    def _dim(self) -> int:
        dim = getattr(self._encoder, "dim", 0)
        return int(dim or 0)

    def rebuild(self, **kw) -> int:
        return self.build(**kw)

    def delete(self) -> None:
        """删除 derived index（**绝不触碰 source stores**）。"""
        self._items = []
        self._loaded = False
        self._vector_invalid = False
        self._vector_invalid_reason = ""
        self._vector_unavailable = False
        self._corrupt = False
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
            items = list(data.get("items", []))
            self._items = items
            self._loaded = True
            self._corrupt = False
            self._vector_unavailable = bool(not data.get("vector_ok", True))
            # R3 兼容契约：version / backend / dim 任一不符 → 持久化向量不可用
            # （lexical 文本/引用投影仍可用；向量绝不混用）。原因暴露在 status。
            ver = str(data.get("version", ""))
            backend = str(data.get("backend", ""))
            dim = int(data.get("dim", 0) or 0)
            rt_kind = str(getattr(self._encoder, "kind", "UNKNOWN"))
            if ver and ver != INDEX_VERSION:
                self._vector_invalid = True
                self._vector_invalid_reason = f"version_mismatch:{ver}!={INDEX_VERSION}"
                log.warning("D2 index version mismatch %s != %s → vector off", ver, INDEX_VERSION)
            elif backend and backend != rt_kind:
                self._vector_invalid = True
                self._vector_invalid_reason = f"backend_mismatch:{backend}!={rt_kind}"
                log.warning("D2 index backend mismatch %s != %s → vector off", backend, rt_kind)
            elif dim and self._dim() and dim != self._dim():
                self._vector_invalid = True
                self._vector_invalid_reason = f"dimension_mismatch:{dim}!={self._dim()}"
                log.warning("D2 index dimension mismatch %s != %s → vector off", dim, self._dim())
        except Exception as e:
            log.warning("index load failed（视为缺失 → fallback）: %s", e)
            self._items = []
            self._loaded = True
            self._corrupt = True

    def exists(self) -> bool:
        if self._path is not None and self._path.exists():
            return True
        return bool(self._items)

    def count(self) -> int:
        self._ensure_loaded()
        return len(self._items)

    def status(self) -> Dict[str, Any]:
        self._ensure_loaded()
        usable_vecs = sum(1 for it in self._items if it.get("vec") is not None)
        return {"derived": True, "rebuildable": True, "non_authoritative": True,
                "not_an_eighth_truth_store": True,
                "exists": self.exists(), "item_count": self.count(),
                "version": INDEX_VERSION, "backend": getattr(self._encoder, "kind", "UNKNOWN"),
                "dim": self._dim(), "truncated": self._truncated,
                "vector_enabled": bool(usable_vecs) and not self._vector_invalid
                and not self._vector_unavailable,
                "vector_usable_count": usable_vecs,
                "vector_invalid": self._vector_invalid,
                "vector_invalid_reason": self._vector_invalid_reason,
                "vector_unavailable": self._vector_unavailable,
                "corrupt": self._corrupt,
                "last_vector_error": self._last_vector_error}

    # -------------------------------------------------- lexical path（DETERMINISTIC LEXICAL）
    def lexical_lookup(self, query: str, top_k: int = LEXICAL_TOP_K) -> List[Dict[str, Any]]:
        """字符 bigram 词法重叠候选（词法相似度，非语义）。"""
        self._ensure_loaded()
        q = _clean(query)
        if not q:
            return []
        scored = []
        for it in self._items:
            hay = it.get("text", "") + " " + " ".join(it.get("keywords", []))
            hits = _lexical_ngram_score(q, hay)
            if hits > 0:
                scored.append((hits, it))
        scored.sort(key=lambda x: -x[0])
        return [{"store": it["store"], "ref_id": it["ref_id"], "lex": float(h),
                 "vec": None}
                for h, it in scored[:top_k]]

    # -------------------------------------------------- vector path（TRUE COSINE；检索层归一化）
    def vector_lookup(self, query: str, top_k: int = VECTOR_TOP_K) -> List[Dict[str, Any]]:
        """cosine 相似度候选（R4：检索边界统一 L2 归一 —— 不依赖 provider 是否已归一；
        结果恒在 [-1,1]；数量/维度/有限值校验，畸形输入 fail-soft 到空，lexical 继续）。"""
        self._ensure_loaded()
        if self._vector_invalid or self._vector_unavailable or not self._items:
            return []
        try:
            qv = self._norm_vector(self._encoder.encode([query])[0])
        except Exception as e:
            self._last_vector_error = f"{type(e).__name__}: {e}"
            log.warning("D2 query encode failed（vector off）: %s", e)
            return []
        if qv is None:
            self._last_vector_error = "malformed query vector"
            return []
        scored = []
        for it in self._items:
            v = it.get("vec")
            if v is None:
                continue
            dv = self._norm_vector(v)
            if dv is None:
                continue                                # 畸形条目跳过（不产生误导状态）
            sim = float(np.dot(qv, dv))
            sim = max(-1.0, min(1.0, sim))              # 数值容差夹紧
            if VECTOR_MIN_SIM and sim < VECTOR_MIN_SIM:
                continue
            scored.append((sim, it))
        scored.sort(key=lambda x: -x[0])
        return [{"store": it["store"], "ref_id": it["ref_id"], "lex": None,
                 "vec": float(s)}
                for s, it in scored[:top_k]]

    @staticmethod
    def _norm_vector(raw) -> "Optional[np.ndarray]":
        """规范化 + 校验（一维、有限值、非零 L2 归一）；畸形返回 None。"""
        try:
            arr = np.asarray(raw, dtype=np.float32)
            if arr.ndim != 1 or arr.size == 0:
                return None
            if not np.all(np.isfinite(arr)):
                return None
            norm = float(np.linalg.norm(arr))
            if norm <= 1e-12:
                return None
            return arr / norm
        except Exception:
            return None

    # -------------------------------------------------- hybrid union（dedupe by store+ref_id）
    def hybrid_lookup(self, query: str, top_k: int = HYBRID_UNION_CAP) -> List[Dict[str, Any]]:
        """lexical ∪ vector → 按 (store, ref_id) 去重 → 保留成分分与命中路径。"""
        self._ensure_loaded()
        merged: Dict[tuple, Dict[str, Any]] = {}
        for c in self.lexical_lookup(query):
            key = (c["store"], c["ref_id"])
            merged.setdefault(key, {"store": c["store"], "ref_id": c["ref_id"],
                                    "lex": 0.0, "vec": None, "paths": set()})
            merged[key]["lex"] = float(c["lex"] or 0.0)
            merged[key]["paths"].add("lexical")
        for c in self.vector_lookup(query):
            key = (c["store"], c["ref_id"])
            if key not in merged:
                merged[key] = {"store": c["store"], "ref_id": c["ref_id"],
                               "lex": 0.0, "vec": None, "paths": set()}
            merged[key]["vec"] = float(c["vec"] or 0.0)
            merged[key]["paths"].add("vector")
        out = []
        for cand in merged.values():
            lex = cand["lex"] or 0.0
            vec = cand["vec"] or 0.0
            cand["score"] = round(0.6 * lex + 0.4 * vec, 6)
            cand["paths"] = sorted(cand["paths"])
            out.append(cand)
        out.sort(key=lambda x: -x["score"])
        return out[:top_k]


    # D2 兼容别名：旧名 lookup() == hybrid union（返回 {store,ref_id,...} 引用提示）。
    def lookup(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        return self.hybrid_lookup(query, top_k=top_k)


# D2：诚实命名的旧名别名（既有导入/测试兼容；新代码用 DerivedRetrievalIndex）。
SemanticVectorIndex = DerivedRetrievalIndex
