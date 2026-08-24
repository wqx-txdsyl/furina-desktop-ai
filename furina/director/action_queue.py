"""Action Request（plan/8 §2）。

所有系统都不能直接控制身体，必须提交 ActionRequest 到 Director。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class ActionRequest:
    source: str                # behavior / interaction / agent / state
    action: str
    priority: int              # 对齐 state.P_* 或 director 的优先级
    interruptible: bool = True
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        return f"[{self.source}:{self.action} pri={self.priority} int={self.interruptible}] {self.reason}".strip()
