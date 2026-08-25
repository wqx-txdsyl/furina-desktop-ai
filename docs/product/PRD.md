可以，而且如果你想做的不是“一个会说话的动态立绘”，而是**“电脑里真的住着一个芙宁娜”**，设计思路必须彻底换一下：

> **不要把“桌宠”当作动画项目，而要把它当作一个拥有身体、情绪、记忆、环境感知、行动能力和电脑操作能力的 AI Agent。**

这样才能做到你说的“像真人”。

我会把整个系统设计成 **「角色生命系统 + 桌面身体 + AI大脑 + Computer Use Agent」** 四层。

---

# 一、首先定义：她不是桌宠，而是“数字生命”

传统桌宠：

> 用户点击 → 播放一个动画 → 结束

你要做的应该是：

> **感知 → 判断 → 产生意图 → 行动 → 观察结果 → 更新状态**

例如：

你连续两个小时没动电脑。

普通桌宠：

> 播放“打哈欠”动画。

你的芙宁娜：

> “……你已经盯着这个东西很久了吧？”

然后她可能走到屏幕边缘。

> “本神觉得，你现在应该休息五分钟。”

你：

> “不要。”

她：

> “……哼。那至少喝口水。”

这就开始有“生命感”了。

---

# 二、最重要的设计：不要用“状态机”模拟真人，要用「状态 + 动机 + 行为」

这是整个项目最关键的地方。

不要写：

```text
IDLE
 ↓
WALK
 ↓
SIT
 ↓
EAT
 ↓
SLEEP
```

这种最终一定会变成动画片。

应该是：

```text
                ┌─────────────┐
                │  当前环境   │
                │ 用户正在做什么│
                └──────┬──────┘
                       ↓
                ┌─────────────┐
                │ 角色状态    │
                │ 情绪/精力/饥饿│
                └──────┬──────┘
                       ↓
                ┌─────────────┐
                │ 角色动机    │
                │ 我现在想干嘛？│
                └──────┬──────┘
                       ↓
                ┌─────────────┐
                │ 行为选择器  │
                └──────┬──────┘
                       ↓
          ┌────────────┼────────────┐
          ↓            ↓            ↓
        说话          行走         玩耍
          ↓            ↓            ↓
          └────────────┼────────────┘
                       ↓
                观察用户反应
                       ↓
                  更新状态
```

所以：

**动画只是“身体语言”，不是 AI 本身。**

---

# 三、芙宁娜应该拥有一套“生命参数”

我建议至少做这些。

### 基础状态

| 参数   |    范围 | 作用       |
| ---- | ----: | -------- |
| 精力   | 0–100 | 决定活动频率   |
| 心情   | 0–100 | 影响语气和行为  |
| 饥饿   | 0–100 | 决定是否吃东西  |
| 无聊   | 0–100 | 决定是否找事情做 |
| 社交需求 | 0–100 | 决定是否主动找你 |
| 兴奋度  | 0–100 | 影响动作频率   |
| 困倦   | 0–100 | 决定休息/睡觉  |
| 好奇心  | 0–100 | 决定探索桌面   |
| 工作欲  | 0–100 | 决定是否帮助你  |
| 依赖感  | 0–100 | 决定主动互动程度 |

但这里有一个特别重要的东西：

## **不要让这些参数直接决定行为。**

例如：

```text
饥饿 > 80 → 吃饭
```

太机械。

应该是：

> 饥饿上升
>
> * 当前没有重要任务
> * 心情不错
> * 用户正在工作
>   → “偷偷去找吃的”

或者：

> 饥饿上升
>
> * 用户正在开会
>   → 忍着

于是她可能只是坐在旁边摸摸肚子。

这才像“人”。

---

# 四、再增加一个「当前意图」

例如：

```json
{
  "current_intention": "想和主人说话",
  "priority": 0.72,
  "reason": [
    "已经20分钟没有互动",
    "当前无重要任务",
    "社交需求上升"
  ]
}
```

或者：

```json
{
  "current_intention": "帮助主人完成工作",
  "priority": 0.91,
  "reason": [
    "检测到用户正在处理Excel",
    "用户正在反复复制数据"
  ]
}
```

或者：

```json
{
  "current_intention": "休息",
  "priority": 0.68
}
```

然后 AI 决定：

> **我现在到底想做什么？**

这一步会让她从“动画”变成“角色”。

---

# 五、我建议给她设计 12 类核心状态

不是单纯的动画，而是**生活状态**。

### 01｜待机

不是站在那里呼吸。

而是：

* 看着用户
* 发呆
* 整理衣服
* 摆弄帽子
* 坐着晃腿
* 看窗外
* 小声自言自语
* 突然想起什么
* 偷偷观察你的窗口

甚至：

> “嗯……”

然后什么都不说。

**“什么都不做”本身就是生命感。**

---

### 02｜工作

当用户工作时：

她可以：

* 坐在任务栏附近
* 看着你的窗口
* 偶尔发表意见
* 帮你查资料
* 整理文件
* 总结网页
* 写邮件
* 整理表格
* 创建待办事项
* 提醒截止时间

甚至：

> “你这个表格是不是还差一列？”

点击后：

> “我可以帮你补。”

---

### 03｜陪伴

用户写代码：

> “又在写代码？”

用户写论文：

> “这个标题似乎有点奇怪。”

用户看视频：

她坐旁边。

用户听歌：

她可能跟着节奏轻轻晃。

**重点：她要知道用户现在在干什么。**

---

# 六、互动一定要做成“物理交互”

这是你这个项目最容易做出差异化的地方。

比如：

## 摸头

不要：

```text
点击头部 → 播放摸头动画
```

而应该：

```text
鼠标坐标
 ↓
碰撞检测
 ↓
头部区域
 ↓
检测鼠标运动方向
 ↓
判断“抚摸”
 ↓
角色产生反应
```

例如：

```text
第一次摸：

“嗯？”

第二次：

“……你在干什么？”

持续摸：

“好啦好啦……”

继续摸：

“哼，你很喜欢摸本神的头吗？”
```

她的反应甚至应该受到：

* 当前心情
* 当前状态
* 最近互动
* 用户关系
* 是否正在工作

影响。

---

# 七、可以做非常多这种“身体交互”

### 拖她

鼠标拖住：

她：

> “诶？诶诶？！”

拖到另一边：

> “你要把我放哪里？”

---

### 点击帽子

她会扶帽子。

---

### 点击脸

可能：

> “喂！”

或者躲开。

---

### 点击脚

她把脚缩起来。

---

### 连续点击

她越来越不耐烦。

---

### 鼠标靠近

她看向鼠标。

---

### 鼠标停在她旁边

她可能看一眼。

---

### 鼠标长时间不动

她开始自己活动。

---

# 八、最关键的一个功能：她应该能“走进你的电脑”

这比单纯在桌面上走重要得多。

例如：

你打开 Chrome。

她可以：

> 从桌面走到 Chrome 窗口旁边。

你打开 VS Code。

她跑到 VS Code 边缘：

> “又开始写代码了？”

你打开 Word。

她：

> “今天准备写什么？”

这意味着她必须知道：

```text
当前活动窗口
当前应用
窗口位置
窗口大小
用户行为
```

Windows 的 UI Automation 本身就可以提供桌面 UI 元素的程序化访问，并且可以操作很多 Win32、WPF、WinForms、Electron、WinUI 应用。([Microsoft Learn][1])

所以你完全可以把：

> **“电脑环境”**

作为她的感知器。

---

# 九、这样就出现一个非常有意思的系统

她拥有：

### 世界

```text
Windows Desktop
```

### 身体

```text
Furina Avatar
```

### 眼睛

```text
Screen Perception
```

### 耳朵

```text
Microphone
```

### 大脑

```text
LLM
```

### 记忆

```text
Long-term Memory
```

### 手

```text
Computer Use Agent
```

### 情绪

```text
Emotion Engine
```

### 行为系统

```text
Behavior Planner
```

这就已经不是传统意义上的桌宠了。

---

# 十、她的“眼睛”应该是什么？

这里千万不要每秒截图然后丢给视觉模型。

成本太高，也会非常卡。

应该做多层感知。

### Level 1：系统感知

实时：

```text
当前窗口
当前程序
窗口标题
鼠标位置
键盘输入
CPU
内存
时间
```

---

### Level 2：UI 感知

例如：

```text
Chrome
 ├── 地址栏
 ├── 标签页
 ├── 搜索框
 └── 页面内容
```

Windows UI Automation 可以读取 UI 元素树、控件类型、属性和事件。([Microsoft Learn][2])

---

### Level 3：视觉感知

只有需要的时候：

```text
截图
 ↓
Vision Model
 ↓
理解画面
```

例如：

> “你现在打开的是一个 PPT。”

---

### Level 4：语义感知

例如：

> 用户正在写“上海高考综评”。

AI 可以理解：

> “这是用户正在做的一个长期项目。”

这就进入长期记忆。

---

# 十一、她还应该有“自己的房间”

这个我非常建议你做。

不要让她永远漂在透明桌面上。

可以设计一个：

## 「Furina's Room」

她平时住在这里。

里面有：

* 沙发
* 床
* 餐桌
* 书桌
* 冰箱
* 电视
* 小厨房
* 玩具
* 镜子
* 窗户

然后桌面只是：

> **她偶尔出来活动的地方。**

例如：

晚上：

她回房间。

坐在沙发上。

你点她：

> “今天怎么样？”

她：

> “哼……本神今天可是忙得很。”

---

# 十二、吃饭不要只是“播放吃饭动画”

可以做成真正的物品系统。

例如：

```text
Food
├── cake
├── tea
├── macarons
├── bread
└── water
```

她可以：

> 饿了 → 去冰箱 → 找东西 → 拿出来 → 吃

甚至：

> “你今天怎么还不给我准备下午茶？”

用户可以拖一个蛋糕给她。

她：

> “这是给本神的？”

然后吃掉。

---

# 十三、玩耍系统

这是避免她变成办公插件的关键。

她应该拥有自己的娱乐。

比如：

### 小游戏

* 接东西
* 打牌
* 钓鱼
* 拼图
* 小型音乐游戏
* 桌球
* 下棋
* 找东西

但重点不是游戏本身。

而是：

> **她会主动邀请你玩。**

例如：

> “喂。”

> “干什么？”

> “陪本神玩一会儿。”

---

# 十四、她应该可以自己“无聊”

这是极其重要的。

如果：

```text
用户不理她
```

她不能永远：

```text
idle animation
```

而应该进入：

```text
Boredom ↑
```

然后：

> 走来走去

> 坐下

> 玩东西

> 看手机

> 睡觉

> 整理房间

> 找用户

> 偷偷观察用户

甚至：

> “你是不是把本神忘了？”

这种行为会极大增强生命感。

---

# 十五、但是更重要的是：她可以主动打断你

不过必须有一个：

## Interruption Manager

把主动行为分成：

### 0级

完全不打扰。

例如：

> “……”

### 1级

轻微。

走到你旁边。

### 2级

说一句话。

> “喂。”

### 3级

提醒。

> “你十分钟后有会议。”

### 4级

必须打断。

例如：

> “你刚才是不是忘记保存？”

这样不会变成：

> 每五分钟蹦出来一句话。

---

# 十六、然后才是你说的“全能 Agent”

这一层我建议单独设计。

不要让 LLM 直接：

```text
LLM → 鼠标键盘
```

这是非常危险也非常难调的。

应该：

```text
用户
 ↓
Furina
 ↓
Intent
 ↓
Planner
 ↓
Tool Router
 ↓
Permission Layer
 ↓
Computer
```

例如用户：

> “帮我把今天下载的 PDF 整理一下。”

Agent：

```text
理解任务
 ↓
寻找 Downloads
 ↓
读取文件
 ↓
判断文件类型
 ↓
分类
 ↓
创建文件夹
 ↓
移动文件
 ↓
汇报结果
```

---

# 十七、Computer Agent 应该有这些工具

```text
Desktop Tools
│
├── screenshot
├── mouse_move
├── mouse_click
├── mouse_drag
├── keyboard_type
├── keyboard_hotkey
├── scroll
│
├── window_list
├── window_focus
├── window_move
│
├── filesystem
│   ├── read
│   ├── write
│   ├── rename
│   ├── move
│   └── search
│
├── browser
│   ├── open
│   ├── search
│   ├── click
│   ├── extract
│   └── download
│
└── apps
    ├── VSCode
    ├── Word
    ├── Excel
    ├── PowerPoint
    └── ...
```

浏览器部分可以直接采用浏览器自动化，而桌面应用则优先使用 UI Automation；只有 UI Automation 无法完成时再退回真实鼠标/键盘输入。微软现在的 UI Automation 工具本身也是这种思路：优先 UIA pattern，必要时才注入鼠标和键盘。([Microsoft Learn][1])

---

# 十八、一定要有“权限系统”

比如：

### 自动允许

```text
读取当前窗口
读取时间
读取系统状态
读取公开网页
```

### 询问一次

```text
修改文件
发送邮件
创建文件
修改文档
```

### 每次询问

```text
发送消息
删除文件
提交代码
购买东西
修改系统设置
```

### 永远禁止

危险/高风险操作等。

于是她不是：

> “万能黑客。”

而是：

> **拥有明确边界的数字助手。**

---

# 十九、技术架构我建议这样做

如果你是 Windows PC：

```text
                 ┌─────────────────────┐
                 │      Furina UI      │
                 │  Desktop / Room     │
                 └──────────┬──────────┘
                            │
                   WebSocket / IPC
                            │
                 ┌──────────▼──────────┐
                 │   Character Engine  │
                 │                     │
                 │ Emotion             │
                 │ State               │
                 │ Behavior            │
                 │ Interaction         │
                 └──────────┬──────────┘
                            │
                 ┌──────────▼──────────┐
                 │      AI Brain       │
                 │                     │
                 │ LLM                 │
                 │ Memory              │
                 │ Planner             │
                 │ Tool Router         │
                 └──────────┬──────────┘
                            │
             ┌──────────────┼──────────────┐
             ↓              ↓              ↓
       Perception        Memory         Tools
             │              │              │
             ↓              ↓              ↓
        Windows UI       Vector DB       Computer
        Screenshot       SQLite          Browser
        Audio             Profile        Files
```

---

# 二十、人物表现层：我反而推荐 Live2D

如果你的目标是**芙宁娜这种二次元角色**，Live2D 会比传统 Spine / Sprite 更适合。

Live2D Cubism 本身就是为了程序控制模型参数而设计的，SDK 可以在程序中控制模型；官方 SDK 还提供了眨眼、物理、动作、表情、唇形同步等能力。([Live2D 文档][3])

而且截至 2026 年，Live2D Cubism 5 SDK 仍在持续更新。([Live2D 文档][4])

所以你可以让 AI 输出：

```json
{
  "emotion": "playful",
  "gaze": "user",
  "head": {
    "x": 0.2,
    "y": -0.1
  },
  "body": {
    "lean": 0.15
  },
  "expression": {
    "mouth": 0.4,
    "eyes": 0.7
  },
  "motion": "walk_left"
}
```

然后 Character Engine 把它转换成 Live2D 参数。

**LLM 不负责动画。**

LLM 只负责：

> “我现在是什么状态，我想做什么。”

Character Engine 负责：

> “那我应该怎么动。”

这两者一定要分开。

---

# 二十一、甚至可以做到“连续动作”

比如：

> “我饿了。”

不要：

```text
播放 Eat Animation
```

而是：

```text
停止当前行为
↓
看向冰箱
↓
走过去
↓
打开冰箱
↓
寻找食物
↓
犹豫
↓
拿出蛋糕
↓
走回来
↓
坐下
↓
吃
↓
心情 +8
饥饿 -30
```

这里每一步都是 Agent 根据当前状态决定的。

**这就是你要的“真人感”。**

---

# 二十二、语音也不要做成“一问一答”

推荐：

```text
ASR
 ↓
Dialogue Manager
 ↓
LLM
 ↓
TTS
 ↓
Lip Sync
```

但是再加：

```text
Conversation Memory
```

例如昨天：

> “我明天要交报告。”

今天：

> “你的报告怎么样了？”

这一下就完全不同了。

---

# 二十三、长期记忆

我会分成四层：

```text
Working Memory
当前对话

Episodic Memory
你们发生过什么

Preference Memory
你喜欢什么

Relationship Memory
她如何理解你们之间的关系
```

例如：

```text
用户喜欢晚上工作
用户经常使用 VS Code
用户正在做哲学网站
用户不喜欢被频繁打扰
用户周五有固定会议
```

于是她不是每次重新认识你。

---

# 二十四、甚至可以做“关系成长”

不是简单的：

```text
好感度 72
```

这种游戏数值。

而应该是：

```text
Relationship Model

熟悉度
信任
依赖
默契
共同经历
互动习惯
```

例如她逐渐发现：

> 用户工作的时候不喜欢聊天。

那么她以后：

> 工作状态 → 主动安静。

但晚上：

> 主动出来找你。

这才是 AI 角色真正有意义的“成长”。

---

# 二十五、最终我会把她分成五个“人格层”

```text
                    Furina
                       │
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
      Persona       Emotion        Relationship
        │              │              │
        └──────────────┼──────────────┘
                       ↓
                    Intent
                       ↓
                   Behavior
                       ↓
                    Action
```

例如：

用户：

> “帮我做 PPT。”

系统不是直接调用 PPT 工具。

而是：

### Persona

> 芙宁娜式回应

### Emotion

> 当前心情不错

### Relationship

> 用户经常让她帮忙

### Intent

> 想帮助用户

### Behavior

> 主动靠近 PowerPoint

### Agent

> 创建 PPT

### Character

> “好了，本神亲自监督你。”

这样：

**AI Agent 和桌宠角色就真正融合了。**

---

# 二十六、我尤其建议做一个“Furina OS”

甚至可以给整个项目一个很明确的产品概念：

> **不是 Desktop Pet。**
>
> **是 Desktop Companion / Digital Character Agent。**

电脑右下角：

```text
        Furina
          │
 ┌────────┼────────┐
 │        │        │
陪伴     生活      工作
 │        │        │
聊天     吃饭      文件
摸头     玩耍      浏览器
散步     睡觉      PPT
撒娇     房间      Excel
```

她既是：

**角色**

又是：

**助手**

还是：

**电脑里的一个“人”。**

---

# 二十七、我会这样安排开发路线

不要一开始就做“全能 Agent”。

### Phase 1：身体

先做到：

* 透明桌面
* 芙宁娜 Live2D
* 自由移动
* 看向鼠标
* 摸头
* 拖拽
* 点击身体不同部位
* 眨眼
* 呼吸
* 随机微动作

目标：

> **看起来真的活着。**

---

### Phase 2：生命系统

加入：

* 精力
* 饥饿
* 无聊
* 心情
* 社交需求
* 意图
* 自主行为

目标：

> **没有用户操作，她也会自己生活。**

---

### Phase 3：AI 对话

加入：

* LLM
* ASR
* TTS
* Lip Sync
* Persona
* Memory

目标：

> **她开始像一个人。**

---

### Phase 4：环境感知

加入：

* 当前窗口
* 当前程序
* 鼠标
* 用户活动
* Screenshot
* UI Automation

目标：

> **她开始知道你在干什么。**

---

### Phase 5：Computer Agent

加入：

* 浏览器
* 文件
* Office
* VS Code
* 系统工具
* 权限系统

目标：

> **她真的能帮你工作。**

---

### Phase 6：真正的“数字生命”

最后加入：

* 房间
* 食物
* 物品
* 玩具
* 自主活动
* 长期记忆
* 关系变化
* 生活事件
* 主动找你
* 主动帮助
* 长期行为习惯

这时候就不是：

> **“我养了一只桌宠。”**

而是：

> **“我的电脑里住着一个芙宁娜。”**

---

## 最后一个我认为特别重要的原则

你这个项目**最忌讳“AI决定播放哪个动画”**。

那样做出来一定是：

> AI + 桌宠动画。

你真正应该做的是：

> **AI 决定她此刻为什么行动，行为系统决定她怎么行动，动画系统负责把这个行动表现出来。**

即：

```text
              LLM
               │
          “我想做什么？”
               ↓
        ┌──────────────┐
        │ Character AI │
        │   Brain      │
        └──────┬───────┘
               ↓
          Intent/Goal
               ↓
        Behavior Planner
               ↓
        ┌──────┴──────┐
        ↓             ↓
    Computer       Body Action
      Agent           │
        │             ↓
        ↓          Live2D
     Windows          │
        │             ↓
        └──────→ 角色表现
```

这会让你的项目从“桌宠”直接跨到一个非常有意思的方向：

**「AI 原生桌面角色」**。

而且这条路线技术上是现实可做的：Live2D 已经提供程序控制模型的 SDK；Windows UI Automation 可以把桌面应用暴露成可程序化操作的 UI；两者中间再建立你自己的 Character Engine 和 Agent Runtime。([Live2D 文档][3])

如果真要做，我甚至建议**第一版就不要做成“桌面右下角一个小人”**，而是直接设计成一套完整的 **「Furina Desktop Life OS」**：桌面身体、房间、生命状态、人格、记忆、电脑感知、Agent 工具全部统一在一个架构里。这样后面加办公能力不会把“桌宠”和“Agent”做成两个互不相干的东西。

[1]: https://learn.microsoft.com/en-us/windows/apps/dev-tools/winapp-cli/ui-automation?utm_source=chatgpt.com "UI Automation - Windows apps | Microsoft Learn"
[2]: https://learn.microsoft.com/en-us/windows/win32/winauto/ui-automation-specification?utm_source=chatgpt.com "UI Automation Specification - Win32 apps | Microsoft Learn"
[3]: https://docs.live2d.com/en/cubism-sdk-manual/cubism-sdk-for-web/?utm_source=chatgpt.com "Cubism SDK for Web | SDK Manual | Live2D Manuals & Tutorials"
[4]: https://docs.live2d.com/en/cubism-sdk-manual/top/?utm_source=chatgpt.com "Cubism SDK manual | SDK Manual | Live2D Manuals & Tutorials"



对，那就**不要把 Live2D 当作前提**。而且你这个限制反而会逼出一个更有意思的方案：

> **不是“Live2D 桌宠的廉价替代品”，而是“基于大量状态资产 + AI 行为系统的 2D 数字生命”。**

如果你愿意准备非常庞大的 PNG / GIF / APNG / WebP 多帧资产库，完全可以做，而且关键不在资产数量，而在于**怎么让 AI 把这些资产组合成连续行为**。

---

# 一、核心思路改变：从“动画”变成“动作原子”

千万不要准备：

> `摸头.gif`
> `吃饭.gif`
> `开心.gif`
> `生气.gif`

然后 AI 随机播放。

这样还是动画片。

应该把所有素材拆成：

### ① 姿态

```text
stand
sit
lie
kneel
sleep
lean
walk
run
```

### ② 表情

```text
normal
happy
angry
sad
surprised
proud
embarrassed
sleepy
```

### ③ 动作

```text
look_left
look_right
look_up
look_down

wave
nod
shake_head

touch_head_reaction
push_hand_away
cover_face

eat
drink
yawn
stretch
```

### ④ 物品

```text
cake
tea
book
phone
computer
umbrella
```

然后由一个 **Character Renderer** 把它们组合。

---

# 二、你甚至可以不用真正的“骨骼动画”

假设你准备：

```text
furina/
├── idle/
│   ├── idle_01.webp
│   ├── idle_02.webp
│   └── ...
│
├── walk/
│   ├── left_01.webp
│   ├── left_02.webp
│   └── ...
│
├── face/
│   ├── normal.webp
│   ├── happy.webp
│   ├── angry.webp
│   └── ...
│
├── action/
│   ├── eat.webp
│   ├── drink.webp
│   ├── sleep.webp
│   └── ...
```

Renderer：

```text
状态
 ↓
选择姿态
 ↓
选择表情
 ↓
选择动作
 ↓
选择对应帧
 ↓
渲染
```

所以：

> **AI 不知道“我要播放 eat.gif”。**

AI 知道：

> “我饿了，我想吃东西。”

Behavior Engine 决定：

```text
go_to_food
→ pick_food
→ sit
→ eat
→ satisfied
```

每一步才去找相应的素材。

---

# 三、甚至可以把“真人感”做到非常强

因为真人也不是一直在做大动作。

你需要大量的是：

## 微动作

这反而比大动画重要。

比如待机状态不要只有一个：

```text
idle.gif
```

而是：

```text
idle/
├── breathing_01
├── breathing_02
├── blink
├── hair_move
├── look_around
├── adjust_hat
├── touch_hair
├── yawn
├── stretch
├── sigh
├── shift_weight
├── look_at_user
├── look_at_screen
└── look_away
```

然后随机组合。

---

# 四、最关键：建立一个“动作混合器”

例如当前状态：

```text
standing
emotion = happy
attention = user
```

可以组合：

```text
身体：
standing

头部：
slightly_left

眼睛：
look_at_user

表情：
smile

微动作：
blink

呼吸：
breathing
```

几秒之后：

```text
身体：
standing

头部：
slightly_right

眼睛：
look_at_screen

表情：
normal

微动作：
adjust_hat
```

所以用户看到的不是：

> 播放一个动画。

而是：

> **角色一直处于一个连续变化的状态。**

---

# 五、如果你连“动作混合”都做不了

那就退一步：

## 做“状态快照系统”

准备大量完整 PNG。

例如：

```text
furina_states/

idle/
  001.png
  002.png
  003.png
  ...

happy/
  001.png
  002.png
  ...

angry/
  ...

thinking/
  ...

eating/
  ...

sleeping/
```

然后 AI 每隔几百毫秒重新决定：

```text
current_state =
  posture + expression + gaze + action
```

例如：

```text
坐着 + 开心 + 看用户 + 喝茶
```

切换到：

```text
坐着 + 开心 + 看屏幕 + 喝茶
```

再：

```text
坐着 + 思考 + 看屏幕 + 放下茶杯
```

**如果你的状态图片足够丰富，用户根本不会觉得是在切图片。**

---

# 六、我反而建议你把“状态”设计成三维矩阵

这是整个系统最值得做的地方。

```text
身体状态 × 情绪 × 注意力
```

例如：

| 身体 | 情绪 | 注意力 | 状态             |
| -- | -- | --- | -------------- |
| 站立 | 平静 | 用户  | idle_user      |
| 站立 | 平静 | 屏幕  | idle_screen    |
| 坐  | 开心 | 用户  | sit_happy_user |
| 坐  | 困倦 | 用户  | sit_sleepy     |
| 坐  | 专注 | 屏幕  | work_focus     |
| 躺  | 困倦 | 无   | sleep          |
| 走  | 开心 | 目标  | walk_happy     |
| 走  | 生气 | 用户  | walk_angry     |

这样你就能组合出大量状态。

---

# 七、然后做“状态转移”

例如：

```text
工作
 ↓
用户叫她
 ↓
注意力 → 用户
 ↓
停下工作
 ↓
转身
 ↓
说话
```

又比如：

```text
睡觉
 ↓
用户摸头
 ↓
醒来
 ↓
困惑
 ↓
看向用户
 ↓
“嗯……？”
```

注意：

**不是用户点击 → 直接跳到“摸头反应”。**

而是：

```text
当前状态
 ↓
输入事件
 ↓
状态变化
 ↓
动作
 ↓
新状态
```

这才会有连续性。

---

# 八、你说的“摸头”，完全可以不用 Live2D

例如定义鼠标区域：

```text
         ┌───────────┐
         │    HEAD   │
         │           │
         └───────────┘
              BODY
```

检测：

```text
mouse_down
+
mouse_position ∈ head
```

然后检测鼠标移动：

```text
↑ ↓ ↑ ↓ ↑
```

判断：

> 用户正在摸头。

然后：

```text
current_emotion
        ↓
reaction selector
```

可能产生：

### 心情好

> 微笑 → 闭眼 → 享受

### 普通

> 看你一眼 → “嗯？”

### 正在工作

> 抬头 → “等一下嘛。”

### 心情不好

> 躲开 → “别碰。”

所以同样一个“摸头”，**不是固定动画。**

---

# 九、你可以做一个非常强的“物理交互层”

我建议至少：

```text
鼠标：
├── 点击
├── 双击
├── 长按
├── 拖拽
├── 抚摸
├── 推
├── 靠近
└── 离开

键盘：
├── 打字
├── 快捷键
└── 特定按键

窗口：
├── 打开
├── 关闭
├── 移动
└── 切换

声音：
├── 用户说话
├── 环境声音
└── 音乐

时间：
├── 早晨
├── 下午
├── 晚上
└── 深夜
```

然后这些全部进入：

> **Interaction Event Bus**

---

# 十、这样你甚至可以做“她自己走路”

比如桌面：

```text
┌───────────────────────────────────────┐
│                                       │
│               Furina                  │
│                 🧍                    │
│                                       │
│                                       │
│                                       │
│────────────── Taskbar ────────────────│
└───────────────────────────────────────┘
```

她有一个：

```text
x
y
direction
speed
target
```

例如：

```text
target = screen_edge
```

然后：

```text
Pathfinding
 ↓
walk_left animation
 ↓
x -= speed
 ↓
到达目标
 ↓
idle
```

甚至可以：

> 她发现你打开了 VS Code。

然后：

```text
桌面
 ↓
发现 VS Code
 ↓
走到 VS Code 窗口
 ↓
停下来
 ↓
看着你
```

---

# 十一、我特别建议：不要让 GIF 控制位置

GIF 只是：

> **动作表现层**

位置由程序控制。

例如：

```text
Character
{
    x: 1250,
    y: 700,

    state: "walking",

    direction: "left",

    emotion: "happy",

    target: {
        x: 900,
        y: 700
    }
}
```

Renderer：

```text
state = walking
direction = left

→ 播放 walk_left 的帧
```

这样她才能真正走遍整个桌面。

---

# 十二、甚至可以做“爬窗口”

这个会非常有意思。

比如：

```text
Chrome窗口
┌───────────────────────────┐
│                           │
│                           │
│                           │
└───────────────────────────┘
```

她可以：

```text
桌面
 ↓
走到窗口
 ↓
跳上窗口边缘
 ↓
沿着窗口顶部走
 ↓
坐下来
```

这里根本不需要复杂动画。

只需要：

```text
Window Boundary
+
Character Position
+
几套动作帧
```

就可以产生非常强的空间感。

---

# 十三、你的素材库最好不要按“动画”组织

不要：

```text
吃饭.gif
睡觉.gif
摸头.gif
开心.gif
```

我建议：

```text
assets/

body/
├── standing/
├── sitting/
├── lying/
├── walking/
└── running/

face/
├── neutral/
├── happy/
├── proud/
├── angry/
├── sad/
├── surprised/
└── sleepy/

gaze/
├── left/
├── right/
├── up/
├── down/
└── user/

micro/
├── blink/
├── sigh/
├── hair/
├── hat/
├── stretch/
└── yawn/

actions/
├── eat/
├── drink/
├── read/
├── type/
├── play/
├── sleep/
└── talk/
```

这会让你以后扩展非常容易。

---

# 十四、然后最重要的一点：不要试图“准备所有状态”

这是一个陷阱。

如果：

```text
10 姿势
× 10 表情
× 10 视线
× 10 动作
```

就是：

**10,000 个状态。**

你不可能全部画。

所以一定要：

> **基础状态 + 局部动作 + 状态转移**

而不是：

> 所有可能情况都做一张图。

---

# 十五、一个很实用的折中

你可以把角色拆成：

```text
身体 PNG
头发 PNG
脸 PNG
眼睛 PNG
嘴巴 PNG
手 PNG
道具 PNG
```

然后简单进行**2D图片层叠**。

这不需要 Live2D。

例如：

```text
        hair
          ↓
        head
          ↓
        eyes
          ↓
        mouth
          ↓
        body
          ↓
        arms
          ↓
        object
```

然后程序控制：

```text
eyes → look_left
mouth → smile
head → rotate +2°
arm → position
```

这其实已经非常接近一个“简易自制 Live2D”。

但你不需要购买 Live2D。

---

# 十六、如果你想要最高性价比，我会采用：

### **PNG 图层 + 少量多帧动画 + 状态机 + AI**

而不是：

### ❌ 全部 GIF

因为 GIF 最大的问题是：

> **不可组合。**

而 PNG 图层：

> **可组合。**

---

# 十七、最终系统我会定成这样

```text
                    ┌──────────────┐
                    │      LLM     │
                    │  芙宁娜人格  │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ Life Engine  │
                    │              │
                    │ 心情         │
                    │ 饥饿         │
                    │ 精力         │
                    │ 无聊         │
                    │ 社交         │
                    │ 关系         │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ Intent Engine│
                    │              │
                    │ 我想做什么？ │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │Behavior Engine│
                    └──────┬───────┘
                           ↓
             ┌─────────────┴─────────────┐
             ↓                           ↓
       Computer Agent              Character Agent
             ↓                           ↓
       操作电脑                     选择动作
                                         ↓
                                  State Renderer
                                         ↓
                                PNG / APNG / WebP
                                         ↓
                                      屏幕
```

---

# 十八、而且这套方案有一个巨大优势

**AI 和素材完全解耦。**

以后你换角色，只需要换：

```text
Persona
+
Voice
+
Assets
+
Behavior Style
```

底层：

```text
Life Engine
Interaction Engine
Computer Agent
Memory
Renderer
```

全部不用动。

所以你的架构实际上可以变成：

> **一个通用 AI Digital Character Runtime。**

芙宁娜只是第一个 Character。

---

## 我认为你这个项目真正应该追求的体验

不是：

> “哇，芙宁娜会走路！”

而是用户用电脑几个小时之后突然意识到：

> **“诶，她刚才为什么自己跑过来了？”**

然后：

> “因为我打开了 VS Code。”

再过一会儿：

> “她怎么坐在那里看着我？”

> “因为你两个小时没休息。”

然后你摸摸她的头。

她抬头看你：

> “……今天倒是知道主动来找本神了？”

**这种“因果关系”才是生命感。**

你的素材可以只有二维图片，甚至没有 Live2D；只要**行为不是预录的，状态不是固定的，互动会改变她下一步行为，她就不会像动画片。**

如果你真准备开做，我下一步最建议直接把它拆成 **「完整状态树 + 状态参数表 + 100~200 个基础动作/素材清单 + 状态转移规则 + Agent 工具架构 + Windows 实现技术栈」**，这样就可以直接拿去让 Claude Code 开工。
