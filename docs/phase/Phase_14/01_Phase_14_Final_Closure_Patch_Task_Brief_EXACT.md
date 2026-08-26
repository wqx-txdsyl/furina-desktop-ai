# Phase 14 Final Closure Patch — 任务书

> **目标状态：`PHASE_14_FINAL_GATE_PASS`**
>
> 本任务不是 Phase 15 开发，不允许顺手实现 Phase 15 功能。唯一目标是把此前 Qwen + ChatGPT adversarial review 已确认的 Phase 14 残余 blocker 全部关闭，并用真实 production-path 测试证明关闭。

---

## 0. 执行模型与角色分工

### 主实现模型
**V4 Pro**

职责：
- 阅读现有 Phase 14 实现与测试；
- 复现 blocker；
- 追踪所有 production write paths；
- 做最小但架构正确的修复；
- 补 reviewer-locked regression tests；
- 跑 targeted tests + full suite；
- 输出完整 closeout 报告。

### 独立 Reviewer
**Qwen3.8 gateway**

要求：
- 使用独立上下文；
- 不读取 V4 Pro 的推理过程，只看仓库、diff、测试和 closeout 报告；
- 重点寻找 false-green、旁路写入、重复 owner、provenance 丢失、只改测试不改生产路径、只修文档不修真实 source-of-truth 等问题；
- 给出 `PASS / FAIL`，若 FAIL 必须提供可复现证据。

### 最终 Gate
在 V4 Pro 修复 + Qwen3.8 独立复审后，再交给 ChatGPT 做最终架构一致性 Gate。

---

# 1. 范围与硬约束

## 1.1 本任务必须解决

此前最终 adversarial review 尚未关闭的三组 blocker：

- **C2 — Source / provenance correctness**
- **C3 — Memory provenance + single production formation authority + objective interaction semantics**
- **C4 — Preference / plan lifecycle provenance**

其中：

> **C3 为 P0。**

只要 C3 仍存在任何可达 production bypass，Phase 14 就不得 PASS。

---

## 1.2 明确禁止

本任务禁止：

- 开始或实现 Phase 15 / 15.1 / 15.1.1；
- 为“顺便清理”而大规模重构无关模块；
- 修改行为语义以迎合测试；
- 通过 mock-only / monkeypatch-only 测试宣称 production path 已闭合；
- 删除、放宽或跳过 reviewer test 来获得 green；
- 用硬编码特例处理某一句测试输入；
- 创建第二套 memory formation authority；
- 仅修改文档而不核对真实生产 source-of-truth；
- 仅修改 timestamp/status 而声称 lifecycle provenance 已完成；
- 修改 `pyproject.toml`、处理 packaging、Office optional dependencies 或 Qt flaky 技术债；
- commit / push，除非用户另行明确授权。

---

# 2. 开发环境

使用现有环境：

```text
F:\program\Python\furina-work\.venv\Scripts\python.exe
```

当前环境已通过：
- Phase 15 cognition locked tests：18 passed
- Phase 15 integration：6 passed
- Selfcheck：OK

当前 editable install 因 setuptools flat-layout package discovery 问题不可用，仓库通过 `.pth` 实现可导入。

**本任务不要处理这个 packaging 问题。**

所有 Python / pytest 调用优先使用：

```bat
F:\program\Python\furina-work\.venv\Scripts\python.exe -m pytest ...
```

---

# 3. Preflight —— 必须先做

在修改任何文件前：

1. 输出：
   - 当前 branch；
   - 当前 HEAD commit；
   - `git status --short`；
   - 是否存在用户未提交修改。
2. 不得 reset / checkout / clean 用户现有修改。
3. 定位 Phase 14 对应：
   - source/canon mapping；
   - C6 canonical event；
   - CognitionHub；
   - MemoryEngine；
   - Scheduler；
   - preference lifecycle；
   - plan lifecycle；
   - 相关 production-path tests。
4. 用代码搜索确认所有 memory formation write sites：
   - `MemoryEngine.consolidate`
   - 等价 wrapper
   - EPISODIC / semantic / C3 写入口
   - Scheduler / app / cognition / behavior 中任何间接调用。
5. 在修复前形成 **BEFORE evidence**。

不得“看见明显 bug 就直接改”，必须先证明真实生产路径。

---

# 4. C2 — Source / Provenance Correctness

## 4.1 已知问题

此前审计确认 source map 内存在互相矛盾的事实来源声明：

- Act I–V 映射表；
- 旧的 15-stage `PARTIAL` 表；
- 后来的 `SOURCE-COMPLETE` 声明；

三者存在并存冲突。

已明确发现：

### `FUR-006`
曾被同时归因到不同 Act（至少 Act II / Act V），source attribution 不唯一。

### `FUR-052`
属于 character-story 类来源，却曾被当作 main-story Act IV evidence 使用。

这意味着：

```text
claim -> source -> narrative stage
```

链路并非单一可信来源。

---

## 4.2 修复目标

必须建立一个**唯一 canonical source-of-truth**。

要求：

1. 找到当前 production 实际读取/依赖的 source mapping。
2. 区分：
   - main story evidence；
   - character story；
   - profile/archive；
   - voice line；
   - 其他来源类型。
3. `FUR-052` 不得伪装为 main-story Act IV 证据。
4. `FUR-006` 必须得到唯一、可解释、与真实来源一致的 attribution。
5. 旧表如果只是历史材料：
   - 明确标记 historical/deprecated；
   - 或移除会被误当 canonical 的重复声明；
   - 不能继续与 canonical mapping 平级存在。
6. `SOURCE-COMPLETE` 只有在数据真的闭合时才能保留。
7. 修改真实 source data / canonical mapping，而不是只改说明文字。

---

## 4.3 C2 必须新增/强化的测试

至少覆盖：

### C2-T1 — Canonical mapping uniqueness
同一 source ID 在 canonical mapping 中不得产生互相矛盾的 stage/type attribution。

### C2-T2 — Source type correctness
character-story source 不得被识别为 main-story evidence。

### C2-T3 — FUR-006 regression
锁定 `FUR-006` 的正确 canonical attribution。

### C2-T4 — FUR-052 regression
锁定 `FUR-052` 的正确 source type，并证明它不会再作为 main-story Act IV evidence。

### C2-T5 — Production reader consistency
测试必须读取 production 真正使用的 source-of-truth，而不是复制一份测试字典。

---

# 5. C3 — P0 Memory Formation Authority / Provenance Closure

## 5.1 已知 blocker

此前确认存在真实可达旁路：

```text
Scheduler.on_user_ignore()
    -> _consolidate_episode()
        -> MemoryEngine.consolidate()
```

该路径可以在：

- 不经过 C6 canonical event；
- 不经过 CognitionHub / canonical formation owner；
- `source_event_ids=[]`

的情况下直接形成 EPISODIC / C3 memory。

这是 Phase 14 Final Gate 的 **P0 blocker**。

---

# 5.2 不变量

修复后必须满足：

```text
Every durable memory
    -> exactly one canonical formation authority
    -> exact canonical source event provenance
```

具体要求：

### INV-C3-1 — Single production owner
生产代码中只能存在一个负责“从 experience/event 形成 durable memory”的 canonical authority。

其他模块可以：
- emit event；
- submit observation；
- request cognition；

但不得自己形成 durable memory。

### INV-C3-2 — Exact provenance
所有新形成的 durable memory 必须拥有真实：

```text
source_event_ids
```

不得：
- `[]`
- `None`
- fabricated ID
- unrelated previous event ID

### INV-C3-3 — C6 exactly-once
一次真实 canonical interaction/event 不得因为多路径消费而形成重复 C6 或重复 durable memory。

### INV-C3-4 — No Scheduler formation bypass
`Scheduler` 不得拥有隐藏的 memory consolidation authority。

特别检查：

```python
on_user_ignore()
_consolidate_episode()
```

以及任何同类 wrapper。

### INV-C3-5 — No second bypass
不能只修 `on_user_ignore()`，必须搜索整个 repo，证明没有其他 production caller 可以绕过 canonical owner。

---

# 5.3 Objective Interaction Semantics

此前 C3 不只包含 owner/provenance，还包含 interaction semantics。

必须审查“用户互动”“忽略”“有效 interaction”的判定是否来自真实可观察事件，而不是：

- 单纯经过 N 秒；
- scheduler 自己推测用户忽略；
- 没有实际 target/object；
- 没有对应输入事件；
- timer 到点就凭空写一段记忆。

要求：

```text
observable event
    -> canonical event
        -> cognition
            -> optional memory formation
```

而不是：

```text
timer/scheduler inference
    -> durable memory
```

如果 `user_ignore` 是派生语义，必须能追溯到导致该判断的 canonical observed events。

---

# 5.4 推荐修复方向

不要机械照抄以下结构；先确认现有架构的 canonical owner。

目标形态应类似：

```text
Scheduler
   |
   | emits/records canonical event
   v
C6 / Event Timeline
   |
   v
CognitionHub / canonical formation authority
   |
   v
MemoryEngine
```

而不是：

```text
Scheduler ----------------> MemoryEngine
CognitionHub -------------> MemoryEngine
other module -------------> MemoryEngine
```

若现有 canonical owner 已经存在，优先让旁路汇入现有 owner，**不要新建第二个 service**。

---

# 5.5 C3 必须新增/强化的测试

### C3-T1 — Scheduler bypass regression
真实调用 `Scheduler.on_user_ignore()` 的 production path，证明它不能直接形成无 provenance memory。

### C3-T2 — Exact source_event_ids
形成的 memory 必须精确包含触发它的 canonical event id。

### C3-T3 — Empty provenance forbidden
任何 production formation path 都不得形成：

```python
source_event_ids == []
```

### C3-T4 — Exactly-once
同一个 interaction 经过 Scheduler + cognition pipeline 后：
- canonical event exactly once；
- durable memory formation exactly once；
- 不得 duplicate。

### C3-T5 — Repository-wide formation authority
通过 production caller tracing / architectural test 证明不存在第二条可达写入 authority。

不要只 grep 方法名；wrapper/indirect call 也要覆盖。

### C3-T6 — Objective ignore semantics
没有真实 qualifying interaction 时，单纯 timer/tick 不得凭空制造“用户忽略了我”的 durable memory。

### C3-T7 — Real ignore path
当真实 observed interaction 满足 ignore 条件时：
- canonical event 存在；
- provenance 正确；
- cognition 正确消费；
- 若策略允许形成 memory，则由唯一 owner 形成。

---

# 6. C4 — Preference / Plan Lifecycle Provenance

## 6.1 已知问题

此前实体 key、targeted/ambiguous semantics 大体正确。

剩余 blocker 是 lifecycle conversion：

```text
ACTIVE
 -> SUPERSEDED

ACTIVE
 -> COMPLETED
```

此前实现主要只改变：

- status；
- timestamps；

但缺乏足够证据证明：

> “究竟是哪一次真实 utterance/event 导致了这次 lifecycle transition？”

所以状态虽然变了，provenance 没有闭合。

---

# 6.2 修复目标

任何 lifecycle transition 必须可追溯到真实 trigger。

至少包含一种明确、稳定、可查询的 provenance：

```text
trigger_event_id
```

或现有架构中的等价 canonical evidence field。

如果系统同时有 utterance/event 两层，则必须明确哪个是 canonical owner，不要重复制造 source-of-truth。

要求：

### INV-C4-1
`SUPERSEDED` 必须知道：
- 被谁替代；
- 为什么替代；
- 哪个 canonical event 触发。

### INV-C4-2
`COMPLETED` 必须知道：
- 哪个真实 event/utterance 证明完成；
- transition 时间；
- 对应 entity identity。

### INV-C4-3
不能只靠：
```text
updated_at
status
```
反推来源。

### INV-C4-4
保持已验证正确的：
- entity-specific key；
- targeted semantics；
- ambiguous input 不误伤其他 entity。

---

# 6.3 C4 必须新增/强化的 production-path tests

### C4-T1 — Preference supersede provenance
真实输入导致旧 preference 被 supersede：
- old entity status 正确；
- new/current entity 正确；
- transition 有 exact trigger event。

### C4-T2 — Plan complete provenance
真实输入导致 plan complete：
- status 正确；
- trigger event 正确；
- production path 可回溯。

### C4-T3 — Ambiguous utterance safety
含糊输入不能错误 supersede/complete 另一个实体。

### C4-T4 — Entity-specific isolation
两个不同 target/entity 并存时，一个 lifecycle transition 不得污染另一个。

### C4-T5 — Persistence / reload
如果 lifecycle 状态是持久化数据，重载后 provenance 不得丢失。

---

# 7. Reviewer-Locked Test 原则

本任务新增测试必须满足：

1. **production path first**
2. 尽量从公开/真实入口驱动，不直接调用内部私有方法伪造成功。
3. test fixture 可以建立环境，但不得替生产代码补 provenance。
4. 不允许在测试里手动写：
   ```python
   source_event_ids=[expected_id]
   ```
   然后证明 production 会这么做。
5. 必须至少有一组测试能在 BEFORE 版本稳定失败，在 AFTER 稳定通过。
6. 对每个 blocker 保存：
   - BEFORE reproduction；
   - root cause；
   - fix；
   - AFTER proof。

---

# 8. Regression / Frozen Contracts

修复不得破坏此前 Phase 13/14 已冻结语义，尤其重新检查：

- Director priority arbitration；
- interruptibility；
- Dispatcher；
- DirectDialogueQueue；
- Permission；
- PlannerV2；
- C6 exactly-once；
- event timeline；
- Cognition owner-thread；
- app observe count；
- entity-specific preference/plan semantics。

若修复 C3 时改变事件流，必须特别防止：

```text
duplicate C6
duplicate memory
double observe
double cognition
```

---

# 9. 测试 Gate

## Gate A — 新增 blocker tests

C2/C3/C4 所有新增 reviewer-locked tests：

```text
0 failed
```

## Gate B — Phase 14 targeted suite

运行所有 Phase 14 / cognition / memory / event / lifecycle 相关测试。

要求：

```text
0 failed
```

## Gate C — Phase 15 preservation tests

虽然禁止开发 Phase 15，但当前已有的 18 个 cognition locked tests + 6 个 integration tests必须继续通过，以证明 closure patch 没破坏现有上层行为。

预期基线：

```text
18 passed
6 passed
```

## Gate D — Full suite non-regression

当前环境已知基线：

```text
1149 passed
5 failed
```

五个既有失败来自：
- python-docx missing
- python-pptx missing
- openpyxl missing
- 同类 Office production test
- full-suite 下偶发 Qt timer test（隔离运行 PASS）

本任务不得引入任何新的失败。

允许 Final Gate 的 full-suite 条件：

```text
new failures == 0
```

若仍出现 Qt flaky：
- 必须隔离重跑；
- 报告单测结果；
- 不得借此掩盖 Phase 14 回归。

本任务不要顺手修 Office deps / Qt flaky。

---

# 10. Static Architecture Verification

测试通过后仍必须进行一次静态 trace。

至少回答：

### Memory formation
- repo 中所有 `MemoryEngine.consolidate()` / 等价 durable write caller 是谁？
- canonical production owner 是谁？
- 是否还有 Scheduler / App / Behavior 等旁路？

### C6
- 谁创建？
- 谁消费？
- exactly-once 如何保证？

### Lifecycle
- supersede/complete 的 trigger evidence 在哪里写？
- reload 后是否还能找到？

### Source map
- canonical mapping 文件/对象是哪一个？
- deprecated mapping 是否还能被 production 读取？

只报告测试 green，不做这一步，不得宣称 Final Gate PASS。

---

# 11. 完成报告格式

V4 Pro 最终必须严格按以下结构报告：

## 1. Gate Result

```text
PHASE_14_FINAL_GATE_PASS
```

或：

```text
PHASE_14_FINAL_GATE_FAIL
```

不得使用含糊的 “mostly ready”。

## 2. BEFORE Reproduction
逐项列出：
- C2
- C3
- C4

包含真实命令 / test / production path evidence。

## 3. Root Cause
逐项说明架构根因，而不是只写症状。

## 4. Modified Files
每个文件：
- 修改原因；
- 修改内容；
- 是否改变 public contract。

## 5. C2 Closure Evidence
明确说明：
- FUR-006；
- FUR-052；
- canonical source map；
- deprecated/duplicate mappings。

## 6. C3 Closure Evidence
必须列出：

```text
BEFORE:
Scheduler -> MemoryEngine bypass

AFTER:
<actual canonical production path>
```

并证明：
- single owner；
- exact provenance；
- no empty source_event_ids；
- exactly-once；
- objective interaction semantics。

## 7. C4 Closure Evidence
分别证明：
- preference supersede；
- plan complete；
- trigger provenance；
- entity isolation。

## 8. Tests
报告：
- 新增测试数量；
- targeted；
- Phase 14；
- 18 cognition locked；
- 6 integration；
- full suite；
- 隔离 Qt flaky（如出现）。

## 9. Static Call-Site Audit
列出所有 durable memory production write sites。

## 10. Git Diff Summary

```text
git diff --stat
git status --short
```

## 11. Remaining Gaps
如果还有任何未证明项：

```text
PHASE_14_FINAL_GATE_FAIL
```

不能以技术债名义绕过 C2/C3/C4 blocker。

---

# 12. 最终判定标准

只有以下全部成立才能输出：

```text
PHASE_14_FINAL_GATE_PASS
```

- [ ] C2 canonical source/provenance 唯一且无矛盾
- [ ] FUR-006 attribution 已闭合
- [ ] FUR-052 source type 已纠正
- [ ] C3 Scheduler durable-memory bypass 已消失
- [ ] 全 repo 只有一个 production memory formation authority
- [ ] durable memory 均具有真实 exact source-event provenance
- [ ] 不存在 `source_event_ids=[]` 的可达生产形成路径
- [ ] C6 / memory exactly-once
- [ ] ignore/interaction semantics 来自 observable event，而非 timer 推测
- [ ] preference supersede 有 trigger provenance
- [ ] plan complete 有 trigger provenance
- [ ] entity-specific / ambiguous semantics 未回归
- [ ] reviewer-locked production tests 全绿
- [ ] Phase 14 targeted suite 全绿
- [ ] 已有 Phase 15 cognition/integration tests 保持全绿
- [ ] full suite 无新增失败
- [ ] static call-site audit 未发现第二条旁路
- [ ] 未进行 Phase 15 scope creep

---

# 13. 给执行模型的最终指令

**不要先给设计建议。直接审计仓库、复现 BEFORE、修复、加测试、运行 Gate，并输出最终 closeout。**

如果发现本任务书中的某个预设与仓库真实代码不符：

1. 以仓库真实 production path 为准；
2. 提供证据；
3. 保持本任务定义的不变量；
4. 不得为了匹配任务书文字而错误改代码。

本任务追求的是：

> **真实架构闭合，而不是让测试变绿。**
