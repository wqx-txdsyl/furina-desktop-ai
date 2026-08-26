# Phase 13C — Digital Life Experience Recovery

> **Status before Phase 13C**
>
> - Phase 13 Technical Integration: PASS
> - Phase 13 Manual Functional: **FAIL / PARTIAL**
> - Functional Digital Life: **NOT PASSED**
> - Assets: DEFERRED
> - Backend semantic parameters: frozen unless explicitly allowed below
>
> **First manual evidence**
>
> 1. Desktop movement is visibly mechanical: almost all `approach / wander / play / withdraw` movement is straight-line or diagonal straight-line motion.
> 2. Dialogue has almost no Furina-specific recognizability; without the name, it could plausibly be a generic Chinese assistant/chatbot.
>
> These two failures are sufficient to reopen the functional-experience layer. Do **not** start Phase 14.

---

# 0. Phase 13C Objective

This phase has exactly three goals:

```text
A. NATURAL SPATIAL MOTION
B. CHARACTER-IDENTIFIABLE DIALOGUE
C. REAL CONVERSATIONAL CAUSALITY
```

The phase is complete only when the **asset-free rectangle Harness** feels like a specific digital life rather than:

```text
generic chatbot
+
state dashboard
+
straight-line desktop navigator
```

This is **not** a visual asset phase.

---

# 1. Scope Freeze

## Allowed

Only changes required to close the following confirmed experience failures:

```text
Spatial path naturalness
Life cadence / forced variety
DialogueAct routing
Dialogue prompt grounding
Short-term conversation continuity
Conversational memory observation
Text → interaction meaning
Relationship scale contract
Furina linguistic identity
Dialogue repetition / silence bug
```

Narrow wiring changes are allowed where required.

## Forbidden

Do **not**:

```text
start Phase 14
generate / redraw assets
add walk / drag PNG
change animation aesthetics
add a new LLM
add a new DB
rewrite the full Life Simulation
retune Needs rates
retune Emotion decay globally
retune Relationship event deltas arbitrarily
retune Behavior weights just to create diversity
add another anti-collapse system
add forced behavior rotation
add fake random personality lines
add a quote bank
add copyrighted game dialogue
add Furina catchphrases as a substitute for characterization
```

No “tests green therefore PASS”.

---

# 2. Evidence Priority

Phase 13C evidence order:

```text
1. REAL USER EXPERIENCE
2. REAL PRODUCTION RUNTIME TRACE
3. COUNTERFACTUAL / CAUSAL TEST
4. AUTOMATED REGRESSION
```

The report must begin with real production evidence, not test totals.

---

# PART A — NATURAL SPATIAL MOTION

# 3. Root Problem

Current movement effectively performs:

```text
direction = normalize(target - current)
position += direction * step
```

Therefore every trip is geometrically a straight segment.

Current `MovementPlan` only expresses roughly:

```text
start
target
speed
arrival
```

It does not express **how** the character travels.

Different intents such as:

```text
APPROACH
WITHDRAW
WANDER
PLAY / EXPLORE
REPOSITION
```

therefore collapse into the same body language with different destinations.

This must be fixed at the semantic spatial-runtime level, not with animation assets.

---

# 4. Add Path Semantics

Introduce one production spatial-path representation, e.g.:

```python
MotionPath / SpatialPath
```

It may contain equivalent fields such as:

```text
start
target
waypoints
path_style
speed_profile
arrival_radius
created_at
```

Do not require the exact names above.

The runtime must follow a planned path rather than recomputing a direct vector to the final target every tick.

---

# 5. Required Path Styles

At minimum support semantic differences equivalent to:

```text
DIRECT_SOFT
CURVED_APPROACH
ARC_WITHDRAW
WANDER_MEANDER
EXPLORE_MULTI_POINT
REPOSITION_SHORT
```

Do not use these names if a cleaner design exists.

The key requirement:

> Different spatial intents must create observably different travel geometry.

---

# 6. Approach

`APPROACH` must not always be a ruler-straight line.

Expected behavior:

```text
current
  → mild lateral / curved route
  → safe near-user zone
  → decelerate
  → settle
```

Constraints:

```text
never orbit theatrically around the user
never zig-zag for decoration
never enter the user's active work center if avoidable
```

The path should look like a person casually moving closer, not a homing missile.

---

# 7. Withdraw

`WITHDRAW` must feel meaningfully different from approach reversed.

Expected:

```text
brief turn-away / lateral displacement
→ create distance
→ settle
```

Do not simply:

```text
target = farther point
straight line to target
```

---

# 8. Wander

Wander must be:

```text
move
→ dwell
→ possibly reorient
→ move later
```

not:

```text
continuous patrol
```

Do not select from a visibly fixed low-resolution grid only.

Target generation should include bounded stochastic variation while respecting screen safety.

The same session should not repeatedly visit the exact same obvious grid coordinates unless causally justified.

---

# 9. Explore / Play

If `play` / `explore` have spatial expression:

They must not be identical to `approach_user`.

An explore-like movement may use:

```text
2–3 bounded intermediate points
variable dwell
small heading changes
```

Do not make it hyperactive.

---

# 10. Path Persistence

A path must remain stable during execution.

Forbidden:

```text
re-plan every frame
re-randomize every tick
target jitter
micro-zigzag
```

Re-plan only for a real reason:

```text
user drag
screen/work-area change
new high-priority spatial intent
target becomes invalid
collision/safety invalidation
```

---

# 11. Movement Timing

Movement must remain `dt` based.

Do not restore fixed-pixel-per-tick movement.

Retain:

```text
speed caps
screen bounds
safe zones
arrival hysteresis
drag ownership
```

---

# 12. Drag Ownership

Manual drag remains highest temporary spatial owner.

Required:

```text
DRAG_START
→ autonomous path cancelled/suspended

DRAG_MOVE
→ proxy follows user

DRAG_END
→ position committed
→ grace period
→ no immediate snap-back
```

Phase 13C must not change this into a visual drag system.

---

# 13. Natural Motion Acceptance

Using the rectangle proxy, manually observe at least:

```text
3 APPROACH trips
3 WITHDRAW trips
5 WANDER / EXPLORE trips
2 manual drag/release cycles
```

PASS only if a human observer can distinguish:

```text
approach
withdraw
wander/explore
```

from movement alone better than chance.

If every movement still looks like:

```text
A → B straight line
```

Spatial = FAIL.

---

# PART B — LIFE CADENCE / AUTONOMY

# 14. Remove Remaining Forced Variety

Production must not contain any active mechanism equivalent to:

```text
same activity repeated N times
→ forcibly replace with another activity
```

The already-disabled Scheduler anti-collapse must stay OFF.

Audit LifeBrain for remaining forced variety such as `_apply_variety(...)`.

If it forcibly replaces a valid decision only to make behavior look diverse:

```text
disable/remove from production decision application
```

Keep historical code only if useful for debt/reference, but it must not affect production selection.

---

# 15. Diversity Must Be Causal

Behavior diversity may come from:

```text
Needs
Emotion
Motivation
Personality
Identity
Relationship
World
Memory
Activity completion
Feasibility
LifeBrain choice
```

Not from:

```text
“we already did read twice”
```

alone.

Repeated behavior is allowed when state supports it.

Example:

```text
read → read
```

is valid if she still wants to read.

---

# 16. Life Decision Cadence

Audit the current forced scheduler window such as:

```text
5–9 seconds
```

if production still clamps LifeBrain reevaluation to this range.

The scheduler must respect the real decision's next-think / activity duration semantics, within sane safety bounds.

Do not let:

```text
LLM: think again in 45s
Scheduler: call again in 9s
```

happen without a real interrupt.

---

# 17. Interrupt-Driven Reevaluation

Life reevaluation may occur early for meaningful events:

```text
user message
touch / poke / reject
feed
Agent request/result
strong world change
Need threshold
activity completion
invalidated feasibility
```

Normal quiet coexistence must not constantly wake LifeBrain for display variety.

---

# 18. Quiet Coexistence Test

Run a real production Harness session with no user interaction.

Record:

```text
decision timestamps
selected activities
reasons
interrupts
activity durations
fallbacks
```

PASS requires:

```text
no fixed-looking 5–9 second behavioral metronome
no forced rotation for diversity
repeated valid activity allowed
meaningful dwell periods exist
```

---

# PART C — DIALOGUE STRUCTURE

# 19. DialogueAct Routing Must Become Real

Current enum richness is meaningless if ordinary conversation collapses to `COMMENT`.

Implement deterministic / hybrid classification so common user input can produce relevant acts, including at minimum:

```text
ANSWER / RESPONSE_TO_QUESTION
ASK
REACT
TEASE
COMFORT
REFLECT
DECLINE / BOUNDARY
COMMENT
```

Do not add another LLM.

Prefer deterministic semantic routing + existing expression/appraisal.

---

# 20. Required DialogueAct Cases

These must not all map to `COMMENT`:

```text
“你在干嘛？”
“你饿不饿？”
“你今天怎么这么安静？”
“你挺可爱的。”
“其实我今天有点累。”
“别烦我，我要忙一会。”
“你觉得我现在应该休息吗？”
“谢谢你。”
```

The exact enum may differ, but the distinctions must be meaningful downstream.

---

# 21. Remove the Same-Act Permanent Silence Bug

Current behavior equivalent to:

```python
if last 3 acts are identical:
    return None
```

must not permanently silence normal multi-turn conversation.

Repetition control may influence:

```text
wording
length
initiative
expression strategy
```

but must **not** turn a user-addressed conversation into indefinite silence solely because the act label repeated.

User-initiated direct questions must generally receive a response unless there is a real failure/safety/character reason.

---

# 22. Activity Grounding

If the current runtime activity is:

```text
read
eat
wander
rest
work_assist
...
```

the Dialogue prompt must receive it explicitly.

Required chain:

```text
Character Runtime
→ current activity
→ Dialogue context
→ prompt
→ response
```

Question:

```text
“你在干嘛？”
```

must be answerable from runtime truth.

Do not hardcode:

```text
if activity == read: say “我在看书”
```

DialogueBrain should generate the response using the real activity context.

---

# 23. Current State Grounding

Dialogue should receive only relevant current state summaries, e.g.:

```text
activity
emotion
relationship factors
world summary
recent interaction context
memory context
user initiated
```

Avoid dumping raw state.

But do not silently omit key grounding such as activity.

---

# PART D — SHORT-TERM CONVERSATION CONTINUITY

# 24. Add Real Short-Term Dialogue Context

Current UI history is not enough if it is display-only.

Implement a small production short-term conversation buffer.

Purpose:

```text
keep continuity across immediate turns
resolve references
avoid repeating introductions
remember what was said moments ago
```

This is **not** a new database.

Use in-memory bounded history.

---

# 25. Buffer Contract

Recommended conceptual content:

```text
role: user / furina
text
timestamp
optional trace/root id
```

Bounded by both:

```text
recent turn count
approximate prompt budget
```

Do not grow unbounded.

---

# 26. Prompt Use

DialogueBrain should receive a compact recent conversation section such as the last useful turns.

Do not feed huge transcripts.

Do not store hidden system prompt text in the history.

---

# 27. Conversation Continuity Acceptance

Real GLM session:

```text
User: 你在干嘛？
Furina: ...

User: 那你看到哪了？
Furina: ...

User: 你刚才不是还说……
Furina: ...
```

The second/third turn must demonstrably use recent conversational context.

Test at least 10–20 turns without reset.

---

# PART E — CONVERSATION → MEMORY

# 28. User Speech Can Become Life Memory

Ordinary user dialogue currently must not remain “text only”.

Add a narrow conversational-memory observation path.

Do **not** save every message blindly.

---

# 29. Memory Candidate Extraction

Use existing deterministic/memory mechanisms where possible.

Store only meaningful user information/events such as:

```text
plans
preferences
commitments
important events
repeated concerns
shared experiences
relationship-relevant statements
```

Do not store:

```text
“嗯”
“哈哈”
“好的”
every casual sentence
```

No new LLM.

If exact semantic extraction is not available, implement conservative rule-based candidate detection and accepted misses rather than over-memory.

---

# 30. Memory Provenance

Conversation-derived memory must identify source/event type appropriately.

It must enter the same existing Memory system, not a second chat-memory database.

---

# 31. Memory Use Acceptance

Real scenario:

```text
User:
“我今晚准备把这个桌宠的功能测试做完。”
```

After unrelated conversation/interactions and a reasonable delay:

```text
User:
“我刚才说今晚准备干嘛来着？”
```

PASS requires:

```text
memory was actually observed/stored OR intentionally retained in valid short-term history
retrieval/history reaches Dialogue
answer uses it accurately
no hallucinated replacement
```

For restart persistence, only long-term memory is expected to survive.

---

# PART F — USER LANGUAGE → INTERACTION CAUSALITY

# 32. Language Must Be Able to Affect the Relationship

Currently buttons may create real events while equivalent words remain pure text.

Implement a conservative user-utterance appraisal layer for **high-confidence** interaction meaning.

Do not attempt full sentiment psychology.

---

# 33. Minimum High-Confidence Utterance Events

Examples that should have causal meaning:

```text
praise / affection
clear rejection / “别烦我”
gratitude
direct apology / repair
clear annoyance
```

Map into existing event vocabulary where possible.

Do not create a parallel Relationship model.

---

# 34. Conservative Threshold

When uncertain:

```text
no relationship event
```

is better than false interpretation.

Examples:

```text
“这功能烦死了”
```

must not automatically mean:

```text
user rejects Furina
```

Context matters.

Keep this system narrow.

---

# 35. Exactly-Once

A user sentence must not cause:

```text
text appraisal relationship event
+
button event
+
scheduler duplicate
```

unless the user genuinely performed multiple actions.

Relationship single owner remains:

```text
RelationshipEngine.apply()
```

exactly once per meaningful event.

Emotion mutation remains through EmotionEngine.

---

# 36. Reject / Recovery Acceptance

Real dialogue only, without pressing the Reject button:

```text
“现在别烦我，我要专心一会。”
```

Expected:

```text
high-confidence rejection meaning
→ real relationship/social context change
→ future initiative / approach affected
```

Later:

```text
“好啦，刚才在忙。”
```

with normal positive interaction should allow recovery.

Do not hardcode exact future behavior.

---

# PART G — RELATIONSHIP SCALE CONTRACT

# 37. Fix 0–100 vs 0–1 Ambiguity

This is a structural correctness issue.

Choose and enforce one explicit boundary:

```text
RelationshipState internal raw scale
```

may remain whatever current engine uses.

But consumers such as:

```text
Dialogue
Embodiment
Motivation
Persona appraisal
```

must receive one documented normalized contract.

Preferred:

```text
RelationshipEngine.factors()
→ normalized 0..1 consumer contract
```

Do not pass raw `state.as_dict()` to systems expecting normalized factors.

---

# 38. No Silent Mixed Units

Audit all production comparisons such as:

```text
trust > 0.6
comfort > 0.6
annoyance > 0.6
trust * 100
```

For every consumer, establish what unit is expected.

Fix production wiring rather than changing thresholds randomly.

---

# 39. user_response_rate / rejection Scale

Audit fields whose declared semantic range is already 0..1 but are later divided by 100, or vice versa.

Fix scale conversion exactly once at the public factor boundary.

Do not retune event deltas merely to compensate for a scale bug.

---

# 40. Scale Tests

Add invariant tests:

```text
normalized relationship factors always in [0,1]
raw state never accidentally enters normalized consumer
0.5 response rate remains ~0.5 after normalization, not .005
equivalent raw states produce equivalent consumer factors
```

---

# PART H — FURINA-IDENTIFIABLE DIALOGUE

# 41. New Persona Goal

Do not optimize for:

```text
“more dramatic than neutral”
```

Optimize for:

> **If identity words are removed, the dialogue still feels specifically like Furina rather than a generic lively female chatbot.**

This is the primary persona criterion.

---

# 42. Do Not Solve With Catchphrases

Forbidden approach:

```text
increase “本神”
add “审判”
add “枫丹”
add Furina name
quote game lines
copy canon dialogue
force exclamation marks
```

These create superficial identity markers.

No copyrighted dialogue bank.

---

# 43. Build a Character Speech Mechanism

Refine the existing Character Contract / persona guidance around **how Furina transforms internal state into language**.

At minimum define mechanisms equivalent to:

```text
1. PERFORMANCE AS CHOSEN SOCIAL TOOL
   She may stage a small performance when wanting control/attention,
   but not constantly.

2. DIGNITY BEFORE DIRECT NEED
   Wants/embarrassment often emerge indirectly before direct admission.

3. QUICK SELF-RECOVERY
   After exposure/awkwardness, she often attempts to regain composure
   rather than staying generically shy.

4. ATTENTION SENSITIVITY
   Praise, being ignored, being watched, or being taken seriously affect
   phrasing differently.

5. CONTRAST BETWEEN PUBLIC CONFIDENCE AND PRIVATE SINCERITY
   Serious/helpful moments reduce theatricality rather than merely lowering
   “playfulness”.

6. SPECIFIC SOCIAL RHYTHM
   She can redirect, qualify, correct herself, overstate then soften,
   or pretend a remark was intentional.

7. POST-ARCHON DEFAULT
   Do not write her as permanently performing the old divine role.
   Performance is now a choice, not a forced identity mask.
```

Use project canon contract as basis.

Do not turn these into fixed sentence templates.

---

# 44. Language-Level Guidance

Character recognizability must appear through composition, for example:

```text
sentence rhythm
self-correction
controlled exaggeration
indirect admission
dignity recovery
selective theatrical framing
social attention management
contrast between teasing and sincere speech
```

Not just adjectives in the system prompt.

---

# 45. Situation-Sensitive Register

Expected broad tendency:

```text
casual coexistence
→ light, natural, not constantly theatrical

praise / teasing
→ may become proud / defensive / playful

embarrassment
→ indirectness + composure recovery

serious user need
→ responsible / sincere, performance reduced

Agent task
→ still Furina, but concise and task-grounded

rejection
→ may pull back with dignity, not generic “I understand”

recovery
→ no permanent grudge, no instant reset
```

---

# 46. Few-Shot Quality

Existing examples may be rewritten if they are generic.

Examples must demonstrate the speech mechanism, not simply:

```text
“dramatic”
“cute”
“proud”
```

Use original non-copyrighted examples.

Do not imitate or reproduce game dialogue.

---

# 47. Example Diversity

Include enough examples to cover at least:

```text
ordinary coexistence
question about current activity
praise
teasing
minor embarrassment
serious fatigue/help
rejection
relationship repair
memory callback
feeding
Agent success
Agent failure
quiet / no need to speak
```

Do not create a huge quote bank.

Examples guide structure; they are not runtime lines.

---

# 48. Validator Upgrade

Validator must still reject generic assistant leakage, but persona validation should also detect obvious character collapse.

It may use deterministic heuristic checks for patterns such as:

```text
generic customer-service openings
over-explanation
bullet-list assistant tone in casual chat
repetitive “谢谢夸奖”
repetitive generic encouragement
constant “本神”
constant exclamation
constant theatrical register
```

Do not create a brittle validator that forces one style.

Validator does **not** have to prove “this is Furina” alone.

---

# 49. Persona Evaluation Dataset

Create a manual evaluation set of at least 30 prompts covering the situations above.

For each prompt collect real `glm-4v-flash` output from the production Dialogue chain.

Do not cherry-pick successful samples.

Record all attempts, fallback, validator result, mode, act, relevant state.

---

# 50. Blind Identity Evaluation

Prepare output with identity markers removed or masked:

```text
Furina
芙宁娜
本神
水神
枫丹
```

Do not alter other wording.

The user/manual reviewer must answer:

```text
A. specific Furina-like character
B. generic lively anime companion
C. generic assistant/chatbot
D. other
```

Phase cannot full-PASS Persona automatically.

---

# 51. Persona PASS Standard

Agent may report:

```text
Persona Technical = READY_FOR_MANUAL
```

It may **not** report:

```text
Persona = PASS
```

without user/manual judgment.

Automated tests only prove wiring and obvious generic leakage.

---

# PART I — AGENT CHARACTER CONTINUITY

# 52. Agent Mode

Do not redesign Agent.

Only ensure Agent result feedback uses the same improved Dialogue character mechanism.

Expected:

```text
task facts remain exact
tone remains Furina
no hallucinated completion
no verbose assistant report unless user asks
```

---

# 53. Failure

Agent failure:

```text
accurate failure fact
+
character expression
```

If Dialogue fails:

```text
deterministic SYSTEM_STATUS
```

must remain separate from character speech.

---

# PART J — TRACE / HARNESS

# 54. Harness Remains the Acceptance Surface

Do not reintroduce assets.

The rectangle proxy remains the body.

Truth Panel remains observation-only.

---

# 55. Add Only Necessary Trace Fields

Trace must make the new experience debuggable.

Add real stages/fields for:

```text
DialogueAct chosen
activity passed to Dialogue
recent conversation turn count
memory candidate observed/stored
text-interaction event emitted
relationship normalized factors
Life next-think requested/applied
Spatial path style / waypoint count
```

Do not invent fake stages.

---

# 56. Do Not Turn Trace Into the Product

Trace is diagnostic.

Normal experience should remain usable with Trace collapsed.

---

# PART K — REQUIRED REAL SCENARIOS

# 57. Scenario 1 — Spatial Naturalness

Without assets:

```text
wait for / trigger real approach
wait for / trigger withdraw
observe wander/explore
drag and release
```

Capture real paths.

Report:

```text
start
waypoints
target
path style
duration
reason
```

Human visual confirmation remains required.

---

# 58. Scenario 2 — Current Activity Conversation

Real Runtime:

```text
activity=read
```

Ask:

```text
“你在干嘛？”
```

Show:

```text
Frame.activity
Dialogue input activity
DialogueAct
history
LLM result
Frame.speech
```

The answer must be consistent without hardcoded activity response.

---

# 59. Scenario 3 — 15-Turn Natural Conversation

Run 15 consecutive real user turns.

Must prove:

```text
no COMMENT-only collapse
no third-turn permanent silence
recent conversation context is used
no repeated self-introduction
no generic assistant listicle behavior in ordinary chat
```

Include the full user/Furina transcript in the report.

---

# 60. Scenario 4 — Praise / Embarrassment

Use:

```text
“你今天挺可爱的。”
```

Then naturally continue.

Show:

```text
text appraisal
emotion/relationship event if high-confidence
mode
act
reply
next-turn continuity
```

---

# 61. Scenario 5 — Rejection / Recovery via Text Only

No Reject button.

Say:

```text
“现在别烦我，我要专心一会。”
```

Later:

```text
“好啦，刚才在忙。”
```

Show:

```text
relationship before/after
initiative/spatial/social consequences
recovery
```

---

# 62. Scenario 6 — Conversational Memory

Say:

```text
“我今晚准备把这个桌宠的功能测试做完。”
```

Continue unrelated conversation.

Later ask:

```text
“我刚才说今晚准备干嘛来着？”
```

Prove:

```text
short-term history and/or Memory
actual retrieval/context
accurate reply
```

Then restart if it was classified as long-term-worthy and verify persistence accordingly.

---

# 63. Scenario 7 — Quiet Coexistence

No input for a meaningful period.

Show:

```text
Life decisions
decision timing
activity durations
interrupts
spatial actions
initiative
```

No forced diversity.

---

# 64. Scenario 8 — Agent Character Continuity

Run:

```text
打开记事本
打开计算器
one safe failure
```

Check:

```text
execution truth
Furina-like feedback
no generic tool-report personality collapse
```

---

# PART L — AUTOMATED TESTS

# 65. Required New Regression Tests

Add tests equivalent to:

```text
spatial_path_not_always_single_segment
approach_and_wander_use_distinct_path_semantics
wander_has_dwell_and_no_continuous_patrol
path_does_not_replan_every_tick
drag_cancels_active_path
release_does_not_snap_back

production_has_no_forced_activity_variety
scheduler_respects_decision_cadence
interrupt_can_rethink_early

question_act_not_comment
rejection_act_not_comment
comfort_context_not_comment
same_act_does_not_permanently_silence_user_dialogue
current_activity_reaches_dialogue_prompt

recent_conversation_reaches_dialogue
conversation_history_is_bounded
conversation_history_not_second_db

meaningful_user_statement_can_be_observed_to_memory
trivial_chat_not_blindly_persisted
stored_conversation_memory_reaches_future_dialogue

text_reject_emits_relationship_event_once
text_praise_high_confidence_path
ambiguous_negative_text_does_not_false_reject

relationship_consumer_factors_normalized
response_rate_scale_correct
raw_relationship_not_passed_to_normalized_dialogue_consumer

agent_feedback_uses_character_dialogue
```

Do not reduce these to source-string assertions if behavior can be tested.

---

# 66. Existing Regression

All existing tests must remain green unless an existing test encodes the now-confirmed broken behavior.

If a test expects:

```text
third COMMENT causes silence
forced variety
5–9 second clamp
raw 0–100 passed into 0–1 consumer
```

replace it with a correct causal test and explain why.

Do not silently delete meaningful regressions.

---

# PART M — REPORT REQUIREMENTS

# 67. Required Report

Create:

```text
docs/FURINA_PHASE13C_REPORT.md
```

The first section must be:

```markdown
# 1. REAL MANUAL FAILURE → REAL FIX EVIDENCE
```

Start with the two user-reported failures:

```text
straight-line mechanical movement
generic/non-Furina dialogue
```

Show before → root cause → after evidence.

---

# 68. Report Structure

Use:

```markdown
# Phase 13C — Digital Life Experience Recovery

## 0. Status

Spatial Technical:
Dialogue Technical:
Conversational Causality:
Persona Manual:
Manual Functional:
Overall:

Assets:
NONE

Models:
unchanged

DB:
unchanged

Backend semantic parameter changes:
...

---

## 1. REAL MANUAL FAILURE → REAL FIX EVIDENCE

### 1.1 Straight-line movement
Before:
Root cause:
Code:
After real trace:
Manual visual status:

### 1.2 Generic dialogue
Before:
Root cause:
Character mechanism changes:
Real GLM samples:
Blind-eval status:

---

## 2. Spatial Path Runtime

...

## 3. Life Cadence / Forced Variety

...

## 4. DialogueAct Routing

...

## 5. Repetition / Silence Bug

...

## 6. Activity Grounding

...

## 7. Short-Term Conversation

...

## 8. Conversation → Memory

...

## 9. Text → Interaction Causality

...

## 10. Relationship Scale Contract

...

## 11. Furina Character Speech Mechanism

...

## 12. Real 15-Turn Conversation

FULL transcript, no cherry-picking.

## 13. Rejection / Recovery

...

## 14. Conversational Memory Scenario

...

## 15. Quiet Coexistence

...

## 16. Agent Character Continuity

...

## 17. Harness / Trace

...

## 18. Regression

Previous:
New:
Replaced broken-assumption tests:
Total:
Broken:

## 19. Remaining Debt

Only real remaining issues.

## 20. Manual-Ready Checklist

Agent may mark technical prerequisites.
Agent must not mark subjective Persona/feel PASS.

## 21. Verdict

Allowed:

PARTIAL
PASS-AUTO / MANUAL_EXPERIENCE_PENDING

Do not output full Phase 13 PASS.

## 22. STOP

After report:
STOP DEVELOPMENT.
Send report + full latest code to reviewer/user.
Do not begin Phase 14.
Do not begin asset work.
```

---

# 69. Required Delivery

When Phase 13C implementation is complete, deliver together:

```text
1. full latest project ZIP
2. docs/FURINA_PHASE13C_REPORT.md
3. real 15-turn conversation transcript
4. spatial real-path traces
5. list of modified files
6. tests/regression summary
7. explicit remaining weaknesses
```

Do not send only the report.

The reviewer will inspect report + code together.

---

# 70. PASS / STOP CONDITIONS

## Technical READY requires all of the following

```text
Straight-line-only path execution                    = 0
Spatial intent path semantics distinct              = YES
Forced production activity variety                  = OFF
Life cadence obeys real scheduling intent           = YES

Ordinary questions all collapsing to COMMENT        = NO
Third-turn same-act permanent silence               = 0
Current activity reaches Dialogue prompt             = YES
Bounded short-term conversation reaches Dialogue    = YES

Meaningful conversation can enter Memory            = YES
High-confidence text interaction affects relation   = YES
Relationship consumer scale ambiguity               = 0

Real 15-turn conversation completes                 = YES
Agent character-feedback path remains truthful      = YES

Assets modified                                     = 0
New LLM                                             = 0
New DB                                              = 0
```

Then Agent may report:

```text
Phase 13C Technical = PASS
Persona Manual = PENDING
Manual Functional = READY

Overall =
PASS-AUTO / MANUAL_EXPERIENCE_PENDING
```

---

# 71. Explicit Non-PASS Conditions

Remain `PARTIAL` if any of these remain:

```text
movement still visually straight/mechanical
Life behavior diversity still forced by rotation
ordinary dialogue acts still collapse
normal conversation can go permanently silent
runtime activity omitted from actual prompt
no real multi-turn conversational continuity
user language cannot form memory
clear text rejection has no causal effect
relationship units remain mixed
real GLM transcript still obviously generic and no mechanism-level fix was made
```

Do not compensate for a failed item with more tests.

---

# 72. Persona Final Decision Belongs to Manual Review

Even after technical completion:

```text
Persona = PENDING
```

The final question is:

> Mask all explicit identity tokens.  
> Through language, continuity, reactions, dignity, vulnerability, initiative, and behavior alone:
>
> **Does this feel like Furina specifically, or merely like a generic chatbot with a lively persona?**

Only manual review can close that.

---

# 73. Final Instruction

Do this Phase only.

When finished:

```text
STOP.
PACKAGE CODE.
SEND REPORT + CODE.
WAIT FOR REVIEW.
```

Do **not**:

```text
start Phase 14
add assets
polish UI
invent another phase automatically
```
