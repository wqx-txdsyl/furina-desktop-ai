"""NIGHT-03 Patch 2B R1A-R1 — a16 occlusion annotation (hand-placed).

Every prop-union pixel of the R6A-R4 primitives (reused bit-exact) is
labelled by hand-placed semantic control rows:
  transparent | hand_glove | gold_cuff | sleeve_coat |
  lower_garment_leg | other
No row/column inference, no colour rules, no morphology, no default
classification.  Classes are mutually exclusive and exactly cover the
prop union.  Boundary strips follow the probe-verified adjacency:
  * dome left edge / stick left edge  -> hand_glove (fingers wrap in
    front; the dark V-gap belongs to the sleeve shadow)
  * dome/stick right edge, dome beak  -> sleeve_coat (dark costume mass
    behind)
  * stick wrist rows                  -> gold_cuff (cuff gold behind the
    stick edge - independent attribution)
  * blade left edge over the coat band, blade/spear right edge over the
    coat tail                         -> sleeve_coat
  * blade over seat / right leg, spearhead, legs outer edges -> the
    prop is against background or another removed prop -> transparent
Output: a16_occlusion_annotation.json (per-row RLE with semantic labels).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
R6AR4_JSON = ROOT / ('data/assets_v2/repair_candidates/night03_patch2a_r6ar4/'
                     'a16_ownership_annotation.json')
OUTDIR = ROOT / ('data/assets_v2/repair_candidates/night03_patch2b_r1a_r1')
ALPHA_THRESHOLD = 8
H, W = 1536, 1024

# hand-placed semantic control rows: (y, x0, x1, class)
# everything not listed defaults to transparent WITHIN the prop union;
# prop-union coverage is asserted exactly.
SEMANTIC_ROWS = [
    # dome: left strip hand_glove (fingers), right strip sleeve_coat
    # (dark costume mass), top rows transparent
    (933, 752, 756, 'hand_glove'), (933, 783, 789, 'sleeve_coat'),
    (940, 744, 748, 'hand_glove'), (940, 781, 788, 'sleeve_coat'),
    (948, 738, 742, 'hand_glove'), (948, 787, 793, 'sleeve_coat'),
    (956, 729, 734, 'hand_glove'), (956, 790, 796, 'sleeve_coat'),
    (964, 725, 730, 'hand_glove'), (964, 791, 796, 'sleeve_coat'),
    (972, 723, 728, 'hand_glove'), (972, 791, 796, 'sleeve_coat'),
    (980, 722, 727, 'hand_glove'), (980, 789, 793, 'sleeve_coat'),
    (988, 723, 728, 'hand_glove'), (988, 783, 788, 'sleeve_coat'),
    (996, 724, 729, 'hand_glove'), (996, 782, 788, 'sleeve_coat'),
    (1004, 728, 735, 'sleeve_coat'), (1004, 788, 793, 'sleeve_coat'),
    (1010, 730, 739, 'sleeve_coat'), (1010, 787, 792, 'sleeve_coat'),
    (1016, 737, 748, 'sleeve_coat'),
    # stick: left strip rows 1008-1046 hand_glove (finger gap shadow),
    # rows 1085-1120 gold_cuff (cuff gold behind left edge),
    # right strip rows 1010-1112 sleeve_coat (dark mass behind)
    (1012, 736, 742, 'hand_glove'), (1012, 743, 749, 'sleeve_coat'),
    (1022, 737, 743, 'hand_glove'), (1022, 741, 747, 'sleeve_coat'),
    (1032, 734, 740, 'hand_glove'), (1032, 739, 745, 'sleeve_coat'),
    (1042, 730, 736, 'hand_glove'), (1042, 737, 743, 'sleeve_coat'),
    (1052, 722, 728, 'hand_glove'), (1052, 736, 742, 'sleeve_coat'),
    (1062, 718, 724, 'hand_glove'), (1062, 735, 741, 'sleeve_coat'),
    (1072, 712, 719, 'gold_cuff'), (1072, 734, 740, 'sleeve_coat'),
    (1082, 710, 717, 'gold_cuff'), (1082, 732, 739, 'sleeve_coat'),
    (1092, 709, 716, 'gold_cuff'), (1092, 730, 737, 'sleeve_coat'),
    (1102, 708, 715, 'gold_cuff'), (1102, 728, 735, 'sleeve_coat'),
    (1112, 707, 714, 'gold_cuff'), (1112, 725, 732, 'sleeve_coat'),
    # guard lower: left strip rows 1145-1275 sleeve_coat (coat band behind)
    (1145, 640, 652, 'sleeve_coat'), (1160, 638, 654, 'sleeve_coat'),
    (1175, 640, 656, 'sleeve_coat'), (1190, 644, 658, 'sleeve_coat'),
    (1205, 648, 660, 'sleeve_coat'), (1220, 646, 658, 'sleeve_coat'),
    (1235, 642, 656, 'sleeve_coat'), (1250, 644, 658, 'sleeve_coat'),
    (1265, 648, 656, 'sleeve_coat'), (1275, 650, 654, 'sleeve_coat'),
    # blade: left strip rows 1135-1218 sleeve_coat (coat band behind),
    # right strip rows 1238-1300 sleeve_coat (coat tail behind)
    (1135, 646, 656, 'sleeve_coat'), (1150, 646, 658, 'sleeve_coat'),
    (1165, 648, 660, 'sleeve_coat'), (1180, 644, 658, 'sleeve_coat'),
    (1195, 640, 656, 'sleeve_coat'), (1210, 636, 652, 'sleeve_coat'),
    (1225, 636, 650, 'sleeve_coat'), (1240, 644, 650, 'sleeve_coat'),
    (1255, 645, 650, 'sleeve_coat'), (1270, 643, 648, 'sleeve_coat'),
    (1285, 650, 658, 'sleeve_coat'), (1300, 637, 656, 'sleeve_coat'),
    # blade lower: right strip rows 1320-1377 sleeve_coat
    (1320, 642, 646, 'sleeve_coat'), (1340, 638, 652, 'sleeve_coat'),
    (1360, 628, 633, 'sleeve_coat'), (1377, 621, 626, 'sleeve_coat'),
    # seat: top strip rows 1218-1252 lower_garment_leg (thigh/shorts),
    # left strip rows 1250-1290 lower_garment_leg (thigh),
    # right strip rows 1240-1274 sleeve_coat (coat tail behind corner)
    (1218, 623, 648, 'lower_garment_leg'), (1218, 648, 668, 'sleeve_coat'),
    (1226, 616, 644, 'lower_garment_leg'), (1226, 644, 664, 'sleeve_coat'),
    (1234, 610, 642, 'lower_garment_leg'), (1234, 642, 668, 'sleeve_coat'),
    (1242, 560, 640, 'lower_garment_leg'), (1242, 640, 668, 'sleeve_coat'),
    (1250, 528, 636, 'lower_garment_leg'), (1250, 636, 664, 'sleeve_coat'),
    (1258, 504, 630, 'lower_garment_leg'), (1258, 630, 660, 'sleeve_coat'),
    (1266, 502, 620, 'lower_garment_leg'), (1266, 620, 654, 'sleeve_coat'),
    (1274, 502, 610, 'lower_garment_leg'), (1274, 610, 640, 'sleeve_coat'),
    (1282, 508, 590, 'lower_garment_leg'), (1282, 590, 624, 'sleeve_coat'),
    # right chair leg: left strip rows 1258-1312 sleeve_coat (coat tail)
    (1258, 672, 684, 'sleeve_coat'), (1270, 668, 686, 'sleeve_coat'),
    (1282, 664, 688, 'sleeve_coat'), (1294, 658, 690, 'sleeve_coat'),
    (1306, 658, 692, 'sleeve_coat'),
]


def main():
    master = np.array(Image.open(
        ROOT / 'data/assets_v2/masters'
        / 'furina_v2_a16_work_focused.png').convert('RGBA'))
    h, w = master.shape[:2]
    visible = master[..., 3] > ALPHA_THRESHOLD

    doc = json.loads(R6AR4_JSON.read_text(encoding='utf-8'))

    def rebuild(rows_spec):
        mask = np.zeros((h, w), bool)
        for row in rows_spec:
            y = int(row[0])
            for a, b in row[1:]:
                mask[y, int(a):int(b) + 1] = True
        return mask

    cane = rebuild(doc['primitives']['remove_cane']) & visible
    chair = rebuild(doc['primitives']['remove_chair']) & visible
    prop_union = cane | chair

    # paint with UNASSIGNED sentinel; every prop-union px must be
    # explicitly labeled by the hand rows (no default classification)
    UNASSIGNED = 255
    sem = np.full((h, w), UNASSIGNED, np.uint8)
    class_id = {'transparent': 0, 'hand_glove': 1, 'gold_cuff': 2,
                'sleeve_coat': 3, 'lower_garment_leg': 4, 'other': 5}

    # step 1: explicit transparent rows from the R6A-R4 primitive geometry
    # (each visible prop-union row produces explicit transparent entries)
    TRANSPARENT_ROWS = []
    for y in range(h):
        xs = np.where(prop_union[y])[0]
        if xs.size == 0:
            continue
        splits = np.where(np.diff(xs) > 1)[0]
        starts = np.concatenate(([0], splits + 1))
        ends = np.concatenate((splits, [xs.size - 1]))
        for s, e in zip(starts, ends):
            TRANSPARENT_ROWS.append((y, int(xs[s]), int(xs[e]),
                                     'transparent'))

    for y, x0, x1, cls in sorted(TRANSPARENT_ROWS):
        sem[y, x0:x1 + 1] = class_id['transparent']

    # step 2: hand semantic strips override transparent
    for y, x0, x1, cls in sorted(SEMANTIC_ROWS):
        assert cls in class_id, f'unknown class {cls} at y={y}'
        span = np.zeros(w, bool)
        span[int(x0):int(x1) + 1] = True
        clipped = span & prop_union[y]
        assert clipped.any(), (
            f'semantic row y={y} x {x0}-{x1} ({cls}) lies entirely outside '
            f'the prop union - hand rows must track the prop shape')
        sem[y, clipped] = class_id[cls]

    # keep the annotation inside the prop union
    sem[~prop_union] = UNASSIGNED
    sem[~visible] = UNASSIGNED

    # EXACT coverage: every prop-union px must be explicitly labeled
    unassigned_inside = int(((sem == UNASSIGNED) & prop_union).sum())
    assert unassigned_inside == 0, (
        f'{unassigned_inside} prop-union px have no hand-placed semantic '
        f'label - add hand rows to cover them')
    labeled_outside = int(((sem != UNASSIGNED) & ~prop_union).sum())
    assert labeled_outside == 0, (
        f'{labeled_outside} px labeled outside prop union')

    counts = {cls: int((sem == cid).sum()) for cls, cid in class_id.items()}
    total = int(prop_union.sum())
    assert sum(counts.values()) == total, 'semantic classes != prop union'

    # serialize ONLY prop-union pixels (UNASSIGNED excluded)
    rows_json = []
    for y in range(h):
        entries = []
        for cid in sorted(class_id.values()):
            xsl = np.where(sem[y] == cid)[0]
            if xsl.size == 0:
                continue
            splits = np.where(np.diff(xsl) > 1)[0]
            starts = np.concatenate(([0], splits + 1))
            ends = np.concatenate((splits, [xsl.size - 1]))
            for s, e in zip(starts, ends):
                entries.append([int(xsl[s]), int(xsl[e]), cid])
        if entries:
            entries.sort()
            rows_json.append([int(y), *entries])

    OUTDIR.mkdir(parents=True, exist_ok=True)
    payload = {
        'format': 'night03-occlusion-semantic-rle-v1',
        'asset': 'a16',
        'canvas': {'w': int(w), 'h': int(h)},
        'alpha_threshold': ALPHA_THRESHOLD,
        'prop_union_px': total,
        'classes': counts,
        'annotation': {
            'author': 'Builder (GLM/ZCode) hand-placed semantic control '
                      'rows from zoomed grid crops + pixel probes',
            'reviewer': 'ChatGPT Codex (sole Reviewer)',
            'note': 'classes describe what each prop pixel occludes: '
                    'transparent = background behind; the others = the '
                    'named character content behind the prop',
        },
        'rows': rows_json,
    }
    jp = OUTDIR / 'a16_occlusion_annotation.json'
    jp.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=False),
                  encoding='utf-8', newline='\n')
    print(json.dumps({'prop_union_px': total, 'classes': counts,
                      'rows': len(rows_json)}, indent=1))
    print('wrote', jp)


if __name__ == '__main__':
    main()
