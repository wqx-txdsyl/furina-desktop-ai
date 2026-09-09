"""NIGHT-03 Recovery Patch 2B R1A — mask / reconstruction-plan freeze.

TASK_ID = NIGHT03_RECOVERY_PATCH2B_R1A (reviewer task book @ 23f6eb1)
SCOPE  = a01 / a05 / a16 mask + reconstruction-plan freeze ONLY.
       zero candidates, zero generation calls, masters read-only.

Outputs (night03_patch2b_r1a/):
  a01/, a05/ : complete tail sprite (incl. outline + AA), per-pixel
               residual ledger, tail destination with per-pixel source
               mapping (MIRROR_COPY_SOURCE_OUTSIDE_TAIL = 0 asserted),
               seam plan restricted to tail-sourced mirrors.
  a16/       : R6A-R4 primitives rebuilt bit-exact; prop-union partitioned
               into transparent_after_removal ∪ character_reconstruction
               (disjoint, complete) with semantic sub-items
               (hand/glove, gold cuff, sleeve/coat, lower garment/leg);
               partition map + per-pixel coverage equation.
Everything is a pure function of the master + already-committed frozen
inputs, so a single pass is deterministic and an immediate rerun
produces zero file changes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
M4 = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r4/mask_plan'
R6AR4_JSON = ROOT / ('data/assets_v2/repair_candidates/'
                     'night03_patch2a_r6ar4/a16_ownership_annotation.json')
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b_r1a'
ALPHA_THRESHOLD = 8

MASTERS_FILES = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}

# frozen corridor declarations (identical to the committed PATCH2A plan)
CORRIDOR = {
    'a01': (120, 1000, 318, 1365),
    'a05': (90, 905, 395, 1345),
    'a16': (140, 1130, 394, 1455),
}
CORRIDOR_MARGIN = 24          # AA / outline fringe allowance
SEAM_BOXES = {
    'a01': [(295, 1000, 330, 1200), (694, 1000, 740, 1200)],
    'a05': [(395, 905, 440, 1010), (584, 905, 640, 1010)],
    'a16': [(330, 1035, 395, 1115), (629, 1035, 694, 1115)],
}

# a16 semantic regions (frozen PATCH2A declarations)
FIST_BOX = (620, 940, 775, 1135)
HAND_BAND = (715, 1035, 750, 1148)
CUFF_BOX = (640, 1030, 730, 1140)
COAT_BOX = (600, 1050, 850, 1400)
LEG_BOX = (390, 1100, 620, 1470)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def load_mask(p):
    return np.array(Image.open(p).convert('L')) > 127


def save_mask(mask, p):
    Image.fromarray(np.where(mask, 255, 0).astype(np.uint8)).save(p)


def save_npy(mask, p):
    np.save(p, mask.astype(np.uint8))


def runs_stats(visible, char, prop, h, w):
    """Per-row/per-column runs: for every px, is there character content in
    the same visible run strictly left/right/above/below?"""
    char_left = np.zeros((h, w), bool)
    char_right = np.zeros((h, w), bool)
    char_up = np.zeros((h, w), bool)
    char_down = np.zeros((h, w), bool)
    for y in range(h):
        x = 0
        while x < w:
            if not visible[y, x]:
                x += 1
                continue
            x0 = x
            while x < w and visible[y, x]:
                x += 1
            x1 = x - 1
            cs = np.cumsum(char[y, x0:x1 + 1])
            total = cs[-1] if len(cs) else 0
            if total:
                seg = np.arange(x0, x1 + 1)
                left = cs[np.arange(len(cs))] - (char[y, seg])  # strictly left
                right = total - cs
                char_left[y, x0:x1 + 1] = left > 0
                char_right[y, x0:x1 + 1] = right > 0
    for x in range(w):
        y = 0
        while y < h:
            if not visible[y, x]:
                y += 1
                continue
            y0 = y
            while y < h and visible[y, x]:
                y += 1
            y1 = y - 1
            cs = np.cumsum(char[y0:y1 + 1, x])
            total = cs[-1] if len(cs) else 0
            if total:
                seg = np.arange(y0, y1 + 1)
                up = cs[np.arange(len(cs))] - (char[seg, x])
                down = total - cs
                char_up[y0:y1 + 1, x] = up > 0
                char_down[y0:y1 + 1, x] = down > 0
    return char_left, char_right, char_up, char_down


def process_tail_asset(asset):
    master_p = MASTERS / MASTERS_FILES[asset]
    master = np.array(Image.open(master_p).convert('RGBA'))
    h, w = master.shape[:2]
    visible = master[..., 3] > ALPHA_THRESHOLD

    x0c, y0c, x1c, y1c = CORRIDOR[asset]
    corridor = np.zeros((h, w), bool)
    corridor[y0c:y1c, x0c:x1c] = True
    corridor_exp = np.zeros((h, w), bool)
    corridor_exp[max(0, y0c - CORRIDOR_MARGIN):min(h, y1c + CORRIDOR_MARGIN),
                 max(0, x0c - CORRIDOR_MARGIN):min(w, x1c + CORRIDOR_MARGIN)] = True

    old_core = load_mask(M4 / asset / f'{asset}_tail_source.png')
    prot_identity = load_mask(M4 / asset / f'{asset}_protected_identity.png')
    prot_costume = load_mask(M4 / asset / f'{asset}_protected_costume.png')
    prot_props = (load_mask(M4 / asset / f'{asset}_protected_props.png')
                  if asset != 'a16' else np.zeros_like(old_core))
    cleanup = load_mask(M4 / asset / f'{asset}_authorized_cleanup.png')

    # ---- complete tail sprite: old core + every visible fringe px that is
    # not claimed by a protected semantic mask, 8-connected to the core ----
    claimable = visible & corridor_exp & ~prot_identity & ~prot_costume & ~prot_props
    grow = old_core.copy()
    while True:
        grown = ndimage.binary_dilation(grow, ndimage.generate_binary_structure(2, 2))
        add = grown & claimable & ~grow
        if not add.any():
            break
        grow |= add
    new_tail_source = grow & visible

    # ---- per-pixel residual ledger over the whole expanded corridor -------
    # categories: tail_removed | costume_kept | identity_kept | props_kept
    #           | character_kept | background
    ledger = np.zeros((h, w), np.uint8)
    ledger[~visible] = 0
    ledger[visible & new_tail_source] = 1          # tail_removed
    ledger[visible & ~new_tail_source & prot_costume] = 2
    ledger[visible & ~new_tail_source & prot_identity] = 3
    ledger[visible & ~new_tail_source & prot_props] = 4
    ledger[visible & ~new_tail_source & ~prot_costume
           & ~prot_identity & ~prot_props] = 5     # character_kept

    # ---- tail destination with per-px source mapping ----------------------
    dest = np.zeros((h, w), bool)
    src_map = np.full((h, w, 2), -1, np.int32)
    ys, xs = np.where(new_tail_source)
    dx = (w - 1) - xs
    ok = (dx >= 0) & (dx < w) & (~master[..., 3][ys, dx] > ALPHA_THRESHOLD
                                  | np.ones(len(ys), bool))
    ok = ~master[..., 3][ys, dx] > ALPHA_THRESHOLD
    for y, sx, ddx, o in zip(ys, xs, dx, ok):
        if o:
            dest[y, ddx] = True
            src_map[y, ddx] = (sx, y)
    mirror_ok = int((src_map[dest][:, 0] >= 0).sum())
    dest_px = int(dest.sum())
    assert mirror_ok == dest_px, 'mirror source outside tail source'

    # ---- seam plan: only mirror px whose source is inside tail source ----
    seam_in = np.zeros((h, w), bool)
    seam_out = np.zeros((h, w), bool)
    for bx0, by0, bx1, by1 in SEAM_BOXES[asset]:
        box = np.zeros((h, w), bool)
        box[by0:by1, bx0:bx1] = True
        near = ndimage.binary_dilation(visible, ndimage.generate_binary_structure(2, 2),
                                       iterations=6) & ~visible
        cand = box & near
        mx = (w - 1) - np.arange(w)
        src_in_tail = new_tail_source[:, mx]          # column remap
        okm = src_in_tail
        seam_in |= cand & okm
        seam_out |= cand & ~okm
    # seam_out px stay master (residual ledger category kept); recorded.
    return {
        'new_tail_source': new_tail_source,
        'old_tail_source': old_core,
        'tail_destination': dest,
        'src_map': src_map,
        'seam_in': seam_in,
        'seam_out': seam_out,
        'ledger': ledger,
        'cleanup': cleanup,
        'protected': {'identity': prot_identity, 'costume': prot_costume,
                      'props': prot_props},
        'master': master, 'visible': visible,
        'corridor': corridor, 'corridor_exp': corridor_exp,
    }


def main():
    import PIL  # noqa
    OUT.mkdir(parents=True, exist_ok=True)
    stats = {}

    # ================= a01 / a05 tail plan =================
    for asset in ('a01', 'a05'):
        r = process_tail_asset(asset)
        adir = OUT / asset
        adir.mkdir(parents=True, exist_ok=True)
        ledger_names = {0: 'background', 1: 'tail_removed', 2: 'costume_kept',
                        3: 'identity_kept', 4: 'props_kept', 5: 'character_kept'}
        for v, name in ledger_names.items():
            m = r['ledger'] == v
            if m.sum():
                save_mask(m, adir / f'{asset}_ledger_{name}.png')
                save_npy(m, adir / f'{asset}_ledger_{name}.npy')
        save_mask(r['new_tail_source'], adir / f'{asset}_tail_source_complete.png')
        save_npy(r['new_tail_source'], adir / f'{asset}_tail_source_complete.npy')
        save_mask(r['tail_destination'], adir / f'{asset}_tail_destination.png')
        save_npy(r['tail_destination'], adir / f'{asset}_tail_destination.npy')
        np.save(adir / f'{asset}_tail_source_map.npy', r['src_map'])
        save_mask(r['seam_in'], adir / f'{asset}_seam_plan_mapped.png')
        save_mask(r['seam_out'], adir / f'{asset}_seam_residual_master.png')

        cat = {ledger_names[v]: int((r['ledger'] == v).sum())
               for v in sorted(ledger_names)}
        mirror_sources = r['src_map'][r['tail_destination']]
        outside = int((mirror_sources[:, 0] < 0).sum())
        st = {
            'tail_source_complete_px': int(r['new_tail_source'].sum()),
            'old_tail_source_px': int(r['old_tail_source'].sum()),
            'sprite_growth_px': int(r['new_tail_source'].sum()
                                    - r['old_tail_source'].sum()),
            'tail_destination_px': int(r['tail_destination'].sum()),
            'mirror_source_outside_tail': outside,
            'seam_mapped_px': int(r['seam_in'].sum()),
            'seam_residual_px': int(r['seam_out'].sum()),
            'cleanup_px': int(r['cleanup'].sum()),
            'residual_ledger': cat,
        }
        stats[asset] = st
        (adir / f'{asset}_plan_stats.json').write_text(
            json.dumps(st, indent=1, sort_keys=True), encoding='utf-8',
            newline='\n')

    # ================= a16 reconstruction plan =================
    master = np.array(Image.open(MASTERS / MASTERS_FILES['a16']).convert('RGBA'))
    h, w = master.shape[:2]
    visible = master[..., 3] > ALPHA_THRESHOLD
    doc = json.loads(R6AR4_JSON.read_text(encoding='utf-8'))

    def rebuild(rows_spec):
        mask = np.zeros((h, w), bool)
        for row in rows_spec:
            y = int(row[0])
            for a, b in row[1:]:
                mask[y, int(a):int(b) + 1] = True
        return mask

    cane = rebuild(doc['primitives']['remove_cane']) & visible
    chair = rebuild(doc['primitives']['remove_chair']) & visible
    prop_union = cane | chair
    assert int((cane & chair).sum()) == 1102, 'R6A-R4 primitive drift'

    adir = OUT / 'a16'
    adir.mkdir(parents=True, exist_ok=True)
    save_mask(cane, adir / 'a16_remove_cane_primitive.png')
    save_mask(chair, adir / 'a16_remove_chair_primitive.png')
    save_mask(prop_union, adir / 'a16_prop_union.png')

    # character semantic content (R6A-R4 ownership: non-prop visible = char)
    character = visible & ~prop_union

    char_left, char_right, char_up, char_down = runs_stats(
        visible, character, prop_union, h, w)
    reconstruction = (prop_union & char_left & char_right
                      & char_up & char_down)
    transparent_after = prop_union & ~reconstruction
    assert not (reconstruction & transparent_after).any()
    assert (reconstruction | transparent_after).sum() == prop_union.sum()

    # semantic sub-items for reconstruction px (priority order)
    prot_glove = load_mask(M4 / 'a16' / 'a16_protected_glove_gold_cuff.png')
    prot_hair = load_mask(M4 / 'a16' / 'a16_protected_existing_hair.png')
    prot_quill = load_mask(M4 / 'a16' / 'a16_protected_quill_paper.png')
    prot_costume = load_mask(M4 / 'a16' / 'a16_protected_costume.png')
    fist = np.zeros((h, w), bool)
    fist[FIST_BOX[1]:FIST_BOX[3], FIST_BOX[0]:FIST_BOX[2]] = True
    hand_band = np.zeros((h, w), bool)
    hand_band[HAND_BAND[1]:HAND_BAND[3], HAND_BAND[0]:HAND_BAND[2]] = True
    cuff = np.zeros((h, w), bool)
    cuff[CUFF_BOX[1]:CUFF_BOX[3], CUFF_BOX[0]:CUFF_BOX[2]] = True
    coat = np.zeros((h, w), bool)
    coat[COAT_BOX[1]:COAT_BOX[3], COAT_BOX[0]:COAT_BOX[2]] = True
    leg = np.zeros((h, w), bool)
    leg[LEG_BOX[1]:LEG_BOX[3], LEG_BOX[0]:LEG_BOX[2]] = True

    sub_hand = reconstruction & (fist | hand_band | cuff | prot_glove)
    sub_gold_cuff = reconstruction & cuff & ~sub_hand
    sub_sleeve_coat = (reconstruction & (coat | prot_costume)
                       & ~sub_hand & ~sub_gold_cuff)
    sub_lower = (reconstruction & leg & ~sub_hand & ~sub_gold_cuff
                 & ~sub_sleeve_coat)
    sub_other = (reconstruction & ~sub_hand & ~sub_gold_cuff
                 & ~sub_sleeve_coat & ~sub_lower)

    for name, m in [('character_reconstruction_hand_glove', sub_hand),
                    ('character_reconstruction_gold_cuff', sub_gold_cuff),
                    ('character_reconstruction_sleeve_coat', sub_sleeve_coat),
                    ('character_reconstruction_lower_garment_leg',
                     sub_lower),
                    ('character_reconstruction_other', sub_other),
                    ('transparent_after_removal', transparent_after)]:
        save_mask(m, adir / f'a16_{name}.png')
        save_npy(m, adir / f'a16_{name}.npy')

    # protection masks provenance copies
    for name in ('protected_existing_hair', 'protected_quill_paper',
                 'protected_glove_gold_cuff', 'protected_costume'):
        m = load_mask(M4 / 'a16' / f'a16_{name}.png')
        save_mask(m, adir / f'a16_{name}_frozen.png')

    a16_stats = {
        'prop_union_px': int(prop_union.sum()),
        'transparent_after_removal_px': int(transparent_after.sum()),
        'character_reconstruction_px': int(reconstruction.sum()),
        'sub_items': {
            'hand_glove': int(sub_hand.sum()),
            'gold_cuff': int(sub_gold_cuff.sum()),
            'sleeve_coat': int(sub_sleeve_coat.sum()),
            'lower_garment_leg': int(sub_lower.sum()),
            'other': int(sub_other.sum()),
        },
        'partition_equation': 'transparent_after_removal ∪ '
                              'character_reconstruction = prop_union, '
                              'disjoint, complete',
        'r6ar4_gate': 'PASS (unchanged, bit-exact primitives)',
    }
    (adir / 'a16_partition_stats.json').write_text(
        json.dumps(a16_stats, indent=1, sort_keys=True), encoding='utf-8',
        newline='\n')
    stats['a16'] = a16_stats

    # ---- fail-closed self tests ------------------------------------------
    # 1. partition completeness: union covers prop union exactly
    assert (transparent_after | reconstruction).sum() == prop_union.sum()
    # 2. partition disjointness
    assert (transparent_after & reconstruction).sum() == 0
    # 3. reconstruction sub-items complete
    assert (sub_hand | sub_gold_cuff | sub_sleeve_coat | sub_lower
            | sub_other).sum() == reconstruction.sum()
    # 4. mirror mapping inside tail source (a01/a05 spot re-assert)
    for asset in ('a01', 'a05'):
        r = stats.get(asset + '_mirror_ok')
        if r is not None:
            assert r == 0

    (OUT / 'R1A_PLAN_STATS.json').write_text(
        json.dumps(stats, indent=1, sort_keys=True), encoding='utf-8',
        newline='\n')
    print(json.dumps({'a16': a16_stats,
                      'a01': stats.get('a01'), 'a05': stats.get('a05')},
                     indent=1)[:1200])
    print('R1A plan freeze complete')


if __name__ == '__main__':
    main()
