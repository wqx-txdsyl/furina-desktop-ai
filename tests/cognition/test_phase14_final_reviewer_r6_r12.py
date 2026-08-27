"""Phase 14 Final Reviewer Residual R6–R12 — reviewer-locked tests。

Counterexamples（§11）：
  A — provenance fail-open        -> R6-T1（C6 append 失败 → 无新 C3）
  B — fake Canon completeness     -> R7-T1（exact Act IV + CHARACTER_STORY/null-act → 不覆盖）
  C — invalidated social bid      -> R8-T2 / R9-preemption（Agent 抢占 → 无 USER_IGNORED）
  D — removed production wiring   -> R9（真实 Director.submit + drain → App._on_execute → Scheduler）
  E — duplicate identical text    -> R10-T3（相同 utterance 两回合 → 按 event id/turn 精确绑定）
  F — physical event identity     -> R11-T1..T3（pet/poke/drag → USER_PET/USER_POKE/USER_DRAG）
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from furina.core import EventBus
from furina.cognition import CognitionHub
from furina.director import ActionRequest
from furina.director.director import P_AGENT_TASK, P_INTERNAL_NEED
from furina.emotion import EmotionEngine
from furina.memory import MemoryEngine, MemoryStore
from furina.relationship.engine import RelationshipEngine
from furina.runtime.scheduler import Scheduler
from furina.state import StateEngine

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


def _sched_with_cog(tmp_path):
    bus = EventBus()
    se = StateEngine(bus)
    emo = EmotionEngine(se.state.emotion)
    store = MemoryStore(tmp_path / "mem.db")
    me = MemoryEngine(_Bus(), store)
    rel = RelationshipEngine()
    hub = CognitionHub(tmp_path / "cog.db", memory_engine=me, relationship_engine=rel)
    sched = Scheduler(bus, se, None, None, me, None, None,
                      emotion_engine=emo, relationship_engine=rel, cognition=hub)
    sched.dispatcher.bind_owner()
    sched.world_perc.state.idle_available = True
    sched.world_perc.state.user_present = True
    sched.world_perc.state.user_active = True
    sched.world_perc.state.user_idle_seconds = 5.0
    sched.world_perc._has_valid_idle = True
    return sched, hub, me


def _real_furina(tmp_path, timezone: str = ""):
    """真实 Furina + 真实 Scheduler（与 launch() 相同的装配），用于真实生产路径测试。

    Phase 15 D4/R1（加性参数）：``timezone`` 注入显式用户时区权威
    （AppConfig.timezone；默认空=维持旧行为 fail-closed）。"""
    from furina.app import Furina
    from furina.config import AppConfig, LLMProfile
    cfg = AppConfig(root_dir=tmp_path, zhipu_api_key="", agnes_api_key="",
                    llm=LLMProfile(api_key=""), data_dir=tmp_path,
                    timezone=timezone)
    f = Furina(cfg)
    sched = Scheduler(f.bus, f.state, f.behavior, f.director, f.memory, f.world, f.wa,
                      life_brain=f.life_brain, dialogue_brain=f.dialogue_brain,
                      emotion_engine=f.emotion, motivation=f.motivation,
                      relationship_engine=f.relationship, embodiment=f.embodiment,
                      cognition=f.cognition)
    f._sched = sched
    sched.dispatcher.bind_owner()
    sched.world_perc.state.idle_available = True
    sched.world_perc.state.user_present = True
    sched.world_perc.state.user_active = True
    sched.world_perc.state.user_idle_seconds = 5.0
    sched.world_perc._has_valid_idle = True
    return f, sched


def _ignore_mems(hub):
    return [m for m in hub.autobiography.all_memories(status=None)
            if getattr(m, "event_type", "") == "user_ignore"]


def _all_memory_ids(hub):
    return {m.mem_id for m in hub.autobiography.all_memories(status=None)}


# ================================================================ R6 — C3 fail-closed
def test_r6_t1_c6_append_failure_forms_no_memory(tmp_path):
    """COUNTEREXAMPLE A：强制 USER_STATEMENT_OBSERVED append 失败 → 无新 durable C3。"""
    from furina.memory import MemoryLevel, MemorySource
    f, _ = _real_furina(tmp_path)
    try:
        def _boom(*a, **k):
            raise RuntimeError("forced C6 append failure")
        f.cognition.record_event = _boom
        before = _all_memory_ids(f.cognition)
        r = f._observe_with_provenance("我今天准备完成一个重要计划",
                                       level=MemoryLevel.EPISODIC,
                                       source=MemorySource.CONVERSATION,
                                       importance=0.5, context="user_plan")
        assert r is None, "fail-closed：C6 失败必须返回 None（不落库）"
        assert _all_memory_ids(f.cognition) == before, "不得形成 provenance-less C3"
        assert f.cognition.events.query_by_type("USER_STATEMENT_OBSERVED") == []
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r6_t2_successful_observation_keeps_resolvable_provenance(tmp_path):
    """R6-T2：成功路径 —— C6 存在 → C3 source_event_ids != [] → 全部解析到 life_events。"""
    from furina.memory import MemoryLevel, MemorySource
    f, _ = _real_furina(tmp_path)
    try:
        m = f._observe_with_provenance("我喜欢在晚上看书", level=MemoryLevel.EPISODIC,
                                       source=MemorySource.CONVERSATION, importance=0.5,
                                       context="user_speech")
        assert m is not None and m.source_event_ids, "成功路径必须带 provenance"
        evs = f.cognition.events.query_by_type("USER_STATEMENT_OBSERVED")
        assert any(e.event_id == m.source_event_ids[0] for e in evs), \
            "provenance 必须解析到真实 USER_STATEMENT_OBSERVED"
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r6_t3_no_swallow_and_continue_path():
    """R6-T3：production 代码不存在 C6 append 异常 → source_event_ids=[] → durable C3 的路径。"""
    import furina.app as A
    src = open(A.__file__, encoding="utf-8").read()
    start = src.index("def _observe_with_provenance")
    end = src.index("def _maybe_observe_conversation")
    body = src[start:end]
    assert "FAIL CLOSED" in body, "必须显式 fail-closed"
    assert "return None" in body, "C6 失败必须 return None"
    # 不允许旧的 swallow-and-continue 模式（except: pass 后仍调用 memory.observe）
    assert "except Exception:\n            pass\n        return self.memory.observe" not in body
    assert "source_event_ids=src_ids" not in body


def test_r6_t4_existing_successful_c3_routes_keep_provenance(tmp_path):
    """R6-T4：USER_FEED / USER_POKE / USER_IGNORED / verified AGENT_COMPLETED 全部保持可解析 provenance。"""
    hub = _hub(tmp_path)
    # USER_FEED（真实生产入口 submit_feed 路径由 integration 覆盖；此处 consolidation 路径）
    ev_feed = hub.record_event("USER_FEED", payload={"food": "蛋糕"},
                               source="interaction", importance=0.5)
    # USER_POKE（R11 独立类型）
    hub.record_event("USER_POKE", payload={"kind": "poke", "count": 1},
                     source="interaction", importance=0.5)
    # verified AGENT_COMPLETED
    ev_agent = hub.record_event("AGENT_COMPLETED", payload={"goal": "创建报告"},
                                source="agent", task_id="t_r6", importance=0.6)
    ev_ids_before = {e.event_id for e in hub.events.query_recent(100)}
    assert ev_feed.event_id in ev_ids_before and ev_agent.event_id in ev_ids_before
    for m in hub.autobiography.all_memories(status=None):
        assert m.source_event_ids, f"无 provenance 记忆: {m.content}"
        assert set(m.source_event_ids) <= ev_ids_before, "provenance 必须全部解析到 C6"
    hub.close()
    # 真实 Furina 生产 ingress 驱动 USER_IGNORED（Director 边界见 R9；此处 scheduler 直接入口）
    sched, hub2, _ = _sched_with_cog(tmp_path)
    sched.on_mind_action_started("approach_user")
    sched._pending_social_bid["deadline"] = time.time() - 1.0
    sched._tick_social_bid()
    ev_ignored = hub2.events.query_by_type("USER_IGNORED")[0]
    ev_ids = {e.event_id for e in hub2.events.query_recent(100)}
    for m in hub2.autobiography.all_memories(status=None):
        assert m.source_event_ids, f"无 provenance 记忆: {m.content}"
        assert set(m.source_event_ids) <= ev_ids, "provenance 必须全部解析到 C6"
    assert ev_ignored.event_id in ev_ids
    hub2.close()


# ================================================================ R7 — semantic completeness
def _fixture_hub(episode: dict):
    """临时 fixture episode 经 production reader（CanonHistoryStore）加载；
    registry/sources 使用仓库真源。"""
    from furina.cognition.stores.canon_history import CanonHistoryStore
    tmp = Path(tempfile.mkdtemp())
    hist = tmp / "hist.json"
    hist.write_text(json.dumps({"episodes": [episode]}, ensure_ascii=False), encoding="utf-8")
    return CanonHistoryStore(history_path=hist,
                             sources_path=_REAL_SOURCES,
                             evidence_path=_REAL_REGISTRY)


def test_r7_t1_character_story_null_act_cannot_cover_exact_act(tmp_path):
    """COUNTEREXAMPLE B：episode act=IV + CHARACTER_STORY(null act) → 不得算作 Act IV 覆盖。"""
    ep = {"episode_id": "FIX_EP", "quest": "Chapter IV", "act": "IV",
          "evidence_ids": ["FUR-052"], "source_ids": ["SRC-006"], "timeline_order": 1}
    store = _fixture_hub(ep)
    gaps = store.metrics()["episodes_without_exact_act_main_story_evidence"]
    assert any(g["episode"] == "FIX_EP" for g in gaps), \
        f"CHARACTER_STORY/null-act 不得满足精确 Act IV: {gaps}"
    assert store.metrics()["mandatory_life_stage_source_status"].startswith(
        "PARTIAL"), "语义不支撑 → 生命周期状态必须如实 PARTIAL"


def test_r7_t2_act_mismatch_is_semantic_conflict():
    """R7-T2：episode act=IV + MAIN_STORY/Chapter IV/act=I evidence → semantic conflict。"""
    ep = {"episode_id": "FIX_EP", "quest": "Chapter IV", "act": "IV",
          "evidence_ids": ["FUR-006"], "source_ids": ["SRC-001"], "timeline_order": 1}
    store = _fixture_hub(ep)
    conflicts = store.metrics()["evidence_attribution_conflicts"]
    assert any(c["episode"] == "FIX_EP" and c.get("evidence_act") == "I" for c in conflicts), \
        f"act 不一致必须产生语义冲突: {conflicts}"
    status = store.metrics()["mandatory_life_stage_source_status"]
    assert not status.endswith("SOURCE_COMPLETE"), \
        f"semantic_conflicts != [] 时不得 SOURCE_COMPLETE: {status}"


def test_r7_t3_same_act_main_story_is_valid():
    """R7-T3：MAIN_STORY/Chapter IV/act=IV evidence 对 Act IV 有效。"""
    ep = {"episode_id": "FIX_EP", "quest": "Chapter IV", "act": "IV",
          "evidence_ids": ["FUR-039"], "source_ids": ["SRC-001"], "timeline_order": 1}
    store = _fixture_hub(ep)
    m = store.metrics()
    assert m["evidence_attribution_conflicts"] == []
    assert not any(g["episode"] == "FIX_EP"
                   for g in m["episodes_without_exact_act_main_story_evidence"])
    assert m["mandatory_life_stage_source_status"] == "SOURCE_COMPLETE"


def test_r7_t4_fur006_remains_main_story_act_one():
    """R7-T4：FUR-006 保持 MAIN_STORY / Chapter IV / Act I。"""
    store = _fixture_hub({"episode_id": "X", "quest": "Chapter IV", "act": "I",
                          "evidence_ids": ["FUR-006"], "source_ids": ["SRC-001"],
                          "timeline_order": 1})
    u = store.evidence_unit("FUR-006")
    assert u["source_type"] == "MAIN_STORY" and u["quest"] == "Chapter IV" and u["act"] == "I"


def test_r7_t5_fur052_cannot_satisfy_exact_main_story_act():
    """R7-T5：FUR-052 保持 CHARACTER_STORY/act=null，且不能支撑任何精确主线 act。"""
    store = _fixture_hub({"episode_id": "X", "quest": "Chapter IV", "act": "V",
                          "evidence_ids": ["FUR-052"], "source_ids": ["SRC-006"],
                          "timeline_order": 1})
    u = store.evidence_unit("FUR-052")
    assert u["source_type"] == "CHARACTER_STORY" and u.get("act") in (None, "")
    gaps = store.metrics()["episodes_without_exact_act_main_story_evidence"]
    assert any(g["episode"] == "X" for g in gaps), "FUR-052 不得满足任何精确主线 act"


def test_r7_t6_production_metrics_truthful():
    """R7-T6：production metrics 如实暴露（与文档一致，见 FURINA_CANON_LIFE_SOURCE_MAP.md）。

    Phase 15 D1（生产事实迁移，closeout 披露）：官方 Act II/III 幕级锚点（SRC-011/012 →
    FUR-057/058）补齐后，幕级 coverage 变为 COMPLETE；语义层 PARTIAL 的唯一缺口仍
    锁定为 INNER_WORLD_REVELATION——该保护强度不变，仅更新已验证的生产期望值。
    """
    hub = _hub(Path(tempfile.mkdtemp()))
    m = hub.canon_history.metrics()
    # 结构层（既有锁定契约保持）
    assert m["canon_span_status"] == "MANDATORY_SPAN_SOURCE_COMPLETE"
    # 语义层：两类完整性分离且如实
    assert m["main_story_act_coverage_status"] == "COMPLETE"
    assert m["missing_main_story_acts"] == [], m["missing_main_story_acts"]
    assert m["main_story_act_coverage"] == {"I": True, "II": True, "III": True,
                                            "IV": True, "V": True}
    assert m["evidence_attribution_conflicts"] == []
    assert m["evidence_registry_duplicates"] == []
    assert m["unregistered_evidence_ids"] == []
    # INNER_WORLD_REVELATION 的 act=V 主张缺乏同 act MAIN_STORY 证据 → 如实列出（唯一缺口）
    gaps = [g["episode"] for g in m["episodes_without_exact_act_main_story_evidence"]]
    assert gaps == ["INNER_WORLD_REVELATION"], gaps
    assert m["mandatory_life_stage_source_status"].startswith("PARTIAL")
    hub.close()


def test_r7_t7_missing_acts_exposed():
    """R7-T7：coverage 暴露机制必须持续工作。

    D1 后五幕齐备 → missing=[]；本用例改锁"暴露机制的诚实性"：
    每个登记为 False 的幕必须出现在 missing 列表中（若出现 None 型缺口），
    且当前全 True 时 missing 必须恰为空（不许隐瞒任何缺失）。
    """
    hub = _hub(Path(tempfile.mkdtemp()))
    m = hub.canon_history.metrics()
    cov = m["main_story_act_coverage"]
    expected_missing = sorted(a for a, ok in cov.items() if not ok)
    assert m["missing_main_story_acts"] == expected_missing
    if all(cov.values()):
        assert m["missing_main_story_acts"] == []
        assert m["main_story_act_coverage_status"] == "COMPLETE"
    hub.close()


# ================================================================ R8 — social bid lifecycle
def test_r8_t1_bid_start_failure_fails_closed(tmp_path):
    """R8-T1：SOCIAL_BID_STARTED 持久化失败 → 不开响应窗口 → 无 ignore。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    hub.record_event = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("forced"))
    sched.begin_social_bid(reason="executed:approach_user")
    assert sched._pending_social_bid is None, "E1 失败 → 不得开启 pending 窗口"
    sched._tick_social_bid(now=time.time() + 9999)
    assert hub.events.query_by_type("USER_IGNORED") == []
    assert _ignore_mems(hub) == []
    hub.close()


def test_r8_t2_preemption_cancels_bid_no_ignore(tmp_path):
    """R8-T2：approach_user 开始（E1=1）→ Agent 抢占 → 无 USER_IGNORED、无 ignore C3。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    sched.on_mind_action_started("approach_user")
    assert len(hub.events.query_by_type("SOCIAL_BID_STARTED")) == 1
    sched.on_mind_preempted(reason="preempted_by_agent")
    assert sched._pending_social_bid is None, "抢占必须使 pending bid 失效"
    sched._tick_social_bid(now=time.time() + 9999)
    assert hub.events.query_by_type("USER_IGNORED") == [], "失效 bid 不得产生 ignore"
    assert _ignore_mems(hub) == []
    hub.close()


def test_r8_t3_user_response_clears_bid(tmp_path):
    """R8-T3：用户正常回应 → bid 清除 → 无 ignore。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    sched.on_mind_action_started("approach_user")
    assert sched._pending_social_bid is not None
    sched.on_user_response()
    assert sched._pending_social_bid is None
    sched._tick_social_bid(now=time.time() + 9999)
    assert hub.events.query_by_type("USER_IGNORED") == []
    hub.close()


def test_r8_t4_ordinary_timeout_chain_intact(tmp_path):
    """R8-T4：正常未中断超时 → E1=1, E2=1, memory=[E2, E1]。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    sched.on_mind_action_started("approach_user")
    e1 = hub.events.query_by_type("SOCIAL_BID_STARTED")[0]
    sched._pending_social_bid["deadline"] = time.time() - 1.0
    sched._tick_social_bid()
    e2 = hub.events.query_by_type("USER_IGNORED")[0]
    mems = _ignore_mems(hub)
    assert len(mems) == 1
    assert list(mems[0].source_event_ids) == [e2.event_id, e1.event_id]
    hub.close()


def test_r8_t5_repeated_cancel_and_ticks_exactly_once(tmp_path):
    """R8-T5：重复取消/重复 tick → 无假 ignore、exactly-once。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    sched.on_mind_action_started("approach_user")
    sched._cancel_social_bid("test")
    sched._cancel_social_bid("again")          # 幂等
    sched.on_mind_preempted(reason="preempted_by_user")
    for _ in range(3):
        sched._tick_social_bid(now=time.time() + 9999)
    assert hub.events.query_by_type("USER_IGNORED") == []
    assert len(hub.events.query_by_type("SOCIAL_BID_STARTED")) == 1
    hub.close()


# ================================================================ R9 — real Director E2E
def test_r9_real_director_e2e_production_wiring(tmp_path):
    """COUNTEREXAMPLE D：真实 Director.submit + drain → App._on_execute → Scheduler → C3。

    不直接调用 sched.on_mind_action_started —— 删除 App._on_execute 的 Scheduler 回调
    本测试即失败（锁定真实 wiring）。"""
    f, sched = _real_furina(tmp_path)
    try:
        f.director.submit(ActionRequest(source="mind", action="approach_user",
                                        priority=P_INTERNAL_NEED, reason="e2e",
                                        interruptible=True,
                                        payload={"planned_duration": 5.0}))
        f.director.drain()
        bids = f.cognition.events.query_by_type("SOCIAL_BID_STARTED")
        assert len(bids) == 1, \
            "真实 Director→App._on_execute→Scheduler 链路必须开启 bid（wiring 被删除即失败）"
        e1 = bids[0]
        sched._pending_social_bid["deadline"] = time.time() - 1.0
        sched._tick_social_bid()
        e2s = f.cognition.events.query_by_type("USER_IGNORED")
        assert len(e2s) == 1
        e2 = e2s[0]
        assert e2.payload.get("bid_source_event_id") == e1.event_id
        mems = [m for m in f.cognition.autobiography.all_memories(status=None)
                if m.event_type == "user_ignore"]
        assert mems and list(mems[0].source_event_ids) == [e2.event_id, e1.event_id], \
            f"因果链必须完整: {mems[0].source_event_ids if mems else None}"
        # exactly-once
        sched._tick_social_bid()
        assert len(f.cognition.events.query_by_type("USER_IGNORED")) == 1
        assert len([m for m in f.cognition.autobiography.all_memories(status=None)
                    if m.event_type == "user_ignore"]) == 1
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r9_agent_preemption_invalidates_bid_real_director(tmp_path):
    """COUNTEREXAMPLE C（real Director）：mind approach 进行中 → agent 高优先级接管 →
    pending bid 失效 → 无 USER_IGNORED。"""
    f, sched = _real_furina(tmp_path)
    try:
        f.director.submit(ActionRequest(source="mind", action="approach_user",
                                        priority=P_INTERNAL_NEED, reason="e2e",
                                        interruptible=True,
                                        payload={"planned_duration": 5.0}))
        f.director.drain()
        assert len(f.cognition.events.query_by_type("SOCIAL_BID_STARTED")) == 1
        assert sched._pending_social_bid is not None
        # agent 更高优先级接管（真实 Director 仲裁 + on_before_replace）
        f.director.submit(ActionRequest(source="agent", action="agent_work",
                                        priority=P_AGENT_TASK, reason="takeover"))
        f.director.drain()
        assert sched._pending_social_bid is None, "Agent 抢占必须使 bid 失效"
        sched._tick_social_bid(now=time.time() + 9999)
        assert f.cognition.events.query_by_type("USER_IGNORED") == [], \
            "被抢占的 bid 不得产生 USER_IGNORED"
        assert not [m for m in f.cognition.autobiography.all_memories(status=None)
                    if m.event_type == "user_ignore"]
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


# ================================================================ R10 — exact USER_MESSAGE identity
def _submit(f, text):
    f.submit_user_message(text)


def _transition_row(f, category, status):
    return f.cognition._db.query_one(
        "SELECT * FROM user_model_items WHERE category=? AND status=? "
        "ORDER BY updated_at DESC LIMIT 1", (category, status))


def _resolve_transition(f, row):
    """row → T（transition 事件）→ U（canonical USER_MESSAGE）→ verbatim utterance。"""
    t = next(e for e in f.cognition.events.query_recent(200)
             if e.event_id == row["transition_event_id"])
    src = t.payload.get("source_event_id", "")
    u = next(e for e in f.cognition.events.query_recent(200) if e.event_id == src)
    return t, u


def test_r10_t1_preference_transition_exact_user_message_identity(tmp_path):
    """R10-T1：row → exact transition event → exact USER_MESSAGE event → verbatim utterance。"""
    f, _ = _real_furina(tmp_path)
    try:
        _submit(f, "我喜欢喝咖啡")
        utt = "我现在不喝咖啡了"
        _submit(f, utt)
        row = _transition_row(f, "PREFERENCE", "superseded")
        assert row
        t, u = _resolve_transition(f, row)
        assert t.event_type == "USER_PREFERENCE_CHANGED"
        assert u.event_type == "USER_MESSAGE", "T 必须精确指向 canonical USER_MESSAGE"
        assert u.payload.get("text") == utt
        assert t.payload.get("statement") == utt
        assert row["transition_event_id"] == t.event_id
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_t2_plan_complete_exact_user_message_identity(tmp_path):
    """R10-T2：plan complete 同样 row → T → U → verbatim utterance。"""
    f, _ = _real_furina(tmp_path)
    try:
        _submit(f, "我今天准备完成桌宠测试")
        utt = "桌宠测试做完了"
        _submit(f, utt)
        row = _transition_row(f, "PLAN", "completed")
        assert row and row["key"] == "plan:桌宠测试"
        t, u = _resolve_transition(f, row)
        assert t.event_type == "USER_PLAN_COMPLETED"
        assert u.event_type == "USER_MESSAGE" and u.payload.get("text") == utt
        assert t.payload.get("statement") == utt
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_t3_duplicate_identical_utterance_resolves_by_event_id(tmp_path):
    """COUNTEREXAMPLE E：两个回合说相同 correction —— 必须按 event id 绑定到对应 turn。"""
    f, _ = _real_furina(tmp_path)
    try:
        _submit(f, "我喜欢喝咖啡")            # 建立 preference
        _submit(f, "我现在不喝咖啡了")        # turn A：supersede #1
        _submit(f, "我喜欢喝咖啡")            # 重新声明 → 新 ACTIVE item
        _submit(f, "我现在不喝咖啡了")        # turn B：supersede #2（相同文本！）
        rows = f.cognition._db.query_all(
            "SELECT * FROM user_model_items WHERE category='PREFERENCE' "
            "AND status='superseded' ORDER BY updated_at ASC")
        assert len(rows) == 2, f"期望两次 supersede: {len(rows)}"
        row_b = rows[-1]                       # 最后一次 transition
        t_b, u_b = _resolve_transition(f, row_b)
        row_a = rows[0]
        t_a = next(e for e in f.cognition.events.query_recent(200)
                   if e.event_id == row_a["transition_event_id"])
        u_a = next(e for e in f.cognition.events.query_recent(200)
                   if e.event_id == t_a.payload.get("source_event_id", ""))
        assert u_b.event_id != u_a.event_id, "两个回合的事件身份必须不同"
        assert u_b.turn_id != u_a.turn_id, "两个回合的 turn 身份必须不同"
        assert t_b.payload.get("source_event_id") == u_b.event_id, \
            "turn B 的 transition 必须精确指向 turn B 的 USER_MESSAGE（文本相等不够）"
        assert u_b.payload.get("text") == u_a.payload.get("text"), \
            "两条 utterance 文本确实相同（证明按身份而非文本解析）"
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_t4_linked_events_share_turn_identity(tmp_path):
    """R10-T4：U.turn_id == T.turn_id == DirectDialogueQueue turn_id。"""
    f, _ = _real_furina(tmp_path)
    try:
        _submit(f, "我喜欢喝咖啡")
        _submit(f, "我现在不喝咖啡了")
        row = _transition_row(f, "PREFERENCE", "superseded")
        t, u = _resolve_transition(f, row)
        assert t.turn_id == u.turn_id and t.turn_id is not None, \
            f"linked 事件必须共享 turn identity: T={t.turn_id} U={u.turn_id}"
        q = f._direct_dialogue_queue()
        qids = {o["turn_id"] for o in q.recent_outcomes(20)}
        assert u.turn_id in qids, "turn_id 必须是 DirectDialogueQueue 的 ingress identity"
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_t5_no_circular_provenance(tmp_path):
    """R10-T5：row → T → U 无循环（T 不指向自身、T ≠ U）。"""
    f, _ = _real_furina(tmp_path)
    try:
        _submit(f, "我喜欢喝咖啡")
        _submit(f, "我现在不喝咖啡了")
        row = _transition_row(f, "PREFERENCE", "superseded")
        t, u = _resolve_transition(f, row)
        assert t.event_id != u.event_id
        assert t.payload.get("source_event_id") != t.event_id, "T 不得指向自身"
        # row 指向 derived transition 事件 T（derived 事件保留），T 精确指向 U —— 无循环
        assert row["transition_event_id"] == t.event_id
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r10_t7_reserved_turn_cancel_no_sequence_hole(tmp_path):
    """R10-T7：reserve 后 owner 准备失败 → 可观察终态；后续 turn 无 hole。"""
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
        assert q.outcome_count()["CANCELLED"] >= 1, "reserve 后失败必须到达可观察终态"
        # 后续 turn 正常分配、正常终态（无 sequence hole / 永久 pending）
        f.submit_user_message("下一条必须正常")
        assert q.wait_idle(timeout=5.0), "后续 turn 必须到达终态（无永久 pending）"
        assert q.pending() == 0
        assert q.outcome_count()["CANCELLED"] >= 1
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


# ================================================================ R11 — physical event truth
def test_r11_t1_petting_emits_user_pet_only(tmp_path):
    """COUNTEREXAMPLE F / R11-T1：petting → 恰好 1 条 USER_PET；无 USER_POKE/USER_DRAG。"""
    f, _ = _real_furina(tmp_path)
    try:
        f.interaction.emit_event("petting", "head")
        assert len(f.cognition.events.query_by_type("USER_PET")) == 1
        assert f.cognition.events.query_by_type("USER_POKE") == []
        assert f.cognition.events.query_by_type("USER_DRAG") == []
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r11_t2_poke_emits_user_poke_only(tmp_path):
    """R11-T2：poke → 恰好 1 条 USER_POKE；poke 不产生 USER_PET。"""
    f, _ = _real_furina(tmp_path)
    try:
        f.interaction.emit_event("poke", "whole")
        assert len(f.cognition.events.query_by_type("USER_POKE")) == 1
        assert f.cognition.events.query_by_type("USER_PET") == []
        assert f.cognition.events.query_by_type("USER_DRAG") == []
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r11_t3_drag_emits_user_drag_only(tmp_path):
    """R11-T3：drag → 恰好 1 条 USER_DRAG；drag 不产生 USER_PET。"""
    f, _ = _real_furina(tmp_path)
    try:
        f.interaction.emit_event("drag", "whole")
        assert len(f.cognition.events.query_by_type("USER_DRAG")) == 1
        assert f.cognition.events.query_by_type("USER_PET") == []
        assert f.cognition.events.query_by_type("USER_POKE") == []
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_r11_t4_c3_content_matches_true_interaction(tmp_path):
    """R11-T4：C3 内容与真实物理互动一致（戳/拎 ≠ 摸头）。"""
    hub = _hub(tmp_path)
    hub.record_event("USER_POKE", payload={"kind": "poke", "count": 1},
                     source="interaction", importance=0.5)
    hub.record_event("USER_DRAG", payload={"kind": "drag", "count": 1},
                     source="interaction", importance=0.5)
    hub.record_event("USER_PET", payload={"kind": "petting", "count": 1},
                     source="interaction", importance=0.5)
    contents = [m.content for m in hub.autobiography.all_memories(status=None)]
    assert any("戳" in c for c in contents)
    assert any("拎" in c for c in contents)
    assert any("摸" in c for c in contents)      # petting 仍是摸头
    hub.close()


def test_r11_t5_repeated_high_count_poke_not_pet(tmp_path):
    """R11-T5：高频重复 poke（count>5）→ 拒绝/重复语义，不是摸头。"""
    hub = _hub(tmp_path)
    hub.record_event("USER_POKE", payload={"kind": "poke", "count": 9},
                     source="interaction", importance=0.5)
    mems = hub.autobiography.all_memories(status=None)
    assert any("反复戳" in m.content for m in mems), [m.content for m in mems]
    assert not any("摸" in m.content for m in mems)
    hub.close()


def test_r11_t6_all_formed_c3_preserves_exact_provenance(tmp_path):
    """R11-T6：三种互动形成的 C3 全部保留 exact C6 provenance。"""
    hub = _hub(tmp_path)
    evs = []
    evs.append(hub.record_event("USER_PET", payload={"kind": "petting"}, source="interaction",
                                importance=0.5))
    evs.append(hub.record_event("USER_POKE", payload={"kind": "poke", "count": 1},
                                source="interaction", importance=0.5))
    evs.append(hub.record_event("USER_DRAG", payload={"kind": "drag"}, source="interaction",
                                importance=0.5))
    all_ids = {e.event_id for e in hub.events.query_recent(100)}
    for m in hub.autobiography.all_memories(status=None):
        assert m.source_event_ids and set(m.source_event_ids) <= all_ids, \
            f"provenance 必须精确解析: {m.source_event_ids}"
    assert {e.event_id for e in evs} <= all_ids
    hub.close()
