"""Cognitive 层数据模型（Phase 14B）。

7 个逻辑 Store 的共享 dataclass 契约。权威说明见 docs/architecture/COGNITIVE_ARCHITECTURE.md。

关键原则：
- objective_summary（发生了什么）与 inferred_inner_state（推断如何理解）必须分字段；
- furina_knew / furina_did_not_know 表达"当时的信息边界"；
- Canon 数据 runtime read-only；用户数据（UserModel/LifeEvent/AgentTask）走 SQLite。
"""
from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ================================================================ C2 Canon Episode
@dataclass
class CanonEpisode:
    """C2 单一 episode：客观经历 + 当时信息边界 + 心理影响 + 现在影响（结构化推导）。"""

    episode_id: str
    timeline_order: int = 0
    period: str = ""
    life_stage: str = ""                # Phase 15A：人生阶段标识（与 episode_id 对齐）
    version: str = ""
    quest: str = ""
    act: str = ""
    scene: str = ""
    objective_summary: str = ""
    furina_role_at_time: str = ""
    furina_knew: List[str] = field(default_factory=list)
    furina_did_not_know: List[str] = field(default_factory=list)
    people_present: List[str] = field(default_factory=list)
    relationship_context: List[str] = field(default_factory=list)
    social_context: List[str] = field(default_factory=list)
    external_demands: List[str] = field(default_factory=list)
    actions_taken: List[str] = field(default_factory=list)
    choices: List[str] = field(default_factory=list)
    expressed_emotions: List[str] = field(default_factory=list)
    inferred_inner_state: List[str] = field(default_factory=list)
    immediate_consequences: List[str] = field(default_factory=list)
    psychological_effects: List[str] = field(default_factory=list)
    belief_effects: List[str] = field(default_factory=list)
    coping_strategies: List[str] = field(default_factory=list)
    present_day_effects: List[str] = field(default_factory=list)
    trigger_topics: List[str] = field(default_factory=list)
    explicit_recall_policy: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)
    confidence: str = "medium"          # low / medium / high
    canon_status: str = "canonical"     # canonical / derived / partial / unknown
    status: str = ""                    # Phase 15A：数据状态别名（partial/unknown 等）

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CanonEpisode":
        known = {f for f in cls.__dataclass_fields__}  # noqa: SIM118
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> Dict[str, Any]:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


# ================================================================ C4 User Model
@dataclass
class UserModelItem:
    """C4 单条用户模型 item（evidence + confidence；supersede 不 overwrite）。"""

    item_id: str = ""
    category: str = "FACT"              # FACT/PREFERENCE/DISLIKE/ROUTINE/PROJECT/GOAL/PLAN/
                                        # COMMUNICATION_PREFERENCE/IMPORTANT_DATE/HABIT/INTEREST
    key: str = ""
    value_json: str = "{}"              # JSON-safe
    confidence: float = 0.5
    source_event_id: str = ""
    source_text_excerpt: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    valid_from: float = 0.0
    valid_to: float = 0.0               # 0 = 永久有效
    status: str = "active"              # active/superseded/expired/deleted/completed/cancelled
    # Phase 15D：temporal scope（日期不确定时 temporal_uncertain=1，绝不编日期）
    temporal_uncertain: int = 0
    declared_at: float = 0.0
    # Phase 14 Final Closure：lifecycle transition provenance ——
    # supersede/complete 的 canonical C6 trigger event id + 原因（触发 utterance 摘录）
    transition_event_id: str = ""
    transition_reason: str = ""
    # Phase 15 D4：结构化确定性时间语义（JSON 字符串；空=无时间语义）。
    # 解析仅在 canonical ingress 一次完成，重启后绝不重解释。Uncertainty 走
    # temporal_uncertain 列，不塞进本 JSON。
    temporal_json: str = ""

    @property
    def value(self) -> Any:
        try:
            return json.loads(self.value_json)
        except Exception:
            return None

    @property
    def temporal_payload(self) -> Dict[str, Any]:
        """解析 temporal_json → dict；损坏/为空返回 {}（fail-closed，不臆造）。"""
        if not self.temporal_json:
            return {}
        try:
            data = json.loads(self.temporal_json)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @classmethod
    def from_row(cls, row) -> "UserModelItem":
        keys = row.keys()
        return cls(
            item_id=row["item_id"], category=row["category"], key=row["key"],
            value_json=row["value_json"], confidence=float(row["confidence"] or 0.0),
            source_event_id=row["source_event_id"], source_text_excerpt=row["source_text_excerpt"],
            created_at=float(row["created_at"] or 0.0), updated_at=float(row["updated_at"] or 0.0),
            valid_from=float(row["valid_from"] or 0.0), valid_to=float(row["valid_to"] or 0.0),
            status=row["status"],
            temporal_uncertain=int(row["temporal_uncertain"] or 0)
            if "temporal_uncertain" in keys else 0,
            declared_at=float(row["declared_at"] or 0.0)
            if "declared_at" in keys else 0.0,
            transition_event_id=row["transition_event_id"] or ""
            if "transition_event_id" in keys else "",
            transition_reason=row["transition_reason"] or ""
            if "transition_reason" in keys else "",
            temporal_json=(row["temporal_json"] or "")
            if "temporal_json" in keys else "",
        )


# ================================================================ C6 Life Event
@dataclass
class LifeEvent:
    """C6 单条客观事件（append-only ledger；payload 必须 JSON-safe、无 interpretation）。"""

    event_id: str = ""
    event_type: str = ""
    timestamp_wall: float = 0.0
    timestamp_monotonic_session: float = 0.0
    session_id: str = ""
    source: str = ""
    actor: str = ""
    channel: str = ""
    turn_id: Optional[int] = None
    task_id: str = ""
    payload_json: str = "{}"
    importance: float = 0.0
    created_at: float = 0.0

    @property
    def payload(self) -> Dict[str, Any]:
        try:
            return json.loads(self.payload_json)
        except Exception:
            return {}

    @classmethod
    def from_row(cls, row) -> "LifeEvent":
        return cls(
            event_id=row["event_id"], event_type=row["event_type"],
            timestamp_wall=float(row["timestamp_wall"] or 0.0),
            timestamp_monotonic_session=float(row["timestamp_monotonic_session"] or 0.0),
            session_id=row["session_id"], source=row["source"], actor=row["actor"],
            channel=row["channel"],
            turn_id=row["turn_id"] if row["turn_id"] is not None else None,
            task_id=row["task_id"] or "", payload_json=row["payload_json"],
            importance=float(row["importance"] or 0.0), created_at=float(row["created_at"] or 0.0),
        )


# ================================================================ C7 Agent Task History
@dataclass
class AgentTask:
    """C7 单条 agent 任务记录（verified 事实，来自真实执行/Verify）。"""

    task_id: str = ""
    original_request: str = ""
    goal: str = ""
    status: str = "PLANNED"             # PLANNED/RUNNING/COMPLETED_VERIFIED/FAILED/UNVERIFIED/CANCELLED
    started_at: float = 0.0
    finished_at: float = 0.0
    permission_summary: str = ""
    plan_json: str = "{}"
    verified: bool = False
    result_summary: str = ""
    error: str = ""

    @classmethod
    def from_row(cls, row) -> "AgentTask":
        return cls(
            task_id=row["task_id"], original_request=row["original_request"],
            goal=row["goal"] or "", status=row["status"],
            started_at=float(row["started_at"] or 0.0), finished_at=float(row["finished_at"] or 0.0),
            permission_summary=row["permission_summary"] or "",
            plan_json=row["plan_json"] or "{}", verified=bool(row["verified"]),
            result_summary=row["result_summary"] or "", error=row["error"] or "",
        )


@dataclass
class AgentTaskStep:
    """C7 单步执行记录（args 写库前必须 redaction）。"""

    task_id: str = ""
    step_index: int = 0
    capability: str = ""
    tool: str = ""
    args_redacted_json: str = "{}"
    permission_level: str = ""
    status: str = "PLANNED"             # PLANNED/RUNNING/COMPLETED_VERIFIED/FAILED/UNVERIFIED
    verified: bool = False
    result_json: str = "{}"
    error: str = ""


@dataclass
class AgentArtifact:
    """C7 单条 artifact（exists_verified 必须来自 filesystem truth）。"""

    task_id: str = ""
    artifact_type: str = ""
    path: str = ""
    exists_verified: bool = False
    metadata_json: str = "{}"


# ================================================================ Cognitive Context（assembler 输出）
@dataclass
class CognitiveContext:
    """ContextAssembler 输出：plain immutable 快照（bounded）。权威顺序见架构文档 §3。"""

    current_facts: Dict[str, Any] = field(default_factory=dict)      # CURRENT FACT（最高）
    recent_events: List[LifeEvent] = field(default_factory=list)     # ≤5 RECENT EVENT
    relevant_agent_tasks: List[AgentTask] = field(default_factory=list)  # ≤2 AGENT TASK FACT
    user_model_items: List[UserModelItem] = field(default_factory=list)  # ≤5 USER MODEL FACT
    autobiographical_memories: List[str] = field(default_factory=list)   # ≤3 AUTOBIO MEMORY
    canon_identity: Dict[str, Any] = field(default_factory=dict)        # C1 只读视图
    relevant_canon_episodes: List[CanonEpisode] = field(default_factory=list)  # ≤2 CANON CONTEXT
    relationship: Dict[str, float] = field(default_factory=dict)        # C5 归一化因子（快照）
    canon_activation: int = 0                                           # C2 activation 0..3

    def is_bounded(self, bounds: Optional[Dict[str, int]] = None) -> bool:
        b = bounds or {
            "canon": 2, "memories": 3, "user": 5, "agent": 2, "events": 5,
        }
        return (len(self.relevant_canon_episodes) <= b["canon"]
                and len(self.autobiographical_memories) <= b["memories"]
                and len(self.user_model_items) <= b["user"]
                and len(self.relevant_agent_tasks) <= b["agent"]
                and len(self.recent_events) <= b["events"])


# ================================================================ Work Willingness（model-only，Phase 14K 预留）
class WorkDisposition(str, enum.Enum):
    EAGER = "EAGER"
    WILLING = "WILLING"
    RELUCTANT = "RELUCTANT"
    PROTEST = "PROTEST"
    REFUSE = "REFUSE"


@dataclass
class WorkWillingnessInput:
    """工作意愿输入模型（model-only；禁止接成 production refusal）。"""

    energy: float = 0.5
    fatigue: float = 0.5
    mood: float = 0.5
    relationship: float = 0.5
    annoyance: float = 0.5
    task_interest: float = 0.5
    recent_workload: float = 0.0
    urgency: float = 0.0


@dataclass
class WorkWillingnessResult:
    disposition: WorkDisposition = WorkDisposition.WILLING
    score: float = 0.0
    factors: Dict[str, float] = field(default_factory=dict)
    refusal_eligible: bool = False       # 本 Phase 恒 False（不接硬拒绝）


class WorkWillingnessModel:
    """model-only：由输入推导 disposition 候选（仅供未来 Character Agency 使用）。

    本 Phase 明确禁止：fatigue > N → refuse everything；不参与 production task 决策。
    """

    def estimate(self, inp: WorkWillingnessInput) -> WorkWillingnessResult:
        positive = (inp.energy * 0.3 + inp.mood * 0.2 + inp.task_interest * 0.25
                    + inp.relationship * 0.15 + inp.urgency * 0.1)
        negative = (inp.fatigue * 0.3 + inp.annoyance * 0.25 + inp.recent_workload * 0.2)
        score = max(0.0, min(1.0, positive - negative + 0.5))
        if score >= 0.75:
            disp = WorkDisposition.EAGER
        elif score >= 0.5:
            disp = WorkDisposition.WILLING
        elif score >= 0.3:
            disp = WorkDisposition.RELUCTANT
        elif score >= 0.15:
            disp = WorkDisposition.PROTEST
        else:
            disp = WorkDisposition.REFUSE
        return WorkWillingnessResult(
            disposition=disp, score=round(score, 3),
            factors={"energy": inp.energy, "fatigue": inp.fatigue, "mood": inp.mood,
                     "relationship": inp.relationship, "annoyance": inp.annoyance,
                     "task_interest": inp.task_interest,
                     "recent_workload": inp.recent_workload, "urgency": inp.urgency},
            refusal_eligible=False,
        )
