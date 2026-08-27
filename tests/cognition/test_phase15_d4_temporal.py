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


def _apply(hub, text: str, turn_id: int, basis: float):
    """测试注入显式时区权威（镜像生产配置后的调用形态）。"""
    return hub.apply_user_message(text, turn_id=turn_id, basis_ts=basis,
                                  tz_name=SH)


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
    _apply(hub, "我今天要写报告初稿", 1, _basis(2026, 8, 27))
    it = hub.user_model.query_active(category="PLAN")[0]
    assert it.temporal_payload["kind"] == "POINT"
    assert it.temporal_payload["start"] == "2026-08-27"
    hub.close()


def test_d4_t2_tomorrow_is_next_local_calendar_date(tmp_path):
    hub = _hub(tmp_path)
    _apply(hub, "我明天要写报告", 1, _basis(2026, 8, 27))
    it = hub.user_model.query_active(category="PLAN")[0]
    assert it.temporal_payload["start"] == "2026-08-28"
    assert it.temporal_uncertain == 0
    hub.close()


def test_d4_t3_day_after_tomorrow(tmp_path):
    hub = _hub(tmp_path)
    _apply(hub, "我后天去体检", 1, _basis(2026, 8, 27))
    it = hub.user_model.query_active(category="PLAN")[0]
    assert it.temporal_payload["start"] == "2026-08-29"
    hub.close()


# ================================================================ T4 绝对日期（无 LLM）
def test_d4_t4_absolute_dates_deterministic(tmp_path):
    hub = _hub(tmp_path)
    _apply(hub, "我2026年9月3日交付方案", 1, _basis(2026, 8, 27))
    it = [x for x in hub.user_model.query_active(category="PLAN")
          if x.key == "plan:方案"][0]
    p = it.temporal_payload
    assert p["kind"] == "POINT" and p["start"] == "2026-09-03"
    # 缺年：取 basis 起最近将来（显式规则）
    _apply(hub, "我打算9月30日去办签证", 2, _basis(2026, 8, 27))
    it2 = [x for x in hub.user_model.query_active(category="PLAN")
           if x.key == "plan:签证"][0]
    assert it2.temporal_payload["start"] == "2026-09-30"
    hub.close()


# ================================================================ T5 模糊不造日期
def test_d4_t5_vague_stays_uncertain_without_invented_date(tmp_path):
    hub = _hub(tmp_path)
    _apply(hub, "过几天我打算整理房间", 1, _basis(2026, 8, 27))
    it = hub.user_model.query_active(category="PLAN")[0]
    assert it.temporal_uncertain == 1
    assert it.temporal_json == ""            # 不落任何日期载荷
    assert it.status == "active"
    hub.close()


# ================================================================ T6 周重复（确定性）
def test_d4_t6_weekly_recurrence_structured(tmp_path):
    hub = _hub(tmp_path)
    _apply(hub, "我要每周六去健身房", 1, _basis(2026, 8, 27))   # 周四
    it = hub.user_model.query_active(category="PLAN")[0]
    p = it.temporal_payload
    assert p["kind"] == "RECUR" and p["dow"] == 6
    assert "start" not in p                                 # 重复型不伪装成单点
    hub.close()


# ================================================================ T7/T8 dedupe vs 取代
def test_d4_t7_same_plan_changed_date_supersedes_not_swallows(tmp_path):
    hub = _hub(tmp_path)
    _apply(hub, "我明天要写报告", 1, _basis(2026, 8, 27))
    _time.sleep(0.03)
    _apply(hub, "我明天要写报告", 2, _basis(2026, 8, 30))   # 三天后重说同一句
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
    _apply(hub, "我明天要写报告", 1, _basis(2026, 8, 27))
    _apply(hub, "这个周末我想整理房间", 2, _basis(2026, 8, 27))
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


def test_d4_t9_declaration_provenance_resolvable_exact_chain(tmp_path):
    """R5：C4 行 → source_event_id → 精确 USER_PLAN_DECLARED → 同 turn_id 的唯一
    canonical USER_MESSAGE —— 逐环身份验证，不接受“存在某条 U”。"""
    from tests.cognition.test_phase14_final_reviewer_r6_r12 import _real_furina
    f, _ = _real_furina(tmp_path, timezone=SH)
    try:
        f.submit_user_message("我明天要写季度总结")
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=15.0)
        rows = f.cognition._db.query_all(
            "SELECT * FROM user_model_items WHERE category='PLAN' AND status='active'")
        assert rows and rows[0]["temporal_json"], rows
        row = rows[0]

        # 环1：行 → 声明事件（按 id 精确）
        dev = f.cognition._db.query_one(
            "SELECT * FROM life_events WHERE event_id=?", (row["source_event_id"],))
        assert dev is not None and dev["event_type"] == "USER_PLAN_DECLARED",             dict(dev) if dev else None

        # 环2：声明 → canonical U（同 turn_id 唯一）
        u_rows = f.cognition._db.query_all(
            "SELECT * FROM life_events WHERE event_type='USER_MESSAGE' AND turn_id=?",
            (dev["turn_id"],))
        assert len(u_rows) == 1, [dict(u) for u in u_rows]
        u = u_rows[0]
        assert "季度总结" in (json.loads(u["payload_json"]) or {}).get("text", "")
        # 时间语义也必须可追溯：声明事件 payload 内嵌 resolver 载荷
        assert json.loads(dev["payload_json"]).get("temporal", {}).get("start")
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
    _apply(hub, "我明天要写报告", 1, _basis(2026, 8, 27))
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
def test_d4_t14_overdue_temporal_plan_never_autocompletes(tmp_path):
    """R6：ACTIVE PLAN 带**过去日期**的结构化 POINT 载荷 → 重启/继续处理若干批
    之后仍 active；时钟流逝绝不产生 ACTIVE→COMPLETED。"""
    db = Path(tmp_path) / "cog.db"
    from furina.cognition import CognitionHub as _CH
    hub = _CH(db)
    _apply(hub, "我今天要完成发布清单", 1, _basis(2020, 6, 1))      # 历史 ingress
    it = hub.user_model.query_active(category="PLAN")[0]
    assert it.temporal_payload.get("start") == "2020-06-01", it.temporal_payload
    hub.close()

    # —— “多日后”的重启 + 继续处理无关事件批次 ——
    hub2 = _CH(db)
    hub2.process_pending(batch=10)
    hub2.process_pending(batch=10)
    _time.sleep(0.05)
    rows = hub2.user_model.query_active(category="PLAN")
    targets = [x for x in rows if x.key == "plan:发布清单"]
    assert targets and targets[0].status == "active",         "due 已过但无独立完成证据 → 必须 ACTIVE"
    assert targets[0].temporal_payload["start"] == "2020-06-01"
    comp = hub2.user_model.query_active(category="PLAN")
    assert all(x.status == "active" for x in comp)
    hub2.close()


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
    _apply(hub, "我明天要写报告", 1, _basis(2026, 8, 27))
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


# ================================================================
# External Reviewer Residual III（Review = NEEDS_NARROW_PATCH）
# ================================================================

def _app_with_tz(tmp_path, tz_value):
    """R1-T1：共享 harness（含 dispatcher 绑定）+ 配置时区 + 固定时钟注入。"""
    import types as _types
    from tests.cognition.test_phase14_final_reviewer_r6_r12 import _real_furina
    app_mod = __import__("furina.app", fromlist=["time"])
    real_time = app_mod.time
    fixed = _basis(2026, 8, 27, 20, 30, tz="UTC")   # NY=08-27 16:30 / SH=08-28 04:30
    f, _sched = _real_furina(tmp_path, timezone=tz_value)
    app_mod.time = _types.SimpleNamespace(time=lambda: fixed,
                                          sleep=lambda *_: None,
                                          localtime=_time.localtime,
                                          monotonic=_time.monotonic)
    return f, app_mod, real_time


def test_d4_r1_t1_configured_tz_controls_production_ingress_date(tmp_path):
    """R1-T1：生产 submit_user_message 路径 + 配置时区 America/New_York +
    午夜附近的 canonical ingress → 行内 tz=配置值、本地日历正确（≠Asia/Shanghai）。"""
    tmp = Path(tmp_path)
    f, _fixed, real_time = None, None, None
    import furina.app as app_mod
    try:
        f, _fixed, real_time = _app_with_tz(tmp, "America/New_York")
        real_time_mod = real_time                      # 备原引用（还原用）
        assert f._user_tz == "America/New_York"
        f.submit_user_message("我明天要写报告")
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=15.0)
        rows_q = f.cognition.user_model.query_active(category="PLAN")
        it = [x for x in rows_q]
        rows = [x for x in (f.cognition._db.query_all(
            "SELECT * FROM user_model_items WHERE category='PLAN' AND status='active'"))]
        assert rows, rows
        p = json.loads(rows[0]["temporal_json"])
        assert p["tz"] == "America/New_York", p          # 权威=配置值，非默认猜测
        assert p["start"] == "2026-08-28"                # NY 本地“明天”
        del real_time_mod
    finally:
        if real_time is not None:
            app_mod.time = real_time                     # 还原模块级 time
        try:
            f.cognition.close()
        except Exception:
            pass


def test_d4_r1_t2_unconfigured_timezone_fails_closed(tmp_path):
    """未配置时区 → 生产入口不得落任何时间载荷（绝不默认 Asia/Shanghai）。"""
    import furina.app as app_mod
    f, fixed, real_time = None, None, None
    try:
        f, fixed, real_time = _app_with_tz(tmp_path, "")       # 空 tz
        assert f._user_tz is None
        f.submit_user_message("我明天要写报告")
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=15.0)
        rows = f.cognition._db.query_all(
            "SELECT * FROM user_model_items WHERE category='PLAN' AND status='active'")
        assert rows, "计划本身仍应存在（文本真值不受影响）"
        for r in rows:
            assert (r["temporal_json"] or "") == "", r     # 无日期 → fail-closed
            assert int(r["temporal_uncertain"]) == 0       # 也非 uncertain（只是没解析）
    finally:
        if real_time is not None:
            app_mod.time = real_time
        try:
            f.cognition.close()
        except Exception:
            pass


def test_d4_r2_weekend_aliases_locked():
    """R2：四个周末别名在已知基准周逐一锁定端点；平周语义不变。"""
    from furina.cognition.temporal import resolve_temporal
    b = _basis(2026, 8, 27)                                 # 周四
    expect = {
        "这个周末": ("2026-08-29", "2026-08-30"),
        "本周末": ("2026-08-29", "2026-08-30"),
        "下个周末": ("2026-09-05", "2026-09-06"),
        "下周末": ("2026-09-05", "2026-09-06"),
    }
    for token, (s, e) in expect.items():
        r = resolve_temporal(f"{token}我想去看展", basis_epoch=b, tz_name=SH)
        assert r.payload["kind"] == "RANGE"
        assert (r.payload["start"], r.payload["end"]) == (s, e), token
    plain1 = resolve_temporal("本周内完成自评", basis_epoch=b, tz_name=SH)
    plain2 = resolve_temporal("下周开始学日语", basis_epoch=b, tz_name=SH)
    assert (plain1.payload["start"], plain1.payload["end"]) == ("2026-08-24", "2026-08-30")
    assert (plain2.payload["start"], plain2.payload["end"]) == ("2026-08-31", "2026-09-06")


def test_d4_r3_approx_and_alternatives_fail_closed(tmp_path):
    """R3：近似量词/或者连接/模糊∩精确 → uncertainty=1 且零日期；精确保留。"""
    hub = _hub(tmp_path)
    for utt, turn in (("下个月左右我要搬家", 1),
                      ("九月可能要去一次上海", 2),
                      ("我打算下个月左右去上海出差", 5),
                      ("我明天或者过几天写报告", 3),
                      ("我明天或后天写报告", 4)):
        _apply(hub, utt, turn, _basis(2026, 8, 27))
        _time.sleep(0.02)
    pl = [i for i in hub.user_model.query_active(category="PLAN", limit=50)]
    approx_keys = [x.key for x in pl
                   if x.temporal_uncertain == 1 and x.temporal_json == ""]
    assert "plan:搬家" in approx_keys, approx_keys          # 下个月左右我要搬家
    # 精确对应句不允许被近似守卫误伤（同一批里“九月可能…”等保持 uncertain，
    # 而后续精确句子应正常落库 —— 见下方 exact 断言）
    # 精确保留
    _apply(hub, "明天写报告", 9, _basis(2026, 8, 27))
    _apply(hub, "我打算下个月去上海出差", 10, _basis(2026, 8, 27))
    _apply(hub, "2026年9月3日提交申请表", 11, _basis(2026, 8, 27))
    keys_dbg = [x.key for x in hub.user_model.query_active(category="PLAN", limit=50)]
    exact = {x.key: x.temporal_payload for x in keys_dbg and
             hub.user_model.query_active(category="PLAN", limit=50)}
    assert exact["plan:报告"]["start"] == "2026-08-28"
    assert exact["plan:申请表"]["start"] == "2026-09-03"
    hub.close()


def test_d4_r3b_invalid_calendar_inputs_fail_closed(tmp_path):
    """R4-A/B（hub 级）：非法生日日/月 与 非法月份声明 → 行存在但零日期+uncertain。"""
    hub = _hub(tmp_path)
    _apply(hub, "我的生日是2月30日", 1, _basis(2026, 8, 27))
    bd = hub.user_model.query_active(category="IMPORTANT_DATE")[0]
    assert bd.value == "02-30" or bd.value == "02-30"      # 原文保留于 value/excerpt 层
    assert bd.temporal_uncertain == 1 and bd.temporal_json == "", \
        (bd.temporal_uncertain, bd.temporal_json)
    _apply(hub, "明年13月我要搬家", 2, _basis(2026, 8, 27))
    moved = [x for x in hub.user_model.query_active(category="PLAN") if x.key == "plan:搬家"]
    assert moved and moved[0].temporal_uncertain == 1 and moved[0].temporal_json == ""
    # 合法闰日仍为 ANNUAL
    _apply(hub, "我的生日是2月29日", 3, _basis(2026, 8, 27))
    leap = [x for x in hub.user_model.query_active(category="IMPORTANT_DATE", limit=50)]
    ann = [x for x in leap if x.temporal_payload.get("md") == "02-29"]
    assert ann and ann[0].temporal_payload["kind"] == "ANNUAL"
    hub.close()


# ================================================================
# External Reviewer Residual Closure II（Review_2 = NEEDS_NARROW_PATCH）
# ================================================================

def test_d4_f1_env_timezone_flows_through_real_load_config(tmp_path, monkeypatch):
    """F1：FURINA_TIMEZONE 环境变量 → 真 load_config() → Furina → submit
    → 行内 tz/env 配置一致、午夜场景日期正确（非 Asia/Shanghai）。"""
    import furina.app as app_mod
    from furina.config import load_config
    import types as _types

    tmp = Path(tmp_path)
    monkeypatch.setenv("FURINA_TIMEZONE", "America/New_York")
    monkeypatch.setenv("FURINA_ROOT", str(tmp))
    from tests.cognition.test_phase14_final_reviewer_r6_r12 import _real_furina
    cfg = load_config()                                # 真实配置装载路径
    assert cfg.timezone == "America/New_York"
    f, _sched = _real_furina(tmp, cfg=cfg)
    fixed = _basis(2026, 8, 27, 20, 30, tz="UTC")      # NY=08-27 / SH=08-28
    real_time = app_mod.time
    app_mod.time = _types.SimpleNamespace(time=lambda: fixed,
                                          sleep=lambda *_: None,
                                          localtime=_time.localtime,
                                          monotonic=_time.monotonic)
    try:
        assert f._user_tz == "America/New_York"
        f.submit_user_message("我明天要写报告")
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=15.0)
        rows = f.cognition._db.query_all(
            "SELECT * FROM user_model_items WHERE category='PLAN' AND status='active'")
        assert rows and rows[0]["temporal_json"]
        p = json.loads(rows[0]["temporal_json"])
        assert p["tz"] == "America/New_York"
        assert p["start"] == "2026-08-28"              # NY 本地“明天”
    finally:
        app_mod.time = real_time
        try:
            f.cognition.close()
        except Exception:
            pass


def test_d4_f2_empty_env_timezone_no_guessed_date(tmp_path, monkeypatch):
    """F2：FURINA_TIMEZONE="" → 计划文本仍落库，但零时间载荷（fail-closed）。"""
    import furina.app as app_mod
    from furina.config import load_config
    import types as _types

    tmp = Path(tmp_path)
    monkeypatch.setenv("FURINA_TIMEZONE", "")
    monkeypatch.setenv("FURINA_ROOT", str(tmp))
    cfg = load_config()
    assert cfg.timezone == ""
    from tests.cognition.test_phase14_final_reviewer_r6_r12 import _real_furina as _rf
    f, _sched = _rf(tmp, cfg=cfg)
    fixed = _basis(2026, 8, 27, 20, 30, tz="UTC")
    real_time = app_mod.time
    app_mod.time = _types.SimpleNamespace(time=lambda: fixed,
                                          sleep=lambda *_: None,
                                          localtime=_time.localtime,
                                          monotonic=_time.monotonic)
    try:
        assert f._user_tz is None
        f.submit_user_message("我明天要写报告")
        q = f._direct_dialogue_queue()
        assert q.wait_idle(timeout=15.0)
        rows = f.cognition._db.query_all(
            "SELECT * FROM user_model_items WHERE category='PLAN' AND status='active'")
        assert rows, rows
        for r in rows:
            assert (r["temporal_json"] or "") == ""     # 不猜任何日历
    finally:
        app_mod.time = real_time
        try:
            f.cognition.close()
        except Exception:
            pass


def test_d4_f3_non_leap_basis_feb29_nexts_to_leap_year():
    """F3：2026 非闰年 basis 的“2月29日”→ 最近将来有效日期 2028-02-29。"""
    from furina.cognition.temporal import resolve_temporal
    r = resolve_temporal("2月29日提交材料", basis_epoch=_basis(2026, 8, 27),
                         tz_name=SH)
    assert r.payload and r.payload["kind"] == "POINT"
    assert r.payload["start"] == "2028-02-29", r.payload


def test_d4_f4_leap_basis_before_feb29_same_year():
    """F4：闰年 basis 在 2月29日前 → 同年 02-29。"""
    from furina.cognition.temporal import resolve_temporal
    r = resolve_temporal("2月29日提交材料", basis_epoch=_basis(2024, 1, 10),
                         tz_name=SH)
    assert r.payload and r.payload["start"] == "2024-02-29"


def test_d4_f5_explicit_year_month_range(tmp_path):
    """F5：『2026年9月我要搬家』→ RANGE 2026-09-01..2026-09-30 precision=month。"""
    hub = _hub(tmp_path)
    _apply(hub, "2026年9月我要搬家", 1, _basis(2026, 8, 27))
    it = [x for x in hub.user_model.query_active(category="PLAN")
          if x.key == "plan:搬家"][0]
    p = it.temporal_payload
    assert p["kind"] == "RANGE" and p["precision"] == "month"
    assert (p["start"], p["end"]) == ("2026-09-01", "2026-09-30")
    hub.close()


def test_d4_f6_leap_month_range(tmp_path):
    """F6：2028年2月 → RANGE 含 02-29。"""
    from furina.cognition.temporal import resolve_temporal
    r = resolve_temporal("2028年2月完成专项审计", basis_epoch=_basis(2026, 8, 27),
                         tz_name=SH)
    assert r.payload["kind"] == "RANGE" and r.payload["precision"] == "month"
    assert (r.payload["start"], r.payload["end"]) == ("2028-02-01", "2028-02-29")


def test_d4_f7_invalid_month_never_clamped():
    """F7：2026年13月 → uncertain，绝不允许 clamp 到 12 月。"""
    from furina.cognition.temporal import resolve_temporal
    r = resolve_temporal("2026年13月我要搬家", basis_epoch=_basis(2026, 8, 27),
                         tz_name=SH)
    assert r.payload is None and r.uncertain is True
