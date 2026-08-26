# Phase 05 — Presence / Idle Truth Closure

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 05`
>
> **Confidence:** `MEDIUM`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M4`
- `plan/7 desktop runtime.md`
- `furina/world_perception.py`
- `furina/runtime/window_awareness.py`

---

## 1. 目标

把“用户是否在场/是否工作”变成 canonical world fact，避免后续 Life/Dialogue 各自重建 presence。

## 2. PresenceFacts

输出至少包含：

```text
known
present
idle_available
idle_seconds
user_working/activity
```

## 3. 规则

- availability bit 是第一真相。
- stale idle 值不能在 unavailable 时重新证明 present。
- explicit user input 可作为该次 interaction 的在场证据，但不能伪造 OS idle。
- world semantic event 应按 update instance 消费，不从历史 recent list 重放。

## 4. 验收

startup → poll failure → valid sample 三段有测试；
20s/60s boundary 不重复事件；
第二次真实 transition 能再次发事件。
