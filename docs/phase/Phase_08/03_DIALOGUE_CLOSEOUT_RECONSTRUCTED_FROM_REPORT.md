# Phase 08 — Dialogue Closeout / Reviewer Gate

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 08`
>
> **Confidence:** `MEDIUM-HIGH`
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

## 1. 定位

依据 `docs/FURINA_DIALOGUE_CLOSEOUT.md` 反向恢复最终 gate。

## 2. Gate

- 删除硬编码角色台词旁路。
- DialogueBrain 是生产语言唯一来源。
- validator/god calibration 真正执行。
- fallback 不泄漏 generic assistant。
- history pairing / ordering 稳定。
- Persona 指纹测试覆盖 pride、vulnerability、help、rejection 等。

## 3. 禁止

- 为了过测试加固定回答。
- 用关键词硬改某一句 benchmark。
- 把 Persona 问题转嫁给 Renderer。
- 新增另一个语言 LLM owner。

## 4. 完成后

Dialogue 语义可被冻结，下一阶段转 Body/Embodiment。
