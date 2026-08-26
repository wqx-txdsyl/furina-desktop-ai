"""Phase 15F — Persistent Cognitive Loop + Restart 测试（tests/cognition/）。

覆盖：C6 append → pending → process_pending（InterpretationEngine → owner apply → C3/C4）；
processing cursor 持久化；restart 幂等（exactly-once / duplicate=0）；shutdown 不丢未处理事件；
重启后记忆仍可检索（Scenario B）。
"""
from __future__ import annotations

from pathlib import Path

from furina.cognition import CognitionHub
from furina.memory import MemoryEngine, MemoryStore


class _Bus:
    def emit(self, *a, **k):
        return None


def _hub(tmp: Path) -> CognitionHub:
    store = MemoryStore(tmp / "mem.db")
    engine = MemoryEngine(_Bus(), store)
    return CognitionHub(tmp / "cog.db", memory_engine=engine)


# ================================================================ Reviewer 54/55：restart 幂等
def test_restart_idempotent_consolidation(tmp_path):
    """event 持久化 → shutdown → reopen → consolidate once → reopen again → duplicate=0。"""
    hub1 = _hub(tmp_path)
    # 走 pipeline 路径（events.append 未处理；bridge 语义）
    hub1.events.append(event_type="USER_PET", payload={"strong": True}, importance=0.6)
    hub1.close()
    # Run B：reopen → process_pending → C3 exactly once
    hub2 = _hub(tmp_path)
    assert hub2.processing_status()["pending"] >= 1, "重启后未处理事件仍在（不丢）"
    r1 = hub2.process_pending(batch=10)
    assert r1["processed"] == 1 and r1["memories"] == 1, r1
    assert hub2.autobiography.count() == 1
    hub2.close()
    # Run C：reopen again → duplicate = 0
    hub3 = _hub(tmp_path)
    r2 = hub3.process_pending(batch=10)
    assert r2["processed"] == 0 and r2["memories"] == 0, f"重启后 duplicate=0: {r2}"
    assert hub3.autobiography.count() == 1, "C3 不得重复"
    assert hub3.processing_status()["pending"] == 0, "全部事件已处理"
    hub3.close()


def test_same_event_replayed_three_times_once(tmp_path):
    """同一未处理事件重放 3 次 process_pending → C3 count increase = 1。"""
    hub = _hub(tmp_path)
    ev = hub.events.append(event_type="AGENT_COMPLETED", payload={"goal": "创建文档"},
                           task_id="t1", importance=0.6)
    for _ in range(3):
        r = hub.process_pending(batch=10)
    assert hub.autobiography.count() == 1, f"重放 3 次只能形成 1 条: {hub.autobiography.count()}"
    assert hub.processing_status()["pending"] == 0
    m = hub.autobiography.recent(1)[0]
    assert ev.event_id in m.source_event_ids
    hub.close()


def test_shutdown_does_not_drop_pending(tmp_path):
    """append 后立即 shutdown → 未处理事件不丢；reopen 后仍可处理。"""
    hub1 = _hub(tmp_path)
    hub1.events.append(event_type="USER_PET", payload={"strong": True}, importance=0.6)
    hub1.close()                       # 未 process 就 shutdown
    hub2 = _hub(tmp_path)
    assert hub2.processing_status()["pending"] >= 1
    r = hub2.process_pending(batch=10)
    assert r["processed"] == 1 and hub2.autobiography.count() == 1
    hub2.close()


# ================================================================ 生产管线：AGENT_COMPLETED → C3 可追溯
def test_pipeline_agent_completed_memory_with_provenance(tmp_path):
    hub = _hub(tmp_path)
    ev = hub.events.append(event_type="AGENT_COMPLETED",
                           payload={"goal": "创建 report.md"}, task_id="task_x", importance=0.6)
    hub.process_pending(batch=10)
    assert hub.autobiography.count() == 1
    m = hub.autobiography.recent(1)[0]
    assert ev.event_id in m.source_event_ids, "管线形成记忆必须可追溯"
    assert "report.md" in m.content
    hub.close()


# ================================================================ Scenario B：连续共同经历跨 restart 检索
def test_scenario_b_memory_survives_restart_and_retrieves(tmp_path):
    """用户声明任务 + Agent COMPLETED → C6 → C3 有意义记忆 → restart → 对话可检索。"""
    hub1 = _hub(tmp_path)
    hub1.apply_user_message("我今天准备完成桌宠测试")     # C4 PLAN（direct path，marked processed）
    hub1.events.append(event_type="AGENT_COMPLETED",
                       payload={"goal": "完成桌宠测试"}, task_id="task_b", importance=0.6)
    hub1.process_pending(batch=10)
    assert hub1.autobiography.count() == 1
    hub1.close()
    # restart：不依赖 recent dialogue history
    hub2 = _hub(tmp_path)
    ctx = hub2.assemble(query="桌宠测试")
    assert any("桌宠" in str(x) for x in ctx.autobiographical_memories), \
        "重启后 C3 记忆必须可检索（不是靠最近对话历史）"
    hub2.close()


# ================================================================ 处理进度持久化
def test_processing_cursor_persists_across_restart(tmp_path):
    hub1 = _hub(tmp_path)
    hub1.events.append(event_type="USER_PET", payload={"strong": True}, importance=0.6)
    hub1.process_pending(batch=10)
    s1 = hub1.processing_status()
    hub1.close()
    hub2 = _hub(tmp_path)
    s2 = hub2.processing_status()
    assert s2["processed"] >= s1["processed"], "cursor/log 必须跨 restart 持久"
    assert s2["pending"] == 0, "已处理事件重启后不得回到 pending"
    hub2.close()
