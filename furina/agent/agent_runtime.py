"""Agent Runtime（legacy-plan/5 §4, §25）。

USER REQUEST → UNDERSTAND → CHECK PERMISSION → OBSERVE → PLAN → ACT
→ OBSERVE RESULT → VERIFY → (success/recoverable/blocked)。

关键：绝不假装成功（§24）；高权限必须确认（§19）；Agent 与角色行为同步（§15）。

Phase 14I（C7 integration）：每次 execute 生成 stable task_id；生命周期
PLANNED → RUNNING → COMPLETED_VERIFIED/FAILED/UNVERIFIED/CANCELLED 可持久化；
worker 返回结构化 task_record → `on_task_finished` 回调（由 App 经 dispatcher 提交 owner
→ CognitionHub.persist_agent_result 写 C7）。worker 不直接写 Cognition authoritative DB。
"""
from __future__ import annotations

import time
import uuid
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
                 planner_factory: Callable[[ToolRegistry], Planner] = Planner,
                 task_history: Optional[Callable[[Dict[str, Any]], None]] = None,
                 permission_resolver=None) -> None:
        self.bus = bus
        self.tools = tools
        self.permission = permission
        self.planner = planner_factory(tools)
        self.context = AgentContext()
        # Phase 14.1 §3：动态权限（effective permission）解析器（覆盖已有文件 → L2 等）
        from .permission import EffectivePermissionResolver
        self._perm_resolver = permission_resolver or EffectivePermissionResolver()
        # Phase 14I：worker 产出结构化 task_record → owner persist 回调（App 注入 dispatcher owner 包装）
        self.on_task_finished = task_history
        # 角色行为同步钩子（legacy-plan/5 §15），由 app 注入：如 approach/walk/report
        self.on_body_sync: Optional[Callable[[str], None]] = None
        # FINAL-R1 §8.1：**显式生命周期状态**（Harness 只读此真相，不读不存在的字段）
        self.status = "IDLE"   # IDLE / RUNNING / COMPLETED_VERIFIED / FAILED / UNVERIFIED
        self.current_task_id = ""
        self._last_task_record: Dict[str, Any] = {}   # Phase 14I：最近一次任务的结构化记录（实例级）

    # -------------------------------------------------- 主循环
    def execute(self, user_request: str, extra_context: Optional[Dict[str, Any]] = None,
                task_auth=None) -> Dict[str, Any]:
        # Phase 14.1.1 §1：**本次 task 独立 AuthorizationContext**（immutable/task-local）。
        # 未显式给（普通自然语言任务）→ 默认 L0/L1 only；L2/L3 deny unless 本 task 有匹配授权。
        if task_auth is None:
            task_auth = self.permission.default_task_context()
        # Phase 14I：stable task_id（C7 精确追踪的事实标识）
        task_id = f"task_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        self.current_task_id = task_id
        self.status = "RUNNING"   # FINAL-R1 §8.1：真实生命周期状态（每个转移都更新）
        self.bus.emit(EventType.AGENT_STARTED,
                      payload={"request": user_request, "task_id": task_id}, source="agent")
        log.info("agent: %s (task=%s auth=%s)", user_request, task_id, task_auth.source)
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
            self.bus.emit(EventType.AGENT_FAILED,
                          payload={"reason": reason, "task_id": task_id}, source="agent")
            self._body("confused")
            self.status = "FAILED"
            self._report_task(task_id, "FAILED", goal=plan.goal, original_request=user_request,
                              verified=False, result_summary="", error=reason,
                              steps=[], artifacts=[], plan_json=self._plan_json(plan),
                              permission_summary="")
            return {"status": "failed", "reason": reason, "results": [],
                    "task_id": task_id, "task_record": self._last_task_record}
        self._body("work")

        results: List[Dict[str, Any]] = []
        steps: List[Dict[str, Any]] = []
        artifacts: List[Dict[str, Any]] = []
        for i, step in enumerate(plan.steps):
            # 未知工具 → 如实失败，绝不崩溃/假装成功（legacy-plan/5 §24）
            try:
                tool = self.tools.get(step.tool)
            except Exception as e:
                self.bus.emit(EventType.AGENT_FAILED,
                              payload={"step": i, "reason": f"unknown_tool:{step.tool}",
                                       "task_id": task_id},
                              source="agent")
                self._body("confused")
                self.status = "FAILED"
                steps.append({"step_index": i, "tool": step.tool, "args": step.args,
                              "capability": "", "permission_level": "",
                              "status": "FAILED", "verified": False, "result": None,
                              "error": f"unknown_tool:{step.tool}"})
                self._report_task(task_id, "FAILED", goal=plan.goal, original_request=user_request,
                                  verified=False, result_summary="", error=str(e),
                                  steps=steps, artifacts=artifacts, plan_json=self._plan_json(plan),
                                  permission_summary="")
                return {"status": "failed", "reason": str(e), "results": results,
                        "task_id": task_id, "task_record": self._last_task_record}
            # 权限检查（Phase 14.1：最终 effective permission + Phase 14.1.1：task-scoped auth）
            eff = self._perm_resolver.effective_permission(tool, step.args)
            step_path = self._path_arg(step.args)
            decision = self.permission.check(f"{tool.description}：{step.args}", eff,
                                             task_auth=task_auth, tool=step.tool,
                                             path=step_path)
            steps.append({"step_index": i, "tool": step.tool, "args": step.args,
                          "capability": "", "permission_level": eff.name,
                          "status": "RUNNING", "verified": False, "result": None, "error": ""})
            if not decision.granted:
                # Phase 14.1 §2：reason 保持旧契约 "permission_denied"（level/source 放 permission_summary）
                self.bus.emit(EventType.AGENT_FAILED,
                              payload={"step": i, "reason": "permission_denied",
                                       "task_id": task_id},
                              source="agent")
                self._body("report")
                self.status = "FAILED"
                steps[-1]["status"] = "FAILED"
                steps[-1]["error"] = "permission_denied"
                self._report_task(task_id, "FAILED", goal=plan.goal, original_request=user_request,
                                  verified=False, result_summary="", error="permission_denied",
                                  steps=steps, artifacts=artifacts, plan_json=self._plan_json(plan),
                                  permission_summary=f"denied:{eff.name}:{decision.reason}")
                return {"status": "failed", "reason": "permission_denied", "results": results,
                        "task_id": task_id, "task_record": self._last_task_record}
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
            steps[-1]["status"] = "COMPLETED_VERIFIED" if (res.ok and verified) else \
                ("UNVERIFIED" if res.ok else "FAILED")
            steps[-1]["verified"] = bool(verified)
            steps[-1]["result"] = self._result_data(res.data)
            steps[-1]["error"] = res.error or ""
            art = self._artifact_from_result(i, step.tool, res)
            if art:
                artifacts.append(art)
            if not res.ok:
                self.bus.emit(EventType.AGENT_FAILED,
                              payload={"step": i, "error": res.error, "task_id": task_id},
                              source="agent")
                self._body("confused")
                self.status = "FAILED"
                self._report_task(task_id, "FAILED", goal=plan.goal, original_request=user_request,
                                  verified=False, result_summary="", error=res.error,
                                  steps=steps, artifacts=artifacts, plan_json=self._plan_json(plan),
                                  permission_summary="")
                return {"status": "failed", "reason": res.error, "results": results,
                        "task_id": task_id, "task_record": self._last_task_record}
            # Phase 13 终审 §10.3：**verified=False 不得 COMPLETED**（ok 只是"没抛错"，不是"完成"）
            if not verified:
                reason = f"unverified_step:{i}:{step.tool}"
                self.bus.emit(EventType.AGENT_FAILED,
                              payload={"step": i, "reason": reason, "task_id": task_id},
                              source="agent")
                self._body("confused")
                self.status = "UNVERIFIED"
                self._report_task(task_id, "UNVERIFIED", goal=plan.goal,
                                  original_request=user_request, verified=False,
                                  result_summary="", error=reason,
                                  steps=steps, artifacts=artifacts, plan_json=self._plan_json(plan),
                                  permission_summary="")
                return {"status": "unverified", "reason": reason, "results": results,
                        "task_id": task_id, "task_record": self._last_task_record}

        self._body("report")
        # Phase 13 终审 §10.6：结构化事实摘要来自**已验证**结果（DialogueBrain 只能角色化事实，不得发明成功）
        ok_verified = [r for r in results if r["ok"] and r["verified"]]
        summary = (f"完成了 {len(ok_verified)}/{len(results)} 个步骤："
                   f"{plan.goal}（已验证 {len(ok_verified)} 步）")
        self.bus.emit(EventType.AGENT_COMPLETED,
                      payload={"goal": plan.goal, "results": results, "summary": summary,
                               "verified": True, "task_id": task_id,
                               "task_record": {"task_id": task_id, "status": "COMPLETED_VERIFIED",
                                               "goal": plan.goal, "verified": True,
                                               "result_summary": summary, "error": "",
                                               "steps": steps, "artifacts": artifacts,
                                               "plan_json": self._plan_json(plan),
                                               "permission_summary": ""}},
                      source="agent")
        self.status = "COMPLETED_VERIFIED"
        self._report_task(task_id, "COMPLETED_VERIFIED", goal=plan.goal,
                          original_request=user_request, verified=True,
                          result_summary=summary, error="",
                          steps=steps, artifacts=artifacts, plan_json=self._plan_json(plan),
                          permission_summary="")
        return {"status": "completed", "goal": plan.goal, "results": results,
                "summary": summary, "task_id": task_id, "task_record": self._last_task_record}

    # -------------------------------------------------- C7 task_record（Phase 14I）
    def _report_task(self, task_id: str, status: str, *, goal: str, original_request: str,
                     verified: bool, result_summary: str, error: str,
                     steps: List[Dict[str, Any]], artifacts: List[Dict[str, Any]],
                     plan_json: str, permission_summary: str) -> None:
        """worker 侧组装结构化 task_record → 交给 owner persist 回调（不直接写 Cognition DB）。"""
        record = {
            "task_id": task_id, "status": status, "goal": goal,
            "original_request": original_request, "verified": verified,
            "result_summary": result_summary, "error": error,
            "steps": steps, "artifacts": artifacts,
            "plan_json": plan_json, "permission_summary": permission_summary,
        }
        self._last_task_record = record
        if self.on_task_finished is not None:
            try:
                self.on_task_finished(record)
            except Exception as e:   # pragma: no cover —— owner persist 失败不影响 Agent 结果
                log.warning("task history persist callback failed: %s", e)

    @staticmethod
    def _path_arg(args: Dict[str, Any]) -> str:
        """从 step args 提取路径（供 task-scoped allowed_path_root 检查）。"""
        for k in ("path", "base", "source", "dest", "target", "file", "new_name"):
            v = (args or {}).get(k)
            if isinstance(v, str) and v.strip():
                return v
        return ""

    @staticmethod
    def _plan_json(plan: AgentPlan) -> str:
        import json
        try:
            return json.dumps({"goal": plan.goal,
                               "steps": [{"tool": s.tool, "args": s.args, "expect": s.expect}
                                         for s in plan.steps]},
                              ensure_ascii=False, default=str)[:2000]
        except Exception:
            return "{}"

    @staticmethod
    def _result_data(data: Any) -> Dict[str, Any]:
        """步骤结果（JSON-safe 摘要；不持久化完整大对象）。"""
        import json
        try:
            s = json.dumps(data, ensure_ascii=False, default=str)[:1000]
            return json.loads(s) if isinstance(data, (dict, list)) else {"summary": s[:300]}
        except Exception:
            return {}

    @staticmethod
    def _artifact_from_result(step_index: int, tool: str, res: ToolResult) -> Optional[Dict[str, Any]]:
        """从已验证工具结果提取 artifact（真实 path + exists_verified=filesystem truth）。"""
        data = res.data
        if not isinstance(data, dict):
            return None
        path = data.get("path") or data.get("dest")      # fs.move 等返回 dest
        if not path or not isinstance(path, str):
            return None
        return {"artifact_type": "file", "path": path, "exists_verified": bool(res.verified),
                "metadata": {"tool": tool, "step_index": step_index,
                             "is_dir": data.get("is_dir", False)}}

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
