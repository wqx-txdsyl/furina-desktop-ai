"""Life Simulation 闭环测试：经历→状态反馈 打破机械重复（anti-collapse OFF 也成立）。"""
from __future__ import annotations

import random
from collections import Counter

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation
from furina.behavior.outcome import apply_outcome, outcome_for
from furina.behavior.motivation import CATEGORY


def _longest(seq):
    mx = cur = 1
    for i in range(1, len(seq)):
        cur = cur + 1 if seq[i] == seq[i-1] else 1
        mx = max(mx, cur)
    return mx


def _closure_run(steps=40, scenario="none", anti=False, time_drift=True, rng=None):
    rng = rng or random.Random(7)
    st = CharacterState(); st.clock_hour = 14
    if scenario == "bored":
        st.needs.boredom = 92; st.needs.playfulness = 88
    elif scenario == "social":
        st.needs.social_need = 95
    ee = EmotionEngine(st.emotion)
    mot = BehaviorMotivation()
    acts = []; bor = []
    for _ in range(steps):
        cands = mot.candidates(st, ee)
        pick = rng.choices(cands[:4], weights=[max(0.05, c.score) for c in cands[:4]], k=1)[0]
        act = pick.activity
        apply_outcome(st, act, ee, relationship=None)   # 经历→状态反馈（真实闭环）
        if time_drift:
            st.needs.boredom = min(100, st.needs.boredom + 3.0)
            st.needs.social_need = min(100, st.needs.social_need + 2.0)
            st.needs.energy = max(0, st.needs.energy - 2.0)
            st.needs.clamp()
        acts.append(act); bor.append(round(st.needs.boredom))
        if not anti:
            mot._last_done.clear(); mot._activity_history = []; mot._category_history = []
        else:
            mot.mark_done(act, 0)
    return acts, bor


def test_activity_changes_need():
    """因果：做 play 真的降低 boredom（经历→状态反馈）。"""
    st = CharacterState(); st.needs.boredom = 90
    ee = EmotionEngine(st.emotion)
    apply_outcome(st, "play", ee)
    assert st.needs.boredom < 90, "play 应降低 boredom"


def test_failure_grants_half():
    """失败/中断反馈：success=False 时收益减半（不假装完成）。"""
    st = CharacterState(); st.needs.hunger = 80
    ee = EmotionEngine(st.emotion)
    apply_outcome(st, "eat", ee, success=True)
    full = st.needs.hunger
    st2 = CharacterState(); st2.needs.hunger = 80
    apply_outcome(st2, "eat", ee, success=False)
    half = st2.needs.hunger
    # 完成 eat 降更多,中断只降一半
    assert full < half, "中断(失败)不应获得完整收益"


def test_time_drift_no_monotonic_without_anti():
    """anti-collapse OFF + 时间回归：不做 explore→play→explore→play 单调（闭环打破机械重复）。"""
    for scenario in ["none", "bored", "social"]:
        acts, _bor = _closure_run(scenario=scenario, anti=False, time_drift=True)
        c = Counter(acts)
        # 关键:不应只有 2 种活动(调度器式),且同活动连击有限
        # (允许≤5:当某个需求(如无聊)真正主导时,play/explore 连续合理——这是"需求驱动",非 anti 强制)
        assert len(c) >= 5, f"{scenario} 活动太单一: {dict(c.most_common(4))}"
        assert _longest(acts) <= 5, f"{scenario} 机械重复连击过大(调度器式): {_longest(acts)}"


def test_closure_produces_lifecycle():
    """典型闭环:高无聊→play→boredom↓→play 动机下降→其它行为接管。"""
    st = CharacterState(); st.needs.boredom = 92; st.needs.playfulness = 88
    ee = EmotionEngine(st.emotion)
    mot = BehaviorMotivation()
    # 第一次(高无聊):play 应高
    first = mot.candidates(st, ee)[:3]
    # 做几次 play 并应用反馈
    for _ in range(4):
        apply_outcome(st, "play", ee)
        st.needs.boredom = min(100, st.needs.boredom + 3)   # 时间回归
        st.needs.clamp()
    after = mot.candidates(st, ee)[:3]
    # 做完 play 后,boredom 下降,play 不应仍是唯一最高
    assert st.needs.boredom < 92, "play 应降低 boredom"
    assert any(c.activity != "play" for c in after[:2]), "做完 play 后应有其它行为接管"
