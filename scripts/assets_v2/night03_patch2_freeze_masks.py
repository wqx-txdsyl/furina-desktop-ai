"""NIGHT-03 Recovery Patch 2A — freeze pre-build semantic masks (Builder).

Task book: NIGHT03_RECOVERY_PATCH2A (Reviewer: ChatGPT Codex).
BASE_SHA: a1586f70416add58d44891330fd8c5aad4d832cb.  Scope: a01 / a05 / a16 only.

Legal inputs (ONLY): masters, BASE, frozen specs and the pre-declared semantic
coordinates / manually confirmed component seeds written below as DECLARED
constants.  No candidate is generated; no Patch 1 artifact is read; no image
generation is invoked.  All outputs stay under
data/assets_v2/repair_candidates/night03_patch2/mask_plan/.

Every mask is a single-channel 8-bit PNG whose values are only 0 and 255.
allowed_edit is the frozen union of the declared edit terms, and
allowed_edit ∩ protected_* must be exactly empty; the script fails otherwise.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
BASE_P = ROOT / 'data/assets_v2/_base/furina-base.png'
SPEC_DIR = ROOT / 'data/assets_v2/_spec'
REVIEW_REPORT = ROOT / ('data/assets_v2/repair_candidates/night03_patch1/'
                        'NIGHT03_PATCH1_REVIEW_REPORT.md')
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2/mask_plan'
CANVAS = (1024, 1536)
ST8 = np.ones((3, 3), bool)   # 8-connectivity
ST4 = ndimage.generate_binary_structure(2, 1)

ASSETS = {
    'a01': 'furina_v2_a01_stand_neutral_front.png',
    'a05': 'furina_v2_a05_stand_confident_proud.png',
    'a16': 'furina_v2_a16_work_focused.png',
}

MASK_ORDER = ['tail_source', 'old_tail_removal', 'tail_destination',
              'seam_reconstruction', 'authorized_cleanup',
              'protected_identity', 'protected_costume', 'protected_props',
              'allowed_edit']
A16_EXTRA_ORDER = ['chair_removal', 'cane_removal', 'hair_reconstruction',
                   'hand_reconstruction', 'speck_cleanup',
                   'protected_existing_hair', 'protected_quill_paper',
                   'protected_glove_gold_cuff']

# ---------------------------------------------------------------------------
# DECLARED semantic constants — manually confirmed from masters + _inspect
# crops + probe measurements + the first-round NIGHT03_REVIEW_REPORT.md
# coordinate record.  Boxes are (x0, y0, x1, y1) numpy-slicing style; seeds
# are (x, y) points inside the manually identified semantic component.
# ---------------------------------------------------------------------------

DECLARED = {
    'a01': {
        # Old showpiece tail, viewer-left: mass y~1078-1310 (tint comp
        # 16040px x187-306/y1075-1300 + outline shell + curl tip).  The pale
        # striped panel at x>=318 is the coattail LINING (incl. the lobe comp
        # x323-402/y1186-1308 that round 1 wrongly mirrored) — clip at x<=318.
        'tail_corridor': (120, 1000, 318, 1365),
        'tail_seeds': [(250, 1120), (270, 1260), (200, 1180),
                       (270, 1330), (288, 1200), (275, 1058)],
        'shell_radius': 5,
        # cane: gold ring handle + white orb + light-blue shaft + spearhead,
        # held IN FRONT of the tail (x~270-352).  Probe-verified: saturated
        # shaft core (b-r>=60) is leak-free against the tail component.
        'props_boxes': [(270, 998, 352, 1470)],
        'props_parts': [
            {'box': (270, 998, 352, 1470), 'colors': ['gold', 'shaft'],
             'seeds': [(312, 1200)]},
            {'box': (280, 1010, 335, 1095), 'colors': ['white', 'gold'],
             'seeds': [(300, 1060)]},
        ],
        # costume: bow+cravat, coattail striped lining, skirt/legs/socks,
        # gloved hand+cuff, coat torso / coattail body.
        'costume_boxes': [(330, 820, 540, 1080),
                          (318, 955, 470, 1310),
                          (330, 1080, 640, 1470),
                          (250, 915, 352, 1102),
                          (340, 830, 700, 1180)],
        'protected_identity_box': (60, 60, 700, 1000),
        'extra_guard_boxes': [],
        # 2px semi-transparent dark speck off the hair silhouette
        # (first-round review: harmless cleanup, pixels (363,714-715)).
        'cleanup_boxes': [(360, 710, 368, 719)],
        'cleanup_seeds': [(363, 714)],
        'seam_boxes': [(295, 1000, 330, 1200),
                       (694, 1000, 740, 1200)],
    },
    'a05': {
        # Old tail, viewer-left: single tint component 34349px,
        # bbox x156-389/y921-1288 (+ outline shell).  Chest area
        # y795-935 x380-580 is vest/sash/bow highlight — not tail.
        # Tail edge truly reaches x389; bow guard starts x390.
        'tail_corridor': (90, 905, 395, 1345),
        'tail_seeds': [(250, 1150)],
        'shell_radius': 5,
        # ornate cane, viewer-right: pearl-white orb head (x~810-870,
        # y~755-830), gold guard (x~770-800/y~930-1000), near-vertical
        # light-blue shaft (x~690-795, y~1000-1375).  Head white is
        # box-restricted so the white glove cuff can never enter.
        'props_boxes': [(680, 735, 810, 1385)],
        'props_parts': [
            {'box': (680, 920, 810, 1385), 'colors': ['gold', 'shaft'],
             'seeds': [(790, 980), (760, 1100)]},
            {'box': (795, 740, 880, 860), 'colors': ['white', 'gold'],
             'seeds': [(838, 790)]},
        ],
        'costume_boxes': [(390, 855, 465, 1100),
                          (380, 795, 580, 935),
                          (400, 1000, 660, 1470),
                          (560, 900, 800, 1420),
                          (655, 1040, 790, 1380)],
        'protected_identity_box': (60, 60, 700, 905),
        'extra_guard_boxes': [],
        # detached wisp island (ratification debris, 465px measured round 1)
        'cleanup_boxes': [(610, 1270, 675, 1325)],
        'cleanup_seeds': [(652, 1295)],
        'seam_boxes': [(395, 905, 440, 1010),
                       (584, 905, 640, 1010)],
    },
    'a16': {
        # Old tail, viewer-left: C-curl comps 20122px x189-376/y1149-1418 and
        # 2897px x287-380/y1171-1255.  The diagonal tint band y1035-1105 /
        # x337-398 is the QUILL feather, not tail (probe: background at
        # x300-345) — corridor starts y>=1130.
        'tail_corridor': (140, 1130, 394, 1455),
        'tail_seeds': [(280, 1250), (220, 1300), (330, 1200)],
        'shell_radius': 5,
        'props_boxes': [],
        'props_seeds': [],
        'props_parts': [],
        # held cane: pearl pommel + gold grip + blue blade + silver tip,
        # declared as separate corridor parts so the wide white/gold tests
        # can never reach the glove cuff frills or the right-side hair
        # (hair tips end y<=905; pommel box therefore starts y>=910).
        'cane_parts': [
            {'box': (620, 1000, 780, 1160), 'colors': ['gold'],
             'seeds': [(725, 1065)]},
            {'box': (735, 910, 812, 1015), 'colors': ['white', 'gold'],
             'seeds': [(770, 955)]},
            {'box': (560, 1110, 720, 1160), 'colors': ['deep_blue'],
             'seeds': [(675, 1140)]},
            {'box': (595, 1160, 720, 1445), 'colors': ['deep_blue'],
             'seeds': [(660, 1260), (615, 1400)]},
        ],
        # dedicated removal masks (task book §4 a16 list):
        'chair_corridor': (410, 1080, 730, 1470),
        'chair_shoe_guard': (390, 1390, 560, 1470),
        'fist_box': (620, 940, 775, 1135),
        'quill_box': (320, 940, 400, 1100),
        'paper_box': (330, 1085, 510, 1180),
        # 3 floating specks (first-round review §4 verified-good removals)
        'cleanup_boxes': [(271, 951, 288, 961), (271, 1014, 286, 1027),
                          (305, 1061, 314, 1076)],
        'cleanup_seeds': [(283, 956), (278, 1020), (308, 1067)],
        'costume_boxes': [(380, 880, 680, 1240),
                          (390, 1080, 620, 1350),
                          (600, 1050, 850, 1400),
                          (695, 1140, 830, 1270),
                          (390, 1100, 620, 1470)],
        'protected_identity_box': (150, 540, 790, 920),
        'extra_guard_boxes': [(320, 940, 400, 1100),   # quill
                              (330, 1085, 510, 1180)],  # paper
        'seam_boxes': [(330, 1035, 395, 1115),
                       (629, 1035, 694, 1115)],
    },
}

# ---------------------------------------------------------------------------
# deterministic pixel tests (constants recorded; master is the only source)
# ---------------------------------------------------------------------------

def tint_tail(rgb):
    """pale / blue-shadow tail-hair colour test (constants as NIGHT-03)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = (r + g + b) / 3.0
    pale = (b - r >= 18) & (bright >= 130) & (g >= r - 10)
    shadow = (g - r >= 25) & (b - r >= 35) & (bright >= 110) & (b > g)
    return pale | shadow


def colour_test(rgb, names):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = (r + g + b) / 3.0
    out = np.zeros(bright.shape, bool)
    for n in names:
        if n == 'gold':
            out |= (r >= 120) & (r > g) & (g > b) & (r - b >= 30)
        elif n == 'white':      # blue-tinged pearl white (orb / pommel / head)
            out |= (bright >= 185) & (np.abs(b - r) <= 25)
        elif n == 'shaft':      # saturated light-blue shaft core
            out |= (b - r >= 60) & (b >= 140) & (bright < 210)
        elif n == 'deep_blue':  # a16 blade
            out |= (b - r >= 45) & (b >= 110)
        elif n == 'silver':     # a16 blade tip
            out |= (bright >= 140) & (b - r >= 25) & (b - r <= 80) & (b >= 170)
        else:
            raise SystemExit(f'unknown colour test {n}')
    return out


def box_mask(shape, boxes):
    m = np.zeros(shape, bool)
    for x0, y0, x1, y1 in boxes:
        m[y0:y1, x0:x1] = True
    return m


def component_from_seeds(cand, seeds, max_search=25):
    """Seed -> connected component.  If the exact seed pixel is empty, the
    nearest candidate pixel within max_search (deterministic ring scan,
    ascending radius then y then x) is used instead."""
    if not seeds:
        return np.zeros_like(cand)
    lab, _ = ndimage.label(cand, structure=ST8)
    out = np.zeros_like(cand)
    ys, xs = np.where(cand)
    order = np.argsort(ys * 4096 + xs)
    ys, xs = ys[order], xs[order]
    for sx, sy in seeds:
        ident = 0
        if cand[sy, sx]:
            ident = lab[sy, sx]
        else:
            for rr in range(1, max_search + 1):
                y0, y1 = max(0, sy - rr), min(cand.shape[0], sy + rr + 1)
                x0, x1 = max(0, sx - rr), min(cand.shape[1], sx + rr + 1)
                sel = ((ys >= y0) & (ys < y1) & (xs >= x0) & (xs < x1))
                if sel.any():
                    ident = lab[ys[sel][0], xs[sel][0]]
                    break
        if ident == 0:
            raise SystemExit(f'seed ({sx},{sy}): no candidate pixel within '
                             f'{max_search}px')
        out |= lab == ident
    return out


def build_props(rgb, alpha, d):
    """props component: per-part declared boxes + colour tests + seeds."""
    if not d.get('props_parts'):
        return np.zeros(alpha.shape, bool)
    cand = np.zeros(alpha.shape, bool)
    seeds = []
    for part in d['props_parts']:
        zone = box_mask(alpha.shape, [part['box']])
        zone &= ~box_mask(alpha.shape, part.get('exclude', []))
        cand |= colour_test(rgb, part['colors']) & alpha & zone
        seeds.extend(part['seeds'])
    return ndimage.binary_fill_holes(
        component_from_seeds(cand, seeds)) & alpha


def freeze(asset, im):
    h, w = im.shape[:2]
    assert (w, h) == CANVAS
    rgb = im[..., :3].astype(int)
    alpha = im[..., 3] > 8
    d = DECLARED[asset]

    props = build_props(rgb, alpha, d)
    costume = box_mask((h, w), d['costume_boxes']) & alpha
    identity = box_mask((h, w), [d['protected_identity_box']]) & alpha
    extra = box_mask((h, w), d['extra_guard_boxes']) & alpha
    cleanup_boxes = box_mask((h, w), d['cleanup_boxes'])

    # --- authorized cleanup first (protected zones must not swallow debris)
    cleanup = np.zeros((h, w), bool)
    for bx0, by0, bx1, by1 in d['cleanup_boxes']:
        zone = np.zeros((h, w), bool)
        zone[by0:by1, bx0:bx1] = alpha[by0:by1, bx0:bx1]
        cleanup |= zone
    cleanup = component_from_seeds(cleanup, d['cleanup_seeds'])

    costume = costume & ~cleanup
    identity = identity & ~cleanup

    # --- tail semantic component: seed-connected tint core inside corridor
    corridor = box_mask((h, w), [d['tail_corridor']])
    tint = tint_tail(rgb) & alpha & corridor & ~props & ~extra
    tail_core = component_from_seeds(tint, d['tail_seeds'])
    tail_solid = ndimage.binary_fill_holes(tail_core) & corridor
    shell_zone = ndimage.binary_dilation(tail_core, ST8,
                                         iterations=d['shell_radius'])
    hard_guard = identity | costume | props | extra   # full-strength guards
    shell = (shell_zone & alpha & corridor & ~tail_solid & ~hard_guard)
    tail_source = (tail_solid | shell) & alpha & ~hard_guard

    # --- old tail deletion = source minus every protected pixel
    old_removal = tail_source

    # --- destination: exact mirror of the frozen source about x=512,
    #     restricted to currently transparent pixels (body stays untouched;
    #     shape == mirrored component, never a rectangular patch)
    dest = np.fliplr(tail_source) & ~alpha

    # --- seam reconstruction: declared bands, transparent pixels only,
    #     within 6px of existing alpha (edge hugging, no rectangles on body)
    seam = np.zeros((h, w), bool)
    near = ndimage.binary_dilation(alpha, ST8, iterations=6)
    for x0, y0, x1, y1 in d['seam_boxes']:
        seam[y0:y1, x0:x1] |= ~alpha[y0:y1, x0:x1] & near[y0:y1, x0:x1]

    out = {
        'tail_source': tail_source,
        'old_tail_removal': old_removal,
        'tail_destination': dest,
        'seam_reconstruction': seam,
        'authorized_cleanup': cleanup,
        'protected_identity': identity,
        'protected_costume': costume,
        'protected_props': props,
        'allowed_edit': None,
    }
    allowed_terms = ['old_tail_removal', 'tail_destination',
                     'seam_reconstruction', 'authorized_cleanup']

    if asset == 'a16':
        del out['authorized_cleanup']
        out['speck_cleanup'] = cleanup
        del out['protected_props']

        # chair: wood-coloured connected component inside declared corridor
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        wood = ((r > g) & (g > b) & (r - b >= 14) & (r - g <= 50)
                & (r >= 40) & (r < 210)) & alpha
        wood &= box_mask((h, w), [d['chair_corridor']])
        # every wood component in the corridor belongs to the baked chair
        # except fragments touching her shoe/sock zone (warm shoe shadows)
        shoe = box_mask((h, w), [d['chair_shoe_guard']])
        labs, nlab = ndimage.label(wood, structure=ST8)
        keep = np.zeros_like(wood)
        for i in range(1, nlab + 1):
            comp = labs == i
            if (comp & shoe & alpha).any():
                continue
            keep |= comp
        chair = ndimage.binary_fill_holes(keep) & alpha

        # held cane: per-part corridors (pommel/grip/blade/tip) so wide white
        # or gold tests can never reach glove cuff frills or sock frills
        cc = np.zeros(alpha.shape, bool)
        cane_seeds = []
        for part in d['cane_parts']:
            zone = box_mask(alpha.shape, [part['box']])
            zone &= ~box_mask(alpha.shape, part.get('exclude', []))
            cc |= colour_test(rgb, part['colors']) & alpha & zone
            cane_seeds.extend(part['seeds'])
        cane = ndimage.binary_fill_holes(
            component_from_seeds(cc, cane_seeds)) & alpha

        hair_recon = np.zeros((h, w), bool)  # intentionally empty (report §4)
        hand_recon = cane & box_mask((h, w), [d['fist_box']])

        out['chair_removal'] = chair
        out['cane_removal'] = cane
        out['hair_reconstruction'] = hair_recon
        out['hand_reconstruction'] = hand_recon
        out['protected_existing_hair'] = identity & ~cane & ~chair
        out['protected_quill_paper'] = extra & ~cane & ~chair
        glove = ((box_mask((h, w), [d['fist_box']])
                  | box_mask((h, w), [(600, 960, 700, 1070)])) & alpha)
        out['protected_glove_gold_cuff'] = glove & ~cane & ~chair
        out['protected_costume'] = costume & ~cane & ~chair
        allowed_terms = ['old_tail_removal', 'tail_destination',
                         'seam_reconstruction', 'speck_cleanup',
                         'chair_removal', 'cane_removal', 'hair_reconstruction',
                         'hand_reconstruction']

    allowed = np.zeros((h, w), bool)
    for term in allowed_terms:
        allowed |= out[term]
    out['allowed_edit'] = allowed

    names = [m for m in MASK_ORDER if m in out]
    names += [m for m in A16_EXTRA_ORDER if m in out and m not in names]
    names += [m for m in out if m not in names]
    return out, names, allowed_terms


OVERLAY_COLORS = {
    'tail_source': (0, 200, 255), 'old_tail_removal': (255, 40, 40),
    'tail_destination': (0, 230, 60), 'seam_reconstruction': (255, 220, 0),
    'authorized_cleanup': (0, 255, 220), 'speck_cleanup': (0, 255, 220),
    'chair_removal': (150, 90, 40), 'cane_removal': (255, 140, 0),
    'hair_reconstruction': (170, 120, 255), 'hand_reconstruction': (255, 105, 180),
    'protected_identity': (30, 80, 255), 'protected_costume': (230, 0, 230),
    'protected_props': (255, 160, 60), 'protected_existing_hair': (30, 80, 255),
    'protected_quill_paper': (120, 200, 120),
    'protected_glove_gold_cuff': (255, 160, 60),
    'allowed_edit': (255, 255, 255),
}


def paint(im_rgba, masks, order, bg_rgb):
    h, w = im_rgba.shape[:2]
    a = im_rgba[..., 3:4].astype(np.float32) / 255.0
    if bg_rgb is None:
        base = im_rgba[..., :3].astype(np.float32)
    else:
        base = np.full((h, w, 3), bg_rgb, np.float32)
    out = base * a + np.full((h, w, 3), 255.0 if bg_rgb is None else bg_rgb,
                             np.float32) * (1 - a) if bg_rgb is None \
        else base * a + np.full((h, w, 3), bg_rgb, np.float32) * (1 - a)
    out = out.astype(np.float32)
    for name in order:
        if name == 'allowed_edit':
            continue
        m = masks[name]
        col = np.array(OVERLAY_COLORS[name], np.float32)
        out[m] = out[m] * 0.45 + col * 0.55
    am = masks['allowed_edit']
    edge = am & ~ndimage.binary_erosion(am, ST4)
    out[edge] = (255, 255, 255)
    return out.clip(0, 255).astype(np.uint8)


def checker(h, w, c=24):
    yy, xx = np.mgrid[0:h, 0:w]
    t = ((xx // c) + (yy // c)) % 2 == 0
    return np.where(t[..., None], 200, 150).astype(np.uint8)


def sha256_path(p):
    hsh = hashlib.sha256()
    with open(p, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            hsh.update(chunk)
    return hsh.hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plan = {'task': 'NIGHT03_RECOVERY_PATCH2A_MASK_FREEZE',
            'base_sha': 'a1586f70416add58d44891330fd8c5aad4d832cb',
            'canvas': list(CANVAS), 'inputs': {}, 'assets': {}}
    for p in sorted(SPEC_DIR.glob('*.md')):
        plan['inputs'][f'_spec/{p.name}'] = sha256_path(p)
    plan['inputs']['BASE'] = sha256_path(BASE_P)
    plan['inputs']['PATCH1_REVIEW_REPORT'] = sha256_path(REVIEW_REPORT)

    fail = []
    for asset, fn in ASSETS.items():
        mp = MASTERS / fn
        im = np.array(Image.open(mp).convert('RGBA'))
        masks, order, terms = freeze(asset, im)
        adir = OUT / asset
        adir.mkdir(exist_ok=True)
        ent = {'master_file': f'data/assets_v2/masters/{fn}',
               'master_sha256': sha256_path(mp), 'masks': {},
               'allowed_terms': terms, 'intersections': {}}
        for name in order:
            m = masks[name]
            arr = m.astype(np.uint8) * 255
            assert arr.max() in (0, 255)
            p = adir / f'{asset}_{name}.png'
            Image.fromarray(arr, 'L').save(p)
            ys, xs = np.where(m)
            ent['masks'][name] = {
                'px': int(m.sum()),
                'bbox': [int(xs.min()), int(ys.min()), int(xs.max()),
                         int(ys.max())] if m.any() else None,
                'sha256': sha256_path(p)}
        prot = [n for n in order if n.startswith('protected_')]
        for pn in prot:
            val = int((masks['allowed_edit'] & masks[pn]).sum())
            ent['intersections'][f'allowed_edit^{pn}'] = val
            if val:
                fail.append(f'{asset}: allowed_edit overlaps {pn} ({val}px)')
        for i, a in enumerate(terms):
            for b in terms[i + 1:]:
                ent['intersections'][f'{a}^{b}'] = int(
                    (masks[a] & masks[b]).sum())
        u = np.zeros_like(masks['allowed_edit'])
        for t in terms:
            u |= masks[t]
        ent['allowed_union_eq'] = bool((u == masks['allowed_edit']).all())
        if not ent['allowed_union_eq']:
            fail.append(f'{asset}: allowed union equation violated')
        ent['destination_on_transparent_only'] = bool(
            not (masks['tail_destination'] & (im[..., 3] > 8)).any())
        # audit: tail-coloured pixels inside the corridor left unclaimed
        # (costume/prop-adjacent boundary fringe, by-design protected)
        dcl = DECLARED[asset]
        hh, ww = im.shape[:2]
        tint_all = tint_tail(im[..., :3].astype(int)) & (im[..., 3] > 8)             & box_mask((hh, ww), [dcl['tail_corridor']])
        ent['boundary_residual_px'] = int(
            (tint_all & ~masks['tail_source'] & (im[..., 3] > 8)).sum())
        if not ent['destination_on_transparent_only']:
            fail.append(f'{asset}: destination claims existing alpha')
        # evidence: colour-coded overlays on master / checker / dark / light
        h, w = im.shape[:2]
        Image.fromarray(paint(im, masks, order, None)).save(
            adir / f'{asset}_overlay_master.png')
        ch = checker(h, w).astype(np.float32)
        a = im[..., 3:4].astype(np.float32) / 255.0
        for bgn, bg in (('checker', ch),
                        ('dark', np.full((h, w, 3), 32, np.float32)),
                        ('light', np.full((h, w, 3), 240, np.float32))):
            flat = (im[..., :3].astype(np.float32) * a
                    + bg * (1 - a)).clip(0, 255).astype(np.uint8)
            flat_im = np.dstack([flat, np.full((h, w), 255, np.uint8)])
            Image.fromarray(paint(flat_im, masks, order, None)).save(
                adir / f'{asset}_overlay_{bgn}.png')
        plan['assets'][asset] = ent
        print(f'[{asset}] ' + ', '.join(f"{k}={v['px']}"
                                        for k, v in ent['masks'].items()))

    CROPS = {
        'a01': [('tail_lining_cane', 120, 960, 480, 1360, 2),
                ('destination_zone', 620, 960, 940, 1360, 2),
                ('lobe_lining', 300, 1140, 480, 1340, 4)],
        'a05': [('tail_bow_root', 90, 815, 510, 1160, 2),
                ('destination_cane', 500, 900, 900, 1400, 2),
                ('wisp', 600, 1250, 690, 1340, 4)],
        'a16': [('tail', 140, 1040, 420, 1460, 2),
                ('pommel_hand', 560, 850, 880, 1270, 2),
                ('chair', 400, 1080, 760, 1480, 2),
                ('destination_zone', 600, 1000, 920, 1460, 2)],
    }
    for asset, fn in ASSETS.items():
        im = Image.open(MASTERS / fn).convert('RGBA')
        for cname, x0, y0, x1, y1, z in CROPS[asset]:
            big = im.crop((x0, y0, x1, y1)).resize(
                ((x1 - x0) * z, (y1 - y0) * z), Image.NEAREST)
            arr = np.array(big).astype(np.float32)
            a = arr[..., 3:4] / 255.0
            bgc = checker(*big.size[::-1]).astype(np.float32)
            comp = (arr[..., :3] * a + bgc * (1 - a)).clip(0, 255).astype(
                np.uint8)
            Image.fromarray(comp).save(
                OUT / asset / f'{asset}_crop_{cname}_{z}x.png')

    # gate: no candidate PNG anywhere under night03_patch2
    for p in OUT.parent.rglob('*.png'):
        rel = p.relative_to(OUT.parent).as_posix()
        if not (rel.startswith('_inspect/') or rel.startswith('mask_plan/')):
            fail.append(f'unexpected png outside _inspect/mask_plan: {rel}')

    plan_copy = {k: v for k, v in plan.items()}
    canonical = json.dumps(plan_copy, sort_keys=True, ensure_ascii=True,
                           separators=(',', ':'))
    plan['MASK_PLAN_SHA256'] = hashlib.sha256(
        canonical.encode('utf-8')).hexdigest()
    (OUT / 'night03_patch2_mask_plan.json').write_text(
        json.dumps(plan, indent=1, sort_keys=True), encoding='utf-8')

    if fail:
        print('FREEZE FAILED:')
        for f in fail:
            print(' -', f)
        raise SystemExit(1)
    print('MASK_PLAN_SHA256 =', plan['MASK_PLAN_SHA256'])
    print('FREEZE OK — masks frozen, no candidates generated')


if __name__ == '__main__':
    main()
