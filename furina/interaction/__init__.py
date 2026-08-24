"""互动包：把用户输入翻译成“芙宁娜经历的事情”（plan/4 §34）。"""
from .interaction_types import (
    Hitbox,
    HitboxShape,
    InteractionEvent,
    InteractionZone,
    TouchKind,
)
from .gesture import GestureRecognizer
from .interaction_engine import InteractionEngine

__all__ = [
    "Hitbox",
    "HitboxShape",
    "InteractionEvent",
    "InteractionZone",
    "TouchKind",
    "GestureRecognizer",
    "InteractionEngine",
]
