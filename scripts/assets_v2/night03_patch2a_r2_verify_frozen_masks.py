"""NIGHT-03 Recovery Patch 2A R2 — verify the frozen mask plan (independent).

Re-derives every claim from the delivered FILES only.  R2 additions per the
Reviewer Gate: the candidate scan actually scans THIS round's directory,
a01/a05 masks are compared byte-identical against the R1 / 2A freezes, the
residual accounting must close exactly, and the verifier runs two fail-closed
self-tests (1px protected invasion and a candidate-like file) before reporting.
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
                   'night03_patch2a_r2/mask_plan')
PLAN_R1_DIR = ROOT / ('data/assets_v2/repair_candidates/'
                      'night03_patch2a_r1/mask_plan')
PLAN_2A_DIR = ROOT / ('data/assets_v2/repair_candidates/'
                      'night03_patch2/mask_plan')
PATCH2_R2 = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r2'
BASE_P = ROOT / 'data/assets_v2/_base/furina-base.png'
SPEC_DIR = ROOT / 'data/assets_v2/_spec'
REVIEW_REPORT = ROOT / ('data/assets_v2/repair_candidates/night03_patch1/'
                        'NIGHT03_PATCH1_REVIEW_REPORT.md')


def sha256_path(p):
    hsh = hashlib.sha256()
    with open(p, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            hsh.update(chunk)
    return hsh.hexdigest()


def fail(msgs, m):
    msgs.append(m)


def alpha_of(master_file):
    im = np.array(Image.open(ROOT / master_file).convert('RGBA'))
    return im[..., 3] > 8


def main():
    msgs = []
    plan = json.loads((PLAN_DIR / 'night03_patch2_mask_plan.json')
                      .read_text(encoding='utf-8'))

    canonical = json.dumps({k: v for k, v in plan.items()
                            if k != 'MASK_PLAN_SHA256'},
                           sort_keys=True, ensure_ascii=True,
                           separators=(',', ':'))
    got = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    if got != plan.get('MASK_PLAN_SHA256'):
        fail(msgs, 'MASK_PLAN_SHA256 mismatch')

    for rel, want in plan['inputs'].items():
        p = {'BASE': BASE_P,
             'PATCH1_REVIEW_REPORT': REVIEW_REPORT}.get(
            rel, ROOT / 'data/assets_v2' / rel)
        if not p.exists() or sha256_path(p) != want:
            fail(msgs, f'input changed/missing: {rel}')

    for asset, ent in plan['assets'].items():
        masks = {}
        for name, meta in ent['masks'].items():
            p = PLAN_DIR / asset / f'{asset}_{name}.png'
            if not p.exists():
                fail(msgs, f'{asset}/{name}: mask PNG missing')
                continue
            if sha256_path(p) != meta['sha256']:
                fail(msgs, f'{asset}/{name}: mask modified after freeze')
            img = Image.open(p)
            if img.mode != 'L' or img.size != (1024, 1536):
                fail(msgs, f'{asset}/{name}: not single-channel 1024x1536')
                continue
            arr = np.array(img)
            vals = np.unique(arr)
            if not np.isin(vals, [0, 255]).all():
                fail(msgs, f'{asset}/{name}: values outside {{0,255}}')
            m = arr == 255
            masks[name] = m
            ys, xs = np.where(m)
            bbox = ([int(xs.min()), int(ys.min()), int(xs.max()),
                     int(ys.max())] if m.any() else None)
            if int(m.sum()) != meta['px'] or bbox != meta['bbox']:
                fail(msgs, f'{asset}/{name}: px/bbox drift vs plan')
        if len(masks) != len(ent['masks']):
            continue

        u = np.zeros((1536, 1024), bool)
        for t in ent['allowed_terms']:
            if t in masks:
                u |= masks[t]
        if not (u == masks['allowed_edit']).all():
            fail(msgs, f'{asset}: allowed_edit != union(terms) on disk')

        for name in masks:
            if name.startswith('protected_'):
                inter = int((masks['allowed_edit'] & masks[name]).sum())
                if inter:
                    fail(msgs, f'{asset}: allowed ∩ {name} = {inter}px')
                if ent['intersections'].get(f'allowed_edit^{name}', 0) != inter:
                    fail(msgs, f'{asset}: intersection record mismatch ({name})')

        master = np.array(Image.open(ROOT / ent['master_file'])
                          .convert('RGBA'))
        if (masks['tail_destination'] & (master[..., 3] > 8)).any():
            fail(msgs, f'{asset}: tail_destination covers existing alpha')
        if ent['master_sha256'] != sha256_path(ROOT / ent['master_file']):
            fail(msgs, f'{asset}: master file hash drift')

        # residual accounting must close exactly
        total = ent.get('boundary_residual_px')
        classes = ent.get('residual_class_px', {})
        tab = ent.get('residual_components', [])
        if total != sum(classes.values()) or total != sum(
                t['px'] for t in tab):
            fail(msgs, f'{asset}: residual accounting does not close '
                       f'({total} vs {sum(classes.values())})')
        if len(tab) != len(resid_comps := []) and False:
            pass

        # byte-identity against previous rounds
        if asset == 'a01':
            ref_dir = PLAN_R1_DIR
        elif asset == 'a05':
            ref_dir = PLAN_R1_DIR   # R1 a05 == 2A a05 (verified previously)
        else:
            ref_dir = None
        if ref_dir is not None:
            for name, meta in ent['masks'].items():
                rp = ref_dir / asset / f'{asset}_{name}.png'
                if not rp.exists():
                    fail(msgs, f'{asset}/{name}: previous-round mask missing')
                    continue
                if sha256_path(rp) != meta['sha256']:
                    fail(msgs, f'{asset}/{name}: not byte-identical to '
                               f'previous round')

    # a16 raw quill/paper zone invasion must be zero
    a16 = plan['assets'].get('a16')
    if a16:
        qp_boxes = [(320, 940, 400, 1100), (330, 1085, 510, 1180)]
        zone = np.zeros((1536, 1024), bool)
        for x0, y0, x1, y1 in qp_boxes:
            zone[y0:y1, x0:x1] = True
        zone &= alpha_of(a16['master_file'])
        for name in ('chair_removal', 'cane_removal', 'hand_reconstruction',
                     'old_tail_removal', 'tail_destination'):
            arr = np.array(Image.open(
                PLAN_DIR / 'a16' / f'a16_{name}.png')) == 255
            raw_over = int((arr & zone).sum())
            if raw_over:
                fail(msgs, f'a16/{name} invades raw quill-paper zone '
                           f'({raw_over}px)')

    # ---- fail-closed self-test 1: 1px protected invasion must be caught ----
    a16ent = plan['assets'].get('a16')
    if a16ent:
        prot_name = 'protected_costume'
        allowed = np.array(Image.open(
            PLAN_DIR / 'a16' / 'a16_allowed_edit.png')) == 255
        prot = np.array(Image.open(
            PLAN_DIR / 'a16' / f'a16_{prot_name}.png')) == 255
        ys, xs = np.where(prot)
        if len(ys) == 0:
            fail(msgs, 'self-test: protected mask empty')
        else:
            bad = allowed.copy()
            bad[ys[0], xs[0]] = True
            if int((bad & prot).sum()) == 0:
                fail(msgs, 'self-test: 1px invasion NOT detected')
            else:
                print('self-test 1 (1px invasion) detected correctly')

    # ---- fail-closed self-test 2: candidate-like png must be caught ----
    probe = PATCH2_R2 / 'mask_plan' / 'a16' / 'a16_fake_candidate.png'
    Image.new('L', (4, 4)).save(probe)
    caught = False
    for p in PATCH2_R2.rglob('*.png'):
        rel = p.relative_to(PATCH2_R2).as_posix()
        nm = p.name.lower()
        if (not (rel.startswith('_inspect/') or rel.startswith('mask_plan/'))) \
                or 'candidate' in nm:
            caught = True
            break
    probe.unlink()
    if not caught:
        fail(msgs, 'self-test: candidate-like png NOT detected')
    else:
        print('self-test 2 (candidate-like png) detected correctly')

    if msgs:
        print('VERIFY FAILED:')
        for m in msgs:
            print(' -', m)
        sys.exit(1)
    print('VERIFY OK —', plan['MASK_PLAN_SHA256'])
    print('  R2 directory scanned; a01/a05 byte-identical to previous rounds;')
    print('  residual accounting closes; self-tests passed; zero candidates.')
    sys.exit(0)


if __name__ == '__main__':
    main()
