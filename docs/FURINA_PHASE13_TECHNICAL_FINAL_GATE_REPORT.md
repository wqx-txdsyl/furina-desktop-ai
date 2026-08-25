# Furina Desktop AI — Phase 13 Technical Final Gate Patch 报告

**Review baseline:** `4a5767a090fd54d771c56768bad14e604b4aac02`（657 tests）
**范围**：仅修复评审确认的两个残余 blocker —— §1 Director 优先级仲裁（FAIL）、§2 idle 初始真相（FAIL）。
其余六项（§1 情绪唯一 owner / §2 owner-ingress FIFO / §4 用户抢占 / §5 规范 status / §6 统一 owner 绑定 / §8 单一记忆）为 FROZEN，未触碰。

---

## §1 P0 — Director 允许低优先级 mind 替换 active Agent

### BEFORE（复现）

`Director.drain()` 只在 `current.interruptible is False` 时挡请求：

```python
if self._current and req.priority >= self._current.priority and self._current.interruptible is False:
    requeue(req); return
# 否则替换
```

因此：`current=Agent(priority=2, interruptible=True 默认)` + 队列 `mind(priority=3)` → drain 时 mind 替换 Agent —— 违反优先级层级（数字越小越高）。

### 为什么旧 657-green 测试是 false-green

`test_active_agent_blocks_lower_priority_mind_across_real_drains` 旧版（§3 集成）提交 mind 后**从不调用 `director.drain()`** —— `say_calls==0` 只证明"未 drain 的排队请求没执行"，没证明"active Agent 挡住低优先级 mind"（生产每 medium tick 都 drain，bug 可达）。

### 生产修复（`furina/director/director.py`）

```python
if self._current is not None:
    if req.priority > self._current.priority:            # 严格更低 → 永不替换（与 interruptible 无关）
        requeue(req); return
    if req.priority == self._current.priority and self._current.interruptible is False:
        requeue(req); return
    # req.priority < current.priority → 更高优先级可抢占（既有策略）
```

优先级常量未改；未把 Agent 设成 non-interruptible 来掩盖。

### AFTER（确定性）

- **直接 Director 契约**：
  ```
  Agent(2, interruptible=True) current → 入队 mind(3) → drain×5 → current==agent、"read" 0 次执行、mind 仍排队
  mind(3) current → Agent(2) → drain → current==agent，on_before_replace 恰好一次 [("mind","agent")]
  同优先级同源 Agent：planning→work→report（priority 2 全 interruptible）→ 三阶段全部执行（不冻结）
  ```
- **生产集成（真实 Director + Scheduler + 生产等价 executor + 成功 fake DB，Agent 活跃时多次 drain）**：
  ```
  Agent current + mind(talk, speech_level=3) 入队 → drain×8（真实节奏）+ dispatcher.drain()
    → current==agent、say_calls==0、_pending_social_bid is None、_activity_instance is None
  director.finish(source="agent") → drain → mind 执行
    → current==mind、ActivityInstance RUNNING、say_calls==1、drain 后 social bid 可开
  ```

## §2 P1 — idle_available 初始默认是假的 True

### BEFORE（真值错位）

```python
CharacterState:  user_idle_seconds=0.0, idle_available=True
WorldState:      user_idle_seconds=0.0, idle_available=True
Scheduler:       getattr(self.wa, "idle_available", True)
Harness 诊断:     getattr(st, "idle_available", True)
```

进程启动后、首个 GetLastInputInfo 之前：真值是"未测量"，运行时却宣称"可用 + 0.0"（与"用户刚互动"不可区分）。

### 修复

- `CharacterState.idle_available = False`、`WorldState.idle_available = False`（`user_idle_seconds=0.0` 只是存储占位）；
- Scheduler 回退 `getattr(self.wa, "idle_available", False)`；Harness 诊断回退 `getattr(st, "idle_available", False)`；
- `CharacterState.snapshot()` 在 `user_idle` 旁暴露 `idle_available`；`WorldState.to_dict()` 增加 `idle_available`；
- `WorldPerception.update(idle_available=False)` 且从未有有效样本：`user_activity=UNKNOWN`、**`user_active=False`**、`interaction_availability=0`、`last_events=[]`、不制造 USER_BECAME_ACTIVE/USER_RETURNED/USER_LEFT/WORK_STARTED-ENDED。

### AFTER（确定性）

```
CharacterState().idle_available is False；WorldPerception().state.idle_available is False
Scheduler 缺 wa.idle_available 属性 → _tick_medium 后 state.idle_available is False（保守回退）
Harness 缺该属性 → diagnostics["idle_available"] is False
snapshot() 含 "user_idle"+"idle_available"（False）；world.to_dict() 含 idle_available（False）
首样本不可用 → user_active is False、interaction_availability==0.0、last_events==[]
启动集成：start() 后 idle_available=False → 首次失败 poll 后仍 False → 有效样本后 True + 42.0
```

旧 H1 idle 测试保持全绿（首样本 UNKNOWN/零新事件、有效样本 True+精确值、有效后临时失败保留最后有效值但标当前不可用）。

## 回归

| 基线（4a5767a） | 本 patch |
|---|---|
| 657 passed / 0 failed | **672 passed / 0 failed**（+15：test_phase13_gate.py） |

冻结的六项未改动；旧 §3 集成测试被强化（补上真实 drain 节奏）。

## STOP

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

未声称任何 PASS。评审只复核 A（真实 drain 下高优先级 Agent 挡住低优先级 mind）与 B（idle 可用性在真实证据出现前为 False）；通过则 **PHASE 13 TECHNICAL = PASS / BACKEND FUNCTIONAL CONTRACT = FROZEN** → Manual Experience Acceptance（非 Phase 14）。
