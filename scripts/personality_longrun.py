"""长期人格持久性审计（mock 驱动, 300+ steps/人格, fast）+ 异常检测。

用真实 Motivation + 确定性 mock 选行为，跑 300+ steps 观察人格是否在 Life Loop 中保持，
并检测：行为塌缩 / 需求吞噬人格 / 单一类别霸占 / Brain 吞噬。
anti-collapse OFF。
"""
from __future__ import annotations

import sys, math, random
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.personality_persistence as P
from furina.behavior import BehaviorMotivation
from furina.behavior.motivation import CATEGORY
from furina.behavior.outcome import apply_outcome


def mock_run(personality, steps=300, seed=11):
    rng = random.Random(seed)
    st = P.CharacterState(); st.clock_hour = 14
    st.relationship = P.RelationshipState()
    ee = P.EmotionEngine(st.emotion)
    mot = BehaviorMotivation(personality=personality)
    acts = []; cats = []; bo = []; sn = []
    for i in range(steps):
        w = (int(i / 25) % 2 == 0)
        P._dyn_needs(st, 30.0, w, 0 if (i % 15 < 5) else 300)
        ee.decay(dt=30.0); ee.derive_label()
        mot._last_done.clear(); mot._activity_history = []; mot._category_history = []
        cands = mot.candidates(st, ee)
        pick = rng.choices(cands[:4], weights=[max(0.04, c.score) for c in cands[:4]], k=1)[0]
        apply_outcome(st, pick.activity, ee, relationship=st.relationship, recent_counts=None)
        mot.mark_done(pick.activity, 0)
        acts.append(pick.activity); cats.append(CATEGORY.get(pick.activity))
        bo.append(st.needs.boredom); sn.append(st.needs.social_need)
    return acts, cats, bo, sn


def audit(name, acts, cats, bo, sn):
    n = len(acts); c = Counter(acts); cc = Counter(cats)
    ent = -sum(v/n*math.log2(v/n) for v in c.values() if v)
    def longest(seq):
        mx = cur = 1
        for i in range(1, len(seq)):
            cur = cur+1 if seq[i] == seq[i-1] else 1
            mx = max(mx, cur)
        return mx
    top_share = c.most_common(1)[0][1]/n
    top_cat = cc.most_common(1)[0][1]/n
    boring_at_100 = sum(1 for v in bo if v >= 95)/n
    print(f"\n[{name}] {n} steps（mock, anti OFF）")
    print(f"  SELF={cc.get('SELF',0)/n*100:.0f}% SOCIAL={cc.get('SOCIAL',0)/n*100:.0f}% OBSERVE={cc.get('OBSERVATION',0)/n*100:.0f}%")
    print(f"  explore={c.get('explore',0)/n*100:.0f}% play={c.get('play',0)/n*100:.0f}% talk={c.get('talk',0)/n*100:.0f}% approach={c.get('approach_user',0)/n*100:.0f}%")
    print(f"  熵={ent:.2f} 同活动最长={longest(acts)} 同类别最长={longest(cats)} top活动占比={top_share*100:.0f}% top类别占比={top_cat*100:.0f}%")
    print(f"  boredom≥95={boring_at_100*100:.0f}% 终态boredom={bo[-1]:.0f} social={sn[-1]:.0f}")
    # 异常标记
    flags = []
    if top_share > 0.5: flags.append("行为塌缩(top>50%)")
    if top_cat > 0.6: flags.append("类别霸占(topcat>60%)")
    if longest(cats) > 5: flags.append("同类别连击过长")
    if boring_at_100 > 0.3: flags.append("boredom长期高位")
    print(f"  异常: {flags if flags else '无'}")
    return {"SELF": cc.get("SELF",0)/n, "SOCIAL": cc.get("SOCIAL",0)/n, "explore": c.get("explore",0)/n,
            "play": c.get("play",0)/n, "talk": c.get("talk",0)/n, "approach": c.get("approach_user",0)/n,
            "entropy": ent, "flags": flags}


if __name__ == "__main__":
    print("=" * 70)
    print("长期人格持久性（mock, 300 steps/人格）+ 异常审计, anti OFF")
    print("=" * 70)
    fps = {}
    for nm, per in [("Explorer", P.EXPLORER), ("Social", P.SOCIAL), ("Playful", P.PLAYFUL), ("Furina", P.FURINA)]:
        acts, cats, bo, sn = mock_run(per, steps=300, seed=11)
        fps[nm] = audit(nm, acts, cats, bo, sn)
    def dist(a, b):
        keys = ["SELF","SOCIAL","explore","play","read","talk","approach"]
        return round(sum(abs(fps[a][k]-fps[b][k]) for k in keys if k in fps[a] and k in fps[b]), 2)
    print("\n长期 persistence 距离(300 steps 后):")
    for a, b in [("Explorer","Social"),("Explorer","Playful"),("Social","Playful")]:
        print(f"  {a} vs {b}: {dist(a,b)}")
