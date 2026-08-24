"""Personality 长期人机验收（本轮）—— 真实 Brain 动态 Life Loop。

两个实验：
A. 静态反事实：固定 World/Needs/Emotion/Rel/History/Seed，仅改人格（已有数据，这里重跑含 Furina）。
B. 动态反事实：三个人格从相同初始状态同时运行 N steps，状态自然分叉，
   验证"人格 → 行为 → Outcome → 状态 → 行为"的二阶差异 + Personality Persistence。

全程 anti-collapse OFF。运行真实 LLM Brain。
"""
from __future__ import annotations

import sys, time, random, math
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
from furina.behavior.outcome import apply_outcome
from furina.memory.memory_types import RelationshipState

EXPLORER = Personality(0.5, 0.2, 1.0, 0.5, 0.5, 1.0, 0.1, 0.9)
SOCIAL = Personality(0.5, 1.0, 0.2, 0.5, 0.8, 0.5, 0.9, 0.2)
PLAYFUL = Personality(0.5, 0.5, 0.5, 1.0, 0.5, 0.5, 0.7, 0.5)
from furina.persona.furina_persona import FURINA_BEHAVIOR_PERSONALITY
FURINA = Personality(**FURINA_BEHAVIOR_PERSONALITY)


def make_runner(personality, name):
    cfg = load_config()
    lb = LifeBrain(get_adapter(cfg.llm.provider)(cfg.llm))
    def run(steps, seed=9, needs=None, user_schedule=None, record=False):
        rng = random.Random(seed)
        st = CharacterState(); st.clock_hour = 14
        if needs:
            for k, v in needs.items():
                setattr(st.needs, k, v)
        st.relationship = RelationshipState()
        ee = EmotionEngine(st.emotion)
        mot = BehaviorMotivation(personality=personality)
        trace = []
        for i in range(steps):
            # 时间 & 用户状态调度（周期性工作/空闲，模拟一天）
            w = (int(i / 20) % 2 == 0)
            idle = 0 if (i % 15 < 5) else 300
            # 需求漂移（真实动力学）+ 情绪衰减 + outcome 反馈形成 Life Loop
            st.clock_minute = (st.clock_minute + 5) % 60
            st.clock_hour = (st.clock_hour + 1 if st.clock_minute == 0 else st.clock_hour) % 24
            se = _dyn_needs(st, 30.0, w, idle)
            ee.decay(dt=30.0); ee.derive_label()
            mot._last_done.clear(); mot._activity_history = []; mot._category_history = []
            cands = [c.as_dict() for c in mot.candidates(st, ee, ctx={"talk_boost": 0.0 if w else 0.1})]
            before = {k: round(getattr(st.needs, k), 1) for k in ("boredom", "social_need", "curiosity", "fatigue")}
            st.life.activity = "idle"; st.intent.action = "idle"
            d = lb.decide(state=st, force=True, candidates=cands)
            act = d.activity
            apply_outcome(st, act, ee, relationship=st.relationship, recent_counts=None)
            st.life.activity = act; st.intent.action = act
            after = {k: round(getattr(st.needs, k), 1) for k in ("boredom", "social_need", "curiosity", "fatigue")}
            mot.mark_done(act, 0)
            if record:
                trace.append({"activity": act, "cat": CATEGORY.get(act),
                              "need_before": before, "need_after": after,
                              "emotion": ee.state.label, "selected": d.validated_selection,
                              "invalid": d.brain_invalid,
                              "top2": [c["activity"] for c in cands[:2]]})
        return {"trace": trace, "st": st, "ee": ee}
    return run


def _dyn_needs(st, dt, working, idle):
    """模拟 StateEngine.update_needs 的稳态积累（不引额外依赖）。"""
    n = st.needs
    if working:
        n.fatigue = max(0, min(100, n.fatigue + 0.55 * dt/30))
        n.boredom = max(0, min(100, n.boredom + 0.4 * dt/30))
    else:
        n.fatigue = max(0, min(100, n.fatigue + 0.06 * dt/30))
        n.boredom = max(0, min(100, n.boredom - 0.2 * dt/30))
    n.social_need = max(0, min(100, n.social_need + (0.10 if working else 0.0) * dt/30))
    n.energy = max(0, min(100, n.energy - 0.18 * dt/30))
    # 稳态再生（简化）
    for f, base, k in [("boredom", 28, .03), ("playfulness", 58, .03), ("curiosity", 66, .03),
                       ("social_need", 78, .028), ("fatigue", 25, .02), ("sleepiness", 12, .012)]:
        cur = getattr(n, f)
        if cur < base:
            setattr(n, f, cur + (base - cur) * min(1.0, k * dt/30))
    n.clamp()
    st.user_working = working
    st.user_idle_seconds = idle
    return st


def js(a, b):
    keys = list(set(a) | set(b))
    def n(d):
        s = sum(d.values()); return {k: v/(s or 1) for k, v in d.items()}
    pa, pb = n(a), n(b)
    m = {k: (pa.get(k, 0)+pb.get(k, 0))/2 for k in keys}
    def kl(p): return sum(p.get(k, 0)*math.log2((p.get(k, 0) or 1e-9)/(m[k] or 1e-9)) for k in keys if p.get(k, 0) > 0)
    return 0.5*kl(pa)+0.5*kl(pb)


def fingerprint(trace):
    acts = Counter(r["activity"] for r in trace)
    cats = Counter(r["cat"] for r in trace)
    n = len(trace)
    ent = -sum(v/n*math.log2(v/n) for v in acts.values() if v)
    def longest(seq):
        mx = cur = 1
        for i in range(1, len(seq)):
            cur = cur+1 if seq[i] == seq[i-1] else 1
            mx = max(mx, cur)
        return mx
    return {
        "SELF": cats.get("SELF", 0)/n, "SOCIAL": cats.get("SOCIAL", 0)/n,
        "explore": acts.get("explore", 0)/n, "play": acts.get("play", 0)/n,
        "read": acts.get("read", 0)/n, "talk": acts.get("talk", 0)/n,
        "approach": acts.get("approach_user", 0)/n,
        "entropy": ent, "streak": longest([r["activity"] for r in trace]),
        "n_distinct": len(acts),
    }


if __name__ == "__main__":
    import argparse as _a
    ap = _a.ArgumentParser()
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--mode", default="b", choices=["a", "b", "both"])
    ap.add_argument("--seed", type=int, default=9)
    args = ap.parse_args()
    # 只需导入，不在脚本里放重逻辑（重逻辑放在单独验证脚本）
    print(f"harness ready: steps={args.steps} mode={args.mode} seed={args.seed}")
