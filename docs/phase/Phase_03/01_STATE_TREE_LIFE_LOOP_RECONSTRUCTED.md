# Phase 03 — State Tree / Continuous Life Loop

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 03`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M2`
- `plan/1 state tree.md`
- `plan/3 behaviour engine.md`
- `furina/state`
- `furina/emotion`
- `furina/behavior`

---

## 1. 目标

建立持续变化的角色内部状态，使芙宁娜不是“按钮触发动画”的播放器。

## 2. 状态

至少覆盖项目实际使用的需求/倾向变量：

```text
energy
hunger
fatigue
boredom
social_need
curiosity
playfulness
work_interest
attention
satisfaction
sleepiness
```

以及多维 Emotion。

每个状态必须明确：
- 范围；
- baseline；
- dt-based decay/recovery；
- clamp；
- event delta；
- snapshot/serialization。

## 3. Tick

- fast tick：表现/位置相关轻量更新。
- medium tick：需求、世界、行为/大脑。
- slow tick：低频维护。
- 时间步变化不能让数值行为完全不同。

## 4. 验收

- 长跑无 NaN / runaway。
- 同一 dt 总时长在不同 tick rate 下结果近似。
- 状态变化有可解释来源。
- 初始化状态符合健康 baseline，而不是一启动就极端。
