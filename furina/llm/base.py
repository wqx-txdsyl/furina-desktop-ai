"""LLM adapter 抽象接口（拔插层）。

所有模型通过统一协议暴露：文本对话、结构化输出、图像输入。
模块只依赖 ``LLMAdapter``，不依赖具体厂商（plan/8 §16 显式、可替换）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union

from furina.core import LLMError

ContentPart = Dict[str, Any]  # {"type":"text"|"image_url", ...}


def content(*parts: Union[str, tuple]) -> List[ContentPart]:
    """快速构造 content 数组。

    - ``content("你好")`` -> [{"type":"text","text":"你好"}]
    - ``content(("image", data_uri))`` -> [{"type":"image_url", ...}]
    """
    out: List[ContentPart] = []
    for p in parts:
        if isinstance(p, str):
            out.append({"type": "text", "text": p})
        else:
            kind, value = p
            if kind == "image":
                out.append({"type": "image_url", "image_url": {"url": value}})
            elif kind == "text":
                out.append({"type": "text", "text": value})
    return out


@dataclass
class LLMMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: List[ContentPart]


@dataclass
class LLMResult:
    text: str
    usage: Optional[Dict[str, int]] = None
    raw: Any = None


class LLMAdapter(ABC):
    """模型适配器统一接口。"""

    provider: str = ""

    @abstractmethod
    def chat(self, messages: List[LLMMessage], *, temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> LLMResult:
        """普通对话；messages 可含图像 part。"""

    @abstractmethod
    def structured(self, messages: List[LLMMessage], *, schema: Dict[str, Any],
                   temperature: Optional[float] = None) -> Dict[str, Any]:
        """结构化输出：按 JSON Schema 约束返回 dict。禁止解析自由文本（plan/8 §8）。"""

    @abstractmethod
    def is_available(self) -> bool:
        """是否配置可用（如 api key 是否存在）。"""
