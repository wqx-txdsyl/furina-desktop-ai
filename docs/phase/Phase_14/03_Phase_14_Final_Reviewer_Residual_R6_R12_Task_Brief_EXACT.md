# Phase 14 — Final Reviewer Residual R6–R12 Task Brief
# FINAL Cognitive Truth / Provenance / Production-Path Closure
# EXACT TASK BRIEF

Document path:

phase/Phase_14/03_Phase_14_Final_Reviewer_Residual_R6_R12_Task_Brief_EXACT.md

Repository:

wqx-txdsyl/furina-desktop-ai

Reviewer baseline / exact starting SHA:

41bec530f80dd7925b359dc2434d7f00754636cc

Expected parent implementation SHA already included in baseline:

d9f2e650b8a60a619dcdc1db3f6385527285ce4f

Recommended new branch:

fix/phase14-final-reviewer-r6-r12

Reviewer:

GPT-5.6 Sol

Current external reviewer verdict at baseline:

PHASE_14_FINAL_GATE = FAIL

This task exists ONLY to close the final reviewer residuals R6–R12 described below.

Do NOT start Phase 16.
Do NOT implement Hermes.
Do NOT redesign C1–C7.
Do NOT redesign Director.
Do NOT redesign RelationshipEngine.
Do NOT redesign the Agent permission architecture.
Do NOT redesign frontend/GUI.
Do NOT reopen already-correct Phase 14 contracts.

The coding agent MUST NOT declare PHASE_14_FINAL_GATE_PASS.

Only the external reviewer may issue final PASS.

======================================================================
0. PHASE DOCUMENTATION PROTOCOL
======================================================================

The repository now uses the canonical recovery/phase documentation tree:

phase/
├── README_RECOVERY.md
├── RECOVERY_LEDGER.md
├── Phase_01/
├── ...
├── Phase_13/
└── Phase_14/
    ├── 00_MANIFEST.md
    ├── 00_PHASE14_ORIGINAL_CORE_FUNCTIONAL_PRODUCT_CLOSEOUT_RECONSTRUCTED.md
    ├── 01_Phase_14_Final_Closure_Patch_Task_Brief_EXACT.md
    ├── 02_Phase_14_Reviewer_Residual_Closure_Task_Brief_EXACT.md
    └── 03_Phase_14_Final_Reviewer_Residual_R6_R12_Task_Brief_EXACT.md

THIS task brief is Phase 14 document #03.

Before finishing the task:

1. Ensure this task brief exists at:

   phase/Phase_14/03_Phase_14_Final_Reviewer_Residual_R6_R12_Task_Brief_EXACT.md

2. Create the closeout report at:

   phase/Phase_14/04_Phase_14_Final_Reviewer_Residual_R6_R12_Closeout_Report_EXACT.md

3. Update:

   phase/Phase_14/00_MANIFEST.md

   using its EXISTING format/style.

4. Update:

   phase/RECOVERY_LEDGER.md

   only if the ledger's existing convention records completed implementation tasks there.

5. Do NOT create random Phase 14 reports under docs/.

6. Do NOT create or invent a Phase_14/99_EXACT_RECOVERY_CHRONOLOGY.md unless the repository's existing recovery convention already requires one.

Preserve the existing recovery-document format rather than inventing a new one.

======================================================================
1. BASELINE TRUTH
======================================================================

The external reviewer audited:

e116a51d96677a412b6ea8ecf05516572cfdf4c0
    ↓
d9f2e650b8a60a619dcdc1db3f6385527285ce4f
    ↓
41bec530f80dd7925b359dc2434d7f00754636cc

The combined range contains the actual production fixes plus reviewer-locked tests.

Confirmed-good work that MUST NOT be redesigned:

A. C4 lifecycle storage exists:
   - transition_event_id
   - transition_reason
   - persistence/reload

B. MemoryEngine.consolidate now preserves Experience.source_event_ids.

C. Scheduler no longer directly calls MemoryEngine.consolidate for USER_IGNORED.

D. SOCIAL_BID_STARTED → USER_IGNORED basic E1/E2 causal chain exists.

E. USER_IGNORED C3 can preserve:
   [USER_IGNORED event, SOCIAL_BID_STARTED event]

F. FUR-006 attribution was corrected to MAIN_STORY / Chapter IV / Act I.

G. FUR-052 attribution was corrected to CHARACTER_STORY / no main-story Act.

H. Preference/plan transition text now preserves the full verbatim utterance on the direct path.

I. RelationshipEngine remains the relationship numeric truth owner.

Do NOT reopen these from scratch.

Patch only the remaining truth holes.

======================================================================
2. REVIEWER RESIDUAL SUMMARY
======================================================================

The final reviewer found these remaining blockers:

R6 — P0
C3 formation is still fail-open when C6 provenance creation fails.

R7 — P0
C2 completeness can still false-green on structurally valid but semantically invalid evidence.

R8 — P1
Social bid lifecycle is incomplete:
- E1 creation failure can still leave a pending bid.
- Furina-side interruption/preemption can later create a false USER_IGNORED.

R9 — P1
The claimed "real production Director E2E" reviewer test directly calls
Scheduler.on_mind_action_started and therefore does not lock the real wiring.

R10 — P1
Verbatim utterance is preserved, but the transition is not exactly linked to the
specific canonical USER_MESSAGE event/turn. Current test only proves string equality.

R11 — P1
pet / poke / drag remain collapsed into C6 event_type USER_PET even though the
objective timeline already defines USER_PET / USER_POKE / USER_DRAG separately.

R12 — FINAL VERIFICATION
Full suite was reported as:

1184 passed
4 failed

The four failures were described as Office dependency failures.

A final gate cannot accept failed tests merely because they are "known".

======================================================================
3. R6 — C3 FORMATION MUST FAIL CLOSED
======================================================================

Severity:

P0

Current defect:

App._observe_with_provenance currently behaves semantically like:

    try:
        E = cognition.record_event(USER_STATEMENT_OBSERVED)
        source_event_ids = [E]
    except:
        pass

    memory.observe(... source_event_ids=source_event_ids)

Therefore:

C6 append failure
    ↓
source_event_ids=[]
    ↓
MemoryEngine may still form a durable memory.

That violates the C3 provenance invariant.

----------------------------------------------------------------------
3.1 HARD INVARIANT
----------------------------------------------------------------------

For every NEW production C3 durable autobiographical memory:

source_event_ids MUST:

1. be non-empty;
2. contain real canonical C6 event IDs;
3. resolve to existing life_events rows;
4. exist BEFORE the durable C3 row is formed.

No C6 evidence:

NO NEW C3 MEMORY.

Required:

C6 formation failure
    ↓
C3 formation MUST FAIL CLOSED

Forbidden:

C6 failure
    ↓
provenance-less memory
    ↓
"we will repair provenance later"

No deferred provenance repair.

----------------------------------------------------------------------
3.2 REQUIRED PRODUCTION BEHAVIOR
----------------------------------------------------------------------

At minimum fix:

App._observe_with_provenance

If cognition is installed and:

record_event(...)
fails,

or returns no valid event,

or returns an event that cannot be resolved,

the method MUST:

- log the failure;
- return None;
- NOT call MemoryEngine.observe;
- NOT write a new C3 row.

Do not swallow the error and then continue into memory formation.

If the existing compatibility shell with cognition=None must remain for old isolated
unit tests, it must NOT be mistaken for the normal production path.

Production Furina runtime must never create provenance-less C3 through this fallback.

Prefer fail-closed behavior over compatibility magic.

----------------------------------------------------------------------
3.3 R6 REVIEWER-LOCKED TESTS
----------------------------------------------------------------------

Add tests proving at least:

R6-T1
Real App production observation path + forced cognition.record_event failure:

BEFORE:
memory count = N

AFTER:
memory count = N
no new durable memory.

R6-T2
Successful production conversation observation:

C6 USER_STATEMENT_OBSERVED exists
    ↓
C3 source_event_ids != []
    ↓
every source_event_id resolves to life_events.

R6-T3
No code path may convert:

C6 append exception
→ source_event_ids=[]
→ durable C3

R6-T4
Existing successful C3 routes remain valid:

USER_FEED
USER_PET/Poke/Drag after R11
USER_IGNORED
verified AGENT_COMPLETED

all preserve resolvable provenance.

Do not satisfy this only with a manually fabricated event ID in a test.

At least one test must exercise the actual Furina production ingress.

======================================================================
4. R7 — C2 SEMANTIC COMPLETENESS MUST NOT FALSE-GREEN
======================================================================

Severity:

P0

Current improvement:

The repository now has:

data/canon/furina_evidence_units.json

and machine-readable evidence attribution.

This is good and must be preserved.

Current remaining defect:

CanonHistoryStore.metrics() can still report:

MANDATORY_SPAN_SOURCE_COMPLETE

based mainly on whether an episode references a source whose:

status == USED

even when the semantic evidence cannot support that episode's declared quest/act.

Structural validity is NOT semantic source completeness.

----------------------------------------------------------------------
4.1 HARD RULE
----------------------------------------------------------------------

A source/evidence reference may count toward completeness only if its attribution is
semantically compatible with the claim being supported.

For an episode declaring:

quest = Chapter IV
act = I / II / III / IV / V

an evidence unit intended to satisfy that exact main-story act MUST be compatible with:

source_type = MAIN_STORY
quest = Chapter IV
act = the same exact act

A CHARACTER_STORY / VOICE_LINE / PROFILE item with act=null MUST NOT satisfy an exact
Chapter IV Act requirement merely because:

- its evidence_id exists;
- its source_id is USED;
- it concerns Furina;
- its source is official.

Example false-green that MUST be rejected:

episode.act = IV

evidence:
source_type = CHARACTER_STORY
act = null

Result MUST NOT be "Act IV semantically covered".

----------------------------------------------------------------------
4.2 DISTINGUISH TWO DIFFERENT COMPLETENESS CONCEPTS
----------------------------------------------------------------------

The current documentation mixes:

A. mandatory life-stage provenance completeness

and

B. Chapter IV Act I–V curated main-story coverage.

These are NOT the same metric.

Implement explicit truthful metrics.

Recommended conceptual split:

mandatory_life_stage_source_status

and

main_story_act_coverage_status

Exact internal names may differ if there is a strong compatibility reason, but the
semantics MUST be separate.

Mandatory life-stage completeness asks:

"Does every canonical life episode have semantically compatible provenance?"

Main-story Act coverage asks:

"Do Acts I, II, III, IV, V each have semantically attributed MAIN_STORY evidence?"

If current evidence has:

Act I = covered
Act II = no curated main-story unit
Act III = no curated main-story unit
Act IV = covered
Act V = covered

then the system MUST truthfully expose something equivalent to:

main_story_act_coverage_status = PARTIAL
missing_acts = ["II", "III"]

It MUST NOT describe Acts I–V as fully source-complete.

----------------------------------------------------------------------
4.3 DO NOT FABRICATE SOURCES
----------------------------------------------------------------------

If repository evidence does not contain valid Act II / Act III main-story units:

DO NOT invent evidence.

DO NOT relabel a Character Story as main story.

DO NOT turn version "4.1"/"4.2" into Act IV/V.

DO NOT assign a null-act voice line to an exact act.

DO NOT use model memory as canonical provenance.

Truthful PARTIAL is preferable to fake COMPLETE.

If valid official evidence already exists in the repository and can be correctly
attributed, it may be wired.

If not, report the gap.

----------------------------------------------------------------------
4.4 VALIDATOR REQUIREMENTS
----------------------------------------------------------------------

Strengthen CanonHistoryStore validation so that at minimum:

- duplicate evidence IDs fail;
- missing evidence IDs fail;
- incompatible exact act attribution fails;
- exact Chapter IV act cannot be satisfied by non-main-story null-act evidence;
- evidence source_type/quest/act compatibility is checked;
- semantic conflicts affect the corresponding completeness result.

Do NOT keep:

semantic_conflicts != []
while
status == SOURCE_COMPLETE.

----------------------------------------------------------------------
4.5 DOCUMENTATION CONSISTENCY
----------------------------------------------------------------------

Update:

docs/persona/FURINA_CANON_LIFE_SOURCE_MAP.md

and any current architecture wording that still falsely implies global full source coverage.

The document may say:

20 mandatory life stages are structurally/provenance covered

ONLY if the strengthened semantic validator proves it.

It must separately state current Act I–V coverage truth.

If Acts II/III remain missing curated main-story units, document that explicitly.

Do not delete the historical/deprecated table if it is intentionally retained, but it
must remain clearly non-authoritative.

----------------------------------------------------------------------
4.6 R7 REVIEWER-LOCKED TESTS
----------------------------------------------------------------------

R7-T1
Temporary fixture:

episode.act = IV

evidence:
source_type=CHARACTER_STORY
act=null

must NOT count as valid Act IV coverage.

R7-T2
Temporary fixture:

episode.act = IV

evidence:
MAIN_STORY
Chapter IV
act=I

must produce semantic conflict.

R7-T3
Temporary fixture:

MAIN_STORY
Chapter IV
act=IV

must be valid for Act IV.

R7-T4
FUR-006 remains:

MAIN_STORY
Chapter IV
Act I

R7-T5
FUR-052 remains:

CHARACTER_STORY
act=null

and cannot satisfy any exact main-story act.

R7-T6
Production metrics + source-map documentation agree.

R7-T7
If no Act II/III MAIN_STORY evidence exists:

main-story coverage MUST expose those missing acts.

Do NOT mutate production evidence inside tests merely to make them pass.
Use temporary fixture files where a counterexample is needed.

======================================================================
5. R8 — SOCIAL BID LIFECYCLE MUST BE CAUSALLY VALID
======================================================================

Severity:

P1

The happy-path design is correct:

SOCIAL_BID_STARTED E1
    ↓
response window expires
    ↓
USER_IGNORED E2
    ↓
C3 provenance [E2, E1]

Preserve it.

Two holes remain.

----------------------------------------------------------------------
5.1 E1 CREATION FAILURE MUST FAIL CLOSED
----------------------------------------------------------------------

Current possible behavior:

record SOCIAL_BID_STARTED
    ↓ exception
source_event_id=""
    ↓
_pending_social_bid still created
    ↓
later USER_IGNORED
    ↓
memory provenance only [E2]

Forbidden for a real production bid.

Required:

If canonical E1 cannot be persisted:

DO NOT open the pending response window.

No canonical bid event:

NO canonical ignore timer.

----------------------------------------------------------------------
5.2 FURINA-SIDE CANCELLATION
----------------------------------------------------------------------

A user may only be judged as "not responding" while the originating Furina social bid
is still valid.

Example current false causal chain:

Furina starts approach_user
    ↓
SOCIAL_BID_STARTED
    ↓
Agent preempts Furina
    ↓
Furina stops approaching
    ↓
user never had a valid continuing bid to answer
    ↓
timer expires
    ↓
USER_IGNORED    <-- WRONG

Required:

A pending social bid must be invalidated when the Furina-side initiating attempt is
cancelled/interrupted before the response window legitimately completes.

At minimum inspect and correctly handle:

- mind action preemption;
- user takeover that terminates the originating action;
- activity replacement/switch if it invalidates the bid;
- shutdown/stop if pending;
- any explicit cancellation of the originating social action.

Existing legitimate behavior remains:

user response
→ pending bid cleared
→ no USER_IGNORED.

----------------------------------------------------------------------
5.3 IMPLEMENTATION SHAPE
----------------------------------------------------------------------

A dedicated helper such as:

_cancel_social_bid(reason)

is acceptable and likely preferable to scattered assignment.

It must be idempotent.

Do not create USER_IGNORED during cancellation.

A SOCIAL_BID_CANCELLED C6 event is optional if useful for objective auditability,
but do not introduce it merely for decoration.

If introduced:

- add it explicitly to EventTimelineStore whitelist;
- reference the originating SOCIAL_BID_STARTED;
- ensure exactly-once;
- do not form a C3 memory from cancellation.

----------------------------------------------------------------------
5.4 R8 TESTS
----------------------------------------------------------------------

R8-T1
Force SOCIAL_BID_STARTED record failure:

_pending_social_bid is None
USER_IGNORED later == 0
C3 ignore memory == 0.

R8-T2
approach_user starts normally:

SOCIAL_BID_STARTED == 1

then Furina is preempted by Agent before timeout:

USER_IGNORED == 0
ignore C3 == 0.

R8-T3
user responds normally:

bid clears
no ignore.

R8-T4
ordinary uninterrupted timeout:

E1 == 1
E2 == 1
memory provenance == [E2, E1].

R8-T5
repeated cancellation/ticks remain exactly-once/no false ignore.

======================================================================
6. R9 — REAL DIRECTOR → APP → SCHEDULER PRODUCTION TEST
======================================================================

Severity:

P1 / false-green test

Current reviewer test claims:

Director execution
→ Scheduler
→ social bid

but actually begins with:

sched.on_mind_action_started("approach_user")

That bypasses the wiring it claims to prove.

Therefore deleting the production App._on_execute → Scheduler call would not fail the test.

----------------------------------------------------------------------
6.1 REQUIRED E2E PATH
----------------------------------------------------------------------

At least one reviewer-locked test MUST drive the actual production chain:

real Furina
    ↓
real Director
    ↓
Director.submit(ActionRequest(source="mind", action="approach_user", ...))
    ↓
real director.drain()
    ↓
App._on_execute
    ↓
Scheduler.on_mind_action_started
    ↓
SOCIAL_BID_STARTED
    ↓
timeout
    ↓
USER_IGNORED
    ↓
CognitionHub
    ↓
C3

Do NOT directly invoke:

sched.on_mind_action_started(...)

as the start of this test.

The test may manipulate the response deadline after the real production start in order
to avoid a real 60-second wait.

----------------------------------------------------------------------
6.2 FALSE-GREEN REQUIREMENT
----------------------------------------------------------------------

The test must fail if the following production wiring is removed:

App._on_execute
→ Scheduler.on_mind_action_started

This is the point of the test.

Also include a real Director preemption counterexample if practical:

mind social action active
    ↓
agent higher-priority takeover
    ↓
pending bid invalidated
    ↓
no USER_IGNORED.

Do not replace the real Director with a fake callback-only object.

======================================================================
7. R10 — EXACT USER_MESSAGE EVENT IDENTITY
======================================================================

Severity:

P1

Current good behavior:

transition payload.statement preserves the verbatim utterance.

Current insufficient behavior:

the test finds:

USER_PREFERENCE_CHANGED.statement == utterance

and separately finds:

some USER_MESSAGE.text == same utterance.

That proves string equality, NOT event identity.

Two identical utterances in two different turns break the proof.

----------------------------------------------------------------------
7.1 REQUIRED PROVENANCE CONTRACT
----------------------------------------------------------------------

For a direct user turn that causes a C4 lifecycle transition:

canonical USER_MESSAGE event U
    ↓ exact identity edge
semantic transition event T
    ↓
C4 lifecycle row

must be recoverable by EVENT ID, not by searching equal text.

Required trace must support either:

C4 row
→ transition event T
→ source USER_MESSAGE U

or an equally strong direct representation.

The transition must identify the specific USER_MESSAGE event that caused it.

String equality alone is forbidden as provenance.

----------------------------------------------------------------------
7.2 TURN IDENTITY
----------------------------------------------------------------------

The canonical USER_MESSAGE must remain bound to the same DirectDialogueQueue turn identity.

Preferred invariant:

USER_MESSAGE.turn_id
==
transition event.turn_id
==
DirectTurn.turn_id

where applicable.

Do NOT invent a second competing user-turn identity.

DirectDialogueQueue.turn_id remains the direct user ingress identity.

----------------------------------------------------------------------
7.3 ORDERING PROBLEM TO SOLVE
----------------------------------------------------------------------

Current production ordering is roughly:

apply_user_message(text)
    ↓
transition may be created
    ↓
freeze snapshot
    ↓
DirectDialogueQueue.submit()
    ↓
turn_id becomes known
    ↓
USER_MESSAGE event recorded

This makes exact transition → USER_MESSAGE linkage impossible at transition creation time.

Fix the ordering without violating existing direct-lane guarantees.

A valid implementation may use a small two-phase DirectDialogueQueue ingress API, for example:

reserve direct turn identity
    ↓
record canonical USER_MESSAGE with turn_id
    ↓
apply C4 semantics using that exact event ID
    ↓
freeze owner snapshot
    ↓
enqueue the already-reserved turn for worker execution

This is only an example.

The exact implementation may differ.

Hard requirements:

- do NOT read or manually mutate private `_next_turn_id` from App;
- do NOT allow the worker to begin before owner semantic effects + snapshot freeze are complete;
- total direct-turn timeout must still begin at ingress/reservation, not be reset on enqueue;
- FIFO must remain strict;
- no turn-id holes that permanently block later turns;
- if owner preparation fails after reservation, the turn must reach an observable terminal/cancelled state rather than remain forever pending.

----------------------------------------------------------------------
7.4 DERIVED TRANSITION EVENT
----------------------------------------------------------------------

Preserve:

USER_PREFERENCE_CHANGED
USER_PLAN_COMPLETED

as useful C6 semantic transition events unless there is a compelling compatibility reason not to.

Recommended provenance:

USER_MESSAGE U
    ↓
USER_PREFERENCE_CHANGED / USER_PLAN_COMPLETED T
    payload/source metadata contains exact U.event_id
    same turn_id
    ↓
user_model_items.transition_event_id = T.event_id

Then:

row
→ T
→ U

is exact and deterministic.

Do NOT create a circular provenance chain.

Do NOT point T back to itself.

----------------------------------------------------------------------
7.5 R10 TESTS
----------------------------------------------------------------------

R10-T1
Real submit_user_message preference correction:

row
→ exact transition event
→ exact canonical USER_MESSAGE event
→ verbatim utterance.

R10-T2
Same for plan completion.

R10-T3
Two separate turns contain the SAME correction utterance.

The transition caused by turn #2 must link to turn #2 USER_MESSAGE event,
not merely "an event with matching text".

R10-T4
All linked events share the correct turn identity.

R10-T5
No circular provenance.

R10-T6
DirectDialogueQueue FIFO and deadline tests remain green.

R10-T7
If preparation fails after turn reservation, no permanent pending turn / sequence hole exists.

======================================================================
8. R11 — PET / POKE / DRAG MUST BE DISTINCT C6 OBJECTIVE EVENTS
======================================================================

Severity:

P1

Current production behavior:

petting → USER_PET {kind="petting"}
poke    → USER_PET {kind="poke"}
drag    → USER_PET {kind="drag"}

This makes the objective event_type itself inaccurate.

EventTimelineStore already defines:

USER_PET
USER_POKE
USER_DRAG

Use them.

----------------------------------------------------------------------
8.1 REQUIRED OBJECTIVE MAPPING
----------------------------------------------------------------------

Canonical C6 mapping:

petting
→ USER_PET

poke
→ USER_POKE

drag
→ USER_DRAG

Do NOT use USER_PET as a generic "physical interaction" umbrella.

Payload may still contain:

count
kind
other bounded observable fields

but event_type itself must be truthful.

----------------------------------------------------------------------
8.2 CONSOLIDATOR
----------------------------------------------------------------------

Update Consolidator so all three canonical event types receive correct deterministic
memory semantics where the memory threshold is satisfied.

Examples:

USER_PET
→ "用户轻轻摸了摸我的头"
→ event_type user_positive_touch

USER_POKE
→ ordinary poke:
   "用户戳了我一下"

→ repeated poke:
   "用户反复戳了我N下"

USER_DRAG
→ "用户把我拎起来移动"

Do not classify USER_DRAG as Event-only if the established product semantics say an
important drag interaction may form autobiographical memory.

Preserve threshold/reinforcement behavior.

----------------------------------------------------------------------
8.3 R11 TESTS
----------------------------------------------------------------------

At least one test must drive the true production interaction path.

R11-T1
petting:

C6 contains exactly one USER_PET
no USER_POKE
no USER_DRAG.

R11-T2
poke:

C6 contains exactly one USER_POKE
no USER_PET caused by that poke.

R11-T3
drag:

C6 contains exactly one USER_DRAG
no USER_PET caused by that drag.

R11-T4
C3 content matches the true physical interaction.

R11-T5
repeated high-count poke produces annoyance/repeated-poke semantics, not pet semantics.

R11-T6
all formed C3 memories preserve exact C6 provenance.

======================================================================
9. R12 — ZERO-FAIL VERIFICATION / OFFICE DEPENDENCY TRUTH
======================================================================

Severity:

FINAL VERIFICATION BLOCKER

Current reported full-suite result at baseline:

1184 passed
4 failed

The four failures were reported as Office missing-dependency failures:

docx
pptx
xlsx
docx-plan related paths

"Known environment failure" is NOT equivalent to PASS.

----------------------------------------------------------------------
9.1 FIRST CLASSIFY THE FOUR FAILURES
----------------------------------------------------------------------

Before changing code:

reproduce the four failures and determine whether they are caused by:

A. dependency declared by project but absent from the current environment;

B. runtime Office dependency used by production code but missing from pyproject.toml;

C. actual production bug;

D. test-environment configuration problem.

Do not guess.

Record the exact four failing test names and root exceptions.

----------------------------------------------------------------------
9.2 DEPENDENCY DECLARATION RULE
----------------------------------------------------------------------

Current pyproject runtime dependencies do NOT include typical Office libraries such as:

python-docx
python-pptx
openpyxl

If production Office capabilities genuinely import/use these packages, and they are
required for advertised production tools such as:

docx.create
pptx.create
xlsx.create
document planning/execution,

then dependency truth must be fixed.

A production runtime dependency belongs in project metadata.

Do NOT require developers to know an undocumented manual pip command.

If confirmed required:

add the appropriate packages to pyproject.toml runtime dependencies with reasonable
minimum versions compatible with the current implementation.

Do NOT randomly pin exact versions without reason.

Do NOT add packages merely because their names look related.

Inspect the actual imports first.

----------------------------------------------------------------------
9.3 FORBIDDEN VERIFICATION CHEATS
----------------------------------------------------------------------

Do NOT:

- skip the four tests;
- xfail them;
- weaken their assertions;
- delete them;
- mark Office capability unavailable only to make tests green;
- catch ImportError and report fake success;
- change a real failure into a silent no-op;
- lower coverage by removing test collection;
- alter requires-python as part of this task unless an unrelated proven blocker makes
  it absolutely necessary.

Python-version redesign is OUT OF SCOPE.

----------------------------------------------------------------------
9.4 FINAL TEST REQUIREMENT
----------------------------------------------------------------------

Targeted tests first.

Then run the full suite.

Final acceptance requires:

0 failed

No new skip.
No new xfail.
No weakened reviewer tests.

For the FINAL candidate, run the complete suite THREE consecutive times.

Required:

FULL RUN #1: 0 failed
FULL RUN #2: 0 failed
FULL RUN #3: 0 failed

If any run fails:

do NOT output READY_FOR_FINAL_REVIEW.

Report the exact failure.

======================================================================
10. REVIEWER-LOCKED TEST FILE
======================================================================

Add a new test file rather than silently mutating the previous reviewer evidence.

Preferred path:

tests/cognition/test_phase14_final_reviewer_r6_r12.py

Previous files must remain:

tests/cognition/test_phase14_final_closure.py
tests/cognition/test_phase14_residual_closure.py

Do NOT weaken or remove their tests.

If an old test now encodes a contract that is explicitly superseded by R6–R12
(for example old USER_PET collapse semantics), update it ONLY where logically required
and state exactly why.

No broad test rewrite.

The new file should explicitly contain reviewer-locked counterexamples for:

R6
R7
R8
R9
R10
R11

R12 is verified by full-suite execution and dependency evidence.

======================================================================
11. REQUIRED FALSE-GREEN COUNTEREXAMPLES
======================================================================

The following MUST be demonstrated.

COUNTEREXAMPLE A — provenance fail-open

Force C6 USER_STATEMENT_OBSERVED append failure.

Expected:

no new C3.

COUNTEREXAMPLE B — fake Canon completeness

Exact Act IV episode + CHARACTER_STORY/null-act evidence.

Expected:

not semantically Act-IV-covered.

COUNTEREXAMPLE C — invalidated social bid

approach_user starts
→ Agent preempts
→ deadline passes.

Expected:

no USER_IGNORED.

COUNTEREXAMPLE D — removed production wiring

The real Director E2E test must depend on:

Director
→ App._on_execute
→ Scheduler.

No direct Scheduler start call.

COUNTEREXAMPLE E — duplicate identical utterance

Turn A:
"我现在不喝咖啡了"

Turn B:
"我现在不喝咖啡了"

Transition caused by B MUST resolve by event ID / turn ID to B.

Text equality is insufficient.

COUNTEREXAMPLE F — physical event identity

poke cannot produce C6 USER_PET.
drag cannot produce C6 USER_PET.

======================================================================
12. STATIC ARCHITECTURE AUDIT AFTER PATCH
======================================================================

Before final report, perform a fresh repo-wide static audit.

Report:

1. all MemoryEngine.observe callers;
2. all MemoryEngine.consolidate callers;
3. all direct MemoryStore.insert callers;
4. all raw SQL writers to memories;
5. production App/Scheduler memory formation routes;
6. all social-bid open/cancel/expire routes;
7. all USER_MESSAGE creation sites;
8. all USER_PREFERENCE_CHANGED creation sites;
9. all USER_PLAN_COMPLETED creation sites;
10. pet/poke/drag C6 production emission sites;
11. Canon completeness computation sites;
12. Office package imports + corresponding pyproject dependency declarations.

Do not use function-name grep alone where AST/static semantic inspection is practical.

======================================================================
13. SCOPE — ALLOWED FILES
======================================================================

Likely production files may include:

furina/app.py
furina/runtime/scheduler.py
furina/runtime/dialogue_queue.py
furina/cognition/hub.py
furina/cognition/consolidation/consolidator.py
furina/cognition/stores/event_timeline.py
furina/cognition/stores/canon_history.py
furina/cognition/stores/user_model.py
furina/cognition/stores/autobiography.py
furina/memory/memory_engine.py
data/canon/*
docs/persona/FURINA_CANON_LIFE_SOURCE_MAP.md
pyproject.toml

tests/cognition/test_phase14_final_reviewer_r6_r12.py

plus the required phase documentation:

phase/Phase_14/03_Phase_14_Final_Reviewer_Residual_R6_R12_Task_Brief_EXACT.md
phase/Phase_14/04_Phase_14_Final_Reviewer_Residual_R6_R12_Closeout_Report_EXACT.md
phase/Phase_14/00_MANIFEST.md
phase/RECOVERY_LEDGER.md if required by existing ledger convention

This is not permission to touch every listed file.

Modify only what the exact fixes require.

======================================================================
14. OUT OF SCOPE / DO NOT TOUCH
======================================================================

Do NOT implement:

- Hermes
- Phase 16 Work Sovereignty
- WorkDisposition production routing
- frontend
- GUI redesign
- TTS
- ASR
- renderer
- animation
- asset pipeline
- new C8
- second Memory DB
- second UserModel
- second Relationship truth
- new Persona architecture
- new Emotion architecture
- new Agent planner architecture
- permission redesign
- Office overwrite-policy redesign
- Phase 14 scope/path authorization redesign

Do not refactor unrelated code.

======================================================================
15. PRE-IMPLEMENTATION GIT GATE
======================================================================

Before editing:

git status --short

Confirm current repository contains exact baseline:

41bec530f80dd7925b359dc2434d7f00754636cc

Create / switch to:

fix/phase14-final-reviewer-r6-r12

from that exact baseline.

Do NOT base this task on master.

Do NOT discard unrelated user changes.

If the worktree contains unrelated modifications that cannot safely be preserved:

STOP and report.

======================================================================
16. IMPLEMENTATION ORDER
======================================================================

Recommended order:

STEP 1
Reproduce current reviewer counterexamples BEFORE modification.

STEP 2
R6 fail-closed C3 provenance.

STEP 3
R7 semantic Canon completeness validator + truthful metrics/docs.

STEP 4
R8 social-bid lifecycle invalidation.

STEP 5
R9 real Director production E2E test.

STEP 6
R10 exact USER_MESSAGE event identity.

STEP 7
R11 pet/poke/drag C6 split.

STEP 8
R12 Office dependency / zero-fail test environment closure.

STEP 9
Run previous Phase 14 reviewer tests.

STEP 10
Run Phase 15 preservation tests.

STEP 11
Run full suite ×3.

STEP 12
Static architecture audit.

STEP 13
Write Phase 14 closeout report.

STEP 14
Update Phase 14 manifest / recovery ledger.

STEP 15
Commit and push exact branch.

STEP 16
STOP for independent reviewer.

======================================================================
17. REQUIRED TEST GATES
======================================================================

Gate A — new R6–R12 tests

All pass.

Gate B — previous Phase 14 final closure:

tests/cognition/test_phase14_final_closure.py

All pass.

Gate C — previous Phase 14 residual closure:

tests/cognition/test_phase14_residual_closure.py

All pass except only those assertions that must be explicitly updated because R11
correctly replaces USER_PET collapse semantics.

Any modified old assertion must be reported.

Gate D — relevant cognition / memory / scheduler / dialogue queue / Director integration tests

All pass.

Gate E — Phase 15 preservation

Run existing Phase 15 / Phase 15.1 cognitive tests.

No regression in:

C1/C2 immutability
C3 provenance/lifecycle
C4 user model
C5 relationship provenance
C6 timeline
C7 agent truth
bounded context
restart idempotency
vector derived status
Focalors/Furina boundary

Gate F — Agent Foundation preservation

No regression in:

task-scoped authorization
scope-before-permission
derived-path checking
Office no-silent-overwrite
C7 verified completion semantics

Gate G — FULL SUITE ×3

All three runs:

0 failed.

======================================================================
18. REQUIRED PHASE CLOSEOUT REPORT
======================================================================

Create:

phase/Phase_14/04_Phase_14_Final_Reviewer_Residual_R6_R12_Closeout_Report_EXACT.md

It must contain:

# Phase 14 Final Reviewer Residual R6–R12 — Closeout Report

## 1. Result

Only:

READY_FOR_FINAL_REVIEW

or

NOT_READY_FOR_FINAL_REVIEW

Do NOT output:

PHASE_14_FINAL_GATE_PASS

## 2. Baseline

baseline_sha:
branch:
final_sha:

## 3. Commit list

List every commit created by this task.

## 4. Modified files

For each:

file
reason
contract affected

## 5. R6 — C3 fail-closed proof

Show BEFORE counterexample.

Show AFTER production path.

Show the exact behavior when C6 append fails.

## 6. R7 — Canon completeness proof

Report:

mandatory life-stage status
main-story Act I–V status
missing acts if any
evidence attribution conflicts
FUR-006 attribution
FUR-052 attribution

Explicitly explain why an official but semantically wrong source can no longer make
completeness green.

## 7. R8 — Social bid lifecycle

Show:

normal start
normal response
normal timeout
E1 failure
preemption cancellation

Show event counts.

## 8. R9 — Real Director E2E

Show actual chain:

Director.submit
→ drain
→ App._on_execute
→ Scheduler
→ SOCIAL_BID_STARTED
→ USER_IGNORED
→ C3

State why deleting the production callback now fails the test.

## 9. R10 — Exact utterance provenance

Provide a real trace with IDs:

DirectTurn.turn_id =
USER_MESSAGE.event_id =
transition event.id =
transition source USER_MESSAGE id =
C4 row.transition_event_id =

Also show duplicate-identical-utterance test proof.

## 10. R11 — physical event truth

Show actual:

petting C6 types
poke C6 types
drag C6 types

and C3 content/provenance.

## 11. R12 — Office / dependency truth

List the four original failures.

For each:

root cause
fix
dependency declaration if applicable

## 12. Static sink / authority audit

List:

observe callers
consolidate callers
MemoryStore.insert callers
raw memories SQL
C6 physical interaction emitters
USER_MESSAGE creation sites
social bid lifecycle sites

## 13. Test results

New reviewer tests:
Previous final closure:
Previous residual closure:
Phase 15 preservation:
Agent integration:

Full run #1:
passed:
failed:
skipped:
duration:

Full run #2:
passed:
failed:
skipped:
duration:

Full run #3:
passed:
failed:
skipped:
duration:

## 14. Git state

git status --short before commit:
git status --short after commit:
push result:
remote branch:
final remote SHA:

## 15. Remaining gaps

If none:

No known R6–R12 implementation blockers remain.
Final PASS is intentionally deferred to the independent reviewer.

If any:

list them truthfully.

======================================================================
19. COMMIT / PUSH REQUIREMENT
======================================================================

This time implementation MUST be committed and pushed.

Do not finish with:

"changes are uncommitted"

or

"ready for user to push".

Push:

fix/phase14-final-reviewer-r6-r12

Report exact remote SHA.

Do not push to master.

Do not merge.

======================================================================
20. FINAL ACCEPTANCE CHECKLIST
======================================================================

Before saying READY_FOR_FINAL_REVIEW confirm ALL:

[ ] exact baseline 41bec530 was used

[ ] R6: C6 formation failure cannot create new provenance-less C3

[ ] R6: successful production C3 provenance resolves to real C6

[ ] R7: semantic evidence compatibility participates in completeness

[ ] R7: Character Story / Voice Line cannot satisfy exact main-story Act merely by being official

[ ] R7: mandatory life-stage status and Act I–V coverage are not conflated

[ ] R7: Act II/III remain truthfully missing if no real evidence exists

[ ] R7: FUR-006 remains MAIN_STORY Act I

[ ] R7: FUR-052 remains CHARACTER_STORY with no act

[ ] R8: failed SOCIAL_BID_STARTED persistence cannot open pending bid

[ ] R8: Furina-side preemption invalidates pending bid

[ ] R8: preempted bid cannot later produce USER_IGNORED

[ ] R8: ordinary uninterrupted timeout still produces exactly E1/E2/C3

[ ] R9: reviewer test uses real Director.submit + drain

[ ] R9: production App._on_execute wiring is actually locked

[ ] R10: transition provenance uses exact USER_MESSAGE event identity

[ ] R10: duplicate identical utterances cannot confuse provenance

[ ] R10: DirectDialogueQueue FIFO remains intact

[ ] R10: ingress deadline semantics remain intact

[ ] R10: no pending/sequence hole if reserved turn preparation fails

[ ] R11: petting emits USER_PET

[ ] R11: poke emits USER_POKE

[ ] R11: drag emits USER_DRAG

[ ] R11: C3 semantics and provenance remain correct

[ ] R12: all original Office failures are classified and actually resolved

[ ] no skip added

[ ] no xfail added

[ ] no assertions weakened to hide failures

[ ] previous Phase 14 reviewer tests remain valid

[ ] Phase 15 preservation tests remain green

[ ] Agent permission/scope foundation remains green

[ ] full suite run #1 = 0 failed

[ ] full suite run #2 = 0 failed

[ ] full suite run #3 = 0 failed

[ ] phase/Phase_14/03 task document exists

[ ] phase/Phase_14/04 closeout document exists

[ ] phase/Phase_14/00_MANIFEST.md updated

[ ] RECOVERY_LEDGER updated if required by existing convention

[ ] implementation committed

[ ] branch pushed

[ ] exact remote final SHA reported

[ ] no Phase 16 work started

======================================================================
21. STOP CONDITION
======================================================================

After:

implementation
+
tests
+
phase documentation
+
commit
+
push
+
final report

STOP.

Do not start another phase.

Do not merge.

Do not claim external reviewer approval.

Your final response must end with exactly one of:

READY_FOR_FINAL_REVIEW

or

NOT_READY_FOR_FINAL_REVIEW: <exact blocker>

The independent reviewer will inspect the pushed exact SHA and determine whether:

PHASE_14_FINAL_GATE_PASS

may finally be issued.
