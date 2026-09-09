# NIGHT03_PATCH2B_R1A_REPORT — mask / reconstruction-plan freeze

- builder: GLM/ZCode; reviewer: ChatGPT Codex (sole Reviewer)
- task_id: NIGHT03_RECOVERY_PATCH2B_R1A (base 23f6eb1)
- scope: a01/a05/a16 mask + reconstruction-plan freeze ONLY
- zero candidates, zero generation calls, masters read-only
- patch 2B candidates retained solely as manual counter-examples
  (not used as pixel/mask/diff inputs anywhere in this freeze)

## a16 prop-union post-removal partition (program-generated)

- prop union (R6A-R4 primitives, bit-exact): 36124 px
- transparent_after_removal: 33161 px
- character_reconstruction: 2963 px
- partition equation: transparent ∪ reconstruction = prop_union,
  disjoint, complete (fail-closed asserts in the freeze script)
- sub-items: hand/glove 1451, gold cuff 0,
  sleeve/coat 1500, lower garment/leg 12,
  other 0
- the frozen reconstruction masks will later receive opaque
  character content written by the repair pass (never cleared to
  transparent); that write happens in a later round

## a01 / a05 tail plan (program-generated)

| metric | a01 | a05 |
|---|---:|---:|
| tail_source_complete px | 29183 | 67616 |
| old tail source px | 24368 | 46616 |
| sprite growth (outline+AA) px | 4815 | 21000 |
| tail_destination px | 26400 | 34243 |
| mirror_source_outside_tail | 0 | 0 |
| seam mapped px | 681 | 0 |
| seam residual (kept master) px | 1372 | 0 |
| cleanup px | 2 | 465 |

## a01/a05 residual ledger (every visible corridor px attributed)

| category | a01 px | a05 px |
|---|---:|---:|
| background | 1017146 | 996916 |
| tail_removed | 29183 | 67616 |
| costume_kept | 138904 | 143974 |
| identity_kept | 320071 | 291901 |
| props_kept | 2578 | 6378 |
| character_kept | 64982 | 66079 |

## determinism

- double run = byte-identical outputs (all mask PNG/NPY/JSON)

STATUS = READY_FOR_NIGHT03_PATCH2B_R1A_PLAN_REVIEW
