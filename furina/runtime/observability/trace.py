"""Phase 13 Observability —— RuntimeTrace + 环形 Trace 记录（观察只读，非模拟器）。

Trace 只记录**真实系统发生的事**，不构造假状态。默认内存缓冲，不落库。
所有 summary 经 `redact()` 脱敏（不记录 api key / authorization / 完整 prompt）。
"""
from __future__ import annotations

import re
import time
import threading
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# 敏感字段（key/authorization/secret/token/password）—— 不进 summary
_SENSITIVE_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer\s+[A-Za-z0-9._\-]+|"
    r"secret|token|password|sk-[A-Za-z0-9]+|zhipu|glm-|model\s+=)"
)


def redact(text: Any) -> str:
    """把文本中可能的密钥/头信息替换为占位符。"""
    if text is None:
        return ""
    s = str(text)
    s = _SENSITIVE_RE.sub("***", s)
    # 长 token 形串（常见）也可裁剪
    return s[:2000]


@dataclass
class RuntimeTrace:
    """一次真实子系统的"因果阶段性发生"。"""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    root_trace_id: str = ""
    parent_trace_id: str = ""
    timestamp: float = field(default_factory=time.time)

    trigger_type: str = ""          # USER_MESSAGE / INTERACT / FEED / LIFE / AGENT / SPATIAL / ...
    trigger_source: str = ""        # harness / window / scheduler / app / ...
    subsystem: str = ""             # dialogue / life / interaction / memory / relationship / emotion / agent / spatial
    stage: str = ""                 # APPRAISAL / LLM_REQUEST / LLM_RESULT / VALIDATOR / FRAME / ...

    input_summary: str = ""         # 脱敏后的输入摘要（非完整 prompt）
    output_summary: str = ""        # 脱敏后的输出摘要

    model: str = ""                 # glm-4v-flash / local-fallback / ...
    fallback: bool = False
    success: bool = True
    latency_ms: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["extra"] = dict(self.extra)
        return d


class TraceRecorder:
    """线程安全的内存环形 Trace 缓冲。默认 300，事件驱动。"""

    def __init__(self, ring_size: int = 300) -> None:
        self._traces: List[RuntimeTrace] = []
        self._ring_size = max(50, ring_size)
        self._lock = threading.RLock()
        self._count = 0
        self._roots: List[str] = []

    # -------------------------------------------------- 记录
    def record(self, trace: RuntimeTrace) -> RuntimeTrace:
        with self._lock:
            self._traces.append(trace)
            if len(self._traces) > self._ring_size:
                self._traces = self._traces[-self._ring_size:]
            self._count += 1
            if trace.root_trace_id and trace.root_trace_id not in self._roots:
                self._roots.append(trace.root_trace_id)
        return trace

    def start_root(self, *, trigger_type: str, trigger_source: str = "",
                   subsystem: str = "", stage: str = "", input_summary: str = "",
                   output_summary: str = "", model: str = "", extra: dict | None = None) -> RuntimeTrace:
        root = uuid.uuid4().hex[:10]
        t = RuntimeTrace(root_trace_id=root, trigger_type=trigger_type,
                         trigger_source=trigger_source, subsystem=subsystem, stage=stage,
                         input_summary=redact(input_summary), output_summary=redact(output_summary),
                         model=model, extra=extra or {})
        return self.record(t)

    def child(self, parent: RuntimeTrace, *, subsystem: str, stage: str,
              input_summary: str = "", output_summary: str = "", model: str = "",
              fallback: bool = False, success: bool = True, latency_ms: float = 0.0,
              extra: dict | None = None) -> RuntimeTrace:
        t = RuntimeTrace(root_trace_id=parent.root_trace_id, parent_trace_id=parent.trace_id,
                         trigger_type=parent.trigger_type, trigger_source=parent.trigger_source,
                         subsystem=subsystem, stage=stage,
                         input_summary=redact(input_summary), output_summary=redact(output_summary),
                         model=model, fallback=fallback, success=success, latency_ms=latency_ms,
                         extra=extra or {})
        return self.record(t)

    def child_to_root(self, root_trace_id: str, *, subsystem: str, stage: str,
                      input_summary: str = "", output_summary: str = "", model: str = "",
                      fallback: bool = False, success: bool = True, latency_ms: float = 0.0,
                      extra: dict | None = None, trigger_type: str = "", trigger_source: str = "") -> RuntimeTrace:
        """§11：后台线程经显式 root_trace_id 关联（跨线程传播，不依赖"当前全局 trace"）。"""
        t = RuntimeTrace(root_trace_id=root_trace_id, parent_trace_id=root_trace_id,
                         trigger_type=trigger_type, trigger_source=trigger_source,
                         subsystem=subsystem, stage=stage,
                         input_summary=redact(input_summary), output_summary=redact(output_summary),
                         model=model, fallback=fallback, success=success, latency_ms=latency_ms,
                         extra=extra or {})
        return self.record(t)

    # -------------------------------------------------- 读取
    def recent(self, n: int = 50) -> List[RuntimeTrace]:
        with self._lock:
            return list(self._traces[-n:])

    def chain(self, root_trace_id: str) -> List[RuntimeTrace]:
        with self._lock:
            return [t for t in self._traces if t.root_trace_id == root_trace_id]

    def event_count(self) -> int:
        return self._count

    def clear(self) -> None:
        with self._lock:
            self._traces = []
            self._count = 0
            self._roots = []
