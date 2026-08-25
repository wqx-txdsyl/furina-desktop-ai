"""Phase 13C — Digital Life Experience Recovery 测试（自然运动 + 对话机制 + 关系尺度契约）。"""
from __future__ import annotations

import random
import os
import time
from types import SimpleNamespace
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from furina.runtime.world import DesktopWorld, Rect
from furina.runtime.spatial import SpatialIntentResolver, DesktopSpatialRuntime, SpatialIntent
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.frame import FrameBody


def _mk(foot=(200, 900), aw=Rect(600, 200, 700, 600), seed=1):
    world = DesktopWorld(1920, 1080)
    world.taskbar_height = 48.0
    world.update_active_window(aw)
    rt = DesktopSpatialRuntime(world, window=None, rng=random.Random(seed))
    rt.set_initial_foot(foot[0], foot[1])
    return world, rt


def _frame(activity="idle", intent="NONE", posture="standing"):
    return RuntimeFrameBuilder().build(activity_name=activity,
                                       body=FrameBody(posture=posture),
                                       motion_intent=intent)


# ================================================================ A. Spatial path semantics
def test_spatial_path_not_always_single_segment():
    """APPROACH 不应总是单段直击目标——应有 path_style + waypoints。"""
    world, rt = _mk(foot=(200, 900))
    d = SpatialIntentResolver().resolve(_frame("approach_user", intent="APPROACH"))
    plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
    assert plan is not None
    assert plan.path_style in ("CURVED_APPROACH", "DIRECT_SOFT", "WANDER_MEANDER", "EXPLORE_MULTI_POINT")
    assert len(plan.waypoints) >= 1, "approach 应有中间 waypoint（非单段直线）"


def test_approach_and_wander_use_distinct_path_semantics():
    """APPROACH（弯） vs WANDER（漫游/多点）应产生不同 path_style / 几何。"""
    world, rt = _mk(foot=(200, 900))
    d_ap = SpatialIntentResolver().resolve(_frame("approach_user", intent="APPROACH"))
    p_ap = rt.planner.plan(d_ap, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
    rt2 = DesktopSpatialRuntime(world, rng=random.Random(2))
    rt2.set_initial_foot(200, 900)
    d_wd = SpatialIntentResolver().resolve(_frame("wander", intent="NONE"))
    p_wd = rt2.planner.plan(d_wd, rt2.state.position, rt2.adapter.char_w, rt2.adapter.char_h)
    assert p_ap is not None and p_wd is not None
    assert p_ap.path_style != p_wd.path_style or len(p_ap.waypoints) != len(p_wd.waypoints), \
        "approach 与 wander 应有可区分的路径语义"


def test_path_does_not_replan_every_tick():
    """同一计划多 tick：路径（waypoints）稳定，不被每帧重随机。"""
    world, rt = _mk(foot=(200, 900))
    d = SpatialIntentResolver().resolve(_frame("wander", intent="NONE"))
    rt.accept(d, now=0.0)
    wps_before = list(getattr(rt._current_plan, "waypoints", [])) if rt._current_plan else []
    for i in range(1, 40):
        rt.tick(now=i * 0.1)
    wps_after = list(getattr(rt._current_plan, "waypoints", [])) if rt._current_plan else []
    assert wps_before == wps_after, "路径中间点不应每 tick 重随机"


def test_drag_cancels_active_path():
    """拖拽打断当前路径（DRAGGED），路径被取消。"""
    QApplication.instance() or QApplication([])
    from furina.runtime.harness.proxy import SpatialProxyWindow
    world = DesktopWorld(1920, 1080)
    world.update_active_window(Rect(600, 200, 700, 600))
    win = SpatialProxyWindow(world=world)
    rt = DesktopSpatialRuntime(world, window=win)
    rt.set_initial_foot(200, 900)
    d = SpatialIntentResolver().resolve(_frame("approach_user", intent="APPROACH"))
    rt.accept(d, now=0.0)
    rt.tick(now=0.5)
    assert rt.state.moving
    rt.on_drag_start(now=1.0)
    assert rt.state.state == "DRAGGED" and not rt.state.moving


# ================================================================ C. Dialogue mechanism
def test_question_act_not_comment():
    from furina.dialogue_brain import DialogueBrain
    db = DialogueBrain.__new__(DialogueBrain)
    assert db.classify_act("你在干嘛？") == "RESPONSE_TO_QUESTION"
    assert db.classify_act("你觉得我现在应该休息吗？") == "RESPONSE_TO_QUESTION"


def test_rejection_act_not_comment():
    from furina.dialogue_brain import DialogueBrain
    db = DialogueBrain.__new__(DialogueBrain)
    assert db.classify_act("别烦我，我要忙一会。") == "DECLINE"


def test_comfort_context_not_comment():
    from furina.dialogue_brain import DialogueBrain
    db = DialogueBrain.__new__(DialogueBrain)
    assert db.classify_act("其实我今天有点累。") == "COMFORT"
    assert db.classify_act("你挺可爱的。") == "REACT"


def test_same_act_does_not_permanently_silence_user_dialogue():
    """§21：用户发起的对话不能因 act 重复而永久静音。"""
    from furina.dialogue_brain import DialogueBrain
    class _LLM:
        def is_available(self): return True
        def structured(self, msgs, schema=None, temperature=0.9): return {"speech": "好的"}
    db = DialogueBrain(_LLM(), "p")
    for _ in range(4):
        out = db.say(intent="talk", emotion="calm", user_text="你好呀", user_initiated=True)
        assert out is not None, "用户发起的对话不应因 act 重复被静音"


def test_current_activity_reaches_dialogue_prompt():
    from furina.dialogue_brain import _dialogue_prompt_v2
    class _App:
        def to_prompt(self):
            return {"mode": "CASUAL", "secondary_mode": "", "dialogue_act": "COMMENT", "strategy": ""}
        mode = "CASUAL"; dialogue_act = "COMMENT"
    p = _dialogue_prompt_v2(_App(), intent="talk", emotion="calm", user_text="你在干嘛？",
                            context="", memories=None, world=None, examples=[], person="p",
                            activity="read")
    assert "正在做的事" in p and "read" in p, "当前活动必须进入 prompt"


# ================================================================ G. relationship scale contract
def test_relationship_consumer_factors_normalized():
    from furina.relationship.engine import RelationshipEngine
    from furina.memory.memory_types import RelationshipState
    st = RelationshipState()
    st.trust = 0.5
    st.interaction_tolerance = 50.0   # 0-100
    st.social_confidence = 40.0       # 0-100
    r = RelationshipEngine(st)
    f = r.factors()
    assert 0.0 <= f["trust"] <= 1.0
    assert abs(f["interaction_tolerance"] - 0.5) < 1e-6, "0-100 → 应归一化为 0.5，而非 50"
    assert abs(f["social_confidence"] - 0.4) < 1e-6, "0-100 → 应归一化为 0.4，而非 40"
    assert all(0.0 <= v <= 1.0 for v in f.values()), "所有 consumer 因子应在 [0,1]"


def test_raw_relationship_not_passed_to_normalized_consumer():
    """对话 consumer 使用 factors() 而非 raw as_dict()（H1 §10：owner 冻结快照里归一化）。"""
    import furina.app as A
    src = open(A.__file__, encoding="utf-8").read()
    bw = src[src.index("def _brain_worker"):src.index("def _recent_memories")]
    assert "snapshot" in bw, "对话 worker 必须用冻结快照（不读 live 关系）"
    snap_src = src[src.index("def _freeze_direct_snapshot"):src.index("def _brain_worker")]
    assert "relationship.factors()" in snap_src, "冻结快照必须用归一化 factors()"


# ================================================================ D. short-term conversation buffer
def test_conversation_history_is_bounded_and_reaches_dialogue():
    from furina.dialogue_brain import DialogueBrain
    class _LLM:
        def is_available(self): return True
        def structured(self, msgs, schema=None, temperature=0.9): return {"speech": "唔。", "emotion_hint": ""}
    db = DialogueBrain(_LLM(), "p")
    for i in range(12):
        db.say(intent="talk", emotion="calm", user_text=f"第{i}句", user_initiated=True)
    hist = db.recent_turns(20)
    assert len(hist) <= db._history_limit, "历史应有界"
    assert hist[-1]["text"] == "唔。", "最后一条应为芙宁娜回复"
    # prompt 含机制引导 + 最近对话
    from furina.dialogue_brain import _dialogue_prompt_v2
    class _App:
        def to_prompt(self):
            return {"mode": "CASUAL", "secondary_mode": "", "dialogue_act": "COMMENT", "strategy": ""}
        mode = "CASUAL"; dialogue_act = "COMMENT"
    p = _dialogue_prompt_v2(_App(), intent="talk", emotion="calm", user_text="",
                            context="", memories=None, world=None, examples=[], person="p",
                            activity="idle", history=db.recent_turns(4))
    assert "说话机制" in p, "prompt 应含角色语言机制引导"
    assert "最近对话" in p, "prompt 应含最近对话上下文"


# ================================================================ F. text → interaction causality
def test_text_reject_emits_relationship_event_once():
    from types import SimpleNamespace
    from furina.app import Furina
    app = Furina.__new__(Furina)
    app.calls = {"apply": 0}
    rel = SimpleNamespace()
    orig_apply = None
    class _Rel:
        def apply(self, ev, **kw):
            app.calls["apply"] += 1
            return {}
        def __getattr__(self, n): return None
    app.relationship = _Rel()
    app.state = SimpleNamespace(state=SimpleNamespace(relationship=None))
    app._apply_user_text_fx("现在别烦我，我要专心一会。")
    assert app.calls["apply"] == 1, "明确拒绝应 exactly-once 触发关系事件"


def test_ambiguous_negative_text_does_not_false_reject():
    from types import SimpleNamespace
    from furina.app import Furina
    app = Furina.__new__(Furina)
    app.calls = {"apply": 0}
    class _Rel:
        def apply(self, ev, **kw):
            app.calls["apply"] += 1
            return {}
        def __getattr__(self, n): return None
    app.relationship = _Rel()
    app.state = SimpleNamespace(state=SimpleNamespace(relationship=None))
    app._apply_user_text_fx("这功能烦死了")   # 关于功能，不是拒绝芙宁娜 → 不触发
    assert app.calls["apply"] == 0, "关于功能的抱怨不应误判为拒绝"


# ================================================================ E. conversation → memory
def test_conversation_memory_observe():
    from types import SimpleNamespace
    from furina.app import Furina
    app = Furina.__new__(Furina)
    app.mem_observed = []
    app.memory = SimpleNamespace(observe=lambda *a, **k: app.mem_observed.append((a, k)))
    app._maybe_observe_conversation("我今晚准备把这个桌宠的功能测试做完。")
    assert len(app.mem_observed) == 1, "高置信用户信息应进入记忆候选"


def test_trivial_chat_not_blindly_persisted():
    from types import SimpleNamespace
    from furina.app import Furina
    app = Furina.__new__(Furina)
    app.mem_observed = []
    app.memory = SimpleNamespace(observe=lambda *a, **k: app.mem_observed.append((a, k)))
    app._maybe_observe_conversation("好的")
    app._maybe_observe_conversation("哈哈")
    assert len(app.mem_observed) == 0, "随意的'好的/哈哈'不应盲存"
