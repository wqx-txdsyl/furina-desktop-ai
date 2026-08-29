"""NIGHT-03 Patch 1 — master pixel forensics: grid crops of critical zones.

Writes diagnostic PNGs only under repair_candidates/night03_patch1/_inspect/.
Masters are opened read-only; nothing else is written.

Use: python scripts/assets_v2/night03_patch1_inspect.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch1/_inspect'
OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}

# (key, crop box, upscale) — boxes chosen around every defect/costume zone
CROPS = {
    'a01': [
        ('grid_full', (0, 0, 1024, 1536), 1),
        ('tail_zone', (100, 850, 560, 1500), 2),
        ('top_curl', (150, 100, 500, 420), 2),
        ('lining', (330, 900, 500, 1400), 3),
        ('cane', (200, 1000, 420, 1536), 2),
    ],
    'a05': [
        ('grid_full', (0, 0, 1024, 1536), 1),
        ('tail_zone', (100, 800, 560, 1460), 2),
        ('bow', (300, 800, 520, 1130), 3),
        ('wisp', (540, 1200, 760, 1400), 3),
        ('cane_right', (680, 850, 900, 1536), 2),
    ],
    'a16': [
        ('grid_full', (0, 0, 1024, 1536), 1),
        ('hair_right', (560, 760, 900, 1060), 3),
        ('grip', (560, 900, 860, 1280), 3),
        ('chair', (400, 1080, 800, 1536), 2),
        ('tail_zone', (160, 1060, 560, 1500), 2),
    ],
}


def grid(im, step=50, major=100):
    im = im.convert('RGBA')
    im = im.resize((im.width // 1, im.height // 1))  # identity
    d = ImageDraw.Draw(im)
    w, h = im.size
    for x in range(0, w, step):
        c = (255, 0, 0, 90) if x % major == 0 else (255, 160, 0, 55)
        d.line([(x, 0), (x, h)], fill=c, width=1)
        if x % major == 0:
            d.text((x + 2, 2), str(x), fill=(255, 60, 60, 255))
    for y in range(0, h, step):
        c = (255, 0, 0, 90) if y % major == 0 else (255, 160, 0, 55)
        d.line([(0, y), (w, y)], fill=c, width=1)
        if y % major == 0:
            d.text((2, y + 2), str(y), fill=(255, 60, 60, 255))
    return im


def checker(im):
    """Transparent backdrop -> light checkerboard so alpha edges are visible."""
    im = im.convert('RGBA')
    a = np.array(im)
    out = np.zeros((*a.shape[:2], 4), np.uint8)
    c1 = np.array([80, 80, 80, 255], np.uint8)
    c0 = np.array([25, 25, 25, 255], np.uint8)
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    out[..., :3] = np.where(((xx // 16 + yy // 16) % 2)[..., None] == 1, c1[:3], c0[:3])
    out[..., 3] = 255
    al = a[..., 3:4].astype(np.float32) / 255.0
    out[..., :3] = (a[..., :3].astype(np.float32) * al + out[..., :3] * (1 - al)).astype(np.uint8)
    return Image.fromarray(out)


def main():
    for key, fname in FILES.items():
        src = Image.open(MASTERS / fname).convert('RGBA')
        for name, box, scale in CROPS[key]:
            crop = src.crop(box)
            if name == 'grid_full':
                vis = grid(crop.copy())
                vis = vis.resize((600, 900), Image.LANCZOS)
            else:
                cb = checker(crop)
                g = grid(crop.copy())
                # side-by-side: flat | checkerboard
                panel = Image.new('RGBA', (crop.width * scale * 2 + 8, crop.height * scale), (35, 35, 35, 255))
                panel.paste(crop.resize((crop.width * scale, crop.height * scale), Image.NEAREST), (0, 0))
                panel.paste(g.resize((crop.width * scale, crop.height * scale), Image.NEAREST), (crop.width * scale + 8, 0))
                vis = panel
                if vis.width > 1600:
                    vis = vis.resize((1600, int(vis.height * 1600 / vis.width)), Image.LANCZOS)
            vis.convert('RGB').save(OUT / f'{key}_{name}.png')
            print(f'{key}/{name}: {box} scale={scale} -> {OUT / (key + "_" + name + ".png")}')


if __name__ == '__main__':
    main()
