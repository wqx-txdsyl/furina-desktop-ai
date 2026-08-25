"""闭环动力学健康测试（任务 §5）：anti-collapse OFF 时需求能自我维持、不粘死、轮流驱动行为。

用真实 update_needs（稳态再生）+ outcome（diminishing returns）+ Motivation 跑长模拟，
验证：
 1. 需求不长期贴 0 或 100（有恢复/再积累）
 2. 不同需求随时间轮流成为行为驱动（need takeover）
 3. 行为满足需求后需求下降（因果）
"""
from __future__ import annotations

import random
from collections import Counter

from furina.core import EventBus
from furina.state import CharacterState
from furina.state.state_engine import StateEngine
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation
from furina.behavior.outcome import apply_outcome, outcome_for
from furina.behavior.motivation import CATEGORY

random.seed(42)
NEEDS = ["boredom", "playfulness", "fatigue", "social_need", "curiosity"]


def _sim(minutes=480, dt=30.0):
    # Phase 13 终审 §3：需求漂移改为分钟级产品时间常数后，**2 小时窗口不足以观察完整生理/驱动周期**
    # （旧 120 分钟 + 每秒漂移 = 被证明错误的时间流逝感：工作 2 分钟疲劳即 ~100）。
    # 现在按 8 小时（480 分钟）真实共处尺度模拟，需求才经历 积累→满足→再积累 的完整周期。
    se = StateEngine(EventBus())
    st = se.state; st.clock_hour = 14
    ee = EmotionEngine(st.emotion); mot = BehaviorMotivation()
    steps = int(minutes * 60 / dt)
    trace = {k: [] for k in NEEDS}; acts = []
    for i in range(steps):
        working = (int(i * dt / (30 * 60)) % 2 == 0)
        se.update_needs(dt, working, 0 if (i % 60 < 20) else 300)
        ee.decay(dt=dt); ee.derive_label()
        cands = mot.candidates(st, ee)
        pick = random.choices(cands[:4], weights=[max(0.05, c.score) for c in cands[:4]], k=1)[0]
        apply_outcome(st, pick.activity, ee, recent_counts=None)
        mot.mark_done(pick.activity, 0)
        for k in NEEDS:
            trace[k].append(getattr(st.needs, k))
        acts.append(pick.activity)
    return trace, acts


def test_needs_not_stuck_zero_or_full():
    """需求不长期贴 0 或 100（动态稳态，非枯竭/饱和）。"""
    trace, _ = _sim(480)  # Phase 13 §3：8h 人类尺度（旧 120min 编码了被证伪的时间流逝感）
    n = len(trace["boredom"])
    for k in NEEDS:
        s = trace[k]
        at_zero = sum(1 for v in s if v <= 5) / n
        at_full = sum(1 for v in s if v >= 95) / n
        # 允许偶发，但不应长期粘死（< 50%）
        assert at_zero < 0.5, f"{k} 长期贴0: {at_zero:.0%}"
        assert at_full < 0.5, f"{k} 长期贴100: {at_full:.0%}"


def test_needs_oscillate():
    """需求应随时间起伏（有积累→满足→再积累），而非单调。

    Phase 13 终审 §3 说明：驱动型需求（boredom/social）有**封顶 peak**（58-78，不贴 100），
    因此自然振荡带是 (peak − 行为释放量) ~ peak：
      - boredom 带宽 ~55-72（spread ≈ 15-20）
      - fatigue 从基线涨到高值（8h 工作）+ 休息回落（spread 大）
      - social_need 16-78（spread ≈ 60）
    旧断言"每种 >25"编码的是被证伪的时间流逝感（分钟级全饱和），不再适用。
    """
    trace, _ = _sim(480)  # Phase 13 §3：8h 人类尺度（旧 120min 编码了被证伪的时间流逝感）
    # §6 单次结算后 social 带宽 ~16-78（spread≈60 上下波动到 ~39）；阈值取 35
    expect = {"boredom": 12.0, "fatigue": 40.0, "social_need": 35.0}
    for k, min_spread in expect.items():
        s = trace[k]
        spread = max(s) - min(s)
        assert spread > min_spread, \
            f"{k} 变化过小 {spread:.0f}（期望 > {min_spread:.0f}），说明需求没在积累/满足"


def test_anti_off_still_diverse():
    """anti-collapse OFF：行为仍多样（需求系统自身维持多样性）。"""
    _, acts = _sim(480)  # Phase 13 §3：8h 人类尺度（旧 120min 编码了被证伪的时间流逝感）
    c = Counter(acts)
    assert len(c) >= 6, f"anti OFF 下活动太单一: {dict(c.most_common(5))}"
    cats = Counter(CATEGORY.get(a) for a in acts)
    assert cats.get("SELF", 0) > 0, "应有自主生活行为"


def test_need_takeover():
    """不同内部需求应轮流成为行为驱动（fatigue→rest, sleepiness→sleep 等）。"""
    trace, acts = _sim(480)  # Phase 13 §3：8h 人类尺度（旧 120min 编码了被证伪的时间流逝感）
    # 在 fatigue 高位的时点，随后的行为应出现 rest/sleep（取 top 15% 高位样本的后续行为）
    f = trace["fatigue"]
    high_thres = sorted(f)[int(len(f) * 0.85)]
    following = []
    for i, val in enumerate(f):
        if val >= high_thres and i + 1 < len(acts):
            following.append(acts[i + 1])
    assert any(a in ("rest", "sleep") for a in following), \
        "高疲劳时后续应有休息/睡眠行为"
    # 高疲劳时 rest/sleep 占比应明显高于全分布基线（疲劳确实驱动休息，非随机噪声）。
    # Phase 13 §3：人类尺度下疲劳危机期更短、且常与饥饿/困倦竞争主导，占比阈值从 0.15 放宽到
    # "显著高于随机基线"（全分布中 rest/sleep 出现率通常 < 3%）。
    rest_share = sum(1 for a in following if a in ("rest", "sleep")) / len(following)
    base_share = sum(1 for a in acts if a in ("rest", "sleep")) / len(acts)
    # 高疲劳时休息占比应显著高于全分布基线（≥2×，且不低于 2%）—— 疲劳确实驱动休息
    assert rest_share >= max(base_share * 2.0, 0.02), \
        f"高疲劳驱动休息不足: {rest_share:.0%}（基线 {base_share:.0%}）"


def test_activity_reduces_its_need():
    """因果：做 play 降低 boredom；降低幅度随需求已低而递减（diminishing）。"""
    st_high = CharacterState(); st_high.needs.boredom = 90
    ee = EmotionEngine(st_high.emotion)
    before = st_high.needs.boredom
    apply_outcome(st_high, "play", ee, recent_counts={})
    after_high = st_high.needs.boredom
    # 高需求时降得多
    st_low = CharacterState(); st_low.needs.boredom = 5
    ee2 = EmotionEngine(st_low.emotion)
    before_low = st_low.needs.boredom
    apply_outcome(st_low, "play", ee2, recent_counts={})
    after_low = st_low.needs.boredom
    assert after_high < before, "play 应降低高 boredom"
    # 低需求时几乎不再降（diminishing），且不把需求降到负
    assert after_low >= before_low - 5, f"低需求 play 不应把 boredom 清空: {before_low}->{after_low}"


def test_repeating_activity_diminishes():
    """连续做同一种活动收益递减（自然涌现'玩够了'）。"""
    st = CharacterState(); st.needs.boredom = 90
    ee = EmotionEngine(st.emotion)
    st1 = CharacterState(); st1.needs.boredom = 90
    ee1 = EmotionEngine(st1.emotion)
    apply_outcome(st, "play", ee)                 # 第1次
    first_drop = 90 - st.needs.boredom
    apply_outcome(st, "play", ee, recent_counts={"play": 2})   # 第3次（已玩过2次）
    second_drop = st.needs.boredom  # 用于对比
    # 重复做同样的事,下降应被 dampening 得更少 => 实际值仍较高（降得更少）
    assert first_drop >= 0
    # 用 fresh 对比：无重复时降得多,有重复降得少
    st2 = CharacterState(); st2.needs.boredom = 90
    ee2 = EmotionEngine(st2.emotion)
    apply_outcome(st2, "play", ee2, recent_counts={})   # 无重复
    no_rep_drop = 90 - st2.needs.boredom
    st3 = CharacterState(); st3.needs.boredom = 90
    ee3 = EmotionEngine(st3.emotion)
    apply_outcome(st3, "play", ee3, recent_counts={"play": 3})   # 重复3次
    rep_drop = 90 - st3.needs.boredom
    assert no_rep_drop > rep_drop, "重复做同一活动应收益递减"
