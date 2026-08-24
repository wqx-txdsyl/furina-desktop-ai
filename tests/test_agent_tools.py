"""Agent 工具测试（M7）。"""
from __future__ import annotations

from unittest import mock

from furina.agent import ToolRegistry, PermissionManager, AgentRuntime
from furina.agent.tools import ALL_TOOLS, LaunchTool, OrganizeTool, ListDirTool, MakeDirsTool
from furina.agent.tools.apps import _APPS
from furina.core import EventBus


def _registry() -> ToolRegistry:
    r = ToolRegistry()
    for t in ALL_TOOLS:
        r.register(t())
    return r


def test_launch_maps_known_apps():
    # 直接看映射表
    assert _APPS["notepad"] == "notepad"
    assert _APPS["vscode"] == "code"


def test_launch_tool_unknown():
    t = LaunchTool()
    with mock.patch("furina.agent.tools.apps.subprocess.Popen") as m:
        res = t.run(name="definitely_not_an_app_xyz")
        assert not res.ok                     # 未知应用 → 诚实失败
        m.assert_not_called()


def test_launch_tool_success():
    t = LaunchTool()
    with mock.patch("furina.agent.tools.apps.subprocess.Popen") as m:
        res = t.run(name="记事本")
        assert res.ok and res.verified
        m.assert_called_once()


def test_agent_plan_open_notepad():
    bus = EventBus()
    tools = _registry()
    perm = PermissionManager()
    agent = AgentRuntime(bus, tools, perm)
    plan = agent.planner.build_plan("打开记事本", {})
    assert plan.steps[0].tool == "app.launch"
    assert plan.steps[0].args == {"name": "notepad"}


def test_agent_execute_launch():
    bus = EventBus()
    tools = _registry()
    perm = PermissionManager()
    agent = AgentRuntime(bus, tools, perm)
    with mock.patch("furina.agent.tools.apps.subprocess.Popen") as m:
        res = agent.execute("打开记事本", {})
    assert res["status"] == "completed", res


def test_browser_open_and_search():
    from furina.agent.tools.browser import OpenUrlTool, SearchTool
    with mock.patch("furina.agent.tools.browser.webbrowser.open") as m:
        assert OpenUrlTool().run("example.com").ok
        m.assert_called_once()
    with mock.patch("furina.agent.tools.browser.webbrowser.open") as m:
        r = SearchTool().run("芙宁娜 桌宠")
        assert r.ok and "q=" in r.data["opened"]


def test_agent_no_fake_success_on_failure():
    """Agent 失败必须如实返回 failed（不假装成功，final test.md A-14/15）。"""
    from furina.agent.tools.filesystem import ListDirTool
    bus = EventBus()
    tools = ToolRegistry()
    tools.register(ListDirTool())
    perm = PermissionManager()
    perm.on_confirm = lambda d, l: True
    agent = AgentRuntime(bus, tools, perm)
    # 传入一个不存在目录的“整理”计划 → fs.list_dir 失败 → 如实 failed
    res = agent.execute("整理下载文件夹", {"path": "/no/such/dir/xyz"})
    assert res["status"] == "failed", res
    assert res["reason"] != ""   # 有真实原因，不是 “完成”


def test_agent_permission_denied_is_failed(tmp_path):
    """高权限操作无确认处理时被拒，且如实失败。"""
    bus = EventBus()
    tools = ToolRegistry()
    for t in (ListDirTool, MakeDirsTool, OrganizeTool):
        tools.register(t())
    perm = PermissionManager()     # 未提供 on_confirm → L2 拒绝
    agent = AgentRuntime(bus, tools, perm)
    res = agent.execute("整理下载文件夹", {"path": str(tmp_path)})
    assert res["status"] == "failed"
    assert res["reason"] == "permission_denied"
