# MASTER_GENERATION_PROMPT_SPEC.md

- spec_id: FURINA-PROMPT-SYSTEM-V2
- status: FROZEN
- generator: Agnes `agnes-image-2.1-flash`, img2img with BASE as init image

## 1. Architecture

Every asset prompt = **LOCK BLOCKS (identical bytes, every generation) + minimal semantic delta**.
No asset-specific prose beyond the delta blocks. The fewer uncontrolled textual differences between
prompts, the lower the style drift.

## 2. Lock blocks

### CHARACTER_IDENTITY_LOCK (verbatim, every prompt)

```
Furina from Genshin Impact, premium chibi anime illustration, 2.2-heads-tall chibi proportions.
Near-white hair with pale ice-blue inner shading and light sky-blue accent streaks, voluminous
wavy bob, full jagged fringe over the eyebrows, one thick curved ahoge hooking to the left, long
wavy side tail flowing down past the hip on her left side. Large deep-blue eyes with top-down
gradient iris (deep blue to pale cyan) and bright dual highlights, thin light eyebrows, tiny low
mouth, small pointed chin, soft round cheeks. Dark navy top hat worn tilted to her left, decorated
with gold crown ornaments, hanging teardrop blue gems, white frilled ornament and blue gem pin.
Navy swallowtail jacket with white shirt inset, two gold buttons, blue ascot pinned by one large
round blue gem brooch, dark blue gloves, large blue back bow, white shorts, blue-white striped
hem trim, dark thigh strap with hanging teardrop gem on her right thigh, light-blue ruffled sock
covers over navy shoes. Same character design in every image.
```

### STYLE_LOCK (verbatim, every prompt)

```
Clean hard-cel anime shading, flat fills, one hard shadow per form with hue-shifted blue shadow
tones, crisp uniform dark blue-gray outlines, geometric white highlights, medium-high saturation,
closed navy-and-ice-blue color palette, gold accents only on small ornaments. High-quality anime
sticker-grade finish, 2D flat illustration.
```

### CAMERA_LOCK (verbatim, every prompt)

```
Full-body shot, eye-level camera, mild telephoto flattening, no perspective distortion, character
centered and filling about ninety percent of the frame height, entire silhouette visible including
hat top and shoe soles, nothing cropped.
```

### TRANSPARENCY_LOCK (verbatim, every prompt)

```
Solid flat magenta #FF00FF background, no gradient, no ground, no shadow on the ground, no props
other than her cane, no watermark, no text, no border.
```

### NEGATIVE_BLOCK (sent as negative_prompt)

```
realistic proportions, tall body, long legs, non-chibi, oversized head beyond chibi, toddler,
photorealistic, 3D render, Nendoroid figure, painterly brush strokes, watercolor, sketch lines,
thick outline western cartoon, extra ahoge, missing ahoge, straight untilted hat, missing hat,
alt costume, dress replacing jacket, missing brooch, missing thigh strap, simplified costume,
different hair color, saturated all-blue hair, huge eyes, tiny ignored details, gradient
background, colored environment, bloom, glow, rim light, text, watermark, cropped feet,
cropped hat, multiple characters, extra characters, hands with five detailed fingers
```

## 3. Delta blocks (per asset — the ONLY parts that change)

- `ACTION_BLOCK`: posture + limb placement, one or two sentences
- `EXPRESSION_BLOCK`: brow/eyelid/mouth change, anatomy-preserving (see §5)
- `GAZE_BLOCK`: `looking at the viewer` (default) / `looking slightly to her right` etc.
- `GEOMETRY_LOCK delta`: only when the semantic requires it (e.g. sitting lowers height fraction)

Example full prompt (A11 sitting):

> [CHARACTER_IDENTITY_LOCK] [STYLE_LOCK] [CAMERA_LOCK] Furina sitting on the ground with her legs
> together, knees folded to her right, hands resting on her lap around the cane. [EXPRESSION:
> calm, gentle closed-mouth smile, relaxed brows.] [GAZE: looking at the viewer.] [TRANSPARENCY_LOCK]

## 4. Generation parameters (frozen for the Alpha)

| parameter | value |
|---|---|
| model | agnes-image-2.1-flash |
| mode | img2img, init = BASE png (data URI) |
| size / ratio | 2K / 2:3 |
| negative_prompt | NEGATIVE_BLOCK |
| seed | recorded per candidate; regenerated candidates bump seed |

## 5. Expression philosophy (applies to every EXPRESSION_BLOCK)

- preserve facial anatomy; NO deformation, NO emote-pack exaggeration
- prefer: brow angle/height, eyelid aperture, gaze direction, small mouth-shape change, head
  orientation, posture, hand movement, body tension
- forbidden: giant reaction face, chibi-comedy deformation, meme faces, tears fountains,
  spiral eyes, blush floods

## 6. Prompt provenance rule

Every candidate records: prompt hash (of concatenated lock blocks), delta text, model, seed,
timestamp, init image hash. See metadata schema. Assets with unknown origin are not accepted.
