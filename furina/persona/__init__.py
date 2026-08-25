"""人格包：芙宁娜固定人格 + 动态倾向 + Prompt 组合（legacy-plan/8 §10）。

提示词必须是“可组合的”，不是 5000 行超级大 prompt：
Persona + Current State + Relevant Memories + Current Environment + Available Actions + Current Task。
"""
from .furina_persona import FURINA_PERSONA, compose_request

__all__ = ["FURINA_PERSONA", "compose_request"]
