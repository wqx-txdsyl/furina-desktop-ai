"""NIGHT-03 Patch 1 — semantic-layering repair library (fresh implementation).

Design principles (vs round-1 which ate costume/props):
  * tail = geometric corridor ∩ alpha minus protective layers: no colour test on
    the tail INTERIOR, so dark curl strokes / outline / AA edges are captured
    wholesale (round-1 kept the outline ghost and dropped the tip).
  * purple-tint tests are used ONLY to *identify* the tail component and never
    to *delete* costume (each tinted costume region is excluded geometrically).
  * protections are per-asset geometric + thickness based (solid dark = body),
    never pure colour thresholds over the whole canvas.
  * the mirrored patch is composited BEHIND the master body and body pixels
    always win (z-order preserved; body byte-identical outside edit masks).
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

ST = ndimage.generate_binary_structure(2, 2)


def poly_mask(shape, pts):
    """Rasterize a closed polygon (points in canvas coords) into a bool mask."""
    h, w = shape[:2]
    m = np.zeros((h, w), bool)
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        if x1 == x0:
            step = 1 if y1 > y0 else -1
            ys = range(y0, y1 + step, step)
            xs = [x0] * len(list(ys))
        else:
            k = int(abs(y1 - y0) + 1)
            ys = np.linspace(y0, y1, k).astype(int)
            xs = np.linspace(x0, x1, k).astype(int)
        for xx, yy in zip(xs, ys):
            if 0 <= xx < w and 0 <= yy < h:
                m[yy, xx] = True
    # scanline fill
    filled = np.zeros_like(m)
    for y in range(h):
        xs = np.where(m[y])[0]
        if xs.size >= 2:
            filled[y, xs.min():xs.max() + 1] = True
    return filled


def rect_mask(shape, x0, y0, x1, y1):
    m = np.zeros(shape[:2], bool)
    m[int(y0):int(y1), int(x0):int(x1)] = True
    return m


def strips_mask(shape, segs):
    """segs: (p0, p1, half_width) => rotated band masks."""
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    m = np.zeros(shape[:2], bool)
    for (x0, y0), (x1, y1), hw in segs:
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy or 1
        t = np.clip(((xx - x0) * dx + (yy - y0) * dy) / L2, 0, 1)
        px, py = x0 + t * dx, y0 + t * dy
        m |= (xx - px) ** 2 + (yy - py) ** 2 <= hw * hw
    return m


def dil(mask, it=2, st=None):
    return ndimage.binary_dilation(mask, structure=st or ST, iterations=it)


def fill_holes(mask):
    return ndimage.binary_fill_holes(mask)


def label_comps(mask, min_px=1):
    lab, n = ndimage.label(mask, structure=ST)
    out = []
    for i in range(1, n + 1):
        c = lab == i
        if c.sum() >= min_px:
            ys, xs = np.where(c)
            out.append((c, int(c.sum()), int(xs.min()), int(ys.min()),
                        int(xs.max()), int(ys.max())))
    return out


def dims(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return r, g, b, (r + g + b) / 3.0


def tint_tail(rgb):
    """Pale-blue tail/hair tint: strong blue separation, medium-high brightness."""
    r, g, b, bright = dims(rgb)
    pale = (b - r >= 18) & (bright >= 130) & (g >= r - 10)
    shadow = (g - r >= 25) & (b - r >= 35) & (bright >= 110) & (b > g)
    return pale | shadow


def solid_dark(im, thr=110, min_thick=7):
    """Solid dark masses (arm/glove/coat/cane dark): dark comps with EDT-max>=min_thick."""
    r, g, b, bright = dims(im[..., :3].astype(int))
    dark = (bright < thr) & (im[..., 3] > 8)
    lab, n = ndimage.label(dark, structure=ST)
    dist = ndimage.distance_transform_edt(dark)
    out = np.zeros_like(dark)
    for i in range(1, n + 1):
        c = lab == i
        if c.sum() >= 12 and float(dist[c].max()) >= min_thick:
            out |= c
    return out


def thin_dark(im, thr=110, max_thick=4):
    """Thin dark lines (tail outline / curls) but NOT solid shapes."""
    r, g, b, bright = dims(im[..., :3].astype(int))
    dark = (bright < thr) & (im[..., 3] > 8)
    lab, n = ndimage.label(dark, structure=ST)
    dist = ndimage.distance_transform_edt(dark)
    out = np.zeros_like(dark)
    for i in range(1, n + 1):
        c = lab == i
        if c.sum() >= 3 and float(dist[c].max()) <= max_thick:
            out |= c
    return out


def composite_behind(body, patch, pos):
    """Draw patch BEHIND body-foreground: opaque body pixels win bit-exactly."""
    out = body.copy()
    px, py = pos
    ph, pw = patch.shape[:2]
    if px < 0 or py < 0 or px + pw > out.shape[1] or py + ph > out.shape[0]:
        raise ValueError(f'patch placement {pos} out of canvas')
    reg = out[py:py + ph, px:px + pw]
    bg = np.zeros(patch.shape[:2], bool)
    fg = body[..., 3] > 8
    fg = fg[py:py + ph, px:px + pw]
    ra = reg[..., 3:4].astype(np.float32) / 255.0
    pa = patch[..., 3:4].astype(np.float32) / 255.0
    # body wins bit-exactly wherever it has any alpha; tail fills only the empty/
    # semi pixels that do NOT belong to the body (strict z-order preservation)
    fg3 = fg[..., None]
    under_a = pa * (1 - ra)
    out_a = np.where(fg3, ra, ra + under_a)
    safe = np.where(out_a == 0, 1, out_a)
    under = (reg[..., :3].astype(np.float32) * ra
             + patch[..., :3].astype(np.float32) * pa * (1 - ra)) / safe
    col = np.where(fg3, reg[..., :3], under)
    both0 = (reg[..., 3:4] == 0) & (patch[..., 3:4] == 0)
    col = np.where(both0, reg[..., :3], col)
    out_a = np.where(both0, 0.0, out_a)
    out[py:py + ph, px:px + pw, :3] = col.astype(np.uint8)
    out[py:py + ph, px:px + pw, 3] = (np.clip(out_a[..., 0], 0, 1) * 255).astype(np.uint8)
    return out
