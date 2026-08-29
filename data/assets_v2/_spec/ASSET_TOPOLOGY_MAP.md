# ASSET_TOPOLOGY_MAP.md

- spec_id: FURINA-TOPOLOGY-V2
- status: FROZEN (topology PLAN only; no layer production tonight beyond Art Alpha)

Purpose: a reusable map of separable regions of the BASE Furina, with a classification per region.
This map later feeds Phase 20/21 (layered/procedural rig). No piece is forced into a layer tonight.

Classification vocabulary:

- ALWAYS_STATIC — never separated, never animated independently
- PROCEDURAL_CANDIDATE — runtime procedural motion (deform/swap), no discrete frames
- LAYER_CANDIDATE — separate PNG layer for compositing/swap
- FRAME_SEQUENCE_ONLY — only coherent as keyframed sequence
- SPECIAL_ONLY — rare pre-rendered clip material

## 1. Region table

| region | class | notes |
|---|---|---|
| head (whole) | ALWAYS_STATIC as unit; subdivides below | |
| face (skin) | ALWAYS_STATIC | expression variants via face swap (EXPRESSION class) |
| eyes L/R (open) | LAYER_CANDIDATE | blink via PROCEDURAL eyelid overlay |
| eyelids / blink overlay | PROCEDURAL_CANDIDATE | 3-frame blink sprite (open/half/closed) |
| irises/pupils | LAYER_CANDIDATE | gaze shift = iris layer translation within eye mask |
| eyebrows | LAYER_CANDIDATE | small set of brow shapes per mood |
| mouth | LAYER_CANDIDATE | small mouth-shape set (talk loop) |
| neck | ALWAYS_STATIC | |
| front hair (bangs + face locks) | LAYER_CANDIDATE | sway deformation |
| ahoge | PROCEDURAL_CANDIDATE | springy lag; spring params per action |
| side hair L | LAYER_CANDIDATE | her right, shorter tail |
| side hair R (long showpiece tail) | LAYER_CANDIDATE | primary lag/sway element |
| rear hair | ALWAYS_STATIC | rarely visible separately |
| hat | LAYER_CANDIDATE | lifts with jump/ surprise actions |
| hat ornaments (gold/gems) | ALWAYS_STATIC (attached to hat layer) | |
| hat ribbon/feather ornament | PROCEDURAL_CANDIDATE | secondary lag after hat |
| brooch / ascot | ALWAYS_STATIC | |
| torso (jacket + shirt + bow back) | ALWAYS_STATIC as unit | breath = subtle torso scale, PROCEDURAL |
| upper arm L/R | LAYER_CANDIDATE | limited poses; else FRAME_SEQUENCE |
| forearm L/R | LAYER_CANDIDATE | same |
| hands L/R (gloved) | LAYER_CANDIDATE | small pose set (open, point, hold cane) |
| waist / shorts | ALWAYS_STATIC | |
| coat tails (swallowtail back) | PROCEDURAL_CANDIDATE | sway in locomotion |
| thigh strap + pendant | PROCEDURAL_CANDIDATE | pendant lag |
| upper legs / lower legs | FRAME_SEQUENCE_ONLY | chibi legs are short; layering gives little |
| sock covers / shoes | ALWAYS_STATIC per foot pose | |
| cane/rapier | LAYER_CANDIDATE | attached to hand R anchor |
| whole-body shadow | FX asset (`fx_contact_shadow`) | never baked into masters |
| Hydro FX (droplets, ripple, aura) | FX assets / SPECIAL_ONLY | separate transparent overlays |
| speech/hud attachment zone | runtime concept | see geometry spec speech_anchor |

## 2. Priority for future layer extraction (Phase 20/21)

1. eyes/iris/blink overlay (procedural life)
2. mouth set (talk loop)
3. side hair R tail + ahoge (lag/sway)
4. hat + ornament (bounce)
5. arms/hands (gesture set)
6. cane (attach/detach semantics)

## 3. Composition rules

- Layers must be cut from an ACCEPT-grade master of the matching pose so palette/line matches.
- Layer cut edges keep the same outline color as the master (no halo, no cut-line glow).
- Every layer ships metadata referencing its source master asset_id.
