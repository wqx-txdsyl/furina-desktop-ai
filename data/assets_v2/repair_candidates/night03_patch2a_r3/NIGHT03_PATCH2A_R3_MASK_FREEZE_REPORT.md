# NIGHT03_PATCH2A_R3_MASK_FREEZE_REPORT — Complete Frozen Semantic Mask Gate

- patch_id: `NIGHT03_RECOVERY_PATCH2A_R3`
- base_sha: `f622831d43dd50876d1b82ef945a691625d4205f`（R2 提交，Reviewer Gate 基线）
- branch: `feature/night03-recovery-patch2`（同一独立 worktree `F:\program\Python\furina-night03`）
- builder: GLM-5.3-Flash / ZCode（任务书 NIGHT03 Recovery Patch 2A R3，Reviewer: ChatGPT Codex）
- date: 2026-09-07
- scope: a16 cane/chair 以预声明区间表重构为完整语义 mask；保护区近杖条目改用收窄后的声明盒；a01/a05 与 R2 逐位一致；零候选、零生成、零 master/BASE/production 改动
- 备注: 本报告全部指标由冻结 plan JSON 的实际值写成（无 stale metric）

## 1. 对 R2 两项视觉 blocker 的修正

| R2 blocker | R3 修正 |
|---|---|
| blade 区同色候选残留 11,343px（最大块 11,292px，(592,1155)-(721,1404)）；其中 8,841px 被 protected_costume 占用、490px 被 protected_glove 占用 | 根因=宽盒+dark_fabric 色类把杖身并进服装保护。R3:①刃部改用**预声明逐 y 区间表**（50 行 (y,x_left,x_right) 冻结常量，即分部多边形，实测自 master 蓝色刃身、排除右侧常礼服蓝边带）；②近刃保护区条目收窄至刃多边形之外——dress 盒右界 680→604、coattail_r 盒左界 695→712、sash 盒左界 695→712；③cane = 区间表∩α ∪ 握把/珠头多色组件 ∪ 蓝暗描边带(dilate4, bright≤130, 排除缎带盒与近保护区) | 
| chair cutout 遗留"骨架椅"（黑轮廓/内部线条/木色碎片） | chair 填充不再限 wood_tight：fill_holes(comp) ∧ zone ∧ α ∧ ¬near_prot（内部亮纹/暗线/AA 全部随椅走）；保留暗描边带与暖木带；填充与带均排除近保护区 2px 环带 |

## 2. 冻结指标（px，实际冻结值）

| mask | a01（=R2 逐位） | a05（=R2 逐位） | a16 |
|---|---:|---:|---:|
| tail_source / old_tail_removal | 24368 | 46616 | 30231 |
| tail_destination | 23690 | 25509 | 10801 |
| seam_reconstruction | 2053 | 0 | 769 |
| authorized_cleanup / speck_cleanup | 2 | 465 | 135 |
| chair_removal | — | — | 12560 |
| cane_removal | — | — | 13562 |
| hair_reconstruction | — | — | 0（维持） |
| hand_reconstruction | — | — | 1013 |
| protected_existing_hair | 320071(a01 identity) | 291901 | 62279 |
| protected_costume | 203199 | 170165 | 95798 |
| protected_props | 2578 | 6378 | — |
| protected_quill_paper | — | — | 8802 |
| protected_glove_gold_cuff | — | — | 15854 |
| allowed_edit（并集） | 49941 | 72590 | 66706 |

a16 protected 近杖条目收窄后：dress 盒右界 604、coattail_r 盒左界 712、sash 盒左界 712（均声明几何，非 removal 掩码扣除）；刃部区间表与三盒不相交，cane 像素不再进入服装/手套保护。

## 3. 验证（全部通过）

`night03_patch2a_r3_verify_frozen_masks.py`：

- MASK_PLAN_SHA256 canonical 重算一致：`f80ae22ccf6ee78c7d6e56206cd133aa288b4dc001e3c3236096a1cd24d78e5a`
- 全部 mask PNG 单通道/1024×1536/{0,255}/px/bbox/SHA256 与 plan 一致；并集等式成立；allowed∩protected=0 全成立；
- **a01/a05 全部 mask 与 R2 byte-identical**（逐 mask SHA256 比对）；
- residual 总账闭合（total == Σclasses == Σcomponents，无跳过）；
- **cutout 重建逐位比对**：由 master+mask 重建 cane/chair/合并 cutout，与提交的 `a16_{tag}_cutout_checker_100.png` 逐位相等（零差异像素）；
- **残留组件审计**：cane/chair 走廊内 ≥120px 同色残留组件 = 0（近保护区 2px 环带内边界 AA 除外，如实排除）；
- quill/paper 原始盒对全部 removal mask 侵入 = 0px；
- **报告指标一致性**：本报告由冻结 plan 实际值写成，验证器核对 MASK_PLAN_SHA256 与各 mask px 值均存在于报告中（stale metric 即 FAIL）；
- masters/BASE/_spec/Patch1 报告/2A、R1、R2 原产物位一致；R2 目录与报告逐位未动。

## 4. cutout 证据（仅证据，永不为输入）

`mask_plan/a16/`：`a16_cane_cutout_checker_{100,200,400}.png`、`a16_chair_cutout_checker_{100,200,400}.png`、`a16_cane_chair_cutout_checker_100.png`（合并棋盘底；另有深底/浅底 overlay 与 200%/400% 裁剪）。目检结论：杖体/杖饰/金顶/青嵌片/黑轮廓/尖端全部消失且无悬浮碎片；椅面/椅腿/描边/木纹全部消失且无骨架残留；人物、服装、纸笔、手套零缺口。

## 5. 已记录边界

- a16 刃部与常礼服/缎带接触线的 1-2px 混合 AA 不认领（near_prot 环带排除），刃部蓝暗主体已经由区间表+描边带覆盖。
- a01 residual 1291px 全部分类入账（保守侧胜策略不变）。
- a16 `cane ∩ hand_reconstruction`（指间握柄像素）如实在交集矩阵记录，两侧均为授权项。

## 6. 回执

```text
PATCH_ID = NIGHT03_RECOVERY_PATCH2A_R3
BASE_SHA = f622831d43dd50876d1b82ef945a691625d4205f
BRANCH = feature/night03-recovery-patch2
CANDIDATES_CREATED = 0
GENERATION_CALLS = 0
A01_MASKS_BYTE_IDENTICAL_TO_R2 = true
A05_MASKS_BYTE_IDENTICAL_TO_R2 = true
A16_CANE_COMPLETE = true
A16_CHAIR_COMPLETE = true
A16_CANE_CUTOUT_CLEAN = true
A16_CHAIR_CUTOUT_CLEAN = true
CUTOUT_REBUILD_COMPARISON = PASS
REPORT_METRICS_CONSISTENT = true
ALLOWED_PROTECTED_OVERLAP = 0
MASK_PLAN_SHA256 = f80ae22ccf6ee78c7d6e56206cd133aa288b4dc001e3c3236096a1cd24d78e5a
MASTERS_UNCHANGED = true
PRODUCTION_FILES_CHANGED = 0
UNRELATED_FILES_COMMITTED = 0
REPORT = data/assets_v2/repair_candidates/night03_patch2a_r3/NIGHT03_PATCH2A_R3_MASK_FREEZE_REPORT.md
STATUS = READY_FOR_NIGHT03_PATCH2A_R3_REVIEW
```

完成后立即停止：不开始 Patch 2B，等待唯一 Reviewer（ChatGPT Codex）审阅。
