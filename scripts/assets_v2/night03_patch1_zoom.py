"""NIGHT-03 Patch 1 — high-zoom zone crops (4x) + tint-mask overlay evidence."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch1/_inspect'
OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}

ZOOMS = {
    'a01': [
        ('arm_glove', (230, 850, 410, 1170), 3),
        ('fan_bottom', (150, 1150, 420, 1400), 3),
        ('tail_top', (280, 880, 420, 1080), 3),
    ],
    'a05': [
        ('bow_zone', (300, 840, 480, 1120), 3),
        ('tail_root_top', (280, 880, 420, 1120), 3),
        ('tail_bottom', (140, 1150, 420, 1420), 3),
    ],
    'a16': [
        ('grip4x', (560, 940, 820, 1240), 4),
        ('cane_head', (640, 880, 900, 1080), 3),
        ('tail_root', (300, 840, 520, 1140), 3),
    ],
}


def tint(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = (r + g + b) / 3.0
    pale = (b >= r) & (b - r >= 6) & (bright >= 150) & (g >= r - 4)
    shadow = (g - r >= 25) & (b - r >= 35) & (bright >= 110) & (b > g)
    return pale | shadow


def overlay(im, box, grid=False):
    a = np.array(im)
    rgb = a[..., :3].astype(int)
    m = tint(rgb) & (a[..., 3] > 8)
    vis = a.copy()
    vis[m] = [255, 0, 0, 255]
    out = Image.fromarray(np.ascontiguousarray(vis))
    flat = Image.fromarray(a)
    panel = Image.new('RGBA', (a.shape[1] * 2 + 6, a.shape[0]), (30, 30, 30, 255))
    panel.paste(flat, (0, 0))
    panel.paste(out, (a.shape[1] + 6, 0))
    return panel


def main():
    for key, fname in FILES.items():
        src = Image.open(MASTERS / fname).convert('RGBA')
        for name, box, scale in ZOOMS[key]:
            crop = src.crop(box)
            ov = overlay(crop, box)
            ov = ov.resize((ov.width * scale, ov.height * scale), Image.NEAREST)
            if ov.width > 1900:
                ov = ov.resize((1900, int(ov.height * 1900 / ov.width)), Image.LANCZOS)
            ov.convert('RGB').save(OUT / f'{key}_{name}.png')
            print(f'{key}/{name} {box} -> saved')


if __name__ == '__main__':
    main()
