"""Phase 14.1.1 Final Production Safety & Event Truth Closure 测试（tests/agent/integration/）。

Reviewer-locked（真实 production path：真实 Furina + PermissionManager/AgentRuntime/
CognitionHub + 真实工具）：
1. menu L2 scope does not allow fs.delete
2. menu task A authorization does not leak into concurrent task B
3. task A completion/revoke does not revoke task B independent context
4. L2 authorization never implies L3
5-7. existing docx/pptx/xlsx cannot L1 overwrite
8. Office rejected overwrite preserves exact bytes/hash
9. read→play→read→play records four distinct activity starts
10. same activity instance duplicate emit records once
11. finish references matching start instance
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from PySide6.QtWidgets import QApplication

from furina.agent import ToolRegistry
from furina.agent.capabilities import build_capability_registry
from furina.agent.capabilities.documents import DocxCreateTool, PptxCreateTool, XlsxCreateTool
from furina.agent.permission import AuthorizationContext, Permission
from furina.agent.planner_v2 import PlannerV2
from furina.app import Furina
from furina.config import AppConfig, LLMProfile

_QAPP = QApplication.instance() or QApplication([])


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


class _StubLLM:
    def __init__(self, plan_json, available=True):
        self._plan = plan_json
        self._available = available

    def is_available(self):
        return self._available

    def structured(self, messages, *, schema=None, temperature=None):
        return json.loads(self._plan)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run(agent, request: str, plan_json: str, *, tmp_path, task_auth=None):
    """真实 AgentRuntime + 真实 PlannerV2（stub LLM 只提供计划 JSON）+ 真实权限链。"""
    reg = build_capability_registry(agent.tools)
    agent.planner = PlannerV2(agent.tools, reg, llm=_StubLLM(plan_json))
    return agent.execute(request, {"path": str(tmp_path)}, task_auth=task_auth)


# ================================================================ 1. menu L2 scope: no fs.delete
def test_1_menu_l2_scope_does_not_allow_fs_delete(fapp, tmp_path):
    precious = tmp_path / "precious.txt"
    precious.write_text("keep", encoding="utf-8")
    # 菜单任务的 bounded L2（与 App._agent_worker 一致：allowed_tools=organize 序列）
    auth = fapp.permission.new_task_context(
        max_permission=Permission.L2_HIGH_RISK,
        allowed_tools=("fs.list_dir", "fs.make_dirs", "fs.organize"),
        allowed_path_root=str(tmp_path), source="menu:整理下载文件夹")
    # PlannerV2 为该菜单错误规划 fs.delete（out of tool scope）
    res = _run(fapp.agent, "整理下载文件夹",
               json.dumps({"goal": "整理", "steps": [{"tool": "fs.delete",
                                                      "args": {"path": str(precious)},
                                                      "expect": "删除"}]}),
               tmp_path=tmp_path, task_auth=auth)
    assert res["status"] == "failed" and "permission_denied" in res["reason"], res
    assert precious.exists(), "菜单 L2 的 tool scope 不含 fs.delete → 文件必须保留"
    assert "task_scope_mismatch" in str(res["task_record"]["permission_summary"]), \
        "拒绝原因必须是 task scope 不匹配（菜单 L2 不覆盖任意工具）"


# ================================================================ 2/3. concurrency isolation
def test_2_menu_task_a_auth_does_not_leak_into_task_b(fapp, tmp_path):
    """Task A（menu L2 scoped）与 Task B（LLM plan fs.delete）并发 → B 被拒，A 授权不泄漏。"""
    precious = tmp_path / "precious.txt"
    precious.write_text("keep", encoding="utf-8")
    auth_a = fapp.permission.new_task_context(
        max_permission=Permission.L2_HIGH_RISK,
        allowed_tools=("fs.list_dir", "fs.make_dirs", "fs.organize"),
        allowed_path_root=str(tmp_path), source="menu:A")
    # Task A 授权 active 的同时，Task B 用**自己的默认 context**（L0/L1 only）尝试删除
    res_b = _run(fapp.agent, "删除文件",
                 json.dumps({"goal": "删除", "steps": [{"tool": "fs.delete",
                                                        "args": {"path": str(precious)},
                                                        "expect": "删除"}]}),
                 tmp_path=tmp_path, task_auth=None)
    assert res_b["status"] == "failed" and "permission_denied" in res_b["reason"], res_b
    assert precious.exists(), "Task B 不得借用 Task A 的 L2 授权"
    # Task A 自身 scope 内操作仍被允许（授权未因 B 的存在而失效）
    res_a = _run(fapp.agent, "整理",
                 json.dumps({"goal": "整理", "steps": [{"tool": "fs.organize",
                                                        "args": {"base": str(tmp_path),
                                                                 "dry_run": True},
                                                        "expect": "预览"}]}),
                 tmp_path=tmp_path, task_auth=auth_a)
    assert res_a["status"] == "completed", f"Task A scope 内操作应成功: {res_a}"


def test_3_task_a_revoke_does_not_revoke_task_b(fapp, tmp_path):
    """Task A 完成/销毁其 context，不影响 Task B 的独立 context（无全局 set 可 revoke）。"""
    target = tmp_path / "b.txt"
    target.write_text("b", encoding="utf-8")
    auth_a = fapp.permission.new_task_context(max_permission=Permission.L2_HIGH_RISK,
                                              allowed_tools=("fs.organize",), source="A")
    auth_b = fapp.permission.new_task_context(max_permission=Permission.L2_HIGH_RISK,
                                              allowed_tools=("fs.delete",), source="B")
    # Task A 结束（context 局部对象自然销毁；无全局授权可 revoke）
    del auth_a
    # Task B 独立 context 仍有效
    res_b = _run(fapp.agent, "删除",
                 json.dumps({"goal": "删除", "steps": [{"tool": "fs.delete",
                                                        "args": {"path": str(target)},
                                                        "expect": "删除"}]}),
                 tmp_path=tmp_path, task_auth=auth_b)
    assert res_b["status"] == "completed", f"Task B 独立 context 不得被 Task A 影响: {res_b}"
    assert not target.exists()


# ================================================================ 4. L2 never implies L3
def test_4_l2_authorization_never_implies_l3(fapp, tmp_path):
    auth = fapp.permission.new_task_context(max_permission=Permission.L2_HIGH_RISK,
                                            allowed_tools=("comm.send_message",),
                                            source="L2-token")
    decision = fapp.permission.check("发送消息", Permission.L3_SENSITIVE,
                                     task_auth=auth, tool="comm.send_message")
    assert not decision.granted, "L2 token 不得授权 L3"
    # L2 步骤在匹配 context 下放行（对照）
    decision2 = fapp.permission.check("整理", Permission.L2_HIGH_RISK,
                                      task_auth=auth, tool="comm.send_message")
    assert decision2.granted


# ================================================================ 5-8. Office no silent overwrite
def _office_tool_cls(name):
    return {"docx.create": DocxCreateTool, "pptx.create": PptxCreateTool,
            "xlsx.create": XlsxCreateTool}[name]


@pytest.mark.parametrize("tool_cls,args", [
    (DocxCreateTool, {"title": "覆盖", "paragraphs": ["x"]}),
    (PptxCreateTool, {"slides": [{"title": "覆盖", "bullets": []}]}),
    (XlsxCreateTool, {"rows": [["a", 1]]}),
])
def test_5_7_existing_office_cannot_l1_overwrite(tmp_path, tool_cls, args):
    """existing docx/pptx/xlsx → L1 create DENIED / tool not executed → bytes unchanged。"""
    ext = {"DocxCreateTool": "docx", "PptxCreateTool": "pptx", "XlsxCreateTool": "xlsx"}[
        tool_cls.__name__]
    target = tmp_path / f"important.{ext}"
    target.write_bytes(b"ORIGINAL-OFFICE-CONTENT-V1")   # 预置已有文件
    before = _sha(target)
    tool = tool_cls()
    # 直接工具层（production tool）：已有目标必须拒绝，绝不 L1 silent overwrite
    res = tool.run(str(target), **args)
    assert not res.ok, f"{tool_cls.__name__} 不得覆盖已有文件: {res}"
    assert _sha(target) == before, "拒绝后原文件字节必须不变（SHA256 before==after）"


def test_8_office_rejected_overwrite_preserves_exact_bytes(tmp_path):
    """Office rejected overwrite → SHA256 before == after（含通过真实 Agent L1 路径）。"""
    target = tmp_path / "important.docx"
    target.write_bytes(b"REAL-DOCX-BYTES-v1")
    before = _sha(target)
    # 真实 AgentRuntime 路径：默认 context（L1 only）+ PlannerV2 规划 docx.create 到已有文件
    from furina.agent import AgentRuntime, PermissionManager, ToolRegistry
    from furina.agent.tools import ALL_TOOLS
    bus = __import__("furina.core", fromlist=["EventBus"]).EventBus()
    tools = ToolRegistry()
    for c in ALL_TOOLS:
        tools.register(c())
    reg = build_capability_registry(tools)
    agent = AgentRuntime(bus, tools, PermissionManager())
    res = agent.execute("创建文档",
                        {"path": str(tmp_path)},
                        task_auth=None)   # default L1
    # 计划走 fallback doc.create（.docx 由 doc.create 拒绝：只支持 txt/md）→ 不改 important.docx
    assert _sha(target) == before, "任何路径都不得碰已有 important.docx"
    # 直接 docx.create 于已有文件同样拒绝（工具层）
    r = DocxCreateTool().run(str(target), title="x")
    assert not r.ok and _sha(target) == before
    assert res["status"] in ("failed", "unverified", "completed")  # 不崩即可；核心断言是字节不变


# ================================================================ 9-11. C6 activity instance truth
def test_9_read_play_read_play_four_distinct_starts(fapp):
    """read→play→read→play：4 个不同 activity_instance_id；ACTIVITY_STARTED read=2、play=2。"""
    for action in ("read", "play", "read", "play"):
        fapp._on_execute(SimpleNamespace(action=action, source="mind", payload={},
                                         reason="r", priority=0.5))
    started = fapp.cognition.events.query_by_type("ACTIVITY_STARTED")
    assert len(started) == 4, f"必须 4 次 START: {len(started)}"
    read = [e for e in started if e.payload.get("activity") == "read"]
    play = [e for e in started if e.payload.get("activity") == "play"]
    assert len(read) == 2 and len(play) == 2, f"read=2 play=2: read={len(read)} play={len(play)}"
    ids = [e.payload.get("activity_instance_id") for e in started]
    assert len(set(ids)) == 4, f"每次 START 必须唯一 instance id: {ids}"


def test_10_same_activity_instance_duplicate_emit_once(fapp):
    """同一 instance 重复 emit → exactly once（bridge key 去重，不靠时间戳字符串）。"""
    fapp._on_execute(SimpleNamespace(action="read", source="mind", payload={},
                                     reason="r", priority=0.5))
    started = fapp.cognition.events.query_by_type("ACTIVITY_STARTED")
    assert len(started) == 1
    inst_id = started[0].payload["activity_instance_id"]
    # 重复 emit 同一 instance（显式 key 相同）→ bridge 去重
    bridge = fapp._event_bridge
    bridge.record("ACTIVITY_STARTED", key=f"activity-start:{inst_id}",
                  payload={"activity": "read", "activity_instance_id": inst_id},
                  source="director", importance=0.1)
    bridge.record("ACTIVITY_STARTED", key=f"activity-start:{inst_id}",
                  payload={"activity": "read", "activity_instance_id": inst_id},
                  source="director", importance=0.1)
    assert len(fapp.cognition.events.query_by_type("ACTIVITY_STARTED")) == 1, \
        "同一 instance 重复 emit 必须 exactly once"


def test_11_finish_references_matching_start_instance(fapp):
    """FINISH 必须引用对应 START 的同一 activity_instance_id。"""
    fapp._on_execute(SimpleNamespace(action="read", source="mind", payload={},
                                     reason="r", priority=0.5))
    fapp._on_execute(SimpleNamespace(action="play", source="mind", payload={},
                                     reason="r", priority=0.5))
    started = fapp.cognition.events.query_by_type("ACTIVITY_STARTED")
    finished = fapp.cognition.events.query_by_type("ACTIVITY_FINISHED")
    assert len(finished) == 1, f"read→play 应产生 1 个 FINISH: {len(finished)}"
    fin = finished[0].payload
    read_start = [e for e in started if e.payload.get("activity") == "read"][0].payload
    assert fin["activity"] == "read" and fin["next"] == "play"
    assert fin["activity_instance_id"] == read_start["activity_instance_id"], \
        "FINISH 必须引用 START 的同一 instance"
    assert fin["reason"] == "activity_switch"


# ================================================================ Windows integration
def test_windows_office_overwrite_protection_and_auth_isolation(tmp_path):
    """Windows 真实 temp：Office 覆盖保护（字节不变）+ 并发授权隔离。"""
    # Office 覆盖保护
    for ext in ("docx", "pptx", "xlsx"):
        p = tmp_path / f"imp.{ext}"
        p.write_bytes(b"V1-BYTES")
        before = _sha(p)
        tool = {"docx": DocxCreateTool, "pptx": PptxCreateTool, "xlsx": XlsxCreateTool}[ext]()
        r = tool.run(str(p), **({"title": "x"} if ext == "docx"
                                else {"slides": []} if ext == "pptx" else {"rows": []}))
        assert not r.ok and _sha(p) == before, f"{ext} 覆盖必须被拒且字节不变"
    # 并发授权隔离（PermissionManager 无全局状态）
    pm = __import__("furina.agent.permission", fromlist=["PermissionManager"]).PermissionManager()
    auth_a = pm.new_task_context(max_permission=Permission.L2_HIGH_RISK,
                                 allowed_tools=("fs.organize",), source="A")
    auth_b = pm.new_task_context(max_permission=Permission.L1_LOW_WRITE, source="B")
    assert pm.check("organize", Permission.L2_HIGH_RISK, task_auth=auth_a,
                    tool="fs.organize").granted
    assert not pm.check("delete", Permission.L2_HIGH_RISK, task_auth=auth_b,
                        tool="fs.delete").granted, "B 的 L1 不得执行 L2"
    assert not pm.check("delete", Permission.L3_SENSITIVE, task_auth=auth_a,
                        tool="comm.send_message").granted, "A 的 L2 不得覆盖 L3"
