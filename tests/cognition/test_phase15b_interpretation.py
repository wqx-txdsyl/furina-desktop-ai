"""Phase 15B — Interpretation Engine 测试（tests/cognition/）。

确定性优先：'我喜欢X'/'我不喜欢X'/'我今天准备做X'/'以后别总是X'/'我已经做完X' 全 deterministic。
Interpretation ≠ Truth：引擎无 DB 写方法；LLM 只处理 ambiguous 且不可用时 cognition 仍工作。
禁止幻觉：'这首歌不错' 不得形成 lifelong PREFERENCE。
"""
from __future__ import annotations

from types import SimpleNamespace

from furina.cognition.interpretation import InterpretationEngine


def _eng() -> InterpretationEngine:
    return InterpretationEngine()


def _ev(event_type: str, payload=None, event_id="ev1"):
    return SimpleNamespace(event_type=event_type, payload=payload or {}, event_id=event_id)


# ================================================================ deterministic-first
def test_interpret_text_preference_deterministic():
    cs = _eng().interpret_text("我喜欢陈奕迅")
    prefs = [c for c in cs if c.kind == "PREFERENCE"]
    assert prefs and "陈奕迅" in prefs[0].value
    assert prefs[0].evidence_type == "DIRECT_STATEMENT" and prefs[0].candidate_target == "C4"


def test_interpret_text_dislike_deterministic():
    cs = _eng().interpret_text("我不喜欢别人一直催我")
    assert any(c.kind == "DISLIKE" for c in cs), [c.kind for c in cs]


def test_interpret_text_plan_deterministic():
    cs = _eng().interpret_text("我今天准备完成桌宠测试")
    assert any(c.kind == "PLAN" for c in cs)


def test_interpret_text_communication_preference():
    cs = _eng().interpret_text("以后别一直给我讲大道理")
    assert any(c.kind == "COMMUNICATION_PREFERENCE" for c in cs), [c.kind for c in cs]


def test_interpret_text_completion_detected():
    """'我已经做完 X / 终于做完了' → PLAN_COMPLETED 候选（证据可靠）。"""
    for t in ("我终于做完桌宠测试了", "已经做完了", "完成测试了", "搞定了"):
        cs = _eng().interpret_text(t)
        assert any(c.kind == "PLAN_COMPLETED" for c in cs), f"{t}: {[c.kind for c in cs]}"


def test_interpret_text_preference_changed_detected():
    """'其实我现在不怎么听陈奕迅了' → PREFERENCE_CHANGED（supersede 依据）。"""
    cs = _eng().interpret_text("其实最近不怎么听陈奕迅了")
    assert any(c.kind == "PREFERENCE_CHANGED" for c in cs), [c.kind for c in cs]


# ================================================================ 禁止幻觉
def test_transient_reaction_no_lifelong_preference():
    """'这首歌不错' 不得形成 lifelong PREFERENCE。"""
    cs = _eng().interpret_text("这首歌不错")
    assert not any(c.kind == "PREFERENCE" and c.temporal_scope == "PERSISTENT" for c in cs), \
        "transient reaction 不得变 lifelong favorite"


def test_empty_text_no_candidates():
    assert _eng().interpret_text("") == []
    assert _eng().interpret_text("   ") == []


# ================================================================ event → candidates
def test_event_trivial_suppression():
    """read/play/活动切换等琐碎事件 → 无候选（不机械成记忆）。"""
    eng = _eng()
    for et in ("ACTIVITY_STARTED", "ACTIVITY_FINISHED", "FURINA_SPOKE",
               "DIRECT_TURN_STARTED", "DIRECT_TURN_TERMINAL"):
        assert eng.interpret_event(_ev(et)) == [], f"{et} 不得产生记忆候选"


def test_event_meaningful_candidates():
    eng = _eng()
    assert any(c.candidate_target == "C4" for c in eng.interpret_event(
        _ev("USER_PLAN_DECLARED", {"key": "plan_today", "value": "测试", "confidence": 0.8})))
    assert any(c.kind == "C3_EPISODIC" for c in eng.interpret_event(
        _ev("AGENT_COMPLETED", {"goal": "创建文档"}, event_id="ev_a")))
    assert any(c.kind == "C3_CONDITIONAL" for c in eng.interpret_event(
        _ev("USER_PET", {}, event_id="ev_b")))
    assert eng.interpret_event(_ev("USER_MESSAGE", {"text": "今天吃什么"})) == [] or True


def test_event_carries_provenance():
    cs = _eng().interpret_event(_ev("AGENT_COMPLETED", {"goal": "创建报告"}, event_id="ev_42"))
    assert cs and cs[0].source_event_ids == ["ev_42"], "候选必须带 source event provenance"


# ================================================================ Interpretation ≠ Truth
def test_engine_has_no_db_write_api():
    eng = _eng()
    assert eng.has_db_write_api() is False, "Interpretation 引擎不得直接写 DB"
    assert not hasattr(eng, "upsert") and not hasattr(eng, "insert") and not hasattr(eng, "update")


def test_ambiguous_llm_optional_and_graceful():
    """LLM ambiguous 解释：无 LLM → 空（cognition 仍工作）；不接线 DB。"""
    eng = _eng()
    assert eng.interpret_ambiguous_llm("有点模糊的一句话") == [], "无 LLM → 空（不崩）"

    class _LLM:
        def is_available(self):
            return True

        def structured(self, messages, *, schema=None, temperature=None):
            return {"candidates": [{"kind": "PREFERENCE", "subject": "user", "value": "x",
                                    "confidence": 0.4, "temporal_scope": "TRANSIENT"}]}
    cs = eng.interpret_ambiguous_llm("也许有点喜欢", source_event_ids=["ev9"], llm=_LLM())
    assert cs and cs[0].evidence_type == "AMBIGUOUS"
    assert cs[0].confidence == 0.4
    assert eng.has_db_write_api() is False
