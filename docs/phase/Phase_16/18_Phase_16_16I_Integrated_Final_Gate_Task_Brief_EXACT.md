# Phase 16 — 16I Integrated Final Gate
# Task Brief — EXACT

## 0. Gate authority

16I begins only after 16A, 16B, 16D, 16E, 16C, 16F, 16H and 16G each received external reviewer
PASS and were ff-only integrated into `feature/phase16-work-sovereignty`. Launcher supplies the
accepted integration SHA. Branch: `feature/phase16-16i-integrated-final-gate`.

This is an evidence-only final gate. Production/test fixes are forbidden. A failure produces a
separate reviewer micro-patch task; do not repair it inside this branch.

## 1. Required ancestry and scope audit

- Verify local/remote integration equality and accepted Delta SHAs in ancestry.
- Compare Phase15 frozen SHA to Phase16 base; list every production/test/schema change by Delta.
- Confirm only authorized work-domain tables were added and C1–C7 schema/enum/writers unchanged.
- Confirm no task branch merge commits/unknown commits and document manifest matches history.

## 2. Contract and routing gates

- WorkContract immutable/hash/version/source/workspace/budget/verification invariants.
- Technical router uses only explicit constraints/capability/health/permission/budget.
- Persona/emotion/relationship/willingness cannot affect Phase16 routing.
- Mechanism refusal yields zero backend calls.

## 3. Permission and backend gates

- Permission intersection cannot widen WorkContract.
- No unscoped always-approve; persistent grants are user-originated, scoped, revocable, provenanced.
- Hermes Runs API active probe, auth, SSE, reconnect, approval and stop behavior verified.
- No CLI/proxy/webhook execution fallback.
- Hermes profile/workspace/SOUL/memory isolation holds.

## 4. Truth and recovery gates

- Backend completed remains BACKEND_DONE_UNVERIFIED.
- Only 16F may produce VERIFIED.
- Repair is bounded and cannot mutate contract/permission.
- Same contract cannot double-run; stale workers cannot overwrite terminal state.
- Restart UNKNOWN path reconciles and verifies before truth.
- Cancellation remains CANCELLING until real terminal evidence.
- Exactly one C7 result through the existing owner and one provenance-correct C6 result.
- No automatic C3, C4, C5 or Persona writes.

## 5. G-S1 Single Mouth

Run production-path causal tests/traces proving backend text, tool progress, approval messages and
result summaries do not bypass Furina's dialogue owner. During active run, direct user input retains
its ordering and backend cannot independently deliver to messaging/webhook/peer channels.

## 6. G-S2 SOUL/Memory isolation

Static and runtime audit:

- backend configuration has no Furina Persona/SOUL/C1–C7 write path;
- Hermes memory/profile data cannot be read as Furina truth;
- canonical user provenance gates remain required;
- no new memory, relationship or user-model writer;
- no Phase20 renderer/body/TTS/ASR assets or code.

## 7. Required test gates

Run once each unless the repository's accepted task docs name a stricter command:

- all Phase16 Delta targeted tests;
- permission/agent/runtime/artifact/migration/restart suites;
- all `tests/cognition`;
- Phase15 final/frozen gates;
- static writer/schema/event/60fps I/O audits.

Then run the complete repository suite **three independent times**. Record count, failures,
skips/xfails and duration for each. Do not use reruns to hide a failure.

## 8. Controlled live Hermes UAT

Using a dedicated harmless temporary workspace/profile and the configured local API Server:

1. health/capability probe;
2. submit one bounded read-only contract;
3. observe structured run events;
4. reconcile final backend status as UNVERIFIED;
5. independently verify the requested harmless result;
6. prove no direct user-visible bypass and no Furina truth/memory mutation.

If a configured Hermes Runs API is unavailable, report a Phase16 blocker; mocks alone cannot close
the first-adapter product claim. Never expose credentials or run destructive tools.

## 9. Output discipline

Only task/final-closeout documents may change. Fill document 19 with real evidence, commit and push
the gate branch, verify local/remote and stop. Do not merge, tag, start Phase17/20, or claim
`PHASE_16_FINAL_GATE=PASS`.

