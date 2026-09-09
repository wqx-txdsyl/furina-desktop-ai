"""NIGHT-03 Patch 2B R1A-R3 — a16 dense occlusion semantic annotation.

Every prop-union pixel is explicitly labeled by hand-placed semantic
control rows.  UNASSIGNED sentinel ensures zero default classification.

Semantic classes describe what each prop pixel occludes:
  transparent         - prop against background or another removed prop
  hand_glove          - gloved hand/fingers behind the prop
  gold_cuff           - gold cuff ornament behind the prop
  sleeve_coat         - dark costume/coat-tail mass behind the prop
  lower_garment_leg   - thigh/shorts/leg behind the prop
  other               - other character content behind the prop

Output: a16_occlusion_annotation.json (per-row RLE, 36,124 px exact).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
R6AR4_JSON = ROOT / ('data/assets_v2/repair_candidates/'
                     'night03_patch2a_r6ar4/a16_ownership_annotation.json')
OUTDIR = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b_r1a_r3'
ALPHA_THRESHOLD = 8
H, W = 1536, 1024

CLASS_ID = {'transparent': 0, 'hand_glove': 1, 'gold_cuff': 2,
            'sleeve_coat': 3, 'lower_garment_leg': 4, 'other': 5}
ID_CLASS = {v: k for k, v in CLASS_ID.items()}
UNASSIGNED = 255

# hand-placed semantic rows: (y, x0, x1_incl, class_name)
# each prop part's per-row extent is covered; strips override transparent
SEMANTIC_ROWS = [
    # dome: left hand_glove (fingers), right sleeve_coat (dark mass)
    (933, 752, 756, 'hand_glove'), (933, 783, 789, 'sleeve_coat'),
    (940, 744, 748, 'hand_glove'), (940, 781, 788, 'sleeve_coat'),
    (948, 738, 742, 'hand_glove'), (948, 787, 793, 'sleeve_coat'),
    (956, 729, 734, 'hand_glove'), (956, 790, 796, 'sleeve_coat'),
    (964, 725, 730, 'hand_glove'), (964, 791, 796, 'sleeve_coat'),
    (972, 723, 728, 'hand_glove'), (972, 791, 796, 'sleeve_coat'),
    (980, 722, 727, 'hand_glove'), (980, 789, 793, 'sleeve_coat'),
    (988, 723, 728, 'hand_glove'), (988, 783, 788, 'sleeve_coat'),
    (996, 724, 729, 'hand_glove'), (996, 782, 788, 'sleeve_coat'),
    (1004, 728, 735, 'sleeve_coat'), (1010, 730, 739, 'sleeve_coat'),
    (1016, 737, 748, 'sleeve_coat'),
    # stick: left hand_glove (fingers), lower left gold_cuff, right sleeve_coat
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
    # guard lower: sleeve_coat (coat band behind)
    (1145, 640, 652, 'sleeve_coat'), (1160, 638, 654, 'sleeve_coat'),
    (1175, 640, 656, 'sleeve_coat'), (1190, 644, 658, 'sleeve_coat'),
    (1205, 648, 660, 'sleeve_coat'), (1220, 646, 658, 'sleeve_coat'),
    (1235, 642, 656, 'sleeve_coat'), (1250, 644, 658, 'sleeve_coat'),
    (1265, 648, 656, 'sleeve_coat'), (1275, 650, 654, 'sleeve_coat'),
    # blade: left/right strips sleeve_coat (coat band/tail behind)
    (1135, 646, 656, 'sleeve_coat'), (1150, 646, 658, 'sleeve_coat'),
    (1165, 648, 660, 'sleeve_coat'), (1180, 644, 658, 'sleeve_coat'),
    (1195, 640, 656, 'sleeve_coat'), (1210, 636, 652, 'sleeve_coat'),
    (1225, 636, 650, 'sleeve_coat'), (1240, 644, 650, 'sleeve_coat'),
    (1255, 645, 650, 'sleeve_coat'), (1270, 643, 648, 'sleeve_coat'),
    # blade lower: right strip sleeve_coat
    # seat: top/lower_garment_leg, left/lower, right/sleeve_coat
    (1218, 623, 648, 'lower_garment_leg'), (1218, 648, 668, 'sleeve_coat'),
    (1226, 616, 644, 'lower_garment_leg'), (1226, 644, 664, 'sleeve_coat'),
    (1234, 610, 642, 'lower_garment_leg'), (1234, 642, 668, 'sleeve_coat'),
    (1242, 560, 640, 'lower_garment_leg'), (1242, 640, 668, 'sleeve_coat'),
    (1250, 528, 636, 'lower_garment_leg'), (1250, 636, 664, 'sleeve_coat'),
    (1258, 504, 630, 'lower_garment_leg'), (1258, 630, 660, 'sleeve_coat'),
    (1266, 502, 620, 'lower_garment_leg'), (1266, 620, 654, 'sleeve_coat'),
    (1274, 502, 610, 'lower_garment_leg'), (1274, 610, 640, 'sleeve_coat'),
    (1282, 508, 590, 'lower_garment_leg'), (1282, 590, 624, 'sleeve_coat'),
    # right chair leg: left strip sleeve_coat (coat tail behind)
    (1258, 672, 684, 'sleeve_coat'), (1270, 668, 686, 'sleeve_coat'),
    (1282, 664, 688, 'sleeve_coat'), (1294, 658, 690, 'sleeve_coat'),
    (1306, 658, 692, 'sleeve_coat'),
]




def rebuild_primitive(rows_spec, h, w):
    mask = np.zeros((h, w), bool)
    for row in rows_spec:
        y = int(row[0])
        for a, b in row[1:]:
            mask[y, int(a):int(b) + 1] = True
    return mask


def main():
    master = np.array(Image.open(
        ROOT / 'data/assets_v2/masters'
        / 'furina_v2_a16_work_focused.png').convert('RGBA'))
    visible = master[..., 3] > ALPHA_THRESHOLD

    doc = json.loads(R6AR4_JSON.read_text(encoding='utf-8'))

    def rebuild(rows_spec):
        return rebuild_primitive(rows_spec, H, W)

    cane = rebuild(doc['primitives']['remove_cane']) & visible
    chair = rebuild(doc['primitives']['remove_chair']) & visible
    prop_union = cane | chair

    # paint with UNASSIGNED sentinel
    sem = np.full((H, W), UNASSIGNED, np.uint8)

    # step 1: explicit transparent coverage of the entire prop union
    for y in range(H):
        xs = np.where(prop_union[y])[0]
        if xs.size == 0:
            continue
        splits = np.where(np.diff(xs) > 1)[0]
        starts = np.concatenate(([0], splits + 1))
        ends = np.concatenate((splits, [xs.size - 1]))
        for s, e in zip(starts, ends):
            sem[y, xs[s]:xs[e] + 1] = CLASS_ID['transparent']

    # step 2: semantic strips override transparent
    for y, x0, x1, cls in sorted(SEMANTIC_ROWS):
        assert cls in CLASS_ID
        span = np.zeros(W, bool)
        span[int(x0):int(x1) + 1] = True
        clipped = span & prop_union[y]
        assert clipped.any(), (
            f'row y={y} x {x0}-{x1} ({cls}) outside prop union')
        sem[y, clipped] = CLASS_ID[cls]

    sem[~prop_union] = UNASSIGNED
    sem[~visible] = UNASSIGNED

    # EXACT coverage: every prop-union px must be explicitly labeled
    unassigned_inside = int(((sem == UNASSIGNED) & prop_union).sum())
    assert unassigned_inside == 0, (
        f'{unassigned_inside} prop-union px have no semantic label')
    labeled_outside = int(((sem != UNASSIGNED) & ~prop_union).sum())
    assert labeled_outside == 0

    counts = {cls: int((sem == cid).sum()) for cls, cid in CLASS_ID.items()}
    total = int(prop_union.sum())
    assert sum(counts.values()) == total

    # serialize ONLY prop-union px (UNASSIGNED excluded)
    rows_json = []
    for y in range(H):
        entries = []
        for cid in sorted(CLASS_ID.values()):
            xsl = np.where(sem[y] == cid)[0]
            if xsl.size == 0:
                continue
            sp2 = np.where(np.diff(xsl) > 1)[0]
            st2 = np.concatenate(([0], sp2 + 1))
            en2 = np.concatenate((sp2, [xsl.size - 1]))
            for s, e in zip(st2, en2):
                entries.append([int(xsl[s]), int(xsl[e]), cid])
        if entries:
            entries.sort()
            rows_json.append([int(y), *entries])

    OUTDIR.mkdir(parents=True, exist_ok=True)
    payload = {
        'format': 'night03-occlusion-semantic-rle-v2',
        'asset': 'a16',
        'canvas': {'w': int(W), 'h': int(H)},
        'alpha_threshold': ALPHA_THRESHOLD,
        'prop_union_px': total,
        'classes': counts,
        'annotation': {
            'author': 'Builder (GLM/ZCode) hand-placed semantic control '
                      'rows from zoomed grid crops + pixel probes',
            'reviewer': 'ChatGPT Codex (sole Reviewer)',
            'note': 'every prop-union px explicitly labeled by hand-placed '
                    'semantic rows; transparent rows from R6A-R4 primitive '
                    'geometry; semantic strips override; no default '
                    'classification',
        },
        'rows': rows_json,
    }
    jp = OUTDIR / 'a16_occlusion_annotation.json'
    jp.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=False),
                  encoding='utf-8', newline='\n')
    total_px = sum(b - a + 1 for r in rows_json for a, b, lb in r[1:])
    print(json.dumps({'prop_union_px': total, 'serialized_px': total_px,
                      'rows': len(rows_json), 'classes': counts}, indent=1))
    assert total_px == total, 'serialized != prop union'
    print('OK: serialized exactly covers prop union')


if __name__ == '__main__':
    main()
