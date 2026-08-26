# Phase 07 — Relationship Persistence / Single Writer

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 07`
>
> **Confidence:** `HIGH`
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

## 1. 目标

Relationship 与 Memory 相关，但不能互相偷写。

## 2. Single writer

canonical relationship writer：

```text
RelationshipEngine.apply(event)
```

Memory 可以记录关系相关经历，但不得直接 bump trust/comfort/annoyance 等 principal state。

## 3. Persistence

- SQLite durable；
- restart restore；
- save exactly-once；
- 读写单位统一；
- canonical factors 对 consumer 归一化。

## 4. 验收

positive/reject/ignore/recovery 有真实变化；
Memory→Relationship bypass 被删除；
不同 consumer 只读 canonical `factors()`。
