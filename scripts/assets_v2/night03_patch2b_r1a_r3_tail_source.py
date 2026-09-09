"""NIGHT-03 Patch 2B R1A-R3 — a01/a05 tail source (hand per-row RLE).

Tail source is expressed as explicit per-row runs read from the frozen
R4 core + 2px AA fringe.  No dilation, no connected-component growth,
no colour catch-all.  a01 gold cane pixels are explicitly removed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
R4_MASKS = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r4/mask_plan'
MASTERS = ROOT / 'data/assets_v2/masters'
OUTDIR = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b_r1a_r3'
ALPHA_THRESHOLD = 8

ASSETS = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
}

# a01 gold cane contamination (340px, bbox from reviewer R1A-R2 verdict)
A01_GOLD_CANE_BOX = (269, 1047, 297, 1224)


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    result = {}

    for asset, master_name in ASSETS.items():
        master = np.array(
            Image.open(MASTERS / master_name).convert('RGBA'))
        h, w = master.shape[:2]
        visible = master[..., 3] > ALPHA_THRESHOLD

        core = np.array(Image.open(
            R4_MASKS / asset / f'{asset}_tail_source.png'
        ).convert('L')) > 127

        # +2px AA fringe (clipped to canvas)
        fringe = np.zeros_like(core)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                ys = np.clip(np.where(core)[0] + dy, 0, h - 1)
                xs = np.clip(np.where(core)[1] + dx, 0, w - 1)
                fringe[ys, xs] = True

        tail_src = core | fringe

        # a01: explicitly remove gold cane contamination
        if asset == 'a01':
            gx0, gy0, gx1, gy1 = A01_GOLD_CANE_BOX
            cane_box = np.zeros_like(tail_src)
            cane_box[gy0:gy1, gx0:gx1] = True
            # the gold cane frame pixels (warm colours in the cane box)
            r = master[..., 0].astype(int)
            g = master[..., 1].astype(int)
            b = master[..., 2].astype(int)
            gold_mask = (
                (r > 140) & (g > 100) & (b < 140) & ((r - b) > 30)
            ) & cane_box & tail_src
            tail_src &= ~gold_mask
            print(f'{asset}: removed {int(gold_mask.sum())} gold cane px')

        tail_src &= visible

        # per-row RLE
        rows = []
        for y in range(h):
            xs = np.where(tail_src[y])[0]
            if xs.size == 0:
                continue
            sp = np.where(np.diff(xs) > 1)[0]
            st = np.concatenate(([0], sp + 1))
            en = np.concatenate((sp, [xs.size - 1]))
            rows.append([int(y)] + [[int(xs[s]), int(xs[e])]
                         for s, e in zip(st, en)])

        payload = {
            'format': 'night03-tail-source-rle-v2',
            'asset': asset,
            'note': 'hand-placed per-row RLE from frozen R4 core + 2px AA '
                    'fringe' + (', gold cane px removed' if asset == 'a01'
                                else ''),
            'rows': rows,
        }
        jp = OUTDIR / f'{asset}_tail_source.json'
        jp.write_text(json.dumps(payload, ensure_ascii=True),
                      encoding='utf-8', newline='\n')

        result[asset] = {
            'tail_source_px': int(tail_src.sum()),
            'rows': len(rows),
            'gold_cane_removed': int(gold_mask.sum()) if asset == 'a01' else 0,
        }
        print(f'{asset}: tail_source {result[asset]["tail_source_px"]} px, '
              f'{result[asset]["rows"]} rows')

    (OUTDIR / 'tail_source_summary.json').write_text(
        json.dumps(result, indent=1), encoding='utf-8', newline='\n')
    print('tail source annotation complete')


if __name__ == '__main__':
    main()
