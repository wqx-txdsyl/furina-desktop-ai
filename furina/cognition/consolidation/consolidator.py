"""Event → Memory 最小 Consolidator。

不是所有 event 都变 Memory。单事件单 owner：禁止一次事件多 owner 重复写 memory。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from furina.core import get_logger
from furina.memory import MemoryLevel, MemorySource

log = get_logger("cognition.consolidator")

# 仅事件（不进 memory）的类型
_EVENT_ONLY = {"ACTIVITY_STARTED", "ACTIVITY_FINISHED", "FURINA_SPOKE", "DIRECT_TURN_STARTED",
               "USER_CLICK", "USER_DRAG", "SYSTEM_EVENT", "APP_LAUNCHED", "BROWSER_OPENED",
               "USER_STATEMENT_OBSERVED"}

# 可能形成 memory 的显著类型（仍需 importance 门槛）
_SIGNIFICANT = {"USER_PET", "USER_POKE", "USER_FEED", "AGENT_COMPLETED", "AGENT_FAILED",
                "USER_PLAN_DECLARED", "USER_PREFERENCE_DECLARED", "FILE_CREATED",
                "FILE_MOVED", "DOCUMENT_CREATED", "RELATIONSHIP_MILESTONE", "MEMORY_FORMED"}


class Consolidator:
    """确定性 consolidation 决策（LLM 不参与）。

    输出 plan：{"events": [...], "form_memory": bool, "memory": {...} | None,
               "user_model": {...} | None, "milestone": {...} | None}
    """

    def __init__(self, memory_threshold: float = 0.45) -> None:
        self._threshold = memory_threshold

    def consider(self, event_type: str, *, payload: Optional[Dict[str, Any]] = None,
                 importance: float = 0.0, verified: bool = False,
                 source_event_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        p = dict(payload or {})
        src = list(source_event_ids or [])
        plan: Dict[str, Any] = {"events": [event_type], "form_memory": False,
                                "memory": None, "user_model": None, "milestone": None}
        if event_type in _EVENT_ONLY:
            return plan                       # 普通事件 → Event only
        if event_type not in _SIGNIFICANT:
            return plan
        # 显著事件：按类型给确定性处理
        if event_type == "USER_PET":
            if importance >= self._threshold or p.get("strong", False):
                plan["form_memory"] = True
                plan["memory"] = {"content": "用户轻轻摸了摸我的头", "level": MemoryLevel.EPISODIC,
                                  "source": MemorySource.INTERACTION, "importance": 0.5,
                                  "event_type": "user_positive_touch",
                                  "source_event_ids": src}
        elif event_type == "USER_FEED":
            # Phase 15.1：喂食 → C6 → consolidation → 可选 C3（单一形成权威，带 provenance）
            if importance >= self._threshold:
                plan["form_memory"] = True
                plan["memory"] = {"content": f"用户喂了我{p.get('food', '')}",
                                  "level": MemoryLevel.EPISODIC,
                                  "source": MemorySource.INTERACTION, "importance": 0.5,
                                  "event_type": "user_feed", "outcome": p.get("outcome", ""),
                                  "source_event_ids": src}
        elif event_type == "AGENT_COMPLETED":
            # Agent 成功完成重要任务 → Event + AgentTask(C7) + 可形成 episodic memory
            if verified and (importance >= self._threshold or bool(p.get("goal"))):
                plan["form_memory"] = True
                plan["memory"] = {"content": f"我帮用户完成了：{p.get('goal', '')}",
                                  "level": MemoryLevel.EPISODIC, "source": MemorySource.AGENT_TASK,
                                  "importance": 0.55, "outcome": p.get("goal", ""),
                                  "event_type": "help_success",
                                  "source_event_ids": src}
        elif event_type == "AGENT_FAILED":
            if importance >= self._threshold:
                plan["form_memory"] = True
                plan["memory"] = {"content": f"帮用户处理{ p.get('request','') }时失败了",
                                  "level": MemoryLevel.EPISODIC, "source": MemorySource.AGENT_TASK,
                                  "importance": 0.45, "event_type": "help_failure",
                                  "source_event_ids": src}
        elif event_type == "USER_PLAN_DECLARED":
            # 明确用户计划 → Event + UserModel PLAN + 可形成 memory
            plan["user_model"] = {"category": "PLAN", "key": p.get("key", "plan"),
                                  "value": p.get("value", ""), "confidence": p.get("confidence", 0.8),
                                  "excerpt": p.get("excerpt", "")}
            if importance >= self._threshold:
                plan["form_memory"] = True
                plan["memory"] = {"content": f"用户今天准备：{p.get('value', '')}",
                                  "level": MemoryLevel.EPISODIC, "source": MemorySource.USER_EXPLICIT,
                                  "importance": 0.55, "event_type": "user_plan",
                                  "source_event_ids": src}
        elif event_type == "USER_PREFERENCE_DECLARED":
            plan["user_model"] = {"category": p.get("category", "PREFERENCE"),
                                  "key": p.get("key", ""), "value": p.get("value", ""),
                                  "confidence": p.get("confidence", 0.7),
                                  "excerpt": p.get("excerpt", "")}
        elif event_type == "RELATIONSHIP_MILESTONE":
            plan["milestone"] = {"type": p.get("type", ""), "note": p.get("note", ""),
                                 "source_event_ids": src}
        elif event_type in ("FILE_CREATED", "FILE_MOVED", "DOCUMENT_CREATED"):
            if importance >= self._threshold:
                plan["form_memory"] = True
                plan["memory"] = {"content": p.get("summary", event_type),
                                  "level": MemoryLevel.EPISODIC, "source": MemorySource.AGENT_TASK,
                                  "importance": 0.5, "event_type": "agent_file_op",
                                  "source_event_ids": src}
        return plan
