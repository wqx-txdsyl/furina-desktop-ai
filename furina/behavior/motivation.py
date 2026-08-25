"""Behavior Motivation（Life Simulation P2 任务 2/3/4/5/6/11/13/14）—— 候选行为冲动评分。

从"顺序打分"升级为：
  Internal State + Emotion + Relationship + World + Recent Behavior + Interaction History
  → Motivation
  → Brain 人格化选择

核心目标：**任何一个安全行为（尤其 observe_user）都不能成为所有场景的隐性 fallback。**
- 每个候选带 **grounding why**（§1.2），Brain 能理解分数来源
- Personality 权重（§2，来自 Persona 配置，不用 LLM）
- Relationship（familiarity/trust/annoyance + 动态 interaction_frequency）参与 Motivation（§11-12）
- talk 作为**独立候选**，带 speech_opportunity + speech_reason（§6-7）
- 拒绝/回应 → interaction_tolerance 真实变化（§13-14）
- **production anti-collapse = OFF（评审基线 0402e7f）**：不再有类别/活动/观察占比的
  纯多样性惩罚（§3/§4/§5 的 _category_penalty/_activity_penalty/_observation_crush_guard
  已整体移除）。多样性只能来自 Needs/Emotion/Personality/Identity/Relationship/World/
  Memory/可行性；最近行为只作 context/grounding/reason（如 needs outcome、用户拒绝的
  因果抑制），绝不作"刚做过所以必须换一个"的人工节拍器。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from furina.state import CharacterState
from furina.emotion.engine import EmotionEngine

# ---------------------------------------------------------------- 类别
CATEGORY = {
    # SELF：自己的事（自主生活）
    "read": "SELF", "drink": "SELF", "eat": "SELF", "play": "SELF", "explore": "SELF",
    "stretch": "SELF", "rest": "SELF", "think": "SELF", "tidy": "SELF", "daydream": "SELF",
    "wander": "SELF", "play_with_object": "SELF",
    # SOCIAL：主动与用户互动
    "approach_user": "SOCIAL", "talk": "SOCIAL", "invite_user": "SOCIAL",
    "greet": "SOCIAL", "comfort": "SOCIAL", "celebrate": "SOCIAL", "seek_attention": "SOCIAL",
    "ask_user": "SOCIAL", "comment": "SOCIAL",
    # OBSERVATION：观察用户/环境（易塌缩为隐性 idle）
    "observe_user": "OBSERVATION", "observe_work": "OBSERVATION", "look_around": "OBSERVATION",
    "watch_user": "OBSERVATION",
    # ASSISTANCE：帮用户
    "offer_help": "ASSISTANCE", "assist_user": "ASSISTANCE",
    # NEED：生存
    "sleep": "NEED", "nap": "NEED",
    # 兜底
    "idle": "SELF",
}
SELF = "SELF"; SOCIAL = "SOCIAL"; OBSERVATION = "OBSERVATION"; ASSISTANCE = "ASSISTANCE"

# ---------------------------------------------------------------- Personality（§2）
@dataclass
class Personality:
    """角色层面行为倾向（来自 Persona 配置，数据驱动，不用 LLM）。

    确定性、稳定、不由 LLM 每次生成、不因一次行为改变（本阶段禁止人格学习）。
    范围为 0..1；0.5 = 中性（无偏好），越高越倾向该维度。
    """
    self_activity_preference: float = 0.5   # 更爱自己做自己的事
    social_activity_preference: float = 0.5  # 更主动接近用户
    exploration_preference: float = 0.5     # 更爱探索
    play_preference: float = 0.5            # 更爱玩
    helpfulness: float = 0.5                # 更爱观察工作并帮忙
    curiosity: float = 0.5                  # 更爱探索/求知
    attention_seeking: float = 0.4          # 更爱发起交流
    independence: float = 0.5               # 更能自己待着

    def as_weight(self, activity: str) -> float:
        """活动级人格权重倍率（~0.25~1.85；0.5 中性 = 1.0）。"""
        return max(0.25, min(1.85, 1.0 + self._personality_fit(activity)))

    def _personality_fit(self, activity: str) -> float:
        """人格与活动的"契合度"偏移（-1~+1）：= 各人格字段对齐度的加权和。

        0 = 中性；正 = 人格特别偏好此活动；负 = 人格疏远此活动。
        这是 **Preference**（人格偏好），与 **Need Pressure**（需求压力）区分开。
        """
        p = self
        base = {
            "explore": [("exploration_preference", 0.9), ("curiosity", 0.9), ("independence", 0.5)],
            "wander":  [("exploration_preference", 0.8), ("curiosity", 0.6), ("independence", 0.5)],
            "look_around": [("exploration_preference", 0.7), ("curiosity", 0.7), ("independence", 0.4)],
            "read":    [("curiosity", 0.8), ("self_activity_preference", 0.6), ("independence", 0.5)],
            "play":    [("play_preference", 1.2), ("attention_seeking", 0.3)],
            "play_with_object": [("play_preference", 1.2)],
            "think":   [("self_activity_preference", 0.5), ("independence", 0.5)],
            "daydream": [("self_activity_preference", 0.6), ("independence", 0.5)],
            "tidy":    [("self_activity_preference", 0.5), ("helpfulness", 0.2)],
            "rest":    [("independence", 0.3), ("self_activity_preference", 0.3)],
            "sleep":   [("independence", 0.3)],
            "approach_user": [("social_activity_preference", 1.0), ("attention_seeking", 0.8)],
            "talk":    [("social_activity_preference", 1.1), ("attention_seeking", 1.0)],
            "invite_user": [("social_activity_preference", 1.0), ("attention_seeking", 0.8)],
            "greet":   [("social_activity_preference", 0.9), ("attention_seeking", 0.8)],
            "comfort": [("social_activity_preference", 0.8), ("helpfulness", 0.5)],
            "celebrate": [("social_activity_preference", 0.9), ("attention_seeking", 0.7)],
            "seek_attention": [("attention_seeking", 1.2), ("social_activity_preference", 0.6)],
            "ask_user": [("social_activity_preference", 0.8), ("attention_seeking", 0.7)],
            "comment": [("social_activity_preference", 0.7), ("attention_seeking", 0.6)],
            "watch_user": [("social_activity_preference", 0.4), ("attention_seeking", 0.3)],
            "offer_help": [("helpfulness", 1.1), ("social_activity_preference", 0.6)],
            "assist_user": [("helpfulness", 1.0)],
            "observe_user": [("social_activity_preference", 0.3), ("attention_seeking", 0.3)],
            "observe_work": [("helpfulness", 0.4)],
            "drink": [("self_activity_preference", 0.4)],
            "eat":   [("self_activity_preference", 0.4)],
        }
        terms = base.get(activity) or [("self_activity_preference", 0.3)]
        fit = 0.0
        for field, strength in terms:
            fit += (getattr(p, field, 0.5) - 0.5) * strength
        return fit

    def fit_for(self, activity: str) -> float:
        """人格与该行为的契合度（0..1 归一化，用于 Debug 的 personality_fit 字段）。"""
        fit = self._personality_fit(activity)
        # 把 -1.2..1.85 映射到 0..1
        return max(0.0, min(1.0, (fit + 1.0) / 3.0))


def _needs(s: CharacterState) -> dict:
    return {
        "energy": s.needs.energy, "hunger": s.needs.hunger, "fatigue": s.needs.fatigue,
        "sleepiness": s.needs.sleepiness, "boredom": s.needs.boredom,
        "social_need": s.needs.social_need, "curiosity": s.needs.curiosity,
        "playfulness": s.needs.playfulness, "satisfaction": s.needs.satisfaction,
    }


def _rel(state: CharacterState) -> dict:
    """从关系状态取 0..1 关系因子（C-R2 §7：只经 canonical relationship_factors()）。"""
    rel = getattr(state, "relationship", None)
    from furina.relationship.engine import relationship_factors
    if rel is None:
        rel = {}
    if isinstance(rel, dict):
        # 若已是 normalized factors 字典，直接透传（保留派生键）
        out = relationship_factors({})   # 先给默认
        for k in ("familiarity", "trust", "comfort", "annoyance", "attachment",
                  "interaction_tolerance", "social_confidence", "respect",
                  "user_response_rate", "user_rejection_rate", "response_rate",
                  "confidence", "interaction_freq"):
            if k in rel:
                out[k] = float(rel[k])
        return out
    return relationship_factors(rel)


def _why_for(activity: str, state: CharacterState, emotion: EmotionEngine,
             rel: dict, ctx: dict) -> List[str]:
    """该候选获得分数的**可解释原因**（§1.2，Brain 需要理解分数来源）。"""
    n = _needs(state); e = emotion.behavior_tendency(); w = []
    if activity == "play" and n["boredom"] > 55:
        w.append("boredom_high")
    if activity == "play" and n["playfulness"] > 55:
        w.append("playfulness_high")
    if activity == "observe_user":
        if state.user_working:
            w.append("user_working")
        if rel["confidence"] > 0.5:
            w.append("safe_to_observe")
    if activity == "approach_user":
        if n["social_need"] > 55:
            w.append("social_need_high")
        if not state.user_working:
            w.append("user_available")
        if rel["attachment"] > 0.5:
            w.append("close_relationship")
    if activity == "talk":
        if ctx.get("interesting_event"):
            w.append("interesting_event")
        if ctx.get("long_silence"):
            w.append("long_silence")
        if n["social_need"] > 55:
            w.append("social_need_high")
    if activity == "explore" and (n["curiosity"] > 55 or e["explore_bias"] > 50):
        w.append("curiosity_high")
    if activity == "read" and n["curiosity"] > 45:
        w.append("curiosity_medium")
    if activity == "rest" and n["fatigue"] > 55:
        w.append("fatigue_high")
    if activity == "rest" and n["sleepiness"] > 55:
        w.append("sleepy_high")
    if activity == "offer_help" and rel["trust"] > 0.6:
        w.append("trust_high")
    return w or ["need_baseline"]


# ---------------------------------------------------------------- 主导需求唤起
# 类别对需求的亲和度（每个类别主要由哪些需求驱动）
_CATEGORY_AFFINITY = {
    SELF: 0.45, SOCIAL: 0.55, OBSERVATION: 0.0, ASSISTANCE: 0.35, "NEED": 0.6,
}
# 具体活动对应的"满足哪个需求"（用于 urgency 联动）
_NEED_OF = {
    "play": "boredom", "explore": "curiosity", "read": "curiosity", "wander": "boredom",
    "approach_user": "social_need", "talk": "social_need", "invite_user": "social_need",
    "comfort": "social_need", "celebrate": "social_need", "observe_user": "social_need",
    "rest": "fatigue", "sleep": "sleepiness", "stretch": "fatigue", "eat": "hunger",
    "drink": "hunger", "tidy": "boredom", "assist_user": "work_interest", "offer_help": "work_interest",
}


def _need_affinity(activity: str, n: dict) -> float:
    """该活动主要满足的需求在当前有多迫切（0..1）。"""
    key = _NEED_OF.get(activity)
    if key and key in n:
        needle = n[key] / 100.0
        # 满足度越高越迫切；用二次曲线让高需求显著抬升
        return needle * needle
    return 0.0


def _survival_pressure(n: dict) -> float:
    """生存需求紧迫度（0..1）：fatigue/hunger/sleepiness 越紧迫，人格权重越应退让（§四）。"""
    # 用三次曲线：只有真的接近危急（>70）才显著抑制人格
    s = max(n["fatigue"], n["hunger"], n["sleepiness"])
    return _clamp((s - 60.0) / 40.0) ** 1.5 if s > 60 else 0.0


def _dominant_need(n: dict) -> str:
    """当前最迫切的"动机型"需求（boredom/social/curiosity/playfulness 中最高者）。"""
    return max(("boredom", "social_need", "curiosity", "playfulness"),
               key=lambda k: n[k])


def _dominant_urgency(n: dict) -> float:
    """当前最迫切的"动机型"需求强度，0..1。"""
    return n[_dominant_need(n)] / 100.0


# 角色身份 → 各活动的 identity_fit（appraisal 分量 + 价值观决定"这个行为含角色意义吗"）
# 用户定向行为（在 away 时不可行）
_USER_DIRECTED = {"approach_user", "observe_user", "observe_work", "watch_user",
                  "invite_user", "comfort", "offer_help", "assist_user"}
# 需要用户在场才可行
_NEEDS_USER = _USER_DIRECTED | {"talk", "greet", "seek_attention", "ask_user",
                                "comment", "celebrate", "react_to_user"}


def _feasible(activity: str, state, ctx=None) -> tuple[bool, List[str]]:
    """Affordance（可执行性）判定 —— 回答"现在能不能做"，与 Motivation（想不想做）分离。

    user away → 用户定向行为**不可行**（不进入 Brain allowed space）。
    user present + deep focus → 仍 feasible（只是 Motivation 被 cost 压）。
    user returned → 重新开放。
    不新增行为规则；SELF 行为始终可行。
    """
    ctx = ctx or {}
    if ctx.get("world_off"):
        return True, []   # World OFF：不做约束
    wf = ctx.get("world") or (getattr(state, "world", None) and getattr(state.world, "factors")())
    if wf is None:
        return True, []
    present = wf.get("user_present", 1.0)
    availability = wf.get("availability", 1.0)
    user_working = wf.get("user_working", 0.0)
    presence_known = wf.get("presence_known", 1.0)
    # Pre-Manual §5：**在场未知（presence_known=0，OS idle 不可用）→ 用户定向行为不可行**
    # （unknown ≠ away，但也不得主动假设用户可用；reason 用 user_presence_unknown）
    if presence_known < 0.5:
        if activity in _NEEDS_USER:
            return False, ["user_presence_unknown", "world_idle_unavailable"]
        return True, []
    # 用户不在场 → 用户定向行为 infeasible
    if present < 0.5:
        if activity in _NEEDS_USER:
            return False, ["user_unavailable", "world_activity_away"]
        return True, []
    # 用户在场：deep focus 不 filter（仅 motivation 降权），talk 在可用≈0 时也不是普通主动
    if activity in _NEEDS_USER and availability < 0.1 and user_working > 0.5:
        if activity in ("talk", "greet", "seek_attention", "ask_user", "comment"):
            return False, ["user_unavailable", "low_availability"]
    return True, []


def _world_factors(state, ctx=None) -> Optional[dict]:
    """从 state/ctx 读归一化世界因子；无则 None（World Influence 可关闭）。"""
    ctx = ctx or {}
    if ctx.get("world_off"):
        return None
    # 显式注入（scheduler 传）优先，否则从 state.world 读
    if ctx.get("world"):
        return ctx["world"]
    w = getattr(state, "world", None)
    if w is None:
        return None
    if hasattr(w, "factors"):
        return w.factors()
    return None


def _apply_world(base: float, activity: str, wf: dict) -> tuple[float, List[str]]:
    """世界因子 → 候选环境修正（只改环境，不指定 Activity；防 observe fallback）。"""
    tags: List[str] = []
    cost = wf.get("interruption_cost", 0.0)
    availability = wf.get("availability", 1.0)
    focus = wf.get("focus", 0.0)
    working = wf.get("user_working", 0.0)
    present = wf.get("user_present", 1.0)
    assist = wf.get("assistance_opportunity", 0.0)
    cat = CATEGORY.get(activity, SELF)

    # 深度工作 → 主动社交（SOCIAL/ASSISTANCE 的主动部分）被压，但 SELF/OBSERVATION 不被压
    if cost > 0.6:
        if activity in ("talk", "approach_user", "invite_user", "seek_attention", "ask_user"):
            base *= 0.5
            tags.append("user_deep_focus")
            tags.append("high_interruption_cost")
        if activity == "greet":
            base *= 0.6
            tags.append("user_deep_focus")
    # 用户离开 → SELF 活动稍抬，社交压死（不打扰）
    if present < 0.5:
        if cat == SELF:
            base *= 1.15
            tags.append("user_away")
        if activity in ("talk", "approach_user", "invite_user", "seek_attention"):
            base *= 0.3
            tags.append("user_away")
    # 用户刚回来（user_working=0 且 present，看是否 user idle 低）→ 反应/社交机会
    if present > 0.5 and working == 0.0 and availability > 0.6:
        if activity in ("talk", "approach_user", "greet", "watch_user"):
            base *= 1.12
            tags.append("user_available")
    # 协助机会（忙碌+深度+可帮）→ offer_help 抬、但仅"maybe"，不硬顶
    if assist > 0.4 and activity in ("offer_help", "assist_user"):
        base = base * (1.0 + assist * 0.4)
        tags.append("help_possible")
    if assist > 0.4 and activity in ("talk", "invite_user"):
        base *= 0.75
        tags.append("user_focused")
    # 有趣上下文 → 探索/好奇机会
    if wf.get("interesting_context", 0) > 0.5 and activity in ("explore", "look_around", "observe_work"):
        base *= 1.1
        tags.append("interesting_context")
    return base, tags


def _identity_activity_fit(identity, ap, activity) -> tuple[float, List[str]]:
    """返回 (activity 的 identity_fit 0..1, 原因列表)。

    Furina 身份：她重视认可/尊严/能力，喜欢戏剧化、爱伴侣。不同 appraisal 分量
    会让她对"表演/展现/庆祝/陪伴"等行为更有意义感 —— 这就是 Identity ≠ Personality。
    """
    if activity is None:
        return 0.0, []
    vals = identity.values
    a = ap
    fit = 0.0
    reasons: List[str] = []
    def add(cond, score, reason):
        nonlocal fit
        if cond:
            fit += score
            reasons.append(reason)
    # 表演/展现：戏剧化呈现高 + 有表演机会
    add(activity in ("celebrate", "dance", "excited") and a.performance_opportunity > 0.3,
        a.performance_opportunity * identity.dramatic_self_presentation * 0.5, "performance_opportunity")
    # 求关注但不显得需要：talk/approach 在认可机会高时更自然
    add(activity in ("talk", "approach_user", "greet", "seek_attention") and a.recognition_opportunity > 0.3,
        a.recognition_opportunity * vals.get("recognition", 0.5) * 0.4, "recognition_opportunity")
    # 尊严受威胁 → 反而收敛主动/转向展示能力（offer_help/celebrate 是"证明自己"）
    add(activity in ("offer_help", "assist_user", "celebrate") and a.dignity_threat > 0.3,
        a.dignity_threat * identity.desire_to_be_seen_as_capable * 0.4, "dignity_threat_competence")
    # 陪伴机会 + 重视陪伴 → 社交类更自然
    add(activity in ("talk", "approach_user", "invite_user", "comfort") and a.companionship_opportunity > 0.3,
        a.companionship_opportunity * vals.get("companionship", 0.5) * 0.4, "companionship_opportunity")
    # 责任 cue → 帮忙/负责更有意义
    add(activity in ("offer_help", "assist_user", "comfort") and a.responsibility_cue > 0.3,
        a.responsibility_cue * vals.get("responsibility", 0.5) * 0.4, "responsibility_cue")
    # 脆弱压力：失败后 → 她更倾向"待在安全的自己活动"（非刷存在感）
    add(activity in ("read", "think", "daydream", "rest") and a.vulnerability_pressure > 0.5,
        -a.vulnerability_pressure * 0.2, "vulnerability_retreat")
    return max(0.0, min(1.0, fit)), reasons


class BehaviorMotivation:
    """候选行为评分器。Brain 决策前调用，得到带 why 的候选冲动分。"""

    def __init__(self, personality: Optional[Personality] = None,
                 identity=None, memory_engine=None) -> None:
        self.personality = personality or Personality()
        self.identity = identity                      # Character Identity（Phase 05）
        self.memory_engine = memory_engine            # 记忆引擎（Phase 07，可为 None）
        self._last_done: Dict[str, float] = {}          # activity → 最后做的时间
        self._category_history: List[str] = []          # 最近类别序列（反塌缩/多样性）
        self._activity_history: List[str] = []          # 最近活动序列
        self._last_speech: float = 0.0                  # 最近发言时间
        self._interaction_tolerance: float = 50.0       # 用户对主动的接纳度（§13）

    # -------------------------------------------------- 反馈（§13-14：拒绝/回应必须真改变未来行为）
    def _memory_interpret(self, state, ctx=None) -> dict:
        """Memory → Interpretation（§14）：检索现在相关记忆 → 确定性解释 → memory_fit/reasons。

        OFF：ctx['memory_off']=True 或 无 memory_engine → 返回中性。
        绝不做第二套 Relationship（§15）：只输出 context-specific expectation。
        """
        if ctx is None:
            ctx = {}
        if ctx.get("memory_off") or self.memory_engine is None:
            return {"risk": 0.0, "pos": 0.0, "help": 0.0, "salience": 0.0,
                    "reasons": [], "memories": []}
        wf = _world_factors(state, ctx) or {}
        # context 取结构化 world 活动的 user_activity（factors() 不含它，从 state.world.state 读）
        context = getattr(getattr(state, "world", None) and state.world.state, "user_activity", "")
        context = context.value if hasattr(context, "value") else (context or "")
        if not context:
            context = wf.get("user_activity", "") or getattr(state, "activity_context", "")
        mems = self.memory_engine.retrieve(query="", limit=6, context=context or None,
                                           tags=[context] if context else None)
        interp = self.memory_engine.interpret(mems, context=context or "")
        reasons = []
        if interp["interaction_risk"] > 0.4:
            reasons.append("similar_context_previous_rejection")
        if interp["positive_expectation"] > 0.4:
            reasons.append("similar_context_positive")
        if interp["help_expectation"] > 0.4:
            reasons.append("previous_help_was_welcomed")
        return {"risk": interp["interaction_risk"], "pos": interp["positive_expectation"],
                "help": interp["help_expectation"], "salience": interp["memory_salience"],
                "reasons": reasons, "memories": mems}

    # -------------------------------------------------- 反馈（§13-14：拒绝/回应必须真改变未来行为）
    def _appraise(self, state, activity=None, ctx=None) -> dict:
        """Character Identity → CharacterAppraisal（确定性处境解读）。无 identity 时返回中性。"""
        if self.identity is None:
            return {"appraisal": {}, "motives": {}, "fit": 0.0, "reasons": []}
        ctx = ctx or {}
        from furina.persona.character_identity import appraise
        recent = list(ctx.get("recent_events", [])) or list(getattr(state, "_last_recent_events", []))
        rel = _rel(state)
        ap = appraise(self.identity, user_present=bool(getattr(state, "user_present", True)),
                      user_working=bool(getattr(state, "user_working", False)),
                      recent_events=recent, user_idle=float(getattr(state, "user_idle_seconds", 0)),
                      relationship_factors=rel, emotion_label=getattr(state.emotion, "label", "calm"))
        fit, reasons = _identity_activity_fit(self.identity, ap, activity)
        return {"appraisal": ap.as_dict(), "motives": ap.influence(), "fit": fit, "reasons": reasons}

    # -------------------------------------------------- 反馈（§13-14：拒绝/回应必须真改变未来行为）
    def on_user_response(self, responded: bool, was_interactive: bool) -> None:
        """用户回应/拒绝 → 更新接纳度与关系统计（真实状态变化，不只是 prompt）。"""
        if responded:
            self._interaction_tolerance = min(100.0, self._interaction_tolerance + 4)
        else:
            self._interaction_tolerance = max(10.0, self._interaction_tolerance - 6)

    def reject(self) -> None:
        """用户明确拒绝 → 之后一段时间收敛主动行为。"""
        self._interaction_tolerance = max(10.0, self._interaction_tolerance - 10)

    def mark_done(self, activity: str, now: float) -> None:
        self._last_done[activity] = now
        self._activity_history.append(activity)
        self._activity_history = self._activity_history[-8:]
        self._category_history.append(CATEGORY.get(activity, SELF))
        self._category_history = self._category_history[-8:]

    def mark_speech(self, now: float) -> None:
        self._last_speech = now

    # -------------------------------------------------- 打分
    def _score(self, state, emotion, activity, rel, ctx, now) -> tuple[float, List[str], float, float, List[str]]:
        n = _needs(state); e = emotion.behavior_tendency()
        cat = CATEGORY.get(activity, SELF)
        base = 0.1

        def _t(*terms):
            return _clamp(sum(terms))

        # 各活动基线分数（0..1）
        if activity == "play":
            base = _t(n["playfulness"]/100*0.4, n["boredom"]/100*0.4, e["play_bias"]/100*0.2)
        elif activity == "explore":
            base = _t(n["curiosity"]/100*0.5, n["boredom"]/100*0.3, e["explore_bias"]/100*0.2)
        elif activity == "read":
            base = _t(n["curiosity"]/100*0.4, n["boredom"]/100*0.3, (100-n["energy"])/100*0.1)
        elif activity == "drink":
            base = _t(n["hunger"]/100*0.6)
        elif activity == "eat":
            base = _t(n["hunger"]/100*0.8)
        elif activity == "rest":
            base = _t(n["fatigue"]/100*0.5, n["sleepiness"]/100*0.3, e["rest_bias"]/100*0.2)
        elif activity == "sleep":
            base = _t(n["sleepiness"]/100*0.6, n["fatigue"]/100*0.3, _late(state)*0.3)
        elif activity == "tidy":
            base = _t(n["boredom"]/100*0.3)
        elif activity == "stretch":
            base = _t(n["fatigue"]/100*0.4, n["boredom"]/100*0.2)
        elif activity == "wander":
            base = _t(n["boredom"]/100*0.4, e["explore_bias"]/100*0.2)
        elif activity == "daydream":
            base = _t(n["boredom"]/100*0.2, (100-n["energy"])/100*0.2)
        elif activity == "observe_user":
            base = _t(n["social_need"]/100*0.25, (0.35 if state.user_working else 0.1))
        elif activity == "observe_work":
            base = _t(0.45 if state.user_working else 0.08)
        elif activity == "watch_user":
            base = _t(0.15 + n["social_need"]/100*0.1)
        elif activity == "look_around":
            base = _t(n["curiosity"]/100*0.25 + 0.1)
        elif activity == "approach_user":
            base = _t(n["social_need"]/100*0.5, e["approach_bias"]/100*0.25, e["talk_bias"]/100*0.15)
        elif activity == "talk":
            base = _t(n["social_need"]/100*0.45, e["talk_bias"]/100*0.3, ctx.get("talk_boost", 0.0))
        elif activity == "invite_user":
            base = _t(n["social_need"]/100*0.45, e["talk_bias"]/100*0.2, ctx.get("talk_boost", 0.0))
        elif activity == "greet":
            base = _t(ctx.get("greet_boost", 0.0), n["social_need"]/100*0.2)
        elif activity == "comfort":
            base = _t(n["social_need"]/100*0.2, (0.3 if state.emotion.sadness > 40 else 0.0))
        elif activity == "offer_help":
            base = _t(0.45 if state.user_working else 0.05, rel["trust"] * 0.2)
        elif activity == "assist_user":
            base = _t(0.4 if state.user_working else 0.05)
        elif activity == "idle":
            base = _clamp(0.08 + n["boredom"]/100*0.01)   # 低基线，绝不默认
        else:
            base = _clamp(0.1)

        # 主导需求唤起（§：让最迫切的需求**独占**驱动行为，而非被其它需求分走）。
        # 只有"满足该主导需求"的活动才被抬升；其它活动被相对压低 —— 避免多个需求同时饱和时互相挤兑。
        # **生理优先（§四）**：生存需求(疲劳/饿/困)高时，它们压倒动机型需求成为主导。
        surv = _survival_pressure(n)
        if surv > 0.4:
            # 生存危机时：选出最迫切的生存需求作为主导
            dn = "fatigue" if n["fatigue"] >= n["hunger"] and n["fatigue"] >= n["sleepiness"] \
                else ("hunger" if n["hunger"] >= n["sleepiness"] else "sleepiness")
            if _NEED_OF.get(activity) == dn:
                base = base * (1.0 + surv * 0.9)   # 生存需求显著抬升其活动
            else:
                base *= 0.7   # 非生存需求在危机时被大幅压低
        else:
            dn = _dominant_need(n)
            if _NEED_OF.get(activity) == dn:
                base = base * (1.0 + _dominant_urgency(n) * _CATEGORY_AFFINITY.get(cat, 0.0) * 1.8)
            else:
                base = base * 0.85   # 非主导需求的活动被适当压低
        # 人格（§2）—— 生理需求优先（§四）：生存越急，人格越退让。
        # 分量角色：
        #   - 乘法 pw：人格偏好放大"需求已有"的活动
        #   - 加法 additive：人格偏好**抬升**即使需求中等/未起的活动（Preference，非 Need Pressure）
        # 这样 Social 在 social_need 中等时也能让 talk/approach 竞争,而不是只能放大低分。
        pw = self.personality.as_weight(activity)
        survival = _survival_pressure(n)
        pw = 1.0 + (pw - 1.0) * (1.0 - survival)   # survival=0→全人格；survival=1→人格中性化
        base *= pw
        # 加法偏好项：人格"喜欢做这个"的固定抬升（越契合越高），**但生理危机时为 0**
        # 这是 Personality ≠ Need 的关键：让"人格偏好的活动"能在需求中等时也竞争，而非只放大需求已有的高分。
        if cat != "NEED" and survival < 0.7:
            fit = self.personality._personality_fit(activity)
            if fit > 0:
                base = base + fit * 0.30 * (1.0 - survival)
        # Relationship 加权（§5 按维度语义，非统一乘数）：
        #   familiarity↑ → 靠近成本降；comfort↑ → 陪伴/说话更自然；
        #   social_confidence↑ → 主动社交更大胆；annoyance↑ → 主动/打扰降；
        #   trust↑ → 更深/帮忙↑。每个维度作用不同行为。
        if activity in ("approach_user", "invite_user"):
            # 熟悉 + 自在 → 靠近/邀请更自然；烦 → 收敛
            base *= _clamp(0.35 + rel["familiarity"] * 0.5 + rel["comfort"] * 0.4
                           + rel["social_confidence"] * 0.35 - rel["annoyance"] * 0.55)
        elif activity in ("talk", "comment", "greet", "seek_attention", "ask_user"):
            # 自在 + 自信 → 更敢开口；烦/不信任 → 收敛
            base *= _clamp(0.30 + rel["comfort"] * 0.45 + rel["social_confidence"] * 0.5
                           - rel["annoyance"] * 0.5 - (1.0 - rel["trust"]) * 0.15)
        elif activity in ("offer_help", "assist_user"):
            # 信任 → 帮忙更自然
            base *= _clamp(0.30 + rel["trust"] * 0.55 + rel["respect"] * 0.3)
        elif activity == "comfort":
            base *= _clamp(0.30 + rel["comfort"] * 0.45 + rel["attachment"] * 0.3
                           + rel["trust"] * 0.2 - rel["annoyance"] * 0.3)
        elif activity in ("observe_user", "watch_user"):
            # 熟悉高→更愿陪；烦→少盯
            base *= _clamp(0.35 + rel["familiarity"] * 0.35 - rel["annoyance"] * 0.45)
        # 互动接纳度（§13）：tolerance 低 → 抑制 SOCIAL/ASSISTANCE 主动行为（保持）
        if cat in (SOCIAL, ASSISTANCE):
            tol = _clamp((rel.get("interaction_tolerance", 0.5) - 0.4) / 0.4 + 0.6)
            base *= tol
        # B4（评审基线 0402e7f）：**production anti-collapse = OFF**。
        # 类别重复惩罚 / 活动重复惩罚 / 观察占比守卫等纯多样性机制已**整体移除**
        # （"刚做过所以必须换一个"不是因果；真实人可连续读书）。
        # 最近行为仅保留**有现实语义**的因果信号：needs outcome（吃后 hunger 降）、
        # 用户拒绝（§13 tolerance）、活动 cooldown、world 可行性、关系后果。
        # 30s/90s recency 乘子也已删除 —— 它既非因果，又会混用假时钟/真时钟导致
        # 环境相关的不确定行为（Windows 全新启动机上 repeated-read 被误压成 explore）。

        why = _why_for(activity, state, emotion, rel, ctx)
        fit = self.personality.fit_for(activity)   # 人格契合度 0..1（Debug 用 §六）
        # ---- World 影响（Phase 06）：只改变候选环境，不直接指定 Activity；不制造 observe fallback。
        # 用户深度工作 → 主动社交/打扰降；用户离开 → SELF 升；用户刚回来 → 社交/反应升。
        wf = _world_factors(state, ctx)
        if wf is not None:
            base, wtags = _apply_world(base, activity, wf)
            why = why + wtags
        # ---- Memory 影响（Phase 07 §17）：解释 → memory_fit → 候选。绝不做第二套 Relationship。
        mem = self._memory_interpret(state, ctx)
        if mem["salience"] > 0 and not ctx.get("memory_off"):
            mfit = 0.0
            mreasons = list(mem["reasons"])
            if activity in ("talk", "approach_user", "invite_user", "greet", "seek_attention"):
                # 历史被拒 → 风险高 → 压；历史积极 → 抬
                if mem["risk"] > 0.35:
                    mfit -= mem["risk"] * 0.30
                    if not mreasons:
                        mreasons.append("similar_context_previous_rejection")
                if mem["pos"] > 0.35:
                    mfit += mem["pos"] * 0.30
            elif activity in ("offer_help", "assist_user"):
                if mem["help"] > 0.35:
                    mfit += mem["help"] * 0.25
                    mreasons.append("previous_help_was_welcomed")
            if mfit != 0.0:
                base += mfit
                why = why + mreasons
        # ---- Character Identity 影响（Phase 05）：appraisal → identity_fit → 加法偏好。
        # 生理优先：survival 高时 identity 让位（§10）。不直接指定 Activity，只改变意义/倾向。
        survival = _survival_pressure(n)
        if self.identity is not None and survival < 0.7:
            try:
                ares = self._appraise(state, activity, ctx)
                ifit, ireasons = ares["fit"], ares["reasons"]
                if ifit > 0:
                    base = base + ifit * 0.32 * (1.0 - survival)
                fit_personality = fit
                return _clamp(base), why, fit_personality, ifit, ireasons
            except Exception:
                pass
        return _clamp(base), why, fit, 0.0, []

    def candidates(self, state: CharacterState, emotion: EmotionEngine,
                   now: Optional[float] = None, ctx: Optional[dict] = None) -> List["Candidate"]:
        import time as _t
        now = _t.monotonic() if now is None else now
        ctx = ctx or {}
        rel = _rel(state)
        pool = ["read", "drink", "eat", "play", "explore", "stretch", "rest", "think", "tidy",
                "daydream", "wander", "look_around", "observe_user", "observe_work", "watch_user",
                "approach_user", "talk", "invite_user", "greet", "comfort", "offer_help",
                "assist_user", "sleep", "idle"]
        out = []
        for act in pool:
            score, why, fit, ifit, ireas = self._score(state, emotion, act, rel, ctx, now)
            feasible, feas_why = _feasible(act, state, ctx)
            out.append(Candidate(act, round(score, 3), why, CATEGORY.get(act, SELF),
                                 personality_fit=round(fit, 2),
                                 identity_fit=round(ifit, 2),
                                 identity_reasons=list(ireas),
                                 feasible=feasible,
                                 feasibility_reasons=list(feas_why)))
        out.sort(key=lambda c: (c.feasible, c.score), reverse=True)   # 可行优先,再按动机
        return out

    @staticmethod
    def as_debug(cands: List["Candidate"]) -> List[dict]:
        return [c.as_dict() for c in cands]

    # -------------------------------------------------- Speech Opportunity（§6）
    def talk_opportunity(self, state, emotion, ctx=None, now=None) -> tuple[float, str]:
        """0..1：现在是不是该开口说话的机会？带原因（§6-8）。"""
        import time as _t
        now = _t.monotonic() if now is None else now
        ctx = ctx or {}
        n = _needs(state); rel = _rel(state)
        soc = n["social_need"] / 100.0
        avail = 0.3 if not state.user_working else 0.0
        event = 0.35 if ctx.get("interesting_event") else 0.0
        silent = 0.3 if ctx.get("long_silence") else 0.0
        emo = emotion.behavior_tendency()["talk_bias"] / 100.0 * 0.3
        since_speech = (now - self._last_speech) if self._last_speech else 999
        recency = _clamp(since_speech / 60.0)   # 刚说过 → 压低
        cost = (100 - self._interaction_tolerance) / 100.0 * 0.3   # 接纳度低 → 打扰成本高
        score = _clamp(soc * 0.35 + avail + event + silent + emo + recency * 0.3 - cost)
        reason = ""
        if ctx.get("interesting_event"):
            reason = ctx.get("interesting_event")
        elif ctx.get("long_silence"):
            reason = "long_silence"
        elif state.user_working:
            reason = ""
        elif rel["confidence"] < 0.4:
            reason = "low_confidence"
        return score, reason


@dataclass
class Candidate:
    activity: str
    score: float = 0.0
    why: List[str] = field(default_factory=list)
    category: str = ""
    personality_fit: float = 0.0   # 人格契合度 0..1（Debug §六）
    identity_fit: float = 0.0      # 角色身份契合度 0..1（Phase 05 §26）
    identity_reasons: List[str] = field(default_factory=list)
    feasible: bool = True          # Affordance（Phase 06B：能不能做）
    feasibility_reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"activity": self.activity, "motivation": round(self.score, 2),
                "why": list(self.why), "category": self.category,
                "personality_fit": round(self.personality_fit, 2),
                "identity_fit": round(self.identity_fit, 2),
                "identity_reasons": list(self.identity_reasons),
                "feasible": self.feasible,
                "feasibility_reasons": list(self.feasibility_reasons)}


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _late(s: CharacterState) -> float:
    return 0.5 if (s.clock_hour >= 23 or s.clock_hour < 6) else 0.0
