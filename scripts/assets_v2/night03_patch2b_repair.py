"""NIGHT-03 Recovery Patch 2B step 2 — candidate repair + full evidence.

Reads ONLY: the masters, the frozen allowed-edit masks written by
night03_patch2b_freeze_allowed.py, and the frozen PATCH2A R4 term masks.

Repair semantics (identical for every asset, master is the only colour
source):
  1. old tail removed            -> alpha 0 on the frozen tail_source mask
  2. authorized/speck cleanup    -> alpha 0 on the frozen cleanup mask
  3. a16 cane+chair removal      -> alpha 0 on the R6A-R4 ownership union
  4. tail migration              -> tail_destination pixels are painted
                                    with their horizontal mirror source
                                    pixels (RGB+alpha) from the master
  5. seam reconstruction         -> seam pixels are painted with their
                                    horizontal mirror source pixels

The changed-pixel set is then audited: every changed pixel must lie
inside the frozen allowed-edit mask (unauthorized diff must be 0).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
FROZEN = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b/frozen'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b'
MASTERS_FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}
CLEAR_MASKS = {
    'a01': ['tail_source', 'authorized_cleanup'],
    'a05': ['tail_source', 'authorized_cleanup'],
    'a16': ['tail_source', 'speck_cleanup'],
}


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def load_mask(p):
    return np.array(Image.open(p).convert('L')) > 127


def checker(h, w, c=24):
    yy, xx = np.mgrid[0:h, 0:w]
    t = ((xx // c) + (yy // c)) % 2 == 0
    return np.where(t, 200, 150).astype(np.uint8)


def on_bg(rgb, alpha, bg):
    a = alpha[..., None].astype(np.float32) / 255.0
    return (rgb.astype(np.float32) * a + bg[..., None].astype(np.float32)
            * (1 - a)).clip(0, 255).astype(np.uint8)


def repair_asset(asset, master_name):
    W = 1024
    master = np.array(Image.open(MASTERS / master_name).convert('RGBA'))
    h, w = master.shape[:2]
    dst = master.copy()

    # 1+2. removals (alpha -> 0)
    for term in CLEAR_MASKS[asset]:
        m = load_mask(FROZEN / f'{asset}_{term}.png')
        dst[..., 3][m] = 0
    if asset == 'a16':
        m5 = load_mask(FROZEN / 'a16_remove_cane_r6ar4.png')
        m6 = load_mask(FROZEN / 'a16_remove_chair_r6ar4.png')
        dst[..., 3][m5] = 0
        dst[..., 3][m6] = 0

    # 4+5. mirror-paint (tail destination + seam reconstruction)
    for term in ['tail_destination', 'seam_reconstruction']:
        m = load_mask(FROZEN / f'{asset}_{term}.png')
        ys, xs = np.where(m)
        sx = (W - 1) - xs
        dst[ys, xs, 0] = master[ys, sx, 0]
        dst[ys, xs, 1] = master[ys, sx, 1]
        dst[ys, xs, 2] = master[ys, sx, 2]
        dst[ys, xs, 3] = master[ys, sx, 3]

    return master, dst


def audit(master, dst, allowed):
    changed = np.any(master != dst, axis=2)
    unauthorized = changed & ~allowed
    return changed, unauthorized


def evidence(asset, master, dst, changed, outdir):
    h, w = master.shape[:2]
    bgc = checker(h, w)
    rgb_m, a_m = master[..., :3], master[..., 3]
    rgb_d, a_d = dst[..., :3], dst[..., 3]

    # triptych: master / candidate / changed-overlay on checker
    overlay = on_bg(rgb_d, a_d, bgc)
    ov = overlay.copy()
    ov[changed] = (0.4 * ov[changed] + 0.6 * np.array([255, 0, 255]))
    tri = np.concatenate([on_bg(rgb_m, a_m, bgc), overlay, ov], axis=1)
    Image.fromarray(tri).save(outdir / f'{asset}_triptych.png')

    # candidate on three backgrounds, whole image
    for name, bg in [('checker', checker(h, w)), ('dark', np.full((h, w), 32, np.uint8)),
                     ('light', np.full((h, w), 240, np.uint8))]:
        comp = on_bg(rgb_d, a_d, bg)
        Image.fromarray(comp).save(outdir / f'{asset}_candidate_{name}_full.png')
        img = Image.fromarray(comp)
        for s in (512, 256, 128):
            img.resize((s, int(s * h / w)), Image.LANCZOS).save(
                outdir / f'{asset}_candidate_{name}_{s}.png')
        for z, tag in ((2, '200'), (4, '400')):
            zones = ([('tip', (540, 880, 900, 1470))] if asset != 'a16' else
                     [('tip', (540, 880, 900, 1470)),
                      ('seat', (390, 1180, 730, 1360))])
            for zn, (x0, y0, x1, y1) in zones:
                crop = Image.fromarray(comp[y0:y1, x0:x1]).resize(
                    ((x1 - x0) * z, (y1 - y0) * z), Image.NEAREST)
                crop.save(outdir / f'{asset}_candidate_{name}_{tag}_{zn}.png')


def main():
    outdir = OUT
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {}

    frozen_inputs = json.loads(
        (FROZEN / 'frozen_inputs.json').read_text(encoding='utf-8'))
    manifest['frozen_inputs'] = frozen_inputs
    # the frozen allowed-edit masks are themselves inputs
    for asset in MASTERS_FILES:
        p = FROZEN / f'{asset}_allowed_edit.png'
        manifest[f'{asset}:frozen_allowed_edit'] = sha256_bytes(p.read_bytes())

    meta_all = {}
    for asset, master_name in MASTERS_FILES.items():
        allowed = load_mask(FROZEN / f'{asset}_allowed_edit.png')
        master, dst = repair_asset(asset, master_name)
        changed, unauthorized = audit(master, dst, allowed)
        n_unauth = int(unauthorized.sum())
        n_changed = int(changed.sum())
        assert n_unauth == 0, (
            f'{asset}: {n_unauth} unauthorized diff pixels outside the '
            f'frozen allowed edit')

        cand_path = outdir / f'{asset}_repair.png'
        Image.fromarray(dst).save(cand_path)
        evidence(asset, master, dst, changed, outdir)

        meta = {
            'asset': asset,
            'master_file': MASTERS_FILES[asset],
            'master_sha256': sha256_bytes(
                (MASTERS / master_name).read_bytes()),
            'candidate_sha256': sha256_bytes(cand_path.read_bytes()),
            'dimensions': [int(dst.shape[1]), int(dst.shape[0])],
            'changed_px': n_changed,
            'unauthorized_diff_px': n_unauth,
            'allowed_edit_px': int(allowed.sum()),
            'frozen_allowed_edit_sha256': manifest[
                f'{asset}:frozen_allowed_edit'],
        }
        meta_all[asset] = meta
        mp = outdir / f'{asset}_metadata.json'
        mp.write_text(json.dumps(meta, indent=1, sort_keys=True),
                      encoding='utf-8', newline='\n')
        manifest[f'{asset}:metadata'] = sha256_bytes(mp.read_bytes())
        print(f'{asset}: changed={n_changed} unauthorized={n_unauth}')

    for p in sorted(outdir.rglob('*')):
        if p.is_file() and p.name != 'manifest.json':
            manifest[p.relative_to(outdir).as_posix()] = sha256_bytes(
                p.read_bytes())
    (outdir / 'manifest.json').write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding='utf-8',
        newline='\n')

    meta_path = outdir / 'asset_metadata.json'
    meta_path.write_text(json.dumps(meta_all, indent=1, sort_keys=True),
                         encoding='utf-8', newline='\n')
    print('patch2b candidates + evidence complete')


if __name__ == '__main__':
    main()
