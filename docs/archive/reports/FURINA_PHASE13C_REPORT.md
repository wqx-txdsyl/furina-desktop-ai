# Phase 13C — C-R1 Closeout（Digital Life Experience Recovery）

## 0. Status

```
Technical:            READY_FOR_REVIEW
Persona:              PENDING（需用户盲评 §50，Agent 不代判）
Manual:               NOT STARTED（需用户跑 --harness + 人工确认空间天然性 / 15-turn / 盲评）
Overall:              REVIEW_REQUIRED

Assets:               NONE（0 素材改动）
Models:               unchanged（glm-4v-flash）
DB:                   unchanged
Backend semantic parameter changes: NO（无 Needs/Emotion/Relationship/Behavior 数值调整；
                      仅新增 factors() 归一化契约 + act 路由 + grounding + 机制引导 + 修正混单位阈值）
```

> **不写 Phase 13 PASS。** 按 reviewer 要求，只报 `READY_FOR_REVIEW`，等 reviewer 复核。
> 报告与最终代码逐项一致。

---

## 1. REAL ROUTE EVIDENCE（先于 Regression）

### C-R1.1 Life Autonomy
- `decide()` **不再调用** `_apply_variety` / 任何 repeat guard；`_life_prompt` 移除"刻意换类别 / 别连续同类 / 最近做过就换"硬要求（保留"近期行为"作信息，不强制改选）。
- `_apply_schedule` **不再 8..45 clamp** —— 真实 `next_think_in` 透传；统一安全 clamp owner = **Scheduler._life_think_interval**（5..120；sleep 15..180）。
- 证据测试：`test_production_no_forced_variety`、`test_repeated_reasonable_activity_allowed`（read→read 保留）、`test_next_think_not_truncated`（`test_life_next_think_clamped_not_60000` 已**替换**为 `test_life_next_think_not_truncated_to_45`：d.next_think_in==60000 不被截断）。
- Interrupt 仍可提前唤醒（`on_user_reject → _interrupt_life`；interaction/feed 均 `_interrupt_life`）。

### C-R1.2 Relationship Scale
- `RelationshipEngine` 现在**只有一个 `factors()`**（删除了遗留的 /100 重复方法）。
- canonical raw 单位：熟人/信任/舒适/依恋/尊重/依赖/烦/接纳度/社交自信 = **0..100**（engine decay clamp 0.5..99.5 佐证）→ factors() `/100`；`user_response_rate/user_rejection_rate` = **0..1**（默认 0.5/0.0）→ 原样。
- 所有 Dialogue 消费者（direct/feeding/autonomous Life speech/interaction speech/Agent speech）+ Embodiment 一律 `relationship.factors()` / `_rel_factors()`；`DialogueBrain.say` 不再收 `state.as_dict()` raw。
- `expressive.py mode()` 不再 ×100 传给 `mode_for`；混单位阈值修正：`memory_engine` annoyance>0.6（原 >60）、`furina_character_contract` annoyance>0.6 / trust<0.25 / trust>0.55 / familiarity>0.6、`life_brain._relationship_factors` 不再 /100。
- 证据：`test_relationship_factors_exact_numeric`（trust 50→0.5、response_rate 0.5→0.5、tolerance 50→0.5、confidence 40→0.4）、`test_annoyance_07_triggers_06_path`、`test_all_dialogue_callsites_normalized`、`test_raw_relationship_not_in_dialogue_consumer`。

### C-R1.3 Conversation Context
- `say()` 的 history 只含**当前轮之前**的发言；当前 `user_text` 单独附一次（prompt 中当前 user 恰好出现一次）。
- 对话→记忆观察放在**回复完成之后**（`_maybe_observe_conversation(text)` 在 `speech` 产出后调用），避免当前轮记忆被同一 prompt 检索回显。
- 证据：`test_current_user_appears_once_in_prompt`（count==1 + history 不含当前 user）。

### C-R1.4 Conversation Memory
- 使用正式 **`MemorySource.CONVERSATION`**（原 `getattr(..., "DIALOGUE", SYSTEM)` 已改）。
- 证据：`test_conversation_memory_source`（stored.source.value == "conversation"）。

### C-R1.5 Text → Life Interaction（统一 route）
- 文本拒绝走 **`sched.on_user_reject()`** —— 与 Reject 按钮**同一个语义执行入口**（relationship exactly-once + persistence + rejection stats + tolerance↓ + `_interrupt_life` + 后续空间/动机收敛）。
- Praise/gratitude 用 **EV_POSITIVE_RESPONSE**（不伪装成 EV_POSITIVE_TOUCH）。
- 保守阈值：`"这功能烦死了"` 不误判为拒绝。
- 证据：`test_text_reject_emits_relationship_event_once`（exactly-once）、`test_ambiguous_negative_text_does_not_false_reject`（0 触发）。

### C-R1.6 Persona Few-Shot Routing + Validator
- `_route_example_context(act, activity, user_text)` 把 act 映射到 example context（question_activity / rejection / agent_success / memory_callback / comfort / praise / high_trust）。
- 移除 few-shot 舞台动作 `（合上书）（皱眉）（想了想）…`。
- Validator §48：新增泛化鼓励 / "谢谢夸奖"式 / 客服开场 pattern + `overuse_god_catchphrase`（"本神">2）+ `over_exclamation`（短句感叹≥4）。
- 证据：`test_example_selector_routes_act_to_context`（Top-K 命中目标 example）、`test_examples_have_no_stage_actions`。

### C-R1.7 Spatial Naturalness
- `CURVED_APPROACH / ARC_WITHDRAW` 用 **Catmull-Rom 密集采样**（≥8 段），方向连续；wander/explore 目标加**有界位置抖动**并重新校验 safe zone（非固定 4×3 网格点）。
- 路径稳定不每 tick 重随机；保留 dt / ease / arrival / 安全区 / 拖拽 owner。
- 证据：`test_curved_approach_is_smooth`（≥8 waypoint，隔壁 heading 最大转角 <45°）、`test_wander_targets_not_fixed_grid`（8 次 ≥4 个不同坐标）、`test_path_does_not_replan_every_tick`、`test_drag_cancels_active_path`。

---

## 2. Regression
```
Previous: 428
New:      13 (test_closeout_r1.py)
Total:    441
Broken:   0
Replaced broken-assumption tests (编码旧破坏行为，§66):
  - test_three_brain.py::test_life_next_think_clamped_not_60000 → test_life_next_think_not_truncated_to_45
    （旧测试断言 8..45 clamp，那正是 C-R1.1 要修的强制节拍器；改为断言"不被截断到45"）
```

## 3. 修改文件
`furina/life_brain.py`（去强制多样 + 去 8..45 clamp + prompt 软化 + _relationship_factors 修 /100）、
`furina/relationship/engine.py`（单一 factors() + canonical 单位）、
`furina/dialogue/expressive.py`（mode() 不再 ×100）、
`furina/dialogue/validator.py`（§48 通用泄漏 + 角色塌陷）、
`furina/dialogue_brain.py`（history 去当前轮 + example 路由 + 机制引导）、
`furina/persona/expression_examples.py`（新增情境例子 + 去舞台动作）、
`furina/persona/furina_character_contract.py`（0..1 阈值）、
`furina/runtime/scheduler.py`（_rel_factors() + Dialogue/Embodiment 归一化 + 生命节拍器移除）、
`furina/runtime/spatial/planner.py`（Catmull-Rom 平滑 + wander/explore 抖动）、
`furina/runtime/spatial/runtime.py`（沿 waypoints 路径 + _goal）、
`furina/memory/memory_engine.py`（annoyance 0.6）、
`furina/app.py`（_apply_user_text_fx 统一 route + 观察后置 + CONVERSATION source + factors()）、
`tests/test_closeout_r1.py`（13 新）。

## 4. 剩余诚实弱点
- **Persona 盲评 / 真实 15-turn / 空间天然性人工确认**：需用户/ reviewer 亲自判定（§50/§59/§13）。
- Harness trace 新字段（§55）：本轮未新增（仅既有 agent/dialogue/frame trace）；属诊断增强，非功能性阻断。
- Agent 角色连续性（§52-53）：结果反馈路径复用已改进的同一条 DialogueBrain（13B），本轮未单独回归复核。

## 5. Verdict
```
Technical:  READY_FOR_REVIEW
Persona:    PENDING
Manual:     NOT STARTED
Overall:    REVIEW_REQUIRED
```
（≤5 句）C-R1 全部八项已按最终代码闭合：无强制多样、唯一 clamp owner、单一 factors() + canonical 单位并把混单位阈值全部修正、
当前轮去重不重复进 prompt、当前轮记忆不回声、CONVERSATION 源、文本拒绝与按钮共享统一 route、act→example 路由 + validator 扩展、
Catmull-Rom 平滑 + wander 非固定网格。**Persona/Manual 不可由 Agent 判定**，故 `READY_FOR_REVIEW / REVIEW_REQUIRED`，等待 reviewer 复核。

## 6. STOP
停止开发。请 reviewer 复核报告 + 代码（工作区为最新完整代码；本环境无法生成 ZIP，但库中即最终版）。
复核通过后再决定是否进入 Phase 14 / 素材。**不自动开始 Phase 14，不补素材，不调参。**
