"""NIGHT-03 gate checks, triptychs and runtime previews (read-only wrt masters)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/assets_v2/repair_candidates/night03'
BASE = np.array(Image.open(ROOT / 'data/assets_v2/_base/furina-base.png'))
MASTERS = ROOT / 'data/assets_v2/masters'
NAMES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}
# zones allowed to change (tail corridor on both sides + prop zones)
ZONES = {
    'a01': [(60, 850, 900, 1475)],
    'a05': [(100, 850, 900, 1475)],
    'a16': [(100, 850, 920, 1475), (380, 1140, 720, 1475), (600, 850, 820, 1140)],
}


def check(key):
    name = NAMES[key]
    im_o = np.array(Image.open(MASTERS / name))
    im_n = np.array(Image.open(OUT / f'furina_v2_{key}_repair.png'))
    res = {}
    diff = np.any(im_o != im_n, axis=-1)
    zone = np.zeros(diff.shape, bool)
    for x0, y0, x1, y1 in ZONES[key]:
        zone[y0:y1, x0:x1] = True
    res['changed_px'] = int(diff.sum())
    res['changed_outside_zone'] = int((diff & ~zone).sum())
    res['changed_pct'] = round(100 * diff.sum() / diff.size, 2)
    a = im_n[..., 3] > 8
    lab, n = ndimage.label(a)
    sizes = sorted(ndimage.sum(a, lab, range(1, n + 1)).tolist(), reverse=True)
    res['alpha_components'] = n
    res['islands_gt40px'] = int(sum(1 for s in sizes[1:] if s > 40))
    rows = np.where(a.any(axis=1))[0]
    cols = np.where(a.any(axis=0))[0]
    res['bbox'] = [int(cols.min()), int(rows.min()), int(cols.max()), int(rows.max())]
    res['lowest_row'] = int(rows.max())
    res['com_x'] = round(float((np.arange(1024)[None, :] * a).sum() / a.sum()) / 1024, 4)
    rgb = im_n[..., :3].astype(int)
    magenta = ((rgb[..., 0] > 180) & (rgb[..., 2] > 180) & (rgb[..., 1] < 90) & a)
    res['magenta_px'] = int(magenta.sum())
    corners = [im_n[0:24, 0:24, 3].max(), im_n[0:24, -24:, 3].max(),
               im_n[-24:, 0:24, 3].max(), im_n[-24:, -24:, 3].max()]
    res['corner_alpha_max'] = [int(c) for c in corners]
    # head/torso untouched (identity by construction)
    res['head_zone_changed'] = int(diff[:850, :].sum())
    return res


def triptych(key):
    name = NAMES[key]
    o = Image.open(MASTERS / name).convert('RGBA')
    n = Image.open(OUT / f'furina_v2_{key}_repair.png').convert('RGBA')
    b = Image.fromarray(BASE).convert('RGBA').resize((683, 1024))
    w = Image.new('RGBA', (1024 + 8, 1024), (30, 30, 30, 255))
    w.paste(o.resize((683, 1024)), (0, 0))
    w.paste(n.resize((683, 1024)), (341, 0))
    w.alpha_composite(b, (341, 0))
    panel = Image.new('RGBA', (1024 * 2 + 16, 1024), (30, 30, 30, 255))
    panel.paste(o.resize((683, 1024)), (0, 0))
    panel.paste(n.resize((683, 1024)), (683 + 8, 0))
    panel.paste(b, (1366 + 16, 0))
    panel.save(OUT / f'night03_triptych_{key}.png')


def previews(key):
    n = Image.open(OUT / f'furina_v2_{key}_repair.png').convert('RGBA')
    d = OUT / 'runtime_previews'
    d.mkdir(exist_ok=True)
    for s in (512, 256, 128):
        n.resize((s, int(s * 1.5)), Image.LANCZOS).save(d / f'{key}_pet_{s}.png')


if __name__ == '__main__':
    report = {}
    for key in NAMES:
        report[key] = check(key)
        triptych(key)
        previews(key)
        print(key, json.dumps(report[key]))
    (OUT / '_gate_checks.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
