"""NIGHT-02: lower-body crop sheets (tail side + thigh strap side) for all 19 masters + BASE row."""
import json, os
from PIL import Image, ImageDraw

ROOT = 'data/assets_v2'
OUT = os.path.join(ROOT, 'review', 'ratification_lowerbody_sheets')
os.makedirs(OUT, exist_ok=True)

m = json.load(open(os.path.join(ROOT, 'metadata', 'manifest_v2.json'), encoding='utf-8'))
entries = sorted(m['entries'], key=lambda e: e['alpha_id'])

CROP = (100, 880, 950, 1470)  # lower body region
TW, TH = 510, 350  # tile size after scaling crop (850x590 -> 0.6)
COLS = 2
PER_SHEET = 6

tiles = []
# BASE first as reference row tile
base = Image.open(os.path.join(ROOT, '_base', 'furina-base.png')).convert('RGBA')
bc = base.crop((10, 0, 224, 320)).resize((TW, TH), Image.LANCZOS)
bw = Image.new('RGB', (TW, TH), (255, 255, 255))
bw.paste(bc, (0, 0), bc)
d = ImageDraw.Draw(bw)
d.text((5, 3), 'BASE (ground truth: tail=viewer-RIGHT, strap=viewer-LEFT thigh)', fill=(200, 0, 0))
tiles.append(('BASE', bw))

for e in entries:
    aid = e['alpha_id']
    mf = e['master_file'].replace('\\', '/')
    im = Image.open(mf).convert('RGBA')
    c = im.crop(CROP).resize((TW, TH), Image.LANCZOS)
    tile = Image.new('RGB', (TW, TH), (255, 255, 255))
    tile.paste(c, (0, 0), c)
    dd = ImageDraw.Draw(tile)
    dd.text((5, 3), f'{aid} {e["semantic_state"]}', fill=(200, 0, 0))
    dd.text((5, 16), 'tail side? strap side?', fill=(0, 0, 200))
    tiles.append((aid, tile))

for si in range(0, len(tiles), PER_SHEET):
    chunk = tiles[si:si + PER_SHEET]
    rows = (len(chunk) + COLS - 1) // COLS
    sheet = Image.new('RGB', (COLS * (TW + 8) + 8, rows * (TH + 8) + 8), (60, 60, 60))
    for i, (name, tile) in enumerate(chunk):
        r, cidx = divmod(i, COLS)
        sheet.paste(tile, (8 + cidx * (TW + 8), 8 + r * (TH + 8)))
    p = os.path.join(OUT, f'lowerbody_{si//PER_SHEET:02d}.png')
    sheet.save(p)
    print('saved', p, 'tiles:', [t[0] for t in chunk])
