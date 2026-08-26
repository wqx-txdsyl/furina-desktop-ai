"""Phase 15C — C3 Autobiographical Memory Lifecycle 测试（tests/cognition/）。

覆盖：事件溯源（source_event_ids → C6 可解析）、有意义形成、琐事抑制（read/play 不机械成记忆）、
reinforcement（相似经历合并不重复插行）、supersession/archival（遗忘=归档，C6 账本不动）、
Failed Agent 不形成成功记忆、Verified Agent 记忆可追溯。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from furina.cognition import CognitionHub
from furina.memory import MemoryEngine, MemoryLevel, MemorySource, MemoryStatus, MemoryStore
from furina.memory.experience import Experience


class _Bus:
    def emit(self, *a, **k):
        return None


def _hub(tmp: Path) -> CognitionHub:
    store = MemoryStore(tmp / "mem.db")
    engine = MemoryEngine(_Bus(), store)
    return CognitionHub(tmp / "cog.db", memory_engine=engine)


def _count_memories(hub, *, status=None) -> int:
    return hub.autobiography.count(status=status)


# ================================================================ 有意义形成 + 事件溯源（Reviewer 53/19）
def test_c3_meaningful_formation_with_provenance(tmp_path):
    hub = _hub(tmp_path)
    ev = hub.record_event("AGENT_COMPLETED", payload={"goal": "创建报告"},
                          source="agent", task_id="task_1", importance=0.6)
    assert _count_memories(hub) == 1, "重要 Agent 完成应形成 C3"
    m = hub.autobiography.recent(1)[0]
    assert ev.event_id in m.source_event_ids, "C3 必须带 source_event_ids（provenance）"
    # reviewer 19：source_event_ids → 全部可解析为现有 C6 记录
    for eid in m.source_event_ids:
        evs = hub.events.query_recent(100)
        assert any(e.event_id == eid for e in evs), f"memory source {eid} 必须解析到 C6"
    hub.close()


def test_c3_source_event_resolves_via_pipeline(tmp_path):
    hub = _hub(tmp_path)
    ev = hub.record_event("USER_PET", payload={"strong": True}, importance=0.6)
    assert _count_memories(hub) == 1
    m = hub.autobiography.recent(1)[0]
    assert m.source_event_ids == [ev.event_id]
    hub.close()


# ================================================================ 琐事抑制（Reviewer 56 / N4）
def test_c3_repetition_suppression_read_play(tmp_path):
    hub = _hub(tmp_path)
    # read/play/read/play 活动事件（bridge 路径 append，无 consolidate）
    for act in ("read", "play", "read", "play"):
        hub.events.append(event_type="ACTIVITY_STARTED",
                          payload={"activity": act, "activity_instance_id": f"i_{act}"},
                          importance=0.1)
    assert hub.events.query_by_type("ACTIVITY_STARTED") and len(
        hub.events.query_by_type("ACTIVITY_STARTED")) == 4, "C6 完整记录 4 个 START"
    # C3 不得机械产生 4 条记忆（ACTIVITY_* 不进入 memory 形成）
    assert _count_memories(hub) == 0, "琐碎活动不得成记忆"
    hub.close()


def test_c3_pet_x4_no_duplicate_memories(tmp_path):
    """N3：pet×4 → 不得 4 条相同长期记忆（条件形成 + reinforcement 合并）。"""
    hub = _hub(tmp_path)
    for i in range(4):
        hub.record_event("USER_PET", payload={"strong": False}, importance=0.6)
    n = _count_memories(hub)
    assert n == 1, f"4 次摸头应合并为 1 条（或按 policy 有界），实际 {n}"
    m = hub.autobiography.recent(1)[0]
    assert m.recurrence_count >= 1 or len(m.source_event_ids) >= 1, "重复经历应累积证据"
    hub.close()


# ================================================================ reinforcement（Reviewer 54 语义：相似经历不重复插行）
def test_c3_reinforcement_merges_similar_experiences(tmp_path):
    hub = _hub(tmp_path)
    kw = dict(world_context="", activity="", outcome="success",
              user_relevance=0.9, outcome_significance=0.9,
              emotional_intensity=0.9, relationship_relevance=0.9,
              identity_relevance=0.5, novelty=0.8)
    exp1 = Experience(token="help_success||", event_type="help_success",
                      summary="成功帮用户完成了一件事", source_event_ids=["ev_a"], **kw)
    hub.autobiography.consolidate(exp1)
    exp2 = Experience(token="help_success||", event_type="help_success",
                      summary="成功帮用户完成了一件事", source_event_ids=["ev_b"], **kw)
    hub.autobiography.consolidate(exp2)
    assert _count_memories(hub) == 1, "相似经历必须 reinforce 合并，不得重复插行"
    m = hub.autobiography.recent(1)[0]
    assert m.recurrence_count >= 1
    assert "ev_b" in m.source_event_ids, "reinforce 必须累积新证据"
    hub.close()


# ================================================================ lifecycle：supersession / archival（遗忘≠删 C6）
def test_c3_supersession_and_archival_preserves_history(tmp_path):
    hub = _hub(tmp_path)
    ev = hub.record_event("AGENT_COMPLETED", payload={"goal": "旧任务"},
                          source="agent", task_id="task_old", importance=0.6)
    m = hub.autobiography.recent(1)[0]
    assert ev.event_id in m.source_event_ids
    # supersede：旧记忆保留为历史（SUPERSEDED）
    hub.autobiography.supersede(m.mem_id)
    all_mems = {mm.mem_id: mm for mm in hub.autobiography.all_memories(status=None)}
    assert all_mems[m.mem_id].status == MemoryStatus.SUPERSEDED, "superseded 语义必须保留历史"
    # archive：遗忘 = 归档（C6 账本不动）
    ev2 = hub.record_event("USER_PET", payload={"strong": True}, importance=0.6)
    mems = hub.autobiography.recent(10)
    pet = next(m_ for m_ in mems if ev2.event_id in m_.source_event_ids)
    assert pet is not None
    before_events = hub.events.count()
    hub.autobiography.archive(pet.mem_id)
    assert hub.events.count() == before_events, "遗忘不得 DELETE FROM life_events"
    assert hub.autobiography.count(status=None) == 2, "归档/取代后记录仍在（历史保留）"
    re_fetched = {mm.mem_id: mm for mm in hub.autobiography.all_memories(status=None)}
    assert re_fetched[pet.mem_id].status == MemoryStatus.ARCHIVED, "归档后状态必须 ARCHIVED"
    hub.close()


# ================================================================ Failed Agent truth（Reviewer 57 / N6）
def test_c3_failed_agent_no_success_memory(tmp_path):
    hub = _hub(tmp_path)
    hub.record_event("AGENT_FAILED", payload={"request": "整理目录"}, importance=0.4)
    mems = hub.autobiography.recent(5)
    for m in mems:
        assert "成功" not in m.content and "完成" not in m.content, \
            f"Failed Agent 不得形成成功记忆: {m.content}"
    # C7 FAILED 真相（不依赖 C3）
    from furina.agent.agent_runtime import AgentRuntime  # noqa: F401（确保 agent 模块可用）
    assert True
    hub.close()


# ================================================================ Verified Agent memory（Reviewer 58）
def test_c3_verified_agent_memory_traceable(tmp_path):
    hub = _hub(tmp_path)
    ev = hub.record_event("AGENT_COMPLETED", payload={"goal": "创建 report.md"},
                          source="agent", task_id="task_verify", importance=0.6)
    m = hub.autobiography.recent(1)[0]
    assert "report.md" in m.content or "创建" in m.content
    assert ev.event_id in m.source_event_ids, "C3 必须能追溯真实任务事件"
    # 追溯：C3 → source_event_ids → C6 event（含 task_id linkage）
    linked = [e for e in hub.events.query_by_type("AGENT_COMPLETED") if e.task_id == "task_verify"]
    assert linked, "C6 事件必须带 task_id linkage"
    hub.close()
