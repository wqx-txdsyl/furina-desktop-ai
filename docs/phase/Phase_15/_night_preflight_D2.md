# Night Preflight B2 — D2 Real Hybrid Retrieval（READ-ONLY，未实施）

任务书：`docs/phase/Phase_15/08_Phase_15_D2_Hybrid_Derived_Retrieval_Task_Brief_EXACT.md`
基线：`391bed8`（只读检查）

## 1. "SemanticVectorIndex" 实际哪里没有 vector

`furina/cognition/retrieval/index.py`：
- `lookup()` (L134-147) = 中文 **2-gram 子串命中计数**：把 query 去标点后取相邻二字
  集合，对每个 item 的 `text+keywords` 数 hits，降序取 top_k。纯词法。
- 构造参数 `embed_fn` **从未被调用**（存进 `self._embed_fn` 后全程无人引用）——
  接口已预留但零实现；
- 持久化 = `cognition_index.json` 平面 JSON `{marker,version,built_at,items[]}`，
  items 仅 {store,ref_id,text,keywords}，**无向量字段**；
- ranker.py 的 relevance 同为词法/元数据加权（authority .30 / relevance .25 /
  recency .15 …），无相似度模型参与。

结论与外审 Correction A 一致：**真实向量检索不存在**，缺口比"缺 hybrid 融合"更大。

## 2. 最小 embedding backend 选择

约束回顾：pyproject 现有依赖仅 numpy/aiohttp/httpx 等；无 torch/sklearn/faiss/
chroma/sentence-transformers。AronaAI 用本地 BGE 模型 + Chroma——引入 100MB+ 模型
与新重依赖不符合本项目最小正确原则。

推荐分层方案（接口先行）：

```text
Layer 0（必须）：deterministic fallback vector —— 基于 Unicode bigram 的
  hashing trick（固定 dim=256, numpy L2 归一）。纯词法但可被同一 cosine 管线
  统一，替代现 lookup 的临时打分；无新依赖、离线稳定、完全 deterministic。
Layer 1（可选注入）：真正神经 embedding = 由 embed_fn 注入点接外部 provider
  （现有 httpx 即够；是否用 GLM/Zhipu embedding endpoint 由任务书决策 +
  key 存在性决定）。无 key 时自动落回 Layer 0，产品行为不劣化。
```

不选本地大模型：下载/许可/体积/离线风险不成比例，且 brief 未要求语义质量上限。

## 3. 是否需要 Chroma —— 否

- 我们索引的 ref 是 `(store, ref_id)` 内部引用，权威永远在 sqlite source stores
  重查（master plan D2 hard invariant #4）；向量只是**提示排序**；
- 项目当前规模（C2 20 episodes + C3/C4/C7 有界条目）在千级以内，numpy 矩阵暴力
  cosine（float32, dim≤1024）微秒级，无 ANN 必要；
- 引入 Chroma 会复制 AronaAI 的双写同步病（其自备 check_memory_sync.py 佐证），
  违背 derived/non-authoritative 冻结边界的精神。

## 4. lexical ∪ vector 最小正确实现

```text
candidates =
    lexical_hits(q)                      # 现 2-gram 逻辑保留为一路
  ∪ vector_topn(q)                       # cosine ≥ min_sim（如 0.30）
dedupe by (store, ref_id)，分数归一后交给既有 ranker 重排
→ top_k refs → 调用方权威重查（context.py 已如此消费）
```

幂等保证：`build()` 先清空重建（现有实现即幂等）；新增 items[].vec 后
`delete()/rebuild()` 不变。vector 缺失/损坏的 fallback = Layer0 hash 向量恒可用，
故"embedding unavailable → deterministic lexical retrieval"天然满足。

## 5. index metadata/version 设计

```json
{"marker": {...derived/rebuildable/non_authoritative...},
 "index_version": "<bump>",          // 引入 vec 字段时 bump
 "embed": {"backend": "hash_bigram_v1|provider:<name>", "dim": N},
 "built_at": ...,
 "items": [{store, ref_id, text, keywords, vec?: [float32...]}]}
```

status() 增加 backend/dim 透出，供 T-corruption/运维检查。损坏路径已有
（JSON decode fail → 空 index + 词法退化，log warning）；补一类
"vec 维度不符" 丢弃单条的韧性测试。

## 6. 最大 corruption/fallback 风险

1. **静默退化**：provider 抖动导致全量 hash 向量 → 召回质量下降但无告警。缓解：
   status() 记录 backend 实际使用率 + 一条 log.warning 节流提示。
2. **索引无界增长**：build 无 cap。建议 build 时强制上限（如 ≤5000 条，超出截断
   最旧 C3/agent 条目并计入 status.truncated），保 bounded 内存/加载时间。
3. **维度漂移**：切换 backend 后旧文件 vec_dim 不符 → 单条跳过策略 +
   version 不匹配直接触发 rebuild 提示。
4. retrieval 侧误把 vector 分当 truth 的回归风险 → master plan I2 场景测试锁
   （superseded C4 不因高分压过 active 真值：ranker authority 权重已在位）。

以上均为记录；未做任何实现。

## Night Long-Run 增补（第二轮只读，未实施）

- **最小接线点已锁定**：全仓唯一"refs 变行"咽喉 = `furina/cognition/context.py::
  assemble()` 的分桶构造段（memories/events/user/agent 各自 store 直查处）。接线 =
  在该函数入口先用 `hub.lookup_index(query)` 取 hints（仅提示排序/配额偏置），再照旧
  走权威 store 查询取真实行；除这里与 `retriever.py` 的 C2 检索外不新增消费点。
  （此前盘点 F-1 的落地答案。）
- **零新依赖向量可行性**：确认可行 —— numpy 已是直接依赖；Layer0 hash-bigram(dim≤256)
  纯确定性；provider 注入用 httpx 即达。无需 torch/sklearn/faiss/chroma。
- **hash 基线 vs 真 embedding 对照**：hash 词面召回强（专名/精确词命中稳）、零语义泛化；
  provider 向量补 paraphrase 与跨表述召回但有成本/离线失效/维度一致性问题。
  结论维持两层数据模型：backend 字段入 index JSON，质量劣化必须可见（status()
  透出 backend 实际使用率），fallback 永远可达。
- Phase16 审计交叉印证：hermes-agent 的 artifacts/mime 白名单思路与本任务无关（勿混入）；
  无新增依赖引入理由。
