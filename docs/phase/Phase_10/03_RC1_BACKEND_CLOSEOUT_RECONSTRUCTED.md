# Phase 10.5 — RC1 Backend Closeout / Freeze Re-sign

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 10`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `docs/BACKEND_FREEZE.md`
- `docs/FURINA_BACKEND_AUDIT.md`
- `FURINA_RC1_CLOSEOUT_REPORT.md`
- `furina/runtime/frame.py`

---

## 1. 必修 blocker

历史 source 明确要求关闭：

- MemoryStore cross-thread：线程安全连接 + RLock。
- Relationship 单一写入口：`RelationshipEngine.apply()`。
- `body_snapshot()` 退出正式前端接口，`current_frame()` 成为唯一契约。

## 2. 冻结范围

Needs / Emotion / Personality / Identity / Relationship / Memory / World / Motivation / Feasibility / LifeBrain / Dialogue / Embodiment / RuntimeFrame schema。

## 3. Accepted debt

允许明确列出但不改的 debt；不得借“优化”重新打开行为分布或 Persona。

## 4. 最终输出

```text
BACKEND RC1 — FINAL FREEZE
schema v1.0
```

并写清 unfreeze conditions。
