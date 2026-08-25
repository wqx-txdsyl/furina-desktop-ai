"""Agent 工具层（legacy-plan/5 §10）。

所有工具遵循 Observe → Plan → Act → Verify → Reflect；重要操作必须 Verify（§5）。
优先结构化，截图视觉为后备（§6）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from furina.core import AgentError
from .permission import Permission


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str = ""
    verified: bool = False            # 是否经过 Verify（§5 铁律）
    note: str = ""


class BaseTool:
    name: str = ""
    description: str = ""
    permission: Permission = Permission.L0_READ
    # 结构化参数 schema（供 LLM 工具调用约束）
    schema: Dict[str, Any] = field(default_factory=dict)

    @property
    def verify(self) -> bool:
        """该工具是否需要显式验证结果（agent.runtime 会强制）。"""
        return True

    def run(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise AgentError(f"未知工具: {name}（已注册: {list(self._tools)}）")
        return self._tools[name]

    def list(self) -> List[str]:
        return list(self._tools)

    def structured_defs(self) -> List[Dict[str, Any]]:
        return [{"name": t.name, "description": t.description, "schema": t.schema}
                for t in self._tools.values()]
