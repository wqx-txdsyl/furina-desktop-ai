"""Phase 06B: World Affordance / Feasibility 测试（§19）。"""
from __future__ import annotations

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality
from furina.world_perception import WorldPerception
from furina.life_brain import LifeBrain

P = Personality(0.6, 0.7, 0.55, 0.6, 0.7, 0.6, 0.65, 0.55)


def _cands(app, idle, typing):
    wp = WorldPerception()
    wp.update(app=app, title="x", idle_seconds=idle, hour=14, minute=0, typing=typing, dt=3)
    st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 65; st.world = wp
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation(personality=P)
    return m.candidates(st, ee, ctx={"world": wp.factors(), "recent_events": wp.event_tags()}), wp


def test_away_removes_user_affordances():
    """away：用户定向行为 infeasible。"""
    c, _ = _cands("chrome", 900, False)
    for act in ("approach_user", "talk", "observe_user", "observe_work", "offer_help", "invite_user"):
        cand = next((x for x in c if x.activity == act), None)
        assert cand is not None and cand.feasible is False, f"{act} 应 infeasible"


def test_focus_does_not_remove_social_affordance():
    """deep focus：social 仍 feasible（只是 motivation 降）。"""
    c, _ = _cands("Code.exe", 2, True)
    for act in ("approach_user", "talk", "offer_help"):
        cand = next((x for x in c if x.activity == act), None)
        assert cand is not None and cand.feasible is True, f"{act} 深度工作应仍 feasible"


def test_returned_restores_user_affordance():
    """returned（重新在场）：approach/talk 重新 feasible。"""
    c, _ = _cands("Code.exe", 3, True)   # user present
    for act in ("approach_user", "talk"):
        cand = next((x for x in c if x.activity == act), None)
        assert cand.feasible is True, f"{act} 应恢复 feasible"


def test_feasibility_before_topn():
    """Feasibility 在 Top-N 前：Brain 只看到 feasible 候选。"""
    c, _ = _cands("chrome", 900, False)   # away
    space = LifeBrain._candidate_space([x.as_dict() for x in c], top_n=4)
    acts = [a["activity"] for a in space]
    assert "approach_user" not in acts and "talk" not in acts, f"away 的 allowed 不应含用户定向: {acts}"
    assert all(a.get("feasible", True) for a in space), "allowed 应全 feasible"


def test_brain_never_sees_infeasible():
    """away 时 user-directed 不在 decision_space（Brain 输入）。"""
    c, _ = _cands("chrome", 900, False)
    space = LifeBrain._candidate_space([x.as_dict() for x in c], top_n=4)
    assert all(a["feasible"] for a in space), "Brain allowed 空间不应含 infeasible"


def test_assistance_feasibility():
    """away：offer_help infeasible；working：feasible + help_possible；idle：feasible 无 help_possible。"""
    # away
    c, _ = _cands("chrome", 900, False)
    oh = next(x for x in c if x.activity == "offer_help")
    assert oh.feasible is False, "away 时 offer_help infeasible"
    # deep work
    c2, _ = _cands("Code.exe", 2, True)
    oh2 = next(x for x in c2 if x.activity == "offer_help")
    assert oh2.feasible is True, "working 时 offer_help feasible"
    assert "help_possible" in oh2.why, "working 时应有 help_possible tag"
    # idle（用户在场非工作）
    c3, _ = _cands("chrome", 120, False)
    oh3 = next(x for x in c3 if x.activity == "offer_help")
    assert oh3.feasible is True, "idle 时 offer_help feasible（可帮）"
    # idle 时不抬 helper 动机（无 help_possible）
    assert "help_possible" not in oh3.why, "idle 不应因 help_possible 抬 offer_help"


def test_surrogate_tick_equivalence():
    """surrogate 用生产等价 6s tick 积分（§16），非一次 dt=60。"""
    # 验证 WorldPerception 的 dt 确实按 6s 小步推进（无一次跳过 60s 的累加）
    wp = WorldPerception()
    wp.update(app="Code.exe", title="a.py", idle_seconds=2, hour=14, minute=0, typing=True, dt=6)
    assert wp.state.activity_duration < 6.5, "单 tick 不应跳过大量时长"
