# FURINA_IDENTITY_LOCK.md

- spec_id: FURINA-IDENTITY-LOCK-V2
- status: FROZEN
- date: 2026-08-27 (NIGHT-01)
- authority: `data/assets_v2/_base/furina-base.png` (byte-identical copy of `data/assets/reference/furina-base.png`)
- rule: **BASE WINS.** Where this document or any other spec conflicts with the BASE image, the BASE image is correct.

## 0. Source of truth

Single authoritative reference:

- file: `data/assets_v2/_base/furina-base.png`
- original: `data/assets/reference/furina-base.png` (NEVER modify or delete)
- canvas: 224 × 320 px, RGBA, transparent background
- opaque alpha bounding box: (15, 7) – (216, 317)
- derived inspection crops live in `data/assets_v2/_base/inspections/` (NOT authoritative, derived from BASE only)

All old V1 assets under `data/assets/poses/` are DEPRECATED as style references. They are not to be
averaged against, matched, or preserved. See ASSET_STYLE_LOCK.md §10.

## 1. Overall proportion verdict (CRITICAL)

The BASE is a **chibi-proportioned** Furina:

- total height : head height ≈ 2.2 : 1 (head ≈ 45% of total height)
- This supersedes any generic "no chibi proportions" negative constraint. The BASE defines the
  production identity as chibi; the identity lock is chibi Furina, rendered at high craft quality.
- Impression: young-adult Furina stylized into premium chibi; elegant, theatrical, NOT toddler-like.

Key measured ratios (fractions of opaque bbox, height H = 310 px, width W = 201 px):

| measure | value (approx) |
|---|---|
| head height | 0.45 H |
| head width (with hair) | ~0.75 W |
| eye line | ~0.62 H from top (~0.38 H below hair top) |
| shoulder line | ~0.50 H |
| ground contact (shoe soles) | y = 0.995–1.0 H |
| center of mass x | ~0.50 W (slight lean, cane side heavier) |

## 2. A. FACE

- face shape: soft round-chibi face, wide cheeks, small pointed chin, jaw curve smooth and short
- cheek proportion: cheeks at ~full width of face, slight outward bulge
- eye shape: very large, vertically-round ovals; upper lid thick and dark; lower lid nearly open
- eye spacing: ~1.0 eye-width between inner corners (wide-set, chibi standard)
- iris proportion: iris fills ~70% of eye opening; strong vertical highlight
- iris color: deep blue outer ring → mid blue → pale cyan/white core gradient, top-down
- pupils: dark navy, small, centered-low
- highlights: one large soft white highlight upper-outer, one small sharp lower-inner
- eyebrow: thin, light blue-gray, softly arched, sits above eye with visible gap
- nose: implied only — tiny shadow dot or omitted; NO drawn nose line
- mouth: small, placed low (near chin); BASE pose = open cheerful smile with dark interior and
  small tongue/teeth hint; mouth must always remain small relative to face
- age impression: youthful (late-teens stylized); never aged up, never infantile

## 3. B. HAIR

- base color: near-white with cool tint (#F0F0F4 area), inner/lower layers shaded pale ice blue (#D8E4F0)
- accent layers: streaks and under-layers of light sky blue (#A8C8E8 area); deep navy shadow pockets (#2C3C78)
- silhouette: voluminous, cloud-like, wavy bob framing the face and falling past the shoulders
- bangs: full fringe, parted slightly off-center (her right), jagged soft points over the eyebrows,
  two longer face-framing locks falling to cheek level
- side hair: two long wavy side tails from behind the ears; her left tail (viewer right) is the LONG
  showpiece tail, flowing down past the hip to knee level with a curling tip; her right tail is
  shorter, partially behind the arm/cane
- rear hair: fills silhouette behind shoulders; light blue tint in shadow
- ahoge: ONE signature thick curved ahoge from the crown, curling toward viewer-left in a large
  open hook — mandatory identity element
- strand grouping: painted as grouped ribbon-like locks with hard cel shadow edges, not strand-by-strand
- blue/white value rule: white dominates (~70%), light blue accents (~20%), deep blue shadow (~10%)

## 4. C. HEAD ACCESSORIES

- hat: dark navy top hat (flat-topped cylinder with slightly flared brim), worn tilted toward her
  left (viewer right), brim sitting above the bangs, covering the crown's right side
- hat band: blue with white striped ribbon detail
- hat crown decorations: gold crown-like pointed ornaments along the top rim + teardrop-shaped blue
  gem drops hanging from the rim + thin gold trim lines
- side ornament: white frilled/feather ornament + blue gem pin with gold setting on the viewer-right
  side of the band
- ribbons: no large head ribbon besides the band ornament
- alignment: hat is always tilted; a straight vertical hat is a REJECTABLE drift

## 5. D. BODY

- proportions: chibi 2.2-head figure; short torso, short limbs, large head (see §1)
- shoulder width: narrow, ~0.55 head width
- arm length: short; upper+forearm together ≈ 0.45 head height when hanging
- hand scale: small, simplified, 3–4 finger suggestion inside dark gloves
- leg ratio: thighs and calves nearly equal, short; total leg ≈ 0.45 H
- shoe scale: slightly oversized rounded navy shoes with light soles
- silhouette: A-line — wide head/hair/hat on top, narrow waist, gently widening to hem and feet

## 6. E. COSTUME (locked structure)

- collar/shirt: white high collar shirt front visible as a V inset in the jacket
- ascot: blue cravat/ascot at the throat, pinned by ONE large round blue gem brooch with gold setting
- jacket: dark navy, fitted, double row hint of two gold buttons, white shirt inset, swallowtail
  coattails at the back, hem finished with blue-and-white striped frill trim
- sleeves: long navy sleeves ending in dark blue gloves (glove slightly darker navy than jacket,
  cuff visible)
- back bow: large blue bow with central blue gem at the back waist
- waist: white shorts under the jacket hem
- leg details: single dark navy thigh strap on her right thigh (viewer left) with a small gold
  clasp and a hanging teardrop blue gem pendant
- legs: bare skin from shorts to socks (chibi simplification; no full stockings in BASE)
- socks/shoes: light blue-white ruffled sock covers (lace-trim spats) over navy shoes; small
  ribbon detail at the shoe vamp
- prop: gold-and-navy rapier/cane held in her right hand (viewer left), ornate guard, held point-down
  (amended 2026-08-28: the cane is an OPTIONAL prop, not an identity invariant — see §10 item 7;
  `prop_mode`/`cane_hand`/`prop_required` are recorded per asset in the manifest)
- decorative elements: gold accents appear ONLY on hat ornaments, brooch setting, buttons, cane —
  never as large surfaces

## 7. F. MATERIAL LANGUAGE

- fabric: flat cel fills, one hard shadow per form, minimal fabric texture
- metal (gold): saturated gold with sharp white specular shapes, dark outline
- gemstone: blue gradient fill (deep→light top-down) + one white star-shaped or round highlight
- ribbon: same cel language as fabric, striped pattern allowed only where BASE shows it
- hair: ribbon-locked groups, hard-edged shadow shapes
- skin: flat warm-white with one soft blush/shadow tone; no painterly blending
- Hydro elements: NOT present in BASE. Hydro FX live only in the separate FX layer system
  (see ASSET_TOPOLOGY_MAP.md); they must never be baked into identity masters.

## 8. G. RENDERING

- line quality: clean, confident dark outlines (dark blue-gray-black), uniform width, no sketch lines
- edge softness: hard cel edges throughout; no airbrush softness on form shadows
- cel/painterly balance: 90% cel / 10% soft (cheeks, gem cores)
- highlight shape: geometric (rounds, stars, rectangles), placed deliberately
- shadow softness: hard-edged shadow shapes everywhere except cheeks
- saturation: medium-high; blues rich but not neon
- contrast: clear value separation between white hair / navy costume / light blue accents
- facial rendering: minimal — flat skin, shadow under bangs, blush hint, heavy eye rendering
- hair rendering: grouped locks, hard shadow shapes, subtle blue ambient bounce in white hair

## 9. H. CAMERA

- projection: standard anime illustration projection, mild telephoto feel (flattened perspective)
- apparent focal length: ~85mm-equivalent feel; NO wide-angle distortion
- full-body framing: character fills 85–95% of canvas height, centered horizontally (±5%)
- default angle: eye-level to very slightly below eye-level (heroic micro-tilt allowed, ≤5°)
- horizon: single vanishing region far away; floor contact implied by shadow, not by visible ground plane
- rotation limits: yaw ±30° from front, pitch ±10° — beyond this requires FRAME_SEQUENCE_ONLY asset class

## 10. Identity drift checklist (used by the review gate)

Any candidate FAILING one of these is REJECT:

1. head-to-body ratio ≠ ~2.2 heads (±10%)
2. ahoge missing, doubled, or curling the wrong way
3. hat missing, un-tilted (vertical), wrong color family, or ornaments restructured
4. eye shape enlarged/shrunk beyond chibi standard, or iris gradient re-colored
5. hair silhouette changed (bob length, tail count, tail length order)
6. costume structure changed (jacket→dress, missing brooch, missing thigh strap, missing striped trim)
7. prop missing when pose implies her right hand holds the cane (unless action block explicitly removes it)
   — AMENDED 2026-08-28 (NIGHT-02): the cane is an OPTIONAL prop, not an identity invariant. Missing
   cane is NEVER a rejection reason; cane left/right hand is NEVER a regeneration reason. Only spatial
   continuity within one continuous animation is required. Poses without cane default to
   `prop_mode: none`. This item no longer blocks ACCEPT.
8. palette drift (see ASSET_STYLE_LOCK.md §6 palette table)
9. rendering style drift (soft painterly, 3D, photoreal, thick-paint)
10. age impression drift in either direction
