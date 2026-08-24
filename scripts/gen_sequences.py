"""多帧动作序列生成器（任务书 §8-11：Entry/Loop/Exit，程序插值，不用视频）。

从静态姿态图（站/坐/躺/睡）出发，用 **程序在帧间做柔和过渡**（crossfade + 轻微位移），
生成统一画布的干净 PNG 序列，并写入 manifest 的 entry_frames / loop_frames / exit_frames。

每个动作三段：
  ENTER（from_pose → to_pose 的过渡，如 sit_down）
  LOOP（目标姿态的持续循环帧，如 sitting 呼吸/微动）
  EXIT（to_pose → from_pose 的过渡，可反向复用）

用法：
  python scripts/gen_sequences.py --name sit_down --from standing --to sitting
  python scripts/gen_sequences.py --name sit_down --from standing --to sitting --out data/assets
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
import numpy as np

from furina.config import load_config
from furina.assets.asset_manifest import AssetManifest, AssetEntry
from furina.core import setup_logging, get_logger

log = get_logger("scripts.gen_sequences")

CANVAS_W, CANVAS_H = 512, 640
TARGET_CONTENT_H = int(CANVAS_H * 0.88)
N_ENTER = 8         # 过渡帧数
N_LOOP = 10         # 循环帧数


def _load_centered(png: Path) -> Image.Image:
    """加载并规整到统一画布（内容高 ~88%，居中）。"""
    im = Image.open(png).convert("RGBA")
    bb = im.getchannel("A").getbbox()
    if bb:
        im = im.crop(bb)
    scale = TARGET_CONTENT_H / im.height
    nw, nh = int(im.width * scale), TARGET_CONTENT_H
    im = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    canvas.paste(im, ((CANVAS_W - nw) // 2, (CANVAS_H - nh) // 2))
    return canvas


def _blend(a: Image.Image, b: Image.Image, t: float) -> Image.Image:
    """两帧交叉混合（程序插值，非视频）。t=0→a, t=1→b。"""
    return Image.blend(a, b, t)


def _save(im: Image.Image, p: Path) -> None:
    im.save(p, "PNG")


def gen_transition(from_png: Path, to_png: Path, prefix: str, poses: Path, n: int) -> list[str]:
    """生成 from→to 的 ENTER 过渡帧（逐帧插值）。"""
    a = _load_centered(from_png); b = _load_centered(to_png)
    paths = []
    for i in range(n):
        t = i / max(1, n - 1)   # 0..1
        frame = _blend(a, b, t)
        p = poses / f"anim_{prefix}_{i:02d}.png"
        _save(frame, p)
        paths.append(f"poses/anim_{prefix}_{i:02d}.png")
    return paths


def gen_loop(pose_png: Path, prefix: str, poses: Path, n: int) -> list[str]:
    """生成本姿态的循环帧（轻微呼吸/微动，避免 GIF 感——程序微位移/缩放）。"""
    base = _load_centered(pose_png)
    paths = []
    for i in range(n):
        # 极轻微的垂直呼吸 + 微缩放（让循环“活着”但不机械）
        breath = (i / max(1, n - 1)) * 0.02   # ±1% 高度微动
        v_off = int((i % 2) * 2.0)              # 每两帧 ±2px 微晃（int）
        w, h = base.size
        frame = base.resize((int(w * (1 - breath)), int(h * (1 - breath))), Image.LANCZOS)
        canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        paste_x = (CANVAS_W - frame.width) // 2
        paste_y = (CANVAS_H - frame.height) // 2 + v_off
        canvas.paste(frame, (paste_x, paste_y))
        p = poses / f"anim_{prefix}_loop_{i:02d}.png"
        _save(canvas, p)
        paths.append(f"poses/anim_{prefix}_loop_{i:02d}.png")
    return paths


def build_sequence(cfg, name: str, from_pose: str, to_pose: str, out_dir: Path,
                   opts) -> None:
    poses = out_dir / "poses"
    poses.mkdir(parents=True, exist_ok=True)
    # 找静态姿态图：furina_{posture}_neutral_front_idle_01.png
    def pose_file(posture: str) -> Path:
        cand = poses / f"furina_{posture}_neutral_front_idle_01.png"
        if cand.exists():
            return cand
        # 兜底：任意该 posture 的素材
        for f in poses.glob(f"furina_{posture}_*.png"):
            return f
        raise FileNotFoundError(f"找不到 {posture} 姿态素材")

    from_f = pose_file(from_pose); to_f = pose_file(to_pose)
    enter = gen_transition(from_f, to_f, name, poses, N_ENTER)
    loop = gen_loop(to_f, name, poses, N_LOOP)
    # EXIT = 反向 ENTER（to→from）
    exit_frames = list(reversed(enter))

    m_path = out_dir / "manifest.json"
    manifest = AssetManifest.load(m_path) if m_path.exists() else AssetManifest()
    manifest.entries = [e for e in manifest.entries
                        if not (e.kind == "sequence" and e.action == name)]
    manifest.entries.append(AssetEntry(
        asset_id=f"anim_{name}", posture=to_pose, emotion="neutral", gaze="front",
        action=name, kind="sequence", loop=False,
        role="transition", transition_from=from_pose, transition_to=to_pose,
        entry_frames=enter, loop_frames=loop, exit_frames=exit_frames,
        frames=enter[:2] + loop + exit_frames[:2],
        path=enter[0], tags=["animation", "transition"]))
    manifest.save(m_path)
    log.info("完成序列 %s: enter=%d loop=%d exit=%d", name, len(enter), len(loop), len(exit_frames))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--from", dest="from_pose", required=True)
    ap.add_argument("--to", dest="to_pose", required=True)
    ap.add_argument("--out", default="data/assets")
    args = ap.parse_args()
    setup_logging(20)
    cfg = load_config()
    build_sequence(cfg, args.name, args.from_pose, args.to_pose, cfg.root_dir / args.out, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
