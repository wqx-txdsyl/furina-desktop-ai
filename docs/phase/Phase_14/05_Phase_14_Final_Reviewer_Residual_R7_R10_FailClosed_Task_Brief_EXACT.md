# Phase 14 — Final Reviewer Residual R7 / R10 Fail-Closed Task Brief
# FINAL Semantic Completeness / Exact Provenance Closure
# EXACT TASK BRIEF

Document path:

`docs/phase/Phase_14/05_Phase_14_Final_Reviewer_Residual_R7_R10_FailClosed_Task_Brief_EXACT.md`

Repository:

`wqx-txdsyl/furina-desktop-ai`

Reviewer baseline / exact starting SHA:

`102d46b56c7e27fa37ba180d43e12b203ca5fd39`

Implementation commit already included in baseline:

`b8c0eb934501dc713e28779fa3f3ff9382a2d020`

Recommended branch:

`fix/phase14-final-r7-r10-failclosed`

Reviewer:

`GPT-5.6 Sol`

Current external reviewer verdict at baseline:

`PHASE_14_FINAL_GATE = FAIL`

This task exists ONLY to close the two remaining independent-review blockers described below:

- **R7 residual — P0:** Canon semantic completeness still false-greens when a non-exact-act episode references a missing / unregistered evidence ID.
- **R10 residual — P1:** direct user-turn C4 lifecycle mutation still fails open when canonical `USER_MESSAGE` persistence fails; `EventBridge._seen` can also retain a failed key and poison retry.

Do NOT reopen R6 / R8 / R9 / R11 / R12.
Do NOT redesign C1–C7.
Do NOT redesign MemoryEngine formation authority.
Do NOT redesign Director.
Do NOT redesign Scheduler social-bid semantics.
Do NOT redesign interaction event semantics.
Do NOT start Phase 15 / Phase 16 / Hermes / frontend / renderer / asset work.
Do NOT perform unrelated cleanup.
Do NOT touch `nul` except to leave it untracked.
Do NOT fabricate Canon sources.
Do NOT weaken any existing reviewer-locked assertion.

The coding agent MUST NOT declare `PHASE_14_FINAL_GATE_PASS`.

Only the external reviewer may issue final PASS.

---

# 0. PHASE DOCUMENTATION PROTOCOL

The repository currently uses:

```text
docs/phase/
├── README_RECOVERY.md
├── RECOVERY_LEDGER.md
│
├── Phase_01/
├── ...
├── Phase_13/
└── Phase_14/
    ├── 00_MANIFEST.md
    ├── 00_PHASE14_ORIGINAL_CORE_FUNCTIONAL_PRODUCT_CLOSEOUT_RECONSTRUCTED.md
    ├── 01_Phase_14_Final_Closure_Patch_Task_Brief_EXACT.md
    ├── 02_Phase_14_Reviewer_Residual_Closure_Task_Brief_EXACT.md
    ├── 03_Phase_14_Final_Reviewer_Residual_R6_R12_Task_Brief_EXACT.md
    ├── 04_Phase_14_Final_Reviewer_Residual_R6_R12_Closeout_Report_EXACT.md
    └── 05_Phase_14_Final_Reviewer_Residual_R7_R10_FailClosed_Task_Brief_EXACT.md
```

THIS task brief is Phase 14 document **#05**.

Before finishing the task:

1. Ensure this exact task brief exists at:

   `docs/phase/Phase_14/05_Phase_14_Final_Reviewer_Residual_R7_R10_FailClosed_Task_Brief_EXACT.md`

2. Create the closeout report at:

   `docs/phase/Phase_14/06_Phase_14_Final_Reviewer_Residual_R7_R10_FailClosed_Closeout_Report_EXACT.md`

3. Update:

   `docs/phase/Phase_14/00_MANIFEST.md`

   using its existing format/style.

4. Update:

   `docs/phase/RECOVERY_LEDGER.md`

   only according to its existing convention.

5. Do NOT create another Phase 14 chronology unless the repository convention explicitly requires it.

6. Do NOT create random duplicate reports under another directory.

7. Preserve existing recovery status terminology:
   - `EXACT_RECOVERED`
   - `RECONSTRUCTED`

8. This file is an **EXACT task brief** generated for the current residual closure. Do not rename it into a reconstructed document.

---

# 1. BASELINE TRUTH

The external reviewer audited the pushed branch head:

```text
41bec530f80dd7925b359dc2434d7f00754636cc
    ↓
b8c0eb934501dc713e28779fa3f3ff9382a2d020
    ↓
102d46b56c7e27fa37ba180d43e12b203ca5fd39
```

Confirmed-good implementation that MUST remain frozen unless a direct regression is proven:

## R6 — C3 fail-closed

Production `App._observe_with_provenance` now:

```text
C6 USER_STATEMENT_OBSERVED append succeeds
    ↓
valid event_id
    ↓
MemoryEngine.observe(... source_event_ids=[event_id])
```

and:

```text
C6 append fails / invalid event_id
    ↓
return None
    ↓
NO new C3
```

Do not redesign it.

## R8 — Social-bid lifecycle

Confirmed:

```text
SOCIAL_BID_STARTED persistence failure
    ↓
NO pending social bid
```

and:

```text
executed:approach_user
    ↓
real preemption
    ↓
pending bid cancelled
    ↓
NO false USER_IGNORED
```

Do not redesign it.

## R9 — Real Director production E2E

Reviewer-locked test now drives:

```text
Director.submit
    ↓
Director.drain
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
C3
```

Do not replace this with a fake or direct Scheduler call.

## R11 — Physical interaction event truth

Confirmed production mapping:

```text
petting → USER_PET
poke    → USER_POKE
drag    → USER_DRAG
```

and distinct deterministic C3 semantics.

Do not collapse these event types again.

## R12 — Office dependency truth

Production dependencies are now declared in `pyproject.toml`:

```text
python-docx>=0.8.11
python-pptx>=0.6.18
openpyxl>=3.0.7
```

Do not revert or optionalize these to make tests easier.

---

# 2. CURRENT FINAL BLOCKERS

Only two implementation blockers remain.

```text
R7-FC  — P0 — all-episode missing evidence validation
R10-FC — P1 — canonical USER_MESSAGE provenance must fail closed
```

There is also one tightly coupled R10 support defect:

```text
EventBridge._seen must not retain a key when append itself failed.
```

No other architecture work is authorized.

---

# 3. R7-FC — ALL EPISODES MUST FAIL ON MISSING / UNREGISTERED EVIDENCE

Severity:

`P0`

## 3.1 Current defect

Current `CanonHistoryStore._evidence_attribution_conflicts()` checks unregistered evidence only after an exact-act gate equivalent to:

```python
if episode.act not in ("I", "II", "III", "IV", "V"):
    continue
```

Therefore a non-exact-act canonical episode can contain:

```text
source_ids = [valid USED source]
evidence_ids = ["NON_EXISTENT_EVIDENCE_ID"]
act = null / span / non-exact
```

and escape the unregistered-evidence check entirely.

That can produce the false-green shape:

```text
valid USED source
+
missing evidence_id
+
non-exact-act episode
    ↓
no dangling source
no exact-act conflict
no exact-act support requirement
no duplicate
    ↓
mandatory_life_stage_source_status may become SOURCE_COMPLETE
```

This violates the already-frozen semantic rule:

> Missing evidence IDs must fail semantic completeness for ANY episode, not only exact Chapter IV Act episodes.

## 3.2 Hard invariant

For every `CanonEpisode`:

```text
for each evidence_id in episode.evidence_ids:
    evidence_id MUST resolve to exactly one registered evidence unit
```

This invariant is global.

It does NOT depend on:

- quest;
- act;
- source_type;
- whether the episode is a main-story episode;
- whether `act` is exact / null / span;
- whether the source itself is `USED`.

A valid `source_id` does not rescue a missing `evidence_id`.

## 3.3 Required implementation

Introduce or refactor toward a clear global validation layer.

Acceptable conceptual split:

```text
A. evidence reference integrity
   - unregistered evidence IDs
   - duplicate evidence IDs

B. attribution compatibility
   - quest compatibility
   - exact-act compatibility
   - source_type compatibility

C. coverage
   - life-stage semantic status
   - Chapter IV main-story act coverage
```

Exact method names are flexible.

The important requirement:

```text
unregistered evidence reference
    ↓
mandatory_life_stage_source_status != SOURCE_COMPLETE
```

for ALL episodes.

Do NOT encode this only inside `_act_support_gaps()`.

Do NOT rely on `canon_span_status`; that remains the legacy structural metric.

## 3.4 Preserve truthful current Canon status

Do NOT fabricate sources to make metrics green.

Current truthful state must remain equivalent to:

```text
canon_span_status
    = MANDATORY_SPAN_SOURCE_COMPLETE
    # legacy structural metric only

mandatory_life_stage_source_status
    = PARTIAL...
    # because semantic evidence still has a real gap

main_story_act_coverage_status
    = PARTIAL

missing_main_story_acts
    = ["II", "III"]

episodes_without_exact_act_main_story_evidence
    includes INNER_WORLD_REVELATION
```

Do NOT relabel:

- Character Story → MAIN_STORY;
- Voice-Over → main-story Act;
- game version → Act number;
- null act → exact act.

Do NOT invent official source IDs / URLs / locators.

If evidence is missing, report missing.

## 3.5 R7-FC reviewer-locked counterexamples

Add tests at minimum:

### R7-FC-T1 — non-exact-act missing evidence

Temporary fixture:

```text
episode:
    episode_id = FIX_MISSING
    act = null
    source_ids = [a valid USED source]
    evidence_ids = ["FUR-NOT-REGISTERED"]
```

Required:

```text
unregistered_evidence_ids contains FUR-NOT-REGISTERED
mandatory_life_stage_source_status != SOURCE_COMPLETE
```

This is the core blocker.

### R7-FC-T2 — span-act missing evidence

Temporary fixture:

```text
episode.act = "I-V"
evidence_ids = ["FUR-NOT-REGISTERED"]
```

Required: same failure.

### R7-FC-T3 — exact-act behavior remains correct

Preserve existing cases:

```text
Act IV + CHARACTER_STORY/null act → invalid for exact Act IV support
Act IV + MAIN_STORY/Act I       → semantic conflict
Act IV + MAIN_STORY/Act IV      → valid exact-act support
```

### R7-FC-T4 — production metrics remain truthful

Production data must still expose:

```text
missing_main_story_acts == ["II", "III"]
main_story_act_coverage_status == "PARTIAL"
INNER_WORLD_REVELATION remains a semantic gap
```

No production Canon evidence may be mutated in tests.

---

# 4. R10-FC — USER_MESSAGE PROVENANCE MUST FAIL CLOSED

Severity:

`P1`

## 4.1 Current good design

Keep the two-phase direct ingress:

```text
reserve DirectTurn identity
    ↓
record canonical USER_MESSAGE U
    ↓
apply C4 semantics using U.event_id
    ↓
freeze snapshot
    ↓
submit_reserved
```

Keep:

```text
USER_MESSAGE.turn_id
==
transition_event.turn_id
==
DirectTurn.turn_id
```

Keep:

```text
C4 row
    ↓ transition_event_id
T = USER_PREFERENCE_CHANGED / USER_PLAN_COMPLETED
    ↓ payload.source_event_id
U = exact canonical USER_MESSAGE
```

Keep duplicate-identical-utterance identity tests.

Do NOT return to text equality as provenance.

## 4.2 Current fail-open defect

Current production flow can behave like:

```text
reserve turn
    ↓
bridge.record(USER_MESSAGE)
    ↓ throws / fails
    ↓
exception swallowed
umsg_id = ""
    ↓
cog.apply_user_message(... source_event_id=None)
    ↓
transition T may still be created
    ↓
preference superseded / plan completed
```

Then `_ensure_transition_event()` can fall back to creating a transition event without exact source `USER_MESSAGE`.

Result:

```text
C4 lifecycle mutation exists
but canonical trigger event U does not exist
```

That violates the exact provenance contract.

## 4.3 Hard invariant

For a **production direct user turn**:

If a C4 lifecycle mutation is caused by a direct user utterance, then:

```text
valid canonical USER_MESSAGE U
MUST exist first
```

and:

```text
U.event_id
MUST be supplied into semantic transition creation
```

If U cannot be created / returned / resolved:

```text
NO C4 lifecycle transition mutation
```

Specifically:

```text
NO preference supersede
NO plan complete
NO USER_PREFERENCE_CHANGED orphan transition
NO USER_PLAN_COMPLETED orphan transition
```

The direct conversation itself does NOT need to fail.

Preferred behavior:

```text
USER_MESSAGE provenance persistence failure
    ↓
skip evidence-dependent C4 durable mutation
    ↓
continue freeze/enqueue/reply if otherwise possible
    ↓
log an observable warning
```

This preserves user experience without corrupting C4 truth.

## 4.4 Production-path requirement

Fix `App.submit_user_message`.

Production path must distinguish:

```text
A. canonical USER_MESSAGE recorded successfully
   → apply_user_message(... exact source_event_id)

B. canonical USER_MESSAGE recording failed
   → do NOT call evidence-dependent C4 lifecycle mutation path
```

Do NOT solve this by fabricating a fake event ID.

Do NOT silently create a derived transition with no U.

Do NOT silently search for another same-text USER_MESSAGE.

## 4.5 `CognitionHub` defense in depth

The App fix is necessary, but a bounded defense is also required so the hub cannot accidentally create an orphan lifecycle transition when production direct semantics explicitly require source provenance.

Acceptable approaches include:

- explicit `require_source_event=True`;
- explicit production/direct mode;
- a dedicated direct-turn apply API;
- another small contract that clearly distinguishes isolated legacy/test calls from production evidence-backed calls.

Do NOT break legitimate isolated deterministic unit tests unless they can be migrated cleanly.

The important invariant:

```text
production direct lifecycle mutation
without valid source USER_MESSAGE
== rejected / no-op
```

## 4.6 EventBridge `_seen` failure poisoning

Current conceptual issue:

```text
_seen[key] = True
    ↓
append(...)
    ↓ append fails
```

If the key remains in `_seen`, retry can be suppressed even though no canonical event exists.

Required:

```text
only mark key as seen AFTER successful append
```

or:

```text
on append exception:
    rollback _seen[key]
```

Preferred:

```text
append first
    ↓ success
mark _seen
```

but preserve concurrency assumptions / exactly-once behavior.

Do NOT broaden this into an EventBridge redesign.

## 4.7 R10-FC reviewer-locked counterexamples

### R10-FC-T1 — preference correction + USER_MESSAGE append failure

Setup:

```text
active preference exists
```

Force the canonical `USER_MESSAGE` append to fail for the correction turn.

Then submit:

```text
"我现在不喝咖啡了"
```

Required:

```text
old preference remains ACTIVE
no new superseded row caused by this turn
USER_PREFERENCE_CHANGED == 0 for this turn
no orphan transition event
DirectTurn still reaches a terminal state if dialogue path itself is healthy
```

### R10-FC-T2 — plan completion + USER_MESSAGE append failure

Setup:

```text
active plan exists
```

Force USER_MESSAGE append failure, then submit completion utterance.

Required:

```text
plan remains ACTIVE
USER_PLAN_COMPLETED == 0 for this turn
no orphan transition event
```

### R10-FC-T3 — EventBridge retry after append failure

For a stable key:

```text
first append → forced exception
second append → normal
```

Required:

```text
second call actually persists exactly one canonical event
key was not poisoned by failed first attempt
```

### R10-FC-T4 — happy path still exact

Preserve:

```text
row → T → U
T.source_event_id == U.event_id
T.turn_id == U.turn_id == DirectTurn.turn_id
```

### R10-FC-T5 — duplicate identical correction remains identity-safe

Two turns with identical correction text must still resolve to two different `USER_MESSAGE.event_id` values and corresponding turn IDs.

### R10-FC-T6 — preparation failure after reservation remains terminal

Existing `cancel_reserved` contract remains green.

### R10-FC-T7 — FIFO / deadline regression

All prior DirectDialogueQueue FIFO / deadline tests remain unchanged and green.

---

# 5. R6 / R8 / R9 / R11 / R12 FREEZE CONTRACT

This task must NOT use the two blockers as an excuse to refactor already-correct areas.

## R6 frozen

Forbidden:

- reintroducing provenance-less C3;
- changing successful memory thresholds;
- moving formation authority;
- redesigning MemoryEngine.

## R8 frozen

Forbidden:

- reopening social bid on failed E1;
- changing legitimate spoken-bid semantics;
- generating USER_IGNORED during cancellation.

## R9 frozen

Forbidden:

- replacing real Director E2E with direct Scheduler invocation;
- weakening preemption assertions.

## R11 frozen

Forbidden:

```text
poke → USER_PET
drag → USER_PET
```

No umbrella regression.

## R12 frozen

Forbidden:

- removing Office dependencies;
- converting failures to skip / xfail;
- changing production Office capability semantics just to satisfy environment.

---

# 6. STATIC AUDIT REQUIREMENTS

After implementation, perform a narrow static audit.

At minimum verify:

1. every `CanonEpisode.evidence_ids` reference is globally validated;
2. unregistered evidence validation is not gated by exact act;
3. `_life_stage_source_status()` includes global missing evidence integrity;
4. production direct C4 lifecycle mutation has a canonical USER_MESSAGE gate;
5. production direct mutation cannot call orphan transition fallback;
6. EventBridge failed append does not permanently mark `_seen`;
7. successful EventBridge dedupe still works;
8. DirectDialogueQueue turn identity still has one authority;
9. timeout still begins at reserve/ingress;
10. no new C3 formation writer;
11. no new raw `memories` writer;
12. no R11 event collapse;
13. no Office dependency regression;
14. no Canon source fabrication.

Include this audit in the closeout report.

---

# 7. FALSE-GREEN PROHIBITIONS

The following are explicitly forbidden:

## F1

Do NOT make R7 pass only for exact-act fixtures while leaving non-exact episodes unchecked.

## F2

Do NOT define `unregistered_evidence_ids` from a function that skips non-exact episodes.

## F3

Do NOT preserve `mandatory_life_stage_source_status == SOURCE_COMPLETE` while global missing evidence exists.

## F4

Do NOT mutate production evidence to remove the counterexample instead of fixing validation.

## F5

Do NOT swallow USER_MESSAGE append failure and continue into durable C4 lifecycle mutation.

## F6

Do NOT create a transition event with only verbatim text but no canonical source event and call that provenance.

## F7

Do NOT search for “some USER_MESSAGE with equal text”.

Event identity must be exact.

## F8

Do NOT fabricate a source event ID.

## F9

Do NOT cancel the whole user dialogue just because C4 provenance persistence failed, unless the existing architecture makes safe continuation impossible.

Preferred: conversation continues, durable evidence-dependent mutation is skipped.

## F10

Do NOT mark EventBridge dedupe key before successful persistence unless rollback is guaranteed.

## F11

Do NOT weaken old tests, delete tests, add skip/xfail, or lower assertions.

## F12

Do NOT claim Phase 14 PASS from the coding agent.

---

# 8. REVIEWER-LOCKED TEST FILE

Prefer adding a focused file such as:

`tests/cognition/test_phase14_final_r7_r10_failclosed.py`

Do NOT stuff these cases into unrelated historical test files unless there is a strong repository convention reason.

Minimum new reviewer cases:

```text
R7-FC-T1  non-exact-act missing evidence fails
R7-FC-T2  span-act missing evidence fails
R7-FC-T3  prior exact-act semantics preserved
R7-FC-T4  production metrics remain truthful

R10-FC-T1 preference correction fails closed when U append fails
R10-FC-T2 plan completion fails closed when U append fails
R10-FC-T3 EventBridge failed append does not poison retry key
R10-FC-T4 happy row→T→U exact identity preserved
R10-FC-T5 identical utterances remain distinct by event/turn identity
R10-FC-T6 reserved prep failure still reaches terminal
R10-FC-T7 FIFO/deadline regression remains green
```

More tests are allowed only if directly useful to these residuals.

---

# 9. TEST EXECUTION GATES

Use the project-local validated Python environment.

Do NOT silently switch interpreter versions during this task.

Run in this order.

## Gate A — new residual tests

```text
tests/cognition/test_phase14_final_r7_r10_failclosed.py
```

All must pass.

## Gate B — previous R6–R12 reviewer tests

```text
tests/cognition/test_phase14_final_reviewer_r6_r12.py
```

All must pass unchanged except only if an assertion is mechanically renamed because of a non-semantic API name change; any such change must be reported and justified.

Prefer zero modification.

## Gate C — previous R1–R5 residual / closure tests

Run all Phase 14 cognition closure / residual reviewer tests.

All must pass.

## Gate D — targeted cognition

Run relevant cognition, memory, scheduler, dialogue queue, Director integration tests.

## Gate E — Phase 15 preservation

Run the existing Phase 15 preservation suites already used in the previous closeout.

## Gate F — Agent / Office foundation

Run the previous Agent foundation suite including Office tests.

Expected: zero dependency failures.

## Gate G — FULL SUITE ×3

Run the entire test suite three consecutive times.

Required:

```text
0 failed
0 skipped caused by this task
0 xfailed introduced by this task
```

Do NOT retry until lucky.

Record each run separately:

```text
FULL RUN #1
FULL RUN #2
FULL RUN #3
```

with exact pass/fail/skip counts and durations.

Historical previous report was:

```text
1218 passed / 0 failed / 0 skipped ×3
```

Do NOT force the count to equal 1218 if new tests increase it.

The semantic rule is:

```text
old tests preserved
+
new tests added
+
zero failures
```

not “make the number look familiar”.

---

# 10. REQUIRED COUNTEREXAMPLE OUTPUT

The closeout report must include actual runtime/fixture evidence for both blockers.

## Counterexample G — R7 missing evidence

Show BEFORE conceptual failure and AFTER actual metrics for a fixture similar to:

```text
episode.act = null
evidence_ids = ["FUR-NOT-REGISTERED"]
```

AFTER must show:

```text
unregistered_evidence_ids includes FUR-NOT-REGISTERED
mandatory_life_stage_source_status != SOURCE_COMPLETE
```

## Counterexample H — R10 USER_MESSAGE failure

Show:

```text
existing ACTIVE preference
    ↓
forced USER_MESSAGE append failure
    ↓
correction turn submitted
```

AFTER must show:

```text
preference status remains ACTIVE
no USER_PREFERENCE_CHANGED transition for failed turn
no transition row mutation
DirectTurn terminal state is observable
```

Also show plan-completion equivalent or test evidence.

## Counterexample I — EventBridge retry

Show:

```text
first record(key=K) → forced append failure
second record(key=K) → succeeds
query → exactly one persisted event
```

---

# 11. IMPLEMENTATION SCOPE

Expected modified production files should be small and likely limited to:

```text
furina/cognition/stores/canon_history.py
furina/app.py
furina/cognition/hub.py
furina/cognition/bridge.py
```

Plus:

```text
tests/cognition/test_phase14_final_r7_r10_failclosed.py
docs/phase/Phase_14/00_MANIFEST.md
docs/phase/Phase_14/06_Phase_14_Final_Reviewer_Residual_R7_R10_FailClosed_Closeout_Report_EXACT.md
docs/phase/RECOVERY_LEDGER.md   # only if existing convention requires
```

`docs/persona/FURINA_CANON_LIFE_SOURCE_MAP.md` should be modified only if implementation changes the wording needed for consistency.

Do NOT touch other files without explaining why they are strictly required.

---

# 12. GIT / BRANCH / PUSH CONTRACT

Starting SHA:

`102d46b56c7e27fa37ba180d43e12b203ca5fd39`

Recommended branch:

`fix/phase14-final-r7-r10-failclosed`

Before coding:

```text
git status
git rev-parse HEAD
git branch --show-current
```

Confirm exact baseline.

After implementation:

1. run all required gates;
2. inspect final diff;
3. ensure no unrelated files were added;
4. do not add `nul`;
5. commit;
6. push the task branch;
7. verify remote SHA == local SHA.

Suggested commit structure:

```text
1. fix: global Canon evidence reference integrity
2. fix: direct C4 USER_MESSAGE provenance fail-closed
3. test: lock final R7/R10 counterexamples
4. docs: Phase 14 final residual closeout
```

A single clean commit is also acceptable if the agent workflow strongly prefers it.

Do NOT merge to master.

Do NOT rebase unrelated history.

---

# 13. CLOSEOUT REPORT REQUIREMENTS

Create:

`docs/phase/Phase_14/06_Phase_14_Final_Reviewer_Residual_R7_R10_FailClosed_Closeout_Report_EXACT.md`

It must contain at least:

## 1. Result

Exactly:

```text
READY_FOR_FINAL_REVIEW
```

Do NOT write `PHASE_14_FINAL_GATE_PASS`.

## 2. Baseline / branch / final SHA

Include:

```text
baseline
branch
final local SHA
final remote SHA
```

## 3. Modified files

For every changed file:

```text
file
why changed
contract affected
```

## 4. R7-FC closure

Explain:

- previous non-exact missing-evidence hole;
- global validator shape;
- exact metrics after;
- no fabricated evidence;
- current production PARTIAL truth.

## 5. R10-FC closure

Explain:

- canonical U failure behavior;
- App production path;
- Hub defense-in-depth;
- no orphan T;
- conversation continuation behavior;
- exact row→T→U happy path.

## 6. EventBridge retry integrity

Explain:

```text
failed append
→ key not permanently seen
→ retry succeeds
→ exactly one persisted event
```

## 7. Counterexamples G / H / I

Include real outputs.

## 8. Frozen residual preservation

Explicitly confirm:

```text
R6 preserved
R8 preserved
R9 preserved
R11 preserved
R12 preserved
```

## 9. Static audit

Include all items from §6.

## 10. Tests

Report Gates A–G separately.

For full suite include all three exact results.

## 11. Git state

Include:

```text
git status --short
local SHA
remote SHA
```

Any pre-existing untracked file must be disclosed.

Do not add `nul`.

## 12. Remaining gaps

If any blocker remains, say so.

Do not claim “none” unless all task requirements actually passed.

## 13. Final line

Exactly:

```text
READY_FOR_FINAL_REVIEW
```

---

# 14. FINAL SELF-AUDIT BEFORE PUSH

The coding agent must answer each with YES/NO and evidence.

```text
A. Can any non-exact Canon episode reference a missing evidence ID and still report semantic SOURCE_COMPLETE?

B. Is missing evidence validation independent of exact Chapter IV act validation?

C. Did any production Canon evidence get fabricated or relabelled to make status green?

D. Can production direct C4 supersede a preference when canonical USER_MESSAGE persistence failed?

E. Can production direct C4 complete a plan when canonical USER_MESSAGE persistence failed?

F. Can any production direct lifecycle transition T exist without a valid canonical USER_MESSAGE U?

G. Can a failed EventBridge append poison _seen and block a later valid retry?

H. Does happy-path row → T → U still resolve by exact event ID?

I. Do identical utterances in separate turns remain distinct by event ID / turn ID?

J. Did DirectDialogueQueue FIFO/deadline behavior change?

K. Did R6 C3 fail-closed regress?

L. Did R8 social-bid fail-closed/preemption regress?

M. Did R9 real Director E2E regress?

N. Did R11 pet/poke/drag objective truth regress?

O. Did R12 Office dependency truth regress?

P. Did any new durable C3 formation writer appear?

Q. Did any test get skipped/xfail/weakened/deleted to achieve green?

R. Is local final SHA identical to remote final SHA?
```

Required answers:

```text
A  NO
B  YES
C  NO
D  NO
E  NO
F  NO
G  NO
H  YES
I  YES
J  NO
K  NO
L  NO
M  NO
N  NO
O  NO
P  NO
Q  NO
R  YES
```

Any deviation must be reported as a remaining blocker.

---

# 15. EXTERNAL REVIEWER ACCEPTANCE CONDITIONS

The external reviewer may issue:

`PHASE_14_FINAL_GATE_PASS`

only if all of the following are independently verified:

1. global missing/unregistered evidence integrity covers every Canon episode;
2. semantic source status cannot false-green on missing evidence;
3. current Canon PARTIAL gaps remain truthful;
4. production direct C4 mutation fails closed when canonical USER_MESSAGE cannot be persisted;
5. no orphan preference/plan lifecycle transition can be created on that failure path;
6. EventBridge failed append does not poison dedupe retry;
7. exact row→T→U identity remains intact on the happy path;
8. duplicate identical utterances remain distinguishable by event/turn identity;
9. R6/R8/R9/R11/R12 remain preserved;
10. no new memory authority bypass exists;
11. all reviewer-locked tests pass;
12. full suite passes three consecutive runs with zero failures;
13. branch is pushed and remote SHA matches local;
14. no unrelated scope expansion occurred.

Until then:

```text
PHASE_14_FINAL_GATE = FAIL
```

---

# 16. STOP

After:

```text
implementation
→ targeted gates
→ full suite ×3
→ static audit
→ closeout
→ commit
→ push
→ remote SHA verification
```

STOP.

Do NOT:

- merge;
- start Phase 15;
- start Phase 16;
- start Hermes;
- start external-reference integration;
- redesign Persona;
- clean unrelated files;
- delete historical phase docs;
- claim final PASS.

Final implementation status must remain:

```text
READY_FOR_FINAL_REVIEW
```

Core principle for this final residual:

> **没有证据，不要把它写成事实。**
>
> **Canon 的证据不存在，就不能算完整；用户话语的 canonical event 没落地，就不能把它变成持久的 C4 生命周期事实。**
