"""NIGHT03_PATCH2B_R1A_R7 — semantic freeze mutation tests.

1 positive control + real mutations (each mutates a temporary copy of
the R1A-R7 static source or deliverable and runs the independent
verifier as a subprocess; must reject: exit != 0) + fresh-checkout
double byte reproduction.
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import numpy as np
from PIL import Image

import pytest

REPO = Path(__file__).resolve().parents[3]
VERIFIER = REPO / ('scripts/assets_v2/'
                   'night03_patch2b_r1a_r7_verify_plan.py')
FREEZE = REPO / ('scripts/assets_v2/'
                 'night03_patch2b_r1a_r7_freeze_plan.py')
SOURCES = REPO / ('data/assets_v2/annotation_sources/'
                  'night03_patch2b_r1a_r7')
R6_SRC = REPO / ('data/assets_v2/annotation_sources/'
                 'night03_patch2b_r1a_r6/a16_occlusion_annotation.json')
R1B_OUT = REPO / ('data/assets_v2/repair_candidates/'
                  'night03_patch2b_r1b')
R1B_R1_OUT = REPO / ('data/assets_v2/repair_candidates/'
                     'night03_patch2b_r1b_r1')
OUTPUT = REPO / ('data/assets_v2/repair_candidates/'
                 'night03_patch2b_r1a_r7')
MASTERS = REPO / 'data/assets_v2/masters'


def run_verifier(sources=None, r6_src=None, r1b_out=None,
                 r1b_r1_out=None, output=None, masters=None):
    cmd = [sys.executable, str(VERIFIER)]
    cmd += ['--sources', str(sources or SOURCES)]
    cmd += ['--r6-src', str(r6_src or R6_SRC)]
    cmd += ['--r1b-out', str(r1b_out or R1B_OUT)]
    cmd += ['--r1b-r1-out', str(r1b_r1_out or R1B_R1_OUT)]
    cmd += ['--output', str(output or OUTPUT)]
    cmd += ['--masters', str(masters or MASTERS)]
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


def resync_manifest(out_dir, rel):
    mf_p = Path(out_dir) / 'manifest.json'
    mf = json.loads(mf_p.read_text(encoding='utf-8'))
    mf[rel.replace('\\', '/')] = hashlib.sha256(
        (Path(out_dir) / rel).read_bytes()).hexdigest()
    mf_p.write_text(json.dumps(mf, indent=1, sort_keys=True) + '\n',
                    encoding='utf-8', newline='\n')


def test_pristine_delivery_passes():
    r = run_verifier()
    assert r.returncode == 0, r.stdout + r.stderr


def test_roi_outside_class_change_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    for row in doc['rows']:
        if row[0] == 933:  # dome glove strip, OUTSIDE the ROI
            for i, e in enumerate(row[1:]):
                if e[2] == 'hand_glove':
                    row[1 + i] = [e[0], e[1], 'transparent']
                    break
            break
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'ROI-outside class change accepted'


def test_prop_union_plus_one_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    doc['rows'].append([50, [0, 5, 'transparent']])
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'prop union +1 accepted'


def test_prop_union_minus_one_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    a, b, cn = doc['rows'][0][1]
    doc['rows'][0][1] = [a + 1, b, cn]
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'prop union -1 accepted'


def test_batch_lower_box_flip_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    ledger = load_json(src / 'hand_ledger.json')
    flipped = 0
    for row in doc['rows']:
        y = row[0]
        if not (1055 <= y < 1080):
            continue
        new_entries = []
        for e in row[1:]:
            if e[2] == 'transparent':
                new_entries.append([e[0], e[1], 'hand_glove'])
                flipped += e[1] - e[0] + 1
            else:
                new_entries.append(e)
        row[:] = [y] + new_entries
    assert flipped >= 100, flipped
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'batch box flip accepted'


def test_batch_upper_box_flip_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    flipped = 0
    for row in doc['rows']:
        y = row[0]
        if not (985 <= y < 1015):
            continue
        new_entries = []
        for e in row[1:]:
            if e[2] == 'transparent':
                new_entries.append([e[0], e[1], 'hand_glove'])
                flipped += e[1] - e[0] + 1
            else:
                new_entries.append(e)
        row[:] = [y] + new_entries
    assert flipped >= 500, flipped
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'batch upper flip accepted'


def test_illegal_class_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    doc['rows'][0][1][2] = 'banana'
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'illegal class accepted'


def test_changed_px_missing_ledger_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    ledger = load_json(src / 'hand_ledger.json')
    # revert the FIRST ledger change in the rows (ledger keeps it)
    y, a, b, oc, nc, reason = ledger['entries'][0]
    for row in doc['rows']:
        if row[0] == y:
            for e in row[1:]:
                if e[2] == nc and not (e[0] == a and e[1] == b):
                    continue
            for i, e in enumerate(row[1:]):
                if e[0] <= a and e[1] >= b and e[2] == nc:
                    row[1 + i] = [a, b, oc]
                    break
            break
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'changed px missing from ledger accepted'


def test_ledger_unchanged_px_rejected(tmp_path):
    src = copy_sources(tmp_path)
    ledger = load_json(src / 'hand_ledger.json')
    ledger['entries'].append([50, 0, 3, 'transparent', 'hand_glove',
                              'HAND_CONNECTIVITY'])
    save_json(src / 'hand_ledger.json', ledger)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'ledger entry for unchanged px accepted'


def test_ledger_duplicate_run_rejected(tmp_path):
    src = copy_sources(tmp_path)
    ledger = load_json(src / 'hand_ledger.json')
    ledger['entries'].append(list(ledger['entries'][0]))
    save_json(src / 'hand_ledger.json', ledger)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'duplicate ledger run accepted'


def test_ledger_out_of_order_rejected(tmp_path):
    src = copy_sources(tmp_path)
    ledger = load_json(src / 'hand_ledger.json')
    ledger['entries'][5], ledger['entries'][30] = \
        ledger['entries'][30], ledger['entries'][5]
    save_json(src / 'hand_ledger.json', ledger)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'out-of-order ledger accepted'


def test_rows_duplicate_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    doc['rows'].append(list(doc['rows'][10]))
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'duplicate row accepted'


def test_rows_extra_field_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    doc['rows'][0][1].append('extra')
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'extra-field entry accepted'


def test_static_source_sha_tamper_rejected(tmp_path):
    src = copy_sources(tmp_path)
    ledger = load_json(src / 'hand_ledger.json')
    ledger['note'] = 'tampered'
    save_json(src / 'hand_ledger.json', ledger)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'tampered static source accepted'


def test_old_r1a_tamper_rejected(tmp_path):
    r6 = tmp_path / 'r6.json'
    doc = load_json(R6_SRC)
    doc['prop_union_px'] = 36123
    save_json(r6, doc)
    r = run_verifier(r6_src=r6)
    assert r.returncode != 0, 'tampered R1A baseline accepted'


def test_old_r1b_tamper_rejected(tmp_path):
    r1b = tmp_path / 'r1b'
    shutil.copytree(R1B_OUT, r1b)
    p = r1b / 'manifest.json'
    mf = load_json(p)
    key = sorted(mf)[0]
    mf[key] = '0' * 64
    save_json(p, mf)
    r = run_verifier(r1b_out=r1b)
    assert r.returncode != 0, 'tampered R1B delivery accepted'


def test_old_r1b_r1_tamper_rejected(tmp_path):
    r1b_r1 = tmp_path / 'r1b_r1'
    shutil.copytree(R1B_R1_OUT, r1b_r1)
    p = r1b_r1 / 'manifest.json'
    mf = load_json(p)
    key = sorted(mf)[0]
    mf[key] = '0' * 64
    save_json(p, mf)
    r = run_verifier(r1b_r1_out=r1b_r1)
    assert r.returncode != 0, 'tampered R1B-R1 delivery accepted'


def test_evidence_1px_synced_rejected(tmp_path):
    out = copy_output(tmp_path)
    rel = 'a16_changed_pixel_overlay.png'
    p = out / rel
    arr = np.array(Image.open(p).convert('RGB'))
    ys, xs = np.where((arr != 0).any(axis=-1))
    arr[ys[0], xs[0]] = ((arr[ys[0], xs[0]].astype(np.int32) + 7) % 256
                         ).astype(np.uint8)
    Image.fromarray(arr).save(p)
    resync_manifest(out, rel)
    r = run_verifier(output=out)
    assert r.returncode != 0, 'tampered evidence accepted (synced)'


def test_stale_manifest_rejected(tmp_path):
    out = copy_output(tmp_path)
    p = out / 'manifest.json'
    mf = load_json(p)
    key = sorted(mf)[0]
    mf[key] = '0' * 64
    save_json(p, mf)
    r = run_verifier(output=out)
    assert r.returncode != 0, 'stale manifest accepted'


# ---------------- byte reproducibility --------------------------------

@pytest.mark.slow
def test_fresh_checkout_double_byte_reproducibility(tmp_path):
    sha = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True,
                         text=True, cwd=str(REPO)).stdout.strip()
    assert len(sha) == 40

    def extract(destination):
        destination.mkdir(parents=True)
        tar_path = tmp_path / (destination.name + '.tar')
        with open(tar_path, 'wb') as fh:
            subprocess.run(['git', 'archive', sha], stdout=fh,
                           cwd=str(REPO), check=True)
        with tarfile.open(tar_path) as tf:
            tf.extractall(destination)
        return destination

    ref = extract(tmp_path / 'ref')
    work = extract(tmp_path / 'work')
    rel_out = Path('data/assets_v2/repair_candidates/night03_patch2b_r1a_r7')
    committed = ref / rel_out
    assert committed.exists()
    shutil.rmtree(work / rel_out)

    def build_and_compare(label):
        r = subprocess.run(
            [sys.executable, str(work / FREEZE.relative_to(REPO))],
            capture_output=True, text=True, cwd=str(work))
        assert r.returncode == 0, f'{label}: freeze failed\n{r.stderr}'
        built = work / rel_out
        files = sorted(p.relative_to(built).as_posix()
                       for p in built.rglob('*') if p.is_file())
        mismatch = [f for f in files
                    if (built / f).read_bytes()
                    != (committed / f).read_bytes()]
        assert not mismatch, f'{label}: not byte-identical: {mismatch[:5]}'
        return len(files)

    n1 = build_and_compare('first run')
    n2 = build_and_compare('second run')
    assert n1 == n2
