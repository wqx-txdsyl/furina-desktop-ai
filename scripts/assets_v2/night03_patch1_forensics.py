"""NIGHT-03 Patch 1 — scanline/component forensics for precise mask boundaries.

Read-only on masters/BASE. Writes a text dump + small diagnostic PNGs under
night03_patch1/_inspect/. Output is the evidence base for mask vertex tables.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
BASE = ROOT / 'data/assets_v2/_base/furina-base.png'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch1/_inspect'
OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}


def tail_tint(rgb, variant=0):
    """Variants of the pale hair/tail tint. variant switchable for tuning."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = (r + g + b) / 3.0
    pale = (b >= r) & (b - r >= 6) & (bright >= 150) & (g >= r - 4)
    shadow = (g - r >= 25) & (b - r >= 35) & (bright >= 110) & (b > g)
    white = (np.abs(b - r) <= 16) & (np.abs(g - r) <= 16) & (bright >= 200)
    if variant == 0:
        return pale | shadow
    if variant == 1:
        return pale | shadow | white
    return pale


def comp_report(mask, alpha, min_px=300, rois=None):
    lab, n = ndimage.label(mask)
    rows = []
    for i in range(1, n + 1):
        c = lab == i
        sz = int(c.sum())
        if sz < min_px:
            continue
        ys, xs = np.where(c)
        rows.append((sz, int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    rows.sort(reverse=True)
    return rows


def scanline_rows(im, rows, x0, x1, label):
    a = im[..., 3] > 8
    out = []
    for y in rows:
        line = a[y, x0:x1]
        xs = np.where(line)[0]
        if xs.size == 0:
            out.append(f'  y={y}: none')
            continue
        runs = np.split(xs, np.where(np.diff(xs) > 1)[0] + 1)
        parts = []
        for r in runs:
            if r.size < 2:
                continue
            cx = x0 + (r[0] + r[-1]) // 2
            px = im[y, cx, :3]
            parts.append(f'{x0 + int(r[0])}-{x0 + int(r[-1])} rgb{tu(px)}')
        out.append(f'  y={y}: ' + ' | '.join(parts))
    print(f'== {label} ==')
    for l in out:
        print(l)


def tu(px):
    return tuple(int(v) for v in px)


def col_scan(im, cols, y0, y1, label):
    a = im[..., 3] > 8
    print(f'== {label} (cols) ==')
    for x in cols:
        line = a[y0:y1, x]
        ys = np.where(line)[0]
        if ys.size == 0:
            print(f'  x={x}: none')
            continue
        runs = np.split(ys, np.where(np.diff(ys) > 1)[0] + 1)
        parts = []
        for r in runs:
            if r.size < 2:
                continue
            cy = y0 + (r[0] + r[-1]) // 2
            px = im[cy, x, :3]
            parts.append(f'{y0 + int(r[0])}-{y0 + int(r[-1])} rgb{tu(px)}')
        print(f'  x={x}: ' + ' | '.join(parts))


def main():
    for key, fname in FILES.items():
        im = np.array(Image.open(MASTERS / fname))
        a = im[..., 3] > 8
        rgb = im[..., :3].astype(int)
        print('#' * 20, key, '#' * 20)
        for variant, name in ((0, 'tail_tint_v0'), (1, 'tail_tint_v1')):
            mask = tail_tint(rgb, variant) & a
            comps = comp_report(mask, a, min_px=200)
            print(f'-- {name} components (sz, xmin,ymin,xmax,ymax):')
            for c in comps[:14]:
                print('   ', c)
        print()

    # BASE for cross-check of tail side
    base = np.array(Image.open(BASE))
    ba = base[..., 3] > 8
    brgb = base[..., :3].astype(int)
    mask = tail_tint(brgb, 0) & ba
    comps = comp_report(mask, ba, min_px=100)
    print('BASE tail_tint components:')
    for c in comps:
        print('   ', c)

    for key, fname in FILES.items():
        im = np.array(Image.open(MASTERS / fname))
        if key == 'a01':
            scanline_rows(im, [950, 1000, 1050, 1100, 1150, 1200, 1250, 1300, 1320], 100, 520, 'a01 rows')
            col_scan(im, [160, 200, 240, 280, 320, 360, 390, 410, 425, 440, 460], 880, 1420, 'a01 cols')
        elif key == 'a05':
            scanline_rows(im, [880, 920, 960, 1000, 1050, 1100, 1150, 1200, 1250, 1300], 100, 520, 'a05 rows')
            col_scan(im, [160, 200, 240, 280, 320, 360, 400, 430, 460, 490], 850, 1420, 'a05 cols')
        else:
            scanline_rows(im, [1000, 1040, 1080, 1120, 1160, 1200, 1240, 1280, 1320, 1360, 1400, 1440], 150, 620, 'a16 rows (tail)')
            scanline_rows(im, [900, 930, 960, 990, 1020, 1050, 1080, 1110, 1140, 1170, 1200], 560, 900, 'a16 rows (grip/cane)')
            col_scan(im, [620, 660, 700, 740, 780, 820, 860], 900, 1500, 'a16 cols (grip)')
            col_scan(im, [200, 250, 300, 350, 400, 450, 500], 1050, 1470, 'a16 cols (tail)')


if __name__ == '__main__':
    main()
