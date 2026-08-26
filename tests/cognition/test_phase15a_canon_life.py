"""Phase 15A — C2 Canon Life Completion 测试（tests/cognition/）。

覆盖：source map 可复现 locator、20 mandatory life stages、Canon knowledge boundary
（Focalors 知道 ≠ Furina 知道）、performance meaning（过去=duty / 现在=choice）、
Canon runtime immutability（文件 checksum 不变 / 无 mutation API）。
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from furina.cognition import CognitionHub
from furina.cognition.retrieval.retriever import CanonLifeRetriever

_REPO = Path(__file__).resolve().parents[2]

# §6 强制覆盖的 20 个 life stages
MANDATORY_STAGES = [
    "ORIGIN_IDENTITY", "FOCALORS_INSTRUCTION", "PUBLIC_ROLE_BEGIN", "LONG_PERFORMANCE",
    "PUBLIC_EXPECTATION", "PRIVATE_ISOLATION", "MASK_CRACKS", "TRAVELER_INTERACTIONS",
    "TRIAL_BEGIN", "TRIAL_PRESSURE", "INNER_WORLD_REVELATION", "FOCALORS_TRUTH",
    "PUBLIC_ROLE_END", "POST_AQ_WITHDRAWAL", "ORDINARY_LIFE", "STORY_QUEST_CONTACT",
    "RETURN_TO_STAGE", "VISION_RECEIVED", "CHOSEN_PERFORMANCE", "CURRENT_SELF",
]


def _hub() -> CognitionHub:
    return CognitionHub(Path(tempfile.mkdtemp()) / "cog.db")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ================================================================ source map 可复现 locator
def test_source_map_access_locators_reproducible():
    data = json.loads((_REPO / "data/canon/furina_life_sources.json").read_text(encoding="utf-8"))
    srcs = data["sources"]
    assert len(srcs) >= 10
    for s in srcs:
        assert s.get("source_id"), s
        assert s.get("canon_tier") in (0, 1, 2, 3)
        loc = s.get("access_locator", "")
        assert isinstance(loc, str) and loc.strip(), f"{s['source_id']} 必须含可复现 access_locator"
        # TIER 3 禁止来源：locator 明确 N/A（不可定位 = 正确）
        if s["canon_tier"] == 3:
            assert "N/A" in loc or "禁止" in loc


# ================================================================ 20 mandatory life stages 全覆盖
def test_mandatory_life_stage_coverage():
    hub = _hub()
    eps = {e.episode_id: e for e in hub.canon_history.all_episodes()}
    missing = [s for s in MANDATORY_STAGES if s not in eps]
    assert not missing, f"缺少 mandatory life stage: {missing}"
    for sid in MANDATORY_STAGES:
        ep = eps[sid]
        assert ep.life_stage == sid, f"{sid} 必须带 life_stage"
        assert ep.objective_summary, f"{sid} 必须含 objective_summary"
        assert ep.evidence_ids, f"{sid} 必须含 evidence_ids"
    hub.close()


# ================================================================ knowledge boundary（Focalors 知道 ≠ Furina 知道）
def test_canon_knowledge_boundary_furina_did_not_know():
    hub = _hub()
    eps = {e.episode_id: e for e in hub.canon_history.all_episodes()}
    # FOCALORS_INSTRUCTION / ORIGIN_IDENTITY：Furina 当时不知道全盘计划（Focalors 知道）
    for sid in ("FOCALORS_INSTRUCTION", "ORIGIN_IDENTITY"):
        ep = eps[sid]
        assert ep.furina_did_not_know, f"{sid} 必须含 furina_did_not_know（信息边界）"
    inst = eps["FOCALORS_INSTRUCTION"]
    dnk = " ".join(inst.furina_did_not_know)
    assert any(k in dnk for k in ("计划", "全盘", "如何结束", "何时")), \
        f"Furina 不得知道全盘计划: {dnk}"
    # 明确 Furina != Focalors（同源但信息/权能不同）
    origin = eps["ORIGIN_IDENTITY"]
    assert origin.furina_did_not_know, "Furina 不拥有 Focalors 完整知识/权能"


def test_canon_focalors_furina_boundary_query():
    """'你和芙卡洛斯是什么关系' → activation 3 + FOCALORS_TRUTH/ORIGIN_IDENTITY。"""
    hub = _hub()
    r = CanonLifeRetriever(hub.canon_history)
    eps, act = r.retrieve("你和芙卡洛斯是什么关系")
    assert act == 3
    ids = [e.episode_id for e in eps]
    assert any(i in ids for i in ("FOCALORS_TRUTH", "ORIGIN_IDENTITY")), ids
    # 不允许 "Furina == Focalors"（任何 episode 的 objective 都区分二者）
    truth = hub.canon_history.get_episode("FOCALORS_TRUTH")
    assert "人格侧" in truth.objective_summary or "人类" in truth.objective_summary
    hub.close()


# ================================================================ performance meaning（过去=duty，现在=choice）
def test_performance_meaning_duty_vs_choice():
    hub = _hub()
    eps = {e.episode_id: e for e in hub.canon_history.all_episodes()}
    long_perf = eps["LONG_PERFORMANCE"]
    chosen = eps["CHOSEN_PERFORMANCE"]
    # 过去：义务/面具/生存/负担
    past = " ".join(long_perf.inferred_inner_state + long_perf.psychological_effects
                    + long_perf.external_demands)
    assert any(k in past for k in ("不能", "扮演", "维持", "义务", "生存", "暴露", "孤独")), past
    # 现在：选择/艺术/自我表达/享受
    now = " ".join(chosen.inferred_inner_state + chosen.present_day_effects
                   + chosen.psychological_effects)
    assert any(k in now for k in ("选择", "自我表达", "归宿", "自由", "自己", "自洽")), now
    # 禁止：把过去五百年推断成"她当时很享受"
    long_past = " ".join(long_perf.expressed_emotions + long_perf.inferred_inner_state)
    assert "享受" not in long_past, "不能从'现在爱表演'推断过去也享受"
    hub.close()


# ================================================================ Canon runtime immutability
def test_canon_runtime_immutable_no_mutation_api():
    hub = _hub()
    # 无 mutation API
    assert not hasattr(hub.canon_history, "append_episode")
    assert not hasattr(hub.canon_history, "update_episode")
    assert not hasattr(hub.canon_identity, "set_fact")
    assert hub.canon_history.is_read_only() and hub.canon_identity.is_read_only()
    hub.close()


def test_canon_files_checksum_unchanged_after_runtime_use():
    """runtime 操作（查询/检索/assembler）后 Canon 文件 checksum 必须不变。"""
    hp = _REPO / "data/canon/furina_life_history.json"
    sp = _REPO / "data/canon/furina_life_sources.json"
    before_h, before_s = _sha(hp), _sha(sp)
    hub = _hub()
    for _ in range(3):
        hub.canon_history.all_episodes()
        hub.canon_history.metrics()
        CanonLifeRetriever(hub.canon_history).retrieve("如果没人关注你了怎么办")
        hub.assemble(query="今天吃什么")
    hub.close()
    assert _sha(hp) == before_h, "runtime 不得改写 Canon 数据文件"
    assert _sha(sp) == before_s
