"""NIGHT-03 Patch 2B R1A-R6 — INDEPENDENT plan verifier.

Shares no code with night03_patch2b_r1a_r6_freeze_plan.py.  Re-derives
every deliverable from the static sources + frozen authorities and
cross-checks the committed output tree, report, receipt and manifest.
Read-only.  Exit 0 only if every check passes.

R1A-R6 closure additions — UNREVIEWED is COMPUTED, not trusted:
  * final-source rows / review rows: y strictly increasing, globally
    unique (canonical RLE); draft/accepted runs canonical;
  * {review y} == {final rows y} == {draft authority rows y};
  * review accepted (whole canvas) == final source pixels;
  * review draft (whole canvas) == independent DRAFT_AUTHORITY
    (a01/a05_tail_draft_authority.json, SHA256-pinned);
  * accepted_sum == FINAL_SOURCE.sum() == source_px;
  * draft_sum == DRAFT_AUTHORITY.sum();
  * rejected runs jointly validated (order / no overlap / no
    duplicates / exactly one reason per pixel);
  * UNREVIEWED == DRAFT_AUTHORITY - accepted - rejected, computed,
    asserted == 0;
  * exact arity everywhere; extra fields rejected.
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
CLASS_COLOURS = {
    'transparent': (235, 235, 235), 'hand_glove': (60, 120, 255),
    'gold_cuff': (255, 200, 0), 'sleeve_coat': (255, 0, 255),
    'lower_garment_leg': (0, 220, 120), 'other': (128, 128, 128),
}
ZOOM_REGIONS = {
    'hand': (705, 920, 805, 1075),
    'cuff': (695, 1060, 750, 1125),
    'seat': (490, 1205, 680, 1295),
    'blade': (625, 1125, 675, 1285),
}
GOLD_WINDOWS = {'a01': (262, 1040, 300, 1230), 'a05': (370, 905, 400, 975)}
TAIL_FORMAT = 'night03-tail-source-rle-v4-static'
DRAFT_AUTH_FORMAT = 'night03-tail-draft-authority-v1-static'
OCC_FORMAT = 'night03-occlusion-semantic-rle-v4-static'
A16_PROP_UNION_PX = 36124
REJECT_REASONS = ('PROTECTED_CONFLICT', 'GOLD_STAFF_AA')
MASTERS_FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}
PROTECTED_TERMS = {
    'a01': ['protected_identity', 'protected_costume', 'protected_props'],
    'a05': ['protected_identity', 'protected_costume', 'protected_props'],
}
STATUS_EXPECTED = 'READY_FOR_NIGHT03_PATCH2B_R1A_R6_PLAN_REVIEW'

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
    'draft_authority_a01': (
        '4a9dcbbf8d1c551ee0e6cc23eea7f45a0a5be4bb04eec8e020d6a0aa06c60ad9'),
    'draft_authority_a05': (
        '2d36504af33b5601bab30e9397234d9a52861d6ac7876a585fe9ea2b3a367fab'),
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


def png_gray(p):
    return np.array(Image.open(p).convert('L'))


def checker_bg(h, w, c=12):
    yy, xx = np.mgrid[0:h, 0:w]
    return np.where((((xx // c) + (yy // c)) % 2 == 0)[..., None],
                    200, 150).astype(np.float32)


def composite(master, background):
    af = master[..., 3:4].astype(np.float32) / 255.0
    return master[..., :3].astype(np.float32) * af + background * (1 - af)


def rows_canonical_errors(rows_spec, h, w, arity, what):
    """Independent canonical-RLE validation. Returns [] when clean."""
    errs = []
    prev_y = -1
    seen_y = set()
    for row in rows_spec:
        if not (isinstance(row, list) and len(row) >= 1):
            errs.append(f'{what}: malformed row')
            return errs
        y = row[0]
        if not isinstance(y, int) or isinstance(y, bool) or not (0 <= y < h):
            errs.append(f'{what}: row y={y!r} outside canvas')
            return errs
        if y <= prev_y:
            errs.append(f'{what}: rows not strictly increasing/unique '
                        f'(y={y} after {prev_y})')
            return errs
        if y in seen_y:
            errs.append(f'{what}: duplicate row y={y}')
            return errs
        seen_y.add(y)
        prev_y = y
        prev_end = -1
        for run in row[1:]:
            if not (isinstance(run, list) and len(run) == arity):
                errs.append(f'{what}: run arity != {arity}: {run!r}')
                return errs
            a, b = run[0], run[1]
            for v in (a, b):
                if not isinstance(v, int) or isinstance(v, bool):
                    errs.append(f'{what}: non-int coordinate {v!r}')
                    return errs
            if a < 0 or b < a or b >= w:
                errs.append(f'{what}: run {a}-{b} out of bounds')
                return errs
            if a <= prev_end:
                errs.append(f'{what}: runs not canonical at y={y} '
                            f'({a}-{b} after {prev_end})')
                return errs
            prev_end = b
    return errs


def runs_row_to_mask(runs, w):
    m = np.zeros(w, bool)
    for run in runs:
        m[run[0]:run[1] + 1] = True
    return m


def verify(sources, output, r6ar4_json, r4masks, masters):
    ck = Checker()

    # ---- authority pins -------------------------------------------
    if not ck.check(sha256_path(r6ar4_json) ==
                    PINNED_SHA256['r6ar4_annotation'],
                    'R6A-R4 annotation SHA256 pin'):
        raise VerifyFail('R6A-R4 authority hash mismatch')
    for asset in ('a01', 'a05'):
        for term in PROTECTED_TERMS[asset]:
            pin = f'protected_{asset}_{term}'
            ck.check(sha256_path(r4masks / asset / f'{asset}_{term}.png') ==
                     PINNED_SHA256[pin], f'{pin} SHA256 pin')
        da_p = sources / f'{asset}_tail_draft_authority.json'
        if not ck.check(da_p.exists(),
                        f'{asset} draft authority present'):
            raise VerifyFail(f'{asset} draft authority missing')
        ck.check(sha256_path(da_p) == PINNED_SHA256[f'draft_authority_{asset}'],
                 f'draft_authority_{asset} SHA256 pin')
    for asset in ('a01', 'a05', 'a16'):
        ck.check(sha256_path(masters / MASTERS_FILES[asset]) ==
                 PINNED_SHA256[f'master_{asset}'],
                 f'master_{asset} SHA256 pin')

    # ---- R6A-R4 prop union -----------------------------------------
    doc = json.loads(Path(r6ar4_json).read_text(encoding='utf-8'))
    m16 = np.array(Image.open(
        masters / MASTERS_FILES['a16']).convert('RGBA'))
    vis16 = m16[..., 3] > ALPHA
    cane = runs_rebuild(doc['primitives']['remove_cane'], H, W) & vis16
    chair = runs_rebuild(doc['primitives']['remove_chair'], H, W) & vis16
    union = cane | chair
    ck.check(int(union.sum()) == A16_PROP_UNION_PX,
             'prop union == 36124 px')
    bgc = checker_bg(H, W)

    # ---- a16 source validity + provenance contract ------------------
    occ = json.loads((sources / 'a16_occlusion_annotation.json')
                     .read_text(encoding='utf-8'))
    ck.check(occ.get('format') == OCC_FORMAT, 'a16 format metadata')
    ck.check(occ.get('canvas') == {'w': W, 'h': H}, 'a16 canvas metadata')
    ck.check(occ.get('alpha_threshold') == ALPHA, 'a16 alpha_threshold')
    ck.check(occ.get('class_vocabulary') == CLASSES, 'a16 vocabulary')
    ck.check('parts' not in occ and 'annotation' not in occ,
             'a16 provenance contract: no control-row/part claims')
    prov = occ.get('provenance')
    ck.check(isinstance(prov, dict) and prov.get('authority') == 'rows',
             "a16 provenance contract: authority == 'rows'")
    errs = rows_canonical_errors(occ.get('rows', []), H, W, 3, 'a16 rows')
    ck.check(not errs, f'a16 rows canonical RLE ({errs[:1]})')
    if errs:
        raise VerifyFail(f'a16 rows invalid: {errs[:3]}')
    sem = np.full((H, W), -1, np.int16)
    dup_err = None
    for row in occ['rows']:
        y = row[0]
        for a, b, cname in row[1:]:
            if cname not in CLASSES:
                dup_err = f'unknown class {cname!r}'
                break
            span = sem[y, a:b + 1]
            if (span != -1).any():
                dup_err = f'duplicate px y={y} x{a}-{b}'
                break
            sem[y, a:b + 1] = CLASSES.index(cname)
        if dup_err:
            break
    ck.check(dup_err is None, f'a16 pixel overlap/duplicates ({dup_err})')
    if dup_err:
        raise VerifyFail(f'a16 source invalid: {dup_err}')
    labeled = (sem != -1) & union
    ck.check(int(labeled.sum()) == A16_PROP_UNION_PX,
             f'a16 labeled == prop union ({int(labeled.sum())})')
    ck.check(not (sem != -1)[~union].any(),
             'a16 labeled_outside_prop_union == 0')
    counts = {c: int(((sem == i) & union).sum())
              for i, c in enumerate(CLASSES)}
    ck.check(sum(counts.values()) == A16_PROP_UNION_PX, 'a16 class_sum')
    ck.check(occ.get('classes') == counts, 'a16 classes metadata exact')
    ck.check(occ.get('prop_union_px') == A16_PROP_UNION_PX,
             'a16 prop_union_px metadata')

    # ---- a16 deliverables (pixel-exact rebuilds) --------------------
    for i, cname in enumerate(CLASSES):
        m_exp = (sem == i) & union
        p = output / f'a16_class_{cname}.png'
        if ck.check(p.exists(), f'a16_class_{cname}.png present'):
            ck.check(np.array_equal(png_gray(p) > 127, m_exp),
                     f'a16_class_{cname}.png pixels')
        n = output / f'a16_class_{cname}.npy'
        if ck.check(n.exists(), f'a16_class_{cname}.npy present'):
            ck.check(np.array_equal(np.load(n).astype(bool), m_exp),
                     f'a16_class_{cname}.npy pixels')
        c = output / f'a16_class_{cname}_cutout.png'
        if ck.check(c.exists(), f'a16_class_{cname}_cutout.png present'):
            cut = m16.copy()
            cut[..., 3][~m_exp] = 0
            exp_cut = composite(cut, bgc).astype(np.uint8)
            got = np.array(Image.open(c).convert('RGB'))
            ck.check(np.array_equal(got, exp_cut),
                     f'a16_class_{cname}_cutout.png pixel-exact rebuild')

    idx_p = output / 'a16_occlusion_partition_indexed.png'
    if ck.check(idx_p.exists(), 'partition indexed PNG present'):
        pim = Image.open(idx_p)
        idx = np.array(pim)
        exp_idx = np.full((H, W), 6, np.uint8)
        for i in range(6):
            exp_idx[(sem == i) & union] = i
        ck.check(np.array_equal(idx, exp_idx),
                 'partition index values (classes 0-5, off-union 6)')
        ck.check(pim.mode == 'P', 'partition is indexed/palette PNG')
        exp_pal = [v for cname in CLASSES for v in CLASS_COLOURS[cname]] \
            + [0, 0, 0]
        ck.check((pim.getpalette() or [])[:len(exp_pal)] == exp_pal,
                 'partition palette colours exact')
        ck.check(pim.info.get('transparency') == 6,
                 'partition transparency index == 6')

    exp_colp = None
    colp_p = output / 'a16_occlusion_partition_color.png'
    ov_p = output / 'a16_semantic_overlay.png'
    if ck.check(colp_p.exists() and ov_p.exists(),
                'colour partition + overlay present'):
        af16 = m16[..., 3:4].astype(np.float32) / 255.0
        colp = m16[..., :3].astype(np.float32) * af16 + bgc * (1 - af16)
        for i, cname in enumerate(CLASSES):
            m = (sem == i) & union
            rgb = np.array(CLASS_COLOURS[cname], np.float32)
            if cname == 'transparent':
                colp[m] = colp[m] * 0.55 + rgb * 0.45
            else:
                colp[m] = colp[m] * 0.35 + rgb * 0.65
        exp_colp = colp.astype(np.uint8)
        ck.check(np.array_equal(np.array(Image.open(colp_p).convert('RGB')),
                                exp_colp),
                 'a16_occlusion_partition_color.png pixel-exact rebuild')
        ck.check(np.array_equal(np.array(Image.open(ov_p).convert('RGB')),
                                exp_colp),
                 'a16_semantic_overlay.png pixel-exact rebuild')

    for tag, (x0, y0, x1, y1) in ZOOM_REGIONS.items():
        for z in (4, 8):
            rel = f'a16_zoom_{tag}_{z * 100}.png'
            p = output / rel
            if not ck.check(p.exists(), f'{rel} present'):
                continue
            if exp_colp is None:
                ck.check(False, f'{rel} rebuild skipped (no overlay)')
                continue
            sub = Image.fromarray(exp_colp[y0:y1, x0:x1]).resize(
                ((x1 - x0) * z, (y1 - y0) * z), Image.NEAREST)
            ck.check(np.array_equal(
                np.array(Image.open(p).convert('RGB')),
                np.array(sub, np.uint8)), f'{rel} pixel-exact rebuild')

    # ---- tails: ledger closure + raw gates + deliverables ------------
    tail_stats = {}
    for asset in ('a01', 'a05'):
        master = np.array(Image.open(
            masters / MASTERS_FILES[asset]).convert('RGBA'))
        h, w = master.shape[:2]
        visible = master[..., 3] > ALPHA
        doc_t = json.loads((sources / f'{asset}_tail_source.json')
                           .read_text(encoding='utf-8'))
        da_doc = json.loads((sources / f'{asset}_tail_draft_authority.json')
                            .read_text(encoding='utf-8'))
        ck.check(doc_t.get('format') == TAIL_FORMAT,
                 f'{asset} format metadata')
        ck.check(doc_t.get('canvas') == {'w': W, 'h': H},
                 f'{asset} canvas metadata')
        ck.check(doc_t.get('alpha_threshold') == ALPHA,
                 f'{asset} alpha_threshold metadata')
        ck.check(da_doc.get('format') == DRAFT_AUTH_FORMAT,
                 f'{asset} draft authority format')
        ck.check(da_doc.get('canvas') == {'w': W, 'h': H},
                 f'{asset} draft authority canvas')

        errs_f = rows_canonical_errors(doc_t.get('rows', []), h, w, 2,
                                       f'{asset} rows')
        ck.check(not errs_f, f'{asset} final rows canonical RLE '
                             f'({errs_f[:1]})')
        if errs_f:
            raise VerifyFail(f'{asset} rows invalid: {errs_f[:3]}')
        raw = runs_rebuild(doc_t['rows'], h, w)
        ck.check(doc_t.get('source_px') == int(raw.sum()),
                 f"{asset} source_px == reconstructed "
                 f"({doc_t.get('source_px')} vs {int(raw.sum())})")
        errs_d = rows_canonical_errors(da_doc.get('rows', []), h, w, 2,
                                       f'{asset} draft authority rows')
        ck.check(not errs_d, f'{asset} draft authority rows canonical '
                             f'({errs_d[:1]})')
        if errs_d:
            raise VerifyFail(f'{asset} draft authority invalid: '
                             f'{errs_d[:3]}')
        draft_a = runs_rebuild(da_doc['rows'], h, w)
        ck.check(da_doc.get('draft_px') == int(draft_a.sum()),
                 f'{asset} draft authority draft_px == reconstructed')

        review = doc_t.get('review')
        if ck.check(isinstance(review, dict), f'{asset} review record dict'):
            ck.check(review.get('protocol') == 'FULL_MANUAL_REVIEW',
                     f'{asset} review protocol')
            ck.check(set(review.get('rejected_reasons', []))
                     <= set(REJECT_REASONS), f'{asset} reason vocabulary')
            adj = doc_t.get('adjudication')
            ck.check(isinstance(adj, dict)
                     and tuple(adj.get('gold_window', ()))
                     == GOLD_WINDOWS[asset],
                     f'{asset} adjudication gold_window metadata')
            rrows = review.get('rows')
            if ck.check(isinstance(rrows, list), f'{asset} review rows'):
                # canonical: y strictly increasing, globally unique,
                # exact arity 4, runs canonical, rejected joint
                c_errs = None
                prev_y = -1
                seen_y = set()
                n_draft = n_acc = n_rej = 0
                ok_sets = True
                for entry in rrows:
                    if not (isinstance(entry, list) and len(entry) == 4):
                        c_errs = 'review row arity != 4'
                        break
                    y, d_r, a_r, r_r = entry
                    if not isinstance(y, int) or isinstance(y, bool) \
                            or not (0 <= y < h):
                        c_errs = f'review row y={y!r} out of canvas'
                        break
                    if y <= prev_y:
                        c_errs = f'review rows not strictly increasing ' \
                                 f'(y={y} after {prev_y})'
                        break
                    if y in seen_y:
                        c_errs = f'duplicate review row y={y}'
                        break
                    seen_y.add(y)
                    prev_y = y
                    e3 = rows_canonical_errors(
                        [[y] + list(d_r)], h, w, 2,
                        f'{asset} review draft')
                    e3 += rows_canonical_errors(
                        [[y] + list(a_r)], h, w, 2,
                        f'{asset} review accepted')
                    # joint rejected validation
                    prev_end = -1
                    reason_map = {}
                    for run in r_r:
                        if not (isinstance(run, list) and len(run) == 3):
                            c_errs = f'rejected run arity != 3: {run!r}'
                            break
                        a, b, reason = run
                        if reason not in REJECT_REASONS:
                            c_errs = f'invalid reason {reason!r}'
                            break
                        if not isinstance(a, int) or not isinstance(b, int) \
                                or a < 0 or b < a or b >= w:
                            c_errs = f'rejected run {a}-{b} out of bounds'
                            break
                        if a <= prev_end:
                            c_errs = f'rejected runs jointly not canonical ' \
                                     f'at y={y} ({a}-{b} after {prev_end})'
                            break
                        prev_end = b
                        for x in range(a, b + 1):
                            if x in reason_map:
                                c_errs = f'pixel ({y},{x}) has multiple ' \
                                         f'reasons'
                                break
                            reason_map[x] = reason
                        if c_errs:
                            break
                    if c_errs or e3:
                        c_errs = c_errs or e3[0]
                        break
                    dm = runs_row_to_mask(d_r, w)
                    am = runs_row_to_mask(a_r, w)
                    rm = runs_row_to_mask([(a, b) for a, b, _ in r_r], w)
                    if (am & rm).any():
                        ok_sets = False
                        c_errs = f'y={y}: accepted ∩ rejected != 0'
                        break
                    if not np.array_equal(am, raw[y]):
                        ok_sets = False
                        c_errs = f'y={y}: accepted != final source row'
                        break
                    n_draft += int(dm.sum())
                    n_acc += int(am.sum())
                    n_rej += int(rm.sum())
                ck.check(c_errs is None,
                         f'{asset} review ledger canonical + jointly '
                         f'validated ({c_errs})')
                ck.check(ok_sets, f'{asset} review per-row accepted == '
                                  f'final row, disjoint rejected')
                if c_errs is None:
                    # closure equations
                    ck.check(sorted(seen_y) ==
                             sorted(int(r[0]) for r in doc_t['rows']),
                             f'{asset} review y set == final source y set')
                    ck.check(sorted(seen_y) ==
                             sorted(int(r[0]) for r in da_doc['rows']),
                             f'{asset} review y set == draft authority '
                             f'y set')
                    dm_all = np.zeros((h, w), bool)
                    am_all = np.zeros((h, w), bool)
                    rm_all = np.zeros((h, w), bool)
                    for y, d_r, a_r, r_r in rrows:
                        dm_all[y] |= runs_row_to_mask(d_r, w)
                        am_all[y] |= runs_row_to_mask(a_r, w)
                        rm_all[y] |= runs_row_to_mask(
                            [(a, b) for a, b, _ in r_r], w)
                    ck.check(np.array_equal(am_all, raw),
                             f'{asset} review accepted (whole canvas) == '
                             f'final source')
                    ck.check(np.array_equal(dm_all, draft_a),
                             f'{asset} review draft (whole canvas) == '
                             f'DRAFT_AUTHORITY')
                    ck.check(np.array_equal(dm_all, am_all | rm_all),
                             f'{asset} REVIEW_DRAFT == REVIEW_ACCEPTED ∪ '
                             f'REVIEW_REJECTED')
                    ck.check(n_acc == int(raw.sum()) ==
                             doc_t.get('source_px'),
                             f'{asset} accepted_sum == FINAL_SOURCE.sum() '
                             f'== source_px ({n_acc})')
                    ck.check(n_draft == int(draft_a.sum()) ==
                             da_doc.get('draft_px'),
                             f'{asset} draft_sum == '
                             f'DRAFT_AUTHORITY.sum() ({n_draft})')
                    unreviewed = draft_a & ~am_all & ~rm_all
                    n_unrev = int(unreviewed.sum())
                    ck.check(n_unrev == 0,
                             f'{asset} computed UNREVIEWED == 0 '
                             f'(={n_unrev})')
                    ck.check(review.get('unreviewed_px') == n_unrev,
                             f'{asset} unreviewed metadata == computed')
                    ck.check(review.get('draft_px') == n_draft
                             and review.get('accepted_px') == n_acc
                             and review.get('rejected_px') == n_rej,
                             f'{asset} review metadata == recomputed '
                             f'totals')

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
                 f'{asset} visible_destination ∩ protected == 0')
        stats = {'tail_source_px': int(raw.sum()),
                 'destination_px': int(dest_exp.sum()),
                 'visible_destination_px': int(vis_dest_exp.sum()),
                 'underlay_px': int(underlay_exp.sum()),
                 'underlay_protected_px': int((underlay_exp & prot).sum()),
                 'raw_outside_visible': raw_out,
                 'raw_protected_overlap': raw_prot,
                 'mirror_source_outside_tail': mirror_out}
        rv = doc_t.get('review') or {}
        stats['review_draft_px'] = rv.get('draft_px')
        stats['review_accepted_px'] = rv.get('accepted_px')
        stats['review_rejected_px'] = rv.get('rejected_px')
        stats['review_unreviewed_px'] = rv.get('unreviewed_px')
        stats['draft_authority_px'] = da_doc.get('draft_px')
        tail_stats[asset] = stats
        for name, exp in [('tail_source', raw),
                          ('tail_destination', dest_exp),
                          ('tail_visible_destination', vis_dest_exp),
                          ('tail_underlay', underlay_exp)]:
            p = output / asset / f'{asset}_{name}.png'
            if ck.check(p.exists(), f'{asset}_{name}.png present'):
                ck.check(np.array_equal(png_gray(p) > 127, exp),
                         f'{asset}_{name}.png pixels')
            n = output / asset / f'{asset}_{name}.npy'
            if ck.check(n.exists(), f'{asset}_{name}.npy present'):
                ck.check(np.array_equal(np.load(n).astype(bool), exp),
                         f'{asset}_{name}.npy pixels')

    # ---- report / receipt -------------------------------------------
    rep_p = output / 'NIGHT03_PATCH2B_R1A_R6_REPORT.md'
    rec_p = output / 'NIGHT03_PATCH2B_R1A_R6_RECEIPT.txt'
    if ck.check(rep_p.exists(), 'report present'):
        rep = rep_p.read_text(encoding='utf-8')
        rep_lines = set(rep.splitlines())
        ck.check(f'STATUS = {STATUS_EXPECTED}' in rep_lines,
                 'report STATUS R1A-R6')
        for old in ('PATCH2B_R1A_R5', 'PATCH2B_R1A_R4', 'PATCH2B_R1A_R3'):
            ck.check(old not in rep, f'report carries no {old} name')
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
            sec = section_for(f'{asset} ')
            sec_set = set(sec)
            for k, v in tail_stats[asset].items():
                exp = f'- {k}: {v}'
                ck.check(exp in sec_set, f'report {asset} {k} == {v}')
                conflicts = [ln for ln in sec
                             if ln.startswith(f'- {k}: ') and ln != exp]
                ck.check(not conflicts,
                         f'report {asset} {k} no conflicting line '
                         f'({conflicts[:1]})')
        a16_sec = section_for('a16 occlusion')
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
        ck.check(f'STATUS = {STATUS_EXPECTED}' in rec,
                 'receipt STATUS R1A-R6')
        for old in ('PATCH2B_R1A_R5', 'PATCH2B_R1A_R4', 'PATCH2B_R1A_R3'):
            ck.check(old not in rec, f'receipt carries no {old} name')
        all_pairs = re.findall(r'^([A-Z0-9_]+) = (.*)$', rec, re.MULTILINE)
        keys = [k for k, _ in all_pairs]
        ck.check(len(keys) == len(set(keys)),
                 'receipt has no duplicate keys')
        kv = dict(all_pairs)
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
                                   'night03_patch2b_r1a_r6')
    ap.add_argument('--output', type=Path,
                    default=ROOT / 'data/assets_v2/repair_candidates/'
                                   'night03_patch2b_r1a_r6')
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
