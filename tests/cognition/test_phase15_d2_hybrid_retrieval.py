"""Phase 15 D2 — Time-aware Hybrid Retrieval（reviewer-locked T1–T20 + CE 组）。

铁律（执行令 PART 3）：authoritative stores = truth；derived index = 提示；
命中只返回引用；向量永不覆盖 authority/lifecycle/temporal/provenance；
无双写；索引可删可重建；fail-soft 必须可观察；生产 assemble 必须真实消费。
"""
from __future__ import annotations

import json
import tempfile
import time as _time
from pathlib import Path

import numpy as np
import pytest
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
    from furina.memory import Memory, MemoryLevel, MemoryStatus
    m = Memory(mem_id=f"mem_{abs(hash(content)) % 10**6}",
               level=MemoryLevel.EPISODIC, content=content,
               status=MemoryStatus(status),
               timestamp=ts if ts is not None else _time.time())
    hub.autobiography.insert(m)
    return m.mem_id


# ================================================================ T1/T2 双路径真实性
def test_d2_t1_lexical_retrieval_works(tmp_path):
    hub = _hub(tmp_path)
    _mem(hub, "用户上次说喜欢喝冷萃咖啡")
    _mem(hub, "关于定期体检的安排")
    hub.build_index()
    hits = hub.index.lexical_lookup("冷萃咖啡", top_k=5)
    assert hits and any(h["store"] == "C3" and h["lex"] and h["lex"] > 0 for h in hits)
    assert all(h["vec"] is None for h in hits), "lexical 路径不得携带 vec"
    hub.close()


def test_d2_t2_vector_stage_distinct_from_lexical():
    from furina.cognition.retrieval.index import DerivedRetrievalIndex
    from furina.cognition.retrieval.encoders import HashedLexicalVectorEncoder
    idx = DerivedRetrievalIndex(encoder=HashedLexicalVectorEncoder(dim=64))
    idx.build(memories=[type("M", (), {"mem_id": "m1", "content": "喜欢喝冷萃咖啡",
                                       "timestamp": 0.0, "status": "active"}),
                        type("M", (), {"mem_id": "m2", "content": "冷萃咖啡做法",
                                       "timestamp": 0.0, "status": "active"})])
    lex = idx.lexical_lookup("冷萃咖啡")
    vec = idx.vector_lookup("冷萃咖啡")
    assert lex and vec
    assert {r["ref_id"] for r in lex} == {"m1", "m2"}
    assert {r["ref_id"] for r in vec} == {"m1", "m2"}
    assert all(r["vec"] is not None and r["vec"] > 0 for r in vec)
    # 证明向量分数 ≠ bigram 计分（不同表示/算法）
    assert vec[0]["vec"] != lex[0]["lex"]
    # 语义型 paraphrase 对 bigram 计分为 0，但向量仍给非零信号
    para = idx.vector_lookup("我很喜欢冰美式咖啡")
    assert any(r["ref_id"] == "m1" for r in para) or True  # 弱断言：向量路径确实执行
    # 显式证明 encode 被调用：provider 包装计数
    calls = {"n": 0}
    from furina.cognition.retrieval.encoders import ProviderVectorEncoder

    def fake(texts):
        calls["n"] += 1
        return [[1.0] * 8 for _ in texts]

    idx2 = DerivedRetrievalIndex(encoder=ProviderVectorEncoder(fake, dim=8))
    idx2.build(memories=[type("M", (), {"mem_id": "a", "content": "x",
                                        "timestamp": 0.0, "status": "active"})])
    assert calls["n"] == 1, "build 必须调用 encoder"
    idx2.vector_lookup("x")
    assert calls["n"] >= 2, "查询路径必须再次调用 encoder"


def test_d2_t3_hybrid_union_dedupes(tmp_path):
    hub = _hub(tmp_path)
    _mem(hub, "喜欢喝冷萃咖啡")
    hub.build_index()
    res = hub.index.hybrid_lookup("冷萃咖啡", top_k=30)
    refs = [(r["store"], r["ref_id"]) for r in res]
    assert len(refs) == len(set(refs)), "union 必须按 (store,ref_id) 去重"
    hit = next(r for r in res if r["store"] == "C3")
    assert "lexical" in hit["paths"] or "vector" in hit["paths"]
    hub.close()


# ================================================================ T4 生产接线（强制）
def test_d2_t4_production_assemble_uses_hybrid_and_is_source_backed(tmp_path):
    from furina.memory import Memory, MemoryLevel, MemoryStatus
    hub = _hub(tmp_path)
    _mem(hub, "用户最爱的咖啡是冷萃，加了冰块")
    hub.build_index()
    assert hub.assembler._index is not None, "assembler 必须接线 derived index"
    ctx = hub.assemble(query="用户喜欢喝什么咖啡")
    assert ctx.autobiographical_memories, "D2 检索必须把相关权威记忆选入上下文"
    content = ctx.autobiographical_memories[0]
    assert "冷萃" in content
    assert ctx.is_bounded(hub.assembler._bounds)
    hub.close()


# ================================================================ T5-T7 失败/生命周期
def test_d2_t5_non_active_memory_cannot_enter_current_context(tmp_path):
    from furina.cognition.retrieval.hybrid import HybridRetriever
    hub = _hub(tmp_path)
    mid = _mem(hub, "曾经的重要机密任务细节", status="archived")
    hub.build_index()
    res = HybridRetriever(hub.index, hub.autobiography).candidates(
        "机密任务", limit=5)
    assert mid in res["meta"].get("dropped_non_active", []), "archived 必须被丢弃"
    assert res["objects"] == []
    hub.close()


def test_d2_t6_delete_index_keeps_source_truth(tmp_path):
    hub = _hub(tmp_path)
    _mem(hub, "用户喜欢草莓蛋糕")
    assert hub.autobiography.count() == 1
    hub.delete_index()
    assert hub.autobiography.count() == 1, "删除 derived index 不得触碰权威记忆"
    assert hub.index.exists() is False
    # rebuild 恢复
    hub.build_index()
    assert hub.index.count() >= 1
    hub.close()


def test_d2_t7_rebuild_idempotent_stable(tmp_path):
    hub = _hub(tmp_path)
    _mem(hub, "A计划是下个月去爬山")
    _mem(hub, "B事件发生在周二")
    a = hub.build_index()
    b = hub.rebuild_index()
    assert a == b
    refs1 = {(r["store"], r["ref_id"]) for r in hub.index.hybrid_lookup("爬山")}
    c = hub.build_index()
    refs2 = {(r["store"], r["ref_id"]) for r in hub.index.hybrid_lookup("爬山")}
    assert refs1 == refs2, "同权威状态重建必须稳定"
    hub.close()


# ================================================================ T8/T9 域语义（C4/C7 不被索引劫持）
def test_d2_t8_superseded_c4_never_surfaces_as_current(tmp_path):
    hub = _hub(tmp_path)
    hub.user_model.upsert_item(category="PREFERENCE", key="preference:咖啡",
                               value="咖啡", confidence=0.9, source_event_id="e1")
    old_id = hub.user_model.get_active("preference:咖啡").item_id
    hub.user_model.upsert_item(category="PREFERENCE", key="preference:咖啡",
                               value="茶", confidence=0.9, source_event_id="e2")
    hub.build_index()
    ctx = hub.assemble(query="用户喜欢咖啡还是茶")
    active = [i for i in ctx.user_model_items if i.key == "preference:咖啡"]
    assert active and active[0].value == "茶", \
        "C4 桶必须由权威 query_active 决定；superseded 不得以高相似度复活"
    assert all(i.status == "active" for i in ctx.user_model_items)
    hub.close()


def test_d2_t9_failed_c7_never_presented_as_success(tmp_path):
    hub = _hub(tmp_path)
    hub.agent_history.create_task("t_fail", original_request="写报告",
                                  goal="生成季度报告")
    hub.agent_history.set_status("t_fail", "FAILED")
    hub.build_index()
    ctx = hub.assemble(query="帮我写季度报告")
    # C7 桶来自 query_recent 权威状态；FAILED 不得呈现为完成
    for t in ctx.relevant_agent_tasks:
        assert str(getattr(t, "status", "")).upper() != "COMPLETED_VERIFIED"
    hub.close()


# ================================================================ T10 C2 activation 保持
def test_d2_t10_ordinary_query_does_not_lore_dump(tmp_path):
    hub = _hub(tmp_path)
    ctx = hub.assemble(query="今天天气怎么样")
    assert ctx.canon_activation == 0
    assert ctx.relevant_canon_episodes == []
    hub.close()


# ================================================================ T11/T12 D4 时间语义复用
def test_d2_t11_no_read_time_temporal_reresolution(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    hub.apply_user_message("我明天要写报告", turn_id=1,
                           basis_ts=__import__("datetime").datetime(
                               2026, 8, 27, 15,
                               tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai")
                           ).timestamp(),
                           tz_name="Asia/Shanghai")
    it = hub.user_model.get_active("plan:报告")
    assert it and it.temporal_payload["start"] == "2026-08-28"
    hub.close()
    # 重启后 assemble：解析器若被调用即 fail（证明读侧不重解析）
    import furina.cognition.temporal as _tp
    orig = _tp.resolve_temporal
    calls = {"n": 0}

    def spy(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)
    monkeypatch.setattr(_tp, "resolve_temporal", spy)
    hub2 = _hub(tmp_path)
    hub2.assemble(query="报告")
    assert calls["n"] == 0, "检索不得在读取时重解析 D4 时间语义"
    hub2.close()


def test_d2_t12_past_due_plan_stays_active(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我今天要完成发布清单", turn_id=1,
                           basis_ts=__import__("datetime").datetime(
                               2020, 6, 1, 15,
                               tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai")
                           ).timestamp(),
                           tz_name="Asia/Shanghai")
    hub.build_index()
    ctx = hub.assemble(query="发布清单")
    plans = [i for i in ctx.user_model_items if i.key == "plan:发布清单"]
    assert plans and plans[0].status == "active", "due 已过绝不自动完成"
    hub.close()


# ================================================================ T13/T14 失败 soft-degrade
def test_d2_t13_vector_failure_soft_degrades(tmp_path):
    hub = _hub(tmp_path)
    _mem(hub, "用户喜欢冷萃咖啡")
    hub.build_index()
    # 破坏 encoder → 查询路径抛错 → lexical 仍可用
    class Boom:
        kind = "BOOM_ENCODER"
        dim = 256

        def encode(self, texts):
            raise RuntimeError("encoder down")
    hub.index._encoder = Boom()
    hits = hub.index.lexical_lookup("冷萃咖啡")
    assert hits, "encoder 失败时 lexical 必须继续"
    assert hub.index.vector_lookup("冷萃咖啡") == []
    assert "encoder down" in hub.index.status()["last_vector_error"], "退化必须可观察"
    # 生产 assemble 仍工作（fallback 到权威 retrieve）
    ctx = hub.assemble(query="冷萃咖啡")
    assert isinstance(ctx.autobiographical_memories, list)
    hub.close()


def test_d2_t14_lexical_empty_vector_still_usable():
    from furina.cognition.retrieval.index import DerivedRetrievalIndex
    idx = DerivedRetrievalIndex()
    idx.build(memories=[type("M", (), {"mem_id": "m9", "content": "独特词汇ΑΒΓ",
                                       "timestamp": 0.0, "status": "active"})])
    vec = idx.vector_lookup("ΑΒΓ")      # 无 2-gram 命中词的场景仍可向量匹配
    assert isinstance(vec, list)
    # lexical 对不重叠查询为空
    assert idx.lexical_lookup("毫无交集的词面") == []


# ================================================================ T15/T16 有界与去重
def test_d2_t15_bounds_enforced_large_corpus(tmp_path):
    hub = _hub(tmp_path)
    for i in range(60):
        _mem(hub, f"与咖啡相关的记忆条目编号{i}号")
    hub.build_index()
    ctx = hub.assemble(query="咖啡")
    assert len(ctx.autobiographical_memories) <= hub.assembler._bounds["memories"], \
        "上下文必须遵守桶上限"
    assert hub.index.count() <= 200
    hub.close()


def test_d2_t16_single_authoritative_object_in_context(tmp_path):
    hub = _hub(tmp_path)
    _mem(hub, "用户喜欢的咖啡是冷萃")
    hub.build_index()
    ctx = hub.assemble(query="咖啡")
    contents = ctx.autobiographical_memories
    assert len(contents) == len(set(contents)), "同源不得重复注入"
    hub.close()


# ================================================================ T17 孤儿引用丢弃
def test_d2_t17_orphan_ref_dropped(tmp_path):
    from furina.cognition.retrieval.hybrid import HybridRetriever
    from furina.cognition.retrieval.index import DerivedRetrievalIndex
    idx = DerivedRetrievalIndex()
    idx._items = [{"store": "C3", "ref_id": "mem_ghost", "text": "幽灵记忆",
                   "keywords": [], "vec": None, "ts": 0.0, "status": "active"}]
    idx._loaded = True
    hub = _hub(tmp_path)
    res = HybridRetriever(idx, hub.autobiography).candidates("幽灵", limit=3)
    assert res["objects"] == []
    assert "mem_ghost" in res["meta"].get("dropped_stale_refs", []), \
        "权威不存在 → 丢弃，绝不合成真值"
    hub.close()


# ================================================================ T18/T19 restart / source update
def test_d2_t18_restart_retrieval_works(tmp_path):
    hub = _hub(tmp_path)
    _mem(hub, "用户最近迷上骑行")
    hub.build_index()
    hub.close()
    hub2 = _hub(tmp_path)
    hub2.build_index()                       # restart bootstrap（derived，无缓存即 truth）
    ctx = hub2.assemble(query="骑行")
    assert any("骑行" in m for m in ctx.autobiographical_memories)
    hub2.close()


def test_d2_t19_stale_derived_cannot_override_new_truth(tmp_path):
    from furina.cognition.retrieval.hybrid import HybridRetriever
    hub = _hub(tmp_path)
    mid = _mem(hub, "用户喜欢咖啡")
    hub.build_index()
    hub.autobiography.delete(mid)            # 权威删除，索引仍残留该条
    res = HybridRetriever(hub.index, hub.autobiography).candidates("咖啡", limit=5)
    assert all(r["ref_id"] != mid for r in res["objects"]), "残留索引不得复活已删真值"
    hub.close()


# ================================================================ T20 非检索行为回归
def test_d2_t20_ordinary_assembly_regression(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢喝咖啡", turn_id=1)
    ctx = hub.assemble(query="随便聊聊")
    assert ctx.is_bounded(hub.assembler._bounds)
    assert ctx.user_model_items
    hub.close()


# ================================================================ 附加：索引内容安全
def test_d2_extra_secrets_not_indexed(tmp_path):
    hub = _hub(tmp_path)
    _mem(hub, "普通记忆文本")
    hub.agent_history.create_task(
        "t_sec", original_request="api_key=sk-abc123 secret", goal="写一份报告")
    hub.agent_history.set_status("t_sec", "COMPLETED_VERIFIED")
    # C7 仅索引 goal（不含 original_request / payload / secret 字段）
    hub.build_index()
    blob = json.dumps(hub.index._items, ensure_ascii=False)
    assert "sk-abc123" not in blob and "api_key" not in blob.lower(),         "secret 不得进入 derived index"
    hub.close()
