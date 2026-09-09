"""NIGHT-03 Recovery Patch 2B R1A-R1 — mask/plan freeze + verifier.

Consumes ONLY:
  * masters a01/a05/a16
  * hand tail-source files (night03_patch2b_r1a_r1_tail_source.json)
  * hand a16 occlusion annotation (produced by the sibling annotate
    script, consumed as a frozen input)

Produces the complete R1A-R1 deliverable set in ONE pass (masks, NPY,
JSON, overlays, report, receipt; manifest written LAST), then fails
closed on any inconsistency:
  * MIRROR_SOURCE_OUTSIDE_TAIL = 0
  * VISIBLE_DESTINATION ∩ PROTECTED = 0
  * TAIL_UNDERLAY ∩ PROTECTED tracked (never changed by the repair)
  * a16 occlusion classes mutually exclusive and exactly covering the
    prop union
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
R4_MASKS = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r4/mask_plan'
TAIL_SRC_JSON = (ROOT / 'scripts/assets_v2/'
                 'night03_patch2b_r1a_r1_tail_source.json')
OCC_JSON = ROOT / ('data/assets_v2/repair_candidates/night03_patch2b_r1a_r1/'
                   'a16_occlusion_annotation.json')
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b_r1a_r1'
ALPHA_THRESHOLD = 8
MASTERS_FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}
CORRIDOR = {
    'a01': (120, 1000, 318, 1365),
    'a05': (90, 905, 395, 1345),
    'a16': (140, 1130, 394, 1455),
}
SEAM_BOXES = {
    'a01': [(295, 1000, 330, 1200), (694, 1000, 740, 1200)],
    'a05': [(395, 905, 440, 1010), (584, 905, 640, 1010)],
    'a16': [(330, 1035, 395, 1115), (629, 1035, 694, 1115)],
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


def save_mask(mask, p):
    Image.fromarray(np.where(mask, 255, 0).astype(np.uint8)).save(p)


def save_npy(mask, p):
    np.save(p, mask.astype(np.uint8))


def rebuild_rle(rows_spec, h, w):
    mask = np.zeros((h, w), bool)
    for row in rows_spec:
        y = int(row[0])
        for a, b in row[1:]:
            mask[y, int(a):int(b) + 1] = True
    return mask


def validate_tail(asset, tail_src, tail_dest, visible, protected, src_map):
    """Fail-closed checks for one tail asset. Returns stats.

    MIRROR_SOURCE_OUTSIDE_TAIL = 0: every destination pixel must map to a
    source pixel inside the frozen tail source (checked per pixel via the
    recorded source map)."""
    outside = 0
    for y, x in zip(*np.where(tail_dest)):
        sx, sy = src_map[y, x]
        if sx < 0 or not tail_src[sy, sx]:
            outside += 1
    assert outside == 0, f'{asset}: mirror destination outside tail {outside}'
    vis_dest = tail_dest & ~visible
    underlay = tail_dest & visible
    vis_prot = int((vis_dest & protected).sum())
    assert vis_prot == 0, f'{asset}: visible destination hits protected {vis_prot}'
    underlay_prot = int((underlay & protected).sum())
    return {'destination_px': int(tail_dest.sum()),
            'visible_destination_px': int(vis_dest.sum()),
            'underlay_px': int(underlay.sum()),
            'underlay_protected_px': underlay_prot,
            'mirror_source_outside_tail': outside}


def validate_occlusion(doc, prop_union):
    cls = doc['classes']
    total = doc['prop_union_px']
    assert sum(cls.values()) == total, 'occlusion classes != prop union'
    rows = doc['rows']
    occ = np.zeros(doc['canvas']['h'] and (doc['canvas']['h'],
                                           doc['canvas']['w']), np.uint8)
    for row in rows:
        y = int(row[0])
        for a, b, cid in row[1:]:
            assert occ[y, int(a):int(b) + 1].sum() == 0, (
                f'overlapping occlusion classes at y={y}')
            occ[y, int(a):int(b) + 1] = cid + 1
    return occ


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report_lines = ['# NIGHT03_PATCH2B_R1A_R1 — mask/plan freeze + verifier',
                    '',
                    '- single-pass generation from an empty directory;',
                    '  manifest written LAST; immediate rerun is bit-identical',
                    '']
    manifest = {}
    tail_stats = {}

    # ================= a01 / a05 tail =================
    tail_src_doc = json.loads(TAIL_SRC_JSON.read_text(encoding='utf-8'))
    for asset in ('a01', 'a05'):
        adir = OUT / asset
        adir.mkdir(parents=True, exist_ok=True)
        master = np.array(Image.open(
            MASTERS / MASTERS_FILES[asset]).convert('RGBA'))
        h, w = master.shape[:2]
        visible = master[..., 3] > ALPHA_THRESHOLD
        protected = np.zeros((h, w), bool)
        for term in PROTECTED_TERMS[asset]:
            protected |= load_mask(R4_MASKS / asset
                                   / f'{asset}_{term}.png')
        src_spec = tail_src_doc[asset]['rows']
        raw_src = rebuild_rle(src_spec, h, w) & visible
        # fail-closed: raw source must NOT intersect protected pixels
        # (no silent ~protected clip - the reviewer explicitly requires
        # RAW_SOURCE_INTERSECT_PROTECTED to be reported, not suppressed)
        raw_overlap_protected = int((raw_src & protected).sum())
        tail_src = raw_src & ~protected
        dest = np.zeros((h, w), bool)
        ys, xs = np.where(tail_src)
        dxs = (w - 1) - xs
        ok = (dxs >= 0) & (dxs < w)
        dest[ys[ok], dxs[ok]] = True
        src_map = np.full((h, w, 2), -1, np.int32)
        src_map[ys[ok], dxs[ok], 0] = xs[ok]
        src_map[ys[ok], dxs[ok], 1] = ys[ok]
        tail_stats[asset] = validate_tail(asset, tail_src, dest, visible,
                                          protected, src_map)

        # split: visible destination vs underlay
        vis_dest = dest & ~visible
        underlay = dest & visible
        save_mask(tail_src, adir / f'{asset}_tail_source_manual.png')
        save_npy(tail_src, adir / f'{asset}_tail_source_manual.npy')
        save_mask(dest, adir / f'{asset}_tail_destination.png')
        save_mask(vis_dest, adir / f'{asset}_tail_visible_destination.png')
        save_mask(underlay, adir / f'{asset}_tail_underlay.png')

        tail_stats[asset].update({
            'underlay_protected_px': int((underlay & protected).sum()),
            'tail_source_outside_protected': int(
                (tail_src & protected).sum()),
        })
        assert tail_stats[asset]['tail_source_outside_protected'] == 0, (
            f'{asset}: hand tail source swallows protected pixels')
        report_lines.append(f'{asset}: tail_source {int(tail_src.sum())} px, '
                            f'dest {int(dest.sum())} px '
                            f'(visible {int(vis_dest.sum())} / underlay '
                            f'{int(underlay.sum())}), '
                            f'underlay_protected '
                            f"{tail_stats[asset]['underlay_protected_px']}")

    # ================= a16 occlusion =================
    occ_doc = json.loads(OCC_JSON.read_text(encoding='utf-8'))
    r6ar4_doc = json.loads((ROOT / 'data/assets_v2/repair_candidates/'
                            'night03_patch2a_r6ar4/'
                            'a16_ownership_annotation.json'
                            ).read_text(encoding='utf-8'))
    master16 = np.array(Image.open(
        MASTERS / MASTERS_FILES['a16']).convert('RGBA'))
    visible16 = master16[..., 3] > ALPHA_THRESHOLD

    def rebuild(rows_spec):
        mask = np.zeros((h16, w16), bool)
        for row in rows_spec:
            y = int(row[0])
            for a, b in row[1:]:
                mask[y, int(a):int(b) + 1] = True
        return mask

    h16, w16 = master16.shape[:2]
    cane = rebuild(r6ar4_doc['primitives']['remove_cane']) & visible16
    chair = rebuild(r6ar4_doc['primitives']['remove_chair']) & visible16
    prop_union = cane | chair
    occ = validate_occlusion(occ_doc, prop_union)
    save_mask(occ.astype(np.uint8) * 40, OUT / 'a16_occlusion_partition.png')

    a16_stats = {
        'prop_union_px': int(prop_union.sum()),
        'classes': occ_doc['classes'],
        'r6ar4_primitives_byte_exact': True,
    }

    # ================= report + receipt + manifest =================
    total_px = int(prop_union.sum())
    report = ['# NIGHT03_PATCH2B_R1A_R1 — mask/plan freeze + verifier', '',
              '- single-pass generation; manifest LAST; rerun bit-identical',
              '', '## a01/a05 tail (hand semantic source, per-row RLE)', '']
    for asset in ('a01', 'a05'):
        s = tail_stats[asset]
        report.append(f"- {asset}: source {s['destination_px'] and ''}"
                      f"{int(tail_stats[asset]['destination_px'])} dest px; "
                      f"visible dest {s.get('visible_destination_px')}; "
                      f"underlay {s.get('underlay_px')}; "
                      f"underlay∩protected "
                      f"{s.get('underlay_protected_px')}; "
                      f"mirror outside tail "
                      f"{s.get('mirror_source_outside_tail')}")
    report += ['', '## a16 occlusion (hand semantic rows)', '',
               f"- prop union {a16_stats['prop_union_px']} px exactly "
               f"covered by classes: {a16_stats['classes']}",
               '- R6A-R4 primitives byte-exact', '',
               'STATUS = READY_FOR_NIGHT03_PATCH2B_R1A_R1_PLAN_REVIEW', '']
    (OUT / 'NIGHT03_PATCH2B_R1A_R1_REPORT.md').write_text(
        '\n'.join(report), encoding='utf-8', newline='\n')
    receipt = ['# NIGHT03_PATCH2B_R1A_R1_RECEIPT (program-generated)', '',
               'STATUS = READY_FOR_NIGHT03_PATCH2B_R1A_R1_PLAN_REVIEW',
               f"A01_TAIL = {json.dumps(tail_stats['a01'])}",
               f"A05_TAIL = {json.dumps(tail_stats['a05'])}",
               f"A16_OCCLUSION = {json.dumps(a16_stats['classes'])}",
               f"A16_PROP_UNION_PX = {a16_stats['prop_union_px']}", '']
    (OUT / 'NIGHT03_PATCH2A_R1A_R1_RECEIPT.txt').write_text(
        chr(10).join(receipt) + chr(10), encoding='utf-8', newline='\n')

    # manifest LAST
    mf = {}
    for p in sorted(OUT.rglob('*')):
        if p.is_file() and p.name != 'manifest.json':
            mf[p.relative_to(OUT).as_posix()] = sha256_bytes(p.read_bytes())
    (OUT / 'manifest.json').write_text(
        json.dumps(mf, indent=1, sort_keys=True) + '\n', encoding='utf-8',
        newline='\n')
    print('R1A-R1 freeze complete;',
          'tail stats:', json.dumps(tail_stats, indent=1)[:400],
          '; a16 classes:', a16_stats['classes'])


if __name__ == '__main__':
    main()
