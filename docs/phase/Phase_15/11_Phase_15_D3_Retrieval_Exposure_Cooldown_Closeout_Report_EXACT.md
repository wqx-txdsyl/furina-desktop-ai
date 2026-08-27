# Phase 15 — D3 Retrieval Exposure Cooldown
# CLOSEOUT REPORT — EXACT

## 1. Result

```text
READY_FOR_REVIEW
```

（不宣告 D3_PASS / PHASE15_PASS；判定权在外部 reviewer。）

## 2. Baseline / Branch / SHA

```text
accepted D2 SHA（PART 0 已 --ff-only 快进集成分支并推送）: 55c5959780883b0d0504653dfab9a4e6958e4c8b
task branch: feature/phase15-d3-retrieval-exposure-cooldown（自 55c5959 切出）
D3 主实现 commit : 3267ba7480f42ccba27542fbb110e4115384de8c
reviewer blockers 修复（功能+测试）: 5e14f3dc9cf5bb0cc8e18bc91cf02d863bdbf89a
final local SHA : 见 §10（本任务最后 commit；push 后校验 local == remote）
final remote SHA: == final local SHA（push 后校验）
```

## 3. Exposure Model

- **结构**：`RetrievalExposureLedger`（`furina/cognition/retrieval/exposure.py`）——
  `OrderedDict[ref_key → last_exposed_monotonic]`；ref_key = `f"C3:{mem_id}"`；
  LRU 容量 256、TTL 900s（均可注入），到期/淘汰即恢复资格。
- **属性**：OPERATIONAL / DERIVED / SESSION-LOCAL / NON-AUTHORITATIVE。
  进程内纯内存，无迁移、无持久化文件；重启即清空。
- **受影响 store**：仅 C3 记忆桶的**自动注入排序**。C4/C7/C2 桶与 C5/C6 完全不经账本。
- **mark 时点**：`CognitiveContext.assemble()` 成功构造并通过 `is_bounded` 校验后，
  对最终入选（`selected_objs[: memories]`）逐条 mark —— **最终装配失败/中止绝不
  标记**（异常向上传播、`return ctx` 未到达 → 零记录，T6）；**fallback 成功进入
  context 后仍标记**（fallback 对象同样落入 `selected_objs`，与主路径共用同一 mark
  点）；被 ranker 排除/候选池截断的对象一律不标（T4/T5）。

## 4. Explicit Recall Bypass

`is_recall_intent()`：确定性 bounded 正则（你还记得|**刚才那个**|刚才你说/提|再说说|
再说一次|重复一下|之前说/提的/过 等）；**「刚才那个…」为任务书锁定说法**，已命中；
绝不调 LLM。

实测 trace（D3 测试 `test_d3_t2b_explicit_recall_bypasses_cooldown` +
`test_d3_t2e_recall_bypass_with_locked_phrase`）：

```text
“冷萃咖啡”         → ctx 含「用户喜欢喝冷萃咖啡」（首现并标记）
“聊聊咖啡相关的话题” → ctx 不含该记忆（TTL 内抑制生效）
“你还记得我说的咖啡吗”→ ctx 再次含该记忆（显式召回绕过冷却）
“给我讲讲咖啡吧”    → ctx 不含该记忆（非召回措辞 → 冷却抑制）
“刚才那个冷萃咖啡的配方再讲一遍” → ctx 再次含该记忆（锁定说法绕过冷却）
```

## 5. Truth Non-Mutation Proof

曝光循环前后对 C3 全量权威行做 (mem_id, content, status, timestamp) 四元组快照比对
（`test_d3_t12_c3_authoritative_rows_unchanged_by_exposure_loop`）：**完全相等**。
ledger 内部零 DB 访问（纯 OrderedDict）；stores/base.py 本任务零改动（§7 迁移行为）。

## 6. Failure Counterexample

注入式失败（monkeypatch events.query_recent 在上下文构造中段抛 RuntimeError）：
`assemble` 向上传播、leder.snapshot()=={} —— **候选已生成但装配中止 ⇒ 零曝光记录**
（T6）。同时非 active C3 在 HybridRetriever 解析层被丢弃不进入池（不影响曝光记账
正确性）；T15 锁定 recall 检测器零误报（负面样例含『最近怎么样』『明天要去体检』等）。

## 7. Tests

| Gate | Scope | Result |
|---|---|---|
| A（new D3 tests） | tests/cognition/test_phase15_d3_exposure.py | **19 passed**（16 + t2e/t1b/t7b；T9/T15 增强） |
| B（all D2 retrieval） | hybrid + residual 两套件 | **37 passed** |
| C（D1 + D4 + Phase14 provenance） | d1_canon_evidence + d4_temporal + Phase14 三件套 + r7r10 | **133 passed** |
| D/E 合（cognition 全目录） | tests/cognition | **278 passed**（275 + 3 新增） |
| F（FULL SUITE） | 全仓库 | **1343 passed / 0 failed / 0 skipped**（原 ×2：334s/320s 各 1340；reviewer 修复轮 ×1：285s 1343） |

静态审计要点（执行令 §5）：单一代码策略点=RetrievalExposureLedger；唯一 mark 点=
context.assemble 成功返回前一处；生产零引用泄漏到 stores 层（grep 验证 0）；源层零
mutation；无双权威；无 LLM 召回分类；有界状态（LRU+TTL 双保险）。

## 8. Static Audit

另执行执行令清单全项 grep：RetrievalExposureLedger 仅 exposure.py 定义 +
hub/context 两处接线；assemble() 调用链、retrieval candidate paths、explicit-recall
检测、exposure mark 调用点均收敛于 context.assemble 单函数内；C1-C7 写入计数增量=0；
DB writes 增量=0（本任务未触碰任何 store/schema）。

## 9. Remaining UX Gaps

- 冷却窗口固定 900s/容量 256 为模块常量（可注入但未暴露到 AppConfig；如需运营调参
  另行任务）；
- 显式召回措辞为有限白名单（覆盖测试样例与常见说法；更广中文变体留待观察）；
- C4 当前真值桶未参与冷却（按 brief 有意排除）——若未来允许 user-fact 冷却须先过
  评审定义“当前事实”边界。

## 10. Git State

```text
commit 仅含 D3-scoped 文件（新增 exposure.py + test_phase15_d3_exposure.py；
改写 context.py/hub.py 接线；closeout 11 + 10 任务书入库）
reviewer blockers 修复 commit：exposure.py（「刚才那个…」锁定说法）+ 测试
（t2e/t1b/t7b 新增、T9/T15 增强）+ closeout 本文件 —— 未触碰任何其他源码
unrelated untracked（data/assets_v2/, scripts/assets_v2/, Phase_16/_night_*,
其余 _night_*/12-15 文档, nul）一律未 add/commit/move
final local SHA == final remote SHA 于 push 后校验；未 merge integration；未开始 D5
```

## 11. Final Line

```text
READY_FOR_REVIEW
```
