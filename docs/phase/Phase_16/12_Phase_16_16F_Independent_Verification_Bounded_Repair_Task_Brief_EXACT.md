# Phase 16 — 16F Independent Verification & Bounded Repair
# Task Brief — EXACT

## 0. Authority and baseline

Start only after accepted 16C integration. Governed by WorkContract verification standards,
16E states and backend evidence transport. Branch: `feature/phase16-16f-independent-verification`.

## 1. Goal

Create a task-level verifier owned by Furina. It independently evaluates backend evidence against
the immutable WorkContract, and optionally performs a strictly bounded repair loop. Backend claims,
exit code zero and fluent final text are never sufficient proof.

## 2. Required recon

Inspect AgentRuntime `_verify`, ToolResult `verified`, artifact records, filesystem/process/tool
verification primitives, task_record structure and existing C7 persistence boundary. Reuse
deterministic checkers; do not fork step-level truth.

## 3. Verification model

Define typed equivalents of:

- `EvidenceBundle`: bounded, immutable references to artifacts, normalized terminal events and
  local observations with hashes/provenance;
- `VerificationCheck`: deterministic checker ID, inputs, result and explanation;
- `VerificationReport`: contract_id/run_id, standard hash, per-check evidence, verdict, timestamps;
- verdicts `VERIFIED`, `FAILED`, `INCONCLUSIVE`—only verifier may produce VERIFIED.

Deterministic checks run first. An LLM may summarize or propose checks only when explicitly
configured; it cannot override a failed deterministic check or become sole evidence.

## 4. Artifact/evidence rules

- Enforce count/size/MIME/path limits and workspace containment.
- Hash local artifacts before evaluation; reject missing, mutated, escaped or unsupported items.
- Backend-provided tests/logs are claims until independently rerun or corroborated.
- Evidence and reports contain no secrets and are bounded for persistence/diagnostics.

## 5. Repair loop

- Repair is allowed only when WorkContract permits it and budget remains.
- Every attempt gets a distinct attempt_id/run_id bound to the same immutable contract.
- Re-enter at BACKEND_DONE_UNVERIFIED and verify again; never patch the verdict.
- Stop on success, hard failure, denial, cancellation, timeout, exhausted attempts/cost/time or
  repeated identical failure signature.
- No recursive/unbounded repair and no widening contract/permission/backend set.

## 6. Forbidden

- No C7/C6/C3 writes (16G), durable recovery ledger (16H) or user-visible success report.
- No verifier that simply trusts backend status, text or its own self-report.
- No modification of WorkContract during repair.
- No C1–C7 schema/writer changes.

## 7. Tests

At minimum:

1. valid deterministic evidence verifies;
2. forged completed/text/exit-zero remains unverified;
3. artifact tamper/path escape/oversize/unknown MIME rejected;
4. mixed checks fail if a required check fails;
5. inconclusive never maps to VERIFIED;
6. backend and verifier responsibilities separated;
7. repair succeeds only after fresh evidence;
8. attempt/time/cost limits stop exactly;
9. repeated identical failure circuit-breaks;
10. cancellation/approval denial prevents repair;
11. contract hash unchanged across attempts;
12. no C7/C6/C3 writes.

Run targeted 16F, agent verification/artifact regressions, cognition suite and full suite once.
Stop at `READY_FOR_REVIEW`.

