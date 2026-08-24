"""状态持久化骨架：供崩溃恢复 / 开机还原（plan/7 §46, §45）。

首版用 JSON 快照；后续可并入 SQLite 记忆存储。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from furina.core import get_logger
from .state_model import CharacterState

log = get_logger("state.store")


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, state: CharacterState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "macro": state.life.macro.value,
            "activity": state.life.activity,
            "needs": {
                k: getattr(state.needs, k)
                for k in state.needs.__dataclass_fields__  # type: ignore[attr-defined]
            },
            "mood": state.emotion.mood,
            "position": {"x": 0.0, "y": 0.0},  # 位置由 Runtime 维护
            "saved_at": __import__("time").time(),
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> CharacterState:
        if not self.path.exists():
            return CharacterState()
        try:
            data: Dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
            st = CharacterState()
            if "macro" in data:
                from .state_model import MacroState
                st.life.macro = MacroState(data["macro"])
            if "needs" in data:
                for k, v in data["needs"].items():
                    setattr(st.needs, k, v)
            if "mood" in data:
                st.emotion.mood = data["mood"]
            return st
        except Exception as e:  # pragma: no cover
            log.warning("state load failed: %s", e)
            return CharacterState()
