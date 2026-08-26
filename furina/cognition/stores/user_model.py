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
                    valid_to: float = 0.0, temporal_uncertain: int = 0) -> UserModelItem:
        """新增/更新 item。同 category+key 的旧 active item → superseded（不 overwrite 历史）。

        返回新 item。confidence 由调用方（deterministic extraction）给定，本层不猜。
        Phase 15D：temporal_uncertain=1 表示日期无法确定（绝不编日期）。
        """
        cat = category if category in CATEGORIES else "FACT"
        value_json = self._to_json(value)
        now = time.time()
        # 旧 active 同 key item → supersede（validity close）
        for old in self._active_by_key(cat, key):
            self._db.execute(
                "UPDATE user_model_items SET status='superseded', valid_to=?, updated_at=? "
                "WHERE item_id=?",
                (now, now, old.item_id))
        item_id = f"umi_{int(now*1000)}_{uuid.uuid4().hex[:6]}"
        row = (item_id, cat, key, value_json, float(confidence), source_event_id,
               (source_text_excerpt or "")[:500], now, now, now, float(valid_to), "active",
               int(temporal_uncertain or 0), now)
        self._db.execute(
            "INSERT INTO user_model_items(item_id,category,key,value_json,confidence,"
            "source_event_id,source_text_excerpt,created_at,updated_at,valid_from,valid_to,status,"
            "temporal_uncertain,declared_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        return UserModelItem(
            item_id=item_id, category=cat, key=key, value_json=value_json,
            confidence=float(confidence), source_event_id=source_event_id,
            source_text_excerpt=(source_text_excerpt or "")[:500],
            created_at=now, updated_at=now, valid_from=now, valid_to=float(valid_to),
            status="active", temporal_uncertain=int(temporal_uncertain or 0), declared_at=now)

    # -------------------------------------------------- Phase 15D：PLAN 生命周期
    def set_plan_status(self, key: str, status: str, *, category: str = "PLAN") -> Optional[UserModelItem]:
        """把 ACTIVE PLAN 转移到 COMPLETED/CANCELLED/EXPIRED（不新增互不关联的 plan）。

        '我终于做完了' 的 evidence 关联到既有 plan（按 key），否则不猜。
        """
        st = status if status in PLAN_STATUSES else "ACTIVE"
        rows = self._db.query_all(
            "SELECT * FROM user_model_items WHERE category=? AND key=? AND status='active' "
            "ORDER BY updated_at DESC LIMIT 1", (category, key))
        if not rows:
            return None
        it = UserModelItem.from_row(rows[0])
        self._db.execute(
            "UPDATE user_model_items SET status=?, updated_at=?, valid_to=? WHERE item_id=?",
            (st.lower(), time.time(), time.time(), it.item_id))
        it.status = st.lower()
        it.valid_to = time.time()
        return it

    def complete_plan(self, key: str) -> Optional[UserModelItem]:
        return self.set_plan_status(key, "COMPLETED")

    def cancel_plan(self, key: str) -> Optional[UserModelItem]:
        return self.set_plan_status(key, "CANCELLED")

    def expire_item(self, item_id: str) -> None:
        """validity close（用户明确反悔时，不删除历史）。"""
        now = time.time()
        self._db.execute(
            "UPDATE user_model_items SET status='expired', valid_to=?, updated_at=? WHERE item_id=?",
            (now, now, item_id))

    def supersede_item(self, item_id: str) -> None:
        """Phase 15D：被当前事实取代 → SUPERSEDED（历史保留，不再 active 检索）。"""
        now = time.time()
        self._db.execute(
            "UPDATE user_model_items SET status='superseded', valid_to=?, updated_at=? "
            "WHERE item_id=?",
            (now, now, item_id))

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
