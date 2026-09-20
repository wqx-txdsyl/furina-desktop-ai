# NIGHT03_PATCH2B_R1B — final candidates

## a01
- tail_source_px: 24349
- destination_px: 24349
- visible_destination_px: 23809
- underlay_px: 540
- actual_diff_px: 48158
- candidate_sha256: e11ae1491ce26ebcdfaaf97b516c0fa675906d883c30661e02ecabc5b37cf0d6
- ACTUAL_DIFF == TAIL_SOURCE ∪ VISIBLE_DESTINATION: True
- UNDERLAY_DIFF: 0 (False == preserved)

## a05
- tail_source_px: 49286
- destination_px: 49286
- visible_destination_px: 26644
- underlay_px: 22642
- actual_diff_px: 75930
- candidate_sha256: 8e99885e5ce388e2e752991364010f43d6c36713ebb22e1db86970f19e6b6325
- ACTUAL_DIFF == TAIL_SOURCE ∪ VISIBLE_DESTINATION: True
- UNDERLAY_DIFF: 0 (False == preserved)

## a16
- class transparent: 24565
- class hand_glove: 645
- class gold_cuff: 327
- class sleeve_coat: 5849
- class lower_garment_leg: 4738
- class other: 0
- write_coverage_px: 36124
- outside_union_diff_px: 0
- transparent_all_zero_rgba: True
- nontransparent_alpha_255: True


## build identity and inputs
- BASE_SHA: de2532baca88aef4d7568664a912d859ef62e307
- FINAL_HEAD: recorded in the delivery commit message (the report is part of that commit and cannot embed its own hash)
- master a01 SHA256: c3ed763c7eed3bfc620e4847e0028e5c6eae83a8170f41a1152915e7885172a6
- master a05 SHA256: 8ddcfde186fb352ce32381543273902295ceeb3fd3f3db6b064141fcf5199a77
- master a16 SHA256: f4997917453d6a541a08d021132ecad3bd8cffb63773833d31bdcde805d099ab
- R1A-R6 source pins: see source_manifest.json in data/assets_v2/annotation_sources/night03_patch2b_r1b (verified before any parse/use)

## candidate SHA256
- a01_candidate: e11ae1491ce26ebcdfaaf97b516c0fa675906d883c30661e02ecabc5b37cf0d6
- a05_candidate: 8e99885e5ce388e2e752991364010f43d6c36713ebb22e1db86970f19e6b6325
- a16_candidate: 259af2daae14668ef0d64ed795e09e6c6b351e24ceacd83a79437c25b4d200d5

## generation budget
- GENERATION_CALLS: 0 (a01/a05 deterministic by rule; a16 authored by deterministic hand-tuned local reconstruction, no image-generation call used)
- authoring ledger: annotation_sources/night03_patch2b_r1b/generation_ledger.json

## visual self-gate matrix (Builder self-check; final visual judgement rests with the sole Reviewer)
- [PASS] a01 tail root / cane junction / tail tip @2x-8x
- [PASS] a01 checker/light/dark full + 512/256/128
- [PASS] a05 bow/tail root / dress edge / tail tip @2x-8x
- [PASS] a05 checker/light/dark full + 512/256/128
- [PASS] a16 hand/cuff/seat/blade/lower garment @2x-8x
- [PASS] a16 no cane/chair residue
- [PASS] a16 glove reads as fingers, cuff reads as gold band
- [PASS] a16 coat tail / seat garment continuation
- [PASS] a16 no flat blocks / black columns / white holes
- [PASS] a16 512/256/128 still readable
- [PASS] no double tails / old-tail ghosts (a01, a05)
- [PASS] no mirrored cane/bow/dress content (a01, a05)

## tests and reproduction
- scripts/assets_v2/night03_patch2b_r1b_verify_candidates.py: PASS (independent, subprocess)
- tests/agent/work/test_night03_patch2b_r1b_candidates.py: 1 positive + 18 real mutations PASS; fresh-checkout byte reproducibility PASS (archive/extract HEAD, delete output, single-entry rebuild, byte-identical twice)
- R1A-R6 suite re-run: 29/29 PASS
- double build run: byte-identical

## remaining risks (no hiding)
- a16 reconstruction is a partial reveal: content continues only inside the frozen union slivers; at 8x the strip ends are visible as diagonal cuts where the frozen plan bounds the reveal
- a16 finger/cuff detail is stylised chibi-level, not full-art-level; final visual judgement rests with the sole Reviewer
- a05 semantic geometry exception (if triggered) is recorded, not corrected

## files
- complete delivered file list: manifest.json (this build, written LAST)

STATUS = READY_FOR_NIGHT03_PATCH2B_R1B_INDEPENDENT_VISUAL_REVIEW
