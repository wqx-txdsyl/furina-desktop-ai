有。**而且我认为确实还有最后一条，而且应该现在补上。**

前面 ①～⑦解决了“芙宁娜怎么活”，但还缺一个东西：

# ⑧ Orchestration / Director —— 芙宁娜的“意识调度层”

它不是新的功能模块，而是**把前面七个系统真正组织起来的总导演**。

如果没有这一层，你直接让 Qwen3.8 去写代码，很容易出现一个典型问题：

> 每个模块都能运行，但模块之间互相抢控制权。

例如：

* Behavior 说“去睡觉”
* Agent 说“去 VS Code”
* Interaction 说“用户刚刚摸我，必须回应”
* Memory 说“今天用户很累，应该陪伴”
* State 说“困了”
* Scheduler 又触发了随机散步

最后代码变成一堆：

```python
if ...
elif ...
elif ...
```

然后越写越乱。

所以最后必须补上：

> **谁拥有决定权？什么事情可以打断什么事情？什么时候调用 Qwen3.8？**

---

# ⑧ Director：统一决策与调度层

核心职责只有一句：

> **它不创造行为，只负责决定当前哪个系统应该拥有控制权。**

---

## 1. 六个系统不能平权

必须有优先级。

我建议：

```text
最高
│
├── Safety / User Control
│
├── Direct User Interaction
│
├── Active Agent Task
│
├── Important Internal Need
│
├── Autonomous Behavior
│
└── Idle / Micro Behavior
最低
```

例如：

### 芙宁娜正在散步

突然用户摸头：

> **立刻打断散步。**

因为：

```text
Interaction > Autonomous Behavior
```

---

### 芙宁娜正在睡觉

用户说：

> “帮我打开 VS Code。”

则：

```text
User Request > Sleep
```

唤醒。

---

### Agent 正在整理文件

芙宁娜突然想喝茶：

> **不能直接打断 Agent。**

因为：

```text
Active Agent Task > Internal Need
```

她可以：

> 等 Agent 完成。

---

# 2. 建立统一 Action Queue

所有系统都不能直接控制身体。

都必须提交：

```text
Action Request
```

例如：

```json
{
  "source": "behavior",
  "action": "walk",
  "priority": 30,
  "interruptible": true
}
```

Interaction：

```json
{
  "source": "interaction",
  "action": "head_touch_reaction",
  "priority": 80,
  "interruptible": true
}
```

Agent：

```json
{
  "source": "agent",
  "action": "work",
  "priority": 70,
  "interruptible": false
}
```

Director：

> 决定谁执行。

---

# 3. 这是避免代码失控的关键

最终不要允许：

```text
Behavior → Renderer
Interaction → Renderer
Agent → Renderer
State → Renderer
```

全部直接调用。

应该只有：

```text
State
Behavior
Interaction
Agent
Memory
       ↓
 Action Requests
       ↓
   Director
       ↓
Character Runtime
       ↓
Renderer
```

这一个规则，**一定写进 PRD。**

---

# 4. Director 还负责“Qwen 什么时候醒”

这是针对 **Qwen3.8** 特别重要的一点。

千万不要让 Qwen：

> 一直思考芙宁娜现在应该干什么。

这会让整个系统变慢、复杂，而且 Qwen3.8 的本地推理成本会直接成为桌宠瓶颈。

应该：

```text
普通情况
→ 本地规则系统

复杂情况
→ Qwen3.8
```

---

# 5. 什么事情不需要 Qwen3.8

全部本地完成：

* 眨眼
* 呼吸
* 走路
* 坐下
* 睡觉
* 基础情绪变化
* 鼠标摸头
* 拖拽
* 基础需求变化
* 时间变化
* 窗口检测
* 简单主动行为
* 动画切换
* Hitbox
* 基础 Agent 工具调用

这样芙宁娜才会：

> **快。**

---

# 6. 什么事情才调用 Qwen3.8

### 语言

> 用户和她聊天。

### 复杂意图

> “你觉得我现在应该先干哪个？”

### 复杂关系判断

> 用户行为出现明显变化。

### 复杂自主行为

> 她遇到了一个以前没见过的情况。

### Agent Planning

> 多步骤电脑任务。

### Memory Consolidation

> 一天结束后的经历整理。

也就是说：

> **Qwen3.8 是低频、高价值决策器。**

---

# 7. Qwen3.8 的一个现实问题：不要让它输出自由文本控制系统

这一点我尤其想提醒你，因为**代码 AI 很容易把这个坑直接写进项目**。

不要设计成：

```text
Qwen:
“我觉得我应该走到右边，然后看看主人在做什么……”
```

程序再通过字符串解析。

绝对不要。

---

# 8. Qwen3.8 输出必须结构化

例如：

```json
{
  "intent": "help_user",
  "emotion": "concerned",
  "action": "approach_user",
  "speech": "要不要我帮你看看？",
  "priority": 65,
  "reason": "user_has_been_working_for_long_time"
}
```

程序只解析：

```text
intent
emotion
action
priority
speech
```

不要解析自然语言。

---

# 9. 更进一步：让 Qwen3.8 只能使用有限枚举

例如：

```text
action:

IDLE
APPROACH
WALK
TALK
PLAY
REST
SLEEP
OBSERVE
HELP
ASK_PERMISSION
RUN_AGENT_TASK
```

而不是：

> “Qwen 想出来一个 `go_and_peek_at_user`。”

否则你的代码很快会爆炸。

---

# 10. Prompt 也不要写成一个超级大 Prompt

这是我认为**你用 Qwen3.8 做代码实现时尤其应该注意的地方**。

不要让代码 AI 写：

```text
一个 5000 行 prompt
里面包含人格、状态、工具、记忆、所有规则……
```

应该拆成：

```text
Persona Prompt
+
Current State
+
Relevant Memories
+
Current Environment
+
Available Actions
+
Current Task
```

组合成当前请求。

这样：

> 更容易调试。

也更符合 Qwen 系列模型做结构化 Agent 的方式。

---

# 11. 对 Qwen3.8 的另一个要求：代码必须“显式”，不要过度魔法化

你现在不是在做一个传统 Web 项目。

这种项目最怕 Qwen 写成：

```text
BaseCharacter
    ↓
SmartCharacter
    ↓
AICharacter
    ↓
EnhancedAICharacter
    ↓
UltimateFurinaManager
```

然后几百个类互相继承。

**不要。**

第一版应该：

> 简单、明确、模块化。

例如：

```text
runtime/
state/
behavior/
interaction/
memory/
agent/
assets/
director/
```

每个模块都有清晰输入输出。

---

# 12. 我甚至建议你让 Qwen3.8 先写“事件总线”

整个项目的神经系统：

```text
EventBus
```

所有重要事情都变成 Event：

```text
USER_CLICK
HEAD_TOUCHED
USER_SPEAK
WINDOW_CHANGED
USER_IDLE
USER_RETURNED
AGENT_STARTED
AGENT_COMPLETED
AGENT_FAILED
MEMORY_CREATED
STATE_CHANGED
SLEEP_STARTED
WAKE_UP
```

然后：

```text
Event
 ↓
Director
 ↓
Relevant Systems
```

这样模块之间不会互相硬编码。

---

# 13. 最终架构我建议定成这张

```text
                         ┌──────────────┐
                         │   Qwen3.8    │
                         │ Reason / Plan│
                         └──────┬───────┘
                                │
                                ↓
┌──────────────────────────────────────────────────┐
│                    DIRECTOR                      │
│            决策 / 优先级 / 中断 / 调度              │
└──────────┬───────────┬───────────┬───────────────┘
           │           │           │
           ↓           ↓           ↓
       STATE       BEHAVIOR    INTERACTION
           │           │           │
           └───────────┼───────────┘
                       ↓
                 ACTION QUEUE
                       ↓
                 CHARACTER RUNTIME
                       │
             ┌─────────┴─────────┐
             ↓                   ↓
         ANIMATION            POSITION
             │                   │
             └─────────┬─────────┘
                       ↓
                    RENDERER
                       ↓
                    WINDOWS


              ┌─────────────────┐
              │     MEMORY      │
              └────────┬────────┘
                       ↑
                       │
                  EXPERIENCE


              ┌─────────────────┐
              │      AGENT      │
              │ Computer / File │
              └────────┬────────┘
                       ↑
                       │
                   DIRECTOR
```

---

# 14. 现在我给你一个最终的“不要再加功能”版本

我建议**产品层就到这里封顶**。

最终 8 个核心模块：

| # | 模块              | 一句话            |
| - | --------------- | -------------- |
| ① | **State**       | 她现在是什么状态       |
| ② | **Assets**      | 她有什么身体         |
| ③ | **Behavior**    | 她想做什么          |
| ④ | **Interaction** | 用户如何影响她        |
| ⑤ | **Agent**       | 她能替用户做什么       |
| ⑥ | **Memory**      | 她记得什么          |
| ⑦ | **Runtime**     | 她如何存在于 Windows |
| ⑧ | **Director**    | **谁现在拥有行动控制权** |

其中：

> **⑧不是第八个“功能”，而是前七个系统的调度中枢。**

所以我不会再给你加什么：

* 社交系统
* 成就系统
* 商店
* 换装
* 虚拟货币
* 好感度 UI
* 小游戏中心
* 云同步
* 社区

这些现在全部**不要碰**。

它们只会把项目做散。

---

# 最后，给 Qwen3.8 的开发原则

你马上要把这个东西交给 Qwen3.8 写，我反而最建议你把下面这段**直接作为项目最高级开发约束**。

> ### Furina Desktop Companion — Core Engineering Rules
>
> 1. **Event-driven architecture first.**
> 2. All major systems communicate through explicit events/interfaces, not direct cross-module calls.
> 3. **Director is the only module allowed to resolve competing actions.**
> 4. State, Behavior, Interaction, Agent, Memory and Runtime must remain logically separated.
> 5. LLM output must always be structured and schema-constrained; never parse free-form natural language to control the application.
> 6. Qwen3.8 is used only for high-value reasoning, dialogue, planning and reflection. Never use the LLM for high-frequency rendering, animation, input detection or simple state updates.
> 7. All basic behaviors must continue when the LLM is unavailable.
> 8. Agent actions must follow Observe → Plan → Act → Verify → Reflect.
> 9. Never claim an Agent task succeeded unless the result has been independently verified.
> 10. Never allow autonomous behavior to bypass user permission boundaries.
> 11. Character animation is a presentation layer, not the source of behavior.
> 12. Every visual action must be driven by semantic state/action data rather than hard-coded UI events.
> 13. Memory must be separated into explicit facts, observations, episodic experiences, semantic knowledge and relationship state.
> 14. Inferences must never silently become facts.
> 15. The system must remain debuggable: every important event, state transition, action decision and Agent operation should be traceable.
> 16. Prefer simple explicit code over excessive abstraction, inheritance, magic dispatch or autonomous self-modifying behavior.
> 17. Build the smallest working vertical slice first, then expand.
> 18. Do not introduce new product subsystems unless they are required by the existing architecture.

---

## 而你的第一版 MVP，我建议反而砍到极小

**不要一上来就实现我们上面说的全部东西。**

第一阶段只实现：

```text
芙宁娜
│
├── 基础待机
├── 呼吸 / 眨眼
├── 走路
├── 坐下
├── 睡觉
├── 摸头
├── 拖拽
├── 对话
├── 简单记忆
├── 当前窗口感知
└── 一个真实 Agent 任务
```

然后验证一个最关键的体验：

> **“我打开电脑，芙宁娜在桌面上自己生活；我工作的时候她会观察；我叫她帮忙时，她真的能走过来并操作电脑；第二天她还记得昨天发生过什么。”**

如果这一条跑通，**这个项目就已经成立了。**

剩下的全部都是扩展，而不是重新发明产品。
