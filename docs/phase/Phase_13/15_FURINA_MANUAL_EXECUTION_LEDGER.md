# Furina Desktop AI — Manual Experience Acceptance Execution Ledger

**Frozen backend baseline:** `0402e7f1236cbc681e92c7ed7feca19ce5826618`

## Gate status

```text
PHASE 13 TECHNICAL = PASS
PRE-MANUAL AUDIT = PASS
BACKEND FUNCTIONAL CONTRACT = FROZEN
MANUAL EXPERIENCE ACCEPTANCE = STARTED
PHASE 14 = BLOCKED UNTIL MANUAL PASS
```

## M0 Environment sanity

| Item | Status | Evidence |
|---|---|---|
| GitHub frozen source baseline readable | PASS | `0402e7f` reviewed through GitHub connector |
| Final fallback gate A/B/C | PASS | StateEngine availability-only truth; BehaviorEngine choose/current/chain gates; valid-present restoration tests |
| Local Python audit runtime | PASS | Python 3.13 environment available |
| Qt/PySide6 offscreen runtime | PASS | PySide6 6.11.2 initialized with `QT_QPA_PLATFORM=offscreen` |
| Exact `0402e7f` source materialized in local execution container | PENDING-ARTIFACT | GitHub connector can read source, but sandbox shell cannot DNS/clone GitHub; local ZIPs predate frozen baseline |
| Real Zhipu/GLM endpoint from reviewer sandbox | UNAVAILABLE | sandbox DNS cannot resolve `open.bigmodel.cn`; no API key was sent or exposed |

## Manual A — reviewer executable

| Group | Status |
|---|---|
| A1 Runtime/startup/restart | WAITING FOR EXACT FROZEN SOURCE |
| A2 World/presence simulation | WAITING FOR EXACT FROZEN SOURCE |
| A3 Needs/long-run Life | WAITING FOR EXACT FROZEN SOURCE |
| A4 Emotion/state causality | WAITING FOR EXACT FROZEN SOURCE |
| A5 Relationship causality | WAITING FOR EXACT FROZEN SOURCE |
| A6 Dialogue mechanics | WAITING FOR EXACT FROZEN SOURCE |
| A7 Persona blind evaluation | WAITING FOR REAL GLM TRANSCRIPT |
| A8 Memory/restart | WAITING FOR EXACT FROZEN SOURCE |
| A9 Feed | WAITING FOR EXACT FROZEN SOURCE |
| A10 Agent truthfulness | WAITING FOR EXACT FROZEN SOURCE |
| A11 Spatial trajectories | WAITING FOR EXACT FROZEN SOURCE |
| A12 Failure/recovery | PARTIAL — network-unavailable case can be tested once exact source is materialized |

## Manual B — user-required

- Real Win32 foreground process / window transitions
- Real GetLastInputInfo idle / away / return
- Real mouse click / pet / poke / drag ergonomics
- Multi-window / DPI / multi-monitor behavior
- Real app-launch observation (Calculator / Notepad / failure)
- Real Qt responsiveness under actual model/network latency
- Real `glm-4v-flash` transcript if reviewer sandbox remains network-blocked
- 30–120 minute real coexistence session
- Final subjective Furina likeness and movement naturalness

## Evidence policy

No Manual group will be marked PASS from source review or automated test count alone.
Exact frozen-build execution is required for Manual A, and real Windows/model evidence is required for Manual B.
