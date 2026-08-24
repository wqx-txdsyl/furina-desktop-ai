"""行为选择统计报告（任务 §22）—— Mock Brain（快、稳定、大样本，纯行为统计）。"""
from __future__ import annotations

import sys, random, math
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation
from furina.behavior.motivation import CATEGORY


def pick(mot, state, emotion):
    """Mock 选行为：带一点随机（避免死循环）但倾向高分候选的诚实 mock。"""
    cands = mot.candidates(state, emotion)
    top4 = cands[:4]
    weights = [c.score + 0.01 for c in top4]
    return random.choices(top4, weights=weights, k=1)[0]


def longest(seq):
    if not seq:
        return 0
    mx = cur = 1
    for i in range(1, len(seq)):
        cur = cur + 1 if seq[i] == seq[i-1] else 1
        mx = max(mx, cur)
    return mx


def run_scenario(n=60, **need):
    st = CharacterState(); st.clock_hour = 14
    st.user_working = need.pop("user_working", False)
    for k, v in need.items():
        setattr(st.needs, k, v)
    ee = EmotionEngine(st.emotion)
    mot = BehaviorMotivation()
    acts = []; cats = []
    talk_opp = talk_acc = talk_rej = 0
    for _ in range(n):
        p = pick(mot, st, ee)
        soc, reason = mot.talk_opportunity(st, ee)
        if p.activity == "talk":
            talk_opp += 1
            if reason and soc > 0.5:
                talk_acc += 1
            else:
                talk_rej += 1
        mot.mark_done(p.activity, 0)
        acts.append(p.activity); cats.append(CATEGORY.get(p.activity, "SELF"))
    return acts, cats, {"talk_opp": talk_opp, "talk_acc": talk_acc, "talk_rej": talk_rej}


def stats(label, data):
    acts, cats, t = data
    n = len(acts); c = Counter(acts); cc = Counter(cats)
    probs = [v / n for v in c.values()]
    ent = -sum(p * math.log2(p) for p in probs if p > 0)
    print(f"\n=== {label} ({n} 决策) ===")
    print(f"  Idle%         : {c.get('idle',0)/n*100:4.1f}%")
    print(f"  Observe%      : {cc.get('OBSERVATION',0)/n*100:4.1f}%")
    print(f"  Self Activity%: {cc.get('SELF',0)/n*100:4.1f}%")
    print(f"  Social%       : {cc.get('SOCIAL',0)/n*100:4.1f}%")
    print(f"  Assistance%   : {cc.get('ASSISTANCE',0)/n*100:4.1f}%")
    print(f"  最长同活动连击 : {longest(acts)}  (硬上限3)")
    print(f"  最长同类别连击 : {longest(cats)}")
    print(f"  候选熵         : {ent:.2f}")
    print(f"  Talk: opp={t['talk_opp']} acc={t['talk_acc']} rej={t['talk_rej']}")
    print(f"  Top5           : {dict(c.most_common(5))}")


if __name__ == "__main__":
    random.seed(42)
    stats("a_no_interact", run_scenario())
    stats("b_user_working", run_scenario(user_working=True))
    stats("c_high_social", run_scenario(social_need=95))
    stats("d_high_boredom", run_scenario(boredom=95, playfulness=90))
    stats("e_high_fatigue", run_scenario(fatigue=95, sleepiness=90))
    print("\n[硬性反塌缩] 是否任何场景 observe>50% 或 同活动连击>3:")
    all_ok = True
    for label in ["a", "b", "c", "d"]:
        data = run_scenario()
        acts, cats, _ = data
        obs = sum(1 for x in cats if x == "OBSERVATION") / len(cats)
        if obs > 0.5 or longest(acts) > 3:
            all_ok = False
            print(f"  {label}: FAIL observe={obs:.2f} streak={longest(acts)}")
    print("  ALL PASS" if all_ok else "  FAIL")
