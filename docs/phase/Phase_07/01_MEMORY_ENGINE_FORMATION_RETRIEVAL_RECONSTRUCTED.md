# Phase 07 — Memory Engine / Formation / Retrieval

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 07`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M6`
- `plan/6 memory engine.md`
- `furina/memory`
- `furina/relationship`
- `BACKEND_FREEZE.md`

---

## 1. 目标

让 Furina 具备持续记忆，但严格区分事实、观察、经历和关系状态。

## 2. Memory 类型

至少区分：
- explicit user fact；
- observation；
- episodic experience；
- semantic knowledge；
- relationship state。

推测不能默认升级为用户事实。

## 3. Formation

- significance/importance threshold；
- repetition reinforcement；
- dedupe；
- capacity governance；
- source/provenance；
- thread-safe persistence。

低重要事件允许遗忘。

## 4. Retrieval

融合：
- semantic/relevance；
- recency；
- importance；
- relationship；
- context specificity。

context 不匹配的 memory 必须显著降权或不返回。

## 5. 验收

事件形成→重启→检索→Dialogue 使用可证明；
重复事件 reinforce 不重复污染；
capacity 有界。
