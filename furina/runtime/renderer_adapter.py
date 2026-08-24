"""RendererAdapter —— 把唯一 CharacterRuntimeFrame 转成旧 Renderer/set_pose_semantics 的输入。

收敛双轨（§10/§11）：
    BodyExpressionState → CharacterRuntimeFrame.body → 【Adapter】 → 旧 Renderer
（不再有 body_snapshot 独立外部接口 / derived_visual_state 并行喂 Renderer。）

本模块只做**语义 → 旧素材路径**的投影，不生成素材、不动 frame；缺失时退回 best-available，
并记录 ASSET_MISSING / DEGRADED。
"""
from __future__ import annotations

from typing import Dict, Optional

from .frame import CharacterRuntimeFrame


def renderer_adapter(frame: CharacterRuntimeFrame, *,
                     activity: str = "idle", walk_visible: bool = False,
                     head_touch: bool = False, degraded: Optional[Dict] = None) -> Dict:
    """由 frame 推导旧 renderer 需要的 (posture, emotion, gaze, action, micro, transition, deg)。

    返回 dict：{"pose","emotion","gaze","action","micro","transition","deg"}。
    - posture 来自 body.pose（语义姿态的素材标签，默认 standing）。
    - emotion 来自 body.emotion_label（旧素材情绪标签）。
    - gaze    来自 body.gaze_label。
    - action  由 activity + walk/head_touch 覆盖。
    - micro   来自 body.micro_preferences（若为空给默认 breathing/blink）。
    """
    body = frame.body
    act = activity or frame.activity.name or "idle"
    action = act
    # 走动覆盖
    if walk_visible:
        action = "walk"
    # 互动姿态优先
    if head_touch:
        action = "head_touch"

    deg = dict(degraded or {})
    # best-available：素材缺失只记录，不回 idle（§34）；此处由调用方填充 deg。
    return {
        "pose": body.pose or "standing",
        "emotion": body.emotion_label or "neutral",
        "gaze": body.gaze_label or "front",
        "action": action,
        "micro": list(body.micro_preferences) or ["breathing", "blink"],
        "transition": body.transition_style or "SMOOTH",
        "deg": deg,
    }
