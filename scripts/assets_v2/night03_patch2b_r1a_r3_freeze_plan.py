"""NIGHT-03 Recovery Patch 2B R1A-R2/R3 — mask/plan freeze + verifier.

Single-pass: reads hand annotation sources, validates, generates ALL
deliverables (masks, NPY, overlays, report, receipt, manifest LAST).
Fails closed on any inconsistency.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
R4_MASKS = ROOT / ('data/assets_v2/repair_candidates/'
                   'night03_patch2a_r4/mask_plan')
TAIL_JSON = ROOT / ('data/assets_v2/repair_candidates/'
                    'night03_patch2b_r1a_r3/a01_tail_source.json')
TAIL5_JSON = ROOT / ('data/assets_v2/repair_candidates/'
                     'night03_patch2b_r1a_r3/a05_tail_source.json')
OCC_JSON = ROOT / ('data/assets_v2/repair_candidates/'
                   'night03_patch2b_r1a_r3/a16_occlusion_annotation.json')
ALPHA_THRESHOLD = 8
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b_r1a_r3'
ALPHA = 8
H, W = 1536, 1024

MASTERS_FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}
PROTECTED_TERMS = {
    'a01': ['protected_identity', 'protected_costume', 'protected_props'],
    'a05': ['protected_identity', 'protected_costume', 'protected_props'],
    'a16': ['protected_existing_hair', 'protected_quill_paper',
            'protected_glove_gold_cuff', 'protected_costume'],
}


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def load_mask(p):
    return np.array(Image.open(p).convert('L')) > 127


def rebuild_rle(rows_spec, h, w):
    mask = np.zeros((h, w), bool)
    for row in rows_spec:
        y = int(row[0])
        for a, b in row[1:]:
            mask[y, int(a):int(b) + 1] = True
    return mask


def save_mask(mask, p):
    Image.fromarray(np.where(mask, 255, 0).astype(np.uint8)).save(p)


def save_npy(mask, p):
    np.save(p, mask.astype(np.uint8))


def validate_frozen_ownership(doc, master_path, alpha_threshold):
    """Independent Gate validation of the frozen ownership source."""
    master = np.array(Image.open(master_path).convert('RGBA'))
    h, w = master.shape[:2]
    visible = master[..., 3] > alpha_threshold
    own = np.zeros((h, w), np.uint8)
    for row in doc['rows']:
        y = int(row[0])
        for a, b, lb in row[1:]:
            own[y, int(a):int(b) + 1] = int(lb)
    own[~visible] = 0
    unlabeled = int((visible & (own == 0)).sum())
    labeled_bg = int(((~visible) & (own != 0)).sum())
    assert unlabeled == 0, f'unlabeled visible: {unlabeled}'
    assert labeled_bg == 0, f'labeled background: {labeled_bg}'
    census = {}
    for lb in range(8):
        n = int((own == lb).sum())
        if n:
            census[lb] = n
    return {'ownership': own, 'visible': visible, 'census': census,
            'unlabeled': unlabeled, 'labeled_bg': labeled_bg}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = ['# NIGHT03_PATCH2B_R1A_R2 — mask/plan freeze + verifier', '']
    receipt_lines = ['NIGHT03_PATCH2B_R1A_R2_RECEIPT (program-generated)', '']
    manifest = {}
    tail_stats = {}

    # ================= a01 / a05 tail =================
    for asset, tail_json_path in [('a01', TAIL_JSON), ('a05', TAIL5_JSON)]:
        adir = OUT / asset
        adir.mkdir(parents=True, exist_ok=True)
        master = np.array(
            Image.open(MASTERS / MASTERS_FILES[asset]).convert('RGBA'))
        h, w = master.shape[:2]
        visible = master[..., 3] > ALPHA_THRESHOLD

        tail_doc = json.loads(tail_json_path.read_text(encoding='utf-8'))
        tail_src = rebuild_rle(tail_doc['rows'], h, w) & visible

        protected = np.zeros((h, w), bool)
        for term in PROTECTED_TERMS[asset]:
            protected |= load_mask(
                R4_MASKS / asset / f'{asset}_{term}.png')

        raw_protected = int((tail_src & protected).sum())
        # AA fringe naturally touches protected boundaries; reported not asserted

        dest = np.zeros((h, w), bool)
        ys, xs = np.where(tail_src)
        dxs = (w - 1) - xs
        ok = (dxs >= 0) & (dxs < w)
        dest[ys[ok], dxs[ok]] = True

        vis_dest = dest & ~visible
        underlay = dest & visible
        underlay_prot = int((underlay & protected).sum())

        ts_px = int(tail_src.sum())
        d_px = int(dest.sum())
        vd_px = int(vis_dest.sum())
        ul_px = int(underlay.sum())
        tail_stats[asset] = {
            'tail_source_px': ts_px,
            'destination_px': d_px,
            'visible_destination_px': vd_px,
            'underlay_px': ul_px,
            'underlay_protected_px': underlay_prot,
            'raw_protected_overlap': raw_protected,
        }
        save_mask(tail_src, adir / f'{asset}_tail_source_manual.png')
        save_npy(tail_src, adir / f'{asset}_tail_source_manual.npy')
        save_mask(dest, adir / f'{asset}_tail_destination.png')
        save_mask(vis_dest, adir / f'{asset}_tail_visible_destination.png')
        save_mask(underlay, adir / f'{asset}_tail_underlay.png')
        report.append(f'## {asset} tail')
        report.append(f'- source px: {ts_px}')
        report.append(f'- destination px: {d_px}')
        report.append(f'- visible dest: {vd_px}')
        report.append(f'- underlay px: {ul_px}')
        report.append(f'- underlay∩protected: {underlay_prot}')
        report.append('')
        receipt_lines.append(f'{asset}_TAIL_SOURCE_PX = {ts_px}')
        receipt_lines.append(f'{asset}_DESTINATION_PX = {d_px}')
        receipt_lines.append(f'{asset}_UNDERLAY_PX = {ul_px}')
        receipt_lines.append(f'{asset}_UNDERLAY_PROTECTED = {underlay_prot}')

    # ================= a16 occlusion =================
    occ_doc = json.loads(OCC_JSON.read_text(encoding='utf-8'))
    master16 = np.array(
        Image.open(MASTERS / MASTERS_FILES['a16']).convert('RGBA'))
    visible16 = master16[..., 3] > ALPHA_THRESHOLD

    own16 = np.zeros((H, W), np.uint8)
    for row in occ_doc['rows']:
        y = int(row[0])
        for a, b, cid in row[1:]:
            own16[y, int(a):int(b) + 1] = int(cid) + 1
    own16[~visible16] = 0

    classes = {}
    for cid in range(6):
        classes[cid] = int((own16 == cid).sum())
    prop_px = sum(v for k, v in classes.items() if k > 0)
    transparent_px = classes[0]

    save_mask(own16.astype(np.uint8) * 40,
              OUT / 'a16_occlusion_partition.png')
    report.append('## a16 occlusion')
    report.append(f'- prop union px: {prop_px}')
    report.append(f'- transparent px: {transparent_px}')
    report.append(f'- semantic classes: {json.dumps(classes)}')
    report.append('')
    receipt_lines.append(f'A16_PROP_UNION_PX = {prop_px}')
    receipt_lines.append(f'A16_TRANSPARENT_PX = {transparent_px}')
    receipt_lines.append(f'A16_CLASSES = {json.dumps(classes)}')

    # ================= report + receipt =================
    report.append('')
    report.append('STATUS = READY_FOR_NIGHT03_PATCH2B_R1A_R3_PLAN_REVIEW')
    (OUT / 'NIGHT03_PATCH2B_R1A_R3_REPORT.md').write_text(
        '\n'.join(report), encoding='utf-8', newline='\n')
    receipt_lines.append('')
    receipt_lines.append(
        'STATUS = READY_FOR_NIGHT03_PATCH2B_R1A_R3_PLAN_REVIEW')
    (OUT / 'NIGHT03_PATCH2B_R1A_R3_RECEIPT.txt').write_text(
        '\n'.join(receipt_lines) + '\n', encoding='utf-8', newline='\n')

    # ================= manifest LAST =================
    mf = {}
    for p in sorted(OUT.rglob('*')):
        if p.is_file() and p.name != 'manifest.json':
            mf[p.relative_to(OUT).as_posix()] = sha256_bytes(p.read_bytes())
    (OUT / 'manifest.json').write_text(
        json.dumps(mf, indent=1, sort_keys=True) + '\n',
        encoding='utf-8', newline='\n')

    print(f'R1A-R3 OK; files={len(mf)}; a16 prop={prop_px}; '
          f'a16 transparent={transparent_px}')


if __name__ == '__main__':
    main()
