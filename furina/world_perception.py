"""Structured World Perception（Phase 06）。

把 Raw Desktop Signals（前台应用 / 标题 / 窗口类名 / idle / 时间 / 输入活动）
确定性地归纳为：

    Raw Signals → WorldState（结构化）→ WorldEvent（有意义的改变）→ WorldSalience
        → CharacterAppraisal / Motivation / LifeBrain

不做 Vision、不做 OCR、不新增 LLM、不写 SQLite（World State 是 runtime state）。
关键原则：
  - 宁可 unknown，不要假装知道（不按窗口标题深度猜内容）。
  - World Event 必须 debounce / stability，代表"有意义的变化"，而非 OS 噪声。
  - World 只改变"候选环境"，不直接指定 Activity；不得制造新的 observe fallback。
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from furina.state.state_engine import classify_activity


# ---------------------------------------------------------------- 用户活动枚举
class UserActivity(str, enum.Enum):
    AWAY = "away"
    IDLE = "idle"
    BROWSING = "browsing"
    READING = "reading"
    WRITING = "writing"
    CODING = "coding"
    WORKING = "working"
    GAMING = "gaming"
    WATCHING_MEDIA = "watching_media"
    COMMUNICATION = "communication"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------- World Event
class WorldEvent(str, enum.Enum):
    USER_BECAME_ACTIVE = "USER_BECAME_ACTIVE"
    USER_BECAME_IDLE = "USER_BECAME_IDLE"
    USER_LEFT = "USER_LEFT"
    USER_RETURNED = "USER_RETURNED"
    APP_CHANGED = "APP_CHANGED"
    ACTIVITY_CHANGED = "ACTIVITY_CHANGED"
    WORK_STARTED = "WORK_STARTED"
    WORK_ENDED = "WORK_ENDED"
    FOCUS_STARTED = "FOCUS_STARTED"
    FOCUS_ENDED = "FOCUS_ENDED"
    LONG_FOCUS = "LONG_FOCUS"
    LONG_SILENCE = "LONG_SILENCE"
    TIME_PERIOD_CHANGED = "TIME_PERIOD_CHANGED"


# ---------------------------------------------------------------- World State
@dataclass
class WorldState:
    timestamp: float = 0.0
    day_period: str = "day"            # morning/noon/afternoon/evening/night
    user_present: bool = True
    user_active: bool = True           # 有近期输入（非 idle）
    user_idle_seconds: float = 0.0
    foreground_app: str = ""           # 窗口类名
    foreground_process: str = ""       # 进程名（近似 app）
    foreground_title: str = ""
    app_category: str = "unknown"      # reasoning: code/write/browse/comm/...
    user_activity: UserActivity = UserActivity.UNKNOWN
    user_focus_level: float = 0.0      # 0..1
    interaction_availability: float = 1.0  # 0..1
    interruption_cost: float = 0.0     # 0..1
    activity_duration: float = 0.0     # 当前用户活动持续秒数
    same_context_duration: float = 0.0  # 同一前台上下文持续秒数
    recent_world_events: List[str] = field(default_factory=list)
    interesting_context: bool = False
    assistance_opportunity: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "user_activity": self.user_activity.value,
            "focus_level": round(self.user_focus_level, 2),
            "interaction_availability": round(self.interaction_availability, 2),
            "interruption_cost": round(self.interruption_cost, 2),
            "foreground_app": self.foreground_process or self.foreground_app,
            "activity_duration": round(self.activity_duration, 1),
            "recent_events": self.recent_world_events[-6:],
            "interesting_context": self.interesting_context,
        }


# ---------------------------------------------------------------- 配置（阈值集中，不散落 magic number）
_APP_CATEGORY_RULES = [
    (("code", "vscode", "pycharm", "idea", "terminal", "conhost", "cmd", "powershell"), "coding"),
    (("winword", "word", "wps", "notepad", "editor", "obsidian", "typora"), "writing"),
    (("excel", "et", "powerpnt", "ppt", "acrobat", "pdf", "libreoffice"), "working"),
    (("chrome", "msedge", "firefox", "brave", "opera"), "browsing"),
    (("wechat", "weixin", "qq", "telegram", "discord", "slack", "outlook"), "communication"),
    (("vlc", "potplayer", "mpv", "wmplayer", "youtube"), "watching_media"),
    (("steam", "game", "epicgames", "wuthering"), "gaming"),
]
_READING_HINT = ("read", "pdf", "document", "小说", "article", "manga", "comic", "doc")
_AWAY_IDLE_THRESHOLD = 300.0       # 5min 无输入 → away
_STABLE_ACTIVITY_MIN = 30.0        # 活动需稳定 30s 才算 significant transition
_LONG_FOCUS_THRESHOLD = 600.0      # 10min 连续 focus
_LONG_SILENCE_THRESHOLD = 900.0    # 15min


def _cat(app: str, title: str) -> str:
    a = (app or "").lower(); t = (title or "").lower()
    for keys, cat in _APP_CATEGORY_RULES:
        if any(k in a for k in keys):
            return cat
    if any(k in t for k in _READING_HINT):
        return "reading"
    return "unknown"


def _period(hour: int) -> str:
    if 5 <= hour < 9: return "morning"
    if 9 <= hour < 12: return "noon"
    if 12 <= hour < 18: return "afternoon"
    if 18 <= hour < 23: return "evening"
    return "night"


class WorldPerception:
    """确定性世界感知：raw signals → WorldState + stable WorldEvents + salience。

    每 medium tick 调用 update()，内部维护稳定性窗口与 debounce，只发出"有意义"事件。
    """

    def __init__(self) -> None:
        self.state = WorldState()
        self._prev_activity = UserActivity.UNKNOWN
        self._prev_app = ""
        self._prev_period = ""
        self._activity_since = 0.0
        self._context_since = 0.0
        self._focus_since = 0.0
        self._last_emit: Dict[str, float] = {}   # event -> 上次 emit 时间

    def _emit(self, out: List[str], ev: WorldEvent, w: WorldState) -> None:
        """debounce / stability：同一事件需间隔最少 20s 才再发。"""
        key = ev.value
        now = w.timestamp
        prev = self._last_emit.get(key, -999.0)
        if now - prev < 20.0:
            return
        self._last_emit[key] = now
        out.append(key)

    def update(self, *, app: str, title: str, idle_seconds: float,
               hour: int, minute: int, typing: bool = False, dt: float = 3.0) -> WorldState:
        w = self.state
        w.timestamp = time.time()
        w.day_period = _period(hour)
        w.user_idle_seconds = idle_seconds
        w.foreground_app = app
        w.foreground_title = title
        w.foreground_process = app
        w.app_category = _cat(app, title)

        # 用户在场/活跃
        w.user_present = idle_seconds < _AWAY_IDLE_THRESHOLD
        w.user_active = (typing or idle_seconds < 30) and w.user_present

        # 活动：away > idle > 由 app 类别
        if not w.user_present:
            w.user_activity = UserActivity.AWAY
        elif idle_seconds >= 30 and not typing:
            w.user_activity = UserActivity.IDLE
        else:
            w.user_activity = _activity_from_category(w.app_category, title)

        # Focus / availability / interruption（§6 三者不同）
        focus, avail, cost = _focus_availability(w.user_activity, typing, idle_seconds, w.app_category)
        w.user_focus_level = focus
        w.interaction_availability = avail
        w.interruption_cost = cost

        # 持续时间
        self._activity_since = self._activity_since + dt if w.user_activity == self._prev_activity else 0.0
        w.activity_duration = self._activity_since
        self._context_since = self._context_since + dt if (app == self._prev_app) else 0.0
        w.same_context_duration = self._context_since

        # 事件（debounce）
        events = self._derive_events(w)
        w.recent_world_events = w.recent_world_events[-8:] + list(events)
        w.interesting_context = _interesting(w.app_category, events, w.same_context_duration)
        w.assistance_opportunity = _assistance(w)

        self._prev_activity = w.user_activity
        self._prev_app = app
        self._prev_period = w.day_period
        self._focus_since = self._focus_since + dt if w.user_focus_level > 0.7 else 0.0
        return w

    def _derive_events(self, w: WorldState) -> List[str]:
        ev: List[str] = []
        # 用户在场状态转变
        if self._prev_activity in (UserActivity.AWAY,) and w.user_present:
            self._emit(ev, WorldEvent.USER_RETURNED, w)
        elif self._prev_activity != UserActivity.AWAY and not w.user_present:
            self._emit(ev, WorldEvent.USER_LEFT, w)
        if self._prev_activity == UserActivity.IDLE and w.user_active:
            self._emit(ev, WorldEvent.USER_BECAME_ACTIVE, w)
        # 前台窗口类转变
        if self._prev_app and w.foreground_app != self._prev_app:
            self._emit(ev, WorldEvent.APP_CHANGED, w)
        # 用户活动转变
        if w.user_activity != self._prev_activity:
            self._emit(ev, WorldEvent.ACTIVITY_CHANGED, w)
            # 工作开始/结束
            working_new = w.user_activity in (UserActivity.CODING, UserActivity.WORKING, UserActivity.WRITING)
            working_old = self._prev_activity in (UserActivity.CODING, UserActivity.WORKING, UserActivity.WRITING)
            if working_new and not working_old:
                self._emit(ev, WorldEvent.WORK_STARTED, w)
            if not working_new and working_old:
                self._emit(ev, WorldEvent.WORK_ENDED, w)
        # focus
        if w.user_focus_level > 0.7 and self._focus_since > 10:
            self._emit(ev, WorldEvent.FOCUS_STARTED, w)
        if w.user_focus_level < 0.3 and self._focus_since > 10:
            self._emit(ev, WorldEvent.FOCUS_ENDED, w)
        if w.user_focus_level > 0.7 and self._focus_since > _LONG_FOCUS_THRESHOLD:
            self._emit(ev, WorldEvent.LONG_FOCUS, w)
        if w.user_idle_seconds > _LONG_SILENCE_THRESHOLD:
            self._emit(ev, WorldEvent.LONG_SILENCE, w)
        if w.day_period != self._prev_period and self._prev_period:
            self._emit(ev, WorldEvent.TIME_PERIOD_CHANGED, w)
        return ev

    # -------------------------------------------------- 供 Motivation / Brain
    def factors(self) -> Dict[str, float]:
        """归一化世界因子（0..1），供 Motivation 读。"""
        w = self.state
        return {
            "focus": w.user_focus_level,
            "availability": w.interaction_availability,
            "interruption_cost": w.interruption_cost,
            "assistance_opportunity": w.assistance_opportunity,
            "user_working": 1.0 if w.user_activity in (UserActivity.CODING, UserActivity.WORKING, UserActivity.WRITING) else 0.0,
            "user_present": 1.0 if w.user_present else 0.0,
            "user_idle": min(1.0, w.user_idle_seconds / _AWAY_IDLE_THRESHOLD),
            "interesting_context": 1.0 if w.interesting_context else 0.0,
        }

    def event_tags(self) -> List[str]:
        return list(self.state.recent_world_events[-4:])


# ---------------------------------------------------------------- 内部 helper
def _activity_from_category(cat: str, title: str) -> UserActivity:
    t = (title or "").lower()
    if cat == "coding": return UserActivity.CODING
    if cat == "writing": return UserActivity.WRITING
    if cat == "working": return UserActivity.WORKING
    if cat == "browsing": return UserActivity.BROWSING
    if cat == "communication": return UserActivity.COMMUNICATION
    if cat == "watching_media": return UserActivity.WATCHING_MEDIA
    if cat == "gaming": return UserActivity.GAMING
    if cat == "reading": return UserActivity.READING
    return UserActivity.UNKNOWN


def _focus_availability(act: UserActivity, typing: bool, idle: float, cat: str) -> tuple[float, float, float]:
    """聚焦 / 可用 / 打扰成本 —— 三者不相等（§6）。"""
    if act == UserActivity.AWAY:
        return 0.0, 0.0, 0.0
    if act in (UserActivity.CODING, UserActivity.WORKING, UserActivity.WRITING):
        # coding+持续输入 → focus 高、成本高、可用低
        base = 0.9 if typing else 0.6
        return base, 0.15, base
    if act == UserActivity.READING:
        return 0.7, 0.5, 0.55
    if act == UserActivity.BROWSING:
        return 0.4, 0.7, 0.35
    if act == UserActivity.WATCHING_MEDIA:
        return 0.5, 0.6, 0.4
    if act == UserActivity.COMMUNICATION:
        return 0.3, 0.8, 0.25
    if act == UserActivity.GAMING:
        return 0.8, 0.2, 0.7
    if act == UserActivity.IDLE:
        return 0.1, 0.9, 0.05
    return 0.3, 0.6, 0.3


def _interesting(cat: str, events: List[str], same_ctx: float) -> bool:
    """结构化"有趣上下文"：app 类别突变 / 罕见类别 / 意外活动转变。"""
    if any(e in ("APP_CHANGED", "ACTIVITY_CHANGED") for e in events):
        if cat in ("gaming", "watching_media", "browsing") or cat == "unknown":
            return True
    return False


def _assistance(w: WorldState) -> float:
    """assistance_opportunity：用户忙/在深度工作 + 应用支持帮忙 → 有帮忙可能（≠ 用户请求帮忙）。"""
    if w.user_activity not in (UserActivity.CODING, UserActivity.WORKING, UserActivity.WRITING):
        return 0.0
    if w.user_focus_level < 0.5:
        return 0.0
    # 只是"maybe useful"，不假装"requested"
    return min(1.0, w.user_focus_level * 0.7)
