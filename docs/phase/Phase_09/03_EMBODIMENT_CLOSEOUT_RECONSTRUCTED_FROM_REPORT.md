# Phase 09 — Embodiment Closeout / Freeze Preparation

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

## 1. 定位

在 Backend Freeze 前确认 Body semantic 足够表达前端所需信息。

## 2. 必须证明

- BodyExpressionState 完整可序列化。
- Dialogue/Emotion/Activity 变化会反映到 body semantic。
- Body Validator 工作。
- 无 Renderer/asset filename 泄漏到 domain layer。
- 后续 `CharacterRuntimeFrame` 可以只携带 semantic body intent。

## 3. STOP

通过后不继续打磨动画；进入 Runtime Contract / Backend Freeze。
