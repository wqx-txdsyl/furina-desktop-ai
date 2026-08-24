"""adapter 注册表（拔插）。"""
from __future__ import annotations

from typing import Dict, Type

from .base import LLMAdapter


class _Registry:
    def __init__(self) -> None:
        self._map: Dict[str, Type[LLMAdapter]] = {}

    def register(self, name: str, cls: Type[LLMAdapter]) -> None:
        self._map[name] = cls

    def get(self, name: str) -> Type[LLMAdapter]:
        if name not in self._map:
            raise KeyError(f"未知 LLM provider: {name}（已注册: {list(self._map)}）")
        return self._map[name]


_registry = _Registry()


def register_adapter(name: str, cls: Type[LLMAdapter]) -> None:
    _registry.register(name, cls)


def get_adapter(name: str) -> Type[LLMAdapter]:
    return _registry.get(name)
