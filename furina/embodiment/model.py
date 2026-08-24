"""具身表达语义模型（Phase 09）—— 全部为**语义级** intents，不指向任何素材/动画文件。

本层只输出"她身体此刻想表达什么"，由后续 Asset Resolver 决定具体素材。
这是确定性语义模型：不新增任何 LLM 调用，也不修改 Dialogue/Identity/等冻结模块。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------- 表情 intent（不等于 emotion label）
class ExpressionIntent(str, enum.Enum):
    NEUTRAL = "neutral"
    SOFT = "soft"                 # 放松的微微平和
    PLEASED = "pleased"           # 满意/愉悦
    PROUD = "proud"
    PLAYFUL = "playful"
    EMBARRASSED = "embarrassed"
    GUARDED = "guarded"
    ANNOYED = "annoyed"
    CONCERNED = "concerned"
    SAD = "sad"
    TIRED = "tired"
    EXCITED = "excited"
    SINCERE = "sincere"


# ---------------------------------------------------------------- Gaze intent
class GazeIntent(str, enum.Enum):
    USER = "USER"
    SCREEN = "SCREEN"
    ACTIVITY_TARGET = "ACTIVITY_TARGET"
    AWAY = "AWAY"
    SIDE = "SIDE"
    DOWN = "DOWN"
    AROUND = "AROUND"
    NONE = "NONE"


# ---------------------------------------------------------------- Posture intent（语义，不是素材）
class PostureIntent(str, enum.Enum):
    UPRIGHT = "upright"
    RELAXED = "relaxed"
    CONTAINED = "contained"       # 收着/防御性内敛
    GUARDED = "guarded"
    LEANING = "leaning"
    RESTING = "resting"
    SEATED = "seated"
    LYING = "lying"
    SLEEPING = "sleeping"
    ENGAGED = "engaged"           # 前倾投入（工作/被吸引）


# ---------------------------------------------------------------- Proximity intent（不做路径规划）
class ProximityIntent(str, enum.Enum):
    MAINTAIN = "MAINTAIN"
    APPROACH = "APPROACH"
    WITHDRAW = "WITHDRAW"
    NEAR = "NEAR"
    FAR = "FAR"


# ---------------------------------------------------------------- Movement tempo
class TempoIntent(str, enum.Enum):
    VERY_SLOW = "very_slow"
    SLOW = "slow"
    NORMAL = "normal"
    LIVELY = "lively"
    ENERGETIC = "energetic"


# ---------------------------------------------------------------- Transition style
class TransitionStyle(str, enum.Enum):
    IMMEDIATE = "IMMEDIATE"
    SMOOTH = "SMOOTH"
    HESITANT = "HESITANT"
    ENERGETIC = "ENERGETIC"
    GENTLE = "GENTLE"
    RELUCTANT = "RELUCTANT"


# ---------------------------------------------------------------- Micro motion intent（语义）
class MicroMotionIntent(str, enum.Enum):
    BLINK = "BLINK"
    BREATH = "BREATH"
    SIGH = "SIGH"
    YAWN = "YAWN"
    STRETCH = "STRETCH"
    GIGGLE = "GIGGLE"
    LOOK_SHIFT = "LOOK_SHIFT"
    FIDGET = "FIDGET"           # 小动作（手指/轻微晃动）
    NONE = "NONE"


# ---------------------------------------------------------------- Speech sync（口气-身体协调）
class SpeechSync(str, enum.Enum):
    NONE = "NONE"                # 沉默
    NEUTRAL = "NEUTRAL"
    ALIGNED = "ALIGNED"          # 与话语节奏一致
    ANIMATED = "ANIMATED"        # 话多/表演时较高协调


# ---------------------------------------------------------------- BodyExpressionState（核心输出）
@dataclass
class BodyExpressionState:
    expression: str = ExpressionIntent.NEUTRAL.value
    gaze: str = GazeIntent.NONE.value
    posture: str = PostureIntent.RELAXED.value
    body_openness: float = 0.5    # 0..1 开放/接纳程度
    proximity: str = ProximityIntent.MAINTAIN.value
    movement_tempo: str = TempoIntent.NORMAL.value
    movement_amplitude: float = 0.5   # 0..1 动作幅度（与 tempo 独立）
    hesitation: float = 0.4           # 0..1 行动犹豫
    composure: float = 0.7            # 0..1 表层控制/体面
    micro_motion: List[str] = field(default_factory=list)   # 本帧优先 micro（语义）
    transition_style: str = TransitionStyle.SMOOTH.value
    speech_sync: str = SpeechSync.NEUTRAL.value
    reasons: List[str] = field(default_factory=list)
    # 兼容字段（供既有 pose_emotion_gaze 消费方使用，避免重构 renderer）
    pose: str = "standing"            # standing / sitting / lying / sleeping ...
    emotion_label: str = "neutral"    # 素材情绪标签（中性兜底）
    gaze_label: str = "front"         # 素材朝向标签

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("pose", "emotion_label", "gaze_label")}
        if isinstance(self.micro_motion, list):
            d["micro_motion"] = list(self.micro_motion)
        return d


# ---------------------------------------------------------------- EmbodimentPersona（身份层，独立于 Dialogue）
@dataclass(frozen=True)
class EmbodimentPersona:
    """该角色作为"身体"的稳定偏好（identity 驱动，与 Dialogue Contract 的 mode 分离）。

    只描述"她身体大概率怎么表达"，不写死任何具体素材；数值 0..1。
    """
    key: str
    theatrical_modulation: float = 0.5      # 表演性动作放大系数
    posture_pride: float = 0.5              # 骄傲时挺直/占位
    openness_baseline: float = 0.5          # 常态身体开放度
    gaze_naturalness: float = 0.5           # 自然视线切换（vs 固定盯）
    recognition_hesitation: float = 0.5     # 被关注时的迟疑（防"永远直视"）
    performance_amplitude: float = 0.5      # 表演时动作幅度
    guarded_to_sincere: float = 0.5         # 能从不设防到真诚的过渡意愿
    vulnerability_visibility: float = 0.5   # 脆弱可见程度
    always_presents: bool = False           # 是否习惯性"端着"（Former Mask = True）


# 三套身体人格（公平对照；不含 Dialogue Persona 文本，纯身体偏好参数）
FURINA_EMBODIMENT = EmbodimentPersona(
    key="furina",
    theatrical_modulation=0.65,
    posture_pride=0.6,
    openness_baseline=0.6,
    gaze_naturalness=0.65,
    recognition_hesitation=0.6,        # 被夸奖/被关注会先迟疑（防永远直视）
    performance_amplitude=0.7,
    guarded_to_sincere=0.75,           # 能放松、能真诚
    vulnerability_visibility=0.5,
    always_presents=False,             # POST_ARCHON_QUEST：不必永远端着
)

NEUTRAL_EMBODIMENT = EmbodimentPersona(
    key="neutral",
    theatrical_modulation=0.2,
    posture_pride=0.2,
    openness_baseline=0.7,             # 更随意/更开放
    gaze_naturalness=0.5,
    recognition_hesitation=0.25,       # 被夸没那么多曲折，自然接受
    performance_amplitude=0.25,
    guarded_to_sincere=0.5,
    vulnerability_visibility=0.5,
    always_presents=False,
)

FORMER_MASK_EMBODIMENT = EmbodimentPersona(
    key="mask",
    theatrical_modulation=0.8,
    posture_pride=0.95,
    openness_baseline=0.35,            # 收着、端着
    gaze_naturalness=0.2,              # 少自然切换（更"被凝视"）
    recognition_hesitation=0.2,        # 被夸也不迟疑（习惯被注视）
    performance_amplitude=0.8,
    guarded_to_sincere=0.15,           # 很少转向真诚/示弱
    vulnerability_visibility=0.15,     # 脆弱几乎不可见
    always_presents=True,              # 习惯性维持公开姿态
)

EMBODIMENT_PERSONAS = {
    FURINA_EMBODIMENT.key: FURINA_EMBODIMENT,
    NEUTRAL_EMBODIMENT.key: NEUTRAL_EMBODIMENT,
    FORMER_MASK_EMBODIMENT.key: FORMER_MASK_EMBODIMENT,
}
