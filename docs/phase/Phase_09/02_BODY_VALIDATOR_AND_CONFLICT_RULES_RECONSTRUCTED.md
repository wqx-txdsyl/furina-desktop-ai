# Phase 09 — Body Validator / Conflict Rules

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 09`
>
> **Confidence:** `MEDIUM-HIGH`
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

阻止语义身体组合自相矛盾。

## 2. Validator 示例

- sleeping 时不允许强烈 user-facing active gesture。
- serious/vulnerable 情境避免过度 energetic。
- no-user/unknown presence 时避免强制 eye contact。
- high hesitation 应影响 timing/tempo，而不是固定看左。
- interaction reaction 可以短时 override baseline，但不能永久占 owner。

## 3. Gate

Validator 必须输出原因；
修正/降级 deterministic；
不得直接写素材。
