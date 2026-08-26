"""Phase 15D — C4 User Model Evolution 测试（tests/cognition/）。

覆盖：evidence-first、explicit correction wins（supersede）、PLAN 生命周期（COMPLETED 关联）、
temporal scope（日期不确定不编造）、communication preference 进入 dialogue context、
'这首歌不错' 不形成 lifelong、当前轮 > 旧 UserModel。
"""
from __future__ import annotations

import tempfile
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


def _active(hub, category=None):
    return hub.user_model.query_active(limit=100, category=category)


# ================================================================ Reviewer 51：preference lifecycle
def test_preference_lifecycle_supersede_after_change(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢陈奕迅")
    prefs = _active(hub, "PREFERENCE")
    assert len(prefs) == 1 and "陈奕迅" in str(prefs[0].value)
    old_id = prefs[0].item_id
    assert prefs[0].source_event_id, "evidence-first：必须带 source_event_id"
    # 用户改变 → 旧 item superseded；current context 不再把 old 当 active
    hub.apply_user_message("其实最近不怎么听陈奕迅了")
    assert _active(hub, "PREFERENCE") == [], "旧偏好不得继续 active"
    all_items = hub.user_model.query_active(limit=100)  # active 全量
    assert old_id not in [i.item_id for i in all_items]
    # 历史保留（superseded 记录仍在）
    conn = hub._db._conn
    rows = conn.execute("SELECT status FROM user_model_items WHERE item_id=?",
                        (old_id,)).fetchone()
    assert rows and rows[0] == "superseded", "旧偏好必须 SUPERSEDED（历史保留）"
    hub.close()


# ================================================================ Reviewer 12 / G5：current turn > old C4
def test_current_turn_beats_old_user_model(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢喝咖啡")
    assert len(_active(hub, "PREFERENCE")) == 1
    hub.apply_user_message("我现在不喝咖啡了")
    # 当前明确声明后：coffee 不再作为 active 当前事实
    assert not any("咖啡" in str(i.value) for i in _active(hub, "PREFERENCE")), \
        "current explicit turn 必须赢过旧 C4"
    hub.close()


# ================================================================ Reviewer 28：PLAN 生命周期
def test_plan_lifecycle_active_then_completed(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我今天准备完成桌宠测试")
    plans = _active(hub, "PLAN")
    assert plans and plans[0].status == "active"
    # 完成后：'终于做完了' 关联 ACTIVE PLAN → COMPLETED（不新增互不关联 plan）
    r = hub.apply_user_message("我终于做完桌宠测试了")
    assert r["plans_completed"], "完成声明必须关联到既有 plan"
    plans_after = _active(hub, "PLAN")
    assert plans_after == [], "COMPLETED plan 不得继续 active"
    rows = hub._db._conn.execute(
        "SELECT status FROM user_model_items WHERE category='PLAN' AND key LIKE 'plan:%'").fetchall()
    assert any(r0[0] == "completed" for r0 in rows), "plan 必须 COMPLETED"
    hub.close()


# ================================================================ Reviewer 27：temporal scope
def test_temporal_uncertain_no_fabricated_dates(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我明天要交报告")
    # PLAN 带 temporal scope：valid_from 已设；日期不确定 → temporal_uncertain 语义
    plans = _active(hub, "PLAN")
    assert plans, "明天要交报告 → PLAN"
    # 不编造具体截止日期（valid_to 保留 0 = 未确定，temporal_uncertain 允许 1）
    conn = hub._db._conn
    row = conn.execute("SELECT valid_to, temporal_uncertain FROM user_model_items "
                       "WHERE item_id=?", (plans[0].item_id,)).fetchone()
    assert row[0] == 0.0, "不得编造截止日期（valid_to 未确定）"
    hub.close()


# ================================================================ Reviewer 52 / §29：communication preference → dialogue
def test_communication_preference_reaches_dialogue_context(tmp_path):
    """'别一直给我讲大道理' → C4 COMMUNICATION_PREFERENCE 且进入真实 snapshot + prompt。"""
    hub = _hub(tmp_path)
    hub.apply_user_message("别一直给我讲大道理")
    cps = _active(hub, "COMMUNICATION_PREFERENCE")
    assert cps, "COMMUNICATION_PREFERENCE 必须形成"
    ctx = hub.assemble(query="在吗")
    assert any(i.category == "COMMUNICATION_PREFERENCE" for i in ctx.user_model_items), \
        "assembler 必须检索到 communication preference"
    # prompt 注入路径（真实 _dialogue_prompt_v2 消费 cognitive_context）
    from furina.dialogue_brain import _dialogue_prompt_v2
    class _A:
        def to_prompt(self):
            return {"mode": "CASUAL", "secondary_mode": "", "dialogue_act": "COMMENT", "strategy": ""}
    d = {"user_model_items": [{"category": i.category, "value": i.value,
                               "confidence": i.confidence, "key": i.key}
                              for i in ctx.user_model_items],
         "recent_events": [], "relevant_agent_tasks": [],
         "canon": {"activation": 0, "episodes": []},
         "autobiographical_memories": [], "relationship": {}}
    p = _dialogue_prompt_v2(_A(), intent="talk", emotion="calm", user_text="在吗",
                            context="", memories=None, world=None, examples=[], person="",
                            activity="idle", cognitive_context=d)
    assert "大道理" in p, "Dialogue prompt 必须收到 COMMUNICATION_PREFERENCE"
    hub.close()


# ================================================================ 禁止幻觉（N2 / §13）
def test_transient_reaction_no_lifelong(tmp_path):
    hub = _hub(tmp_path)
    r = hub.apply_user_message("这首歌不错")
    assert r["declarations"] == [], "'这首歌不错' 不得形成 C4 item"
    assert _active(hub) == [], "不得创建 lifelong favorite"


def test_canon_unchanged_by_user_claim(tmp_path):
    """N1：'你就是芙卡洛斯' → C1/C2 不变（canon runtime immutable）。"""
    hub = _hub(tmp_path)
    before_eps = [(e.episode_id, len(e.furina_knew), len(e.furina_did_not_know))
                  for e in hub.canon_history.all_episodes()]
    hub.apply_user_message("你就是芙卡洛斯本人")
    after_eps = [(e.episode_id, len(e.furina_knew), len(e.furina_did_not_know))
                 for e in hub.canon_history.all_episodes()]
    assert before_eps == after_eps, "用户说法不得修改 Canon"
    hub.close()


# ================================================================ evidence chain（Reviewer 18）
def test_c4_evidence_chain_resolves(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我今天准备完成桌宠测试")
    plans = _active(hub, "PLAN")
    it = plans[0]
    evs = hub.events.query_by_type("USER_PLAN_DECLARED")
    assert any(e.event_id == it.source_event_id for e in evs), "C4 source_event_id → C6 可解析"
    assert "桌宠" in it.source_text_excerpt, "excerpt 必须保留"
    hub.close()


# ================================================================ Scenario D：reality correction
def test_reality_correction_updates_plan(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("今天要测试")
    assert _active(hub, "PLAN")
    hub.apply_user_message("已经测试完了")
    assert _active(hub, "PLAN") == [], "完成后不再提醒（plan completed）"
    hub.close()
