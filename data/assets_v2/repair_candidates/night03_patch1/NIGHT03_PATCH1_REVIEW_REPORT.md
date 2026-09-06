# NIGHT03_PATCH1_REVIEW_REPORT — Independent Reviewer Gate

- reviewer: Codex independent Reviewer（唯一 Reviewer）
- date: 2026-08-29
- patch_id: `NIGHT03_RECOVERY_PATCH1`
- scope: 仅审阅 a01 / a05 / a16；不修图、不改脚本、不扩展其余 11 张、不开始 A15
- decision: **NIGHT03_PATCH1_PATCH_REQUIRED**

## 1. 最终判定

**Patch 1 不通过，方法不得扩展到剩余 11 张。**

三张候选均能从 master 确定性逐像素复现，SHA、alpha、geometry、manifest 与 metadata
也全部吻合；但原尺寸、200%、512、256、128 和透明棋盘背景审阅均发现 blocker。
a01/a05 的镜像尾部带有明显硬直边、近黑色实心块或矩形过渡；a16 的右侧头发、手部、
杖头邻域和纸张发生实质损伤，尾部与身体的组合也存在明显断裂和硬切。

此外，最终 `allowed_edit` 不是完整预声明的 mask：三个 builder 都先产生候选，再由
`post_cleanup` 从候选 alpha 连通状态计算 `explicit_debris` / `weld`，最后把这些区域并入
`allowed_edit`。按 cleanup 前的 `removal ∪ patch_footprint` 复核，共有 470 个变化像素在
原许可范围之外（a01=2、a05=5、a16=463）；扩展后的最终 mask 才把该数降为 0。

```text
DECISION = NIGHT03_PATCH1_PATCH_REQUIRED
METHOD_PROVEN_VERIFIED = false
PILOT_PASS = 0
MASK_PREDECLARED = false
MASK_SELF_PROVING = true
UNAUTHORIZED_DIFF_PIXELS = 470
IDENTITY_REGRESSIONS = 1
COSTUME_DAMAGE = 1
TAIL_FAILURES = 3
PROP_FX_FAILURES = 1
ALPHA_FAILURES = 0
METADATA_MISMATCHES = 0
A05_GEOMETRY_EXCEPTION_ACCEPTED = true
A16_HAND_ACCEPTED = false
A16_HAIR_REPAIR_ACCEPTED = false
REPRODUCIBLE_OUTPUTS = 3
MASTERS_UNCHANGED = true
PRODUCTION_FILES_CHANGED = 0
GENERATION_CALLS = 0
REPORT = data/assets_v2/repair_candidates/night03_patch1/NIGHT03_PATCH1_REVIEW_REPORT.md
STATUS = NIGHT03_PATCH1_PATCH_REQUIRED
```

`UNAUTHORIZED_DIFF_PIXELS=470` 使用 Reviewer 的严格口径：以 cleanup 前、由 master 和
预定变换产生的编辑并集为准。Builder 的最终扩展 mask 口径仍为 0，但该 0 不能作为
独立授权证据。

## 2. 审阅输入与方法

已完整审阅：

- 当前线程中的 NIGHT-03 Recovery Patch 1 Reviewer 任务书
- `data/assets_v2/_spec/ASSET_GEOMETRY_AND_ANCHOR_SPEC.md`
- `data/assets_v2/_spec/FURINA_IDENTITY_LOCK.md`
- `data/assets_v2/repair_candidates/night03/NIGHT03_REVIEW_REPORT.md`
- `data/assets_v2/repair_candidates/night03_patch1/NIGHT03_PATCH1_REPORT.md`
- manifest、3 份 metadata、3 张候选、3 张三联图、9 张 runtime preview、mask/diff overlay
- `scripts/assets_v2/night03_patch1_{lib,inspect,forensics,zoom,repair,finalize}.py`
- a01/a05/a16 master 与 `_base/furina-base.png`

方法包括：脚本静态审查、从内存重跑三个 builder、候选逐像素比较、alpha>8 的 4 连通
复测、SHA256、metadata/manifest 对照、保护区与真实 diff 交叉、原尺寸与缩放视觉审阅。

## 3. 完整性、安全与可复现性

| 项目 | 结果 | 证据 |
|---|---|---|
| 候选/三联/预览/metadata | PASS | 3 / 3 / 9 / 3，文件齐全 |
| 尺寸与模式 | PASS | 三张均为 1024×1536 RGBA |
| master-only 输入 | PASS | repair builder 仅从 `data/assets_v2/masters` 读取图像 |
| 首轮失败候选未使用 | PASS | 脚本无 `repair_candidates/night03/` 输入路径 |
| 网络/生成调用 | PASS | 无网络、API、图像生成或 subprocess 路径；`GENERATION_CALLS=0` |
| 写入安全 | PASS | 写入路径局限于 `night03_patch1/`；master 与 production 无写路径 |
| 三张可复现 | PASS | 内存重跑与磁盘 PNG 3/3 逐像素相同 |
| 候选 SHA | PASS | 3/3 与 manifest 一致 |
| master / BASE SHA | PASS | 3 个 master 与 BASE 均与 manifest 一致 |

`production_files_changed: 0` 在 finalize 中是硬编码字段，而不是一次 git diff 测量；
不过静态审查确认 NIGHT-03 Patch 1 脚本没有 production 写路径。当前工作区已有的 Phase 16
修改属于并行工作，不归因于本 patch，也未被 Reviewer 触碰。

## 4. Mask 与脚本审查

### 4.1 `tail_source` 并未使用已识别的尾部组件

三个 builder 都先计算 `final` 组件选择结果，但随后未使用它，而直接执行：

```text
tail_source = corridor & alpha & ~prot
```

对应 `night03_patch1_repair.py` 第 105/111、249/253、429/433 行。也就是说实际删除对象
是“走廊内所有未保护前景”，不是已识别的尾部语义组件。这仍会把保护规则遗漏的服装、
头发、道具和暗色轮廓整体纳入尾部。

### 4.2 最终 allowed mask 含候选生成后的自授权区域

三个 builder 都在候选合成后调用 `post_cleanup`，再执行：

```text
allowed = allowed | debris_m | weld_m
```

对应第 140-141、279-280、462-463 行。严格复核结果：

| 资产 | cleanup 前 allowed 外真实 diff | cleanup 后最终 allowed 外 diff |
|---|---:|---:|
| a01 | 2 | 0 |
| a05 | 5 | 0 |
| a16 | 463 | 0 |
| 合计 | **470** | **0** |

Builder 的 `info.outside_diff` 还在 `post_cleanup` 前计算，因此不会统计 cleanup 新增的变化；
finalize 虽重新计算全图 diff，但使用的是已扩展的最终 mask。此结构不能证明所有变化预先
获得语义授权。

### 4.3 报告与实际像素存在直接矛盾

- Builder 报告称 a01 `(363,714-715)` 两像素“保留 master 原状”，实际候选删除了这
  2 个像素，并在 cleanup 后把它们列为 `explicit_debris`。
- Builder 报告称 a16 头发保护区除允许编辑外零变化，实测保护头发区变化 4,148 px，
  其中删除 4,052 px；最大变化连通块 4,102 px，bbox `(745,915)-(797,1017)`。
- Builder 报告称 a16 quill/纸张零变化，实测 `quill_paper` mask 内 100 px 被删除；
  直接区域 `(330,982)-(482,1162)` 内共删除 105 个原前景像素。
- Builder 报告称 a16 手套和金饰原像素完整保留；但手/杖头区域
  `(600,900)-(865,1165)` 有 11,980 px 变化，其中 10,790 px 原前景被删除。

## 5. 独立像素与 metadata 复测

| 指标 | a01 | a05 | a16 |
|---|---:|---:|---:|
| changed_px | 58,425 | 63,409 | 72,595 |
| alpha_components | 1 | 1 | 1 |
| islands_gt40 | 0 | 0 | 0 |
| magenta_px | 0 | 0 | 0 |
| corners_transparent | true | true | true |
| lowest_row | 1467 | 1467 | 1467 |
| content_px | [229,60,611,1408] | [238,60,637,1408] | [240,316,598,1152] |
| com_x | 0.5255 | 0.5409 | 0.5248 |
| manifest measured match | true | true | true |
| metadata measured match | true | true | true |

alpha、metadata 和 hash 全部通过，但它们只证明结构与记录一致，不能覆盖视觉/语义失败。

## 6. 原尺寸与多尺度视觉结论

| 资产 | Identity/Pose | Costume/Prop | Tail | 视觉判定 |
|---|---|---|---|---|
| a01 | 主体身份保持 | 手杖/主体服装总体保持 | 新尾根与遮挡区出现大面积近黑实心块、长竖直硬边，且右尾与身体结合不自然 | **FAIL** |
| a05 | 主体身份保持 | 蝴蝶结和手杖主体保持 | 尾根/手杖后方出现矩形浅蓝块、黑色竖条与裁切边；不是自然遮挡过渡 | **FAIL** |
| a16 | 主体头脸保持，但右侧发卷受损 | 手部、杖头邻域、纸张和外套边缘明显破碎 | 新尾分段感、硬切和身体连接错误，在 512/256/128 仍可见 | **FAIL** |

### a01 blocker

- 新增近黑像素（RGB 均值 <20）共 **9,083 px**，bbox
  `(676,982)-(838,1362)`。
- 最长近黑竖直连续段位于 `x=709, y=1160-1362`，长度 **203 px**。
- 该黑块来自尾部 hole fill/镜像 patch，不是服装、阴影或透明背景；在棋盘、灰底、
  512 和 256 预览中均明显。
- 结论：旧 blocker 未闭环，产生了新的尾根/层级/硬切 blocker。

### a05 blocker

- patch footprint 从 `x=694` 开始，尾根处出现与裁切边对齐的浅蓝矩形块和黑色竖条。
- 新增近黑像素共 **1,349 px**，bbox `(694,1037)-(723,1296)`。
- 视觉上不是从袖后自然涌出的柔和尾根，而是可识别的矩形图块；512/256/128 均仍可见。
- 结论：蝴蝶结主体虽保住，但尾部合成仍不可交付。

### a16 blocker

- 右侧头发保护区变化 4,148 px，最大块位于 `(745,915)-(797,1017)`；所谓 130 px
  weld 无法恢复被删除的 4,052 个头发像素。
- 手/杖头区 11,980 px 变化、10,790 px 删除；候选仍留有白/金/深蓝碎片，拳部不构成
  自然完整的手，而是破碎边缘和悬浮片。
- quill/纸张保护区 100 px 被删除，直接违反“零变化”声明。
- 椅子主体虽大体转为透明，但删除边缘与服装/尾部交叠处形成硬切、空洞和断片。
- 512、256、128 下仍可辨认破碎手部和断裂尾部，不能以“512 下不可见”豁免。

## 7. a05 几何豁免

`A05_GEOMETRY_EXCEPTION_ACCEPTED = true`。

独立实测 `com_x=0.5409`，画布尺寸未变，主体未全局平移、缩放或裁切；偏差来自姿态本身
右倾与尾部从 viewer-left 迁至 viewer-right，符合 GEOMETRY §5 Compatibility rule 2 的
语义记录要求。该豁免只认可几何原因，不豁免尾部的矩形块、黑条和硬切视觉失败。

## 8. 必须修复的 blocker

1. 不得再把 `corridor & alpha & ~prot` 直接当作尾部；必须实际使用已识别、经人工核验的
   尾部语义组件，并为每个被删除的 master 前景像素给出类别归属。
2. `allowed_edit` 必须在候选生成前冻结。cleanup 可提出 debris/weld 建议，但不得在修改后
   自动把自身输出并入许可 mask；Reviewer 应能用冻结 mask 重算 outside diff。
3. a01 删除 `(676,982)-(838,1362)` 的近黑填充块，重建无硬直边、无实心黑柱的尾根与
   遮挡过渡。
4. a05 删除从 `x=694` 开始的矩形浅蓝/黑色拼块，尾根必须保持自然轮廓和连续绘制语言。
5. a16 从 master 重新处理：完整保护右侧头发、quill/纸张、手套、金饰、袖口和服装；
   杖头删除后需要真正重建被遮挡结构，不能用 130 px 发色桥或碎片 weld 代替。
6. 修复后重新提供透明棋盘、浅底、深底、100%、200%、512/256/128 证据；自动 alpha
   单连通只能作为结构门，不能替代视觉门。

## 9. Reviewer 修改范围

Reviewer 仅新增本报告：

`data/assets_v2/repair_candidates/night03_patch1/NIGHT03_PATCH1_REVIEW_REPORT.md`

未修改候选图、master、production、metadata、manifest、脚本或首轮 NIGHT-03 文件；
未提交、未推送、未扩展剩余 11 张、未开始 A15。

