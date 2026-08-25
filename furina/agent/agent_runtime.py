"""Agent Runtime（legacy-plan/5 §4, §25）。

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
        # 角色行为同步钩子（legacy-plan/5 §15），由 app 注入：如 approach/walk/report
        self.on_body_sync: Optional[Callable[[str], None]] = None
        # FINAL-R1 §8.1：**显式生命周期状态**（Harness 只读此真相，不读不存在的字段）
        self.status = "IDLE"   # IDLE / RUNNING / COMPLETED_VERIFIED / FAILED / UNVERIFIED

    # -------------------------------------------------- 主循环
    def execute(self, user_request: str, extra_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.status = "RUNNING"   # FINAL-R1 §8.1：真实生命周期状态（每个转移都更新）
        self.bus.emit(EventType.AGENT_STARTED, payload={"request": user_request}, source="agent")
        log.info("agent: %s", user_request)
        # Phase 13 终审 §10.2：**任务局部上下文** —— 每次 execute 用全新 AgentContext，
        # 绝不把任务 A 的 path/vars 泄漏进任务 B（持久 context 只允许显式安全全局设置）。
        task_ctx = AgentContext()
        if extra_context:
            task_ctx.vars.update(extra_context)
        self._body("approach")           # 走向屏幕
        plan = self.planner.build_plan(user_request, task_ctx.vars)
        log.info("agent plan: goal=%s steps=%d status=%s", plan.goal, len(plan.steps), plan.status)
        # 计划不可行（无法映射工具/缺参数）→ 如实失败，绝不假装成功（legacy-plan/5 §24）
        if plan.status in ("unable", "failed"):
            reason = plan.constraints[-1] if plan.constraints else f"plan_status:{plan.status}"
            self.bus.emit(EventType.AGENT_FAILED, payload={"reason": reason}, source="agent")
            self._body("confused")
            self.status = "FAILED"
            return {"status": "failed", "reason": reason, "results": []}
        self._body("work")

        results: List[Dict[str, Any]] = []
        for i, step in enumerate(plan.steps):
            # 未知工具 → 如实失败，绝不崩溃/假装成功（legacy-plan/5 §24）
            try:
                tool = self.tools.get(step.tool)
            except Exception as e:
                self.bus.emit(EventType.AGENT_FAILED,
                              payload={"step": i, "reason": f"unknown_tool:{step.tool}"},
                              source="agent")
                self._body("confused")
                self.status = "FAILED"
                return {"status": "failed", "reason": str(e), "results": results}
            # 权限检查
            decision = self.permission.check(f"{tool.description}：{step.args}", tool.permission)
            if not decision.granted:
                self.bus.emit(EventType.AGENT_FAILED, payload={"step": i, "reason": "permission_denied"},
                              source="agent")
                self._body("report")
                self.status = "FAILED"
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
                self.status = "FAILED"
                return {"status": "failed", "reason": res.error, "results": results}
            # Phase 13 终审 §10.3：**verified=False 不得 COMPLETED**（ok 只是"没抛错"，不是"完成"）
            if not verified:
                reason = f"unverified_step:{i}:{step.tool}"
                self.bus.emit(EventType.AGENT_FAILED, payload={"step": i, "reason": reason}, source="agent")
                self._body("confused")
                self.status = "UNVERIFIED"
                return {"status": "unverified", "reason": reason, "results": results}

        self._body("report")
        # Phase 13 终审 §10.6：结构化事实摘要来自**已验证**结果（DialogueBrain 只能角色化事实，不得发明成功）
        ok_verified = [r for r in results if r["ok"] and r["verified"]]
        summary = (f"完成了 {len(ok_verified)}/{len(results)} 个步骤："
                   f"{plan.goal}（已验证 {len(ok_verified)} 步）")
        self.bus.emit(EventType.AGENT_COMPLETED,
                      payload={"goal": plan.goal, "results": results, "summary": summary,
                               "verified": True},
                      source="agent")
        self.status = "COMPLETED_VERIFIED"
        return {"status": "completed", "goal": plan.goal, "results": results, "summary": summary}

    # -------------------------------------------------- Verify（§5 / FINAL-R1 §6）
    def _verify(self, step, res: ToolResult) -> bool:
        """FINAL-R1 §6：**全局硬门** —— 必需条件 `res.ok AND res.verified`。

        工具特定的语义检查只会更严、绝不放宽（BaseTool.verify 语义一致执行）。
        `ToolResult(ok=True, verified=False)`（如 launch 观察失败）**绝不**算完成。
        """
        if not res.ok:
            return False
        if not res.verified:
            return False
        # 工具特定语义（更严，不更松）：有数据才可验证
        if step.tool in ("fs.list_dir", "fs.make_dirs", "fs.organize"):
            return res.data is not None
        return True

    # -------------------------------------------------- 身体同步（legacy-plan/5 §15）
    def _body(self, phase: str) -> None:
        if self.on_body_sync:
            self.on_body_sync(phase)
