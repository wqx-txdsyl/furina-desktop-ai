"""Phase 14 Final Residual R7-FC / R10-FC — reviewer-locked fail-closed tests。

Counterexamples（brief §10）：
  G — 非精确 act episode 引用缺失/未注册 evidence 可 false-green
      -> R7-FC-T1/T2（全局 evidence 引用完整性层；与精确单幕归因层分离）
  H — canonical USER_MESSAGE persistence 失败后 C4 lifecycle mutation 仍然发生
      -> R10-FC-T1/T2（App 路径 A/B 分流 + hub ``require_source_event`` 门，
         无 orphan transition / 无 supersede / 无 plan complete；对话继续）
  I — EventBridge append 失败把 _seen 毒化、静默吞掉后续合法重试
      -> R10-FC-T3（append 成功后才 mark seen）
"""
from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from furina.cognition import CognitionHub
from furina.cognition.bridge import EventBridge
from furina.memory import MemoryEngine, MemoryStore
from furina.relationship.engine import RelationshipEngine

_REPO = Path(__file__).resolve().parents[2]
_REAL_REGISTRY = _REPO / "data/canon/furina_evidence_units.json"
_REAL_SOURCES = _REPO / "data/canon/furina_life_sources.json"

_QAPP = QApplication.instance() or QApplication([])


class _Bus:
    def emit(self, *a, **k):
        return None


def _hub(tmp_path) -> CognitionHub:
    store = MemoryStore(tmp_path / "mem.db")
    engine = MemoryEngine(_Bus(), store)
    return CognitionHub(tmp_path / "cog.db", memory_engine=engine,
                        relationship_engine=RelationshipEngine())


def _real_furina(tmp_path):
    """真实 Furina + 真实 Scheduler（launch() 同款装配），走真实生产 submit 入口。"""
    from furina.app import Furina
    from furina.config import AppConfig, LLMProfile
    from furina.runtime.scheduler import Scheduler
    cfg = AppConfig(root_dir=tmp_path, zhipu_api_key="", agnes_api_key="",
                    llm=LLMProfile(api_key=""), data_dir=tmp_path)
    f = Furina(cfg)
    sched = Scheduler(f.bus, f.state, f.behavior, f.director, f.memory, f.world, f.wa,
                      life_brain=f.life_brain, dialogue_brain=f.dialogue_brain,
                      emotion_engine=f.emotion, motivation=f.motivation,
                      relationship_engine=f.relationship, embodiment=f.embodiment,
                      cognition=f.cognition)
    f._sched = sched
    sched.dispatcher.bind_owner()
    return f, sched


def _submit(f, text):
    f.submit_user_message(text)


def _transition_rows(f, sql, params=()):
    return f.cognition._db.query_all(sql, params)


def _hist_hub(episodes: list):
    """临时 fixture episodes 经 production reader（CanonHistoryStore）加载；
    registry/sources 使用仓库真源。"""
    from furina.cognition.stores.canon_history import CanonHistoryStore
    tmp = Path(tempfile.mkdtemp())
    hist = tmp / "hist.json"
    hist.write_text(json.dumps({"episodes": episodes}, ensure_ascii=False),
                    encoding="utf-8")
    return CanonHistoryStore(history_path=hist, sources_path=_REAL_SOURCES,
                             evidence_path=_REAL_REGISTRY)


def _fixture_hub(episode: dict):
    return _hist_hub([episode])


def _force_umsg_append_failure(f):
    """强制 canonical USER_MESSAGE append 失败（仅该类型；其余事件正常）。"""
    orig = f.cognition.events.append
    state = {"on": True}

    def patched(**kw):
        if state["on"] and kw.get("event_type") == "USER_MESSAGE":
            raise RuntimeError("forced USER_MESSAGE append failure")
        return orig(**kw)

    f.cognition.events.append = patched
    return state


# ================================================================ R7-FC — 全局 evidence 引用完整性
def test_r7_fc_t1_non_exact_act_missing_evidence_fails(tmp_path):
    """COUNTEREXAMPLE G：act=null + 有效 USED source + 未注册 evidence → 必须失败。"""
    ep = {"episode_id": "FIX_MISSING", "quest": "", "act": None,
          "evidence_ids": ["FUR-NOT-REGISTERED"],
          "source_ids": ["SRC-001"],     # 有效 USED source —— 不能挽救缺失 evidence
          "timeline_order": 1}
    m = _fixture_hub(ep).metrics()
    assert "FUR-NOT-REGISTERED" in m["unregistered_evidence_ids"], m
    assert any(c.get("reason") == "unregistered" and c["evidence"] == "FUR-NOT-REGISTERED"
               for c in m["evidence_attribution_conflicts"])
    st = m["mandatory_life_stage_source_status"]
    assert st != "SOURCE_COMPLETE" and st.startswith("GAPS:unregistered_evidence"), st
    # 结构层 legacy 指标不变（canon_span_status 不是语义完整性载体）
    assert m["canon_span_status"] == "MANDATORY_SPAN_SOURCE_COMPLETE"


def test_r7_fc_t2_span_act_missing_evidence_fails(tmp_path):
    """R7-FC-T2：act="I-V" 跨度同样受全局引用完整性约束。"""
    ep = {"episode_id": "FIX_MISSING", "quest": "Chapter IV", "act": "I-V",
          "evidence_ids": ["FUR-NOT-REGISTERED"], "source_ids": ["SRC-001"],
          "timeline_order": 1}
    m = _fixture_hub(ep).metrics()
    assert "FUR-NOT-REGISTERED" in m["unregistered_evidence_ids"], m
    st = m["mandatory_life_stage_source_status"]
    assert st != "SOURCE_COMPLETE" and st.startswith("GAPS:unregistered_evidence"), st


def test_r7_fc_t3_exact_act_semantics_preserved(tmp_path):
    """R7-FC-T3：既有精确单幕三层判定保持原样；未注册只报告一次（不重复计数）。"""
    # Act IV + CHARACTER_STORY/null-act → 不得支撑（gap），状态如实 PARTIAL
    m_char = _fixture_hub({"episode_id": "FIX_EP", "quest": "Chapter IV", "act": "IV",
                           "evidence_ids": ["FUR-052"], "source_ids": ["SRC-006"],
                           "timeline_order": 1}).metrics()
    assert any(g["episode"] == "FIX_EP"
               for g in m_char["episodes_without_exact_act_main_story_evidence"])
    assert m_char["mandatory_life_stage_source_status"].startswith("PARTIAL")

    # Act IV + MAIN_STORY/Act I → semantic conflict（归因兼容层）
    m_mis = _fixture_hub({"episode_id": "FIX_EP", "quest": "Chapter IV", "act": "IV",
                          "evidence_ids": ["FUR-006"], "source_ids": ["SRC-001"],
                          "timeline_order": 1}).metrics()
    assert any(c.get("evidence_act") == "I" for c in m_mis["evidence_attribution_conflicts"])

    # Act IV + MAIN_STORY/Act IV → 合法支撑（全局层不误伤已注册数据）
    m_ok = _fixture_hub({"episode_id": "FIX_EP", "quest": "Chapter IV", "act": "IV",
                         "evidence_ids": ["FUR-039"], "source_ids": ["SRC-001"],
                         "timeline_order": 1}).metrics()
    assert m_ok["evidence_attribution_conflicts"] == []
    assert m_ok["mandatory_life_stage_source_status"] == "SOURCE_COMPLETE"

    # 精确单幕 episode 引用未注册 evidence → 全局层恰好报告一次（不在归因层重复）
    m_miss = _fixture_hub(
        {"episode_id": "FIX_MISSING_EXACT", "quest": "Chapter IV", "act": "IV",
         "evidence_ids": ["FUR-NOT-A", "FUR-NOT-B"], "source_ids": ["SRC-001"],
         "timeline_order": 1}).metrics()
    assert sorted(m_miss["unregistered_evidence_ids"]) == ["FUR-NOT-A", "FUR-NOT-B"]
    unreg = [c for c in m_miss["evidence_attribution_conflicts"]
             if c.get("reason") == "unregistered"]
    assert len(unreg) == 2, m_miss["evidence_attribution_conflicts"]


def test_r7_fc_t4_production_metrics_remain_truthful():
    """R7-FC-T4：生产数据零缺失引用；PARTIAL 缺口必须照旧如实暴露（不许顺手洗绿）。"""
    from furina.cognition.stores.canon_history import CanonHistoryStore
    m = CanonHistoryStore().metrics()   # 默认真源 data/canon/*（测试不改生产文件）
    assert m["unregistered_evidence_ids"] == []
    assert m["evidence_attribution_conflicts"] == []
    assert m["evidence_registry_duplicates"] == []
    assert m["canon_span_status"] == "MANDATORY_SPAN_SOURCE_COMPLETE"
    assert m["main_story_act_coverage_status"] == "PARTIAL"
    assert m["missing_main_story_acts"] == ["II", "III"]
    assert m["main_story_act_coverage"] == {"I": True, "II": False, "III": False,
                                            "IV": True, "V": True}
    assert any(g["episode"] == "INNER_WORLD_REVELATION"
               for g in m["episodes_without_exact_act_main_story_evidence"])
    assert m["mandatory_life_stage_source_status"].startswith("PARTIAL")


# ================================================================ R10-FC — canonical USER_MESSAGE 失败即关闭
def test_r10_fc_t1_preference_correction_fails_closed_when_umsg_append_fails(tmp_path):
    """COUNTEREXAMPLE H：U append 失败 → 无 supersede、无 orphan T、对话照常到终态。"""
    f, _ = _real_furina(tmp_path)
    try:
        _submit(f, "我喜欢喝咖啡")                    # 正常建立 preference
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=15.0)
        row_before = f.cognition._db.query_one(
            "SELECT * FROM user_model_items WHERE category='PREFERENCE' "
            "AND status='active' LIMIT 1")
        assert row_before

        state = _force_umsg_append_failure(f)
        try:
            _submit(f, "我现在不喝咖啡了")            # correction 回合：U append 强制失败
        finally:
            state["on"] = False

        row_after = f.cognition._db.query_one(
            "SELECT * FROM user_model_items WHERE category='PREFERENCE' "
            "AND status='active' LIMIT 1")
        assert row_after and row_after["item_id"] == row_before["item_id"], \
            "旧 preference 必须保持 ACTIVE 且行身份不变"
        superseded = _transition_rows(
            f, "SELECT COUNT(*) AS c FROM user_model_items "
               "WHERE category='PREFERENCE' AND status='superseded'")
        assert superseded[0]["c"] == 0, "U 失败回合不得产生 superseded 行"
        assert f.cognition.events.query_by_type("USER_PREFERENCE_CHANGED") == [], \
            "U 失败回合不得产生 orphan transition 事件"
        # 对话本身继续：该回合到达可观察终态
        assert q.wait_idle(timeout=15.0)
        outs = [o for o in q.recent_outcomes(50)
                if (o.get("user_text") or "").startswith("我现在不喝咖啡")]
        assert outs and outs[0]["status"] in ("REPLIED", "FAILED", "CANCELLED"), outs
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_fc_t2_plan_completion_fails_closed_when_umsg_append_fails(tmp_path):
    """R10-FC-T2：plan 完成 utterance 在 U append 失败时 → plan 保持 ACTIVE。"""
    f, _ = _real_furina(tmp_path)
    try:
        _submit(f, "我今天准备完成桌宠测试")
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=15.0)
        plan = f.cognition._db.query_one(
            "SELECT * FROM user_model_items WHERE category='PLAN' "
            "AND status='active' AND key=?", ("plan:桌宠测试",))
        assert plan

        state = _force_umsg_append_failure(f)
        try:
            _submit(f, "桌宠测试做完了")
        finally:
            state["on"] = False

        still = f.cognition._db.query_one(
            "SELECT * FROM user_model_items WHERE item_id=?", (plan["item_id"],))
        assert still and still["status"] == "active", \
            "U 失败回合不得完成 plan"
        done = f.cognition._db.query_one(
            "SELECT COUNT(*) AS c FROM user_model_items WHERE category='PLAN' "
            "AND status='completed'")
        assert done["c"] == 0
        assert f.cognition.events.query_by_type("USER_PLAN_COMPLETED") == [], \
            "不得产生 orphan USER_PLAN_COMPLETED transition"
        assert q.wait_idle(timeout=15.0), "对话本身必须照常到达终态"
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_fc_t3_failed_append_does_not_poison_retry_key(tmp_path):
    """COUNTEREXAMPLE I：首记强制异常 → key 不进 _seen → 重试真正落库且仅一条。"""
    hub = _hub(Path(tempfile.mkdtemp()))
    try:
        br = EventBridge(hub)
        orig = hub.events.append
        calls = {"n": 0}

        def flaky(**kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("forced append failure")
            return orig(**kw)

        hub.events.append = flaky
        with pytest.raises(RuntimeError):
            br.record("ACTIVITY_STARTED", key="K", payload={"a": 1}, process=False)
        assert "K" not in br._seen, "失败的 append 不得把 key 留在 _seen（毒化重试）"

        ev_id = br.record("ACTIVITY_STARTED", key="K", payload={"a": 1},
                          process=False)
        assert ev_id, "重试必须成功并返回新事件 id"
        evs = hub.events.query_by_type("ACTIVITY_STARTED")
        assert len(evs) == 1 and evs[0].event_id == ev_id, \
            "重试必须恰好持久化一条 canonical 事件"
        assert "K" in br._seen
        # 成功后的 dedupe 依旧生效（exactly-once 保持）
        assert br.record("ACTIVITY_STARTED", key="K", payload={"a": 1},
                         process=False) is None
        assert len(hub.events.query_by_type("ACTIVITY_STARTED")) == 1
    finally:
        hub.close()


def test_r10_fc_t4_hub_gate_rejects_without_canonical_user_message(tmp_path):
    """R10-FC hub defense-in-depth：require_source_event=True 时无有效 U → 整体跳过。"""
    hub = _hub(Path(tempfile.mkdtemp()))
    try:
        # 孤立调用（默认 require=False）：isolated shell 行为保持不变
        hub.apply_user_message("我喜欢喝咖啡")
        row = hub._db.query_one(
            "SELECT * FROM user_model_items WHERE category='PREFERENCE' "
            "AND status='active' LIMIT 1")
        assert row

        # 生产契约（require=True）+ 无效 source id → 完全拒绝（no-op）
        r = hub.apply_user_message("我现在不喝咖啡了", turn_id=7,
                                   source_event_id="does-not-exist",
                                   require_source_event=True)
        assert r.get("skipped") == "missing_canonical_user_message", r
        after = hub._db.query_one(
            "SELECT * FROM user_model_items WHERE item_id=?", (row["item_id"],))
        assert after and after["status"] == "active"
        superseded = hub._db.query_all(
            "SELECT * FROM user_model_items WHERE status='superseded'")
        assert superseded == []
        assert hub.events.query_by_type("USER_PREFERENCE_CHANGED") == []

        # 同一门放行合法路径：真实 canonical USER_MESSAGE → 允许演化
        u = hub.events.append(event_type="USER_MESSAGE", payload={"text": "我现在不喝咖啡了"},
                              source="user", channel="DIRECT_USER_TURN", turn_id=9,
                              importance=0.2)
        r2 = hub.apply_user_message("我现在不喝咖啡了", turn_id=9,
                                    source_event_id=u.event_id,
                                    require_source_event=True)
        assert not r2.get("skipped"), r2
        assert r2["superseded"], "有真实 U 时同一门必须放行 lifecycle 演化"
        final = hub._db.query_one(
            "SELECT * FROM user_model_items WHERE item_id=?", (row["item_id"],))
        assert final and final["status"] == "superseded"
    finally:
        hub.close()


def test_r10_fc_t5_happy_row_t_u_identity_still_exact(tmp_path):
    """R10-FC-T4（happy path）：row → T → U 按 event id 精确解析（未被收紧破坏）。"""
    f, _ = _real_furina(tmp_path)
    try:
        _submit(f, "我喜欢喝咖啡")
        utt = "我现在不喝咖啡了"
        _submit(f, utt)
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=15.0)
        row = f.cognition._db.query_one(
            "SELECT * FROM user_model_items WHERE category='PREFERENCE' "
            "AND status='superseded' ORDER BY updated_at DESC LIMIT 1")
        assert row
        t = next(e for e in f.cognition.events.query_recent(200)
                 if e.event_id == row["transition_event_id"])
        u = next(e for e in f.cognition.events.query_recent(200)
                 if e.event_id == t.payload.get("source_event_id", ""))
        assert t.event_type == "USER_PREFERENCE_CHANGED"
        assert u.event_type == "USER_MESSAGE" and u.payload.get("text") == utt
        assert t.payload.get("statement") == utt
        assert t.turn_id == u.turn_id and t.turn_id is not None
        qids = {o["turn_id"] for o in q.recent_outcomes(20)}
        assert u.turn_id in qids
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_fc_t6_identical_corrections_resolve_by_identity(tmp_path):
    """R10-FC-T5：两回合相同 correction 文本 → 不同 U event id / turn id。"""
    f, _ = _real_furina(tmp_path)
    try:
        _submit(f, "我喜欢喝咖啡")
        _submit(f, "我现在不喝咖啡了")            # turn A
        _submit(f, "我喜欢喝咖啡")
        _submit(f, "我现在不喝咖啡了")            # turn B（相同文本）
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=20.0)
        rows = _transition_rows(
            f, "SELECT * FROM user_model_items WHERE category='PREFERENCE' "
               "AND status='superseded' ORDER BY updated_at ASC")
        assert len(rows) == 2, f"期望两次 supersede: {len(rows)}"
        pair = []
        for r in rows:
            t = next(e for e in f.cognition.events.query_recent(300)
                     if e.event_id == r["transition_event_id"])
            u = next(e for e in f.cognition.events.query_recent(300)
                     if e.event_id == t.payload.get("source_event_id", ""))
            pair.append((t, u))
        (t_a, u_a), (t_b, u_b) = pair
        assert u_a.event_id != u_b.event_id and u_a.turn_id != u_b.turn_id
        assert t_b.payload.get("source_event_id") == u_b.event_id
        assert u_a.payload.get("text") == u_b.payload.get("text")
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_fc_t7_reserved_prep_failure_still_terminal(tmp_path):
    """R10-FC-T6：reserve 后准备失败 → CANCELLED 终态；无 sequence hole。"""
    f, _ = _real_furina(tmp_path)
    try:
        q = f._direct_dialogue_queue()
        orig_freeze = f._freeze_direct_snapshot

        def _boom(text, ingress_seq=None):
            raise RuntimeError("freeze failed")
        f._freeze_direct_snapshot = _boom
        with pytest.raises(RuntimeError):
            f.submit_user_message("这一条会因为快照失败而取消")
        f._freeze_direct_snapshot = orig_freeze
        assert q.outcome_count()["CANCELLED"] >= 1
        _submit(f, "下一条必须正常")
        assert q.wait_idle(timeout=15.0)
        assert q.pending() == 0
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_fc_t8_ingress_fifo_and_reserve_deadline_regression(tmp_path):
    """R10-FC-T7：严格 ingress FIFO 保序；deadline 在 reserve 时刻起算；终态齐备。"""
    f, _ = _real_furina(tmp_path)
    try:
        texts = ["你好呀芙宁娜", "今天天气怎么样", "再讲个笑话吧"]
        for tx in texts:
            _submit(f, tx)
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=25.0)
        ing = [o for o in reversed(q.recent_outcomes(30))]
        assert len(ing) >= 3
        tail = [o["user_text"] for o in ing[-3:]]
        assert tail == texts, f"FIFO 顺序被破坏: {tail}"
        assert all(o["status"] in ("REPLIED", "FAILED", "CANCELLED") for o in ing[-3:])
        assert q.pending() == 0
        # deadline 于 reserve 即起算（worker 启动前；提交不重置）
        tid = q.reserve_turn(user_text="manual-probe")
        turn = q._turns[tid]
        assert turn.status == "RESERVED"
        assert abs(turn.deadline - (turn.created_monotonic + q.timeout)) < 1e-6
        q.cancel_reserved(tid, reason="probe-done")
        assert q._turns[tid].status == "CANCELLED"
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_fc_t9_app_logs_observable_warning_on_umsg_failure(tmp_path, caplog):
    """R10-FC 观察性：U append 失败 → App 记录可观察 FAIL-CLOSED warning。"""
    f, _ = _real_furina(tmp_path)
    try:
        _submit(f, "我喜欢喝咖啡")
        assert f._direct_dialogue_queue().wait_idle(timeout=15.0)
        state = _force_umsg_append_failure(f)
        try:
            with caplog.at_level(logging.WARNING, logger="app"):
                _submit(f, "我现在不喝咖啡了")
        finally:
            state["on"] = False
        f._direct_dialogue_queue().wait_idle(timeout=15.0)
        assert any("FAIL-CLOSED" in (r.getMessage()) for r in caplog.records), \
            [r.getMessage() for r in caplog.records]
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_fc_t10_time_never_regresses_deadline_contract(tmp_path):
    """冒烟：真实 correction 流程在失败路径之后仍可在健康路径再次 supersede。"""
    f, _ = _real_furina(tmp_path)
    try:
        _submit(f, "我喜欢喝咖啡")
        assert f._direct_dialogue_queue().wait_idle(timeout=15.0)
        state = _force_umsg_append_failure(f)
        try:
            _submit(f, "我现在不喝咖啡了")          # 失败回合：被关住
        finally:
            state["on"] = False
        f._direct_dialogue_queue().wait_idle(timeout=15.0)
        assert f.cognition.events.query_by_type("USER_PREFERENCE_CHANGED") == []
        time.sleep(0.05)
        _submit(f, "我现在不喝咖啡了")              # 健康回合（真实 canonical U）：恢复演化能力
        assert f._direct_dialogue_queue().wait_idle(timeout=15.0)
        n = f.cognition._db.query_one(
            "SELECT COUNT(*) AS c FROM user_model_items WHERE status='superseded'")
        assert n["c"] >= 1, "恢复健康证据链后 lifecycle 演化必须重新可用"
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass
