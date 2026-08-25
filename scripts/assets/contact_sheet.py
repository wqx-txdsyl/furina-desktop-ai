"""角色一致性验收：把 manifest 里的资产拼成一张联络表。

    python scripts/assets/contact_sheet.py --out data/assets/_sheet.png

作用：把 座/坐/躺/睡 + 表情 + 视线 放在一张图上，一眼核对“是不是同一个芙宁娜”。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image, ImageDraw, ImageFont

from furina.config import load_config
from furina.assets.asset_manifest import AssetManifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/assets/_sheet.png")
    ap.add_argument("--cell-h", type=int, default=300)
    args = ap.parse_args()

    cfg = load_config()
    manifest = AssetManifest.load(cfg.model_manifest_path)
    entries = manifest.entries
    if not entries:
        print("manifest 无资产")
        return 1

    cell_h = args.cell_h
    cols = 5
    rows = (len(entries) + cols - 1) // cols
    cell_w = int(cell_h * 0.7)
    label_h = 22
    sheet = Image.new("RGBA", (cols * cell_w, rows * (cell_h + label_h)), (255, 255, 255, 255))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("msyh.ttc", 13) or ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    for i, e in enumerate(entries):
        p = cfg.assets_dir / e.path
        if not p.exists():
            continue
        im = Image.open(p).convert("RGBA")
        # 等比缩放到 cell_w x cell_h（保持透明）
        im.thumbnail((cell_w, cell_h))
        col, row = i % cols, i // cols
        x = col * cell_w + (cell_w - im.width) // 2
        y = row * (cell_h + label_h) + (cell_h - im.height) // 2
        # 白底上去掉透明显示
        cell_bg = Image.new("RGBA", sheet.size, (255, 255, 255, 255))
        sheet.alpha_composite(im, (x, y))
        d.text((col * cell_w + 2, row * (cell_h + label_h) + cell_h + 4),
               f"{e.posture}/{e.emotion}/{e.gaze}", fill=(30, 30, 40), font=font)

    sheet.convert("RGB").save(args.out)
    print(f"联络表 -> {args.out}  ({len(entries)} 张)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
