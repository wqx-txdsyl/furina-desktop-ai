# Phase 21 — Production Art & Animation Library
# Master Plan — EXACT

## 0. Existing foundation

The repository contains legacy and Night asset work plus renderer-facing asset conventions. These
are valuable Art Alpha inputs. Phase 21 begins only after Phase 20 freezes the production body,
anchor, direction, transition and fallback contracts that the library must satisfy.

## 1. Goal

Deliver a coherent, legally traceable and technically deterministic Furina production art library
covering daily life, work, emotion, interaction, props and transitions.

## 2. Invariants

- Furina's approved identity, silhouette, costume and palette are locked before bulk production.
- Every shipped asset has provenance, creator/tool record and distribution-right status.
- Asset filenames never create runtime semantics; versioned manifests provide explicit meaning.
- Missing or invalid assets fall back safely and can never change backend truth.
- Automated checks do not replace frame-by-frame human visual review.
- The shipped body remains PNG/state-image/multi-frame animation; no Live2D scope is implied.
- Generated or placeholder material is never represented as final reviewed production art.

## 3. Delta order

```text
21A Asset Standard & Character Identity Lock
→ 21B Core Life Animation Pack
→ 21C Work, Emotion, Prop & Transition Pack
→ 21D Packaging, Resolver & Automated QC
→ 21E Visual Acceptance & Long-run Final Gate
```

The final gate requires both deterministic technical evidence and named human visual acceptance.
