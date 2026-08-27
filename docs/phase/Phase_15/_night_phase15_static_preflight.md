# Night Phase 15 Static Preflight（READ-ONLY）— durable-writer inventory + 边界核查

基线：`feature/phase15-d1-canon-act2-act3-evidence @ 391bed8`（READY_FOR_REVIEW 状态未变）
方法：全仓 grep 生产代码（排除 tests/），逐 authority 盘点写入调用点。

## 1. Durable writer inventory

| Authority | 写入点（生产，唯一清单） | 判定 |
|---|---|---|
| C2 Canon Life | **无**。canon_history/sources/evidence_units 在 furina/ 内仅出现为只读路径常量与 docstring；store 无写方法（D1-T9 亦锁字节不变） | PASS |
| C3 Autobiographical Memory | `App._observe_with_provenance` →（fail-closed 门）→ `memory.observe(...,source_event_ids=[U])`；`CognitionHub._form_memory` ← `_apply_c3_candidate`/`_apply_consolidation`；consolidator 只产 plan 由 hub 落库。`app.py:1301` 为 cog=None legacy 壳（注释明示非生产路径，R6 已锁定） | PASS：MemoryEngine 单一 formation authority |
| C4 User Model | 全部经 `hub.user_model.upsert_item/supersede_item/complete_plan`（hub.py 312/328/362/476/494）；direct 入口带 R10-FC require_source_event 门 | PASS 无 bypass |
| C5 Relationship | `relationship.apply()` 调用点 = app.py 420/1252/1267（owner 文本 fx）、scheduler.py 432/1195/1227（事件反馈）、memory_engine.py 100（内部 decay 逻辑）；milestone 仅 hub.py:368（带 provenance）。全部为 engine 常量 delta，无 LLM 直写、无新表 | PASS（架构既有 sanctioned producers；D5 未来只需注入 n-provider，不新增写者类别） |
| C6 Event Timeline | `events.append` 仅两处：bridge.py:59（owner curated 白名单桥）+ hub.record_event:156 | PASS append-only 单通道保持 |
| C7 Agent History | `hub.persist_agent_result/create_task/set_plan/add_step`（app.py:929 owner 调用；agent_runtime 仅注释说明 worker 不直写 DB） | PASS verified-truth 边界保持 |
| Derived Index | hub.build_index/rebuild/delete/status/lookup；写文件仅 `cognition_index.json`（marker=derived/rebuildable/non_authoritative 恒在档） | PASS 非 C8 |

## 2. 专项检查（night order PART C 第 3 条）

```text
unauthorized writer           ：未发现（上表即全量调用面）
vector-as-truth               ：未发现 —— index.lookup 只产 {store,ref_id} 提示；
                                 且当前生产代码无任何 lookup 消费点（见下"发现"）
direct C4 write bypass        ：未发现（唯一的 upsert 集群在 hub；R10-FC 门仍生效）
C2 runtime mutation           ：未发现
duplicate C3 formation author.: 未发现（observe 只从 App fail-closed 门与 hub 进入）
```

## 3. 夜审发现（记录，不在本轮处理）

F-1（对 D2 有用）：**derived index 目前是"建成但未接线"状态** ——
`hub.lookup_index` 无任何生产调用方；context.assemble 直查各权威 store。
D2 实施时必须决定接线方式（assemble 消费 refs）或在任务书中明确维持
standalone + 测试级消费。建议按 master plan I2/I3 场景把"refs → 权威重查"
链路正式接通。

F-2（对 D5 有用）： relationship.apply 的三个生产 producer（app 文本 fx /
scheduler 反馈 / memory_engine 内部）是既定 sanctioned 面；anti-spam 的
n-provider 应在该三处共用同一注入路径，避免出现第二套计数真相。

F-3（无害）：scheduler._recent_events.append 为内存去重簿记，非 durable，
已排除出 C6 清单以免歧义。

## 4. D1 HEAD 复跑结论

PART C #1 full suite @ 391bed8：结果见 morning handoff §8（与 D1 Gate E 同码一致复跑）。
