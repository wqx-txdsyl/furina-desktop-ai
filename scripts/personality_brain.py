"""真实 LLM Brain 人格 A/B（P0）—— Top-N 候选空间约束后，验证 Brain 是否尊重人格。

记录: allowed space / raw selection / validated selection / invalid / compliance。
anti-collapse OFF。固定 state+seed，仅变人格。
"""
from __future__ import annotations

import sys, random
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from furina.config.app_config import load_config
from furina.llm import get_adapter
from furina.life_brain import LifeBrain
from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality
from furina.behavior.motivation import CATEGORY

EXPLORER = Personality(0.5, 0.2, 1.0, 0.5, 0.5, 1.0, 0.1, 0.9)
SOCIAL = Personality(0.5, 1.0, 0.2, 0.5, 0.8, 0.5, 0.9, 0.2)
PLAYFUL = Personality(0.5, 0.5, 0.5, 1.0, 0.5, 0.5, 0.7, 0.5)


def run(personality, n=20, seed=3, needs=None):
    cfg = load_config()
    lb = LifeBrain(get_adapter(cfg.llm.provider)(cfg.llm))
    rng = random.Random(seed)
    st = CharacterState(); st.clock_hour = 14
    if needs:
        for k, v in needs.items():
            setattr(st.needs, k, v)
    ee = EmotionEngine(st.emotion)
    mot = BehaviorMotivation(personality=personality)
    rows = []
    for i in range(n):
        st.clock_minute = (st.clock_minute + 5) % 60
        mot._last_done.clear(); mot._activity_history = []; mot._category_history = []
        cands = [c.as_dict() for c in mot.candidates(st, ee)]
        allowed = [c["activity"] for c in cands[:4]]   # Top-4
        st.life.activity = "idle"; st.intent.action = "idle"
        d = lb.decide(state=st, force=True, candidates=cands)
        st.life.activity = d.activity; st.intent.action = d.activity
        rows.append({
            "allowed": list(d.allowed_space),
            "raw": d.brain_raw_selection,
            "selected": d.activity,
            "cat": CATEGORY.get(d.activity),
            "invalid": d.brain_invalid,
        })
        mot.mark_done(d.activity, 0)
    return rows


def summarize(name, rows):
    n = len(rows)
    sel = Counter(r["selected"] for r in rows)
    cats = Counter(r["cat"] for r in rows)
    invalid = sum(1 for r in rows if r["invalid"]) / n
    # top1/top3 compliance: 选中的是否在给定决定空间的排位
    top1 = sum(1 for r in rows if r["selected"] == r["allowed"][0]) / n
    top3 = sum(1 for r in rows if r["selected"] in r["allowed"][:3]) / n
    print(f"\n[{name}] {n} 次真实 LLM 决策 (Top-4 空间约束)")
    print(f"  最终行为: {dict(sel.most_common(6))}")
    print(f"  类别: {dict(cats)}")
    print(f"  valid_selection率(compliance): {100-invalid*100:.0f}%  top1率: {top1*100:.0f}%  top3率: {top3*100:.0f}%")
    # 显示每步 raw vs validated
    for r in rows[:5]:
        raw = "*" if r["selected"] == r["raw"] else f"{r['raw']}->{r['selected']}"
        print(f"     allowed={r['allowed'][:3]}  pick={r['selected']}({'invalid' if r['invalid'] else 'ok'})")
    return {"sel": sel, "top1": top1, "top3": top3, "invalid": invalid, "cats": cats}


def js(a, b):
    import math
    keys = list(set(a) | set(b))
    def n(d):
        s = sum(d.values()); return {k: v/s for k, v in d.items()} if s else {}
    pa, pb = n(a), n(b)
    m = {k: (pa.get(k, 0)+pb.get(k, 0))/2 for k in keys}
    def kl(p): return sum(p.get(k, 0)*math.log2(p.get(k, 0)/m[k]) for k in keys if p.get(k, 0) > 0 and m[k] > 0)
    return 0.5*kl(pa)+0.5*kl(pb)


if __name__ == "__main__":
    needs = {"boredom": 50, "social_need": 45, "curiosity": 55, "fatigue": 25, "playfulness": 40}
    print("=" * 72)
    print("真实 LLM Brain 人格 A/B —— Top-N 候选空间约束, anti OFF")
    print("=" * 72)
    res = {}
    for nm, per in [("Explorer", EXPLORER), ("Social", SOCIAL), ("Playful", PLAYFUL)]:
        rows = run(per, n=20, seed=3, needs=needs)
        res[nm] = summarize(nm, rows)
    print("\n行为分布 JS 距离:")
    for a, b in [("Explorer", "Social"), ("Explorer", "Playful"), ("Social", "Playful")]:
        print(f"  {a} vs {b}: {js(res[a]['sel'], res[b]['sel']):.3f}")
    print("\n关键对齐 (Playful.play vs Explorer.play):")
    play_e = res["Explorer"]["sel"].get("play", 0)/20
    play_p = res["Playful"]["sel"].get("play", 0)/20
    print(f"  Explorer play: {play_e*100:.0f}%   Playful play: {play_p*100:.0f}%")
    print(f"  Explorer explore: {res['Explorer']['sel'].get('explore',0)/20*100:.0f}%  Playful explore: {res['Playful']['sel'].get('explore',0)/20*100:.0f}%")
    soc_social = (res['Social']['sel'].get('talk',0)+res['Social']['sel'].get('approach_user',0))/20
    print(f"  Social talk+approach: {soc_social*100:.0f}%")
