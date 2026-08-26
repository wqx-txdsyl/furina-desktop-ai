"""Phase 15 Reviewer-Locked Integration Tests（tests/agent/integration/，真实 Furina production path）。

全部使用真实 Furina(cfg) + CognitionHub + MemoryEngine + RelationshipEngine + EventTimeline +
UserModelStore + ContextAssembler + real _freeze_direct_snapshot；LLM 仅 stub（环境无 key）。
禁止 FakeCognition / FakeMemory / FixedContextAssembler / 直接 INSERT 当验收。
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest import mock

import pytest
from PySide6.QtWidgets import QApplication

from furina.app import Furina
from furina.config import AppConfig, LLMProfile

_QAPP = QApplication.instance() or QApplication([])


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


def _say(fapp, text):
    fapp.dialogue_brain = _StubBrain()
    fapp.submit_user_message(text)
    q = fapp._direct_dialogue_queue()
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        fapp._rt_dispatcher().drain()
        if q.wait_idle(0.05):
            break
        time.sleep(0.01)
    fapp._rt_dispatcher().drain()


# ================================================================ Reviewer 51：preference lifecycle（真实 production）
def test_15_reviewer_51_preference_lifecycle_production(fapp):
    _say(fapp, "我喜欢陈奕迅")
    prefs = fapp.cognition.user_model.query_active(limit=20, category="PREFERENCE")
    assert len(prefs) == 1 and "陈奕迅" in str(prefs[0].value)
    old_id = prefs[0].item_id
    assert prefs[0].source_event_id
    # 用户改变（真实 turn）
    _say(fapp, "其实最近不怎么听陈奕迅了")
    active = fapp.cognition.user_model.query_active(limit=20, category="PREFERENCE")
    assert old_id not in [i.item_id for i in active], "旧偏好不得继续 active（correction wins）"
    row = fapp.cognition._db._conn.execute(
        "SELECT status FROM user_model_items WHERE item_id=?", (old_id,)).fetchone()
    assert row and row[0] == "superseded", "旧偏好必须 SUPERSEDED（历史保留）"


# ================================================================ Reviewer 61：current truth > memory
def test_15_reviewer_61_current_truth_beats_memory(fapp):
    # 先制造 memory：真实活动执行（read）→ recent
    fapp._on_execute(type("R", (), {"action": "read", "source": "mind", "payload": {},
                                    "reason": "r", "priority": 0.5})())
    # current = play（recent 是 read）
    fapp._on_execute(type("R", (), {"action": "play", "source": "mind", "payload": {},
                                    "reason": "r", "priority": 0.5})())
    snap = fapp._freeze_direct_snapshot("你现在在干嘛？")
    # recovery 走 CURRENT FACT：play（不回答 read）
    r = fapp._grounded_fact_recovery(snap, {"hard_issues": ["ungrounded_activity"],
                                            "soft_issues": []})
    assert "玩" in r and "看" not in r, f"current truth 必须赢过旧 memory: {r}"


# ================================================================ Reviewer 62：current turn > C4
def test_15_reviewer_62_current_turn_beats_c4(fapp):
    _say(fapp, "我喜欢喝咖啡")
    assert any("咖啡" in str(i.value) for i in
               fapp.cognition.user_model.query_active(limit=20, category="PREFERENCE"))
    _say(fapp, "我现在不喝咖啡了")
    snap = fapp._freeze_direct_snapshot("在吗")
    d = dict(snap.cognitive_context)
    um = d.get("user_model_items") or []
    assert not any("咖啡" in str(i.get("value", "")) for i in um), \
        "当前 explicit turn 后，coffee 不得作为 active 当前事实进入 snapshot"


# ================================================================ Reviewer 20：context bounded under volume
def test_15_reviewer_20_context_bounded_under_volume(fapp, tmp_path):
    hub = fapp.cognition
    for i in range(100):
        hub.events.append(event_type="USER_PET", payload={"i": i})
        hub.user_model.upsert_item(category="FACT", key=f"k{i}", value=f"v{i}", confidence=0.5)
        hub.agent_history.create_task(original_request=f"task{i}", goal=f"goal{i}")
    snap = fapp._freeze_direct_snapshot("随便聊聊")
    d = dict(snap.cognitive_context)
    assert len(d["user_model_items"]) <= 3
    assert len(d["recent_events"]) <= 3
    assert len(d["relevant_agent_tasks"]) <= 2
    assert len(d["autobiographical_memories"]) <= 3
    assert len(d["canon"]["episodes"]) <= 2


# ================================================================ Scenario A：偏好演化跨 restart
def test_15_scenario_a_preference_evolution_across_restart(fapp, tmp_path):
    _say(fapp, "我喜欢陈奕迅")
    fapp.cognition.close()
    # restart：同一 DB 重新打开（真实持久化）
    cfg = AppConfig(root_dir=tmp_path, zhipu_api_key="", agnes_api_key="",
                    llm=LLMProfile(api_key=""), data_dir=tmp_path)
    f2 = Furina(cfg)
    f2._rt_dispatcher().bind_owner()
    _say(f2, "其实最近不怎么听陈奕迅了")
    active = f2.cognition.user_model.query_active(limit=20, category="PREFERENCE")
    assert not any("陈奕迅" in str(i.value) for i in active), \
        "跨 restart 后旧偏好不得仍 ACTIVE（historically liked + current changed）"
    # 历史仍在（superseded）
    rows = f2.cognition._db._conn.execute(
        "SELECT status FROM user_model_items WHERE category='PREFERENCE'").fetchall()
    assert any(r[0] == "superseded" for r in rows), "历史必须保留"
    f2.cognition.close()


# ================================================================ Windows integration：persistent DB + cursor + index
def test_15_windows_persistent_loop_and_index(tmp_path):
    """Windows 真实 temp：C3/C4/cursor 跨 restart 存活；index delete/rebuild；无 duplicate。"""
    from furina.cognition import CognitionHub
    from furina.memory import MemoryEngine, MemoryStore
    db = tmp_path / "w.db"
    mem_db = tmp_path / "wmem.db"

    def _mk():
        store = MemoryStore(mem_db)
        return CognitionHub(db, memory_engine=MemoryEngine(_Bus(), store))
    h1 = _mk()
    h1.events.append(event_type="AGENT_COMPLETED", payload={"goal": "创建 w.md"},
                     task_id="tw", importance=0.6)
    h1.apply_user_message("我喜欢陈奕迅")
    h1.process_pending(batch=10)
    h1.build_index()
    assert h1.autobiography.count() == 1
    assert len(h1.user_model.query_active(limit=20)) >= 1
    h1.close()
    # restart
    h2 = _mk()
    assert h2.autobiography.count() == 1, "C3 跨 restart 存活"
    assert len(h2.user_model.query_active(limit=20)) >= 1, "C4 跨 restart 存活"
    r = h2.process_pending(batch=10)
    assert r["processed"] == 0, "cursor 跨 restart 存活 → 无 duplicate"
    # index delete → source 不动；rebuild → 检索恢复
    before = (h2.events.count(), h2.autobiography.count(), h2.user_model.count())
    h2.delete_index()
    assert not h2.index.exists()
    assert (h2.events.count(), h2.autobiography.count(), h2.user_model.count()) == before, \
        "删除 derived index 不得碰 source"
    n = h2.rebuild_index()
    assert n > 0 and h2.lookup_index("陈奕迅"), "rebuild 后检索恢复"
    h2.close()


class _Bus:
    def emit(self, *a, **k):
        return None
