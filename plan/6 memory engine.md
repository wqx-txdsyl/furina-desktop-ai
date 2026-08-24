好。第⑥条其实是整个产品里**最容易做成“普通 AI”的地方，也最值得做深**。

如果前五条已经让芙宁娜：

> 有身体 → 会行动 → 能互动 → 能使用电脑

那么第六条要让她真正拥有：

> **“我和你一起生活过。”**

所以这次我不建议把它简单叫“Memory / RAG”。

# ⑥ 记忆系统 Memory Engine

---

# 1. 核心定义

记忆系统不是：

> 把聊天记录存进数据库，然后下次检索出来。

真正的定义应该是：

> **记录芙宁娜经历过的事件、对用户形成的认识、两人形成的关系，以及这些经历如何改变她未来的行为。**

因此：

```text
Memory
≠
Chat History
```

而是：

```text
Experience
↓
Interpretation
↓
Memory
↓
Belief / Preference / Relationship
↓
Future Behavior
```

---

# 2. 为什么普通聊天记忆不够

例如用户今天说：

> “我最近在做一个机器人项目。”

普通 AI 会记：

```text
User is working on a robotics project.
```

但芙宁娜真正应该形成的是：

```text
Event:
用户最近投入大量时间做机器人项目

Observation:
用户经常晚上编程

Reaction:
芙宁娜主动陪伴

Outcome:
用户接受了她的陪伴

Relationship:
共同活动增加

Future:
用户工作时可以适当陪伴，但不要频繁打扰
```

这才叫：

> **生活记忆。**

---

# 3. 四层记忆结构

我建议最终至少四层。

```text
┌─────────────────────────┐
│     Identity Memory     │
│     “你是谁 / 我是谁”     │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│   Semantic Memory       │
│     “我知道什么”          │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│   Episodic Memory       │
│     “我们经历过什么”       │
└────────────┬────────────┘
             ↓
┌─────────────────────────┐
│   Relationship Memory   │
│     “我们变成了什么关系”    │
└─────────────────────────┘
```

这四层不能混。

---

# 4. Identity Memory

这是最稳定的一层。

记录：

### 用户

例如：

```text
name
preferred_name
timezone
usual_work_hours
favorite_apps
work_style
communication_style
```

但必须区分：

> **用户明确告诉她的。**

和：

> **系统推测出来的。**

例如：

```text
explicit:
“我不喜欢晚上被打扰。”

inferred:
用户晚上工作时很少回应
→ 可能不喜欢打扰
```

两者可信度完全不同。

---

# 5. 用户画像不能完全由 AI 自己决定

不能让 Qwen 说：

> “用户是一个孤独的人。”

然后数据库：

```text
user_personality = lonely
```

这会非常危险，也容易产生错误人格判断。

应该保存：

```text
observation
+
confidence
+
source
```

例如：

```text
Observation:
用户经常在深夜工作

Source:
behavior

Confidence:
0.72
```

而不是：

```text
Fact:
用户喜欢熬夜
```

---

# 6. Semantic Memory

这是：

> **芙宁娜长期“知道”的事情。**

例如：

```text
用户正在做某个项目
用户使用 VS Code
用户喜欢某种工作方式
某个文件夹是重要项目
用户正在准备某个比赛
```

这类信息不需要记住完整事件。

它是：

> **压缩后的知识。**

---

# 7. Episodic Memory

这是最重要的一层。

它记录：

> **发生过什么。**

例如：

```text
2026-08-23 20:14

Event:
用户第一次让芙宁娜整理 Downloads。

Context:
用户正在整理电脑。

Action:
芙宁娜执行文件分类。

Outcome:
任务成功。

User reaction:
满意。

Emotion:
芙宁娜感到有成就感。
```

这就是一段真正的：

> **经历。**

---

# 8. 不是什么都值得记

这是记忆系统的核心。

如果什么都存：

```text
用户点击了 1432 次鼠标
用户移动鼠标 8321 次
用户打开 Chrome 27 次
```

最终：

> 记忆库变成垃圾场。

所以需要：

# Memory Formation

系统判断：

> **这一事件有没有资格成为记忆？**

---

# 9. 记忆形成评分

可以定义：

```text
memory_score =
importance
+
novelty
+
emotional_intensity
+
relationship_impact
+
future_relevance
+
repetition
```

例如：

### 用户摸头一次

```text
importance = 1
```

不保存长期记忆。

---

### 用户每天睡前摸头

```text
repetition = high
future_relevance = high
```

形成：

> “睡前摸头是我们的习惯。”

---

### 用户第一次让她完成重要工作

```text
importance = high
relationship_impact = high
```

形成长期记忆。

---

# 10. 记忆不是永久的

必须有：

```text
memory_strength
```

以及：

```text
last_recalled
last_reinforced
```

某个很久不用的记忆：

> 强度逐渐下降。

但如果再次发生：

> 强度恢复。

这就是：

> **遗忘 + 强化。**

---

# 11. 但是重要记忆不能简单衰减

例如：

> 用户告诉她自己的名字。

不能因为三个月没提：

> “我忘了你叫什么。”

所以需要：

```text
importance
```

作为保护因子。

可以分成：

```text
core
important
normal
ephemeral
```

---

# 12. 记忆生命周期

一个事件：

```text
Raw Event
↓
Candidate Memory
↓
Consolidation
↓
Long-term Memory
↓
Reinforcement / Decay
↓
Archive
```

也就是说：

> **短期经历不一定立即成为长期记忆。**

类似人类：

> 今天发生的事情 → 晚上回忆 → 留下重要部分。

---

# 13. Memory Consolidation

可以设置一个：

> **“夜间回顾”机制。**

每天结束时，芙宁娜对当天经历进行总结：

```text
Today
↓
Events
↓
Important events
↓
Repeated patterns
↓
New user preferences
↓
Relationship changes
↓
Memories
```

例如：

> 今天用户工作了 5 小时。

不是记：

```text
用户工作 5 小时
```

而是：

> “最近用户似乎正在集中精力处理这个项目。”

---

# 14. 但“回顾”不能凭空创造事实

这是硬规则。

总结只能来自：

```text
Observed Events
+
User Statements
+
Confirmed Results
```

不能：

> 根据几次行为脑补完整人格。

所以每条记忆都应该有：

```text
source
```

---

# 15. Source 类型

至少：

```text
user_explicit
conversation
interaction
behavior
computer_observation
agent_task
system
inference
```

例如：

```text
用户说：
“我喜欢深夜工作。”

source = user_explicit
confidence = 1.0
```

而：

```text
系统发现：
用户连续一周 23:00 还在工作。

source = behavior
confidence = 0.74
```

---

# 16. Memory 与 Behavior Engine 的关系

这是第六条最重要的连接。

记忆不是：

> “以后聊天的时候引用一下。”

而应该：

> **改变行为决策。**

例如：

记忆：

```text
用户工作时不喜欢被频繁打扰
```

那么第三条：

```text
talk_to_user utility ↓
quietly_accompany utility ↑
```

---

# 17. 记忆影响人格，但不能修改核心人格

例如：

用户经常夸她：

> “你今天做得很好。”

可能：

```text
confidence ↑
comfort ↑
relationship ↑
```

但是不能：

> 芙宁娜永久变成另一个人格。

所以分：

```text
Core Persona
```

和：

```text
Learned Tendencies
```

核心人格稳定。

行为倾向动态变化。

---

# 18. Relationship Memory

这一层非常重要。

不要只用：

> 好感度 87。

而是维护关系维度：

```text
familiarity
trust
comfort
attachment
respect
dependency
annoyance
```

例如：

用户经常：

> 尊重她的拒绝。

那么：

```text
trust ↑
respect ↑
comfort ↑
```

用户经常：

> 打断她正在做的事情。

可能：

```text
annoyance ↑
```

---

# 19. Relationship 是动态的

关系应该像：

```text
陌生
↓
熟悉
↓
习惯
↓
亲近
↓
长期陪伴
```

但可以反向变化。

例如长期不互动：

```text
familiarity
可能缓慢下降
```

又重新互动：

> 恢复。

这比一个：

> `affection = 92`

真实得多。

---

# 20. 关系应该影响她的行为边界

例如熟悉程度高：

她可能：

> 更主动找你。

信任高：

> 更愿意接受你的请求。

尊重高：

> 更愿意帮助你。

但：

> **关系高 ≠ 无条件服从。**

这一点必须保留。

---

# 21. 记忆检索不能只做向量搜索

普通 RAG：

```text
query
↓
embedding
↓
top-k
```

对于桌宠不够。

因为她需要回答：

> “我为什么现在想起这件事情？”

所以检索应该混合：

```text
semantic similarity
+
recency
+
importance
+
emotional relevance
+
relationship relevance
+
context
```

---

# 22. 例如用户说：

> “你还记得那个项目吗？”

普通向量检索：

> 找关键词相似。

我们的系统应该：

```text
项目名称
+
相关事件
+
用户当时的情绪
+
过去任务
+
最近一次提及
```

然后形成：

> “当然。你之前让我帮你整理过它的文件，当时……”

这才像：

> **她真的记得。**

---

# 23. 记忆应该有“上下文”

一条记忆至少应该包含：

```text
memory_id
type
content
timestamp
source
importance
confidence
emotional_weight
relationship_weight
embedding
```

事件记忆再加：

```text
context
action
outcome
participants
```

---

# 24. 记忆不能只存文本

建议：

> **结构化数据库 + 向量数据库双层。**

结构化数据库：

负责：

```text
时间
类型
强度
关系
来源
状态
```

向量库：

负责：

> 语义检索。

---

# 25. 为什么不能全部丢进 Chroma

因为你会需要查询：

> “最近一个月用户让我做过哪些 Agent 任务？”

这不是向量检索最擅长的。

应该：

```text
SQL:
时间 / 类型 / 用户 / 关系
```

然后：

```text
Vector:
语义相似
```

最后融合。

---

# 26. 记忆检索流程

```text
Current Context
      ↓
What do I need to remember?
      ↓
Generate retrieval signals
      ↓
SQL filtering
      +
Vector search
      +
Recency
      +
Importance
      ↓
Memory ranking
      ↓
Relevant memories
      ↓
Qwen3.8
```

---

# 27. 记忆排名

例如：

```text
memory_score =
0.30 semantic
+
0.20 relevance
+
0.15 recency
+
0.15 importance
+
0.10 relationship
+
0.10 emotional
```

第一版可以这么做。

后续再通过实际数据调整。

---

# 28. 记忆应该主动影响行为

这是非常重要的：

不是只有：

> 用户说话 → 检索记忆。

还应该：

> **行为决策 → 检索相关记忆。**

例如：

芙宁娜准备：

> 邀请用户玩游戏。

Behavior Engine：

```text
为什么想玩？
```

Memory Engine：

> 用户过去三次工作时拒绝过。

于是：

```text
play_invitation score ↓
```

她可能改成：

> 安静陪伴。

---

# 29. 记忆应该能够触发行为

反过来也成立。

例如记忆：

> 用户今天晚上有重要会议。

时间到了。

Memory：

```text
event approaching
```

↓

Behavior：

> 主动提醒。

所以：

```text
Memory
↔
Behavior
```

是双向关系。

---

# 30. Agent 任务也应该进入记忆

例如：

> 芙宁娜第一次成功帮用户整理 PPT。

记录：

```text
agent_task
goal
result
user_feedback
```

之后用户再次说：

> “帮我处理 PPT。”

她已经知道：

> 自己以前做过类似任务。

于是：

> 更快制定计划。

这就是：

> **能力经验记忆。**

---

# 31. 甚至可以形成“技能记忆”

例如：

```text
Task:
整理 Downloads

第一次：
失败率较高

第二次：
成功

第三次：
成功

```

系统可以形成：

> “这种任务我已经比较熟悉。”

于是未来：

```text
planning_confidence ↑
```

但这里要注意：

> **经验 ≠ 权限。**

熟练了也不能跳过安全确认。

---

# 32. 用户可以查看她记得什么

这是产品上非常重要的透明度设计。

应该有：

> **Memory / Memories**

页面。

用户能看到：

```text
芙宁娜记得：

• 你最近在做某个项目
• 你习惯使用 VS Code
• 你工作时不喜欢频繁被打扰
• 你曾经让我整理过下载文件
• 我们第一次一起完成了……
```

并允许：

* 删除
* 修改
* 禁止记忆
* 标记错误

---

# 33. 用户应该能够纠正记忆

例如：

> “我已经不做这个项目了。”

系统：

```text
old memory
↓
superseded
```

不要直接删除历史。

因为：

> 她确实记得你曾经做过。

只是：

> 现在已经不是当前事实。

所以记忆需要：

```text
active
superseded
archived
```

---

# 34. 时间变化非常重要

例如：

2026：

> 用户在做 A 项目。

2027：

> 用户已经转向 B 项目。

不能出现：

> 芙宁娜永远认为用户在做 A。

所以语义记忆必须有：

```text
valid_from
valid_to
```

这也是为什么我不建议单纯做：

> “用户画像 JSON”。

---

# 35. 记忆冲突

如果：

> 用户以前说喜欢 A。

后来：

> “我现在不喜欢 A 了。”

应该：

```text
old:
likes A
valid_to = now

new:
dislikes A
valid_from = now
```

而不是：

> 两条互相矛盾的记忆同时有效。

---

# 36. “她记错了”也应该成为一种可处理状态

如果用户说：

> “我没说过这个。”

系统应该：

```text
memory confidence ↓
```

而不是：

> 强行坚持。

可以回复：

> “那是我记错了，抱歉。”

然后更新记忆来源与可信度。

这会极大增强真实感。

---

# 37. 隐私分层

由于她会观察电脑，所以记忆系统必须从第一天就设计隐私边界。

建议：

### Private

默认不进入长期记忆：

* 密码
* 支付信息
* 私人敏感内容
* 无关网页内容

### Contextual

只在当前任务使用。

### Memory

明确有长期价值的信息。

### Explicit Memory

用户明确说：

> “记住这个。”

最高优先级。

---

# 38. “观察”不等于“记住”

这句话我建议直接写进 PRD。

例如：

芙宁娜知道：

> 用户正在打开某个网页。

不代表：

> 她要永久记住用户访问过这个网页。

所以：

```text
Perception
≠
Memory
```

同样：

```text
Conversation
≠
Memory
```

```text
Observation
≠
Fact
```

---

# 39. 最终记忆形成机制

完整流程：

```text
Event
 ↓
Perception
 ↓
Is this meaningful?
 ↓
 ├── No → discard / short-term
 │
 └── Yes
       ↓
Interpret
       ↓
Extract
       ↓
Classify
       ↓
Score
       ↓
Consolidate
       ↓
Long-term Memory
       ↓
Influence Future Behavior
```

---

# 40. 一天结束时

可以形成一个非常有意思的机制：

## “今日回忆”

不是机械：

> 今日总结：用户工作了 6 小时。

而是芙宁娜自己的视角：

> 今天主人一直在忙那个项目。
> 我下午陪他待了一会儿。
> 后来他让我帮忙整理了文件。
> ……嗯，今天还算顺利。

这段总结可以：

> 进入 Episodic Memory。

以后用户问：

> “昨天我们干嘛了？”

她就真的有东西可以回忆。

---

# 41. 甚至可以形成“记忆节点”

长期运行后：

```text
              用户
               │
       ┌───────┼────────┐
       ↓       ↓        ↓
     项目A    工作习惯   游戏
       │       │        │
    ┌──┴──┐    │      ┌─┴─┐
    ↓     ↓    ↓      ↓   ↓
  PPT    VSCode 深夜工作  第一次
    │                  玩耍
    ↓
 芙宁娜帮助完成
```

于是记忆不再只是：

> 一堆文本。

而逐渐形成：

> **共同生活的事件网络。**

---

# 42. 最终架构

```text
                    EXPERIENCE
                         ↓
                  Event Collector
                         ↓
                ┌────────┴────────┐
                ↓                 ↓
          Short-term          Importance
            Memory              Filter
                │                 │
                └────────┬────────┘
                         ↓
                  Memory Formation
                         ↓
              ┌──────────┼──────────┐
              ↓          ↓          ↓
          Episodic   Semantic   Relationship
          Memory     Memory       Memory
              │          │          │
              └──────────┼──────────┘
                         ↓
                  Memory Retrieval
                         ↓
                      Qwen3.8
                         ↓
              Behavior / Agent
                         ↓
                     Experience
```

这形成一个真正的闭环：

> **经历 → 记忆 → 改变 → 再经历。**

---

# 43. 第六条十条硬规则

**① 记忆不是聊天记录。**

**② 观察不等于记忆。**

**③ 用户明确告诉她的事实，与 AI 推测必须分开。**

**④ 每条重要记忆必须拥有来源、时间、重要性和可信度。**

**⑤ 短期事件经过筛选和巩固后才进入长期记忆。**

**⑥ 记忆必须允许强化、衰减、过时和被纠正。**

**⑦ 时间变化必须被建模，同一个事实不能永远有效。**

**⑧ 记忆必须真正影响 Behavior，而不能只是聊天时拿出来引用。**

**⑨ Agent 的工作经历、互动经历和生活经历都可以成为记忆。**

**⑩ 用户拥有查看、纠正、删除和限制记忆的最终权力。**

---

# 44. 到这里，六条终于形成一个完整生命循环

现在已经不是六个孤立模块：

```text
① State
     ↓
“我现在是什么状态”

② Assets
     ↓
“我身体怎么表现”

③ Behavior
     ↓
“我现在想做什么”

④ Interaction
     ↓
“你刚才对我做了什么”

⑤ Agent
     ↓
“我能替你做什么”

⑥ Memory
     ↓
“我记得我们经历过什么”
     ↓
回到 ①
```

最终形成：

```text
                  ┌──────────────┐
                  │    MEMORY    │
                  └──────┬───────┘
                         ↓
                  ┌──────────────┐
                  │    STATE     │
                  └──────┬───────┘
                         ↓
                  ┌──────────────┐
                  │   BEHAVIOR   │
                  └──────┬───────┘
                         ↓
              ┌──────────┴──────────┐
              ↓                     ↓
        INTERACTION              AGENT
              ↓                     ↓
              └──────────┬──────────┘
                         ↓
                      EXPERIENCE
                         ↓
                       MEMORY
```

**这时候芙宁娜才真正拥有了“过去”。**

而有了过去，前面的状态、行为、互动、Agent 才不再是每次启动都重新开始的脚本。

---

接下来第⑦条，我建议**不要再继续堆 AI 功能**，而是把整个东西真正落到 Windows Runtime：**透明窗口、桌面坐标系、渲染层、素材切换、多帧播放、点击穿透、窗口检测、FPS、资源缓存、任务栏、开机启动、休眠唤醒，以及这些系统如何和前六层连接。**

因为到第六条为止，我们已经把“**她是谁、怎么动、为什么动、如何与你互动、如何操作电脑、如何记住你们的生活**”基本定完了。

第七条就是：

> **“这一切究竟怎样真的住进 Windows 桌面。”**
