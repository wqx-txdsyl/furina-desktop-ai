"""NIGHT-02: thigh-strap zoom sheet per master (full-res crops)."""
import json, os
from PIL import Image, ImageDraw

ROOT = 'data/assets_v2'
OUT = os.path.join(ROOT, 'review', 'ratification_lowerbody_sheets')
m = json.load(open(os.path.join(ROOT, 'metadata', 'manifest_v2.json'), encoding='utf-8'))
entries = sorted(m['entries'], key=lambda e: e['alpha_id'])

# thigh region crops per asset (sitting assets use different y)
CROPS = {}
for e in entries:
    aid = e['alpha_id']
    if aid in ('a11', 'a16', 'a19'):
        CROPS[aid] = (330, 1000, 780, 1350)
    else:
        CROPS[aid] = (330, 980, 780, 1300)

TW, TH, COLS = 460, 326, 3
tiles = []
base = Image.open(os.path.join(ROOT, '_base', 'furina-base.png')).convert('RGBA')
bc = base.crop((140, 180, 224, 265)).resize((TW, TH), Image.NEAREST)
t = Image.new('RGB', (TW, TH), (255, 255, 255)); t.paste(bc, (0, 0), bc)
ImageDraw.Draw(t).text((5, 3), 'BASE strap: viewer-LEFT thigh (4x zoom)', fill=(200, 0, 0))
tiles.append(('BASE', t))
for e in entries:
    aid = e['alpha_id']
    im = Image.open(e['master_file'].replace('\\', '/')).convert('RGBA')
    c = im.crop(CROPS[aid]).resize((TW, TH), Image.LANCZOS)
    t = Image.new('RGB', (TW, TH), (255, 255, 255)); t.paste(c, (0, 0), c)
    ImageDraw.Draw(t).text((5, 3), f'{aid}', fill=(200, 0, 0))
    tiles.append((aid, t))

for si in range(0, len(tiles), 9):
    chunk = tiles[si:si + 9]
    rows = (len(chunk) + COLS - 1) // COLS
    sheet = Image.new('RGB', (COLS * (TW + 6) + 6, rows * (TH + 6) + 6), (60, 60, 60))
    for i, (name, tile) in enumerate(chunk):
        r, ci = divmod(i, COLS)
        sheet.paste(tile, (6 + ci * (TW + 6), 6 + r * (TH + 6)))
    p = os.path.join(OUT, f'strapzoom_{si//9:02d}.png')
    sheet.save(p)
    print('saved', p, [t2[0] for t2 in chunk])
