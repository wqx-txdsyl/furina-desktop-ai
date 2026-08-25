"""furina/agent/capabilities —— Universal Agent 能力层（Phase 14C）。"""
from .models import Capability, CapabilityRegistry
from .registry import build_capability_registry

__all__ = ["Capability", "CapabilityRegistry", "build_capability_registry"]
