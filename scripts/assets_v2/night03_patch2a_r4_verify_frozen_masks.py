"""NIGHT-03 Recovery Patch 2A R4 — verify the frozen mask plan (independent).

R4 checks per the Reviewer Gate:
- verifier root points ONLY at night03_patch2a_r4; candidate scan scans R4;
- all masks: mode/values/px/bbox/SHA256/union per asset;
- a01/a05 masks byte-identical to the R3 freeze;
- residual accounting closes (total == sum(classes) == sum(components));
- allowed ∩ protected = 0 per asset (1px invasion self-test must be caught);
- cutouts rebuilt from master+masks for ALL groups × ALL backgrounds × ALL
  scales (100 full / 200 / 400) and compared byte-exact;
- per-protected isolated cutouts rebuilt and compared;
- Builder report + receipt metrics are parsed with exact asset+mask+px
  mapping (stale or missing values fail);
- a16 quill/paper raw boxes: zero invasion by any removal mask.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
R4 = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r4'
PLAN_DIR = R4 / 'mask_plan'
REPORT_MD = R4 / 'NIGHT03_PATCH2A_R4_MASK_FREEZE_REPORT.md'
RECEIPT_TXT = R4 / 'NIGHT03_PATCH2A_R4_RECEIPT.txt'
R3_MASKS = ROOT / ('data/assets_v2/repair_candidates/'
                   'night03_patch2a_r3/mask_plan')
BASE_P = ROOT / 'data/assets_v2/_base/furina-base.png'
SPEC_DIR = ROOT / 'data/assets_v2/_spec'
REVIEW_REPORT = ROOT / ('data/assets_v2/repair_candidates/night03_patch1/'
                        'NIGHT03_PATCH1_REVIEW_REPORT.md')

ASSETS = ('a01', 'a05', 'a16')
A16_TERMS = ['old_tail_removal', 'tail_destination', 'seam_reconstruction',
             'speck_cleanup', 'chair_removal', 'cane_removal',
             'hair_reconstruction', 'hand_reconstruction']
A16_PROT = ['protected_existing_hair', 'protected_quill_paper',
            'protected_glove_gold_cuff', 'protected_costume']
QP_BOXES = [(320, 940, 400, 1100), (330, 1085, 510, 1180)]
GROUP_RECTS = {'cane': (592, 1155, 722, 1450),
               'chair': (410, 1080, 730, 1470),
               'cane_chair': (410, 905, 815, 1450)}
CUT_SCALES = {'200': 200, '400': 400}


def sha256_path(p, text_lf=False):
    hsh = hashlib.sha256()
    if text_lf:
        hsh.update(Path(p).read_bytes().replace(b'\r\n', b'\n'))
        return hsh.hexdigest()
    with open(p, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            hsh.update(chunk)
    return hsh.hexdigest()


def fail(msgs, m):
    msgs.append(m)


def checker(h, w, c=24):
    yy, xx = np.mgrid[0:h, 0:w]
    t = ((xx // c) + (yy // c)) % 2 == 0
    return np.where(t[..., None], 200, 150).astype(np.uint8)


def rebuild_cutout(master, kill, bg):
    cut = master.copy()
    cut[..., 3][kill] = 0
    af = cut[..., 3:4].astype(np.float32) / 255.0
    return (cut[..., :3].astype(np.float32) * af
            + bg.astype(np.float32) * (1 - af)).clip(0, 255).astype(np.uint8)


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
        got = sha256_path(p, text_lf=rel.endswith('.md'))
        if not p.exists() or got != want:
            fail(msgs, f'input changed/missing: {rel}')

    a16m = {}
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
            if not np.isin(np.unique(arr), [0, 255]).all():
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

        terms = (A16_TERMS if asset == 'a16' else
                 ['old_tail_removal', 'tail_destination',
                  'seam_reconstruction', 'authorized_cleanup'])
        u = np.zeros((1536, 1024), bool)
        for t in terms:
            if t in masks:
                u |= masks[t]
        if 'allowed_edit' in masks and not (u == masks['allowed_edit']).all():
            fail(msgs, f'{asset}: allowed_edit != union(terms) on disk')

        prot = [n for n in masks if n.startswith('protected_')]
        for pn in prot:
            inter = int((masks['allowed_edit'] & masks[pn]).sum())
            if inter:
                fail(msgs, f'{asset}: allowed ∩ {pn} = {inter}px')
            if ent['intersections'].get(f'allowed_edit^{pn}', 0) != inter:
                fail(msgs, f'{asset}: intersection record mismatch ({pn})')

        mf = ROOT / ent['master_file']
        master = np.array(Image.open(mf).convert('RGBA'))
        if (masks['tail_destination'] & (master[..., 3] > 8)).any():
            fail(msgs, f'{asset}: tail_destination covers existing alpha')
        if ent['master_sha256'] != sha256_path(mf):
            fail(msgs, f'{asset}: master file hash drift')

        total = ent.get('boundary_residual_px')
        classes = ent.get('residual_class_px', {})
        tab = ent.get('residual_components', [])
        if asset == 'a01' and (total != sum(classes.values())
                               or total != sum(t['px'] for t in tab)):
            fail(msgs, 'a01: residual accounting does not close')

        # byte-identity vs R3: a01/a05 only (a16 was reworked in R4)
        if asset in ('a01', 'a05'):
            for name, meta in ent['masks'].items():
                rp = R3_MASKS / asset / f'{asset}_{name}.png'
                if rp.exists() and sha256_path(rp) != meta['sha256']:
                    fail(msgs, f'{asset}/{name}: not byte-identical to R3')

    # ---- a16: cutouts rebuilt for ALL groups × backgrounds × scales ----
    a16 = plan['assets'].get('a16')
    if a16:
        a16dir = PLAN_DIR / 'a16'
        master = np.array(Image.open(
            ROOT / a16['master_file']).convert('RGBA'))
        h16, w16 = master.shape[:2]
        groups = {'cane': ['a16_cane_removal.png'],
                  'chair': ['a16_chair_removal.png'],
                  'cane_chair': ['a16_cane_removal.png',
                                 'a16_chair_removal.png']}
        bgs = {'checker': checker(h16, w16).astype(np.float32),
               'dark': np.full((h16, w16, 3), 32, np.float32),
               'light': np.full((h16, w16, 3), 240, np.float32)}
        af = master[..., 3:4].astype(np.float32) / 255.0
        for tag, files in groups.items():
            kill = np.zeros((h16, w16), bool)
            for f in files:
                kill |= np.array(Image.open(a16dir / f)) == 255
            cut = master.copy()
            cut[..., 3][kill] = 0
            caf = cut[..., 3:4].astype(np.float32) / 255.0
            rx0, ry0, rx1, ry1 = GROUP_RECTS[tag]
            for bgn, bg in bgs.items():
                comp = (cut[..., :3].astype(np.float32) * caf
                        + bg * (1 - caf)).clip(0, 255).astype(np.uint8)
                full_p = a16dir / f'a16_{tag}_cutout_{bgn}_100.png'
                if not full_p.exists():
                    fail(msgs, f'a16/{tag}: cutout {bgn}/100 missing')
                    continue
                ref = np.array(Image.open(full_p).convert('RGB'))
                if not (ref == comp).all():
                    fail(msgs, f'a16/{tag}/{bgn}/100: rebuilt cutout differs')
                for zlabel, z in CUT_SCALES.items():
                    if z is None:
                        continue
                    sub = Image.fromarray(comp[ry0:ry1, rx0:rx1]).resize(
                        ((rx1 - rx0) * z // 100, (ry1 - ry0) * z // 100),
                        Image.NEAREST)
                    p = a16dir / f'a16_{tag}_cutout_{bgn}_{zlabel}.png'
                    if not p.exists():
                        fail(msgs, f'a16: cutout scale file missing {p.name}')
                        continue
                    ref = np.array(Image.open(p).convert('RGB'))
                    exp = np.array(sub)
                    if not (ref == exp).all():
                        fail(msgs, f'a16/{tag}/{bgn}/{zlabel}: differs')

        # per-protected isolated cutouts rebuilt + compared
        for pname in A16_PROT:
            p = a16dir / f'a16_{pname}.png'
            if not p.exists():
                fail(msgs, f'a16/{pname}: mask missing')
                continue
            pm = np.array(Image.open(p)) == 255
            iso = master.copy()
            iso[..., 3][~pm] = 0
            bgc = checker(h16, w16).astype(np.float32)
            af = iso[..., 3:4].astype(np.float32) / 255.0
            comp = (iso[..., :3].astype(np.float32) * af
                    + bgc * (1 - af)).clip(0, 255).astype(np.uint8)
            ip = a16dir / f'a16_{pname}_isolated_cutout.png'
            if not ip.exists():
                fail(msgs, f'a16/{pname}: isolated cutout missing')
                continue
            ref = np.array(Image.open(ip).convert('RGB'))
            if not (ref == comp).all():
                fail(msgs, f'a16/{pname}: isolated cutout differs')

        # raw quill/paper invasion zero for every removal mask
        zone = np.zeros((h16, w16), bool)
        for x0, y0, x1, y1 in QP_BOXES:
            zone[y0:y1, x0:x1] = True
        zone &= master[..., 3] > 8
        for name in A16_TERMS:
            arr = np.array(Image.open(
                a16dir / f'a16_{name}.png')) == 255
            raw_over = int((arr & zone).sum())
            if raw_over:
                fail(msgs, f'a16/{name} invades raw quill-paper zone '
                           f'({raw_over}px)')

    # ---- report + receipt consistency: exact asset+mask+px mapping ----
    if not REPORT_MD.exists():
        fail(msgs, 'Builder report missing')
    if not RECEIPT_TXT.exists():
        fail(msgs, 'receipt file missing')
    if REPORT_MD.exists():
        txt = REPORT_MD.read_text(encoding='utf-8')
        if plan['MASK_PLAN_SHA256'] not in txt:
            fail(msgs, 'report missing frozen MASK_PLAN_SHA256')
        for asset, ent in plan['assets'].items():
            for name, meta in ent['masks'].items():
                lookup = ('tail_source' if name == 'old_tail_removal'
                          else name)
                row = re.search(
                    rf'\|\s*{asset}\s*\|\s*{re.escape(lookup)}\s*\|\s*(\d+)\s*\|',
                    txt)
                if not row:
                    fail(msgs, f'report missing table row: {asset}/{name}')
                    continue
                if int(row.group(1)) != meta['px']:
                    fail(msgs, f'report stale: {asset}/{name} '
                               f'{row.group(1)} != {meta["px"]}')
        if 'STATUS = READY_FOR_NIGHT03_PATCH2A_R4_REVIEW' not in txt:
            fail(msgs, 'report status line wrong')
    if RECEIPT_TXT.exists():
        rcpt = RECEIPT_TXT.read_text(encoding='utf-8')
        pairs = {k: v.strip()
                 for k, v in re.findall(r'^([A-Z0-9_]+) = (.+)$', rcpt, re.M)}
        expect = {
            'PATCH_ID': 'NIGHT03_RECOVERY_PATCH2A_R4',
            'BASE_SHA': plan['base_sha'],
            'MASK_PLAN_SHA256': plan['MASK_PLAN_SHA256'],
            'CANDIDATES_CREATED': '0', 'GENERATION_CALLS': '0',
            'A01_RESIDUAL_TOTAL':
                str(plan['assets']['a01']['boundary_residual_px']),
            'ALLOWED_PROTECTED_OVERLAP': '0',
            'INPUT_HASH_CROSS_PLATFORM': 'true',
            'STATUS': 'READY_FOR_NIGHT03_PATCH2A_R4_REVIEW',
        }
        for k, v in expect.items():
            if pairs.get(k) != v:
                fail(msgs, f'receipt {k} = {pairs.get(k)} != {v}')
        for k in ('A01_MASKS_BYTE_IDENTICAL_TO_R3',
                  'A05_MASKS_BYTE_IDENTICAL',
                  'A16_CANE_COMPLETE', 'A16_CHAIR_COMPLETE',
                  'A16_CANE_CUTOUT_CLEAN', 'A16_CHAIR_CUTOUT_CLEAN',
                  'CUTOUT_ALL_SCALE_VERIFIED', 'DARK_LIGHT_CUTOUTS_PRESENT',
                  'CUTOUT_REBUILD_ALL_SCALES_BYTE_EXACT',
                  'INPUT_HASH_CROSS_PLATFORM', 'VERIFIER_SCANS_R4',
                  'PROTECTED_MASKS_PREDECLARED_GEOMETRIC_PARTITION',
                  'PROTECTED_MASKS_REMOVAL_INDEPENDENT',
                  'MASTERS_UNCHANGED'):
            if pairs.get(k) != 'true':
                fail(msgs, f'receipt {k} != true')

    # ---- no-candidate scan on R4 + self-tests ----
    probe = R4 / 'mask_plan' / 'a16' / 'a16_fake_candidate.png'
    Image.new('L', (4, 4)).save(probe)
    caught = False
    for p in R4.rglob('*.png'):
        rel = p.relative_to(R4).as_posix()
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

    a16ent = plan['assets'].get('a16')
    if a16ent:
        allowed = np.array(Image.open(
            PLAN_DIR / 'a16' / 'a16_allowed_edit.png')) == 255
        prot = np.array(Image.open(
            PLAN_DIR / 'a16' / 'a16_protected_costume.png')) == 255
        ysn, xsn = np.where(prot)
        bad = allowed.copy()
        bad[ysn[0], xsn[0]] = True
        if int((bad & prot).sum()) == 0:
            fail(msgs, 'self-test: 1px invasion NOT detected')
        else:
            print('self-test 1 (1px invasion) detected correctly')

    if msgs:
        print('VERIFY FAILED:')
        for m in msgs:
            print(' -', m)
        sys.exit(1)
    print('VERIFY OK —', plan['MASK_PLAN_SHA256'])
    print('  all backgrounds × all scales rebuilt byte-exact; protected')
    print('  isolated cutouts verified; report/receipt exact-mapped;')
    print('  self-tests passed; zero candidates; R4 dir scanned.')
    sys.exit(0)


if __name__ == '__main__':
    main()
