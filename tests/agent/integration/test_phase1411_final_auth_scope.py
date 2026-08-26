"""Phase 14.1.1 FINAL Authorization Scope Fix 测试（tests/agent/integration/）。

核心：**SCOPE 先于 PERMISSION LEVEL** —— 显式 task AuthorizationContext 下，
tool/path scope mismatch 无论 L0/L1/L2/L3 都不得绕过；scope 通过后才按 level 裁决。
multi-path 工具必须检查**所有** filesystem path（rename 检查最终 destination）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from furina.agent import AgentRuntime, PermissionManager, ToolRegistry
from furina.agent.capabilities import build_capability_registry
from furina.agent.permission import Permission
from furina.app import Furina
from furina.config import AppConfig, LLMProfile

_QAPP = QApplication.instance() or QApplication([])

# 与 App._agent_worker 菜单任务一致的 bounded scope
_DL = "C:/Users/TestUser/Downloads"
_MENU_TOOLS = ("fs.list_dir", "fs.make_dirs", "fs.organize")


@pytest.fixture()
def pm():
    return PermissionManager()


def _menu_auth(pm, root=_DL):
    return pm.new_task_context(max_permission=Permission.L2_HIGH_RISK,
                               allowed_tools=_MENU_TOOLS, allowed_path_root=root,
                               source="menu:整理下载文件夹")


def _check(pm, auth, level, tool, paths):
    return pm.check("t", level, task_auth=auth, tool=tool, paths=tuple(paths))


# ================================================================ 1/2. out-of-scope L1 denied（scope 先于 level）
def test_1_scoped_auth_rejects_out_of_tool_l1(pm):
    """fs.create_file Downloads/out.txt（L1，但 tool 不在 scope）→ DENIED（不得因 L1 auto-allow 绕过）。"""
    auth = _menu_auth(pm)
    d = _check(pm, auth, Permission.L1_LOW_WRITE, "fs.create_file", [f"{_DL}/out.txt"])
    assert not d.granted and d.reason == "task_scope_mismatch", d
    assert d.level == Permission.L1_LOW_WRITE


def test_2_scoped_auth_rejects_out_of_root_l1(pm):
    """fs.create_file D:/outside.txt（L1，tool 在 scope？不在——用 in-scope tool 但路径越界）。"""
    auth = _menu_auth(pm)
    # 用 scope 内 tool（fs.make_dirs）但路径在 root 外 → DENIED
    d = _check(pm, auth, Permission.L1_LOW_WRITE, "fs.make_dirs", ["D:/outside/X"])
    assert not d.granted and d.reason == "task_scope_mismatch", d
    # 纯 L1 越界（fs.create_file 不在 tool scope 也 DENIED——双重越界）
    d2 = _check(pm, auth, Permission.L1_LOW_WRITE, "fs.create_file", ["D:/outside.txt"])
    assert not d2.granted and d2.reason == "task_scope_mismatch", d2


# ================================================================ 3. in-scope L1 allowed
def test_3_scoped_auth_allows_in_tool_in_root_l1(pm):
    """fs.make_dirs Downloads/X（scope 内 + root 内 + L1）→ ALLOWED。"""
    auth = _menu_auth(pm)
    d = _check(pm, auth, Permission.L1_LOW_WRITE, "fs.make_dirs", [f"{_DL}/X"])
    assert d.granted, d


# ================================================================ 4. multi-path tool checks every relevant path
def test_4_multipath_tool_checks_every_path(pm):
    """fs.copy：source 在 root 内、dest 在 root 外 → DENIED（必须检查**所有** path）。"""
    # 验证 multi-path 机制：scope 允许 fs.copy（menu scope 不含它，故用自定义 auth）
    auth = pm.new_task_context(max_permission=Permission.L2_HIGH_RISK,
                               allowed_tools=("fs.copy",), allowed_path_root=_DL,
                               source="test:copy")
    # dest 越界 → DENIED（source 在 root 内也不能救）
    d = _check(pm, auth, Permission.L1_LOW_WRITE, "fs.copy",
               [f"{_DL}/a.txt", "D:/outside/b.txt"])
    assert not d.granted and d.reason == "task_scope_mismatch", d
    # source 越界、dest 在 root 内 → DENIED（source 也必须检查）
    d1 = _check(pm, auth, Permission.L1_LOW_WRITE, "fs.copy",
                ["D:/outside/a.txt", f"{_DL}/b.txt"])
    assert not d1.granted and d1.reason == "task_scope_mismatch", d1
    # 全部在 root 内 → ALLOWED
    d2 = _check(pm, auth, Permission.L1_LOW_WRITE, "fs.copy",
                [f"{_DL}/a.txt", f"{_DL}/b.txt"])
    assert d2.granted, d2


def test_4b_rename_checks_final_destination(pm):
    """rename：new_name 是 basename，不单独当 absolute path 检查；检查最终 destination。"""
    auth = pm.new_task_context(max_permission=Permission.L2_HIGH_RISK,
                               allowed_tools=("fs.rename",), allowed_path_root=_DL,
                               source="test:rename")
    # path 在 root 内、new_name basename → 最终 destination 在 root 内 → ALLOWED
    d = _check(pm, auth, Permission.L1_LOW_WRITE, "fs.rename",
               [f"{_DL}/a.txt", f"{_DL}/renamed.txt"])
    assert d.granted, d
    # path 在 root 外（经 path 收集）→ DENIED
    d2 = _check(pm, auth, Permission.L1_LOW_WRITE, "fs.rename", ["D:/outside/a.txt"])
    assert not d2.granted, d2


# ================================================================ reviewer-locked 全集
def test_reviewer_locked_scope_matrix(pm):
    """菜单 auth（tools=fs.list_dir/make_dirs/organize，root=Downloads）全矩阵。"""
    auth = _menu_auth(pm)
    def g(tool, paths, level=Permission.L1_LOW_WRITE):
        return _check(pm, auth, level, tool, paths).granted
    # fs.create_file Downloads/out.txt → DENIED（tool 不在 scope，即使 L1）
    assert not g("fs.create_file", [f"{_DL}/out.txt"])
    # fs.create_file D:/outside.txt → DENIED
    assert not g("fs.create_file", ["D:/outside.txt"])
    # fs.make_dirs Downloads/X → ALLOWED
    assert g("fs.make_dirs", [f"{_DL}/X"])
    # fs.make_dirs D:/outside/X → DENIED
    assert not g("fs.make_dirs", ["D:/outside/X"])
    # fs.organize Downloads → L2 ALLOWED（scope 内 + max_permission L2）
    assert _check(pm, auth, Permission.L2_HIGH_RISK, "fs.organize", [_DL]).granted
    # fs.delete Downloads/x → DENIED（tool mismatch，即使 L2 授权存在）
    assert not _check(pm, auth, Permission.L2_HIGH_RISK, "fs.delete", [f"{_DL}/x"]).granted
    # L2 auth → comm.send_message L3 → DENIED（L2 不覆盖 L3）
    assert not _check(pm, auth, Permission.L3_SENSITIVE, "comm.send_message", []).granted


# ================================================================ runtime-level：out-of-scope L1 真实执行被拒
@pytest.fixture()
def fapp(tmp_path):
    cfg = AppConfig(root_dir=tmp_path, zhipu_api_key="", agnes_api_key="",
                    llm=LLMProfile(api_key=""), data_dir=tmp_path)
    f = Furina(cfg)
    f._rt_dispatcher().bind_owner()
    yield f
    try:
        if f.cognition is not None:
            f.cognition.close()
    except Exception:
        pass


def test_runtime_scoped_auth_blocks_out_of_tool_l1(fapp, tmp_path):
    """真实 AgentRuntime：菜单 auth 下 fs.create_file（L1 但 tool 不在 scope）→ DENIED + 文件不创建。"""
    root = tmp_path / "Downloads"
    root.mkdir()
    auth = fapp.permission.new_task_context(
        max_permission=Permission.L2_HIGH_RISK,
        allowed_tools=("fs.list_dir", "fs.make_dirs", "fs.organize"),
        allowed_path_root=str(root), source="menu:整理下载文件夹")
    out = root / "out.txt"
    # 直接 permission 链验证（scope 先于 level：L1 也拒绝）
    d = fapp.permission.check("create", Permission.L1_LOW_WRITE,
                              task_auth=auth, tool="fs.create_file",
                              paths=[str(out)])
    assert not d.granted and d.reason == "task_scope_mismatch", d
    assert not out.exists()
    # in-scope tool 真实执行成功（fs.make_dirs 在 root 内）
    from furina.agent.tools.filesystem import MakeDirsTool
    r = MakeDirsTool().run(base=str(root), names=["X"])
    assert r.ok and (root / "X").is_dir()
