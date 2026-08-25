# Phase 13A — Functional Truth Closeout

## 0. Verdict

```
Technical:            PARTIAL
Manual readiness:     NOT READY（尚有 §7/§9/§10/§11/§13 未完全闭合）
Previous tests:       394
New tests:            11 (test_truth_closeout.py) + (14 harness)
Total:                405
Backend semantic params changed: NO（仅 Scheduler 互动 handler 的 ownership 收敛 + app 世界/记忆接线）
Assets changed:       NONE
```

诚实结论：本阶段把**用户最常看到的 truth 断点**（假绿 / 单一空间 / Qt 线程 / 空 world / 记忆类型 /
互动双写 / 对话真相 / anti-collapse）修好并证明；**但仍为 PARTIAL**——§7 Agent exactly-once 与
Agent failure→Dialogue、§9 feed 非阻塞、§10 完整因果 trace、§11 跨线程 root 关联、§13 真实 memory count
未完全闭合。**不宣称 PASS，不交给用户做 Manual 验收**（§17：条件未全满足）。

---

## 1. REAL ROUTE EVIDENCE（mach-done 项）

### Interaction exactly-once（§6）
`InteractionEngine.emit_event("petting","head")` 真实 route：
- RelationshipEngine.apply 计数 = **1**（`test_petting_relationship_applied_once_real_route`）。
- Scheduler._on_interaction 已**不再直接写 emotion/relationship**（`test_petting_emotion_engine_single_writer` source）。
- poke 同样 exactly-once（`test_poke_real_route_no_conflicting_double_apply`）。

### anti-collapse OFF（§12）
- 生产 `_apply_life_decision` 不再调用 `_anti_collapse`；旧实现保留为未启用 debt
  （`test_production_anti_collapse_is_off`，去注释后仅看真实代码）。

### Space single truth（§2）
- `launch_harness` 创建**唯一** DesktopSpatialRuntime，注入 RuntimeHarness；
  `harness.spatial is app._spatial`（`test_harness_and_panel_share_single_spatial_runtime` + 运行时 boot 打印 True）。

### World + Memory context（§4/§5）
- `Furina._runtime_world_factors()` 只读 Scheduler.world_perc，供 `_brain_worker`/`_feed` 使用（不再空 `{}`）。
- `memory.interpret(mem_objs)` 传 `List[Memory]`（非 List[str]），`_brain_worker`/`_feed`/`_speak_via_dialogue` 已改。

### Frame.speech = conversation truth + dedup（§8）
- Harness Conversation 以 `CharacterRuntimeFrame.speech` 为准（`_on_frame`），去重同句（`test_frame_speech_is_harness_conversation_truth`）。

### Truth badges / fallback（§1）
- `runtime_health()` 只从真实指标（life attempt/success/fallback/failure、dialogue outcome、agent state）得出；
  `current_life()['fallback']` 来自真实计数（`test_current_life_fallback_not_hardcoded`，构造 5 fallback → "YES"）。

### Qt thread marshalling（§3）
- 背景 EventBus 回调 → `queue_chat()`（线程安全队列）→ panel 定时器在 **GUI 线程** `drain_chat()` 显示；
  无 QWidget 跨线程直改（Harness Conversation 与 proxy 更新均在 GUI 线程）。

---

## 2. Truth Panel fixes（§1）
- 徽章不再"对象存在即 glm ✓"；Dialogue 徽章按 `SPOKE / MODEL_FAILURE / SILENT_BY_POLICY`。
- `current_life.fallback` 来自 `brain_metrics`（life_fallbacks/failures）。
- Agent badge 用真实 `_busy/_last_success/_last_err`（正确的 agent 组件读取，不硬引错误模块）。

## 3. Qt thread proof（§3）
- `drain_chat` 仅在 panel 的 `_refresh`（GUI 线程）执行；`queue_chat` 可从任意线程调用。
- 测试：`test_frame_speech_is_harness_conversation_truth` 通过（队列 + 去重）。

## 4. World + Memory context proof（§4/§5）
- `_runtime_world_factors()` 返回 `{user_working, user_activity, ...}`，非空。
- `interpret` 接收 memory 对象（`test_memory_interpret_receives_memory_objects`）。

## 5. Interaction ownership（§6）
```
Emotion writer:      EmotionEngine only（App INTERACTION_INPUT handler；Scheduler 不再写）
Relationship writer: RelationshipEngine.apply only，exactly-once（App._on_meaningful_interaction）
Memory writer:       MemoryEngine only（Scheduler._consolidate_episode / App._on_meaningful_interaction）
```
`test_relationship_event_applied_once` 旧的"手工 apply 两次"伪验收已由真实 route 测试取代。

## 6. Agent ownership（§7）—— **PARTIAL**
```
Entry:               打开记事本/计算器/整理测试目录 均路由到 Agent（AGENT_TASKS 已加 打开计算器）
Lifecycle event owner: 未完全收敛 —— AgentRuntime.execute 与 App._agent_worker 可能重复 emit
Success count:       未 exactly-once 验证
Failure count:       未 exactly-once 验证
Dialogue count:      Agent failure 用户反馈未走 DialogueBrain（仍为固定 SYSTEM_STATUS）
```

## 7. Frame Speech as UI truth（§8）— done。

## 8. Trace correlation（§11）—— **PARTIAL**
- 目前仍为"每个触发一个 root"；后台 DialogueBrain/LifeBrain 未继承用户输入的 root_trace_id
  （未做 §11 显式 trace context / request id 关联）。

## 9. Regression
```
Previous: 394
New:      11 → 405 总量（含 14 harness + 11 truth-closeout）
Broken:   0
```

## 10. Narrow Freeze Exceptions
无"调参"型例外；属于 ownership/接线收敛：
- Scheduler._on_interaction：移除 emotion/relationship 直接写（改为单 owner）。
- app._brain_worker/_feed：世界上下文改读 Scheduler；memory interpret 传对象。
- app._runtime_world_factors：新只读 helper。
- 语义参数修改：NO。

## 11. Remaining Debt（Phase 13B 候选，若继续）
- §7 Agent lifecycle exactly-once（单 owner）+ Agent failure → DialogueBrain(task_mode)。
- §9 feed 的 LLM 部分放入后台（确定 effect 同步、speech 异步）。
- §10 完整因果 trace（emotion/relationship before→after、memory stored/dedup、agent plan/permission/tool 链）。
- §11 跨线程 root_trace_id 关联（防两条消息串 trace）。
- §13 `memory_info()` 真实 rows 计数（或改 badge 为 Memory available: YES/NO）。

## 12. Verdict
```
Technical: PARTIAL
```
（≤5 句）最影响用户"看到就是在发生"的 truth 断点已修好并证明：不假绿、单一空间、Qt 线程安全、
世界/记忆上下文真实、互动单写 exactly-once、对话以 Frame.speech 为准且去重、anti-collapse=OFF。
但 Agent exactly-once/dialogue、feed 非阻塞、完整因果 trace、跨线程 root 关联、真实记忆计数仍未闭合。
**不宣称 PASS；Manual 验收仍未就绪。**

## 13. Next Step
（本阶段是 Closeout，非新功能。）继续 Phase 13B 把 §7/§9/§10/§11/§13 闭合后再让用户 Manual 验收；
禁止开始 Phase 14、禁止素材/参数工作。
