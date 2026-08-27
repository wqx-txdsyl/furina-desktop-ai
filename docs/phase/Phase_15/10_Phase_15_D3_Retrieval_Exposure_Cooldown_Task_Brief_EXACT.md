# Phase 15 — D3 Retrieval Exposure Cooldown
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

`docs/phase/Phase_15/10_Phase_15_D3_Retrieval_Exposure_Cooldown_Task_Brief_EXACT.md`

Recommended branch:

`feature/phase15-d3-retrieval-cooldown`

Base:

latest accepted integration SHA after D2.

---

# 1. MISSION

Prevent the same autobiographical/context item from being automatically injected into adjacent turns so often that Furina feels repetitive.

This is an exposure-control problem.

It is NOT forgetting.

---

# 2. DATA OWNERSHIP

Preferred first implementation:

```text
session-local RetrievalExposureLedger
```

or equivalent bounded operational cache.

Properties:

```text
OPERATIONAL
DERIVED
NON-AUTHORITATIVE
EXPIRABLE
BOUNDED
```

Do not modify canonical C3 truth rows with presentation history unless strictly required.

---

# 3. SEMANTICS

Automatic retrieval:

```text
recently exposed ref
→ temporary score penalty or suppression
```

Explicit user recall intent:

```text
"你还记得..."
"刚才那个..."
"再说说..."
"我之前说的..."
```

→ bypass or strongly relax exposure cooldown.

High-priority current facts and C6/C7 truth are not hidden by a memory cooldown.

---

# 4. SCOPE

First version should apply narrowly to:

```text
C3 autobiographical memory
```

Optionally C2 anecdotal injection only if tests prove benefit.

Do NOT suppress:

```text
C1 identity
current C4 explicit truth
critical C7 task state
current C6 event
```

---

# 5. RESTART

Persistence is NOT required.

Default preference:

```text
session-local
```

unless recon demonstrates repeated restart spam that materially harms UX.

Avoid unnecessary durable schema.

---

# 6. REQUIRED TESTS

```text
D3-T1 same C3 auto-selected on adjacent unrelated turn is penalized/suppressed
D3-T2 after cooldown it can reappear
D3-T3 explicit recall bypasses cooldown
D3-T4 cooldown does not delete/archive/weaken C3 truth
D3-T5 restart follows documented session-local semantics
D3-T6 current C4 truth unaffected
D3-T7 current C6 event unaffected
D3-T8 context bounds preserved
D3-T9 different memories still allow diversity
D3-T10 failed context assembly does not poison exposure state
```

Important:

mark exposure only after successful context inclusion, not merely candidate generation.

---

# 7. GATES

```text
Gate A D3 tests
Gate B D2 hybrid retrieval
Gate C D4 temporal semantics
Gate D C3 lifecycle / MemoryEngine authority
Gate E context/restart tests
Gate F full suite
```

---

# 8. STATIC AUDIT

Prove:

```text
no C3 authority mutation
no new truth store
no global permanent forgetting
no explicit recall suppression
no pre-success exposure poisoning
```

---

# 9. CLOSEOUT

Create:

`docs/phase/Phase_15/11_Phase_15_D3_Retrieval_Exposure_Cooldown_Closeout_Report_EXACT.md`

Stop at:
`READY_FOR_REVIEW`
