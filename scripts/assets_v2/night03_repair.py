"""NIGHT-03 — Art Alpha Tail & Matte Repair (local surgical pipeline).

Pilots a01/a05/a16 then conditional batch repair.  Zero generation calls:
tail MIRRORED_ERROR is repaired by extract->span-fill->mirror->composite-behind;
matte/prop defects are removed by colour/strip masks with row-lerp infill.
Writes only under data/assets_v2/repair_candidates/night03/.  Masters untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from night03_tail_lib import (build_patch, composite_behind, delete_pixels,
                              extract_tail_region, hair_mask, line_strip_mask,
                              row_span_fill)

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03'
OUT.mkdir(parents=True, exist_ok=True)
ST = ndimage.generate_binary_structure(2, 2)


def smooth_and_mainify(mask, rel_keep=0.05):
    st = ndimage.iterate_structure(ST, 3)
    m = ndimage.binary_closing(ndimage.binary_opening(mask, structure=st), structure=st)
    lab, n = ndimage.label(m)
    if not n:
        return m
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    main = sizes.argmax() + 1
    keep = np.zeros_like(m)
    for i in range(1, n + 1):
        if sizes[i - 1] >= rel_keep * sizes[main - 1]:
            keep |= lab == i
    return keep


def hair_debris_cleanup(body, roi, max_px=1200, protect=None):
    hm = hair_mask(body[..., :3].astype(int)) & (body[..., 3] > 8)
    hm[:roi[1], :] = False; hm[roi[3]:, :] = False
    hm[:, :roi[0]] = False; hm[:, roi[2]:] = False
    if protect is not None:
        hm &= ~protect
    lab, n = ndimage.label(hm)
    deb = np.zeros_like(hm)
    for i in range(1, n + 1):
        comp = lab == i
        if comp.sum() <= max_px:
            deb |= comp
    return delete_pixels(body, deb), int(deb.sum())


def row_lerp_infill(im, hole, max_gap=50, max_delta=90):
    out = im.copy()
    opaque = im[..., 3] > 8
    for y in range(im.shape[0]):
        xs = np.where(hole[y])[0]
        if xs.size == 0:
            continue
        runs = np.split(xs, np.where(np.diff(xs) > 1)[0] + 1)
        for r in runs:
            l, rt = r[0] - 1, r[-1] + 1
            if l < 0 or rt >= im.shape[1]:
                continue
            gap = rt - l - 1
            if gap <= 0 or gap > max_gap:
                continue
            if not (opaque[y, l] and opaque[y, rt]):
                continue
            c0 = out[y, l, :3].astype(int); c1 = out[y, rt, :3].astype(int)
            if np.abs(c1 - c0).max() > max_delta:
                continue
            w = np.linspace(0, 1, gap + 2)[1:-1, None]
            out[y, l + 1:rt, :3] = (c0 * (1 - w) + c1 * w).astype(np.uint8)
            out[y, l + 1:rt, 3] = 255
    return out



def col_lerp_infill(im, hole, max_gap=70, max_delta=90):
    """Vertical analogue of row_lerp_infill (bridges holes along columns)."""
    out = im.copy()
    opaque = im[..., 3] > 8
    for x in range(im.shape[1]):
        ys = np.where(hole[:, x])[0]
        if ys.size == 0:
            continue
        runs = np.split(ys, np.where(np.diff(ys) > 1)[0] + 1)
        for r in runs:
            t, bt = r[0] - 1, r[-1] + 1
            if t < 0 or bt >= im.shape[0]:
                continue
            gap = bt - t - 1
            if gap <= 0 or gap > max_gap:
                continue
            if not (opaque[t, x] and opaque[bt, x]):
                continue
            c0 = out[t, x, :3].astype(int); c1 = out[bt, x, :3].astype(int)
            if np.abs(c1 - c0).max() > max_delta:
                continue
            w = np.linspace(0, 1, gap + 2)[1:-1, None]
            out[t + 1:bt, x, :3] = (c0 * (1 - w) + c1 * w).astype(np.uint8)
            out[t + 1:bt, x, 3] = 255
    return out


def delete_small_islands(im, max_size=40):
    a = im[..., 3] > 8
    lab, n = ndimage.label(a)
    sizes = ndimage.sum(a, lab, range(1, n + 1))
    out = im.copy()
    removed = 0
    for i in range(1, n + 1):
        if sizes[i - 1] <= max_size:
            out[lab == i] = 0
            removed += int(sizes[i - 1])
    return out, removed


def tail_mirror(im, roi, axis, close_r=6, exclude_strips=(), excl_rects=(), protect=None,
                shift=0, scale=1.0, com_limit=0.53, auto_place=False, orphan_cap=2000,
                spare_occluders=False):
    tm, alpha = extract_tail_region(im, roi=roi, close_r=close_r,
                                    exclude_strips=exclude_strips, excl_rects=excl_rects)
    gaps = row_span_fill(tm, max_gap=44) & ~tm   # occluder strips crossing the tail
    if spare_occluders:
        # spare a band around foreground occluders (cane shafts) so deletion and
        # debris cleanup never eat them; the patch still spans them via lerp
        tm_del = tm & ~ndimage.binary_dilation(gaps, ST, iterations=3)
    else:
        tm_del = tm
    filled = smooth_and_mainify(row_span_fill(tm, max_gap=44))
    patch, pos = build_patch(im, filled)
    x0, y0 = pos
    h, w = patch.shape[:2]
    nx0 = 2 * axis - (x0 + w)
    mpatch = np.ascontiguousarray(patch[:, ::-1])
    body = delete_pixels(im, tm_del)
    prot = protect
    if spare_occluders:
        prot = (ndimage.binary_dilation(gaps, ST, iterations=3) | protect) if protect is not None             else ndimage.binary_dilation(gaps, ST, iterations=3)
    body, ndeb = hair_debris_cleanup(body, roi, protect=prot)
    # any-colour orphan fragments fully inside the tail roi (outline bits etc.)
    a1 = body[..., 3] > 8
    lab, n = ndimage.label(a1)
    orphan = np.zeros_like(a1)
    for i in range(1, n + 1):
        comp = lab == i
        if comp.sum() > orphan_cap:
            continue
        ys, xs = np.where(comp)
        if (xs.min() >= roi[0] and xs.max() <= roi[2]
                and ys.min() >= roi[1] and ys.max() <= roi[3]):
            orphan |= comp
    body = delete_pixels(body, orphan)
    ndeb += int(orphan.sum())

    def compose(nx, sc):
        p = mpatch
        if sc != 1.0:
            nh, nw = max(1, round(h * sc)), max(1, round(w * sc))
            p = np.asarray(Image.fromarray(mpatch).resize((nw, nh), Image.LANCZOS))
        nx = int(round(nx)); ny = int(y0)
        out = composite_behind(body, p, (nx, ny))
        return out, p, (nx, ny)

    if not auto_place:
        out, p, place = compose(nx0 + shift, scale)
        return out, tm, place, ndeb

    # search minimal-distortion placement meeting com_x limit + root attachment
    body_a = body[..., 3] > 8
    best = None
    for sc in (1.0, 0.97, 0.94, 0.91, 0.88):
        for sh in (0, -20, -40, -60, -80, -100, -120):
            out, p, place = compose(nx0 + sh, sc)
            m = metrics(out)
            pa = p[..., 3] > 0
            ph, pw = pa.shape
            overlap = (pa & body_a[place[1]:place[1] + ph,
                                   place[0]:place[0] + pw]).sum()
            ok_com = m['com_x'] <= com_limit
            ok_att = overlap >= 1500
            score = (abs(sc - 1.0) * 100 + abs(sh) / 10.0)
            if ok_com and ok_att and (best is None or score < best[0]):
                best = (score, out, place, sc, sh, overlap, m['com_x'])
    if best is None:
        raise RuntimeError('no placement satisfies com/attachment constraints')
    _, out, place, sc, sh, overlap, comx = best
    print(f'  placement: scale={sc} shift={sh} overlap={overlap} com_x={comx}')
    return out, tm, place, ndeb


def metrics(im):
    a = im[..., 3] > 8
    comx = (np.arange(im.shape[1])[None, :] * a).sum() / a.sum()
    rows = np.where(a.any(axis=1))[0]
    cols = np.where(a.any(axis=0))[0]
    lab, n = ndimage.label(a)
    sizes = sorted(ndimage.sum(a, lab, range(1, n + 1)).tolist(), reverse=True)
    return {'com_x': round(comx / im.shape[1], 4), 'lowest_row': int(rows.max()),
            'bbox': [int(cols.min()), int(rows.min()), int(cols.max()), int(rows.max())],
            'alpha_components': n, 'largest_sizes': [int(s) for s in sizes[:4]]}


# ---------------------------------------------------------------- per-asset
def a01():
    im = np.array(Image.open(MASTERS / 'furina_v2_a01_stand_neutral_front.png'))
    roi = (60, 900, 430, 1470)
    strips = [((255, 1042), (345, 1042), 50), ((300, 1090), (302, 1185), 22),
              ((302, 1185), (312, 1345), 13), ((312, 1345), (322, 1432), 11),
              ((316, 1432), (320, 1465), 13)]
    protect = np.zeros(im.shape[:2], bool)
    for s in strips:
        protect |= line_strip_mask(im.shape[:2], s[0], s[1], s[2] + 10)
    out, tm, pos, ndeb = tail_mirror(im, roi, axis=512, exclude_strips=strips,
                                     protect=protect)
    out, isl = delete_small_islands(out, max_size=40)
    return out, dict(tail_px=int(tm.sum()), mirror_pos=list(pos),
                     debris_px=ndeb, island_px=isl)


def a05():
    im = np.array(Image.open(MASTERS / 'furina_v2_a05_stand_confident_proud.png'))
    im, isl0 = delete_small_islands(im, max_size=500)   # detached tail wisp
    roi = (100, 850, 480, 1420)
    # pure mirror placement: pose is right-leaning so com_x exceeds 0.50±0.03
    # whatever the tail side; deviation recorded per GEOMETRY spec §5.2.
    out, tm, pos, ndeb = tail_mirror(im, roi, axis=512)
    out, isl = delete_small_islands(out, max_size=40)
    return out, dict(wisp_island_px=isl0, tail_px=int(tm.sum()),
                     mirror_pos=list(pos), debris_px=ndeb, island_px=isl)


def a16():
    im = np.array(Image.open(MASTERS / 'furina_v2_a16_work_focused.png'))
    rgb = im[..., :3].astype(int)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = (r + g + b) / 3
    # 1) chair: wood core only (warm grow invades skin shadows), zone-limited
    zone = np.zeros(im.shape[:2], bool); zone[1140:1475, 465:720] = True
    wood = (r > g) & (g > b) & (r - b >= 30) & (r - g <= 34) & (r >= 70) & (r < 208)
    wood &= zone
    chair_del = ndimage.binary_dilation(wood, np.ones((11, 11))) & (im[..., 3] > 8)
    im = delete_pixels(im, chair_del)
    # 2) cane: three head rectangles + shaft strips.  Protect her glove/sleeve and
    #    the coattail (navy = b>r, g-r<60); skip infill inside the grip zone so
    #    finger gaps stay transparent instead of laddering.
    gold = (r > g) & (g > b) & (r - b >= 45) & (r >= 120)
    gem = (b > r + 40) & (b >= 140) & (bright >= 90)
    orb = (bright >= 185) & (np.abs(r - b) <= 45) & (np.abs(g - r) <= 45)
    navy = (b > r) & (g - r < 60) & (bright < 160)
    rects = [((692, 805), (856, 1040)),   # finial + white helm + collar
             ((682, 778), (975, 1082)),   # collar behind glove fingers
             ((650, 762), (1076, 1214))]  # guard + teardrop gems
    hz = np.zeros(im.shape[:2], bool)
    for (xa, xb), (ya, yb) in rects:
        hz[ya:yb, xa:xb] = True
    # above the glove the helm is over bg/hair only: delete its dark outline,
    # gold and white body while sparing pale-blue hair and attached highlights
    hz_upper = np.zeros_like(hz); hz_upper[856:978, 694:815] = True
    r_, g_, b_ = r, g, b
    hairblue = (b_ > r_ + 10) & (g_ >= r_ - 5) & (bright >= 120)
    white0 = (bright >= 185) & (np.abs(r_ - b_) <= 14) & (np.abs(g_ - r_) <= 14)
    white_prot = white0 & ndimage.binary_dilation(hairblue, ST, iterations=3)
    helmkill = ((bright < 175) & ~hairblue) | (gold & hz_upper) | gem | (white0 & ~white_prot)
    head = ((gold | gem | orb) & hz & ~hz_upper) | (helmkill & hz_upper & (im[..., 3] > 8))
    glove_band = np.zeros_like(hz); glove_band[962:, :] = True
    head = ndimage.binary_dilation(head, ST, iterations=2) & hz & ~(navy & glove_band)
    strips = [((672, 1200), (628, 1265), 22), ((628, 1265), (590, 1330), 18),
              ((590, 1330), (568, 1390), 16), ((568, 1390), (550, 1462), 17)]
    cane = head.copy()
    for s in strips:
        cane |= line_strip_mask(im.shape[:2], s[0], s[1], s[2])
    cane &= im[..., 3] > 8
    im = delete_pixels(im, cane)
    # column lerp only below the helm (bridging there drags hair into streaks)
    lower = np.zeros(im.shape[:2], bool); lower[1040:, :] = True
    im = col_lerp_infill(im, cane & lower)
    # rebuild a clean closed fist from the largest glove mass in the grip zone
    GR = (slice(950, 1115), slice(620, 800))
    gzone = np.zeros(im.shape[:2], bool); gzone[GR] = True
    ga = (im[..., 3] > 8) & gzone
    lab, n = ndimage.label(ga)
    if n:
        sizes = ndimage.sum(ga, lab, range(1, n + 1))
        palm = lab == (sizes.argmax() + 1)
        fist = ndimage.binary_fill_holes(ndimage.binary_dilation(palm, ST, iterations=3)) & gzone
        rgbv = im[..., :3].astype(int)
        rr, gg, bb = rgbv[..., 0][palm], rgbv[..., 1][palm], rgbv[..., 2][palm]
        fill_col = np.array([int(np.median(rr)), int(np.median(gg)), int(np.median(bb))])
        add = fist & ~palm
        im[add, :3] = fill_col
        im[add, 3] = 255
        lost = gzone & ~fist & (im[..., 3] > 0) & ~palm
        im[lost] = 0
    # thin cane remnants (shaft edges / tip) inside the corridor: thickness test
    cor = np.zeros(im.shape[:2], bool); cor[1150:1475, 540:700] = True
    ca = (im[..., 3] > 8) & cor
    lab3, n3 = ndimage.label(ca)
    dist = ndimage.distance_transform_edt(ca)
    thin = np.zeros_like(ca)
    for i in range(1, n3 + 1):
        comp = lab3 == i
        if dist[comp].max() <= 16:
            thin |= comp
    im = delete_pixels(im, thin)
    infill_px = int(cane.sum())
    # 3) tail mirror: shift left for com band + coattail root attachment
    roi = (120, 1080, 400, 1470)
    out, tm, pos, ndeb = tail_mirror(im, roi, axis=512, auto_place=True,
                                     com_limit=0.53, orphan_cap=20000)
    # after tail removal the old curl outline is isolated: thin-line cleanup
    cor2 = np.zeros(im.shape[:2], bool); cor2[1150:1475, 140:395] = True
    ca2 = (out[..., 3] > 8) & cor2
    lab4, n4 = ndimage.label(ca2)
    dist2 = ndimage.distance_transform_edt(ca2)
    thin2 = np.zeros_like(ca2)
    for i in range(1, n4 + 1):
        comp = lab4 == i
        if dist2[comp].max() <= 16:
            thin2 |= comp
    out = delete_pixels(out, thin2)
    out, isl = delete_small_islands(out, max_size=100)
    return out, dict(chair_px=int(chair_del.sum()), cane_px=int(cane.sum()), infill_px=infill_px,
                     tail_px=int(tm.sum()), mirror_pos=list(pos),
                     debris_px=ndeb, island_px=isl)


ASSETS = {'a01': a01, 'a05': a05, 'a16': a16}

BATCH = {
    'a03': dict(roi=(60, 850, 440, 1470)),
    'a04': dict(roi=(60, 850, 440, 1470)),
    'a06': dict(roi=(60, 850, 440, 1470)),
    'a07': dict(roi=(60, 850, 440, 1470)),
    'a08': dict(roi=(60, 850, 440, 1470)),
    'a09': dict(roi=(60, 850, 440, 1470)),
    'a10': dict(roi=(60, 850, 440, 1470)),
    'a13': dict(roi=(60, 850, 440, 1470)),
    'a14': dict(roi=(60, 850, 440, 1470)),
    'a18': dict(roi=(60, 850, 440, 1470)),
    'a19': dict(roi=(55, 1100, 400, 1455), excl_rects=[(295, 1270, 460, 1470)]),
}
NAMES = {
    'a03': 'stand_neutral_slight_right', 'a04': 'stand_relaxed_idle',
    'a06': 'stand_gentle_happy', 'a07': 'stand_annoyed', 'a08': 'stand_embarrassed',
    'a09': 'stand_curious_leaning', 'a10': 'stand_sleepy', 'a13': 'pet_response',
    'a14': 'poke_response', 'a18': 'stand_quiet_reflective', 'a19': 'eating',
}


def batch(only=None):
    from night03_tail_lib import extract_tail_region
    report = {}
    for key, cfg in BATCH.items():
        if only and key not in only:
            continue
        im = np.array(Image.open(MASTERS / f'furina_v2_{key}_{NAMES[key]}.png'))
        im, isl0 = delete_small_islands(im, max_size=500)  # specks/droplets/FX
        out, tm, pos, ndeb = tail_mirror(
            im, cfg['roi'], axis=512, spare_occluders=True,
            excl_rects=cfg.get('excl_rects', ()))
        out, isl = delete_small_islands(out, max_size=40)
        name = OUT / f'furina_v2_{key}_repair.png'
        Image.fromarray(out).save(name)
        m = metrics(out)
        report[key] = {'file': str(name.relative_to(ROOT)),
                       'info': dict(defect_island_px=isl0, tail_px=int(tm.sum()),
                                    mirror_pos=list(pos), debris_px=ndeb,
                                    island_px=isl), 'metrics': m}
        print(key, json.dumps(report[key]['info']), json.dumps(m))
    return report


def main():
    report = {}
    for key, fn in ASSETS.items():
        out, info = fn()
        name = OUT / f'furina_v2_{key}_repair.png'
        Image.fromarray(out).save(name)
        m = metrics(out)
        report[key] = {'file': str(name.relative_to(ROOT)), 'info': info, 'metrics': m}
        print(key, json.dumps(info), json.dumps(m))
    (OUT / '_pilot_state.json').write_text(json.dumps(report, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
