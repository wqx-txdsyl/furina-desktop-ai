好，第⑤条就是整个产品从“AI 桌宠”真正进入“AI Agent”层的地方。

前四条解决的是：

1. **状态树**：她现在是什么状态。
2. **素材系统**：她有什么身体。
3. **行为系统**：她为什么做某件事。
4. **互动系统**：她如何理解用户对她做了什么。

第五条要解决：

> **她如何真正使用电脑，成为一个能够替用户完成工作的 Agent。**

而且这里有一个非常重要的产品原则：

> **不能做成“电脑 Agent + 芙宁娜皮肤”。**
>
> 用户应该感觉是：**芙宁娜本人正在使用我的电脑。**

---

# ⑤ Agent 系统 Computer Agent

## 1. 核心定义

芙宁娜的 Agent 能力不是一个独立的聊天框。

它是她的：

> **“手、眼睛和行动能力”。**

完整关系应该是：

```text
芙宁娜
│
├── Personality
│
├── Emotion
│
├── Memory
│
├── Needs
│
├── Behavior
│
└── Agent
      ├── Eyes
      ├── Hands
      ├── Browser
      ├── Files
      └── Applications
```

因此用户说：

> “帮我把这个文件整理一下。”

不是：

```text
用户 → Agent Chat → Agent执行
```

而是：

```text
用户
 ↓
芙宁娜听见
 ↓
理解请求
 ↓
判断自己能不能做
 ↓
决定接受
 ↓
制定计划
 ↓
走向电脑
 ↓
操作电脑
 ↓
观察结果
 ↓
完成
 ↓
回来告诉用户
```

---

# 2. Agent 必须拥有三种能力

## Eyes

理解电脑。

包括：

* 当前窗口
* 当前应用
* UI 元素
* 屏幕截图
* OCR
* 网页内容
* 文件结构
* 错误信息

---

## Hands

操作电脑。

包括：

* 鼠标移动
* 点击
* 双击
* 拖拽
* 滚轮
* 键盘
* 快捷键
* 输入文字
* 窗口操作

---

## Brain

决定：

> **下一步应该干什么。**

这里才是 Qwen3.8 的主要位置。

---

# 3. 三层 Agent 架构

我建议明确拆成：

```text
                    Qwen3.8
                       │
                ┌──────┴──────┐
                │   Planner   │
                └──────┬──────┘
                       ↓
                Action Plan
                       ↓
              ┌────────────────┐
              │ Agent Runtime  │
              └───────┬────────┘
                      ↓
             Tool / Computer API
                      ↓
                  Windows
```

Qwen 不应该直接控制鼠标。

而应该：

> **生成结构化行动计划。**

---

# 4. Agent 的五步循环

任何电脑任务都进入：

```text
Observe
↓
Plan
↓
Act
↓
Verify
↓
Reflect
```

例如：

> “帮我打开昨天的项目。”

### Observe

检查：

* 当前桌面
* 文件系统
* 最近文件

### Plan

```text
寻找项目目录
↓
找到项目
↓
打开
↓
确认成功
```

### Act

执行。

### Verify

检查：

> 项目是否真的打开？

### Reflect

如果失败：

> 换方案。

---

# 5. 为什么必须 Verify

传统 Agent 很容易：

```text
click
↓
认为成功
↓
继续
```

这是危险的。

例如点击：

> “保存”。

但实际上：

> 弹出了确认窗口。

如果不观察：

> 下一步就全错。

所以每一个重要 Action 后面都需要：

```text
Action
↓
Observation
↓
State Update
```

---

# 6. Agent 不应该只看截图

我建议做一个：

# Perception Hierarchy

优先级：

```text
Level 1
系统 API
        ↓
Level 2
UI Automation / Accessibility
        ↓
Level 3
DOM / Application API
        ↓
Level 4
OCR
        ↓
Level 5
Vision Model
```

原则：

> **能结构化读取，就不要截图识别。**

---

# 7. Windows UI Automation

Windows 上大量软件可以直接获得：

```text
Window
Button
Text
Input
Menu
List
Tree
```

例如：

```text
按钮：
"保存"
```

Agent 可以直接定位：

```text
role = button
name = 保存
```

而不是：

> 看截图猜“保存”按钮在哪里。

这样准确率高很多。

---

# 8. Vision 只在必要时使用

例如某个程序：

> UI Automation 什么都读不到。

这时候：

```text
Screenshot
↓
Vision
↓
理解画面
```

Qwen Vision 或其他视觉模型负责：

> “这个窗口里现在发生了什么？”

然后 Agent 再行动。

---

# 9. 鼠标操作必须有“意图”

不要让 Planner 输出：

```json
{
  "x": 783,
  "y": 412
}
```

这种方案极其脆弱。

优先：

```json
{
  "action": "click",
  "target": {
    "role": "button",
    "name": "保存"
  }
}
```

只有没有结构化目标时才退回：

```text
screen coordinate
```

---

# 10. Agent Tool 层

建议从第一版就规范成：

```text
computer
├── observe_screen
├── get_active_window
├── list_windows
├── focus_window
├── click
├── double_click
├── move_mouse
├── drag
├── scroll
├── type
├── press
└── hotkey
```

文件：

```text
filesystem
├── list
├── search
├── read
├── create
├── rename
├── move
├── copy
└── delete
```

浏览器：

```text
browser
├── open
├── search
├── navigate
├── click
├── type
├── extract
└── download
```

应用：

```text
application
├── launch
├── close
├── focus
└── inspect
```

---

# 11. 第一版不要追求“什么都能做”

这个项目非常容易掉进：

> “我要做一个万能 Computer Use Agent。”

然后最后整个项目变成 Agent 项目，芙宁娜反而没了。

第一版应该优先做：

### 文件

* 查找
* 打开
* 整理
* 重命名
* 创建文件夹

### 浏览器

* 打开网页
* 搜索
* 阅读
* 提取信息

### 办公

* Word
* PowerPoint
* Excel

### 开发

* VS Code
* 文件搜索
* 终端
* Git 基础操作

---

# 12. Agent 任务必须有“目标”

例如：

> “帮我整理桌面。”

Planner 应该先形成：

```text
Goal:
organize_desktop
```

而不是立即操作。

然后：

```text
Goal
↓
Constraints
↓
Plan
↓
Actions
```

---

# 13. 计划必须可视化

这里可以把“Agent 感”直接融入角色表现。

例如芙宁娜：

> “让我看看。”

然后旁边出现一个非常小的状态提示：

```text
正在查看桌面
↓
整理文件
↓
确认分类
```

而不是传统：

> “Executing tool…”

用户看到的是：

> **芙宁娜正在工作。**

---

# 14. 计划不能暴露成技术日志

不要：

```text
ToolCall:
filesystem.list("/Desktop")

ToolCall:
filesystem.move(...)
```

这会瞬间把角色感打碎。

用户看到：

> “我先看看你的桌面。”

必要时：

> “我发现这里有 37 个文件。”

然后继续工作。

---

# 15. Agent 与角色身体同步

这是第五条最重要的体验设计。

例如：

## 查文件

芙宁娜：

> 走到屏幕附近。

身体：

```text
walk
↓
stop
↓
look_screen
```

Agent：

```text
search_files
```

---

## 输入文字

身体：

> 看着屏幕。

Agent：

```text
keyboard.type()
```

---

## 等待

身体：

> 坐下。

Agent：

> 等待程序响应。

---

## 出错

身体：

> 皱眉 / 困惑。

Agent：

> 重新观察。

---

## 完成

身体：

> 转向用户。

芙宁娜：

> “完成了。”

---

# 16. Agent 应该拥有“工作状态”

增加几个专门的角色状态：

```text
working
thinking
observing
waiting
confused
success
failed
asking_permission
```

注意：

这些不是情绪。

例如：

```text
working + happy
working + serious
working + confused
```

可以同时存在。

---

# 17. Thinking 不能变成 ChatGPT 转圈

这是桌宠最容易出现的问题。

不要：

> 芙宁娜站着，头上显示“思考中……”

持续 20 秒。

而应该：

```text
thinking
↓
看屏幕
↓
移动
↓
尝试
↓
观察
```

**Agent 思考应该通过行动体现。**

---

# 18. Agent 任务可以被用户打断

例如：

芙宁娜正在整理文件。

用户：

> “停一下。”

立即：

```text
cancel_requested
↓
stop_current_action
↓
return_control
```

然后：

> “好。”

这非常重要。

用户永远拥有最高控制权。

---

# 19. Agent 权限系统

必须从第一版建立。

我建议四级。

## L0：只读

无需确认：

* 看时间
* 看当前窗口
* 读取公开网页
* 查看应用状态

---

## L1：低风险写入

默认允许或可设置自动：

* 创建文件
* 创建文件夹
* 修改非敏感内容

---

## L2：高风险操作

需要确认：

* 删除
* 批量移动
* 覆盖文件
* 修改重要文档
* 发送内容

---

## L3：敏感操作

必须明确确认：

* 发邮件
* 发消息
* 购买
* 修改系统设置
* 执行高风险命令

---

# 20. 权限确认也应该角色化

不要弹：

> `Allow computer.click?`

而是：

> 芙宁娜：

> “我发现这里有一个旧文件夹，里面有 126 个文件。我要把它们移动到‘旧资料’文件夹，可以吗？”

用户：

> 可以。

这才符合产品世界观。

---

# 21. Agent 的“自主权”必须有限

这是一个很重要的边界：

> **芙宁娜可以自主决定行为，但不能自主扩大权限。**

例如：

她可以：

> 自己决定去看看用户正在做什么。

但是不能：

> 自己决定读取私人文件。

她可以：

> 自己决定提醒用户。

但不能：

> 自己决定发送消息给别人。

所以：

```text
Autonomy ≠ Unlimited Permission
```

---

# 22. Agent 任务记忆

任务结束后，不应该只返回：

> 完成。

可以记录：

```text
Task
↓
Goal
↓
Actions
↓
Result
↓
User feedback
```

例如：

> 用户喜欢文件按项目分类。

下一次：

> 芙宁娜会更倾向于使用项目分类。

这就是 Agent 与记忆系统真正连接起来。

---

# 23. Agent 错误也可以形成角色体验

例如程序打开失败。

不要：

> `ERROR 0x800...`

而是：

> “诶？它好像不太愿意听我的。”

然后继续尝试。

如果真的无法完成：

> “我试了两种方法，还是打不开。你要不要自己看看？”

这样：

**失败也是角色行为。**

---

# 24. Agent 不能假装成功

这是硬规则。

如果：

```text
verify = failed
```

就不能：

> “完成啦！”

必须：

```text
failed
↓
retry
↓
alternative
↓
ask_user
```

否则信任很快就会崩。

---

# 25. Agent 的最终循环

最终我建议固定成：

```text
USER REQUEST
     ↓
UNDERSTAND
     ↓
CHECK PERMISSION
     ↓
OBSERVE COMPUTER
     ↓
PLAN
     ↓
ACT
     ↓
OBSERVE RESULT
     ↓
VERIFY
     │
     ├── success → COMPLETE
     │
     ├── recoverable → RETRY / REPLAN
     │
     └── blocked → ASK USER
```

而这个过程中：

```text
Agent Runtime
      ↕
Behavior Engine
      ↕
Character Body
```

三者一直同步。

---

# 26. 一个完整例子

用户：

> **“芙宁娜，帮我把下载文件夹整理一下。”**

### ① 理解

芙宁娜：

> “嗯？又乱成一团了？交给本神吧。”

系统建立：

```text
Goal:
organize_downloads
```

---

### ② 观察

她走向屏幕。

Agent：

```text
inspect Downloads
```

发现：

```text
PDF
Images
ZIP
Installers
Documents
```

---

### ③ 规划

Planner：

```text
create categories
↓
classify files
↓
create folders
↓
move files
↓
verify
```

---

### ④ 执行

她看着屏幕。

文件不断移动。

如果执行时间较长：

> 她坐下来等待。

---

### ⑤ 出现异常

发现：

> 某文件正在被占用。

芙宁娜：

> “这个文件好像不肯走。”

Agent 换方案。

---

### ⑥ 完成

她从窗口旁走回来。

> “好了。”

然后：

```text
Task success
↓
Memory
```

记住：

> 用户接受这种整理方式。

---

# 27. 这样一来五个系统开始闭环

到现在：

```text
① State
        ↓
② Assets
        ↓
③ Behavior
        ↓
④ Interaction
        ↓
⑤ Agent
```

真正的循环已经出现：

```text
用户做事
 ↓
Computer Perception
 ↓
芙宁娜理解环境
 ↓
产生内部状态变化
 ↓
Behavior Engine
 ↓
决定是否介入
 ↓
Agent
 ↓
操作电脑
 ↓
用户看到结果
 ↓
用户与她互动
 ↓
Interaction Engine
 ↓
Memory
 ↓
下一次行为发生变化
```

这已经不是普通桌宠的架构了。

---

# 28. 第五条的十条硬规则

我建议直接定死：

**① Agent 是芙宁娜的行动能力，不是独立聊天机器人。**

**② Qwen3.8 负责理解、规划和复杂决策，不直接操纵鼠标。**

**③ Agent 必须遵循 Observe → Plan → Act → Verify → Reflect。**

**④ 优先使用结构化 UI/API，截图视觉识别作为后备。**

**⑤ 所有重要操作必须验证结果。**

**⑥ Agent 行动必须与角色身体行为同步。**

**⑦ Agent 可以自主行动，但不能自主扩大权限。**

**⑧ 高风险操作必须经过用户确认。**

**⑨ 任务失败必须真实反馈，禁止假装完成。**

**⑩ Agent 的任务经历可以进入芙宁娜的长期记忆，并改变未来行为。**

---

## 第五条定完以后，有一个很关键的变化

前四条里的芙宁娜主要是：

> **“生活在你的电脑里。”**

第五条以后，她开始：

> **“能够参与并影响你的电脑生活。”**

例如她可以自己走到 VS Code 旁边、发现你卡在一个报错上，然后**是否主动帮助你**，这个决定仍然来自第三条 Behavior Engine；一旦你同意，她才通过第五条 Agent 系统真正动手。

所以这五层现在已经形成非常漂亮的关系：

> **状态决定她是什么样的人。**
>
> **素材决定她有什么身体。**
>
> **行为决定她想做什么。**
>
> **互动决定你们如何互相影响。**
>
> **Agent 决定她能用这台电脑做什么。**

**下一条第⑥条就应该解决“记忆系统”。**
而且我认为这一条会比普通 RAG/聊天记忆复杂得多——因为我们不是要让她“记得聊天内容”，而是要让她真的拥有一段**和用户共同生活过的历史**。
