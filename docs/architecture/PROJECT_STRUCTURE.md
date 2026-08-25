# Project Structure

> STATUS = CURRENT（当前仓库结构）+ PLANNED（未来预留命名，NO IMPLEMENTATION YET）。
> 本文件是仓库布局的唯一入口；代码导航见 `docs/README.md`。

## 根目录（唯一允许的文件/目录）

```
.env.example         配置模板（真实 .env 不入库）
.gitignore
README.md            产品一句话定位 + 运行方法 + 配置 + 目录导航
pyproject.toml
requirements.txt
main.py              桌面应用入口
run_frozen.py        PyInstaller 冻结入口
furina-desktop.spec  PyInstaller 打包规格

furina/              产品核心（production modules）
data/                运行时数据（assets/、数据库；用户数据不入库）
docs/                文档（唯一索引：docs/README.md）
scripts/             工具脚本（assets/runtime/analysis/dev）
tests/               pytest 测试套件
```

## furina/（当前，原地保留）

```
furina/
├─ app.py              应用总装（Director executor / 生产入口）
├─ dialogue_brain.py   三脑：语言（DialogueBrain）
├─ runtime/scheduler.py 运行时调度器（furina/runtime/scheduler.py）
├─ brain.py            LifeBrain 决策脑
├─ life_brain.py       生命决策
├─ feeding.py          喂食系统
├─ persona/            人格包（furina_canon 唯一 Canon 源 + planner/autobiographical）
├─ memory/             记忆引擎（SQLite + 检索）
├─ relationship/       关系引擎
├─ agent/              Agent（手/眼/行动：planner/permission/tools）
├─ embodiment/         具身语义层
├─ emotion/            情感引擎
├─ behavior/           行为引擎
├─ interaction/        互动识别
├─ director/           动作仲裁
├─ runtime/            桌面运行时（spatial/frame/harness/…）
├─ state/              五维状态
├─ assets/             素材引擎（manifest/resolver/…）
├─ core/               事件总线/时钟/日志
├─ llm/                LLM adapter（zhipu / openai-compat）
└─ world_perception.py 世界感知
```

> 禁止为"目录漂亮"移动 production modules。`app.py` / `dialogue_brain.py` / `runtime/scheduler.py`
> 等重构在各自独立 Phase 处理，不在此次整理范围。

## docs/（唯一索引：docs/README.md）

```
docs/
├─ README.md            Documentation Index
├─ product/             PRD / ROADMAP
├─ architecture/        PROJECT_STRUCTURE + future/（PLANNED）
├─ persona/             当前有效人格文档
├─ runtime/             运行时文档
├─ assets/              素材文档 + generation/ 生成指南
├─ testing/             测试/验收文档
└─ archive/             legacy-plan/ reports/ audits/ legacy/
```

## scripts/（工具脚本）

```
scripts/
├─ assets/    资产生成/验证/覆盖率（generate_assets/rebuild_assets/verify_assets/…）
├─ runtime/   运行时 harness/验证/场景（runtime_harness/scenario_validation/…）
├─ analysis/  行为审计/统计（behavior_audit/behavior_stats/audit_coverage）
└─ dev/       开发辅助（chat/memory CLI）
```

## tests/

pytest 套件；`python -m pytest` 运行。新增测试按子系统命名（如 `tests/persona/`）。

---

# Future Production Namespace（PLANNED —— 仅冻结命名，NO IMPLEMENTATION YET）

以下路径**预留**给后续 Phase，本任务及当前版本**禁止创建**这些 Python package。

## furina/cognition/

```
furina/cognition/
    stores/            逻辑认知存储（见 docs/architecture/future/COGNITIVE_STORES.md）
    retrieval/         语义检索
    consolidation/     记忆巩固
    beliefs/           解释 / Belief Update
    context_assembly/  上下文组装
```

## furina/agent/（扩展）

```
furina/agent/
    capabilities/      能力域注册（见 UNIVERSAL_AGENT.md）
    integrations/      外部集成
```

## furina/presentation/

```
furina/presentation/
    body/              Character Body（见 CHARACTER_BODY.md）
    animation/         多帧动画
    rendering/         渲染
    ui/                界面
```

> 现有 `persona/` `memory/` `relationship/` `agent/` `embodiment/` `runtime/` 全部原地保留，
> 不迁移到上述命名空间。
