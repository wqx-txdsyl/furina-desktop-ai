"""NIGHT03_PATCH2B_R1A_R4 — negative mutation tests for the plan freeze.

Every test really mutates a temporary copy of the committed data and
then runs the independent verifier
(scripts/assets_v2/night03_patch2b_r1a_r4_verify_plan.py) as a
subprocess.  The verifier must REJECT every mutation (exit != 0) and
accept the pristine delivery (exit == 0).

Covered mutations:
  1.  a16 partition missing pixel            -> FAIL
  2.  a16 duplicate/overlapping pixel        -> FAIL
  3.  a16 pixel outside the R6A-R4 union     -> FAIL
  4.  a16 illegal class name                 -> FAIL
  5.  a01 tail raw source over alpha<=8      -> FAIL
  6.  a01 tail raw source hits protected     -> FAIL
  7.  a05 tail raw source hits protected     -> FAIL
  8.  mirror destination outside tail map    -> FAIL
  9.  R6A-R4 primitive/ledger tampering      -> FAIL
  10. R4 protected mask tampering            -> FAIL
  11. stale report                           -> FAIL
  12. stale manifest                         -> FAIL
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import pytest

REPO = Path(__file__).resolve().parents[3]
VERIFIER = REPO / ('scripts/assets_v2/'
                   'night03_patch2b_r1a_r4_verify_plan.py')
SOURCES = REPO / 'data/assets_v2/annotation_sources/night03_patch2b_r1a_r4'
OUTPUT = REPO / ('data/assets_v2/repair_candidates/'
                 'night03_patch2b_r1a_r4')
R6AR4 = REPO / ('data/assets_v2/repair_candidates/'
                'night03_patch2a_r6ar4/a16_ownership_annotation.json')
R4MASKS = REPO / ('data/assets_v2/repair_candidates/'
                  'night03_patch2a_r4/mask_plan')
MASTERS = REPO / 'data/assets_v2/masters'

A01_PROTECTED_ADD = (1030, 292, 295)   # protected_props, visible, not in src
A05_PROTECTED_ADD = (795, 380, 383)    # protected_costume, visible, not in src


def run_verifier(sources=None, output=None, r6ar4=None, r4masks=None):
    cmd = [sys.executable, str(VERIFIER)]
    cmd += ['--sources', str(sources or SOURCES)]
    cmd += ['--output', str(output or OUTPUT)]
    cmd += ['--r6ar4-json', str(r6ar4 or R6AR4)]
    cmd += ['--r4masks', str(r4masks or R4MASKS)]
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=str(REPO))


def copy_sources(tmp_path):
    dst = tmp_path / 'src'
    shutil.copytree(SOURCES, dst)
    return dst


def copy_output(tmp_path):
    dst = tmp_path / 'out'
    shutil.copytree(OUTPUT, dst)
    return dst


def load_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def save_json(p, doc):
    Path(p).write_text(json.dumps(doc, ensure_ascii=True),
                       encoding='utf-8', newline='\n')


def test_pristine_delivery_passes():
    r = run_verifier()
    assert r.returncode == 0, r.stdout + r.stderr


def test_a16_missing_pixel_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    removed = False
    for row in doc['rows']:
        if len(row) >= 3:
            del row[1]
            removed = True
            break
    assert removed
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'missing a16 pixel accepted'


def test_a16_duplicate_pixel_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    injected = False
    for row in doc['rows']:
        if len(row) >= 2:
            a, b, cname = row[1]
            row.append([a, min(a + 1, b), 'hand_glove'
                        if cname != 'hand_glove' else 'gold_cuff'])
            injected = True
            break
    assert injected
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'duplicate a16 pixel accepted'


def test_a16_outside_union_pixel_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    doc['rows'].append([50, [0, 5, 'transparent']])
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'outside-union a16 pixel accepted'


def test_a16_illegal_class_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    row = doc['rows'][0]
    a, b, _ = row[1]
    row[1] = [a, b, 'banana']
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'illegal a16 class accepted'


def test_a01_tail_over_alpha_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a01_tail_source.json')
    doc['rows'].append([50, [0, 5]])
    save_json(src / 'a01_tail_source.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'a01 raw source over transparent area accepted'


def test_a01_tail_protected_rejected(tmp_path):
    src = copy_sources(tmp_path)
    y, x0, x1 = A01_PROTECTED_ADD
    doc = load_json(src / 'a01_tail_source.json')
    doc['rows'].append([y, [x0, x1]])
    save_json(src / 'a01_tail_source.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'a01 raw source hitting protected accepted'


def test_a05_tail_protected_rejected(tmp_path):
    src = copy_sources(tmp_path)
    y, x0, x1 = A05_PROTECTED_ADD
    doc = load_json(src / 'a05_tail_source.json')
    doc['rows'].append([y, [x0, x1]])
    save_json(src / 'a05_tail_source.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'a05 raw source hitting protected accepted'


def test_mirror_source_map_outside_tail_rejected(tmp_path):
    out = copy_output(tmp_path)
    p = out / 'a01' / 'a01_tail_destination.png'
    arr = np.array(Image.open(p).convert('L'))
    assert arr[50, 50] == 0
    arr[50, 50] = 255
    Image.fromarray(arr).save(p)
    r = run_verifier(output=out)
    assert r.returncode != 0, 'destination outside the tail map accepted'


def test_r6ar4_authority_tamper_rejected(tmp_path):
    doc = load_json(R6AR4)
    prim = doc['primitives']['remove_cane']
    a, b = prim[0][1]
    prim[0][1] = [int(a) + 1, int(b)]
    p = tmp_path / 'a16_ownership_annotation.json'
    save_json(p, doc)
    r = run_verifier(r6ar4=p)
    assert r.returncode != 0, 'tampered R6A-R4 authority accepted'


def test_protected_mask_tamper_rejected(tmp_path):
    masks = tmp_path / 'mask_plan'
    shutil.copytree(R4MASKS, masks)
    p = masks / 'a01' / 'a01_protected_props.png'
    arr = np.array(Image.open(p).convert('L'))
    arr[1300, 310] = 255 if arr[1300, 310] == 0 else 0
    Image.fromarray(arr).save(p)
    r = run_verifier(r4masks=masks)
    assert r.returncode != 0, 'tampered protected mask accepted'


def test_stale_report_rejected(tmp_path):
    out = copy_output(tmp_path)
    p = out / 'NIGHT03_PATCH2B_R1A_R4_REPORT.md'
    text = p.read_text(encoding='utf-8')
    target = None
    for line in text.splitlines():
        if '- tail_source_px:' in line:
            target = line
            break
    assert target
    tampered = text.replace(target, target + '  (stale)')
    p.write_text(tampered, encoding='utf-8', newline='\n')
    r = run_verifier(output=out)
    assert r.returncode != 0, 'stale report accepted'


def test_stale_manifest_rejected(tmp_path):
    out = copy_output(tmp_path)
    p = out / 'manifest.json'
    mf = load_json(p)
    key = sorted(mf)[0]
    mf[key] = '0' * 64
    save_json(p, mf)
    r = run_verifier(output=out)
    assert r.returncode != 0, 'stale manifest accepted'
