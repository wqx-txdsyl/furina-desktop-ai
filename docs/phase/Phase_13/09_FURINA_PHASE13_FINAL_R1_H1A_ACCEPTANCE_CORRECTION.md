# Furina Desktop AI — Phase 13 FINAL-R1-H1-A Acceptance Correction

**Review baseline:** `6db20043f9621e28d5978d04d8d234e4b6f7ba3e`

This is **not H2 / R2 / a new phase**.

The reviewer accepts the majority of H1. This file contains only the final acceptance corrections for six H1-contract gaps found in production wiring/tests.

After these exact corrections: **STOP**.

If reviewer confirms them:

```text
PHASE 13 TECHNICAL = PASS
BACKEND FUNCTIONAL CONTRACT = FROZEN
NEXT = Manual Experience Acceptance
```

No ordinary backend optimization cycle is allowed after this.

---

# 0. Freeze everything else

Do not modify:

- Windows idle modular arithmetic itself
- WorldPerception `last_events` fresh-event design
- Relationship canonical units
- Needs constants
- Emotion model/decay/weights
- Life diversity/anti-collapse settings
- Dialogue Persona/prompt/examples
- Dialogue FIFO gate design except tests needed below
- direct-history atomic-pair design
- DialogueContextSnapshot architecture
- Agent verified hard gate
- Agent planner/tools
- Memory architecture
- Spatial
- renderer/assets/animation
- Phase 14 work

---

# 1. P0 — Interaction Emotion is applied twice in the real Furina wiring

## Reproduction

`Furina.__init__` still registers:

```python
self.bus.on(EventType.INTERACTION_INPUT, self._on_interaction_emotion)
```

H1 additionally wires:

```python
self.interaction.on_emotion_semantic = self._on_interaction_emotion
```

`InteractionEngine._apply()` now performs:

```text
on_emotion_semantic(ev)
-> on_meaningful_interaction(ev)
-> bus.emit(INTERACTION_INPUT)
```

Therefore the production path is:

```text
pet/poke/drag/click
-> _on_interaction_emotion()        # semantic hook: first apply
-> bus.emit(INTERACTION_INPUT)
   -> Furina bus subscriber
      -> _on_interaction_emotion()  # second apply
```

H1 tests missed this because `_interaction_app()` attached the semantic hook but did **not** register the same bus subscriber that real `Furina.__init__` registers.

## Required fix

One finalized semantic interaction must have exactly one Emotion owner path.

Preferred:

```text
InteractionEngine finalized semantic event
-> on_emotion_semantic exactly once
-> relationship/memory
-> broadcast for downstream consumers
```

Remove/disable the duplicate App bus Emotion subscriber for the finalized production path.

Do not compensate by halving Emotion deltas.

## Required integration test

Use wiring equivalent to production, not a reduced stub that omits one subscriber.

```text
test_real_furina_petting_emotion_applied_once
test_real_furina_poke_emotion_applied_once
test_real_furina_drag_emotion_applied_once
test_real_furina_click_emotion_applied_once
```

Assert exact `_recent[event] == 1` after one `InteractionEngine.emit_event(...)`.

---

# 2. P0 — Interaction freezes Dialogue before all immediate Life/Needs effects

Current Scheduler `_on_interaction()` starts `_speak_via_dialogue(...)` near the top of each semantic branch.

Only afterwards it performs:

```text
social_need -= 5
adapt_tolerance(...)
sync relationship
consolidate episode
_interrupt_life(...)
sleeping -> ENGAGED
```

H1 required:

```text
semantic event
-> Emotion
-> Relationship
-> Needs/Life immediate effect
-> Memory
-> authoritative state
-> freeze Dialogue snapshot
-> worker
```

The pre-broadcast Emotion/Relationship change fixed only part of this ordering.

## Required fix

For finalized click/petting/poke/drag, finish all synchronous owner-domain effects first.

Only then freeze the DialogueContextSnapshot and launch the Dialogue worker.

Do not create a second interaction system.

## Required deterministic test

Use `InteractionEngine.emit_event()` + a barrier/capturing DialogueBrain.

At the instant Dialogue worker begins, prove:

```text
Emotion already updated exactly once
Relationship already updated exactly once where applicable
social_need already changed
Life interrupt already registered
sleep wake/engaged transition already applied when applicable
snapshot is already frozen
```

Tests:

```text
test_real_interaction_all_domain_effects_precede_dialogue
test_real_petting_snapshot_is_post_event
test_real_poke_snapshot_is_post_event
test_real_drag_snapshot_is_post_event
```

The current tests that only assert Emotion/Relationship after `emit_event()` are insufficient evidence for this ordering.

---

# 3. P0 — Real user interaction still does not finalize a running mind Activity

H1 correctly wires Agent preemption:

```text
Director.on_before_replace
-> on_mind_preempted
```

But real semantic user interaction currently bypasses Director.

`INTERACTION_INPUT` is handled directly by Scheduler; no `source="interaction"` ActionRequest replaces the current mind request.

Therefore:

```text
mind/read RUNNING
-> user pets/pokes/drags/clicks
-> character reacts
-> ActivityInstance can remain RUNNING
-> elapsed continues until a later Life decision
```

This violates H1's explicit requirement to handle meaningful user takeover even if it bypasses Director.

## Required fix

At a finalized meaningful user interaction, if a mind ActivityInstance is RUNNING:

```text
finalize it immediately
elapsed stops now
partial outcome exactly once
finish_reason = preempted_by_user
Director mind ownership is released appropriately
```

Either:
- route the real user interaction through Director with `source="interaction"`, or
- explicitly call the same lifecycle-finalization boundary from the semantic interaction handler and release current mind ownership.

Do not merely set `_life_interrupt_pending`.

## Required production-path tests

No manual `pending_finish` injection.

```text
test_user_petting_takeover_finalizes_running_mind_immediately
test_user_poke_takeover_finalizes_running_mind_immediately
test_user_drag_takeover_finalizes_running_mind_immediately
test_user_takeover_elapsed_stops_at_interaction
test_user_takeover_outcome_applied_once
test_user_takeover_cannot_later_become_completed
```

---

# 4. P0 — Activity lifecycle status and non-completion reward violate the frozen contract

## 4.1 Status currently becomes `PREEMPTED_BY_AGENT`

H1 report claims canonical lifecycle status is:

```text
RUNNING
COMPLETED
INTERRUPTED
ABORTED
FAILED
```

but `on_mind_preempted()` currently does:

```python
inst["status"] = reason.upper()
```

so Agent takeover produces:

```text
status = PREEMPTED_BY_AGENT
```

That mixes **state** with **finish reason**.

## Required fix

Keep canonical state and reason separate:

```text
status = INTERRUPTED   # or ABORTED when semantically appropriate
finish_reason = preempted_by_agent / preempted_by_user / ...
```

Tests and diagnostics must consume the canonical status.

---

## 4.2 `success=False, progress=1.0` still receives completion-scale reward

Current formula remains:

```python
scale = 1.0 if success else (0.3 + 0.7 * progress)
```

So:

```text
success=False
progress=1.0
=> scale=1.0
```

A failed/aborted/interrupted activity can therefore receive reward identical to COMPLETED.

H1 explicitly forbids this.

## Required fix

Preserve:

```text
10% interrupted < 70% interrupted < 100%-progress non-completed < COMPLETED
```

Non-completion scale must be **strictly below completion scale for every progress in [0,1]**.

This is a semantic completion distinction, not behavior-distribution tuning.

## Required tests

```text
test_preemption_status_is_canonical_interrupted
test_preemption_finish_reason_preserves_agent_or_user_source
test_noncompleted_progress_1_still_less_than_completed
test_interrupted_reward_monotonic_but_never_full
```

Do not only test progress=0.3.

---

# 5. P1 — Harness startup does not explicitly bind Runtime owner

Formal `launch()` now does:

```python
sched.dispatcher.bind_owner()
```

but `launch_harness()` does not.

`Scheduler.start()` itself also does not bind.

Because `RuntimeDispatcher.require_owner()` now refuses to self-bind, Harness relies on the first timer-driven `sched.step()/drain()` to become owner.

That violates H1 §12:

```text
owner is explicitly bound during runtime startup,
before worker/user guarded mutations can occur.
```

## Required fix

Prefer the single lifecycle boundary:

```python
Scheduler.start(...)
    -> dispatcher.bind_owner()
```

or an equivalent shared startup function used by both production GUI and Harness.

Then remove redundant special-case binding if appropriate.

`drain()` should not be the intended mechanism that establishes production ownership.

## Required tests

Test actual startup semantics, not `RuntimeDispatcher` in isolation:

```text
test_scheduler_start_binds_owner_to_calling_thread
test_launch_harness_has_owner_before_first_timer_tick
test_guarded_harness_action_valid_before_first_step
test_worker_cannot_become_owner
```

---

# 6. P1 — Manual diagnostics still hide current idle-sample availability

H1 §2.1 required the runtime to distinguish:

```text
last known idle value
vs
current Windows idle sample unavailable
```

`WindowAwareness.idle_available` now exists, but Harness `_diagnostics()` currently only exposes:

```text
idle_seconds
```

A retained old value can therefore look like a current valid OS measurement during Manual.

## Required fix

Expose at minimum:

```text
idle_seconds
idle_available
```

Optionally:

```text
idle_last_valid_seconds
```

Do not replace retained idle with zero.

## Test

```text
test_harness_diagnostics_exposes_idle_availability
```

Sequence:

```text
valid sample 42s
-> API becomes unavailable
-> state may retain 42s
-> diagnostics:
   idle_seconds = 42
   idle_available = False
```

---

# 7. Strengthen the false-green tests

The following current tests do not fully exercise the production claim in their name:

### Interaction
Current `_interaction_app()` omits the real App bus Emotion subscriber, so it cannot detect double Emotion application.

### `test_real_interaction_snapshot_frozen_before_worker`
It does not instantiate/capture a Dialogue worker or snapshot; it only checks state after `emit_event`.

Replace/strengthen with actual callback/barrier capture.

### User takeover
H1 required a user-takeover lifecycle test; current hotfix only proves Agent takeover.

### Lifecycle reward
Current test proves non-completed at progress=0.3 is less than completed; it does not test the critical `progress=1.0` boundary.

### Owner startup
Current tests exercise `RuntimeDispatcher` directly; they do not prove the Harness startup path binds before first interaction.

These test changes are mandatory evidence, not optional coverage polish.

---

# 8. Accepted H1 items — do not reopen

Reviewer accepts and freezes:

```text
Windows idle None preservation concept          PASS
Windows 32-bit wrap arithmetic                  PASS
World last_events fresh-event consumption       PASS
Agent success Memory returned to owner          PASS
Autonomous Life Dialogue moved off owner        PASS
Dialogue FIFO gate architecture                 PASS
Direct history atomic pair architecture         PASS
Social bid moved off decision-submission        PASS
Agent verified hard gate                        PASS
DialogueContextSnapshot architecture            PASS
Feed effects-before-worker ordering              PASS
Agent takeover immediate-finalize concept        PASS
```

Only §§1–7 above may be changed.

---

# 9. Report

Update/create:

```text
docs/FURINA_PHASE13_FINAL_R1_H1A_ACCEPTANCE_REPORT.md
```

Order:

1. six reviewer reproductions
2. exact root causes
3. production corrections
4. strengthened production-path tests
5. deterministic AFTER evidence
6. full regression
7. STOP

Do not lead with test count.

---

# 10. Forbidden

Do NOT:

- start Phase 14
- touch assets/renderer/animation/spatial
- retune Needs/Emotion/Relationship/Personality
- alter Persona prompts/examples
- add catchphrases
- change LLM/model/DB
- refactor unrelated backend
- add another diversity mechanism
- reopen already accepted H1 areas

---

# 11. STOP / release gate

After implementation:

```text
PUSH
send SHA
send exact regression result
send H1-A report
STOP
```

Allowed Agent verdict:

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

Reviewer checks only this H1-A file.

If all six gaps pass:

```text
PHASE 13 TECHNICAL = PASS
BACKEND FUNCTIONAL CONTRACT = FROZEN
```

Then immediately proceed to:

```text
Manual Experience Acceptance
```

No H2/R2/R3 for ordinary optimization.
