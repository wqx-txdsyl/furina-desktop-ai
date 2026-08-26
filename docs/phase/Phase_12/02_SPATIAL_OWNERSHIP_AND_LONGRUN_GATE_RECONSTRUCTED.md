# Phase 12 — Spatial Ownership / Long-run Gate

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 12`
>
> **Confidence:** `MEDIUM-HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `docs/FURINA_PHASE12_REPORT.md`
- `FURINA_PHASE12V_VISUAL_RUNTIME_RECOVERY.md`
- `furina/runtime/spatial`

---

## 1. Ownership migration

必须删除生产路径中的：
- Scheduler pixel target；
- Scheduler direct `window.set_position`；
- Scheduler spatial activity→macro 偷写。

legacy 方法只能 deprecated no-op。

## 2. Long-run

大量 spatial ticks 检查：
- out-of-bounds；
- stuck；
- duplicate arrival；
- frame-spam replan；
- target hysteresis；
- screen resize revalidate。

## 3. 非目标

不做 A*/NavMesh、桌面图标物理碰撞、跳跃重力、跨屏追人、鼠标追逐。

## 4. Gate

自动技术通过 ≠ 人工视觉通过；报告必须分开。
