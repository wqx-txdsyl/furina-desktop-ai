# NIGHT03_PATCH2B_R1B_R1 — a16 re-attempt + evidence fix

- a01 destination evidence: a01/a01_dest_crop_tail_root_dest_400.png
- a01 destination evidence: a01/a01_dest_crop_staff_junction_dest_400.png
- a01 destination evidence: a01/a01_dest_crop_tail_tip_dest_400.png
- a05 destination evidence: a05/a05_dest_crop_bow_tail_root_dest_400.png
- a05 destination evidence: a05/a05_dest_crop_dress_edge_dest_400.png
- a05 destination evidence: a05/a05_dest_crop_tail_tip_dest_400.png
## frozen-plan hand blocker (pixel-exact)
- transparent-class px in y[1055,1080) x[700,750): 546 (severs the fist/wrist from the cuff band; a natural gripping hand needs these rows as glove/skin)
- transparent-class px in y[985,1015) x[700,760): 893 (severs the dome-reveal fingers from the fist below)
- per task book: mask expansion / semantic reclassification is forbidden for the Builder; R1A_REOPEN_REQUIRED = true

## honest self-gate
- a01/a05: candidates untouched (byte-locked); destination-side evidence now provided
- a16: best-effort reconstruction inside the frozen union; the hand region cannot form a natural structure because the frozen transparent rows sever the wrist (see blocker documentation)

STATUS = NIGHT03_PATCH2B_R1B_R1_BLOCKED_BY_FROZEN_PLAN
R1A_REOPEN_REQUIRED = true
