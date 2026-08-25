"""Phase 13 FINAL-R1 Reviewer Residual Closeout — §1 World / §2 Emotion 修复测试。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
from types import SimpleNamespace
from unittest import mock

from furina.core import EventBus, EventType
from furina.state import CharacterState
from furina.state.state_engine import StateEngine
from furina.emotion import (EmotionEngine, EVENT_PRAISE, EVENT_REJECT, EVENT_AGENT_DONE,
                            EVENT_FEED)
from furina.runtime.window_awareness import WindowInfo, _idle_from_ticks, _get_idle_seconds
from furina.runtime.world import DesktopWorld, Rect
from furina.runtime.scheduler import Scheduler


# ================================================================ §1.1 idle tick source
def test_windows_idle_nonzero_sample_exact():
    """确定性样本：now=120000ms, last=90000ms → idle=30.0s（H1 §2.2 wrap 兼容）。"""
    assert _idle_from_ticks(90000.0, 120000.0) == 30.0
    # now < last = 32 位回绕场景：结果为 (now32-last32)&0xFFFFFFFF，是真实回绕后的 idle，不是 0
    wrapped = _idle_from_ticks(120000.0, 90000.0)
    assert wrapped > 1000.0, f"now<last 是回绕（大值），不是假装 0: {wrapped}"


def test_windows_idle_uses_kernel32_tick_source():
    """API-mock：GetLastInputInfo 走 user32，GetTickCount64 走 **kernel32**（不是 user32）。"""
    import ctypes

    class _LII(ctypes.Structure):   # 与 LASTINPUTINFO 内存布局一致（UINT + DWORD）
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    calls = {"kernel32_tick": 0, "user32_tick": 0}

    def _get_last_input(buf):
        ctypes.cast(buf, ctypes.POINTER(_LII)).contents.dwTime = 90000
        return 1

    class _User32:
        def GetLastInputInfo(self, buf):
            return _get_last_input(buf)

        def GetTickCount(self):
            calls["user32_tick"] += 1
            return 120000

    class _Kernel32:
        def GetTickCount64(self):
            calls["kernel32_tick"] += 1
            return 120000

    windll = SimpleNamespace(user32=_User32(), kernel32=_Kernel32())
    with mock.patch("ctypes.windll", windll):
        idle = _get_idle_seconds()
    assert idle == 30.0, f"样本应产出 30.0s，实际 {idle}"
    assert calls["kernel32_tick"] == 1, "tick 必须来自 Kernel32.GetTickCount64"
    assert calls["user32_tick"] == 0, "GetTickCount 不得从 user32 调用"


def test_windows_idle_api_failure_is_not_fake_zero_activity():
    """API 失败 → None / idle_available=False；不得假装成 0（用户一直活跃）。"""
    from furina.runtime.window_awareness import WindowAwareness

    class _FailUser32:
        def GetLastInputInfo(self, buf):
            return 0   # 失败

    windll = SimpleNamespace(user32=_FailUser32(),
                             kernel32=SimpleNamespace(GetTickCount64=lambda: 120000))
    with mock.patch("ctypes.windll", windll):
        assert _get_idle_seconds() is None, "API 失败必须返回 None，不是 0"
    # WindowAwareness：失败采样 → idle_available=False（保留上一有效值，不假装 0）
    wa = WindowAwareness(update_cb=lambda info: None)
    with mock.patch("ctypes.windll", windll), mock.patch("sys.platform", "win32"):
        wa.poll()
    assert wa.idle_available is False, "失败采样不得标记可用"


# ================================================================ §1.2 单次 World 更新 + 集成
class _FakeWA:
    """模拟 WindowAwareness：poll() 经 bus 发 ACTIVE_WINDOW_UPDATED（真实 Scheduler 采样路径）。"""

    def __init__(self, bus, info):
        self.bus = bus
        self.info = info
        self.last_idle = info.idle
        self.idle_available = info.idle is not None

    def set(self, info):
        self.info = info
        self.last_idle = info.idle
        self.idle_available = info.idle is not None

    def poll(self):
        self.bus.emit(EventType.ACTIVE_WINDOW_UPDATED, payload=self.info, source="runtime")
        return self.info


def _sched_with_wa(info):
    bus = EventBus()
    se = StateEngine(bus)
    world = DesktopWorld(1920, 1080)
    world.taskbar_height = 48.0
    wa = _FakeWA(bus, info)
    sched = Scheduler(bus, se, None, None, None, world, wa)
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.be = SimpleNamespace(step=lambda s: None)   # _tick_medium 回退路径需要
    sched.director = SimpleNamespace(drain=lambda: None, submit=lambda r: None,
                                     finish=lambda **k: None)
    return sched, bus, se, wa


def _chrome_info():
    return WindowInfo(app="Chrome_WidgetWin_1", title="tab", process="chrome", idle=5.0,
                      rect=Rect(100, 100, 800, 600))


def _code_info():
    # 真实场景：VS Code 前台窗口的类名是 Electron 风格（Chrome_WidgetWin_1），进程是 Code
    return WindowInfo(app="Chrome_WidgetWin_1", title="main.py — app", process="Code", idle=5.0,
                      rect=Rect(100, 100, 800, 600))


def _drive(sched, wa, info, ticks=14):
    wa.set(info)
    sched._last_window_poll = 0.0
    for _ in range(ticks):
        sched._tick_medium(3.0)


def test_scheduler_world_updates_once_per_medium_sample():
    """每个 medium 采样 **恰好一次** WorldPerception.update（on_window 只缓存，不独立推进）。"""
    sched, bus, se, wa = _sched_with_wa(_chrome_info())
    counter = {"n": 0}
    orig = sched.world_perc.update

    def _counted(**kw):
        counter["n"] += 1
        return orig(**kw)
    sched.world_perc.update = _counted
    sched._last_window_poll = 0.0
    for _ in range(3):
        sched._tick_medium(3.0)
    assert counter["n"] == 3, f"3 个 medium tick 应恰好 3 次 update，实际 {counter['n']}"


def test_scheduler_browser_to_code_transition_reaches_coding():
    """稳定 chrome → 切到 Code 进程（Chrome_Widget 类名）→ 稳定窗口后 CODING，且 user_working=True。"""
    from furina.world_perception import UserActivity
    sched, bus, se, wa = _sched_with_wa(_chrome_info())
    _drive(sched, wa, _chrome_info())
    assert sched.world_perc.state.user_activity == UserActivity.BROWSING
    assert sched.se.state.user_working is False
    # 切到 Code（类名仍是 Chrome_WidgetWin_1）→ 30s+ 稳定后必须 CODING（类/进程双喂不得重置 pending）
    _drive(sched, wa, _code_info(), ticks=14)
    assert sched.world_perc.state.user_activity == UserActivity.CODING, \
        f"browser→code 必须稳定提交 CODING，实际 {sched.world_perc.state.user_activity}"
    assert sched.se.state.user_working is True, "coding → user_working 必须为 True"


def test_scheduler_code_to_browser_transition_reaches_browsing():
    from furina.world_perception import UserActivity
    sched, bus, se, wa = _sched_with_wa(_code_info())
    _drive(sched, wa, _code_info())
    assert sched.world_perc.state.user_activity == UserActivity.CODING
    _drive(sched, wa, _chrome_info(), ticks=14)
    assert sched.world_perc.state.user_activity == UserActivity.BROWSING, \
        f"code→browser 必须稳定提交 BROWSING，实际 {sched.world_perc.state.user_activity}"


def test_scheduler_idle_comes_from_windowawareness():
    """state.user_idle_seconds 必须来自 WindowAwareness（真实 idle），而非自喂。"""
    info = WindowInfo(app="ClsX", title="", process="notepad", idle=42.0, rect=Rect(0, 0, 400, 300))
    sched, bus, se, wa = _sched_with_wa(info)
    sched.se.state.user_idle_seconds = 0.0
    _drive(sched, wa, info, ticks=2)
    assert abs(sched.se.state.user_idle_seconds - 42.0) < 1e-6, \
        f"idle 必须来自 WindowAwareness: {sched.se.state.user_idle_seconds}"


# ================================================================ §2.1 BRAIN_SPOKE 不得覆盖情绪
def test_brain_spoke_cannot_overwrite_emotion_label():
    """权威 label=embarrassed → BRAIN_SPOKE(payload.emotion='happy') → label 保持 embarrassed。"""
    sched, bus, se, wa = _sched_with_wa(_chrome_info())
    sched.emotion.apply_event(EVENT_REJECT, tired_hint=0.0)   # → embarrassed/sad
    authoritative = sched.se.state.emotion.label
    payload = SimpleNamespace(speech="好的~", intent="talk", emotion="happy")
    bus.emit(EventType.BRAIN_SPOKE, payload=payload, source="worker")
    sched.drain_apply()
    assert sched.se.state.emotion.label == authoritative, \
        f"BRAIN_SPOKE 不得覆盖权威情绪: {sched.se.state.emotion.label} != {authoritative}"
    assert sched.se.state.intent.emotion == "happy", "表达提示应落 Intent.emotion（非权威槽）"


# ================================================================ §2.2 apply 后立即派生 label
def _fresh_ee():
    return EmotionEngine(CharacterState().emotion)


def test_praise_label_is_updated_before_praise_dialogue_snapshot():
    ee = _fresh_ee()
    ee.apply_event(EVENT_PRAISE, tired_hint=0.0)
    assert ee.state.label in ("proud", "happy"), "apply_event 后 label 立即派生（无需等 tick）"


def test_reject_label_is_updated_before_rejection_dialogue_snapshot():
    ee = _fresh_ee()
    ee.apply_event(EVENT_REJECT, tired_hint=0.0)
    assert ee.state.label in ("embarrassed", "sad"), "reject 后 label 立即派生"


def test_feed_label_is_updated_before_feed_dialogue_snapshot():
    from furina.app import Furina
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.emotion = EmotionEngine(app.state.state.emotion)
    app.relationship = None
    app.memory = SimpleNamespace(observe=lambda *a, **k: None,
                                 retrieve=lambda **k: [],
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    app.dialogue_brain = None
    app.bus = SimpleNamespace(emit=lambda *a, **k: None)
    app._sched = SimpleNamespace(interrupt_life=lambda r: None)
    with mock.patch("furina.feeding.apply_food", return_value={"hunger": -30, "satisfaction": +10}):
        app._feed("蛋糕")
    assert app.state.state.emotion.label in ("happy",), \
        f"feed 后 label 立即派生: {app.state.state.emotion.label}"


def test_agent_done_label_is_updated_before_agent_dialogue_snapshot():
    sched, bus, se, wa = _sched_with_wa(_chrome_info())
    sched._on_agent_done(SimpleNamespace(payload={"summary": "x", "verified": True}))
    assert sched.se.state.emotion.label in ("proud",), \
        f"agent_done 后 label 立即派生: {sched.se.state.emotion.label}"


# ================================================================ §2.3 WORK_STARTED/ENDED 情绪
def test_stable_work_start_emotion_event_once():
    sched, bus, se, wa = _sched_with_wa(_chrome_info())
    _drive(sched, wa, _chrome_info())          # 稳定 BROWSING
    sched.emotion._recent.clear()
    _drive(sched, wa, _code_info(), ticks=14)  # 稳定 CODING → WORK_STARTED
    assert sched.emotion._recent.get("user_work_start", 0) == 1, \
        f"WORK_STARTED 情绪应恰好一次: {sched.emotion._recent}"
    # 继续稳定在 coding：不得重复消费
    _drive(sched, wa, _code_info(), ticks=6)
    assert sched.emotion._recent.get("user_work_start", 0) == 1


def test_stable_work_end_emotion_event_once():
    sched, bus, se, wa = _sched_with_wa(_code_info())
    _drive(sched, wa, _code_info())            # 稳定 CODING
    sched.emotion._recent.clear()
    _drive(sched, wa, _chrome_info(), ticks=14)  # 稳定 BROWSING → WORK_ENDED
    assert sched.emotion._recent.get("user_work_end", 0) == 1, \
        f"WORK_ENDED 情绪应恰好一次: {sched.emotion._recent}"


# ================================================================ §2.4 未映射事件不进 _recent
def test_unmapped_pointer_control_does_not_enter_emotion_recent():
    from furina.app import Furina
    from furina.interaction.interaction_types import InteractionEvent, TouchKind, InteractionZone
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.emotion = EmotionEngine(app.state.state.emotion)
    app.bus = SimpleNamespace()
    before = dict(app.emotion._recent)
    for kind in ("grab", "release", "hover", "leave", "approach", "double_click"):
        app._on_interaction_emotion(SimpleNamespace(payload=InteractionEvent(
            type=TouchKind(kind), target=InteractionZone.WHOLE)))
    assert app.emotion._recent == before, \
        f"未映射指针控制不得进入 emotion._recent: {app.emotion._recent}"
    # 有映射的 click 正常进入
    app._on_interaction_emotion(SimpleNamespace(payload=InteractionEvent(
        type=TouchKind.CLICK, target=InteractionZone.WHOLE)))
    assert "user_click" in app.emotion._recent


def test_emotion_engine_single_production_definition():
    """emotion/engine.py 只能有一个 EmotionEngine 类定义。"""
    import furina.emotion.engine as E
    src = open(E.__file__, encoding="utf-8").read()
    assert src.count("class EmotionEngine:") == 1, "必须只有一个 EmotionEngine 生产实现"
