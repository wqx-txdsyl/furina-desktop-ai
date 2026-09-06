"""NIGHT-03 Patch 2 — builder visual inspection helper.

Reads ONLY masters + BASE (legal inputs). Writes diagnostic crops under
data/assets_v2/repair_candidates/night03_patch2/_inspect/.
This is a Builder debugging aid; it is NOT part of the frozen mask plan.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
BASE_P = ROOT / 'data/assets_v2/_base/furina-base.png'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2/_inspect'
OUT.mkdir(parents=True, exist_ok=True)

ASSETS = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}


def checker(w, h, c=24):
    t = np.zeros((h, w, 3), np.uint8)
    for y in range(h):
        for x in range(w):
            t[y, x] = (200, 200, 200) if ((x // c) + (y // c)) % 2 == 0 else (150, 150, 150)
    return t


def on_checker(im_rgba):
    bg = checker(im_rgba.shape[1], im_rgba.shape[0])
    a = im_rgba[..., 3:4].astype(np.float32) / 255.0
    out = (im_rgba[..., :3].astype(np.float32) * a
           + bg.astype(np.float32) * (1 - a)).astype(np.uint8)
    return out


def save(arr, name):
    Image.fromarray(arr).save(OUT / name)
    print('wrote', name)


def main():
    base_full = np.array(Image.open(BASE_P).convert('RGBA'))
    # BASE upscaled to 1024x1536 for side-by-side reference (nearest to keep pixels)
    base_big = np.array(Image.fromarray(base_full).resize((1024, 1536), Image.NEAREST))
    save(on_checker(base_big), 'base_full_checker.png')

    for key, fn in ASSETS.items():
        im = np.array(Image.open(MASTERS / fn).convert('RGBA'))
        save(on_checker(im), f'{key}_full_checker.png')
        save(on_checker(base_big), 'base_full_checker.png')

    # --- a01 crops: tail zone, cane, head
    a01 = np.array(Image.open(MASTERS / ASSETS['a01']).convert('RGBA'))
    save(on_checker(a01[60:520, 200:830]), 'a01_head_100.png')
    save(on_checker(a01[840:1130, 150:520]), 'a01_tailtop_cane_100.png')
    z = np.array(Image.fromarray(on_checker(a01[840:1130, 150:520])).resize(
        (740 * 2, 290 * 2), Image.NEAREST))
    save(z, 'a01_tailtop_cane_200.png')
    save(on_checker(a01[1100:1470, 120:480]), 'a01_tailbottom_100.png')
    z = np.array(Image.fromarray(on_checker(a01[1100:1470, 120:480])).resize(
        (720 * 2, 740 * 2), Image.NEAREST))
    save(z, 'a01_tailbottom_200.png')

    # --- a05 crops: bow, tail, wisp, cane
    a05 = np.array(Image.open(MASTERS / ASSETS['a05']).convert('RGBA'))
    save(on_checker(a05[820:1180, 100:560]), 'a05_bow_tailtop_100.png')
    z = np.array(Image.fromarray(on_checker(a05[820:1180, 100:560])).resize(
        (920 * 2, 720 * 2), Image.NEAREST))
    save(z, 'a05_bow_tailtop_200.png')
    save(on_checker(a05[1150:1470, 120:480]), 'a05_tailbottom_100.png')
    save(on_checker(a05[1240:1340, 580:710]), 'a05_wisp_100.png')
    z = np.array(Image.fromarray(on_checker(a05[1240:1340, 580:710])).resize(
        (260 * 4, 200 * 4), Image.NEAREST))
    save(z, 'a05_wisp_400.png')

    # --- a16 crops: hair/pommel, hand/guard, quill/paper, chair, tail
    a16 = np.array(Image.open(MASTERS / ASSETS['a16']).convert('RGBA'))
    save(on_checker(a16[690:1180, 180:920]), 'a16_upper_100.png')
    z = np.array(Image.fromarray(on_checker(a16[880:1180, 540:900])).resize(
        (720 * 2, 600 * 2), Image.NEAREST))
    save(z, 'a16_hand_pommel_200.png')
    z = np.array(Image.fromarray(on_checker(a16[690:1060, 620:900])).resize(
        (560 * 2, 740 * 2), Image.NEAREST))
    save(z, 'a16_righthair_pommel_200.png')
    save(on_checker(a16[1080:1500, 260:840]), 'a16_chair_tail_100.png')
    z = np.array(Image.fromarray(on_checker(a16[1080:1500, 260:840])).resize(
        (1160 * 2, 840 * 2), Image.NEAREST))
    save(z, 'a16_chair_tail_200.png')
    save(on_checker(a16[900:1180, 260:520]), 'a16_quill_paper_100.png')


if __name__ == '__main__':
    main()
