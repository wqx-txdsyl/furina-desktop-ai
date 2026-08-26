# Phase 03 — Emotion → Motivation → Behavior Closure

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 03`
>
> **Confidence:** `HIGH`
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

形成真正闭环：

```text
event/world
  ↓
Emotion + Needs
  ↓
BehaviorMotivation candidates
  ↓
utility + personality + feasibility
  ↓
chosen behavior
  ↓
runtime execution
```

## 2. Emotion

事件映射必须 deterministic；LLM 不直接写 authoritative Emotion。
多维 emotion 派生 label，但 label 不成为第二套独立真相。

## 3. Motivation

候选评分至少允许：
- needs
- emotion
- personality
- world
- relationship/memory hints
- cooldown
- feasibility

参与。

禁止把“为了看起来多样”实现成无条件轮换行为。

## 4. Behavior

行为有 duration、cooldown、interruptible、tags、可选 chain。
用户工作时存在打扰成本；生存需求优先级合理。

## 5. 验收

- needs counterfactual 会改变候选排序。
- praise/reject/poke 等 emotion counterfactual 会改变倾向。
- 相同输入 deterministic core 可复现。
- LLM 不可用时仍可由 deterministic Behavior fallback 生存。
