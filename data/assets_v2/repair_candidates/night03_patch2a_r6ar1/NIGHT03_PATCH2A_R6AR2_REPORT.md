# NIGHT03_PATCH2A_R6AR2 — a16 Ownership Gate (Builder report)

- MASK_PLAN_SHA256 = 43c8ddb763bc83dc225d4d211dd46f413f82ad8cb16dc15474ee5a6eb7f42199
- OWNERSHIP_SOURCE_SHA256 = 52334b495edebdc67defb6485f6c1d48a3115e684f096cb2bc69a72411f7e26f
- OWNERSHIP_COMPLETE = true (unclassified_visible_pixels = 0)
- LABEL0_BACKGROUND_ONLY = true (labeled_background_pixels = 0)
- PROTECTED_OTHER_CHARACTER = explicit label 7 (62721 px)
- STATIC_SOURCE_INDEPENDENT = true (freeze script reads the committed scanline RLE JSON read-only; it never generates or modifies it; the annotate tool uses NO computed catch-all — explicit hand-placed regions cover every visible pixel and the tool fails otherwise)
- CANE_CHAIR = hand-traced per-row contours along the real prop outlines; no wide rectangles, no coarse polygons spanning the character; the ribbon tied to the blade is part of the cane assembly (reviewer: please confirm this semantic call)
- ISOLATED_CUTOUT_VALID = true (every cutout non-checker pixel count equals its label census)
- OVERLAY_VALID = true (label/value iteration verified)
- REPRODUCIBLE = fixed PNG params, sorted iteration, no timestamps; double-run byte-identical in the recorded environment

## Ownership census (px)

| label | px |
|---|---:|
| background | 1120309 |
| protected_hair | 204760 |
| protected_quill_paper | 22584 |
| protected_glove_gold_cuff | 9451 |
| protected_costume | 116933 |
| remove_cane | 23746 |
| remove_chair | 12360 |
| protected_other_character | 62721 |

## Cross-check vs master

- visible (alpha>8) px: 452555
- labelled px (labels 1..7): 452555
- difference: 0

STATUS = READY_FOR_NIGHT03_PATCH2A_R6AR2_OWNERSHIP_REVIEW
