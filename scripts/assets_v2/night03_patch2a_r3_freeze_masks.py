"""NIGHT-03 Recovery Patch 2A R3 — complete frozen semantic masks (Builder).

Task book: NIGHT03_RECOVERY_PATCH2A_R2 (Reviewer: ChatGPT Codex).
BASE_SHA: 98987c90e260fb4df500c3303c70d2b5ae82dde8 (Patch 2A R1).

R2 scope:
- a01 / a05 masks are byte-identical to the accepted R1 freeze.
- a16 protected masks are built INCLUSION-ONLY by build_protected_masks()
  (positive seeded components; never ~cane / ~chair / ~allowed / ~exclusion),
  frozen BEFORE any edit mask is constructed.
- a16 cane_removal / chair_removal are complete semantic masks: coloured
  components + enclosed holes + boundary outline bands inside declared
  corridors, trimmed so they never touch the frozen protected masks.
- Cutout evidence (mask-alpha zeroed on a master copy, evidence only) is
  emitted for cane / chair / combined.
- Zero candidates, zero generation calls.
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
OUT = ROOT / ('data/assets_v2/repair_candidates/'
              'night03_patch2a_r3/mask_plan')
R1_MASKS = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r1/mask_plan'
CANVAS = (1024, 1536)
ST8 = np.ones((3, 3), bool)
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
A16_EXTRA = ['chair_removal', 'cane_removal', 'hair_reconstruction',
             'hand_reconstruction', 'speck_cleanup',
             'protected_existing_hair', 'protected_quill_paper',
             'protected_glove_gold_cuff']

# ---------------------------------------------------------------------------
# a01 / a05 constants — identical to the accepted R1 freeze (byte-identical)
# ---------------------------------------------------------------------------
DECLARED_R1 = {
    'a01': {
        'tail_corridor': (120, 1000, 318, 1372),
        'tail_seeds': [(250, 1120), (270, 1260), (200, 1180),
                       (280, 1340), (288, 1200), (275, 1058),
                       (258, 1085), (270, 1095), (290, 1310)],
        'lower_curl_min_ymax': 1355,
        'shell_radius': 5,
        'props_boxes': [(270, 998, 352, 1470)],
        'props_parts': [
            {'box': (270, 998, 352, 1470), 'colors': ['gold', 'shaft'],
             'seeds': [(312, 1200)]},
            {'box': (280, 1010, 335, 1095), 'colors': ['white', 'gold'],
             'seeds': [(300, 1060)]},
        ],
        'costume_boxes': [(330, 820, 540, 1080),
                          (318, 955, 470, 1310),
                          (330, 1080, 640, 1470),
                          (250, 915, 352, 1045),
                          (340, 830, 700, 1180)],
        'protected_identity_box': (60, 60, 700, 1000),
        'extra_guard_boxes': [],
        'cleanup_boxes': [(360, 710, 368, 719)],
        'cleanup_seeds': [(363, 714)],
        'seam_boxes': [(295, 1000, 330, 1200),
                       (694, 1000, 740, 1200)],
    },
    'a05': {
        'tail_corridor': (90, 905, 395, 1345),
        'tail_seeds': [(250, 1150)],
        'shell_radius': 5,
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
        'cleanup_boxes': [(610, 1270, 675, 1325)],
        'cleanup_seeds': [(652, 1295)],
        'seam_boxes': [(395, 905, 440, 1010),
                       (584, 905, 640, 1010)],
    },
}

# ---------------------------------------------------------------------------
# a16 declarations (R2)
# ---------------------------------------------------------------------------
D16 = {
    # tail: identical to R1 (approved)
    'tail_corridor': (140, 1130, 394, 1455),
    'tail_seeds': [(280, 1250), (220, 1300), (330, 1200)],
    'shell_radius': 5,
    'cleanup_boxes': [(271, 951, 288, 961), (271, 1014, 286, 1027),
                      (305, 1061, 314, 1076)],
    'cleanup_seeds': [(283, 956), (278, 1020), (308, 1067)],
    'seam_boxes': [(330, 1035, 395, 1115),
                   (629, 1035, 694, 1115)],
    'quill_box': (320, 940, 400, 1100),
    'paper_box': (330, 1085, 510, 1180),
    # ---- protected declarations (inclusion-only, seeded positive comps) ----
    'prot': {
        'hair_zone': (150, 540, 790, 920),
        'hair_seeds': [(400, 700), (300, 780), (560, 640), (680, 860),
                       (350, 880), (700, 890)],
        'hat_zone': (200, 555, 700, 745),
        'hat_seeds': [(420, 640), (560, 620)],
        'face_zone': (330, 720, 480, 890),
        'face_seeds': [(400, 800)],
        'quill_seed': (355, 1000),
        'paper_seed': (420, 1130),
        'glove_zone': (600, 1000, 762, 1160),
        'glove_seeds': [(630, 1060), (645, 1090), (620, 1030)],
        'cuff_gold_zone': (620, 1000, 692, 1130),
        'cuff_gold_seed': (655, 1045),
        'frill_zone': (595, 950, 665, 1075),
        'frill_seed': (612, 952),
        # costume items: zone + colour class + seed (positive per item)
        'items': [
            {'name': 'dress', 'blade_adjacent': True, 'box': (380, 880, 604, 1240),
             'class': 'dark_fabric', 'seed': (520, 940)},
            {'name': 'bow_chest', 'box': (430, 950, 560, 1105),
             'class': 'blue_violet', 'seed': (490, 1030)},
            {'name': 'shorts', 'box': (390, 1085, 625, 1230),
             'class': 'white', 'seed': (500, 1150)},
            {'name': 'thigh', 'box': (330, 1140, 545, 1300),
             'class': 'skin', 'seed': (430, 1210)},
            {'name': 'garter', 'box': (495, 1195, 565, 1262),
             'class': 'gold', 'seed': (528, 1228)},
            {'name': 'calf', 'box': (400, 1252, 545, 1400),
             'class': 'skin', 'seed': (470, 1300)},
            {'name': 'sock', 'box': (378, 1290, 560, 1400),
             'class': 'white', 'seed': (430, 1330)},
            {'name': 'shoe', 'box': (378, 1385, 545, 1470),
             'class': 'dark_fabric', 'seed': (450, 1420)},
            {'name': 'coattail_r', 'blade_adjacent': True, 'box': (683, 1050, 850, 1400),
             'class': 'dark_fabric', 'seed': (760, 1200)},
            {'name': 'sash_wide', 'blade_adjacent': True, 'box': (601, 1075, 830, 1270),
             'class': 'blue_violet', 'seed': (640, 1110)},
            {'name': 'dress_dark_r', 'blade_adjacent': True, 'box': (596, 1090, 655, 1165),
             'class': 'dark_fabric', 'seed': (625, 1120)},
            {'name': 'shorts_shadow', 'box': (500, 1110, 590, 1205),
             'class': 'warm_shadow', 'seed': (545, 1160)},
            {'name': 'shoe_gems', 'box': (405, 1395, 430, 1425),
             'class': 'gem_blue', 'seed': (416, 1408)},
            {'name': 'sleeve_gold', 'box': (405, 1070, 445, 1100),
             'class': 'gold', 'seed': (425, 1085)},
            {'name': 'shorts_trim', 'box': (505, 1100, 535, 1140),
             'class': 'blue_violet', 'seed': (520, 1118)},
            {'name': 'garter_strap', 'box': (495, 1195, 565, 1262),
             'class': ['dark_fabric', 'dark_warm'], 'seed': (528, 1228)},
            {'name': 'sleeve_piece', 'box': (595, 1075, 690, 1152),
             'class': 'dark_fabric', 'seed': (625, 1115)},
            {'name': 'sash', 'box': (712, 1140, 830, 1270),
             'class': 'blue_violet', 'seed': (760, 1200)},
        ],
    },
    # ---- cane: three declared corridors, complete colour coverage ----
    'cane_parts': [
        {'name': 'grip_guard', 'box': (620, 1000, 782, 1232),
         'exclude': [(615, 1105, 695, 1160)],
         'colors': ['gold', 'white', 'cyan', 'deep_blue', 'mid_blue',
                    'enamel_dark', 'dark_gold'],
         'seeds': [(725, 1065), (672, 1185), (700, 1100), (733, 1088), (695, 1115)], 'fill': 'holes'},
        {'name': 'pommel', 'box': (730, 905, 815, 1020),
         'colors': ['white', 'gold', 'cyan'],
         'seeds': [(770, 955)], 'fill': 'holes'},
        {'name': 'blade', 'box': (592, 1155, 722, 1450),
         'colors': ['deep_blue', 'mid_blue', 'silver', 'outline_dark',
                    'cyan', 'blade_highlight'],
         'seeds': [(660, 1260), (615, 1400)], 'fill': 'full'},
    ],
    'ribbon_false_box': (615, 1105, 695, 1160),
    'blade_spans': [
        (1156, 607, 694), (1162, 614, 641), (1168, 614, 636), (1174, 617, 641),
        (1180, 620, 645), (1186, 623, 655), (1192, 626, 667), (1198, 631, 669),
        (1204, 628, 649), (1210, 626, 649), (1216, 633, 649), (1222, 646, 665),
        (1228, 652, 682), (1234, 658, 680), (1240, 660, 678), (1246, 658, 675),
        (1252, 656, 673), (1258, 655, 670), (1264, 653, 668), (1270, 652, 666),
        (1276, 651, 663), (1282, 649, 661), (1288, 647, 658), (1294, 645, 656),
        (1300, 643, 654), (1306, 641, 651), (1312, 640, 649), (1318, 638, 647),
        (1324, 636, 644), (1330, 634, 642), (1336, 632, 640), (1342, 630, 637),
        (1348, 628, 635), (1354, 626, 633), (1360, 625, 631), (1366, 623, 629),
        (1372, 621, 626), (1378, 619, 624), (1384, 616, 622), (1390, 614, 620),
        (1396, 610, 619), (1402, 609, 621), (1408, 602, 620), (1414, 601, 617),
        (1420, 600, 613), (1426, 599, 613), (1432, 597, 609), (1438, 596, 606),
        (1444, 596, 602), (1449, 596, 600)],
    'hand_band': (715, 1035, 750, 1148),
    # ---- chair: complete warm-wood coverage inside the corridor ----
    'chair_corridor': (410, 1080, 730, 1470),
    'chair_shoe_guard': (390, 1390, 560, 1470),
    'chair_body_guard': (330, 1140, 545, 1262),
    'chair_seeds': [(600, 1275), (594, 1350), (677, 1300),
                    (500, 1272), (497, 1300)],
}

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


def tint_tail(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = (r + g + b) / 3.0
    pale = (b - r >= 18) & (bright >= 130) & (g >= r - 10)
    shadow = (g - r >= 25) & (b - r >= 35) & (bright >= 110) & (b > g)
    return pale | shadow


def colour_test(rgb, names):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = (r + g + b) / 3.0
    out = np.zeros(bright.shape, bool)
    for nm in names:
        if nm == 'gold':
            out |= (r >= 120) & (r > g) & (g > b) & (r - b >= 30)
        elif nm == 'white':
            out |= (bright >= 185) & (np.abs(b - r) <= 25)
        elif nm == 'shaft':
            out |= (b - r >= 60) & (b >= 140) & (bright < 210)
        elif nm == 'deep_blue':   # blade core
            out |= (b - r >= 65) & (b >= 110)
        elif nm == 'mid_blue':    # blade highlight / lighter blue body
            out |= (b - r >= 40) & (b >= 120) & (bright < 210)
        elif nm == 'cyan':        # eye inlays / gems
            out |= (g >= r + 25) & (b >= r + 40) & (bright >= 90)
        elif nm == 'blade_highlight':  # white-blue streaks on the blade
            out |= (bright >= 170) & (b - r >= 15) & (b >= g)
        elif nm == 'enamel_dark':  # dark blue enamel of the ornate grip
            out |= (bright <= 115) & (b - r >= 40) & (b > g)
        elif nm == 'gem_blue':     # dark blue shoe/gem accents
            out |= (b - r >= 50) & (b >= 90)
        elif nm == 'dark_warm':    # warm near-black (garter strap)
            out |= (bright <= 90) & (r >= g)
        elif nm == 'dark_gold':    # dark gold shading of the ornate grip
            out |= (bright <= 200) & (r > g) & (g >= b) & (r - b >= 25)
        elif nm == 'silver':      # blade tip
            out |= (bright >= 140) & (b - r >= 25) & (b - r <= 80) & (b >= 170)
        elif nm == 'outline_dark':  # dark outline / inlay / interior line
            out |= (bright <= 110) & (b_ > g_) if False else \
                (bright <= 110) & (b >= g)
        elif nm == 'dark_fabric':  # navy costume (dress / coat / shoe)
            out |= (bright <= 140) & (b >= g) & (b - r >= 15)
        elif nm == 'blue_violet':  # sash / ribbon fabric
            out |= (b - r >= 25) & (b - g >= 15) & (bright >= 90) & (bright <= 215)
        elif nm == 'skin':         # warm skin
            out |= (r >= 150) & (r > g) & (g >= b) & (r - b >= 25)
        elif nm == 'warm_shadow':  # warm fabric shadow / lining grey
            out |= (r >= g) & (r - b >= 8) & (bright >= 95) & (bright <= 190)
        else:
            raise SystemExit(f'unknown colour test {nm}')
    return out


def box_mask(shape, boxes):
    m = np.zeros(shape, bool)
    for x0, y0, x1, y1 in boxes:
        m[y0:y1, x0:x1] = True
    return m


def component_from_seeds(cand, seeds, max_search=25):
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
                sel = (ys >= y0) & (ys < y1) & (xs >= x0) & (xs < x1)
                if sel.any():
                    ident = lab[ys[sel][0], xs[sel][0]]
                    break
        if ident == 0:
            raise SystemExit(f'seed ({sx},{sy}): no candidate pixel within '
                             f'{max_search}px')
        out |= lab == ident
    return out


def build_protected_masks(rgb, alpha, d16):
    """R2 requirement: protected masks are built INCLUSION-ONLY from
    positive components inside declared zones.  No ~cane / ~chair /
    ~allowed / ~exclusion appears anywhere in this function."""
    h, w = alpha.shape
    p = d16['prot']
    rr, gg, bb2 = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright16 = (rr + gg + bb2) / 3.0
    dark_any16 = (bright16 < 130) & (bb2 - rr >= 10) & (bb2 - rr <= 60)
    prot = {}

    def seeded(mask, seeds):
        return component_from_seeds(mask, seeds)

    def all_comps(mask, min_px=150):
        lab, n = ndimage.label(mask, structure=ST8)
        out = np.zeros_like(mask)
        for i in range(1, n + 1):
            c = lab == i
            if int(c.sum()) >= min_px:
                out |= c
        return out

    # hair + hat + face (identity), positive components in declared zones
    zone = box_mask((h, w), [p['hair_zone']])
    hair = all_comps(fz_tint(rgb) & alpha & zone, 150)
    hat_zone = box_mask((h, w), [p['hat_zone']])
    hat = all_comps(colour_test(rgb, ['dark_fabric']) & alpha & hat_zone, 100)
    hat = hat | (ndimage.binary_fill_holes(hat) & alpha & hat_zone)
    face = all_comps(colour_test(rgb, ['skin']) & alpha
                     & box_mask((h, w), [p['face_zone']]), 100)
    prot['protected_existing_hair'] = (hair | hat | face) & alpha

    # quill (pale feather) + paper (white sheet)
    quill = all_comps(fz_tint(rgb) & alpha
                      & box_mask((h, w), [d16['quill_box']]), 80)
    paper = all_comps(colour_test(rgb, ['white']) & alpha
                      & box_mask((h, w), [d16['paper_box']]), 150)
    prot['protected_quill_paper'] = (quill | paper) & alpha

    # glove (dark, sleeve-connected) + cuff gold trim + white frill
    glove = all_comps(colour_test(rgb, ['dark_fabric']) & alpha
                      & box_mask((h, w), [p['glove_zone']]), 150)
    glove = glove | (ndimage.binary_fill_holes(glove) & alpha
                     & box_mask((h, w), [p['glove_zone']]) & ~dark_any16)
    cuff = all_comps(colour_test(rgb, ['gold']) & alpha
                     & box_mask((h, w), [p['cuff_gold_zone']]), 80)
    frill = all_comps(colour_test(rgb, ['white']) & alpha
                      & box_mask((h, w), [p['frill_zone']]), 80)
    prot['protected_glove_gold_cuff'] = glove | cuff | frill

    # costume: positive per-item components.  Items adjoining the cane use
    # the DECLARED blade span polygon (frozen geometry constants below the
    # plan header, never a removal mask) as a zone-level boundary so that
    # cane pixels can never enter costume protection.
    blade_poly = np.zeros_like(alpha)
    spans = d16['blade_spans']
    for (ya, la, ra), (yb, lb, rb) in zip(spans, spans[1:]):
        for y in range(ya, yb):
            t = (y - ya) / (yb - ya)
            xl = int(la + (lb - la) * t)
            xr = int(ra + (rb - ra) * t) + 1
            blade_poly[y, xl:xr] = True
    costume = np.zeros_like(alpha)
    for item in p['items']:
        zone = box_mask((h, w), [item['box']])
        if item.get('blade_adjacent'):
            zone &= ~blade_poly
        cols = item['class'] if isinstance(item['class'], list)             else [item['class']]
        costume |= all_comps(colour_test(rgb, cols) & alpha & zone, 40)
    prot['protected_costume'] = costume & alpha

    # every protected mask is closed to a single-pixel safety outline
    for k in prot:
        prot[k] = prot[k] & alpha
    return prot


def fz_tint(rgb):
    return tint_tail(rgb)


def build_props(rgb, alpha, d):
    cand = np.zeros_like(alpha)
    seeds = []
    for part in d['props_parts']:
        zone = box_mask(alpha.shape, [part['box']])
        cand |= colour_test(rgb, part['colors']) & alpha & zone
        seeds.extend(part['seeds'])
    return ndimage.binary_fill_holes(
        component_from_seeds(cand, seeds)) & alpha


def freeze_r1_a01_a05(asset, im):
    """Byte-identical re-run of the accepted R1 a01/a05 pipeline."""
    h, w = im.shape[:2]
    rgb = im[..., :3].astype(int)
    alpha = im[..., 3] > 8
    d = DECLARED_R1[asset]

    props = build_props(rgb, alpha, d)
    costume = box_mask((h, w), d['costume_boxes']) & alpha
    identity = box_mask((h, w), [d['protected_identity_box']]) & alpha
    cleanup = np.zeros((h, w), bool)
    for bx0, by0, bx1, by1 in d['cleanup_boxes']:
        zone = np.zeros((h, w), bool)
        zone[by0:by1, bx0:bx1] = alpha[by0:by1, bx0:bx1]
        cleanup |= zone
    cleanup = component_from_seeds(cleanup, d['cleanup_seeds'])
    costume = costume & ~cleanup
    identity = identity & ~cleanup

    corridor = box_mask((h, w), [d['tail_corridor']])
    tint = tint_tail(rgb) & alpha & corridor & ~props
    tail_core = component_from_seeds(tint, d['tail_seeds'])
    tail_solid = ndimage.binary_fill_holes(tail_core) & corridor
    shell_zone = ndimage.binary_dilation(tail_core, ST8,
                                         iterations=d['shell_radius'])
    hard_guard = identity | costume | props
    shell = shell_zone & alpha & corridor & ~tail_solid & ~hard_guard
    tail_source = (tail_solid | shell) & alpha & ~hard_guard
    if asset == 'a01':
        tail_source |= (tail_solid & alpha & ~props
                        & ~(identity | costume))
    dest = np.fliplr(tail_source) & ~alpha
    seam = np.zeros((h, w), bool)
    near = ndimage.binary_dilation(alpha, ST8, iterations=6)
    for x0, y0, x1, y1 in d['seam_boxes']:
        seam[y0:y1, x0:x1] |= ~alpha[y0:y1, x0:x1] & near[y0:y1, x0:x1]

    out = {'tail_source': tail_source,
           'old_tail_removal': tail_source,
           'tail_destination': dest,
           'seam_reconstruction': seam,
           'authorized_cleanup': cleanup,
           'protected_identity': identity,
           'protected_costume': costume,
           'protected_props': props}
    order = [m for m in MASK_ORDER if m in out]
    return out, order


def freeze_a16(im):
    h, w = im.shape[:2]
    rgb = im[..., :3].astype(int)
    alpha = im[..., 3] > 8
    r_, g_, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    br16 = (rgb[..., 0] + rgb[..., 1] + rgb[..., 2]) / 3.0
    br_ = b_ - r_

    # ---- 1. protected masks FIRST (inclusion-only), then frozen ----
    prot = build_protected_masks(rgb, alpha, D16)
    protected_all = np.zeros_like(alpha)
    for k in prot.values():
        protected_all |= k

    # ---- 2. tail (R1-identical construction) ----
    corridor = box_mask((h, w), [D16['tail_corridor']])
    tint = fz_tint(rgb) & alpha & corridor
    tail_core = component_from_seeds(tint, D16['tail_seeds'])
    tail_solid = ndimage.binary_fill_holes(tail_core) & corridor
    shell_zone = ndimage.binary_dilation(tail_core, ST8,
                                         iterations=D16['shell_radius'])
    shell = shell_zone & alpha & corridor & ~tail_solid & ~protected_all
    qp_zone = box_mask((h, w), [D16['quill_box'], D16['paper_box']])
    tail_source = tail_solid | shell
    tail_source = tail_source & ~qp_zone
    old_removal = tail_source
    dest = np.fliplr(tail_source) & ~alpha
    seam = np.zeros((h, w), bool)
    near = ndimage.binary_dilation(alpha, ST8, iterations=6)
    for x0, y0, x1, y1 in D16['seam_boxes']:
        seam[y0:y1, x0:x1] |= ~alpha[y0:y1, x0:x1] & near[y0:y1, x0:x1]
    cleanup = np.zeros((h, w), bool)
    for bx0, by0, bx1, by1 in D16['cleanup_boxes']:
        zone = np.zeros((h, w), bool)
        zone[by0:by1, bx0:bx1] = alpha[by0:by1, bx0:bx1]
        cleanup |= zone
    cleanup = component_from_seeds(cleanup, D16['cleanup_seeds'])

    # ---- 3. chair: complete warm-wood semantic mask ----
    warm = ((r_ > g_) & (g_ > b_) & (r_ - b_ >= 14) & (r_ - g_ <= 50)
            & (r_ >= 40) & (br16 <= 210)) & alpha
    ch_zone = box_mask((h, w), [D16['chair_corridor']])
    ch_cand = (warm & ch_zone
               & ~box_mask((h, w), [D16['chair_shoe_guard']])
               & ~box_mask((h, w), [D16['chair_body_guard']])
               & ~protected_all)
    chair = component_from_seeds(ch_cand, D16['chair_seeds'])
    near_prot = ndimage.binary_dilation(protected_all, ST8, iterations=2)
    filled = ndimage.binary_fill_holes(chair) & ch_zone & alpha & ~near_prot
    band = (ndimage.binary_dilation(chair, ST8, iterations=3) & ~chair
            & ch_zone & alpha & (br16 <= 210) & warm & ~near_prot)
    chair = ((filled & warm) | chair | band) & alpha
    chair = ndimage.binary_fill_holes(chair) & ch_zone & alpha & ~near_prot
    chair |= (ndimage.binary_fill_holes(chair) & alpha & ~protected_all
              & ch_zone & (br16 <= 210) & (r_ > g_) & (r_ - b_ >= 14))
    # dark warm outline band hugging the chair pieces (never near protected,
    # never the blue blade): r>=g dark pixels adjacent to the chair
    ch_band = (ndimage.binary_dilation(chair, ST8, iterations=5) & ~chair
               & ch_zone & alpha & (r_ >= g_) & (r_ - b_ >= 10)
               & (br16 <= 130) & ~near_prot)
    chair |= ch_band
    # lit top-edge highlight of the seat (bright warm-white line)
    ch_hl = (ndimage.binary_dilation(chair, ST8, iterations=5) & ~chair
             & ch_zone & alpha & (br16 >= 170) & (abs(r_ - g_) <= 30)
             & ~near_prot)
    chair |= ch_hl
    chair &= alpha

    # ---- 4. cane: complete multi-colour semantic mask ----
    cane = np.zeros_like(alpha)
    for part in D16['cane_parts']:
        zone = box_mask((h, w), [part['box']])
        zone &= ~box_mask((h, w), part.get('exclude', []))
        cand = colour_test(rgb, part['colors']) & alpha & zone & ~protected_all
        comp = component_from_seeds(cand, part['seeds'])
        if part['fill'] == 'full':
            grown = comp | (ndimage.binary_dilation(comp, ST8, iterations=3)
                            & (br16 <= 110) & (b_ >= g_) & zone & alpha
                            & ~near_prot)
            cane |= ndimage.binary_fill_holes(grown) & alpha & zone
        elif part['fill'] == 'holes':
            # grip: enclosed dark enamel/inlays are part of the cane; the
            # glove fingers are never fully enclosed by the gold
            cane |= ndimage.binary_fill_holes(comp) & alpha & zone
        else:  # 'none'
            cane |= comp & alpha
    # blade: declared span table (frozen sub-polygon, measured from master)
    spans = D16['blade_spans']
    for (ya, la, ra), (yb, lb, rb) in zip(spans, spans[1:]):
        for y in range(ya, yb):
            t = (y - ya) / (yb - ya)
            xl = int(la + (lb - la) * t)
            xr = int(ra + (rb - ra) * t) + 1
            cane[y, xl:xr] |= alpha[y, xl:xr]
    y_end, la, ra = spans[-1]
    cane[y_end:1450, la:ra] |= alpha[y_end:1450, la:ra]
    # blue-dark outline band around the blade spans (never near protected,
    # never inside the ribbon box, never warm chair pixels: r>=g excluded)
    b_band = (ndimage.binary_dilation(cane, ST8, iterations=4) & ~cane
              & box_mask((h, w), [(592, 1155, 722, 1450)])
              & alpha & (br16 <= 130)
              & ~box_mask((h, w), [D16['ribbon_false_box']])
              & ~near_prot)
    cane |= b_band
    cane &= alpha & ~near_prot

    # ---- 5. hand reconstruction (independent declared band) ----
    hx0, hy0, hx1, hy1 = D16['hand_band']
    hand = np.zeros((h, w), bool)
    gold_16 = ((r_ >= 120) & (r_ > g_) & (g_ > b_) & (r_ - b_ >= 30) & alpha)
    hand[hy0:hy1, hx0:hx1] = (gold_16[hy0:hy1, hx0:hx1]
                              & (br16[hy0:hy1, hx0:hx1] >= 130))
    hand &= ~box_mask((h, w), [(735, 910, 812, 1015)])
    hand &= alpha

    out = {'tail_source': tail_source,
           'old_tail_removal': old_removal,
           'tail_destination': dest,
           'seam_reconstruction': seam,
           'speck_cleanup': cleanup,
           'chair_removal': chair,
           'cane_removal': cane,
           'hair_reconstruction': np.zeros((h, w), bool),
           'hand_reconstruction': hand,
           'protected_existing_hair': prot['protected_existing_hair'],
           'protected_quill_paper': prot['protected_quill_paper'],
           'protected_glove_gold_cuff': prot['protected_glove_gold_cuff'],
           'protected_costume': prot['protected_costume'],
           'allowed_edit': None}
    allowed_terms = ['old_tail_removal', 'tail_destination',
                     'seam_reconstruction', 'speck_cleanup',
                     'chair_removal', 'cane_removal', 'hair_reconstruction',
                     'hand_reconstruction']
    allowed = np.zeros_like(alpha)
    for t in allowed_terms:
        allowed |= out[t]
    out['allowed_edit'] = allowed
    names = [m for m in MASK_ORDER if m in out and m != 'protected_identity']
    names += [m for m in A16_EXTRA if m in out and m not in names]
    return out, names, allowed_terms


pommel_zone = None


def paint(im_rgba, masks, order, bg_rgb):
    h, w = im_rgba.shape[:2]
    a = im_rgba[..., 3:4].astype(np.float32) / 255.0
    if bg_rgb is None:
        base = im_rgba[..., :3].astype(np.float32)
        out = base * a + 255.0 * (1 - a)
    else:
        base = np.full((h, w, 3), bg_rgb, np.float32)
        out = base * a + base * (1 - a)
    out = out.astype(np.float32)
    for name in order:
        if name == 'allowed_edit' or name.startswith('_'):
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
    plan = {'task': 'NIGHT03_RECOVERY_PATCH2A_R2_MASK_FREEZE',
            'base_sha': '98987c90e260fb4df500c3303c70d2b5ae82dde8',
            'canvas': list(CANVAS), 'inputs': {}, 'assets': {}}
    for pth in sorted(SPEC_DIR.glob('*.md')):
        plan['inputs'][f'_spec/{pth.name}'] = sha256_path(pth)
    plan['inputs']['BASE'] = sha256_path(BASE_P)
    plan['inputs']['PATCH1_REVIEW_REPORT'] = sha256_path(REVIEW_REPORT)

    fail = []
    for asset, fn in ASSETS.items():
        mp = MASTERS / fn
        im = np.array(Image.open(mp).convert('RGBA'))
        h, w = im.shape[:2]
        if asset in ('a01', 'a05'):
            masks, order = freeze_r1_a01_a05(asset, im)
            terms = ['old_tail_removal', 'tail_destination',
                     'seam_reconstruction', 'authorized_cleanup']
            u = np.zeros_like(masks['tail_source'])
            for t in terms:
                u |= masks[t]
            masks['allowed_edit'] = u
            if 'allowed_edit' not in order:
                order.append('allowed_edit')
        else:
            masks, order, terms = freeze_a16(im)
        adir = OUT / asset
        adir.mkdir(exist_ok=True)
        ent = {'master_file': f'data/assets_v2/masters/{fn}',
               'master_sha256': sha256_path(mp), 'masks': {},
               'allowed_terms': terms, 'intersections': {}}
        for name in order:
            if name.startswith('_'):
                continue
            m = masks[name]
            arr = m.astype(np.uint8) * 255
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
        if not ent['destination_on_transparent_only']:
            fail.append(f'{asset}: destination claims existing alpha')
        # residual accounting: every residual component is classified
        dcl = DECLARED_R1.get(asset, D16 if asset == 'a16' else None)
        hh, ww = im.shape[:2]
        corr = (DECLARED_R1[asset]['tail_corridor'] if asset in DECLARED_R1
                else D16['tail_corridor'])
        tint_all = (tint_tail(im[..., :3].astype(int)) & (im[..., 3] > 8)
                    & box_mask((hh, ww), [corr]))
        resid = tint_all & ~masks['tail_source']
        rl, rn = ndimage.label(resid, structure=ST8)
        tab = []
        total = 0
        classes = {}
        for i in range(1, rn + 1):
            c = rl == i
            px = int(c.sum())
            total += px
            ys, xs = np.where(c)
            bb = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
            if False:
                pass
            elif asset == 'a01':
                if bb[0] >= 302:
                    cls = 'lining_boundary_AA'
                elif bb[2] <= 302 and bb[3] <= 1064:
                    cls = 'upper_fringe'
                elif bb[0] >= 292 and bb[1] >= 1090:
                    cls = 'cane_boundary_AA'
                else:
                    cls = 'corridor_boundary_AA'
            elif asset == 'a05':
                cls = 'corridor_fringe'
            else:
                if bb[0] >= 302 or bb[1] <= 1140:
                    cls = 'paper_quill_boundary_AA'
                else:
                    cls = 'corridor_fringe'
            tab.append({'px': px, 'bbox': list(bb), 'class': cls})
            classes[cls] = classes.get(cls, 0) + px
        ent['boundary_residual_px'] = total
        ent['residual_components'] = tab
        ent['residual_class_px'] = classes
        ent['residual_total_equals_classes'] = bool(
            total == sum(classes.values()))
        if not ent['residual_total_equals_classes']:
            fail.append(f'{asset}: residual accounting mismatch')
        pass
        # evidence overlays
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

    # ---- mandatory cutout evidence (evidence only, never an input) ----
    for name, fn in (('a16', ASSETS['a16']),):
        im = np.array(Image.open(MASTERS / fn).convert('RGBA'))
        adir = OUT / name
        removals = np.zeros(im.shape[:2], bool)
        cane = np.array(Image.open(adir / 'a16_cane_removal.png')) == 255
        chair = np.array(Image.open(adir / 'a16_chair_removal.png')) == 255
        removals |= cane
        ch = checker(*im.shape[:2]).astype(np.float32)
        a = im[..., 3:4].astype(np.float32) / 255.0
        for tag, kill in (('cane', cane), ('chair', chair),
                          ('cane_chair', cane | chair)):
            cut = im.copy()
            cut[..., 3][kill] = 0
            for zname, bg in (('100', checker(*im.shape[:2]).astype(np.float32)),
                              ('dark', np.full(im.shape[:2], 32, np.float32)[..., None]
                               if im.ndim == 3 else None),
                              ('light', np.full(im.shape[:2], 240, np.float32)[..., None])):
                pass
            bgc = checker(*im.shape[:2]).astype(np.float32)
            arr = cut.astype(np.float32)
            aa = arr[..., 3:4] / 255.0
            comp = (arr[..., :3] * aa + bgc * (1 - aa)).clip(0, 255).astype(np.uint8)
            Image.fromarray(comp).save(adir / f'a16_{tag}_cutout_checker_100.png')
            for z, zx in ((200, 2), (400, 4)):
                reg = {'cane': (592, 1155, 722, 1450),
                       'chair': (410, 1080, 730, 1470),
                       'cane_chair': (410, 905, 815, 1450)}[tag]
                cx0, cy0, cx1, cy1 = reg
                sub = Image.fromarray(comp[cy0:cy1, cx0:cx1]).resize(
                    ((cx1 - cx0) * zx, (cy1 - cy0) * zx), Image.NEAREST)
                sub.save(adir / f'a16_{tag}_cutout_checker_{z}.png')

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
            comp = (arr[..., :3] * a + bgc * (1 - a)).clip(0, 255).astype(np.uint8)
            Image.fromarray(comp).save(
                OUT / asset / f'{asset}_crop_{cname}_{z}x.png')

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
