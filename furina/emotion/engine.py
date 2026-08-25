"""Emotion Engine（Life Simulation P2 任务 1）—— 确定性情感模块，**不用 LLM**。

职责：Event → 情绪维度变化 → 衰减 → 派生 label/mood → 影响 Behavior Motivation。
不做复杂心理学模型，第一版重点：**可解释、稳定、可调试**。

关键原则：这是“第三个脑”之外的程序化模块，绝不取代 Brain 的高层决策；
它只提供“这件事让我产生了某种感觉”，从而影响候选行为的冲动强度。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from furina.state.state_model import EmotionState

# 情绪维度（与 EmotionState 字段对齐）
DIMENSIONS = ["happiness", "sadness", "anger", "pride", "curiosity",
              "embarrassment", "loneliness", "excitement", "calm"]


# ---------------------------------------------------------------- 事件 → 情绪增量
@dataclass
class EmotionDelta:
    happiness: float = 0.0
    sadness: float = 0.0
    anger: float = 0.0
    pride: float = 0.0
    curiosity: float = 0.0
    embarrassment: float = 0.0
    loneliness: float = 0.0
    excitement: float = 0.0
    calm: float = 0.0
    reason: str = ""

    def as_dict(self) -> dict:
        d = {k: round(v, 2) for k, v in self.__dict__.items() if isinstance(v, (int, float))}
        d["reason"] = self.reason
        return d


# 事件类型（用户/交互/内部/时间）
EVENT_PET = "user_pet"          # 摸头
EVENT_POKE = "user_poke"        # 戳
EVENT_CLICK = "user_click"      # 点击
EVENT_DRAG = "user_drag"        # 拖拽
EVENT_FEED = "user_feed"        # 喂食
EVENT_PRAISE = "user_praise"    # 夸奖
EVENT_IGNORE = "user_ignore"    # 被忽略（用户长时间不理）
EVENT_REJECT = "user_reject"    # 拒绝互动
EVENT_TALK = "user_talk"        # 对话
EVENT_WORK_START = "user_work_start"
EVENT_WORK_END = "user_work_end"
EVENT_RETURN = "user_return"    # 用户回来
EVENT_AGENT_DONE = "agent_done"  # 任务完成
EVENT_FOOD = "food_eaten"       # 吃到好吃的

# 事件 → 情绪增量（确定性，可解释）
EVENT_DELTAS: Dict[str, EmotionDelta] = {
    EVENT_PET:     EmotionDelta(happiness=6, calm=4, loneliness=-4, pride=2, reason="被摸头，温暖"),
    EVENT_POKE:    EmotionDelta(anger=4, excitement=2, happiness=-2, reason="被戳，有点恼"),
    EVENT_CLICK:   EmotionDelta(curiosity=5, excitement=3, reason="被点了一下，好奇"),
    EVENT_DRAG:    EmotionDelta(anger=1, excitement=4, embarrassment=3, reason="被拖拽，有点慌"),
    EVENT_FEED:    EmotionDelta(happiness=6, pride=3, calm=2, sadness=-3, reason="被喂食，开心"),
    EVENT_PRAISE:  EmotionDelta(happiness=8, pride=8, excitement=4, reason="被夸奖，得意"),
    EVENT_IGNORE:  EmotionDelta(loneliness=8, sadness=4, happiness=-3, reason="被冷落，孤单"),
    EVENT_REJECT:  EmotionDelta(sadness=4, embarrassment=5, loneliness=3, reason="被拒绝，受挫"),
    EVENT_TALK:    EmotionDelta(happiness=4, excitement=3, loneliness=-5, reason="对话交流"),
    EVENT_WORK_START: EmotionDelta(curiosity=3, calm=2, reason="用户开始工作"),
    EVENT_WORK_END:  EmotionDelta(happiness=3, excitement=3, reason="用户忙完"),
    EVENT_RETURN:    EmotionDelta(happiness=7, loneliness=-6, excitement=4, reason="用户回来了"),
    EVENT_AGENT_DONE: EmotionDelta(pride=5, happiness=4, reason="帮用户完成了任务"),
    EVENT_FOOD:      EmotionDelta(happiness=5, calm=3, pride=2, reason="吃到好吃的"),
}


# ---------------------------------------------------------------- 衰减（随时间回到稳定基线）
# Phase 13 终审 §4.3：情绪衰减改为**分钟级时间常数**（τ≈10 分钟），
# 不再 ~60s 就把事件效果几乎抹平。普通有意义事件在 5 分钟仍显著（≈61% 残留），30 分钟基本回落（≈5%）。
_EMOTION_TAU_SECONDS = 600.0   # 10 分钟

# 各维度中性基线（decay 目标 + 派生 label 的"无事件参考点"）
_BASELINE = {"happiness": 60, "sadness": 5, "anger": 5, "pride": 40,
             "curiosity": 50, "embarrassment": 8, "loneliness": 15,
             "excitement": 30, "calm": 70}

# 派生 label 的相对-基线显著度阈值：低于它 → calm（默认/无事）
_SALIENCE_MIN = 4.5


def _salience(st: EmotionState) -> Dict[str, float]:
    """相对基线的显著度：当前维度高出中性基线多少（负向维度同样适用）。"""
    return {dim: max(0.0, getattr(st, dim) - _BASELINE[dim]) for dim in DIMENSIONS}


class EmotionEngine:
    """确定性情绪引擎：apply(event) → decay(dt) → 派生 label。"""

    def __init__(self, state: Optional[EmotionState] = None) -> None:
        self.state = state or EmotionState()
        self._recent: Dict[str, float] = {}   # 最近情绪事件（用于 debug）

    # -------------------------------------------------- 应用事件
    def apply(self, event: str, delta: Optional[EmotionDelta] = None) -> EmotionDelta:
        """把一个事件映射为情绪增量，并叠加到 state。"""
        d = delta or EVENT_DELTAS.get(event, EmotionDelta())
        if d is None:
            d = EmotionDelta()
        for dim in DIMENSIONS:
            cur = getattr(self.state, dim)
            setattr(self.state, dim, max(0.0, min(100.0, cur + getattr(d, dim))))
        self.state.clamp()
        self._recent[event] = self._recent.get(event, 0) + 1
        return d

    # -------------------------------------------------- Phase 13 FINAL-R1 §2.2：权威语义事件边界
    def apply_event(self, event: str, tired_hint: float = 0.0,
                    delta: Optional[EmotionDelta] = None) -> EmotionDelta:
        """**生产语义事件唯一入口**：apply 维度变化后**立即派生权威 label**（同线程、同调用栈）。

        这样 praise/reject/feed/poke/agent_done 等事件后的 Dialogue/Body 快照
        读到的是 post-event label，而不是等下一个 medium tick 才 derive。
        维度仍是真相；label 由维度派生（不硬编码 event→label）。
        **必须在运行时 owner 线程调用**（§3 分发边界）。
        """
        d = self.apply(event, delta=delta)
        self.derive_label(tired_hint=tired_hint)
        return d

    # -------------------------------------------------- 衰减（随时间回到稳定基线）
    def decay(self, dt: float = 3.0, rate: float = 0.15) -> None:
        """情绪随时间自然衰减（分钟级：τ=10 分钟 @ rate=0.15）。

        dt 为经过的秒数；rate 保留为兼容参数（越大衰减越快）：τ = 600 × (0.15/rate) 秒。
        """
        import math
        tau = _EMOTION_TAU_SECONDS * (0.15 / max(rate, 1e-3))
        k = 1.0 - math.exp(-dt / tau)   # 精确指数衰减（dt 不变性：k 随 dt 缩放）
        st = self.state
        for dim in DIMENSIONS:
            cur = getattr(st, dim)
            target = _BASELINE[dim]
            setattr(st, dim, max(0.0, min(100.0, cur + (target - cur) * k)))
        st.clamp()

    # -------------------------------------------------- 派生 label（基线-相对显著度，非绝对最大值）
    def derive_label(self, tired_hint: float = 0.0) -> str:
        """把多维情绪压缩成离散标签。

        Phase 13 终审 §4.1/4.2：**基线-相对显著度 + 阈值**，不再用绝对最大值。
        - 默认健康基线 → 全部显著度 ≈ 0 → **calm**（不再被 sleepy 抢占）；
        - 事件只在其维度**明显高出中性基线**时才主导 label（praise→proud/happy、reject→embarrassed/sad、
          poke→annoyed、return→happy）；
        - sleepy 只有在真实困倦信号（tired_hint，来自 Needs，0..1）时才可派生；
          绝不把"平静"误判为"困倦"。
        """
        st = self.state
        sal = _salience(st)
        scores: Dict[str, float] = {
            "happy": sal["happiness"] * 1.0 + sal["excitement"] * 0.4,
            "excited": sal["excitement"] * 1.0 + sal["happiness"] * 0.3,
            "proud": sal["pride"] * 1.2 + sal["happiness"] * 0.2,
            "curious": sal["curiosity"] * 1.0 + sal["excitement"] * 0.2,
            "sad": sal["sadness"] * 1.0 + sal["loneliness"] * 0.6,
            "annoyed": sal["anger"] * 1.2 + sal["embarrassment"] * 0.2,
            "embarrassed": sal["embarrassment"] * 1.0 + sal["sadness"] * 0.4,
            # 困倦必须有真实 tired 信号才参与竞争（情绪维度本身不足以判定 sleepy）。
            # FINAL-R1：tired_hint 需 **明显困倦**（>0.5，对应 sleepiness+fatigue>100）才可能派生 sleepy；
            # 健康基线（sleepiness10+fatigue20→0.15）绝不误判 sleepy。
            "sleepy": max(0.0, (tired_hint - 0.5)) * 100.0 * 0.9 + sal["calm"] * 0.2,
        }
        best = max(scores, key=scores.get)
        # 无事/无显著情绪 → calm（默认健康基线）
        if scores[best] < _SALIENCE_MIN:
            label = "calm"
        else:
            label = best
        st.label = label
        # 派生 mood / valence / arousal（兼容现有接口）
        st.mood = max(0.0, min(100.0, st.happiness * 0.5 + st.calm * 0.2 + (100 - st.sadness) * 0.3))
        st.valence = max(0.0, min(1.0, (st.happiness + (100 - st.sadness)) / 200))
        st.arousal = max(0.0, min(1.0, (st.excitement + st.anger) / 200))
        return label

    # -------------------------------------------------- 情绪倾向 → 行为冲动（低频，给 Motivation 用）
    def behavior_tendency(self) -> Dict[str, float]:
        """把情绪折算成对行为方向的冲动（0..1），供 Behavior Motivation 加权。"""
        st = self.state
        return {
            "play_bias": st.happiness * 0.4 + st.excitement * 0.6,       # 开心/激动 → 想玩
            "approach_bias": st.happiness * 0.3 + st.curiosity * 0.5 + (100 - st.loneliness) * 0.2,
            "explore_bias": st.curiosity * 0.8 + st.excitement * 0.2,
            "rest_bias": (100 - st.excitement) * 0.5 + (100 - st.calm) * 0.3,
            "talk_bias": st.happiness * 0.3 + (100 - st.loneliness) * 0.4 + st.curiosity * 0.3,
            "sad_bias": st.sadness,
        }
