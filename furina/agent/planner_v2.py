"""Planner V2（Phase 14C）—— Universal Agent 规划层。

- LLM 只能产生 goal / steps[{tool, args, expect}]，**不能执行工具**；
- deterministic validation：tool exists / capability available / required args / max steps /
  permission admissible / path validation / 无未知字段；引用未知 tool → plan invalid（**不自动替换**）；
- LLM 不可用/失败 → deterministic fallback（记事本/计算器/整理目录仍工作，不依赖 LLM availability）。

Planner V2 使用项目现有 LLM adapter（furina/llm），不新造独立模型配置。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from furina.core import get_logger
from furina.llm import LLMAdapter
from .capabilities.models import CapabilityRegistry
from .permission import Permission
from .planner import AgentPlan, AgentStep, Planner, _guess_app
from .tool import ToolRegistry

log = get_logger("agent.planner_v2")

MAX_STEPS = 8

_PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "args": {"type": "object"},
                    "expect": {"type": "string"},
                },
                "required": ["tool"],
            },
        },
    },
    "required": ["goal", "steps"],
}

# 默认许可域：用户主动发起任务允许到 L2（L3 敏感需确认，由 PermissionManager 执行期把关）
_DEFAULT_ALLOWED_PERMISSION = Permission.L2_HIGH_RISK


class PlannerV2(Planner):
    """LLM 结构化计划 + deterministic validation + 确定性 fallback。"""

    def __init__(self, tools: ToolRegistry, registry: Optional[CapabilityRegistry] = None,
                 llm: Optional[LLMAdapter] = None, max_steps: int = MAX_STEPS) -> None:
        super().__init__(tools)
        self.registry = registry
        self.llm = llm
        self.max_steps = max_steps

    # -------------------------------------------------- 主入口
    def build_plan(self, user_request: str, context: Optional[Dict[str, Any]] = None) -> AgentPlan:
        context = context or {}
        # 1) LLM 计划（若可用）→ 必须通过 deterministic validation
        if self.llm is not None:
            try:
                if self.llm.is_available():
                    llm_plan = self._llm_plan(user_request, context)
                    if llm_plan is not None and self._validate(llm_plan, context):
                        return llm_plan
                    log.info("planner_v2: LLM plan 无效/不可行，走 fallback: %s", user_request)
                else:
                    log.info("planner_v2: LLM unavailable，走 deterministic fallback")
            except Exception as e:
                log.warning("planner_v2: LLM 计划失败(%s)，走 fallback", e)
        # 2) deterministic fallback（旧确定性能力：记事本/计算器/整理目录等）
        return self._fallback_plan(user_request, context)

    # -------------------------------------------------- LLM 结构化输出
    def _llm_plan(self, user_request: str, context: Dict[str, Any]) -> Optional[AgentPlan]:
        # BaseTool.schema 可能是裸 dataclasses.Field（类级缺省）→ 防御性转 dict
        def _safe_schema(s: Any) -> Dict[str, Any]:
            if isinstance(s, dict):
                return s
            return {}
        tools = [{"name": t.name, "description": t.description, "schema": _safe_schema(t.schema)}
                 for t in self.tools._tools.values()]
        caps = ""
        if self.registry is not None:
            caps = "\n".join(
                f"- {c.capability_id} [{c.domain}] available={c.available}"
                f"{'' if c.available else ' reason=' + c.availability_reason}"
                for c in self.registry.all())
        sys = (
            "你是芙宁娜的 Agent 规划器。你只输出 JSON 计划，绝不执行任何工具。\n"
            "可用工具:\n" + json.dumps(tools, ensure_ascii=False) + "\n"
            "能力可用性:\n" + caps + "\n"
            "规则:\n"
            "- 只能引用上面列出的真实工具名；未知工具 → 直接输出空 steps（unable）。\n"
            "- 不要自动替换成类似工具。\n"
            "- 不要包含删除/覆盖等破坏性步骤，除非用户明确要求。\n"
            "- args 必须满足工具 schema；expect 写可验证的预期结果。\n"
            "- 最多 " + str(self.max_steps) + " 步。\n"
            "- 只输出 JSON（不要 markdown 代码块）。"
        )
        from furina.llm.base import LLMMessage, content
        messages = [
            LLMMessage(role="system", content=content(sys)),
            LLMMessage(role="user", content=content(f"用户请求：{user_request}")),
        ]
        raw = self.llm.structured(messages, schema=_PLAN_SCHEMA, temperature=0.0)
        if not isinstance(raw, dict):
            return None
        steps = []
        for s in raw.get("steps") or []:
            if not isinstance(s, dict):
                continue
            steps.append(AgentStep(
                tool=str(s.get("tool", "")),
                args=dict(s.get("args") or {}),
                expect=str(s.get("expect", "") or ""),
            ))
        if not steps:
            return AgentPlan(goal=str(raw.get("goal", user_request)),
                             status="unable",
                             constraints=["LLM 未产出可用步骤"])
        return AgentPlan(goal=str(raw.get("goal", user_request)), steps=steps)

    # -------------------------------------------------- deterministic validation
    def _validate(self, plan: AgentPlan, context: Dict[str, Any]) -> bool:
        if not plan.steps or len(plan.steps) > self.max_steps:
            return False
        allowed_perm = context.get("allowed_permission", _DEFAULT_ALLOWED_PERMISSION)
        for step in plan.steps:
            # 1) tool exists
            try:
                tool = self.tools.get(step.tool)
            except Exception:
                log.info("planner_v2 validation: 未知 tool %s（不自动替换）", step.tool)
                return False
            # 2) capability available
            if self.registry is not None:
                cap = self.registry.tool_owner(step.tool)
                if cap is not None and not cap.available:
                    log.info("planner_v2 validation: capability %s unavailable", cap.capability_id)
                    return False
            # 3) args 必须 dict
            if not isinstance(step.args, dict):
                return False
            # 4) required args（按 tool schema）
            req = (tool.schema or {}).get("required") or []
            for r in req:
                if r not in step.args:
                    log.info("planner_v2 validation: 缺 required arg %s", r)
                    return False
            # 5) permission admissible
            if tool.permission.value > allowed_perm.value:
                log.info("planner_v2 validation: tool %s 权限 %s 超出允许 %s",
                         step.tool, tool.permission, allowed_perm)
                return False
            # 6) path validation：args 里的路径必须是字符串（不自动展开任意对象）
            for k, v in step.args.items():
                if k in ("path", "base", "source", "dest", "target", "file"):
                    if not isinstance(v, str) or not v.strip():
                        return False
        return True

    # -------------------------------------------------- deterministic fallback
    def _fallback_plan(self, user_request: str, context: Dict[str, Any]) -> AgentPlan:
        """LLM 不可用/失败时的确定性计划（与旧 Planner 行为一致：记事本/计算器/整理目录）。"""
        return super().build_plan(user_request, context)


def guess_app_fallback(text: str) -> Optional[str]:
    """确定性应用猜测（fallback 用；未知 → None，绝不默认 notepad）。"""
    return _guess_app(text)
