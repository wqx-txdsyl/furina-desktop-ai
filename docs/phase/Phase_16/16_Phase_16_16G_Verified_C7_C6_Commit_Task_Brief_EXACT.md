# Phase 16 — 16G Verified C7/C6 Commit
# Task Brief — EXACT

## 0. Authority and baseline

Start only after accepted 16H integration. Governed by frozen C7/C6 contracts, 16F reports and
16H durable commit claims. Branch: `feature/phase16-16g-verified-truth-commit`.

## 1. Goal

Project finalized work-domain outcomes into cognition truth exactly once: verified success through
the existing C7 owner as `COMPLETED_VERIFIED`, truthful non-success through existing statuses, and
one provenance-correct C6 lifecycle result. No backend or worker writes cognition directly.

## 2. Required recon

Re-read `agent_history.py`, C7 DDL, `CognitionHub.persist_agent_result`, dispatcher C7→C6 path,
event type registration and all current callers/writers. Audit whether the existing dispatcher
already emits the required C6 event so Phase 16 does not double-write it.

If implementation requires any C7 schema/enum/writer change, set
`FROZEN_CONTRACT_EXCEPTION_REQUIRED=REQUIRED` and stop before code changes.

## 3. Projection table

Lock an explicit mapping equivalent to:

- 16F VERIFIED → C7 `COMPLETED_VERIFIED`, `verified=true`;
- verification FAILED/backend failure → existing `FAILED` when failure is final and evidenced;
- INCONCLUSIVE/backend done without adequate proof → existing `UNVERIFIED`;
- confirmed cancellation → existing `CANCELLED`;
- UNKNOWN/BLOCKED_APPROVAL/VERIFYING/REPAIRING/BACKEND_DONE_UNVERIFIED → no C7 terminal write.

Only the owner-thread `CognitionHub.persist_agent_result` path may perform the write.

## 4. Exactly-once protocol

- Consume 16H's durable truth-commit claim keyed by contract/task/verifier report identity.
- Use stable existing task_id; do not add contract_id to C7.
- A crash before/after C7 or C6 write must reconcile without duplicate C7 row, duplicate C6 result
  event or lost final state.
- Persist/compare verifier report hash; a conflicting second report cannot overwrite accepted truth.
- Stale workers and backend events cannot acquire the commit claim.

## 5. C6 provenance

Prefer the existing dispatcher `AGENT_COMPLETED`/`AGENT_FAILED` vocabulary and include status,
verified, contract_id, task_id, run_id and verifier-report reference in bounded payload/provenance.
Add a new event type only if recon proves existing types cannot express the truth; never emit both
for one conclusion. C6 event formation failure must not produce a provenance-less downstream C3.

## 6. Memory and presentation boundary

- Automatic C3 write remains OFF; no new memory writer.
- Result summary is grounded in verified report and bounded/redacted.
- User-visible reporting remains outside this Delta's backend path and must pass Single Mouth.
- Work data never updates Persona, UserModel or Relationship.

## 7. Tests

At minimum:

1. verified→one C7 COMPLETED_VERIFIED via real owner path;
2. forged backend completed never completes C7;
3. failed/unverified/cancelled mapping accuracy;
4. forbidden WorkExecution states never written to C7;
5. duplicate commit and concurrent stale worker exactly-once;
6. crash at each C7/C6 commit boundary then restart reconciliation;
7. conflicting verifier report rejected;
8. one C6 result with resolvable provenance and both IDs;
9. C6 failure produces no provenance-less C3;
10. C3 automatic writes zero;
11. full writer audit finds no second C7 owner;
12. C7 schema/enum tuple equality and Phase 15 tests preserved.

Run targeted 16G, real hub/store integration, cognition suite, Phase 15 frozen gates and full suite
once. Stop at `READY_FOR_REVIEW`.

