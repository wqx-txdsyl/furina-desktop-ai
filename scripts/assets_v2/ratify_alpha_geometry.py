"""NIGHT-02 independent ratification — alpha & geometry diagnostics (read-only analysis).

Outputs:
  data/assets_v2/review/ratification_measurements.json
  data/assets_v2/review/matte_sheets/<id>_matte.png  (4-bg composite + fringe/holes panel)
No master/raw/base file is modified.
"""
import json, os
import numpy as np
from PIL import Image, ImageDraw

ROOT = 'data/assets_v2'
OUT_MEAS = os.path.join(ROOT, 'review', 'ratification_measurements.json')
MATTE_DIR = os.path.join(ROOT, 'review', 'matte_sheets')
os.makedirs(MATTE_DIR, exist_ok=True)

m = json.load(open(os.path.join(ROOT, 'metadata', 'manifest_v2.json'), encoding='utf-8'))

def measure(path):
    im = Image.open(path)
    info = {'format': im.format, 'mode': im.mode, 'size': im.size}
    if im.mode != 'RGBA':
        im = im.convert('RGBA')
    a = np.array(im)
    alpha = a[..., 3].astype(np.int32)
    rgb = a[..., :3].astype(np.int32)

    opaque = alpha >= 250
    semi = (alpha > 0) & (alpha < 250)
    trans = alpha == 0

    ys, xs = np.nonzero(opaque)
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None

    cov = float((alpha > 0).mean())
    info['alpha_coverage_frac'] = round(cov, 4)
    info['opaque_bbox'] = bbox
    info['semi_px'] = int(semi.sum())
    info['opaque_px'] = int(opaque.sum())

    # --- holes: fully transparent pixels NOT reachable from image border through transparent area
    holes = 0
    holes_px = 0
    if bbox:
        from collections import deque
        H, W = alpha.shape
        visited = np.zeros((H, W), bool)
        dq = deque()
        for x in range(W):
            for y in (0, H - 1):
                if trans[y, x] and not visited[y, x]:
                    visited[y, x] = True; dq.append((y, x))
        for y in range(H):
            for x in (0, W - 1):
                if trans[y, x] and not visited[y, x]:
                    visited[y, x] = True; dq.append((y, x))
        while dq:
            y, x = dq.popleft()
            for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)):
                ny, nx = y+dy, x+dx
                if 0 <= ny < H and 0 <= nx < W and not visited[ny, nx] and trans[ny, nx]:
                    visited[ny, nx] = True; dq.append((ny, nx))
        hole_mask = trans & ~visited
        if hole_mask.any():
            # connected components of holes
            seen = np.zeros((H, W), bool)
            for y, x in zip(*np.nonzero(hole_mask)):
                if seen[y, x]: continue
                holes += 1
                dq = deque([(y, x)]); seen[y, x] = True
                n = 0
                while dq:
                    cy, cx = dq.popleft(); n += 1
                    for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)):
                        ny, nx = cy+dy, cx+dx
                        if 0 <= ny < H and 0 <= nx < W and hole_mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True; dq.append((ny, nx))
                holes_px += n
    info['enclosed_holes'] = holes
    info['enclosed_hole_px'] = holes_px

    # --- magenta fringe: near-#FF00FF pixels with alpha>0
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mag = (r > 180) & (b > 180) & (g < 110) & (alpha > 0)
    info['magenta_like_px'] = int(mag.sum())
    # pinkish semi-transparent edge pixels (hue toward magenta/red) among semi pixels
    if semi.any():
        sr, sg, sb = r[semi], g[semi], b[semi]
        pinkish = (sr > sb) & (sb > sg) & ((sr - sg) > 40)
        info['semi_pinkish_edge_px'] = int(pinkish.sum())
        info['semi_mean_rgb'] = [round(float(sr.mean()),1), round(float(sg.mean()),1), round(float(sb.mean()),1)]
    else:
        info['semi_pinkish_edge_px'] = 0
    # corners: alpha coverage in 24px corner boxes
    corners = {}
    H, W = alpha.shape
    for name, sl in {'tl': (slice(0,24),slice(0,24)), 'tr': (slice(0,24),slice(W-24,W)),
                     'bl': (slice(H-24,H),slice(0,24)), 'br': (slice(H-24,H),slice(W-24,W))}.items():
        corners[name] = int((alpha[sl] > 0).sum())
    info['corner_px'] = corners

    # --- edge alpha stats: alpha histogram of pixels adjacent to transparent area
    er = np.zeros((H, W), bool)
    er[1:, :] |= trans[1:, :]; er[:-1, :] |= trans[:-1, :]
    er[:, 1:] |= trans[:, 1:]; er[:, :-1] |= trans[:, :-1]
    edge = er & (alpha > 0)
    ea = alpha[edge]
    if ea.size:
        info['edge_px'] = int(ea.size)
        info['edge_alpha_lt128_frac'] = round(float((ea < 128).mean()), 4)
        info['edge_alpha_gt240_frac'] = round(float((ea > 240).mean()), 4)

    # --- geometry: baseline contact
    G = 1468
    if bbox:
        x0, y0, x1, y1 = bbox
        info['content_bbox'] = bbox
        info['height_frac'] = round((y1 - y0 + 1) / 1536, 4)
        info['width_frac'] = round((x1 - x0 + 1) / 1024, 4)
        # center of mass x over opaque
        comx = float((np.nonzero(opaque)[1] * alpha[opaque]).sum() / alpha[opaque].sum())
        info['com_x_frac'] = round(comx / 1024, 4)
        # bottom row profile: bottom-most 3 rows' opaque x ranges
        rows = []
        for yy in range(max(y0, y1 - 2), y1 + 1):
            xr = np.nonzero(opaque[yy])[0]
            rows.append([int(yy), int(xr.min()), int(xr.max()), int(xr.size)] if xr.size else [int(yy)])
        info['bottom_rows'] = rows
        # sole contact: lowest opaque row's x segments
        lowest = np.nonzero(opaque[y1])[0]
        segs = []
        if lowest.size:
            start = prev = int(lowest[0])
            for x in lowest[1:]:
                x = int(x)
                if x - prev > 4:
                    segs.append([start, prev]); start = x
                prev = x
            segs.append([start, prev])
        info['lowest_row_segments'] = segs
        info['lowest_y'] = int(y1)
        info['baseline_delta_px'] = int(y1 - G)
        # head anchor approx: topmost 12% of content width center
        head_rows = opaque[y0:y0 + int(0.10 * (y1 - y0))]
        hy, hx = np.nonzero(head_rows)
        info['top10pct_center_x_frac'] = round(float(hx.mean() + 0) / 1024, 4) if hx.size else None
    return info

results = {}
for e in m['entries']:
    aid = e['alpha_id']
    mf = e['master_file'].replace('\\', '/')
    results[aid] = measure(mf)
    print(aid, json.dumps(results[aid]))

with open(OUT_MEAS, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=1)
print('saved', OUT_MEAS)

# --- matte diagnostic sheets: 4 backgrounds side by side, downscaled
names = ['white', 'black', 'gray50', 'checker']
for e in m['entries']:
    aid = e['alpha_id']
    mf = e['master_file'].replace('\\', '/')
    im = Image.open(mf).convert('RGBA')
    tile_w, tile_h = 340, 510
    small = im.resize((tile_w, tile_h), Image.LANCZOS)
    sheet = Image.new('RGB', (tile_w * 4 + 50, tile_h + 30), (128, 128, 128))
    d = ImageDraw.Draw(sheet)
    for i, name in enumerate(names):
        bg = Image.new('RGB', (tile_w, tile_h), (255, 255, 255) if name == 'white' else
                       (0, 0, 0) if name == 'black' else (128, 128, 128))
        if name == 'checker':
            bg = Image.new('RGB', (tile_w, tile_h), (255, 255, 255))
            dd = ImageDraw.Draw(bg)
            for yy in range(0, tile_h, 20):
                for xx in range(0, tile_w, 20):
                    if (xx // 20 + yy // 20) % 2 == 0:
                        dd.rectangle([xx, yy, xx + 19, yy + 19], fill=(180, 180, 180))
        bg.paste(small, (0, 0), small)
        sheet.paste(bg, (i * (tile_w + 10) + 5, 25))
        d.text((i * (tile_w + 10) + 8, 5), f"{aid} {name}", fill=(0, 0, 0))
    sheet.save(os.path.join(MATTE_DIR, f'{aid}_matte.png'))
print('matte sheets saved to', MATTE_DIR)
