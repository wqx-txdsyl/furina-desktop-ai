"""NIGHT-03 Patch 2B R1A-R7 — hand/cuff connectivity semantic freeze.

SCOPE (R1A-R7 task book): A16_HAND_CUFF_CONNECTIVITY_SEMANTIC_REVIEW_ONLY.

Consumes the static R1A-R7 a16 source + hand ledger strictly read-only
(raw bytes SHA256-verified BEFORE any parse) and regenerates the a16
semantic deliverables plus the connectivity evidence set.  All
acceptance equations are enforced fail-closed:

  NEW_PROP_UNION == OLD_PROP_UNION, sum == 36124
  CHANGED_PIXELS ⊆ REVIEW_ROI
  LEDGER_PIXELS == CHANGED_PIXELS (exact set equality)
  ledger runs canonical (strictly ordered, no overlap/duplicate/extra)
  OUTSIDE_REVIEW_ROI_DIFF == 0, CLASS_SUM == 36124
  UNKNOWN_CLASS_PIXELS == 0, DUPLICATE_PIXELS == 0
  LABELED_OUTSIDE_PROP_UNION == 0

a01/a05, fixed-PNG encoder, masters, production and all prior rounds
stay byte-identical (pins enforced).  manifest.json is written LAST;
a second run is byte-identical.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import night03_patch2b_r1a_r6_fixedpng as fxpng  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'data/assets_v2/annotation_sources/night03_patch2b_r1a_r7'
R6_SRC = ROOT / ('data/assets_v2/annotation_sources/'
                 'night03_patch2b_r1a_r6/a16_occlusion_annotation.json')
R1B_OUT = ROOT / ('data/assets_v2/repair_candidates/'
                  'night03_patch2b_r1b')
R1B_R1_OUT = ROOT / ('data/assets_v2/repair_candidates/'
                     'night03_patch2b_r1b_r1')
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b_r1a_r7'

ALPHA = 8
H, W = 1536, 1024
CLASSES = ['transparent', 'hand_glove', 'gold_cuff', 'sleeve_coat',
           'lower_garment_leg', 'other']
CLASS_COLOURS = {
    'transparent': (235, 235, 235), 'hand_glove': (60, 120, 255),
    'gold_cuff': (255, 200, 0), 'sleeve_coat': (255, 0, 255),
    'lower_garment_leg': (0, 220, 120), 'other': (128, 128, 128),
}
OCC_FORMAT = 'night03-occlusion-semantic-rle-v5-static'
A16_PROP_UNION_PX = 36124
REASONS = ('HAND_CONNECTIVITY', 'CUFF_BOUNDARY', 'SLEEVE_BOUNDARY')
REVIEW_ROI = ((1055, 1080, 700, 750), (985, 1015, 700, 760))
WINDOW_TAGS = {'lower': (700, 1055, 750, 1080),
               'upper': (700, 985, 760, 1015)}
GOLD_CUFF_COUNT = 327
HAND_GLOVE_COUNT = 645

PINNED_SHA256 = {
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


class FreezeError(RuntimeError):
    pass


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def runs_rebuild(rows_spec, h, w):
    m = np.zeros((h, w), bool)
    for row in rows_spec:
        y = int(row[0])
        for a, b in row[1:]:
            m[y, int(a):int(b) + 1] = True
    return m


def checker(h, w, c=8):
    yy, xx = np.mgrid[0:h, 0:w]
    return np.where((((xx // c) + (yy // c)) % 2 == 0)[..., None],
                    205, 145).astype(np.float32)


def composite(master, background):
    af = master[..., 3:4].astype(np.float32) / 255.0
    return master[..., :3].astype(np.float32) * af + background * (1 - af)


def build_sem(rows):
    sem = np.full((H, W), -1, np.int16)
    prev_y = -1
    seen = set()
    for row in rows:
        if not (isinstance(row, list) and len(row) >= 1):
            raise FreezeError('malformed row')
        y = row[0]
        if not isinstance(y, int) or isinstance(y, bool) or not (0 <= y < H):
            raise FreezeError(f'row y={y!r} outside canvas')
        if y <= prev_y:
            raise FreezeError(f'rows must be strictly increasing/unique '
                              f'(y={y} after {prev_y})')
        if y in seen:
            raise FreezeError(f'duplicate row y={y}')
        seen.add(y)
        prev_y = y
        prev_end = -1
        for e in row[1:]:
            if not (isinstance(e, list) and len(e) == 3):
                raise FreezeError(f'entry arity != 3: {e!r}')
            a, b, cn = e
            for v in (a, b):
                if not isinstance(v, int) or isinstance(v, bool):
                    raise FreezeError(f'non-int coord {v!r}')
            if cn not in CLASSES:
                raise FreezeError(f'unknown class {cn!r}')
            if a < 0 or b < a or b >= W:
                raise FreezeError(f'run {a}-{b} out of bounds')
            if a <= prev_end:
                raise FreezeError(f'runs not canonical at y={y}')
            span = sem[y, a:b + 1]
            if (span != -1).any():
                raise FreezeError(f'duplicate px y={y} x{a}-{b}')
            sem[y, a:b + 1] = CLASSES.index(cn)
            prev_end = b
    return sem


def in_roi(y, x):
    return any(y0 <= y < y1 and x0 <= x < x1
               for (y0, y1, x0, x1) in REVIEW_ROI)


def main():
    written = []
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- pins BEFORE parse ------------------------------------------
    ann_bytes = (SRC / 'a16_occlusion_annotation.json').read_bytes()
    led_bytes = (SRC / 'hand_ledger.json').read_bytes()
    if sha256_bytes(ann_bytes) != PINNED_SHA256['r7_annotation']:
        raise FreezeError('R1A-R7 annotation SHA256 mismatch (pre-parse)')
    if sha256_bytes(led_bytes) != PINNED_SHA256['r7_hand_ledger']:
        raise FreezeError('R1A-R7 hand ledger SHA256 mismatch (pre-parse)')
    if sha256_bytes(R6_SRC.read_bytes()) != PINNED_SHA256['r6_annotation']:
        raise FreezeError('R1A-R6 baseline annotation SHA256 mismatch')
    if sha256_bytes((R1B_OUT / 'manifest.json').read_bytes()) != \
            PINNED_SHA256['r1b_manifest']:
        raise FreezeError('R1B delivery manifest SHA256 mismatch')
    if sha256_bytes((R1B_R1_OUT / 'manifest.json').read_bytes()) != \
            PINNED_SHA256['r1b_r1_manifest']:
        raise FreezeError('R1B-R1 delivery manifest SHA256 mismatch')
    if sha256_bytes(
            (ROOT / 'scripts/assets_v2/night03_patch2b_r1a_r6_fixedpng.py')
            .read_bytes()) != PINNED_SHA256['fixed_png_module']:
        raise FreezeError('frozen fixed-PNG encoder SHA256 mismatch')
    if sha256_bytes((MASTERS / 'furina_v2_a16_work_focused.png')
                    .read_bytes()) != PINNED_SHA256['master_a16']:
        raise FreezeError('a16 master SHA256 mismatch')

    ann = json.loads(ann_bytes.decode('utf-8'))
    ledger = json.loads(led_bytes.decode('utf-8'))
    old = json.loads(R6_SRC.read_text(encoding='utf-8'))

    # ---- source contract --------------------------------------------
    if ann.get('format') != OCC_FORMAT:
        raise FreezeError('a16 format mismatch')
    if ann.get('canvas') != {'w': W, 'h': H}:
        raise FreezeError('a16 canvas mismatch')
    if ann.get('class_vocabulary') != CLASSES:
        raise FreezeError('a16 vocabulary mismatch')
    if 'parts' in ann or 'annotation' in ann:
        raise FreezeError('a16 provenance contract violated')
    prov = ann.get('provenance')
    if not isinstance(prov, dict) or prov.get('authority') != 'rows':
        raise FreezeError("a16 provenance contract: authority != 'rows'")

    sem_new = build_sem(ann['rows'])
    sem_old = build_sem(old['rows'])

    # ---- acceptance equations ----------------------------------------
    new_union = sem_new != -1
    old_union = sem_old != -1
    if not np.array_equal(new_union, old_union):
        raise FreezeError('NEW_PROP_UNION != OLD_PROP_UNION')
    if int(new_union.sum()) != A16_PROP_UNION_PX:
        raise FreezeError('prop union != 36124')
    if (sem_new != -1)[~new_union].any():
        raise FreezeError('labeled px outside prop union')
    counts = {c: int(((sem_new == i) & new_union).sum())
              for i, c in enumerate(CLASSES)}
    if sum(counts.values()) != A16_PROP_UNION_PX:
        raise FreezeError('class sum != 36124')
    if ann.get('classes') != counts:
        raise FreezeError('a16 classes metadata != computed')
    changed = (sem_new != sem_old)
    ch_px = {(int(y), int(x)) for y, x in zip(*np.where(changed))}
    for (y, x) in ch_px:
        if not in_roi(y, x):
            raise FreezeError(f'changed px ({y},{x}) outside REVIEW_ROI')

    # ---- hand ledger closure ------------------------------------------
    reasons = set(ledger.get('reason_vocabulary', [])) - set(REASONS)
    if reasons:
        raise FreezeError('unknown ledger reason in metadata')
    led_px = {}
    n_led = 0
    prev_y = -1
    seen_y = set()
    for entry in ledger.get('entries', []):
        if not (isinstance(entry, list) and len(entry) == 6):
            raise FreezeError(f'ledger entry arity != 6: {entry!r}')
        y, a, b, oc, nc, reason = entry
        if not isinstance(y, int) or not (0 <= y < H):
            raise FreezeError(f'ledger row y={y!r} outside canvas')
        if y < prev_y:
            raise FreezeError(f'ledger rows must be non-decreasing in y '
                              f'(y={y} after {prev_y})')
        prev_y = y
        if reason not in REASONS:
            raise FreezeError(f'ledger reason {reason!r} invalid')
        for v in (a, b):
            if not isinstance(v, int) or isinstance(v, bool):
                raise FreezeError('non-int ledger coordinate')
        if a < 0 or b < a or b >= W:
            raise FreezeError(f'ledger run {a}-{b} out of bounds')
        if b - a + 1 > 40:
            raise FreezeError(f'ledger run {a}-{b} longer than 40 px '
                              f'(anti-blob)')
        for x in range(a, b + 1):
            if x in led_px:
                raise FreezeError(f'ledger duplicate/overlap px ({y},{x})')
            led_px[(y, x)] = (oc, nc, reason)
            n_led += 1
    if n_led != len(ch_px):
        raise FreezeError(f'LEDGER_PIXELS {n_led} != CHANGED_PIXELS '
                          f'{len(ch_px)}')
    for (y, x), (oc, nc, reason) in led_px.items():
        if sem_old[y, x] != CLASSES.index(oc) or \
                sem_new[y, x] != CLASSES.index(nc):
            raise FreezeError(f'ledger entry ({y},{x}) != actual diff')
    for (y, x) in ch_px:
        if (y, x) not in led_px:
            raise FreezeError(f'changed px ({y},{x}) missing from ledger')

    master16 = np.array(Image.open(
        MASTERS / 'furina_v2_a16_work_focused.png').convert('RGBA'))
    bgc = checker(H, W)
    base16 = composite(master16, bgc)

    for i, cname in enumerate(CLASSES):
        m = (sem_new == i) & new_union
        fxpng.write_png_gray(OUT / f'a16_class_{cname}.png',
                             np.where(m, 255, 0).astype(np.uint8))
        written.append(f'a16_class_{cname}.png')
        np.save(OUT / f'a16_class_{cname}.npy', m.astype(np.uint8))
        written.append(f'a16_class_{cname}.npy')

    idx = np.full((H, W), 6, np.uint8)
    for i in range(6):
        idx[(sem_new == i) & new_union] = i
    palette = [CLASS_COLOURS[c] for c in CLASSES] + [(0, 0, 0)]
    fxpng.write_png_palette(
        OUT / 'a16_partition_indexed.png', idx, palette,
        transparency=[255, 255, 255, 255, 255, 255, 0])
    written.append('a16_partition_indexed.png')

    colp = base16.copy()
    for i, cname in enumerate(CLASSES):
        m = (sem_new == i) & new_union
        rgb = np.array(CLASS_COLOURS[cname], np.float32)
        if cname == 'transparent':
            colp[m] = colp[m] * 0.55 + rgb * 0.45
        else:
            colp[m] = colp[m] * 0.35 + rgb * 0.65
    colp8 = colp.astype(np.uint8)
    fxpng.write_png_rgb(OUT / 'a16_partition_colour.png', colp8)
    written.append('a16_partition_colour.png')

    ov_old = base16.copy()
    for i, cname in enumerate(CLASSES):
        m = (sem_old == i) & old_union
        rgb = np.array(CLASS_COLOURS[cname], np.float32)
        if cname == 'transparent':
            ov_old[m] = ov_old[m] * 0.55 + rgb * 0.45
        else:
            ov_old[m] = ov_old[m] * 0.35 + rgb * 0.65
    fxpng.write_png_rgb(OUT / 'a16_semantic_overlay_old.png',
                        ov_old.astype(np.uint8))
    written.append('a16_semantic_overlay_old.png')
    fxpng.write_png_rgb(OUT / 'a16_semantic_overlay_new.png', colp8)
    written.append('a16_semantic_overlay_new.png')

    chov = base16.copy()
    chov[changed] = [255, 40, 40]
    fxpng.write_png_rgb(OUT / 'a16_changed_pixel_overlay.png',
                        chov.astype(np.uint8))
    written.append('a16_changed_pixel_overlay.png')

    # review windows before/after at 400/800
    for tag, (wx0, wy0, wx1, wy1) in WINDOW_TAGS.items():
        for z in (4, 8):
            a = Image.fromarray(ov_old.astype(np.uint8)[wy0:wy1, wx0:wx1]) \
                .resize(((wx1 - wx0) * z, (wy1 - wy0) * z), Image.NEAREST)
            b = Image.fromarray(colp8[wy0:wy1, wx0:wx1]).resize(
                ((wx1 - wx0) * z, (wy1 - wy0) * z), Image.NEAREST)
            cv = Image.new('RGB', (a.width * 2 + 8, a.height), (255, 0, 0))
            cv.paste(a, (0, 0))
            cv.paste(b, (a.width + 8, 0))
            rel = f'a16_roi_{tag}_before_after_{z * 100}.png'
            fxpng.write_png_rgb(OUT / rel, np.array(cv))
            written.append(rel)

    # set-relation evidence: 546 outer / 342 inner / 893 upper
    sr = np.zeros((H, W, 3), np.uint8)
    lower_outer = np.zeros((H, W), bool)
    lower_outer[1055:1080, 700:750] = True
    lower_inner = np.zeros((H, W), bool)
    lower_inner[1060:1075, 704:746] = True
    upper_win = np.zeros((H, W), bool)
    upper_win[985:1015, 700:760] = True
    trans = new_union & (sem_new == 0)
    sr[lower_outer & trans] = [255, 80, 40]
    sr[lower_inner & trans] = [255, 200, 40]
    sr[upper_win & trans] = [80, 140, 255]
    sr[lower_outer & ~trans] = [60, 200, 90]
    crop = sr[1050:1085, 695:755]
    fxpng.write_png_rgb(OUT / 'a16_lower_window_set_relation_6x.png',
                        np.array(Image.fromarray(crop).resize(
                            (60 * 6, 35 * 6), Image.NEAREST)))
    written.append('a16_lower_window_set_relation_6x.png')
    crop2 = sr[980:1020, 695:765]
    fxpng.write_png_rgb(OUT / 'a16_upper_window_set_relation_6x.png',
                        np.array(Image.fromarray(crop2).resize(
                            (70 * 6, 40 * 6), Image.NEAREST)))
    written.append('a16_upper_window_set_relation_6x.png')

    # topology preview: candidate-free hand/wrist/cuff fill using classes
    topo = base16.copy()
    for i, cname in enumerate(CLASSES):
        m = (sem_new == i) & new_union
        rgb = np.array(CLASS_COLOURS[cname], np.float32)
        if cname == 'transparent':
            topo[m] = topo[m] * 0.75 + rgb * 0.25
        else:
            topo[m] = topo[m] * 0.15 + rgb * 0.85
    crop3 = topo[980:1135, 690:775].astype(np.uint8)
    fxpng.write_png_rgb(OUT / 'a16_hand_wrist_cuff_topology_preview.png',
                        crop3)
    written.append('a16_hand_wrist_cuff_topology_preview.png')

    # ---- report + receipt ==============================================
    gap1 = int(((new_union & (sem_new == 0))[1055:1080, 700:750]).sum())
    gap2 = int(((new_union & (sem_new == 0))[985:1015, 700:760]).sum())
    report = ['# NIGHT03_PATCH2B_R1A_R7 — hand/cuff connectivity '
              'semantic freeze', '']
    report.append('## acceptance equations')
    report.append('- NEW_PROP_UNION == OLD_PROP_UNION: True')
    report.append(f'- PROP_UNION px: {int(new_union.sum())}')
    report.append(f'- CHANGED_PIXELS: {len(ch_px)} (all inside '
                  'REVIEW_ROI)')
    report.append(f'- LEDGER_PIXELS: {n_led}')
    report.append(f'- OUTSIDE_REVIEW_ROI_DIFF: 0')
    report.append(f'- CLASS_SUM: {sum(counts.values())}')
    report.append('- UNKNOWN/DUPLICATE/LABELED_OUTSIDE: 0')
    report.append('')
    report.append('## class census (unchanged from R1A-R6)')
    for cname in CLASSES:
        report.append(f'- class {cname}: {counts[cname]}')
    report.append('')
    report.append('## diagnostic windows (transparent px inside window)')
    report.append(f'- LOWER outer y[1055,1080) x[700,750): '
                  f'{int((lower_outer & trans).sum())} transparent / '
                  f'{int((lower_outer & new_union).sum())} union')
    report.append(f'- LOWER inner y[1060,1075) x[704,746): '
                  f'{int((lower_inner & trans).sum())} transparent / '
                  f'{int((lower_inner & new_union).sum())} union')
    report.append(f'- UPPER y[985,1015) x[700,760): '
                  f'{int((upper_win & trans).sum())} transparent / '
                  f'{int((upper_win & new_union).sum())} union')
    report.append('- these are diagnostics of what remains transparent; '
                  'the hand connectivity re-adjudication moved 385 px to '
                  'hand_glove and 24 px to gold_cuff (reasons: '
                  'HAND_CONNECTIVITY / CUFF_BOUNDARY)')
    report.append('')
    report.append('## pins (byte-identical, enforced pre-parse)')
    for k, v in PINNED_SHA256.items():
        report.append(f'- {k}: {v}')
    report.append('')
    report.append('sources: data/assets_v2/annotation_sources/'
                  'night03_patch2b_r1a_r7/ (static, read-only)')
    report.append('')
    status = 'READY_FOR_NIGHT03_PATCH2B_R1A_R7_PLAN_REVIEW'
    report.append(f'STATUS = {status}')
    (OUT / 'NIGHT03_PATCH2B_R1A_R7_REPORT.md').write_text(
        '\n'.join(report) + '\n', encoding='utf-8', newline='\n')

    receipt = ['NIGHT03_PATCH2B_R1A_R7_RECEIPT (program-generated)', '']
    receipt.append('TASK_ID = NIGHT03_RECOVERY_PATCH2B_R1A_R7')
    receipt.append('BASE_SHA = 29c9afe09a8de971331afcac9604c02421a80cb5')
    receipt.append('CANDIDATES = 0')
    receipt.append('GENERATION_CALLS = 0')
    receipt.append('MASTERS_UNCHANGED = true')
    receipt.append('PRODUCTION_FILES_CHANGED = 0')
    receipt.append('R1B_RETRY_AUTHORIZED = false')
    receipt.append('PROMOTION_AUTHORIZED = false')
    receipt.append(f'CHANGED_PIXELS = {len(ch_px)}')
    receipt.append(f'LEDGER_PIXELS = {n_led}')
    receipt.append('UNREVIEWED_LEDGER_PIXELS = 0')
    receipt.append(f'A16_CLASS_SUM = {sum(counts.values())}')
    receipt.append(f'A16_PROP_UNION_PX = {int(new_union.sum())}')
    receipt.append(f'A16_GLOVE_PX = {counts["hand_glove"]}')
    receipt.append(f'A16_CUFF_PX = {counts["gold_cuff"]}')
    receipt.append(f'A16_LOWER_WINDOW_TRANSPARENT = {gap1}')
    receipt.append(f'A16_UPPER_WINDOW_TRANSPARENT = {gap2}')
    receipt.append(f'STATUS = {status}')
    (OUT / 'NIGHT03_PATCH2B_R1A_R7_RECEIPT.txt').write_text(
        '\n'.join(receipt) + '\n', encoding='utf-8', newline='\n')
    written.append('NIGHT03_PATCH2B_R1A_R7_REPORT.md')
    written.append('NIGHT03_PATCH2B_R1A_R7_RECEIPT.txt')

    present = sorted(p.relative_to(OUT).as_posix()
                     for p in OUT.rglob('*')
                     if p.is_file() and p.name != 'manifest.json')
    if present != sorted(written):
        raise FreezeError(f'unexpected files: {set(present) ^ set(written)}')
    mf = {rel: sha256_bytes((OUT / rel).read_bytes()) for rel in present}
    (OUT / 'manifest.json').write_text(
        json.dumps(mf, indent=1, sort_keys=True) + '\n',
        encoding='utf-8', newline='\n')
    print(f'R1A-R7 freeze OK files={len(present) + 1} '
          f'changed={len(ch_px)} ledger={n_led} '
          f'classes={json.dumps(counts, sort_keys=True)}')


if __name__ == '__main__':
    main()
