"""Phase 15 D4 — deterministic temporal resolver（候选层，绝不写库）。

职责边界（06 任务书 + 执行令 PART 3-8）：
- 输入 = 用户原句文本 + canonical ingress 时间戳(epoch) + 用户本地时区(IANA 名)；
- 输出 = 结构化 temporal 载荷（candidate 携带）或 uncertain 标记；
- 相对词（今天/明天/后天）只按 ingress 当刻的本地日历解析**一次**并持久化；
  重启后绝不以新的"当前时间"重解释；
- 无 LLM、无网络、无 datetime.now()/date.today()/time.time() —— 基准一律由参数注入。

确定性支持集（PART 7 白名单，超出即 uncertain / None）：
  RELATIVE DAY : 今天 / 明天 / 后天 / 大后天
  ABSOLUTE     : YYYY年M月D日 ; M月D日(号)   （缺年 → 取 basis 起最近的将来日期，
                 该规则显式定义并测试；绝不臆造年份以外的信息）
  WEEK SPAN    : 本周 / 下周 / 这个周末|本周末 / 下个周末|下周末 （周一~周日界）
  MONTH SPAN   : 本月 / 下个月|下月
  RECUR WEEKLY : 每周X / 每个星期X / 每星期X / 每礼拜X
  ANNUAL       : 生日是M月D日（IMPORTANT_DATE 专用窄模式，年度重复为语义自带）

模糊集合（PART 8，一律 temporal_uncertain=true，不造日期）：
  过几天 最近 有空的时候|有空 晚点 以后 月底前后 这阵子 改天
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

DEFAULT_USER_TZ = "Asia/Shanghai"
PAYLOAD_VERSION = 1
_MAX_SUPPORTED_YEAR = 9999      # datetime 模块支持上限（与 MAXYEAR 一致）

_WEEKDAY_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
               "日": 0, "天": 0}

_RELATIVE_DAYS = (("大后天", 3), ("后天", 2), ("明天", 1), ("今天", 0))
_RELATIVE_DAYS_NAMES = tuple(w for w, _o in _RELATIVE_DAYS)
_VAGUE_TOKENS = ("过几天", "有空的时候", "有空", "晚点", "以后", "月底前后",
                 "这阵子", "改天", "最近")
# R3：近似量词（出现在含时间锚的语句中 → 拒绝精确化，uncertain）
_APPROX_TOKENS = ("左右", "大概", "可能", "也许", "差不多", "前后")
_ALT_RE = re.compile(r"或者|或是|还是")
# R2：周末别名（优先于整周判定；逐一锁定四个别名）
_WEEKEND_ALIASES = (("下个周末", True), ("下周末", True),
                    ("这个周末", False), ("本周末", False))
_RECUR_RE = re.compile(r"每(?:个)?(?:周|星期|礼拜)([一二三四五六日天])")
_ABS_FULL_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_ABS_NOYEAR_RE = re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})[日号](?!\d)")
_MONTH_ONLY_RE = re.compile(r"(今年|明年)?\s*(\d{1,2})月(?!\d)")


@dataclass
class TemporalOutcome:
    """resolver 结果：payload=None 且 uncertain=False 表示"本句无时间语义"。"""

    payload: Optional[Dict[str, Any]] = None
    uncertain: bool = False
    matched: str = ""
    notes: Tuple[str, ...] = field(default_factory=tuple)


def _zone(tz_name: str) -> ZoneInfo:
    return ZoneInfo(tz_name or DEFAULT_USER_TZ)


def local_datetime(basis_epoch: float, tz_name: str) -> datetime:
    """canonical ingress epoch → 用户本地墙钟（唯一的本地化入口）。"""
    return datetime.fromtimestamp(float(basis_epoch), _zone(tz_name))


def _iso(d: datetime.date) -> str:
    return d.strftime("%Y-%m-%d")


def _payload(kind: str, *, start: Optional[str] = None, end: Optional[str] = None,
             dow: Optional[int] = None, md: Optional[str] = None,
             precision: str = "day", matched: str = "",
             basis_epoch: float = 0.0, tz_name: str = DEFAULT_USER_TZ,
             year: Optional[int] = None, month: Optional[int] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"v": PAYLOAD_VERSION, "kind": kind,
                           "tz": tz_name, "basis": round(float(basis_epoch), 3)}
    if start:
        out["start"] = start
    if end:
        out["end"] = end
    if dow is not None:
        out["dow"] = int(dow)
    if md:
        out["md"] = md
    if precision != "day":
        out["precision"] = precision
    if year is not None:
        out["year"] = int(year)
    if month is not None:
        out["month"] = int(month)
    if matched:
        out["matched"] = matched[:24]
    return out


# -------------------------------------------------------------- public API
def detect_vague(text: str) -> str:
    """命中模糊时间词则返回该词（即便也有精确表达时不干扰）。"""
    t = text or ""
    for v in _VAGUE_TOKENS:
        if v in t:
            return v
    return ""


def resolve_temporal(text: str, *, basis_epoch: float,
                     tz_name: str = DEFAULT_USER_TZ) -> TemporalOutcome:
    """确定性解析一条用户语句的时间语义。

    规则顺序：模糊先行占位（未见精确规则时）→ 周重复 → 绝对全日期 →
    缺年日期 → 相对日 → 周/月跨度 → 生日(ANNUAL)。首个命中的精确规则生效。
    """
    t = (text or "").strip()
    if not t:
        return TemporalOutcome()
    try:
        local = local_datetime(basis_epoch, tz_name)
    except Exception:
        # 时区不可用 → fail-closed：宁可不确定也不落错误日期（brief §9）
        return TemporalOutcome(uncertain=True, notes=("tz_unavailable",))

    def out(payload: Optional[Dict[str, Any]], *, unc: bool = False,
            matched: str = "", notes: Tuple[str, ...] = ()) -> TemporalOutcome:
        return TemporalOutcome(payload=payload, uncertain=unc, matched=matched,
                               notes=notes)

    # ---- R3 守卫：近似量词 / 或者-连接 / 多个相对日并存 —— 一律拒绝精确化 ----
    approx_hit = next((a for a in _APPROX_TOKENS if a in t), "")
    alt_conn = bool(_ALT_RE.search(t))
    has_anchor = (
        any(w in t for w in _RELATIVE_DAYS_NAMES)
        or "周末" in t or "本周" in t or "这周" in t or "下周" in t
        or "本月" in t or "下个月" in t or "下月" in t
        or bool(_ABS_FULL_RE.search(t)) or bool(_ABS_NOYEAR_RE.search(t))
        or bool(re.search(r"(?:\d{1,2}|[一二三四五六七八九十]{1,3})月", t))
    )
    n_relative = sum(1 for w in _RELATIVE_DAYS_NAMES if w in t)
    if (approx_hit or alt_conn or n_relative >= 2) and \
            (has_anchor or detect_vague(t) or approx_hit):
        reason = ("approximate_expression",) if approx_hit else \
                 ("alternative_temporal_branches",)
        return out(None, unc=True, matched=approx_hit, notes=reason)

    vague = detect_vague(t)

    # 0) annual month-day（生日专用语义：每年度重复，优先于任何通用绝对日期规则）
    #    R4-A：月份/日期确定性校验（Feb 29 以闰年基准视为合法），非法 → uncertain。
    mb = re.search(r"生日(?:是|在)?\s*(\d{1,2})月(\d{1,2})[日号]", t)
    if mb:
        mm, dd = int(mb.group(1)), int(mb.group(2))
        if not 1 <= mm <= 12:
            return out(None, unc=True, matched=mb.group(0),
                       notes=("invalid_month",))
        leap_year = local.year if local.year % 4 == 0 and (
            local.year % 100 != 0 or local.year % 400 == 0) else 2024
        try:
            feb_leap_end = local.replace(year=leap_year, month=2, day=29)
            max_day = 29 if (mm == 2 and feb_leap_end.day == 29) else (
                [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mm - 1])
        except ValueError:
            max_day = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mm - 1]
        if not 1 <= dd <= max_day:
            return out(None, unc=True, matched=mb.group(0),
                       notes=("invalid_day",))
        md = f"{mm:02d}-{dd:02d}"
        return out(_payload("ANNUAL", md=md, matched=mb.group(0),
                            basis_epoch=basis_epoch, tz_name=tz_name))

    # 1) weekly recurrence（每周六 / 每个星期六 …）
    m = _RECUR_RE.search(t)
    if m:
        dow = _WEEKDAY_CN.get(m.group(1))
        if dow is not None:
            p = _payload("RECUR", dow=dow, matched=m.group(0),
                         basis_epoch=basis_epoch, tz_name=tz_name,
                         precision="weekly")
            return out(p)

    # 2) absolute full date（YYYY年M月D日）
    m = _ABS_FULL_RE.search(t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dt = local.replace(year=y, month=mo, day=d)
        except ValueError:
            return out(None, unc=True, matched=m.group(0),
                       notes=("invalid_date",))
        iso = _iso(dt)
        return out(_payload("POINT", start=iso, matched=m.group(0),
                            basis_epoch=basis_epoch, tz_name=tz_name))

    # 2b) explicit year-month（R3：YYYY年M月 → 当月日历 RANGE；月份非法不 clamp）
    m_ym = re.search(r"(\d{4})年(\d{1,2})月(?!\d)", t)
    if m_ym and "日" not in m_ym.group(0):
        y, mo = int(m_ym.group(1)), int(m_ym.group(2))
        if not 1 <= mo <= 12:
            return out(None, unc=True, matched=m_ym.group(0),
                       notes=("invalid_month",))
        try:
            first = local.replace(year=y, month=mo, day=1).date()
        except ValueError:
            return out(None, unc=True, matched=m_ym.group(0),
                       notes=("invalid_date",))
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        return out(_payload("RANGE", start=_iso(first), end=_iso(last),
                            matched=m_ym.group(0), basis_epoch=basis_epoch,
                            tz_name=tz_name, precision="month"))

    # 3) no-year date（M月D日[/号]）：取 basis 起最近将来的**有效**该日期
    #    （R2：2月29日等在缺年场景沿 Gregorian 闰周期向后搜索，永不视为非法；
    #     连续多年都不存在（如 2月30日）→ uncertain。）
    m = _ABS_NOYEAR_RE.search(t)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        # Final calendar off-by-one closure：offset 0..8 **含端点**（共 9 个候选年，
        # 覆盖 Gregorian 世纪边缘最大闰日间隔，如 2096-03-01 basis → 2104-02-29）；
        # 上限贴 datetime.MAXYEAR，越界即 fail-closed。
        year_hi = min(local.year + 8, _MAX_SUPPORTED_YEAR)
        for yy in range(local.year, year_hi + 1):
            try:
                cand = local.replace(year=yy, month=mo, day=d).date()
            except ValueError:
                continue                                    # 该年无此日期
            except OverflowError:
                break                                       # 超出 datetime 支持 → 终止搜索
            if cand >= local.date():
                return out(_payload("POINT", start=_iso(cand), matched=m.group(0),
                                    basis_epoch=basis_epoch, tz_name=tz_name))
        return out(None, unc=True, matched=m.group(0),
                   notes=("invalid_date",))

    # 4) relative days（大后天>后天>明天>今天；最长优先避免"后天"吃掉"大后天"）
    for word, offset in _RELATIVE_DAYS:
        if word in t:
            target = (local + timedelta(days=offset)).date()
            return out(_payload("POINT", start=_iso(target), matched=word,
                                basis_epoch=basis_epoch, tz_name=tz_name))

    # 5) weekend spans（R2：周末别名优先于整周判定；四个别名逐一锁定）
    if "周末" in t:
        this_monday = local.date() - timedelta(days=local.weekday())
        sat = this_monday + timedelta(days=5)
        nxt_sat = sat + timedelta(days=7)
        hit = next((w for w, _n in _WEEKEND_ALIASES if w in t), "")
        is_next = hit in ("下个周末", "下周末")
        s = nxt_sat if is_next else sat
        return out(_payload("RANGE", start=_iso(s), end=_iso(s + timedelta(days=1)),
                            matched=(hit or "周末"), basis_epoch=basis_epoch,
                            tz_name=tz_name))

    # 6) week spans（本周/下周：周一~周日含端点；“…周末”已在上方分支消费）
    if ("本周" in t or "这周" in t) and "周末" not in t:
        this_monday = local.date() - timedelta(days=local.weekday())
        s = this_monday
        return out(_payload("RANGE", start=_iso(s), end=_iso(s + timedelta(days=6)),
                            matched="本周" if "本周" in t else "这周",
                            basis_epoch=basis_epoch, tz_name=tz_name))
    if "下周" in t and "周末" not in t:
        this_monday = local.date() - timedelta(days=local.weekday())
        s = this_monday + timedelta(days=7)
        return out(_payload("RANGE", start=_iso(s), end=_iso(s + timedelta(days=6)),
                            matched="下周", basis_epoch=basis_epoch,
                            tz_name=tz_name))

    # 7) month spans（本月 / 下个月|下月；月末前等模糊归 vague 处理）
    if "下个月" in t or "下月" in t:
        y, mo = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
        first = local.replace(year=y, month=mo, day=1).date()
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        return out(_payload("RANGE", start=_iso(first), end=_iso(last),
                            matched=("下个月" if "下个月" in t else "下月"),
                            basis_epoch=basis_epoch, tz_name=tz_name))
    if "本月" in t:
        first = local.replace(day=1).date()
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        return out(_payload("RANGE", start=_iso(first), end=_iso(last),
                            matched="本月", basis_epoch=basis_epoch, tz_name=tz_name))

    # 8) month-only with explicit year word（今年X月 / 明年X月）
    #    R4-B：用户声明的月份不 clamp —— 非法月份（13月/0月）→ uncertain（不修复）。
    m = _MONTH_ONLY_RE.search(t)
    if m and (m.group(1) or ""):
        y = local.year + (1 if m.group(1) == "明年" else 0)
        mo = int(m.group(2))
        if not 1 <= mo <= 12:
            return out(None, unc=True, matched=m.group(0),
                       notes=("invalid_month",))
        first = local.replace(year=y, month=mo, day=1).date()
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        return out(_payload("RANGE", start=_iso(first), end=_iso(last),
                            matched=m.group(0), basis_epoch=basis_epoch,
                            tz_name=tz_name, precision="month"))

    # 10) 模糊收口：有模糊词但无任何精确规则 → uncertain，不造日期（PART 8/R3）
    if vague:
        return out(None, unc=True, matched=vague, notes=("vague_expression",))
    return out(None)
