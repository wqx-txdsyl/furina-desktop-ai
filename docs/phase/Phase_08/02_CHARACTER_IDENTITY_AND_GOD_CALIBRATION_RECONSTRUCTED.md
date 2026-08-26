# Phase 08 — Character Identity / God Calibration / Dialogue Act

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 08`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `docs/FURINA_DIALOGUE_CLOSEOUT.md`
- `furina/dialogue`
- `furina/persona/character_identity.py`
- `tests/test_dialogue_closeout.py`

---

## 1. 目标

把稳定身份、情境人格和语言策略分层，避免一个 `mood` 决定整个人格。

## 2. 分层

- Stable Character Identity
- Trait activation
- PersonaMode
- DialogueAct
- ExpressionStrategy

## 3. “本神”规则

只允许：
- preferred
- neutral
- suppressed

禁止 `if proud: force "本神"`。

## 4. 验收场景

- proud/playful；
- sincere/responsible；
- vulnerable；
- embarrassed；
- serious help；
- user rejects/returns。

同一角色要能在不同情境下保持连续身份而非单一模板。
