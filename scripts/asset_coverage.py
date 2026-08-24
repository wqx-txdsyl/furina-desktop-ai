"""Phase 12V —— 运行时素材覆盖（V6 重写）。

旧版「520/520=100%」把 `resolver.resolve(...) is not None` 当命中；而 AssetResolver 在非空
manifest 下几乎总会返回 fallback entry，所以那不是 exact coverage。

本版**用生产的同一套**选择：
    VisualSemanticMapper.map()   （后端语义 → 素材词汇，唯一映射点）
        + AssetResolver.resolve() （真实 runtime 选择器）

分类只允许：
    EXACT                 四要素（posture/emotion/gaze/action）精准命中
    COMPATIBLE_DEGRADED   action 或 posture 命中，其余有降级
    SEMANTIC_LOSS        退到 standing/neutral/front 兜底
    MISSING              无素材可命中

输出：docs/ASSET_COVERAGE_V2.md
用法：python scripts/asset_coverage.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from furina.assets.asset_manifest import AssetManifest, AssetResolver, AssetQuery
from furina.runtime.visual_semantics import VisualSemanticMapper

MANIFEST = ROOT / "data" / "assets" / "manifest.json"
M = AssetManifest.load(MANIFEST)
RES = AssetResolver(M)
MAPPER = VisualSemanticMapper(M)

# 语义请求（后端 Frame 会给出的）：(name, posture, expression, gaze, activity, action_override)
SCENARIOS = [
    ("idle standing", "relaxed", "neutral", "NONE", "idle", None),
    ("idle sitting", "seated", "neutral", "NONE", "rest", None),
    ("read", "upright", "focus", "DOWN", "read", None),
    ("think", "relaxed", "thoughtful", "NONE", "think", None),
    ("eat", "upright", "happy", "DOWN", "eat", None),
    ("drink", "upright", "neutral", "DOWN", "drink", None),
    ("play", "upright", "playful", "DOWN", "play", None),
    ("proud", "upright", "proud", "USER", "idle", None),
    ("embarrassed", "upright", "embarrassed", "SIDE", "seek_attention", None),
    ("sad", "relaxed", "sad", "DOWN", "idle", None),
    ("USER gaze", "relaxed", "neutral", "USER", "idle", None),
    ("SCREEN gaze", "upright", "focus", "SCREEN", "observe_work", None),
    ("SIDE gaze", "relaxed", "embarrassed", "SIDE", "idle", None),
    ("head_touch", "upright", "happy", "USER", "head_touch", None),
    ("poke", "upright", "surprised", "USER", "poke", None),
    ("drag", "upright", "surprised", "USER", "drag", "drag"),
    ("walk", "upright", "neutral", "front", "walk", None),
    ("sleep", "sleeping", "sleepy", "NONE", "sleep", None),
    ("wake", "upright", "neutral", "NONE", "idle", None),
]


def classify(mapped, entry) -> str:
    """按真实 runtime 语义做质量判定（不是 non-None）。"""
    if entry is None:
        return "MISSING"
    m = mapped
    exact = (entry.posture == m.posture and entry.emotion == m.expression
             and entry.gaze == m.gaze and entry.action == m.action)
    if exact:
        return "EXACT"
    # 动作命中（posture/emotion/gaze 有降级但动作对）
    if entry.action == m.action and m.action != "idle":
        return "COMPATIBLE_DEGRADED"
    # 姿势命中（同等姿态下表达/视线降级）
    if entry.posture == m.posture:
        return "COMPATIBLE_DEGRADED"
    # 退到 standing/neutral/front 兜底 → 语义丢失
    if entry.posture == "standing" and entry.emotion == "neutral" and entry.gaze == "front":
        return "SEMANTIC_LOSS"
    return "SEMANTIC_LOSS"


def main() -> int:
    rows = []
    counts = {"EXACT": 0, "COMPATIBLE_DEGRADED": 0, "SEMANTIC_LOSS": 0, "MISSING": 0}
    for name, posture, expr, gaze, activity, action_over in SCENARIOS:
        mapped = MAPPER.map(posture=posture, expression=expr, gaze=gaze, activity=activity,
                            interaction_override=action_over)
        q = AssetQuery(posture=mapped.posture, emotion=mapped.expression, gaze=mapped.gaze,
                       direction="front", action=mapped.action)
        resolved = RES.resolve(q)
        quality = classify(mapped, resolved)
        counts[quality] += 1
        asset_id = resolved.asset_id if resolved else "-"
        rows.append((name, posture, expr, gaze, activity,
                     f"{mapped.posture}/{mapped.expression}/{mapped.gaze}/{mapped.action}",
                     asset_id, quality, ";".join(mapped.degraded)))

    lines = ["# Runtime Asset Coverage（Phase 12V）\n"]
    lines.append("> 用生产同一套选择器：VisualSemanticMapper.map() + AssetResolver.resolve()。")
    lines.append("> **`resolve 非 None` 不等于 exact**；以下为真实匹配质量。\n")
    lines.append("| Scenario | Requested semantic | Mapped visual semantic | Asset | Match Quality |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        mq = f"**{r[7]}**" if r[7] == "EXACT" else r[7]
        lines.append(f"| {r[0]} | {r[1]}/{r[2]}/{r[3]}/{r[4]} | {r[5]} | {r[6]} | {mq} |")
    lines.append("")
    lines.append("## Quality breakdown")
    lines.append(f"- EXACT: {counts['EXACT']}")
    lines.append(f"- COMPATIBLE_DEGRADED: {counts['COMPATIBLE_DEGRADED']}")
    lines.append(f"- SEMANTIC_LOSS: {counts['SEMANTIC_LOSS']}")
    lines.append(f"- MISSING: {counts['MISSING']}")
    lines.append(f"- **total**: {len(rows)}")
    lines.append("")
    lines.append("## Notes")
    for r in rows:
        if r[8]:
            lines.append(f"- {r[0]}: degraded → {r[8]}")

    out = ROOT / "docs" / "ASSET_COVERAGE_V2.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {out}")
    print("QUALITY:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
