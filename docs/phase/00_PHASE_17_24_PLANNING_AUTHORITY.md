# Phase 17–24 — Future Execution Planning Authority

> STATUS = FROZEN PLANNING BASELINE
> PRODUCT ROADMAP AUTHORITY = `docs/product/ROADMAP.md`
> EXECUTION ORDER = Phase 17 → 18 → 19 → 20 → 21 → 22 → 23 → 24

## 1. Purpose

This document makes the post-Phase-16 roadmap executable without pretending that future repository
state already exists. Each Phase directory contains an index, a master plan, Delta task briefs and
an integrated closeout template. These documents freeze product ownership, dependencies, forbidden
shortcuts and acceptance evidence.

They do **not** pre-authorize work before its predecessor gate. At launch time the coordinator must
insert the real accepted integration SHA and re-run repository recon. A task brief whose baseline,
public interfaces or prerequisite evidence no longer matches reality must stop for a documentation
correction; the implementation model may not silently reinterpret it.

## 2. Canonical delivery boundary

- Phase 23 owns Eyes and multimodal perception only.
- Phase 24 owns complete product integration, release and documented future outlook.
- The current Furina product is not formally released until Phase 24 closes.
- Multi-character implementation is not required for release. Phase 24 freezes interfaces and
  outlook only unless the user separately authorizes a future product expansion.

## 2.1 Canonical Phase entry points

- [Phase 17 — Character Agency & Work Willingness](Phase_17/_INDEX_README.md)
- [Phase 18 — Computer Control & Office Automation](Phase_18/_INDEX_README.md)
- [Phase 19 — Connected Services & Communications](Phase_19/_INDEX_README.md)
- [Phase 20 — Desktop Embodiment & Visible Action](Phase_20/_INDEX_README.md)
- [Phase 21 — Production Art & Animation Library](Phase_21/_INDEX_README.md)
- [Phase 22 — Voice Interaction](Phase_22/_INDEX_README.md)
- [Phase 23 — Eyes & Multimodal Perception](Phase_23/_INDEX_README.md)
- [Phase 24 — Integrated Product, Character Platform & Release](Phase_24/_INDEX_README.md)

## 3. Universal execution protocol

Every Delta follows:

```text
accepted predecessor integration SHA
→ read-only recon and dependency proof
→ task-specific branch
→ bounded implementation
→ targeted + related + cognition/frozen regressions
→ one full suite unless the brief requires more
→ commit and push
→ independent external review
→ reviewer patch loop if required
→ ff-only integration from the accepted SHA
```

No Builder may self-issue PASS. Builder output stops at `READY_FOR_REVIEW`. Only the external
Reviewer may accept a Delta or Phase. Unknown commits, merge commits on task branches, dirty-scope
overlap, skipped security tests or unverifiable live claims are blockers.

## 4. Frozen cross-Phase authorities

- C1 Persona truth remains authoritative for character identity.
- C2 Canon remains read-only and versioned.
- C3–C7 retain their Phase 15 owners and provenance rules.
- Phase 16 remains the only authority for WorkContract, technical routing, permission, approval,
  execution truth, independent verification, recovery and C7/C6 work-result projection.
- Phase 17 owns subjective willingness and character policy, never technical permission.
- Phase 18 owns computer/office control adapters.
- Phase 19 owns connected-service channels and contact/destination safety.
- Phase 20 owns presentation/body runtime.
- Phase 21 owns production asset packs and visual QC.
- Phase 22 owns audio capture/playback and voice turn-taking.
- Phase 23 owns visual observation and multimodal grounding.
- Phase 24 owns product-wide integration, distribution and release evidence.

No later Phase may create a second dialogue mouth, second task truth store, second permission
system, second runtime frame, second C7 writer or a parallel Persona/Memory/Relationship truth.

## 5. Shared safety rules

- All external side effects require Phase 16 authorization and cancellation.
- Observation is not completion evidence; successful work still requires independent verification.
- Secrets, credentials, contact identities, screenshots and recordings are bounded and redacted.
- Password, payment, private-window and sensitive-field surfaces fail closed.
- UI/audio/video work never blocks the owner thread or the presentation frame loop.
- LLM output cannot directly mutate durable truth or issue irreversible side effects.
- Tests must exercise production paths, failure paths, restart boundaries and exact ownership.
- Real product claims require controlled live UAT; mocks alone cannot close an adapter claim.

## 6. Task-brief validity fields

Before each Delta starts, its launcher records:

```ini
BASE_SHA=<accepted predecessor integration SHA>
BRANCH=<task-specific branch>
DEPENDENCY_SHAS=<accepted required Delta SHAs>
LOCAL_REMOTE_MATCH=true
WORKTREE_CLEAN=true
LIVE_ENVIRONMENT=<available|unavailable with blocker>
```

If these cannot be proven, stop before editing.

## 7. Closeout minimum

Every closeout records changed files, migrations, public API changes, frozen-contract equality,
targeted/related/full test results, real UAT evidence where required, warnings/skips, local/remote
SHA equality, remaining gaps and `READY_FOR_REVIEW`. Claims must distinguish Builder-reported,
automated, reviewer-reproduced and human-observed evidence.
