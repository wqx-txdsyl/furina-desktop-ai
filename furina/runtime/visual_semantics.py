"""Phase 12V FIX B —— 生产VisualSemanticMapper：后端语义(posture/expression/gaze/action) → 素材词汇。

旧问题（V2/V3）：Frame 输出 posture=relaxed/engaged、expression=soft/tired、gaze=USER/SCREEN，
但 manifest 用的是 standing/sitting、neutral/happy、front/user/screen。生产代码没有映射，
导致大量请求退回 standing/neutral/front（"520/520=100%"其实是 fallback 掩盖）。

本模块是**唯一**语义→素材词汇的映射点，生产与 coverage 脚本共用同一份。

词汇表（data/assets/manifest.json）：
  posture: standing/sitting/lying/sleeping/crouching/leaning
  emotion: neutral/happy/proud/playful/embarrassed/annoyed/curious/excited/sad/sleepy/...
  gaze:    front/left/right/up/down/screen/user
  action:  read/eat/play/drink/think/nap/wave/dance/yawn/sigh/stretch/giggle/look/excited/...
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

# ---------------------------------------------------------------- 语义 posture → 素材 posture
_POSTURE_MAP = {
    # 后端 FrameBody/Embodiment posture（PostureIntent / base pose）
    "seated": "sitting",
    "sitting": "sitting",
    "sleeping": "sleeping",
    "lying": "lying",
    "leaning": "leaning",
    "crouching": "crouching",
    "resting": "sitting",        # 休息→坐下（有 sit_down / sitting_loop）
    "upright": "standing",
    "relaxed": "standing",
    "contained": "standing",
    "guarded": "standing",
    "engaged": "standing",
    "standing": "standing",
}

# ---------------------------------------------------------------- 语义 expression → 素材 emotion
_EXPRESSION_MAP = {
    "neutral": "neutral",
    "soft": "happy",             # 柔和的平和→轻快（有 happy 素材）
    "pleased": "happy",
    "proud": "proud",
    "playful": "playful",
    "embarrassed": "embarrassed",
    "guarded": "neutral",        # 无对应 → 中性（防御内敛不可见）
    "annoyed": "annoyed",
    "concerned": "sad",          # 关切/忧虑→担心（sad 最接近）
    "sad": "sad",
    "tired": "sleepy",
    "sleepy": "sleepy",
    "excited": "excited",
    "sincere": "neutral",        # 真诚→中性（无专门素材）
    "happy": "happy",
    "focus": "focus",            # read/observe_work 用
    "curious": "curious",
    "thinking": "thinking",
    "thoughtful": "thoughtful",
    "smug": "smug",
    "surprised": "surprised",
    "calm": "neutral",
    "lonely": "sad",
    "grateful": "happy",
    "confused": "neutral",
    "determined": "focus",
    "thoughtful": "thoughtful",
}

# ---------------------------------------------------------------- 语义 gaze → 素材 gaze
_GAZE_MAP = {
    "USER": "user",
    "SCREEN": "screen",
    "ACTIVITY_TARGET": "screen",
    "AWAY": "front",            # 回避（配合 side_history 生成 side）
    "SIDE": "left",            # 由 side_history 交替 left/right（见 _gaze_side）
    "DOWN": "down",
    "AROUND": "left",
    "NONE": "front",
    "front": "front",
    "user": "user",
    "screen": "screen",
    "left": "left",
    "right": "right",
    "up": "up",
    "down": "down",
}

# ---------------------------------------------------------------- activity → 素材 action
_ACTION_MAP = {
    "read": "read",
    "eat": "eat",
    "play": "play",
    "play_with_object": "play",
    "drink": "drink",
    "think": "think",
    "nap": "nap",
    "greet": "wave",
    "wave": "wave",
    "dance": "dance",
    "yawn": "yawn",
    "sigh": "sigh",
    "stretch": "stretch",
    "giggle": "giggle",
    "excited": "excited",
    "look_around": "look",
    "look": "look",
    "celebrate": "excited",
    "groom": "stretch",
    "hold_tea": "hold_tea",
    "hold_cake": "hold_cake",
    "hold_book": "hold_book",
    "hold_phone": "hold_phone",
    "hold_gift": "hold_gift",
    "head_touch": "head_touch",
    "poke": "poke",
}

# 无专属 action asset 的活动（用 idle action；posture/emotion 仍映射）
_ACTION_EMPTY_OK = {"idle", "talk", "observe_user", "observe_work", "watch_user", "approach_user",
                    "assist_user", "offer_help", "invite_user", "seek_attention", "comfort",
                    "sleep", "rest", "walk", "wander", "explore", "tidy", "daydream", "continue",
                    "agent_planning", "agent_report"}


@dataclass
class MappedSemantics:
    """一段"后端语义 → 素材词汇"的映射结果，附匹配质量。"""
    posture: str = "standing"
    expression: str = "neutral"
    gaze: str = "front"
    action: str = "idle"
    degraded: list = None          # 记录降级原因（如 "posture:seated→sitting"）
    match: str = "EXACT"           # EXACT / COMPATIBLE_DEGRADED / SEMANTIC_LOSS / MISSING

    def __post_init__(self):
        if self.degraded is None:
            self.degraded = []

    @property
    def quality(self) -> str:
        return self.match


class VisualSemanticMapper:
    """后端语义 → 素材词汇。所有映射集中于此，供 Runtime 与 coverage 共用。"""

    def __init__(self, manifest=None) -> None:
        self.manifest = manifest
        self._gaze_side = "left"    # SIDE/AWAY 交替 left/right

    # -------------------------------------------------- posture
    def map_posture(self, posture: str) -> Tuple[str, list]:
        p = (posture or "").lower().strip()
        if not p:
            return "standing", ["posture:empty"]
        asset = _POSTURE_MAP.get(p)
        if asset:
            return asset, ([] if asset == p else [f"posture:{p}->{asset}"])
        # 未知 posture：尝试直接当成素材 posture；否则 standing
        if p in ("standing", "sitting", "lying", "sleeping", "crouching", "leaning"):
            return p, []
        return "standing", [f"posture:{p}->standing"]

    # -------------------------------------------------- expression
    def map_expression(self, expression: str) -> Tuple[str, list]:
        e = (expression or "").lower().strip()
        if not e:
            return "neutral", ["expression:empty"]
        asset = _EXPRESSION_MAP.get(e)
        if asset:
            return asset, ([] if asset == e else [f"expression:{e}->{asset}"])
        if e in _EXPRESSION_MAP.values():
            return e, []
        return "neutral", [f"expression:{e}->neutral"]

    # -------------------------------------------------- gaze
    def map_gaze(self, gaze: str) -> Tuple[str, list]:
        g = (gaze or "").upper().strip()
        if not g or g == "NONE":
            return "front", ["gaze:NONE->front"]
        if g in ("SIDE", "AWAY", "AROUND"):
            # 交替到侧向，避免每次都 same
            side = "left" if self._gaze_side == "left" else "right"
            return side, [f"gaze:{g}->{side}"]
        asset = _GAZE_MAP.get(g)
        if asset:
            return asset, ([] if asset == g.lower() else [f"gaze:{g}->{asset}"])
        if g.lower() in ("front", "left", "right", "up", "down", "screen", "user"):
            return g.lower(), []
        return "front", [f"gaze:{g}->front"]

    # -------------------------------------------------- action
    def map_action(self, activity: str, interaction_override: Optional[str] = None) -> Tuple[str, list]:
        if interaction_override:
            act = _ACTION_MAP.get(interaction_override)
            if act:
                return act, []
            if interaction_override == "drag":
                return "idle", ["action:drag->MISSING"]   # 无 drag 素材，显式降级
        a = (activity or "").lower().strip()
        if not a:
            return "idle", ["action:empty"]
        asset = _ACTION_MAP.get(a)
        if asset:
            return asset, []
        if a in _ACTION_EMPTY_OK:
            return "idle", []
        # 未知 activity → idle
        return "idle", [f"action:{a}->idle"]

    # -------------------------------------------------- 整段映射
    def map(self, *, posture: str, expression: str, gaze: str, activity: str,
            interaction_override: Optional[str] = None) -> MappedSemantics:
        mp, dp = self.map_posture(posture)
        me, de = self.map_expression(expression)
        mg, dg = self.map_gaze(gaze)
        ma, da = self.map_action(activity, interaction_override)
        degraded = dp + de + dg + da
        # 匹配质量：无降级 = EXACT；仅表达/视线/姿态近似 = COMPATIBLE_DEGRADED；无 action 素材但属空集 = COMPATIBLE_DEGRADED；未知丢弃 = SEMANTIC_LOSS
        miss = [d for d in degraded if "MISSING" in d]
        if miss:
            match = "MISSING"
        elif any("->standing" in d or "->neutral" in d or "->front" in d for d in degraded):
            match = "SEMANTIC_LOSS"
        elif degraded:
            match = "COMPATIBLE_DEGRADED"
        else:
            match = "EXACT"
        return MappedSemantics(posture=mp, expression=me, gaze=mg, action=ma,
                               degraded=degraded, match=match)
