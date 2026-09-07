# NIGHT03_PATCH2A_R5_MASK_FREEZE_REPORT — single-source ownership map

- patch_id: NIGHT03_RECOVERY_PATCH2A_R5
- base_sha: 826a70141c212fd2b6a833d0fbb7f912cd1701f2
- branch: feature/night03-recovery-patch2
- single_source: a16_ownership_map.png (labels 0-9, mutual exclusive)
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
| a16 | cane_removal | 11041 |
| a16 | hair_reconstruction | 0 |
| a16 | hand_reconstruction | 1013 |
| a16 | protected_existing_hair | 62234 |
| a16 | protected_quill_paper | 4942 |
| a16 | protected_glove_gold_cuff | 7285 |
| a16 | protected_costume | 323114 |
| a16 | allowed_edit | 66550 |

## ownership

- single source: a16_ownership_map.png, labels 0-9 mutual exclusive
  (0 other/background, 1 hair, 2 quill-paper, 3 glove-cuff, 4 costume,
   5 cane, 6 chair, 7 unassigned-alpha, 8 remove-tail, 9 repair-hand)
- ownership_unassigned_alpha_px = 0 (alpha pixels not covered by the
  declared items; they remain unprotected and unclaimed, by design)
- all masks derived by equality; labels frozen before derivation

## verification

- verifier VERIFY OK; residual total == sum(classes) for a01
  (1291);
- allowed_edit == union(terms) per asset; allowed ∩ protected = 0 per asset;
- a01/a05 masks byte-identical to R4; input hashes are LF-normalized;
- cutouts rebuilt from master+masks and compared byte-exact
  (all backgrounds, 100/200/400);
- a16 protected isolated cutouts delivered; zero candidates; zero calls.

MASK_PLAN_SHA256 = dc692c3f45315e1e1d223fd0d2b2d78b5a17647cdb654f025e3ddf4e38f5970c
STATUS = READY_FOR_NIGHT03_PATCH2A_R5_OWNERSHIP_REVIEW
