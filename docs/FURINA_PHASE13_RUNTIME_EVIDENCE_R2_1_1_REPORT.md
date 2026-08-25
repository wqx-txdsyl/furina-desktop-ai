# Furina Desktop AI — Phase 13 Runtime Evidence Blocker Repair R2.1.1 (FINAL Contract Closure) 报告

**冻结基线：** `218ddc67566a7c08422537450ecde106a5571d91`（832 tests）
**分支：** `fix/phase13-runtime-evidence-r2-1-1`（本补丁提交见文末）
**严格范围：** 只修 R2.1 已声明但尚未真正满足的 residual；未新增 Persona 优化；未改 LifeBrain / Motivation / Spatial / Relationship / Emotion / Feeding / Agent Planner / Agent Tools。原 832 全保留（0 delete/skip/xfail/放宽），新增 14 项边界测试。

---

## A. 每个 residual 的 root cause / fix

### ① P0 — HARD candidate 必须 NEVER surface
- 根因：soft-surface 分支按 soft 数量选优 —— attempt=HARD+0soft、retry=0hard+1soft 时会按 soft 更少**选回 HARD attempt**。
- fix：选择优先级 A. hard==0 永远优先于 hard>0（retry 无 HARD → 一律 surface retry）；B. 仅双方 hard==0 才按 soft 数量选优；C. 双方 HARD → 前面已 FAILED。另加 **surface invariant 守卫**：任何将被 surface 的 speech，`v.hard_issues` 非空 → 改 FAILED（绝不泄漏 HARD）。

### ② P0 — severity table 冻结
- 根因：`example_copy` 误在 `_HARD_ISSUES`。
- fix：移出 `_HARD_ISSUES`（=SOFT）；example-copy attempt+retry → surface + `soft_issues` 含 example_copy，不 FAILED。

### ③ P0 — GodCalibrationGate 不得杀 direct 可用性
- 根因：旧行为 `gate_output(None)` → `god_gate_suppressed` → DirectTurn FAILED，与"god 风格=SOFT"矛盾。
- fix：`DIRECT_USER_TURN` + user_initiated 时 gate 抑制 → 确定性 `本神→我` 替换 + 记录 SOFT `god_reference_suppressed`，**绝不 FAILED**；ambient lane 保留 suppression 语义。

### ④ P0 — 真实可见 speech-event 投递
- 根因：speech_id 只解决 text-dedupe；Scheduler 仍只有一个 `_speech` 槽 —— 多个 `_say()` 在 Frame publish 前发生只显示最后一个。
- fix：新增 `EventType.SPEECH_SURFACED`（speech_id/text/channel/turn_id）；`scheduler._say()` 每次 utterance 发出该事件；Harness 从事件 **exactly-once** 记录（Furina utterance 按 speech_id 去重；Frame 只负责当前视觉快照，不再承担历史队列职责）。HARD INTEGRATION：真实 App/Scheduler/Harness 链 5 个全 FAILED DirectTurn 同 SYSTEM_STATUS → terminal=5、pending=0、visible utterance=5、每 turn_id 恰一个可见终态；2 个同文本正常回复 → visible=2。

### ⑤ P2 — Furina utterance 绑定 DirectTurn
- 根因：Furina utterance turn_id=None/channel=""（A-STRESS 只能按数组位置猜）。
- fix：BRAIN_SPOKE/`_system_status_failure`/`_speak_via_dialogue` 均携带 channel + turn_id → SPEECH_SURFACED → utterance 含 role/turn_id/channel/speech_id/text/terminal_status；`_turn_terminal` 映射处理"终态 trace 先到、utterance 后到"的顺序（FAILED 的 SYSTEM_STATUS 也绑定对应 turn_id）。

### ⑥ P0-2 — lifecycle badge active state
- 根因：`_on_direct_turn_trace` 只在终态更新 badge → 新 turn 入队期间仍显示旧 LAST_OK。
- fix：DIRECT_INGRESS/QUEUED → status=QUEUED；GENERATION_STARTED → status=GENERATING；终态 → 终态。逐相位测试：QUEUED/GENERATING→RUNNING/PENDING、REPLIED→LAST_OK；previous LAST_OK + 新 QUEUED → 不得继续 LAST_OK。

### ⑦ P0-3 — validation telemetry 进 DIRECT_TURN_TRACE
- 根因：terminal payload 无 validation_issues/hard_issues/soft_issues。
- fix：queue `_trace` payload 增加三项（EventBus 直读，不依赖 private recent_outcomes）；harness `_on_direct_turn_trace` 保存进 recorder（output_summary 含 hard/soft）。测试：soft-surfaced REPLIED soft_issues!=[]、hard-failed FAILED hard_issues!=[] 均从 EventBus 读到。

### ⑧ P0 — severity invariant
- 根因：`activity_contradiction` 只 append 不设 valid=False → 可能 valid=True 且 hard_issues!=[]。
- fix：`activity_contradiction` 设 valid=False；`_classify()` 统一 invariant：hard_issues 非空 ⇒ valid=False。测试：offer_help 无帮助语义 → hard_issues 含 activity_contradiction 且 valid==False；多组输入验证无 valid=True+hard。

### ⑨ P1-4 — Agent success 必须用 AGENT_REPORT
- 根因：`_on_agent_done` 未传 interaction="agent" → channel=INTERACTION_REACTION、task_mode=False。
- fix：success 报告传 `interaction="agent"` → channel=AGENT_REPORT、task_mode=True、activity=agent_report、context=result-bound facts。测试断言 captured kwargs。

## B. FILES CHANGED
`furina/core/event_bus.py`（SPEECH_SURFACED） · `furina/runtime/scheduler.py`（_say 事件+channel/turn_id 绑定；agent done interaction；_on_brain 绑定） · `furina/runtime/harness/controller.py`（SPEECH_SURFACED 订阅+exactly-once；utterance 去重；badge active state；validation telemetry；_turn_terminal） · `furina/dialogue/validator.py`（example_copy SOFT；activity_contradiction valid=False；_classify invariant） · `furina/dialogue_brain.py`（HARD 候选选择优先级+surface invariant；god gate direct 不杀） · `furina/runtime/dialogue_queue.py`（trace payload 三项） · `furina/app.py`（_system_status_failure turn_id；BRAIN_SPOKE channel/turn_id；feed channel） · `tests/test_phase13_r11_residuals.py`/`test_dialogue_liveness.py`/`test_phase13_r21_runtime_evidence.py`（_say 新签名机械兼容） · `tests/test_phase13_r211_contract_closure.py`（新增 14 项）。

## C. TESTS ADDED（14 项）
①（3）：HARD attempt+soft retry → surface retry 且 hard_issues==[]；双方 hard==0 按 soft 选优；双方 HARD FAILED。②（2）：example_copy=SOFT 不在 HARD；example-copy attempt+retry surface+soft_issues。③（2）：direct 单次本神 → 不 FAILED/替换本神/soft 记录；ambient 保留 suppression。④+⑤（2）：真实链 5×同 SYSTEM_STATUS → 5 可见+每 turn_id 恰一终态+terminal_status 绑定；2×同文本正常回复 → 2 可见+异 speech_id。⑥（1）：逐相位 badge（QUEUED/GENERATING→RUNNING/PENDING、REPLIED→LAST_OK、新 QUEUED 不得停留 LAST_OK）。⑦（1）：EventBus 直读 soft/hard telemetry。⑧（2）：activity_contradiction invariant；无 valid=True+hard。⑨（1）：Agent success captured kwargs channel=AGENT_REPORT、task_mode=True、context 含事实。

## D. FULL SUITE ×3
```
run 1：846 passed / 0 failed（26.8s）
run 2：846 passed / 0 failed
run 3：846 passed / 0 failed
专项：14 passed；原 832 全保留（0 delete/skip/xfail/放宽；仅 _say 新签名对测试 stub 机械兼容）
Selfcheck：SELFCHECK OK
Smoke：SMOKE OK
```

## E. GIT
```
branch: fix/phase13-runtime-evidence-r2-1-1
commit SHA: （见提交结果）
commit message: Phase 13 Runtime Evidence Blocker Repair R2.1.1 FINAL Contract Closure: HARD-never-surface + surface invariant (1), example_copy SOFT (2), god gate direct availability (3), SPEECH_SURFACED visible event (4), Furina utterance DirectTurn binding (5), badge active states (6), validation telemetry in trace (7), severity invariant (8), agent success AGENT_REPORT (9) (846 tests)
```

## F. UNRESOLVED
NONE

---

未声称 R2/R3/Persona/Phase 13 PASS；不跑 Runtime Manual，不自评 Windows CI green（本机即 Windows，结果供评审参考）。验收权不属 Coding Agent。
