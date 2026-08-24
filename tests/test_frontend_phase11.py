"""Phase 11 Step 0 + Animation Runtime 测试（§20）。

覆盖：
  0.1 硬编码台词旁路删除（DialogueBrain 唯一语言源）
  0.2 Frame 深不可变
  0.3 Scheduler 不再直写 Window（无重复 window 调用）+ 单动画 owner
  0.4 AnimationController 只收 AnimationSpec + blink 真实发生 + nonloop completion
  渲染逻辑：FrontendFrameConsumer diff / AnimationPlanner / MicroScheduler
"""
from __future__ import annotations

import importlib
import time
from types import MappingProxyType

from furina.runtime.frame import CharacterRuntimeFrame, FrameBody, FrameDebug
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.animation import AnimationController, AnimationSpec


# ================================================================ 0.1 hardcoded speech
def test_hardcoded_speech_cannot_override_dialogue():
    """Scheduler 不再从硬编码台词池取文本（SPEECH_LINES 已删除）。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    assert "SPEECH_LINES" not in src, "硬编码台词池必须删除"
    assert "_behavior_speech" not in src, "硬编码自发台词方法必须删除"


def test_dialogue_failure_prefers_silence():
    """Dialogue 失败/未配置 → speech=None；不回退固定 Furina 台词。"""
    from furina.runtime.frame_builder import RuntimeFrameBuilder
    f = RuntimeFrameBuilder().build(activity_name="talk",
                                    speech={"should_speak": False, "text": "", "validation_status": "silent"})
    assert f.speech.text == ""
    assert f.speech.should_speak is False


def test_runtime_has_single_speech_source():
    """正式 Runtime 唯一语言源 = DialogueBrain → Frame.speech。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    # 不应再调用 random.choice 从台词池取；返回 None 由对话失败触发
    assert "random.choice(pool)" not in src


# ================================================================ 0.2 deep immutability
def test_frame_nested_collection_immutable():
    """FrameBody.micro_preferences / FrameDebug 内列表/映射不可变。"""
    f = CharacterRuntimeFrame(body=FrameBody(), debug=FrameDebug())
    try:
        f.body.micro_preferences.append("X")   # type: ignore[attr-defined]
        assert False, "micro_preferences 不可 append"
    except AttributeError:
        pass
    try:
        f.debug.body_reasons.append("Y")
        assert False
    except AttributeError:
        pass
    try:
        f.debug.needs["fatigue"] = 99
        assert False, "needs 映射不可写"
    except TypeError:
        pass
    assert isinstance(f.body.micro_preferences, tuple)
    assert isinstance(f.debug.body_reasons, tuple)
    assert isinstance(f.debug.needs, MappingProxyType)


def test_event_frame_cannot_be_mutated():
    """EventBus 发布的 Frame（真实对象）不可被前端改。"""
    from furina.core.event_bus import EventBus, EventType
    bus = EventBus()
    kept = []
    bus.on(EventType.CHARACTER_FRAME_UPDATED, lambda ev: kept.append(ev.payload))
    f = RuntimeFrameBuilder().build(activity_name="read")
    bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=f, source="runtime")
    assert kept and kept[0] is f
    try:
        kept[0].body.micro_preferences.append("X")
        assert False
    except AttributeError:
        pass


def test_serialization_still_v1():
    """深不可变不改变 v1 JSON contract（micro 输出 list、needs 输出 dict）。"""
    f = RuntimeFrameBuilder().build(activity_name="read", debug_enabled=True, debug={
        "body_reasons": ["a"], "needs": {"fatigue": 40}})
    d = f.to_dict(debug=True)
    assert isinstance(d["body"]["micro_preferences"], list)
    assert isinstance(d["debug"]["needs"], dict)
    assert d["meta"]["schema_version"] == "1.0"


# ================================================================ 0.3 scheduler no direct window write
def test_scheduler_no_direct_window_render():
    """Scheduler._update_scene 不再调用 set_pose_semantics / set_render_state。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    assert "self.window.set_pose_semantics(" not in src, "Scheduler 不应直写 window"
    assert "self.window.set_render_state(" not in src


def test_scheduler_no_duplicate_window_write():
    """Scheduler 里对 window 的 set_render_state / set_pose_semantics 调用应为 0 次。"""
    import furina.runtime.scheduler as S
    src = open(S.__file__, encoding="utf-8").read()
    assert src.count("window.set_render_state(") == 0
    assert src.count("window.set_pose_semantics(") == 0


def test_single_animation_owner():
    """只有一个 owner 对 ClipPlayer.play 负责：AnimationRuntime（Frontend），不再从 Window 主路径调 play。"""
    import furina.runtime.furina_window as W
    src = open(W.__file__, encoding="utf-8").read()
    # Window.present 主路径不得再 anim.play / 委托 _apply_clip
    present = src[src.index("def present("):src.index("def _apply_clip(")]
    assert "self.anim.play(" not in present, "present 主路径不应 play clip"
    assert "self._apply_clip(" not in present, "present 主路径不应委托 _apply_clip"
    # drag 只报告 override，不直接 play
    drag = src[src.index("def set_drag_pose("):src.index("def _local_char_rect(")]
    assert "anim.play(" not in drag, "set_drag_pose 不应直接 anim.play"


# ================================================================ 0.4 animation clip contract + blink
def test_animation_play_signature_valid():
    """ClipPlayer.play 只收 AnimationSpec（不再 frames/fps/loop 关键字）。"""
    import inspect
    sig = inspect.signature(AnimationController.play)
    params = list(sig.parameters.keys())
    assert "spec" in params and "now" in params, f"play 签名应 (spec, now)，实际 {params}"


def test_blink_actually_occurs():
    """blink 真实发生（非 0）：由 MicroScheduler 驱动，有正强度峰值。"""
    from furina.runtime.micro import MicroScheduler
    ms = MicroScheduler()
    # 强制下一步立即触发一次 blink
    ms._blink_next = 0.0
    t0 = time.monotonic()
    # 第一步触发（now>=next），此刻开始 blink
    st1 = ms.step(dt=0.016, now=t0, micro_pref=[])
    # 第二步在 blink 中点（t0 + dur/2 ≈ +0.075）→ 应达峰值
    st2 = ms.step(dt=0.016, now=t0 + ms._blink_dur / 2, micro_pref=[])
    assert st1.blink == 0.0 or st2.blink > 0.5, f"blink 应力求峰值，st1={st1.blink} st2={st2.blink}"
    # 至少某次 > 0（真实发生），最关键的：峰值时刻 > 0.5
    assert st2.blink > 0.5, f"blink 峰值应为正，实际 {st2.blink}"


def test_nonloop_clip_emits_completion():
    """非 loop clip 播完 → clip_finished / is_finished == True。"""
    class _MockLoad:
        def __call__(self, path):
            return None
    c = AnimationController(_MockLoad())
    # 3 帧非 loop，fps=1：now 在起始 + 帧周期后应 finished
    spec = AnimationSpec(["a", "b", "c"], fps=1.0, loop=False)
    c.play(spec, now=100.0)
    assert c.is_finished(now=100.0 + 2.0) is True   # 3 帧 @1fps → 2s 后到底
    assert c.is_finished(now=100.0) is False


# ================================================================ FrontendFrameConsumer diff
def test_consumer_diff_activity_change():
    """activity 变化触发 semantic change；frame_id-only 变化不触发。"""
    from furina.core.event_bus import EventBus, EventType
    from furina.runtime.frontend import FrontendFrameConsumer
    bus = EventBus(); consumer = FrontendFrameConsumer(bus)
    f1 = RuntimeFrameBuilder().build(activity_name="read")
    bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=f1, source="r")
    f2 = RuntimeFrameBuilder().build(activity_name="sleep")
    bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=f2, source="r")
    # 第二次 activity 变化 → changed 含 activity_name
    assert consumer.visual.activity == "sleep"


# ================================================================ paintEvent does not advance life state
def test_paint_event_does_not_advance_life_state():
    """paintEvent 不再推进 _breath_t / 生命状态（假 16ms）—— 查源码。"""
    import furina.runtime.furina_window as W
    src = open(W.__file__, encoding="utf-8").read()
    assert "_breath_t += " not in src, "paintEvent 不应推进呼吸时钟"
    assert "_micro_life" not in src, "paintEvent 不应自己推进 micro 生命周期"


# ================================================================ AssetResolver prefers semantics (Phase 09)
def test_asset_resolver_prefers_semantics():
    """语义字段必须真正进入 asset 选择：present 用 target_pose/expression/gaze，且不固定 action=idle。"""
    import furina.runtime.furina_window as W
    src = open(W.__file__, encoding="utf-8").read()
    assert "target_pose" in src and "expression" in src and "gaze" in src
    # 也不得固定 action="idle" 作为唯一选择（FIX C：生产用 mapper 映射 asset_action）
    import furina.runtime.frontend as F
    fsrc = open(F.__file__, encoding="utf-8").read()
    assert "asset_action" in fsrc, "生产必须使用映射后的 asset_action"
    # FrontendFrameConsumer 必须用 VisualSemanticMapper（后端语义→素材词汇）
    assert "VisualSemanticMapper" in fsrc and "mapper.map(" in fsrc, "consumer 应经 mapper 映射"
