# Phase Report — Frontend Character Runtime / Animation Integration

## 0. Status
Result: **PASS**
Tests: **288 / 288 passed**（273 旧 + 15 新，零回归）
Previous: 273
New: 15（test_frontend_phase11.py）
Backend frozen: ✅（**BACKEND RC1**，未解冻）
Freeze version: RC1（schema v1.0）
Anti-collapse: OFF
Model: glm-4v-flash（唯一 LLM；本阶段 0 新 LLM 调用，前端全确定性）

## 1. Scope

Step 0（4 件强制前置契约清理 已完成）+ 动画 Runtime 骨架 + 6 场景验证 + Asset 覆盖扫描。

实际完成：
- Step 0.1：删除硬编码 `SPEECH_LINES`/`_behavior_speech`（DialogueBrain 唯一语言源，失败→silence）。
- Step 0.2：`CharacterRuntimeFrame` 深不可变（micro_preferences/body_reasons/speech_reasons→tuple，needs→MappingProxyType；to_dict 仍输出 v1 JSON）。
- Step 0.3：删除 Scheduler→Window 双重直写（Scheduler 只发布 Frame；`FrontendFrameConsumer` 驱动 Window）。
- Step 0.4：修复 `AnimationController.play(spec)` 契约 + blink 真实发生 bug + nonloop `progress/is_finished`。
- 新增 `FrontendVisualState` / `FrontendFrameConsumer`（semantic diff）/ `AnimationPlanner`（transition graph + hesitation hold）/ `AnimationRuntime` / `MicroScheduler`（呼吸/眨眼/视线/微动作独立时钟）。
- `FurinaWindow` 改为纯 View（`present()` 主路径；`set_pose_semantics` deprecated）。
- 扫描真实 manifest → `docs/ASSET_COVERAGE_V1.md`。
- 6 关键场景验证（`scripts/scenario_validation.py`）全 PASS。

明确没做（按要求）：Walk/Pathfinding、TTS、Asset 生成、Renderer overhaul、Speech bubble UX 完整（只从 Frame 显示）。

## 2. Files

Added：`furina/runtime/frontend.py`、`furina/runtime/micro.py`、`tests/test_frontend_phase11.py`、
`scripts/scenario_validation.py`、`scripts/asset_coverage.py`、`docs/ASSET_COVERAGE_V1.md`。
Modified：`furina/runtime/frame.py`（deep immutable）、`furina/runtime/furina_window.py`（纯 View +
blink/paint 修复）、`furina/runtime/scheduler.py`（删除硬编码台词 + 不再直写 window）、
`furina/runtime/animation.py`（progress/is_finished）、`furina/app.py`（FrontendFrameConsumer + AnimationRuntime wiring + 定时器）。
Unchanged（冻结后端）：`furina/state/emotion/behavior/persona/relationship/memory/world_perception/dialogue/embodiment/life_brain/director` 全部未动。（本阶段对 Scheduler 的改动只限前端表现层 wiring + 硬编码台词删除，未改 Life Runtime semantics。）

## 3. Feature Architecture（Before → After）

Before（控制权分散）：
```
Scheduler owns presentation（set_pose_semantics + set_render_state，且重复两遍）
Window owns animation choice（set_pose_semantics 内部按 activity 找 asset）
paintEvent owns micro timing（_breath_t += 0.016 / 随机 gaze / 算 blink）
```
After（控制权迁移）：
```
Frame owns semantic truth
FrontendFrameConsumer owns semantic diff（activity/expression/gaze/posture/micro/speech → VisualState）
AnimationRuntime owns presentation timing（QTimer 30FPS）
MicroScheduler owns breath/blink/gaze/micro（MathScheduler 独立时钟）
window.present() 是唯一动画 owner；paintEvent 只绘制
```

数据流：
```
CharacterRuntimeFrame → CHARACTER_FRAME_UPDATED → FrontendFrameConsumer (diff)
  → FrontendVisualState → AnimationRuntime/AnimationPlanner (+MicroScheduler)
  → window.present(...) → paintEvent (只画)
```

## 4. CharacterRuntimeFrame 深不可变（Step 0.2）

- `FrameBody.micro_preferences: tuple`、`FrameDebug.body_reasons/speech_reasons: tuple`、
  `FrameDebug.needs: MappingProxyType`。
- `__post_init__` 深冻结（`object.__setattr__`），前端不可 append/改映射。
- `to_dict(debug=...)` 仍输出 JSON list/dict（`micro_preferences: [...]`、`needs: {...}`）——
  **schema v1.0 JSON contract 不变**。
- 测试：`test_frame_nested_collection_immutable` / `test_event_frame_cannot_be_mutated` /
  `test_serialization_still_v1`。

## 5. FrontendFrameConsumer（semantic diff，§15）

订阅 `CHARACTER_FRAME_UPDATED`，比较：activity.name / body.expression / body.gaze / body.posture /
body.transition_style / body.hesitation / speech.text / speech.should_speak / motion.intent /
interaction.response_mode。
`frame_id/timestamp/debug/world_hint-only` 变化**不重启动画**。测试 `test_consumer_diff_activity_change`。

## 6. AnimationPlanner（transition graph + hesitation，§11/§13）

- 姿态过渡来自真实 manifest 的 6 条 transition 序列：`sit_down / stand_up / lie_down / lie_up /
  go_sleep / wake_up`（各含 entry/loop/exit 帧）。
- `TRANSITION_GRAPH`：`(standing,sitting)→sit_down` 等；不支持则走 best-available。
- hesitation（≥0.6 + HESITANT）→ `pre_hold_ms`（250~530ms）+ 后续 LOOK_SHIFT。不做"hesitation→固定向左看"。
- 不依赖后端 activity.phase；用 `prev_frame vs current_frame` + `prev_pose/target_pose` 推导 ENTRY/LOOP/EXIT/TRANSITION。

## 7. MicroScheduler（真实 blink/gaze/micro，§9/§10/§24）

- `MicroState`：breath/blink/gaze/active_micro，全部独立时钟（由 AnimationRuntime.tick 驱动，**不假设 paint==16ms**）。
- blink：`next_at / started_at / duration / phase` 三角波重算（修复旧 `now - future` 使 blink==0 的 bug）。
- gaze：权重池顺序切换（不强随机）；micro：从 `Frame.body.micro_preferences` 挑，带 recency 抑制。
- 呼吸为 baseline，不由本层关闭（§24）。
- 测试：`test_blink_actually_occurs`（确认真实非 0 / 峰值 >0.5）。

## 8. Step 0.3 单动画 owner

- `FurinaWindow.present()` 是唯一对 `ClipPlayer.play` 负责的入口（`_apply_clip` 把语义 clip 解析为帧）。
- `set_pose_semantics` deprecated（legacy 兼容，不走主路径）。
- Scheduler 不再调用 `window.set_pose_semantics/set_render_state`（源码断言 0 次）。
- drag 覆写保留（`set_drag_pose`），是唯一的 Window/InputRouter 即时覆写，不争抢主路径（§17）。
- 测试：`test_single_animation_owner` / `test_scheduler_no_direct_window_render` /
  `test_scheduler_no_duplicate_window_write`。

## 9. 6 关键场景验证（全部 PASS）

`scripts/scenario_validation.py`（不启动 GUI，走 pure 逻辑）：
| 场景 | activity | expr | gaze | target_pose | 关键 | RESULT |
|---|---|---|---|---|---|---|
| Quiet Read | read | neutral | SCREEN | seated | micro=BLINK/BREATH | PASS |
| Praise Embarrassed | talk | embarrassed | USER | upright | hes=0.68 → pre_hold=522ms | PASS |
| Proud | talk | proud | USER | upright | expr=proud | PASS |
| Failure High Trust | talk | sad | USER | relaxed | gentle | PASS |
| Deep Work Coexistence | think | neutral | SCREEN | seated | speech=None、自活 | PASS |
| Sleep | sleep | (sleepy) | NONE | sleeping | transition=go_sleep | PASS |

其中 Praise Embarrassed 验证了"被夸后**停一下**（pre_hold 522ms）、视线/犹豫再动"的时序；Sleep 验证 `go_sleep → sleeping loop → wake_up`（不靠 Scheduler 下一 tick 才跳）。

## 10. Asset 覆盖扫描（`docs/ASSET_COVERAGE_V1.md`）

真实 manifest 77 条（base_pose 12 / expression 21 / gaze 12 / micro 10 / action 9 / transition 6 / prop 5 / interaction 2）。
- 520 个真实语义请求（posture×expression×gaze）全部 resolve 到 asset（**100%，缺失 0**）——
  因 Resolver 有 best-available 回退优先级（Exact→Same posture→Same action→Nearest→Neutral）。
- 6 条 transition 序列均带 entry/loop/exit 帧（8/10/8）。
- 结论：Frame 语义 → asset 无硬缺口；缺失时走 best-available 并记 ASSET_MISSING，不 fallback idle。

## 11. FAILURES / 可观察（Step 0.4）

- `AnimationController.play` 契约：`play(spec, now=None)`（三个坏调用已改为 `AnimationSpec(...)`）。
- nonloop completion：新增 `progress()` / `is_finished()`——非 loop 播到末帧即 finished（∨ loop 永不）。
- blink bug 修复：用 `started_at/duration` 三角波，`test_blink_actually_occurs` 断言真实非 0。

## 12. Regression

Previous：273
New：15（test_frontend_phase11.py）
Total：**288**
Broken：0

## 13. Remaining Weaknesses / Future

PARAMETER（不阻塞）：
- `pre_hold_ms` 映射（250~530ms）是配置值，后续可调。
- MicroScheduler gaze 池未按 Frame body.gaze 语义细化（AROUND→controlled sequence 待后续）；当前 semantic gaze 已进入 VisualState。

FRONTEND/FUTURE（下一阶段）：
- 完整 AnimationRuntime 状态机（ENTRY→LOOP→EXIT 需要 ClipPlayer 完成事件推进，已加 `clip_finished` 接口，完整播放交由后续）。
- Speech bubble UX 完整（从 Frame 显示，TTS 未做）。
- GazeRuntime hold/cooldown/return 完整演。
- drag→关系/Emotion 因果（Phase 13）。
- `Renderer.py` 保留兼容/测试，未围绕它重建主路径（按要求）。

SHOULD_FIX（下一步顺手）：
- `FrontendFrameConsumer.visual_phase` 当前被 `_apply_tokens` 设成 `TRANSITION` 触发 replan；最终 phase 推进由 AnimationRuntime 完成。

## 14. Verdict

**PASS**。Step 0 四个契约 Bug（硬编码台词旁路、Frame 深不可变、Scheduler→Window 双重直写、AnimationController 契约 + blink/completion bug）全部清除；真实 `CharacterRuntimeFrame` → `FrontendFrameConsumer` → `AnimationPlanner/MicroScheduler` → `window.present()` 控制权迁移完成，paintEvent 变纯 View（不再推进生命状态）。6 个关键场景（read/praise-embarrassed/proud/failure-high-trust/deep-work/sleep）全 PASS，Asset 覆盖无硬缺口。288/288 测试全绿，273 旧测试零回归，后端仍冻结（RC1 未解冻）。

## 15. Recommended Next Step

**Phase 12 — Asset Resolver / Animation Timing 打磨**：把 `Renderer.py` 合成层与素材主路径真正对齐、完善 AnimationRuntime 的 ENTRY→LOOP→EXIT 状态机（用 `clip_finished`）、做 Speech bubble UX 与 TTS 预留、以及 `FrontendFrameConsumer`→`AnimationRuntime` 相位推进。这一步后，再把前端从"她还活着"的验证推进到真正可用的表现层。
