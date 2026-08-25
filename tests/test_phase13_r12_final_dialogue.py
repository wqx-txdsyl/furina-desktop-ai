"""Phase 13 Pre-Manual Blocker Repair R1.2 — FINAL Dialogue Liveness Closure（基线 9b90b5f）。

R1.2-1 direct_turn_timeout 真正 ingress→terminal / R1.2-2 移除双 FIFO·双 sequence authority /
R1.2-3 per-call result 禁止回读共享字段 / R1.2-4 keep_outcomes 真 bounded。
只改 dialogue 子系统；不改 Persona/Motivation/Spatial/Relationship/Emotion/Memory/Agent。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from types import SimpleNamespace

from furina.core import EventBus, EventType
from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.dialogue_brain import DialogueBrain
from furina.runtime.dialogue_snapshot import DialogueContextSnapshot
from furina.runtime.dialogue_queue import DirectDialogueQueue


class _HangLLM:
    """永久挂起（阻塞在 Event；测试不放行）。"""

    def __init__(self):
        self.release = threading.Event()
        self.calls = 0

    def is_available(self):
        return True

    def structured(self, msgs, schema=None, temperature=0.9):
        self.calls += 1
        self.release.wait(timeout=30.0)
        return {"speech": "通了"}


class _SeqLLM:
    def __init__(self, fail=()):
        self.n = 0
        self.fail = set(fail)

    def is_available(self):
        return True

    def structured(self, msgs, schema=None, temperature=0.9):
        self.n += 1
        if self.n in self.fail:
            return {"speech": ""}
        return {"speech": f"回复{self.n}"}


def _snap(text, channel="DIRECT_USER_TURN"):
    return DialogueContextSnapshot(user_text=text, channel=channel, user_initiated=True)


def _app_with(db, say_capture=None):
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
                                 _say=(say_capture if say_capture is not None
                                       else (lambda t, dur=4.0: None)))
    app.dialogue_brain = db
    app._fallback_dispatcher = None
    app._rt_dispatcher().bind_owner()
    return app


# ================================================================ R1.2-1 总预算 ingress→terminal
def test_r12_1_five_rapid_with_hang_total_wall_about_one_budget():
    """timeout=0.25，五条快速（首条 hang）→ 总 wall ≈ 一次 budget，不是 5×。

    排队时间计入 deadline（submit 时刻设定）；turn2~5 轮到时已过 deadline → 立即 FAILED。
    """
    budget = 0.25
    hang = _HangLLM()
    brain = DialogueBrain(hang, persona="你是芙宁娜。")
    bus = EventBus()
    phases = []
    bus.on(EventType.DIRECT_TURN_TRACE, lambda ev: phases.append(ev.payload.get("phase")))
    q = DirectDialogueQueue(bus=bus, timeout=budget)

    def proc(turn, snap):
        res = brain.say_with_result(**snap.say_kwargs(), deadline=turn.deadline)
        return {"speech": res.get("speech"), "failure_reason": res.get("failure_reason")}

    q.set_processor(proc)
    t0 = time.monotonic()
    for i in range(5):
        q.submit(_snap(f"m{i}"), user_text=f"m{i}")
    assert q.wait_idle(timeout=8.0)
    elapsed = time.monotonic() - t0
    # 5 个 DirectTurn 全 terminal、无丢失、pending=0、worker alive
    assert phases.count("GENERATION_STARTED") == 5
    term = phases.count("REPLIED") + phases.count("FAILED") + phases.count("CANCELLED")
    assert term == 5, f"5 个 DirectTurn 全 terminal: {term}"
    assert q.pending() == 0
    assert q._worker.is_alive()
    outs = q.recent_outcomes(10)
    assert all(o["status"] == "FAILED" for o in outs), outs
    assert all(o["failure_reason"] == "generation_timeout" for o in outs), outs
    # 总 wall ≈ 一次 budget（5×budget = 1.25s 不允许；给 2.5× 调度容差）
    assert elapsed < budget * 2.5, f"总时长应接近一次 budget 而非 5×: {elapsed:.2f}s"
    assert elapsed >= budget * 0.5, f"turn1 应真正生成到超时: {elapsed:.2f}s"


# ================================================================ R1.2-2 双 FIFO 移除
def test_r12_2_middle_db_unavailable_same_brain_recovers():
    """同 brain 实例：msg1 REPLIED → db=None msg2 FAILED → 恢复同一实例 msg3 REPLIED。

    禁止 msg3 永久等待不存在的 msg2 brain seq（msg2 从未消费 seq）。
    """
    brain = DialogueBrain(_SeqLLM(), persona="你是芙宁娜。")
    app = _app_with(brain)
    dq = app._direct_dialogue_queue()

    app.submit_user_message("第一条")
    assert dq.wait_idle(timeout=8.0)
    assert dq.recent_outcomes(5)[0]["status"] == "REPLIED"

    app.dialogue_brain = None                      # 暂时不可用
    app.submit_user_message("第二条")
    assert dq.wait_idle(timeout=8.0)
    out2 = dq.recent_outcomes(5)[0]
    assert out2["status"] == "FAILED" and out2["failure_reason"] == "dialogue_brain_unavailable", out2

    app.dialogue_brain = brain                     # 恢复**同一实例**
    app.submit_user_message("第三条")
    assert dq.wait_idle(timeout=8.0), "msg3 不得永久等待"
    outs = dq.recent_outcomes(5)
    assert outs[0]["status"] == "REPLIED", f"msg3 必须 REPLIED: {outs}"
    # history 无 seq hole：msg1/回复1 + msg3/回复2（msg2 失败不占 brain seq；LLM 调用计数为第 2 次）
    assert [h["text"] for h in brain._history] == ["第一条", "回复1", "第三条", "回复2"], \
        [h["text"] for h in brain._history]


def test_r12_2_queue_timeout_then_normal_message_still_works():
    """多条消息在 queue 中超过 deadline → 直接 timeout；随后正常消息仍工作，无 seq hole。"""
    budget = 0.2
    hang = _HangLLM()
    brain = DialogueBrain(hang, persona="你是芙宁娜。")
    q = DirectDialogueQueue(bus=None, timeout=budget)

    def proc(turn, snap):
        res = brain.say_with_result(**snap.say_kwargs(), deadline=turn.deadline)
        return {"speech": res.get("speech"), "failure_reason": res.get("failure_reason")}

    q.set_processor(proc)
    q.submit(_snap("hang1"), user_text="hang1")
    q.submit(_snap("hang2"), user_text="hang2")
    q.submit(_snap("hang3"), user_text="hang3")
    # 等 hang1 超时 + hang2/3 过期失败
    assert q.wait_idle(timeout=8.0)
    outs = q.recent_outcomes(10)
    assert len(outs) == 3 and all(o["status"] == "FAILED" for o in outs), outs
    assert all(o["failure_reason"] == "generation_timeout" for o in outs), outs
    # 换正常 LLM（同一 brain，deadline 从头算）
    brain.llm = _SeqLLM()
    q.submit(_snap("正常"), user_text="正常")
    assert q.wait_idle(timeout=8.0)
    out = q.recent_outcomes(5)[0]
    assert out["status"] == "REPLIED", f"后续正常消息必须可工作: {out}"
    # history 无 hole：hang1 的 seq 被跳过，正常消息成对提交
    assert [h["text"] for h in brain._history] == ["正常", "回复1"], \
        [h["text"] for h in brain._history]


# ================================================================ R1.2-3 per-call result
def test_r12_3_direct_generation_empty_ambient_another_failure():
    """direct=generation_empty 且 ambient 同时产生另一 failure → DirectTurn 稳定等于 direct 自己的。"""
    class _SplitLLM:
        def is_available(self): return True
        def structured(self, msgs, schema=None, temperature=0.9):
            prompt = msgs[1].content[0]["text"] if isinstance(msgs[1].content, list) \
                else str(msgs[1].content)
            if "自主" in prompt:                 # ambient → 双重 invalid（慢）
                time.sleep(0.05)
                return {"speech": "（叹气）好吧"}
            return {"speech": ""}               # direct → generation_empty（快）

    brain = DialogueBrain(_SplitLLM(), persona="你是芙宁娜。")
    q = DirectDialogueQueue(bus=None, timeout=5.0)

    def proc(turn, snap):
        res = brain.say_with_result(**snap.say_kwargs(), deadline=turn.deadline)
        return {"speech": res.get("speech"), "failure_reason": res.get("failure_reason")}

    q.set_processor(proc)
    # ambient 先开跑（会写共享 last_failure_reason），direct 随后并发
    amb_result = {}

    def _ambient():
        amb_result["r"] = brain.say_with_result(channel="AMBIENT_AUTONOMOUS",
                                                user_initiated=False, intent="talk",
                                                context="自主", deadline=time.monotonic() + 5.0)

    t = threading.Thread(target=_ambient)
    t.start()
    time.sleep(0.02)                            # ambient 已进入生成（写共享值）
    q.submit(_snap("在吗"), user_text="在吗")
    assert q.wait_idle(timeout=8.0)
    t.join(timeout=8.0)
    out = q.recent_outcomes(5)[0]
    assert out["status"] == "FAILED"
    assert out["failure_reason"] == "generation_empty", \
        f"DirectTurn 必须稳定等于 direct 自己的 failure（ambient 不得污染）: {out['failure_reason']}"
    assert amb_result["r"]["failure_reason"] == "validation_twice_invalid", amb_result


def test_r12_3_say_impl_never_reads_shared_field_for_result():
    """R1.2-3：_say_impl 的 per-call return 不得回读 shared last_*（静态契约）。"""
    import furina.dialogue_brain as D
    src = open(D.__file__, encoding="utf-8").read()
    impl = src[src.index("def _say_impl"):src.index("def _generate(")]
    assert "return (None, self.last_failure_reason" not in impl, \
        "per-call result 禁止回读共享 last_failure_reason"
    assert "return self.last_failure_reason" not in impl
    assert "return self.last_validation_failure" not in impl


# ================================================================ R1.2-4 keep_outcomes 真 bounded
def test_r12_4_keep10_150_jobs_terminal_history_bounded():
    """keep_outcomes=10 + 150 jobs 全完成后（不再 submit）→ retained terminal ≤ 10。"""
    bus = EventBus()
    phases = []
    bus.on(EventType.DIRECT_TURN_TRACE, lambda ev: phases.append(ev.payload.get("phase")))
    q = DirectDialogueQueue(bus=bus, timeout=5.0, keep_outcomes=10)
    calls = []

    def proc(turn, snap):
        calls.append(turn.turn_id)
        return {"speech": "ok", "failure_reason": ""}

    q.set_processor(proc)
    for i in range(150):
        q.submit(_snap(f"m{i}"), user_text=f"m{i}")
    assert q.wait_idle(timeout=30.0)
    # 不再 submit —— terminal 历史必须已被 _finish trim 收敛
    assert len(calls) == 150, f"processor calls 必须 150: {len(calls)}"
    assert phases.count("GENERATION_STARTED") == 150
    term = phases.count("REPLIED") + phases.count("FAILED") + phases.count("CANCELLED")
    assert term == 150, f"terminal trace 必须 150: {term}"
    assert q.pending() == 0
    retained = q.recent_outcomes(1000)
    assert len(retained) <= 10, f"retained terminal history 必须 ≤ keep_outcomes: {len(retained)}"
    assert q._worker.is_alive()
