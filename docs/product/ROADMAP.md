# Furina Desktop AI — Roadmap

> STATUS = CURRENT 官方正式路线（已确定）。
> 本文件是唯一当前路线图；历史阶段规划见 `docs/archive/legacy-plan/`。
> 不重新发明另一套 Phase 编号。状态只写 **implemented / pending**（禁止 PASS 措辞）。

## Phase 13 — Core Runtime Closure

```
Phase 13
  R2.2.1
  → Reviewer Audit
  → Windows exact-SHA CI
  → Agent Runtime Evidence
  → R3-A Physical Manual（DEFERRED BY REVIEW PROCESS）
  → CORE RUNTIME V1 FREEZE（冻结为 BACKEND RC1 基准）
```

## Phase 14 — Cognitive Foundation & Universal Agent Expansion

状态：

- **implemented**：Phase 13 Final Residual Closure（clock domain / stale recent truth /
  direct foreground active-set）
- **implemented**：Cognitive Foundation（C1-C7 七个逻辑 Store + CognitionHub + ContextAssembler +
  Consolidator + Canon Life Retrieval；`furina/cognition/`）
- **implemented**：Universal Agent Core（Capability Registry + Planner V2 + deterministic fallback；
  `furina/agent/capabilities/`）
- **implemented**：Filesystem / Documents / Application Catalog / Browser & Desktop foundation /
  Communication & Calendar provider interfaces（provider 未配置时显式 unavailable）
- **implemented**：Agent Task History（C7）integration + User Model minimum runtime integration +
  runtime integration boundary（owner ingress 冻结 bounded cognitive context）
- **pending**：Character Body / Rendering（`furina/presentation/`，见
  docs/architecture/future/CHARACTER_BODY.md，仍 PLANNED）
- **pending**：Work Willingness production refusal（本 Phase 仅 model-only 预留）
- **pending**：Integrated Manual（Manuel 状态 = **DEFERRED BY REVIEW PROCESS**）
  - 原因：Cognitive + Agent backend capability surface 正在扩展，Integrated Manual 将在后端与
    Character Body 更稳定后统一执行。

## Phase 15 — Cognitive Life（pending）

## Phase 16 — Universal Office/Life Agent 深化（pending）

## Phase 17 — Character Agency / Work Willingness 正式行为（pending）

## Phase 18 — Character Body / Rendering（pending）

## Phase 19 — Integrated Life Manual（pending）
