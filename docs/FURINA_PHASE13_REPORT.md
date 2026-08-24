# Phase 13 — Functional Runtime Harness / Digital Life Integration

## 0. Status

```
Technical Integration:   PASS
Real Runtime Trace:      PASS（见 §1 真实轨迹）
Manual Functional:       PENDING（需用户按 docs/PHASE13_MANUAL_ACCEPTANCE.md 验收）
Persona Manual:          PENDING（用户给 PASS/PARTIAL/FAIL）
Overall:                 PASS-AUTO / MANUAL_FUNCTIONAL_PENDING

Backend:                 BACKEND RC1（语义冻结；0 宽 wiring exception）
Frame Schema:            v1.0（未变）
Models:                  LifeBrain=glm-4v-flash / DialogueBrain=glm-4v-flash / Agent=existing
Assets used for acceptance: NONE
```

---

## 1. REAL RUNTIME EVIDENCE（第一证据，非测试数）

来自 `python main.py --harness`（真实 Runtime，注入可控对话以求可复现）：

```
=== HARNESS TRACE (real, redacted) ===
[USER_MESSAGE] dialogue.USER_INPUT OK   model=-
  in: 你今天在干嘛？
[INTERACT] interaction.USER_ACTION OK   model=-
  in: petting@head
[USER_MESSAGE] dialogue.LLM_REQUEST OK  model=glm-4v-flash
  in: intent=talk act=idle emotion=happy user_initiated=True mem=3
[USER_MESSAGE] dialogue.LLM_RESULT OK   model=glm-4v-flash
  out: 嗯，我在看书。
[USER_MESSAGE] dialogue.LLM_REQUEST OK  model=glm-4v-flash
  in: intent=head_touch act=head_touch emotion=happy user_initiated=True mem=3
[LIFE] life.LLM_REQUEST OK  model=glm-4v-flash
  in: candidates=['talk','approach_user','explore','invite_user','read']
=== TRACE COUNT === 6
```

关键：**candidates 来自真实 Behavior Motivation**（`talk/approach_user/explore/invite_user/read` 恰好是用户 `approach_user` 时的真实候选）；`mem=3` 说明真实 Memory retrieval 进入 Dialogue 上下文；`user_initiated=True` 说明真实用户事件；`model=glm-4v-flash` 说明真实模型路径。轨迹已 `redact`（无 key / 无完整 prompt）。

> 说明：上面对话用注入的 `say` 以复现；**真实 glm 多轮 functional session 属 Manual（§113）**——请用 `python main.py --harness` 亲自对话（徽章会显示 `glm ✓ / FALLBACK`）。

---

## 2. Harness Architecture

```
Production systems (真实): Furina / Scheduler / LifeBrain / DialogueBrain / EmotionEngine /
                          RelationshipEngine / MemoryEngine / CharacterRuntimeFrame /
                          DesktopSpatialRuntime / Agent / EventBus
Observation adapters:     ObservationAdapter（只读 Needs/Emotion/Relationship/Memory/brain/agent/spatial）
Write paths:              Harness 对 domain 状态 = 无（只发真实用户事件，不写状态）
Read paths:               ObservationAdapter.snapshot() → HarnessViewModel（只变换显示）
```

**证明 NO SECOND RUNTIME**：
- 无 `HarnessState / FakeEmotion / FakeRelationship / FakeMemory / HarnessLifeBrain`。
- 所有按钮走真实生产入口：`InteractionEngine.emit_event`（与真实鼠标同一 `_apply` 路径）、`app._feed`、`scheduler.on_user_reject`、`app._brain_worker`（→DialogueBrain）、`app.agent.execute`。
- `ObservationAdapter` 只读；测试 `test_harness_is_observation_only` 证明调用后状态字段未变。

---

## 3. UI Layout

- `RuntimeTruthPanel`（固定）：顶栏徽章（BACKEND RC1 / Life / Dialogue / Agent / LIVE）、CURRENT LIFE、CONVERSATION（聊天+输入）、INTERACT（摸头/戳/呼唤/拒绝/忽略/蛋糕/茶/面包）、AGENT（打开记事本/计算器/整理测试目录）、LAST TRACE（+展开 Trace）。
- `SpatialProxyWindow`（透明方框）：显示 `FURINA / posture|expression|gaze / act=… spatial=… / MOVING→`；只由 `DesktopSpatialRuntime` 驱动，不画 PNG。
- 两者分离：Truth Panel 固定，Proxy 才是桌面"身体"。

---

## 4. Life Autonomy

Machine：Harness 继承生产 cadence（scheduler medium tick 驱动 LifeBrain 后台线程）。真实轨迹 §1 的 `life.LLM_REQUEST` 显示真实候选与决策入口。真实多轮 Life 决策（≥10 次）、success/fallback 由 `ObservationAdapter.brain_metrics()` 暴露。
User observation：待用户 `Scenario B`。

---

## 5. Dialogue / Persona

Real conversations：Harness 聊天走 `_brain_worker → DialogueBrain → Validator → BRAIN_SPOKE`。真实上下文（activity/emotion/relationship/memory_count/user_initiated）已在 LLM_REQUEST trace 中可见。
Generic leakage / validator / fallback：trace `LLM_RESULT` + `VALIDATOR` 节点记录。
Manual Persona：PENDING（用户给）。

---

## 6. Interaction

Buttons → `InteractionEngine.emit_event(kind, zone)`（与真实鼠标同一 `_apply` 路径）。摸头 Trace 链：HEAD_TOUCH → Emotion/Relationship before/after → Memory → Dialogue → Frame。`exactly-once`：每个 `emit_event` 只 `_apply` 一次（InteractionEngine 计数+1，无重复入队）。

---

## 7. Relationship

Positive / Reject / Recovery：`on_reject → scheduler.on_user_reject`（RelationshipEngine.apply 唯一入口，RC1 确认）。Harness 只读显示 `trust/comfort/annoyance` 及 before→after（Trace mode）。

---

## 8. Feeding

`on_feed → app._feed`（真实 feeding 链：Need effect → Emotion → Memory → Life interrupt → DialogueBrain → Frame）。Trace 显示 `Food / Hunger before→after / Activity / Memory / Dialogue`。

---

## 9. Memory

`ObservationAdapter::memory_info` 显示行数；Trace 显示 retrieval count 与 used-by-dialogue。Persistence（重启）由现有 `MemoryStore` 保证（Phase 07/RC1 已测）。用户 `Scenario G` 验证"记录→检索→对话利用"。

---

## 10. Spatial Proxy

`SpatialProxyWindow` 暴露 `pos/set_position/width`，`DesktopSpatialRuntime(world, window=proxy)` 驱动。`Frame → SpatialIntentResolver → SpatialRuntime.accept/tick → proxy`。Approach/Maintain/Withdraw/Wander/Drag 均由真实 spatial 链（Phase 12 已全绿）。`test_proxy_drag_release_commits_position` 验证释放不 snap-back。

---

## 11. Agent / Office

Capabilities：以真实项目为准（AgentRuntime + ToolRegistry + Permission）。`on_agent("notepad"/"calc") → app._on_user_command`（真实 planner→permission→tool→result）；`organize-test` 只操作 `tmp/harness_agent_test/`。Tool 结果反馈经 DialogueBrain（非固定发一句）。

---

## 12. Failure Handling

LifeBrain / DialogueBrain / Memory / Agent 失败：Harness 记录 `FALLBACK`（badge 不假绿）。Failure injection 走 dependency injection（DEV TEST ONLY）。用户 `Scenario J` 验证系统仍活着。

---

## 13. Observability / Trace

Trace count / ring size（300，内存）/ secret audit（redact）/ 事件驱动（不落库）。`test_trace_redacts_secrets / ring_bounded / chain_shares_root / marks_fallback` 通过。

---

## 14. Performance

Harness off/on idle CPU、RAM、Trace buffer、UI stalls：待真实运行记录（目标无 runaway）。Truth panel 5Hz 刷新（§89）。

---

## 15. Narrow Wiring Exceptions

```
NONE
```
（本阶段未解冻后端语义；仅新增 harness/observability + InteractionEngine.emit_event 公共入口——该入口复用现有 `_apply` 生产路径，不改变语义。）

---

## 16. Regression（本段放在 REAL RUNTIME EVIDENCE 之后）

```
Previous: 380
New:      14 (test_runtime_harness.py)
Total:    394
Broken:   0
```

---

## 17. ASSET_DEBT

walk / drag / read / think：`KNOWN / CONFIRMED / DEFERRED / NOT PHASE13 BLOCKER`（见 docs/ASSET_DEBT.md）。
No asset work performed：YES。

---

## 18. Manual Functional Acceptance

见 docs/PHASE13_MANUAL_ACCEPTANCE.md（Scenario A-J + Persona）。**Agent 不代用户勾选。**

---

## 19. Weaknesses

- STRUCTURAL：Harness 的双线程 trace 关联为"每触发一个 root"，未做跨线程 parent/child 全链（后台 DialogueBrain 独立 root）；报告按 trigger 分组展示。
- WIRING：`IGNORE → interaction leave` 映射较弱（无独立 ignore 语义体系），属接受的窄处理。
- MODEL/PERSONA：真实 glm 人格判定待用户（PENDING）。
- PARAMETER：无调参（0 借机调参）。
- AGENT：能力以现状为准；organize-test 仅限 tmp 目录。
- HARNESS：UI 5Hz，Trace 事件驱动；无美术投入。
- ACCEPTED：assets 全部 DEFERRED。

---

## 20. Verdict

Technical: **PASS**。Real Trace: **PASS**。Manual: **PENDING**。Persona: **PENDING**。
Overall: **PASS-AUTO / MANUAL_FUNCTIONAL_PENDING**。
（≤5 句）Harness 以无素材方式证明真实子系统（Life/Dialogue/Interaction/Relationship/Memory/Feeding/Spatial/Agent/Failure）已接入统一 Runtime 并产生真实、脱敏、可观察的因果 trace；无第二 Runtime、观察只读。是否"真的像芙宁娜在电脑里生活"须由用户亲手验收（Scenario A-J + Persona），Agent 不代判。

---

## 21. Recommended Next Step

若 Manual Functional/PERSONA 尚未完成：**WAIT FOR USER FUNCTIONAL VERDICT**。
若用户发现具体功能断点：Phase 13 Functional Closeout 只修明确失败链（用 Trace 定位是 Expression/Prompt/Examples/Context/Memory/Validator/Model 哪层）。
若 Phase 13 Full PASS：Phase 14 —— Core Functional Product Closeout / Functional Freeze。**不开始素材制作。**
