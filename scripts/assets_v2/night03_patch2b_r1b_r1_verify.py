"""NIGHT-03 Patch 2B R1B-R1 — independent verifier.

Inherits every R1B candidate check (the R1B delivery is byte-locked via
its own pinned manifest) and adds the R1B-R1 specifics: destination
evidence correctness, a16 re-attempt consistency, honest blocked-status
claims, blocker-documentation pixel counts.  Read-only; non-zero exit
on any violation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ALPHA = 8
H, W = 1536, 1024
CLASSES = ['transparent', 'hand_glove', 'gold_cuff', 'sleeve_coat',
           'lower_garment_leg', 'other']
R1B_OUT = ROOT / ('data/assets_v2/repair_candidates/'
                  'night03_patch2b_r1b')
STATUS_EXPECTED = 'NIGHT03_PATCH2B_R1B_R1_BLOCKED_BY_FROZEN_PLAN'

# byte-lock: the R1B delivery manifest file itself must not change
R1B_MANIFEST_SHA256 = None  # provided via --r1b-manifest-sha


class VerifyFail(Exception):
    pass


class Checker:
    def __init__(self):
        self.failures = []
        self.passes = 0

    def check(self, cond, label):
        if cond:
            self.passes += 1
        else:
            self.failures.append(label)
        return bool(cond)

    def result(self):
        return self.passes, self.failures


def sha256_path(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def runs_rebuild(rows_spec, h, w):
    m = np.zeros((h, w), bool)
    for row in rows_spec:
        y = int(row[0])
        for a, b in row[1:]:
            m[y, int(a):int(b) + 1] = True
    return m


def mirror(mask, w):
    out = np.zeros_like(mask)
    ys, xs = np.where(mask)
    out[ys, (w - 1) - xs] = True
    return out


def checker_bg(h, w, c=12):
    yy, xx = np.mgrid[0:h, 0:w]
    return np.where((((xx // c) + (yy // c)) % 2 == 0)[..., None],
                    200, 150).astype(np.float32)


def composite(master, background):
    af = master[..., 3:4].astype(np.float32) / 255.0
    return master[..., :3].astype(np.float32) * af + background * (1 - af)


def verify(r1a_src, r1b_src, r1b_r1_src, r1b_out, output, masters,
           r1b_manifest_sha):
    ck = Checker()

    # ---- byte-lock: R1B delivery --------------------------------------
    if r1b_manifest_sha is not None:
        if not ck.check(sha256_path(r1b_out / 'manifest.json') ==
                        r1b_manifest_sha,
                        'R1B delivery byte-lock (manifest SHA)'):
            raise VerifyFail('R1B delivery modified')
    else:
        print('WARN: --r1b-manifest-sha not provided; R1B byte-lock '
              'reduced to internal consistency')

    # ---- R1B-R1 source pins --------------------------------------------
    smf = json.loads((r1b_r1_src / 'source_manifest.json')
                     .read_text(encoding='utf-8'))
    for rel, expected in sorted(smf['files'].items()):
        if 'night03_patch2b_r1b_r1' in rel:
            fpath = r1b_r1_src / Path(rel).name
        else:
            fpath = r1a_src / Path(rel).name
        if not ck.check(sha256_path(fpath) == expected,
                        f'source pin {rel}'):
            raise VerifyFail(f'source tampered: {rel}')

    # ---- R1B candidate checks (inherited, against locked delivery) -----
    occ = json.loads((r1a_src / 'a16_occlusion_annotation.json')
                     .read_text(encoding='utf-8'))
    sem = np.full((H, W), -1, np.int16)
    for row in occ['rows']:
        y = int(row[0])
        for a, b, cn in row[1:]:
            sem[y, int(a):int(b) + 1] = CLASSES.index(cn)
    UNION = sem >= 0
    m_trans = UNION & (sem == 0)
    m_non = UNION & (sem > 0)
    recon = np.array(Image.open(
        r1b_r1_src / 'a16_reconstruction_source.png').convert('RGBA'))
    master16 = np.array(Image.open(
        masters / 'furina_v2_a16_work_focused.png').convert('RGBA'))

    # ---- R1B-R1 a16 candidate consistency -------------------------------
    cand_p = output / 'a16' / 'a16_candidate.png'
    if not ck.check(cand_p.exists(), 'r1b-r1 a16 candidate present'):
        raise VerifyFail('a16 candidate missing')
    cand16 = np.array(Image.open(cand_p).convert('RGBA'))
    ck.check(cand16.shape == (H, W, 4), 'a16 candidate shape')
    expected16 = master16.copy()
    expected16[m_trans] = [0, 0, 0, 0]
    expected16[m_non] = recon[m_non]
    ck.check(np.array_equal(cand16, expected16),
             'a16 candidate == master/plan/reconstruction composite')
    outside = (cand16 != master16).any(axis=-1) & ~UNION
    ck.check(not outside.any(),
             f'a16 outside-union diff == 0 ({int(outside.sum())})')
    counts = {c: int(((sem == i) & UNION).sum())
              for i, c in enumerate(CLASSES)}
    ck.check(sum(counts.values()) == 36124, 'a16 class sum == 36124')

    # ---- destination evidence (a01: pixel-exact rebuild) ----------------
    master = np.array(Image.open(
        masters / 'furina_v2_a01_stand_neutral_front.png')
        .convert('RGBA'))
    h, w = master.shape[:2]
    cand = np.array(Image.open(
        r1b_out / 'a01' / 'a01_candidate.png').convert('RGBA'))
    tdoc = json.loads((r1a_src / 'a01_tail_source.json')
                      .read_text(encoding='utf-8'))
    source = runs_rebuild(tdoc['rows'], h, w)
    dest = mirror(source, w)
    vis_dest = dest & (master[..., 3] <= ALPHA)
    bg = checker_bg(h, w)
    comp_m = composite(master, bg)
    comp_c = composite(cand, bg)
    x0, y0, x1, y1 = 694, 1040, 874, 1180
    a = Image.fromarray(comp_m[y0:y1, x0:x1].astype(np.uint8)).resize(
        ((x1 - x0) * 4, (y1 - y0) * 4), Image.NEAREST)
    b = Image.fromarray(comp_c[y0:y1, x0:x1].astype(np.uint8)).resize(
        ((x1 - x0) * 4, (y1 - y0) * 4), Image.NEAREST)
    cv = Image.new('RGB', (a.width * 2 + 8, a.height), (255, 0, 0))
    cv.paste(a, (0, 0))
    cv.paste(b, (a.width + 8, 0))
    got = np.array(Image.open(
        output / 'a01' / 'a01_dest_crop_tail_root_dest_400.png')
        .convert('RGB'))
    ck.check(np.array_equal(got, np.array(cv)),
             'a01 destination tail-root evidence pixel-exact rebuild')
    for asset in ('a01', 'a05'):
        for tag in ('tail_root_dest', 'staff_junction_dest',
                    'tail_tip_dest') if asset == 'a01' else \
                   ('bow_tail_root_dest', 'dress_edge_dest',
                    'tail_tip_dest'):
            for z in (200, 400, 800):
                ck.check((output / asset /
                          f'{asset}_dest_crop_{tag}_{z}.png').exists(),
                         f'{asset} dest crop {tag} {z} present')

    # ---- blocker documentation consistency ------------------------------
    gap1 = int(((UNION & (sem == 0))[1055:1080, 700:750]).sum())
    gap2 = int(((UNION & (sem == 0))[985:1015, 700:760]).sum())
    rep_p = output / 'NIGHT03_PATCH2B_R1B_R1_REPORT.md'
    if ck.check(rep_p.exists(), 'report present'):
        rep = rep_p.read_text(encoding='utf-8')
        rep_lines = set(rep.splitlines())
        exp1 = (f'- transparent-class px in y[1055,1080) x[700,750): '
                f'{gap1} (severs the fist/wrist from the cuff band; a '
                'natural gripping hand needs these rows as glove/skin)')
        exp2 = (f'- transparent-class px in y[985,1015) x[700,760): '
                f'{gap2} (severs the dome-reveal fingers from the fist '
                'below)')
        ck.check(exp1 in rep_lines,
                 f'report blocker gap1 exact line (== {gap1} px)')
        ck.check(exp2 in rep_lines,
                 f'report blocker gap2 exact line (== {gap2} px)')
        ck.check('R1A_REOPEN_REQUIRED = true' in rep_lines,
                 'report R1A_REOPEN_REQUIRED = true')

    rec_p = output / 'NIGHT03_PATCH2B_R1B_R1_RECEIPT.txt'
    if ck.check(rec_p.exists(), 'receipt present'):
        rec = rec_p.read_text(encoding='utf-8')
        kv = dict(re.findall(r'^([A-Z0-9_]+) = (.*)$', rec, re.MULTILINE))
        ck.check(kv.get('SELF_GATE_PASS') == 'false',
                 'receipt SELF_GATE_PASS = false (honest)')
        ck.check(kv.get('R1A_REOPEN_REQUIRED') == 'true',
                 'receipt R1A_REOPEN_REQUIRED = true')
        ck.check(kv.get('A16_STATUS') ==
                 'FAIL_FROZEN_PLAN_INSUFFICIENT',
                 'receipt A16_STATUS')
        ck.check(kv.get('A01_DEST_EVIDENCE_FILES') == '9',
                 'receipt a01 dest evidence count')
        ck.check(kv.get('A05_DEST_EVIDENCE_FILES') == '9',
                 'receipt a05 dest evidence count')

    # ---- manifest ---------------------------------------------------------
    mf_p = output / 'manifest.json'
    if ck.check(mf_p.exists(), 'manifest present'):
        mf = json.loads(mf_p.read_text(encoding='utf-8'))
        actual = {p.relative_to(output).as_posix(): sha256_path(p)
                  for p in sorted(output.rglob('*'))
                  if p.is_file() and p.name != 'manifest.json'}
        ck.check(set(mf) == set(actual),
                 'manifest covers exactly the delivered files')
        bad = [k for k in mf if mf.get(k) != actual.get(k)]
        ck.check(not bad, f'manifest hashes match (bad: {bad[:3]})')

    return ck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--r1a-src', type=Path,
                    default=ROOT / 'data/assets_v2/annotation_sources/'
                                   'night03_patch2b_r1a_r6')
    ap.add_argument('--r1b-src', type=Path,
                    default=ROOT / 'data/assets_v2/annotation_sources/'
                                   'night03_patch2b_r1b')
    ap.add_argument('--r1b-r1-src', type=Path,
                    default=ROOT / 'data/assets_v2/annotation_sources/'
                                   'night03_patch2b_r1b_r1')
    ap.add_argument('--output', type=Path,
                    default=ROOT / 'data/assets_v2/repair_candidates/'
                                   'night03_patch2b_r1b_r1')
    ap.add_argument('--r1b-out', type=Path,
                    default=R1B_OUT)
    ap.add_argument('--masters', type=Path,
                    default=ROOT / 'data/assets_v2/masters')
    ap.add_argument('--r1b-manifest-sha', type=str, default=None)
    args = ap.parse_args()
    try:
        ck = verify(args.r1a_src, args.r1b_src, args.r1b_r1_src,
                    args.r1b_out, args.output, args.masters,
                    args.r1b_manifest_sha)
    except VerifyFail as e:
        print(f'VERIFIER FAIL: {e}')
        return 1
    except Exception as e:
        print(f'VERIFIER FAIL (unexpected): {type(e).__name__}: {e}')
        return 1
    passes, failures = ck.result()
    for f in failures:
        print(f'FAIL: {f}')
    ok = not failures
    print(f'VERIFIER {"PASS" if ok else "FAIL"}: {passes} checks passed, '
          f'{len(failures)} failed')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
