# Phase 16 — 16H Recovery, Idempotency, Cancellation & Backpressure
# Task Brief — EXACT

## 0. Authority and baseline

Start only after accepted 16F integration. This Delta intentionally precedes 16G so truth commits
can consume a durable idempotency/recovery foundation. Branch:
`feature/phase16-16h-recovery-idempotency`.

## 1. Goal

Implement the durable work-domain ledger, crash/restart reconciliation, contract/run idempotency,
real cancellation and bounded event buffering. The ledger is authoritative only for work execution;
it is not a new cognition store and cannot become Persona/Memory/Relationship truth.

## 2. Required recon and storage decision

Inspect existing SQLite ownership, migrations, thread model, app startup/shutdown, C7/C6 stores,
dispatcher queues and Hermes status/reconnect behavior. Produce a schema/owner decision before
editing. Reuse existing DB infrastructure only if it preserves owner-thread and transaction rules.

This brief authorizes the minimum new **work-domain** persistence needed for immutable contracts,
execution attempts, backend bindings, terminal/critical events and commit/recovery markers. It does
not authorize changes to any C1–C7 table, enum or writer. Migration must be additive, versioned,
idempotent and covered by upgrade/reopen tests.

## 3. Durable invariants

- Unique immutable `(contract_id, contract_hash)`; same ID/different hash is conflict.
- At most one active execution claim per contract.
- Every attempt has stable attempt_id/run_id/backend_id and monotonic persisted state/version.
- WorkExecutionState persists only in work tables; forbidden C7 states remain forbidden.
- Critical events and terminal evidence survive restart; high-volume progress may be coalesced.
- State transitions use compare-and-set/transaction semantics so stale workers cannot overwrite a
  newer terminal state.
- Ledger exposes a truth-commit claim/marker for 16G but does not write C7/C6 itself.

## 4. Recovery

At startup:

1. load non-terminal executions;
2. mark reconciliation-in-progress/UNKNOWN without writing C7;
3. query backend status when supported;
4. recover terminal evidence and invoke 16F verification when evidence is sufficient;
5. otherwise remain typed UNKNOWN/FAILED according to explicit timeout policy;
6. block a second submit for the same contract until reconciliation closes or reviewer-approved
   takeover occurs.

Never convert “process disappeared” directly into verified, completed or a new duplicate run.

## 5. Cancellation

- Cancel request moves RUNNING/WAITING/REPAIRING to CANCELLING and persists intent.
- Call backend stop once per active run; repeated cancel is idempotent.
- Remain CANCELLING until terminal backend evidence or explicit timeout policy resolves.
- Pre-submit cancel creates no backend run.
- Cancel while approval-waiting invalidates outstanding approval; late approval cannot restart.
- C7 CANCELLED is not written here; 16G owns final cognition projection.

## 6. Backpressure

- Use bounded per-run/global queues or equivalent bounded structures.
- Never drop run terminal, approval, cancel, disconnect/reconnect, verification verdict or truth
  commit boundary events.
- Coalesce/drop progress/token/tool ticks by deterministic policy and expose counters.
- Sustained spam cannot grow RAM, DB rows or payload bytes without bound.
- Backpressure never blocks the owner thread or 60fps loop on DB/vector/network I/O.

## 7. Tests

At minimum:

1. additive migration from frozen Phase 15 DB and idempotent reopen;
2. C1–C7 schema/row tuple equality across migration;
3. same contract concurrent submit yields one active run;
4. same ID/different hash conflict;
5. stale state/version write rejected;
6. crash at pre-submit/post-submit/mid-SSE/post-backend/pre-verification boundaries;
7. UNKNOWN verify-on-recovery and duplicate-run prevention;
8. cancellation before/during approval/tool/repair and late-event handling;
9. critical events never dropped under flood;
10. progress memory/DB cardinality bounded under large attack;
11. restart preserves terminal evidence and clears only documented operational buffers;
12. no C7/C6/C3 write and no 60fps DB/network path.

Run targeted 16H, migration/restart/agent/cognition regressions, Phase 15 frozen gates and full
suite once. Stop at `READY_FOR_REVIEW`.

