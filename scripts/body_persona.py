"""Phase 09 模拟：30 matched × 3 persona 对照 + 300 长跑 + Hard-Blind + Collapse Audit。

运行：python scripts/body_persona.py
"""
from __future__ import annotations

import sys, random, statistics
sys.path.insert(0, r"F:\program\Python\furina-work - 副本 (2)")
from collections import Counter

from furina.embodiment import (
    EmbodiedExpressionEngine, BodyValidator,
    FURINA_EMBODIMENT, NEUTRAL_EMBODIMENT, FORMER_MASK_EMBODIMENT,
)
from furina.dialogue import PersonaMode, DialogueAct

ENGINES = {
    "furina": EmbodiedExpressionEngine(FURINA_EMBODIMENT),
    "neutral": EmbodiedExpressionEngine(NEUTRAL_EMBODIMENT),
    "mask": EmbodiedExpressionEngine(FORMER_MASK_EMBODIMENT),
}
VAL = BodyValidator()

# (emotion, mode, activity, trust, familiarity, fatigue, dialogue_act, user_working)
def build_scenarios():
    S = []
    # 普通生活（松弛优先）
    for a in ("idle", "read", "rest", "think"):
        for e in ("calm", "happy", "sleepy"):
            S.append((e, PersonaMode.CASUAL.value, a, 0.5, 0.5, 25.0, "COMMENT", False))
    # 情感情感场
    for e in ("proud", "excited", "embarrassed", "annoyed", "sad", "lonely"):
        S.append((e, PersonaMode.PROUD.value if e in ("proud",) else PersonaMode.CASUAL.value,
                  "idle", 0.5, 0.5, 25.0, "COMMENT", False))
    for e in ("proud", "embarrassed", "sad"):
        # 表演 vs 真诚 vs 防御
        S.append((e, PersonaMode.PERFORMATIVE.value, "idle", 0.5, 0.4, 25.0, "BOAST", False))
        S.append((e, PersonaMode.SINCERE.value, "idle", 0.8, 0.8, 25.0, "ADMIT", False))
        S.append((e, PersonaMode.GUARDED.value, "idle", 0.2, 0.2, 25.0, "DEFLECT", False))
    # 关系反事实
    S.append(("calm", PersonaMode.RESPONSIBLE.value, "offer_help", 0.9, 0.9, 25.0, "OFFER_HELP", False))
    S.append(("calm", PersonaMode.RESPONSIBLE.value, "offer_help", 0.2, 0.2, 25.0, "OFFER_HELP", False))
    # 疲劳覆盖
    S.append(("proud", PersonaMode.PERFORMATIVE.value, "idle", 0.5, 0.5, 90.0, "BOAST", False))
    S.append(("proud", PersonaMode.PERFORMATIVE.value, "idle", 0.5, 0.5, 15.0, "BOAST", False))
    # 工作/专注/睡眠
    S.append(("calm", PersonaMode.RESPONSIBLE.value, "read", 0.5, 0.5, 30.0, "COMMENT", True))
    S.append(("sleepy", PersonaMode.CASUAL.value, "sleep", 0.5, 0.5, 60.0, "COMMENT", False))
    S.append(("calm", PersonaMode.CASUAL.value, "rest", 0.5, 0.5, 45.0, "COMMENT", False))
    return S


def run(persona_key, scenarios, silence_flags):
    eng = ENGINES[persona_key]
    outs = []
    for i, (emotion, mode, act, trust, fam, fatigue, da, uw) in enumerate(scenarios):
        silence = silence_flags[i]
        st = eng.express(emotion=emotion, mode=mode, dialogue_act=da,
                         relationship={"trust": trust, "comfort": trust,
                                       "annoyance": 0.1 if trust > 0.5 else 0.4,
                                       "familiarity": fam},
                         activity=act, fatigue=fatigue,
                         user_working=uw, silence=silence,
                         social_motive=0.4 + trust * 0.4,
                         recent_rejection=(trust == 0.2))
        st = VAL.validate(st, activity=act, fatigue=fatigue, silence=silence)
        outs.append(st)
    return outs


# ---------------------------------------------------------------- 指纹聚合
def fingerprint(outs):
    def pct(vals):
        c = Counter(vals)
        n = len(vals)
        return {k: round(v / n * 100, 1) for k, v in c.most_common()}
    return {
        "expression": pct([o.expression for o in outs]),
        "gaze": pct([o.gaze for o in outs]),
        "posture": pct([o.posture for o in outs]),
        "tempo": pct([o.movement_tempo for o in outs]),
        "transition": pct([o.transition_style for o in outs]),
        "micro": pct([m for o in outs for m in o.micro_motion]),
        "means": {
            "openness": round(statistics.mean(o.body_openness for o in outs), 3),
            "amplitude": round(statistics.mean(o.movement_amplitude for o in outs), 3),
            "hesitation": round(statistics.mean(o.hesitation for o in outs), 3),
            "composure": round(statistics.mean(o.composure for o in outs), 3),
        },
    }


def signature_vector(o):
    """Hard-Blind 用的纯身体向量（不含 persona/emotion/identity）。"""
    return {
        "expression": o.expression, "gaze": o.gaze, "posture": o.posture,
        "open": round(o.body_openness, 2), "tempo": o.movement_tempo,
        "amp": round(o.movement_amplitude, 2), "hes": round(o.hesitation, 2),
        "comp": round(o.composure, 2),
    }


def main():
    scenarios = build_scenarios()
    n = len(scenarios)
    print(f"matched scenarios = {n} (per person)  x 3 personas = {n*3} body decisions")
    # 一半静默（coexistence）
    rng = random.Random(7)
    silence_flags = [rng.random() < 0.5 for _ in scenarios]
    results = {}
    for k in ["furina", "neutral", "mask"]:
        outs = run(k, scenarios, silence_flags)
        results[k] = outs
        print(f"\n--- {k} ---")
        fp = fingerprint(outs)
        print("  means:", fp["means"])
        print("  top expression:", list(fp["expression"].items())[:4])
        print("  top gaze:", list(fp["gaze"].items())[:4])
        print("  top posture:", list(fp["posture"].items())[:4])
        print("  top tempo:", fp["tempo"])
        print("  top transition:", fp["transition"])
        print("  top micro:", list(fp["micro"].items())[:5])

    # ---- Hard-Blind: 只看身体向量，聚类区分三 persona（用均值向量两两距离）
    print("\n=== Hard-Blind 指纹（排除 persona/emotion/identity 标签，纯身体向量）===")
    mean_vec = {k: {f: statistics.mean(getattr(o, f) for o in results[k])
                    for f in ("body_openness", "movement_amplitude", "hesitation", "composure")}
                for k in ["furina", "neutral", "mask"]}
    for k, v in mean_vec.items():
        print(f"  {k}: { {f: round(x,3) for f,x in v.items()} }")
    # 两两欧氏距离（归一化特征）
    def dist(a, b):
        keys = ("body_openness", "movement_amplitude", "hesitation", "composure")
        return round(sum((mean_vec[a][k] - mean_vec[b][k]) ** 2 for k in keys) ** 0.5, 4)
    print(f"  furina-vs-neutral distance = {dist('furina','neutral')}")
    print(f"  furina-vs-mask    distance = {dist('furina','mask')}")
    print(f"  neutral-vs-mask   distance = {dist('neutral','mask')}")

    # ---- Collapse audit
    print("\n=== Collapse Audit（普通生活 + 全部场景）===")
    all_outs = results["furina"]
    gz = Counter(o.gaze for o in all_outs)
    user_gaze_pct = gz.get("USER", 0) / len(all_outs) * 100
    up = Counter(o.posture for o in all_outs)
    upright_pct = up.get("upright", 0) / len(all_outs) * 100
    expr_top = Counter(o.expression for o in all_outs).most_common(3)
    micro_all = Counter(m for o in all_outs for m in o.micro_motion)
    micro_top = micro_all.most_common(3)
    trans_top = Counter(o.transition_style for o in all_outs).most_common(3)
    print(f"  user-gaze%        = {user_gaze_pct:.1f}   (threshold 60)")
    print(f"  upright%          = {upright_pct:.1f}   (threshold 60)")
    print(f"  top expression    = {expr_top}")
    print(f"  top micro         = {micro_top}")
    print(f"  top transition    = {trans_top}")
    # longest identical body-state streak
    max_streak = 0; cur = 1
    for i in range(1, len(all_outs)):
        if EmbodiedExpressionEngine.signature(all_outs[i]) == EmbodiedExpressionEngine.signature(all_outs[i-1]):
            cur += 1
        else:
            cur = 1
        max_streak = max(max_streak, cur)
    print(f"  longest identical body-state streak = {max_streak}")

    # ---- 300 长跑：随机状态游走（确定性，无 LLM）
    print("\n=== 300-decision Long-run（随机状态游走）===")
    rng2 = random.Random(21)
    emos = ["calm", "happy", "sad", "proud", "embarrassed", "annoyed", "sleepy", "excited"]
    modes = [PersonaMode.CASUAL.value, PersonaMode.PERFORMATIVE.value, PersonaMode.PROUD.value,
             PersonaMode.GUARDED.value, PersonaMode.SINCERE.value, PersonaMode.PLAYFUL.value]
    acts = ["idle", "read", "rest", "play", "observe_user", "eat", "think", "sleep", "walk"]
    trace = []
    eng = ENGINES["furina"]
    for _ in range(300):
        st = eng.express(
            emotion=rng2.choice(emos), mode=rng2.choice(modes),
            dialogue_act=rng2.choice(["COMMENT", "BOAST", "OFFER_HELP", "ADMIT"]),
            relationship={"trust": rng2.random(), "comfort": rng2.random(),
                          "annoyance": rng2.random() * 0.5, "familiarity": rng2.random()},
            activity=rng2.choice(acts), fatigue=rng2.uniform(0, 100),
            silence=rng2.random() < 0.5, user_working=rng2.random() < 0.3,
            social_motive=rng2.random(), recent_rejection=rng2.random() < 0.2)
        st = VAL.validate(st, activity=st.posture or "idle", fatigue=0.0, silence=False)
        trace.append(st)
    print(f"  decisions = {len(trace)}")
    def dist(o):
        return {k: round(v / len(trace) * 100, 1) for k, v in Counter([getattr(x, o) for x in trace]).most_common(4)}
    print("  expression:", dist("expression"))
    print("  gaze:", dist("gaze"))
    print("  posture:", dist("posture"))
    print("  tempo:", dist("movement_tempo"))
    print("  transition:", dist("transition_style"))
    micro = Counter(m for o in trace for m in o.micro_motion)
    print("  micro:", [(k, round(v / sum(micro.values()) * 100, 1)) for k, v in micro.most_common(5)])
    # collapse check for long-run
    gz2 = Counter(o.gaze for o in trace)
    print(f"  long-run user-gaze% = {gz2.get('USER',0)/len(trace)*100:.1f}, "
          f"sigh% = {sum(1 for o in trace if 'SIGH' in o.micro_motion)/len(trace)*100:.1f}, "
          f"giggle% = {sum(1 for o in trace if 'GIGGLE' in o.micro_motion)/len(trace)*100:.1f}")


if __name__ == "__main__":
    main()
