"""多帧动画批量生成（legacy-plan/2 §7-L4, ⑦§19-21）。

在单脚本 gen_animation.py 基础上，为多个命名动画各生成一条多帧序列。
用法：
    python scripts/assets/gen_animations_batch.py --name walk --kf a.png b.png ...
    python scripts/assets/gen_animations_batch.py --jobs "eat:sit.png:eat.png" ...
从 docs/archive/legacy-plan/2 asset engine.md 读取需求，逐条生成；每条出帧后立即入 manifest（断点续跑）。

注意：Video V2.0 有关键帧规整要求（同画布全身居中），已由 normalize 处理。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import time

from furina.config import load_config
from furina.assets.agnes_client import AgnesClient, VideoOptions, _as_data_uris
from furina.assets.asset_manifest import AssetManifest, AssetEntry
from furina.core import setup_logging, get_logger

log = get_logger("scripts.assets.gen_animations_batch")

CANVAS = 1024
FRAMES = 12
FPS = 12
VIDEO_RETRIES = 8          # 视频接口常 503，加重试次数与指数退避
VIDEO_BACKOFF = 15.0


def create_video_retry(ag: AgnesClient, opts: VideoOptions) -> dict:
    """create_video 带更多重试：视频接口 503 频繁，单独多等几次再放弃。"""
    last_err = None
    for attempt in range(VIDEO_RETRIES):
        try:
            return ag.create_video(opts)
        except Exception as e:   # 429/503/网络
            last_err = e
            log.warning("create_video 第 %d 次失败 (%s)，%s 秒后重试…",
                        attempt + 1, getattr(e, "response", "<none>") or e,
                        VIDEO_BACKOFF)
            time.sleep(VIDEO_BACKOFF)
    raise last_err


def normalize(png: str, out: str, canvas: int = CANVAS) -> str:
    from PIL import Image
    im = Image.open(png).convert("RGBA")
    scale = (canvas * 0.92) / im.height
    nw, nh = int(im.width * scale), int(im.height * scale)
    im = im.resize((nw, nh), Image.LANCZOS)
    c = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    c.paste(im, ((canvas - nw) // 2, (canvas - nh) // 2))
    c.save(out)
    return out


def emit_frames(video_bytes: bytes, poses_dir: Path, prefix: str, n: int) -> list[str]:
    import cv2
    from PIL import Image
    from furina.assets.postprocess import remove_background_and_crop
    tmp = poses_dir / "_v.mp4"
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
        Image.frombytes("RGB", (f.shape[1], f.shape[0]),
                        cv2.cvtColor(f, cv2.COLOR_BGR2RGB).tobytes()).save(p)
        remove_background_and_crop(p, tolerance=32)
        paths.append(f"poses/anim_{prefix}_{j:02d}.png")
    cap.release()
    tmp.unlink(missing_ok=True)
    return paths


def generate_one(ag: AgnesClient, out_dir: Path, name: str, kf_paths: list[str]) -> tuple[int, list[str]]:
    poses_dir = out_dir / "poses"
    poses_dir.mkdir(parents=True, exist_ok=True)
    norm_kf = []
    for i, p in enumerate(kf_paths):
        nf = out_dir / f"_kf{i}.png"
        normalize(p, str(nf))
        norm_kf.append(_as_data_uris([str(nf)])[0])
    d = create_video_retry(ag, VideoOptions(
        prompt="smooth in-place transition between keyframes, identical chibi Genshin Furina, "
               "full body always centered and same framing, flat cel-shaded 2D, no camera zoom, no scene",
        keyframes=norm_kf, num_frames=min(FRAMES * 2 + 1, 441), frame_rate=FPS))
    vid = d.get("video_id") or d.get("task_id")
    log.info("视频任务 %s, 等待完成…", vid)
    res = ag.wait_video(vid, timeout=420, interval=4)
    url = ag.video_url_from(res)
    if not url:
        log.error("未拿到视频 URL: %s", str(res)[:200])
        return 1, []
    import httpx
    data = httpx.get(url, timeout=180).content
    frames = emit_frames(data, poses_dir, name, FRAMES)
    if not frames:
        log.error("拆帧失败: %s", name)
        return 1, []
    m_path = out_dir / "manifest.json"
    manifest = AssetManifest.load(m_path) if m_path.exists() else AssetManifest()
    # 去掉同名的旧 sequence 条目（若重跑）
    manifest.entries = [e for e in manifest.entries
                        if not (e.kind == "sequence" and e.action == name)]
    manifest.entries.append(AssetEntry(
        asset_id=f"anim_{name}", posture="standing", emotion="neutral", gaze="user",
        action=name, kind="sequence", loop=True, fps=FPS, frames=frames,
        path=frames[0], tags=["animation"]))
    manifest.save(m_path)
    log.info("完成：%s %d 帧 -> manifest", name, len(frames))
    return 0, frames


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", nargs="+", required=True,
                    help="每条 'name:path1;path2'（用分号分隔关键帧）")
    ap.add_argument("--out", default="data/assets")
    args = ap.parse_args()

    setup_logging(20)
    cfg = load_config()
    ag = AgnesClient(cfg.agnes_api_key)
    out_dir = cfg.root_dir / args.out

    failures = 0
    for job in args.jobs:
        name, _, rest = job.partition(":")
        kf = [p for p in rest.split(";") if p]
        if not kf:
            log.warning("跳过 %s：无关键帧", name)
            continue
        rc, frames = generate_one(ag, out_dir, name, kf)
        failures += rc
        if rc:
            log.warning("失败：%s", name)
    log.info("批量动画结束，失败 %d", failures)
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
