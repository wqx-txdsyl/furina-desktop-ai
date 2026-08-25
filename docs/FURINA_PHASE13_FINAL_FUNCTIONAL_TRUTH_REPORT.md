# Phase 13 FINAL Functional Truth Closeout — 终审报告

**评审基线**：commit `2d0da7fb7a34e938f2a064807b8a1f62bec22d2e`（C-R2 hotfix）
**本报告证据规则**：复现 → 根因 → 生产修复 → 确定性证据 → 回归；测试数量只是回归基线。
**真实 GLM 转录**：见 §6（本轮未产生，诚实声明）。

---

## 1. 已修复项（复现 → 根因 → 修复 → 证据）

### §2 世界真相（Windows 感知边界）

**2.1 时钟（year, month → hour, minute）**
- 复现：`time.localtime()[:2] => (2026, 8)`（真实输出）→ `clock_hour≈2026`，昼夜/睡眠语义被污染。
- 根因：`update_clock(*time.localtime()[:2])` 把 (year, month) 当 (hour, minute)。
- 修复：`furina/runtime/scheduler.py` `update_clock(lt.tm_hour, lt.tm_min)`。
- 证据：真实探针 `tm_hour, tm_min => (11, 0)`；day_period `{8:morning, 13:afternoon, 20:evening, 0:night}`。

**2.2 真实输入空闲秒（GetLastInputInfo）**
- 复现：生产无 GetLastInputInfo；`user_idle_seconds` 被上一帧值自喂。
- 修复：`window_awareness._get_idle_seconds()`（ctypes GetLastInputInfo）+ `WindowInfo.idle`；
  `_tick_medium` 用 `self.wa.last_idle` 写入 `state.user_idle_seconds`，不再自喂。

**2.3 user_working 来自 World**
- 复现：`update_needs(..., self.se.state.user_working, ...)` 用上一帧值（自喂）。
- 修复：`_tick_medium` 从 `world_perc.factors()["user_working"]` 读（进程分类 + title），写回 state。

**2.4 进程可执行名 vs 窗口类名**
- 复现：`Chrome_WidgetWin_1` 含 "et" → 被 `("excel","et")` 子串匹配误判为表格/办公。
- 修复：`WindowInfo.process`（GetWindowThreadProcessId → OpenProcess → QueryFullProcessImageNameW）；
  分类只吃进程名（`_APP_CATEGORY_EXACT` 精确匹配，"et" 仅作 WPS 表格真实进程名）；
  `classify_activity` 同步改为整词匹配。证据：`_cat("Chrome_WidgetWin_1","") == "unknown"`。

**2.5 稳定性阈值**
- 复现：`_STABLE_ACTIVITY_MIN=30` 声明未用，类别切换即时生效（一次误判即切换）。
- 修复：`WorldPerception` 增加 pending 候选 + dt 累计稳定时长，满 30s 才真正切换（away/idle 立即）。

**测试**：`test_scheduler_clock_uses_hour_minute / test_world_day_period_known_times / test_windows_idle_signal_is_runtime_truth / test_foreground_process_separate_from_window_class / test_chrome_widget_class_not_false_office_match / test_state_user_working_comes_from_world / test_world_activity_transition_requires_stability / test_world_unknown_does_not_fake_typing`。

---

### §3 Needs 人类尺度时间常数

- 复现（旧每秒漂移）：working 120s → fatigue≈86/boredom≈100；idle 600s → hunger≈86。
- 根因：所有被动漂移是 per-second 常数（"时间流逝感"失真）；驱动型需求被 drift 无界推过 peak 到 100。
- 修复（`state_engine.py`）：全部漂移改 **per-minute 常数**（线性 /60 → per-second，dt 不变性）；
  驱动型需求（boredom/playfulness/curiosity/social_need）**封顶于各自 peak（58-78，不贴 100）**；
  `_recharge/_rising_drive` 改精确指数（`1-exp(-rate·dt)`，修复 dt=30 时 k≥1 瞬间钉死）。
- 证据（真实探针，模拟 8h）：

```
30min  working {fatigue 32.6, hunger 26.8, sleepiness 15.1, energy 75.0, boredom 72.0}
120min working {fatigue 70.4, hunger 43.0, sleepiness 25.9, energy 75.0, boredom 72.0}
240min working {fatigue 100.0, hunger 64.6, sleepiness 40.3, energy 75.0, boredom 72.0}
480min working {fatigue 100.0, hunger 100.0, sleepiness 69.1, energy 75.0, boredom 72.0}
480min nonwork {fatigue 39.2, hunger 100.0, sleepiness 69.1, energy 75.0, boredom 72.0}
```

满足验收：30 分钟无生理需求饱和；2h 工作 fatigue 显著但非危机；hunger 小时级演化；sleepiness 昼夜兼容；驱动永不贴 100。

**测试**：`test_needs_no_minutes_scale_saturation / _30min_normal_session_sane / _2h_working_curve_sane / _4h_curve_sane / _dt_invariance`。
旧 `test_dynamics` 从 120min 窗口改为 8h 人类尺度（旧窗口编码了被证伪的时间流逝感），振荡断言按封顶驱动带重标定并注释原因。

---

### §4 情绪语义真相

- 复现：默认派生 `sleepy`（calm=70 被 `_sleepiness≈70` 抢位）；praise→calm（绝对基线压过事件）；事件 ~60s 被抹平；
  LifeDecision 直接覆盖 `emotion.label`；praise/reject/ignore/return/agent_done/feed 未接线。
- 根因：label 用**绝对最大值**而非基线-相对显著度；衰减 τ≈20s；语义事件未路由；所有权被 LifeBrain 侵犯。
- 修复（`emotion/engine.py` + `app.py` + `scheduler.py`）：
  - **基线-相对显著度 + 阈值**（`_SALIENCE_MIN=4.5`）：默认 → calm；praise→proud/happy；reject→embarrassed/sad；poke→annoyed；return→happy；agent_done→proud；
  - **sleepy 只由真实困倦信号**（`tired_hint`，来自 Needs）派生，绝不把"平静"误判为困倦；
  - **分钟级衰减**（τ=600s @ rate=0.15；精确指数）：5min 保留 ≈61%，30min 回落 ≈5%；
  - **语义事件接线恰好一次**：praise/reject（文本高置信）+ talk（普通对话）+ feed（EVENT_FEED）+ agent_done（EVENT_AGENT_DONE）+ return（idle→active 边界）+ ignore（EVENT_IGNORE）；
  - **所有权**：LifeDecision.emotion → `Intent.emotion`（非权威表达提示槽），不再写 `EmotionState.label`；未知互动 kind → None（不再默认 EVENT_CLICK）。
- 证据（真实探针）：

```
baseline -> calm | praise -> proud | reject -> embarrassed | poke -> annoyed
talk -> happy | feed -> happy | return -> happy | agent_done -> proud
praise 后 pride 显著度: 0min=8.0 5min=4.9 30min=0.4   （分钟级保留）
```

**测试**：`test_default_emotion_is_calm / test_default_not_sleepy_without_tired / test_praise_changes_derived_emotion / test_reject_changes_derived_emotion / test_poke_can_create_annoyed_state / test_return_makes_happy / test_emotion_decay_is_minutes_scale / test_emotion_event_routes_exactly_once / test_life_decision_does_not_write_emotion_truth / test_unknown_interaction_not_mapped_to_click`。

---

### §5 强制多样 = OFF（延续 + 补强）

- 复现：BehaviorMotivation 仍含 `_category_penalty/_activity_penalty/_observation_crush_guard` 与 18s idle 唤醒。
- 修复：三个多样机制注释禁用；唯一保留显式时间项 = 30/90s 语义冷却（活动本身）；`autonomy_stagnation` 唤醒删除（全文件无该串）。
- 行为证据（新增）：

```
test_unchanged_state_history_alone_does_not_force_category_switch  ✓（仅历史不同不改 top）
test_repeated_read_can_remain_top_candidate                       ✓（反复 read 仍可 top）
test_observation_ratio_does_not_boost_unrelated_categories        ✓（观察占比不抬高其它类）
test_no_autonomy_stagnation_interrupt_for_quiet_idle              ✓
test_forced_diversity_production_calls_zero                       ✓
```

---

### §6 Activity 生命周期与 Outcome 真相

- 复现：活动替换被当作自动完成（`_apply_activity_outcome(prev)` 默认 success=True）；
  OUTCOMES 带 relationship delta（自我农场：自主 approach/talk/help 就涨 trust）；
  `approach_user` social_need 双重结算（needs dict + 字段各一次）；
  `outcome_for` 修改共享全局对象。
- 修复（`behavior/outcome.py` + `scheduler.py`）：
  - `outcome_for` 返回 `dataclasses.replace` **新鲜副本**（不污染全局）；
  - **OUTCOMES 移除全部 relationship delta**（关系只由 RelationshipEngine 从真实证据写入；
    `apply_outcome` 关系块删除，参数保留为签名兼容）；
  - social_need **唯一字段恰好一次**（approach_user 的 needs dict 重复项删除）；
  - 生命周期：活动实例 `{activity, instance_id, started_at, planned_duration}`；
    替换时按 `elapsed ≥ planned_duration` 判 COMPLETED（全额）/ 否则 INTERRUPTED（减半）；
    `_last_activity_finish{activity, reason, elapsed, planned_duration}` 可观察；
  - **已验证的 Agent 帮助 → EV_SUCCESSFUL_HELP 恰好一次**（`_on_agent_done`，verified=False 不发）。
- 证据：`outcome_for success=True/False 独立；全局 spec 仍 True`。
- 测试：`test_activity_replacement_is_not_automatic_completion / test_activity_completion_when_duration_elapsed / test_interrupted_activity_not_full_reward / test_activity_completion_exactly_once / test_outcome_spec_not_shared_mutable / test_social_need_not_double_applied / test_autonomous_social_activity_cannot_self_farm_relationship / test_verified_help_can_emit_relationship_event_once`。

---

### §7 真实输入语义恰好一次

- 复现：GRAB/RELEASE/HOVER/LEAVE 全被当正面互动（扣社交/加接纳度/可打断）；未知 kind 默认 EVENT_CLICK。
- 修复：`_on_interaction` 顶部门控（grab/release/hover/leave/approach/double_click 直接 return）；
  未知 kind → `None`；**语义忽略 USER_IGNORE**（Scheduler.on_user_ignore：EVENT_IGNORE + EV_IGNORE + Life 收敛 + 记忆，恰好一次），Harness Ignore 走该路由（不再映射指针 leave）。
- 测试：`test_grab_does_not_change_social_need / test_real_click_has_one_semantic_causal_event / test_grab_release_hover_leave_are_not_positive_interaction / test_unknown_interaction_not_mapped_to_click / test_ignore_is_not_pointer_leave / test_semantic_ignore_affects_emotion_relationship_once`。

---

### §8 线程所有权 + 对话 FIFO

- 复现：BRAIN_SPOKE/AGENT_COMPLETED 在 worker 线程同步改运行时状态；对话竞态 user1/user2/reply2/reply1。
- 修复：
  - **DialogueBrain.say FIFO 串行**（`_say_lock` RLock 覆盖整个生成 + history 写入；`say()` 包装 `_say_impl()`）；
  - **Scheduler apply 队列**：BRAIN_SPOKE/AGENT_COMPLETED/AGENT_FAILED 入 `_apply_q`，由 owner 线程
    （`step()`/`drain_apply()`）统一落地；`_speak_via_dialogue` 的 `_say` 结果同样入队；
    Harness `tick_spatial()` 先 drain（GUI 线程 = owner）。
- 证据（行为）：`test_two_fast_user_messages_preserve_reply_order`（turn1 慢 250ms，history 仍
  user1→furina1→user2→furina2）；`test_brain_spoke_marshaled_to_runtime_apply_thread`（worker emit 不改状态，
  drain 后落地）；`test_agent_completion_marshaled_to_runtime_apply_thread`。

---

### §9 Validator 强制执行

- 复现：`valid=False` 除 generic_assistant_voice 外原样返回；"你能别烦我吗？"被 "吗" 抢成 RESPONSE_TO_QUESTION。
- 修复：`say()` 校验失败 → **同一 DialogueBrain 再生成一次（确定性校验反馈）→ 再验证**；
  仍失败 → None + `last_validation_failure`（可观察失败路径，App 转 SYSTEM_STATUS，不静默失声）；
  `classify_act` **拒绝/边界语义优先于标点式疑问检测**。
- 测试：`test_stage_direction_invalid_not_returned / test_too_long_invalid_not_returned / test_catchphrase_overuse_invalid_not_returned / test_over_exclamation_invalid_not_returned / test_example_copy_invalid_not_returned / test_direct_user_invalid_has_bounded_recovery / test_rejection_question_routes_decline`。

---

### §10 Agent 真相性

- 复现：计算器→notepad；`verified=False` 仍 COMPLETED；context 跨任务泄漏；Popen 成功即 verified=True；
  `_on_agent_body` 绕过 Director 直写状态；AGENT_COMPLETED 无 summary（Scheduler 落回 "完成啦。"）；
  `app.launch` 分类 L0_READ。
- 修复：
  - `_guess_app`：+计算器/calculator/calc；**未知 → None → 计划 failed/澄清**（绝不默认 notepad）；
  - **任务局部上下文**（`execute()` 每次新建 AgentContext）；
  - **verified 门**：`ok=True 且 verified=True` 才继续；否则 `status=unverified` + AGENT_FAILED（无 COMPLETED）；
  - **启动可观察验证**（`_observe_process`：Windows tasklist 轮询 ≤3s；未观察到 → verified=False）；
  - **Agent 身体经 Director**（`source=agent, P_AGENT_TASK`；executor 有 agent 分支，回调线程不直写状态）；
  - **结构化事实摘要**（`完成了 N/M 个步骤：goal（已验证 N 步）`）随 AGENT_COMPLETED 发出；
  - `LaunchTool.permission = L1_LOW_WRITE`（启动是副作用）。
- 测试：`test_calculator_maps_to_calc / test_unknown_open_request_does_not_default_notepad / test_agent_context_is_task_local / test_unverified_step_cannot_complete / test_launch_requires_observable_verification / test_agent_completed_only_after_all_verified / test_agent_body_goes_through_director / test_agent_summary_contains_verified_fact / test_app_launch_not_classified_read_only`。

---

### §11 Feed 生产路径

- 复现：GUI 命令 `_on_user_command → _feed()` 同步调用 DialogueBrain（LLM 慢调用阻塞 Qt）；Harness 与 GUI 行为不一致。
- 修复：`_feed` 的食物效应/情绪/记忆/打断**同步**完成，DialogueBrain 台词**后台线程**执行；
  GUI 与 Harness 走同一 `app._feed`；结果经 BRAIN_SPOKE → apply 队列在主线程落地。
- 测试：`test_gui_feed_uses_same_submit_path_as_harness / test_feed_emotion_event_exactly_once / test_slow_feed_dialogue_does_not_block_caller`。

---

### §12 空间自然性（wander/explore 平滑）

- 复现：评审轨迹探针 72°~167° 相邻航向跳变（折线机器人）；wander/explore 无平滑。
- 修复（`spatial/planner.py`）：wander/explore 改用 **角圆化（二次贝塞尔圆弧 + 直线段密集采样）**——
  路径贴折线、只圆转角、无 Catmull-Rom 稀疏控制点的 overshoot/回折；explore 中间点改为
  **沿轴单调的正弦摆动**（只前进不回折，幅度有界）；修复起/终点重复产生的零长段伪转角。
- 证据（真实轨迹采样，max heading delta，目标 <45°）：

```
approach_user  seeds [9.3, 46.5, 9.3, 51.3, 9.5]   ← 既有 Catmull-Rom（C-R1.7 已验收冻结，未改）
wander         seeds [5.7, 4.9, 6.1, 6.5, 5.5]
explore        seeds [5.7, 4.9, 6.1, 6.5, 5.5]
```

- 测试：`test_wander_has_no_sharp_waypoint_corner / test_explore_has_no_sharp_waypoint_corner / test_path_style_wander_explore_are_meander_or_multi`（叠加既有 `test_wander_targets_not_fixed_grid / test_path_stable_not_replanned_each_tick / test_drag_release_no_snap_back`）。

---

### §13 记忆契约单位债

- 复现：`behavior_hint()` 读原始 principal(0..100) 却按 0.6 阈值比较（raw comfort=1 → approach_bonus）。
- 修复：统一消费 canonical `relationship_factors()`（0..1），阈值保持 0.6。
- 证据：`raw comfort=1 → factors 0.010（不再触发）; raw 90 → 0.900（触发）`。
- 测试：`test_memory_behavior_hint_canonical_units`（含旧 bug 复现点）。

---

### §14 Harness 真值徽章（不许假绿）

- 复现：徽章可显示 "glm ✓ / Agent ✓" 只因 Brain 对象存在/导入成功；Memory "rows" 用 query(limit=1)（0/1）；
  Ignore = 指针 leave；无诊断字段。
- 修复（`harness/controller.py` + `window.py` + `memory_store.count()`）：
  - **Life**: UNAVAILABLE（未尝试）/ LAST_OK / LAST_FAILED / FALLBACK（真实 attempt/success/failure/fallback）；
  - **Dialogue**: UNAVAILABLE（无适配器）/ AVAILABLE（可调用未尝试）/ LAST_OK / LAST_FAILED（真实 outcome + llm.is_available）；
  - **Agent**: IDLE / RUNNING / COMPLETED_VERIFIED（仅 AGENT_COMPLETED，§10 门保证已验证）/ FAILED / UNVERIFIED（unverified_step 失败）；
  - **Memory**: `{status: AVAILABLE/EMPTY/UNAVAILABLE, count: n}`（真实 `count()`，非 0/1）；
  - **诊断字段**：clock(hour/minute)、idle_seconds、user_working、world(process/category/activity)、
    emotion_recent_events + label、life_next_think、activity_finish{reason,elapsed,planned}、activity_instance、
    spatial{path_style, waypoints, max_heading_delta_deg}。
- 测试：`test_harness_badges_never_green_by_import / test_harness_last_failure_not_green / test_harness_fallback_not_green / test_harness_agent_unverified_not_green / test_harness_memory_count_truthful / test_harness_diagnostics_present / test_harness_ignore_uses_semantic_ignore / test_harness_feed_same_production_path`。

---

## 2. 回归

| 基线 | 本终审 |
|---|---|
| 452 passed / 0 failed（C-R2 hotfix） | **526 passed / 0 failed**（+74 新增：final/final2/final3/final4/final5） |

替换/更新的旧测试（均因旧断言编码了被证伪的行为，已注释原因）：
- `test_dynamics`：120min → 480min 人类尺度；振荡阈值按封顶驱动带重标定；takeover 阈值改为"≥2× 全分布基线"。
- `test_closeout_r1::test_annoyance_07_triggers_06_path`：断言 canonical 形式。
- `test_agent_tools`：launch 成功需 mock 可观察验证（§10.4 诚实语义）。
- `test_phase13b::test_memory_badge_honest`：断言 COUNT=n 真值契约（§14）。

## 3. 真实 GLM / Persona 证据

**本轮未产生。** 会话内无可用生产 GLM-4v-flash 直连端点，无法执行 13 场景真实转录。
**Persona = NOT REVIEWED**（任何自动化测试都不能自称 Persona PASS）。

## 4. 剩余不可验证项（诚实声明）

1. 真实 Windows 进程/空闲采样（本机无前台应用运行时的实际 tasklist/GetLastInputInfo 输出留待 Manual）。
2. 真实 GLM 13 场景转录 + 盲评（需端点可用环境）。
3. 真实 GUI 交互（Qt 窗口内点击/拖拽/喂食）的手工体验。
4. `app.launch` 真实启动验证（测试用 mock 观察函数；真机行为需 Manual 复验）。

## 5. STOP

### 最终判定

```text
Technical = READY_FOR_REVIEW        （§2-§14 全部实现，73 项新测试 + 真实探针证据）
Real Runtime Evidence = PROVIDED    （本报告 §1 各节的复现/探针/轨迹采样）
Persona = NOT REVIEWED              （无 GLM 转录，不自我通过）
Manual = NOT YET REVIEWED
Overall = REVIEW_REQUIRED
```

**未写**：Phase 13 PASS / Persona PASS / Manual PASS / Ready for Phase 14。

**下一步**：评审通过后进入 **Manual Experience Acceptance**（真实运行轨迹：长时间 Life 节奏、安静共处、真实 World 上下文、情绪因果、互动/拒绝/恢复、记忆、喂食、Agent 真相性、真实空间运动、真实 GLM 人格、Windows 响应），Manual 通过后才允许 Phase 14。
