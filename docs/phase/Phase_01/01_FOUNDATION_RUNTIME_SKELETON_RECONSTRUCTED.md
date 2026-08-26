# Phase 01 — Foundation Runtime Skeleton / Minimum Vertical Slice

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 01`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M0`
- `plan/0 main plan.md`
- `tests/test_skeleton.py`
- `main.py`

---

## 1. 任务目标

先做一个最小但真实的桌面生命运行骨架，使后续任何功能都能接在稳定 Runtime 上，而不是先堆 UI、素材或模型能力。

目标形态：

```text
main.py
  ↓
Furina App aggregate
  ├─ EventBus
  ├─ CharacterState / StateEngine
  ├─ Behavior skeleton
  ├─ Interaction skeleton
  ├─ Memory skeleton
  ├─ LLM adapter seam
  ├─ Agent seam
  ├─ Director seam
  └─ PySide6 desktop window
```

## 2. 必须完成

- 建立 `furina/` 模块化包结构，模块可独立 import。
- PySide6 创建透明、无边框、置顶桌面窗口，可正常退出。
- EventBus 作为跨模块的显式通信骨架。
- 建立基础 CharacterState、clock/tick、life loop。
- `main.py` 至少支持正常启动、`--smoke`、`--selfcheck`。
- 任何 LLM 初始化失败时，确定性核心仍能启动。
- 日志能够看到模块初始化、关键事件与异常。

## 3. 工程约束

- 禁止把全部功能塞回 `app.py`。
- 禁止让动画成为领域状态来源。
- 禁止在渲染 tick 中调用 LLM。
- 跨模块修改必须通过显式 API / EventBus。
- 先保证可运行、可测试、可观察，再扩能力。

## 4. 验收 Gate

- 所有核心模块 import 成功。
- `--selfcheck` 返回 OK。
- `--smoke` 能启动并自动退出，无崩溃。
- skeleton 单测全绿。
- LLM 不可用时，基础窗口/生命循环仍运行。
- 不允许用空 `except: pass` 把启动错误伪装为通过。

## 5. STOP

本轮通过后停止。不要顺手实现完整素材、复杂记忆、Office Agent 或 Persona。
