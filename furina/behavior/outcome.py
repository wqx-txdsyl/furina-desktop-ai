"""Activity Outcome（Life Simulation P2 闭环）—— 经历 → 状态反馈。

核心闭环：
    Activity → Activity Outcome → Needs/Emotion/Relationship feedback → State changed
    → Motivation recomputed → next Behavior

设计原则（至关紧要）：
 ① 这是**因果反馈**（行为做完 → 状态改变），**不是**行为选择规则。
    下一行为仍由 BehaviorMotivation 决定 —— 绝不做硬编码行为循环
   （如 play→boredom↓→→rest−→→…）。
 ② 区分反馈类型：
    - 即时 feedback：行为完成后立即改变状态
    - 情绪 feedback：行为产生 happiness / calm / excitement 等变化
    - 需求 feedback：play/rest/talk 满足对应需求
    - 关系 feedback：成功互动 / 被拒绝影响 Relationship
    - 失败/中断 feedback：行为没完成（被打断）时**不能假装获得完整收益**
 ③ 纯确定性程序，不用 LLM。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from furina.state import CharacterState
from furina.emotion.engine import EmotionEngine
from furina.memory.memory_types import RelationshipState

# 稳态基线（与 state_engine 的 _BASELINE 对齐；diminishing returns 用）
try:
    from furina.state.state_engine import _BASELINE
except Exception:  # pragma: no cover - 避免循环导入时兜底
    _BASELINE = {"boredom": 28.0, "playfulness": 38.0, "curiosity": 50.0,
                 "satisfaction": 62.0, "social_need": 45.0, "energy": 75.0,
                 "sleepiness": 12.0, "hunger": 22.0, "fatigue": 25.0, "work_interest": 50.0}


@dataclass
class Outcome:
    """一个活动完成后对状态的影响（delta）。"""
    needs: Dict[str, float] = field(default_factory=dict)       # e.g. {"boredom": -12, "hunger": -55}
    emotion: Dict[str, float] = field(default_factory=dict)     # e.g. {"happiness": +5, "calm": +3}
    relationship: Dict[str, float] = field(default_factory=dict)  # e.g. {"familiarity": +1}
    social_need: float = 0.0        # 直接结算社交需求（talk 满足它）
    success: bool = True            # 失败/中断时不获得完整收益

    # 对 state 的"目标"标记（给诊断/可解释用）
    note: str = ""


# 活动 → 完成后的因果影响（数据表；数值越小越温和，避免"一步到位"）
OUTCOMES: Dict[str, Outcome] = {
    # ---- SELF 自主（需求反馈：满足对应动机来源）----
    "play":   Outcome(needs={"boredom": -14, "playfulness": -12, "energy": -3},
                      emotion={"happiness": +5, "excitement": +3}, note="玩了一小会儿，满足玩耍欲"),
    "explore": Outcome(needs={"boredom": -10, "curiosity": -9},
                       emotion={"excitement": +4, "curiosity": +2}, note="探索到有趣的东西，好奇得到满足"),
    "read":   Outcome(needs={"boredom": -8, "curiosity": -7, "energy": -2},
                      emotion={"calm": +4}, note="读完一段，充实"),
    "drink":  Outcome(needs={"hunger": -18}, emotion={"calm": +2}, social_need=+2, note="喝了口茶"),
    "eat":    Outcome(needs={"hunger": -52, "energy": +4}, emotion={"happiness": +5}, note="吃饱了"),
    "stretch": Outcome(needs={"fatigue": -12, "energy": +5, "boredom": -3},
                       emotion={"calm": +3}, note="拉伸了一下，缓解疲劳"),
    "rest":   Outcome(needs={"fatigue": -18, "energy": +12, "sleepiness": -6},
                      emotion={"calm": +4}, note="好好休息了一会儿"),
    "sleep":  Outcome(needs={"fatigue": -42, "energy": +18, "sleepiness": -45},
                      emotion={"calm": +5}, note="睡了个好觉"),
    "tidy":   Outcome(needs={"boredom": -6}, emotion={"pride": +3}, note="整理了下桌面"),
    "think":  Outcome(needs={"boredom": -4}, emotion={"calm": +3}, note="想事情"),
    "daydream": Outcome(needs={"boredom": -5}, emotion={"calm": +4, "happiness": +2}, note="发呆"),
    "wander": Outcome(needs={"boredom": -8, "curiosity": -5}, note="随便溜达"),
    "idle":   Outcome(needs={"boredom": +1}, note="随意待着"),
    # ---- SOCIAL（需求反馈：满足社交需求）----
    # Phase 13 终审 §6.2：**活动 Outcome 不再携带 relationship delta**（自我农场：芙宁娜不能因"自己
    # 选择靠近/搭话/帮忙"就自动涨 trust/comfort）。关系只能由 RelationshipEngine 从真实关系证据写入
    # （用户回应 / 接受-拒绝互动 / 已验证的 Agent 帮助等）。
    # §6.3：social_need 只经唯一字段结算一次（不在 needs dict 重复出现）。
    "approach_user": Outcome(needs={}, social_need=-40, emotion={"happiness": +3}, note="靠近了用户"),
    "talk":    Outcome(social_need=-45, emotion={"happiness": +5, "loneliness": -6}, note="和用户聊了聊"),
    "invite_user": Outcome(social_need=-38, emotion={"happiness": +4, "excitement": +3}, note="邀请用户一起"),
    "greet":   Outcome(social_need=-12, emotion={"happiness": +4}, note="和用户打了个招呼"),
    "comfort": Outcome(emotion={"happiness": +3, "calm": +2}, social_need=-10, note="安慰用户"),
    "celebrate": Outcome(emotion={"happiness": +6, "excitement": +5}, social_need=-8, note="一起庆祝"),
    "seek_attention": Outcome(social_need=-16, emotion={"happiness": +3}, note="引起用户注意"),
    "ask_user":  Outcome(social_need=-12, emotion={"curiosity": +2}, note="问了用户一句"),
    "comment":   Outcome(social_need=-8, note="随口说了句"),
    "watch_user": Outcome(needs={"social_need": +2}, emotion={"loneliness": -3}, note="看着用户"),
    # ---- OBSERVATION ----
    "observe_user": Outcome(emotion={"loneliness": -2}, social_need=+3, note="看看用户在干嘛"),
    "observe_work": Outcome(emotion={"curiosity": +2}, note="看用户工作"),
    "look_around":  Outcome(needs={"curiosity": -6}, note="环顾四周"),
    # ---- ASSISTANCE（无关系奖励：帮不帮忙是她的选择，信任来自真实结果）----
    "offer_help": Outcome(emotion={"pride": +4, "happiness": +3}, social_need=-6, note="主动想帮忙"),
    "assist_user": Outcome(emotion={"pride": +4}, social_need=-4, note="帮忙做事"),
}


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def outcome_for(activity: str, success: bool = True) -> Outcome:
    """取活动的因果影响；未知活动给空反馈（不改变状态，避免凭空造因果）。

    FINAL-R1 §5：返回**深拷贝**（dataclasses.replace 只浅拷贝 needs/emotion dict，
    会与全局 OUTCOMES 共享可变 dict）—— 调用方改副本不影响全局 spec。
    success 只写进副本（全局 spec 保持 True）。
    """
    import copy
    o = copy.deepcopy(OUTCOMES.get(activity, Outcome()))
    o.success = success
    return o


def apply_outcome(state: CharacterState, activity: str, emotion: EmotionEngine,
                  success: bool = True, progress: Optional[float] = None,
                  relationship: Optional[RelationshipState] = None,
                  recent_counts: Optional[Dict[str, int]] = None) -> Outcome:
    """把活动的因果反馈应用到当前状态（needs + emotion）。

    **FINAL-R1 §5 进度感知**：
      - success=True（completed）→ scale = 1.0（全额）；
      - success=False（interrupted/aborted/failed）→ scale = 0.3 + 0.7×progress
        （progress=10% → 0.37；70% → 0.79；未给 progress 时默认 50% 中断 → 0.65，兼容旧"减半"语义）。
      不假装完成。

    **Diminishing returns（§）**：依赖当前需求状态 + recent_counts（自然涌现，非 anti-collapse）。
    """
    o = outcome_for(activity, success)
    if progress is None:
        progress = 0.5 if not o.success else 1.0
    scale = 1.0 if o.success else (0.3 + 0.7 * max(0.0, min(1.0, progress)))
    # 连续做同一种活动 → 收益递减（重复抑制的自然涌现，非行为选择规则）
    rep = recent_counts.get(activity, 0) if recent_counts else 0
    rep_scale = max(0.3, 1.0 - 0.25 * rep)      # 1次=0.75, 2次=0.5, 3次=0.3
    n = state.needs
    # 行为满足需求时保留的"残余"下限（避免 sleep 把 fatigue 打到 0 造成锯齿）
    _FLOOR = {"fatigue": 32.0, "sleepiness": 8.0, "hunger": 25.0, "energy": 10.0}
    for k, v in o.needs.items():
        if hasattr(n, k):
            cur = getattr(n, k)
            # 若反馈是要"降低该需求"（v<0，满足它），且需求已很低 → 递减（不把需求清零）。
            # diminish：需求越低可满足空间越小。需求=100 → 全效；需求=0 → 几乎无效。
            if v < 0:
                avail = _clamp01(cur / 100.0 + 0.12)   # 随当前值
                delta = v * avail * rep_scale * scale
            else:
                delta = v * rep_scale * scale
            new_val = cur + delta
            if v < 0 and k in _FLOOR:
                new_val = max(new_val, min(_FLOOR[k], cur))   # 不低于残余下限（也不高于原值）
            setattr(n, k, max(0.0, min(100.0, new_val)))
    # 情绪反馈（生命感：做某件事会带来特定情绪；也受重复递减影响）
    st_e = emotion.state
    for k, v in o.emotion.items():
        if hasattr(st_e, k):
            setattr(st_e, k, max(0.0, min(100.0, getattr(st_e, k) + v * rep_scale * scale)))
    # 社交需求单独结算（同样递减）—— §6.3：唯一字段，恰好一次
    if o.social_need:
        cur_s = n.social_need
        avail = _clamp01(cur_s / 100.0 + 0.12) if o.social_need < 0 else 1.0
        n.social_need = max(0.0, min(100.0, cur_s + o.social_need * avail * rep_scale * scale))
    # Phase 13 终审 §6.2：**活动 Outcome 不写关系**（OUTCOMES 已不含 relationship delta）。
    # 关系只由 RelationshipEngine 从真实关系证据写入；relationship 参数保留仅为签名兼容。
    n.clamp()
    return o
