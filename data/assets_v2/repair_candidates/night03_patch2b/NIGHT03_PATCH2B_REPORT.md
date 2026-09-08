# NIGHT03_PATCH2B_REPORT — three-asset pilot repair

- builder: GLM/ZCode; reviewer: ChatGPT Codex (sole Reviewer)
- scope: a01 / a05 / a16 pilots only; no other asset touched
- inputs: masters only + the frozen PATCH2A R4 mask PNGs + the
  committed R6A-R4 ownership annotation (primitives + ledger)
- allowed edits were frozen (night03_patch2b_freeze_allowed.py,
  night03_patch2b/frozen/) BEFORE any candidate existed; the
  repair script consumed those frozen masks only

## semantics

- a01/a05: old showpiece tail removed and migrated to its frozen
  mirror destination; authorized cleanups applied; the held cane
  stays (it is protected_props in the frozen mask plan)
- a16: cane + chair removed strictly via the R6A-R4 ownership
  primitives (remove_cane / remove_chair, 1,102px overlap
  resolved through the frozen occlusion_resolution ledger);
  old tail migrated; specks cleaned; seam reconstructed by
  mirror copy; hand band left as master (no invented content)
- RIBBON_AS_CANE_ACCEPTED = false / SASH_PROTECTED = true
- no reconstruction content was invented: seam/migration pixels
  are horizontal-mirror copies of master pixels; the failed
  flat-fill approach of earlier rounds is not used

## per-asset audit (program-generated)

| asset | changed px | unauthorized px | allowed px |
|---|---:|---:|---:|
| a01 | 49596 | 0 | 49941 |
| a05 | 72590 | 0 | 72590 |
| a16 | 78060 | 0 | 78097 |

every actual diff is a strict subset of the frozen allowed edit
(unauthorized = 0 for all three assets).

## ledger / primitives (a16)

- ledger entries: 32
- ledger pixels: 1102
- ledger winners: cane 103 px / chair 999 px (R6A-R4 PASS)

## hashes

| asset | master SHA256 | candidate SHA256 |
|---|---|---|
| a01 | c3ed763c7eed3bfc620e4847e0028e5c6eae83a8170f41a1152915e7885172a6 | cc71e9d3545793c4b071eff273c5cfdcb6f80b4d651c6136c191fff06657ab7f |
| a05 | 8ddcfde186fb352ce32381543273902295ceeb3fd3f3db6b064141fcf5199a77 | 511f268be714f53c4cf10926712c826048388b4ceffb18bdf3350b1ef60f35a5 |
| a16 | f4997917453d6a541a08d021132ecad3bd8cffb63773833d31bdcde805d099ab | 580af55984d493cfed10aa23ef5f3a8b0f2f72fe0a69fdfedd57efcb653f59c1 |

## deliverables

- 3 candidates (full RGBA), 3 triptychs
- per-asset candidate on checker/dark/light, whole image
- 512 / 256 / 128 down-scales per background
- 200% / 400% zone crops per asset
- per-asset metadata JSON + manifest.json (all file SHAs)
- reproducible scripts: night03_patch2b_freeze_allowed.py,
  night03_patch2b_repair.py, night03_patch2b_report.py

STATUS = READY_FOR_NIGHT03_PATCH2B_INDEPENDENT_VISUAL_REVIEW
