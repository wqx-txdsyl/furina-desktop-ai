# Phase 11 — Scene Validation / Asset Coverage Gate

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 11`
>
> **Confidence:** `MEDIUM-HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `docs/FURINA_PHASE11_REPORT.md`
- `BACKEND_FREEZE.md`
- `furina/runtime/frontend.py`
- `furina/runtime/animation.py`

---

## 1. 场景

至少验证：
- quiet read；
- praise/embarrassed；
- proud；
- failure/high trust；
- deep work coexistence；
- sleep/wake。

## 2. 验证重点

- semantic diff 不因 timestamp/frame_id 重启动画；
- hesitation 产生 pre-hold/节奏，而非固定 gaze；
- sleep transition entry/loop/exit；
- asset resolver 对语义请求有 best-available；
- missing asset 可观察。

## 3. 完成条件

自动管线 PASS 只能证明技术正确；视觉“自然”如果未人工验收必须明确标 `MANUAL_PENDING`。
