# Phase 02 — Multi-frame Animation Foundation / M1.5

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 02`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M1 / M1.5`
- `plan/2 asset engine.md`
- `data/assets/manifest.json`
- `tests/test_assets.py`
- `tests/test_animation.py`

---

## 1. 目标

把静态状态图升级为能表现“活着”的多帧动画，但保持动画层纯表现。

## 2. AnimationController 必须支持

- fps
- loop / non-loop
- interrupt
- current frame
- progress
- finished
- entry / loop / exit
- transition sequence
- breathing baseline
- safe fallback

## 3. 关键序列

优先支持站↔坐、坐↔躺、睡眠/醒来、eat/play 等基础转场。
walk 如果真实素材尚不可用，机制先就绪，视觉债显式记录。

## 4. 不变量

- 动画完成不能自动修改 Life 状态。
- Renderer 不重新决定行为。
- interruption 必须有确定性规则。
- 播放缺帧不导致索引越界或卡死。

## 5. 验收

- loop 永不错误标 finished。
- non-loop 正确到末帧并 finished。
- transition 可中断且不会残留错误 owner。
- 无视频生成服务时仍能运行现有静态资产。
