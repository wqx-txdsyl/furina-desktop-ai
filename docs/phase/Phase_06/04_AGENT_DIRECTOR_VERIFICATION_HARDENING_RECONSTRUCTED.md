# Phase 06 — Agent/Director Verification Residual Hardening

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 06`
>
> **Confidence:** `MEDIUM`
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

## 1. 目的

锁定后续 reviewer 发现的 false-green 风险，使 Agent 和 Director 的“成功/执行”都对应真实生产事实。

## 2. 必须证明

- Agent `ok AND verified` 才算成功。
- calc/notepad 等映射必须验证真实目标进程。
- Agent body request 经 Director，不直接写身体状态。
- Director preemption callback 在 takeover 当刻 finalize activity。
- 被 blocked mind request 无自主 speech、无 bid。
- 测试必须实际调用工具 mock step/真实验证接口，不能只 mock 最终结果对象。

## 3. STOP

只加 truth/verification，不扩 Office 能力。
