"""NIGHT-03 Patch 2B R1A-R4 — INDEPENDENT plan verifier.

Shares no code with night03_patch2b_r1a_r4_freeze_plan.py.  Re-derives
every deliverable from the static sources + frozen authorities and
cross-checks the committed output tree, report, receipt and manifest.
Read-only: writes nothing.  Exit 0 only if every check passes.

Pinned authority SHA256s make tampering with the R6A-R4 primitives /
ledger, the R4 protected masks or the masters detectable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ALPHA = 8
H, W = 1536, 1024
CLASSES = ['transparent', 'hand_glove', 'gold_cuff', 'sleeve_coat',
           'lower_garment_leg', 'other']
A16_PROP_UNION_PX = 36124
MASTERS_FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}
PROTECTED_TERMS = {
    'a01': ['protected_identity', 'protected_costume', 'protected_props'],
    'a05': ['protected_identity', 'protected_costume', 'protected_props'],
}
STATUS_EXPECTED = 'READY_FOR_NIGHT03_PATCH2B_R1A_R4_PLAN_REVIEW'

PINNED_SHA256 = {
    'r6ar4_annotation': (
        '95e6d150d3d507569dd2749ea00de8754a0a9f76d5525b35998d66cb594fc0f9'),
    'protected_a01_protected_identity': (
        'cab00defd7842e65c846c2ba247862d81e0fa53aabe8ff0ca4237afdbd99c4c1'),
    'protected_a01_protected_costume': (
        '627cce49b0b3cd08ae60778bf06590eaf39800ff62892bf8bed99d850bf98640'),
    'protected_a01_protected_props': (
        'fd1cf738337878cc86398e5db87e00059e50ec4ae700554922584d5edaa42cf1'),
    'protected_a05_protected_identity': (
        '1b6848732b6a792738141d98c1f110d92db317978d4594e737254c88a7d91b6c'),
    'protected_a05_protected_costume': (
        'ef9c4a4b18045254d58d879bf08754a92d0747219e0faa39dc5f4b7b2c944d41'),
    'protected_a05_protected_props': (
        'b2d661b9c7823d305b40f24aa6000fdecbde6b202c2328f9da2bc5b5c99faf1d'),
    'master_a01': (
        'c3ed763c7eed3bfc620e4847e0028e5c6eae83a8170f41a1152915e7885172a6'),
    'master_a05': (
        '8ddcfde186fb352ce32381543273902295ceeb3fd3f3db6b064141fcf5199a77'),
    'master_a16': (
        'f4997917453d6a541a08d021132ecad3bd8cffb63773833d31bdcde805d099ab'),
}


class VerifyFail(Exception):
    pass


class Checker:
    def __init__(self):
        self.failures = []
        self.passes = 0

    def check(self, cond, label):
        if cond:
            self.passes += 1
        else:
            self.failures.append(label)
        return bool(cond)

    def result(self):
        return self.passes, self.failures


def sha256_path(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def runs_rebuild(rows_spec, h, w):
    m = np.zeros((h, w), bool)
    for row in rows_spec:
        y = int(row[0])
        for a, b in row[1:]:
            m[y, int(a):int(b) + 1] = True
    return m


def mirror(mask, w):
    out = np.zeros_like(mask)
    ys, xs = np.where(mask)
    out[ys, (w - 1) - xs] = True
    return out


def png_pixels(p):
    return np.array(Image.open(p).convert('L'))


def verify(sources, output, r6ar4_json, r4masks, masters):
    ck = Checker()

    # ---- authority pins -------------------------------------------
    if not ck.check(sha256_path(r6ar4_json) ==
                    PINNED_SHA256['r6ar4_annotation'],
                    'R6A-R4 annotation SHA256 pin (primitive/ledger intact)'):
        raise VerifyFail('R6A-R4 authority hash mismatch')
    for asset in ('a01', 'a05'):
        for term in PROTECTED_TERMS[asset]:
            pin = f'protected_{asset}_{term}'
            ck.check(sha256_path(r4masks / asset / f'{asset}_{term}.png') ==
                     PINNED_SHA256[pin], f'{pin} SHA256 pin')
    for asset in ('a01', 'a05', 'a16'):
        ck.check(sha256_path(masters / MASTERS_FILES[asset]) ==
                 PINNED_SHA256[f'master_{asset}'],
                 f'master_{asset} SHA256 pin')

    # ---- R6A-R4 prop union (independent rebuild) -------------------
    doc = json.loads(Path(r6ar4_json).read_text(encoding='utf-8'))
    m16 = np.array(Image.open(
        masters / MASTERS_FILES['a16']).convert('RGBA'))
    vis16 = m16[..., 3] > ALPHA
    cane = runs_rebuild(doc['primitives']['remove_cane'], H, W) & vis16
    chair = runs_rebuild(doc['primitives']['remove_chair'], H, W) & vis16
    union = cane | chair
    ck.check(int(union.sum()) == A16_PROP_UNION_PX,
             'prop union == 36124 px')

    # ---- a16 source validity (independent) --------------------------
    occ = json.loads((sources / 'a16_occlusion_annotation.json')
                     .read_text(encoding='utf-8'))
    ok_vocab = ck.check(occ.get('class_vocabulary') == CLASSES,
                        'a16 class vocabulary exact')
    sem = np.full((H, W), -1, np.int16)
    dup = unk = oob = 0
    for row in occ.get('rows', []):
        y = int(row[0])
        for a, b, cname in row[1:]:
            if cname not in CLASSES:
                unk += (b - a + 1)
                continue
            if not (0 <= int(a) <= int(b) < W) or not (0 <= y < H):
                oob += 1
                continue
            span = sem[y, int(a):int(b) + 1]
            dup += int((span != -1).sum())
            sem[y, int(a):int(b) + 1] = CLASSES.index(cname)
    ck.check(ok_vocab and unk == 0, f'a16 unknown_class_pixels == 0 (={unk})')
    ck.check(dup == 0, f'a16 duplicate_pixels == 0 (={dup})')
    ck.check(oob == 0, f'a16 runs inside canvas (={oob})')
    labeled = (sem != -1) & union
    ck.check(int(labeled.sum()) == A16_PROP_UNION_PX,
             f'a16 labeled == prop union ({int(labeled.sum())})')
    outside = int(((sem != -1) & ~union).sum())
    ck.check(outside == 0, f'a16 labeled_outside_prop_union == 0 (={outside})')
    counts = {c: int(((sem == i) & union).sum())
              for i, c in enumerate(CLASSES)}
    ck.check(sum(counts.values()) == A16_PROP_UNION_PX,
             'a16 class_sum == 36124')

    # ---- a16 deliverables -------------------------------------------
    for i, cname in enumerate(CLASSES):
        m_exp = (sem == i) & union
        p = output / f'a16_class_{cname}.png'
        if ck.check(p.exists(), f'a16_class_{cname}.png present'):
            ck.check(np.array_equal(png_pixels(p) > 127, m_exp),
                     f'a16_class_{cname}.png pixels')
        n = output / f'a16_class_{cname}.npy'
        if ck.check(n.exists(), f'a16_class_{cname}.npy present'):
            ck.check(np.array_equal(np.load(n).astype(bool), m_exp),
                     f'a16_class_{cname}.npy pixels')
        c = output / f'a16_class_{cname}_cutout.png'
        ck.check(c.exists(), f'a16_class_{cname}_cutout.png present')
    idx_p = output / 'a16_occlusion_partition_indexed.png'
    if ck.check(idx_p.exists(), 'partition indexed PNG present'):
        pim = Image.open(idx_p)
        idx = np.array(pim)
        exp_idx = np.full((H, W), 6, np.uint8)
        for i in range(6):
            exp_idx[(sem == i) & union] = i
        ck.check(np.array_equal(idx, exp_idx),
                 'partition indexed values preserved (classes 0-5, '
                 'off-union 6)')
        ck.check(pim.mode == 'P', 'partition is indexed/palette PNG')
    for rel in ('a16_occlusion_partition_color.png',
                'a16_semantic_overlay.png',
                'a16_zoom_hand_400.png', 'a16_zoom_hand_800.png',
                'a16_zoom_cuff_400.png', 'a16_zoom_cuff_800.png',
                'a16_zoom_seat_400.png', 'a16_zoom_seat_800.png',
                'a16_zoom_blade_400.png', 'a16_zoom_blade_800.png'):
        ck.check((output / rel).exists(), f'{rel} present')

    # ---- tails: raw gates + deliverables ----------------------------
    tail_stats = {}
    for asset in ('a01', 'a05'):
        master = np.array(Image.open(
            masters / MASTERS_FILES[asset]).convert('RGBA'))
        h, w = master.shape[:2]
        visible = master[..., 3] > ALPHA
        doc_t = json.loads((sources / f'{asset}_tail_source.json')
                           .read_text(encoding='utf-8'))
        raw = runs_rebuild(doc_t['rows'], h, w)
        raw_out = int((raw & ~visible).sum())
        ck.check(raw_out == 0,
                 f'{asset} raw_source ∩ outside_visible == 0 (={raw_out})')
        prot = np.zeros((h, w), bool)
        for term in PROTECTED_TERMS[asset]:
            prot |= np.array(Image.open(
                r4masks / asset / f'{asset}_{term}.png').convert('L')) > 127
        raw_prot = int((raw & prot).sum())
        ck.check(raw_prot == 0,
                 f'{asset} raw_source ∩ protected == 0 (={raw_prot})')
        dest_exp = mirror(raw, w)
        vis_dest_exp = dest_exp & ~visible
        underlay_exp = dest_exp & visible
        mirror_out = int((mirror(dest_exp, w) ^ raw).sum())
        ck.check(mirror_out == 0,
                 f'{asset} mirror_source_outside_tail == 0 (={mirror_out})')
        vd_prot = int((vis_dest_exp & prot).sum())
        ck.check(vd_prot == 0,
                 f'{asset} visible_destination ∩ protected == 0 (={vd_prot})')
        stats = {'tail_source_px': int(raw.sum()),
                 'destination_px': int(dest_exp.sum()),
                 'visible_destination_px': int(vis_dest_exp.sum()),
                 'underlay_px': int(underlay_exp.sum()),
                 'underlay_protected_px': int((underlay_exp & prot).sum()),
                 'raw_outside_visible': raw_out,
                 'raw_protected_overlap': raw_prot,
                 'mirror_source_outside_tail': mirror_out}
        tail_stats[asset] = stats
        for name, exp in [('tail_source', raw),
                          ('tail_destination', dest_exp),
                          ('tail_visible_destination', vis_dest_exp),
                          ('tail_underlay', underlay_exp)]:
            p = output / asset / f'{asset}_{name}.png'
            if ck.check(p.exists(), f'{asset}_{name}.png present'):
                ck.check(np.array_equal(png_pixels(p) > 127, exp),
                         f'{asset}_{name}.png pixels')
            n = output / asset / f'{asset}_{name}.npy'
            if ck.check(n.exists(), f'{asset}_{name}.npy present'):
                ck.check(np.array_equal(np.load(n).astype(bool), exp),
                         f'{asset}_{name}.npy pixels')

    # ---- report / receipt -------------------------------------------
    rep_p = output / 'NIGHT03_PATCH2B_R1A_R4_REPORT.md'
    rec_p = output / 'NIGHT03_PATCH2B_R1A_R4_RECEIPT.txt'
    if ck.check(rep_p.exists(), 'report present'):
        rep = rep_p.read_text(encoding='utf-8')
        ck.check(f'STATUS = {STATUS_EXPECTED}' in rep, 'report STATUS R1A-R4')
        ck.check('PATCH2B_R1A_R3' not in rep, 'report carries no R1A-R3 name')
        for asset in ('a01', 'a05'):
            for k, v in tail_stats[asset].items():
                ck.check(f'- {k}: {v}' in rep,
                         f'report {asset} {k} == {v}')
        for cname in CLASSES:
            ck.check(f'- class {cname}: {counts[cname]}' in rep,
                     f'report a16 class {cname} == {counts[cname]}')
    if ck.check(rec_p.exists(), 'receipt present'):
        rec = rec_p.read_text(encoding='utf-8')
        ck.check(f'STATUS = {STATUS_EXPECTED}' in rec,
                 'receipt STATUS R1A-R4')
        ck.check('PATCH2B_R1A_R3' not in rec,
                 'receipt carries no R1A-R3 name')
        kv = dict(re.findall(r'^([A-Z0-9_]+) = (.*)$',
                             rec, re.MULTILINE))
        ck.check(kv.get('CANDIDATES_CREATED') == '0',
                 'receipt CANDIDATES_CREATED = 0')
        ck.check(kv.get('GENERATION_CALLS') == '0',
                 'receipt GENERATION_CALLS = 0')
        ck.check(kv.get('A16_LABELED_PX') == str(A16_PROP_UNION_PX),
                 'receipt A16_LABELED_PX')
        ck.check(kv.get('A16_CLASS_SUM') == str(A16_PROP_UNION_PX),
                 'receipt A16_CLASS_SUM')
        try:
            got = json.loads(kv.get('A16_CLASSES', '{}'))
        except json.JSONDecodeError:
            got = {}
        ck.check(got == counts, 'receipt A16_CLASSES exact')
        for asset in ('a01', 'a05'):
            for k, v in tail_stats[asset].items():
                ck.check(kv.get(f'{asset.upper()}_{k.upper()}') == str(v),
                         f'receipt {asset}_{k} == {v}')

    # ---- manifest ----------------------------------------------------
    mf_p = output / 'manifest.json'
    if ck.check(mf_p.exists(), 'manifest present'):
        mf = json.loads(mf_p.read_text(encoding='utf-8'))
        actual = {p.relative_to(output).as_posix(): sha256_path(p)
                  for p in sorted(output.rglob('*'))
                  if p.is_file() and p.name != 'manifest.json'}
        ck.check(set(mf) == set(actual),
                 'manifest covers exactly the delivered files')
        bad = [k for k in mf if mf.get(k) != actual.get(k)]
        ck.check(not bad, f'manifest hashes match files (bad: {bad[:3]})')
        ck.check('manifest.json' not in mf, 'manifest excludes itself')

    return ck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sources', type=Path,
                    default=ROOT / 'data/assets_v2/annotation_sources/'
                                   'night03_patch2b_r1a_r4')
    ap.add_argument('--output', type=Path,
                    default=ROOT / 'data/assets_v2/repair_candidates/'
                                   'night03_patch2b_r1a_r4')
    ap.add_argument('--r6ar4-json', type=Path,
                    default=ROOT / 'data/assets_v2/repair_candidates/'
                                   'night03_patch2a_r6ar4/'
                                   'a16_ownership_annotation.json')
    ap.add_argument('--r4masks', type=Path,
                    default=ROOT / 'data/assets_v2/repair_candidates/'
                                   'night03_patch2a_r4/mask_plan')
    ap.add_argument('--masters', type=Path,
                    default=ROOT / 'data/assets_v2/masters')
    args = ap.parse_args()
    try:
        ck = verify(args.sources, args.output, args.r6ar4_json,
                    args.r4masks, args.masters)
    except VerifyFail as e:
        print(f'VERIFIER FAIL: {e}')
        return 1
    except Exception as e:  # any unexpected inconsistency fails closed
        print(f'VERIFIER FAIL (unexpected): {type(e).__name__}: {e}')
        return 1
    passes, failures = ck.result()
    for f in failures:
        print(f'FAIL: {f}')
    ok = not failures
    print(f'VERIFIER {"PASS" if ok else "FAIL"}: {passes} checks passed, '
          f'{len(failures)} failed')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
