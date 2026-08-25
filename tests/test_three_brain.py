"""三脑架构测试（legacy-plan/8 修正：LifeBrain 决策 / DialogueBrain 语言 / ToolAgent 双手 严格隔离）。

核心回归：sleep 是**行为**不是终态 —— LifeBrain 决策必须带 next_think_in + exit_conditions，
且可返回 continue（避免翻车），以及 LLM 不可用时能本地 fallback（A-13）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from furina.llm import LLMAdapter, LLMMessage, LLMResult
from furina.state import CharacterState, MacroState
from furina.life_brain import LifeBrain, LifeDecision, LIFE_ACTIVITIES
from furina.dialogue_brain import DialogueBrain


class FakeAdapter(LLMAdapter):
    provider = "fake"

    def __init__(self, structured_result: Optional[Dict[str, Any]] = None, available: bool = True):
        self._res = structured_result or {}
        self._available = available

    def chat(self, messages, *, temperature=None, max_tokens=None) -> LLMResult:
        return LLMResult(text="ok")

    def structured(self, messages, *, schema=None, temperature=None) -> Dict[str, Any]:
        return self._res

    def is_available(self) -> bool:
        return self._available


# ---------------------------------------------------------------- LifeBrain
def test_life_decision_requires_terminating_fields():
    """任何 LifeDecision 都必须带 continue/exit/next_think，确保 sleep 等不是终态。"""
    d = LifeBrain._coerce({
        "activity": "sleep", "emotion": "sleepy", "intent": "恢复",
        "duration": 600, "interruptible": True, "exit_conditions": ["morning", "user_touch"],
        "next_think_in": 300, "dialogue_needed": False, "tool_needed": False, "reason": "困",
    })
    assert d.activity == "sleep" and d.next_think_in >= 5
    assert d.exit_conditions, "sleep 必须带退出条件（否则会睡死）"
    assert d.is_continue is False


def test_life_continue_is_noop_activity():
    d = LifeDecision(activity="continue", reason="仍然合适", next_think_in=90)
    assert d.is_continue is True


def test_life_schema_enums():
    assert "sleep" in LIFE_ACTIVITIES and "continue" in LIFE_ACTIVITIES


def test_life_decide_uses_structured_and_clamps():
    fake = FakeAdapter({"activity": "observe_user", "emotion": "curious", "intent": "陪用户",
                        "duration": 300, "interruptible": True, "exit_conditions": ["user_stops"],
                        "next_think_in": 120, "dialogue_needed": False, "tool_needed": False,
                        "reason": "用户在工作"})
    lb = LifeBrain(fake)
    st = CharacterState()
    st.clock_hour = 9
    st.user_working = True    # 用户工作 → observe_user 才合理，不被 variety 打破
    st.life.activity = "idle"; st.intent.action = "idle"
    d = lb.decide(state=st, force=True)
    assert d.activity == "observe_user"


def test_life_invalid_activity_clamped_to_idle():
    # 非法 activity 必须被钳到合法枚举（_coerce 层），不崩。
    fake = FakeAdapter({"activity": "fly_to_moon", "emotion": "curious", "intent": "x",
                        "duration": 1, "interruptible": True, "exit_conditions": [],
                        "next_think_in": 10, "dialogue_needed": False, "tool_needed": False, "reason": "r"})
    out = LifeBrain._coerce({"activity": "fly_to_moon", "emotion": "curious", "intent": "x",
                             "duration": 1, "interruptible": True, "exit_conditions": [],
                             "next_think_in": 10, "dialogue_needed": False, "tool_needed": False, "reason": "r"})
    assert out.activity == "idle"


def test_life_next_think_not_truncated_to_45():
    """C-R1.1：LifeBrain **不再**把 next_think 截断到 8~45（那是强制的"生命节拍器"，掩盖自主感）。
    真实值透传；统一安全 clamp 归属 Scheduler（单一 owner）。这里验证 LLM 的 60000 不被偷偷改成 45。"""
    fake = FakeAdapter({"activity": "rest", "emotion": "calm", "intent": "歇",
                        "duration": 120, "interruptible": True, "exit_conditions": [],
                        "next_think_in": 60000, "dialogue_needed": False, "tool_needed": False, "reason": "r"})
    lb = LifeBrain(fake)
    st = CharacterState()
    d = lb.decide(state=st, force=True)
    assert d.next_think_in == 60000, f"LifeBrain 应透传真实 next_think（不截断到45），实际 {d.next_think_in}"


def test_life_decide_returns_real_activity_not_bare_continue():
    """去除了“未到时间就返回裸 continue”的锁死：第二次决策也应给真实活动。"""
    fake = FakeAdapter({"activity": "think", "emotion": "thoughtful", "intent": "想点事",
                        "duration": 60, "interruptible": True, "exit_conditions": [],
                        "next_think_in": 30, "dialogue_needed": False, "tool_needed": False, "reason": "r"})
    lb = LifeBrain(fake)
    st = CharacterState()
    st.life.activity = "idle"; st.intent.action = "idle"
    d1 = lb.decide(state=st, force=True)
    d2 = lb.decide(state=st, force=False)   # 不应再因“未到期”吞成 continue
    assert d1.activity in ("think", "rest")   # LLM 给 think；也许是 rest
    assert d2.activity != "continue" or d2.is_continue is False


def test_life_fallback_without_llm_keeps_sleep_terminating():
    """A-13：LLM 不可用 → 本地 fallback，且 sleep 仍带 next_think/exit（不是死睡）。"""
    lb = LifeBrain(FakeAdapter(available=False))
    st = CharacterState()
    st.clock_hour = 23
    st.needs.sleepiness = 95
    st.needs.fatigue = 85
    d = lb.decide(state=st, force=True)
    assert d.activity == "sleep"
    assert d.next_think_in >= 5 and d.exit_conditions, "fallback 的 sleep 也必须可退出"


# ---------------------------------------------------------------- DialogueBrain（只产语言）
def test_dialogue_returns_speech_only():
    fake = FakeAdapter({"speech": "你累了吧？歇会儿~"})
    db = DialogueBrain(fake)
    out = db.say(intent="observe_user", emotion="concerned", user_text="好累")
    assert isinstance(out, str) and out == "你累了吧？歇会儿~"


def test_dialogue_does_not_decide_intent():
    """DialogueBrain 输入 intent 只用于措辞，不返回决策对象。"""
    fake = FakeAdapter({"speech": "嗯。"})
    db = DialogueBrain(fake)
    out = db.say(intent="sleep", emotion="sleepy")
    assert isinstance(out, str)   # 只有字符串台词
    assert "intent" not in out and "activity" not in out


# ---------------------------------------------------------------- Life → Macro 映射（三脑把 Life 交给 Runtime）
def test_life_activity_maps_to_macro():
    from furina.runtime.scheduler import _macro_for
    assert _macro_for("sleep") == MacroState.SLEEPING
    assert _macro_for("rest") == MacroState.RESTING
    assert _macro_for("observe_user") == MacroState.WORKING
    assert _macro_for("idle") == MacroState.IDLE


# ---------------------------------------------------------------- 生物需求护栏（决定“不能忽视需求”）
def test_need_guard_hunger_overrides_weak_choice():
    st = CharacterState(); st.clock_hour = 14; st.needs.hunger = 80
    g = LifeBrain._apply_need_guard(st, LifeDecision(activity="rest"))
    assert g.activity == "eat"


def test_need_guard_late_night_sleep():
    st = CharacterState(); st.clock_hour = 23; st.needs.sleepiness = 90
    g = LifeBrain._apply_need_guard(st, LifeDecision(activity="observe_user"))
    assert g.activity == "sleep"
    assert g.exit_conditions and g.next_think_in >= 5   # sleep 非终态


def test_need_guard_bored_play():
    st = CharacterState(); st.clock_hour = 15; st.needs.boredom = 85
    st.needs.energy = 80; st.needs.hunger = 20; st.needs.sleepiness = 10
    g = LifeBrain._apply_need_guard(st, LifeDecision(activity="observe_user"))
    assert g.activity == "play"


def test_need_guard_calm_keeps_choice():
    st = CharacterState(); st.clock_hour = 15; st.needs.hunger = 20
    st.needs.sleepiness = 10; st.needs.boredom = 30
    g = LifeBrain._apply_need_guard(st, LifeDecision(activity="idle"))
    assert g.activity == "idle"


# ---------------------------------------------------------------- 懒惰 continue 重决策（“不切换”根治）
def test_lazy_continue_forced_to_real_decision():
    st = CharacterState(); st.clock_hour = 14; st.needs.hunger = 80
    if LifeBrain._force_real_decision(st, {}).activity == "eat":
        pass   # 依赖 world 快照，这里只验证它能给非 continue 的答案
    assert LifeBrain._force_real_decision(st, {}).activity != "continue"


# ---------------------------------------------------------------- 活动 → 具体身体姿态（80 素材被用上）
def test_pose_for_activity_gives_distinct_assets():
    from furina.runtime.scheduler import pose_for_activity
    seen = set()
    for a in ["idle", "observe_user", "eat", "drink", "play", "sleep", "rest"]:
        p, emo, gaze, act = pose_for_activity(a)
        # 不同活动回到不同的 (posture, action) 组合，避免永远同一种站姿
        seen.add((p, act))
    assert len(seen) >= 5, f"活动应映射到不同姿态组合，实际={seen}"


# ---------------------------------------------------------------- 主动生活感（打破 idle 锁）
def test_variety_breaks_idle_lock():
    """连续重复发呆型活动会切到主动行为（talk/approach/play…），否则像静止人像。"""
    from furina.life_brain import LIFE_ACTIVITIES, SELF_ACTIVITIES, SOCIAL_ACTIVITIES
    lb = LifeBrain(FakeAdapter())
    lb._repeat = 1          # 再同一次就达 2 → 打破
    st = CharacterState(); st.user_working = False
    st.life.activity = "idle"; st.intent.action = "idle"
    d = lb._apply_variety(st, LifeDecision(activity="idle", reason="test"))
    assert d.activity in LIFE_ACTIVITIES
    assert d.activity != "idle", "必须打破 idle，切换到真实行为"


def test_variety_breaks_any_same_activity():
    """任何非生存活动连续 2 次都会被打破（避免卡在 approach_user/observe_user 等）。"""
    from furina.life_brain import LIFE_ACTIVITIES
    lb = LifeBrain(FakeAdapter())
    lb._repeat = 1          # 再同一次就达 2 → 打破
    st = CharacterState(); st.user_working = True
    st.life.activity = "approach_user"; st.intent.action = "approach_user"
    d = lb._apply_variety(st, LifeDecision(activity="approach_user", reason="test"))
    assert d.activity in LIFE_ACTIVITIES
    assert d.activity != "approach_user", "必须打破卡住的同一活动"


def test_variety_preserves_strong_need():
    """强需求（eat/sleep）不被 variety 打断。"""
    lb = LifeBrain(FakeAdapter())
    st = CharacterState(); st.needs.hunger = 20
    d = lb._apply_variety(st, LifeDecision(activity="sleep"))
    assert d.activity == "sleep"


# ---------------------------------------------------------------- 互动机会评分 + 注意力预算（任务书 §21-22）
def _attach_valid_world(st, idle=10.0):
    """Pre-Manual：有效 OS 空闲样本（idle_available=True）→ 在场已知。"""
    from furina.world_perception import WorldPerception
    wp = WorldPerception()
    wp.update(app="code", title="", idle_seconds=idle, hour=st.clock_hour, minute=0, idle_available=True)
    st.world = wp
    return st


def test_interaction_opportunity_scoring():
    """§21：用户忙→低分；闲→高分；深夜→更低。"""
    lb = LifeBrain(FakeAdapter())
    st = _attach_valid_world(CharacterState()); st.clock_hour = 14; st.user_working = True
    assert lb.interaction_opportunity(st) < 50, "用户忙应低机会"
    st2 = _attach_valid_world(CharacterState()); st2.clock_hour = 14; st2.user_working = False
    assert lb.interaction_opportunity(st2) > 50, "用户闲应高机会"
    st3 = _attach_valid_world(CharacterState()); st3.clock_hour = 23; st3.user_working = False
    assert lb.interaction_opportunity(st3) < lb.interaction_opportunity(st2), "深夜应更低"


def test_attention_budget_regen_and_spend():
    """§22：预算耗尽可能被恢复；预算低时 variety 倾向自主活动而非社交。"""
    lb = LifeBrain(FakeAdapter())
    assert lb.budget == 12.0
    lb.spend_budget(6.0)
    assert lb.budget == 6.0
    old = lb.budget
    lb.regen_budget(per_sec=0.05)
    assert lb.budget >= old
    # 预算耗尽 → variety 不再选社交（只自主）
    lb._budget = 0.0
    st = CharacterState(); st.user_working = False
    for _ in range(5):
        d = lb._apply_variety(st, LifeDecision(activity="idle"))
        from furina.life_brain import SOCIAL_ACTIVITIES, SELF_ACTIVITIES
        assert d.activity not in SOCIAL_ACTIVITIES, f"预算低仍选社交: {d.activity}"


def test_snapshot_includes_interaction_opportunity():
    lb = LifeBrain(FakeAdapter())
    st = CharacterState(); st.clock_hour = 12; st.user_working = False
    snap = lb.build_snapshot(st)
    assert "interaction_opportunity" in snap
    assert "relationship" in snap and "interaction_tolerance" in snap["user"]


# ---------------------------------------------------------------- 关系驱动 + 用户自适应（任务书 §18, §23）
def test_adapt_tolerance_up_on_response_down_on_ignore():
    lb = LifeBrain(FakeAdapter())
    lb.adapt_tolerance(user_responded=True, was_interactive=True)
    assert lb.tolerance > 50, "用户积极回应应提高接纳度"
    lb2 = LifeBrain(FakeAdapter())
    # 多次被忽略 → 接纳度下降
    for _ in range(8):
        lb2.adapt_tolerance(user_responded=False, was_interactive=True)
    assert lb2.tolerance < 50, "多次被忽略应降低接纳度"


def test_low_tolerance_reduces_social_proactivity():
    from furina.life_brain import SOCIAL_ACTIVITIES
    lb = LifeBrain(FakeAdapter())
    st = CharacterState(); st.user_working = False
    # 高接纳度 → 至少有时会选社交
    lb._tolerance = 90.0; lb._budget = 12.0
    seen_social = False
    for _ in range(20):
        d = lb._apply_variety(st, LifeDecision(activity="idle"))
        if d.activity in SOCIAL_ACTIVITIES:
            seen_social = True; break
    assert seen_social, "高接纳度应有机会选社交行为"
    # 极低接纳度 → 只自主，不社交
    lb2 = LifeBrain(FakeAdapter()); lb2._tolerance = 10.0; lb2._budget = 12.0
    for _ in range(20):
        d = lb2._apply_variety(st, LifeDecision(activity="idle"))
        assert d.activity not in SOCIAL_ACTIVITIES, f"低接纳度仍选社交: {d.activity}"


def test_high_annoyance_reduces_proactivity():
    from furina.memory.memory_types import RelationshipState
    st = _attach_valid_world(CharacterState()); st.clock_hour = 14; st.user_working = False
    lb = LifeBrain(FakeAdapter())
    lb._budget = 12.0
    lb._relationships_memory = RelationshipState()
    base = lb.interaction_opportunity(st)
    lb._relationships_memory.annoyance = 80
    assert lb.interaction_opportunity(st) < base, "高厌烦应降低互动机会"


def test_relationship_drive_leans_social_when_comfortable():
    lb = LifeBrain(FakeAdapter())
    tr = lb.relationship_traits()
    assert "familiarity" in tr and "annoyance" in tr
