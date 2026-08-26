# Phase 04 — Interaction Engine / Semantic User Actions

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 04`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M3`
- `plan/4 interaction engine.md`
- `furina/interaction`
- `furina/feeding.py`
- `Phase 13 interaction hardening history`

---

## 1. 目标

把鼠标/拖拽等原始输入转成稳定语义事件，再驱动领域反应。

## 2. 语义事件

至少区分：

- click
- petting/head touch
- poke
- drag
- call
- reject
- feed
- meaningful response

pointer hover/leave/grab/release 不能自动等价为“有意义互动”。

## 3. 正确顺序

```text
raw input
→ semantic interaction
→ owner-side Emotion
→ Relationship / Memory semantics
→ EventBus broadcast
→ frozen dialogue/body snapshot
→ presentation
```

## 4. Exactly-once

一次真实 semantic interaction：
- 只 apply 一次 Emotion；
- 只 apply 一次 Relationship；
- durable memory 不得由两个 owner 重复形成；
- dialogue reaction 不重复。

## 5. 验收

真实 `emit_event` production path 覆盖 pet/poke/click/drag；
测试不允许直接跳过 InteractionEngine 调内部 handler 冒充生产路径。
