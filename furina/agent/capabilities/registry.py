"""Capability Registry 构建（Phase 14C）。

从现有 ToolRegistry 自动注册可用 tools + 手工声明 provider 类能力（unavailable 显式标原因）。
"""
from __future__ import annotations

from typing import List, Optional

from furina.agent.permission import Permission
from furina.agent.tool import ToolRegistry
from .models import Capability, CapabilityRegistry

# 既有 tools 的 domain 归属（工具 → capability_id）
_TOOL_OWNER: dict = {}


def _register_tool_caps(registry: CapabilityRegistry, tools: ToolRegistry) -> None:
    """按既有工具名 → domain 注册可用能力（available=true，reason=''）。"""
    known = {
        "FILESYSTEM": ["fs.list_dir", "fs.make_dirs", "fs.read_file", "fs.organize",
                       "fs.exists", "fs.stat", "fs.search", "fs.create_file", "fs.write_text",
                       "fs.append_text", "fs.replace_text", "fs.copy", "fs.move", "fs.rename",
                       "fs.create_dir", "fs.open_path", "fs.delete"],
        "DOCUMENTS": ["doc.create", "doc.read", "doc.write", "doc.append", "doc.edit",
                      "docx.create", "pptx.create", "xlsx.create"],
        "BROWSER": ["browser.open", "browser.search"],
        "DESKTOP": ["computer.screenshot", "desktop.active_window", "desktop.list_windows"],
        "APPLICATIONS": ["app.launch"],
    }
    for domain, tool_names in known.items():
        present = [t for t in tool_names if _tool_exists(tools, t)]
        cap_id = f"cap.{domain.lower()}"
        read_only = domain in ("BROWSER", "DESKTOP")
        perm = Permission.L0_READ if read_only else Permission.L1_LOW_WRITE
        if present:
            registry.register(Capability(
                capability_id=cap_id, domain=domain,
                description=f"{domain} 能力（已注册 {len(present)} 个工具）",
                tools=present, read_only=read_only, default_permission=perm,
                requirements="", available=True, availability_reason=""))
        else:
            registry.register(Capability(
                capability_id=cap_id, domain=domain,
                description=f"{domain} 能力（无可用工具）",
                tools=[], read_only=read_only, default_permission=perm,
                requirements="至少一个工具", available=False,
                availability_reason="no_tools_registered"))
        for t in present:
            _TOOL_OWNER[t] = cap_id


def _tool_exists(tools: ToolRegistry, name: str) -> bool:
    try:
        tools.get(name)
        return True
    except Exception:
        return False


def _register_provider_caps(registry: CapabilityRegistry, providers: Optional[dict] = None) -> None:
    """Provider 类能力：没有 provider → available=false, reason=provider_not_configured。"""
    providers = providers or {}
    comm = providers.get("communication")
    cal = providers.get("calendar")
    registry.register(Capability(
        capability_id="cap.communication", domain="COMMUNICATION",
        description="查消息/起草/发送（provider 接口）",
        tools=["comm.list_accounts", "comm.list_conversations", "comm.read_messages",
               "comm.draft_message", "comm.send_message"],
        read_only=False, default_permission=Permission.L3_SENSITIVE,
        requirements="CommunicationProvider 已配置",
        available=comm is not None,
        availability_reason="" if comm is not None else "provider_not_configured"))
    registry.register(Capability(
        capability_id="cap.calendar", domain="CALENDAR",
        description="日历查询/创建/更新（provider 接口）",
        tools=["calendar.list_calendars", "calendar.list_events", "calendar.create_event",
               "calendar.update_event"],
        read_only=False, default_permission=Permission.L2_HIGH_RISK,
        requirements="CalendarProvider 已配置",
        available=cal is not None,
        availability_reason="" if cal is not None else "provider_not_configured"))
    registry.register(Capability(
        capability_id="cap.research", domain="RESEARCH",
        description="知识检索/研究（本 Phase 无独立 provider）",
        tools=[], read_only=True, default_permission=Permission.L0_READ,
        requirements="research provider",
        available=False, availability_reason="provider_not_configured"))
    # Browser DOM automation 无稳定 provider → unavailable（不得假装已浏览网页）
    registry.register(Capability(
        capability_id="cap.browser_dom", domain="BROWSER",
        description="浏览器 DOM 自动化（点击/提取）——本 Phase 无稳定 provider",
        tools=[], read_only=False, default_permission=Permission.L2_HIGH_RISK,
        requirements="browser DOM/control provider",
        available=False, availability_reason="provider_not_configured"))


def build_capability_registry(tools: ToolRegistry,
                              providers: Optional[dict] = None) -> CapabilityRegistry:
    """构建完整 CapabilityRegistry（tools 自动 + providers 显式）。"""
    reg = CapabilityRegistry()
    _register_tool_caps(reg, tools)
    _register_provider_caps(reg, providers)
    return reg


def register_tool_capability(registry: CapabilityRegistry, capability_id: str,
                             domain: str, description: str, tools: List[str], *,
                             read_only: bool, default_permission: Permission,
                             available: bool, availability_reason: str = "") -> None:
    """外部扩展点：注册自定义 capability。"""
    registry.register(Capability(
        capability_id=capability_id, domain=domain, description=description,
        tools=list(tools), read_only=read_only, default_permission=default_permission,
        requirements="", available=available, availability_reason=availability_reason))
