# Phase 05 — Windows World Perception / Window Awareness

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 05`
>
> **Confidence:** `HIGH`
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

让 Furina 感知真实 Windows 世界，而不是行为层自行猜“用户在干什么”。

## 2. 原始事实

至少采集：
- foreground window title/process/class；
- process exe category；
- window rect；
- screen / available geometry；
- user idle sample availability；
- taskbar/safe bounds。

## 3. Truth boundary

必须区分：

```text
raw fact
available?
derived semantic
```

`unknown` 不能被当作 false；idle sample unavailable 不能被强制变成 `0s active`。

## 4. 稳定性

foreground/分类变化需 stability window/hysteresis，避免瞬态切窗让角色频繁改变行为。

## 5. 验收

- browser ↔ code 等真实切换有稳定 transition。
- idle unavailable 端到端保留。
- failed OS poll 不制造 user-return/user-active 假事件。
- world layer 不直接写 Emotion/Relationship。
