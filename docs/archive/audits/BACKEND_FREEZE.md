# Backend Freeze Declaration

> Phase 10 — Character Runtime Contract / Backend Integration Freeze
> 版本：schema v1.0（`SCHEMA_VERSION = "1.0"`）
> 状态：**BACKEND RC1 — FINAL FREEZE**（Phase 10.5-Closeout 完成，BLOCKER 已解，重新签署）

---

> **RC1 修订记录**（Phase 10.5-Audit 发现并已修复）：
> - **B1 已解**：MemoryStore 跨线程（`check_same_thread=False` + `RLock`），LifeBrain 后台线程不再静默降级。
> - **S1 已修**：Relationship 单一写入口 = `RelationshipEngine.apply()`；移除 Memory→Relationship 旁路。
> - **S4 已弃用**：`body_snapshot()` → deprecated，正式接口 `current_frame()`。
> - **已接受为 debt 不改**：S2（四层行为防重复重叠）、S3（identity 双重确定性 appraise）、72h 独立跑、memory relevance 精化、glm 对话略平。

---

## FROZEN（后端冻结模块清单，§46）

以下模块自本声明起**冻结**。原则上不新增/重构其机制（Needs / Emotion / Personality / Identity /
Relationship / Memory / World / Motivation / Feasibility / LifeBrain / Dialogue / Embodiment）：

- state（`furina/state`）— Needs / Emotion / Macro / Attention / Intent / CharacterState
- emotion（`furina/emotion`）— 情绪维度与事件增量
- behavior / motivation / outcome（`furina/behavior`）— 行为选择 / Personality / Outcome
- personality（`furina/persona.furina_persona`）— 行为人格（β 权重）
- character identity（`furina/persona.character_identity`）— 四层身份 / trait_activation
- relationship（`furina/relationship`）— 长期 + 短期关系维度（**单一写入口 RelationshipEngine.apply**）
- memory（`furina/memory`）— episodic memory / retrieval（**线程安全**）
- world / world_perception（`furina/world_perception`）— 世界感知 / affordance
- feasibility（`furina/behavior` 内 affordance/feasibility）
- life brain contract（`furina/life_brain` + `furina/director`）— 生命决策契约
- dialogue expression（`furina/dialogue` + `furina/dialogue_brain`）— PersonaMode / DialogueAct /
  ExpressionStrategy / Validator / GodCalibrationGate
- embodiment（`furina/embodiment`）— BodyExpressionState / EmbodiedExpressionEngine / BodyValidator
- runtime frame schema v1（`furina/runtime/frame.py`）— `CharacterRuntimeFrame`（immutable, versioned）

## 唯一前端契约（§2-§19）

前端原则上只消费 **`CharacterRuntimeFrame`**（`furina/runtime/frame.py`），不再分别读取：

```
CharacterState / derived_visual_state / body_snapshot / Dialogue result / Activity / Renderer semantics
```

统一由 `RuntimeFrameBuilder.build(...)` 产出，经 `CHARACTER_FRAME_UPDATED` 事件发布。
- immutable snapshot（frozen dataclass），前端不可反向改后端。
- 只含语义 intent，**不**含素材文件名 / 帧索引 / 坐标 / prompt / memory / key。
- debug 可完全关闭；普通前端不依赖 debug 字段，**不**读内部 Needs。
- 视觉路径：`Frame.body → RendererAdapter → 旧 Renderer`（双轨已收敛）。
- 前端唯一接口：`current_frame()`；`body_snapshot()` 已 deprecated（Phase 11 禁用）。

## Allowed Future Changes（解冻后允许/后续阶段）

以下属于**前端/表现层**，不在 Backend 冻结内（§48）：

- Animation Runtime（帧播放 / 插值 / micro 播放）
- Asset Resolver enhancement（best-available 素材选择）
- Desktop Spatial Runtime / Walk / Pathfinding
- Interaction rendering / Speech bubble UX / TTS / Window UX / Product UX
- Agent capability expansion

## Unfreeze Conditions（解冻规则 §47）

后端可解冻当且仅当满足其一：

1. regression / crash（修复类 bug）；
2. 长跑证明结构性错误（state runaway / 行为塌缩 / memory 爆炸 / dialogue spam / body 塌缩）；
3. 前端 contract 无法表达必要语义（schema 缺字段，须扩展 schema_version）；
4. 用户核心体验出现**无法由表现层解决**的问题。

**以下不是解冻理由**：
- "感觉不够聪明" / "动画不够丰富" / "角色有点呆" — 这些属于前端表现问题。

## Freeze Calibration（本阶段允许的一次小校准）

本阶段只做了一次 Dialogue 小校准（`furina/dialogue/god_calibration.py`）：
- "本神" 情境化：`preferred`（PROUD / PLAYFUL / PERFORMATIVE + BOAST / TEASE / CELEBRATE）、
  `suppressed`（SINCERE / RESPONSIBLE / VULNERABLE + 严肃帮助）、`neutral`（普通）。
- 机制只有 allowed / preferred / suppressed；**绝不** `if proud: force "本神"`。
- cooldown 属短期 Dialogue runtime，**不**写入 Memory。
- 重开 Dialogue 大改不在本声明授权内。

## Accepted Tech Debt（RC1 确认，不修）

- S2：四层行为防重复重叠（`_category_penalty` / `_activity_penalty` / `_observation_crush_guard` /
  `LifeBrain._apply_variety` / `Scheduler._anti_collapse`）—— 属行为分布敏感，改动会重开已冻结因果实验，**不动**。
- S3：identity 双重确定性 appraise（`_appraise` 与 `build_snapshot`）— 只读冗余，无行为影响，**不动**。
- 72h 独立 smoke（将以 24h surrogate + RC1 真实线程路径覆盖，不扩展）。
- memory relevance 精化。
- glm 对话略平（属前端/模型表现）。

