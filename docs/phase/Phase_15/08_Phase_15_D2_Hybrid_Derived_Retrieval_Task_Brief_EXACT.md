# Phase 15 — D2 Real Hybrid Retrieval on Derived Index
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

`docs/phase/Phase_15/08_Phase_15_D2_Hybrid_Derived_Retrieval_Task_Brief_EXACT.md`

Recommended branch:

`feature/phase15-d2-hybrid-retrieval`

Base:

latest externally accepted integration SHA after D4.

---

# 1. MISSION

Replace naming-only / lexical-only "semantic vector" behavior with a real, bounded hybrid retrieval pipeline while preserving C1-C7 authority.

Required architecture:

```text
selected source-store summaries
→ derived lexical representation
+
derived vector representation
→ candidate union
→ ref dedupe
→ authoritative re-query
→ authority/status/recency/relevance rerank
→ bounded context refs
```

---

# 2. ABSOLUTE AUTHORITY RULE

The index is:

```text
DERIVED
REBUILDABLE
NON-AUTHORITATIVE
NOT C8
```

Delete all index files:

```text
C1-C7 truth must remain fully intact.
```

No vector entry may directly overwrite a C4/C3/C2/C7 row.

---

# 3. EMBEDDING BACKEND

Recon current project dependencies before choosing backend.

Requirements:

```text
local-capable or existing provider abstraction
deterministic fallback
no mandatory cloud dependency for cognition
batch embedding supported if practical
dimension/version metadata stored
```

Do not add a heavyweight dependency without demonstrating need.

Do not copy AronaAI's Chroma dual-write truth model.

---

# 4. INDEX CONTENT

Allowed selected summary representations:

```text
C2 objective summary / trigger topics
C3 bounded memory content
C4 active/superseded structured summary as needed
C7 verified task goal/result summary
```

Forbidden:

```text
API keys
raw private DB dump
raw screenshot stream
unbounded C6
secrets
hidden chain-of-thought
```

---

# 5. HYBRID CANDIDATES

At minimum implement:

```text
lexical candidate path
vector candidate path
candidate union
dedupe by (store, ref_id)
```

Reranker must preserve current authority concepts.

Similarity alone cannot win over truth status.

Example:

```text
superseded C4 high cosine
vs
active C4 lower cosine
→ active truth must win for factual answer assembly.
```

---

# 6. TEMPORAL RETRIEVAL

D2 may consume D4's structured temporal semantics.

Do not build a second independent time parser.

Queries like:

```text
我昨天说过什么计划
上周那个报告
九月的安排
```

should use:

```text
query interpretation
+
structured temporal filters
+
hybrid text retrieval
```

when available.

---

# 7. FAILURE MODES

Required graceful degradation:

```text
embedding backend unavailable
→ lexical path

vector index missing
→ lexical path

vector index corrupted
→ ignore/delete/rebuild safely

embedding dimension/version mismatch
→ reject index and rebuild

source row missing for returned ref
→ drop candidate
```

Never return stale derived text as authoritative truth.

---

# 8. REQUIRED TESTS

```text
D2-T1 exact lexical name retrieval
D2-T2 semantic paraphrase retrieval requiring vector signal
D2-T3 candidate union dedupes refs
D2-T4 active C4 beats superseded derived candidate
D2-T5 archived/low-authority C3 cannot dominate merely by cosine
D2-T6 vector unavailable → lexical works
D2-T7 corrupted index → safe fallback
D2-T8 delete index → source stores unchanged
D2-T9 rebuild idempotent
D2-T10 stale ref missing in source → dropped
D2-T11 index metadata/version mismatch → rebuild/fallback
D2-T12 context bounds remain enforced
D2-T13 C2 activation policy remains respected
D2-T14 secrets are not indexed
```

---

# 9. PERFORMANCE

Measure at least:

```text
small warm retrieval
cold load
rebuild time on test corpus
```

No 60fps loop access to DB/vector search.

Retrieval remains cognition-turn-level work.

---

# 10. GATES

```text
Gate A D2 tests
Gate B D1/D4 accepted tests
Gate C Phase15 retrieval/context tests
Gate D Phase14 provenance preservation
Gate E restart/index rebuild tests
Gate F full suite
```

---

# 11. STATIC AUDIT

Search for:

```text
vector result writing source store
index treated as truth
new C8 storage
raw secret indexing
unbounded C6 indexing
duplicate embedding implementations
```

All must be absent.

---

# 12. CLOSEOUT

Create:

`docs/phase/Phase_15/09_Phase_15_D2_Hybrid_Derived_Retrieval_Closeout_Report_EXACT.md`

Final coding-agent status:
`READY_FOR_REVIEW`
