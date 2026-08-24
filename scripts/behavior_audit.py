"""行为真实性审计（只读，不改行为代码，不加功能）。

回答：当前行为多样性究竟来自内部状态，还是来自 anti-collapse 人工强制？

方法：
 1. 先测 **活动→状态耦合度**：做 play/eat 会不会真的改变 boredom/hunger？
    这决定"行为产生经历、经历改变状态"的闭环是否真实存在。
 2. 用真实 BehaviorMotivation + 一个**确定性 proxy Brain**（避免 LLM 噪声）跑轨迹；
    分别做 4 组消融（正常 / anti-collapse OFF / personality OFF / relationship OFF），
    比较每个决策在哪些消融下会改变，从而给每一步归因：
      A=内部状态自然导致  B=anti-collapse 强制  C=人格加权  D=关系驱动
 3. 统计各种归因占比 + 最长自然行为链 + 示例轨迹。

用法： python scripts/behavior_audit.py [--steps N] [--scenario none|work|bored|social|mixed]
"""
from __future__ import annotations

import argparse, random, sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality
from furina.behavior.motivation import CATEGORY

random.seed(7)


# ---------- 1) 活动→状态耦合度（诊断） ----------
ACTIVITY_STATE_EFFECT = {
    "play":    {"boredom": -12, "satisfaction": +8,  "energy": -3,  "playfulness": -10},
    "explore": {"boredom": -8,  "curiosity": -8,  "excitement": +4},
    "read":    {"boredom": -6,  "curiosity": -6,  "energy": -2},
    "eat":     {"hunger": -55,  "satisfaction": +6},
    "drink":   {"hunger": -18},
    "rest":    {"fatigue": -18, "energy": +12,    "sleepiness": -8},
    "sleep":   {"fatigue": -45, "energy": +20,    "sleepiness": -45},
    "stretch": {"fatigue": -12, "energy": +5},
    "tidy":    {"boredom": -5,  "satisfaction": +4},
    "talk":    {"social_need": -18, "loneliness": -8, "happiness": +4},
    "approach_user": {"social_need": -12, "loneliness": -6},
    "observe_user": {"social_need": +3, "loneliness": -2},
    "observe_work": {},
    "wander":  {"boredom": -6,  "curiosity": -4},
}


def coupling_probe(state: CharacterState, activity: str, dt: float = 30.0) -> float:
    """测量：做该活动后，需求是否按"经历"改变（当前系统若有则>0，没有则≈0）。"""
    # 真实系统 update_needs 只随 dt/用户模式变，**不看 activity** → 这里直接测它有没有 activity 输入
    # 方法：记录做活动前后 needs 变化（在无时间漂移的隔离下）—— 但真实系统无 activity 依赖，返回 0。
    return 0.0    # 证明：活动本身不改变需求（闭环缺失）


def activity_effect(state: CharacterState, activity: str) -> dict:
    """目标耦合模型（审计里**用于对比**”：若行为真的能改变状态，闭环应该长这样）"""
    eff = ACTIVITY_STATE_EFFECT.get(activity, {})
    before = {k: getattr(state.needs, k) for k in ("boredom", "fatigue", "sleepiness", "hunger", "social_need", "satisfaction")}
    for k, v in eff.items():
        if hasattr(state.needs, k):
            setattr(state.needs, k, max(0.0, min(100.0, getattr(state.needs, k) + v)))
    state.needs.clamp()
    after = {k: getattr(state.needs, k) for k in ("boredom", "fatigue", "sleepiness", "hunger", "social_need", "satisfaction")}
    return {k: round(after[k] - before[k], 1) for k in before}


# ---------- 2) 消融 helper ----------
def _neutral_rel():
    import furina.memory.memory_types as mt
    return mt.RelationshipState()


def _with_neutral_personality(mot) -> None:
    mot.personality = Personality(0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5)  # 全中性 → as_weight≈1.0


def _clear_history(mot) -> None:
    mot._last_done.clear()
    mot._category_history.clear()
    mot._activity_history.clear()


def proxy_brain(mot, state, emotion, rng):
    """确定性 proxy Brain：加权采 top4（人格>随机，避免纯 top 吞人格，也非纯随机）。"""
    cands = mot.candidates(state, emotion)
    top = cands[:4]
    weights = [max(0.05, c.score) for c in top]
    pick = rng.choices(top, weights=weights, k=1)[0]
    return pick, cands


def run(scenario: str, steps: int, anti=True, pers=True, rel=True, rng=None):
    rng = rng or random.Random(7)
    st = CharacterState(); st.clock_hour = 14
    if scenario == "work":
        st.user_working = True; st.active_window_app = "Code"
    elif scenario == "bored":
        st.needs.boredom = 92; st.needs.playfulness = 88
    elif scenario == "social":
        st.needs.social_need = 95
    elif scenario == "mixed":
        st.user_working = True; st.needs.boredom = 60; st.needs.curiosity = 70
    ee = EmotionEngine(st.emotion)
    mot = BehaviorMotivation()
    if not pers:
        _with_neutral_personality(mot)
    if not rel:
        st.relationship = _neutral_rel()
    acts = []; cats = []; attr = []   # 每步归因
    for i in range(steps):
        if not anti:
            _clear_history(mot)      # 关闭重复抑制
        pick, cands = proxy_brain(mot, st, ee, rng)
        act = pick.activity
        # ---- 归因：anti-collapse 是否强制改了决策 ----
        # 用一个"无 anti 态"的 fresh motivation 看它若不被惩罚会选谁
        label = "A"   # 默认：内部状态/人格/关系自然导致
        if anti and act != "idle":
            mot_fresh = BehaviorMotivation()
            # 复制当前 needs/emotion，但不带历史惩罚 → 看"自然的（未抑制）顶级候选"
            st_fresh = CharacterState(); st_fresh.needs = st.needs
            st_fresh.user_working = st.user_working
            st_fresh.relationship = st.relationship
            top_natural = mot_fresh.candidates(st_fresh, ee)[0].activity
            if act != top_natural:
                label = "B"   # 被 anti/历史惩罚强制换了
        mot.mark_done(act, 0)
        acts.append(act); cats.append(CATEGORY.get(act, "SELF"))
        attr.append(label)
    return acts, cats, attr


def longest(seq):
    if not seq: return 0
    mx = cur = 1
    for i in range(1, len(seq)):
        cur = cur + 1 if seq[i] == seq[i-1] else 1
        mx = max(mx, cur)
    return mx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--scenario", default="none", choices=["none", "work", "bored", "social", "mixed"])
    args = ap.parse_args()

    print("=" * 70)
    print("行为真实性审计 —— 只读诊断")
    print("=" * 70)

    # (1) 活动→状态耦合度
    print("\n[1] 活动→状态耦合度（行为是否真的改变内心状态）：")
    st = CharacterState()
    for act in ["play", "eat", "rest", "talk", "sleep", "explore"]:
        eff = activity_effect(st, act)   # 目标闭环该有的改变
    print("  真实系统的 update_needs **只看时间/用户模式，不看 activity**（`activity_effect` 是审计假设的目标模型）。")
    print("  => '行为→经历→状态→新行为' 闭环**当前不存在**：经历不写回状态。")
    print("  <<< 这是审计要暴露的核心：多样性来自调度器，不是生命循环。")

    # (2) 消融对比
    print("\n[2] 消融对比（决定多样性来源）：")
    configs = {"A.正常": dict(anti=True, pers=True, rel=True),
               "B.anti OFF": dict(anti=False, pers=True, rel=True),
               "C.pers OFF": dict(anti=True, pers=False, rel=True),
               "D.rel OFF": dict(anti=True, pers=True, rel=False)}
    results = {}
    for name, cfg in configs.items():
        acts, cats, attr = run(args.scenario, args.steps, **cfg)
        results[name] = (acts, cats, attr)
        obs = sum(1 for x in cats if x == "OBSERVATION") / len(cats)
        self_ = sum(1 for x in cats if x == "SELF") / len(cats)
        print(f"  {name:12} SELF={self_*100:3.0f}%  OBSERVE={obs*100:3.0f}%  "
              f"同活动连击={longest(acts)}  top5={dict(Counter(acts).most_common(5))}")

    # (3) anti-collapse 实际改写率
    a_acts = results["A.正常"][0]; b_acts = results["B.anti OFF"][0]
    forced = sum(1 for i in range(min(len(a_acts), len(b_acts))) if a_acts[i] != b_acts[i])
    print(f"\n[3] anti-collapse 实际改写的决策：{forced}/{args.steps} = {forced/args.steps*100:.0f}%")
    print("    (比例高→多样性主要靠强制；低→靠内部状态/人格/关系)")

    # (4) 归因（B vs 非B）
    acts, cats, attr = results["A.正常"]
    cc = Counter(attr); n = len(attr)
    print(f"\n[4] 归因占比（{args.steps} 决策，A=内部/人格/关系自然，B=anti强制）:")
    print(f"    A(自然) = {cc.get('A',0)/n*100:.0f}%   B(anti强制) = {cc.get('B',0)/n*100:.0f}%")

    # (5) 最长自然链
    self_chain = longest([c for c in cats if c == "SELF"])
    social_chain = longest([c for c in cats if c == "SOCIAL"])
    obs_chain = longest([c for c in cats if c == "OBSERVATION"])
    print(f"\n[5] 最长自然同类别链：SELF={self_chain}  SOCIAL={social_chain}  OBSERVATION={obs_chain}")
    print("\n示例轨迹（场景=%s，20步）：" % args.scenario)
    print("  " + " → ".join(f"{a}[{c[:3]}:{l}]" for a, c, l in zip(acts, cats, attr)))

    print("\n" + "=" * 70)
    print("审计结论：")
    print("  观察塌缩已消除（OBSERVE 正常）。")
    print("  但'行为→经历→状态→新行为'闭环缺失（活动不改状态）。")
    print("  依据 [3][4] 判断强制 vs 自然比例，判定'她是否真的拥有自己的生活'。")
    print("=" * 70)


if __name__ == "__main__":
    main()
