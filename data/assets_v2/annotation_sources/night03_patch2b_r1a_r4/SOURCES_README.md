# NIGHT03_PATCH2B_R1A_R4 — authoritative annotation sources (STATIC)

This directory holds the three final authoritative hand annotations for
the R1A-R4 mask/plan freeze.  They are **static committed data**: the
freeze script consumes them strictly read-only and never creates or
modifies them.  Nothing in this directory is generated at freeze time;
no dilation, no colour filtering, no morphological ops and no default
classification exist anywhere in the committed freeze pipeline.

## Files

| file | asset | content |
|---|---|---|
| `a16_occlusion_annotation.json` | a16 | 6-class occlusion semantics, per-row explicit runs, exactly the 36,124 px R6A-R4 prop union |
| `a01_tail_source.json` | a01 | hand tail-source runs, raw gates pre-validated (0 outside-visible, 0 protected) |
| `a05_tail_source.json` | a05 | hand tail-source runs, raw gates pre-validated (0 outside-visible, 0 protected) |

## a16 occlusion semantics

Class vocabulary (mutually exclusive, exactly one label per prop pixel):
`transparent`, `hand_glove`, `gold_cuff`, `sleeve_coat`,
`lower_garment_leg`, `other`.

Every prop-union pixel carries an explicit run entry in `rows`; there is
no implicit fill and no pre-painted transparent.  The labelled set equals
the R6A-R4 prop union (cane | chair primitives, alpha > 8) exactly:
36,124 px, zero outside, zero duplicates, zero unknown classes.

Semantic faces are continuous: the Builder hand-placed per-part control
rows (recorded in the JSON `parts[*].control_rows`) and each face is
interpolated only **between** those control rows.  Part paint order and
the first-wins conflict rule are recorded in the JSON `annotation`
block.  Final measured census (px): transparent 24,565, hand_glove 645,
gold_cuff 327, sleeve_coat 5,849, lower_garment_leg 4,738, other 0.

## a01 / a05 tail sources — hand adjudication record

Both sources were re-adjudicated by the Builder at 4x-8x zoom with
pixel probes.  Raw gates are asserted **before any use** and no
clipping happens anywhere:

- `raw_source ∩ outside_visible = 0`
- `raw_source ∩ protected = 0`

### a01 (final 24,349 px; raw draft was 24,925 px)

Two contaminations were hand-adjudicated out of the draft:

1. **309 px protected_props conflicts removed.**  The draft's 2 px AA
   fringe had swallowed the gold staff silhouette (head/hook region
   x269-297, y1045-1078) and the lower shaft's left edge (x306-319,
   y1231-1359).  The protected_props authority wins: all 309 px are
   staff, not tail.  (Sampled and confirmed visually at 5x.)
2. **267 px gold staff AA removed** inside the staff window
   x[262,300] y[1040,1230]: warm gold anti-aliasing of the staff edge
   that the fringe caught but the props mask (hard-edged) does not
   cover.  Confirmed: zero warm px remain in the final source.

### a05 (final 49,286 px; raw draft was 49,408 px)

1. **122 px protected_costume conflicts removed** at the gown edge
   (x380-391, y915-967): gown edge px swallowed by the AA fringe.
   Costume authority wins; confirmed visually at 6x.

No gold/staff contamination exists in a05 (window probe: 0 px).

## Validation contract (enforced fail-closed by the freeze)

- a16: `labeled == prop_union(36124)`, `labeled_outside = 0`,
  `duplicate_pixels = 0`, `unknown_class_pixels = 0`,
  `class_sum = 36124`.
- tails: raw gates above; mirror destination derived deterministically;
  `visible_destination ∩ protected = 0`; `mirror_source_outside_tail = 0`.
