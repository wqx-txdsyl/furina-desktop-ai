"""C4 — User Model（user_model_items 表）。

- conservative explicit extraction：只有明确高置信 self-statements 才形成 item；
- evidence + confidence 必带；
- 同一 key 更新 → supersede / validity close（**不得无历史 overwrite**）；
- 禁止：模糊一句话 → 永久人格标签。
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from furina.core import get_logger
from ..models import UserModelItem
from .base import CognitionDB

log = get_logger("cognition.user_model")

CATEGORIES = ("FACT", "PREFERENCE", "DISLIKE", "ROUTINE", "PROJECT", "GOAL",
              "PLAN", "COMMUNICATION_PREFERENCE", "IMPORTANT_DATE",
              "HABIT", "INTEREST")

# Phase 15D：PLAN 生命周期（§28）
PLAN_STATUSES = ("ACTIVE", "COMPLETED", "CANCELLED", "EXPIRED", "SUPERSEDED")


class UserModelStore:
    """C4 唯一写 owner（deterministic conservative extraction 后持久化）。"""

    def __init__(self, db: CognitionDB) -> None:
        self._db = db

    # -------------------------------------------------- write
    def upsert_item(self, *, category: str, key: str, value: Any, confidence: float,
                    source_event_id: str = "", source_text_excerpt: str = "",
                    valid_to: float = 0.0, temporal_uncertain: int = 0,
                    temporal_json: str = "") -> UserModelItem:
        """新增/更新 item。同 category+key 的旧 active item → superseded（不 overwrite 历史）。

        返回新 item。confidence 由调用方（deterministic extraction）给定，本层不猜。
        Phase 15D：temporal_uncertain=1 表示日期无法确定（绝不编日期）。
        Phase 15 D4：temporal_json 为确定性解析载荷（resolver 在 canonical ingress
        一次性解析；本层只持久化，不重解释、不生成时间）。
        """
        cat = category if category in CATEGORIES else "FACT"
        value_json = self._to_json(value)
        now = time.time()
        # 旧 active 同 key item → supersede（validity close），并记录 transition evidence：
        # 本次 declaration 事件（source_event_id）就是触发 supersede 的 canonical trigger
        # （Phase 14 Final Closure INV-C4-1：不能只靠 status/timestamp 反推来源）。
        for old in self._active_by_key(cat, key):
            self._db.execute(
                "UPDATE user_model_items SET status='superseded', valid_to=?, updated_at=?, "
                "transition_event_id=?, transition_reason=? WHERE item_id=?",
                (now, now, source_event_id or "", (source_text_excerpt or "")[:200],
                 old.item_id))
        item_id = f"umi_{int(now*1000)}_{uuid.uuid4().hex[:6]}"
        t_json = (temporal_json or "")[:1000]
        row = (item_id, cat, key, value_json, float(confidence), source_event_id,
               (source_text_excerpt or "")[:500], now, now, now, float(valid_to), "active",
               int(temporal_uncertain or 0), now, t_json)
        self._db.execute(
            "INSERT INTO user_model_items(item_id,category,key,value_json,confidence,"
            "source_event_id,source_text_excerpt,created_at,updated_at,valid_from,valid_to,status,"
            "temporal_uncertain,declared_at,temporal_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        return UserModelItem(
            item_id=item_id, category=cat, key=key, value_json=value_json,
            confidence=float(confidence), source_event_id=source_event_id,
            source_text_excerpt=(source_text_excerpt or "")[:500],
            created_at=now, updated_at=now, valid_from=now, valid_to=float(valid_to),
            status="active", temporal_uncertain=int(temporal_uncertain or 0),
            declared_at=now, temporal_json=t_json)

    # -------------------------------------------------- Phase 15D：PLAN 生命周期
    def set_plan_status(self, key: str, status: str, *, category: str = "PLAN",
                        transition_event_id: str = "",
                        transition_reason: str = "") -> Optional[UserModelItem]:
        """把 ACTIVE PLAN 转移到 COMPLETED/CANCELLED/EXPIRED（不新增互不关联的 plan）。

        '我终于做完了' 的 evidence 关联到既有 plan（按 key），否则不猜。
        Phase 14 Final Closure（INV-C4-2）：lifecycle transition 必须记录触发它的
        canonical C6 event id + 原因（真实 utterance），不得只有 status/timestamp。
        """
        st = status if status in PLAN_STATUSES else "ACTIVE"
        rows = self._db.query_all(
            "SELECT * FROM user_model_items WHERE category=? AND key=? AND status='active' "
            "ORDER BY updated_at DESC LIMIT 1", (category, key))
        if not rows:
            return None
        it = UserModelItem.from_row(rows[0])
        now = time.time()
        self._db.execute(
            "UPDATE user_model_items SET status=?, updated_at=?, valid_to=?, "
            "transition_event_id=?, transition_reason=? WHERE item_id=?",
            (st.lower(), now, now, transition_event_id or "",
             (transition_reason or "")[:200], it.item_id))
        it.status = st.lower()
        it.valid_to = now
        it.transition_event_id = transition_event_id or ""
        it.transition_reason = (transition_reason or "")[:200]
        return it

    def complete_plan(self, key: str, *, transition_event_id: str = "",
                      transition_reason: str = "") -> Optional[UserModelItem]:
        return self.set_plan_status(key, "COMPLETED", transition_event_id=transition_event_id,
                                    transition_reason=transition_reason)

    def cancel_plan(self, key: str) -> Optional[UserModelItem]:
        return self.set_plan_status(key, "CANCELLED")

    def expire_item(self, item_id: str) -> None:
        """validity close（用户明确反悔时，不删除历史）。"""
        now = time.time()
        self._db.execute(
            "UPDATE user_model_items SET status='expired', valid_to=?, updated_at=? WHERE item_id=?",
            (now, now, item_id))

    def supersede_item(self, item_id: str, *, transition_event_id: str = "",
                       transition_reason: str = "") -> None:
        """Phase 15D：被当前事实取代 → SUPERSEDED（历史保留，不再 active 检索）。

        Phase 14 Final Closure（INV-C4-1）：必须记录触发 supersede 的 canonical C6
        event id + 原因（真实 utterance），不得只有 status/timestamp。
        """
        now = time.time()
        self._db.execute(
            "UPDATE user_model_items SET status='superseded', valid_to=?, updated_at=?, "
            "transition_event_id=?, transition_reason=? WHERE item_id=?",
            (now, now, transition_event_id or "", (transition_reason or "")[:200], item_id))

    def delete_item(self, item_id: str) -> None:
        """deletion API：删除单条 user model item。"""
        self._db.execute("DELETE FROM user_model_items WHERE item_id=?", (item_id,))

    # -------------------------------------------------- read
    def _active_by_key(self, category: str, key: str) -> List[UserModelItem]:
        rows = self._db.query_all(
            "SELECT * FROM user_model_items WHERE category=? AND key=? AND status='active' "
            "ORDER BY updated_at DESC", (category, key))
        return [UserModelItem.from_row(r) for r in rows]

    def query_active(self, limit: int = 5, category: Optional[str] = None) -> List[UserModelItem]:
        sql = "SELECT * FROM user_model_items WHERE status='active'"
        args: List = []
        if category:
            sql += " AND category=?"
            args.append(category)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        rows = self._db.query_all(sql, args)
        return [UserModelItem.from_row(r) for r in rows]

    def get_active(self, key: str) -> Optional[UserModelItem]:
        rows = self._db.query_all(
            "SELECT * FROM user_model_items WHERE key=? AND status='active' "
            "ORDER BY updated_at DESC LIMIT 1", (key,))
        return UserModelItem.from_row(rows[0]) if rows else None

    def count(self, status: str = "active") -> int:
        return self._db.count("user_model_items") if status == "all" else len(self.query_active(limit=10000))

    @staticmethod
    def _to_json(value: Any) -> str:
        import json
        try:
            return json.dumps(value, ensure_ascii=False, default=str)[:2000]
        except Exception:
            return '"<unserializable>"'
