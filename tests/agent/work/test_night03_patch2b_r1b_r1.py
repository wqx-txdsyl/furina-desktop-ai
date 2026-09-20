"""NIGHT03_PATCH2B_R1B_R1 — mutation + reproducibility tests.

1 positive control + real mutations + fresh-checkout double byte
reproducibility.  Every mutation really edits a temporary copy; the
independent verifier (night03_patch2b_r1b_r1_verify.py) runs as a
subprocess and must reject every mutation (exit != 0).
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
VERIFIER = REPO / 'scripts/assets_v2/night03_patch2b_r1b_r1_verify.py'
BUILDER = REPO / ('scripts/assets_v2/'
                  'night03_patch2b_r1b_r1_build_evidence.py')
R1A_SRC = REPO / ('data/assets_v2/annotation_sources/'
                  'night03_patch2b_r1a_r6')
R1B_SRC = REPO / ('data/assets_v2/annotation_sources/'
                  'night03_patch2b_r1b')
R1B_R1_SRC = REPO / ('data/assets_v2/annotation_sources/'
                     'night03_patch2b_r1b_r1')
R1B_OUT = REPO / ('data/assets_v2/repair_candidates/'
                  'night03_patch2b_r1b')
OUTPUT = REPO / ('data/assets_v2/repair_candidates/'
                 'night03_patch2b_r1b_r1')
MASTERS = REPO / 'data/assets_v2/masters'


def r1b_manifest_sha():
    return hashlib.sha256(
        (R1B_OUT / 'manifest.json').read_bytes()).hexdigest()


def run_verifier(r1a_src=None, r1b_src=None, r1b_r1_src=None,
                 output=None, r1b_out=None, masters=None,
                 r1b_manifest_sha=None):
    if r1b_manifest_sha is None:
        r1b_manifest_sha = hashlib.sha256(
            (R1B_OUT / 'manifest.json').read_bytes()).hexdigest()
    cmd = [sys.executable, str(VERIFIER)]
    cmd += ['--r1a-src', str(r1a_src or R1A_SRC)]
    cmd += ['--r1b-src', str(r1b_src or R1B_SRC)]
    cmd += ['--r1b-r1-src', str(r1b_r1_src or R1B_R1_SRC)]
    cmd += ['--output', str(output or OUTPUT)]
    cmd += ['--r1b-out', str(r1b_out or R1B_OUT)]
    cmd += ['--masters', str(masters or MASTERS)]
    cmd += ['--r1b-manifest-sha', str(r1b_manifest_sha)]
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=str(REPO))


def copy_tree(src, name):
    dst = tmp_root() / name
    shutil.copytree(src, dst)
    return dst


def tmp_root():
    return Path(__file__).parent


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
    r = run_verifier(r1b_manifest_sha=r1b_manifest_sha())
    assert r.returncode == 0, r.stdout + r.stderr


def test_destination_evidence_deleted_rejected(tmp_path):
    out = tmp_path / 'out'
    shutil.copytree(OUTPUT, out)
    (out / 'a01' / 'a01_dest_crop_tail_root_dest_400.png').unlink()
    r = run_verifier(output=out, r1b_manifest_sha=r1b_manifest_sha())
    assert r.returncode != 0, 'deleted destination evidence accepted'


def test_destination_evidence_1px_synced_rejected(tmp_path):
    out = tmp_path / 'out'
    shutil.copytree(OUTPUT, out)
    rel = 'a01/a01_dest_crop_tail_root_dest_400.png'
    p = out / rel
    arr = np.array(Image.open(p).convert('RGB'))
    arr[5, 5] = ((arr[5, 5].astype(np.int32) + 9) % 256).astype(np.uint8)
    Image.fromarray(arr).save(p)
    resync_manifest(out, rel)
    r = run_verifier(output=out, r1b_manifest_sha=r1b_manifest_sha())
    assert r.returncode != 0, 'misaligned destination evidence accepted'


def test_old_r1b_file_modified_rejected(tmp_path):
    out = tmp_path / 'out'
    shutil.copytree(OUTPUT, out)
    r1b = out.parent / 'r1b_locked'
    shutil.copytree(R1B_OUT, r1b)
    p = r1b / 'a01' / 'a01_candidate.png'
    arr = np.array(Image.open(p).convert('RGBA'))
    arr[500, 500] = (9, 9, 9, 255)
    Image.fromarray(arr).save(p)
    # keep the R1B manifest internally consistent (resync) - the byte
    # lock on the manifest file itself must still catch this
    mf_p = r1b / 'manifest.json'
    mf = json.loads(mf_p.read_text(encoding='utf-8'))
    mf['a01/a01_candidate.png'] = hashlib.sha256(
        p.read_bytes()).hexdigest()
    mf_p.write_text(json.dumps(mf, indent=1, sort_keys=True) + '\n',
                    encoding='utf-8', newline='\n')
    locked_sha = hashlib.sha256(
        (R1B_OUT / 'manifest.json').read_bytes()).hexdigest()
    r = run_verifier(output=out, r1b_out=r1b,
                     r1b_manifest_sha=locked_sha)
    assert r.returncode != 0, 'modified old R1B file accepted'


def test_r1a_source_tamper_rejected(tmp_path):
    src = tmp_path / 'r1a'
    shutil.copytree(R1A_SRC, src)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    doc['prop_union_px'] = 36123
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(r1a_src=src, r1b_manifest_sha=r1b_manifest_sha())
    assert r.returncode != 0, 'tampered R1A source accepted'


def test_r1b_r1_a16_source_tamper_rejected(tmp_path):
    src = tmp_path / 'r1b_r1'
    shutil.copytree(R1B_R1_SRC, src)
    p = src / 'a16_reconstruction_source.png'
    arr = np.array(Image.open(p).convert('RGBA'))
    ys, xs = np.where(arr[..., 3] == 255)
    arr[ys[0], xs[0]] = (9, 9, 9, 255)
    Image.fromarray(arr).save(p)
    r = run_verifier(r1b_r1_src=src, r1b_manifest_sha=r1b_manifest_sha())
    assert r.returncode != 0, 'tampered a16 reconstruction source accepted'


def test_a16_candidate_inconsistency_rejected(tmp_path):
    out = tmp_path / 'out'
    shutil.copytree(OUTPUT, out)
    p = out / 'a16' / 'a16_candidate.png'
    arr = np.array(Image.open(p).convert('RGBA'))
    ys, xs = np.where((arr[..., 3] == 255))
    arr[ys[0], xs[0]] = (5, 5, 5, 255)
    Image.fromarray(arr).save(p)
    resync_manifest(out, 'a16/a16_candidate.png')
    r = run_verifier(output=out, r1b_manifest_sha=r1b_manifest_sha())
    assert r.returncode != 0, 'inconsistent a16 candidate accepted'


def test_stale_blocker_claim_rejected(tmp_path):
    out = tmp_path / 'out'
    shutil.copytree(OUTPUT, out)
    rel = 'NIGHT03_PATCH2B_R1B_R1_REPORT.md'
    p = out / rel
    text = p.read_text(encoding='utf-8')
    stale = text.replace('severs the fist/wrist from the cuff band; a ',
                         'severs the fist/wrist from the cuff band; STALE ')
    p.write_text(stale, encoding='utf-8', newline='\n')
    resync_manifest(out, rel)
    r = run_verifier(output=out, r1b_manifest_sha=r1b_manifest_sha())
    assert r.returncode != 0, 'stale blocker claim accepted'


def test_false_self_gate_claim_rejected(tmp_path):
    out = tmp_path / 'out'
    shutil.copytree(OUTPUT, out)
    rel = 'NIGHT03_PATCH2B_R1B_R1_RECEIPT.txt'
    p = out / rel
    text = p.read_text(encoding='utf-8')
    text = text.replace('SELF_GATE_PASS = false',
                        'SELF_GATE_PASS = true')
    p.write_text(text, encoding='utf-8', newline='\n')
    resync_manifest(out, rel)
    r = run_verifier(output=out, r1b_manifest_sha=r1b_manifest_sha())
    assert r.returncode != 0, 'false self-gate claim accepted'


# ---------------- byte reproducibility --------------------------------

@pytest.mark.slow
def test_fresh_checkout_double_byte_reproducibility(tmp_path):
    """fresh exact checkout -> delete R1B-R1 output -> single entry ->
    committed == rebuilt byte-identical -> second run identical; also
    the locked R1B delivery must remain byte-identical."""
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
    rel_out = Path('data/assets_v2/repair_candidates/night03_patch2b_r1b_r1')
    committed = ref / rel_out
    assert committed.exists()
    shutil.rmtree(work / rel_out)

    def build_and_compare(label):
        r = subprocess.run(
            [sys.executable, str(work / BUILDER.relative_to(REPO))],
            capture_output=True, text=True, cwd=str(work))
        assert r.returncode == 0, f'{label}: build failed\n{r.stderr}'
        built = work / rel_out
        files = sorted(p.relative_to(built).as_posix()
                       for p in built.rglob('*') if p.is_file())
        mismatch = [f for f in files
                    if (built / f).read_bytes()
                    != (committed / f).read_bytes()]
        assert not mismatch, f'{label}: not byte-identical: {mismatch[:5]}'
        # the locked R1B delivery must also remain byte-identical
        rel_r1b = Path('data/assets_v2/repair_candidates/night03_patch2b_r1b')
        r1b_files = sorted(p.relative_to(work / rel_r1b).as_posix()
                           for p in (work / rel_r1b).rglob('*')
                           if p.is_file())
        r1b_bad = [f for f in r1b_files
                   if (work / rel_r1b / f).read_bytes()
                   != (ref / rel_r1b / f).read_bytes()]
        assert not r1b_bad, f'{label}: R1B delivery changed: {r1b_bad[:3]}'
        return len(files)

    n1 = build_and_compare('first run')
    n2 = build_and_compare('second run')
    assert n1 == n2
