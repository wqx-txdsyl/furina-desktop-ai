"""Relationship Engine（Phase 04）—— 把关系从"统计变量+线性乘数"升级为真正会演化的动态系统。

区分短期状态（变化快、恢复快）与长期关系（变化慢、需积累）：
  短期：annoyance / interaction_tolerance / social_confidence
  长期：familiarity / trust / comfort

事件 → 维度变化 → 恢复（decay）→ 反哺 Motivation（按维度，非统一好感度）。
核心设计：
  ① 正向互动形成长期反馈（familiarity/comfort/confidence 渐进上升；trust 慢速）。
  ② 拒绝/负向形成渐进收敛（annoyance↑, tolerance↓, confidence↓；只有严重/连续才动 trust/comfort）。
  ③ 可恢复（一段时间无负向 → annoyance/tolerance 回落；positive → comfort/confidence 重建）。
  ④ 关系 History 反哺未来 Motivation（按维度语义作用）。
  ⑤ 与 Personality 交互（关系改变人格的表达方式，而非覆盖人格）。

纯确定性，不用 LLM。
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from furina.memory.memory_types import RelationshipState


# 事件类型
EV_POSITIVE_RESPONSE = "positive_response"    # 用户积极回应
EV_USER_INITIATED = "user_initiated"          # 用户主动发起
EV_ACCEPTED_INVITATION = "accepted_invitation"
EV_POSITIVE_TOUCH = "positive_touch"          # 摸头等
EV_SUCCESSFUL_HELP = "successful_help"        # 成功帮忙
EV_LONG_POSITIVE_SESSION = "long_positive_session"
EV_REJECT = "reject"                          # 用户拒绝
EV_IGNORE = "ignore"                          # 用户忽略
EV_CANCEL = "cancel"                          # 用户取消请求
EV_FAILED_HELP = "failed_help"                # 帮忙失败
EV_NEGATIVE_RESPONSE = "negative_response"

# D5 — 事件族（anti-spam 饱和的单位；**不同族绝不共享饱和计数**）。
# positive_touch（pet-like）独立成族：猛摸不会错误压制 successful_help / 社交正向。
# successful_help / failed_help **相反语义，拆分独立族**：帮忙成功的饱和绝不允许
# 压制一次真实失败的负向影响（反之亦然）。负向事件统一为 negative 族。
EVENT_FAMILIES: Dict[str, str] = {
    EV_POSITIVE_RESPONSE: "positive_social",
    EV_USER_INITIATED: "positive_social",
    EV_ACCEPTED_INVITATION: "positive_social",
    EV_LONG_POSITIVE_SESSION: "positive_social",
    EV_POSITIVE_TOUCH: "positive_touch",
    EV_SUCCESSFUL_HELP: "help_success",
    EV_FAILED_HELP: "help_failure",
    EV_REJECT: "negative",
    EV_IGNORE: "negative",
    EV_CANCEL: "negative",
    EV_NEGATIVE_RESPONSE: "negative",
}

# D5 参数（均可注入；确定性）：
# 短窗口（秒）+ 窗口内每次同族事件的递减底数 + 每族保留最近时间戳的硬容量。
# 账本 = per-family deque(maxlen=max_hits_per_family)：窗口内事件数线性增长被硬容量
# 截断 → 总 ledger 长度 ≤ distinct_families × max_hits_per_family，确定性有界。
DEFAULT_ANTISPAM_WINDOW_SECONDS = 120.0
DEFAULT_DIMINISH_BASE = 0.5
DEFAULT_MAX_HITS_PER_FAMILY = 64


def event_family(event: str) -> str:
    """事件 → 饱和族。未知事件按自身 event 名成独立族（其 delta 为空 → 天然 no-op，
    且永远不会创建 family 账本条目）。"""
    return EVENT_FAMILIES.get(event, event)

# canonical raw 单位（C-R2 §3）。任何生产消费者（Dialogue/Embodiment/Motivation/Persona appraisal）
# 必须只经由 relationship_factors() 拿归一化 0..1；**禁止**在别处重复实现单位转换。
#   0..100 raw: familiarity/trust/comfort/attachment/respect/dependency/annoyance/
#               interaction_tolerance/social_confidence
#   0..1  raw : user_response_rate / user_rejection_rate
#   派生     : response_rate / confidence / interaction_freq（0..1）
_HUNDRED_SCALE = ("familiarity", "trust", "comfort", "attachment", "respect", "dependency",
                  "annoyance", "interaction_tolerance", "social_confidence")


def relationship_factors(rel) -> dict:
    """唯一的 canonical 关系归一化实现（0..1 consumer contract）。

    rel 可为 RelationshipState / dict / None。None/缺失字段用**中性默认**（rate .5、置信 .5、接纳度 .5），
    避免"无关系"时 principal 全 0 + confidence 1.0 的假象把行为打偏。
    """
    def _get(k: str) -> float:
        if rel is None:
            return 0.0
        if isinstance(rel, dict):
            return float(rel.get(k, 0.0) or 0.0)
        return float(getattr(rel, k, 0.0) or 0.0)

    neutral = {"response_rate": 0.5, "confidence": 0.5, "interaction_tolerance": 0.5,
               "social_confidence": 0.5, "interaction_freq": 0.0}
    out: dict = {}
    for k in ("familiarity", "trust", "comfort", "attachment", "respect", "dependency",
              "annoyance", "interaction_tolerance", "social_confidence",
              "user_response_rate", "user_rejection_rate"):
        v = _get(k)
        if not _has_field(rel, k) and k in ("interaction_tolerance", "social_confidence"):
            v = 50.0   # neutral 0-100
        if k in _HUNDRED_SCALE:
            v = v / 100.0   # 0-100 → 0..1
        out[k] = max(0.0, min(1.0, v))
    out["response_rate"] = out["user_response_rate"] if _has_field(rel, "user_response_rate") else neutral["response_rate"]
    out["confidence"] = (max(0.0, min(1.0, 1.0 - out["user_rejection_rate"]))
                         if _has_field(rel, "user_rejection_rate") else neutral["confidence"])
    out["interaction_freq"] = neutral["interaction_freq"]
    return out


def _has_field(rel, k: str) -> bool:
    if rel is None:
        return False
    if isinstance(rel, dict):
        return k in rel
    return hasattr(rel, k)


class RelationshipEngine:
    """关系演化引擎（确定性）。持有 RelationshipState，变更 + 恢复 + 供 Motivation 读。"""

    # 长期维度：需要积累，慢速变化，不被轻微互动快速刷满
    LONG_TERM = ("familiarity", "trust", "comfort")
    # 短期维度：变化快、恢复快
    SHORT_TERM = ("annoyance", "interaction_tolerance", "social_confidence")

    def __init__(self, state: Optional[RelationshipState] = None, *,
                 window_seconds: float = DEFAULT_ANTISPAM_WINDOW_SECONDS,
                 diminish_base: float = DEFAULT_DIMINISH_BASE,
                 max_hits_per_family: int = DEFAULT_MAX_HITS_PER_FAMILY,
                 time_fn: Optional[Any] = None) -> None:
        self.state = state or RelationshipState()
        # D5 anti-spam（有界 operational 状态，纯内存；无 schema、无持久化）：
        # per-family deque(maxlen) —— 每族只保留最近 max_hits_per_family 个时间戳，
        # 持续 spam 也会持续更新（append 自动淘汰最旧），绝不因满容量停止记账。
        # window=0 → 关闭饱和（恢复旧线性行为，仅用于测试/诊断对照）。
        self._window = float(max(0.0, window_seconds))
        self._base = float(max(0.0, min(1.0, diminish_base)))
        self._max_hits = int(max(1, max_hits_per_family))
        self._time_fn = time_fn or time.monotonic
        self._family_hits: Dict[str, deque] = {}   # family → 窗口内最近时间戳（有界）

    # -------------------------------------------------- 归一化 consumer 契约（C-R2 唯一实现）
    @property
    def _HUNDRED_SCALE(self):
        return _HUNDRED_SCALE

    def factors(self) -> Dict[str, float]:
        """归一化 0..1 关系因子（**唯一** canonical 实现 = relationship_factors）。"""
        return relationship_factors(self.state)

    # -------------------------------------------------- 事件 → 维度增量（渐进，非一次跳满）
    def _event_delta(self, event: str) -> Dict[str, float]:
        d: Dict[str, float] = {}
        if event == EV_POSITIVE_RESPONSE:
            d = {"familiarity": 3.5, "comfort": 5.0, "social_confidence": 5.0,
                 "interaction_tolerance": 4.0, "user_response_rate": 0.05}   # C-R2：rate=0..1，小增量
        elif event == EV_USER_INITIATED:
            d = {"familiarity": 4.0, "comfort": 4.5, "social_confidence": 4.0,
                 "interaction_tolerance": 3.0}
        elif event == EV_ACCEPTED_INVITATION:
            d = {"familiarity": 3.5, "comfort": 4.0, "social_confidence": 4.5}
        elif event == EV_POSITIVE_TOUCH:
            d = {"familiarity": 2.5, "comfort": 6.0, "social_confidence": 3.0,
                 "user_response_rate": 0.04}   # C-R2 0..1
        elif event == EV_SUCCESSFUL_HELP:
            d = {"respect": 3.0, "trust": 2.0, "comfort": 3.0, "social_confidence": 4.0}   # trust 慢速
        elif event == EV_LONG_POSITIVE_SESSION:
            d = {"familiarity": 5.0, "comfort": 6.0, "trust": 1.2, "social_confidence": 3.0}
        elif event == EV_REJECT:
            d = {"annoyance": 7.0, "interaction_tolerance": -6.0, "social_confidence": -4.0,
                 "user_rejection_rate": 0.05, "rejection_count": 1.0}   # C-R2 0..1 + count
        elif event == EV_IGNORE:
            d = {"annoyance": 4.0, "interaction_tolerance": -3.0, "social_confidence": -2.5}
        elif event == EV_CANCEL:
            d = {"annoyance": 3.0, "interaction_tolerance": -2.0, "social_confidence": -2.0}
        elif event == EV_FAILED_HELP:
            d = {"annoyance": 4.5, "social_confidence": -4.0, "trust": -0.8}   # 连续才动 trust
        elif event == EV_NEGATIVE_RESPONSE:
            d = {"annoyance": 5.0, "interaction_tolerance": -4.0, "social_confidence": -3.5}
        return d

    # -------------------------------------------------- D5 anti-spam：事件族饱和（deterministic/bounded/time-aware）
    def _now(self) -> float:
        try:
            return float(self._time_fn())
        except Exception:
            return 0.0

    def _family_multiplier(self, family: str) -> float:
        """窗口内同族已发生次数 k → 本次影响乘数 base**k（首次=1.0，完全不受削弱）。

        rolling window + 硬容量：时间戳按序入队，过期者从队首逐出；deque(maxlen)
        保证每族至多保留最近 max_hits_per_family 个 → 持续 spam 时乘数被 0.5^容量
        封底（≈0），总影响几何有界；窗口滚动逐出旧事件 → 影响**逐步**恢复。
        记录发生在计算乘数之后（本次事件计入后续事件的 k）。
        """
        if self._window <= 0:
            return 1.0
        now = self._now()
        hits = self._family_hits.setdefault(family, deque(maxlen=self._max_hits))
        while hits and now - hits[0] >= self._window:
            hits.popleft()                             # 逐出窗口外旧事件
        k = len(hits)
        hits.append(now)                               # 满容量自动淘汰最旧（持续更新）
        return self._base ** k

    def saturation_snapshot(self) -> Dict[str, List[float]]:
        """诊断视图：各事件族当前保留的时间戳（OPERATIONAL / 非真值；用于测试与审计）。"""
        return {f: list(ts) for f, ts in self._family_hits.items()}

    def apply(self, event: str, strength: float = 1.0, reason: str = "") -> Dict[str, float]:
        """应用一个关系事件（渐进）。

        返回值 = 基础事件 delta × anti-spam 饱和乘数（round 3 位）；**不含** strength、
        LONG_TERM/trust 乘数与 clamp —— 实际 state 落地是 v×strength×mult 经 _bump
        按字段单位 clamp 后的结果，不可把返回值当作完整 state 差值。
        """
        delta = self._event_delta(event)
        if not delta:
            return {}                                   # 未知事件安全 no-op（不创建/污染 family）
        # D5：短窗口内同族重复 → 本次影响确定性递减（首次=1.0；总影响有界 ≈ 1/(1-base) 倍单次）
        mult = self._family_multiplier(event_family(event))
        # 长期维度慢速：familiarity/comfort 可较快积累，trust 格外慢（不能一次刷满）
        for k, v in delta.items():
            if k == "trust":
                v *= 0.5      # trust 格外慢速（需要长期稳定正向）
            elif k in self.LONG_TERM:
                v *= 0.7
            self._bump(k, v * strength * mult)
        self.state.last_interaction_ts = self.state.last_interaction_ts
        return {k: round(v * mult, 3) for k, v in delta.items()}

    def _bump(self, key: str, delta: float) -> None:
        """按字段 unit 夹紧（C-R2 §4）：rate 字段 0..1；0-100 字段 0..100；计数 ≥0；时间戳原样。"""
        if not hasattr(self.state, key):
            return
        cur = float(getattr(self.state, key) or 0.0) + delta
        if key in ("user_response_rate", "user_rejection_rate"):
            val = max(0.0, min(1.0, cur))
        elif key in _HUNDRED_SCALE:
            val = max(0.0, min(100.0, cur))
        elif key.endswith("_count") or key == "rejection_count":
            val = max(0.0, cur)
        elif key == "last_interaction_ts":
            val = float(getattr(self.state, key) or 0.0)
        else:
            val = cur
        setattr(self.state, key, val)

    # -------------------------------------------------- 恢复（decay）：负向状态自然回落
    def decay(self, dt: float = 3.0) -> None:
        """随时间恢复：无负向事件时 annoyance 回落、tolerance/confidence 回归基线。

        短期维度随时间回归中性；长期维度（familiarity/trust/comfort）基本保留（关系是积累）。
        """
        k = min(1.0, dt / 120.0)   # 每 120s 回归一小步
        st = self.state
        # 短期：annoyance 回落、tolerance/confidence 向中性回弹
        st.annoyance = max(0.0, st.annoyance * (1 - 0.05 * k))
        st.interaction_tolerance = max(0.0, min(100.0,
            st.interaction_tolerance + (50.0 - st.interaction_tolerance) * 0.03 * k))
        st.social_confidence = max(0.0, min(100.0,
            st.social_confidence + (40.0 - st.social_confidence) * 0.03 * k))
        # 长期维度只做极缓慢的保守衰减（避免关系永久贴 100 或 0 的 runaway）
        for f in ("trust", "comfort"):
            val = getattr(st, f)
            setattr(st, f, max(0.5, min(99.5, val)))   # 保留但夹住不 runaway
        # 统计随时间滚动（interaction_count 按小时窗户简化衰减）
        st.interaction_count_1h = max(0.0, st.interaction_count_1h - 0.5 * k)
        st.interaction_count_24h = max(0.0, st.interaction_count_24h - 0.1 * k)

