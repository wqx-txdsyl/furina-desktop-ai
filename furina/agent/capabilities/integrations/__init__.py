"""Communication / Calendar provider 接口（Phase 14H）。

- 正式 provider 契约；**没有 provider → capability unavailable**，绝不 mock 成成功；
- 权限：read → L0 或用户配置 read scope；draft → L1；send → **L3 SENSITIVE**；
  create/update external calendar → L2/L3；
- 本 Phase 不要求真正接通微信/钉钉；留 Gmail / Outlook / DingTalk 等 integration point。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ================================================================ 通用结果（provider 层）
@dataclass
class ProviderResult:
    ok: bool
    data: Any = None
    error: str = ""
    verified: bool = False


# ================================================================ CommunicationProvider
class CommunicationProvider(ABC):
    """消息/邮件 provider 契约（send 为 L3 SENSITIVE，必须有显式授权）。"""

    provider_id: str = ""

    @abstractmethod
    def list_accounts(self) -> ProviderResult: ...

    @abstractmethod
    def list_conversations(self, account: str = "", limit: int = 20) -> ProviderResult: ...

    @abstractmethod
    def read_messages(self, conversation_id: str, limit: int = 20) -> ProviderResult: ...

    @abstractmethod
    def draft_message(self, to: str, subject: str = "", body: str = "") -> ProviderResult:
        """起草（L1）；不发送。"""

    @abstractmethod
    def send_message(self, to: str, subject: str = "", body: str = "") -> ProviderResult:
        """发送（L3 SENSITIVE）；未授权/未配置 → ProviderResult(ok=False)。"""


# ================================================================ CalendarProvider
class CalendarProvider(ABC):
    """日历 provider 契约（create/update external → L2/L3）。"""

    provider_id: str = ""

    @abstractmethod
    def list_calendars(self) -> ProviderResult: ...

    @abstractmethod
    def list_events(self, calendar_id: str = "", start: Optional[str] = None,
                    end: Optional[str] = None, limit: int = 20) -> ProviderResult: ...

    @abstractmethod
    def create_event(self, calendar_id: str, summary: str, start: str, end: str,
                     description: str = "") -> ProviderResult: ...

    @abstractmethod
    def update_event(self, calendar_id: str, event_id: str,
                     changes: Dict[str, Any]) -> ProviderResult: ...


# ================================================================ ProviderRegistry
class ProviderRegistry:
    """provider 注册表：communication / calendar（没有 → None，capability 标 unavailable）。"""

    def __init__(self) -> None:
        self.communication: Optional[CommunicationProvider] = None
        self.calendar: Optional[CalendarProvider] = None

    def register_communication(self, provider: CommunicationProvider) -> None:
        self.communication = provider

    def register_calendar(self, provider: CalendarProvider) -> None:
        self.calendar = provider

    def as_dict(self) -> Dict[str, Any]:
        return {"communication": self.communication, "calendar": self.calendar}
