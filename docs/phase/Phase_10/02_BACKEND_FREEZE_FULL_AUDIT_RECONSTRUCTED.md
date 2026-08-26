# Phase 10.5 — Backend Freeze Full Audit

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 10`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `docs/BACKEND_FREEZE.md`
- `docs/FURINA_BACKEND_AUDIT.md`
- `FURINA_RC1_CLOSEOUT_REPORT.md`
- `furina/runtime/frame.py`

---

## 1. 目标

冻结前不靠测试数自信，做一次真实所有权/线程/production-path 审计。

## 2. 分类

发现项只能归类：

```text
BLOCKER
SHOULD_FIX_BEFORE_FRONTEND
ACCEPTED_TECH_DEBT
FRONTEND/FUTURE
```

只有 BLOCKER 允许解冻后端做最小修复。

## 3. 必审

- State/Emotion/Behavior owner；
- Relationship 单一 writer；
- Memory 跨线程；
- LifeBrain/Director contract；
- Dialogue/Embodiment owner；
- RuntimeFrame single source；
- Scheduler 是否存在表现/领域双写。

## 4. Evidence

每个 blocker：

```text
BEFORE reproduction
→ root cause
→ minimal fix
→ AFTER proof
```

禁止只靠 grep/静态判断宣布关闭。
