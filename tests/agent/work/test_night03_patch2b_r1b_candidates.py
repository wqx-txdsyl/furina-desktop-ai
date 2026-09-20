"""NIGHT03_PATCH2B_R1B — candidate mutation + reproducibility tests.

1 positive control + 18 real mutations + 1 fresh-checkout byte
reproducibility test.  Every mutation really edits a temporary copy of
the delivered files and the independent verifier
(scripts/assets_v2/night03_patch2b_r1b_verify_candidates.py) is run as
a subprocess; it must reject every mutation (exit != 0).
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
                   'night03_patch2b_r1b_verify_candidates.py')
FREEZE = REPO / ('scripts/assets_v2/'
                 'night03_patch2b_r1b_build_candidates.py')
R1A_SRC = REPO / ('data/assets_v2/annotation_sources/'
                  'night03_patch2b_r1a_r6')
R1B_SRC = REPO / ('data/assets_v2/annotation_sources/'
                  'night03_patch2b_r1b')
OUTPUT = REPO / ('data/assets_v2/repair_candidates/'
                 'night03_patch2b_r1b')
MASTERS = REPO / 'data/assets_v2/masters'


def runs_rebuild(rows_spec, h=1536, w=1024):
    m = np.zeros((h, w), bool)
    for row in rows_spec:
        y = int(row[0])
        for a, b in row[1:]:
            m[y, int(a):int(b) + 1] = True
    return m


def mirror(mask, w=1024):
    out = np.zeros_like(mask)
    ys, xs = np.where(mask)
    out[ys, (w - 1) - xs] = True
    return out


def run_verifier(r1a_src=None, r1b_src=None, output=None, masters=None):
    cmd = [sys.executable, str(VERIFIER)]
    cmd += ['--r1a-src', str(r1a_src or R1A_SRC)]
    cmd += ['--r1b-src', str(r1b_src or R1B_SRC)]
    cmd += ['--output', str(output or OUTPUT)]
    cmd += ['--masters', str(masters or MASTERS)]
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=str(REPO))


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
    data = (Path(out_dir) / rel).read_bytes()
    mf[rel.replace('\\', '/')] = hashlib.sha256(data).hexdigest()
    mf_p.write_text(json.dumps(mf, indent=1, sort_keys=True) + '\n',
                    encoding='utf-8', newline='\n')


def test_pristine_delivery_passes():
    r = run_verifier()
    assert r.returncode == 0, r.stdout + r.stderr


def _mutate_candidate(tmp_path, asset, mask_fn, color):
    out = copy_output(tmp_path)
    cand_p = out / asset / f'{asset}_candidate.png'
    arr = np.array(Image.open(cand_p).convert('RGBA'))
    mask = mask_fn()
    ys, xs = np.where(mask)
    assert len(ys) > 0
    arr[ys[0], xs[0]] = color
    assert not np.array_equal(
        arr[ys[0], xs[0]], np.array(Image.open(cand_p).convert('RGBA'))[ys[0], xs[0]])
    Image.fromarray(arr).save(cand_p)
    resync_manifest(out, f'{asset}/{asset}_candidate.png')
    return out


def _a01_masks():
    doc = load_json(R1A_SRC / 'a01_tail_source.json')
    source = runs_rebuild(doc['rows'])
    dest = mirror(source)
    vis = dest & (np.array(Image.open(
        MASTERS / 'furina_v2_a01_stand_neutral_front.png')
        .convert('RGBA'))[..., 3] <= 8)
    under = dest & ~vis
    outside = ~(source | dest)
    return source, vis, under, outside


def _a05_masks():
    doc = load_json(R1A_SRC / 'a05_tail_source.json')
    source = runs_rebuild(doc['rows'])
    dest = mirror(source)
    vis = dest & (np.array(Image.open(
        MASTERS / 'furina_v2_a05_stand_confident_proud.png')
        .convert('RGBA'))[..., 3] <= 8)
    under = dest & ~vis
    under_prot = under & (np.array(Image.open(
        MASTERS / 'furina_v2_a05_stand_confident_proud.png')
        .convert('RGBA'))[..., 3] > 8)
    outside = ~(source | dest)
    return source, vis, under, outside, under_prot


def test_a01_source_px_left_rejected(tmp_path):
    src, *_ = _a01_masks()
    out = _mutate_candidate(tmp_path, 'a01', lambda: src, (255, 255, 255, 255))
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a01 source px left in candidate accepted'


def test_a01_destination_mirror_wrong_rejected(tmp_path):
    _, vis, _, _ = _a01_masks()
    out = _mutate_candidate(tmp_path, 'a01', lambda: vis, (1, 2, 3, 255))
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a01 mirror-incorrect destination accepted'


def test_a01_outside_union_modified_rejected(tmp_path):
    _, _, _, outside = _a01_masks()
    out = _mutate_candidate(tmp_path, 'a01', lambda: outside, (9, 9, 9, 255))
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a01 outside-union modification accepted'


def test_a01_underlay_modified_rejected(tmp_path):
    _, _, under, _ = _a01_masks()
    out = _mutate_candidate(tmp_path, 'a01', lambda: under, (9, 9, 9, 255))
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a01 underlay modification accepted'


def test_a05_source_px_left_rejected(tmp_path):
    src, *_ = _a05_masks()
    out = _mutate_candidate(tmp_path, 'a05', lambda: src, (255, 255, 255, 255))
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a05 source px left in candidate accepted'


def test_a05_destination_mirror_wrong_rejected(tmp_path):
    _, vis, _, _, _ = _a05_masks()
    out = _mutate_candidate(tmp_path, 'a05', lambda: vis, (1, 2, 3, 255))
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a05 mirror-incorrect destination accepted'


def test_a05_outside_union_modified_rejected(tmp_path):
    _, _, _, outside, _ = _a05_masks()
    out = _mutate_candidate(tmp_path, 'a05', lambda: outside, (9, 9, 9, 255))
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a05 outside-union modification accepted'


def test_a05_protected_underlay_modified_rejected(tmp_path):
    _, _, _, _, under_prot = _a05_masks()
    out = _mutate_candidate(tmp_path, 'a05', lambda: under_prot,
                            (9, 9, 9, 255))
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a05 protected underlay modification accepted'


def _a16_sets():
    doc = load_json(R1A_SRC / 'a16_occlusion_annotation.json')
    CLS = doc['class_vocabulary']
    sem = np.full((1536, 1024), -1, np.int16)
    for row in doc['rows']:
        y = int(row[0])
        for a, b, cn in row[1:]:
            sem[y, int(a):int(b) + 1] = CLS.index(cn)
    union = sem >= 0
    trans = sem == 0
    non = sem > 0
    return union, trans, non


def test_a16_outside_union_modified_rejected(tmp_path):
    union, trans, non = _a16_sets()
    outside = ~union

    def fn():
        return outside
    out = copy_output(tmp_path)
    p = out / 'a16' / 'a16_candidate.png'
    arr = np.array(Image.open(p).convert('RGBA'))
    ys, xs = np.where(fn())
    arr[ys[0], xs[0]] = (9, 9, 9, 255)
    Image.fromarray(arr).save(p)
    resync_manifest(out, 'a16/a16_candidate.png')
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a16 outside-union modification accepted'


def test_a16_transparent_nonzero_rejected(tmp_path):
    _, trans, _ = _a16_sets()
    out = copy_output(tmp_path)
    p = out / 'a16' / 'a16_candidate.png'
    arr = np.array(Image.open(p).convert('RGBA'))
    ys, xs = np.where(trans)
    arr[ys[0], xs[0]] = (1, 1, 1, 255)
    Image.fromarray(arr).save(p)
    resync_manifest(out, 'a16/a16_candidate.png')
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a16 transparent px nonzero accepted'


def test_a16_nontransparent_transparent_rejected(tmp_path):
    _, _, non = _a16_sets()
    out = copy_output(tmp_path)
    p = out / 'a16' / 'a16_candidate.png'
    arr = np.array(Image.open(p).convert('RGBA'))
    ys, xs = np.where(non)
    arr[ys[0], xs[0]] = (0, 0, 0, 0)
    Image.fromarray(arr).save(p)
    resync_manifest(out, 'a16/a16_candidate.png')
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a16 non-transparent px made transparent accepted'


def test_a16_write_coverage_missing_rejected(tmp_path):
    _, _, non = _a16_sets()
    out = copy_output(tmp_path)
    p = out / 'a16' / 'a16_candidate.png'
    arr = np.array(Image.open(p).convert('RGBA'))
    ys, xs = np.where(non)
    arr[ys[0], xs[0]] = (0, 0, 0, 0)
    Image.fromarray(arr).save(p)
    resync_manifest(out, 'a16/a16_candidate.png')
    r = run_verifier(output=out)
    assert r.returncode != 0, 'a16 missing write-coverage px accepted'


def test_r1a_frozen_file_tamper_rejected(tmp_path):
    src = tmp_path / 'r1a'
    shutil.copytree(R1A_SRC, src)
    doc = load_json(src / 'a01_tail_source.json')
    doc['source_px'] = doc['source_px'] + 1
    save_json(src / 'a01_tail_source.json', doc)
    r = run_verifier(r1a_src=src)
    assert r.returncode != 0, 'tampered R1A frozen source accepted'


def test_master_tamper_rejected(tmp_path):
    masters = tmp_path / 'masters'
    shutil.copytree(MASTERS, masters)
    p = masters / 'furina_v2_a16_work_focused.png'
    arr = np.array(Image.open(p).convert('RGBA'))
    arr[10, 10] = (arr[10, 10].astype(np.int32) + 1) % 256
    Image.fromarray(arr).save(p)
    r = run_verifier(masters=masters)
    assert r.returncode != 0, 'tampered master accepted'


def test_a16_reconstruction_source_tamper_rejected(tmp_path):
    src = tmp_path / 'r1b'
    shutil.copytree(R1B_SRC, src)
    p = src / 'a16_reconstruction_source.png'
    arr = np.array(Image.open(p).convert('RGBA'))
    ys, xs = np.where(arr[..., 3] == 255)
    arr[ys[0], xs[0]] = (9, 9, 9, 255)
    Image.fromarray(arr).save(p)
    r = run_verifier(r1b_src=src)
    assert r.returncode != 0, 'tampered a16 reconstruction source accepted'


def test_stale_report_with_manifest_sync_rejected(tmp_path):
    out = copy_output(tmp_path)
    rel = 'NIGHT03_PATCH2B_R1B_REPORT.md'
    p = out / rel
    text = p.read_text(encoding='utf-8')
    target = None
    for line in text.splitlines():
        if '- tail_source_px:' in line:
            target = line
            break
    assert target
    p.write_text(text.replace(target, target + '  (stale)'),
                 encoding='utf-8', newline='\n')
    resync_manifest(out, rel)
    r = run_verifier(output=out)
    assert r.returncode != 0, 'stale report accepted (manifest synced)'


def test_wrong_manifest_rejected(tmp_path):
    out = copy_output(tmp_path)
    p = out / 'manifest.json'
    mf = load_json(p)
    key = sorted(mf)[0]
    mf[key] = '0' * 64
    save_json(p, mf)
    r = run_verifier(output=out)
    assert r.returncode != 0, 'wrong manifest accepted'


def test_evidence_1px_tamper_with_manifest_sync_rejected(tmp_path):
    out = copy_output(tmp_path)
    rel = 'a01/a01_diff_classified.png'
    p = out / rel
    arr = np.array(Image.open(p).convert('RGB'))
    ys, xs = np.where((arr != 0).any(axis=-1))
    y0, x0 = ys[0], xs[0]
    arr[y0, x0] = ((arr[y0, x0].astype(np.int32) + 7) % 256).astype(np.uint8)
    Image.fromarray(arr).save(p)
    resync_manifest(out, rel)
    r = run_verifier(output=out)
    assert r.returncode != 0, 'tampered evidence accepted (manifest synced)'


# ---------------- byte reproducibility --------------------------------

@pytest.mark.slow
def test_fresh_checkout_byte_reproducibility(tmp_path):
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
    rel_out = Path('data/assets_v2/repair_candidates/night03_patch2b_r1b')
    committed = ref / rel_out
    assert committed.exists()
    shutil.rmtree(work / rel_out)
    assert not (work / rel_out).exists()

    def build_and_compare(label):
        r = subprocess.run(
            [sys.executable, str(work / FREEZE.relative_to(REPO))],
            capture_output=True, text=True, cwd=str(work))
        assert r.returncode == 0, f'{label}: build failed\n{r.stderr}'
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
