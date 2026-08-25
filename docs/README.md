# Documentation Index

> 唯一 Documentation Index。所有文档从本页导航。
> 代码结构见 `architecture/PROJECT_STRUCTURE.md`；产品路线见 `product/ROADMAP.md`。

## product/ — 产品

- `product/PRD.md` — 产品需求文档
- `product/ROADMAP.md` — 当前官方正式路线（Phase 13 → 19）

## architecture/ — 架构

- `PROJECT_STRUCTURE.md` — 仓库布局 + 未来命名空间预留
- `future/COGNITIVE_STORES.md` — 认知存储预留（PLANNED）
- `future/UNIVERSAL_AGENT.md` — Universal Agent 预留（PLANNED）
- `future/CHARACTER_BODY.md` — Character Body / Rendering 预留（PLANNED）

## persona/ — 人格（当前有效）

- `FURINA_CANON_EVIDENCE.md` — Canon evidence / provenance（56 units，角色行为的原作证据来源）
- `FURINA_PERSONA_MODEL.md` — Canon Persona Model（从 Evidence 派生的统一模型）
- `FURINA_CN_VOICE_PROFILE.md` — 中文语音画像

> 区分：
> - `docs/persona/FURINA_CANON_EVIDENCE.md` = **Canon evidence / provenance**（"证据来自哪里"）
> - `furina/persona/furina_canon.py` = **Runtime canonical truth source**（"运行时唯一事实源"，
>   从 Evidence 派生；所有 Runtime Persona 必须依赖它，不得维护平行 identity truth）

> 旧 `FURINA_CHARACTER_EVIDENCE.md` 已被 Canon Evidence 完全 supersede，归档于 `archive/legacy/`。

## runtime/ — 运行时

- `SPATIAL_RUNTIME.md` — 空间运行时

## assets/ — 素材

- `ASSET_COVERAGE_V2.md` — 素材覆盖率（当前）
- `ASSET_DEBT.md` — 素材缺口
- `generation/IMAGE_GENERATION_GUIDE.md` — 图像生成指南
- `generation/ANIMATION_GENERATION_GUIDE.md` — 动画生成指南

## testing/ — 测试 / 验收

- `PHASE13_MANUAL_ACCEPTANCE.md` — Phase 13 手动验收

## archive/ — 历史（非当前真值）

- `legacy-plan/` — 旧 Plan（plan/0~8 + PHASE_PLAN.md），已退役
- `reports/` — 各 Phase delivery/report（Phase11/12/13/RC1/R2.x…）
- `audits/` — 历史 audit/freeze（BACKEND_FREEZE / BACKEND_AUDIT / DIALOGUE_CLOSEOUT）
- `legacy/` — 其他被 supersede 的文档（FURINA_CHARACTER_EVIDENCE / ASSET_COVERAGE_V1 / FINAL_TEST_V1）
