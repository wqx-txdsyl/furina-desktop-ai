# Phase 02 — Asset Generation / QC / Identity Consistency

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 02`
>
> **Confidence:** `MEDIUM-HIGH`
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

建立基座图驱动的素材生成与 QC 规则，让生成资产可以批量加入 Manifest，而不是人工随意命名。

## 2. 要求

- 基座参考图作为身份锚点。
- 生成输出必须透明背景或可稳定抠图。
- 尺寸、角色脚底锚点、构图范围可统一。
- 检查服装、发色、发饰、眼睛、比例与整体 2D 风格一致性。
- 不把低质量/身份漂移图加入 production manifest。
- 生成工具失败时保留任务清单，不污染运行时。

## 3. QC 输出

每个资产至少记录：

```text
semantic tags
source/reference
approved / rejected
reason
anchor
frame/sequence metadata
```

## 4. 验收

- 首批核心姿态/表情/视线/动作能通过 Resolver 使用。
- QC 有明确 rejected path。
- 运行时不依赖生成服务在线。
