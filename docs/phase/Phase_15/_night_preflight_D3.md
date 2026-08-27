# Night Preflight B3 — D3 Retrieval Exposure Cooldown（READ-ONLY，未实施）

任务书：`docs/phase/Phase_15/10_Phase_15_D3_Retrieval_Exposure_Cooldown_Task_Brief_EXACT.md`
基线：`391bed8`（只读检查）

## 1. exposure 应在哪一层记录

**唯一咽喉点 = `CognitionHub.assemble()`（furina/cognition/context.py:50+）**：
所有进入 prompt 的 C3/C4/C2/C6/C7 都经它分桶装配。推荐：

```text
RetrievalExposureLedger 挂在 hub（session 生命周期）
    mark(store, ref_id) 仅在对应桶**成功并入 snapshot 之后**调用
rank 阶段读 ledger 给 C3 桶内近期已暴露 ref 一个乘性惩罚（如 ×0.35 或直接沉底阈值）
```

不选 bridge / retriever 层：retriever 只产候选不入 prompt（候选 ≠ 曝光），
bridge 是事件入口——都违背 brief "mark exposure only after successful context
inclusion"。

## 2. context assembly 成功的定义（可操作化）

```text
success(bag) := assemble 全程无异常
              AND 返回的 ContextSnapshot 已包含该 bag 的非空入选列表
按桶逐个判定：C3 桶成功才 mark 其 ref；
部分失败（某 store 抛错被内部 except 吞掉）→ 该桶跳过 mark —— 直接满足 D3-T10
（失败不得毒化曝光状态：没曝光就没记录）。
```

现状核对：assemble 内各 store 检索均 try/except 包裹，partial-failure 路径真实存在，
所以 ledger 挂在"装配完成点"而非"候选生成点"是必须的，不是偏好。

## 3. explicit recall intent 当前在哪里识别

**当前无处识别**（全仓无"你还记得/刚才那个"类意图判定）。Persona planner 有同类
deterministic regex 先例（persona_planner._CONFIDE_RE）。推荐：

```text
furina/cognition/retrieval/recall_intent.py（新纯函数模块）
is_recall_intent(text) -> bool   # 你还记得|刚才那个|再说说|之前(说的|那个)|想起来了吗
```

接线点：dialogue/app 在调用 assemble 时传 `explicit_recall=is_recall_intent(text)`
→ hub 对 C3 桶施加 bypass（惩罚系数=1.0，但仍是 bounded top_k）。
识别失败（False）只是回到默认冷却，安全；不会反向制造记忆抑制。

## 4. session-local cache 生命周期

```text
数据结构：dict[ref_key -> last_exposed_monotonic]，ref_key=f"{store}:{ref_id}"
容量：LRU 上限（建议 256 条），超限淘汰最旧 —— BOUNDED
TTL：默认 900s（可配；仅影响自动注入惩罚，不影响任何查询 API 返回值）
持久化：无（进程内存）；重启即清空 = 文档化语义（master plan §10 明示首选）
owner 归属：hub 由 owner 线程访问，无需锁；与既有 conversation 快照冻结语义一致
```

## 5. failure poisoning 风险清单

| 风险 | 缓解 |
|---|---|
| 候选生成即计数 → 后续装配失败"白冷却" | §1/§2 的 after-inclusion 才 mark |
| 显式召回被冷却压住（违反 D3-T3 底线） | bypass 参数仅作用于自动注入路径；显式路径恒 0 惩罚 |
| 冷却把真相藏起来（变成遗忘） | 只作用于 C3 自动注入排序；C4 当前真值/C6 当前事件/C7 关键态/C1 不入 ledger 范围（brief §4 白名单）+ 各桶上限不变（D3-T8） |
| ledger 无限增长 | LRU+TTL 双界 |
| 多次小失败累积成永久压制 | TTL 到期自愈；无任何写库行为 |

## 6. 最小方案结论

无需 durable schema、无需新 store、无迁移：ledger + recall-intent 纯函数 +
assemble 两处小改即可满足 T1-T10 全部断言场景。

## Night Long-Run 增补（第二轮只读，未实施）

- **explicit-recall 检测器确切插入点**：句子入口两级可选——推荐 A：owner ingress
  （App.submit_user_message 已在该处做文本 fx）计算一次 `recall=is_recall_intent(text)`
  并随 DirectTurn snapshot 冻结传递至 worker 的 assemble 调用（快照不可变、无共享态）；
  备选 B：worker 内 assemble(query=text) 前现算（更简单但把 NLU 放上 worker 线程，
  违背快照冻结美学）。**采用 A**。
- **exposure mark 确切点**：`context.assemble()` 构造完 ContextSnapshot、返回前一次
  try 内成功路径逐桶 mark；任一桶内部异常被吞即跳过该桶 mark（已有 partial-failure
  结构支撑，符合 D3-T10）。全库无第二写入点（防 poison 由"仅成功后计数"+TTL 双保险）。
- 夜审交叉核（Phase16 recon）：clawd 的 per-session 有界队列合并是为宠物 UI 状态
  防洪设计的传输层技巧，与本任务曝光惩罚问题不同构 —— 记录为"不迁移"，防止误搬。
