# Phase 14 Reviewer Residual Closure — Task Brief

> **阶段定位：Phase 14 修复轮 / Reviewer Residual**
>
> **前置状态：上一轮 `Phase 14 Final Closure Patch` 已完成主体修复，但最终独立 Gate 未通过。**
>
> **当前目标：只关闭剩余的 C3 P0 证明/架构缺口，以及 1 个 C4 provenance 验证点。**
>
> **禁止扩大范围。**
>
> 只有本任务全部满足后，才能输出：
>
> ```text
> PHASE_14_FINAL_GATE_PASS
> ```

---

# 0. 执行模型与角色

## 主执行模型

**Ox Alpha**

原因：
- 已继承上一轮 V4 Pro → Ox 的 working tree 与上下文；
- 本轮是窄范围 residual closure，不值得换模型重新读取整个仓库；
- 重点是验证/收敛，不是新架构开发。

## 最终 Reviewer / Gate

**GPT-5.6 Sol**

Ox Alpha 本轮已经属于实现方，**不得再把自己的自审当作独立 adversarial review**。

最终是否 `PHASE_14_FINAL_GATE_PASS`，由独立 reviewer 根据：
- production path；
- git diff；
- reviewer-locked tests；
- static sink audit；
- closeout evidence

重新判定。

---

# 1. 本轮背景

上一轮已基本关闭：

- C2 canonical source / provenance；
- FUR-006 attribution；
- FUR-052 source type；
- Scheduler `on_user_ignore()` 直接 `MemoryEngine.consolidate()` bypass；
- C4 preference supersede / plan complete 的 transition evidence；
- full suite 无新增 regression。

上一轮报告测试结果：

```text
Gate A: 19 passed
Gate C: 18 + 6 passed
Full suite: 1169 passed / 4 known Office dependency failures
New failures: 0
```

**这些通过项本轮不得重做、不得借机重构。**

最终 Gate 未通过的原因集中在以下 5 个 residual：

```text
R1 — 唯一 durable-memory formation authority 尚未被严格定义/证明
R2 — static audit 只扫 observe/consolidate，不足以证明无 direct durable-write bypass
R3 — USER_IGNORED 缺少对真实 social-bid canonical event 的 causal provenance
R4 — C3-T7 Real Ignore production path 没有被完整证明
R5 — C4 transition_event 必须证明能回溯到原始 utterance，而不是循环 derived provenance
```

其中 R1–R4 属 **C3 P0**。

---

# 2. 硬约束

## 2.1 本轮只允许解决 R1–R5

禁止：

- 重做 C2；
- 修改 FUR-006 / FUR-052，除非发现上一轮修复导致直接 regression；
- 重构 cognition 总体架构；
- 开始 Phase 15；
- 修改 Office optional dependencies；
- 修 Qt flaky；
- 修改 packaging / `pyproject.toml`；
- 调整 Persona / Emotion / Motivation 参数；
- 做 unrelated cleanup；
- commit / push，除非用户另行授权。

---

## 2.2 不允许“通过定义绕过问题”

尤其禁止：

```text
“多个模块都能 MemoryEngine.observe，
但我把 MemoryEngine 本身叫唯一 owner，
所以 single-owner 已满足。”
```

如果多个 production caller 能各自决定：
- 是否形成 durable memory；
- 用什么内容；
- 用什么 importance；
- 用什么 provenance；
- 何时写入；

那么它们仍然拥有 formation authority。

本轮必须给出**可执行架构定义**，而不是只改术语。

---

# 3. R1 — Canonical Durable-Memory Formation Authority

## 3.1 当前问题

上一轮 closeout 同时声称：

```text
hub._form_memory = canonical owner
```

但 static audit 又列出：

```text
MemoryEngine.observe callers:
- hub._form_memory
- autobiography.observe
- app._observe_with_provenance
```

因此：

> “只有一个 production formation authority”

尚未被证明。

---

# 3.2 必须先定义 authority

修代码前必须输出一段明确声明：

```text
Canonical durable-memory formation authority = <ONE OWNER>
```

然后解释：

- 谁可以 submit observation/event；
- 谁可以 decide formation；
- 谁可以 construct Memory；
- 谁可以 persist durable memory；
- 谁只能作为 adapter/delegate；
- 哪些 legacy API 仍可存在但不是 production authority。

---

# 3.3 可接受架构

可以采用以下任一真实成立的模型。

## 模式 A — CognitionHub owns formation policy

```text
App / Scheduler / Adapter
       ↓
canonical event / observation submit
       ↓
CognitionHub
       ↓
formation policy
       ↓
MemoryEngine persistence
```

在该模式下：

- `App` 不得独立决定 durable formation；
- `Autobiography` 不得独立决定 formation；
- 它们只能 submit / delegate。

## 模式 B — MemoryEngine owns all formation

```text
App / Hub / Adapter
       ↓
observation
       ↓
MemoryEngine
       ↓
ONE canonical formation policy
       ↓
durable persistence
```

在该模式下：

- Hub 不得拥有第二套 formation policy；
- App/adapter 只传输入；
- 去重、provenance、formation、persistence 的权威规则全部在 MemoryEngine。

---

# 3.4 禁止的架构

```text
App ----------------------> MemoryEngine.observe
Hub ----------------------> MemoryEngine.observe
Autobiography ------------> MemoryEngine.observe

且每个 caller 各自决定：
content / importance / provenance / formation semantics
```

即使这些 caller 当前“事件集不重叠”，也不符合 single authority。

---

# 3.5 R1 必须新增测试

### R1-T1 — Formation owner architectural contract

必须能自动失败于：

- 新增第二个 production formation authority；
- 新增直接 durable-memory writer；
- App/Scheduler 重新取得 formation decision 权。

不要只检查函数名。

### R1-T2 — Submitter vs owner

证明所有非 owner production path：

```text
只 submit
不 decide formation
不直接 persist durable memory
```

### R1-T3 — Exact provenance invariant at owner boundary

canonical owner 接收到输入后，任何 durable memory：

```text
source_event_ids != []
```

且 exact source events 可解析。

---

# 4. R2 — Repository-wide Durable Write Sink Audit

## 4.1 当前问题

上一轮 static audit 主要检查：

```text
MemoryEngine.consolidate(...)
MemoryEngine.observe(...)
```

这不足以证明无 bypass。

以下代码也能直接形成 durable memory：

```python
m = Memory(...)
store.insert(m)
```

或：

```python
db.execute("INSERT INTO memories ...")
```

完全绕过 `observe()` / `consolidate()`。

---

# 4.2 本轮必须审计最终 sinks

至少搜索并分类：

```text
MemoryStore.insert
.store.insert(
INSERT INTO memories
Memory(...)
nightly_consolidate
import/migration adapters
legacy wrappers
autobiography adapters
test-only writers
```

最终报告必须给出：

```text
ALL durable-memory production write sinks
```

每个 sink 标记：

```text
PRODUCTION
TEST
MIGRATION
DEV/CLI
DEPRECATED
```

---

# 4.3 判定标准

允许有多个**物理 persistence helper**，但只能有一个**production formation authority**。

例如：

```text
canonical owner
   ↓
MemoryStore.insert
```

可以。

但：

```text
App
   ↓
MemoryStore.insert

Scheduler
   ↓
MemoryStore.insert
```

不可以。

---

# 4.4 R2 必须新增测试

### R2-T1 — No direct production store bypass

production 模块不得绕过 canonical authority 直接：

```text
MemoryStore.insert
raw INSERT
equivalent durable write
```

### R2-T2 — Legacy / CLI isolation

如果存在：
- migration；
- import；
- debug CLI；
- nightly maintenance；

必须证明它们不会成为 normal runtime formation bypass。

---

# 5. R3 — USER_IGNORED Must Reference Real Social-Bid Event

## 5.1 当前问题

上一轮 AFTER：

```text
social bid timeout
    ↓
on_user_ignore(bid_reason)
    ↓
USER_IGNORED
payload = {
    bid_reason,
    window_s
}
```

`bid_reason="spoken:talk"` 是描述，不是 canonical causal provenance。

---

# 5.2 正确 causal chain

本轮必须形成：

```text
SOCIAL_BID_STARTED
event_id = E1
reason = spoken:talk / executed:approach_user
presence_known = true
user_present = true
visible = true
started_at = ...
deadline = ...
        ↓
response window
        ↓
(no qualifying response)
        ↓
USER_IGNORED
event_id = E2
source_event_ids = [E1]
```

至少要能回答：

```text
为什么判定 USER_IGNORED？
→ 因为 canonical social-bid event E1 在 response window 内无 qualifying response。
```

而不是：

```text
→ 因为 payload 写了 spoken:talk。
```

---

# 5.3 Social bid event 要求

`SOCIAL_BID_STARTED` 或现有等价 canonical event 必须：

- 只在真实、合格、可见的 social bid 时记录；
- unknown presence 不记录；
- absent user 不记录；
- blocked mind action 不记录；
- suppressed/failed speech 不记录；
- pointer leave 不记录；
- system/agent status speech 不记录；
- exactly-once。

pending bid 中应保存：

```text
source_event_id
deadline
reason
```

或等价数据。

---

# 5.4 Response semantics

qualifying user response 必须取消 pending bid。

至少覆盖：

- direct user message；
- click；
- petting；
- poke；
- drag semantic interaction；
- feeding；
- reject；
- 其他当前生产定义的 meaningful response。

不得把 hover/leave 当 response 或 ignore。

---

# 6. R4 — C3-T7 Real Ignore Production Path

上一轮 closeout 没有完整给出 C3-T7 evidence。

本轮必须新增/强化一个明确命名的 production-path test。

## C3-T7 — Real Ignore End-to-End

测试必须从真实入口驱动：

```text
eligible social action
    ↓
Director actually executes
    ↓
visible social bid opens
    ↓
canonical SOCIAL_BID_STARTED recorded
    ↓
no user response
    ↓
deadline expires
    ↓
Scheduler medium/social tick
    ↓
USER_IGNORED canonical event
    ↓
Cognition
    ↓
optional durable memory
```

必须同时断言：

### Event layer

```text
SOCIAL_BID_STARTED == 1
USER_IGNORED == 1
```

### Provenance

```text
USER_IGNORED.source_event_ids == [SOCIAL_BID_STARTED.event_id]
```

### Memory

若 policy 决定形成：

```text
memory.source_event_ids contains USER_IGNORED.event_id
```

如果设计为 memory 同时引用 causal chain，也可：

```text
[USER_IGNORED.event_id, SOCIAL_BID_STARTED.event_id]
```

但必须明确 canonical rule，不能测试临时拼。

### Exactly-once

再次 tick：

```text
no second USER_IGNORED
no second memory
```

### Negative counterfactuals

至少覆盖：

```text
no bid → no ignore
user responds → no ignore
presence unknown → no bid → no ignore
speech failed/suppressed → no bid → no ignore
blocked mind action → no bid → no ignore
```

---

# 7. R5 — C4 Transition Provenance Must Reach Original Utterance

## 7.1 当前风险

上一轮 direct `apply_user_message` 路径会创建：

```text
USER_PREFERENCE_CHANGED
USER_PLAN_COMPLETED
```

再把它作为：

```text
transition_event_id
```

这只有在 derived event 本身能回溯到原始用户 utterance 时才成立。

否则可能形成：

```text
preference superseded
    ↓ why?
USER_PREFERENCE_CHANGED
    ↓ why?
because preference superseded
```

循环 provenance。

---

# 7.2 必须证明

以：

```text
“其实最近不怎么听陈奕迅了”
```

为例：

```text
transition_event_id
    ↓
USER_PREFERENCE_CHANGED
    ↓
source_event_id / parent_event_id / raw utterance evidence
    ↓
original user utterance
```

同理 plan complete：

```text
“桌宠测试做完了”
```

必须能从 lifecycle row 最终解析回原始 utterance evidence。

---

# 7.3 R5 必须新增测试

### R5-T1 — Preference transition → original utterance

从 DB row：

```text
transition_event_id
```

开始，不使用测试 fixture 里保存的外部变量，真实 resolve：

```text
event
→ source/parent/raw evidence
→ original utterance
```

### R5-T2 — Plan complete → original utterance

同上。

### R5-T3 — No circular provenance

禁止：

```text
transition row → derived event → transition row
```

作为唯一 evidence。

---

# 8. Regression Locks

本轮不得破坏上一轮已经通过的内容。

必须继续保持：

## C2

- FUR-006 = Act I canonical attribution
- FUR-052 = CHARACTER_STORY
- evidence attribution conflicts = 0

## C3 existing

- Scheduler no direct `MemoryEngine.consolidate`
- poke/drag/reject-poke objective semantics
- no empty provenance durable memory
- existing exactly-once contracts

## C4 existing

- preference entity isolation
- plan entity isolation
- ambiguous safety
- reload persistence

## Earlier frozen contracts

- Director priority arbitration
- RuntimeDispatcher owner-thread
- interaction exactly-once
- Emotion single owner
- C6 exactly-once
- no pointer-leave→ignore
- no blocked mind speech/social-bid
- agent verified hard gate

---

# 9. Required Test Gates

## Gate R-A — New residual tests

所有 R1–R5 新测试：

```text
0 failed
```

---

## Gate R-B — Previous Phase 14 closure tests

```text
tests/cognition/test_phase14_final_closure.py
```

必须继续：

```text
19 passed
```

若本轮增加同文件测试，则报告：

```text
previous 19 still pass
new residual tests pass
```

不要混淆基线。

---

## Gate R-C — Cognition / Memory / Scheduler targeted

要求：

```text
0 failed
```

Office optional-dependency tests不要混进此 Gate 的 PASS/FAIL 统计。

---

## Gate R-D — Phase 15 preservation

保持：

```text
18 cognition locked passed
6 integration passed
```

---

## Gate R-E — Full suite

以当前已知基线：

```text
1169 passed
4 known Office dependency failures
```

为参考。

要求：

```text
new failures == 0
```

若 Qt flaky 再出现：
- 隔离重跑；
- 明确标记；
- 不得借此掩盖 residual regression。

---

# 10. Static Architecture Audit — 必须输出

最终报告必须回答以下问题。

## 10.1 Formation Authority

```text
Canonical durable-memory formation authority = ?
```

只能有一个明确答案。

---

## 10.2 All production submitters

列出所有：

```text
event submitter
observation submitter
memory candidate submitter
```

并证明它们不是 formation authority。

---

## 10.3 All durable write sinks

列出所有：

```text
MemoryStore.insert
raw DB INSERT
equivalent durable writers
```

标注：
- caller；
- scope；
- production reachable?；
- authority relationship。

---

## 10.4 USER_IGNORED causal chain

必须输出真实示例：

```text
SOCIAL_BID_STARTED event_id=...
        ↓
USER_IGNORED event_id=...
source_event_ids=[...]
        ↓
MEMORY id=...
source_event_ids=[...]
```

---

## 10.5 C4 causal chain

必须输出真实示例：

```text
original utterance
        ↓
canonical utterance/event id
        ↓
USER_PREFERENCE_CHANGED / USER_PLAN_COMPLETED
        ↓
transition_event_id
        ↓
stored lifecycle row
```

---

# 11. BEFORE / AFTER Evidence

不要直接改完后报 green。

本轮仍然要求至少对 residual 建立 BEFORE evidence。

例如：

## R1 BEFORE

```text
multiple production callers possess independent formation decisions
```

或：

```text
current architecture cannot prove otherwise
```

## R3 BEFORE

```text
USER_IGNORED only contains bid_reason/window_s
no canonical bid source event id
```

## R5 BEFORE

如果当前 transition event 已经可以回原始 utterance，则 R5 可以是：

```text
BEFORE audit proved already closed
no code change required
test added to lock it
```

不要为了“每项都要改代码”而制造无意义修改。

---

# 12. 修改策略

本轮优先：

```text
minimal patch
+
architectural proof
+
reviewer-locked test
```

而不是：

```text
large refactor
```

如果上一轮代码实际上已经满足某个 residual，只是报告没证明：

> **只补 proof/test，不改 production code。**

---

# 13. 完成报告格式

Ox Alpha 最终必须严格按以下结构输出。

## 1. Result

只能：

```text
READY_FOR_FINAL_REVIEW
```

或：

```text
RESIDUAL_BLOCKER_REMAINS
```

**不得自己输出 `PHASE_14_FINAL_GATE_PASS`。**

最终 PASS 由独立 reviewer 判定。

---

## 2. BEFORE Evidence

逐项：

- R1
- R2
- R3
- R4
- R5

---

## 3. Canonical Formation Authority

明确一句：

```text
Canonical durable-memory formation authority = ...
```

并解释 ownership boundary。

---

## 4. Modified Files

每个文件：
- why
- what
- public contract impact

---

## 5. R1 Closure

证明 single authority。

---

## 6. R2 Sink Audit

完整 durable write sink 表。

---

## 7. R3 Ignore Provenance

给真实 event chain。

---

## 8. R4 C3-T7

给 production path + assertions + exactly-once + negative cases。

---

## 9. R5 C4 Original-Utterance Provenance

分别给：
- preference
- plan

的完整 causal chain。

---

## 10. Tests

分别报告：

```text
new residual tests
previous 19 Phase14 closure tests
targeted cognition/memory/scheduler
18 cognition locked
6 integration
full suite
```

Office 4 个 known failures 单独写，不要混入 targeted PASS。

---

## 11. Static Architecture Audit

列：

```text
all formation decision sites
all submitters
all durable write sinks
all direct MemoryStore writers
```

---

## 12. Git Diff

```text
git diff --stat
git status --short
```

不要 commit / push。

---

## 13. Remaining Gaps

只要 R1–R5 任意一个未被严格证明：

```text
RESIDUAL_BLOCKER_REMAINS
```

不得使用 “mostly passed”。

---

# 14. Final Acceptance Checklist

交给独立 reviewer 前，执行模型必须确认：

- [ ] canonical durable-memory formation authority 唯一且定义清晰
- [ ] 非 owner production path 只能 submit，不独立 decide formation
- [ ] 全 repo durable write sinks 已扫描
- [ ] normal runtime 无 direct MemoryStore/DB bypass
- [ ] social bid 有 canonical start event
- [ ] USER_IGNORED 引用真实 social-bid source event
- [ ] C3-T7 real ignore production path 完整通过
- [ ] no bid → no ignore
- [ ] user response → no ignore
- [ ] unknown presence → no fake bid/ignore
- [ ] blocked/suppressed social attempt → no bid/ignore
- [ ] USER_IGNORED exactly-once
- [ ] durable memory exactly-once
- [ ] preference transition 可回原始 utterance
- [ ] plan complete transition 可回原始 utterance
- [ ] 不存在 circular provenance
- [ ] previous Phase 14 19 tests 继续通过
- [ ] 18 + 6 preservation tests 继续通过
- [ ] full suite 无新增失败
- [ ] 未触碰本轮 scope 外内容
- [ ] 未 commit / push

---

# 15. 给 Ox Alpha 的最终指令

这是 **Phase 14 Reviewer Residual Closure**，不是新功能开发。

先审计当前 working tree，再最小修复。

重点不是“再加更多测试数字”，而是把下面两条真正证明：

```text
ONE durable-memory formation authority
```

和：

```text
derived semantic event
    -> exact canonical causal source
```

如果代码已经满足某项，只缺证据，就补 production-path test / static proof，不要无意义重构。

完成后输出：

```text
READY_FOR_FINAL_REVIEW
```

然后停止。

不要 commit。
不要 push。
不要进入 Phase 15。
