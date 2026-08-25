"""Phase 13 Runtime Evidence Blocker Repair R2.1（基线 9b075a6）。

P0-1 speech event identity（同文本不同 turn 各显示一次）/ P0-2 harness direct telemetry /
P0-3 validator severity（soft 不失败）/ P1-1 当前事实>记忆 / P1-2 interaction grounding /
P1-3 plan 记忆 + follow-up / P1-4 agent 结果绑定报告 / P1-5 用户格式约束 /
P1-6 persona surface 机制 / P2 harness conversation 事件身份。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from types import SimpleNamespace

import pytest

# RuntimeHarness 会创建 QWidget（proxy）→ 必须先有 QApplication（offscreen 单例）
from PySide6.QtWidgets import QApplication
_QAPP = QApplication.instance() or QApplication([])

from furina.core import EventBus, EventType
from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.dialogue.validator import DialogueValidator
from furina.dialogue_brain import DialogueBrain
from furina.runtime.dialogue_snapshot import DialogueContextSnapshot
from furina.runtime.dialogue_queue import DirectDialogueQueue

_v = DialogueValidator()


def _snap(text, channel="DIRECT_USER_TURN"):
    return DialogueContextSnapshot(user_text=text, channel=channel, user_initiated=True)


class _SeqLLM:
    def __init__(self, speeches):
        self._s = list(speeches)
        self.calls = 0

    def is_available(self):
        return True

    def structured(self, msgs, schema=None, temperature=0.9):
        self.calls += 1
        return {"speech": self._s.pop(0) if self._s else ""}


def _brain(seq):
    return DialogueBrain(_SeqLLM(seq), persona="你是芙宁娜。")


# ================================================================ P0-1 speech event identity
def test_p0_1_say_increments_speech_id_same_text_distinct_events():
    """P0-1：同一文本的两次 _say 是不同 speech event（speech_id 递增）。"""
    from furina.runtime.scheduler import Scheduler
    from furina.state.state_engine import StateEngine
    bus = EventBus()
    sched = Scheduler(bus, StateEngine(bus), None, None, None, None, None)
    sched._say("（系统状态：刚才的回复生成失败。）", dur=4.0)
    id1 = sched._speech_seq
    sched._say("（系统状态：刚才的回复生成失败。）", dur=4.0)
    id2 = sched._speech_seq
    assert id2 > id1, "不同 utterance（同文本）必须不同 speech_id"


def _fake_harness():
    from furina.runtime.harness.controller import RuntimeHarness
    from furina.runtime.frame import FrameSpeech, CharacterRuntimeFrame, FrameActivity
    from furina.runtime.world import DesktopWorld
    app = SimpleNamespace(bus=EventBus(), state=None, relationship=SimpleNamespace(state=None),
                          memory=SimpleNamespace(store=SimpleNamespace(query=lambda *a, **k: [])),
                          _sched=SimpleNamespace(current_frame=lambda: None), _spatial=None,
                          life_brain=None, dialogue_brain=None, agent=None, _direct_dq=None,
                          world=DesktopWorld(1920, 1080))
    h = RuntimeHarness(app)
    h.recorder.clear()
    return h, FrameSpeech, CharacterRuntimeFrame, FrameActivity


def test_p0_1_frame_dedupe_by_speech_id_not_text():
    """P0-1：同文本不同 speech_id 的 frame 各显示一次；同 id 重复 tick 只显示一次。"""
    h, FS, CRF, FA = _fake_harness()
    txt = "（系统状态：刚才的回复生成失败。）"
    f1 = CRF(activity=FA(name="talk"), speech=FS(should_speak=True, text=txt, speech_id=1))
    f1b = CRF(activity=FA(name="talk"), speech=FS(should_speak=True, text=txt, speech_id=1))
    f2 = CRF(activity=FA(name="talk"), speech=FS(should_speak=True, text=txt, speech_id=2))
    h._on_frame(SimpleNamespace(payload=f1))
    h._on_frame(SimpleNamespace(payload=f1b))   # 同一 utterance 重复 tick → dedupe
    h._on_frame(SimpleNamespace(payload=f2))    # 不同 utterance 同文本 → 必须显示
    furina = [u for u in h.utterances if u["role"] == "Furina"]
    assert len(furina) == 2, f"同文本不同 turn 必须各显示一次: {furina}"


def test_p0_1_five_failed_turns_same_system_status_all_observable():
    """P0-1 HARD：5 个连续 FAILED direct turn，同 SYSTEM_STATUS 文本 → 5 个可观察 failure。"""
    brain = _brain(["（叹气）好吧"] * 10)   # stage_direction HARD → 每 turn 双失败
    bus = EventBus()
    phases = []
    bus.on(EventType.DIRECT_TURN_TRACE, lambda ev: phases.append(ev.payload.get("phase")))
    q = DirectDialogueQueue(bus=bus, timeout=5.0, keep_outcomes=20)

    def proc(turn, snap):
        res = brain.say_with_result(**snap.say_kwargs(), deadline=turn.deadline)
        return {"speech": res.get("speech"), "failure_reason": res.get("failure_reason"),
                "validation_issues": res.get("validation_issues", []),
                "hard_issues": res.get("hard_issues", []), "soft_issues": res.get("soft_issues", [])}

    q.set_processor(proc)
    for i in range(5):
        q.submit(_snap(f"m{i}"), user_text=f"m{i}")
    assert q.wait_idle(timeout=8.0)
    assert phases.count("FAILED") == 5, f"5 个 DirectTurn 必须全部 FAILED: {phases}"
    assert q.pending() == 0
    outs = q.recent_outcomes(10)
    assert all(o["status"] == "FAILED" and o["failure_reason"] == "validation_twice_invalid" for o in outs)
    assert all(o["hard_issues"] == ["stage_direction"] for o in outs), outs
    # 每个 FAILED turn 都是独立 DirectTurn（同 failure 文本但不同事件身份）
    assert len({o["turn_id"] for o in outs}) == 5


# ================================================================ P0-2 harness telemetry
def _app_with_queue(brain):
    from furina.app import Furina
    from furina.runtime.world import DesktopWorld
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.emotion = EmotionEngine(app.state.state.emotion)
    app.relationship = SimpleNamespace(apply=lambda *a, **k: None, factors=lambda: {})
    app.memory = SimpleNamespace(observe=lambda *a, **k: None, retrieve=lambda **k: [],
                                 interpret=lambda *a, **k: {},
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    app.bus = EventBus()
    app._sched = SimpleNamespace(interrupt_life=lambda r: None, on_user_response=lambda: None,
                                 _say=lambda t, dur=4.0, channel="", turn_id=None: None)
    app.dialogue_brain = brain
    app._fallback_dispatcher = None
    app._rt_dispatcher().bind_owner()
    app.world = DesktopWorld(1920, 1080)
    return app


def test_p0_2_badge_sequence_from_direct_lifecycle():
    """P0-2 HARD：direct success → validation failure → success → badge LAST_OK/LAST_FAILED/LAST_OK。"""
    from furina.runtime.harness.controller import RuntimeHarness
    app = _app_with_queue(_brain(["嗯，我在呢。"]))
    h = RuntimeHarness(app)
    bus = app.bus
    # 用真实 DIRECT_TURN_TRACE 相位序列驱动 badge（同 harness 订阅路径）
    def trace(phase, tid=1, seq=1, reason="", lat=1.0):
        bus.emit(EventType.DIRECT_TURN_TRACE, payload={"turn_id": tid, "ingress_seq": seq,
                                                       "channel": "DIRECT_USER_TURN", "phase": phase,
                                                       "status": phase, "latency_ms": lat,
                                                       "failure_reason": reason, "user_text": "x"},
                 source="test")
    trace("DIRECT_INGRESS"); trace("GENERATION_STARTED"); trace("REPLIED")
    assert h.dialogue_badge() == "LAST_OK"
    trace("DIRECT_INGRESS", tid=2, seq=2); trace("GENERATION_STARTED", tid=2, seq=2)
    trace("FAILED", tid=2, seq=2, reason="validation_twice_invalid")
    assert h.dialogue_badge() == "LAST_FAILED", "direct FAILED 后 badge 必须 LAST_FAILED"
    trace("DIRECT_INGRESS", tid=3, seq=3); trace("GENERATION_STARTED", tid=3, seq=3)
    trace("REPLIED", tid=3, seq=3)
    assert h.dialogue_badge() == "LAST_OK"
    # ambient（旧路径 outcome）不得覆盖 direct last outcome
    h._dialog_last["outcome"] = "SPOKE"   # 模拟 ambient SPOKE
    assert h.dialogue_badge() == "LAST_OK"
    # trace 每个 direct turn 含 ingress/generation/result/terminal
    stages = {t.stage for t in h.recorder.recent(50)}
    assert {"DIRECT_DIRECT_INGRESS", "DIRECT_GENERATION_STARTED", "DIRECT_REPLIED",
            "DIRECT_FAILED"}.issubset(stages), stages


def test_p0_2_production_queue_drives_badge():
    """P0-2 集成：真实 DirectDialogueQueue 终态 → harness badge。"""
    from furina.runtime.harness.controller import RuntimeHarness
    app = _app_with_queue(_brain(["嗯，我在呢。", "（叹气）好吧", "（叹气）好吧", "嗯，我来了。"]))
    h = RuntimeHarness(app)
    app.submit_user_message("第一条")
    dq = app._direct_dialogue_queue()
    assert dq.wait_idle(timeout=8.0)
    app._rt_dispatcher().drain()
    assert h.dialogue_badge() == "LAST_OK"
    app.submit_user_message("第二条")      # 双失败（hard）
    assert dq.wait_idle(timeout=8.0)
    app._rt_dispatcher().drain()
    assert h.dialogue_badge() == "LAST_FAILED", "真实 lifecycle FAILED 后 badge 必须 LAST_FAILED"


# ================================================================ P0-3 severity
def test_p0_3_soft_only_surfaces_not_failed():
    """P0-3：attempt/retry 都只有 SOFT（generic_assistant_voice）→ surface + soft_issues，不 FAILED。"""
    brain = _brain(["有什么可以帮你吗？", "随时为您服务。"])   # 两个都是 generic_assistant_voice（SOFT）
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="在吗",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] is not None, "仅 SOFT 不得失败（一句话不够漂亮不得变系统错误）"
    assert res["failure_reason"] == ""
    assert res["soft_issues"], f"必须记录 soft_quality_issues: {res}"
    assert all(i not in res["hard_issues"] for i in res["soft_issues"])


def test_p0_3_soft_retry_to_valid_surfaces_retry():
    brain = _brain(["有什么可以帮你吗？", "嗯，我在呢。"])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="在吗",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] == "嗯，我在呢。"


def test_p0_3_hard_still_fails_with_issues():
    brain = _brain(["作为AI，我可以帮助你完成任务。", "作为AI，我可以帮助你完成任务。"])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="在吗",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] is None
    assert res["failure_reason"] == "validation_twice_invalid"
    assert "generic_assistant_identity" in res["hard_issues"], res


def test_p0_3_validator_severity_classification():
    r = _v.validate("有什么可以帮你吗？", should_speak=True)          # SOFT
    assert "generic_assistant_voice" in r.soft_issues and not r.hard_issues
    r2 = _v.validate("作为AI，我可以帮助你完成任务。", should_speak=True)  # HARD
    assert "generic_assistant_identity" in r2.hard_issues
    r3 = _v.validate("嗯，我在呢。", should_speak=True)
    assert r3.valid and not r3.hard_issues and not r3.soft_issues


# ================================================================ P1-1 当前事实 > 记忆
def test_p1_1_work_claim_during_talk_hard_invalid():
    """P1-1 HARD：current_activity=talk + 过去记忆（帮用户整理）+ “我现在正在整理测试目录”→ HARD invalid。"""
    r = _v.validate("我现在正在整理测试目录", should_speak=True, activity="talk")
    assert not r.valid
    assert "ungrounded_activity" in r.hard_issues, r


def test_p1_1_work_claim_during_agent_work_valid():
    """P1-1：activity=agent_work 时工作声称一致 → 合法。"""
    r = _v.validate("我正在整理测试目录", should_speak=True, activity="agent_work")
    assert r.valid, r.issues


def test_p1_1_past_memory_not_current_truth_in_prompt():
    """P1-1：prompt 必须显式 CURRENT_FACTS vs PAST_MEMORY（过去≠正在发生）。"""
    from furina.dialogue_brain import _dialogue_prompt_v2
    class _App:
        def to_prompt(self):
            return {"mode": "CASUAL", "secondary_mode": "", "dialogue_act": "COMMENT", "strategy": ""}
        mode = "CASUAL"; dialogue_act = "COMMENT"
    p = _dialogue_prompt_v2(_App(), intent="talk", emotion="calm", user_text="你在干嘛？",
                            context="", memories=["我帮用户整理测试目录"],
                            world=None, examples=[], person="p",
                            activity="talk", agent_state="IDLE", agent_task="")
    assert "CURRENT_FACTS" in p and "PAST_MEMORY" in p
    assert "过去" in p and "不得说成" in p


def test_p1_1_agent_facts_in_direct_snapshot():
    """P1-1：direct 快照携带 agent_state/agent_task（CURRENT_FACTS 权威）。"""
    from furina.app import Furina
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.agent = SimpleNamespace(status="COMPLETED_VERIFIED", current_task="")
    app.memory = SimpleNamespace(retrieve=lambda **k: [], interpret=lambda *a, **k: {})
    app.relationship = SimpleNamespace(factors=lambda: {})
    app._sched = None
    snap = app._freeze_direct_snapshot("在吗")
    assert snap.agent_state == "COMPLETED_VERIFIED"
    assert snap.agent_task == ""


# ================================================================ P1-2 interaction grounding
def test_p1_2_petting_attack_claim_hard_invalid():
    """P1-2 HARD：petting（正面触碰）回复声称被偷袭/被戳 → interaction_contradiction。"""
    r = _v.validate("你竟然敢偷袭我！", should_speak=True, interaction="petting")
    assert not r.valid
    assert "interaction_contradiction" in r.hard_issues, r


def test_p1_2_poke_may_express_poked():
    """P1-2：poke 可表达被戳。"""
    r = _v.validate("哎呀，你戳我干嘛？", should_speak=True, interaction="poke")
    assert r.valid, r.issues


def test_p1_2_petting_positive_reply_valid():
    r = _v.validate("嗯，感觉好舒服呢。", should_speak=True, interaction="petting")
    assert r.valid, r.issues


def test_p1_2_reaction_snapshot_carries_interaction_fact():
    """P1-2：互动反应快照携带 interaction kind（进入 prompt FACT）。"""
    from furina.runtime.scheduler import Scheduler
    from furina.state.state_engine import StateEngine
    bus = EventBus()
    sched = Scheduler(bus, StateEngine(bus), None, None, None, None, None)
    sched.me = SimpleNamespace(retrieve=lambda *a, **k: [])
    sched.relationship = None
    sched.world_perc = SimpleNamespace(factors=lambda: {})
    snap = sched._freeze_reaction_snapshot(intent="head_touch", emotion="happy",
                                           user_initiated=True, context="你轻轻摸了摸我的头",
                                           activity="head_touch", interaction="petting")
    assert snap.interaction == "petting"


# ================================================================ P1-3 plan 记忆 + follow-up
def test_p1_3_plan_and_followup_memory_retrieval():
    """P1-3 HARD：今天准备…+做完以后… → 检索返回对应事实。"""
    import tempfile
    from pathlib import Path
    from furina.memory import MemoryEngine, MemoryStore
    from furina.app import Furina
    d = Path(tempfile.mkdtemp())
    bus = EventBus()
    app = object.__new__(Furina)
    app.memory = MemoryEngine(bus, MemoryStore(d / "t.db"))
    app._maybe_observe_conversation("我今天准备完成桌宠的功能测试。")
    app._maybe_observe_conversation("做完以后应该能轻松一点。")
    got1 = app.memory.retrieve(query="今天准备做什么？", limit=4)
    got2 = app.memory.retrieve(query="做完以后会怎么样？", limit=4)
    assert any("完成桌宠的功能测试" in m.content for m in got1), \
        [m.content for m in got1]
    assert any("应该能轻松一点" in m.content for m in got2), \
        [m.content for m in got2]


# ================================================================ P1-4 agent 结果绑定报告
def test_p1_4_agent_done_context_contains_result_facts():
    """P1-4：AGENT_COMPLETED → 报告 context 含 request/完成/goal/验证（notepad 语义）。"""
    from furina.runtime.scheduler import Scheduler
    from furina.state.state_engine import StateEngine
    bus = EventBus()
    sched = Scheduler(bus, StateEngine(bus), None, None, None, None, None)
    captured = {}
    class _DB:
        def say(self, **kw):
            captured["kw"] = kw
            return "报告"
    sched.dialogue_brain = _DB()
    sched.emotion = EmotionEngine(sched.se.state.emotion)
    sched.relationship = None
    sched.me = SimpleNamespace(retrieve=lambda *a, **k: [])
    sched.world_perc = SimpleNamespace(factors=lambda: {})
    sched._agent_last_request = "打开记事本"
    sched._on_agent_done(SimpleNamespace(payload={
        "goal": "打开记事本", "verified": True,
        "summary": "完成了 1/1 个步骤：打开记事本（已验证 1 步）",
        "results": [{"ok": True, "verified": True, "data": "notepad.exe RUNNING"}]}))
    ctx = captured["kw"].get("context", "")
    assert "打开记事本" in ctx and "完成" in ctx, ctx
    assert "验证通过" in ctx, ctx
    assert "notepad.exe" in ctx, "必须包含 concrete evidence"


def test_p1_4_agent_done_fallback_exactly_once():
    """P1-4：角色报告未出话 → 确定性事实回退（exactly-once 用户可见）。"""
    from furina.runtime.scheduler import Scheduler
    from furina.state.state_engine import StateEngine
    bus = EventBus()
    sched = Scheduler(bus, StateEngine(bus), None, None, None, None, None)
    sched.dialogue_brain = None          # 无 DialogueBrain → fallback 直接落地
    sched._agent_last_request = "打开记事本"
    sched._on_agent_done(SimpleNamespace(payload={
        "goal": "打开记事本", "verified": True, "summary": "完成了 1/1 个步骤",
        "results": []}))
    assert "任务已完成" in sched._speech and "打开记事本" in sched._speech, sched._speech


# ================================================================ P1-5 用户格式约束
def test_p1_5_constraint_deterministic_extraction():
    """P1-5：'只能回答会或者不会。' → 输出 ∈ {会, 不会}，无额外解释。"""
    brain = _brain(["当然会啦，我会一直陪着你的。"])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="只能回答会或者不会。",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] in ("会", "不会"), f"必须确定性提取选项: {res['speech']!r}"
    assert res["failure_reason"] == ""


def test_p1_5_constraint_not_in_output_retries_then_extracts():
    brain = _brain(["嗯嗯好的没问题", "肯定不会忘记你的啦"])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="只能回答会或者不会。",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] == "不会", res


def test_p1_5_validator_constraint_hard():
    r = _v.validate("我会的，别担心。", should_speak=True, constraint=("会", "不会"))
    assert not r.valid
    assert "explicit_user_constraint_violation" in r.hard_issues


# ================================================================ P1-6 persona surface 机制
def test_p1_6_surface_tracking_across_all_channels():
    """P1-6：recent surfaced 跨 direct/interaction/feed/agent 全通道跟踪。"""
    brain = _brain(["嗯，我在呢。"] * 8)   # 足够 retry 燃料（soft recent_repetition 每次耗 2）
    brain.say_with_result(channel="DIRECT_USER_TURN", user_text="一", user_initiated=True, ingress_seq=1)
    brain.say_with_result(channel="INTERACTION_REACTION", user_initiated=True,
                          intent="head_touch", context="摸头")
    brain.say_with_result(channel="FEED_REACTION", user_initiated=True, intent="eat", context="喂食")
    brain.say_with_result(channel="AGENT_REPORT", user_initiated=True, intent="assist_user",
                          context="报告", activity="agent_report")
    assert len(brain._recent_surfaced) == 4, \
        f"全通道 surfaced 跟踪: {brain._recent_surfaced}"


def test_p1_6_exact_recent_repetition_flagged():
    """P1-6：近期逐字重复（P21 重复 P19）→ recent_repetition（soft）。"""
    recent = ["我最大的缺点是完美主义"]
    r = _v.validate("我最大的缺点是完美主义", should_speak=True, recent_surface=recent)
    assert "recent_repetition" in r.soft_issues, r


def test_p1_6_generic_self_analysis_soft():
    """P1-6：generic interview self-analysis（乐观/倾听/完美主义模板）→ soft issue。"""
    r = _v.validate("我最大的优点就是能够保持一颗乐观的心态，而且喜欢与人交流。",
                    should_speak=True)
    assert "generic_self_analysis" in r.soft_issues, r
    assert not r.hard_issues, "风格缺陷不可是 HARD"


def test_p1_6_soft_does_not_kill_serious_comfort_reply():
    """P1-6：serious/comfort 场景，soft 风格缺陷不得把回复杀掉（surface）。"""
    brain = _brain(["哎呀哎呀哎呀，别难过，我会陪着你的。", "别难过，我在呢。"])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="我担心自己做的没人喜欢。",
                                user_initiated=True, ingress_seq=1, activity="comfort")
    assert res["speech"] is not None, "soft 缺陷不得杀掉 serious 回应"


# ================================================================ P2 harness conversation identity
def test_p2_harness_utterances_structured():
    """P2：conversation 存储保留 turn_id/channel/speech_id/text/terminal status。"""
    from furina.runtime.harness.controller import RuntimeHarness
    from furina.runtime.frame import FrameSpeech, CharacterRuntimeFrame, FrameActivity
    from furina.runtime.world import DesktopWorld
    app = SimpleNamespace(bus=EventBus(), state=None, relationship=SimpleNamespace(state=None),
                          memory=SimpleNamespace(store=SimpleNamespace(query=lambda *a, **k: [])),
                          _sched=SimpleNamespace(current_frame=lambda: None), _spatial=None,
                          life_brain=None, dialogue_brain=None, agent=None, _direct_dq=None,
                          world=DesktopWorld(1920, 1080))
    h = RuntimeHarness(app)
    # DIRECT_INGRESS → user utterance（turn_id/channel）
    app.bus.emit(EventType.DIRECT_TURN_TRACE, payload={
        "turn_id": 7, "ingress_seq": 7, "channel": "DIRECT_USER_TURN",
        "phase": "DIRECT_INGRESS", "status": "QUEUED", "latency_ms": 0.0,
        "failure_reason": "", "user_text": "在吗"}, source="test")
    # 终态 → terminal_status 更新
    app.bus.emit(EventType.DIRECT_TURN_TRACE, payload={
        "turn_id": 7, "ingress_seq": 7, "channel": "DIRECT_USER_TURN",
        "phase": "REPLIED", "status": "REPLIED", "latency_ms": 100.0,
        "failure_reason": "", "user_text": "在吗"}, source="test")
    # frame speech → Furina utterance（speech_id）
    f = CharacterRuntimeFrame(activity=FrameActivity(name="talk"),
                              speech=FrameSpeech(should_speak=True, text="嗯，我在呢。", speech_id=3))
    h._on_frame(SimpleNamespace(payload=f))
    you = [u for u in h.utterances if u["role"] == "You"]
    fur = [u for u in h.utterances if u["role"] == "Furina"]
    assert you and you[0]["turn_id"] == 7 and you[0]["channel"] == "DIRECT_USER_TURN"
    assert you[0]["terminal_status"] == "REPLIED", you
    assert fur and fur[0]["speech_id"] == 3 and fur[0]["text"] == "嗯，我在呢。", fur
