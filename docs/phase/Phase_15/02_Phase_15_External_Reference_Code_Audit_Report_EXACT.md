# Phase 15 — External Reference Code Audit Report

任务书：`docs/phase/Phase_15/01_Phase_15_External_Reference_Code_Audit_Task_Brief_EXACT.md`
模式：READ-ONLY AUDIT（本报告为唯一交付物；零生产代码 / 测试 / 依赖 / Canon 数据改动）

## 1. Audit Result

| Repo | Default branch | Audited SHA | Audit date | Reality Gate |
|---|---|---|---|---|
| P15-REF-01 `xiahy456/AronaAI` | `main` | `97223ef956e0464a7f08f1d9ab105a346ca3299c` | 2026-08-27 | IMPLEMENTED（核心认知子系统均有可运行代码） |
| P15-REF-02 `Furinelle/furina` | `main` | `9d7e858d5d1cf382e8af32c1e9318d020da6d6f0` | 2026-08-27 | PARTIALLY_IMPLEMENTED（Persona=纯 prompt 文件；memory/consolidation/recall=Node 纯函数 + 单测） |
| P15-REF-03 `com554433/Genshin-Furina-RP-Skill` | `master` | `fa275c734b1da38bc406d6fe96e4b403875d23f9` | 2026-08-27 | DOC_ONLY（无 runtime/测试；README 徽章宣称 Tests 90% passing 与仓库事实不符） |
| （显式延后）`kiyotakali/Miru` | — | 无法可靠解析开放 backend 源码树（本次 `git ls-remote` / raw 探测均无可用源码响应） | 2026-08-27 | BLOCKED |

Overall finding：**没有任何外部仓库达到或超越 Furina 的 C1-C7 真值边界与溯源纪律**；
AronaAI 是唯一具备成体系运行时实现的参考，贡献了若干真实、可测的机制级 delta
（时间感知混合检索、注入冷却、写时时间归一化、goal 跟进式主动状态机、关系气候的
日帽+基线回归）；Furinelle 的价值在 Persona 维度表与 Canon locator；RP-Skill 只有
locator / red-team 价值。

## 2. Furina Phase 15 baseline（对照基准，冻结）

- C1 Canon Identity：`furina/persona/character_identity.py`（历史面具 vs 当前凡人态分层）、
  `furina/cognition/stores/canon_identity.py`。硬边界：Furina != Focalors，同源不共享
  运行时知识/记忆。
- C2 Canon Life History：`furina/cognition/stores/canon_history.py` +
  `data/canon/furina_life_history.json` / `furina_life_sources.json` /
  `furina_evidence_units.json`（56 单元归因真源）。version-controlled、runtime 只读、
  语义完整性如实 PARTIAL（missing_main_story_acts=['II','III']）。
- C3 自传体记忆：`furina/memory/memory_engine.py`（唯一 formation authority；
  reinforce 累积 source_event_ids、archive(reason) 无静默删除）+
  `furina/cognition/stores/autobiography.py`。
- C4 User Model：`furina/cognition/stores/user_model.py`（upsert/supersede/complete，
  valid_from/valid_to 时效列，transition_event_id/reason）。
- C5 Relationship：`furina/relationship/engine.py`（多维 0..100 因子 + rate 维度 +
  decay-to-baseline 仅作用短期维度；milestones 带 provenance）。
- C6 事件真源：`furina/cognition/stores/event_timeline.py`（append-only 白名单）+
  `furina/cognition/bridge.py`（exactly-once dedupe，失败不毒化重试 key）。
- C7 Agent Task History：`furina/cognition/stores/agent_history.py`（verified execution truth，
  FAILED ≠ 成功记忆）。
- Derived Semantic Index：`furina/cognition/retrieval/{index,ranker,retriever}.py`
  （INDEX_MARKER: derived/rebuildable/non_authoritative；authority 权重 + recency +
  importance/confidence 综合打分；embedding 不可用 → deterministic lexical/metadata 退化）。
- 生产纪律（Phase 14 freeze）：canonical USER_MESSAGE 两阶段 ingress 与 row→T→U 精确
  身份链、R6/R10 fail-closed、Scheduler 社交投标生命周期、C3 单一 formation authority。

## 3. AronaAI code audit

```text
Repository:      xiahy456/AronaAI
Default branch:  main
Audited SHA:     97223ef956e0464a7f08f1d9ab105a346ca3299c
Audit date:      2026-08-27
Relevant code roots: backend/app/{memory,relationship,proactive,knowledge,planner},
                 backend/app/{orchestrator,prompt,conversation,embeddings}.py
Relevant tests:  backend/scripts/test_*_unit.py / smoke_*.py / test_query_time.py 等
                 standalone 脚本（assert 式）；frontend 少量脚本测试；无 CI workflow
Reality Gate:    IMPLEMENTED
License:         Apache-2.0（代码级复用可行，需保留声明；本项目本任务未复制任何代码）
```

### 3.1 Actual code paths（真实调用链，orchestrator.handle_chat）

```text
user_text → relationship.on_user_text/classify（UserAct 判定；refuse 可跳过生成）
  → memory_store.encode_queries([text, time_query])（本地 BGE）
  → memory_store.retrieve(top_k, apply_inject_cooldown=True, now=…)
      内部：FTS5 候选键 ∪ Chroma 向量候选 → 以存量 embedding 余弦重打分 → max 合并
            + 时间感知变体（build_time_aware_query 注入当前时间；相对日期展开 FTS 查询组）
            + BGE 缺失 → _fts_only_entries 纯词法退化
  → knowledge.retrieve（独立 Chroma/BGE RAG 管线 + clip_knowledge_for_inject 字符预算）
  → planner.plan(memories, knowledge, climate_block)（双路由：LLM planner 或本地退化）
        IntentCard{draft/emotion/user_act/followup_ok/reply_ok}；reply_ok=False → 静默跳过
  → _compose_reply（history 截断 LOCAL_MAX_HISTORY_TURNS=4；token 预算裁剪）
  → 异步 MemoryExtractor 队列（should_extract 触发 → DeepSeek JSON 抽取 → daily quota）
```

### 3.2 A1–A6 exact answers

**A1 User Model（extractor 实现口径）**
- upsert/delete：**代码**（store.upsert/store.delete + LLM 输出 op）。
- existing-key reconciliation：**prompt**（"优先复用已有记忆的 key"）+ **代码**辅助
  （抽取时把 retrieve_entries 的已有记忆注入 prompt；批内 `_collapse_batch_upserts`
  归一化内容合并、hot-key 保护）。
- temporal normalization：**prompt 规则**（相对→绝对日期阶梯 年月日/年月/年；区间「或/到」；
  周期习惯保留周期表述；过去→最近已发生、将来→即将到来），由 `query_time.format_extract_now()`
  提供当前时间上下文——确定性解析器只服务于查询侧（query_time.py），不在写入侧兜底。
- user-sourced-only facts：**仅 prompt 约束**（"记忆必须来自于用户所述"），无说话人身份的代码校验。
- plan/goal completion：**prompt 为主 + 代码硬约束保护**（`_reconcile_after_upsert` 对
  goal 类别一律不参与相似合并/自动清除——goal 只能被显式 op=delete 移除）。
- confidence 字段：无。诚实性靠 validate.py 的拒绝规则（疑问句/猜测类内容拒收）。

**A2 Memory retrieval（代码核实，非 README）**
- SQLite durable store：✔（memories 表 key PK/content/category/updated_at/source/
  last_injected_at）。
- FTS5：✔（`CREATE VIRTUAL TABLE memories_fts USING fts5(... tokenize='unicode61')`，
  jieba 预分词查询）。
- vector store：✔ Chroma（cosine space），本地 BGE 编码（`embeddings.LocalBgeEncoder`）。
- hybrid merge：✔（FTS 候选键以存量 embedding 余弦重打分后与向量结果 max 合并；
  candidate_top_k > top_k 先扩后收）。
- fallback：✔ BGE 缺失/异常 → FTS-only。
- time-aware retrieval：✔ 时间改写查询 + 相对日期展开多查询 FTS 组 + 时间向量编码。
- injection cooldown：✔ `last_injected_at` + `inject_cooldown_sec`，chat 主路径
  orchestrator.py:195/444 显式启用（近期已注入的记忆被抑制重复注入）。

**A3 Memory vs Knowledge 分离**：物理分离 ✔ —— memory（SQLite+FTS5+Chroma collections）
与 knowledge lore（独立 markdown 分块 ingest → 独立 Chroma collection + 词法别名计数）
是两条管线两个 store（backend/scripts/ingest_knowledge.py、diagnose_knowledge_rag.py）。
但两者都是"可重建索引之上的检索层"，Canon 权威与分层归因概念不存在。

**A4 Relationship（值得吸收与否）**
- trust / dependence / tension ∈ [-1,1] 三维慢气候：代码实现于 relationship/state.py
  （apply_delta 含 α*Δ - β*(old-baseline) 回归、daily_abs_cap 日累计绝对增量上限、
  makeup 张力补偿、跨日 reset 计数）。
- climate 分区（secure_play/cling_risk/rupture/cold_tool/fragile/steady）→ 行动策略
  speak/initiate/refuse/silence（policy.py，明确"不输出数字刻度"的产品哲学）。
- 值得 ADAPT 的点：**daily_abs_cap 防刷机制**与**向 baseline 的慢回归**；climate 只作为
  policy 门控而非可见数值。其短板：无事件溯源（delta 由文本分类产生，不可追溯）、
  单用户场景假设、维度比我们的少（我们是多维因子 + rate 维）。

**A5 Cognitive loop（真实 orchestration 路径见 §3.1）**：持久层三类独立 store
（memory/knowledge/relationship 各自文件），单进程 asyncio 编排，重启后 SQLite/JSON
状态均恢复；无事件时间线，客观历史不可回放。

**A6 Proactive behavior**：**主要是确定性调度器/冷却逻辑，非自主认知**：
proactive/loop.py TICK_SEC=30 进程级 ticker 从动机集合 pick_motive 至多一个；
slots/care（午饭/睡觉时段 after_sec 窗口）、festival（生日来自 profile 记忆）、idle/
goal（冷却窗口、mute、每日配额，ProactiveState JSON 持久化跨重启）；relationship 决定
能否发起（decide_proactive 按 climate 门控）。与 Fixed timer 的差别仅在于持久化的
quota/mute 簿记与 memory 内容拼装。对照我方 presence/attention 投标模型（Scheduler
social bid + USER_IGNORED 反馈闭环）语义上更弱。

### 3.3 Strengths / Weaknesses / Conflicts / Deltas

- Strengths：混合检索工程质量高且全链路有退化路径；写入侧验证+去重+reconcile 成体系；
  抽取配额/队列防滥用；goal 类保护性删除约束；关系中"防刷 + 回归"的数值设计。
- Weaknesses：无 source-event 溯源（C6 缺位）；记忆无时效列/无 supersede 历史
  （delete 为物理删）；无 C1/C2 概念；proactive 与"注意他人"无关；无 CI。
- C1-C7 conflicts：LLM 直接产出 durable fact 且可 delete（违背 formation authority）；
  无客观事件真源；向量索引与权威行双写（自备 check_memory_sync.py 佐证同步风险，
  我方 derived index 明确 non-authoritative 且幂等 rebuild）。
- Candidate deltas：见 §8/§9（D-A1..D-A5）。

## 4. Furinelle code audit

```text
Repository:      Furinelle/furina
Default branch:  main
Audited SHA:     9d7e858d5d1cf382e8af32c1e9318d020da6d6f0
Audit date:      2026-08-27
Relevant code roots: skills/furina/scripts/furina-memory.mjs（590 行工具）,
                 scripts/furina-eval.mjs, tests/{memory,persona-content}.test.mjs,
                 skills/furina/references/**（persona/canon/markdown 资料）
Relevant tests:  node:test 单测（clamp/inferType/overlapScore/strength/heart 等，
                 202 行）；persona-content.test.mjs = 静态内容断言（81 行）
Reality Gate:    PARTIALLY_IMPLEMENTED（memory 工具有真实代码与测试；persona 全部为 prompt）
License:         MIT（代码复用许可宽松；官方台词/图片资产另计版权风险）
```

### F1 Persona dimensions（只提取机制，不复制文本）

| 维度 | 是否显式 | 是否 state-dependent | 是否被测 | 我方现有等价 |
|---|---|---|---|---|
| 自称切换（“本神”↔“我”） | 显式（亲密度阈值表） | 是（按关系数值门控） | 否（无测试） | 有更稳做法：`furina/persona/furina_character_contract.py` 把"本神"定义为**历史面具残留**并限制使用频率（当前态合同），不与关系数值耦合 |
| 爱面子序列（嘴硬否认→轻受用→转话题） | 显式 | 部分 | 否 | `furina/persona/persona_planner.py` 应答策略 + 情绪事件链部分覆盖 |
| 舞台腔/意象集 | 显式（可选、限频） | 部分 | persona-content 静态断言 | `character_identity.py`Former-Mask 层 + expression_examples |
| 压力等级 0-3 表达梯度（句子变短/停顿/省略号增多/舞台词退场） | 显式 | 是 | 否 | docs/persona/FURINA_CANON_EVIDENCE.md 被戳穿分层证据（FUR-006/007/008）+ 情绪模式驱动；**但"随压力单调收紧语言形态"作为可测行为我们没有同等显式的表** |
| 脆弱/吐露触发 | 显式（高压+特定话题抑制舞台词） | 是 | 否 | persona_planner._CONFIDE_RE 吐露路径覆盖 |
| OOC 约束（身份坚守/第四墙/退出指令/安全红线） | 显式规则表 | 部分 | persona-content 断言 | Phase13 validator/guard 族（tests/persona/test_validator_rules.py 等） |
| 好奇/无聊敏感 | 隐含于 personality.md | 弱 | 否 | Motivation/diversity（behavior/motivation.py）驱动 |

### F2 Persona evaluation 现状

- 手工验收场景：✔ scripts/furina-eval.mjs（从 furina_voice_cases.md 读表格打印人工评测
  prompt；自我声明"不调用模型"）→ **manual acceptance scenario**。
- 静态内容断言：✔ tests/persona-content.test.mjs（对 markdown 文件做字符串存在性检查，
  例如确认"Furina 是人类而非 Focalors 物种设定"字样）→ **content-file assertions**。
- 真实 runtime 模型评测：✘ 不存在。

### F3 Canon locator（只是 locator，不进 Canon truth）

- `references/furina_resource/03_story_timeline.md` 给出第四章 **Act II（仿若无因飘落的
  轻雨）/ Act III（向深水中的晨星）** 具名场景摘要与传说任务分幕时间线 —— 正对我方
  `missing_main_story_acts=['II','III']` 的证据缺位。
- 规则遵守：external repo = locator only；任何 C2 evidence unit 必须先回到官方来源
  （游戏内任务日志/官方资料）取得 locator 并经 `data/canon/furina_evidence_units.json`
  归因登记后才可使用。README/社区 wiki 汇编（含 moegirl 补充文档）不得直接采信。
- `11_sensitive_topics.md`/`ooc_rules.md` 可作为我方 red-team 用例补充素材（总结层面）。

### F4 Memory architecture 对照（collapse 判定）

单一 JSON store（skills/furina/scripts/furina-memory.mjs DEFAULT_STORE）同时承载：

```text
intimacy(0-10 亲密度) + interaction_state + soul_state/soul_energy(回忆深度/表达欲…)
+ profile(preferred_name/boundaries/style_preferences) + memories[] + notes[]
+ reflection_queue + sleep consolidation state
```

- 关系数值直接门控记忆 recall（proactive recall 需 intimacy ≥ min_intimacy 默认 6）——
  关系状态越权成为记忆检索的前置授权，混淆 C3/C5；
- profile 与 memories 同容器无 lifecycle 边界（C4/C3 混杂）；
- 无 source provenance、无 transition 事件、supersede 缺失（近似重叠 >0.68 直接 merge，
  consolidate 时 priority==1 且 strength<35 的条目被**静默丢弃**）；
- 为什么弱于 C1-C7：一个 store 同时扮演六个角色，任何一层污染全部层；无法回答
  "这个事实从哪句话来 / 这段关系何时因何变化 / 哪些是我的亲身经历而非用户画像"；
  删除不可审计。结论：REJECT 其持久化模型（但其 recall 相关性/强度 reinforce 公式、
  以及"情绪化 soul_state 作为表达风格旋钮"可作为前后端演示层的 LATER 参考）。

## 5. Genshin RP Skill audit

```text
Repository:      com554433/Genshin-Furina-RP-Skill
Default branch:  master
Audited SHA:     fa275c734b1da38bc406d6fe96e4b403875d23f9
Audit date:      2026-08-27
Relevant code roots: 无 runtime 代码；SKILL.md + manifest.json + references/research/*.md
                 + references/sources.json（2395 行内容，0 行程序）
Relevant tests:  无（README 徽章 "Tests 90% passing" 无对应物 —— false claim）
Reality Gate:    DOC_ONLY
License:         未附 LICENSE 文件（默认保留所有权利 → 内容只可总结引用，不可复制）
```

### G1 Implementation reality

runtime ✘ / memory engine ✘ / user model ✘ / relationship engine ✘ / retrieval ✘ /
tests ✘ —— 只有 prompt（SKILL.md）、skill 元数据（manifest.json）、研究笔记
（research/01-06）与来源清单（sources.json）。其自评徽章（Quality 89% / Evidence 85% /
Tests 90%）为无对应物的自我评分，不构成证据。

### G2 Character epistemic boundary（可提炼的边界规则素材）

SKILL.md 提供 knows/doesn't-know 清单的朴素二分（知道枫丹史/审判流程 vs 不知道旅行者
来历/他国详情/提瓦特全史）。与我方 C1/C2 对照发现两类问题：
- **时期混同**：把"知晓芙卡洛斯计划全部细节（预言/神格分离/审判计划）"写作无条件
  事实，同时其 research/01-setting.md 又写明"神格继承记忆、人格继承身体精神"——
  若人格即芙宁娜，则"她全知计划细节"与前裁判期叙事冲突；我方模型按 episode 记录
  `furina_knew / furina_did_not_know` + 时间锚，能表达"何时尚不知/何时得知"，该 repo
  不能。
- **边界粒度**：静态清单 vs 我方 per-episode 证据归因。其清单可作 red-team 提问素材
  （"审判前你叫什么名字？""你和芙卡洛斯什么关系？"类），映射到 tests 层面归入我方
  persona/canon 挑战用例（仅概念采纳 ADAPT-LATER，Phase 15 不需要 patch）。

### G3 Source quality 分类（信息性；不接受其自评 reliability）

sources.json 15 条：`official`（baike.mihoyo 角色页/官方明细等 5 条）、`wiki`
（Bilibili 原神 WIKI、Fandom 类）、`media`（新闻/视频报道数条），字段带自评
very_high/high 与 sha256 contentHash。分类可用作 locator 索引；自评 reliability 不予
采信，一切 C2 引用以我方 TIER 协议复核为准。

### G4 Identity conflict（red-team cases 登记）

1. SKILL.md 开头将"魔神名芙卡洛斯"作为芙宁娜的直接同位语，research/01-setting.md
   称"两个都是水神，是一个人撕成两半"、"神格继承了水神的记忆"——若按此表述让角色
   承认"我就是芙卡洛斯/我记得五百年前的神性经历"，将违反 C1 硬边界（同源 ≠ 共享
   运行时知识/身份混同； canon 上人格半身并未继承神格记忆）。
2. "她知道芙卡洛斯计划的全部细节"的全知条款可用于探测时期错乱（如审判前情形下问
   "神格现在枢机里怎么样了？"应属不可知域）。
3. 修复方向（不实施）：上述两条均已在我方 C2 里有正确的表达载体
   （episode.knowledge_boundary + K ancestry 边界），无需外部修正。

## 6. Miru deferred status

判定 BLOCKED / DEFERRED：本机探测（git ls-remote https://github.com/kiyotakali/Miru、
raw README 抓取）未能取得足够开放的 cognitive backend 源码树进行代码级审计；
因此**不基于 README 作出任何实现性主张**。待上游公开足够源码后可在后续增补审计，
不影响本报告结论。

## 7. Cross-repo comparison matrix

| 维度 | Furina（现况） | AronaAI | Furinelle | RP Skill |
|---|---|---|---|---|
| Canon 边界 | C1+C2 版本化/只读/归因 registry | 无概念（世界观知识=RAG） | 参考资料汇编（mix wiki/moegirl） | research 笔记（含时期混同） |
| Persona | 证据表+面具分层+情绪驱动 | 固定人设 prompt（阿洛娜） | 纯 prompt 维度表（丰富但 static） | 纯 prompt |
| Persona Eval | pytest 化 validator/identity/coherence 测试 | smoke 脚本级 | manual 场景 + 内容断言 | 无（虚假徽章） |
| Interpretation | 确定性优先 interpreter（confidence/temporal_scope 字段，candidates≠truth） | LLM 抽取为主 + regex 兜底 + 写入校验/quota/dedupe | 规则 hint 分类（type hints） | 无 |
| C3 记忆 | MemoryEngine 单一权威 + provenance + archive | 键值 facts（无事件溯源、物理删） | JSON 数组（merge/静默丢弃） | 无 |
| C4 用户模型 | supersede/complete + 时效 + transition 溯源 | upsert/delete + hot keys + goal 保护删除 | profile 混在全局 JSON | 无 |
| C5 关系 | 多维因子 + 短期回归 + milestone 溯源 | 三维气候 + 日帽/基线回归 + 气候分区门控 | intimacy 数字门控 recall（冲突） | 无 |
| C6 事件真源 | append-only 白名单 timeline + bridge exactly-once | 无（only last_injected_at 簿记） | 无 | 无 |
| Retrieval | derived index（non-auth，lexical 退化）+ ranker(authority/recency) | SQLite+FTS5+Chroma 混合 + 时间感知 + 冷却（强） | token 重叠 + strength | 无 |
| Context | context.py 分桶 bounded 快照（owner 冻结） | history/mem/knowledge/planner + token 预算裁剪 | 渲染 markdown 模板 | 全文塞入 |
| Proactive | presence/attention 投标 + Director 心智动作（注意驱动） | 定时 ticker + 时段窗 + quota/mute 簿记 + goal 跟进 | reflection_queue 手动提示 | 无 |
| Provenance | 全链事件 id 精确绑定（row→T→U） | source='deepseek'/'regex' 仅标签 | 无 | sources.json locator |
| Restart | sqlite/json 全持久 + process_pending 幂等 + worker daemon | SQLite/JSON 持久 ✔ | JSON 持久 ✔ | n/a |
| Tests | 1232项 pytest ×3 绿 | standalone 脚本（有实质但无 CI） | node:test 有效单测（无 CI） | 无 |

## 8. External Delta Matrix

| ID | External repo | External file/path | Actual mechanism | Our current equivalent | External advantage | Our advantage | Conflict? | Decision |
|---|---|---|---|---|---|---|---|---|
| D-A1 | AronaAI | backend/app/memory/store.py (`_hybrid_score_map`,`_time_aware_score_map`,jieba FTS queries) | FTS5 候选 ∪ 向量候选→余弦重打分 max 合并；相对日期展开为时间 FTS 查询组 | furina/cognition/retrieval/{index,ranker,retriever}.py：语义 index + authority/recency ranker；embedding 缺失才 lexical 退化（非混合） | 词法∩向量互补提升召回；"哪天…"类时间问句命中率高 | index 非权威、可重建、authority 分层 | 否 | **ADAPT**（15E） |
| D-A2 | AronaAI | backend/app/memory/store.py (`_filter_injected_recently`,`last_injected_at`) + orchestrator.py:195 | 注入冷却：近期已注入记忆抑制重复注入 | furina/cognition/context.py 分桶限额，无重复抑制 | 降低自传体反复复读感，不改真值权威 | 真值仍在 source stores | 否 | **ADAPT**（15E） |
| D-A3 | AronaAI | backend/app/memory/extractor.py EXTRACT_SYSTEM + query_time.py | 写时时间归一化：相对时间→绝对日期阶梯/区间/周期保留；goal 只许显式删除（代码级） | furina/cognition/interpretation/interpreter.py 仅剥离时间前缀（"这周/今天"）；candidate.temporal_scope 字段未解析 | 事实写入即刻具备精确时间语义，后续过期推理可用 | 我们 candidates≠truth、写入门控完整 | 否 | **ADAPT**（15B/15D） |
| D-A4 | AronaAI | backend/app/proactive/{goal,scheduler,hub}.py + ProactiveState JSON | 基于存储 goals 的稀疏跟进循环：最旧未访优先、拒绝 mute、每日上限、冷却持久化跨重启 | furina/behavior/motivation.py + runtime/scheduler.py：presence 注意投标/Director 动作；C4 ACTIVE PLAN 无主动跟进消费者 | 让"说过的计划"产生长期照料行为而不喧宾夺主 | 我们的社交投标/忽略反馈闭环 + fail-closed 更强 | 否（须走我们 R8 语义） | **ADAPT**（15F） |
| D-A5 | AronaAI | backend/app/relationship/{state,policy}.py | Δ 惯性 + β·baseline 回归 + daily_abs_cap 日帽 + makeup；climate 区→动作门控（不外显数字） | furina/relationship/engine.py 多维因子、trust 慢速、短期维度 decay 回归；**无日帽、无全局基线配置、无分区策略消费** | 防连击刷值/防漂移；气候区直接映射 proactive 静默权 | milestones 带 provenance；维度更细 | 与"不可见数值"产品哲学一致，需 careful | **ADAPT**（bounded：日帽+慢气候区作为 15F 政策输入；位置请外审裁定） |
| D-F1 | Furinelle | references/prompt/_shared_runtime.md（压力 0-3 表） | 压力等级→语言形态单调收紧的可执行行为表 | 情绪/被戳穿分层证据（FUR-006/007/008）驱动 persona planner | 形态梯度可直接作为评测 oracle | 已有底层状态机 | persona 属后续阶段 | LATER |
| D-F2 | Furinelle | skills/furina/references/furina_resource/03_story_timeline.md | Act II/III 场景具名列（locator） | data/canon missing_main_story_acts=['II','III'] | 提供取证线索 | 我们有官方协议保证不采信 community 文本 | 否（locator-only） | **ADAPT-as-DATA**（15A 数据采集线索，非代码） |
| D-F3 | Furinelle | scripts/furina-eval.mjs + tests/persona-content.test.mjs | 手工场景表生成器 + 内容断言 | tests/persona/*（更强） | — | 我们已有自动化身份/连贯性测试 | 否 | NO_CHANGE |
| D-G1 | RP Skill | SKILL.md（knows/doesn't-know 表） | 角色可知边界朴素清单 | C2 episode.furina_knew/did_not_know + 知识边界字段 | 提供提问攻击面灵感 | 期间化粒度远胜 | 期批评审后可作 red-team 用例输入 | REJECT（机制）/留作用例素材 |
| D-G2 | RP Skill | references/sources.json | 类型化来源清单+contentHash | furina_evidence_units.json + SOURCE map | hash 思路可在未来采集器参考 | 已有 tier/USED/FORBIDDEN 协议 | 否 | NO_CHANGE |

False-positive guard 复核：D-A1..A5 均满足 §14 六条件（代码存在/我方无等价/改善真实
行为/不违 C1-C7 权威/属 Phase 15/可测试）；D-F3/D-G2 因等价或更优判 NO_CHANGE；
D-G1 机制级 REJECT。

## 9. TOP actual useful deltas（共 5 条，不足 10 不硬凑）

**T1（ADAPT，15E Retrieval Maturity）时间感知混合检索**
- problem：当前 derived index 对专有名词/精确日期类查询召回不稳（纯语义相似度+metadata）。
- external mechanism：AronaAI FTS5∪vector 余弦重打分 + 相对日期展开多查询 + jieba。
- why useful：词法与语义互补；时间改写解决"昨天说的""上周约的"类检索。
- our gap：`furina/cognition/retrieval/index.py` 无混合通道（lexical 仅作退化）。
- target：15E。risk：index 仍必须 non_authoritative（重建幂等），不得变成第二真源。

**T2（ADAPT，15E）注入冷却**
- problem：同一记忆可能在相邻回合反复进入上下文（体验上复读）。
- external mechanism：last_injected_at + cooldown 秒窗抑制重复注入。
- our gap：`furina/cognition/context.py` 只有桶配额，无近期注入簿记。
- risk：冷却只在装配层生效，绝不影响 source stores 与 salience 计算。

**T3（ADAPT，15B/15D）C4/C3 写时时间归一化**
- problem："我今天准备完成X"写入时把绝对日期丢掉（只存记录时刻），日后无法做
  到期/拖延推断。
- external mechanism：抽取时按【当前时间】把相对表述解析到年月日/年月/年，区间与
  周期保留结构化表达，解析失败宁缺勿猜。
- our gap：interpreter 只剥离时间前缀；user_model 无 due/when 语义列（有
  declared_at/temporal_uncertain 可扩展）。
- risk：不确定解析必须落 temporal_uncertain=true 并保持候选≠真值门控。

**T4（ADAPT，15F Persistent Loop）C4 plan/goal 的主动跟进**
- problem：用户说过"准备完成X"，系统永不主动过问完成情况——C4 只是静态档案。
- external mechanism：goals 驱动的稀疏跟进（最旧优先、mute-on-dismiss、max/day、
  冷却持久化），由 social bid 机制承载。
- our gap：motivation/scheduler 无 C4 ACTIVE PLAN 消费者。
- risk：必须嵌入我方 presence/attention 投标与 R8 fail-closed 生命周期；禁止固定定时
  直发（brief 5.11 警告）。

**T5（ADAPT，bounded；定位请外审裁定 C5-hardening or 15F）关系日帽 + 慢气候分区**
- problem：正反馈事件连击可以在短窗内显著推高因子（我方仅 clamp 上界+trust 慢速）。
- external mechanism：daily_abs_cap + 向基线的慢回归 + climate 区驱动 proactive 门控
  （保持不可外显）。
- our gap：engine.apply 无日累计上限；无分区消费。
- risk：不得引入可见好感度；分区只能作为内部政策输入并保留 milestone 溯源不变。

## 10. Explicit NO-CHANGE areas（我方已更强，冻结不动）

```text
C1-C7 分离本身（外部最佳实践者也在关键处互相 collapse）
C6 append-only 客观事件真源 + EventBridge exactly-once/失败不毒化（Arona/Furinelle 无对应物）
exact event provenance（row→T→U、transition_event_id、source_event_ids 全链）
C2 只读版本化 Canon + 56 单元 evidence registry + PARTIAL 如实暴露
derived vector/semantic index 的非权威性与幂等 rebuild
MemoryEngine 唯一 formation authority（对比 Arona LLM 直接增删 durable fact）
presence/attention 社交投标模型（对比 A6 确定性 ticker）
C3 archive(reason) 无静默删除 + reinforcement 累证（对比 Furinelle consolidate 静默丢弃）
```

## 11. REJECTED external patterns

```text
intimacy 数字门控记忆检索 / 可见心 meter（Furinelle PROACTIVE_RECALL_MIN_INTIMACY、intimacy 0-10）
单 JSON 混装 memory/profile/relationship/soul（Furinelle DEFAULT_STORE）
LLM 直接 upsert/delete durable truth 且无说话人校验（Arona EXTRACT_SYSTEM，仅 prompt 约束 user-sourced）
向量库副本与权威行双写同步（Arona memory store ↔ Chroma，check_memory_sync.py 自证风险）
README 徽章代替实现（RP Skill "Tests 90% passing" 无测试文件）
角色全知条款与时期混同（RP Skill knows-all-plan / "一个人撕成两半"身份混同 → 违反 C1）
物理硬删事实（无 tombstone/supersede 历史：Arona delete、Furinelle consolidate drop）
```

## 12. LATER items（移出 Phase 15）

- 打断/话轮 router（Arona turntaking/{buffer,speaker,rules,llm_router}）→ Phase 22
  Voice/Interaction。
- 生日/节日/午休关怀时段提醒（Arona proactive care/festival slots）→ Phase 19 UI/20
  Embodiment 层（跟随桌面体验设计），且须换我方 bid 机制。
- Persona 压力形态阶梯作评测 oracle（Furinelle 0-3 表）→ Persona 打磨阶段（15 之后）。
- Miru 后端开源后的补审计 → Phase 15 增补任务。

## 13. Proposed Phase 15 patch candidates（仅列候选，不写任务书）

| # | subphase | files likely affected | behavioral contract | expected tests | necessary? |
|---|---|---|---|---|---|
| P1 | 15E | furina/cognition/retrieval/index.py, retriever.py（新增 fts 子模块可选） | C6/C3/C4 文本列建可重建 FTS5 辅助索引；retrieve=词法∪语义重打分融合；index 仍派生/非权威 | 索引重建幂等；缺失退化=现状；混合排序优于单路（fixture 断言）；非权威标记不变 | 需要（召回质量真实缺口） |
| P2 | 15E | furina/cognition/context.py（+ stores 记录 injected_at） | 近 N 秒已注入记忆降权/跳过；仅装配层效果 | 冷却生效/到期恢复；source stores 零变更断言 | 需要（低风险高体验收益） |
| P3 | 15B/15D | furina/cognition/interpretation/interpreter.py, stores/user_model.py(models/base 迁移) | 写时把相对时间解析为结构化 when（granularity: day/month/year）；失败→temporal_uncertain；周期表述保留原文语义 | 解析正确性表驱动用例；失败不落 uncertain=false；既有判定回归全绿 | 需要（使 plan/goal 生命周期可推理） |
| P4 | 15F | furina/behavior/motivation.py, runtime/scheduler.py | ACTIVE PLAN 驱动的稀疏关心跟进：进 social bid 通道（presence 必须、deadline/ignore 语义复用）、每日上限+mute+冷却持久化 | 无 presence 不发；ignore 后 mute；重启后配额/冷却保持；direct 对话优先不受阻 | 需要（C4 闭环缺失是真实产品缺口） |
| P5 | C5-hardening / 15F（定位待审） | furina/relationship/engine.py（+ settings） | apply 增加每日累计绝对增量上限；新增慢气候分区（内部字段）作为 motivation 门控输入；里程碑溯源契约不动 | 连击触发日帽断言；跨日重置；分区驱动 silence 断言；milestone provenance 回归 | 待审：改进真实但有架构定位问题，勿自行开工 |

各候选独立评审、ONE at a time 实施；任一被否决不影响其余。

## 14. Final recommendation

外部参考确认存在 5 个机制级真实 delta（T1-T5）与 1 个数据取证线索（Act II/III locator），
建议进入 Reviewer 过滤 → Delta Decision 流程。

```text
PHASE15_EXTERNAL_AUDIT_COMPLETE_PATCH_CANDIDATES_FOUND
```
