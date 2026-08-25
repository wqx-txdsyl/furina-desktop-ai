# Phase Report — Desktop Spatial Life / Movement Runtime

## 0. Status

```
Technical Result:        PASS
Manual Visual Result:    PENDING            ← 由用户人工验收（Agent 不勾选视觉清单）
Overall:                 PASS-AUTO / MANUAL_VISUAL_PENDING

Tests:
  Previous:              307
  New:                   42
  Total:                 349
  Broken:                0

Backend:                 BACKEND RC1 — FINAL FREEZE（本轮 0 处后端改动）
Schema:                  CharacterRuntimeFrame v1.0（未变）
Anti-collapse:           OFF（未变）
LLM added:               0

GUI auto gate:           PASS (programmatic; see §2)
50k spatial run:         PASS (oob=0 / stuck=0 / duplicate_arrival=0)
```

> 结论：**技术层面 PASS**。视觉"自不自然"属于人工验收范畴，本轮 Agent 未获得屏幕视觉，
> 不把"窗口成功启动/程序链跑通"写成"视觉体验 PASS"。

---

## 1. Scope

**Implemented（本期完成）**
- 桌面空间生命层 `furina/runtime/spatial/`：`model / resolver / planner / runtime (+adapter)`。
- Spatial Ownership Migration：Scheduler 移除 `_move_target / _walk_visible / _move_step / _maybe_walk_to_window` 生产路径（仅保留 deprecated no-op，生产调用计数 = 0）。
- dt-based 移动 + ease-in/cruise/ease-out + arrival_radius + overshoot 防越。
- 语义空间意图 APPROACH / WITHDRAW / MAINTAIN / NEAR / FAR / REPOSITION / NONE + wander&dwell 约束。
- 拖拽接管（interrupt / commit / grace/manual_position_grace）。
- 屏幕边界安全、屏幕 resize revalidate、多屏 current_screen。
- sleep 禁移 / wake 后允许移动。
- 目标滞后 hysteresis + frame-spam 不重规划。
- 空间事件 `MOVEMENT_STARTED / SPATIAL_TARGET_REACHED / MOVEMENT_INTERRUPTED`（exactly-once）。
- GUI Integration AUTO Gate（`scripts/gui_integration_smoke.py`）。
- 自动验收 `scripts/spatial_validation.py`；人工演示 `scripts/manual_gui_phase12.py`。
- docs/SPATIAL_RUNTIME.md（坐标/锚点/所有权/生命周期）。

**Explicitly not implemented**
- 真实 walk 动画素材（manifest 无 walk sequence）→ 统一 DEGRADED_WALK_VISUAL（§116）。
- A* / NavMesh / 图标碰撞 / 窗户物理碰撞（§78/§79 明确不做）。
- 跨屏追用户（§130 禁止）。鼠标追逐（§129 禁止）。重力 / 跳跃 / 物理（§128 禁止）。
- 到站自动说话 / 改关系 / 记忆 / 情绪（§69/§123-§126 禁止，全部留给后端）。
- Phase 13 的用户互动（摸头 / 点击 / 拖拽 / 喂食 / 呼唤 / 拒绝 / 打断）语义回程。

---

## 2. Step 0 — GUI Technical Integration Gate

`scripts/gui_integration_smoke.py`（offscreen，程序化，非视觉）。运行时长约 20s：

```
QApplication:            created (PASS)
FurinaWindow:            created + apply_reference_size (PASS)
Frame events:            7
Consumer calls:          7
Animation ticks:         1109
Present calls:           1109
Paint calls:             1093
Transitions (active):    240   (TRANSITION phase ticks)
Loop (active):           869
TRANSITION_COMPLETED:    4
Exceptions:              0
Crash:                   0
Thread IDs (qapp/consumer/present/paint):  31520 / 31520 / 31520 / 31520
Qt mutation on GUI thread:                 PASS
Result:                  PASS
```

IMPORTANT：以上**只表明程序化管线运行正确**；
`entry_active=0` 因为注入的场景 pose 变化未被强触发（场景切换快）。

**本轮顺带修复一个真实 latent bug**：`app._render_tick` 里 `micro_sched.step()` 返回
`MicroState`（含 `.breath / .blink / .active_micro`），但旧代码误写 `ms.state.breath`，
真实 GUI 路径从未被跑过（之前有"不启动 GUI 窗口"约束，只跑 headless），只有启动真窗口才触发。
本轮 Step 0 把它暴露并修复为 `ms.breath / ms.blink / ms.active_micro`。

---

## 3. Ownership Migration

**Before**
```
Scheduler:
  _move_target            ← 保存像素目标
  _walk_visible           ← 保存 walk 布尔
  _move_step()            ← fast tick 直推 window.set_position
  _maybe_walk_to_window() ← activity→随机/边缘坐标 + 直接 life.macro = RESTING
```

**After**
```
Scheduler spatial pixel ownership:  REMOVED（生产路径 0）
Production calls remaining:         0
Spatial owner:                      DesktopSpatialRuntime
Scheduler 允许的残留:               _move_step/_maybe_walk_to_window 为 deprecated no-op
                                    （DeprecationWarning，不移动窗口、不改 life.macro）
```

验证（tests/test_spatial_ownership.py）：
`window.set_position(` 不在 Scheduler 源码；`self._move_target / self._walk_visible` 不在；
`step()` 不移动窗口；legacy 方法为 no-op；`life.macro = RESTING` 段已删。

---

## 4. Final Spatial Architecture

```
BACKEND RC1
   │  (motion.intent/target/direction/speed_semantic/allow_reposition
   │   body.proximity/movement_tempo/movement_amplitude/hesitation/transition_style
   │   activity.name / world_hint.user_*)
   ▼
CharacterRuntimeFrame
   ▼
SpatialIntentResolver  (语义意图解释，不重新决策)
   ▼
MovementPlan  →  SpatialPlanner  (语义目标 → safe 几何坐标 / foot anchor)
   ▼
DesktopSpatialRuntime  (状态机 + dt 移动 + 拖拽 + 长跑健康)  ← 自主移动唯一 owner
   ├─────────► AnimationRuntime.set_movement(moving, facing)  (walk 视觉 / DEGRADED)
   ▼
PositionAdapter (foot ↔ set_position(pos))
   ▼
FurinaWindow.set_position()
```

---

## 5. SpatialState（FrontendSpatialState）

| Field | Meaning |
|---|---|
| state | SpatialState（IDLE/PREPARING/STARTING/MOVING/ARRIVING/ARRIVED/INTERRUPTED/DRAGGED） |
| position / anchor_position | foot anchor（脚底中点）当前坐标（screen logical pixel） |
| current_screen | 所在屏幕 index |
| current_zone | 所在区域（open/corner/near_user/edge） |
| target_type | TargetType（CURRENT/USER_WINDOW_EDGE/NEAR_USER_SAFE/QUIET_CORNER/...） |
| target_position | foot anchor 目标 |
| facing | LEFT / RIGHT / FRONT |
| velocity / speed | 当前速度 / 计划速度（px/s） |
| moving / arrived | 是否移动 / 是否到达 |
| movement_started_at / arrival_time | 起止时间 |
| distance_remaining | 距目标距离 |
| source_frame_id / movement_reason | 来源 frame / 原因 |
| degraded | 缺 walk 素材 → DEGRADED_WALK_VISUAL |
| drag_active | 用户拖拽中 |

---

## 6. MovementPlan

| Field | Meaning |
|---|---|
| intent | 空间意图 |
| start / target | foot anchor 起终点 |
| target_type | 语义目标类型 |
| speed_semantic / speed_px_sec | 语义速度 / 实际 px/s |
| arrival_radius | 到达半径 |
| facing_policy | HORIZONTAL / FACE_USER / FACE_SCREEN |
| pre_move_delay | 起步犹豫（秒） |
| interruptible | 是否可打断 |
| source_frame_id / reason / activity | 来源与原因 |

**禁止包含**：fatigue / social_need / trust / emotion / memory / identity / motivation（§21）。
MovementPlan 只消费 Frame。

---

## 7. Coordinate Model

- **Screen coordinate**：Qt logical pixel 虚拟桌面，原点 = 主屏左上，+x 右 / +y 下。
- **Window coordinate（pos）**：`FurinaWindow.set_position(x, y)` 的 `(x, y)`。`pos.x` = 距窗口左缘 `side` px 的点；`pos.y` = 距窗口顶缘 `top` px 的点。窗口左上角 = `(x - side, y - top)`。
- **Character anchor（foot anchor）**：角色底脚中点（center-x, foot-y）。standing/sitting/lying 画布不同，但脚底锚点稳定，是空间层的位置真相。
- **Adapter 互转**：
  - `foot_to_pos(fx, fy) = (fx - window_w/2 + side, fy - char_h)`
  - `pos_to_foot(x, y) = (x + window_w/2 - side, y + char_h)`
  - 依据：角色在窗口水平居中（char center-x = pos.x - side + window_w/2）；无气泡下移时角色脚底 = pos.y + char_h。
- 全部 Qt logical pixel；DPI 由 Qt 换算。

---

## 8. Safe Bounds

| Source | Value / rule |
|---|---|
| Taskbar | `world.taskbar_height`（默认 48），`available_bounds()` 扣除 |
| Bubble | 保留（顶层气泡区/阴影由 Window clamp 兜底；空间层只算 foot 在屏内） |
| Shadow | `edge_margin` 预留 |
| Edge margin | `config.edge_margin = 24` px |
| Last defense | `FurinaWindow.set_position()` 自身 clamp 保留作最后保险（§40） |

---

## 9. Target Zones

| Target | Resolution Strategy |
|---|---|
| NEAR_USER_SAFE | `world.window_edge_candidates()`：bottom-edge / outside-left / outside-right / safe corner；取离当前最近且合法的 foot 候选（不贴窗口中心） |
| USER_WINDOW_EDGE | 活动窗口下方边缘 |
| USER_WINDOW_SIDE | 活动窗口侧边 |
| QUIET_CORNER | 距用户最远的安全角 |
| LEFT/RIGHT_OPEN_AREA | 可用区网格采样 |
| CURRENT_NEIGHBORHOOD | 当前附近微小修正（REPOSITION / 修复） |
| OPEN_DESKTOP_AREA | 可用区网格 + 回避当前极小邻域 |
| DRAG_RELEASE | 用户释放处（不走自主规划） |
| SAFE_FALLBACK | 就近 safe 修复 |

---

## 10. Spatial Intent Resolution

| Intent | Meaning |
|---|---|
| APPROACH | 走用户附近安全区（非用户中心）；若已足够近则不重走 |
| WITHDRAW | 去更远安全区，增大与用户距离 |
| MAINTAIN | 保持；仅当位置非法才 REPOSITION 修复 |
| NEAR | 距离偏好：已 <= near_radius 则保持，否则靠近（hysteresis） |
| FAR | 距离偏好：已 >= far_radius 则保持，否则远离（hysteresis） |
| REPOSITION | 小幅安全修正（目标移动 / 几何变化 / 位置非法） |
| NONE | 默认不自主移动；仅活动明确允许时(wander/explore)才踱步 |

来源优先级：`motion.intent > body.proximity > activity 语义回退`（§31 只消费，不重新决策）。

---

## 11. Movement Lifecycle

| State | Behavior |
|---|---|
| IDLE | 无计划；flush pending |
| PREPARING | 起步犹豫倒计时（pre_move_delay） |
| STARTING | ease-in 起步加速 |
| MOVING | 巡航，位置推进（dt-based） |
| ARRIVING | ease-out 减速靠近 |
| ARRIVED | 到站停留（minimum_dwell + movement_cooldown），grace 后可再自主 |
| INTERRUPTED | 高优先重规划 / 拖拽打断 |
| DRAGGED | 用户拖拽，位置由鼠标接管；release 提交 |

---

## 12. dt / FPS Independence

| FPS | Arrival time | Final position |
|---|---|---|
| 30 | 4.90 s | (448, 740) |
| 60 | 4.92 s | ~same |
| 120 | 4.91 s | ~same |

Final-position delta: < 20 px（脚到目标，非振荡）。Travel-time delta: < 0.5 s。
（`test_movement_fps_independent`、`spatial_validation FPS PASS`）

---

## 13. Speed Counterfactual

| Speed | travel_time |
|---|---|
| SLOW | 10.1 s |
| NORMAL | 4.9 s |
| ENERGETIC(FAST) | 2.5 s |

Travel_time_slow > normal > energetic（目标一致）。`Speed PASS`。

---

## 14. Hesitation / Transition Style

- Low hesitation (0.2) → pre_move_delay ≈ 0.19 s；High (0.9) → ≈ 0.86 s。`Hesitation PASS`。
- Transition style：HESITANT 起步 > ENERGETIC（`test_transition_style_affects_start`）。
- 高犹豫不取消合法移动（§65）；只拉长起步延迟 / 降低初始加速度。

---

## 15. Movement ↔ Animation

- Walk starts：`DesktopSpatialRuntime.movement_visual().moving=True` → `AnimationRuntime.set_movement(True, facing)`。
- Walk stops：到站后 moving=False → `set_movement(False)`（回 activity clip）。
- Slide cases：缺 walk 素材 → `DEGRADED_WALK_VISUAL`（移动继续，视觉不强行走 idle 造成误判；§116）。
- In-place walk cases：到站后 `movement_visual().moving=False`，不再原地走。
- Facing：dx<0 → LEFT，dx>0 → RIGHT，否则 FRONT。
- Flip：无第二套素材；walk 缺失时记录 degraded，不生成素材（§54/§127）。

`test_movement_walk_sync / no_walk_when_stationary / missing_walk_asset_degrades / no_inplace_walk` 通过。

---

## 16. Approach User

- Start：`activity=approach_user, proximity=APPROACH` → SpatialIntentResolver → APPROACH。
- Resolved target：NEAR_USER_SAFE，foot=(448,740)（距用户窗口左下外侧，不遮正文/按钮）。
- Distance：起点 (300,900) → 目标 (448,740)，travel ≈ 195 px（NORMAL=60px/s）。
- Arrival：到达后 ARRIVED，moving=False。
- Animation：走 walk（可退化为 DEGRADED_WALK_VISUAL）。
- Result：`Approach PASS`（target 非窗口中心）。

---

## 17. Maintain / Quiet Coexistence

- Duration simulated：30 min @ 5 Hz。
- Plans：0。Movement：0。Position drift：0.0 px。
- micro/animation 仍由 AnimationRuntime / MicroScheduler 驱动（不因静止而停）。
- Result：`Quiet PASS`（`test_quiet_coexistence_spatial_stable`）。

---

## 18. Withdraw

- Initial distance：250 px。Final distance：363 px。Target zone：QUIET_CORNER / far。
- Result：`Withdraw PASS`（`400 > 250+50`）。

---

## 19. Wander / Dwell

- Duration：30 min @ 2 Hz。Moves：35 次到达（arrivals=35）。Dwell：有（cooldown 24s）。
- Average dwell：非连续。Moving share：36.2%（< 40%）。
- Result：`Wander PASS`（有停留，不像巡逻机器人）。

---

## 20. Drag / Release

- Movement before drag：MOVING。Interrupt：MOVEMENT_INTERRUPTED 发出，state=DRAGGED。
- Drop commit：释放位置 = 新的空间真相（读 window pos→foot），不 snap 回自主目标。
- Grace period：`manual_position_grace = 15s`（此期间普通 wander/reposition 被 cooldown 约束；高优先 APPROACH/WITHDRAW 可覆盖）。
- Snap-back：无。
- Result：`Drag PASS`（`test_drag_interrupts_movement / drag_commits_position / drag_release_grace`）。

---

## 21. Screen / Bounds

- Resolution change：`_revalidate` 就近修复（`test_screen_resize_revalidate`）。
- Taskbar：`available_bounds()` 扣除。Out-of-bounds：0（`Bounds / 50k out_of_bounds=0`）。
- Screen revalidation：每次 tick 校验当前位置合法性。

---

## 22. Multi-monitor Basic

- Current screen：拖到第二屏（x 起点 1920）→ `current_screen=1`。
- Dragged to second screen：释放后 position 落第二屏，current_screen 更新。
- Autonomous movement：留在当前屏（目标用当前屏几何）。
- Cross-screen chase：不做（§90 禁止）。
- Result：`test_multi_monitor_current_screen` 通过。

---

## 23. Target Hysteresis

- Small target movement（8 px）：不重规划（`_should_skip_replan`）。
- Large target movement（> significant_target_change=200px）：重规划。
- Replans：小变化 = 0。
- Result：`test_target_hysteresis / frame_spam_no_replan` 通过。

---

## 24. Exactly-once Events

- `MOVEMENT_STARTED`：每计划一次（`_start_plan`）。
- `SPATIAL_TARGET_REACHED`：每目标一次（latch per target）。
- `MOVEMENT_INTERRUPTED`：拖拽 / 高优先重规划。
- Duplicates：0（`_arrived_emitted_for` latch）。

---

## 25. Frame Spam

- Frames：1000 同空间语义（只有 frame_id/time 变）。
- Spatial semantic changes：0。Replans：≈0（`plans` 增量 < 5）。
- Expected：不重规划。
- Result：`test_frame_spam_no_replan` 通过。

---

## 26. Failure Handling

| 情况 | 结果 |
|---|---|
| no valid target | legal stationary/degraded（planner 返回 None） |
| invalid geometry | `_nearest_valid` / `SAFE_FALLBACK` |
| target disappears | 无用户窗口 → APPROACH 无目标 → 不动 |
| screen removed | `current_screen_for_point` 回主屏 |
| frame changes mid-movement | 重规划（高优先打断）或 pending |
| missing walk asset | DEGRADED_WALK_VISUAL（移动继续，不卡空间层） |
| AnimationRuntime temporarily unavailable | spatial 独立推进，不阻塞 |

不 crash：`test_spatial_long_run_health` + 失败用例。

---

## 27. 50k Spatial Long-run

`scripts/spatial_validation.py` → `50k PASS`：

```
ticks:            50000
plans:            2650
starts/arrivals:  推进正常
out_of_bounds:    0
stuck:            0
duplicate_arrival:0
overshoots:       0
moving_share:     36.2% (< 40%)
```

---

## 28. Performance

- Idle CPU：not measured（本轮只做程序化正确性；性能采集另留）。
- Moving CPU：not measured。
- RAM：not measured。
- Spatial tick：纯 Python 数值推进，单 tick O(1)。
- GUI timer：16ms 定时器（30 FPS 运动时钟；§119）。
- Position updates/sec：与 QTimer 16ms 同步（≈60/s）。

> 说明：不因追某个指标做大改（§118 主要检查无 runaway）。headless 50k run CPU 用时正常。

---

## 29. Regression

```
Previous: 307
New:      42
Total:    349
Broken:   0
```

Backend RC1 未解冻；框架 schema v1.0 未变；anti-collapse OFF 未变；LLM 未新增。

---

## 30. Manual Visual Check

```
Status:  MANUAL_VISUAL_PENDING
```

命令：

```
python scripts/manual_gui_phase12.py
```

Checklist（**Agent 未获得视觉能力，不得自行勾选**）：

```
[ ] 无闪屏
[ ] 无尺寸跳变
[ ] 无滑行（自主移动时确实在走）
[ ] 无原地走路（停了就不走）
[ ] 左右方向/翻转正确
[ ] 起步自然（无瞬移）
[ ] 到达自然
[ ] Approach 不遮挡目标中心
[ ] Withdraw 明显远离
[ ] Wander 有停留（不像巡逻）
[ ] Sleep 不移动
[ ] Wake 后正常
[ ] Drag 不抢控制
[ ] Release 不 snap-back
[ ] 屏幕边缘不裁角色/气泡
```

> 注意：当前 manifest 无 walk 动画序列 → 移动时视觉为 DEGRADED_WALK_VISUAL
> （移动距离真实发生，但"走路画面"需真实 asset 才能完整呈现；此项列入 Weaknesses）。

---

## 31. Weaknesses

| 类型 | 问题 | 证据 | 阻塞 Technical PASS? |
|---|---|---|---|
| STRUCTURAL | manifest 无 walk sequence → 移动阶段始终 DEGRADED_WALK_VISUAL，无真实 walk 帧 | `data/assets/manifest.json` 仅 10 个 sequence（6 transition + 4 loop），无 walk | 不阻塞（§116 规定退化路径）；但视觉完整性需后续 asset |
| PARAMETER | speed_px / arrival_radius / near_radius / far_radius / grace 为判断值，未人校 | `SpatialConfig` 默认值 | 不阻塞（可调）；视觉效果由人工反馈校对 |
| GUI | offscreen 用 1920x1080 单屏；真实桌面 DPI / 多屏 / 任务栏位置未在 GUI 真跑 | Step 0 用 offscreen + 模拟窗口几何 | 不阻塞（§96 允许模拟几何）；由人工 visual check 覆盖 |
| VISUAL-MANUAL | 人工视觉结果 = PENDING | §30 | 不阻塞 Technical PASS；但 Blocking 整体 = 用户勾选 |
| FUTURE | Phase 13 用户互动回程未做 | 范围外 | 不阻塞 Phase 12 |

---

## 32. Verdict

**Technical: PASS**。**Manual: PENDING**。**Overall: PASS-AUTO / MANUAL_VISUAL_PENDING**。
（≤5 句）程序化管线（GUI 链 + 空间层 + 所有权迁移 + 50k health）全部通过；后端 RC1 未动、schema 未变、0 新增 LLM。唯一需要人工确认的是"视觉自不自然"——它不在 Agent 可验证范围内。鉴于此，整体只记 `PASS-AUTO / MANUAL_VISUAL_PENDING`，等用户跑 `manual_gui_phase12.py` 后升为完整 PASS 或 PARTIAL。

---

## 33. Recommended Next Step

Technical PASS → **Phase 13 — User Interaction Integration**。
但若 Manual Visual FAIL，先等用户反馈的具体视觉问题做 **Phase 12 Visual Closeout**，
不要自行开始 Phase 13。也不要询问泛泛的"是否继续"。
