"""NIGHT-03 Recovery Patch 2A R6A-R1 — Builder manual annotation tool.

Produces the EXTERNAL static ownership source
``a16_ownership_annotation.json`` (per-row scanline RLE) for asset a16.

Every run below was hand-placed by the Builder from visual analysis of
zoomed grid crops (4x/5x for the cane head, 3x/4x for shaft/guard/blade/
chair) plus numeric pixel probes at boundary rows.  The freeze script
consumes the JSON read-only; it never generates or modifies it.

Interpolation: between two control rows the tool linearly interpolates
the run edges; this only serialises the Builder's hand-placed landmarks
into the required per-row scanline format.

label 0 is RESERVED for transparent background.  Every alpha>8 pixel
receives an explicit semantic label; pixels not covered by any hand
region are explicitly assigned protected_other_character (7).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
OUTDIR = ROOT / ('data/assets_v2/repair_candidates/'
                 'night03_patch2a_r6ar1')
DEVDIR = OUTDIR / '_dev_crops'
MASTER_FILE = 'furina_v2_a16_work_focused.png'
ALPHA_THRESHOLD = 8

LABELS = [
    {'id': 0, 'name': 'background'},
    {'id': 1, 'name': 'protected_hair'},
    {'id': 2, 'name': 'protected_quill_paper'},
    {'id': 3, 'name': 'protected_glove_gold_cuff'},
    {'id': 4, 'name': 'protected_costume'},
    {'id': 5, 'name': 'remove_cane'},
    {'id': 6, 'name': 'remove_chair'},
    {'id': 7, 'name': 'protected_other_character'},
]
L_HAIR, L_QUILL, L_GLOVE, L_COSTUME, L_CANE, L_CHAIR, L_OTHER = range(1, 8)

# --------------------------------------------------------------------------
# hand-placed control rows: (y, x_left, x_right_inclusive)
# linear interpolation between consecutive control rows of one part.
# --------------------------------------------------------------------------

HAIR = [
    (540, 155, 400), (580, 155, 650), (600, 200, 650), (620, 200, 700),
    (700, 200, 700), (745, 250, 760), (780, 250, 790), (820, 250, 790),
    (870, 250, 790), (900, 280, 750), (920, 300, 700), (940, 320, 660),
    (850, 550, 700), (900, 560, 700), (950, 570, 700), (1000, 580, 690),
    (1050, 590, 670), (1100, 600, 650), (1150, 610, 640),
]

QUILL = [(940, 320, 400), (1100, 320, 400)]
PAPER = [(1085, 330, 510), (1180, 330, 510)]

GLOVE = [
    (930, 690, 745), (950, 680, 730), (970, 670, 725), (990, 660, 722),
    (1010, 650, 723), (1030, 642, 724), (1050, 638, 722), (1070, 636, 720),
    (1090, 638, 716), (1110, 640, 714), (1130, 644, 710), (1145, 648, 706),
]

TORSO = [
    (880, 380, 550), (950, 370, 600), (1000, 360, 620), (1050, 360, 620),
    (1100, 360, 620), (1150, 370, 620), (1200, 380, 620), (1240, 390, 620),
]
NECK = [(880, 430, 560), (950, 430, 560)]
BELT_HIP = [
    (1050, 700, 780), (1100, 700, 810), (1150, 700, 825), (1200, 700, 830),
    (1250, 700, 830), (1270, 700, 830),
]
COAT_TAIL = [
    (1235, 695, 840), (1260, 686, 848), (1290, 688, 850), (1320, 698, 848),
    (1350, 706, 842), (1380, 708, 838), (1410, 710, 830), (1440, 700, 800),
    (1455, 680, 760), (1465, 650, 720),
]
SPIKY_MASS = [
    (985, 772, 795), (1000, 770, 803), (1015, 768, 802), (1030, 764, 800),
    (1045, 752, 798), (1060, 748, 794), (1075, 746, 788), (1090, 744, 782),
    (1105, 742, 778), (1120, 740, 772), (1135, 738, 768),
]
SHORTS = [(1150, 410, 580), (1200, 410, 580), (1240, 420, 575)]
THIGH_RIGHT = [(1190, 520, 580), (1230, 520, 585), (1265, 525, 580)]
THIGH_LEFT = [(1220, 395, 560), (1300, 400, 540), (1380, 410, 530)]
GARTER = [(1195, 495, 565), (1262, 495, 565)]
SOCKS = [(1290, 375, 545), (1360, 380, 540), (1400, 385, 535)]
SHOES = [(1385, 375, 555), (1440, 380, 545), (1468, 385, 540)]
LEFT_SKIRT = [(1150, 340, 420), (1250, 340, 430), (1350, 350, 440)]

# ---- remove_cane: hand-traced along the real contours --------------------

GOLD_BALL = [
    (884, 762, 784), (890, 757, 789), (898, 753, 792), (908, 752, 793),
    (918, 755, 791), (925, 759, 789), (932, 763, 788), (938, 766, 782),
]
DOME = [
    (933, 749, 792), (938, 742, 797), (945, 736, 801), (952, 730, 804),
    (960, 726, 806), (968, 723, 808), (976, 721, 809), (984, 721, 809),
    (992, 722, 808), (998, 724, 806), (1004, 727, 801), (1010, 731, 794),
    (1016, 735, 783),
]
STICK = [
    (1008, 727, 768), (1016, 735, 778), (1025, 737, 757), (1035, 731, 751),
    (1045, 728, 746), (1055, 718, 745), (1065, 716, 745), (1075, 703, 742),
    (1085, 698, 748), (1095, 696, 750), (1105, 693, 747), (1115, 687, 742),
    (1125, 700, 737), (1135, 672, 715), (1142, 650, 702),
]
CROSSGUARD_WINGS = [
    (1145, 640, 700), (1160, 638, 706), (1175, 640, 706), (1190, 644, 702),
    (1205, 648, 700), (1220, 646, 700), (1235, 642, 700), (1250, 644, 702),
    (1265, 648, 700), (1275, 650, 694),
]
BLADE = [
    (1085, 682, 716), (1095, 668, 712), (1105, 666, 708), (1115, 666, 706),
    (1125, 662, 704), (1135, 652, 702), (1145, 646, 700), (1155, 650, 700),
    (1165, 652, 702), (1175, 650, 700), (1185, 646, 698), (1195, 642, 696),
    (1205, 638, 692), (1215, 636, 688), (1225, 638, 684), (1235, 642, 682),
    (1245, 646, 681), (1255, 647, 680), (1265, 645, 676), (1275, 642, 668),
    (1285, 640, 663), (1295, 639, 660), (1300, 638, 658),
]
BLADE_LOWER = [
    (1300, 641, 661), (1330, 631, 647), (1360, 621, 637), (1377, 613, 638),
]
SPEARHEAD = [
    (1376, 612, 638), (1386, 594, 626), (1394, 592, 623), (1402, 591, 624),
    (1410, 591, 623), (1418, 591, 620), (1426, 592, 618), (1434, 593, 618),
    (1442, 593, 618), (1448, 593, 614), (1454, 593, 601), (1459, 594, 597),
]
RIBBON_MAIN = [
    (1140, 700, 745), (1148, 698, 760), (1156, 694, 782), (1164, 692, 796),
    (1172, 692, 806), (1180, 694, 816), (1190, 697, 824), (1200, 700, 829),
    (1210, 703, 834), (1220, 706, 839), (1230, 710, 841), (1240, 715, 841),
    (1250, 720, 839), (1260, 726, 837), (1270, 732, 835), (1280, 738, 831),
    (1290, 745, 827), (1300, 752, 821), (1310, 760, 811), (1320, 770, 796),
    (1330, 780, 776),
]
RIBBON_LEFT_TAIL = [
    (1186, 588, 618), (1195, 575, 612), (1205, 565, 616), (1215, 560, 617),
    (1225, 558, 615), (1235, 563, 611), (1245, 568, 606), (1252, 570, 600),
]

# ---- remove_chair: hand-traced along the real contours -------------------

SEAT = [
    (1218, 623, 646), (1224, 616, 652), (1230, 610, 656), (1236, 590, 657),
    (1242, 525, 657), (1248, 500, 658), (1254, 498, 656), (1260, 497, 654),
    (1266, 497, 648), (1272, 499, 638), (1278, 510, 632), (1284, 545, 624),
    (1288, 570, 618),
]
LEG_LEFT = [
    (1278, 575, 611), (1290, 579, 611), (1300, 580, 612), (1310, 581, 612),
    (1320, 583, 613), (1330, 584, 613), (1340, 585, 613), (1350, 586, 614),
    (1360, 587, 614), (1370, 589, 614), (1380, 590, 615), (1390, 591, 613),
    (1400, 592, 606), (1410, 593, 601), (1420, 594, 599), (1424, 594, 598),
    (1428, 595, 597),
]
LEG_RIGHT = [
    (1258, 671, 683), (1268, 660, 687), (1278, 656, 688), (1290, 660, 689),
    (1300, 660, 689), (1310, 661, 690), (1320, 662, 691), (1330, 664, 691),
    (1340, 666, 692), (1350, 666, 693), (1360, 668, 694), (1370, 670, 695),
    (1380, 672, 696), (1390, 674, 697), (1400, 674, 698), (1410, 675, 698),
    (1420, 674, 698), (1424, 673, 697),
]

PROTECT_PARTS = [
    (L_HAIR, 'hair_main', HAIR),
    (L_QUILL, 'quill', QUILL),
    (L_QUILL, 'paper', PAPER),
    (L_GLOVE, 'glove_hand', GLOVE),
    (L_COSTUME, 'torso', TORSO),
    (L_COSTUME, 'neck_collar', NECK),
    (L_COSTUME, 'belt_hip', BELT_HIP),
    (L_COSTUME, 'coat_tail', COAT_TAIL),
    (L_COSTUME, 'spiky_mass', SPIKY_MASS),
    (L_COSTUME, 'shorts', SHORTS),
    (L_COSTUME, 'thigh_right', THIGH_RIGHT),
    (L_COSTUME, 'thigh_left', THIGH_LEFT),
    (L_COSTUME, 'garter', GARTER),
    (L_COSTUME, 'socks', SOCKS),
    (L_COSTUME, 'shoes', SHOES),
    (L_COSTUME, 'left_skirt', LEFT_SKIRT),
]
REMOVE_PARTS = [
    (L_CANE, 'cane_gold_ball', GOLD_BALL),
    (L_CANE, 'cane_dome', DOME),
    (L_CANE, 'cane_stick', STICK),
    (L_CANE, 'cane_guard_lower', CROSSGUARD_WINGS),
    (L_CANE, 'cane_blade', BLADE),
    (L_CANE, 'cane_blade_lower', BLADE_LOWER),
    (L_CANE, 'cane_spearhead', SPEARHEAD),
    (L_CANE, 'cane_ribbon_main', RIBBON_MAIN),
    (L_CANE, 'cane_ribbon_left_tail', RIBBON_LEFT_TAIL),
    (L_CHAIR, 'chair_seat', SEAT),
    (L_CHAIR, 'chair_leg_left', LEG_LEFT),
    (L_CHAIR, 'chair_leg_right', LEG_RIGHT),
]


def rows_to_runs(rows):
    """Expand hand-placed control rows into per-row runs (linear interp)."""
    rows = sorted(rows)
    out = {}
    for (y0, a0, b0), (y1, a1, b1) in zip(rows, rows[1:]):
        span = y1 - y0
        for y in range(y0, y1):
            t = (y - y0) / span
            out[y] = (round(a0 + (a1 - a0) * t), round(b0 + (b1 - b0) * t))
    y_last = rows[-1][0]
    out[y_last] = (rows[-1][1], rows[-1][2])
    return out


def merge_runs(run_list):
    """Union same-row runs; returns sorted merged list of (x0, x1)."""
    if not run_list:
        return []
    run_list = sorted(run_list)
    merged = [list(run_list[0])]
    for a, b in run_list[1:]:
        if a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [tuple(r) for r in merged]


def main():
    master = np.array(Image.open(MASTERS / MASTER_FILE).convert('RGBA'))
    h, w = master.shape[:2]
    visible = master[..., 3] > ALPHA_THRESHOLD

    # paint order: protect parts -> explicit other-character catch-all ->
    # cane parts -> chair parts (removals win every overlap)
    ownership = np.zeros((h, w), np.uint8)

    per_label_runs = {lb: {} for lb in range(1, 8)}
    for lb, name, rows in PROTECT_PARTS:
        for y, (a, b) in rows_to_runs(rows).items():
            per_label_runs[lb].setdefault(y, []).append((a, b))
    for lb, name, rows in REMOVE_PARTS:
        for y, (a, b) in rows_to_runs(rows).items():
            per_label_runs[lb].setdefault(y, []).append((a, b))

    # explicit catch-all: remaining visible pixels -> protected_other_character
    claimed = np.zeros((h, w), bool)
    for lb in (L_HAIR, L_QUILL, L_GLOVE, L_COSTUME,
               L_CANE, L_CHAIR):
        for y, runs in per_label_runs[lb].items():
            for a, b in runs:
                claimed[y, a:b + 1] = True
    other_px = visible & ~claimed
    lab_other = np.zeros((h, w), np.uint8)
    lab_other[other_px] = L_OTHER
    for y in range(h):
        xs = np.where(lab_other[y])[0]
        if xs.size:
            splits = np.where(np.diff(xs) > 1)[0]
            starts = np.concatenate(([0], splits + 1))
            ends = np.concatenate((splits, [xs.size - 1]))
            per_label_runs[L_OTHER].setdefault(y, [])
            for s, e in zip(starts, ends):
                per_label_runs[L_OTHER][y].append((int(xs[s]), int(xs[e])))

    for lb in range(1, 8):
        for y, runs in per_label_runs[lb].items():
            for a, b in merge_runs(runs):
                ownership[y, a:b + 1] = lb
    ownership[~visible] = 0

    # ---- sanity ----------------------------------------------------------
    bad_visible = int((visible & (ownership == 0)).sum())
    bad_bg = int((~visible & (ownership != 0)).sum())
    cane_chair_overlap = int(((ownership == L_CANE)
                              & (ownership == L_CHAIR)).sum())
    print(f'visible={int(visible.sum())} unlabeled_visible={bad_visible} '
          f'labeled_background={bad_bg} cane_chair_overlap={cane_chair_overlap}')
    assert bad_visible == 0 and bad_bg == 0

    # ---- write the static annotation source ------------------------------
    # rows are serialised FROM the final ownership array, so the JSON is
    # non-overlapping by construction and always identical to the census.
    OUTDIR.mkdir(parents=True, exist_ok=True)
    rows_json = []
    for y in range(h):
        entries = []
        for lb in range(1, 8):
            xs = np.where(ownership[y] == lb)[0]
            if xs.size == 0:
                continue
            splits = np.where(np.diff(xs) > 1)[0]
            starts = np.concatenate(([0], splits + 1))
            ends = np.concatenate((splits, [xs.size - 1]))
            for s, e in zip(starts, ends):
                entries.append([int(xs[s]), int(xs[e]), int(lb)])
        if entries:
            entries.sort()
            rows_json.append([int(y), *entries])
    doc = {
        'format': 'night03-ownership-scanline-rle-v1',
        'asset': 'a16',
        'canvas': {'w': int(w), 'h': int(h)},
        'alpha_threshold': ALPHA_THRESHOLD,
        'labels': LABELS,
        'annotation': {
            'author': 'Builder (GLM/ZCode) manual visual scanline '
                      'annotation from zoomed grid crops + pixel probes',
            'reviewer': 'ChatGPT Codex (sole Reviewer)',
            'note': 'label 0 reserved for transparent background; every '
                    'alpha>8 pixel carries an explicit semantic label; '
                    'remove_cane includes the ribbon tied to the blade',
        },
        'rows': rows_json,
    }
    jp = OUTDIR / 'a16_ownership_annotation.json'
    jp.write_text(json.dumps(doc, ensure_ascii=True, sort_keys=False),
                  encoding='utf-8', newline='\n')
    print(f'wrote {jp} rows={len(rows_json)} '
          f'{jp.stat().st_size} bytes')

    census = {LABELS[lb]['name']: int((ownership == lb).sum())
              for lb in range(8)}
    print(json.dumps(census, indent=1))

    # ---- dev previews (NOT part of the deliverable) -----------------------
    DEVDIR.mkdir(parents=True, exist_ok=True)
    colours = {0: (0, 0, 0), 1: (30, 80, 255), 2: (120, 200, 120),
               3: (255, 160, 60), 4: (230, 0, 230), 5: (255, 40, 40),
               6: (160, 90, 40), 7: (0, 200, 200)}
    ov = np.zeros((h, w, 3), np.uint8)
    for lb in range(8):
        ov[ownership == lb] = colours[lb]
    af = master[..., 3:4].astype(np.float32) / 255.0
    blend = (ov.astype(np.float32) * 0.55 * af
             + master[..., :3].astype(np.float32) * 0.45 * af
             + 255.0 * (1 - af)).clip(0, 255).astype(np.uint8)
    Image.fromarray(blend).save(DEVDIR / 'iter_overlay_full.png')
    for tag, kill in [('cane', ownership == L_CANE),
                      ('chair', ownership == L_CHAIR),
                      ('both', (ownership == L_CANE)
                       | (ownership == L_CHAIR))]:
        cut = master.copy()
        cut[..., 3][kill] = 0
        bg = np.full((h, w, 3), 255, np.uint8)
        a2 = cut[..., 3:4].astype(np.float32) / 255.0
        comp = (cut[..., :3].astype(np.float32) * a2
                + bg * (1 - a2)).clip(0, 255).astype(np.uint8)
        Image.fromarray(comp).save(DEVDIR / f'iter_{tag}_cutout.png')
    for name, (x0, y0, x1, y1, z) in {
            'head': (640, 880, 850, 1140, 3),
            'blade_seat': (540, 1130, 860, 1360, 2),
            'tip': (540, 1300, 760, 1470, 3)}.items():
        crop = blend[y0:y1, x0:x1]
        Image.fromarray(crop).resize(
            ((x1 - x0) * z, (y1 - y0) * z), Image.NEAREST).save(
            DEVDIR / f'iter_ov_{name}.png')
    print('dev previews written')


if __name__ == '__main__':
    main()
