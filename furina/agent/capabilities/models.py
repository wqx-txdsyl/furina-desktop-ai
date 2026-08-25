"""Capability Registry 数据模型（Phase 14C）。

Capability = domain 能力声明；available=false 时必须给 availability_reason。
禁止用假实现"凑齐"domain。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from furina.agent.permission import Permission


@dataclass
class Capability:
    capability_id: str
    domain: str
    description: str = ""
    tools: List[str] = field(default_factory=list)
    read_only: bool = True
    default_permission: Permission = Permission.L0_READ
    requirements: str = ""
    available: bool = True
    availability_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "domain": self.domain,
            "description": self.description,
            "tools": list(self.tools),
            "read_only": self.read_only,
            "default_permission": self.default_permission.name,
            "requirements": self.requirements,
            "available": self.available,
            "availability_reason": self.availability_reason,
        }


class CapabilityRegistry:
    """能力注册表：domain → capability；unavailable 必须显式标原因。"""

    def __init__(self) -> None:
        self._caps: Dict[str, Capability] = {}

    def register(self, cap: Capability) -> None:
        self._caps[cap.capability_id] = cap

    def get(self, capability_id: str) -> Optional[Capability]:
        return self._caps.get(capability_id)

    def all(self) -> List[Capability]:
        return list(self._caps.values())

    def by_domain(self, domain: str) -> List[Capability]:
        return [c for c in self._caps.values() if c.domain == domain]

    def is_available(self, capability_id: str) -> bool:
        c = self._caps.get(capability_id)
        return bool(c and c.available)

    def availability_reason(self, capability_id: str) -> str:
        c = self._caps.get(capability_id)
        return c.availability_reason if c else "unknown_capability"

    def tool_owner(self, tool_name: str) -> Optional[Capability]:
        """tool → 所属 capability（Planner V2 validation 用：tool 必须 exists 且所属 capability available）。"""
        for c in self._caps.values():
            if tool_name in c.tools:
                return c
        return None
