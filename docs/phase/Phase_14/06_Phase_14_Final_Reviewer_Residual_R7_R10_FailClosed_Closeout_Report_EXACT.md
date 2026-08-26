# Phase 14 Final Reviewer Residual R7-FC / R10-FC — Fail-Closed Closeout Report

## 1. Result

```text
READY_FOR_FINAL_REVIEW
```

Final PASS 由独立 reviewer（GPT-5.6 Sol）判定，本报告不自行输出
`PHASE_14_FINAL_GATE_PASS`。

## 2. Baseline / branch / final SHA

- baseline_sha: `102d46b56c7e27fa37ba180d43e12b203ca5fd39`
- baseline 确认：编码前 `git rev-parse HEAD` == `102d46b…` == 远端
  `refs/heads/fix/phase14-final-reviewer-r6-r12`。
- branch: `fix/phase14-final-r7-r10-failclosed`（自 baseline 切出）
- implementation commits：见 §11 commit 列表；final local SHA / final remote SHA =
  任务最后一个 commit 的完整 SHA（push 后 `git rev-parse HEAD` 与
  `git ls-remote origin fix/phase14-final-r7-r10-failclosed` 必须一致）。

## 3. Modified files

| file | why changed | contract affected |
|---|---|---|
| `furina/cognition/stores/canon_history.py` | **R7-FC**：新增全局 evidence 引用完整性层 `_unregistered_evidence_refs()`（覆盖 EVERY episode，与 quest/act/source_type/主线/USED 无关）；`_evidence_attribution_conflicts()` 改为「A 引用完整性先行 + B 归因兼容性」分层；`_life_stage_source_status()` 增加首个分支：任一未注册引用 → `GAPS:unregistered_evidence=[...]` | metrics 键不变、语义收紧（生产数据零缺失 → 输出串全部保持原值）；私有方法名新增，无删除 |
| `furina/app.py` | **R10-FC §4.4**：`submit_user_message` 区分路径 A/B —— canonical USER_MESSAGE 记录成功 → `apply_user_message(..., source_event_id=U, require_source_event=True)`；记录失败/桥不可用/空 id → 不调用 apply，记可观察 warning，对话继续（freeze/enqueue/reply）。USER_MESSAGE 与 DIRECT_TURN_STARTED 拆成独立 try | 生产 direct 回合的 C4 durable 演化 fail-closed；turn 终态保证、FIFO、deadline 契约不变 |
| `furina/cognition/hub.py` | **R10-FC §4.5** defense-in-depth：`apply_user_message` 新增 `require_source_event=False` 可选参数；为 True 时 `source_event_id` 必须解析到一条真实存在的 canonical USER_MESSAGE（`life_events` 中 event_type='USER_MESSAGE'），否则整体跳过并返回 `{..."skipped": "missing_canonical_user_message"}` | 默认值 False → 孤立确定性单测不受影响；生产 direct 路径统一走 True |
| `furina/cognition/bridge.py` | **R10-FC §4.6**：`record` 的 `_seen[key]=True`（含 trim）移动到 `events.append` **成功之后**；失败不再毒化重试 key | exactly-once 语义保持（成功后 dedupe）；单 owner 线程调用契约不变 |
| `tests/cognition/test_phase14_final_r7_r10_failclosed.py` | **新增** 14 个 reviewer-locked 测试（R7-FC-T1..T4、R10-FC-T1..T8+T9/T10 编号见 §10-Gate A） | 新测试；未修改任何既有测试 |
| `docs/phase/Phase_14/00_MANIFEST.md` / `RECOVERY_LEDGER.md` / 本文件 | 文档协议（§0） | 文档 |

未触碰：`furina/memory/**`（无新记忆写入方）、`director/**`、`scheduler.py` 社交投标语义、
interaction 事件语义（R11）、`pyproject.toml`（R12）、`data/canon/*`（零改动）、`nul`（保持 untracked）。

## 4. R7-FC closure

**Previous hole**：`_evidence_attribution_conflicts()` 在进入 evidence 检查前有

```python
if (e.act or "") not in ("I", "II", "III", "IV", "V"):
    continue
```

因此 act=null / 跨度（I-V）/ 非主线的 episode 可以携带 `evidence_ids=["不存在的ID"]`
完全逃逸校验 —— 有效 USED source + 缺失 evidence + 非精确 act → 无 dangling、无冲突、
无 gap、无重复 → 语义完整性可能 false-green。

**Global validator shape**（三层分离，方法名按 brief §3.3 允许自定）：

- A 引用完整性：`_unregistered_evidence_refs()` —— 对 EVERY `CanonEpisode.evidence_ids`
  全量解析到唯一注册单元；不依赖 quest / act（精确或跨度或 null）/ source_type /
  是否主线 / 来源是否 USED；有效 source_id 不能挽救缺失 evidence_id；
- B 归因兼容性：`_evidence_attribution_conflicts()` = A 层结果 + 原精确单幕 act 归属
  矛盾判定（A 层已在 entries 内的报告不重复计数）；
- C 覆盖层：`_act_support_gaps()` / `_main_story_act_coverage()` 保持原语义。

`mandatory_life_stage_source_status()` 首个分支消费 A 层结果 → 任一缺失引用即
`!= SOURCE_COMPLETE`（且与 `canon_span_status` 彻底解耦——后者保留 legacy 结构指标）。

**Exact metrics after**（fixture 同 brief §10 Counterexample G）：

```text
episode.act=null + source_ids=[SRC-001 USED] + evidence_ids=["FUR-NOT-REGISTERED"]
  unregistered_evidence_ids         = ['FUR-NOT-REGISTERED']
  mandatory_life_stage_source_status = GAPS:unregistered_evidence=['FUR-NOT-REGISTERED']
  canon_span_status（legacy 结构层）  = MANDATORY_SPAN_SOURCE_COMPLETE   ← 不变
span-act "I-V" 变体同上（同样失败）。
```

**No fabricated evidence / truthful PARTIAL kept**：生产数据（56 单元 registry、64 条
episode→evidence 引用）零缺失、零冲突，本修复对生产输出零改变：

```text
missing_main_story_acts            = ['II', 'III']
main_story_act_coverage_status     = PARTIAL
episodes_without_exact_act_main_story_evidence 含 INNER_WORLD_REVELATION
mandatory_life_stage_source_status = PARTIAL:episodes_without_exact_act_main_story_evidence=['INNER_WORLD_REVELATION']
canon_span_status                  = MANDATORY_SPAN_SOURCE_COMPLETE
```

无 Character Story→MAIN_STORY 重贴标签、无 Voice-Over→Act 补写、无新官方来源编造。

## 5. R10-FC closure

**Canonical U failure behavior**：

- App 生产路径（路径 A/B，brief §4.4）：`umsg_id` 成功（真 id）→ 路径 A：
  `cog.apply_user_message(text, channel="DIRECT_USER_TURN", turn_id=turn_id,
  source_event_id=umsg_id, require_source_event=True)`；空/异常 → 路径 B：
  `log.warning("R10-FC FAIL-CLOSED: ...")` 且**不调用** apply —— 不会走到
  `_ensure_transition_event` 的 orphan fallback（F5/F6/F8 全部被结构性排除，
  F7 不适用：从不按文本搜索 USER_MESSAGE）。
- Hub defense-in-depth（§4.5 采用方案1 `require_source_event=True`）：
  `source_event_id` 必须在 `life_events` 解析为一条真实 `USER_MESSAGE` 行才放行；
  否则返回 `skipped="missing_canonical_user_message"`，全程 zero mutation
  （无 supersede / 无 plan complete / 无孤儿 T / 连 declaration upsert 也一并跳过）。
  孤立单测外壳默认 False，原行为逐字保留（未破坏任何既有隔离测试）。

**Conversation continuation**（F9）：U 失败只跳过该回合的 C4 durable 应用；快照冻结、
`submit_reserved`、worker 回复照常进行 —— DirectTurn 必达终态
（runtime 证据：H 反例中该回合 `wait_idle=True, status=FAILED` —— 终态即可，
FAILED 来自空 API key 的快速生成失败，非 C4 路径所致）。

**Exact row→T→U happy path preserved**：R10-FC-T5/T6（= brief R10-FC-T4/T5）在真实
production 入口上验证 row → transition_event_id → T（payload.source_event_id）→ U
（USER_MESSAGE），`T.turn_id == U.turn_id ∈ DirectDialogueQueue outcomes`；相同文本两回合
解析出不同 U.event_id / U.turn_id。

## 6. EventBridge retry integrity

`record(key)` 新顺序：

```text
key ∈ _seen?          → 返回 None（exactly-once dedupe，保持）
events.append(...)    → 失败则异常向外传播，_seen 不变（可重试）
append 成功           → _seen[key]=True（有界 trim 顺延）
process=True 时       → 幂等批处理（原逻辑不变）
```

Runtime 证据（Counterexample I）：

```text
first record(key=K)  → 注入异常 FAILED；_seen contains K? False
second record(key=K) → persisted event_id=lev_1787760325062_523a7b64，
                       ACTIVITY_STARTED 总行数 = 1
third record(key=K)  → None（成功后 dedupe 生效）
```

锁测：R10-FC-T3 断言全链（不含 K → 重试恰好一条 → 含 K → 第三次 None）。

## 7. Counterexamples G / H / I（actual runtime output）

### G — R7 missing evidence（null-act 不可再逃逸）

```text
G-after null-act:
  unregistered_evidence_ids = ['FUR-NOT-REGISTERED']
  mandatory_life_stage_source_status = GAPS:unregistered_evidence=['FUR-NOT-REGISTERED']
  canon_span_status (legacy structural) = MANDATORY_SPAN_SOURCE_COMPLETE
G-after span-act(I-V):
  unregistered_evidence_ids = ['FUR-NOT-REGISTERED']
  mandatory_life_stage_source_status = GAPS:unregistered_evidence=['FUR-NOT-REGISTERED']
production truth preserved:
  unregistered_evidence_ids = []
  missing_main_story_acts = ['II', 'III']
  main_story_act_coverage_status = PARTIAL
  mandatory_life_stage_source_status = PARTIAL:episodes_without_exact_act_main_story_evidence=['INNER_WORLD_REVELATION']
```

### H — canonical USER_MESSAGE persistence failure fails closed

```text
H before: active preference row = {'item_id': 'umi_…', 'status': 'active', 'key': 'preference:咖啡'}
[app] WARNING R10-FC FAIL-CLOSED: canonical USER_MESSAGE 未落地(turn=2) → 本回合跳过证据依赖的 C4 durable 演化（对话继续）
H after failed turn:
  old preference row -> {'item_id': 'umi_…', 'status': 'active'}     # 行身份不变
  superseded rows total -> 0
  USER_PREFERENCE_CHANGED events -> []                                # 无 orphan T
  dialogue continuation: wait_idle=True turn_outcome(status=FAILED)   # 终态可观察（对话继续）
plan-completion equivalent:
H-plan before: {'item_id': 'umi_…', 'status': 'active'}
H-plan after failed turn:
  plan row -> {'item_id': 'umi_…', 'status': 'active'} | USER_PLAN_COMPLETED events -> 0
```

### I — EventBridge retry after failed append

```text
I first record(key=K): FAILED as injected (forced append failure #1); _seen contains K? False
I second record(key=K): persisted event_id=lev_1787760325062_523a7b64 |
                        total ACTIVITY_STARTED rows=1 | third dedupe call -> None
```

## 8. Frozen residual preservation

```text
R6 preserved —— _observe_with_provenance 未触碰；C3-T* 与 R6-T1..T4 全绿（Gate B/C）。
R8 preserved —— scheduler.py 本次 diff 为零行改动；R8-T1..T5 全绿（Gate B）。
R9 preserved —— 真实 Director E2E 测试原文保留并全绿（Gate B）。
R11 preserved —— pet/poke/drag 三事件映射未动；R11-T1..T6 全绿（Gate B）。
R12 preserved —— pyproject.toml 未动；Office 能力测试 0 失败（Gate F 101 passed）。
```

另：`git diff --stat` 显示生产代码仅上述 4 文件（+80/-18），无其它模块被动。

## 9. Static audit（brief §6 全部 14 项）

| # | item | verdict | evidence |
|---|---|---|---|
| 1 | 每个 `CanonEpisode.evidence_ids` 全局校验 | PASS | `_unregistered_evidence_refs` 遍历 `self._episodes`（无条件 continue） |
| 2 | unregistered 校验不被精确单幕 gate 限制 | PASS | 该方法独立于 `_evidence_attribution_conflicts` 的 act gate；gate 内 `u is None → continue` 仅避免重复计数 |
| 3 | `_life_stage_source_status()` 含全局缺失 integrity | PASS | 方法首分支即 missing → `GAPS:unregistered_evidence=…` |
| 4 | 生产 direct C4 lifecycle 有 canonical USER_MESSAGE gate | PASS | app.py umsg 分支 + hub `require_source_event=True` 双层 |
| 5 | 生产 direct 不会调用 orphan transition fallback | PASS | U 缺失时根本不进入 `apply_user_message`；hub 门二次拦截 |
| 6 | EventBridge 失败 append 不永久标记 `_seen` | PASS | mark 移至 append 成功后（R10-FC-T3） |
| 7 | 成功 dedupe 仍工作 | PASS | R10-FC-T3 第三次调用 → None、仍 1 行 |
| 8 | DirectDialogueQueue turn identity 单一权威 | PASS | turn_id 只出自 queue（reserve）；本次 diff 未触碰 queue |
| 9 | timeout 自 reserve/ingress 起算 | PASS | `reserve_turn` 设 deadline；R10-FC-T8 断言 `deadline ≈ created_monotonic + timeout` 且 submit 不重置 |
| 10 | 无新 C3 formation writer | PASS | diff 未新增任何 memory 写入调用 |
| 11 | 无新 raw memories 写入方 | PASS | 同上（memory engine/store 无 diff） |
| 12 | 无 R11 事件坍缩 | PASS | pet/poke/drag 映射 diff 为零 |
| 13 | 无 Office 依赖回归 | PASS | pyproject 无 diff；Gate F 全绿 |
| 14 | 无 Canon 来源捏造 | PASS | `data/canon/*` 零 diff；生产 metrics 输出与修复前逐字一致 |

## 10. Tests（Gates A–G）

项目本地已验证解释器（`.venv`，Python 3.14）全程未切换。

- **Gate A**（new）`tests/cognition/test_phase14_final_r7_r10_failclosed.py`
  → `14 passed in 6.77s`（R7-FC-T1..T4；R10-FC-T1/T2/T3/T4(hub-gate)/T5(happy)/T6(dup)/T7(cancel)/T8(fifo+deadline)/T9(warning 观察性)/T10(健康路径恢复)）
- **Gate B** `tests/cognition/test_phase14_final_reviewer_r6_r12.py`
  → `30 passed in 8.86s`（**零修改**，无需机械改名）
- **Gate C**（previous closure/residual）`test_phase14_final_closure.py` + `test_phase14_residual_closure.py`
  → `34 passed in 9.03s`
- **Gate D**（targeted cognition/scheduler/dialogue/Director/memory/relationship）
  `test_cognitive_stores.py / test_director.py / test_dialogue_closeout.py /
  test_dialogue_liveness.py / test_memory_phase.py / test_relationship.py / test_phase13_h1final.py`
  → `105 passed in 7.20s`
- **Gate E**（Phase 15 preservation）`test_phase151_truth_closure.py` + phase15a–f +
  `tests/agent/integration/test_phase15_cognitive_life.py`
  → `75 passed in 20.18s`
- **Gate F**（Agent / Office foundation）`tests/agent/**` + `tests/test_agent_tools.py`
  → `101 passed, 15 warnings in 28.79s`（零依赖失败）
- **Gate G** FULL SUITE ×3（127s≤ 单轮 ≤132s）：

```text
FULL RUN #1  1232 passed / 0 failed / 0 skipped   87.37s
FULL RUN #2  1232 passed / 0 failed / 0 skipped  100.23s
FULL RUN #3  1232 passed / 0 failed / 0 skipped  131.85s
```

历史基线 1218 + 本次新增 14 = 1232，未 skip/xfail 任何用例（F11/Q 达成）；
15 条 warnings 为任务前既有 pytest 告警，与本任务无关、数量未增。

## 11. Git state

commit 序列（建议的四段结构）：

```text
1. fix(canon): 全局 evidence 引用完整性（R7-FC）
2. fix(direct-turn): canonical USER_MESSAGE provenance fail-closed（R10-FC）
3. test: 锁定 R7-FC / R10-FC 反例（14 cases）
4. docs: Phase 14 final R7-FC/R10-FC closeout（05 brief 入库 + 06 报告 + manifest/ledger）
```

`git status --short`（commit 前）：

```text
 M furina/app.py
 M furina/cognition/bridge.py
 M furina/cognition/hub.py
 M furina/cognition/stores/canon_history.py
?? docs/phase/Phase_14/05_Phase_14_Final_Reviewer_Residual_R7_R10_FailClosed_Task_Brief_EXACT.md
?? nul                                    ← 既存 artifact，按约定不加库
?? tests/cognition/test_phase14_final_r7_r10_failclosed.py
```

final local SHA == final remote SHA 于 push 后验证
（`git ls-remote origin fix/phase14-final-r7-r10-failclosed`）；不 merge、不动 master。

## 12. Remaining gaps

本任务两个 blocker（R7-FC / R10-FC）及其耦合缺陷（EventBridge `_seen` 毒化）已全部闭合，
Gates A–G 全绿。剩余事项仅有：**外部独立 reviewer 尚未给出最终判定**
—— 在其确认前状态维持 `PHASE_14_FINAL_GATE = FAIL`（本 agent 不自行宣判 PASS）。
既有真实缺口如实保留（不属于本任务，亦未被掩盖）：Act II/III 主线 curated 证据单元缺位
（`NO_CURATED_MAIN_STORY_UNIT`）与 INNER_WORLD_REVELATION 的精确 act V 支撑缺口。

## 13. Final line

```text
READY_FOR_FINAL_REVIEW
```

## 附：Final self-audit（brief §14，A–R）

| q | answer | evidence |
|---|---|---|
| A | **NO** | 非精确 episode 引缺失 id 即 `GAPS:unregistered_evidence`（R7-FC-T1/T2） |
| B | **YES** | A 层独立方法；exact-act 三元组矩阵行为逐项保留（R7-FC-T3） |
| C | **NO** | `data/canon/*` 零 diff；生产 metrics 输出未变 |
| D | **NO** | H 反例 runtime 证据：correction 后旧 preference 仍 active |
| E | **NO** | H-plan 证据：plan 仍 active、completed=0、事件=0 |
| F | **NO** | T/U 恒等链只经真实 U；hub 门拒绝一切无源 lifecycle（T4-hub） |
| G | **NO** | I 反例：首败后 `_seen` 无 K，重试恰好持久化一条 |
| H | **YES** | R10-FC-T5 happy path row→T→U 按 event id |
| I | **YES** | R10-FC-T6 双相同文本 → 双不同身份 |
| J | **NO** | queue 模块零 diff；FIFO/deadline 断言全绿（R10-FC-T8、R10-T7） |
| K | **NO** | R6-T1..T4 绿（Gate B） |
| L | **NO** | R8-T1..T5 绿；scheduler 零 diff |
| M | **NO** | R9 真 Director E2E 绿 |
| N | **NO** | R11-T1..T6 绿；三类型映射零 diff |
| O | **NO** | R12 依赖声明零 diff；Office 测试零失败 |
| P | **NO** | diff 无新 memory writer |
| Q | **NO** | 零删改弱化：仅新增 1 测试文件（14 cases）；1232=1218+14×3 轮全过 |
| R | **YES** | push 后远端 ref == 本地 HEAD（§11 验证步骤） |
