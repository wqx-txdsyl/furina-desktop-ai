# Furina Desktop AI — Phase 13 FINAL-R1 Reviewer Residual Truth Closeout

**Review baseline:** `9f5e44f34d02e94ca8034f20ea3f1738984bbd50`

**Entering verdict:**

```text
Phase 13 automated regression report = 530 PASS reported by Agent
Phase 13 technical reviewer verdict  = PARTIAL
Manual Experience Acceptance         = BLOCKED
Phase 14 Frontend / Assets           = BLOCKED
```

This is **not a new backend feature phase**.  
This is the final residual closeout for explicit reviewer-verified defects that remain in `9f5e44f`.

After this task, STOP. Do not continue ordinary optimization.

---

# 0. Freeze what already passed

Do **not** reopen or retune the following unless a regression from this task requires a mechanical fix:

- C-R2 canonical Relationship scale contract
- LifeBrain `_apply_variety()` production call = OFF
- BehaviorMotivation diversity-only `_category_penalty/_activity_penalty/_observation_crush_guard` production multipliers = OFF
- human-scale Needs constants as currently designed
- Memory store/retrieve/restart architecture
- Memory `behavior_hint()` canonical relationship normalization
- Dialogue validator bounded regeneration concept
- DECLINE-before-question act precedence
- current-turn dialogue dedup
- bounded conversation memory
- Outcome relationship self-farm removal
- social_need duplicate field removal
- planner calculator mapping / unknown-app no-notepad fallback
- app.launch permission = side-effecting permission
- spatial approach/withdraw smoothing
- spatial wander/explore corner-rounding design
- drag/release no-snap-back behavior
- assets / animation / renderer

No asset changes. No new LLM. No new DB. No new persona catchphrase bank. No Needs/Emotion/Relationship parameter tuning to make output distributions look good.

---

# 1. P0 — Windows World truth still has two production defects

## 1.1 `GetTickCount` is called from the wrong DLL

Current `furina/runtime/window_awareness.py` effectively does:

```python
user32 = ctypes.windll.user32
...
ticks = user32.GetTickCount()
```

`GetLastInputInfo` belongs to User32, but `GetTickCount` / `GetTickCount64` belongs to Kernel32.

Because `_get_idle_seconds()` catches all exceptions and returns `None`, this can silently degrade to:

```text
idle = 0.0
```

and make Furina believe the user is always active.

### Required fix

Use a correct Windows tick source:

```text
GetLastInputInfo -> User32
GetTickCount64   -> Kernel32   (preferred)
```

If using 32-bit `GetTickCount`, handle wrap correctly. Prefer `GetTickCount64`.

Do not silently convert an API failure into a truthful-looking idle `0.0`.

Represent unavailable idle truth explicitly until a valid sample exists.

### Tests

Behavioral API-mock tests, not source-string tests:

```text
test_windows_idle_uses_kernel32_tick_source
test_windows_idle_nonzero_sample_exact
test_windows_idle_api_failure_is_not_fake_zero_activity
```

Example deterministic sample:

```text
current tick = 120000 ms
last input   = 90000 ms
idle         = 30.0 s
```

must produce ~30.0.

---

## 1.2 WorldPerception is updated twice per medium tick with conflicting identities

Current flow:

```text
_tick_medium
  -> wa.poll()
     -> ACTIVE_WINDOW_UPDATED
        -> Scheduler._on_window()
           -> world_perc.update(app=WINDOW_CLASS, process omitted)
  -> later in the same _tick_medium
     -> world_perc.update(app=WINDOW_CLASS, process=REAL_PROCESS)
```

The first call can classify an Electron/Chrome-style window class as `UNKNOWN`.
The second call can classify the process as `CODING/BROWSING/...`.

With the new 30s pending stability window this can reset the pending candidate every tick:

```text
UNKNOWN -> CODING -> UNKNOWN -> CODING ...
```

so a real transition such as browser -> VS Code may never accumulate 30s and never commit.

### Required fix

There must be **one authoritative WorldPerception.update() per medium sample**.

Recommended:

```text
WindowAwareness.poll()
  -> cache raw WindowInfo only
  -> Scheduler captures:
       local hour/minute
       real idle
       class
       process
       title
       rect
  -> exactly one WorldPerception.update(...)
```

`_on_window()` may update raw active-window facts/geometry, but must not independently advance WorldPerception state/stability.

### Required integration test

Do not only unit-test `WorldPerception` directly.

Simulate the actual Scheduler sampling path:

```text
stable browser/chrome
-> switch to Code process with Electron/Chrome_Widget style class
-> 30+ seconds of medium ticks
```

Assert:

```text
World.user_activity == CODING
state.user_working == True
pending candidate did not reset due to class/process double feed
```

Also test coding -> browser.

Tests:

```text
test_scheduler_world_updates_once_per_medium_sample
test_scheduler_browser_to_code_transition_reaches_coding
test_scheduler_code_to_browser_transition_reaches_browsing
```

---

# 2. P0 — Emotion authority is still not fully single-owner / immediate

## 2.1 Scheduler `_on_brain()` still writes EmotionState.label

Current latest code still contains:

```python
self.se.state.emotion.label = getattr(out, "emotion", self.se.state.emotion.label)
```

inside `Scheduler._on_brain()`.

This violates the explicit contract:

```text
EmotionEngine owns emotional truth.
```

A BRAIN_SPOKE payload must never be able to overwrite authoritative emotion, especially with a stale worker-thread snapshot.

### Required fix

Delete the write.

If BRAIN_SPOKE needs an expression hint, keep it in a non-authoritative field such as `Intent.emotion`; never mutate `EmotionState.label`.

Required test:

```text
authoritative emotion = embarrassed
emit BRAIN_SPOKE(payload.emotion="happy")
drain apply
=> EmotionState.label remains embarrassed
```

---

## 2.2 Semantic event dimensions update before label, so immediate dialogue can see stale emotion

`EmotionEngine.apply(EVENT_PRAISE)` changes dimensions but does not derive the new label.

Production routes then immediately call DialogueBrain using:

```python
self.state.state.emotion.label
```

Examples:

```text
praise
reject
feed
pet/poke/drag
agent_done
```

Therefore the current reply can still be generated with the pre-event label until the next medium tick.

### Required fix

Create/reuse one authoritative semantic-emotion application boundary:

```text
semantic event
-> EmotionEngine.apply(event)
-> derive authoritative label immediately
   using current real tired_hint when needed
-> downstream Dialogue/Body snapshots
```

Do not hardcode event -> label. Dimensions remain the truth; derive from dimensions.

All of this must execute on the runtime owner thread (§3 below).

Required tests:

```text
test_praise_label_is_updated_before_praise_dialogue_snapshot
test_reject_label_is_updated_before_rejection_dialogue_snapshot
test_feed_label_is_updated_before_feed_dialogue_snapshot
test_agent_done_label_is_updated_before_agent_dialogue_snapshot
```

---

## 2.3 Work start/end semantic events remain unwired

EmotionEngine defines:

```text
EVENT_WORK_START
EVENT_WORK_END
```

but current Scheduler World update path does not consume stable `WORK_STARTED/WORK_ENDED` into those emotion events.

### Required fix

After a **stable** World transition, route:

```text
WORK_STARTED -> EVENT_WORK_START
WORK_ENDED   -> EVENT_WORK_END
```

exactly once.

Do not fire from unstable pending candidates.

Tests:

```text
test_stable_work_start_emotion_event_once
test_stable_work_end_emotion_event_once
```

---

## 2.4 Unknown pointer/control events must not become fake emotion events

Current App event listener can call:

```python
emotion.apply(None)
```

for unmapped `INTERACTION_INPUT` kinds.

Even if the delta is zero, this pollutes `_recent` diagnostics with a fake `None` semantic event.

### Required fix

Only call EmotionEngine when an explicit semantic mapping exists.

Also remove the duplicate/dead first `EmotionEngine` class definition in `emotion/engine.py`; keep one implementation.

Tests:

```text
test_unmapped_pointer_control_does_not_enter_emotion_recent
test_emotion_engine_single_production_definition
```

---

# 3. P0 — Runtime owner-thread contract is only half implemented

The new Scheduler apply queue correctly marshals:

```text
BRAIN_SPOKE
AGENT_COMPLETED
AGENT_FAILED
```

But production workers still mutate domain state directly.

## Verified examples

### User dialogue worker

`App._brain_worker()` runs in a background thread and directly performs:

```text
_apply_user_text_fx()
  -> Relationship mutation / rejection route
EmotionEngine.apply(EVENT_TALK)
Memory.observe(...)
```

### Agent worker

`App._agent_worker()` starts in a background thread and directly writes:

```python
self.state.state.life.macro = WORKING
self.state.state.life.activity = "agent_planning"
```

### Agent body callback

`AgentRuntime._body()` runs from Agent worker.
`App._on_agent_body()` calls `Director.submit()` directly from that worker.
Director's heap queue is part of runtime ownership and should not be mutated from arbitrary workers.

### Harness Feed

GUI calls `_feed()` directly on owner thread, while Harness wraps `_feed()` in another worker thread.
This makes the two paths semantically different and causes deterministic Food/Emotion/Memory/Life mutations to occur on different thread owners.

## Required fix

Create one small public runtime apply/dispatch boundary. Do not rewrite the entire EventBus.

Concept:

```text
owner thread:
  deterministic domain mutation
  Director queue mutation
  state mutation
  Emotion/Relationship mutation
  final event application

worker threads:
  LLM network I/O
  tool execution / slow OS I/O
  immutable computation/snapshots
```

A `queue.Queue` / `SimpleQueue` or equivalent explicit dispatcher is preferred over relying on `list.append + GIL`.

### User dialogue production entry

Create one production entry, e.g.:

```text
submit_user_message(text)
```

called by GUI and Harness.

It must preserve user-input sequence and arrange:

```text
owner: high-confidence semantic event / relationship / emotion
worker: Dialogue LLM
owner: final speech/frame apply + post-turn memory commit as appropriate
```

No direct shared-domain mutation from worker.

### Feed production entry

Create one production entry, e.g.:

```text
submit_feed(food)
```

called by both GUI and Harness.

Deterministic food effect + semantic Emotion + memory/life event executes exactly once on owner thread.
Slow Dialogue runs off-thread.
Final speech returns to owner apply queue.

Harness must not add a second wrapper thread around the domain mutation.

### Agent

Agent start/body phases must enter owner queue/Director through the runtime dispatcher.
`_agent_worker()` must not directly write CharacterState.
`Director.submit()` from Agent body callbacks must be marshalled to owner.

Tests must capture thread IDs, not source strings:

```text
test_text_praise_domain_apply_runs_on_owner_thread
test_text_reject_domain_apply_runs_on_owner_thread
test_talk_emotion_apply_runs_on_owner_thread
test_agent_planning_state_runs_on_owner_thread
test_agent_body_director_submit_runs_on_owner_thread
test_feed_domain_effect_runs_on_owner_thread
test_worker_threads_only_return_results_to_owner
```

Qt must remain responsive.

---

# 4. P0 — Dialogue needs true input FIFO and channel-safe history

## 4.1 RLock serialization is not a FIFO contract

Latest DialogueBrain holds one `RLock` around the whole LLM call.

That prevents simultaneous mutation but Python lock acquisition order is not an input-order guarantee.

The required truth is:

```text
user input sequence 1
user input sequence 2
```

must always yield direct-turn chronology:

```text
user1
furina1
user2
furina2
```

regardless of worker scheduling.

### Required fix

Assign sequence at message ingress and use an explicit FIFO dialogue executor/queue (or equivalent deterministic sequencing).

Do not rely on “thread 1 was started first, so it probably acquired RLock first”.

The lock can remain as an internal safety guard but cannot be the ordering mechanism.

---

## 4.2 Autonomous / Feed / Agent speech currently enters direct-user `_history`

Every successful `DialogueBrain.say()` ends with:

```python
self.push_history("furina", speech)
```

even when there is no direct user turn.

Thus:

```text
autonomous speech
feed speech
Agent report speech
```

can appear as orphan Furina turns in the same short-term history later fed to direct conversation.

This violates the previous contract:

> Autonomous/Feed/Agent speech must not corrupt direct-user turn history.

### Required fix

Use explicit dialogue channel/turn semantics.

At minimum distinguish:

```text
DIRECT_USER_TURN
AMBIENT_AUTONOMOUS
FEED_REACTION
AGENT_REPORT
INTERACTION_REACTION
```

The bounded direct conversation history must contain coherent user/Furina turn pairs only.

Ambient/shared events can be provided as separate recent-context facts when relevant, but not masquerade as direct dialogue history.

No new DB.

Tests:

```text
test_direct_user_ingress_is_strict_fifo
test_second_input_cannot_overtake_first_before_lock_acquisition
test_autonomous_speech_not_added_as_orphan_direct_turn
test_feed_speech_not_added_as_orphan_direct_turn
test_agent_report_not_added_as_orphan_direct_turn
test_direct_history_remains_coherent_after_ambient_speech
```

---

# 5. P0 — Activity lifecycle must start from actual Director execution, not Life decision submission

Latest Scheduler does improve replacement semantics, but still starts the lifecycle too early.

Current order is effectively:

```text
LifeDecision produced
-> previous outcome settled
-> NEW activity instance created
-> motivation.mark_done(new activity)
-> ActionRequest submitted to Director
-> Director may or may not execute it later
```

If a higher-priority Agent/user action owns Director, the mind request can remain queued.

The character has **not actually started** the Life activity, yet:

```text
activity instance timer is running
_current_life_activity changed
recency mark_done applied
```

A later decision can therefore settle Outcome for an activity that never executed.

## Required fix

Activity lifecycle starts only when the Director actually applies/starts that `source=mind` action.

Recommended boundary:

```text
LifeDecision
-> ActionRequest queued
-> Director executes
-> ACTION_STARTED / executor confirmation
-> create ActivityInstance
-> mark_started
```

Do not create a completed/interruptible activity instance merely because a decision was submitted.

### Explicit lifecycle result

Represent at minimum:

```text
RUNNING
COMPLETED
INTERRUPTED
FAILED
ABORTED
```

with:

```text
instance_id
activity
started_at
planned_duration
elapsed
progress
finish_reason
source request id / decision id
```

### Interrupted progress is not always a fixed 50%

Current `success=False` gives the same 0.5 scale regardless of whether the activity ran ~10% or ~70%.

The original acceptance evidence explicitly required 10% and 70% interruption cases.

Outcome must reflect real progress / semantic completion.

Do not over-engineer simulation physics; a bounded progress-aware scale is enough.

Required proof:

```text
10% interrupted reward < 70% interrupted reward < completed reward
```

### `mark_done`

Do not call `mark_done()` when a decision is merely submitted.
Only update recency/history from an activity that actually started/finished according to the chosen semantic.

### Outcome spec copy safety

`dataclasses.replace()` only shallow-copies the `needs` / `emotion` dicts.
Do not expose mutable dictionaries shared with global `OUTCOMES`.

Use immutable specs or copy nested dicts.

Tests:

```text
test_queued_mind_action_does_not_start_activity_instance
test_blocked_mind_action_cannot_receive_outcome
test_activity_instance_starts_on_director_execution
test_mark_done_not_called_for_unexecuted_request
test_activity_status_completed_interrupted_failed_aborted
test_interrupted_10pct_less_reward_than_70pct
test_interrupted_70pct_less_reward_than_completed
test_outcome_nested_specs_not_shared_mutable
```

Keep already-passed:
- no relationship self-farm
- social_need exactly once.

---

# 6. P0 — Agent verified gate is still functionally broken

This is a verified false-green in `9f5e44f`.

## Production bug

`ToolResult` has a real field:

```python
verified: bool
```

`LaunchTool` correctly returns:

```text
ok=True
verified=False
```

when `Popen()` occurred but process observation failed.

However `AgentRuntime._verify()` currently:

```text
for fs tools -> checks data is not None
for other tools -> return True
```

It does **not require `res.verified == True`**.

Therefore:

```text
app.launch:
Popen succeeds
observable process verification fails
ToolResult(ok=True, verified=False)
AgentRuntime._verify() -> True
AGENT_COMPLETED
```

This violates the central Agent truth contract.

## Why the new “530” contract test is false-green

`test_agent_completed_only_after_all_verified()` uses:

```text
path="/tmp/xxx"
```

without creating the directory.

The plan fails at the earlier `fs.list_dir` step before reaching the mocked:

```text
OrganizeTool(... verified=False)
```

so the assertion “not completed” passes for the wrong reason.

The test never proves the intended verified gate.

## Required fix

Minimum verification rule:

```text
required step success =
    res.ok is True
    AND res.verified is True
    AND any additional runtime semantic verification passes
```

Tool-specific semantic checks may make the gate stricter, never looser than `res.verified`.

`BaseTool.verify` semantics should be honored consistently.

### app.launch

If process observation returns false:

```text
status != completed
AGENT_COMPLETED count = 0
Agent state = UNVERIFIED/FAILED
```

On modern Windows, do not assume the launcher executable name is always the final observable application process.
Calculator in particular may need an app-specific observable process/window alias.

Verify an observable application outcome robustly.

### Rewrite the false-green tests

Use `tmp_path` and create the full prerequisites so execution definitely reaches the mocked unverified step.

Assert the mocked step call count > 0.

Required tests:

```text
test_toolresult_verified_false_is_global_hard_gate
test_unverified_launch_cannot_complete
test_agent_completed_only_after_all_verified_reaches_target_step
test_agent_completed_contract_test_not_early_failure
test_calculator_launch_verifier_accepts_real_windows_observable_identity
test_launch_observation_failure_emits_no_completed
```

Keep task-local context and planner mapping fixes frozen.

---

# 7. P1 — Semantic Ignore needs a real production trigger

`Scheduler.on_user_ignore()` is now a valid semantic route and Harness no longer maps Ignore to pointer leave.

That part passes.

But the product contract was:

> A real ignore corresponds to Furina initiating social contact and the user not responding within a defined response window.

A manual Harness Ignore button alone is not the production detector.

## Required fix

Add a small response-window tracker for actual Furina-initiated social attempts.

Concept:

```text
Furina initiates eligible direct social bid
-> pending_response token + deadline
-> real user response cancels token
-> deadline expires without response
-> semantic USER_IGNORE exactly once
```

Do not count:
- autonomous self-talk
- non-social ambient line
- pointer leave
- user absent from the start
- Agent/system status

Do not tune the timeout for diversity; document it as interaction semantics.

Harness “Ignore” may still invoke the same semantic route directly for deterministic testing.

Tests:

```text
test_social_bid_without_response_emits_ignore_once
test_user_response_cancels_pending_ignore
test_pointer_leave_never_resolves_as_ignore
test_autonomous_ambient_speech_does_not_start_ignore_window
test_user_absent_does_not_create_fake_ignore
```

---

# 8. P1 — Harness still has two fake-truth paths

## 8.1 Agent status is overwritten back to IDLE

Harness Agent event handlers correctly set:

```text
RUNNING
COMPLETED_VERIFIED
FAILED
UNVERIFIED
```

But `runtime_health()` then calls `_read_agent_state()`.

`_read_agent_state()` reads:

```text
agent._busy
agent._last_err
agent._last_success
```

The latest `AgentRuntime` does not define/update those fields.

So `runtime_health()` can overwrite the event-derived real state back to `IDLE`.

### Required fix

Choose **one** Agent status owner.

Recommended:
- AgentRuntime exposes an explicit lifecycle/status field updated on every real lifecycle transition;
- Harness only reads that truth.

Or keep controller event state, but do not overwrite it from nonexistent fields.

Required behavioral test:

```text
started event -> runtime_health()["agent"] == RUNNING
unverified -> runtime_health()["agent"] == UNVERIFIED
failed -> runtime_health()["agent"] == FAILED
verified complete -> runtime_health()["agent"] == COMPLETED_VERIFIED
```

Do not test `_agent_state` directly and skip `runtime_health()`.

---

## 8.2 Life LAST_OK/LAST_FAILED is aggregate, not latest

Current Life health tracks aggregate counts:

```text
attempt
success
fallback
failure
```

and `life_badge()` checks “any success” before “any failure”.

Sequence:

```text
success
then latest call fails
```

can still display:

```text
LAST_OK
```

because success count remains >0.

### Required fix

Track explicit latest outcome:

```text
last_outcome = OK / FAILED / FALLBACK / NONE
last_attempt_at
```

Badge uses the latest attempt, counts are diagnostic only.

Test:

```text
success -> failure => LAST_FAILED
failure -> success => LAST_OK
success -> fallback => FALLBACK
```

---

## 8.3 Feed test must verify behavior, not source text

Current tests mostly prove:

```text
GUI source contains self._feed
Harness source contains self.app._feed
```

but Harness currently adds a worker-thread wrapper around `_feed`, so thread/domain semantics differ.

After §3 unified `submit_feed`, test actual calls/events/thread ownership, not source strings.

---

# 9. P1 — Work/interaction event ordering must provide current truth to Dialogue

Once §2/§3 are fixed, ensure finalized semantic interactions follow one order:

```text
final semantic event
-> owner-thread Emotion / Relationship / Needs effect
-> authoritative derived state
-> Dialogue context snapshot
-> Dialogue worker
-> owner-thread speech apply
```

This avoids starting a dialogue worker before Relationship/Emotion has finished updating.

Do not create a second Interaction system.

Tests:

```text
test_petting_dialogue_snapshot_sees_post_event_emotion
test_praise_dialogue_snapshot_sees_post_event_relationship
test_reject_dialogue_snapshot_sees_post_event_relationship_and_emotion
```

---

# 10. Spatial / Needs / Memory — freeze for Technical review

For this residual task:

## Spatial

Current `9f5e44f` wander/explore implementation now uses rounded path sampling.
Do not redesign it.

Only keep regression tests:

```text
max heading delta < 45°
path stable
wander dwell
drag/release no snap-back
```

Human visual naturalness belongs to Manual.

## Needs

Do not retune the new human-scale constants in this task.

Whether the resulting 2h/4h/8h subjective rhythm feels right belongs to Manual unless a deterministic time-unit bug is found.

## Memory

Core store/retrieve/restart and canonical relationship normalization are frozen.

No new DB.

---

# 11. Required regression/evidence

Do not lead report with test count.

First show each reviewer residual failing BEFORE and passing AFTER.

Mandatory evidence bundle:

## World

```text
Win32 mocked idle = 30.0s
browser -> code actual Scheduler path after stable window -> CODING
code -> browser -> BROWSING
exactly one WorldPerception update per medium sample
```

## Emotion

```text
BRAIN_SPOKE payload cannot overwrite authoritative label
praise/reject/feed/agent_done dialogue snapshots see post-event label
WORK_STARTED/WORK_ENDED semantic event count = 1
```

## Thread

Record thread IDs:

```text
GUI/runtime owner
dialogue worker
agent worker
feed dialogue worker
```

Prove all domain mutations listed in §3 happen on owner.

## Dialogue

Deliberately control worker scheduling so message #2 attempts execution before #1.
Still output:

```text
user1
furina1
user2
furina2
```

Then inject autonomous/feed/Agent speech and show direct history remains coherent.

## Activity lifecycle

Show:

```text
queued-but-never-executed mind action -> no instance/no outcome

COMPLETED
INTERRUPTED @10%
INTERRUPTED @70%
FAILED
ABORTED
```

with exact reward ordering.

## Agent

Show:

```text
notepad observable verify success -> completed
calculator observable verify success -> completed
observable verify failure -> NOT completed
ToolResult(ok=True, verified=False) -> NOT completed
target mocked unverified step was actually executed
```

## Ignore

Show pending social bid:
- timeout -> one ignore
- response -> zero ignore.

## Harness

Call `runtime_health()` after lifecycle events; show exact badge/status transitions.

---

# 12. Tests

Add real behavioral tests for every item above.

Source-string tests may remain as guardrails but **cannot be the only evidence** for runtime semantics.

Explicitly replace/fix these false-green patterns:

```text
test_agent_completed_only_after_all_verified
test_harness_agent_unverified_not_green
test_gui_feed_uses_same_submit_path_as_harness
test_state_user_working_comes_from_world
```

because their current form does not exercise the complete production behavior claimed by the test name.

All existing tests remain green unless an existing test encodes a now-proven broken behavior. Document replacements.

---

# 13. Report

Create:

```text
docs/FURINA_PHASE13_FINAL_R1_REVIEWER_CLOSEOUT_REPORT.md
```

Order:

1. reviewer residual reproduced
2. root cause
3. production fix
4. deterministic evidence
5. strengthened false-green tests
6. full regression
7. remaining Manual-only items
8. STOP

Do not claim Persona PASS.

Allowed final state:

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

---

# 14. Forbidden

Do NOT:

- begin Phase 14
- touch image assets
- add animation polish
- add a new LLM
- add a new DB
- redesign Persona
- tune Needs to make demos look varied
- re-enable anti-collapse
- add activity rotation
- add fake Furina line banks
- change Relationship weights for diversity
- use test count as proof
- make Harness hide failures
- call a submitted-but-not-executed action “activity started”
- call `ok=True, verified=False` a completed Agent step

---

# 15. STOP / release gate

After implementation:

```text
STOP DEVELOPMENT
PUSH ONE COHERENT COMMIT/SERIES
SEND COMMIT SHA + REPORT
WAIT FOR REVIEWER
```

Reviewer will re-check **only the residual contracts in this file**.

If they pass:

```text
PHASE 13 TECHNICAL = PASS
```

Then the next gate is immediately:

# Manual Experience Acceptance

Manual is **not Phase 14**.

Manual will cover:

- long-running Life cadence
- quiet coexistence
- real Windows World perception
- emotion causality as experienced
- touch / poke / drag / reject / ignore / recovery
- conversation continuity
- Memory recall/restart
- Feed
- verified Agent actions
- actual spatial naturalness
- real glm-4v-flash Persona blind review
- Qt/Windows responsiveness
- failure behavior

Only if Manual passes:

```text
FUNCTIONAL DIGITAL LIFE = PASS
```

Then and only then enter:

# Phase 14 — Frontend Rendering / Asset Integration

At that point backend semantics freeze except true regressions.
