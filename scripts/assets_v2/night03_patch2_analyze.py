"""NIGHT-03 Patch 2 — precise component analysis (Builder dev tool).

Reads ONLY masters. Writes grid-annotated zoom crops + span reports under
repair_candidates/night03_patch2/_analyze/.  Used to design the frozen Mask
Plan; not part of the plan itself.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2/_analyze'
OUT.mkdir(parents=True, exist_ok=True)
ST = ndimage.generate_binary_structure(2, 2)

IM = {
    'a01': np.array(Image.open(MASTERS / 'furina_v2_a01_stand_neutral_front.png').convert('RGBA')),
    'a05': np.array(Image.open(MASTERS / 'furina_v2_a05_stand_confident_proud.png').convert('RGBA')),
    'a16': np.array(Image.open(MASTERS / 'furina_v2_a16_work_focused.png').convert('RGBA')),
}


def grid_crop(key, x0, y0, x1, y1, zoom, name, step=20, major=100):
    im = IM[key][y0:y1, x0:x1]
    h, w = im.shape[:2]
    bg = np.full((h, w, 3), 255, np.uint8)
    a = im[..., 3:4].astype(np.float32) / 255.0
    comp = (im[..., :3].astype(np.float32) * a + bg * (1 - a)).astype(np.uint8)
    big = np.array(Image.fromarray(comp).resize((w * zoom, h * zoom), Image.NEAREST))
    im2 = Image.fromarray(big)
    d = ImageDraw.Draw(im2)
    for gx in range(x0 - x0 // step * step, x1 + 1, step):
        if gx < x0:
            continue
        X = (gx - x0) * zoom
        col = (255, 0, 0) if gx % major == 0 else (0, 200, 0)
        d.line([(X, 0), (X, big.shape[0])], fill=col, width=1)
        if gx % major == 0:
            d.text((X + 2, 2), str(gx), fill=(200, 0, 0))
    for gy in range(y0 - y0 // step * step, y1 + 1, step):
        if gy < y0:
            continue
        Y = (gy - y0) * zoom
        col = (255, 0, 0) if gy % major == 0 else (0, 200, 0)
        d.line([(0, Y), (big.shape[1], Y)], fill=col, width=1)
        if gy % major == 0:
            d.text((2, Y + 2), str(gy), fill=(200, 0, 0))
    im2.save(OUT / f'{name}.png')
    print('grid', name)


def comps_report(key, mask, min_px=30, name='comps'):
    lab, n = ndimage.label(mask, structure=ST)
    out = []
    for i in range(1, n + 1):
        c = lab == i
        s = int(c.sum())
        if s < min_px:
            continue
        ys, xs = np.where(c)
        out.append({'id': int(i), 'px': s,
                    'bbox': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]})
    out.sort(key=lambda t: -t['px'])
    print(f'--- {key} {name}: {len(out)} comps >= {min_px}px')
    for t in out[:25]:
        print('   ', t)
    return out


def spans(key, mask, y0, y1, step=10, label=''):
    print(f'--- {key} spans {label} (rows {y0}..{y1} step {step})')
    for y in range(y0, y1 + 1, step):
        xs = np.where(mask[y])[0]
        if xs.size == 0:
            print(f'  y={y}: -')
            continue
        runs = np.split(xs, np.where(np.diff(xs) > 2)[0] + 1)
        rr = [f'{r[0]}-{r[-1]}' for r in runs]
        print(f'  y={y}: {", ".join(rr)}')


def tint_tail(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = (r + g + b) / 3.0
    pale = (b - r >= 18) & (bright >= 130) & (g >= r - 10)
    shadow = (g - r >= 25) & (b - r >= 35) & (bright >= 110) & (b > g)
    return pale | shadow


def main():
    for k, im in IM.items():
        rgb = im[..., :3].astype(int)
        alpha = im[..., 3] > 8
        lab, n = ndimage.label(alpha, structure=ST)
        sizes = ndimage.sum(alpha, lab, range(1, n + 1))
        order = np.argsort(sizes)[::-1]
        print(f'== {k} alpha comps: {n}, top sizes: {[int(sizes[i]) for i in order[:6]]}')

    a01 = IM['a01']
    rgb = a01[..., :3].astype(int)
    alpha = a01[..., 3] > 8
    tint = tint_tail(rgb) & alpha
    comps_report('a01', tint & (np.arange(a01.shape[0])[:, None] > 900), 200,
                 'tail-tint comps y>900')
    grid_crop('a01', 140, 900, 460, 1130, 3, 'a01_root_seam')
    grid_crop('a01', 250, 1050, 420, 1350, 3, 'a01_tail_cane')
    grid_crop('a01', 330, 940, 560, 1160, 3, 'a01_root_body')
    grid_crop('a01', 340, 690, 400, 740, 8, 'a01_speck_363')
    spans('a01', tint, 940, 1420, 20, 'tail tint')

    a05 = IM['a05']
    rgb = a05[..., :3].astype(int)
    alpha = a05[..., 3] > 8
    tint = tint_tail(rgb) & alpha
    comps_report('a05', tint, 150, 'tail-tint comps all')
    grid_crop('a05', 300, 830, 560, 1080, 3, 'a05_bow_root')
    grid_crop('a05', 250, 1030, 480, 1330, 3, 'a05_tail_coattail')
    grid_crop('a05', 560, 820, 900, 1180, 2, 'a05_right_rootzone')
    grid_crop('a05', 590, 1250, 700, 1350, 5, 'a05_wisp')

    a16 = IM['a16']
    rgb = a16[..., :3].astype(int)
    alpha = a16[..., 3] > 8
    tint = tint_tail(rgb) & alpha
    r_, g_, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = (r_ + g_ + b_) / 3.0
    wood = (r_ > g_) & (g_ > b_) & (r_ - b_ >= 14) & (r_ - g_ <= 50) & (r_ >= 40) & (r_ < 210)
    white = (bright >= 185) & (np.abs(b_ - r_) <= 30)
    comps_report('a16', wood & alpha, 100, 'wood comps')
    comps_report('a16', tint, 150, 'tail-tint comps')
    grid_crop('a16', 660, 850, 880, 1080, 4, 'a16_hand_pommel_grid')
    grid_crop('a16', 640, 1020, 820, 1180, 4, 'a16_guard_lavender')
    grid_crop('a16', 400, 1100, 720, 1360, 3, 'a16_chair_full')
    grid_crop('a16', 430, 1230, 700, 1500, 3, 'a16_tip_zone')
    grid_crop('a16', 150, 1060, 480, 1460, 2, 'a16_tail_left')
    grid_crop('a16', 350, 1060, 560, 1240, 3, 'a16_tailroot_body')
    grid_crop('a16', 250, 930, 330, 1090, 5, 'a16_specks')
    spans('a16', wood & alpha, 1100, 1480, 20, 'wood')


if __name__ == '__main__':
    main()
