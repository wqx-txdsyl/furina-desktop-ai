# Universal Office / Life Agent — Architecture Reservation

> STATUS = PLANNED
> NO IMPLEMENTATION YET
> 本文件冻结未来 Universal Agent 的 capability domains 与执行管线。不实现。

## Capability Domains（冻结）

| Domain | 覆盖 |
|---|---|
| Filesystem | 文件/目录操作 |
| Documents | 文档读写/整理 |
| Browser | 浏览器/网页 |
| Applications | 应用启动/控制 |
| Communication | 通讯/消息 |
| Calendar / Life | 日历/生活事务 |
| Desktop Perception | 桌面/屏幕感知 |
| Knowledge / Research | 知识检索/研究 |

## 执行管线（保留）

```
Capability Registry → Planner → Permission → Execute → Verify → Report
```

- Capability Registry：能力注册（domain → tools）
- Planner：目标 → 计划（LLM 只产 Goal/Plan，不直接调工具）
- Permission：权限确认（L0/L1 自动，L2/L3 角色确认）
- Execute：真实执行工具
- Verify：执行后验证（绝不假装成功）
- Report：结果绑定报告（FACT_CORE）

## 未来 Character Agency：Work Willingness（架构预留，不实现）

工作意愿状态：

```
EAGER
WILLING
RELUCTANT
PROTEST
REFUSE
```

未来受以下因素影响：

```
energy
fatigue
mood
relationship
annoyance
task_interest
recent_workload
urgency
```

> 此处只记录架构方向；当前 Agent 仍按既有 `furina/agent/` 语义工作。
