# 芙宁娜桌面伙伴 · AI Character Runtime

一个**真正活在 Windows 桌面上的 AI 芙宁娜**：拥有身体(资产)、情绪、需求、记忆、行动意图与电脑操作能力。
以 **PNG/多帧资产 + 程序控制 + 状态模型** 驱动，不依赖 Live2D。

> 文档入口见 [docs/README.md](docs/README.md)；仓库结构见 [docs/architecture/PROJECT_STRUCTURE.md](docs/architecture/PROJECT_STRUCTURE.md)。
> LLM 为智谱 GLM（`.env` 的 `ZHIPU_API_KEY`，默认 `glm-4v-flash`，视觉+对话）。

## 架构总览

```
                    ZHIPU GLM (reason / plan / 对话 / 视觉, 结构化输出)
                         │
          ┌──────────────▼──────────────┐
          │         DIRECTOR            │ 唯一仲裁：action queue/优先级/中断
          └──┬──────────┬──────────┬────┘
 STATE      BEHAVIOR    INTERACTION      ASSETS (Agnes AI 生成)
          └──────────┼──────────┘
                  ACTION QUEUE
                     │
            CHARACTER RUNTIME (PySide6 透明桌面层)
          ┌──────────┴──────────┐
      ANIMATION             POSITION / WORLD
                     │
             RENDERER → WINDOWS 桌面
      MEMORY (SQLite+向量)   AGENT (工具/权限/Planner)
```

三脑架构：LifeBrain 决定"做什么"、DialogueBrain 决定"怎么说"、Tool Agent 决定"怎么操作电脑"。

## 代码包结构

```
furina/
├─ runtime/    透明窗口、渲染、世界/坐标、调度、输入、窗口感知、素材管理
├─ state/      五维状态模型 Life/Emotion/Needs/Attention/Intent
├─ behavior/   Utility AI + 行为状态机 + 打扰成本/冷却/中断
├─ interaction/ hitbox/锚点、手势识别 → InteractionEvent
├─ memory/     记忆引擎、形成/巩固/检索、SQLite+向量
├─ agent/      工具、权限、Planner、Observe→Plan→Act→Verify→Reflect
├─ assets/     Manifest、Resolver、Agnes 生成客户端、QC、命名规范
├─ director/   Action Queue + 唯一仲裁
├─ llm/        可拔插 adapter（默认智谱 glm-4v-flash，视觉+对话）
├─ persona/    芙宁娜人格（furina_canon 唯一 Canon 源 + planner/autobiographical）
├─ config/     .env 加载、AppConfig、模型档
└─ core/       事件总线、时钟(三档Tick)、日志、错误
```

## 如何运行

```bash
pip install -r requirements.txt

python main.py --selfcheck     # 模块自检（不启动 GUI）
python main.py --smoke         # 启动窗口 1.5s 自动退出（验证渲染）
python main.py                 # 启动透明桌面窗
python -m pytest               # 单元测试（tests/）
```

> 右键她：对话框（大脑回复）/ 随手帮忙（整理下载、打开记事本）/ 喂她（蛋糕/茶/面包）。

## 配置（`.env`）

```ini
ZHIPU_API_KEY=...     # 智谱 GLM（LLM 大脑 + 视觉）
AGNES_API_KEY=...     # Agnes AI（素材/动画生成）
# 可选：FURINA_LLM_MODEL=glm-4.5-air   （切换拔插模型）
```

## 状态

Phase 13 Core Runtime Closure
