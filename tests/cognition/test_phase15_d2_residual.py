"""Phase 15 D2 — External Reviewer Residual R1-R12（Review = NEEDS_NARROW_PATCH）。

锁定：稳定哈希跨进程一致、持久化索引跨进程直载、兼容契约（version/backend/dim）、
真 cosine ∈ [-1,1]、畸形 provider fail-soft、lazy 生命周期激活与零重复构建、
derived 不压制权威召回、build 失败真状态且重启保持。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

_QAPP = QApplication.instance() or QApplication([])


def _hub(tmp_path):
    from furina.cognition import CognitionHub
    from furina.memory import MemoryEngine, MemoryStore
    class _Bus:
        def emit(self, *a, **k):
            return None
    store = MemoryStore(Path(tmp_path) / "mem.db")
    return CognitionHub(Path(tmp_path) / "cog.db",
                        memory_engine=MemoryEngine(_Bus(), store))


def _mem(hub, content: str, *, status="active", ts=None):
    import time as _t
    from furina.memory import Memory, MemoryLevel, MemoryStatus
    m = Memory(mem_id=f"mem_{abs(hash(content)) % 10**6}",
               level=MemoryLevel.EPISODIC, content=content,
               status=MemoryStatus(status),
               timestamp=ts if ts is not None else _t.time())
    hub.autobiography.insert(m)
    return m.mem_id


def _spawn(code: str, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, env=env, cwd=os.getcwd())
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ================================================================ R2/R3 稳定哈希
def test_d2_r2_stable_hashing_across_processes():
    code = (
        "from furina.cognition.retrieval.encoders import HashedLexicalVectorEncoder\n"
        "import struct\n"
        "e=HashedLexicalVectorEncoder(dim=64, seed=7)\n"
        "v=e.encode(['冷萃咖啡'])[0]\n"
        "print(struct.pack('<%df' % len(v), *v).hex())\n"
    )
    a = _spawn(code, {"PYTHONHASHSEED": "1"})
    b = _spawn(code, {"PYTHONHASHSEED": "999"})
    assert a == b, "跨进程向量必须字节一致（不受 PYTHONHASHSEED 影响）"


def test_d2_r3_persisted_index_loads_in_new_process_without_rebuild(tmp_path):
    from furina.cognition.retrieval.encoders import HashedLexicalVectorEncoder
    from furina.cognition.retrieval.index import DerivedRetrievalIndex, default_index_path
    ip = default_index_path(Path(tmp_path) / "cog.db")
    idx = DerivedRetrievalIndex(index_path=ip, encoder=HashedLexicalVectorEncoder(dim=64))
    idx.build(memories=[
        type("M", (), {"mem_id": "m1", "content": "用户喜欢喝冷萃咖啡",
                       "timestamp": 1.0, "status": "active"})])
    parent_hits = {r["ref_id"]: round(r["vec"], 6)
                   for r in idx.vector_lookup("冷萃咖啡")}
    code = f"""
import json
from furina.cognition.retrieval.encoders import HashedLexicalVectorEncoder
from furina.cognition.retrieval.index import DerivedRetrievalIndex
ip = {str(ip)!r}
idx = DerivedRetrievalIndex(index_path=ip, encoder=HashedLexicalVectorEncoder(dim=64))
hits = {{r['ref_id']: round(r['vec'], 6) for r in idx.vector_lookup('冷萃咖啡')}}
print(json.dumps(hits, ensure_ascii=False))
"""
    out = _spawn(code, {"PYTHONHASHSEED": "4242"})
    assert json.loads(out) == parent_hits, "子进程直载（不重建）必须得到一致向量检索"


# ================================================================ R4/R5/R6 兼容契约
def _persisted_with_meta(tmp_path, **meta):
    from furina.cognition.retrieval.index import (INDEX_MARKER,
                                                   default_index_path)
    ip = default_index_path(Path(tmp_path) / "cog.db")
    dim = meta.get("dim", 256)
    data = {"marker": INDEX_MARKER,
            "version": meta.get("version", "15E.2"),
            "built_at": 0.0, "dim": dim,
            "backend": meta.get("backend", "HASHED_LEXICAL_VECTOR"),
            "vector_ok": True, "truncated": 0,
            "items": [{"store": "C3", "ref_id": "m1", "text": "冷萃咖啡",
                       "keywords": [], "vec": [0.1] * dim,
                       "ts": 0.0, "status": "active"}]}
    ip.parent.mkdir(parents=True, exist_ok=True)
    ip.write_text(json.dumps(data), encoding="utf-8")
    return ip


def test_d2_r4_version_mismatch_disables_vectors(tmp_path):
    from furina.cognition.retrieval.index import DerivedRetrievalIndex
    ip = _persisted_with_meta(tmp_path, version="OLD.1")
    idx = DerivedRetrievalIndex(index_path=ip)
    st = idx.status()
    assert st["vector_invalid"] is True
    assert "version_mismatch" in st["vector_invalid_reason"]
    assert st["vector_enabled"] is False
    assert idx.vector_lookup("冷萃咖啡") == []
    assert idx.lexical_lookup("冷萃咖啡"), "lexical 仍可用"
    idx.build(memories=[type("M", (), {"mem_id": "m1", "content": "冷萃咖啡",
                                       "timestamp": 0.0, "status": "active"})])
    assert idx.status()["vector_enabled"] is True, "重建即恢复"


def test_d2_r5_backend_mismatch_disables_vectors(tmp_path):
    from furina.cognition.retrieval.index import DerivedRetrievalIndex
    ip = _persisted_with_meta(tmp_path, backend="PROVIDER_SEMANTIC_EMBEDDING")
    idx = DerivedRetrievalIndex(index_path=ip)
    st = idx.status()
    assert st["vector_invalid"] is True
    assert "backend_mismatch" in st["vector_invalid_reason"]
    assert idx.vector_lookup("冷萃咖啡") == []
    assert idx.lexical_lookup("冷萃咖啡")


def test_d2_r6_dimension_mismatch_disables_vectors(tmp_path):
    from furina.cognition.retrieval.index import DerivedRetrievalIndex
    ip = _persisted_with_meta(tmp_path, dim=128)
    idx = DerivedRetrievalIndex(index_path=ip)
    st = idx.status()
    assert st["vector_invalid"] is True
    assert "dimension_mismatch" in st["vector_invalid_reason"]
    assert idx.vector_lookup("冷萃咖啡") == []


# ================================================================ R7/R8 cosine 契约
def test_d2_r7_true_cosine_range(tmp_path):
    from furina.cognition.retrieval.index import DerivedRetrievalIndex
    from furina.cognition.retrieval.encoders import ProviderVectorEncoder
    idx = DerivedRetrievalIndex(encoder=ProviderVectorEncoder(
        lambda texts: [[10.0, 0.0] if t == "咖啡" else [0.0, 5.0]
                       for t in texts], dim=2))
    idx.build(memories=[
        type("M", (), {"mem_id": "a", "content": "咖啡", "timestamp": 0.0,
                       "status": "active"}),
        type("M", (), {"mem_id": "b", "content": "骑行", "timestamp": 0.0,
                       "status": "active"}),
    ])
    hits = {r["ref_id"]: r["vec"] for r in idx.vector_lookup("咖啡")}
    assert abs(hits["a"] - 1.0) < 1e-4, hits          # [10,0]·[2,0] 归一后 = 1.0（非 20）
    assert abs(hits.get("b", 0.0)) < 1e-4, hits       # 正交 → 0.0（min_sim 过滤下可为缺席）
    for v in hits.values():
        assert -1.0 - 1e-6 <= v <= 1.0 + 1e-6, v


def test_d2_r8_malformed_provider_falls_soft_to_lexical(tmp_path):
    from furina.cognition.retrieval.index import DerivedRetrievalIndex
    from furina.cognition.retrieval.encoders import ProviderVectorEncoder
    idx = DerivedRetrievalIndex(encoder=ProviderVectorEncoder(
        lambda texts: [["bad", "dim"] for _ in texts], dim=2))
    idx.build(memories=[
        type("M", (), {"mem_id": "a", "content": "冷萃咖啡", "timestamp": 0.0,
                       "status": "active"})])
    assert idx.vector_lookup("冷萃咖啡") == [], "畸形向量 fail-soft 到空"
    assert idx.lexical_lookup("冷萃咖啡"), "lexical 必须继续"
    assert idx.status()["vector_enabled"] is False


# ================================================================ R9/R10 lazy lifecycle
def test_d2_r9_production_activation_without_manual_build(tmp_path):
    hub = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    assert hub.index.count() == 0
    ctx = hub.assemble(query="咖啡")                   # 无手动 build_index
    assert hub.index.count() >= 1, "首次 assemble 必须自动构建 derived index"
    assert hub.index.status()["vector_enabled"] is True
    assert any("冷萃" in m for m in ctx.autobiographical_memories)
    hub.close()


def test_d2_r10_unchanged_second_assemble_does_not_rebuild(tmp_path):
    hub = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    hub.ensure_index_current()
    base = hub.index.count()
    calls = {"n": 0}
    orig = hub.build_index

    def counted(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)
    hub.build_index = counted
    hub.assemble(query="咖啡")
    hub.assemble(query="咖啡")
    assert calls["n"] == 0, "指纹未变不得重建/重新编码"
    assert hub.index.count() == base
    hub.close()


# ================================================================ R11 不压制权威召回
def test_d2_r11_new_authoritative_memory_not_suppressed_by_stale_hybrid(tmp_path):
    hub = _hub(tmp_path)
    _mem(hub, "旧的弱相关记忆：用户喜欢看海")
    hub.build_index()                                  # 索引只含旧记忆
    _mem(hub, "用户昨天提到想要一辆新自行车")          # 索引之后新增权威记忆
    ctx = hub.assemble(query="自行车")
    assert any("自行车" in m for m in ctx.autobiographical_memories), \
        "derived 非空弱候选不得压制权威新记忆"
    assert len(ctx.autobiographical_memories) <= hub.assembler._bounds["memories"]
    hub.close()


# ================================================================ R12 build 失败真状态
def test_d2_r12_build_encoder_failure_truthful_and_persisted(tmp_path):
    from furina.cognition.retrieval.index import (DerivedRetrievalIndex,
                                                   default_index_path)
    from furina.cognition.retrieval.encoders import ProviderVectorEncoder
    ip = default_index_path(Path(tmp_path) / "cog.db")

    def boom(texts):
        raise RuntimeError("build-time encoder down")
    idx = DerivedRetrievalIndex(index_path=ip,
                                encoder=ProviderVectorEncoder(boom, dim=8))
    idx.build(memories=[
        type("M", (), {"mem_id": "a", "content": "冷萃咖啡", "timestamp": 0.0,
                       "status": "active"})])
    st = idx.status()
    assert st["vector_enabled"] is False and st["vector_unavailable"] is True
    assert "encoder down" in st["last_vector_error"]
    assert idx.lexical_lookup("冷萃咖啡")
    # restart/load 保持诚实状态（vector_ok 已持久化）
    idx2 = DerivedRetrievalIndex(index_path=ip,
                                 encoder=ProviderVectorEncoder(boom, dim=8))
    st2 = idx2.status()
    assert st2["vector_enabled"] is False and st2["vector_unavailable"] is True
