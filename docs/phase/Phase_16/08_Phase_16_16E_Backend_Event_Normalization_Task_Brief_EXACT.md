# Phase 16 — 16E Backend Event Normalization
# Task Brief — EXACT

## 0. Authority and baseline

Start only after accepted 16D integration. Governed by Master Plan §§5A/10 and prior contracts.
Branch: `feature/phase16-16e-event-normalization`.

## 1. Goal

Create one backend-neutral event envelope and deterministic WorkExecution state reducer. External
backend vocabulary is input; only the reducer owns WorkExecutionState. This Delta does not execute
Hermes and does not write C7.

## 2. Required recon

Inventory Native AgentRuntime progress/results, ToolResult, dispatcher messages, current event
queues and C6 registration behavior. Inspect current Hermes Runs/SSE vocabulary from the installed
or pinned official surface, but do not couple production types to Hermes field names.

## 3. Normalized event contract

Define typed envelopes with at least event_id, backend_id, contract_id, run_id, sequence,
occurred_at/received_at, kind, sanitized payload, terminal/critical flags and provenance.

Required semantic kinds include equivalents of:

- run accepted/started;
- approval requested/resolved;
- tool started/progress/completed;
- backend completed/failed/cancelled;
- stop requested/stopping;
- transport disconnected/reconnected;
- protocol error.

Unknown external kinds remain observable as typed unknown events; they cannot create a success
transition.

## 4. State reducer

Implement and test legal transitions among:

`IDLE, STARTING, RUNNING, WAITING_PERMISSION, BLOCKED_APPROVAL, TOOL_RUNNING (subphase),
BACKEND_DONE_UNVERIFIED, VERIFYING, REPAIRING, CANCELLING, CANCELLED, VERIFIED, FAILED, UNKNOWN`.

Rules:

- backend completed maps only to `BACKEND_DONE_UNVERIFIED`;
- `VERIFIED` is reserved for 16F and cannot be produced by backend mapping;
- duplicate events are idempotent; out-of-order events cannot regress a terminal state;
- illegal transitions return diagnostics without silently changing state;
- `TOOL_RUNNING` is a subphase/observation and must not destroy the enclosing run state;
- these states never enter C7.

## 5. Backpressure boundary

Define event priority now; durable implementation arrives in 16H. Terminal, approval, cancellation,
disconnect and verification-boundary events are critical and never droppable. Progress/token/tool
ticks may be coalesced or dropped under pressure. Do not persist token streams as cognition events.

## 6. C6 boundary

Backend operational events are not automatically C6 truth. 16E may define a projection interface,
but 16G owns any C6 append. No duplicate C6 event vocabulary is introduced here.

## 7. Tests

At minimum:

1. full legal transition table;
2. illegal transition fail-safe;
3. completed→BACKEND_DONE_UNVERIFIED, never VERIFIED;
4. duplicate/out-of-order sequence handling;
5. unknown external event observable but non-authoritative;
6. approval and cancellation paths;
7. disconnect→UNKNOWN policy boundary;
8. critical event classification;
9. payload redaction and bounded size;
10. no WorkExecutionState value written to C7/C6;
11. Native and Hermes-shaped fixtures normalize to the same semantics;
12. reducer deterministic under repeated replay.

Run targeted 16E, agent event regressions, cognition suite and full suite once. Stop at
`READY_FOR_REVIEW`.

