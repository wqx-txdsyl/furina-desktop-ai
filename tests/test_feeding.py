"""喂食系统测试（M3）。"""
from __future__ import annotations

from furina.state import CharacterState
from furina.feeding import apply_food, default_food, FOODS


def test_foods_registry():
    assert "cake" in FOODS and "tea" in FOODS and "water" in FOODS
    assert default_food("does_not_exist").name == "面包"


def test_apply_food_reduces_hunger_raises_satisfaction():
    st = CharacterState()
    st.needs.hunger = 80
    st.needs.satisfaction = 40
    st.emotion.mood = 50
    res = apply_food(st, FOODS["cake"])
    assert st.needs.hunger == max(0.0, 80 + FOODS["cake"].hunger_delta)   # 饥饿下降
    assert st.needs.satisfaction > 40
    assert st.emotion.mood > 50
    assert res["ate"] is True and res["reaction"]


def test_food_does_not_go_below_zero():
    st = CharacterState()
    st.needs.hunger = 10
    apply_food(st, FOODS["cake"])
    assert st.needs.hunger >= 0
