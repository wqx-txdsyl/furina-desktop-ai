"""Phase 13C C-R2 最终合同 Closeout 测试（行为级：精确数值 / 写侧 / 单route / 路由 / 无舞台动作）。"""
from __future__ import annotations

import os
import re
from types import SimpleNamespace
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from furina.memory.memory_types import RelationshipState
from furina.relationship.engine import (
    RelationshipEngine, relationship_factors, EV_REJECT, EV_POSITIVE_RESPONSE, EV_POSITIVE_TOUCH,
)


# ================================================================ canonical normalizer exact
def test_relationship_canonical_normalizer_exact():
    st = RelationshipState()
    st.familiarity = 50; st.trust = 50; st.comfort = 60; st.annoyance = 20
    st.user_response_rate = 0.5; st.user_rejection_rate = 0.2
    f = relationship_factors(st)
    assert abs(f["trust"] - 0.5) < 1e-9 and abs(f["comfort"] - 0.6) < 1e-9
    assert abs(f["annoyance"] - 0.2) < 1e-9 and abs(f["familiarity"] - 0.5) < 1e-9
    assert abs(f["user_response_rate"] - 0.5) < 1e-9   # 0..1 原样
    assert abs(f["user_rejection_rate"] - 0.2) < 1e-9
    assert abs(f["response_rate"] - 0.5) < 1e-9
    assert abs(f["confidence"] - 0.8) < 1e-9           # 1 - 0.2
    # 无关系 → 中性，不饱和到 1.0
    n = relationship_factors(None)
    assert abs(n["trust"] - 0.0) < 1e-9 and abs(n["confidence"] - 0.5) < 1e-9
    assert n["social_confidence"] <= 1.0 and abs(n["interaction_tolerance"] - 0.5) < 1e-9


def test_relationship_rate_write_clamps_01():
    """EV_POSITIVE_RESPONSE 后 response_rate 不得 >1（写侧按 0..1 clamp，而非 0..100）。"""
    st = RelationshipState(); st.user_response_rate = 0.5
    r = RelationshipEngine(st)
    r.apply(EV_POSITIVE_RESPONSE)
    assert 0.0 <= st.user_response_rate <= 1.0, f"response_rate 应在 [0,1]，实际 {st.user_response_rate}"
    assert st.user_response_rate <= 1.0, "不得出现 1.3"


def test_positive_response_rate_never_exceeds_one():
    for _ in range(50):
        r = RelationshipEngine(RelationshipState())
        for _ in range(30):
            r.apply(EV_POSITIVE_RESPONSE)
            assert 0.0 <= r.state.user_response_rate <= 1.0


def test_reject_stats_increment_once_real_route():
    """一次 EV_REJECT → rejection_count +1、user_rejection_rate 一次（_bump 单写，无 Scheduler 双写）。"""
    st = RelationshipState(); st.rejection_count = 0; st.user_rejection_rate = 0.0
    r = RelationshipEngine(st)
    r.apply(EV_REJECT)
    assert st.rejection_count == 1, f"rejection_count 应 +1，实际 {st.rejection_count}"
    assert 0.0 <= st.user_rejection_rate <= 1.0
    assert st.user_rejection_rate < 0.5, "一次拒绝不应把 rejection_rate 拉到 >0.5"


# ================================================================ BehaviorMotivation canonical
def test_behavior_motivation_relationship_scale_exact():
    from furina.behavior.motivation import _rel
    from furina.state import CharacterState
    st = CharacterState()
    rs = RelationshipState(); rs.trust = 50; rs.comfort = 60; rs.annoyance = 20
    rs.user_response_rate = 0.5; rs.user_rejection_rate = 0.2
    st.relationship = rs
    rel = _rel(st)
    assert abs(rel["trust"] - 0.5) < 1e-9
    assert abs(rel["comfort"] - 0.6) < 1e-9
    assert abs(rel["annoyance"] - 0.2) < 1e-9
    assert abs(rel["response_rate"] - 0.5) < 1e-9, f"response_rate 应为 .5，实际 {rel['response_rate']}"
    assert abs(rel["confidence"] - 0.8) < 1e-9, f"confidence 应为 .8，实际 {rel['confidence']}"


# ================================================================ LifeBrain appraisal canonical
def test_lifebrain_appraisal_relationship_scale_exact():
    from furina.life_brain import _relationship_factors
    from furina.state import CharacterState
    st = CharacterState()
    rs = RelationshipState(); rs.familiarity = 50; rs.trust = 50; rs.comfort = 60; rs.annoyance = 20
    st.relationship = rs
    f = _relationship_factors(st)
    assert abs(f["trust"] - 0.5) < 1e-9, f"trust 应 .5（非 1.0 饱和），实际 {f['trust']}"
    assert abs(f["comfort"] - 0.6) < 1e-9
    assert abs(f["annoyance"] - 0.2) < 1e-9
    assert abs(f["familiarity"] - 0.5) < 1e-9
    assert f["trust"] <= 1.0, "不得饱和到 1.0"


# ================================================================ Dialogue normalized annoyance branch
def test_dialogue_annoyance_normalized_branch():
    from furina.persona.furina_character_contract import mode_for
    # annoyance=0.7 (>0.6) 触发高烦 GUARDED；0.2 不触发（且信任足够）
    assert mode_for("calm", 0.6, 0.6, 0.7, False, True) == "GUARDED", "annoyance .7 应触发高烦"
    assert mode_for("calm", 0.6, 0.6, 0.2, False, True) != "GUARDED", "annoyance .2 不应触发"


def test_expressive_annoyance_warmth_brevity():
    """C-R2 hotfix：真实 ExpressionStrategy 路径，annoyance=.7 → warmth 更低 / brevity 更高（vs .2）。"""
    from furina.dialogue import ExpressionEngine
    from furina.persona.character_identity import FURINA_IDENTITY
    eng = ExpressionEngine(FURINA_IDENTITY)
    high = eng.strategy(emotion="calm", mode="CASUAL",
                        relationship={"annoyance": 0.7, "trust": 0.5, "comfort": 0.5, "familiarity": 0.4},
                        task_mode=False, activation={}, user_working=False)
    low = eng.strategy(emotion="calm", mode="CASUAL",
                       relationship={"annoyance": 0.2, "trust": 0.5, "comfort": 0.5, "familiarity": 0.4},
                       task_mode=False, activation={}, user_working=False)
    assert high.warmth < low.warmth, f"annoyance .7 warmth 应更低: high={high.warmth} low={low.warmth}"
    assert high.brevity > low.brevity, f"annoyance .7 brevity 应更高: high={high.brevity} low={low.brevity}"


# ================================================================ positive text persists once
def test_text_positive_response_persists_once():
    from furina.app import Furina
    app = Furina.__new__(Furina)
    app.saved = []
    rs = RelationshipState(); rs.user_response_rate = 0.4
    from furina.relationship.engine import RelationshipEngine
    eng = RelationshipEngine(rs)
    app.relationship = eng
    app.state = SimpleNamespace(state=SimpleNamespace(relationship=None))
    store = SimpleNamespace(save_relationship=lambda s: app.saved.append(s))
    app.memory = SimpleNamespace(store=store)
    app._sched = None
    app._apply_user_text_fx("谢谢你帮我")
    assert len(app.saved) == 1, "一次高置信谢意应持久化一次"
    assert app.state.state.relationship is eng.state, "state 引用应保持共享"


# ================================================================ agent failure example routing
def test_agent_failure_selects_agent_failure_example():
    from furina.dialogue_brain import DialogueBrain
    from furina.persona.expression_examples import get_examples
    db = DialogueBrain.__new__(DialogueBrain)
    class _App:
        mode = "CASUAL"; dialogue_act = "COMMENT"
    sel = db._select_examples(_App(), emotion="calm", activity="agent_fail", user_text="")
    assert "agent_failure" in [e["context"] for e in sel], "agent_fail 应命中 agent_failure 例子"


def test_no_stage_direction_in_any_example():
    from furina.persona.expression_examples import get_examples
    for e in get_examples():
        assert "（" not in e["speech"], f"example 不应含任何舞台动作/动作括号: {e['speech']}"
