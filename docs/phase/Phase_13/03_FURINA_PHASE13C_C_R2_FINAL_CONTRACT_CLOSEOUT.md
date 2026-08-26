# Phase 13C — C-R2 Final Contract Closeout

> Reviewer verdict on C-R1:
>
> **C-R1 is materially improved but NOT yet `READY_FOR_MANUAL`.**
>
> Do not start Phase 14. Do not change assets. Do not tune Needs/Emotion/Behavior/Persona weights.
>
> This R2 is intentionally narrow. It exists only to close verified production contract bugs left after R1.

---

# 0. Status entering R2

```text
Phase 13C Technical        PARTIAL
Manual                     NOT READY
Persona                    PENDING

Spatial curve architecture PASS-AUTO
Forced-variety removal     PASS
Conversation dedup         PASS
Conversation source        PASS

Relationship contract      FAIL
Persona example routing    PARTIAL
```

---

# 1. Reviewer first evidence — MUST reproduce before changing code

With a real `RelationshipState`:

```text
familiarity=50
trust=50
comfort=60
annoyance=20
user_response_rate=.5
user_rejection_rate=.2
```

current code produces approximately:

```text
RelationshipEngine.factors():
trust=.5
comfort=.6
annoyance=.2
response_rate=.5
confidence=.8

BehaviorMotivation._rel():
trust=.5
comfort=.6
annoyance=.2
response_rate=.005       <-- WRONG
confidence=.998          <-- WRONG

LifeBrain._relationship_factors():
trust=1.0                <-- WRONG
comfort=1.0              <-- WRONG
annoyance=1.0            <-- WRONG
familiarity=1.0          <-- WRONG
```

Also:

```text
user_response_rate=.5
EV_POSITIVE_RESPONSE
→ user_response_rate=1.3
```

because `RelationshipEngine._bump()` still clamps every field to 0..100.

This evidence must be included in the R2 report as BEFORE.

---

# 2. Create ONE relationship normalization function

There must be exactly one canonical conversion implementation for production consumers.

Recommended shape:

```python
relationship_factors(rel: RelationshipState | dict | None) -> dict
```

Location should be in `furina/relationship/` (or equivalent canonical relationship module).

`RelationshipEngine.factors()` must delegate to it.

Do not keep independent unit-conversion implementations in:

```text
BehaviorMotivation._rel
LifeBrain._relationship_factors
Dialogue
Embodiment
```

They may call the canonical helper, but must not reimplement the conversion.

---

# 3. Canonical units

Keep the C-R1 contract unless migration proves impossible:

```text
0..100 raw:
familiarity
trust
comfort
attachment
respect
dependency
annoyance
interaction_tolerance
social_confidence

0..1 raw:
user_response_rate
user_rejection_rate
```

Derived:

```text
response_rate 0..1
confidence    0..1
interaction_freq 0..1
```

Document this once.

---

# 4. Fix write-side units — not only read-side

`RelationshipEngine._bump()` must clamp according to the field unit.

Forbidden:

```python
all fields -> clamp(0, 100)
```

Required conceptual behavior:

```text
0..100 fields → clamp 0..100
0..1 fields   → clamp 0..1
counts        → non-negative count semantics
timestamps    → timestamp semantics
```

Do not silently treat all relationship fields as the same unit.

---

# 5. Normalize event deltas consistently

Current event deltas for normalized rates such as:

```text
user_response_rate +0.8
user_rejection_rate +0.8
```

must be audited against the declared 0..1 contract.

Do NOT arbitrarily “tune them until behavior looks good”.

Perform a unit migration:

```text
determine intended magnitude under the old representation
→ express the same intended magnitude in the new canonical unit
→ document the conversion
```

The final invariant is:

```text
after every RelationshipEngine.apply:
0 <= user_response_rate <= 1
0 <= user_rejection_rate <= 1
```

No transient 1.3 values.

---

# 6. Reject route must not double-update statistics

Current production route:

```text
RelationshipEngine.apply(EV_REJECT)
```

already changes:

```text
user_rejection_rate
rejection_count
```

then `Scheduler.on_user_reject()` directly changes the same fields again.

This is duplicate ownership.

Fix so that one reject causes:

```text
RelationshipEngine.apply(EV_REJECT) exactly once
rejection_count increments exactly once
user_rejection_rate changes exactly once
persistence once after final state
LifeBrain tolerance adaptation once
life interrupt once
```

Scheduler must not manually bump relationship fields already owned by `RelationshipEngine`.

---

# 7. BehaviorMotivation must consume canonical factors

Current `_rel(state)` incorrectly performs:

```text
user_response_rate / 100
user_rejection_rate / 100
```

even though they are 0..1.

Replace duplicated normalization with the canonical relationship-factor helper.

Required exact test:

```text
raw response_rate=.5
raw rejection_rate=.2

BehaviorMotivation receives:
response_rate=.5
confidence=.8
```

not `.005/.998`.

This test must execute the actual `_rel`/candidate production path, not source-string grep.

---

# 8. LifeBrain CharacterAppraisal must consume canonical factors

Current `CharacterState.relationship` is populated with the raw `RelationshipState` object.

Therefore `LifeBrain._relationship_factors()` must NOT assume it is already normalized.

Remove this duplicate helper or delegate to the canonical normalizer.

Required exact test:

```text
raw:
familiarity=50
trust=50
comfort=60
annoyance=20

LifeBrain appraisal factors:
.5 / .5 / .6 / .2
```

No saturation to 1.0.

---

# 9. Dialogue expressive normalized thresholds

`furina/dialogue/expressive.py` still contains:

```python
annoyance > 60
```

while Dialogue now receives normalized factors.

Fix to the correct normalized contract.

Perform one grep/audit for every relationship threshold in production consumers.

Do not change behavioral meaning other than unit conversion.

Required test must execute strategy behavior:

```text
annoyance=.7 triggers high-annoyance branch
annoyance=.2 does not
```

Do not merely assert a source string exists.

---

# 10. Positive text interaction persistence

High-confidence praise/gratitude currently calls `RelationshipEngine.apply(EV_POSITIVE_RESPONSE)` directly.

Ensure the final relationship state is persisted using the same relationship persistence contract as other meaningful interactions.

Do not rely on “some unrelated future interaction might save it”.

One praise event:

```text
apply once
persist once
state reference remains the canonical shared state
```

---

# 11. Persona example routing — close two verified gaps

## 11.1 Agent failure

Current `_route_example_context()` routes any `activity` containing `"agent"` to:

```text
agent_success
```

so `activity="agent_fail"` selects the success example.

Fix:

```text
agent_fail / failed agent result
→ agent_failure
agent_report / successful completion
→ agent_success
```

Add an actual selector test.

## 11.2 Stage-direction examples

Current example pool still contains lines such as:

```text
（安静地看了一会儿）...
（轻声）...
（轻轻地）...
（安静了一会儿）...
```

The Phase 13C contract forbids stage-direction examples.

Remove/rewrite all parenthetical action/performance directions from synthetic examples.

Do not weaken the test regex to make them pass.

Test should reject any example using action/stage parentheticals, not only a small hardcoded word list.

---

# 12. Tests that MUST be added/replaced

Behavioral tests, not only source scans:

```text
test_relationship_canonical_normalizer_exact
test_relationship_rate_write_clamps_01
test_positive_response_rate_never_exceeds_one
test_reject_stats_increment_once_real_route

test_behavior_motivation_relationship_scale_exact
test_lifebrain_appraisal_relationship_scale_exact

test_dialogue_annoyance_normalized_branch

test_text_positive_response_persists_once

test_agent_failure_selects_agent_failure_example
test_no_stage_direction_in_any_example
```

Existing 441 tests remain green unless one encodes the now-proven wrong unit behavior.

---

# 13. Mandatory code invariants for reviewer

Reviewer will directly check:

```text
canonical relationship normalizer implementations = 1

BehaviorMotivation:
response_rate .5 -> .5
rejection .2 -> confidence .8

LifeBrain appraisal:
50/50/60/20 -> .5/.5/.6/.2

RelationshipEngine:
rate fields never >1

one EV_REJECT:
rejection_count delta = exactly 1 semantic event
no Scheduler second relationship-stat mutation

Dialogue normalized:
annoyance .7 reaches high-annoyance strategy

agent_fail:
example context = agent_failure

stage-direction synthetic examples = 0
```

---

# 14. Do NOT touch

```text
Spatial path implementation
Life cadence
forced-variety work
conversation history
current-turn memory ordering
asset system
animation
Needs parameters
Emotion parameters
Relationship principal deltas except unit migration for rate fields
Behavior weights
LLM choice
DB schema
```

No new feature work.

---

# 15. Report

Create/update:

```text
docs/FURINA_PHASE13C_R2_REPORT.md
```

Start with the exact BEFORE reproduction in §1.

Then AFTER show exact numeric values.

Do not lead with test count.

Final allowed status:

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = PENDING
Overall = REVIEW_REQUIRED
```

Do not claim Phase 13 PASS.

---

# 16. STOP CONDITION

After R2:

```text
STOP DEVELOPMENT
PACKAGE LATEST PROJECT
SEND ZIP + R2 REPORT
WAIT FOR REVIEW
```

If reviewer confirms the explicit invariants above, there will be no C-R3 for ordinary optimization.

The next action will be **Manual Experience Test** unless a new hard blocker is discovered while verifying these exact invariants.
