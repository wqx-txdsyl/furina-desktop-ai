"""智谱 GLM adapter —— 默认模型 glm-4v-flash（免费，视觉+对话）。

OpenAI 兼容端点：open.bigmodel.cn/api/paas/v4/chat/completions。
- 图片以 ``image_url`` + data URI 传递，已验证可用。
- 结构化输出用 ``response_format.json_schema`` 约束（plan/8 §8 禁自由文本控制）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from furina.config import LLMProfile
from furina.core import LLMError, get_logger
from .base import LLMAdapter, LLMMessage, LLMResult

log = get_logger("llm.zhipu")


class ZhipuAdapter(LLMAdapter):
    provider = "zhipu"

    def __init__(self, profile: LLMProfile) -> None:
        self.profile = profile
        self._client = httpx.Client(base_url=profile.base_url, timeout=120.0)

    # ------------------------------------------------------ helpers
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.profile.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, messages: List[LLMMessage], temperature: float, max_tokens: int) -> Dict[str, Any]:
        msgs = []
        for m in messages:
            item: Dict[str, Any] = {"role": m.role}
            # 单文本块可简化为字符串，多模态保持数组
            if len(m.content) == 1 and m.content[0]["type"] == "text":
                item["content"] = m.content[0]["text"]
            else:
                item["content"] = m.content
            msgs.append(item)
        return {
            "model": self.profile.model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            r = self._client.post("/chat/completions", headers=self._headers(), json=payload)
        except httpx.HTTPError as e:
            raise LLMError(f"Zhipu 网络错误: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"Zhipu {r.status_code}: {r.text[:300]}")
        return r.json()

    # ------------------------------------------------------ interface
    def chat(self, messages: List[LLMMessage], *, temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> LLMResult:
        t = self.profile.temperature if temperature is None else temperature
        mt = self.profile.max_tokens if max_tokens is None else max_tokens
        data = self._post(self._payload(messages, t, mt))
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Zhipu 响应异常: {str(data)[:200]}") from e
        return LLMResult(text=text, usage=data.get("usage"), raw=data)

    def structured(self, messages: List[LLMMessage], *, schema: Dict[str, Any],
                   temperature: Optional[float] = None) -> Dict[str, Any]:
        t = self.profile.temperature if temperature is None else temperature
        # 对轻量模型(json_schema 可能不生效)，用 json_object + 提示词显式要求 JSON，
        # 并做健壮提取（找第一个 { 到最后一个 }）。
        payload = self._payload(messages, t, self.profile.max_tokens)
        # 追加 JSON 指令到系统/用户侧
        payload["messages"] = self._with_json_instruction(payload["messages"], schema)
        payload["response_format"] = {"type": "json_object"}
        data = self._post(payload)
        try:
            text = data["choices"][0]["message"]["content"]
            return _extract_json(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise LLMError(f"Zhipu 结构化输出解析失败: {str(data)[:200]}") from e

    def _with_json_instruction(self, msgs: List[Dict[str, Any]], schema: Dict[str, Any]) -> List[Dict[str, Any]]:
        """只注入“字段名 + 必填”的简短 JSON 要求（闪版模型易被复杂 schema 带偏）。"""
        props = schema.get("properties", {})
        fields = ", ".join(props.keys())
        instr = (f"请严格只输出一个 JSON 对象，不要输出代码块或解释。"
                 f"必须包含字段：{fields}。除 JSON 外不要任何文字。")
        if msgs and msgs[0].get("role") == "system" and isinstance(msgs[0].get("content"), str):
            msgs[0]["content"] = msgs[0]["content"] + "\n" + instr
        else:
            msgs.append({"role": "user", "content": instr})
        return msgs

    def is_available(self) -> bool:
        return bool(self.profile.api_key)


def _extract_json(text: str) -> Dict[str, Any]:
    """抽取出 JSON 对象（容忍模型在前后加了代码块/解释）。"""
    text = text.strip()
    # 去掉 ```json ``` 围栏
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.lstrip()
    s = text.find("{")
    e = text.rfind("}")
    if s == -1 or e == -1 or e < s:
        raise json.JSONDecodeError("no object", text, 0)
    return json.loads(text[s : e + 1])
