"""D2 — vector encoders（诚实命名 + 跨进程确定性）。

- ``HashedLexicalVectorEncoder``：把查询/文档的字符 bigram 用 **blake2b 稳定哈希**
  投影到固定维实向量（HASHED_LEXICAL_VECTOR）。不使用 Python 内置 ``hash()``
  （进程级盐化，跨进程不可复现）；相同文本+相同 seed+相同 dim → 跨进程字节一致。
  这是**词法哈希向量**，**不是**语义 embedding。
- ``ProviderVectorEncoder``：可选真实语义 embedding provider 注入点（批接口）；
  未配置时 D2 走 hashed 基线。provider 输出**不保证归一化** —— 归一化由检索层
  （index.vector_lookup）在余弦边界统一执行（R4 契约）。
"""
from __future__ import annotations

import hashlib
from typing import Callable, List, Sequence

import numpy as np

Vector = List[float]


def l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm <= 1e-12:
        return vec
    return vec / norm


def _stable_digest(key: str) -> int:
    """blake2b 稳定摘要（与 PYTHONHASHSEED 无关）。"""
    return int.from_bytes(hashlib.blake2b(key.encode("utf-8"),
                                          digest_size=8).digest(), "big")


class HashedLexicalVectorEncoder:
    """deterministic 词法哈希向量（bigram→固定维，L2 归一，跨进程稳定）。"""

    kind = "HASHED_LEXICAL_VECTOR"

    def __init__(self, dim: int = 256, seed: int = 0) -> None:
        self.dim = int(dim)
        self._seed = int(seed)

    def _digest(self, text: str) -> np.ndarray:
        q = (text or "").lower()
        grams = [q[i:i + 2] for i in range(max(0, len(q) - 1))] if len(q) >= 2 else [q]
        v = np.zeros((self.dim,), dtype=np.float32)
        for g in grams:
            h = _stable_digest(f"{self._seed}:{g}")     # seed 参与哈希（R2）
            idx = h % self.dim
            sign = 1.0 if (h >> 63) & 1 else -1.0
            v[idx] += sign
        return v

    def encode(self, texts: Sequence[str]) -> List[Vector]:
        out = []
        for t in texts:
            vec = l2_normalize(self._digest(t)).tolist()
            out.append([float(x) for x in vec])
        return out


class ProviderVectorEncoder:
    """可选真实语义 embedding provider（批接口；不保证归一化 —— 检索层负责）。"""

    kind = "PROVIDER_SEMANTIC_EMBEDDING"

    def __init__(self, encode_fn: Callable[[Sequence[str]], List[Vector]],
                 dim: int = 0) -> None:
        self._fn = encode_fn
        self.dim = int(dim or 0)

    def encode(self, texts: Sequence[str]) -> List[Vector]:
        return list(self._fn(texts))
