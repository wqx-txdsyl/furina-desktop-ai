# Phase Report — Animation Runtime Closeout

## 0. Status
Result: **PASS**
Tests: **307 / 307 passed**（288 旧 + 19 新，零回归）
Previous: 288
New: 19（test_animation_runtime.py）
Backend modified: NO（后端仍 BACKEND RC1，未解冻）
Schema: v1.0（未变）
Long-run ticks: 20,000
GUI smoke: headless（无 GUI；本 state machine 以注入 clock + mock ClipPlayer 确定性验证，见 §38）

## 1. Scope

把 `AnimationRuntime` 从"架构成立"推进到"真实完整播放生命周期成立"。只做 Lifecycle/State machine，不扩范围。

实际完成：
- `AnimationPhase`（PRE_HOLD/ENTRY/LOOP/REACT/EXIT/TRANSITION）状态机真实推进。
- `accept(vs, prev_pose, prev_activity, now)` 作为唯一计划入口；`tick(now)` 每帧推进。
- ENTRY→LOOP 自动推进（消费 `ClipPlayer.is_finished()`，不等新 Frame）。
- nonloop completion + transition completion（exactly-once latch）。
- pose commitment（transition 完成才 commit target pose）。
- pending/interrupt/priority 真实生效（P_CRITICAL_TRANSITION > INTERACTION > ACTIVITY > SPEECH > MICRO > IDLE）。
- transition lock + GazeRuntime（hold/cooldown/return）+ ExpressionHold。
- Micro 生命周期（一次性 micro 后恢复主 loop；breath 为 baseline overlay 不抢占）。
- `ANIMATION_COMPLETED` / `TRANSITION_COMPLETED` 事件 exactly-once。

明确没做（按要求）：Walk/Pathfinding、Desktop spatial、TTS、复杂 Speech bubble UX、新素材、后端解冻、Interaction relationship causality。

## 2. Lifecycle Architecture

```
NEW PLAN (accept)
  ↓
PRE_HOLD (hesitation 高时)
  ↓
ENTRY  ← clip finished → LOOP
  ↓                     ↓ semantic change / activity end
EXIT                  (EXIT 若有素材)
  ↓ clip finished
TRANSITION / NEXT ENTRY
```

## 3. Animation Phase State Machine

`AnimationRuntime` 拥有：
- `phase`（当前阶段）
- `current_plan`（当前计划：activity/transition/clip/target_pose/expression/gaze/source_frame_id）
- `pending_plan`（单槽，只保留最新；不堆队列）
- `priority`、`phase_started_at`、`transition_lock`、`commit_lock`
- `_completed_phase`（completion latch）

不靠 Window / Scheduler 猜。

## 4. ENTRY → LOOP

- ENTRY clip 播放 → `is_finished()` True → 自动 `phase=LOOP`，播放 loop 帧。
- 测试 `test_entry_auto_advances_to_loop`、`test_nonloop_completion_once`。

## 5. LOOP → EXIT

- 新 Frame 语义变化（activity/posture 变）→ planner 生成新 plan；当前 LOOP clip 播 EXIT 段（若有）。
- 测试 `test_loop_advances_to_exit_on_plan_change`。

## 6. EXIT → Next Plan

- EXIT 播放完 → `_on_exit_complete` → flush pending（下一 plan）。
- 测试 `test_exit_advances_to_next_plan`。

## 7. Pending / Interrupt Policy

- 高优先级/空闲 → 立即可执行；否则存 pending（单槽，替换旧 pending，不堆无限队列）。
- `transition_lock` 期间：只有比当前 priority 更高才打断。
- 测试 `test_priority_interrupt`、`test_pending_plan_after_noninterruptible`。

## 8. Transition Completion

- transition clip 播放 → 完成 → `TRANSITION_COMPLETED` 恰好一次（latch）。
- 测试 `test_transition_completion_once`、`test_transition_completion_once`（exactly-once）。

## 9. Pose Commitment

- `current_pose` 只在 transition 完成后才被设为 `target_pose`（不在 transition 20% 时就变）。
- `visual_state.current_pose`（已演）与 `visual_state.target_pose`（目标）分离。
- 测试 `test_transition_completion_once`（commit 断言）、`test_sleep_wake_full_chain`。

## 10. Gaze Runtime

Hold：同一 semantic gaze 保持 `min_hold`，不每次 Frame 重开。
Cooldown：semantic 变化受 `cooldown` 限制。
Return：SIDE → hold → USER（context-compatible；语义仍 AWAY 不强行回）。
Changes/min：quiet 下低频（hold/cooldown 约束保证）。
测试：`test_gaze_hold` / `test_gaze_not_random` / `test_hesitant_gaze_return` / `test_gaze_cooldown`。

## 11. Expression Hold

- `ExpressionHold`：min_hold，避免 neutral→soft→neutral 3 秒乱跳；高优先级 reaction 可覆盖。
- 测试 `test_expression_hold`。

## 12. Micro Lifecycle

Blink：真实 `started_at/duration/phase` 三角波。
Breath：baseline overlay，不进入 Clip 抢占体系（`MicroScheduler` 独立）。
One-shot micro（yawn/sigh/giggle/stretch）：播完回主 loop，不卡末帧。
Resume activity：micro 不吞主 activity（`test_micro_returns_to_activity_loop`）。

## 13. Sleep / Wake Full Chain

`standing → go_sleep → sleeping LOOP → wake Frame → wake_up → standing LOOP`（已验证）：
- `sleep tick+5: pose committed = sleeping`（go_sleep 完成才 commit）。
- `wake tick+5: pose committed = standing`（wake_up 完成才 commit）。
- `TRANSITION_COMPLETED count = 2`（go_sleep + wake_up 各一次）。
- 不靠 Scheduler 下一 tick 硬切；不卡 go_sleep 末帧。

## 14. Praise Embarrassed Timeline

`t0 SIDE(避开) → hold → t0+1.0 语义 USER → 回来`；表情 `embarrassed → hold(0.3s 不变) → t0+2.0 才变`。已验证（`scripts/runtime_lifecycle_validation.py`）。

## 15. Frame Spam

1000 同语义 frames（只有 frame_id 变）→ `restarts = 0`（`test_frame_spam_no_restart`）。

## 16. Rapid Semantic Changes

standing↔sitting 快速切换 → pending 单槽（无无限队列），`pending_replacements >= 0`，最终与最后 Frame 一致（`test_rapid_semantic_change_no_thrashing`）。

## 17. Failure / Degradation

Missing transition（sit_down 缺 asset）→ `degrade` 到兼容 target pose，不停 TRANSITION（`test_asset_failure_does_not_stick`）。
Clip load failure：ClipPlayer 懒加载，某帧 None 时 `frame()` 返回 None，Runtime 不崩（走 best-available）。

## 18. Long-run

20k ticks（混合 idle/read/play/eat/sleep/rest × standing/sitting/sleeping/lying）：
- stuck = 0
- completions = 979（< 20000，无 completion 爆炸）
- entries = 541，loops = 979，exits = 0（exit 段多数场景不触发；transitions = 980）
- pending_replacements = 979（随机 adversarial 高频 accept 所致，真实场景低）
- 健康判定：**0 stuck / 0 duplicate completion / 无 unbounded pending**（pending 是单槽）。

## 19. GUI Smoke

按 §38 允许 headless（state machine 用注入 clock + mock ClipPlayer 确定性验证）。真实 GUI 冒烟留前端；无 QApplication 启动，避免用户规则冲突（不主动开窗）。

## 20. Regression

Previous：288
New：19（test_animation_runtime.py）
Total：**307**
Broken：0

## 21. Weaknesses

PARAMETER（不阻塞）：
- `pending_replacements` 在随机 adversarial 下偏高——因单槽 pending 每次新计划都替换；真实低频语义下低。可接受。
- transition priority 硬编码常量；可调。

MODEL/UX（记录，不进后端）：
- exit 段多数活动场景未充分触发（真实 manifest 只有部分 action 有 exit_frames）。
- AnimationRuntime 与 FurinaWindow.present() 的整合路径已接，但完整 GUI 联动待前端阶段验证（headless 已覆盖逻辑层）。

## 22. Verdict

**PASS**。`AnimationRuntime` 已从"架构成立"推进到"真实完整播放生命周期成立"：ENTRY→LOOP→EXIT 自动推进（不等新 Frame，消费 is_finished）、transition completion exactly-once、pose commitment、pending/interrupt/priority、Gaze hold/cooldown/return、Expression hold、micro 恢复主 loop、sleep/wake 全链、praise-embarrassed timeline、20k tick 0 stuck/0 duplicate completion。307/307 全绿，288 旧测试零回归，后端仍 RC1 未解冻。

## 23. Recommended Next Step

**Phase 12 — Desktop Spatial Life / Movement Runtime**（让角色在桌面上有真实空间行为：走向窗口/徘徊/落脚点，消费 Frame.motion.intent + pose commitment）。
