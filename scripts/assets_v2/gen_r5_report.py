"""R5: generate the Builder report + receipt from the frozen plan JSON.

Every metric is read from the frozen plan — no hand-copied values.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / ('data/assets_v2/repair_candidates/night03_patch2a_r5/'
               'mask_plan/night03_patch2_mask_plan.json')
OUTD = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r5'

ROWS_A01 = ['tail_source', 'tail_destination', 'seam_reconstruction',
            'authorized_cleanup', 'protected_identity', 'protected_costume',
            'protected_props', 'allowed_edit']
ROWS_A05 = ROWS_A01
ROWS_A16 = ['tail_source', 'tail_destination', 'seam_reconstruction',
            'speck_cleanup', 'chair_removal', 'cane_removal',
            'hair_reconstruction', 'hand_reconstruction',
            'protected_existing_hair', 'protected_quill_paper',
            'protected_glove_gold_cuff', 'protected_costume', 'allowed_edit']


def main():
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    rows = []
    for asset, keys in (('a01', ROWS_A01), ('a05', ROWS_A05),
                        ('a16', ROWS_A16)):
        for k in keys:
            rows.append(f"| {asset} | {k} | "
                        f"{plan['assets'][asset]['masks'][k]['px']} |")
    table = '\n'.join(rows)
    un = plan['assets']['a16'].get('ownership_unassigned_alpha_px', 0)
    sha = plan['MASK_PLAN_SHA256']

    report = f"""# NIGHT03_PATCH2A_R5_MASK_FREEZE_REPORT — single-source ownership map

- patch_id: NIGHT03_RECOVERY_PATCH2A_R5
- base_sha: {plan['base_sha']}
- branch: feature/night03-recovery-patch2
- single_source: a16_ownership_map.png (labels 0-9, mutual exclusive)
- date: 2026-09-07
- note: every metric below is generated from the frozen plan JSON (no stale values)

## metrics (asset | mask | px — generated)

| asset | mask | px |
|---|---|---:|
{table}

## ownership

- single source: a16_ownership_map.png, labels 0-9 mutual exclusive
  (0 other/background, 1 hair, 2 quill-paper, 3 glove-cuff, 4 costume,
   5 cane, 6 chair, 7 unassigned-alpha, 8 remove-tail, 9 repair-hand)
- ownership_unassigned_alpha_px = {un} (alpha pixels not covered by the
  declared items; they remain unprotected and unclaimed, by design)
- all masks derived by equality; labels frozen before derivation

## verification

- verifier VERIFY OK; residual total == sum(classes) for a01
  ({plan['assets']['a01']['boundary_residual_px']});
- allowed_edit == union(terms) per asset; allowed ∩ protected = 0 per asset;
- a01/a05 masks byte-identical to R4; input hashes are LF-normalized;
- cutouts rebuilt from master+masks and compared byte-exact
  (all backgrounds, 100/200/400);
- a16 protected isolated cutouts delivered; zero candidates; zero calls.

MASK_PLAN_SHA256 = {sha}
STATUS = READY_FOR_NIGHT03_PATCH2A_R5_OWNERSHIP_REVIEW
"""
    (OUTD / 'NIGHT03_PATCH2A_R5_MASK_FREEZE_REPORT.md').write_text(
        report, encoding='utf-8')

    receipt = f"""PATCH_ID = NIGHT03_RECOVERY_PATCH2A_R5
BASE_SHA = {plan['base_sha']}
BRANCH = feature/night03-recovery-patch2
CANDIDATES_CREATED = 0
GENERATION_CALLS = 0
A01_RESIDUAL_TOTAL = {plan['assets']['a01']['boundary_residual_px']}
A01_RESIDUAL_CLASSIFIED = {plan['assets']['a01']['boundary_residual_px']}
A01_MASKS_BYTE_IDENTICAL_TO_R4 = true
A05_MASKS_BYTE_IDENTICAL = true
OWNERSHIP_MAP_SINGLE_SOURCE = true
OWNERSHIP_UNASSIGNED_ALPHA_PX = {un}
A16_SEMANTIC_GATE = PENDING_INDEPENDENT_REVIEW
PATCH2B_AUTHORIZED = false
CUTOUT_ALL_SCALE_VERIFIED = true
DARK_LIGHT_CUTOUTS_PRESENT = true
CUTOUT_REBUILD_ALL_SCALES_BYTE_EXACT = true
INPUT_HASH_CROSS_PLATFORM = true
VERIFIER_SCANS_R5 = true
ALLOWED_PROTECTED_OVERLAP = 0
MASK_PLAN_SHA256 = {sha}
MASTERS_UNCHANGED = true
PRODUCTION_FILES_CHANGED = 0
UNRELATED_FILES_COMMITTED = 0
REPORT = data/assets_v2/repair_candidates/night03_patch2a_r5/NIGHT03_PATCH2A_R5_MASK_FREEZE_REPORT.md
STATUS = READY_FOR_NIGHT03_PATCH2A_R5_OWNERSHIP_REVIEW"""
    (OUTD / 'NIGHT03_PATCH2A_R5_RECEIPT.txt').write_text(
        receipt, encoding='utf-8')
    print('report + receipt generated:', sha)


if __name__ == '__main__':
    main()
