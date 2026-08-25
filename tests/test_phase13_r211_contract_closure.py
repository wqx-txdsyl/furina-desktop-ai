"""Phase 13 Runtime Evidence Blocker Repair R2.1.1 FINAL Contract Closure（基线 218ddc6）。

① P0 HARD 候选永不 surface / ② example_copy=SOFT / ③ god gate 不杀 direct 可用性 /
④ 真实可见 speech-event 投递（SPEECH_SURFACED）/ ⑤ Furina utterance 绑定 DirectTurn /
⑥ badge active state / ⑦ validation telemetry 进 DIRECT_TURN_TRACE /
⑧ severity invariant / ⑨ Agent success 用 AGENT_REPORT。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from types import SimpleNamespace

import pytest

from PySide6.QtWidgets import QApplication
_QAPP = QApplication.instance() or QApplication([])

from furina.core import EventBus, EventType
from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.dialogue.validator import DialogueValidator
from furina.dialogue_brain import DialogueBrain
from furina.runtime.dialogue_snapshot import DialogueContextSnapshot
from furina.runtime.dialogue_queue import DirectDialogueQueue
from furina.runtime.world import DesktopWorld

_v = DialogueValidator()


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


def _snap(text, channel="DIRECT_USER_TURN"):
    return DialogueContextSnapshot(user_text=text, channel=channel, user_initiated=True)


# ================================================================ ① P0 HARD 候选永不 surface
def test_p0_1_hard_attempt_soft_retry_surfaces_retry_not_attempt():
    """①：attempt=HARD+0soft（AI身份）、retry=0hard+1soft（客服腔）→ 必须 surface retry。

    HARD invariant：任何被 surface 的 speech，hard_issues MUST == []。
    """
    brain = _brain(["作为AI，我可以帮助你完成任务。", "有什么可以帮你吗？"])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="在吗",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] is not None
    assert res["speech"] == "有什么可以帮你吗？", \
        f"必须 surface retry（soft），绝不 surface HARD attempt: {res['speech']!r}"
    assert "作为AI" not in res["speech"]
    assert res["failure_reason"] == ""
    assert res["hard_issues"] == [], f"surface 的 speech hard_issues MUST == []: {res['hard_issues']}"
    assert "generic_assistant_voice" in res["soft_issues"], res


def test_p0_1_soft_both_sides_choose_fewer_soft():
    """①B：双方 hard==0 才按 soft 数量选更优。"""
    brain = _brain(["有什么可以帮你吗？", "嗯，我在呢。"])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="在吗",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] == "嗯，我在呢。"     # retry 0 soft < attempt 1 soft
    assert res["hard_issues"] == []


def test_p0_1_both_hard_fails():
    brain = _brain(["作为AI，我可以帮助你完成任务。", "作为AI，我可以帮助你完成任务。"])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="在吗",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] is None and res["failure_reason"] == "validation_twice_invalid"


# ================================================================ ② example_copy = SOFT
def test_p0_2_example_copy_soft_not_hard():
    """②：example_copy 必须 SOFT（不在 _HARD_ISSUES）。"""
    from furina.persona.expression_examples import get_examples
    ex = get_examples()[0]["speech"]
    r = _v.validate(ex, should_speak=True, example_phrases=[ex])
    assert "example_copy" in r.soft_issues and "example_copy" not in r.hard_issues, r


def test_p0_2_example_copy_surfaces_not_failed():
    """②：example-copy attempt+retry → Direct reply 保持 surface，soft_issues 含 example_copy。"""
    from furina.persona.expression_examples import get_examples
    ex = get_examples()[0]["speech"]
    brain = _brain([ex, ex])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="在吗",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] is not None, "example_copy(SOFT) 不得 FAILED"
    assert res["failure_reason"] == ""
    assert "example_copy" in res["soft_issues"], res
    assert res["hard_issues"] == []


# ================================================================ ③ god gate 不杀 direct
def test_p0_3_god_gate_direct_not_failed():
    """③：sincere/serious direct 回复含单次“本神” → 不得 FAILED/god_gate_suppressed。"""
    brain = _brain(["别难过，本神在呢。"])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="我有点难过",
                                user_initiated=True, ingress_seq=1, activity="comfort")
    assert res["speech"] is not None, "direct 不得因 god style 失败"
    assert res["failure_reason"] != "god_gate_suppressed", res
    assert "本神" not in res["speech"], "抑制时应确定性移除（替换为'我'）"
    assert "god_reference_suppressed" in res["soft_issues"], res


def test_p0_3_ambient_keeps_suppression():
    """③：ambient lane 保留 suppression 语义（god_gate_suppressed 仍可返回 None）。"""
    brain = _brain(["别难过，本神在呢。"])
    res = brain.say_with_result(channel="AMBIENT_AUTONOMOUS", user_initiated=False,
                                intent="comfort", context="自主", activity="comfort")
    assert res["speech"] is None
    assert res["failure_reason"] == "god_gate_suppressed", res


# ================================================================ ④+⑤ SPEECH_SURFACED 集成
def _full_chain_app(brain):
    """真实 App/Scheduler/Harness 链（submit_user_message → queue → brain → SYSTEM_STATUS/
    BRAIN_SPOKE → scheduler._say → SPEECH_SURFACED → harness utterances）。"""
    from furina.app import Furina
    from furina.runtime.scheduler import Scheduler
    from furina.state.state_engine import StateEngine
    app = object.__new__(Furina)
    bus = EventBus()
    app.bus = bus
    app.state = SimpleNamespace(state=CharacterState())
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, DesktopWorld(1920, 1080), None)
    sched.emotion = EmotionEngine(se.state.emotion)
    sched.be = SimpleNamespace(step=lambda s: None)
    sched.director = SimpleNamespace(drain=lambda: None, submit=lambda r: None, finish=lambda **k: None)
    app._sched = sched
    app.emotion = sched.emotion
    app.relationship = SimpleNamespace(apply=lambda *a, **k: None, factors=lambda: {})
    app.memory = SimpleNamespace(observe=lambda *a, **k: None, retrieve=lambda **k: [],
                                 interpret=lambda *a, **k: {},
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    app.dialogue_brain = brain
    app._fallback_dispatcher = None
    app.agent = SimpleNamespace(status="IDLE", current_task="")
    app.world = DesktopWorld(1920, 1080)
    app._rt_dispatcher().bind_owner()
    return app


def test_p0_4_integration_five_failed_turns_identical_status_visible():
    """④ HARD INTEGRATION：真实链 5 个全 FAILED DirectTurn 同 SYSTEM_STATUS → 5 个可见。"""
    from furina.runtime.harness.controller import RuntimeHarness
    brain = _brain(["（叹气）好吧"] * 10)      # stage_direction HARD → 每 turn 双失败
    app = _full_chain_app(brain)
    h = RuntimeHarness(app)
    for i in range(5):
        app.submit_user_message(f"m{i}")
    dq = app._direct_dialogue_queue()
    assert dq.wait_idle(timeout=10.0)
    app._rt_dispatcher().drain()
    # ① terminal=5, pending=0
    outs = dq.recent_outcomes(10)
    assert len(outs) == 5 and all(o["status"] == "FAILED" for o in outs)
    assert dq.pending() == 0
    # ④ visible utterance = 5（SPEECH_SURFACED 事件，同文本不丢）
    furina = [u for u in h.utterances if u["role"] == "Furina"
              and "系统状态" in u["text"]]
    assert len(furina) == 5, f"5 个相同 SYSTEM_STATUS 必须各可见一次: {len(furina)}"
    # ⑤ 每个 turn_id 恰一个可见终态（结构化绑定，不按数组位置猜）
    for tid in range(1, 6):
        mine = [u for u in furina if u.get("turn_id") == tid]
        assert len(mine) == 1, f"turn#{tid} 必须恰一个可见终态: {mine}"
        assert mine[0]["channel"] == "DIRECT_USER_TURN"
        assert mine[0]["terminal_status"] == "FAILED", mine
    # panel/chat 队列可见 outcome = 5
    drained = h.drain_chat()
    assert sum(1 for r, _ in drained if r == "Furina" and "系统状态" in _) == 5, \
        [t for _, t in drained]


def test_p0_4_two_identical_normal_replies_both_visible():
    """④：两个不同 direct turn 生成完全相同正常回复 → visible reply count = 2。"""
    from furina.runtime.harness.controller import RuntimeHarness
    brain = _brain(["嗯，我在呢。", "嗯，我在呢。"])
    app = _full_chain_app(brain)
    h = RuntimeHarness(app)
    app.submit_user_message("一")
    app.submit_user_message("二")
    dq = app._direct_dialogue_queue()
    assert dq.wait_idle(timeout=10.0)
    app._rt_dispatcher().drain()
    furina = [u for u in h.utterances if u["role"] == "Furina" and u["text"] == "嗯，我在呢。"]
    assert len(furina) == 2, f"同文本正常回复必须各显示一次: {len(furina)}"
    assert {u.get("turn_id") for u in furina} == {1, 2}
    assert all(u["terminal_status"] == "REPLIED" for u in furina)
    assert len({u["speech_id"] for u in furina}) == 2, "两个不同 speech event"


# ================================================================ ⑥ badge active state
def test_p0_2_badge_active_states():
    """⑥：QUEUED→RUNNING/PENDING、GENERATING→RUNNING/PENDING、REPLIED→LAST_OK；
    previous LAST_OK + 新 turn QUEUED → 不得继续 LAST_OK。"""
    from furina.runtime.harness.controller import RuntimeHarness
    app = SimpleNamespace(bus=EventBus(), state=None, relationship=SimpleNamespace(state=None),
                          memory=SimpleNamespace(store=SimpleNamespace(query=lambda *a, **k: [])),
                          _sched=SimpleNamespace(current_frame=lambda: None), _spatial=None,
                          life_brain=None, dialogue_brain=None, agent=None, _direct_dq=None,
                          world=DesktopWorld(1920, 1080))
    h = RuntimeHarness(app)
    bus = app.bus

    def tr(phase, tid=1, seq=1):
        bus.emit(EventType.DIRECT_TURN_TRACE, payload={
            "turn_id": tid, "ingress_seq": seq, "channel": "DIRECT_USER_TURN",
            "phase": phase, "status": phase, "latency_ms": 1.0, "failure_reason": "",
            "user_text": "x"}, source="test")

    tr("DIRECT_INGRESS")
    assert h.dialogue_badge() == "RUNNING/PENDING", "QUEUED → RUNNING/PENDING"
    tr("GENERATION_STARTED")
    assert h.dialogue_badge() == "RUNNING/PENDING", "GENERATING → RUNNING/PENDING"
    tr("REPLIED")
    assert h.dialogue_badge() == "LAST_OK"
    # 新 turn 入队 → 不得停留在旧 LAST_OK
    tr("DIRECT_INGRESS", tid=2, seq=2)
    assert h.dialogue_badge() == "RUNNING/PENDING", "新 turn QUEUED 后不得继续 LAST_OK"


# ================================================================ ⑦ validation telemetry
def test_p0_3_telemetry_in_direct_turn_trace():
    """⑦：soft-surfaced REPLIED soft_issues!=[]、hard-failed FAILED hard_issues!=[]，
    均从 EventBus DIRECT_TURN_TRACE 直读（不依赖 private recent_outcomes）。"""
    bus = EventBus()
    terminal_payloads = []
    bus.on(EventType.DIRECT_TURN_TRACE, lambda ev: terminal_payloads.append(ev.payload)
           if ev.payload.get("phase") in ("REPLIED", "FAILED", "CANCELLED") else None)
    # soft-surfaced（attempt+retry 都只有 SOFT → surface 时 soft_issues 非空）
    brain = _brain(["有什么可以帮你吗？", "随时为您服务。"])
    q = DirectDialogueQueue(bus=bus, timeout=5.0)
    q.set_processor(lambda turn, snap: (
        lambda res: {"speech": res.get("speech"), "failure_reason": res.get("failure_reason"),
                     "validation_issues": res.get("validation_issues", []),
                     "hard_issues": res.get("hard_issues", []),
                     "soft_issues": res.get("soft_issues", [])})(
            brain.say_with_result(**snap.say_kwargs(), deadline=turn.deadline)))
    q.submit(_snap("在吗"), user_text="在吗")
    assert q.wait_idle(timeout=8.0)
    soft = [p for p in terminal_payloads if p["phase"] == "REPLIED"]
    assert soft and soft[0]["soft_issues"], f"soft-surfaced REPLIED 必须带 soft_issues: {soft}"
    # hard-failed
    brain2 = _brain(["作为AI，我可以帮助你完成任务。", "作为AI，我可以帮助你完成任务。"])
    q2 = DirectDialogueQueue(bus=bus, timeout=5.0)
    q2.set_processor(lambda turn, snap: (
        lambda res: {"speech": res.get("speech"), "failure_reason": res.get("failure_reason"),
                     "validation_issues": res.get("validation_issues", []),
                     "hard_issues": res.get("hard_issues", []),
                     "soft_issues": res.get("soft_issues", [])})(
            brain2.say_with_result(**snap.say_kwargs(), deadline=turn.deadline)))
    q2.submit(_snap("在吗"), user_text="在吗")
    assert q2.wait_idle(timeout=8.0)
    hard = [p for p in terminal_payloads if p["phase"] == "FAILED"]
    assert hard and hard[0]["hard_issues"], f"hard-failed FAILED 必须带 hard_issues: {hard}"
    assert hard[0]["validation_issues"], "必须带 validation_issues"


# ================================================================ ⑧ severity invariant
def test_p0_8_activity_contradiction_invariant():
    """⑧：activity=offer_help 无帮助语义 → hard_issues 含 activity_contradiction 且 valid==False。"""
    r = _v.validate("我在看书呢", should_speak=True, activity="offer_help")
    assert "activity_contradiction" in r.hard_issues, r
    assert r.valid is False, "hard_issues 非空 ⇒ valid=False（invariant）"


def test_p0_8_no_valid_true_with_hard():
    """⑧：统一 invariant —— 任何 validate 结果不得 valid=True 且 hard_issues!=[]。"""
    for speech, kw in [("作为AI，我可以帮助你完成任务。", {}),
                       ("我在看书呢", {"activity": "offer_help"}),
                       ("我现在正在整理测试目录", {"activity": "talk"}),
                       ("你竟然敢偷袭我！", {"interaction": "petting"})]:
        r = _v.validate(speech, should_speak=True, **kw)
        assert not (r.valid and r.hard_issues), (speech, r.valid, r.hard_issues)


# ================================================================ ⑨ Agent success AGENT_REPORT
def test_p1_4_agent_success_uses_agent_report_semantics():
    """⑨：Agent completed 报告必须 channel=AGENT_REPORT、task_mode=True、context 含事实。"""
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
    kw = captured["kw"]
    assert kw.get("channel") == "AGENT_REPORT", kw
    assert kw.get("task_mode") is True, kw
    ctx = kw.get("context", "")
    assert "打开记事本" in ctx and "完成" in ctx and "验证" in ctx and "notepad.exe" in ctx, ctx
