"""Furina Character Identity（Phase 05）。

Character Identity 与 Behavioral Personality、Emotion、Relationship 严格分离：
  - Personality 回答"她偏好什么活动"
  - Emotion 回答"她此刻感受"
  - Relationship 回答"她和用户的关系"
  - **Character Identity 回答"她如何理解自己、什么对她重要、同一事件对她意味着什么"**

它通过结构化确定性状态 (self concept / core values / contradictions / sensitivities / motives)
+ CharacterAppraisal（处境解读）进入 Motivation，**不是 Prompt roleplay**，也不直接指定行为。

关键：
  - Identity 只改变"某个当前事件对她的重要性"（Situation Appraisal + Candidate Interpretation）。
  - Identity 不能覆盖生理系统（fatigue=100 → rest 仍优先）。
  - 提供 NEUTRAL_CHARACTER_IDENTITY 用于严格反事实（设成与 Furina 相同 Behavioral Personality）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CharacterIdentity:
    """结构化角色身份（确定性，不用 LLM）。"""
    name: str = "neutral"
    # ---- Self Concept（她如何理解自己）----
    need_to_maintain_dignity: float = 0.5        # 看重尊严/面子
    desire_to_be_recognized: float = 0.5         # 渴望被认可
    dramatic_self_presentation: float = 0.5       # 戏剧化自我呈现
    sensitivity_to_appearing_incompetent: float = 0.5  # 害怕显得无能
    desire_to_be_seen_as_capable: float = 0.5    # 想显得能干
    independent_self_image: float = 0.5          # 独立自主的自我形象
    # Phase 07 修正：历史创伤/成长 traits（08A 校准 —— 有"时期"与"激活条件"，非 always-on）
    craves_genuine_connection: float = 0.5       # 渴望真实、不表演的连接
    fear_of_being_exposed: float = 0.5           # 怕被看穿"我其实不是神"
    loneliness_sensitivity: float = 0.5          # 对孤独/被冷落的敏感
    # ---- Trait Era 元数据（08A §3-4：stable/historical/latent/contextual/post_story_growth）----
    trait_eras: Dict[str, str] = field(default_factory=dict)
    # ---- Trait Activation（08A §9：历史创伤只在相似情境激活；普通情境低）----
    trait_activation: Dict[str, float] = field(default_factory=lambda: {
        "fear_of_being_exposed": 0.3,
        "loneliness_sensitivity": 0.3,
    })   # 0..1 默认激活强度（默认"背景级"，不会 always-on 悲剧化）
    # ---- Core Values（稳定的价值维度）----
    values: Dict[str, float] = field(default_factory=lambda: {
        "dignity": 0.5, "recognition": 0.5, "freedom": 0.5, "companionship": 0.5,
        "responsibility": 0.5, "competence": 0.5, "enjoyment": 0.5, "care_for_others": 0.5,
        "authenticity": 0.5,
    })
    # ---- Emotional Sensitivities（哪些事件对她更敏感）----
    sensitivities: Dict[str, float] = field(default_factory=lambda: {
        "praise": 0.5, "being_ignored": 0.5, "public_failure": 0.5, "successful_performance": 0.5,
        "user_return": 0.5, "rejection": 0.5, "being_needed": 0.5, "successful_help": 0.5,
        "unexpected_attention": 0.5, "loss_of_control": 0.5,
    })


# -----------------------------------------------------------------------------
# 芙宁娜身份（08A 校准，依据 docs/FURINA_CHARACTER_EVIDENCE.md，默认 POST_ARCHON_QUEST 时期）
#
# 分层（不能扁平成一个数）：
#   Stable Core          —— 跨剧情较稳定：戏剧性/表现力/自尊/好奇/爱表演
#   Former Mask          —— 历史面具：神性威严/夸大的确信/永不破功（历史，非当前)
#   Historical Scars     —— latent/triggered：怕被看穿/孤独敏感/失败敏感（相似情境才激活）
#   Current Growth       —— 卸任后：自由/做自己/主动重拾表演/能真诚不表演
# 关键：fear_of_being_exposed / loneliness_sensitivity 是 **triggered**，不是 always-on。
# -----------------------------------------------------------------------------
FURINA_IDENTITY = CharacterIdentity(
    name="furina",
    # ---- Stable Core（跨阶段稳定）----
    need_to_maintain_dignity=0.9,
    desire_to_be_recognized=0.82,
    dramatic_self_presentation=0.8,
    sensitivity_to_appearing_incompetent=0.7,   # 稳定但不过度
    desire_to_be_seen_as_capable=0.78,
    independent_self_image=0.65,                 # 卸任后更需要"自己作主"
    # ---- Current Growth（08A 关键补充：之前的缺口）----
    craves_genuine_connection=0.85,              # 渴望真实、非表演的连接
    # ---- Former Mask（降到 historical/latent，不是核心强度）----
    fear_of_being_exposed=0.5,                   # 历史残留，**默认背景级**
    loneliness_sensitivity=0.5,                  # 历史残留，**默认背景级**
    values={"dignity": 0.85, "recognition": 0.8, "freedom": 0.7, "companionship": 0.85,
            "responsibility": 0.7, "competence": 0.8, "enjoyment": 0.8, "care_for_others": 0.72,
            "authenticity": 0.8},                # 渴望真实（虽爱表演）
    sensitivities={"praise": 0.9, "being_ignored": 0.8, "public_failure": 0.75, "successful_performance": 0.85,
                   "user_return": 0.8, "rejection": 0.8, "being_needed": 0.7, "successful_help": 0.7,
                   "unexpected_attention": 0.6, "loss_of_control": 0.7, "connection": 0.9},
    # trait 时期（08A §3-4）：历史创伤标成 historical/latent，非 always_active_core
    trait_eras={
        "fear_of_being_exposed": "historical_latent",
        "loneliness_sensitivity": "historical_latent",
        "dramatic_self_presentation": "stable",
        "craves_genuine_connection": "post_story_growth",
        "desire_to_be_recognized": "stable",
        "independent_self_image": "post_story_growth",
    },
    # 激活：默认背景级（普通场景不悲剧化），相似情境才显著（08A §9/§16）
    trait_activation={"fear_of_being_exposed": 0.3, "loneliness_sensitivity": 0.3},
)

# 中性身份：所有值 0.5（用于严格反事实 —— 与 Furina 使用完全相同 Behavioral Personality）
NEUTRAL_CHARACTER_IDENTITY = CharacterIdentity(name="neutral")


# ---------------------------------------------------------------- Character Appraisal
@dataclass
class CharacterAppraisal:
    """芙宁娜如何理解当前处境（确定性）：输出若干 0..1 的"处境分量"。"""
    recognition_opportunity: float = 0.0   # 得到认可的机会
    dignity_threat: float = 0.0            # 尊严受威胁
    companionship_opportunity: float = 0.0  # 陪伴机会
    responsibility_cue: float = 0.0        # 责任感被唤起
    performance_opportunity: float = 0.0   # 表演/展现自己的机会
    vulnerability_pressure: float = 0.0    # 暴露脆弱/显得无能的风险

    def as_dict(self) -> Dict[str, float]:
        return {k: round(v, 3) for k, v in self.__dict__.items()}

    def influence(self) -> Dict[str, float]:
        """核心: 各分量对"哪些活动更值得"的偏移贡献（0..1, 供 Motivation 加/乘）。"""
        return {
            "praise_receptive": min(1.0, self.performance_opportunity + self.recognition_opportunity),
            "attention_wanting": min(1.0, self.recognition_opportunity + self.companionship_opportunity),
            "dignity_guarding": min(1.0, self.dignity_threat + self.vulnerability_pressure),
            "help_motivated": min(1.0, self.responsibility_cue + self.companionship_opportunity),
        }


def activation_gain(identity: CharacterIdentity, trait: str, *,
                    boost_if: bool = False, boost: float = 0.9) -> float:
    """08A §9/§16：历史创伤 trait 的激活增益（默认背景级；相似情境才显著）。

    trait_activation[trait] 是默认激活强度（背景级，如 0.3）；
    当触发条件成立时提升到 boost（如 0.9）。这保证"普通场景不悲剧化，相关场景才浮现"。
    """
    base = identity.trait_activation.get(trait, 0.3)
    return boost if boost_if else base


def appraise(identity: CharacterIdentity, *,
             user_present: bool, user_working: bool, recent_events: List[str],
             user_idle: float, relationship_factors: Dict[str, float],
             emotion_label: str) -> CharacterAppraisal:
    """确定性处境解读：把世界 + 身份敏感度转成 appraisal 分量。

    同一事件，Furina 和 Neutral 会产生不同 appraisal（因 sensitivities/values 不同）。
    """
    rv = identity.values
    st = identity.sensitivities
    a = CharacterAppraisal()
    events = " ".join(recent_events).lower()

    # 认可机会：用户在 / 刚注意她 / 夸奖 / 被需要 → 高的 desire_to_be_recognized 更敏感
    praise = st.get("praise", 0.5) * (1.0 if "praise" in events or "夸奖" in events or "compliment" in events else 0.0)
    return_boost = st.get("user_return", 0.5) * (1.0 if ("return" in events or "回来" in events or "welcome" in events) else 0.0)
    needed = st.get("being_needed", 0.5) * (1.0 if ("need" in events or "帮忙" in events) else 0.0)
    a.recognition_opportunity = min(1.0, rv.get("recognition", 0.5) *
                                    (0.3 + praise + return_boost + needed + (0.4 if user_present and not user_working else 0.0)))

    # 表演机会：用户在场 + 有展示空间 + 戏剧化呈现倾向
    a.performance_opportunity = min(1.0, identity.dramatic_self_presentation *
                                    (0.5 if user_present else 0.1) * (0.5 + rv.get("recognition", 0.5)))

    # 陪伴机会：孤独/用户可用
    a.companionship_opportunity = min(1.0, (1.0 - relationship_factors.get("familiarity", 0)) * 0.2
                                      + relationship_factors.get("comfort", 0) * 0.4
                                      + (0.4 if user_present and not user_working else 0.0))
    a.companionship_opportunity *= (0.6 + rv.get("companionship", 0.5))

    # 责任 cue：用户需要帮忙 / 在忙
    a.responsibility_cue = min(1.0, (1.0 if "帮忙" in events or "help" in events or user_working else 0.0)
                               * rv.get("responsibility", 0.5) * (0.5 + st.get("being_needed", 0.5)))

    # 尊严威胁：被拒绝 / 被忽略 / 失败 → 高 dignity 敏感更受威胁
    # **08A 激活约束**：历史创伤（fear_of_being_exposed）只在"被质疑/被逼解释/失败被追问"等
    # 相似情境才显著激活（trait_activation 门控），普通场景不悲剧化。
    reject = st.get("rejection", 0.5) * (1.0 if ("reject" in events or "拒绝" in events) else 0.0)
    ignore = st.get("being_ignored", 0.5) * (1.0 if ("ignore" in events or "忽略" in events or user_idle > 900) else 0.0)
    a.dignity_threat = min(1.0, identity.need_to_maintain_dignity * (reject + ignore))
    # 触发上下文：需要展示脆弱 / 被质疑能力
    trigger = ("expose" in events or "质疑" in events or "解释" in events
               or "talent" in events or "置疑" in events)
    exposure_gain = activation_gain(identity, "fear_of_being_exposed", boost_if=trigger, boost=0.9)
    a.dignity_threat = min(1.0, a.dignity_threat + identity.fear_of_being_exposed * exposure_gain * 0.3)

    # 脆弱压力：失败 / 显得无能
    fail = st.get("public_failure", 0.5) * (1.0 if ("fail" in events or "失败" in events) else 0.0)
    a.vulnerability_pressure = min(1.0, identity.sensitivity_to_appearing_incompetent * fail

                                   + (0.2 if emotion_label in ("embarrassed", "sad") and fail else 0.0))
    return a


# 人格冲突（内部张力，用于 Candidate Interpretation —— 不是行为发生器）
CONTRADICTIONS = [
    # (想要, vs, 不愿显得, 作用的活动, 权重)
    ("wants_attention", "does_not_want_to_look_needy", ["talk", "approach_user", "seek_attention"], 1.0),
    ("wants_companionship", "values_independence", ["invite_user", "talk"], -0.4),  # 独立缓冲社交
    ("wants_to_appear_confident", "sensitive_to_failure", ["celebrate", "offer_help"], 0.7),
    ("likes_dramatic_expression", "can_be_genuinely_caring", ["comfort", "celebrate"], 0.6),
    ("wants_recognition", "does_not_directly_admit_need", ["perform", "show_off"], -0.5),
]
