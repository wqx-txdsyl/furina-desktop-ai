# Phase 06 — Director / Unified Action Arbitration

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 06`
>
> **Confidence:** `HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M5/M7/M8`
- `plan/5 computer agent.md`
- `plan/8 other details.md`
- `furina/life_brain.py`
- `furina/dialogue_brain.py`
- `furina/director`

---

## 1. 目标

所有竞争性的“身体/动作占用”由 Director 唯一仲裁，Life、Dialogue、Agent 不互相抢写。

## 2. ActionRequest

至少包含：

```text
source
action
priority
interruptible
reason
payload
```

## 3. 核心规则

- 更低优先级请求绝不替换更高优先级 current，和 current 是否 interruptible 无关。
- 相同优先级保持明确既有语义。
- 更高优先级才可能 preempt。
- 被阻塞 request 不得提前产生 activity instance、speech、social bid 或 outcome。
- finish 后队列继续 drain。

## 4. 验收

必须有真实 `director.drain()` production-equivalent 测试，而不是只证明“没 drain 时没执行”。

Agent active + repeated drain 时，低优先级 mind 不能顶掉 Agent；
Agent finish 后 queued mind 才开始。
