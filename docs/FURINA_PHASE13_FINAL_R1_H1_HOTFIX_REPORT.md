# Furina Desktop AI — Phase 13 FINAL-R1-H1 Hard-Blocker Hotfix 报告

**Review baseline:** `880805f300acb37102b7b0545e95f8581407c2f2`（581 tests，FINAL-R1 评审 = PARTIAL）
**证据规则**：每个 H1 blocker 先复现（BEFORE）→ 根因 → 生产修复 → 确定性证明（AFTER）；用事件/屏障/可控时钟/线程 ID/调用计数/bounded join。

---

## 2. Windows idle 真相（H1-P0）

### 2.1 `None` 被转回假的 `0.0`

- **BEFORE（复现）**：`_active_window_windows()` 里 `idle=_get_idle_seconds() or 0.0` —— API 失败 → None → `0.0` → `idle_available=True` → 运行时以为"用户刚互动"。
- **根因**：`or 0.0` 把"未知"伪装成"活跃"。
- **修复**：`idle=_get_idle_seconds()`（保留 None）；`WindowAwareness` 区分 `idle_available=False / last_idle=上一有效值或 None`；Scheduler 在不可用时保留上一有效值。
- **AFTER（确定性）**：
  ```
  mock _get_idle_seconds→None + 完整窗口 fake → _active_window_windows().idle is None
  poll 收到 None → idle_available=False, last_idle=None（test_idle_failure_poll_keeps_idle_unavailable）
  ```

### 2.2 32 位 dwTime 与 64 位 GetTickCount64 裸减不安全

- **BEFORE**：`idle = now64 - last32` —— 长 uptime 时 now64 高位非 0 → 巨大假空闲。
- **修复**：`now32 = now64 & 0xFFFFFFFF; elapsed_ms = (now32 - last32) & 0xFFFFFFFF`（mod 2^32 回绕正确）。
- **AFTER（确定性）**：
  ```
  wrap 跨 0xFFFFFFFF→0：_idle_from_ticks(0xFFFFFF00, 0x00000100) == 0.512s
  长 uptime（now64=0x1_00000000+30000）→ idle == 10.0s（不巨大）
  ```

## 3. World 语义事件必须按"事件实例"消费（H1-P0）

- **BEFORE**：Scheduler 用 `"WORK_STARTED" in recent_world_events`（历史串）+ 时间戳去重；旧串残留 21s 后可再次消费 → 违反恰好一次。
- **根因**：`recent_world_events` 是历史存储，不是"本次 update 发出的事件"。
- **修复**：`WorldPerception.last_events`（每次 `update()` 新发出的事件实例列表，全局单调 `_event_seq` 诊断）；Scheduler 按实例计数消费（`last_events.count(ev_key)`），绝不从历史串推断；World 内置 20s debounce + 30s 稳定性。**可控时钟**注入（`now_fn`）供测试跨 debounce 边界。
- **AFTER（确定性，可控时钟）**：
  ```
  browse→coding 稳定 → user_work_start==1；继续 coding 120s → 仍 1（历史残留不重触发）
  browse→coding→browse→coding → user_work_start==2（第二次真实转换才第二个）
  手动塞旧串进 recent_world_events（last_events 空）→ 不触发
  ```

## 12. Runtime owner 显式绑定（H1-P1）

- **BEFORE**：`require_owner` 首个调用者自绑定 —— worker 可能先成为 owner。
- **修复**：`bind_owner(thread_id=None)` 启动时（`launch()` 在 Qt/runtime 线程）显式绑定；`submit()` 绝不建立 owner；未绑定前 `require_owner` 报错（不自绑定）。
- **AFTER**：`bind_owner()` 后 owner==绑定线程；worker `require_owner` 抛错；`submit` 后 owner 仍 None；未绑定 worker 调用 → "before runtime owner was bound"。

## 5. Dialogue FIFO 锁反转（H1-P0）

- **BEFORE（复现）**：turn2 抢到 `_say_lock` 后等 turn1 槽位，而 turn1 等不到锁 → 死锁。旧测试绕过 `say()` 直调 `_push_ordered`，测不到该竞态。
- **根因**：生成锁先于 turn 顺序保证。
- **修复**：**turn FIFO 门（ticket/Condition）在生成锁之前**：`_gate_wait(seq)` 等到前序 turn 完成才进入 `_say_lock`；`finally` 中 `_gate_release(seq)`（失败/沉默也推进）。
- **AFTER（确定性，bounded join）**：
  ```
  turn2 先到门（_gate_wait(2)）→ turn1 完整 say → turn2 被放行，两线程 5s 内退出（无死锁）
  并发 say（turn1 慢 150ms）→ LLM 调用序 [1,2]，history = user1/furina1/user2/furina2
  turn1 失败/沉默 → turn2 正常出话（FIFO 推进）
  ```

## 6. 直接历史原子成对提交（H1-P0）

- **BEFORE**：直接回合先提交 user 槽再做模型/校验 —— 生成失败/双重校验失败/输出门抑制 → 孤儿 "User: ..." 无 Furina 回复。
- **修复**：`_pending_direct_user` 暂存；**只有存在可显示回复**才原子成对提交（user→furina）；失败/沉默回合的槽位由 `say()` finally 跳过。
- **AFTER**：模型失败/双重校验失败 → history 空；valid → `[user, furina]`；`valid→invalid→valid→silent→valid` → 偶数成对、严格 user/furina。

## 7. 社交响应窗口只在可见执行时开启（H1-P0）

- **BEFORE**：`_apply_life_decision` 在决策提交时就 `begin_social_bid` —— 被阻塞的 talk 也开窗口 → 60s 后假 USER_IGNORE。
- **修复**：bid 只在**可见执行**开启：`approach_user`（走过去可见）在 `on_mind_action_started` 开；其它社交类在**可见台词成功出话**后由 ambient worker 经 dispatcher（owner）提交；被阻塞决策/无效台词/缺席不开。
- **AFTER**：阻塞社交决策 → 无 bid；未执行 talk → 无 ignore；talk 无可见台词 → 无 bid；approach_user 执行 → 一个窗口；用户回应取消 → 0 ignore。

## 8. Activity 实例在实际抢占时立即 finalize（H1-P0）

- **BEFORE**：生产无抢占 finalize；测试手动注入 `pending_finish="aborted"`；Agent/用户接管后 mind 实例仍 RUNNING，后续 Life 决策可能把接管后的时间算作 mind 时间。
- **修复**：`Director.on_before_replace(old, new)` 实际替换回调 → `app._on_director_replace` → `sched.on_mind_preempted(reason)`：elapsed 停在接管时刻、progress 当时计算、status=INTERRUPTED/ABORTED、部分奖励（success=False + progress 感知）恰好一次；后续 Life 结算跳过（实例非 RUNNING）。
- **AFTER（生产路径：真实 Director + ActionRequest 驱动）**：
  ```
  mind 执行 → agent 接管 → finish_reason=preempted_by_agent，elapsed 冻结（sleep 后不变）
  后续 Life 决策换活动 → 不被算成 completed（finish_reason 仍 preempted_by_agent）
  再来 agent 请求 → 不重复结算
  failed/aborted（progress<1）恢复量 < completed（scale<1）
  ```

## 9. 定型互动顺序（H1-P0）

- **BEFORE**：`InteractionEngine._apply` 先 `bus.emit(INTERACTION_INPUT)`（Scheduler 同步起对话 worker）再 `on_meaningful_interaction`（关系）—— 对话可能看到旧关系。
- **修复**：`_apply` 顺序：**on_emotion_semantic（Emotion）→ on_meaningful_interaction（Relationship+Memory）→ 广播 INTERACTION_INPUT（Needs/Life + 冻结快照 + worker）**；drag 补关系事件（EV_POSITIVE_TOUCH）。
- **AFTER（真实 emit_event）**：petting → EV_POSITIVE_TOUCH 恰好一次 + label 立即 "happy"；poke → EV_NEGATIVE_RESPONSE；drag → EV_POSITIVE_TOUCH；广播返回后情绪已派生、关系已应用。

## 10. DialogueContextSnapshot（H1-P0）

- **BEFORE**：`_brain_worker` 等 worker 在运行时读 live 可变状态（关系/情绪/活动/idle/world/记忆）。
- **修复**：新增 `furina/runtime/dialogue_snapshot.py`（frozen dataclass，只存事实副本）；owner 冻结后传给 worker：
  - 直接对话：`submit_user_message` → `_freeze_direct_snapshot`（owner）→ worker
  - 喂食：`_freeze_feed_snapshot`（owner）→ worker
  - 互动/Agent：`Scheduler._freeze_reaction_snapshot`（owner）→ worker
  - 自主：`Scheduler._freeze_ambient_snapshot`（owner）→ worker
- **AFTER**：冻结后改 live 状态（label→sleepy、relationship→0.99、activity→sleep）→ 快照仍保留冻结值（5 通道测试）。

## 11. Feed 域效果先于 dialogue worker（H1-P0）

- **BEFORE**：`_feed` 在 memory.observe / life.activity / macro / interrupt 之前就启动 `_feed_dialogue`。
- **修复**：owner 顺序：食物效应 → 情绪 apply+derive → 记忆 → life/activity/intent → interrupt → 取消 social bid → **冻结快照** → 再启动 worker。
- **AFTER**：barrier 测试证明 order 中 memory/interrupt/cancel_bid 全部先于 dialogue_started；worker 收到 post-feed activity="eat"。

## 4. Owner 线程剩余直写（H1-P0）

### 4.1 Agent 成功后的记忆写入
- **BEFORE**：`_agent_worker` 在 worker 直调 `memory.observe`。
- **修复**：经 `_rt_dispatcher().submit(...)` 回 owner 执行。
- **AFTER（thread-id）**：worker 完成后 drain 前 `seen=={}`；drain 后 memory.observe 的线程 == owner_thread_id。

### 4.2 自主 Life Dialogue 的 LLM 移出 owner
- **BEFORE**：`_apply_life_decision` 在 owner tick 上同步 `dialogue_brain.say()`。
- **修复**：owner 冻结快照 → worker say → 结果经 dispatcher 回 owner 应用（`_say`/`_llm_speech_at`）。
- **AFTER（thread-id）**：say 调用线程 != owner；慢 LLM（0.3s）下 `_apply_life_decision` 返回 <0.15s（不阻塞 owner）；drain 前 `_speech==""`，drain 后落地。

## 回归

| 基线（880805f） | 本 hotfix |
|---|---|
| 581 passed / 0 failed | **622 passed / 0 failed**（+41：test_phase13_h1/h1b） |

替换/更新的旧测试：`test_windows_idle_nonzero_sample_exact`（wrap 语义）、`test_phase13_final.py::test_unknown_interaction_not_mapped_to_click`（方法重构后守卫更新）、`test_phase13c.py::test_raw_relationship_not_passed_to_normalized_consumer`（快照冻结后守卫更新）、`test_phase13_final4.py::test_activity_instance_starts_on_director_execution`（owner 显式绑定）。其余 581 全绿未动。

## 剩余 Manual-only（诚实声明）

1. 真实 Windows 前台采样 / tasklist / GetLastInputInfo 真机输出。
2. 真实 glm-4v-flash 13 场景转录 + 盲评（**Persona = NOT REVIEWED**）。
3. Qt/Windows 响应性与真实 GUI 交互（快照/worker 重构后的真机手感）。
4. 真实 app.launch 可观察验证（测试用 mock）。
5. 空间自然度主观观感（机械验证 <45° 已冻结，主观属 Manual）。

## STOP

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

未声称任何 PASS。评审只复核本文件 H1 不变量；通过则 PHASE 13 TECHNICAL = PASS → Manual Experience Acceptance（非 Phase 14）。
