# Phase 13 FINAL — Functional Core Closeout

> **Reviewer status**
>
> Latest reviewed baseline:
>
> - Repository: `wqx-txdsyl/furina-desktop-ai`
> - C-R2 commit: `7e4b67a`
> - Hotfix commit: `2d0da7f`
> - Reviewer local regression: **452 PASS / 0 FAIL**
> - PySide6 6.11.2 + pytest-qt: real offscreen Qt environment works
>
> **Verdict before this task**
>
> ```text
> Phase 13 Technical Regression          PASS
> Phase 13 Functional Digital Life       FAIL / PARTIAL
> Persona Manual                          NOT READY
> Asset Presentation                     DEFERRED
>
> Overall:
> PARTIAL — FINAL FUNCTIONAL CORE CLOSEOUT REQUIRED
> ```
>
> This is the **last ordinary code closeout before Manual**.
>
> Do not start Phase 14.
> Do not touch assets.
> Do not add a new model or DB.
> Do not declare PASS from test count.

---

# 0. First evidence — why 452 PASS is not enough

The reviewer executed the latest production code and confirmed the following real failures.

## 0.1 Clock truth is wrong

Current production:

```python
self.se.update_clock(*time.localtime()[:2])
```

`time.localtime()[:2]` is:

```text
(year, month)
```

not:

```text
(hour, minute)
```

Observed equivalent:

```text
stored clock_hour = 2026
stored clock_minute = 8
```

This makes State/World/Life believe it is effectively always night.

---

## 0.2 Forced diversity is still active in BehaviorMotivation

Even though Scheduler `_anti_collapse` and LifeBrain `_apply_variety` are disabled, production scoring still applies:

```text
_observation_crush_guard()
_category_penalty()
_activity_penalty()
recency penalty
```

History alone can crush a valid activity/category and boost unrelated categories.

Observed with identical state:

```text
same state + no history:
read is competitive

same state + repeated read history:
read / SELF category is progressively crushed out of the top candidates
```

This is still artificial behavior rotation.

---

## 0.3 Quiet coexistence is forcibly interrupted

`Scheduler._monitor_kpi()` currently does:

```text
idle ~18 seconds
→ AUTONOMY_STAGNATION
→ _interrupt_life()
```

A KPI monitor is therefore mutating production behavior.

Quiet existence cannot be a failure condition.

---

## 0.4 Activity lifecycle is not truthful

Production tracks:

```text
_current_life_activity
_current_activity_duration
```

but:

- `_current_activity_duration` stores requested duration, not elapsed duration.
- `_current_activity_started_at` is not consistently initialized for ordinary Life activities.
- LifeBrain cannot reliably know true elapsed activity time.
- Changing activity calls `_apply_activity_outcome(prev)` as if the previous activity completed successfully, regardless of elapsed duration / interruption / rejection.

Therefore:

```text
start activity
→ immediately replaced
→ still receives completion reward
```

is possible.

---

## 0.5 Activity Outcome violates Relationship ownership

`behavior/outcome.py` directly mutates raw `RelationshipState` for activities such as:

```text
approach_user
talk
invite_user
comfort
offer_help
assist_user
```

This means Furina can gain relationship simply because **she acted**, even if the user did not respond.

It also bypasses:

```text
RelationshipEngine.apply()
```

single-writer ownership and persistence semantics.

---

## 0.6 approach_user social need is double-counted

Current outcome contains both:

```text
needs={"social_need": -40}
social_need=-40
```

Both are applied.

Observed equivalent:

```text
social_need 80
→ about 21 after one approach_user settlement
```

This is not one causal effect.

---

## 0.7 Homeostasis runs on a minutes-scale, not a life-scale

Using real scheduler seconds:

### Idle / not working

Approximate observed state:

```text
1 min:  boredom ~63, social_need ~74
5 min:  hunger ~53
10 min: hunger ~86, fatigue ~56
30 min: hunger/fatigue/sleepiness ~= 100
```

### User working

Approximate observed:

```text
1 min: fatigue ~53, boredom ~78
2 min: fatigue ~86, boredom ~=100
3 min: fatigue ~=100
```

This makes a supposed all-day desktop life hit physiological ceilings within minutes.

This is a **time-unit / functional horizon bug**, not visual polish.

---

## 0.8 Wander / Explore is still visibly robotic

Actual sampled spatial trajectories show:

```text
CURVED_APPROACH:
smooth, max local heading delta ~7°

ARC_WITHDRAW:
mostly smooth, ~20–30° max

WANDER / EXPLORE:
72°–167° instantaneous direction changes at intermediate points
```

Approach was fixed; wander/explore still follows unsmoothed polyline waypoints.

---

## 0.9 Agent calculator route is wrong

Observed planner helper behavior:

```text
"打开计算器"
→ app.launch(name="notepad")
```

because calculator is not mapped and `_guess_app()` falls back to notepad.

---

## 0.10 Agent can claim success without verification

Current `_verify()` effectively returns true for many successful ToolResults even when:

```text
ToolResult.verified == False
```

Examples:

```text
fs.organize: ok=True, verified=False
→ Agent _verify() == True

app.launch:
Popen returned
→ immediately ToolResult(... verified=True)
```

Then Agent emits:

```text
AGENT_COMPLETED
```

even though the post-condition may not have been verified.

This violates the project's own rule:

> 未验证不得宣称成功。

---

## 0.11 Agent context leaks between tasks

`AgentRuntime.context.vars` persists across requests and only `.update()` is called.

Observed equivalent:

```text
Task A context: path=/tmp/A
Task B: no path supplied

Task B planner still sees path=/tmp/A
```

Unrelated tasks must not inherit stale execution targets.

---

## 0.12 Agent body/task ownership bypasses Director

App/Agent callbacks directly write:

```text
state.life.macro = WORKING
state.life.activity = agent_...
attention = ACTIVE_WINDOW
```

No production `P_AGENT_TASK` ActionRequest owns the Agent action through Director.

Director therefore is not actually the sole owner of action arbitration for Agent tasks.

---

## 0.13 Production feeding is still GUI-blocking

Harness puts feed in a background thread, but the real product command route:

```text
FurinaWindow command
→ App._on_user_command("喂：...")
→ _feed()
→ synchronous DialogueBrain.say()
```

runs before returning.

A deliberately slow Dialogue call causes `_on_user_command()` to block for the same duration.

The Harness fix does not fix production.

---

## 0.14 Feeding bypasses EmotionEngine and ignores actual hunger state

`feeding.apply_food()` directly writes:

```text
state.emotion.mood
state.emotion.label
```

instead of using EmotionEngine as the canonical emotion writer.

Also `hungry=True` is effectively always used by production.

Observed:

```text
hunger=5 + cake
and
hunger=80 + cake
```

both consume food and produce essentially the same semantic reaction path.

---

## 0.15 Dialogue Validator is not enforced

`DialogueBrain.say()` only blocks one invalid issue:

```text
generic_assistant_voice
```

Other validator failures are allowed through.

Production-path probes:

```text
（叹气）我知道了。
→ returned

本神本神本神！
→ returned

好！好！好！好！
→ returned
```

even though the Validator marks such outputs invalid.

---

## 0.16 God calibration can turn a direct user response into silence

If model output contains `"本神"` in a suppressed context or cooldown:

```text
gate_output()
→ None
```

A user may ask a direct question, the model answers, then the post-gate silently discards the answer.

Style correction must not become unexplained conversational silence.

---

## 0.17 Persona prompt still over-primes “本神”

Current persona/prompt still includes semantics equivalent to:

```text
自称“本神”
```

and multiple synthetic examples contain it.

This conflicts with the frozen character rule:

```text
“本神” = contextual old-stage register
not default identity
```

It encourages a generic caricature instead of Furina-specific speech rhythm.

---

## 0.18 Rejection questions are misclassified

Current order checks generic questions before rejection.

Observed:

```text
“别烦我好吗？”
→ RESPONSE_TO_QUESTION

“能不能先别打扰我？”
→ RESPONSE_TO_QUESTION
```

Relationship text semantics may reject correctly, but DialogueAct/persona register is wrong.

---

## 0.19 Trust → emotional openness code is dead

`ExpressionEngine.strategy()` computes a local `openness += ...` but does not write it back.

Observed:

```text
trust=.2 → emotional_openness=.5
trust=.9 → emotional_openness=.5
```

Trust therefore does not affect the intended expression dimension.

---

## 0.20 Short-term dialogue history is much shorter than advertised

Storage limit is 8 messages, but production prompt currently uses effectively only about the last **3 messages** before current user text.

This is roughly 1–2 prior turns, not enough to validate a coherent 15-turn conversation.

---

## 0.21 Few-shot examples can contradict the current activity

For an activity question, the selector can inject an example whose literal speech says:

```text
“在看书……”
```

even if current real activity is:

```text
eat / wander / rest
```

Examples currently teach both style **and accidental facts**.

That can corrupt runtime grounding.

---

## 0.22 Harness Ignore has reversed semantics

Harness `Ignore` currently maps to:

```text
interaction.emit_event("leave")
```

Scheduler generic interaction handling then:

```text
social_need decreases
adapt_tolerance(user_responded=True)
```

So “ignore” can be interpreted as a positive user response.

---

## 0.23 One physical interaction can create duplicate long-term memories

One pet/poke/drag can produce:

```text
App memory.observe(raw interaction)
+
Scheduler consolidate structured Experience
```

Two long-term representations for the same event can enter retrieval.

---

## 0.24 World focus events are level-triggered instead of transition-triggered

While focus stays high:

```text
FOCUS_STARTED
```

can be emitted repeatedly after debounce.

After long focus threshold:

```text
LONG_FOCUS
```

can also repeat.

A “STARTED” event must be an edge, not a periodic status heartbeat.

---

## 0.25 Harness Agent badge is not truthful

`runtime_health()` refreshes Agent state from attributes such as:

```text
_busy
_last_err
_last_success
```

that AgentRuntime does not define.

Event callback may set `RUNNING/SUCCESS`, then next UI refresh resets the badge back to IDLE.

---

# 1. Objective

This closeout has one goal:

> **Make the asset-free rectangle build causally trustworthy and experientially testable as a digital life.**

It does NOT aim for final visual polish.

After this task, reviewer will perform the complete Manual Experience Audit.

There will be no ordinary “Phase 13E/13F” iteration.

---

# 2. A — Time / World Truth

## A1. Fix clock input

Replace the incorrect year/month wiring with actual local:

```text
tm_hour
tm_min
```

Required production test:

```text
fake local time 17:42
→ state.clock_hour == 17
→ state.clock_minute == 42
→ world.day_period == afternoon
```

Also test:

```text
00:30 → night
08:00 → morning
13:00 → afternoon
20:00 → evening
```

Do not source time independently in multiple subsystems.

---

## A2. Make world “START” events edge-triggered

`FOCUS_STARTED`:

```text
low/non-focus → focused
```

exactly once per focus episode.

`FOCUS_ENDED`:

```text
focused → non-focus
```

exactly once.

`LONG_FOCUS`:

one milestone event per focus episode, unless an explicit later milestone exists.

Do not emit these every 20 seconds while the condition remains true.

Add fake-clock deterministic tests.

---

# 3. B — Life Autonomy / Homeostasis

## B1. Remove remaining history-only forced diversity

Production candidate ranking must not use:

```text
_observation_crush_guard
_category_penalty
_activity_penalty
```

or an equivalent “you already did this category/activity, therefore change” mechanism.

Do not replace them with another forced rotation.

A real **refractory period** is allowed only when causally tied to a completed activity and its physical/social semantics, e.g.:

```text
just finished drinking
→ cannot immediately drink again
```

not:

```text
read twice
→ must stop reading
```

### Test

With an identical state and unchanged needs/world/relationship:

```text
read is top candidate
mark read history multiple times
```

must not be pushed out solely because of repetition history.

Repeated valid activity must remain possible.

---

## B2. KPI must be observation-only

`_monitor_kpi()` may log:

```text
AUTONOMY_STAGNATION
```

but must not:

```text
_interrupt_life()
change candidate weights
change activity
```

solely because the character has been idle for ~18s.

Quiet coexistence is a valid life state.

---

## B3. Establish a canonical activity lifecycle

Create one truthful lifecycle contract:

```text
activity
started_at
requested_duration
elapsed
interruptible
completion_reason
completed / interrupted / cancelled
```

The production activity owner must set `started_at` when the action is actually accepted/executed, not merely when the LLM proposes it.

The Frame and LifeBrain snapshot must read the same activity timing truth.

---

## B4. Settle outcomes only according to real lifecycle

Do NOT:

```text
activity changed
→ previous activity automatically success=True
```

Settlement must distinguish at minimum:

```text
COMPLETED
INTERRUPTED_BY_USER
INTERRUPTED_BY_AGENT
REPLACED_BY_LIFE_DECISION
FAILED
CANCELLED
```

Full outcome benefit only for legitimate completion.

Partial/interrupted benefit must use elapsed/progress semantics.

A 1-second `read` must not earn the same benefit as a completed read period.

---

## B5. Fix homeostasis to a real product time horizon

Do not randomly divide every rate.

First define explicit product horizons and calibrate against them.

Required invariant targets for a healthy baseline character, no activity outcome:

### Normal idle coexistence

```text
10 minutes:
no physiological Need should hit >=90 from normal baseline

30 minutes:
hunger/fatigue/sleepiness must not all saturate

2 hours:
at least one meaningful physiological drive may become strong,
but the entire Needs vector must not be pinned at 100
```

### User working

```text
10 minutes:
fatigue < 70
boredom < 90

30 minutes:
fatigue may be meaningfully high but should not be guaranteed 100
```

Choose reasonable exact expected bands and document them.

The product is an all-day desktop companion; “minutes == hours” is invalid.

Do not retune Behavior weights to hide bad Needs timing.

---

# 4. C — Activity Outcome / Relationship Ownership

## C1. Remove Relationship mutation from generic Activity Outcome

`behavior/outcome.py` must not directly write raw relationship fields.

These actions alone do NOT prove positive user relationship:

```text
approach_user
talk
invite_user
comfort
offer_help
assist_user
```

Relationship changes require verified interaction outcome:

```text
user responded
user accepted
help succeeded and user received result
user rejected
user ignored
```

All relationship writes continue through:

```text
RelationshipEngine.apply(...)
```

exactly once.

---

## C2. Fix duplicate social_need outcome

For `approach_user`, use one and only one social_need effect.

Remove either:

```text
needs.social_need delta
```

or:

```text
Outcome.social_need
```

as duplicated representation.

Audit all outcomes for the same double-field pattern.

---

## C3. Activity outcomes must persist only self-state causal effects

Generic activity settlement may update:

```text
Needs
Emotion through EmotionEngine
internal satisfaction
```

but must not manufacture user approval.

---

# 5. D — Spatial Natural Motion

## D1. Keep the good paths

Do not regress:

```text
CURVED_APPROACH
ARC_WITHDRAW
dt-based movement
path persistence
drag ownership
safe zones
```

---

## D2. Smooth Wander / Explore

Current multi-point paths have instantaneous 72°–167° turns.

Do not follow raw waypoint polyline corners.

Use one of:

```text
Catmull-Rom sampling
Bezier sampling
bounded steering / curvature-constrained interpolation
```

for wander/explore.

### Required numeric acceptance

Across at least 20 seeded trajectories:

```text
APPROACH max adjacent heading delta <= 30°
WITHDRAW max adjacent heading delta <= 40°
WANDER/EXPLORE normal interior heading delta <= 45°
```

No single waypoint corner >60° unless caused by:

```text
screen safety emergency
user drag
new high-priority interrupt
```

---

## D3. Wander rhythm

Require:

```text
move
→ dwell
→ optional reorient
→ later move
```

not continuous patrol.

Collect:

```text
trajectory x/y
heading
path length
direct distance
dwell times
destinations
```

for report.

Do not use assets.

---

# 6. E — Dialogue / Persona Runtime

## E1. Enforce Validator truth

If `DialogueValidator.valid == False`, the raw output must not be returned unchanged.

Blocking issues include at least:

```text
generic_assistant_voice
stage_direction
overuse_god_catchphrase
over_exclamation
example_copy
too_long
god_overuse
god_overuse_ordinary when marked invalid
```

Non-blocking informational warnings can remain separate.

---

## E2. User-initiated invalid output gets one bounded retry

For a direct user conversation:

```text
LLM output
→ invalid style
```

do NOT silently turn the turn into `None`.

Allow at most **one** correction retry using the same DialogueBrain / same LLM, with compact validator feedback.

Then:

```text
retry valid → use
retry fails → truthful degraded/silent status
```

No fixed Furina fallback line.

Autonomous low-priority speech may simply stay silent after validation failure.

---

## E3. GodCalibration must not cause unexplained silence

In a user-initiated turn:

```text
suppressed/cooldown “本神”
```

should be handled as a style-validation retry case, not simply:

```text
gate_output → None
```

Do not replace words mechanically.

---

## E4. Fix “本神” character contract

Change persona guidance from semantics equivalent to:

```text
“自称本神”
```

to:

```text
“本神”是旧舞台式/骄傲式自称。
默认日常不需要使用；
只在 proud/playful/performance/tease 等合适语境偶发，
严肃、私下、帮助、脆弱场景主动收起。
```

Audit synthetic examples.

Do not remove all `"本神"`; reduce it to a contextual minority.

Do not add copied game quotes.

---

## E5. Rejection classification takes priority over punctuation

These must classify as boundary/rejection, not ordinary question:

```text
别烦我好吗？
能不能先别打扰我？
你先让我安静会儿行吗？
```

Run rejection semantic checks before generic question detection, or support a clear priority layer.

---

## E6. Fix trust → openness

Actually assign the calculated relationship effect back to:

```text
ExpressionStrategy.emotional_openness
```

Required counterfactual:

```text
same everything
trust=.2 vs trust=.9

high trust must produce measurably higher openness
```

within valid cap.

---

## E7. Increase real bounded short-term conversation context

Define one clear contract, e.g.:

```text
last 8–12 messages
or last 4–6 turns
within a compact character budget
```

Current effective ~3 previous messages is insufficient.

Do not create a DB.

Do not include current user message twice.

---

## E8. Few-shot examples must teach mechanism, not false facts

Do not inject an example whose literal semantic fact contradicts runtime.

For example:

```text
current activity = eat
question = “你在干嘛？”
```

must not be given a style example that literally claims:

```text
“我在看书”
```

Options:

- store separate style skeleton/scene metadata,
- include example context and reject contradictory contexts,
- or make activity-query examples fact-neutral.

The model must always prioritize current runtime truth.

---

## E9. Remove/deprecate unused fixed fallback lines

`_fallback_line()` still contains a hardcoded Furina line pool.

If it truly has zero production callers, remove/deprecate it so it cannot accidentally re-enter formal speech ownership.

Formal character speech owner remains DialogueBrain.

---

# 7. F — Interaction / Feed / Memory

## F1. Create a real semantic Ignore route

Harness Ignore and future UI ignore semantics must route to a canonical:

```text
USER_IGNORE
```

effect:

```text
RelationshipEngine.apply(EV_IGNORE) exactly once
Life tolerance decreases appropriately
does NOT count as user_responded=True
may interrupt/alter future social initiative if semantics require
persistence exactly once
```

Do not map Ignore to generic `leave` and then treat it as positive interaction.

---

## F2. Deduplicate physical-interaction memory

One pet/poke/drag must not independently create:

```text
raw memory.observe row
+
structured consolidate row
```

for the same event unless they are explicitly linked as distinct memory layers.

Prefer one canonical episodic consolidation route.

Required:

```text
one user physical action
→ one canonical long-term episode identity
```

---

## F3. Production feeding must be non-blocking

Use one shared production route for:

```text
real FurinaWindow menu
Harness
future interaction UI
```

Required flow:

```text
USER_FEED
→ deterministic state/event application quickly
→ return UI
→ DialogueBrain in worker
→ result applied on runtime/main owner
→ Frame.speech
```

A fake DialogueBrain sleeping 1 second must not make the Qt click/command handler block for 1 second.

---

## F4. Emotion ownership during feeding

Feeding must not directly mutate:

```text
emotion.label
emotion.mood
```

through `feeding.py`.

Use the existing EmotionEngine feed/food event semantics.

---

## F5. Feeding must respect actual hunger

Compute hunger state from real Needs.

At minimum differentiate:

```text
very hungry
normal
already full / very low hunger
```

Do not force `"ate": True` and identical consumption semantics for every state.

Do not hardcode final dialogue.

DialogueBrain receives the deterministic feeding outcome and expresses it.

---

# 8. G — Agent Truth / Arbitration

## G1. Fix calculator

Add explicit app resolution for:

```text
calculator
计算器
calc
```

On Windows resolve to the intended calculator command/app.

No fallback to notepad.

---

## G2. Per-request Agent context

At the beginning of every `execute()`:

```text
new request context
```

must be created from:

```text
explicit safe persistent context
+
this request extra_context
```

Do not keep arbitrary previous task vars.

Test:

```text
task A path=/tmp/A
task B no path

task B planner must not see /tmp/A
```

---

## G3. Verification must be real

`AGENT_COMPLETED` must mean all required postconditions were verified.

Do not convert:

```text
ok=True, verified=False
```

into verified success.

### fs.organize

After actual move:

```text
verify expected source files are gone / destination exists
```

or equivalent post-state.

### app.launch

`Popen` alone is execution, not verification.

On Windows verify at least one reliable signal where feasible:

```text
process/window becomes present
```

If verification is unavailable:

```text
status = completed_unverified / partial
```

and Dialogue must say truthfully that the launch command was issued, not “已经成功打开”.

---

## G4. Agent event/status contract

Distinguish:

```text
STARTED
COMPLETED_VERIFIED
COMPLETED_UNVERIFIED
FAILED
PERMISSION_DENIED
```

or an equivalent truthful status model.

Harness badge must consume this authoritative state.

---

## G5. Fix Harness Agent badge

Do not query nonexistent:

```text
_busy
_last_err
_last_success
```

Either:

- AgentRuntime owns a real read-only status object/property, or
- Harness maintains event-derived authoritative status without overwriting it every refresh.

---

## G6. Agent must acquire Director ownership

An active Agent task must submit/own a:

```text
source="agent"
priority=P_AGENT_TASK
```

Director action.

Do not directly write Life state from `_on_agent_body()` as the primary arbitration mechanism.

Required behavior:

```text
Agent starts
→ Director owns agent action
→ autonomous Life cannot overwrite it
→ direct user interaction can preempt according to priority policy
→ Agent completion/failure releases Director agent ownership
```

No state race between autonomous `mind` and Agent.

---

## G7. Permission semantics

`app.launch` is not a read-only action.

Classify it at least:

```text
L1_LOW_WRITE
```

or equivalent.

Do not globally auto-confirm L2/L3 merely because `submit_agent_task()` was called.

Confirmation bypass may only apply when the request itself carries explicit proof that the user just authorized that exact action.

Harness test tasks may use a safe explicit fixture authorization.

---

# 9. H — Runtime Mutation / Thread Ownership

Do not redesign the whole EventBus.

But enforce this boundary:

```text
LLM / Agent worker threads:
compute + emit result

Scheduler/domain mutable state:
applied on one runtime/main mutation owner
```

Current synchronous EventBus can call Scheduler callbacks on worker threads.

Create a minimal runtime command/result queue if needed.

Required stress test:

```text
Life decision worker
Dialogue worker
Agent worker
Qt/harness refresh
```

run concurrently for repeated cycles with:

```text
0 cross-thread QWidget writes
0 duplicate domain applies
0 corrupted Life activity
0 uncaught exceptions
```

If an existing main-thread result-drain pattern can be reused, use it.

Do not build a new actor framework.

---

# 10. I — Harness / Trace Truth

The Harness remains a dev observability surface, not a second Runtime.

Fix the following:

```text
Agent badge truthful
Ignore semantics truthful
Frame speech truth unchanged
Spatial Proxy uses unique SpatialRuntime
```

Add diagnostic fields only where needed for this closeout:

```text
activity elapsed + completion reason
current Life next-think
Agent verified status
feeding outcome / hunger band
spatial path style
```

Do not turn Harness into a large UI project.

---

# 11. Accepted Debt — DO NOT EXPAND THIS TASK

The following do not justify more architecture work in this closeout unless they cause an actual regression:

```text
Asset content / walk / drag / read PNG
visual polish
TTS / ASR
browser/Office capability expansion
Memory vector relevance refinement
deprecated RelationshipState.apply if production calls remain zero
dead MemoryEngine.behavior_hint path — do not silently activate it
full trace parent/child perfection beyond functional truth
final Windows DPI/aesthetic positioning
```

Record them; do not fix them.

---

# 12. Mandatory automated tests

Add behavioral tests, not source-string-only checks.

At minimum:

```text
# time/world
test_scheduler_uses_real_hour_minute
test_world_focus_started_edge_once
test_world_long_focus_once_per_episode

# life/homeostasis
test_motivation_repetition_does_not_force_variety
test_kpi_idle_does_not_interrupt_life
test_activity_elapsed_truth
test_interrupted_activity_does_not_receive_full_outcome
test_homeostasis_10min_horizon
test_homeostasis_30min_horizon
test_homeostasis_working_horizon

# outcome/relationship
test_activity_outcome_does_not_write_relationship
test_approach_social_need_not_double_counted

# spatial
test_wander_path_heading_continuity
test_explore_path_heading_continuity
test_wander_has_dwell

# dialogue
test_validator_blocks_all_invalid_blocking_issues
test_user_dialogue_invalid_style_retries_once
test_god_suppression_does_not_silence_direct_user_turn_without_retry
test_rejection_question_classifies_decline
test_high_trust_increases_openness
test_dialogue_history_real_multiturn_budget
test_activity_example_cannot_inject_contradictory_fact

# interaction/feed
test_ignore_is_not_positive_response
test_one_interaction_one_episode_identity
test_production_feed_command_is_nonblocking
test_feed_emotion_uses_emotion_engine
test_feed_low_vs_high_hunger_differs

# agent
test_calculator_routes_calculator
test_agent_context_cleared_between_requests
test_unverified_tool_cannot_emit_verified_completion
test_agent_launch_verification_truth
test_agent_owns_director_during_task
test_agent_releases_director_on_finish
test_app_launch_permission_not_read_only
test_harness_agent_badge_matches_real_agent_status

# concurrency
test_async_results_apply_on_runtime_owner
test_concurrent_life_dialogue_agent_stress
```

All existing **452** tests must remain green unless one encodes a now-proven invalid behavior.

If replacing a test, explain the broken assumption.

---

# 13. Mandatory real-runtime evidence

Report must start with these, **before regression count**.

## 13.1 Clock

```text
OS local time:
Frame clock:
World day_period:
```

must agree.

---

## 13.2 Quiet coexistence

Run at least a meaningful accelerated/deterministic equivalent plus a real-duration smoke.

Report:

```text
Life decision timestamps
next-think
activities
interrupt reasons
idle dwell
Needs over time
```

Prove there is no 18-second forced-idle wakeup and no history-only activity rotation.

---

## 13.3 Homeostasis

Report tables:

```text
0 / 10 / 30 / 60 / 120 min
```

for idle and working cases.

---

## 13.4 Activity lifecycle

Show:

```text
activity=read
started_at
elapsed
interrupt at ...
completion_reason=INTERRUPTED
outcome scale=...
```

and a genuine completed activity.

---

## 13.5 Spatial

For at least:

```text
5 approach
5 withdraw
10 wander/explore
2 drag/release
```

export:

```text
x/y samples
max heading delta
route ratio
dwell
destination
```

No asset is used as evidence.

---

## 13.6 Dialogue production-path probes

Using a deterministic fake LLM to test validation plumbing:

```text
stage direction output
overused 本神
over-exclamation
generic assistant
```

must never pass raw unchanged.

Then run real model evidence when available.

---

## 13.7 Interaction / Feed

Show:

```text
head touch
ignore
reject
feed hungry
feed full
```

with:

```text
Emotion before/after
Relationship before/after
Memory episode identity
Life interrupt
Frame speech
```

---

## 13.8 Agent

Show:

```text
open notepad
open calculator
organize safe test directory
one deliberately unverifiable action/result
one safe failure
```

For every task:

```text
request
permission
Director ownership
tool
execution result
verification
final status
Dialogue feedback
```

---

# 14. Real Persona evaluation — mandatory but Agent cannot self-PASS

After all objective Dialogue fixes above, run **real `glm-4v-flash`** through the production Dialogue path.

Required dataset:

```text
>= 30 single/mixed contexts
+
one uninterrupted >=15-turn conversation
```

Must cover:

```text
quiet coexistence
current activity question
casual chat
praise
teasing
embarrassment
serious fatigue
rejection
repair
memory callback
feeding
Agent success
Agent failure
```

Do not cherry-pick.

Commit/save the complete transcript in:

```text
docs/PHASE13_FINAL_PERSONA_TRANSCRIPT.md
```

Create a second blind copy in which only explicit identity tokens are masked:

```text
芙宁娜
Furina
本神
水神
枫丹
```

Do not rewrite other wording.

Agent status:

```text
Persona Technical = READY_FOR_BLIND_REVIEW
```

Agent must not mark Persona PASS.

---

# 15. Report format

Create:

```text
docs/FURINA_PHASE13_FINAL_REPORT.md
```

Required structure:

```markdown
# Phase 13 FINAL — Functional Core Closeout

## 0. Status
Technical:
Functional runtime:
Persona:
Manual:
Overall:

## 1. REAL RUNTIME EVIDENCE
### Clock
### Quiet coexistence
### Homeostasis
### Activity lifecycle
### Spatial trajectories
### Dialogue validation
### Interaction / Ignore / Feed
### Memory
### Agent verification / Director ownership

## 2. Root Causes Fixed

## 3. Exact Ownership Contracts
Time:
Activity:
Emotion:
Relationship:
Speech:
Spatial:
Agent:
Runtime thread mutation:

## 4. Persona Transcript
links / paths

## 5. Regression
Previous: 452
New:
Replaced invalid tests:
Total:
Failures:

## 6. Remaining Accepted Debt

## 7. Verdict

Allowed only:
READY_FOR_REVIEW
PARTIAL
FAIL

## 8. STOP
STOP DEVELOPMENT.
WAIT FOR REVIEWER.
```

Do not put test count before real evidence.

---

# 16. Forbidden changes

Strictly forbidden in this task:

```text
Phase 14
asset generation
asset remapping/polish
animation aesthetics
new LLM
new database
new vector DB
new agent capability family
browser automation expansion
Office automation expansion
TTS/ASR
large UI redesign
random personality lines
hardcoded Furina quote bank
copyrighted game dialogue
behavior diversity guards
parameter changes whose only purpose is “make distribution look nicer”
```

Homeostasis rate changes are allowed **only** as a measured time-unit calibration under §B5.

---

# 17. Final PASS gate

Agent may only report:

```text
Technical = READY_FOR_REVIEW
```

when ALL are true:

```text
clock year/month bug                             = 0
history-only forced behavior rotation            = 0
KPI behavioral intervention                      = 0

activity start/elapsed/completion truth           = PASS
interrupted activity full reward                  = 0
ActivityOutcome direct Relationship writes        = 0
social_need duplicated outcome                    = 0

10/30min Needs pathological saturation            = 0
all-day life time horizon evidence                = PASS

wander/explore >60° normal hard corners           = 0
wander dwell                                      = PASS

raw invalid Dialogue output returned              = 0
direct user turn silently lost to style gate      = 0
default “本神” identity instruction               = 0
rejection-question wrong act                      = 0
trust openness dead path                          = 0
short-term multi-turn context                     = PASS
few-shot factual contradiction                    = 0

Ignore counted as positive response               = 0
duplicate interaction episodic memory             = 0
production feed GUI block                         = 0
feeding direct Emotion state write                = 0
hunger-insensitive feeding                        = 0

calculator→notepad                                = 0
Agent stale request context                       = 0
unverified completion claimed verified            = 0
Agent Director bypass                             = 0
Agent status fake/idle reset                      = 0
launch permission classified read-only            = 0

repeated FOCUS_STARTED/LONG_FOCUS level events    = 0

all previous regression                           = PASS
new behavioral regression                         = PASS
assets changed                                    = 0
```

Then:

```text
Phase 13 FINAL Technical = READY_FOR_REVIEW
Persona = READY_FOR_BLIND_REVIEW
Manual = NOT DECLARED BY AGENT
Overall = REVIEW_REQUIRED
```

---

# 18. STOP / handoff

When complete:

```text
1. Push one or more clearly named commits to GitHub.
2. Send commit SHAs.
3. Send docs/FURINA_PHASE13_FINAL_REPORT.md.
4. Send docs/PHASE13_FINAL_PERSONA_TRANSCRIPT.md.
5. STOP.
```

Do not begin another phase.

The reviewer will then run:

```text
full pytest
Qt/Harness
functional manual checklist
spatial trajectory review
Persona blind review
```

If reviewer passes:

```text
FUNCTIONAL DIGITAL LIFE = PASS
→ next phase may begin
```

If reviewer finds a hard blocker, only that concrete blocker may reopen Phase 13.
No ordinary optimization loop.
