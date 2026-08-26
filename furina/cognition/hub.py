"""CognitionHub —— 认知层总装（Phase 14K runtime integration boundary）。

- App owner 初始化：连接 existing MemoryEngine / RelationshipEngine + Canon adapters +
  UserModel / EventTimeline / AgentTaskHistory + ContextAssembler。
- worker 不直接写 Cognition authoritative DB：worker 返回结构化结果 → owner（dispatcher）→ persist。
- 不把数据库连接传 worker；ContextAssembler 在 owner ingress 构造 plain immutable data。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from furina.core import get_logger
from .consolidation.consolidator import Consolidator
from .context import CognitiveContextAssembler
from .models import CognitiveContext, LifeEvent, WorkWillingnessInput, WorkWillingnessModel
from .stores.agent_history import AgentTaskHistoryStore
from .stores.autobiography import AutobiographicalMemoryStore
from .stores.base import CognitionDB
from .stores.canon_history import CanonHistoryStore
from .stores.canon_identity import CanonIdentityStore
from .stores.event_timeline import EventTimelineStore
from .stores.relationship import RelationshipStore
from .stores.user_model import UserModelStore

log = get_logger("cognition.hub")

# Phase 14J：deterministic conservative user-model extraction（禁止模糊一句 → 永久人格标签）
# Phase 15.1：**entity-specific identity** —— 不同偏好主体/计划各自独立 ACTIVE（不同 key），
# 同主体修正才 supersede（不再用全局 'preference' / 'plan_today' 唯一身份）。
_PLAN_RE = re.compile(r"(今天|明天|后天|下周|这周|等会|一会儿|待会|马上|月底|打算|准备|计划|要).{0,24}(完成|做|写|测|整理|学|练|去|弄|处理|搞定|交)")
_PREF_RE = re.compile(r"(?:我(?:真的|特别|很|超)?喜欢|最爱|超爱)(.{2,40}?)(?:。|！|!|$)")
_DISLIKE_RE = re.compile(r"(?:我?(?:不太|很不|讨厌|不喜欢|烦|嫌))(?:别人|你|人|一直|总|总是|老|老是)?(.{2,40}?)(?:。|！|!|$)")
# 指令式沟通偏好：不要/不许/请别/别再/少（裸"别"排除"别人"里的"别"）
_CPREF_RE = re.compile(r"(?:不要|不许|请别|别再|少|(?<!人)别)(?:一直|总是|老是|动不动|天天|再)?(?:跟我|给我|对我|跟|给)?(.{2,40}?)(?:。|！|!|$)")
_FACT_RE = re.compile(r"(?:我是|我是个|我是位|我叫)(.{1,30}?)(?:。|！|!|$)")
_LOW_CONF_MARKERS = ("也许", "可能", "大概", "或许", "有时候", "偶尔", "感觉")
# 计划目标提取："我今天准备完成桌宠测试" → "桌宠测试"；"今天要测试" → "测试"
# 连续标记（今天+准备+要…）全部消费后再取目标名词
_PLAN_TARGET_RE = re.compile(
    r"(?:我)?(?:(?:今天|明天|后天|下周|这周|等会|一会儿|待会|马上|月底|打算|准备|计划|要)\s*){1,3}"
    r"(?:要|还|再)?\s*(?:完成|做|写|测|整理|学|练|去|弄|处理|搞定|交)?\s*(.{2,40}?)(?:。|！|!|$)")


def _plan_target(text: str) -> str:
    """从计划声明提取稳定实体（目标名词）；无 → 空（保守，不硬造）。"""
    m = _PLAN_TARGET_RE.search(text or "")
    if not m:
        return ""
    target = m.group(1).strip()
    # 去掉残留动作词/时间词（"我今天准备完成桌宠测试" 的 完成 已被可选组吃掉；防御）
    for w in ("完成", "做完", "写好", "测完", "整理好"):
        if target.startswith(w) and len(target) > len(w) + 1:
            target = target[len(w):]
    return target[:30]


class UserModelExtractor:
    """Phase 14J：conservative explicit extraction（deterministic，LLM 不参与）。

    只在明确高置信 self-statement 时产出 candidate；模糊/低置信 → None。
    """

    def extract(self, text: str) -> Optional[Dict[str, Any]]:
        t = (text or "").strip()
        if not t:
            return None
        low_conf = 0.45 if any(m in t for m in _LOW_CONF_MARKERS) else None

        m = _PLAN_RE.search(t)
        if m and any(k in t for k in ("准备", "打算", "要", "今天", "明天", "后天", "下周", "月底")):
            target = _plan_target(t) or "待定"
            return {"category": "PLAN", "key": f"plan:{target}",
                    "value": t[:80], "confidence": low_conf or 0.85,
                    "excerpt": t[:120]}
        # DISLIKE 先于 CPREF（"我不喜欢…" 是 dislike 陈述）
        m = _DISLIKE_RE.search(t)
        if m:
            return {"category": "DISLIKE", "key": f"dislike:{m.group(1).strip()[:30]}",
                    "value": m.group(1)[:60], "confidence": low_conf or 0.7,
                    "excerpt": t[:120]}
        m = _CPREF_RE.search(t)
        if m and ("讲大道理" in t or "催" in t or "吵" in t or "打扰" in t or "说话" in t):
            return {"category": "COMMUNICATION_PREFERENCE", "key": "comm_style",
                    "value": m.group(0)[:60], "confidence": low_conf or 0.85,
                    "excerpt": t[:120]}
        m = _PREF_RE.search(t)
        if m:
            entity = m.group(1).strip()
            for v in ("喝", "吃", "玩", "看", "听", "爱", "用", "去", "买"):
                if entity.startswith(v) and len(entity) > len(v) + 1:
                    entity = entity[len(v):]
                    break
            entity = entity.rstrip("了。！! ")[:30]
            return {"category": "PREFERENCE", "key": f"preference:{entity}",
                    "value": entity, "confidence": low_conf or 0.8,
                    "excerpt": t[:120]}
        m = _FACT_RE.search(t)
        if m:
            return {"category": "FACT", "key": f"fact:{m.group(1).strip()[:20]}",
                    "value": m.group(1)[:60], "confidence": low_conf or 0.6,
                    "excerpt": t[:120]}
        return None


class CognitionHub:
    """认知层总装：7 store + assembler + consolidator + willingness(model-only)。"""

    def __init__(self, db_path, memory_engine=None, relationship_engine=None,
                 session_id: str = "", history_path: Optional[Path] = None,
                 sources_path: Optional[Path] = None) -> None:
        self._db = CognitionDB(Path(db_path))
        self.canon_identity = CanonIdentityStore()
        self.canon_history = CanonHistoryStore(history_path=history_path,
                                               sources_path=sources_path)
        self.autobiography = AutobiographicalMemoryStore(memory_engine) if memory_engine else None
        self.user_model = UserModelStore(self._db)
        self.relationship = RelationshipStore(self._db, relationship_engine) if relationship_engine else None
        self.events = EventTimelineStore(self._db, session_id=session_id)
        self.agent_history = AgentTaskHistoryStore(self._db)
        self.consolidator = Consolidator()
        self.extractor = UserModelExtractor()
        # Phase 15B：Interpretation Engine（deterministic-first；无 DB 写 API）
        from .interpretation import InterpretationEngine
        self.interpretation = InterpretationEngine()
        self.willingness = WorkWillingnessModel()     # model-only（Phase 14K 预留）
        # Phase 15E：Derived Semantic Vector Index（DERIVED/REBUILDABLE/NON-AUTHORITATIVE）
        from .retrieval import SemanticVectorIndex, default_index_path
        self.index = SemanticVectorIndex(index_path=default_index_path(self._db._path))
        self.assembler = CognitiveContextAssembler(
            canon_identity=self.canon_identity,
            canon_history=self.canon_history,
            autobiography=self.autobiography or _NullAutobiography(),
            user_model=self.user_model,
            relationship=self.relationship or _NullRelationship(),
            events=self.events,
            agent_history=self.agent_history,
        )
        self._session_id = session_id
        log.info("CognitionHub ready: schema_version=%s", self._db.schema_version)

    # -------------------------------------------------- 便捷入口（owner 线程）
    def record_event(self, event_type: str, *, payload: Optional[Dict[str, Any]] = None,
                     source: str = "runtime", actor: str = "furina", channel: str = "",
                     turn_id: Optional[int] = None, task_id: str = "",
                     importance: float = 0.0, consolidate: bool = True):
        """owner 线程：追加客观事件 + 可选 consolidation（单事件单 owner）。

        Phase 14.1 §8：返回 LifeEvent（含 event_id），供 UserModel upsert 的 source_event_id
        evidence chain 使用（objective event 先落地 → 拿到 event_id → item 引用它）。
        Phase 15F：无论 consolidate 与否，事件都标记 processed（inline 路径已处理/由调用方
        负责）—— 避免 process_pending 重复消费。
        """
        ev = self.events.append(event_type=event_type, payload=payload, source=source,
                                actor=actor, channel=channel, turn_id=turn_id,
                                task_id=task_id, importance=importance)
        if consolidate:
            self._apply_consolidation(ev)
        self._mark_processed(ev.event_id)
        return ev

    # -------------------------------------------------- Phase 15F：Persistent Cognitive Loop
    def _mark_processed(self, event_id: str, version: str = "15F.1") -> None:
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO event_processing(event_id,process_version,processed_at) "
                "VALUES(?,?,?)", (event_id, version, time.time()))
        except Exception:
            pass

    def _is_processed(self, event_id: str) -> bool:
        try:
            return self._db.query_one(
                "SELECT 1 FROM event_processing WHERE event_id=?", (event_id,)) is not None
        except Exception:
            return False

    def process_pending(self, batch: int = 10) -> Dict[str, Any]:
        """owner：处理未 consolidation 的 C6 事件（cursor+log 幂等；bounded batch）。

        C6 append → pending → 本方法（InterpretationEngine → candidates → owner apply
        → C3/C4/C5）。同一 event_id + process_version 重复处理 → duplicate=0；
        重启后不会重复 consolidation，也不会丢未处理事件。
        """
        stats: Dict[str, Any] = {"processed": 0, "already_processed": 0,
                                 "candidates": 0, "memories": 0,
                                 "user_items": 0, "plans_completed": [],
                                 "superseded": []}
        try:
            rows = self._db.query_all(
                "SELECT le.* FROM life_events le LEFT JOIN event_processing ep "
                "ON le.event_id=ep.event_id WHERE ep.event_id IS NULL "
                "ORDER BY le.created_at ASC LIMIT ?", (batch,))
        except Exception as e:
            log.warning("process_pending query failed: %s", e)
            return stats
        for row in rows:
            ev = LifeEvent.from_row(row)
            if self._is_processed(ev.event_id):
                stats["already_processed"] += 1
                continue
            try:
                for cand in self.interpretation.interpret_event(ev):
                    stats["candidates"] += 1
                    if cand.candidate_target == "C4":
                        r = self._apply_c4_candidate(cand)
                        stats["user_items"] += len(r.get("items", []))
                        stats["plans_completed"].extend(r.get("plans_completed", []))
                        stats["superseded"].extend(r.get("superseded", []))
                    elif cand.candidate_target == "C3":
                        self._apply_c3_candidate(cand, ev)
                        stats["memories"] += 1
                self._mark_processed(ev.event_id)
                stats["processed"] += 1
            except Exception as e:
                log.warning("process_pending event %s failed: %s", ev.event_id, e)
        # cursor 推进（处理进度持久化：重启不重复、不丢失）
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO cognition_meta(key,value) VALUES('last_processed_event_id',?)",
                (self._db.query_one(
                    "SELECT COALESCE(MAX(processed_at),0) AS t FROM event_processing")["t"] and
                 str(self.events.count()) or "0",))
        except Exception:
            pass
        return stats

    def processing_status(self) -> Dict[str, Any]:
        try:
            pending = self._db.query_one(
                "SELECT COUNT(*) AS c FROM life_events le LEFT JOIN event_processing ep "
                "ON le.event_id=ep.event_id WHERE ep.event_id IS NULL")["c"]
            processed = self._db.count("event_processing")
        except Exception:
            pending, processed = -1, -1
        return {"pending": int(pending or 0), "processed": int(processed or 0),
                "idempotent": True}

    def _apply_c4_candidate(self, cand) -> Dict[str, Any]:
        """C4 候选 → owner 落地（entity-specific；supersede 不 overwrite；计划生命周期）。"""
        out: Dict[str, Any] = {"items": [], "plans_completed": [], "superseded": []}
        src = (cand.source_event_ids or [""])[0]
        try:
            if cand.kind == "PLAN_COMPLETED":
                # Phase 15.1：targeted completion —— 唯一目标才完成；ambiguous 不自动完成
                if cand.predicate and cand.predicate != "plan:__ambiguous__":
                    done = self._complete_plan_key(cand.predicate)
                    if done:
                        out["plans_completed"].append(done.item_id)
            elif cand.kind == "PREFERENCE_CHANGED":
                # Phase 15.1：entity-specific supersede —— 只 supersede 该实体旧 item
                if cand.predicate and cand.predicate != "preference:__unknown__":
                    for it in self.user_model.query_active(limit=100, category="PREFERENCE"):
                        if it.key == cand.predicate:
                            self.user_model.supersede_item(it.item_id)
                            out["superseded"].append(it.item_id)
            elif cand.kind in ("PLAN", "PREFERENCE", "DISLIKE", "COMMUNICATION_PREFERENCE",
                               "FACT", "HABIT", "INTEREST", "GOAL", "IMPORTANT_DATE"):
                # deterministic dedupe：同 category+key 且值相同的 ACTIVE item 已存在
                # （例如 direct-path 已处理）→ 保留原 provenance，不重复 upsert/supersede。
                key = cand.predicate or "fact"
                existing = self.user_model.query_active(limit=100, category=cand.kind)
                same = next((i for i in existing
                             if i.key == key and str(i.value) == str(cand.value)), None)
                if same is not None:
                    out["items"].append(same.item_id)
                    return out
                it = self.user_model.upsert_item(
                    category=cand.kind, key=key, value=cand.value,
                    confidence=cand.confidence, source_event_id=src,
                    source_text_excerpt=(cand.reason or "")[:500])
                out["items"].append(it.item_id)
        except Exception as e:
            log.warning("apply c4 candidate failed: %s", e)
        return out

    def _apply_c3_candidate(self, cand, ev) -> None:
        """C3 候选 → owner 落地（dedupe+provenance；Failed Agent 不形成成功记忆）。"""
        from furina.memory import MemoryLevel, MemorySource
        mem: Dict[str, Any] = {"content": cand.value, "level": MemoryLevel.EPISODIC,
                               "source_event_ids": [ev.event_id],
                               "event_type": ev.event_type}
        if cand.kind == "C3_EPISODIC" or cand.predicate == "agent_task":
            mem["source"] = MemorySource.AGENT_TASK
            mem["importance"] = cand.confidence
        else:
            mem["source"] = MemorySource.INTERACTION
            mem["importance"] = max(0.4, cand.confidence)
        self._form_memory(ev, mem)

    def _apply_consolidation(self, ev) -> None:
        try:
            plan = self.consolidator.consider(ev.event_type, payload=ev.payload,
                                              importance=ev.importance,
                                              verified=bool(ev.task_id),
                                              source_event_ids=[ev.event_id])
            if plan.get("form_memory") and self.autobiography is not None and plan.get("memory"):
                self._form_memory(ev, plan["memory"])
            if plan.get("user_model"):
                u = plan["user_model"]
                self.user_model.upsert_item(category=u["category"], key=u["key"],
                                            value=u["value"], confidence=u["confidence"],
                                            source_event_id=ev.event_id,
                                            source_text_excerpt=u.get("excerpt", ""))
            if plan.get("milestone") and self.relationship is not None:
                msrc = (plan["milestone"].get("source_event_ids") or [""])[0]
                self.relationship.record_milestone(plan["milestone"]["type"],
                                                   plan["milestone"].get("note", ""),
                                                   source_event_id=msrc)
        except Exception as e:
            log.warning("consolidation failed: %s", e)

    def _form_memory(self, ev, mem: Dict[str, Any]) -> None:
        """Phase 15C：C3 形成（deterministic dedupe + provenance）。

        - 同 event_type 的 ACTIVE 近 24h 记忆 → **reinforce**（recurrence++ / importance 取 max /
          strength↑ / 累积 source_event_ids），**不重复插行**（N3：pet×4 只 1 条）。
        - 否则 observe 新记忆（带 source_event_ids provenance）。
        """
        auto = self.autobiography
        etype = mem.get("event_type", ev.event_type)
        src_ids = list(mem.get("source_event_ids") or [ev.event_id])
        import time as _t
        now = _t.time()
        dup = None
        try:
            for m in auto.recent(50):
                if (m.status.value == "active" and m.event_type == etype
                        and (now - m.timestamp) < 86400.0):
                    dup = m
                    break
        except Exception:
            dup = None
        if dup is not None:
            dup.recurrence_count += 1
            dup.importance = max(float(dup.importance), float(mem.get("importance", 0.5)))
            dup.strength = min(1.0, float(dup.strength) + 0.05)
            dup.last_reinforced = now
            for eid in src_ids:
                if eid and eid not in dup.source_event_ids:
                    dup.source_event_ids.append(eid)
            auto.insert(dup)
            return
        m = auto.observe(mem["content"], level=mem.get("level"), source=mem.get("source"),
                         importance=mem.get("importance", 0.5), context=ev.event_type,
                         outcome=mem.get("outcome", ""), source_event_ids=src_ids)
        if m is not None:
            # 补写 event_type（dedupe 键）并回写（保持单一持久化 = MemoryEngine.store）
            if not getattr(m, "event_type", ""):
                m.event_type = etype
                auto.insert(m)

    def extract_user_model(self, text: str) -> Optional[Dict[str, Any]]:
        """Phase 14J：deterministic conservative extraction（owner 决定是否 persist）。"""
        return self.extractor.extract(text)

    # -------------------------------------------------- Phase 15D：用户一句话 → C4 确定性演化（owner）
    def apply_user_message(self, text: str, *, channel: str = "DIRECT_USER_TURN",
                           turn_id: Optional[int] = None) -> Dict[str, Any]:
        """owner：用户直接消息 → C4 演化（evidence-first，current explicit turn wins）。

        - declaration（我喜欢X/我今天准备做X/以后别总是X）→ declaration event 先落地 →
          upsert(source_event_id)；explicit correction wins（supersede 旧 item）；
        - PLAN_COMPLETED（做完了/终于完成）→ 关联 ACTIVE PLAN → COMPLETED（不新增互不关联 plan）；
        - PREFERENCE_CHANGED（其实现在不怎么听X了）→ 旧 PREFERENCE SUPERSEDED（历史保留）。
        - 不记录 USER_MESSAGE 事件（EventBridge 在 turn 入口负责，避免 duplicate）。
        - '这首歌不错' → 无候选（transient，不形成 lifelong）。
        """
        applied: Dict[str, Any] = {"declarations": [], "superseded": [],
                                   "plans_completed": [], "events": []}
        try:
            for cand in self.interpretation.interpret_text(text):
                if cand.kind in ("PLAN_COMPLETED", "PREFERENCE_CHANGED"):
                    r = self._apply_c4_candidate(cand)
                    applied["plans_completed"].extend(r["plans_completed"])
                    applied["superseded"].extend(r["superseded"])
                elif cand.kind in ("PLAN", "PREFERENCE", "DISLIKE", "COMMUNICATION_PREFERENCE",
                                   "FACT", "HABIT", "INTEREST", "GOAL", "IMPORTANT_DATE"):
                    ev_type = ("USER_PLAN_DECLARED" if cand.kind == "PLAN"
                               else "USER_PREFERENCE_DECLARED")
                    dev = self.record_event(ev_type, source="dialogue", channel=channel,
                                            turn_id=turn_id,
                                            payload={"key": cand.predicate, "value": cand.value,
                                                     "excerpt": cand.reason,
                                                     "confidence": cand.confidence},
                                            importance=0.5, consolidate=False)
                    it = self.user_model.upsert_item(
                        category=cand.kind, key=cand.predicate or "fact",
                        value=cand.value, confidence=cand.confidence,
                        source_event_id=dev.event_id,
                        source_text_excerpt=(cand.reason or "")[:500])
                    applied["declarations"].append(it.item_id)
                    applied["events"].append(dev.event_id)
        except Exception as e:
            log.warning("apply_user_message failed: %s", e)
        return applied

    def _complete_plan_key(self, key: str):
        """Phase 15.1：targeted plan completion —— 只完成该实体 key 的 ACTIVE PLAN。"""
        return self.user_model.complete_plan(key)

    def _complete_plans(self) -> List[str]:
        """（legacy 兼容）证据可唯一识别时才完成；否则不动（不批量完成）。"""
        return []

    # -------------------------------------------------- agent result → C7（owner persist）
    def persist_agent_result(self, task_id: str, *, status: str, goal: str = "",
                             original_request: str = "", verified: bool = False,
                             result_summary: str = "", error: str = "",
                             steps: Optional[List[Dict[str, Any]]] = None,
                             artifacts: Optional[List[Dict[str, Any]]] = None,
                             plan_json: str = "{}",
                             permission_summary: str = "") -> None:
        """worker 返回结构化 task result → **owner**（dispatcher）调用本方法持久化 C7。

        Phase 14.1 §5：C7 精确保留生命周期 status（PLANNED/RUNNING/COMPLETED_VERIFIED/
        FAILED/UNVERIFIED/CANCELLED），**不得由 verified bool 替代 status**。
        本方法设计为只在 owner 线程执行（不直接暴露给 worker）。
        """
        task = self.agent_history.get_task(task_id)
        if task is None:
            self.agent_history.create_task(task_id, original_request=original_request, goal=goal)
        if plan_json or permission_summary:
            self.agent_history.set_plan(task_id, plan_json, permission_summary)
        if steps:
            for s in steps:
                self.agent_history.add_step(
                    task_id, int(s.get("step_index", 0)), tool=s.get("tool", ""),
                    args=s.get("args", {}), capability=s.get("capability", ""),
                    permission_level=s.get("permission_level", ""),
                    status=s.get("status", "RUNNING"), verified=bool(s.get("verified", False)),
                    result=s.get("result"), error=s.get("error", ""))
        if artifacts:
            for a in artifacts:
                self.agent_history.add_artifact(
                    task_id, a.get("artifact_type", "file"), a.get("path", ""),
                    exists_verified=bool(a.get("exists_verified", False)),
                    metadata=a.get("metadata"))
        # 精确保留 status（FAILED → FAILED；UNVERIFIED → UNVERIFIED；verified success → COMPLETED_VERIFIED）
        self.agent_history.set_status(task_id, status, error=error,
                                      verified=bool(verified), result_summary=result_summary)

    def assemble(self, *, query: str = "", topic: str = "",
                 current_facts: Optional[Dict[str, Any]] = None,
                 trust: float = 0.5) -> CognitiveContext:
        """owner ingress：构造有界 immutable cognitive context。"""
        return self.assembler.assemble(query=query, topic=topic,
                                       current_facts=current_facts, trust=trust)

    # -------------------------------------------------- Phase 15E：Derived Index 管理
    def build_index(self) -> int:
        """从 source stores 的选中条目重建 derived index（幂等）。"""
        return self.index.build(
            canon_episodes=self.canon_history.all_episodes(),
            memories=self.autobiography.all_memories(status=None, limit=200)
            if self.autobiography else [],
            user_items=self.user_model.query_active(limit=200),
            agent_tasks=self.agent_history.query_recent(limit=50))

    def rebuild_index(self) -> int:
        return self.build_index()

    def delete_index(self) -> None:
        """删除 derived index（**不触碰 source stores**）。"""
        self.index.delete()

    def index_status(self) -> Dict[str, Any]:
        return self.index.status()

    def lookup_index(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """NON-AUTHORITATIVE 语义提示；缺失/不可用 → []（cognition 仍工作）。"""
        try:
            return self.index.lookup(query, top_k=top_k)
        except Exception:
            return []

    def willingness_input(self, **kw: float) -> WorkWillingnessInput:
        return WorkWillingnessInput(**{k: float(v) for k, v in kw.items()
                                       if k in WorkWillingnessInput.__dataclass_fields__})

    # -------------------------------------------------- migration / health
    @property
    def schema_version(self) -> str:
        return self._db.schema_version

    def health(self) -> Dict[str, Any]:
        return {
            "schema_version": self._db.schema_version,
            "canon_episodes": self.canon_history.episode_count(),
            "user_model_items": self.user_model.count(),
            "life_events": self.events.count(),
            "agent_tasks": self.agent_history.count(),
            "memories": self.autobiography.count() if self.autobiography else 0,
            "canon_runtime_mutable": False,
        }

    def close(self) -> None:
        self._db.close()


class _NullAutobiography:
    """memory_engine 未注入时的只读空替身（assembler 兼容）。"""

    def retrieve(self, *, query="", limit=3, context=None):
        return []

    def count(self, *, status=None):
        return 0


class _NullRelationship:
    def factors(self):
        return {}
