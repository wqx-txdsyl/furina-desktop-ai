"""Brain 与 Zhipu 结构化解析测试（离线，mock 适配器）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from furina.llm import LLMAdapter, LLMMessage, LLMResult
from furina.llm.base import content
from furina.llm.zhipu import _extract_json
from furina.brain import FurinaBrain, BrainOutput
from furina.state import CharacterState


class FakeAdapter(LLMAdapter):
    provider = "fake"

    def __init__(self, structured_result: Optional[Dict[str, Any]] = None, available: bool = True):
        self._res = structured_result or {}
        self._available = available
        self.built_payloads = []

    def chat(self, messages, *, temperature=None, max_tokens=None) -> LLMResult:
        return LLMResult(text="ok")

    def structured(self, messages, *, schema=None, temperature=None) -> Dict[str, Any]:
        self.built_payloads.append((messages, schema))
        return self._res

    def is_available(self) -> bool:
        return self._available


def test_coerce_valid():
    out = FurinaBrain._coerce({"intent": "rest", "emotion": "concerned",
                               "action": "rest", "speech": "歇歇吧", "priority": 0.8, "reason": "r"})
    assert out.intent == "rest" and out.priority == 0.8 and out.speech == "歇歇吧"


def test_coerce_invalid_intent_clamped():
    out = FurinaBrain._coerce({"intent": "go_and_peek_at_user", "priority": 2.0})
    assert out.intent == "idle"          # 不在枚举 → 回退 idle
    assert out.priority == 1.0           # 超界被钳到 1.0
    assert out.action == "idle"          # 无效 action → 回退 intent


def test_think_returns_structured():
    fake = FakeAdapter(structured_result={"intent": "approach_user", "emotion": "playful",
                                          "action": "approach_user", "speech": "过来陪你",
                                          "priority": 0.7, "reason": "社交需求"})
    b = FurinaBrain(fake, None)
    out = b.think(state=CharacterState(), user_text="陪陪我")
    assert out.intent == "approach_user"
    assert out.speech == "过来陪你"
    # 组合的 prompt 里应含允许意图与示例
    msgs = fake.built_payloads[0][0]
    joined = ""
    for m in msgs:
        for part in m.content:
            if part.get("type") == "text":
                joined += part.get("text", "")
    assert "approach_user" in joined or "rest" in joined
    assert "只输出 JSON" in joined


def test_think_fallback_when_unavailable():
    fake = FakeAdapter(available=False)
    b = FurinaBrain(fake, None)
    out = b.think(user_text="hi")
    assert out.intent == "idle" and out.speech == ""
    assert "llm_err" in out.reason


def test_think_schema_is_required_fields():
    fake = FakeAdapter(structured_result={"intent": "rest"})
    b = FurinaBrain(fake, None)
    b.think(user_text="x")
    schema = fake.built_payloads[0][1]
    assert "intent" in schema["properties"]
    assert set(schema["required"]) == {"intent", "emotion", "action", "speech", "priority", "reason"}


def test_extract_json():
    assert _extract_json('{"a":1}') == {"a": 1}
    assert _extract_json('```json\n{"a":1}\n```') == {"a": 1}
    assert _extract_json('解释：{"intent":"rest"} 完') == {"intent": "rest"}
    import pytest
    with pytest.raises(Exception):
        _extract_json("没有JSON")
