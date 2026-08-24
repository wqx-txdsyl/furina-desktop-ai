"""Phase 06: Structured World Perception 测试（§30）。"""
from __future__ import annotations

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality
from furina.world_perception import WorldPerception, UserActivity, WorldEvent

P = Personality(0.6, 0.7, 0.55, 0.6, 0.7, 0.6, 0.65, 0.55)


def _wp():
    return WorldPerception()


def test_activity_classification():
    wp = _wp()
    wp.update(app="Code.exe", title="main.py", idle_seconds=2, hour=14, minute=0, typing=True, dt=3)
    assert wp.state.user_activity == UserActivity.CODING, "IDE+输入→coding"
    wp.update(app="chrome", title="tab", idle_seconds=4, hour=14, minute=1, typing=False, dt=3)
    assert wp.state.user_activity == UserActivity.BROWSING, "浏览器→browsing"


def test_focus_estimation():
    wp = _wp()
    wp.update(app="Code.exe", title="a.py", idle_seconds=1, hour=14, minute=0, typing=True, dt=3)
    assert wp.state.user_focus_level > 0.7, "深度工作 focus 高"
    assert wp.state.interruption_cost > 0.6, "深度工作打扰成本高"
    assert wp.state.interaction_availability < 0.3, "深度工作可用低"


def test_interaction_availability_distinct():
    wp = _wp()
    wp.update(app="chrome", title="youtube", idle_seconds=5, hour=14, minute=0, typing=False, dt=3)
    assert wp.state.user_activity in (UserActivity.WATCHING_MEDIA, UserActivity.BROWSING)
    wp2 = _wp()
    wp2.update(app="chrome", title="tab", idle_seconds=120, hour=14, minute=0, typing=False, dt=3)
    # idle(120s,仍在场) 可用 > activity 时；或分类为 idle 且 avail 比 deep 高
    assert wp2.state.user_activity == UserActivity.IDLE, f"应为 idle: {wp2.state.user_activity}"
    assert wp2.state.interaction_availability > 0.6, "idle 可用应高"
    assert wp2.state.interaction_availability > wp.state.interaction_availability, "idle 可用应高于 active"


def test_world_event_transition():
    wp = _wp()
    wp.update(app="Code.exe", title="a.py", idle_seconds=2, hour=14, minute=0, typing=True, dt=3)
    assert "WORK_STARTED" in wp.state.recent_world_events
    wp.update(app="chrome", title="tab", idle_seconds=5, hour=14, minute=1, typing=False, dt=3)
    assert "WORK_ENDED" in wp.state.recent_world_events


def test_event_debounce():
    wp = _wp()
    # 快速在 IDE/browser 间切换多次，不应刷屏 WORK_STARTED/WORK_ENDED
    for i in range(8):
        app = "Code.exe" if i % 2 == 0 else "chrome"
        wp.update(app=app, title="x", idle_seconds=2, hour=14, minute=i % 60, typing=True, dt=3)
    # debounce 20s：8 个 tick(3s each)=24s 内同事件不应重复太多
    work_started = wp.state.recent_world_events.count("WORK_STARTED")
    assert work_started <= 2, f"WORK_STARTED 应被 debounce: {work_started}"


def test_user_return_event():
    wp = _wp()
    wp.update(app="Code.exe", title="a.py", idle_seconds=2, hour=14, minute=0, typing=True, dt=3)
    wp.update(app="Code.exe", title="a.py", idle_seconds=900, hour=14, minute=5, typing=False, dt=3)
    wp.update(app="Code.exe", title="a.py", idle_seconds=3, hour=14, minute=6, typing=True, dt=3)
    assert "USER_LEFT" in wp.state.recent_world_events
    assert "USER_RETURNED" in wp.state.recent_world_events


def test_work_start_end():
    wp = _wp()
    wp.update(app="Code.exe", title="a.py", idle_seconds=2, hour=14, minute=0, typing=True, dt=3)
    assert "WORK_STARTED" in wp.state.recent_world_events
    wp.update(app="chrome", title="tab", idle_seconds=4, hour=14, minute=1, typing=False, dt=3)
    assert "WORK_ENDED" in wp.state.recent_world_events


def test_world_to_motivation():
    """World → Motivation：深度工作时 talk 被压,单独空闲时 talk 高。"""
    def talk_score(idle, typing, app="Code.exe"):
        wp = _wp()
        wp.update(app=app, title="x", idle_seconds=idle, hour=14, minute=0, typing=typing, dt=3)
        st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 70; st.world = wp
        ee = EmotionEngine(st.emotion)
        m = BehaviorMotivation(personality=P)
        cs = m.candidates(st, ee, ctx={"world": wp.factors(), "recent_events": wp.event_tags()})
        return next((c.score for c in cs if c.activity == "talk"), 0.0)
    deep = talk_score(idle=2, typing=True)      # 深度工作
    available = talk_score(idle=5, typing=False, app="chrome")   # 空闲可用
    assert available > deep, f"空闲应比深度工作更敢 talk: {available:.2f} vs {deep:.2f}"


def test_world_off_control():
    """World OFF（ctx world_off=True）→ 不产生 world-specific 动机差异。"""
    wp = _wp()
    wp.update(app="Code.exe", title="a.py", idle_seconds=2, hour=14, minute=0, typing=True, dt=3)
    st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 70; st.world = wp
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation(personality=P)
    # OFF: 不注入 world
    off_c = m.candidates(st, ee, ctx={"world_off": True})
    on_c = m.candidates(st, ee, ctx={"world": wp.factors()})
    # 世界深工作时,ON 应改变 talk(top vs 候选) —— 至少一个候选的 score/why 不同
    off_why = {c.activity: c.why for c in off_c}
    on_why = {c.activity: c.why for c in on_c}
    assert on_why != off_why or {c.activity: c.score for c in on_c} != {c.activity: c.score for c in off_c}, \
        "World ON 应产生 world-specific 差异"


def test_world_counterfactual():
    """同一角色,只改 World(深工作 vs 空闲) → 行为变化。"""
    def top_act(app, idle, typing):
        wp = _wp(); wp.update(app=app, title="x", idle_seconds=idle, hour=14, minute=0, typing=typing, dt=3)
        st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 70; st.world = wp
        ee = EmotionEngine(st.emotion)
        m = BehaviorMotivation(personality=P)
        return m.candidates(st, ee, ctx={"world": wp.factors()})[0].activity
    deep = top_act("Code.exe", 2, True)
    avail = top_act("chrome", 5, False)
    assert deep != avail, "深工作 vs 空闲应产生不同行为"


def test_no_observation_collapse():
    """World 加入后长跑,observation 类别不>50%。"""
    import random
    rng = random.Random(5)
    st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 65
    wp = _wp(); st.world = wp
    ee = EmotionEngine(st.emotion); m = BehaviorMotivation(personality=P)
    from furina.behavior.motivation import CATEGORY
    cats = []
    seq = [("Code.exe", "a.py", True, 2), ("chrome", "tab", False, 5),
           ("Code.exe", "b.py", True, 2), ("chrome", "t2", False, 300), ("chrome", "t3", False, 900)]
    for i in range(120):
        app, title, typing, idle = seq[i % len(seq)]
        wp.update(app=app, title=title, idle_seconds=idle, hour=14, minute=i % 60, typing=typing, dt=3)
        m._last_done.clear(); m._activity_history = []; m._category_history = []
        cands = [c.as_dict() for c in m.candidates(st, ee, ctx={"world": wp.factors(), "recent_events": wp.event_tags()})]
        pick = rng.choices(cands[:4], weights=[max(0.04, c["motivation"]) for c in cands[:4]], k=1)[0]
        m.mark_done(pick["activity"], 0)
        cats.append(CATEGORY.get(pick["activity"]))
    obs = sum(1 for c in cats if c == "OBSERVATION") / len(cats)
    assert obs < 0.5, f"观察类不应塌缩: {obs:.0%}"


def test_assistance_opportunity():
    """深度工作+可帮 app → assistance_opportunity>0, 但不等于"请求帮忙"。"""
    wp = _wp()
    wp.update(app="Code.exe", title="a.py", idle_seconds=2, hour=14, minute=0, typing=True, dt=3)
    assert wp.state.assistance_opportunity > 0, "深度工作应产生 help_possible"
    wp2 = _wp()
    wp2.update(app="chrome", title="tab", idle_seconds=300, hour=14, minute=0, typing=False, dt=3)
    assert wp2.state.assistance_opportunity == 0, "空闲/离开不应有帮忙机会"
    # 有 help_possible 的 offer_help 动机抬升，但非强制
    st = CharacterState(); st.clock_hour = 14; st.world = wp
    ee = EmotionEngine(st.emotion); m = BehaviorMotivation(personality=P)
    c = m.candidates(st, ee, ctx={"world": wp.factors()})
    offer = next((x for x in c if x.activity == "offer_help"), None)
    assert offer is not None and ("help_possible" in offer.why if offer else False)
