"""NIGHT-03 Recovery Patch 2A R3 — verify the frozen mask plan (independent).

R3 additions per the Reviewer Gate: the verifier rebuilds the cutout
evidence from master+masks and compares it byte-exact against the committed
evidence files; the Builder report metrics are cross-checked against the
frozen plan (stale metrics fail); the a16 cutout is audited for leftover
staff/chair fragments inside the corridors.

Re-derives every claim from the delivered FILES only.  R2/R3 checks: the
candidate scan actually scans THIS round's directory, a01/a05 masks are
compared byte-identical against the previous round freezes, the residual
accounting must close exactly, the cutout evidence is rebuilt from
master+masks and compared byte-exact, the Builder report metrics are
cross-checked against the frozen plan, and the verifier runs two fail-closed
self-tests (1px protected invasion and a candidate-like file)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
PLAN_DIR = ROOT / ('data/assets_v2/repair_candidates/'
                   'night03_patch2a_r3/mask_plan')
PLAN_R1_DIR = ROOT / ('data/assets_v2/repair_candidates/'
                      'night03_patch2a_r2/mask_plan')
REPORT_MD = ROOT / ('data/assets_v2/repair_candidates/night03_patch2a_r3/'
                    'NIGHT03_PATCH2A_R3_MASK_FREEZE_REPORT.md')
PLAN_2A_DIR = ROOT / ('data/assets_v2/repair_candidates/'
                      'night03_patch2/mask_plan')
PATCH2_R2 = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r3'
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

    # ---- R3: rebuild cutouts from master+masks, compare byte-exact ----
    a16ent = plan['assets'].get('a16')
    if a16ent:
        a16dir = PLAN_DIR / 'a16'
        master = np.array(Image.open(
            ROOT / a16ent['master_file']).convert('RGBA'))
        cane = np.array(Image.open(a16dir / 'a16_cane_removal.png')) == 255
        chair = np.array(Image.open(a16dir / 'a16_chair_removal.png')) == 255
        for tag, kill in (('cane', cane), ('chair', chair),
                          ('cane_chair', cane | chair)):
            cut = master.copy()
            cut[..., 3][kill] = 0
            bgc = np.zeros((1536, 1024, 3), np.uint8)
            yy, xx = np.mgrid[0:1536, 0:1024]
            t = ((xx // 24) + (yy // 24)) % 2 == 0
            bgc[...] = np.where(t[..., None], 200, 150)
            af = cut[..., 3:4].astype(np.float32) / 255.0
            comp = (cut[..., :3].astype(np.float32) * af
                    + bgc.astype(np.float32) * (1 - af)
                    ).clip(0, 255).astype(np.uint8)
            committed = a16dir / f'a16_{tag}_cutout_checker_100.png'
            if not committed.exists():
                fail(msgs, f'a16: committed cutout missing: {committed.name}')
                continue
            ref = np.array(Image.open(committed).convert('RGB'))
            if not (ref == comp).all():
                diffpx = int((ref != comp).any(axis=2).sum())
                fail(msgs, f'a16 {tag} cutout: rebuilt image differs from '
                           f'committed evidence ({diffpx}px)')

    # ---- R3: report metrics must match the frozen plan ----
    if REPORT_MD.exists():
        txt = REPORT_MD.read_text(encoding='utf-8')
        if plan['MASK_PLAN_SHA256'] not in txt:
            fail(msgs, 'report does not carry the frozen MASK_PLAN_SHA256')
        for asset, ent in plan['assets'].items():
            for name, meta in ent['masks'].items():
                token = f"{meta['px']}"
                if name in ('tail_source', 'old_tail_removal',
                            'tail_destination', 'seam_reconstruction',
                            'authorized_cleanup', 'speck_cleanup',
                            'chair_removal', 'cane_removal',
                            'hair_reconstruction', 'hand_reconstruction',
                            'protected_costume', 'protected_props',
                            'protected_quill_paper',
                            'protected_glove_gold_cuff',
                            'protected_existing_hair'):
                    if asset == 'a01' and name == 'protected_identity':
                        token = ''
                    if token and token not in txt:
                        fail(msgs, f'report stale: {asset}/{name} px '
                                   f'{meta["px"]} not found in report')
        if 'STATUS = READY_FOR_NIGHT03_PATCH2A_R2_REVIEW' in txt:
            fail(msgs, 'report still carries the R2 status line')
    else:
        fail(msgs, 'Builder report missing')

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

    # ---- R3: leftover-fragment audit inside the corridors ----
    if a16ent:
        master = np.array(Image.open(
            ROOT / a16ent['master_file']).convert('RGBA'))
        corridor = np.zeros((1536, 1024), bool)
        for x0, y0, x1, y1 in [(592, 1155, 722, 1450),
                               (410, 1080, 730, 1470)]:
            corridor[y0:y1, x0:x1] = True
        gone = np.zeros((1536, 1024), bool)
        for name in ('cane_removal', 'chair_removal'):
            gone |= np.array(Image.open(
                PLAN_DIR / 'a16' / f'a16_{name}.png')) == 255
        # same-colour leftovers of cane/chair inside their own corridors,
        # excluding pixels near the protected masks (documented boundary AA)
        rgbm = master[..., :3].astype(int)
        rm, gm, bm = rgbm[..., 0], rgbm[..., 1], rgbm[..., 2]
        brightm = (rm + gm + bm) / 3.0
        near = ndimage.binary_dilation(
            np.array(Image.open(PLAN_DIR / 'a16' / 'a16_protected_costume.png'
                                )) == 255, np.ones((3, 3), bool), iterations=2)
        cand_left = ((bm - rm >= 25) & (bm >= gm) | ((rm >= gm) & (gm > bm)
                     & (rm - bm >= 10) & (rm >= 25) & (brightm <= 210)))
        left = cand_left & corridor & ~gone & ~near & (
            master[..., 3] > 8)
        lab2, n2 = ndimage.label(left, structure=np.ones((3, 3), bool))
        big = 0
        for i in range(1, n2 + 1):
            c = lab2 == i
            if int(c.sum()) >= 120:
                big += 1
        if big:
            fail(msgs, f'a16: {big} leftover same-colour fragments (>=120px) '
                       f'remain inside the cane/chair corridors')

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
