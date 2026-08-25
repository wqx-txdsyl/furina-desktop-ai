# Phase 13 FINAL Functional Truth Closeout — 诚实进度报告（PARTIAL）

**评审基线**：commit `2d0da7fb7a34e938f2a064807b8a1f62bec22d2e`（C-R2 hotfix，452 测试）
**本关状态**：**未完成（PARTIAL）**。以下内容按「复现 → 根因 → 修复 → 确定性证据 → 回归」逐条展开；
**未声称 READY_FOR_REVIEW / PASS / Persona PASS / Manual PASS / Phase 14 就绪**。

> 测试数量只是回归基线，不是证据。本报告的证据是：真实运行时复现、真实源码路径、真实确定性探针输出。

---

## 1. 已完成并验证的 P0（本轮真实修复，全部有行为/源码测试）

### 1.1 §2.1 世界时钟（year, month → hour, minute）

**复现（真实运行）**：

```
time.localtime()[:2] 旧bug => (2026, 8)   ← (year, month)，不是 (hour, minute)
tm_hour, tm_min       => (11, 0)
```

**根因**：生产 `Scheduler` 调用 `self.se.update_clock(*time.localtime()[:2])`，把 `(year, month)` 当成 `(hour, minute)`，
导致 `clock_hour ≈ 2026`，污染昼夜、睡眠/休息与 World 语义。

**修复**（`furina/runtime/scheduler.py:328-330`）：

```python
lt = time.localtime()
self.se.update_clock(lt.tm_hour, lt.tm_min)
```

**确定性证据**：

```
day_period: {8: 'morning', 13: 'afternoon', 20: 'evening', 0: 'night'}   # 00:30 → night
```

**测试**：`test_scheduler_clock_uses_hour_minute`、`test_world_day_period_known_times`。

---

### 1.2 §4.5 情绪所有权（LifeDecision 不得覆盖 EmotionEngine 的 label）

**复现（源码路径）**：`app._on_execute()` 原代码

```python
payload = getattr(req, "payload", {}) or {}
if payload.get("emotion"):
    st.emotion.label = payload["emotion"]   # ← LifeBrain 决策直接覆盖权威情绪
```

**根因**：一次真实的拒绝已产生 embarrassed/sad，随后 LifeBrain 的 `read + calm` 决策可把它擦掉 —— 违反「EmotionEngine 拥有情绪真相」。

**修复**（`furina/app.py`）：LifeDecision 的 `emotion` 降级为**非权威表达/行为提示**，落到 `Intent.emotion`（结构化输出槽），不再写 `EmotionState.label`。

**确定性证据**：`test_life_decision_does_not_write_emotion_truth` —— 传入 `payload={"emotion": "happy"}` 的 `ActionRequest`，
执行后 `state.emotion.label == "calm"`（权威值未被覆盖），`state.intent.emotion == "happy"`（提示槽落位）。

---

### 1.3 §5 强制多样 = 关（行为评分不再有多样性惩罚）

**复现（源码路径）**：`furina/behavior/motivation.py` 打分链原含

```text
base *= self._observation_crush_guard(activity)   # 观察占比 >50% → 类别 ×0.4 / 其他 ×1.4
base *= self._category_penalty(activity)          # 同类反复 → 重罚
base *= self._activity_penalty(activity)          # 同活动反复 → 重罚
```

**根因**：纯「展示过太多」就改排序 = 人工多样性，违反 §0 第 8 条。另外 Scheduler 曾有 `idle_streak / autonomy_stagnation` 短时唤醒路径。

**修复**：三个机制注释禁用（`motivation.py:606-608`）；唯一保留的显式时间项是 30/90s **语义冷却**
（活动本身，非视觉多样，`motivation.py:614`）；`_monitor_kpi` 只留日志，不再 `_interrupt_life("autonomy_stagnation")`（全文件已无该串）。

**测试**：`test_forced_diversity_production_calls_zero`、`test_no_autonomy_stagnation_interrupt_for_quiet_idle`。

---

### 1.4 §7 指针控制阶段 ≠ 有意义互动（真实输入因果恰好一次）

**复现（真实指针序列）**：`mouse down → GRAB`、`mouse release → CLICK/DRAG/POKE`，但 `INTERACTION_INPUT` 全部被
Scheduler 当作正面互动消费（扣社交、加接纳度、可记忆、可打断）；App 情绪映射还把未知 kind 默认成 `EVENT_CLICK`。

**修复**：
- `scheduler._on_interaction` 顶部门控：`grab/release/hover/leave/approach/double_click` 直接 return（`scheduler.py:245-250`），不进生命因果；
- `app.py:91-96` 情绪映射 `emotion_event.get(getattr(ev.payload.type, "value", ""), None)` —— 未知 kind → `None`（无事件），不再默认 `EVENT_CLICK`。

**测试**：`test_grab_release_hover_leave_are_not_positive_interaction`（四种指针阶段台词为空）、
`test_unknown_interaction_not_mapped_to_click`（源码断言 None 分支）。

---

### 1.5 §13 记忆关系偏置的单位债（raw principal → canonical 0..1）

**复现（真实探针）**：`memory_engine.behavior_hint()` 读 `RelationshipState.comfort`（raw 0..100）却按 0..1 阈值比较：
`raw comfort=1 → approach_bonus`、`raw annoyance=1 → social_penalty=70`。

**修复**（`furina/memory/memory_engine.py`）：统一消费 canonical `relationship_factors()`，阈值保持 0.6（0..1）。

**确定性证据（真实探针输出）**：

```
raw comfort=1  annoyance=1  -> factors comfort=0.010 annoyance=0.010   # 不再误触发
raw comfort=90 annoyance=90 -> factors comfort=0.900 annoyance=0.900   # 正确触发
```

**测试**：`test_memory_behavior_hint_canonical_units`（含旧 bug 复现点：raw=1 不得触发）。

---

## 2. 回归

| 基线 | 本关 |
|---|---|
| 452 passed / 0 failed（C-R2 hotfix） | **460 passed / 0 failed**（+8 新增：test_phase13_final.py） |

- 旧测试无一删除；`test_closeout_r1.py::test_annoyance_07_triggers_06_path` 更新为断言 canonical 形式
  （`f.get("annoyance", 0.0) > 0.6` 且 `rel.annoyance > 0.6` 不得出现），因为原断言编码的是已被 §13 修复取代的旧实现。
- 涉及变更：`furina/app.py`、`furina/behavior/motivation.py`、`furina/memory/memory_engine.py`、`furina/runtime/scheduler.py`、`tests/test_phase13_final.py`（新增）、`tests/test_closeout_r1.py`（断言更新）。

---

## 3. 未完成（诚实列出，不掩饰）

以下 P0/P1 本轮**未实现**，故本关整体为 PARTIAL：

| 项 | 内容 | 为什么没做 |
|---|---|---|
| §2.2/2.3/2.4/2.5 | 真实 `GetLastInputInfo` 空闲秒；`user_working` 来自 World 而非上一帧自喂；前台进程可执行文件与窗口类分离（`Chrome_WidgetWin_1` 假 office 匹配）；稳定性阈值真正生效 | 需要一个真实 Windows 感知边界（ctypes/Win32 探针），属于独立较大改动，本回合预算不允许半吊子实现 |
| §3 | Needs 按 分钟/小时 级产品时间常数 + 30m/2h/4h/8h 曲线 | 需要重定全部被动速率与曲线文档，且与现有 dt 逻辑联动，不能只除一个数 |
| §4.1-4.4 | 基线-相对的情绪派生（默认→calm、praise→proud/happy、reject→embarrassed/sad、poke→annoyed、return→happy）；分钟级衰减；语义事件恰好一次接线 | 情绪派生重写是最大块之一；本轮只完成了 §4.5 所有权这一小块 |
| §6 | Activity 生命周期 COMPLETED/INTERRUPTED/FAILED/ABORTED + 实例 id + 结局不可变 + 关系不可自我农场 + social_need 恰好一次 | 影响调度器/Outcome/关系三层，需整组契约测试 |
| §8 | Dialogue FIFO 串行 + 运行时单 apply 线程（dialogue 竞态 user1/user2/reply2/reply1） | 线程/排队边界，属架构级改动 |
| §9 | Validator 强制执行（invalid 不得原样显示、一次重生成 + 有界恢复、"你能别烦我吗？"→DECLINE） | 中等改动 |
| §10 | Agent 真相性（计算器→calc、任务局部上下文、verified=False 不得 COMPLETED、启动可观察验证、Director 走 agent 源、摘要含已验证事实、launch 至少 L1_LOW_WRITE） | 涉及 planner/runtime/permission/工具多文件 |
| §11 | Feed 生产路径（GUI 与 Harness 同一提交路径、不阻塞 Qt、效果恰好一次） | 需 GUI 线程边界配合 §8 |
| §12 | wander/explore 平滑（无 >~45° 突转） | 需在 spatial planner 增加 Catmull-Rom 到所有路径 + 轨迹采样证据 |
| §14 | Harness 真值徽章（AVAILABLE/LAST_OK/LAST_FAILED/FALLBACK、Agent COMPLETED_VERIFIED/UNVERIFIED、Memory COUNT=n、诊断字段） | 中等改动 |

**未决风险**（诚实说明）：§4 派生/衰减未动，意味着即便所有权正确，默认派生仍可能偏离 calm、事件情绪仍可能快速衰减 —— 该 P0 在 Manual 前必须完成。

---

## 4. 真实 GLM / Persona 证据

**本轮未产生。** 会话内没有可用的生产 GLM-4v-flash 直连端点（未配置、无法发起真实 13 场景转录），
因此 Persona 证据缺失，**Persona = NOT REVIEWED**。任何自动化测试均不能自称 Persona PASS。

---

## 5. STOP

### 最终判定（Agent 声明的诚实状态）

```text
Technical      = PARTIAL（NOT READY_FOR_REVIEW —— 已完成 5 组 P0 修复并有真实证据，§2.2-2.5/§3/§4.1-4.4/§6/§8/§9/§10/§11/§12/§14 未完成）
Real Runtime Evidence = PROVIDED（上述 5 组的复现 + 真实探针输出；其余项无证据）
Persona        = NOT REVIEWED（无 GLM 转录）
Manual         = NOT YET REVIEWED
Overall        = IN PROGRESS / PARTIAL —— 继续完成剩余 P0 后重新提交终审
```

**未写**：Phase 13 PASS / Persona PASS / Manual PASS / Ready for Phase 14。

**下一步（评审确认后）**：继续实现 §4 情绪派生+衰减、§6 Activity 生命周期、§2.2-2.5 Windows 感知边界等剩余 P0，
每项带复现证据与测试，全部完成后才允许 Technical = READY_FOR_REVIEW。
