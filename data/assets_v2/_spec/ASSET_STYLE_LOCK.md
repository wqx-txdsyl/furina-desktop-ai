# ASSET_STYLE_LOCK.md

- spec_id: FURINA-STYLE-LOCK-V2
- status: FROZEN
- date: 2026-08-27 (NIGHT-01)
- authority: BASE (`data/assets_v2/_base/furina-base.png`). **BASE WINS** over any text here.

## 1. Rendering style

Premium chibi anime illustration, hard-cel shading, clean uniform outlines, flat fills with
deliberate geometric highlights. The one and only style for ALL Furina production assets.

- NO painterly brushwork
- NO semi-realism, NO photorealism, NO 3D-render look (no raytraced highlights, no AO bakes)
- NO watercolor, NO sketch, NO thick-outline American cartoon style
- NO gradient-mesh softness on forms (gradient allowed ONLY inside irises and gems, as in BASE)

## 2. Line treatment

- single consistent dark outline color (very dark desaturated blue-gray, ~#20222E)
- uniform stroke weight at production resolution; outline never lighter than mid-gray
- no double outlines, no colored outlines except a permitted 1px darker-blue line inside hair
  shadow boundaries (as in BASE)
- interior seams (clothing panels, hair locks) use the same line, slightly thinner

## 3. Shading treatment

- two-tone cel per form: base fill + one hard shadow shape (three-tone only where BASE shows it,
  e.g. hair deep pockets)
- shadow color: hue-shifted toward blue, never gray-black multiply mush
- highlight placement: consistent top-left key light (see §8 lighting)
- cheeks: single soft warm blush oval, low opacity
- no ambient occlusion passes, no rim light by default

## 4. Color behavior

- palette is closed (§6); new hues may not be introduced
- value structure: white/light values carried by hair+shirt+socks; dark values by hat+jacket+shoes;
  mid blue as bridge
- saturation peaks reserved for gemstones and eye irises
- background: 100% transparent. Chroma-key production background (magenta #FF00FF) must be fully
  removed; no fringe, halo, or semi-transparent contamination outside intended soft edges (hair tips
  may keep ≤2px soft alpha)

## 5. Material treatment

- see FURINA_IDENTITY_LOCK.md §7. Material language is part of the style lock and identical rules apply.

## 6. Canonical palette (sampled from BASE, 16-bin quantized)

| token | hex (approx) | use |
|---|---|---|
| WHITE | #F0F0F4 | hair base, shirt, sock covers, highlights |
| ICE | #DCE6F2 | hair shadow tone 1, white-in-shadow |
| SKY | #A0C4E4 | hair accent streaks, trim light blue |
| MIDBLUE | #5A84C4 | bridge mid-tone, iris mid, ribbon accents |
| NAVY | #20307E | jacket, hat, shoe upper, deep hair shadow |
| DEEPNAVY | #1A2660 | jacket/hat shadow, line shadow pockets |
| GOLD | #E8C86A | ornaments, buttons, cane guard |
| SKIN | #FDF4F0 | skin base |
| SKINSHADE | #F0DCD8 | skin shadow/blush support |
| IRIS-DEEP | #24389C | iris outer, gem base |
| IRIS-LIGHT | #8CC8F0 | iris core, gem top light |
| OUTLINE | #20222E | all lines |

Tolerance for review: hue ±10°, value ±8%, chroma ±10%. Beyond tolerance = palette drift = REJECT.

## 7. Face / eye / hair / costume fidelity

- face treatment: per FURINA_IDENTITY_LOCK.md §2 — deviations there are identity drift
- eye treatment: iris gradient + dual highlight structure is MANDATORY in every asset
- hair treatment: grouped ribbon locks with hard shadows; ahoge always present
- costume-detail fidelity: full detail at every production size. NEVER simplify costume
  (no dropping brooch, buttons, thigh strap, striped trim, glove cuffs) — simplification drift is REJECT

## 8. Lighting assumptions

- single key light: top-left, slightly front (≈10 o'clock), white-neutral
- fill: ambient blue bounce (environment read as cool)
- no secondary rim light, no colored gels, no dramatic cast shadows on the body
- ground contact: soft elliptical drop shadow (cool blue-gray, ~25% alpha) belongs to the SHADOW
  layer, never baked into the master silhouette

## 9. Edge & transparency rules

- production format: PNG, RGBA, straight (non-premultiplied) alpha
- background: fully transparent
- outline pixels: fully opaque; interior anti-aliasing allowed 1px inside the outline
- no background color contamination, no glow bleed, no shadow baked under feet in masters
  (shadow is a separate FX asset `fx_contact_shadow`)

## 10. Relation to deprecated V1 assets

All assets in `data/assets/poses/` (V1, source "agnes", manifest `data/assets/manifest.json` v1)
are DEPRECATED as references. They are neither style nor identity sources. They may remain on disk
(read-only) until explicit deletion authorization. V2 assets must never be visually compared to,
blended with, or averaged against V1 assets.

## 11. NEGATIVE CONSTRAINTS (hard)

1. NO non-chibi realistic proportions (the generic "no chibi" rule is SUPERSEDED — the BASE IS chibi;
   "chibi" drift here means drifting AWAY from the BASE's exact chibi ratio)
2. NO oversized-head drift beyond ±10% of BASE ratio; NO eye enlargement drift
3. NO simplified costume, NO alternate costume interpretation, NO costume-color swaps
4. NO hair-length drift; NO ahoge removal; NO hat shape drift; NO hat-tilt removal
5. NO face-age drift (older or younger)
6. NO body-proportion drift (leg length, shoulder width)
7. NO random painterly / oil / acrylic styles; NO random cel-shading variants (e.g. NO Ghibli-soft)
8. NO photorealism; NO 3D-render appearance; NO Nendoroid/figure look (must remain 2D illustration)
9. NO excessive bloom, glow, or particle FX baked into identity masters
10. NO colored background contamination; NO gradient backgrounds; NO environment art
11. NO uncontrolled rim light; NO dramatic cinematic lighting
12. NO random camera focal-length changes; NO dutch angles; NO wide-angle distortion
13. NO chibi-exaggeration drift (mega-head "popuko" chibi, bean mouth, noodle limbs)
14. NO sticker-style thick white borders, NO emote-pack exaggerated deformation
15. NO Hydro/water FX baked into identity masters (FX are separate layers only)
16. NO third-party Furina artwork as source, reference, or init image (§18 of mission: only BASE)
