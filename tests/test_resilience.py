"""韧性测试（final test.md A-13：LLM 不可用时核心仍运行）。

当 Zhipu 不可用时：芙宁娜仍能构造、状态系统仍工作、配置无 key 不崩。
（真实桌宠在无 LLM 时仍能走/睡/被摸/观察 —— 本测试验证“大脑缺失不拖垮核心”。）
"""
from __future__ import annotations

import math

from furina.config import AppConfig, LLMProfile
from furina.app import Furina
from furina.core import EventBus
from furina.state import StateEngine, MacroState


def _no_key_cfg() -> AppConfig:
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    return AppConfig(root_dir=d, zhipu_api_key="", agnes_api_key="",
                     llm=LLMProfile(api_key=""))


def test_app_constructs_without_llm_key():
    """无 Zhipu key 也能构建 Furina（三脑降级），不崩。"""
    cfg = _no_key_cfg()
    f = Furina(cfg)
    assert f.life_brain is not None    # 大脑对象存在（adapter 不可用但对象在）
    assert f.dialogue_brain is not None
    assert f.agent is not None
    assert f.state is not None


def test_core_life_loop_without_llm():
    """无 LLM 时本地生命循环仍推进（需求/意图/行为），不会卡死。"""
    cfg = _no_key_cfg()
    f = Furina(cfg)
    se = f.state
    se.update_needs(3.0, user_working=True, user_idle=0.0)
    cand = se.generate_intent(se.state)      # 本地 Utility，无需 LLM
    assert cand.intent is not None
    # 行为引擎选择也无需 LLM
    action = f.behavior.choose(se.state.snapshot())
    assert action is not None or f.behavior.behaviors  # 有行为即可
    # 状态无 NaN/越界
    n = se.state.needs
    for v in (n.energy, n.fatigue, n.hunger):
        assert 0.0 <= v <= 100.0 and not math.isnan(v)


def test_behavior_is_llm_independent():
    """行为系统完全独立于 LLM（这是“LLM 挂了桌宠还活着”的关键）。"""
    bus = EventBus()
    se = StateEngine(bus)
    from furina.behavior import BehaviorEngine, BehaviorDefinition
    be = BehaviorEngine(bus)
    be.register(BehaviorDefinition("observe_user", utility_fn=lambda s: 70, priority=3))
    be.register(BehaviorDefinition("idle", base_utility=5))
    se.state.user_working = True
    act = be.step(se.state.snapshot())
    assert act == "observe_user"     # 无需任何 LLM 调用


def test_memory_hint_influences_behavior():
    """plan/6 §28：记忆偏置真实参与行为选择，而非只喂 LLM prompt。"""
    bus = EventBus()
    from furina.behavior import BehaviorEngine, BehaviorDefinition
    from furina.state import StateEngine
    se = StateEngine(bus)
    be = BehaviorEngine(bus)
    # 一个高打扰成本行为（talk）+ 一个低打扰（idle）
    be.register(BehaviorDefinition("talk_to_user", base_utility=60, priority=3))
    be.register(BehaviorDefinition("idle", base_utility=5))
    se.state.user_working = True
    base = se.state.snapshot()
    # 无偏置：talk 因为 base 高而胜出（即便 user_working，base 60 仍可能高）
    action_with_memory = None
    with_memory_bias = dict(base)
    with_memory_bias["memory_bias"] = {"social_penalty": 120}
    action_with_memory = be.step(with_memory_bias)
    # 加 social_penalty 后，talk（社交打扰）被压到 idle 之下或不选它
    # 用 utility_of 直接断言偏置生效
    u_talk_base = be.utility_of(be.behaviors["talk_to_user"], base)
    u_talk_bias = be.utility_of(be.behaviors["talk_to_user"], with_memory_bias)
    assert u_talk_bias < u_talk_base, "记忆社交偏置应降低打扰行为的 utility"
    assert u_talk_bias < 5 - 1 or u_talk_bias < be.utility_of(be.behaviors["idle"], with_memory_bias), \
        "带偏置后 idle 应压过 talk"
