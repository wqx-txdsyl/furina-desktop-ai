"""NIGHT-03 Patch 2B R1A-R6 — mask/plan freeze (single entry).

SCOPE (R1A-R6 task book): full-review ledger closure only.  Identical
deliverable set to R1A-R5, regenerated from
data/assets_v2/annotation_sources/night03_patch2b_r1a_r6/ (static,
read-only) into night03_patch2b_r1a_r6/.

R1A-R6 closure additions — UNREVIEWED is COMPUTED, not trusted:
  * every final-source row y and every review row y is strictly
    increasing and globally unique (canonical RLE);
  * {review y} == {final rows y} == {draft authority rows y} exactly;
  * review accepted pixels, whole canvas, == final source pixels;
  * review draft pixels, whole canvas, == the independent
    DRAFT_AUTHORITY (a01/a05_tail_draft_authority.json);
  * accepted_sum == FINAL_SOURCE.sum() == source_px;
  * draft_sum == DRAFT_AUTHORITY.sum();
  * rejected runs jointly validated: coordinate order, no overlap,
    no duplicate pixels, exactly one reason per pixel;
  * UNREVIEWED == DRAFT_AUTHORITY - accepted - rejected, computed per
    pixel, asserted == 0;
  * all run lists are canonical RLE with exact arity; extra fields
    are rejected.

Unchanged gates (fail-closed, before any use, zero clipping):
  raw_source ∩ outside_visible == 0
  raw_source ∩ protected      == 0
  a16 labeled == prop_union(36124), outside == 0, duplicates == 0,
  unknown classes == 0, class_sum == 36124, provenance contract holds.

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
import night03_patch2b_r1a_r6_fixedpng as fxpng  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'data/assets_v2/annotation_sources/night03_patch2b_r1a_r6'
R6AR4_JSON = ROOT / ('data/assets_v2/repair_candidates/'
                     'night03_patch2a_r6ar4/a16_ownership_annotation.json')
R4_MASKS = ROOT / ('data/assets_v2/repair_candidates/'
                   'night03_patch2a_r4/mask_plan')
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b_r1a_r6'

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
DRAFT_AUTH_FORMAT = 'night03-tail-draft-authority-v1-static'
OCC_FORMAT = 'night03-occlusion-semantic-rle-v4-static'
A16_PROP_UNION_PX = 36124
ZOOM_REGIONS = {
    'hand': (705, 920, 805, 1075),
    'cuff': (695, 1060, 750, 1125),
    'seat': (490, 1205, 680, 1295),
    'blade': (625, 1125, 675, 1285),
}
REJECT_REASONS = ('PROTECTED_CONFLICT', 'GOLD_STAFF_AA')

# R1A-R6-R1: the freeze embeds the expected DRAFT_AUTHORITY bytes hash
# and fail-closes BEFORE parsing JSON, constructing sets, or using the
# authority in any way.
PINNED_DRAFT_AUTHORITY_SHA256 = {
    'a01': ('4a9dcbbf8d1c551ee0e6cc23eea7f45a0a5be4bb04eec8e020d6a0a'
            'a06c60ad9'),
    'a05': ('2d36504af33b5601bab30e9397234d9a52861d6ac7876a585fe9ea'
            '2b3a367fab'),
}


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


def validate_run(entry, w, what, arity):
    """Exact-arity, canonical single run."""
    if not isinstance(entry, list) or len(entry) != arity:
        raise FreezeError(f'{what}: run must have exactly {arity} '
                          f'fields: {entry!r}')
    for v in entry[:2]:
        if not isinstance(v, int) or isinstance(v, bool):
            raise FreezeError(f'{what}: non-int coordinate {v!r}')
    a, b = entry[0], entry[1]
    if a < 0 or b < a or b >= w:
        raise FreezeError(f'{what}: run {a}-{b} out of bounds')
    return a, b


def validate_rows_canonical(rows_spec, h, w, what, arity):
    """y strictly increasing + globally unique; runs canonical."""
    prev_y = -1
    seen_y = set()
    for row in rows_spec:
        if not (isinstance(row, list) and len(row) >= 1):
            raise FreezeError(f'{what}: malformed row {row!r}')
        y = row[0]
        if not isinstance(y, int) or isinstance(y, bool) or not (0 <= y < h):
            raise FreezeError(f'{what}: row y={y!r} outside canvas')
        if y <= prev_y:
            raise FreezeError(
                f'{what}: rows must be strictly increasing and globally '
                f'unique (y={y} after y={prev_y})')
        if y in seen_y:
            raise FreezeError(f'{what}: duplicate row y={y}')
        seen_y.add(y)
        prev_end = -1
        for run in row[1:]:
            a, b = validate_run(run, w, what, arity)
            if a <= prev_end:
                raise FreezeError(
                    f'{what}: runs must be strictly increasing without '
                    f'overlap or duplicates at y={y}: {a}-{b} after '
                    f'end {prev_end}')
            prev_end = b
        prev_y = y


def runs_row_to_mask(runs, w):
    m = np.zeros(w, bool)
    for run in runs:
        m[run[0]:run[1] + 1] = True
    return m


def validate_rejected_joint(y, rejected, w, what):
    """Joint validation of ALL rejected runs of one row: coordinate
    order, no overlap, no duplicate pixels, exactly one reason/px."""
    prev_end = -1
    reason_map = {}
    for run in rejected:
        if not (isinstance(run, list) and len(run) == 3):
            raise FreezeError(f'{what}: rejected run must be exactly '
                              f'[a, b, reason]: {run!r}')
        a, b, reason = run
        if not (isinstance(a, int) and isinstance(b, int)):
            raise FreezeError(f'{what}: non-int rejected coordinate')
        if isinstance(reason, str):
            ok_reason = reason in REJECT_REASONS
        else:
            ok_reason = False
        if not ok_reason:
            raise FreezeError(f'{what}: rejected reason {reason!r} invalid')
        if a < 0 or b < a or b >= w:
            raise FreezeError(f'{what}: rejected run {a}-{b} out of bounds')
        if a <= prev_end:
            raise FreezeError(
                f'{what}: rejected runs of row y={y} must be jointly '
                f'ordered without overlap or duplicates: {a}-{b} after '
                f'end {prev_end}')
        prev_end = b
        for x in range(a, b + 1):
            if x in reason_map:
                raise FreezeError(
                    f'{what}: pixel ({y},{x}) carries more than one '
                    f'rejected reason ({reason_map[x]} and {reason})')
            reason_map[x] = reason


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
        raise FreezeError('a16 provenance contract violated: '
                          'control-row/part claims must not exist')
    prov = doc.get('provenance')
    if not isinstance(prov, dict) or prov.get('authority') != 'rows':
        raise FreezeError("a16 provenance contract violated: "
                          "provenance.authority must be 'rows'")
    rows = doc.get('rows')
    if not isinstance(rows, list) or not rows:
        raise FreezeError('a16 source: rows missing/empty')
    prev_y = -1
    seen_y = set()
    sem = np.full((H, W), -1, np.int16)
    for row in rows:
        y = row[0]
        if not isinstance(y, int) or isinstance(y, bool) or not (0 <= y < H):
            raise FreezeError(f'a16 source: row y={y!r} outside canvas')
        if y <= prev_y:
            raise FreezeError(f'a16 source: rows strictly increasing '
                              f'required (y={y} after {prev_y})')
        if y in seen_y:
            raise FreezeError(f'a16 source: duplicate row y={y}')
        seen_y.add(y)
        prev_y = y
        prev_end = -1
        for entry in row[1:]:
            if not (isinstance(entry, list) and len(entry) == 3):
                raise FreezeError(f'a16 source: entry must be exactly '
                                  f'[a, b, class]: {entry!r}')
            a, b, cname = entry
            for v in (a, b):
                if not isinstance(v, int) or isinstance(v, bool):
                    raise FreezeError(f'a16 source: non-int coord {v!r}')
            if cname not in CLASSES:
                raise FreezeError(f'a16 source: unknown class {cname!r}')
            if a < 0 or b < a or b >= W:
                raise FreezeError(f'a16 source: run {a}-{b} out of bounds')
            if a <= prev_end:
                raise FreezeError(
                    f'a16 source: runs strictly increasing without '
                    f'overlap/duplicates at y={y}')
            span = sem[y, a:b + 1]
            if (span != -1).any():
                raise FreezeError(
                    f'a16 source: duplicate px in row y={y} x{a}-{b}')
            sem[y, a:b + 1] = CLASSES.index(cname)
            prev_end = b
    labeled = (sem != -1) & union
    if int(labeled.sum()) != A16_PROP_UNION_PX:
        raise FreezeError(f'a16 labeled {int(labeled.sum())} != prop '
                          f'union {A16_PROP_UNION_PX}')
    if (sem != -1)[~union].any():
        raise FreezeError('a16 source: labeled px outside prop union')
    counts = {c: int(((sem == i) & union).sum())
              for i, c in enumerate(CLASSES)}
    if sum(counts.values()) != A16_PROP_UNION_PX:
        raise FreezeError('a16 source: class sum != prop union')
    if doc.get('classes') != counts:
        raise FreezeError('a16 classes metadata != computed counts')
    if doc.get('prop_union_px') != A16_PROP_UNION_PX:
        raise FreezeError('a16 prop_union_px metadata mismatch')
    return sem, counts


def validate_draft_authority(doc, asset):
    if doc.get('format') != DRAFT_AUTH_FORMAT:
        raise FreezeError(f"{asset} draft authority format "
                          f"{doc.get('format')!r} != {DRAFT_AUTH_FORMAT}")
    if doc.get('canvas') != {'w': W, 'h': H}:
        raise FreezeError(f'{asset} draft authority canvas mismatch')
    if doc.get('alpha_threshold') != ALPHA:
        raise FreezeError(f'{asset} draft authority alpha mismatch')
    if doc.get('provenance', {}).get('authority') != 'rows':
        raise FreezeError(f'{asset} draft authority provenance contract')
    rows = doc.get('rows')
    validate_rows_canonical(rows, H, W, f'{asset} draft authority', 2)
    draft = rebuild_runs(rows, H, W)
    if doc.get('draft_px') != int(draft.sum()):
        raise FreezeError(f'{asset} draft authority draft_px mismatch')
    return draft


def validate_tail_source(doc, da_doc, asset):
    """Metadata + canonical rows + FULL closure validation against the
    independent DRAFT_AUTHORITY."""
    if doc.get('format') != TAIL_FORMAT:
        raise FreezeError(f"{asset} format {doc.get('format')!r} "
                          f"!= {TAIL_FORMAT}")
    if doc.get('canvas') != {'w': W, 'h': H}:
        raise FreezeError(f'{asset} canvas metadata mismatch')
    if doc.get('alpha_threshold') != ALPHA:
        raise FreezeError(f'{asset} alpha_threshold mismatch')
    rows = doc.get('rows')
    validate_rows_canonical(rows, H, W, f'{asset} rows', 2)
    final = rebuild_runs(rows, H, W)
    if doc.get('source_px') != int(final.sum()):
        raise FreezeError(f"{asset} source_px {doc.get('source_px')} != "
                          f"reconstructed {int(final.sum())}")

    draft_a = validate_draft_authority(da_doc, asset)

    review = doc.get('review')
    if not isinstance(review, dict):
        raise FreezeError(f'{asset}: review record missing')
    if review.get('protocol') != 'FULL_MANUAL_REVIEW':
        raise FreezeError(f'{asset}: review protocol mismatch')
    if set(review.get('rejected_reasons', [])) - set(REJECT_REASONS):
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
    prev_y = -1
    seen_y = set()
    final_y = sorted(int(r[0]) for r in rows)
    da_y = sorted(int(r[0]) for r in da_doc['rows'])
    for entry in review_rows:
        if not (isinstance(entry, list) and len(entry) == 4):
            raise FreezeError(f'{asset}: review row must be exactly '
                              f'[y, draft_runs, accepted_runs, '
                              f'rejected_runs]: {entry!r}')
        y, d_r, a_r, rej_r = entry
        if not isinstance(y, int) or isinstance(y, bool) or not (0 <= y < H):
            raise FreezeError(f'{asset}: review row y={y!r} out of canvas')
        if y <= prev_y:
            raise FreezeError(f'{asset}: review rows strictly increasing '
                              f'and globally unique required '
                              f'(y={y} after {prev_y})')
        if y in seen_y:
            raise FreezeError(f'{asset}: duplicate review row y={y}')
        seen_y.add(y)
        prev_y = y
        # canonical runs
        prev_end = -1
        for run in d_r:
            a, b = validate_run(run, W, f'{asset} review draft', 2)
            if a <= prev_end:
                raise FreezeError(f'{asset} y={y}: draft runs not canonical')
            prev_end = b
        prev_end = -1
        for run in a_r:
            a, b = validate_run(run, W, f'{asset} review accepted', 2)
            if a <= prev_end:
                raise FreezeError(
                    f'{asset} y={y}: accepted runs not canonical')
            prev_end = b
        # joint rejected validation
        validate_rejected_joint(y, rej_r, W, f'{asset} review rejected')
        dm = runs_row_to_mask(d_r, W)
        am = runs_row_to_mask(a_r, W)
        rm = runs_row_to_mask([(a, b) for a, b, _ in rej_r], W)
        if (am & rm).any():
            raise FreezeError(f'{asset} y={y}: accepted ∩ rejected != 0')
        if not np.array_equal(am, final[y]):
            raise FreezeError(f'{asset} y={y}: accepted runs != final '
                              f'source row')
        n_draft += int(dm.sum())
        n_acc += int(am.sum())
        n_rej += int(rm.sum())

    # ---- closure: coverage sets and computed UNREVIEWED --------------
    if sorted(seen_y) != final_y:
        raise FreezeError(f'{asset}: review y set != final source y set '
                          f'({len(seen_y)} vs {len(final_y)} rows)')
    if sorted(seen_y) != da_y:
        raise FreezeError(f'{asset}: review y set != draft authority y '
                          f'set ({len(seen_y)} vs {len(da_y)} rows)')

    dm_all = np.zeros((H, W), bool)
    am_all = np.zeros((H, W), bool)
    rm_all = np.zeros((H, W), bool)
    for y, d_r, a_r, rej_r in review_rows:
        dm_all[y] |= runs_row_to_mask(d_r, W)
        am_all[y] |= runs_row_to_mask(a_r, W)
        rm_all[y] |= runs_row_to_mask([(a, b) for a, b, _ in rej_r], W)
    if not np.array_equal(am_all, final):
        raise FreezeError(f'{asset}: review accepted (whole canvas) != '
                          f'final source')
    if not np.array_equal(dm_all, draft_a):
        raise FreezeError(f'{asset}: review draft (whole canvas) != '
                          f'independent DRAFT_AUTHORITY')
    if not np.array_equal(dm_all, am_all | rm_all):
        raise FreezeError(f'{asset}: REVIEW_DRAFT != REVIEW_ACCEPTED ∪ '
                          f'REVIEW_REJECTED (rejected runs must live '
                          f'inside the draft authority and cover the '
                          f'rest of it)')
    if n_acc != int(final.sum()) or n_acc != doc.get('source_px'):
        raise FreezeError(f'{asset}: accepted_sum {n_acc} != '
                          f'FINAL_SOURCE.sum()/source_px '
                          f'({int(final.sum())})')
    if n_draft != int(draft_a.sum()) or n_draft != da_doc.get('draft_px'):
        raise FreezeError(f'{asset}: draft_sum {n_draft} != '
                          f'DRAFT_AUTHORITY.sum() ({int(draft_a.sum())})')
    unreviewed = draft_a & ~am_all & ~rm_all
    n_unreviewed = int(unreviewed.sum())
    if n_unreviewed != 0:
        raise FreezeError(f'{asset}: computed UNREVIEWED = {n_unreviewed} '
                          f'!= 0')
    if review.get('unreviewed_px') != n_unreviewed:
        raise FreezeError(f'{asset}: review.unreviewed_px metadata != '
                          f'computed {n_unreviewed}')
    if review.get('draft_px') != n_draft or \
            review.get('accepted_px') != n_acc or \
            review.get('rejected_px') != n_rej:
        raise FreezeError(f'{asset}: review totals != recomputed')
    return final, review


def mirror_mask(mask, w):
    out = np.zeros_like(mask)
    ys, xs = np.where(mask)
    out[ys, (w - 1) - xs] = True
    return out


def main():
    written = []
    OUT.mkdir(parents=True, exist_ok=True)
    report = ['# NIGHT03_PATCH2B_R1A_R6 — mask/plan freeze', '']
    receipt = ['NIGHT03_PATCH2B_R1A_R6_RECEIPT (program-generated)', '']
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
        # freeze-side DRAFT_AUTHORITY SHA pin (R1A-R6-R1): raw bytes
        # verified BEFORE any parse, set construction, or use
        da_bytes = (SRC / f'{asset}_tail_draft_authority.json').read_bytes()
        da_sha = sha256_bytes(da_bytes)
        if da_sha != PINNED_DRAFT_AUTHORITY_SHA256[asset]:
            raise FreezeError(
                f'{asset}: DRAFT_AUTHORITY SHA256 mismatch ({da_sha} != '
                f'{PINNED_DRAFT_AUTHORITY_SHA256[asset]}) — refusing to '
                f'parse or use a non-authoritative draft file')
        da_doc = json.loads(da_bytes.decode('utf-8'))
        raw, review = validate_tail_source(doc, da_doc, asset)

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

        tail_src = raw

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
            'draft_authority_px': int(da_doc['draft_px']),
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
        report.append(f'## {asset} tail (review-ledger closure verified; '
                      'raw gates pre-validated, zero clipping)')
        for k, v in stats.items():
            report.append(f'- {k}: {v}')
        report.append('- review y set == final y set == draft authority '
                      'y set')
        report.append('- accepted (whole canvas) == final source')
        report.append('- draft (whole canvas) == independent draft '
                      'authority')
        report.append('- UNREVIEWED computed == 0')
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
    report.append('- review ledger closure: y sets equal, accepted == '
                  'final, draft == draft authority, '
                  'draft == accepted ∪ rejected, rejected jointly '
                  'validated, UNREVIEWED computed == 0 (a01, a05)')
    report.append('- a16 labeled == R6A-R4 prop union == 36124')
    report.append('- a16 provenance contract: rows-only (enforced)')
    report.append('- PNG encoding: deterministic fixed-Huffman LZ77 '
                  'deflate (environment-independent bytes)')
    report.append('')
    report.append('sources: data/assets_v2/annotation_sources/'
                  'night03_patch2b_r1a_r6/ (static, read-only, '
                  'never created or modified by this freeze)')
    report.append('')
    status = 'READY_FOR_NIGHT03_PATCH2B_R1A_R6_PLAN_REVIEW'
    report.append(f'STATUS = {status}')
    (OUT / 'NIGHT03_PATCH2B_R1A_R6_REPORT.md').write_text(
        '\n'.join(report) + '\n', encoding='utf-8', newline='\n')
    receipt.append(f'STATUS = {status}')
    (OUT / 'NIGHT03_PATCH2B_R1A_R6_RECEIPT.txt').write_text(
        '\n'.join(receipt) + '\n', encoding='utf-8', newline='\n')
    written.append('NIGHT03_PATCH2B_R1A_R6_REPORT.md')
    written.append('NIGHT03_PATCH2B_R1A_R6_RECEIPT.txt')

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

    print(f'R1A-R6 freeze OK files={len(present) + 1} '
          f'a16_prop={A16_PROP_UNION_PX} '
          f'a16_classes={json.dumps(counts, sort_keys=True)}')
    for asset in ('a01', 'a05'):
        s = tail_stats[asset]
        print(f"  {asset}: source={s['tail_source_px']} "
              f"raw_gates=0/0 mirror_outside=0 "
              f"review={s['review_accepted_px']}+"
              f"{s['review_rejected_px']}+0unreviewed "
              f"draft_auth={s['draft_authority_px']}")


if __name__ == '__main__':
    main()
