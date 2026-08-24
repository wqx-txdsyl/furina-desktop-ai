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

    # -------------------------------------------------- 衰减（随时间回到稳定基线）
    def decay(self, dt: float = 3.0, rate: float = 0.15) -> None:
        """情绪随时间自然衰减（比如 happiness 82 → 80 → 77 → 74）。
        dt 为经过的秒数；rate 为每秒衰减系数（越接近 0 越慢回稳）。
        """
        st = self.state
        # 各维度向自己的中性值回归
        baseline = {"happiness": 60, "sadness": 5, "anger": 5, "pride": 40,
                    "curiosity": 50, "embarrassment": 8, "loneliness": 15,
                    "excitement": 30, "calm": 70}
        k = rate * min(dt, 10.0) / 3.0
        for dim in DIMENSIONS:
            cur = getattr(st, dim)
            target = baseline.get(dim, 50.0)
            setattr(st, dim, max(0.0, min(100.0, cur + (target - cur) * k)))
        st.clamp()

    # -------------------------------------------------- 派生 label（由主导情绪决定）
    def derive_label(self) -> str:
        """把多维情绪压缩成离散标签（供素材选择/表现层用）。"""
        st = self.state
        scores = {
            "happy": st.happiness * 0.7 + st.excitement * 0.3,
            "excited": st.excitement * 0.8 + st.happiness * 0.2,
            "proud": st.pride * 0.9 + st.happiness * 0.1,
            "curious": st.curiosity * 0.9 + st.excitement * 0.1,
            "sad": st.sadness * 0.9 + st.loneliness * 0.1,
            "annoyed": st.anger * 0.9,
            "sleepy": _sleepiness(st),
            "embarrassed": st.embarrassment * 0.9 + st.anger * 0.1,
            "calm": st.calm * 0.8 + (100 - st.excitement) * 0.2,
        }
        label = max(scores, key=scores.get)
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


def _sleepiness(st: EmotionState) -> float:
    """困倦：由 calm 高 + 无兴奋近似（真正的困倦在 Needs，这里只做情绪侧近似）。"""
    return st.calm * 0.7 + (100 - st.excitement) * 0.3
