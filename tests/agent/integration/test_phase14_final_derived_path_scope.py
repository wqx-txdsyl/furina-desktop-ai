"""Phase 14 FINAL Derived Path Scope Closure 测试（tests/agent/integration/）。

fs.make_dirs 的 derived paths：Authorization allowed_path_root 必须验证工具**真正写入的
最终 filesystem paths**（resolve(base/name)），不能只验证 args 里叫 base 的字段。

Reviewer-locked production tests —— 全部走：
真实 AgentRuntime → PlannerV2（stub LLM 只提供 plan JSON）→ PermissionManager →
真实 tool execution spy（执行计数证明 permission 先于执行）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from furina.agent.permission import Permission
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
    def __init__(self, plan_json):
        self._plan = plan_json

    def is_available(self):
        return True

    def structured(self, messages, *, schema=None, temperature=None):
        return json.loads(self._plan)


def _run(fapp, tmp_path, names, scope_root=None):
    """真实 AgentRuntime + 真实 PlannerV2(stub LLM) + task-scoped auth + 执行 spy。

    scope_root：allowed_path_root（默认 tmp_path/Downloads）；
    allowed_tools = ("fs.make_dirs",)。
    """
    root = scope_root or (tmp_path / "Downloads")
    root.mkdir(parents=True, exist_ok=True)
    auth = fapp.permission.new_task_context(
        max_permission=Permission.L2_HIGH_RISK,
        allowed_tools=("fs.make_dirs",),
        allowed_path_root=str(root), source="menu:make_dirs")
    plan = {"goal": "创建目录", "steps": [{"tool": "fs.make_dirs",
                                          "args": {"base": str(root), "names": names},
                                          "expect": "目录存在"}]}
    fapp.agent.planner = PlannerV2(fapp.tools, fapp.capability_registry,
                                   llm=_StubLLM(json.dumps(plan)))
    # 执行 spy：记录 fs.make_dirs 真实执行次数
    counts = {"make_dirs": 0}
    real = fapp.tools.get("fs.make_dirs").run

    def _spy(**kw):
        counts["make_dirs"] += 1
        return real(**kw)
    fapp.tools.get("fs.make_dirs").run = _spy
    res = fapp.agent.execute("创建目录", {"path": str(root)}, task_auth=auth)
    return res, counts, root


# ================================================================ 1. in-scope derived path → COMPLETED
def test_1_make_dirs_in_scope_derived_allowed(fapp, tmp_path):
    """base=Downloads, names=["X"] → derived Downloads/X ∈ root → COMPLETED + X 存在。"""
    res, counts, root = _run(fapp, tmp_path, ["X"])
    assert res["status"] == "completed", res
    assert counts["make_dirs"] == 1, "scope 内必须真实执行"
    assert (root / "X").is_dir(), "Downloads/X 必须真实存在"


# ================================================================ 2. ".." traversal derived → DENIED pre-execution
def test_2_make_dirs_traversal_denied(fapp, tmp_path):
    """names=["../../outside"] → derived 越出 root → FAILED permission_denied /
    task_scope_mismatch / 执行计数=0 / outside 不存在。"""
    res, counts, root = _run(fapp, tmp_path, ["../../outside"])
    assert res["status"] == "failed" and "permission_denied" in res["reason"], res
    assert "task_scope_mismatch" in str(res["task_record"]["permission_summary"]), \
        res["task_record"]["permission_summary"]
    assert counts["make_dirs"] == 0, "越界 step 不得执行（permission 先于执行）"
    outside = (tmp_path / "outside")
    assert not outside.exists(), "outside 不得被创建"


# ================================================================ 3. mixed names: any out-of-root → whole step DENIED
def test_3_make_dirs_mixed_names_whole_step_denied(fapp, tmp_path):
    """names=["A", "../../outside", "B"] → 整个 step DENIED；A/B/outside 均不得创建。"""
    res, counts, root = _run(fapp, tmp_path, ["A", "../../outside", "B"])
    assert res["status"] == "failed" and "permission_denied" in res["reason"], res
    assert "task_scope_mismatch" in str(res["task_record"]["permission_summary"])
    assert counts["make_dirs"] == 0, "混合越界 → 整个 step 不得执行"
    assert not (root / "A").exists() and not (root / "B").exists(), "A/B 不得创建"
    assert not (tmp_path / "outside").exists(), "outside 不得创建"


# ================================================================ 4. absolute child path outside → DENIED
def test_4_make_dirs_absolute_outside_denied(fapp, tmp_path):
    """names=["C:/outside_abs"]（absolute，pathlib 直接落盘）→ derived 越出 root → DENIED。"""
    outside_abs = tmp_path / "outside_abs"
    res, counts, root = _run(fapp, tmp_path, [str(outside_abs)])
    assert res["status"] == "failed" and "permission_denied" in res["reason"], res
    assert "task_scope_mismatch" in str(res["task_record"]["permission_summary"])
    assert counts["make_dirs"] == 0, "absolute 越界不得执行"
    assert not outside_abs.exists(), "absolute 越界目录不得创建"


# ================================================================ defense-in-depth（工具层独立拒绝）
def test_make_dirs_tool_defense_in_depth(tmp_path):
    """MakeDirsTool 自身语义：absolute / .. 穿越 / 空名 / resolve 越出 base → 拒绝。"""
    from furina.agent.tools.filesystem import MakeDirsTool
    base = tmp_path / "base"
    base.mkdir()
    t = MakeDirsTool()
    assert t.run(str(base), ["X"]).ok and (base / "X").is_dir()
    # .. 穿越
    r = t.run(str(base), ["../../outside"])
    assert not r.ok and "越出 base" in r.error
    assert not (tmp_path / "outside").exists()
    # absolute
    r2 = t.run(str(base), [str(tmp_path / "abs")])
    assert not r2.ok and "absolute" in r2.error
    # 空名
    r3 = t.run(str(base), [""])
    assert not r3.ok and "空" in r3.error
