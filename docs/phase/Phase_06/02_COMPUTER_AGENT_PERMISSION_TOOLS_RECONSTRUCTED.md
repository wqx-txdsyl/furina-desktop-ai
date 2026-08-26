# Phase 06 — Computer Agent / Tools / Permission

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 06`
>
> **Confidence:** `HIGH`
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

## 1. 生命周期

```text
Observe
→ Plan
→ Risk
→ Permission
→ Execute
→ Verify
→ Report
```

## 2. Tool Registry

初期允许文件、启动应用、浏览器等明确工具。
未知 app/tool 必须失败，不能默认启动记事本之类替代品。

## 3. Permission

至少保留风险分级：
- 自动允许；
- 低风险确认；
- 高风险每次确认；
- 禁止。

任何自主任务不得绕过用户权限边界。

## 4. Truthfulness

`res.ok` 不等于成功；所有工具必须经过可观察 verify。
未 verified 不得输出 `COMPLETED_VERIFIED`，也不得形成“我成功帮用户完成了”记忆。

## 5. 验收

- dry-run 与真实写操作区分。
- 文件整理验证执行后树。
- app.launch 验证真实进程/窗口。
- Agent failure 有 factual report，不伪造成功。
