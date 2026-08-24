"""Behavior Resolver —— Activity → Behavior Profile → Visual State（任务书 §15-16, §19, §37）。

语义核心：**Activity（她想做什么）才是核心**，Pose/Emotion/Gaze 是它当前的视觉状态。
不做自由笛卡尔积（sitting × 9emotion × 6gaze ...），而是一个 Activity 对应一个
**Behavior Profile**，再从 Profile 推导具体视觉状态。

例如：
    Activity = observe_user
    Profile  = { pose: sitting, emotion: curious, gaze: user,
                 transition: sit_down, action: micro, micro: breathing+blink }

这样系统好扩展：加新 Activity 只需加一条 Profile，不产生几千种组合。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class BehaviorProfile:
    """一个 Life Activity 所需的视觉表现（语义核心）。"""
    activity: str
    pose: str = "standing"            # standing / sitting / lying / sleeping / crouching / leaning
    emotion: str = "neutral"          # neutral / happy / curious / thinking / proud / sleepy / annoyed ...
    gaze: str = "front"               # user / screen / front / left / right / up / down
    transition: Optional[str] = None  # 进入该活动的过渡序列（sit_down / lie_down / go_sleep ...）
    action: str = "idle"              # idle / micro / drink / eat / read / play / wave / stretch ...
    micro: List[str] = field(default_factory=lambda: ["breathing", "blink"])
    macro: str = "idle"               # 对应宏观状态（living / working / engaged / resting / sleeping）
    speakable: bool = False           # 该活动值得开口说话（交给 DialogueBrain）


# Activity → Behavior Profile（任务书 §19 生活行为池）
BEHAVIOR_PROFILES: dict[str, BehaviorProfile] = {
    # ---- 自主生活 SELF ----
    "read":       BehaviorProfile("read", "sitting", "thinking", "screen", "sit_down", "read", ["breathing", "blink"], "living"),
    "drink":      BehaviorProfile("drink", "sitting", "happy", "front", "sit_down", "drink", ["breathing", "blink"], "living"),
    "eat":        BehaviorProfile("eat", "sitting", "happy", "front", "sit_down", "eat", ["breathing", "blink"], "living"),
    "rest":       BehaviorProfile("rest", "lying", "sleepy", "front", "lie_down", "idle", ["breathing"], "resting"),
    "stretch":    BehaviorProfile("stretch", "standing", "sleepy", "front", None, "stretch", ["breathing"], "living"),
    "think":      BehaviorProfile("think", "sitting", "thinking", "screen", "sit_down", "read", ["breathing", "blink"], "living"),
    "explore":    BehaviorProfile("explore", "standing", "curious", "front", None, "idle", ["breathing", "blink", "gaze_change"], "living"),
    "look_around": BehaviorProfile("look_around", "standing", "curious", "front", None, "idle", ["blink", "gaze_change"], "living"),
    "daydream":   BehaviorProfile("daydream", "sitting", "thinking", "up", "sit_down", "idle", ["breathing"], "living"),
    "tidy":       BehaviorProfile("tidy", "standing", "proud", "front", None, "idle", ["breathing"], "living"),
    "play":       BehaviorProfile("play", "standing", "happy", "user", None, "play", ["breathing", "blink"], "living"),
    # ---- 观察/陪伴用户 USER ----
    "observe_user": BehaviorProfile("observe_user", "sitting", "curious", "user", "sit_down", "idle",
                                  ["breathing", "blink", "gaze_change"], "working", speakable=True),
    "observe_work": BehaviorProfile("observe_work", "sitting", "neutral", "screen", "sit_down", "idle",
                                  ["breathing", "blink"], "working"),
    "watch_user":   BehaviorProfile("watch_user", "standing", "curious", "user", None, "idle",
                                  ["blink", "gaze_change"], "engaged", speakable=True),
    "approach_user": BehaviorProfile("approach_user", "standing", "curious", "user", None, "walk",
                                    ["breathing"], "living", speakable=True),
    "greet":        BehaviorProfile("greet", "standing", "happy", "user", None, "wave",
                                    ["breathing", "blink"], "engaged", speakable=True),
    "talk":         BehaviorProfile("talk", "standing", "happy", "user", None, "idle",
                                    ["breathing", "blink"], "engaged", speakable=True),
    "ask_user":     BehaviorProfile("ask_user", "standing", "happy", "user", None, "idle",
                                    ["breathing", "blink"], "engaged", speakable=True),
    "invite_user":  BehaviorProfile("invite_user", "sitting", "playful", "user", "sit_down", "play",
                                    ["breathing", "blink"], "engaged", speakable=True),
    "seek_attention": BehaviorProfile("seek_attention", "standing", "playful", "user", None, "idle",
                                    ["breathing", "blink"], "engaged", speakable=True),
    "offer_help":   BehaviorProfile("offer_help", "sitting", "concerned", "user", "sit_down", "idle",
                                    ["breathing", "blink"], "working", speakable=True),
    # ---- 运动 MOVEMENT ----
    "walk":   BehaviorProfile("walk", "standing", "neutral", "front", None, "walk", ["breathing"], "living"),
    "wander": BehaviorProfile("wander", "standing", "neutral", "front", None, "walk", ["breathing"], "living"),
    # ---- 特殊 SPECIAL ----
    "celebrate": BehaviorProfile("celebrate", "standing", "happy", "user", None, "excited",
                                 ["breathing", "blink"], "engaged", speakable=True),
    "comfort":   BehaviorProfile("comfort", "sitting", "concerned", "user", "sit_down", "idle",
                                 ["breathing", "blink"], "engaged", speakable=True),
    # ---- 生存 ----
    "sleep": BehaviorProfile("sleep", "sleeping", "sleepy", "front", "go_sleep", "idle", ["breathing"], "sleeping"),
    "nap":   BehaviorProfile("nap", "sleeping", "sleepy", "front", "go_sleep", "idle", ["breathing"], "sleeping"),
    # ---- 兜底 ----
    "idle":     BehaviorProfile("idle", "standing", "neutral", "front", None, "idle", ["breathing", "blink"], "idle"),
    "continue": BehaviorProfile("continue", "standing", "neutral", "front", None, "idle", ["breathing", "blink"], "idle"),
}


def profile_for(activity: str) -> BehaviorProfile:
    """取 Activity 的 Behavior Profile；未知活动回退到安全默认（绝不凭空造状态）。"""
    return BEHAVIOR_PROFILES.get(activity or "idle", BEHAVIOR_PROFILES["idle"])


def derive_visual_state(activity: str, emotion_override: str = "") -> dict:
    """Activity → Visural State (pose/emotion/gaze/action/transition/micro/macro)。

    用户明确要求的语义核心：Activity 决定 Profile，Profile 再决定具体视觉维度。
    """
    p = profile_for(activity)
    # 若 Brain 给了情绪，用它；否则用 Profile 的默认情绪
    return {
        "activity": p.activity,
        "pose": p.pose,
        "emotion": emotion_override or p.emotion,
        "gaze": p.gaze,
        "action": p.action,
        "transition": p.transition,
        "micro": list(p.micro),
        "macro": p.macro,
        "speakable": p.speakable,
    }
