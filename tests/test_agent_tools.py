"""Agent 工具测试（M7）。"""
from __future__ import annotations

from unittest import mock

from furina.agent import ToolRegistry, PermissionManager, AgentRuntime
from furina.agent.tools import ALL_TOOLS, LaunchTool, OrganizeTool, ListDirTool, MakeDirsTool
from furina.agent.tools.apps import _APPS
from furina.core import EventBus, EventType


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
    # Phase 13 终审 §10.4：Popen 成功 + 可观察进程验证都满足 → verified
    with mock.patch("furina.agent.tools.apps.subprocess.Popen") as m, \
         mock.patch("furina.agent.tools.apps._observe_process", return_value=True):
        res = t.run(name="记事本")
        assert res.ok and res.verified
        m.assert_called_once()


def test_launch_requires_observable_verification():
    """Popen 成功但观察不到进程 → verified=False（绝不假装启动成功）。"""
    t = LaunchTool()
    with mock.patch("furina.agent.tools.apps.subprocess.Popen") as m, \
         mock.patch("furina.agent.tools.apps._observe_process", return_value=False):
        res = t.run(name="记事本")
        assert res.ok and not res.verified, "Popen 成功 ≠ 启动成功（必须可观察验证）"


def test_calculator_maps_to_calc():
    from furina.agent.planner import _guess_app
    assert _guess_app("打开计算器") == "calc"
    assert _guess_app("打开 calculator") == "calc"
    assert _guess_app("用 calc") == "calc"


def test_unknown_open_request_does_not_default_notepad():
    from furina.agent.planner import _guess_app
    from furina.agent import Planner, ToolRegistry
    assert _guess_app("打开一个奇怪软件") is None, "未知应用必须返回 None（绝不默认 notepad）"
    p = Planner(ToolRegistry())
    plan = p.build_plan("打开一个奇怪软件", {})
    assert plan.status == "unable", "未知应用计划必须失败/澄清"
    assert "notepad" not in str(plan.steps)


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
    # §10.4：启动必须可观察验证（mock Popen 成功 + mock 进程观察成功 → completed）
    with mock.patch("furina.agent.tools.apps.subprocess.Popen") as m, \
         mock.patch("furina.agent.tools.apps._observe_process", return_value=True):
        res = agent.execute("打开记事本", {})
    assert res["status"] == "completed", res
    assert res.get("summary") and "已验证" in res["summary"], "summary 必须含已验证事实"


def test_unverified_step_cannot_complete():
    """verified=False 的步骤不得 AGENT_COMPLETED（§10.3）。"""
    from furina.agent.tools.filesystem import ListDirTool
    from furina.agent.tool import ToolResult
    bus = EventBus()
    events = []
    bus.on(EventType.AGENT_COMPLETED, lambda ev: events.append(ev))
    bus.on(EventType.AGENT_FAILED, lambda ev: events.append(ev))
    tools = ToolRegistry()
    tools.register(ListDirTool())
    perm = PermissionManager()
    agent = AgentRuntime(bus, tools, perm)
    # list_dir 返回空 data → _verify=False → 不得 completed
    with mock.patch.object(ListDirTool, "run", return_value=ToolResult(True, data=None, verified=False)):
        res = agent.execute("整理下载文件夹", {"path": "/tmp/xxx"})
    assert res["status"] != "completed", res
    assert not any(getattr(e, "type", None) == EventType.AGENT_COMPLETED for e in events), \
        "unverified 步骤不得发 AGENT_COMPLETED"


def test_agent_context_is_task_local():
    """任务 A 的 path/vars 不得泄漏进任务 B（§10.2）。"""
    bus = EventBus()
    tools = _registry()
    perm = PermissionManager()
    agent = AgentRuntime(bus, tools, perm)
    agent.execute("打开记事本", {})     # 任务 A（无 path）
    # 任务 B 请求"整理"但没给 path → 必须失败（不能沿用任务 A/历史任何 path）
    res = agent.execute("整理下载文件夹", {})
    assert res["status"] == "failed", "缺 path 的整理任务必须失败（无历史泄漏）"


def test_app_launch_not_classified_read_only():
    from furina.agent.tools.apps import LaunchTool
    from furina.agent.permission import Permission
    assert LaunchTool.permission == Permission.L1_LOW_WRITE, "启动应用是副作用，不是只读"


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
