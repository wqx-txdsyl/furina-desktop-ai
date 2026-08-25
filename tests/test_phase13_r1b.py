"""Phase 13 FINAL-R1 Reviewer Residual Closeout — §3 owner 线程 / §4 FIFO+通道 测试。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from types import SimpleNamespace

from furina.core import EventBus
from furina.state import CharacterState
from furina.state.state_engine import StateEngine
from furina.emotion import EmotionEngine
from furina.runtime.scheduler import Scheduler
from furina.dialogue_brain import DialogueBrain


# ================================================================ §3 owner 线程分发
def _app_stub():
    from furina.app import Furina
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.emotion = EmotionEngine(app.state.state.emotion)
    app.relationship = SimpleNamespace(apply=lambda *a, **k: None, factors=lambda: {})
    app.memory = SimpleNamespace(observe=lambda *a, **k: None, retrieve=lambda **k: [],
                                 store=SimpleNamespace(save_relationship=lambda r: None))
    app.dialogue_brain = None
    app.bus = SimpleNamespace(emit=lambda *a, **k: None)
    app._sched = SimpleNamespace(interrupt_life=lambda r: None)
    app._fallback_dispatcher = None
    return app


def test_submit_user_message_requires_owner_thread():
    """submit_user_message 的域变更必须发生在 owner 线程（worker 调用 → RuntimeError）。"""
    app = _app_stub()
    d = app._rt_dispatcher()
    d.bind_owner()                      # owner = 本测试线程
    err = {}
    def _worker_call():
        try:
            app.submit_user_message("你真可爱")
        except RuntimeError as e:
            err["raised"] = str(e)
    t = threading.Thread(target=_worker_call)
    t.start(); t.join()
    assert "raised" in err, "worker 调用 submit_user_message 必须抛 owner 违规"
    assert d.violations(), "必须记录违规"
    # owner 调用正常
    app.submit_user_message("你真可爱")
    assert app.state.state.emotion.label in ("proud", "happy"), "owner 调用应正常生效"


def test_text_praise_domain_apply_runs_on_owner_thread():
    """praise 语义（关系/情绪）在 owner 线程执行。"""
    app = _app_stub()
    d = app._rt_dispatcher()
    d.bind_owner()
    applied_on = {}
    orig_apply = app.relationship.apply
    def _tracked(*a, **k):
        applied_on["thread"] = threading.get_ident()
        return orig_apply(*a, **k)
    app.relationship.apply = _tracked
    app.submit_user_message("你真可爱")
    assert applied_on.get("thread") == d.owner_thread_id, \
        f"praise 关系变更必须在 owner 线程: {applied_on.get('thread')} != {d.owner_thread_id}"


def test_talk_emotion_apply_runs_on_owner_thread():
    app = _app_stub()
    d = app._rt_dispatcher()
    d.bind_owner()
    seen = {}
    orig = app.emotion.apply_event
    def _tracked(event, tired_hint=0.0, delta=None):
        if event == "user_talk":
            seen["thread"] = threading.get_ident()
        return orig(event, tired_hint=tired_hint, delta=delta)
    app.emotion.apply_event = _tracked
    app.submit_user_message("今天天气不错")
    assert seen.get("thread") == d.owner_thread_id, "EVENT_TALK 必须在 owner 线程 apply"


def test_agent_planning_state_runs_on_owner_thread():
    """_agent_worker 的 planning 状态写入必须经 dispatcher 在 owner 线程落地。"""
    bus = EventBus()
    se = StateEngine(bus)
    app = _app_stub()
    app.state = SimpleNamespace(state=se.state)
    app._sched = None
    d = app._rt_dispatcher()
    d.bind_owner()
    app._agent_worker("打开记事本", {})
    # worker 提交后、drain 前：状态未变
    assert se.state.life.activity != "agent_planning", "worker 提交后不得直接改状态"
    d.drain()
    assert se.state.life.activity == "agent_planning", "drain（owner）后 planning 状态落地"
    assert se.state.life.macro.value == "working"


def test_agent_body_director_submit_runs_on_owner_thread():
    """_on_agent_body 的 Director.submit 必须经 dispatcher 在 owner 线程执行。"""
    bus = EventBus()
    app = _app_stub()
    submitted = []
    app.director = SimpleNamespace(submit=lambda r: submitted.append(r))
    d = app._rt_dispatcher()
    d.bind_owner()
    def _worker():
        app._on_agent_body("approach")
    t = threading.Thread(target=_worker)
    t.start(); t.join()
    assert submitted == [], "worker 线程不得直接改 Director 队列"
    d.drain()
    assert len(submitted) == 1 and submitted[0].source == "agent", \
        "owner drain 后 Director 收到 agent body 请求"


def test_feed_domain_effect_runs_on_owner_thread():
    from unittest import mock
    app = _app_stub()
    d = app._rt_dispatcher()
    d.bind_owner()
    app.dialogue_brain = None
    err = {}
    def _worker():
        try:
            app.submit_feed("蛋糕")
        except RuntimeError as e:
            err["raised"] = str(e)
    with mock.patch("furina.feeding.apply_food", return_value={"hunger": -30, "satisfaction": +10}):
        t = threading.Thread(target=_worker)
        t.start(); t.join()
    assert "raised" in err, "worker 调用 submit_feed 必须抛 owner 违规"
    with mock.patch("furina.feeding.apply_food", return_value={"hunger": -30, "satisfaction": +10}):
        app.submit_feed("蛋糕")   # owner 正常
    assert app.state.state.intent.action == "eat", "owner 调用 feed 应正常生效"


# ================================================================ §4 FIFO + 通道
class _SlowLLM:
    def __init__(self):
        self.calls = 0
    def is_available(self):
        return True
    def structured(self, msgs, schema, temperature=0.9):
        self.calls += 1
        if self.calls == 1:
            time.sleep(0.2)
        return {"speech": f"回复{self.calls}"}


def _db():
    return DialogueBrain(_SlowLLM(), persona="你是芙宁娜。")


def test_direct_user_ingress_is_strict_fifo():
    db = _db()
    results = {}
    def _call(text, tag):
        results[tag] = db.say(intent="talk", user_text=text, user_initiated=True,
                              context="casual", user_present=True)
    t1 = threading.Thread(target=_call, args=("第一句", "r1"))
    t2 = threading.Thread(target=_call, args=("第二句", "r2"))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert [h["text"] for h in db._history] == ["第一句", "回复1", "第二句", "回复2"], \
        f"直接对话必须严格 FIFO: {[h['text'] for h in db._history]}"


def test_second_input_cannot_overtake_first_before_lock_acquisition():
    """绕过锁：msg2（seq 3/4）先提交，msg1（seq 1/2）后提交 → 历史仍按 seq 排序。"""
    db = _db()
    def _late():
        time.sleep(0.05)
        db._push_ordered(1, "user", "第一句")
        db._push_ordered(2, "furina", "回复1")
    def _early():
        db._push_ordered(3, "user", "第二句")   # 先到但 seq 更大
        db._push_ordered(4, "furina", "回复2")
    t1 = threading.Thread(target=_late)
    t2 = threading.Thread(target=_early)
    t2.start(); t1.start(); t2.join(); t1.join()
    assert [h["text"] for h in db._history] == ["第一句", "回复1", "第二句", "回复2"], \
        f"seq 排序失败（后到者不得超车）: {[h['text'] for h in db._history]}"


def _ambient_speech(db, channel):
    return db.say(intent="talk", user_initiated=False, context="casual",
                  channel=channel, user_present=True)


def test_autonomous_speech_not_added_as_orphan_direct_turn():
    db = _db()
    _ambient_speech(db, "AMBIENT_AUTONOMOUS")
    assert all(h["channel"] == "DIRECT_USER_TURN" for h in db._history) and db._history == [], \
        "自主台词不得进入直接对话历史"
    assert len(db._ambient) == 1 and db._ambient[0]["channel"] == "AMBIENT_AUTONOMOUS"


def test_feed_speech_not_added_as_orphan_direct_turn():
    db = _db()
    _ambient_speech(db, "FEED_REACTION")
    assert db._history == [], "喂食台词不得进入直接对话历史"
    assert db._ambient[0]["channel"] == "FEED_REACTION"


def test_agent_report_not_added_as_orphan_direct_turn():
    db = _db()
    _ambient_speech(db, "AGENT_REPORT")
    assert db._history == [], "Agent 报告台词不得进入直接对话历史"
    assert db._ambient[0]["channel"] == "AGENT_REPORT"


def test_direct_history_remains_coherent_after_ambient_speech():
    db = _db()
    db.say(intent="talk", user_text="在吗", user_initiated=True, context="casual")
    _ambient_speech(db, "AMBIENT_AUTONOMOUS")
    db.say(intent="talk", user_text="还在吗", user_initiated=True, context="casual")
    texts = [h["text"] for h in db._history]
    # 直接历史只有成对的 user/furina（环境台词穿插后仍连贯）
    assert texts[0] == "在吗" and texts[2] == "还在吗"
    assert all(h["channel"] == "DIRECT_USER_TURN" for h in db._history)
    assert len(db._history) == 4, f"直接历史必须保持成对连贯: {texts}"
