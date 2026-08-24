"""长期 Personality Fingerprint（任务 §九）+ 状态稳定性（§十）+ Relationship×Personality（§十一）。"""
from __future__ import annotations

import sys, math, random
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality
from furina.behavior.motivation import CATEGORY
from furina.memory.memory_types import RelationshipState

EXPLORER = Personality(0.5, 0.2, 1.0, 0.5, 0.5, 1.0, 0.1, 0.9)
SOCIAL   = Personality(0.5, 1.0, 0.2, 0.5, 0.8, 0.5, 0.9, 0.2)
PLAYFUL  = Personality(0.5, 0.5, 0.5, 1.0, 0.5, 0.5, 0.7, 0.5)


def fingerprint(personality, steps=300, seed=5, needs=None, rel=None):
    rng = random.Random(seed)
    st = CharacterState(); st.clock_hour = 14
    if needs:
        for k, v in needs.items():
            setattr(st.needs, k, v)
    st.relationship = rel or RelationshipState()
    ee = EmotionEngine(st.emotion)
    mot = BehaviorMotivation(personality=personality)
    acts = []; cats = []
    for i in range(steps):
        # 模拟时间漂移（让状态随场景演化）
        st.clock_minute = (st.clock_minute + 5) % 60
        st.clock_hour = (st.clock_hour + 1 if st.clock_minute == 0 else st.clock_hour) % 24
        if i % 20 == 0:
            # 偶尔注入需求波动（探索不同状态）
            st.needs.boredom = max(20, min(95, st.needs.boredom + rng.choice([-15, 10, 20])))
            st.needs.social_need = max(20, min(95, st.needs.social_need + rng.choice([-10, 15, 5])))
            st.needs.curiosity = max(20, min(95, st.needs.curiosity + rng.choice([-8, 12])))
            st.needs.fatigue = max(15, min(95, st.needs.fatigue + rng.choice([-8, 12])))
            st.needs.clamp()
        # anti OFF
        mot._last_done.clear(); mot._activity_history = []; mot._category_history = []
        cands = mot.candidates(st, ee)
        pick = rng.choices(cands[:4], weights=[max(0.04, c.score) for c in cands[:4]], k=1)[0]
        mot.mark_done(pick.activity, 0)
        acts.append(pick.activity); cats.append(CATEGORY.get(pick.activity))
    return acts, cats


def summarize(acts, cats):
    n = len(acts); c = Counter(acts); cc = Counter(cats)
    ent = -sum(v/n*math.log2(v/n) for v in c.values() if v)
    def longest(seq):
        mx = cur = 1
        for i in range(1, len(seq)):
            cur = cur+1 if seq[i] == seq[i-1] else 1
            mx = max(mx, cur)
        return mx
    rec = {
        "explore": sum(v for a, v in c.items() if a in ("explore", "wander", "look_around"))/n,
        "play": c.get("play", 0)/n,
        "read": c.get("read", 0)/n,
    }
    return {
        "SELF": cc.get("SELF", 0)/n, "SOCIAL": cc.get("SOCIAL", 0)/n,
        "OBSERVE": cc.get("OBSERVATION", 0)/n, "ASSIST": cc.get("ASSISTANCE", 0)/n,
        "explore": rec["explore"], "play": rec["play"], "read": rec["read"],
        "talk": c.get("talk", 0)/n, "approach": c.get("approach_user", 0)/n,
        "entropy": ent, "streak": longest(acts), "n_distinct": len(c),
    }


if __name__ == "__main__":
    print("=" * 70)
    print("长期 Personality Fingerprint（anti OFF, ~300 决策/人格）")
    print("=" * 70)
    fps = {}
    PER = {"Explorer": EXPLORER, "Social": SOCIAL, "Playful": PLAYFUL}
    for nm, per in PER.items():
        acts, cats = fingerprint(per, steps=300, seed=5)
        fps[nm] = summarize(acts, cats)
    hdr = ["SELF", "SOCIAL", "OBSERVE", "ASSIST", "explore", "play", "read", "talk", "approach", "entropy", "streak"]
    print(f"{'Metric':10}" + "".join(f"{h:>9}" for h in hdr))
    for nm in PER:
        f = fps[nm]
        print(f"{nm:10}" + "".join(f"{f[h]*100:8.1f}%" if h not in ("entropy","streak") else f"{f[h]:8.2f}" for h in hdr))
    # 区分度
    def dif(a, b, keys):
        return sum(abs(a[k]-b[k]) for k in keys)
    keys = ["SELF", "SOCIAL", "explore", "play", "talk", "approach"]
    print(f"\n语义区分度(0..1):")
    print(f"  Explorer vs Social: {dif(fps['Explorer'], fps['Social'], keys):.2f}")
    print(f"  Explorer vs Playful: {dif(fps['Explorer'], fps['Playful'], keys):.2f}")
    print(f"  Social vs Playful:   {dif(fps['Social'], fps['Playful'], keys):.2f}")
