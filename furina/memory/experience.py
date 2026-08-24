"""Experience 与 Memory Importance（Phase 07）。

Experience = 一次值得考虑的"经历"（来自互动/行为/World/情绪）。
Importance 确定性评估（不用 LLM）：emotional_intensity / relationship_relevance /
identity_relevance / novelty / user_relevance / outcome_significance / recurrence。

关键：Importance ≠ Emotion；低情绪也可能高重要（如用户首次求助）。
Consolidation：Experience → Memory（去噪/结构化/压缩/tag/dedup/reinforce/capacity）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from furina.memory.memory_types import Memory, MemoryLevel, MemorySource


@dataclass
class Experience:
    token: str                      # 事件 key（用于 dedup）
    event_type: str                 # user_rejection / help_success / ...
    summary: str                    # 结构化摘要（模板）
    world_context: str = ""         # coding / idle / browsing ...
    activity: str = ""
    outcome: str = ""               # success / failure / neutral
    # 评估因子（0..1）
    emotional_intensity: float = 0.3
    relationship_relevance: float = 0.3
    identity_relevance: float = 0.2
    novelty: float = 0.3
    user_relevance: float = 0.3
    outcome_significance: float = 0.3
    recurrence: float = 0.0
    # 关系维度快照（供 debug，不用于 Memory 更新 Relationship）
    relationship_snapshot: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------- Importance（确定性）
IMPORTANCE_WEIGHTS = {
    "emotional_intensity": 0.22,
    "relationship_relevance": 0.24,
    "identity_relevance": 0.18,
    "novelty": 0.12,
    "user_relevance": 0.12,
    "outcome_significance": 0.12,
}


def importance_of(e: Experience) -> float:
    """确定性重要性 0..1（§5-6：不等于纯 Emotion）。"""
    s = sum(IMPORTANCE_WEIGHTS[k] * getattr(e, k) for k in IMPORTANCE_WEIGHTS)
    return max(0.0, min(1.0, s))


# ---------------------------------------------------------------- 事件模板
def template_summary(event_type: str, world_context: str = "", activity: str = "", outcome: str = "") -> str:
    """结构化模板摘要（第 8 节：不追求漂亮自然语言）。"""
    m = {
        "user_rejection": f"用户在{world_context or '当时'}拒绝了主动{activity or '互动'}",
        "user_ignore": f"用户忽略了我（{world_context or '当时'}）",
        "user_positive_response": f"用户{world_context or '当时'}积极回应了我",
        "user_initiated": f"用户主动找我（{world_context or '当时'}）",
        "help_success": f"成功帮用户完成了一件事",
        "help_failure": f"想帮忙但没成功",
        "activity_success": f"我自己完成了一件重要的事：{activity}",
        "activity_failure": f"{activity}没弄好",
        "praise": f"用户夸赞了我（{world_context or '当时'}）",
        "user_returned": f"用户离开后回来了",
        "user_left": f"用户离开了一会儿",
        "long_focus": f"用户长时间专注工作（{world_context}）",
        "first_help_request": "用户第一次请我帮忙",
    }
    base = m.get(event_type, f"发生了{event_type}{f'（{world_context}）' if world_context else ''}")
    if outcome == "success":
        base += "，结果不错"
    elif outcome == "failure":
        base += "，结果不顺"
    return base


# ---------------------------------------------------------------- Event key（dedup §9）
def event_key(event_type: str, world_context: str = "", activity: str = "") -> str:
    return f"{event_type}|{world_context}|{activity}"
