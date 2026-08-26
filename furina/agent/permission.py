"""权限系统（legacy-plan/5 §19-21）+ Phase 14.1/14.1.1 Safety Closure。

四档：L0 只读(自动允许) / L1 低风险写入(显式用户任务内允许) /
L2 高风险(需本次任务明确高风险授权) / L3 敏感(必须单独 explicit confirmation)。

Phase 14.1.1 硬规则（Task-scoped Authorization）：
- **Authorization 必须绑定"本次 Agent task"**：`AuthorizationContext`（authorization_id /
  max_permission / allowed_tools / allowed_path_root / source），每次 `AgentRuntime.execute`
  拥有独立 immutable/task-local context；**禁止跨并发任务共享的全局 set{Permission}**。
- 普通任意自然语言任务 default：L0/L1 only；L2/L3 deny —— 除非本任务有匹配授权。
- **L3 不得被 L2 token 覆盖**（max_permission 语义）。
- 菜单任务"整理下载文件夹"可获 bounded L2：allowed_tools 限定 organize 确定性序列、
  allowed_path_root 限定用户 Downloads；fs.delete 任意路径 / doc.write outside root → DENIED。
- 任务结束只销毁该 task context；不得 revoke 其它并发 task 的 context。
- `on_confirm` 保留为"单独 explicit confirmation"（GUI 弹窗）；生产默认拒绝（绝不 fake confirm）。
"""
from __future__ import annotations

import enum
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple


class Permission(int, enum.Enum):
    L0_READ = 0         # 只读（自动允许）
    L1_LOW_WRITE = 1    # 低风险写入（显式用户任务内允许）
    L2_HIGH_RISK = 2    # 高风险（需本次任务明确高风险授权）
    L3_SENSITIVE = 3    # 敏感（必须单独 explicit confirmation）


@dataclass(frozen=True)
class AuthorizationContext:
    """本次 Agent task 的独立授权上下文（immutable / task-local）。"""

    authorization_id: str
    max_permission: Permission
    allowed_tools: Tuple[str, ...] = ()     # 空 = 不限工具（仅按权限）
    allowed_path_root: str = ""             # 空 = 不限路径
    source: str = ""
    is_default: bool = False                # True = 未显式授权的默认任务（L0/L1 only + on_confirm 路径）

    def allows(self, tool: str, paths: Tuple[str, ...] = ()) -> bool:
        """tool / **所有** filesystem path 是否在授权范围内。

        - allowed_tools 非空 → tool 必须在其中（否则 DENIED，无论 L0/L1/L2/L3）；
        - allowed_path_root 非空 → **每个** path 都必须在 root 内（source/dest/path/base/
          target/file 全查；rename 由调用方传最终 destination，不单独查 basename）。
        """
        if self.allowed_tools and tool and tool not in self.allowed_tools:
            return False
        if self.allowed_path_root and paths:
            root = os.path.normpath(os.path.abspath(os.path.expanduser(self.allowed_path_root)))
            for p in paths:
                if not isinstance(p, str) or not p.strip():
                    continue
                pp = os.path.normpath(os.path.abspath(os.path.expanduser(p)))
                if not (pp == root or pp.startswith(root + os.sep)):
                    return False
        return True


@dataclass
class PermissionDecision:
    granted: bool
    reason: str = ""
    level: Optional[Permission] = None


class PermissionManager:
    """权限裁决 + Task-scoped Authorization Context。

    - L0/L1：自动放行（显式用户任务内的低风险写入）。
    - L2/L3：**只接受本 task 的 AuthorizationContext**（匹配 max_permission + tool/path scope）
      或 on_confirm 单独 explicit confirmation；默认拒绝。
    - 无任何跨任务共享的授权集合 —— 每次 execute 的 context 独立，天然并发隔离。
    """

    def __init__(self) -> None:
        # 默认自动策略：L0/L1 放行；L2/L3 需要 task-scoped 授权或显式确认
        self.auto_allow_above: Permission = Permission.L1_LOW_WRITE
        self.on_confirm: Optional[Callable[[str, Permission], bool]] = None

    # -------------------------------------------------- Task-scoped Authorization
    def new_task_context(self, *, max_permission: Permission,
                         allowed_tools: Tuple[str, ...] = (),
                         allowed_path_root: str = "",
                         source: str = "") -> AuthorizationContext:
        """为**本次 Agent task**创建独立授权上下文（调用方每次 execute 新建）。"""
        return AuthorizationContext(
            authorization_id=f"auth_{uuid.uuid4().hex[:10]}",
            max_permission=max_permission,
            allowed_tools=tuple(allowed_tools or ()),
            allowed_path_root=allowed_path_root or "",
            source=source,
            is_default=False,
        )

    def default_task_context(self) -> AuthorizationContext:
        """普通自然语言任务的默认上下文：L0/L1 only（L2/L3 需 on_confirm 显式确认）。"""
        return AuthorizationContext(
            authorization_id="default", max_permission=Permission.L1_LOW_WRITE,
            source="default", is_default=True,
        )

    # -------------------------------------------------- 裁决
    def check(self, description: str, level: Permission,
              *, effective_level: Optional[Permission] = None,
              task_auth: Optional[AuthorizationContext] = None,
              tool: str = "", paths: Tuple[str, ...] = ()) -> PermissionDecision:
        """最终 effective permission 裁决。

        **Scope 先于 Permission Level**（Phase 14.1.1 FINAL）：
        对显式任务授权（task_auth.is_default=False）——
          1. 先验证 scope：tool ∈ allowed_tools（若非空）+ **所有** path args 在
             allowed_path_root 内（若非空）；scope mismatch → DENIED/task_scope_mismatch，
             **无论该 step 是 L0/L1/L2/L3 都不得绕过 task scope**；
          2. scope 通过后再按 permission level：L0/L1 → auto allow；L2/L3 → max_permission
             （L3 不得被 L2 token 覆盖）。
        默认任务（无显式授权 / is_default=True）——
          L0/L1 → auto allow；L2/L3 仅 on_confirm 单独 explicit confirmation（生产默认拒绝）。
        """
        eff = effective_level or level
        if task_auth is not None and not task_auth.is_default:
            # 显式任务授权：SCOPE → PERMISSION LEVEL
            if not task_auth.allows(tool, paths):
                return PermissionDecision(False, "task_scope_mismatch", eff)
            if eff.value <= task_auth.max_permission.value:
                return PermissionDecision(True, f"task_authorization:{task_auth.source}", eff)
            return PermissionDecision(False, "insufficient_authorization", eff)
        # 默认任务（无显式授权）
        if eff.value <= self.auto_allow_above.value:
            return PermissionDecision(True, "auto", eff)
        if self.on_confirm is not None:
            ok = self.on_confirm(description, eff)
            return PermissionDecision(ok, "user_confirm" if ok else "denied", eff)
        return PermissionDecision(False, "no-authorization", eff)


# ================================================================ 动态权限（Phase 14.1 §3 / 14.1.1 §2）
class EffectivePermissionResolver:
    """根据工具 + 运行时事实（目标是否存在）计算最终 effective permission。

    规则：
    - 新文件 create/write → L1（显式用户任务内）
    - **已有文件覆盖**（write_text / doc.write / copy / move / rename 目标已存在）→ L2
      （默认 overwrite=False；显式 overwrite + L2 授权才可覆盖）
    - delete → L2+
    - communication.send → L3
    - Office *.create（docx/pptx/xlsx）：**永不覆盖已有文件**（工具层拒绝，无需升级权限）
    - 其余 → 工具 class static permission
    """

    def __init__(self, fs_probe: Optional[Callable[[str], bool]] = None) -> None:
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
        if name in ("docx.create", "pptx.create", "xlsx.create"):
            # Phase 14.1.1 §2：Office create 永不覆盖已有文件（工具层拒绝）；新路径 L1
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
            if args.get("overwrite") is True:
                return Permission.L2_HIGH_RISK
            return Permission.L1_LOW_WRITE
        if name in ("fs.create_file", "fs.append_text", "fs.create_dir", "fs.open_path",
                    "doc.create", "doc.append", "doc.edit",
                    "docx.create", "pptx.create", "xlsx.create"):
            return Permission.L1_LOW_WRITE
        return getattr(tool, "permission", Permission.L0_READ)
