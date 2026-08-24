"""Activity × Asset 覆盖矩阵审计（用户要求 ①：Brain 是否正确利用身体的审计）。

对 Brain 的每个候选 Activity：
  1. 找到其 Behavior Profile（pose/emotion/gaze/action/transition/micro）
  2. 在 manifest 里解析该视觉状态（exact → compatible）
  3. 标记覆盖状态：EXACT(命中) / COMPATIBLE(近似) / MISSING(缺，但不 idle——记 ASSET_MISSING)
这告诉我们：哪些 Activity 有直接的视觉表现，哪些会降级，哪些完全没素材但仍不 idle。

用法： python scripts/audit_coverage.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from furina.config import load_config
from furina.core import setup_logging, get_logger
from furina.assets.asset_manifest import AssetManifest, AssetQuery, AssetResolver
from furina.behavior.resolver import profile_for
from furina.life_brain import LIFE_ACTIVITIES

log = get_logger("scripts.audit")


def classify(e, profile) -> str:
    if e is None:
        return "MISSING"
    if (e.posture == profile.pose and e.gaze == profile.gaze
            and e.emotion == (profile.emotion) and e.action == profile.action):
        return "EXACT"
    if e.posture == profile.pose:
        return "COMPATIBLE(pose)"
    return "COMPATIBLE(other)"


def main() -> int:
    setup_logging(20)
    cfg = load_config()
    mp = cfg.root_dir / "data/assets/manifest.json"
    m = AssetManifest.load(mp)
    r = AssetResolver(m)

    print("=" * 78)
    print(f"Activity × Asset 覆盖矩阵   （manifest={len(m.entries)} 条；Brain 候选 {len(LIFE_ACTIVITIES)} 个）")
    print("=" * 78)
    print(f"{'Activity':16} {'Pose':9} {'Emotion':9} {'Gaze':8} {'Action':8} {'Transition':10} {'覆盖'}")
    print("-" * 78)
    counts = {"EXACT": 0, "COMPATIBLE(pose)": 0, "COMPATIBLE(other)": 0, "MISSING": 0}
    for act in LIFE_ACTIVITIES:
        p = profile_for(act)
        q = AssetQuery(p.pose, p.emotion, p.gaze, "front", p.action)
        e = r.resolve(q)
        st = classify(e, p)
        counts[st] += 1
        asset = e.asset_id if e else "-"
        print(f"{act:16} {p.pose:9} {p.emotion:9} {p.gaze:8} {p.action:8} "
              f"{(p.transition or '-'):10} {st:22} {asset[:30]}")
    print("-" * 78)
    print(f"汇总: EXACT={counts['EXACT']}  COMPATIBLE(pose)={counts['COMPATIBLE(pose)']}  "
          f"COMPATIBLE(other)={counts['COMPATIBLE(other)']}  MISSING={counts['MISSING']}")
    print("\n无条件素材的 Activity（缺素材仍不 idle，走 best-available + ASSET_MISSING）:")
    missing_acts = [a for a in LIFE_ACTIVITIES if classify(r.resolve(AssetQuery(
        profile_for(a).pose, profile_for(a).emotion, profile_for(a).gaze, "front", profile_for(a).action)), profile_for(a)) == "MISSING"]
    print("  ", missing_acts or "无（全部有至少一个可解析素材，不含 idle）")
    print("\n总 ASSET_MISSING 次数:", sum(r.missing.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
