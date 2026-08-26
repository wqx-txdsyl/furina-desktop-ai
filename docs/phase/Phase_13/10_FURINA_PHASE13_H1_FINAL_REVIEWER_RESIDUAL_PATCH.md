# Furina Desktop AI — Phase 13 H1 FINAL Reviewer Residual Patch

**Review baseline:** `6db20043f9621e28d5978d04d8d234e4b6f7ba3e`

## Reviewer verdict

```text
Agent local regression report = 622 green
GitHub CI evidence            = none
H1 reviewer verdict           = NOT ACCEPTED
Technical                     = PARTIAL
Manual                        = BLOCKED
Persona                       = NOT REVIEWED
Phase 14                      = BLOCKED
```

This is **not H2, not R2, not a new backend phase, and not an optimization pass**.

The H1 implementation is largely correct. The only allowed work is to close the **7 reviewer-verified residuals below**. Everything else is frozen.

After these 7 items are fixed, STOP and return for review.

If these 7 contracts pass:

```text
PHASE 13 TECHNICAL = PASS
BACKEND FUNCTIONAL CONTRACT = FROZEN
NEXT = Manual Experience Acceptance
```

No ordinary follow-up backend closeout is allowed.

---

# 0. Freeze all H1 work that passed

Do **not** reopen, redesign, or retune:

- Windows process classification
- Kernel32 / User32 API split
- 32-bit idle wrap arithmetic itself
- World single `WorldPerception.update()` per medium sample
- World `last_events` fresh-event architecture
- Emotion baseline-relative derivation
- Emotion `apply_event()` concept
- Relationship canonical scale
- Needs human-time scale
- anti-collapse OFF / forced diversity OFF
- Agent `ok AND verified` global hard gate
- Agent tool mappings / task-local context
- Agent status truth
- Feed domain-before-worker ordering
- `DialogueContextSnapshot` concept
- direct-history atomic pair concept
- FIFO gate-before-generation-lock concept
- Agent-memory owner dispatch
- autonomous LLM moved off owner thread
- Activity instance starts on actual Director execution
- progress-aware outcomes
- Spatial implementation
- Memory core store/retrieve/restart
- Harness truth badge work already completed
- Persona / assets / renderer / animation

No parameter tuning. No new LLM. No new DB. No new Persona line bank.

---

# 1. P0 — Production Interaction applies Emotion twice

## Verified production wiring

`Furina.__init__` still registers:

```python
self.bus.on(EventType.INTERACTION_INPUT, self._on_interaction_emotion)
```

H1 also added:

```python
self.interaction.on_emotion_semantic = self._on_interaction_emotion
```

and `InteractionEngine._apply()` now does:

```text
on_emotion_semantic(ev)
-> on_meaningful_interaction(ev)
-> bus.emit(INTERACTION_INPUT)
```

Therefore one real:

```text
petting / poke / drag / click
```

runs the same `_on_interaction_emotion()` once through the semantic hook and again through the EventBus subscriber.

The current H1 test is false-green because its `_interaction_app()` only wires:

```python
ie.on_emotion_semantic = app._on_interaction_emotion
```

and does **not** reproduce the real `Furina.__init__` EventBus subscription.

## Required fix

There must be exactly **one** production owner for semantic Interaction → Emotion.

Preferred:

```text
InteractionEngine semantic hook
    owns pre-broadcast Emotion application
```

and remove the duplicate App `INTERACTION_INPUT -> _on_interaction_emotion` subscription.

If some legacy/external path still needs EventBus mapping, it must have an explicit already-applied semantic marker and prove no duplicate application.

Do not solve this with idempotency based on timing.

## Required tests

Use actual production-equivalent wiring, including the real EventBus subscriptions that remain after the fix.

```text
test_production_petting_emotion_applies_exactly_once
test_production_poke_emotion_applies_exactly_once
test_production_drag_emotion_applies_exactly_once
test_production_click_emotion_applies_exactly_once
test_interaction_recent_counter_increments_once_per_semantic_event
```

Assert dimension delta and `_recent[event]` both occur exactly once.

---

# 2. P0 — Direct Dialogue FIFO sequence is still assigned in worker scheduling order, not user input order

H1 added a correct FIFO gate **inside `DialogueBrain.say()`**, but production input order is still not captured at ingress.

Current production:

```text
owner submit_user_message("user1")
-> start worker1

owner submit_user_message("user2")
-> start worker2

worker enters DialogueBrain.say()
-> _next_seq()
```

So if worker2 is scheduled before worker1:

```text
worker2 gets seq=1
worker1 gets seq=2
```

The FIFO then faithfully preserves the **wrong order**.

`DialogueContextSnapshot` already has a `seq` field, but production does not assign/use it for `DialogueBrain.say()`.

The current H1 test:

```python
t1.start()
t2.start()
```

does not force worker2 to enter `say()` first, so it is scheduling-probability evidence, not an ingress-order proof.

## Required fix

Assign direct-user turn sequence on the **owner thread at `submit_user_message()` ingress**, before starting any worker.

Allowed designs:

### Option A — reserve sequence explicitly

```text
submit_user_message:
  ingress_seq = dialogue_brain.reserve_turn()
  freeze snapshot(seq=ingress_seq)
  start worker(snapshot)

worker:
  dialogue_brain.say(..., ingress_seq=snapshot.seq)
```

### Option B — App-owned FIFO work queue

Owner enqueues direct DialogueTurn objects in user-input order and one worker consumer processes them.

The ordering identity must originate from the user ingress, not from worker execution timing.

Do not rely on thread start order.

## Required deterministic test

Force this exact schedule:

```text
owner submits user1 first
owner submits user2 second

worker1 is blocked before DialogueBrain.say
worker2 reaches DialogueBrain.say first
```

Then release worker1.

Required result:

```text
LLM call order:
user1
user2

history:
user1
furina1
user2
furina2
```

Both threads/tasks must terminate within bounded timeout.

Tests:

```text
test_production_user_ingress_seq_assigned_on_owner
test_worker2_entering_say_first_cannot_overtake_user1
test_snapshot_seq_is_consumed_by_dialogue_fifo
test_direct_history_order_matches_submit_user_message_order
```

Keep the current gate-before-lock implementation; fix the ingress identity.

---

# 3. P0 — Life autonomous speech still starts on decision submission, before Director execution

H1 correctly moved Life Dialogue LLM off the owner thread, but the worker is still created inside:

```text
Scheduler._apply_life_decision()
```

immediately after the `ActionRequest` is submitted.

So this is still possible:

```text
Agent currently owns Director
LifeBrain decides: talk/read/comment
mind ActionRequest is queued / blocked
BUT autonomous Dialogue worker starts anyway
speech becomes visible
social bid may open
```

This violates the already-established truth:

```text
decision submitted != activity started
```

and can bypass Director priority.

It also makes the current social-bid test false-green: its blocked-social Scheduler has `dialogue_brain=None`, so no actual successful speech worker can expose the bug.

## Required fix

Life-decision speech must become eligible only after the corresponding mind action is actually accepted/executed by Director.

Recommended:

```text
LifeDecision
-> ActionRequest(payload includes speech metadata)
-> Director executes mind request
-> App._on_execute / Scheduler.on_mind_action_started(...)
-> owner freezes Dialogue snapshot
-> worker DialogueBrain.say
-> owner applies visible speech
```

Move **all Life-decision autonomous speech dispatch** to the actual execution boundary, not only social speech.

For social activities:

```text
blocked mind request
=> no visible social speech
=> no pending social bid
=> no USER_IGNORE
```

For non-social activities:

```text
blocked read/comment/etc.
=> no narration pretending the activity happened
```

## Required tests

Use a real Director with a higher-priority current task and a working fake DialogueBrain.

```text
test_blocked_social_mind_request_emits_no_speech
test_blocked_social_mind_request_creates_no_bid_after_worker_time
test_blocked_non_social_mind_request_emits_no_activity_speech
test_executed_mind_request_starts_autonomous_dialogue_exactly_once
test_agent_owned_director_prevents_mind_speech_until_execution
```

The test must wait/drain enough to prove that a worker could not later create the bid.

---

# 4. P0 — Real user Interaction still does not finalize a running mind Activity

Agent preemption is now production-wired through:

```text
Director.on_before_replace
```

That part passes.

But real pet/poke/drag/click interactions do **not** submit an `ActionRequest(source="interaction")`, and the current Scheduler interaction path only:

```text
changes immediate state
interrupt_life(...)
```

It does not immediately finalize the running mind instance or release the mind Director ownership.

Therefore:

```text
mind activity RUNNING
-> user meaningfully interacts
-> interaction consumes attention
-> activity instance can remain RUNNING
-> elapsed continues through the user interaction
```

The required H1 test:

```text
test_user_takeover_finalizes_running_mind_immediately
```

was not implemented. Current preemption tests only prove Agent takeover.

## Required fix

At the finalized meaningful user interaction boundary:

```text
CLICK / PETTING / POKE / DRAG
```

if a `source=mind` activity is actively running:

```text
finalize it immediately exactly once
stop elapsed at interaction takeover
apply partial outcome once
release/replace Director mind ownership
then process interaction response
```

You may either:

- route the semantic interaction through Director as a real `source="interaction"` action, or
- provide one explicit owner-thread user-takeover hook equivalent to Director preemption.

Do not create a second behavior system.

Pointer-control phases:

```text
grab / release / hover / leave
```

must not preempt life by themselves.

## Required tests

Use the real production interaction path:

```text
InteractionEngine.emit_event(...)
```

with a real running mind instance.

```text
test_real_petting_finalizes_running_mind_immediately
test_real_poke_finalizes_running_mind_immediately
test_real_drag_finalizes_running_mind_immediately
test_real_click_finalizes_running_mind_immediately
test_pointer_control_does_not_finalize_mind
test_user_preemption_elapsed_stops_at_interaction_time
test_user_preemption_outcome_exactly_once
test_user_preemption_cannot_later_become_completed
```

---

# 5. P0 — Activity status field violates its own canonical state machine

Current `on_mind_preempted(reason)` writes:

```python
status = reason.upper()
```

so production can create statuses such as:

```text
PREEMPTED_BY_AGENT
PREEMPTED_BY_USER
```

But the Activity lifecycle contract already defined canonical status values:

```text
RUNNING
COMPLETED
INTERRUPTED
ABORTED
FAILED
```

`preempted_by_agent` is a **finish reason**, not a lifecycle status.

This matters because future logic/diagnostics must be able to switch over a stable finite status enum.

## Required fix

Separate:

```text
status
finish_reason
```

Example:

```text
Agent takeover:
status = INTERRUPTED
finish_reason = preempted_by_agent

User takeover:
status = INTERRUPTED
finish_reason = preempted_by_user

explicit cancel:
status = ABORTED
finish_reason = user_cancel / shutdown / ...

tool/runtime failure:
status = FAILED
finish_reason = ...
```

Never encode arbitrary reasons into `status`.

## Required tests

```text
test_agent_preemption_status_is_interrupted
test_user_preemption_status_is_interrupted
test_finish_reason_preserves_preemption_source
test_activity_status_always_in_canonical_set
```

Update tests that currently assert `status == "PREEMPTED_BY_AGENT"`; that assertion encodes the broken behavior.

---

# 6. P0 — Harness startup does not explicitly bind RuntimeDispatcher owner

Formal `launch()` now performs:

```python
sched.dispatcher.bind_owner()
```

but `launch_harness()` does:

```text
sched.start(proxy)
...
start QTimer
```

without explicit owner binding.

`RuntimeDispatcher.require_owner()` now intentionally refuses to auto-bind.

Therefore an early Harness button/input can reach:

```text
submit_user_message / submit_feed
```

before the first timer `sched.step()->drain()` fallback bind and raise:

```text
domain mutation ... requested before runtime owner was bound
```

The unit tests only prove `RuntimeDispatcher.bind_owner()` itself; they do not prove both production startup surfaces are bound.

## Required fix

Put owner binding in the single common runtime startup boundary.

Preferred:

```python
Scheduler.start(...)
    -> dispatcher.bind_owner()
    -> schedule ticks
```

Then both:

```text
launch()
launch_harness()
```

inherit the same contract.

Any extra `launch()` bind may remain idempotent or be removed.

`drain()` may remain a defensive fallback, but production startup must not rely on "first timer probably fires before first click".

## Required tests

```text
test_scheduler_start_binds_owner_to_start_thread
test_launch_path_owner_bound_before_first_user_event
test_harness_path_owner_bound_before_first_user_event
test_harness_first_message_before_first_timer_does_not_raise
test_harness_first_feed_before_first_timer_does_not_raise
```

Use offscreen Qt where needed.

---

# 7. P1 — Idle API failure is preserved as None at WindowAwareness, but downstream runtime still starts from fake-active `0.0`

H1 correctly fixed:

```text
WindowInfo.idle = None
WindowAwareness.idle_available = False
```

However `CharacterState.user_idle_seconds` defaults to:

```python
0.0
```

and Scheduler currently does:

```text
if wa.idle_available:
    state.user_idle_seconds = wa.last_idle

WorldPerception.update(
    idle_seconds=state.user_idle_seconds
)
```

So before the first valid OS idle sample:

```text
raw truth = unavailable
runtime value = 0.0
WorldPerception interprets 0.0 as active/present
```

This is still semantically indistinguishable from a real "user just interacted" sample downstream.

After at least one valid sample, retaining the previous valid value during a temporary API failure is acceptable; the problematic case is **no valid sample has ever existed**.

## Required fix

Represent idle availability explicitly across the runtime boundary.

Minimal acceptable design:

```text
state/world has idle_available (or equivalent)
```

Rules:

```text
valid sample:
    idle_available=True
    update idle_seconds

temporary failure after valid sample:
    idle_available=False for current sample
    last valid idle may be retained for continuity
    no fake "new active" transition is emitted

failure before any valid sample:
    idle_available=False
    do not manufacture USER_BECAME_ACTIVE / USER_RETURNED / AWAY->ACTIVE from default 0
    diagnostics show UNKNOWN/UNAVAILABLE, not measured 0
```

Do not redesign WorldState broadly; one availability bit / Optional boundary is enough.

## Required tests

```text
test_first_idle_sample_unavailable_does_not_claim_measured_zero
test_first_idle_sample_unavailable_emits_no_active_transition
test_valid_idle_sample_sets_available_and_value
test_failure_after_valid_sample_retains_last_value_but_marks_current_unavailable
test_harness_world_diagnostics_exposes_idle_unavailable
```

---

# 8. P1 — One meaningful Interaction currently writes two long-term memories

H1 moved:

```text
App._on_meaningful_interaction
```

before EventBus broadcast.

That method already does:

```text
MemoryEngine.observe(...)
```

for first pet/drag/poke.

Then Scheduler's `INTERACTION_INPUT` consumer still does:

```text
_consolidate_episode(...)
```

on the same semantic interaction.

Both use the same `MemoryEngine` / persistent store, but they are different memory formats/keys, so normal deduplication does not guarantee they collapse into one row.

Thus one physical semantic event can produce two long-term memories.

This is inside H1 §9's exactly-once semantic ordering, not a request to redesign Memory.

## Required fix

Choose **one** long-term memory owner for a finalized Interaction semantic event.

Recommended:

```text
App semantic interaction handler:
Emotion
Relationship
one Memory semantic integration
then broadcast
```

Scheduler must not create a second long-term memory for the same interaction.

Alternatively keep Scheduler consolidation and remove the App `observe` for those same event types.

Do not alter MemoryEngine storage architecture.

## Required tests

Use a temporary real MemoryStore or exact insert/observe/consolidate call counters:

```text
test_one_petting_creates_at_most_one_semantic_long_term_memory
test_one_poke_creates_at_most_one_semantic_long_term_memory
test_one_drag_creates_at_most_one_semantic_long_term_memory
test_repeated_distinct_interactions_remain_distinct_events
```

Relationship and Emotion must still each apply exactly once.

---

# 9. Required false-green replacements

The following current evidence is insufficient and must be replaced/strengthened:

### Interaction

Current H1 test builds a partial `_interaction_app()` that omits the real App EventBus Emotion subscriber.

Required test must reproduce the actual remaining production wiring.

### Dialogue FIFO

Current "turn2 first" test directly calls `_gate_wait(2)`.

Required test must force **production `submit_user_message()` worker2** to enter generation before worker1 while preserving owner submission order.

### Blocked social bid

Current blocked-social test has `dialogue_brain=None`.

Required test must use a successful fake DialogueBrain and prove a Director-blocked request cannot later emit speech/bid after worker time and dispatcher drain.

### User takeover

Current suite tests Agent takeover only.

Required test must drive `InteractionEngine.emit_event()` against a running real mind activity.

### Runtime owner

Current suite tests the dispatcher class, not both startup surfaces.

Required test must verify `launch` and `launch_harness`/common startup.

---

# 10. Regression / evidence format

Create:

```text
docs/FURINA_PHASE13_H1_FINAL_REVIEWER_RESIDUAL_REPORT.md
```

Order:

1. each residual BEFORE reproduction
2. why the old 622-green test missed it
3. production fix
4. deterministic AFTER evidence
5. full regression result
6. STOP

Do not lead with test count.

Required deterministic techniques:

- `threading.Event` / `Barrier`
- bounded `join(timeout=...)`
- controllable clock where needed
- real EventBus / InteractionEngine / Director production path
- exact call counters
- thread IDs
- temporary real MemoryStore where persistence is under test

No source-string-only proof.

---

# 11. Forbidden

Do NOT:

- begin Phase 14
- touch assets
- change renderer/animation
- redesign Spatial
- retune Needs
- retune Relationship
- change Persona
- add catchphrases
- add a new LLM
- add a new DB
- re-enable anti-collapse
- reintroduce diversity forcing
- expand Agent scope
- refactor unrelated modules
- turn this into H2/R2

---

# 12. Final STOP gate

After fixing **only these residuals**:

```text
run full regression
push one coherent commit/series
send:
- commit SHA
- residual report
- exact regression result
STOP
```

Allowed Agent verdict:

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

Reviewer will re-check **only §§1–8 above**.

If those pass:

```text
PHASE 13 TECHNICAL = PASS
BACKEND FUNCTIONAL CONTRACT = FROZEN
```

Next step immediately:

```text
Manual Experience Acceptance
```

Manual is not Phase 14.

Only after Manual passes:

```text
FUNCTIONAL DIGITAL LIFE = PASS
Phase 14 — Frontend Rendering / Asset Integration
```
