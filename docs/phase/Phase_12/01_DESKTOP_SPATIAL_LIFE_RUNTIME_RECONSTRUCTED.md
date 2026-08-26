# Phase 12 — Desktop Spatial Life / Movement Runtime

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 12`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `docs/FURINA_PHASE12_REPORT.md`
- `FURINA_PHASE12V_VISUAL_RUNTIME_RECOVERY.md`
- `furina/runtime/spatial`

---

## 1. 目标

把像素空间所有权从 Scheduler 移到独立 Spatial Runtime。

```text
Frame motion/body semantics
→ SpatialIntentResolver
→ MovementPlan
→ SpatialPlanner
→ DesktopSpatialRuntime
→ PositionAdapter
→ Window
```

## 2. SpatialIntent

APPROACH / WITHDRAW / MAINTAIN / NEAR / FAR / REPOSITION / NONE。

Spatial 只消费语义，不重新判断 Needs/Emotion/Persona。

## 3. Movement lifecycle

IDLE → PREPARING → STARTING → MOVING → ARRIVING → ARRIVED，
并支持 INTERRUPTED / DRAGGED。

## 4. 几何

foot anchor 是角色位置真相；
screen/window/anchor 坐标显式转换；
taskbar/multi-screen/resize 安全。

## 5. 验收

30/60/120 FPS 近似一致；
overshoot=0；
drag release commit；
sleep 禁移动；
movement events exactly-once。
