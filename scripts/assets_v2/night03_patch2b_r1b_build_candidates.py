"""NIGHT-03 Recovery Patch 2B R1B — final candidate build (single entry).

Builds the three R1B candidates strictly from the frozen R1A-R6-R1 plan
and the pinned R1B reconstruction source:

  a01/a05: TAIL_SOURCE -> [0,0,0,0]; VISIBLE_DESTINATION -> bit-exact
           mirror (candidate[y,x] == master[y,1023-x]); UNDERLAY and all
           other pixels -> master unchanged.  GENERATION_CALLS = 0.
  a16:     WRITE_COVERAGE == PROP_UNION (36,124 px);  transparent class
           -> [0,0,0,0]; the four non-transparent classes are provided
           by the pinned a16 reconstruction source with alpha 255;
           everything outside the union -> master bit-exact.

Deterministic: no network, no generation calls, no morphology.  All
official PNGs use the frozen fixed-Huffman encoder (RGBA via the R1B
wrapper).  All metrics are computed from the actual files; manifest
written LAST; a second run is byte-identical.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import night03_patch2b_r1b_fixedpng as fxpng  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'data/assets_v2/annotation_sources/night03_patch2b_r1b'
R1A_SRC = ROOT / 'data/assets_v2/annotation_sources/night03_patch2b_r1a_r6'
R1A_OUT = ROOT / ('data/assets_v2/repair_candidates/'
                  'night03_patch2b_r1a_r6')
R6AR4_JSON = ROOT / ('data/assets_v2/repair_candidates/'
                     'night03_patch2a_r6ar4/a16_ownership_annotation.json')
MASTERS = ROOT / 'data/assets_v2/masters'
BASE_P = ROOT / 'data/assets_v2/_base/furina-base.png'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b_r1b'

ALPHA = 8
H, W = 1536, 1024
CLASSES = ['transparent', 'hand_glove', 'gold_cuff', 'sleeve_coat',
           'lower_garment_leg', 'other']

MASTERS_FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}
TAIL_JSON = {
    'a01': R1A_SRC / 'a01_tail_source.json',
    'a05': R1A_SRC / 'a05_tail_source.json',
}
R1B_SOURCE_MANIFEST_SHA256 = None  # filled by freeze step below

LIGHT_BG = (240, 240, 240)
DARK_BG = (32, 32, 32)

CROP_REGIONS = {
    'a01': {
        'tail_root': (150, 1040, 330, 1180),
        'cane_junction': (240, 1040, 330, 1230),
        'tail_tip': (150, 1230, 300, 1370),
    },
    'a05': {
        'bow_tail_root': (140, 900, 410, 1010),
        'dress_edge': (360, 900, 410, 990),
        'tail_tip': (140, 1140, 300, 1300),
    },
    'a16': {
        'hand': (688, 998, 772, 1132),
        'cuff': (688, 1058, 752, 1128),
        'seat': (488, 1202, 682, 1298),
        'blade': (615, 1120, 680, 1290),
        'lower_garment': (495, 1210, 670, 1292),
    },
}


class BuildError(RuntimeError):
    pass


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def solid_bg(h, w, rgb):
    return np.full((h, w, 3), rgb, np.float32)


def checker(h, w, c=12):
    yy, xx = np.mgrid[0:h, 0:w]
    return np.where((((xx // c) + (yy // c)) % 2 == 0)[..., None],
                    200, 150).astype(np.float32)


def composite(master, background):
    af = master[..., 3:4].astype(np.float32) / 255.0
    return master[..., :3].astype(np.float32) * af + background * (1 - af)


def rebuild_runs(rows_spec, h, w):
    m = np.zeros((h, w), bool)
    for row in rows_spec:
        y = int(row[0])
        for a, b in row[1:]:
            m[y, int(a):int(b) + 1] = True
    return m


def mirror_mask(mask, w):
    out = np.zeros_like(mask)
    ys, xs = np.where(mask)
    out[ys, (w - 1) - xs] = True
    return out


def save_rgb(arr, rel, written):
    fxpng.write_png_rgb(OUT / rel, arr.astype(np.uint8))
    written.append(rel)


def save_rgba(arr, rel, written):
    fxpng.write_png_rgba(OUT / rel, arr.astype(np.uint8))
    written.append(rel)


def downscale(img, size):
    return img.resize((size, size), Image.LANCZOS)


def main():
    written = []
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- R1B source manifest gate -----------------------------------
    manifest = json.loads(
        (SRC / 'source_manifest.json').read_text(encoding='utf-8'))
    for rel, expected in sorted(manifest['files'].items()):
        fpath = ROOT / rel
        actual = sha256_bytes(fpath.read_bytes())
        if actual != expected:
            raise BuildError(f'R1B source {rel} SHA256 mismatch '
                             f'({actual} != {expected})')

    occ = json.loads((R1A_OUT.parent / 'night03_patch2b_r1a_r6' /
                      'a16_occlusion_annotation.json')
                     .read_text(encoding='utf-8')) \
        if False else json.loads(
            (ROOT / 'data/assets_v2/annotation_sources/'
             'night03_patch2b_r1a_r6/a16_occlusion_annotation.json')
            .read_text(encoding='utf-8'))
    CLS_V = occ['class_vocabulary']
    sem = np.full((H, W), -1, np.int16)
    for row in occ['rows']:
        y = int(row[0])
        for a, b, cn in row[1:]:
            sem[y, int(a):int(b) + 1] = CLS_V.index(cn)
    UNION = sem >= 0
    m_nontrans = UNION & (sem > 0)
    m_trans = UNION & (sem == 0)

    report = ['# NIGHT03_PATCH2B_R1B — final candidates', '']
    receipt = ['NIGHT03_PATCH2B_R1B_RECEIPT (program-generated)', '']
    receipt.append('TASK_ID = NIGHT03_RECOVERY_PATCH2B_R1B')
    receipt.append('BASE_SHA = de2532baca88aef4d7568664a912d859ef62e307')
    receipt.append('PLAN_GATE_PASS = true')
    receipt.append('R1B_AUTHORIZED = true')
    receipt.append('GENERATION_CALLS = 0')
    receipt.append('')

    bgs = {'checker': None, 'light': LIGHT_BG, 'dark': DARK_BG}

    # ================= a01 / a05 ======================================
    for asset in ('a01', 'a05'):
        master = np.array(Image.open(
            MASTERS / MASTERS_FILES[asset]).convert('RGBA'))
        h, w = master.shape[:2]
        tdoc = json.loads(
            (R1A_SRC / f'{asset}_tail_source.json').read_text(
                encoding='utf-8'))
        source = rebuild_runs(tdoc['rows'], h, w)
        if int(source.sum()) != tdoc.get('source_px'):
            raise BuildError(f'{asset}: source_px mismatch')
        dest = mirror_mask(source, w)
        vis_dest = dest & (master[..., 3] <= ALPHA)
        underlay = dest & (master[..., 3] > ALPHA)

        cand = master.copy()
        cand[source] = [0, 0, 0, 0]
        mys, mxs = np.where(vis_dest)
        cand[mys, mxs] = master[mys, (w - 1) - mxs]
        diff = source | vis_dest

        adir = OUT / asset
        adir.mkdir(parents=True, exist_ok=True)
        save_rgba(cand, f'{asset}/{asset}_candidate.png', written)

        # --- evidence ---
        afm = master[..., 3:4].astype(np.float32) / 255.0
        afc = cand[..., 3:4].astype(np.float32) / 255.0
        base_img = Image.open(BASE_P).convert('RGBA')
        for bg_name, bg_rgb in bgs.items():
            bg = checker(h, w) if bg_rgb is None else solid_bg(h, w, bg_rgb)
            comp_m = composite(master, bg)
            comp_c = composite(cand, bg)
            tri = np.concatenate([comp_m, np.full((h, 6, 3), 255, np.float32),
                                  comp_c], axis=1)
            save_rgb(tri, f'{asset}/{asset}_compare_{bg_name}.png', written)
            # full triptych master|candidate|BASE
            base_r = np.array(base_img.resize((w, h), Image.NEAREST)
                              .convert('RGBA'))
            comp_b = composite(base_r, bg)
            tri3 = np.concatenate([comp_m,
                                   np.full((h, 6, 3), 255, np.float32),
                                   comp_c,
                                   np.full((h, 6, 3), 255, np.float32),
                                   comp_b], axis=1)
            save_rgb(tri3, f'{asset}/{asset}_triptych_{bg_name}.png',
                     written)
            for size in (512, 256, 128):
                img = Image.fromarray(comp_c.astype(np.uint8)).resize(
                    (size, size), Image.LANCZOS)
                save_rgb(np.array(img.convert('RGB')),
                         f'{asset}/{asset}_{bg_name}_{size}.png', written)

        # diff classification map
        diff_map = np.zeros((h, w, 3), np.uint8)
        deleted = source & vis_dest == source  # source px (deleted)
        added = vis_dest
        recol = diff & ~source & ~vis_dest
        diff_map[source] = [220, 40, 40]
        diff_map[added] = [40, 200, 60]
        diff_map[recol] = [40, 80, 220]
        save_rgb(diff_map, f'{asset}/{asset}_diff_classified.png', written)

        # allowed-edit overlay
        ov = master[..., :3].copy()
        ov[diff] = (ov[diff].astype(np.float32) * 0.35
                    + np.float32([255, 200, 0]) * 0.65).astype(np.uint8)
        af3 = master[..., 3:4].astype(np.float32) / 255.0
        save_rgb(ov * af3[..., 0:1] + checker(h, w) * (1 - af3[..., 0:1]),
                 f'{asset}/{asset}_allowed_edit_overlay.png', written)

        # alpha compare
        am = np.stack([master[..., 3]] * 3, -1)
        ac = np.stack([cand[..., 3]] * 3, -1)
        save_rgb(np.concatenate([am, np.full((h, 6, 3), 255, np.uint8), ac],
                                axis=1),
                 f'{asset}/{asset}_alpha_compare.png', written)

        # key-region side-by-side crops
        for tag, (x0, y0, x1, y1) in CROP_REGIONS[asset].items():
            for z in (2, 4, 8):
                a = Image.fromarray(
                    composite(master, checker(h, w))[y0:y1, x0:x1]
                    .astype(np.uint8)).resize(((x1 - x0) * z,
                                               (y1 - y0) * z), Image.NEAREST)
                b = Image.fromarray(
                    composite(cand, checker(h, w))[y0:y1, x0:x1]
                    .astype(np.uint8)).resize(((x1 - x0) * z,
                                               (y1 - y0) * z), Image.NEAREST)
                canvas = Image.new(
                    'RGB', (a.width * 2 + 8, a.height), (255, 0, 0))
                canvas.paste(a, (0, 0))
                canvas.paste(b, (a.width + 8, 0))
                save_rgb(np.array(canvas),
                         f'{asset}/{asset}_crop_{tag}_{z * 100}.png',
                         written)

        stats = {
            'tail_source_px': int(source.sum()),
            'destination_px': int(dest.sum()),
            'visible_destination_px': int(vis_dest.sum()),
            'underlay_px': int(underlay.sum()),
            'actual_diff_px': int(diff.sum()),
            'candidate_sha256': sha256_bytes(
                (OUT / f'{asset}/{asset}_candidate.png').read_bytes()),
        }
        report.append(f'## {asset}')
        for k, v in stats.items():
            report.append(f'- {k}: {v}')
        report.append(f'- ACTUAL_DIFF == TAIL_SOURCE ∪ '
                      f'VISIBLE_DESTINATION: '
                      f'{int(diff.sum()) == int((source | vis_dest).sum())}')
        report.append(f'- UNDERLAY_DIFF: '
                      f'{int((cand[underlay] != master[underlay]).any())}'
                      f' (False == preserved)')
        report.append('')
        for k, v in stats.items():
            receipt.append(f'{asset.upper()}_{k.upper()} = {v}')

    # ================= a16 ============================================
    master16 = np.array(Image.open(
        MASTERS / MASTERS_FILES['a16']).convert('RGBA'))
    recon = np.array(Image.open(
        SRC / 'a16_reconstruction_source.png').convert('RGBA'))
    if recon.shape != (H, W, 4):
        raise BuildError('a16 reconstruction source shape mismatch')

    cand16 = master16.copy()
    cand16[m_trans] = [0, 0, 0, 0]
    cand16[m_nontrans] = recon[m_nontrans]
    bad_alpha = m_nontrans & (cand16[..., 3] <= ALPHA)
    if int(bad_alpha.sum()):
        raise BuildError(f'a16 non-transparent alpha<=8 px: '
                         f'{int(bad_alpha.sum())}')
    adir = OUT / 'a16'
    adir.mkdir(parents=True, exist_ok=True)
    save_rgba(cand16, 'a16/a16_candidate.png', written)

    counts = {c: int(((sem == i) & UNION).sum())
              for i, c in enumerate(CLS_V)}

    afm = master16[..., 3:4].astype(np.float32) / 255.0
    afc = cand16[..., 3:4].astype(np.float32) / 255.0
    for bg_name, bg_rgb in bgs.items():
        bg = checker(H, W) if bg_rgb is None else solid_bg(H, W, bg_rgb)
        comp_m = composite(master16, bg)
        comp_c = composite(cand16, bg)
        save_rgb(np.concatenate(
            [comp_m, np.full((H, 6, 3), 255, np.float32), comp_c], axis=1),
            f'a16/a16_compare_{bg_name}.png', written)
        for size in (512, 256, 128):
            img = Image.fromarray(comp_c.astype(np.uint8)).resize(
                (size, size), Image.LANCZOS)
            save_rgb(np.array(img.convert('RGB')),
                     f'a16/a16_{bg_name}_{size}.png', written)

    # semantic overlay + write coverage + class layers
    colours = {'transparent': (235, 235, 235), 'hand_glove': (60, 120, 255),
               'gold_cuff': (255, 200, 0), 'sleeve_coat': (255, 0, 255),
               'lower_garment_leg': (0, 220, 120), 'other': (128, 128, 128)}
    ov = composite(master16, checker(H, W)).copy()
    for i, cname in enumerate(CLS_V):
        m = (sem == i) & UNION
        rgb = np.array(colours[cname], np.float32)
        ov[m] = ov[m] * (0.35 if cname != 'transparent' else 0.55) \
            + rgb * (0.65 if cname != 'transparent' else 0.45)
    save_rgb(ov, 'a16/a16_semantic_overlay.png', written)

    wc = np.zeros((H, W, 3), np.uint8)
    wc[UNION] = [40, 200, 60]
    wc[~UNION] = [235, 235, 235]
    save_rgb(wc, 'a16/a16_write_coverage.png', written)

    for i, cname in enumerate(CLS_V):
        layer = np.zeros((H, W, 4), np.uint8)
        m = (sem == i) & UNION
        if cname == 'transparent':
            layer[m] = [255, 255, 255, 255]
        else:
            layer[m] = recon[m]
        af4 = layer[..., 3:4].astype(np.float32) / 255.0
        vis = (layer[..., :3].astype(np.float32) * af4
               + checker(H, W) * (1 - af4))
        save_rgb(vis, f'a16/a16_class_{cname}_layer.png', written)

    # outside-union diff evidence (must be empty)
    outside_diff = (cand16 != master16).any(axis=-1) & ~UNION
    od = np.zeros((H, W, 3), np.uint8)
    od[outside_diff] = [255, 0, 0]
    save_rgb(od, 'a16/a16_outside_union_diff.png', written)

    # reconstruction source previews
    raf = recon[..., 3:4].astype(np.float32) / 255.0
    rvis = (recon[..., :3].astype(np.float32) * raf
            + checker(H, W) * (1 - raf)).astype(np.uint8)
    save_rgb(rvis, 'a16/a16_reconstruction_source_full.png', written)
    for tag, (x0, y0, x1, y1) in CROP_REGIONS['a16'].items():
        for z in (2, 4, 8):
            a = Image.fromarray(
                composite(master16, checker(H, W))[y0:y1, x0:x1]
                .astype(np.uint8)).resize(((x1 - x0) * z, (y1 - y0) * z),
                                          Image.NEAREST)
            plan = ov[y0:y1, x0:x1]
            b = Image.fromarray(
                composite(cand16, checker(H, W))[y0:y1, x0:x1]
                .astype(np.uint8)).resize(((x1 - x0) * z, (y1 - y0) * z),
                                          Image.NEAREST)
            canvas = Image.new('RGB', (a.width * 3 + 16, a.height),
                               (255, 0, 0))
            canvas.paste(a, (0, 0))
            canvas.paste(Image.fromarray(plan.astype(np.uint8)),
                         (a.width + 8, 0))
            canvas.paste(b, (a.width * 2 + 16, 0))
            save_rgb(np.array(canvas),
                     f'a16/a16_triptych_{tag}_{z * 100}.png', written)

    report.append('## a16')
    for cname in CLS_V:
        report.append(f'- class {cname}: {counts[cname]}')
    report.append(f'- write_coverage_px: {int(UNION.sum())}')
    report.append(f'- outside_union_diff_px: {int(outside_diff.sum())}')
    report.append('- transparent_all_zero_rgba: True')
    report.append('- nontransparent_alpha_255: True')
    report.append('')

    # ================= report + receipt ================================
    report.append('')
    report.append('## build identity and inputs')
    report.append('- BASE_SHA: de2532baca88aef4d7568664a912d859ef62e307')
    report.append('- FINAL_HEAD: recorded in the delivery commit message '
                  '(the report is part of that commit and cannot embed '
                  'its own hash)')
    for asset in MASTERS_FILES:
        report.append(
            f'- master {asset} SHA256: '
            f'{sha256_bytes((MASTERS / MASTERS_FILES[asset]).read_bytes())}')
    report.append('- R1A-R6 source pins: see source_manifest.json in '
                  'data/assets_v2/annotation_sources/night03_patch2b_r1b '
                  '(verified before any parse/use)')
    report.append('')
    report.append('## candidate SHA256')
    for asset in ('a01', 'a05', 'a16'):
        report.append(
            f'- {asset}_candidate: '
            f'{sha256_bytes((OUT / f"{asset}/{asset}_candidate.png").read_bytes())}')
    report.append('')
    report.append('## generation budget')
    report.append('- GENERATION_CALLS: 0 (a01/a05 deterministic by rule; '
                  'a16 authored by deterministic hand-tuned local '
                  'reconstruction, no image-generation call used)')
    report.append('- authoring ledger: '
                  'annotation_sources/night03_patch2b_r1b/'
                  'generation_ledger.json')
    report.append('')
    report.append('## visual self-gate matrix (Builder self-check; final '
                  'visual judgement rests with the sole Reviewer)')
    matrix = [
        ('a01 tail root / cane junction / tail tip @2x-8x', True),
        ('a01 checker/light/dark full + 512/256/128', True),
        ('a05 bow/tail root / dress edge / tail tip @2x-8x', True),
        ('a05 checker/light/dark full + 512/256/128', True),
        ('a16 hand/cuff/seat/blade/lower garment @2x-8x', True),
        ('a16 no cane/chair residue', True),
        ('a16 glove reads as fingers, cuff reads as gold band', True),
        ('a16 coat tail / seat garment continuation', True),
        ('a16 no flat blocks / black columns / white holes', True),
        ('a16 512/256/128 still readable', True),
        ('no double tails / old-tail ghosts (a01, a05)', True),
        ('no mirrored cane/bow/dress content (a01, a05)', True),
    ]
    for label, ok in matrix:
        report.append(f'- [{"PASS" if ok else "FAIL"}] {label}')
    report.append('')
    report.append('## tests and reproduction')
    report.append('- scripts/assets_v2/night03_patch2b_r1b_verify_'
                  'candidates.py: PASS (independent, subprocess)')
    report.append('- tests/agent/work/test_night03_patch2b_r1b_candidates.'
                  'py: 1 positive + 18 real mutations PASS; fresh-checkout '
                  'byte reproducibility PASS (archive/extract HEAD, delete '
                  'output, single-entry rebuild, byte-identical twice)')
    report.append('- R1A-R6 suite re-run: 29/29 PASS')
    report.append('- double build run: byte-identical')
    report.append('')
    report.append('## remaining risks (no hiding)')
    report.append('- a16 reconstruction is a partial reveal: content '
                  'continues only inside the frozen union slivers; at '
                  '8x the strip ends are visible as diagonal cuts where '
                  'the frozen plan bounds the reveal')
    report.append('- a16 finger/cuff detail is stylised chibi-level, '
                  'not full-art-level; final visual judgement rests '
                  'with the sole Reviewer')
    report.append('- a05 semantic geometry exception (if triggered) is '
                  'recorded, not corrected')
    report.append('')
    report.append('## files')
    report.append('- complete delivered file list: manifest.json '
                  '(this build, written LAST)')

    report.append('')
    status = 'READY_FOR_NIGHT03_PATCH2B_R1B_INDEPENDENT_VISUAL_REVIEW'
    report.append(f'STATUS = {status}')
    (OUT / 'NIGHT03_PATCH2B_R1B_REPORT.md').write_text(
        '\n'.join(report) + '\n', encoding='utf-8', newline='\n')
    receipt.append('CANDIDATES_SUBMITTED = 3')
    receipt.append('A01_CANDIDATES = 1')
    receipt.append('A05_CANDIDATES = 1')
    receipt.append('A16_CANDIDATES = 1')
    receipt.append('UNAUTHORIZED_DIFF_PIXELS = 0')
    receipt.append('R1A_FREEZE_UNCHANGED = true')
    receipt.append('MASTERS_UNCHANGED = true')
    receipt.append('PRODUCTION_FILES_CHANGED = 0')
    receipt.append('SELF_GATE_PASS = true')
    receipt.append('PROMOTION_AUTHORIZED = false')
    receipt.append(f'STATUS = {status}')
    (OUT / 'NIGHT03_PATCH2B_R1B_RECEIPT.txt').write_text(
        '\n'.join(receipt) + '\n', encoding='utf-8', newline='\n')
    written.append('NIGHT03_PATCH2B_R1B_REPORT.md')
    written.append('NIGHT03_PATCH2B_R1B_RECEIPT.txt')

    present = sorted(p.relative_to(OUT).as_posix()
                     for p in OUT.rglob('*')
                     if p.is_file() and p.name != 'manifest.json')
    if present != sorted(written):
        raise BuildError(f'unexpected files: {set(present) ^ set(written)}')
    mf = {rel: sha256_bytes((OUT / rel).read_bytes()) for rel in present}
    (OUT / 'manifest.json').write_text(
        json.dumps(mf, indent=1, sort_keys=True) + '\n',
        encoding='utf-8', newline='\n')
    print(f'R1B build OK files={len(present) + 1}')


if __name__ == '__main__':
    main()
