"""Phase 14.1 Production Wiring & Safety Closure 测试（tests/agent/integration/）。

全部走 **production path**（真实 `Furina(cfg)` + 真实 AgentRuntime + 真实 PlannerV2 +
真实 PermissionManager / ApplicationCatalog / CognitionHub）：
- 唯一例外是 LLM 响应 stub（测试环境无 API key）—— PlannerV2 / validation / permission /
  C7 / C6 / C4 全部是真实生产代码，仅模型输出被替身；禁止用 FixedPlanner 代替验收。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest import mock

import pytest
from PySide6.QtWidgets import QApplication

from furina.agent import ToolRegistry
from furina.agent.capabilities import build_capability_registry
from furina.agent.capabilities.applications import ApplicationCatalog
from furina.agent.permission import Permission
from furina.agent.planner_v2 import PlannerV2
from furina.agent.tools.apps import LaunchTool
from furina.app import Furina
from furina.config import AppConfig, LLMProfile

_QAPP = QApplication.instance() or QApplication([])


@pytest.fixture()
def fapp(tmp_path):
    """真实 Furina（无 LLM key；fallback dispatcher 绑定测试线程 = owner；独立 temp DB）。"""
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
    """测试替身：返回固定 JSON 计划（PlannerV2 真实解析 + 真实 validation）。"""

    def __init__(self, plan_json, available=True):
        self._plan = plan_json
        self._available = available

    def is_available(self):
        return self._available

    def structured(self, messages, *, schema=None, temperature=None):
        return json.loads(self._plan)


class _StubBrain:
    def say_with_result(self, **kw):
        return {"speech": "嗯，好的。", "failure_reason": "",
                "validation_issues": [], "hard_issues": [], "soft_issues": []}


def _spy_executed(agent):
    """给注册工具包一层计数代理（证明"执行前被拒"）。"""
    executed = []
    for name in agent.tools.list():
        tool = agent.tools.get(name)
        fn = tool.run

        def _make(nm, fn0):
            def _spy(**kw):
                executed.append(nm)
                return fn0(**kw)
            return _spy
        tool.run = _make(name, fn)
    return executed


# ================================================================ 1. production planner wiring
def test_1_production_agent_planner_is_planner_v2(fapp):
    from furina.agent.planner_v2 import PlannerV2
    assert isinstance(fapp.agent.planner, PlannerV2), "production agent.planner 必须是 PlannerV2"
    assert fapp.agent.planner.tools is fapp.tools
    assert fapp.agent.planner.registry is fapp.capability_registry
    # 同一 LLM adapter（禁止第二套模型配置）
    assert fapp.agent.planner.llm is fapp.llm, "PlannerV2 必须共享项目唯一 LLM adapter"
    assert fapp.llm is not None or fapp.agent.planner.llm is None


# ================================================================ 2/3. natural language acceptance（真实 Furina）
def test_2_production_nl_md_creation_real_file(fapp, tmp_path):
    """'创建 hello.md，内容 Hello Furina' → PlannerV2 → doc.create → real file verified。"""
    res = fapp.agent.execute("创建 hello.md，内容 Hello Furina", {"path": str(tmp_path)})
    assert res["status"] == "completed", f"production 必须完成: {res}"
    f = tmp_path / "hello.md"
    assert f.exists() and f.read_text(encoding="utf-8") == "Hello Furina", "真实文件存在且内容正确"
    # 计划确实来自 production PlannerV2（非 FixedPlanner）
    plan = fapp.agent.planner.build_plan("创建 hello.md，内容 Hello Furina", {"path": str(tmp_path)})
    assert plan.steps and plan.steps[0].tool == "doc.create"


def test_3_production_nl_docx_plan(fapp, tmp_path):
    """'创建 Word 文档' → PlannerV2 → docx.create（真实 Furina production wiring）。"""
    res = fapp.agent.execute("创建 Word 文档", {"path": str(tmp_path)})
    assert res["status"] == "completed", res
    assert (tmp_path / "document.docx").exists(), "真实 docx 文件必须存在"
    plan = fapp.agent.planner.build_plan("创建 Word 文档", {"path": str(tmp_path)})
    assert plan.steps[0].tool == "docx.create"


# ================================================================ 4/5. overwrite permission（L1 denied / L2 authorized）
def test_4_l1_cannot_overwrite_existing(fapp, tmp_path):
    """用户只授权 L1 → 覆盖已有 report.md 被拒 → 原字节不变。"""
    report = tmp_path / "report.md"
    report.write_text("original", encoding="utf-8")
    llm = _StubLLM(json.dumps({"goal": "覆盖", "steps": [{"tool": "doc.write",
                                                          "args": {"path": str(report),
                                                                   "content": "hacked",
                                                                   "overwrite": True},
                                                          "expect": "覆盖"}]}))
    fapp.agent.planner = PlannerV2(fapp.tools, fapp.capability_registry, llm=llm)
    executed = _spy_executed(fapp.agent)
    res = fapp.agent.execute("覆盖 report.md", {})
    assert res["status"] == "failed" and "permission_denied" in res["reason"], res
    assert "doc.write" not in executed, "覆盖工具不得执行"
    assert report.read_text(encoding="utf-8") == "original", "原字节不变"


def test_5_l2_explicit_authorize_overwrites(fapp, tmp_path):
    """L2 显式授权（本次 task scoped AuthorizationContext）→ overwrite → reread verified。"""
    report = tmp_path / "report.md"
    report.write_text("original", encoding="utf-8")
    llm = _StubLLM(json.dumps({"goal": "覆盖", "steps": [{"tool": "doc.write",
                                                          "args": {"path": str(report),
                                                                   "content": "hacked",
                                                                   "overwrite": True},
                                                          "expect": "覆盖"}]}))
    fapp.agent.planner = PlannerV2(fapp.tools, fapp.capability_registry, llm=llm)
    # Phase 14.1.1：授权 = 本次 task 的 AuthorizationContext（不再有全局 authorize set）
    task_auth = fapp.permission.new_task_context(max_permission=Permission.L2_HIGH_RISK,
                                                 source="test:L2")
    res = fapp.agent.execute("覆盖 report.md", {}, task_auth=task_auth)
    assert res["status"] == "completed", f"L2 显式授权应可覆盖: {res}"
    assert report.read_text(encoding="utf-8") == "hacked", "覆盖后 reread verified"


def test_5b_production_confirm_callback_never_blanket_allows(fapp):
    """App confirm 回调必须默认拒绝（不 blanket allow L2/L3）。"""
    assert fapp._confirm_agent_permission("删除文件", Permission.L2_HIGH_RISK) is False
    assert fapp._confirm_agent_permission("发送消息", Permission.L3_SENSITIVE) is False


# ================================================================ 6. delete never blanket auto-confirm
def test_6_delete_no_blanket_auto_confirm(fapp, tmp_path):
    target = tmp_path / "precious.txt"
    target.write_text("keep", encoding="utf-8")
    llm = _StubLLM(json.dumps({"goal": "删除", "steps": [{"tool": "fs.delete",
                                                          "args": {"path": str(target)},
                                                          "expect": "删除"}]}))
    fapp.agent.planner = PlannerV2(fapp.tools, fapp.capability_registry, llm=llm)
    executed = _spy_executed(fapp.agent)
    res = fapp.agent.execute("删除文件", {})
    assert res["status"] == "failed" and "permission_denied" in res["reason"], res
    assert "fs.delete" not in executed, "无显式授权 → delete 绝不执行"
    assert target.exists(), "文件必须原样保留"


# ================================================================ 7. ApplicationCatalog production wiring
def test_7_catalog_consumed_by_production_launch(fapp):
    tool = fapp.tools.get("app.launch")
    assert isinstance(tool, LaunchTool)
    assert isinstance(tool.catalog, ApplicationCatalog), "production app.launch 必须消费 Catalog"
    # 真实可发现应用（本机 PATH）可 resolve 到真实 target
    rec = tool.catalog.resolve("notepad") or tool.catalog.resolve("记事本")
    assert rec is not None and rec.launch_target, "真实 discover 到 target"
    # 未知 → unable + Popen 0（不得启动 notepad）
    with mock.patch("furina.agent.tools.apps.subprocess.Popen") as m:
        r = tool.run("XYZABC不存在的软件")
        assert not r.ok and m.call_count == 0
    # 真实 Agent 任务：打开记事本（Popen+observe 由系统真实路径 mock）
    with mock.patch("furina.agent.tools.apps.subprocess.Popen"), \
         mock.patch("furina.agent.tools.apps._observe_process", return_value=True):
        res = fapp.agent.execute("打开记事本", {})
    assert res["status"] == "completed", f"真实 app.launch 必须完成: {res}"


def test_7b_menu_task_scoped_authorization_only(fapp):
    """精选安全菜单任务 → 本次 task 独立 bounded AuthorizationContext（工具/路径限定）；
    任意文本请求不授予。"""
    captured = {}

    def _spy_execute(req, ctx=None, task_auth=None):
        captured["auth"] = task_auth
        return {"status": "skipped"}   # 不真正执行（只验证授权构造）
    fapp.agent.execute = _spy_execute
    fapp._agent_worker("整理下载文件夹")
    auth = captured.get("auth")
    assert auth is not None, "菜单任务必须构造 task-scoped AuthorizationContext"
    assert auth.max_permission == Permission.L2_HIGH_RISK
    assert "fs.organize" in auth.allowed_tools, "菜单 L2 必须限定 organize 确定性序列工具"
    assert "fs.delete" not in auth.allowed_tools, "菜单 L2 不得覆盖任意工具（尤其 fs.delete）"
    assert "Downloads" in auth.allowed_path_root, "菜单 L2 必须限定路径根 = 用户 Downloads"
    # 任意文本请求不授予
    captured.clear()
    fapp._agent_worker("随便说的任意请求文本")
    a2 = captured.get("auth")
    assert a2 is None or a2.max_permission == Permission.L1_LOW_WRITE, \
        "任意文本请求不得获得 L2 授权"


# ================================================================ 8/9. C7 exact lifecycle preservation
def test_8_runtime_failed_persists_failed(fapp):
    res = fapp.agent.execute("打开一个不存在的XYZABC软件", {})
    assert res["status"] == "failed"
    rec = res["task_record"]
    fapp.cognition.persist_agent_result(
        rec["task_id"], status=rec["status"], goal=rec["goal"],
        original_request=rec["original_request"], verified=rec["verified"],
        result_summary=rec["result_summary"], error=rec["error"],
        steps=rec["steps"], artifacts=rec["artifacts"])
    t = fapp.cognition.agent_history.get_task(rec["task_id"])
    assert t.status == "FAILED", f"runtime FAILED → C7 FAILED（不得被 verified bool 替代）: {t.status}"


def test_9_runtime_unverified_persists_unverified(fapp, tmp_path):
    from furina.agent.tool import ToolResult
    # 计划第一步 fs.list_dir 返回 ok=True verified=False → runtime UNVERIFIED
    with mock.patch.object(fapp.tools.get("fs.list_dir"), "run",
                           return_value=ToolResult(True, data=None, verified=False)):
        res = fapp.agent.execute("整理下载文件夹", {"path": str(tmp_path)})
    assert res["status"] == "unverified", res
    rec = res["task_record"]
    fapp.cognition.persist_agent_result(
        rec["task_id"], status=rec["status"], goal=rec["goal"],
        original_request=rec["original_request"], verified=rec["verified"],
        result_summary=rec["result_summary"], error=rec["error"],
        steps=rec["steps"], artifacts=rec["artifacts"])
    t = fapp.cognition.agent_history.get_task(rec["task_id"])
    assert t.status == "UNVERIFIED", f"runtime UNVERIFIED → C7 UNVERIFIED: {t.status}"


# ================================================================ 10/11. C2 context reaches real Direct snapshot
def test_10_canon_episode_reaches_real_direct_snapshot(fapp):
    """'如果没人关注你了怎么办' → 真实 _freeze_direct_snapshot 含相关 episode + present-day effect。"""
    snap = fapp._freeze_direct_snapshot("如果没人关注你了怎么办")
    d = dict(snap.cognitive_context)
    assert d["canon"]["activation"] == 2
    ids = [e["episode_id"] for e in d["canon"]["episodes"]]
    assert any(i in ids for i in ("LONG_PERFORMANCE", "ORDINARY_LIFE", "CHOSEN_PERFORMANCE")), ids
    assert any(e.get("present_day_effects") for e in d["canon"]["episodes"]), "必须含 present-day effect"
    assert all("objective_summary" in e for e in d["canon"]["episodes"])


def test_10b_focalors_query_activation_3(fapp):
    snap = fapp._freeze_direct_snapshot("你和芙卡洛斯是什么关系")
    d = dict(snap.cognitive_context)
    assert d["canon"]["activation"] == 3
    ids = [e["episode_id"] for e in d["canon"]["episodes"]]
    assert "FOCALORS_TRUTH" in ids or "ORIGIN_IDENTITY" in ids


def test_11_ordinary_query_no_lore_dump(fapp):
    """'今天吃什么' → activation 0 → 快照/上下文不含 explicit Canon plot。"""
    snap = fapp._freeze_direct_snapshot("今天吃什么")
    d = dict(snap.cognitive_context)
    assert d["canon"]["activation"] == 0
    assert d["canon"]["episodes"] == [], "普通日常不得携带 explicit Canon episode"
    serialized = json.dumps(d, ensure_ascii=False, default=str)
    assert "LONG_PERFORMANCE" not in serialized, "不得把 LONG_PERFORMANCE 写进普通上下文"
    # prompt 注入路径同样无 lore（有界）
    from furina.dialogue_brain import _dialogue_prompt_v2
    class _A:
        def to_prompt(self):
            return {"mode": "CASUAL", "secondary_mode": "", "dialogue_act": "COMMENT", "strategy": ""}
    p = _dialogue_prompt_v2(_A(), intent="talk", emotion="calm", user_text="今天吃什么",
                            context="", memories=None, world=None, examples=[], person="",
                            activity="read", cognitive_context=d)
    assert "过去经历片段" not in p, "prompt 不得渲染 Canon episode 段落（activation 0）"
    assert "【认知上下文" not in p or "LONG_PERFORMANCE" not in p


# ================================================================ 12/13. C6 exact-once counts
def test_12_c6_direct_event_exact_counts(fapp):
    fapp.dialogue_brain = _StubBrain()
    fapp.submit_user_message("你好呀")
    q = fapp._direct_dialogue_queue()
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        fapp._rt_dispatcher().drain()
        if q.wait_idle(0.05):
            break
        time.sleep(0.01)
    fapp._rt_dispatcher().drain()
    umsgs = fapp.cognition.events.query_by_type("USER_MESSAGE")
    assert len(umsgs) == 1, f"USER_MESSAGE 必须 exactly once: {len(umsgs)}"
    turn_id = umsgs[0].turn_id
    assert turn_id, "USER_MESSAGE 必须带 turn_id"
    turn_evs = fapp.cognition.events.query_by_turn(turn_id)
    by_type = {}
    for e in turn_evs:
        by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
    assert by_type.get("USER_MESSAGE", 0) == 1
    assert by_type.get("DIRECT_TURN_STARTED", 0) == 1
    assert by_type.get("DIRECT_TURN_TERMINAL", 0) == 1, f"DIRECT terminal exactly once: {by_type}"
    assert by_type.get("FURINA_SPOKE", 0) == 1, f"FURINA_SPOKE exactly once（有可见台词）: {by_type}"


def test_13_c6_agent_lifecycle_exact_counts(fapp, tmp_path):
    res = fapp.agent.execute("整理下载文件夹", {"path": str(tmp_path)})   # 无菜单授权 → L2 拒 → FAILED
    fapp._rt_dispatcher().drain()   # on_task_finished → owner _persist_agent_task → AGENT_FAILED event
    tid = res["task_id"]
    evs = fapp.cognition.events.query_by_task(tid)
    started = [e for e in evs if e.event_type == "AGENT_STARTED"]
    terminal = [e for e in evs if e.event_type in
                ("AGENT_COMPLETED", "AGENT_FAILED", "AGENT_UNVERIFIED", "AGENT_CANCELLED")]
    assert len(started) == 1, f"AGENT_STARTED exactly once: {len(started)}"
    assert len(terminal) == 1, f"Agent terminal exactly once: {len(terminal)}"
    assert terminal[0].event_type == "AGENT_FAILED", "L2 未授权 organize → FAILED"


# ================================================================ 14. C4 evidence chain
def test_14_c4_item_source_event_id_resolves_c6(fapp):
    fapp.dialogue_brain = _StubBrain()
    fapp.submit_user_message("我今天准备完成桌宠测试")
    items = fapp.cognition.user_model.query_active(limit=20)
    plan_items = [i for i in items if i.category == "PLAN" and "桌宠" in str(i.value)]
    assert plan_items, "PLAN item 必须存在"
    it = plan_items[0]
    assert it.source_event_id != "", "source_event_id 必须非空"
    evs = fapp.cognition.events.query_by_type("USER_PLAN_DECLARED")
    assert any(e.event_id == it.source_event_id for e in evs), "source_event_id 必须解析到 C6 event"
    assert "桌宠" in it.source_text_excerpt, "excerpt 必须保留"


# ================================================================ 15/16. PlannerV2 validation 硬化
def test_15_unknown_tool_execution_count_zero(fapp):
    llm = _StubLLM('{"goal": "创建", "steps": [{"tool": "fs.nonexistent_tool", '
                   '"args": {"path": "C:/x"}, "expect": "x"}]}')
    fapp.agent.planner = PlannerV2(fapp.tools, fapp.capability_registry, llm=llm)
    executed = _spy_executed(fapp.agent)
    res = fapp.agent.execute("创建文件", {})
    assert res["status"] in ("failed", "unverified"), res
    assert executed == [], f"未知 tool 不得执行任何工具: {executed}"
    assert "fs.nonexistent_tool" not in json.dumps(res, default=str)


def test_16_malformed_missing_args_rejected_pre_execution(fapp, tmp_path):
    # 16a：缺失 required（doc.create 需要 path）→ 执行前拒绝
    llm1 = _StubLLM('{"goal": "创建", "steps": [{"tool": "doc.create", '
                    '"args": {"content": "x"}, "expect": "x"}]}')
    fapp.agent.planner = PlannerV2(fapp.tools, fapp.capability_registry, llm=llm1)
    executed = _spy_executed(fapp.agent)
    res = fapp.agent.execute("创建文件", {"path": str(tmp_path)})
    assert res["status"] in ("failed", "unverified"), res
    assert executed == [], "缺失 required args 必须执行前拒绝"
    # 16b：NUL / 空 path 拒绝
    llm2 = _StubLLM('{"goal": "创建", "steps": [{"tool": "doc.create", '
                    '"args": {"path": "C:/x\\u0000y.md", "content": "x"}, "expect": "x"}]}')
    fapp.agent.planner = PlannerV2(fapp.tools, fapp.capability_registry, llm=llm2)
    executed = _spy_executed(fapp.agent)
    res2 = fapp.agent.execute("创建文件", {"path": str(tmp_path)})
    assert res2["status"] in ("failed", "unverified"), res2
    assert executed == [], "NUL path 必须执行前拒绝"


# ================================================================ Windows integration（真实 temp + 真实发现）
def test_windows_integration_real_temp_and_discovery(tmp_path):
    """Windows 本机：MD 创建/写入；已有文件无 L2 拒绝；L2 显式覆盖 verified；真实应用发现。"""
    from furina.agent.tools.filesystem import WriteTextTool
    p = tmp_path / "note.md"
    r = WriteTextTool().run(str(p), content="v1")
    assert r.ok and r.verified and p.read_text(encoding="utf-8") == "v1"
    # 已有文件无 L2 → 默认拒绝
    r2 = WriteTextTool().run(str(p), content="v2")
    assert not r2.ok and p.read_text(encoding="utf-8") == "v1", "已有文件默认拒绝覆盖"
    # 显式 overwrite（工具层 L1 语义已含 overwrite=True；权限由上层 L2 授权）
    r3 = WriteTextTool().run(str(p), content="v2", overwrite=True)
    assert r3.ok and r3.verified and p.read_text(encoding="utf-8") == "v2"
    # 真实应用发现（不批量启动第三方 app；只验证 resolve + 未知不猜）
    cat = ApplicationCatalog()
    recs = cat.all_records()
    assert recs, "Windows 上应发现至少一个真实应用"
    assert cat.resolve("XYZABC不存在") is None
    # 至少能 resolve 一个本机真实应用（notepad 或任意 PATH 应用）
    resolvable = [r for r in recs if r.launch_target]
    assert resolvable, "Catalog 必须产出带真实 launch_target 的 record"
