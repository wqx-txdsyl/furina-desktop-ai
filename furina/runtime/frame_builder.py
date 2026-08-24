"""RuntimeFrameBuilder —— 唯一 Frame 构建器（Phase 10 §12）。

输入：CharacterState / Activity / Dialogue result / BodyExpressionState / WorldState / Interaction state
输出：CharacterRuntimeFrame（immutable snapshot）。

禁止各模块自己拼 Frame；前端只消费 Frame。本模块不读 Engine 内部、不触碰 Memory DB / prompt / key。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from .frame import (
    CharacterRuntimeFrame, FrameMeta, FrameActivity, FrameSpeech, FrameBody, FrameMotion,
    FrameInteraction, FrameWorldHint, FrameDebug,
    ActivityCategory, ActivityPhase, MotionIntent, SpeedSemantic, ResponseMode, SpeechValidation,
)
from furina.behavior.motivation import CATEGORY as _ACT_CATEGORY


def _activity_category(name: str) -> str:
    return _ACT_CATEGORY.get(name or "idle", ActivityCategory.UNKNOWN.value)


class RuntimeFrameBuilder:
    """把 Runtime 状态汇成唯一 CharacterRuntimeFrame。"""

    def __init__(self, character_id: str = "furina") -> None:
        self.character_id = character_id
        self._frame_id = 0

    # -------------------------------------------------- 需要为每个 engine 提供的数据
    def build(
        self,
        *,
        frame_id: Optional[int] = None,
        state: Optional[Any] = None,             # CharacterState（含 life/emotion/needs/attention/intent）
        activity_name: str = "idle",
        activity_started_at: float = 0.0,
        activity_progress: float = 0.0,
        activity_phase: str = ActivityPhase.LOOP.value,
        activity_target: str = "",
        activity_interruptible: bool = True,
        speech: Optional[Dict] = None,           # {"should_speak","text","dialogue_act","length","initiative","mode","validation_status","priority","can_interrupt_animation"}
        body: Optional[Any] = None,              # BodyExpressionState
        world: Optional[Any] = None,             # WorldPerception（有 factors()/state）或 dict
        interaction: Optional[Dict] = None,      # 覆盖 interaction affordance
        motion_intent: str = MotionIntent.NONE.value,
        motion_target: str = "",
        motion_direction: str = "",
        motion_speed: str = SpeedSemantic.NONE.value,
        motion_reposition: bool = False,
        debug: Optional[Dict] = None,            # {"activity_reason","motivation_top","persona_mode","body_reasons","speech_reasons","world_summary","needs"}
        debug_enabled: bool = False,
        now: Optional[float] = None,
    ) -> CharacterRuntimeFrame:
        if frame_id is None:
            self._frame_id += 1
            frame_id = self._frame_id
        now = now if now is not None else time.time()

        # --- world hint ---
        world_hint = self._world_hint(world, state)
        # --- activity ---
        act = FrameActivity(
            name=activity_name or "idle",
            category=_activity_category(activity_name),
            phase=activity_phase or ActivityPhase.LOOP.value,
            target=activity_target or "",
            started_at=activity_started_at,
            progress=max(0.0, min(1.0, activity_progress or 0.0)),
            interruptible=activity_interruptible,
        )
        # --- speech ---
        sp = FrameSpeech(**(speech or {})) if speech else FrameSpeech()
        if not sp.should_speak and not sp.text:
            sp = FrameSpeech(should_speak=False, text="", validation_status=SpeechValidation.SILENT.value)
        # --- body ---
        body = self._frame_body(body)
        # --- interaction ---
        inter = self._frame_interaction(interaction, act, world_hint)
        # --- motion ---
        motion = FrameMotion(intent=motion_intent or MotionIntent.NONE.value, target=motion_target or "",
                             direction=motion_direction or "", speed_semantic=motion_speed or SpeedSemantic.NONE.value,
                             allow_reposition=motion_reposition)
        # --- debug ---
        dbg = FrameDebug(enabled=bool(debug_enabled), **(debug or {}))

        frame = CharacterRuntimeFrame(
            meta=FrameMeta(frame_id=frame_id, timestamp=now, schema_version="1.0",
                           character_id=self.character_id),
            activity=act, speech=sp, body=body, motion=motion, interaction=inter,
            world_hint=world_hint, debug=dbg,
        )
        return frame

    # -------------------------------------------------- helpers
    def _world_hint(self, world, state) -> FrameWorldHint:
        wh = FrameWorldHint()
        # 优先 WorldPerception（有 factors()）
        if world is not None:
            if hasattr(world, "factors"):
                try:
                    f = world.factors()
                    wh = FrameWorldHint(
                        user_present=bool(f.get("user_present", True)),
                        user_working=bool(f.get("user_working", False)),
                        user_activity=getattr(getattr(world, "state", None), "user_activity", ""),
                        day_period=getattr(getattr(world, "state", None), "day_period", ""),
                        interaction_availability=float(f.get("availability", 1.0)),
                        interruption_cost=float(f.get("interruption_cost", 0.0)),
                        interesting_context=bool(f.get("interesting_context", False)),
                    )
                except Exception:
                    pass
            elif isinstance(world, dict):
                wh = FrameWorldHint(
                    user_present=bool(world.get("user_present", True)),
                    user_working=bool(world.get("user_working", False)),
                    user_activity=str(world.get("user_activity", "")),
                    day_period=str(world.get("day_period", "")),
                    interaction_availability=float(world.get("availability", 1.0)),
                    interruption_cost=float(world.get("interruption_cost", 0.0)),
                    interesting_context=bool(world.get("interesting_context", False)),
                )
        # 若 state 有更细的 user_working，覆盖
        if state is not None and getattr(state, "user_working", False):
            wh = FrameWorldHint(
                user_present=wh.user_present, user_working=True, user_activity=wh.user_activity,
                day_period=wh.day_period, interaction_availability=wh.interaction_availability,
                interruption_cost=wh.interruption_cost, interesting_context=wh.interesting_context,
            )
        return wh

    def _frame_body(self, body) -> FrameBody:
        if body is None:
            return FrameBody()
        # body 是 BodyExpressionState（Phase 09）或 dict
        if isinstance(body, dict):
            return FrameBody(**{k: body.get(k) for k in (
                "expression", "gaze", "posture", "body_openness", "proximity", "movement_tempo",
                "movement_amplitude", "hesitation", "composure", "transition_style") if k in body},
                **({"micro_preferences": list(body.get("micro_motion", []))}),
                **({"pose": body.get("pose", "standing"),
                    "emotion_label": body.get("emotion_label", "neutral"),
                    "gaze_label": body.get("gaze_label", "front")}))
        # dataclass
        return FrameBody(
            expression=getattr(body, "expression", "neutral"),
            gaze=getattr(body, "gaze", "NONE"),
            posture=getattr(body, "posture", "relaxed"),
            body_openness=float(getattr(body, "body_openness", 0.5)),
            proximity=getattr(body, "proximity", "MAINTAIN"),
            movement_tempo=getattr(body, "movement_tempo", "normal"),
            movement_amplitude=float(getattr(body, "movement_amplitude", 0.5)),
            hesitation=float(getattr(body, "hesitation", 0.4)),
            composure=float(getattr(body, "composure", 0.7)),
            micro_preferences=list(getattr(body, "micro_motion", []) or []),
            transition_style=getattr(body, "transition_style", "SMOOTH"),
            pose=getattr(body, "pose", "standing"),
            emotion_label=getattr(body, "emotion_label", "neutral"),
            gaze_label=getattr(body, "gaze_label", "front"),
        )

    def _frame_interaction(self, interaction: Optional[Dict], act: FrameActivity,
                           wh: FrameWorldHint) -> FrameInteraction:
        # 默认：睡眠/away 不可互动；否则可
        sleeping = act.name in ("sleep", "nap")
        away = not wh.user_present or wh.interaction_availability < 0.3
        if interaction is not None:
            return FrameInteraction(**{k: interaction[k] for k in (
                "available", "focus_target", "accept_touch", "accept_drag", "busy",
                "response_mode") if k in interaction})
        resp = ResponseMode.SLEEPING.value if sleeping else (
            ResponseMode.AWAY.value if away else ResponseMode.AVAILABLE.value)
        return FrameInteraction(
            available=not sleeping and not away,
            focus_target="whole",
            accept_touch=not sleeping and not away,
            accept_drag=True,
            busy=bool(sleeping),
            response_mode=resp,
        )
