"""LLM 包：可拔插 adapter（默认智谱 GLM，视觉+对话）。"""
from .base import LLMAdapter, LLMMessage, LLMResult, content
from .registry import get_adapter, register_adapter
from .zhipu import ZhipuAdapter
from .openai_compat import OpenAICompatAdapter

# 默认注册
register_adapter("zhipu", ZhipuAdapter)
register_adapter("openai_compat", OpenAICompatAdapter)

__all__ = [
    "LLMAdapter",
    "LLMMessage",
    "LLMResult",
    "content",
    "get_adapter",
    "register_adapter",
    "ZhipuAdapter",
]
