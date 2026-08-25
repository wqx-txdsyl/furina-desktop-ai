"""C1 — Canon Identity（只读 adapter，runtime writable = NO）。

SOURCE OF TRUTH = furina/persona/furina_canon.py（唯一 Canon 源）。
Cognition 只做 read-only view，**禁止**把 Canon facts 复制进 SQLite 形成第二 truth。
"""
from __future__ import annotations

from typing import Any, Dict, List

from furina.persona import furina_canon as _canon


class CanonIdentityStore:
    """只读 Canon identity 视图：身份事实 / 人格轴 / 矛盾 / 反身份 / 语言指纹 / system persona。"""

    def __init__(self) -> None:
        self._module = _canon
        self._mutable = False

    # -------------------------------------------------- read-only views
    def identity_facts(self) -> List[Dict[str, str]]:
        return list(getattr(self._module, "IDENTITY_FACTS", []))

    def personality_axes(self) -> Dict[str, Dict[str, object]]:
        return {k: dict(v) for k, v in (getattr(self._module, "PERSONALITY_AXES", {}) or {}).items()}

    def contradictions(self) -> List[tuple]:
        return list(getattr(self._module, "CORE_CONTRADICTIONS", []))

    def anti_identity(self) -> List[str]:
        return list(getattr(self._module, "ANTI_IDENTITY", []))

    def voice_fingerprint(self) -> Dict[str, object]:
        return dict(getattr(self._module, "VOICE_FINGERPRINT", {}))

    def behavior_patterns(self) -> Dict[str, Dict[str, str]]:
        return {k: dict(v) for k, v in (getattr(self._module, "BEHAVIOR_PATTERNS", {}) or {}).items()}

    def dramatic_intensity(self) -> Dict[str, tuple]:
        return dict(getattr(self._module, "DRAMATIC_INTENSITY", {}))

    def periods(self) -> tuple:
        return tuple(getattr(self._module, "PERIODS", ()))

    def default_period(self) -> str:
        return str(getattr(self._module, "DEFAULT_PERIOD", "POST_AQ_CURRENT"))

    def system_persona(self) -> str:
        return str(getattr(self._module, "SYSTEM_PERSONA", ""))

    def evidence_for(self, model_claim: str) -> List[str]:
        try:
            return list(self._module.evidence_for(model_claim))
        except Exception:
            return []

    # -------------------------------------------------- snapshot（assembler 用）
    def snapshot(self) -> Dict[str, Any]:
        return {
            "identity_facts": self.identity_facts(),
            "personality_axes": self.personality_axes(),
            "contradictions": [f"{a} ↔ {b}" for a, b, _n, _e in self.contradictions()],
            "anti_identity": self.anti_identity(),
            "voice_fingerprint": self.voice_fingerprint(),
            "default_period": self.default_period(),
        }

    # -------------------------------------------------- 不变式证明
    def is_read_only(self) -> bool:
        """Canon identity runtime writable = NO（无任何写方法）。"""
        return self._mutable is False
