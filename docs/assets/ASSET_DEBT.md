# ASSET_DEBT（Phase 13）

本文件集中记录**已确认、已隔离、且明确 DEFERRED（非 Phase 13 阻断项）** 的素材缺口。
Asset Presentation 在 Phase 13 全面冻结；**本阶段不生成/重绘任何 PNG / CG / 动画素材**。

| Item | Status | Reason | Phase 13 blocker? | Owner |
|---|---|---|---|---|
| walk 素材 | KNOWN / CONFIRMED / DEFERRED | manifest 无 `action=walk` 序列/姿势；移动只有位移 + DEGRADED_WALK_VISUAL | NO | Future Visual phase |
| drag 素材 | KNOWN / CONFIRMED / DEFERRED | manifest 无 `action=drag`；拖拽仅 DEGRADED_DRAG_VISUAL | NO | Future Visual phase |
| read 渲染内容退化 | KNOWN / CONFIRMED / DEFERRED | `furina_standing_focus_front_read_01` 只是站姿（无书）；metadata 命中外形不符 | NO | Future Visual phase |
| think 渲染内容退化 | KNOWN / CONFIRMED / DEFERRED | `furina_standing_thoughtful_front_think_01` 只是站姿（无思考手势） | NO | Future Visual phase |
| play/drink/wave 等内容待核 | KNOWN / DEFERRED | 依赖 UI 逐步人工核（eat 已确认有真实 cookie） | NO | Future Visual phase |

状态原则：

```text
KNOWN          —— 已被真实轨迹/视觉模型确认存在
CONFIRMED      —— 非猜测（有证据）
DEFERRED       —— 本阶段不处理
NOT PHASE13 BLOCKER —— 不阻塞 Functional Digital Life 判定
```

**重要**：这些缺口不影响 Phase 13 判定"数字生命是否成立"。Phase 13 只证明
Life / Dialogue / Interaction / Relationship / Memory / Feeding / Spatial / Agent / Failure 的真实因果。
视觉表现是后续独立层。
