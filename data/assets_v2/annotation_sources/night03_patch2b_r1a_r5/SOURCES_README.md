# NIGHT03_PATCH2B_R1A_R5 — authoritative annotation sources (STATIC)

This directory holds the three final authoritative hand annotations for
the R1A-R5 mask/plan freeze.  They are **static committed data**: the
freeze consumes them strictly read-only and never creates or modifies
them.  No dilation, no colour filtering, no morphological ops and no
default classification exist anywhere in the committed freeze pipeline.

## Files

| file | asset | content |
|---|---|---|
| `a16_occlusion_annotation.json` | a16 | 6-class occlusion semantics, per-row explicit runs, exactly the 36,124 px R6A-R4 prop union |
| `a01_tail_source.json` | a01 | hand tail-source runs + FULL per-row manual review record |
| `a05_tail_source.json` | a05 | hand tail-source runs + FULL per-row manual review record |

## a16 occlusion semantics — rows are the sole authority

Per the R1A-R5 task book (option b): **the final per-pixel RLE in
`rows` is the single authoritative source of a16 occlusion
semantics.**  No control rows, interpolation rules or part
definitions are claimed or recorded — the freeze/verifier enforce
that the keys `parts`/`annotation` do not exist and that
`provenance.authority == "rows"`.  The labelled set equals the R6A-R4
prop union (cane | chair primitives, alpha > 8) exactly: 36,124 px,
zero outside, zero duplicates, zero unknown classes.

Class vocabulary (mutually exclusive): `transparent`, `hand_glove`,
`gold_cuff`, `sleeve_coat`, `lower_garment_leg`, `other`.
Final census (px): transparent 24,565, hand_glove 645, gold_cuff 327,
sleeve_coat 5,849, lower_garment_leg 4,738, other 0.

## a01 / a05 tail sources — full manual review record

Both sources carry a complete, machine-checkable per-row review
record (`review.rows`): every row is
`[y, draft_runs, accepted_runs, rejected_runs_with_reason]`, so every
draft pixel is explicitly classified:

- `MANUALLY_ACCEPTED` — pixel stays in the final source
  (`accepted_runs`; accepted == final `rows` exactly)
- `MANUALLY_REJECTED` — pixel removed, with reason
  `PROTECTED_CONFLICT` (protected authority wins) or
  `GOLD_STAFF_AA` (gold staff anti-aliasing inside the staff window)
- `UNREVIEWED` — **0 px** by construction, enforced fail-closed

Review totals — a01: draft 24,925 = accepted 24,349 + rejected 576
(309 PROTECTED_CONFLICT + 267 GOLD_STAFF_AA); a05: draft 49,408 =
accepted 49,286 + rejected 122 (all PROTECTED_CONFLICT).
Review method: 4x-8x zoomed crops with pixel probes; the staff window
for a01 is x[262,300] y[1040,1230] (recorded in `adjudication`).

Raw gates are asserted **before any use** and no clipping exists:
`raw_source ∩ outside_visible = 0`, `raw_source ∩ protected = 0`.

## Validation contract (enforced fail-closed by the freeze + verifier)

- a16: `labeled == prop_union(36124)`, `labeled_outside = 0`,
  `duplicate_pixels = 0`, `unknown_class_pixels = 0`,
  `class_sum = 36124`, provenance contract holds.
- tails: strict row validation (bounds / strict order / no overlap /
  no duplicates), `source_px == reconstructed pixels`, metadata
  (format / canvas / alpha_threshold / gold_window) exact, review
  record complete with `UNREVIEWED = 0`, raw gates zero,
  `mirror_source_outside_tail = 0`,
  `visible_destination ∩ protected = 0`.
- deliverables: PNG encoding is deterministic (this repo's own
  fixed-Huffman LZ77 deflate), so a fresh exact checkout rebuilt by
  the single freeze entry reproduces every committed byte.
