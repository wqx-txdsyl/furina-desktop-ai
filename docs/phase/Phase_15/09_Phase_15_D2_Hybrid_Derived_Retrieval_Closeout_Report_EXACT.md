# Phase 15 — D2 Hybrid Derived Retrieval
# CLOSEOUT REPORT — EXACT

## 1. Result

```text
READY_FOR_REVIEW
```

（不宣告 D2_PASS / PHASE15_PASS；判定权在外部 reviewer。）

## 2. Baseline / Branch / SHAs

```text
integration baseline（PART 0 已 --ff-only 快进并推送）: 7f93569cebbc05ae13eb7e14eb6b66d9e1088c13
task branch: feature/phase15-d2-hybrid-retrieval（自 7f93569 切出）
final local SHA : 见 §11（本任务最后 commit）
final remote SHA: == final local SHA（push 后校验）
```

## 3. Retrieval Architecture（实现即契约）

```text
AUTHORITATIVE STORES（C2/C3/C4/C7 真值；C1/C5/C6 不被检索触碰）
        ↓ build（选中摘要；有界 MAX_INDEXED_ITEMS=5000，超限截断并计数）
DERIVED INDEX（DerivedRetrievalIndex：store/ref_id/text/keywords/ts/status/vec）
        ↓
LEXICAL CANDIDATES（字符 bigram 重叠，deterministic，词法相似度）
        +
VECTOR CANDIDATES（cosine；向量由注入 encoder 生成）
        ↓
HYBRID UNION（按 (store,ref_id) 去重，保留成分分与 paths 标记）
        ↓
AUTHORITY-AWARE 解析（HybridRetriever：ref → 权威 store 取真实对象；
      缺失/删除 → 丢弃；非 active C3 → 丢弃）
        ↓
既有 RetrievalRanker（status-authority/recency/importance/confidence/strength
      + diversity 惩罚）确定性重排
        ↓
BOUNDED REFERENCES（assembler 桶上限 memories=3 等不变）
        ↓
CognitiveContext（plain immutable snapshot）
```

生产接线点（PART 9 硬门）：`CognitionHub.assemble()` 的 C3 记忆桶 ——
`HybridRetriever(index, autobiography).candidates(query, limit)` 先产出权威对象池，
再交既有 ranker；索引缺失/任何异常 → 回退原 `auto.retrieve` 路径（fail-soft 且 meta 可观察）。

## 4. Authority Proof（index 永不成为 truth）

- 命中只携带 (store, ref_id) + 成分分；最终对象一律回权威 store 解析（T17/CE3 孤儿引用
  直接丢弃，绝不合成真值）；
- C4 桶仍由 `query_active` 决定（T8/CE1：superseded 高相似度无法复活为当前真值）；
- C7 桶仍由 `query_recent` 权威状态决定（T9/CE2：FAILED 不呈现为完成）；
- C2 激活策略原样（T10/CE9：普通话题 activation=0、不 lore-dump）；
- C6 事件与 C5 关系不进入任何向量路径（域不混淆，PART 10）；
- 无任何 source-store 写入依赖 index 成功（静态审计 §9）。

## 5. Embedding Backend / Versioning

- 协议：`VectorEncoder.encode(texts)->List[Vector]`（`retrieval/encoders.py`）。
- 默认实现：`HashedLexicalVectorEncoder(dim=256, seed=0)` —— 字符 bigram 哈希投影 +
  L2 归一。**诚实分类：HASHED_LEXICAL_VECTOR（词法哈希向量），不是语义 embedding**；
  类名/kind/文档均不冒充 SEMANTIC_VECTOR。
- 可选注入：`ProviderVectorEncoder`（真实语义 provider 批接口；未配置则走哈希基线）。
- 元数据：index JSON 持久化 `{version: 15E.2, dim, backend, truncated, items[].vec}`；
  维度/版本不符 → 向量路径关闭（`vector_invalid`），lexical 继续，重建即恢复（T11）。
- 失败策略（PART 8）：encoder 异常 → `last_vector_error` 记录 + lexical 继续 +
  `status()` 可观测；损坏文件 → 视为缺失；删除/重建幂等且绝不触碰 source stores（T6）。

## 6. Counterexamples（实测锁定）

```text
CE1  superseded C4 高相似 vs active：C4 桶权威 query_active 胜出（T8）
CE2  FAILED C7 任务文本高匹配：仅以历史状态呈现，绝不 success（T9）
CE3  索引指向已删 ref：HybridRetriever 丢弃（T17/T19）
CE4  向量高分旧记忆 vs 词法分新真值：非 active 候选先滤（T5），域桶权威优先
CE5  encoder 崩溃：lexical 继续 + last_vector_error 可观察（T13）
CE6  删除索引目录：C2-C7 完整、可重建（T6）
CE7  lexical+vector 同源：union 去重单份（T3/T16）
CE8  “明天”三天前解析：读取零重解析（T11 spy）、due 已过仍 ACTIVE（T12）
CE9  普通问候句：activation=0 无剧情注入（T10）
CE10 大批量语料：桶上限与索引上限共同约束（T15）
```

## 7. Performance（实测台账，1500 条语料）

```text
insert 1500 mems       14.1s（既有写入面；与检索无关）
build_index(220 items) 0.046s
4 hybrid queries       23.3ms 合计（≈6ms/查询，纯本地 numpy）
final context          3 条记忆（桶上限内，bounded=True）
```
无网络依赖；向量在 build 时批量编码一次（无每查询 O(N) embedding API）；
60fps 循环零接触（检索只发生在 assemble 认知回合）。

## 8. Tests

| Gate | Scope | Result |
|---|---|---|
| A（new D2 tests） | tests/cognition/test_phase15_d2_hybrid_retrieval.py | **21 passed** |
| B（retrieval/context 既有） | phase15e + cognitive_stores + phase15f | **34 passed** |
| C（Phase14 provenance） | R6-R12 reviewer + failclosed + closure/residual | **78 passed** |
| D（D4 temporal） | test_phase15_d4_temporal.py | **31 passed** |
| E（cognition 全目录） | tests/cognition | **243 passed** |
| F（FULL SUITE ×2） | 全仓库 | **1308 passed / 0 failed / 0 skipped**（193s, 180s；1287+21） |

零 skip / 零 xfail / 零弱化断言。

## 9. Static Audit

```text
vector 结果写 source store   ：无（index 仅读写自身 derived 文件；source 写入面不变）
index 当 truth              ：无（T8/T9/T17/CE1/CE2/CE3 反向锁定）
新 C8 存储                  ：无（marker not_an_eighth_truth_store 恒在档）
raw secret 索引             ：无（C7 只索引 goal；original_request/secret 不进 index）
无界 C6 索引                ：无（C6 完全不进入 derived 投影）
重复 embedding 实现          ：无（唯一 encoder 协议 + 两个实现）
诚实命名                    ：2-gram 计分函数 = _lexical_ngram_score / lexical_lookup；
                              哈希向量 = HashedLexicalVectorEncoder(kind=HASHED_LEXICAL_VECTOR)；
                              SemanticVectorIndex 仅作兼容别名（hub/__init__ 引用点已注释）
C1-C7 writer 增量           ：0（本任务未新增任何真值写入方）
embed_fn 残留（memory_engine） ：既有 Phase15E 回忆检索钩子，与 D2 无关，未并入（§10）
```

## 10. Remaining Gaps

- 生产 wiring 当前只把 hybrid 应用于 **C3 记忆桶**；C4/C7/C2 桶保持权威查询/激活策略
  不动（有意为之：域语义 > 全局 top-k soup）。C4/C7 hybrid 提示化留待后续任务评估。
- `memory_engine.embed_fn`（Phase 15E 遗留的回忆检索嵌入钩子）未并入 D2 管线——
  与 index 无关的既有架构位，保持原样。
- `lookup_index()`（owner 便捷提示接口）现返回 hybrid union 引用；暂无 UI 消费，仅 API。

## 11. Git State

```text
commit 仅含 D2-scoped 文件（新增 encoders.py / hybrid.py / test_phase15_d2_hybrid_retrieval.py；
改写 index.py / context.py / hub.py / memory_store.py(+fetch) / autobiography.py(+get)；
closeout 09 + 08 任务书入库）
unrelated untracked（data/assets_v2/, scripts/assets_v2/, Phase_16/_night_*, 其余
_night_* 与 10-15 文档, nul）一律未 add/commit/move
local SHA == remote SHA 于 push 后校验（feature/phase15-d2-hybrid-retrieval）
未 merge 进 integration；未开始 D3/D5/Phase16
```

## 12. Final Line

```text
READY_FOR_REVIEW
```
