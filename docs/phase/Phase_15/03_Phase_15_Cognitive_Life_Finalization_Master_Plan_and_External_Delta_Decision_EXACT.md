# Phase 15 — Cognitive Life Finalization
# Master Plan + External Delta Decision + Branch / Documentation Protocol
# EXACT

Document path:

`docs/phase/Phase_15/03_Phase_15_Cognitive_Life_Finalization_Master_Plan_and_External_Delta_Decision_EXACT.md`

Repository:

`wqx-txdsyl/furina-desktop-ai`

External audit commit:

`4442fac4de1deabaf967d2f029032f0076512ab7`

Phase 14 code frozen SHA:

`f8e84ecc7be67fbfa9d78f00b056bce4dd420095`

Phase 15 documentation baseline SHA:

`4442fac4de1deabaf967d2f029032f0076512ab7`

External reviewer:

`GPT-5.6 Sol`

Current state:

```text
Phase 14 = FINAL REVIEWER PASS / CODE FROZEN
Phase 15 External Reference Audit = REVIEWED
Phase 15 = READY FOR BOUNDED FINALIZATION TASKS
```

This document is the authoritative **Phase 15 master execution plan**.

It freezes:

- the corrected interpretation of the external audit;
- the accepted / rejected / deferred deltas;
- Phase 15 implementation order;
- branch naming;
- documentation numbering;
- reviewer authority;
- no-change architecture;
- final acceptance gates.

It does NOT itself authorize unbounded implementation.

Each implementation unit still requires its own exact bounded task brief.

---

# 0. WHY THIS MASTER PLAN EXISTS

Phase 15 already had a large cognitive architecture and substantial implementation before the external-reference audit.

The purpose of the external audit was not to replace that architecture.

It was to answer:

```text
What do mature / adjacent projects actually implement
that Furina still genuinely lacks?
```

The audit produced useful findings, but the external reviewer identified several classification / wording issues that MUST be corrected before implementation.

Therefore Phase 15 must NOT proceed directly from the raw audit report.

The canonical flow is now:

```text
Phase 14 PASS / FROZEN
        ↓
01 External Reference Code Audit Task Brief
        ↓
02 External Reference Code Audit Report
        ↓
03 THIS MASTER PLAN
   + reviewer corrections
   + delta decision
   + branch/docs protocol
        ↓
04+ one bounded implementation task at a time
        ↓
Phase 15 Integrated Final Gate
        ↓
Phase 15 FROZEN
        ↓
Phase 16
```

---

# 1. SHA / BASELINE TERMINOLOGY — DO NOT CONFUSE THESE

There are now TWO important SHAs.

## 1.1 Phase 14 CODE frozen SHA

```text
f8e84ecc7be67fbfa9d78f00b056bce4dd420095
```

Meaning:

```text
Phase 14 production implementation
+
Phase 14 tests
+
Phase 14 final reviewer closure
=
FROZEN
```

No Phase 15 implementation may reinterpret this as "Phase 14 is still open".

## 1.2 Phase 15 documentation baseline SHA

```text
4442fac4de1deabaf967d2f029032f0076512ab7
```

This commit is:

```text
Phase 14 frozen code
+
Phase 15 docs only:
    00_MANIFEST
    01 External Audit Task Brief
    02 External Audit Report
```

No production code changed between:

```text
f8e84ec
→
4442fac
```

Therefore:

```text
PHASE14_CODE_FROZEN_SHA = f8e84ec...
PHASE15_WORKING_DOC_BASELINE = 4442fac...
```

Do NOT casually call `4442fac` the Phase 14 final code SHA.

Do NOT start future Phase 15 work from some unrelated master state.

---

# 2. BRANCH-NAMING CORRECTION

The Phase 15 audit docs commit `4442fac` was pushed while the operator was still on:

`fix/phase14-final-r7-r10-failclosed`

This is a **branch-name semantic mistake**, not a code-integrity failure.

Why it was tolerated:

```text
4442fac changed docs only
and did not modify Phase 14 production code.
```

But the old branch name MUST NOT continue into Phase 15 implementation.

From this master plan onward:

```text
NO new Phase 15 production work
on a branch named fix/phase14-...
```

## 2.1 Canonical Phase 15 integration branch

Recommended:

`feature/phase15-cognitive-life-finalization`

Create it from:

`4442fac4de1deabaf967d2f029032f0076512ab7`

This branch is the integration line for accepted Phase 15 bounded tasks.

## 2.2 Bounded task branches

Each implementation unit SHOULD use a task-specific branch created from the latest externally accepted Phase 15 integration SHA.

Recommended names:

```text
feature/phase15-d1-canon-act2-act3-evidence
feature/phase15-d4-temporal-semantics
feature/phase15-d2-hybrid-retrieval
feature/phase15-d3-retrieval-cooldown
feature/phase15-d5-relationship-antispam
```

Important:

```text
D1 / D4 / D2 / D3 / D5
are Delta IDs / implementation order labels,
NOT new Phase numbers.
```

## 2.3 Sequential base rule

After each bounded task:

```text
task branch
→ implementation
→ tests
→ external reviewer
→ PASS
→ fast-forward / integrate into Phase 15 integration branch
→ next task branches from the NEW accepted integration SHA
```

Do NOT branch every task forever from stale `4442fac`.

Do NOT stack a new task on top of an unreviewed predecessor.

---

# 3. EXTERNAL AUDIT REVIEW VERDICT

The external audit itself is accepted with reviewer reclassification.

Canonical verdict:

```text
PHASE15_EXTERNAL_AUDIT_REVIEW = PASS_WITH_RECLASSIFICATION
```

The audit successfully established:

- exact external repository SHAs;
- Reality Gates;
- code-vs-README distinction;
- C1-C7 comparisons;
- genuine AronaAI runtime mechanisms;
- Furinelle Persona / locator value;
- RP-Skill low implementation depth;
- Miru code-level audit deferral.

However, its raw T1–T5 classifications are NOT implementation authority.

This master plan supersedes those classifications.

---

# 4. EXTERNAL AUDIT CORRECTIONS / PREVIOUS MISJUDGMENTS

These corrections are permanent and MUST be preserved in future Phase 15 docs.

---

## 4.1 Correction A — T1 understated our actual retrieval gap

The raw audit described Furina as if it already had a semantic/vector retrieval path and only lacked hybrid retrieval.

Actual current production truth:

`furina/cognition/retrieval/index.py`

is named:

`SemanticVectorIndex`

and accepts an `embed_fn`, but its current `lookup()` implementation performs lexical Chinese 2-gram hit counting.

`furina/cognition/retrieval/ranker.py`

also uses deterministic lexical relevance.

Therefore the actual gap is larger:

```text
CURRENT:
derived index
+
lexical lookup / metadata / authority rank
+
deterministic fallback

NOT YET:
real vector similarity retrieval
+
hybrid lexical/vector candidate merge
```

Reviewer correction:

```text
T1 priority ↑
```

T1 becomes one of the highest-value Phase 15 deltas.

---

## 4.2 Correction B — T3 external implementation was overstated

The raw audit's matrix language could be read as if AronaAI has a mature deterministic write-time temporal normalizer.

More accurate external truth:

```text
AronaAI:
write-side relative-time normalization
= largely prompt-guided extraction behavior

deterministic date parsing
= stronger on query/retrieval side
```

Therefore Furina MUST NOT copy an alleged mature deterministic write parser that does not actually exist.

What we adopt is the PRODUCT / SEMANTIC idea:

```text
relative time in explicit C4 statements
should become bounded deterministic temporal semantics
when safely resolvable.
```

Our implementation must be our own deterministic authority-preserving design.

---

## 4.3 Correction C — T4 was assigned to the wrong Phase

Raw audit:

```text
T4 C4 plan proactive follow-up
→ ADAPT @ 15F
```

Reviewer correction:

```text
T4
→ LATER
→ Phase 17 Character Agency
```

Reason:

```text
C4 stores a plan
```

is cognition.

But:

```text
Furina notices the old plan
→ decides now is a good time
→ decides whether to interrupt
→ initiates social behavior
```

is Character Agency.

Phase 15 responsibility ends at:

```text
C4 plan is truthful
queryable
temporally meaningful
lifecycle-correct
```

Phase 17 owns:

```text
when / whether Furina acts on it.
```

This distinction is permanent.

---

## 4.4 Correction D — T5 mixed truth evolution and behavior policy

Raw audit bundled:

```text
relationship anti-spam
+
baseline / climate
+
proactive policy
```

into one candidate.

Reviewer correction:

### T5-A

```text
Relationship anti-spam / anti-runaway evolution
→ ACCEPT
→ Phase 15
```

This belongs to C5 truth evolution.

### T5-B

```text
relationship climate
→ proactive / silence / approach policy
→ LATER
→ Phase 17
```

This belongs to Character Agency.

Do NOT recombine them.

---

## 4.5 Correction E — RP-Skill test wording was too strong

The audit report used wording equivalent to:

```text
README "Tests 90% passing" = false claim
```

Repository Reality Gate confirms:

```text
no runtime
no reproducible test suite artifacts
README contains 90% test-pass badge / scenario percentages
```

But repository evidence alone cannot prove no off-repo/manual evaluation ever occurred.

Future docs MUST use the more precise wording:

> `The "90% tests passing" claim is not reproducibly substantiated by repository test artifacts at the audited SHA.`

Do NOT call it fraud / fake / fabricated unless direct evidence exists.

---

## 4.6 Correction F — Furinelle is not a cognitive-architecture authority

Furinelle remains useful for:

```text
Persona dimensions
Persona manual evaluation scenarios
Canon locator clues
future Hermes adapter recon
```

But its memory runtime mixes concepts such as:

```text
memory
profile
relationship / intimacy
soul state
reflection
```

more aggressively than our C1-C7 architecture permits.

Therefore:

```text
Furinelle Persona/Eval = reference
Furinelle memory authority model = REJECT
```

Do not import its intimacy meter.

---

# 5. PHASE 15 FROZEN NO-CHANGE ARCHITECTURE

The following are NOT open for redesign in Phase 15 finalization.

## C1 Canon Identity

```text
Furina != Focalors
same origin does not mean identical knowledge/memory
```

## C2 Canon Life History

```text
version controlled
runtime read-only
official provenance required
external repo may be locator only
```

## C3 Runtime Autobiographical Memory

```text
MemoryEngine = formation authority
durable memory requires valid event provenance
Memory != Event
Memory != User Model
```

## C4 User Model

```text
structured lifecycle
current explicit truth > stale fact
supersede / complete, not silent overwrite
exact source-event provenance
```

## C5 Relationship

```text
RelationshipEngine = truth owner
not an intimacy score
not a visible heart meter
milestones preserve provenance
```

## C6 Event Timeline

```text
objective append-only truth
```

## C7 Agent Task History

```text
verified work truth
agent backend "done" != verified done
```

## Derived Retrieval

```text
DERIVED
REBUILDABLE
NON-AUTHORITATIVE
NOT C8
```

## Production Direct Turn

```text
USER_MESSAGE U
→ transition T
→ lifecycle row

exact event identity
fail closed
```

Any implementation that violates these is rejected regardless of external inspiration.

---

# 6. FINAL ACCEPTED PHASE 15 DELTA SET

Exactly FIVE implementation deltas survive reviewer filtering.

Plus ONE Canon evidence acquisition task.

The canonical set is:

```text
D1  C2 Act II / III Official Evidence Acquisition

D4  Deterministic Temporal Semantics for C4

D2  Real Hybrid Retrieval on Derived Index

D3  Retrieval Injection Cooldown / Exposure Control

D5  Relationship Anti-Spam / Anti-Runaway Hardening
```

Implementation order is intentionally:

```text
D1
→ D4
→ D2
→ D3
→ D5
→ Integrated Final Gate
```

The number order is NOT changed just to look sequential.

The D IDs preserve traceability back to the external audit / reviewer decision.

---

# 7. D1 — C2 ACT II / III OFFICIAL EVIDENCE ACQUISITION

Target:

`Phase 15A / C2`

Priority:

`HIGH / LOW RUNTIME RISK`

Problem:

Production C2 truthfully reports:

```text
missing_main_story_acts = ["II", "III"]
main_story_act_coverage_status = PARTIAL
```

Furinelle provides useful Act II / III scene locators.

External text is NOT authoritative.

## D1 Contract

Flow:

```text
external locator
→ official in-game / HoYo / official transcript source
→ independent verification
→ source registry
→ evidence units
→ episode attribution
→ semantic metrics
```

Rules:

```text
NO community text as C2 truth
NO invented URLs
NO guessed acts
NO relabel Character Story as MAIN_STORY
NO coverage laundering
```

D1 succeeds only if official evidence is actually found.

If Act II or III cannot be verified:

```text
remain PARTIAL
```

That is a valid result.

## D1 likely files

```text
data/canon/furina_life_sources.json
data/canon/furina_evidence_units.json
data/canon/furina_life_history.json   # only if attribution genuinely needs update
docs/persona/FURINA_CANON_LIFE_SOURCE_MAP.md
tests/cognition/...canon...
```

## D1 key tests

```text
official source classification
exact Chapter IV / exact act attribution
no community source promoted
metrics truthful
all evidence IDs registered
semantic conflicts = none
```

---

# 8. D4 — DETERMINISTIC TEMPORAL SEMANTICS FOR C4

Target:

`15B Interpretation + 15D User Model`

Priority:

`HIGH`

Problem:

Current Interpretation has:

```text
temporal_scope:
PERSISTENT / TRANSIENT / DATED / UNKNOWN
```

but does not sufficiently preserve semantic time from explicit utterances such as:

```text
今天...
明天...
后天...
下周...
这个周末...
九月...
2026年9月...
每周六...
```

C4 has lifecycle timestamps but lacks sufficient semantic `when/due` information.

## D4 Scope

First version applies only to explicit C4 domains where temporal semantics matter:

```text
PLAN
GOAL
IMPORTANT_DATE
ROUTINE / HABIT where deterministic
```

Do NOT expand D4 into general natural-language temporal understanding.

Do NOT apply it broadly to C3.

C3 already records actual event time.

## D4 principles

```text
deterministic-first
timezone-aware
absolute when safely resolvable
structured recurrence when safely resolvable
uncertain → temporal_uncertain
never invent
original utterance provenance retained
```

Potential model:

```text
temporal_kind
start_at
due_at
end_at
recurrence
timezone
temporal_uncertain
```

Exact schema is implementation-task-specific and must be justified.

Do NOT add fields merely because AronaAI has analogous concepts.

## D4 required behavior examples

```text
"我明天交报告"
→ explicit PLAN / GOAL
→ tomorrow in user-local calendar
→ exact source U preserved

"我九月可能..."
→ uncertain
→ no fake exact day

"我每周六..."
→ recurrence only if rule is unambiguous
```

---

# 9. D2 — REAL HYBRID RETRIEVAL ON DERIVED INDEX

Target:

`15E Retrieval`

Priority:

`VERY HIGH`

This is the largest technical retrieval delta.

## Current truth

Current derived index:

```text
is DERIVED
is REBUILDABLE
is NON-AUTHORITATIVE
```

These invariants are excellent and frozen.

But current lookup is predominantly deterministic lexical matching.

## D2 Goal

Add a real hybrid candidate system:

```text
lexical candidates
∪
vector candidates
        ↓
dedupe by authoritative ref
        ↓
authority/status/recency/relevance rerank
        ↓
bounded refs
```

Not:

```text
vector top-k
→ truth
```

## D2 hard invariants

```text
vector store/index can be deleted
→ C1-C7 remain intact

vector build failure
→ cognition still works

embedding unavailable
→ deterministic lexical retrieval

index result
→ returns refs / hints
→ authoritative store re-query wins
```

## D2 indexing rule

Index only selected safe summary representations of:

```text
C2
C3
C4
C7
```

Do NOT index:

```text
secrets
raw screenshots
API keys
whole DB dumps
C6 unbounded event history
```

## D2 retrieval quality requirements

Must test:

```text
exact-name query
semantic paraphrase
date-sensitive query where applicable
stale/superseded C4 does not outrank active truth
archived C3 does not dominate active strong memory
vector corruption fallback
index delete/rebuild idempotence
```

D2 must NOT copy AronaAI's authoritative-memory / Chroma dual-write model.

---

# 10. D3 — RETRIEVAL INJECTION COOLDOWN / EXPOSURE CONTROL

Target:

`15E Context Assembly`

Priority:

`MEDIUM-HIGH`

Problem:

Current bounded context prevents dumps, but the same high-scoring memory can appear in adjacent turns repeatedly.

This creates:

```text
"Furina keeps bringing up the same memory"
```

even though truth/retrieval correctness is technically fine.

## D3 design correction

Do NOT add `last_injected_at` to authoritative C3 truth rows unless an implementation brief proves a strong reason.

Preferred model:

```text
RetrievalExposureLedger
or
session-local exposure cache
```

Properties:

```text
OPERATIONAL
DERIVED
NON-AUTHORITATIVE
BOUNDED
EXPIRABLE
```

## D3 semantics

Recent automatic injection:

```text
same memory
→ temporary penalty / suppression
```

But explicit user recall:

```text
"你还记得..."
"刚才那个..."
"再说说..."
```

must be able to bypass cooldown.

Cooldown must NEVER mean forgetting.

## D3 restart decision

Persistence is optional.

First implementation should prefer the smallest correct design.

If session-local state solves the product problem:

```text
do not create unnecessary durable storage.
```

---

# 11. D5 — RELATIONSHIP ANTI-SPAM / ANTI-RUNAWAY HARDENING

Target:

`C5 Relationship truth evolution`

Priority:

`MEDIUM`

Current RelationshipEngine already has:

```text
multi-dimensional state
short-term vs long-term distinction
trust slower than other dimensions
negative-state recovery
baseline-like short-term decay
clamps
provenance milestones
```

Therefore DO NOT replace it with AronaAI's relationship model.

The real gap is:

```text
repeated identical events in a short period
can still accumulate too linearly.
```

Example:

```text
100 pet events
should not equal years of trust.

several accidental negative interactions
should not destroy the relationship.
```

## D5 goal

Introduce bounded diminishing accumulation.

Possible mechanisms to compare in the implementation task:

```text
rolling-window cap
daily absolute cap
diminishing returns by event repetition
event-family saturation
hybrid
```

Do NOT choose one merely because AronaAI used it.

## D5 hard boundaries

```text
NO visible affection number
NO intimacy level
NO "unlock affection stage"
NO coercive work-for-affection
NO loss of provenance
NO climate-driven autonomous behavior in Phase 15
```

The relationship remains continuous internal truth.

---

# 12. DEFERRED TO PHASE 17 — PERMANENT RECLASSIFICATION

These items must NOT re-enter Phase 15 through implementation convenience.

## P17-D1 — Plan / Goal Proactive Follow-Up

Former external candidate:

`T4`

Phase:

`17 Character Agency`

Because it requires:

```text
notice plan
→ choose motive
→ decide whether to interrupt
→ choose timing
→ social bid
→ Furina action
```

## P17-D2 — Relationship Climate → Behavior Policy

Former portion of:

`T5`

Phase:

`17 Character Agency`

Because it maps internal relationship truth to:

```text
approach
silence
refuse
play
support
distance
```

This is behavior policy.

Phase 15 may expose clean C5 factors.

Phase 17 decides what Furina does with them.

---

# 13. PERSONA / EVAL FINDINGS — NO PHASE 15 IMPLEMENTATION YET

Furinelle produced useful Persona hypotheses:

```text
self-reference mode
theatricality
face-saving
composure
vulnerability leakage
curiosity
boredom sensitivity
pressure-linked language shape
verbosity drift
imagery repetition
```

These are valuable as:

```text
Persona observability dimensions
future evaluation cases
red-team scenarios
```

But the external audit did NOT prove that our current Persona implementation requires immediate production redesign.

Therefore:

```text
NO Phase 15 Persona rewrite.
```

Future use:

```text
Persona regression suite
Phase 17 expression/agency
Phase 20 embodiment
Phase 22 voice delivery
```

---

# 14. REJECTED EXTERNAL PATTERNS

The following are explicitly rejected.

```text
single JSON mixing:
memory
profile
relationship
emotion/soul
reflection

intimacy level as relationship truth

heart / affection UI meter

LLM directly writes durable truth

LLM deletes durable truth without owner lifecycle

vector DB as authoritative memory

community Furina timeline as C2 truth

Furina/Focalors conflation

player omniscience as Furina knowledge

fixed timer directly speaking as "autonomy"

README architecture claims without runtime evidence
```

Future agents must not re-propose these merely as "industry practice".

---

# 15. PHASE 15 DOCUMENT NUMBERING

Existing:

```text
00_MANIFEST.md
01_Phase_15_External_Reference_Code_Audit_Task_Brief_EXACT.md
02_Phase_15_External_Reference_Code_Audit_Report_EXACT.md
03_Phase_15_Cognitive_Life_Finalization_Master_Plan_and_External_Delta_Decision_EXACT.md
```

Recommended future numbering:

```text
04_Phase_15_D1_Canon_Act_II_III_Official_Evidence_Task_Brief_EXACT.md
05_Phase_15_D1_Canon_Act_II_III_Official_Evidence_Closeout_Report_EXACT.md

06_Phase_15_D4_Deterministic_Temporal_Semantics_Task_Brief_EXACT.md
07_Phase_15_D4_Deterministic_Temporal_Semantics_Closeout_Report_EXACT.md

08_Phase_15_D2_Hybrid_Derived_Retrieval_Task_Brief_EXACT.md
09_Phase_15_D2_Hybrid_Derived_Retrieval_Closeout_Report_EXACT.md

10_Phase_15_D3_Retrieval_Exposure_Cooldown_Task_Brief_EXACT.md
11_Phase_15_D3_Retrieval_Exposure_Cooldown_Closeout_Report_EXACT.md

12_Phase_15_D5_Relationship_AntiSpam_Hardening_Task_Brief_EXACT.md
13_Phase_15_D5_Relationship_AntiSpam_Hardening_Closeout_Report_EXACT.md

14_Phase_15_Integrated_Final_Gate_Task_Brief_EXACT.md
15_Phase_15_Integrated_Final_Closeout_Report_EXACT.md
```

Do NOT rename future docs casually after implementation begins.

If a task is rejected before implementation:

```text
reserve the number
or document the cancellation in manifest
```

Do not silently reuse a number for another task.

---

# 16. IMPLEMENTATION ORDER RATIONALE

## D1 first

Why:

```text
isolated data/evidence scope
low runtime risk
closes known truthful Canon gaps if official evidence exists
tests source-discipline first
```

## D4 second

Why:

```text
temporal truth belongs in C4 before retrieval learns to search it
```

Do not build fancy time-aware retrieval over semantically weak stored time.

## D2 third

Why:

```text
retrieval substrate upgrade
largest technical retrieval change
should operate over stronger C4 semantics
```

## D3 fourth

Why:

```text
cooldown depends on final retrieval candidate/exposure semantics
```

Do not build cooldown twice around a retrieval system that is about to change.

## D5 fifth

Why:

```text
independent C5 hardening
touches stable relationship dynamics
best done after cognition retrieval path stabilizes
```

---

# 17. PER-TASK REVIEWER PROTOCOL

Every bounded implementation task follows:

```text
EXACT task brief
        ↓
baseline SHA confirmed
        ↓
task branch
        ↓
recon
        ↓
implementation
        ↓
new reviewer-locked tests
        ↓
preservation tests
        ↓
full suite
        ↓
static audit
        ↓
closeout report
        ↓
commit / push
        ↓
local SHA == remote SHA
        ↓
READY_FOR_REVIEW
        ↓
external reviewer
```

Coding agent may say:

```text
READY_FOR_REVIEW
```

or task-specific equivalent.

Coding agent may NOT say:

```text
PHASE_15_GATE_PASS
PHASE_15_FINAL_PASS
```

Only the external reviewer may.

---

# 18. TEST DISCIPLINE

Baseline at the last Phase 14 final reviewer run was reported as:

```text
1232 passed / 0 failed / 0 skipped
```

Phase 15 audit added docs only.

Therefore the first Phase 15 production task must preserve all existing tests.

Permanent rules:

```text
NO skip
NO xfail
NO deleted assertion
NO weakened assertion
NO "known failure" accepted as green
```

Each task should have:

```text
Gate A new task tests
Gate B previous Phase 15 accepted task tests
Gate C Phase 14 reviewer preservation
Gate D subsystem integration
Gate E agent/office foundation when relevant
Gate F full suite
```

The integrated final gate will be stricter.

---

# 19. PHASE 15 INTEGRATED FINAL GATE

After D1/D4/D2/D3/D5 individually pass, run one final integrated Phase 15 gate.

It must prove cross-feature behavior, not just isolated tests.

Minimum integrated scenarios:

## I1 — User plan with relative time

```text
user:
"我明天要完成报告"

canonical U
→ C4 PLAN
→ deterministic temporal semantics
→ source-event provenance
→ restart
→ still correct
```

## I2 — Current truth beats stale retrieval

```text
old C4 preference
→ superseded
→ index still contains stale derived representation temporarily
→ authoritative re-query
→ current active fact wins
```

## I3 — Hybrid retrieval

```text
exact lexical query
semantic paraphrase
embedding unavailable
corrupt index
delete/rebuild
```

all produce correct bounded behavior.

## I4 — Exposure cooldown

```text
memory automatically injected
→ adjacent unrelated turn
→ suppressed / penalized
→ explicit recall request
→ bypass
```

## I5 — Relationship repetition

```text
repeated positive interaction burst
→ bounded growth

repeated minor negative burst
→ bounded damage

milestone provenance remains valid
```

## I6 — Canon evidence truth

If D1 found official Act II/III evidence:

```text
metrics improve only for verified acts
```

If D1 did not:

```text
metrics remain PARTIAL
```

Both can pass.

## I7 — Restart

After restart:

```text
C1-C7 preserved
derived index reconstructable
operational cooldown state follows documented persistence semantics
no truth lost
```

---

# 20. PHASE 15 FINAL ACCEPTANCE CONDITIONS

The external reviewer may issue:

```text
PHASE_15_FINAL_GATE = PASS
```

only if:

1. D1 completed truthfully;
2. C4 temporal semantics are deterministic and fail-safe;
3. hybrid retrieval is real, not naming-only;
4. vector retrieval remains non-authoritative;
5. lexical fallback works;
6. index delete/rebuild is safe and idempotent;
7. cooldown does not become memory truth;
8. explicit recall can bypass exposure suppression;
9. C5 repeated events cannot runaway;
10. relationship milestones/provenance remain intact;
11. C1-C7 authority boundaries remain unchanged;
12. no C8 emerged;
13. no Phase 17 agency behavior leaked into Phase 15;
14. all old reviewer tests pass;
15. all new task tests pass;
16. full suite is green;
17. restart behavior is verified;
18. local/remote SHA match;
19. docs manifest matches actual history.

Then:

```text
Phase 15 = CLOSED / FROZEN
```

---

# 21. WHAT PHASE 15 DOES NOT INCLUDE

Explicitly NOT part of Phase 15:

```text
Hermes integration
Work Sovereignty
work refusal/protest
Agent backend selection
Furina deciding when to proactively follow up plans
relationship climate driving behavior
transparent desktop window
sprites
animation
TTS / ASR
wake word
desktop-pet body
agent embodiment
visual assets
```

These remain future phases.

---

# 22. NIGHT / IDLE EXECUTION POLICY

ZCode idle/scheduled capability may be used for Phase 15, but only under bounded authority.

## Safe night work

```text
READ-ONLY repo recon
static audit
test execution
index rebuild stress test
failure-path enumeration
bounded implementation from an EXACT task brief
```

## Forbidden autonomous night decisions

```text
redefine C1-C7
change phase boundary
move T4 back into Phase 15
choose a new relationship architecture
change Canon source hierarchy
start Hermes
start Phase 17
merge master
```

Night agent is an executor, not the project architect.

---

# 23. PHASE 15 MASTER DECISION TABLE

| Item | Final Decision | Phase | Implementation? |
|---|---|---:|---|
| Act II/III external locator | ACCEPT-AS-LOCATOR | 15A | D1 |
| Official Act II/III evidence | ACQUIRE IF VERIFIED | 15A | D1 |
| T1 real hybrid retrieval | ACCEPT / HIGH | 15E | D2 |
| T2 injection cooldown | ACCEPT / HIGH | 15E | D3 |
| T3 temporal semantics | ACCEPT / SCOPED | 15B/15D | D4 |
| T4 plan proactive follow-up | DEFER | 17 | NO |
| T5-A relationship anti-spam | ACCEPT | 15 C5 hardening | D5 |
| T5-B climate→behavior | DEFER | 17 | NO |
| Furinelle persona dimensions | LATER / EVAL INPUT | later | NO |
| Furinelle intimacy memory model | REJECT | — | NO |
| RP-Skill epistemic prompts | red-team material only | research | NO |
| RP-Skill source architecture | NO_CHANGE / weaker | — | NO |
| Miru backend | DEFER until code exists | later | NO |

---

# 24. NO SCOPE CREEP RULE

Any new idea discovered during D1–D5 must be classified:

```text
BLOCKER
or
BACKLOG
```

Only a true blocker to the current task may expand the implementation.

A useful improvement is not automatically a blocker.

If a new improvement belongs to a later phase:

```text
document
→ defer
→ continue current bounded task
```

Do not grow Phase 15 indefinitely.

---

# 25. NEXT DOCUMENT

The next document after this master plan is:

`04_Phase_15_D1_Canon_Act_II_III_Official_Evidence_Task_Brief_EXACT.md`

It must be written separately and narrowly.

Do NOT combine D1 + D4 + D2 into one giant coding task.

The purpose of this master plan is precisely to prevent that.

---

# 26. FINAL PHASE 15 EXECUTION MAP

```text
PHASE 14
FINAL PASS / FROZEN
f8e84ec
        │
        ▼
PHASE 15 DOC BASELINE
4442fac
        │
        ├── 01 External Audit Brief
        ├── 02 External Audit Report
        └── 03 Master Plan + Reviewer Delta Decision
                │
                ▼
feature/phase15-cognitive-life-finalization
                │
                ▼
D1
Official Canon Act II/III Evidence
                │
                ▼
REVIEWER PASS
                │
                ▼
D4
Deterministic C4 Temporal Semantics
                │
                ▼
REVIEWER PASS
                │
                ▼
D2
Real Hybrid Derived Retrieval
                │
                ▼
REVIEWER PASS
                │
                ▼
D3
Retrieval Exposure Cooldown
                │
                ▼
REVIEWER PASS
                │
                ▼
D5
Relationship Anti-Spam Hardening
                │
                ▼
REVIEWER PASS
                │
                ▼
PHASE 15 INTEGRATED FINAL GATE
                │
          ┌─────┴─────┐
          │           │
        FAIL         PASS
          │           │
only blocker patch   Phase 15 FROZEN
                      │
                      ▼
                   Phase 16
```

---

# 27. CORE PRINCIPLES

> **External code can teach mechanisms; it cannot redefine Furina's truth architecture.**

> **The Phase 14 code freeze SHA and the Phase 15 docs baseline SHA are different concepts.**

> **Branch names must reflect the phase being implemented.**

> **Cognition records what is true; Character Agency decides what Furina does about it.**

> **Retrieval may become smarter without becoming authoritative.**

> **Relationship may become more stable without becoming a game-like affection meter.**

> **Canon may remain PARTIAL forever rather than become falsely complete.**

> **One bounded task, one reviewer gate, then the next task.**
