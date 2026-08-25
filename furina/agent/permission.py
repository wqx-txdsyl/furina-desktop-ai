"""权限系统（legacy-plan/5 §19-21）。

四档：L0 只读(无需确认) / L1 低风险写入(默认允许或可设自动) /
L2 高风险(需确认) / L3 敏感(必须确认)。
关键：Autonomy ≠ Unlimited Permission（§21）—— 芙宁娜可自主行为但不能自主扩权。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Callable, Optional


class Permission(int, enum.Enum):
    L0_READ = 0         # 只读
    L1_LOW_WRITE = 1    # 低风险写入
    L2_HIGH_RISK = 2    # 高风险
    L3_SENSITIVE = 3    # 敏感


@dataclass
class PermissionDecision:
    granted: bool
    reason: str = ""
    level: Optional[Permission] = None


class PermissionManager:
    """权限裁决 + 角色化确认钩子。

    允许自动放行 L0/L1；L2/L3 走 character-confirm 回调（弹角色口吻，legacy-plan/5 §20）。
    """

    def __init__(self) -> None:
        # 默认自动策略：放行 L0/L1；L2/L3 询问
        self.auto_allow_above: Permission = Permission.L1_LOW_WRITE
        self.on_confirm: Optional[Callable[[str, Permission], bool]] = None   # (描述, level)->bool

    def check(self, description: str, level: Permission) -> PermissionDecision:
        if level.value <= self.auto_allow_above.value:
            return PermissionDecision(True, "auto", level)
        # 需要用户确认 → 角色化
        if self.on_confirm:
            ok = self.on_confirm(description, level)
            return PermissionDecision(ok, "user" if ok else "denied", level)
        return PermissionDecision(False, "no-confirm-handler", level)
