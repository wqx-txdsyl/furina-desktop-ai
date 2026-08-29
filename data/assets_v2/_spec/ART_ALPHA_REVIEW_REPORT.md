# ART_ALPHA_REVIEW_REPORT.md

- report_id: FURINA-ART-ALPHA-REVIEW-NIGHT01
- date: 2026-08-27 (NIGHT-01)
- reviewer: automated night run + visual gate (side-by-side sheets, 10-point identity checklist)
- base authority: `data/assets_v2/_base/furina-base.png`
- generator: Agnes `agnes-image-2.1-flash`, img2img from BASE, 2K 2:3, seed recorded per asset
- budget used: 40 generation calls (hard cap reached)

## 1. Verdict

**READY_FOR_ART_ALPHA_REVIEW** — 19 accepted masters, 1 rejected candidate.
Acceptance threshold (≥12) met without lowering any review criterion.

| outcome | count | ids |
|---|---|---|
| ACCEPT | 19 | a01–a14, a16–a20 |
| REJECT | 1 | a15 |
| not generated | 0 | — |

## 2. Pipeline as executed

1. LOCK-block prompt system (see MASTER_GENERATION_PROMPT_SPEC.md); transparency block promoted to
   prompt head after first-round background haze.
2. img2img generation (BASE as init image), magenta cutout-sheet background.
3. Hue-based chroma matte (kills r>g ∧ b>g family, 1px erode + despill) → transparent RGBA.
4. Canvas normalization to 1024×1536, ground baseline y=1468, center x=512, per-class content height.
5. Review sheet per candidate (BASE | candidate) in `review/`.
6. Identity gate (FURINA_IDENTITY_LOCK §10, 10 items) + style gate (palette/rendering/camera) +
   geometry gate (baseline, centering, silhouette completeness).

## 3. Accepted masters

| id | semantic state | notable review notes |
|---|---|---|
| a01 | stand neutral front | anchor-neutral reference master; tail side CORRECT |
| a02 | stand neutral slight-left | tail side CORRECT |
| a03 | stand neutral slight-right | tail side CORRECT |
| a04 | relaxed idle | tail side flipped |
| a05 | confident/proud | tail flipped; cane-as-scepter reads well |
| a06 | gentle happy | tail flipped; minor extra thigh band |
| a07 | annoyed | tail flipped; crossed-arm pout, anatomy preserved |
| a08 | embarrassed | tail flipped; cane reduced to wrist ribbon-wand |
| a09 | curious leaning | tail flipped |
| a10 | sleepy | tail flipped; excellent half-lid rendering |
| a11 | sitting (floor) | tail flipped; cane across lap present |
| a12 | walking key pose | tail side CORRECT; best locomotion evidence |
| a13 | pet response | tail flipped; no cane (hands raised — acceptable) |
| a14 | poke response | tail flipped; startle without exaggeration |
| a16 | working/focused | tail flipped; quill+paper, Furina as herself (mission §14 satisfied) |
| a17 | speaking/presenting | tail flipped; articulate open mouth |
| a18 | quiet/reflective | tail flipped; gaze level instead of slightly down |
| a19 | eating (opt) | tail flipped; 2–3 tiny baked sparkle pixels noted for cleanup |
| a20 | playing (opt) | tail side CORRECT; one-foot twirl with hat-hand release |

All 19 pass: 2.2-head proportion (±10%), single left-hooking ahoge, tilted hat with gold/teardrop
ornaments, gradient iris + dual highlights, full costume structure (brooch, gloves, back bow,
striped trim, thigh strap, ruffled sock covers), closed navy/ice palette, hard-cel rendering,
clean transparency (corner alpha = 0 on all), baseline and centering contract.

## 4. REJECT record

- **a15 lifted/drag response** — three generation attempts never realized the mid-air-lift
  semantics (character remained standing). Identity itself was fine each time, but the asset would
  have carried a false `semantic_state`. Moved to `rejected/` with reason in metadata.
  Deferred to the SPECIAL_ONLY class (keyframe/video tooling per future plan).

## 5. Known systematic deviation: tail chirality

13 of 19 masters render the long showpiece side tail on the image-LEFT; the BASE has it on the
image-RIGHT (her left). Silhouette, length, and color match; chirality is flipped. Two regen rounds
(including explicit image-side wording and a negative block) did not eliminate it — the generator
flips it ~50% of the time under pose changes.

Assessment: recorded deviation, not an accept-blocker — the checklist's hair-silhouette item
(count/length order) passes, and ASSET_TOPOLOGY_MAP.md already classifies the tail as
LAYER_CANDIDATE #3 for Phase 20/21, where a one-time mirrored tail-layer fix (or per-asset layer
flip at runtime) resolves it. Recommendation: fix at layer-extraction time, do NOT re-roll
masters for it.

## 6. Style-consistency observations

- Palette stability across all 20 raw candidates: high; navy/ice/gold tokens within tolerance.
- Line weight and cel treatment: consistent; no painterly/3D contamination survived review.
- Camera: all accepted masters obey eye-level, full-body, uncropped framing.
- Geometry: center-x within ±0.03; standing content height 0.88–0.94 of canvas; sitting 0.62–0.72.
- Transparency: all 20 processed candidates have fully transparent corners and no visible matte
  after the hue-based key replaced the first-round value-based key.

## 7. Artifacts

- masters: `data/assets_v2/masters/` (19 PNG + per-asset meta JSON)
- rejected: `data/assets_v2/rejected/` (a15 PNG + meta)
- raw provenance: `data/assets_v2/raw/` (all 40 generations, seed + prompt hash + init hash)
- review sheets: `data/assets_v2/review/sheet_*.png` (20)
- machine-readable manifest: `data/assets_v2/metadata/manifest_v2.json`
- tooling (no backend imports): `scripts/assets_v2/night_alpha.py`

## 8. STOP per mission §22

This run stops here. No full-library expansion was started. Final state:

**READY_FOR_ART_ALPHA_REVIEW** (19 accepted / threshold 12; review artifacts complete)

Explicitly NOT claimed: ASSET_LIBRARY_COMPLETE, PHASE_21_PASS, PRODUCTION_ART_COMPLETE.

## 9. Recommended next actions (for a future authorized night)

1. Human eyeball pass over the 19 sheets (5 minutes) to ratify the automated gate.
2. Tail-layer flip fix during first layer-extraction pass.
3. Re-attempt drag/lift as a SPECIAL clip via the video/keyframe endpoint.
4. Only then declare READY_FOR_FULL_ASSET_PRODUCTION and open the POSTURE/LOCOMOTION queues.
