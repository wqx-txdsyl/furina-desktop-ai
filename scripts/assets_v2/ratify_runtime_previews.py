"""NIGHT-02: read-only runtime scale previews (512/256/128) + required overview sheets."""
import json, os
from PIL import Image, ImageDraw

ROOT = 'data/assets_v2'
PRE = os.path.join(ROOT, 'review', 'runtime_previews')
os.makedirs(PRE, exist_ok=True)
m = json.load(open(os.path.join(ROOT, 'metadata', 'manifest_v2.json'), encoding='utf-8'))
entries = sorted(m['entries'], key=lambda e: e['alpha_id'])

verdict = {}
for e in entries:
    aid = e['alpha_id']
    im = Image.open(e['master_file'].replace('\\', '/')).convert('RGBA')
    for w in (512, 256, 128):
        h = int(im.height * w / im.width)
        im.resize((w, h), Image.LANCZOS).save(os.path.join(PRE, f'{aid}_{w}.png'))

# --- runtime_scale_overview.png: all masters + BASE at true pet size 128px
TILE_W, TILE_H = 128, 192
COLS = 5
tiles = []
base = Image.open(os.path.join(ROOT, '_base', 'furina-base.png')).convert('RGBA')
b = base.resize((TILE_W, TILE_H), Image.LANCZOS)
tile = Image.new('RGBA', (TILE_W, TILE_H + 24), (245, 245, 245, 255))
tile.paste(b, (0, 6), b)
ImageDraw.Draw(tile).text((4, TILE_H + 5), 'BASE', fill=(0, 0, 0))
tiles.append(('BASE', tile))
for e in entries:
    aid = e['alpha_id']
    im = Image.open(e['master_file'].replace('\\', '/')).convert('RGBA').resize((TILE_W, TILE_H), Image.LANCZOS)
    tile = Image.new('RGBA', (TILE_W, TILE_H + 24), (245, 245, 245, 255))
    tile.paste(im, (0, 6), im)
    ImageDraw.Draw(tile).text((4, TILE_H + 5), aid, fill=(0, 0, 0))
    tiles.append((aid, tile))
nrows = (len(tiles) + COLS - 1) // COLS
sheet = Image.new('RGB', (COLS * (TILE_W + 8) + 8, nrows * (TILE_H + 30) + 8), (40, 40, 40))
d = ImageDraw.Draw(sheet)
d.text((8, 2), 'Furina v2 alpha — runtime 128px pet-size readability (all masters + BASE)', fill=(255, 255, 255))
for i, (name, tile) in enumerate(tiles):
    r, c = divmod(i, COLS)
    sheet.paste(tile, (8 + c * (TILE_W + 8), 16 + r * (TILE_H + 30)))
sheet.save(os.path.join(ROOT, 'review', 'runtime_scale_overview.png'))
print('saved runtime_scale_overview.png')

# --- ratification_overview.png: contact sheet ~168px with verdict labels
TW, TH = 168, 252
COLS = 5
entries_sorted = sorted(m['entries'], key=lambda e: e['alpha_id'])
# placeholder verdicts filled from JSON if exists
vr = {}
vp = os.path.join(ROOT, 'metadata', 'ratification_v1.json')
if os.path.exists(vp):
    vr = json.load(open(vp, encoding='utf-8')).get('verdicts', {})
nrows = (len(entries_sorted) + COLS - 1) // COLS
sheet = Image.new('RGB', (COLS * (TW + 8) + 8, nrows * (TH + 26) + 8), (30, 30, 30))
d = ImageDraw.Draw(sheet)
d.text((8, 2), 'Furina v2 alpha — independent ratification contact sheet', fill=(255, 255, 255))
for i, e in enumerate(entries_sorted):
    aid = e['alpha_id']
    im = Image.open(e['master_file'].replace('\\', '/')).convert('RGBA').resize((TW, TH), Image.LANCZOS)
    tile = Image.new('RGBA', (TW, TH + 24), (245, 245, 245, 255))
    tile.paste(im, (0, 2), im)
    dd = ImageDraw.Draw(tile)
    v = vr.get(aid, {}).get('verdict', '?')
    color = (0, 160, 0) if v == 'ACCEPT' else (200, 150, 0) if v == 'HOLD' else (200, 0, 0)
    dd.text((4, TH + 6), f'{aid} {v}', fill=color)
    r, c = divmod(i, COLS)
    sheet.paste(tile, (8 + c * (TW + 8), 16 + r * (TH + 26)))
sheet.save(os.path.join(ROOT, 'review', 'ratification_overview.png'))
print('saved ratification_overview.png')
