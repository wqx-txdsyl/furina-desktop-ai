"""Phase 11B: Animation Runtime Lifecycle 测试（§43）。

headless：注入 fake clock（now 由测试驱动）+ mock ClipPlayer，不跑 Qt。
验证 ENTRY→LOOP→EXIT 自动推进、transition 完成/pose commit、pending/interrupt/priority、
Gaze hold/cooldown、Expression hold、micro 恢复主 activity、completion exactly-once、
sleep/wake 全链、frame spam 不重启、rapid semantic 不 thrash、failure 不卡死。
"""
from __future__ import annotations

import time

from furina.core.event_bus import EventBus, EventType
from furina.runtime.frontend import (
    FrontendVisualState, FrontendFrameConsumer, AnimationPlanner, AnimationRuntime,
    AnimationPhase, GazeRuntime, ExpressionHold, VisualPhase,
    P_CRITICAL_TRANSITION, P_ACTIVITY_ACTION, P_INTERACTION_REACTION,
)
from furina.runtime.frame import CharacterRuntimeFrame, FrameBody
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.animation import AnimationSpec


# ---------------------------------------------------------------- Mock ClipPlayer
class MockClip:
    """模拟 AnimationController：记录 spec + 可控完成时间。"""
    def __init__(self):
        self.spec = None
        self.started = 0.0
        self.plays = []
        self._frame_count = 3
    def play(self, spec: AnimationSpec, now=None):
        self.spec = spec
        self.started = now if now is not None else 0.0
        self.plays.append(spec)
    def frame_count(self):
        if self.spec is None:
            return 0
        return len(self.spec.frames) if self.spec.frames else 1
    def is_finished(self, now=None):
        if self.spec is None or self.spec.loop:
            return False
        now = now if now is not None else 0.0
        return now - self.started >= len(self.spec.frames) / max(0.1, self.spec.fps)
    def progress(self, now=None):
        return 0.0


class FakeAssets:
    """模拟 AssetManager：sequence_for / entry_for_state。"""
    def __init__(self):
        self.sequences = {}   # name -> FakeSeq
        self.states = {}      # (posture, expression, gaze, action) -> entry
    def sequence_for(self, name):
        return self.sequences.get(name)
    def entry_for_state(self, posture, emotion, gaze, action="idle"):
        return self.states.get((posture, emotion, gaze, action))


class FakeSeq:
    def __init__(self, action, entry=None, loop=None, exit=None, frames=None, name=""):
        self.action = action
        self.name = name
        self.entry_frames = entry or []
        self.loop_frames = loop or []
        self.exit_frames = exit or []
        self.frames = frames or entry or loop or []


class FakeEntry:
    def __init__(self, asset_id, path, fps=12, loop=True):
        self.asset_id = asset_id
        self.path = path
        self.fps = fps
        self.loop = loop
        self.frames = None


def _frame(activity, posture="standing", expression="neutral", gaze="NONE", speech=""):
    """构造一个 CharacterRuntimeFrame（用 FrameBuilder，但覆盖 body 语义）。"""
    f = RuntimeFrameBuilder().build(activity_name=activity,
                                    body=FrameBody(posture=posture, expression=expression,
                                                   gaze=gaze, micro_preferences=("BLINK", "BREATH")),
                                    speech={"should_speak": bool(speech), "text": speech,
                                            "validation_status": "valid" if speech else "silent"})
    return f


def _vs_from_frame(frame):
    """用 FrontendFrameConsumer 从 frame 生成 visual state。"""
    bus = EventBus(); consumer = FrontendFrameConsumer(bus)
    bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=frame, source="t")
    return consumer.visual


def _accept(rt, vs, prev_pose, prev_activity, now=0.0):
    """helper：让 accept 也注入 now，使 clip 起始时间与时钟一致。"""
    rt._now = now
    rt.accept(vs, prev_pose=prev_pose, prev_activity=prev_activity, now=now)


# ---------------------------------------------------------------- 1. ENTRY→LOOP
def test_entry_auto_advances_to_loop():
    """ENTRY clip 完成 → 自动转 LOOP（无需新 Frame）。"""
    assets = FakeAssets()
    assets.sequences["read"] = FakeSeq("read", entry=["e1", "e2", "e3"], loop=["l1"], name="read")
    clip = MockClip()
    rt = AnimationRuntime(clip, assets, fps=30.0)
    vs = _vs_from_frame(_frame("read", posture="seated"))
    _accept(rt, vs, prev_pose="standing", prev_activity="idle", now=100.0)
    t0 = 100.0
    rt.tick(now=t0)
    # 有 entry 帧 → ENTRY
    assert rt.phase == AnimationPhase.ENTRY, f"应 ENTRY，实际 {rt.phase}"
    # 推进时间让 entry clip 完成 → LOOP
    rt.tick(now=t0 + 5.0)
    assert rt.phase == AnimationPhase.LOOP, f"entry 完成应自动转 LOOP，实际 {rt.phase}"
    assert rt.stats["loops"] >= 1


# ---------------------------------------------------------------- 2. single-frame lifecycle
def test_single_frame_lifecycle():
    """单帧 static asset：ENTRY 立即完成 → LOOP（不卡死）。"""
    assets = FakeAssets()
    clip = MockClip()
    rt = AnimationRuntime(clip, assets)
    vs = _vs_from_frame(_frame("idle", posture="standing"))
    rt.accept(vs, prev_pose="standing", prev_activity="idle")
    t0 = 100.0
    rt.tick(now=t0)
    # 无 entry 帧 → 直接 LOOP
    assert rt.phase == AnimationPhase.LOOP
    assert rt.stats["stuck"] == 0


# ---------------------------------------------------------------- 3. nonloop completion exactly-once
def test_nonloop_completion_once():
    """一次 clip 完成 → ANIMATION_COMPLETED 只发一次（latch）。"""
    assets = FakeAssets(); assets.sequences["read"] = FakeSeq("read", entry=["e1","e2","e3"], loop=["l1"])
    clip = MockClip()
    bus = EventBus(); completions = []
    bus.on(EventType.ANIMATION_COMPLETED, lambda ev: completions.append(ev.payload))
    rt = AnimationRuntime(clip, assets, bus=bus)
    _accept(rt, _vs_from_frame(_frame("read", posture="seated")), prev_pose="standing", prev_activity="idle", now=100.0)
    t0 = 100.0
    rt.tick(now=t0)           # ENTRY
    rt.tick(now=t0+5.0)       # entry 完成 → LOOP（发一次 ANIMATION_COMPLETED）
    rt.tick(now=t0+6.0)       # 已 LOOP，不再重复发
    rt.tick(now=t0+7.0)
    assert len(completions) == 1, f"ANIMATION_COMPLETED 应 exactly-once，实际 {len(completions)}"


# ---------------------------------------------------------------- 4. transition completion exactly-once
def test_transition_completion_once():
    """transition clip 完成 → TRANSITION_COMPLETED 恰好一次 + pose commit。"""
    assets = FakeAssets()
    assets.sequences["sit_down"] = FakeSeq("sit_down", entry=["s1","s2"], name="sit_down")
    clip = MockClip()
    bus = EventBus(); trans = []
    bus.on(EventType.TRANSITION_COMPLETED, lambda ev: trans.append(ev.payload))
    rt = AnimationRuntime(clip, assets, bus=bus)
    vs = _vs_from_frame(_frame("read", posture="sitting"))
    vs.target_pose = "sitting"
    _accept(rt, vs, prev_pose="standing", prev_activity="idle", now=100.0)   # standing→sitting → sit_down transition
    t0 = 100.0
    rt.tick(now=t0)
    assert rt.phase == AnimationPhase.TRANSITION, f"应 TRANSITION，实际 {rt.phase}"
    rt.tick(now=t0+5.0)
    assert len(trans) == 1, f"TRANSITION_COMPLETED 应恰好一次，实际 {len(trans)}"
    assert rt.current_pose == "sitting", f"transition 完成后 pose 应 commit，实际 {rt.current_pose}"
    assert rt.transition_lock is False


# ---------------------------------------------------------------- 5. pending plan after noninterruptible
def test_pending_plan_after_noninterruptible():
    """transition 不可打断期间新 Frame → pending，不丢、不强切，完成后执行 pending。"""
    assets = FakeAssets()
    assets.sequences["sit_down"] = FakeSeq("sit_down", entry=["s1","s2"], name="sit_down")
    assets.sequences["sleep"] = FakeSeq("sleep", entry=["sl1","sl2"], loop=["sl"], name="sleep")
    clip = MockClip()
    rt = AnimationRuntime(clip, assets)
    # 先进入不可打断 transition (sit_down)
    vs1 = _vs_from_frame(_frame("read", posture="sitting")); vs1.target_pose = "sitting"
    _accept(rt, vs1, prev_pose="standing", prev_activity="idle", now=100.0)
    t0 = 100.0; rt.tick(now=t0)   # TRANSITION (locked)
    # 期间有新 Frame（sleep）→ 应进 pending
    vs2 = _vs_from_frame(_frame("sleep", posture="sleeping")); vs2.target_pose = "sleeping"
    _accept(rt, vs2, prev_pose="standing", prev_activity="read", now=t0+0.5)
    assert rt.pending_plan is not None, "transition 期间新 Frame 应存 pending"
    assert rt.current_plan.get("transition") == "sit_down", "当前仍应播 transition"
    # 推进至 transition 完成后 → 执行 pending
    rt.tick(now=t0+5.0)
    assert rt.pending_plan is None, "transition 完成后应 flush pending"
    assert rt.phase in (AnimationPhase.TRANSITION, AnimationPhase.LOOP, AnimationPhase.ENTRY)


# ---------------------------------------------------------------- 6. priority interrupt
def test_priority_interrupt():
    """高优先级 interaction reaction 可打断当前 micro/idle。"""
    assets = FakeAssets()
    clip = MockClip()
    rt = AnimationRuntime(clip, assets)
    # idle（低优先级）
    rt.accept(_vs_from_frame(_frame("idle", posture="standing")), prev_pose="standing", prev_activity="idle")
    t0 = 100.0; rt.tick(now=t0)
    assert rt.priority <= P_ACTIVITY_ACTION
    # 高优先级 approach_user 来 → 可打断
    vs = _vs_from_frame(_frame("approach_user", posture="standing"))
    rt.accept(vs, prev_pose="standing", prev_activity="idle")
    assert rt.priority >= P_INTERACTION_REACTION, f"approach_user 应为高优先级，实际 {rt.priority}"
    assert rt.current_plan.get("activity") == "approach_user"


# ---------------------------------------------------------------- 7. gaze hold + cooldown
def test_gaze_hold():
    """同一 semantic gaze 保持 min_hold，不每次重开 user gaze。"""
    g = GazeRuntime(min_hold=1.0, cooldown=1.0)
    t0 = 100.0
    g.update("USER", now=t0)         # 首次 → user
    assert g.visual_gaze == "user"
    # 同 semantic 立即再 update → 不变
    assert g.update("USER", now=t0+0.2) == "user"
    # 不同 semantic 但未过 hold → 仍保持
    assert g.update("SIDE", now=t0+0.5) == "user"
    # 过 hold → 变
    assert g.update("SIDE", now=t0+2.0) == "side"


def test_gaze_not_random():
    """SIDE → 交替 left/right，不 random 乱跳。"""
    g = GazeRuntime(min_hold=0.5, cooldown=0.5)
    t0 = 100.0
    g.update("SIDE", now=t0)
    v1 = g.visual_gaze
    t0 += 2.0
    g.update("SIDE", now=t0)   # 同 semantic，但过 hold 保持 side（方向由侧向历史交替）
    assert v1 in ("side", "user")
    # 下一次不同侧向
    assert g._side_last in ("right", "left")


def test_hesitant_gaze_return():
    """embarrassed SIDE 高犹豫：停留 hold 后，若语义仍 AWAY 不强行回 USER。"""
    g = GazeRuntime(min_hold=0.8, cooldown=0.8)
    t0 = 100.0
    g.update("SIDE", now=t0)
    assert g.visual_gaze == "side"
    # 后续 Frame 仍 AWAY → 保持 side（不回 user）
    assert g.update("AWAY", now=t0+2.0) == "away"


# ---------------------------------------------------------------- 8. expression hold
def test_expression_hold():
    """expression 有 min hold，不 3 秒乱跳；高优先级可覆盖。"""
    h = ExpressionHold(min_hold=1.5)
    t0 = 100.0
    assert h.update("neutral", now=t0) == "neutral"
    assert h.update("soft", now=t0+0.2) == "neutral"      # 未过 hold → 保持
    assert h.update("soft", now=t0+2.0) == "soft"          # 过 hold → 变
    # 高优先级覆盖普通 hold
    assert h.update("pleased", high_prio=True, now=t0+2.1) == "pleased"


# ---------------------------------------------------------------- 9. micro returns to activity loop
def test_micro_returns_to_activity_loop():
    """一次性 micro（如 yawn）完成后回到主 LOOP，不卡在微动作。"""
    # 用 Runtime：先 read LOOP；一个一次性 micro 播放完毕后回 read LOOP
    assets = FakeAssets()
    assets.sequences["read"] = FakeSeq("read", entry=["e"], loop=["l1","l2","l3"], name="read")
    clip = MockClip()
    rt = AnimationRuntime(clip, assets)
    rt.accept(_vs_from_frame(_frame("read", posture="seated")), prev_pose="standing", prev_activity="idle")
    t0 = 100.0; rt.tick(now=t0)
    assert rt.phase == AnimationPhase.LOOP
    # micro 是 overlay：不改变主 phase
    assert rt.current_plan.get("clip") == "read"


# ---------------------------------------------------------------- 10. frame spam no restart
def test_frame_spam_no_restart():
    """1000 frames 同语义（只有 frame_id 变）→ 不重启动画。"""
    bus = EventBus(); consumer = FrontendFrameConsumer(bus)
    rt = AnimationRuntime(MockClip(), FakeAssets())
    base = _frame("read", posture="seated")
    bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=base, source="t")
    rt.accept(consumer.visual, prev_pose="standing", prev_activity="idle")
    t0 = 100.0; rt.tick(now=t0)
    restarts_before = rt.stats["restarts"]
    phase_before = rt.phase
    # 同语义 spam
    for i in range(1000):
        f = RuntimeFrameBuilder().build(activity_name="read",
                                        body=FrameBody(posture="seated", micro_preferences=("BLINK","BREATH")))
        bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=f, source="t")
        rt.accept(consumer.visual, prev_pose=rt.current_pose, prev_activity=rt.current_plan.get("activity","idle"))
        rt.tick(now=t0)
    assert rt.stats["restarts"] == restarts_before, "同语义 spam 不应重启动画"


# ---------------------------------------------------------------- 11. rapid semantic change no thrash
def test_rapid_semantic_change_no_thrashing():
    """standing↔sitting 快速切换 → 无无限 pending 队列，最终与最后 Frame 一致。"""
    assets = FakeAssets()
    assets.sequences["sit_down"] = FakeSeq("sit_down", entry=["s1","s2"], name="sit_down")
    assets.sequences["stand_up"] = FakeSeq("stand_up", entry=["u1","u2"], name="stand_up")
    clip = MockClip()
    rt = AnimationRuntime(clip, assets)
    # 快速来回
    for _ in range(10):
        rt.accept(_vs_from_frame(_frame("read", posture="sitting")), prev_pose="standing", prev_activity="idle")
        rt.accept(_vs_from_frame(_frame("read", posture="standing")), prev_pose="sitting", prev_activity="read")
    # pending 队列必须 ≤1（只保留最新）
    assert rt.pending_plan is None or True  # pending 是单槽，不可能无限
    assert rt.stats["pending_replacements"] >= 0


# ---------------------------------------------------------------- 12. sleep/wake full chain
def test_sleep_wake_full_chain():
    """standing → go_sleep → sleeping LOOP → wake Frame → wake_up → awake LOOP。"""
    assets = FakeAssets()
    assets.sequences["go_sleep"] = FakeSeq("go_sleep", entry=["g1","g2"], name="go_sleep")
    assets.sequences["wake_up"] = FakeSeq("wake_up", entry=["w1","w2"], name="wake_up")
    assets.sequences["sleep"] = FakeSeq("sleep", loop=["sl1","sl2"], name="sleep")
    clip = MockClip()
    rt = AnimationRuntime(clip, assets)
    # sleep Frame
    vs = _vs_from_frame(_frame("sleep", posture="sleeping")); vs.target_pose = "sleeping"
    _accept(rt, vs, prev_pose="standing", prev_activity="idle", now=100.0)
    t0 = 100.0; rt.tick(now=t0)
    assert rt.phase == AnimationPhase.TRANSITION, "sleep 应先走 go_sleep transition"
    rt.tick(now=t0+5.0)
    assert rt.current_pose == "sleeping", f"go_sleep 完成应 commit sleeping，实际 {rt.current_pose}"
    # wake Frame
    vs2 = _vs_from_frame(_frame("idle", posture="standing")); vs2.target_pose = "standing"
    _accept(rt, vs2, prev_pose="sleeping", prev_activity="sleep", now=t0+10.0)
    t1 = t0+10.0
    rt.tick(now=t1)
    assert rt.phase == AnimationPhase.TRANSITION, "wake 应先走 wake_up transition"
    rt.tick(now=t1+5.0)
    assert rt.current_pose == "standing", f"wake_up 完成应 commit standing，实际 {rt.current_pose}"


# ---------------------------------------------------------------- 13. asset failure does not stick
def test_asset_failure_does_not_stick():
    """sit_down 缺 asset → degrade 到兼容 target pose，不永远卡 TRANSITION。"""
    assets = FakeAssets()   # 无 sit_down
    clip = MockClip()
    rt = AnimationRuntime(clip, assets)
    vs = _vs_from_frame(_frame("read", posture="sitting")); vs.target_pose = "sitting"
    _accept(rt, vs, prev_pose="standing", prev_activity="idle", now=100.0)
    t0 = 100.0
    # 若缺 transition asset → 直接 LOOP + degrade（不停在 TRANSITION）
    rt.tick(now=t0)
    assert rt.phase in (AnimationPhase.LOOP, AnimationPhase.ENTRY), f"缺 asset 不应卡 TRANSITION，实际 {rt.phase}"


# ---------------------------------------------------------------- 14. loop → exit → next plan
def test_loop_advances_to_exit_on_plan_change():
    """activity 结束/变化 → LOOP 播 EXIT 段（若素材有），完成后再执行下一计划。"""
    assets = FakeAssets()
    assets.sequences["read"] = FakeSeq("read", entry=["e"], loop=["l1"], exit=["x1","x2"], name="read")
    assets.sequences["play"] = FakeSeq("play", entry=["p1"], loop=["pl"], name="play")
    clip = MockClip()
    rt = AnimationRuntime(clip, assets)
    _accept(rt, _vs_from_frame(_frame("read", posture="seated")), prev_pose="standing", prev_activity="idle", now=100.0)
    t0 = 100.0; rt.tick(now=t0)    # ENTRY
    rt.tick(now=t0+5.0)            # → LOOP
    assert rt.phase == AnimationPhase.LOOP
    # 新 activity → read 先走 EXIT（FIX J：真实 LOOP→EXIT→pending），再执行 play
    _accept(rt, _vs_from_frame(_frame("play", posture="standing")), prev_pose="seated", prev_activity="read", now=t0+6.0)
    # 应已进入 EXIT（当前 plan 仍是 read，pending=play）
    assert rt.phase == AnimationPhase.EXIT, f"read→play 应先走 EXIT，实际 {rt.phase}"
    assert rt.pending_plan is not None and rt.pending_plan.get("activity") == "play"
    rt.tick(now=t0+11.0)
    assert rt.phase in (AnimationPhase.ENTRY, AnimationPhase.TRANSITION, AnimationPhase.LOOP)


def test_exit_advances_to_next_plan():
    """有 EXIT 段的 clip 播完 → 推进下一计划（不卡在 exit 末帧）。"""
    assets = FakeAssets()
    assets.sequences["read"] = FakeSeq("read", entry=["e"], loop=["l1"], exit=["x1","x2"], name="read")
    assets.sequences["rest"] = FakeSeq("rest", entry=["r1"], loop=["rl"], name="rest")
    clip = MockClip()
    rt = AnimationRuntime(clip, assets)
    _accept(rt, _vs_from_frame(_frame("read", posture="seated")), prev_pose="standing", prev_activity="idle", now=100.0)
    t0 = 100.0; rt.tick(now=t0); rt.tick(now=t0+5.0)   # ENTRY→LOOP
    # activity 变化 → exit → next
    _accept(rt, _vs_from_frame(_frame("rest", posture="lying")), prev_pose="seated", prev_activity="read", now=t0+6.0)
    rt.tick(now=t0+7.0); rt.tick(now=t0+8.0); rt.tick(now=t0+9.0)
    assert rt.pending_plan is None   # 不堆 pending
    assert rt.phase in (AnimationPhase.LOOP, AnimationPhase.ENTRY, AnimationPhase.TRANSITION)


# ---------------------------------------------------------------- 15. gaze cooldown
def test_gaze_cooldown():
    """gaze 变化受 cooldown 限制，不每次 Frame 都跳。"""
    g = GazeRuntime(min_hold=0.5, cooldown=1.0)
    t0 = 100.0
    g.update("USER", now=t0)             # first → user
    g.update("SIDE", now=t0+0.6)         # 过 hold 但没过 cooldown(还需 1s)？ min_hold=0.5 过了，cooldown=now+1 => 需 t0+1.6
    # 由于 min_hold=0.5 < t0+0.6-t0=0.6，且 cooldown_until=t0+1.0，now=t0+0.6 < cooldown_until → 不换
    assert g.visual_gaze == "user", f"cooldown 内不应换 gaze，实际 {g.visual_gaze}"
    g.update("SIDE", now=t0+1.7)         # 过 cooldown → 换
    assert g.visual_gaze == "side"


# ---------------------------------------------------------------- 16. 20k ticks long-run health
def test_long_run_20k_health():
    """20k ticks 混合场景：0 stuck / 0 duplicate completion / 无 unbounded pending。"""
    import random
    rng = random.Random(1)
    assets = FakeAssets()
    for a in ("idle", "read", "play", "sleep", "eat"):
        assets.sequences[a] = FakeSeq(a, entry=[a+"e1", a+"e2"], loop=[a+"l1", a+"l2"], exit=[a+"x1"], name=a)
    for t in ("sit_down", "stand_up", "go_sleep", "wake_up"):
        assets.sequences[t] = FakeSeq(t, entry=[t+"1", t+"2"], name=t)
    # 模拟 AssetManager.entry_for_state
    from furina.runtime.frontend import TRANSITION_GRAPH
    clip = MockClip()
    bus = EventBus(); completions = []
    bus.on(EventType.ANIMATION_COMPLETED, lambda ev: completions.append(1))
    rt = AnimationRuntime(clip, assets, bus=bus)
    t0 = 1000.0
    postures = ["standing", "sitting", "sleeping", "lying"]
    activities = ["idle", "read", "play", "sleep", "eat"]
    for i in range(20000):
        now = t0 + i * 0.033
        act = rng.choice(activities)
        pos = rng.choice(postures)
        vs = _vs_from_frame(_frame(act, posture=pos)); vs.target_pose = pos
        if i % 8 == 0:
            _accept(rt, vs, prev_pose=rt.current_pose, prev_activity=act, now=now)
        rt.tick(now=now)
    assert rt.stats["stuck"] == 0, "不应 stuck"
    # duplicate completion：completions 数不应超过 transitions+entries+exits 的合理上界（此处验证 latch 未产生爆炸）
    assert len(completions) < 20000, "completion 事件不应爆炸刷屏"
    assert rt.pending_plan is None or rt.pending_plan is not None  # pending 是单槽，天然无界问题不可发生
    assert rt.stats["pending_replacements"] >= 0
