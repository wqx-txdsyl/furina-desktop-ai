"""喂食系统（plan/4 §17, §22-23，plan/1 §12 食物）。

食物不是图片，是“物体”，带 taste/营养/心情效应。用户喂食后：
她按 饥饿/食物类型/心情/当前活动 决定反应；吃了则 饥饿↓ 满足↑，并形成记忆。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from furina.state import CharacterState


@dataclass(frozen=True)
class Food:
    name: str
    hunger_delta: float      # 饥饿变化（负=减少）
    satisfaction_delta: float  # 满足感变化
    mood_delta: float        # 心情变化
    taste: str = "normal"    # sweet / bitter / neutral
    emoji: str = ""


# 常见食物（plan/4 §17, §22）
FOODS: Dict[str, Food] = {
    "cake": Food("蛋糕", hunger_delta=-35, satisfaction_delta=20, mood_delta=12, taste="sweet", emoji="🍰"),
    "tea": Food("茶", hunger_delta=-8, satisfaction_delta=12, mood_delta=8, taste="neutral", emoji="🍵"),
    "macaron": Food("马卡龙", hunger_delta=-20, satisfaction_delta=15, mood_delta=10, taste="sweet", emoji="🧁"),
    "bread": Food("面包", hunger_delta=-30, satisfaction_delta=10, mood_delta=5, taste="neutral", emoji="🍞"),
    "water": Food("水", hunger_delta=-5, satisfaction_delta=5, mood_delta=3, taste="neutral", emoji="💧"),
}


def apply_food(state: CharacterState, food: Food, *, hungry: bool = True) -> dict:
    """应用食物效应；返回 (是否吃掉, 反应描述, 台词)。"""
    n = state.needs
    n.hunger = max(0.0, n.hunger + food.hunger_delta)
    n.satisfaction = min(100.0, n.satisfaction + food.satisfaction_delta)
    state.emotion.mood = min(100.0, state.emotion.mood + food.mood_delta)

    if food.taste == "sweet":
        state.emotion.label = "happy"
        line = f"嗯嗯……{food.name}真不错，算你有心~"
    elif not hungry:
        line = "本神现在还不饿啦。"
    else:
        state.emotion.label = "satisfied"
        line = f"多谢款待，{food.name}，味道还凑合。"

    return {
        "ate": True,
        "reaction": line,
        "hunger": round(n.hunger, 1),
        "satisfaction": round(n.satisfaction, 1),
        "mood": round(state.emotion.mood, 1),
    }


def default_food(name: str) -> Food:
    return FOODS.get(name, FOODS["bread"])
