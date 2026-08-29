# ART_ALPHA_PLAN.md

- spec_id: FURINA-ART-ALPHA-PLAN-V2
- status: ACTIVE (night 2026-08-27)
- target: 12–20 ACCEPTED masters. NOT more. No full-library production tonight.

## 1. Purpose

Prove that a BASE-locked, prompt-locked pipeline can produce visibly-same-Furina assets across
different semantic states. The Alpha is the gate that later authorizes full production
(READY_FOR_FULL_ASSET_PRODUCTION). It does NOT authorize mass generation.

## 2. Alpha set (18 required + 2 optional)

| id | semantic state | posture | key risks |
|---|---|---|---|
| A01 | neutral standing front | standing | reference-neutral; anchors origin |
| A02 | neutral standing slight-left | standing | yaw drift, hat/ahoge flip |
| A03 | neutral standing slight-right | standing | mirror asymmetry (tail side) |
| A04 | relaxed idle | standing | proportion drift via "cute" wording |
| A05 | confident / proud | standing | costume simplification, chest-out distortion |
| A06 | gentle happy | standing | eye-enlargement drift |
| A07 | annoyed / mildly offended | standing | emote-pack exaggeration |
| A08 | embarrassed / caught off guard | standing | deformation drift |
| A09 | curious / leaning attention | standing | balance/anchor drift |
| A10 | sleepy / low-energy standing | standing | eye rendering consistency |
| A11 | sitting | sitting | baseline/contact semantics |
| A12 | walking key pose | locomotion | leg articulation vs chibi legs |
| A13 | petting response | interaction | anatomy under hand-raised pose |
| A14 | poke response | interaction | exaggeration risk |
| A15 | dragged / lifted response | interaction | gravity/contact believability |
| A16 | working / focused (writing with quill-like gesture, cane set aside) | work | prop consistency; must stay Furina |
| A17 | speaking / presenting | work/present | mouth rendering, gesture |
| A18 | quiet / reflective | standing | subtle-expression fidelity |
| A19 (opt) | eating | special | only if consistency strong |
| A20 (opt) | playing | special | only if consistency strong |

A16 constraint (mission §14): Furina acting as HERSELF at work — no office-employee Furina,
no laptop stock illustration. Focused quill/document gesture in her own costume.

## 3. Pipeline per candidate

1. compose prompt = LOCK blocks + delta (prompt system spec)
2. img2img generate (BASE init, 2K 2:3, NEGATIVE_BLOCK, seed recorded)
3. chroma-key magenta background → transparent RGBA (careful: keep hair/edge integrity)
4. normalize canvas to 1024×1536, fit baseline contract
5. auto-measure anchors (alpha bbox + head/top heuristics)
6. build side-by-side comparison sheet (candidate vs BASE) for the review gate
7. manual review vs identity checklist (IDENTITY_LOCK §10) + style gate
8. classify ACCEPT / REGENERATE / REJECT; record reason + provenance

## 4. Review gates (summary; full criteria in review report template)

- Identity gate: 10-point checklist in FURINA_IDENTITY_LOCK.md §10 — any failure = REJECT
- Style gate: palette within tolerance (STYLE_LOCK §6), rendering style, camera, transparency
- Geometry gate: baseline, center-x, height fraction, anchor deltas vs A01
- "Does it look like THIS exact Furina?" — not "is it pretty"

## 5. Budget

- ≤ 40 generation calls total (incl. regenerations) — stay compact
- stop expanding at 20 accepted, or when 2 consecutive regenerations fail the same checklist item
- A19/A20 only after ≥16 accepted and consistency is visibly holding

## 6. Exit states (mission §22)

- READY_FOR_ART_ALPHA_REVIEW — ≥12 accepted
- ART_ALPHA_GENERATION_BLOCKED_NO_GENERATOR — no working generator access
- NOT_READY_FOR_ART_ALPHA_REVIEW: <exact blocker> — e.g. keying pipeline failure, identity
  collapse across all candidates
