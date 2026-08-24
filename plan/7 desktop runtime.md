好，第⑦条是**最终落地层**。

前六条解决的是“芙宁娜作为一个数字生命应该是什么”，第七条解决：

> **这个数字生命究竟怎样真正存在于 Windows 桌面上。**

这里我建议我们把它直接定名为：

# ⑦ Desktop Runtime —— Windows 桌面运行时

---

# 1. 核心定义

不要把整个程序理解成：

> 一个显示 PNG 的窗口。

而应该理解成：

> **一个拥有自己空间、渲染、输入、时间和生命周期的角色运行环境。**

也就是：

```text
Windows
   │
   ↓
Desktop Runtime
   │
   ├── World
   ├── Renderer
   ├── Input
   ├── Position
   ├── Animation
   ├── Window Awareness
   ├── Scheduler
   ├── Resource Manager
   └── Character Runtime
              │
              ├── State
              ├── Behavior
              ├── Interaction
              ├── Agent
              └── Memory
```

---

# 2. 第一原则：芙宁娜不是“一个窗口”

这是整个 Runtime 最重要的设计原则。

普通桌宠：

```text
窗口
└── 图片
```

我们的系统：

```text
Desktop World
│
├── Furina Character
├── Hitboxes
├── Interaction Layer
├── Effects
├── Floating UI
└── Debug / System Layer
```

窗口只是：

> **承载这个世界的技术容器。**

---

# 3. 她必须真正存在于桌面坐标系

建立：

```text
Desktop Coordinate System
```

例如：

```text
(0,0)
┌──────────────────────────────────┐
│                                  │
│                    Furina        │
│                       ↓          │
│                     (x,y)        │
│                                  │
│                                  │
└──────────────────────────────────┘
```

角色拥有：

```text
x
y
width
height
scale
direction
z_index
```

所以她不是：

> “显示在窗口中央。”

而是：

> **她在桌面上的某个位置。**

---

# 4. 多显示器必须从第一版考虑

如果用户有：

```text
Monitor 1
Monitor 2
```

芙宁娜应该知道：

```text
Monitor A
└── x: 0 ~ 1920

Monitor B
└── x: 1920 ~ 3840
```

她甚至可以：

> 从一个屏幕走到另一个屏幕。

当然，第一版可以先限制：

> 单显示器完整支持。

但底层坐标系统不能写死。

---

# 5. 桌面是她的世界

建立几个空间概念：

```text
World
├── Desktop
├── Taskbar
├── WindowSurface
├── ScreenEdge
└── CharacterZone
```

角色可以有：

```text
surface = desktop
surface = window_edge
surface = taskbar
```

以后甚至可以扩展：

```text
surface = browser
surface = vscode
surface = custom_room
```

---

# 6. Window Awareness

这是第七条里非常重要的一项。

系统持续知道：

```text
当前活动窗口
窗口位置
窗口大小
窗口标题
应用程序
```

例如：

```text
active_window:
VS Code

rect:
x=420
y=120
width=1300
height=800
```

---

# 7. 芙宁娜可以“靠近窗口”

例如：

用户打开 VS Code。

系统发现：

```text
VS Code
x=420
y=120
```

Behavior Engine 决定：

> “去看看主人在干什么。”

Runtime：

```text
target.x = 400
target.y = 800
```

然后：

```text
walk
→
approach
→
stop
→
look_at_window
```

---

# 8. 不要真的让她覆盖应用窗口

建议默认：

> **芙宁娜视觉上可以靠近窗口，但不会遮挡用户的重要内容。**

她可以站：

* 窗口边缘
* 窗口顶部
* 屏幕边缘
* 桌面空白区域

如果用户明确允许：

> 才可以进入窗口覆盖区域。

这样不会从“桌宠”变成“屏幕污染”。

---

# 9. 窗口层级

建议至少：

```text
Background
↓
Normal Windows
↓
Furina
↓
Temporary Character UI
↓
System UI
```

但这里有个关键点：

> **不要无脑 Always On Top。**

否则她会盖住：

* 浏览器
* IDE
* 游戏
* PPT

用户会烦。

---

# 10. Z-Order 应该动态变化

例如：

### 普通状态

芙宁娜：

> 在桌面层。

### 用户互动

> 临时置顶。

### Agent 工作

> 可以暂时提高层级。

### 用户全屏游戏

> 自动隐藏 / 降级。

---

# 11. 全屏检测

例如用户：

> 打开游戏。

系统检测：

```text
fullscreen = true
```

芙宁娜可以：

> 自动退到后台。

或者：

> 缩小成角落小窗。

这是必须有的。

---

# 12. 透明窗口

核心视觉必须支持：

> **透明背景。**

最终用户看到：

```text
Windows Desktop
        +
    Furina PNG
```

而不是：

```text
┌──────────────────┐
│                  │
│      Furina      │
│                  │
└──────────────────┘
```

---

# 13. Alpha 渲染

素材本身：

```text
RGBA
```

Runtime：

```text
Alpha Compositing
```

这样：

* 角色透明区域不遮挡桌面
* 阴影可以半透明
* 特效可以透明
* 气泡可以透明

---

# 14. 点击穿透

这是非常关键的。

例如角色 PNG：

```text
┌─────────────┐
│ transparent │
│     ◎       │
│   Furina    │
│             │
└─────────────┘
```

用户点击透明区域：

> 应该点击到下面的 Windows。

用户点击角色：

> 芙宁娜收到输入。

因此需要：

```text
Pixel / Hitbox Interaction
```

---

# 15. 不要使用“整张图片都是点击区域”

否则：

> 用户明明点击桌面，却一直摸到芙宁娜。

应该定义：

```text
Hitbox
├── head
├── body
├── hand
├── food
└── interaction_zone
```

---

# 16. Hitbox 不一定等于图片轮廓

例如：

```text
head:
ellipse

body:
polygon

hand:
small region
```

这样可以实现：

> 真正的“摸头”。

---

# 17. 输入系统

Runtime 接收：

```text
Mouse
├── move
├── down
├── up
├── click
├── double_click
└── wheel

Keyboard
├── key_down
├── key_up
└── shortcut

System
├── window_change
├── screen_change
├── idle
├── resume
└── shutdown
```

统一转换为：

```text
Interaction Event
```

再交给第四条。

---

# 18. 不让 UI 直接决定角色反应

错误：

```text
if headClicked:
    play("happy")
```

正确：

```text
Input
↓
Interaction Event
↓
Character State
↓
Behavior Evaluation
↓
Reaction
↓
Animation
```

所以：

> Runtime 负责“发生了什么”。

> Interaction Engine 决定“这意味着什么”。

> Behavior Engine 决定“她怎么回应”。

---

# 19. 动画 Runtime

这是没有 Live2D 后最核心的技术模块。

需要：

```text
Animation Controller
```

负责：

```text
Idle
Walk
Sit
Sleep
Talk
Eat
Drink
Play
...
```

---

# 20. 动画不是“播放 GIF”

我强烈建议：

> **不要把核心动画系统设计成 GIF 播放器。**

而是：

```text
Animation
├── frames
├── fps
├── loop
├── blend
├── interruptible
├── priority
└── tags
```

例如：

```text
walk_right:
frames = [001...008]
fps = 12
loop = true
interruptible = true
```

---

# 21. 动画状态机

例如：

```text
IDLE
 │
 ├── user_touch → REACT
 │
 ├── walk_target → WALK
 │
 ├── tired → SIT
 │
 ├── sleepy → SLEEP
 │
 └── talk → TALK
```

但这里要注意：

> **动画状态机不是 Behavior Engine。**

Behavior：

> “我要去用户旁边。”

Animation：

> “那我现在播放走路。”

---

# 22. 动画优先级

例如：

```text
sleep = 10
special_event = 9
interaction = 8
talk = 7
action = 5
idle = 1
```

如果正在：

> Idle

用户摸头：

> Interaction 覆盖 Idle。

如果正在：

> Walking

突然睡觉：

> Behavior 终止 Walking。

---

# 23. 动画中断

必须支持。

例如：

```text
walking
```

用户：

> 摸头。

不能：

> “请等待走路动画播放完。”

应该：

```text
walk
 ↓
interrupt
 ↓
touch_reaction
```

完成后：

> 是否继续走？

由 Behavior Engine 决定。

---

# 24. 动画过渡

由于你使用大量独立状态图，最大的问题是：

> **切图会很生硬。**

所以需要最基础的 Transition：

```text
standing
↓
sit_down
↓
sitting
```

而不是：

```text
standing.png
→
sitting.png
```

中间加：

> sit_down 多帧。

---

# 25. 微动作系统

这是第七条最值得强调的。

即使她没有任何事情做：

> 她也不能完全静止。

Idle Layer 可以叠加：

```text
Base Pose
+
Breathing
+
Blink
+
Hair Motion
+
Small Sway
```

例如：

```text
Base:
sitting

Overlay:
breathing

Random:
blink

Occasional:
look_left
```

最终：

> 看起来像一个活着的人。

---

# 26. 随机不能是真随机

否则：

> 角色会莫名其妙一直眨眼。

应该使用：

```text
Behavior Probability
+
Cooldown
+
State
+
Context
```

例如：

```text
blink:
cooldown = 2~8s
probability = context dependent
```

---

# 27. 微动作必须服从状态

例如：

### 开心

```text
blink ↑
small_sway ↑
```

### 困倦

```text
blink slow
movement ↓
```

### 紧张

```text
movement slightly ↑
gaze shifts
```

所以：

> 微动作也应该受到 State Engine 控制。

---

# 28. FPS

推荐：

### Runtime

60 FPS。

### 动画

根据素材：

* 8 FPS
* 12 FPS
* 15 FPS
* 24 FPS

并不需要所有素材都 60 FPS。

60 FPS 是：

> **渲染刷新率。**

不是：

> 图片动画帧率。

---

# 29. 资源管理

如果一次加载几百张 PNG：

> 内存很容易膨胀。

所以需要：

# Asset Manager

负责：

```text
load
cache
unload
preload
stream
```

---

# 30. 预加载策略

当前状态：

> 立即加载。

下一可能状态：

> 预加载。

低概率状态：

> 不加载。

例如当前：

```text
sitting
```

预加载：

```text
sit
blink
look
talk
stand
```

而：

> 跳舞

暂时不加载。

---

# 31. Asset Manifest

建议每个素材最终都有：

```json
{
  "id": "furina_sit_happy_01",
  "type": "frame",
  "state": "sitting",
  "emotion": "happy",
  "gaze": "user",
  "fps": 12,
  "loop": false,
  "priority": 5,
  "interruptible": true
}
```

Runtime 不应该依赖文件名猜逻辑。

---

# 32. 素材版本

因为全部素材来自 AI 生成，所以必须有：

```text
asset_version
character_version
generator
reference
prompt_version
quality_status
```

例如：

```text
furina_base_v1
furina_base_v2
```

以后发现：

> 新生成的一批脸变了。

可以整批替换。

---

# 33. AI 素材质量检查

建议进入 Runtime 前：

```text
Generate
↓
Identity Check
↓
Transparency Check
↓
Resolution Check
↓
Bounding Box Check
↓
Human Review
↓
Approved
```

只有：

> Approved

才能进入正式素材库。

---

# 34. DPI 与缩放

Windows 不一定是：

> 100% 缩放。

可能：

```text
100%
125%
150%
200%
```

所以角色尺寸不能直接：

```text
300px
```

而应该根据：

```text
logical pixel
+
DPI
```

计算。

否则换一台电脑：

> 芙宁娜直接变成巨人/小蚂蚁。

---

# 35. 角色尺寸

不要固定：

> 300×300。

应该：

```text
character_scale
```

例如：

```text
small
normal
large
```

默认：

> 屏幕高度的某个比例。

用户可以调节。

---

# 36. 桌面边界

她不能走出屏幕。

定义：

```text
world_bounds
```

并留：

```text
safe_margin
```

例如：

```text
left = 20
right = screen_width - 20
bottom = taskbar_top - 10
```

---

# 37. 移动系统

不要直接：

```text
x += 10
```

而应该：

```text
current_position
↓
target_position
↓
path
↓
velocity
↓
animation
```

这样以后才能加入：

* 加速
* 减速
* 转身
* 停顿
* 绕开区域

---

# 38. 简单路径规划就够了

第一版完全不需要复杂 NavMesh。

桌面环境其实非常简单。

可以：

```text
A
↓
B
```

以后如果出现：

> 窗口障碍。

再加入：

```text
obstacle avoidance
```

---

# 39. “走到哪里”不应该由 Runtime 决定

Runtime 只负责：

> 从 A 到 B。

Behavior Engine 决定：

> **为什么去 B。**

例如：

```text
Behavior:
go_to_user

Runtime:
target = user_related_position
```

这样模块边界清晰。

---

# 40. Scheduler

她的世界必须一直运行。

所以需要：

```text
Scheduler
```

负责：

* 时间
* 状态更新
* 行为 Tick
* 微动作
* Agent 任务
* 记忆事件
* 睡眠
* 唤醒

---

# 41. 不要每秒都调用 Qwen3.8

这是一个非常重要的性能原则。

错误：

```text
每 1 秒：
问 LLM “芙宁娜现在应该干嘛？”
```

绝对不能这么做。

应该：

```text
Local Runtime
↓
持续运行
```

只有：

> **复杂决策事件**

才调用 Qwen3.8。

例如：

```text
重大用户行为
复杂对话
Agent Planning
关系变化
异常情况
```

---

# 42. 三种 Tick

可以设计：

### Fast Tick

约 60 FPS：

```text
render
animation
input
```

### Medium Tick

约 1–5 秒：

```text
state update
idle behavior
window awareness
```

### Slow Tick

约 1–10 分钟：

```text
memory
relationship
long-term behavior
```

---

# 43. 芙宁娜的“睡眠”

这不仅是动画。

当：

```text
sleeping = true
```

系统可以：

```text
Agent ↓
Perception ↓
Behavior ↓
Rendering ↓
```

进入低功耗模式。

但仍然保留：

```text
system wake event
user interaction
alarm
```

---

# 44. 最小化/后台

如果用户最小化所有窗口：

> 她仍然可以生活。

如果程序最小化：

> 可以选择让她继续运行。

如果电脑锁屏：

> Runtime 进入 suspended。

解锁：

> resume。

---

# 45. 开机启动

可以提供：

> **开机自动启动芙宁娜**

但默认应该：

> 用户明确开启。

启动后：

```text
initialize
↓
load memory
↓
restore state
↓
restore relationship
↓
spawn character
```

于是她不是：

> 每次启动都失忆。

---

# 46. 崩溃恢复

必须保存：

```text
last_state
last_position
last_activity
memory queue
relationship
```

如果程序崩溃：

> 下次恢复。

但不要恢复：

> 正在进行的危险 Agent 操作。

Agent 任务必须：

```text
cancel_on_crash
```

---

# 47. 网络断开

这一点非常重要。

如果 Qwen3.8 是本地：

> 核心桌宠仍然应该运行。

网络断开：

```text
聊天能力 ↓
Agent 网络能力 ↓
```

但是：

```text
动画
状态
互动
本地记忆
基础行为
```

继续运行。

这才叫：

> **真正生活在电脑里。**

---

# 48. Qwen3.8 不应该成为 Runtime 的单点故障

系统必须允许：

```text
LLM unavailable
```

然后：

> 芙宁娜仍然能走、睡、眨眼、被摸、吃东西、观察桌面。

而不是：

> LLM 挂了 → 整个桌宠死了。

---

# 49. 系统架构最终可以定成

```text
┌─────────────────────────────────────────┐
│              Windows Runtime            │
│                                         │
│  ┌───────────┐     ┌───────────────┐   │
│  │ Renderer  │     │ Input System  │   │
│  └─────┬─────┘     └──────┬────────┘   │
│        │                   │            │
│        └─────────┬─────────┘            │
│                  ↓                      │
│         ┌──────────────────┐            │
│         │ Character Runtime│            │
│         └────────┬─────────┘            │
│                  ↓                      │
│         ┌──────────────────┐            │
│         │ Behavior Engine  │            │
│         └───────┬──────────┘            │
│                 │                       │
│        ┌────────┴─────────┐             │
│        ↓                  ↓             │
│   Memory Engine       Agent Runtime     │
│                             │           │
│                             ↓           │
│                         Windows        │
└─────────────────────────────────────────┘
```

---

# 50. Runtime 与六个系统的职责边界

这个必须定死。

| 系统          | 负责什么                    |
| ----------- | ----------------------- |
| State       | 她现在是什么状态                |
| Asset       | 用什么素材表现                 |
| Behavior    | 她想做什么                   |
| Interaction | 用户刚才对她做了什么              |
| Agent       | 她如何操作电脑                 |
| Memory      | 她过去经历过什么                |
| **Runtime** | **把这一切真正运行在 Windows 上** |

尤其：

> Runtime **不决定人格**。

> Runtime **不决定行为**。

> Runtime **不决定记忆**。

它只负责：

> **让这些东西能够真实发生。**

---

# 51. 最终一次完整事件

例如用户点击芙宁娜头部。

### Windows

产生：

```text
mouse_down
```

↓

### Runtime

检测：

```text
hitbox = head
```

↓

### Interaction Engine

判断：

```text
head_touch
```

↓

### State

```text
mood + 3
```

↓

### Memory

判断：

> 是否值得记忆。

↓

### Behavior

决定：

> 她现在想回应。

↓

### Asset

选择：

```text
happy_touch_reaction
```

↓

### Renderer

播放动画。

↓

### Qwen3.8

如果需要自然语言：

> “哼……再摸一下也不是不可以。”

↓

### Memory

记录：

> 用户与芙宁娜发生互动。

这就是完整闭环。

---

# 52. 最终启动流程

用户开机。

```text
Windows
 ↓
Furina Runtime
 ↓
Load Character
 ↓
Load Memory
 ↓
Restore State
 ↓
Detect Desktop
 ↓
Determine Position
 ↓
Start Scheduler
 ↓
Spawn Furina
 ↓
Idle Behavior
```

然后：

> 她出现。

不是：

> 一个网页打开了。

而是：

> **她回来了。**

这个区别非常重要。

---

# 53. 第七条的十条硬规则

**① 芙宁娜不是一个 PNG 窗口，而是一个运行在 Windows 桌面坐标系中的数字角色。**

**② Runtime 负责渲染、输入、位置、动画、资源和生命周期，不负责决定人格与行为。**

**③ 核心动画系统使用结构化多帧 Animation，而不是依赖 GIF 播放。**

**④ 透明区域必须支持点击穿透，角色区域必须拥有独立 Hitbox。**

**⑤ 微动作系统必须独立于主动作系统，保证 Idle 状态仍然具有生命感。**

**⑥ 窗口感知必须存在，但不能让芙宁娜无意义地遮挡用户工作。**

**⑦ Qwen3.8 不参与高频渲染和基础行为 Tick，只处理真正需要推理的事件。**

**⑧ LLM、网络或 Agent 暂时不可用时，芙宁娜的基础生命循环仍必须继续。**

**⑨ Agent 操作与角色视觉行为必须同步，但二者逻辑必须解耦。**

**⑩ Runtime 必须支持暂停、恢复、崩溃恢复、休眠、全屏检测、多显示器和 DPI 缩放。**

---

# 现在 ①～⑦ 才真正闭环了

整个产品可以压缩成这一张图：

```text
                    ┌───────────────┐
                    │    MEMORY     │
                    │   我经历过什么  │
                    └───────┬───────┘
                            ↓
                    ┌───────────────┐
                    │     STATE     │
                    │   我现在怎样    │
                    └───────┬───────┘
                            ↓
                    ┌───────────────┐
                    │   BEHAVIOR    │
                    │   我想做什么    │
                    └───────┬───────┘
                            ↓
               ┌────────────┴────────────┐
               ↓                         ↓
       ┌───────────────┐         ┌───────────────┐
       │  INTERACTION  │         │     AGENT     │
       │  你对我做什么   │         │ 我能替你做什么  │
       └───────┬───────┘         └───────┬───────┘
               └────────────┬────────────┘
                            ↓
                    ┌───────────────┐
                    │    ASSETS     │
                    │  我的身体表现   │
                    └───────┬───────┘
                            ↓
                    ┌───────────────┐
                    │    RUNTIME    │
                    │  我如何存在于桌面 │
                    └───────┬───────┘
                            ↓
                         WINDOWS
```

这里其实还有一个很重要的结论：

> **Qwen3.8 不是这个产品的“大脑本身”，而是大脑中负责复杂语言和推理的部分。**

真正的“芙宁娜”是：

**State + Behavior + Memory + Interaction + Agent + Persona + Body + Runtime**

共同组成的。

所以到这里，我们暂时**不要再加第⑧、第⑨、第⑩个系统**。产品核心已经够完整了。

下一步最合理的不是继续扩功能，而是把这 **7 个系统之间的接口和数据流彻底对齐**——否则最后写 PRD 时最容易出现的问题就是：每一条单看都很好，但七条拼起来以后，**同一件事到底由谁决定**会开始冲突。

我建议下一步直接做一件事：

> **把①～⑦合并成一张“芙宁娜生命运行总架构图 + Event Flow + 模块职责表”，逐条检查有没有逻辑冲突。**

这一步做完，才适合正式写最终 PRD。
