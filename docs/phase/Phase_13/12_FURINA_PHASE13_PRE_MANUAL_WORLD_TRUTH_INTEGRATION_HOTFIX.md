# Furina Desktop AI — Phase 13 Pre-Manual World Truth Integration Hotfix

**Review baseline:** `32bc11be795484e82449dc776624a29eac49dd1f`

## 0. Reviewer status

A final full backend-functional audit has been completed before Manual.

Coverage included:

```text
Runtime / owner-thread contract
State / Needs / Emotion ownership
Relationship units / causal writes
World / WindowAwareness / idle truth
Motivation / feasibility / LifeBrain
Director / Activity lifecycle / Outcome
Interaction exactly-once / takeover / Ignore
Dialogue FIFO / history / frozen snapshots / Validator
Memory store / recall / restart / exactly-once
Agent planner / permission / verify / lifecycle / reporting
Spatial technical path semantics
Harness truth / failure/fallback diagnostics
App production wiring / fallback paths / cross-module integration
```

No second independent blocker was found.

The **only remaining technical blocker is one integration cluster**:

```text
WorldPerception truth
    ↓
CharacterState / LifeBrain / Motivation / Dialogue / Embodiment / social semantics
```

The World layer itself now distinguishes:

```text
idle_available = False
user_activity = UNKNOWN
user_active = False
interaction_availability = 0
```

when OS idle truth is unavailable.

But several downstream consumers still reconstruct user presence from the legacy numeric placeholder:

```python
user_idle_seconds = 0.0
```

or fail to receive the structured World snapshot at all.

This patch closes the entire cluster.

This is NOT:
- a new Phase
- a new R/H closeout series
- a Persona redesign
- a tuning pass

After this patch passes review:

```text
PHASE 13 TECHNICAL = PASS
BACKEND FUNCTIONAL CONTRACT = FROZEN
NEXT = Manual Experience Acceptance
```

No more pre-Manual static optimization rounds.

---

# 1. P0 — LifeBrain is not actually receiving the structured World snapshot

## Current production mismatch

Scheduler attaches:

```python
state.world = self.world_perc
```

where `self.world_perc` is a `WorldPerception`.

But `LifeBrain.build_snapshot()` currently does:

```python
wp = getattr(state, "world", None)
if wp is not None and hasattr(wp, "to_dict"):
    snapshot["world"] = wp.to_dict()
```

`to_dict()` currently exists on `WorldState`, not on `WorldPerception`.

Therefore the LifeBrain snapshot can silently omit:

```text
world.user_activity
world.focus_level
world.interaction_availability
world.interruption_cost
world.foreground_app
world.recent_events
world.idle_available
```

even though Motivation is consuming `WorldPerception.factors()` correctly.

This creates split truth:

```text
Motivation sees structured World
LifeBrain prompt may not
```

That is unacceptable before Persona/Life Manual acceptance.

## Required fix

Create one canonical World snapshot interface.

Preferred minimal implementation:

```python
class WorldPerception:
    def to_dict(self) -> dict:
        return self.state.to_dict()
```

or an equivalent explicit `snapshot()` method.

Then all downstream consumers use that canonical interface.

Do not attach `WorldState` in one place and `WorldPerception` in another ad hoc.

## Required test

Production-equivalent:

```text
Scheduler medium sample
-> WorldPerception = CODING
-> state.world = WorldPerception
-> LifeBrain.build_snapshot(state)
```

Assert:

```text
snapshot["world"]["user_activity"] == "coding"
snapshot["world"]["idle_available"] is True
snapshot["world"]["foreground_app"] reflects process
```

Tests:

```text
test_lifebrain_receives_structured_world_from_production_state
test_worldperception_to_dict_matches_worldstate_truth
test_lifebrain_world_not_silently_omitted
```

---

# 2. P0 — Define one authoritative user-presence truth boundary

The root error across the remaining consumers is:

```text
idle_seconds numeric placeholder
is being treated as
presence truth
```

This must stop.

## Required canonical representation

Create one small deterministic helper/API, for example:

```python
PresenceFacts(
    known: bool,
    present: bool,
    active: bool,
    idle_seconds: Optional[float],
)
```

or an equivalent immutable dict/helper.

Its source priority:

### A. Valid OS World truth

If:

```text
WorldState.idle_available == True
```

then:

```text
known = True
present = WorldState.user_present
active = WorldState.user_active
idle_seconds = WorldState.user_idle_seconds
```

### B. Explicit current user event

A real current:

```text
direct user message
feed command
click
petting
poke
drag
```

is itself hard evidence that the user is present **for that interaction snapshot**.

Therefore even if OS idle is unavailable:

```text
known = True
present = True
active = True
source = explicit_user_event   # optional diagnostic
```

Do NOT fabricate or permanently overwrite OS idle seconds from this.

### C. No valid OS sample and no explicit current user event

Then:

```text
known = False
present = False
active = False
idle_seconds = None
```

Important:

```text
known=False + present=False
```

means "unknown / do not proactively assume user availability",
not "we measured the user as away".

For expression/dialogue semantics:

```text
user_present = False
solitude = False
presence_known = False
```

so unknown does not become either:
- "the user is definitely here"
- "Furina is definitely alone"

---

# 3. P0 — LifeBrain legacy raw-idle inference must be removed

Current `LifeBrain.build_snapshot()` still does:

```python
"user": {
    "active": bool(state.user_working or state.user_idle_seconds < 300),
    "idle_seconds": int(state.user_idle_seconds),
}
```

When:

```text
idle_available=False
user_idle_seconds=0.0 placeholder
```

this reports:

```text
active=True
```

which contradicts World truth.

## Required fix

LifeBrain must consume the canonical PresenceFacts / structured World.

Snapshot must expose enough truth to the model:

```text
user.presence_known
user.present
user.active
user.idle_available
user.idle_seconds = measured value OR null
user.working
```

Do not hide unknown by substituting zero.

### Character appraisal

Current LifeBrain also effectively defaults missing `state.user_present` to `True`.

`CharacterState` does not own that authoritative fact.

CharacterAppraisal must receive canonical World/presence truth.

Do not use:

```python
getattr(state, "user_present", True)
```

as a presence source.

Tests:

```text
test_lifebrain_idle_unavailable_not_active
test_lifebrain_idle_unavailable_presence_unknown
test_lifebrain_valid_idle_42s_present_truth
test_lifebrain_away_idle_present_false
test_character_appraisal_uses_world_presence_not_default_true
```

---

# 4. P0 — `interaction_opportunity()` must not treat unknown as an available user

Current LifeBrain interaction opportunity reads:

```python
idle = state.user_idle_seconds

if not state.user_working:
    score += 18
...
```

So on startup/API failure:

```text
idle_available=False
user_working=False
user_idle_seconds=0
```

the system can increase the opportunity to proactively interact.

That is the opposite of the World contract:

> 宁可 unknown，不要假装知道。

## Required fix

At the start of `interaction_opportunity()`:

```text
if user presence is unknown:
    proactive interaction opportunity = 0
```

unless the current call is explicitly grounded in a user-initiated event.

This is not diversity tuning. It is feasibility truth.

A direct user message/pet/feed can still have immediate reaction Dialogue because the event itself proves presence.

Tests:

```text
test_interaction_opportunity_zero_when_presence_unknown
test_interaction_opportunity_uses_valid_world_idle
test_explicit_user_event_can_react_when_os_idle_unknown
```

---

# 5. P0 — Motivation feasibility must understand `idle_available / presence_known`

Motivation already reads:

```python
state.world.factors()
```

so its World connection is real.

But `WorldPerception.factors()` currently exposes a conservative `user_present=True` even in the pre-first-valid-idle UNKNOWN branch.

`_feasible()` can therefore still allow proactive user-directed candidates even when the runtime has no evidence that the user is available.

## Required fix

Add to canonical world factors:

```text
idle_available
presence_known
```

Example:

```python
{
    ...
    "idle_available": 0.0/1.0,
    "presence_known": 0.0/1.0,
}
```

Then feasibility contract:

```text
presence unknown:
    SELF / survival behavior = feasible
    proactive user-directed behavior requiring the user = infeasible

explicit current user event:
    reaction behavior may be feasible via explicit context override
```

At minimum gate:

```text
talk
greet
approach_user
observe_user
watch_user
seek_attention
ask_user
comment
invite_user
comfort
offer_help / assist_user when user-dependent
```

according to the existing `_NEEDS_USER` semantics.

Do NOT turn unknown into AWAY.
Use a reason such as:

```text
user_presence_unknown
world_idle_unavailable
```

Tests:

```text
test_unknown_presence_filters_user_directed_candidates
test_unknown_presence_keeps_self_candidates
test_valid_present_world_restores_social_feasibility
test_valid_away_world_filters_social
test_user_event_context_can_override_presence_for_immediate_reaction
```

---

# 6. P0 — Return emotion must consume World event truth, not reconstruct it from raw idle

Scheduler still has a legacy branch equivalent to:

```python
idle = state.user_idle_seconds
was_idle = self._was_user_absent

if idle < 300 and was_idle:
    EVENT_RETURN

self._was_user_absent = idle >= 300
```

This duplicates World semantics and ignores `idle_available`.

WorldPerception already emits a fresh, exactly-once:

```text
USER_RETURNED
```

event.

## Required fix

Delete/deactivate the raw-idle return detector.

Route:

```text
WorldPerception.last_events contains USER_RETURNED
-> Emotion EVENT_RETURN exactly once
```

Use the same fresh-event-instance consumption boundary already used for WORK_STARTED / WORK_ENDED.

Do not infer return from placeholder numeric state.

Tests:

```text
test_idle_unavailable_never_emits_return_emotion
test_world_user_returned_emits_return_emotion_once
test_historical_user_returned_does_not_retrigger
test_second_real_return_transition_emits_second_return
```

---

# 7. P0 — Social bid / Ignore must require known visible user presence

`begin_social_bid()` currently gates only:

```python
if state.user_idle_seconds >= 300:
    return
```

If OS idle truth is unavailable:

```text
idle_available=False
user_idle_seconds=0
```

a social bid can still start.

Sixty seconds later this can become:

```text
USER_IGNORE
```

despite never knowing that a user was present.

## Required fix

`begin_social_bid()` must require canonical:

```text
presence_known == True
present == True
```

unless the social bid was triggered directly by a current explicit user interaction, in which case presence is known for that event.

For autonomous Life social speech:

```text
unknown presence -> no pending social bid
```

Tests:

```text
test_unknown_presence_autonomous_speech_creates_no_bid
test_unknown_presence_never_creates_fake_ignore
test_valid_present_social_speech_creates_one_bid
test_valid_away_social_speech_creates_no_bid
```

---

# 8. P0 — Autonomous Dialogue / Embodiment / Frame must stop rebuilding presence from raw idle

The Scheduler still contains several patterns like:

```python
solitude = state.user_idle_seconds > 300
user_present = state.user_idle_seconds < 300
```

in:

- autonomous `DialogueContextSnapshot`
- expression appraisal
- embodiment request/context
- runtime frame dialogue/persona metadata

This means:

```text
idle unavailable + placeholder 0
```

can propagate as:

```text
user_present=True
solitude=False
```

even while World says UNKNOWN.

## Required fix

Every non-user-initiated consumer must use the same canonical PresenceFacts.

When unknown:

```text
presence_known=False
user_present=False
solitude=False
```

When measured present:

```text
presence_known=True
user_present=True
solitude=False
```

When measured away:

```text
presence_known=True
user_present=False
solitude=True
```

If `DialogueContextSnapshot` lacks `presence_known`, add it as a backward-compatible field/default.

Do not create a second presence system inside Dialogue or Embodiment.

Tests:

```text
test_autonomous_dialogue_unknown_presence_not_fake_present
test_autonomous_dialogue_known_away_is_solitude
test_embodiment_unknown_presence_not_fake_present
test_runtime_frame_unknown_presence_not_fake_present
test_presence_semantics_identical_across_dialogue_and_body
```

---

# 9. P1 — User-initiated Dialogue / Feed / Interaction should use explicit event evidence

Direct user text currently derives:

```text
user_present / solitude
```

from raw idle even though the fact that a user just submitted text is stronger evidence than OS idle.

For:

```text
submit_user_message
submit_feed
click / pet / poke / drag
```

freeze snapshots with:

```text
presence_known=True
user_present=True
solitude=False
```

for that immediate event.

Do not mutate the persistent World state solely because of the event.

This prevents a broken/unavailable idle API from making a real current user interaction look absent or unknown.

Tests:

```text
test_direct_message_is_explicit_presence_evidence
test_feed_is_explicit_presence_evidence
test_petting_is_explicit_presence_evidence
test_explicit_event_does_not_fabricate_os_idle_measurement
```

---

# 10. P1 — Local fallback path must obey the same unknown-presence contract

`BehaviorEngine.step()` is correctly production fallback-only when LifeBrain is unavailable. Keep that architecture.

But `StateEngine.generate_intent()` / attention helpers still reason from the numeric idle placeholder.

Fallback mode must not become a loophole where an unavailable LLM + unavailable idle sensor causes proactive social behavior.

## Required fix

For fallback intent/attention:

```text
idle_available=False
-> do not use user_idle_seconds as measured presence
-> no proactive user-directed social intent purely from social_need
-> self/survival behaviors remain available
```

Do not redesign StateEngine or BehaviorEngine.

Tests:

```text
test_local_fallback_unknown_presence_no_proactive_social
test_local_fallback_unknown_presence_self_life_continues
test_local_fallback_valid_present_can_socialize
```

---

# 11. Required cross-module integration proof

This is the important part. Do not prove only helpers.

## Scenario A — startup / idle API unavailable

Production-equivalent runtime:

```text
CharacterState idle_available=False
WindowAwareness has no valid idle
WorldPerception.update(... idle_available=False)
```

Assert across all consumers:

```text
World.user_activity == UNKNOWN
World.user_active == False
LifeBrain snapshot user.presence_known == False
LifeBrain snapshot user.active == False
structured world exists in Life snapshot
interaction_opportunity == 0
Motivation filters proactive user-directed activities
no autonomous social bid
no USER_IGNORE
no EVENT_RETURN
Dialogue autonomous snapshot does not claim present/alone
Body/Frame does not claim present
SELF activity remains feasible
```

## Scenario B — valid present sample

```text
idle=42s
idle_available=True
foreground process=code.exe
```

Assert:

```text
presence_known=True
present=True
structured World enters LifeBrain
coding/work truth consistent
social feasibility follows current availability/focus rules
```

## Scenario C — valid away sample

```text
idle=600s
idle_available=True
```

Assert:

```text
presence_known=True
present=False
autonomous social candidates infeasible
solitude=True
no social bid
```

## Scenario D — OS idle unavailable but user explicitly talks

```text
idle_available=False
submit_user_message("在吗")
```

Assert for this turn:

```text
presence_known=True
user_present=True
solitude=False
```

while persistent World still truthfully says:

```text
idle_available=False
```

and no fake OS idle measurement is written.

## Scenario E — real return

```text
valid away
-> valid active
-> WorldEvent.USER_RETURNED
```

Assert:

```text
EVENT_RETURN exactly once
```

No raw-idle duplicate detector.

---

# 12. Regression scope / freeze

All prior Phase 13 contracts remain frozen.

Do NOT reopen:

```text
Director priority
Activity lifecycle
Outcome tuning
Emotion model tuning
Relationship scale
Needs time constants
Dialogue FIFO/history
Validator
Memory architecture
Agent verify/permission/tools
Spatial
Harness badge architecture
anti-collapse / diversity
Persona
assets / renderer
```

Only mechanical compatibility changes needed for canonical PresenceFacts are allowed.

Run the full existing regression suite plus new integration tests.

Do not lead the report with test count.

---

# 13. Report

Create:

```text
docs/FURINA_PHASE13_PRE_MANUAL_WORLD_TRUTH_INTEGRATION_REPORT.md
```

Order:

1. root defect reproduced
2. all legacy raw-idle consumer paths found
3. canonical presence/world boundary
4. production fixes
5. cross-module scenarios A–E
6. regression
7. STOP

Allowed Agent verdict:

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

Do not claim Manual PASS.

---

# 14. Forbidden

Do NOT:

- start Phase 14
- modify assets / renderer / animation
- redesign Persona
- tune Persona prompts
- add line banks
- tune Needs
- tune Relationship
- re-enable anti-collapse
- add diversity forcing
- redesign Director
- redesign Activity lifecycle
- expand Agent tools
- add a new LLM
- add a new DB
- use random social suppression as a workaround
- treat UNKNOWN as AWAY
- treat placeholder idle=0 as ACTIVE
- create a second World/presence model

---

# 15. Final release gate

After this patch:

```text
push one coherent commit/series
send:
- commit SHA
- report
- exact full regression result
STOP
```

Reviewer will check only this World Truth integration cluster.

If it passes:

```text
PHASE 13 TECHNICAL = PASS
BACKEND FUNCTIONAL CONTRACT = FROZEN
PRE-MANUAL AUDIT = PASS
```

Then immediately enter:

```text
Manual Experience Acceptance
```

Manual will be split into:

```text
A. Reviewer-executable simulated/audit-environment tests
B. User-required Windows / real-API / subjective experience tests
```

Only after Manual:

```text
FUNCTIONAL DIGITAL LIFE = PASS
Phase 14 — Frontend Rendering / Asset Integration
```
