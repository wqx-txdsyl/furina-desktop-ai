# NIGHT03_PATCH2A_R6AR1 — a16 Ownership Gate (Builder report)

- MASK_PLAN_SHA256 = a03ada6a76edc8d203f4f7439fcb01fc99cfde7cdba640a8832c556fe221b8fa
- OWNERSHIP_SOURCE_SHA256 = 4c7e639513b7f037854b047862665259636601e3616b81665fb2dc8beec183c3
- OWNERSHIP_COMPLETE = true (unclassified_visible_pixels = 0)
- LABEL0_BACKGROUND_ONLY = true (labeled_background_pixels = 0)
- PROTECTED_OTHER_CHARACTER = explicit label 7 (123778 px)
- STATIC_SOURCE_INDEPENDENT = true (freeze script reads the committed scanline RLE JSON read-only; it never generates or modifies it)
- CANE_CHAIR = hand-traced per-row contours along the real prop outlines; no wide rectangles, no coarse polygons spanning the character; the ribbon tied to the blade is part of the cane assembly (reviewer: please confirm this semantic call)
- ISOLATED_CUTOUT_VALID = true (every cutout non-checker pixel count equals its label census)
- OVERLAY_VALID = true (label/value iteration verified)
- REPRODUCIBLE = fixed PNG params, sorted iteration, no timestamps; double-run byte-identical in the recorded environment

## Ownership census (px)

| label | px |
|---|---:|
| background | 1120309 |
| protected_hair | 145975 |
| protected_quill_paper | 4488 |
| protected_glove_gold_cuff | 9181 |
| protected_costume | 119429 |
| remove_cane | 35009 |
| remove_chair | 14695 |
| protected_other_character | 123778 |

## Cross-check vs master

- visible (alpha>8) px: 452555
- labelled px (labels 1..7): 452555
- difference: 0

STATUS = READY_FOR_NIGHT03_PATCH2A_R6AR1_OWNERSHIP_REVIEW
