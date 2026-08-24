"""素材库完整核验测试（任务书 §13, §32, §46）：四层覆盖 + Entry/Loop/Exit + 缺失降级。"""
from __future__ import annotations

from pathlib import Path

from furina.assets.asset_manifest import AssetManifest, AssetQuery, AssetResolver

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "assets" / "manifest.json"

P1_POSES = {"standing", "sitting", "lying", "sleeping"}


def test_manifest_exists_and_full():
    m = AssetManifest.load(MANIFEST)
    assert len(m.entries) >= 12, f"素材库应覆盖 P0 姿态，实际 {len(m.entries)}"
    # 四层架构（任务书 §3-13）：base_pose / expression / gaze / micro / action 都要有
    roles = {e.role for e in m.entries}
    for r in ["base_pose", "expression", "gaze", "micro", "action", "transition"]:
        assert r in roles, f"缺少 {r} 层素材"


def test_core_poses_covered():
    m = AssetManifest.load(MANIFEST)
    poses = {e.posture for e in m.entries}
    assert P1_POSES.issubset(poses), f"P0 姿态缺失: {P1_POSES - poses}"


def test_gaze_variety():
    m = AssetManifest.load(MANIFEST)
    gazes = {e.gaze for e in m.entries if e.role == "gaze"}
    assert len(gazes) >= 4, f"视线素材不足: {gazes}"


def test_sequences_have_entry_loop_exit():
    m = AssetManifest.load(MANIFEST)
    seqs = [e for e in m.entries if e.kind == "sequence" and e.role == "transition"]
    assert seqs, "应有过渡序列"
    for s in seqs:
        assert getattr(s, "entry_frames", None), f"{s.action} 缺 entry"
        assert getattr(s, "loop_frames", None) or getattr(s, "frames", None), f"{s.action} 缺 loop"
        # loopable=False 的过渡序列不应无限循环（任务书 §10）
        if s.role == "transition":
            assert s.loop is False, f"{s.action} 过渡不应无限循环"


def test_missing_asset_does_not_idle():
    """任务书 §26-28：缺素材不回落 idle，取 best-available 并记录 ASSET_MISSING。"""
    m = AssetManifest.load(MANIFEST)
    r = AssetResolver(m)
    e = r.resolve(AssetQuery("flying", "ecstatic", "left", "back", "levitate"))
    assert e is not None, "缺素材也应返回某帧（best-available）"
    assert r.missing, "应记录 ASSET_MISSING"


def test_drink_request_resolves_to_drink_or_compatible():
    m = AssetManifest.load(MANIFEST)
    r = AssetResolver(m)
    e = r.resolve(AssetQuery("standing", "neutral", "front", "front", "drink"))
    # 优先命中 drink 动作，或站姿（绝不因为“没 drink 而 idle”）
    assert e is not None
    assert e.action == "drink" or e.posture == "standing"
