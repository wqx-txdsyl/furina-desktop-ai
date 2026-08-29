# NIGHT03_PATCH1_REPORT — Recovery Builder (三张试点重新证明方法)

- patch_id: NIGHT03_RECOVERY_PATCH1
- date: 2026-08-29
- builder: Recovery Builder (fresh session, GLM-5.3-Flash)
- basis: NIGHT03_REVIEW_REPORT.md (Independent Reviewer Gate, DECISION = NIGHT03_PATCH_REQUIRED)
- scope: 仅 a01 / a05 / a16 三张试点；其余 11 张未触碰；A15 未开始
- scripts: `scripts/assets_v2/night03_patch1_{lib,inspect,forensics,zoom,repair,finalize}.py`
  （全部为新文件名，未覆盖任何 `night03_*` 旧脚本）

## 1. 输入 master 的路径与 SHA256

| 资产 | master | SHA256 |
|---|---|---|
| a01 | `data/assets_v2/masters/furina_v2_a01_stand_neutral_front.png` | `c3ed763c7eed3bfc…`（完整值见 manifest.master_sha256） |
| a05 | `data/assets_v2/masters/furina_v2_a05_stand_confident_proud.png` | `8ddcfde186fb352c…` |
| a16 | `data/assets_v2/masters/furina_v2_a16_work_focused.png` | `f4997917453d6a54…` |

候选 SHA256（由 finalize 从文件字节重算）：

| 候选 | SHA256 |
|---|---|
| `repair_candidates/night03_patch1/furina_v2_a01_repair.png` | `6be747c7d78687de…` |
| `repair_candidates/night03_patch1/furina_v2_a05_repair.png` | `0893cb75384fd78d…` |
| `repair_candidates/night03_patch1/furina_v2_a16_repair.png` | `55aacb18c1846ebc…` |

## 2. 未使用首轮失败候选作为输入的证明

- 三个 builder（`build_a01/build_a05/build_a16`）唯一的图像输入是
  `MASTERS / furina_v2_<key>_<name>.png`（源码可静态审读，无其他读入路径）。
- 全部脚本对 `repair_candidates/night03/`（首轮目录）零读取、零写入；
  `grep -r "night03/" scripts/assets_v2/night03_patch1_*.py` 无首轮路径引用。
- finalize 前后对三个 master 各做一次 SHA256 并写入 manifest：
  `masters_unchanged = true`。

## 3. 每张采用的独立修复方法

三张共用同一框架（`night03_patch1_lib.py` + `night03_patch1_repair.py`），
每张独立建立语义分层，参数互不共用：

**共同合成层级**（对应任务书 §4 强制层级）：
1. 原始透明背景（master 的 alpha 场，除允许编辑区外逐位保持）；
2. 修复后的尾部：`tail_source`（几何廊道∩alpha−保护层）整块镜像于 x=512，
   先做 occluder 孔洞的谐波扩散填充，再 `composite_behind` 到身体后方
   （身体不透明像素**逐位优先**，连 alpha 都不改动）；
3. 身体、服装、头发、合法道具 = master 原像素（除 removal/允许编辑区外零触碰）；
4. 接缝融合仅限：patch 与身体的 AA 交界（半透明混合）+ 手指缝隙的扩散填补。

**a01（基础尾部）**：走廊多边形 28 顶点（左缘贴尾扇外沿 164-190，右缘贴外套中蓝层
341-374，底缘含尾尖新月至 y≈1374）；保护 = 深色粗体几何限定（臂/袖口/手指三矩形内、
bright<80、EDT≥7）+ 手杖（环 303,1042 r44×52 / 菱 302,1144 / 金爪 300,1190 / 杖身
5 条带）+ 金色全局色测 + 袜褶矩形 (383,1278)-(700,1400)。顶部 curl 判定为**固定发型**
（BASE 与 a01 同在左上），不属尾部，未动。残余暗红点 (202,1199-1203) 因 dark-gold
判据收紧 (g−b≥20) 后随走廊删除。

**a05（尾部与蝴蝶结重叠）**：蝴蝶结+垂带矩形保护 (374,858)-(500,1096)；走廊右缘在
结区 x≤374、在短裤区收到 302-310、在下叶右缘 356-362；短裤/双腿矩形保护
(322,1092)-(560,1470)；游离 wisp（615-672,1276-1322）走 `explicit_debris_mask` 独立删除，
patch 构建仅用尾区（wisp 不入 patch，杜绝镜像复制）。

**a16（最困难组合）**：四个独立子系统——
- 椅子：双色 wood 测试（亮木 r−g≤34 + 暖棕 wood2/wood_mid r−g 28-50）×确认木密度门
  （σ12 高斯 ≥0.10/0.06）×邻域亮度门（≤155/148，防误删小腿阴影）×走廊多边形；
- 手杖：分区删除（杖头 745-862,902-1046 含灰调/暗圈清扫；杖颈奶油 748-800,1000-1092；
  护手含右翼 628-764,1086-1154 加全删矩形 686-766,1086-1156；杖身 4 条带随实测路径
  (706,1140)→(688,1250)→(658,1330)→(624,1420)；杖尖 572-660,1380-1478），
  crystal 判据用 b−g≤55 区分外套淡紫，杖身宽暗侧用"贴晶体 ≤12px"条件删除，
  手套矩形 (600,930)-(795,1100) 内 navy 保护保持、之外放行；
- 拳头：食指缝孔隙仅限拳矩形内、以非杖色源做谐波扩散填色（259px），金爪+深蓝手套
  完整保留，无 lerp 拖影、无实心团块；
- 头发：杖头删除后两片发卷 (752-769,1022-1043)/(763-784,1001-1017) 与主体断开，
  `post_cleanup` 以 2px 发色桥焊接回主发团（weld 130px，逐片用碎片自身均值色），
  alpha 连通性恢复 1 分量。

## 4. 所有 mask 的定义、bbox、像素数和 overlay

逐 mask 的 px/bbox 已写入 `night03_patch1_manifest.json` → `assets.<id>.mask_stats`；
彩色 overlay（每像素归类可见）= `night03_patch1/<id>_mask_overlay.png`。摘要：

| a01 | px | | a05 | px | | a16 | px |
|---|---|---|---|---|---|---|---|
| corridor | 45,624 | | corridor | 50,697 | | corridor | 29,821 |
| tail_source=removal | 24,375 | | removal | 36,822 | | removal(并集) | 62,526 |
| protected_cane | 22,835 | | protected_bow | 29,988 | | chair_del | 14,254 |
| protected_frills | 38,674 | | protected_shorts | 89,964 | | cane_del | 24,260 |
| patch_footprint | 49,185 | | patch_footprint | 42,558 | | quill_paper | 26,628 |
| explicit_debris | 2 | | explicit_debris | 5 | | specks | 135 |
| | | | | | | protected_hair | 236,160 |
| | | | | | | explicit_debris | 458 |
| | | | | | | weld | 130 |

## 5. full-canvas RGBA diff 统计（1024×1536 全画布，逐位比较 RGBA 四通道）

| | changed | deleted(旧尾/椅/杖/FX) | added(新尾) | recolored(拳缝填色) | **allowed 外** |
|---|---|---|---|---|---|
| a01 | 58,425 | 24,377 | 34,048 | 0 | **0** |
| a05 | 63,409 | 36,827 | 26,582 | 0 | **0** |
| a16 | 72,595 | 57,934 | 9,605 | 5,056 | **0** |

归因：每个变化像素 ∈ allowed_edit_mask（removal ∪ patch_footprint ∪ debris ∪ weld）。
a01 的 2px 头区变化=0（(363,714-715) 半透明杂点按任务书选项保留 master 原状）。

## 6. a01/a05/a16 原 blocker 逐项闭环

**a01**（Reviewer §4/§10）
- B-a01-1 外套衬里被剥除 (x395-430,y973-1300)：衬里位于走廊右界之外且受金/暗色保护；
  diff 证明衬里区零变化。**闭环**。
- B-a01-2 旧尾描线鬼影 (x190-260,y1150-1300)：本方法删"廊道∩alpha−保护"（非颜色测试），
  描线+外晕随整体删除；左区残留成分仅剩手杖/外套/腿（程序枚举+人工复核）。**闭环**。
- B-a01-3 镜像尾尖碎裂（条纹浮片/青色横条/y≈1300 硬切）：patch 由整条 alpha 廊道构成
  （无 min_comp/rel_keep 丢弃），暗卷纹与尖端全部入 patch；无任何浮片/硬切。**闭环**。
- 尾根连接：镜像贴身体后方，根部被手套/外套自然遮挡（200% 复核）。**闭环**。
- (363,714-715) 两半透明杂点：**保留 master 原状**（任务书许可选项），不计身份回归。

**a05**
- B-a05-1 蝴蝶结粉碎 (x374-443,y870-1038+垂带)：结+垂带整体矩形保护，diff 证明
  区域逐位未变。**闭环**。
- B-a05-2 镜像服装碎片 (x678-766,y903-992)：patch 仅含尾区像素；蝴蝶结在保护层内
  永不入 patch；白色矩形空洞无（删除边界=走廊折线，非矩形）。**闭环**。
- wisp 游离岛 (623-662,1283-1314)：explicit_debris 独立删除。**闭环**。

**a16**
- B-a16-1 右侧头发被删 (x694-815,y850-1000)：头发区 (180-900,690-1018) 全程 identity
  保护；杖头删除后断开的 influencing 发卷以发色桥回焊；diff 证明发区除允许编辑外零变化。
  **闭环**。
- B-a16-2 手部粉碎/拖影：无 col-lerp、无实心团块填充；拳=master 手套+金爪原像素，
  仅指缝 259px 扩散填色；200% 下读作持握姿态，无碎块/拖影/断指感。**闭环**。
- B-a16-3 锯齿空洞吃裙/短裤/外套：椅/杖删除全部走色测×密度门×亮度门×分区，
  diff 证明裙/短裤/外套零变化；外套褶皱保留（wood_mid 邻域亮度门）。**闭环**。
- B-a16-4 尾 2-3 断片：patch 含整条尾（含 y1145-1210 腿间可见段），occluder 孔洞
  扩散桥接，镜像后为单一连续体并没入身体后方。**闭环**。
- 烘焙椅子移除 14,254px、手持手杖移除 24,260px、quill/纸张零变化、3 颗 specks
  (135px) explicit_debris 移除。**闭环**。

## 7. 五档视觉检查结果

每张在 100%、200%（关键区放大）、512、256、128 检查
（证据：`_inspect/a0{1,5}_*.png`、`a16_*.png`、`runtime_previews/*_pet_{512,256,128}.png`、
triptych 三联图）：

| 检查项 | a01 | a05 | a16 |
|---|---|---|---|
| 身份与姿态 | PASS | PASS | PASS |
| 头发完整性（含 a16 两侧卷+高光） | PASS | PASS | PASS（含焊点） |
| 服装完整性（衬里/结/垂带/裙/短裤/袜褶/袖口/金饰） | PASS | PASS | PASS |
| 道具保留/删除正确（a01/a05 手杖、a16 quill+纸、手杖全删） | PASS | PASS | PASS |
| 尾部方向（viewer-right，BASE 一致） | PASS | PASS | PASS |
| 尾部连贯性（单一连续、无断片） | PASS | PASS | PASS |
| 尾与身体层级（身后、被手臂/外套/手杖正确遮挡） | PASS | PASS | PASS |
| 旧尾残留/描线鬼影 | PASS | PASS | PASS |
| 双尾 | PASS | PASS | PASS |
| 白边/黑边/矩形洞/硬切边 | PASS | PASS | PASS（杖头区为语义透明） |
| 半透明鬼影 | PASS | PASS | PASS |
| alpha 碎屑 | PASS | PASS | PASS |
| 缩放可读性（512/256/128） | PASS | PASS | PASS |

a16 备注：拳部在 200% 下金爪与深蓝手套之间为指缝透空+扩散填色，读作自然持握；
杖头原位置头发卷的高光斑点为 master 发丝高光本体（逐位保留），非残留。

## 8. alpha 与 geometry 实测（从最终候选重算，未复制首轮）

| | a01 | a05 | a16 |
|---|---|---|---|
| 模式/角点 | RGBA 直通 alpha，四角 24×24 全透明 | 同 | 同 |
| 品红污染 | 0 | 0 | 0 |
| alpha 分量（alpha>8, 4-连通） | 1 | 1 | 1 |
| islands>40 | 0 | 0 | 0 |
| opaque_px / semi_px | 553,711 / 13,215 | 553,811 / 13,346 | 394,158 / 11,515 |
| content_px [x,y,w,h] | [229,60,611,1408] | [238,60,637,1408] | [240,316,598,1152] |
| lowest_row（baseline G=1468） | 1467 | 1467 | 1467 |
| com_x | 0.5255 | 0.5409 | 0.5248 |
| margin L/R | 229/184 | 238/149 | 240/186 |

- a01/a16 com_x 在 0.50±0.03 容差内，无需 §5.2 记录。
- a05 com_x 0.5409 超 0.53：**引用 GEOMETRY §5.2** —— 姿态本身右倾（首轮 Reviewer
  已确认该偏差为真、由尾侧迁移构成）+ 尾部整块迁至右侧；未使用平移/缩放/扭曲角色
  压阈值（镜像轴=512，纯对称）。理由已写入 metadata `review_notes`。
- a16 content_px 宽度变化（652→598）纯由旧尾（最左 186）移除与新尾（最右 837）加入
  造成，角色本体锚点未动（头部/躯干区逐位一致）。

## 9. 图像生成调用记录及数量

**GENERATION_CALLS = 0**。三张全部确定性完成，无任何生成模型调用；
无 generation_log.json（未使用生成模型）。

## 10. master/production 前后 hash 证明

- manifest `master_sha256`：finalize 入口与出口各算一次，三者前后一致
  → `masters_unchanged: true`。
- production（`furina/`）：本 patch 所有写入目标均在
  `data/assets_v2/repair_candidates/night03_patch1/` 与 `scripts/assets_v2/night03_patch1_*.py`，
  零 production 写路径。`PRODUCTION_FILES_CHANGED = 0`。
- git：未执行任何 add/commit/push。

## 11. 新增/修改文件清单

新增（无任何既有文件被修改/覆盖/删除）：
- 脚本：`scripts/assets_v2/night03_patch1_lib.py`、`night03_patch1_inspect.py`、
  `night03_patch1_forensics.py`、`night03_patch1_zoom.py`、`night03_patch1_repair.py`、
  `night03_patch1_finalize.py`
- 候选：`repair_candidates/night03_patch1/furina_v2_a{01,05,16}_repair.png`
- 三联图：`night03_patch1_triptych_a{01,05,16}.png`（MASTER | PATCH1 | BASE）
- 预览：`runtime_previews/a{01,05,16}_pet_{512,256,128}.png`（9 张）
- overlay：`a{01,05,16}_mask_overlay.png`、`a{01,05,16}_diff_overlay.png`
- metadata：`metadata/furina_v2_a{01,05,16}_*.meta.json`（3 份刷新副本，
  review_status=PENDING，含 night03_patch1 块与全部实测）
- 证据：`_inspect/*`（网格裁剪/对比/diffmap）、`_pilot_patch1.json`
- 汇总：`night03_patch1_manifest.json`、本报告

## 12. 尚存风险

1. **a16 拳部**：确定性方案保留 master 手套+金爪原像素，指缝以扩散填色。512/256/128
   下读作自然持握；100-200% 下指缝填色为平滑色块（非原绘细节）。若 Reviewer 认定
   200% 下不够"自然完整"，剩余路径是任务书许可的局部重绘（≤12 次调用），本轮未使用。
2. **a16 杖头区**：原杖头遮住的头发不可恢复（master 中不存在），发卷边缘呈杖形缺口 +
   发丝高光斑点裸露；已用发色桥保持 alpha 连通，512 下不可见，200% 下可见轻微缺口。
3. **a16 杖头/护手删除为语义透明**：该区域原为背景，删除后为透明（非空洞）。
4. **a05 尾根**：尾根上段自袖后涌出的过渡为扩散填充的柔和色域（源被手臂遮挡无真像素），
   512 下自然，200% 下比原绘略软。
5. a01 尾尖下缘、a16 尾上缘与 occluder 交界处有扩散填充的柔和过渡带，均为尾自身
   遮挡重建，200% 可辨识其"软"，形态正确。
6. 三张的镜像尾部亮度分布为源侧镜像（光源方向随之镜像）；BASE 尾即右侧受光，观感一致。

## 13. 最终状态

- SELF_GATE_PASS（三张全部满足 §11 自检判据：allowed 外 diff=0、保护零未授权变化、
  既有 blocker 全闭环、无新增损伤、尾语义/连贯/层级正确、服装道具完整、a16 手部
  桌宠尺寸可交付、alpha/metadata 全过、master/production 未变）
- 未扩展其余 11 张，未开始 A15，未提交/推送。
- 状态：**READY_FOR_NIGHT03_PATCH1_REVIEW**（等待独立 Reviewer）

— Recovery Builder 完毕。
