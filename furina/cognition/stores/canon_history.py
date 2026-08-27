"""C2 — Canon Life History（只读，runtime writable = NO）。

物理存储：data/canon/furina_life_history.json + furina_life_sources.json（version-controlled）。
不存在于用户可写 SQLite。检索走 CanonLifeRetriever（activation 0..3）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from furina.core import get_logger
from ..models import CanonEpisode

log = get_logger("cognition.canon_history")

_REPO_ROOT = Path(__file__).resolve().parents[3]          # furina/cognition/stores → repo root
_DEFAULT_HISTORY = _REPO_ROOT / "data" / "canon" / "furina_life_history.json"
_DEFAULT_SOURCES = _REPO_ROOT / "data" / "canon" / "furina_life_sources.json"
_DEFAULT_EVIDENCE = _REPO_ROOT / "data" / "canon" / "furina_evidence_units.json"


class CanonHistoryStore:
    """C2 只读 store：加载 + 查询 CanonEpisode（不提供写方法）。"""

    def __init__(self, history_path: Optional[Path] = None,
                 sources_path: Optional[Path] = None,
                 evidence_path: Optional[Path] = None) -> None:
        self._history_path = Path(history_path or _DEFAULT_HISTORY)
        self._sources_path = Path(sources_path or _DEFAULT_SOURCES)
        self._evidence_path = Path(evidence_path or _DEFAULT_EVIDENCE)
        self._episodes: List[CanonEpisode] = []
        self._by_id: Dict[str, CanonEpisode] = {}
        self._sources: List[Dict] = []
        # Phase 14 Final Closure：evidence units → canonical attribution registry
        # （唯一 claim→source→stage 映射；FUR-006/FUR-052 等 act/type 归因的机器真源）。
        self._evidence_units: List[Dict] = []
        self._load()

    def _load(self) -> None:
        if not self._history_path.is_file():
            log.warning("canon history missing: %s（C2 空，不猜）", self._history_path)
            return
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
            eps = data.get("episodes", []) if isinstance(data, dict) else []
            for d in eps:
                ep = CanonEpisode.from_dict(d)
                self._episodes.append(ep)
                self._by_id[ep.episode_id] = ep
            self._episodes.sort(key=lambda e: e.timeline_order)
        except Exception as e:
            log.warning("canon history parse failed: %s", e)
        if self._sources_path.is_file():
            try:
                s = json.loads(self._sources_path.read_text(encoding="utf-8"))
                self._sources = list(s.get("sources", []) if isinstance(s, dict) else [])
            except Exception:
                self._sources = []
        if self._evidence_path.is_file():
            try:
                e = json.loads(self._evidence_path.read_text(encoding="utf-8"))
                self._evidence_units = list(e.get("evidence_units", []) if isinstance(e, dict) else [])
            except Exception:
                self._evidence_units = []

    # -------------------------------------------------- read
    def all_episodes(self) -> List[CanonEpisode]:
        return list(self._episodes)

    def get_episode(self, episode_id: str) -> Optional[CanonEpisode]:
        return self._by_id.get(episode_id)

    def episode_count(self) -> int:
        return len(self._episodes)

    def periods_covered(self) -> List[str]:
        seen: List[str] = []
        for e in self._episodes:
            if e.period and e.period not in seen:
                seen.append(e.period)
        return seen

    def sources(self) -> List[Dict]:
        return [dict(s) for s in self._sources]

    # -------------------------------------------------- evidence attribution registry
    def evidence_units(self) -> List[Dict]:
        """全部 evidence unit 的 canonical attribution（唯一 claim→source→stage 映射）。"""
        return [dict(u) for u in self._evidence_units]

    def evidence_unit(self, evidence_id: str) -> Optional[Dict]:
        for u in self._evidence_units:
            if u.get("evidence_id") == evidence_id:
                return dict(u)
        return None

    def _unregistered_evidence_refs(self) -> List[Dict]:
        """R7-FC：全局 evidence **引用完整性**层 —— 覆盖 EVERY CanonEpisode。

        每个 ``evidence_ids`` 引用都必须解析到唯一注册单元。该层是全局不变量，
        不依赖 quest / act（精确单幕 / 跨度 / null）/ source_type / 是否主线 /
        来源是否 USED。有效的 source_id **不能**挽救缺失的 evidence_id。
        """
        reg = {u.get("evidence_id"): u for u in self._evidence_units}
        out: List[Dict] = []
        for e in self._episodes:
            for eid in (e.evidence_ids or []):
                if reg.get(eid) is None:
                    out.append({"episode": e.episode_id, "evidence": eid,
                                "reason": "unregistered"})
        return out

    def _evidence_attribution_conflicts(self) -> List[Dict]:
        """episode（确定单幕）与其引用的 evidence registry act 归属矛盾清单。

        分层校验（R7-FC）：
        - A 引用完整性（``_unregistered_evidence_refs``）—— 所有 episode 全局生效，
          未注册 evidence 一律报告（不受精确单幕 gate 限制）；
        - B 归因兼容性 —— episode 声明 quest=Chapter IV + act 为单幕（I..V）时，
          其引用的 evidence 若 registry 也登记了确定 act 且两者不一致 → 冲突
          （如 act=V 的 episode 引用 Act I 庭审场景）。act 为跨度（I-V）/ null 的
          episode 或 evidence → 不做 B 层判定。
        """
        reg = {u.get("evidence_id"): u for u in self._evidence_units}
        conflicts: List[Dict] = list(self._unregistered_evidence_refs())
        for e in self._episodes:
            if (e.act or "") not in ("I", "II", "III", "IV", "V"):
                continue
            for eid in (e.evidence_ids or []):
                u = reg.get(eid)
                if u is None:
                    continue      # 缺失引用已在全局完整性层报告（不重复计数）
                ua = (u.get("act") or "")
                if ua and ua != e.act:
                    conflicts.append({"episode": e.episode_id, "evidence": eid,
                                      "episode_act": e.act, "evidence_act": ua})
        return conflicts

    # -------------------------------------------------- Phase 14 R6–R12（R7）：语义 completeness
    # 两类**不同**的完整性概念，必须分开报告：
    #   A. mandatory life-stage provenance（结构 + 语义兼容性）
    #   B. Chapter IV Act I–V curated main-story coverage（registry 级）
    # 语义硬规则：声明 quest=Chapter IV + 精确 act 的 episode，其该 act 主张必须由
    #   （MAIN_STORY, quest=Chapter IV, act=同一 act）的 evidence 支持；
    #   CHARACTER_STORY / VOICE_LINE / PROFILE 且 act=null 的 evidence 无论多官方，
    #   都不得满足精确主线 act 要求（不许 false-green）。
    #
    # D1 reviewer residual：精确幕支撑/覆盖还必须验证 evidence→source **持有链** ——
    # evidence_id 必须被一个合格权威且 USED 的 Canon source 登记，否则视为孤立证据，
    # 不产生覆盖、不构成精确支撑（fail-closed）。
    #
    # D1 reviewer residual II：tier 秩 ≠ 事实权威类型。持有链还要求来源在
    # **事实性角色**上合格 —— CURATED_MODEL / DERIVED_FROM_EVIDENCE 的 Tier0 派生
    # 模型文档（如 SRC-002/003）不是独立事实证据，不得为任何 factual evidence 作保。

    #: 当前冻结层级下可承载 Canon truth 的权威层（Tier 0 游戏文本/doc 种子、
    #: Tier 1 官方页面）。Tier 2 镜像/Tier 3 禁止源一律不合格。
    _ELIGIBLE_TRUTH_TIERS = (0, 1)

    #: 可为**事实性** evidence 作保的原始材质显式白名单（来自现存 registry 的事实
    #: 角色登记：Tier0 游戏文本/curated 种子、Tier1 官方公告页）。显式允许清单，
    #: 不做语义猜测；新事实材质（例如未来启用的官方档案页）须评审后扩表。
    _FACTUAL_ORIGINAL_MATERIALS = frozenset({
        "OFFICIAL_GAME_TEXT",
        "OFFICIAL_ANNOUNCEMENT_PAGE",
    })

    def _source_can_back_factual_evidence(self, source) -> bool:
        """单一策略点：source 能否为事实性 Canon evidence 作保（Residual II）。

        三条件合取，缺一不可：
          status == USED
          且 canon_tier ∈ _ELIGIBLE_TRUTH_TIERS
          且 original_material ∈ _FACTUAL_ORIGINAL_MATERIALS
        """
        if not isinstance(source, dict):
            return False
        try:
            tier = int(source.get("canon_tier", -1))
        except (TypeError, ValueError):
            return False
        return (
            tier in self._ELIGIBLE_TRUTH_TIERS
            and source.get("status") == "USED"
            and str(source.get("original_material") or "")
            in self._FACTUAL_ORIGINAL_MATERIALS
        )

    def _evidence_source_backed(self, evidence_id: str) -> bool:
        """evidence_id 是否具有合格权威 USED 来源持有链（唯一判定入口）。

        合格 = 存在登记了该 evidence_id 的来源，且该来源通过
        ``_source_can_back_factual_evidence``。NOT_USED / FORBIDDEN /
        Tier2+ / community locator / 无主单元 / 派生模型材质全部不合格。
        """
        if not evidence_id:
            return False
        for s in self._sources:
            ev_ids = s.get("evidence_ids") or []
            if evidence_id not in ev_ids:
                continue
            if self._source_can_back_factual_evidence(s):
                return True
        return False

    def _registry_duplicates(self) -> List[str]:
        seen: Dict[str, int] = {}
        for u in self._evidence_units:
            eid = u.get("evidence_id", "")
            seen[eid] = seen.get(eid, 0) + 1
        return [eid for eid, n in seen.items() if n > 1]

    def _act_support_gaps(self) -> List[Dict]:
        """Chapter IV 精确 act episode 缺少同 act MAIN_STORY evidence 的缺口（语义不支撑）。

        D1 residual：支撑还需该 evidence 具有合格权威 USED 来源持有链
        （_evidence_source_backed）；episode 的 source_ids 里的其它有效来源
        不能为不相关的 evidence 单元作保。
        """
        reg = {u.get("evidence_id"): u for u in self._evidence_units}
        gaps: List[Dict] = []
        for e in self._episodes:
            if (e.quest or "") != "Chapter IV" or (e.act or "") not in ("I", "II", "III", "IV", "V"):
                continue
            supported = False
            for eid in (e.evidence_ids or []):
                u = reg.get(eid)
                if u is None:
                    continue
                if (u.get("source_type") == "MAIN_STORY"
                        and u.get("quest") == "Chapter IV"
                        and u.get("act") == e.act
                        and self._evidence_source_backed(eid)):
                    supported = True
                    break
            if not supported:
                gaps.append({"episode": e.episode_id, "act": e.act,
                             "evidence": list(e.evidence_ids or [])})
        return gaps

    def _main_story_act_coverage(self) -> Dict[str, bool]:
        """Chapter IV Act I–V 各自是否有 registry 登记且**来源持有链合格**的
        MAIN_STORY 同 act 证据单元（D1 residual：孤立/未使用/禁用源登记的单元
        不产生覆盖）。"""
        acts = {"I": False, "II": False, "III": False, "IV": False, "V": False}
        for u in self._evidence_units:
            if (u.get("source_type") == "MAIN_STORY"
                    and (u.get("quest") or "") == "Chapter IV"
                    and (u.get("act") or "") in acts
                    and self._evidence_source_backed(u.get("evidence_id", ""))):
                acts[u["act"]] = True
        return acts

    def tier_counts(self) -> Dict[str, int]:
        out = {"tier0": 0, "tier1": 0, "tier2": 0, "tier3": 0}
        for s in self._sources:
            t = int(s.get("canon_tier", -1))
            key = f"tier{t}" if t in (0, 1, 2, 3) else "tier3"
            out[key] += 1
        return out

    def metrics(self) -> Dict[str, object]:
        eps = self._episodes
        used = [s for s in self._sources if s.get("status") == "USED"]
        unused = [s for s in self._sources if s.get("status") == "NOT_USED"]
        # Phase 15.1：mandatory 20 stages 每个都必须引用 ≥1 个 USED 来源（无 dangling）
        dangling = [e.episode_id for e in eps
                    if not [s for s in (e.source_ids or []) if s in {u["source_id"] for u in used}]]
        return {
            "canon_source_map_entries": len(self._sources),
            "canon_episode_count": len(eps),
            "tier0_sources": self.tier_counts()["tier0"],
            "tier1_sources": self.tier_counts()["tier1"],
            "tier2_mirror_sources": self.tier_counts()["tier2"],
            "unsupported_sources_excluded": self.tier_counts()["tier3"],
            "life_periods_covered": self.periods_covered(),
            # Phase 15.1：强制人生跨度来源完整性（20/20 阶段有官方来源 provenance）
            "canon_span_status": ("MANDATORY_SPAN_SOURCE_COMPLETE"
                                  if not dangling else f"GAPS:{dangling}"),
            "mandatory_stage_count": len(eps),
            "mandatory_stages_with_used_source": len(eps) - len(dangling),
            "sources_used": [u["source_id"] for u in used],
            "sources_unused_not_counted": [u["source_id"] for u in unused],
            "dangling_source_ids": dangling,
            "partial_periods": [e.episode_id for e in eps if e.canon_status == "partial"],
            "episodes_with_knowledge_boundary": sum(
                1 for e in eps if e.furina_knew or e.furina_did_not_know),
            "episodes_with_psychological_effect": sum(1 for e in eps if e.psychological_effects),
            "episodes_with_present_day_effect": sum(1 for e in eps if e.present_day_effects),
            "episodes_with_evidence_ids": sum(1 for e in eps if e.evidence_ids),
            # Phase 14 Final Closure：evidence attribution registry 一致性
            "evidence_registry_entries": len(self._evidence_units),
            "evidence_attribution_conflicts": self._evidence_attribution_conflicts(),
            # Phase 14 R6–R12（R7）：两类完整性分离（语义真实性，禁止 false-green）
            "evidence_registry_duplicates": self._registry_duplicates(),
            "unregistered_evidence_ids": [c["evidence"] for c in self._evidence_attribution_conflicts()
                                          if c.get("reason") == "unregistered"],
            "episodes_without_exact_act_main_story_evidence": self._act_support_gaps(),
            "main_story_act_coverage": self._main_story_act_coverage(),
            "missing_main_story_acts": [a for a, ok in self._main_story_act_coverage().items() if not ok],
            "main_story_act_coverage_status": (
                "COMPLETE" if all(self._main_story_act_coverage().values()) else "PARTIAL"),
            # 语义 mandatory life-stage 状态：结构（dangling）+ 冲突 + registry 有效性 +
            # 精确 act 支撑全部干净才算 SOURCE_COMPLETE；任何语义缺口 → 如实 PARTIAL。
            # （canon_span_status 保留为纯结构指标，兼容既有锁定测试。）
            "mandatory_life_stage_source_status": self._life_stage_source_status(),
            "runtime_canon_mutable": False,
        }

    def _life_stage_source_status(self) -> str:
        # R7-FC：全局 evidence 引用完整性（所有 episode，act 无关）→ 任一缺失引用
        # 即 fail（任何真实存在的"有效 source + 缺失 evidence"伪装都被拒绝）。
        missing = self._unregistered_evidence_refs()
        conflicts = [c for c in self._evidence_attribution_conflicts()
                     if c.get("reason") != "unregistered"]
        gaps = self._act_support_gaps()
        dups = self._registry_duplicates()
        used = [s for s in self._sources if s.get("status") == "USED"]
        dangling = [e.episode_id for e in self._episodes
                    if not [s for s in (e.source_ids or [])
                            if s in {u["source_id"] for u in used}]]
        if missing:
            return ("GAPS:unregistered_evidence="
                    f"{sorted({m['evidence'] for m in missing})}")
        if dangling:
            return f"GAPS:dangling_sources={dangling}"
        if conflicts:
            return f"GAPS:attribution_conflicts={conflicts}"
        if dups:
            return f"GAPS:registry_duplicates={dups}"
        if gaps:
            return ("PARTIAL:episodes_without_exact_act_main_story_evidence="
                    f"{[g['episode'] for g in gaps]}")
        return "SOURCE_COMPLETE"

    def is_read_only(self) -> bool:
        return True
