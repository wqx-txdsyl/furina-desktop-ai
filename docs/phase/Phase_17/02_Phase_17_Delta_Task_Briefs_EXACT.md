# Phase 17 — Delta Task Briefs — EXACT

All Deltas inherit `../00_PHASE_17_24_PLANNING_AUTHORITY.md`. Launcher supplies the real BASE_SHA.

## 17A — Agency Decision Contract

**Goal:** define immutable public inputs/outputs and ownership for subjective decisions.

Required:

- typed context using bounded references to Persona, emotion, relationship climate, active plan,
  presence, interruption cost and WorkContract summary;
- closed decisions: ENGAGE / NEGOTIATE / DEFER / REFUSE / SILENT;
- closed public reason categories; no chain-of-thought storage;
- deterministic default and fail-closed behavior;
- no C1–C7 or WorkContract mutation;
- lexical identity, defensive copy, bounded serialization and secret-safe diagnostics.

Tests: schema exactness, mutation resistance, missing/stale truth, hostile strings, no durable
writer, no permission call and stable deterministic fallback.

Stop at `READY_FOR_REVIEW`; do not implement proactive behavior in 17A.

## 17B — Willingness, Refusal & Negotiation

**Goal:** apply AgencyDecision before Phase 16 submission and express the result through Single
Mouth.

Required:

- explicit user intent and hard safety constraints dominate subjective preference;
- refusal/defer/negotiation never masquerade as backend failure;
- ENGAGE still passes through normal Phase 16 authorization;
- user can ask for reason, retry, narrow scope or override only where policy permits;
- character backend preference is a tie-breaker after technical routing constraints;
- bounded policy; no LLM-only authority and no hidden random refusal.

Tests: willingness cannot widen scope; denial produces zero backend call; technical unavailable is
not character refusal; explicit backend choice respected; dialogue grounded in public reason;
Single Mouth and owner-thread proofs.

## 17C — P17-D1/D2 Proactive Policy

**Goal:** implement the two permanently deferred Phase 15 items.

Required:

- active C4 plan follow-up only when provenance, lifecycle, time and presence are valid;
- persistent bounded quota/cooldown/mute using an existing appropriate owner or an explicitly
  approved operational record—not a new cognition Store;
- relationship climate affects approach/silence/intensity, never factual memory retrieval rights;
- direct conversation, approval and active work take priority;
- ignore/dismiss/mute prevents nagging; restart preserves documented limits;
- no holiday/birthday UI choreography—that belongs to Phase 19/20.

Tests: no presence/no follow-up; stale/superseded plan blocked; daily cap; mute/restart; direct turn
preemption; relationship extremes remain bounded; C4/C5 rows unchanged.

## 17D — Work-Persona Integration & Final Gate

**Goal:** prove Furina remains Furina while using Phase 16 work execution.

Required:

- agency decision trace references contract/run without becoming execution truth;
- success/failure language grounded in verified report;
- pressure suite: repeated requests, failure, cancellation, risky requests, relationship climates;
- long-run interruption-rate and refusal-rate bounds;
- real dialogue/manual scenarios reviewed by a human;
- full writer audit and complete suite three times.

Output only Phase 17 closeout evidence. Production fixes require a separate reviewer micro-patch.
