"""一键重建完整素材库（任务书 §3-13, §34-37）：P0~P3 静态图 + 全部多帧序列。

步骤：
  A. 生成四层静态素材（base_pose / expression / gaze / micro / action / interaction / prop）
  B. 校验（角色一致性 / 透明 / 尺寸）
  C. 生成多帧动作序列（Entry/Loop/Exit，程序插值不用视频）

用法：  python scripts/assets/rebuild_assets.py [--dry-run] [--phase 1|2|3|all]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from furina.config import load_config
from furina.core import setup_logging, get_logger

log = get_logger("scripts.assets.rebuild")


def build_sequences(cfg, out_dir: Path) -> None:
    """根据已有静态姿态生成所有过渡/循环序列（程序插值）。"""
    poses = out_dir / "poses"
    # 序列清单：(name, from_pose, to_pose)；四姿 P0 间两两过渡
    transitions = [
        ("sit_down", "standing", "sitting"),
        ("stand_up", "sitting", "standing"),
        ("lie_down", "sitting", "lying"),
        ("lie_up", "lying", "sitting"),
        ("wake_up", "sleeping", "sitting"),
        ("go_sleep", "sitting", "sleeping"),
    ]
    # 可循环的单姿态循环（呼吸/微动）：给每个高频姿态一个 LOOP 序列
    loop_from = {"sitting": "sitting", "standing": "standing", "lying": "lying", "sleeping": "sleeping"}
    from scripts.assets.gen_sequences import build_sequence, gen_loop, _load_centered, CANVAS_W, CANVAS_H, N_LOOP
    for name, frm, to in transitions:
        try:
            build_sequence(cfg, name, frm, to, out_dir, None)
        except Exception as e:
            log.warning("build sequence %s skip: %s", name, e)
    # 单姿态循环
    import numpy as np
    for pose in loop_from:
        try:
            pf = poses / f"furina_{pose}_neutral_front_idle_01.png"
            if not pf.exists():
                continue
            frames = gen_loop(pf, f"{pose}_loop", poses, N_LOOP)
            from furina.assets.asset_manifest import AssetManifest, AssetEntry
            mp = out_dir / "manifest.json"
            m = AssetManifest.load(mp) if mp.exists() else AssetManifest()
            m.entries = [e for e in m.entries if not (e.kind == "sequence" and e.action == f"{pose}_loop")]
            m.entries.append(AssetEntry(asset_id=f"anim_{pose}_loop", posture=pose, emotion="neutral",
                                        gaze="front", action=f"{pose}_loop", kind="sequence", loop=True,
                                        role="micro", frames=frames, path=frames[0], tags=["animation", "loop"]))
            m.save(mp)
        except Exception as e:
            log.warning("build loop %s skip: %s", pose, e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--phase", default="all", choices=["1", "2", "3", "all"])
    ap.add_argument("--out", default="data/assets")
    args = ap.parse_args()
    setup_logging(20)
    cfg = load_config()
    out_dir = cfg.root_dir / args.out

    from furina.assets.agnes_client import AgnesClient
    from furina.assets.pipeline import AssetPipeline
    from furina.assets.asset_manifest import AssetManifest, semantic_id_for
    from furina.assets.qc import QCEngine

    if not cfg.agnes_api_key:
        log.error("缺 AGNES_API_KEY")
        return 1
    base = cfg.root_dir / "data" / "assets" / "reference" / "furina-base.png"
    if not base.exists():
        log.error("缺基座图")
        return 1
    agnes = AgnesClient(cfg.agnes_api_key)
    pipeline = AssetPipeline(base, agnes, out_dir, QCEngine())
    mp = out_dir / "manifest.json"
    manifest = AssetManifest.load(mp) if mp.exists() else AssetManifest()

    # 选批次
    from scripts.assets.generate_assets import batch_phase1, batch_phase2, batch_phase3
    if args.phase == "1":
        specs = batch_phase1()
    elif args.phase == "2":
        specs = batch_phase1() + batch_phase2()
    elif args.phase == "3":
        specs = batch_phase1() + batch_phase2() + batch_phase3()
    else:
        from scripts.assets.generate_assets import batch_flat100full
        specs = batch_flat100full()
    log.info("待生成 %d 个素材 (phase=%s dry=%s)", len(specs), args.phase, args.dry_run)

    existing = {e.semantic_id(): e for e in manifest.entries}
    done = skipped = fails = 0
    for spec in specs:
        sem = semantic_id_for(spec.posture, spec.emotion, spec.gaze, "front", spec.action)
        if sem in existing and existing[sem].quality_score > 0:
            skipped += 1; continue
        try:
            if args.dry_run:
                log.info("[dry] %s", sem); continue
            entry = pipeline.generate_one(spec)
            manifest.entries.append(entry); existing[sem] = entry
            mp.parent.mkdir(parents=True, exist_ok=True); manifest.save(mp)
            done += 1
            log.info("  + %-44s qc=%d role=%s", entry.asset_id, entry.quality_score, entry.role)
        except Exception as e:
            fails += 1
            log.warning("生成失败 %s: %s", sem, e)
    log.info("静态素材: 新增 %d, 跳过 %d, 失败 %d, 共 %d", done, skipped, fails, len(manifest.entries))

    if not args.dry_run and args.phase in ("3", "all"):
        build_sequences(cfg, out_dir)
        log.info("多帧序列已生成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
