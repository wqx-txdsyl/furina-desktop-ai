"""NIGHT-03 Patch 2B R1A-R4 — mask/plan freeze (single entry).

Consumes the three static authoritative annotation sources in
data/assets_v2/annotation_sources/night03_patch2b_r1a_r4/ strictly
read-only and generates every R1A-R4 deliverable into
data/assets_v2/repair_candidates/night03_patch2b_r1a_r4/.

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
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'data/assets_v2/annotation_sources/night03_patch2b_r1a_r4'
R6AR4_JSON = ROOT / ('data/assets_v2/repair_candidates/'
                     'night03_patch2a_r6ar4/a16_ownership_annotation.json')
R4_MASKS = ROOT / ('data/assets_v2/repair_candidates/'
                   'night03_patch2a_r4/mask_plan')
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b_r1a_r4'

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
A16_PROP_UNION_PX = 36124
ZOOM_REGIONS = {
    'hand': (705, 920, 805, 1075),
    'cuff': (695, 1060, 750, 1125),
    'seat': (490, 1205, 680, 1295),
    'blade': (625, 1125, 675, 1285),
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


def runs_of(row_mask):
    xs = np.where(row_mask)[0]
    if xs.size == 0:
        return []
    sp = np.where(np.diff(xs) > 1)[0]
    st = np.concatenate(([0], sp + 1))
    en = np.concatenate((sp, [xs.size - 1]))
    return [(int(xs[s]), int(xs[e])) for s, e in zip(st, en)]


def checker(h, w, c=12):
    yy, xx = np.mgrid[0:h, 0:w]
    return np.where((((xx // c) + (yy // c)) % 2 == 0)[..., None],
                    200, 150).astype(np.float32)


def mirror_mask(mask, w):
    out = np.zeros_like(mask)
    ys, xs = np.where(mask)
    out[ys, (w - 1) - xs] = True
    return out


def save_mask_png(mask, path, written):
    Image.fromarray(np.where(mask, 255, 0).astype(np.uint8)).save(path)
    written.append(path.relative_to(OUT).as_posix())


def save_npy(mask, path, written):
    np.save(path, mask.astype(np.uint8))
    written.append(path.relative_to(OUT).as_posix())


def composite(master, bg=None):
    af = master[..., 3:4].astype(np.float32) / 255.0
    background = checker(master.shape[0], master.shape[1]) if bg is None else bg
    return master[..., :3].astype(np.float32) * af + background * (1 - af)


def save_png(arr, path, written):
    Image.fromarray(arr.astype(np.uint8)).save(path)
    written.append(path.relative_to(OUT).as_posix())


def validate_a16_source(doc, union):
    rows = doc.get('rows')
    if not isinstance(rows, list) or not rows:
        raise FreezeError('a16 source: rows missing/empty')
    sem = np.full((H, W), -1, np.int16)
    vocab = doc.get('class_vocabulary')
    if vocab != CLASSES:
        raise FreezeError(f'a16 source: unexpected class vocabulary {vocab}')
    for row in rows:
        if not (isinstance(row, list) and len(row) >= 2):
            raise FreezeError('a16 source: malformed row')
        y = int(row[0])
        if not (0 <= y < H):
            raise FreezeError(f'a16 source: row y={y} outside canvas')
        for a, b, cname in row[1:]:
            if cname not in CLASSES:
                raise FreezeError(f'a16 source: unknown class {cname!r}')
            if not (0 <= int(a) <= int(b) < W):
                raise FreezeError(f'a16 source: run {a}-{b} outside canvas')
            span = sem[y, int(a):int(b) + 1]
            if (span != -1).any():
                raise FreezeError(
                    f'a16 source: duplicate px in row y={y} '
                    f'x{a}-{b} (overlapping runs)')
            sem[y, int(a):int(b) + 1] = CLASSES.index(cname)
    labeled = (sem != -1) & union
    n_labeled = int(labeled.sum())
    if n_labeled != A16_PROP_UNION_PX:
        raise FreezeError(
            f'a16 source: labeled {n_labeled} != prop union '
            f'{A16_PROP_UNION_PX}')
    if (sem != -1)[~union].any():
        raise FreezeError('a16 source: labeled px outside prop union')
    counts = {c: int(((sem == i) & union).sum()) for i, c in enumerate(CLASSES)}
    if sum(counts.values()) != A16_PROP_UNION_PX:
        raise FreezeError('a16 source: class sum != prop union')
    return sem, counts


def build_prop_union():
    doc = json.loads(R6AR4_JSON.read_text(encoding='utf-8'))
    m16 = np.array(Image.open(
        MASTERS / MASTERS_FILES['a16']).convert('RGBA'))
    vis = m16[..., 3] > ALPHA
    cane = rebuild_runs(doc['primitives']['remove_cane'], H, W) & vis
    chair = rebuild_runs(doc['primitives']['remove_chair'], H, W) & vis
    return cane | chair


def main():
    written = []
    OUT.mkdir(parents=True, exist_ok=True)
    report = ['# NIGHT03_PATCH2B_R1A_R4 — mask/plan freeze', '']
    receipt = ['NIGHT03_PATCH2B_R1A_R4_RECEIPT (program-generated)', '']
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
        raw = rebuild_runs(doc['rows'], h, w)  # RAW: nothing clipped

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
        # source-map closure: mirroring the destination must reproduce
        # the tail source exactly (every dest px's pre-image ∈ tail)
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
        }
        tail_stats[asset] = stats
        for name, mask in [('tail_source', tail_src),
                           ('tail_destination', dest),
                           ('tail_visible_destination', vis_dest),
                           ('tail_underlay', underlay)]:
            save_mask_png(mask, adir / f'{asset}_{name}.png', written)
            save_npy(mask, adir / f'{asset}_{name}.npy', written)
        report.append(f'## {asset} tail (raw gates pre-validated, '
                      'zero clipping)')
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

    # six independent class masks (PNG + NPY)
    for i, cname in enumerate(CLASSES):
        m = (sem == i) & union
        save_mask_png(m, OUT / f'a16_class_{cname}.png', written)
        save_npy(m, OUT / f'a16_class_{cname}.npy', written)
        # per-class isolated cutout over checker
        cut = master16.copy()
        cut[..., 3][~m] = 0
        save_png(composite(cut, bgc),
                 OUT / f'a16_class_{cname}_cutout.png', written)

    # indexed/palette partition preserving class values (0-5);
    # outside-union uses reserved index 6 (transparent), never class 0
    idx = np.full((H, W), 6, np.uint8)
    for i, cname in enumerate(CLASSES):
        idx[(sem == i) & union] = i
    pal = Image.fromarray(idx, 'P')
    palette = []
    for cname in CLASSES:
        palette.extend(CLASS_COLOURS[cname])
    palette.extend([0, 0, 0])
    pal.putpalette(palette)
    pal.save(OUT / 'a16_occlusion_partition_indexed.png',
             transparency=6)
    written.append('a16_occlusion_partition_indexed.png')

    # colour composite partition
    colp = base16.copy()
    for i, cname in enumerate(CLASSES):
        m = (sem == i) & union
        rgb = np.array(CLASS_COLOURS[cname], np.float32)
        colp[m] = colp[m] * (0.35 if cname != 'transparent' else 0.55) + rgb * (
            0.65 if cname != 'transparent' else 0.45)
    save_png(colp, OUT / 'a16_occlusion_partition_color.png', written)

    # master semantic overlay
    save_png(colp, OUT / 'a16_semantic_overlay.png', written)

    # 400% / 800% zoom evidence: hand, cuff, seat, blade
    for tag, (x0, y0, x1, y1) in ZOOM_REGIONS.items():
        for z in (4, 8):
            sub = Image.fromarray(colp[y0:y1, x0:x1].astype(np.uint8)).resize(
                ((x1 - x0) * z, (y1 - y0) * z), Image.NEAREST)
            sub.save(OUT / f'a16_zoom_{tag}_{z * 100}.png')
            written.append(f'a16_zoom_{tag}_{z * 100}.png')

    report.append('## a16 occlusion (static source, exact cover)')
    report.append(f'- prop_union_px: {A16_PROP_UNION_PX}')
    for cname in CLASSES:
        report.append(f'- class {cname}: {counts[cname]}')
    report.append('- labeled_outside_prop_union: 0')
    report.append('- duplicate_pixels: 0')
    report.append('- unknown_class_pixels: 0')
    report.append('- off-canvas px counted as transparent: 0')
    report.append('')
    receipt.append('A16_PROP_UNION_PX = '
                   f'{A16_PROP_UNION_PX}')
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
    report.append('- a16 labeled == R6A-R4 prop union == 36124')
    report.append('')
    report.append('sources: data/assets_v2/annotation_sources/'
                  'night03_patch2b_r1a_r4/ (static, read-only, '
                  'never created or modified by this freeze)')
    report.append('')
    status = 'READY_FOR_NIGHT03_PATCH2B_R1A_R4_PLAN_REVIEW'
    report.append(f'STATUS = {status}')
    (OUT / 'NIGHT03_PATCH2B_R1A_R4_REPORT.md').write_text(
        '\n'.join(report) + '\n', encoding='utf-8', newline='\n')
    receipt.append(f'STATUS = {status}')
    (OUT / 'NIGHT03_PATCH2B_R1A_R4_RECEIPT.txt').write_text(
        '\n'.join(receipt) + '\n', encoding='utf-8', newline='\n')
    written.append('NIGHT03_PATCH2B_R1A_R4_REPORT.md')
    written.append('NIGHT03_PATCH2B_R1A_R4_RECEIPT.txt')

    # ================= manifest LAST ===================================
    present = sorted(p.relative_to(OUT).as_posix()
                     for p in OUT.rglob('*')
                     if p.is_file() and p.name != 'manifest.json')
    if present != sorted(written):
        raise FreezeError(
            f'unexpected files in output: '
            f'{set(present) ^ set(written)}')
    manifest = {rel: sha256_bytes((OUT / rel).read_bytes())
                for rel in present}
    (OUT / 'manifest.json').write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + '\n',
        encoding='utf-8', newline='\n')

    print(f'R1A-R4 freeze OK files={len(present) + 1} '
          f'a16_prop={A16_PROP_UNION_PX} a16_classes='
          f'{json.dumps(counts, sort_keys=True)}')
    for asset in ('a01', 'a05'):
        print(f"  {asset}: source={tail_stats[asset]['tail_source_px']} "
              f"raw_gates=0/0 mirror_outside=0")


if __name__ == '__main__':
    main()
