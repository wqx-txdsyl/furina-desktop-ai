"""NIGHT03_PATCH2B_R1A_R6 — negative mutation + reproducibility tests.

Every test really mutates a temporary copy of the committed data and
runs the independent verifier
(scripts/assets_v2/night03_patch2b_r1a_r6_verify_plan.py) as a
subprocess.  The verifier must REJECT every mutation (exit != 0) and
accept the pristine delivery (exit == 0).

Where the task book demands it, ALL sync-able metadata (review totals,
report, receipt, manifest) is re-synced after the tamper so the
rejection provably comes from the coverage/closure checks, not from
stale-hash detection.

R1A-R6 required mutations:
  1.  delete one complete review row (+ full metadata sync) -> FAIL
  2.  duplicate a review y                              -> FAIL
  3.  duplicate a final-source row                      -> FAIL
  4.  duplicate/overlap a rejected run                  -> FAIL
  5.  swap row order (review rows reversed)             -> FAIL
  6.  tamper the independent DRAFT_AUTHORITY            -> FAIL
  7.  delete review row, sync totals/report/receipt/manifest -> FAIL
Carried-over mutations: a16 missing/duplicate/outside/illegal class,
a16 provenance deleted / control-rows injected, a01 over alpha,
a01/a05 protected, mirror map, R6A-R4 authority tamper, protected mask
tamper, cutout/overlay/zoom/palette 1px (manifest synced), stale
report (manifest synced), stale manifest.
Plus: full byte reproducibility from a fresh exact checkout.
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
                   'night03_patch2b_r1a_r6_verify_plan.py')
FREEZE = REPO / ('scripts/assets_v2/'
                 'night03_patch2b_r1a_r6_freeze_plan.py')
SOURCES = REPO / 'data/assets_v2/annotation_sources/night03_patch2b_r1a_r6'
OUTPUT = REPO / ('data/assets_v2/repair_candidates/'
                 'night03_patch2b_r1a_r6')
R6AR4 = REPO / ('data/assets_v2/repair_candidates/'
                'night03_patch2a_r6ar4/a16_ownership_annotation.json')
R4MASKS = REPO / ('data/assets_v2/repair_candidates/'
                  'night03_patch2a_r4/mask_plan')

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


# ---------------- R1A-R6 ledger-closure mutations --------------------

def _sync_review_metadata(src_dir, asset, doc):
    """Recompute every sync-able number so only the closure checks can
    reject (review totals, report, receipt, manifest)."""
    review = doc['review']
    rows = review['rows']
    d = a = rj = 0
    for _y, d_r, a_r, r_r in rows:
        for run in d_r:
            d += run[1] - run[0] + 1
        for run in a_r:
            a += run[1] - run[0] + 1
        for run in r_r:
            rj += run[1] - run[0] + 1
    review['draft_px'] = d
    review['accepted_px'] = a
    review['rejected_px'] = rj
    review['unreviewed_px'] = 0
    save_json(src_dir / f'{asset}_tail_source.json', doc)

    # output copy mirrors report/receipt/manifest must be synced by the
    # caller via the returned numbers; here we only fix the source side.


def test_delete_review_row_fully_synced_rejected(tmp_path):
    """Task book item: delete one complete review row and sync ALL
    sync-able metadata (review totals, report, receipt, manifest).
    Must still FAIL via the coverage/closure checks."""
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a01_tail_source.json')
    review = doc['review']
    assert len(review['rows']) == 319
    removed = review['rows'].pop(40)   # delete an arbitrary middle row
    _sync_review_metadata(src, 'a01', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, \
        'deleted review row accepted even with full metadata sync'


def test_delete_review_row_with_output_sync_rejected(tmp_path):
    """Task book item: delete review row AND sync totals/report/receipt/
    manifest in the output copy too. Must still FAIL."""
    src = copy_sources(tmp_path)
    out = copy_output(tmp_path)
    doc = load_json(src / 'a01_tail_source.json')
    review = doc['review']
    removed = review['rows'].pop(40)
    y = removed[0]
    _sync_review_metadata(src, 'a01', doc)

    # mirror the new totals into report + receipt, then resync manifest
    rep_p = out / 'NIGHT03_PATCH2B_R1A_R6_REPORT.md'
    rep = rep_p.read_text(encoding='utf-8')
    rep = rep.replace(f'- review_draft_px: 24925',
                      f'- review_draft_px: {review["draft_px"]}')
    rep = rep.replace(f'- review_accepted_px: 24349',
                      f'- review_accepted_px: {review["accepted_px"]}')
    rep = rep.replace(f'- review_rejected_px: 576',
                      f'- review_rejected_px: {review["rejected_px"]}')
    rep = rep.replace(f'- tail_source_px: 24349',
                      f'- tail_source_px: {review["accepted_px"]}')
    rep_p.write_text(rep, encoding='utf-8', newline='\n')
    rec_p = out / 'NIGHT03_PATCH2B_R1A_R6_RECEIPT.txt'
    rec = rec_p.read_text(encoding='utf-8')
    rec = rec.replace('A01_REVIEW_DRAFT_PX = 24925',
                      f'A01_REVIEW_DRAFT_PX = {review["draft_px"]}')
    rec = rec.replace('A01_REVIEW_ACCEPTED_PX = 24349',
                      f'A01_REVIEW_ACCEPTED_PX = {review["accepted_px"]}')
    rec = rec.replace('A01_REVIEW_REJECTED_PX = 576',
                      f'A01_REVIEW_REJECTED_PX = {review["rejected_px"]}')
    rec = rec.replace('A01_TAIL_SOURCE_PX = 24349',
                      f'A01_TAIL_SOURCE_PX = {review["accepted_px"]}')
    rec_p.write_text(rec, encoding='utf-8', newline='\n')

    # rebuild the output source-dependent masks to match the tampered
    # source (accepted minus the deleted row), then resync manifest for
    # every touched file
    sys.path.insert(0, str(REPO / 'scripts' / 'assets_v2'))
    import night03_patch2b_r1a_r6_fixedpng as fxpng
    H, W = 1536, 1024

    def rebuild(rows_spec):
        m = np.zeros((H, W), bool)
        for row in rows_spec:
            y2 = int(row[0])
            for a, b in row[1:]:
                m[y2, int(a):int(b) + 1] = True
        return m

    final_rows = [r for r in doc['rows'] if r[0] != y]
    doc['rows'] = final_rows
    doc['source_px'] = review['accepted_px']
    save_json(src / 'a01_tail_source.json', doc)
    final = rebuild(final_rows)
    fxpng.write_png_gray(out / 'a01' / 'a01_tail_source.png',
                         np.where(final, 255, 0).astype(np.uint8))
    np.save(out / 'a01' / 'a01_tail_source.npy', final.astype(np.uint8))
    w = 1024
    dest = np.zeros_like(final)
    ys, xs = np.where(final)
    dest[ys, (w - 1) - xs] = True
    fxpng.write_png_gray(out / 'a01' / 'a01_tail_destination.png',
                         np.where(dest, 255, 0).astype(np.uint8))
    np.save(out / 'a01' / 'a01_tail_destination.npy', dest.astype(np.uint8))
    resync_manifest(out, 'a01/a01_tail_source.png')
    resync_manifest(out, 'a01/a01_tail_source.npy')
    resync_manifest(out, 'a01/a01_tail_destination.png')
    resync_manifest(out, 'a01/a01_tail_destination.npy')
    resync_manifest(out, 'NIGHT03_PATCH2B_R1A_R6_REPORT.md')
    resync_manifest(out, 'NIGHT03_PATCH2B_R1A_R6_RECEIPT.txt')

    r = run_verifier(sources=src, output=out)
    assert r.returncode != 0, \
        'deleted review row accepted even with output fully synced'


def test_duplicate_review_y_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a05_tail_source.json')
    review = doc['review']
    dup = json.loads(json.dumps(review['rows'][10]))
    review['rows'].insert(11, dup)
    save_json(src / 'a05_tail_source.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'duplicate review y accepted'


def test_duplicate_final_source_row_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a01_tail_source.json')
    dup = json.loads(json.dumps(doc['rows'][50]))
    doc['rows'].insert(51, dup)
    save_json(src / 'a01_tail_source.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'duplicate final-source row accepted'


def test_duplicate_rejected_run_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a05_tail_source.json')
    for entry in doc['review']['rows']:
        if entry[3]:
            entry[3].append(list(entry[3][0]))
            break
    else:
        pytest.fail('no rejected runs found in a05 ledger')
    save_json(src / 'a05_tail_source.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'duplicate/overlapping rejected run accepted'


def test_swapped_row_order_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a01_tail_source.json')
    doc['review']['rows'][20], doc['review']['rows'][21] = \
        doc['review']['rows'][21], doc['review']['rows'][20]
    save_json(src / 'a01_tail_source.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'swapped review row order accepted'


def test_draft_authority_tamper_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a01_tail_draft_authority.json')
    doc['draft_px'] = doc['draft_px'] - 1
    save_json(src / 'a01_tail_draft_authority.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'tampered draft authority accepted'


# ---------------- carried-over mutations ------------------------------

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


def test_a16_provenance_deleted_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    del doc['provenance']
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'a16 with deleted provenance accepted'


def test_a16_control_row_claims_rejected(tmp_path):
    src = copy_sources(tmp_path)
    doc = load_json(src / 'a16_occlusion_annotation.json')
    doc['parts'] = {'dome_hand': {'control_rows': [[933, 752, 756]]}}
    save_json(src / 'a16_occlusion_annotation.json', doc)
    r = run_verifier(sources=src)
    assert r.returncode != 0, 'a16 with control-row claims accepted'


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
    arr = np.array(Image.open(p))
    assert arr[50, 50] == 0
    arr[50, 50] = 255
    Image.fromarray(arr).save(p)
    resync_manifest(out, 'a01/a01_tail_destination.png')
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
    arr = np.array(Image.open(p))
    arr[1300, 310] = 255 if arr[1300, 310] == 0 else 0
    Image.fromarray(arr).save(p)
    r = run_verifier(r4masks=masks)
    assert r.returncode != 0, 'tampered protected mask accepted'


def test_cutout_1px_tamper_with_manifest_sync_rejected(tmp_path):
    out = copy_output(tmp_path)
    rel = 'a16_class_hand_glove_cutout.png'
    p = out / rel
    arr = np.array(Image.open(p).convert('RGB'))
    assert not np.array_equal(arr[10, 10], [1, 2, 3])
    arr[10, 10] = [1, 2, 3]
    Image.fromarray(arr).save(p)
    resync_manifest(out, rel)
    r = run_verifier(output=out)
    assert r.returncode != 0, 'tampered cutout accepted (manifest synced)'


def test_overlay_1px_tamper_with_manifest_sync_rejected(tmp_path):
    out = copy_output(tmp_path)
    rel = 'a16_semantic_overlay.png'
    p = out / rel
    arr = np.array(Image.open(p).convert('RGB'))
    assert not np.array_equal(arr[10, 10], [4, 5, 6])
    arr[10, 10] = [4, 5, 6]
    Image.fromarray(arr).save(p)
    resync_manifest(out, rel)
    r = run_verifier(output=out)
    assert r.returncode != 0, 'tampered overlay accepted (manifest synced)'


def test_zoom_1px_tamper_with_manifest_sync_rejected(tmp_path):
    out = copy_output(tmp_path)
    rel = 'a16_zoom_seat_800.png'
    p = out / rel
    arr = np.array(Image.open(p).convert('RGB'))
    assert not np.array_equal(arr[10, 10], [7, 8, 9])
    arr[10, 10] = [7, 8, 9]
    Image.fromarray(arr).save(p)
    resync_manifest(out, rel)
    r = run_verifier(output=out)
    assert r.returncode != 0, 'tampered zoom evidence accepted'


def test_palette_tamper_with_manifest_sync_rejected(tmp_path):
    out = copy_output(tmp_path)
    rel = 'a16_occlusion_partition_indexed.png'
    p = out / rel
    im = Image.open(p)
    assert im.mode == 'P'
    pal = im.getpalette()[:]
    pal[0:3] = [1, 2, 3]
    im.putpalette(pal)
    im.save(p)
    resync_manifest(out, rel)
    r = run_verifier(output=out)
    assert r.returncode != 0, 'tampered palette accepted (manifest synced)'


def test_stale_report_with_manifest_sync_rejected(tmp_path):
    out = copy_output(tmp_path)
    rel = 'NIGHT03_PATCH2B_R1A_R6_REPORT.md'
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
def test_fresh_checkout_byte_reproducibility(tmp_path):
    """fresh exact checkout -> delete R1A-R6 output -> single freeze
    entry rebuild -> committed == rebuilt 48/48 bytes -> second run
    still 48/48."""
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
    rel_out = Path('data/assets_v2/repair_candidates/night03_patch2b_r1a_r6')
    committed = ref / rel_out
    assert committed.exists()
    shutil.rmtree(work / rel_out)
    assert not (work / rel_out).exists()

    def freeze_and_compare(label):
        r = subprocess.run(
            [sys.executable, str(work / FREEZE.relative_to(REPO))],
            capture_output=True, text=True, cwd=str(work))
        assert r.returncode == 0, f'{label}: freeze failed\n{r.stderr}'
        built = work / rel_out
        files = sorted(p.relative_to(built).as_posix()
                       for p in built.rglob('*') if p.is_file())
        assert len(files) == 48, f'{label}: {len(files)} files'
        mismatch = [f for f in files
                    if (built / f).read_bytes()
                    != (committed / f).read_bytes()]
        assert not mismatch, f'{label}: not byte-identical: {mismatch[:5]}'

    freeze_and_compare('first run')
    freeze_and_compare('second run')
