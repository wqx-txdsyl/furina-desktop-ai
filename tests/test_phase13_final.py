"""Phase 13 终审 — 已修复 P0 的行为测试（世界时钟 / 输入语义 / 强制多样 OFF / 未知事件不映射 click）。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from furina.core import EventBus, EventType
from furina.interaction.interaction_types import InteractionEvent, TouchKind, InteractionZone


def test_scheduler_clock_uses_hour_minute():
    """localtime()[:2] 曾是 (year, month)；必须传 (hour, minute)。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    assert "lt.tm_hour, lt.tm_min" in src, "update_clock 应传 (hour, minute)"
    assert "update_clock(*time.localtime()[:2])" not in src, "旧 bug 必须移除"


def test_world_day_period_known_times():
    from furina.world_perception import _period
    assert _period(8) == "morning"
    assert _period(13) == "afternoon"
    assert _period(20) == "evening"
    assert _period(0) == "night"


def test_grab_release_hover_leave_are_not_positive_interaction():
    """指针控制阶段（grab/release/hover/leave）不得进入生命因果：Scheduler._on_interaction 直接跳过。"""
    from furina.runtime.scheduler import Scheduler
    bus = EventBus()
    sched = Scheduler(bus, None, None, None, None, None, None)
    sched._speech = ""
    for kind in ("grab", "release", "hover", "leave"):
        ev = InteractionEvent(type=TouchKind(kind), target=InteractionZone.WHOLE)
        sched._on_interaction(type("E", (), {"payload": ev})())
        assert sched._speech == "", f"{kind} 不应产生任何正面互动（台词应为空）"


def test_unknown_interaction_not_mapped_to_click():
    """App 的 INTERACTION_INPUT 情绪映射：未知 kind 不得默认 EVENT_CLICK（行为级见 test_phase13_r1）。"""
    import furina.app as A
    src = open(A.__file__, encoding="utf-8").read()
    assert "def _on_interaction_emotion" in src, "语义映射必须在独立方法中"
    m = src[src.index("def _on_interaction_emotion"):src.index("def _tired_hint") or len(src)]
    assert "_map.get(kind, None)" in m, "未知 kind 必须映射 None"
    assert "if mapped is None:\n            return None" in m, "无映射 → 不调用 EmotionEngine"


def test_forced_diversity_production_calls_zero():
    """行为打分不再存在/调用 category/activity 惩罚与观察塌缩守卫（B4：整体移除，非仅注释）。

    旧断言（注释禁用态）已升级：评审基线 0402e7f 的 B4 要求把纯多样性惩罚**整体删除**，
    连 _category_penalty/_activity_penalty/_observation_crush_guard 定义都不保留，
    且 30/90s recency 乘子（混用假时钟/真时钟、属'刚做过所以换一个'）一并移除。
    """
    import furina.behavior.motivation as M
    src = open(M.__file__, encoding="utf-8").read()
    assert "def _category_penalty" not in src, "类别惩罚方法必须移除（B4）"
    assert "def _activity_penalty" not in src, "活动惩罚方法必须移除（B4）"
    assert "def _observation_crush_guard" not in src, "观察塌缩守卫必须移除（B4）"
    score = src[src.index("def _score"):]
    assert "base *= 0.4 if since < 30" not in score, "30/90s recency 乘子必须移除（B4，环境相关非因果）"
    assert "observation_crush_guard" not in score and "_category_penalty(" not in score \
        and "_activity_penalty(" not in score, "生产打分不得引用任何多样性惩罚"


def test_no_autonomy_stagnation_interrupt_for_quiet_idle():
    """安静 idle 不再触发 autonomy_stagnation 强制唤醒（合法安静共处）。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    kpi = src[src.index("def _monitor_kpi"):src.index("def _drive_life")]
    assert "_interrupt_life(\"autonomy_stagnation\")" not in kpi, "安静 idle 不得强制唤醒 LifeBrain"


def _motivation_top(state, history_acts=()):
    from furina.behavior import BehaviorMotivation
    from furina.emotion import EmotionEngine
    m = BehaviorMotivation()
    t = 100.0
    for a in history_acts:
        m.mark_done(a, t)
        t += 60.0
    ee = EmotionEngine(state.emotion)
    cands = m.candidates(state, ee)
    return cands[0].activity, cands[0].score


def test_unchanged_state_history_alone_does_not_force_category_switch():
    """同一状态下，**仅靠**近期历史不同不得改变 top 候选（多样性只能来自 Needs/Emotion/World…）。"""
    from furina.state import CharacterState
    st = CharacterState(); st.needs.boredom = 90; st.needs.curiosity = 80; st.needs.playfulness = 80
    a1, s1 = _motivation_top(st, history_acts=("play", "play", "play"))
    a2, s2 = _motivation_top(st, history_acts=("read", "read", "read"))
    assert a1 == a2, f"仅历史不同不得改变 top: {a1} vs {a2}"
    assert abs(s1 - s2) < 1e-6, "仅历史不同不得改变分数"


def test_repeated_read_can_remain_top_candidate():
    """反复做 read 后，read 仍可保持 top（无多样性惩罚强制换类）。"""
    from furina.state import CharacterState
    st = CharacterState(); st.needs.curiosity = 90; st.needs.boredom = 80
    top, _ = _motivation_top(st, history_acts=("read", "read", "read", "read", "read"))
    assert top == "read", f"read 不应因做过多次被强制换掉: {top}"


def test_observation_ratio_does_not_boost_unrelated_categories():
    """观察占比高不得因此抬高其它类别（observation crush guard 已禁用）。"""
    from furina.state import CharacterState
    st = CharacterState(); st.needs.boredom = 90; st.needs.curiosity = 80
    hist = ["observe_user", "observe_work", "watch_user", "observe_user", "observe_work"] * 2
    top, _ = _motivation_top(st, history_acts=hist)
    assert top in ("play", "explore", "read"), f"观察历史不得把无关类别抬成 top: {top}"


def test_life_decision_does_not_write_emotion_truth():
    """§4.5：LifeDecision 的 emotion 只是表达提示，不得覆盖 EmotionEngine 拥有的 label。"""
    from types import SimpleNamespace
    from furina.app import Furina
    from furina.state.state_model import CharacterState
    from furina.director.action_queue import ActionRequest

    app = object.__new__(Furina)            # 跳过 __init__，只测 _on_execute
    app.state = SimpleNamespace(state=CharacterState())
    app.state.state.emotion.label = "calm"  # EmotionEngine 权威值
    req = ActionRequest(source="behavior", action="read", priority=60,
                        reason="calm reading", payload={"emotion": "happy"})
    app._on_execute(req)
    # 权威情绪不被 LifeDecision 覆盖
    assert app.state.state.emotion.label == "calm"
    # 表达/行为提示落到非权威槽 Intent.emotion
    assert app.state.state.intent.emotion == "happy"


def test_memory_behavior_hint_canonical_units():
    """§13：behavior_hint 必须消费 canonical 0..1 factors；raw principal=1 不得再触发偏置。"""
    from types import SimpleNamespace
    from furina.memory.memory_engine import MemoryEngine

    me = MemoryEngine.__new__(MemoryEngine)   # 跳过 __init__（不碰 DB）
    me.relationship = None
    me.store = SimpleNamespace(insert=lambda m: None, query=lambda limit=8: [])
    me.bus = SimpleNamespace(emit=lambda *a, **k: None)

    def _hint(comfort, annoyance):
        me.relationship = SimpleNamespace(comfort=comfort, annoyance=annoyance)
        b = me.behavior_hint(context="")
        me.relationship = None
        return b

    # raw comfort=1 (0.01 归一化) 不得触发 approach_bonus —— 旧 bug 复现点
    assert "approach_bonus" not in _hint(1, 1)
    # raw comfort=90 (>0.6) 触发 approach_bonus
    assert _hint(90, 1).get("approach_bonus") == 20
    # raw annoyance=90 (>0.6) 触发 social_penalty
    assert _hint(1, 90).get("social_penalty", 0) >= 70
