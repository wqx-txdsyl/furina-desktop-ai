# Furina Desktop AI — Phase 13 H1 FINAL Reviewer Residual Patch 报告

**Review baseline:** `6db20043f9621e28d5978d04d8d234e4b6f7ba3e`（622 tests，H1 评审 = NOT ACCEPTED）
**证据规则**：每个残差先 BEFORE 复现 → 为什么旧 622-green 测试漏掉 → 生产修复 → AFTER 确定性证明（Event/Barrier/bounded join/可控状态/真实 EventBus·InteractionEngine·Director 路径/精确计数器/线程 ID）。

---

## 1. P0 — 生产互动把 Emotion 应用两次

- **BEFORE（复现）**：`Furina.__init__` 仍注册 `bus.on(INTERACTION_INPUT, _on_interaction_emotion)`，H1 又加了 `interaction.on_emotion_semantic = _on_interaction_emotion`；`_apply()` 先走钩子、广播再触发订阅 → 一次 pet/poke/drag/click 应用两次情绪。
- **为什么旧测试漏掉**：H1 测试 `_interaction_app()` 只接钩子，没复现真实 `__init__` 的 EventBus 订阅。
- **修复**：删除 EventBus `INTERACTION_INPUT → _on_interaction_emotion` 订阅；唯一 owner = `InteractionEngine.on_emotion_semantic`（预广播）。
- **AFTER（生产等价接线：真实 EventBus + 剩余唯一订阅）**：
  ```
  bus 上不再有 _on_interaction_emotion 订阅（断言）
  petting → _recent[user_pet]==1 + label=happy + 关系恰好一次
  poke → _recent[user_poke]==1 + label=annoyed；drag/click 同样恰好一次
  两次独立 petting → _recent[user_pet]==2（每次语义事件 +1，非 +2）
  ```

## 2. P0 — 直接对话 FIFO 序号在 worker 调度序分配

- **BEFORE**：`DialogueBrain.say()` 内部 `_next_seq()` —— worker2 先进入 say 会拿到更小 seq，FIFO 忠实保存**错误**顺序。H1 测试 `t1.start(); t2.start()` 依赖调度概率。
- **修复**：owner 线程在 `submit_user_message()` 入口调用 `dialogue_brain.reserve_turn()` 预留 seq；`DialogueContextSnapshot.ingress_seq` 携带；worker 以 `say(ingress_seq=snapshot.seq)` 消费。FIFO 身份 = 用户入队顺序。
- **AFTER（确定性：worker1 阻塞在 say() 之前，worker2 先到）**：
  ```
  attempts[:1]==["w2"]（worker2 确实先到达 say）
  LLM 调用序 == [1,2]（user1 先）
  history == 第一句/回复1/第二句/回复2；两线程 bounded join(5) 内退出
  ```

## 3. P0 — 自主 Life 台词仍在决策提交时启动

- **BEFORE**：`_apply_life_decision` 提交 ActionRequest 后立刻起 dialogue worker —— Agent 占用 Director 时，被阻塞的 talk/read 仍出叙述台词、可能开 social bid。旧 blocked-social 测试 `dialogue_brain=None`，测不到真 bug。
- **修复**：自主台词移入**执行边界**：speech 元数据（speech_level/speech_intent/dialogue_needed/emotion/duration）进 ActionRequest payload；`app._on_execute(source=mind)` 在 `on_mind_action_started` 后调 `sched.start_autonomous_dialogue(...)`（节流 + 冻结快照 + worker + owner 应用）。
- **AFTER（真实 Director + 成功 fake DB + worker 时间 + drain）**：
  ```
  Agent 拥有 Director → mind 决策（social/non-social）→ 等 0.3s + drain → say_calls==0、无 bid
  mind 执行 → start_autonomous_dialogue → say_calls==1、drain 后 _speech 落地
  Agent 释放 → mind 执行 → 台词 + social bid 才出现
  ```

## 4. P0 — 真实用户互动不 finalize 运行中的 mind

- **BEFORE**：pet/poke/drag/click 只改即时状态 + `interrupt_life`，不 finalize 运行中的 mind 实例（elapsed 继续走）；H1 只测了 Agent 抢占。
- **修复**：`InteractionEngine.on_user_takeover` 钩子（CLICK/PETTING/POKE/DRAG，预广播阶段）→ `app._on_user_takeover_interaction` → `sched.on_user_takeover()`（`on_mind_preempted("preempted_by_user")` + `director.finish(source="mind")`）。指针控制（grab/release/hover/leave）不经此路径。
- **AFTER（真实 emit_event + 运行中 mind）**：
  ```
  petting/poke/drag/click → finish_reason==preempted_by_user、status==INTERRUPTED、elapsed 冻结在互动时刻
  grab/release/hover/leave → status 仍 RUNNING（不抢占）
  再互动不重复结算；后续 Life 决策不得把它变 completed
  ```

## 5. P0 — Activity status 违反规范状态机

- **BEFORE**：`status = reason.upper()` → 产生 `PREEMPTED_BY_AGENT/PREEMPTED_BY_USER` 等非规范值。
- **修复**：`Scheduler._canonical_status(reason)`：status ∈ {RUNNING,COMPLETED,INTERRUPTED,ABORTED,FAILED}；`finish_reason` 独立保留 `preempted_by_agent/preempted_by_user/user_cancel/shutdown/...`；`_last_activity_finish` 也携带规范 status。
- **AFTER**：agent/user 抢占 → status==INTERRUPTED + finish_reason 保留来源；`_canonical_status` 对全部 reason 返回规范集。
- **旧测试更新**：`test_preempted_mind_cannot_later_become_completed` 断言改为 INTERRUPTED + finish_reason（不再断言 PREEMPTED_BY_AGENT）。

## 6. P0 — Harness 启动未显式绑定 owner

- **BEFORE**：`launch_harness` 不 bind —— 首个 timer 前的按钮/输入会触 `require_owner` 报"未绑定"。
- **修复**：`Scheduler.start()` 统一 `dispatcher.bind_owner()`（launch 与 launch_harness 共用；launch() 的额外 bind 保持幂等）。
- **AFTER**：`start()` 后 `owner_thread_id == 调用线程`；stub 走 start() 后 `submit_user_message/submit_feed` 不抛错。

## 7. P1 — idle 不可用未跨运行时边界

- **BEFORE**：`CharacterState.user_idle_seconds` 默认 0.0；首样本不可用时 World 把 0.0 当"用户刚互动"（可发 USER_BECAME_ACTIVE/离开转换）。
- **修复**：`idle_available` 位跨边界：`CharacterState.idle_available`、`WorldState.idle_available`；`WorldPerception.update(idle_available=...)` 在**从未有有效样本**时：`user_activity=UNKNOWN`、不发事件、不产生在场/活跃/离开转换；临时失败（已有有效样本）保留最后有效值但标当前不可用；harness 诊断暴露 `idle_available`。
- **AFTER**：
  ```
  首样本 unavailable → idle_available=False、activity=UNKNOWN、last_events==[]
  5 次 unavailable → recent 无 USER_BECAME_ACTIVE/USER_RETURNED
  有效样本 → available=True + value=42.0
  有效后临时失败 → 保留分类（不退回 UNKNOWN、不制造新活跃）
  harness 诊断 idle_available==False
  ```

## 8. P1 — 一次定型互动写两条长期记忆

- **BEFORE**：`App._on_meaningful_interaction`（memory.observe）+ Scheduler `_consolidate_episode`（同一事件另一格式）→ 两条。
- **修复**：**唯一长期记忆 owner = App 语义处理器**；Scheduler 互动路径移除 `_consolidate_episode`。
- **AFTER（精确计数器）**：petting/poke/drag 各恰好 1 条语义记忆、consolidate 计数 0；三次不同事件 → 3 条；关系/情绪仍恰好一次（§1 测试覆盖）。

## 9. 回归

| 基线（6db2004） | 本 patch |
|---|---|
| 622 passed / 0 failed | **657 passed / 0 failed**（+35：test_phase13_h1final.py） |

更新旧测试：`test_phase13_h1.py::test_preempted_mind_cannot_later_become_completed`（规范 status 断言）、
`test_phase13_h1b.py` 自主台词测试（改走执行边界 `start_autonomous_dialogue` + 新 `_freeze_ambient_snapshot` 签名）。

## 10. 剩余 Manual-only（诚实声明）

1. 真实 Windows 前台采样 / tasklist / GetLastInputInfo 真机输出。
2. 真实 glm-4v-flash 13 场景转录 + 盲评（**Persona = NOT REVIEWED**）。
3. Qt/Windows 真实 GUI 响应与手感（快照/owner 重构后）。
4. 真实 app.launch 可观察验证（测试用 mock）。
5. 空间自然度主观观感（机械 <45° 已冻结，主观属 Manual）。

## STOP

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

未声称任何 PASS。评审只复核本文件 §§1–8；通过则 **PHASE 13 TECHNICAL = PASS / BACKEND FUNCTIONAL CONTRACT = FROZEN** → Manual Experience Acceptance（非 Phase 14）。
