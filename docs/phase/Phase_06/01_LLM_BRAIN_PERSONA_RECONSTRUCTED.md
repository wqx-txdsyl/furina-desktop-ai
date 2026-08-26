# Phase 06 — LLM Brain / Structured Decision / Persona Foundation

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 06`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M5/M7/M8`
- `plan/5 computer agent.md`
- `plan/8 other details.md`
- `furina/life_brain.py`
- `furina/dialogue_brain.py`
- `furina/director`

---

## 1. 目标

LLM 只负责高价值推理与语言，不成为高频控制器。

## 2. Brain boundary

至少区分：
- LifeBrain：高层生命决策；
- DialogueBrain：语言表达；
- Agent：电脑操作。

后续系统明确坚持三脑，不新增第四个随意 LLM owner。

## 3. 要求

- provider adapter 可插拔；
- 输出结构化/schema validated；
- LifeBrain 只产 decision，不直接写 authoritative Emotion/Needs；
- DialogueBrain 只决定说什么，不直接执行工具；
- LLM fail/fallback 可观察；
- 不解析自由文本去驱动工具。

## 4. Persona

Persona 进入 prompt/context/validator，但不能靠固定台词池假装人格。
“本神”等强口癖必须按情境 preferred/neutral/suppressed。

## 5. 验收

- 无 LLM 仍有 deterministic life fallback。
- invalid structured output 不进入领域。
- Dialogue 与 Life 的职责边界有测试。
