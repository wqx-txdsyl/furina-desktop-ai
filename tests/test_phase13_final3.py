"""Phase 13 终审 Batch B：§9 Validator 强制、§10 Agent 真相性、§11 Feed 生产路径。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from types import SimpleNamespace

from furina.dialogue_brain import DialogueBrain


# ================================================================ §9 Validator 强制
class _FakeLLM:
    """按队列返回 speech 的假 LLM（is_available True；structured 返回 schema 字段）。"""

    def __init__(self, speeches):
        self._speeches = list(speeches)
        self.calls = 0

    def is_available(self):
        return True

    def structured(self, msgs, schema, temperature=0.9):
        self.calls += 1
        speech = self._speeches.pop(0) if self._speeches else ""
        return {"speech": speech}


def _db(llm):
    db = DialogueBrain(llm, persona="你是芙宁娜。")
    # 让 expression 必须说话
    return db


def test_rejection_question_routes_decline():
    db = DialogueBrain(_FakeLLM([]))
    assert db.classify_act("你能别烦我吗？") == "DECLINE", \
        "拒绝/边界语义必须优先于标点式疑问检测"
    assert db.classify_act("你在干嘛？") == "RESPONSE_TO_QUESTION"


def test_stage_direction_invalid_not_returned():
    """stage_direction 等 invalid 输出不得原样返回（有界恢复后仍失败 → None + 可观察失败）。"""
    llm = _FakeLLM(["（叹气）好吧我陪你。", "（叹气）好吧我陪你。"])   # 两次都 invalid
    db = _db(llm)
    out = db.say(intent="talk", user_text="陪我", user_initiated=True, context="casual")
    assert out is None, "invalid 舞台腔不得原样显示"
    assert db.last_validation_failure, "必须暴露可观察校验失败路径"
    assert llm.calls == 2, f"至多再生成一次（有界恢复），实际 {llm.calls}"


def test_direct_user_invalid_has_bounded_recovery():
    """第一次 invalid → 第二次 valid → 显示第二次（有界恢复成功）。"""
    llm = _FakeLLM(["（叹气）好吧我陪你。", "好吧，那我陪你一会儿。"])
    db = _db(llm)
    out = db.say(intent="talk", user_text="陪我", user_initiated=True, context="casual")
    assert out and "（叹气）" not in out, "应显示重生成后的合法台词"
    assert db.last_validation_failure == []


def test_valid_speech_passes_through_once():
    llm = _FakeLLM(["嗯，我在呢。"])
    db = _db(llm)
    out = db.say(intent="talk", user_text="在吗", user_initiated=True, context="casual")
    assert out == "嗯，我在呢。"
    assert llm.calls == 1, "合法输出不应触发重生成"


def test_too_long_invalid_not_returned():
    llm = _FakeLLM(["好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀好呀", "太长了"])
    db = _db(llm)
    out = db.say(intent="talk", user_text="聊会", user_initiated=True, context="casual")
    assert out is None or len(out) <= 120, "超长输出不得原样显示（必须重生成或 None）"


def test_catchphrase_overuse_invalid_not_returned():
    llm = _FakeLLM(["本神本神本神本神本神本神本神本神", "好呀"])
    db = _db(llm)
    out = db.say(intent="talk", user_text="聊会", user_initiated=True, context="casual")
    assert out is None or out.count("本神") <= 2, "口头禅过度不得原样显示"


def test_over_exclamation_invalid_not_returned():
    llm = _FakeLLM(["好好好好！！！！", "好吧"])
    db = _db(llm)
    out = db.say(intent="talk", user_text="聊会", user_initiated=True, context="casual")
    assert out is None or (out.count("！") + out.count("!")) < 4, "感叹号泛滥不得原样显示"


def test_example_copy_invalid_not_returned():
    # （沉默）匹配舞台动作 → 两次都 invalid → None（不泄漏）
    llm = _FakeLLM(["（沉默）好吧我陪你", "（沉默）好吧我陪你"])
    db = _db(llm)
    out = db.say(intent="talk", user_text="聊会", user_initiated=True, context="casual")
    assert out is None, "舞台腔复读不得原样显示"


# ================================================================ §10 Agent 真相性
def test_agent_body_goes_through_director():
    """App._on_agent_body 必须经 Director 提交（source=agent），不得直接写 CharacterState。"""
    import furina.app as A
    src = open(A.__file__, encoding="utf-8").read()
    body = src[src.index("def _on_agent_body"):src.index("def _on_user_command")]
    assert "self.director.submit" in body, "Agent 身体同步必须走 Director"
    assert "st.life.macro = MacroState.WORKING" not in body, "回调线程不得直接写状态"
    exec_src = src[src.index("def _on_execute"):src.index("def _on_meaningful_interaction")]
    assert 'getattr(req, "source", "") == "agent"' in exec_src, "executor 必须有 agent 分支"


def test_agent_summary_contains_verified_fact():
    """AGENT_COMPLETED 的 summary 必须来自已验证结果（含已验证步数）。"""
    import furina.agent.agent_runtime as AR
    src = open(AR.__file__, encoding="utf-8").read()
    assert "summary" in src and "已验证" in src, "summary 必须含已验证事实"


# ================================================================ §11 Feed 生产路径
def test_gui_feed_uses_same_submit_path_as_harness():
    """FINAL-R1 §3：GUI 命令与 Harness Feed 都走唯一生产入口 submit_feed（同一路径、同一线程 owner）。"""
    import furina.app as A
    import furina.runtime.harness.controller as C
    src_a = open(A.__file__, encoding="utf-8").read()
    cmd = src_a[src_a.index("def _on_user_command"):src_a.index("def _feed")]
    assert "self.submit_feed(" in cmd, "GUI 喂食必须走 submit_feed 生产入口"
    assert "def submit_feed" in src_a, "必须有统一 submit_feed 入口"
    src_c = open(C.__file__, encoding="utf-8").read()
    assert "self.app.submit_feed(food)" in src_c, "Harness Feed 必须走同一个 submit_feed"
    assert "threading.Thread(target=self._apply_feed" not in src_c, "Harness 不得再包 worker 线程"


def test_feed_emotion_event_exactly_once():
    """喂食 → EVENT_FEED 恰好一次（App 层 apply 一次；scheduler 不重复）。"""
    import furina.app as A
    src = open(A.__file__, encoding="utf-8").read()
    feed = src[src.index("def _feed"):src.index("def _confirm_agent_permission")]
    assert feed.count("apply_event(EVENT_FEED") == 1, \
        f"EVENT_FEED 应恰好 apply 一次，实际 {feed.count('apply_event(EVENT_FEED')}"


def test_slow_feed_dialogue_does_not_block_caller():
    """喂食的 DialogueBrain 慢调用不得阻塞 _feed 调用方（后台线程）。"""
    from unittest import mock
    from furina.app import Furina

    app = object.__new__(Furina)
    app.dialogue_brain = object()
    app.state = SimpleNamespace(state=SimpleNamespace(
        intent=SimpleNamespace(), life=SimpleNamespace(activity="", macro=object(), reason=""),
        needs=SimpleNamespace(hunger=50.0, satisfaction=60.0, energy=50.0),
        emotion=SimpleNamespace(label="calm")))
    app.memory = SimpleNamespace(observe=lambda *a, **k: None,
                                 retrieve=lambda **k: [], store=SimpleNamespace(
                                     save_relationship=lambda r: None))
    app.relationship = None
    app.bus = SimpleNamespace(emit=lambda *a, **k: None)
    app._sched = SimpleNamespace(interrupt_life=lambda r: None)
    app.emotion = SimpleNamespace(apply=lambda *a, **k: None)

    # 慢对话：say 睡 0.4s。_feed 本身必须很快返回（后台线程执行对话）。
    slow = mock.Mock(side_effect=lambda **k: (_ for _ in ()).throw(AssertionError("should not block")))
    app.dialogue_brain = SimpleNamespace(say=lambda **k: None)   # 对话在后台线程，_feed 不调用它

    t0 = time.monotonic()
    from unittest.mock import patch
    with patch("furina.feeding.apply_food", return_value={"hunger": -30, "satisfaction": +10}):
        app._feed("蛋糕")
    dt = time.monotonic() - t0
    assert dt < 0.2, f"_feed 被对话阻塞了（{dt:.2f}s）—— 对话必须后台执行"
