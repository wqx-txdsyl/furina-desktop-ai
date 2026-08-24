"""Agent Runtime（plan/5 §4, §25）。

USER REQUEST → UNDERSTAND → CHECK PERMISSION → OBSERVE → PLAN → ACT
→ OBSERVE RESULT → VERIFY → (success/recoverable/blocked)。

关键：绝不假装成功（§24）；高权限必须确认（§19）；Agent 与角色行为同步（§15）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from furina.core import EventBus, EventType, get_logger
from .permission import Permission, PermissionManager
from .planner import AgentPlan, Planner
from .tool import ToolRegistry, ToolResult

log = get_logger("agent.runtime")


@dataclass
class AgentContext:
    """跨步骤共享上下文（如目标目录）。"""
    vars: Dict[str, Any] = field(default_factory=dict)


class AgentRuntime:
    def __init__(self, bus: EventBus, tools: ToolRegistry, permission: PermissionManager,
                 planner_factory: Callable[[ToolRegistry], Planner] = Planner) -> None:
        self.bus = bus
        self.tools = tools
        self.permission = permission
        self.planner = planner_factory(tools)
        self.context = AgentContext()
        # 角色行为同步钩子（plan/5 §15），由 app 注入：如 approach/walk/report
        self.on_body_sync: Optional[Callable[[str], None]] = None

    # -------------------------------------------------- 主循环
    def execute(self, user_request: str, extra_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.bus.emit(EventType.AGENT_STARTED, payload={"request": user_request}, source="agent")
        log.info("agent: %s", user_request)
        if extra_context:
            self.context.vars.update(extra_context)
        self._body("approach")           # 走向屏幕
        plan = self.planner.build_plan(user_request, self.context.vars)
        log.info("agent plan: goal=%s steps=%d status=%s", plan.goal, len(plan.steps), plan.status)
        # 计划不可行（无法映射工具/缺参数）→ 如实失败，绝不假装成功（plan/5 §24）
        if plan.status in ("unable", "failed"):
            reason = plan.constraints[-1] if plan.constraints else f"plan_status:{plan.status}"
            self.bus.emit(EventType.AGENT_FAILED, payload={"reason": reason}, source="agent")
            self._body("confused")
            return {"status": "failed", "reason": reason, "results": []}
        self._body("work")

        results: List[Dict[str, Any]] = []
        for i, step in enumerate(plan.steps):
            # 未知工具 → 如实失败，绝不崩溃/假装成功（plan/5 §24）
            try:
                tool = self.tools.get(step.tool)
            except Exception as e:
                self.bus.emit(EventType.AGENT_FAILED,
                              payload={"step": i, "reason": f"unknown_tool:{step.tool}"},
                              source="agent")
                self._body("confused")
                return {"status": "failed", "reason": str(e), "results": results}
            # 权限检查
            decision = self.permission.check(f"{tool.description}：{step.args}", tool.permission)
            if not decision.granted:
                self.bus.emit(EventType.AGENT_FAILED, payload={"step": i, "reason": "permission_denied"},
                              source="agent")
                self._body("report")
                return {"status": "failed", "reason": "permission_denied", "results": results}
            # 执行
            try:
                res: ToolResult = tool.run(**step.args)
            except TypeError as e:
                res = ToolResult(False, error=f"参数错误: {e}")
            except Exception as e:
                res = ToolResult(False, error=str(e))
            # Validate：Verify（§5, §24）—— 骨架以工具 verified 字段 + 注意非空为准
            verified = self._verify(step, res)
            results.append({"step": i, "tool": step.tool, "ok": res.ok,
                            "verified": verified, "data": res.data, "error": res.error})
            if not res.ok:
                self.bus.emit(EventType.AGENT_FAILED, payload={"step": i, "error": res.error}, source="agent")
                self._body("confused")
                return {"status": "failed", "reason": res.error, "results": results}

        self._body("report")
        self.bus.emit(EventType.AGENT_COMPLETED, payload={"goal": plan.goal, "results": results}, source="agent")
        return {"status": "completed", "goal": plan.goal, "results": results}

    # -------------------------------------------------- Verify（§5）
    def _verify(self, step, res: ToolResult) -> bool:
        # 简单骨架验证：失败必 false
        if not res.ok:
            return False
        # 需有数据的只读/写操作，data 为空视为未验证成功
        if step.tool in ("fs.list_dir", "fs.make_dirs") and not res.data:
            return False
        # fs.organize：dry_run 预览本身成功即可（如实标 verified），但真实移动必须看到实际移动结果
        if step.tool == "fs.organize":
            return res.ok and res.data is not None
        return True

    # -------------------------------------------------- 身体同步（plan/5 §15）
    def _body(self, phase: str) -> None:
        if self.on_body_sync:
            self.on_body_sync(phase)
