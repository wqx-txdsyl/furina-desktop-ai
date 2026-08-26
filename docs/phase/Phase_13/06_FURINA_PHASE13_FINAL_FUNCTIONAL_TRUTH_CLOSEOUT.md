# Furina Desktop AI — Phase 13 FINAL Functional Truth Closeout

**Status entering this task:** `FUNCTIONAL DIGITAL LIFE = FAIL / NEXT PHASE BLOCKED`

**Reviewer baseline:** GitHub commit `2d0da7fb7a34e938f2a064807b8a1f62bec22d2e`  
**Regression baseline:** synchronized C-R2 + hotfix run previously reached **452 PASS / 0 FAIL**.  
Passing tests are a regression baseline only; they are **not** evidence that the digital-life experience is correct.

This is the **final backend/runtime truth closeout before Manual Experience Acceptance**.

If this task passes reviewer verification, **do not start another backend optimization phase**.  
The next gate is **Manual Experience Acceptance**.  
Only after Manual passes may the project enter **Phase 14 — Frontend Rendering / Asset Integration**.

---

# 0. Non-negotiable product contract

The product is:

> **Life → Character → Relationship → Interaction → Assistance**

Not “Agent + Furina skin”.

Three LLM brains only:

- `LifeBrain` = what I want to do
- `DialogueBrain` = how I say it
- `Agent` = computer operation

Everything else is deterministic.

Core rules:

1. **World is fact.**
2. **EmotionEngine owns emotional truth.**
3. **RelationshipEngine owns relationship truth.**
4. **LifeBrain selects behavior; it does not fabricate emotion.**
5. **Activity Outcome may change internal state only after a real activity lifecycle event.**
6. **User interaction causality must be exactly once.**
7. **Agent may report success only after verification.**
8. **anti-collapse / forced diversity = OFF.**
9. **Harness is an oscilloscope, never a simulator and never a fake-green dashboard.**
10. **No frontend/assets work until this closeout + Manual are passed.**

---

# 1. Scope / forbidden changes

## Allowed

Only fixes required by the verified findings below.

## Forbidden

- Phase 14
- asset generation/redraw
- animation polish unrelated to spatial truth
- new LLM
- new database
- second Relationship/Emotion/World system
- catchphrase banks
- hardcoded “Furina responses”
- arbitrary parameter tuning to make test distributions look diverse
- forced activity rotation
- hiding failures in fallback
- claiming Persona PASS from automated tests

---

# 2. P0 — World Truth

## Verified failures

### 2.1 Clock is wrong

Current production Scheduler calls:

```python
self.se.update_clock(*time.localtime()[:2])
```

`time.localtime()[:2]` is `(year, month)`, not `(hour, minute)`.

Result: `clock_hour ≈ 2026`, poisoning night/day, sleep/rest and World semantics.

### 2.2 `user_idle_seconds` is not sourced from Windows input truth

No production `GetLastInputInfo` path was found.

### 2.3 `user_working` is effectively self-fed

`StateEngine.update_needs(..., self.se.state.user_working, ...)` receives the previous state value instead of a current World fact.

### 2.4 foreground `app` is a window class, not process executable

`WindowAwareness` uses `GetClassNameW`.

The World classifier then substring-matches app text. Because the rules contain very short tokens such as `"et"`, class names such as `Chrome_WidgetWin_1` can be falsely classified as office/working.

### 2.5 stability threshold is declared but not enforced

`_STABLE_ACTIVITY_MIN` exists, but activity/app transition events are emitted immediately except for debounce.

## Required fix

Create one truthful Windows perception boundary.

On Windows, obtain:

- foreground HWND
- title
- window class as a separate field
- real process executable/process name
- window rect
- real input idle time via `GetLastInputInfo`

Do not pretend to know typing if no typing signal exists. Use explicit `False/unknown` semantics rather than a stale undeclared `_last_typing`.

`WorldPerception` must be the source of:

- user_present
- user_active
- user_activity
- user_working
- focus
- availability
- interruption_cost
- day_period

Scheduler must pass actual local:

```text
hour = tm_hour
minute = tm_min
```

Apply stability semantics to activity transitions.

## Mandatory tests

```text
test_scheduler_clock_uses_hour_minute
test_world_day_period_known_times
test_windows_idle_signal_is_runtime_truth
test_foreground_process_separate_from_window_class
test_chrome_widget_class_not_false_office_match
test_state_user_working_comes_from_world
test_world_activity_transition_requires_stability
test_world_unknown_does_not_fake_typing
```

---

# 3. P0 — Needs must use human-scale real time

## Verified failure

Production `StateEngine.update_needs()` was simulated with real seconds.

Observed examples from a neutral/default state:

```text
working ~120 s:
fatigue ≈ 86
boredom ≈ 100

working ~180 s:
fatigue ≈ 100

idle/nonworking 600 s:
hunger ≈ 86
fatigue ≈ 56
sleepiness ≈ 52

~1800 s:
hunger/fatigue/sleepiness can all reach 100
```

This makes “living together for hours” behave like a time-lapse simulation.

## Required fix

Treat all passive need rates as explicit **per-minute / per-hour product time constants**, not magic per-second drift.

Do not merely divide every number until tests pass.

Document expected timescale.

Minimum acceptance:

- from a neutral healthy baseline, passive physiology must not saturate in a few minutes;
- at 30 minutes of ordinary use, no physiological need may reach emergency/saturation solely from passive drift;
- fatigue may become meaningfully high after sustained multi-hour work, not 2–3 minutes;
- hunger should evolve over hours;
- sleepiness should be strongly compatible with circadian/world time, not reach crisis after a short session;
- boredom/social/curiosity may motivate actions earlier, but must not mechanically hit 100 every few minutes.

Produce simulated curves for:

```text
30 min
2 h
4 h
8 h
```

for both working and nonworking contexts.

## Mandatory tests

```text
test_needs_no_minutes_scale_saturation
test_needs_30min_normal_session_sane
test_needs_2h_working_curve_sane
test_needs_4h_curve_sane
test_needs_dt_invariance
```

`dt_invariance`: 600 × 1s and 200 × 3s should be approximately equivalent.

---

# 4. P0 — Emotion Semantic Truth

This is one of the largest remaining blockers.

## Verified failures

### 4.1 baseline label is wrong

Default `EmotionState` can derive to `sleepy`, because `_sleepiness()` is approximated from:

```text
high calm + low excitement
```

This confuses “calm” with “sleepy”.

### 4.2 events barely control visible emotion

Production-class probes from default state showed many events still deriving to calm/sleepy:

```text
praise -> calm
reject -> sleepy
ignore -> sleepy
agent_done -> sleepy
pet/feed/talk/etc -> mostly calm
```

Absolute baseline dimensions dominate the event.

### 4.3 event effects decay far too quickly

Praise/reject deltas were almost fully erased on ~minute scale.

### 4.4 existing semantic Emotion events are not fully wired

The module defines:

```text
EVENT_PRAISE
EVENT_REJECT
EVENT_TALK
EVENT_IGNORE
EVENT_RETURN
EVENT_AGENT_DONE
EVENT_FEED
...
```

but many production routes do not emit them.

### 4.5 LifeDecision can overwrite emotional truth

`app._on_execute()` writes:

```text
LifeDecision.payload["emotion"] -> CharacterState.emotion.label
```

A real rejection can create embarrassment/sadness, then a later `read + calm` decision can erase it.

This violates ownership.

## Required fix

### One owner

`EmotionEngine` is the only owner of:

- emotional dimensions
- derived emotion label
- mood / valence / arousal

`LifeDecision.emotion` must **not** write `EmotionState.label`.

If the field is retained for schema compatibility, treat it as a non-authoritative expression/behavior hint only, or deprecate it.

### Derivation

Design label derivation around baseline-relative salience / meaningful dominance / hysteresis, not just absolute raw maxima.

Mandatory semantic expectations:

```text
default healthy baseline -> calm

high-confidence praise
-> proud or happy (not calm merely because calm baseline is high)

clear rejection
-> embarrassed/sad/guarded-compatible emotional truth

repeated poke / sufficiently strong poke
-> annoyed-compatible truth

user return after loneliness
-> happy/excited-compatible truth
```

Do not hardcode each event directly to one label; dimensions remain real.

### Decay

Use explicit emotion time constants.

Ordinary meaningful events should remain behaviorally relevant for minutes, not disappear almost entirely in ~60s.

### Wire semantic events exactly once

At minimum:

```text
pet
poke
click
drag-finalized
feed
praise
reject
talk
ignore
user return
work start/end
agent success
```

No unknown interaction may default to `EVENT_CLICK`.

## Mandatory tests

```text
test_default_emotion_is_calm
test_praise_changes_derived_emotion
test_reject_changes_derived_emotion
test_poke_can_create_annoyed_state
test_emotion_not_erased_by_life_decision
test_lifebrain_does_not_write_emotion_truth
test_emotion_event_routes_exactly_once
test_unknown_input_does_not_become_click
test_emotion_decay_is_minutes_scale
```

---

# 5. P0 — Forced diversity must actually be OFF

## Passed

`LifeBrain.decide()` no longer calls `_apply_variety()`.

Do not regress this.

## Verified remaining failure

`BehaviorMotivation` still contains production diversity mechanisms:

```text
_category_penalty
_activity_penalty
_observation_crush_guard
recent-done multiplier
```

Examples:

- observation >50% of recent history -> observation ×0.4, other category ×1.4
- repeated same category/activity receives heavy multiplicative penalties
- same unchanged state can change ranking solely because recent activity history changed

Real probe showed unchanged state + repeated history could crush `read` from a meaningful candidate to almost zero.

Scheduler also has an `idle_streak` / `autonomy_stagnation` wakeup path that can trigger a rethink merely because idle lasted a short period.

This is still artificial diversity.

## Required fix

Production activity ranking may change due:

```text
Needs
Emotion
Personality
Identity
Relationship
World
Memory
Feasibility
real activity outcome
real cooldown/physical feasibility
```

It must **not** change merely because:

> “we have already shown this category enough times”.

Remove/disable all diversity-only multipliers from production scoring.

Explicit semantic cooldown is allowed only when it represents the activity itself, not visual variety.

Do not wake LifeBrain after ~18 seconds merely because the character is idle.

Quiet coexistence is valid.

## Mandatory tests

```text
test_unchanged_state_history_alone_does_not_force_category_switch
test_repeated_read_can_remain_top_candidate
test_observation_ratio_does_not_boost_unrelated_categories
test_no_autonomy_stagnation_interrupt_for_quiet_idle
test_forced_diversity_production_calls_zero
```

---

# 6. P0 — Activity lifecycle and Outcome truth

## Verified failures

### 6.1 replacement is treated as completion

When new activity differs from previous activity:

```python
_apply_activity_outcome(prev)
```

is called with default `success=True`.

Planned duration / actual elapsed time / exit condition are not used to prove completion.

### 6.2 relationship can be self-farmed

Activity outcomes directly increase raw relationship fields for actions such as:

```text
approach_user
talk
comfort
offer_help
assist_user
```

The character can therefore become more trusted/familiar simply because **it chose** to approach/talk/help, even with no user response or verified help result.

### 6.3 social_need can be applied twice

`approach_user` currently has social need change in both:

```text
Outcome.needs["social_need"]
and
Outcome.social_need
```

Real probe from social_need=60 produced a much larger double reduction.

### 6.4 shared global Outcome is mutated

`outcome_for(activity, success)` mutates the shared object stored in global `OUTCOMES`.

A call with success=False can mutate the same object another call holds.

## Required fix

Introduce explicit activity lifecycle result, minimum:

```text
COMPLETED
INTERRUPTED
FAILED
ABORTED
```

Track:

```text
activity instance id
started_at
planned_duration
elapsed
exit condition
finish reason
```

A LifeBrain replacement is **not automatically COMPLETED**.

Outcome scale must reflect actual progress / completion semantics.

Make Outcome specifications immutable or return fresh copies.

Relationship updates must be removed from generic Activity Outcome.

Relationship changes only through `RelationshipEngine` from real relationship evidence:

- user response
- accepted/rejected interaction
- verified Agent help success where semantically appropriate
- explicit meaningful interaction

Do not award trust because Furina merely offered help.

Make social need adjustment exactly once.

## Mandatory tests

```text
test_activity_replacement_is_not_automatic_completion
test_interrupted_activity_not_full_reward
test_activity_completion_exactly_once
test_activity_instance_has_finish_reason
test_outcome_spec_not_shared_mutable
test_social_need_not_double_applied
test_autonomous_social_activity_cannot_self_farm_relationship
test_verified_help_can_emit_relationship_event_once
```

---

# 7. P0 — Real input semantics exactly once

## Verified failure

A real pointer sequence currently behaves approximately:

```text
mouse down -> GRAB
mouse release -> CLICK / DRAG / POKE / LONG_PRESS
```

But all `INTERACTION_INPUT` events are consumed by Scheduler as meaningful positive user interaction:

- social_need decreases
- tolerance increases
- episode consolidation can happen
- life interrupt occurs

App emotion mapping also defaults unknown kinds to `EVENT_CLICK`.

Therefore one real click/drag can create multiple causal effects.

Harness direct semantic buttons do not reproduce this duplication.

## Required fix

Separate **pointer control phases** from **meaningful semantic interaction**.

`GRAB`, raw `RELEASE`, `HOVER`, pointer `LEAVE` must not automatically count as:

```text
user responded positively
social need satisfied
relationship event
emotion click
memory episode
```

Only finalized semantic interactions may enter life causality:

```text
CLICK
PETTING
POKE
DRAG (final semantic)
...
```

### Ignore is not pointer leave

Create/reuse one semantic `USER_IGNORE` route.

Harness “Ignore” must invoke this route.

Real ignore should correspond to “Furina initiated and user did not respond within the defined response window”, not cursor leaving the sprite.

Route to existing:

```text
Emotion EVENT_IGNORE
Relationship EV_IGNORE
Life tolerance / future social tendency
Memory if sufficiently meaningful
```

exactly once.

## Mandatory tests

```text
test_real_click_has_one_semantic_causal_event
test_real_drag_has_one_semantic_causal_event
test_grab_does_not_change_social_need
test_hover_leave_do_not_count_as_positive_response
test_unknown_interaction_not_mapped_to_click
test_ignore_is_not_pointer_leave
test_semantic_ignore_affects_emotion_relationship_once
```

---

# 8. P0 — Runtime thread ownership + dialogue ordering

## Verified failures

`EventBus` is synchronous.

User dialogue and Agent tasks run in background threads.

Therefore:

```text
worker thread emits BRAIN_SPOKE / AGENT_COMPLETED
-> Scheduler callback executes immediately in worker thread
-> runtime state is mutated from worker thread
```

There is no single domain apply thread.

### Dialogue race reproduced

Two rapid messages with first response slower than second produced history:

```text
user1
user2
furina_reply2
furina_reply1
```

Prompt2 saw user1 before reply1 existed.

This destroys conversational chronology.

## Required fix

Do not add another Brain.

Add a small runtime coordination boundary.

### Dialogue

All stateful `DialogueBrain.say()` calls that touch `_history` must be serialized.

Recommended:

```text
single FIFO Dialogue executor / queue
```

User messages preserve input order.

Autonomous/Feed/Agent speech must not corrupt direct-user turn history.

Qt must remain nonblocking.

### Runtime state application

Background workers may perform slow I/O/LLM/tool work.

Final domain mutations and event application must be marshalled to one runtime apply thread / Qt-main-safe queue.

Do not let synchronous EventBus callbacks mutate shared runtime state from arbitrary worker threads.

## Mandatory tests

```text
test_two_fast_user_messages_preserve_reply_order
test_dialogue_history_is_chronological_under_concurrency
test_dialogue_calls_do_not_mutate_history_concurrently
test_worker_event_does_not_apply_runtime_state_on_worker_thread
test_agent_completion_marshaled_to_runtime_apply_thread
test_brain_spoke_marshaled_to_runtime_apply_thread
test_qt_remains_responsive_during_slow_dialogue
```

---

# 9. P0 — Dialogue validator must be an enforcement layer

## Verified failure

Validator correctly identifies invalid output such as:

```text
stage_direction
too_long
example_copy
overuse_god_catchphrase
over_exclamation
```

But `DialogueBrain` only hard-rejects `generic_assistant_voice`.

Other `valid=False` responses can still be returned unchanged.

## Required fix

If `ValidationResult.valid == False`, original invalid speech must never be shown unchanged.

No new judge model.

Allowed policy:

1. one same-DialogueBrain regeneration with deterministic validation feedback;
2. revalidate;
3. if still invalid, expose observable Dialogue failure / system-status path rather than leaking invalid character output.

For user direct messages, do not silently enter permanent silence.

Also fix act precedence:

```text
"你能别烦我吗？"
```

must route to `DECLINE`, not `RESPONSE_TO_QUESTION`.

Boundary/rejection semantics outrank punctuation-based question detection.

## Mandatory tests

```text
test_stage_direction_invalid_not_returned
test_too_long_invalid_not_returned
test_catchphrase_overuse_invalid_not_returned
test_over_exclamation_invalid_not_returned
test_example_copy_invalid_not_returned
test_direct_user_invalid_output_has_bounded_recovery
test_rejection_question_routes_decline
```

---

# 10. P0 — Agent truthfulness

## Verified failures

### 10.1 calculator maps to notepad

Planner `_guess_app()` lacks calculator mapping.

### 10.2 `verified=False` can still complete

Production probe:

```text
ToolResult(ok=True)
_verify(...) = False
```

still produced:

```text
status=completed
AGENT_COMPLETED
```

### 10.3 task context leaks across tasks

`AgentRuntime.context` is persistent and `extra_context` is merged.

Task A's path/vars can remain in Task B.

### 10.4 app launch is not really verified

`subprocess.Popen()` success immediately returns:

```text
verified=True
```

without proving the process/window appeared.

### 10.5 Agent body bypasses Director

`App._on_agent_body()` directly writes CharacterState instead of submitting Agent ownership through Director.

### 10.6 completion report loses verified facts

`AGENT_COMPLETED` emits goal/results, but Scheduler reads:

```text
payload["summary"]
```

which is absent, so it often falls back to “完成啦。”

### 10.7 permission classification is dishonest

`app.launch` is classified `L0_READ` even though launching an application is a side-effecting computer action.

## Required fix

### Planner

Correct app resolution:

```text
计算器 / calculator / calc -> calc
记事本 -> notepad
...
```

Unknown app must fail/clarify, not default to notepad.

### Per-task context

Each `execute()` receives a fresh task context.

Persistent runtime context may contain only explicitly safe global settings, never arbitrary previous request args.

### Verification

Completion condition:

```text
every required step:
res.ok == True
AND tool/runtime verification == True
```

If verification fails:

```text
UNVERIFIED / FAILED
```

No `AGENT_COMPLETED`.

`app.launch` must verify observable process/window presence within a bounded timeout on Windows.

### Director

Agent body/action ownership enters Director as `source=agent`, `P_AGENT_TASK`.

No direct life/activity overwrite from Agent callback.

### Report fact

Build structured factual completion summary from **verified** result.

DialogueBrain may character-style that fact, but may not invent success.

### Permission

Classify launch as at least low-risk side effect (`L1_LOW_WRITE` or equivalent honest category).

User-initiated menu may still auto-authorize according to policy.

## Mandatory tests

```text
test_calculator_maps_to_calc
test_unknown_open_request_does_not_default_notepad
test_agent_context_is_task_local
test_unverified_step_cannot_complete
test_launch_requires_observable_verification
test_agent_completed_only_after_all_verified
test_agent_body_goes_through_director
test_agent_summary_contains_verified_fact
test_app_launch_not_classified_read_only
```

---

# 11. P1 — Feed production GUI path

## Verified failure

Harness Feed runs `_feed()` in a background thread.

Production GUI route:

```text
FurinaWindow command
-> App._on_user_command
-> _feed()
```

calls `_feed()` synchronously.

`_feed()` invokes DialogueBrain, so network latency can block Qt.

Harness therefore does not represent production responsiveness.

## Required fix

Use one production Feed submit path shared by Harness and GUI.

Deterministic food effect/event must be well-defined and exactly once.

LLM/dialogue work must not block Qt.

Apply final speech/runtime changes through the runtime apply boundary from §8.

## Mandatory tests

```text
test_gui_feed_uses_same_submit_path_as_harness
test_slow_feed_dialogue_does_not_block_qt
test_feed_effect_exactly_once
test_feed_emotion_event_exactly_once
```

---

# 12. P1 — Spatial naturalness closeout

## Passed — freeze

Do not regress:

```text
approach
withdraw
drag/release
manual release no snap-back
minimum dwell / cooldown
path persistence
```

Reviewer headless drag probe:

```text
moving -> drag -> release at new location -> next tick
position delta = 0
```

### Remaining failure

`wander/explore` still follow sparse piecewise-linear intermediate waypoints.

Reviewer trajectory probes showed instantaneous adjacent heading changes around:

```text
72° ... 167°
```

while approach is smooth.

This still reads as “折线机器人”.

## Required fix

Smooth all natural locomotion paths, not only approach/withdraw.

Use one of the existing permitted mechanisms:

- Catmull-Rom sampling
- bounded-curvature steering
- equivalent continuous-heading path

No zigzag theatrical wandering.

Wander still needs:

```text
move
dwell
reorient
later move
```

## Mandatory tests

```text
test_wander_has_no_sharp_waypoint_corner
test_explore_has_no_sharp_waypoint_corner
test_wander_destination_not_fixed_grid_only
test_path_stable_not_replanned_each_tick
test_drag_release_no_snap_back
```

Save real trajectory samples.

Acceptance target for normal sampled paths:

```text
no artificial instantaneous heading jump > ~45°
```

and typical path should be materially smoother than that threshold.

---

# 13. P1 — Memory contract debt

## Passed — freeze

Core conversation memory was reviewer-probed:

```text
store -> retrieve -> close DB -> reopen -> retrieve
```

works.

Do not redesign Memory or add a DB.

## Remaining unit debt

`MemoryEngine.behavior_hint()` reads raw `RelationshipState` principal fields (0..100) but compares:

```text
comfort > .6
annoyance > .6
```

as if normalized.

Probe:

```text
raw comfort=1 -> approach_bonus
raw annoyance=1 -> social_penalty=70
```

Current shown scheduler usage appears weak/dead for selection, so this is not the main blocker, but it is a contract landmine.

## Required fix

Either:

- consume canonical `relationship_factors()`, or
- remove the dead relationship bias path.

Do not create another normalization implementation.

Test exact units.

---

# 14. P1 — Harness must never fake green

## Verified failures

Current badges can show:

```text
glm ✓
Agent ✓
```

merely because Brain objects exist / AgentRuntime imports.

They do not prove:

- adapter availability
- latest call success
- fallback status
- verified Agent result

Memory “rows” is computed via `query(limit=1)`, so it is effectively only 0/1.

Harness Ignore is pointer leave rather than semantic ignore.

Harness Feed differs from GUI production path.

## Required fix

Badges must derive from real runtime facts:

### Life / Dialogue

At minimum:

```text
AVAILABLE
UNAVAILABLE
LAST_OK
LAST_FAILED
FALLBACK
```

Use real adapter availability + last attempt result.

### Agent

```text
IDLE
RUNNING
COMPLETED_VERIFIED
FAILED
UNVERIFIED
```

No `Agent ✓` just because import succeeded.

### Memory

Display truthful:

```text
AVAILABLE
EMPTY
COUNT=n
UNAVAILABLE
```

Use actual count.

### Add diagnostic fields required for Manual

```text
local clock hour/minute
World process/category/activity
real idle seconds
Emotion last semantic event
Emotion derived label
Life requested/applied next-think
Dialogue queue seq / turn seq
Activity instance + finish reason
Agent verification status
Spatial path style
trajectory waypoint/sample count
max heading delta
```

Harness must call the same production Feed / Ignore / Agent paths as GUI.

## Mandatory tests

```text
test_harness_glm_badge_requires_real_availability
test_harness_last_failure_not_green
test_harness_agent_unverified_not_green
test_harness_memory_count_truthful
test_harness_ignore_uses_semantic_ignore
test_harness_feed_same_production_path
```

---

# 15. Thread / EventBus architecture constraint

Do **not** rewrite the whole EventBus unless necessary.

The minimum contract is:

```text
slow work may happen in worker threads
domain/runtime state application happens on one owner thread
```

A queue/dispatcher around worker results is acceptable.

Do not let:

```text
BRAIN_SPOKE
AGENT_COMPLETED
AGENT_FAILED
feed-dialogue result
```

synchronously mutate runtime state on arbitrary worker threads.

The solution must remain testable headlessly.

---

# 16. Regression tests / evidence bundle

After implementing all fixes:

## A. Full test suite

All old tests green unless an old test encoded a now-proven broken behavior.

If replacing a test, explain why.

## B. Required deterministic evidence

Provide machine-readable or Markdown evidence for:

### World

```text
08:00 -> morning
13:00 -> afternoon
20:00 -> evening
00:30 -> night
```

plus actual Windows process/class/idle sample.

### Needs

Curves:

```text
30m / 2h / 4h / 8h
working and nonworking
```

### Emotion

Before/after for:

```text
baseline
praise
reject
poke
talk
feed
user_return
agent_done
```

plus 5m/30m decay samples.

### Activity lifecycle

Show:

```text
completed
interrupted at 10%
interrupted at 70%
replaced before complete
```

and exact outcome.

### Real pointer

Trace a real/simulated pointer:

```text
press -> click
press/move/release -> drag
petting
```

Show **one semantic causal event** each.

### Dialogue concurrency

Two messages where turn1 model latency > turn2 model latency.

Final visible/history order must still be:

```text
user1
furina1
user2
furina2
```

or another explicitly serialized FIFO contract, never reply2 before reply1.

### Agent

```text
notepad success
calculator success
unknown app fail/clarify
forced verified=False -> NOT completed
task A context does not enter task B
launch verify fail -> NOT completed
```

### Spatial

At least:

```text
3 approach
3 withdraw
5 wander
5 explore
2 drag/release
```

Save x/y samples and max heading delta.

---

# 17. Real GLM / Persona evidence — required, but Agent may NOT self-pass Persona

Reviewer environment cannot currently perform direct outbound POST to the production GLM endpoint.

Therefore, after code fixes, run the **real production `glm-4v-flash`** in an environment where it is available and save the unedited transcript.

Minimum scenarios:

1. “你在干嘛？”
2. ordinary casual talk
3. praise
4. teasing / mild embarrassment
5. serious tired/stressed user
6. text-only rejection
7. apology/recovery
8. memory callback
9. feed
10. Agent verified success
11. Agent failure
12. quiet coexistence / autonomous speech
13. 15-turn continuous conversation

Requirements:

- no cherry-picking;
- save all attempts;
- include DialogueAct, mode, activity, relevant World/Emotion/Relationship summary;
- mask API secrets;
- do not let Agent label itself “Persona PASS”.

Allowed report state:

```text
Persona = READY_FOR_REVIEW
```

Reviewer will blind-evaluate after masking explicit identity tokens.

---

# 18. Files expected to change

Likely areas only; do not mechanically touch every file:

```text
furina/runtime/scheduler.py
furina/runtime/window_awareness.py
furina/world_perception.py
furina/state/state_engine.py

furina/emotion/engine.py
furina/app.py

furina/behavior/motivation.py
furina/behavior/outcome.py

furina/interaction/gesture.py
furina/interaction/interaction_engine.py
furina/runtime/input_router.py

furina/dialogue_brain.py
furina/dialogue/validator.py
runtime/dialogue coordination layer if needed

furina/agent/agent_runtime.py
furina/agent/planner.py
furina/agent/tools/apps.py
furina/agent/permission.py

furina/runtime/spatial/planner.py
furina/runtime/spatial/runtime.py

furina/memory/memory_engine.py

furina/runtime/harness/*
tests/*
```

No asset files.

---

# 19. Required report

Create:

```text
docs/FURINA_PHASE13_FINAL_FUNCTIONAL_TRUTH_REPORT.md
```

Order:

1. **Reviewer failure reproduced**
2. root cause
3. production fix
4. deterministic evidence
5. regression
6. real GLM transcript evidence
7. remaining unverifiable items
8. STOP

Do not lead with test count.

---

# 20. Required final verdict from Agent

Agent is NOT allowed to write:

```text
Phase 13 PASS
Persona PASS
Manual PASS
Ready for Phase 14
```

Allowed:

```text
Technical = READY_FOR_REVIEW
Real Runtime Evidence = PROVIDED
Persona = READY_FOR_REVIEW
Manual = NOT YET REVIEWED
Overall = REVIEW_REQUIRED
```

Then STOP.

---

# 21. Reviewer release gate

Reviewer will verify only the explicit contracts in this task.

If they pass:

```text
PHASE 13 TECHNICAL = PASS
```

Then immediately:

# Manual Experience Acceptance

This is an acceptance gate, not another backend feature phase.

Manual covers:

- long-running Life cadence
- quiet coexistence
- real World context
- emotional causality
- interaction/reject/recovery
- memory
- feed
- Agent truthfulness
- real spatial motion
- real GLM Persona
- Windows responsiveness

If Manual passes:

```text
FUNCTIONAL DIGITAL LIFE = PASS
```

Then and only then:

# Phase 14 — Frontend Rendering / Asset Integration

Phase 14 may finally focus on:

- actual Furina image assets
- sprite/body presentation
- action animation presentation
- transitions
- visual polish
- final desktop embodiment

Backend semantics should then be treated as frozen except for true regressions.

---

# 22. STOP

After the implementation, push one coherent commit/series and send:

1. commit SHA
2. `docs/FURINA_PHASE13_FINAL_FUNCTIONAL_TRUTH_REPORT.md`
3. full test summary
4. deterministic evidence bundle
5. real GLM transcript
6. known remaining weaknesses

Then **STOP** and wait for reviewer.
