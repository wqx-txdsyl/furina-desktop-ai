# NIGHT03_PATCH2A_R6AR3 — a16 Ownership Gate (Builder report)

- MASK_PLAN_SHA256 = 96b4e809fdca9277e785d21445511c1336e087c1e6d515cee5bbfbea82dcbf56
- OWNERSHIP_SOURCE_SHA256 = 496fd4eb6c74da339788c234bc811feebdfacf51976c3717a9f2fafc4c6fd837
- OWNERSHIP_COMPLETE = true (unclassified_visible_pixels = 0)
- LABEL0_BACKGROUND_ONLY = true (labeled_background_pixels = 0)
- PROTECTED_OTHER_CHARACTER = explicit label 7 (62723 px)
- STATIC_SOURCE_INDEPENDENT = true (freeze script reads the committed scanline RLE JSON read-only; it never generates or modifies it; the annotate tool uses NO computed catch-all — explicit hand-placed regions cover every visible pixel and the tool fails otherwise)
- CANE_CHAIR = hand-traced per-row contours along the real prop outlines; no wide rectangles, no coarse polygons spanning the character; cane/chair primitive overlap is resolved through the frozen occlusion_resolution ledger carried inside the JSON (bbox, px, winner, rationale, explicit pixel list) and every ledger pixel is re-verified above
- RIBBON_AS_CANE_ACCEPTED = false / SASH_PROTECTED = true (sash and white cloth are protected_costume; the cane passes in front of them)
- ISOLATED_CUTOUT_VALID = true (every cutout non-checker pixel count equals its label census)
- OVERLAY_VALID = true (label/value iteration verified)
- REPRODUCIBLE = fixed PNG params, sorted iteration, no timestamps; double-run byte-identical in the recorded environment

## Ownership census (px)

| label | px |
|---|---:|
| background | 1120309 |
| protected_hair | 204718 |
| protected_quill_paper | 22584 |
| protected_glove_gold_cuff | 9451 |
| protected_costume | 116955 |
| remove_cane | 22514 |
| remove_chair | 13610 |
| protected_other_character | 62723 |

## Cross-check vs master

- visible (alpha>8) px: 452555
- labelled px (labels 1..7): 452555
- difference: 0

STATUS = READY_FOR_NIGHT03_PATCH2A_R6AR3_OWNERSHIP_REVIEW
