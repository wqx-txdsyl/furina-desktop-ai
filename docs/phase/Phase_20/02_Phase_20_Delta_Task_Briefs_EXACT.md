# Phase 20 — Delta Task Briefs — EXACT

## 20A — Presentation Runtime & Transparent Window

Implement the production transparent desktop window, DPI/multi-monitor/taskbar handling,
click-through/hit regions, z-order policy, pause/hide/emergency stop and lifecycle cleanup. Preserve
UI-thread ownership and measure idle/active CPU, memory and frame pacing.

## 20B — Body & Animation Resolver

Map CharacterRuntimeFrame semantics to versioned asset keys, clips, transitions, facing and
interruptibility. One animation owner only. Missing assets use documented safe fallbacks; no
semantic inference from filenames; no Live2D.

## 20C — Spatial Movement & Interaction

Complete bounded walking/path/arrival, safe screen regions, target-window vicinity, drag takeover,
pet/poke/feed hitboxes, collision and critical-UI avoidance. Frontend emits interaction events;
backend remains the meaning owner. Test DPI, multi-monitor, taskbar, window changes and manual drag.

## 20D — Visible Work State

Represent thinking, execution, approval wait, verification, repair, cancellation, completion and
failure from real work-state references. Input simulation and body animation remain separate.
Animation must lag/fail safely and never upgrade backend truth.

## 20E — Visual & Performance Final Gate

Run 24h-equivalent bounded soak, frame-time/CPU/GPU/memory checks, owner-thread audit, interaction
latency, multi-monitor Windows UAT and a human visual checklist. Run full suite three times.
Evidence-only branch; fixes require micro-patches.
