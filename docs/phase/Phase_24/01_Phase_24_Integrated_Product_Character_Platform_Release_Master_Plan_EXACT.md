# Phase 24 — Integrated Product, Character Platform & Release
# Master Plan — EXACT

## 0. Existing foundation

Phase 24 consumes only accepted outputs from Phase 13–23. It does not compensate for a missing
phase by weakening gates. Earlier architectural reservations for persona packs and multiple
characters become documented extension interfaces and future outlook, while Furina remains the
only required production character for this release.

## 1. Goal

Integrate, package, harden, document and formally release the complete Windows desktop Furina
product, with safe lifecycle management and a credible future character-platform boundary.

## 2. Invariants

- Phase 24 is the sole formal product-completion and release authority.
- Release truth requires accepted evidence from every required prior phase; no inherited claim is
  converted into PASS without verification.
- One cognition owner, work-state owner, action owner, verifier, runtime-frame contract, animation
  owner and speaking owner remain in force across the integrated product.
- Install, update, rollback, export and uninstall are recoverable, least-privilege and data-safe.
- Telemetry is minimal, documented, consent-aware and free of secrets, raw audio and raw captures.
- Release artifacts are reproducible, signed/checksummed where supported and linked to source SHA.
- Persona-pack and multi-character interfaces are future reservations, not a claim that a second
  production character ships in this phase.
- The project is not declared formally released until 24F external sign-off.

## 3. Delta order

```text
24A Integrated Product Gate
→ 24B Windows Distribution, Installer, Update & Rollback
→ 24C Permissions, Data Lifecycle, Settings & Uninstall
→ 24D Performance, Reliability, Telemetry & Release Channels
→ 24E Character Interface & Future Platform Reservation
→ 24F Release Candidate, Integrated Life Manual & Sign-off
```

The final release gate includes named human UAT, reproducible artifacts, known-gap disclosure and
an explicit release decision. Future outlook is documented separately from shipped capability.
