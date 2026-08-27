# Phase 15 — D5 Relationship Anti-Spam / Anti-Runaway Hardening
# EXACT TASK BRIEF

Repository:
`wqx-txdsyl/furina-desktop-ai`

Phase 15 integration branch:
`feature/phase15-cognitive-life-finalization`

Phase 14 code frozen SHA:
`f8e84ecc7be67fbfa9d78f00b056bce4dd420095`

Phase 15 documentation baseline:
`4442fac4de1deabaf967d2f029032f0076512ab7`

Phase 15 Master Plan adoption commit reported by operator:
`a5bd81c`

External reviewer authority:
`GPT-5.6 Sol`

Permanent constraints:

```text
C1-C7 authority boundaries remain frozen.
Derived retrieval is DERIVED / REBUILDABLE / NON-AUTHORITATIVE / NOT C8.
No coding agent may declare PHASE_15_FINAL_GATE_PASS.
Each bounded task must stop at READY_FOR_REVIEW.
No task may absorb later-phase Character Agency / Hermes / GUI / Voice scope.
No skip / xfail / weakened assertion / fabricated Canon evidence.
```


Document path:

`docs/phase/Phase_15/12_Phase_15_D5_Relationship_AntiSpam_Hardening_Task_Brief_EXACT.md`

Recommended branch:

`feature/phase15-d5-relationship-antispam`

Base:

latest accepted integration SHA after D3.

---

# 1. MISSION

Harden C5 truth evolution against short-window repetitive-event runaway.

Do NOT redesign RelationshipEngine.

Do NOT add relationship climate behavior policy.

Do NOT add visible affection levels.

---

# 2. CURRENT MODEL TO PRESERVE

Existing concepts remain:

```text
familiarity
trust
comfort
attachment
respect
dependency
annoyance
interaction_tolerance
social_confidence
response/rejection rates
short-term vs long-term dynamics
trust slower accumulation
decay/recovery
provenance milestones
```

---

# 3. PROBLEM

Repeated event bursts currently can accumulate too linearly.

Examples:

```text
100 rapid pet events
≠ years of trust

10 accidental pokes
≠ relationship collapse
```

The system needs diminishing influence.

---

# 4. RECON / DESIGN COMPARISON

Before implementation compare at least:

```text
A. daily absolute cap
B. rolling-window cap
C. per-event-family diminishing returns
D. hybrid saturation
```

Choose based on product semantics and testability.

Do not copy AronaAI merely because it uses a daily cap.

Preferred characteristics:

```text
continuous
smooth
deterministic
restart-safe if durable history is required
not easily gamed
does not erase meaningful long-term accumulation
```

---

# 5. EVENT FAMILY SEMANTICS

Consider grouping repeated interactions:

```text
positive touch family
positive conversation family
negative touch family
ignore/reject family
successful-help family
failed-help family
```

Different families may saturate differently.

Trust should remain especially resistant to rapid farming.

---

# 6. PROVENANCE

C5 truth/milestones retain provenance.

Anti-spam logic must not:

```text
drop objective C6 events
rewrite history
hide actual interaction count
```

It only bounds C5 delta impact.

Objective event truth remains objective.

---

# 7. REQUIRED TESTS

```text
D5-T1 1 positive touch still changes relationship
D5-T2 100 rapid positive touches show diminishing/bounded effect
D5-T3 spaced positive interactions can accumulate meaningfully over time
D5-T4 trust cannot be rapidly farmed
D5-T5 repeated mild negative burst is bounded
D5-T6 serious distinct negative events still matter
D5-T7 event family separation works
D5-T8 C6 event count remains truthful
D5-T9 milestone provenance still resolves
D5-T10 restart preserves any durable anti-spam state if design requires it
D5-T11 relationship factors remain normalized
D5-T12 no visible affinity/intimacy state added
```

---

# 8. FORBIDDEN

```text
NO affection XP
NO relationship level
NO unlock stages
NO "pet Furina to make her work"
NO T5-B climate→behavior
NO Phase17 proactive policy
NO random LLM relationship delta
```

---

# 9. GATES

```text
Gate A D5 tests
Gate B existing relationship tests
Gate C R8/R9 social-bid preservation
Gate D all accepted Phase15 deltas
Gate E restart tests
Gate F full suite
```

---

# 10. STATIC AUDIT

Search for:

```text
new affinity/intimacy UI fields
relationship→work coercion
direct LLM C5 writes
lost milestone provenance
C6 event suppression
Phase17 behavior policy
```

All absent.

---

# 11. CLOSEOUT

Create:

`docs/phase/Phase_15/13_Phase_15_D5_Relationship_AntiSpam_Hardening_Closeout_Report_EXACT.md`

Stop at:
`READY_FOR_REVIEW`
