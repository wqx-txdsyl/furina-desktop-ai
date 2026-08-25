"""Phase 13 FINAL-R1-H1 Reviewer Hard-Blocker Hotfix — 全部 H1 不变量的行为测试。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from types import SimpleNamespace
from unittest import mock

from furina.core import EventBus, EventType
from furina.state import CharacterState
from furina.state.state_engine import StateEngine
from furina.emotion import EmotionEngine
from furina.runtime.scheduler import Scheduler
from furina.runtime.dispatcher import RuntimeDispatcher
from furina.dialogue_brain import DialogueBrain
from furina.runtime.window_awareness import WindowInfo, _idle_from_ticks
from furina.runtime.world import Rect, DesktopWorld


# ================================================================ §2 Windows idle 真相
def test_active_window_preserves_idle_none():
    """H1 §2.1：_active_window_windows 必须保留 idle=None（不再 `or 0.0`）。"""
    import ctypes
    import furina.runtime.window_awareness as WA

    class _U:
        def __init__(self):
            import ctypes
            from ctypes import wintypes
            self.GetForegroundWindow = lambda: 1
            self.GetWindowTextLengthW = lambda h: 0
            self.GetWindowTextW = lambda h, b, n: 0
            self.GetClassNameW = lambda h, b, n: (b.__setattr__("value", "ClsX") or 0)
            def _rect(h, r):
                ptr = ctypes.cast(r, ctypes.POINTER(wintypes.RECT))
                ptr.contents.left = 0; ptr.contents.top = 0
                ptr.contents.right = 100; ptr.contents.bottom = 100
                return 0
            self.GetWindowRect = _rect
    windll = SimpleNamespace(user32=_U(), kernel32=SimpleNamespace())
    with mock.patch("ctypes.windll", windll), \
         mock.patch.object(WA, "_get_idle_seconds", return_value=None), \
         mock.patch.object(WA, "_get_process_name", return_value="proc"):
        info = WA._active_window_windows()
    assert info is not None and info.idle is None, \
        f"API 失败必须保留 None，实际 {info.idle!r}（绝不得 or 0.0）"


def test_idle_failure_poll_keeps_idle_unavailable():
    """H1 §2.1：poll 收到 None → idle_available=False（不假装 0）。"""
    import furina.runtime.window_awareness as WA
    seen = {}
    wa = WA.WindowAwareness(update_cb=lambda info: seen.update({"idle": info.idle}))
    info = WindowInfo(app="x", title="", process="p", idle=None, rect=Rect(0, 0, 10, 10))
    with mock.patch.object(WA, "_active_window_windows", return_value=info), \
         mock.patch("sys.platform", "win32"):
        wa.poll()
    assert seen.get("idle") is None, "poll 必须保留 None"
    assert wa.idle_available is False, "失败采样不得标记可用"
    assert wa.last_idle is None, "无有效采样时 last_idle 保持 None"


def test_idle_failure_does_not_become_zero():
    """H1 §2.1：_get_idle_seconds 失败 → WindowInfo.idle 是 None 而非 0.0（行为断言）。"""
    import furina.runtime.window_awareness as WA
    with mock.patch.object(WA, "_get_idle_seconds", return_value=None), \
         mock.patch.object(WA, "_active_window_windows",
                           return_value=WindowInfo(app="a", process="b", idle=None)):
        # poll 路径：update_cb 收到 idle=None
        seen = {}
        wa = WA.WindowAwareness(update_cb=lambda info: seen.update({"idle": info.idle}))
        with mock.patch("sys.platform", "win32"):
            wa.poll()
        assert seen.get("idle") is None, "poll 必须把 None 传给 update_cb（不假装 0）"


def test_idle_wrap_32bit_correct():
    """H1 §2.2：跨 0xFFFFFFFF→0 回绕仍正确。"""
    # last32=0xFFFFFF00(4294967040), now32=0x00000100(256) → elapsed=(256-4294967040)&0xFFFFFFFF=512ms
    assert abs(_idle_from_ticks(0xFFFFFF00, 0x00000100) - 0.512) < 1e-6


def test_idle_long_uptime_does_not_become_huge():
    """H1 §2.2：长 uptime（now64 高位非 0）不得产生巨大假空闲。"""
    now64 = 0x1_00000000 + 30000   # ~49 天 uptime，低 32 位 = 30000
    idle = _idle_from_ticks(20000, now64)
    assert abs(idle - 10.0) < 1e-6, f"长 uptime 应得 10.0s，实际 {idle}"


# ================================================================ §12 owner 显式绑定
def test_runtime_owner_bound_to_start_thread():
    d = RuntimeDispatcher()
    d.bind_owner()
    assert d.owner_thread_id == threading.get_ident(), "owner 必须是显式绑定线程"
    err = {}
    def _worker():
        try:
            d.require_owner("test_mutation")
        except RuntimeError as e:
            err["raised"] = str(e)
    t = threading.Thread(target=_worker)
    t.start(); t.join()
    assert "raised" in err, "worker 不得通过 require_owner"


def test_worker_cannot_become_owner_before_first_drain():
    """H1 §12：submit 不建立 owner；未绑定前 worker 请求守卫变更 → 报错（不自绑定）。"""
    d = RuntimeDispatcher()
    d.submit(lambda: None)   # submit 不得绑定 owner
    assert d.owner_thread_id is None, "submit 不得建立 owner"
    err = {}
    def _worker():
        try:
            d.require_owner("early_mutation")
        except RuntimeError as e:
            err["raised"] = str(e)
    t = threading.Thread(target=_worker)
    t.start(); t.join()
    assert "before runtime owner was bound" in err.get("raised", ""), \
        f"未绑定 owner 时守卫必须报错（不把自己绑成 owner）: {err}"


# ================================================================ §3 World 事件实例
class _FakeWA:
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


def _sched_wa(info):
    bus = EventBus()
    se = StateEngine(bus)
    world = DesktopWorld(1920, 1080)
    world.taskbar_height = 48.0
    wa = _FakeWA(bus, info)
    sched = Scheduler(bus, se, None, None, None, world, wa)
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.be = SimpleNamespace(step=lambda s: None)
    sched.director = SimpleNamespace(drain=lambda: None, submit=lambda r: None, finish=lambda **k: None)
    sched.dispatcher.bind_owner()
    # H1 §3：可控时钟（事件 debounce 用同一时钟，测试可跨 20s 边界）
    clock = {"t": 1000.0}
    sched.world_perc._now_fn = lambda: clock["t"]
    sched._test_clock = clock
    return sched, bus, se, wa


def _chrome():
    return WindowInfo(app="Chrome_WidgetWin_1", title="t", process="chrome", idle=5.0,
                      rect=Rect(100, 100, 800, 600))


def _code():
    return WindowInfo(app="Chrome_WidgetWin_1", title="main.py", process="Code", idle=5.0,
                      rect=Rect(100, 100, 800, 600))


def _drive(sched, wa, info, ticks=14):
    wa.set(info)
    sched._last_window_poll = 0.0
    for _ in range(ticks):
        sched._tick_medium(3.0)
        if hasattr(sched, "_test_clock"):
            sched._test_clock["t"] += 3.0   # 世界时钟随 dt 前进（真实 20s debounce 边界）


def test_work_started_event_consumed_once_after_60s_without_new_event():
    sched, bus, se, wa = _sched_wa(_chrome())
    _drive(sched, wa, _chrome())
    sched.emotion._recent.clear()
    _drive(sched, wa, _code(), ticks=14)
    assert sched.emotion._recent.get("user_work_start", 0) == 1
    # 继续 coding 120s（无新事件）→ 不得重触发
    _drive(sched, wa, _code(), ticks=40)
    assert sched.emotion._recent.get("user_work_start", 0) == 1, \
        "60s+ 无新事件不得重触发（不能从 recent 历史串推断）"


def test_second_real_work_transition_emits_second_event():
    sched, bus, se, wa = _sched_wa(_chrome())
    _drive(sched, wa, _chrome())
    sched.emotion._recent.clear()
    _drive(sched, wa, _code(), ticks=14)      # → coding: WORK_STARTED #1
    _drive(sched, wa, _chrome(), ticks=14)    # → browse: WORK_ENDED #1
    _drive(sched, wa, _code(), ticks=14)      # → coding again: WORK_STARTED #2
    assert sched.emotion._recent.get("user_work_start", 0) == 2, \
        f"第二次真实转换必须发第二个事件: {sched.emotion._recent}"


def test_recent_world_history_cannot_retrigger_emotion():
    sched, bus, se, wa = _sched_wa(_code())
    _drive(sched, wa, _code())
    sched.emotion._recent.clear()
    # 手动把旧 WORK_STARTED 塞进历史串（无新实例）→ 不得触发
    sched.world_perc.state.recent_world_events.append("WORK_STARTED")
    sched.world_perc.last_events = []
    sched._tick_medium(3.0)
    assert sched.emotion._recent.get("user_work_start", 0) == 0, \
        "历史串残留不得重触发情绪事件"


# ================================================================ §5 FIFO gate
class _OrderedLLM:
    def __init__(self, order, fail_seq=()):
        self.order = order
        self.fail_seq = set(fail_seq)
    def is_available(self):
        return True
    def structured(self, msgs, schema, temperature=0.9):
        seq = self.order["n"] + 1
        self.order["n"] = seq
        self.order["calls"].append(seq)
        if seq in self.fail_seq:
            return {"speech": ""}   # 失败/沉默
        if seq == 1:
            time.sleep(0.15)        # turn1 慢
        return {"speech": f"回复{seq}"}


def test_turn2_forced_before_turn1_lock_does_not_deadlock():
    """H1 §5：turn2 抢先到达（gate 等待）不得死锁；turn1 完成后放行。"""
    order = {"n": 0, "calls": []}
    db = DialogueBrain(_OrderedLLM(order), persona="你是芙宁娜。")
    gate_done = {"ok": False}
    def _turn2_gate_first():
        db._gate_wait(2)          # turn2 先到门（模拟抢先）
        gate_done["ok"] = True
    t2 = threading.Thread(target=_turn2_gate_first)
    t2.start()
    time.sleep(0.05)
    # turn1 完整 say（必须能获得 gate + 锁）
    out1 = db.say(intent="talk", user_text="第一句", user_initiated=True, context="casual")
    t2.join(timeout=5.0)
    assert not t2.is_alive(), "turn2 gate 必须被放行（不得死锁）"
    assert gate_done["ok"] and out1 == "回复1"


def test_dialogue_llm_call_order_matches_ingress_order():
    order = {"n": 0, "calls": []}
    db = DialogueBrain(_OrderedLLM(order), persona="你是芙宁娜。")
    results = {}
    def _call(text, tag):
        results[tag] = db.say(intent="talk", user_text=text, user_initiated=True, context="casual")
    t1 = threading.Thread(target=_call, args=("第一句", "r1"))
    t2 = threading.Thread(target=_call, args=("第二句", "r2"))
    t1.start(); t2.start()
    t1.join(timeout=6); t2.join(timeout=6)
    assert not t1.is_alive() and not t2.is_alive()
    assert order["calls"] == [1, 2], f"LLM 调用序必须==入队序: {order['calls']}"
    assert [h["text"] for h in db._history] == ["第一句", "回复1", "第二句", "回复2"]


def test_dialogue_failure_advances_fifo():
    order = {"n": 0, "calls": []}
    db = DialogueBrain(_OrderedLLM(order, fail_seq={1}), persona="你是芙宁娜。")
    out1 = db.say(intent="talk", user_text="第一句", user_initiated=True, context="casual")
    assert out1 is None, "turn1 失败 → None"
    out2 = db.say(intent="talk", user_text="第二句", user_initiated=True, context="casual")
    assert out2 == "回复2", "turn1 失败必须推进 FIFO，turn2 正常出话"


def test_dialogue_silence_advances_fifo():
    order = {"n": 0, "calls": []}
    db = DialogueBrain(_OrderedLLM(order, fail_seq={1}), persona="你是芙宁娜。")
    db.say(intent="talk", user_text="第一句", user_initiated=True, context="casual")   # 沉默
    out2 = db.say(intent="talk", user_text="第二句", user_initiated=True, context="casual")
    assert out2 == "回复2", "沉默回合必须推进 FIFO"


# ================================================================ §6 无孤儿 user 回合
class _InvalidLLM:
    def __init__(self, speeches):
        self._s = list(speeches)
    def is_available(self):
        return True
    def structured(self, msgs, schema, temperature=0.9):
        return {"speech": self._s.pop(0) if self._s else ""}


def test_model_failure_creates_no_orphan_direct_user_turn():
    db = DialogueBrain(_InvalidLLM([""]), persona="你是芙宁娜。")
    out = db.say(intent="talk", user_text="在吗", user_initiated=True, context="casual")
    assert out is None
    assert db._history == [], f"模型失败不得产生孤儿 User 回合: {db._history}"


def test_double_validation_failure_creates_no_orphan_direct_user_turn():
    db = DialogueBrain(_InvalidLLM(["（叹气）好吧", "（叹气）好吧"]), persona="你是芙宁娜。")
    out = db.say(intent="talk", user_text="在吗", user_initiated=True, context="casual")
    assert out is None
    assert db._history == [], f"双重校验失败不得产生孤儿 User 回合: {db._history}"


def test_valid_direct_turn_commits_exact_pair():
    db = DialogueBrain(_InvalidLLM(["嗯，我在呢。"]), persona="你是芙宁娜。")
    out = db.say(intent="talk", user_text="在吗", user_initiated=True, context="casual")
    assert out == "嗯，我在呢。"
    assert [h["role"] for h in db._history] == ["user", "furina"]


def test_history_always_even_user_furina_pairs():
    """valid→invalid→valid→silent→valid：直接历史永远偶数成对。"""
    llm = _InvalidLLM(["回复1", "（叹气）坏", "（叹气）坏", "回复3", "", "回复5"])
    db = DialogueBrain(llm, persona="你是芙宁娜。")
    for i, text in enumerate(["一", "二", "三", "四", "五"]):
        db.say(intent="talk", user_text=text, user_initiated=True, context="casual")
    hist = db._history
    assert len(hist) % 2 == 0, f"直接历史必须偶数成对: {len(hist)}"
    roles = [h["role"] for h in hist]
    assert roles == ["user", "furina"] * (len(hist) // 2), f"必须严格 user/furina 成对: {roles}"


# ================================================================ §7 社交 bid 只在可见执行时
def _sched_bid():
    bus = EventBus()
    se = StateEngine(bus)
    emo = EmotionEngine(se.state.emotion)
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.emotion = emo
    sched.relationship = SimpleNamespace(apply=lambda *a, **k: None, state=None,
                                         factors=lambda: {"comfort": 0.5})
    sched.dispatcher.bind_owner()
    se.state.user_idle_seconds = 10.0
    return sched, bus, se


def test_blocked_social_decision_creates_no_pending_bid():
    from furina.life_brain import LifeDecision
    sched, bus, se = _sched_bid()
    sched._apply_life_decision(LifeDecision(activity="talk", duration=30, next_think_in=60))
    assert sched._pending_social_bid is None, "被阻塞/未执行的社交决策不得开启响应窗口"


def test_unexecuted_talk_cannot_emit_ignore():
    sched, bus, se = _sched_bid()
    sched._tick_social_bid(now=time.time() + 999)
    assert sched.emotion._recent.get("user_ignore", 0) == 0


def test_invalid_social_speech_creates_no_pending_bid():
    """无效/被抑制的社交台词 → 不开启响应窗口（bid 只在可见执行+成功出话时开启）。"""
    sched, bus, se = _sched_bid()
    # 直接执行 talk（on_mind_action_started）→ 不再立即开 bid（talk 需可见台词）
    sched.on_mind_action_started("talk", 30.0)
    assert sched._pending_social_bid is None, "talk 无可见台词前不得开 bid（等出话后再开）"


def test_visible_social_bid_starts_one_window():
    """approach_user 执行（走过去的可见动作）→ 开启一个响应窗口。"""
    sched, bus, se = _sched_bid()
    sched.on_mind_action_started("approach_user", 30.0)
    assert sched._pending_social_bid is not None, "approach_user 可见执行应开启响应窗口"
    sched.on_mind_action_started("approach_user", 30.0)   # 重复 → 不叠加
    assert sched._pending_social_bid is not None


def test_user_response_cancels_visible_bid():
    sched, bus, se = _sched_bid()
    sched.on_mind_action_started("approach_user", 30.0)
    assert sched._pending_social_bid is not None
    sched.on_user_response()
    assert sched._pending_social_bid is None
    sched._tick_social_bid(now=time.time() + 999)
    assert sched.emotion._recent.get("user_ignore", 0) == 0


# ================================================================ §8 抢占 finalize（生产路径）
def _director_sched():
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.motivation = __import__("furina.behavior", fromlist=["BehaviorMotivation"]).BehaviorMotivation()
    from furina.director import Director, ActionRequest
    director = Director(bus)
    director.set_executor(lambda req: sched.on_mind_action_started(
        req.action, float((getattr(req, "payload", {}) or {}).get("planned_duration", 0.0) or 0.0))
        if getattr(req, "source", "") == "mind" else None)
    director.on_before_replace = _wire_replace(sched)
    sched.director = director
    sched.dispatcher.bind_owner()
    return sched, bus, se, director, ActionRequest


def _wire_replace(sched):
    def _cb(old, new):
        if old is not None and getattr(old, "source", "") == "mind":
            new_src = getattr(new, "source", "")
            sched.on_mind_preempted(reason=f"preempted_by_{new_src}")
    return _cb


def test_agent_takeover_finalizes_running_mind_immediately():
    sched, bus, se, director, AR = _director_sched()
    director.submit(AR(source="mind", action="read", priority=3, payload={"planned_duration": 60.0}))
    director.drain()   # mind 执行 → RUNNING 实例
    assert sched._activity_instance["status"] == "RUNNING"
    time.sleep(0.1)    # mind 跑了一小会
    director.submit(AR(source="agent", action="agent_work", priority=2))
    director.drain()   # agent 接管 → on_before_replace → finalize
    inst = sched._activity_instance
    assert inst["finish_reason"] == "preempted_by_agent", f"抢占必须 finalize: {inst}"
    assert sched._last_activity_finish["reason"] == "preempted_by_agent"
    # elapsed 停在抢占时刻（不是之后 Life 决策的时间）
    frozen_elapsed = inst["elapsed"]
    time.sleep(0.15)
    assert inst["elapsed"] == frozen_elapsed, "elapsed 必须停在接管时刻"


def test_preempted_mind_cannot_later_become_completed():
    from furina.life_brain import LifeDecision
    sched, bus, se, director, AR = _director_sched()
    director.submit(AR(source="mind", action="read", priority=3, payload={"planned_duration": 60.0}))
    director.drain()
    time.sleep(0.05)
    director.submit(AR(source="agent", action="agent_work", priority=2))
    director.drain()
    # H1-FINAL §5：status 是规范集 INTERRUPTED；finish_reason 保留抢占来源
    assert sched._activity_instance["status"] == "INTERRUPTED", sched._activity_instance
    assert sched._activity_instance["finish_reason"] == "preempted_by_agent"
    # 后续 Life 决策换活动：settlement 必须跳过（非 RUNNING）→ 不会被算成 completed
    sched._current_life_activity = "read"
    sched._apply_life_decision(LifeDecision(activity="sleep", duration=180, next_think_in=90))
    assert sched._last_activity_finish["reason"] == "preempted_by_agent", \
        "抢占后的时间不得算作 mind 活动时间（不得变成 completed）"


def test_preemption_outcome_applied_exactly_once():
    sched, bus, se, director, AR = _director_sched()
    fatigue_before = se.state.needs.fatigue
    director.submit(AR(source="mind", action="read", priority=3, payload={"planned_duration": 60.0}))
    director.drain()
    time.sleep(0.05)
    director.submit(AR(source="agent", action="agent_work", priority=2))
    director.drain()
    assert sched._last_activity_finish["reason"] == "preempted_by_agent"
    # 再来一个 agent 请求不会重复结算（实例已非 RUNNING）
    director.submit(AR(source="agent", action="agent_report", priority=2))
    director.drain()
    assert sched._last_activity_finish["reason"] == "preempted_by_agent", "不得重复结算"


def test_failed_or_aborted_never_receives_completed_scale():
    """抢占（success=False + progress<1）的恢复量必须小于完成（scale<1）。"""
    from furina.behavior.outcome import apply_outcome
    st_ab = CharacterState(); st_ab.needs.fatigue = 80.0
    apply_outcome(st_ab, "rest", EmotionEngine(st_ab.emotion), success=False, progress=0.3)
    st_c = CharacterState(); st_c.needs.fatigue = 80.0
    apply_outcome(st_c, "rest", EmotionEngine(st_c.emotion), success=True, progress=1.0)
    assert st_ab.needs.fatigue > st_c.needs.fatigue, "aborted 恢复量必须小于 completed"
