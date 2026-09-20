# NIGHT03_PATCH2B_R1A_R6 — authoritative annotation sources (STATIC)

This directory holds the authoritative annotation sources for the
R1A-R6 mask/plan freeze.  They are **static committed data**: the
freeze consumes them strictly read-only and never creates or modifies
them.  No dilation, no colour filtering, no morphological ops and no
default classification exist anywhere in the committed freeze pipeline.

## Files

| file | asset | content |
|---|---|---|
| `a16_occlusion_annotation.json` | a16 | 6-class occlusion semantics, per-row explicit runs, exactly the 36,124 px R6A-R4 prop union; `rows` is the sole authority |
| `a01_tail_source.json` | a01 | final tail-source rows + full per-row manual review ledger |
| `a05_tail_source.json` | a05 | final tail-source rows + full per-row manual review ledger |
| `a01_tail_draft_authority.json` | a01 | **independent DRAFT_AUTHORITY** — the R1A-R3 draft rows the review ledger must cover exactly |
| `a05_tail_draft_authority.json` | a05 | independent DRAFT_AUTHORITY (same role) |

## a16 occlusion semantics — rows are the sole authority

The final per-pixel RLE in `rows` is the single authoritative source of
a16 occlusion semantics.  The freeze/verifier enforce that the keys
`parts`/`annotation` do not exist and that `provenance.authority ==
"rows"`.  Labelled set == R6A-R4 prop union exactly: 36,124 px, zero
outside, zero duplicates, zero unknown classes.  Census (px):
transparent 24,565, hand_glove 645, gold_cuff 327, sleeve_coat 5,849,
lower_garment_leg 4,738, other 0.

## Tail sources — full review ledger with computed completeness closure

`UNREVIEWED = 0` is **not a trusted field**: the freeze and the
independent verifier COMPUTE completeness from coverage relations
against the independent DRAFT_AUTHORITY:

- every final-source row y appears exactly once, strictly increasing;
- every review row y appears exactly once, strictly increasing;
- `{review y} == {final rows y} == {draft authority rows y}`;
- review accepted pixels, whole canvas, == final source pixels
  (`accepted_sum == FINAL_SOURCE.sum() == source_px`);
- review draft pixels, whole canvas, == DRAFT_AUTHORITY pixels
  (`draft_sum == DRAFT_AUTHORITY.sum()`);
- rejected runs are jointly validated: coordinate order, no overlap,
  no duplicate pixels, exactly one reason per pixel;
- `UNREVIEWED == DRAFT_AUTHORITY - accepted - rejected` computed per
  pixel and asserted `== 0`;
- all run lists are canonical RLE: strictly increasing, no overlap,
  no duplicates, exact arity (extra fields rejected).

Review totals — a01: draft 24,925 = accepted 24,349 + rejected 576
(309 PROTECTED_CONFLICT + 267 GOLD_STAFF_AA); a05: draft 49,408 =
accepted 49,286 + rejected 122 (all PROTECTED_CONFLICT).

Raw gates are asserted **before any use** and no clipping exists:
`raw_source ∩ outside_visible = 0`, `raw_source ∩ protected = 0`.

## Determinism

PNG deliverables use this repo's own fixed-Huffman LZ77 deflate, so a
fresh exact checkout rebuilt by the single freeze entry reproduces
every committed byte (48/48).
