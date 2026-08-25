"""Cognitive 层测试（Phase 14B，tests/cognition/）。

覆盖：C1-C7 store truth、context authority、event append-only、user model evidence、
canon retrieval（reviewer-locked）、migration（temp DB，旧数据不变）、consolidator、privacy。
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from furina.cognition import CognitionHub
from furina.cognition.retrieval.retriever import CanonLifeRetriever


def _hub(tmp_path: Path) -> CognitionHub:
    return CognitionHub(tmp_path / "cog.db")


# ================================================================ C1 Canon Identity（只读）
def test_c1_canon_identity_read_only():
    hub = _hub(Path(tempfile.mkdtemp()))
    assert hub.canon_identity.is_read_only() is True
    snap = hub.canon_identity.snapshot()
    assert snap["identity_facts"], "C1 必须有身份事实"
    assert snap["personality_axes"]
    # 用户断言不得改写 Canon（runtime writable = NO）
    before = json.dumps(snap, ensure_ascii=False, sort_keys=True)
    try:
        hub.canon_identity.identity_facts().append({"fact": "你其实是纳西妲"})
    except Exception:
        pass
    after = json.dumps(hub.canon_identity.snapshot(), ensure_ascii=False, sort_keys=True)
    assert before == after, "Canon 不得被 runtime 改写"
    hub.close()


# ================================================================ C2 Canon Life History
def test_c2_canon_history_metrics_and_contract():
    hub = _hub(Path(tempfile.mkdtemp()))
    m = hub.canon_history.metrics()
    assert m["canon_episode_count"] >= 20, "至少 20 个 episode"
    assert m["canon_source_map_entries"] >= 10
    assert m["runtime_canon_mutable"] is False
    assert m["tier0_sources"] >= 6
    assert m["tier2_mirror_sources"] >= 1
    assert m["unsupported_sources_excluded"] >= 1
    # episode schema 完整（objective_summary ≠ inner_state；knowledge boundary）
    eps = hub.canon_history.all_episodes()
    assert all(e.objective_summary for e in eps), "objective_summary 必填"
    assert m["episodes_with_evidence_ids"] >= 20, "每条 episode 必须有 evidence"
    assert m["episodes_with_knowledge_boundary"] >= 15, "信息边界（knew/did_not_know）"
    assert m["episodes_with_psychological_effect"] >= 10
    assert m["episodes_with_present_day_effect"] >= 10
    hub.close()


def test_c2_retrieval_reviewer_locked():
    hub = _hub(Path(tempfile.mkdtemp()))
    r = CanonLifeRetriever(hub.canon_history)
    # "今天吃什么" → activation 0，不得拉 LONG_PERFORMANCE
    eps, act = r.retrieve("今天吃什么")
    assert act == 0 and eps == []
    # "没人关注你怎么办" → 相关 episodes（LONG_PERFORMANCE/ORDINARY_LIFE/CHOSEN_PERFORMANCE）
    eps, act = r.retrieve("没人关注你怎么办")
    ids = [e.episode_id for e in eps]
    assert act == 2
    assert any(i in ids for i in ("LONG_PERFORMANCE", "ORDINARY_LIFE", "CHOSEN_PERFORMANCE"))
    # "你和芙卡洛斯是什么关系" → ORIGIN_IDENTITY/FOCALORS_TRUTH activation 3
    eps, act = r.retrieve("你和芙卡洛斯是什么关系")
    assert act == 3 and [e.episode_id for e in eps] == ["ORIGIN_IDENTITY", "FOCALORS_TRUTH"]
    # "你当水神的时候开心吗" → PUBLIC_ROLE/LONG_PERFORMANCE activation 3
    eps, act = r.retrieve("你当水神的时候开心吗")
    assert act == 3
    assert any(e.episode_id in ("PUBLIC_ROLE_BEGIN", "LONG_PERFORMANCE") for e in eps)
    hub.close()


def test_c2_runtime_canon_mutable_false():
    hub = _hub(Path(tempfile.mkdtemp()))
    assert hub.canon_history.is_read_only() is True
    assert not hasattr(hub.canon_history, "append_episode"), "C2 不得有写方法"
    hub.close()


# ================================================================ C3 Autobiographical adapter
def test_c3_autobiography_adapter_single_table(tmp_path):
    from furina.memory import MemoryEngine, MemoryStore, MemoryLevel, MemorySource
    d = tmp_path
    store = MemoryStore(d / "mem.db")
    engine = MemoryEngine(EventBusFake(), store)
    hub = CognitionHub(d / "cog.db", memory_engine=engine)
    m = hub.autobiography.observe("用户第一次摸我的头", level=MemoryLevel.EPISODIC,
                                  source=MemorySource.INTERACTION, importance=0.6)
    assert m is not None
    assert engine.store.count() == 1, "C3 只写 existing memories 表"
    # 不得存在第二张 cognitive memory 表
    conn = sqlite3.connect(str(d / "cog.db"))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert not any("cognitive_mem" in t or "autobiographical_mem" in t for t in tables), \
        "禁止第二套记忆 truth"
    assert hub.autobiography.backing_table == "memories"
    hub.close()


class EventBusFake:
    def emit(self, *a, **k):
        return None


# ================================================================ C4 User Model
def test_c4_user_model_evidence_and_supersede(tmp_path):
    hub = _hub(tmp_path)
    it = hub.user_model.upsert_item(category="PREFERENCE", key="tea", value="喜欢喝茶",
                                    confidence=0.9, source_text_excerpt="我喜欢喝茶")
    it2 = hub.user_model.upsert_item(category="PREFERENCE", key="tea", value="现在喜欢咖啡",
                                     confidence=0.9, source_text_excerpt="我现在喜欢咖啡")
    old = hub.user_model.get_active("tea")
    assert old is not None and old.value == "现在喜欢咖啡", "新值生效"
    # 旧 item 必须 superseded（不得无历史 overwrite）
    conn = sqlite3.connect(str(tmp_path / "cog.db"))
    rows = conn.execute("SELECT status FROM user_model_items WHERE category='PREFERENCE' "
                        "AND key='tea' ORDER BY created_at").fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["superseded", "active"], f"supersede 语义: {rows}"
    hub.close()


def test_c4_extraction_conservative(tmp_path):
    hub = _hub(tmp_path)
    # 明确高置信 → PLAN
    cand = hub.extract_user_model("我今天准备完成桌宠测试")
    assert cand and cand["category"] == "PLAN" and cand["confidence"] >= 0.8
    # 明确喜欢 → PREFERENCE
    cand = hub.extract_user_model("我喜欢陈奕迅")
    assert cand and cand["category"] == "PREFERENCE" and "陈奕迅" in cand["value"]
    # 不喜欢催 → DISLIKE
    cand = hub.extract_user_model("我不喜欢别人一直催我")
    assert cand and cand["category"] == "DISLIKE"
    # 模糊一句 → 不得自动成为永久人格标签
    assert hub.extract_user_model("这首歌不错") is None
    hub.close()


def test_c4_user_model_context_contains_plan(tmp_path):
    hub = _hub(tmp_path)
    hub.user_model.upsert_item(category="PLAN", key="plan_today", value="完成桌宠测试",
                               confidence=0.85, source_text_excerpt="我今天准备完成桌宠测试")
    ctx = hub.assemble(query="我今天准备干什么？")
    assert any(i.category == "PLAN" and "桌宠" in str(i.value) for i in ctx.user_model_items), \
        "Context 必须含 PLAN"
    hub.close()


# ================================================================ C5 Relationship
def test_c5_relationship_adapter(tmp_path):
    from furina.relationship.engine import RelationshipEngine
    eng = RelationshipEngine()
    hub = _hub(tmp_path)
    # 先用带 engine 的 hub 验证 factors 同源
    hub.close()
    hub = CognitionHub(tmp_path / "cog2.db", relationship_engine=eng)
    assert hub.relationship.factors() == eng.factors(), "current truth 来自 existing engine"
    before = eng.factors()["familiarity"]
    hub.relationship.apply("positive_response", reason="测试")
    assert eng.factors()["familiarity"] > before, "写入口委托 engine（唯一 owner）"
    hub.relationship.record_milestone("first_positive", "第一次积极回应")
    ms = hub.relationship.milestones()
    assert ms and ms[0]["milestone_type"] == "first_positive"
    hub.close()


# ================================================================ C6 Event Timeline
def test_c6_event_append_only(tmp_path):
    hub = _hub(tmp_path)
    ev = hub.events.append(event_type="USER_PET", payload={"kind": "pet"}, importance=0.5)
    with pytest.raises(ValueError):
        hub.events.append(event_type="USER_PET", event_id=ev.event_id)  # 不可悄悄 overwrite
    assert hub.events.count() == 1
    hub.close()


def test_c6_query_and_payload_safety(tmp_path):
    hub = _hub(tmp_path)
    hub.events.append(event_type="AGENT_COMPLETED", payload={"goal": "整理目录"},
                      task_id="task_x", importance=0.6)
    hub.events.append(event_type="USER_PET", payload={"kind": "pet"}, turn_id=7)
    hub.events.append(event_type="AGENT_COMPLETED", payload={"goal": "创建文档"},
                      task_id="task_y")
    assert len(hub.events.query_by_task("task_x")) == 1
    assert len(hub.events.query_by_turn(7)) == 1
    assert len(hub.events.query_by_type("AGENT_COMPLETED")) == 2
    assert len(hub.events.query_recent(limit=10)) == 3
    # 隐私：payload 中的敏感 token 必须 redacted；不存 interpretation
    hub.events.append(event_type="SYSTEM_EVENT",
                      payload={"note": "api_key=sk-abcdef1234567890 已配置"}, importance=0.1)
    evs = hub.events.query_by_type("SYSTEM_EVENT")
    assert evs and "sk-abcdef" not in json.dumps(evs[0].payload, ensure_ascii=False), \
        "敏感 token 不得持久化"
    # 长文本/深层对象 normalize
    hub.events.append(event_type="SYSTEM_EVENT", payload={"big": "x" * 5000})
    assert len(hub.events.query_recent(1)[0].payload_json) <= 2200, "长文本必须截断"
    hub.close()


# ================================================================ C7 Agent Task History
def test_c7_agent_task_history_exact(tmp_path):
    hub = _hub(tmp_path)
    tid = hub.agent_history.create_task(original_request="把 notes.md 整理到 Docs", goal="移动 notes.md")
    hub.agent_history.add_step(tid, 0, tool="fs.move",
                               args={"source": "C:/notes.md", "dest": "C:/Docs/notes.md",
                                     "api_key": "sk-secret123"},
                               capability="FILESYSTEM", permission_level="L1",
                               status="COMPLETED_VERIFIED", verified=True,
                               result={"dest": "C:/Docs/notes.md"})
    hub.agent_history.add_artifact(tid, "file", "C:/Docs/notes.md", exists_verified=True)
    hub.agent_history.complete_task(tid, verified=True, result_summary="已移动到 Docs")
    t = hub.agent_history.get_task(tid)
    assert t is not None and t.status == "COMPLETED_VERIFIED" and t.verified is True
    # args 写库前 redaction
    step = hub.agent_history.steps(tid)[0]
    assert "sk-secret123" not in step.args_redacted_json, "args 必须 redacted"
    # 精确查询：notes.md → exact destination
    found = hub.agent_history.find_latest_by_artifact("notes.md")
    assert found and found[0].task_id == tid
    arts = hub.agent_history.artifacts(tid)
    assert arts[0].path == "C:/Docs/notes.md" and arts[0].exists_verified is True
    hub.close()


def test_c7_ok_not_verified_never_completed(tmp_path):
    hub = _hub(tmp_path)
    tid = hub.agent_history.create_task(goal="启动应用")
    hub.agent_history.add_step(tid, 0, tool="app.launch", args={"name": "x"},
                               status="UNVERIFIED", verified=False)
    hub.agent_history.complete_task(tid, verified=False, result_summary="")
    t = hub.agent_history.get_task(tid)
    assert t.status == "UNVERIFIED", "ok!=verified → UNVERIFIED（不得 COMPLETED）"
    hub.close()


# ================================================================ Context Assembler
def test_context_assembler_bounded(tmp_path):
    hub = _hub(tmp_path)
    for i in range(12):
        hub.events.append(event_type="USER_PET", payload={"i": i})
    for i in range(8):
        hub.user_model.upsert_item(category="FACT", key=f"k{i}", value=f"v{i}", confidence=0.6)
    ctx = hub.assemble(query="随便聊聊")
    assert ctx.is_bounded(), "context 必须 bounded"
    assert len(ctx.recent_events) <= 5
    assert len(ctx.user_model_items) <= 5
    assert ctx.canon_identity  # C1 只读视图
    hub.close()


def test_context_authority_fields_present(tmp_path):
    hub = _hub(tmp_path)
    ctx = hub.assemble(query="今天吃什么", current_facts={"activity": "read"})
    assert ctx.current_facts.get("activity") == "read"
    assert ctx.canon_activation == 0
    hub.close()


# ================================================================ Consolidator
def test_consolidator_event_only_vs_memory(tmp_path):
    from furina.cognition.consolidation.consolidator import Consolidator
    c = Consolidator()
    # 普通事件 → Event only
    plan = c.consider("ACTIVITY_STARTED", payload={"activity": "read"}, importance=0.0)
    assert plan["form_memory"] is False and plan["user_model"] is None
    # 用户摸头（高 importance）→ 条件 Memory
    plan = c.consider("USER_PET", payload={"strong": True}, importance=0.6)
    assert plan["form_memory"] is True
    # 明确用户计划 → UserModel PLAN + memory
    plan = c.consider("USER_PLAN_DECLARED", payload={"key": "plan_today", "value": "测试",
                                                     "confidence": 0.85}, importance=0.6)
    assert plan["user_model"] is not None and plan["user_model"]["category"] == "PLAN"
    # Agent 成功 → episodic memory（单 owner）
    plan = c.consider("AGENT_COMPLETED", payload={"goal": "创建文档"}, importance=0.6, verified=True)
    assert plan["form_memory"] is True
    # 关系里程碑 → milestone，不复制成 memory
    plan = c.consider("RELATIONSHIP_MILESTONE", payload={"type": "repair", "note": "和好"})
    assert plan["milestone"] is not None and plan["form_memory"] is False


def test_consolidator_single_owner_via_hub(tmp_path):
    hub = _hub(tmp_path)
    hub.record_event("AGENT_COMPLETED", payload={"goal": "创建文档"}, source="agent",
                     task_id="task_1", importance=0.6)
    assert hub.events.count() == 1, "Event 恰好一次"
    hub.record_event("AGENT_COMPLETED", payload={"goal": "创建文档"}, source="agent",
                     task_id="task_2", importance=0.6)
    assert hub.events.count() == 2, "每个事件恰好一条（单 owner）"
    hub.close()


# ================================================================ Work Willingness（model-only）
def test_willingness_model_only_no_production_refusal():
    from furina.cognition import WorkWillingnessInput, WorkDisposition
    hub = _hub(Path(tempfile.mkdtemp()))
    r = hub.willingness.estimate(WorkWillingnessInput(fatigue=0.95, energy=0.1, annoyance=0.9))
    assert r.refusal_eligible is False, "本 Phase 禁止 production refusal"
    assert isinstance(r.disposition, WorkDisposition)
    hub.close()


# ================================================================ Migration（temp DB only）
def test_migration_preserves_old_memories_and_relationship(tmp_path):
    """旧 Phase13 DB → 新版本打开：schema 增加；memories count 不变；relationship 值不变。"""
    from furina.memory import MemoryEngine, MemoryStore, MemoryLevel, MemorySource
    from furina.relationship.engine import RelationshipEngine
    old_db = tmp_path / "furina.db"
    store = MemoryStore(old_db)
    engine = MemoryEngine(EventBusFake(), store)
    engine.observe("旧记忆：用户喜欢喝茶", level=MemoryLevel.SEMANTIC,
                   source=MemorySource.USER_EXPLICIT, importance=0.8)
    engine.observe("旧记忆：帮用户整理过下载文件夹", level=MemoryLevel.EPISODIC,
                   source=MemorySource.AGENT_TASK, importance=0.7)
    rel = RelationshipEngine(store.load_relationship())
    rel.apply("positive_response")
    store.save_relationship(rel.state)
    old_count = store.count()
    old_rel = dict((k, v) for k, v in store.load_relationship().as_dict().items())
    store.close()
    # 打开新版（同一 DB 路径）→ schema 增加 + 旧数据不变
    hub = CognitionHub(old_db, memory_engine=MemoryEngine(EventBusFake(), MemoryStore(old_db)),
                       relationship_engine=RelationshipEngine())
    new_store = MemoryStore(old_db)
    assert new_store.count() == old_count, f"memories count 必须不变: {new_store.count()} vs {old_count}"
    new_rel = dict((k, v) for k, v in new_store.load_relationship().as_dict().items())
    assert new_rel == old_rel, "relationship 值必须不变"
    conn = sqlite3.connect(str(old_db))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"user_model_items", "life_events", "agent_tasks"} <= tables, "新 schema 已增加"
    assert hub.schema_version
    hub.close()


# ================================================================ Deletion APIs
def test_deletion_apis(tmp_path):
    hub = _hub(tmp_path)
    it = hub.user_model.upsert_item(category="FACT", key="k", value="v", confidence=0.6)
    tid = hub.agent_history.create_task(goal="g")
    hub.agent_history.complete_task(tid, verified=True, result_summary="ok")
    hub.events.append(event_type="USER_PET")
    hub.user_model.delete_item(it.item_id)
    hub.agent_history.delete_task(tid)
    n = hub.events.clear()
    assert hub.user_model.count() == 0
    assert hub.agent_history.get_task(tid) is None
    assert hub.events.count() == 0 and n >= 1
    hub.close()
