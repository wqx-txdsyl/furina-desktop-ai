# Phase 15 — D4 Deterministic Temporal Semantics for C4
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

`docs/phase/Phase_15/06_Phase_15_D4_Deterministic_Temporal_Semantics_Task_Brief_EXACT.md`

Recommended branch:

`feature/phase15-d4-temporal-semantics`

Base:

latest externally accepted Phase 15 integration SHA after D1 review.

---

# 1. MISSION

Add bounded, deterministic, timezone-aware temporal semantics to explicit C4 statements.

Primary targets:

```text
PLAN
GOAL
IMPORTANT_DATE
ROUTINE
HABIT
```

Do NOT redesign general NLU.

Do NOT add broad LLM temporal authority.

Do NOT push this into C3.

---

# 2. PROBLEM

Current C4 stores declaration/lifecycle timestamps, but utterance semantics such as:

```text
明天交报告
下周完成测试
九月开始……
2026年9月……
每周六……
```

are not reliably represented as structured semantic time.

A plan stored today is not equivalent to a plan **due today**.

---

# 3. TIME AUTHORITY

Use user-local timezone at owner ingress.

Temporal interpretation must be based on:

```text
canonical USER_MESSAGE U
+
turn-local current timestamp
+
user-local timezone
```

Persist resolved values only when deterministic.

Never reinterpret relative dates later using a new current date.

Example:

```text
on Aug 27:
"明天交报告"
→ due date Aug 28
```

After restart on Aug 29 it must remain Aug 28.

---

# 4. ALLOWED FIRST-VERSION SEMANTICS

Required:

```text
today
tomorrow
day after tomorrow
explicit YYYY-MM-DD / YYYY年M月D日
this week / next week only if bounded policy defines an unambiguous representation
this weekend / next weekend only if exact start/end semantics are specified
explicit month
simple weekly recurrence
```

For vague phrases:

```text
过几天
最近
以后
有空
下个月左右
九月可能
```

do not invent a precise instant.

Use:

```text
temporal_uncertain = true
```

and preserve source text.

---

# 5. DATA MODEL

Implementation may extend C4 with a minimal structured temporal payload.

Prefer a single coherent model over scattered columns.

Candidate conceptual fields:

```text
temporal_kind
start_at
due_at
end_at
date_precision
recurrence
timezone
temporal_uncertain
```

Exact schema requires recon before implementation.

Do not create fields that have no consumer/test.

---

# 6. INTERPRETATION RULE

Interpretation remains:

```text
candidate != truth
```

Pipeline:

```text
canonical U
→ deterministic interpretation candidate
→ temporal resolver
→ C4 owner validation
→ durable item
```

The temporal resolver MUST NOT directly mutate DB.

---

# 7. LIFECYCLE

Existing:

```text
ACTIVE
COMPLETED
CANCELLED
EXPIRED
SUPERSEDED
```

remains.

D4 may enable deterministic expiration only when semantic contract is explicit and externally reviewed.

Do NOT silently auto-complete plans because due time passed.

Missed deadline != completed.

---

# 8. REQUIRED TESTS

At minimum:

```text
D4-T1 "我明天交报告" resolves relative to user-local calendar
D4-T2 restart preserves original resolved date
D4-T3 same utterance in two different days resolves differently at ingress
D4-T4 explicit absolute date preserves exact date
D4-T5 vague date becomes uncertain, not fabricated
D4-T6 weekly recurrence is structured
D4-T7 current explicit correction supersedes old plan with exact provenance
D4-T8 USER_MESSAGE persistence failure → no temporal C4 mutation
D4-T9 lifecycle row→T→U provenance preserved
D4-T10 timezone boundary around midnight is correct
D4-T11 DST-safe behavior if timezone library/environment supports DST
D4-T12 non-temporal preference behavior unchanged
```

---

# 9. FAIL-CLOSED

If temporal resolution fails unexpectedly:

```text
preserve user statement
mark uncertain where allowed
or skip temporal enrichment
```

Never reject a valid explicit C4 fact solely because optional temporal enrichment failed, unless storing it without time would change its meaning.

For a statement whose truth fundamentally depends on time:

```text
fail closed rather than fabricate.
```

---

# 10. GATES

```text
Gate A D4 tests
Gate B D1 accepted tests
Gate C Phase14 R10 exact provenance
Gate D C4 interpretation/user-model tests
Gate E restart tests
Gate F full suite
```

---

# 11. STATIC AUDIT

Ensure:

```text
no direct LLM durable writes
no C3 schema pollution
no current-time reinterpretation on read
no timezone-naive relative-date persistence
no auto-complete-by-deadline
no Phase17 proactive follow-up
```

---

# 12. CLOSEOUT

Create:

`docs/phase/Phase_15/07_Phase_15_D4_Deterministic_Temporal_Semantics_Closeout_Report_EXACT.md`

Stop at:

```text
READY_FOR_REVIEW
```
