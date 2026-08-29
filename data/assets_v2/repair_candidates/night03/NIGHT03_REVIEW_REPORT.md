# NIGHT03_REVIEW_REPORT — Independent Reviewer Gate

- reviewer: NIGHT-03 Independent Reviewer (fresh session, GLM-5.3-Flash)
- date: 2026-08-29
- inputs reviewed: NIGHT-03 review task book (prompt), ASSET_GEOMETRY_AND_ANCHOR_SPEC.md (FURINA-GEOMETRY-LOCK-V2, §5.2 = Compatibility rule 2), FURINA_IDENTITY_LOCK.md scope, NIGHT-02 `metadata/ratification_v1.json` + `review/ratification_measurements.json`, `NIGHT03_REPAIR_REPORT.md`, `night03_repair_manifest.json`, `_pilot_state.json` / `_batch_state.json` / `_gate_checks.json` / `_finalize_checks.json`, `scripts/assets_v2/night03_{repair,tail_lib,gate,finalize}.py` (full static read), 15 refreshed metadata files, 14 candidate PNGs, 14 triptychs, 42 runtime previews, 19 masters, `_base/furina-base.png`
- method: independent pixel measurement (alpha>8 and alpha>=250 conventions), deletion/addition cluster forensics vs strict ROIs, 100%–200% zoom crops of every defect site, 512/256/128 preview inspection, full re-run of the repair pipeline into a temp directory

## 1. Final verdict

**DECISION = NIGHT03_PATCH_REQUIRED**

TheBuilder's counts, hashes, metadata and reproducibility claims are all **true and verified**.
The failure is **visual/semantic**: the repair method systematically eats costume and prop
pixels (chest bows, ribbon tails, sock frills, coattail lining, cane shafts, a16's hair and
hand) inside the over-wide tail ROIs, and the Builder's objective gate was structurally blind
to all of it (its change-zones cover the entire lower body; its "head zone" y<850 misses hair
below y=850). METHOD_PROVEN is therefore **not verified**: 0 of 3 pilots is deliverable.

```
DECISION = NIGHT03_PATCH_REQUIRED
METHOD_PROVEN_VERIFIED = false
PILOT_PASS = 0            (a01/a05/a16 all carry blocker-level damage)
FULL_PASS = 0             (all 14 carry at least one blocker)
IDENTITY_REGRESSIONS = 1  (a16 right-side hair largely deleted; a01 2px speck cleanup is harmless)
TAIL_FAILURES = 4         (a01 fragmented tip + outline ghost; a14 leftover stump; a16 3-fragment tail; a19 leftover fragment)
ALPHA_FAILURES = 0        (topology/magenta/corners/baseline all clean and verified)
PROP_FX_FAILURES = 14     (costume/prop collateral damage in every asset; see §10/§11)
COSTUME_DAMAGE_ASSETS = 14 / 14
METADATA_MISMATCHES = 0
SCRIPT_SAFETY_FAILURES = 0
MASTERS_UNCHANGED = true
PRODUCTION_FILES_CHANGED = 0   (attributable to NIGHT-03; see §9 note on external 16C commit)
GENERATION_CALLS = 0
REVIEW_REPORT = data/assets_v2/repair_candidates/night03/NIGHT03_REVIEW_REPORT.md
STATUS = NIGHT03_PATCH_REQUIRED
```

## 2. Review scope and basis

- Original task book: the NIGHT-03 review instruction itself (no separate task-book file exists
  in the repo); referenced specs read in full: `data/assets_v2/_spec/ASSET_GEOMETRY_AND_ANCHOR_SPEC.md`
  (§2 baseline, §3 anchors, §5.2 deviation rule, §6 prop policy), ASSET_TAXONOMY, STYLE_LOCK scope,
  FURINA_IDENTITY_LOCK scope (face/hair/costume/palette are identity-locked).
- Ground truth for "correct tail side": NIGHT-02 ratification (BASE tail = viewer-right, curled
  tip) re-confirmed by reviewer measurement of BASE (tail-band hair mass right>left at native
  224×320 scale) — semantics agreed.
- Nothing was trusted from the Builder's reports without re-derivation from files/pixels.

## 3. File completeness and safety checks — ALL PASS

1. Manifest scope: exactly the 14 NIGHT-02 HOLD assets (a01,a03,a04,a05,a06,a07,a08,a09,a10,
   a13,a14,a16,a18,a19) + a02 metadata-only. No omission, no duplicate, no extra asset
   (a11/a12/a15/a17/a20 correctly absent; ACCEPT assets untouched).
2. Per-asset deliverables complete: 14 candidates + 14 triptychs + 42 previews (14×512/256/128)
   + 15 refreshed metadata. Counts verified by directory scan.
3. All candidates 1024×1536 RGBA straight alpha, corners transparent; naming matches the
   report's deliverable list (`furina_v2_<id>_repair.png`, `night03_triptych_<id>.png` 2065×1024
   = master|repaired|BASE, `<id>_pet_{512,256,128}.png` 128×192 aspect-correct).
4. SHA256: all 15 master hashes, all 14 candidate hashes and BASE (`2f8e10bb…2682a`) recomputed
   and match the manifest exactly.
5. Masters/production: see §9 — unchanged, proven at pixel level.
6. Scripts: no hidden master-overwrite path, no production writes, no network/API/generation
   calls (imports: json/sys/pathlib/numpy/PIL/scipy only); all output paths anchored under
   `repair_candidates/night03/`. See §8.
7. `git status` recorded before and after review; untracked set unchanged
   (`data/assets_v2/`, `scripts/assets_v2/`, three `_night_*.md` docs, `nul` — all pre-existing).
   Note: during the review window commit `0684753` (Phase 16 16C Reviewer Patch 5) landed
   externally and absorbed the two pre-existing dirty tracked files
   (`furina/agent/backend/hermes.py`, `tests/agent/integration/test_phase16c_hermes_api_adapter.py`).
   That is the parallel 16C workstream, not NIGHT-03 and not the reviewer.

## 4. PART A pilot review (a01, a05, a16) — 0/3 PASS

### a01 — FAIL (tail-side correct; three visual blockers)

Verified good: tail hair mass moved 35353/13156 (L/R) → 16290/31377; cane fully preserved
(strips protected); head-zone change is exactly 2 px at (x=363, y=714) and (x=363, y=715) —
a detached 2-px semi-transparent dark speck (alpha 9/15, RGB≈[12,9,15]) floating off the hair
silhouette; its deletion is a harmless cleanup, not an identity regression.

Blockers (100% zoom evidence):
- **B-a01-1 Coattail lining flayed**: the pale striped lining on the coattail's inner edge
  (x≈395–430, y≈973–1300; deletion clusters 469 px @ x395-429/y973-1044, 434 px @ x408-429/
  y1038-1101 plus main-cluster edge) is deleted to thin slivers with hard cut edges — the
  coattail reads "hollowed".
- **B-a01-2 Old-tail outline ghost**: a thin dark curved line remains tracing the old tail's
  lower silhouette around (x≈190–260, y≈1150–1300) (the outline was never hair-coloured, so
  the hair-only masks never removed it).
- **B-a01-3 Fragmented mirrored tail tip**: the mirrored tail terminates in disconnected
  rectangular slivers — ADD cluster 5222 px @ x627-763/y1227-1358 split into a striped floating
  fragment (mirrored coattail-lining captured by the mask), a cyan horizontal bar ≈x736-775/
  y1325-1344 with straight vertical edges, and a hard horizontal cut at the main tail mass
  bottom (y≈1300). Clear colour discontinuity + cut marks at 100%.

### a05 — FAIL (chest bow destroyed)

Verified good: wisp island (464+1=465 px @ x623-662/y1283-1314, matching ratification's "410 px
@(625,1284)-(662,1313)" up to alpha threshold) removed cleanly; tail mass moved to the right
(49537/24835 → 3618/46919).

Blockers:
- **B-a05-1 Bow shredded**: white rectangular voids strike through the chest bow and its
  hanging ribbon tails (bow core ≈x374–443, y≈870–1038; ribbon tails to y≈1090; part of the
  61278 px main deletion cluster @ x149-479/y850-1400). Hard rectangular edges through bow,
  shorts and thigh visible at 100% and in the 512 px runtime preview.
- **B-a05-2 Mirrored costume fragment pasted**: the captured bow pixels were mirrored to the
  right and pasted as a floating fragment (ADD 2139 px @ x678-766/y903-992) near the coattail.

### a16 — FAIL (highest-risk item; hair + hand destroyed)

Verified good: baked chair removed (25,437 px mask, core achieved); held cane removed
(12,454 px); quill and paper fully intact; 3 specks (70/33/32 px @ x273-284/y1016-1025,
x307-312/y1063-1074, x280-286/y953-959) removed; objective topology clean.

Blockers:
- **B-a16-1 Hair deleted**: the right-side hair curls are largely deleted (helmkill zone
  x≈694–815, y≈850–1000). The gate's "head zone y<850" is meaningless for this sitting pose —
  the damage sits just below the line and was never measured. Asymmetric clipped silhouette is
  visible even at 128 px and obvious at 512 px.
- **B-a16-2 Hand mangled, not a "rebuilt fist"**: the grip area (x≈650–800, y≈950–1130) is a
  shredded dark mass with white slivers and vertical column-lerp smear streaks dripping below
  the glove. At 200% it is debris, at 512 px it reads as a corrupted arm. The report's "known
  cosmetic note (hand simplified to a closed fist)" materially understates this — blocker, no
  exemption.
- **B-a16-3 Jagged removal voids**: chair/cane removal bit into her skirt hem, shorts and
  coattail (x≈460–720, y≈1140–1470 edges) leaving ragged white holes with hard edges well
  beyond the wood areas.
- **B-a16-4 Fragmented mirrored tail**: ADD clusters 4365 px @ x728-834/y1159-1289,
  2378 px @ x687-765/y1297-1418, 1902 px @ x631-674/y1306-1405 — the tail arrives as 2–3
  disconnected floating arcs; (alpha_components=1 only via incidental touching).

**PART A gate: 0/3 PASS ⇒ METHOD_PROVEN = true is NOT verified.** The objective gate ("3/3
objective_pass") is true but measures the wrong things (see §8 root cause).

## 5. Full 14-asset review table

Legend: ✓ = pass, ✗ = blocker found. Every row was reviewed on master + candidate + BASE +
triptych + 512/256/128 previews, plus 100–200% zoom crops at each defect site and a
red=deleted / green=added diff overlay.

| ID | Identity/Pose | Tail Side | Tail Layering | Seam/Ghost | Alpha | Prop/FX | Metadata | Visual Verdict |
|---|---|---|---|---|---|---|---|---|
| a01 | ✓ (2px speck cleanup harmless) | ✓ L→R | ✗ fragmented tip | ✗ outline ghost + lining flay | ✓ | ✗ coattail lining eaten | ✓ | FAIL |
| a03 | ✓ | ✓ L→R | ✓ | ✗ hard voids at bow/ribbon/lining | ✓ | ✗ bow+ribbon deleted | ✓ | FAIL |
| a04 | ✓ | ✓ L→R | ✓ | ✗ hard voids at bow/ribbon/lining | ✓ | ✗ bow+ribbon deleted | ✓ | FAIL |
| a05 | ✓ | ✓ L→R | ✓ | ✗ bow voids + pasted fragment | ✓ | ✗ bow shredded | ✓ | FAIL |
| a06 | ✓ | ✓ L→R | ✓ | ✗ voids at lining/leg | ✓ | ✗ cane lower shaft+spearhead deleted (report claims preserved — false) | ✓ | FAIL |
| a07 | ✓ | ✓ L→R | ✓ | ✗ bow voids | ✓ | ✗ bow wing+ribbon deleted; 6px-speck claim TRUE (see §6) | ✓ | FAIL |
| a08 | ✓ | ✓ L→R | ✓ | ✗ bow/shred voids | ✓ | ✗ cane shredded (head bitten, shaft gone, tip floating) | ✓ | FAIL |
| a09 | ✓ | ✓ L→R | ✓ | ✗ bow voids | ✓ | ✗ bow wing+ribbon deleted | ✓ | FAIL |
| a10 | ✓ | ✓ L→R | ✓ | ✗ voids at ribbon/skirt | ✓ | ✗ bow ribbon+skirt bites at hands | ✓ | FAIL |
| a13 | ✓ | ✓ L→R | ✓ | ✗ voids at frills/ribbon | ✓ | ✗ raised-arm frills + chest ribbon deleted; droplets removed OK | ✓ | FAIL |
| a14 | ✓ | ✓ L→R | ✗ leftover stump | ✗ straight-cut edge, frill bites | ✓ | ✗ raised-foot sock frill bitten; bow wing deleted | ✓ | FAIL |
| a16 | ✗ hair deleted | ✓ L→R | ✗ 3 floating fragments | ✗ jagged voids + smear streaks | ✓ | ✗ hand mangled; voids in skirt/coattail | ✓ | FAIL |
| a18 | ✓ | ✓ L→R | ✓ | ✗ voids at bow/ribbon | ✓ | ✗ bow wing deleted; cane head nicked; frill nibbled | ✓ | FAIL |
| a19 | ✓ | ✓ L→R | ✗ leftover fragment behind left leg | ✗ cut edge; frill bites | ✓ | ✓ moon/sparkle/dots removed cleanly; staff+cake kept; ✗ sock frill shredded | ✓ | FAIL |

Tail-side quantification (hair-mask mass L/R, y-band 950–1420), all 14 moved left→right,
matching the BASE-consistent side — this part of the method works.

## 6. Special investigations

### a07 — Builder claim CONFIRMED ("原声明成立")
Independent check of the master at (x=579, y=600) and both coordinate interpretations:
the point is inside the body (alpha 213, skin tone [220,145,172]); the full image has exactly
**1** alpha-connected component even at alpha>0 (8-connectivity) — no 6 px (or any) detached
component exists anywhere. Batch evidence `defect_island_px=0` is consistent; region is
byte-identical in the candidate. The NIGHT-02 "6 px speck at (579,600)" record was a false
positive. No漏检 by either party.

### a13 — droplets removed cleanly, but costume damage elsewhere
The detached droplet island measured 138 px @ x324-335/y1255-1269 (ratification said "two
droplets 112 px" — threshold-related counting of the same target); it is fully removed with no
semi-transparent residue and no character-edge damage. Tail and alpha pass. Blocker is
elsewhere: raised-arm frills (115 px @ x341-381/y850-900, 93 px @ x341-370/y1107-1141) and the
striped chest ribbon are deleted with hard voids.

### a16 — see §4. Deliverable quality: NO. The chair and held-cane removal core works and
quill/paper survive, but hair deletion, the mangled hand, jagged clothing voids and the
fragmented tail are each independently disqualifying. "Known simplification" is not accepted.

### a19 — FX removal clean; two tail/frill blockers
All baked FX verified removed at source coordinates (moon 239 px @ x303-324/y1062-1090,
sparkle 235 px @ x777-796/y1198-1226, dots 62/59/36/20 px; total 651 px = Builder's number);
no fill-patches, blur, transparency anomalies or outline holes at those spots; the leaning
staff and cake are untouched. Blockers: (1) the white sock frill on her left foot is shredded
by rectangular bites (deletion inside the tail ROI x≈295–400, y≈1270–1455 — the rect mask
protected only tail *extraction*, not hair_debris_cleanup, so the report's "sock frills
excluded via rect mask" is misleading); (2) an old-tail fragment remains behind the left leg
inside the same excl_rect (295,1270)-(460,1470), never deleted, with a hard cut edge.

## 7. Metadata verification (recomputed from files, Builder caches ignored)

- **15/15 refreshed metadata files match** independent re-measurement of the actual files
  (content_px, lowest_row, com_x, alpha_components, islands_gt40, magenta_px, corners).
  Candidate hashes in `night03_repair` blocks match file bytes.
- **a02**: recorded content_px [180,60,664,1408] equals the measured value under alpha>0 /
  alpha≥1 / alpha>8; the NIGHT-02 "+1 px" reading [181,61,663,1407] is the alpha≥250
  convention (confirmed in `ratify_alpha_geometry.py`). The "±1 px is threshold difference"
  claim is **VERIFIED**; the refreshed copy states the convention explicitly. Pixels untouched;
  status stays ACCEPT.
- **com_x deviations vs 0.50±0.03**: a05 0.5489, a07 0.5363, a10 0.5419, a13 0.5413,
  a14 0.5493, a16 0.5312, a06 0.5302 exceed 0.53 — all seven carry the §5.2 deviation note
  with semantic reason in `review_notes`. a03 0.5289, a09 0.5300 (exactly at limit), a18
  0.5274, a19 0.5272, a08 0.5234, a04 0.5220, a01 0.5194 are within tolerance and correctly
  unnoted. Deviations are genuine consequences of tail-side relocation (no crop/shift/canvas
  tricks detected — head/torso zones bit-identical), visually acceptable in composition.
- Non-blocker observation: GEOMETRY §5.2's letter says the semantic reason goes into
  `semantic_state`; the Builder used `review_notes`/`night03_repair`. Acceptable here (keeps
  `semantic_state` machine-clean; this review's criteria reference review_notes) but recorded
  as a letter-deviation.
- Non-blocker: a16's "12.5k px column-lerp infill" — 12454 is the cane *deletion* count;
  `infill_px` is bookkept as `cane.sum()` by construction, so the actual infill/fist pixel
  count was never measured.

## 8. Script safety and reproducibility

Safety (static review of night03_repair.py / night03_tail_lib.py / night03_gate.py /
night03_finalize.py):
- **SCRIPT_SAFETY_FAILURES = 0.** Masters are opened read-only; every write targets
  `data/assets_v2/repair_candidates/night03/**`; no network/API/generation imports or calls;
  no dependence on undocumented manual intermediates (the `_inspect/` crops are diagnostic
  outputs, not inputs); asset IDs, ROIs, strips, thresholds and colour tests are recorded in
  code; no path exists that overwrites masters, raw/, rejected/, _base/ or furina/.
- `night03_gate.py` contains an older two-panel triptych variant that is dead code (finalize's
  3-panel version ran last and produced the delivered triptychs). Cosmetic only.

Reproducibility (dynamic):
- Pilots a01/a05/a16 and the full batch re-run from current masters with the current scripts
  into a temp directory (repo untouched): **14/14 candidates BIT-IDENTICAL (SHA256)** to the
  delivered files, including a16's auto-placement. The pipeline is deterministic from recorded
  inputs; no hidden state. (One bookkeeping line in `batch()` uses `relative_to(ROOT)` and
  crashes if OUT is redirected — irrelevant to the delivered run.)

Root cause of the visual failures (for the patch task):
1. `hair_mask` (pale / blue-shadow / white-border tests) matches Furina's costume: bow
   highlights, striped ribbons, white skirt, sock frills, coattail lining, pale cane shafts.
2. Tail ROIs are wide and tall (a01 x60-430/y900-1470; batch x60-440/y850-1470; a05
   x100-480/y850-1420) — they contain chest bows (x≈320–460, y≈850–1100), ribbons, glove
   frills, sock frills and coattail lining.
3. Deletion/debris/island cleanup apply the mask with no costume protection;
   `spare_occluders` only protects row-span gaps ≤44 px created by the span-fill.
4. The objective gate cannot see any of this: `ZONES` cover the whole lower body (changes
   inside them are unchecked) and `head_zone` = y<850 misses all hair below 850 (a16).
5. The mirrored patch re-pastes captured costume pixels on the right (a05 bow fragment).
6. `excl_rects` shield regions from extraction but not from debris cleanup, and also prevent
   old-tail deletion inside them (a19 leftover).

## 9. Masters / production unchanged — PROVEN

- Pixel-level: all 15 touched-scope masters re-measured under NIGHT-02's exact convention
  (alpha≥250 opaque, semi 1–249): opaque_px, semi_px and opaque_bbox are **bit-identical** to
  `review/ratification_measurements.json` for every asset (my first pass showed "mismatches"
  that resolved 100% into the threshold-convention difference — opaque delta == semi delta for
  all 15).
- mtime: all masters 2026-08-27 02:32, predating all NIGHT-03 work (2026-08-28 02:18–02:58).
- ACCEPT masters a02/a11/a12/a17/a20: included in the identical-measurement proof.
- Production (`furina/`): 0 changes attributable to NIGHT-03. The branch's pre-existing dirty
  `hermes.py`/test files were committed externally as `0684753` during the review window
  (parallel 16C workstream). No git add/commit/push performed by the reviewer.

## 10. Blockers (must-fix; each alone forces NIGHT03_PATCH_REQUIRED)

Per-asset, coordinates are x-ranges/y-ranges in the 1024×1536 canvas; observation zoom noted.

- **a01** @100–160%: (1) coattail lining flayed, x395-430 / y973-1300; (2) old-tail outline
  ghost arc, x≈190-260 / y≈1150-1300; (3) fragmented mirrored tail tip (striped floating
  fragment + cyan bar x736-775 / y1325-1344 + hard horizontal cut y≈1300).
- **a03** @200%: chest bow left wing + hanging ribbon deleted (voids x≈345-440 / y≈850-1090);
  coattail lining edge deleted (x301-318 / y1340-1350).
- **a04** @200%: same bow/ribbon deletion class (clusters 4360 px @ x372-439/y912-1114 et al.);
  coattail lining edge deleted.
- **a05** @100–200% + 512 preview: bow shredded x374-443 / y870-1038 + ribbon tails; mirrored
  bow fragment pasted x678-766 / y903-992.
- **a06** @200%: cane lower shaft + spearhead deleted (4811 px @ x400-439 / y1158-1464) —
  contradicts the report's "cane preserved"; coattail lining eaten.
- **a07** @200%: bow left wing + ribbon deleted (within main cluster x183-439 / y926-1455).
- **a08** @150%: cane head bitten (x367-439 / y930-1000, x404-439 / y1020-1100), shaft deleted,
  crystal tip left floating; bow behind helm shredded.
- **a09** @200%: bow wing + ribbon deleted (x375-439 / y911-1071).
- **a10** @200%: bow ribbon tail + skirt bites beside clasped hands (x≈330-439 / y≈864-1150).
- **a13** @200%: raised-arm frills (x341-381 / y850-900; x341-370 / y1107-1141) + striped chest
  ribbon deleted.
- **a14** @200%: raised-foot sock frill rectangular bite (x≈398-439 / y≈1156-1223); bow wing
  deleted (x407-439 / y850-893); leftover old-tail stump with straight cut edge ≈x330-390 /
  y1100-1200.
- **a16** @100–200% + 512/128 previews: (1) right-side hair curls deleted x≈694-815 /
  y≈850-1000; (2) hand mangled x≈650-800 / y≈950-1130 (shredded mass + vertical lerp smears —
  not a fist); (3) jagged voids eating skirt/shorts/coattail x≈460-720 / y≈1140-1470;
  (4) mirrored tail in 2-3 disconnected fragments (x728-834/y1159-1289, x687-765/y1297-1418,
  x631-674/y1306-1405).
- **a18** @180%: bow left wing + ribbon deleted (x≈387-439 / y≈961-1100); cane head nicked
  (x407-438 / y986-1024); sock frill nibbled (x415-439 / y1311-1371).
- **a19** @200%: left sock frill shredded (deletions inside ROI x≈295-400 / y≈1270-1455);
  leftover old-tail fragment behind left leg inside excl_rect (295,1270)-(460,1470).

Repair requirements (to convert into the Patch task book):
1. Add per-asset costume/prop protection (bow, ribbons, frills, skirt, coattail lining, cane
   geometry) to *every* deletion/cleanup pass, not just tail extraction; restrict deletion to
   tail-hair pixels below the waist line and outside body/costume silhouettes; forbid pasting
   any captured non-hair pixels (drop or mask captured costume fragments before mirroring).
2. a16: rework without touching hair (exclude the helm zone from deletion or protect
   hair-coloured AND white pixels adjacent to hair); rebuild the hand properly or leave the
   area transparent for a later layered solution; constrain chair removal to wood-coloured
   pixels only; make the mirrored tail a single coherent attached mass or reject.
3. a19: apply the excl_rect to hair_debris_cleanup as well, while still deleting old-tail
   pixels inside it (protect only true frill/bow pixels).
4. Remove outline ghosts (a01): the cleanup must also remove the old tail's dark outline
   (any-colour components fully inside the tail silhouette), not only hair-coloured pixels.
5. Fix the gate so it can never pass this again: narrow change-zones to the actual tail
   corridor per asset, define head/identity zones per pose (not fixed y<850), and add an
   automated "deleted-pixel must be tail-hair-coloured and in-corridor" assertion plus a
   mandatory 100% and 512-px visual QA pass per asset.
6. Correct the report claims that are false as written: a06 "cane preserved", a19 "sock
   frills excluded", a16 "fist rebuilt" / "hand simplified", a16 "known cosmetic notes".

## 11. Non-blockers

- a01 2 px head-zone change: located (363,714-715), detached semi-transparent speck, harmless.
- a07: "no 6 px component at (579,600)" — claim true (see §6).
- Alpha/matte topology on all 14: 1 component, 0 islands>40, 0 magenta, corners transparent,
  baseline row 1467 — all verified; a05 wisp / a13 droplets / a16 specks / a19 FX removals
  themselves are clean.
- §5.2 deviation notes present for all seven out-of-tolerance com_x values; a09 sits exactly
  at 0.5300 (tolerant edge) without a note — acceptable.
- Metadata letter-deviation (review_notes instead of semantic_state) and the a16 "infill_px"
  bookkeeping label — record only.
- Previews show no white/black fringe artefacts from LANCZOS downscaling.
- `nul` file and `_inspect/` (74 files) are pre-existing builder artefacts; not reviewer's.

## 12. Reviewer file manifest

Added: `data/assets_v2/repair_candidates/night03/NIGHT03_REVIEW_REPORT.md` (this file — the
only file added or modified in the repository by the reviewer; all inspection crops lived in
the OS temp directory). One accidentally created scratch file
(`_inspect/_review_base_upscaled.png`) was deleted within minutes of creation and no longer
exists. No git operations performed.

— End of report. Reviewer stops here: no repairs applied, no A15, no next-night work.