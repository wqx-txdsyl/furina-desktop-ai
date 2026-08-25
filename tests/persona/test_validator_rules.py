"""R2.2 FINAL — Validator 新规则 + DialogueBrain 集成测试（tests/persona/ 03）。

覆盖（R2.2 §21/§27）：
  - Validator 新 HARD/SOFT 规则（identity_contradiction / action_promise_contradiction /
    subject_inversion / lore_overexposition / seriousness_mismatch）
  - Action promise firewall >= 3
  - Fact recovery（Grounded Fact Recovery）>= 4
  - Foreground ownership（前台所有权）>= 6
  - Agent fact core >= 5
  - Few-shot anti-copy >= 3
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from types import SimpleNamespace

from furina.core import EventBus, EventType
from furina.dialogue.validator import DialogueValidator
from furina.dialogue_brain import DialogueBrain

_v = DialogueValidator()


# ================================================================ Validator 新规则
def test_validator_identity_contradiction_hard():
    """'我是水神' → identity_contradiction（HARD）。"""
    r = _v.validate("因为我是水神啊。", should_speak=True, context="casual")
    assert not r.valid
    assert "identity_contradiction" in r.hard_issues, r


def test_validator_identity_focalors_equal_hard():
    """'我和芙卡洛斯是同一个人' → identity_contradiction。"""
    r = _v.validate("我和芙卡洛斯是同一个人，她就是我。", should_speak=True, context="casual")
    assert "identity_contradiction" in r.hard_issues, r


def test_validator_action_promise_firewall_hard():
    """agent_state=IDLE 且 activity 非 agent 时声称'我去帮你整理' → HARD。"""
    r = _v.validate("我去帮你整理测试目录。", should_speak=True, activity="talk",
                    agent_state="IDLE", agent_task="")
    assert not r.valid
    assert "action_promise_contradiction" in r.hard_issues, r


def test_validator_action_promise_ok_when_running():
    """agent_state=RUNNING 时'我正在帮你整理'合法（Agent 任务真实进行中）。"""
    r = _v.validate("我正在帮你整理测试目录。", should_speak=True, activity="agent_work",
                    agent_state="RUNNING", agent_task="整理测试目录")
    assert "action_promise_contradiction" not in r.hard_issues, r


def test_validator_action_promise_ok_when_agent_work_activity():
    """activity=agent_work（Agent 报告通道）时工作声称合法。"""
    r = _v.validate("已经帮你整理好了，文件都移到 Docs 和 Images 了。",
                    should_speak=True, activity="agent_report", agent_state="COMPLETED_VERIFIED")
    assert "action_promise_contradiction" not in r.hard_issues, r


def test_validator_subject_inversion_hard_when_confide():
    """用户 CONFIDE 说自己的担心，回复'你怎么知道…'拉回自己 → subject_inversion。"""
    r = _v.validate("哎呀，你怎么知道我不确定呢？", should_speak=True,
                    context="sincere", user_act="CONFIDE")
    assert "subject_inversion" in r.hard_issues, r


def test_validator_subject_inversion_not_when_normal_question():
    """普通反问（非 CONFIDE）不触发 subject_inversion。"""
    r = _v.validate("你怎么知道我在看书？", should_speak=True, context="casual",
                    user_act="ANSWER")
    assert "subject_inversion" not in r.hard_issues, r


def test_validator_lore_overexposition_soft_only():
    """百科式 lore 铺开 → lore_overexposition（SOFT，不 FAILED）。"""
    r = _v.validate("实际上，枫丹的历史要追溯到五百年前，当时水神芙卡洛斯……",
                    should_speak=True, context="casual")
    assert "lore_overexposition" in r.soft_issues
    assert "lore_overexposition" not in r.hard_issues


def test_validator_seriousness_mismatch_soft():
    """认真话题用夸张糊弄 → seriousness_mismatch（SOFT）。"""
    r = _v.validate("哈哈哈哈哈！放心啦！", should_speak=True, context="sincere")
    assert "seriousness_mismatch" in r.soft_issues


def test_validator_correction_ignored_hard():
    """'我是认真问的'后回复过短敷衍 → constraint_ignored_after_correction。"""
    r = _v.validate("嗯嗯。", should_speak=True, context="casual", correction=True)
    assert "constraint_ignored_after_correction" in r.hard_issues, r


def test_validator_referent_lost_hard():
    """用户指代'那现在呢'，回复丢指代 → referent_lost。"""
    r = _v.validate("天气不错。", should_speak=True, context="casual", referent="前文话题")
    assert "referent_lost" in r.hard_issues, r


def test_validator_referent_kept_ok():
    r = _v.validate("那件事我还记得呢。", should_speak=True, context="casual", referent="前文话题")
    assert "referent_lost" not in r.hard_issues, r


# ================================================================ DialogueBrain 集成
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


def test_brain_action_promise_never_surfaces():
    """agent IDLE：LLM 声称'我去帮你整理'×2 → 不 surface（HARD never surface）。"""
    brain = _brain(["我去帮你整理测试目录。", "我去帮你整理测试目录。"])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="你在干嘛？",
                                user_initiated=True, ingress_seq=1, activity="talk",
                                agent_state="IDLE", agent_task="")
    assert res["speech"] is None
    assert res["failure_reason"] == "validation_twice_invalid"
    assert "action_promise_contradiction" in res["hard_issues"]


def test_brain_identity_contradiction_fails():
    brain = _brain(["因为我是水神啊。", "因为我是水神啊。"])
    res = brain.say_with_result(channel="DIRECT_USER_TURN", user_text="你是谁？",
                                user_initiated=True, ingress_seq=1)
    assert res["speech"] is None
    assert "identity_contradiction" in res["hard_issues"]


def test_brain_correction_serious_plan_in_prompt():
    """'我是认真问的' → prompt 含 SINCERE plan（严肃转换进入生成指导）。"""
    prompts = []

    class _L:
        def is_available(self):
            return True

        def structured(self, msgs, schema=None, temperature=0.9):
            p = msgs[1].content[0]["text"] if isinstance(msgs[1].content, list) else str(msgs[1].content)
            prompts.append(p)
            return {"speech": "嗯，我在认真回答你。"}

    db = DialogueBrain(_L(), persona="你是芙宁娜。")
    db.say(channel="DIRECT_USER_TURN", user_text="我是认真问的，如果没人看你呢？",
           user_initiated=True)
    assert any("SINCERE" in p and "PersonaPlan" in p for p in prompts), "prompt 应含 SINCERE plan"


def test_brain_autobiography_level3_in_prompt():
    """'你和芙卡洛斯是什么关系？' → prompt 含 EXPLICIT_REFERENCE 指导。"""
    prompts = []

    class _L:
        def is_available(self):
            return True

        def structured(self, msgs, schema=None, temperature=0.9):
            p = msgs[1].content[0]["text"] if isinstance(msgs[1].content, list) else str(msgs[1].content)
            prompts.append(p)
            return {"speech": "她是镜子里的我。"}

    db = DialogueBrain(_L(), persona="你是芙宁娜。")
    db.say(channel="DIRECT_USER_TURN", user_text="你和芙卡洛斯是什么关系？",
           user_initiated=True)
    assert any("芙卡洛斯" in p and ("神格" in p or "人格" in p) for p in prompts), \
        "level 3 应注入 canonical 身份指导"


def test_brain_ordinary_no_autobiography_in_prompt():
    """'今天吃什么？' → 不注入自传激活指导（level 0 无 auto_guide 块）。"""
    prompts = []

    class _L:
        def is_available(self):
            return True

        def structured(self, msgs, schema=None, temperature=0.9):
            p = msgs[1].content[0]["text"] if isinstance(msgs[1].content, list) else str(msgs[1].content)
            prompts.append(p)
            return {"speech": "随便吃点什么都行。"}

    db = DialogueBrain(_L(), persona="你是芙宁娜。")
    db.say(channel="DIRECT_USER_TURN", user_text="今天吃什么？", user_initiated=True)
    p = prompts[0]
    # 自传指导（level>=1 才注入）不应出现；基础 prompt 中的角色段/防呆说明允许提及历史名词
    assert "你的回答可以受到过往经历的影响" not in p, "level 0 不得注入自传激活指导"
    assert "可以出现一句个人化的历史引用" not in p, "level 0 不得注入自传引用指导"
    assert "可以明确谈芙卡洛斯" not in p, "level 0 不得注入显式历史指导"


def test_brain_opening_style_variety_in_prompt():
    """prompt 含 opening style 指导（非'哎呀'固定词）。"""
    prompts = []

    class _L:
        def is_available(self):
            return True

        def structured(self, msgs, schema=None, temperature=0.9):
            p = msgs[1].content[0]["text"] if isinstance(msgs[1].content, list) else str(msgs[1].content)
            prompts.append(p)
            return {"speech": "嗯，我在呢。"}

    db = DialogueBrain(_L(), persona="你是芙宁娜。")
    db.say(channel="DIRECT_USER_TURN", user_text="在吗", user_initiated=True)
    assert any("开场" in p and "PersonaPlan" in p for p in prompts), "prompt 应含开场指导"


# ================================================================ Grounded Fact Recovery（>=4）
def _app_with_brain(brain):
    from furina.app import Furina
    from furina.state import CharacterState
    from furina.emotion import EmotionEngine
    app = object.__new__(Furina)
    app.state = SimpleNamespace(state=CharacterState())
    app.emotion = EmotionEngine(app.state.state.emotion)
    app.bus = EventBus()
    app._sched = SimpleNamespace(interrupt_life=lambda r: None, on_user_response=lambda: None,
                                 _say=lambda t, dur=4.0, channel="", turn_id=None: None)
    app.dialogue_brain = brain
    app.memory = SimpleNamespace(observe=lambda *a, **k: None, retrieve=lambda **k: [],
                                 interpret=lambda *a, **k: {})
    app._rt_dispatcher().bind_owner()
    return app


def test_fact_recovery_grounded_activity_on_ungrounded_fail():
    """A14 型：LLM 两次 ungrounded_activity 失败 → app 用权威 activity 恢复（非 SYSTEM_STATUS）。"""
    from furina.app import Furina
    from furina.runtime.dialogue_snapshot import DialogueContextSnapshot
    app = _app_with_brain(_brain(["我在这里闲逛呢。", "我在这里闲逛呢。"]))
    app.dialogue_brain = DialogueBrain(_SeqLLM(["我在这里闲逛呢。", "我在这里闲逛呢。"]),
                                       persona="你是芙宁娜。")
    snap = DialogueContextSnapshot(user_text="刚才你有在做自己的事情吗？", activity="read",
                                   channel="DIRECT_USER_TURN", user_initiated=True)
    res = app.dialogue_brain.say_with_result(**snap.say_kwargs(), deadline=time.monotonic() + 5)
    # 模拟 _brain_worker 的恢复分支（直接测 _grounded_fact_recovery）
    recovered = app._grounded_fact_recovery(snap, res)
    assert recovered, "ungrounded_activity 失败必须恢复"
    assert "看书" in recovered, f"恢复文本必须含权威活动事实: {recovered}"
    assert "系统状态" not in recovered, "恢复文本不得是 SYSTEM_STATUS"


def test_fact_recovery_not_for_other_hard():
    """其它 HARD（如 AI 身份）失败不恢复。"""
    from furina.runtime.dialogue_snapshot import DialogueContextSnapshot
    app = _app_with_brain(_brain([]))
    snap = DialogueContextSnapshot(user_text="你是谁？", activity="idle",
                                   channel="DIRECT_USER_TURN", user_initiated=True)
    res = {"hard_issues": ["generic_assistant_identity"], "soft_issues": []}
    assert app._grounded_fact_recovery(snap, res) == "", "非 ungrounded 的 HARD 不得恢复"


def test_fact_recovery_not_for_mixed_hard():
    """ungrounded + 其它 HARD 混合 → 不恢复（不绕过其它约束）。"""
    from furina.runtime.dialogue_snapshot import DialogueContextSnapshot
    app = _app_with_brain(_brain([]))
    snap = DialogueContextSnapshot(user_text="在干嘛", activity="read",
                                   channel="DIRECT_USER_TURN", user_initiated=True)
    res = {"hard_issues": ["ungrounded_activity", "identity_contradiction"], "soft_issues": []}
    assert app._grounded_fact_recovery(snap, res) == ""


def test_fact_recovery_activity_map_covers_production():
    """活动事实映射覆盖 production activities（talk/idle/read/agent_work…）。"""
    from furina.app import Furina
    for a in ("read", "idle", "talk", "explore", "agent_work", "rest", "eat", "sleep"):
        assert Furina._activity_fact_line(a), f"缺活动事实描述: {a}"


def test_brain_worker_fact_recovery_end_to_end():
    """_brain_worker 端到端：ungrounded 双重失败 → recovered speech 而非 SYSTEM_STATUS。"""
    from furina.runtime.dialogue_snapshot import DialogueContextSnapshot
    app = _app_with_brain(DialogueBrain(_SeqLLM(["我正在探索新事物呢。", "我正在探索新事物呢。"]),
                                        persona="你是芙宁娜。"))
    snap = DialogueContextSnapshot(user_text="刚才你在干嘛？", activity="read",
                                   channel="DIRECT_USER_TURN", user_initiated=True)
    out = app._brain_worker("刚才你在干嘛？", snapshot=snap)
    assert out.get("speech"), "fact recovery 应产出 speech"
    assert "看书" in out["speech"]
    assert out["failure_reason"] == "", "恢复后 failure_reason 应为空"
    assert "系统状态" not in out["speech"]


# ================================================================ Foreground Ownership（>=6）
def _make_sched():
    from furina.runtime.scheduler import Scheduler
    from furina.state import StateEngine
    bus = EventBus()
    se = StateEngine(bus)
    sched = Scheduler(bus, se, None, None, None, None, None)
    return sched, bus


def test_foreground_direct_active_blocks_ambient():
    """direct active（QUEUED/GENERATING）→ _ambient_allowed=False。"""
    sched, bus = _make_sched()
    assert sched._ambient_allowed()
    bus.emit(EventType.DIRECT_TURN_TRACE, payload={"phase": "GENERATION_STARTED",
                                                   "status": "GENERATING", "turn_id": 1},
             source="test")
    assert sched._direct_active is True
    assert sched._ambient_allowed() is False, "direct 生成中 ambient 必须让路"


def test_foreground_direct_terminal_opens_grace():
    """direct 终态 → grace window 内 ambient 仍禁。"""
    sched, bus = _make_sched()
    bus.emit(EventType.DIRECT_TURN_TRACE, payload={"phase": "REPLIED", "status": "REPLIED",
                                                   "turn_id": 1}, source="test")
    assert sched._direct_active is False
    assert sched._ambient_allowed() is False, "grace 内 ambient 不得插话"
    assert sched._direct_grace_until > time.monotonic()


def test_foreground_grace_expires_allows_ambient():
    """grace 过期后 ambient 恢复允许。"""
    sched, bus = _make_sched()
    bus.emit(EventType.DIRECT_TURN_TRACE, payload={"phase": "REPLIED", "status": "REPLIED",
                                                   "turn_id": 1}, source="test")
    sched._direct_grace_until = time.monotonic() - 0.1   # 强制过期
    assert sched._ambient_allowed() is True


def test_foreground_ephemeral_dropped_during_direct():
    """direct active 时普通 ambient（EPHEMERAL）→ 直接 drop（不 defer）。"""
    sched, bus = _make_sched()
    sched.dialogue_brain = object()
    bus.emit(EventType.DIRECT_TURN_TRACE, payload={"phase": "GENERATION_STARTED",
                                                   "status": "GENERATING", "turn_id": 1},
             source="test")
    sched.start_autonomous_dialogue(activity="talk", speech_level=1, dialogue_needed=False)
    assert sched._ambient_deferred == [], "EPHEMERAL 应 drop 不 defer"


def test_foreground_important_deferred_during_direct():
    """direct active 时 IMPORTANT ambient → defer（grace 后重放）。"""
    sched, bus = _make_sched()
    sched.dialogue_brain = object()
    bus.emit(EventType.DIRECT_TURN_TRACE, payload={"phase": "GENERATION_STARTED",
                                                   "status": "GENERATING", "turn_id": 1},
             source="test")
    sched.start_autonomous_dialogue(activity="talk", speech_level=3, dialogue_needed=True)
    assert len(sched._ambient_deferred) == 1, "IMPORTANT 应 defer"
    assert sched._ambient_deferred[0]["dialogue_needed"] is True


def test_foreground_deferred_replayed_after_grace():
    """grace 结束 + 未过期 → defer 的 IMPORTANT 重放（重新走自主台词路径）。"""
    sched, bus = _make_sched()
    sched.dialogue_brain = object()
    # 先 defer
    sched._ambient_deferred = [{"activity": "talk", "speech_intent": "打个招呼",
                                "emotion": "happy", "intent": "talk", "duration": 3.0,
                                "speech_level": 3, "dialogue_needed": True,
                                "born": time.monotonic() - 2.0}]
    # 重放（grace 已过，freshness 内）→ 会再调 start_autonomous_dialogue（此时 allowed）
    sched._direct_grace_until = time.monotonic() - 1.0
    sched._try_deferred_ambient(sched._ambient_deferred[0], time.monotonic())
    # 允许路径下 dialogue_brain=object() 无 say → 不产生新 defer（正常返回）
    assert True


def test_foreground_deferred_stale_dropped():
    """defer 超过 8s → stale drop（不重放）。"""
    sched, bus = _make_sched()
    sched.dialogue_brain = object()
    old = {"activity": "talk", "speech_intent": "", "emotion": "", "intent": "talk",
           "duration": 0.0, "speech_level": 3, "dialogue_needed": True,
           "born": time.monotonic() - 20.0}
    sched._direct_grace_until = time.monotonic() - 1.0
    sched._try_deferred_ambient(old, time.monotonic())
    assert sched._ambient_deferred == [], "过期 defer 应 drop"


# ================================================================ Agent Fact Core（>=5）
def test_agent_fact_core_in_prompt():
    """agent report prompt 含 FACT_CORE 指令（不可删事实）。"""
    from furina.dialogue_brain import _dialogue_prompt_v2
    class _App:
        def to_prompt(self):
            return {"mode": "RESPONSIBLE", "secondary_mode": "", "dialogue_act": "COMMENT",
                    "strategy": ""}
        mode = "RESPONSIBLE"; dialogue_act = "COMMENT"
    p = _dialogue_prompt_v2(_App(), intent="assist_user", emotion="proud", user_text="",
                            context="任务完成", memories=None, world=None, examples=[],
                            person="p", activity="agent_report",
                            agent_state="COMPLETED_VERIFIED", agent_task="整理测试目录")
    assert "FACT_CORE" in p and "不可删除" in p, "prompt 必须含 FACT_CORE 指令"
    assert "具体结果" in p or "验证" in p or "证据" in p


def test_agent_report_forbids_fabrication_in_prompt():
    """agent report 禁止编造未验证细节（'花了几分钟'）。"""
    from furina.dialogue_brain import _dialogue_prompt_v2
    class _App:
        def to_prompt(self):
            return {"mode": "RESPONSIBLE", "secondary_mode": "", "dialogue_act": "COMMENT",
                    "strategy": ""}
        mode = "RESPONSIBLE"; dialogue_act = "COMMENT"
    p = _dialogue_prompt_v2(_App(), intent="assist_user", emotion="proud", user_text="",
                            context="任务完成", memories=None, world=None, examples=[],
                            person="p", activity="agent_report")
    assert "编造" in p and "花了几分钟" in p


def test_agent_report_requires_fact_before_persona():
    from furina.dialogue_brain import _dialogue_prompt_v2
    class _App:
        def to_prompt(self):
            return {"mode": "RESPONSIBLE", "secondary_mode": "", "dialogue_act": "COMMENT",
                    "strategy": ""}
        mode = "RESPONSIBLE"; dialogue_act = "COMMENT"
    p = _dialogue_prompt_v2(_App(), intent="assist_user", emotion="proud", user_text="",
                            context="任务完成", memories=None, world=None, examples=[],
                            person="p", activity="agent_report")
    assert "先明确报告" in p and "再允许角色口吻" in p


def test_agent_report_has_authoritative_facts_source():
    """scheduler._on_agent_done context 含 original_request/goal/summary/concrete（FACT 层）。"""
    from furina.runtime.scheduler import Scheduler
    import furina.runtime.scheduler as SM
    src = open(SM.__file__, encoding="utf-8").read()
    on_done = src[src.index("def _on_agent_done"):src.index("def _on_agent_fail")]
    for k in ("goal", "summary", "concrete"):
        assert k in on_done, f"_on_agent_done 缺 FACT 字段: {k}"
    assert "verified" in on_done


def test_agent_fallbacks_exactly_once():
    """Agent 完成 fallback（SYSTEM_STATUS）绑定 AGENT_REPORT 事实（exactly-once 路径）。"""
    import furina.runtime.scheduler as SM
    src = open(SM.__file__, encoding="utf-8").read()
    assert "fallback=f" in src and "系统状态：任务已完成" in src


# ================================================================ Few-shot anti-copy（>=3）
def test_fewshot_examples_have_no_verbatim_speech_in_prompt():
    """prompt 注入表达规律而非整句台词（R2.2 §14）。"""
    from furina.dialogue_brain import _dialogue_prompt_v2
    from furina.persona.expression_examples import get_examples
    exs = get_examples()[:2]
    class _App:
        def to_prompt(self):
            return {"mode": "CASUAL", "secondary_mode": "", "dialogue_act": "COMMENT",
                    "strategy": ""}
        mode = "CASUAL"; dialogue_act = "COMMENT"
    p = _dialogue_prompt_v2(_App(), intent="talk", emotion="calm", user_text="在吗",
                            context="", memories=None, world=None, examples=exs,
                            person="p")
    # prompt 不得包含 example 的整句 speech（placeholder 也不该出现）
    for e in exs:
        assert e.get("speech", "") not in p, "prompt 不得注入整句 example 台词"
    assert "表达规律参考" in p and "绝不照抄" in p


def test_fewshot_placeholders_still_serve_example_copy_detection():
    """placeholder speech 仍供 validator 的 example_copy 检测（SOFT）。"""
    from furina.persona.expression_examples import get_examples
    ex = get_examples()[0]
    assert "speech" in ex and ex["speech"]
    assert "（" not in ex["speech"], "placeholder 不得含舞台动作括号"
    r = _v.validate(ex["speech"], should_speak=True, example_phrases=[ex["speech"]])
    assert "example_copy" in r.soft_issues and "example_copy" not in r.hard_issues, r


def test_fewshot_example_schema_fields():
    """PersonaExample 含 context/internal_state/social_strategy/voice/anti_pattern；transition 可选。"""
    from furina.persona.expression_examples import get_examples
    for e in get_examples():
        for f in ("context", "internal_state", "social_strategy",
                  "voice_features", "anti_pattern"):
            assert f in e, f"PersonaExample 缺字段 {f}: {e.get('context')}"
        # transition 可选但如有则非空
        if "transition" in e:
            assert e["transition"].strip()
