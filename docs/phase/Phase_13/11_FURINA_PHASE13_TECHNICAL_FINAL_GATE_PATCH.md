# Furina Desktop AI — Phase 13 Technical Final Gate Patch

**Review baseline:** `4a5767a090fd54d771c56768bad14e604b4aac02`

This is the **last technical gate patch** before Manual Experience Acceptance.

It is NOT:
- H2
- R2
- a new backend phase
- an optimization pass

Reviewer re-checked only the previously agreed §§1–8 residual contracts.

## Reviewer result

The following are accepted and FROZEN:

```text
§1 Interaction Emotion exactly-once        PASS
§2 Direct Dialogue ingress FIFO            PASS
§4 Real user Interaction takeover          PASS
§5 Canonical Activity status               PASS
§6 Common runtime owner binding            PASS
§8 Interaction long-term Memory exactly-once PASS
```

Two explicit residual blockers remain:

```text
§3 Director priority arbitration            FAIL
§7 idle availability initial truth          FAIL
```

Fix ONLY these two blockers.

If they pass:

```text
PHASE 13 TECHNICAL = PASS
BACKEND FUNCTIONAL CONTRACT = FROZEN
NEXT = Manual Experience Acceptance
```

There is no further ordinary technical closeout after this patch.

---

# 1. P0 — Director allows a lower-priority mind request to replace an active Agent

## Production root cause

Director priority contract:

```text
smaller number = higher priority

P_USER_INTERACTION = 1
P_AGENT_TASK       = 2
P_INTERNAL_NEED    = 3
P_AUTONOMOUS       = 4
```

Current `Director.drain()` effectively only blocks a lower/equal request when:

```python
current.interruptible is False
```

Current shape:

```python
if self._current and req.priority >= self._current.priority \
        and self._current.interruptible is False:
    requeue(req)
    return

# otherwise replacement occurs
self._current = req
```

Therefore:

```text
current Agent:
    priority=2
    interruptible=True   # ActionRequest default

queued mind:
    priority=3

director.drain()
```

can incorrectly do:

```text
Agent(2) -> mind(3)
```

even though mind is LOWER priority.

This violates the Director hierarchy and directly breaks residual §3:

```text
Agent owns Director
-> blocked Life mind request
-> must NOT execute
-> must NOT speak
-> must NOT start social bid
```

## Why the current 657-green blocked-mind test is false-green

The current test does:

```text
1. submit Agent
2. director.drain()  # Agent becomes current
3. sched._apply_life_decision(...)  # mind is only queued
4. sleep
5. sched.dispatcher.drain()
6. assert say_calls == 0
```

It does **not call `director.drain()` after the mind request is queued**.

So `say_calls==0` proves only:

```text
"an undrained queued request did not execute"
```

not:

```text
"an active higher-priority Agent blocked the lower-priority mind request"
```

In real Scheduler production, `director.drain()` is called every medium tick, so the bug is reachable.

---

## Required production fix

Director arbitration must respect priority independently of `interruptible`.

Minimum invariant:

```text
lower-priority request may NEVER replace a higher-priority current action
```

Preserve current same-priority behavior unless a real regression requires otherwise.

A minimal safe shape is conceptually:

```python
if current is not None:
    if req.priority > current.priority:
        # strictly lower priority
        requeue(req)
        return

    if req.priority == current.priority:
        # preserve existing intended same-priority semantics
        # especially Agent phase -> Agent phase if currently relied upon
        ...

    # req.priority < current.priority:
    # higher-priority request may preempt according to existing policy
```

Do not rewrite Director architecture.

Do not change the priority constants.

Do not make Agent artificially `interruptible=False` just to hide the arbitration bug.
The Director itself must enforce priority truth.

---

## Required deterministic tests

### A. Direct Director contract

```text
test_lower_priority_mind_cannot_preempt_active_agent
```

Exact scenario:

```text
current = Agent priority 2, interruptible=True
queue   = mind priority 3
call director.drain()
```

Assert:

```text
director.current().source == "agent"
mind executor call count == 0
mind remains queued/deferred
```

Call `director.drain()` repeatedly while Agent is current.

Still:

```text
current == agent
mind execute count == 0
```

### B. Higher priority must still work

```text
test_higher_priority_agent_preempts_running_mind
```

```text
current mind priority 3
new Agent priority 2
director.drain()
```

Assert Agent takes over and existing Activity preemption contract still fires exactly once.

### C. Do not accidentally break equal-priority Agent phase transitions

If production currently relies on:

```text
agent_planning -> agent_executing -> agent_verifying
```

all at priority 2, add:

```text
test_equal_priority_same_source_agent_phase_transition_still_works
```

Do not make the priority fix freeze Agent on its first phase.

### D. Full §3 production integration

Replace/strengthen the current false-green blocked-mind test.

Use:

```text
real Director
real Scheduler
production-equivalent App._on_execute executor
working fake DialogueBrain
```

Sequence:

```text
1. Agent priority 2 becomes Director current
2. LifeDecision(talk, speech_level=3) is submitted
3. call director.drain() multiple times
4. wait enough for any incorrectly launched worker
5. drain RuntimeDispatcher
```

Required:

```text
Director current == Agent
Dialogue say_calls == 0
_pending_social_bid is None
no mind ActivityInstance started
```

Then:

```text
6. director.finish(source="agent")
7. director.drain()
```

Now and only now:

```text
mind executes
ActivityInstance starts
Dialogue say_calls == 1
visible social speech can open one bid
```

Required test names:

```text
test_active_agent_blocks_lower_priority_mind_across_real_drains
test_blocked_mind_has_no_activity_instance
test_blocked_mind_has_no_autonomous_speech_or_bid
test_deferred_mind_executes_only_after_agent_finishes
```

The test is invalid if it omits `director.drain()` while Agent is active.

---

# 2. P1 — `idle_available` still starts as fake True before any OS evidence exists

## Production root cause

H1-FINAL correctly propagates an explicit availability bit after WindowAwareness polls.

However the initial dataclass truth is still:

```python
CharacterState:
    user_idle_seconds = 0.0
    idle_available = True

WorldState:
    user_idle_seconds = 0.0
    idle_available = True
```

Harness diagnostics also uses:

```python
getattr(st, "idle_available", True)
```

But at process startup, before the first Windows idle sample:

```text
no GetLastInputInfo result has ever been obtained
```

so the truthful state is:

```text
idle_available = False
idle_seconds = unknown/unmeasured
```

not:

```text
idle_available = True
idle_seconds = 0.0
```

This creates a short startup window where diagnostics/runtime can claim the default zero is measured truth.

---

## Required fix

### A. Truthful defaults

Change initial defaults to:

```python
CharacterState.idle_available = False
WorldState.idle_available = False
```

Keep `user_idle_seconds=0.0` only as a storage placeholder; it must not be interpreted as measured while availability=False.

### B. Scheduler fallback must be conservative

Current:

```python
idle_avail = bool(getattr(self.wa, "idle_available", True))
```

must not default to True.

Use:

```python
idle_avail = bool(getattr(self.wa, "idle_available", False))
```

### C. Harness diagnostics fallback must be conservative

Current:

```python
getattr(st, "idle_available", True)
```

must default False.

### D. Expose availability in state snapshots where idle truth is exposed

If `CharacterState.snapshot()` exposes:

```text
user_idle
```

it must also expose:

```text
idle_available
```

so downstream debugging/decision consumers cannot accidentally treat placeholder zero as measured truth.

Likewise, if `WorldState.to_dict()` exposes idle-derived truth to diagnostics/context, include `idle_available`.

Do not redesign these data structures; add the availability bit only.

### E. Unknown state must not claim active

In the `WorldPerception.update(... idle_available=False)` branch before any valid sample has ever existed, ensure:

```text
user_activity = UNKNOWN
user_active = False
interaction_availability = 0
last_events = []
```

The exact value of the legacy boolean `user_present` may remain conservative if needed, but any consumer that interprets "active now" must not receive True from an unmeasured default.

Do not manufacture:
- USER_BECAME_ACTIVE
- USER_RETURNED
- USER_LEFT
- WORK_STARTED/ENDED from idle transitions

until real relevant evidence exists.

---

## Required deterministic tests

```text
test_character_state_idle_available_defaults_false
test_world_state_idle_available_defaults_false
test_scheduler_idle_availability_missing_attr_defaults_false
test_harness_idle_availability_missing_attr_defaults_false
test_character_snapshot_pairs_user_idle_with_availability
test_world_dict_exposes_idle_availability
test_first_unavailable_idle_sample_user_active_is_false
```

Also keep all existing H1 idle tests green:

```text
first unavailable sample -> UNKNOWN / zero new idle events
valid sample -> available=True + exact value
temporary failure after valid sample -> retain last valid continuity + current availability=False
```

### Startup integration proof

Before the first medium poll:

```text
Scheduler constructed
Scheduler.start()
Harness/runtime diagnostics read
```

must show:

```text
idle_available=False
```

After first failed/unavailable poll:

```text
idle_available=False
```

After first successful sample:

```text
idle_available=True
idle_seconds=<measured value>
```

---

# 3. Freeze the other six residual contracts

Do not touch except for mechanical compatibility with §§1–2:

```text
§1 Emotion single owner                FROZEN PASS
§2 owner-ingress Dialogue seq          FROZEN PASS
§4 user interaction takeover           FROZEN PASS
§5 canonical Activity status           FROZEN PASS
§6 Scheduler.start owner binding        FROZEN PASS
§8 one Interaction long-term memory     FROZEN PASS
```

Specifically do NOT:
- rewrite Dialogue FIFO
- change Interaction ordering
- change Activity reward scaling
- change Memory ownership
- touch Emotion mappings
- move owner binding again
- touch Spatial
- tune Needs/Relationship/Persona

---

# 4. Regression/evidence

Create:

```text
docs/FURINA_PHASE13_TECHNICAL_FINAL_GATE_REPORT.md
```

Report order:

1. Director priority BEFORE reproduction
2. why old 657 test was false-green
3. Director production fix
4. real-drain AFTER evidence
5. idle default BEFORE truth mismatch
6. idle default/fallback AFTER evidence
7. full regression
8. STOP

Do not lead with test count.

No source-string-only proof.

Use actual:
- Director
- ActionRequest
- Scheduler
- production-equivalent App executor
- repeated `director.drain()`
- exact call counters
- bounded waits for Dialogue worker
- runtime diagnostics for idle

---

# 5. Forbidden

Do NOT:
- start Manual in the Agent
- start Phase 14
- touch assets/renderer/animation
- redesign Director
- change priority constants
- make Agent non-interruptible as a workaround
- retune Life cadence
- retune Needs
- retune Relationship
- modify Persona
- add LLM/DB
- reopen Spatial
- add anti-collapse/diversity forcing
- refactor unrelated code

---

# 6. Final release gate

After fixing ONLY §§1–2:

```text
run full regression
push one coherent commit
send:
- SHA
- docs/FURINA_PHASE13_TECHNICAL_FINAL_GATE_REPORT.md
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

Reviewer will check only:

```text
A. higher-priority Agent truly blocks lower-priority mind through real Director drains
B. idle availability is false until actual evidence exists
```

If both pass:

```text
PHASE 13 TECHNICAL = PASS
BACKEND FUNCTIONAL CONTRACT = FROZEN
```

Then immediately:

```text
Manual Experience Acceptance
```

Only after Manual passes:

```text
FUNCTIONAL DIGITAL LIFE = PASS
Phase 14 — Frontend Rendering / Asset Integration
```
