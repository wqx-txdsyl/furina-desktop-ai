"""NIGHT-03 finalization: batch gate checks, triptychs, previews, refreshed metadata."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/assets_v2/repair_candidates/night03'
BASE = np.array(Image.open(ROOT / 'data/assets_v2/_base/furina-base.png'))
MASTERS = ROOT / 'data/assets_v2/masters'
META = ROOT / 'data/assets_v2/metadata'

NAMES = {
    'a01': 'stand_neutral_front', 'a03': 'stand_neutral_slight_right',
    'a04': 'stand_relaxed_idle', 'a05': 'stand_confident_proud',
    'a06': 'stand_gentle_happy', 'a07': 'stand_annoyed', 'a08': 'stand_embarrassed',
    'a09': 'stand_curious_leaning', 'a10': 'stand_sleepy', 'a13': 'pet_response',
    'a14': 'poke_response', 'a16': 'work_focused', 'a18': 'stand_quiet_reflective',
    'a19': 'eating',
}
ALL = list(NAMES)


def sha256(p):
    h = hashlib.sha256()
    h.update(Path(p).read_bytes())
    return h.hexdigest()


def measure(path):
    im = np.array(Image.open(path))
    a = im[..., 3] > 8
    rows = np.where(a.any(axis=1))[0]
    cols = np.where(a.any(axis=0))[0]
    lab, n = ndimage.label(a)
    sizes = sorted(ndimage.sum(a, lab, range(1, n + 1)).tolist(), reverse=True)
    rgb = im[..., :3].astype(int)
    magenta = int((((rgb[..., 0] > 180) & (rgb[..., 2] > 180) & (rgb[..., 1] < 90)) & a).sum())
    comx = float((np.arange(1024)[None, :] * a).sum() / a.sum())
    return {'content_px': [int(cols.min()), int(rows.min()),
                           int(cols.max() - cols.min() + 1), int(rows.max() - rows.min() + 1)],
            'lowest_row': int(rows.max()), 'com_x': round(comx / 1024, 4),
            'alpha_components': n, 'islands_gt40': int(sum(1 for s in sizes[1:] if s > 40)),
            'magenta_px': magenta,
            'corners_transparent': all([im[0:24, 0:24, 3].max() == 0, im[0:24, -24:, 3].max() == 0,
                                        im[-24:, 0:24, 3].max() == 0, im[-24:, -24:, 3].max() == 0])}


def diff_stats(key):
    o = np.array(Image.open(MASTERS / f'furina_v2_{key}_{NAMES[key]}.png'))
    n = np.array(Image.open(OUT / f'furina_v2_{key}_repair.png'))
    d = np.any(o != n, axis=-1)
    return {'changed_px': int(d.sum()), 'head_zone_changed_px': int(d[:850, :].sum()),
            'changed_pct': round(100 * d.sum() / d.size, 2)}


def triptych(key):
    o = Image.open(MASTERS / f'furina_v2_{key}_{NAMES[key]}.png').convert('RGBA')
    n = Image.open(OUT / f'furina_v2_{key}_repair.png').convert('RGBA')
    b = Image.fromarray(BASE).convert('RGBA').resize((683, 1024))
    panel = Image.new('RGBA', (683 * 3 + 16, 1024), (25, 25, 25, 255))
    panel.paste(o.resize((683, 1024)), (0, 0))
    panel.paste(n.resize((683, 1024)), (691, 0))
    panel.alpha_composite(b, (1382, 0))
    panel.save(OUT / f'night03_triptych_{key}.png')


def previews(key):
    n = Image.open(OUT / f'furina_v2_{key}_repair.png').convert('RGBA')
    d = OUT / 'runtime_previews'
    d.mkdir(exist_ok=True)
    for s in (512, 256, 128):
        n.resize((s, int(s * 1.5)), Image.LANCZOS).save(d / f'{key}_pet_{s}.png')


def refresh_meta(key):
    src = META_SRC = MASTERS / f'furina_v2_{key}_{NAMES[key]}.meta.json'
    meta = json.loads(src.read_text(encoding='utf-8'))
    m = measure(OUT / f'furina_v2_{key}_repair.png')
    meta['geometry']['content_px'] = m['content_px']
    meta['review_status'] = 'PENDING'
    old_notes = meta.get('review_notes', '')
    meta['review_notes'] = (
        'NIGHT-03 local repair candidate (master untouched): tail MIRRORED_ERROR corrected to '
        'BASE-consistent viewer-right by extract->span-fill->mirror->composite-behind; '
        + ('prop/matte defects removed locally; ' if key in ('a05', 'a13', 'a16', 'a19') else '')
        + f"measured com_x {m['com_x']}"
        + (', deviation from 0.50±0.03 recorded per GEOMETRY spec §5.2 (pose right-leaning / '
           'tail mass relocation; semantic reason: tail-side correction)' if m['com_x'] > 0.53 else '')
        + '. Awaiting human review.')
    meta['night03_repair'] = {
        'method': 'local_surgical_no_generation',
        'generation_calls': 0,
        'candidate_file': str((OUT / f'furina_v2_{key}_repair.png').relative_to(ROOT)),
        'candidate_sha256': sha256(OUT / f'furina_v2_{key}_repair.png'),
        'master_file': str((MASTERS / f'furina_v2_{key}_{NAMES[key]}.png').relative_to(ROOT)),
        'master_sha256': sha256(MASTERS / f'furina_v2_{key}_{NAMES[key]}.png'),
        'measured': m,
    }
    dst = OUT / 'metadata' / f'furina_v2_{key}_{NAMES[key]}.meta.json'
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding='utf-8')
    return m


def refresh_a02():
    """ACCEPT master, pixels untouched: refresh only the +-1px content_px metadata error."""
    key, name = 'a02', 'stand_neutral_slight_left'
    src = MASTERS / f'furina_v2_{key}_{name}.meta.json'
    meta = json.loads(src.read_text(encoding='utf-8'))
    m = measure(MASTERS / f'furina_v2_{key}_{name}.png')
    old = meta['geometry']['content_px']
    meta['geometry']['content_px'] = m['content_px']
    changed = old != m['content_px']
    meta['review_notes'] = (
        'NIGHT-03: metadata-only re-measurement of content_px under the alpha>8 convention: '
        f'recorded {old}, measured {m["content_px"]} -> '
        + ('refreshed' if changed else 'identical, no change required')
        + '; pixels untouched (ACCEPT). Master file unchanged.')
    meta['night03_metadata_refresh'] = {'recorded': old, 'measured': m['content_px'],
                                        'changed': bool(changed), 'pixels_changed': False}
    dst = OUT / 'metadata' / f'furina_v2_{key}_{name}.meta.json'
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding='utf-8')
    return old, m['content_px']


if __name__ == '__main__':
    report = {}
    for key in ALL:
        m = measure(OUT / f'furina_v2_{key}_repair.png')
        entry = {'measured': m, 'diff': diff_stats(key)}
        ok = (m['alpha_components'] == 1 and m['islands_gt40'] == 0 and m['magenta_px'] == 0
              and m['corners_transparent'] and m['lowest_row'] == 1467
              and entry['diff']['head_zone_changed_px'] < 50)
        entry['objective_pass'] = bool(ok)
        report[key] = entry
        triptych(key)
        previews(key)
        refresh_meta(key)
        print(key, json.dumps(entry))
    old_px, new_px = refresh_a02()
    print('a02 metadata:', old_px, '->', new_px)
    (OUT / '_finalize_checks.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
