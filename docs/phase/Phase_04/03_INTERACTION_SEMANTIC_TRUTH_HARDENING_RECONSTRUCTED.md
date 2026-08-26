# Phase 04 — Interaction Semantic Truth / Ignore Boundary Hardening

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 04`
>
> **Confidence:** `MEDIUM`
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

## 1. 背景

后续 Phase 13 reviewer 明确暴露了若干早期 Interaction 语义债。本重建文件保存这些应被视为 Phase 04 合约的边界。

## 2. 不变量

- pointer leave ≠ USER_IGNORE。
- unknown interaction kind ≠ click。
- poke / drag / petting 的记忆内容必须保持客观差异。
- 拒绝级 poke 不能被记录成正面的“轻轻摸头”。
- user response window 必须由真实 social bid 开启。
- 没有可观察 bid 时，timer 不能凭空制造“用户忽略我”。

## 3. 验收

为每种 interaction 断言：
- event type/payload；
- Emotion effect；
- Relationship effect；
- memory content/provenance；
- exactly-once。

本轮只修 semantic truth，不扩互动种类。
