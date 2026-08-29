# ASSET_TAXONOMY_AND_MANIFEST.md

- spec_id: FURINA-TAXONOMY-V2
- status: FROZEN (structure only — tonight builds the manifest skeleton, NOT the full library)

## 1. Category taxonomy (frozen)

| category | meaning | typical class |
|---|---|---|
| POSTURE | base body states (stand/sit/lie/walk…) | master |
| EXPRESSION | facial variants per posture | face layer or master |
| GAZE | eye-direction variants | iris layer offset |
| MICRO_ACTION | small delayed reactions (poke, pet) | frame family |
| LOCOMOTION | walk/run/drag cycles | frame families |
| INTERACTION | user-driven responses (lift, drag) | frame families |
| WORK_ACTION | Furina acting on work states (think/execute/verify/report) | masters + frame families |
| SPECIAL | rare cinematic moments | special clips |
| TRANSITION | between-state bridges (sit_down, stand_up…) | frame families |
| FX | hydro/contact-shadow overlays | fx assets |

## 2. Manifest skeleton (created tonight)

`data/assets_v2/metadata/manifest_v2.json`:

```json
{
  "character": "furina",
  "version": "v2-alpha",
  "base_identity": {
    "file": "_base/furina-base.png",
    "identity_version": "furina-base-2026-08",
    "style_version": "FURINA-STYLE-LOCK-V2"
  },
  "specs": ["FURINA_IDENTITY_LOCK", "ASSET_STYLE_LOCK", "ASSET_GEOMETRY_AND_ANCHOR_SPEC",
             "ASSET_TOPOLOGY_MAP", "ASSET_TAXONOMY_AND_MANIFEST", "MASTER_GENERATION_PROMPT_SPEC"],
  "categories": { "<category>": { "planned": N, "accepted": N } },
  "entries": []
}
```

Each entry follows the metadata schema in ASSET_GEOMETRY_AND_ANCHOR_SPEC.md §4.

## 3. Target scale (FUTURE — do NOT generate tonight)

| group | planned |
|---|---|
| full-body masters | 55–70 |
| useful layers | 45–65 |
| frame-sequence families | 35–45 |
| expanded animation frames | 350–500 |
| rare special clips | 8–12 |
| procedural FX assets | 20–30 |
| accepted core assets | ≈150–190 |
| runtime files | ≈500–700 |

## 4. Naming convention (frozen)

```
furina_v2_<alpha_id>_<posture>_<semantic>_<facing>[_fNN].png
```

- alpha ids: `a01` … `a20`
- sequences: family id + frame index (`_f00` … )
- layers: `_layer_<region>` suffix, source master id in metadata
- fx: `fx_<name>` in `fx/`

## 5. Directory contract

```
data/assets_v2/
  _base/            BASE copy + inspections (read-only)
  _spec/            all lock/spec documents
  masters/          accepted full-body masters
  layers/           future layer extractions
  sequences/        future frame families
  fx/               hydro/contact-shadow overlays
  raw/              unprocessed generator output (chroma background)
  review/           comparison sheets, review artifacts
  rejected/         failed candidates with reason in metadata
  metadata/         manifests, provenance
```
