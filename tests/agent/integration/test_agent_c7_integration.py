"""Agent × Cognition 集成测试（Phase 14I/J/K，tests/agent/integration/）。

覆盖 reviewer-locked：
- 13/14 创建 hello.md + 改内容 → 真实文件 exists + C7 artifact
- 15 未知 app → unable（不启动 notepad）
- 17 ok=True verified=False → task != COMPLETED（C7 持久化为 UNVERIFIED）
- 18 LLM planner 输出未知 tool → 执行前拒绝
- 19 planner 不可用 → deterministic fallback 仍工作
- 23 move A→B → C7 精确查询报 B
- App owner 路径：worker task_record → dispatcher → owner persist C7
"""
from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from furina.agent import AgentRuntime, PermissionManager, ToolRegistry
from furina.agent.capabilities import build_capability_registry
from furina.agent.planner_v2 import PlannerV2
from furina.agent.planner import AgentPlan, AgentStep, Planner
from furina.agent.tool import ToolResult
from furina.agent.tools import ALL_TOOLS
from furina.core import EventBus, EventType
from furina.cognition import CognitionHub


def _registry() -> ToolRegistry:
    r = ToolRegistry()
    for c in ALL_TOOLS:
        r.register(c())
    return r


class _FixedPlanner(Planner):
    """固定计划（测试 13/14/23 用）：hello.md 创建 → 修改。"""

    def __init__(self, tools, steps):
        super().__init__(tools)
        self._steps = steps

    def build_plan(self, user_request, context=None):
        return AgentPlan(goal=user_request, steps=self._steps)


def _step(tool, args, expect=""):
    return AgentStep(tool=tool, args=args, expect=expect)


def _make_agent(steps=None, planner_cls=Planner, hub=None):
    bus = EventBus()
    tools = _registry()
    perm = PermissionManager()
    perm.on_confirm = lambda d, l: True
    records = []
    agent = AgentRuntime(bus, tools, perm, planner_factory=planner_cls,
                         task_history=lambda rec: records.append(rec))
    if steps is not None:
        agent.planner = _FixedPlanner(tools, steps)
    return bus, tools, agent, records


# ================================================================ 13/14/23：文件任务 → C7 精确查询
def test_agent_creates_file_and_c7_artifact(tmp_path):
    """创建 hello.md 写 Hello Furina → 真实文件 exists/内容 verified + C7 artifact。"""
    bus, tools, agent, records = _make_agent(steps=[
        _step("doc.create", {"path": str(tmp_path / "hello.md"), "content": "Hello Furina"}),
    ])
    res = agent.execute("创建 hello.md", {})
    assert res["status"] == "completed", res
    f = tmp_path / "hello.md"
    assert f.exists() and f.read_text(encoding="utf-8") == "Hello Furina", "真实文件存在且内容正确"
    # task_record 含 artifact（exists_verified 来自 filesystem truth）
    rec = records[-1]
    assert rec["status"] == "COMPLETED_VERIFIED" and rec["verified"] is True
    arts = rec["artifacts"]
    assert arts and arts[0]["path"] == str(f) and arts[0]["exists_verified"] is True
    assert res.get("task_id") and res["task_id"] == rec["task_id"], "stable task_id"


def test_agent_edits_file_verified_content(tmp_path):
    """把 hello.md 改成 Hello Fontaine → verified 内容。"""
    f = tmp_path / "hello.md"
    f.write_text("Hello Furina", encoding="utf-8")
    bus, tools, agent, records = _make_agent(steps=[
        _step("doc.edit", {"path": str(f), "old": "Furina", "new": "Fontaine"}),
    ])
    res = agent.execute("改成 Hello Fontaine", {})
    assert res["status"] == "completed", res
    assert f.read_text(encoding="utf-8") == "Hello Fontaine", "真实内容已改"


def test_agent_move_file_c7_exact_query(tmp_path):
    """move A → B → C7 精确查询报告 B（不依赖 Memory semantic guessing）。"""
    src = tmp_path / "notes.md"
    src.write_text("content", encoding="utf-8")
    dst_dir = tmp_path / "Docs"
    bus, tools, agent, records = _make_agent(steps=[
        _step("fs.move", {"source": str(src), "dest": str(dst_dir / "notes.md")}),
    ])
    res = agent.execute("把 notes.md 移到 Docs", {})
    assert res["status"] == "completed", res
    assert (dst_dir / "notes.md").exists() and not src.exists()
    # 真实持久化到 C7（temp DB）→ 精确查询
    hub = CognitionHub(tmp_path / "cog.db")
    tid = res["task_id"]
    hub.persist_agent_result(tid, status=res["task_record"]["status"], goal="把 notes.md 移到 Docs",
                             original_request="把 notes.md 移到 Docs",
                             verified=res["task_record"]["verified"],
                             result_summary=res["task_record"]["result_summary"],
                             steps=res["task_record"]["steps"],
                             artifacts=res["task_record"]["artifacts"])
    found = hub.agent_history.find_latest_by_artifact("notes.md")
    assert found and found[0].task_id == tid, "C7 精确查询必须命中"
    arts = hub.agent_history.artifacts(tid)
    assert arts and arts[0].path == str(dst_dir / "notes.md"), "exact destination = B"
    hub.close()


# ================================================================ 17：ok≠verified → 非 COMPLETED
def test_ok_true_verified_false_task_not_completed(tmp_path):
    class _BadTool:
        name = "fs.read_file"
        description = "read"
        permission = None
        schema = {}

        def run(self, **kw):
            return ToolResult(True, data=None, verified=False)

    bus = EventBus()
    tools = ToolRegistry()
    tools.register(_BadTool())
    perm = PermissionManager()
    agent = AgentRuntime(bus, tools, perm)
    res = agent.execute("整理下载文件夹", {"path": str(tmp_path)})
    assert res["status"] != "completed", "ok=True verified=False 不得 COMPLETED"
    assert res["status"] == "unverified" or res["status"] == "failed"
    assert res["task_record"]["status"] in ("UNVERIFIED", "FAILED")
    assert res["task_record"]["verified"] is False


# ================================================================ 18/19：Planner V2 边界
def test_llm_plan_nonexistent_tool_rejected_before_execution(tmp_path):
    """LLM 输出未知 tool → 执行前拒绝（不执行、不替换）。"""
    class _BadLLM:
        def is_available(self):
            return True

        def structured(self, messages, *, schema=None, temperature=None):
            return {"goal": "创建", "steps": [{"tool": "fs.nonexistent", "args": {"path": "x"}}]}

    bus = EventBus()
    tools = _registry()
    reg = build_capability_registry(tools)
    perm = PermissionManager()
    perm.on_confirm = lambda d, l: True
    executed = []

    class _SpyPlanner(PlannerV2):
        def _fallback_plan(self, user_request, context):
            # 记录 fallback 被走到（LLM 计划被拒）
            return super()._fallback_plan(user_request, context)

    pv = _SpyPlanner(tools, reg, llm=_BadLLM())
    agent = AgentRuntime(bus, tools, perm, planner_factory=lambda t: pv)
    res = agent.execute("创建文件", {})
    # 未知 tool 被拒 → 走 fallback；fallback 对"创建文件"无法映射 → unable/failed
    assert res["status"] in ("failed", "unverified")
    assert "fs.nonexistent" not in json.dumps(res.get("task_record", {}), default=str)
    assert res["task_record"]["status"] != "COMPLETED_VERIFIED"


def test_planner_unavailable_deterministic_fallback(tmp_path):
    """Planner 不可用（无 LLM）→ 记事本/计算器/整理目录仍工作（reviewer-locked 19）。"""
    bus = EventBus()
    tools = _registry()
    reg = build_capability_registry(tools)
    perm = PermissionManager()
    agent = AgentRuntime(bus, tools, perm, planner_factory=lambda t: PlannerV2(t, reg, llm=None))
    p = agent.planner.build_plan("打开记事本", {})
    assert p.steps and p.steps[0].tool == "app.launch"
    p2 = agent.planner.build_plan("打开计算器", {})
    assert p2.steps[0].args == {"name": "calc"}
    tmp = Path(tempfile.mkdtemp())
    p3 = agent.planner.build_plan("整理下载文件夹", {"path": str(tmp)})
    assert p3.status == "planned"


# ================================================================ 15：未知 app → unable（不启动 notepad）
def test_unknown_app_unable_no_notepad(tmp_path):
    bus = EventBus()
    tools = _registry()
    perm = PermissionManager()
    agent = AgentRuntime(bus, tools, perm)
    with mock.patch("furina.agent.tools.apps.subprocess.Popen") as m:
        res = agent.execute("打开一个不存在的XYZABC软件", {})
    assert res["status"] in ("failed", "unverified"), f"未知应用必须失败: {res}"
    assert m.call_count == 0, "不得启动任何程序（尤其 notepad）"


# ================================================================ App owner 路径：worker→dispatcher→owner persist
def test_app_owner_persists_agent_task(tmp_path):
    """worker 返回 task_record → dispatcher owner → _persist_agent_task 写 C7。"""
    from furina.app import Furina
    app = object.__new__(Furina)
    app.cognition = CognitionHub(tmp_path / "app.db")
    # owner dispatcher 模拟：直接执行（测试线程 = owner）
    calls = []
    app._rt_dispatcher = lambda: SimpleNamespace(submit=lambda fn: (calls.append(fn), fn())[1])
    app._persist_agent_task({
        "task_id": "task_abc", "status": "COMPLETED_VERIFIED", "goal": "创建文档",
        "original_request": "创建文档", "verified": True,
        "result_summary": "完成", "error": "",
        "steps": [{"step_index": 0, "tool": "doc.create", "args": {"path": "C:/x.md"},
                   "capability": "DOCUMENTS", "permission_level": "L1",
                   "status": "COMPLETED_VERIFIED", "verified": True,
                   "result": {"path": "C:/x.md"}, "error": ""}],
        "artifacts": [{"artifact_type": "file", "path": "C:/x.md",
                       "exists_verified": True, "metadata": {}}],
        "plan_json": "{}", "permission_summary": "",
    })
    t = app.cognition.agent_history.get_task("task_abc")
    assert t is not None and t.status == "COMPLETED_VERIFIED"
    assert len(app.cognition.agent_history.artifacts("task_abc")) == 1
    evs = app.cognition.events.query_by_type("AGENT_COMPLETED")
    assert len(evs) == 1, "owner 记录 AGENT_COMPLETED 事件"
    app.cognition.close()


def test_app_freeze_snapshot_includes_cognitive_context(tmp_path):
    """owner ingress 冻结 Direct snapshot 时附带 bounded cognitive context（plain immutable）。"""
    from furina.app import Furina
    app = object.__new__(Furina)
    app._sched = None
    app.agent = None
    app.relationship = None
    app.memory = SimpleNamespace(retrieve=lambda *a, **k: [], interpret=lambda *a, **k: {})
    app.state = SimpleNamespace(state=SimpleNamespace(
        life=SimpleNamespace(macro=None, activity="read", reason=""),
        intent=SimpleNamespace(action="", emotion="", priority=0.0),
        emotion=SimpleNamespace(label="calm"),
        user_idle_seconds=0.0))
    app.cognition = CognitionHub(tmp_path / "cog.db")
    snap = app._freeze_direct_snapshot("今天吃什么")
    assert len(snap.cognitive_context) > 0, "快照必须携带 bounded cognitive context"
    d = dict(snap.cognitive_context)
    assert "canon_activation" in d and d["canon_activation"] == 0
    app.cognition.close()


# ================================================================ User Model runtime 集成（Phase 14J）
def test_user_model_plan_visible_in_context(tmp_path):
    hub = CognitionHub(tmp_path / "cog.db")
    cand = hub.extract_user_model("我今天准备完成桌宠测试")
    assert cand and cand["category"] == "PLAN"
    hub.user_model.upsert_item(category=cand["category"], key=cand["key"], value=cand["value"],
                               confidence=cand["confidence"],
                               source_text_excerpt=cand["excerpt"])
    ctx = hub.assemble(query="我今天准备干什么？")
    assert any(i.category == "PLAN" for i in ctx.user_model_items), "Context 含 PLAN"
    # UserModel 不得覆盖 current explicit user turn（assembler 输出只是参考事实）
    assert ctx.current_facts is not None
    hub.close()


# ================================================================ FACT_CORE 保留 B（reviewer 24）
def test_agent_fact_core_keeps_destination_even_if_persona_omits():
    """LLM persona 报告漏掉 B → deterministic FACT_CORE 仍含 B（既有契约回归 + C7 事实）。"""
    from furina.dialogue_brain import _dialogue_prompt_v2
    from types import SimpleNamespace as _NS

    class _App:
        def to_prompt(self):
            return {"mode": "RESPONSIBLE", "secondary_mode": "", "dialogue_act": "REPORT",
                    "strategy": ""}
        mode = "RESPONSIBLE"
        dialogue_act = "REPORT"

    p = _dialogue_prompt_v2(_App(), intent="assist_user", emotion="proud", user_text="",
                            context="", memories=[], world={}, examples=[], person="",
                            activity="agent_report", agent_state="COMPLETED_VERIFIED",
                            agent_task="把 notes.md 移到 Docs",
                            agent_facts={"goal": "把 notes.md 移到 Docs", "terminal_status": "REPLIED",
                                         "verified": True,
                                         "concrete_evidence": "已移到 C:/Docs/notes.md",
                                         "has_duration_evidence": False})
    assert "C:/Docs/notes.md" in p or "Docs/notes.md" in p, "FACT_CORE 必须保留目的地 B"
    assert "FACT_CORE" in p
