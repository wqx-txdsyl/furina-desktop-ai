# PHASE13 — Manual Functional Acceptance（用户亲手验收）

运行：`python main.py --harness`（不渲染任何 PNG；无素材依赖）。

完成后请按下方勾选。**Agent 不代你勾选**。

## Scenario A — 普通对话（多轮）
- 在 CONVERSATION 输入并与她聊几轮（普通闲聊 / 问她在干嘛 / 夸她 / 轻微调侃 / 认真求助 / 沉默后再说话）。
- `[ ]` 每轮能看到 Furina 真实回复（右上 `DialogueBrain: glm ✓` 或 `FALLBACK`）。
- `[ ]` 回复携带真实上下文（她在做的事 / 关系 / 记忆），不空泛。

## Scenario B — Life Autonomy
- 什么也不做，看几分钟。
- `[ ]` `LifeBrain: glm`，Current Life 区 activity 会自然变化，Body/Spatial 随之更新。
- `[ ]` 不是固定 10 秒强切，而是生产节拍。

## Scenario C — 夸 / 摸头
- 点 `[摸头]`。
- `[ ]` Current Life 的 Emotion / Relationship 有真实变化；对话区有 Furina 真实反应（来自 DialogueBrain）。
- `[ ]` 【展开 Trace】能看到 HEAD_TOUCH → Emotion/Relationship before/after → Memory → Dialogue 链。

## Scenario D — 拒绝
- 点 `[拒绝]`。
- `[ ]` 后续她接近/主动聊天的倾向**确实下降**（看未来行为，不只即时数值）。

## Scenario E — 关系恢复
- 拒绝后恢复正常交流。
- `[ ]` 关系能回升（非永久负面）。

## Scenario F — 喂食
- 高 hunger 与普通 hunger 各喂一次（[蛋糕]/[茶]/[面包]）。
- `[ ]` Trace 显示 `Hunger 62 → 31` 之类真实变化；`Activity idle → eat`；Furina 有真实反应。

## Scenario G — Memory
- 告诉她"我今天准备完成桌宠的功能测试。"
- 之后问"我之前说今天准备做什么？"
- `[ ]` Memory retrieval 真正命中；答案合理利用该信息（不是数据库有一行就算）。

## Scenario H — Spatial Proxy
- 观察方框：`[ ]` 不频繁乱跑；`[ ]` MAINTAIN 能保持；`[ ]` Approach 不贴目标中心；`[ ]` Withdraw 明显远离；`[ ]` Wander 有停留。
- 拖方框：`[ ]` 不抢控制；`[ ]` 松手不 snap-back。

## Scenario I — Agent
- `[打开记事本]` → `[ ]` 真打开；Trace 显示 planner/permission/tool/result。
- `[整理测试目录]` → `[ ]` 只操作 `tmp/harness_agent_test/`，结果合理。

## Scenario J — Failure Survival
- 模拟一次 LLM 失败 / Agent 失败（DEV TEST ONLY 面板）。
- `[ ]` 系统仍活着；`Life/Dialogue` 徽章显示 `FALLBACK`（不是假绿）。

## Furina Persona（最重要）
> 把方框上的名字 `FURINA` 遮住，只通过她的行为和说话，能否感到这是同一个具体角色，而不是通用助手？

- `[ ]` 不像通用 AI 助手
- `[ ]` 有 Furina 表达辨识度
- `[ ]` 不是旧 Archon Mask 常驻
- `[ ]` 不会满嘴"本神"
- `[ ]` 普通聊天自然
- `[ ]` 真诚场景能收住表演
- `[ ]` 不每句夸张
- `[ ]` 不机械复读

## Persona Verdict（用户给）：`PASS / PARTIAL / FAIL`

## Overall（用户给）：`PASS / PASS-AUTO/MANUAL_FUNCTIONAL_PENDING / PARTIAL / FAIL`
（只有上列功能 + Persona 全部通过才为 Phase 13 PASS）
