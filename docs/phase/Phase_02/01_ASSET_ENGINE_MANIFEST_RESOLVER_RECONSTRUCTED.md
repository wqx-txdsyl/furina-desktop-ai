# Phase 02 — Asset Engine / Manifest / Resolver

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

在“不使用 Live2D、主要依靠大量状态图与多帧序列”的约束下，把素材从散乱文件变成机器可解析的语义资产系统。

## 2. 核心链路

```text
semantic request
  ↓
AssetQuery
  ↓
AssetManifest
  ↓
AssetResolver
  ↓
AssetEntry / sequence
  ↓
renderer
```

## 3. Manifest 至少表达

- posture
- expression / emotion
- gaze
- direction
- action
- transition
- prop / interaction
- frame sequence
- fps
- loop
- anchor / hitbox / reference size
- identity/QC metadata

## 4. Resolver

优先级必须 deterministic：

```text
Exact
→ same posture/action
→ nearest compatible
→ neutral/best available
```

缺素材时必须记录 degraded/missing 事实，不能偷偷把所有东西都变成 idle 然后宣称成功。

## 5. 素材与语义隔离

生产行为代码不得硬编码 PNG 文件名作为主要语义决策。
素材层只能“呈现”动作，不能反向写 Needs / Emotion / Memory / Relationship。

## 6. 验收

- manifest load/save/schema 测试。
- resolver fallback 测试。
- 缺失素材时不崩溃且可观察。
- identity anchor / reference size 在不同资产中稳定。
- 当前真实素材可被程序解析。
