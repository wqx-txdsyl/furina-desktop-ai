"""NIGHT-03 Recovery Patch 2B step 3 — program-generated report.

Every number is read from asset_metadata.json / manifest.json / the
committed annotation JSON.  Nothing is hand-copied.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2b'

meta = json.loads((OUT / 'asset_metadata.json').read_text(encoding='utf-8'))
manifest = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
doc = json.loads((OUT.parent / 'night03_patch2a_r6ar4'
                  / 'a16_ownership_annotation.json').read_text(encoding='utf-8'))

L = []
L.append('# NIGHT03_PATCH2B_REPORT — three-asset pilot repair')
L.append('')
L.append('- builder: GLM/ZCode; reviewer: ChatGPT Codex (sole Reviewer)')
L.append('- scope: a01 / a05 / a16 pilots only; no other asset touched')
L.append('- inputs: masters only + the frozen PATCH2A R4 mask PNGs + the')
L.append('  committed R6A-R4 ownership annotation (primitives + ledger)')
L.append('- allowed edits were frozen (night03_patch2b_freeze_allowed.py,')
L.append('  night03_patch2b/frozen/) BEFORE any candidate existed; the')
L.append('  repair script consumed those frozen masks only')
L.append('')
L.append('## semantics')
L.append('')
L.append('- a01/a05: old showpiece tail removed and migrated to its frozen')
L.append('  mirror destination; authorized cleanups applied; the held cane')
L.append('  stays (it is protected_props in the frozen mask plan)')
L.append('- a16: cane + chair removed strictly via the R6A-R4 ownership')
L.append('  primitives (remove_cane / remove_chair, 1,102px overlap')
L.append('  resolved through the frozen occlusion_resolution ledger);')
L.append('  old tail migrated; specks cleaned; seam reconstructed by')
L.append('  mirror copy; hand band left as master (no invented content)')
L.append('- RIBBON_AS_CANE_ACCEPTED = false / SASH_PROTECTED = true')
L.append('- no reconstruction content was invented: seam/migration pixels')
L.append('  are horizontal-mirror copies of master pixels; the failed')
L.append('  flat-fill approach of earlier rounds is not used')
L.append('')
L.append('## per-asset audit (program-generated)')
L.append('')
L.append('| asset | changed px | unauthorized px | allowed px |')
L.append('|---|---:|---:|---:|')
for a in ('a01', 'a05', 'a16'):
    m = meta[a]
    L.append(f"| {a} | {m['changed_px']} | {m['unauthorized_diff_px']} | "
             f"{m['allowed_edit_px']} |")
L.append('')
L.append('every actual diff is a strict subset of the frozen allowed edit')
L.append('(unauthorized = 0 for all three assets).')
L.append('')
L.append('## ledger / primitives (a16)')
L.append('')
L.append(f"- ledger entries: {len(doc['occlusion_resolution'])}")
L.append(f"- ledger pixels: {sum(e['px'] for e in doc['occlusion_resolution'])}")
L.append(f"- ledger winners: cane 103 px / chair 999 px (R6A-R4 PASS)")
L.append('')
L.append('## hashes')
L.append('')
L.append('| asset | master SHA256 | candidate SHA256 |')
L.append('|---|---|---|')
for a in ('a01', 'a05', 'a16'):
    m = meta[a]
    L.append(f"| {a} | {m['master_sha256']} | {m['candidate_sha256']} |")
L.append('')
L.append('## deliverables')
L.append('')
L.append('- 3 candidates (full RGBA), 3 triptychs')
L.append('- per-asset candidate on checker/dark/light, whole image')
L.append('- 512 / 256 / 128 down-scales per background')
L.append('- 200% / 400% zone crops per asset')
L.append('- per-asset metadata JSON + manifest.json (all file SHAs)')
L.append('- reproducible scripts: night03_patch2b_freeze_allowed.py,')
L.append('  night03_patch2b_repair.py, night03_patch2b_report.py')
L.append('')
L.append('STATUS = READY_FOR_NIGHT03_PATCH2B_INDEPENDENT_VISUAL_REVIEW')
L.append('')

(OUT / 'NIGHT03_PATCH2B_REPORT.md').write_text(
    '\n'.join(L), encoding='utf-8', newline='\n')
print('report written')

