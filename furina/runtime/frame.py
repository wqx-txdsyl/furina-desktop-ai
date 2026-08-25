"""CharacterRuntimeFrame —— Phase 10 唯一前端契约（immutable snapshot，版本化）。

原则（§2-§19）：
  - 前端原则上只消费这一份结构，不直接读 CharacterState / Engine。
  - Frame 是只读快照（frozen dataclass），不是可变对象；用户交互回程通过 EventBus。
  - 只含**语义 intent**，不含素材文件名 / 帧索引 / 坐标。
  - debug 可选，可完全关闭；普通前端不得依赖 debug 字段；不读内部 Needs。
  - schema_version 固定，作为稳定 API。

分节：meta / activity / speech / body / motion / interaction / world_hint / debug。
"""
from __future__ import annotations

import enum, time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.0"
CHARACTER_ID = "furina"


# ---------------------------------------------------------------- Activity phase（§5）
class ActivityPhase(str, enum.Enum):
    PREPARE = "PREPARE"
    ENTER = "ENTER"
    LOOP = "LOOP"
    REACT = "REACT"
    EXIT = "EXIT"
    TRANSITION = "TRANSITION"


# ---------------------------------------------------------------- Activity category（§4）
class ActivityCategory(str, enum.Enum):
    SELF = "SELF"
    SOCIAL = "SOCIAL"
    OBSERVATION = "OBSERVATION"
    ASSISTANCE = "ASSISTANCE"
    NEED = "NEED"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------- Motion intent（§8）
class MotionIntent(str, enum.Enum):
    NONE = "NONE"
    MAINTAIN = "MAINTAIN"
    APPROACH = "APPROACH"
    WITHDRAW = "WITHDRAW"
    REPOSITION = "REPOSITION"


class SpeedSemantic(str, enum.Enum):
    NONE = "NONE"
    SLOW = "slow"
    NORMAL = "normal"
    FAST = "fast"


# ---------------------------------------------------------------- Speech validation（§6）
class SpeechValidation(str, enum.Enum):
    VALID = "valid"
    SILENT = "silent"
    INVALID = "invalid"


# ---------------------------------------------------------------- Interaction（§9）
class ResponseMode(str, enum.Enum):
    AVAILABLE = "available"      # 可互动
    BUSY = "busy"                # 忙，不打断
    SLEEPING = "sleeping"
    AWAY = "away"


# ---------------------------------------------------------------- Frame 分节 dataclasses
@dataclass(frozen=True)
class FrameMeta:
    frame_id: int = 0
    timestamp: float = 0.0
    schema_version: str = SCHEMA_VERSION
    character_id: str = CHARACTER_ID


@dataclass(frozen=True)
class FrameActivity:
    name: str = "idle"
    category: str = ActivityCategory.SELF.value
    phase: str = ActivityPhase.LOOP.value
    target: str = ""
    started_at: float = 0.0
    progress: float = 0.0          # 0..1（可选，当前无真实进度则 0）
    interruptible: bool = True


@dataclass(frozen=True)
class FrameSpeech:
    should_speak: bool = False
    text: str = ""
    dialogue_act: str = ""
    length: str = ""
    initiative: float = 0.0
    mode: str = ""
    validation_status: str = SpeechValidation.SILENT.value
    priority: int = 0
    can_interrupt_animation: bool = False
    # R2.1 P0-1：speech event identity（单调递增）—— 不同 utterance 即使文本相同也是
    # 不同事件；同一 utterance 的重复 tick 才允许去重（不能按 text equality 去重）。
    speech_id: int = 0


@dataclass(frozen=True)
class FrameBody:
    expression: str = "neutral"
    gaze: str = "NONE"
    posture: str = "relaxed"
    body_openness: float = 0.5
    proximity: str = "MAINTAIN"
    movement_tempo: str = "normal"
    movement_amplitude: float = 0.5
    hesitation: float = 0.4
    composure: float = 0.7
    # 深不可变：内部用 tuple（前端不可 append），to_dict 输出 list（保持 v1 JSON contract）
    micro_preferences: tuple = ()   # tuple[str, ...]
    transition_style: str = "SMOOTH"
    # 兼容旧 Renderer 素材路径（由 Visual Adapter 从语义派生，非直接 asset）
    pose: str = "standing"
    emotion_label: str = "neutral"
    gaze_label: str = "front"

    def __post_init__(self) -> None:
        object.__setattr__(self, "micro_preferences",
                           tuple(getattr(self, "micro_preferences", ()) or ()))


@dataclass(frozen=True)
class FrameMotion:
    intent: str = MotionIntent.NONE.value
    target: str = ""                # 语义目标，非坐标
    direction: str = ""
    speed_semantic: str = SpeedSemantic.NONE.value
    allow_reposition: bool = False


@dataclass(frozen=True)
class FrameInteraction:
    available: bool = True
    focus_target: str = "whole"
    accept_touch: bool = True
    accept_drag: bool = True
    busy: bool = False
    response_mode: str = ResponseMode.AVAILABLE.value


@dataclass(frozen=True)
class FrameWorldHint:
    user_present: bool = True
    user_working: bool = False
    user_activity: str = ""
    day_period: str = ""
    interaction_availability: float = 1.0
    interruption_cost: float = 0.0
    interesting_context: bool = False


@dataclass(frozen=True)
class FrameDebug:
    enabled: bool = False
    activity_reason: str = ""
    motivation_top: str = ""
    persona_mode: str = ""
    body_reasons: tuple = ()       # tuple[str, ...]（深不可变）
    speech_reasons: tuple = ()     # tuple[str, ...]
    world_summary: str = ""
    needs: dict = field(default_factory=dict)   # 深冻结为 MappingProxyType（只读映射）

    def __post_init__(self) -> None:
        # 把 `needs` 深冻结为只读映射，且 body_reasons/speech_reasons 强制 tuple。
        object.__setattr__(self, "needs", MappingProxyType(dict(getattr(self, "needs", {}) or {})))
        object.__setattr__(self, "body_reasons", tuple(getattr(self, "body_reasons", ()) or ()))
        object.__setattr__(self, "speech_reasons", tuple(getattr(self, "speech_reasons", ()) or ()))


# ---------------------------------------------------------------- 根 Frame（immutable）
@dataclass(frozen=True)
class CharacterRuntimeFrame:
    meta: FrameMeta = field(default_factory=FrameMeta)
    activity: FrameActivity = field(default_factory=FrameActivity)
    speech: FrameSpeech = field(default_factory=FrameSpeech)
    body: FrameBody = field(default_factory=FrameBody)
    motion: FrameMotion = field(default_factory=FrameMotion)
    interaction: FrameInteraction = field(default_factory=FrameInteraction)
    world_hint: FrameWorldHint = field(default_factory=FrameWorldHint)
    debug: FrameDebug = field(default_factory=FrameDebug)

    # ---------------- serialization（只读，JSON-safe） ----------------
    def to_dict(self, *, debug: bool = False) -> dict:
        d = {
            "meta": {
                "frame_id": self.meta.frame_id,
                "timestamp": round(self.meta.timestamp, 3),
                "schema_version": self.meta.schema_version,
                "character_id": self.meta.character_id,
            },
            "activity": {
                "name": self.activity.name,
                "category": self.activity.category,
                "phase": self.activity.phase,
                "target": self.activity.target,
                "started_at": round(self.activity.started_at, 2),
                "progress": round(self.activity.progress, 3),
                "interruptible": self.activity.interruptible,
            },
            "speech": {
                "should_speak": self.speech.should_speak,
                "text": self.speech.text,
                "dialogue_act": self.speech.dialogue_act,
                "length": self.speech.length,
                "initiative": round(self.speech.initiative, 2),
                "mode": self.speech.mode,
                "validation_status": self.speech.validation_status,
                "priority": self.speech.priority,
                "can_interrupt_animation": self.speech.can_interrupt_animation,
                "speech_id": self.speech.speech_id,   # R2.1 P0-1：speech event identity
            },
            "body": {
                "expression": self.body.expression,
                "gaze": self.body.gaze,
                "posture": self.body.posture,
                "body_openness": round(self.body.body_openness, 2),
                "proximity": self.body.proximity,
                "movement_tempo": self.body.movement_tempo,
                "movement_amplitude": round(self.body.movement_amplitude, 2),
                "hesitation": round(self.body.hesitation, 2),
                "composure": round(self.body.composure, 2),
                "micro_preferences": list(self.body.micro_preferences),
                "transition_style": self.body.transition_style,
                # 兼容旧 Renderer 素材路径
                "pose": self.body.pose,
                "emotion_label": self.body.emotion_label,
                "gaze_label": self.body.gaze_label,
            },
            "motion": {
                "intent": self.motion.intent,
                "target": self.motion.target,
                "direction": self.motion.direction,
                "speed_semantic": self.motion.speed_semantic,
                "allow_reposition": self.motion.allow_reposition,
            },
            "interaction": {
                "available": self.interaction.available,
                "focus_target": self.interaction.focus_target,
                "accept_touch": self.interaction.accept_touch,
                "accept_drag": self.interaction.accept_drag,
                "busy": self.interaction.busy,
                "response_mode": self.interaction.response_mode,
            },
            "world_hint": {
                "user_present": self.world_hint.user_present,
                "user_working": self.world_hint.user_working,
                "user_activity": self.world_hint.user_activity,
                "day_period": self.world_hint.day_period,
                "interaction_availability": round(self.world_hint.interaction_availability, 2),
                "interruption_cost": round(self.world_hint.interruption_cost, 2),
                "interesting_context": self.world_hint.interesting_context,
            },
        }
        # debug 可选、可完全关闭；普通前端不依赖
        if debug and self.debug.enabled:
            d["debug"] = {
                "activity_reason": self.debug.activity_reason,
                "motivation_top": self.debug.motivation_top,
                "persona_mode": self.debug.persona_mode,
                "body_reasons": list(self.debug.body_reasons),
                "speech_reasons": list(self.debug.speech_reasons),
                "world_summary": self.debug.world_summary,
                "needs": dict(self.debug.needs),
            }
        return d

    @classmethod
    def minimal(cls) -> "CharacterRuntimeFrame":
        """无上下文兜底（Brain 失败/启动早期），保证永远有合法 Frame。"""
        return cls(meta=FrameMeta(timestamp=time.time()))
