"""Personality 因果性实验（任务 §6-§14）。

严格反事实：固定 World/Needs/Emotion/Relationship/Recent History/Random Seed，
仅改变 Personality，验证候选排名与行为分布是否稳定分化。

anti_collapse = OFF（人格必须是差异的因果来源）。
"""
from __future__ import annotations

import sys, random, math
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality
from furina.behavior.motivation import CATEGORY
from furina.memory.memory_types import RelationshipState

# 三个测试人格（任务 §5）
EXPLORER = Personality(0.5, 0.2, 1.0, 0.5, 0.5, 1.0, 0.1, 0.9)   # selfp, social, explore, play, helpf, curios, attn, indep
SOCIAL   = Personality(0.5, 1.0, 0.2, 0.5, 0.8, 0.5, 0.9, 0.2)
PLAYFUL  = Personality(0.5, 0.5, 0.5, 1.0, 0.5, 0.5, 0.7, 0.5)
NEUTRAL  = Personality()
PERSONALITIES = {"Explorer": EXPLORER, "Social": SOCIAL, "Playful": PLAYFUL}


def set_state(st, scenario, rel_state=None):
    """设定固定 needs 场景 + 关系。"""
    if scenario == "normal":
        st.needs.boredom = 50; st.needs.social_need = 45; st.needs.curiosity = 55
        st.needs.fatigue = 25; st.needs.playfulness = 40
    elif scenario == "high_fatigue":
        st.needs.fatigue = 100; st.needs.sleepiness = 90
    elif scenario == "high_social":
        st.needs.social_need = 92; st.needs.boredom = 60
    elif scenario == "high_boredom":
        st.needs.boredom = 95; st.needs.playfulness = 92
    elif scenario == "high_curiosity":
        st.needs.curiosity = 95
    st.clock_hour = 14
    rel = rel_state or RelationshipState()
    # 关系（trust/comfort/annoyance）
    return rel


def run_counterfactual(scenario, name, personality, steps=60, seed=42, rel_state=None,
                       anti=False, need_overrides=None):
    """固定 seed + 状态，只改 personality；anti OFF。返回 (acts, cats, cands_log)。"""
    rng = random.Random(seed)
    st = CharacterState(); st.clock_hour = 14
    if need_overrides:
        for k, v in need_overrides.items():
            setattr(st.needs, k, v)
    rel = rel_state or RelationshipState()
    st.relationship = rel
    ee = EmotionEngine(st.emotion)
    mot = BehaviorMotivation(personality=personality)
    acts = []; cats = []; cands_log = []
    for i in range(steps):
        # deterministic world clock
        st.clock_minute = (st.clock_minute + 5) % 60
        st.clock_hour = (st.clock_hour + 1 if st.clock_minute == 0 else st.clock_hour) % 24
        if not anti:
            mot._last_done.clear(); mot._activity_history = []; mot._category_history = []
        cands = mot.candidates(st, ee)
        # 记录 top1 候选 + 其 base/personality 分解
        top = cands[0]
        pick = rng.choices(cands[:4], weights=[max(0.04, c.score) for c in cands[:4]], k=1)[0]
        # 人格修改量 = 相对 neutral 的上提/压低
        base_neutral = BehaviorMotivation(personality=NEUTRAL).candidates(st, ee)
        base_by_act = {c.activity: c.score for c in base_neutral}
        pw = mot.personality.as_weight(pick.activity)
        cands_log.append({
            "personality": name,
            "activity": pick.activity,
            "category": CATEGORY.get(pick.activity),
            "base_neutral": round(base_by_act.get(pick.activity, 0), 3),
            "personality_weight": round(pw, 2),
            "final": round(pick.score, 3),
            "top_candidate": top.activity,
            "top_score": round(top.score, 3),
            "was_top": pick.activity == top.activity,
        })
        mot.mark_done(pick.activity, 0)
        acts.append(pick.activity); cats.append(CATEGORY.get(pick.activity, "SELF"))
    return acts, cats, cands_log


def dist(acts):
    c = Counter(acts); n = len(acts)
    return {a: round(v / n, 3) for a, v in c.items()}, c


def top_share(acts, topk):
    c = Counter(acts); n = len(acts)
    return sum(v for a, v in c.items() if a in topk) / n


def jensen_shannon(p, q):
    """行为分布差异（0=相同）。"""
    keys = set(p) | set(q)
    K = len(keys)
    pp = [p.get(k, 0) for k in keys]; qq = [q.get(k, 0) for k in keys]
    def norm(a): 
        s = sum(a); return [x/s for x in a] if s else a
    ppn = norm(pp); qqn = norm(qq)
    m = [(x+y)/2 for x, y in zip(ppn, qqn)]
    def kl(a): return sum(x*math.log2(x/y) for x, y in zip(a, m) if x > 0 and y > 0)
    return 0.5 * kl(ppn) + 0.5 * kl(qqn)


def main():
    print("=" * 70)
    print("Personality 因果性实验 —— 固定状态+seed，仅变人格，anti OFF")
    print("=" * 70)

    # 1) 反事实：normal 场景，3 人格 + OFF 对照
    results = {}
    print("\n[1] 反事实 A/B — 场景=normal (state+seed 全固定)")
    fixed_needs = {"boredom": 50, "social_need": 45, "curiosity": 55, "fatigue": 25, "playfulness": 40}
    for nm in ["Explorer", "Social", "Playful"]:
        acts, cats, log = run_counterfactual("normal", nm, PERSONALITIES[nm], steps=100, seed=7,
                                             anti=False, need_overrides=fixed_needs)
        p, c = dist(acts)
        results[nm] = (p, acts, cats)
        print(f"  {nm:9} Top: {dict(sorted(p.items(), key=lambda x:-x[1])[:5])}")
        # 人格偏爱类别占比
        cat_share = Counter(cats)
        print(f"           SELF={cat_share.get('SELF',0)/len(cats)*100:.0f}% SOCIAL={cat_share.get('SOCIAL',0)/len(cats)*100:.0f}%")

    # 2) Personality OFF: 用 NEUTRAL 人格，3 个 personality 指纹都改成 NEUTRAL -> 应无差异
    print("\n[2] Personality OFF 对照 — 3 人格被替换为 NEUTRAL(视为 OFF)")
    off_acts = {}
    for nm in ["Explorer", "Social", "Playful"]:
        acts, cats, log = run_counterfactual("normal", nm, NEUTRAL, steps=100, seed=7,
                                             anti=False, need_overrides=fixed_needs)
        p, c = dist(acts)
        off_acts[nm] = p
        print(f"  {nm}(→Neutral) Top: {dict(sorted(p.items(), key=lambda x:-x[1])[:4])}")
    jso = jensen_shannon(off_acts["Explorer"], off_acts["Social"])
    jso2 = jensen_shannon(off_acts["Explorer"], off_acts["Playful"])
    print(f"  OFF 时 Explorer vs Social JS距离={jso:.4f} (≈0 → 人格被关闭时无差异)")

    # 3) Personality ON: 分布差异
    print("\n[3] Personality ON — 分布差异 (JS 距离, >0 表示显著分化)")
    j_e_s = jensen_shannon(results["Explorer"][0], results["Social"][0])
    j_e_p = jensen_shannon(results["Explorer"][0], results["Playful"][0])
    j_s_p = jensen_shannon(results["Social"][0], results["Playful"][0])
    print(f"  Explorer vs Social JS = {j_e_s:.4f}")
    print(f"  Explorer vs Playful JS = {j_e_p:.4f}")
    print(f"  Social vs Playful JS   = {j_s_p:.4f}")

    # 4) 候选排名偏移
    print("\n[4] 候选排名偏移（normal 场景, top3 候选）")
    for nm in ["Explorer", "Social", "Playful"]:
        _,_,log = run_counterfactual("normal", nm, PERSONALITIES[nm], steps=30, seed=7,
                                     anti=False, need_overrides=fixed_needs)
        # 平均每个候选的 base_neutral vs final
        print(f"  {nm:9}: 每次决策 top候选={Counter(l['top_candidate'] for l in log).most_common(2)}")

    print("\n完成。判定标准: ON 时 JS 距离显著>0, OFF 时≈0 => 人格是真实因果变量。")
    return 0


if __name__ == "__main__":
    main()
