# Phase 16 — 16B ExecutionBackend Protocol & Registry
# Task Brief — EXACT

## 0. Authority and baseline

Governed by the Phase 16 Master Plan and accepted 16A contract. Start only after 16A external
reviewer PASS and ff-only integration. Launcher supplies the latest integration SHA.
Branch: `feature/phase16-16b-execution-backend`.

## 1. Goal

Create a backend-neutral execution protocol, registry and deterministic technical router.
Keep installation discovery, health, capabilities and run handles distinct. Wrap the existing
Native AgentRuntime as the first conformance implementation without changing its semantics.

## 2. Required recon

Inspect AgentRuntime, ToolRegistry/ToolResult, capability registry, planner fallback, cancellation
surfaces, config patterns and all callers. Search for existing backend/provider abstractions and
avoid a parallel registry.

## 3. Required abstractions

Define typed equivalents of:

- `BackendDescriptor`: stable ID, display metadata and protocol version;
- `BackendCapabilities`: explicit booleans/limits, never free-form promises;
- `BackendHealth`: installed, reachable, healthy, checked_at, reason and expiry;
- `BackendRunHandle`: backend_id, run_id and correlation only;
- `BackendEvent`/result references owned later by 16E;
- `ExecutionBackend`: `probe`, `submit`, `events`, `stop`, optional `resolve_approval` capability;
- `ExecutionBackendRegistry`: explicit registration, duplicate rejection, lookup and snapshot;
- deterministic technical router constrained by WorkContract.

Registration is not execution. `installed != reachable != healthy != capable`.

## 4. Routing rules

The router may use only:

1. explicit user/backend constraint in WorkContract;
2. allowed backend set;
3. required capabilities;
4. current non-stale health;
5. permission/workspace/budget compatibility;
6. deterministic tie-break configured by technical policy.

It must not use Persona, emotion, relationship, willingness, intimacy or an LLM. No compatible
backend means a typed mechanism-level refusal and zero submit calls.

## 5. Native adapter

Add a thin Native backend wrapper over existing `AgentRuntime.execute`. Preserve current task
record, ToolResult verification and permission behavior. A native “completed” result is still
unverified at the Phase 16 backend boundary until 16F; do not weaken AgentRuntime's existing
verification either.

## 6. Forbidden

- No Hermes HTTP implementation (16C), approval channel (16D), event state machine (16E),
  verifier (16F), durable ledger (16H) or C7 commit (16G).
- No external agent install/uninstall/upgrade; discovery is read-only.
- No MCP backend, subagent router or provider credential copying.
- No dynamic import of arbitrary backend code and no silent fallback to an unapproved backend.
- No C1–C7/DB changes.

## 7. Tests

At minimum:

1. duplicate backend IDs rejected;
2. installed-but-unhealthy is not routable;
3. stale health is not treated as healthy;
4. required capability mismatch produces zero submit;
5. explicit allowed backend constraint cannot be widened;
6. deterministic tie-break repeatability;
7. Persona/relationship changes do not affect technical routing;
8. backend exception is fail-soft typed failure, not another backend's silent execution;
9. Native adapter preserves existing result semantics;
10. registry snapshots are immutable/caller-safe;
11. no install/uninstall side effects;
12. Phase 15 cognition/store contracts unchanged.

Run targeted 16B, existing agent/capability/runtime suites, cognition regression and full suite
once. Finish `READY_FOR_REVIEW`, without merging or starting 16D.

