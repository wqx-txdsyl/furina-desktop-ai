# Phase 12V — Post-recovery Manual Re-acceptance

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 12`
>
> **Confidence:** `MEDIUM`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `docs/FURINA_PHASE12_REPORT.md`
- `FURINA_PHASE12V_VISUAL_RUNTIME_RECOVERY.md`
- `furina/runtime/spatial`

---

## 1. 定位

根据已找回的 Phase 12V 原始任务书：自动 349/349 曾不足以证明视觉链真实可用，因此 recovery 后必须重新人工验收。

## 2. 人工重点

- semantic action 是否肉眼可见；
- read/eat/play/think/sleep 是否不再都像 idle；
- entry/loop/exit 是否真实推进；
- breath 是否作用于角色 body 而非整个窗口；
- drag ownership；
- walk visual 与 spatial movement 同步；
- dialogue bubble/角色身体是否无 ownership 争抢。

## 3. Gate

用户未确认前不得把 `PARTIAL — VISUAL CLOSEOUT REQUIRED` 改为完全 PASS，也不得进入 Phase 13。
