"""OpenAI 兼容适配器（通用拔插）。

用于接任意 OpenAI-compatible /chat/completions 端点：Zhipu、DeepSeek、MoonShot、阿里百炼、
vLLM 本地、Ollama 等。这使“换更快的模型”无需改代码，只改 .env 配置。

    FURINA_LLM_PROVIDER=openai_compat
    FURINA_LLM_BASE_URL=https://api.deepseek.com/v1
    FURINA_LLM_MODEL=deepseek-chat
    FURINA_LLM_API_KEY=...
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from furina.config import LLMProfile
from furina.core import LLMError, get_logger
from .base import LLMAdapter, LLMMessage, LLMResult

log = get_logger("llm.openai_compat")


class OpenAICompatAdapter(LLMAdapter):
    provider = "openai_compat"

    def __init__(self, profile: LLMProfile) -> None:
        self.profile = profile
        self._client = httpx.Client(base_url=profile.base_url, timeout=90.0)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.profile.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, messages: List[LLMMessage], temperature: float, max_tokens: int,
                 response_format: Optional[dict] = None) -> Dict[str, Any]:
        msgs = []
        for m in messages:
            if isinstance(m, dict):
                item = {"role": m.get("role"), "content": m.get("content")}
            else:
                item: Dict[str, Any] = {"role": m.role}
                if len(m.content) == 1 and m.content[0]["type"] == "text":
                    item["content"] = m.content[0]["text"]
                else:
                    item["content"] = m.content
            msgs.append(item)
        payload: Dict[str, Any] = {
            "model": self.profile.model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        return payload

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            r = self._client.post("/chat/completions", headers=self._headers(), json=payload)
        except httpx.HTTPError as e:
            raise LLMError(f"openai_compat 网络错误: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"openai_compat {r.status_code}: {r.text[:300]}")
        return r.json()

    def chat(self, messages: List[LLMMessage], *, temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> LLMResult:
        t = self.profile.temperature if temperature is None else temperature
        mt = self.profile.max_tokens if max_tokens is None else max_tokens
        data = self._post(self._payload(messages, t, mt))
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"openai_compat 响应异常: {str(data)[:200]}") from e
        return LLMResult(text=text, usage=data.get("usage"), raw=data)

    def structured(self, messages: List[LLMMessage], *, schema: Dict[str, Any],
                   temperature: Optional[float] = None) -> Dict[str, Any]:
        t = self.profile.temperature if temperature is None else temperature
        # 通用做法：优先 json_schema（部分端点可用），否则 json_object。
        try:
            payload = self._payload(messages, t, self.profile.max_tokens)
            payload["response_format"] = {"type": "json_schema",
                                          "json_schema": {"name": "resp", "schema": schema}}
            text = self._post(payload)["choices"][0]["message"]["content"]
            return _extract_json(text)
        except Exception:
            # 轻量模型不支持 json_schema → 用 json_object + 提示词，并健壮提取
            messages2 = self._with_json_instruction(messages, schema)
            payload = self._payload(messages2, t, self.profile.max_tokens,
                                    response_format={"type": "json_object"})
            text = self._post(payload)["choices"][0]["message"]["content"]
            return _extract_json(text)

    def _with_json_instruction(self, msgs, schema) -> List[Dict[str, Any]]:
        props = schema.get("properties", {})
        instr = (f"请严格只输出一个 JSON 对象，必须包含字段：{', '.join(props.keys())}，"
                 f"除 JSON 外不要任何文字。")
        out: List[Dict[str, Any]] = []
        for m in msgs:
            if isinstance(m, dict):
                role = m.get("role")
                content_val = m.get("content")
            else:
                role = m.role
                content_val = m.content
            if isinstance(content_val, list) and len(content_val) == 1 and content_val[0].get("type") == "text":
                item = {"role": role, "content": content_val[0]["text"]}
            else:
                item = {"role": role, "content": content_val}
            out.append(item)
        if out and out[0].get("role") == "system":
            out[0]["content"] = out[0]["content"] + "\n" + instr
        else:
            out.append({"role": "user", "content": instr})
        return out

    def is_available(self) -> bool:
        return bool(self.profile.api_key)


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
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
