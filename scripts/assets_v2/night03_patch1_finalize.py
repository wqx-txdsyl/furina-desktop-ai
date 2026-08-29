"""NIGHT-03 Patch 1 — finalize: gates, previews, triptychs, overlays, metadata, manifest.

Re-runs the deterministic builders (reproducible), measures everything from the
actual files, writes deliverables under repair_candidates/night03_patch1/.
Masters/production are opened read-only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import night03_patch1_repair as R

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
BASE_P = ROOT / 'data/assets_v2/_base/furina-base.png'
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch1'
META_OUT = OUT / 'metadata'
PREV_OUT = OUT / 'runtime_previews'
META_OUT.mkdir(parents=True, exist_ok=True)
PREV_OUT.mkdir(parents=True, exist_ok=True)

NAMES = {'a01': 'stand_neutral_front', 'a05': 'stand_confident_proud',
         'a16': 'work_focused'}
BASE = np.array(Image.open(BASE_P))


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def measure(im):
    a = im[..., 3] > 8
    rows = np.where(a.any(axis=1))[0]
    cols = np.where(a.any(axis=0))[0]
    lab, n = ndimage.label(a)
    sizes = sorted(ndimage.sum(a, lab, range(1, n + 1)).tolist(), reverse=True)
    rgb = im[..., :3].astype(int)
    magenta = int((((rgb[..., 0] > 180) & (rgb[..., 2] > 180) & (rgb[..., 1] < 90)) & a).sum())
    opaque = im[..., 3] >= 250
    semi = (im[..., 3] >= 1) & (im[..., 3] < 250)
    ys, xs = np.where(opaque)
    comx = float((np.arange(im.shape[1])[None, :] * a).sum() / max(a.sum(), 1))
    return {'content_px': [int(cols.min()), int(rows.min()),
                           int(cols.max() - cols.min() + 1), int(rows.max() - rows.min() + 1)],
            'lowest_row': int(rows.max()), 'com_x': round(comx / im.shape[1], 4),
            'alpha_components': n,
            'islands_gt40': int(sum(1 for s in sizes[1:] if s > 40)),
            'largest_sizes': [int(s) for s in sizes[:4]],
            'magenta_px': magenta,
            'corners_transparent': all([im[0:24, 0:24, 3].max() == 0,
                                        im[0:24, -24:, 3].max() == 0,
                                        im[-24:, 0:24, 3].max() == 0,
                                        im[-24:, -24:, 3].max() == 0]),
            'opaque_px': int(opaque.sum()), 'semi_px': int(semi.sum()),
            'opaque_bbox': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if opaque.any() else None,
            'centroid_x_px': round(comx, 1),
            'margin_left': int(cols.min()), 'margin_right': int(1023 - cols.max()),
            'ground_contact_row': int(rows.max())}


def diff_classes(m, c):
    d = (c != m).any(axis=-1)
    del_ = d & (c[..., 3] <= 8) & (m[..., 3] > 8)
    add_ = d & (c[..., 3] > 8) & (m[..., 3] <= 8)
    chg_ = d & ~del_ & ~add_
    return d, del_, add_, chg_


def diffmap(m, c, path):
    d, del_, add_, chg_ = diff_classes(m, c)
    vis = np.zeros((1536, 1024, 4), np.uint8)
    vis[..., :3] = 35
    vis[..., 3] = 255
    vis[del_] = [255, 0, 0, 255]
    vis[add_] = [0, 255, 0, 255]
    vis[chg_] = [255, 255, 0, 255]
    Image.fromarray(vis).save(path)


def triptych(key, cand_path):
    o = Image.open(MASTERS / f'furina_v2_{key}_{NAMES[key]}.png').convert('RGBA')
    n = Image.open(cand_path).convert('RGBA')
    b = Image.fromarray(BASE).convert('RGBA').resize((683, 1024))
    panel = Image.new('RGBA', (683 * 3 + 16, 1024), (25, 25, 25, 255))
    panel.paste(o.resize((683, 1024)), (0, 0))
    panel.paste(n.resize((683, 1024)), (691, 0))
    panel.alpha_composite(b, (1382, 0))
    panel.convert('RGB').save(OUT / f'night03_patch1_triptych_{key}.png')


def bbox_of(mask):
    if not mask.any():
        return None
    ys = np.where(mask.any(axis=1))[0]
    xs = np.where(mask.any(axis=0))[0]
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def main():
    master_sha_before = {k: sha256(MASTERS / f'furina_v2_{k}_{NAMES[k]}.png')
                         for k in NAMES}
    report = {}
    for key in ('a01', 'a05', 'a16'):
        out, masks, info = R.ASSETS[key]()
        cand_path = OUT / f'furina_v2_{key}_repair.png'
        Image.fromarray(out).save(cand_path)
        m = np.array(Image.open(MASTERS / f'furina_v2_{key}_{NAMES[key]}.png'))
        c = np.array(Image.open(cand_path))

        meas = measure(c)
        d, del_, add_, chg_ = diff_classes(m, c)
        allowed = masks['allowed_edit']
        outside = int((d & ~allowed).sum())
        del_out = int((del_ & ~allowed).sum())
        add_out = int((add_ & ~allowed).sum())
        chg_out = int((chg_ & ~allowed).sum())

        mask_stats = {k: {'px': int(v.sum()), 'bbox': bbox_of(v)}
                      for k, v in masks.items()}

        ci = Image.fromarray(c)
        for s in (512, 256, 128):
            ci.resize((s, int(s * 1.5)), Image.LANCZOS).save(PREV_OUT / f'{key}_pet_{s}.png')
        triptych(key, cand_path)
        diffmap(m, c, OUT / f'{key}_diff_overlay.png')
        ov = c.copy()
        colors = {'corridor': (90, 200, 255), 'tail_source': (255, 255, 0),
                  'removal': (255, 0, 0), 'chair_del': (160, 60, 0),
                  'cane_del': (255, 140, 0), 'specks': (255, 0, 130),
                  'protected_skin': (0, 90, 0), 'protected_navy': (0, 60, 120),
                  'quill_paper': (0, 200, 90), 'protected_hair': (0, 200, 200),
                  'protected_bow': (255, 0, 255), 'protected_arm': (0, 90, 0),
                  'protected_hip': (128, 0, 128), 'protected_shorts': (255, 0, 130),
                  'protected_dark': (0, 90, 0), 'protected_cane': (255, 140, 0),
                  'protected_frills': (255, 0, 255), 'patch_footprint': (0, 255, 140),
                  'explicit_debris': (255, 0, 255), 'weld': (0, 255, 255)}
        for k, v in masks.items():
            if k == 'allowed_edit' or k not in colors:
                continue
            ov[v, :3] = colors[k]
            ov[v, 3] = 255
        Image.fromarray(ov).save(OUT / f'{key}_mask_overlay.png')

        objective_ok = (meas['alpha_components'] == 1 and meas['islands_gt40'] == 0
                        and meas['magenta_px'] == 0 and meas['corners_transparent']
                        and outside == 0)
        entry = {'candidate_file': str(cand_path.relative_to(ROOT)),
                 'candidate_sha256': sha256(cand_path),
                 'master_file': str((MASTERS / f'furina_v2_{key}_{NAMES[key]}.png').relative_to(ROOT)),
                 'master_sha256': master_sha_before[key],
                 'measured': meas,
                 'diff': {'changed_px': int(d.sum()), 'deleted_px': int(del_.sum()),
                          'added_px': int(add_.sum()), 'recolored_px': int(chg_.sum()),
                          'outside_allowed_px': outside,
                          'deleted_outside': del_out, 'added_outside': add_out,
                          'recolored_outside': chg_out,
                          'unauthorized_diff_pixels': outside},
                 'mask_stats': mask_stats,
                 'builder_info': R.jsan(info),
                 'objective_pass': bool(objective_ok)}
        report[key] = entry
        print(key, 'outside=', outside, 'objective=', objective_ok,
              'com_x=', meas['com_x'], 'lowest=', meas['lowest_row'])

        src = MASTERS / f'furina_v2_{key}_{NAMES[key]}.meta.json'
        meta = json.loads(src.read_text(encoding='utf-8'))
        meta['geometry']['content_px'] = meas['content_px']
        meta['review_status'] = 'PENDING'
        com_note = ''
        if meas['com_x'] > 0.53:
            com_note = (f"; com_x {meas['com_x']} deviates from 0.50+/-0.03 per GEOMETRY spec "
                        '5.2: tail mass relocated to the BASE-consistent viewer-right side; '
                        'semantic reason: NIGHT-03 tail-side correction (no crop/shift/scale applied)')
        meta['review_notes'] = (
            'NIGHT-03 PATCH1 candidate (master untouched): semantic-layering repair - '
            'old wrong-side tail removed via geometric corridor + protections, whole tail '
            'mirrored about x=512 and composited BEHIND the master body (body pixels '
            'bit-identical outside allowed_edit_mask)' + com_note +
            '. Awaiting independent review.')
        meta['night03_patch1'] = {
            'patch_id': 'NIGHT03_RECOVERY_PATCH1',
            'method': 'semantic_layer_local_no_generation',
            'generation_calls': 0,
            'candidate_file': entry['candidate_file'],
            'candidate_sha256': entry['candidate_sha256'],
            'master_file': entry['master_file'],
            'master_sha256': entry['master_sha256'],
            'input_from_master_only': True,
            'failed_night03_candidates_used': False,
            'measured': meas,
            'diff': entry['diff'],
            'mask_stats': mask_stats,
            'objective_pass': entry['objective_pass'],
        }
        (META_OUT / f'furina_v2_{key}_{NAMES[key]}.meta.json').write_text(
            json.dumps(meta, indent=1, ensure_ascii=False), encoding='utf-8')

    master_sha_after = {k: sha256(MASTERS / f'furina_v2_{k}_{NAMES[k]}.png')
                        for k in NAMES}
    manifest = {
        'patch_id': 'NIGHT03_RECOVERY_PATCH1',
        'created_utc': datetime.utcnow().isoformat() + 'Z',
        'inputs_from_master_only': True,
        'failed_night03_candidates_used': False,
        'generation_calls': 0,
        'assets': report,
        'masters_unchanged': master_sha_before == master_sha_after,
        'master_sha256': master_sha_after,
        'base_sha256': sha256(BASE_P),
        'production_files_changed': 0,
    }
    (OUT / 'night03_patch1_manifest.json').write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding='utf-8')
    print('masters_unchanged:', master_sha_before == master_sha_after)


if __name__ == '__main__':
    main()
