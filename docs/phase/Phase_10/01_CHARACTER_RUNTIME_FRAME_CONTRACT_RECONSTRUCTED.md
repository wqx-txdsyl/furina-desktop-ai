# Phase 10 — CharacterRuntimeFrame Contract

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

把后端所有对前端的真相收敛到一个版本化不可变 Frame。

```text
Backend domains
→ RuntimeFrameBuilder
→ CharacterRuntimeFrame v1
→ CHARACTER_FRAME_UPDATED
→ Frontend
```

## 2. Frame 规则

- immutable / frozen；
- schema version；
- semantic intent only；
- debug 可完全关闭；
- 不包含 asset filename、frame index、prompt、secret、memory body；
- 前端不得反向修改。

## 3. 唯一接口

生产前端只消费：

```text
current_frame()
CHARACTER_FRAME_UPDATED
```

`body_snapshot()` 等旧并行接口进入 deprecated。

## 4. 验收

serialization contract；
nested collection deep immutability；
old frontend direct state reads 清点。
