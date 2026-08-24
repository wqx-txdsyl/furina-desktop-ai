"""多帧动画生成管线（plan/2 §7-L4, ⑦§19-21）。

Agnes Video V2.0 关键帧动画 → 拆帧 → 抠黑底 → 多帧资产入 manifest。
关键：**关键帧必须先规整到同一画布（全全身、居中、同比例）**，否则会特写/缩放。

    python scripts/gen_animation.py --name sit_down \
        --kf data/assets/poses/furina_standing_neutral_front_idle_01.png \
             data/assets/poses/furina_sitting_neutral_user_idle_01.png \
        --frames 12 --fps 12
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
import cv2
import httpx

from furina.config import load_config
from furina.assets.agnes_client import AgnesClient, VideoOptions, _as_data_uris
from furina.assets.asset_manifest import AssetManifest, AssetEntry
from furina.assets.postprocess import remove_background_and_crop
from furina.core import setup_logging, get_logger

log = get_logger("scripts.gen_animation")

CANVAS = 1024


def normalize(png: str, out: str, canvas: int = CANVAS) -> str:
    """等比缩放到 canvas 高的 ~92%，全身居中画到 canvas×canvas（保证一致构图）。"""
    im = Image.open(png).convert("RGBA")
    scale = (canvas * 0.92) / im.height
    nw, nh = int(im.width * scale), int(im.height * scale)
    im = im.resize((nw, nh), Image.LANCZOS)
    c = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    c.paste(im, ((canvas - nw) // 2, (canvas - nh) // 2))
    c.save(out)
    return out


def emit_frames(video_bytes: bytes, poses_dir: Path, prefix: str, n: int) -> list[str]:
    """拆帧并抠黑底，存为透明 PNG，返回帧相对路径（poses/...）。"""
    tmp = poses_dir / "_video.mp4"
    tmp.write_bytes(video_bytes)
    cap = cv2.VideoCapture(str(tmp))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or n
    idxs = [int(i * (total - 1) / (n - 1)) for i in range(n)] if total > 1 else [0]
    paths: list[str] = []
    for j, idx in enumerate(idxs):
        cap.set(1, idx)
        ok, f = cap.read()
        if not ok:
            continue
        p = poses_dir / f"anim_{prefix}_{j:02d}.png"
        # cv2 读出来是 BGR；用 PIL 保存（支持中文路径）
        from PIL import Image
        Image.frombytes("RGB", (f.shape[1], f.shape[0]), cv2.cvtColor(f, cv2.COLOR_BGR2RGB).tobytes()).save(p)
        remove_background_and_crop(p, tolerance=32)   # 抠黑底
        paths.append(f"poses/anim_{prefix}_{j:02d}.png")
    cap.release()
    tmp.unlink(missing_ok=True)
    return paths


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--kf", nargs="+", required=True, help="关键帧 PNG 路径（≥2）")
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--out", default="data/assets")
    args = ap.parse_args()

    setup_logging(20)
    cfg = load_config()
    ag = AgnesClient(cfg.agnes_api_key)
    out_dir = cfg.root_dir / args.out
    poses_dir = out_dir / "poses"

    # 1) 规整关键帧到同一画布（避免特写/缩放）
    norm_kf = []
    for i, p in enumerate(args.kf):
        nf = out_dir / f"_kf{i}.png"
        normalize(p, str(nf))
        norm_kf.append(_as_data_uris([str(nf)])[0])
        log.info("规整关键帧 %s", p)

    # 2) 生成视频
    d = ag.create_video(VideoOptions(
        prompt="smooth in-place transition between keyframes, identical chibi Genshin Furina, "
               "full body always centered and same framing, flat cel-shaded 2D, no camera zoom, no scene",
        keyframes=norm_kf, num_frames=min(args.frames * 2 + 1, 441), frame_rate=args.fps))
    vid = d.get("video_id") or d.get("task_id")
    log.info("视频任务 %s, 等待完成…", vid)
    res = ag.wait_video(vid, timeout=300, interval=3)
    url = ag.video_url_from(res)
    if not url:
        log.error("未拿到视频 URL: %s", str(res)[:200])
        return 1
    data = httpx.get(url, timeout=120).content

    # 3) 拆帧 + 抠底 + 入 manifest
    poses_dir.mkdir(parents=True, exist_ok=True)
    frames = emit_frames(data, poses_dir, args.name, args.frames)
    if not frames:
        log.error("拆帧失败")
        return 1
    m_path = out_dir / "manifest.json"
    manifest = AssetManifest.load(m_path) if m_path.exists() else AssetManifest()
    # 多帧动画条目：作为 action=<name> 的帧序列
    manifest.entries.append(AssetEntry(
        asset_id=f"anim_{args.name}",
        posture="standing", emotion="neutral", gaze="user",
        action=args.name, kind="sequence", loop=True,
        fps=args.fps, frames=frames, path=frames[0], tags=["animation"]))
    manifest.save(m_path)
    log.info("完成：%s 多帧 %d 帧 -> manifest", args.name, len(frames))
    for f in frames:
        log.info("  + %s", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
