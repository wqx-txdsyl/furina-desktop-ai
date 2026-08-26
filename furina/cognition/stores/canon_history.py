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

    def _evidence_attribution_conflicts(self) -> List[Dict]:
        """episode（确定单幕）与其引用的 evidence registry act 归属矛盾清单。

        规则：episode.act 为 Chapter IV 单幕（I..V）时，其引用的 evidence 若 registry
        也登记了确定 act 且两者不一致 → 冲突（如 act=V 的 episode 引用 Act I 庭审场景）。
        act 为跨度（I-V）或无 act 的 evidence → 不判定冲突。
        """
        reg = {u.get("evidence_id"): u for u in self._evidence_units}
        conflicts: List[Dict] = []
        for e in self._episodes:
            if (e.act or "") not in ("I", "II", "III", "IV", "V"):
                continue
            for eid in (e.evidence_ids or []):
                u = reg.get(eid)
                if u is None:
                    conflicts.append({"episode": e.episode_id, "evidence": eid,
                                      "reason": "unregistered"})
                    continue
                ua = (u.get("act") or "")
                if ua and ua != e.act:
                    conflicts.append({"episode": e.episode_id, "evidence": eid,
                                      "episode_act": e.act, "evidence_act": ua})
        return conflicts

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
            "runtime_canon_mutable": False,
        }

    def is_read_only(self) -> bool:
        return True
