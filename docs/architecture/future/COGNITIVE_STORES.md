# Cognitive Stores — Architecture Reservation

> STATUS = PLANNED
> NO IMPLEMENTATION YET
> 本文件冻结未来认知存储的**逻辑划分**。当前版本不创建任何 Cognitive DB / Python 模块。

## 7 个逻辑 Store（冻结）

| ID | Store | 一句话 | 回答的问题 |
|---|---|---|---|
| C1 | Canon Identity | “我是谁” | 芙宁娜的身份/人格事实（Canon 源：`furina/persona/furina_canon.py`） |
| C2 | Canon Life History | “游戏主线/传说任务/角色故事中，我以前经历过什么” | 过去的经历及其人格影响 |
| C3 | Runtime Autobiographical Memory | “来到桌面世界以后，我新经历了什么” | 与用户共处后的新记忆 |
| C4 | User Model | “用户是谁” | 用户画像/偏好/习惯 |
| C5 | Relationship | “我们是什么关系” | 关系状态（当前 `relationship/` 引擎的演进） |
| C6 | Life / Event Timeline | “客观上实际上发生了什么” | 客观事件时间线 |
| C7 | Agent Task History | “我替用户做过什么、结果是什么” | Agent 任务历史与结果 |

## Derived layer

- **Semantic Vector Index**：跨 store 的语义向量索引（检索基础）。

## Processes

- **Memory Consolidation**：短期 → 长期巩固
- **Interpretation / Belief Update**：解释经历 → 更新信念/人格影响
- **Retrieval**：按查询/上下文检索
- **Context Assembly**：组装进入对话/决策的上下文

## 关键边界

**Canon Life History ≠ 剧情百科。**

C2 不存“剧情设定条目”，存的是**经历**及其人格影响：

- 经历（当时发生了什么）
- 当时知道/不知道什么（信息边界）
- 心理影响（当时感受/认知）
- 当前人格影响（对现在的“我”意味着什么）

## 当前版本对应（现状，非新实现）

- C1 → `furina/persona/furina_canon.py`（Canon 常量）
- C3 → `furina/memory/`（Runtime 记忆，SQLite）
- C5 → `furina/relationship/`（关系引擎）
- C7 → Agent 完成记忆（`memory` observe agent_task）
- C2 / C4 / C6 → 未实现（PLANNED）
