import numpy as np, json
from collections import deque
from PIL import Image
ROOT = 'data/assets_v2'
m = json.load(open(ROOT + '/metadata/manifest_v2.json', encoding='utf-8'))
for aid in ['a02', 'a20', 'a17', 'a11', 'a01', 'a13', 'a16', 'a19']:
    e = [x for x in m['entries'] if x['alpha_id'] == aid][0]
    a = np.array(Image.open(e['master_file'].replace('\\', '/')).convert('RGBA'))
    alpha = a[..., 3].astype(int)
    H, W = alpha.shape
    trans = alpha == 0
    vis = np.zeros((H, W), bool)
    dq = deque()
    for x in range(W):
        for y in (0, H - 1):
            if trans[y, x] and not vis[y, x]:
                vis[y, x] = True; dq.append((y, x))
    for y in range(H):
        for x in (0, W - 1):
            if trans[y, x] and not vis[y, x]:
                vis[y, x] = True; dq.append((y, x))
    while dq:
        y, x = dq.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W and not vis[ny, nx] and trans[ny, nx]:
                vis[ny, nx] = True; dq.append((ny, nx))
    hm = trans & ~vis
    seen = np.zeros((H, W), bool)
    comps = []
    for y, x in zip(*np.nonzero(hm)):
        if seen[y, x]:
            continue
        dq = deque([(y, x)]); seen[y, x] = True
        n = 0; bx = [x, x, y, y]
        while dq:
            cy, cx = dq.popleft(); n += 1
            bx = [min(bx[0], cx), max(bx[1], cx), min(bx[2], cy), max(bx[3], cy)]
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < H and 0 <= nx < W and hm[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True; dq.append((ny, nx))
        comps.append((n, bx))
    comps.sort(reverse=True)
    print(aid, 'holes:', [(c[0], c[1]) for c in comps[:6]])
