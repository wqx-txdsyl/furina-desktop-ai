"""权限系统（legacy-plan/5 §19-21）+ Phase 14.1 Safety Closure。

四档：L0 只读(无需确认) / L1 低风险写入(显式用户任务内允许) /
L2 高风险(需本次任务明确高风险授权) / L3 敏感(必须单独 explicit confirmation)。

Phase 14.1 硬规则：
- **禁止 blanket allow L2/L3**：`on_confirm` 回调默认拒绝；只接受显式 authorization。
- `authorize(level)`：本次任务一次性显式授权（GUI confirm token / 测试 / 精选安全菜单）。
  **不得**因"用户发起了 Agent task"自动通过 L3；unknown/LLM plan 的 delete/overwrite
  绝不自动 confirm。
- `EffectivePermissionResolver`：动态权限 —— 覆盖已有文件 / delete / send 等必须升级档位，
  不能只靠 class static permission。
"""
from __future__ import annotations

import enum
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


class Permission(int, enum.Enum):
    L0_READ = 0         # 只读（自动允许）
    L1_LOW_WRITE = 1    # 低风险写入（显式用户任务内允许）
    L2_HIGH_RISK = 2    # 高风险（需本次任务明确高风险授权）
    L3_SENSITIVE = 3    # 敏感（必须单独 explicit confirmation）


@dataclass
class PermissionDecision:
    granted: bool
    reason: str = ""
    level: Optional[Permission] = None


class PermissionManager:
    """权限裁决 + Authorization Context。

    - L0/L1：自动放行（显式用户任务内的低风险写入）。
    - L2/L3：默认**拒绝**；只有 `authorize()` 显式授权或 `on_confirm` 显式确认才放行。
    - `on_confirm` 是"单独 explicit confirmation"钩子（GUI 弹窗）；生产默认不注册，
      或注册为返回 False 的拒绝回调 —— 绝不 fake confirm。
    """

    def __init__(self) -> None:
        # 默认自动策略：L0/L1 放行；L2/L3 需要显式授权
        self.auto_allow_above: Permission = Permission.L1_LOW_WRITE
        self.on_confirm: Optional[Callable[[str, Permission], bool]] = None
        self._explicit: set = set()      # 本次任务显式授权的 level（Authorization Context）

    # -------------------------------------------------- Authorization Context
    def authorize(self, level: Permission, *, scope: str = "task") -> None:
        """显式授权（本次任务一次性）：GUI confirm token / 测试 / 精选安全菜单任务。"""
        self._explicit.add(level)

    def revoke_all(self) -> None:
        """任务结束/新任务开始：清空授权上下文（授权不跨任务延续）。"""
        self._explicit.clear()

    def is_authorized(self, level: Permission) -> bool:
        return level in self._explicit

    # -------------------------------------------------- 裁决
    def check(self, description: str, level: Permission,
              *, effective_level: Optional[Permission] = None) -> PermissionDecision:
        """最终 effective permission 裁决（调用方应传入 dynamic effective level）。

        - effective_level 未给 → 用 class static level。
        - L0/L1 → auto allow；L2/L3 → 显式授权 / on_confirm 显式确认，否则拒绝。
        """
        eff = effective_level or level
        if eff.value <= self.auto_allow_above.value:
            return PermissionDecision(True, "auto", eff)
        # L2/L3：Authorization Context 显式授权
        if eff in self._explicit:
            return PermissionDecision(True, "explicit_authorization", eff)
        # L2/L3：单独 explicit confirmation（GUI 弹窗；默认拒绝，绝不 fake confirm）
        if self.on_confirm is not None:
            ok = self.on_confirm(description, eff)
            return PermissionDecision(ok, "user_confirm" if ok else "denied", eff)
        return PermissionDecision(False, "no-confirm-handler", eff)


# ================================================================ 动态权限（Phase 14.1 §3）
class EffectivePermissionResolver:
    """根据工具 + 运行时事实（目标是否存在）计算最终 effective permission。

    规则：
    - 新文件 create/write → L1（显式用户任务内）
    - **已有文件覆盖**（write_text / doc.write / copy / move / rename 目标已存在）→ L2
      （默认 overwrite=False；显式 overwrite + L2 授权才可覆盖）
    - delete → L2+
    - communication.send → L3
    - 其余 → 工具 class static permission
    """

    def __init__(self, fs_probe: Optional[Callable[[str], bool]] = None) -> None:
        # fs_probe(path)->bool：目标是否存在（可注入；默认 stat 磁盘）
        self._fs_probe = fs_probe or (lambda p: Path(os.path.expanduser(str(p))).exists())

    def effective_permission(self, tool, args: dict) -> Permission:
        name = getattr(tool, "name", "")
        args = args or {}
        if name == "fs.delete":
            return Permission.L2_HIGH_RISK
        if name == "comm.send_message":
            return Permission.L3_SENSITIVE
        if name in ("fs.write_text", "doc.write"):
            path = args.get("path")
            # 显式 overwrite=True 或目标已存在 → L2（覆盖已有文件）
            if args.get("overwrite") is True or (path and self._fs_probe(path)):
                return Permission.L2_HIGH_RISK
            return Permission.L1_LOW_WRITE
        if name in ("fs.copy", "fs.move", "fs.rename"):
            dest = args.get("dest") or args.get("new_name") or args.get("path")
            if dest and self._fs_probe(dest):
                return Permission.L2_HIGH_RISK
            return Permission.L1_LOW_WRITE
        if name in ("fs.create_file", "fs.append_text", "fs.create_dir", "fs.open_path",
                    "doc.create", "doc.append", "doc.edit"):
            return Permission.L1_LOW_WRITE
        return getattr(tool, "permission", Permission.L0_READ)

    def static_permission(self, tool, args: dict) -> Permission:
        """Planner 预执行校验用（**不做磁盘 probe**）：按显式参数保守估计。"""
        name = getattr(tool, "name", "")
        args = args or {}
        if name == "fs.delete":
            return Permission.L2_HIGH_RISK
        if name == "comm.send_message":
            return Permission.L3_SENSITIVE
        if name in ("fs.write_text", "doc.write", "fs.copy", "fs.move", "fs.rename"):
            # 显式 overwrite=True → 覆盖语义 → 至少 L2（保守）
            if args.get("overwrite") is True:
                return Permission.L2_HIGH_RISK
            return Permission.L1_LOW_WRITE
        if name in ("fs.create_file", "fs.append_text", "fs.create_dir", "fs.open_path",
                    "doc.create", "doc.append", "doc.edit"):
            return Permission.L1_LOW_WRITE
        return getattr(tool, "permission", Permission.L0_READ)
