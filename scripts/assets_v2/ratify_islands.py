import numpy as np, json, os
from collections import deque
from PIL import Image
ROOT = 'data/assets_v2'
m = json.load(open(ROOT + '/metadata/manifest_v2.json', encoding='utf-8'))
res = {}
for e in m['entries']:
    aid = e['alpha_id']
    a = np.array(Image.open(e['master_file'].replace('\\', '/')).convert('RGBA'))
    op = a[..., 3] >= 128
    H, W = op.shape
    seen = np.zeros((H, W), bool)
    comps = []
    ys, xs = np.nonzero(op)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        dq = deque([(y0, x0)])
        seen[y0, x0] = True
        n = 0
        minx = maxx = x0; miny = maxy = y0
        while dq:
            y, x = dq.popleft(); n += 1
            minx = min(minx, x); maxx = max(maxx, x); miny = min(miny, y); maxy = max(maxy, y)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < H and 0 <= nx < W and op[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True; dq.append((ny, nx))
        comps.append((n, minx, miny, maxx, maxy))
    comps.sort(reverse=True)
    islands = [c for c in comps[1:] if c[0] >= 4]
    res[aid] = {'components': len(comps), 'main_px': int(comps[0][0]),
                'islands': [{'px': int(c[0]), 'bbox': [int(c[1]), int(c[2]), int(c[3]), int(c[4])]} for c in islands[:8]]}
    print(aid, 'comps:', len(comps), 'islands:', [(c['px'], c['bbox']) for c in res[aid]['islands']][:5])
json.dump(res, open(ROOT + '/review/ratification_islands.json', 'w'), indent=1)
