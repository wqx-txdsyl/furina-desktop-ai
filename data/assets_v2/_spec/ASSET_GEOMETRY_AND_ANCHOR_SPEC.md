# ASSET_GEOMETRY_AND_ANCHOR_SPEC.md

- spec_id: FURINA-GEOMETRY-LOCK-V2
- status: FROZEN for Art Alpha (production runtime wiring is OUT OF SCOPE tonight — specification only)

## 1. Canonical canvas

| field | value |
|---|---|
| canvas | 1024 × 1536 px (2:3 portrait) |
| generation request | size=2K, ratio=2:3 (Agnes) |
| color mode | RGBA PNG, straight alpha |
| character height in canvas | 0.88–0.94 of canvas height for standing full-body |
| horizontal placement | character center-of-mass at x = 0.50 (±0.03) |

Non-standing classes may vary height fraction (sitting ≈ 0.62–0.72) but NEVER canvas size or
center-x rule without a semantic reason recorded in `semantic_state`.

## 2. Baseline and vertical contract

- ground baseline G = y = 1468 px (0.956 H) — the line where shoe soles rest
- standing feet: both sole contact points within 6 px of G
- sitting: seat contact at y = 1468 px, feet may be higher (recorded via foot anchors)
- window-top / edge sitting: contact semantics recorded in metadata `contact` field; baseline rule
  still applies to the CANVAS (contact point mapped to G)
- no cropping: full silhouette + ahoge + hat tip + cane tip must fit with ≥24 px margin

## 3. Anchor set (relative coordinates, fraction of canvas, origin top-left)

| anchor | default (x, y) | notes |
|---|---|---|
| anchor_x / anchor_y (root) | 0.50, 0.94 | placement root = between the feet |
| head_anchor | 0.50, 0.26 | center of head mass (below hat) |
| chest_anchor | 0.50, 0.50 | brooch level |
| hand_anchor_l | 0.68, 0.55 | her left hand (viewer right) default rest |
| hand_anchor_r | 0.34, 0.56 | her right hand (cane grip side) |
| foot_anchor_l | 0.44, 0.94 | her left foot |
| foot_anchor_r | 0.56, 0.94 | her right foot |
| interaction_anchor | 0.50, 0.62 | point user interactions (poke/pet) aim at |
| speech_anchor | 0.72, 0.20 | bubble attach point (upper viewer-right) |
| shadow_origin | 0.50, 0.95 | contact shadow ellipse center |
| gaze_anchor | free (x,y) | where she looks; default 0.50, 0.30 (front) |

Facing convention: `facing` ∈ {front, front_left, front_right, side_left, side_right, back}.
"her left" = viewer right in front views. All anchors are recorded per-asset; defaults above are the
neutral standing values and every full-body master must stay within tolerance:

- anchor drift tolerance: ±0.02 (x or y) per anchor vs the neutral master A01
- characters facing left/right mirror hand anchors accordingly (recorded, not recomputed)

## 4. Machine-readable metadata schema (proposal — NOT wired into runtime tonight)

```json
{
  "asset_id": "furina_v2_a01_stand_neutral_front",
  "category": "POSTURE | EXPRESSION | GAZE | MICRO_ACTION | LOCOMOTION | INTERACTION | WORK_ACTION | SPECIAL | TRANSITION | FX",
  "semantic_state": "idle_neutral",
  "posture": "standing",
  "facing": "front",
  "expression": "neutral",
  "gaze": "front",
  "action": null,
  "frame_index": 0,
  "canvas_width": 1024,
  "canvas_height": 1536,
  "anchor_x": 0.50,
  "anchor_y": 0.94,
  "head_anchor": [0.50, 0.26],
  "hand_anchor_l": [0.68, 0.55],
  "hand_anchor_r": [0.34, 0.56],
  "foot_anchor_l": [0.44, 0.94],
  "foot_anchor_r": [0.56, 0.94],
  "interaction_anchor": [0.50, 0.62],
  "speech_anchor": [0.72, 0.20],
  "shadow_origin": [0.50, 0.95],
  "contact": "feet_ground | sit_surface | window_edge | drag_midair | none",
  "prop_mode": "none | cane | task_prop",
  "cane_hand": "none | image_left | image_right",
  "prop_required": false,
  "gravity_center": [0.50, 0.70],
  "loop": false,
  "interruptible": true,
  "source_generation_id": "agnes-image-2.1-flash / seed / timestamp",
  "base_identity_version": "furina-base-2026-08",
  "style_version": "FURINA-STYLE-LOCK-V2",
  "review_status": "PENDING | ACCEPT | REGENERATE | REJECT",
  "review_notes": "",
  "motion_notes": {
    "procedural_candidates": ["breath", "blink", "sway"],
    "layer_candidates": ["arm_l", "tail_r"],
    "constraints": ""
  }
}
```

## 5. Compatibility rules

1. Every master ships with measured anchors (auto-measured from alpha + manual confirm in review).
2. No master may shift the character, scale, or crop arbitrarily; deviations require a semantic
   reason written into `semantic_state`.
3. Frame sequences inherit anchors of their entry pose; per-frame anchor deltas ≤4 px.
4. Scale reference: head height of a full-body standing master = 0.42 × canvas height (±3%).

## 6. Prop policy (amended 2026-08-28, NIGHT-02)

- The BASE cane is an **OPTIONAL prop**, NOT an identity invariant. Identity locks cover face,
  hairstyle, costume, palette, proportions and core decorations only.
- `cane_hand` records the image-side where the cane is drawn; it need not be the same hand across
  different poses. Only spatial continuity within one continuous animation is required.
- Poses that do not need a cane default to `prop_mode: none` (props absent from the frame).
- Formal / presentation poses may choose `cane` by semantics; `task_prop` covers pose-specific
  props (quill, document, cake, …).
- A missing cane is NEVER a rejection reason; cane left/right hand is NEVER a regeneration reason.
- Where a prop causes unnatural motion, occludes a hand, or conflicts with the task prop, the asset
  is flagged for later removal/layering — not immediately regenerated.
