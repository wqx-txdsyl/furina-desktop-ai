# Phase 20 — Desktop Embodiment & Visible Action
# Master Plan — EXACT

## 0. Existing foundation

The repository already has immutable CharacterRuntimeFrame, FrameBuilder, RendererAdapter,
Embodiment semantics, frontend/spatial foundations and legacy renderer/assets. The future
architecture reservation explicitly chooses PNG/state images/multi-frame animation, not Live2D.

## 1. Goal

Deliver a production desktop body whose visuals faithfully consume runtime semantics, coexist with
Windows applications and make work/approval/verification states visible without becoming a source
of task truth.

## 2. Invariants

- CharacterRuntimeFrame remains the only backend→presentation contract.
- Renderer and body never write Persona, Emotion, Relationship or work state.
- GUI mutation stays on the UI owner thread; no DB/network/LLM on the frame loop.
- animation interruption, drag, positioning and emergency hide/stop are deterministic;
- work visualization references real Phase 16 state and cannot manufacture completion;
- current legacy namespaces stay in place unless a separately reviewed migration is required.

## 3. Delta order

```text
20A Presentation Runtime & Transparent Window
→ 20B Body/Animation Resolver
→ 20C Spatial Movement & Physical Interaction
→ 20D Visible Work State
→ 20E Visual/Performance Final Gate
```

Real Windows visual QA is mandatory and remains distinct from automated technical evidence.
