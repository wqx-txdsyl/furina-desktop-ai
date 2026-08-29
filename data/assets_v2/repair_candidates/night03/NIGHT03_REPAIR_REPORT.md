# NIGHT03_REPAIR_REPORT — Art Alpha Tail & Matte Repair

- date: 2026-08-28
- inputs: NIGHT-01 19 masters, NIGHT-02 `ratification_v1.json`, `ART_ALPHA_INDEPENDENT_RATIFICATION.md`, retained BASE (`2f8e10bb…2682a`)
- method: **local surgical repair, zero generation** — the MIRRORED_ERROR tail is repaired by
  segment (two-tier pale/white-border hair mask inside a per-asset ROI) → row-span fill of narrow
  foreground occluders (cane shafts) with edge-lerp colour → mirror about the canvas axis →
  composite **behind** the untouched body → delete the original left-side tail → hair/orphan debris
  cleanup. Prop/matte defects (chair, cane, droplets, wisp, FX, specks) are removed by colour/strip
  masks with column-lerp infill. No image-generation model was invoked; all work written under
  `repair_candidates/night03/`. Masters, raw/, rejected/, _base/ and the 5 ACCEPT masters untouched.

## PART A — pilots (a01, a05, a16), budget ≤4 gen attempts each / ≤12 total → 0 calls used

| asset | repairs | identity | pose | tail | alpha | props/bg | geometry |
|---|---|---|---|---|---|---|---|
| a01 | tail mirror (cane shaft spans filled, cane fully preserved) | PASS (head zone diff ≤2 px) | PASS | coherent, root attached behind coattail | 1 comp, 0 islands | none added | com_x 0.5194 (in 0.50±0.03), baseline 1467 |
| a05 | tail mirror + detached 410 px tail wisp removed | PASS | PASS | coherent | clean | none added | com_x 0.5489 — **deviation recorded** (§5.2) |
| a16 | tail mirror + chair removed (25.4 k px) + held cane removed, fist rebuilt (12.5 k px, column-lerp infill) + 3 specks removed | PASS | PASS (quill/paper kept, no desk/background) | coherent | 1 comp, 0 islands | none added | com_x 0.5312 — deviation +0.0012 recorded (§5.2) |

**PART A Gate: 3/3 PASS (required ≥2/3) → METHOD_PROVEN = true → PART B executed.**

Known cosmetic notes for human review (a16): hand simplified to a closed fist after cane removal;
transparent gaps remain where chair wood was visible between skirt/thigh/coattail in the master.

## PART B — conditional batch (executed after gate pass), ≤2 gen each / ≤36 total → 0 calls used

| asset | repairs | com_x | objective gate |
|---|---|---|---|
| a03 | tail mirror | 0.5289 | PASS |
| a04 | tail mirror | 0.5220 | PASS |
| a06 | tail mirror (cane crossed tail centre — occluder spans filled, cane preserved) | 0.5302 | PASS |
| a07 | tail mirror; 6 px speck investigated at (579,600): **no detached component exists** there, region byte-identical — nothing to remove | 0.5363 | PASS (com deviation recorded) |
| a08 | tail mirror | 0.5234 | PASS |
| a09 | tail mirror | 0.5300 | PASS |
| a10 | tail mirror | 0.5419 | PASS (com deviation recorded) |
| a13 | tail mirror + 2 droplet islands (138 px) removed | 0.5413 | PASS (com deviation recorded) |
| a14 | tail mirror | 0.5493 | PASS (com deviation recorded) |
| a18 | tail mirror | 0.5274 | PASS |
| a19 | tail mirror + baked FX removed (crescent moon + sparkle + dots, 651 px); cake prop and leaning staff kept; sock frills excluded via rect mask | 0.5272 | PASS |

com_x note: removing a left-side tail and re-adding it on the right necessarily shifts the
centre-of-mass right; for right-leaning poses (a05, a07, a10, a13, a14) the result exceeds
0.50±0.03 by up to +0.019. Per ASSET_GEOMETRY_AND_ANCHOR_SPEC §5.2 the deviation is recorded with
its semantic reason (tail-side correction to BASE-consistent side) in each refreshed
`review_notes`/`night03_repair` metadata block instead of distorting the tail placement.

## Metadata refresh (pixels untouched unless stated)

- All 14 repair candidates: refreshed `content_px`, measured `com_x`, `review_status: PENDING`,
  `night03_repair` provenance block (method, sha256 of candidate and master) → copies under
  `repair_candidates/night03/metadata/`. Master meta.json files untouched.
- a02 (ACCEPT, untouched): metadata-only re-measurement — recorded content_px equals the measured
  value under the alpha>8 convention; **no change required**. The NIGHT-02 "+1 px" reading used a
  different alpha threshold; pixels remain byte-identical.

## Objective gate table (all 14 candidates)

1 alpha component · 0 islands >40 px · 0 magenta-like px · 4 corners transparent ·
lowest opaque row 1467 (baseline G=1468 ±1) · head zone (y<850) diff ≤2 px (a01) / 0 px (all others)
· all changed pixels confined to the tail/prop zones.

## Rule compliance

- Cane treated as optional prop; no asset failed for cane absence; a05 scepter and a19 staff kept.
- No whole-image horizontal mirror anywhere (tail-only mirror transplant).
- a02/a11/a12/a17/a20 original files byte-identical (a02 metadata copy only).
- No regeneration was used to cover alpha/metadata issues; masters not overwritten;
  no git add/commit/push; no Phase16 tracked-file modifications; furina/ untouched.
- A15 not started; asset library not extended; stop after this report.

## Deliverables

- `repair_candidates/night03/furina_v2_<id>_repair.png` × 14
- `repair_candidates/night03/night03_triptych_<id>.png` × 14 (master | repaired | BASE)
- `repair_candidates/night03/runtime_previews/<id>_pet_{512,256,128}.png` × 42
- `repair_candidates/night03/metadata/*.meta.json` × 15 (14 repairs + a02 refresh)
- `repair_candidates/night03/night03_repair_manifest.json`
- `_finalize_checks.json`, `_pilot_state.json`, `_batch_state.json` (machine-readable evidence)
- `_inspect/` — iteration/audit crops

## Final receipt

```
METHOD_PROVEN = true
GENERATION_CALLS = 0
PILOT_ACCEPT = 3            (a01, a05, a16 — PART A gate; human review pending)
REPAIRED_ACCEPT = 14        (repair candidates passing the night's objective gate)
STILL_HOLD = 0              (all 14 MIRRORED_ERROR/matte HOLDs processed; ACCEPT promotion awaits human review)
IDENTITY_REGRESSIONS = 0    (head/torso zones bit-identical; ≤2 stray px on a01)
TAIL_CORRECTED = 14
ALPHA_REPAIRED = 4          (a05 wisp, a13 droplets, a16 specks, a19 FX; a07 speck: none found)
PROPS_REMOVED = 2           (a16: baked chair, held cane)
MASTERS_OVERWRITTEN = false
PRODUCTION_FILES_CHANGED = 0
STATUS = READY_FOR_NIGHT03_REVIEW
```

Stop — no library expansion, no A15.
