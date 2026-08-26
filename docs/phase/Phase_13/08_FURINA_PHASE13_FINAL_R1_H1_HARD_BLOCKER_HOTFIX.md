# Furina Desktop AI — Phase 13 FINAL-R1-H1 Reviewer Hard-Blocker Hotfix

**Review baseline:** `880805f300acb37102b7b0545e95f8581407c2f2`

This is **NOT Phase 13 R2**, not a new backend phase, and not an optimization pass.

It is a one-time hotfix for reviewer-reproduced hard blockers that remain inside the already-defined FINAL-R1 contract.

After this hotfix, STOP.  
Reviewer will check **only the invariants in this file**.

If they pass:

```text
PHASE 13 TECHNICAL = PASS
NEXT = Manual Experience Acceptance
```

No ordinary H2/R2/R3 is allowed.

---

# 0. Current reviewer verdict

```text
Agent local regression report = 581 green
GitHub CI evidence            = none
FINAL-R1 reviewer verdict     = PARTIAL
Manual                        = BLOCKED
Phase 14                      = BLOCKED
```

Important: many R1 fixes are real and are frozen below.  
Do not reinterpret this hotfix as permission to redesign them.

---

# 1. Freeze confirmed R1 fixes

Do NOT reopen or retune:

- Relationship canonical units / C-R2
- forced variety OFF
- anti-collapse OFF in production
- human-scale Needs constants
- Agent planner mappings
- Agent task-local context
- Agent global `res.ok AND res.verified` hard gate
- strengthened Agent target-step test using real `tmp_path`
- Agent explicit lifecycle status
- Harness Agent status reading `AgentRuntime.status`
- Harness Life `last_outcome`
- Outcome deep copy concept
- progress-aware interrupted rewards concept
- Activity lifecycle start moved from decision submission to Director execution
- `_on_brain()` no longer overwrites authoritative emotion
- `EmotionEngine.apply_event()` apply+derive concept
- duplicate EmotionEngine class removal
- unmapped pointer emotion guard
- WorldPerception single-update-per-medium architecture
- Memory core store/retrieve/restart
- Spatial technical implementation
- assets / renderer / animation
- Persona design

No parameter tuning for prettier demos.

---

# 2. H1-P0 — Windows idle truth is still false on API failure

## 2.1 `None` is converted back to fake `0.0`

Current production code correctly makes:

```python
_get_idle_seconds() -> Optional[float]
```

but `_active_window_windows()` still constructs:

```python
idle=_get_idle_seconds() or 0.0
```

Therefore:

```text
GetLastInputInfo/API failure
-> None
-> `or 0.0`
-> WindowInfo.idle = 0.0
-> WindowAwareness.idle_available = True
-> runtime believes "user just interacted"
```

This directly violates FINAL-R1 §1.1.

### Required fix

Preserve `None` all the way:

```python
idle=_get_idle_seconds()
```

No `or 0`, no sentinel that looks like a real active-user measurement.

`WindowAwareness` must distinguish:

```text
idle_available = False
last_idle = previous valid sample / None
```

Scheduler may retain previous valid value for continuity, but diagnostics must expose that the current OS idle sample is unavailable.

---

## 2.2 `LASTINPUTINFO.dwTime` is 32-bit; raw subtraction from GetTickCount64 is unsafe

Windows `LASTINPUTINFO.dwTime` is a `DWORD` tick count. It has 32-bit wrap semantics.

Current code effectively does:

```python
now64 = GetTickCount64()
last32 = lii.dwTime
idle = now64 - last32
```

After sufficiently long uptime, the upper bits of `now64` make this a huge false idle.

### Required fix

Use a wrap-aware compatible calculation.

Allowed approaches:

### A. 32-bit compatible source

```text
GetLastInputInfo.dwTime (DWORD)
GetTickCount()          (DWORD)
elapsed = (now32 - last32) & 0xFFFFFFFF
```

### B. Keep GetTickCount64 but compare the low DWORD modulo 2^32

```python
now32 = now64 & 0xFFFFFFFF
elapsed_ms = (now32 - last32) & 0xFFFFFFFF
```

Do not naïvely subtract 32-bit last tick from 64-bit uptime.

### Required deterministic tests

```text
test_active_window_preserves_idle_none
test_idle_failure_poll_keeps_idle_unavailable
test_idle_failure_does_not_become_zero
test_idle_wrap_32bit_correct
test_idle_long_uptime_does_not_become_huge
```

A wrap test must cross `0xFFFFFFFF -> 0`.

The old test that merely makes `WindowAwareness.poll()` fail due to an incomplete fake Win32 object is insufficient. Mock the complete `_active_window_windows` path or mock `_get_idle_seconds()` returning None and assert the resulting `WindowInfo.idle is None`.

---

# 3. H1-P0 — World semantic events must be consumed as event instances, not recent-history strings

FINAL-R1 fixed duplicate WorldPerception.update. Keep that.

But Scheduler now checks:

```python
if "WORK_STARTED" in world.state.recent_world_events:
    if now - last_consumed > 20:
        apply EVENT_WORK_START
```

`recent_world_events` is historical storage, not "events emitted by this update".

If an old `WORK_STARTED` remains in the recent list:

```text
t=0: event consumed
t=21s: same old string still in list
-> consumed again
```

That violates exactly-once semantics.

### Required fix

Expose/consume **fresh events emitted by the current `WorldPerception.update()`**.

Examples:

```text
WorldPerception.last_events
update(...) -> WorldUpdateResult(events=[...])
event instance IDs / monotonic sequence numbers
```

Do not infer newness from membership in historical `recent_world_events`.

### Required tests

Use a controllable clock.

```text
test_work_started_event_consumed_once_after_60s_without_new_event
test_work_ended_event_consumed_once_after_60s_without_new_event
test_second_real_work_transition_emits_second_event
test_recent_world_history_cannot_retrigger_emotion
```

Proof:

```text
browse -> stable coding -> WORK_STARTED count = 1
advance 120s while remaining coding -> count = 1
coding -> stable browse -> WORK_ENDED count = 1
browse -> stable coding again -> WORK_STARTED count = 2
```

---

# 4. H1-P0 — Owner-thread contract still has direct worker mutation / owner-thread LLM

## 4.1 Agent success Memory write remains on Agent worker

Current `_agent_worker()` still calls:

```python
self.memory.observe(...)
```

after successful tool execution.

### Required fix

Return the immutable Agent result to owner and perform Memory integration through RuntimeDispatcher.

### Test

```text
test_agent_success_memory_observe_runs_on_owner_thread
```

Capture the actual thread ID.

---

## 4.2 Autonomous Life Dialogue still calls LLM on runtime owner

`Scheduler._apply_life_decision()` runs from owner tick and currently calls:

```python
self.dialogue_brain.say(...)
```

directly for autonomous/speakable Life decisions.

### Required fix

```text
owner: freeze Dialogue snapshot
worker: DialogueBrain.say(snapshot)
owner: apply speech/result
```

Do not change Life cadence.

### Tests

```text
test_autonomous_dialogue_llm_not_called_on_owner_thread
test_slow_autonomous_dialogue_does_not_block_runtime_owner
test_autonomous_dialogue_result_applies_on_owner_thread
```

---

# 5. H1-P0 — Dialogue FIFO has a real lock inversion

Current order:

```text
seq = _next_seq()
acquire _say_lock
_push_ordered(seq slots)
```

If turn #2 acquires `_say_lock` before turn #1:

```text
turn2 holds _say_lock
turn2 waits for turn1 slots
turn1 cannot acquire _say_lock
=> deadlock
```

Current test named `test_second_input_cannot_overtake_first_before_lock_acquisition` bypasses `say()` and calls `_push_ordered()` directly, so it does not test this production race.

### Required fix

Use a true turn FIFO gate **before** generation.

Allowed:
- dedicated serial Dialogue executor
- ticket/Condition gate before generation lock
- one consumer queue

No later turn may hold the generation lock while waiting for an earlier turn.

### Required deterministic tests

Force:

```text
turn1 seq=1, paused before generation
turn2 seq=2, attempts to proceed first
release turn1
```

Assert both threads terminate with bounded timeout and:

```text
LLM call order = turn1, turn2
history = user1, furina1, user2, furina2
```

Tests:

```text
test_turn2_forced_before_turn1_lock_does_not_deadlock
test_dialogue_llm_call_order_matches_ingress_order
test_dialogue_failure_advances_fifo
test_dialogue_silence_advances_fifo
```

---

# 6. H1-P0 — Direct history still permits orphan user turns

Current direct path commits the user history slot before model success/validation.

If model generation/validation/gating returns `None`, the history can contain:

```text
User: ...
```

with no Furina reply.

### Required fix

Atomically commit a valid direct pair only after a displayable response exists.

A failed/silent turn may be recorded in diagnostics, but not as an orphan direct-dialogue pair.

### Tests

```text
test_model_failure_creates_no_orphan_direct_user_turn
test_double_validation_failure_creates_no_orphan_direct_user_turn
test_output_gate_suppression_creates_no_orphan_direct_user_turn
test_valid_direct_turn_commits_exact_pair
test_history_always_even_user_furina_pairs
```

Mixed run:

```text
valid -> invalid -> valid -> silent -> valid
```

must preserve coherent direct history.

---

# 7. H1-P0 — Social Ignore window starts on decision submission, not visible bid

Current `_apply_life_decision()` calls `begin_social_bid()` for social activities before Director execution.

So a blocked `talk` can create:

```text
unseen social attempt
-> 60s timeout
-> false USER_IGNORE
```

### Required fix

Start a response window only when an eligible social bid is actually executed and observable.

- blocked mind decision -> no bid
- invalid/suppressed speech -> no bid
- absent user -> no bid
- Agent/system/ambient speech -> no bid

If body-only gestures count as bids, define exactly which **executed** actions count.

### Tests

```text
test_blocked_social_decision_creates_no_pending_bid
test_unexecuted_talk_cannot_emit_ignore
test_invalid_social_speech_creates_no_pending_bid
test_visible_social_bid_starts_one_window
test_user_response_cancels_visible_bid
```

---

# 8. H1-P0 — Activity lifecycle is not wired to actual preemption

Activity instances now start at Director execution. Good.

But production does not finalize a RUNNING mind instance when Agent/user control actually takes over.

Tests currently manually inject:

```python
instance["pending_finish"] = "aborted"
```

Production does not.

### Required fix

At actual Director replacement/preemption:

```text
finalize running mind instance immediately
elapsed stops at takeover
progress computed then
status = INTERRUPTED/ABORTED
partial outcome exactly once
```

A later Life decision must never count Agent/user time as mind activity time.

Use a real Director/App/Scheduler callback such as `on_before_replace(old,new)` or equivalent.

Also ensure FAILED/ABORTED can never receive reward indistinguishable from COMPLETED.

### Tests must use production path

```text
test_agent_takeover_finalizes_running_mind_immediately
test_user_takeover_finalizes_running_mind_immediately
test_preempted_mind_elapsed_stops_at_takeover
test_preempted_mind_cannot_later_become_completed
test_preemption_outcome_applied_exactly_once
test_failed_or_aborted_never_receives_completed_scale
```

---

# 9. H1-P0 — Real interaction ordering still allows stale Relationship in Dialogue

Current `InteractionEngine._apply()` does:

```text
bus.emit(INTERACTION_INPUT)
then on_meaningful_interaction(ev)
```

Scheduler can launch Dialogue from the bus callback before `on_meaningful_interaction()` applies Relationship changes.

### Required fix

For a finalized semantic interaction:

```text
semantic classification
-> owner Emotion
-> owner Relationship
-> owner Needs/Life immediate effect
-> owner Memory event if applicable
-> freeze DialogueContextSnapshot
-> worker Dialogue
-> owner speech apply
```

Do not create a second Interaction system.

### Required integration tests

Use actual `InteractionEngine.emit_event()`.

```text
test_real_petting_dialogue_sees_post_relationship
test_real_poke_dialogue_sees_post_relationship
test_real_drag_dialogue_sees_post_relationship
test_real_interaction_snapshot_frozen_before_worker
```

---

# 10. H1-P0 — Dialogue context must be frozen on owner before any worker

Current `_brain_worker()` later reads live mutable runtime state from worker:
relationship, emotion, activity, idle/world, Memory context.

That does not satisfy:

```text
owner effects -> authoritative state -> frozen snapshot -> worker LLM
```

### Required fix

Introduce one small immutable/copied owner-side snapshot, e.g.:

```text
DialogueContextSnapshot
```

Use it for:
- direct user dialogue
- Feed reaction
- interaction reaction
- Agent report/failure
- autonomous Life speech

Snapshot contains only required copied facts; no references to mutable runtime objects.

### Tests

Mutate live runtime after snapshot creation but before worker proceeds.

```text
test_direct_dialogue_uses_owner_frozen_snapshot
test_feed_dialogue_uses_owner_frozen_snapshot
test_interaction_dialogue_uses_owner_frozen_snapshot
test_agent_dialogue_uses_owner_frozen_snapshot
test_autonomous_dialogue_uses_owner_frozen_snapshot
```

---

# 11. H1-P0 — Feed starts Dialogue before all domain effects finish

Current `_feed()` starts `_feed_dialogue` before:

```text
memory.observe
life.activity = eat
life.macro = living
life interrupt
```

### Required fix

Owner sequence:

```text
food effect
emotion apply+derive
memory
life/activity/intent
interrupt
cancel pending social bid
freeze snapshot
then start Dialogue worker
```

### Tests

Use barrier fake DialogueBrain:

```text
test_feed_all_domain_effects_precede_dialogue_worker
test_feed_worker_receives_post_feed_activity
test_feed_worker_does_not_read_live_mutable_state
```

---

# 12. H1-P1 — Runtime owner must be explicitly bound by startup

`RuntimeDispatcher.require_owner()` currently binds whoever calls first if owner is unset.

### Required fix

Bind runtime owner explicitly during startup on the Qt/runtime thread, before workers can request guarded mutations.

`submit()` must never establish owner identity.

### Tests

```text
test_runtime_owner_bound_to_start_thread
test_worker_cannot_become_owner_before_first_drain
```

---

# 13. Evidence requirements

Create:

```text
docs/FURINA_PHASE13_FINAL_R1_H1_HOTFIX_REPORT.md
```

Do not lead with test count.

For every H1 blocker show:

```text
BEFORE reproduction
root cause
production fix
AFTER deterministic proof
```

Use:
- Events/Barriers for races
- fake/controlled clocks
- thread IDs
- actual Scheduler/Director/InteractionEngine paths
- call counters
- bounded `join(timeout=...)`

A test is not sufficient evidence if it:
- only searches source
- bypasses the production path responsible for the bug
- manually injects the state production should create
- passes through early failure
- relies on likely thread scheduling
- uses tight loops to "test" 20s/60s boundaries

---

# 14. Forbidden

Do NOT:
- begin Phase 14
- touch assets/animation/renderer
- tune Needs/Personality/Relationship
- re-enable anti-collapse
- add rotation/diversity forcing
- redesign Persona
- add line banks
- add LLM/DB
- redesign Spatial
- expand Agent tools
- refactor unrelated modules

---

# 15. STOP gate

After fixing only H1:

```text
run full regression
push coherent hotfix
send SHA + report + exact regression result
STOP
```

Allowed Agent verdict:

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

Reviewer checks only H1.

If H1 passes:

```text
PHASE 13 TECHNICAL = PASS
```

Then immediately:

```text
Manual Experience Acceptance
```

Only after Manual:

```text
FUNCTIONAL DIGITAL LIFE = PASS
Phase 14 — Frontend Rendering / Asset Integration
```
