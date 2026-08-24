"""Body Validator（§43）—— 轻量兼容校验，不做复杂修复。

只覆盖现有活动/姿态/对话/疲劳冲突：发现越界就 clamp / degrade 到兼容语义意图，
并**记录原因**（供 debug "为什么她刚才移开了视线"）。

冲突项：
    activity_pose_conflict       睡眠/躺/坐 vs 站姿
    sleep_gaze_conflict          睡眠时 gaze_user → 无效
    high_fatigue_energy_conflict 高疲劳仍 energy tempo / 大振幅
    persona_mode_conflict        PERFORMATIVE vs 睡眠（模式被活动压掉）
    speech_body_conflict         沉默却高口语同步
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .model import (
    BodyExpressionState, GazeIntent, PostureIntent, TempoIntent, SpeechSync, ProximityIntent,
)

# 姿态宽容集（语义 -> 可组合的 posture）
_POSE_COMPAT = {
    "sleep": {PostureIntent.SLEEPING.value},
    "rest": {PostureIntent.LYING.value, PostureIntent.RELAXED.value, PostureIntent.RESTING.value},
    "nap": {PostureIntent.SLEEPING.value, PostureIntent.LYING.value},
    "read": {PostureIntent.SEATED.value, PostureIntent.RELAXED.value},
    "think": {PostureIntent.SEATED.value, PostureIntent.RELAXED.value},
    "daydream": {PostureIntent.SEATED.value, PostureIntent.RELAXED.value},
    "eat": {PostureIntent.SEATED.value, PostureIntent.RELAXED.value},
    "drink": {PostureIntent.SEATED.value, PostureIntent.RELAXED.value},
    "idle": {PostureIntent.RELAXED.value, PostureIntent.UPRIGHT.value, PostureIntent.LEANING.value,
             PostureIntent.RESTING.value},
}
# 高打扰/表演不允许的姿态（语义简化）
_UPRIGHT_HEAVY = {PostureIntent.UPRIGHT.value, PostureIntent.ENGAGED.value, PostureIntent.GUARDED.value}


class BodyValidator:
    """轻量冲突校验器：越界则 clamp/degrade 并记录。不返回布尔，产出修正后的 state。"""

    def validate(self, st: BodyExpressionState, *, activity: str = "idle",
                 fatigue: float = 20.0, silence: bool = False) -> BodyExpressionState:
        r: List[str] = []
        act = activity or "idle"

        # ---- activity_pose_conflict：站姿类在躺/坐/睡活动里不兼容
        allowed = _POSE_COMPAT.get(act)
        if allowed is not None and st.posture not in allowed and act not in ("sleep",):
            # 只对"明显站姿/表演姿"降级；relaxed 是安全兜底
            if st.posture in _UPRIGHT_HEAVY:
                st.posture = PostureIntent.SEATED.value if act in ("read", "think") else PostureIntent.RELAXED.value
                r.append(f"activity_pose_conflict:{st.posture}")

        # ---- sleep_gaze_conflict
        if act in ("sleep", "nap") and st.gaze not in (GazeIntent.NONE.value, GazeIntent.DOWN.value):
            st.gaze = GazeIntent.NONE.value
            r.append("sleep_gaze_conflict")

        # ---- high_fatigue_energy_conflict
        if fatigue >= 70:
            if st.movement_tempo in (TempoIntent.LIVELY.value, TempoIntent.ENERGETIC.value, TempoIntent.NORMAL.value):
                st.movement_tempo = TempoIntent.SLOW.value
                r.append("high_fatigue_energy_conflict")
            if st.movement_amplitude > 0.35:
                st.movement_amplitude = 0.25
                r.append("high_fatigue_amplitude_clamp")

        # ---- persona_mode_conflict：PERFORMATIVE 在 sleep/rest 不可能成立（被活动压掉）
        if act in ("sleep", "nap", "rest") and st.posture in _UPRIGHT_HEAVY:
            st.posture = PostureIntent.LYING.value if act == "rest" else PostureIntent.SLEEPING.value
            r.append("persona_mode_conflict(activity_wins)")

        # ---- speech_body_conflict：沉默却仍高口语同步
        if silence and st.speech_sync != SpeechSync.NONE.value:
            st.speech_sync = SpeechSync.NONE.value
            r.append("speech_body_conflict")

        st.reasons = (st.reasons or []) + r
        return st
