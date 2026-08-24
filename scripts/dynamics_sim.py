"""闭环动力学长期模拟（任务 §4-5）：2h / 6h / 24h，anti-collapse OFF。

用真实 update_needs（稳态再生）+ real BehaviorMotivation + outcome（diminishing returns），
Mock Brain（确定性加权）选行为，验证：
 - 需求不长期贴 0 / 贴 100
 - 需求形成"积累→满足→衰减→再生"动态稳态
 - 不同需求随时间轮流成为行为驱动力（need takeover）
 - 关掉 anti-collapse 仍能维持行为多样性

指标：need min/max/mean、time-at-zero、time-at-100、振荡周期、恢复时间、
      每行为满意度递减、boredom/fatigue/social_need/playfulness 时序、24h 完整轨迹。
"""
from __future__ import annotations

import sys, random, math
from pathlib import Path
from collections import Counter, defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from furina.state import CharacterState
from furina.state.state_engine import StateEngine, _BASELINE
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation
from furina.behavior.outcome import apply_outcome
from furina.behavior.motivation import CATEGORY
from furina.core import EventBus

random.seed(42)

NEEDS = ["boredom", "playfulness", "fatigue", "sleepiness", "social_need", "curiosity", "satisfaction"]
SOCIAL = {"approach_user", "talk", "invite_user", "greet", "comfort", "celebrate", "seek_attention"}


def sim(sim_minutes: float, dt=30.0, user_side_ratio=0.4):
    bus = EventBus()
    se = StateEngine(bus)
    st = se.state
    st.clock_hour = 14
    ee = EmotionEngine(st.emotion)
    mot = BehaviorMotivation()
    steps = int(sim_minutes * 60 / dt)
    trace = {k: [] for k in NEEDS}
    acts = []; times = []
    recent_counts = defaultdict(int)
    # 分时段用户状态（工作/不忙轮换 + 偶尔互动）
    for i in range(steps):
        t = i * dt
        working = (int(t / (30 * 60)) % 2 == 0)   # 每 30min 切换一次工作状态
        idle = 0 if (i % 60 < 20) else 300
        se.update_needs(dt, working, idle)
        ee.decay(dt=dt); ee.derive_label()
        # 行为选择（Mock Brain，anti OFF）
        cands = mot.candidates(st, ee)
        pick = random.choices(cands[:4], weights=[max(0.05, c.score) for c in cands[:4]], k=1)[0]
        act = pick.activity
        apply_outcome(st, act, ee, recent_counts=dict(recent_counts))
        recent_counts[act] += 1
        # 加时钟推进（分钟）
        st.clock_minute = (st.clock_minute + int(dt / 60)) % 60
        st.clock_hour = (st.clock_hour + 1 if st.clock_minute == 0 else st.clock_hour) % 24
        for k in NEEDS:
            trace[k].append(getattr(st.needs, k))
        acts.append(act); times.append(t)
    return {"trace": trace, "acts": acts, "times": times, "st": st}


def metrics(name, data):
    trace = data["trace"]; acts = data["acts"]; st = data["st"]
    n = len(acts)
    print(f"\n=== {name} 模拟（{int(data['times'][-1]/60)} 分钟, {n} 决策, anti OFF）===")
    c = Counter(acts)
    # 需求统计
    print("需求 min/mean/max | time_at<=5% | time_at>=95%:")
    for k in NEEDS:
        s = trace[k]
        zero = sum(1 for v in s if v <= 5) / n * 100
        full = sum(1 for v in s if v >= 95) / n * 100
        print(f"  {k:14} min={min(s):5.1f} mean={sum(s)/n:5.1f} max={max(s):5.1f} | <=5%:{zero:4.1f}% | >=95%:{full:4.1f}%")
    # 行为多样性
    cats = Counter(CATEGORY.get(a) for a in acts)
    self_ = cats.get("SELF", 0)/n*100; social_ = cats.get("SOCIAL", 0)/n*100
    obs_ = cats.get("OBSERVATION", 0)/n*100; asst_ = cats.get("ASSISTANCE", 0)/n*100
    print(f"\n行为: 不同活动={len(c)}  SELF={self_:.0f}% SOCIAL={social_:.0f}% OBSERVE={obs_:.0f}% ASSIST={asst_:.0f}%")
    print(f"  top6 = {dict(c.most_common(6))}")
    # 需求接管：统计每次"new dominant need"何时驱动转向
    turn_take = _need_takeover(trace, acts)
    print(f"\n需求接管示例（不同内部需求轮流成为驱动）:\n  {turn_take[:6]}")
    # 振荡/恢复：boredom 的峰谷
    per = _oscillation(trace["boredom"])
    print(f"boredom 振荡周期(平均峰距) ≈ {per:.0f} 决策点(约{per*0.5:.0f}min)" if per else "boredom 无明显振荡(近稳态)")
    return c


def _need_takeover(trace, acts):
    """找需求主导的切换：某需求达到峰值后行为切换到满足它的活动。"""
    # 简化：每个需求达到本阶段高峰时的"下个行为"
    out = []
    n = len(acts)
    for k in NEEDS:
        s = trace[k]
        # 找峰值时刻
        peak = max(range(len(s)), key=lambda i: s[i])
        # 峰值后的行为
        if peak + 2 < n:
            out.append(f"{k}@{s[peak]:.0f}→{acts[peak+1]}")
    return out


def _oscillation(s):
    """粗略峰谷周期：找局部极大值间距。"""
    peaks = []
    for i in range(2, len(s)-2):
        if s[i] > s[i-1] and s[i] >= s[i+1] and s[i] > s[i-2]:
            peaks.append(i)
    if len(peaks) < 3:
        return 0
    gaps = [peaks[i+1]-peaks[i] for i in range(len(peaks)-1)]
    return sum(gaps)/len(gaps)


def show_trace(data, label):
    trace = data["trace"]
    stride = max(1, len(trace["boredom"]) // 24)   # 24 个采样点
    print(f"\n{label} 需求时序（每 {stride} 点采一次，共 {len(trace['boredom'])} 点）:")
    print(f"  {'min':>4} {'boredom':>8} {'playful':>8} {'fatigue':>8} {'social':>8} {'curious':>8}")
    for i in range(0, len(trace["boredom"]), stride):
        print(f"  {i*30//60:>3}m  {trace['boredom'][i]:8.0f} {trace['playfulness'][i]:8.0f} "
              f"{trace['fatigue'][i]:8.0f} {trace['social_need'][i]:8.0f} {trace['curiosity'][i]:8.0f}")


if __name__ == "__main__":
    print("=" * 70)
    print("闭环动力学长期模拟 —— anti-collapse OFF")
    print("=" * 70)
    h = sim(120)
    metrics("2h", h); show_trace(h, "2h")
    h6 = sim(360)
    metrics("6h", h6)
    h24 = sim(1440)
    metrics("24h", h24); show_trace(h24, "24h(全)")
