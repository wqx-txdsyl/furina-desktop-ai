# Phase 11 — Frontend Character Runtime / Animation Integration

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 11`
>
> **Confidence:** `HIGH`
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

## 1. 目标

让 frontend 真正只消费 `CharacterRuntimeFrame`，把 semantic truth 转成可见动画。

## 2. 新 ownership

```text
Frame = semantic truth
FrontendFrameConsumer = semantic diff
AnimationPlanner = presentation plan
AnimationRuntime = timing owner
MicroScheduler = micro clocks
FurinaWindow.present = view entry
paintEvent = draw only
```

## 3. 必须实现

- FrontendVisualState；
- semantic diff；
- transition planner；
- animation runtime；
- blink/breath/gaze/micro scheduler；
- `window.present()` 主路径；
- actual manifest resolver。

## 4. 禁止

Scheduler 直接写 Window presentation；
paintEvent 推进 Life 状态；
前端读 Needs/Memory；
新增 LLM。
