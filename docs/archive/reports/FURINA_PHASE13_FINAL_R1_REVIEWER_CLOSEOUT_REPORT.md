# Furina Desktop AI — Phase 13 FINAL-R1 Reviewer Residual Closeout 报告

**Review baseline:** `9f5e44f34d02e94ca8034f20ea3f1738984bbd50`（530 tests，技术评审 = PARTIAL）
**本报告证据规则**：先展示评审缺陷复现 → 根因 → 生产修复 → 确定性证据 → 强化后的 false-green 测试 → 全量回归。不以测试数开头。

---

## 1. §1 Windows World 真相

### 1.1 GetTickCount 调错 DLL（User32 → Kernel32）

- **复现（源码路径）**：`_get_idle_seconds()` 里 `ticks = user32.GetTickCount()`；`GetTickCount` 属于 Kernel32。
  异常被全捕获返回 `None` → `idle=0.0`（假装用户一直活跃）。
- **根因**：错误 DLL + 失败被静默转成 0。
- **修复**（`furina/runtime/window_awareness.py`）：
  - `GetLastInputInfo`（User32）+ `GetTickCount64`（**Kernel32**，64 位无回绕）；
  - API 失败 → `None` / `WindowAwareness.idle_available=False`（**显式不可用**，不假装 0）；
  - Scheduler `_tick_medium`：空闲真相不可用时保留上一有效值，不覆盖为 0。
- **确定性证据**（API-mock，非源码串）：
  ```
  now=120000ms, last=90000ms → idle = 30.0s（_idle_from_ticks 纯函数）
  GetLastInputInfo 失败 → _get_idle_seconds() is None；poll 后 idle_available=False
  mock windll：kernel32.GetTickCount64 恰好 1 次，user32.GetTickCount 0 次
  ```

### 1.2 WorldPerception 每个 medium 采样被更新两次（class/process 互掐）

- **复现**：`wa.poll()` → ACTIVE_WINDOW_UPDATED → `_on_window` 里 `world_perc.update(app=CLASS)`；
  同一 `_tick_medium` 稍后又 `world_perc.update(app=CLASS, process=REAL)`。两次喂入使 30s 稳定性窗口的
  pending 候选每 tick 被重置（UNKNOWN↔CODING 抖动），browser→code 永远无法稳定提交。
- **根因**：`_on_window` 独立推进 WorldPerception，与 `_tick_medium` 双写。
- **修复**：`_on_window` **只缓存原始窗口事实**（`_last_info` + geometry），
  `_tick_medium` 每采样**恰好一次** `world_perc.update(...)`（class+process+idle+hour/minute 统一喂入）。
- **确定性证据**（真实 Scheduler 采样路径集成测试）：
  ```
  3 个 medium tick → world_perc.update 恰好 3 次（计数器）
  stable chrome → 切 Code（类名仍是 Chrome_WidgetWin_1）→ 14 tick → user_activity == CODING
  user_working == True；code → browser → BROWSING；idle 42.0s 来自 WindowAwareness
  ```

## 2. §2 情绪权威

### 2.1 `_on_brain()` 仍写 EmotionState.label

- **复现**：`self.se.state.emotion.label = getattr(out, "emotion", ...)`。
- **修复**：删除该写；BRAIN_SPOKE 的 emotion 只落 `Intent.emotion`（非权威表达槽）。
- **证据**：权威 label=embarrassed → emit BRAIN_SPOKE(happy) → drain → label 仍 embarrassed，`intent.emotion=="happy"`。

### 2.2 语义事件维度更新后 label 未立即派生

- **复现**：`EmotionEngine.apply(EVENT_PRAISE)` 只改维度，`derive_label` 要等下一 medium tick；
  生产路由随即用旧 label 喂 Dialogue。
- **修复**：新增唯一权威边界 `EmotionEngine.apply_event(event, tired_hint)`（apply + 立即派生，owner 线程），
  全部生产路由（praise/reject/talk/feed/poke/click/drag/agent_done/return/ignore/work-start/end）改走它。
- **顺带修复真实 bug**：sleepy 分数 `tired_hint*100*0.8` 让健康基线（0.15）也误判 sleepy → 改为
  `max(0, tired_hint-0.5)*100*0.9`（明显困倦 >0.5 才可能 sleepy）。
- **证据**：`apply_event(EVENT_PRAISE)` 后 label 立即 "proud"（无需 tick）；
  `test_feed_label_is_updated_before_feed_dialogue_snapshot` / `test_agent_done_...` 等 4 个 snapshot 测试全过。

### 2.3 WORK_STARTED/WORK_ENDED 未接线

- **修复**：`_tick_medium` 消费**稳定** World 事件（`_derive_events` 只从已提交类别产生，且有 20s debounce）
  → `EVENT_WORK_START/EVENT_WORK_END` 恰好一次（时间戳去重防 recent 列表重复消费）。
- **证据**：browser→coding 稳定后 `_recent["user_work_start"]==1`；继续稳定不重复；反向 `user_work_end==1`。

### 2.4 未映射事件进 `_recent` + 重复 EmotionEngine 类

- **复现**：`emotion.apply(None)` 污染 `_recent`；`emotion/engine.py` 有**两个** `class EmotionEngine`。
- **修复**：语义映射独立方法 `_on_interaction_emotion`（无映射直接 return，不调用 EmotionEngine）；删除死类。
- **证据**：grab/release/hover/leave/approach/double_click 后 `_recent` 不变；click 正常进入；
  `class EmotionEngine:` 计数 == 1。

## 3. §3 运行时 owner 线程契约

- **复现**：`_brain_worker`（worker）直接做文本语义/关系/情绪/记忆；`_agent_worker` 直写状态；
  `_on_agent_body` 在 worker 直改 Director 队列；Harness Feed 额外包 worker 线程（两路径线程 owner 不同）。
- **修复**：新增 `furina/runtime/dispatcher.py`（`RuntimeDispatcher`：`queue.SimpleQueue` + owner 绑定 +
  `require_owner` 违规守卫 + violations 记录）；Scheduler 的 apply 队列迁移到 dispatcher；
  生产入口 **`submit_user_message(text)` / `submit_feed(food)`**（owner 语义恰好一次 → worker LLM →
  dispatcher 回 owner 应用）；`_agent_worker` 状态写入与 `_on_agent_body` 的 Director.submit 经 dispatcher；
  Harness 不再包 worker 线程（直接调 submit_*，与 GUI 同 owner）。
- **证据**（thread-id 测试，非源码串）：
  ```
  worker 调 submit_user_message/submit_feed → RuntimeError + violations 记录
  praise 关系变更 / EVENT_TALK 情绪的 thread id == dispatcher.owner_thread_id
  _agent_worker 提交后 drain 前状态不变，drain 后 agent_planning
  _on_agent_body 后 drain 前 Director 队列空，drain 后 source=agent 请求入队
  ```

## 4. §4 对话显式 FIFO + 通道历史

### 4.1 RLock 不是 FIFO

- **修复**：入口 `_next_seq()` 分配递增 seq（取锁之前）；history 提交经 `_push_ordered`（Condition 严格按
  seq 排序，stale seq 幂等丢弃）；`say()` 的 `finally` 用 `_skip_slots` 推进本回合双槽（环境/沉默/失败回合
  不会让后续回合死锁等不存在的 seq）。
- **证据**：绕过锁直接 `_push_ordered(3,4)` 先提交、`(1,2)` 后提交 → 历史仍 `第一句/回复1/第二句/回复2`；
  两个并发 say（turn1 慢 200ms）→ 直接历史严格成对。

### 4.2 自主/喂食/Agent 台词混入直接历史

- **复现**：每次 `say()` 都 `push_history("furina", speech)`，自主/喂食/Agent 台词成为孤儿 Furina 回合。
- **修复**：通道语义 `DIRECT_USER_TURN / AMBIENT_AUTONOMOUS / FEED_REACTION / AGENT_REPORT /
  INTERACTION_REACTION`；只有 DIRECT 进 `_history`，其余进 `_ambient` 池（近期上下文事实）。
- **证据**：AMBIENT/FEED/AGENT 台词后 `_history==[]` 且 `_ambient` 有对应 channel；
  直接回合穿插环境台词后历史仍 4 条成对连贯。

## 5. §5 Activity 生命周期从 Director 实际执行开始

- **复现**：LifeDecision 提交即创建实例/`mark_done`/计时；被更高优先级阻塞的 mind 请求从未执行，
  后续决策却结算了一个没跑过的活动；中断收益固定 0.5（10% 与 70% 无区别）；`outcome_for` 浅拷贝共享嵌套 dict。
- **修复**：
  - 实例只在 Director executor 确认时创建：`app._on_execute(source=mind)` → `sched.on_mind_action_started(...)`
    （创建 RUNNING 实例 + `mark_done`，owner 线程）；
  - `_apply_life_decision` 只结算"真正执行过且 RUNNING"的实例；被阻塞 → 无实例 → 无结算；
  - 状态机 `RUNNING → COMPLETED/INTERRUPTED/ABORTED/FAILED`（`pending_finish` 支持外部原因）+ 实例字段
    （instance_id/started_at/planned_duration/elapsed/progress/finish_reason/source）；
  - **进度感知奖励**：`scale = 1.0（完成）/ 0.3+0.7×progress（中断）`；未给 progress 默认 50% 中断（0.65，兼容旧语义）；
  - `outcome_for` 深拷贝（嵌套 needs/emotion dict 不再共享全局）。
- **证据**：
  ```
  仅提交 mind 决策 → _activity_instance is None、无 mark_done、无结算
  on_mind_action_started 后 → RUNNING 实例 + activity_history==[activity]
  10% 中断疲劳恢复(63.44 之后按新 scale) > 70% 中断 > 完成（progress 0.1/0.7/1.0 递增收益）
  改副本 needs/emotion 不影响全局 OUTCOMES
  ```

## 6. §6 Agent verified 硬门

- **复现（评审实证 false-green）**：`_verify()` 对非 fs 工具 `return True`，不要求 `res.verified`；
  `ToolResult(ok=True, verified=False)`（launch 观察失败）仍 → COMPLETED。旧契约测试用 `/tmp/xxx`
  在 `fs.list_dir` 早退，从未执行到被 mock 的 unverified 步骤。
- **修复**：
  - `_verify` 全局硬门：`res.ok AND res.verified`；工具特定检查只更严；
  - launch 可观察验证支持**真实进程身份别名**（calc → Calculator.exe 等 UWP 身份，不假设启动名==进程名）；
  - 重写 false-green 测试：`tmp_path` + 全前置 + **断言被 mock 步骤真正被调用**。
- **证据**：
  ```
  ToolResult(ok=True, verified=False)（ListDir 伪造）→ status != completed、无 AGENT_COMPLETED
  organize 步骤 mock verified=False 且调用数 >0（早退不算数）→ 不完成
  launch 观察失败 → 不 COMPLETED、无事件
  tasklist 输出 Calculator.exe → _observe_process("calc") == True
  ```

## 7. §7 语义 Ignore 的生产触发（响应窗口）

- **修复**：Scheduler 社交响应窗口 —— 芙宁娜选择社交类活动（approach/talk/greet/invite/seek_attention/
  ask_user/comfort）且用户在场 → `begin_social_bid()`（pending token + 60s deadline）；
  真实回应（定型互动/文本/喂食/拒绝）→ `on_user_response()` 取消；`_tick_medium` 检查到期 → `on_user_ignore()` 恰好一次。
  指针离开/自主环境台词/用户缺席不开启、不触发。
- **证据**：超时无回应 → `user_ignore==1` 且不重复；用户回应 → 0；指针阶段不取消也不触发（到期才 ignore）；
  无 bid → 不触发；用户缺席 → 不开启。

## 8. §8 Harness 真值

### 8.1 Agent 状态单一 owner

- **复现**：`runtime_health()` 的 `_read_agent_state()` 读 `_busy/_last_err/_last_success`（不存在字段）
  → 把事件态覆盖回 IDLE。
- **修复**：`AgentRuntime.status` 真实生命周期字段（每次转移更新：RUNNING/COMPLETED_VERIFIED/FAILED/UNVERIFIED）；
  Harness 只读它。
- **证据**：`runtime_health()["agent"]` 依次 == RUNNING/UNVERIFIED/FAILED/COMPLETED_VERIFIED/IDLE（经 runtime_health，非 `_agent_state`）。

### 8.2 Life 徽章用最新一次

- **复现**：`life_badge()` 先看聚合 success，"success 后失败"仍显示 LAST_OK。
- **修复**：`_life_last["last_outcome"]`（OK/FAILED/FALLBACK）+ `last_attempt_at`，徽章只看最新一次。
- **证据**：success→FAILED ⇒ LAST_FAILED；FAILED→OK ⇒ LAST_OK；OK→FALLBACK ⇒ FALLBACK。

### 8.3 Feed 行为验证

- 旧源码串测试改为断言 `submit_feed` 唯一入口 + "Harness 不得再包 worker 线程"（`threading.Thread(target=self._apply_feed` 不存在），
  并新增 §3 thread-id 行为测试（`test_feed_domain_effect_runs_on_owner_thread`）。

## 9. §9 事件 → 权威状态 → Dialogue 快照顺序

- **修复**：语义事件在 owner 线程完成 Emotion/Relationship 效果 + 立即派生 label（§2.2/§3），
  Dialogue 快照随后读取的都是 post-event 状态。
- **证据**：`petting → label=="happy"`；`praise → EV_POSITIVE_RESPONSE 恰好一次 + label proud/happy`；
  `reject → label embarrassed/sad`。

## 10. 强化后的 false-green 测试（替换说明）

| 旧测试 | 问题 | 替换 |
|---|---|---|
| `test_agent_completed_only_after_all_verified` | `/tmp/xxx` 早退于 list_dir，没测到 verified 门 | `test_agent_completed_contract_test_not_early_failure`（tmp_path + mock 步骤调用数>0）+ `test_toolresult_verified_false_is_global_hard_gate` |
| `test_harness_agent_unverified_not_green` | 直测 `_agent_state`，不经 runtime_health | `test_harness_agent_status_from_runtime_owner`（经 runtime_health） |
| `test_gui_feed_uses_same_submit_path_as_harness` | 断言 `_feed` 源码 | 断言 `submit_feed` 唯一入口 + Harness 无第二 worker 线程 |
| `test_state_user_working_comes_from_world` | 源码串断言 | 行为级：真实 `_tick_medium` 采样路径 → CODING + user_working True |
| `test_emotion_decay.../test_unknown_interaction...` 等源码守卫 | 保留为守卫 | 新行为测试补位（§2.2/§2.4） |

## 11. 全量回归

| 基线（9f5e44f） | 本终审 |
|---|---|
| 530 passed / 0 failed | **581 passed / 0 failed**（+51：test_phase13_r1/r1b/r1c + 强化测试） |

- 旧测试仅按上述替换/更新（均因旧断言未覆盖完整生产行为或编码被证伪的旧契约）。
- 顺带修复：sleepy 误判（tired_hint 阈值）、世界时钟/单次更新、FIFO 死锁（无 user_text 回合槽位占位）。

## 12. 剩余 Manual-only 项（诚实声明）

1. 真实 Windows 前台采样（tasklist/GetLastInputInfo 真机输出）。
2. 真实 glm-4v-flash 13 场景转录 + 盲评（**Persona = NOT REVIEWED**）。
3. Qt/Windows 响应性与真实 GUI 交互（点击/拖拽/喂食/Agent）。
4. 真实 app.launch 可观察验证（测试用 mock 观察函数）。
5. 空间自然度的人眼观感（wander/explore 平滑已机械验证 <45°，主观自然度属 Manual）。

## 13. STOP

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

未声称任何 PASS。评审通过后进入 Manual Experience Acceptance（非 Phase 14）。
