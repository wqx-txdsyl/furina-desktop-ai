# Phase 15 — D1 Canon Act II / III Official Evidence Acquisition
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

`docs/phase/Phase_15/04_Phase_15_D1_Canon_Act_II_III_Official_Evidence_Task_Brief_EXACT.md`

Recommended task branch:

`feature/phase15-d1-canon-act2-act3-evidence`

Start from:

the latest externally accepted SHA on `feature/phase15-cognitive-life-finalization`.

---

# 1. MISSION

Close only the known C2 evidence gaps for Fontaine Archon Quest Chapter IV Acts II and III **if and only if official evidence can actually be verified**.

Current truthful state:

```text
main_story_act_coverage_status = PARTIAL
missing_main_story_acts = ["II", "III"]
```

External repositories may be used only as **locators**.

They are not C2 truth.

The authoritative chain must remain:

```text
external locator
→ official source
→ exact source registration
→ exact evidence unit
→ exact episode attribution
→ semantic completeness metrics
```

A legitimate final result is still PARTIAL if official evidence cannot be verified.

---

# 2. ALLOWED SOURCE HIERARCHY

Use the frozen C2 hierarchy.

Tier 0 preferred:

```text
official in-game Simplified Chinese text / TextMap / official quest transcript
official Furina Character Story / Story Quest / Voice-Over where semantically appropriate
```

Tier 1:

```text
official HoYoWiki / HoYoverse / miHoYo pages
official story teaser / trailer / cutscene transcript
```

External projects including Furinelle are locator-only.

Forbidden as authoritative evidence:

```text
community wiki summaries
forum posts
media articles
fanworks
AI summaries
RP Skill prose
Furinelle prose
```

---

# 3. RECON

Before editing:

1. confirm branch and HEAD;
2. inspect:
   - `data/canon/furina_life_history.json`
   - `data/canon/furina_life_sources.json`
   - `data/canon/furina_evidence_units.json`
   - `docs/persona/FURINA_CANON_LIFE_SOURCE_MAP.md`
   - `furina/cognition/stores/canon_history.py`
   - current Canon tests;
3. record current production metrics;
4. identify exact episodes intended to receive Act II / III evidence;
5. verify every official source locator manually or programmatically.

Do not assume Furinelle's act labels are correct.

---

# 4. HARD INVARIANTS

```text
Furina != Focalors.
Furina knowledge boundary remains episode-specific.
No evidence unit may be invented.
No act may be guessed.
No Character Story / Voice-Over source may be relabelled MAIN_STORY.
No version number may be treated as act number.
Every evidence_id must resolve globally.
Every source_id must resolve.
Exact-act support requires:
    source_type = MAIN_STORY
    quest = Chapter IV
    act = exact same act
```

---

# 5. IMPLEMENTATION

If official Act II evidence is verified:

- register or reuse an exact official source;
- create minimal evidence unit(s);
- attach only to semantically compatible episode(s);
- update source map.

Do the same independently for Act III.

If one act succeeds and the other fails:

```text
missing_main_story_acts must contain only the genuinely missing act.
```

If neither succeeds:

```text
leave production Canon data unchanged except documentation of attempted verification if appropriate.
```

Do not lower validator strictness to obtain COMPLETE.

---

# 6. REVIEWER-LOCKED TESTS

Add focused tests proving:

```text
D1-T1 every newly added evidence ID is registered
D1-T2 every newly added source ID is registered
D1-T3 exact MAIN_STORY Chapter IV Act II support is exact, not inferred
D1-T4 exact MAIN_STORY Chapter IV Act III support is exact, not inferred
D1-T5 wrong-act evidence cannot support another act
D1-T6 community / locator source cannot count as official support
D1-T7 production semantic metrics match actual verified state
D1-T8 all prior R7 / R7-FC semantic completeness tests remain green
D1-T9 Canon runtime remains read-only
D1-T10 Furina/Focalors knowledge boundary unchanged
```

Only include Act II/III success assertions when official evidence was actually found.

---

# 7. GATES

```text
Gate A  new D1 tests
Gate B  Phase 14 Canon semantic completeness reviewer tests
Gate C  Phase 15 cognition Canon tests
Gate D  all persona/Canon tests
Gate E  full suite
```

For full suite, zero failures.

Do not force coverage status to COMPLETE.

---

# 8. STATIC AUDIT

Verify:

```text
no new unregistered evidence IDs
no unregistered source IDs
no community source promoted
no source tier weakened
no exact-act mismatch
no duplicate evidence IDs
no runtime mutation path into C2
no unrelated production files changed
```

---

# 9. GIT

Commit only D1-related production/data/tests/docs.

Push task branch.

Verify local SHA == remote SHA.

Do not merge.

---

# 10. CLOSEOUT

Create:

`docs/phase/Phase_15/05_Phase_15_D1_Canon_Act_II_III_Official_Evidence_Closeout_Report_EXACT.md`

Final coding-agent status:

```text
READY_FOR_REVIEW
```

or:

```text
NOT_READY_FOR_REVIEW: <exact blocker>
```

Do not declare Phase 15 PASS.
