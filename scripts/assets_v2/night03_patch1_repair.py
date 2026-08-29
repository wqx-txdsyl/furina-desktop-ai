"""NIGHT-03 Patch 1 — pilot repair builder (a01, a05, a16).

Method per asset (semantic layering, tail relocation to BASE-consistent side):
  1. tail_source_mask : corridor ∩ alpha minus protections  (old wrong-side tail)
  2. removal_mask      : tail + outline + (a05 wisp) + (a16 chair/cane/specks)
  3. protected_*       : identity / costume / prop masks (per asset geometry)
  4. allowed_edit_mask : strict union of actual edit regions
  5. the master body pixels are bit-identical outside allowed_edit_mask.

Writes only under data/assets_v2/repair_candidates/night03_patch1/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from night03_patch1_lib import (composite_behind, dil, fill_holes, label_comps,
                                poly_mask, rect_mask, strips_mask, tint_tail)

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch1'
OUT.mkdir(parents=True, exist_ok=True)
AXIS = 512.0


def load(key, name):
    return np.array(Image.open(MASTERS / f'furina_v2_{key}_{name}.png'))


def stats(mask):
    if not mask.any():
        return {'px': 0, 'bbox': None}
    ys, xs = np.where(mask)
    return {'px': int(mask.sum()),
            'bbox': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]}


# ---------------------------------------------------------------- a01
A01_CORRIDOR = [
    (386, 944), (356, 942), (334, 970), (316, 1004), (294, 1040),
    (246, 1054), (198, 1072), (172, 1104), (164, 1150), (164, 1196),
    (170, 1238), (182, 1280), (196, 1318), (214, 1352), (243, 1374),
    (282, 1368), (311, 1346), (338, 1328), (357, 1310), (355, 1296),
    (348, 1262), (342, 1230), (341, 1204), (346, 1174), (352, 1148),
    (362, 1120), (370, 1086), (374, 1044), (382, 990),
]
A01_SHAFT = [
    ((316, 1170), (318, 1240), 22),
    ((318, 1240), (322, 1310), 21),
    ((322, 1310), (327, 1380), 20),
    ((327, 1380), (332, 1425), 20),
    ((332, 1425), (335, 1455), 18),
]


def ring_mask(shape, cx, cy, rx, ry, pad=0):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    e = ((xx - cx) / (rx + pad)) ** 2 + ((yy - cy) / (ry + pad)) ** 2
    return e <= 1.0


def build_a01():
    im = load('a01', 'stand_neutral_front')
    rgb = im[..., :3].astype(int)
    alpha = im[..., 3] > 8
    shape = im.shape[:2]

    corr = poly_mask(shape, A01_CORRIDOR) & alpha
    tint = tint_tail(rgb) & alpha
    # dark solid = arm/glove/coat/cane body parts (glove/coat navy is <80 bright)
    dark = (rgb.sum(2) / 3 < 80) & alpha
    lab, n = ndimage.label(dark, structure=ndimage.generate_binary_structure(2, 2))
    dist = ndimage.distance_transform_edt(dark)
    dark_thick = np.zeros_like(dark)
    for i in range(1, n + 1):
        c = lab == i
        if c.sum() >= 14 and float(dist[c].max()) >= 7:
            dark_thick |= c
    # cane protection: ring + gold guard + crystal diamond + shaft strips
    cane_prot = (ring_mask(shape, 303, 1042, 44, 52)
                 | ring_mask(shape, 302, 1144, 26, 30)     # crystal diamond
                 | ring_mask(shape, 300, 1190, 32, 20)     # gold claw feet
                 | strips_mask(shape, A01_SHAFT))
    r_, g_, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    gold = (((r_ > 150) & (g_ > 95) & (b_ < 170) & (r_ - b_ >= 40))
            | ((r_ >= 100) & (r_ - b_ >= 60) & (g_ - b_ >= 20))) & alpha
    # identity/costume protection: frills sit at x>=383 (no corridor overlap).
    # dark_thick is confined to the arm/cuff/finger rectangles so the tail's own
    # dark curl strokes (thin, inside the fan) are NOT mistaken for body.
    frills = rect_mask(shape, 383, 1278, 700, 1400)
    body_dark = dark_thick & (rect_mask(shape, 250, 840, 415, 1010)
                              | rect_mask(shape, 262, 900, 368, 1030)
                              | rect_mask(shape, 283, 985, 368, 1195))
    prot = body_dark | cane_prot | frills | gold

    # tail identification: tint core components inside corridor (>=400px, real tint)
    comps = label_comps(dil(tint & corr, 3) & corr & ~prot, min_px=60)
    final = np.zeros_like(alpha)
    for c, sz, x0, y0, x1, y1 in comps:
        if int((c & tint).sum()) >= 250 and sz >= 400:
            final |= c
    # deletion = the whole corridor alpha that is not protected (tail + outline +
    # soft outer glow + inner dark strokes; body bits are excluded via protections)
    tail_source = corr & alpha & ~prot
    removal = tail_source
    body = im.copy()
    body[removal] = 0
    # patch
    ys, xs = np.where(removal)
    x0, y0_, x1, y1_ = xs.min(), ys.min(), xs.max(), ys.max()
    sub = im[y0_:y1_ + 1, x0:x1 + 1]
    m = removal[y0_:y1_ + 1, x0:x1 + 1]
    patch = np.zeros((*m.shape, 4), np.uint8)
    patch[..., :3] = np.where(m[..., None], sub[..., :3], 0)
    patch[..., 3] = np.where(m, sub[..., 3], 0)
    # fill occluder holes (cane ring/shaft, glove/arm) with nearest tail-coloured
    # pixels, capped so real windows stay open; light blur blends the fills.
    occ_local = (cane_prot | (dark_thick & corr))[y0_:y1_ + 1, x0:x1 + 1]
    filled, n_enc = patch_fill(patch, occluders=occ_local)
    # mirror about AXIS
    mpatch = np.ascontiguousarray(filled[:, ::-1])
    w = filled.shape[1]
    nx = int(round(2 * AXIS - (x0 + w)))
    out = composite_behind(body, mpatch, (nx, y0_))
    # scan out-of-allowed diffs
    diff = out != im
    d = diff.any(axis=-1)
    allowed = removal | np.zeros_like(removal)
    # allowed also includes patch footprint (any pixel actually changed by add)
    acc = np.zeros_like(removal)
    acc[y0_:y1_ + 1, nx:nx + w] |= (mpatch[..., 3] > 0)
    allowed |= acc
    out, debris_m, weld_m = post_cleanup(out, allowed)
    allowed = allowed | debris_m | weld_m
    outside = d & ~allowed
    masks = {'corridor': corr, 'tail_source': tail_source, 'removal': removal,
             'protected_dark': dark_thick, 'protected_cane': cane_prot,
             'protected_frills': frills, 'allowed_edit': allowed,
             'patch_footprint': acc, 'explicit_debris': debris_m, 'weld': weld_m}
    info = {'removal_px': int(removal.sum()), 'patch_px': int((mpatch[..., 3] > 0).sum()),
            'patch_pos': [nx, int(y0_)], 'outside_diff': int(outside.sum()),
            'filled_px': n_enc}
    return out, masks, info


def _dims(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return r, g, b, (r + g + b) / 3.0


def row_bridge(patch, max_gap=44, max_delta=80):
    m = patch[..., 3] > 0
    out = patch.copy()
    bridged = 0
    h, w = m.shape
    for y in range(h):
        xs = np.where(m[y])[0]
        if xs.size < 2:
            continue
        runs = np.split(xs, np.where(np.diff(xs) > 1)[0] + 1)
        for i in range(len(runs) - 1):
            l, r = runs[i][-1], runs[i + 1][0]
            gap = r - l - 1
            if not (0 < gap <= max_gap):
                continue
            c0 = out[y, l, :3].astype(int)
            c1 = out[y, r, :3].astype(int)
            if np.abs(c1 - c0).max() > max_delta:
                continue
            wgt = np.linspace(0, 1, gap + 2)[1:-1, None]
            out[y, l + 1:r, :3] = (c0 * (1 - wgt) + c1 * wgt).astype(np.uint8)
            out[y, l + 1:r, 3] = 255
            bridged += int(gap)
    return out, bridged


def patch_fill(patch, occluders=None, max_dist=60):
    """Fill occluder holes (cane ring/shaft, glove/arm) by harmonic diffusion from
    the surrounding tail pixels (no cell boundaries), capped to the occluder zones."""
    m = patch[..., 3] > 0
    if occluders is None:
        occluders = ndimage.binary_fill_holes(m)
    holes = occluders & ~m
    dist, (iy, ix) = ndimage.distance_transform_edt(~m, return_indices=True)
    sel = holes & (dist <= max_dist)
    filled = int(sel.sum())
    out = patch.copy()
    if filled:
        sub = out[..., :3].astype(np.float32)
        work = sub.copy()
        for _ in range(40):
            nxt = ndimage.gaussian_filter(work, sigma=(1.0, 1.0, 0))
            work[sel] = nxt[sel]
            work[~sel] = sub[~sel]
        out[sel, :3] = work[sel].astype(np.uint8)
        out[sel, 3] = 255
    return out, filled


# ---------------------------------------------------------------- a05
A05_CORRIDOR = [
    (368, 890), (372, 955), (374, 1000), (370, 1050), (358, 1078),
    (338, 1090), (310, 1096), (302, 1110), (296, 1128), (298, 1140),
    (312, 1150), (340, 1155), (356, 1164), (358, 1180), (360, 1202),
    (362, 1222), (356, 1240), (342, 1252), (330, 1262), (320, 1280),
    (302, 1298), (286, 1299), (270, 1301), (252, 1302), (234, 1294),
    (218, 1266), (200, 1240), (174, 1216), (154, 1192), (144, 1162),
    (144, 1120), (148, 1082), (172, 1040), (214, 1000), (268, 966),
    (316, 928), (340, 905),
]
A05_BOW_RECT = (374, 858, 500, 1096)


def build_a05():
    im = load('a05', 'stand_confident_proud')
    rgb = im[..., :3].astype(int)
    alpha = im[..., 3] > 8
    shape = im.shape[:2]
    corr = poly_mask(shape, A05_CORRIDOR) & alpha
    tint = tint_tail(rgb) & alpha

    dark = (rgb.sum(2) / 3 < 80) & alpha
    lab, n = ndimage.label(dark, structure=ndimage.generate_binary_structure(2, 2))
    dist = ndimage.distance_transform_edt(dark)
    dark_thick = np.zeros_like(dark)
    for i in range(1, n + 1):
        c = lab == i
        if c.sum() >= 14 and float(dist[c].max()) >= 7:
            dark_thick |= c
    # body/costume geometric protections (no colour-only deletion anywhere)
    bow = rect_mask(shape, *A05_BOW_RECT)
    arm = rect_mask(shape, 330, 820, 430, 1000)          # upper arm + shoulder
    hip = rect_mask(shape, 300, 990, 460, 1160)          # her right hand/forearm on hip
    shorts = rect_mask(shape, 322, 1092, 560, 1470)      # shorts + both legs
    body_dark = dark_thick & (arm | rect_mask(shape, 330, 950, 440, 1160))
    r_, g_, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    gold = (((r_ > 150) & (g_ > 95) & (b_ < 170) & (r_ - b_ >= 40))
            | ((r_ >= 100) & (r_ - b_ >= 60) & (g_ - b_ >= 20))) & alpha
    prot = body_dark | bow | arm | hip | shorts | gold

    comps = label_comps(dil(tint & corr, 3) & corr & ~prot, min_px=60)
    final = np.zeros_like(alpha)
    for c, sz, x0, y0, x1, y1 in comps:
        if int((c & tint).sum()) >= 250 and sz >= 400:
            final |= c
    tail_source = corr & alpha & ~prot
    # explicit_debris_mask: detached tail wisp island (ratified 625-662 / 1284-1313)
    wisp = rect_mask(shape, 615, 1276, 672, 1322) & alpha
    removal = tail_source | wisp
    body = im.copy()
    body[removal] = 0
    ys, xs = np.where(tail_source)
    x0, y0_, x1, y1_ = xs.min(), ys.min(), xs.max(), ys.max()
    sub = im[y0_:y1_ + 1, x0:x1 + 1]
    m = tail_source[y0_:y1_ + 1, x0:x1 + 1]
    patch = np.zeros((*m.shape, 4), np.uint8)
    patch[..., :3] = np.where(m[..., None], sub[..., :3], 0)
    patch[..., 3] = np.where(m, sub[..., 3], 0)
    occ_local = (prot | (dark_thick & corr))[y0_:y1_ + 1, x0:x1 + 1]
    filled, n_enc = patch_fill(patch, occluders=occ_local)
    mpatch = np.ascontiguousarray(filled[:, ::-1])
    w = filled.shape[1]
    nx = int(round(2 * AXIS - (x0 + w)))
    out = composite_behind(body, mpatch, (nx, y0_))

    diff = out != im
    d = diff.any(axis=-1)
    allowed = removal.copy()
    acc = np.zeros_like(removal)
    acc[y0_:y1_ + 1, nx:nx + w] |= (mpatch[..., 3] > 0)
    allowed |= acc
    out, debris_m, weld_m = post_cleanup(out, allowed)
    allowed = allowed | debris_m | weld_m
    outside = d & ~allowed
    masks = {'corridor': corr, 'removal': removal,
             'protected_bow': bow, 'protected_arm': arm, 'protected_hip': hip,
             'protected_shorts': shorts, 'allowed_edit': allowed,
             'patch_footprint': acc, 'explicit_debris': debris_m, 'weld': weld_m}
    info = {'removal_px': int(removal.sum()), 'patch_px': int((mpatch[..., 3] > 0).sum()),
            'patch_pos': [nx, int(y0_)], 'outside_diff': int(outside.sum()),
            'filled_px': n_enc}
    return out, masks, info


# ---------------------------------------------------------------- a16
A16_CORRIDOR = [
    (452, 1170), (420, 1178), (355, 1176), (315, 1156), (258, 1146),
    (208, 1152), (190, 1172), (183, 1205), (178, 1245), (180, 1275),
    (190, 1300), (204, 1322), (218, 1322), (232, 1350), (248, 1384),
    (262, 1410), (278, 1426), (296, 1430), (312, 1428), (332, 1422),
    (350, 1410), (360, 1392),
    (356, 1368), (344, 1348), (330, 1332), (312, 1318), (298, 1300),
    (290, 1280), (286, 1258), (288, 1240), (302, 1232), (322, 1224),
    (342, 1216), (362, 1208), (382, 1202), (404, 1198), (428, 1188),
    (448, 1180),
]
A16_SPECK_RECTS = [(273, 1016, 285, 1026), (306, 1062, 313, 1075),
                   (279, 952, 287, 960)]
A16_CANE_ZONES = {
    'pommel': (745, 902, 862, 1046),
    'cream': (748, 1000, 800, 1092),
    'guard': (628, 1086, 764, 1154),
    'tip': (572, 1380, 660, 1478),
}
A16_CANE_SHAFT = [
    ((706, 1140), (688, 1250), 32),
    ((688, 1250), (658, 1330), 30),
    ((658, 1330), (624, 1420), 26),
    ((696, 1316), (668, 1424), 24),
]


def build_a16():
    im = load('a16', 'work_focused')
    rgb = im[..., :3].astype(int)
    r_, g_, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    alpha = im[..., 3] > 8
    shape = im.shape[:2]
    bright = (r_ + g_ + b_) / 3.0

    # --- identity/costume/prop protections -------------------------------
    hair_zone = rect_mask(shape, 180, 690, 900, 1018)      # head/hair/hat
    quill_paper = poly_mask(shape, [(330, 982), (482, 985), (478, 1160),
                                    (332, 1162)])
    skin = (r_ > g_ + 10) & (r_ - b_ >= 18) & (bright >= 150) & (g_ >= b_)
    legs = poly_mask(shape, [(268, 1035), (630, 1035), (630, 1510),
                             (430, 1510), (330, 1420), (292, 1330)])
    skin_prot = skin & legs
    navy_prot = (bright < 95) & (b_ - r_ >= 22) & alpha   # glove/hair/skirt navy
    gold = (((r_ > 170) & (g_ > 120) & (b_ < 160) & (r_ - b_ >= 50))
            | ((r_ >= 100) & (r_ - b_ >= 60) & (g_ - b_ >= 20))) & alpha
    # --- chair (wood) deletion -------------------------------------------
    wood = (r_ > g_) & (g_ > b_) & (r_ - b_ >= 28) & (r_ - g_ <= 34) \
        & (r_ >= 62) & (r_ < 205)
    wood_dark = (r_ > g_) & (g_ > b_) & (r_ - b_ >= 14) & (r_ - g_ <= 26) \
        & (r_ >= 48) & (r_ < 100)
    wood_zone = poly_mask(shape, [(332, 1102), (800, 1102), (800, 1490),
                                  (700, 1490), (620, 1430), (560, 1400),
                                  (470, 1380), (400, 1330), (352, 1250)])
    # warm-brown chairs woods with wider hue spread, gated by confirmed-wood density
    # so skin shadows (which never neighbour wood) are untouched
    base_wood = wood | wood_dark
    wood2_raw = (r_ > g_) & (g_ > b_) & (r_ - b_ >= 25) & (r_ - g_ >= 28) \
        & (r_ - g_ <= 50) & (r_ >= 90) & (r_ < 175)
    dens_wood = ndimage.gaussian_filter((base_wood | (wood2_raw & wood_zone)).astype(np.float32),
                                        sigma=12)
    nb_bright = (ndimage.gaussian_filter((bright * alpha).astype(np.float32), sigma=16)
                 / np.maximum(ndimage.gaussian_filter(alpha.astype(np.float32), sigma=16), 1e-3))
    wood2 = wood2_raw & (dens_wood >= 0.10) & (nb_bright <= 155)
    # mid-brown chair woods (r-g 30-46): only near confirmed wood, away from bright skin
    wood_mid = (r_ > g_) & (g_ > b_) & (r_ - b_ >= 28) & (r_ - g_ >= 30) \
        & (r_ - g_ <= 46) & (r_ >= 85) & (r_ < 165)
    dens_mid = ndimage.gaussian_filter((base_wood | (wood_mid & wood_zone)).astype(np.float32),
                                       sigma=12)
    wood_mid &= (dens_mid >= 0.06) & (nb_bright <= 148)
    chair_del = (base_wood | wood2 | wood_mid) & wood_zone & alpha & ~navy_prot & ~skin_prot
    chair_del &= ~(r_ < 40)  # never delete near-black
    # --- cane deletion ----------------------------------------------------
    cz = np.zeros(shape[:2], bool)
    for x0c, y0c, x1c, y1c in A16_CANE_ZONES.values():
        cz |= rect_mask(shape, x0c, y0c, x1c, y1c)
    cz |= strips_mask(shape, A16_CANE_SHAFT)
    white_pommel = (bright >= 190) & (b_ >= r_) & (b_ - r_ <= 40) \
        & (np.abs(g_ - r_) <= 20)
    cream = (r_ >= 185) & (b_ >= 140) & (g_ < r_ - 12) & (r_ - g_ <= 60) \
        & (g_ - b_ >= 12)
    crystal = (b_ >= 100) & (b_ - r_ >= 45) & (b_ - g_ <= 55)
    tip_zone = rect_mask(shape, 572, 1424, 656, 1478)
    tip_pale = (b_ >= r_) & (b_ - r_ >= 12) & (bright >= 120) & (bright <= 215)
    cane_dark = (bright < 95) & (b_ - r_ <= 26)       # pommel outline/knob shade
    cane_tint = white_pommel | cream | gold | crystal | cane_dark
    glove_zone = rect_mask(shape, 600, 930, 795, 1100)
    # thin dark lines (cane shaft edges/outline) - thickness test, not colour
    dark_all = (bright < 105) & alpha
    labd, nd_ = ndimage.label(dark_all, structure=ndimage.generate_binary_structure(2, 2))
    distd = ndimage.distance_transform_edt(dark_all)
    thin_dark_m = np.zeros_like(dark_all)
    for i in range(1, nd_ + 1):
        cd = labd == i
        if cd.sum() >= 3 and float(distd[cd].max()) <= 7:
            thin_dark_m |= cd
    navy_soft = navy_prot & ~glove_zone          # cane shaft navy below the glove
    # the shaft's wide dark side hugs its teal core; coat creases do not
    near_crystal = dil(crystal & alpha, 12)
    strip_navy = strips_mask(shape, A16_CANE_SHAFT) & navy_soft & near_crystal
    cane_del = cz & alpha & (cane_tint | (navy_soft & thin_dark_m) | strip_navy) \
        & ~(navy_prot & glove_zone)
    cane_del |= tip_zone & tip_pale & alpha
    # guard dark backing block (thick navy the colour tests spare)
    guard_full = rect_mask(shape, 686, 1086, 766, 1156)
    cane_del |= guard_full & alpha & ~skin_prot & ~hair_zone
    # dark teal gem/crystal edges misread as navy: g rises with b on crystal
    crystal_dark = (b_ - r_ >= 80) & (g_ >= 70) & (b_ >= 110) & alpha
    cane_del |= cz & crystal_dark
    # remnant sweep inside the pommel zone: neutral gray/gold shades of the head,
    # sparing the hair (comps containing true navy) and its pale highlights
    hairish = (bright < 175) & (b_ - r_ >= 5) & alpha
    hz = rect_mask(shape, 695, 895, 785, 1100)
    labh, nh = ndimage.label(hairish & hz, structure=ndimage.generate_binary_structure(2, 2))
    hair_prot = np.zeros_like(hairish)
    for i in range(1, nh + 1):
        ch = labh == i
        if (ch & navy_prot).any():
            hair_prot |= ch
    remnant = (cz & alpha & (bright >= 110) & (bright <= 215)
               & (np.abs(b_ - r_) <= 34) & (b_ >= r_ - 8) & ~hair_prot & ~navy_prot)
    remnant |= (cz & alpha & (r_ >= 200) & (g_ >= 200) & (b_ <= 215) & (r_ - b_ >= 30))
    cane_del |= remnant
    # --- specks (explicit debris) -----------------------------------------
    specks = np.zeros(shape[:2], bool)
    for x0c, y0c, x1c, y1c in A16_SPECK_RECTS:
        specks |= rect_mask(shape, x0c, y0c, x1c, y1c) & alpha
    # --- tail corridor ------------------------------------------------------
    corr = poly_mask(shape, A16_CORRIDOR) & alpha
    tint = tint_tail(rgb) & alpha
    # navy protection does not apply inside the tail corridor (the tail's own dark
    # strokes are navy); the boot/shoe rectangle keeps its protection
    boot_rect = rect_mask(shape, 320, 1360, 640, 1510)
    navy_eff = navy_prot & ~(corr & ~boot_rect)
    prot = navy_eff | skin_prot | quill_paper | hair_zone
    comps = label_comps(dil(tint & corr, 3) & corr & ~prot, min_px=60)
    final = np.zeros_like(alpha)
    for c, sz, x0, y0, x1, y1 in comps:
        if int((c & tint).sum()) >= 250 and sz >= 400:
            final |= c
    tail_source = corr & alpha & ~prot
    # --- apply deletions ----------------------------------------------------
    removal = tail_source | chair_del | cane_del | specks
    body = im.copy()
    body[removal] = 0
    # --- fill holes left by cane (fist gaps + coat/pommel cuts) --------------
    body, filled_fist = fill_cane_holes(body, cane_del, cane_tint)
    # --- tail patch ----------------------------------------------------------
    ys, xs = np.where(tail_source)
    x0, y0_, x1, y1_ = xs.min(), ys.min(), xs.max(), ys.max()
    sub = im[y0_:y1_ + 1, x0:x1 + 1]
    m = tail_source[y0_:y1_ + 1, x0:x1 + 1]
    patch = np.zeros((*m.shape, 4), np.uint8)
    patch[..., :3] = np.where(m[..., None], sub[..., :3], 0)
    patch[..., 3] = np.where(m, sub[..., 3], 0)
    # occluder zones inside the patch (chair/seat over the tail) are bridged
    occ_local = chair_del[y0_:y1_ + 1, x0:x1 + 1]
    filled, n_enc = patch_fill(patch, occluders=ndimage.binary_fill_holes(m))
    mpatch = np.ascontiguousarray(filled[:, ::-1])
    w = filled.shape[1]
    nx = int(round(2 * AXIS - (x0 + w)))
    out = composite_behind(body, mpatch, (nx, y0_))

    diff = out != im
    d = diff.any(axis=-1)
    allowed = removal.copy()
    acc = np.zeros_like(removal)
    acc[y0_:y1_ + 1, nx:nx + w] |= (mpatch[..., 3] > 0)
    allowed |= acc
    out, debris_m, weld_m = post_cleanup(out, allowed)
    allowed = allowed | debris_m | weld_m
    outside = d & ~allowed
    masks = {'corridor': corr, 'removal': removal, 'chair_del': chair_del,
             'cane_del': cane_del, 'specks': specks, 'protected_skin': skin_prot,
             'protected_navy': navy_prot, 'quill_paper': quill_paper,
             'protected_hair': hair_zone, 'allowed_edit': allowed,
             'patch_footprint': acc, 'explicit_debris': debris_m, 'weld': weld_m}
    info = {'removal_px': int(removal.sum()), 'chair_px': int(chair_del.sum()),
            'cane_px': int(cane_del.sum()), 'specks_px': int(specks.sum()),
            'patch_px': int((mpatch[..., 3] > 0).sum()),
            'patch_pos': [nx, int(y0_)], 'outside_diff': int(outside.sum()),
            'filled_px': n_enc, 'fist_fill_px': filled_fist}
    return out, masks, info


def fill_cane_holes(body, cane_del, cane_tint, dens_thr=0.35):
    """Diffusion-fill the holes the cane removal left inside the fist / hair / coat
    foreground.  Fill sources EXCLUDE the cane palette (white/cream/gold/crystal)
    so the fill inherits cloth/hair/skin tones instead of re-creating the cane.
    Holes standing against the empty background stay open."""
    if int(cane_del.sum()) == 0:
        return body, 0
    a = body[..., 3] > 8
    src = a & ~cane_tint
    dens = ndimage.gaussian_filter(src.astype(np.float32), sigma=14)
    fill_zone = rect_mask(body.shape[:2], 610, 943, 774, 1094)   # fist finger gaps
    bl = cane_del & (dens >= dens_thr) & fill_zone
    filled = int(bl.sum())
    if bl.any():
        work = body.copy()
        reg = work[..., :3].astype(np.float32)
        base = reg.copy()
        for _ in range(40):
            nxt = ndimage.gaussian_filter(reg, sigma=(1.0, 1.0, 0))
            reg[bl] = nxt[bl]
            reg[~bl] = base[~bl]
        work[bl, :3] = reg[bl].astype(np.uint8)
        work[bl, 3] = 255
        return work, filled
    return body, filled


def shape_a(im):
    return im.shape[:2]


def post_cleanup(im, allowed, dust_max=40, weld_max=1500, weld_dist=18):
    """Final alpha hygiene: detached dust comps (<= dust_max px) are removed as
    explicit debris; mid-size floaters (hair fragments cut loose by prop removal)
    are welded back to the main component with a 2px bridge of their own edge
    colour.  Returns (image, debris_mask, weld_mask)."""
    a = im[..., 3] > 8
    lab, n = ndimage.label(a)   # 4-connectivity, matching the objective gate
    if n <= 1:
        return im, np.zeros_like(a), np.zeros_like(a)
    sizes = ndimage.sum(a, lab, range(1, n + 1))
    main = int(np.argmax(sizes)) + 1
    out = im.copy()
    debris = np.zeros_like(a)
    weld = np.zeros_like(a)
    weld_cols = []
    st = ndimage.generate_binary_structure(2, 2)
    for i in range(1, n + 1):
        if i == main:
            continue
        comp = lab == i
        sz = int(sizes[i - 1])
        if sz <= dust_max:
            debris |= comp
            continue
        if sz <= weld_max:
            dm = ndimage.distance_transform_edt(lab != main)
            df = ndimage.distance_transform_edt(lab != i)
            band = np.zeros_like(a)
            band[df <= weld_dist] = True
            cand = band & (dm <= weld_dist)
            if not cand.any():
                debris |= comp
                continue
            ys, xs = np.where(cand)
            pm = (ys[np.argmin(df[ys, xs])], xs[np.argmin(df[ys, xs])])  # nearest main
            pf = (ys[np.argmin(dm[ys, xs])], xs[np.argmin(dm[ys, xs])])  # nearest fragment
            k = int(max(abs(pm[0] - pf[0]), abs(pm[1] - pf[1]))) + 1
            fw = np.zeros_like(a)
            for t in range(k + 1):
                yy = int(round(pf[0] + (pm[0] - pf[0]) * t / max(k, 1)))
                xx = int(round(pf[1] + (pm[1] - pf[1]) * t / max(k, 1)))
                fw[max(0, yy - 1):yy + 2, max(0, xx - 1):xx + 2] = True
            weld |= fw
            weld_cols.append((fw, out[comp, :3][out[comp, 3] > 8].mean(0)))
    if debris.any():
        out[debris] = 0
    for fw, cols in weld_cols:
        out[fw, :3] = np.tile(cols.astype(np.uint8), (int(fw.sum()), 1))
        out[fw, 3] = 255
    return out, debris, weld


ASSETS = {'a01': build_a01, 'a05': build_a05, 'a16': build_a16}


def jsan(v):
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (list, tuple)):
        return [jsan(t) for t in v]
    return v


def main():
    report = {}
    for key, fn in ASSETS.items():
        out, masks, info = fn()
        Image.fromarray(out).save(OUT / f'furina_v2_{key}_repair.png')
        report[key] = {'info': jsan(info),
                       'masks': {k: stats(v) for k, v in masks.items()}}
        # mask overlay (flat | overlay) for review
        from PIL import Image as I
        base = I.fromarray(out)
        ov = np.array(base).copy()
        colors = {'corridor': (90, 200, 255), 'tail_source': (255, 255, 0),
                  'removal': (255, 0, 0), 'protected_dark': (0, 90, 0),
                  'protected_cane': (255, 140, 0), 'protected_frills': (255, 0, 255),
                  'patch_footprint': (0, 255, 140), 'allowed_edit': (255, 255, 255),
                  'protected_bow': (255, 0, 255), 'protected_arm': (0, 90, 0),
                  'protected_hip': (128, 0, 128), 'protected_shorts': (255, 0, 130)}
        for k, m in masks.items():
            if k == 'allowed_edit':
                continue
            c = colors.get(k, (255, 255, 0))
            ov[m, :3] = c
            ov[m, 3] = 255
        I.fromarray(ov).save(OUT / f'{key}_mask_overlay.png')
        print(key, json.dumps(jsan(info)))
    (OUT / '_pilot_patch1.json').write_text(json.dumps(report, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
