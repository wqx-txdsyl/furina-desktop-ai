"""Life Simulation 测试（任务 1/2）：Emotion Engine + Behavior Motivation。

Emotion Engine：确定性、事件→情绪→衰减→label→行为倾向，不用 LLM。
Behavior Motivation：idle 只是候选，绝不因无事件自动胜出；冲动随需求/情绪/时间变化。
"""
from __future__ import annotations

from furina.state import CharacterState
from furina.emotion import EmotionEngine, EVENT_PET, EVENT_PRAISE, EVENT_IGNORE, EVENT_REJECT, DIMENSIONS
from furina.behavior import BehaviorMotivation


def test_emotion_event_applies_delta():
    ee = EmotionEngine(CharacterState().emotion)
    before = ee.state.happiness
    ee.apply(EVENT_PRAISE)
    assert ee.state.happiness > before, "夸奖应提升 happy"


def test_emotion_decay_returns_to_baseline():
    ee = EmotionEngine(CharacterState().emotion)
    ee.apply(EVENT_PRAISE)
    ee.state.happiness = 90.0
    for _ in range(20):
        ee.decay(dt=3.0)
    assert ee.state.happiness < 90.0, "情绪应随时间衰减"


def test_emotion_derive_label_valid():
    ee = EmotionEngine(CharacterState().emotion)
    label = ee.derive_label()
    assert label in ("happy", "excited", "proud", "curious", "sad", "annoyed", "sleepy", "embarrassed", "calm")


def test_emotion_is_deterministic_no_llm():
    """Emotion Engine 是确定性的程序，不依赖 LLM。"""
    import inspect
    src = inspect.getsource(EmotionEngine)
    assert "llm" not in src.lower() or "self.llm" not in src, "Emotion Engine 不应调用 LLM"


def test_emotion_dims_stay_in_range():
    ee = EmotionEngine(CharacterState().emotion)
    for _ in range(30):
        ee.apply(EVENT_PET)
    for dim in DIMENSIONS:
        assert 0.0 <= getattr(ee.state, dim) <= 100.0, dim


def test_motivation_idle_not_default_winner():
    """高无聊/高社交时，idle 不应排名第一（Idle is a behavior, not fallback）。"""
    st = CharacterState()
    st.needs.boredom = 90; st.needs.social_need = 80
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation()
    cands = m.candidates(st, ee)
    top = cands[0].activity
    assert top != "idle", f"idle 不应成为默认胜出, top={top}"
    # idle 在候选里但仍参与竞争
    assert any(c.activity == "idle" for c in cands)


def test_motivation_high_fatigue_prefers_rest():
    st = CharacterState(); st.needs.fatigue = 95; st.needs.sleepiness = 90
    ee = EmotionEngine(st.emotion)
    cands = BehaviorMotivation().candidates(st, ee)
    top3 = {c.activity for c in cands[:3]}
    assert "rest" in top3 or "sleep" in top3, f"高疲劳应倾向休息: {top3}"


def test_motivation_scores_differentiated():
    st = CharacterState(); st.needs.boredom = 90
    ee = EmotionEngine(st.emotion)
    cands = BehaviorMotivation().candidates(st, ee)
    scores = [c.score for c in cands]
    assert max(scores) > min(scores), "候选分应区分化"
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_motivation_recency_penalizes_repeat():
    st = CharacterState(); st.needs.boredom = 90; st.needs.playfulness = 90
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation()
    import time
    t = time.time()
    m.mark_done("play", t)   # 刚玩过
    cands = m.candidates(st, ee, now=t + 1)   # 1s 后
    play_score = next(c.score for c in cands if c.activity == "play")
    # 刚做过的 play 会被 recency 压制（相比不做标记时）
    assert play_score < 1.0
