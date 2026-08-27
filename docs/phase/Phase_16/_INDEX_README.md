# Phase 16 Document Set Index

Formal phase: **Phase 16 — Work Sovereignty & Verified Agent Execution**

```text
PHASE15_FROZEN_SHA = 6d9b30d79d64e5ea566fcb2a0fd5a46276a8139e
PHASE15_STATUS     = CLOSED / FROZEN
```

Integration branch: `feature/phase16-work-sovereignty`.

## Canonical documents

| No. | Delta | Document |
|---:|:---:|---|
| 01 | Master | `01_Phase_16_Work_Sovereignty_Verified_Agent_Execution_Master_Plan_EXACT.md` |
| 02 | 16A | `02_Phase_16_16A_WorkContract_Task_Brief_EXACT.md` |
| 03 | 16A | `03_Phase_16_16A_WorkContract_Closeout_Report_EXACT.md` |
| 04 | 16B | `04_Phase_16_16B_ExecutionBackend_Protocol_Registry_Task_Brief_EXACT.md` |
| 05 | 16B | `05_Phase_16_16B_ExecutionBackend_Protocol_Registry_Closeout_Report_EXACT.md` |
| 06 | 16D | `06_Phase_16_16D_Permission_Approval_Boundary_Task_Brief_EXACT.md` |
| 07 | 16D | `07_Phase_16_16D_Permission_Approval_Boundary_Closeout_Report_EXACT.md` |
| 08 | 16E | `08_Phase_16_16E_Backend_Event_Normalization_Task_Brief_EXACT.md` |
| 09 | 16E | `09_Phase_16_16E_Backend_Event_Normalization_Closeout_Report_EXACT.md` |
| 10 | 16C | `10_Phase_16_16C_Hermes_API_Backend_Adapter_Task_Brief_EXACT.md` |
| 11 | 16C | `11_Phase_16_16C_Hermes_API_Backend_Adapter_Closeout_Report_EXACT.md` |
| 12 | 16F | `12_Phase_16_16F_Independent_Verification_Bounded_Repair_Task_Brief_EXACT.md` |
| 13 | 16F | `13_Phase_16_16F_Independent_Verification_Bounded_Repair_Closeout_Report_EXACT.md` |
| 14 | 16H | `14_Phase_16_16H_Recovery_Idempotency_Cancellation_Backpressure_Task_Brief_EXACT.md` |
| 15 | 16H | `15_Phase_16_16H_Recovery_Idempotency_Cancellation_Backpressure_Closeout_Report_EXACT.md` |
| 16 | 16G | `16_Phase_16_16G_Verified_C7_C6_Commit_Task_Brief_EXACT.md` |
| 17 | 16G | `17_Phase_16_16G_Verified_C7_C6_Commit_Closeout_Report_EXACT.md` |
| 18 | 16I | `18_Phase_16_16I_Integrated_Final_Gate_Task_Brief_EXACT.md` |
| 19 | 16I | `19_Phase_16_16I_Integrated_Final_Closeout_Report_EXACT.md` |

Document 01 is the unique Master Plan. Documents 02–19 are constrained derivatives and cannot
override it. Every closeout is an unexecuted template until real evidence replaces its placeholders.

## Locked implementation order

```text
16A → 16B → 16D → 16E → 16C → 16F → 16H → 16G → 16I
```

16H precedes 16G deliberately: durable idempotency/recovery and the truth-commit claim must exist
before exactly-once C7/C6 projection.

Each Delta requires latest accepted integration baseline → task branch → implementation/tests →
external reviewer PASS → ff-only integration. The next Delta may not start earlier.

## Non-authoritative inputs

The following `_night_*` proposals are design evidence only, are not part of this canonical package,
and cannot authorize implementation:

```text
_night_external_recon_raw.md
_night_phase16_architecture_preflight.md
_night_phase16_authority_redteam.md
```
