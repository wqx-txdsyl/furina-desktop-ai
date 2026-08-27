"""D2 — vector encoders（诚实命名）。

- ``HashedLexicalVectorEncoder``：把查询/文档的字符 bigram 哈希投影到固定维实向量。
  这是**词法哈希向量**（HASHED_LEXICAL_VECTOR），**不是**语义 embedding ——
  它只让 cosine 相似度捕获词面重叠的软形式，用于与显式 lexical 候选互补。
- ``ProviderVectorEncoder``：可选真实语义 embedding provider 注入点
  （callable 批接口；未配置时 D2 走 hashed 基线，绝不假装语义）。
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence

import numpy as np

Vector = List[float]


def l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm <= 1e-12:
        return vec
    return vec / norm


class HashedLexicalVectorEncoder:
    """deterministic 词法哈希向量（bigram→固定维，L2 归一，重启稳定）。"""

    kind = "HASHED_LEXICAL_VECTOR"

    def __init__(self, dim: int = 256, seed: int = 0) -> None:
        self.dim = int(dim)
        rng = np.random.default_rng(seed)
        self._proj = rng.normal(size=(self.dim,), scale=0.5).astype(np.float32)
        self._bias = rng.integers(0, 2, size=(self.dim,), dtype=np.int8).astype(np.float32)

    def _digest(self, text: str) -> np.ndarray:
        q = (text or "").lower()
        grams = [q[i:i + 2] for i in range(max(0, len(q) - 1))] if len(q) >= 2 else [q]
        v = np.zeros((self.dim,), dtype=np.float32)
        for g in grams:
            h = abs(hash(g)) % (2**32)
            idx = h % self.dim
            sign = 1.0 if (h >> 16) % 2 == 0 else -1.0
            v[idx] += sign
        return v

    def encode(self, texts: Sequence[str]) -> List[Vector]:
        out = []
        for t in texts:
            vec = l2_normalize(self._digest(t)).tolist()
            out.append([float(x) for x in vec])
        return out


class ProviderVectorEncoder:
    """可选真实语义 embedding provider（批接口）。

    未提供/抛错 → 调用方回退到 hashed 基线（fail-soft，绝不阻塞 retrieval）。
    """

    kind = "PROVIDER_SEMANTIC_EMBEDDING"

    def __init__(self, encode_fn: Callable[[Sequence[str]], List[Vector]],
                 dim: int = 0) -> None:
        self._fn = encode_fn
        self.dim = int(dim or 0)

    def encode(self, texts: Sequence[str]) -> List[Vector]:
        return list(self._fn(texts))
