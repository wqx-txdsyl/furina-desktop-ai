"""NIGHT-03 Patch 2A R6A-R1 — Builder dev tool: fine grid crops for
manual contour tracing. NOT part of the deliverable plan.

Reads ONLY the a16 master. Writes zoomed grid tiles under
repair_candidates/night03_patch2a_r6ar1/_dev_crops/.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / ('data/assets_v2/repair_candidates/night03_patch2a_r6ar1/'
              '_dev_crops')
OUT.mkdir(parents=True, exist_ok=True)

MASTER_FILE = 'furina_v2_a16_work_focused.png'
IM = np.array(Image.open(MASTERS / MASTER_FILE).convert('RGBA'))


def tile(x0, y0, x1, y1, zoom, name, step=10, major=50):
    im = IM[y0:y1, x0:x1]
    h, w = im.shape[:2]
    big = np.full((h, w, 3), 255, np.uint8)
    a = im[..., 3:4].astype(np.float32) / 255.0
    comp = (im[..., :3].astype(np.float32) * a + big * (1 - a)
            ).astype(np.uint8)
    img = Image.fromarray(comp).resize((w * zoom, h * zoom), Image.NEAREST)
    d = ImageDraw.Draw(img)
    for gx in range(x0 - x0 % step, x1 + 1, step):
        if gx < x0:
            continue
        X = (gx - x0) * zoom
        col = (255, 0, 0) if gx % major == 0 else (0, 200, 0)
        d.line([(X, 0), (X, h * zoom)], fill=col, width=1)
        if gx % major == 0:
            d.text((X + 2, 2), str(gx), fill=(180, 0, 0))
    for gy in range(y0 - y0 % step, y1 + 1, step):
        if gy < y0:
            continue
        Y = (gy - y0) * zoom
        col = (255, 0, 0) if gy % major == 0 else (0, 200, 0)
        d.line([(0, Y), (w * zoom, Y)], fill=col, width=1)
        if gy % major == 0:
            d.text((2, Y + 2), str(gy), fill=(180, 0, 0))
    img.save(OUT / f'{name}.png')
    print('tile', name, f'{w}x{h} @{zoom}x')


def dark_tile(x0, y0, x1, y1, zoom, name):
    im = IM[y0:y1, x0:x1]
    h, w = im.shape[:2]
    big = np.full((h, w, 3), 30, np.uint8)
    a = im[..., 3:4].astype(np.float32) / 255.0
    comp = (im[..., :3].astype(np.float32) * a + big * (1 - a)
            ).astype(np.uint8)
    img = Image.fromarray(comp).resize((w * zoom, h * zoom), Image.NEAREST)
    img.save(OUT / f'{name}.png')
    print('dark', name)


TILES = [
    # cane head / top ornament zone
    (690, 880, 830, 1030, 4, 'head'),
    # shaft upper (over right hand / glove zone)
    (600, 980, 740, 1130, 4, 'shaft_upper'),
    # shaft lower (over lap / belt / costume)
    (620, 1080, 780, 1240, 3, 'shaft_lower'),
    # blade upper (over chair seat / tail)
    (570, 1150, 730, 1310, 3, 'blade_upper'),
    # blade lower (tip zone over background)
    (570, 1290, 730, 1460, 3, 'blade_lower'),
    # chair seat zone (vs costume / tail)
    (390, 1200, 560, 1340, 3, 'chair_seat_left'),
    (540, 1200, 720, 1340, 3, 'chair_seat_right'),
    # chair legs zone
    (450, 1300, 620, 1470, 3, 'chair_legs_left'),
    (560, 1290, 730, 1470, 3, 'chair_legs_right'),
    # right hair vs cane head boundary context
    (700, 860, 900, 1010, 3, 'hair_head_context'),
    # glove / hand closeup
    (570, 970, 700, 1160, 4, 'glove_hand'),
]

for x0, y0, x1, y1, z, name in TILES:
    tile(x0, y0, x1, y1, z, f'{name}_grid')
    dark_tile(x0, y0, x1, y1, z, f'{name}_dark')

# alpha map overview of the two zones
for nm, (x0, y0, x1, y1) in {
        'zone_cane': (560, 880, 840, 1470),
        'zone_chair': (380, 1190, 730, 1470)}.items():
    a = IM[y0:y1, x0:x1, 3]
    img = Image.fromarray(a, 'L').resize(((x1 - x0) * 2, (y1 - y0) * 2),
                                         Image.NEAREST)
    img.save(OUT / f'{nm}_alpha2x.png')
    print('alpha', nm)
