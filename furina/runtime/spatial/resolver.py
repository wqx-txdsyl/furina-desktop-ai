"""Phase 12 SpatialIntentResolver —— 把 CharacterRuntimeFrame 空间语义解析为空间意图。

**边界**：只做"解释"，不做"决策"。
  - 意图来源优先级：frame.motion.intent > frame.body.proximity > activity 语义回退。
  - 速度：frame.motion.speed_semantic（若指定）否则 frame.body.movement_tempo。
  - 犹豫 / 过渡 / 幅度：直接消费 frame.body。
  - **不读 Needs / Emotion / Relationship / Memory / Identity**
    （RC1 契约：前端只消费 Frame；需要什么由后端在 Frame 里表达）。

本类可 headless 测试；frame 是 duck-typed（真实 CharacterRuntimeFrame 或等价结构）。
"""
from __future__ import annotations

from typing import Any

from .model import ResolvedIntent, SpatialIntent, SpeedSemantic

# activity → 空间意图回退（§31：消费 Backend activity 语义，非重新决策）
_ACTIVITY_FALLBACK = {
    "approach_user": SpatialIntent.APPROACH.value,
    "observe_work": SpatialIntent.NEAR.value,
    "observe_user": SpatialIntent.NEAR.value,
    "assist_user": SpatialIntent.NEAR.value,
    "watch_user": SpatialIntent.NEAR.value,
    "talk": SpatialIntent.NEAR.value,
    "greet": SpatialIntent.APPROACH.value,
    "seek_attention": SpatialIntent.APPROACH.value,
    "offer_help": SpatialIntent.APPROACH.value,
    "invite_user": SpatialIntent.APPROACH.value,
    "comfort": SpatialIntent.APPROACH.value,
    "celebrate": SpatialIntent.NEAR.value,
}

# activity → 是否允许"自主踱步"（仅当后端 activity 明确为走动/探索，§30 禁止前端自造 wander）
_WANDER_ACTIVITIES = {"walk", "wander", "explore", "look_around", "stretch", "dance"}


class SpatialIntentResolver:
    """Frame → ResolvedIntent（纯语义，无位置状态）。"""

    def resolve(self, frame: Any) -> ResolvedIntent:
        motion = getattr(frame, "motion", None)
        body = getattr(frame, "body", None)
        activity = getattr(getattr(frame, "activity", None), "name", "idle")
        world_hint = getattr(frame, "world_hint", None)
        meta = getattr(frame, "meta", None)
        frame_id = int(getattr(meta, "frame_id", 0) or 0)

        # ---- 意图：motion.intent 优先 ----
        intent = self._intent_from_motion(motion)
        # ---- 其次 body.proximity ----
        if intent == SpatialIntent.NONE.value:
            intent = self._intent_from_proximity(body)
        # ---- 最后 activity 语义回退（§31）----
        fallback = self._intent_from_activity(activity)
        if intent in (SpatialIntent.NONE.value, SpatialIntent.MAINTAIN.value):
            # activity 明确要动（approach_user 等）优先于"未指定的 MAINTAIN"
            if fallback in (SpatialIntent.APPROACH.value, SpatialIntent.WITHDRAW.value,
                            SpatialIntent.NEAR.value, SpatialIntent.FAR.value):
                intent = fallback

        # ---- 速度 ----
        speed = self._speed(motion, body)
        # ---- 表现参数（直接消费）----
        hes = getattr(body, "hesitation", 0.4)
        hesitation = float(hes) if hes is not None else 0.4
        transition = getattr(body, "transition_style", "SMOOTH") or "SMOOTH"
        amp = getattr(body, "movement_amplitude", 0.5)
        amplitude = float(amp) if amp is not None else 0.5
        allow_reposition = bool(getattr(motion, "allow_reposition", False))
        tempo = getattr(body, "movement_tempo", "normal") or "normal"

        # ---- 世界 cue ----
        user_present = bool(getattr(world_hint, "user_present", True)) if world_hint else True
        user_working = bool(getattr(world_hint, "user_working", False)) if world_hint else False

        # ---- 踱步许可（仅在明确活动时才开；§30/§34）----
        wander_allowed = activity in _WANDER_ACTIVITIES
        # 踱步活动里，若是"中性 MAINTAIN"（默认 proximity），应视为 NONE 让 planner 走踱步路径；
        # 若 proximity/motion 明确给出 APPROACH/WITHDRAW 等，仍尊重之（不把真实意图覆盖成踱步）。
        if wander_allowed and intent == SpatialIntent.MAINTAIN.value:
            intent = SpatialIntent.NONE.value

        reason = f"{activity}->{intent}"
        return ResolvedIntent(
            intent=intent,
            speed_semantic=speed,
            tempo=tempo,
            hesitation=min(1.0, max(0.0, hesitation)),
            transition_style=transition,
            amplitude=min(1.0, max(0.0, amplitude)),
            allow_reposition=allow_reposition,
            wander_allowed=wander_allowed,
            source_frame_id=frame_id,
            reason=reason,
            activity=activity,
            user_present=user_present,
            user_working=user_working,
        )

    # -------------------------------------------------- 各部分映射
    @staticmethod
    def _intent_from_motion(motion: Any) -> str:
        if motion is None:
            return SpatialIntent.NONE.value
        raw = str(getattr(motion, "intent", "") or "").upper()
        mapping = {
            "MAINTAIN": SpatialIntent.MAINTAIN.value,
            "APPROACH": SpatialIntent.APPROACH.value,
            "WITHDRAW": SpatialIntent.WITHDRAW.value,
            "REPOSITION": SpatialIntent.REPOSITION.value,
            "NONE": SpatialIntent.NONE.value,
            "": SpatialIntent.NONE.value,
        }
        return mapping.get(raw, SpatialIntent.NONE.value)

    @staticmethod
    def _intent_from_proximity(body: Any) -> str:
        if body is None:
            return SpatialIntent.NONE.value
        raw = str(getattr(body, "proximity", "") or "").upper()
        mapping = {
            "MAINTAIN": SpatialIntent.MAINTAIN.value,
            "APPROACH": SpatialIntent.APPROACH.value,
            "WITHDRAW": SpatialIntent.WITHDRAW.value,
            "NEAR": SpatialIntent.NEAR.value,
            "FAR": SpatialIntent.FAR.value,
            "NONE": SpatialIntent.NONE.value,
        }
        return mapping.get(raw, SpatialIntent.NONE.value)

    @staticmethod
    def _intent_from_activity(activity: str) -> str:
        return _ACTIVITY_FALLBACK.get(activity or "idle", SpatialIntent.NONE.value)

    @staticmethod
    def _speed(motion: Any, body: Any) -> str:
        # motion.speed_semantic（SLOW/NORMAL/FAST）优先
        mot = getattr(motion, "speed_semantic", "") if motion is not None else ""
        mot = str(mot or "").upper()
        if mot in ("SLOW", "NORMAL", "FAST"):
            return {"SLOW": SpeedSemantic.SLOW.value,
                    "NORMAL": SpeedSemantic.NORMAL.value,
                    "FAST": SpeedSemantic.ENERGETIC.value}.get(mot, SpeedSemantic.NORMAL.value)
        # 否则 body.movement_tempo（very_slow..energetic）直接透传
        tempo = getattr(body, "movement_tempo", "normal") if body is not None else "normal"
        tempo = str(tempo or "normal").lower()
        allowed = {v.value for v in SpeedSemantic}
        return tempo if tempo in allowed else SpeedSemantic.NORMAL.value
