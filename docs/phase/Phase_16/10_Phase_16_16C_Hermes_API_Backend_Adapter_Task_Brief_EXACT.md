# Phase 16 — 16C Hermes API Backend Adapter
# Task Brief — EXACT

## 0. Authority and baseline

Start only after 16E external reviewer PASS and ff-only integration. Governed by Master Plan §8,
16B protocol, 16D approval and 16E normalization. Branch: `feature/phase16-16c-hermes-api-adapter`.

## 1. Goal

Implement Hermes as the first external ExecutionBackend through its authenticated HTTP API Server
Runs surface. The adapter transports an already-authorized WorkContract and normalized events;
Hermes never owns contract truth, verification, user-visible speech or C1–C7.

## 2. Required live/source recon

Before production code, record the installed Hermes version and probe authenticated local API
Server endpoints. Confirm actual response/event shapes for health, `/v1/capabilities`, run submit,
status, SSE events, approval, stop and reconnect. Never assume current documentation equals the
installed build. Do not expose credentials in logs/tests/closeout.

If Runs + event SSE are absent, stop with `HERMES_RUNS_SURFACE_UNAVAILABLE`; do not fall back to
`hermes chat -q`, webhook, proxy or chat-completions as the WorkContract execution path.

## 3. Capability probe

- `/v1/capabilities` advertisement is necessary but not sufficient.
- Perform bounded, non-destructive active handshakes for required endpoints.
- Cache positive/negative probe results with short TTL; auth failure, malformed payload, timeout,
  contradiction or missing capability fails closed with a typed reason.
- Capability/health snapshots are derived operational data, not memory or C7 truth.
- `hermes proxy` is never registered; CLI is diagnostic-only; webhook is trigger-only.

## 4. Runs adapter

Implement:

- authenticated submit of the minimal WorkContract projection;
- correlation of contract_id/run_id without trusting Hermes as idempotency owner;
- SSE consumption into 16E envelopes with bounded payloads and redaction;
- status poll reconciliation after disconnect;
- stop request without premature CANCELLED;
- approval request forwarding to 16D and resolution only from a valid Furina decision;
- explicit timeout/resource cleanup and cancellation-safe shutdown.

Hermes `completed` must emit `BACKEND_DONE_UNVERIFIED`. Final text and streamed text are evidence
or presentation material only, never direct dialogue.

## 5. Security and isolation

- Default endpoint is loopback; remote endpoints require explicit configuration and authenticated
  TLS policy outside this brief's defaults.
- API key comes from existing secret/config mechanisms, never committed or included in contract.
- Use a dedicated Hermes profile/workspace boundary; no Furina SOUL/persona/memory files exposed.
- Adapter cannot enable broader Hermes toolsets, jobs, webhook delivery, peer messaging, memory or
  plugins as a side effect.
- No auto/permanent approval; only scoped AuthorizationGrant may be transmitted.

## 6. Tests

Use deterministic fake HTTP/SSE servers for exhaustive behavior; one opt-in local live smoke may
run only if Hermes is configured and must not be required for ordinary CI.

At minimum lock:

1. capability missing/lying/malformed/auth failure fail closed;
2. active probe success and TTL expiry;
3. submit/run correlation;
4. SSE fragmentation, reconnect and status reconciliation;
5. approval pause/resolve/deny/timeout;
6. stop keeps CANCELLING until terminal event;
7. completed→BACKEND_DONE_UNVERIFIED;
8. text never reaches direct dialogue/C7/C3;
9. payload/secret redaction;
10. no CLI/proxy/webhook execution fallback;
11. cleanup on timeout/cancel;
12. Native backend regression unaffected.

Run 16C targeted tests, backend/event/permission regressions, cognition suite and full suite once.
No real destructive tool actions. Finish `READY_FOR_REVIEW`.

