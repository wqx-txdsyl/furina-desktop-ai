"""Phase 15 D5 — Relationship Anti-Spam / Anti-Runaway Hardening（reviewer-locked）。

铁律：C5 current truth owner 仍是 RelationshipEngine；无 schema / 无第二个真值；
short-window 内同族重复 → 边际影响确定性递减；首次事件完整保留；总影响有界；
窗口过去 → 逐步恢复；不同事件族绝不共享饱和计数；strength 仍参与实际 delta；
未知事件安全 no-op；milestone provenance 一字不动。
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pytest import approx

from furina.relationship.engine import (
    RelationshipEngine,
    EV_POSITIVE_RESPONSE, EV_POSITIVE_TOUCH, EV_SUCCESSFUL_HELP, EV_REJECT,
)


class _FakeClock:
    """可注入确定性时钟（禁 sleep）。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt)


# ================================================================ 1. 首次事件完整保留
def test_d5_first_event_matches_existing_delta_exact():
    re = RelationshipEngine()
    ret = re.apply(EV_POSITIVE_RESPONSE)
    # 与 D5 前完全一致（family 首事件 mult=1.0）：LONG_TERM ×0.7、trust ×0.5、rate 0..1
    assert re.state.familiarity == approx(3.5 * 0.7)
    assert re.state.comfort == approx(5.0 * 0.7)
    assert re.state.social_confidence == approx(40.0 + 5.0)
    assert re.state.interaction_tolerance == approx(50.0 + 4.0)
    assert re.state.user_response_rate == approx(0.5 + 0.05)
    assert ret["familiarity"] == approx(3.5)          # 返回 = 基础 delta × mult(=1.0)


# ================================================================ 2. 重复 positive burst
def test_d5_positive_burst_diminishing_and_bounded():
    re = RelationshipEngine()
    prev = 0.0
    margins = []
    for _ in range(100):
        re.apply(EV_POSITIVE_RESPONSE)
        margins.append(re.state.familiarity - prev)
        prev = re.state.familiarity
    # 每次边际增长严格递减（同窗口内；仅前 30 档可测量 —— 50+ 次减半后低于 float 精度）
    for i in range(30):
        assert margins[i] > margins[i + 1], (
            f"边际应递减: {margins[i]:.4f} vs {margins[i+1]:.4f}")
    # 大量重复后边际趋近 0（总影响有界）
    assert margins[-1] < 1e-9, "大量重复后的边际应趋近 0"
    # 状态仍可增长（非零积累）
    assert re.state.familiarity > margins[0] * 1.5
    # 总增长显著低于线性累计（线性=100×首档；几何有界 ≈ 2×首档）
    assert re.state.familiarity < margins[0] * 3.0
    assert re.state.familiarity < 100 * margins[0] * 0.1
    # 不得快速刷满 trust/comfort/familiarity
    assert re.state.trust < 15 and re.state.comfort < 20 and re.state.familiarity < 20


# ================================================================ 3. 100 次触摸 ≠ 长期关系
def test_d5_100_touches_do_not_build_longterm_relationship():
    re = RelationshipEngine()
    for _ in range(100):
        re.apply(EV_POSITIVE_TOUCH)
    # 线性累计会给出 familiarity≈175、comfort≈420（clamp 100）；有界实现必须远低于此
    assert re.state.familiarity < 10
    assert re.state.comfort < 15
    assert re.state.trust == 0, "触摸不产生 trust；未建立长期信任"


# ================================================================ 4. 重复 minor negative burst
def test_d5_negative_burst_reaction_bounded_not_destroying():
    re = RelationshipEngine()
    prev = 0.0
    margins = []
    for _ in range(100):
        re.apply(EV_REJECT)
        margins.append(re.state.annoyance - prev)
        prev = re.state.annoyance
    # 边际损伤严格递减（仅前 30 档可测量 —— 50+ 次减半后低于 float 精度）
    for i in range(30):
        assert margins[i] > margins[i + 1], (
            f"边际损伤应递减: {margins[i]:.4f} vs {margins[i+1]:.4f}")
    assert margins[-1] < 1e-9, "大量重复后的边际损伤应趋近 0"
    # 有反应
    assert re.state.annoyance > 5
    assert re.state.interaction_tolerance < 50
    assert re.state.social_confidence < 40
    # 总损伤有界（线性=100×7=700，clamp 100）
    assert re.state.annoyance < 30
    # 少量意外负向不能摧毁长期关系：短期未归零、长期（trust/comfort）未被波及
    assert re.state.interaction_tolerance > 25
    assert re.state.social_confidence > 25
    assert re.state.trust == 0 and re.state.comfort == 0


# ================================================================ 5. 事件族隔离
def test_d5_event_family_isolation_touch_does_not_suppress_help():
    re = RelationshipEngine()
    for _ in range(100):
        re.apply(EV_POSITIVE_TOUCH)                    # pet 族饱和
    # successful_help 属 help 族（独立饱和）→ 仍获完整影响
    ret = re.apply(EV_SUCCESSFUL_HELP)
    assert re.state.respect == approx(3.0), "help 族不受 pet 族饱和压制"
    assert re.state.trust == approx(2.0 * 0.5)
    assert re.state.comfort == approx(3.0 * 0.7 + 6.0 * 0.7 * (2.0 - 2.0 ** -99))
    assert ret["respect"] == approx(3.0) and ret["trust"] == approx(2.0)


# ================================================================ 6. 时间恢复（injectable clock）
def test_d5_window_recovery_with_injectable_clock():
    clk = _FakeClock()
    re = RelationshipEngine(time_fn=clk, window_seconds=120.0)
    re.apply(EV_POSITIVE_TOUCH)                        # t=1000 → mult 1.0
    fam1 = re.state.familiarity
    clk.advance(1.0)
    re.apply(EV_POSITIVE_TOUCH)                        # t=1001 → mult 0.5
    fam2 = re.state.familiarity
    assert fam2 - fam1 == approx(fam1 * 0.5)
    clk.advance(60.0)
    re.apply(EV_POSITIVE_TOUCH)                        # t=1061 → mult 0.25（半窗内仍饱和）
    fam3 = re.state.familiarity
    assert fam3 - fam2 == approx(fam1 * 0.25), "窗口未过 → 影响仍递减（逐步恢复）"
    clk.advance(121.0)
    re.apply(EV_POSITIVE_TOUCH)                        # t=1182 → 旧事件全部逐出 → mult 1.0
    fam4 = re.state.familiarity
    assert fam4 - fam3 == approx(fam1), "窗口过去 → 同类事件恢复全额影响"


# ================================================================ 7. strength 参与且不绕过饱和
def test_d5_strength_participates_and_does_not_bypass_saturation():
    re = RelationshipEngine()
    prev = 0.0
    margins = []
    for _ in range(3):
        re.apply(EV_POSITIVE_TOUCH, strength=2.0)
        margins.append(re.state.familiarity - prev)
        prev = re.state.familiarity
    assert margins[0] == approx(2.5 * 0.7 * 2.0)          # strength 参与实际 delta
    assert margins[1] == approx(2.5 * 0.7 * 2.0 * 0.5)    # 第 2 次仍递减
    assert margins[2] == approx(2.5 * 0.7 * 2.0 * 0.25)   # 饱和未被 strength 绕过
    assert margins[0] > margins[1] > margins[2]


# ================================================================ 8. clamps / units 保持
def test_d5_clamps_and_units_preserved_after_bursts():
    re = RelationshipEngine()
    for _ in range(100):
        re.apply(EV_POSITIVE_TOUCH)
    for _ in range(100):
        re.apply(EV_REJECT)
    st = re.state
    for k in ("familiarity", "trust", "comfort", "attachment", "respect", "dependency",
              "annoyance", "interaction_tolerance", "social_confidence"):
        v = float(getattr(st, k))
        assert 0.0 <= v <= 100.0, f"{k}={v} 超出 0..100"
    assert 0.0 <= st.user_response_rate <= 1.0, "rate 0..1"
    assert 0.0 <= st.user_rejection_rate <= 1.0, "rejection_rate 0..1"
    assert st.rejection_count >= 0, "count ≥ 0"


# ================================================================ 9. milestone provenance
def test_d5_milestone_provenance_preserved_no_fake_milestones(tmp_path):
    from furina.cognition import CognitionHub
    eng = RelationshipEngine()
    hub = CognitionHub(Path(tmp_path) / "cog.db", relationship_engine=eng)
    hub.relationship.record_milestone("first_positive", "第一次积极回应",
                                      source_event_id="lev_abc_123")
    before = hub.relationship.milestones()
    for _ in range(50):
        hub.relationship.apply(EV_POSITIVE_TOUCH)
    for _ in range(50):
        hub.relationship.apply(EV_REJECT)
    after = hub.relationship.milestones()
    assert len(after) == len(before) == 1, "anti-spam 不得创建虚假 milestone"
    assert after[0]["source_event_id"] == "lev_abc_123", "source_event_id 精确保留"
    assert after[0]["milestone_type"] == "first_positive"
    hub.close()


# ================================================================ 10. restart 语义
def test_d5_restart_truth_persists_ledger_clears():
    clk = _FakeClock()
    re1 = RelationshipEngine(time_fn=clk)
    for _ in range(5):
        re1.apply(EV_POSITIVE_TOUCH)
    # 模拟 restart：C5 current truth 随 state 保留（MemoryStore.save/load_relationship），
    # operational 饱和账本（纯内存）清空 → 首次事件恢复全额。
    re2 = RelationshipEngine(state=copy.copy(re1.state))
    assert re2.state.familiarity == re1.state.familiarity, "C5 current truth 不丢失"
    before = re2.state.familiarity
    re2.apply(EV_POSITIVE_TOUCH)
    assert re2.state.familiarity - before == approx(2.5 * 0.7), (
        "restart 后（账本清空）首事件恢复全额影响")


# ================================================================ 11. counterexample（旧线性必败）
def test_d5_counterexample_linear_accumulation_fails():
    # 正向：默认有界实现 vs 关闭饱和（window=0 → 旧线性行为）
    re = RelationshipEngine()
    for _ in range(100):
        re.apply(EV_POSITIVE_TOUCH)
    re_lin = RelationshipEngine(window_seconds=0.0)      # 旧线性对照
    for _ in range(100):
        re_lin.apply(EV_POSITIVE_TOUCH)
    linear_fam = 100 * (2.5 * 0.7)
    assert re_lin.state.familiarity >= 99.0, "线性对照应接近 clamp 100（证明对照有效）"
    assert re.state.familiarity < linear_fam * 0.1, "100 次触摸不得接近线性累计"
    assert re.state.familiarity < re_lin.state.familiarity * 0.2
    assert re.state.familiarity >= 2.5 * 0.7, "仍须有真实积累（非零）"
    # 负向：线性对照 vs 有界实现
    re2 = RelationshipEngine()
    for _ in range(100):
        re2.apply(EV_REJECT)
    re2_lin = RelationshipEngine(window_seconds=0.0)
    for _ in range(100):
        re2_lin.apply(EV_REJECT)
    linear_annoy = 100 * 7.0
    assert re2_lin.state.annoyance >= 99.0, "线性对照 annoyance 应接近 clamp 100"
    assert re2.state.annoyance < linear_annoy * 0.1, "负向总损伤必须有界"
    assert re2.state.annoyance < re2_lin.state.annoyance * 0.3
    assert re2.state.annoyance > 5.0, "负向须有真实反应"


# ================================================================ 未知事件 no-op
def test_d5_unknown_event_safe_noop_no_ledger_pollution():
    re = RelationshipEngine()
    assert re.apply("totally_unknown_event") == {}
    assert re.state.familiarity == 0.0 and re.state.trust == 0.0
    # 未知事件不得污染饱和账本：随后真实事件仍为全额
    re.apply(EV_POSITIVE_TOUCH)
    assert re.state.familiarity == approx(2.5 * 0.7)
