# Universal Agent Architecture（Phase 14 正式版）

> STATUS = IMPLEMENTED（furina/agent/capabilities/ + Planner V2 + tools expansion）
> 前身：docs/architecture/future/UNIVERSAL_AGENT.md（PLANNED reservation，已升级为本正式文档的 redirect）。

本文档是 Universal Agent 层的**唯一架构契约**：Goal → Plan → Permission → Execute → Verify → Report
管线、Capability Registry、Planner V2、ToolResult 契约、Application Catalog、Communication/Calendar
接口、Work Willingness 预留（model-only）。

## 0. 设计原则

1. **不是 LLM 直接控制电脑**：LLM 只产 Goal/Plan（steps/tool/args/expect），**不能执行工具**。
2. **ok != verified**：`ToolResult.ok` 只是"没抛错"；`verified` 必须来自真实可观察结果
   （filesystem truth / 进程观察 / 重新打开验证）。
3. **Unavailable ≠ 假实现**：capability 不可用必须 `available=false, reason=provider_not_configured`；
   provider 缺失时**绝不 fake success**。
4. **未知 app 不猜**：Application Catalog 只在真实 discover 到时返回可启动 target；
   禁止"未知应用 → 猜一个 executable"；禁止 shell 执行用户任意字符串。
5. **确定性 fallback**：LLM 不可用时，旧 deterministic 能力（记事本/计算器/整理目录）仍工作。
6. **Perception 只读**：browser/desktop 感知全部 L0 read-only；无稳定 DOM/control provider 时标
   browser DOM automation = unavailable。

## 1. Capability Registry

`furina/agent/capabilities/registry.py` + `models.py`。

`Capability` 定义：

```
capability_id
domain            # FILESYSTEM / DOCUMENTS / APPLICATIONS / BROWSER / DESKTOP /
                  # COMMUNICATION / CALENDAR / RESEARCH
description
tools[]           # 该 capability 提供的 tool name 列表
read_only         # bool
default_permission# Permission
requirements      # 依赖说明
available         # bool
availability_reason  # 如 provider_not_configured
```

规则：
- Unavailable capability 必须明确 `available=false` + `availability_reason`。
- **禁止用假实现"凑齐"** domain；本 Phase 不要求所有 domain 都可执行。
- Registry 可从 ToolRegistry 注册的工具自动生成 + 手工声明（provider 类能力）。

## 2. Planner V2

`furina/agent/planner_v2.py`（或 planner.py 内升级）。

目标：用户请求 + Capability Registry + Tool schemas + safe context → structured `AgentPlan`。

**LLM 只能产生**：`goal / steps[{tool, args, expect}]` —— 不执行工具。

**Deterministic validation（LLM 输出必须全部通过）**：
- tool exists（在 ToolRegistry 中注册）；
- capability available（`available=true`，否则 plan invalid / unable）；
- required args 齐全；
- max steps 上限（有界）；
- permission admissible（步骤权限 ≤ 当前许可域）；
- path validation（允许的路径范围；delete/overwrite 不默认出现在普通计划）；
- no unknown fields where unsafe。

规划结果引用**未知 tool** → plan invalid / unable（**不能自动替换**成看起来类似的 tool）。

**Deterministic fallback**（LLM 不可用/失败时保持既有确定性能力）：
- 打开记事本 / 打开计算器 / 整理目录 —— 走旧 heuristic（Planner 既有路径），不依赖 LLM availability。

Planner V2 使用项目**现有 LLM adapter**（`furina/llm/` registry + `LLMAdapter.structured`），
**不新造独立模型配置**。

## 3. Permission 模型（保持既有四档）

```
L0_READ       只读
L1_LOW_WRITE  低风险写入
L2_HIGH_RISK  高风险（需确认）
L3_SENSITIVE  敏感（必须确认）
```

既有 `furina/agent/permission.py` 的 `PermissionManager` 保持为唯一裁决入口。

## 4. Filesystem Capability Expansion（Phase 14D）

在既有 `fs.list_dir / fs.make_dirs / fs.read_file / fs.organize` 之上增加真实 primitives：

```
fs.exists       L0
fs.stat         L0
fs.search       L0
fs.create_file  L1（显式用户选择目标）
fs.write_text   L1（显式目标）/ 覆盖已有 → 至少 L2（非 silent）
fs.append_text  L1
fs.replace_text L1/L2（编辑已有文件）
fs.copy         L1/L2（按 destructive 性）
fs.move         L1/L2
fs.rename       L1/L2
fs.create_dir   L1
fs.open_path    L0/L1
fs.delete       可选；L2 默认，必要时 L3；**不默认出现在普通计划**
```

- 写入防误覆盖：`write_text` 支持 `expected_old_hash` 或 `overwrite=false`（至少一种）。
- **禁止 silent overwrite**。
- `ToolResult` 必须含 `ok / verified / data / error`；verified 必须读取 filesystem truth
  （写后读回验证），不能"函数没报错=verified"。

## 5. Document Capability（Phase 14E）

`furina/agent/capabilities/documents/`：

- **TXT / Markdown**（优先）：create / read / write / append / edit（真实落盘）。
- **DOCX**（python-docx）：创建文档、标题、段落、简单列表、保存、**重新打开验证**段落内容。
- **PPTX**（python-pptx）：创建 presentation、title/content slides、保存、**重新打开验证 slide count**。
- **XLSX**（openpyxl）：创建 workbook、写二维数据、保存、**重新打开验证 cell values**。
- **PDF**：本 Phase 只允许 read/extract foundation 或标 unavailable；不引重型不稳定方案凑能力。

依赖（python-docx / python-pptx / openpyxl）正式加入 `requirements.txt`，并必须有 import/build tests。
输出必须返回**真实 artifact path**，进入 Agent Task History（C7）。

## 6. Application Catalog（Phase 14F）

`furina/agent/capabilities/applications/`：

发现来源（真实 discover，不猜）：
- 已知 safe aliases；
- PATH executables；
- Windows Start Menu shortcuts；
- App Paths registry（`HKCU/HKLM\...\App Paths`）；
- 常见 Office installed paths。

`ApplicationRecord`：`app_id / display_name / aliases / launch_target / process_names / source / confidence`。

目标：`resolve("Word") / resolve("VS Code") / resolve("微信") / resolve("钉钉") / resolve("Spotify") ...`。
规则：
- 只在真实 discover 到 launch target 时返回可启动项；
- **未知 app → 不猜 executable**；返回 unable（reviewer-locked：XYZABC → 不得启动 notepad）；
- 禁止 shell 执行用户任意字符串（只 launch 解析后的 target 路径/可执行名）。

launch：`resolve → execute → observe real process/window → verified`；
启动 target 存在但**不能 verify** → `UNVERIFIED`（不得 `COMPLETED`）。

## 7. Browser / Desktop Foundation（Phase 14G）

不造完整 browser automation framework；把现有 Browser/Desktop tools 纳入 Capability Registry。

至少可靠实现（全部 read-only L0）：
- `browser.open_url`（按现有设计支持）；
- `browser.search_web`（若现有设计支持）；
- `computer.screenshot`；
- `desktop.active_window`；
- `desktop.list_windows`。

无稳定 browser DOM/control provider → `browser DOM automation = unavailable`，不得假装"已浏览网页"。

## 8. Communication / Calendar Interfaces（Phase 14H）

正式 provider interfaces（`furina/agent/capabilities/integrations/` 或 `furina/agent/providers.py`）：

```
CommunicationProvider:
    list_accounts
    list_conversations
    read_messages
    draft_message
    send_message        # L3 SENSITIVE

CalendarProvider:
    list_calendars
    list_events
    create_event        # L2/L3
    update_event        # L2/L3
```

权限：read messages/calendar → L0 或用户配置 read scope；draft → L1；
send message/email → **L3 SENSITIVE**；create/update external calendar → L2/L3。

规则：
- **没有 provider → available=false**，不得 mock 成成功；
- 不要求本 Phase 真正接通微信/钉钉；留 Gmail / Outlook / DingTalk 等 integration point。

## 9. Agent Task History Integration（Phase 14I）

AgentRuntime 每次任务生成 **stable `task_id`**；生命周期：
`PLANNED → RUNNING → COMPLETED_VERIFIED / FAILED / UNVERIFIED / CANCELLED`（**不能只有内存 status**）。

执行完成后：App owner / cognition authority 把完整 Task record 写入 C7
（**worker 不直接写 Cognition authoritative DB** —— 符合 owner contract：worker 返回结构化
task result → dispatcher owner → AgentTaskStore persist）。

Reviewer-locked：task A（notes.md → Docs）之后查询 C7 → find latest task → exact destination = Docs，
不依赖 Memory semantic guessing。

## 10. User Model Minimum Runtime Integration（Phase 14J）

Direct user message owner path：明确高置信 self-statements → UserModel candidate →
deterministic conservative extraction → owner persist。例：
- "我今天准备完成桌宠测试。" → PLAN；
- "我喜欢陈奕迅。" → PREFERENCE；
- "我不喜欢你一直给我讲大道理。" → COMMUNICATION_PREFERENCE / DISLIKE。

但："这首歌不错" 不得自动变 user lifelong favorite。所有 item 必须 evidence + confidence；
ContextAssembler 可检索；**禁止 UserModel 覆盖 current explicit user turn**。

## 11. Runtime Integration Boundary（Phase 14K）

App 初始化 `CognitionHub`，连接：existing MemoryEngine / existing RelationshipEngine /
Canon adapters / new UserModel / new EventTimeline / new AgentTaskHistory / ContextAssembler。

- Direct Dialogue snapshot 可新增 `cognitive_context`（immutable + bounded）；
- **不把数据库连接传 worker**；ContextAssembler 在 owner ingress 先构造 plain immutable data；
- DialogueBrain 只消费 frozen context；
- Agent planner 只消费任务需要的 user/context，**不得把全部私有 memory dump 给 planner**。

## 12. Work Willingness（模型预留，model-only）

本 Phase 只建立接口/模型预留：

```
WorkDisposition: EAGER / WILLING / RELUCTANT / PROTEST / REFUSE
WorkWillingnessInput: energy / fatigue / mood / relationship / annoyance /
                      task_interest / recent_workload / urgency
```

**禁止**现在把它接成硬拒绝 production task（尤其禁止 fatigue > N → refuse everything）。
Character Agency 正式行为放后续独立 Phase；本 Phase 可记录 Agent workload 为后续提供真实数据。

## 13. Privacy / Data Safety

Cognition DB 是用户数据。禁止记录：API keys / passwords / auth tokens / 完整 .env / cookie /
session secrets。Tool args 写 Task History 前必须 **redaction**；路径可记录但**不读入无关文件内容**；
Event payload 要 whitelist/normalize，不能 `repr(object)` 全量持久化。
提供最小 deletion APIs（见 COGNITIVE_ARCHITECTURE.md §8）。

## 14. 既有组件 → 未来角色

| Existing component | Future role | keep / adapt / supersede | Authority owner |
|---|---|---|---|
| `furina/agent/planner.py`（Planner） | deterministic fallback 基座 | keep（Planner V2 包装/升级） | AgentRuntime |
| `furina/agent/tool.py`（ToolRegistry/ToolResult/BaseTool） | 工具注册与结果契约 | keep | AgentRuntime |
| `furina/agent/permission.py`（PermissionManager） | 唯一权限裁决 | keep | PermissionManager |
| `furina/agent/agent_runtime.py` | 执行管线 + C7 事实来源 | adapt（task_id + owner persist 回调） | AgentRuntime |
| `furina/agent/tools/filesystem.py` | FS capability | adapt（新增 primitives） | ToolRegistry |
| `furina/agent/tools/apps.py` | Applications capability | adapt（→ ApplicationCatalog） | ApplicationCatalog |
| `furina/agent/tools/browser.py / computer.py` | Browser/Desktop capability | keep（注册进 registry） | ToolRegistry |
| `docs/architecture/future/UNIVERSAL_AGENT.md` | 历史 reservation | supersede（→ 本正式文档 redirect） | docs |
