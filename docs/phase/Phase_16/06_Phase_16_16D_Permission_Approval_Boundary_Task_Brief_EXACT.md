# Phase 16 — 16D Permission & Approval Boundary
# Task Brief — EXACT

## 0. Authority and baseline

Start only after accepted 16B is ff-only integrated. Governed by the Master Plan, 16A and 16B.
Branch: `feature/phase16-16d-permission-approval`.

## 1. Goal

Add a first-class asynchronous approval channel above the existing synchronous L0–L3
`PermissionManager`, while ensuring inner backend approval can never widen the outer WorkContract.

## 2. Required recon

Map every PermissionManager/AuthorizationContext call, dangerous-tool confirmation path,
dispatcher ownership boundary, user-ingress event identity and current timeout behavior. Identify
the owner thread that may mutate approval state.

## 3. Required model

Implement typed equivalents of:

- `ApprovalRequest`: approval_id, contract_id, run_id, tool/capability, normalized arguments or
  redacted summary, requested scope, reason, risk level, created/expires timestamps, provenance;
- `ApprovalDecision`: approve_once, approve_session, deny, timeout, revoked;
- optional `AuthorizationGrant`: only if persistent/session grants are needed; must be scoped,
  revocable, user-originated and provenanced;
- `ApprovalBroker`: create, wait/observe, resolve exactly once, timeout and revoke.

State ownership must be explicit. Duplicate/late/conflicting resolutions return typed outcomes.

## 4. Two-layer invariant

Effective permission is the intersection of:

```text
WorkContract scope
∩ existing PermissionManager L0–L3 result
∩ explicit approval decision/grant
∩ backend capability
```

No layer may expand another. Denial/timeout produces a visible work-domain event and no tool call.

## 5. Permanent/session grants

- No unrestricted “always approve”.
- A durable/session grant must originate from a canonical USER decision, bind exact capability or
  normalized tool pattern and workspace scope, carry issued_at/expiry/revocation/provenance, and
  remain narrower than the WorkContract.
- Backend text, adapter defaults, inferred intent and LLM output cannot create or expand grants.
- Revocation applies before the next tool boundary.

## 6. Forbidden

- Do not replace or weaken PermissionManager.
- Do not implement willingness/refusal personality behavior.
- No UI modal/renderer; expose domain events/API only.
- No Hermes adapter, verifier, C7 writes, C1–C7 schema or database migration unless a dedicated
  approval store is explicitly proven necessary; if persistence is required beyond existing
  facilities, stop for reviewer scope approval.

## 7. Tests

At minimum:

1. L0/L1 existing semantics preserved;
2. L2/L3 cannot run without the required existing authorization and new approval;
3. inner request broader than contract denied before tool execution;
4. approve-once consumed exactly once;
5. duplicate/conflicting/late resolution idempotent;
6. timeout denies and emits one terminal approval event;
7. canonical user provenance required for durable/session grant;
8. grant scope/expiry/revocation enforced;
9. backend cannot synthesize permanent grant;
10. cancellation while waiting unblocks and never executes tool;
11. secrets/arguments redacted in user-visible/audit payloads;
12. existing PermissionManager regression and C1–C7 unchanged.

Run targeted 16D, permission/agent suites, cognition regression and full suite once. Stop at
`READY_FOR_REVIEW`; do not start 16E.

