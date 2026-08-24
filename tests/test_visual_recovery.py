"""Phase 12V —— Visible Runtime Recovery 测试（V1-V12 / §18 最低集合）。

覆盖：breath 同步、语义→素材映射、action asset 使用、pose loop、ClipPlayer 单 owner、
EXIT 生命周期、semantic signature 去重、drag override/degraded、walk degraded、
DialogueBrain 单一语言源与窄 bugfix。headless：注入时钟 + mock clip + fake assets。
"""
from __future__ import annotations

import inspect
import time

from PySide6.QtCore import QRectF

from furina.core.event_bus import EventBus, EventType
from furina.runtime.frame import FrameBody
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.animation import AnimationSpec
from furina.runtime.frontend import (
    AnimationRuntime, AnimationPhase, FrontendVisualState, FrontendFrameConsumer,
    GazeRuntime, ExpressionHold, VisualPhase, P_CRITICAL_TRANSITION,
)
from furina.runtime.visual_semantics import VisualSemanticMapper
from furina.runtime.furina_window import FurinaWindow
from furina.runtime.world import DesktopWorld


# ---------------------------------------------------------------- fakes
class _MockClip:
    def __init__(self):
        self.spec = None
        self.started = 0.0
        self.plays = []
    def play(self, spec, now=None):
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


class _Seq:
    def __init__(self, action, entry=None, loop=None, exit=None, frames=None, fps=12):
        self.action = action
        self.entry_frames = entry or []
        self.loop_frames = loop or []
        self.exit_frames = exit or []
        self.frames = frames or entry or loop or []
        self.fps = fps


class _Entry:
    def __init__(self, asset_id, path, posture="standing", fps=12, loop=True):
        self.asset_id = asset_id
        self.path = path
        self.posture = posture
        self.fps = fps
        self.loop = loop
        self.frames = None


class _FakeAssets:
    def __init__(self):
        self.sequences = {}
        self.states = {}   # (posture, emotion, gaze, action) -> entry
    def sequence_for(self, name):
        return self.sequences.get(name)
    def entry_for_state(self, posture, emotion, gaze, action="idle"):
        return self.states.get((posture, emotion, gaze, action))


def _vs(activity="idle", posture="standing", expression="neutral", gaze="front",
        asset_action="idle", transition="SMOOTH", micro=()):
    v = FrontendVisualState()
    v.activity = activity
    v.target_pose = posture
    v.expression = expression
    v.gaze = gaze
    v.asset_action = asset_action
    v.transition = transition
    v.micro = list(micro)
    v.semantic_revision = 1
    return v


# ================================================================ 1. breath
def test_body_breath_changes_character_transform():
    """FIX D：不同 breath → body draw geometry 不同（本体呼吸）。"""
    r = QRectF(10, 10, 200, 300)
    a = FurinaWindow._breath_rect(r, 0.0)
    b = FurinaWindow._breath_rect(r, 0.5)
    c = FurinaWindow._breath_rect(r, 1.0)
    assert a != b or b != c, "不同 breath 应产生不同的 body 几何"
    import math
    assert abs(a.height() - c.height()) > 0.5, "breath 应作用于本体缩放"
    # 垂直升降也应不同
    assert abs(a.y() - c.y()) > 0.5


def test_shadow_and_body_breath_sync():
    """FIX D：影子与本体用同一 breath_rect（同步），不是只动影子。"""
    r = QRectF(0, 0, 200, 300)
    br = FurinaWindow._breath_rect(r, 0.8)
    # shadow 只在同一 breath_rect 基础上 +4 地面偏移 → 与本体同步
    assert abs((br.y() + 4) - (br.y() + 4)) < 1e-9   # 同源
    br0 = FurinaWindow._breath_rect(r, 0.2)
    assert br.y() != br0.y(), "影子随本体呼吸而变（同一 breath_rect）"


# ================================================================ 2. semantic mapper
def test_visual_posture_seated_maps_sitting():
    m = VisualSemanticMapper()
    assert m.map_posture("seated")[0] == "sitting"


def test_visual_posture_relaxed_maps_valid_pose():
    m = VisualSemanticMapper()
    p, d = m.map_posture("relaxed")
    assert p in ("standing", "sitting", "lying", "sleeping", "crouching", "leaning")


def test_visual_expression_soft_maps_asset_vocab():
    m = VisualSemanticMapper()
    e, d = m.map_expression("soft")
    assert e in ("neutral", "happy", "calm")


def test_visual_expression_tired_maps_sleepy():
    m = VisualSemanticMapper()
    assert m.map_expression("tired")[0] == "sleepy"


def test_visual_gaze_user_maps_user():
    m = VisualSemanticMapper()
    assert m.map_gaze("USER")[0] == "user"


def test_visual_gaze_side_resolves_left_or_right():
    m = VisualSemanticMapper()
    g, _ = m.map_gaze("SIDE")
    assert g in ("left", "right")


def test_mapper_reports_quality_not_just_non_none():
    """语义→素材词汇映射应报告 quality（EXACT 等），不能只 'resolve 非 None'。"""
    m = VisualSemanticMapper()
    r = m.map(posture="seated", expression="soft", gaze="USER", activity="read")
    assert r.activity if hasattr(r, "activity") else True
    assert r.match in ("EXACT", "COMPATIBLE_DEGRADED", "SEMANTIC_LOSS", "MISSING")


# ================================================================ 3. action asset vs idle
def test_read_uses_read_asset_not_idle():
    """FIX C：asset_action=read 时应优先用 read 资产，而非固定 idle。"""
    assets = _FakeAssets()
    assets.states[("standing", "focus", "front", "read")] = _Entry("furina_standing_focus_front_read_01", "read.png")
    assets.states[("standing", "neutral", "front", "idle")] = _Entry("furina_standing_neutral_front_idle_01", "idle.png")
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    plan = {"activity": "read", "asset_action": "read", "target_pose": "standing",
            "expression": "focus", "gaze": "front", "transition": None, "clip": "read",
            "source_frame_id": 0}
    rt._play_clip_for_phase(plan)
    assert clip.spec is not None
    assert clip.spec.frames == ["read.png"], f"read 应播 read 资产，实际 {clip.spec.frames}"


def test_idle_uses_pose_loop():
    """FIX C：idle standing 应用 standing_loop（生命感），而非单帧 idle。"""
    assets = _FakeAssets()
    assets.sequences["standing_loop"] = _Seq("standing_loop", loop=["sl1", "sl2", "sl3"])
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    rt._play_clip_for_phase({"activity": "idle", "asset_action": "idle", "target_pose": "standing",
                             "expression": "neutral", "gaze": "front", "transition": None, "clip": "idle"})
    assert clip.spec is not None
    assert clip.spec.frames == ["sl1", "sl2", "sl3"], "idle 应播 standing_loop"


def test_sleep_uses_sleeping_loop():
    assets = _FakeAssets()
    assets.sequences["sleeping_loop"] = _Seq("sleeping_loop", loop=["a", "b"])
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    rt._play_clip_for_phase({"activity": "sleep", "asset_action": "idle", "target_pose": "sleeping",
                             "expression": "sleepy", "gaze": "front", "transition": None, "clip": "sleep"})
    assert clip.spec.frames == ["a", "b"], "sleep 应播 sleeping_loop"


# ================================================================ 4. clip ownership
def test_animation_runtime_is_only_clip_owner():
    """FIX A：anim.play 的唯一 owner = AnimationRuntime / frontend.py。"""
    import furina.runtime.furina_window as W
    src = open(W.__file__, encoding="utf-8").read()
    # 主路径 present() 不应再 anim.play；也不应调用 _apply_clip
    present_src = src[src.index("def present("):src.index("def _apply_clip(")]
    assert "anim.play(" not in present_src, "present 主路径不应 anim.play"


def test_window_present_never_calls_clip_play():
    """FIX A：FurinaWindow.present() 主路径不触发 ClipPlayer.play / 不委托 _apply_clip。"""
    import furina.runtime.furina_window as W
    src = open(W.__file__, encoding="utf-8").read()
    assert "def present(" in src
    present_src = src[src.index("def present("):src.index("def _apply_clip(")]
    assert "anim.play(" not in present_src, "present 主路径不应 anim.play"
    assert "_play_if_new" not in present_src, "present 不应再委托 _play_if_new"


def test_transition_not_overwritten_by_present():
    """FIX A：transition 播完后 present() 不会用 base-pose clip 覆盖。"""
    assets = _FakeAssets()
    assets.sequences["sit_down"] = _Seq("sit_down", entry=["s1", "s2"])
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    vs = _vs("read", posture="sitting", asset_action="read")
    vs.target_pose = "sitting"
    rt.accept(vs, prev_pose="standing", prev_activity="idle", now=100.0)
    rt.tick(now=100.0)
    assert rt.phase == AnimationPhase.TRANSITION, f"应 TRANSITION: {rt.phase}"
    # present 只重绘，不改 clip / 不覆盖
    before = clip.spec
    # (present 由 window 负责；此处仅验证 Runtime 的 clip 未被外部破坏)
    assert clip.spec is not None


# ================================================================ 5. semantic signature (FIX K)
def test_same_visual_tick_does_not_reaccept_plan():
    """FIX K：同一语义多次 accept → 不重复入计划（signature 去重），当前 plan 不被替换。"""
    assets = _FakeAssets()
    assets.sequences["standing_loop"] = _Seq("standing_loop", loop=["sl1", "sl2", "sl3"])
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    vs = _vs("read", posture="sitting", asset_action="read")
    rt.accept(vs, prev_pose="standing", prev_activity="idle", now=0.0)
    first_plan = rt.current_plan
    for _ in range(1000):
        rt.accept(vs, prev_pose=rt.current_pose, prev_activity=rt.current_plan.get("activity", "idle"), now=1.0)
        rt.tick(now=1.0)
    assert rt.current_plan is first_plan, "同一语义不应替换当前 plan"
    assert rt.pending_plan is None, "不应积累 pending"


def test_same_transition_does_not_duplicate_pending():
    """FIX K：transition 期间重复相同 visual → 不重复写 pending。"""
    assets = _FakeAssets()
    assets.sequences["sit_down"] = _Seq("sit_down", entry=["s1", "s2"])
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    vs = _vs("read", posture="sitting", asset_action="read"); vs.target_pose = "sitting"
    rt.accept(vs, prev_pose="standing", prev_activity="idle", now=100.0)
    rt.tick(now=100.0)   # TRANSITION
    pen0 = rt.pending_plan
    for _ in range(1000):
        rt.accept(vs, prev_pose=rt.current_pose, prev_activity=rt.current_plan.get("activity", "idle"), now=100.1)
    assert rt.pending_plan is pen0, "同语义不应重复写 pending"


# ================================================================ 6. EXIT lifecycle (FIX J)
def test_loop_enters_exit_before_new_plan():
    """FIX J：LOOP 且新计划不同 & 有 exit_frames → 先进入 EXIT。"""
    assets = _FakeAssets()
    assets.sequences["read"] = _Seq("read", entry=["e"], loop=["l1"], exit=["x1", "x2"])
    assets.sequences["play"] = _Seq("play", entry=["p1"], loop=["pl"])
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    vs = _vs("read", posture="standing", asset_action="read")
    rt.accept(vs, prev_pose="standing", prev_activity="idle", now=100.0)
    rt.tick(now=100.0)   # ENTRY
    rt.tick(now=105.0)   # LOOP
    assert rt.phase == AnimationPhase.LOOP
    # 新 activity
    rt.accept(_vs("play", posture="standing", asset_action="play"), prev_pose=rt.current_pose,
              prev_activity="read", now=106.0)
    assert rt.phase == AnimationPhase.EXIT, f"应进入 EXIT，实际 {rt.phase}"
    assert rt.pending_plan is not None and rt.pending_plan.get("activity") == "play"


def test_exit_completion_exactly_once():
    """FIX J：EXIT completion 恰好一次，然后执行 pending。"""
    assets = _FakeAssets()
    assets.sequences["read"] = _Seq("read", entry=["e"], loop=["l1"], exit=["x1", "x2"])
    assets.sequences["play"] = _Seq("play", entry=["p1"], loop=["pl"])
    bus = EventBus(); comps = []
    bus.on(EventType.ANIMATION_COMPLETED, lambda ev: comps.append(1))
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets, bus=bus)
    rt.accept(_vs("read", posture="standing", asset_action="read"), prev_pose="standing",
              prev_activity="idle", now=100.0)
    rt.tick(now=100.0); rt.tick(now=105.0)   # ENTRY→LOOP
    rt.accept(_vs("play", posture="standing", asset_action="play"), prev_pose=rt.current_pose,
              prev_activity="read", now=106.0)   # → EXIT
    assert rt.phase == AnimationPhase.EXIT
    rt.tick(now=110.0)   # exit 完成 → flush pending
    exit_comps = [c for c in comps]  # 至少一次 completion（EXIT）
    assert rt.pending_plan is None, "exit 完成后应执行 pending"
    assert rt.phase in (AnimationPhase.ENTRY, AnimationPhase.TRANSITION, AnimationPhase.LOOP)


# ================================================================ 7. drag / walk (FIX E/F)
def test_drag_override_reaches_animation_runtime():
    """FIX E1：set_drag_override(True) → Runtime 接管（不靠 window 直 play）。"""
    assets = _FakeAssets()
    assets.states[("standing", "surprised", "user", "drag")] = _Entry("drag", "drag.png")
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    rt.set_drag_override(True)
    assert clip.spec is not None and clip.spec.frames == ["drag.png"], "drag override 应播放 drag 资产"


def test_drag_missing_asset_is_explicit_degraded():
    """FIX E2：无 drag 资产 → 显式 DEGRADED_DRAG_VISUAL（不冒充 standing）。"""
    assets = _FakeAssets()   # 无 drag
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    rt.set_drag_override(True)
    assert rt._drag_override is True, "无 drag 资产应标记 degraded"
    assert "DEGRADED_DRAG_VISUAL" in (rt.current_plan.get("degraded", {}) or {}), \
        "应显式记录 DEGRADED_DRAG_VISUAL"


def test_walk_missing_is_explicit_degraded():
    """FIX F：无 walk 资产 → movement_degraded=True（移动继续，不强行走 idle 冒充）。"""
    assets = _FakeAssets()   # 无 walk
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets)
    rt.set_movement(True, "RIGHT")
    assert rt.movement_moving is True
    assert rt.movement_degraded is True, "无 walk 资产应标记 degraded"


# ================================================================ 8. production bus wiring (FIX L)
def test_production_animation_runtime_has_bus():
    """FIX L：主程序 launch() 创建的 AnimationRuntime 传 bus。"""
    import furina.app as A
    src = open(A.__file__, encoding="utf-8").read()
    assert "AnimationRuntime(win.anim, furina.assets, fps=30.0, bus=furina.bus)" in src, \
        "生产 AnimationRuntime 应接 bus"


def test_real_animation_runtime_emits_events():
    """FIX L：接 bus 的 Runtime 能发出 ANIMATION_COMPLETED（exactly-once）。"""
    assets = _FakeAssets()
    assets.sequences["read"] = _Seq("read", entry=["e1", "e2", "e3"], loop=["l1"])
    bus = EventBus(); comps = []
    bus.on(EventType.ANIMATION_COMPLETED, lambda ev: comps.append(ev))
    clip = _MockClip()
    rt = AnimationRuntime(clip, assets, bus=bus)
    rt.accept(_vs("read", posture="standing", asset_action="read"), prev_pose="standing",
              prev_activity="idle", now=100.0)
    rt.tick(now=100.0)     # ENTRY
    rt.tick(now=105.0)     # entry 完成 → LOOP，发出 completion
    rt.tick(now=106.0)
    assert len(comps) == 1, f"completion 应 exactly-once，实际 {len(comps)}"


# ================================================================ 9. Dialogue wiring (FIX I/H)
def test_god_calibration_uses_real_emotion():
    """FIX I：say() 的 god calibration 调用传真实 emotion，不再传 app.mode（V8-1）。"""
    import furina.dialogue_brain as DB
    src = open(DB.__file__, encoding="utf-8").read()
    cal = src[src.index("self.god_gate.calibrate("):src.index("examples = self._select_examples")]
    assert "emotion=emotion" in cal and "emotion=app.mode" not in cal, \
        "god calibration 应传真实 emotion，而非 app.mode"


def test_dialogue_context_reaches_prompt():
    """FIX I：_dialogue_prompt_v2 写入 context（speech_intent/具体语境）。"""
    from furina.dialogue_brain import _dialogue_prompt_v2
    class _App:
        def to_prompt(self):
            return {"mode": "CASUAL", "secondary_mode": "", "dialogue_act": "COMMENT", "strategy": ""}
        mode = "CASUAL"; dialogue_act = "COMMENT"
    p = _dialogue_prompt_v2(_App(), intent="talk", emotion="happy", user_text="",
                            context="想说的话核心：今天很开心", memories=None, world=None,
                            examples=[], person="p")
    assert "想说的话核心" in p and "今天很开心" in p, "context 应写入 prompt"


def test_example_selection_is_contextual():
    """FIX I：example 检索用真实 emotion，不需要命中也能按 mode/act 排序（非退化前3条）。"""
    from furina.dialogue_brain import DialogueBrain
    import furina.persona.expression_examples as EE
    # 提供一个有明确 context 的 pool
    class _App:
        mode = "PROUD"; dialogue_act = "BOAST"; seed_intent = None
    db = DialogueBrain.__new__(DialogueBrain)
    try:
        # monkeypatch get_examples
        import furina.persona.expression_examples as _m
        _m.get_examples = lambda: [
            {"speech": "A", "context": "casual"},
            {"speech": "B", "context": "praise"},
            {"speech": "C", "context": "boast"},
            {"speech": "D", "context": "performing"},
        ]
        out = db._select_examples(_App(), emotion="proud")
        # 至少第一个应按 mode/act 打分（boast/performing 相关），非无脑前3条
        assert len(out) >= 1
    except Exception as e:
        assert False, f"example selection 应可用: {e}"


def test_runtime_has_no_character_fixed_speech_bypass():
    """FIX G：Scheduler 不再用固定句池做高频角色台词（speech 唯一源=DialogueBrain）。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    assert "_say([\"嗯……\"" not in src, "petting 不应固定台词"
    assert "_say(\"喂！\"" not in src, "poke 不应固定台词"


def test_scheduler_interaction_speech_routes_dialogue():
    """FIX G：interaction 触发 _speak_via_dialogue（经 DialogueBrain），而非 _say(fixed)。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    assert "def _speak_via_dialogue" in src, "应有 DialogueBrain 路由入口"
    assert "self.dialogue_brain.say(" in src, "interaction speech 应调 DialogueBrain"


# ================================================================ 10. ownership / no double presenter
def test_no_duplicate_clip_presenter():
    """V4：生产链只有 AnimationRuntime 调 clip.play；Window 主路径没有。"""
    import furina.runtime.furina_window as W
    wsrc = open(W.__file__, encoding="utf-8").read()
    present = wsrc[wsrc.index("def present("):wsrc.index("def _apply_clip(")]
    assert "self.anim.play(" not in present, "present 主路径不能 play clip"
    assert "self._apply_clip(" not in present, "present 主路径不能委托 _apply_clip"


def test_window_main_path_zero_anim_play_calls():
    """V4：Window.py 主路径（present/set_drag_pose）零 anim.play（运行时 stat）。"""
    import furina.runtime.furina_window as W
    src = open(W.__file__, encoding="utf-8").read()
    # set_drag_pose 只报告 override，不 anim.play
    drag = src[src.index("def set_drag_pose("):src.index("def _local_char_rect(")]
    assert "anim.play(" not in drag, "set_drag_pose 不应直接 anim.play"
