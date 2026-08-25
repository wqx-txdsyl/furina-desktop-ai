"""R2.2.1 Contract Closure 专项测试（tests/persona/ 05）。

覆盖 R2.2.1 要求的 12 项 contract：
  1. real RelationshipState initial factors 不造成 all-GUARDED
  2. correction 在 trust=0 下仍 SINCERE
  3. Runtime FURINA_PERSONA 真正来自 Canon
  4. old identity contradiction 不再存在
  5. PersonaPlan 唯一 mode authority
  6. Agent FACT_CORE 漏事实时 deterministic 保留
  7. Agent 禁编 duration
  8. IMPORTANT ambient grace 后真实 replay
  9. stale ambient drop
  10. 5 rapid Direct 无 ambient 插话
  11. P21→P22 semantic referent
  12. current vs recent activity recovery
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from types import SimpleNamespace

from furina.core import EventBus, EventType
from furina.relationship.engine import RelationshipEngine, relationship_factors


# ================================================================ 1. 真实初值不 all-GUARDED
def test_1_real_relationship_initial_not_all_guarded():
    """R2.2.1 FINAL：真实 RelationshipState() 初值（trust=0）逐案断言（弃用 distinct_modes>=3 证明）。"""
    from furina.persona.persona_planner import plan_for
    fac = relationship_factors(RelationshipEngine().state)
    assert fac["trust"] == 0.0 and fac["annoyance"] == 0.0, fac
    # 逐案：普通 COMMENT → CASUAL；ANSWER → CASUAL；PRAISE → PROUD；
    # CHALLENGE → GUARDED；correction → SINCERE；action → RESPONSIBLE
    assert plan_for("今天有点热", trust=0.0, familiarity=0.0, annoyance=0.0).mode == "CASUAL"
    assert plan_for("你在干嘛？", trust=0.0, familiarity=0.0, annoyance=0.0).mode == "CASUAL"
    assert plan_for("你今天很好看", trust=0.0, familiarity=0.0, annoyance=0.0).mode == "PROUD"
    assert plan_for("你是不是在装？", trust=0.0, familiarity=0.0, annoyance=0.0).mode == "GUARDED"
    assert plan_for("我是认真问的，没人看你你会怎么办？",
                    trust=0.0, familiarity=0.0, annoyance=0.0).mode == "SINCERE"
    assert plan_for("帮我打开记事本", trust=0.0, familiarity=0.0, annoyance=0.0).mode == "RESPONSIBLE"
    # 低 trust 仍降 intimacy
    assert plan_for("今天有点热", trust=0.0, familiarity=0.0, annoyance=0.0).intimacy_level <= 0.35


# ================================================================ 2. correction trust=0 SINCERE
def test_2_correction_sincere_at_trust_zero_drama_drops():
    from furina.persona.persona_planner import plan_for
    playful = plan_for("如果大家不关注你了，你会怎么办？", trust=0.0, familiarity=0.0,
                       annoyance=0.0, emotion="happy")
    serious = plan_for("如果大家不关注你了，你会怎么办？我是认真问的。", trust=0.0,
                       familiarity=0.0, annoyance=0.0, emotion="happy")
    assert serious.mode == "SINCERE"
    assert serious.dramatic_intensity <= playful.dramatic_intensity + 1e-9


# ================================================================ 3/4. Single Canon Authority
def test_3_runtime_furina_persona_from_canon():
    from furina.persona import FURINA_PERSONA
    from furina.persona.furina_canon import SYSTEM_PERSONA
    assert FURINA_PERSONA is SYSTEM_PERSONA, "Runtime persona 必须就是 Canon SYSTEM_PERSONA"
    assert "神格侧" in FURINA_PERSONA and "人格侧" in FURINA_PERSONA


def test_4_old_identity_contradiction_gone():
    """旧平行 truth（'曾以水神芙卡洛斯之名…'）不得存在于 Runtime imported FURINA_PERSONA。"""
    from furina.persona import FURINA_PERSONA
    assert "以" not in FURINA_PERSONA or "芙卡洛斯之名" not in FURINA_PERSONA, \
        "不得再出现 Furina==Focalors 表述"
    assert "你曾以" not in FURINA_PERSONA
    # 正确表述：扮演公众眼中的水神；芙卡洛斯是神格侧
    assert "扮演公众眼中的'水神'" in FURINA_PERSONA or "扮演公众认为的水神" in FURINA_PERSONA


def test_4b_character_identity_derives_from_canon():
    from furina.persona.character_identity import FURINA_IDENTITY
    from furina.persona.furina_canon import PERSONALITY_AXES
    # Furina 行为层关键值必须来自 Canon axes（adapter）
    assert abs(FURINA_IDENTITY.dramatic_self_presentation -
               PERSONALITY_AXES["theatricality"]["default"]) < 1e-9
    assert abs(FURINA_IDENTITY.need_to_maintain_dignity -
               PERSONALITY_AXES["dignity"]["default"]) < 1e-9
    assert abs(FURINA_IDENTITY.desire_to_be_recognized -
               PERSONALITY_AXES["attention_sensitivity"]["default"]) < 1e-9


def test_4c_contract_derives_from_canon():
    from furina.persona.furina_character_contract import CONTRADICTIONS
    from furina.persona.furina_canon import CORE_CONTRADICTIONS
    assert len(CONTRADICTIONS) == len(CORE_CONTRADICTIONS)
    # 不维护平行 contradiction 集
    assert all("↔" in c for c in CONTRADICTIONS)


# ================================================================ 5. PersonaPlan 唯一 mode authority
def test_5_plan_mode_is_final_authority_in_prompt():
    from furina.dialogue_brain import _dialogue_prompt_v2
    from furina.persona.persona_planner import plan_for

    class _App:
        mode = "PLAYFUL"
        dialogue_act = "BOAST"

        def to_prompt(self):
            return {"mode": "PLAYFUL", "secondary_mode": "", "dialogue_act": "BOAST",
                    "strategy": "x"}

    plan = plan_for("我是认真问的，没人看你你会怎么办？")
    assert plan.mode == "SINCERE"
    p = _dialogue_prompt_v2(_App(), intent="talk", emotion="calm",
                            user_text="我是认真问的，没人看你你会怎么办？",
                            context="", memories=None, world=None, examples=[], person="p",
                            plan=plan, auto_guide="")
    assert "mode=SINCERE" in p, "prompt 必须只把 SINCERE 作为输出 mode authority"
    assert "mode=PLAYFUL" not in p, "不得同时告诉 LLM mode=PLAYFUL（平行 mode）"


# ================================================================ 6/7. Agent FACT_CORE deterministic
def _agent_snap(facts=None):
    from furina.runtime.dialogue_snapshot import DialogueContextSnapshot, freeze_flat
    af = facts or {"goal": "整理测试目录", "terminal_status": "COMPLETED_VERIFIED",
                   "verified": True, "summary": "完成了 5/5",
                   "concrete_evidence": "notes.md→Docs; image.png→Images",
                   "has_duration_evidence": False}
    return DialogueContextSnapshot(agent_facts=freeze_flat(af), activity="agent_report",
                                   channel="AGENT_REPORT")


def test_6_fact_core_deterministic_when_persona_misses_facts():
    from furina.runtime.scheduler import Scheduler
    fn = Scheduler._ensure_agent_fact_core
    out = fn("哼，这点小事当然难不倒我。", _agent_snap())
    assert "完成" in out and "整理测试目录" in out, f"漏事实必须 deterministic 保留: {out}"
    assert "Docs" in out and "Images" in out, f"具体证据必须保留: {out}"
    assert "验证" in out, f"verified 事实必须保留: {out}"


def test_6b_fact_core_preserves_existing_complete_facts():
    from furina.runtime.scheduler import Scheduler
    fn = Scheduler._ensure_agent_fact_core
    out = fn("任务已完成：整理测试目录。已验证通过。notes.md 已移到 Docs，image.png 已移到 Images。",
             _agent_snap())
    assert out.count("具体：") == 0, "已有完整事实不得重复追加"
    assert "整理测试目录" in out and "Docs" in out and "Images" in out


def test_7_no_duration_fabrication():
    from furina.runtime.scheduler import Scheduler
    fn = Scheduler._ensure_agent_fact_core
    out = fn("办好了。也就花了几分钟吧。", _agent_snap())
    assert "分钟" not in out, f"无 duration 证据禁编时长: {out}"
    out2 = fn("弄完了，用了大概三十秒。", _agent_snap())
    assert "秒" not in out2, f"无 duration 证据禁编秒数: {out2}"


def test_7b_duration_allowed_when_evidence_exists():
    from furina.runtime.scheduler import Scheduler
    snap = _agent_snap({"goal": "整理测试目录", "terminal_status": "COMPLETED_VERIFIED",
                        "verified": True, "summary": "完成了 5/5",
                        "concrete_evidence": "notes.md→Docs",
                        "has_duration_evidence": True})
    out = Scheduler._ensure_agent_fact_core("办好了，花了几分钟。", snap)
    assert "分钟" in out, "有 duration 证据时允许时长"


# ================================================================ 8/9/10. Foreground ownership
class _FakeBrain:
    def __init__(self):
        self.calls = []

    def say(self, **kw):
        self.calls.append(dict(kw))
        return "嗯，我在这儿呢。"


def _make_sched():
    from furina.runtime.scheduler import Scheduler
    from furina.state import StateEngine
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    # 测试线程 = owner：emit 直接 apply（worker→owner 路径由专门线程测试覆盖）
    sched.dispatcher.bind_owner()
    return sched, bus


def test_8_important_deferred_replayed_after_grace():
    sched, bus = _make_sched()
    brain = _FakeBrain()
    sched.dialogue_brain = brain
    bus.emit(EventType.DIRECT_TURN_TRACE, payload={"phase": "GENERATION_STARTED",
                                                   "status": "GENERATING", "turn_id": 1},
             source="test")
    sched.start_autonomous_dialogue(activity="talk", speech_level=3, dialogue_needed=True)
    assert len(sched._ambient_deferred) == 1 and brain.calls == []
    bus.emit(EventType.DIRECT_TURN_TRACE, payload={"phase": "REPLIED", "status": "REPLIED",
                                                   "turn_id": 1}, source="test")
    assert len(sched._ambient_deferred) == 1, "terminal 后 deferred 不得丢失"
    sched._direct_grace_until = time.monotonic() - 1.0
    sched._tick_deferred_ambient(time.monotonic())
    deadline = time.monotonic() + 2.0
    while len(brain.calls) < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(brain.calls) == 1, "grace 后必须真实 replay"
    assert sched._ambient_deferred == []


def test_9_stale_deferred_dropped():
    sched, bus = _make_sched()
    brain = _FakeBrain()
    sched.dialogue_brain = brain
    sched._ambient_deferred = [{"activity": "talk", "speech_intent": "", "emotion": "",
                                "intent": "talk", "duration": 0.0, "speech_level": 3,
                                "dialogue_needed": True, "born": time.monotonic() - 20.0}]
    sched._direct_grace_until = time.monotonic() - 1.0
    sched._tick_deferred_ambient(time.monotonic())
    assert sched._ambient_deferred == [] and brain.calls == []


def test_10_5_rapid_direct_no_ambient_interruption():
    sched, bus = _make_sched()
    brain = _FakeBrain()
    sched.dialogue_brain = brain
    for tid in range(1, 6):
        bus.emit(EventType.DIRECT_TURN_TRACE, payload={"phase": "GENERATION_STARTED",
                                                       "status": "GENERATING", "turn_id": tid},
                 source="test")
        sched.start_autonomous_dialogue(activity="talk", speech_level=1, dialogue_needed=False)
        sched.start_autonomous_dialogue(activity="talk", speech_level=3, dialogue_needed=True)
        assert sched._ambient_allowed() is False
        assert brain.calls == [], f"direct active 时 ambient 不得 surface: tid={tid}"
        bus.emit(EventType.DIRECT_TURN_TRACE, payload={"phase": "REPLIED", "status": "REPLIED",
                                                       "turn_id": tid}, source="test")
        sched._tick_deferred_ambient(time.monotonic())
        assert brain.calls == [], f"grace 内 ambient 不得 surface: tid={tid}"
    sched._direct_grace_until = time.monotonic() - 1.0
    sched._tick_deferred_ambient(time.monotonic())
    deadline = time.monotonic() + 2.0
    while len(brain.calls) < 5 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(brain.calls) == 5, f"5 条 IMPORTANT 应 grace 后全部 replay: {len(brain.calls)}"
    assert sched._ambient_deferred == []


# ================================================================ 11. P21→P22 semantic referent
def test_11_p21_to_p22_semantic_referent():
    from furina.dialogue_brain import DialogueBrain

    class _L:
        def is_available(self):
            return True

        def structured(self, msgs, schema=None, temperature=0.9):
            return {"speech": "嗯。"}

    db = DialogueBrain(_L(), persona="你是芙宁娜。")
    db.say(channel="DIRECT_USER_TURN",
           user_text="你什么时候最不像平时那个夸张的自己？", user_initiated=True)
    assert db._last_semantic_topic == "平时与真实自我", db._last_semantic_topic
    plan, _ = db._plan_turn(user_text="那现在呢？", app=SimpleNamespace(mode="CASUAL"))
    assert plan.has_referent is True
    assert plan.referent == "平时与真实自我", \
        f"P22 referent 必须是前一个 semantic topic（非 Furina 自然语言文本）: {plan.referent}"
    assert "平时" in plan.referent or "真实" in plan.referent


def test_11b_semantic_topic_not_furina_speech():
    from furina.dialogue_brain import DialogueBrain

    class _L:
        def is_available(self):
            return True

        def structured(self, msgs, schema=None, temperature=0.9):
            return {"speech": "哎呀，我平时就爱这样啊。"}   # Furina 回复与 topic 无关

    db = DialogueBrain(_L(), persona="你是芙宁娜。")
    db.say(channel="DIRECT_USER_TURN", user_text="你和芙卡洛斯是什么关系？", user_initiated=True)
    assert db._last_semantic_topic == "芙卡洛斯与身份", db._last_semantic_topic
    # referent 是 semantic topic，不是 Furina 回复文本
    plan, _ = db._plan_turn(user_text="那现在呢？", app=SimpleNamespace(mode="CASUAL"))
    assert plan.referent == "芙卡洛斯与身份"
    assert "哎呀" not in plan.referent


# ================================================================ 12. current vs recent activity
def test_12_current_vs_recent_activity_recovery():
    """R2.2.1 FINAL：recovery 只读 snapshot；现在→current+'现在'；刚才→recent+'刚才'；stale 不冒充。"""
    from furina.app import Furina, RECENT_ACTIVITY_FRESHNESS_SECONDS
    from furina.runtime.dialogue_snapshot import DialogueContextSnapshot
    app = object.__new__(Furina)
    res = {"hard_issues": ["ungrounded_activity"], "soft_issues": []}
    # B: 现在 → current + "现在"文案
    snap_now = DialogueContextSnapshot(user_text="你现在在干嘛？", activity="read",
                                       channel="DIRECT_USER_TURN", user_initiated=True,
                                       recent_activity="explore",
                                       recent_activity_finished_at=time.monotonic() - 10,
                                       recent_activity_freshness=RECENT_ACTIVITY_FRESHNESS_SECONDS)
    r_now = app._grounded_fact_recovery(snap_now, res)
    assert "现在" in r_now and "看书" in r_now and "刚才" not in r_now, f"现在→current: {r_now}"
    # B: 刚才（fresh recent）→ recent + "刚才"文案
    snap_recent = DialogueContextSnapshot(user_text="刚才你在干嘛？", activity="read",
                                          channel="DIRECT_USER_TURN", user_initiated=True,
                                          recent_activity="explore",
                                          recent_activity_finished_at=time.monotonic() - 10,
                                          recent_activity_freshness=RECENT_ACTIVITY_FRESHNESS_SECONDS)
    r_recent = app._grounded_fact_recovery(snap_recent, res)
    assert "刚才" in r_recent and "四处走走" in r_recent, f"刚才→recent: {r_recent}"
    # A: snapshot freeze 后修改 live recent → recovery 不改变
    app._recent_activity = "play"     # live 修改（worker 不得读）
    app._recent_activity_finished_at = time.monotonic()
    r_recent2 = app._grounded_fact_recovery(snap_recent, res)
    assert r_recent2 == r_recent, "snapshot 冻结后 live 修改不得影响 recovery"
    # C: stale recent 不冒充"刚才"（不出现 explore）
    snap_stale = DialogueContextSnapshot(user_text="刚才你在干嘛？", activity="read",
                                         channel="DIRECT_USER_TURN", user_initiated=True,
                                         recent_activity="explore",
                                         recent_activity_finished_at=time.monotonic() - 9999,
                                         recent_activity_freshness=RECENT_ACTIVITY_FRESHNESS_SECONDS)
    r_stale = app._grounded_fact_recovery(snap_stale, res)
    assert "四处走走" not in r_stale, f"stale recent 不得冒充刚才: {r_stale}"
    assert "看书" in r_stale, "stale 回落 current"


def test_12b_recent_activity_tracked_on_execute():
    from furina.app import Furina
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=SimpleNamespace(
        life=SimpleNamespace(macro=None, activity="", reason=""),
        intent=SimpleNamespace(action="", emotion="", priority=0.0),
        emotion=SimpleNamespace(label="calm"),
        user_idle_seconds=0.0))
    app._sched = None
    # 第一次 execute（无 prev）
    app._on_execute(SimpleNamespace(action="read", source="mind", payload={}, reason="r",
                                    priority=0.5))
    assert getattr(app, "_current_activity_truth", "") == "read"
    # 第二次 execute（activity 变化 → recent 记录）
    app._on_execute(SimpleNamespace(action="explore", source="mind", payload={}, reason="r",
                                    priority=0.5))
    assert app._current_activity_truth == "explore"
    assert app._recent_activity == "read", "activity 变化应记录 recent"
    assert app._recent_activity_finished_at > 0


# ================================================================ 3. DIRECT_TURN_TRACE owner boundary
def test_3_direct_trace_worker_emit_goes_through_dispatcher():
    """R2.2.1 FINAL §3：worker 线程 emit DIRECT_TURN_TRACE → 不直接 mutation，经 dispatcher 回 owner。"""
    import threading

    from furina.runtime.scheduler import Scheduler
    from furina.state import StateEngine
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    # owner = 当前测试线程
    sched.dispatcher.bind_owner()
    # worker 线程 emit（模拟 DirectDialogueQueue worker）
    def _worker_emit():
        bus.emit(EventType.DIRECT_TURN_TRACE,
                 payload={"phase": "GENERATION_STARTED", "status": "GENERATING", "turn_id": 1},
                 source="dialogue_queue")

    t = threading.Thread(target=_worker_emit)
    t.start()
    t.join()
    # worker emit 后：状态**尚未**在 worker 线程修改（handler 走 submit 分支）
    # 由于 emit 在 worker 线程执行，_apply_direct_trace 被 submit 排队 → 需 owner drain
    assert sched.dispatcher.pending() >= 1, "worker emit 必须经 dispatcher submit"
    # drain 前 _direct_active 未变（未由 worker 直接改）
    assert sched._direct_active is False, "worker 不得直接 mutation Scheduler state"
    # owner drain → 状态正确
    sched.dispatcher.drain()
    assert sched._direct_active is True, "owner drain 后 direct_active 必须正确"
    # 无违规（dispatcher violations = 0 —— worker 未 require_owner 调用）
    assert sched.dispatcher.violations() == [], f"violations: {sched.dispatcher.violations()}"


def test_3_direct_trace_terminal_sets_grace_via_owner():
    """R2.2.1 FINAL §3：worker terminal emit → owner drain 后 grace 正确建立。"""
    import threading

    from furina.runtime.scheduler import Scheduler
    from furina.state import StateEngine
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    sched.dispatcher.bind_owner()

    def _worker_emit():
        bus.emit(EventType.DIRECT_TURN_TRACE,
                 payload={"phase": "REPLIED", "status": "REPLIED", "turn_id": 1},
                 source="dialogue_queue")

    t = threading.Thread(target=_worker_emit)
    t.start()
    t.join()
    assert sched._direct_active is False, "worker 不得直接改"
    sched.dispatcher.drain()
    assert sched._direct_active is False
    assert sched._direct_grace_until > time.monotonic(), "owner drain 后 grace 必须建立"
    assert sched.dispatcher.violations() == []


def test_3_foreground_defer_replay_still_works_with_owner():
    """R2.2.1 FINAL §3：owner 绑定下 IMPORTANT defer/replay 无回归。"""
    from furina.runtime.scheduler import Scheduler
    from furina.state import StateEngine
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    brain = _FakeBrain()
    sched.dialogue_brain = brain
    sched.dispatcher.bind_owner()
    # direct active（owner emit → 立即 apply）
    bus.emit(EventType.DIRECT_TURN_TRACE,
             payload={"phase": "GENERATION_STARTED", "status": "GENERATING", "turn_id": 1},
             source="test")
    assert sched._direct_active is True
    sched.start_autonomous_dialogue(activity="talk", speech_level=3, dialogue_needed=True)
    assert len(sched._ambient_deferred) == 1 and brain.calls == []
    # terminal（owner emit → grace）
    bus.emit(EventType.DIRECT_TURN_TRACE,
             payload={"phase": "REPLIED", "status": "REPLIED", "turn_id": 1}, source="test")
    assert len(sched._ambient_deferred) == 1, "terminal 后 deferred 不得丢失"
    # grace 过期 → drain → replay exactly-once
    sched._direct_grace_until = time.monotonic() - 1.0
    sched._tick_deferred_ambient(time.monotonic())
    deadline = time.monotonic() + 2.0
    while len(brain.calls) < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(brain.calls) == 1, "IMPORTANT 应 replay 一次"
    assert sched._ambient_deferred == []
    assert sched.dispatcher.violations() == []
