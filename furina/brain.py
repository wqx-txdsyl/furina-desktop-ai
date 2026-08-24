"""Furina Brain —— LLM Thought Loop（plan/8 §10, §13）。

低频、高价值决策层：对话、复杂意图、关系判断、Agent 规划、回忆。
职责边界（plan/8 §5-9）：
- 只输出结构化 Intent（受限枚举），绝不自由文本控制应用。
- 不做高频渲染/动画/输入检测/简单状态更新。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from furina.core import get_logger
from furina.llm import LLMAdapter, LLMMessage, content
from furina.persona import FURINA_PERSONA
from furina.state import CharacterState, Intent, IntentCategory

log = get_logger("brain")

# 允许的动作枚举（plan/8 §9）—— 与行为系统一致，防止 LLM 发明动作
ALLOWED_ACTIONS = [
    "idle", "observe_user", "approach_user", "talk", "play", "rest",
    "eat", "drink", "sleep", "help_user", "run_agent_task", "ask_permission",
]

_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ALLOWED_ACTIONS},
        "emotion": {"type": "string", "enum": ["happy", "proud", "calm", "concerned",
                                               "playful", "sleepy", "annoyed", "curious"]},
        "action": {"type": "string", "enum": ALLOWED_ACTIONS},
        "speech": {"type": "string"},
        "priority": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["intent", "emotion", "action", "speech", "priority", "reason"],
}


@dataclass
class BrainOutput:
    intent: str = "idle"
    emotion: str = "calm"
    action: str = "idle"
    speech: str = ""
    priority: float = 0.5
    reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_intent(self, category: IntentCategory = IntentCategory.INTERACT) -> Intent:
        return Intent(category=category, action=self.intent, priority=self.priority,
                      reason=self.reason, emotion=self.emotion, speech=self.speech)


class FurinaBrain:
    """LLM 大脑：只在 Thought Loop 里被调用。"""

    def __init__(self, llm: LLMAdapter, memory_engine=None, persona: str = FURINA_PERSONA) -> None:
        self.llm = llm
        self.memory = memory_engine
        self.persona = persona

    def think(self, *, state: CharacterState | None = None, user_text: str = "",
              task: str = "", available_actions: Optional[List[str]] = None,
              category: IntentCategory = IntentCategory.INTERACT) -> BrainOutput:
        """一次推理：组合紧凑上下文 → 结构化输出。失败时回退为安全默认。"""
        actions = available_actions or ALLOWED_ACTIONS
        memories = []
        if self.memory:
            mems = self.memory.retrieve(query=user_text or task or "", limit=3)
            memories = [m.content for m in mems]

        user = self._compact_user(state, user_text, task, actions, memories)
        try:
            if not self.llm.is_available():
                raise RuntimeError("LLM 未配置")
            msgs = [
                LLMMessage("system", content(self.persona)),
                LLMMessage("user", content(user)),
            ]
            result = self.llm.structured(msgs, schema=_INTENT_SCHEMA, temperature=0.5)
            return self._coerce(result)
        except Exception as e:  # pragma: no cover - 回退安全默认
            log.warning("brain.think 失败，回退默认: %s", e)
            return BrainOutput(intent="idle", action="idle", speech="", reason=f"llm_err:{e}")

    @staticmethod
    def _compact_user(state: Optional[CharacterState], user_text: str, task: str,
                      actions: list[str], memories: list[str]) -> str:
        """紧凑 prompt：避免状态大段折叠，给一个一次性示例（闪版模型友好）。"""
        lines: list[str] = []
        if task or user_text:
            lines.append(f"用户说/请求：{user_text or task}")
        if state:
            lines.append(f"状态：{state.life.macro.value}/{state.life.activity}, "
                         f"情绪{state.emotion.label}, 用户空闲{state.user_idle_seconds:.0f}秒, "
                         f"窗口:{state.active_window_app}")
        if memories:
            lines.append("相关记忆：" + "；".join(memories[:3]))
        lines.append("允许的意图：" + ", ".join(actions))
        lines.append('请输出 JSON：{"intent":"...","emotion":"...","speech":"一句话中文台词","priority":0-1,'
                     '"reason":"简短理由"}；intent 只能从允许列表里选。')
        lines.append('示例：{"intent":"rest","emotion":"concerned","speech":"哼…先歇一会儿吧。",'
                     '"priority":0.8,"reason":"用户长时间工作"}')
        lines.append("只输出 JSON。")
        return "\n".join(lines)

    @staticmethod
    def _coerce(raw: Dict[str, Any]) -> BrainOutput:
        intent = raw.get("intent", "idle")
        if intent not in ALLOWED_ACTIONS:
            intent = "idle"
        return BrainOutput(
            intent=intent,
            emotion=raw.get("emotion", "calm"),
            action=raw.get("action") if raw.get("action") in ALLOWED_ACTIONS else intent,
            speech=raw.get("speech", ""),
            priority=max(0.0, min(1.0, float(raw.get("priority", 0.5)))),
            reason=raw.get("reason", ""),
            raw=raw,
        )
