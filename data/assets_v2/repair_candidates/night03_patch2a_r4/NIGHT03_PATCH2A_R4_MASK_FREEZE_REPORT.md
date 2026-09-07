# NIGHT03_PATCH2A_R4_MASK_FREEZE_REPORT — Complete Frozen Semantic Mask Gate

- patch_id: NIGHT03_RECOVERY_PATCH2A_R4
- base_sha: 2c1db8f5bb43d6edb7067f34a565af9fa3e49f15
- branch: feature/night03-recovery-patch2
- builder: GLM-5.3-Flash / ZCode (task book NIGHT03 Recovery Patch 2A R4; Reviewer: ChatGPT Codex)
- date: 2026-09-07
- note: every metric below is generated from the frozen plan JSON (no stale values)

## metrics (asset | mask | px — generated)

| asset | mask | px |
|---|---|---:|
| a01 | tail_source | 24368 |
| a01 | tail_destination | 23690 |
| a01 | seam_reconstruction | 2053 |
| a01 | authorized_cleanup | 2 |
| a01 | protected_identity | 320071 |
| a01 | protected_costume | 203199 |
| a01 | protected_props | 2578 |
| a01 | allowed_edit | 49941 |
| a05 | tail_source | 46616 |
| a05 | tail_destination | 25509 |
| a05 | seam_reconstruction | 0 |
| a05 | authorized_cleanup | 465 |
| a05 | protected_identity | 291901 |
| a05 | protected_costume | 170165 |
| a05 | protected_props | 6378 |
| a05 | allowed_edit | 72590 |
| a16 | tail_source | 30231 |
| a16 | tail_destination | 10801 |
| a16 | seam_reconstruction | 769 |
| a16 | speck_cleanup | 135 |
| a16 | chair_removal | 12560 |
| a16 | cane_removal | 13106 |
| a16 | hair_reconstruction | 0 |
| a16 | hand_reconstruction | 1013 |
| a16 | protected_existing_hair | 62279 |
| a16 | protected_quill_paper | 8802 |
| a16 | protected_glove_gold_cuff | 15733 |
| a16 | protected_costume | 95798 |
| a16 | allowed_edit | 66550 |

## verification

- verifier VERIFY OK; residual total == sum(classes) for a01 (1291);
- allowed_edit == union(terms) per asset; allowed ∩ protected = 0 per asset;
- a01/a05 masks byte-identical to R3; input hashes are LF-normalized;
- cutouts rebuilt from master+masks and compared byte-exact (all backgrounds, 100/200/400);
- a16 protected isolated cutouts delivered; zero candidates; zero generation calls.

MASK_PLAN_SHA256 = a9a3e13f96988d517c2d686d62b19bb029aa29e7c224ff9443113cc1ff05fb66
STATUS = READY_FOR_NIGHT03_PATCH2A_R4_REVIEW
