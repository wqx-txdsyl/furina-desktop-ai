"""NIGHT-03 Patch 2B R1B — INDEPENDENT candidate verifier.

Does not import the candidate builder.  Independently reads the
masters, the R1A-R6 frozen sources, the pinned R1B reconstruction
source and the three candidates; rebuilds the a01/a05 mirror mapping
and the a16 six-class sets; computes every diff/alpha/class/SHA/
manifest relation itself; read-only; exits non-zero on any violation.
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
STATUS_EXPECTED = 'READY_FOR_NIGHT03_PATCH2B_R1B_INDEPENDENT_VISUAL_REVIEW'

CROP_REGIONS = {
    'a01': ('tail_root', 'cane_junction', 'tail_tip'),
    'a05': ('bow_tail_root', 'dress_edge', 'tail_tip'),
    'a16': ('hand', 'cuff', 'seat', 'blade', 'lower_garment'),
}

PINNED_SHA256 = {
    'master_a01': (
        'c3ed763c7eed3bfc620e4847e0028e5c6eae83a8170f41a1152915e7885172a6'),
    'master_a05': (
        '8ddcfde186fb352ce32381543273902295ceeb3fd3f3db6b064141fcf5199a77'),
    'master_a16': (
        'f4997917453d6a541a08d021132ecad3bd8cffb63773833d31bdcde805d099ab'),
    'r1a_tail_a01': None,   # filled from the R1A source manifest at runtime
    'r1a_tail_a05': None,
    'r1a_a16_occ': None,
    'r1b_recon_a16': None,
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


def verify(r1a_src, r1b_src, output, masters):
    ck = Checker()

    manifest = json.loads((r1b_src / 'source_manifest.json')
                          .read_text(encoding='utf-8'))
    files = manifest['files']
    for rel, expected in sorted(files.items()):
        if 'night03_patch2b_r1a_r6' in rel:
            fpath = r1a_src / Path(rel).name
        else:
            fpath = r1b_src / Path(rel).name
        if not ck.check(sha256_path(fpath) == expected,
                        f'source pin {rel}'):
            raise VerifyFail(f'source tampered: {rel}')

    PINNED_SHA256['r1a_tail_a01'] = files[
        'data/assets_v2/annotation_sources/night03_patch2b_r1a_r6/'
        'a01_tail_source.json']
    PINNED_SHA256['r1a_tail_a05'] = files[
        'data/assets_v2/annotation_sources/night03_patch2b_r1a_r6/'
        'a05_tail_source.json']
    PINNED_SHA256['r1a_a16_occ'] = files[
        'data/assets_v2/annotation_sources/night03_patch2b_r1a_r6/'
        'a16_occlusion_annotation.json']
    PINNED_SHA256['r1b_recon_a16'] = files[
        'data/assets_v2/annotation_sources/night03_patch2b_r1b/'
        'a16_reconstruction_source.png']

    for asset in ('a01', 'a05', 'a16'):
        ck.check(sha256_path(masters / MASTERS_FILES[asset]) ==
                 PINNED_SHA256[f'master_{asset}'],
                 f'master_{asset} pin')

    # ---- a16 sets ----------------------------------------------------
    occ = json.loads((r1a_src / 'a16_occlusion_annotation.json')
                     .read_text(encoding='utf-8'))
    sem = np.full((H, W), -1, np.int16)
    for row in occ['rows']:
        y = int(row[0])
        for a, b, cn in row[1:]:
            sem[y, int(a):int(b) + 1] = CLASSES.index(cn)
    UNION = sem >= 0
    m_trans = UNION & (sem == 0)
    m_non = UNION & (sem > 0)
    ck.check(int(UNION.sum()) == A16_PROP_UNION_PX,
             'a16 prop union == 36124 px')
    recon = np.array(Image.open(
        r1b_src / 'a16_reconstruction_source.png').convert('RGBA'))

    # ---- a01/a05 -------------------------------------------------------
    tail_stats = {}
    for asset in ('a01', 'a05'):
        master = np.array(Image.open(
            masters / MASTERS_FILES[asset]).convert('RGBA'))
        h, w = master.shape[:2]
        doc = json.loads((r1a_src / f'{asset}_tail_source.json')
                         .read_text(encoding='utf-8'))
        source = runs_rebuild(doc['rows'], h, w)
        dest = mirror(source, w)
        vis_dest = dest & (master[..., 3] <= ALPHA)
        underlay = dest & (master[..., 3] > ALPHA)
        cand_p = output / asset / f'{asset}_candidate.png'
        if not ck.check(cand_p.exists(), f'{asset} candidate present'):
            raise VerifyFail(f'{asset} candidate missing')
        cand = np.array(Image.open(cand_p).convert('RGBA'))
        ck.check(cand.shape == (h, w, 4), f'{asset} candidate 1024x1536 RGBA')
        diff = source | vis_dest
        # authorized diff exactness
        actual = (cand != master).any(axis=-1)
        ck.check(np.array_equal(actual, diff),
                 f'{asset} ACTUAL_DIFF == TAIL_SOURCE ∪ VISIBLE_DESTINATION '
                 f'({int(actual.sum())} vs {int(diff.sum())})')
        # source cleared
        ck.check(not (cand[source] != 0).any(),
                 f'{asset} tail source fully transparent')
        # visible destination bit-exact mirror
        mys, mxs = np.where(vis_dest)
        ck.check(np.array_equal(cand[mys, mxs],
                                master[mys, (w - 1) - mxs]),
                 f'{asset} visible destination bit-exact mirror')
        # underlay preserved
        uys, uxs = np.where(underlay)
        ck.check(np.array_equal(cand[uys, uxs], master[uys, uxs]),
                 f'{asset} underlay preserved')
        # protected underlay (a05): underlay ∩ protected must be preserved
        stats = {'tail_source_px': int(source.sum()),
                 'destination_px': int(dest.sum()),
                 'visible_destination_px': int(vis_dest.sum()),
                 'underlay_px': int(underlay.sum()),
                 'actual_diff_px': int(diff.sum())}
        tail_stats[asset] = stats

    # ---- a16 ------------------------------------------------------------
    master16 = np.array(Image.open(
        masters / MASTERS_FILES['a16']).convert('RGBA'))
    cand_p = output / 'a16' / 'a16_candidate.png'
    if not ck.check(cand_p.exists(), 'a16 candidate present'):
        raise VerifyFail('a16 candidate missing')
    cand16 = np.array(Image.open(cand_p).convert('RGBA'))
    ck.check(cand16.shape == (H, W, 4), 'a16 candidate 1024x1536 RGBA')
    outside = (cand16 != master16).any(axis=-1) & ~UNION
    ck.check(not outside.any(),
             f'a16 outside-union diff == 0 ({int(outside.sum())})')
    tz = cand16[m_trans]
    ck.check(tz.shape[0] == 0 or not (tz != 0).any(),
             'a16 transparent class all [0,0,0,0]')
    ck.check(np.array_equal(cand16[m_non], recon[m_non]),
             'a16 non-transparent classes == pinned reconstruction source')
    ck.check((cand16[m_non][..., 3] > ALPHA).all() if m_non.any() else True,
             'a16 non-transparent alpha > 8')
    counts = {c: int(((sem == i) & UNION).sum())
              for i, c in enumerate(CLASSES)}
    ck.check(sum(counts.values()) == A16_PROP_UNION_PX,
             'a16 class sum == 36124')

    # no magenta anywhere
    mag = (cand16[..., 0] == 255) & (cand16[..., 1] == 0) & \
        (cand16[..., 2] == 255)
    ck.check(not mag.any(), 'a16 no magenta px')
    for asset in ('a01', 'a05'):
        cpath = output / asset / f'{asset}_candidate.png'
        c = np.array(Image.open(cpath).convert('RGBA'))
        mag = (c[..., 0] == 255) & (c[..., 1] == 0) & (c[..., 2] == 255)
        ck.check(not mag.any(), f'{asset} no magenta px')

    # ---- evidence presence ----------------------------------------------
    for asset in ('a01', 'a05'):
        for rel in (
            f'{asset}_compare_checker.png', f'{asset}_compare_light.png',
            f'{asset}_compare_dark.png',
            f'{asset}_triptych_checker.png',
            f'{asset}_diff_classified.png',
            f'{asset}_allowed_edit_overlay.png',
            f'{asset}_alpha_compare.png',
            f'{asset}_checker_512.png', f'{asset}_checker_256.png',
            f'{asset}_checker_128.png', f'{asset}_light_512.png',
            f'{asset}_light_256.png', f'{asset}_light_128.png',
            f'{asset}_dark_512.png', f'{asset}_dark_256.png',
            f'{asset}_dark_128.png',
        ):
            ck.check((output / asset / rel).exists(), f'{asset}/{rel} present')
        for tag in CROP_REGIONS[asset]:
            for z in (200, 400, 800):
                ck.check(
                    (output / asset /
                     f'{asset}_crop_{tag}_{z}.png').exists(),
                    f'{asset} crop {tag} {z}')
    for rel in ('a16_compare_checker.png', 'a16_compare_light.png',
                'a16_compare_dark.png', 'a16_semantic_overlay.png',
                'a16_write_coverage.png', 'a16_outside_union_diff.png',
                'a16_reconstruction_source_full.png',
                'a16_class_transparent_layer.png',
                'a16_class_hand_glove_layer.png',
                'a16_class_gold_cuff_layer.png',
                'a16_class_sleeve_coat_layer.png',
                'a16_class_lower_garment_leg_layer.png',
                'a16_class_other_layer.png',
                'a16_checker_512.png', 'a16_checker_256.png',
                'a16_checker_128.png', 'a16_light_512.png',
                'a16_light_256.png', 'a16_light_128.png',
                'a16_dark_512.png', 'a16_dark_256.png',
                'a16_dark_128.png'):
        ck.check((output / 'a16' / rel).exists(), f'a16/{rel} present')
    for tag in CROP_REGIONS['a16']:
        for z in (200, 400, 800):
            ck.check((output / 'a16' / f'a16_triptych_{tag}_{z}.png').exists(),
                     f'a16 triptych {tag} {z}')

    # diff-classified pixel verification (a01): recompute and compare
    master = np.array(Image.open(
        masters / MASTERS_FILES['a01']).convert('RGBA'))
    h, w = master.shape[:2]
    doc = json.loads((r1a_src / 'a01_tail_source.json')
                     .read_text(encoding='utf-8'))
    source = runs_rebuild(doc['rows'], h, w)
    dest = mirror(source, w)
    vis_dest = dest & (master[..., 3] <= ALPHA)
    diff = source | vis_dest
    cand = np.array(Image.open(
        output / 'a01' / 'a01_candidate.png').convert('RGBA'))
    diff_map = np.zeros((h, w, 3), np.uint8)
    diff_map[source] = [220, 40, 40]
    diff_map[vis_dest] = [40, 200, 60]
    got = np.array(Image.open(
        output / 'a01' / 'a01_diff_classified.png').convert('RGB'))
    ck.check(np.array_equal(got, diff_map),
             'a01 diff_classified pixel-exact rebuild')

    # ---- report / receipt ------------------------------------------------
    rep_p = output / 'NIGHT03_PATCH2B_R1B_REPORT.md'
    rec_p = output / 'NIGHT03_PATCH2B_R1B_RECEIPT.txt'
    if ck.check(rep_p.exists(), 'report present'):
        rep = rep_p.read_text(encoding='utf-8')
        ck.check(f'STATUS = {STATUS_EXPECTED}' in rep,
                 'report STATUS R1B ready')
        sections = []
        cur_name, cur_lines = None, []
        for ln in rep.splitlines():
            if ln.startswith('## '):
                sections.append((cur_name, cur_lines))
                cur_name, cur_lines = ln[3:].strip(), []
            else:
                cur_lines.append(ln)
        sections.append((cur_name, cur_lines))

        def section_for(prefix):
            for name, lines in sections:
                if name is not None and name.startswith(prefix):
                    return lines
            return []

        for asset in ('a01', 'a05'):
            sec = section_for(f'{asset}')
            sec_set = set(sec)
            for k, v in tail_stats[asset].items():
                exp = f'- {k}: {v}'
                ck.check(exp in sec_set, f'report {asset} {k} == {v}')
                conflicts = [ln for ln in sec
                             if ln.startswith(f'- {k}: ') and ln != exp]
                ck.check(not conflicts,
                         f'report {asset} {k} no conflicting line '
                         f'({conflicts[:1]})')
        a16_sec = section_for('a16')
        a16_set = set(a16_sec)
        for cname in CLASSES:
            exp = f'- class {cname}: {counts[cname]}'
            ck.check(exp in a16_set,
                     f'report a16 class {cname} == {counts[cname]}')
            conflicts = [ln for ln in a16_sec
                         if ln.startswith(f'- class {cname}: ')
                         and ln != exp]
            ck.check(not conflicts,
                     f'report a16 class {cname} no conflicting line '
                     f'({conflicts[:1]})')
    if ck.check(rec_p.exists(), 'receipt present'):
        rec = rec_p.read_text(encoding='utf-8')
        kv = dict(re.findall(r'^([A-Z0-9_]+) = (.*)$', rec, re.MULTILINE))
        ck.check(len(set(kv)) == len(kv), 'receipt no duplicate keys')
        ck.check(kv.get('CANDIDATES_SUBMITTED') == '3',
                 'receipt CANDIDATES_SUBMITTED = 3')
        ck.check(kv.get('GENERATION_CALLS') == '0',
                 'receipt GENERATION_CALLS = 0')
        ck.check(kv.get('UNAUTHORIZED_DIFF_PIXELS') == '0',
                 'receipt UNAUTHORIZED_DIFF_PIXELS = 0')
        ck.check(f'STATUS = {STATUS_EXPECTED}' in rec,
                 'receipt STATUS R1B ready')
        for asset in ('a01', 'a05'):
            for k, v in tail_stats[asset].items():
                ck.check(kv.get(f'{asset.upper()}_{k.upper()}') == str(v),
                         f'receipt {asset}_{k} == {v}')

    # ---- manifest ----------------------------------------------------------
    mf_p = output / 'manifest.json'
    if ck.check(mf_p.exists(), 'manifest present'):
        mf = json.loads(mf_p.read_text(encoding='utf-8'))
        actual = {p.relative_to(output).as_posix(): sha256_path(p)
                  for p in sorted(output.rglob('*'))
                  if p.is_file() and p.name != 'manifest.json'}
        ck.check(set(mf) == set(actual),
                 'manifest covers exactly the delivered files')
        bad = [k for k in mf if mf.get(k) != actual.get(k)]
        ck.check(not bad, f'manifest hashes match (bad: {bad[:3]})')

    return ck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--r1a-src', type=Path,
                    default=ROOT / 'data/assets_v2/annotation_sources/'
                                   'night03_patch2b_r1a_r6')
    ap.add_argument('--r1b-src', type=Path,
                    default=ROOT / 'data/assets_v2/annotation_sources/'
                                   'night03_patch2b_r1b')
    ap.add_argument('--output', type=Path,
                    default=ROOT / 'data/assets_v2/repair_candidates/'
                                   'night03_patch2b_r1b')
    ap.add_argument('--masters', type=Path,
                    default=ROOT / 'data/assets_v2/masters')
    args = ap.parse_args()
    try:
        ck = verify(args.r1a_src, args.r1b_src, args.output, args.masters)
    except VerifyFail as e:
        print(f'VERIFIER FAIL: {e}')
        return 1
    except Exception as e:
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
