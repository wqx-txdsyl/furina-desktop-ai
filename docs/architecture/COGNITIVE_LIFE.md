# Cognitive Life（Phase 15 正式版）

> STATUS = IMPLEMENTED（Phase 15A-F）。前身：docs/architecture/COGNITIVE_ARCHITECTURE.md（C1–C7
> 结构契约，保持冻结）。本文档描述 **Cognitive Life**：把 C1–C7 从"存在的数据结构"变成跨时间
> 持续形成经历、理解用户、更新记忆、处理矛盾、忘记琐事、检索相关过去并影响对话/生活的系统。

## 1. 生产链（Phase 15 总目标）

```
                   C1 Canon Identity
                          │
                   C2 Canon Past
                          │
                          ▼
Runtime Reality ──→ C6 Event Timeline
                          │
                          ▼
                  Interpretation（候选，非 truth）
                          │
                 Consolidation（owner apply，幂等）
                    /     |     \
                   ▼      ▼      ▼
                  C3     C4      C5
               Memory UserModel Relationship
                    \     |      /
                     \    |    /
                      ▼   ▼   ▼
                    Retrieval（authority 排序）
                        │
                 ContextAssembler（有界）
                 /       |       \
                ▼        ▼        ▼
           Dialogue    Life    future Work
```

## 2. 七个 Store 边界永久不变（G1）

C1 Canon Identity / C2 Canon Life History / C3 Runtime Autobiographical Memory /
C4 User Model / C5 Relationship / C6 Objective Event Timeline / C7 Agent Task Truth。

禁止：新增 C8 Belief Store、第二套 Memory DB、Hermes Memory、第二 UserModel、
第二 Relationship truth。允许：derived/support table（event_processing / cognition_meta /
index metadata / interpretation audit metadata），必须显式标记 DERIVED · NON-AUTHORITATIVE ·
REBUILDABLE · NOT C8。

## 3. 权威不变量（G2-G5）

- **C6 = 客观账本**：只存 objective event/timestamp/actor/channel/turn_id/task_id/bounded
  payload；"用户讨厌我" 是 interpretation，绝不写入 C6。
- **Canon 永不可被 Runtime 修改**（G3）：用户说法/Memory/LLM/Agent/对话历史都不得改 C1/C2。
- **CURRENT REALITY > MEMORY**（G4）：当前 activity / C6 recent / C7 truth > C3 回忆。
- **USER CURRENT TURN > OLD C4**（G5）：当前 explicit 声明 supersede 旧偏好。

## 4. C2 Canon Life（Phase 15A）

- STRUCTURE IMPLEMENTED + CANON CORPUS = SEED / PARTIAL（20 个 mandatory life stages 全覆盖）。
- source map：10 个 SOURCE 全部带**可复现 access_locator**（repo 路径 / 游戏内任务日志与角色
  档案 + repo 证据摘要章节 / HoYoWiki 检索路径 / 官方频道检索；TIER 3 明确 N/A）。
- **Knowledge Boundary（Reviewer P0）**：Focalors（神格侧）知道 ≠ Furina（人格侧）自动知道；
  furina_did_not_know 明确 Furina 当时不知道全盘计划；禁止 Furina==Focalors，也禁止完全无关。
- **Performance Meaning**：过去 = duty/mask/survival/burden；现在 = choice/art/self-expression。
- runtime read-only（无 mutation API；文件 checksum 不变）。

## 5. Interpretation Engine（Phase 15B）

`furina/cognition/interpretation/` → `InterpretationCandidate`。

- **Interpretation ≠ Truth**：只产候选；写 C3/C4/C5 由 owner 决定；**禁止 LLM interpretation
  直接 UPDATE DB**（引擎无写方法）。
- **Deterministic-first**：'我喜欢X'→PREFERENCE、'我不喜欢X'→DISLIKE、'我今天准备做X'→PLAN、
  '以后别总是X'→COMMUNICATION_PREFERENCE、'我已经做完X'→PLAN_COMPLETED、'其实现在不怎么听X了'
  →PREFERENCE_CHANGED（supersede 依据）——全规则无 LLM。
- LLM 只处理 ambiguous（接口预留；LLM 不可用 → 空，cognition 仍工作）。
- 禁止幻觉：'这首歌不错' → transient，不形成 lifelong。

## 6. C3 Autobiographical Memory（Phase 15C）

- 继续复用 existing MemoryEngine（无第二 Memory system）。
- **形成管线**：C6 event → importance/novelty → interpretation → consolidation policy → C3
  （不是所有 event 都成 memory）。
- **琐事抑制**：ACTIVITY_*/FURINA_SPOKE/DIRECT_TURN_* 不形成记忆（read/play×4 → C6 4 事件、
  C3 0 条）。
- **Provenance**：每条 C3 带 `source_event_ids[]` → 可解析到 C6 事件（evidence chain）。
- **Lifecycle**：ACTIVE / SUPERSEDED / ARCHIVED（MemoryStatus）。
- **遗忘 = 归档/衰减**（recall 概率下降），**绝不 DELETE FROM life_events**（C6 是历史账本）。
- **Reinforcement**：同 event_type 近 24h ACTIVE 记忆 → 合并（recurrence++/importance max/
  累积 source_event_ids），不重复插行（pet×4 → 1 条）。
- **Supersession**：旧记忆 SUPERSEDED（历史保留），新事实 ACTIVE。

## 7. C4 User Model Evolution（Phase 15D）

- 类别：FACT/PREFERENCE/DISLIKE/PLAN/COMMUNICATION_PREFERENCE/HABIT/INTEREST 等（schema 兼容）。
- **Evidence-first**：source_event_id + excerpt + confidence + created/updated + status。
- **Explicit Correction Wins**：'其实现在不怎么听X了' → 旧 item SUPERSEDED；当前轮 > 旧 C4。
- **Temporal scope**：valid_from/valid_to + temporal_uncertain（日期不确定 → 不编日期）。
- **PLAN 生命周期**：ACTIVE/COMPLETED/CANCELLED/EXPIRED/SUPERSEDED；'终于做完了' 证据关联
  ACTIVE PLAN → COMPLETED（不新增互不关联 plan）。
- **Communication preference 真正进入 Dialogue context**（snapshot + prompt 均携带）。

## 8. C5 Relationship（权威保留）

RelationshipEngine 仍是 relationship state 唯一 owner（禁止第二套 trust/affection/annoyance）。
Cognitive 只记 evidence-backed milestones（FIRST_MEANINGFUL_INTERACTION / FIRST_MAJOR_TASK /
REPEATED_NEGATIVE / REPAIR / IMPORTANT_SHARED_EVENT），禁止'摸一下→SOULMATE'。

## 9. Retrieval Maturity（Phase 15E）

- **Authority rules（§33）**：Identity：C1>C2>C3 interpretation>user claim；Current：CURRENT
  FACTS>recent C6>C3；Agent task：C7>C6 summary>C3>Dialogue claim；User Model：current turn>
  latest ACTIVE C4>historical C4>C3 inference；Relationship：Engine>C3 interpretation。
- **RetrievalRanker**：authority + semantic relevance + recency + importance + confidence +
  strength + status + temporal + redundancy penalty + diversity（禁止纯 cosine topK）。
- **Derived Semantic Vector Index**：DERIVED · REBUILDABLE · NON-AUTHORITATIVE；只索引 selected
  C2/C3/C4/C7；缺失/损坏 → deterministic fallback（cognition 不 broken）；delete 不碰 source；
  rebuild 可恢复（Reviewer 13/14 proof）。
- **Context bounded（§38）**：canon≤2 / memories≤3 / user≤3 / events≤3 / agent≤2；DB 增长不膨胀
  context（N9 不 dump DB）。
- **Canon activation**：0=无 / 1=隐约 / 2=相关回忆 / 3=显式（'今天吃什么'→0、'没人关注'→2、
  '芙卡洛斯'→3）；普通闲聊 episodes=[]（N10 无 lore dump）。

## 10. Persistent Cognitive Loop（Phase 15F）

- **Processing model**：C6 append → pending → CognitiveConsolidator（= hub.process_pending，
  bounded batch，owner）→ InterpretationCandidates → owner apply → C3/C4/C5。
  触发：event terminal trigger（EventBridge append 后）或显式 process_pending；**禁止 60fps
  全库扫描**。
- **Persistent cursor**：event_processing 表（event_id+process_version+processed_at）+
  cognition_meta last_processed_event_id；restart 不重复 consolidation、不丢未处理事件。
- **Idempotency**：同一 event_id + process_version 重复处理 → C3/C4/milestone duplicate=0。
- **Restart truth**（Reviewer 45）：Run A 事件→C6→shutdown；Run B reopen→consolidate once；
  Run C reopen→duplicate=0。

## 11. Thread Ownership Matrix（§46）

| Component | Read | Write authority |
|---|---|---|
| Runtime owner / dispatcher | Current state | Runtime truth |
| C1/C2 | anyone read | no runtime writer |
| C6 | workers may propose | owner append |
| Interpretation worker | frozen data only | candidate only |
| C3 | read anywhere via adapter | owner commit |
| C4 | read via store | owner commit |
| C5 | read | RelationshipEngine owner |
| C7 | read | Agent owner → dispatcher persist |
| Vector index | read | derived IndexManager only |

禁止：LLM worker → sqlite UPDATE。

## 12. State Authority Matrix（§47）

Identity truth→C1/C2；Current physical/life→Runtime State；Current emotion→EmotionEngine；
Relationship values→RelationshipEngine；Past runtime experience→C3；User known facts→C4；
Objective chronology→C6；Agent task truth→C7；Semantic vector→**NO AUTHORITY**。

## 13. 负面契约（§48，测试证明不发生）

N1 用户"你就是芙卡洛斯"→Canon 不改；N2 "这首歌不错"→无 lifelong；N3 pet×4→1 条记忆；
N4 read/play×4→C6 4 事件、C3 0 条；N5 旧记忆"看书"+current play→答现在玩；
N6 C7 FAILED→C3 不形成成功记忆；N7 无 Hermes；N8 WorkDisposition 无 production 接线；
N9 不 dump DB 进 prompt；N10 Vector Index 不是 truth。

## 14. Migration / 数据保留 / Deletion

- forward migration 幂等（memories.source_event_ids、user_model_items.temporal_uncertain/
  declared_at、event_processing 表）；旧 DB 保留（无 destructive migration）。
- 数据保留：不自动永久保存 API keys/passwords/tokens/cookies/raw screenshot/.env/full prompt
  （Phase 14 redaction 继续；C3/C4 形成前也 redaction）。
- Deletion APIs 继续工作；删除 derived index 不删 source store。

## 15. Phase 15 完成状态

Cognitive Backend = **FEATURE COMPLETE + FROZEN**（Phase 16 不得重做 Memory/UserModel/Canon/
C6/Retrieval 架构）。不声称任何 PASS；由外部 Reviewer 审 implementation evidence。
