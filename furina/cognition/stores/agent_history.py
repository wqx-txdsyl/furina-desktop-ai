"""C7 — Agent Task History（agent_tasks / agent_task_steps / agent_artifacts）。

- task_id stable；生命周期 PLANNED → RUNNING → COMPLETED_VERIFIED/FAILED/UNVERIFIED/CANCELLED；
- 事实必须来自真实执行/Verify（ok != verified；verified 来自 filesystem/观察 truth）；
- Tool args 写库前 redaction；
- "notes.md 放哪了" 类问题必须可从本 store 精确回答（不依赖 Memory semantic guessing）。
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from furina.core import get_logger
from ..models import AgentArtifact, AgentTask, AgentTaskStep
from .base import CognitionDB, redact_args

log = get_logger("cognition.agent_history")

TASK_STATUSES = ("PLANNED", "RUNNING", "COMPLETED_VERIFIED", "FAILED", "UNVERIFIED", "CANCELLED")


class AgentTaskHistoryStore:
    """C7 唯一写 owner（基于 verified Agent 结果；worker 不直接写，经 owner persist）。"""

    def __init__(self, db: CognitionDB) -> None:
        self._db = db

    # -------------------------------------------------- task
    def create_task(self, task_id: str = "", *, original_request: str = "",
                    goal: str = "", status: str = "PLANNED") -> str:
        tid = task_id or f"task_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        self._db.execute(
            "INSERT INTO agent_tasks(task_id,original_request,goal,status,started_at) "
            "VALUES(?,?,?,?,?)",
            (tid, (original_request or "")[:1000], (goal or "")[:1000], status, time.time()))
        return tid

    def set_status(self, task_id: str, status: str, *, error: str = "",
                   verified: Optional[bool] = None, result_summary: str = "") -> None:
        st = status if status in TASK_STATUSES else "FAILED"
        updates = ["status=?"]
        args: List = [st]
        if error:
            updates.append("error=?")
            args.append(error[:1000])
        if verified is not None:
            updates.append("verified=?")
            args.append(1 if verified else 0)
        if result_summary:
            updates.append("result_summary=?")
            args.append(result_summary[:1000])
        if st in ("COMPLETED_VERIFIED", "FAILED", "UNVERIFIED", "CANCELLED"):
            updates.append("finished_at=?")
            args.append(time.time())
        args.append(task_id)
        self._db.execute(
            f"UPDATE agent_tasks SET {', '.join(updates)} WHERE task_id=?", args)

    def set_plan(self, task_id: str, plan_json: str, permission_summary: str = "") -> None:
        self._db.execute(
            "UPDATE agent_tasks SET plan_json=?, permission_summary=? WHERE task_id=?",
            (plan_json or "{}", (permission_summary or "")[:500], task_id))

    def complete_task(self, task_id: str, *, verified: bool, result_summary: str = "",
                      error: str = "") -> None:
        if verified:
            self.set_status(task_id, "COMPLETED_VERIFIED", verified=True,
                            result_summary=result_summary)
        else:
            self.set_status(task_id, "UNVERIFIED", verified=False, error=error)

    # -------------------------------------------------- steps
    def add_step(self, task_id: str, step_index: int, *, tool: str, args: Dict[str, Any],
                 capability: str = "", permission_level: str = "", status: str = "PLANNED",
                 verified: bool = False, result: Optional[Dict[str, Any]] = None,
                 error: str = "") -> None:
        """args 写库前必须 redaction。"""
        import json as _json
        red = redact_args(args or {})
        try:
            args_s = _json.dumps(red, ensure_ascii=False, default=str)[:2000]
        except Exception:
            args_s = "{}"
        try:
            res_s = _json.dumps(result or {}, ensure_ascii=False, default=str)[:2000]
        except Exception:
            res_s = "{}"
        self._db.execute(
            "INSERT OR REPLACE INTO agent_task_steps(task_id,step_index,capability,tool,"
            "args_redacted_json,permission_level,status,verified,result_json,error) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (task_id, int(step_index), (capability or "")[:100], (tool or "")[:100],
             args_s, (permission_level or "")[:50], status, 1 if verified else 0,
             res_s, (error or "")[:1000]))

    # -------------------------------------------------- artifacts
    def add_artifact(self, task_id: str, artifact_type: str, path: str, *,
                     exists_verified: bool, metadata: Optional[Dict[str, Any]] = None) -> None:
        import json as _json
        try:
            meta_s = _json.dumps(metadata or {}, ensure_ascii=False, default=str)[:1000]
        except Exception:
            meta_s = "{}"
        self._db.execute(
            "INSERT INTO agent_artifacts(task_id,artifact_type,path,exists_verified,metadata_json) "
            "VALUES(?,?,?,?,?)",
            (task_id, (artifact_type or "")[:50], (path or "")[:1000],
             1 if exists_verified else 0, meta_s))

    # -------------------------------------------------- queries
    def get_task(self, task_id: str) -> Optional[AgentTask]:
        row = self._db.query_one("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,))
        return AgentTask.from_row(row) if row is not None else None

    def query_recent(self, limit: int = 5) -> List[AgentTask]:
        rows = self._db.query_all("SELECT * FROM agent_tasks ORDER BY started_at DESC LIMIT ?",
                                  (limit,))
        return [AgentTask.from_row(r) for r in rows]

    def find_latest_by_artifact(self, filename: str, limit: int = 5) -> List[AgentTask]:
        """按 artifact path/名称精确查询任务（"notes.md 放哪了" 的精确答案来源）。"""
        rows = self._db.query_all(
            "SELECT DISTINCT t.* FROM agent_tasks t JOIN agent_artifacts a ON t.task_id=a.task_id "
            "WHERE a.path LIKE ? OR a.path LIKE ? ORDER BY t.started_at DESC LIMIT ?",
            (f"%{filename}%", f"%/{filename}", limit))
        return [AgentTask.from_row(r) for r in rows]

    def find_latest_by_goal(self, keyword: str, limit: int = 5) -> List[AgentTask]:
        rows = self._db.query_all(
            "SELECT * FROM agent_tasks WHERE goal LIKE ? OR original_request LIKE ? "
            "ORDER BY started_at DESC LIMIT ?",
            (f"%{keyword}%", f"%{keyword}%", limit))
        return [AgentTask.from_row(r) for r in rows]

    def steps(self, task_id: str) -> List[AgentTaskStep]:
        rows = self._db.query_all(
            "SELECT * FROM agent_task_steps WHERE task_id=? ORDER BY step_index ASC", (task_id,))
        out: List[AgentTaskStep] = []
        for r in rows:
            out.append(AgentTaskStep(
                task_id=r["task_id"], step_index=int(r["step_index"]),
                capability=r["capability"], tool=r["tool"],
                args_redacted_json=r["args_redacted_json"],
                permission_level=r["permission_level"], status=r["status"],
                verified=bool(r["verified"]), result_json=r["result_json"], error=r["error"]))
        return out

    def artifacts(self, task_id: str) -> List[AgentArtifact]:
        rows = self._db.query_all(
            "SELECT * FROM agent_artifacts WHERE task_id=? ORDER BY artifact_id ASC", (task_id,))
        return [AgentArtifact(
            task_id=r["task_id"], artifact_type=r["artifact_type"], path=r["path"],
            exists_verified=bool(r["exists_verified"]), metadata_json=r["metadata_json"])
            for r in rows]

    # -------------------------------------------------- deletion API
    def delete_task(self, task_id: str) -> None:
        self._db.execute("DELETE FROM agent_task_steps WHERE task_id=?", (task_id,))
        self._db.execute("DELETE FROM agent_artifacts WHERE task_id=?", (task_id,))
        self._db.execute("DELETE FROM agent_tasks WHERE task_id=?", (task_id,))

    def count(self) -> int:
        return self._db.count("agent_tasks")

    # -------------------------------------------------- 不变式
    def redaction_active(self) -> bool:
        """steps 落库走 redact_args（本 store 唯一写入路径）。"""
        return True
