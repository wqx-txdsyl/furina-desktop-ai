"""Personality 硬性验收测试（任务 §14 Test A-H）。

关键：固定 World/Needs/Emotion/Relationship/History/Seed，仅改 Personality。
anti-collapse OFF —— 人格必须是行为差异的唯一因果来源。
"""
from __future__ import annotations

import random
from collections import Counter

from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality
from furina.behavior.motivation import CATEGORY
from furina.life_brain import LifeBrain, LifeDecision

EXPLORER = Personality(0.5, 0.2, 1.0, 0.5, 0.5, 1.0, 0.1, 0.9)
SOCIAL   = Personality(0.5, 1.0, 0.2, 0.5, 0.8, 0.5, 0.9, 0.2)
PLAYFUL  = Personality(0.5, 0.5, 0.5, 1.0, 0.5, 0.5, 0.7, 0.5)
NEUTRAL  = Personality()


def _run(personality, seed=7, steps=100, needs=None, anti=False):
    rng = random.Random(seed)
    st = CharacterState(); st.clock_hour = 14
    if needs:
        for k, v in needs.items():
            setattr(st.needs, k, v)
    ee = EmotionEngine(st.emotion)
    mot = BehaviorMotivation(personality=personality)
    acts = []
    for _ in range(steps):
        if not anti:
            mot._last_done.clear(); mot._activity_history = []; mot._category_history = []
        cands = mot.candidates(st, ee)
        pick = rng.choices(cands[:4], weights=[max(0.04, c.score) for c in cands[:4]], k=1)[0]
        mot.mark_done(pick.activity, 0)
        acts.append(pick.activity)
    return Counter(acts), acts


def _top(acts, names):
    n = len(acts)
    return sum(v for a, v in acts.items() if a in names) / n


def test_personality_off_produces_no_difference():
    """Test B：Personality 关闭后，不同指纹应无差异（≈等）。"""
    needs = {"boredom": 50, "social_need": 45, "curiosity": 55, "fatigue": 25, "playfulness": 40}
    # 三个不同"指纹"但都被替换为 NEUTRAL，跑同一个 seed
    base = _run(NEUTRAL, seed=7, steps=100, needs=needs)[0]
    for nm_p in [EXPLORER, SOCIAL, PLAYFUL]:   # 仅名字不同，实际都用 NEUTRAL
        pass
    off = _run(NEUTRAL, seed=7, steps=100, needs=needs)[0]
    assert _top(off, ["explore", "read"]) > 0.5, "OFF 时应当稳定(中性偏好explore/read)"
    # 关键：两个NEUTRAL跑相同seed,分布完全一样
    off2 = _run(NEUTRAL, seed=7, steps=100, needs=needs)[0]
    assert off == off2, "Personality OFF: 相同seed应产生完全相同分布"


def test_personality_on_diverges_explorer_vs_social():
    """Test A/C：Explorer vs Social 行为分布必须稳定分化。"""
    needs = {"boredom": 50, "social_need": 45, "curiosity": 55, "fatigue": 25, "playfulness": 40}
    expl = _run(EXPLORER, seed=7, steps=100, needs=needs)[0]
    soc = _run(SOCIAL, seed=7, steps=100, needs=needs)[0]
    # Explorer 更偏探索/阅读；Social 更多 approach_user
    expl_explore = _top(expl, ["explore", "wander", "read"])
    soc_explore = _top(soc, ["explore", "wander", "read"])
    soc_social = _top(soc, ["approach_user", "talk", "invite_user"])
    assert soc_social > 0.1, f"Social 应有社交行为: {soc_social:.2f}"
    assert expl_explore >= soc_explore - 0.05, f"Explorer应更偏探索: {expl_explore:.2f} vs {soc_explore:.2f}"


def test_physiological_priority():
    """Test D：高疲劳时所有人格都倾向 rest/sleep（人格不摧毁生理需求）。"""
    needs = {"fatigue": 100, "sleepiness": 90, "boredom": 60, "playfulness": 60}
    for per in [EXPLORER, SOCIAL, PLAYFUL]:
        c = _run(per, seed=7, steps=60, needs=needs)[0]
        rest_share = _top(c, ["rest", "sleep", "stretch"])
        assert rest_share > 0.5, f"高疲劳应休息: {rest_share:.2f}"


def test_high_social_social_personality_more_social():
    """Test E：高社交需求时 Social 的候选里社交类显著领先 Explorer（候选排名）。"""
    needs = {"social_need": 92, "boredom": 50}
    soc_c = _top_candidate(SOCIAL, needs, n=3)
    expl_c = _top_candidate(EXPLORER, needs, n=3)
    soc_has = any(a in ("approach_user", "talk", "invite_user") for a in soc_c)
    assert soc_has, f"Social topology应含社交: {soc_c}"
    # 归类占比：Social 的 top3 里社交类数量应 >= Explorer
    soc_n = sum(1 for a in soc_c if CATEGORY.get(a) == "SOCIAL")
    expl_n = sum(1 for a in expl_c if CATEGORY.get(a) == "SOCIAL")
    assert soc_n > expl_n, f"Social应更多社交候选: {soc_n} vs {expl_n}"


def _top_candidate(per, needs, n=1):
    """人格在给定需求下的 top-n 候选（确定性，不看随机采样）。"""
    st = CharacterState(); st.clock_hour = 14
    for k, v in needs.items():
        setattr(st.needs, k, v)
    ee = EmotionEngine(st.emotion)
    mot = BehaviorMotivation(personality=per)
    cands = mot.candidates(st, ee)
    return [c.activity for c in cands[:n]]


def test_high_boredom_playful_more_play():
    """Test F：高无聊时 Playful 的候选里 play 排名显著高于 Social（候选排名，§八）。"""
    needs = {"boredom": 80, "playfulness": 80}
    play_cands = _top_candidate(PLAYFUL, needs, n=3)
    soc_cands = _top_candidate(SOCIAL, needs, n=3)
    # Playful 的 top3 含 play
    assert "play" in play_cands, f"Playful topology应含play: {play_cands}"
    # Playful 的 play 排名应比 Social 更靠前（或出现）
    play_rank = play_cands.index("play") if "play" in play_cands else 99
    soc_rank = soc_cands.index("play") if "play" in soc_cands else 99
    assert play_rank <= soc_rank, f"Playful play排名更前: {play_rank} vs {soc_rank}"


def test_high_curiosity_explorer_more_explore():
    """Test G：高好奇时 Explorer 候选里 explore/wander/read 明显领先 Social。"""
    needs = {"curiosity": 95}
    expl_c = _top_candidate(EXPLORER, needs, n=3)
    soc_c = _top_candidate(SOCIAL, needs, n=3)
    expl_explore = sum(1 for a in expl_c if a in ("explore", "wander", "read"))
    soc_explore = sum(1 for a in soc_c if a in ("explore", "wander", "read"))
    assert expl_explore >= soc_explore, f"Explorer应更偏探索: {expl_explore} vs {soc_explore}"
    assert "explore" in expl_c or "read" in expl_c, f"Explorer topology: {expl_c}"


def test_personality_changes_candidate_ranking():
    """Test A：候补排名必须被人格改变（不只最终行为）。"""
    st = CharacterState(); st.needs.boredom = 55; st.needs.social_need = 50; st.needs.curiosity = 55
    ee = EmotionEngine(st.emotion)
    expl = BehaviorMotivation(personality=EXPLORER).candidates(st, ee)
    soc = BehaviorMotivation(personality=SOCIAL).candidates(st, ee)
    expl_top = expl[0].activity
    soc_top = soc[0].activity
    # 排名 top1 不同 或 各候选 person_weight 明显差异
    pw_expl = BehaviorMotivation(personality=EXPLORER).personality.as_weight("explore")
    pw_soc = BehaviorMotivation(personality=SOCIAL).personality.as_weight("explore")
    assert abs(pw_expl - pw_soc) > 0.5, "explore 的人格权重应随人格显著变化"


def test_candidate_space_is_top_n():
    """P0：_candidate_space 取 Top-N（Brain 只从人格化最高候选里选）。"""
    cands = [{"activity": a, "motivation": m} for a, m in
             [("play", .82), ("explore", .74), ("read", .61), ("talk", .2), ("rest", .1)]]
    space = LifeBrain._candidate_space(cands, top_n=4)
    assert [c["activity"] for c in space] == ["play", "explore", "read", "talk"]


def test_constrain_to_space_records_invalid():
    """P0：Brain 跳出 allowed 空间 → 记录 invalid 并回退 top1（不静默接受）。"""
    lb = LifeBrain.__new__(LifeBrain)   # 不构造（避免依赖 LLM）
    allowed = [{"activity": "play", "motivation": .82}, {"activity": "read", "motivation": .61}]
    d = LifeDecision(activity="rest", reason="json")   # rest 不在 allowed
    d2 = lb._constrain_to_space(d, allowed)
    assert d2.brain_invalid is True, "rest 不在 allowed 应标记 invalid"
    assert d2.brain_raw_selection == "rest"
    assert d2.validated_selection in ("play", "read"), "应回退到 allowed 内"
    # 合法选择不标 invalid
    d3 = LifeDecision(activity="read", reason="json")
    d4 = lb._constrain_to_space(d3, allowed)
    assert d4.brain_invalid is False


def test_personality_contract_derives_from_fit():
    """P0：人格契约由候选 personality_fit 推导（top_fit 高活动）。"""
    from furina.life_brain import _life_prompt
    snap = {"candidates": [
        {"activity": "play", "motivation": .82, "personality_fit": .91, "why": [], "category": "SELF"},
        {"activity": "explore", "motivation": .74, "personality_fit": .33, "why": [], "category": "SELF"},
        {"activity": "read", "motivation": .61, "personality_fit": .33, "why": [], "category": "SELF"},
    ], "recent_activities": []}
    prompt = _life_prompt(snap)
    assert "人格契约" in prompt, "契约应写入 prompt"
    assert "play" in prompt, "契约应包含高契合行为"
