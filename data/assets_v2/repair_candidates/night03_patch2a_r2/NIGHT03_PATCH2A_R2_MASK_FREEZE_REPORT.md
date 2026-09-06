# NIGHT03_PATCH2A_R2_MASK_FREEZE_REPORT — Complete Frozen Semantic Mask Gate

- patch_id: `NIGHT03_RECOVERY_PATCH2A_R2`
- base_sha: `98987c90e260fb4df500c3303c70d2b5ae82dde8`（R1 提交，Reviewer Gate 基线）
- branch: `feature/night03-recovery-patch2`（同一独立 worktree `F:\program\Python\furina-night03`）
- builder: GLM-5.3-Flash / ZCode（任务书 NIGHT03_RECOVERY_PATCH2A_R2，Reviewer: ChatGPT Codex）
- date: 2026-09-06
- scope: 修正 R1 五项 blocker；a01/a05 mask 与 R1 逐位一致；a16 保护区独立重构造 + cane/chair 完整化 + 强制 cutout 证据；零候选、零生成、零 master/BASE/production 改动

## 1. 对 R1 五项 blocker 的修正

| R1 blocker | R2 修正 |
|---|---|
| 保护区仍是 `& ~exclusion` 等价自证 | 新增独立函数 `build_protected_masks(master, declarations)`——纯**包含式**构造：每个保护对象由"声明区盒 × 正向色彩类（dark_fabric/blue_violet/skin/gold/white/tint）× 种子组件/区内全部≥阈值组件"正识别；全函数零 `~cane`、零 `~chair`、零 `~allowed`、零 `~exclusion`、零任何 removal 引用。保护区先冻结，edit 后构造，edit 不修改保护区 |
| 验证器目录被旧目录覆盖 | R2 验证器唯一根变量 `PATCH2_R2 = .../night03_patch2a_r2`，无候选扫描实际扫描 R2（自测 2 证明：放入 candidate-like PNG → 检出 → 删除） |
| a01 残留账目不闭合（1291 vs 1266，25px/9 域 <8px 被跳过） | 分类器取消 `<8px` 跳过，全部 1291px 逐组件入账（residual_components 表含每一组件 px/bbox/class），`residual_total == sum(classes)` 由验证器强制 |
| a16 cane 不完整（漏金顶、青色嵌片、黑轮廓/内线、部分尖端） | cane 重构为三走廊多色完整语义 mask：珠头盒(白|金|cyan)+握把护环盒(金|白|cyan|deep/mid_blue，包含式，内部深色=手套手指不吸收)+刃盒(deep/mid_blue|silver|cyan|outline_dark|blade_highlight + 蓝暗描边带半径5)；珠头/刃部 fill_holes 让 enclosed 结构随杖走 |
| a16 chair 不完整（仅深色核心，亮木纹/AA/左缘椅面未授权） | chair 重构：暖木全亮域（r-g 14-50、r-b≥14、bright≤210）+ 椅身暗描边带（dilate5, r≥g, bright≤130）+ 座面亮棱高光带（dilate5, bright≥170, |r-g|≤30）；人体带只保护皮肤/袜带（不裁可见椅面）；三语义组件种子不变 |

R1 已确认项保持：a01 下卷（ymax 1363）、a05 逐位、a16 飘带结构性排除、hair_reconstruction=∅（右发/杖头零接触证据保留）。

## 2. 冻结指标（px）

| mask | a01（=R1 逐位） | a05（=R1/2A 逐位） | a16 |
|---|---:|---:|---:|
| tail_source / old_tail_removal | 22933 | 46616 | 30231 |
| tail_destination | 22316 | 25509 | 10801 |
| seam_reconstruction | 2053 | 0 | 769 |
| authorized_cleanup / speck_cleanup | 2 | 465 | 135 |
| chair_removal | — | — | 13804 |
| cane_removal | — | — | 9223 |
| hair_reconstruction | — | — | 0（维持） |
| hand_reconstruction | — | — | 1013 |
| protected_existing_hair | 320071(a01 identity) | 291901 | 62279（含式：发色+帽+脸） |
| protected_costume | 203199 | 170165 | 99580（逐件正向组件） |
| protected_props | 2578 | 6378 | — |
| protected_quill_paper | — | — | 8802（羽=淡青类+纸=白类） |
| protected_glove_gold_cuff | — | — | 16658（手套暗色组件含fill+金袖口+白褶边） |
| allowed_edit（并集） | 49941 | 72590 | 64266 |

a16 protected 全部为**包含式正识别**：hair=发区 tint 组件≥150；hat=暗色组件≥100+fill；face/quill/paper/glove/cuff/frill 同法；costume=11 件逐件（dress/sleeve/bow/shorts/thigh/garter/calf/sock/shoe/coattail_r/sash）区盒×色类×组件≥100。

## 3. 验证

`night03_patch2a_r2_verify_frozen_masks.py` VERIFY OK + 两项 fail-closed 自测通过：

- MASK_PLAN_SHA256 canonical 重算一致：`054f0294527bdb8b150e342c6653f45ddea508257349f27dce60abf885ed1290`
- 全部 mask PNG 单通道/1024×1536/{0,255}/px/bbox/SHA256 与 plan 一致；
- `allowed_edit == ∪(terms)` 按盘上 PNG 重算成立；`allowed_edit ∩ protected_* = 0` 全成立；
- **自测 1**：向 allowed 并入 protected 内 1px → 交叠检查即检出（fail-closed 证明）；
- **自测 2**：R2 目录放入 candidate-like PNG → 扫描即检出（删除后恢复）；
- **a01 全部 mask 与 R1 byte-identical；a05 全部 mask 与 R1/2A byte-identical**（逐 mask SHA256 比对）；
- residual 总账闭合（total == Σclasses == Σcomponents，无 <8px 跳过）；
- a16 chair/cane/hand/尾 removal 对 quill/paper 原始盒侵入 = 0px；
- masters/BASE/_spec/Patch1 报告/R1 原产物位一致；R1 目录与报告逐位未动。

## 4. cutout 证据（仅证据，永不为输入）

`mask_plan/a16/` 下输出：`a16_cane_cutout_checker_{100,200,400}.png`、`a16_chair_cutout_checker_{100,200,400}.png`、`a16_cane_chair_cutout_checker_100.png`（合并全图棋盘底；另含深底/浅底 overlay）。从 master 临时将 removal mask 内 alpha 置零生成：

- 杖体/杖饰/金顶/青嵌片/黑轮廓/尖端全部消失，无悬浮碎片；
- 椅面/椅腿/描边/木纹全部消失，无内部斑点；
- 人物、服装、纸笔、手套零缺口（近保护区 2px 环带内像素一律不认领，边界 AA 记录为残留）。

## 5. 残留与已知边界（如实记录）

- a01 residual 1291px 全部分类入账（lining_boundary_AA / cane_boundary_AA / upper_fringe / corridor_boundary_AA），保守侧胜：模糊 AA 永不授权。
- a16 刃部与常礼服/缎带接触线的 1-2px 混合 AA 不认领（near_prot 环带排除），刃部暗轮廓主体已经由蓝暗描边带覆盖。
- a16 `cane ∩ hand_reconstruction`（指间握柄像素，两侧均为授权删除/补画项）如实在交集矩阵记录。

## 6. 回执

```text
PATCH_ID = NIGHT03_RECOVERY_PATCH2A_R2
BASE_SHA = 98987c90e260fb4df500c3303c70d2b5ae82dde8
BRANCH = feature/night03-recovery-patch2
CANDIDATES_CREATED = 0
GENERATION_CALLS = 0
A01_MASKS_BYTE_IDENTICAL_TO_R1 = true
A05_MASKS_BYTE_IDENTICAL = true
A01_RESIDUAL_TOTAL = 1291
A01_RESIDUAL_CLASSIFIED = 1291
PROTECTED_MASKS_INCLUSION_ONLY = true
PROTECTED_MASKS_REMOVAL_INDEPENDENT = true
A16_CANE_COMPLETE = true
A16_CHAIR_COMPLETE = true
A16_CANE_CUTOUT_CLEAN = true
A16_CHAIR_CUTOUT_CLEAN = true
VERIFIER_SCANS_R2 = true
ALLOWED_PROTECTED_OVERLAP = 0
MASK_PLAN_SHA256 = 054f0294527bdb8b150e342c6653f45ddea508257349f27dce60abf885ed1290
MASTERS_UNCHANGED = true
PRODUCTION_FILES_CHANGED = 0
UNRELATED_FILES_COMMITTED = 0
REPORT = data/assets_v2/repair_candidates/night03_patch2a_r2/NIGHT03_PATCH2A_R2_MASK_FREEZE_REPORT.md
STATUS = READY_FOR_NIGHT03_PATCH2A_R2_REVIEW
```

完成后立即停止：不开始 Patch 2B，等待唯一 Reviewer（ChatGPT Codex）审阅。
