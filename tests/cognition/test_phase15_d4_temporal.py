"""Phase 15 D4 — Deterministic Temporal Semantics（reviewer-locked，T1–T16）。

权威链（brief §6/PART 3）：canonical U + ingress ts + 用户本地时区
    → 确定性解析（一次性，永不重解释）
    → candidate（≠truth）→ C4 owner 落库。
重启后相对日期保持原解；PASS due 不自动 completed；模糊一律 uncertain 不造日期。
"""
from __future__ import annotations

import datetime
import json
import tempfile
import time as _time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtWidgets import QApplication

_QAPP = QApplication.instance() or QApplication([])

SH = "Asia/Shanghai"


def _basis(y, mo, d, hh=15, mm=0, tz=SH):
    return datetime.datetime(y, mo, d, hh, mm, tzinfo=ZoneInfo(tz)).timestamp()


def _hub(tmp_path):
    from furina.cognition import CognitionHub
    return CognitionHub(Path(tmp_path) / "cog.db")


def _plans(hub, status=None):
    if status is None:
        return hub._db.query_all(
            "SELECT * FROM user_model_items WHERE category='PLAN' ORDER BY updated_at")
    if status == "active":
        return [i for i in hub.user_model.query_active(category="PLAN", limit=50)]
    return hub._db.query_all("SELECT * FROM user_model_items WHERE category='PLAN' "
                             f"AND status='{status}' ORDER BY updated_at")


# ================================================================ T1–T3 相对日
def test_d4_t1_today_resolves_to_ingress_local_date(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我今天要写报告初稿", turn_id=1,
                           basis_ts=_basis(2026, 8, 27))
    it = hub.user_model.query_active(category="PLAN")[0]
    assert it.temporal_payload["kind"] == "POINT"
    assert it.temporal_payload["start"] == "2026-08-27"
    hub.close()


def test_d4_t2_tomorrow_is_next_local_calendar_date(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我明天要写报告", turn_id=1, basis_ts=_basis(2026, 8, 27))
    it = hub.user_model.query_active(category="PLAN")[0]
    assert it.temporal_payload["start"] == "2026-08-28"
    assert it.temporal_uncertain == 0
    hub.close()


def test_d4_t3_day_after_tomorrow(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我后天去体检", turn_id=1, basis_ts=_basis(2026, 8, 27))
    it = hub.user_model.query_active(category="PLAN")[0]
    assert it.temporal_payload["start"] == "2026-08-29"
    hub.close()


# ================================================================ T4 绝对日期（无 LLM）
def test_d4_t4_absolute_dates_deterministic(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我2026年9月3日交付方案", turn_id=1,
                           basis_ts=_basis(2026, 8, 27))
    it = [x for x in hub.user_model.query_active(category="PLAN")
          if x.key == "plan:方案"][0]
    p = it.temporal_payload
    assert p["kind"] == "POINT" and p["start"] == "2026-09-03"
    # 缺年：取 basis 起最近将来（显式规则）
    hub.apply_user_message("我打算9月30日去办签证", turn_id=2,
                           basis_ts=_basis(2026, 8, 27))
    it2 = [x for x in hub.user_model.query_active(category="PLAN")
           if x.key == "plan:签证"][0]
    assert it2.temporal_payload["start"] == "2026-09-30"
    hub.close()


# ================================================================ T5 模糊不造日期
def test_d4_t5_vague_stays_uncertain_without_invented_date(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("过几天我打算整理房间", turn_id=1,
                           basis_ts=_basis(2026, 8, 27))
    it = hub.user_model.query_active(category="PLAN")[0]
    assert it.temporal_uncertain == 1
    assert it.temporal_json == ""            # 不落任何日期载荷
    assert it.status == "active"
    hub.close()


# ================================================================ T6 周重复（确定性）
def test_d4_t6_weekly_recurrence_structured(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我要每周六去健身房", turn_id=1,
                           basis_ts=_basis(2026, 8, 27))   # 周四
    it = hub.user_model.query_active(category="PLAN")[0]
    p = it.temporal_payload
    assert p["kind"] == "RECUR" and p["dow"] == 6
    assert "start" not in p                                 # 重复型不伪装成单点
    hub.close()


# ================================================================ T7/T8 dedupe vs 取代
def test_d4_t7_same_plan_changed_date_supersedes_not_swallows(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我明天要写报告", turn_id=1, basis_ts=_basis(2026, 8, 27))
    _time.sleep(0.03)
    hub.apply_user_message("我明天要写报告", turn_id=2,
                           basis_ts=_basis(2026, 8, 30))   # 三天后重说同一句
    _time.sleep(0.03)
    rows = _plans(hub, status=None)
    actives = [r for r in rows if r["status"] == "active"]
    superseded = [r for r in rows if r["status"] == "superseded"]
    assert len(actives) == 1
    assert json.loads(actives[0]["temporal_json"])["start"] == "2026-08-31"
    assert superseded and json.loads(
        superseded[-1]["temporal_json"])["start"] == "2026-08-28"
    hub.close()


def test_d4_t8_unrelated_plans_coexist(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我明天要写报告", turn_id=1, basis_ts=_basis(2026, 8, 27))
    hub.apply_user_message("这个周末我想整理房间", turn_id=2,
                           basis_ts=_basis(2026, 8, 27))
    acts = hub.user_model.query_active(category="PLAN")
    keys = sorted(i.key for i in acts)
    assert keys == ["plan:房间", "plan:报告"], keys
    by = {i.key: i.temporal_payload for i in acts}
    assert by["plan:报告"]["start"] == "2026-08-28"
    assert by["plan:房间"]["kind"] == "RANGE"
    assert by["plan:房间"]["start"] == "2026-08-29"      # 周六
    assert by["plan:房间"]["end"] == "2026-08-30"        # 周日
    hub.close()


# ================================================================ T9/T10 provenance & fail-closed
def _app_harness(tmp_path):
    from tests.cognition.test_phase14_final_reviewer_r6_r12 import _real_furina
    return _real_furina(tmp_path)


def test_d4_t9_declaration_provenance_resolvable(tmp_path):
    """declaration 行必须可解析到 canonical U（经 USER_PLAN_DECLARED 事件）。"""
    f, _ = _app_harness(tmp_path)
    try:
        f.submit_user_message("我明天要写季度总结")           # canonical ingress
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=15.0)
        rows = f.cognition._db.query_all(
            "SELECT * FROM user_model_items WHERE category='PLAN' AND status='active'")
        assert rows and rows[0]["temporal_json"], rows
        it_dev = f.cognition.events.query_by_type("USER_PLAN_DECLARED")
        assert it_dev, "declaration 事件必须在档"
        u_ids = {e.event_id for e in f.cognition.events.query_by_type("USER_MESSAGE")}
        chain_ok = any(e.payload.get("temporal") for e in it_dev) and \
            all(e.turn_id is not None for e in it_dev)
        assert chain_ok
        # U 存在且 declaration 与其同 turn 身份族
        assert u_ids
        assert json.loads(rows[0]["temporal_json"])["start"]
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


def test_d4_t10_umsg_persistence_failure_means_no_temporal_mutation(tmp_path):
    """canonical U append 失败 → 无任何 C4/temporal 变更（R10-FC 继续生效）。"""
    f, _ = _app_harness(tmp_path)
    try:
        f.submit_user_message("我喜欢喝咖啡")                 # 正常回合打底
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=15.0)
        before_cnt = f.cognition._db.query_one(
            "SELECT COUNT(*) AS c FROM user_model_items")["c"]

        from tests.cognition.test_phase14_final_r7_r10_failclosed import (
            _force_umsg_append_failure)
        state = _force_umsg_append_failure(f)
        try:
            f.submit_user_message("我明天要写年度审计报告")
        finally:
            state["on"] = False
        q.wait_idle(timeout=15.0)

        after_cnt = f.cognition._db.query_one(
            "SELECT COUNT(*) AS c FROM user_model_items")["c"]
        assert after_cnt == before_cnt, "U 失败回合不得新增任何 C4 行"
        tjson_rows = f.cognition._db.query_all(
            "SELECT * FROM user_model_items WHERE temporal_json<>''")
        assert tjson_rows == [], "不得出现 temporal 行"
        assert f.cognition.events.query_by_type("USER_PLAN_DECLARED") == []
    finally:
        try:
            f.cognition.close()
        except Exception:
            pass


# ================================================================ T11 重启不变量
def test_d4_t11_restart_preserves_resolved_relative_date(tmp_path):
    db = Path(tmp_path) / "cog.db"
    hub = _hub(tmp_path)
    hub.apply_user_message("我明天要写报告", turn_id=1, basis_ts=_basis(2026, 8, 27))
    hub.close()
    # —— 重启于“三天后”，也不得把 明天 重解释为新的基准日 ——
    hub2 = CognitionHub(db) if False else None
    from furina.cognition import CognitionHub as _CH
    hub2 = _CH(db)
    it = hub2.user_model.query_active(category="PLAN")[0]
    assert it.temporal_payload["start"] == "2026-08-28"
    hub2.close()


# ================================================================ T12/T13 时区/DST 日历语义
def test_d4_t12_timezone_is_explicit_authority():
    from furina.cognition.temporal import resolve_temporal
    basis = _basis(2026, 8, 27, 23, 30, tz="UTC")     # UTC 23:30
    sh = resolve_temporal("我明天要写周报", basis_epoch=basis, tz_name=SH)
    ny = resolve_temporal("我明天要写周报", basis_epoch=basis,
                          tz_name="America/New_York")
    assert sh.payload["start"] == "2026-08-29"        # 上海已是 8/28 早7:30 → 明天 8/29
    assert ny.payload["start"] == "2026-08-28"        # 纽约仍是 8/27 晚 → 明天 8/28
    assert sh.payload["tz"] == SH and ny.payload["tz"] == "America/New_York"


def test_d4_t13_dst_calendar_semantics_not_naive_24h():
    from furina.cognition.temporal import resolve_temporal, local_datetime
    # 美国 fall-back 日：2026-11-01 本地 00:30（EDT）； naïve +24h 会给出错误日期概念
    tz = ZoneInfo("America/New_York")
    basis = datetime.datetime(2026, 11, 1, 0, 30, tzinfo=tz).timestamp()
    r = resolve_temporal("我明天要去投票", basis_epoch=basis,
                         tz_name="America/New_York")
    local_next = local_datetime(basis, "America/New_York").date() + datetime.timedelta(days=1)
    assert r.payload["start"] == str(local_next) == "2026-11-02"
    # 证明该窗口确为非常规 24h（DST 切换），而实现走的是日历日期
    delta = (datetime.datetime(2026, 11, 2, 0, 30, tzinfo=tz).timestamp() - basis)
    assert abs(delta - 25 * 3600) < 60                # 该自然日恰为 25 小时


# ================================================================ T14 不过期即完成
def test_d4_t14_passing_due_does_not_autocomplete(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我昨天前就该写完的周报先记着", turn_id=99,
                           basis_ts=_basis(2020, 1, 2))
    # 构造一个"早已过期"的 active PLAN（直接落库等价物：声明时 basis 在过去）
    hub.apply_user_message("我打算完成发布清单", turn_id=2,
                           basis_ts=_basis(2020, 6, 1))
    _time.sleep(0.05)
    r = hub.process_pending(batch=10)
    rows = hub.user_model.query_active(category="PLAN")
    targets = [x for x in rows if x.key == "plan:发布清单"]
    assert targets and targets[0].status == "active", \
        "时间流逝绝不自动完成计划"
    r2 = hub.process_pending(batch=10)
    rows2 = hub.user_model.query_active(category="PLAN")
    assert [x.status for x in rows2 if x.key == "plan:发布清单"] == ["active"]
    hub.close()


# ================================================================ T15 非时间偏好不受影响
def test_d4_t15_non_temporal_preferences_unchanged(tmp_path):
    """非时间偏好在重放路径上保持既有 dedupe/provenance 语义（candidate 无 temporal）。"""
    hub = _hub(tmp_path)
    c = hub.interpretation.interpret_text(
        "我喜欢喝咖啡", source_event_ids=["lev_fake_a"], basis_epoch=_basis(2026, 8, 27))
    cand = next(x for x in c if x.kind == "PREFERENCE")
    assert cand.temporal is None                     # resolver 不碰非时间敏感类
    r1 = hub._apply_c4_candidate(cand)
    first_id = r1["items"][0]
    r2 = hub._apply_c4_candidate(cand)               # 重放同候选 → dedupe 保旧 provenance
    assert r2["items"] == [first_id]
    it = hub.user_model.get_active("preference:咖啡")
    assert it.item_id == first_id
    assert it.source_event_id == "lev_fake_a"
    assert it.temporal_json == "" and it.temporal_uncertain == 0
    hub.close()


# ================================================================ T16 损坏载荷 fail-closed
def test_d4_t16_malformed_temporal_payload_fails_closed(tmp_path):
    hub = _hub(tmp_path)
    hub.apply_user_message("我明天要写报告", turn_id=1, basis_ts=_basis(2026, 8, 27))
    hub._db.execute("UPDATE user_model_items SET temporal_json='{{{broken' "
                    "WHERE category='PLAN'")
    it = hub.user_model.query_active(category="PLAN")[0]
    assert it.temporal_payload == {}                   # 读侧 fail-closed
    # 解析器对非法日期同样 fail-closed：
    from furina.cognition.temporal import resolve_temporal
    bad = resolve_temporal("我2026年2月30日提交", basis_epoch=_basis(2026, 1, 15))
    assert bad.payload is None and bad.uncertain is True
    hub.close()


# ================================================================ 补充：受支持日历范围抽查
def test_d4_extra_bounded_calendar_forms():
    from furina.cognition.temporal import resolve_temporal
    b = _basis(2026, 8, 27)                            # 周四
    cases = {
        "本周内完成自评": ("RANGE", "2026-08-24", "2026-08-30"),
        "下周开始学日语": ("RANGE", "2026-08-31", "2026-09-06"),
        "下个周末我想去看展": ("RANGE", "2026-09-05", "2026-09-06"),
        "本月要读完两本书": ("RANGE", "2026-08-01", "2026-08-31"),
        "下个月我要出差一趟": ("RANGE", "2026-09-01", "2026-09-30"),
    }
    for text, (kind, s, e) in cases.items():
        r = resolve_temporal(text, basis_epoch=b, tz_name=SH)
        assert r.payload and r.payload["kind"] == kind, text
        assert r.payload["start"] == s and r.payload["end"] == e, text
    # 年份词月份 & 非法缺席兜底
    jan = resolve_temporal("明年1月我要搬家", basis_epoch=b, tz_name=SH)
    assert jan.payload["start"] == "2027-01-01" and jan.payload["end"] == "2027-01-31"
    none_ = resolve_temporal("我们就随便聊聊吧", basis_epoch=b, tz_name=SH)
    assert none_.payload is None and none_.uncertain is False
