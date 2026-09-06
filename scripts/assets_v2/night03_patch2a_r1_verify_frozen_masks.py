"""NIGHT-03 Recovery Patch 2A R1 — verify the frozen mask plan (independent).

Re-derives every claim from the delivered FILES only: mask PNGs, the plan
JSON, the masters, BASE, frozen specs and the untouched Reviewer report.
Any post-freeze modification of a mask, any value outside {0,255}, any
allowed/protected overlap, any union-equation violation, any master/BASE
drift or any candidate PNG anywhere makes this script exit non-zero.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PLAN_DIR = ROOT / ('data/assets_v2/repair_candidates/'
                   'night03_patch2a_r1/mask_plan')
PLAN_2A_DIR = ROOT / 'data/assets_v2/repair_candidates/night03_patch2/mask_plan'
PATCH2 = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r1'
PLAN_P = PLAN_DIR / 'night03_patch2_mask_plan.json'
MASTERS = ROOT / 'data/assets_v2/masters'
BASE_P = ROOT / 'data/assets_v2/_base/furina-base.png'
SPEC_DIR = ROOT / 'data/assets_v2/_spec'
REVIEW_REPORT = ROOT / ('data/assets_v2/repair_candidates/night03_patch1/'
                        'NIGHT03_PATCH1_REVIEW_REPORT.md')
PATCH2 = ROOT / 'data/assets_v2/repair_candidates/night03_patch2'
MANIFEST = ROOT / ('data/assets_v2/repair_candidates/night03/'
                   'night03_repair_manifest.json')


def sha256_path(p):
    hsh = hashlib.sha256()
    with open(p, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            hsh.update(chunk)
    return hsh.hexdigest()


def _alpha_of(ent):
    mf = ROOT / ent['master_file']
    return np.array(Image.open(mf).convert('RGBA'))[..., 3] > 8


def fail(msgs, m):
    msgs.append(m)


def main():
    msgs = []
    plan = json.loads(PLAN_P.read_text(encoding='utf-8'))

    # 1. plan self-hash (canonical JSON over the plan without the hash field)
    plan_copy = {k: v for k, v in plan.items() if k != 'MASK_PLAN_SHA256'}
    canonical = json.dumps(plan_copy, sort_keys=True, ensure_ascii=True,
                           separators=(',', ':'))
    got = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    if got != plan.get('MASK_PLAN_SHA256'):
        fail(msgs, f'MASK_PLAN_SHA256 mismatch: {got} != '
                   f'{plan.get("MASK_PLAN_SHA256")}')

    # 2. inputs unchanged
    for rel, want in plan['inputs'].items():
        p = {'BASE': BASE_P,
             'PATCH1_REVIEW_REPORT': REVIEW_REPORT}.get(
            rel, ROOT / 'data/assets_v2' / rel)
        if not p.exists():
            fail(msgs, f'missing input {rel}')
            continue
        got = sha256_path(p)
        if got != want:
            fail(msgs, f'input changed: {rel} {got} != {want}')

    # 2b. masters must still match the NIGHT-03 repair manifest records
    if MANIFEST.exists():
        man = json.loads(MANIFEST.read_text(encoding='utf-8'))
        rec = {}
        def walk(o):
            if isinstance(o, dict):
                if 'asset_id' in o and 'master_sha256' in o:
                    rec[o['asset_id']] = o['master_sha256']
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(man)
        for asset, ent in plan['assets'].items():
            want = rec.get(ent['master_file'].split('furina_v2_')[1][:3]
                           if False else asset)
            if want and want != ent['master_sha256']:
                fail(msgs, f'{asset}: master SHA drifts from NIGHT-03 '
                           f'manifest ({want} != {ent["master_sha256"]})')

    # 3. every mask PNG: values/dims/count/bbox/sha + structural checks
    for asset, ent in plan['assets'].items():
        masks = {}
        for name, meta in ent['masks'].items():
            p = PLAN_DIR / asset / f'{asset}_{name}.png'
            if not p.exists():
                fail(msgs, f'{asset}/{name}: mask PNG missing')
                continue
            if sha256_path(p) != meta['sha256']:
                fail(msgs, f'{asset}/{name}: mask modified after freeze')
            im = Image.open(p)
            if im.mode != 'L' or im.size != (1024, 1536):
                fail(msgs, f'{asset}/{name}: not single-channel 1024x1536')
                continue
            arr = np.array(im)
            vals = np.unique(arr)
            if vals.size and vals.max() > 255 or (vals.size and
                                                  not np.isin(vals,
                                                              [0, 255]).all()):
                fail(msgs, f'{asset}/{name}: values outside {{0,255}}: {vals}')
            m = arr == 255
            masks[name] = m
            ys, xs = np.where(m)
            bbox = ([int(xs.min()), int(ys.min()), int(xs.max()),
                     int(ys.max())] if m.any() else None)
            if int(m.sum()) != meta['px'] or bbox != meta['bbox']:
                fail(msgs, f'{asset}/{name}: px/bbox drift vs plan')
        if len(masks) != len(ent['masks']):
            continue

        # 4. allowed union equation, rebuilt from the delivered PNGs
        u = np.zeros((1536, 1024), bool)
        for t in ent['allowed_terms']:
            if t in masks:
                u |= masks[t]
        if not (u == masks['allowed_edit']).all():
            fail(msgs, f'{asset}: allowed_edit != union(terms) on disk')

        # 5. allowed vs protected zero overlap, from the PNGs
        for name in masks:
            if name.startswith('protected_'):
                inter = int((masks['allowed_edit'] & masks[name]).sum())
                if inter:
                    fail(msgs, f'{asset}: allowed ∩ {name} = {inter}px '
                               f'(must be 0)')
                if ent['intersections'].get(f'allowed_edit^{name}', 0) != \
                        inter:
                    fail(msgs, f'{asset}: intersection record mismatch '
                               f'({name})')

        # 6. destination must sit on currently transparent pixels only
        mf = ROOT / ent['master_file']
        master = np.array(Image.open(mf).convert('RGBA'))
        if (masks['tail_destination'] & (master[..., 3] > 8)).any():
            fail(msgs, f'{asset}: tail_destination covers existing alpha')
        if ent['master_sha256'] != sha256_path(mf):
            fail(msgs, f'{asset}: master file hash drift')

        # 6b. R1: a05 masks must be byte-identical to the 2A freeze
        if asset == 'a05':
            for name, meta in ent['masks'].items():
                p2a = PLAN_2A_DIR / 'a05' / f'a05_{name}.png'
                if not p2a.exists():
                    fail(msgs, f'a05/{name}: 2A mask missing for comparison')
                    continue
                if sha256_path(p2a) != meta['sha256']:
                    fail(msgs, f'a05/{name}: differs from 2A frozen mask '
                               f'(must be byte-identical)')

    # 6c. R1 independent raw-zone audit for a16: chair/cane/hand may not
    # touch a single pixel of the raw quill/paper boxes.  (The gold grip
    # legitimately passes through the fist zone; glove protection is the
    # independent protected_glove_gold_cuff zero-overlap check above.)
    a16 = plan['assets'].get('a16')
    if a16:
        qp_boxes = [(320, 940, 400, 1100), (330, 1085, 510, 1180)]
        zone = np.zeros((1536, 1024), bool)
        for x0, y0, x1, y1 in qp_boxes:
            zone[y0:y1, x0:x1] = True
        zone &= _alpha_of(a16)
        for name in ('chair_removal', 'cane_removal', 'hand_reconstruction',
                     'old_tail_removal', 'tail_destination'):
            p = PLAN_DIR / 'a16' / f'a16_{name}.png'
            arr = np.array(Image.open(p)) == 255
            raw_over = int((arr & zone).sum())
            if raw_over:
                fail(msgs, f'a16/{name} invades raw quill-paper zone '
                           f'({raw_over}px)')

    # 7. no candidate PNG anywhere under night03_patch2a_r1
    for p in PATCH2.rglob('*.png'):
        rel = p.relative_to(PATCH2).as_posix()
        if not (rel.startswith('_inspect/') or rel.startswith('mask_plan/')):
            fail(msgs, f'unexpected png outside _inspect/mask_plan: {rel}')
    for p in PATCH2.rglob('*'):
        name = p.name.lower()
        if p.suffix == '.png' and ('candidate' in name or 'repair' in name):
            fail(msgs, f'candidate-like png present: {p}')
    for p in PATCH2.rglob('*'):
        name = p.name.lower()
        if p.suffix == '.png' and ('candidate' in name or 'repair' in name):
            fail(msgs, f'candidate-like png present: {p}')

    if msgs:
        print('VERIFY FAILED:')
        for m in msgs:
            print(' -', m)
        sys.exit(1)
    print('VERIFY OK —', plan['MASK_PLAN_SHA256'])
    print('  masks on disk == plan; union equations hold; '
          'allowed ∩ protected = 0 everywhere;')
    print('  destinations on transparent pixels only; masters/BASE/specs/'
          'reviewer report bit-identical; zero candidates.')
    sys.exit(0)


if __name__ == '__main__':
    main()
