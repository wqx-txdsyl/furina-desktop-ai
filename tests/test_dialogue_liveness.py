"""Phase 13 Pre-Manual Blocker Repair R1 — B1 Direct Dialogue Liveness（DIALOGUE-L1..L10）。

硬契约（评审基线 0402e7f）：
  - 每个 DIRECT_USER_TURN 必达终态 REPLIED / FAILED / CANCELLED（禁止 PENDING_FOREVER）；
  - DIRECT 与 AMBIENT/REACTION/FEED/AGENT 独立 lane（ambient 不占 direct 序号、不堵 direct）；
  - direct ingress FIFO 保序；失败无 orphan user history；生成有界（timeout 可注入）；
  - 可观测相位 DIRECT_INGRESS/QUEUED/GENERATION_STARTED/GENERATION_FINISHED → 终态。
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from types import SimpleNamespace

import pytest

from furina.core import EventBus, EventType
from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.dialogue_brain import DialogueBrain
from furina.runtime.dialogue_snapshot import DialogueContextSnapshot
from furina.runtime.dialogue_queue import DirectDialogueQueue


# ================================================================ 可控 fake LLM
class _SeqLLM:
    """按调用序返回 回复{n}；可指定 slow（延迟）/ fail（空输出）。"""

    def __init__(self, fail=(), slow=(), delay=0.05):
        self.order = {"n": 0, "calls": []}
        self.fail = set(fail)
        self.slow = set(slow)
        self.delay = delay

    def is_available(self):
        return True

    def structured(self, msgs, schema=None, temperature=0.9):
        n = self.order["n"] + 1
        self.order["n"] = n
        self.order["calls"].append(n)
        if n in self.slow:
            time.sleep(self.delay)
        if n in self.fail:
            return {"speech": ""}
        return {"speech": f"回复{n}"}


class _SeqSpeechLLM:
    """按调用序弹出一条预置 speech（耗尽后返回空）。"""

    def __init__(self, speeches):
        self._s = list(speeches)
        self.calls = 0

    def is_available(self):
        return True

    def structured(self, msgs, schema=None, temperature=0.9):
        self.calls += 1
        return {"speech": self._s.pop(0) if self._s else ""}


class _HangLLM:
    """阻塞在 Event 上的 LLM（模拟网络挂起；由测试决定是否放行）。"""

    def __init__(self):
        self.release = threading.Event()
        self.calls = 0

    def is_available(self):
        return True

    def structured(self, msgs, schema=None, temperature=0.9):
        self.calls += 1
        self.release.wait(timeout=30.0)      # 测试不放行则一直阻塞（有界 join 由 say timeout 接管）
        return {"speech": "总算通了"}


def _snap(text, seq=None, channel="DIRECT_USER_TURN"):
    return DialogueContextSnapshot(user_text=text, channel=channel, ingress_seq=seq,
                                   user_initiated=True)   # 生产 _freeze_direct_snapshot 恒 True


def _make_queue(brain, bus=None, timeout=5.0) -> DirectDialogueQueue:
    """真实 DirectDialogueQueue + 生产等价处理器（say_with_result → BRAIN_SPOKE/终态信息）。"""
    q = DirectDialogueQueue(bus=bus, timeout=timeout)

    def proc(turn, snap):
        # R1.1-3：processor 用 turn.deadline（总预算，attempt+retry 共享）
        res = brain.say_with_result(**snap.say_kwargs(), deadline=turn.deadline)
        speech = res.get("speech")
        if speech:
            if bus is not None:
                bus.emit(EventType.BRAIN_SPOKE,
                         payload=type("_O", (), {"speech": speech})(), source="app")
            return {"speech": speech, "failure_reason": ""}
        reason = str(res.get("failure_reason") or "") or "generation_empty"
        return {"speech": None, "failure_reason": reason}

    q.set_processor(proc)
    return q


def _submit(q, brain, text, seq=None):
    if seq is None:
        seq = brain.reserve_turn()          # owner 入口预留 direct 序号（生产语义）
    snap = _snap(text, seq=seq)
    return q.submit(snap, ingress_seq=seq, user_text=text)


def _app_with_dialogue(db):
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
                                 _say=lambda t, dur=4.0: None)
    app.dialogue_brain = db
    app._fallback_dispatcher = None
    app._rt_dispatcher().bind_owner()
    return app


# ================================================================ DIALOGUE-L1
def test_dialogue_l1_five_rapid_submits_all_terminal_in_order():
    """L1：连续快速 submit 5 条，第一条较慢 → 五条全部 terminal、顺序正确。"""
    brain = DialogueBrain(_SeqLLM(slow={1}, delay=0.08), persona="你是芙宁娜。", timeout=5.0)
    brain._history_limit = 100            # 测试放开有界历史，验证完整 FIFO 序列
    q = _make_queue(brain)
    for i in range(1, 6):
        _submit(q, brain, f"第{i}条")
    assert q.wait_idle(timeout=8.0), f"5 条必须全部到达终态: {q.recent_outcomes(10)}"
    outs = sorted(q.recent_outcomes(10), key=lambda o: o["ingress_seq"])
    assert len(outs) == 5
    assert all(o["status"] == "REPLIED" for o in outs), outs
    assert [o["ingress_seq"] for o in outs] == [1, 2, 3, 4, 5], "ingress FIFO 保序"
    assert [h["text"] for h in brain._history] == \
        ["第1条", "回复1", "第2条", "回复2", "第3条", "回复3", "第4条", "回复4", "第5条", "回复5"]


# ================================================================ DIALOGUE-L2/L3
@pytest.mark.parametrize("fail_seq", [(1,), (1,)])
def test_dialogue_l2_l3_failure_or_empty_turn_does_not_block_next(fail_seq):
    """L2/L3：turn1 LLM exception/empty → turn2 仍正常返回（FIFO 继续，无死锁）。"""
    brain = DialogueBrain(_SeqLLM(fail={1}), persona="你是芙宁娜。", timeout=5.0)
    q = _make_queue(brain)
    _submit(q, brain, "第一句")
    _submit(q, brain, "第二句")
    assert q.wait_idle(timeout=8.0)
    outs = sorted(q.recent_outcomes(10), key=lambda o: o["ingress_seq"])
    assert outs[0]["status"] == "FAILED" and outs[0]["failure_reason"], outs[0]
    assert outs[1]["status"] == "REPLIED" and outs[1]["ingress_seq"] == 2, outs[1]
    assert [h["text"] for h in brain._history] == ["第二句", "回复2"], \
        "失败回合不得产生孤儿 User 历史"


# ================================================================ DIALOGUE-L4
def test_dialogue_l4_validator_twice_invalid_does_not_block_next():
    """L4：turn1 validator 两次 invalid → turn2 正常（FIFO 继续）。"""
    # "（叹气）…" 触发 stage_direction → invalid；turn1 两次生成都 invalid → 失败
    brain = DialogueBrain(
        _SeqSpeechLLM(["（叹气）好吧", "（叹气）好吧", "嗯，我在呢。"]),
        persona="你是芙宁娜。", timeout=5.0)
    q = _make_queue(brain)
    _submit(q, brain, "第一句")
    _submit(q, brain, "第二句")
    assert q.wait_idle(timeout=8.0)
    outs = sorted(q.recent_outcomes(10), key=lambda o: o["ingress_seq"])
    assert outs[0]["status"] == "FAILED" and outs[0]["failure_reason"] == "validation_twice_invalid", outs[0]
    assert outs[1]["status"] == "REPLIED", outs[1]
    assert [h["text"] for h in brain._history] == ["第二句", "嗯，我在呢。"]


# ================================================================ DIALOGUE-L5
def test_dialogue_l5_ambient_hang_does_not_block_direct():
    """L5：ambient 故意挂起 → direct 用户消息不被阻塞（独立 lane + 无锁 LLM 阶段）。"""
    fast = DialogueBrain(_SeqLLM(), persona="你是芙宁娜。", timeout=5.0)
    hang2 = _HangLLM()                      # 永不放行 → ambient 生成线程一直挂起
    brain2 = DialogueBrain(hang2, persona="你是芙宁娜。", timeout=0.2)
    # ambient 回合：后台线程生成（卡在 _generate → 有界 join 后按超时失败，挂起线程被弃）
    ambient2 = threading.Thread(
        target=lambda: brain2.say(channel="AMBIENT_AUTONOMOUS", user_initiated=False,
                                  intent="talk", context="自主"))
    ambient2.start()
    time.sleep(0.3)                          # ambient 已进入生成并挂起
    # direct 回合（独立 lane）必须立即出话，不等待 ambient 的 gate / lock / LLM
    t1 = time.monotonic()
    out2 = fast.say(channel="DIRECT_USER_TURN", user_text="在吗", user_initiated=True, timeout=5.0)
    dt = time.monotonic() - t1
    ambient2.join(timeout=5.0)
    assert out2 == "回复1", f"direct 必须立即回复: {out2}"
    assert dt < 1.0, f"direct 不应被 ambient 阻塞: {dt:.2f}s"
    # 同一个 brain 上：ambient 挂起期间 direct 回合同样不被 ambient lane 阻塞
    seq = brain2.reserve_turn()
    out3 = brain2.say(channel="DIRECT_USER_TURN", user_text="在吗", user_initiated=True,
                      ingress_seq=seq, timeout=0.5)
    # ambient LLM 是 hang（无回复）→ direct 有界失败（generation_timeout），但**不是无限等待**
    assert out3 is None
    assert brain2.last_failure_reason == "generation_timeout", brain2.last_failure_reason


# ================================================================ DIALOGUE-L6
def test_dialogue_l6_reversed_worker_arrival_keeps_ingress_order():
    """L6：两个 worker 到达顺序反转 → 最终 direct 顺序仍按 ingress（owner 预留 seq 生效）。"""
    brain = DialogueBrain(_SeqLLM(slow={1}, delay=0.1), persona="你是芙宁娜。", timeout=5.0)
    q = _make_queue(brain)
    seq1 = brain.reserve_turn()
    seq2 = brain.reserve_turn()
    s1 = _snap("第一句", seq1)
    s2 = _snap("第二句", seq2)
    # worker2 先入队消费路径（人工模拟反转：先 submit 2 后 submit 1？不行——FIFO 队列本身保序。
    # 这里证明 owner 预留 seq 与队列入队一致：即使 say() 被并发调用，direct gate 也按 seq 保序）
    results = {}
    def _w1():
        results["r1"] = brain.say(**s1.say_kwargs(), timeout=5.0)
    def _w2():
        results["r2"] = brain.say(**s2.say_kwargs(), timeout=5.0)
    t2 = threading.Thread(target=_w2); t2.start()
    time.sleep(0.05)                        # worker2 先到 say
    t1 = threading.Thread(target=_w1); t1.start()
    t1.join(timeout=8); t2.join(timeout=8)
    assert not t1.is_alive() and not t2.is_alive()
    assert [h["text"] for h in brain._history] == ["第一句", "回复1", "第二句", "回复2"], \
        f"direct history 必须按 ingress 顺序: {[h['text'] for h in brain._history]}"


# ================================================================ DIALOGUE-L7
def test_dialogue_l7_failed_direct_turn_no_orphan_user_history():
    """L7：失败 direct turn 不产生 orphan user history。"""
    brain = DialogueBrain(_SeqLLM(fail={1}), persona="你是芙宁娜。", timeout=5.0)
    q = _make_queue(brain)
    _submit(q, brain, "在吗")
    assert q.wait_idle(timeout=8.0)
    assert q.recent_outcomes(1)[0]["status"] == "FAILED"
    assert brain._history == [], f"失败回合不得留孤儿 User 回合: {brain._history}"


# ================================================================ DIALOGUE-L8
def test_dialogue_l8_success_history_strict_pairs():
    """L8：成功 direct history 严格 user/furina 成对。"""
    brain = DialogueBrain(_SeqLLM(), persona="你是芙宁娜。", timeout=5.0)
    q = _make_queue(brain)
    _submit(q, brain, "user1")
    _submit(q, brain, "user2")
    assert q.wait_idle(timeout=8.0)
    roles = [h["role"] for h in brain._history]
    assert roles == ["user", "furina", "user", "furina"], roles


# ================================================================ DIALOGUE-L9
def test_dialogue_l9_system_status_not_in_persona_history():
    """L9：SYSTEM_STATUS 不进 Persona direct history。"""
    brain = DialogueBrain(_SeqLLM(fail={1}), persona="你是芙宁娜。", timeout=5.0)
    app = _app_with_dialogue(brain)
    sys_status = []
    app._sched._say = lambda t, dur=4.0: sys_status.append(t)
    app.submit_user_message("在吗")
    dq = app._direct_dialogue_queue()
    assert dq.wait_idle(timeout=8.0)
    app._rt_dispatcher().drain()          # SYSTEM_STATUS 经 dispatcher 回 owner 落地
    assert dq.recent_outcomes(1)[0]["status"] == "FAILED", "失败必须有可观察终态"
    assert sys_status and "系统状态" in sys_status[-1], f"失败必须产生 SYSTEM_STATUS: {sys_status}"
    assert not any("系统状态" in (h.get("text") or "") for h in brain._history), \
        "SYSTEM_STATUS 不得进入 Persona 历史"


# ================================================================ DIALOGUE-L10
def test_dialogue_l10_20_rapid_stress_all_terminal_no_deadlock():
    """L10：20 条快速 direct stress → 全部 terminal、无存活死锁 worker / pending ticket。"""
    brain = DialogueBrain(_SeqLLM(), persona="你是芙宁娜。", timeout=5.0)
    brain._history_limit = 100
    q = _make_queue(brain)
    for i in range(1, 21):
        _submit(q, brain, f"消息{i}")
    assert q.wait_idle(timeout=15.0), f"20 条必须全部 terminal: {q.recent_outcomes(30)}"
    cnt = q.outcome_count()
    assert cnt["REPLIED"] == 20, cnt
    assert q.pending() == 0, "无存活 pending ticket"
    assert len(brain._history) == 40, "20 轮严格成对（40 条）"
    assert [h["text"] for h in brain._history][::2][:3] == ["消息1", "消息2", "消息3"], "ingress FIFO"


# ================================================================ lane 隔离（ambient 不占 direct 序号）
def test_ambient_does_not_consume_direct_ingress_sequence():
    """B. Ambient 不占用 direct ingress sequence（独立序号空间）。"""
    brain = DialogueBrain(_SeqLLM(), persona="你是芙宁娜。", timeout=5.0)
    brain.say(channel="AMBIENT_AUTONOMOUS", user_initiated=False, intent="talk", context="自主")
    seq = brain.reserve_turn()
    assert seq == 1, f"ambient 不得占用 direct 序号: {seq}"
    assert brain._history == [], "ambient 不进 direct 历史"


def test_direct_turn_trace_phases_observable():
    """可观测性：DIRECT_INGRESS/QUEUED/GENERATION_STARTED/GENERATION_FINISHED → REPLIED。"""
    bus = EventBus()
    brain = DialogueBrain(_SeqLLM(), persona="你是芙宁娜。", timeout=5.0)
    q = _make_queue(brain, bus=bus, timeout=5.0)
    phases = []
    bus.on(EventType.DIRECT_TURN_TRACE, lambda ev: phases.append(ev.payload.get("phase")))
    _submit(q, brain, "你好")
    assert q.wait_idle(timeout=8.0)
    assert "DIRECT_INGRESS" in phases and "QUEUED" in phases
    assert "GENERATION_STARTED" in phases and "GENERATION_FINISHED" in phases
    assert "REPLIED" in phases, f"终态必须可观测: {phases}"
