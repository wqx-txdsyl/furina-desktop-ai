"""NIGHT-03 Recovery Patch 2B step 1 — freeze the allowed edits BEFORE any
candidate exists.

Inputs (read-only):
  * master a01/a05/a16
  * the committed PATCH2A R4 mask freeze PNGs (tail migration, seams,
    cleanups) under data/assets_v2/repair_candidates/night03_patch2a_r4/
  * the committed PATCH2A R6A-R4 ownership annotation JSON (a16 cane/chair
    removal primitives)

Outputs (night03_patch2b/frozen/):
  * a0X_allowed_edit.png          - the frozen allowed-edit mask (L mode)
  * a16_remove_cane_r6ar4.png / a16_remove_chair_r6ar4.png provenance copies
  * frozen_inputs.json            - SHA256 of every input consumed

Nothing here writes a candidate image.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
M4 = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r4/mask_plan'
R6AR4 = ROOT / ('data/assets_v2/repair_candidates/night03_patch2a_r6ar4/'
                'a16_ownership_annotation.json')
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b/frozen'
MASTERS_FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}


def sha256_path(p):
    h = hashlib.sha256()
    with open(p, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_mask(p):
    m = np.array(Image.open(p).convert('L'))
    return m > 127


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inputs = {}

    for asset, master_name in MASTERS_FILES.items():
        master_path = MASTERS / master_name
        inputs[f'{asset}:master'] = sha256_path(master_path)
        m4dir = M4 / asset
        terms = []
        if asset in ('a01', 'a05'):
            terms = ['tail_source', 'tail_destination',
                     'seam_reconstruction', 'authorized_cleanup']
        else:
            terms = ['tail_source', 'tail_destination',
                     'seam_reconstruction', 'speck_cleanup',
                     'hand_reconstruction']
        allowed = np.zeros((1536, 1024), bool)
        for term in terms:
            mp = m4dir / f'{asset}_{term}.png'
            m = load_mask(mp)
            inputs[f'{asset}:mask:{term}'] = sha256_path(mp)
            allowed |= m
            Image.fromarray(np.where(m, 255, 0).astype(np.uint8)).save(
                OUT / f'{asset}_{term}.png')
        if asset == 'a16':
            doc = json.loads(R6AR4.read_text(encoding='utf-8'))

            def rebuild(rows_spec):
                mask = np.zeros((1536, 1024), bool)
                for row in rows_spec:
                    y = int(row[0])
                    for a, b in row[1:]:
                        mask[y, int(a):int(b) + 1] = True
                return mask

            cane = rebuild(doc['primitives']['remove_cane'])
            chair = rebuild(doc['primitives']['remove_chair'])
            allowed |= cane
            allowed |= chair
            for name, m in (('remove_cane_r6ar4', cane),
                            ('remove_chair_r6ar4', chair)):
                Image.fromarray(np.where(m, 255, 0).astype(np.uint8)).save(
                    OUT / f'a16_{name}.png')
        Image.fromarray(np.where(allowed, 255, 0).astype(np.uint8)).save(
            OUT / f'{asset}_allowed_edit.png')
        inputs[f'{asset}:allowed_edit_px'] = int(allowed.sum())

    (OUT / 'frozen_inputs.json').write_text(
        json.dumps(inputs, indent=1, sort_keys=True), encoding='utf-8',
        newline='\n')
    print('frozen allowed edits written:',
          {k: v for k, v in inputs.items() if k.endswith('_px')})


if __name__ == '__main__':
    main()
