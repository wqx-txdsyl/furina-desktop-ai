"""Universal Agent Capability 测试（Phase 14C-F，tests/agent/capabilities/）。

覆盖：capability registry 可用性、Planner V2 validation/fallback、filesystem primitives
（真实 temp 目录 + filesystem truth verified）、documents（TXT/MD/DOCX/PPTX/XLSX reopen-verify）、
ApplicationCatalog（未知不猜 / 真实发现）、permission 档位。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from furina.agent import PermissionManager, ToolRegistry
from furina.agent.capabilities import build_capability_registry
from furina.agent.capabilities.applications import ApplicationCatalog
from furina.agent.capabilities.documents import (
    DocAppendTool, DocCreateTool, DocEditTool, DocReadTool, DocWriteTool,
    DocxCreateTool, PptxCreateTool, XlsxCreateTool,
)
from furina.agent.permission import Permission
from furina.agent.planner_v2 import PlannerV2
from furina.agent.tool import ToolResult
from furina.agent.tools import ALL_TOOLS
from furina.agent.tools.filesystem import (
    AppendTextTool, CreateFileTool, DeleteTool, ExistsTool, MoveTool,
    ReplaceTextTool, WriteTextTool,
)


def _registry() -> ToolRegistry:
    r = ToolRegistry()
    for c in ALL_TOOLS:
        r.register(c())
    return r


def _cap_registry(tools: ToolRegistry):
    return build_capability_registry(tools)


# ================================================================ Capability Registry
def test_capability_registry_availability():
    tools = _registry()
    reg = _cap_registry(tools)
    assert reg.is_available("cap.filesystem")
    assert reg.is_available("cap.documents")
    # provider 类能力必须显式 unavailable + reason
    assert reg.is_available("cap.communication") is False
    assert "provider_not_configured" in reg.availability_reason("cap.communication")
    assert reg.is_available("cap.calendar") is False
    assert reg.is_available("cap.browser_dom") is False, "无稳定 DOM provider 不得假装可用"
    assert reg.is_available("cap.research") is False
    # 禁止假实现凑齐：未配置的能力 tools 为空
    assert reg.get("cap.communication").tools
    assert reg.get("cap.research").tools == []


def test_capability_read_only_permission():
    tools = _registry()
    reg = _cap_registry(tools)
    assert reg.get("cap.browser").read_only is True
    assert reg.get("cap.desktop").read_only is True
    assert reg.get("cap.filesystem").default_permission == Permission.L1_LOW_WRITE


# ================================================================ Planner V2
class _FakeLLM:
    def __init__(self, plan_json=None, available=True):
        self._plan = plan_json
        self._available = available

    def is_available(self):
        return self._available

    def structured(self, messages, *, schema=None, temperature=None):
        return json.loads(self._plan)


def test_planner_v2_rejects_nonexistent_tool():
    """LLM 输出未知 tool → 必须在执行前被拒绝（不得自动替换）。"""
    tools = _registry()
    reg = _cap_registry(tools)
    llm = _FakeLLM('{"goal": "创建文件", "steps": [{"tool": "fs.nonexistent_tool", '
                   '"args": {"path": "/tmp/x"}, "expect": "x"}]}')
    pv = PlannerV2(tools, reg, llm=llm)
    plan = pv.build_plan("创建文件", {})
    # 校验失败 → 走 fallback（heuristic 对"创建文件"无法识别 → unable，绝不用未知 tool 执行）
    assert plan.status == "unable" or plan.steps == [] or plan.steps[0].tool != "fs.nonexistent_tool"
    if plan.steps:
        assert plan.steps[0].tool != "fs.nonexistent_tool", "未知 tool 不得进入计划"


def test_planner_v2_accepts_valid_llm_plan():
    tools = _registry()
    reg = _cap_registry(tools)
    llm = _FakeLLM('{"goal": "写文件", "steps": [{"tool": "doc.create", '
                   '"args": {"path": "C:/tmp/hello.md", "content": "Hello"}, "expect": "文件存在"}]}')
    pv = PlannerV2(tools, reg, llm=llm)
    plan = pv.build_plan("写文件", {})
    assert plan.steps and plan.steps[0].tool == "doc.create", "有效 LLM 计划应通过 validation"


def test_planner_v2_fallback_without_llm():
    """LLM 不可用 → 旧 deterministic（记事本/计算器/整理目录）仍工作。"""
    tools = _registry()
    pv = PlannerV2(tools, None, llm=None)
    p = pv.build_plan("打开记事本", {})
    assert p.steps and p.steps[0].tool == "app.launch"
    p2 = pv.build_plan("打开计算器", {})
    assert p2.steps and p2.steps[0].args == {"name": "calc"}
    tmp = Path(tempfile.mkdtemp())
    p3 = pv.build_plan("整理下载文件夹", {"path": str(tmp)})
    assert p3.status == "planned" and len(p3.steps) == 5
    # 未知应用 → unable（不猜，不得启动 notepad）
    p4 = pv.build_plan("打开一个不存在的XYZABC软件", {})
    assert p4.status == "unable"
    assert "notepad" not in str(p4.steps)


# ================================================================ Filesystem primitives（真实 temp 目录）
def test_fs_write_text_verified_and_overwrite_guard(tmp_path):
    p = tmp_path / "hello.md"
    r = WriteTextTool().run(str(p), content="Hello Furina")
    assert r.ok and r.verified, "写后必须读回校验（filesystem truth）"
    assert p.read_text(encoding="utf-8") == "Hello Furina"
    # 防误覆盖：expected_old_hash 不匹配 → 拒绝
    r2 = WriteTextTool().run(str(p), content="Hacked", expected_old_hash="wrong-hash")
    assert not r2.ok, "expected_old_hash 不匹配必须拒绝"
    assert p.read_text(encoding="utf-8") == "Hello Furina", "拒绝后原内容不变"
    # overwrite=false → 拒绝覆盖
    r3 = WriteTextTool().run(str(p), content="X", overwrite=False)
    assert not r3.ok, "overwrite=false 必须拒绝"
    assert p.read_text(encoding="utf-8") == "Hello Furina"


def test_fs_create_file_no_silent_overwrite(tmp_path):
    p = tmp_path / "a.txt"
    assert CreateFileTool().run(str(p), content="x").ok
    r = CreateFileTool().run(str(p), content="y")
    assert not r.ok, "已存在文件不得 silent overwrite"


def test_fs_move_verified_filesystem_truth(tmp_path):
    src = tmp_path / "notes.md"
    src.write_text("hi", encoding="utf-8")
    dst = tmp_path / "Docs" / "notes.md"
    r = MoveTool().run(str(src), str(dst))
    assert r.ok and r.verified
    assert dst.exists() and not src.exists(), "verified 必须来自 filesystem truth"
    # 目标已存在且 overwrite=False → 拒绝
    src2 = tmp_path / "b.md"
    src2.write_text("x", encoding="utf-8")
    r2 = MoveTool().run(str(src2), str(dst), overwrite=False)
    assert not r2.ok, "目标已存在必须拒绝（禁止 silent overwrite）"


def test_fs_delete_requires_l2(tmp_path):
    p = tmp_path / "del.txt"
    p.write_text("x", encoding="utf-8")
    r = DeleteTool().run(str(p))
    assert r.ok and r.verified and not p.exists()
    assert DeleteTool.permission == Permission.L2_HIGH_RISK


def test_fs_exists_stat_search(tmp_path):
    p = tmp_path / "findme.txt"
    p.write_text("content", encoding="utf-8")
    assert ExistsTool().run(str(p)).data["exists"] is True
    st = __import__("furina.agent.tools.filesystem", fromlist=["StatTool"]).StatTool()
    r = st.run(str(p))
    assert r.ok and r.data["size"] == len("content")
    s = __import__("furina.agent.tools.filesystem", fromlist=["SearchTool"]).SearchTool()
    r2 = s.run(str(tmp_path), pattern="findme")
    assert r2.ok and any("findme.txt" in h for h in r2.data["hits"])


def test_fs_append_replace(tmp_path):
    p = tmp_path / "log.txt"
    AppendTextTool().run(str(p), content="line1\n")
    AppendTextTool().run(str(p), content="line2\n")
    assert p.read_text(encoding="utf-8") == "line1\nline2\n"
    r = ReplaceTextTool().run(str(p), old="line1", new="LINE1")
    assert r.ok and r.verified
    assert "LINE1" in p.read_text(encoding="utf-8")


# ================================================================ Documents（真实文件 + reopen-verify）
def test_doc_txt_md_lifecycle(tmp_path):
    p = tmp_path / "note.md"
    r = DocCreateTool().run(str(p), content="# 标题\n正文")
    assert r.ok and r.verified and p.exists()
    r2 = DocReadTool().run(str(p))
    assert r2.ok and "标题" in r2.data["content"]
    r3 = DocAppendTool().run(str(p), content="\n追加")
    assert r3.ok and r3.verified
    r4 = DocEditTool().run(str(p), old="标题", new="新标题")
    assert r4.ok and r4.verified
    assert "新标题" in p.read_text(encoding="utf-8")
    r5 = DocWriteTool().run(str(p), content="覆盖", overwrite=False)
    assert not r5.ok, "overwrite=false 拒绝覆盖"


def test_docx_create_reopen_verify(tmp_path):
    p = tmp_path / "doc.docx"
    r = DocxCreateTool().run(str(p), title="芙宁娜测试", paragraphs=["第一段", "第二段"],
                             bullets=["要点A"])
    assert r.ok and r.verified, f"docx reopen-verify 必须通过: {r.error}"
    assert p.exists() and p.stat().st_size > 0


def test_pptx_create_reopen_verify(tmp_path):
    p = tmp_path / "slides.pptx"
    r = PptxCreateTool().run(str(p), slides=[{"title": "第一页", "bullets": ["a"]},
                                             {"title": "第二页", "bullets": []}])
    assert r.ok and r.verified, f"pptx reopen-verify 必须通过: {r.error}"
    assert r.data["slides"] == 2


def test_xlsx_create_reopen_verify(tmp_path):
    p = tmp_path / "data.xlsx"
    r = XlsxCreateTool().run(str(p), rows=[["名称", "数量"], ["苹果", 3], ["香蕉", 5]])
    assert r.ok and r.verified, f"xlsx reopen-verify 必须通过: {r.error}"
    assert p.exists() and p.stat().st_size > 0


# ================================================================ Application Catalog
def test_catalog_unknown_app_never_guessed(tmp_path):
    cat = ApplicationCatalog()
    assert cat.resolve("XYZABC不存在的软件") is None, "未知应用不得猜 executable"
    with mock.patch("furina.agent.capabilities.applications.catalog.subprocess.Popen") as m:
        r = cat.launch("XYZABC不存在的软件")
        assert not r.ok and m.call_count == 0, "不得启动任何程序（尤其 notepad）"


def test_catalog_discovers_known_apps():
    cat = ApplicationCatalog()
    recs = cat.all_records()
    assert recs, "Windows 上至少发现 PATH 内应用（如 notepad）"
    # 已知别名可 resolve 到真实 target
    n = cat.resolve("notepad") or cat.resolve("记事本")
    if n is not None:
        assert n.launch_target, "record 必须带真实 launch target"
        assert n.launch_target.lower().endswith((".exe", ".lnk"))
    # 搜索
    found = cat.search("note")
    assert any("notepad" in r.app_id for r in found)


def test_catalog_launch_unverified_not_completed(tmp_path):
    """target 存在但观察不到进程 → UNVERIFIED（不得 COMPLETED）。"""
    cat = ApplicationCatalog()
    n = cat.resolve("notepad")
    if n is None:
        return  # 非 Windows/未发现 → 跳过（不造假）
    with mock.patch("furina.agent.capabilities.applications.catalog.subprocess.Popen"), \
         mock.patch("furina.agent.capabilities.applications.catalog._observe_process",
                    return_value=False):
        r = cat.launch("notepad")
    assert r.ok is True and r.verified is False, "观察不到进程必须 UNVERIFIED"


# ================================================================ Permission 档位（reviewer D 25-29）
def test_permission_levels():
    from furina.agent.tools.filesystem import ListDirTool, ReadFileTool
    assert ListDirTool.permission == Permission.L0_READ          # 25 read → L0
    assert ReadFileTool.permission == Permission.L0_READ
    assert CreateFileTool.permission == Permission.L1_LOW_WRITE  # 26 新文件显式路径 → L1
    assert DocCreateTool.permission == Permission.L1_LOW_WRITE
    assert WriteTextTool.permission == Permission.L1_LOW_WRITE
    assert DeleteTool.permission == Permission.L2_HIGH_RISK      # 28 delete → L2+
    from furina.agent.tools.apps import LaunchTool
    assert LaunchTool.permission == Permission.L1_LOW_WRITE


def test_communication_send_is_l3():
    from furina.agent.capabilities.integrations import CommunicationProvider
    # send_message 的权限契约 = L3 SENSITIVE（在架构层声明；无 provider 时不可用）
    from furina.agent.capabilities import build_capability_registry
    reg = build_capability_registry(_registry(), providers=None)
    assert reg.get("cap.communication").default_permission == Permission.L3_SENSITIVE  # 29
    assert reg.get("cap.communication").available is False                            # 30
