"""Phase 13 Pre-Manual Blocker Repair R1.1 — Reviewer Residual Gate（基线 250aa74）。

R1.1-1 dialogue_brain=None 也必须有可观察终态 / R1.1-2 绝不 trim 活跃 turn /
R1.1-3 timeout 是整回合总预算 / R1.1-4 Persona 身份去 AI 元叙事 /
R1.1-5 activity grounding 通用矛盾矩阵 / R1.1-6 per-call failure_reason + 去重。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from types import SimpleNamespace

import pytest

from furina.core import EventBus, EventType
from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.dialogue.validator import DialogueValidator
from furina.dialogue_brain import DialogueBrain
from furina.runtime.dialogue_snapshot import DialogueContextSnapshot
from furina.runtime.dialogue_queue import DirectDialogueQueue

_v = DialogueValidator()


def _snap(text, seq=None, channel="DIRECT_USER_TURN"):
    return DialogueContextSnapshot(user_text=text, channel=channel, ingress_seq=seq,
                                   user_initiated=True)


# ================================================================ R1.1-1 db=None
def _app_brain_none():
    from furina.app import Furina
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
    app.dialogue_brain = None
    app._fallback_dispatcher = None
    app._rt_dispatcher().bind_owner()
    return app


def test_direct_message_brain_none_has_failed_terminal():
    """R1.1-1：db=None 的消息也必须产生 DirectTurn + FAILED(dialogue_brain_unavailable)。"""
    app = _app_brain_none()
    phases = []
    app.bus.on(EventType.DIRECT_TURN_TRACE, lambda ev: phases.append(ev.payload.get("phase")))
    app.submit_user_message("在吗")
    dq = app._direct_dialogue_queue()
    assert dq.wait_idle(timeout=8.0)
    outs = dq.recent_outcomes(5)
    assert outs and outs[0]["status"] == "FAILED", outs
    assert outs[0]["failure_reason"] == "dialogue_brain_unavailable", outs[0]
    assert "DIRECT_INGRESS" in phases and "QUEUED" in phases and "FAILED" in phases


def test_direct_message_brain_none_has_system_status():
    """R1.1-1：db=None 也必须产生可观察 SYSTEM_STATUS。"""
    app = _app_brain_none()
    sys_status = []
    app._sched._say = lambda t, dur=4.0, channel="", turn_id=None: sys_status.append(t)
    app.submit_user_message("在吗")
    dq = app._direct_dialogue_queue()
    assert dq.wait_idle(timeout=8.0)
    app._rt_dispatcher().drain()
    assert sys_status and "系统状态" in sys_status[-1], f"必须产生 SYSTEM_STATUS: {sys_status}"


def test_direct_message_brain_none_does_not_create_orphan_history():
    """R1.1-1：db=None 不得产生孤儿/伪回复（无 BRAIN_SPOKE、无 Furina 台词）。"""
    app = _app_brain_none()
    spoke = []
    app.bus.on(EventType.BRAIN_SPOKE, lambda ev: spoke.append(ev.payload))
    app.submit_user_message("在吗")
    dq = app._direct_dialogue_queue()
    assert dq.wait_idle(timeout=8.0)
    assert spoke == [], "db=None 不得伪造 Furina 回复"
    assert dq.recent_outcomes(1)[0]["status"] == "FAILED"


def test_direct_message_brain_none_next_message_after_recovery_can_reply():
    """R1.1-1：db=None 失败后，恢复（注入 dialogue_brain）→ 下一条消息正常回复。"""
    app = _app_brain_none()
    app.submit_user_message("第一条")
    dq = app._direct_dialogue_queue()
    assert dq.wait_idle(timeout=8.0)
    assert dq.recent_outcomes(1)[0]["failure_reason"] == "dialogue_brain_unavailable"

    class _LLM:
        def is_available(self): return True
        def structured(self, msgs, schema=None, temperature=0.9):
            return {"speech": "嗯，我在呢。"}
    app.dialogue_brain = DialogueBrain(_LLM(), persona="你是芙宁娜。")
    app.submit_user_message("恢复后")
    assert dq.wait_idle(timeout=8.0)
    outs = dq.recent_outcomes(5)
    assert outs[0]["status"] == "REPLIED", f"恢复后必须可回复: {outs}"
    # R1.2-2：DirectTurn.ingress_seq = queue turn_id（未显式给 ingress_seq 时）
    assert outs[0]["ingress_seq"] == 2, "恢复后的第一条是第 2 条消息（turn_id=2）"


# ================================================================ R1.1-2 trim
def test_r11_2_keep5_30_jobs_first_slow_all_processed():
    """R1.1-2：keep_outcomes=5 + 30 条快速提交（首条 slow）→ 30 条全部进入 processor 并终态。"""
    bus = EventBus()
    phases = []
    bus.on(EventType.DIRECT_TURN_TRACE, lambda ev: phases.append(ev.payload.get("phase")))
    q = DirectDialogueQueue(bus=bus, timeout=5.0, keep_outcomes=5)
    calls = []

    def proc(turn, snap):
        if turn.turn_id == 1:
            time.sleep(0.05)          # 第 1 条故意 slow（此时后续 29 条已 QUEUED）
        calls.append(turn.turn_id)
        return {"speech": "ok", "failure_reason": ""}

    q.set_processor(proc)
    for i in range(1, 31):
        q.submit(_snap(f"m{i}", seq=i), ingress_seq=i, user_text=f"m{i}")
    assert q.wait_idle(timeout=20.0), f"30 条必须全部 terminal: {q.recent_outcomes(10)}"
    assert len(calls) == 30, f"30 条必须全部真实进入 processor（无跳过）: {len(calls)}"
    assert phases.count("GENERATION_STARTED") == 30
    term = phases.count("REPLIED") + phases.count("FAILED") + phases.count("CANCELLED")
    assert term == 30, f"30 条全部终态: {term}"
    assert q.pending() == 0, "无存活 pending"
    assert q._worker.is_alive(), "worker 必须仍存活"


def test_r11_2_keep10_150_jobs_all_processed():
    """R1.1-2：keep_outcomes=10 + 150 个快速 fake direct jobs → 150 个 processor call 全部发生。"""
    q = DirectDialogueQueue(bus=None, timeout=5.0, keep_outcomes=10)
    calls = []

    def proc(turn, snap):
        calls.append(turn.turn_id)
        return {"speech": "ok", "failure_reason": ""}

    q.set_processor(proc)
    for i in range(1, 151):
        q.submit(_snap(f"m{i}", seq=i), ingress_seq=i, user_text=f"m{i}")
    assert q.wait_idle(timeout=30.0), "150 条必须全部 terminal"
    assert len(calls) == 150, f"150 个 processor call 必须全部发生: {len(calls)}"
    assert q.pending() == 0
    # keep_outcomes 只限 terminal 历史：活跃 turn 从未被删 → 无消息丢失
    assert q._worker.is_alive()


# ================================================================ R1.1-3 总预算
def test_r11_3_timeout_is_total_turn_budget_attempt_plus_retry():
    """R1.1-3：attempt1 消耗大部分预算 → validator invalid → retry 只拿剩余预算。

    总 wall time ≤ 总预算 + 小容差（retry 不重置预算；timeout 不是两次独立 300s）。
    """
    budget = 0.3

    class _LLM:
        def __init__(self):
            self._n = 0
        def is_available(self): return True
        def structured(self, msgs, schema=None, temperature=0.9):
            self._n += 1
            if self._n == 1:
                time.sleep(budget * 0.85)       # 消耗 85% 预算
                return {"speech": "（叹气）好吧"}   # invalid → retry
            time.sleep(budget * 2)              # retry 远超剩余预算 → 超时
            return {"speech": "嗯"}

    db = DialogueBrain(_LLM(), persona="你是芙宁娜。")
    q = DirectDialogueQueue(bus=None, timeout=budget)   # queue.timeout = 总生命周期预算

    def proc(turn, snap):
        res = db.say_with_result(**snap.say_kwargs(), deadline=turn.deadline)
        return {"speech": res.get("speech"), "failure_reason": res.get("failure_reason")}

    q.set_processor(proc)
    t0 = time.monotonic()
    q.submit(_snap("在吗", seq=1), ingress_seq=1, user_text="在吗")
    assert q.wait_idle(timeout=8.0)
    elapsed = time.monotonic() - t0
    out = q.recent_outcomes(5)[0]
    assert out["status"] == "FAILED" and out["failure_reason"] == "generation_timeout", out
    # 共享预算：总时长 ≤ 预算×1.7 + 调度容差（若 retry 重置预算会到 ~1.85×预算）
    assert elapsed < budget * 1.7 + 0.15, f"总时长必须 ≤ 总预算+容差: {elapsed:.2f}s vs {budget}s"


def test_r11_3_deadline_zero_remaining_fails_immediately():
    """R1.1-3：remaining<=0 → 立即 generation_timeout（不做第二次生成）。"""
    db = DialogueBrain(type("_L", (), {"is_available": lambda s: True,
                                       "structured": lambda *a, **k: {"speech": "x"}})(),
                       persona="你是芙宁娜。")
    res = db.say_with_result(channel="DIRECT_USER_TURN", user_text="在吗", user_initiated=True,
                             ingress_seq=1, deadline=time.monotonic() - 1.0)
    assert res["speech"] is None
    assert res["failure_reason"] == "generation_timeout"


# ================================================================ R1.1-4 Persona 身份
def test_persona_identity_no_ai_meta_framing():
    """R1.1-4：核心身份段不得含 AI/游戏元叙事；仍保留 芙宁娜/枫丹。"""
    from furina.persona import FURINA_PERSONA
    assert "芙宁娜" in FURINA_PERSONA and "枫丹" in FURINA_PERSONA
    for bad in ("AI 数字生命", "AI助手", "来自《原神》", "游戏角色"):
        assert bad not in FURINA_PERSONA, f"核心身份段不得含: {bad}"
    # 转 in-world identity：她就是芙宁娜本人，不是"观察人类的 AI"
    assert "你就是芙宁娜本人" in FURINA_PERSONA or "你是芙宁娜本人" in FURINA_PERSONA


# ================================================================ R1.1-5 activity grounding 矩阵
@pytest.mark.parametrize("activity, speech, should_be_invalid", [
    # ---- conflict（互斥当前行为声称 → ungrounded_activity）----
    ("read", "我正在吃蛋糕", True),          # READ vs EAT
    ("eat", "我正在看书", True),             # EAT vs READ
    ("wander", "我正躺着休息", True),        # EXPLORE vs REST
    ("sleep", "我正在四处逛逛", True),       # SLEEP vs EXPLORE
    ("play", "我正在写报告", True),          # PLAY vs WORK
    ("work", "我正躺着打盹", True),          # WORK vs REST
    ("drink", "我在看书", True),             # DRINK vs READ
    ("think", "我在吃蛋糕", True),           # THINK vs EAT
    # ---- compatible（合法：同组自声称 / 无互斥声称 / 自然描述）----
    ("read", "嗯，我在看书呢", False),       # READ 自声称一致
    ("explore", "我正在探索新事物", False),  # EXPLORE 自声称一致
    ("rest", "刚把书放下，发会儿呆", False),  # REST 合法自然描述（无'休息'字样）
    ("read", "刚看到一个很有意思的地方", False),  # READ 无互斥声称
])
def test_r11_5_activity_grounding_matrix(activity, speech, should_be_invalid):
    """R1.1-5：≥5 个 activity 组 × conflict/compatible 矩阵（通用矛盾检查）。"""
    r = _v.validate(speech, should_speak=True, activity=activity, context="casual")
    if should_be_invalid:
        assert not r.valid, (activity, speech)
        assert "ungrounded_activity" in r.issues, (activity, speech, r.issues)
    else:
        assert r.valid, (activity, speech, r.issues)


# ================================================================ R1.1-6 per-call reason + 去重
def test_r11_6_no_duplicate_gate_definitions():
    """R1.1-6：_gate_wait/_gate_release 必须唯一实现（无重复定义）。"""
    import furina.dialogue_brain as D
    src = open(D.__file__, encoding="utf-8").read()
    assert src.count("def _gate_wait") == 1, "存在重复 _gate_wait 定义"
    assert src.count("def _gate_release") == 1, "存在重复 _gate_release 定义"


def test_r11_6_per_call_failure_reason_not_shared_value():
    """R1.1-6：direct failure_reason 来自 per-call result，不被预置的共享值污染。"""
    class _LLM:
        def __init__(self):
            self._s = ["（叹气）好吧", "（叹气）好吧"]
        def is_available(self): return True
        def structured(self, msgs, schema=None, temperature=0.9):
            return {"speech": self._s.pop(0) if self._s else ""}
    brain = DialogueBrain(_LLM(), persona="你是芙宁娜。")
    brain.last_failure_reason = "ambient_clobber"      # 模拟 ambient 已改写共享诊断值
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="在吗",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] is None
    assert res["failure_reason"] == "validation_twice_invalid", \
        f"per-call result 必须返回 direct 自己的原因: {res}"


def test_r11_6_direct_and_ambient_failure_concurrent_direct_reason_own():
    """R1.1-6：direct 失败与 ambient 失败并发 → DirectTurn.failure_reason 是 direct 自己的。"""
    class _SplitLLM:
        def __init__(self):
            self._direct_calls = 0
        def is_available(self): return True
        def structured(self, msgs, schema=None, temperature=0.9):
            prompt = msgs[1].content[0]["text"] if isinstance(msgs[1].content, list) \
                else str(msgs[1].content)
            if "自主" in prompt:                        # ambient 提示 → 空输出失败
                return {"speech": ""}
            self._direct_calls += 1                     # direct → invalid ×2（慢，给并发窗口）
            if self._direct_calls <= 2:
                time.sleep(0.05)
                return {"speech": "（叹气）好吧"}
            return {"speech": "嗯"}

    brain = DialogueBrain(_SplitLLM(), persona="你是芙宁娜。")
    q = DirectDialogueQueue(bus=None, timeout=5.0)

    def proc(turn, snap):
        res = brain.say_with_result(**snap.say_kwargs(), deadline=turn.deadline)
        return {"speech": res.get("speech"), "failure_reason": res.get("failure_reason")}

    q.set_processor(proc)
    q.submit(_snap("在吗", seq=1), ingress_seq=1, user_text="在吗")
    time.sleep(0.02)                                    # direct 已进入生成
    amb = brain.say_with_result(channel="AMBIENT_AUTONOMOUS", user_initiated=False,
                                intent="talk", context="自主", deadline=time.monotonic() + 5.0)
    assert amb["speech"] is None and amb["failure_reason"] == "generation_empty", amb
    assert q.wait_idle(timeout=8.0)
    out = q.recent_outcomes(5)[0]
    assert out["status"] == "FAILED"
    assert out["failure_reason"] == "validation_twice_invalid", \
        f"DirectTurn.failure_reason 必须是 direct 自己的原因（ambient 并发不得污染）: {out}"
