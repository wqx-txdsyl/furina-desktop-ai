# NIGHT03_PATCH2A_MASK_FREEZE_REPORT — Semantic Components + Pre-Build Frozen Mask Gate

- patch_id: `NIGHT03_RECOVERY_PATCH2A`
- base_sha: `a1586f70416add58d44891330fd8c5aad4d832cb`（NIGHT-03 Recovery Patch 1 提交，Reviewer 基线）
- branch: `feature/night03-recovery-patch2`（独立 worktree `F:\program\Python\furina-night03`，自 base_sha 新建）
- builder: GLM-5.3-Flash / ZCode（任务书 NIGHT03_RECOVERY_PATCH2A，Reviewer: ChatGPT Codex）
- date: 2026-09-06
- scope: 仅 a01 / a05 / a16；本阶段只建立并冻结修复前语义 mask，**零候选、零生成调用、零 master/BASE/production 改动**

## 1. 结果概要

三张资产的修复前语义 mask 已全部冻结并通过独立验证（`night03_patch2_verify_frozen_masks.py` → VERIFY OK）。
所有 mask 为 8-bit 单通道 PNG、取值仅 {0,255}；`allowed_edit` 恒等于各资产授权项的并集；
`allowed_edit ∩ protected_* = 0` 全部成立；`tail_destination` 全部落在 master 现存透明像素上。

```text
MASK_PLAN_SHA256 = aa366b183f6c5db1e92edcfb4145699589c6595e4481bc1720c511d7bf30aab6
CANDIDATES_CREATED = 0
GENERATION_CALLS = 0
```

## 2. 工作区隔离与输入封存

- 独立 worktree：`git worktree add -b feature/night03-recovery-patch2 F:/program/Python/furina-night03 a1586f7`；原 Phase 16/17 工作树（furina-work）零改动、零 `git add`。
- 任务书允许的四项未跟踪工件原样复制进 worktree，复制前后 SHA256 逐一核对一致（23 个文件）：
  - `data/assets_v2/repair_candidates/night03_patch1/NIGHT03_PATCH1_REVIEW_REPORT.md` = `cb4088eac01ff69cb9fba27a4f960254d6c4a8c9b2ef99da80d7d7af18ca14c2`（逐位保持，Builder 未修改）
  - `scripts/assets_v2/night03_patch2_inspect.py` = `32a2e99018a43cb88cafdb3912ff51200127574bc1590eb0fe03d1c331405744`
  - `scripts/assets_v2/night03_patch2_analyze.py` = `313682bb0923ccde75a8d6bf92a6bd1daca45578d49b123dd842759fb98ca80f`
  - `data/assets_v2/repair_candidates/night03_patch2/_inspect/`（19 张，首张 `a01_full_checker.png` = `e0e8c589b1cbd0baf4b3563d14161efc880e2e67e12d694b1f7c6c2dcc7f14cd`）
- mask 合法输入仅限：masters、BASE、冻结规范（`_spec/`）、本脚本内预声明语义坐标/人工确认组件种子。Patch 1 候选与管线零读取。

## 3. 语义组件人工确认（含探针证据）

全部坐标在 1024×1536 画布上，x 向右、y 向下。确认手段：`_inspect/` 检查图 + 4×/3×/2× 网格放大裁剪 + 逐行 run 探针 + 逐点 RGBA 采样（过程脚本在 OS temp，未入库）。

### a01（stand_neutral_front）
- **旧尾（viewer-left）**：主体发色连通域 16040px（x187-306/y1075-1300）+ 上缘（y~1052 起）+ 下卷（至 y~1355，越过了首轮评审记录的 1300）+ 内部阴影条。种子连通域 + 内部填充 + 5px 描边壳。**走廊右界硬剪裁 x≤318**：x≥323 的 y1186-1308 叶片组件实测为**常礼服条纹衬里**（首轮正是把它镜像成了"条纹碎片"blocker）——本计划把它划入 protected_costume，绝不进入尾源。
- **手杖（protected_props，2578px）**：金环握把+白玉珠（盒内 white|gold 测试，种子 (300,1060)）与饱和蓝杆芯（b-r≥60，探针实测 b-r≥60 时组件与尾零渗漏、bbox x300-332/y1178-1409）。杖在尾前，尾删除授权到杖轮廓为止。
- **cleanup**：唯一授权项 = (363,714-715) 2px 半透明暗斑（首轮评审已裁定为无害清理）。
- **seam**：左根带 (295,1000)-(330,1200) 与镜像右根带 (694,1000)-(740,1200)，仅含距现存 alpha ≤6px 的透明像素（2053px）。

### a05（stand_confident_proud）
- **旧尾**：单一发色连通域 34349px（x156-389/y921-1288）+ 描边壳。**关键边界**：尾右缘真实到达 x389（4× 裁剪逐像素确认其右为暗描边再右才是礼服），蝴蝶结保护区自 x390 起——x374-389 保留为尾、丝带零损失。
- **探测否证**：chest 区 y795-935/x380-580 的淡色块全部为马甲/胸绶带/蝴蝶结高光（礼服），尾实际自 y≈921 出现——原"尾根顶部段块"假设被像素证据否证。
- **手杖（protected_props，6378px）**：实际布局为近竖直——珠头 (810-870,755-830)、金护环 (770-800,930-1000)、蓝杆 (690-795,1000-1375)；白色测试盒限定杖头 (795,740)-(880,860)，白手套袖口不可能进入组件。
- **cleanup（465px）**：wisp 弧形碎片，实测与冻结值完全一致于首轮评审的 465px 记录；与杖杆最近间距 ~48px，无接触。
- **seam = 0（空 mask，如实冻结）**：两处声明根带的候选区全部为不透明身体/礼服像素，透明∩近alpha 采样为空——2B 的接缝处理必须完全在已删除尾像素与透明像素内进行。

### a16（work_focused）
- **旧尾**：C 形大卷（20122px x189-376/y1149-1418 + 2897px x287-380/y1171-1255），走廊 y≥1130。**探测否证**：y1035-1105/x337-398 的对角淡色带是 **quill 羽毛**而非尾（x300-345 该带外为纯透明背景）——走廊顶界因此定为 1130，羽毛由 protected_quill_paper 全保护。
- **椅子（chair_removal，16789px）**：走廊 (410,1080)-(730,1470) 内全部木头色组件的并集（座椅 5574 + 右腿 3700 + 左腿 3278 + 背柱 998 等 8 块），唯一例外是触及鞋袜区 (390,1390)-(560,1470) 的 172px 暖色碎片（鞋侧阴影，非椅子）。`fill_holes` 会把穿椅而过的刃部孔洞填入 chair（与 cane 交叠 204px，见 §6），像素在两侧均为授权删除项，零保护区冲突。
- **手持手杖（cane_removal，8795px）**：珠头白盒 (735,910)-(812,1015) 白|金 1940px + 金握把盒 (620,1000)-(780,1160) 1945px + 蓝刃两段 3835px（实测刃部沿 x≈675@y1140 → x≈607@y1430 近竖直下降；组件 bbox x608-706 未漏入右侧常礼服蓝边）。注意：**实际杖形与任务书下达前的初步目测不同**，全部盒子以探针实测校准。
- **hand_reconstruction（5031px）** = cane ∩ 拳区 (620,940)-(775,1135)，即拔杖后必须补画握区的杖占像素；**hair_reconstruction = ∅（有意为空）**：杖头 (745-807,922-1002) 与右发卷（发梢最低 y≤905、x≤775）在 master 中**零接触**（4× 裁剪 evidence `a16_righthair_pommel_200.png`，中间为透明背景）——杖头从未遮挡任何头发；首轮"头发被删"实为 Patch 1 把白色杖头误判为发色删除。该空声明是可复核的强声明。
- **speck_cleanup（135px）**：3 个声明盒内的漂浮斑点连通域 (271-288,951-961)/(271-286,1014-1027)/(305-314,1061-1076)，与首轮评审"已干净移除"记录的 70/33/32px 同源（阈值差异）。
- **保护区**：右发卷+全头部 175805px；quill+纸张 21618px；手套+金饰+袖口 20323px；礼服 145107px——均逐像素减去 cane/chair 后冻结。

## 4. 冻结 mask 清单（px）

| mask | a01 | a05 | a16 |
|---|---:|---:|---:|
| tail_source | 20995 | 46616 | 30246 |
| old_tail_removal | 20995 | 46616 | 30246 |
| tail_destination | 20378 | 25509 | 10801 |
| seam_reconstruction | 2053 | 0 | 769 |
| authorized_cleanup / speck_cleanup | 2 | 465 | 135 |
| chair_removal | — | — | 16789 |
| cane_removal | — | — | 8795 |
| hair_reconstruction | — | — | 0（有意为空） |
| hand_reconstruction | — | — | 5031 |
| protected_identity / existing_hair | 320071 | 291901 | 175805 |
| protected_costume | 206900 | 170165 | 145107 |
| protected_props | 2578 | 6378 | — |
| protected_quill_paper | — | — | 21618 |
| protected_glove_gold_cuff | — | — | 20323 |
| allowed_edit（并集） | 43373 | 72590 | 67331 |

`tail_destination` 为 `fliplr(tail_source)`（镜像轴 x=512，与 Patch 1 声明的变换一致）严格减去 master 现存不透明像素——形状即镜像组件本身，不存在任何矩形补块；a01 黑柱来源区 (676,982)-(838,1362) 内的服装/背景像素因此结构性不可能被认领。

## 5. 设计决策与已记录残留

1. **尾/衬里边界带（a01，boundary_residual=3170px）**：走廊内发色像素未被认领的部分几乎全部位于 x306-317 的尾/衬里边界抗锯齿混合带（~350px 边界上散布的 2-11px 条带）与少量距主体 >5px 的孤立碎片。策略 = **保守侧胜**：模糊像素一律留在 master 原状（宁可残留细fringe，绝不授权删除衬里像素）。a05=209px、a16=467px，同类性质。
2. **a05 seam=0**：见 §3；如 Reviewer 认定必须非空，需要任务书澄清授权范围。
3. **a16 hair_reconstruction=∅**：见 §3，证据图随附。
4. **chair fill_holes 与刃部交叠 204px**：座椅板被蓝刃穿孔，孔洞填充使 chair 与 cane 在 204px 上重叠；两侧都是授权删除项，`allowed_edit` 按并集不受影响，交集矩阵如实记录。
5. **hand_reconstruction ⊂ cane_removal**（5031px）：构造性包含，非冲突。

## 6. 交付物清单（本阶段全部新增，均在 night03_patch2/ 下）

- `mask_plan/a01|a05|a16/<asset>_<mask>.png`（每 mask 一张黑白图）
- `mask_plan/<asset>/<asset>_overlay_{master,checker,dark,light}.png`（全 mask 彩色编码 overlay ×4 种底）
- `mask_plan/<asset>/<asset>_crop_*_{2x,4x}.png`（高风险区 200%/400% 裁剪：a01×3、a05×3、a16×4）
- `mask_plan/night03_patch2_mask_plan.json`（每 mask px/bbox/SHA256、交集矩阵、并集等式验证、destination 透明性验证、boundary_residual、输入 SHA256、MASK_PLAN_SHA256 总封印）
- `scripts/assets_v2/night03_patch2_freeze_masks.py`（确定性冻结管线）
- `scripts/assets_v2/night03_patch2_verify_frozen_masks.py`（独立验证器）
- `data/assets_v2/repair_candidates/night03_patch2/NIGHT03_PATCH2A_MASK_FREEZE_REPORT.md`（本报告）

## 7. 验证结果

`night03_patch2_verify_frozen_masks.py`（只读文件重导出，不信任 Builder 缓存）：

- MASK_PLAN_SHA256 canonical 重算一致；
- 全部 mask PNG 单通道/尺寸/{0,255}/px/bbox/SHA256 与 plan 一致（冻结后零改动）；
- `allowed_edit == ∪(terms)` 逐资产按盘上 PNG 重算成立；
- `allowed_edit ∩ protected_* = 0` 逐资产逐保护mask成立；
- `tail_destination` 与 master alpha>8 零交；masters/BASE/_spec/Patch1 Reviewer 报告 SHA256 与 plan 及 NIGHT-03 manifest 记录一致；
- night03_patch2/ 下除 `_inspect/`、`mask_plan/` 外零 PNG、零 candidate/repair 命名文件。

## 8. 边界与停止声明

本阶段零候选、零生成调用、零 master/BASE/production/其余 11 张改动、未开始 A15、未开始 Patch 2B；原 Phase 16/17 工作树零触碰。到达 **READY_FOR_NIGHT03_PATCH2A_MASK_REVIEW**，立即停止，等待唯一 Reviewer（ChatGPT Codex）审阅冻结 mask。

```text
PATCH_ID = NIGHT03_RECOVERY_PATCH2A
BASE_SHA = a1586f70416add58d44891330fd8c5aad4d832cb
BRANCH = feature/night03-recovery-patch2
CANDIDATES_CREATED = 0
GENERATION_CALLS = 0
MASKS_FROM_MASTER_ONLY = true
MASKS_PREDECLARED = true
MASKS_SELF_PROVING = false
ALLOWED_PROTECTED_OVERLAP = 0
MASK_PLAN_SHA256 = aa366b183f6c5db1e92edcfb4145699589c6595e4481bc1720c511d7bf30aab6
A01_PLAN_READY = true
A05_PLAN_READY = true
A16_PLAN_READY = true
MASTERS_UNCHANGED = true
PRODUCTION_FILES_CHANGED = 0
REPORT = data/assets_v2/repair_candidates/night03_patch2/NIGHT03_PATCH2A_MASK_FREEZE_REPORT.md
STATUS = READY_FOR_NIGHT03_PATCH2A_MASK_REVIEW
```
