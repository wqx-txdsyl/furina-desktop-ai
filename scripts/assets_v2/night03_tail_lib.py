"""NIGHT-03 local tail repair library (write-behind mirror method) — v3."""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def hair_mask(rgb: np.ndarray) -> np.ndarray:
    """Two-tier pale-hair test: pale tones, or blue-shadow hair tones (g-r channel separates
    hair shadow from cane-shaft / coattail navy)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = (r + g + b) / 3
    pale = (b >= r) & (b - r >= 8) & (bright >= 165) & (g >= r)
    shadow = (g - r >= 30) & (b - r >= 40) & (bright >= 120) & (b > g)
    white_border = (np.abs(b - r) <= 14) & (np.abs(g - r) <= 14) & (bright >= 225)
    return pale | shadow | white_border


def line_strip_mask(shape, p0, p1, half_width: float) -> np.ndarray:
    """Mask of pixels within half_width of segment p0-p1."""
    h, w = shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    t = ((xx - x0) * dx + (yy - y0) * dy) / max(L2, 1)
    t = np.clip(t, 0, 1)
    px, py = x0 + t * dx, y0 + t * dy
    d2 = (xx - px) ** 2 + (yy - py) ** 2
    return d2 <= half_width * half_width


def extract_tail_region(im, roi, close_r=6, min_comp=400, exclude_strips=(), excl_rects=()):
    alpha = im[..., 3] > 8
    hm = hair_mask(im[..., :3].astype(int)) & alpha
    m = np.zeros_like(hm)
    x0, y0, x1, y1 = roi
    m[y0:y1, x0:x1] = hm[y0:y1, x0:x1]
    for ex0, ey0, ex1, ey1 in excl_rects:
        m[ey0:ey1, ex0:ex1] = False
    for strip in exclude_strips:
        m &= ~line_strip_mask(m.shape, strip[0], strip[1], strip[2])
    st = ndimage.iterate_structure(ndimage.generate_binary_structure(2, 2), close_r)
    m = ndimage.binary_closing(m, structure=st)
    lab, n = ndimage.label(m)
    if n:
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        keep = np.zeros_like(m)
        for i in range(1, n + 1):
            if sizes[i - 1] >= min_comp:
                keep |= lab == i
        m = keep & alpha
    return m, alpha


def row_span_fill(tm, max_gap=40):
    filled = tm.copy()
    for y in range(tm.shape[0]):
        xs = np.where(tm[y])[0]
        if xs.size < 2:
            continue
        runs = np.split(xs, np.where(np.diff(xs) > 1)[0] + 1)
        for i in range(len(runs) - 1):
            l, r = runs[i][-1], runs[i + 1][0]
            if 0 < r - l - 1 <= max_gap:
                filled[y, l + 1:r] = True
    return filled


def build_patch(im, mask, max_fill_gap=40, max_lerp_delta=70):
    ys, xs = np.where(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    sub = im[y0:y1, x0:x1]
    m = mask[y0:y1, x0:x1]
    patch = np.zeros((*m.shape, 4), np.uint8)
    patch[..., :3] = np.where(m[..., None], sub[..., :3], 0)
    patch[..., 3] = np.where(m, sub[..., 3], 0)
    for yy in range(m.shape[0]):
        row = np.where(m[yy])[0]
        if row.size == 0:
            continue
        runs = np.split(row, np.where(np.diff(row) > 1)[0] + 1)
        for i in range(len(runs) - 1):
            l, r = runs[i][-1], runs[i + 1][0]
            gap = r - l - 1
            if 0 < gap <= max_fill_gap:
                c0 = patch[yy, l, :3].astype(int)
                c1 = patch[yy, r, :3].astype(int)
                if np.abs(c1 - c0).max() > max_lerp_delta:
                    continue  # edges belong to different objects; leave gap transparent
                w = np.linspace(0.0, 1.0, gap + 2)[1:-1, None]
                patch[yy, l + 1:r, :3] = (c0 * (1 - w) + c1 * w).astype(np.uint8)
                patch[yy, l + 1:r, 3] = sub[yy, l + 1:r, 3]
    return patch, (int(x0), int(y0))


def composite_behind(body, patch, pos):
    out = body.copy()
    px, py = pos
    ph, pw = patch.shape[:2]
    reg = out[py:py + ph, px:px + pw]
    ra = reg[..., 3:4].astype(float) / 255.0
    pa = patch[..., 3:4].astype(float) / 255.0
    outa = ra + pa * (1 - ra)
    safe = np.where(outa == 0, 1, outa)
    under = (reg[..., :3].astype(float) * ra + patch[..., :3].astype(float) * pa * (1 - ra)) / safe
    col = np.where(ra >= 0.999, reg[..., :3], under)
    out[py:py + ph, px:px + pw, :3] = col.astype(np.uint8)
    out[py:py + ph, px:px + pw, 3] = (outa[..., 0] * 255).clip(0, 255).astype(np.uint8)
    return out


def delete_pixels(im, mask):
    out = im.copy()
    out[mask] = 0
    return out


def floating_debris_mask(before, after, roi, max_size=900):
    """Opaque components present before but disconnected/smaller after deletion inside ROI."""
    a0 = before[..., 3] > 8
    a1 = after[..., 3] > 8
    x0, y0, x1, y1 = roi
    debris = np.zeros_like(a0)
    lab, n = ndimage.label(a1)
    for i in range(1, n + 1):
        comp = lab == i
        ys, xs = np.where(comp)
        if ys.min() < y0 or xs.max() < x0 or xs.min() > x1 or ys.max() > y1:
            continue  # outside ROI entirely
        if comp.sum() <= max_size and not comp[y0:y1, x0:x1].any():
            continue
        if comp.sum() <= max_size:
            # small component fully inside ROI bbox -> likely debris if it was attached before
            if (comp & a0 & ~(a1 & ~comp)).sum() >= 0:  # exists in ROI region of before
                debris |= comp
    return debris
