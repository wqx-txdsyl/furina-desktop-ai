可以。我们已经把**第 1 个「角色状态树」**定下来了，现在做第 **2 个：素材规范**。

我这里会严格基于刚才的整体架构来设计，而且重点不是“列一堆要生成的图片”，而是解决一个核心问题：

> **只有一张基座参考图的情况下，怎样建立一套足够系统的 AI 素材生产规范，让后面生成几百张图时，角色不会逐渐崩掉，而且程序能够真正调用这些素材。**

---

# ② 素材系统设计：Character Asset System

## 一、先定一个总原则

**素材不是动画。**

素材是角色身体能够表达的**视觉状态单元**。

程序不应该知道：

> `furina_happy_03.png`

是什么意思。

而应该知道：

```text
posture = sitting
emotion = happy
gaze = user
action = idle
direction = right
```

然后 Asset System 去寻找最合适的素材。

也就是说：

```text
AI / 行为系统
        ↓
“坐着，看用户，开心，轻微呼吸”
        ↓
Asset Resolver
        ↓
对应素材
        ↓
Renderer
```

所以从今天开始，**所有素材都必须结构化。**

---

# 二、素材分成 6 个层级

我建议最终不是简单的“静态图 / GIF”二分，而是：

```text
L0  Identity
    角色身份基准

L1  Base Pose
    基础姿态

L2  Expression
    表情 / 情绪

L3  Micro Motion
    微动作

L4  Action Animation
    完整动作

L5  Interaction / Event
    高级互动 / 特殊事件
```

这是整个素材库的骨架。

---

# 三、L0：Identity 基准层

这是**唯一不能随便改变的东西**。

你现在的：

> 芙宁娜基座参考图

就是：

```text
IDENTITY_ANCHOR
```

它不是最终桌宠素材。

它是以后所有生成任务的：

```text
Character Reference
+
Style Reference
+
Costume Reference
+
Proportion Reference
+
Color Reference
```

---

## L0 必须锁定的东西

以后任何 AI 生成，都不能随便改变：

### 角色身份

* 发型
* 发色
* 眼睛
* 脸型
* 五官比例
* 服装
* 帽子
* 饰品
* 身体比例
* Q 版比例
* 整体画风

### 允许改变

* 姿势
* 表情
* 视线
* 手势
* 动作
* 身体朝向
* 场景
* 道具

---

# 四、L1：Base Pose 基础姿态

这一层是整个系统最重要的“骨架”。

第一版不要急着生成 100 个动作。

先建立：

## 8 个核心姿态

```text
P01 standing
P02 sitting
P03 lying
P04 sleeping
P05 crouching
P06 leaning
P07 walking
P08 interacting
```

但其中真正高频的是：

```text
standing
sitting
lying
sleeping
```

---

# 五、姿态还必须有方向

例如：

```text
standing_front
standing_left
standing_right
standing_back
```

但是不要一开始把所有方向全部生成。

第一阶段：

```text
front
left
right
```

已经足够。

后续再补：

```text
back
three_quarter_left
three_quarter_right
```

---

# 六、L2：Expression 表情层

这里千万不要只做：

```text
happy
sad
angry
```

因为这会导致 AI 角色最后变成：

> “情绪贴纸”。

应该建立：

## 基础情绪

```text
neutral
happy
excited
proud
sad
angry
surprised
embarrassed
confused
tired
sleepy
curious
```

但还要加入：

## 芙宁娜特色状态

```text
dramatic
self_satisfied
pretending_calm
flustered
arrogant
complaining
being_praised
caught_off_guard
```

这部分非常重要。

因为我们做的是**角色**，不是通用情绪库。

---

# 七、L3：Micro Motion 微动作

这是我认为整个项目里**投资回报率最高的一层**。

因为用户 90% 的时间看到的不是：

> 芙宁娜跳舞。

而是：

> 芙宁娜什么都没干，但她在那里。

所以必须重点做。

---

## 第一批微动作

### 面部

```text
blink
slow_blink
look_left
look_right
look_up
look_down
```

### 身体

```text
breathing
body_sway
head_tilt
small_turn
```

### 手

```text
hair_touch
hat_adjust
hands_together
finger_move
```

### 特殊

```text
yawn
stretch
sigh
shiver
```

---

# 八、微动作不是“播放一次”

例如：

```text
blink
```

不能：

```text
播放 → 结束
```

而应该：

```text
idle
 ↓
随机等待
 ↓
blink
 ↓
idle
 ↓
随机等待
 ↓
blink
```

并且：

```text
blink interval
≈ 3–8s
```

不是固定值。

这样才能避免机械感。

---

# 九、微动作应该有概率

例如：

```json
{
  "action": "blink",
  "min_interval": 3,
  "max_interval": 8
}
```

而：

```json
{
  "action": "hair_touch",
  "probability": 0.08,
  "cooldown": 20
}
```

这样她每次启动都不会完全一样。

---

# 十、L4：完整动作

这一层才是传统意义上的“动画”。

建议第一批只做：

## 移动

```text
walk_left
walk_right
walk_front
```

## 日常

```text
sit_down
stand_up
lie_down
wake_up
sleep
drink
eat
read
stretch
```

## 情绪

```text
celebrate
angry
sad
excited
surprised
```

## 社交

```text
wave
beckon
look_at_user
turn_away
approach_user
```

---

# 十一、动作不要做成 GIF 黑盒

这是非常关键的一条。

不要：

```text
walk.gif
eat.gif
sleep.gif
```

然后程序只能：

```text
play()
```

应该把动作定义成：

```json
{
  "action": "walk",
  "direction": "right",
  "duration": 1.2,
  "interruptible": true,
  "loop": true,
  "root_motion": true
}
```

程序知道：

> 她正在走。

而不是：

> 某个 GIF 正在播放。

---

# 十二、L5：Interaction 互动素材

这才是专门服务于用户互动的。

例如：

### 摸头

```text
head_touch_1
head_touch_2
head_touch_3
```

### 拖拽

```text
drag_surprised
drag_angry
drag_embarrassed
```

### 喂食

```text
food_notice
food_happy
food_eat
food_finish
```

### 点击

```text
tap_surprised
tap_annoyed
tap_happy
```

---

# 十三、L6：Event 特殊事件

数量少，但是用于制造“哇”的瞬间。

例如：

```text
birthday
welcome_back
good_morning
good_night
achievement
rainy_day
snow_day
long_absence
first_meeting
```

还有：

> 用户连续工作很久。

芙宁娜突然：

```text
从屏幕边缘走过来
↓
看用户
↓
叉腰
↓
说话
```

这就是 Event。

---

# 十四、素材数量不要平均分配

如果第一阶段准备 **150 个视觉资产**，我会这样分：

| 类型    | 数量 | 重要性   |
| ----- | -: | ----- |
| 基础姿态  | 15 | ★★★★★ |
| 情绪/表情 | 25 | ★★★★★ |
| 微动作   | 45 | ★★★★★ |
| 日常动作  | 30 | ★★★★  |
| 互动动作  | 20 | ★★★★  |
| 特殊事件  | 15 | ★★★   |

也就是说：

> **不是“动作越多越好”。**

而是：

> **高频状态要密，低频大招要少。**

---

# 十五、我甚至建议第一版先做 100 个

不要一上来生成 500 张。

第一阶段：

```text
100 Assets
```

跑起来。

如果体验已经有生命感，再扩展。

因为你很可能会发现：

> 20 个微动作的效果，比 100 个大动作更明显。

---

# 十六、最关键的：素材之间必须“可组合”

例如系统当前状态：

```text
Posture
= sitting

Emotion
= proud

Gaze
= user

MicroMotion
= breathing
```

Renderer 得到：

```text
sitting
+
proud
+
look_user
+
breathing
```

于是形成：

> 坐着、骄傲地看着用户、轻微呼吸。

下一秒：

```text
sitting
+
proud
+
look_screen
+
hair_touch
```

她就自然变成：

> 坐着看屏幕，顺手整理头发。

---

# 十七、但这里有一个现实问题

**如果你所有素材都是独立完整 PNG，就不能真的像 Live2D 一样随意叠加。**

所以我们不能幻想：

```text
身体 PNG
+
脸 PNG
+
手 PNG
```

永远无缝组合。

你现在的路线更现实：

## “状态图 + 动作序列 + 程序调度”

而不是：

## “真正的 2D 骨骼动画”。

这一点必须在产品设计上承认。

所以 Asset Resolver 应该有：

### Exact Match

找到完全符合条件的素材。

↓

### Partial Match

如果没有：

> 坐着 + 开心 + 看左边

就找：

> 坐着 + 开心

↓

再没有：

> 坐着 + 中性

↓

再通过微动作补足。

---

# 十八、素材匹配优先级

我建议固定为：

```text
Exact Match
      ↓
Same Posture
      ↓
Same Emotion
      ↓
Same Action
      ↓
Nearest Semantic State
      ↓
Neutral Fallback
```

例如系统需要：

```text
lying
+
embarrassed
+
user
```

但是没有。

可以：

```text
lying
+
embarrassed
```

如果还没有：

```text
lying
+
neutral
```

而不是：

> 随便拿一张站立图。

---

# 十九、每个素材必须有 Metadata

最终 Asset Manifest 类似：

```json
{
  "asset_id": "P02_E04_G01_A00_001",

  "posture": "sitting",
  "emotion": "happy",
  "gaze": "user",
  "direction": "front",

  "action": "idle",
  "micro_motion": null,

  "loop": true,

  "duration": null,

  "interruptible": true,

  "priority": 50,

  "tags": [
    "daily",
    "idle",
    "social"
  ]
}
```

以后程序完全根据 metadata 找素材。

---

# 二十、命名规范必须现在就定

不要：

```text
芙宁娜开心2.png
最终版.png
真的最终版.png
新图.png
```

绝对禁止。

统一：

```text
furina_[posture]_[emotion]_[gaze]_[action]_[variant]
```

例如：

```text
furina_sitting_happy_user_idle_01.png

furina_standing_proud_left_idle_01.png

furina_lying_sleepy_screen_idle_01.png

furina_standing_surprised_user_wave_01.png
```

动画：

```text
furina_walk_right_001.png
furina_walk_right_002.png
furina_walk_right_003.png
...
```

---

# 二十一、文件夹也按语义组织

我建议：

```text
assets/
│
├── identity/
│
├── poses/
│
├── expressions/
│
├── micro/
│
├── actions/
│
├── interactions/
│
├── events/
│
├── props/
│
└── manifest/
```

而不是：

```text
assets/
├── 1.png
├── 2.png
├── 3.png
...
```

---

# 二十二、Props 道具必须单独建立

这个很容易被忽略。

例如：

```text
tea
cup
cake
book
phone
computer
gift
umbrella
```

以后可以形成：

```text
Furina + Tea

Furina + Book

Furina + Cake
```

甚至：

```text
Furina
+
Computer
+
Sitting
+
Working
```

---

# 二十三、AI 生成必须建立 Prompt Template

不要每次手写 prompt。

建立：

```text
BASE PROMPT
+
CHARACTER LOCK
+
POSE
+
EXPRESSION
+
GAZE
+
ACTION
+
PROP
+
COMPOSITION
```

例如：

```text
[CHARACTER LOCK]

[POSE]
sitting naturally

[EXPRESSION]
slightly proud

[GAZE]
looking toward the user

[ACTION]
holding a cup of tea

[COMPOSITION]
full body, isolated character

[BACKGROUND]
transparent

[STYLE]
match the provided reference image exactly
```

以后你只替换变量。

---

# 二十四、生成流程必须有“质检”

每生成一张图，不是：

> 看起来不错 → 丢进文件夹。

而是四项检查：

### ① Identity

还是不是同一个芙宁娜？

### ② Anatomy

手、脚、脸、服装有没有崩？

### ③ Style

有没有偏离基座画风？

### ④ Semantic

这张图真的表达了：

> `sitting + happy + user`

吗？

---

# 二十五、建立 Asset Quality Score

每张图：

```text
Identity      0–5
Anatomy       0–5
Style         0–5
Semantics     0–5
Transparency  0–5
```

总分：

```text
25
```

建议：

```text
22–25  → production
18–21  → optional
<18    → regenerate
```

这样后面几百张图不会越来越乱。

---

# 二十六、最终最重要的一条

我们不要追求：

> **“生成尽可能多的图片。”**

而要追求：

> **“让有限的图片产生尽可能多的行为组合。”**

比如 100 个素材，通过：

```text
状态
+
位置
+
方向
+
视线
+
微动作
+
声音
+
文字
+
时间
+
用户行为
```

最终产生：

> **远远超过 100 种体验。**

这才是这个项目真正成立的地方。

---

# ② 最终定稿结构

所以我建议第 2 个设计最终锁成：

```text
02 Character Asset System
│
├── 01 Identity Anchor
│
├── 02 Base Pose
│
├── 03 Expression
│
├── 04 Micro Motion
│
├── 05 Action Animation
│
├── 06 Interaction
│
├── 07 Event
│
├── 08 Props
│
├── 09 Asset Metadata
│
├── 10 Naming Convention
│
├── 11 Directory Structure
│
├── 12 AI Generation Pipeline
│
├── 13 Quality Control
│
└── 14 Asset Resolver
```

而**第 2 个设计真正要解决的问题**就是：

> **“如何把一张基座图，工程化成一个可以被 AI 行为系统持续调用的‘数字身体’。”**

我认为这个版本可以作为后面正式 PRD 的第二章，不需要再往“多生成几张表情包”那个方向走。
