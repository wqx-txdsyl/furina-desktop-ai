可以。**第三条我们就专门把「行为系统」定死。**

我先强调一个核心判断：前面第二条“素材规范”解决的是**她有什么身体能力**；第三条必须解决的是：

> **她为什么在这一刻做这个，而不是做另一个？**

如果这个没设计好，哪怕有 500 张图，最后依然会变成“随机播放动画”。

---

# ③ 行为系统 Behavior Engine

## 1. 核心定义

行为系统不是一个：

```text
事件 → 动画
```

映射表。

而是：

```text
环境
+
角色内部状态
+
用户状态
+
记忆
+
当前行为
+
长期目标
+
随机性
        ↓
    行为候选池
        ↓
    动机/优先级评估
        ↓
    行为决策
        ↓
    行为计划
        ↓
    动作执行
        ↓
    结果反馈
        ↓
    状态/记忆更新
```

也就是说：

> **动画只是行为的最后一层表现。**

---

# 2. 行为分成四级

我建议不要把所有行为放在一个池子里。

## Level 0：身体自主行为

完全不需要 LLM。

例如：

* 眨眼
* 呼吸
* 看向不同方向
* 轻微晃动
* 换坐姿
* 整理头发
* 打哈欠
* 发呆
* 小幅移动

这些行为由本地 Behavior Runtime 高频控制。

例如：

```text
每 2～8 秒
    ↓
检查当前状态
    ↓
选择一个微动作
```

这样即使 Qwen 完全不调用：

> **她仍然是活的。**

---

# 3. Level 1：自主生活行为

同样不应该每次调用 LLM。

例如：

* 喝水
* 吃东西
* 看书
* 休息
* 睡觉
* 在桌面走动
* 找地方坐
* 玩自己的东西
* 看用户
* 靠近用户
* 离开用户

由状态机 + Utility AI 决定。

例如：

```text
困倦 82
疲劳 71
当前没有任务
时间 23:40
```

系统产生：

```text
sleep
score = 94
```

于是：

> 她自己决定去睡觉。

而不是：

```text
if time > 23:
    sleep.gif
```

---

# 4. Level 2：社会行为

这里开始体现“人格”。

例如：

* 主动搭话
* 求关注
* 撒娇
* 抱怨
* 夸用户
* 提醒用户
* 邀请玩耍
* 对用户的行为产生反应
* 观察用户
* 跟随用户
* 因为用户长时间不理她而产生情绪

这一层不能单纯由需求决定。

例如：

```text
social_need = 80
```

并不意味着：

> “我要说话。”

还需要：

```text
social_need
+
relationship
+
current_mood
+
user_activity
+
recent_interaction
+
personality
+
interruptibility
```

共同决定。

---

# 5. Level 3：Agent 行为

这是最高级行为。

例如：

用户：

> “帮我整理一下桌面的文件。”

这不是普通行为，而是：

```text
user_request
↓
intent
↓
plan
↓
tool execution
```

同时芙宁娜的身体也应该表现这个过程：

```text
听到请求
↓
看向用户
↓
站起来
↓
走向屏幕
↓
开始工作
↓
等待 / 操作
↓
回来
↓
报告结果
```

所以：

> **Agent 行为和角色行为必须共享同一个 Behavior Engine。**

不能出现：

> 芙宁娜在桌面上喝茶，同时后台偷偷操作电脑。

---

# 6. 行为不是“命令”，而是“意图”

这是我认为这个项目最重要的设计之一。

不要让 LLM 输出：

```json
{
  "animation": "furina_walk_03"
}
```

甚至不要直接输出：

```json
{
  "action": "walk"
}
```

应该输出：

```json
{
  "intent": "approach_user",
  "reason": "用户长时间工作，我想看看他在做什么"
}
```

然后 Behavior Engine 再决定：

```text
approach_user
↓
找目标
↓
计算路径
↓
选择移动方式
↓
走过去
↓
停止距离
↓
选择姿态
↓
选择视线
↓
选择表情
```

最后才变成：

```text
walk animation
+
look_at_user
+
happy expression
```

---

# 7. 行为的基本数据结构

每一个行为都应该拥有自己的定义。

例如：

```text
Behavior: drink_tea

conditions:
    thirst > 50
    tea_available = true

utility:
    thirst × 0.6
    mood × 0.1
    boredom × 0.1

duration:
    20–60s

interruptible:
    true

cooldown:
    10min

effects:
    thirst ↓
    satisfaction ↑
    fatigue ↓
```

注意：

**行为不是动画。**

`drink_tea` 是行为。

动画只是它的一个可能实现：

```text
walk_to_tea
sit
pick_up_cup
drink
put_down_cup
idle
```

---

# 8. Utility AI 是最适合你的核心机制

我不建议第一版就搞复杂强化学习。

你的场景非常适合：

> **Utility AI + 状态机 + LLM**

每隔一段时间，对候选行为计算分数。

例如：

```text
sleep             86
drink_tea         42
play              31
talk_to_user      64
observe_user      72
walk              25
```

最高的：

> `sleep`

但还不能直接执行。

还要经过：

```text
Priority
+
Cooldown
+
Interruptibility
+
Context
```

最终：

> 睡觉。

---

# 9. 行为分数不能只有“需求”

这是防止她机械化的关键。

例如：

### 玩耍

```text
boredom
+ playfulness
+ energy
+ free_time
+ relationship
- fatigue
```

### 帮助用户

```text
user_need
+ helpfulness
+ work_interest
+ relationship
+ curiosity
```

### 主动聊天

```text
social_need
+ relationship
+ mood
+ recent_interaction
- user_focus
- interruption_cost
```

### 睡觉

```text
sleepiness
+ fatigue
+ time_of_day
- unfinished_intent
- social_need
```

于是她不会像闹钟一样。

---

# 10. 必须加入“打扰成本”

这是我非常建议加入的一个参数。

定义：

```text
interruption_cost
```

例如用户正在：

> 打字

那么：

```text
interruption_cost = 90
```

用户正在：

> 看视频

可能：

```text
interruption_cost = 30
```

用户：

> 已经 10 分钟没操作电脑

可能：

```text
interruption_cost = 5
```

所以：

### 她很想聊天

但用户正在疯狂写代码：

> 她可能只是走到旁边看着。

而不是：

> “主人主人主人！！！”

这会极大提升真实感。

---

# 11. “想做”和“会做”必须分开

例如：

```text
social_need = 90
```

代表：

> 她很想和用户互动。

但：

```text
user_busy = true
```

于是最终：

```text
intent = observe_user
```

而不是：

```text
intent = talk
```

这就是人格的体现。

---

# 12. 行为必须允许失败

这一点非常重要。

现实中的人不是：

> 有意图 → 必然成功。

例如：

```text
intent = approach_user
```

但是：

* 用户正在拖她
* 路径被窗口挡住
* 用户移动窗口
* 她改变主意
* 突然发现用户需要帮助
* Agent 任务开始

都可能：

```text
behavior interrupted
```

然后重新规划。

---

# 13. 行为必须允许“临时改变主意”

例如：

她原本准备：

> 去喝茶。

正在走。

突然：

> 用户打开了她很熟悉的游戏。

那么：

```text
observe_user
```

的 Utility 突然上升。

于是：

```text
walk_to_tea
      ↓
interrupt
      ↓
look_at_screen
      ↓
approach_user
```

这才像一个活人。

---

# 14. 行为树不应该太深

我反而不建议做一个巨大的：

```text
Behavior Tree
├── ...
│   ├── ...
│   │   ├── ...
```

最后整个系统变成游戏 AI。

你的角色行为更适合：

```text
World State
      ↓
Utility AI
      ↓
Intent
      ↓
Behavior State Machine
      ↓
Animation Controller
```

四层足够。

---

# 15. LLM 的真正位置

Qwen3.8 不应该每秒思考。

否则：

> 成本高、速度慢、行为反复、角色神经质。

应该存在两个时间尺度。

## Fast Loop

例如：

```text
10–30 Hz
```

负责：

* 动画
* 位置
* 碰撞
* 鼠标
* 微动作

---

## Life Loop

例如：

```text
每几秒
```

负责：

* 状态更新
* Utility
* 行为选择

---

## Thought Loop

只有必要的时候：

```text
几十秒～几分钟
```

或者：

```text
重要事件
用户对话
复杂决策
Agent 任务
```

才调用 Qwen。

---

# 16. LLM 应该处理“模糊问题”

例如：

> “用户今天怎么一直没说话？”

这种问题 Utility AI 不适合。

Qwen 可以分析：

```text
用户行为
+
近期记忆
+
当前上下文
```

形成：

> “他可能正在专心做事情，我还是先别打扰。”

然后产生：

```text
intent = quietly_accompany
```

---

# 17. LLM 输出也必须受到 Runtime 限制

Qwen不能说：

> “我决定从桌面跳到浏览器里面。”

然后程序就真的执行。

LLM只能从：

```text
Allowed Intent List
```

里面选。

例如：

```text
observe_user
approach_user
talk
play
rest
eat
drink
sleep
help_user
start_agent_task
```

然后 Runtime 判断：

> 当前能不能做。

---

# 18. 行为优先级

我建议：

```text
P0 —— 生存 / Runtime
P1 —— 用户明确请求
P2 —— 重要提醒
P3 —— 角色需求
P4 —— 社交行为
P5 —— 自主生活
P6 —— 微动作
```

例如：

用户：

> “芙宁娜，帮我打开 PPT。”

即使她：

> 正在喝茶。

也应该中断。

但是：

> 用户正在打字时她想喝茶。

不能中断用户。

---

# 19. 行为状态机

一个完整行为应该经历：

```text
INTENT
  ↓
PREPARE
  ↓
MOVE
  ↓
ACT
  ↓
WAIT
  ↓
REACT
  ↓
COMPLETE
```

例如“给用户提醒”：

```text
intent
↓
approach_user
↓
walk
↓
stop
↓
look_at_user
↓
wait_for_attention
↓
talk
↓
observe_reaction
↓
complete
```

如果用户没有回应：

```text
wait
↓
timeout
↓
reduce_interruptiveness
↓
leave
```

**不要无限重复提醒。**

---

# 20. 行为冷却机制

所有主动行为都应该有：

```text
cooldown
```

比如：

```text
ask_to_play = 30min
remind_rest = 45min
complain = 20min
ask_attention = 15min
```

但更高级的是：

> **不是简单 cooldown，而是“近期行为抑制”。**

如果她刚刚已经主动说：

> “你休息一下吧。”

即使 20 分钟后 Utility 又很高，也要考虑：

```text
recent_similar_behavior = true
```

降低分数。

这样她不会机械重复。

---

# 21. 行为之间要有连续性

这是“活人感”的核心。

错误：

```text
喝茶
↓
随机
↓
跳舞
↓
随机
↓
睡觉
```

正确：

```text
喝茶
↓
喝完
↓
满足感上升
↓
坐着
↓
看到用户工作
↓
观察
↓
产生兴趣
↓
靠近
↓
聊天
```

所以：

> **行为结束时，要给下一个行为提供上下文。**

---

# 22. 行为链

允许：

```text
Behavior A
↓
Outcome
↓
Behavior B
↓
Outcome
↓
Behavior C
```

例如：

```text
用户长时间工作
↓
approach_user
↓
observe
↓
发现用户忙
↓
quietly_accompany
↓
用户停止输入
↓
talk
↓
用户说“有点累”
↓
suggest_rest
```

这已经非常接近“角色自主行为”。

---

# 23. 长期目标

芙宁娜还应该拥有少量自己的长期目标。

例如：

```text
今天：
    陪主人工作

近期：
    多了解主人的工作习惯

长期：
    成为更好的助手
```

这些目标不是任务清单。

它们只是：

> **影响行为 Utility 的潜在变量。**

例如：

```text
goal = understand_user
```

那么她更容易：

> 观察用户。

而不是每次都直接询问。

---

# 24. 最关键的一层：行为解释

系统内部必须保存：

```text
为什么做这个行为？
```

例如：

```text
chosen_behavior:
approach_user

reason:
用户持续工作 96 分钟，
当前注意力下降，
芙宁娜关系亲密度较高，
她产生陪伴意图，
但用户当前仍在输入，
因此选择低打扰接近。
```

这对于 Debug 极其重要。

以后你发现：

> “她怎么老往我旁边跑？”

可以直接看到：

```text
approach_user
score = 82

social_need = 74
relationship = 91
user_idle = 0.4
interruption_cost = 65
```

马上知道问题在哪。

---

# 25. 最终 Behavior Engine

我建议最终定成：

```text
                    ┌──────────────┐
                    │  World State │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ Internal     │
                    │ State        │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ Memory       │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ Candidate    │
                    │ Behaviors    │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ Utility      │
                    │ Evaluation   │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ Priority /   │
                    │ Interruption │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ Intent       │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ Behavior     │
                    │ StateMachine │
                    └──────┬───────┘
                           ↓
             ┌─────────────┴─────────────┐
             ↓                           ↓
      Character Body               Computer Agent
             ↓                           ↓
        Animation                    Tools
             └─────────────┬─────────────┘
                           ↓
                       Outcome
                           ↓
                  State / Memory Update
```

---

# 26. 我认为第三条必须定下来的“硬规则”

最后我建议把以下 10 条直接作为产品铁律：

**① LLM 不直接控制动画。**

**② 行为不是动画，动画只是行为的表现层。**

**③ 大多数日常行为由本地 Runtime 决定，不调用 LLM。**

**④ LLM 负责高层意图、复杂判断、语言和规划。**

**⑤ 行为必须考虑用户当前状态，而不是只考虑芙宁娜自己的需求。**

**⑥ 所有主动行为都有打扰成本、冷却和中断机制。**

**⑦ 行为可以失败，可以被打断，也可以临时改变主意。**

**⑧ 行为结束后必须产生结果，并影响后续行为。**

**⑨ 允许行为链，而不是一个行为执行完就回 Idle。**

**⑩ 系统永远能够解释“为什么此刻选择这个行为”。**

---

## 最后一个非常关键的判断

到这里，其实已经可以看出来：

**你的桌宠核心不是“动画系统”，甚至也不是“LLM”。**

真正的核心技术资产应该是：

> ### **Character Behavior Runtime**

以后换成：

* 芙宁娜
* 派蒙
* 自定义 OC
* 用户自己设计的角色

底层都不用重做。

只需要换：

```text
Persona
+
Asset Library
+
Behavior Preferences
+
Voice
```

而 Runtime 还是同一个。

这会让整个项目从“做一个芙宁娜桌宠”，直接升级成：

> **做一个能够承载任意 AI Character 的 Windows Character Runtime。**

而**下一条第④互动系统**，就应该在这个 Behavior Engine 之上解决一个完全不同的问题：

> **用户的鼠标、拖拽、摸头、喂食、点击、窗口接触，究竟怎样进入这个“生命系统”，而不是变成一堆 UI 按钮。**
