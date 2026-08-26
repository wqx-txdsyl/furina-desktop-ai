# Phase 11 — Step 0 Contract Cleanup

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

## 1. 在新增动画前先清四个 blocker

1. 删除 `SPEECH_LINES` / `_behavior_speech` 等硬编码语言旁路。
2. `CharacterRuntimeFrame` 做深不可变，不只是 dataclass 顶层 frozen。
3. 删除 Scheduler→Window 双重直写；Frame/consumer 是主链。
4. 修正 AnimationController play contract、blink 实际发生、non-loop completion。

## 2. 验收

- Scheduler production source 中窗口主路径直写为 0。
- Frame nested tuple/mapping 不可修改。
- blink 峰值真实 > 0。
- non-loop 最终 finished，loop 不 finished。
- serialization 仍保持 v1 JSON contract。
