# Cognitive Architecture（Phase 14 正式版）

> STATUS = IMPLEMENTED（furina/cognition/ + 既有 production modules）
> 前身：docs/architecture/future/COGNITIVE_STORES.md（PLANNED reservation，已升级为本正式文档的 redirect）。

本文档是 Cognitive 层的**唯一架构契约**：7 个逻辑 Store 的 SOURCE / AUTHORITY / PHYSICAL STORAGE /
WRITE OWNER / READERS / RETENTION / CONFLICT RULE / RUNTIME USE，以及 Context Assembler、
Consolidator、Retrieval、Migration 边界。实现见 `furina/cognition/`。

## 0. 设计原则（Runtime Invariants 的认知层映射）

1. **不复制第二套 truth**：已有 `furina/memory/`（memories）、`furina/relationship/`（relationship）、
   `furina/persona/furina_canon.py`（Canon identity）是既有模块的 authoritative owner；Cognition 只做
   **adapter / read-only view**，绝不新造第二个 memory/relationship/canon DB。
2. **LLM 不拥有真相**：LLM 只能输出 candidate（interpretation / user model candidate / 计划），
   必须经 deterministic owner validation 后才落地。
3. **Canon 不可被 Runtime 改写**：C1（identity）与 C2（life history）runtime writable = NO。
4. **bounded context**：Context Assembler 只组装**有界**的 plain immutable 数据，绝不 dump 数据库给 LLM。
5. **Vector 不是 truth**：derived vector index 只索引 selected entries，永远不能覆盖结构化 truth。

## 1. Store Matrix（7 个逻辑 Store）

### C1 — Canon Identity（"我是谁"）

| 项 | 值 |
|---|---|
| SOURCE | `docs/persona/FURINA_CANON_EVIDENCE.md`（FUR-001~056）、`FURINA_PERSONA_MODEL.md`、`FURINA_CN_VOICE_PROFILE.md`、`furina/persona/furina_canon.py` |
| AUTHORITY | `furina/persona/furina_canon.py`（唯一 runtime Canon 源） |
| PHYSICAL STORAGE | version-controlled Python/static data（无 SQLite） |
| WRITE OWNER | 无（runtime writable = **NO**） |
| READERS | CognitionHub / ContextAssembler / Persona / Dialogue |
| RETENTION | 永久（产品知识，非用户数据） |
| CONFLICT RULE | Canon wins；用户断言（"你其实是纳西妲"）不改写 Canon |
| RUNTIME USE | 身份事实 / 人格轴 / 矛盾 / 语言域进入对话 prompt 与行为层 |

实现：`furina/cognition/stores/canon_identity.py`（read-only adapter，直接读 `furina_canon.py` 常量，
**禁止**把 Canon facts 复制进 SQLite 形成第二 truth）。

### C2 — Canon Life History（"在来到这台电脑以前，我经历过什么"）

| 项 | 值 |
|---|---|
| SOURCE | TIER 0 官方游戏内文本（Chapter IV Act I–V / 传说任务"水的女儿" / Character Stories / Voice-Over）；当前仓库已审核的 `FURINA_CANON_EVIDENCE.md` 作为 canon provenance seed；TIER 1 HoYoWiki/官方视频用于交叉核验；TIER 2 社区镜像仅定位/交叉（标 access_source）；TIER 3（论坛/MBTI/二创/AI 总结）**禁止**进入 factual fields |
| AUTHORITY | `data/canon/furina_life_history.json` + `data/canon/furina_life_sources.json`（version-controlled、只读） |
| PHYSICAL STORAGE | JSON 数据文件（**不存在于用户可写 SQLite**） |
| WRITE OWNER | 无（runtime writable = **NO**） |
| READERS | CognitionHub / CanonLifeRetriever（activation 0..3）/ ContextAssembler（≤2 episodes） |
| RETENTION | 永久 |
| CONFLICT RULE | C2（+C1）> 任何 Runtime memory；C2 是"经历及其现在影响"，不是剧情百科 |
| RUNTIME USE | 触发式（activation）进入对话；不 always-on、不 lore bot |

> **C2 状态（Phase 14.1 §10 明示）**：
> `C2 STATUS = STRUCTURE IMPLEMENTED`（schema/store/retrieval/activation 全部实现）；
> `CANON CORPUS = SEED / PARTIAL`（20 条 seed episodes；Chapter IV Act I–IV 具体场景标
> `status=PARTIAL`，不猜）。**不得宣称 FULL CANON LIFE COMPLETE / source-complete**。
> SRC-004/005/006（官方游戏文本）没有可重定位 locator（本 repo 不保存大段原文），
> 不声称 source-complete；完整官方 source expansion 留 Phase 15。

字段模型 `CanonEpisode`（见 `furina/cognition/models.py`）：
`episode_id / timeline_order / period / version / quest / act / scene / objective_summary /
furina_role_at_time / furina_knew[] / furina_did_not_know[] / people_present[] /
relationship_context[] / social_context[] / external_demands[] / actions_taken[] / choices[] /
expressed_emotions[] / inferred_inner_state[] / immediate_consequences[] /
psychological_effects[] / belief_effects[] / coping_strategies[] / present_day_effects[] /
trigger_topics[] / explicit_recall_policy / evidence_ids[] / source_ids[] / confidence / canon_status`。

关键：`objective_summary`（发生了什么）与 `inferred_inner_state`（我们推断她如何理解）
**必须分字段**；`furina_knew[]` / `furina_did_not_know[]` 表达**当时的信息边界**；
`psychological_effects[]` → `present_day_effects[]` 表达"经历 → 当前影响"的结构化推导。

### C3 — Runtime Autobiographical Memory（"来到桌面以后我经历过什么"）

| 项 | 值 |
|---|---|
| SOURCE | Runtime events / user interactions / Agent tasks / relationship milestones / consolidation |
| AUTHORITY | existing `MemoryEngine` / `MemoryStore`（`memories` table） |
| PHYSICAL STORAGE | existing `memories` table（**无第二张 cognitive memory 表**） |
| WRITE OWNER | MemoryEngine（通过 `furina/cognition/stores/autobiography.py` adapter 调用） |
| READERS | MemoryEngine.retrieve / ContextAssembler（≤3 memories） |
| RETENTION | existing memory 治理（importance / strength / capacity eviction） |
| CONFLICT RULE | CURRENT FACT > RECENT FACT > MEMORY；C3 语义回忆不覆盖 C7 精确任务事实 |
| RUNTIME USE | 桌面时代经历进入对话上下文 |

禁止：把游戏主线剧情当普通 Runtime Memory insert（那是 C2 的职责）。

### C4 — User Model（"用户是谁"）

| 项 | 值 |
|---|---|
| SOURCE | 用户**明确高置信**自我陈述、高置信重复行为、已验证任务上下文 |
| AUTHORITY | `furina/cognition/stores/user_model.py`（UserModelStore，唯一写 owner） |
| PHYSICAL STORAGE | SQLite `user_model_items` 表（新增 schema，CREATE TABLE IF NOT EXISTS） |
| WRITE OWNER | Cognition/UserModel owner（deterministic conservative extraction，经 owner 路径持久化） |
| READERS | ContextAssembler（≤5 items）/ Agent planner（任务所需子集） |
| RETENTION | 有效期内；同一 key 更新 → supersede / validity close（**不得无历史 overwrite**） |
| CONFLICT RULE | **current explicit user turn > UserModel**（用户现在说的话永远赢） |
| RUNTIME USE | 对话/计划的用户相关事实 |

`user_model_items` 字段：`item_id / category / key / value_json / confidence / source_event_id /
source_text_excerpt / created_at / updated_at / valid_from / valid_to / status`。
category：`FACT / PREFERENCE / DISLIKE / ROUTINE / PROJECT / GOAL / PLAN /
COMMUNICATION_PREFERENCE / IMPORTANT_DATE`。
禁止：从模糊一句话自动生成高 confidence 人格判断（"这首歌不错" ≠ lifelong favorite）。

### C5 — Relationship（"我们是什么关系"）

| 项 | 值 |
|---|---|
| SOURCE | 真实互动（positive / rejection / milestones / repair / time） |
| AUTHORITY | existing `RelationshipEngine`（`furina/relationship/`） |
| PHYSICAL STORAGE | existing `relationship` table（**不复制一套 trust**） |
| WRITE OWNER | RelationshipEngine（唯一写入口） |
| READERS | CognitionHub（read/write adapter）/ ContextAssembler / Persona |
| RETENTION | 长期积累（decay 机制由 engine 负责） |
| CONFLICT RULE | Relationship != Memory；Memory 解释关系经历，不拥有 current trust truth |
| RUNTIME USE | 归一化 0..1 因子进入对话/行为 |

Cognition 可额外存 relationship history/milestones，但 current relationship dimensions
只有现有 engine 可写。

### C6 — Life / Event Timeline（"客观上发生过什么"）

| 项 | 值 |
|---|---|
| SOURCE | Runtime authoritative events（append-only ledger） |
| AUTHORITY | `furina/cognition/stores/event_timeline.py`（EventTimelineStore，唯一写 owner） |
| PHYSICAL STORAGE | SQLite `life_events` 表（append-only；同一 event_id 不可悄悄 overwrite） |
| WRITE OWNER | CognitionHub / EventTimeline owner（owner 线程路径） |
| READERS | ContextAssembler（≤5 recent events）/ 查询 API |
| RETENTION | 有界（长文本长度限制；payload whitelist/normalize） |
| CONFLICT RULE | Event != Memory；C6 是客观事实，**不得把 interpretation 写进 payload** |
| RUNTIME USE | recent events 进入上下文（RECENT EVENT 是第二高权威） |

`life_events` 字段：`event_id / event_type / timestamp_wall / timestamp_monotonic_session /
session_id / source / actor / channel / turn_id / task_id / payload_json / importance / created_at`。
API：`append / query_recent / query_by_type / query_by_turn / query_by_task / query_time_range`。
禁止持久化：raw screenshots、API keys、完整 LLM system prompts、secret env values。

### C7 — Agent Task History（"我替用户做过什么"）

| 项 | 值 |
|---|---|
| SOURCE | **verified** Agent runtime execution（真实执行/Verify 事实） |
| AUTHORITY | `furina/cognition/stores/agent_history.py`（AgentTaskHistoryStore，唯一写 owner） |
| PHYSICAL STORAGE | SQLite `agent_tasks / agent_task_steps / agent_artifacts` 表 |
| WRITE OWNER | Cognition/AgentTaskHistory owner（worker 返回结构化结果 → dispatcher owner → persist） |
| READERS | ContextAssembler（≤2 tasks）/ 精确查询（"notes.md 放哪了"） |
| RETENTION | 长期（任务历史） |
| CONFLICT RULE | **C7 exact task fact wins** over C3 语义回忆（ok != verified） |
| RUNTIME USE | 回答"我替你做过什么"、"把 X 放哪了"（不依赖 Memory semantic guessing） |

`agent_tasks`：`task_id / original_request / goal / status / started_at / finished_at /
permission_summary / plan_json / verified / result_summary / error`。
status：`PLANNED / RUNNING / COMPLETED_VERIFIED / FAILED / UNVERIFIED / CANCELLED`。
`agent_task_steps`：`task_id / step_index / capability / tool / args_redacted_json /
permission_level / status / verified / result_json / error`（args 写库前 **redaction**）。
`agent_artifacts`：`task_id / artifact_type / path / exists_verified / metadata_json`。

## 2. 既有组件 → 未来角色（keep / adapt / supersede）

| Existing component | Future role | keep / adapt / supersede | Authority owner |
|---|---|---|---|
| `furina/persona/furina_canon.py` | C1 唯一 Canon identity 源 | keep（adapt: Cognition 只读 adapter） | furina_canon |
| `docs/persona/FURINA_CANON_EVIDENCE.md` | C2 canon provenance seed（TIER 0 种子） | keep | repo docs |
| `data/canon/furina_life_history.json` | C2 结构化经历库 | **new**（C2 物理存储） | repo data（只读） |
| `furina/memory/`（MemoryEngine/MemoryStore） | C3 唯一记忆持久化 | keep（adapt: AutobiographicalMemoryStore 包装） | MemoryEngine |
| `furina/relationship/`（RelationshipEngine） | C5 唯一关系 truth | keep（adapt: RelationshipStore 读写 adapter） | RelationshipEngine |
| `furina/agent/`（AgentRuntime） | C7 任务事实来源 | keep（adapt: 完成后 owner 写 C7） | AgentTaskHistoryStore |
| `furina/app.py`（owner ingress） | CognitionHub 组装边界 | adapt（freeze snapshot + cognitive_context） | App owner |
| `docs/architecture/future/COGNITIVE_STORES.md` | 历史 reservation | supersede（→ 本正式文档 redirect） | docs |

**不迁移**任何稳定 production module 到新命名空间（Runtime Invariant 16）。

## 3. Cognitive Context Assembler

`furina/cognition/context.py` → `CognitiveContextAssembler.assemble()` 输出不可变
`CognitiveContext`：

```
CognitiveContext {
    current_facts          # CURRENT FACT（最高权威，来自 runtime snapshot）
    recent_events          # ≤5（RECENT EVENT）
    relevant_agent_tasks   # ≤2（AGENT TASK FACT）
    user_model_items       # ≤5（USER MODEL FACT）
    autobiographical_memories  # ≤3（AUTOBIO MEMORY）
    canon_identity         # C1 只读视图
    relevant_canon_episodes    # ≤2（CANON CONTEXT，最低权威）
    relationship           # C5 归一化因子（只读快照）
}
```

Authority（冲突真值优先，非"全部塞进 prompt"）：
**CURRENT FACTS > RECENT EVENT > AGENT TASK FACT > USER MODEL FACT > AUTOBIO MEMORY > CANON CONTEXT**

默认有界限制：canon episodes ≤ 2、memories ≤ 3、user items ≤ 5、agent tasks ≤ 2、recent events ≤ 5。
**不得把整个数据库 dump 给 LLM。**

组装发生在 **owner ingress**（`furina/app.py` 冻结 Direct snapshot 时同步构造 plain immutable
cognitive_context），worker / DialogueBrain 只消费 frozen context，**不把数据库连接传 worker**。

## 4. Canon Life Retrieval（activation 0..3）

`furina/cognition/retrieval/retriever.py` → `CanonLifeRetriever`：

- **LEVEL 0**：历史只塑造回答，不显式提历史。
- **LEVEL 1**：隐约经验影响。
- **LEVEL 2**：可明确提过去（"以前……"）。
- **LEVEL 3**：用户直接问相关 Canon 身份/人生，可明确谈具体过去。

检索同时考虑：semantic relevance、psychological relevance、PersonaPlan、conversation topic、
relationship trust、explicitness。最终是否显式提历史仍交 PersonaPlan / activation policy。

Reviewer-locked：
- "今天吃什么" → LONG_PERFORMANCE activation **0**（不自动拉取）。
- "没人关注你怎么办" → LONG_PERFORMANCE / ORDINARY_LIFE / CHOSEN_PERFORMANCE relevant。
- "你和芙卡洛斯是什么关系" → ORIGIN_IDENTITY / FOCALORS_TRUTH activation **3**。
- "你当水神的时候开心吗" → PUBLIC_ROLE / LONG_PERFORMANCE activation **3**。
- 不得每次说"五百年……"。

## 5. Event → Memory（最小 Consolidator）

`furina/cognition/consolidation/consolidator.py` → `Consolidator`：**不是所有 event 都变 Memory**。

| Raw Event | 处理 |
|---|---|
| 普通窗口切换 | Event only（C6） |
| 用户摸头 | Event（C6）+ 有条件 Memory（C3，经 MemoryEngine.observe） |
| Agent 成功完成重要任务 | Event + AgentTask（C7）+ 可形成 episodic memory（C3） |
| 明确用户计划 | Event + UserModel PLAN（C4）+ 可形成 memory（C3） |
| 关系数值更新 | Relationship truth（C5）+ 必要时 milestone，**不复制成 5 条 memory** |

**单事件单 owner**：禁止一次事件多 owner 重复写 memory。

## 6. Derived Vector Index（非 truth store）

Vector DB / embedding index **不是第 8 个 truth Store**：只索引 selected C2 episodes、C3 memories、
C4 user model semantic items、selected C7 summaries；必须能由 source data 重新构建；
向量结果**永远不能覆盖** authoritative structured truth。本 Phase 不接外部 embedding 服务
（`furina/memory/` 现有 embedding 列保持 JSON 占位语义）。

## 7. Write Authority Matrix

| Store | runtime writable | writer |
|---|---|---|
| C1 Canon Identity | NO | — |
| C2 Canon Life History | NO | — |
| C3 Autobiographical Memory | YES | MemoryEngine（adapter） |
| C4 User Model | YES | UserModel owner（deterministic） |
| C5 Relationship | YES | RelationshipEngine（唯一） |
| C6 Event Timeline | YES | EventTimeline owner |
| C7 Agent Task | YES | AgentTaskHistory owner（仅 verified Agent 结果） |
| Vector Index | — | Indexer（authority = NONE） |

禁止：DialogueBrain 直接写任意 Store；LLM 输出 candidate 必须经 deterministic owner validation。

## 8. Migration / 数据安全

- 复用现有 `furina.db`（或 configured DB）；新 schema 全部 `CREATE TABLE IF NOT EXISTS`；
  有 schema version/migration mechanism（`furina/cognition/hub.py`）；busy_timeout；明确 transaction boundary。
- **无 destructive migration**：不删除/不清空用户现有 memories / relationship。
- 开始前测试复制 temp DB；migration 测试**只能操作 temp DB**，不碰真实 `data/furina.db`。
- 最小 deletion APIs：delete user model item / delete autobiographical memory（复用现有）/
  delete agent task history item / clear event history。
- Canon C1/C2 不属于用户可学习数据，**不能被 Runtime deletion/learning 改写**。

## 9. 认知因果流

```
官方 Canon 来源 → Canon Evidence(FUR-*) → C1 Identity + C2 Life History → Current Furina baseline
桌面新人生: Runtime Event → C6 Event Timeline → interpretation → C3/C4/C5/C7
→ CognitiveContextAssembler → Persona/Dialogue/Life/Agent → future behavior
```
