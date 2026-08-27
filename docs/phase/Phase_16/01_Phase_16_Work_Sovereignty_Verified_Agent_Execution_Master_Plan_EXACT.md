# Phase 16 — Work Sovereignty & Verified Agent Execution
# MASTER PLAN — EXACT

Document path:

`docs/phase/Phase_16/01_Phase_16_Work_Sovereignty_Verified_Agent_Execution_Master_Plan_EXACT.md`

## 0. 文档协议（Document Protocol）

- 本文件是 Phase 16 **唯一权威执行计划**（master plan）；任务书（brief）、closeout、
  manifest 均从本计划派生，不得与本文冲突。
- 本文档只定义范围、边界、依赖、实施顺序与验收条件；**不构成对任何实现的授权**。
  每个实施单元（Delta）仍需要独立的、更窄的 task brief + 外部 reviewer PASS。
- 文档命名沿用 Phase 15 约定：`NN_Phase_16_<名>_<类型>_EXACT.md`；`_night_*` 前缀文件
  一律为 NON-AUTHORITATIVE（见 §3）。
- 状态措辞禁止 PASS；`READY_FOR_FINAL_REVIEW` 与 `PHASE_16_FINAL_GATE = PASS` 之判定权
  只在外部 reviewer。
- 本计划中的 "16 内只定义数据契约不写决策器" 为对 night 提案的笔误修正（原文 "15 内"）；
  night 文件保持原样，本计划以修正后语义为准。

## 1. 正式名称与目标（Formal Name & Goal）

正式名称：

```text
Phase 16 — Work Sovereignty & Verified Agent Execution
```

目标（一句话）：让 Furina 在**用户意愿之外**、由 Furina 自身主权接单（WorkContract），
通过**通用 backend 协议 + 首个 Hermes 适配器**执行任务，并对执行结果做**独立校验**
后，才以 `COMPLETED_VERIFIED` 写入 C7 —— 全链路禁止 backend 自证完成、禁止越权记忆、
禁止抢占用户可见语音。

本阶段不做（归属后续阶段，见 §16）：

- 意愿/拒绝决策器（willingness decision engine）→ Phase 17 Character Agency
- backend 选择策略（哪家 backend 由 Furina 主动选定）→ Phase 17
- 渲染/身体/TTS/ASR/桌面宠物体 → Phase 20 Embodiment（严格排除，见 §15）

## 2. Frozen Baseline & Branch Protocol

```text
PHASE15_FROZEN_SHA = 6d9b30d79d64e5ea566fcb2a0fd5a46276a8139e
```

- baseline 确认：`git rev-parse HEAD` == 6d9b30d… == remote
  `refs/heads/feature/phase15-cognitive-life-finalization`（Phase 15 integration line）。
- Phase 16 canonical integration branch（本计划实施线）：

```text
feature/phase16-work-sovereignty        （自 6d9b30d 切出）
```

- 每个实施单元使用 task-specific 分支，自**最新被接受的 Phase 16 integration SHA**
  切出，命名建议 `feature/phase16-d<NN>-<名>`（Delta 是实现顺序标签，不是新 Phase 号）。
- Sequential base rule（同 Phase 15 §2.3）：

```text
task branch → implementation → tests → external reviewer PASS
→ fast-forward / integrate into feature/phase16-work-sovereignty
→ 下一个 task 从新的 accepted integration SHA 切出
```

- Phase 15 未宣告 PASS（仅 READY_FOR_FINAL_REVIEW）不影响本计划落盘；但**正式 D1 实施
  以外部 reviewer 签发 PHASE_15_FINAL_GATE = PASS 为前提**。

## 3. 输入来源（Sources）—— 权威 / 非权威

权威输入（canonical，实施引用以此为准）：

```text
Phase 14 final closeout（R6–R12 + R7-FC/R10-FC）→ C1–C7 语义冻结
Phase 15 master plan（03_...）→ 阶段边界、night policy、分支协议
Phase 15 integrated final closeout（15_...）→ 冻结状态、Gate A–H、deferred P17 项
C7 / C6 / Permission 现状代码（见 §4 逐项代码证据）
```

NON-AUTHORITATIVE design inputs（night 提案，仅作设计输入；**不直接声明为 canonical**）：

```text
docs/phase/Phase_16/_night_external_recon_raw.md           外部六仓源码审计（PART B/C）
docs/phase/Phase_16/_night_phase16_architecture_preflight.md  16A–16I 逐节裁定（PART D）
docs/phase/Phase_16/_night_phase16_authority_redteam.md       10 条主权不变量（PART E）
```

以上三份 night 文件的结论须经本 master plan 复核后**逐条转正或否决**；任何未转正的
建议不得进入 task brief。

## 4. 现状核查（Verified Facts，代码证据）

实施前必须读取并在 brief 中引用以下真实接口（本文档已核对）：

### 4.1 C7 — Agent Task History（COMPLETED_VERIFIED 已存在）

```text
furina/cognition/stores/agent_history.py:20
    TASK_STATUSES = ("PLANNED","RUNNING","COMPLETED_VERIFIED","FAILED","UNVERIFIED","CANCELLED")
agent_history.py:65  complete_task(verified=True → COMPLETED_VERIFIED；False → UNVERIFIED)
agent_history.py:53  终态（COMPLETED_VERIFIED/FAILED/UNVERIFIED/CANCELLED）写入 finished_at
furina/cognition/hub.py:607  persist_agent_result(...) —— C7 唯一 owner 写入路径（owner 线程，
                             worker 不直接写 Cognition DB；status 精确保留，hub.py:639）
furina/app.py:950-975  dispatcher：worker task_record → owner persist_agent_result →
                       按 status 写 C6 AGENT_COMPLETED / AGENT_FAILED（provenance 已接线）
furina/agent/agent_runtime.py:308  _verify 全局硬门：res.ok AND res.verified 才算已验证
```

结论：`COMPLETED_VERIFIED` **已是真实定义**（store 枚举 + owner 写入 + C6 provenance
现网使用），Phase 16 **不得重造状态名**，只能复用/扩展。见 §12。

C7 schema（`furina/cognition/stores/base.py:63` agent_tasks DDL：task_id PK /
original_request / goal / status / started_at / finished_at / permission_summary /
plan_json / verified / result_summary / error）**无 contract 维度**；Phase 16 默认
**不修改** C1-C7 schema / enum / writer（冻结边界见 §4.5）。

### 4.2 C6 — Event Timeline

```text
furina/cognition/stores/event_timeline.py:46  append(event_type, payload, source, actor,
                                               channel, turn_id, task_id, importance) → LifeEvent
event_timeline.py:131  register_event_type（新事件类型需注册，否则落 SYSTEM_EVENT）
furina/cognition/hub.py:210  record_event(...) —— owner 线程便捷入口；返回 event_id，
                             UserModel upsert 的 source_event_id 证据链使用
```

结论：C6 是客观 append-only 真值；Phase 16 的 verified 事件（如 AGENT_VERIFIED）走
`register_event_type` + `record_event`，保持 single-owner 线程。

### 4.3 Permission / Approval —— approval 概念当前不存在

```text
furina/agent/permission.py
    Permission: L0_READ / L1_LOW_WRITE / L2_HIGH_RISK / L3_SENSITIVE
    PermissionManager.check(...) —— 同步判定；L0/L1 自动放行；L2/L3 需 task-scoped
                                   AuthorizationContext 或显式确认
    EffectivePermissionResolver.effective_permission(tool, args)
```

结论：代码库**没有** `approval.request` / WAITING_PERMISSION / resolve 等异步审批概念。
Phase 16 的 16D 是**新增一等审批通道**，内层建在现有 PermissionManager 之上，外层建在
WorkContract 之上；不得替换现有同步权限判定（L2/L3 语义继续生效）。

### 4.4 现有 Agent / Backend 接口（Native 基线）

```text
furina/agent/agent_runtime.py  AgentRuntime.execute(user_request, extra_context, task_auth)
                               → 结构化 task_record（status/verified/steps/artifacts/plan）
furina/agent/tools/            Native 工具栈（ToolRegistry / ToolResult(ok, verified, ...)）
furina/agent/capabilities/registry.py  Capability Registry
furina/agent/planner_v2.py     Planner V2 + deterministic fallback
```

结论：16B 的 Native backend 实现 = 上述现有栈的适配器封装，**不改动**其内部执行语义。

### 4.5 Work Execution 独立工作域（Work Domain）—— 不属于 C1-C7

锁定声明（reviewer patch 硬化）：

```text
1. WorkContract / Execution 是独立工作域（work domain），不属于 C1-C7 cognition stores；
   C7（agent_tasks/agent_task_steps/agent_artifacts）仍是 cognition 侧冻结真值。
2. 默认不得修改 C1-C7 schema / enum / writer；工作域的一切状态与契约对象
   （contract_id、run_id、WorkExecutionState）存在于工作域 ledger 中，不落 C7。
3. 工作域不是 Persona / Memory / Relationship 的 truth 来源：C1（canon_identity）、
   C4（user_model）、C5（relationship）真值依旧只由既有 owner 产生，工作域数据
   不得成为或伪装成这些 truth（G-S2 哨兵延续）。
4. contract_id ↔ C7 使用 binding/provenance 关联（非 C7 列）：
   - 工作域 ledger 持有 contract_id ↔ task_id ↔ run_id 绑定；
   - C6 事件（register_event_type + record_event）payload 携带 contract_id + task_id
     作为 provenance 证据链（C7 行身份仍是 task_id，不变）；
   - 已核验：C7 DDL 无 contract 列（base.py:63），cognition 全层无 contract 概念，
     当前代码**不要求** schema 变更即可实现该绑定。
5. 若任一 Delta 的实施被代码证明**必须**改 C7 schema/enum/writer →
   标记 `FROZEN_CONTRACT_EXCEPTION_REQUIRED`，且 16G 在外部 reviewer 批准前
   **BLOCKED**（不实现、不合并）；批准路径见 §5A / §17。
```

## 5. 范围总表（16A–16I：范围、依赖、实施顺序）

| ID | 组件 | 范围（一句话） | 关键依赖 | 顺序 |
|---|---|---|---|---|
| 16A | Work Sovereignty Contract | WorkContract 数据契约（不含 willingness decision） | 无（先行定义词汇表） | 1 |
| 16B | ExecutionBackend Protocol | 通用 backend 协议 + 注册表（registry/run 两正交面 SPLIT） | 16A | 2 |
| 16D | Permission Boundary | 外层 WorkContract 批准 + 内层 tool approval（一等事件） | 16A, 16B | 3 |
| 16E | Backend Event Normalization | backend 事件/状态归一词汇表（对齐 hermes 词表） | 16B | 4 |
| 16C | Hermes Capability Probe + Runs Adapter | 首个 adapter（probe/submit/SSE/stop/approval 转发） | 16B, 16D, 16E | 5 |
| 16F | Independent Verification + Repair | 独立校验 + bounded repair loop | 16E, 16C（证据通道） | 6 |
| 16G | C7/C6 Integration | verified → C7 COMPLETED_VERIFIED；C6 provenance；C3 默认关 | 16F, 16E | 7 |
| 16H | Cancellation/Crash/Restart/Idempotency | UNKNOWN 恢复、contract_id 幂等、TOOL 背压 | 16G（幂等键落 C7） | 8 |
| 16I | Integrated Work Sovereignty Gate | G-S1 Single Mouth、G-S2 隔离哨兵、整体 Gate | 16A–16H | 9 |

依赖原则：只允许**正向依赖**（低序号被高序号依赖），禁止反向依赖导致返工。

锁定实施顺序（Delta 顺序）：

```text
16A → 16B → 16D → 16E → 16C → 16F → 16G → 16H → 16I
```

每步独立 brief + 外部 reviewer PASS 后才能从更新后的 integration SHA 切下一个 Delta。

## 5A. WorkExecutionState / C7 AgentTaskStatus 分离（两套状态机）

锁定声明（reviewer patch 硬化）：Phase 16 引入 **两个相互独立的生命周期状态机**，
禁止混用、禁止互相写入。

```text
WorkExecutionState（工作域，16E/16H 拥有，非 C7）：
    IDLE / STARTING / RUNNING / WAITING_PERMISSION / BLOCKED_APPROVAL /
    TOOL_RUNNING(子相位) / VERIFYING / REPAIRING / CANCELLING / CANCELLED /
    BACKEND_DONE_UNVERIFIED / VERIFIED / FAILED / UNKNOWN

frozen C7 AgentTaskStatus（cognition 冻结六态，agent_history.py:20）：
    PLANNED / RUNNING / COMPLETED_VERIFIED / FAILED / UNVERIFIED / CANCELLED
```

禁写清单（must NOT be written into C7）：

```text
UNKNOWN / BLOCKED_APPROVAL / VERIFYING / REPAIRING / BACKEND_DONE_UNVERIFIED
```

- 上述工作域状态**不得**出现在 `agent_tasks.status` / `agent_task_steps.status`；
  它们只存在于工作域 ledger 与 C6 事件流；
- 工作域 → C7 的唯一合法晋升：16F 验证通过 → 经既有唯一 owner
  `hub.persist_agent_result` 写 `COMPLETED_VERIFIED`（或如实落 FAILED / UNVERIFIED）；
- 16E 归一层（backend 词表 → WorkExecutionState）只产出工作域状态；
  C7 映射只发生在 16G 的终态折算，且仅限六态。

## 6. 技术路由 / Phase 17 意愿决策边界

```text
Phase 16（本阶段，技术路由）：
  - 通用 ExecutionBackend 协议 + 注册表（安装态/健康态/能力探测）
  - Hermes 作为第一个 backend adapter（16C）
  - WorkContract 数据契约 + 拒绝/接单的"时机"纪律（backend 句柄只在 contract signed 后创建）
  - 独立校验 / C7 写入 / 幂等 / 恢复（全部确定性与规则面）

Phase 17（后续，Character Agency / Work Willingness 正式行为）：
  - willingness 判定（Furina 是否愿意接单 / 拒绝 / 罢工）
  - backend 选择策略（依据 16B 的能力探测数据做 agency 级路由）
  - 关系气候 → 行为策略（Phase 15 closeout 已永久延后的 P17-D2）
```

边界铁律：

1. **WorkContract 不包含 willingness decision**（见 §7 字段表）；
2. Phase 16 的拒绝只发生在**机制层**（无审批通道 / 能力缺失 / contract 违约），
   不实现"Furina 主观不愿意"的决策器；
3. Phase 16 提供 backend 能力探测数据（16B registry + 16C probe），**不做**"选谁"的
   agency 判定；
4. Phase 16 新工作域（§4.5）不属于 C1-C7 cognition stores；其任何数据
   **不得成为 Persona / Memory / Relationship 的 truth**（C1/C4/C5 真值依旧只由
   既有 owner 产生；G-S2 哨兵延续）。

## 7. 16A — Work Sovereignty Contract（数据契约）

WorkContract 是 Phase 16 唯一原创核心（FURINA-NATIVE，外部六仓均无此语义；见
`_night_external_recon_raw.md` §1/§8）。**本阶段只定义数据契约，不写决策器**
（"16 内只定义数据契约不写决策器"——night 提案笔误修正版）。

锁定字段：

```text
canonical_user_request   用户原始请求原文（canonical U 链，含 source_event_id）
commitment_scope         Furina 承诺范围声明（可完成/不承诺项）
time_budget              时间预算
allowed_backends         允许后端集合（从 16B registry 约束）
verification_standard    验证标准占位（16F 实施后填实）
grant_permanent          approval 永久授权显式开关（默认 false，见 16D）
contract_id              稳定幂等键（16H 使用；与 C7 经 binding/provenance 关联，
                        见 §4.5 —— 工作域 ledger + C6 事件链，**不新增 C7 列**）
```

不含（禁止出现）：willingness 评分、拒绝理由生成、backend 偏好、情绪/亲密度。

## 8. 16B / 16C — 通用 Backend 协议 + Hermes 首适配器

### 16B ExecutionBackend Protocol（SPLIT 两正交面）

```text
注册表面（静态能力/安装态）   —— 借鉴 CoPet AgentAdapter trait 范式：
    is_installed / install / uninstall / health（注意：installed != healthy）
运行协议面（run 面）          —— 最小协议面：
    probe() / submit(contract) / events() / stop(id)
```

- Native backend = Phase 14 本地 Agent 工具栈的适配器封装（§4.4），复用
  `AgentRuntime.execute` 语义；
- MCP backend → **DEFER**（16B v2），本轮不实施；
- 注册表与运行协议必须分文件/分模块，禁止把"已安装"当"可用健康"。

### 16C Hermes Capability Probe + Runs Adapter（首个 adapter）

- Probe：以 `/v1/capabilities` 的 features 布尔面为源 + 客户端 TTL 缓存 + null 降级；
  probe 结果必须记录 **approval 能力缺失时的拒绝策略**（无审批通道即不允许接危险级
  WorkContract，禁止静默 fallback——HD 反例）。
- Runs：`submit → 202 + run_id → SSE(events) → stop/approval resolve`。
- **approval.request 一等公民化**：挂起 run → 向 Furina 外层转发 → 保留 SSE 余流；
  **禁止**复刻 HD 的 `stopAndFallback` 抢话路径（§14 G-S1）。
- approval choices：默认剔除 `always/permanent`（除非 `contract.grant_permanent=true`）。

### Hermes Interface Decision（reviewer patch 锁定，不允许 task brief 回退）

```text
API Server primary       适配器主通道 = hermes HTTP API Server（POST /v1/runs + SSE）
                         只有 API Server 具备 run 生命周期 / approval 一等事件能力
CLI probe/fallback       hermes CLI 仅用于能力探测（probe）与降级回退，不作为 run 通道
webhook trigger-only     webhook 仅作触发信号（trigger-only），不是执行/结果通道，
                         不承载 UNVERIFIED→VERIFIED 语义
hermes proxy NOT_BACKEND 任何 "hermes proxy" 形态一律不算 backend：不进入 registry、
                         不接 WorkContract、不参与 probe 健康面
Plugin/MCP restricted    Plugin / MCP 通道受限：MCP 细则 DEFER（16B v2）；
                         Phase 16 不得把 plugin/MCP 当一等执行通道
capability probe         一切接口选择以 /v1/capabilities feature 布尔面为源头
                         （run_submission / run_status / run_events_sse / run_stop /
                         approval_response / …）；缺失能力 → 拒绝对应 contract 等级
no always-approve        approval choices 默认剔除 always/permanent；仅当
                         contract.grant_permanent=true 才可透传
output always UNVERIFIED backend 任何输出（含 completed）一律折算为
                         BACKEND_DONE_UNVERIFIED；VERIFIED 只由 16F 校验器产出
Single Mouth             backend 用户可见文本 = 素材；经 Furina 嘴部仲裁输出（G-S1）
```

## 9. 16D — Permission Boundary（双层）

```text
外层 = Furina 主权：用户 → Furina 的 WorkContract 批准（16A）
内层 = Hermes/backend 执行审批：工具调用粒度 once / session / deny（禁 always 自动上浮）
```

- 内层审批**不可扩大**外层范围；权限被拒必须回灌为 contract 违约事件（不吞掉）；
- 状态命名统一：`WAITING_PERMISSION` 明确对应 hermes `waiting_for_approval`（映射见 16E），
  禁止双词混用；
- 新增一等事件与状态机转移：submit → WAITING_PERMISSION → resolve(approve/deny/timeout)；
  timeout 语义在 16H 定义；
- 现有 `PermissionManager`（L0–L3 同步判定）继续生效，16D 只在其上增加异步审批通道，
  **不替换**。

## 10. 16E — Backend Event Normalization

对齐 hermes `_set_run_status` 真实词表（queued/running/waiting_for_approval/stopping/
completed/cancelled/failed + SSE done 哨兵）：

```text
IDLE                     本地抽象（backend 未开工）
STARTING                 ← queued（含 pre-start stop 短路）
RUNNING                  ← running
WAITING_PERMISSION       ← waiting_for_approval（词表对齐）
TOOL_RUNNING             ← 子相位标志（非 status；由 tool.started/进度事件驱动）
VERIFYING                本地态（进入 16F 校验器时设置）
CANCELLING               ← stopping（stop 已发、终态未至；用户可见口径 = 正在停止）
CANCELLED / FAILED       ← cancelled / failed（直接透传）
BACKEND_DONE_UNVERIFIED  ← completed 折算（我方原创；防"完成"越权）
VERIFIED                 16F 出口唯一合法晋升
```

TOOL 高频事件背压采纳 CLAWD 有界队列 + CRITICAL_EVENTS 思想（terminal 事件永不丢弃）。

以上全部是**工作域状态**（WorkExecutionState，见 §5A）；除 16G 终态折算（六态）外，
**任何一项都不得写入 C7**。

## 11. 16F — Independent Verification + Bounded Repair

- backend 说 completed ≡ `BACKEND_DONE_UNVERIFIED`，**绝不**自动 VERIFIED；
- 校验器三段式：evidence 收集（工件 + 终态事件 + 本地复查点）→ Furina verifier
  （deterministic 规则先行）→ VERIFIED / FAILED；
- repair loop（bounded）：失败 → 局部重试策略由 contract 声明；无限重试禁止；
- 证据接收通道形状（size/TTL/mime 白名单）可 TAKE 自 hermes artifacts API，但**只做
  运输**，不改变校验真值来源。

## 12. 16G — C7 Single Owner / C6 Provenance / C3 默认关

```text
verified → C7：仅经 hub.persist_agent_result（唯一 owner）写入 COMPLETED_VERIFIED
              （复用 §4.1 既有枚举与 owner 路径，禁止新增旁路）
C6：verifier 的 VERIFIED/FAILED 结论以 register_event_type + record_event 落客观事件
    （如 AGENT_VERIFIED），payload 携带 contract_id / task_id 证据链
C3：自动写入默认关闭 —— backend 完成 ≠ 成功记忆；成功记忆形成仍走 MemoryEngine
    权威路径（可选采样源，默认 OFF，需任务书显式开启）
```

16G 冻结纪律（reviewer patch 硬化）：

```text
- C7 只接收 frozen 六态终态（§5A）；工作域状态（UNKNOWN/BLOCKED_APPROVAL/VERIFYING/
  REPAIRING/BACKEND_DONE_UNVERIFIED）一律不写入 C7；
- contract_id ↔ C7 走工作域 ledger 绑定 + C6 provenance 事件链（§4.5），不新增 C7 列、
  不改 C7 行身份；
- 默认不改 C1-C7 schema / enum / writer；若实施证明必须改 → 标记
  FROZEN_CONTRACT_EXCEPTION_REQUIRED，16G 在外部 reviewer 批准前 BLOCKED。
```

## 13. 16H — Cancellation / Crash / Restart / Idempotency

```text
UNKNOWN recovery：重启后发现的历史 in-flight run 一律判 **WorkExecutionState=UNKNOWN**
    （工作域状态，§5A；**不得写入 C7**）→ verify-on-recovery（先查证再改状态；禁止
    直接标 FAILED；期间禁止新增同 contract 任务）；**只有验证通过才经既有唯一 owner
    hub.persist_agent_result 写 COMPLETED_VERIFIED**（§4.1 owner 路径，无旁路）
contract_id 幂等：以 contract_id 为 durable 幂等键，存于**工作域 ledger**
    （contract_id ↔ task_id ↔ run_id 绑定，§4.5，不新增 C7 列）；submit 前查重；
    对"同 WorkContract 重试双跑"必须拒绝或接管（hermes 头照发但不依赖）
CANCELLING：对外可见口径 = 正在停止；收到终态事件才落 CANCELLED/FAILED；
    超时升级策略显式化（超时补丁 → FAILED 候选）
TOOL 背压：bounded queue + critical 事件永不丢弃（§10）
```

## 14. 16I — Integrated Gate：G-S1 / G-S2

```text
G-S1 Single Mouth：backend 产生的用户可见文本一律作为"素材"，经 Furina 嘴部仲裁输出；
    仲裁独占期与 DirectDialogueQueue owner 一致；run 流式期间用户输入进 direct lane 排队，
    禁止 backend 旁路输出（HD 抢话为其反例）。
G-S2 SOUL/Memory 隔离哨兵：接入期断言 backend 配置不含 SOUL/人格文件写入路径、不桥接
    backend 记忆栈；Persona 编译只读 furina/persona/*；C4 upsert 仅经 hub
    require_source_event 门 + canonical U；hermes 叙述性内容至多作候选文本，
    无 source_event_ids 则 fail-closed。
```

16I 是 Phase 16 集成终门；各 Delta 还需自己的 Gate（同 Phase 15 Gate A–H 模式）。

## 15. Phase 20 Embodiment 排除边界（严格排除）

本阶段**不得**包含：

```text
renderer / 桌面宠物身体（body）/ sprite / 动画 / 透明窗口
TTS / ASR / wake word / 语音通道
visual assets / 表情渲染
```

G-S1 是**数据流仲裁门**（谁有权对用户说话），不是渲染层实现；G-S2 是装配期断言。
任何需要 UI/渲染/语音的产出都属于 Phase 20 Embodiment / Phase 21 Art / Phase 22
Voice-Interaction（Phase 15 audit brief §12 LATER 清单），禁止在 Phase 16 越界。

## 16. 明确排除 / 不做什么（Out of Scope）

```text
willingness / 拒绝 / 罢工决策器                     → Phase 17
backend 选择策略（Furina agency 级路由）            → Phase 17
关系气候 → 行为策略                                 → Phase 17（closeout 永久延后 P17-D2）
MCP backend 细则                                    → 16B v2（本阶段 DEFER）
subagent 编排                                       → 后续
MiniCPM sidecar / 离线 provider 形态                → LATER
重做 C1–C7 / Memory / UserModel / Canon / Retrieval → 冻结区（COGNITIVE_LIFE §15）
T4 移回 Phase 15 或打开已关闭 Phase 15 项           → 禁止
UI / 渲染 / 语音 / 桌面体                            → Phase 20+
复制外部代码进 Furina（含 night 审计六仓）           → 禁止（TAKE 只取范式与词表）
```

## 17. 已确认契约缺口（Contract Gaps，如实登记）

```text
GAP-1   approval 通道不存在：代码库无 approval.request/WAITING_PERMISSION/resolve；
        16D 必须新增一等审批通道，且不得绕过现有 PermissionManager 同步判定。
GAP-2   C7 CANCELLED 枚举存在但 AgentRuntime 无取消路径产出它；16H 的取消语义必须
        补上从 CANCELLING → CANCELLED 的真实转移（非仅状态名）。
GAP-3   WorkContract / contract_id 不存在：全新契约对象，属于工作域（§4.5）。
        已核验：C7 DDL（base.py:63）无 contract 列，binding/provenance 方案
        （工作域 ledger + C6 事件链）**不要求** C7 schema 变更；若任一 Delta 实施
        被代码证明必须改 C7 → 标记 `FROZEN_CONTRACT_EXCEPTION_REQUIRED`，16G 在
        外部 reviewer 批准前 BLOCKED（不实现、不合并）。
GAP-4   backend 事件归一不存在：16E 是新层；hermes 词表只作映射目标，不搬运实现。
GAP-5   独立验证只到 step 级（_verify）；16F 的任务级独立校验是扩展，不是重构。
GAP-6   UNKNOWN 状态与 verify-on-recovery 不存在：16H 新增，且须与 C7 现有状态机兼容。
```

`COMPLETED_VERIFIED` 本身**不是**缺口（§4.1 已存在真实定义），16G 直接引用。

## 18. 拒绝清单（Rejected Mechanisms，源自 night recon §10，转正为本计划红线）

```text
"Hermes SOUL = Furina 人格"（Furinelle SOUL.md）             → C1 隔离红线，G-S2 检查项
mnemosyne 角色长期记忆仓 + intimacy 0-10 + 告白阶段          → C3/C4/C5 三连违规
approval 'always/permanent' 常规直通                        → 外层未批的永续授权，默认禁用
legacy-chat 抢话 fallback（approval.request→stopAndFallback）→ G-S1 违反实例，禁止复刻
run.completed 当真值                                        → BACKEND_DONE_UNVERIFIED 折算强制
doc-only 状态机叙事（FA approve/verify/repair 词条）        → 无代码，不采信不搬词
MiniCPM 并入计分                                            → DERIVED fork，去重
```

## 19. 遗留问题（Unresolved，留给后续任务书）

```text
1. hermes upstream 是否出现 split-runtime / artifact-verify 演进（跟踪，不影响本计划）
2. approval.request 长任务挂起时长 / 超时语义（16H 任务书须定标）
3. subagent（delegation）是否作为并行工作源（16G 可选采样，默认不纳入）
4. hermes-desktop license 缺失是否补齐（本轮零代码复制，引用边界已受控）
5. 后端事件类型注册表放哪（C6 register_event_type vs 16E 新层）——16E 任务书裁决
```

## 20. 最终验收条件（Phase 16 Final Gate 候选清单）

```text
G-1   sovereign refusal：用户请 Furina 做事但（机制层）拒绝 → backend 调用次数 == 0
G-2   backend completed 不自动 VERIFIED：注入伪造 run.completed → C7 无 COMPLETED_VERIFIED
G-3   hermes 记忆/人格不得改 C4/C1：G-S2 装配期断言 + C4 require_source_event 门
G-4   内层审批不得扩大外层范围：hermes always → 适配器降级 once 或拒收
G-5   CANCELLING 可见状态保持至终态事件：屏蔽 cancelled 事件时状态不提前落终
G-6   崩溃恢复：重启 → UNKNOWN → verify-on-recovery → VERIFIED/FAILED
G-7   Single Mouth：run 流式期间 backend 文本不旁路用户对话
G-8   C7 写入单 owner：无 persist_agent_result 之外的 COMPLETED_VERIFIED 写入路径
G-9   contract_id 幂等：同 contract 重复 submit 拒绝或接管，不双跑
G-10  Phase 15 冻结区零改动：C1–C7/Memory/UserModel/Canon/Retrieval 未触碰
G-11  C7 schema/enum/writer 零改动（或经 FROZEN_CONTRACT_EXCEPTION_REQUIRED
      + 外部 reviewer 批准）；工作域状态（UNKNOWN/BLOCKED_APPROVAL/VERIFYING/
      REPAIRING/BACKEND_DONE_UNVERIFIED）零泄漏进 C7
G-12  工作域数据不成为 Persona/Memory/Relationship truth（C1/C4/C5 真值 owner 未变）
```

## 21. Next Document

下一份文档：`02_Phase_16_<首个 Delta>_Task_Brief_EXACT.md`（Delta 顺序见 §5），
必须单独、窄幅编写，禁止合并多个 Delta 成一个巨型任务。

## 22. Revision（Reviewer Patch）

本版为 Master Plan reviewer document patch（docs only，零生产代码/测试/migration）。

```text
新增 §4.5   Work Execution 独立工作域：非 C1-C7；默认不改 C1-C7 schema/enum/writer；
            contract_id↔C7 走 binding/provenance（工作域 ledger + C6 事件链）；
            若必须改 C7 → FROZEN_CONTRACT_EXCEPTION_REQUIRED + 16G BLOCKED
新增 §5A    WorkExecutionState / C7 AgentTaskStatus 两套状态机分离；
            UNKNOWN/BLOCKED_APPROVAL/VERIFYING/REPAIRING/BACKEND_DONE_UNVERIFIED
            禁写 C7；VERIFIED 仅经既有唯一 owner 晋升 COMPLETED_VERIFIED
§6 边界铁律 4   新工作域不得成为 Persona/Memory/Relationship truth
§8 16C      Hermes Interface Decision 锁定：API Server primary；CLI probe/fallback；
            webhook trigger-only；hermes proxy NOT_BACKEND；Plugin/MCP restricted；
            capability probe；no always-approve；output always UNVERIFIED；Single Mouth
§10         16E 全部状态 = 工作域状态，除 16G 终态折算外不写 C7
§12 16G     16G 冻结纪律（C7 只收六态终态；FROZEN_CONTRACT_EXCEPTION_REQUIRED 门）
§13 16H     UNKNOWN 为工作域状态；verify-on-recovery 仅经唯一 owner 写
            COMPLETED_VERIFIED；幂等键存工作域 ledger（不新增 C7 列）
§17 GAP-3   修正：binding/provenance 方案不需 C7 schema 变更（base.py:63 已核验）；
            若被证明必须改 → FROZEN_CONTRACT_EXCEPTION_REQUIRED + 16G BLOCKED
§20         +G-11（C7 零改动/例外批准 + 工作域状态零泄漏）、G-12（不成为 truth）
```

冻结异常标记（当前状态）：`FROZEN_CONTRACT_EXCEPTION_REQUIRED = NOT_REQUIRED`
（基于 base.py:63 DDL 现状核验；若未来 Delta 反证，须回填为 REQUIRED 并 BLOCK 16G）。
