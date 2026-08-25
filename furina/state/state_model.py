"""五维状态模型（plan/1 §13）。

关键点：
- **宏观状态(MacroState)** 是“她在做什么”，**不是情绪**（情绪不能进状态树）。
- 情绪是连续变量，表现才是离散状态（plan/1 §9）。
- Needs 是“推动它产生行为的内部动力”，不是状态本身（plan/1 §10）。
- Attention 是“她现在注意谁”，是认知状态而非动画属性（plan/1 §11）。
- Intent 是“她想做什么”（plan/1 §12）。
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------- 宏观状态
class MacroState(str, enum.Enum):
    IDLE = "idle"            # 待机 / 自在生活
    ENGAGED = "engaged"      # 正在与用户互动
    LIVING = "living"        # 自主生活
    WORKING = "working"      # 参与工作 / Agent 任务
    RESTING = "resting"      # 休息 / 放松
    SLEEPING = "sleeping"    # 睡眠
    SPECIAL = "special"      # 特殊事件


# ---------------------------------------------------------------- Life
@dataclass
class LifeState:
    """宏观生命状态（plan/1 §7）。"""

    macro: MacroState = MacroState.IDLE
    # 细分活动，例如 observing_user_work / eating / reading ...
    activity: str = "idle"
    # 用于 DEBUG / 决策轨迹
    reason: str = ""


# ---------------------------------------------------------------- Emotion
@dataclass
class EmotionState:
    """连续情绪变量（plan/1 §9）。

    情绪本身是连续变量，表现才离散。用高频二维（valence/arousal）+ 命名标签。
    升级（Life Simulation P2）：扩展为**多维情绪模型**（确定性，不用 LLM），
    每维度 0..100；保留 valence/arousal/mood/label 以兼容现有接口。
    """

    valence: float = 0.5          # 0..1 负..正
    arousal: float = 0.3          # 0..1 平静..激动
    mood: float = 60.0            # 0..100 总心情
    label: str = "calm"           # 离散化标签：happy/excited/proud/...
    confidence: float = 0.5

    # 多维情绪（Life Simulation P2）：每个维度 0..100
    happiness: float = 60.0
    sadness: float = 5.0
    anger: float = 5.0
    pride: float = 40.0
    curiosity: float = 50.0
    embarrassment: float = 8.0
    loneliness: float = 15.0
    excitement: float = 30.0
    calm: float = 70.0

    def clamp(self) -> None:
        """把所有情绪维度夹到 0..100，并同步 mood/valence/arousal。"""
        for f in self.__dataclass_fields__:
            if f in ("valence", "arousal") or f == "label" or f == "confidence":
                continue
            v = getattr(self, f)
            if isinstance(v, (int, float)):
                setattr(self, f, max(0.0, min(100.0, float(v))))
        # 同步派生量：mood 取多维的综合；valence/arousal 由主导情绪近似
        self.mood = max(0.0, min(100.0, self.mood))
        # label 已由 EmotionEngine 根据主导维度派生（此处不自动改 label，保留显式性）


# ---------------------------------------------------------------- Needs
@dataclass
class NeedsState:
    """内部动力（plan/1 §10）。"""

    energy: float = 80.0          # 精力
    hunger: float = 20.0          # 饥饿
    fatigue: float = 20.0         # 疲劳
    sleepiness: float = 10.0      # 困倦
    boredom: float = 30.0         # 无聊
    social_need: float = 40.0     # 社交需求
    curiosity: float = 50.0       # 好奇
    playfulness: float = 30.0     # 玩耍欲
    work_interest: float = 50.0   # 对工作的兴趣
    satisfaction: float = 60.0    # 满足感

    def clamp(self) -> None:
        for f in self.__dataclass_fields__:  # type: ignore[attr-defined]
            setattr(self, f, max(0.0, min(100.0, getattr(self, f))))


# ---------------------------------------------------------------- Attention
class AttentionTarget(str, enum.Enum):
    USER = "user"
    ACTIVE_WINDOW = "active_window"
    SPECIFIC_WINDOW = "specific_window"
    OBJECT = "object"
    SELF = "self"
    NONE = "none"


@dataclass
class AttentionState:
    target: AttentionTarget = AttentionTarget.NONE
    subject: str = ""            # 如窗口标题 / 物体名
    gaze: str = "front"          # front/left/right/up/down/user
    inertia: float = 0.0         # 视线惯性（plan/4 §18）
    delay: float = 0.0


# ---------------------------------------------------------------- Intent
class IntentCategory(str, enum.Enum):
    SURVIVE = "survive"     # eat/drink/sleep
    INTERACT = "interact"   # greet/talk/play/seek_attention
    SELF = "self"           # explore/read/relax/wander
    USER = "user"           # observe/help/remind/accompany
    AGENT = "agent"         # understand/plan/execute/report


@dataclass
class Intent:
    category: IntentCategory = IntentCategory.SELF
    action: str = "wander"          # 受限枚举（plan/8 §9）
    priority: float = 0.0           # 0..1
    reason: str = ""
    # 结构化输出字段（plan/8 §8）
    emotion: str = ""
    speech: str = ""
    allowed: bool = True


# ---------------------------------------------------------------- Aggregate
@dataclass
class CharacterState:
    """聚合状态：一帧内所有认知层快照。"""

    life: LifeState = field(default_factory=LifeState)
    emotion: EmotionState = field(default_factory=EmotionState)
    needs: NeedsState = field(default_factory=NeedsState)
    attention: AttentionState = field(default_factory=AttentionState)
    intent: Intent = field(default_factory=Intent)
    relationship: "object | None" = None   # Life Simulation P2：由调度器注入 memory.relationship（供 Motivation 读）
    world: "object | None" = None          # Phase 06：结构化世界感知（WorldPerception，供 Motivation/Brain 读）

    # ---- 环境 / 世界 ----
    active_window_title: str = ""
    active_window_app: str = ""
    user_idle_seconds: float = 0.0
    user_working: bool = False
    # H1-FINAL §7：空闲真相可用性 —— False 且从未有有效样本时，user_idle_seconds 默认 0 不得当作"用户刚互动"
    idle_available: bool = True

    # ---- 时间 ----
    clock_hour: int = 0
    clock_minute: int = 0

    # ---- 关系（plan/6 §18） ----
    familiarity: float = 0.0
    trust: float = 0.0
    comfort: float = 0.0
    attachment: float = 0.0
    respect: float = 0.0
    dependency: float = 0.0
    annoyance: float = 0.0

    # ---- 聚合快照辅助 ----
    def snapshot(self, reason: str = "") -> dict:
        return {
            "macro": self.life.macro.value,
            "activity": self.life.activity,
            "emotion": self.emotion.label,
            "mood": round(self.emotion.mood, 1),
            "needs": {
                k: round(getattr(self.needs, k), 1)
                for k in self.needs.__dataclass_fields__  # type: ignore[attr-defined]
            },
            "attention": self.attention.target.value,
            "intent": {"category": self.intent.category.value, "action": self.intent.action,
                       "priority": round(self.intent.priority, 2), "reason": self.intent.reason},
            "active_window": {"app": self.active_window_app, "title": self.active_window_title},
            "user_idle": round(self.user_idle_seconds, 1),
            "user_working": self.user_working,
            "clock_hour": self.clock_hour,
            "reason": reason,
        }
