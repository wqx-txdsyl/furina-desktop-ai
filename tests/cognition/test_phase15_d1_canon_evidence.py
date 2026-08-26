"""Phase 15 D1 — Canon Act II/III Official Evidence Acquisition（reviewer-locked）。

锁定契约（04 任务书 §6）：
  T1/T2   新增 evidence/source 全部注册且可解析（全局完整性不回归）
  T3/T4   Act II / Act III 的 exact MAIN_STORY·Chapter IV 支撑是**精确**的
          （字段逐字相等，非推断）
  T5      错幕证据不得支撑其它 act（语义冲突 + support gap 双报）
  T6      community/locator 来源不得计入官方支撑；新增单元归属官方公告页来源
  T7      生产 semantic metrics 与实际验证状态一致（coverage COMPLETE 幕级 +
          life-stage PARTIAL 仅因 INNER_WORLD_REVELATION 真实缺口）
  T8      R7 / R7-FC 的语义完备性判定行为逐条保持（fixture 三态矩阵）
  T9      C2 runtime 只读不变（磁盘字节前后一致 + store 无写方法）
  T10     Furina != Focalors 身份边界原样（canon identity 只读视图 + 反身份事实）

官方锚点（D1 recon，2026-08-27 抓取全文存档）：
  SRC-011 = HoYoLAB 官方号『"As Light Rain Falls Without Reason" Version 4.0 Update Details』
            （post 20899860；update maintenance begins 2023/08/16 06:00 (UTC+8)）
  SRC-012 = 同号『"To the Stars Shining in the Depths" Version 4.1 Update Details』
            （post 21888288；2023/09/27；镜像 genshin.hoyoverse.com/en/news/detail/113142）
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SOURCES = _REPO / "data/canon/furina_life_sources.json"
_REGISTRY = _REPO / "data/canon/furina_evidence_units.json"
_HISTORY = _REPO / "data/canon/furina_life_history.json"

_NEW_UNITS = ("FUR-057", "FUR-058")
_NEW_SOURCES = ("SRC-011", "SRC-012")


def _store(hist=None):
    from furina.cognition.stores.canon_history import CanonHistoryStore
    if hist is None:
        return CanonHistoryStore()
    tmp = Path(tempfile.mkdtemp()) / "hist.json"
    tmp.write_text(json.dumps({"episodes": [hist]}, ensure_ascii=False),
                   encoding="utf-8")
    return CanonHistoryStore(history_path=tmp, sources_path=_SOURCES,
                             evidence_path=_REGISTRY)


# ================================================================ T1/T2 注册完整性
def test_d1_t1_new_evidence_ids_globally_registered():
    ids = {u["evidence_id"] for u in json.loads(
        _REGISTRY.read_text(encoding="utf-8"))["evidence_units"]}
    assert set(_NEW_UNITS) <= ids, f"D1 新增单元必须登记: {_NEW_UNITS}"
    m = _store().metrics()
    assert m["unregistered_evidence_ids"] == []
    assert m["evidence_attribution_conflicts"] == []
    assert m["evidence_registry_duplicates"] == []
    assert m["evidence_registry_entries"] == 58


def test_d1_t2_new_source_ids_registered_and_official_used():
    srcs = {s["source_id"]: s for s in json.loads(
        _SOURCES.read_text(encoding="utf-8"))["sources"]}
    assert set(_NEW_SOURCES) <= set(srcs)
    for sid in _NEW_SOURCES:
        s = srcs[sid]
        assert s["status"] == "USED", sid
        assert int(s["canon_tier"]) == 1, sid
        assert s["source_type"] == "OFFICIAL_WEB", sid
        # 官方身份必须在档：认证官方账号 uid + 公告原文标题都在 access_source/locator 链上
        blob = (s.get("access_source", "") + s.get("access_locator", ""))
        assert "uid=1015537" in blob and "cert_type=1" in blob, sid
        assert s["evidence_ids"], sid
    m = _store().metrics()
    for sid in _NEW_SOURCES:
        assert sid in m["sources_used"], sid


# ================================================================ T3/T4 精确幕支撑
def test_d1_t3_act_ii_support_is_exact_not_inferred():
    u = _store().evidence_unit("FUR-057")
    assert u is not None
    assert u["source_type"] == "MAIN_STORY"
    assert u["quest"] == "Chapter IV"
    assert u["act"] == "II"                      # 逐字，非 None/跨度/版本号
    assert "As Light Rain Falls Without Reason" in u["scene"]
    assert _store().metrics()["main_story_act_coverage"]["II"] is True


def test_d1_t4_act_iii_support_is_exact_not_inferred():
    u = _store().evidence_unit("FUR-058")
    assert u is not None
    assert u["source_type"] == "MAIN_STORY"
    assert u["quest"] == "Chapter IV"
    assert u["act"] == "III"
    assert "To the Stars Shining in the Depths" in u["scene"]
    assert _store().metrics()["main_story_act_coverage"]["III"] is True


# ================================================================ T5 错幕不可支撑
def test_d1_t5_wrong_act_evidence_cannot_support_other_act():
    m = _store({"episode_id": "FIX_WRONG_ACT", "quest": "Chapter IV",
                "act": "IV", "evidence_ids": ["FUR-057"],
                "source_ids": ["SRC-001"], "timeline_order": 1}).metrics()
    conflicts = m["evidence_attribution_conflicts"]
    assert any(c.get("episode") == "FIX_WRONG_ACT"
               and c.get("episode_act") == "IV" and c.get("evidence_act") == "II"
               for c in conflicts), conflicts
    assert any(g["episode"] == "FIX_WRONG_ACT"
               for g in m["episodes_without_exact_act_main_story_evidence"])
    st = m["mandatory_life_stage_source_status"]
    assert st != "SOURCE_COMPLETE"


# ================================================================ T6 locator 不算官方支撑
def test_d1_t6_locator_sources_cannot_count_as_official_support():
    raw = _SOURCES.read_text(encoding="utf-8").lower()
    data = json.loads(_SOURCES.read_text(encoding="utf-8"))
    used = [s for s in data["sources"] if s.get("status") == "USED"]
    banned_markers = ("github.com/furinelle", "fandom.com", "gamersky",
                      "bilibili.com/video", "9game", "ai summary", "reddit")
    for s in used:
        blob = (str(s.get("access_source", "")) + str(s.get("access_locator", ""))).lower()
        for b in banned_markers:
            assert b not in blob or "mirror" in blob or "镜像" in str(s.get("access_locator", "")).lower(), \
                f"{s['source_id']} 不得以社区源为 USED 依据: hit={b}"
    # D1 单元必须由官方公告页来源持有（而非任何 locator 类来源）
    owners = {sid: s for sid, s in ((s["source_id"], s) for s in data["sources"])}
    for unit_id in _NEW_UNITS:
        owning = [s["source_id"] for s in used if unit_id in (s.get("evidence_ids") or [])]
        assert owning, f"{unit_id} 必须被某个 USED 源引用"
        for sid in owning:
            assert owners[sid]["source_type"] == "OFFICIAL_WEB", sid
    assert "github.com/furinelle" not in raw.replace(" ", "").replace("\n", ""), \
        "Furinelle locator 不得出现在 source registry 存储文本中"


# ================================================================ T7 生产 metrics 一致性
def test_d1_t7_production_metrics_match_verified_state():
    m = _store().metrics()
    assert m["main_story_act_coverage"] == {"I": True, "II": True, "III": True,
                                            "IV": True, "V": True}
    assert m["missing_main_story_acts"] == []
    assert m["main_story_act_coverage_status"] == "COMPLETE"
    # 语义层保持诚实：唯一剩余缺口仍是 INNER_WORLD_REVELATION（真实缺口未被洗绿）
    gaps = [g["episode"] for g in m["episodes_without_exact_act_main_story_evidence"]]
    assert gaps == ["INNER_WORLD_REVELATION"], gaps
    st = m["mandatory_life_stage_source_status"]
    assert st.startswith("PARTIAL") and "INNER_WORLD_REVELATION" in st, st
    assert m["canon_span_status"] == "MANDATORY_SPAN_SOURCE_COMPLETE"
    assert m["dangling_source_ids"] == []


# ================================================================ T8 既有判定行为保持
def test_d1_t8_prior_r7_r7fc_semantics_preserved():
    from tests.cognition.test_phase14_final_reviewer_r6_r12 import (
        test_r7_t1_character_story_null_act_cannot_cover_exact_act as r7t1,
        test_r7_t2_act_mismatch_is_semantic_conflict as r7t2,
        test_r7_t3_same_act_main_story_is_valid as r7t3,
    )
    from tests.cognition.test_phase14_final_r7_r10_failclosed import (
        test_r7_fc_t1_non_exact_act_missing_evidence_fails as fc1,
        test_r7_fc_t3_exact_act_semantics_preserved as fc3,
    )
    for fn in (r7t1, r7t2, r7t3, fc1, fc3):
        # 这些用例均为 fixture 隔离，不受生产数据影响；按各自签名调用
        if "tmp_path" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
            fn(tmp_path=Path(tempfile.mkdtemp()))
        else:
            fn()


# ================================================================ T9 C2 运行时只读
def test_d1_t9_canon_runtime_remains_read_only():
    before_s = hashlib.sha256(_SOURCES.read_bytes()).hexdigest()
    before_r = hashlib.sha256(_REGISTRY.read_bytes()).hexdigest()
    before_h = hashlib.sha256(_HISTORY.read_bytes()).hexdigest()
    store = _store()
    store.metrics()
    store.evidence_unit("FUR-057")
    store.all_episodes()
    store.periods_covered()
    store.tier_counts()
    after = (hashlib.sha256(_SOURCES.read_bytes()).hexdigest(),
             hashlib.sha256(_REGISTRY.read_bytes()).hexdigest(),
             hashlib.sha256(_HISTORY.read_bytes()).hexdigest())
    assert after == (before_s, before_r, before_h), "C2 加载/查询不得改写字节"
    forbidden_verbs = ("save", "write", "append", "upsert", "insert", "add_",
                       "remove", "delete", "update", "set_", "create_")
    public = [n for n in dir(store) if not n.startswith("_")]
    writers = [n for n in public for v in forbidden_verbs if n.lower().startswith(v)]
    assert writers == [], f"CanonHistoryStore 不得暴露写方法: {writers}"


# ================================================================ T10 Furina != Focalors
def test_d1_t10_furina_focalors_boundary_unchanged():
    from furina.cognition.stores.canon_identity import CanonIdentityStore
    store = CanonIdentityStore()
    assert getattr(store, "_mutable", False) is False
    anti = "\n".join(store.anti_identity())
    facts = "\n".join(str(f.get("fact", "")) for f in store.identity_facts())
    blob = anti + facts
    assert ("芙卡洛斯" in blob or "Focalors" in blob), "反身份事实必须显式区分神格侧"
    # 边界核心句仍在：同源 ≠ 共享知识/记忆/权能
    assert ("并不拥有" in blob or "不同" in blob or "非同一" in blob
            or "人格侧" in blob), blob[:200]
    snap = store.snapshot()
    assert "identity_facts" in snap and snap["identity_facts"]


# ================================================================
# External Reviewer Residual（NEEDS_NARROW_PATCH）：evidence→source 持有链 fail-closed
# ================================================================
_ORPHAN_ID = "FUR-T901"


def _unit(eid, act="II"):
    return {"evidence_id": eid, "source_type": "MAIN_STORY",
            "quest": "Chapter IV", "act": act, "scene": f"幕级条目 {eid}"}


def _src(sid, *, tier=0, status="USED", owned=(), stype="CURATED_EVIDENCE"):
    return {"source_id": sid, "source_type": stype,
            "access_source": f"fixture {sid}", "original_material": "TEST",
            "canon_tier": tier, "version": None, "quest": None, "act": None,
            "scene": None, "furina_present": None, "relevance": "test",
            "evidence_ids": list(owned), "notes": "", "access_locator": "",
            "status": status}


def _rs_store(units, sources=None, episodes=None):
    """三件套全自定义的隔离 store（用于持有链反例；sources 缺省=无任何来源）。"""
    from furina.cognition.stores.canon_history import CanonHistoryStore
    tmp = Path(tempfile.mkdtemp())
    (tmp / "h.json").write_text(json.dumps({"episodes": episodes or []},
                                           ensure_ascii=False), encoding="utf-8")
    (tmp / "s.json").write_text(json.dumps({"sources": sources},
                                           ensure_ascii=False), encoding="utf-8")
    (tmp / "u.json").write_text(json.dumps({"evidence_units": units},
                                           ensure_ascii=False), encoding="utf-8")
    return CanonHistoryStore(history_path=tmp / "h.json",
                             sources_path=tmp / "s.json",
                             evidence_path=tmp / "u.json")


def test_d1_r1_orphan_evidence_cannot_cover_act():
    """R1：MAIN_STORY/Chapter IV/II 元数据精确但无任何 source 持有 → 不产生覆盖。"""
    m = _rs_store([_unit(_ORPHAN_ID)]).metrics()
    assert m["main_story_act_coverage"]["II"] is False
    assert "II" in m["missing_main_story_acts"]


def test_d1_r2_not_used_source_cannot_cover_act():
    """R2：持有者存在但 status=NOT_USED → 覆盖仍为 False。"""
    m = _rs_store([_unit(_ORPHAN_ID)],
                  [_src("S-NOTU", tier=1, status="NOT_USED",
                        owned=[_ORPHAN_ID], stype="OFFICIAL_WEB")]).metrics()
    assert m["main_story_act_coverage"]["II"] is False
    assert "II" in m["missing_main_story_acts"]


def test_d1_r3_forbidden_and_nonauthoritative_tiers_cannot_cover_act():
    """R3：Tier3/FORBIDDEN 持有 或 Tier2 USED 镜像类持有 → 都不产生覆盖。"""
    forbidden = _rs_store(
        [_unit(_ORPHAN_ID)],
        [_src("S-FORB", tier=3, status="FORBIDDEN", owned=[_ORPHAN_ID],
              stype="FORBIDDEN")]).metrics()
    assert forbidden["main_story_act_coverage"]["II"] is False

    mirror_t2 = _rs_store(
        [_unit(_ORPHAN_ID)],
        [_src("S-MIRR", tier=2, status="USED", owned=[_ORPHAN_ID],
              stype="OFFICIAL_MIRROR")]).metrics()
    assert mirror_t2["main_story_act_coverage"]["II"] is False


def test_d1_r4_unrelated_valid_source_cannot_rescue_exact_episode():
    """R4：episode 有其它有效 USED source_id，但被引 evidence 本身无合格持有链 →
    精确支撑不成立（不得张冠李戴）；覆盖也不因 source_ids 翻绿。"""
    m = _rs_store(
        [_unit(_ORPHAN_ID), {"evidence_id": "FUR-OK", "source_type": "PROFILE",
                             "quest": None, "act": None, "scene": "无关档案"}],
        [_src("S-OK", tier=0, status="USED", owned=["FUR-OK"])],
        episodes=[{"episode_id": "FIX_EP_II", "quest": "Chapter IV",
                   "act": "II", "evidence_ids": [_ORPHAN_ID],
                   "source_ids": ["S-OK"], "timeline_order": 1}]).metrics()
    gaps = [g["episode"] for g in m["episodes_without_exact_act_main_story_evidence"]]
    assert "FIX_EP_II" in gaps, gaps
    st = m["mandatory_life_stage_source_status"]
    assert st != "SOURCE_COMPLETE" and st.startswith("PARTIAL"), st
    assert m["main_story_act_coverage"]["II"] is False


def test_d1_r5_production_official_chain_happy_path():
    """R5：生产 SRC-011→FUR-057 / SRC-012→FUR-058 持有链合法 → 幕覆盖成立。"""
    m = _store().metrics()
    assert m["main_story_act_coverage"]["II"] is True
    assert m["main_story_act_coverage"]["III"] is True
    assert m["missing_main_story_acts"] == []
    assert m["main_story_act_coverage_status"] == "COMPLETE"


def test_d1_r6_inner_world_revelation_still_only_gap_and_demote_fails_closed():
    """R6+方向性验证：INNER_WORLD_REVELATION 是生产唯一精确幕缺口；且将
    FUR-057 的持有者降级 NOT_USED 后 Act II 必须立刻失绿（fail-closed 方向）。"""
    m = _store().metrics()
    gaps = [g["episode"] for g in m["episodes_without_exact_act_main_story_evidence"]]
    assert gaps == ["INNER_WORLD_REVELATION"], gaps

    raw_s = json.loads(_SOURCES.read_text(encoding="utf-8"))["sources"]
    demoted = []
    for s in raw_s:
        s = dict(s)
        if "FUR-057" in (s.get("evidence_ids") or []):
            s["status"] = "NOT_USED"
        demoted.append(s)
    md = _rs_store([u for u in json.loads(_REGISTRY.read_text(encoding="utf-8"))
                    ["evidence_units"]], demoted).metrics()
    assert md["main_story_act_coverage"]["II"] is False, "持有者降级必须失绿"
    assert "II" in md["missing_main_story_acts"]


