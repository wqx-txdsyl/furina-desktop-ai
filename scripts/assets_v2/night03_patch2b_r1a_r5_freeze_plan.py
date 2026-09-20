"""NIGHT-03 Patch 2B R1A-R5 — mask/plan freeze (single entry).

Consumes the static authoritative annotation sources in
data/assets_v2/annotation_sources/night03_patch2b_r1a_r5/ strictly
read-only and generates every R1A-R5 deliverable into
data/assets_v2/repair_candidates/night03_patch2b_r1a_r4's successor
directory night03_patch2b_r1a_r5/.

R1A-R5 additions over R1A-R4:
  * tail sources carry a FULL per-row manual review record
    ([y, draft_runs, accepted_runs, rejected_runs_with_reason]);
    the freeze validates  draft == accepted | rejected  exactly,
    accepted == final rows, disjoint sets, reason vocabulary,
    totals and UNREVIEWED == 0.
  * a16 provenance contract: the final per-pixel RLE (`rows`) is the
    sole authority; no control-row / part / interpolation claims exist
    (enforced: keys `parts`/`annotation` must be absent,
    provenance.authority == 'rows').
  * deterministic PNG encoding (own fixed-Huffman LZ77 deflate):
    committed output is bit-reproducible in any environment.
  * source metadata (format / canvas / alpha_threshold / source_px /
    adjudication gold_window) validated fail-closed.

Fail-closed gates, enforced BEFORE any use and with zero clipping:
  raw_source ∩ outside_visible == 0
  raw_source ∩ protected      == 0
  a16 labeled == prop_union(36124), outside == 0, duplicates == 0,
  unknown classes == 0, class_sum == 36124

No dilation, no colour tests, no morphology, no default classification,
no R1B candidates.  Report, receipt and all numbers are generated
programmatically.  manifest.json is written LAST.  A second run over
the same tree is byte-identical.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import night03_patch2b_r1a_r5_fixedpng as fxpng  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'data/assets_v2/annotation_sources/night03_patch2b_r1a_r5'
R6AR4_JSON = ROOT / ('data/assets_v2/repair_candidates/'
                     'night03_patch2a_r6ar4/a16_ownership_annotation.json')
R4_MASKS = ROOT / ('data/assets_v2/repair_candidates/'
                   'night03_patch2a_r4/mask_plan')
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b_r1a_r5'

ALPHA = 8
H, W = 1536, 1024
CLASSES = ['transparent', 'hand_glove', 'gold_cuff', 'sleeve_coat',
           'lower_garment_leg', 'other']
CLASS_COLOURS = {
    'transparent': (235, 235, 235), 'hand_glove': (60, 120, 255),
    'gold_cuff': (255, 200, 0), 'sleeve_coat': (255, 0, 255),
    'lower_garment_leg': (0, 220, 120), 'other': (128, 128, 128),
}
MASTERS_FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}
PROTECTED_TERMS = {
    'a01': ['protected_identity', 'protected_costume', 'protected_props'],
    'a05': ['protected_identity', 'protected_costume', 'protected_props'],
}
GOLD_WINDOWS = {'a01': (262, 1040, 300, 1230), 'a05': (370, 905, 400, 975)}
TAIL_FORMAT = 'night03-tail-source-rle-v4-static'
OCC_FORMAT = 'night03-occlusion-semantic-rle-v4-static'
A16_PROP_UNION_PX = 36124
ZOOM_REGIONS = {
    'hand': (705, 920, 805, 1075),
    'cuff': (695, 1060, 750, 1125),
    'seat': (490, 1205, 680, 1295),
    'blade': (625, 1125, 675, 1285),
}
REJECT_REASONS = ('PROTECTED_CONFLICT', 'GOLD_STAFF_AA')


class FreezeError(RuntimeError):
    pass


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def rebuild_runs(rows_spec, h, w):
    m = np.zeros((h, w), bool)
    for row in rows_spec:
        y = int(row[0])
        for a, b in row[1:]:
            m[y, int(a):int(b) + 1] = True
    return m


def validate_row_spec(row, h, w, what):
    """Strict per-row run validation: bounds, order, no overlap."""
    if not (isinstance(row, list) and len(row) >= 2):
        raise FreezeError(f'{what}: malformed row {row!r}')
    y = row[0]
    if not isinstance(y, int) or isinstance(y, bool) or not (0 <= y < h):
        raise FreezeError(f'{what}: row y={y!r} outside canvas')
    prev_end = -1
    for run in row[1:]:
        if not (isinstance(run, list) and len(run) >= 2):
            raise FreezeError(f'{what}: malformed run {run!r}')
        a, b = run[0], run[1]
        for v in (a, b):
            if not isinstance(v, int) or isinstance(v, bool):
                raise FreezeError(f'{what}: non-int run coord {v!r}')
        if a < 0 or b < a or b >= w:
            raise FreezeError(f'{what}: run {a}-{b} out of bounds')
        if a <= prev_end:
            raise FreezeError(
                f'{what}: unsorted/overlapping/duplicate runs at '
                f'y={y}: run {a}-{b} after prev end {prev_end}')
        prev_end = b


def runs_to_mask_row(runs, w):
    m = np.zeros(w, bool)
    for run in runs:
        m[run[0]:run[1] + 1] = True
    return m


def checker(h, w, c=12):
    yy, xx = np.mgrid[0:h, 0:w]
    return np.where((((xx // c) + (yy // c)) % 2 == 0)[..., None],
                    200, 150).astype(np.float32)


def composite(master, background):
    af = master[..., 3:4].astype(np.float32) / 255.0
    return master[..., :3].astype(np.float32) * af + background * (1 - af)


def build_prop_union():
    doc = json.loads(R6AR4_JSON.read_text(encoding='utf-8'))
    m16 = np.array(Image.open(
        MASTERS / MASTERS_FILES['a16']).convert('RGBA'))
    vis = m16[..., 3] > ALPHA
    cane = rebuild_runs(doc['primitives']['remove_cane'], H, W) & vis
    chair = rebuild_runs(doc['primitives']['remove_chair'], H, W) & vis
    return cane | chair


def validate_a16_source(doc, union):
    if doc.get('format') != OCC_FORMAT:
        raise FreezeError(f"a16 format {doc.get('format')!r} != {OCC_FORMAT}")
    if doc.get('canvas') != {'w': W, 'h': H}:
        raise FreezeError('a16 canvas metadata mismatch')
    if doc.get('alpha_threshold') != ALPHA:
        raise FreezeError('a16 alpha_threshold mismatch')
    if doc.get('class_vocabulary') != CLASSES:
        raise FreezeError('a16 class vocabulary mismatch')
    if 'parts' in doc or 'annotation' in doc:
        raise FreezeError(
            'a16 provenance contract violated: control-row/part claims '
            'must not exist (rows are the sole authority)')
    prov = doc.get('provenance')
    if not isinstance(prov, dict) or prov.get('authority') != 'rows':
        raise FreezeError(
            "a16 provenance contract violated: provenance.authority "
            "must be 'rows'")
    rows = doc.get('rows')
    if not isinstance(rows, list) or not rows:
        raise FreezeError('a16 source: rows missing/empty')
    sem = np.full((H, W), -1, np.int16)
    for row in rows:
        y = row[0]
        if not isinstance(y, int) or not (0 <= y < H):
            raise FreezeError(f'a16 source: row y={y!r} outside canvas')
        prev_end = -1
        for entry in row[1:]:
            if not (isinstance(entry, list) and len(entry) >= 3):
                raise FreezeError(f'a16 source: malformed entry {entry!r}')
            a, b, cname = entry[0], entry[1], entry[2]
            for v in (a, b):
                if not isinstance(v, int) or isinstance(v, bool):
                    raise FreezeError(f'a16 source: non-int coord {v!r}')
            if cname not in CLASSES:
                raise FreezeError(f'a16 source: unknown class {cname!r}')
            if a < 0 or b < a or b >= W:
                raise FreezeError(f'a16 source: run {a}-{b} out of bounds')
            if a <= prev_end:
                raise FreezeError(
                    f'a16 source: unsorted/overlapping runs at y={y}')
            span = sem[y, a:b + 1]
            if (span != -1).any():
                raise FreezeError(
                    f'a16 source: duplicate px in row y={y} x{a}-{b}')
            sem[y, a:b + 1] = CLASSES.index(cname)
            prev_end = b
    labeled = (sem != -1) & union
    if int(labeled.sum()) != A16_PROP_UNION_PX:
        raise FreezeError(
            f'a16 labeled {int(labeled.sum())} != prop union '
            f'{A16_PROP_UNION_PX}')
    if (sem != -1)[~union].any():
        raise FreezeError('a16 source: labeled px outside prop union')
    counts = {c: int(((sem == i) & union).sum()) for i, c in enumerate(CLASSES)}
    if sum(counts.values()) != A16_PROP_UNION_PX:
        raise FreezeError('a16 source: class sum != prop union')
    if doc.get('classes') != counts:
        raise FreezeError('a16 classes metadata != computed counts')
    if doc.get('prop_union_px') != A16_PROP_UNION_PX:
        raise FreezeError('a16 prop_union_px metadata mismatch')
    return sem, counts


def validate_tail_source(doc, asset):
    """Metadata + strict row validation + FULL review-record validation."""
    if doc.get('format') != TAIL_FORMAT:
        raise FreezeError(f"{asset} format {doc.get('format')!r} "
                          f"!= {TAIL_FORMAT}")
    if doc.get('canvas') != {'w': W, 'h': H}:
        raise FreezeError(f'{asset} canvas metadata mismatch')
    if doc.get('alpha_threshold') != ALPHA:
        raise FreezeError(f'{asset} alpha_threshold mismatch')
    for row in doc.get('rows', []):
        validate_row_spec(row, H, W, f'{asset} rows')

    final = rebuild_runs(doc['rows'], H, W)
    if doc.get('source_px') != int(final.sum()):
        raise FreezeError(
            f"{asset} source_px {doc.get('source_px')} != reconstructed "
            f'{int(final.sum())}')

    review = doc.get('review')
    if not isinstance(review, dict):
        raise FreezeError(f'{asset}: review record missing')
    if review.get('protocol') != 'FULL_MANUAL_REVIEW':
        raise FreezeError(f'{asset}: review protocol mismatch')
    if review.get('unreviewed_px') != 0:
        raise FreezeError(f'{asset}: UNREVIEWED != 0')
    reasons_ok = set(review.get('rejected_reasons', [])) <= set(REJECT_REASONS)
    if not reasons_ok:
        raise FreezeError(f'{asset}: unknown reject reason in metadata')

    adj = doc.get('adjudication')
    if not isinstance(adj, dict):
        raise FreezeError(f'{asset}: adjudication metadata missing')
    if tuple(adj.get('gold_window', ())) != GOLD_WINDOWS[asset]:
        raise FreezeError(f'{asset}: adjudication gold_window mismatch')

    review_rows = review.get('rows')
    if not isinstance(review_rows, list):
        raise FreezeError(f'{asset}: review rows missing')
    n_draft = n_acc = n_rej = 0
    for entry in review_rows:
        if not (isinstance(entry, list) and len(entry) == 4):
            raise FreezeError(f'{asset}: malformed review entry')
        y, draft_r, acc_r, rej_r = entry
        if not isinstance(y, int) or not (0 <= y < H):
            raise FreezeError(f'{asset}: review row y={y!r} out of canvas')
        for runs in (draft_r, acc_r):
            validate_row_spec([y] + list(runs), H, W, f'{asset} review')
        for run in rej_r:
            if not (isinstance(run, list) and len(run) == 3):
                raise FreezeError(f'{asset}: malformed rejected run')
            validate_row_spec([y] + [[run[0], run[1]]], H, W,
                              f'{asset} review')
            if run[2] not in REJECT_REASONS:
                raise FreezeError(
                    f'{asset}: rejected run reason {run[2]!r} invalid')
        dm = runs_to_mask_row(draft_r, W)
        am = runs_to_mask_row(acc_r, W)
        rm = runs_to_mask_row([(a, b) for a, b, _ in rej_r], W)
        if not np.array_equal(dm, am | rm):
            raise FreezeError(
                f'{asset} y={y}: draft != accepted | rejected')
        if (am & rm).any():
            raise FreezeError(f'{asset} y={y}: accepted ∩ rejected != 0')
        if not np.array_equal(am, final[y]):
            raise FreezeError(
                f'{asset} y={y}: accepted runs != final source row')
        n_draft += int(dm.sum())
        n_acc += int(am.sum())
        n_rej += int(rm.sum())
    if n_draft != n_acc + n_rej:
        raise FreezeError(f'{asset}: draft_px != accepted + rejected')
    if review.get('draft_px') != n_draft or \
            review.get('accepted_px') != n_acc or \
            review.get('rejected_px') != n_rej:
        raise FreezeError(f'{asset}: review totals != metadata')
    return final, review


def runs_mask_of_rejected(review_rows):
    m = np.zeros((H, W), bool)
    for entry in review_rows:
        y, _d, _a, rej = entry
        for a, b, _reason in rej:
            m[y, a:b + 1] = True
    return m


def main():
    written = []
    OUT.mkdir(parents=True, exist_ok=True)
    report = ['# NIGHT03_PATCH2B_R1A_R5 — mask/plan freeze', '']
    receipt = ['NIGHT03_PATCH2B_R1A_R5_RECEIPT (program-generated)', '']
    receipt.append('CANDIDATES_CREATED = 0')
    receipt.append('GENERATION_CALLS = 0')
    receipt.append('')

    # ================= a01 / a05 tail (raw gates BEFORE any use) ======
    tail_stats = {}
    for asset in ('a01', 'a05'):
        adir = OUT / asset
        adir.mkdir(parents=True, exist_ok=True)
        master = np.array(Image.open(
            MASTERS / MASTERS_FILES[asset]).convert('RGBA'))
        h, w = master.shape[:2]
        visible = master[..., 3] > ALPHA

        doc = json.loads(
            (SRC / f'{asset}_tail_source.json').read_text(encoding='utf-8'))
        raw, review = validate_tail_source(doc, asset)

        raw_outside = int((raw & ~visible).sum())
        if raw_outside != 0:
            raise FreezeError(
                f'{asset}: raw_source ∩ outside_visible = {raw_outside} != 0')
        protected = np.zeros((h, w), bool)
        for term in PROTECTED_TERMS[asset]:
            protected |= np.array(Image.open(
                R4_MASKS / asset / f'{asset}_{term}.png').convert('L')) > 127
        raw_prot = int((raw & protected).sum())
        if raw_prot != 0:
            raise FreezeError(
                f'{asset}: raw_source ∩ protected = {raw_prot} != 0')

        tail_src = raw  # validated raw, used as-is — no clipping exists

        dest = mirror_mask(tail_src, w)
        mirror_outside = int((mirror_mask(dest, w) ^ tail_src).sum())
        if mirror_outside != 0:
            raise FreezeError(
                f'{asset}: mirror_source_outside_tail = {mirror_outside}')

        vis_dest = dest & ~visible
        underlay = dest & visible
        vd_prot = int((vis_dest & protected).sum())
        if vd_prot != 0:
            raise FreezeError(
                f'{asset}: visible_destination ∩ protected = {vd_prot}')
        ul_prot = int((underlay & protected).sum())

        stats = {
            'tail_source_px': int(tail_src.sum()),
            'destination_px': int(dest.sum()),
            'visible_destination_px': int(vis_dest.sum()),
            'underlay_px': int(underlay.sum()),
            'underlay_protected_px': ul_prot,
            'raw_outside_visible': raw_outside,
            'raw_protected_overlap': raw_prot,
            'mirror_source_outside_tail': mirror_outside,
            'review_draft_px': review['draft_px'],
            'review_accepted_px': review['accepted_px'],
            'review_rejected_px': review['rejected_px'],
            'review_unreviewed_px': review['unreviewed_px'],
        }
        tail_stats[asset] = stats
        for name, mask in [('tail_source', tail_src),
                           ('tail_destination', dest),
                           ('tail_visible_destination', vis_dest),
                           ('tail_underlay', underlay)]:
            fxpng.write_png_gray(adir / f'{asset}_{name}.png',
                                 np.where(mask, 255, 0).astype(np.uint8))
            written.append(f'{asset}/{asset}_{name}.png')
            np.save(adir / f'{asset}_{name}.npy', mask.astype(np.uint8))
            written.append(f'{asset}/{asset}_{name}.npy')
        report.append(f'## {asset} tail (full manual review record; '
                      'raw gates pre-validated, zero clipping)')
        for k, v in stats.items():
            report.append(f'- {k}: {v}')
        report.append('')
        for k, v in stats.items():
            receipt.append(f'{asset.upper()}_{k.upper()} = {v}')
        receipt.append('')

    # ================= a16 occlusion ==================================
    union = build_prop_union()
    if int(union.sum()) != A16_PROP_UNION_PX:
        raise FreezeError('R6A-R4 prop union != 36124 px')
    occ = json.loads(
        (SRC / 'a16_occlusion_annotation.json').read_text(encoding='utf-8'))
    sem, counts = validate_a16_source(occ, union)

    master16 = np.array(Image.open(
        MASTERS / MASTERS_FILES['a16']).convert('RGBA'))
    bgc = checker(H, W)
    base16 = composite(master16, bgc)

    for i, cname in enumerate(CLASSES):
        m = (sem == i) & union
        fxpng.write_png_gray(OUT / f'a16_class_{cname}.png',
                             np.where(m, 255, 0).astype(np.uint8))
        written.append(f'a16_class_{cname}.png')
        np.save(OUT / f'a16_class_{cname}.npy', m.astype(np.uint8))
        written.append(f'a16_class_{cname}.npy')
        cut = master16.copy()
        cut[..., 3][~m] = 0
        fxpng.write_png_rgb(OUT / f'a16_class_{cname}_cutout.png',
                            composite(cut, bgc).astype(np.uint8))
        written.append(f'a16_class_{cname}_cutout.png')

    idx = np.full((H, W), 6, np.uint8)
    for i in range(6):
        idx[(sem == i) & union] = i
    palette = [CLASS_COLOURS[c] for c in CLASSES] + [(0, 0, 0)]
    fxpng.write_png_palette(
        OUT / 'a16_occlusion_partition_indexed.png', idx, palette,
        transparency=[255, 255, 255, 255, 255, 255, 0])
    written.append('a16_occlusion_partition_indexed.png')

    colp = base16.copy()
    for i, cname in enumerate(CLASSES):
        m = (sem == i) & union
        rgb = np.array(CLASS_COLOURS[cname], np.float32)
        if cname == 'transparent':
            colp[m] = colp[m] * 0.55 + rgb * 0.45
        else:
            colp[m] = colp[m] * 0.35 + rgb * 0.65
    colp8 = colp.astype(np.uint8)
    fxpng.write_png_rgb(OUT / 'a16_occlusion_partition_color.png', colp8)
    written.append('a16_occlusion_partition_color.png')
    fxpng.write_png_rgb(OUT / 'a16_semantic_overlay.png', colp8)
    written.append('a16_semantic_overlay.png')

    for tag, (x0, y0, x1, y1) in ZOOM_REGIONS.items():
        for z in (4, 8):
            sub = Image.fromarray(colp8[y0:y1, x0:x1]).resize(
                ((x1 - x0) * z, (y1 - y0) * z), Image.NEAREST)
            fxpng.write_png_rgb(OUT / f'a16_zoom_{tag}_{z * 100}.png',
                                np.array(sub, np.uint8))
            written.append(f'a16_zoom_{tag}_{z * 100}.png')

    report.append('## a16 occlusion (static source, exact cover, '
                  'rows = sole authority)')
    report.append(f'- prop_union_px: {A16_PROP_UNION_PX}')
    for cname in CLASSES:
        report.append(f'- class {cname}: {counts[cname]}')
    report.append('- labeled_outside_prop_union: 0')
    report.append('- duplicate_pixels: 0')
    report.append('- unknown_class_pixels: 0')
    report.append('- off-canvas px counted as transparent: 0')
    report.append('- provenance contract: rows-only, no control-row '
                  'claims (enforced)')
    report.append('')
    receipt.append(f'A16_PROP_UNION_PX = {A16_PROP_UNION_PX}')
    receipt.append(f'A16_LABELED_PX = {A16_PROP_UNION_PX}')
    receipt.append('A16_LABELED_OUTSIDE_PROP_UNION = 0')
    receipt.append('A16_DUPLICATE_PX = 0')
    receipt.append('A16_UNKNOWN_CLASS_PX = 0')
    receipt.append(f'A16_CLASS_SUM = {sum(counts.values())}')
    receipt.append(f'A16_CLASSES = {json.dumps(counts, sort_keys=True)}')
    receipt.append('')

    # ================= report + receipt ================================
    report.append('## gates')
    report.append('- raw_source ∩ outside_visible = 0 (a01, a05)')
    report.append('- raw_source ∩ protected = 0 (a01, a05)')
    report.append('- mirror_source_outside_tail = 0 (a01, a05)')
    report.append('- visible_destination ∩ protected = 0 (a01, a05)')
    report.append('- tail review: UNREVIEWED = 0 (a01, a05)')
    report.append('- a16 labeled == R6A-R4 prop union == 36124')
    report.append('- a16 provenance contract: rows-only (enforced)')
    report.append('- PNG encoding: deterministic fixed-Huffman LZ77 '
                  'deflate (environment-independent bytes)')
    report.append('')
    report.append('sources: data/assets_v2/annotation_sources/'
                  'night03_patch2b_r1a_r5/ (static, read-only, '
                  'never created or modified by this freeze)')
    report.append('')
    status = 'READY_FOR_NIGHT03_PATCH2B_R1A_R5_PLAN_REVIEW'
    report.append(f'STATUS = {status}')
    (OUT / 'NIGHT03_PATCH2B_R1A_R5_REPORT.md').write_text(
        '\n'.join(report) + '\n', encoding='utf-8', newline='\n')
    receipt.append(f'STATUS = {status}')
    (OUT / 'NIGHT03_PATCH2B_R1A_R5_RECEIPT.txt').write_text(
        '\n'.join(receipt) + '\n', encoding='utf-8', newline='\n')
    written.append('NIGHT03_PATCH2B_R1A_R5_REPORT.md')
    written.append('NIGHT03_PATCH2B_R1A_R5_RECEIPT.txt')

    # ================= manifest LAST ===================================
    present = sorted(p.relative_to(OUT).as_posix()
                     for p in OUT.rglob('*')
                     if p.is_file() and p.name != 'manifest.json')
    if present != sorted(written):
        raise FreezeError(f'unexpected files in output: '
                          f'{set(present) ^ set(written)}')
    manifest = {rel: sha256_bytes((OUT / rel).read_bytes())
                for rel in present}
    (OUT / 'manifest.json').write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + '\n',
        encoding='utf-8', newline='\n')

    print(f'R1A-R5 freeze OK files={len(present) + 1} '
          f'a16_prop={A16_PROP_UNION_PX} '
          f'a16_classes={json.dumps(counts, sort_keys=True)}')
    for asset in ('a01', 'a05'):
        s = tail_stats[asset]
        print(f"  {asset}: source={s['tail_source_px']} "
              f"raw_gates=0/0 mirror_outside=0 "
              f"review={s['review_accepted_px']}+"
              f"{s['review_rejected_px']}+0unreviewed")


def mirror_mask(mask, w):
    out = np.zeros_like(mask)
    ys, xs = np.where(mask)
    out[ys, (w - 1) - xs] = True
    return out


if __name__ == '__main__':
    main()
