# Phase 09 — Embodied Expression / Semantic Body Layer

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 09`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `docs/FURINA_EMBODIMENT_REPORT.md`
- `furina/embodiment`
- `tests/test_embodiment.py`
- `BACKEND_FREEZE.md`

---

## 1. 目标

语言、情绪和活动必须转化为身体语义，而不是随机挑 PNG。

## 2. 输入

- activity
- emotion
- dialogue act
- persona mode
- relationship
- interaction
- world/presence

## 3. 输出 BodyExpressionState

至少包括：

```text
posture
expression
gaze
proximity
movement_tempo
movement_amplitude
hesitation
transition_style
micro_preferences
```

## 4. 不变量

Body 是确定性语义层、0 新 LLM。
Body 不直接选素材文件，也不反写 Life/Emotion/Memory。

## 5. 验收

同一情境可重复；
不同 emotion/persona/dialogue act 有可验证 counterfactual；
“害羞”可由 gaze/hesitation/posture/tempo 组合表达，不等于一张 embarrassed 图。
