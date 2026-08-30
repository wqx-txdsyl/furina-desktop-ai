# Phase 24 — Delta Task Briefs — EXACT

## 24A — Integrated Product Gate

Integrate the accepted Phase 13–23 stack and audit all ownership boundaries, event flows, settings,
permissions, migrations and failure states. Run realistic end-to-end daily-life/work/voice/vision
journeys, long-running soak, restart/recovery and hostile-state tests. No release packaging begins
with an unresolved blocker or substituted phase acceptance.

## 24B — Windows Distribution, Installer, Update & Rollback

Produce reproducible Windows release artifacts tied to source SHA, dependency lock and asset pack.
Implement least-privilege install, integrity/signature checks where supported, atomic update,
rollback and damaged-update recovery. Test clean machines, supported upgrades, offline failure and
untrusted package rejection.

## 24C — Permissions, Data Lifecycle, Settings & Uninstall

Create a single understandable settings and permission surface for accounts, automation, microphone,
capture, telemetry and retention. Prove backup/export, restore, deletion, factory reset and complete
uninstall behavior without deleting unrelated user data. Document where every durable datum lives.

## 24D — Performance, Reliability, Telemetry & Release Channels

Freeze supported hardware/OS baselines and budgets for startup, idle/active CPU, memory, disk,
network and latency. Add consent-aware operational telemetry with strict redaction and local
diagnostics. Define stable/pre-release channels, incident response, rollback criteria and support
boundaries; complete extended soak and recovery exercises.

## 24E — Character Interface & Future Platform Reservation

Extract and document stable persona/voice/art/capability extension contracts without moving current
owners or breaking Furina. Validate the reservation with schemas or non-shipping fixtures only.
Describe isolation, identity, permission and migration requirements for future characters. Do not
claim or require a second production character in this release.

## 24F — Release Candidate, Integrated Life Manual & Sign-off

Build the exact release candidate; publish installation, permissions, daily use, safety, privacy,
recovery, update, uninstall and known-limit documentation. Run three full suites, installer/update/
rollback matrices, named human UAT and external release review. Record an explicit GO/NO-GO. Only a
GO with matching local/remote/source/artifact identities permits the formal release declaration.
