# Phase 08 — Dialogue Persona Control

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

从“能聊天”提升为“输出稳定属于芙宁娜，而且不会因为人格模板损害真实对话”。

## 2. Pipeline

```text
DialogueContext
→ PersonaMode
→ DialogueAct
→ ExpressionStrategy
→ LLM
→ Validator
→ calibration gate
→ surface/silence
```

## 3. 要求

- direct user turn / ambient / feed reaction / agent report / interaction reaction 分 channel。
- direct history 不允许 orphan user turn。
- concurrent direct turns 按 ingress 顺序。
- invalid response 不得原样 surface。
- validation failure 可进行一次有界 regeneration，仍失败则明确 system-status/silence。
- 严肃帮助时 suppress 不合时宜的夸张口癖。

## 4. 验收

多类人格场景 counterfactual；
generic-assistant leakage 检测；
validator 真正阻止错误输出，而不是只打日志。
