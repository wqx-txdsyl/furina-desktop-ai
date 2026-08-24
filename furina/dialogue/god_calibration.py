"""God Self-reference Micro-Calibration（Phase 10 Freeze Calibration Gate，§20-26）。

只做**情境化小校准**，不重开 Dialogue 大改：
  - 允许语境（PROUD / PLAYFUL / PERFORMATIVE + BOAST / TEASE / CELEBRATE）→ PREFERRED（提示可自然用"本神"，但不强制）。
  - 抑制语境（SINCERE / RESPONSIBLE / VULNERABLE / 严肃帮助 / 真实脆弱 / 安静日常 / 疲惫 / 正式任务）→ SUPPRESSED。
  - 其余 → NEUTRAL（允许但不偏好）。
  - Cooldown：短期禁止连续"本神"（本神→本神），防止刷屏；**不写入 Memory**。

机制只有 allowed / preferred / suppressed。绝不 `if proud: force "本神"`。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# 允许偏好（§21）：mode / act
PREFERRED_MODES = {"PROUD", "PLAYFUL", "PERFORMATIVE"}
PREFERRED_ACTS = {"BOAST", "TEASE", "CELEBRATE"}
# 强烈抑制（§22）
SUPPRESSED_MODES = {"SINCERE", "RESPONSIBLE", "VULNERABLE"}
SUPPRESSED_ACTS = {"COMFORT", "ADMIT", "OFFER_HELP"}

# 抑制词（严肃/真实/日常）—— 仅用于辅助判定，不构成关键词强制
_SERIOUS_KEYWORDS = ("难受", "难过", "对不起", "抱歉", "别怕", "我在", "帮你", "感谢",
                     "加班", "工作", "梳理", "清单", "报告", "任务")


# ---------------------------------------------------------------- 每次输出的校准元信息
@dataclass
class GodCalibration:
    context: str                                    # allowed / preferred / suppressed / neutral
    gate_reason: str
    temperature_bias_note: str = ""                 # 注入 prompt 的一句话，非强制


class GodCalibrationGate:
    """Dialogue 运行时语境化"本神"小校准（短生命周期，不进 Memory）。"""

    def __init__(self, cooldown_seconds: float = 20.0, max_back_to_back: int = 1) -> None:
        self.cooldown_seconds = cooldown_seconds
        self.max_back_to_back = max_back_to_back
        self._last_god_at: float = 0.0
        self._last_used_in_cooldown: bool = False

    # -------------------------------------------------- 语境判定
    def calibrate(self, *, mode: str, dialogue_act: str = "",
                  emotion: str = "", user_text: str = "") -> GodCalibration:
        m = (mode or "").upper()
        act = (dialogue_act or "").upper()
        emotion_low = (emotion or "").lower()
        # 抑制优先：真诚/责任/脆弱 或 严肃帮助 → 强烈抑制
        if m in SUPPRESSED_MODES or act in SUPPRESSED_ACTS:
            return GodCalibration("suppressed", f"mode={m}/act={act} 抑制（真诚/责任/脆弱）")
        if any(k in (user_text or "") for k in _SERIOUS_KEYWORDS) and emotion_low in ("sad", "lonely", ""):
            return GodCalibration("suppressed", "严肃/真实/疲惫 -> 不端架子")
        # 允许偏好：表演/骄傲/玩笑 + 对应 act
        if m in PREFERRED_MODES or act in PREFERRED_ACTS:
            return GodCalibration("preferred", f"mode={m}/act={act} 可自然端架子（不强制）")
        if m in ("CASUAL",) and act in ("REACT", "COMMENT"):
            return GodCalibration("neutral", "普通闲聊：允许但不偏好")
        # 其余默认 allowed（不禁止）
        return GodCalibration("allowed", "一般情境允许")

    # -------------------------------------------------- prompt advice（非强制）
    def prompt_advice(self, cal: GodCalibration, *, force_turn: bool = False) -> str:
        if cal.context == "suppressed":
            return "（此刻语气真诚/认真，避免'本神'这类旧舞台自称。）"
        if cal.context == "preferred":
            return "（此刻可以自然地用一次'本神'表达骄傲/玩笑/表演，但只一次、别连用。）"
        return "（'本神'可用可不用，有度。）"

    # -------------------------------------------------- 输出后校验 + 冷却
    def gate_output(self, speech: str, *, cal: GodCalibration,
                    now: float | None = None) -> Optional[str]:
        """返回应保留的 speech；若触发 cooldown 或抑制且仍出现'本神'→ 返回 None（软拦截，不强制替换）。

        - suppressed 且含'本神' → 拦截（软）
        - 距上次'本神' < cooldown 且本次又含'本神' → 拦截
        """
        now = time.monotonic() if now is None else now
        has_god = "本神" in (speech or "")
        if not has_god:
            return speech
        # 抑制情境下出现 → 软拦截（不修改用户文本，直接退回静默，交给下一轮）
        if cal.context == "suppressed":
            return None
        # cooldown：上次刚用过，本次又用 → 拦截
        if self._last_used_in_cooldown and (now - self._last_god_at) < self.cooldown_seconds:
            return None
        # 放行：记录
        self._last_god_at = now
        self._last_used_in_cooldown = True
        return speech

    def note_spoke_god(self, speech: str) -> None:
        """外部确认台词真的带'本神'（供冷却状态用）。"""
        if "本神" in (speech or ""):
            self._last_god_at = time.monotonic()
            self._last_used_in_cooldown = True

    def state(self) -> Dict:
        return {"last_god_at": round(self._last_god_at, 3),
                "cooling": bool(self._last_used_in_cooldown)}
