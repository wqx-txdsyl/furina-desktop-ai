"""NIGHT-02: per-foot contact, near-duplicate check, master<->raw correspondence (read-only)."""
import json, os, hashlib
import numpy as np
from PIL import Image

ROOT = 'data/assets_v2'
m = json.load(open(os.path.join(ROOT, 'metadata', 'manifest_v2.json'), encoding='utf-8'))

def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

rows = {}
hashes = {}
for e in m['entries']:
    aid = e['alpha_id']
    mf = e['master_file'].replace('\\', '/')
    hashes[aid] = md5(mf)
    a = np.array(Image.open(mf).convert('RGBA'))
    alpha = a[..., 3]
    opaque = alpha >= 250
    # per-column bottom
    H, W = alpha.shape
    colmax = np.full(W, -1)
    for x in range(W):
        col = np.nonzero(opaque[:, x])[0]
        if col.size:
            colmax[x] = col[-1]
    # foot contact: columns with bottom >= 1462 (within 6px of 1468 line)
    contact_cols = np.nonzero(colmax >= 1462)[0]
    segs = []
    if contact_cols.size:
        start = prev = int(contact_cols[0])
        for x in contact_cols[1:]:
            x = int(x)
            if x - prev > 12:
                segs.append([start, prev]); start = x
            prev = x
        segs.append([start, prev])
    seg_info = []
    for s in segs:
        sub = colmax[s[0]:s[1] + 1]
        seg_info.append({'x_range': s, 'lowest_y': int(sub.max()), 'width': s[1] - s[0] + 1})
    # raw correspondence: key raw (non-magenta) downscaled, IoU vs master alpha mask
    raw = os.path.join(ROOT, 'raw', e['source_generation']['raw_file'])
    rim = Image.open(raw).convert('RGBA').resize((1024, 1536), Image.LANCZOS)
    ra = np.array(rim)
    rr, rg, rb = ra[..., 0].astype(int), ra[..., 1].astype(int), ra[..., 2].astype(int)
    rmag = (rr > 160) & (rb > 160) & (rg < 130)
    rmask = ~rmag
    mmask = alpha > 128
    inter = (rmask & mmask).sum(); union = (rmask | mmask).sum()
    iou = float(inter) / float(union) if union else 0.0
    rows[aid] = {'md5': hashes[aid], 'contact_segments': seg_info, 'raw_iou': round(iou, 4)}

print(json.dumps(rows, indent=1))
with open(os.path.join(ROOT, 'review', 'ratification_contact_raw.json'), 'w', encoding='utf-8') as f:
    json.dump(rows, f, indent=1)

# duplicate detection among masters
ids = sorted(hashes)
print('\nmd5 distinct:', len(set(hashes.values())), 'of', len(hashes))
# near-duplicate: bbox-normalized grayscale diff
masks = {}
for aid in ids:
    im = Image.open(os.path.join(ROOT, 'masters', f'furina_v2_{aid}_' + '_'.join(
        os.listdir(os.path.join(ROOT, 'masters')))[0:0]) if False else
        [os.path.join(ROOT, 'masters', f) for f in os.listdir(os.path.join(ROOT, 'masters'))
         if f.startswith('furina_v2_' + aid + '_') and f.endswith('.png')][0]).convert('RGBA')
    masks[aid] = im
import itertools
near = []
for a1, a2 in itertools.combinations(ids, 2):
    if a1[0:3] != a2[0:3]:
        pass
    i1, i2 = masks[a1], masks[a2]
    s1 = np.array(i1.resize((256, 384), Image.LANCZOS)).astype(int)
    s2 = np.array(i2.resize((256, 384), Image.LANCZOS)).astype(int)
    d = np.abs(s1 - s2).mean()
    if d < 12:
        near.append((a1, a2, round(float(d), 2)))
print('near-duplicate pairs (mean|diff|<12):', near if near else 'none')
