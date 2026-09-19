# NIGHT03_PATCH2B_R1A_R4 — mask/plan freeze

## a01 tail (raw gates pre-validated, zero clipping)
- tail_source_px: 24349
- destination_px: 24349
- visible_destination_px: 23809
- underlay_px: 540
- underlay_protected_px: 0
- raw_outside_visible: 0
- raw_protected_overlap: 0
- mirror_source_outside_tail: 0

## a05 tail (raw gates pre-validated, zero clipping)
- tail_source_px: 49286
- destination_px: 49286
- visible_destination_px: 26644
- underlay_px: 22642
- underlay_protected_px: 22582
- raw_outside_visible: 0
- raw_protected_overlap: 0
- mirror_source_outside_tail: 0

## a16 occlusion (static source, exact cover)
- prop_union_px: 36124
- class transparent: 24565
- class hand_glove: 645
- class gold_cuff: 327
- class sleeve_coat: 5849
- class lower_garment_leg: 4738
- class other: 0
- labeled_outside_prop_union: 0
- duplicate_pixels: 0
- unknown_class_pixels: 0
- off-canvas px counted as transparent: 0

## gates
- raw_source ∩ outside_visible = 0 (a01, a05)
- raw_source ∩ protected = 0 (a01, a05)
- mirror_source_outside_tail = 0 (a01, a05)
- visible_destination ∩ protected = 0 (a01, a05)
- a16 labeled == R6A-R4 prop union == 36124

sources: data/assets_v2/annotation_sources/night03_patch2b_r1a_r4/ (static, read-only, never created or modified by this freeze)

STATUS = READY_FOR_NIGHT03_PATCH2B_R1A_R4_PLAN_REVIEW
