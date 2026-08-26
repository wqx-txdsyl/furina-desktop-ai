# Furina Desktop AI — Phase 13 Pre-Manual FINAL Fallback Presence Patch

**Review baseline:** `e5ce9fbad0d2d6d9eefd523dff5b02338976fbc5`

## 0. Reviewer verdict

The Pre-Manual World Truth Integration hotfix is **accepted for the main production chain**:

```text
WorldPerception canonical snapshot          PASS
PresenceFacts canonical boundary            PASS
LifeBrain structured World                  PASS
LifeBrain user snapshot                     PASS
Character appraisal presence                PASS
interaction_opportunity                     PASS
Motivation feasibility                      PASS
USER_RETURNED event-instance route          PASS
Social bid / Ignore presence gate           PASS
Autonomous Dialogue presence                PASS
Embodiment / Frame presence                 PASS
Direct message / Feed explicit presence     PASS
Interaction explicit presence               PASS
```

The audit found **one remaining root cluster in fallback mode**, with two production consumers:

```text
A. StateEngine fallback re-infers presence from stale numeric idle
B. BehaviorEngine fallback ignores idle availability entirely
```

This patch fixes ONLY those two fallback consumers.

This is NOT:
- another Phase
- a new R/H series
- a tuning pass
- permission to reopen accepted modules

If this patch passes:

```text
PHASE 13 TECHNICAL = PASS
PRE-MANUAL AUDIT = PASS
BACKEND FUNCTIONAL CONTRACT = FROZEN
NEXT = Manual Experience Acceptance
```

No further pre-Manual source audit.

---

# 1. P0 — StateEngine fallback reconstructs `presence_known` from stale legacy values

## Current production code

`StateEngine.generate_intent()` currently contains logic equivalent to:

```python
presence_known = (
    getattr(state, "idle_available", True)
    or bool(idle != 0 or state.user_working)
)
```

and `evaluate_attention()` only treats presence as unknown when:

```python
idle_available == False and user_idle_seconds == 0
```

This breaks the canonical contract after a temporary WinAPI failure.

Example:

```text
t0:
  valid idle sample = 42s
  idle_available = True

t1:
  GetLastInputInfo temporarily unavailable
  idle_available = False
  CharacterState retains last valid user_idle_seconds = 42
```

Canonical `presence_facts()` correctly says:

```text
known=False
present=False
active=False
```

But `StateEngine` says:

```text
idle != 0
=> presence_known=True
```

and can generate proactive social intent.

Same problem for retained 600s or any other nonzero value.

`user_working=True` must also NOT convert an unavailable idle measurement into known presence. Window/application context and user-presence truth are different facts.

---

## Required fix

For the local fallback path, presence truth must follow the availability bit:

```python
presence_known = bool(getattr(state, "idle_available", False))
```

Do not infer it from:

```text
idle != 0
user_working
window process
window title
```

### `evaluate_attention()`

Use:

```text
idle_available=False
=> AttentionTarget.SELF
```

regardless of whether the retained numeric `user_idle_seconds` is:

```text
0
10
42
300
600
```

The retained numeric value is continuity/debug data only while unavailable.

### `generate_intent()`

When `idle_available=False`:

```text
no proactive user-directed social intent
SELF/survival remains available
```

The user may still receive immediate reactions through explicit user-event paths; this fallback is for autonomous local life.

Do not import a second World model into StateEngine.

---

## Required tests

```text
test_state_fallback_unknown_retained_idle_42_no_social
test_state_fallback_unknown_retained_idle_600_no_social
test_state_fallback_unknown_working_true_no_social
test_attention_unknown_retained_idle_42_is_self
test_attention_unknown_retained_idle_600_is_self
test_state_fallback_valid_present_still_can_socialize
```

Do not only test `idle_available=False + idle=0`.

---

# 2. P0 — BehaviorEngine is the actual no-LifeBrain executor and bypasses the new presence truth

## Production path

When `Scheduler.life_brain is None`, Scheduler does:

```python
self.se.generate_intent(self.se.state)
self.be.step(self.se.state.snapshot())
```

Fixing `StateEngine.generate_intent()` is not sufficient because `BehaviorEngine.step()` independently chooses and submits its own action.

Current `BehaviorEngine.utility_of()` only considers:

```text
utility function
recent-action penalty
user_working interruption cost
memory bias
```

It does NOT consume:

```text
idle_available / presence_known
```

Production App registers fallback behaviors including:

```text
observe_user
talk_to_user
approach_user
```

At startup / sensor failure:

```text
idle_available=False
user_idle_seconds=0 or stale retained value
user_working=False
social_need high
```

`talk_to_user` can outscore SELF behaviors and emit:

```text
BEHAVIOR_STARTED
ACTION_REQUEST(source="behavior", action="talk_to_user")
```

even though the runtime explicitly does not know whether a user is present.

This is a real bypass of the World Truth hotfix.

---

## Required fix

Add one minimal fallback feasibility rule inside `BehaviorEngine`.

Do NOT redesign BehaviorMotivation.

Define the fallback behaviors that require known user presence, matching the actual registered fallback action names:

```text
observe_user
talk_to_user
approach_user
```

If more **existing** fallback actions semantically require the user, include them explicitly, but do not broaden product scope.

### Canonical rule

```text
idle_available=False
=> user-dependent fallback action is infeasible
```

Use the `idle_available` field already present in `CharacterState.snapshot()`.

Do NOT treat:

```text
missing idle_available
```

as known/True. Missing means unknown.

SELF/survival actions remain selectable.

---

# 3. P0 — Guard all three BehaviorEngine lifecycle paths, not only `choose()`

A simple utility penalty in `choose()` is not enough.

There are three ways a fallback user-directed behavior can exist:

## 3.1 New selection

```text
choose()
```

Must not select a user-dependent action when presence unknown.

## 3.2 Existing current behavior

Example:

```text
t0 valid present -> talk_to_user starts
t1 idle sensor becomes unavailable
BehaviorEngine.step()
```

Current implementation can return the current action until its duration/min-stay ends.

For presence-dependent fallback behavior:

```text
idle_available=False
=> do not continue pretending the user is known-present
```

Finalize/interrupt the fallback behavior using the existing BehaviorEngine lifecycle semantics, then allow a SELF/survival action.

Do not create new Activity lifecycle architecture here.

## 3.3 Behavior chain

Production fallback has:

```text
observe_user -> approach_user
```

A chain must re-check fallback feasibility at transition time.

Unknown presence must not produce:

```text
observe_user completed
-> approach_user starts
```

simply because the chain condition sees old/raw fields.

---

# 4. Required BehaviorEngine tests

Behavior tests must capture actual emitted events, not just a helper return value.

Use real:

```text
EventBus
BehaviorEngine
production-equivalent registered fallback behaviors
CharacterState.snapshot()
```

Capture:

```text
BEHAVIOR_STARTED
ACTION_REQUEST
BEHAVIOR_INTERRUPTED / COMPLETED where relevant
```

Required:

```text
test_behavior_fallback_unknown_no_talk_action_request
test_behavior_fallback_unknown_no_observe_user_action_request
test_behavior_fallback_unknown_no_approach_action_request
test_behavior_fallback_unknown_keeps_self_behavior_available
test_behavior_fallback_existing_social_stops_when_presence_becomes_unknown
test_behavior_fallback_unknown_does_not_chain_observe_to_approach
test_behavior_fallback_valid_present_social_still_works
```

Use both:

```text
idle_available=False, retained idle=42
idle_available=False, retained idle=600
```

so the test cannot pass only because the numeric placeholder happens to be zero.

---

# 5. Required full Scheduler fallback integration test

This is the release-gate evidence.

Construct the real fallback topology:

```text
Scheduler
StateEngine
BehaviorEngine
EventBus
life_brain=None
WorldPerception
WindowAwareness fake
Director / event capture as needed
```

Use the production fallback behavior registrations or the exact same definitions.

## Scenario F1 — startup unknown

```text
idle_available=False
user_idle_seconds=0
social_need=90
life_brain=None
multiple medium ticks
```

Assert:

```text
no proactive user-directed ACTION_REQUEST
no talk_to_user
no observe_user
no approach_user
SELF/survival life continues
```

## Scenario F2 — temporary sensor failure with retained active idle

```text
first valid sample idle=42
then idle_available=False while retained idle remains 42
social_need=90
```

Assert:

```text
canonical presence unknown
StateEngine produces no proactive social
BehaviorEngine produces no proactive social ACTION_REQUEST
attention = SELF
```

## Scenario F3 — temporary failure with retained away idle

```text
first valid idle=600
then unavailable while retained 600
```

Same result:

```text
unknown, not measured-away
no proactive social
SELF/survival continues
```

## Scenario F4 — valid present restored

```text
idle_available=True
idle=42
```

Assert fallback social behavior can again become eligible according to existing utility/cooldown rules.

This proves the fix is not a blanket social disable.

---

# 6. Explicit user events remain unchanged

Do NOT route direct user messages / Feed / pet / poke / click / drag through this fallback gate.

Those already have:

```text
presence_known=True
user_present=True
source=explicit_user_event
```

for their immediate snapshot.

This patch only governs **autonomous local fallback decisions**.

---

# 7. Freeze all accepted `e5ce9fb` changes

Do NOT modify except mechanical compatibility:

```text
WorldPerception.presence_facts
WorldPerception.to_dict
World event semantics
USER_RETURNED route
LifeBrain structured world
LifeBrain main-model snapshot
Motivation feasibility
social bid / Ignore
DialogueContextSnapshot
DialogueBrain FIFO/history
direct/feed/interaction explicit-event snapshots
Embodiment / Frame presence
Director
Activity lifecycle
Emotion
Relationship
Needs constants
Memory
Agent
Spatial
Harness
Persona
assets / renderer
```

Do not tune fallback utilities to hide the issue.
Fix feasibility truth, not scores.

---

# 8. Test-quality rules

Invalid evidence:

- source-string assertions only
- only testing `StateEngine.generate_intent`
- only testing `idle_available=False + idle=0`
- never invoking `BehaviorEngine.step`
- never capturing emitted `ACTION_REQUEST`
- testing BehaviorEngine helper while bypassing Scheduler fallback
- changing social utility constants until SELF wins

Required evidence is behavioral and production-path based.

---

# 9. Report

Create:

```text
docs/FURINA_PHASE13_PRE_MANUAL_FINAL_FALLBACK_PRESENCE_REPORT.md
```

Order:

1. retained-idle StateEngine reproduction
2. BehaviorEngine bypass reproduction
3. root cause
4. minimal fixes
5. F1–F4 Scheduler integration evidence
6. full regression
7. STOP

Allowed Agent verdict:

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

---

# 10. STOP / release gate

After this patch:

```text
push one coherent commit
send SHA + report + full regression result
STOP
```

Reviewer will check ONLY:

```text
A. StateEngine cannot reconstruct known presence from stale retained idle
B. BehaviorEngine no-LifeBrain fallback cannot bypass presence truth
C. valid present restores existing fallback behavior
```

If all three pass:

```text
PHASE 13 TECHNICAL = PASS
PRE-MANUAL AUDIT = PASS
BACKEND FUNCTIONAL CONTRACT = FROZEN
```

Then immediately:

```text
Manual Experience Acceptance
```

No more source-audit round before Manual.
