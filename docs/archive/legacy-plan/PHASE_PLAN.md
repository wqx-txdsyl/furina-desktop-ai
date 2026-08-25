# 芙宁娜桌面伙伴 —— 完成顺序计划（Phase Plan）

> 依据 `PRD.md` + `legacy-plan/0~8`。**修正**：文档中的 “Qwen3.8” 实际为 **智谱 GLM**（`.env` 的 `ZHIPU_API_KEY`；默认 `glm-4v-flash`，免费，视觉+对话，已实测能识别基座图）。
> `legacy-plan/8` 对 “Qwen 的要求” 是**写代码的工程约束**，作为开发铁律遵守。
> 资产由 **Agnes AI**（`agnes-image-2.1-flash` 图 / `agnes-video-v2.0` 视频）基于 `furina-base.png` 生成，当前 $0。

## 里程碑：先最小垂直切片，再扩展（legacy-plan/8 §“build smallest working vertical slice first”）

| 相位 | 内容 | 对应 plan | 交付物（可验收） | 状态 |
|---|--|--|--|--|
| **M0** | 全模块代码骨架（空壳） | ①-⑧ 接口 + ⑧ §11 | 可运行，透明桌面窗口 + 事件总线 + 生命循环 + 全部子系统接口；53 模块 0 导入错误；15 单测通过；`--smoke`/`--selfcheck` | ✅ 完成 |
| **M1** | 素材引擎 ② + 首批真实资产 | ②全文 | 生成 21 张姿态/表情/视线/动作资产（PMT + Manifest + Resolver + QC） | ✅ 完成(21 基础批) |
| **M1.5** | **多帧动画（流动感）** | ②§7-L4,⑦§19-21 | walk/eat/stand↔sit/play 等**多帧序列**+AnimationController(fps/loop/中断)+跨帧过渡 | 🔄 进行中 |
| **M1** | 素材引擎 ② + 首批真实资产 | ②全文 | 17 个核心语义资产(站/坐/躺/睡/表情/视线,生活化,软边抠图) + Manifest + Resolver | ✅ 完成(17 基准,身份一致过) |
| **M1.5** | **多帧动画（流动感）** | ②§7-L4,⑦§19-21 | AnimationController(fps/loop/中断/呼吸)+跨帧；真实帧序列被 Agnes Video 503 卡住 | 🔄 机制就绪,出帧待 Video 恢复 |
| **M2** | 状态机 + 生命循环细化 ①③ | ①,③ | 五维状态 + Utility + 打扰/冷却 + 时长滞回 + **行为链**(e→rest, observe→approach) | ✅ 核心完成 |
| **M3** | 互动引擎细化 ④ | ④ | 摸头/拖拽/戳 + 情绪/台词反应 + **喂食**(蛋糕/茶/面包,饥饿↓满足↑) | ✅ 摸/拖/戳/喂已通 |
| **M4** | Windows 世界/运行时 ⑦ | ⑦ | 小窗模型(整窗 move,拖拽稳定) + 窗口感知 + **主动走向活动窗口/坐下陪伴** | ✅ 核心完成 |
| **M5** | LLM 大脑 + 人格 + 对话 | ⑥§13,⑧ | Zhipu glm-4v-flash 结构化 + Persona + 对话气泡(右键菜单触发) | ✅ 大脑/对话 core 已通 |
| **M6** | 记忆引擎 ⑥ | ⑥ | 四层记忆 + 形成评分/检索/关系 + 生活记忆(喂食/互动) + memory CLI | ✅ 记忆 core 已通 |
| **M7** | Computer Agent ⑤ | ⑤ | 工具(fs list/mkdir/organize/read,app.launch,browser) + Observe→Plan→Act→Verify→Reflect + 权限四级 | ✅ 核心(文件/启动/浏览) |
| **M8** | Director ⑧ + 加固 + 打包 | ⑧,⑦§52 | Action Queue 唯一仲裁 + A-8 冲突用例测试(5条) + 离线韧性 | 🔄 仲裁/测试已做,打包待办 |

## 当前进度

> **已按 whale-girl 校准（用户指导）：**
> - 桌面窗口 = **小窗模型**（整窗 move，拖拽稳定、无拖影、无 setMask 闪跳）。
> - **景深/浮层** = whale-girl `drop-shadow(0 4px 6px rgba(0,0,0,.25))` 沿剪影淡投影（非描边/鬼影）。**此条已完成**（原“待最后”项已落地）。
> - **呼吸** = 每帧重绘 + 上下浮动（可见；之前是窗口只按 3s tick 重绘导致看不见）。
> - 状态调试叠层默认隐藏（`FURINA_DEBUG=1` 才显示）。
> - 画风方向：已把生成 prompt 改为**扁平赛璐璐 2D 精灵**（当前资产仍为厚涂，待用户允许时重生成）。

- **M0 骨架、M1 资产、M2 状态+行为链、M3 互动+喂食、M4 小窗+窗口感知、M5 大脑、M6 记忆、M7 Agent(文件/启动/浏览)、M8 Director 仲裁** 均已落地并通过测试。
- **测试**：56 个单测通过（skeleton/assets/agent_tools/director/brain/animation/feeding/state）。
- 运行：`python main.py`（窗口）、`--selfcheck` / `--smoke`、`python -m pytest tests/`。

## 待办
- **多帧动画**：等 Agnes Video 关键帧接口恢复（曾 503），或换能出无背景序列的工具。
- **M8 打包**（PyInstaller 等）与**最终验收**：按“先对 plan/ 核对 → 再对照 final test.md(A/B) → 交人实测”执行。
- 未来可加：Agent 浏览器自动化/Office、记忆查看 UI、更丰富微动作。
- 运行：
  - `python main.py --selfcheck` —— 模块自检（无 GUI）
  - `python main.py --smoke` —— 启动窗口 1.5s 自动退出（无崩溃）
  - `python main.py` —— 启动透明桌面窗口（骨架占位图）
  - `python -m pytest tests/` —— 单元测试

## 工程铁律（legacy-plan/8，紧随）

1. Event-driven；模块间显式事件/接口，不直接互调。
2. **Director 是唯一允许解决竞态动作的模块**。
3. State/Behavior/Interaction/Agent/Memory/Runtime 逻辑分离。
4. LLM 输出必须结构化、schema 约束；**禁止**解析自由文本控制应用。
5. LLM 只用于高价值推理/对话/规划/反思；**不用**于高频渲染/动画/输入/简单状态更新。
6. LLM 不可用时基础生命循环照常运行。
7. Agent 遵循 Observe→Plan→Act→Verify→Reflect；**未验证不得宣称成功**。
8. 自主行为不得绕过用户权限边界。
9. 动画是表现层，不是行为的来源；视觉动作由语义状态/动作数据驱动。
10. 记忆分裂：显式事实 / 观察 / 事件经验 / 语义知识 / 关系状态；推测不得默认成事实。
11. 系统可调试：重要事件、状态转移、动作决策、Agent 操作可追踪。
12. 偏好简单显式代码，不过度抽象/继承/魔法分发/自我修改。
13. 先做最小可用垂直切片，再扩展；不新增架构不需要的产品子系统。

## 关键技术选型（已确认）

- **桌面运行时**：Python 3.13 + PySide6（透明无边框置顶、`setMask` 点击穿透、QPainter 合成、DPI）
- **LLM**：智谱 GLM，默认 `glm-4v-flash`（免费，视觉+对话），拔插型（`llm/` adapter），可切 `glm-4.5-air` 等
- **资产生成**：Agnes AI（`agnes-image-2.1-flash` / `agnes-video-v2.0`），基座图 `furina-base.png` 做图生图身份锚点
- **记忆**：SQLite 结构化 + 向量（骨架已预留 embedding 列）
- **窗口感知/Agent**：ctypes user32（免 pywin32），工具层后续接 UIA/浏览器自动化
- **语音(PRD 提到)**：`ZHIPU_API_KEY` 下未发现明确 TTS/ASR 端点，列为后续可选，先以文本气泡落地
