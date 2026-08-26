# Phase 07 — Memory Threading / Durable-Write Ownership Closeout

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 07`
>
> **Confidence:** `MEDIUM-HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M6`
- `plan/6 memory engine.md`
- `furina/memory`
- `furina/relationship`
- `BACKEND_FREEZE.md`

---

## 1. 背景

后续 Backend Audit 发现 MemoryStore 跨线程是冻结前 blocker。本文件反向恢复该 closeout 合约。

## 2. 必须修复

- SQLite store 支持实际后台读/写路径；
- `check_same_thread=False` 仅与显式 lock 一起使用；
- `RLock` 保护共享连接/事务；
- 后台 Life/Dialogue 不得因为 sqlite thread error 静默降级。

## 3. Formation owner

normal runtime 的 durable-memory formation 必须有唯一 canonical authority。
Scheduler/App 不得偷偷构造 Memory/Experience 后直写 store。

## 4. 验收

跨 owner/worker 的生产等价测试；
无 silent exception；
同一 event exactly-once；
source_event_ids 可解析。
