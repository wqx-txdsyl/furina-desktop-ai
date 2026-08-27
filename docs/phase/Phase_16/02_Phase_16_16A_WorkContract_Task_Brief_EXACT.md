# Phase 16 — 16A WorkContract
# Task Brief — EXACT

## 0. Authority and execution protocol

This brief is governed by `01_Phase_16_Work_Sovereignty_Verified_Agent_Execution_Master_Plan_EXACT.md`.
It authorizes only 16A. The execution launcher must provide the latest externally accepted
`feature/phase16-work-sovereignty` SHA. Record actual `git rev-parse HEAD` and
`git status --short`; stop on an unknown baseline or overlapping user changes.

Branch: `feature/phase16-16a-work-contract`.
Do not merge, start 16B, or claim `16A_PASS`; external reviewer owns acceptance.

## 1. Goal

Introduce an immutable, validated, Furina-owned `WorkContract` data contract and vocabulary.
16A defines what was authorized, where work may occur, what counts as success, and the hard
budgets. It does not execute work, choose a backend, ask an LLM whether Furina is willing,
or write C1–C7.

## 2. Required recon

Before editing, inspect:

- current AgentRuntime request/task record types;
- C6 canonical USER event identity and `source_event_id` handling;
- C7 `task_id` and frozen schema;
- Permission/AuthorizationContext types;
- existing serialization, clock and ID conventions.

Document the chosen module path and prove no existing equivalent contract already owns this role.

## 3. Required contract

Implement typed immutable structures equivalent to:

- `WorkContract`;
- `WorkspaceScope` with explicit readable/writable roots;
- `ExecutionBudget` for time, cost and attempts;
- `ArtifactExpectation`;
- `VerificationStandard` containing machine-checkable criteria or typed verifier references;
- `ApprovalPolicyRef` as a reference only—16D owns grants.

The contract must contain stable `contract_id`, version and deterministic content hash;
canonical request, objective, in/out commitment scope, allowed capabilities/backends,
workspace scope, budgets, artifact expectations, verification standard and canonical
`source_event_id`.

## 4. Validation invariants

- Reject empty objective, source event, allowed backend/capability set when required by scope,
  invalid or broad workspace roots, negative/unbounded budgets, duplicate artifact identities,
  and unverifiable success standards.
- Hash excludes runtime state and is stable across serialization round-trips.
- Same `contract_id` + different immutable content is a conflict, never an update.
- Backend input may receive a read-only serialized projection; backend output cannot mutate it.
- No default grants filesystem root, unrestricted shell, unlimited time/cost/attempts, or
  permanent approval.
- Contract may describe a user-chosen backend constraint, but contains no personality-driven
  preference or willingness score.

## 5. Forbidden

- No execution ledger, backend registry, Hermes adapter, approval runtime or verifier.
- No database migration unless recon proves persistence is unavoidable; if so, stop and request
  a new explicit brief rather than adding one.
- No C1–C7 schema/enum/writer change; no C3/C4/C5 writes.
- No `grant_permanent: bool`, emotion, intimacy, relationship climate, refusal prose generator,
  UI, renderer, TTS/ASR or Phase 20 work.

## 6. Tests

At minimum lock:

1. valid minimal and fully populated contract;
2. deterministic ID/hash and serialization round-trip;
3. same ID + changed content conflict;
4. invalid budgets and empty verification rejected;
5. unsafe/broad workspace scope rejected;
6. backend projection cannot mutate canonical contract;
7. willingness/emotion/relationship fields absent;
8. no permanent boolean authorization;
9. C1–C7 row/schema tuple equality before/after contract construction;
10. restart/serialization semantics are truthful—16A creates no hidden persistence.

Run the 16A file, relevant agent/cognition contract suites, then the full repository suite once.
No skip/xfail/assertion weakening.

## 7. Handoff

Report baseline/final SHA, changed files, exact field set, validation rules, hash algorithm,
tests, full-suite result, C1–C7 unchanged proof, remaining gaps and local/remote equality.
Finish `READY_FOR_REVIEW`.

