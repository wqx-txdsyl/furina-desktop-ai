"""Phase 15.1 Cognitive Truth Closure 测试（tests/cognition/ + production path）。

覆盖 Reviewer R1-R15 与负面契约 N1-N10：
- R1/R2：双偏好共存 + 实体级 supersede（陈奕迅 与 咖啡 互不影响）
- R3/R4/R5：双计划共存 + 定向完成 + 模糊完成安全（不批量完成）
- R6/R7/R8：production pet/feed/Agent C3 provenance（真实 Furina ingress）
- R9：Failed Agent 无成功记忆
- R10：C5 milestone → source_event_id → C6 可解析
- R11/R12：C2 mandatory source 解析 + used-source 证明（未使用来源不计）
- R13：Canon 文件 runtime checksum 不变
- R14/R15：restart 幂等 + bounded context 保持绿
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from furina.app import Furina
from furina.cognition import CognitionHub
from furina.config import AppConfig, LLMProfile
from furina.memory import MemoryEngine, MemorySource, MemoryStore

_QAPP = QApplication.instance() or QApplication([])


class _Bus:
    def emit(self, *a, **k):
        return None


def _hub(tmp: Path) -> CognitionHub:
    store = MemoryStore(tmp / "mem.db")
    engine = MemoryEngine(_Bus(), store)
    from furina.relationship.engine import RelationshipEngine
    return CognitionHub(tmp / "cog.db", memory_engine=engine,
                        relationship_engine=RelationshipEngine())


def _active(hub, category=None):
    return hub.user_model.query_active(limit=100, category=category)


# ================================================================ R1/R2：双偏好 + 实体级 supersede
def test_r1_two_preferences_coexist(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢陈奕迅")
    hub.apply_user_message("我喜欢咖啡")
    prefs = _active(hub, "PREFERENCE")
    vals = {str(i.value) for i in prefs}
    assert len(prefs) == 2, f"两个偏好必须独立 ACTIVE: {vals}"
    assert "陈奕迅" in vals and "咖啡" in vals
    keys = {i.key for i in prefs}
    assert "preference:陈奕迅" in keys and "preference:咖啡" in keys, \
        "entity-specific key（非全局 preference）"
    hub.close()


def test_r2_targeted_preference_supersession(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢陈奕迅")
    hub.apply_user_message("我喜欢咖啡")
    hub.apply_user_message("其实最近不怎么听陈奕迅了")
    prefs = _active(hub, "PREFERENCE")
    vals = {str(i.value) for i in prefs}
    assert "咖啡" in vals and "陈奕迅" not in vals, \
        "只 supersede 陈奕迅；咖啡保持 ACTIVE"
    rows = hub._db._conn.execute(
        "SELECT key,status FROM user_model_items WHERE category='PREFERENCE'").fetchall()
    st = {r[0]: r[1] for r in rows}
    assert st.get("preference:陈奕迅") == "superseded", "陈奕迅 → SUPERSEDED"
    assert st.get("preference:咖啡") == "active", "咖啡不受影响"
    hub.close()


# ================================================================ R3/R4/R5：双计划 + 定向/模糊完成
def test_r3_two_plans_coexist(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我今天准备完成桌宠测试")
    hub.apply_user_message("我还要写比赛报告")
    plans = _active(hub, "PLAN")
    keys = {i.key for i in plans}
    assert len(plans) == 2, f"两个计划必须独立 ACTIVE: {keys}"
    assert "plan:桌宠测试" in keys and "plan:比赛报告" in keys
    hub.close()


def test_r4_targeted_plan_completion(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我今天准备完成桌宠测试")
    hub.apply_user_message("我还要写比赛报告")
    r = hub.apply_user_message("桌宠测试做完了")
    assert r["plans_completed"], "必须关联到桌宠测试 plan"
    plans = _active(hub, "PLAN")
    keys = {i.key for i in plans}
    assert "plan:比赛报告" in keys and "plan:桌宠测试" not in keys, \
        "只完成桌宠测试；比赛报告保持 ACTIVE"
    hub.close()


def test_r5_ambiguous_completion_completes_none(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我今天准备完成桌宠测试")
    hub.apply_user_message("我还要写比赛报告")
    r = hub.apply_user_message("我终于做完了")
    assert r["plans_completed"] == [], "模糊完成不得自动完成任何 plan（Correctness > 自动化）"
    assert len(_active(hub, "PLAN")) == 2, "两个 plan 都必须仍 ACTIVE"
    hub.close()


# ================================================================ N3/N4 快捷确认
def test_n3_unrelated_preferences_do_not_supersede(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢陈奕迅")
    hub.apply_user_message("我喜欢咖啡")
    assert len(_active(hub, "PREFERENCE")) == 2, "N3：无关偏好互不 supersede"
    hub.close()


# ================================================================ R6/R7/R8：production C3 provenance（真实 Furina）
@pytest.fixture()
def fapp(tmp_path):
    cfg = AppConfig(root_dir=tmp_path, zhipu_api_key="", agnes_api_key="",
                    llm=LLMProfile(api_key=""), data_dir=tmp_path)
    f = Furina(cfg)
    f._rt_dispatcher().bind_owner()
    yield f
    try:
        if f.cognition is not None:
            f.cognition.close()
    except Exception:
        pass


class _StubBrain:
    def say_with_result(self, **kw):
        return {"speech": "嗯，好。", "failure_reason": "",
                "validation_issues": [], "hard_issues": [], "soft_issues": []}


def test_r6_production_pet_memory_provenance(fapp):
    """真实互动路径：petting → C6 USER_PET → consolidation → C3（provenance 非空且可解析）。"""
    fapp._on_meaningful_interaction(
        SimpleNamespace(type=SimpleNamespace(value="petting"), count=1))
    mems = fapp.cognition.autobiography.all_memories(status=None)
    assert mems, "pet 应形成 C3"
    m = mems[0]
    assert m.source_event_ids, f"pet C3 必须带 provenance: {m.source_event_ids}"
    evs = fapp.cognition.events.query_recent(100)
    for eid in m.source_event_ids:
        assert any(e.event_id == eid and e.event_type == "USER_PET" for e in evs), \
            f"pet C3 source {eid} 必须解析到 C6 USER_PET"
    fapp.cognition.close()


def test_r7_production_feed_memory_provenance(fapp):
    """真实喂食路径：feed → C6 USER_FEED → consolidation → 可选 C3（provenance 非空）。"""
    fapp.dialogue_brain = _StubBrain()
    fapp.submit_feed("蛋糕")
    mems = fapp.cognition.autobiography.all_memories(status=None)
    feed_mems = [m for m in mems if m.event_type == "user_feed"]
    assert feed_mems, "feed 应形成 C3（带 provenance）"
    m = feed_mems[0]
    assert m.source_event_ids and "用户喂了我" in m.content
    evs = fapp.cognition.events.query_by_type("USER_FEED")
    assert any(e.event_id in m.source_event_ids for e in evs), \
        "feed C3 必须解析到 C6 USER_FEED"
    fapp.cognition.close()


def test_r8_production_verified_agent_memory_provenance(fapp, tmp_path):
    """真实 Agent 完成：C7 COMPLETED_VERIFIED + C6 AGENT_COMPLETED → C3 引用精确事件。"""
    res = fapp.agent.execute("创建 hello.md，内容 Hello Furina", {"path": str(tmp_path)})
    assert res["status"] == "completed"
    fapp._persist_agent_task(res["task_record"])     # owner persist → C6 AGENT_COMPLETED + C3
    mems = fapp.cognition.autobiography.all_memories(status=None)
    agent_mems = [m for m in mems if m.event_type == "help_success"]
    assert agent_mems, "verified Agent 应形成有意义 C3"
    m = agent_mems[0]
    evs = fapp.cognition.events.query_by_type("AGENT_COMPLETED")
    assert any(e.event_id in m.source_event_ids for e in evs), \
        "C3 必须引用精确 AGENT_COMPLETED C6 事件"
    # 无第二个 provenance-less App worker success memory
    plain = [x for x in mems if not x.source_event_ids]
    assert not any("帮用户" in x.content for x in plain), "不得有 provenance-less 成功记忆"
    fapp.cognition.close()


def test_r9_failed_agent_no_success_memory(fapp, tmp_path):
    res = fapp.agent.execute("打开一个不存在的XYZABC软件", {})
    assert res["status"] == "failed"
    fapp._persist_agent_task(res["task_record"])
    mems = fapp.cognition.autobiography.all_memories(status=None)
    for m in mems:
        assert "成功" not in m.content and "我完成了" not in m.content, \
            f"Failed Agent 不得形成成功记忆: {m.content}"
    fapp.cognition.close()


# ================================================================ R10：C5 milestone provenance
def test_r10_milestone_source_event_persisted(tmp_path):
    hub = _hub(tmp_path)
    ev = hub.record_event("RELATIONSHIP_MILESTONE",
                          payload={"type": "FIRST_MAJOR_TASK_COMPLETED", "note": "第一次重要任务"},
                          source="agent", task_id="t9", importance=0.6)
    ms = hub.relationship.milestones()
    assert ms and ms[0]["milestone_type"] == "FIRST_MAJOR_TASK_COMPLETED"
    assert ms[0]["source_event_id"] == ev.event_id, "milestone → source_event_id 必须持久化"
    # milestone → source_event_id → 精确 C6 event 可解析
    evs = hub.events.query_by_type("RELATIONSHIP_MILESTONE")
    assert any(e.event_id == ms[0]["source_event_id"] for e in evs)
    hub.close()


def test_n8_milestone_without_source_not_evidence_backed(tmp_path):
    hub = _hub(tmp_path)
    hub.relationship.record_milestone("REPEATED_NEGATIVE_INTERACTION", "无证据", "")
    ms = hub.relationship.milestones()
    assert ms[0]["source_event_id"] == "", "空 source 的 milestone 不得声称 evidence-backed"
    hub.close()


# ================================================================ R11/R12：C2 mandatory source 解析 + used-source
def test_r11_mandatory_source_resolution():
    hub = _hub(Path(__import__("tempfile").mkdtemp()) / "c.db")
    m = hub.canon_history.metrics()
    assert m["canon_span_status"] == "MANDATORY_SPAN_SOURCE_COMPLETE", m["canon_span_status"]
    assert m["dangling_source_ids"] == [], f"无 dangling: {m['dangling_source_ids']}"
    assert m["mandatory_stages_with_used_source"] == 20
    assert m["partial_periods"] == [], "mandatory 阶段不得再有 PARTIAL gap"
    hub.close()


def test_r12_unused_sources_not_counted():
    hub = _hub(Path(__import__("tempfile").mkdtemp()) / "c.db")
    m = hub.canon_history.metrics()
    # 实际使用的来源 = TIER 0（SRC-001..006）；未使用的 cross-check 来源不计
    assert set(m["sources_used"]) == {"SRC-001", "SRC-002", "SRC-003", "SRC-004", "SRC-005", "SRC-006"}
    assert "SRC-007" not in m["sources_used"] and "SRC-008" not in m["sources_used"] and \
        "SRC-009" not in m["sources_used"], "未使用来源不得计入完整性（N9）"
    # 每个 episode 至少引用一个 USED 来源
    for ep in hub.canon_history.all_episodes():
        assert any(s in m["sources_used"] for s in (ep.source_ids or [])), \
            f"{ep.episode_id} 必须引用实际使用来源"
    hub.close()


def test_n10_no_label_only_completeness():
    """完整性由 metrics 从实际 source 解析计算，不是改状态字符串。"""
    hub = _hub(Path(__import__("tempfile").mkdtemp()) / "c.db")
    m = hub.canon_history.metrics()
    assert m["canon_span_status"] == "MANDATORY_SPAN_SOURCE_COMPLETE"
    assert m["mandatory_stages_with_used_source"] == 20
    assert not any(e.canon_status == "partial" for e in hub.canon_history.all_episodes()), \
        "不得靠改 label 假装完整——这里 20 阶段确实全部 evidence-backed"
    hub.close()


# ================================================================ R13：Canon 文件 checksum
def test_r13_canon_checksum_unchanged(tmp_path):
    import json
    repo = Path(__file__).resolve().parents[2]
    hp = repo / "data/canon/furina_life_history.json"
    before = hashlib.sha256(hp.read_bytes()).hexdigest()
    hub = _hub(tmp_path)
    for _ in range(2):
        hub.canon_history.all_episodes()
        hub.assemble(query="如果没人关注你了怎么办")
    hub.close()
    assert hashlib.sha256(hp.read_bytes()).hexdigest() == before


# ================================================================ R14/R15：restart 幂等 + bounded context 保持绿
def test_r14_restart_idempotency_kept(tmp_path):
    h1 = _hub(tmp_path)
    h1.events.append(event_type="USER_PET", payload={"strong": True}, importance=0.6)
    h1.close()
    h2 = _hub(tmp_path)
    r = h2.process_pending(batch=10)
    assert r["processed"] == 1 and h2.autobiography.count() == 1
    h2.close()
    h3 = _hub(tmp_path)
    r3 = h3.process_pending(batch=10)
    assert r3["processed"] == 0 and h3.autobiography.count() == 1, "restart duplicate=0"
    h3.close()


def test_r15_bounded_context_kept(tmp_path):
    hub = _hub(tmp_path)
    for i in range(60):
        hub.events.append(event_type="USER_PET", payload={"i": i})
        hub.user_model.upsert_item(category="FACT", key=f"k{i}", value=f"v{i}", confidence=0.5)
    ctx = hub.assemble(query="随便聊聊")
    assert ctx.is_bounded()
    hub.close()
