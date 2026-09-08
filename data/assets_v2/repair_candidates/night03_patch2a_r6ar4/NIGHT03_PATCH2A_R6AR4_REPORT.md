# NIGHT03_PATCH2A_R6AR4 — a16 Ownership Gate (Builder report)

- MASK_PLAN_SHA256 = 21012a5179594f3711121dff4df44fa49d709831e7228ad9c5dc117fff0640aa
- OWNERSHIP_SOURCE_SHA256 = 95e6d150d3d507569dd2749ea00de8754a0a9f76d5525b35998d66cb594fc0f9
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
| remove_cane | 21515 |
| remove_chair | 14609 |
| protected_other_character | 62723 |

## Cross-check vs master

- visible (alpha>8) px: 452555
- labelled px (labels 1..7): 452555
- difference: 0

STATUS = READY_FOR_NIGHT03_PATCH2A_R6AR4_OWNERSHIP_REVIEW
