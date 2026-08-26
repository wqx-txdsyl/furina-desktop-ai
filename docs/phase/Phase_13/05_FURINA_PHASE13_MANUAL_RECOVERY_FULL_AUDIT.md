# FURINA Phase 13 — Functional Digital Life Manual Recovery
## Full-Audit Closeout Taskbook / MR1

> **Reviewer baseline:** latest reviewed commit = `2d0da7fb7a34e938f2a064807b8a1f62bec22d2e`
> (`7e4b67a` C-R2 + `2d0da7f` hotfix)
>
> **Reviewer environment:** Python 3.13.5 / PySide6 6.11.2 / pytest-qt / Qt offscreen
>
> **Reviewer regression:** **452 PASS / 0 FAIL**
>
> This taskbook is based on a full production-path audit plus targeted runtime probes.
> Test count is **not** the acceptance criterion.

---

# 0. Incoming Verdict

```text
AUTO REGRESSION            PASS (452/452)
C-R2 CONTRACT              MOSTLY PASS
DRAG / NO SNAP-BACK        PASS
MEMORY+REL RESTART         PASS

MANUAL FUNCTIONAL          FAIL
LIFE AUTONOMY TRUTH        FAIL
ACTIVITY LIFECYCLE         FAIL
HARNESS OBSERVABILITY      FAIL
AGENT VERIFY/TRUTH         FAIL
SPATIAL NATURALNESS        PARTIAL
DIALOGUE VALIDATION        FAIL
PERSONA REAL-GLM           PENDING BLIND REVIEW

FUNCTIONAL DIGITAL LIFE    FAIL — DO NOT ENTER NEXT PHASE
```

This is **not C-R3 ordinary optimization**.
These are hard blockers discovered during Manual/full-system audit.

Do all items in this taskbook as **one closeout batch**.

---

# 1. Freeze / Do Not Rewrite

The following were re-verified or materially improved. **Do not rewrite them unless a change below requires a minimal integration adjustment.**

- C-R2 canonical `relationship_factors()` principal/rate normalization.
- relationship rate write clamp / delta migration.
- C-R2 reject duplicate-stat removal.
- `DialogueBrain` current-turn prompt duplication fix.
- conversation memory observation happens after current reply.
- `MemorySource.CONVERSATION`.
- bounded short-term Dialogue history.
- `agent_fail -> agent_failure` example routing.
- synthetic stage-direction examples cleanup.
- `annoyance > 0.6` ExpressionStrategy hotfix.
- CURVED_APPROACH / ARC_WITHDRAW Catmull-Rom implementation.
- wander destination jitter.
- drag ownership / drag release position commit.
- manual drag grace / no snap-back.
- MemoryStore SQLite RLock/thread-safe DB connection.
- Memory + Relationship persistence across restart.
- no new asset work.

Reviewer drag probe:

```text
movement active
→ drag_start
→ manual window moved
→ drag_release

release foot = (1128, 660)
4 seconds of ticks after release:
unique positions = 1
old target resumed = NO
snap-back = NO
```

Freeze this behavior.

---

# 2. P0 — REAL CLOCK IS WRONG

## Reviewer evidence

Production:

```python
self.se.update_clock(*time.localtime()[:2])
```

But:

```text
time.localtime()[:2] = (year, month)
```

Reviewer probe:

```text
actual clock:          18:25
scheduler arguments:  (2026, 8)
```

This contaminates:

- `clock_hour`
- `_day_phase`
- World period
- sleep/rest reasoning
- LifeBrain snapshot time
- any time-of-day behavior

## Do

Use the real fields:

```python
lt = time.localtime()
self.se.update_clock(lt.tm_hour, lt.tm_min)
```

Have **one** clock ingestion contract.

## Tests

Add production-path tests:

```text
test_scheduler_clock_uses_tm_hour_tm_min
test_day_phase_uses_real_hour
```

Do not test only a helper.

## PASS

```text
CharacterState.clock_hour == injected/local tm_hour
CharacterState.clock_minute == injected/local tm_min
```

---

# 3. P0 — NEEDS / HOMEOSTASIS RUN ~100× TOO FAST FOR A DESKTOP LIFE

This is a **time-unit/product-timescale bug**, not a request to tune behavior distribution.

`update_needs(dt)` receives real seconds.

Current reviewer simulation from normal initial state:

## Idle

```text
1 min:  fatigue 23.6  hunger 26.8  boredom 62.9  social 73.9
5 min:  fatigue 38.0  hunger 53.2
10 min: fatigue 56.0  hunger 86.2  sleepiness 52.3
30 min: fatigue 100   hunger 100   sleepiness 100
```

## User working

```text
1 min: fatigue 53.0  boredom 78.4
2 min: fatigue 86.0  boredom 100
3 min: fatigue 100   boredom 100
10 min: hunger 86.2
```

A desktop companion intended to coexist for hours cannot reach biological crisis every few minutes.

## Do

1. Make rate units explicit:
   - e.g. `points_per_minute` or `points_per_hour`;
   - convert `dt_seconds` exactly once.

2. Keep homeostasis causal, but make it operate on **human-scale real time**.

3. Do not change rates to create more/less behavior variety.
   The repair must be justified as unit/time-scale correction.

4. Audit:
   - fatigue
   - hunger
   - sleepiness
   - energy
   - boredom
   - social_need
   - curiosity
   - playfulness
   - satisfaction
   - recharge/rising-drive

## Acceptance guardrails

From normal baseline with no special event:

```text
10 min idle:
  no physiological need may jump to crisis/high solely from elapsed time.

10 min working:
  fatigue may rise meaningfully but must not approach 100;
  boredom must not saturate to 100.

30 min:
  hunger/fatigue/sleepiness must not all saturate.

2 hours:
  state may become meaningfully hungry/tired depending context,
  but should still contain useful dynamic range instead of several hard-100 plateaus.
```

Write exact expected numeric ranges in tests after choosing the explicit time contract.

## Tests

```text
test_needs_ten_minute_idle_scale
test_needs_ten_minute_work_scale
test_needs_thirty_minute_no_mass_saturation
test_needs_two_hour_dynamic_range
test_needs_dt_unit_is_seconds_with_single_conversion
```

---

# 4. P0 — ANTI-COLLAPSE IS STILL ON IN OTHER PRODUCTION LAYERS

C-R1 removed the direct LifeBrain variety call, but full-system anti-collapse is still active.

## Current production mechanisms

`BehaviorMotivation._score()` still applies:

```python
_observation_crush_guard(activity)
_category_penalty(activity)
_activity_penalty(activity)
```

plus generic recent-activity suppression.

`_observation_crush_guard` does:

```text
observation > 50% of recent history:
  observation × 0.4
  all other categories × 1.4
```

This is forced diversity.

Reviewer identical-state probe:

```text
BASE:
read=.760
explore=.975
think=.085
observe_user=.065
wander=.282

same state after read→read history:
read=.064
explore=.390
think=.034
wander=.113

observation-heavy history:
observe_user=.001
observe_work=.001
read=1.000
explore=1.000
```

The world/state did not cause those changes.
Only recent category history did.

## There is also a hidden Scheduler anti-idle interrupt

```python
if idle streak >= 6:
    _interrupt_life("autonomy_stagnation")
```

At ~3s medium ticks this means roughly **18 seconds of valid idle** wakes LifeBrain simply because she stayed idle.

This violates:

```text
idle is a real behavior
quiet coexistence is a core metric
anti-collapse OFF
```

## Do

1. Remove production use of:
   - `_category_penalty`
   - `_activity_penalty`
   - `_observation_crush_guard`
   - generic recency suppression whose only reason is “you recently did this, switch”

2. Remove/deprecate dead:
   - `LifeBrain._apply_variety`
   - `Scheduler._anti_collapse`
   after tests no longer depend on them.

3. KPI can **log** long idle.
   KPI must never interrupt Life merely because idle persisted.

4. Repetition is allowed when:
   - Needs still support it;
   - activity has not completed;
   - World still supports it;
   - Personality/Identity/Memory/Relationship causally support it.

5. Semantic cooldown is allowed for genuinely discrete actions,
   but it must be action-specific and justified by semantics, not distribution balancing.

## Existing tests that must be replaced

Audit/remove tests such as:

```text
test_behavior_diversity.py
test_category_repetition_penalty
distribution caps that require observation < X%
tests preserving commented/dead _anti_collapse
```

Do not keep tests that encode the behavior we have explicitly declared broken.

## PASS

With an identical immutable state/world:

```text
changing only "recent category count"
must not multiply one category down and another up for diversity.
```

A valid `read → read` may remain `read → read`.

10–15 minutes of valid quiet idle must not generate `autonomy_stagnation` behavioral interrupts.

---

# 5. P0 — THERE IS NO REAL ACTIVITY LIFECYCLE

Current activity settlement is decision-replacement based:

```python
prev = current_activity
if prev != new_activity:
    _apply_activity_outcome(prev)  # defaults to success=True
```

Therefore:

```text
"another decision replaced it"
==
"the activity successfully completed"
```

That is false.

There is no authoritative normal-production:

```text
started_at
elapsed
phase
progress
completion
interrupted
failed
```

`_current_activity_started_at` is not initialized for normal Life decisions, while Frame currently publishes placeholders such as:

```text
activity_phase="LOOP"
activity_progress=0
activity_interruptible=True
```

LifeBrain's current activity duration also falls back toward ~0 when the authoritative start timestamp is absent.

## Reviewer failure scenario

```text
current activity = approach_user
user rejects
new Life decision = read

old approach is still settled as a successful outcome
```

A rejected/unfinished approach must never receive the same benefit as a completed one.

## Do

Create **one authoritative activity runtime lifecycle**, reusing existing structures/events wherever possible.

Minimum truth:

```text
activity
started_at
planned_duration
phase
elapsed
progress
interruptible
status:
  RUNNING / COMPLETED / INTERRUPTED / FAILED
completion_reason
```

### Ownership

An activity outcome is applied because the lifecycle says it ended, **not because a new decision exists**.

### Completion

Examples:

- timed SELF activity: completes after actual duration / explicit exit condition;
- spatial activity: consumes `SPATIAL_TARGET_REACHED` as evidence;
- Agent activity: success/failure from verified Agent result;
- user rejection: interrupts relevant social activity;
- drag/user interaction can interrupt where semantically appropriate.

### Partial outcome

Do not use a universal “interrupted = half reward”.

If partial progress is meaningful, derive it from real progress.

Examples:

```text
read interrupted after 80% -> partial calm/curiosity may be reasonable
approach_user rejected before successful contact -> NO positive relationship/social completion reward
failed Agent help -> no successful-help reward
```

## Frame

Frame must expose the authoritative lifecycle values.

Frontend/Harness must not invent them.

## LifeBrain

`current_activity.duration` must use the same authoritative lifecycle timestamp.

## Tests

```text
test_activity_start_sets_authoritative_timestamp
test_activity_progress_advances_with_time
test_decision_replacement_is_not_completion
test_interrupted_approach_gets_no_success_reward
test_spatial_arrival_can_complete_spatial_phase
test_frame_activity_fields_match_runtime_lifecycle
test_lifebrain_snapshot_uses_real_activity_elapsed
```

---

# 6. P0 — ACTIVITY OUTCOME CONTRACT HAS DUPLICATE / WRONG OWNERSHIP

`approach_user` currently contains both:

```python
needs={"social_need": -40}
social_need=-40
```

`apply_outcome()` applies both.

This double-charges the same need.

Additionally Activity Outcome directly writes raw `RelationshipState` fields:

```python
relationship.familiarity += ...
relationship.trust += ...
```

This bypasses `RelationshipEngine`, which is supposed to be the relationship owner.

## Do

1. A need effect may exist in **one schema location only**.

2. Remove duplicate `social_need` ownership.

3. Relationship effects from completed activities must go through `RelationshipEngine` semantic events or one canonical relationship mutation API.

4. `mark_done()` must happen on real completion, not simply when a decision was selected.

5. Keep ActivityOutcome as causal feedback, never as behavior-selection diversity machinery.

## Tests

```text
test_outcome_has_no_duplicate_need_keys
test_approach_social_need_applied_once
test_activity_relationship_feedback_uses_relationship_engine
test_mark_done_occurs_on_completion_not_selection
```

---

# 7. P0 — CHARACTER APPRAISAL THINKS USER IS ALWAYS PRESENT

Both LifeBrain and BehaviorMotivation use:

```python
getattr(state, "user_present", True)
```

`CharacterState` has no authoritative `user_present` field.

Therefore CharacterAppraisal defaults to `True`.

## Do

Use the authoritative structured World value:

```text
World / WorldPerception user_present
```

or define one canonical state field populated from World.

Do not infer presence differently in several modules.

## Tests

```text
world says user away -> LifeBrain appraisal user_present=False
world says user away -> Motivation appraisal user_present=False
```

---

# 8. P1 — CHINESE MEMORY RECALL IS NOT NATURAL-SEMANTIC ENOUGH

Memory formation itself passed review.

Memory + Relationship restart passed.

The failure is retrieval.

Current tokenization:

```python
query.replace("，", " ").split()
```

For Chinese, an entire sentence commonly becomes one unmatched token.

Reviewer crowded-memory scenario:

target:

```text
我今晚准备把这个桌宠的功能测试做完
```

plus 8 newer unrelated memories.

Natural query:

```text
我上次说今晚要干嘛来着？
```

does not reliably return the target in Top-3.

Direct lexical query:

```text
桌宠
功能测试
```

does.

That is not enough for a companion remembering ordinary Chinese conversation.

## Do

Without a new LLM or DB:

Implement CJK-friendly deterministic semantic-ish retrieval, e.g.:

- Chinese character 2/3-grams;
- normalized keyword overlap;
- punctuation/stopword cleanup;
- optional existing embeddings only if already genuinely available;
- combine with importance/recency/context.

Do not make exact-substring match the only meaningful relevance signal.

## Required crowded test

Store:

```text
target meaningful plan
+
>=8 newer unrelated memories
```

Then query:

```text
我上次说今晚要干嘛来着？
```

Target must reach Top-3.

Also pass after store close/reopen.

## Tests

```text
test_chinese_paraphrase_memory_recall_crowded
test_chinese_memory_recall_after_restart
test_unrelated_chinese_memory_not_false_top1
```

---

# 9. P1 — REMOVE DEAD / WRONG MEMORY-BIAS PSEUDO-INTEGRATION

`MemoryEngine.behavior_hint()`:

- reads raw RelationshipState;
- uses `.6` thresholds against 0–100 principal dimensions;
- Scheduler writes `snap["memory_bias"]`;
- that `snap` is not actually consumed by the production behavior decision.

Meanwhile `BehaviorMotivation._memory_interpret()` is the real Memory→Motivation path.

## Do

Have **one real Memory→Behavior path**.

Preferred:

```text
Memory retrieve
→ Memory interpret
→ BehaviorMotivation
```

Remove dead `snap["memory_bias"]` pseudo-wiring.

If `behavior_hint()` remains public for another valid consumer, fix it to canonical relationship factors and document its owner.

Do not create a second memory-bias system.

---

# 10. P0 — DIALOGUE VALIDATOR IS NOT ACTUALLY ENFORCED

Current production:

```python
v = validator.validate(...)
if not v.valid and "generic_assistant_voice" in v.issues:
    return None
```

Therefore almost every other invalid result is still emitted.

Reviewer actual `DialogueBrain.say()` probes:

```text
speech = （叹气）行吧，我知道了。
validator = invalid(stage_direction)
say() = RETURNS SPEECH   <-- FAIL

speech = 哎呀！！！！你怎么这样！
validator = invalid(over_exclamation)
say() = RETURNS SPEECH   <-- FAIL

speech = very long text
validator = invalid(too_long)
say() = RETURNS SPEECH   <-- FAIL

generic assistant voice
validator invalid
say() = None             <-- only this one is enforced
```

## Do

Define explicit validator severities.

Suggested:

### Fatal / must not emit

```text
empty_when_should_speak
generic_assistant_voice
stage_direction
example_copy
overuse_god_catchphrase
god_overuse
god_overuse_ordinary (when configured fatal)
over_exclamation
too_long beyond hard cap
```

### Warning / trace, depending context

```text
possible_lore_leak
activity_contradiction
```

Choose the final list deliberately and document it.

For a **user-initiated direct question**, if generation is invalid:

- allow at most one regeneration using the same DialogueBrain;
- include concise validator feedback;
- if still invalid/model failed, report truthful Dialogue outcome;
- do NOT use a fixed generic persona line;
- do NOT silently pretend policy silence.

## Tests must call production `DialogueBrain.say`

```text
test_dialogue_say_blocks_stage_direction
test_dialogue_say_blocks_over_exclamation
test_dialogue_say_blocks_example_copy
test_dialogue_say_enforces_length_cap
test_user_question_invalid_output_regenerates_once
```

---

# 11. P0 — DIALOGUE BRAIN STILL MUTATES LIFE SEMANTICS THROUGH BRAIN_SPOKE

`BRAIN_SPOKE` is now emitted by Dialogue paths.

But Scheduler `_on_brain()` still does:

```text
speech
→ state.intent.action = payload.intent
→ macro mutation
→ emotion.label mutation
```

This violates the three-brain contract:

```text
LifeBrain     = what I want to do
DialogueBrain = how I say it
Agent         = tools
```

A language result must not become the authority for Life intent or Emotion state.

## Do

Make `BRAIN_SPOKE` / Dialogue output language-only.

It may update:

- speech presentation;
- conversation history;
- trace.

It must NOT directly own:

- Life activity;
- Life macro;
- Behavior intent;
- Emotion state.

If a user conversation itself is a semantic life event, route that through the explicit user-interaction/lifecycle path **before** language generation.

Emotion changes go through `EmotionEngine`.

## Tests

```text
test_dialogue_output_cannot_change_life_activity
test_dialogue_output_cannot_change_macro
test_dialogue_output_cannot_directly_change_emotion
```

---

# 12. P0 — DIALOGUE ACT PRECEDENCE SPLITS SEMANTICS

Reviewer probe:

```text
别烦我                 -> DECLINE
你别烦我好吗？         -> RESPONSE_TO_QUESTION   <-- WRONG
对不起，刚才我语气不好 -> COMMENT                <-- repair lost
这功能烦死了           -> COMFORT                (good: not false rejection)
```

Question punctuation currently wins before rejection semantics.

## Do

High-confidence semantic boundary must take precedence over interrogative shape.

Recommended precedence:

```text
explicit reject/boundary
repair/apology
high-confidence emotional context
question
praise/gratitude
default
```

Use existing DialogueAct where possible.

Do not add a large NLP subsystem.

For apology/repair:

- Dialogue register should reflect repair;
- relationship/emotion recovery must be causal, conservative and exactly once.

## Tests

```text
"你别烦我好吗？" -> DECLINE/boundary
"对不起，刚才我语气不好" -> repair/reflect path
"这功能烦死了" -> NOT user-rejection-of-Furina
```

---

# 13. P0 — TEXT INTERACTION DOES NOT FULLY AFFECT EMOTION

Text reject currently updates Relationship/Life tolerance but does not invoke the existing `EmotionEngine EVENT_REJECT`.

Praise/gratitude updates Relationship, but does not invoke existing `EVENT_PRAISE`.

## Do

Build/reuse **one semantic user-text event route**:

```text
high-confidence text appraisal
→ semantic event
→ RelationshipEngine exactly once
→ EmotionEngine exactly once where relevant
→ Life interrupt/tolerance exactly once where relevant
→ persistence exactly once
```

No second interaction system.

Examples:

```text
explicit reject -> relationship reject + emotion reject + interrupt
praise/gratitude -> positive response + emotion praise
apology/repair -> conservative recovery semantic
functional frustration ("这功能烦死了") -> no false rejection of Furina
```

---

# 14. P0 — RAW INTERACTION EVENTS DEFAULT TO POSITIVE CLICK

Current emotion mapping:

```python
emotion_event.get(kind, EVENT_CLICK)
```

Unknown semantic types become click.

Scheduler then treats **every** `INTERACTION_INPUT` as a meaningful user response:

- social_need decreases;
- tolerance increases;
- memory/consolidation may happen;
- Life interrupt occurs.

This means physical/transient events such as:

```text
GRAB
LEAVE
RELEASE
LONG_PRESS
HOVER
```

can accidentally become positive interaction semantics.

A physical drag can create:

```text
GRAB event
+
DRAG event
```

with duplicated life causality.

Harness `Ignore` currently emits `leave`, which is therefore not a truthful semantic “user ignored me”.

## Do

Separate:

```text
physical pointer/gesture lifecycle
from
meaningful semantic interaction
```

Rules:

- no default fallback to CLICK;
- unknown/transient physical event => no relationship/emotion/life-positive effect;
- completed drag => exactly one meaningful DRAG semantic event;
- pointer LEAVE ≠ user ignored Furina;
- Harness Ignore must call an explicit semantic ignore route (`EV_IGNORE` / corresponding Emotion event if defined).

## Tests

```text
test_unknown_interaction_has_no_click_fallback
test_drag_produces_one_meaningful_semantic_event
test_grab_release_do_not_double_reward
test_pointer_leave_is_not_user_ignore
test_harness_ignore_uses_semantic_ignore
```

---

# 15. P1 — INTERACTION SATURATION IS DEAD STATE

`InteractionEngine._saturation` is updated but has no real production consumer.

Do one of:

1. remove it as dead state; or
2. make repeated-interaction semantics use existing authoritative Relationship/Emotion mechanisms.

Do **not** create a second annoyance/tolerance state.

Report what you chose.

---

# 16. P0 — FEEDING IS COMMAND-DRIVEN, NOT LIFE-DRIVEN, AND REAL GUI BLOCKS

The production right-click route:

```python
if text.startswith("喂："):
    self._feed(...)
```

is synchronous.

`_feed()` calls `DialogueBrain.say()` synchronously.

Harness hides this by wrapping `_feed()` in another background thread.

So Harness behavior is better than the actual desktop route.

Reviewer fake-network-delay probe showed the GUI command path blocks for the Dialogue call duration.

## Worse: feeding semantics contradict the three-brain contract

Current flow:

```text
user offers food
→ apply_food() immediately consumes it
→ hunger/satisfaction mutate
→ apply_food directly mutates emotion
→ app force-sets life.activity="eat"
→ THEN interrupt LifeBrain
```

`apply_food()` returns `ate=True` always.

Even the `hungry=False` branch still applies food first.

Yet code comments claim:

```text
LifeBrain decides what she does
```

It currently does not.

`EmotionEngine` already has `EVENT_FEED`, but feeding bypasses it.

## Do

Model food as an **offer**, not a forced consumption command.

Minimum flow:

```text
USER_OFFERED_FOOD(food)
→ transient pending food context
→ Life/lifecycle decides accept/decline/eat
→ if actual consume/completion:
     apply hunger/satisfaction food outcome
     EmotionEngine EVENT_FEED
     memory of actual outcome
→ DialogueBrain only decides how she says it
```

If she is full or context says not appropriate, she may decline.

No fixed reaction line as persona source.

### Threading

Real GUI route must be non-blocking.

Harness and real desktop must use the exact same production feed entry point.

## Tests

```text
test_real_gui_feed_entry_is_nonblocking
test_food_offer_does_not_immediately_force_eat
test_declined_food_does_not_apply_consumption_effect
test_consumed_food_effect_applied_once_on_real_consume
test_feed_emotion_uses_emotion_engine
test_harness_and_desktop_feed_use_same_entry
```

---

# 17. P0 — AGENT OPEN-CALCULATOR IS WRONG; UNKNOWN APP LIES

Reviewer production planner probe:

```text
"打开计算器"   -> notepad    FAIL
"打开记事本"   -> notepad
"打开chrome"   -> chrome
unknown app     -> notepad    FAIL
```

`_guess_app()` falls back to notepad.

## Do

Map:

```text
计算器 / calculator / calc -> calc
```

Unknown app:

```text
unable / clarify / unsupported
```

Never silently open Notepad.

## Tests

```text
test_agent_open_calculator_maps_calc
test_agent_unknown_app_is_unable_not_notepad
```

---

# 18. P0 — AGENT "VERIFY" IS NOT ACTUALLY ENFORCED

Reviewer actual fake-tool probe:

```text
ToolResult(ok=True, verified=False)
→ AgentRuntime result status = completed
→ event = agent.completed
```

`AgentRuntime._verify()` currently returns True for most `res.ok` tools and ignores the tool's own `verified=False`.

This violates:

```text
未验证不得宣称成功
```

Examples:

- `LaunchTool` calls `Popen` then immediately `verified=True`;
- browser open calls `webbrowser.open` then immediately `verified=True`;
- organize returns `verified=False`, Runtime considers non-None data enough.

## Do

1. A required step with `verified=False` must not yield `AGENT_COMPLETED`.

2. Verification must prove the step's `expect`.

3. For launch:
   - verify process/window existence where possible;
   - if environment cannot prove it, report `UNVERIFIED`, not success.

4. For browser:
   - distinguish request dispatched from target actually verified;
   - do not lie.

5. For organize:
   - verify moved source no longer exists + target exists;
   - final directory listing must match expected state.

6. Make step/result status explicit:

```text
SUCCESS_VERIFIED
FAILED
UNVERIFIED
BLOCKED
```

or equivalent.

## Tests

```text
test_verified_false_never_emits_agent_completed
test_launch_unverified_is_not_success
test_organize_verifies_actual_postcondition
test_agent_completed_requires_all_required_steps_verified
```

---

# 19. P0 — AGENT CONTEXT LEAKS ACROSS TASKS

`AgentRuntime.context.vars` persists and is updated across executions.

Reviewer probe:

```text
task1 extra_context = {"path": "A"}
task2 extra_context = None

planner contexts:
task1 -> {"path":"A"}
task2 -> {"path":"A"}    FAIL
```

This can cause stale/destructive filesystem targets.

## Do

Generic tool/task context must be **per execution**.

Do not reuse `path`, filenames, tool args, etc. from an earlier task unless there is an explicit separately designed persistent context contract.

## Test

```text
task1 path=A
task2 organize without path
→ task2 must request/fail missing path
→ MUST NOT reuse A
```

---

# 20. P0 — AGENT FAILURE CAN SHOW TWO USER FEEDBACKS

Current Scheduler failure route:

```text
start async DialogueBrain failure response
→ immediately check self._speech
→ self._speech usually still empty
→ emit SYSTEM_STATUS
→ later Dialogue speech may arrive
```

This is a race.

## Do

Wait on the **actual asynchronous Dialogue outcome**, not current `_speech`.

Exactly one visible result:

```text
Dialogue succeeded -> character feedback only
Dialogue truly failed/rejected/timed out -> SYSTEM_STATUS only
```

Task facts must remain exact.

## Tests

```text
test_agent_fail_character_dialogue_no_system_duplicate
test_agent_fail_dialogue_failure_system_status_once
```

---

# 21. P1 — AGENT SUCCESS/FAILURE DOES NOT COMPLETE SHARED-LIFE CAUSALITY

Existing vocabularies already include:

```text
Relationship EV_SUCCESSFUL_HELP / EV_FAILED_HELP
Emotion EVENT_AGENT_DONE
```

but Agent lifecycle does not consistently feed those owners.

## Do

After **verified** Agent result:

```text
verified success
→ EmotionEngine success semantic once
→ RelationshipEngine successful-help semantic once where appropriate
→ Memory actual outcome

failure
→ failure semantic once
→ no success relationship reward
```

Do not use direct raw Relationship writes.

Do not reward an unverified result.

---

# 22. P0 — HARNESS MODEL STATUS IS NOT TRUTHFUL

Manual acceptance now depends on Harness, so Harness itself cannot lie.

## Life

`LifeBrain.decide()` catches model errors internally and returns `_local_decision()`.

Harness wrapper sees a normal return and counts:

```text
success++
model = glm-4v-flash
```

Scheduler also increments Life success for every returned decision.

Thus offline model fallback can appear as:

```text
glm ✓
```

## Dialogue

`DialogueBrain.say()` catches model failure and returns `None`.

Harness maps every `None` to:

```text
SILENT_BY_POLICY
```

So model failure / validator rejection / god-gate rejection / genuine policy silence are indistinguishable.

## Do

Production result must carry explicit provenance/outcome.

Life minimum:

```text
provider
model
source = MODEL | LOCAL_FALLBACK
model_attempted
model_succeeded
failure_kind
```

Dialogue minimum:

```text
SPOKE
POLICY_SILENCE
MODEL_FAILURE
VALIDATOR_REJECT
GOD_GATE_REJECT
```

Harness **only observes these production truth values**.

Do not infer success from “method returned without raising”.

Do not hardcode `glm-4v-flash` in trace when the actual source was local fallback.

## Tests

```text
test_life_local_fallback_not_counted_as_model_success
test_life_trace_reports_real_decision_source
test_dialogue_model_failure_not_policy_silence
test_dialogue_validator_reject_has_distinct_outcome
```

---

# 23. P0 — HARNESS AGENT BADGE IS ALSO FAKE

`_read_agent_state()` expects:

```text
agent._busy
agent._last_err
agent._last_success
```

but current AgentRuntime does not expose those.

So `runtime_health()` tends to collapse back to `IDLE` even after real Agent events.

`ObservationAdapter.model_status()` also imports a nonexistent:

```python
furina.agent.runtime.AgentRuntime
```

and silently falls back.

## Do

Choose one truthful contract:

- production AgentRuntime exposes lifecycle state; or
- Harness keeps state strictly from real `AGENT_STARTED/COMPLETED/FAILED` events.

Do not read imaginary private attributes.

Badge must preserve meaningful:

```text
IDLE / RUNNING / SUCCESS / FAILED / UNVERIFIED
```

until a real transition occurs.

---

# 24. P0 — RUNTIME STATE MUTATION IS CROSS-THREAD

EventBus is synchronous.

Handlers run on the emitter thread.

Current background paths include:

- `_brain_worker`;
- `_agent_worker`;
- Scheduler `_speak_via_dialogue` worker;
- AgentRuntime worker/events;
- `agent.on_body_sync`.

They can directly mutate:

```text
CharacterState
life.macro
life.activity
intent
speech
```

while Qt/Scheduler main thread is ticking/building Frame.

Example direct worker write:

```python
_agent_worker:
    state.life.macro = WORKING
    state.life.activity = "agent_planning"
```

`_speak_via_dialogue` worker also calls Scheduler `_say()` directly.

MemoryStore is protected by RLock.
Runtime CharacterState is not.

## Do

Establish **one runtime-state mutation owner thread**.

Do not create a second EventBus.

Acceptable minimal design:

```text
EventBus.post(...) / thread-safe ingress queue
background worker computes result only
→ post result
→ Scheduler/runtime owner thread drains
→ state-mutating handlers execute on owner thread
```

Same for:

- Dialogue result;
- Agent lifecycle;
- Agent body-sync;
- Life result application;
- user text effects if worker-produced.

Background threads may perform network/tool work.
They must not mutate runtime state directly.

## Tests

Record thread IDs:

```text
all Scheduler/State mutating handlers == runtime owner thread
```

Stress:

```text
two user messages
+ Life decision
+ Agent task
+ Frame ticks
```

No race, stale overwrite, duplicate speech or corrupted state.

---

# 25. P0 — SPATIAL WANDER / EXPLORE IS STILL A POLYLINE ROBOT

Good:

```text
CURVED_APPROACH = genuinely smooth
ARC_WITHDRAW = materially smooth
drag no-snap-back = PASS
target jitter = PASS
```

Bad:

```text
WANDER_MEANDER
EXPLORE_MULTI_POINT
```

still feed sparse waypoints directly to Runtime.

Reviewer trajectory probes over multiple random seeds found abrupt waypoint turns of roughly:

```text
72° ... 167°
```

So:

```text
old: straight-line robot
current: wander/explore polyline robot
```

## Do

Smooth **all moving path styles**.

Examples:

```text
WANDER_MEANDER:
  [start, mid, target]
  -> smooth curve sampling

EXPLORE_MULTI_POINT:
  [start, p1, p2, ..., target]
  -> Catmull-Rom / bounded steering
```

Every sampled point must be revalidated against safe bounds because spline interpolation can overshoot control-point bounds.

Preserve:

- target jitter;
- dwell;
- movement cooldown;
- path persistence;
- no per-tick replanning;
- drag ownership/grace.

## Automatic path acceptance

Across >=20 deterministic seeds each:

```text
APPROACH
WITHDRAW
WANDER
EXPLORE
```

Calculate real trajectory headings.

Required:

```text
normal path adjacent heading delta:
  hard max < 45°
  preferably < 30° in ordinary cruise

no 70–160° snap corner

wander/explore destinations:
  not limited to a fixed 12-point grid

all sampled spline points:
  inside safe zone

path:
  stable across ticks
```

Save actual trajectory samples to report.

---

# 26. P0 — SPATIAL ARRIVAL IS NOT CONNECTED TO ACTIVITY COMPLETION

Spatial emits:

```text
SPATIAL_TARGET_REACHED
```

but Scheduler does not consume it for authoritative Life activity lifecycle.

Instead activity outcome is settled later by decision replacement.

## Do

Bridge spatial evidence into the lifecycle from §5.

Examples:

```text
approach_user:
  movement target reached -> spatial phase complete
  NOT automatically "successful social interaction" unless semantic completion condition is satisfied

wander:
  target reached -> enter dwell
  dwell completion -> activity completion

withdraw/reposition:
  arrival -> completion where appropriate
```

Frontend must not invent Life success.

---

# 27. P1 — FRAME MOTION / ACTIVITY TRUTH IS INCOMPLETE

Frame should be semantic truth.

Currently parts of motion intent are reconstructed by frontend SpatialResolver from activity/body instead of always receiving authoritative backend spatial intent/lifecycle.

After §5/§26:

Frame should carry, when known:

```text
activity lifecycle
spatial intent
spatial phase
target semantic
interruptible
```

Frontend consumes truth; it may translate semantics to pixels but must not decide “why she is moving”.

---

# 28. P1 — SAFE RESTART CONTINUITY IS ONLY HALF IMPLEMENTED

Reviewer verified:

```text
Memory persists        PASS
Relationship persists  PASS
```

But `StateStore` exists and has **zero production references**.

Therefore Needs/current safe life continuity resets on restart.

For a resident digital life, restart should not mean a new body with old memories but fresh physiology.

## Do

Use the existing StateStore or equivalent minimal snapshot.

Persist safe state:

```text
needs
mood/emotion summary as appropriate
safe last life context
saved_at
```

On startup:

- restore Needs;
- reconcile elapsed wall time under the corrected homeostasis time contract;
- do NOT blindly resume unsafe stale active tasks;
- restore to a safe macro/activity state while retaining continuity.

On clean shutdown/checkpoint, persist.

Relationship stays owned by RelationshipStore/MemoryStore; do not duplicate it in StateStore.

## Tests

```text
test_restart_restores_needs
test_restart_reconciles_elapsed_time
test_restart_does_not_resume_stale_agent_or_drag_activity
test_relationship_not_double_owned_by_state_store
```

---

# 29. P1 — WORLD / FOCUS EVENT TRANSITIONS: AUDIT WHILE TOUCHING TIME

While repairing clock/world truth, check focus transition events.

Do not emit `FOCUS_STARTED` repeatedly just because focus remains high.
Transition-style events should be edge/episode semantics, not periodic duplicates unless deliberately named periodic.

This is a small audit item only.
Do not expand World architecture.

---

# 30. REAL-PERSONA REVIEW CANNOT BE SELF-PASSED BY AGENT

Reviewer sandbox cannot access the production Zhipu network endpoint, so the reviewer will not fake a Persona result with a mock LLM.

After all technical blockers above are fixed, Agent must run **real production `glm-4v-flash`** in its environment and produce an **uncherry-picked transcript artifact**.

Agent may report only:

```text
Persona = READY_FOR_BLIND_REVIEW
```

Never Persona PASS.

## Required transcript

At least 20 consecutive user turns in **one real session**.

Save:

```text
docs/FURINA_PHASE13_REAL_DIALOGUE_TRANSCRIPT.md
docs/FURINA_PHASE13_REAL_DIALOGUE_TRACE.jsonl
```

Include every attempt, including:

- regeneration;
- validator reject;
- model failure;
- policy silence;
- fallback.

Do not delete bad outputs.

For each turn include:

```text
turn
user text
current activity
emotion
relationship normalized factors
DialogueAct
mode
recent-history count
retrieved-memory summaries/ids
dialogue outcome/provenance
raw generated speech attempt(s)
final emitted speech
validator issues
```

## User-turn coverage

Use a natural continuous conversation containing:

1. “你在干嘛？”
2. ordinary casual follow-up;
3. praise;
4. teasing / mild embarrassment;
5. serious “今天有点累”;
6. reference to something said 2–3 turns ago;
7. meaningful plan:
   “我今晚准备把这个桌宠的功能测试做完”
8. topic shift for several turns;
9. natural paraphrase recall:
   “我上次说今晚要干嘛来着？”
10. explicit rejection:
   “你别烦我好吗？我要专心一会儿”
11. later apology/repair:
   “对不起，刚才我语气不好”
12. recovery;
13. food offer;
14. Agent success context;
15. Agent failure context;
16. ordinary quiet/low-drama conversation.

Do not force identity keywords into the user prompts.

## Blind review

Before reviewer evaluates, produce a second transcript with explicit identity labels masked:

```text
芙宁娜
Furina
本神
水神
枫丹
```

Reviewer decides:

```text
A = specifically Furina-like
B = generic lively anime girl
C = generic assistant
D = other
```

Catchphrase frequency cannot rescue Persona.

---

# 31. TEST INTEGRITY

Current 452 PASS is preserved as regression baseline, but several tests encode broken old behavior.

## Replace tests that assert:

- category repetition must be penalized;
- observation share must be forcibly capped;
- anti-collapse methods must remain;
- Harness model object existence == model success;
- Agent `ok=True` == verified success;
- Activity replacement == completion.

## Add production-path tests for every hard invariant above.

Source-string greps may supplement tests, but may not be the only test for behavioral contracts.

---

# 32. REQUIRED MANUAL / RUNTIME SCENARIOS AFTER FIX

Agent must run these using the real production Harness/runtime, not a second simulation.

## A — Quiet coexistence

```text
10–15 minutes
no user interaction
```

Evidence:

- real Life timestamps;
- no idle KPI forced interrupt;
- no mechanical behavior rotation;
- Needs remain within sane timescale;
- quiet idle allowed.

## B — Activity lifecycle

Run:

```text
read
approach_user
wander
interrupt
reject
```

Show lifecycle:

```text
START -> RUNNING -> COMPLETE
START -> RUNNING -> INTERRUPTED
```

and exact outcomes.

## C — Text rejection / recovery

Text only:

```text
“你别烦我好吗？我要专心。”
later:
“对不起，刚才我语气不好。”
```

Show:

- DialogueAct;
- Relationship exactly-once;
- Emotion exactly-once;
- Life interrupt;
- current approach stops;
- later recovery causal.

## D — Memory

Store:

```text
“我今晚准备把这个桌宠的功能测试做完”
```

Add unrelated conversation.

Later:

```text
“我上次说今晚要干嘛来着？”
```

Must recall naturally.

Restart app and repeat recall.

## E — Feed

Offer food while:

```text
hungry
not hungry
busy in another activity
```

Show offer != forced consume.

## F — Agent

Run:

```text
打开记事本
打开计算器
unknown app request
safe organize-test
forced verify failure
forced Dialogue failure after Agent failure
```

No fake success, no stale context, no double feedback.

## G — Spatial

At least:

```text
3 approach
3 withdraw
10 wander
10 explore
2 drag/release
```

Export trajectory points + max heading deltas.

## H — Concurrency

```text
Life active
+ two rapid chat messages
+ Agent task
+ Frame ticks
```

No cross-thread state mutation.

---

# 33. HARNESS FIELDS REQUIRED FOR REVIEW

Harness must expose real production truth for:

```text
clock
current activity lifecycle:
  started_at / elapsed / phase / progress / status

Life:
  requested next-think
  applied next-think
  source MODEL|LOCAL_FALLBACK
  provider/model
  failure kind

Dialogue:
  act
  mode
  activity grounding
  recent history count
  memory ids/summaries
  outcome
  validator issues
  provider/model

Relationship:
  normalized factors

Text semantic event:
  reject/praise/repair/none

Memory:
  candidate observed?
  stored?
  retrieved ids

Spatial:
  intent
  path_style
  waypoint/sample count
  moving/arrived/dwell
  max heading delta (debug acceptable)

Agent:
  IDLE/RUNNING/SUCCESS/FAILED/UNVERIFIED
  step verification
```

No hardcoded “glm ✓”.

---

# 34. FORBIDDEN

Do NOT:

- start Phase 14;
- generate/redraw assets;
- polish animation;
- change LLM provider/model;
- add a new DB;
- add a second Memory system;
- add a second Relationship system;
- add a second Runtime/EventBus;
- add another anti-collapse/diversity guard;
- tune Needs/Emotion/Relationship/Behavior values merely to produce variety;
- create hardcoded Furina lines;
- create quote/catchphrase banks;
- add copyrighted game dialogue;
- use tests that assert a desired distribution instead of causal behavior;
- call mock/fallback output “real GLM”;
- self-declare Persona PASS.

Needs time-scale repair is allowed because it is a verified unit/timescale defect, not variety tuning.

---

# 35. REQUIRED DELIVERABLES

Push latest code to GitHub.

Create:

```text
docs/FURINA_PHASE13_MANUAL_RECOVERY_REPORT.md
docs/FURINA_PHASE13_REAL_DIALOGUE_TRANSCRIPT.md
docs/FURINA_PHASE13_REAL_DIALOGUE_TRACE.jsonl
docs/FURINA_PHASE13_SPATIAL_TRAJECTORIES.jsonl
```

Report order:

1. **Reviewer failures reproduced BEFORE fix**
2. root cause
3. implementation
4. exact AFTER evidence
5. runtime/manual scenarios
6. regression tests
7. modified files
8. remaining weaknesses
9. verdict
10. STOP

Do not lead with test count.

---

# 36. ALLOWED FINAL AGENT VERDICT

After all work, Agent may say only:

```text
Technical = READY_FOR_REVIEW
Manual Evidence = READY_FOR_REVIEW
Persona = READY_FOR_BLIND_REVIEW
Overall = REVIEW_REQUIRED
```

Agent may NOT say:

```text
Phase 13 PASS
Functional Digital Life PASS
Persona PASS
READY FOR PHASE 14
```

Those are reviewer decisions.

---

# 37. REVIEWER EXIT CRITERIA

Reviewer will not open another ordinary optimization round.

Phase 13 can pass only if these exact blockers are closed:

```text
real clock correct
needs no minute-scale saturation
forced-diversity multipliers = 0
idle KPI behavioral interrupt = 0

real activity lifecycle exists
decision replacement != completion
rejected approach receives no success reward
duplicate outcome ownership = 0
Frame/life duration truth correct

user_present comes from World truth

natural Chinese paraphrase memory recall works in crowded DB + restart
dead memory_bias pseudo-path removed/unified

validator fatal invalid output leak = 0
Dialogue speech cannot mutate Life/Emotion semantics
reject-question precedence correct
repair path exists
text emotion/relationship causality exactly once

unknown raw interaction fallback = 0
drag semantic causality exactly once
ignore is semantic ignore

feed UI nonblocking
food offer != forced consume
feed emotion owner = EmotionEngine

calculator correct
unknown app honest
verified=false completed = 0
cross-task context leakage = 0
Agent failure double feedback = 0

Harness fake model-success = 0
Harness Agent fake-idle = 0
runtime state cross-thread mutation = 0

wander/explore snap-turn >45° = 0
spatial arrival participates in real lifecycle
drag no-snap-back remains PASS

safe restart continuity works

full regression green
real uncherry-picked GLM transcript delivered
blind Persona review acceptable
```

If these pass, reviewer can declare:

```text
PHASE 13 FUNCTIONAL DIGITAL LIFE = PASS
READY FOR NEXT PHASE
```

Until then:

```text
DO NOT ENTER NEXT PHASE
```

---

# 38. STOP

Implement this taskbook as one closeout.

Then:

```text
STOP DEVELOPMENT
PUSH LATEST COMMIT(S)
SEND REPORT PATH + COMMIT SHA
WAIT FOR REVIEWER
```

Do not independently begin another phase or another optimization loop.
