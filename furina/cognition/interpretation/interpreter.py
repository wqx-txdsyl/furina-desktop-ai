"""Interpretation Engine（Phase 15B）—— C6 → InterpretationCandidate（候选，非 truth）。

铁律：
- **Interpretation ≠ Truth**：本引擎只产出候选；是否写 C3/C4/C5 由对应 authority（owner）
  决定；**禁止 LLM interpretation 直接 UPDATE DB**（本引擎无任何写方法）。
- **Deterministic-first**："我喜欢 X / 我不喜欢 X / 我今天准备做 X / 以后别总是 X /
  我已经做完 X" 全部 deterministic（正则/规则），不调 LLM。
- LLM 只允许处理 ambiguous/context-dependent（本 Phase 提供接口预留，不接线 DB）。
- 禁止幻觉："这首歌不错" 不得产出 lifelong PREFERENCE（最多 transient reaction 或 None）。
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from furina.core import get_logger

log = get_logger("cognition.interpretation")

PROCESS_VERSION = "15B.1"


@dataclass
class InterpretationCandidate:
    """C6 事件的解释候选（immutable 语义；owner 决定是否落地）。"""

    interpretation_id: str
    source_event_ids: List[str]
    kind: str                       # PLAN/PREFERENCE/DISLIKE/COMMUNICATION_PREFERENCE/FACT/
                                    # PLAN_COMPLETED/C3_EPISODIC/C3_CONDITIONAL/NONE
    subject: str
    predicate: str
    value: str
    confidence: float
    evidence_type: str              # DIRECT_STATEMENT / COMPLETION / EVENT / AMBIGUOUS
    temporal_scope: str             # PERSISTENT / TRANSIENT / DATED / UNKNOWN
    candidate_target: str           # C4 / C3 / C5 / NONE
    reason: str
    created_at: float = field(default_factory=time.time)
    process_version: str = PROCESS_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {f: getattr(self, f) for f in (
            "interpretation_id", "source_event_ids", "kind", "subject", "predicate", "value",
            "confidence", "evidence_type", "temporal_scope", "candidate_target", "reason",
            "created_at", "process_version")}


# ================================================================ deterministic extractors
# "我已经做完 X" / "终于做完了" → PLAN_COMPLETED
_COMPLETION_RE = re.compile(r"(?:我)?(?:终于|已经|总算)?(?:做?完|完成|搞定|弄好)(?:了)?\s*(?:桌宠测试|报告|任务|这个|作业|文件|文档|项目|工作)?")
_DONE_MARKERS = ("做完了", "完成了", "搞定", "弄好了", "终于做完", "已经做完", "完成测试",
                 "做完测试", "交完", "写完了", "写完了报告", "测完了")

# 明确改变声明（supersede 触发）："现在不/不再/已经不太/最近不/不怎么"
_CHANGE_RE = re.compile(r"(?:现在|最近|如今|已经|其实)?(?:不|不再|不太|不怎么|没|少)(?:听|喝|吃|玩|看|喜欢|爱|用|去|买)?(.{2,40}?)(?:了)?(?:。|！|!|$)")

# transient（禁 lifelong）："不错/好听/还行/可以" 无主语归属时
_TRANSIENT_HINTS = ("这首歌", "这个", "这歌", "那首", "不错", "好听", "还行")


class InterpretationEngine:
    """确定性解释引擎（无 DB 写方法 —— interpretation ≠ truth）。"""

    def __init__(self) -> None:
        from furina.cognition.hub import UserModelExtractor
        self._extractor = UserModelExtractor()

    # -------------------------------------------------- text → candidates（deterministic）
    def interpret_text(self, text: str, source_event_ids: Optional[List[str]] = None) -> List[InterpretationCandidate]:
        """用户一句话 → 确定性候选。模糊/transient → 空或低置信，绝不幻觉 lifelong。"""
        t = (text or "").strip()
        if not t:
            return []
        ev_ids = list(source_event_ids or [])
        out: List[InterpretationCandidate] = []

        # 1) 完成声明 → PLAN_COMPLETED（证据可靠时，目标 C4 计划生命周期）
        if any(m in t for m in _DONE_MARKERS):
            out.append(self._mk(ev_ids, "PLAN_COMPLETED", "user", "plan_completed", t[:80],
                                0.8, "COMPLETION", "DATED", "C4",
                                "完成声明（做完了/完成了）→ 关联 ACTIVE PLAN 转 COMPLETED"))

        # 2) 明确改变声明 → 当前偏好变化（supersede 旧 item 的依据；不覆盖，走 lifecycle）
        m = _CHANGE_RE.search(t)
        if m and any(k in t for k in ("不", "不再", "不太", "不怎么", "没")):
            out.append(self._mk(ev_ids, "PREFERENCE_CHANGED", "user", "preference",
                                m.group(0)[:60], 0.75, "DIRECT_STATEMENT", "PERSISTENT",
                                "C4", "明确偏好改变 → 旧 item SUPERSEDED，新事实 ACTIVE"))

        # 3) 明确高置信声明（复用 UserModelExtractor：PLAN/PREFERENCE/DISLIKE/CPREF/FACT）
        cand = self._extractor.extract(t)
        if cand:
            out.append(self._mk(ev_ids, cand["category"], "user", cand["key"],
                                str(cand["value"]), float(cand["confidence"]),
                                "DIRECT_STATEMENT", "PERSISTENT", "C4", cand["excerpt"]))

        # 4) transient（"这首歌不错"）→ **不**形成 lifelong PREFERENCE
        if any(h in t for h in _TRANSIENT_HINTS) and not out:
            log.debug("interpretation: transient reaction（不形成 lifelong C4）: %s", t)
            return []
        return out

    # -------------------------------------------------- event → candidates
    def interpret_event(self, event) -> List[InterpretationCandidate]:
        """C6 event → 候选。普通/琐碎事件 → 空（trivial suppression 起点）。"""
        et = getattr(event, "event_type", "")
        payload = getattr(event, "payload", {}) or {}
        ev_ids = [getattr(event, "event_id", "")]
        if et == "USER_MESSAGE":
            return self.interpret_text(str(payload.get("text", "")), ev_ids)
        if et == "USER_PLAN_DECLARED":
            return [self._mk(ev_ids, "PLAN", "user", str(payload.get("key", "plan")),
                             str(payload.get("value", "")), float(payload.get("confidence", 0.8)),
                             "DIRECT_STATEMENT", "DATED", "C4", "明确用户计划声明")]
        if et == "USER_PREFERENCE_DECLARED":
            return [self._mk(ev_ids, str(payload.get("category", "PREFERENCE")), "user",
                             str(payload.get("key", "preference")), str(payload.get("value", "")),
                             float(payload.get("confidence", 0.7)), "DIRECT_STATEMENT",
                             "PERSISTENT", "C4", "明确用户偏好声明")]
        if et == "AGENT_COMPLETED":
            return [self._mk(ev_ids, "C3_EPISODIC", "furina", "agent_task",
                             f"我帮用户完成了：{payload.get('goal', '')}", 0.55, "EVENT",
                             "DATED", "C3", "重要 Agent 任务完成（可形成 episodic memory）")]
        if et == "AGENT_FAILED":
            return [self._mk(ev_ids, "C3_CONDITIONAL", "furina", "agent_task",
                             f"帮用户处理{payload.get('request', '')}时失败", 0.4, "EVENT",
                             "DATED", "C3", "Agent 失败（C7 FAILED 真相优先；不形成成功记忆）")]
        if et == "USER_PET":
            return [self._mk(ev_ids, "C3_CONDITIONAL", "furina", "interaction", "用户摸了我的头",
                             0.45, "EVENT", "TRANSIENT", "C3", "有意义的互动（条件记忆）")]
        if et in ("ACTIVITY_STARTED", "ACTIVITY_FINISHED", "FURINA_SPOKE",
                  "DIRECT_TURN_STARTED", "DIRECT_TURN_TERMINAL", "MEANINGFUL_INTERACTION"):
            return []                       # 琐碎/常规事件 → 无候选（不机械成记忆）
        if et in ("FILE_CREATED", "FILE_MOVED", "DOCUMENT_CREATED"):
            return [self._mk(ev_ids, "C3_CONDITIONAL", "furina", "agent_task",
                             str(payload.get("summary", et)), 0.5, "EVENT", "DATED", "C3",
                             "Agent 文件操作（条件记忆）")]
        return []

    # -------------------------------------------------- LLM ambiguous（可选；不接线 DB）
    def interpret_ambiguous_llm(self, text: str, source_event_ids: Optional[List[str]] = None,
                                llm=None) -> List[InterpretationCandidate]:
        """ambiguous/context-dependent 才允许 LLM（接口预留）；LLM 不可用 → 空（cognition 仍工作）。"""
        if llm is None:
            return []
        try:
            if not llm.is_available():
                return []
            from furina.llm.base import LLMMessage, content
            messages = [
                LLMMessage(role="system", content=content(
                    "你是确定性解释助手。只输出 JSON 候选：{kind, subject, value, confidence, "
                    "temporal_scope}。禁止直接写任何数据库。无法确定 → 输出空列表。")),
                LLMMessage(role="user", content=content(f"用户说：{text}")),
            ]
            raw = llm.structured(messages, schema={
                "type": "object", "properties": {
                    "candidates": {"type": "array", "items": {"type": "object",
                        "properties": {"kind": {"type": "string"}, "subject": {"type": "string"},
                                       "value": {"type": "string"},
                                       "confidence": {"type": "number"},
                                       "temporal_scope": {"type": "string"}}}}}})
            out = []
            for c in (raw.get("candidates") or []):
                out.append(self._mk(list(source_event_ids or []), str(c.get("kind", "FACT")),
                                    "user", str(c.get("subject", "")), str(c.get("value", "")),
                                    float(c.get("confidence", 0.3)), "AMBIGUOUS",
                                    str(c.get("temporal_scope", "UNKNOWN")), "C4",
                                    "LLM ambiguous interpretation（候选，owner 决定）"))
            return out
        except Exception as e:
            log.warning("ambiguous LLM interpretation 失败（fallback 空）: %s", e)
            return []

    # -------------------------------------------------- helpers
    def _mk(self, ev_ids: List[str], kind: str, subject: str, predicate: str, value: str,
            confidence: float, evidence_type: str, temporal_scope: str, target: str,
            reason: str) -> InterpretationCandidate:
        return InterpretationCandidate(
            interpretation_id=f"int_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}",
            source_event_ids=ev_ids, kind=kind, subject=subject, predicate=predicate,
            value=value, confidence=max(0.0, min(1.0, confidence)),
            evidence_type=evidence_type, temporal_scope=temporal_scope,
            candidate_target=target, reason=reason)

    # -------------------------------------------------- 不变式
    def has_db_write_api(self) -> bool:
        return False                       # interpretation ≠ truth：无直接写方法
