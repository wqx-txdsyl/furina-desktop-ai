"""记忆类型（legacy-plan/6）。

记忆不是聊天记录；观察 ≠ 记忆（legacy-plan/6 §38）。每条记忆有 source/importance/confidence。
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class MemoryLevel(str, enum.Enum):
    IDENTITY = "identity"        # 你是谁/我是谁
    SEMANTIC = "semantic"        # 我知道什么（压缩知识）
    EPISODIC = "episodic"        # 我们经历过什么
    RELATIONSHIP = "relationship"  # 我们变成什么关系
    WORKING = "working"          # 短期工作上下文（不落库）


class MemorySource(str, enum.Enum):
    USER_EXPLICIT = "user_explicit"
    CONVERSATION = "conversation"
    INTERACTION = "interaction"
    BEHAVIOR = "behavior"
    COMPUTER_OBSERVATION = "computer_observation"
    AGENT_TASK = "agent_task"
    SYSTEM = "system"
    INFERENCE = "inference"


class MemoryStatus(str, enum.Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"     # 被纠正，仍保留历史（legacy-plan/6 §33）
    ARCHIVED = "archived"


@dataclass
class Memory:
    level: MemoryLevel
    content: str
    source: MemorySource = MemorySource.SYSTEM
    importance: float = 0.5
    confidence: float = 0.5
    timestamp: float = field(default_factory=time.time)
    # 事件记忆附加字段（legacy-plan/6 §23）
    context: str = ""
    outcome: str = ""
    participants: str = ""
    # 生命周期（legacy-plan/6 §10-11）
    strength: float = 0.6
    last_recalled: float = 0.0
    last_reinforced: float = 0.0
    # 时间有效性（legacy-plan/6 §34）
    valid_from: float = 0.0
    valid_to: Optional[float] = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    # 关系维度影响（legacy-plan/6 §18）
    relationship_delta: Dict[str, float] = field(default_factory=dict)
    embedding: list = field(default_factory=list)
    mem_id: str = ""
    # Phase 07：结构化长期记忆扩展
    tags: list = field(default_factory=list)          # 语义 tag（world/source/type）
    event_type: str = ""                              # user_rejection / help_success / ...
    world_context: str = ""                           # coding / idle / browsing ...
    recurrence_count: int = 0                         # 相似经历合并计数
    summary: str = ""                                 # 结构化摘要（模板生成）

    def to_row(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["level"] = self.level.value
        d["source"] = self.source.value
        d["status"] = self.status.value
        return d


@dataclass
class RelationshipState:
    """关系是多维的，不是单一好感度（legacy-plan/6 §18）。

    Phase 04：区分**短期状态**（变化快、恢复快）与**长期关系**（变化慢、需积累）。
    - 短期：annoyance / interaction_tolerance / social_confidence
    - 长期：familiarity / trust / comfort
    允许出现 familiarity=high & trust=high & annoyance=high（很熟、很信任但此刻很烦）。
    """

    familiarity: float = 0.0
    trust: float = 0.0
    comfort: float = 0.0
    attachment: float = 0.0
    respect: float = 0.0
    dependency: float = 0.0
    annoyance: float = 0.0
    # 短期状态（Phase 04 新）
    interaction_tolerance: float = 50.0   # 用户对主动的接纳度（0=不接纳，100=很接纳）
    social_confidence: float = 40.0       # 她自己敢主动的信心（0=不敢，100=很敢）
    # 动态互动统计（P2 §12）
    interaction_count_1h: float = 0.0
    interaction_count_24h: float = 0.0
    interaction_days_7d: float = 0.0
    user_response_rate: float = 0.5
    user_rejection_rate: float = 0.0
    rejection_count: float = 0.0
    last_interaction_ts: float = 0.0

    def apply(self, delta: Dict[str, float]) -> None:
        for k, v in delta.items():
            if hasattr(self, k):
                setattr(self, k, max(0.0, min(100.0, float(getattr(self, k)) + v)))

    def as_dict(self) -> Dict[str, float]:
        return {k: round(v, 2) for k, v in self.__dict__.items()}
