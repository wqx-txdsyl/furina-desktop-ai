# Phase 04 — Feeding / Drag / User Takeover Integration

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 04`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M3`
- `plan/4 interaction engine.md`
- `furina/interaction`
- `furina/feeding.py`
- `Phase 13 interaction hardening history`

---

## 1. Feeding

蛋糕/茶/面包等喂食必须走同一生产入口：

```text
feed input
→ food effect
→ needs
→ emotion
→ optional memory
→ life interrupt
→ dialogue snapshot
```

所有 domain effect 必须在 dialogue worker 启动前完成。

## 2. Drag

用户拖拽时：
- 用户立即接管身体位置；
- autonomous movement 停止/中断；
- release 提交新位置；
- 有 grace window，避免立即 snap-back。

## 3. User takeover

真实定型 interaction 可中断可中断的 mind activity；
hover/leave 等 pointer control 不抢占 Life activity。

## 4. 验收

- feed effect exactly-once。
- GUI 与 Harness 走同一路径。
- drag release 不回弹。
- 用户 takeover 会立即冻结当前 activity progress 并结算一次。
