# NIGHT03_PATCH2A_R1_MASK_FREEZE_REPORT — Corrected Frozen Semantic Mask Gate

- patch_id: `NIGHT03_RECOVERY_PATCH2A_R1`
- base_sha: `e8311a25c7a89059c75c8f19aa9b1837e4b719e2`（Patch 2A 提交，Reviewer Gate 基线）
- branch: `feature/night03-recovery-patch2`（同一独立 worktree `F:\program\Python\furina-night03`）
- builder: GLM-5.3-Flash / ZCode（任务书 NIGHT03_RECOVERY_PATCH2A_R1，Reviewer: ChatGPT Codex）
- date: 2026-09-06
- scope: 仅修正 a01 / a16 冻结 mask；a05 逐位保持；零候选、零生成调用、零 master/BASE/production 改动

## 1. 对 Patch 2A 三项 blocker 的修正

| Reviewer blocker | R1 修正 | 结果 |
|---|---|---|
| a01 `tail_source` 漏掉下卷（1237px，(249,1321)-(314,1358)，冻结 mask 只到 y=1333） | 走廊下界 1345→1372；补种子 (280,1340)/(258,1085)/(270,1095)/(290,1310)；手套保护盒 y 上限修正 1102→1045（2A 的收窄修正未带入 R1 副本，本轮修复——该错误盒曾把尾上缘 y1052-1101 全部扣掉） | `tail_source_ymax=1363`（≥1355 达标）；a01 tail 22933→24368px |
| a16 cane 种子 (675,1140) 命中服装飘带（1844px，(622,1110)-(690,1155)） | 4× 探针确认该区为蓝紫缎带面料；删除该种子与其走廊；刃部候选收紧为 b-r≥65 核心色测；握把/护环盒下延至 y1230 并补种子 (672,1185) 覆盖刃领金环；cane 三部件**独立候选**（金握把/珠头白盒/蓝刃互不连通，杜绝跨部件污染） | 飘带组件结构性排除（无任何 cane 部件覆盖 (615,1105)-(695,1160)）；cane_removal=6900px |
| a16 chair = 走廊内全部木色组件（252 个连通域，含纸面/饰件/服装碎片，与 quill/paper 原始盒相交 628px） | 废弃"全部组件"规则；仅冻结三个已识别椅子组件（种子 (600,1275) 座椅板 / (594,1350) 前腿 / (677,1300) 后腿）；候选减去人体带 (475,1190)-(625,1252) 与鞋袜区 (390,1390)-(560,1470)；fill 限 wood_tight | chair_removal=11374px，**组件数=3**（与可见椅子结构一致）；`chair_raw_quill_paper_box_px=0` |

结构性修正：**全部 protected mask 独立构造**——由声明区盒 × 独立色彩类（wood_tight / blade_blue / gold_c / white_c / shaft_c / dark_c）合成，不再引用任何 removal mask（无 `raw & ~cane & ~chair` 等价扣除）；`allowed_edit ∩ protected_* = 0` 由验证器独立复核，且验证器对 chair/cane/hand 侵入 quill/paper 原始盒 1px 即 FAIL。

## 2. 冻结指标（px）

| mask | a01 | a05（逐位=2A） | a16 |
|---|---:|---:|---:|
| tail_source / old_tail_removal | 24368 | 46616 | 30246 |
| tail_destination | 23690 | 25509 | 10801 |
| seam_reconstruction | 2053 | 0 | 769 |
| authorized_cleanup / speck_cleanup | 2 | 465 | 135 |
| chair_removal | — | — | 11374 |
| cane_removal | — | — | 6900 |
| hair_reconstruction | — | — | 0（维持空声明，右发/杖头零接触证据保留） |
| hand_reconstruction | — | — | 1637 |
| protected_identity / existing_hair | 320071 | 291901 | 175805 |
| protected_costume | 203199 | 170165 | 138949 |
| protected_props | 2578 | 6378 | — |
| protected_quill_paper | — | — | 21855 |
| protected_glove_gold_cuff | — | — | 10661 |
| allowed_edit（并集） | 49941 | 72590 | 60444 |

a05 九个 mask 的 SHA256 与 e8311a2 冻结值逐一相等（验证器 6b 检查 VERIFY OK）；allowed_edit 未扩大（72590 不变）。

a16 hand_reconstruction 独立重声明：不再使用 `cane ∩ broad_fist_box`；新定义为声明指缝亮带 (715,1035)-(750,1148) ∩ α ∩ gold_c（握柄奶油色像素，即拔杖后指间必须补回的区域），不含杖头、飘带与透明背景。

## 3. 验证

`night03_patch2a_r1_verify_frozen_masks.py` VERIFY OK：

- MASK_PLAN_SHA256 canonical 重算一致：`9bba785efe52a7b3158d45ad958657d6317fdf0aacbf11af0460e650b4726d9d`
- 全部 mask PNG 单通道/1024×1536/{0,255}/px/bbox/SHA256 与 plan 一致；
- `allowed_edit == ∪(terms)` 按盘上 PNG 重算成立；`allowed_edit ∩ protected_* = 0` 全成立；
- `tail_destination` 全部落在现存透明像素；masters/BASE/_spec/Patch1 报告/e8311a2 原产物位一致；
- **a05 全部 mask 与 2A 冻结值 byte-identical**；
- a16 chair/cane/hand/尾各 removal mask 对 quill/paper 原始盒侵入 = 0px；
- night03_patch2a_r1/ 下除 _inspect（无）、mask_plan 外零 PNG、零 candidate/repair 命名文件。

## 4. 已记录残留与内部交叠（非冲突）

- a16 `cane ∩ hand_reconstruction = 1418px`：指间握柄像素同时是"拔杖删除"与"补画手指"两个授权项的目标，属 allowed 内部包含，联合授权不受影响，交集矩阵如实记录。
- a16 `cane_raw_glove_zone_px = 1940`：金握把几何上必须穿过拳区盒（拳握杖）；权威检查是独立 `protected_glove_gold_cuff ∩ cane = 0`（成立）。该握把组件像素实测 x710-764，与金袖口保护区（x≤709）零重叠。
- a16 chair fill 限 wood_tight：座椅内部少量亮木纹/highlight 像素（bright>130）未认领，删除后可能留下轻微内部斑点，已记录供 2B 评估。
- a01 residual = 1266px 全部分类：lining_boundary_AA 984px + cane_boundary_AA 282px（x306-317 / x292-308 边界抗锯齿，保守侧胜策略，绝不授权删除衬里/手杖像素）；分类表与三联证据图（old | new | residual 分类）随 plan 交付：`a01_old_new_residual_triptych.png`。

## 5. 交付物（全部新增于 night03_patch2a_r1/ 下）

- `mask_plan/a01|a05|a16/`：全部黑白 mask、allowed_edit、protected masks、四底 overlay、200%/400% 高风险裁剪、a01 新旧 residual 三联图
- `mask_plan/night03_patch2_mask_plan.json`（含 MASK_PLAN_SHA256 总封印、交集矩阵、raw_zone_overlaps、residual 分类表、a05=2A SHA 记录）
- `../../scripts/assets_v2/night03_patch2a_r1_freeze_masks.py`、`night03_patch2a_r1_verify_frozen_masks.py`
- 本报告

Gate 条件核对：MASKS_PREDECLARED=true；CANDIDATES_CREATED=0；GENERATION_CALLS=0；a01 下卷不再漏选（ymax 1363）；a05 全部 mask SHA 与 e8311a2 一致；a16 cane 不含 1844px 飘带组件（结构性排除）；a16 chair 仅 3 个语义组件且不含纸笔/饰件/服装/身体；protected masks 不依赖 removal masks；allowed_edit 为授权项精确并集；allowed∩protected=0；masters/BASE/spec/Patch1 报告/e8311a2 原产物不变；production files changed=0。

```text
PATCH_ID = NIGHT03_RECOVERY_PATCH2A_R1
BASE_SHA = e8311a25c7a89059c75c8f19aa9b1837e4b719e2
BRANCH = feature/night03-recovery-patch2
CANDIDATES_CREATED = 0
GENERATION_CALLS = 0
MASKS_FROM_MASTER_ONLY = true
MASKS_PREDECLARED = true
PROTECTED_MASKS_INDEPENDENT = true
A01_LOWER_CURL_INCLUDED = true
A05_MASKS_BYTE_IDENTICAL = true
A16_FALSE_CANE_COMPONENT_REMOVED = true
A16_CHAIR_SEMANTIC_COMPONENTS_ONLY = true
ALLOWED_PROTECTED_OVERLAP = 0
MASK_PLAN_SHA256 = 9bba785efe52a7b3158d45ad958657d6317fdf0aacbf11af0460e650b4726d9d
MASTERS_UNCHANGED = true
PRODUCTION_FILES_CHANGED = 0
UNRELATED_FILES_COMMITTED = 0
REPORT = data/assets_v2/repair_candidates/night03_patch2a_r1/NIGHT03_PATCH2A_R1_MASK_FREEZE_REPORT.md
STATUS = READY_FOR_NIGHT03_PATCH2A_R1_REVIEW
```

完成后立即停止：不开始 Patch 2B，等待唯一 Reviewer（ChatGPT Codex）审阅。
