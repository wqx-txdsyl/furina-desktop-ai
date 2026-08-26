# Phase 05 — Small Window Runtime / Drag / Breath / Visual Shell

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 05`
>
> **Confidence:** `MEDIUM-HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M4`
- `plan/7 desktop runtime.md`
- `furina/world_perception.py`
- `furina/runtime/window_awareness.py`

---

## 1. 目标

确定桌宠窗口模型：小尺寸、整窗移动、拖拽稳定、透明置顶，不依赖复杂 setMask 重建。

## 2. 必须完成

- 小窗角色在桌面边缘/底部安全显示。
- shadow 是柔和剪影阴影，不是描边鬼影。
- debug overlay 默认关闭。
- 呼吸需要由真实 repaint/timer 推进，肉眼可见。
- DPI / reference size 基础兼容。
- 拖拽时不闪跳、不残影。

## 3. 验收

人工确认：
- 角色不占屏；
- 脚不被截；
- 拖拽稳定；
- 呼吸可见；
- 无明显 setMask 闪烁。

这部分是 runtime shell，不允许借机改变 Life semantics。
