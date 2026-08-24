好，现在我拿到完整的上一轮记录了。你刚才说的“第一个设计”就是：

> **① 角色状态树：到底有哪些状态、状态如何转移。** 

而且这里有一个非常重要的前提：**我们不是要设计一棵“动画状态树”，而是要设计芙宁娜这个数字生命的内部状态系统。**

上一版里 `energy / mood / hunger / fatigue / boredom...` 只是生命变量，还远远不能叫“状态树”。我建议这次把它真正拆开。

---

# ① 芙宁娜状态树 V1

我建议采用：

**「基础生命状态 + 当前情绪 + 当前活动 + 注意状态 + 行为意图」五维状态模型**

而不是一棵简单的：

`开心 → 生气 → 难过 → 睡觉`

因为那样最终一定会退化成动画播放器。

---

## 一、先确定最顶层：她到底处于什么“生活阶段”

最顶层我建议只有 **7 个宏观状态**：

```text
FURINA
│
├── 1. IDLE       待机 / 自在生活
│
├── 2. ENGAGED    正在与用户互动
│
├── 3. LIVING     自主生活
│
├── 4. WORKING    参与工作 / Agent任务
│
├── 5. RESTING    休息 / 放松
│
├── 6. SLEEPING   睡眠
│
└── 7. SPECIAL    特殊事件
```

这里有个关键点：

### **“情绪”不要放进这棵树。**

例如：

> 开心、骄傲、委屈、生气、困倦

都不是顶层状态。

因为：

> **“开心”不是她在做什么。**

她完全可以：

> 开心 + 工作
> 开心 + 喝茶
> 开心 + 睡觉
> 开心 + 看着用户

所以：

**状态 ≠ 情绪。**

---

# 二、七个状态分别是什么

### 1. IDLE｜待机

不是“什么都不做”。

而是：

> **没有更高优先级意图时，自主生活的默认状态。**

里面可以发生：

```text
IDLE
├── standing
├── sitting
├── looking_user
├── looking_screen
├── wandering
├── thinking
├── observing
├── micro_action
└── doing_nothing
```

甚至：

> 她坐在那里发呆。

这本身就是一种状态。

---

# 三、ENGAGED｜互动

只要她和用户发生直接交互，就进入这个层。

```text
ENGAGED
├── greeting
├── talking
├── listening
├── reacting
├── being_touched
├── being_dragged
├── playing
├── eating_with_user
└── saying_goodbye
```

但这里千万不要设计成：

> 用户点击 → ENGAGED → 播放 talking.gif → IDLE

而是：

```text
用户行为
   ↓
Interaction Event
   ↓
当前状态 + 情绪 + 关系
   ↓
Reaction Decision
   ↓
ENGAGED
   ↓
新的行为意图
```

所以同样是摸头：

第一次：

> 抬头。

熟悉以后：

> 闭眼享受。

心情不好：

> 躲开。

正在工作：

> “别闹，本神正忙着呢。”

这才是真正的状态系统。

---

# 四、LIVING｜自主生活

这是我认为上一版最需要强化的一块。

她不是一直等着用户。

```text
LIVING
├── eating
├── drinking
├── reading
├── playing_alone
├── organizing
├── exploring
├── looking_out
├── preparing
└── personal_activity
```

例如：

你十分钟没有理她。

她不是：

> IDLE.png

而可能：

```text
LIVING
↓
boredom ↑
↓
curiosity ↑
↓
intent = explore
↓
走到屏幕另一侧
↓
观察窗口
```

甚至：

> 自己拿一本书看。

这才是“桌面里住着一个人”。

---

# 五、WORKING｜工作

这个状态要和 Agent 深度结合。

```text
WORKING
├── observing_user_work
├── waiting_for_task
├── planning
├── executing
├── verifying
├── waiting
├── assisting
└── reporting
```

注意：

### `observing_user_work`

不等于：

> 她正在替你工作。

例如你打开 VS Code：

```text
IDLE
↓
observe_user
↓
发现 VS Code
↓
识别用户正在编程
↓
interest / curiosity
↓
靠近
↓
observing_user_work
```

她可以只是坐在那里看。

而当你说：

> “帮我看看这个。”

才：

```text
observing_user_work
↓
ENGAGED
↓
intent = help
↓
WORKING
↓
planning
↓
executing
```

这个区别非常重要。

---

# 六、RESTING｜休息

和 `SLEEPING` 分开。

```text
RESTING
├── sitting_relaxed
├── lying
├── drinking_tea
├── reading
├── daydreaming
├── relaxing
└── recovering
```

例如：

> 疲劳 60

不意味着：

> 自动睡觉。

可能只是：

> 她走到桌边坐下来喝茶。

而：

> fatigue 很高 + sleepiness 很高 + 时间合适

才逐渐：

```text
RESTING
↓
sleepy
↓
SLEEPING
```

---

# 七、SLEEPING｜睡眠

这里可以做得非常有生命感。

```text
SLEEPING
├── falling_asleep
├── asleep
├── light_sleep
├── deep_sleep
└── waking
```

睡觉的时候甚至不应该完全静止：

```text
asleep
├── breathing
├── turning
├── tiny_movement
└── dream_reaction
```

这样即使用户什么都不做，她也仍然在“活着”。

---

# 八、SPECIAL｜特殊事件

这个状态不是日常状态。

用于：

```text
SPECIAL
├── celebration
├── surprise
├── emergency
├── birthday
├── achievement
├── special_interaction
└── story_event
```

例如用户完成一个大项目。

芙宁娜可能突然：

> 庆祝。

这时候 `SPECIAL` 的优先级高于普通生活状态。

---

# 九、但是：真正重要的是“状态树”下面还要有第二棵树

这才是整个设计的核心。

我建议把：

> **“她现在是什么状态”**

和：

> **“她现在是什么心情”**

彻底分离。

---

## 情绪树

```text
EMOTION
│
├── positive
│   ├── happy
│   ├── excited
│   ├── satisfied
│   ├── proud
│   └── playful
│
├── neutral
│   ├── calm
│   ├── curious
│   ├── focused
│   └── thoughtful
│
└── negative
    ├── annoyed
    ├── sad
    ├── embarrassed
    ├── lonely
    └── anxious
```

而且这里也不能是简单枚举。

我更倾向：

```text
mood = 72
arousal = 45
social_need = 30
```

然后由系统解释成：

> 当前表现偏开心 / 平静。

也就是说：

**情绪本身是连续变量，表现才是离散状态。**

---

# 十、第三层：Needs

这层就是上一版的：

> hunger / fatigue / boredom / social_need...

我建议正式叫：

# NEEDS

```text
NEEDS
│
├── energy
├── hunger
├── fatigue
├── sleepiness
├── boredom
├── social_need
├── curiosity
├── playfulness
├── work_interest
└── satisfaction
```

这些不是“状态”。

而是：

> **推动她产生行为的内部动力。**

例如：

```text
boredom = 82
```

不会直接：

> 播放 play.gif

而是：

```text
boredom ↑
      ↓
Evaluate Needs
      ↓
产生 Explore / Play 倾向
      ↓
Intent
```

这正好符合上一轮确定的：

> Observe → Update State → Evaluate Needs → Generate Intent → Evaluate Priority → Choose Behavior。 

---

# 十一、第四层：Attention

这一层我认为必须加入。

因为她作为桌面角色，最重要的问题之一是：

> **她现在注意谁？**

```text
ATTENTION
│
├── USER
├── ACTIVE_WINDOW
├── SPECIFIC_WINDOW
├── OBJECT
├── SELF
└── NONE
```

例如：

你打开 VS Code。

她：

```text
attention = ACTIVE_WINDOW
```

你开始说话：

```text
attention = USER
```

你把蛋糕拖到她面前：

```text
attention = OBJECT
```

她自己喝茶：

```text
attention = SELF
```

这样“视线”就不再是动画属性，而是**认知状态**。

最后表现层才把：

> `attention = USER`

翻译成：

> 看向用户。

---

# 十二、第五层：Intent

最后才是：

# 她“想做什么”。

例如：

```text
INTENT
│
├── survive
│   ├── eat
│   ├── drink
│   └── sleep
│
├── interact
│   ├── greet
│   ├── talk
│   ├── play
│   └── seek_attention
│
├── self
│   ├── explore
│   ├── read
│   ├── relax
│   └── wander
│
├── user
│   ├── observe
│   ├── help
│   ├── remind
│   └── accompany
│
└── agent
    ├── understand
    ├── plan
    ├── execute
    └── report
```

这一步一旦成立，整个系统就完全不一样了。

---

# 十三、所以最终不是“一棵树”

而是一个：

# **Character State Model**

```text
                    FURINA
                       │
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
      LIFE           EMOTION         NEEDS
        │              │              │
   ┌────┴────┐      mood...      hunger...
   ↓         ↓
 ACTIVITY  REST...
        │
        ↓
    ATTENTION
        │
        ↓
      INTENT
        │
        ↓
    BEHAVIOR
        │
        ↓
    ANIMATION
```

这比传统桌宠的：

```text
开心 → GIF
生气 → GIF
睡觉 → GIF
```

高级很多。

---

# 十四、举一个完整例子

假设你正在写代码。

此时：

```text
Activity:
WORKING / observing_user_work

Emotion:
calm = 68
curiosity = 75

Needs:
social_need = 40
playfulness = 30

Attention:
ACTIVE_WINDOW

Intent:
observe
```

她坐在 VS Code 旁边。

然后你连续工作 90 分钟。

系统更新：

```text
fatigue ↑
user_work_duration ↑
```

于是：

```text
Intent candidates

continue_observing    0.30
seek_attention        0.15
remind_user_rest      0.78
help_user             0.22
play                  0.08
```

选择：

> `remind_user_rest`

于是行为规划：

```text
WORKING
↓
walk_to_user
↓
observe_user
↓
check_interruptibility
↓
speak
```

如果用户正在疯狂输入：

> 她不说话。

而是：

> 站在旁边看。

过了十几秒用户停下来：

> “你已经工作很久了哦。”

然后：

```text
Intent = accompany
```

她坐下来。

**这才是状态树真正应该驱动出来的东西。**

---

# 十五、还有一个我强烈建议加入的东西：状态优先级

否则以后一定会打架。

例如同时：

```text
hunger = 90
user_talk = true
sleepiness = 80
agent_task = true
```

到底干什么？

必须有优先级。

我建议初始：

```text
P0  Critical / Special
P1  User Direct Interaction
P2  Agent Task
P3  Physiological Need
P4  Relationship / Social Need
P5  Self Activity
P6  Ambient / Idle
```

但是这里有一个很重要的设计：

### **高优先级不代表立即打断。**

还要经过：

```text
priority
×
interruptibility
×
cooldown
×
current_context
```

否则她会非常烦。

---

# 十六、因此状态转移不是 if-else

最终应该是：

```text
                ┌──────────────┐
                │ World State  │
                └──────┬───────┘
                       ↓
                ┌──────────────┐
                │ Life State   │
                └──────┬───────┘
                       ↓
                ┌──────────────┐
                │ Needs / Mood │
                └──────┬───────┘
                       ↓
                ┌──────────────┐
                │   Intent     │
                └──────┬───────┘
                       ↓
                ┌──────────────┐
                │   Priority   │
                └──────┬───────┘
                       ↓
                ┌──────────────┐
                │   Behavior   │
                └──────┬───────┘
                       ↓
                ┌──────────────┐
                │    Body      │
                └──────────────┘
```

然后行为完成以后：

```text
Body
 ↓
Result
 ↓
World State
 ↓
Memory
 ↓
Needs / Mood 更新
```

形成闭环。

---

## 我现在认为，第一个设计可以先定成这个核心架构

**不是“一棵状态树”，而是五层状态模型：**

> **Life State → Emotion → Needs → Attention → Intent → Behavior → Body**

其中真正的“状态树”主要负责 **Life State**；

而 **Emotion / Needs / Attention / Intent** 是驱动状态变化的内部变量。

这样我们后面设计 **②素材规范** 时，就可以反过来从这个系统推导：

> 一个状态需要哪些视觉资产？

而不是拍脑袋列：

> “开心来 10 张、生气来 10 张、吃饭来 5 张……”

这两者会直接决定最终桌宠到底是**“有生命的角色”还是“素材库驱动的动画”**。
