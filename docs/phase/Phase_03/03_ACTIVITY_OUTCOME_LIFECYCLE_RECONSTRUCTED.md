# Phase 03 — Activity Outcome / Duration / Lifecycle Hardening

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 03`
>
> **Confidence:** `MEDIUM-HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M2`
- `plan/1 state tree.md`
- `plan/3 behaviour engine.md`
- `furina/state`
- `furina/emotion`
- `furina/behavior`

---

## 1. 目标

让“做了某件事”真正有起点、持续、结束和后果，避免只在状态名上跳来跳去。

## 2. Activity instance

至少追踪：

```text
activity
instance_id
started_at
planned_duration
elapsed
progress
status
finish_reason
```

## 3. Outcome

- 只有真实开始的活动才结算。
- completed / interrupted / aborted / failed 分开。
- 部分执行奖励按 progress 缩放。
- exactly-once，不能多 tick 重复结算。
- Outcome 影响 Needs/Emotion，但不直接操控下一行为。

## 4. 反塌缩

历史 diversity/anti-collapse 机制不得成为强制轮换器。
如果保留，只能作为明确关闭的 legacy/debt；行为多样应主要来自真实状态变化。

## 5. 验收

- 未执行的 queued action 无 outcome。
- 10% / 70% / 100% progress 结果有单调差异。
- preemption 后不会再被后续 tick 改成 completed。
