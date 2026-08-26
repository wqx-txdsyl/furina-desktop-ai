# Phase 15 — External Reference Code Audit
# Cognitive Life External Reality-Gate / Delta Discovery
# EXACT TASK BRIEF

Document path:

`docs/phase/Phase_15/01_Phase_15_External_Reference_Code_Audit_Task_Brief_EXACT.md`

Repository:

`wqx-txdsyl/furina-desktop-ai`

Phase 14 final frozen baseline:

`f8e84ecc7be67fbfa9d78f00b056bce4dd420095`

Recommended working mode:

`READ-ONLY AUDIT`

Recommended branch:

NONE REQUIRED.

This task MUST NOT modify production code.

Current phase state:

```text
Phase 14 = FINAL REVIEWER PASS / FROZEN
Phase 15 = OPEN FOR EXTERNAL REFERENCE AUDIT
```

This is the **first formal task of Phase 15 after Phase 14 freeze**.

The purpose is NOT to merge external projects.

The purpose is:

> Read actual source code of relevant external repositories, compare their implemented cognitive-life mechanisms against Furina's current Phase 15 architecture, identify only genuinely useful deltas, and reject README-only / architecture-only / weaker implementations.

---

# 0. PHASE DOCUMENTATION PROTOCOL

`docs/phase/Phase_15/` does not exist at the frozen baseline.

Create:

```text
docs/phase/Phase_15/
├── 00_MANIFEST.md
├── 01_Phase_15_External_Reference_Code_Audit_Task_Brief_EXACT.md
└── 02_Phase_15_External_Reference_Code_Audit_Report_EXACT.md
```

## 0.1 `00_MANIFEST.md`

Create a minimal Phase 15 manifest using the same style as Phase 14 where applicable.

It must distinguish:

- task briefs;
- audit reports;
- future implementation reports.

Do NOT invent recovery history for Phase 15.

Phase 15 documents are new current-project documents, not `RECONSTRUCTED`.

## 0.2 Task brief

This exact task brief must exist at:

`docs/phase/Phase_15/01_Phase_15_External_Reference_Code_Audit_Task_Brief_EXACT.md`

## 0.3 Audit report

Create:

`docs/phase/Phase_15/02_Phase_15_External_Reference_Code_Audit_Report_EXACT.md`

The report is the ONLY required deliverable besides the manifest/task brief.

Do NOT create implementation task briefs in this task.

Do NOT update production architecture docs yet.

Do NOT update Canon source data yet.

Do NOT create Phase 16 documents.

---

# 1. HARD MODE: READ-ONLY EXTERNAL AUDIT

This task is strictly:

```text
READ
COMPARE
CLASSIFY
REPORT
STOP
```

Forbidden:

```text
NO production code modifications
NO tests modifications
NO dependency installation
NO pyproject changes
NO Canon data edits
NO Memory schema changes
NO C1-C7 redesign
NO cherry-pick
NO copy/paste external code into Furina
NO merge
NO implementation
NO Phase 16 / Hermes work
```

If any external idea appears valuable:

```text
record it as a candidate
→ explain why
→ map it to Phase 15 subphase
→ STOP
```

Do not implement it.

---

# 2. AUDIT TARGETS

Audit actual code for these Phase 15-relevant repositories.

## P15-REF-01 — AronaAI

Repository:

`xiahy456/AronaAI`

Primary expected value:

```text
Interpretation / extraction
User Model
Memory retrieval
Memory vs Knowledge separation
Relationship evolution
Cognitive orchestration
Proactive cognition
```

This repository is the highest-priority general cognitive-life reference for this audit.

## P15-REF-02 — Furinelle Furina

Repository:

`Furinelle/furina`

Audit DEFAULT / mainline Furina implementation only.

Primary expected value:

```text
Furina Persona representation
Persona behavior dimensions
Persona/OOC constraints
Persona evaluation
multi-turn drift scenarios
Canon locator
memory injection / reflection design as comparison material
```

Do NOT audit its Hermes adapter branch in this Phase 15 task.

Hermes adapter belongs to Phase 16.

## P15-REF-03 — Genshin Furina RP Skill

Repository:

`com554433/Genshin-Furina-RP-Skill`

Primary expected value:

```text
character-knowledge-boundary ideas
CSP / behavioral distillation
Canon source locator clues
Persona hypotheses
red-team cases
```

This repo is expected to have LOW implementation depth.

Do not inflate its score because of research prose.

## Explicitly deferred — Miru

Repository:

`kiyotakali/Miru`

Current reason for deferral:

```text
complete cognitive backend source is not sufficiently open for code-level audit
```

It may be mentioned in the report as:

`BLOCKED / DEFERRED`

but MUST NOT receive implementation claims based only on README descriptions.

---

# 3. SHA PINNING / REALITY GATE

Before making ANY technical claim about an external repository:

1. resolve its default branch;
2. resolve the exact commit SHA audited;
3. record that SHA in the report;
4. inspect actual repository tree;
5. inspect relevant implementation files;
6. inspect tests when they exist.

For each repo, the report must begin with:

```text
Repository:
Default branch:
Audited SHA:
Audit date:
Relevant code roots:
Relevant tests:
Reality Gate:
```

Allowed `Reality Gate` outcomes:

```text
IMPLEMENTED
PARTIALLY_IMPLEMENTED
PROMPT_ONLY
DOC_ONLY
BLOCKED
```

README claims do not count as implemented functionality.

A feature may be marked `IMPLEMENTED` only if actual executable/runtime code supports the claim.

---

# 4. OUR FROZEN PHASE 15 BASELINE

Audit external repos AGAINST our current architecture.

Do not compare them against a generic chatbot.

The following Furina boundaries are frozen unless a future separate task explicitly reopens them.

## C1 — Canon Identity

Answers:

`Who am I?`

Hard boundary:

```text
Furina != Focalors
same-origin relation does not imply shared runtime knowledge/memory
```

## C2 — Canon Life History

Answers:

`What canonically happened to me before this desktop life?`

Properties:

```text
version-controlled
runtime read-only
source/evidence provenance
semantic completeness may honestly be PARTIAL
```

## C3 — Runtime Autobiographical Memory

Answers:

`What have I experienced since living with this user?`

Properties:

```text
durable memory requires real event provenance
MemoryEngine is formation authority
lifecycle / dedupe / reinforcement / salience
```

## C4 — User Model

Answers:

`Who is the user?`

Properties:

```text
structured facts/preferences/plans/goals
explicit current fact wins over stale model
supersession / completion lifecycle
transition provenance
exact source event identity
```

## C5 — Relationship

Answers:

`What is our relationship?`

Properties:

```text
RelationshipEngine is truth owner
not a visible affection meter
milestones require provenance
relationship evolution != memory
```

## C6 — Life/Event Timeline

Answers:

`What objectively happened?`

Properties:

```text
append-only objective event truth
semantic memory must not replace it
```

## C7 — Agent Task History

Answers:

`What work did I actually do for the user?`

Properties:

```text
verified execution truth
Hermes/Agent completion is not automatically verified truth
```

## Derived Semantic Index

Properties:

```text
derived
rebuildable
non-authoritative
never source of truth
```

External designs that collapse these boundaries MUST be explicitly identified as conflicts.

---

# 5. PHASE 15 AUDIT DIMENSIONS

For each external repo, audit every relevant dimension below.

If the repo has no implementation for a dimension, say:

`NOT IMPLEMENTED`

Do not infer.

## 5.1 Canon / Knowledge / Memory boundary

Check:

```text
Does it distinguish character canon from runtime memory?
Does it distinguish knowledge/RAG from memory?
Does it distinguish user facts from autobiographical memory?
Does it distinguish relationship state from memory?
Is there an authoritative store?
Can vector retrieval overwrite truth?
```

## 5.2 Persona representation

Check:

```text
identity invariants
behavior dimensions
self-reference
theatricality
face-saving
vulnerability
composure
curiosity
boredom sensitivity
pressure behavior
OOC constraints
state-dependent expression
```

Do not copy external prompt text.

Extract dimensions and mechanisms only.

## 5.3 Persona evaluation

Check:

```text
automatic tests?
manual scenarios?
multi-turn drift?
identity challenge?
Canon challenge?
style repetition?
verbosity drift?
pressure transition?
relationship-state consistency?
```

Distinguish:

```text
content-file assertions
vs
actual model-output evaluation
```

## 5.4 Interpretation / extraction

Check:

```text
deterministic-first?
LLM extraction?
candidate vs fact?
confidence?
explicit user statements?
inference handling?
correction handling?
temporal normalization?
entity reconciliation?
```

## 5.5 C3-like autobiographical memory

Check:

```text
formation trigger
salience
dedupe
reinforcement
compression
forgetting
consolidation
source provenance
event linkage
write authority
restart behavior
```

## 5.6 C4-like user model

Check:

```text
profile
preference
plan
goal
habit
interest
important dates
boundary
upsert
delete
supersede
complete
temporal validity
source authority
```

## 5.7 C5-like relationship

Check:

```text
state variables
inertia
baseline
daily cap
milestones
event model
provenance
relationship -> behavior policy
relationship visibility to user
```

Explicitly flag game-like:

```text
affection level
intimacy number
heart meter
XP-style growth
```

as potential conflicts with our product philosophy.

## 5.8 Retrieval

Check:

```text
lexical
vector
hybrid
reranking
threshold
top-k
time-aware retrieval
cooldown
recency
salience
fallback
token budget
authority separation
```

## 5.9 Context assembly

Check:

```text
what enters prompt
priority ordering
current turn priority
Canon activation
memory limit
user model limit
relationship injection
knowledge injection
token budget
immutable snapshot?
```

## 5.10 Cognitive production loop

Check actual call flow.

Example form:

```text
input
→ event
→ interpretation
→ state changes
→ retrieval
→ planning
→ response
→ persistence
```

Document the REAL code path.

Do not copy architecture diagrams unless verified against code.

## 5.11 Proactive cognition

Check:

```text
when to speak
when to stay silent
idle behavior
goal follow-up
cooldown
quota
attention
relationship influence
memory influence
event triggers
```

Do not confuse fixed timer rules with autonomous cognition.

## 5.12 Provenance / truth discipline

This is a mandatory audit dimension.

Check:

```text
Can durable user facts exist without source event?
Can memory exist without evidence?
Can relationship transitions be traced?
Can derived semantic output become authoritative?
Can LLM hallucination directly mutate durable truth?
```

---

# 6. REQUIRED OUR-CODE COMPARISON

The report must not contain statements such as:

> "AronaAI has a user model, so we should add one."

We already have one.

Every external finding must be compared to the CURRENT Furina equivalent.

Required format:

| ID | External repo | External file/path | Actual mechanism | Our current equivalent | External advantage | Our advantage | Conflict? | Decision |
|---|---|---|---|---|---|---|---|---|

`Decision` must be one of:

```text
TAKE
ADAPT
REJECT
LATER
NO_CHANGE
```

Definitions:

## TAKE

Mechanism is clearly better and can likely be adopted almost directly at the conceptual level.

This does NOT authorize code copying.

## ADAPT

Idea is useful but must be reimplemented under our C1-C7 truth architecture.

This is expected to be the most common positive result.

## REJECT

External idea conflicts with our architecture/product truth or is weaker.

## LATER

Useful but belongs to Phase 16+ or frontend/voice/embodiment.

## NO_CHANGE

Our current implementation already solves the problem as well or better.

---

# 7. REQUIRED REPO-SPECIFIC QUESTIONS

## 7.1 AronaAI

Answer these exactly.

### A1 — User Model

Does its extractor implement:

```text
upsert
delete
existing-key reconciliation
temporal normalization
user-sourced-only facts
plan/goal completion
```

Which of these are actual code vs prompt instructions?

### A2 — Memory retrieval

Verify whether actual code implements:

```text
SQLite durable store
FTS5
vector store
local embeddings
hybrid merge
fallback
time-aware retrieval
injection cooldown
```

Do not rely on README.

### A3 — Memory vs Knowledge

Verify whether these are physically separate code paths/stores.

### A4 — Relationship

Inspect:

```text
trust
dependence
tension
baseline regression
inertia
daily cap
climate
```

Determine whether any of these are worth adapting into C5.

### A5 — Cognitive loop

Trace the real orchestration path.

### A6 — Proactive behavior

Determine whether proactive behavior is actually cognitive/attention-driven or mostly deterministic scheduler/cooldown logic.

---

# 8. FURINELLE-SPECIFIC QUESTIONS

## F1 — Persona dimensions

Extract mechanisms/dimensions only.

Do NOT copy copyrighted dialogue or long prompt passages.

At minimum examine:

```text
self-reference
face-saving
theatricality
composure
vulnerability
curiosity
boredom
pressure
verbosity
imagery
topic initiative
```

For each:

```text
Is it explicit?
Is it state-dependent?
Is it tested?
Would our existing Emotion/Persona stack already derive it?
```

## F2 — Persona evaluation

Separate:

```text
manual acceptance scenario
static content assertion
actual runtime model evaluation
```

Determine exactly what exists.

## F3 — Canon locator

Locate any useful Act II / Act III / post-Archon Furina scene references.

Rules:

```text
external repo = locator only
official source = required before C2 use
```

Do NOT promote external prose into Canon truth.

## F4 — Memory architecture

Audit it specifically as a comparison.

Determine whether it collapses:

```text
memory
user profile
relationship/intimacy
soul state
reflection
```

If so, explain why it is weaker than C1-C7 separation.

---

# 9. GENSHIN RP SKILL-SPECIFIC QUESTIONS

## G1 — Implementation reality

Determine exactly whether there is:

```text
runtime
memory engine
user model
relationship engine
retrieval
tests
```

or only:

```text
prompt
skill files
research
sources
```

## G2 — Character epistemic boundary

Extract any useful rule about:

```text
what Furina herself could know
vs
what the player/audience knows
```

Compare against our C1/C2 knowledge-boundary model.

## G3 — Source quality

Classify its references:

```text
official
official mirror
community wiki
media
forum/community
fanwork
unknown
```

Do not accept self-assigned reliability scores as evidence.

## G4 — Identity conflict

Specifically inspect for Furina/Focalors conflation.

Record every meaningful conflict as a red-team case.

---

# 10. LICENSE / COPYRIGHT / REUSE AUDIT

For every repo:

Record:

```text
license
code reuse permission
content reuse risk
character asset risk
prompt/content copying risk
```

This audit is informational.

Do NOT copy any code/content during this task.

For game-character dialogue or copyrighted source text:

```text
summarize
do not reproduce long passages
```

---

# 11. TEST / ENGINEERING MATURITY AUDIT

For each repo record:

```text
test framework
number/type of relevant tests if reasonably discoverable
CI present?
runtime code present?
persistence code present?
restart tests?
failure-path tests?
integration tests?
```

Do not equate:

```text
file exists
```

with:

```text
production behavior is verified
```

---

# 12. REQUIRED REPORT STRUCTURE

Create:

`docs/phase/Phase_15/02_Phase_15_External_Reference_Code_Audit_Report_EXACT.md`

Use this structure.

## 1. Audit Result

Summarize:

```text
repositories audited
exact SHAs
blocked/deferred repos
overall finding
```

## 2. Furina Phase 15 baseline

Concise C1-C7 / derived-index baseline.

## 3. AronaAI code audit

Include:

```text
Reality Gate
architecture tree
actual code paths
tests
strengths
weaknesses
C1-C7 conflicts
candidate deltas
```

## 4. Furinelle code audit

Same structure.

## 5. Genshin RP Skill audit

Same structure.

## 6. Miru deferred status

Explain why no code-level claims are made.

## 7. Cross-repo comparison matrix

At minimum compare:

```text
Canon
Persona
Persona Eval
Interpretation
C3
C4
C5
C6/event truth
Retrieval
Context
Proactive
Provenance
Restart
Tests
```

## 8. External Delta Matrix

Use the required format from §6.

## 9. TOP actual useful deltas

Maximum:

`10`

Do not manufacture ten if fewer are justified.

Each must contain:

```text
problem
external mechanism
why useful
our current gap
TAKE/ADAPT
target Phase15 subphase
risk
```

## 10. Explicit NO-CHANGE areas

This section is mandatory.

List areas where our architecture is already stronger and should remain frozen.

Likely examples may include, only if code audit supports them:

```text
C1-C7 separation
C6 objective truth
exact event provenance
C2 read-only Canon
derived vector index non-authority
C4 transition event identity
```

## 11. REJECTED external patterns

Examples to check:

```text
intimacy meter as truth
single JSON mixing memory/profile/relationship
LLM direct durable mutation
vector DB as truth
README-only claimed architecture
character omniscience
Furina/Focalors conflation
```

## 12. LATER items

Anything that belongs to:

```text
Phase 16 Hermes
Phase 17 Agency
Phase 19 UI
Phase 20 Embodiment
Phase 21 Art
Phase 22 Voice/Interaction
```

must be moved here instead of contaminating Phase 15.

## 13. Proposed Phase 15 patch candidates

Do NOT write task briefs yet.

Only list candidate patches.

Each candidate must specify:

```text
subphase
files likely affected
behavioral contract
expected tests
whether change is truly necessary
```

## 14. Final recommendation

End with one of:

```text
PHASE15_EXTERNAL_AUDIT_COMPLETE_NO_PATCH_REQUIRED
```

or:

```text
PHASE15_EXTERNAL_AUDIT_COMPLETE_PATCH_CANDIDATES_FOUND
```

This is NOT a Phase 15 final gate.

---

# 13. QUALITY BAR

A high-quality finding looks like:

```text
AronaAI
backend/app/memory/retrieval.py
implements hybrid lexical + vector retrieval with recent-injection suppression.

Our equivalent
furina/cognition/... [exact path]
already has derived semantic lookup but lacks / has equivalent cooldown.

Decision
ADAPT

Reason
cooldown reduces repetitive autobiographical recall without changing source-of-truth authority.

Target
15E Retrieval

Not adopted yet.
```

A LOW-quality finding looks like:

```text
AronaAI has memory.
We should improve our memory.
```

The second form is unacceptable.

---

# 14. FALSE-POSITIVE GUARD

Do not recommend a patch unless ALL are true:

```text
1. External mechanism exists in code.
2. Our current code does not already solve it equivalently.
3. The mechanism improves a real Phase 15 behavior/invariant.
4. It does not violate C1-C7 authority.
5. It belongs to Phase 15.
6. It can be tested.
```

If any condition fails:

```text
NO_CHANGE
REJECT
or LATER
```

---

# 15. OUR CURRENT ARCHITECTURE MUST WIN TIES

If:

```text
external design ~= our design
```

choose:

`NO_CHANGE`

If:

```text
external design is simpler but loses provenance/truth boundaries
```

choose:

`REJECT`

If:

```text
external design has a useful behavior but incompatible persistence model
```

choose:

`ADAPT`

Do not redesign stable architecture for novelty.

---

# 16. STATIC SEARCH OF OUR REPOSITORY

Before recommending any delta, search our current code for an existing equivalent.

At minimum inspect relevant areas under:

```text
furina/cognition/
furina/memory/
furina/relationship/
furina/persona/
furina/dialogue/
furina/runtime/
data/canon/
tests/cognition/
tests/memory/
tests/relationship/
```

Exact directories may differ; follow actual tree.

The report must cite exact Furina file paths for every claimed gap.

---

# 17. NO IMPLEMENTATION / STOP CONDITION

Once the report is complete:

```text
write report
→ ensure manifest/task brief/report paths are correct
→ optional docs-only commit/push if explicitly requested by operator
→ STOP
```

Do NOT:

```text
implement deltas
create Phase 15 patch branch
modify production files
add tests
change Canon evidence
change memory schema
change relationship model
change retrieval
start Hermes
```

Final line must be exactly one of:

```text
PHASE15_EXTERNAL_AUDIT_COMPLETE_NO_PATCH_REQUIRED
```

or:

```text
PHASE15_EXTERNAL_AUDIT_COMPLETE_PATCH_CANDIDATES_FOUND
```

---

# 18. PURPOSE OF THE NEXT STEP

The NEXT Phase 15 document will be written only after this audit is externally reviewed.

If useful deltas survive review, the next step will be:

```text
External Audit
    ↓
Reviewer filters false positives
    ↓
Phase 15 Delta Decision / Acceptance
    ↓
ONE bounded implementation task at a time
```

Do not pre-write implementation tasks before the audit result exists.

---

# 19. CORE PRINCIPLE

> **External repositories are evidence of possible engineering solutions, not authority over Furina's architecture.**
>
> **Read code first, compare against what we already have, preserve truth boundaries, and only change the product when a real measurable delta survives review.**
