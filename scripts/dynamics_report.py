"""闭环动力学校准 —— 最终验收（任务 §re-port）：24h, anti-collapse OFF。

输出用户要的全部指标：min/mean/max、time<=5/>=95、dominant_need 分布、
activity 分布、same_activity_streak、因果触发次数。
"""
from __future__ import annotations

import sys, random
from pathlib import Path
from collections import Counter, defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from furina.core import EventBus
from furina.state.state_engine import StateEngine
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation
from furina.behavior.outcome import apply_outcome
from furina.behavior.motivation import CATEGORY, _NEED_OF

random.seed(99)
NEEDS = ["boredom", "playfulness", "fatigue", "sleepiness", "social_need", "curiosity", "satisfaction"]


def long_sim(minutes=1440, dt=30.0):
    se = StateEngine(EventBus()); st = se.state; st.clock_hour = 14
    ee = EmotionEngine(st.emotion); mot = BehaviorMotivation()
    steps = int(minutes * 60 / dt)
    trace = {k: [] for k in NEEDS}; acts = []; prev_act = None
    causal = defaultdict(int)   # need -> 该需求作为"主导"时触发的行为
    dominant_seq = []
    streak = 1; max_streak = 1
    for i in range(steps):
        working = (int(i * dt / (30 * 60)) % 2 == 0)
        se.update_needs(dt, working, 0 if (i % 60 < 20) else 300)
        ee.decay(dt=dt); ee.derive_label()
        cands = mot.candidates(st, ee)
        pick = random.choices(cands[:4], weights=[max(0.04, c.score) for c in cands[:4]], k=1)[0]
        act = pick.activity
        # 主导需求（动机型）
        dn = _dominant_need(st)
        dominant_seq.append(dn)
        causal[dn] = causal.get(dn, 0) + 1
        apply_outcome(st, act, ee, recent_counts=None)
        mot.mark_done(act, 0)
        for k in NEEDS:
            trace[k].append(getattr(st.needs, k))
        acts.append(act)
        streak = streak + 1 if act == prev_act else 1
        max_streak = max(max_streak, streak)
        prev_act = act
    return trace, acts, causal, dominant_seq, max_streak


def _dominant_need(st):
    n = st.needs
    return max(("boredom", "social_need", "curiosity", "playfulness"),
               key=lambda k: getattr(n, k))


def report(label, trace, acts, causal, dominant_seq, max_streak):
    n = len(acts)
    cc = Counter(acts); dc = Counter(dominant_seq)
    cats = Counter(CATEGORY.get(a) for a in acts)
    print(f"\n{'='*60}\n{label} ({n} 决策, anti OFF)\n{'='*60}")
    print("需求 min/mean/max | <=5% | >=95%:")
    for k in NEEDS:
        s = trace[k]
        print(f"  {k:12} min={min(s):5.1f} mean={sum(s)/n:5.1f} max={max(s):5.1f} | "
              f"{sum(1 for v in s if v<=5)/n*100:4.1f}% | {sum(1 for v in s if v>=95)/n*100:4.1f}%")
    print(f"\n主导需求分布: { {k: round(v/n*100,1) for k,v in dc.items()} }")
    print(f"行为分布: SELF={cats.get('SELF',0)/n*100:.0f}% SOCIAL={cats.get('SOCIAL',0)/n*100:.0f}% "
          f"OBSERVE={cats.get('OBSERVATION',0)/n*100:.0f}% ASSIST={cats.get('ASSISTANCE',0)/n*100:.0f}%")
    print(f"  top6 = {dict(cc.most_common(6))}")
    print(f"  same_activity_streak = {max_streak}")
    print(f"因果触发(主导需求→行为): {dict(causal)}")
    # 因果: 主导 social_need 时,行为里 SOCIAL 占比
    social_dom = [acts[i] for i in range(n) if dominant_seq[i] == "social_need"]
    if social_dom:
        soc_share = sum(1 for a in social_dom if CATEGORY.get(a) == "SOCIAL") / len(social_dom) * 100
        print(f"  当 social_need 主导时 → SOCIAL 行为 {soc_share:.0f}% （>0 表明社交能自然发生）")


def show_trace(trace, label):
    stride = max(1, len(trace["boredom"]) // 24)
    print(f"\n{label} 需求时序(每 {stride} 点):")
    print(f"  {'min':>4} {'bored':>6} {'playf':>6} {'fatig':>6} {'socNe':>6} {'curio':>6}")
    for i in range(0, len(trace["boredom"]), stride):
        print(f"  {i*30//60:>3}m  {trace['boredom'][i]:6.0f} {trace['playfulness'][i]:6.0f} "
              f"{trace['fatigue'][i]:6.0f} {trace['social_need'][i]:6.0f} {trace['curiosity'][i]:6.0f}")


if __name__ == "__main__":
    t, a, c, d, m = long_sim(1440)
    report("24h", t, a, c, d, m)
    show_trace(t, "24h")
