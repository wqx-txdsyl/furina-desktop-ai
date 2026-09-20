# NIGHT03_PATCH2B_R1A_R7 — hand/cuff connectivity semantic freeze

## acceptance equations
- NEW_PROP_UNION == OLD_PROP_UNION: True
- PROP_UNION px: 36124
- CHANGED_PIXELS: 409 (all inside REVIEW_ROI)
- LEDGER_PIXELS: 409
- OUTSIDE_REVIEW_ROI_DIFF: 0
- CLASS_SUM: 36124
- UNKNOWN/DUPLICATE/LABELED_OUTSIDE: 0

## class census (unchanged from R1A-R6)
- class transparent: 24156
- class hand_glove: 1030
- class gold_cuff: 351
- class sleeve_coat: 5849
- class lower_garment_leg: 4738
- class other: 0

## diagnostic windows (transparent px inside window)
- LOWER outer y[1055,1080) x[700,750): 173 transparent / 844 union
- LOWER inner y[1060,1075) x[704,746): 87 transparent / 492 union
- UPPER y[985,1015) x[700,760): 857 transparent / 1039 union
- these are diagnostics of what remains transparent; the hand connectivity re-adjudication moved 385 px to hand_glove and 24 px to gold_cuff (reasons: HAND_CONNECTIVITY / CUFF_BOUNDARY)

## pins (byte-identical, enforced pre-parse)
- r7_annotation: 12cc7997dba06518c348493d063f4d7bd46ec2f315e883a91a07820d344bed1a
- r7_hand_ledger: 326dafd54e291dad6bb0d261924bb678530e0ee6e43953b674674535e1729c2f
- r6_annotation: 0274181f6bce18ba3fad25f259a5e76e73a2b3a1bb5fc03062e44b5ff59d7de8
- r1b_manifest: 8443acb89ada5fc3686e12476d57971e674147150bcb6a6a8401ae3a60f7e37d
- r1b_r1_manifest: db2751428b05d52fb31c8a9ee5ca3f86268d35cbe8dde4a3b579183a154e4561
- fixed_png_module: ff32d541d8ceabdef656f4527d9ae605eec5c41af89e383569997e65a3648a99
- master_a16: f4997917453d6a541a08d021132ecad3bd8cffb63773833d31bdcde805d099ab

sources: data/assets_v2/annotation_sources/night03_patch2b_r1a_r7/ (static, read-only)

STATUS = READY_FOR_NIGHT03_PATCH2B_R1A_R7_PLAN_REVIEW
