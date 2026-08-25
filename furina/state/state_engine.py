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


# ---------------------------------------------------------------- 被动需求时间尺度（§3 终审）
# Phase 13 终审 §3：所有被动需求漂移用 **分钟级产品时间常数**，不再是"每秒漂移"。
# 之前 rate 是 per-second（working 120s 就把 fatigue 推到 ~86、boredom 到 100）→ 时间流逝感失真。
# 现在统一 per-minute，线性换算为 per-second（/60），保证 dt 不变性：
#   600×1s 与 200×3s 近似等价（线性项完全等价；指数项小 k 下近似等价）。
#
# 目标时间尺度（从健康基线出发，仅被动漂移，不含行为反馈）：
#   - 30 分钟普通使用：无生理需求达到饱和（不 emergency）
#   - 2 小时连续工作：fatigue 显著升高（~60-75），但未到危机
#   - 4-8 小时：fatigue 达到高值（饱和）
#   - hunger：小时级演化（~0.32/min → 4h 左右明显饥饿）
#   - sleepiness：与昼夜兼容（白天慢、深夜快）
_PER_MIN = {
    "fatigue_working":    0.42,   # 工作 2h → +50（基线 20 → ~70 显著疲劳）；4h → 饱和
    "fatigue_idle":       0.04,   # 不忙疲劳温和上升（不立刻恢复，恢复靠 rest/sleep 行为）
    "boredom_working":    0.35,   # 工作 2h → +42（驱动型，配合 peak=72 封顶）
    "boredom_idle":      -0.12,   # 闲适缓释
    "work_interest_working": 0.25,
    "work_interest_idle":   -0.18,
    "energy":             0.25,   # 2h → -30（基线 80 → ~50）；4h → ~20；恢复靠 rest/sleep
    "sleepiness_day":     0.12,   # 白天 8h → +58（配合 12 基线 → ~70，可困但非危机）
    "sleepiness_night":   0.38,   # 深夜（23-6）→ 8h 饱和
    "hunger":             0.18,   # 2h → +22（~42 微饿）；4h → +43（~63 明显饿）；8h → 饱和
}


def _per_sec(per_min: float) -> float:
    """per-minute 常数 → per-second 漂移率（线性，dt 不变性）。"""
    return per_min / 60.0


def _rising_drive(n, field: str, peak: float, rate_per_sec: float, dt: float) -> None:
    """驱动型需求向上积累：越久没被行为释放，越接近 peak（但封顶，不贴 100）。

    这是"积累→达到驱动阈值→行为释放→下降→重新积累"的振荡来源。
    当 behavior 已把它降下（曲线下降），这里负责让它慢慢回升。
    **精确指数积累**（Phase 13 终审 §3）：k = 1-exp(-rate·dt)，dt 不变性
    （旧版 min(1.0, rate*dt) 在 dt=30 时 k=1 → 需求被瞬间钉在 peak，振荡消失）。
    """
    cur = getattr(n, field)
    if cur < peak:
        import math
        k = 1.0 - math.exp(-rate_per_sec * dt)
        diff = peak - cur
        setattr(n, field, cur + diff * k)


def _recharge(n, field: str, baseline: float, rate_per_sec: float, dt: float) -> None:
    """稳态再生：字段若低于基线，则向基线回升；距离基线越远 => 越快（非线性）。

    这是"需求重新积累"的核心 —— 让一次 play 不会把 boredom 永久清空；
    而是 boredom 会随时间重新积累，从而再次驱动 play。
    精确指数形式（同 _rising_drive，dt 不变性）。
    """
    cur = getattr(n, field)
    if cur < baseline:
        import math
        k = 1.0 - math.exp(-rate_per_sec * dt)
        diff = baseline - cur
        setattr(n, field, cur + diff * k)
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
# Phase 13 终审 §2.4：只接受**进程可执行名**（精确/整词），绝不做短 token 子串匹配
# （"et" 匹配 "Chrome_WidgetWin_1" 之类的类名会造成假 office/表格误判）。
_WORK_APPS = ("code", "vscode", "winword", "excel", "powerpnt", "pycharm", "idea",
              "terminal", "conhost", "notepad", "obsidian", "typora", "cmd", "powershell")
_STUDY_TITLE = ("论文", "文档", "报告", "学习", "教程", "题目", "ppt", "word", "excel")


def _proc_name(app: str) -> str:
    n = (app or "").strip().lower()
    if n.endswith(".exe"):
        n = n[:-4]
    return n


def classify_activity(app: str, title: str = "") -> dict:
    """把窗口进程分类为用户活动（plan/1 §21，§4 感知）。输入必须是进程名，不是窗口类名。"""
    a = _proc_name(app)
    t = (title or "").lower()
    if a in ("code", "vscode", "pycharm", "idea", "terminal", "conhost", "cmd", "powershell", "wt"):
        return {"working": True, "category": "coding", "label": "编程"}
    if a in ("winword", "word", "wps"):
        return {"working": True, "category": "writing", "label": "写作"}
    if a in ("excel", "et"):
        return {"working": True, "category": "sheet", "label": "表格"}
    if a in ("powerpnt", "ppt"):
        return {"working": True, "category": "slides", "label": "演示"}
    if a in ("chrome", "msedge", "firefox", "brave", "opera"):
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
        hour = self.state.clock_hour
        # ---- 自然积累（Phase 13 终审 §3：per-minute 产品时间常数，/60 → per-second）----
        # 疲惫：工作积累（小时级）、休息恢复（行为）；不忙时温和（绝不分钟级饱和）
        if user_working:
            n.fatigue = _drift(n.fatigue, _per_sec(_PER_MIN["fatigue_working"]), dt)
            n.boredom = _drift(n.boredom, _per_sec(_PER_MIN["boredom_working"]), dt)
            n.work_interest = _drift(n.work_interest, _per_sec(_PER_MIN["work_interest_working"]), dt)
        else:
            n.fatigue = _drift(n.fatigue, _per_sec(_PER_MIN["fatigue_idle"]), dt)
            n.boredom = _drift(n.boredom, _per_sec(_PER_MIN["boredom_idle"]), dt)
            n.work_interest = _drift(n.work_interest, _per_sec(_PER_MIN["work_interest_idle"]), dt)
        n.energy = _drift(n.energy, -_per_sec(_PER_MIN["energy"]), dt)
        # 困倦：昼夜兼容（深夜积累显著加快；白天慢）
        night = (hour >= 23) or (0 <= hour < 6)
        sleepy_rate = _PER_MIN["sleepiness_night"] if night else _PER_MIN["sleepiness_day"]
        n.sleepiness = _drift(n.sleepiness, _per_sec(sleepy_rate), dt)
        n.hunger = _drift(n.hunger, _per_sec(_PER_MIN["hunger"]), dt)

        # ---- 稳态再生（homeostasis）：被行为"满足/消耗"的需求随时间**重新积累**回基线。
        # 关键：距离基线越远 → 恢复越快（非线性），避免"一次行为永久清空某需求"。
        # 对"动机型"需求（curiosity/playfulness/satisfaction/boredom），不仅要回到基线，
        # 还要**向上积累**成驱动（积累到一定程度才产生 Motivation，行为释放后又重新积累）。
        # 注意：social_need 不再用无界 _drift 积累，而是由 rising_drive 向上限积累（封顶），
        # 避免它跑到 100 并永远霸占系统（crowd-out）。
        # 速率仍为 per-second 指数常数（0.03/s → ~30s 回 63% 差距；驱动几分钟内就绪，但不贴 100）。
        _recharge(n, "boredom", _BASELINE["boredom"], 0.03, dt)
        _recharge(n, "playfulness", _BASELINE["playfulness"], 0.02, dt)
        _recharge(n, "curiosity", _BASELINE["curiosity"], 0.02, dt)
        _recharge(n, "satisfaction", _BASELINE["satisfaction"], 0.015, dt)
        _recharge(n, "social_need", _BASELINE["social_need"], 0.028, dt)
        _recharge(n, "energy", _BASELINE["energy"], 0.04, dt)
        _recharge(n, "sleepiness", _BASELINE["sleepiness"], 0.012, dt)
        _recharge(n, "hunger", _BASELINE["hunger"], 0.015, dt)
        # 驱动型需求会"向上积累"：越久没被行为释放，越往上爬（但封顶到中等值，形成自然振荡）。
        _rising_drive(n, "playfulness", _DRIVE_PEAK["playfulness"], 0.03, dt)
        _rising_drive(n, "curiosity", _DRIVE_PEAK["curiosity"], 0.03, dt)
        _rising_drive(n, "boredom", _DRIVE_PEAK["boredom"], 0.035, dt)
        _rising_drive(n, "social_need", _DRIVE_PEAK["social_need"], 0.035, dt)
        # Phase 13 终审 §3：**驱动型需求封顶于各自 peak**（rising_drive 只负责向上收敛，
        # 但 drift 会在超过 peak 后继续无界积累 → 2h 就把 boredom 推到 100）。
        # 驱动型需求只在 [行为释放后, peak] 带内振荡，绝不贴 100 霸占系统。
        for _k, _peak in _DRIVE_PEAK.items():
            if getattr(n, _k) > _peak:
                setattr(n, _k, _peak)
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
