import json
import numpy as np
from PIL import Image
m = json.load(open('data/assets_v2/metadata/manifest_v2.json', encoding='utf-8'))
bad = []
for e in m['entries']:
    aid = e['alpha_id']
    a = np.array(Image.open(e['master_file'].replace('\\', '/')).convert('RGBA'))
    op = a[..., 3] >= 250
    ys, xs = np.nonzero(op)
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    w, h = x1 - x0 + 1, y1 - y0 + 1
    cp = e['geometry'].get('content_px')
    if cp and [x0, y0, w, h] != cp:
        bad.append((aid, 'measured', [x0, y0, w, h], 'manifest', cp))
print('bbox mismatches:', bad if bad else 'none (all content_px match measured [x,y,w,h])')
