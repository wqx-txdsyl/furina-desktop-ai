"""Phase 13C C-R1 Closeout 测试（精确数值 / 单一 route / 无强制多样 / 平滑路径 / 契约单位）。"""
from __future__ import annotations

import os
import random
import re
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from furina.runtime.world import DesktopWorld, Rect
from furina.runtime.spatial import SpatialIntentResolver, DesktopSpatialRuntime, SpatialPoint
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.frame import FrameBody
from furina.relationship.engine import RelationshipEngine
from furina.memory.memory_types import RelationshipState


# ================================================================ C-R1.1 Life autonomy
def test_production_no_forced_variety():
    """decide() 不再调用 _apply_variety / 任何 repeat guard（仅保留方法作为 debt）。"""
    import furina.life_brain as LB
    src = open(LB.__file__, encoding="utf-8").read()
    decide = src[src.index("def decide("):src.index("def _candidate_space")]
    assert "self._apply_variety" not in decide, "生产 decide() 不应调用 _apply_variety"
    assert "repeat guard" not in decide
    # prompt 不再强制"为多样改选择"
    prompt = src[src.index("def _life_prompt"):]
    assert "刻意选一个**不同类别**" not in prompt, "prompt 不应要求刻意换类别"
    assert "别连续 2 次" not in prompt and "最近已经在做的事别一直重复" not in prompt


def test_repeated_reasonable_activity_allowed():
    """同一个合理 activity 连续两次允许保留（read→read 合法）。"""
    from furina.life_brain import LifeBrain
    class _Adapter:
        @staticmethod
        def is_available(): return True
        @staticmethod
        def structured(msgs, schema=None, temperature=0.6):
            return {"activity": "read", "emotion": "calm", "intent": "继续看书", "duration": 60,
                    "interruptible": True, "exit_conditions": [], "next_think_in": 90,
                    "dialogue_needed": False, "tool_needed": False, "reason": "r"}
    lb = LifeBrain(_Adapter())
    from furina.state import CharacterState
    st = CharacterState()
    d1 = lb.decide(state=st, force=True)
    d2 = lb.decide(state=st, force=True)
    assert d1.activity == "read" and d2.activity == "read", "连续 read 应被允许（不因多样强制换）"


def test_next_think_not_truncated():
    """LifeBrain 透传真实 next_think；Scheduler 是唯一 clamp owner。"""
    import furina.life_brain as LB
    import furina.runtime.scheduler as S
    lsrc = open(LB.__file__, encoding="utf-8").read()
    sched_src = open(S.__file__, encoding="utf-8").read()
    sch = lsrc[lsrc.index("def _apply_schedule"):lsrc.index("def next_think_in")]
    assert "max(8.0" not in sch and "min(float(d.next_think_in), 45" not in sch, "LifeBrain 不应再 8..45 clamp"
    # Scheduler 有唯一安全 clamp
    assert "def _life_think_interval" in sched_src


# ================================================================ C-R1.2 relationship scale
def test_relationship_factors_exact_numeric():
    st = RelationshipState()
    st.trust = 50.0        # raw 0-100
    st.comfort = 70.0
    st.annoyance = 20.0
    st.user_response_rate = 0.5   # raw 0..1
    st.user_rejection_rate = 0.0
    st.interaction_tolerance = 50.0
    st.social_confidence = 40.0
    f = RelationshipEngine(st).factors()
    assert abs(f["trust"] - 0.5) < 1e-9, f"trust(50 raw→normalized .5)，实际 {f['trust']}"
    assert abs(f["comfort"] - 0.7) < 1e-9
    assert abs(f["annoyance"] - 0.2) < 1e-9
    assert abs(f["user_response_rate"] - 0.5) < 1e-9, "response_rate 0.5（0..1）应保持 0.5"
    assert abs(f["interaction_tolerance"] - 0.5) < 1e-9, "tolerance 50(0-100) → 0.5"
    assert abs(f["social_confidence"] - 0.4) < 1e-6, "confidence 40(0-100) → 0.4"


def test_annoyance_07_triggers_06_path():
    """annoyance .7 能触发 >.6 的高烦路径（memory_engine 阈值，canonical 0..1）。"""
    import furina.memory.memory_engine as ME
    src = open(ME.__file__, encoding="utf-8").read()
    assert 'f.get("annoyance", 0.0) > 0.6' in src, "memory_engine 应消费 canonical factors 的 0.6 阈值"
    assert "annoyance > 60" not in src, "不应再用 60"
    assert "rel.annoyance > 0.6" not in src, "不应再直接读原始 principal 属性（unit debt）"


def test_all_dialogue_callsites_normalized():
    """Dialogue consumer 一律 factors()（app/scheduler 源码）—— 不再 state.as_dict() 裸露。"""
    import furina.app as A
    import furina.runtime.scheduler as S
    for m in (A, S):
        src = open(m.__file__, encoding="utf-8").read()
        # relationship 传给 DialogueBrain.say 处应有 .factors()
        assert "relationship.factors()" in src or "_rel_factors()" in src, f"{m.__name__} 应使用归一化 factors()"


def test_raw_relationship_not_in_dialogue_consumer():
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    # 原来的 Dialogue say 里 relationship=...as_dict... 已移除
    assert "relationship=self._rel_factors()" in src


# ================================================================ C-R1.3 conversation context dedup
def test_current_user_appears_once_in_prompt():
    from furina.dialogue_brain import DialogueBrain, _dialogue_prompt_v2
    class _LLM:
        def is_available(self): return True
        def structured(self, msgs, schema=None, temperature=0.9): return {"speech": "好。", "emotion_hint": ""}
    db = DialogueBrain(_LLM(), "p")
    # 先有一轮历史
    db.say(intent="talk", emotion="calm", user_text="第一个问题", user_initiated=True)
    class _App:
        def to_prompt(self):
            return {"mode": "CASUAL", "secondary_mode": "", "dialogue_act": "COMMENT", "strategy": ""}
        mode = "CASUAL"; dialogue_act = "COMMENT"
    hist = db.recent_turns(4)
    user_msg = "现在你在干嘛？"
    p = _dialogue_prompt_v2(_App(), intent="talk", emotion="calm", user_text=user_msg,
                            context="", memories=None, world=None, examples=[], person="p",
                            activity="read", history=hist)
    assert p.count(user_msg) == 1, "当前 user 在 prompt 中应只出现一次（history excl current turn）"
    # history 应不含当前 user（hist 是上一轮之后的）
    assert all(h["text"] != user_msg for h in hist)


# ================================================================ C-R1.4 memory source
def test_conversation_memory_source():
    from types import SimpleNamespace
    from furina.app import Furina
    app = Furina.__new__(Furina)
    app.captured = []
    app.memory = SimpleNamespace(observe=lambda *a, **k: app.captured.append((a, k)))
    app._maybe_observe_conversation("我今晚准备把这个桌宠的功能测试做完。")
    assert app.captured and app.captured[0][1].get("source").value == "conversation", \
        "记忆 source 应为 CONVERSATION"


# ================================================================ C-R1.6 example routing
def test_example_selector_routes_act_to_context():
    from furina.dialogue_brain import DialogueBrain
    from furina.persona.expression_examples import get_examples
    db = DialogueBrain.__new__(DialogueBrain)
    pool = {e["context"]: e for e in get_examples()}
    # question_activity
    class _App:
        mode = "CASUAL"; dialogue_act = "RESPONSE_TO_QUESTION"
    sel = db._select_examples(_App(), emotion="calm", activity="idle", user_text="你在干嘛？")
    assert "question_activity" in [e["context"] for e in sel], "问答应命中 question_activity 例子"
    # rejection
    class _App2:
        mode = "CASUAL"; dialogue_act = "DECLINE"
    sel2 = db._select_examples(_App2(), emotion="calm", activity="idle", user_text="别烦我")
    assert "rejection" in [e["context"] for e in sel2], "拒绝应命中 rejection 例子"
    # agent_success
    class _App3:
        mode = "CASUAL"; dialogue_act = "COMMENT"
    sel3 = db._select_examples(_App3(), emotion="calm", activity="agent_report", user_text="")
    assert "agent_success" in [e["context"] for e in sel3], "Agent 完成应命中 agent_success 例子"


def test_examples_have_no_stage_actions():
    from furina.persona.expression_examples import get_examples
    for e in get_examples():
        assert not re.search(r"（(合上书|皱眉|想了想|叹气|笑|安静地看)）", e["speech"]), \
            f"example 不应含舞台动作: {e['speech']}"


# ================================================================ C-R1.7 spatial smooth
def test_curved_approach_is_smooth():
    world = DesktopWorld(1920, 1080); world.taskbar_height = 48.0
    world.update_active_window(Rect(600, 200, 700, 600))
    rt = DesktopSpatialRuntime(world, rng=random.Random(1))
    rt.set_initial_foot(200, 900)
    d = SpatialIntentResolver().resolve(RuntimeFrameBuilder().build(
        activity_name="approach_user", body=FrameBody(posture="standing"), motion_intent="APPROACH"))
    plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
    assert plan is not None and len(plan.waypoints) >= 8, f"curve 应密集采样，实际 {len(plan.waypoints)}"
    # 方向变化连续（无尖锐折角）：相邻 waypoint heading 最大变化角 < 45°
    pts = [rt.state.position] + list(plan.waypoints) + [plan.target]
    import math
    max_turn = 0.0
    for i in range(2, len(pts)):
        a = math.atan2(pts[i-1].y - pts[i-2].y, pts[i-1].x - pts[i-2].x)
        b = math.atan2(pts[i].y - pts[i-1].y, pts[i].x - pts[i-1].x)
        d_ang = abs((b - a + math.pi) % (2 * math.pi) - math.pi)
        max_turn = max(max_turn, math.degrees(d_ang))
    assert max_turn < 45.0, f"curve 不应有尖锐折角（max_turn={max_turn:.1f}°）"


def test_wander_targets_not_fixed_grid():
    """多次 wander 目标经 jitter，不应都落在固定 12 个网格点。"""
    world = DesktopWorld(1920, 1080); world.taskbar_height = 48.0
    world.update_active_window(Rect(600, 200, 700, 600))
    seen = set()
    for seed in range(8):
        rt = DesktopSpatialRuntime(world, rng=random.Random(1000 + seed))
        rt.set_initial_foot(800, 450)
        d = SpatialIntentResolver().resolve(RuntimeFrameBuilder().build(
            activity_name="wander", body=FrameBody(posture="standing"), motion_intent="NONE"))
        plan = rt.planner.plan(d, rt.state.position, rt.adapter.char_w, rt.adapter.char_h)
        if plan:
            seen.add((round(plan.target.x), round(plan.target.y)))
    assert len(seen) >= 4, f"wander 应产生多样的（非固定网格）目标，实际 {len(seen)} 个"
