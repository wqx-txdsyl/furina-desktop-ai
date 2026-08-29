# ART_ALPHA_INDEPENDENT_RATIFICATION — NIGHT-02

- date: 2026-08-28
- reviewer: GLM-5.3-Flash (visual review, fresh session — NIGHT-01 verdicts NOT trusted, all 19 re-reviewed from BASE)
- base_sha256: `2f8e10bb17cdc325cf29954bd960e55c90208e84835dddf5b62001a5b922682a`
- generation_calls: **0** (no image-generation model invoked this session)
- production_files_changed: **0** — masters/, raw/, rejected/, _base/ images untouched
- masters_modified: **0**

## 1. Scope & method

Reviewed every master against the retained BASE (`data/assets_v2/_base/furina-base.png`, 224x320,
opaque bbox (15,7)-(216,317)) and the frozen specs (IDENTITY_LOCK V2, STYLE_LOCK V2,
GEOMETRY_AND_ANCHOR V2, TAXONOMY, TOPOLOGY). Gates per asset:

1. provenance (hashes, raw source, prompt/init md5, seeds, manifest consistency)
2. identity (face, eyes, bangs, hat, ahoge, costume, hair silhouette, proportions, camera, palette, age)
3. long-tail side (BASE_CONSISTENT / VIEWPOINT_JUSTIFIED / MIRRORED_ERROR)
4. alpha (white/black/gray50/checkerboard composites, magenta fringe, holes, detached islands, corners, edge stats)
5. geometry & contact (baseline G=1468, height fraction, center-x, feet/cane contact, anchor deltas vs A01)
6. runtime scale (512/256/128 read-only previews; pet-size readability at 128px)

## 2. Verdicts (19 reviewed)

| id | semantic | verdict | tail | alpha | geometry | notes |
|---|---|---|---|---|---|---|
| a01 | stand_neutral_front | HOLD | MIRRORED_ERROR | CLEAN | OK | Showpiece tail on viewer-LEFT (BASE: viewer-RIGHT); thigh band drawn only on viewer-right thigh (BASE band crosses both, gem at viewer-right end); face/hat/ahoge/costume pass; cane present (image_left); contact 2-foot + cane tip on G. |
| a02 | stand_neutral_slight_left | ACCEPT | BASE_CONSISTENT | CLEAN | OK | Tail on viewer-RIGHT with curled tip (matches BASE); strap band both thighs + gem viewer-right (BASE-like); face/hat/ahoge pass; cane image_left; content_px +1px vs measured (threshold noise); slight-left yaw within limits. |
| a03 | stand_neutral_slight_right | HOLD | MIRRORED_ERROR | CLEAN | OK | Tail on viewer-LEFT while pose is slight-right (inverted); face/hat/ahoge pass; cane image_left. |
| a04 | stand_relaxed_idle | HOLD | MIRRORED_ERROR | CLEAN | OK | Tail on viewer-LEFT (mirrored); face/hat/ahoge pass; content_px +1px (noise). |
| a05 | stand_confident_proud | HOLD | MIRRORED_ERROR | HOLD | OK | Tail on viewer-LEFT (mirrored); detached 410px tail wisp at (625,1284)-(662,1313) — matte artifact; cane held image_right as scepter (allowed, optional prop); right hand on hip per action block. |
| a06 | stand_gentle_happy | HOLD | MIRRORED_ERROR | CLEAN | OK | Tail on viewer-LEFT (mirrored); cane held center both hands; content_px +1px (noise). |
| a07 | stand_annoyed | HOLD | MIRRORED_ERROR | CLEAN | OK | Tail on viewer-LEFT (mirrored); 6px stray speck at (579,600) recorded (negligible); crossed-arms pose clean. |
| a08 | stand_embarrassed | HOLD | MIRRORED_ERROR | CLEAN | OK | Tail on viewer-LEFT (mirrored); face/hat/ahoge pass. |
| a09 | stand_curious_leaning | HOLD | MIRRORED_ERROR | CLEAN | OK | Tail on viewer-LEFT (mirrored); curious-lean pose OK otherwise. |
| a10 | stand_sleepy | HOLD | MIRRORED_ERROR | CLEAN | OK | Tail on viewer-LEFT (mirrored); sleepy pose OK otherwise. |
| a11 | sit_floor | ACCEPT | BASE_CONSISTENT | CLEAN | OK | Sitting: showpiece tail curl on viewer-RIGHT (correct); seat contact at G; height frac 0.667 (spec 0.62-0.72); face/hat/ahoge pass; cane across lap (image_left). |
| a12 | walk_key_pose | ACCEPT | VIEWPOINT_JUSTIFIED | CLEAN | OK | Walking key pose: right showpiece tail longer than left (order preserved); left tail inflated vs BASE short tail but motion-justified; monitor in later frames; right hand holds cane per action block; face pass. |
| a13 | pet_response | HOLD | MIRRORED_ERROR | HOLD | OK | Tail on viewer-LEFT (mirrored); two detached blue droplets (112px total) below tail at (325,1256); cane behind raised arm (image_right) — mark for later layering; face/hat/ahoge pass. |
| a14 | poke_response | HOLD | MIRRORED_ERROR | CLEAN | OK | Tail on viewer-LEFT (mirrored); cane in other hand per action block (image_right); face pass. |
| a16 | work_focused | HOLD | MIRRORED_ERROR | HOLD | CHAIR_EXCEPTION | Tail on viewer-LEFT (mirrored); WOODEN CHAIR baked into master while action block says "unseen writing slope" (environment art, STYLE_LOCK §11.10); cane drawn in hand while action block says "leaning beside her" — removal/layering needed; 3 stray specks near hip (20-54px); height frac 0.75 with chair. |
| a17 | speak_presenting | ACCEPT | BASE_CONSISTENT | CLEAN | OK | Speaking/presenting: right showpiece tail dominant (left tail inflated vs BASE but order preserved — note); cane held like orator (image_right); face/hat/ahoge pass; mouth open speaking. |
| a18 | stand_quiet_reflective | HOLD | MIRRORED_ERROR | CLEAN | OK | Tail on viewer-LEFT (mirrored); quiet reflective face pass; hands clasped on cane (image_left); narrowest ground contact 8px (cane tip); feet within tolerance. |
| a19 | eating | HOLD | MIRRORED_ERROR | HOLD | OK | Tail on viewer-LEFT (mirrored); BAKED decorative FX: detached crescent moon 200px at (304,1062), 4-point sparkle 191px at (778,1199), plus 3 small dots (STYLE_LOCK §11.9); cane absent per action block (task_prop: cake); sitting height 0.667. |
| a20 | playing | ACCEPT | BASE_CONSISTENT | CLEAN | OK | Playing twirl: huge showpiece tail swirl on viewer-RIGHT (correct); 23k enclosed hole = legit gap inside tail swirl loop; cane absent per action block (prop_mode none); single-foot contact plausible for twirl; face/hat/ahoge pass. |

## 3. Counts

| metric | count | assets |
|---|---|---|
| REVIEWED | 19 | — |
| ACCEPT | 5 | a02, a11, a12, a17, a20 |
| HOLD | 14 | a01, a03, a04, a05, a06, a07, a08, a09, a10, a13, a14, a16, a18, a19 |
| REJECT (within 19) | 0 | — |
| TAIL_BASE_CONSISTENT | 4 | a02, a11, a17, a20 |
| TAIL_VIEWPOINT_JUSTIFIED | 1 | a12 |
| TAIL_MIRRORED_ERROR | 14 | a01, a03, a04, a05, a06, a07, a08, a09, a10, a13, a14, a16, a18, a19 |
| ALPHA_CLEAN | 15 | a01, a02, a03, a04, a06, a07, a08, a09, a10, a11, a12, a14, a17, a18, a20 |
| ALPHA_HOLD | 4 | a05, a13, a16, a19 |
| PROVENANCE_COMPLETE | 19 | all 19 |

## 4. Tail review (decisive finding)

BASE ground truth (verified from BASE and the 4x inspection): the long showpiece tail is on her
**left** side = **viewer-RIGHT**, flowing past the hip to knee level with a curling tip; a short tail
sits behind the arm/cane on viewer-LEFT; the ahoge hooks viewer-LEFT and the hat tilts viewer-RIGHT.

**14 of 19 masters place the long showpiece tail on viewer-LEFT** (a01, a03-a10, a13, a14, a16,
a18, a19) — a partial mirror (ahoge/hat are NOT mirrored). Per the NIGHT-02 rule, MIRRORED_ERROR
=> HOLD; **no automatic horizontal flip was applied to any master**. The 4 BASE_CONSISTENT assets
(a02, a11, a17, a20) plus the walking-pose VIEWPOINT_JUSTIFIED asset (a12) are ACCEPT candidates.

## 5. Alpha review

- Zero magenta-like pixels in all 19; all four 24px corners fully transparent; edges show normal
  hair/outline AA, no fringing bands.
- All enclosed holes were labelled: every one is a legitimate pose gap (arm/body, tail/leg,
  tail-swirl loop, chair-leg gaps) — no hair/hat/clothing matting loss.
- ALPHA_HOLD (4): **a05** detached 410px tail wisp (625,1284)-(662,1313); **a13** two detached blue
  droplets (112px) below the tail; **a16** three stray specks near the hip/chair (20-54px); **a19**
  baked decorative FX — detached crescent moon (200px) + 4-point sparkle (191px) + three dots,
  violating STYLE_LOCK §11.9 (no particle FX in identity masters). a07 has a negligible 6px speck.

## 6. Geometry & contact

- All 19: RGBA 1024x1536; lowest opaque row y=1467 (baseline G=1468, within 1px); center-of-mass
  x within 0.49-0.518 (spec 0.50 ±0.03); standing height fraction 0.9167 (spec 0.88-0.94);
  sitting a11/a19 0.6667 (spec 0.62-0.72).
- a16 height fraction 0.75 with a **baked chair** (action block says "unseen writing slope") —
  geometry exception + environment-art violation; the chair is not part of the runtime desktop-pet
  contract and must be removed/layered.
- content_px matches measured [x,y,w,h] for 15/19; a02/a04/a06/a16 differ by 1px (threshold noise).

## 7. Runtime scale

Read-only previews at 512/256/128px written under `review/runtime_previews/` (never overwrite
masters). At true pet size (128px) every master keeps a readable face, hat, ahoge, hands, shoes and
silhouette — no collapse. See `review/runtime_scale_overview.png`.

## 8. A15 (REJECTED, unchanged) — recommendation only

**REGEN_CANDIDATE.** Identity passed in all 3 attempts; the mid-air lift/dangle semantics never
materialized (character stands on the ground). A standing sprite cannot be made to look lifted by
runtime procedure (a ground-drag translation is possible from any standing master, but not a
believable dangle); production belongs to SPECIAL_ONLY keyframe/video tooling as NIGHT-01 noted.
No regeneration was performed this session.

## 9. Prop policy (NIGHT-02 correction applied)

Cane is an OPTIONAL prop, not an identity invariant. `prop_mode`/`cane_hand`/`prop_required`
added to all 19 manifest entries and to the spec schema; FURINA_IDENTITY_LOCK §6 and §10.7 amended.
No asset was rejected or held for cane presence/handedness. Layering candidates flagged:
a13 (cane behind the raised petting arm), a16 (cane should lean beside her, not be held; chair removal).

## 10. Final state

**NOT_READY_FOR_HUMAN_ALPHA_RATIFICATION** — 14/19 masters carry the MIRRORED_ERROR showpiece tail
(viewer-LEFT instead of BASE viewer-RIGHT); 4 masters carry detached-island/FX alpha defects
(a05, a13, a16, a19); a16 additionally bakes a chair and a held cane contradicting its action block.
The 5 clean masters (a02, a11, a12, a17, a20) are ready for human alpha review.

## 11. Next repair queue

1. P1 — tail-side regeneration for the 14 MIRRORED_ERROR assets with anti-mirror lock wording
   ("long showpiece hair tail on her left side / viewer right"); NO horizontal flip of any master.
2. P1 — a16: remove chair ("unseen writing slope"), move cane to "leaning beside her", clear specks.
3. P2 — a19: remove baked crescent/sparkle/dots; a13: remove droplets + layer cane; a05: repair
   detached tail wisp.
4. P3 — a07 6px speck; a02/a04/a06/a16 ±1px metadata refresh.
5. A15 — REGEN_CANDIDATE under SPECIAL_ONLY keyframe tooling (out of tonight's scope).
