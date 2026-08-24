# 芙宁娜桌面伙伴 · AI Character Runtime

一个**真正活在 Windows 桌面上的 AI 芙宁娜**：拥有身体(资产)、情绪、需求、记忆、行动意图与电脑操作能力。
以 **PNG/多帧资产 + 程序控制 + 状态模型** 驱动，不依赖 Live2D。

> 完整工程细节见 `plan/0~8` 与 `PHASE_PLAN.md`（完成顺序计划）。
> **注意**：文档里的 “Qwen3.8” 实际是 **智谱 GLM**（`.env` 的 `ZHIPU_API_KEY`）；`plan/8` 对 “Qwen” 的要求是写代码的工程约束，已作为铁律落地。

## 架构总览

```
                    ZHIPU GLM (reason / plan / 对话 / 视觉, 结构化输出)
                         │
          ┌──────────────▼──────────────┐
          │         DIRECTOR            │ ⑧ 唯一仲裁：action queue/优先级/中断
          └──┬──────────┬──────────┬────┘
 STATE ① BEHAVIOR ③        INTERACTION ④        ASSETS ② (Agnes AI)
          └──────────┼──────────┘
                  ACTION QUEUE
                     │
            CHARACTER RUNTIME ⑦ (PySide6 透明桌面层)
          ┌──────────┴──────────┐
      ANIMATION             POSITION / WORLD
                     │
             RENDERER → WINDOWS 桌面
      MEMORY ⑥ (SQLite+向量)    AGENT ⑤ (工具/权限/Planner)
```

## 代码包结构

```
furina/
├─ runtime/    透明窗口、渲染、世界/坐标、调度、输入、窗口感知、素材管理
├─ state/      五维状态模型 Life/Emotion/Needs/Attention/Intent
├─ behavior/   Utility AI + 行为状态机 + 打扰成本/冷却/中断
├─ interaction/ hitbox/锚点、手势识别 → InteractionEvent
├─ memory/     四层记忆、形成/巩固/检索、SQLite+向量
├─ agent/      工具、权限(四级)、Planner、Observe→Plan→Act→Verify→Reflect
├─ assets/     Manifest、Resolver、Agnes 生成客户端、QC、命名规范
├─ director/   Action Queue + 唯一仲裁
├─ llm/        可拔插 adapter（默认智谱 glm-4v-flash，视觉+对话）
├─ persona/    芙宁娜人格库 + 组合式 prompt
├─ config/     .env 加载、AppConfig、模型档
core/          事件总线、时钟(三档Tick)、日志、错误
```

## 如何运行

```bash
pip install -r requirements.txt

python main.py --selfcheck     # 模块自检（不启动 GUI）
python main.py --smoke         # 启动窗口 1.5s 自动退出（验证渲染）
python main.py                 # 启动透明桌面窗（whale-girl 式小窗）
python -m pytest tests/        # 单元测试（56 项）
```

> 右键她：对话框（大脑回复）/ 随手帮忙（整理下载、打开记事本）/ 喂她（蛋糕/茶/面包）。

## 配置（`.env`）

```ini
ZHIPU_API_KEY=...     # 智谱 GLM（LLM 大脑 + 视觉）
AGNES_API_KEY=...     # Agnes AI（素材/动画生成）
# 可选：FURINA_LLM_MODEL=glm-4.5-air   （切换拔插模型）
```

## 状态

见 `PHASE_PLAN.md`。当前 **M0 骨架完成**，下一步 **M1：用 Agnes 从基座图生成首批真实资产**。
