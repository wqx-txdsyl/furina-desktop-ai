"""NIGHT-03 Patch 2B R1B-R1 — a16 re-attempt + destination evidence.

SCOPE (R1B-R1 task book):
  * a01/a05 candidates, R1A frozen plan, masters, production: byte-locked
    (not rebuilt; only NEW destination-side evidence is added).
  * a16 reconstruction source remade (best effort inside the frozen
    union) + honest visual self-gate.
  * Blocker documentation: pixel-exact proof of why the frozen plan
    cannot yield a natural hand structure.

Deterministic, offline, fixed-Huffman PNGs, manifest LAST.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import night03_patch2b_r1b_fixedpng as fxpng  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'data/assets_v2/annotation_sources/night03_patch2b_r1b_r1'
R1A_SRC = ROOT / ('data/assets_v2/annotation_sources/'
                  'night03_patch2b_r1a_r6')
R1B_OUT = ROOT / ('data/assets_v2/repair_candidates/'
                  'night03_patch2b_r1b')
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b_r1b_r1'

H, W = 1536, 1024
ALPHA = 8


class BuildError(RuntimeError):
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


def mirror_mask(mask, w):
    out = np.zeros_like(mask)
    ys, xs = np.where(mask)
    out[ys, (w - 1) - xs] = True
    return out


def checker(h, w, c=12):
    yy, xx = np.mgrid[0:h, 0:w]
    return np.where((((xx // c) + (yy // c)) % 2 == 0)[..., None],
                    200, 150).astype(np.float32)


def composite(master, background):
    af = master[..., 3:4].astype(np.float32) / 255.0
    return master[..., :3].astype(np.float32) * af + background * (1 - af)


def solid16(rgb):
    return np.full((H, W, 3), rgb, np.float32)


def main():
    written = []
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- source pins ---------------------------------------------------
    smf = json.loads((SRC / 'source_manifest.json')
                     .read_text(encoding='utf-8'))
    for rel, expected in sorted(smf['files'].items()):
        if 'night03_patch2b_r1b_r1' in rel:
            fpath = SRC / Path(rel).name
        else:
            fpath = ROOT / rel
        actual = sha256_bytes(fpath.read_bytes())
        if actual != expected:
            raise BuildError(f'R1B-R1 source {rel} SHA256 mismatch')

    recon = np.array(Image.open(
        SRC / 'a16_reconstruction_source.png').convert('RGBA'))
    occ = json.loads((R1A_SRC / 'a16_occlusion_annotation.json')
                     .read_text(encoding='utf-8'))
    sem = np.full((H, W), -1, np.int16)
    for row in occ['rows']:
        y = int(row[0])
        for a, b, cn in row[1:]:
            sem[y, int(a):int(b) + 1] = occ['class_vocabulary'].index(cn)
    UNION = sem >= 0
    m_trans = UNION & (sem == 0)
    m_non = UNION & (sem > 0)

    master16 = np.array(Image.open(
        MASTERS / 'furina_v2_a16_work_focused.png').convert('RGBA'))
    cand16 = master16.copy()
    cand16[m_trans] = [0, 0, 0, 0]
    cand16[m_non] = recon[m_non]

    report = ['# NIGHT03_PATCH2B_R1B_R1 — a16 re-attempt + evidence fix',
              '']
    receipt = ['NIGHT03_PATCH2B_R1B_R1_RECEIPT (program-generated)', '']
    receipt.append('TASK_ID = NIGHT03_RECOVERY_PATCH2B_R1B_R1')
    receipt.append('BASE_SHA = d9e1e2c08982c5e246d69625f3ba2b6b807c4e21')
    receipt.append('')

    # ---- 1. a01/a05 destination-side evidence --------------------------
    DEST_REGIONS = {
        'a01': {
            'tail_root_dest': (694, 1040, 874, 1180),
            'staff_junction_dest': (694, 1040, 794, 1230),
            'tail_tip_dest': (724, 1230, 874, 1370),
        },
        'a05': {
            'bow_tail_root_dest': (614, 900, 884, 1010),
            'dress_edge_dest': (633, 900, 683, 990),
            'tail_tip_dest': (724, 1140, 884, 1300),
        },
    }
    for asset in ('a01', 'a05'):
        master = np.array(Image.open(
            MASTERS / ('furina_v2_' + asset + '_' +
                       ('stand_neutral_front.png' if asset == 'a01' else
                        'stand_confident_proud.png'))).convert('RGBA'))
        h, w = master.shape[:2]
        cand = np.array(Image.open(
            R1B_OUT / asset / f'{asset}_candidate.png').convert('RGBA'))
        tdoc = json.loads((R1A_SRC / f'{asset}_tail_source.json')
                          .read_text(encoding='utf-8'))
        source = runs_rebuild(tdoc['rows'], h, w)
        dest = mirror_mask(source, w)
        bg = checker(h, w)
        comp_m = composite(master, bg)
        comp_c = composite(cand, bg)
        adir = OUT / asset
        adir.mkdir(parents=True, exist_ok=True)
        n_files = 0
        for tag, (x0, y0, x1, y1) in DEST_REGIONS[asset].items():
            for z in (2, 4, 8):
                a = Image.fromarray(comp_m[y0:y1, x0:x1].astype(np.uint8)) \
                    .resize(((x1 - x0) * z, (y1 - y0) * z), Image.NEAREST)
                b = Image.fromarray(comp_c[y0:y1, x0:x1].astype(np.uint8)) \
                    .resize(((x1 - x0) * z, (y1 - y0) * z), Image.NEAREST)
                cv = Image.new('RGB', (a.width * 2 + 8, a.height),
                               (255, 0, 0))
                cv.paste(a, (0, 0))
                cv.paste(b, (a.width + 8, 0))
                rel = f'{asset}/{asset}_dest_crop_{tag}_{z * 100}.png'
                fxpng.write_png_rgb(OUT / rel, np.array(cv))
                written.append(rel)
                n_files += 1
                if z == 4:
                    report.append(f'- {asset} destination evidence: {rel}')
        receipt.append(f'{asset.upper()}_DEST_EVIDENCE_FILES = {n_files}')
    receipt.append('')

    # ---- 2. a16 candidate (remade reconstruction) -----------------------
    adir = OUT / 'a16'
    adir.mkdir(parents=True, exist_ok=True)
    fxpng.write_png_rgba(OUT / 'a16/a16_candidate.png', cand16)
    written.append('a16/a16_candidate.png')

    # ---- 3. blocker documentation (pixel-exact proof) -------------------
    gap1 = int(((UNION & (sem == 0))[1055:1080, 700:750]).sum())
    gap2 = int(((UNION & (sem == 0))[985:1015, 700:760]).sum())
    report.append('## frozen-plan hand blocker (pixel-exact)')
    report.append(f'- transparent-class px in y[1055,1080) x[700,750): '
                  f'{gap1} (severs the fist/wrist from the cuff band; a '
                  'natural gripping hand needs these rows as glove/skin)')
    report.append(f'- transparent-class px in y[985,1015) x[700,760): '
                  f'{gap2} (severs the dome-reveal fingers from the fist '
                  'below)')
    report.append('- per task book: mask expansion / semantic '
                  'reclassification is forbidden for the Builder; '
                  'R1A_REOPEN_REQUIRED = true')

    zoom = composite(master16, checker(H, W))[980:1135, 690:775]
    z = Image.fromarray(zoom.astype(np.uint8)).resize((85 * 6, 155 * 6),
                                                      Image.NEAREST)
    zd = ImageDraw.Draw(z)
    zd.rectangle([(700 - 690) * 6, (1055 - 980) * 6,
                  (750 - 690) * 6, (1080 - 980) * 6],
                 outline=(255, 0, 0), width=3)
    zd.rectangle([(700 - 690) * 6, (985 - 980) * 6,
                  (760 - 690) * 6, (1015 - 980) * 6],
                 outline=(255, 160, 0), width=3)
    fxpng.write_png_rgb(OUT / 'a16/a16_hand_blocker_proof_6x.png',
                        np.array(z))
    written.append('a16/a16_hand_blocker_proof_6x.png')

    # ---- 4. a16 evidence set --------------------------------------------
    bgs = {'checker': None, 'light': (240, 240, 240), 'dark': (32, 32, 32)}
    for bg_name, bg_rgb in bgs.items():
        bg = checker(H, W) if bg_rgb is None else solid16(bg_rgb)
        comp_c = composite(cand16, bg)
        rel = f'a16/a16_{bg_name}_full.png'
        fxpng.write_png_rgb(OUT / rel, comp_c.astype(np.uint8))
        written.append(rel)
        for size in (512, 256, 128):
            img = Image.fromarray(comp_c.astype(np.uint8)).resize(
                (size, size), Image.LANCZOS)
            rel2 = f'a16/a16_{bg_name}_{size}.png'
            fxpng.write_png_rgb(OUT / rel2, np.array(img.convert('RGB')))
            written.append(rel2)

    # ---- report + receipt ===============================================
    report.append('')
    report.append('## honest self-gate')
    report.append('- a01/a05: candidates untouched (byte-locked); '
                  'destination-side evidence now provided')
    report.append('- a16: best-effort reconstruction inside the frozen '
                  'union; the hand region cannot form a natural '
                  'structure because the frozen transparent rows sever '
                  'the wrist (see blocker documentation)')
    report.append('')
    status = 'NIGHT03_PATCH2B_R1B_R1_BLOCKED_BY_FROZEN_PLAN'
    report.append(f'STATUS = {status}')
    report.append('R1A_REOPEN_REQUIRED = true')
    (OUT / 'NIGHT03_PATCH2B_R1B_R1_REPORT.md').write_text(
        '\n'.join(report) + '\n', encoding='utf-8', newline='\n')
    receipt.append('SELF_GATE_PASS = false')
    receipt.append('A16_STATUS = FAIL_FROZEN_PLAN_INSUFFICIENT')
    receipt.append('R1A_REOPEN_REQUIRED = true')
    receipt.append(f'STATUS = {status}')
    (OUT / 'NIGHT03_PATCH2B_R1B_R1_RECEIPT.txt').write_text(
        '\n'.join(receipt) + '\n', encoding='utf-8', newline='\n')
    written.append('NIGHT03_PATCH2B_R1B_R1_REPORT.md')
    written.append('NIGHT03_PATCH2B_R1B_R1_RECEIPT.txt')

    present = sorted(p.relative_to(OUT).as_posix()
                     for p in OUT.rglob('*')
                     if p.is_file() and p.name != 'manifest.json')
    if present != sorted(written):
        raise BuildError(f'unexpected files: {set(present) ^ set(written)}')
    mf = {rel: sha256_bytes((OUT / rel).read_bytes()) for rel in present}
    (OUT / 'manifest.json').write_text(
        json.dumps(mf, indent=1, sort_keys=True) + '\n',
        encoding='utf-8', newline='\n')
    print(f'R1B-R1 build OK files={len(present) + 1} (STATUS = {status})')


if __name__ == '__main__':
    main()
