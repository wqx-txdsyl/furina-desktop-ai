# Furina Desktop AI — Manual Experience Acceptance Checklist

**Stage:** Post-Phase-13 Technical / Pre-Phase-14  
**Purpose:** Verify that the backend is not only technically correct, but actually behaves like a persistent digital life companion in real use.

---

# 0. Release Gate

Manual is passed only if all P0 experience groups pass and no unresolved P0/P1 defect makes the character feel mechanically fake, causally inconsistent, or operationally dishonest.

Final verdict:

```text
FUNCTIONAL DIGITAL LIFE = PASS
```

Only then:

```text
Phase 14 — Frontend Rendering / Asset Integration
```

If Manual fails:

```text
MANUAL = PARTIAL / FAIL
→ reopen only the minimal module responsible for the reproduced failure
```

No broad backend optimization after Manual starts.

---

# 1. Evidence Standard

Each test must record:

```text
Test ID
Environment
Trigger
Observed behavior
Expected behavior
Trace / state evidence
PASS / PARTIAL / FAIL / UNVERIFIABLE
Notes
```

Where useful, also capture:

```text
timestamp
activity
emotion
needs
relationship factors
world state
user presence / idle
director current source
dialogue channel
memory event
agent status
x/y position
speech text
```

For subjective tests, use at least 3 independent examples before judging.

---

# 2. Manual Split

## A — Reviewer-executable

These can be performed by reviewer in the audit/simulation environment:

- deterministic state transitions
- simulated Window/World changes
- Interaction semantic events
- Dialogue FIFO/history
- Memory persistence/restart
- Relationship causality
- Feed effects
- Agent lifecycle with mocks/fake tools
- Spatial path sampling
- long-run simulated Life cadence
- quiet coexistence simulation
- failure/recovery behavior
- Persona structure review with recorded real-model transcripts
- trajectory metrics
- causal trace audit

## B — User-required real machine

These require the user's actual Windows desktop and/or real external model endpoint:

- real Win32 foreground-window process recognition
- real idle / return detection
- actual mouse/drag/touch UX
- real multi-window/multi-monitor behavior
- actual Qt responsiveness under real network latency
- real app launch verification
- real glm-4v-flash dialogue/persona generation if reviewer environment has no network
- visual/subjective Furina resemblance
- real coexistence over 30–120+ minutes

---

# 3. A — Reviewer-executable Checklist

## A1. Runtime / Startup / Truth

### A1-01 Clean startup
Trigger:
```text
fresh runtime start
```

PASS:
- no exception
- dispatcher owner bound
- idle unavailable remains unknown until evidence
- no fake social bid
- no fake RETURN
- no fake Agent green status
- no phantom memory writes

Evidence:
- initial state snapshot
- runtime health
- recent event trace

---

### A1-02 Restart persistence
Trigger:
```text
create relationship/memory state
shutdown
restart using same DB
```

PASS:
- Memory persists
- Relationship persists according to designed storage
- transient runtime state does not incorrectly persist
- no duplicate replay of old events

---

## A2. World / Presence / Window Simulation

### A2-01 Unknown presence
Simulate:
```text
idle_available=False
no explicit user event
```

PASS:
- World activity = UNKNOWN
- user_active=False
- proactive social candidates blocked
- Life snapshot does not claim active/present
- no social bid
- no ignore timeout
- no return event

---

### A2-02 Explicit user event overrides unknown for current interaction only
Simulate:
```text
idle unavailable
submit user message / feed / pet
```

PASS for that event:
- presence_known=True
- user_present=True
- solitude=False

Persistent World must remain:
```text
idle_available=False
```

---

### A2-03 Active coding
Simulate:
```text
process=Code.exe
idle=5s
valid idle
stable > required window
```

PASS:
- World activity = CODING
- working=True
- focus/availability reasonable
- active Life/Motivation context receives coding truth
- proactive interruption becomes less likely
- assistance/observation remains possible where appropriate

---

### A2-04 Browser transition
Simulate:
```text
coding -> browser
```

PASS:
- stable transition occurs once
- no class/process oscillation
- WORK_ENDED occurs once if semantics require
- Life snapshot reflects browsing after stability

---

### A2-05 Away / return
Simulate:
```text
present -> idle > away threshold -> active
```

PASS:
- AWAY becomes stable
- no proactive social action while away
- return event exactly once
- Emotion EVENT_RETURN exactly once
- second real away→return can create second return

---

## A3. Needs / Homeostasis / Long-run Life

### A3-01 30-minute simulated normal use
Run accelerated deterministic clock.

PASS:
- no need saturates irrationally
- no emergency behavior spam
- activity rhythm remains varied because of causality, not forced rotation
- no repetitive metronome switching

---

### A3-02 2-hour simulated work
PASS:
- fatigue rises meaningfully
- energy decreases gradually
- hunger changes on hour-scale
- no need instantly pegs 100
- Furina does not constantly interrupt working user

---

### A3-03 4–8 hour simulated day
PASS:
- physiological state eventually becomes consequential
- rest/eat/sleep become plausible
- recovery actions produce visible causal state change
- no permanent stuck state

---

### A3-04 Quiet coexistence
Run a long period with:
```text
user present
no direct interaction
normal low-salience world
```

PASS:
- Furina can remain quiet
- does not invent forced speech for diversity
- does not rotate activities mechanically
- does not spam social bids
- still shows autonomous life activity occasionally
- no dead/stuck state

Core question:
> Does she feel like she can exist beside the user without demanding attention?

---

## A4. Emotion / State Causality

### A4-01 Praise
Trigger:
```text
high-confidence praise
```

PASS:
- Emotion changes immediately before reply snapshot
- Relationship changes once
- next dialogue reflects current state naturally
- effect decays/rebalances later rather than sticking forever

---

### A4-02 Reject
Trigger:
```text
clear rejection / “别烦我”
```

PASS:
- correct DialogueAct
- emotion changes once
- relationship/tolerance changes once
- current autonomous social action is interrupted
- no immediate repeated social attempt
- later recovery is possible

---

### A4-03 Pet
PASS:
- Emotion exactly once
- Relationship exactly once
- Memory at most once
- active mind behavior is preempted correctly
- reply sees post-event state

---

### A4-04 Poke
Same criteria as pet, but reaction should be semantically distinct.

---

### A4-05 Drag
PASS:
- semantic drag recognized
- mind takeover occurs once
- no snap-back after release
- emotion/relationship not duplicated

---

### A4-06 Ignore
Simulate:
```text
visible eligible Furina social bid
no response until deadline
```

PASS:
- exactly one ignore event
- no pointer-leave equivalence
- no ignore if user absent
- response before timeout cancels
- invalid/suppressed speech creates no pending bid

---

### A4-07 Recovery
Sequence:
```text
reject
quiet period
normal interaction later
```

PASS:
- guardedness can recover gradually
- no permanent punishment
- no instant amnesia
- later warmth depends on subsequent interaction

---

## A5. Relationship Causality

### A5-01 No self-farming
Run autonomous social actions without user response.

PASS:
- familiarity/trust/comfort do not grow simply because Furina chose social behavior

---

### A5-02 Positive response
User responds positively.

PASS:
- relationship changes once
- values stay in canonical ranges
- rate fields remain 0..1
- later behavior/dialogue sees updated relationship

---

### A5-03 Repeated rejection
PASS:
- no double counting
- annoyance/rejection rate remain bounded
- system becomes appropriately less intrusive
- no permanent lockout

---

## A6. Dialogue Mechanics

### A6-01 15-turn continuous conversation
Use uncherry-picked sequence.

Include:
- greeting
- casual statement
- question
- personal plan
- correction
- joke
- praise
- disagreement
- rejection
- recovery
- reference to previous turn
- topic switch
- return to earlier topic
- request for help
- goodbye/quiet close

PASS:
- no orphan history turns
- continuity remains coherent
- current activity/world/relationship grounding appears where relevant
- no generic assistant boilerplate
- no inexplicable topic reset

---

### A6-02 Rapid double input
Force:
```text
message1 submitted first
worker2 reaches generation first
```

PASS:
- final dialogue order still 1→2
- no deadlock
- history remains paired

---

### A6-03 Ambient speech isolation
Inject:
```text
autonomous speech
feed speech
agent report
```

PASS:
- direct user history remains coherent
- ambient lines do not masquerade as replies to previous user messages

---

### A6-04 Model/validator failure
PASS:
- no orphan direct-user history entry
- no invalid raw output displayed
- runtime remains responsive
- health/fallback state truthful

---

## A7. Persona / Furina Identity Evaluation

Real-model transcript required for final Persona verdict.

### A7-01 Blind identity test
Collect at least 30 outputs across:
- praise
- embarrassment
- being ignored
- user working
- curiosity
- asking for help
- Agent success
- Agent failure
- quiet moment
- disagreement
- vulnerability
- self-directed activity

Mask explicit identity tokens:
```text
芙宁娜
Furina
本神
枫丹
水神
```

Question:
> Without names/catchphrases, does the speech still feel recognizably like Furina rather than a generic playful female assistant?

PASS requires:
- chosen performance rather than forced performance
- dignity before direct need
- quick recovery after embarrassment/exposure
- attention sensitivity
- public confidence / private sincerity contrast
- expressive redirects/self-correction
- post-Archon maturity
- no tsundere caricature
- no generic “AI assistant” voice

---

### A7-02 Same character during office tasks
Compare:
```text
casual dialogue
memory recall
agent success
agent failure
user rejection
```

PASS:
- same personality remains recognizable across all modes
- Agent mode does not turn into generic system bot

---

## A8. Memory

### A8-01 Learn future plan
User says a meaningful plan.

PASS:
- stored once
- later retrievable
- not echoed unnaturally immediately

---

### A8-02 Natural recall
Later ask indirectly / create relevant context.

PASS:
- relevant memory can influence reply
- not every memory is forced into every reply
- no fabricated details

---

### A8-03 Restart recall
Restart DB/runtime.

PASS:
- memory still retrievable
- no duplicate record caused by restart

---

## A9. Feed

### A9-01 Basic feed
PASS:
- hunger/effect changes once
- emotion changes before dialogue
- activity becomes eat as designed
- memory exactly once
- Life interruption/Director semantics correct

---

### A9-02 Feed during activity
PASS:
- previous mind activity finalized correctly
- feed becomes current interaction
- no double outcome

---

## A10. Agent Truthfulness

### A10-01 Verified success
Fake/tool-controlled success.

PASS:
- all required steps ok=True and verified=True
- COMPLETED exactly once
- Furina report grounded in actual result

---

### A10-02 Unverified result
Return:
```text
ok=True
verified=False
```

PASS:
- no COMPLETED
- status UNVERIFIED/FAILED
- dialogue does not claim success

---

### A10-03 Tool failure
PASS:
- failure status truthful
- no completed event
- Furina remains in-character while reporting failure

---

### A10-04 Agent vs Life priority
PASS:
- active Agent blocks lower-priority mind
- deferred Life action does not speak/start until execution
- after Agent finishes, deferred Life can proceed

---

## A11. Spatial

### A11-01 Approach
Record x/y trajectory.

PASS:
- not one straight teleport-like vector
- heading changes smooth
- destination meaningful

---

### A11-02 Withdraw
PASS:
- smooth and semantically opposite to approach
- no instant reversal jitter

---

### A11-03 Wander
Sample multiple seeds.

Record:
- heading delta
- path efficiency
- waypoint curvature
- dwell time
- target distribution

PASS:
- no repeated fixed grid
- no 90°/150° polyline corners
- no identical path shape every run

---

### A11-04 Explore
Same metrics as wander.

PASS:
- behavior distinguishable from wander
- movement has curiosity/exploration semantics

---

### A11-05 Drag/release
PASS:
- follows drag
- release remains where semantically intended
- no snap-back
- no duplicate drag semantics

---

## A12. Failure / Recovery

### A12-01 LLM unavailable
PASS:
- UI/runtime stays alive
- truthful fallback badge/state
- local life can continue
- no fake GLM success

---

### A12-02 Memory DB transient failure
PASS:
- no crash loop
- failure visible in diagnostics
- no fake persisted memory claim

---

### A12-03 Agent failure during Life activity
PASS:
- Director state recovers
- Life can continue afterward
- no stuck WORKING state

---

# 4. B — User-required Windows / Real API Checklist

## B1. Real Windows World perception

### B1-01 VS Code
Open VS Code and work for > stability window.

PASS:
- process recognized as Code
- CODING
- working=True
- no class-name misclassification

---

### B1-02 Browser
Switch to Chrome/Edge.

PASS:
- BROWSING
- transition occurs after stability window
- no oscillation

---

### B1-03 Word / Excel / PowerPoint / Notepad
PASS:
- categories sensible
- work state changes appropriately

---

### B1-04 Idle
Stop input.

Observe:
```text
30s
1min
5min+
```

PASS:
- idle increases realistically
- away only after threshold
- no false active events

---

### B1-05 Return
After away, move mouse/type.

PASS:
- USER_RETURNED once
- Furina reaction at most once
- no event spam

---

### B1-06 Multi-window switching
Rapidly switch windows.

PASS:
- no unstable oscillation
- stability works
- Furina does not constantly react to every alt-tab

---

### B1-07 Multi-monitor / DPI scaling
If available.

PASS:
- window coordinates remain valid
- pet does not leave screen unexpectedly
- drag and spatial movement remain usable

---

## B2. Real mouse interaction

### B2-01 Click
Physically click character.

PASS:
- one semantic click
- no accidental double event

### B2-02 Pet/head-touch
PASS:
- hitbox feels correct
- not too difficult/easy to trigger
- reaction happens once

### B2-03 Poke
PASS:
- distinguishable from pet

### B2-04 Drag
PASS:
- smooth enough
- no jump
- release feels stable

### B2-05 Pointer leave/hover
PASS:
- never interpreted as ignore/rejection

---

## B3. Real glm-4v-flash Dialogue / Persona

Required if reviewer sandbox still cannot reach endpoint.

Capture one raw transcript file with:
- user input
- Furina output
- activity
- emotion
- relationship factors
- world context
- dialogue act
- channel
- timestamp

Minimum:
```text
30 direct/persona evaluation prompts
15-turn natural conversation
5 autonomous lines
3 Agent reports
3 failure/recovery lines
```

Do not cherry-pick.

Reviewer performs the actual Persona blind assessment.

---

## B4. Real latency / Qt responsiveness

### B4-01 Slow LLM
During real network latency, drag/move window and interact.

PASS:
- Qt remains responsive
- no long UI freeze
- worker completion applies later safely

---

### B4-02 Network failure
Temporarily disconnect / use controlled invalid endpoint if safe.

PASS:
- no crash
- truthful fallback
- app remains interactive

---

## B5. Real Agent actions

### B5-01 Calculator
Ask Furina to open calculator.

PASS:
- correct app launches
- verification sees observable app identity
- completed only after verification

### B5-02 Notepad
Same.

### B5-03 Failure case
Use a harmless nonexistent app/task.

PASS:
- no fake completed
- in-character failure report

---

## B6. Real 30–120 minute coexistence session

Run Furina while doing normal work.

Do not deliberately interact much.

Record every:
```text
autonomous activity
autonomous speech
social bid
window reaction
state change
unexpected interruption
```

PASS:
- she does not become a notification machine
- she does not feel dead
- no rhythmic action rotation
- no repetitive phrases
- no obvious state contradictions
- interruptions feel context-sensitive
- quiet coexistence is possible
- autonomous activity feels internally motivated

---

# 5. Cross-cutting Character-State Acceptance

These are not separate implementation tests; they are subjective/causal gates across all scenarios.

## C1. State continuity
Question:
> Does Furina feel like the same person from minute to minute?

PASS:
- no unexplained emotion reset
- no relationship amnesia
- no activity teleportation

---

## C2. Causal legibility
Question:
> Can the user understand why she reacted?

PASS:
- praise → warmer
- rejection → guarded
- work → less intrusive
- idle/away → self activity
- hunger/fatigue → plausible life behavior
- interaction → immediate response

No hidden random rotation needed to explain behavior.

---

## C3. Autonomy
Question:
> Does she have a life when the user does nothing?

PASS:
- can read/rest/wander/explore/observe/etc.
- actions last meaningful durations
- actions can be interrupted
- outcomes change later state
- no behavior merely because "it has not appeared recently"

---

## C4. Presence sensitivity
Question:
> Does she behave differently when user is busy, away, just returned, or directly interacting?

PASS:
- differences visible and causal
- unknown is not mistaken for present
- direct user event is recognized immediately

---

## C5. Furina identity
Question:
> Is she Furina, or just “a cute girl assistant”?

PASS requires identity beyond:
- catchphrases
- honorifics
- surface sass
- random theatrical wording

---

# 6. Final Manual Scorecard

Each group gets:

```text
PASS
PARTIAL
FAIL
UNVERIFIABLE
```

Mandatory groups for FUNCTIONAL DIGITAL LIFE PASS:

```text
World truth
Life/autonomy
Emotion causality
Interaction
Dialogue continuity
Persona
Memory
Agent truth
Spatial naturalness
Qt responsiveness
Quiet coexistence
Long-run state continuity
```

Final verdict template:

```text
Manual Experience Acceptance

World                    =
Life / autonomy          =
Emotion                  =
Interaction              =
Dialogue                 =
Persona                  =
Relationship             =
Memory                   =
Feed                     =
Agent                    =
Spatial                  =
Qt / failure recovery    =
Quiet coexistence        =
Long-run continuity      =

FUNCTIONAL DIGITAL LIFE  = PASS / PARTIAL / FAIL
READY FOR PHASE 14       = YES / NO
```

---

# 7. Manual Execution Order

Recommended order:

```text
M0  Environment sanity
M1  World/presence
M2  Interaction
M3  Emotion/relationship
M4  Dialogue mechanics
M5  Memory
M6  Feed
M7  Agent
M8  Spatial
M9  Persona blind evaluation
M10 Quiet coexistence / long-run Life
M11 Failure/recovery
M12 Final integrated 30–120 minute session
```

Do not begin Phase 14 until M12 is evaluated.
