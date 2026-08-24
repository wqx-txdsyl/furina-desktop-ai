# SPATIAL RUNTIME — 桌面空间生命层（Phase 12）

本文件记录空间层的**坐标 / 锚点 / 屏幕 / 所有权 / 移动生命周期**。设计目标：
空间层是"她去哪、怎么走、什么时候到"的唯一 owner；它**只消费** `CharacterRuntimeFrame`
空间语义（motion / body / activity / world_hint），**不读** Needs / Emotion / Relationship /
Memory / Identity（RC1 契约）。

---

## 1. 所有权（Ownership）

```text
LifeBrain:            WHY / WHAT      （为什么移动、当前活动——冻结后端）
Embodiment:           HOW SHE FEELS   （靠近意愿/速度感/犹豫感——冻结后端）
Spatial Runtime:      WHERE / HOW     （去哪、怎么走、什么时候到）  ← 本期实现，唯一自主移动 owner
Animation Runtime:    HOW IT LOOKS    （walk / transition / idle 视觉）
FurinaWindow:         只画（paint / geometry / hitbox / manual drag / position adapter）
```

**Spatial Runtime 绝不决定**：她是不是想接近用户、是否孤独、是否该陪用户、是否该休息。
这些属于冻结后端。

**Scheduler 已不拥有像素空间**：移除 `_move_target / _walk_visible / _move_step /
_maybe_walk_to_window` 生产路径；仅 deprecated no-op 兼容（生产调用计数 = 0）。
Scheduler 不再调用 `window.set_position()`，也不再把 `life.macro` 改成 RESTING（到达 ≠ 决定休息）。

---

## 2. 坐标模型（Coordinate Model）

三种坐标，语义不同：

| 名称 | 含义 |
|---|---|
| Screen coordinate | Qt logical pixel 虚拟桌面；原点 = 主屏左上，+x 右 / +y 下 |
| Window coordinate（pos） | `FurinaWindow.set_position(x, y)` 的 `(x, y)`；窗口左上角 = `(x - side, y - top)` |
| Character anchor（foot） | 角色**脚底中点**（center-x, foot-y）在 screen 上的点；本层空间逻辑的位置真相 |

**为什么用 foot anchor 而非"角色左上角"**：standing / sitting / lying 的画布宽高不同，
"角色左上角"随姿态漂移；而脚底锚点在 bottom-center 稳定。

### 2.1 Adapter（Pos ↔ foot）

`PositionAdapter`（`furina/runtime/spatial/runtime.py`）：

```python
# 窗口水平居中角色：char center-x = pos.x - side + window_w/2
# 无气泡下移时：char on-screen top = pos.y ；脚底 = pos.y + char_h
foot_to_pos(fx, fy) = (fx - window_w/2 + side, fy - char_h)
pos_to_foot(x, y)    = (x + window_w/2 - side, y + char_h)
```

`PositionAdapter.from_window(win)` 从真实 `FurinaWindow` 读取 `_char_w / _char_h / _side / _top / width()`；
headless 测试用 duck-typed FakeWindow 提供同样字段。

---

## 3. 屏幕（Screen）语义

- `DesktopWorld` 维护 `screens: list[Rect]`（多屏基础支持）。
- `current_screen_for_point(x, y)` / `screen_index_for_point(x, y)`：定位所在屏；不在任何屏 → 主屏。
- `available_bounds(screen)`：可用矩形 = 该屏去掉 `safe_margin`（2×）+ `taskbar_height`。
- `safe_zone(char_w, char_h, screen)`：角色左上角可安全放置区（再扣角色自身尺寸）。
- `is_valid_position / nearest_safe_point`：几何合法性与就近修复。
- `window_edge_candidates(char_w, char_h)`：活动窗口附近安全候选（bottom-edge / outside-left / outside-right）。

多屏规则：若角色被拖到第二屏，之后自主移动**留在当前屏**，不跨屏追用户（目标不可得 → maintain /
safe fallback）。

---

## 4. 模块

```
furina/runtime/spatial/
├── __init__.py
├── model.py      枚举 / SpatialState / MovementPlan / SpatialConfig / ResolvedIntent
├── resolver.py   SpatialIntentResolver：Frame → ResolvedIntent（语义解释）
├── planner.py    SpatialPlanner：ResolvedIntent + 位置 + 几何 → MovementPlan（语义目标→坐标）
└── runtime.py    DesktopSpatialRuntime（状态机 + dt 移动）+ PositionAdapter
```

数据流：

```
CharacterRuntimeFrame
  → SpatialIntentResolver.resolve(frame)        # motion.intent > body.proximity > activity 回退
  → SpatialPlanner.plan(decision, pos, cw, ch)  # MAINTAIN/NONE→None; APPROACH/WITHDRAW/NEAR/FAR→plan
  → DesktopSpatialRuntime.accept(decision, now) # 打断/优先/pending
  → DesktopSpatialRuntime.tick(now)             # 移动 / 到达 / 事件 exactly-once
  → AnimationRuntime.set_movement(moving, facing) # walk 视觉 / DEGRADED
  → PositionAdapter.foot_to_pos → FurinaWindow.set_position()
```

---

## 5. 移动生命周期（Movement Lifecycle）

```
IDLE → PREPARING → STARTING → MOVING → ARRIVING → ARRIVED(停留/冷却) → (可再 IDLE/重规划)
                                   │                     ↑
                                   └── 高优先/拖拽打断 ──────┘
DRAGGED（拖拽中，位置由鼠标接管；release 提交并进入 grace）
```

- 速度：`speed_px_sec`（px/s）**× dt**（§46，禁 3px/frame 常数步长）。
- 加速度：ease-in（起步 +`ease_in_accel·dt`）/ cruise / ease-out（接近目标减速）。
- 到达：`arrival_radius`（禁 `distance == 0`）；每步 `step=min(speed·dt, remaining)`（防过头）。
- 事件 exactly-once：`SPATIAL_TARGET_REACHED` 按目标 latch；`MOVEMENT_STARTED`/`MOVEMENT_INTERRUPTED` 各一次。

---

## 6. 空间意图（Intent）

| Intent | 语义 |
|---|---|
| APPROACH | 走用户附近安全区（非窗口中心） |
| WITHDRAW | 增加与用户距离（去更远安全区） |
| MAINTAIN | 保持；位置非法才 REPOSITION |
| NEAR / FAR | 距离偏好（hysteresis：已近/已远则保持） |
| REPOSITION | 小幅安全修正 |
| NONE | 默认不自主移动；仅活动明确允许才踱步 |

**随机性只用于"多个等价目标"**（§34），绝不决定"是否移动/是否靠近/是否远离"（那来自 Frame）。

---

## 7. 与 Walk 视觉的联动

- 移动 → `movement_visual().moving=True` → `AnimationRuntime.set_movement(True, facing)`。
- 未移动 → `set_movement(False)`。
- 缺 walk 素材 → `DEGRADED_WALK_VISUAL`（移动继续；不强行走 idle 造成"逻辑误判"）。
- 关键 transition（sit_down/stand_up/go_sleep/wake_up...）优先，不被打断。

---

## 8. 不做什么（§78/§79/§128-§131）

- 无 A* / NavMesh / 图标碰撞 / 窗户物理；普通 app window 不当实体墙。
- 无重力 / 跳跃 / 下落 / 碰撞物理。
- 无鼠标追逐、无跨屏 chase、无 Window 自动操控（只操作 FurinaWindow）。
- 到站不自动说话、不改关系、不写记忆、不写情绪（Speech/关系由后端经 Frame 表达）。
