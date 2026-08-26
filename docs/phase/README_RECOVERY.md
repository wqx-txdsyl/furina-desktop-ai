# Furina Phase Taskbook Recovery v1

这是一次“**历史任务书恢复**”，不是每个 Phase 的总结版 PRD。

## 当前恢复原则

用户明确要求保留每个 Phase 的多轮任务书历史，因此本归档采用：

```text
Phase_xx/
  00_MANIFEST.md
  多个初始 / 修复 / reviewer / hotfix / final-gate taskbook
```

而不是“一阶段一个 canonical 总结”。

## 真实性分级

### EXACT_RECOVERED

从当前会话/ChatGPT Library 中找回的原始生成文件，正文原样复制。

目前主要集中在：
- Phase 12V
- Phase 13 多轮 Closeout / Reviewer / Hotfix / Pre-Manual
- Phase 14 两轮 Final Closure

### RECONSTRUCTED

没有找到逐字原件时，依据：
- repository `PHASE_PLAN.md`
- `plan/0~8`
- 后续阶段报告
- code ownership comments
- reviewer/final gate 文件
- 当前可验证架构

反向恢复任务书。

**所有重建稿都在正文顶部标明 `RECONSTRUCTED`，绝不冒充原文。**

## 当前统计

- Exact recovered task/acceptance files: **18**
- Reconstructed task files: **38**

| Phase | Exact | Reconstructed |
|---|---:|---:|
| Phase 01 | 0 | 2 |
| Phase 02 | 0 | 3 |
| Phase 03 | 0 | 3 |
| Phase 04 | 0 | 3 |
| Phase 05 | 0 | 3 |
| Phase 06 | 0 | 4 |
| Phase 07 | 0 | 3 |
| Phase 08 | 0 | 3 |
| Phase 09 | 0 | 3 |
| Phase 10 | 0 | 3 |
| Phase 11 | 0 | 3 |
| Phase 12 | 1 | 3 |
| Phase 13 | 15 | 1 |
| Phase 14 | 2 | 1 |

## 特别说明

1. Phase 01–11 的逐字任务书原件目前没有在 Library 中检索到，因此主要为重建。
2. Phase 12 找回了 `FURINA_PHASE12V_VISUAL_RUNTIME_RECOVERY.md`。
3. Phase 13 找回了大量真实多轮任务书，这是目前恢复最完整的阶段。
4. Phase 14 找回了当前两份真实修复任务书；初始 Phase 14 原件仍缺失，只做了低置信重建。
5. 未来继续恢复时应创建 `v2/v3` 或直接在同一目录新增 `EXACT_RECOVERED` 文件，不要静默重写历史。

## 推荐放入仓库

建议最终仓库结构：

```text
phase/
  README_RECOVERY.md
  RECOVERY_LEDGER.md
  Phase_01/
  ...
  Phase_14/
```

`phase/` 保存“当时要求模型做什么”；`docs/` 保存“模型实际做了什么、测试/审计/报告”。
