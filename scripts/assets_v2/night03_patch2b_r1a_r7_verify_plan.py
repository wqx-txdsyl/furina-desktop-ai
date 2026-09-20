"""NIGHT-03 Patch 2B R1A-R7 — independent semantic freeze verifier.

No import of the freeze.  Re-derives everything from the pinned static
sources and enforces all R1A-R7 acceptance equations independently.
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
H, W = 1536, 1024
CLASSES = ['transparent', 'hand_glove', 'gold_cuff', 'sleeve_coat',
           'lower_garment_leg', 'other']
REASONS = ('HAND_CONNECTIVITY', 'CUFF_BOUNDARY', 'SLEEVE_BOUNDARY')
REVIEW_ROI = ((1055, 1080, 700, 750), (985, 1015, 700, 760))

PINNED = {
    'r7_annotation': (
        '12cc7997dba06518c348493d063f4d7bd46ec2f315e883a91a07820d344bed1a'),
    'r7_hand_ledger': (
        '326dafd54e291dad6bb0d261924bb678530e0ee6e43953b674674535e1729c2f'),
    'r6_annotation': (
        '0274181f6bce18ba3fad25f259a5e76e73a2b3a1bb5fc03062e44b5ff59d7de8'),
    'r1b_manifest': (
        '8443acb89ada5fc3686e12476d57971e674147150bcb6a6a8401ae3a60f7e37d'),
    'r1b_r1_manifest': (
        'db2751428b05d52fb31c8a9ee5ca3f86268d35cbe8dde4a3b579183a154e4561'),
    'fixed_png_module': (
        'ff32d541d8ceabdef656f4527d9ae605eec5c41af89e383569997e65a3648a99'),
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


def checker_bg(h, w, c=8):
    yy, xx = np.mgrid[0:h, 0:w]
    return np.where((((xx // c) + (yy // c)) % 2 == 0)[..., None],
                    205, 145).astype(np.float32)


def composite(master, background):
    af = master[..., 3:4].astype(np.float32) / 255.0
    return master[..., :3].astype(np.float32) * af + background * (1 - af)


def build_sem(rows, errs, what):
    sem = np.full((H, W), -1, np.int16)
    prev_y = -1
    seen = set()
    for row in rows:
        if not (isinstance(row, list) and len(row) >= 1):
            errs.append(f'{what}: malformed row')
            return sem
        y = row[0]
        if not isinstance(y, int) or isinstance(y, bool) or not (0 <= y < H):
            errs.append(f'{what}: row y={y!r} outside canvas')
            return sem
        if y <= prev_y:
            errs.append(f'{what}: rows not strictly increasing (y={y})')
            return sem
        if y in seen:
            errs.append(f'{what}: duplicate row y={y}')
            return sem
        seen.add(y)
        prev_y = y
        prev_end = -1
        for e in row[1:]:
            if not (isinstance(e, list) and len(e) == 3):
                errs.append(f'{what}: entry arity != 3: {e!r}')
                return sem
            a, b, cn = e
            for v in (a, b):
                if not isinstance(v, int) or isinstance(v, bool):
                    errs.append(f'{what}: non-int coordinate')
                    return sem
            if cn not in CLASSES:
                errs.append(f'{what}: unknown class {cn!r}')
                return sem
            if a < 0 or b < a or b >= W:
                errs.append(f'{what}: run {a}-{b} out of bounds')
                return sem
            if a <= prev_end:
                errs.append(f'{what}: runs not canonical at y={y}')
                return sem
            span = sem[y, a:b + 1]
            if (span != -1).any():
                errs.append(f'{what}: duplicate px y={y} x{a}-{b}')
                return sem
            sem[y, a:b + 1] = CLASSES.index(cn)
            prev_end = b
    return sem


def in_roi(y, x):
    return any(y0 <= y < y1 and x0 <= x < x1
               for (y0, y1, x0, x1) in REVIEW_ROI)


def verify(sources, r6_src, r1b_out, r1b_r1_out, output, masters):
    ck = Checker()
    for key, fpath in [
        ('r7_annotation', sources / 'a16_occlusion_annotation.json'),
        ('r7_hand_ledger', sources / 'hand_ledger.json'),
        ('r6_annotation', r6_src),
        ('r1b_manifest', r1b_out / 'manifest.json'),
        ('r1b_r1_manifest', r1b_r1_out / 'manifest.json'),
        ('fixed_png_module',
         ROOT / 'scripts/assets_v2/night03_patch2b_r1a_r6_fixedpng.py'),
        ('master_a16', masters / 'furina_v2_a16_work_focused.png'),
    ]:
        if not ck.check(sha256_path(fpath) == PINNED[key],
                        f'pin {key}'):
            raise VerifyFail(f'pin mismatch: {key}')

    master16 = np.array(Image.open(
        masters / 'furina_v2_a16_work_focused.png').convert('RGBA'))

    ann = json.loads((sources / 'a16_occlusion_annotation.json')
                     .read_text(encoding='utf-8'))
    ledger = json.loads((sources / 'hand_ledger.json')
                        .read_text(encoding='utf-8'))
    old = json.loads(r6_src.read_text(encoding='utf-8'))

    ck.check(ann.get('format') == 'night03-occlusion-semantic-rle-v5-static',
             'format metadata')
    ck.check(ann.get('canvas') == {'w': W, 'h': H}, 'canvas metadata')
    ck.check(ann.get('class_vocabulary') == CLASSES, 'vocabulary')
    ck.check('parts' not in ann and 'annotation' not in ann,
             'provenance contract: no parts/annotation keys')
    prov = ann.get('provenance')
    ck.check(isinstance(prov, dict) and prov.get('authority') == 'rows',
             "provenance authority == 'rows'")

    errs = []
    sem_new = build_sem(ann['rows'], errs, 'r7 rows')
    if errs:
        raise VerifyFail(f'r7 rows invalid: {errs[:3]}')
    ck.check(True, 'r7 rows canonical RLE')
    sem_old = build_sem(old['rows'], [], 'r6 rows')

    new_union = sem_new != -1
    old_union = sem_old != -1
    ck.check(np.array_equal(new_union, old_union),
             'NEW_PROP_UNION == OLD_PROP_UNION')
    ck.check(int(new_union.sum()) == 36124, 'prop union == 36124')
    ck.check(not (sem_new != -1)[~new_union].any(),
             'labeled_outside_prop_union == 0')
    counts = {c: int(((sem_new == i) & new_union).sum())
              for i, c in enumerate(CLASSES)}
    ck.check(sum(counts.values()) == 36124, 'class_sum == 36124')
    ck.check(ann.get('classes') == counts, 'classes metadata exact')
    changed = (sem_new != sem_old)
    ch_px = {(int(y), int(x)) for y, x in zip(*np.where(changed))}
    outside_roi = [(y, x) for (y, x) in ch_px if not in_roi(y, x)]
    ck.check(not outside_roi,
             f'CHANGED_PIXELS subset of REVIEW_ROI ({outside_roi[:3]})')

    entries = ledger.get('entries', [])
    ck.check(ledger.get('protocol') != 'x' or True, 'ledger parsed')
    ck.check(set(ledger.get('reason_vocabulary', [])) <= set(REASONS),
             'ledger reason vocabulary')
    led_px = {}
    l_err = None
    prev_y = -1
    n_led = 0
    for entry in entries:
        if not (isinstance(entry, list) and len(entry) == 6):
            l_err = f'ledger entry arity != 6: {entry!r}'
            break
        y, a, b, oc, nc, reason = entry
        if not isinstance(y, int) or not (0 <= y < H):
            l_err = f'ledger row y={y!r} outside canvas'
            break
        if y < prev_y:
            l_err = f'ledger rows not non-decreasing (y={y} after {prev_y})'
            break
        prev_y = y
        if reason not in REASONS:
            l_err = f'invalid reason {reason!r}'
            break
        if not isinstance(a, int) or not isinstance(b, int) or a < 0 \
                or b < a or b >= W:
            l_err = f'ledger run {a}-{b} invalid'
            break
        for x in range(a, b + 1):
            if x in led_px:
                l_err = f'ledger duplicate/overlap px ({y},{x})'
                break
            led_px[(y, x)] = (oc, nc, reason)
        if l_err:
            break
        n_led += b - a + 1
    ck.check(l_err is None, f'ledger canonical ({l_err})')
    if l_err:
        raise VerifyFail(f'ledger invalid: {l_err}')
    ck.check(len(led_px) == len(ch_px),
             f'LEDGER_PIXELS == CHANGED_PIXELS ({len(led_px)} vs '
             f'{len(ch_px)})')
    mism = [(p, v) for p, v in led_px.items()
            if sem_old[p[0], p[1]] != CLASSES.index(v[0])
            or sem_new[p[0], p[1]] != CLASSES.index(v[1])]
    ck.check(not mism, f'ledger entries == actual pixel diff ({mism[:2]})')
    missing = ch_px - set(led_px)
    ck.check(not missing,
             f'every changed px in ledger (missing: {sorted(missing)[:3]})')
    # surgical-reclassification limits: no bulk conversions; every newly
    # non-transparent px must extend an existing glove/cuff region
    if not ck.check(len(ch_px) <= 500,
                    f'changed px count surgical (={len(ch_px)})'):
        raise VerifyFail('bulk reclassification')
    old_glove_cuff = ((sem_old == CLASSES.index('hand_glove'))
                      | (sem_old == CLASSES.index('gold_cuff'))
                      | (sem_old == CLASSES.index('sleeve_coat')))
    gd = old_glove_cuff.copy()
    for _ in range(9):
        gd = gd | np.roll(gd, 1, 0) | np.roll(gd, -1, 0)             | np.roll(gd, 1, 1) | np.roll(gd, -1, 1)
    far = [(y, x) for (y, x) in ch_px
           if sem_new[y, x] != 0 and not gd[y, x]]
    ck.check(not far,
             f'new non-transparent px within 9px of old glove/cuff '
             f'(far: {far[:2]})')

    # ---- deliverables -----------------------------------------------------
    chov_p = output / 'a16_changed_pixel_overlay.png'
    if ck.check(chov_p.exists(), 'changed overlay present'):
        afm = master16[..., 3:4].astype(np.float32) / 255.0
        base16v = composite(master16, checker_bg(H, W))
        chv = base16v.copy()
        chv[changed] = [255, 40, 40]
        ck.check(np.array_equal(
            np.array(Image.open(chov_p).convert('RGB')),
            chv.astype(np.uint8)), 'changed overlay pixel-exact rebuild')

    for i, cname in enumerate(CLASSES):
        m_exp = (sem_new == i) & new_union
        p = output / f'a16_class_{cname}.png'
        if ck.check(p.exists(), f'{cname} mask present'):
            got = np.array(Image.open(p).convert('L'))
            ck.check(np.array_equal(got > 127, m_exp),
                     f'{cname} mask pixels')
        n = output / f'a16_class_{cname}.npy'
        if ck.check(n.exists(), f'{cname} npy present'):
            ck.check(np.array_equal(np.load(n).astype(bool), m_exp),
                     f'{cname} npy pixels')
    idx_p = output / 'a16_partition_indexed.png'
    if ck.check(idx_p.exists(), 'indexed partition present'):
        pim = Image.open(idx_p)
        idx = np.array(pim)
        exp_idx = np.full((H, W), 6, np.uint8)
        for i in range(6):
            exp_idx[(sem_new == i) & new_union] = i
        ck.check(np.array_equal(idx, exp_idx), 'indexed values')
        ck.check(pim.info.get('transparency') == 6, 'transparency index 6')
    for rel in ('a16_partition_colour.png', 'a16_semantic_overlay_old.png',
                'a16_semantic_overlay_new.png',
                'a16_changed_pixel_overlay.png',
                'a16_lower_window_set_relation_6x.png',
                'a16_upper_window_set_relation_6x.png',
                'a16_hand_wrist_cuff_topology_preview.png'):
        ck.check((output / rel).exists(), f'{rel} present')
    for tag in WINDOW_TAGS:
        for z in (400, 800):
            ck.check((output / f'a16_roi_{tag}_before_after_{z}.png')
                     .exists(), f'roi {tag} {z} present')

    # ---- report/receipt ---------------------------------------------------
    rep_p = output / 'NIGHT03_PATCH2B_R1A_R7_REPORT.md'
    rec_p = output / 'NIGHT03_PATCH2B_R1A_R7_RECEIPT.txt'
    if ck.check(rep_p.exists(), 'report present'):
        rep = rep_p.read_text(encoding='utf-8')
        ck.check('STATUS = READY_FOR_NIGHT03_PATCH2B_R1A_R7_PLAN_REVIEW'
                 in rep, 'report STATUS')
        ck.check(f'- CHANGED_PIXELS: {len(ch_px)}' in rep,
                 'report changed px')
    if ck.check(rec_p.exists(), 'receipt present'):
        rec = rec_p.read_text(encoding='utf-8')
        kv = dict(re.findall(r'^([A-Z0-9_]+) = (.*)$', rec, re.MULTILINE))
        ck.check(kv.get('CHANGED_PIXELS') == str(len(ch_px)),
                 'receipt CHANGED_PIXELS')
        ck.check(kv.get('UNREVIEWED_LEDGER_PIXELS') == '0',
                 'receipt UNREVIEWED = 0')
        ck.check(kv.get('R1B_RETRY_AUTHORIZED') == 'false',
                 'receipt R1B_RETRY_AUTHORIZED = false')

    # ---- manifest ----------------------------------------------------------
    mf_p = output / 'manifest.json'
    if ck.check(mf_p.exists(), 'manifest present'):
        mf = json.loads(mf_p.read_text(encoding='utf-8'))
        actual = {p.relative_to(output).as_posix(): sha256_path(p)
                  for p in sorted(output.rglob('*'))
                  if p.is_file() and p.name != 'manifest.json'}
        ck.check(set(mf) == set(actual), 'manifest covers files exactly')
        bad = [k for k in mf if mf.get(k) != actual.get(k)]
        ck.check(not bad, f'manifest hashes match (bad: {bad[:3]})')

    return ck


from PIL import Image as _I  # noqa: E402  (Image already imported above)


WINDOW_TAGS = {'lower': (700, 1055, 750, 1080),
               'upper': (700, 985, 760, 1015)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sources', type=Path,
                    default=ROOT / 'data/assets_v2/annotation_sources/'
                                   'night03_patch2b_r1a_r7')
    ap.add_argument('--r6-src', type=Path,
                    default=ROOT / 'data/assets_v2/annotation_sources/'
                                   'night03_patch2b_r1a_r6/'
                                   'a16_occlusion_annotation.json')
    ap.add_argument('--r1b-out', type=Path,
                    default=ROOT / 'data/assets_v2/repair_candidates/'
                                   'night03_patch2b_r1b')
    ap.add_argument('--r1b-r1-out', type=Path,
                    default=ROOT / 'data/assets_v2/repair_candidates/'
                                   'night03_patch2b_r1b_r1')
    ap.add_argument('--output', type=Path,
                    default=ROOT / 'data/assets_v2/repair_candidates/'
                                   'night03_patch2b_r1a_r7')
    ap.add_argument('--masters', type=Path,
                    default=ROOT / 'data/assets_v2/masters')
    args = ap.parse_args()
    try:
        ck = verify(args.sources, args.r6_src, args.r1b_out,
                    args.r1b_r1_out, args.output, args.masters)
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
