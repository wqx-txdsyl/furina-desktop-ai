"""Phase 10: Character Runtime Contract / Backend Freeze 测试（§50）。"""
from __future__ import annotations

import time
from dataclasses import FrozenInstanceError

from furina.runtime.frame import (
    CharacterRuntimeFrame, FrameMeta, FrameActivity, FrameBody, FrameMotion,
    FrameInteraction, FrameWorldHint, FrameDebug, SCHEMA_VERSION,
    ActivityPhase, ActivityCategory, MotionIntent,
)
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.renderer_adapter import renderer_adapter
from furina.dialogue import GodCalibrationGate
from furina.core.event_bus import EventBus, EventType

# ---------------------------------------------------------------- fixture（RFC 2557 风格：contract fixture）
import json, os
_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "runtime_frame_v1.json")


def _save_fixture(d):
    os.makedirs(os.path.dirname(_FIXTURE), exist_ok=True)
    with open(_FIXTURE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- runtime_frame_schema
def test_runtime_frame_schema():
    """Frame 序列化字段齐全、schema_version 固定、可反解（fixture 用固定时间戳，contract 稳定可复现）。"""
    b = RuntimeFrameBuilder()
    f = b.build(activity_name="read", speech={"should_speak": True, "text": "在看书呢"},
                now=0.0)
    d = f.to_dict()
    assert d["meta"]["schema_version"] == "1.0"
    assert d["meta"]["character_id"] == "furina"
    assert d["meta"]["frame_id"] >= 1
    assert d["activity"]["name"] == "read"
    assert d["activity"]["category"] == "SELF"
    assert d["activity"]["phase"] in [p.value for p in ActivityPhase]
    for k in ("should_speak", "text", "dialogue_act", "length", "mode", "validation_status"):
        assert k in d["speech"]
    for k in ("expression", "gaze", "posture", "hesitation", "composure", "movement_tempo"):
        assert k in d["body"]
    # fixture 保存（contract stability）
    _save_fixture(d)
    assert os.path.exists(_FIXTURE)


def test_runtime_frame_fixture_loadable():
    """fixture 是可加载的合法 Frame dict（Schema 稳定性锚点）。"""
    assert os.path.exists(_FIXTURE)
    with open(_FIXTURE, encoding="utf-8") as f:
        d = json.load(f)
    assert d["meta"]["schema_version"] == "1.0"
    _ = CharacterRuntimeFrame.minimal()  # 构造可用


# ---------------------------------------------------------------- runtime_frame_immutable
def test_runtime_frame_immutable():
    """Frame 是 frozen（immutable snapshot），前端不可改。"""
    f = CharacterRuntimeFrame()
    try:
        f.body = FrameBody()      # type: ignore[misc]
        assert False, "不应允许改写 frame.body"
    except FrozenInstanceError:
        pass
    try:
        f.meta.frame_id = 999
        assert False, "不应允许改写 meta.frame_id"
    except FrozenInstanceError:
        pass


# ---------------------------------------------------------------- frame_builder
def test_frame_builder():
    """Builder 从各输入产出统一 Frame；body/activity/speech 汇合。"""
    b = RuntimeFrameBuilder()
    from furina.embodiment import EmbodiedExpressionEngine, FURINA_EMBODIMENT
    eng = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
    body = eng.express(emotion="proud", mode="PROUD", activity="idle")
    f = b.build(state=None, activity_name="talk", body=body,
                speech={"should_speak": True, "text": "哼，本神才不稀罕呢", "mode": "PROUD",
                        "dialogue_act": "BOAST"})
    assert f.body.expression == "proud"
    assert f.body.posture == "upright"
    assert f.speech.text == "哼，本神才不稀罕呢"
    assert f.activity.name == "talk"


# ---------------------------------------------------------------- frame_activity_body_consistency
def test_frame_activity_body_consistency():
    """activity ↔ posture 一致性：sleep 不能 upright/user-gaze。"""
    from furina.embodiment import EmbodiedExpressionEngine, FURINA_EMBODIMENT, BodyValidator
    from furina.dialogue import PersonaMode
    eng = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
    body = eng.express(emotion="proud", mode=PersonaMode.PERFORMATIVE.value, activity="sleep")
    body = BodyValidator().validate(body, activity="sleep")
    f = RuntimeFrameBuilder().build(activity_name="sleep", body=body)
    assert f.body.posture == "sleeping"
    assert f.body.gaze == "NONE"
    assert f.body.movement_amplitude < 0.3


# ---------------------------------------------------------------- frame_speech_body_consistency
def test_frame_speech_body_consistency():
    """speech ↔ body：沉默时 speech_sync=NONE（身体仍活），不出现 speech 但 body 冻结。"""
    from furina.embodiment import EmbodiedExpressionEngine, FURINA_EMBODIMENT, BodyValidator
    eng = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
    body = eng.express(emotion="calm", mode="CASUAL", activity="read", silence=True)
    body = BodyValidator().validate(body, activity="read", silence=True)
    f = RuntimeFrameBuilder().build(activity_name="read", body=body,
                                    speech={"should_speak": False, "text": "", "validation_status": "silent"})
    assert f.speech.should_speak is False
    # 身体仍有 micro（呼吸/眨眼），非冻结
    assert "BREATH" in f.body.micro_preferences or "BLINK" in f.body.micro_preferences


# ---------------------------------------------------------------- frame_away_affordance
def test_frame_away_affordance():
    """user away → interaction 不可用 + motion 不 APPROACH_USER。"""
    f = RuntimeFrameBuilder().build(activity_name="read",
                                    world={"user_present": False, "availability": 0.1,
                                           "interruption_cost": 0.9, "user_working": False})
    assert f.interaction.available is False
    assert f.interaction.response_mode == "away"
    assert f.motion.intent in (MotionIntent.NONE.value, MotionIntent.MAINTAIN.value)


def test_frame_sleep_no_user_gaze():
    """sleep → interaction.sleeping + body.gaze NONE（§38 一致性）。"""
    from furina.embodiment import EmbodiedExpressionEngine, FURINA_EMBODIMENT, BodyValidator
    from furina.dialogue import PersonaMode
    eng = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
    body = eng.express(emotion="sleepy", mode=PersonaMode.CASUAL.value, activity="sleep")
    body = BodyValidator().validate(body, activity="sleep")
    f = RuntimeFrameBuilder().build(activity_name="sleep", body=body)
    assert f.interaction.response_mode == "sleeping"
    assert f.body.gaze == "NONE"


# ---------------------------------------------------------------- legacy_renderer_adapter
def test_legacy_renderer_adapter():
    """旧 Renderer 通过 Adapter 消费 Frame：输出 pose/emotion/gaze/action。"""
    from furina.embodiment import EmbodiedExpressionEngine, FURINA_EMBODIMENT
    eng = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
    body = eng.express(emotion="proud", mode="PROUD", activity="talk")
    f = RuntimeFrameBuilder().build(activity_name="talk", body=body)
    out = renderer_adapter(f, activity="talk")
    assert out["pose"] == "standing"
    assert out["emotion"] == "neutral"
    assert out["action"] == "talk"
    assert out["micro"]


# ---------------------------------------------------------------- body_snapshot_removed_from_external_path
def test_frame_consumes_body_snapshot():
    """body_snapshot 不再是独立外部契约：frame.body 是唯一来源。"""
    from furina.embodiment import EmbodiedExpressionEngine, FURINA_EMBODIMENT
    eng = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
    body = eng.express(emotion="embarrassed", mode="GUARDED", activity="idle")
    f = RuntimeFrameBuilder().build(activity_name="idle", body=body)
    assert f.body.hesitation > 0.4        # frame.body 承载 body 语义
    assert f.body.gaze in ("SIDE", "USER", "DOWN")


# ---------------------------------------------------------------- event_to_next_frame
def test_event_to_next_frame():
    """interaction event → 下一帧（Frame A != Frame B），由后端产生而非前端改 body。"""
    bus = EventBus()
    frames = []
    bus.on(EventType.CHARACTER_FRAME_UPDATED, lambda ev: frames.append(ev.payload))
    builder = RuntimeFrameBuilder()
    fa = builder.build(activity_name="sleep", speech={"should_speak": False})
    bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=fa, source="runtime")
    # 用户摸头 → 状态变化 → 新帧
    fb = builder.build(activity_name="talk", speech={"should_speak": True, "text": "嗯？"})
    bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=fb, source="runtime")
    assert len(frames) == 2
    assert frames[0] is not frames[1]
    assert frames[0].activity.name != frames[1].activity.name


# ---------------------------------------------------------------- llm_failure_still_valid_frame
def test_llm_failure_still_valid_frame():
    """Brain 失败仍产出合法 Frame（回到无上下文活动/静默），不崩。"""
    f = CharacterRuntimeFrame.minimal()
    d = f.to_dict()
    assert d["meta"]["schema_version"] == "1.0"
    assert d["activity"]["name"] == "idle"
    assert d["speech"]["should_speak"] is False


# ---------------------------------------------------------------- dialogue_failure_silence
def test_dialogue_failure_silence():
    """dialogue fail → speech=None / should_speak=False，而不是 Frame 崩。"""
    f = RuntimeFrameBuilder().build(activity_name="rest", speech={"should_speak": False, "text": "", "validation_status": "silent"})
    assert f.speech.should_speak is False
    assert f.speech.text == ""


# ---------------------------------------------------------------- asset_missing_degrades
def test_asset_missing_degrades():
    """asset 缺失 → 记录 DEGRADED/best-available，而不是 fallback idle 丢语义。"""
    from furina.embodiment import EmbodiedExpressionEngine, FURINA_EMBODIMENT
    eng = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
    body = eng.express(emotion="excited", mode="PERFORMATIVE", activity="talk")
    f = RuntimeFrameBuilder().build(activity_name="talk", body=body)
    out = renderer_adapter(f, activity="talk", degraded={"missing": ["excited_idle"], "resolved": "neutral"})
    assert out["action"] == "talk"                 # 语义保留
    assert out["deg"]["missing"] == ["excited_idle"]  # 记录降级
    assert out["emotion"] in ("neutral", "proud", "excited")


# ---------------------------------------------------------------- frame_privacy
def test_frame_privacy():
    """Frame 不泄漏 raw window title / prompt / memory / secret。"""
    from furina.embodiment import EmbodiedExpressionEngine, FURINA_EMBODIMENT
    eng = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
    body = eng.express(emotion="calm", mode="CASUAL", activity="read")
    f = RuntimeFrameBuilder().build(activity_name="read", body=body,
                                    world={"user_working": True, "user_activity": "coding",
                                           "availability": 0.5, "interruption_cost": 0.5})
    d = f.to_dict()
    js = json.dumps(d, ensure_ascii=False)
    for secret in ("api_key", "ZHIPU", "password", "sk-", "memory", "prompt", "system"):
        assert secret not in js, f"Frame 泄漏 {secret}"
    assert "user_activity" in d["world_hint"]   # 只含语义
    assert "coding" == d["world_hint"]["user_activity"]


# ---------------------------------------------------------------- frame_id_monotonic
def test_frame_id_monotonic():
    """frame_id 单调递增。"""
    b = RuntimeFrameBuilder()
    ids = [b.build().meta.frame_id for _ in range(5)]
    assert all(ids[i] < ids[i + 1] for i in range(len(ids) - 1))


# ---------------------------------------------------------------- god_self_reference_context_gate
def test_god_self_reference_context_gate():
    """'本神' 语境闸门：preferred（PROUD/BOAST）允许，suppressed（SINCERE）抑制，不强制。"""
    g = GodCalibrationGate()
    assert g.calibrate(mode="PROUD", dialogue_act="BOAST").context == "preferred"
    assert g.calibrate(mode="PLAYFUL", dialogue_act="TEASE").context == "preferred"
    assert g.calibrate(mode="SINCERE", dialogue_act="ADMIT").context == "suppressed"
    assert g.calibrate(mode="RESPONSIBLE").context == "suppressed"
    assert g.calibrate(mode="CASUAL", dialogue_act="COMMENT").context == "neutral"


# ---------------------------------------------------------------- god_self_reference_cooldown
def test_god_self_reference_cooldown():
    """cooldown：连续'本神'被拦截；冷却后再出现则放行。"""
    g = GodCalibrationGate(cooldown_seconds=20.0)
    cal = g.calibrate(mode="PROUD", dialogue_act="BOAST")
    t0 = time.monotonic()
    r1 = g.gate_output("本神登场！", cal=cal, now=t0)
    assert r1 == "本神登场！"          # 首次放行
    r2 = g.gate_output("本神再来一次！", cal=cal, now=t0 + 1)   # 1s 后又在冷却
    assert r2 is None                 # 冷却拦截
    r3 = g.gate_output("本神又来了！", cal=cal, now=t0 + 30)    # 30s 后冷却结束
    assert r3 == "本神又来了！"        # 放行


def test_god_suppressed_never_forced():
    """suppressed 情境出现'本神'→ 软拦截；不强制改文本、不塞关键词。"""
    g = GodCalibrationGate()
    cal = g.calibrate(mode="SINCERE", dialogue_act="ADMIT")
    assert g.gate_output("对不起，本神失态了。", cal=cal) is None
    # preferred 不强制：即使语境 preferred，也允许模型选择不用本神
    pref = g.calibrate(mode="PROUD", dialogue_act="BOAST")
    assert g.prompt_advice(pref).count("本神") >= 1   # 只是引导
    assert "force" not in g.prompt_advice(pref).lower()
