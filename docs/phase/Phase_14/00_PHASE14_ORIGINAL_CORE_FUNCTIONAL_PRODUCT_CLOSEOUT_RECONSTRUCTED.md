# Phase 14 — Core Functional Product Closeout / Functional Freeze — Original Intent

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 14`
>
> **Confidence:** `LOW-MEDIUM`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `Phase_14_Final_Closure_Patch_Task_Brief.md`
- `Phase_14_Reviewer_Residual_Closure_Task_Brief.md`
- `Phase 15.1 blind reviewer findings`

---

## 1. 说明

目前没有找回 Phase 14 最初那一轮任务书原件。可以确定的只有：Phase 13 最终方向把下一阶段定义为 Core Functional Product Closeout / Functional Freeze，且后来的 Phase 15.1 reviewer 明确把一组 Phase 14 contracts 视为 frozen。

因此这里只恢复可以被后续证据支持的“原始意图”，不补写无法证明的具体章节。

## 2. 可确认目标

- 在继续更高层 cognition / product work 前冻结核心功能真相。
- 已经通过的 Director、Dispatcher、DirectDialogueQueue、Permission、Planner 等 production contracts 不得回归。
- event / memory / lifecycle 的 source-of-truth 和 exactly-once 必须可验证。
- 不把“测试全绿”当作唯一完成条件。
- closeout 必须以 production-path evidence + reviewer gate 为准。

## 3. 可确认 frozen contracts

至少包括：
- Director priority / interruptibility；
- RuntimeDispatcher owner thread；
- DirectDialogueQueue；
- Permission / PlannerV2；
- C6 exactly-once；
- event timeline；
- cognition owner-thread；
- app observe count；
- entity-specific preference / plan semantics。

## 4. 恢复状态

如果未来找到 Phase 14 初始任务书，应直接加入本目录并标 `EXACT_RECOVERED`；本文件保留作为恢复记录。
