"""状态引擎：在 Medium Tick 更新需求、评估注意力、生成意图（plan/1, plan/3）。

“本地规则/Utility”部分（plan/3 §15 本地环路）：
Needs → Attention → Evaluate Needs → Intent candidates(utility+priority) → 选一。
真正复杂意图留给 LLM（Thought Loop）。本层**不决定行为**，只产出意图候选，
交由 Behavior/Director 裁决（plan/8 §3）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from furina.core import EventBus, EventType, get_logger
from .state_model import (
    AttentionState,
    AttentionTarget,
    CharacterState,
    Intent,
    IntentCategory,
    MacroState,
    NeedsState,
)

log = get_logger("state")


# ---------------------------------------------------------------- 稳态参数（homeostasis）
# 各需求的"平衡基线"：被行为满足后，随时间向此值回升（重新积累，而非永久清零）。
_BASELINE = {
    "boredom": 28.0, "playfulness": 38.0, "curiosity": 50.0, "satisfaction": 62.0,
    "social_need": 45.0, "energy": 75.0, "sleepiness": 12.0, "hunger": 22.0,
    "fatigue": 25.0, "work_interest": 50.0,
}


# 驱动型需求的"积累峰值"：适度上限（~55-70），行为释放后降到 ~40 再缓慢回升
_DRIVE_PEAK = {
    "playfulness": 58.0, "curiosity": 66.0, "boredom": 72.0, "social_need": 78.0,
}


def _drift(value: float, rate: float, dt: float) -> float:
    """按 rate（每 dt 的变化）移动 value；自然积累（不入基线，仅时间漂移）。"""
    return value + rate * dt


def _rising_drive(n, field: str, peak: float, k: float) -> None:
    """驱动型需求向上积累：越久没被行为释放，越接近 peak（但封顶，不贴 100）。

    这是"积累→达到驱动阈值→行为释放→下降→重新积累"的振荡来源。
    当 behavior 已把它降下（曲线下降），这里负责让它慢慢回升。
    """
    cur = getattr(n, field)
    if cur < peak:
        diff = peak - cur
        setattr(n, field, cur + diff * min(1.0, k))


def _recharge(n, field: str, baseline: float, k: float) -> None:
    """稳态再生：字段若低于基线，则向基线回升；距离基线越远 => 越快（非线性）。

    这是"需求重新积累"的核心 —— 让一次 play 不会把 boredom 永久清空；
    而是 boredom 会随时间重新积累，从而再次驱动 play。
    """
    cur = getattr(n, field)
    if cur < baseline:
        # 越远离基线(低于基线越多)回升越快；靠近基线时变慢（diminishing recharge）
        diff = baseline - cur
        setattr(n, field, cur + diff * min(1.0, k))
    # 高于基线时不强制拉回（让"积累型"需求自然走 _drift 的方向）


# ---------------------------------------------------------------- 优先级
# plan/3 §18 —— 行为优先级（常量，非枚举，避免过度抽象）
P_CRITICAL = 0      # 生存 / Runtime
P_USER_REQUEST = 1  # 用户明确请求
P_IMPORTANT = 2     # 重要提醒
P_NEED = 3          # 角色需求
P_SOCIAL = 4        # 社交行为
P_SELF = 5          # 自主生活
P_MICRO = 6         # 微动作


@dataclass
class IntentCandidate:
    intent: Intent
    utility: float = 0.0


# 常见开发/办公应用 → 用户是否在工作（plan/1 §21 感知）
_WORK_APPS = ("code", "vscode", "winword", "excel", "powerpnt", "chrome", "msedge", "firefox",
              "pycharm", "idea", "terminal", "conhost", "notepad", "obsidian", "typora")
_STUDY_TITLE = ("论文", "文档", "报告", "学习", "教程", "题目", "ppt", "word", "excel")


def classify_activity(app: str, title: str = "") -> dict:
    """把窗口分类为用户活动（plan/1 §21，§4 感知）。"""
    a = (app or "").lower()
    t = (title or "").lower()
    if any(k in a for k in ("code", "vscode", "pycharm", "idea", "terminal", "conhost")):
        return {"working": True, "category": "coding", "label": "编程"}
    if any(k in a for k in ("winword", "word", "wps")):
        return {"working": True, "category": "writing", "label": "写作"}
    if any(k in a for k in ("excel", "et")):
        return {"working": True, "category": "sheet", "label": "表格"}
    if any(k in a for k in ("powerpnt", "ppt")):
        return {"working": True, "category": "slides", "label": "演示"}
    if any(k in a for k in ("chrome", "msedge", "firefox")):
        return {"working": False, "category": "browse", "label": "浏览器"}
    if any(k in t for k in _STUDY_TITLE):
        return {"working": True, "category": "study", "label": "学习"}
    return {"working": False, "category": "other", "label": "其他"}


class StateEngine:
    """负责状态更新 + Needs 结算 + 注意力 + Utility 意图生成。"""

    def __init__(self, bus: EventBus, dt_medium: float = 3.0) -> None:
        self.bus = bus
        self.state = CharacterState()
        self._cooldowns: Dict[str, float] = {}   # 意图 -> 下次允许时间
        self.long_term_goal = "understand_user"  # plan/3 §23 长期目标偏置

    # ---- 需求漂移（被动，本地，无需 LLM） ----
    def update_needs(self, dt: float, user_working: bool, user_idle: float) -> None:
        n = self.state.needs
        # ---- 自然积累（随时间变化；距离基线越远变化越缓 = 类稳态 homeostasis）----
        # 疲惫：工作积累、休息恢复
        if user_working:
            n.fatigue = _drift(n.fatigue, +0.55, dt)
            n.boredom = _drift(n.boredom, +0.4, dt)
            # social_need 不在此无界积累（由上方 rising_drive 封顶积累，避免跑到 100 霸占系统）
            n.work_interest = _drift(n.work_interest, +0.3, dt)
        else:
            n.fatigue = _drift(n.fatigue, +0.06, dt)   # 不忙 fatigue 温和回升（慢，不立刻清空）
            n.boredom = _drift(n.boredom, -0.2, dt)    # 不忙无聊缓和（闲适，但不过度降）
            n.work_interest = _drift(n.work_interest, -0.2, dt)
        n.energy = _drift(n.energy, -0.18, dt)          # 精力缓慢消耗
        n.sleepiness = _drift(n.sleepiness, +0.07, dt)  # 困倦积累
        n.hunger = _drift(n.hunger, +0.11, dt)          # 饥饿积累

        # ---- 稳态再生（homeostasis）：被行为"满足/消耗"的需求随时间**重新积累**回基线。
        # 关键：距离基线越远 → 恢复越快（非线性），避免"一次行为永久清空某需求"。
        # 对"动机型"需求（curiosity/playfulness/satisfaction/boredom），不仅要回到基线，
        # 还要**向上积累**成驱动（积累到一定程度才产生 Motivation，行为释放后又重新积累）。
        # 注意：social_need 不再用无界 _drift 积累，而是由 rising_drive 向上限积累（封顶），
        # 避免它跑到 100 并永远霸占系统（crowd-out）。
        _recharge(n, "boredom", _BASELINE["boredom"], 0.03 * dt)
        _recharge(n, "playfulness", _BASELINE["playfulness"], 0.02 * dt)
        _recharge(n, "curiosity", _BASELINE["curiosity"], 0.02 * dt)
        _recharge(n, "satisfaction", _BASELINE["satisfaction"], 0.015 * dt)
        _recharge(n, "social_need", _BASELINE["social_need"], 0.028 * dt)
        _recharge(n, "energy", _BASELINE["energy"], 0.04 * dt)
        _recharge(n, "sleepiness", _BASELINE["sleepiness"], 0.012 * dt)
        _recharge(n, "hunger", _BASELINE["hunger"], 0.015 * dt)
        # 驱动型需求会"向上积累"：越久没被行为释放，越往上爬（但封顶到中等值，形成自然振荡）。
        _rising_drive(n, "playfulness", _DRIVE_PEAK["playfulness"], 0.03 * dt)
        _rising_drive(n, "curiosity", _DRIVE_PEAK["curiosity"], 0.03 * dt)
        _rising_drive(n, "boredom", _DRIVE_PEAK["boredom"], 0.035 * dt)
        _rising_drive(n, "social_need", _DRIVE_PEAK["social_need"], 0.035 * dt)
        n.clamp()
        self.state.user_working = user_working
        self.state.user_idle_seconds = user_idle
        self.bus.emit(EventType.NEEDS_UPDATED, source="state")

    # ---- 注意力（plan/1 §11）：不是动画属性，是认知状态 ----
    def evaluate_attention(self) -> None:
        st = self.state
        att = st.attention
        if st.user_idle_seconds > 180 or st.active_window_app in ("", "unknown"):
            att.target = AttentionTarget.SELF
        elif classify_activity(st.active_window_app, st.active_window_title)["working"]:
            att.target = AttentionTarget.ACTIVE_WINDOW
            if st.life.macro in (MacroState.ENGAGED, MacroState.WORKING):
                att.target = AttentionTarget.USER if st.user_working and att.gaze == "user" else AttentionTarget.ACTIVE_WINDOW
        else:
            att.target = AttentionTarget.USER

    # ---- 意图生成（Utility 打分 + 优先级 + cooldown + 打扰成本） ----
    def generate_intent(self, state: CharacterState) -> IntentCandidate:
        n = state.needs
        working = state.user_working
        hour = state.clock_hour
        idle = state.user_idle_seconds
        now = time.monotonic()

        cands: List[IntentCandidate] = []
        # 睡眠（survive, P_NEED）
        sleep_u = n.sleepiness * 0.6 + n.fatigue * 0.4
        if (hour >= 23 or hour < 6) and sleep_u > 45:
            sleep_u += (n.sleepiness - n.social_need * 0.3)
            cands.append(IntentCandidate(Intent(IntentCategory.SURVIVE, "sleep", priority=P_NEED,
                                                reason=f"困倦{n.sleepiness:.0f}/深夜"), sleep_u))
        # 吃
        if n.hunger > 68:
            cands.append(IntentCandidate(Intent(IntentCategory.SURVIVE, "eat", priority=P_NEED,
                                                reason=f"饥饿{n.hunger:.0f}"), n.hunger))
        # 休息：疲劳/困倦高且非深夜强迫不睡时，退而求其次
        if n.fatigue > 70 and n.sleepiness < 60:
            cands.append(IntentCandidate(Intent(IntentCategory.SELF, "rest", priority=P_SELF,
                                                reason=f"疲劳{n.fatigue:.0f}"), n.fatigue * 0.8))
        # 陪伴/搭话（social, 考虑打扰成本 plan/3 §10）
        if n.social_need > 65:
            u = n.social_need
            if working:
                u -= 45      # 打扰成本
            else:
                u += 8
            cands.append(IntentCandidate(Intent(IntentCategory.USER, "approach_user", priority=P_SOCIAL,
                                                reason=f"社交{n.social_need:.0f}"), u))
        # 无聊 → 探索/玩耍
        if n.boredom > 70 and n.energy > 30:
            cands.append(IntentCandidate(Intent(IntentCategory.SELF, "wander", priority=P_SELF,
                                                reason=f"无聊{n.boredom:.0f}"), n.boredom))
        # 长期目标偏置（plan/3 §23）：understand_user → 更愿意观察
        if self.long_term_goal == "understand_user" and working:
            cands.append(IntentCandidate(Intent(IntentCategory.USER, "observe_user", priority=P_SOCIAL,
                                                reason="长期目标:了解用户/用户在忙"), 55))

        # cooldown 抑制（plan/3 §20）
        for c in cands:
            last = self._cooldowns.get(c.intent.action, 0)
            if now < last:
                c.utility -= 40

        if not cands:
            best = (Intent(IntentCategory.SELF, "idle", priority=P_MICRO, reason="无高优先级需求"),
                    10.0)
            return self._finalize(best[0], best[1])

        best = max(cands, key=lambda c: c.utility)
        return self._finalize(best.intent, best.utility)

    def _finalize(self, intent: Intent, utility: float) -> IntentCandidate:
        self.state.intent = intent
        self._cooldowns[intent.action] = time.monotonic() + _cooldown_for(intent.action)
        self.bus.emit(EventType.INTENT_CHANGED, payload=intent, source="state")
        return IntentCandidate(intent, utility)

    # ---- 窗口回调 ----
    def on_active_window(self, app: str, title: str) -> None:
        self.state.active_window_app = app
        self.state.active_window_title = title
        self.evaluate_attention()

    def update_clock(self, hour: int, minute: int) -> None:
        self.state.clock_hour = hour
        self.state.clock_minute = minute


def _cooldown_for(action: str) -> float:
    """各意图的最小冷却（plan/3 §20）。"""
    return {"sleep": 240, "eat": 300, "rest": 90, "approach_user": 120,
            "wander": 60, "observe_user": 45}.get(action, 30)
