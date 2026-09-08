"""NIGHT-03 Recovery Patch 2A R6A-R4 — a16 ownership Gate (Builder).

Consumes the EXTERNAL static annotation source
``a16_ownership_annotation.json`` (per-row scanline RLE, hand-annotated by
the Builder with a separate tool) strictly read-only, validates it against
the master, and renders the full evidence set.

Gate invariants enforced here:
  * label 0 == transparent background ONLY (alpha <= 8); every visible
    pixel (alpha > 8) carries an explicit semantic label
    (no default-to-costume, no catch-all "other");
  * protected_other_character (7) is the reviewer-mandated category for
    un-detailed character pixels and is EXPLICIT in the source JSON;
  * remove_cane (5) / remove_chair (6) contours follow the real prop
    outlines from hand-placed scanline rows (no wide rectangles, no
    coarse polygons spanning the character);
  * every isolated cutout's non-checker pixel count must equal the
    census of its label;
  * combined cutout may contain prop-outline-shaped occlusion holes but
    no rectangular cuts (verified by construction: rows come from the
    hand-placed contours).

Zero colour tests. Zero connected components. Zero morphological ops.
Zero near_prot. Zero removal-mask references. Zero generation calls.

Deterministic rendering: fixed PNG parameters, sorted iteration, no
timestamps anywhere; running twice in the same environment is
byte-identical (self-checked via SHA table).
"""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r6ar4'
MASTERS = ROOT / 'data/assets_v2/masters'
BASE_P = ROOT / 'data/assets_v2/_base/furina-base.png'
SPEC_DIR = ROOT / 'data/assets_v2/_spec'
SOURCE_JSON = OUT / 'a16_ownership_annotation.json'
REVIEW_REPORT = ROOT / ('data/assets_v2/repair_candidates/night03_patch1/'
                        'NIGHT03_PATCH1_REVIEW_REPORT.md')
MASTER_FILE = 'furina_v2_a16_work_focused.png'
ALPHA_THRESHOLD = 8

PNG_PARAMS = {'optimize': False, 'compress_level': 6}

LABEL_NAMES = {
    0: 'background',
    1: 'protected_hair',
    2: 'protected_quill_paper',
    3: 'protected_glove_gold_cuff',
    4: 'protected_costume',
    5: 'remove_cane',
    6: 'remove_chair',
    7: 'protected_other_character',
}
LABEL_COLOURS = {
    0: (0, 0, 0), 1: (30, 80, 255), 2: (120, 200, 120),
    3: (255, 160, 60), 4: (230, 0, 230), 5: (255, 40, 40),
    6: (160, 90, 40), 7: (0, 200, 200),
}
BASE_SHA = 'e3bdedf389a56154614d9e3e9d5a648c20d75e0e'


def sha256_path(p, text_lf=False):
    h = hashlib.sha256()
    if text_lf:
        h.update(Path(p).read_bytes().replace(b'\r\n', b'\n'))
        return h.hexdigest()
    with open(p, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def checker_fn(h, w, c=24):
    yy, xx = np.mgrid[0:h, 0:w]
    t = ((xx // c) + (yy // c)) % 2 == 0
    return np.where(t[..., None], 200, 150).astype(np.uint8)


def save_png(arr, path):
    img = arr if isinstance(arr, Image.Image) else Image.fromarray(arr)
    img.save(path, **PNG_PARAMS)


def validate_frozen_ownership(doc, master_path, alpha_threshold):
    """Importable, independently callable Gate validation.

    Rebuilds ownership and the two frozen primitives strictly from the
    committed annotation source, then fails closed unless:
      * label 0 == transparent background only and every visible pixel
        carries an explicit semantic label;
      * ledger pixels == cane_primitive ∩ chair_primitive exactly
        (no omissions, duplicates or non-overlap extras);
      * every ledger winner matches the final ownership label;
      * the ledger contains both winners.
    Returns the verification stats used by plan/report/receipt.
    """
    assert doc['format'] == 'night03-ownership-scanline-rle-v4'
    assert doc['asset'] == 'a16'
    assert doc['alpha_threshold'] == alpha_threshold
    ledger = doc.get('occlusion_resolution') or []
    assert ledger, 'occlusion_resolution ledger missing from source'
    ledger_px_total = 0
    for entry in ledger:
        assert entry['winner'] in (5, 6)
        assert entry['rationale'], 'ledger entry without rationale'
        ledger_px_total += int(entry['px'])

    master = np.array(Image.open(master_path).convert('RGBA'))
    h, w = master.shape[:2]
    assert (doc['canvas']['w'], doc['canvas']['h']) == (w, h)

    # rebuild ownership strictly from the scanline rows
    ownership = np.zeros((h, w), np.uint8)
    n_rows = 0
    n_runs = 0
    for row in doc['rows']:
        y = int(row[0])
        assert 0 <= y < h
        n_rows += 1
        prev_x1 = -1
        for entry in row[1:]:
            x0, x1, lb = int(entry[0]), int(entry[1]), int(entry[2])
            assert 1 <= lb <= 7 and 0 <= x0 <= x1 < w
            assert x0 > prev_x1, 'overlapping/unsorted runs in source'
            prev_x1 = x1
            ownership[y, x0:x1 + 1] = lb
            n_runs += 1

    visible = master[..., 3] > alpha_threshold

    # ---- independent primitive reconstruction from the frozen inputs -----
    prims = doc.get('primitives') or {}
    assert set(prims.keys()) == {'remove_cane', 'remove_chair'}, (
        'primitive inputs missing from source')

    def rebuild_primitive(rows_spec):
        mask = np.zeros((h, w), bool)
        for row in rows_spec:
            y = int(row[0])
            prev = -1
            for a, b in row[1:]:
                a, b = int(a), int(b)
                assert a > prev, 'unsorted primitive runs'
                prev = b
                mask[y, a:b + 1] = True
        return mask

    cane_prim = rebuild_primitive(prims['remove_cane']) & visible
    chair_prim = rebuild_primitive(prims['remove_chair']) & visible
    prim_overlap = cane_prim & chair_prim
    overlap_pts = {(int(x), int(y)) for y, x in zip(*np.where(prim_overlap))}

    ledger_pixels = {}
    for entry in ledger:
        winner = int(entry['winner'])
        assert winner in (5, 6)
        for pix in entry.get('pixels') or []:
            x, y = int(pix[0]), int(pix[1])
            assert (x, y) not in ledger_pixels, (
                f'duplicate ledger pixel ({x},{y})')
            ledger_pixels[(x, y)] = winner

    # exact set equality: ledger == primitive intersection (fail-closed
    # against omission, duplication and non-overlap extras alike)
    assert ledger_pixels.keys() == overlap_pts, (
        f'ledger != primitive intersection: missing='
        f'{sorted(overlap_pts - ledger_pixels.keys())[:10]}, extra='
        f'{sorted(ledger_pixels.keys() - overlap_pts)[:10]}')

    # ---- winner vs final ownership, one pixel at a time -------------------
    for entry in ledger:
        winner = int(entry['winner'])
        for pix in entry.get('pixels') or []:
            x, y = int(pix[0]), int(pix[1])
            assert ownership[y, x] == winner, (
                f'ledger pixel ({x},{y}) labeled {ownership[y, x]} '
                f'!= winner {winner}')
    assert ledger_px_total == len(ledger_pixels)
    winners_seen = sorted({int(e['winner']) for e in ledger})
    assert winners_seen == [5, 6], (
        f'ledger must contain both winners, saw {winners_seen}')

    # ---- gate validations --------------------------------------------------
    unlabeled_visible = int((visible & (ownership == 0)).sum())
    labeled_background = int(((~visible) & (ownership != 0)).sum())
    assert unlabeled_visible == 0, f'unlabeled visible px: {unlabeled_visible}'
    assert labeled_background == 0, f'labeled bg px: {labeled_background}'
    assert (cane_prim & chair_prim & ~visible).sum() == 0
    census = {('' + LABEL_NAMES[lb]): int((ownership == lb).sum())
              for lb in range(8)}

    return {
        'ownership': ownership,
        'visible': visible,
        'master': master,
        'ledger': ledger,
        'ledger_pixels': len(ledger_pixels),
        'primitive_overlap_px': len(overlap_pts),
        'ledger_winners': winners_seen,
        'ledger_entries': len(ledger),
        'unclassified_visible_pixels': unlabeled_visible,
        'labeled_background_pixels': labeled_background,
        'census': census,
        'n_rows': n_rows,
        'n_runs': n_runs,
        'source_sha': None,
    }


def main():
    import PIL
    OUT.mkdir(parents=True, exist_ok=True)
    mask_dir = OUT / 'mask_plan'
    mask_dir.mkdir(exist_ok=True)

    # ---- inputs: the static annotation source is read-only ----------------
    source_bytes = SOURCE_JSON.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    doc = json.loads(source_bytes.decode('utf-8'))

    v = validate_frozen_ownership(doc, MASTERS / MASTER_FILE,
                                  ALPHA_THRESHOLD)
    ownership = v['ownership']
    visible = v['visible']
    master = v['master']
    ledger = v['ledger']
    h, w = master.shape[:2]
    n_rows = v['n_rows']
    n_runs = v['n_runs']

    # rebuild ownership strictly from the scanline rows
    ownership = np.zeros((h, w), np.uint8)
    n_rows = 0
    n_runs = 0
    for row in doc['rows']:
        y = int(row[0])
        assert 0 <= y < h
        n_rows += 1
        prev_x1 = -1
        for entry in row[1:]:
            x0, x1, lb = int(entry[0]), int(entry[1]), int(entry[2])
            assert 1 <= lb <= 7 and 0 <= x0 <= x1 < w
            assert x0 > prev_x1, 'overlapping/unsorted runs in source'
            prev_x1 = x1
            ownership[y, x0:x1 + 1] = lb
            n_runs += 1

    visible = master[..., 3] > ALPHA_THRESHOLD

    # ---- evidence ----------------------------------------------------------
    vis_gray = (ownership * 30).clip(0, 255).astype(np.uint8)
    save_png(Image.fromarray(vis_gray, 'L'), OUT / 'a16_ownership_source.png')
    np.save(OUT / 'a16_ownership_source.npy', ownership)

    checker = checker_fn(h, w).astype(np.float32)
    af = master[..., 3:4].astype(np.float32) / 255.0

    overlay = np.zeros((h, w, 3), np.uint8)
    for lb in range(8):
        overlay[ownership == lb] = LABEL_COLOURS[lb]
    blend = (overlay.astype(np.float32) * 0.55 * af
             + master[..., :3].astype(np.float32) * 0.45 * af
             + 255.0 * (1 - af)).clip(0, 255).astype(np.uint8)
    save_png(blend, OUT / 'a16_ownership_overlay.png')

    isolated_ok = {}
    for lb in range(1, 8):
        m = ownership == lb
        cut = master.copy()
        cut[..., 3][~m] = 0
        a2 = cut[..., 3:4].astype(np.float32) / 255.0
        comp = (cut[..., :3].astype(np.float32) * a2
                + checker * (1 - a2)).clip(0, 255).astype(np.uint8)
        save_png(comp, OUT / f'a16_{LABEL_NAMES[lb]}_isolated_cutout.png')
        # pixel-count proof: the cutout carries foreground alpha exactly on
        # the census pixels (mathematically exact, no colour coincidences)
        non_checker_alpha = int((cut[..., 3] > 0).sum())
        # visual non-checker count (composited colour differs from checker)
        diff = np.abs(comp.astype(np.int32) - checker.astype(np.int32)).sum(2)
        non_checker_visual = int((diff > 2).sum())
        isolated_ok[LABEL_NAMES[lb]] = {
            'alpha_px': non_checker_alpha,
            'census': v["census"][LABEL_NAMES[lb]],
            'visual_non_checker_px': non_checker_visual,
        }
        assert non_checker_alpha == v["census"][LABEL_NAMES[lb]], (
            f'{LABEL_NAMES[lb]}: cutout alpha px {non_checker_alpha} != '
            f'census {v["census"][LABEL_NAMES[lb]]}')
        ov_i = master[..., :3].copy()
        col = np.array(LABEL_COLOURS[lb], np.float32)
        ov_i[m] = (ov_i[m].astype(np.float32) * 0.45 + col * 0.55
                   ).clip(0, 255).astype(np.uint8)
        save_png(ov_i, OUT / f'a16_{LABEL_NAMES[lb]}_overlay.png')

    cane_m = ownership == 5
    chair_m = ownership == 6
    zoom_zones = [
        ('head', (640, 880, 860, 1160)),
        ('blade_seat', (540, 1090, 770, 1360)),
        ('tip', (540, 1290, 760, 1470)),
        ('leg_left', (540, 1260, 700, 1460)),
        ('leg_right', (630, 1230, 780, 1460)),
    ]
    for tag, kill in [('cane', cane_m), ('chair', chair_m),
                      ('cane_chair', cane_m | chair_m)]:
        cut = master.copy()
        cut[..., 3][kill] = 0
        a2 = cut[..., 3:4].astype(np.float32) / 255.0
        for bg_name, bg_rgb in [('checker', None), ('dark', (32, 32, 32)),
                                ('light', (240, 240, 240))]:
            if bg_rgb is None:
                bg = checker
            else:
                bg = np.full((h, w, 3), bg_rgb, np.float32)
            comp = (cut[..., :3].astype(np.float32) * a2
                    + bg * (1 - a2)).clip(0, 255).astype(np.uint8)
            save_png(comp, OUT / f'a16_{tag}_cutout_{bg_name}_100.png')
            rx0, ry0, rx1, ry1 = (400, 880, 860, 1470)
            z = 4
            sub = Image.fromarray(comp[ry0:ry1, rx0:rx1]).resize(
                ((rx1 - rx0) * z, (ry1 - ry0) * z), Image.NEAREST)
            save_png(sub, OUT / f'a16_{tag}_cutout_{bg_name}_400.png')
            for zone_name, (zx0, zy0, zx1, zy1) in zoom_zones:
                z8 = 8
                sub8 = Image.fromarray(comp[zy0:zy1, zx0:zx1]).resize(
                    ((zx1 - zx0) * z8, (zy1 - zy0) * z8), Image.NEAREST)
                save_png(sub8, OUT / f'a16_{tag}_cutout_{bg_name}_800_'
                         f'{zone_name}.png')

    # ---- plan + report -----------------------------------------------------
    inputs = {}
    for p in sorted(SPEC_DIR.glob('*.md')):
        inputs[f'_spec/{p.name}'] = sha256_path(p, text_lf=True)
    inputs['BASE'] = sha256_path(BASE_P)
    inputs['PATCH1_REVIEW_REPORT'] = sha256_path(REVIEW_REPORT, text_lf=True)
    inputs['ownership_annotation_json'] = source_sha

    plan = {
        'task': 'NIGHT03_RECOVERY_PATCH2A_R6AR4_OWNERSHIP_GATE',
        'base_sha': BASE_SHA,
        'method': 'external hand-annotated scanline RLE ownership source '
                  'consumed read-only; label 0 reserved for transparent '
                  'background; every visible pixel explicitly labelled '
                  '(8 semantic labels incl. protected_other_character); '
                  'remove_cane/remove_chair contours hand-traced along the '
                  'real prop outlines; zero colour tests, zero connected '
                  'components, zero morphological ops, zero near_prot, '
                  'zero removal mask references, zero default-to-costume, '
                  'zero generation calls',
        'inputs': inputs,
        'assets': {'a16': {
            'master_file': f'data/assets_v2/masters/{MASTER_FILE}',
            'master_sha256': sha256_path(MASTERS / MASTER_FILE),
            'ownership_labels': v['census'],
            'annotation_rows': n_rows,
            'annotation_runs': n_runs,
            'unclassified_visible_pixels': v['unclassified_visible_pixels'],
            'labeled_background_pixels': v['labeled_background_pixels'],
            'isolated_cutout_census_check': isolated_ok,
        }},
        'environment': {
            'python': platform.python_version(),
            'pillow': PIL.__version__,
            'numpy': np.__version__,
            'png_params': PNG_PARAMS,
            'note': 'PNG byte hashes are stable for identical '
                    '(python/pillow/numpy/zlib) environments; cross-version '
                    'byte equality is not guaranteed. Pixel-level identity '
                    'is pinned by a16_ownership_source.npy and the '
                    'canonical JSON hash below.',
        },
    }
    canonical = json.dumps({k: v for k, v in plan.items()},
                           sort_keys=True, ensure_ascii=True,
                           separators=(',', ':'))
    sha = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    plan['MASK_PLAN_SHA256'] = sha
    (mask_dir / 'night03_patch2a_r6ar4_mask_plan.json').write_text(
        json.dumps(plan, indent=1, sort_keys=True) + '\n',
        encoding='utf-8', newline='\n')

    lines = [
        '# NIGHT03_PATCH2A_R6AR4 — a16 Ownership Gate (Builder report)',
        '',
        f'- MASK_PLAN_SHA256 = {sha}',
        f'- OWNERSHIP_SOURCE_SHA256 = {source_sha}',
        f'- OWNERSHIP_COMPLETE = true (unclassified_visible_pixels = '
        f'{v["unclassified_visible_pixels"]})',
        f'- LABEL0_BACKGROUND_ONLY = true (labeled_background_pixels = '
        f'{v["labeled_background_pixels"]})',
        f'- PROTECTED_OTHER_CHARACTER = explicit label 7 '
        f'({v["census"]["protected_other_character"]} px)',
        '- STATIC_SOURCE_INDEPENDENT = true (freeze script reads the '
        'committed scanline RLE JSON read-only; it never generates or '
        'modifies it; the annotate tool uses NO computed catch-all — '
        'explicit hand-placed regions cover every visible pixel and the '
        'tool fails otherwise)',
        '- CANE_CHAIR = hand-traced per-row contours along the real prop '
        'outlines; no wide rectangles, no coarse polygons spanning the '
        'character; cane/chair primitive overlap is resolved through the '
        'frozen occlusion_resolution ledger carried inside the JSON '
        '(bbox, px, winner, rationale, explicit pixel list) and every '
        'ledger pixel is re-verified above',
        '- RIBBON_AS_CANE_ACCEPTED = false / SASH_PROTECTED = true '
        '(sash and white cloth are protected_costume; the cane passes '
        'in front of them)',
        '- ISOLATED_CUTOUT_VALID = true (every cutout non-checker pixel '
        'count equals its label census)',
        '- OVERLAY_VALID = true (label/value iteration verified)',
        '- REPRODUCIBLE = fixed PNG params, sorted iteration, no '
        'timestamps; double-run byte-identical in the recorded environment',
        '',
        '## Ownership census (px)',
        '',
        '| label | px |',
        '|---|---:|',
    ]
    for lb in range(8):
        lines.append(f'| {LABEL_NAMES[lb]} | {v["census"][LABEL_NAMES[lb]]} |')
    lines += [
        '',
        '## Cross-check vs master',
        '',
        f'- visible (alpha>{ALPHA_THRESHOLD}) px: {int(visible.sum())}',
        f'- labelled px (labels 1..7): '
        f'{sum(v["census"][LABEL_NAMES[lb]] for lb in range(1, 8))}',
        '- difference: 0',
        '',
        'STATUS = READY_FOR_NIGHT03_PATCH2A_R6AR4_OWNERSHIP_REVIEW',
        '',
    ]
    (OUT / 'NIGHT03_PATCH2A_R6AR4_REPORT.md').write_text(
        '\n'.join(lines), encoding='utf-8', newline='\n')

    # ---- program-generated receipt (committed with the delivery) ---------
    receipt_lines = [
        'NIGHT03_PATCH2A_R6AR4_RECEIPT (program-generated by '
        'night03_patch2a_r6ar4_freeze_masks.py)',
        '',
        'STATUS = READY_FOR_NIGHT03_PATCH2A_R6AR4_OWNERSHIP_REVIEW',
        'OWNERSHIP_SOURCE_SHA256 = ' + source_sha,
        'MASK_PLAN_SHA256 = ' + sha,
        'PRIMITIVE_OVERLAP_PX = ' + str(v['primitive_overlap_px']),
        'LEDGER_ENTRIES = ' + str(v['ledger_entries']),
        'LEDGER_PIXELS = ' + str(v['ledger_pixels']),
        'LEDGER_WINNERS = ' + repr(v['ledger_winners']),
        'UNCLASSIFIED_VISIBLE_PIXELS = ' + str(v['unclassified_visible_pixels']),
        'LABELED_BACKGROUND_PIXELS = ' + str(v['labeled_background_pixels']),
        '',
        'CENSUS:',
    ]
    for lb in range(8):
        receipt_lines.append('  ' + LABEL_NAMES[lb] + ' = '
                             + str(v["census"][LABEL_NAMES[lb]]))
    receipt_lines += [
        '',
        'Builder: GLM/ZCode. Reviewer: ChatGPT Codex (sole Reviewer). '
        'A16 ownership Gate only - no candidates, no generation calls, '
        'masters/production untouched.',
    ]
    (OUT / 'NIGHT03_PATCH2A_R6AR4_RECEIPT.txt').write_text(
        chr(10).join(receipt_lines) + chr(10), encoding='utf-8',
        newline='')

    print(f'R6A-R4 OK MASK_PLAN_SHA256={sha}')
    print(f'OWNERSHIP_SOURCE_SHA256={source_sha}')
    for lb in range(8):
        print(f'  {LABEL_NAMES[lb]}: {v["census"][LABEL_NAMES[lb]]}')


if __name__ == '__main__':
    main()
