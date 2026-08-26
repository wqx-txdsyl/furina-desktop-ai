# Phase 13 — Functional Runtime Harness / Digital Life Integration — Initial Task

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 13`
>
> **Confidence:** `MEDIUM-HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `docs/FURINA_PHASE13_REPORT.md`
- `Recovered Phase 13 taskbooks in ChatGPT Library`
- `Phase 13 commit/reviewer history`

---

## 1. 目标

不用新素材，先证明现有 Life / Dialogue / Interaction / Relationship / Memory / Feeding / Spatial / Agent 真正接入同一个 Runtime。

## 2. Harness 原则

- Harness 只能观察真实 production systems。
- 所有按钮走 production entry。
- 禁止第二套 `FakeEmotion/FakeMemory/FakeLifeBrain`。
- trace 脱敏、有限 ring buffer。
- success/fallback/failure 明确展示，不能假绿。

## 3. 场景

至少覆盖：
- direct conversation；
- autonomy；
- interaction；
- rejection/recovery；
- feeding；
- memory；
- spatial proxy；
- agent；
- failure handling；
- persona manual。

## 4. Gate

Technical Integration、Real Runtime Trace、Manual Functional、Persona Manual 分开判定。
Agent 不得替用户勾人工体验。
