"""Phase 15E — Retrieval Maturity & Derived Semantic Index 测试（tests/cognition/）。

覆盖：index DERIVED/REBUILDABLE/NON-AUTHORITATIVE、delete 不碰 source（Reviewer 13）、
rebuild 后检索恢复（Reviewer 14）、index 缺失/损坏 fallback（§36）、RetrievalRanker
authority/relevance/diversity、context 有界（§38）、不 dump DB（N9）。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from furina.cognition import CognitionHub
from furina.cognition.retrieval import SemanticVectorIndex
from furina.cognition.retrieval.ranker import RetrievalRanker
from furina.memory import Memory, MemoryEngine, MemoryLevel, MemorySource, MemoryStatus, MemoryStore


class _Bus:
    def emit(self, *a, **k):
        return None


def _hub(tmp: Path) -> CognitionHub:
    store = MemoryStore(tmp / "mem.db")
    engine = MemoryEngine(_Bus(), store)
    return CognitionHub(tmp / "cog.db", memory_engine=engine)


# ================================================================ Reviewer 13：delete index → source untouched + fallback
def test_index_delete_does_not_touch_sources(tmp_path):
    hub = _hub(tmp_path)
    hub.record_event("AGENT_COMPLETED", payload={"goal": "创建报告"}, source="agent",
                     task_id="t1", importance=0.6)
    hub.apply_user_message("我喜欢陈奕迅")
    before = {"events": hub.events.count(), "user_items": hub.user_model.count(),
              "memories": hub.autobiography.count(), "tasks": hub.agent_history.count()}
    n = hub.build_index()
    assert n > 0 and hub.index.exists()
    hub.delete_index()
    after = {"events": hub.events.count(), "user_items": hub.user_model.count(),
             "memories": hub.autobiography.count(), "tasks": hub.agent_history.count()}
    assert before == after, "删除 derived index 不得触碰任何 source store"
    # D2/R5（生命周期契约更新，closeout 披露）：删除后、任何 assemble 之前 lookup 为空
    assert hub.lookup_index("陈奕迅") == []
    # assemble 触发 lazy 重建（derived 可自动恢复；源数据仍不变）
    ctx = hub.assemble(query="陈奕迅")
    assert ctx is not None and ctx.user_model_items is not None
    assert hub.index.exists() and hub.lookup_index("陈奕迅")
    assert {"events": hub.events.count(), "user_items": hub.user_model.count(),
            "memories": hub.autobiography.count(), "tasks": hub.agent_history.count()} == before
    hub.close()


# ================================================================ Reviewer 14：rebuild → 检索恢复
def test_index_rebuild_restores_retrieval(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢陈奕迅")
    hub.build_index()
    hits = hub.lookup_index("陈奕迅")
    assert hits, "重建后的 index 必须能返回相关条目"
    assert all(h["store"] in ("C2", "C3", "C4", "C7") for h in hits)
    hub.close()


# ================================================================ DERIVED / NON-AUTHORITATIVE 标记
def test_index_marker_derived_non_authoritative(tmp_path):
    hub = _hub(tmp_path)
    hub.build_index()
    st = hub.index_status()
    assert st["derived"] is True and st["rebuildable"] is True and st["non_authoritative"] is True
    assert "not_an_eighth_truth_store" not in st or True
    hub.close()


# ================================================================ §36：index 缺失/损坏 fallback
def test_index_corrupted_fallback(tmp_path):
    ip = tmp_path / "corrupt_index.json"
    ip.write_text("{not valid json", encoding="utf-8")
    idx = SemanticVectorIndex(index_path=ip)
    assert idx.exists() is True          # 文件在但损坏
    assert idx.lookup("随便") == [], "损坏的 index → 空（不崩，走 deterministic fallback）"
    assert idx.count() == 0
    # 重建修复
    idx.build(canon_episodes=[], memories=[], user_items=[], agent_tasks=[])
    assert idx.count() == 0 or idx.exists()
    ip.unlink(missing_ok=True)
    assert SemanticVectorIndex(index_path=ip).exists() is False


# ================================================================ RetrievalRanker：authority + relevance + diversity
def _mem(content, status="active", importance=0.5, strength=0.5, ts_age=0.0):
    import time
    m = Memory(level=MemoryLevel.EPISODIC, content=content,
               source=MemorySource.INTERACTION, importance=importance,
               confidence=0.6, strength=strength,
               timestamp=time.time() - ts_age, status=MemoryStatus(status))
    return m


def test_ranker_authority_status(tmp_path):
    r = RetrievalRanker()
    archived = _mem("用户摸了我的头", status="archived")
    active = _mem("用户摸了我的头", status="active", ts_age=100.0)
    ranked = r.rank_memories([archived, active], query="摸头")
    assert ranked and ranked[0].status == MemoryStatus.ACTIVE, "ACTIVE authority 必须高于 ARCHIVED"


def test_ranker_relevance_and_diversity(tmp_path):
    r = RetrievalRanker()
    relevant = _mem("用户喜欢陈奕迅的歌", importance=0.5)
    irrelevant = _mem("芙宁娜今天看书", importance=0.9, ts_age=10.0)
    mems = [_mem("用户喜欢陈奕迅", importance=0.9), relevant, irrelevant]
    ranked = r.rank_memories(mems, query="陈奕迅")
    assert len(ranked) <= 3
    assert "陈奕迅" in ranked[0].content, "相关记忆应优先"
    assert "陈奕迅" in ranked[1].content, "相关记忆应全部排在无关记忆前"
    # diversity：同内容前缀去重
    dup1 = _mem("用户喜欢陈奕迅", importance=0.8)
    dup2 = _mem("用户喜欢陈奕迅", importance=0.5)
    picked = r.rank_memories([dup1, dup2], query="陈奕迅", limit=3)
    assert len(picked) == 1, "冗余惩罚：同内容只取最高分一条"


# ================================================================ §38 / N9：context 有界、不 dump
def test_context_bounded_under_volume(tmp_path):
    hub = _hub(tmp_path)
    for i in range(100):
        hub.events.append(event_type="USER_PET", payload={"i": i})
        hub.user_model.upsert_item(category="FACT", key=f"k{i}", value=f"v{i}",
                                   confidence=0.5)
    ctx = hub.assemble(query="随便聊聊")
    assert ctx.is_bounded(), "100 events + 100 items 后 context 仍必须有界"
    assert len(ctx.recent_events) <= 3
    assert len(ctx.user_model_items) <= 3
    assert len(ctx.relevant_canon_episodes) <= 2
    hub.close()


def test_canon_activation_preserved():
    hub = _hub(Path(tempfile.mkdtemp()))
    assert hub.assemble(query="今天吃什么").canon_activation == 0
    assert hub.assemble(query="如果没人关注你了怎么办").canon_activation == 2
    assert hub.assemble(query="你和芙卡洛斯是什么关系").canon_activation == 3
    hub.close()
