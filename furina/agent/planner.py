"""Planner（plan/5 §4, §12, §26）。

Agent 遵循 Observe → Plan → Act → Verify → Reflect。
用户请求先形成 Goal，再定 Plan，再执行；禁止“LLM 乱动”。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from furina.core import AgentError, get_logger
from .tool import ToolRegistry, ToolResult

log = get_logger("agent.planner")


@dataclass
class AgentStep:
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    expect: str = ""                  # 预期结果描述（用于 Verify）
    verified: bool = False


@dataclass
class AgentPlan:
    goal: str
    steps: List[AgentStep] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    status: str = "planned"          # planned / executing / completed / failed


class Planner:
    """骨架：由 LLM 生成结构化计划，Runtime 逐条执行并验证。

    LLM 只产 Goal/Plan，不直接调工具（plan/5 §3）。
    """

    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    def build_plan(self, user_request: str, context: Optional[Dict[str, Any]] = None) -> AgentPlan:
        """骨架用启发式；后续换成 Zhipu structured() 产出 AgentPlan。"""
        context = context or {}
        log.info("planner: request=%s", user_request)
        plan = AgentPlan(goal=user_request, constraints=["不得越权", "重要步骤必须校验"])
        # 整理/下载类任务需要知道目标目录（由上游 context 注入，绝不用 "~" 兜底）
        base_path = context.get("path") if context.get("path") else None
        if "整理" in user_request or "desktop" in user_request.lower() or "下载" in user_request:
            if not base_path:
                plan.status = "failed"
                plan.constraints.append("缺少目标目录(path)，需用户指定")
                return plan
            plan.steps = [
                AgentStep(tool="fs.list_dir", args={"path": base_path}, expect="目录列表"),
                AgentStep(tool="fs.make_dirs", args={"base": base_path, "names": ["PDF", "Images", "ZIP", "Docs"]},
                          expect="分类目录存在"),
                AgentStep(tool="fs.organize", args={"base": base_path, "dry_run": True},
                          expect="文件归类预览（先干跑，不破坏）"),
                # 干跑通过后再真正移动（plan/5 §24：动作必须真实发生并在完成后验证，绝不假装成功）。
                # 真实移动属于 L2 高风险，由权限层在用户主动触发的任务中放行。
                AgentStep(tool="fs.organize", args={"base": base_path, "dry_run": False},
                          expect="文件已实际归类"),
                AgentStep(tool="fs.list_dir", args={"path": base_path}, expect="验证归类后的目录"),
            ]
        elif "打开" in user_request or "open" in user_request.lower():
            plan.steps = [
                AgentStep(tool="app.launch", args={"name": _guess_app(user_request)}, expect="应用启动"),
            ]
        elif any(k in user_request.lower() for k in ("看", "观察", "屏幕", "看看", "observe", "screenshot", "桌面")):
            # “看软件 / 看屏幕” → 抓屏（只读），供后续视觉观察
            plan.steps = [AgentStep(tool="computer.screenshot", args={}, expect="屏幕截图")]
        else:
            # 未识别的任务：不生成会导致崩溃的伪步骤（旧版引用不存在的 computer.observe_screen）。
            # 转为 seek 澄清/先观察屏幕，交由上层通过 LLM 理解（plan/5 §3: LLM 只产 Goal/Plan）。
            plan.status = "unable"
            plan.constraints.append("无法将请求映射到现有工具，避免调用工具崩溃；请用户澄清或配置对应工具")
        return plan


def _guess_app(text: str) -> str:
    for kw, app in (("vscode", "code"), ("word", "winword"), ("excel", "excel"),
                    ("ppt", "powerpnt"), ("chrome", "chrome"), ("浏览器", "chrome"),
                    ("记事本", "notepad")):
        if kw in text.lower():
            return app
    return "notepad"
