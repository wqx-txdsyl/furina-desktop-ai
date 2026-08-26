# Phase 15 — D1 Canon Act II / III Official Evidence Acquisition
# CLOSEOUT REPORT — EXACT

Document path:

`docs/phase/Phase_15/05_Phase_15_D1_Canon_Act_II_III_Official_Evidence_Closeout_Report_EXACT.md`

## 1. Result

```text
READY_FOR_REVIEW
```

（编码代理不宣告 PHASE_15_FINAL_GATE_PASS；最终判定权在外部 reviewer。）

## 2. Baseline / Branch / SHA

```text
integration baseline SHA: a5bd81c99580e56715e7fb4192b25bf3be6508a0
                          （feature/phase15-cognitive-life-finalization 最新 accepted SHA）
task branch:              feature/phase15-d1-canon-act2-act3-evidence（自 a5bd81c 切出）
final local SHA:          见 §9（本任务最后一个 commit）
final remote SHA:         push 后 git ls-remote 校验 == final local SHA
```

## 3. Official Evidence Result

### Act II

```text
VERIFIED
official source:  SRC-011 —— 原神官方 HoYoLAB 号公告『"As Light Rain Falls Without Reason"
                  Version 4.0 Update Details』（Genshin Impact Official，uid=1015537，
                  cert_type=1；post www.hoyolab.com/article/20899860；
                  官方 API bbs-api-os.hoyolab.com/community/post/wapi/getPostFull 于
                  公告全文于 2026-08-27 recon 时经该公开官方接口独立核验（retcode=0）；registry 仅保留 locator 与有界主张摘录）。
                  关键官方原句：「V. New Main Story 1. New Archon Quest … Archon Quest
                  Chapter IV: Act II "As Light Rain Falls Without Reason"」；
                  「…and Archon Quest Chapter IV: Act II "As Light Rain Falls Without
                  Reason" will be permanently available」；
                  「Update maintenance begins 2023/08/16 06:00 (UTC+8)」。
source type:      OFFICIAL_WEB（Tier 1；原神官方账号发布的版本更新说明）
quest:            Chapter IV
act:              II（act 编号出自公告原文本身，非由版本号推断）
evidence unit ID: FUR-057
episode IDs:      未挂接（无既有 exact-act=II episode；按 brief §5 仅挂接语义兼容者）
```

### Act III

```text
VERIFIED
official source:  SRC-012 —— 同官方号『"To the Stars Shining in the Depths"
                  Version 4.1 Update Details』（post www.hoyolab.com/article/21888288；
                  镜像页 genshin.hoyoverse.com/en/news/detail/113142；同法独立核验全文，未落整页文本）。
                  关键官方原句：「Archon Quest Chapter IV: Act III "To the Stars Shining
                  in the Depths" ◆ Quest Unlock Criteria: … Complete Archon Quest
                  Chapter IV: Act II "As Light Rain Falls Without Reason"」；
                  「After the Version 4.1 update, Archon Quest Chapter IV: Act III … and
                  Chapter IV: Act IV "Cataclysm's Quickening" will be permanently available」；
                  「update maintenance begins 2023/09/27 06:00 (UTC+8)」。
                  附带官方链序证据：Act II → Act III → Act IV。
source type:      OFFICIAL_WEB（Tier 1）
quest:            Chapter IV
act:              III
evidence unit ID: FUR-058
episode IDs:      未挂接（理由同上）
```

两个幕级单元的**主张范围明确限定**为：幕存在 + Chapter IV 归属 + 版本窗口 +
官方链序。未核验的场景级细节一律不写进 registry（`FURINA_CANON_EVIDENCE.md`
仍只承载 FUR-001~056 的游戏文本类单元）。

CN 名称（「仿若无因飘落的轻雨」「白露与黑潮的序诗」等）以 ys.mihoyo.com CN 官方页
（detail/28551）索引片段作 locator 参考；主锚 = recon 时已独立核验全文的 EN 官方公告。

## 4. Modified Files

| File | Why changed | Authority affected |
|---|---|---|
| `data/canon/furina_evidence_units.json` | 新增 FUR-057（Act II）/ FUR-058（Act III）幕级锚点单元 | evidence registry 唯一归因真源 56→58 条 |
| `data/canon/furina_life_sources.json` | 新增 SRC-011/SRC-012（Tier 1 OFFICIAL_WEB，USED），各持一个新单元 | source registry 10→12 条 |
| `docs/persona/FURINA_CANON_LIFE_SOURCE_MAP.md` | Act 表 II/III 行 COVERED 化 + 验收计数同步 + D1 锚点性质说明 | 文档真源与 metrics 一致性 |
| `tests/cognition/test_phase15_d1_canon_evidence.py` | **新增** D1-T1..T10 reviewer-locked 测试 | 新测试 |
| `tests/cognition/test_phase14_final_reviewer_r6_r12.py` | **[迁移披露]** R7-T6/R7-T7：生产 coverage 期望值 PARTIAL→COMPLETE、missing ["II","III"]→[]（R7-T7 改锁暴露机制诚实性）；INNER_WORLD_REVELATION 唯一缺口断言保留 | 生产事实迁移（非弱化：缺口保护强度不变） |
| `tests/cognition/test_phase14_final_r7_r10_failclosed.py` | **[迁移披露]** R7-FC-T4 同上 | 同上 |
| `tests/cognition/test_phase151_truth_closure.py` | **[迁移披露]** R12 sources_used 精确集合 += SRC-011/012；NOT_USED 排除断言原样保留 | 同上 |
| `data/canon/furina_life_history.json` | **零改动**（无语义兼容的 exact-act episode 需要挂接） | — |

C1-C7 生产代码：**零改动**。

## 5. Before / After Metrics（production CanonHistoryStore 输出）

```text
BEFORE:
canon_span_status                   = MANDATORY_SPAN_SOURCE_COMPLETE
mandatory_life_stage_source_status  = PARTIAL:episodes_without_exact_act_main_story_evidence=['INNER_WORLD_REVELATION']
main_story_act_coverage_status      = PARTIAL
missing_main_story_acts             = ['II', 'III']
main_story_act_coverage             = {I:T, II:F, III:F, IV:T, V:T}
unregistered_evidence_ids           = []
evidence_attribution_conflicts      = []
evidence_registry_entries           = 56

AFTER:
canon_span_status                   = MANDATORY_SPAN_SOURCE_COMPLETE
mandatory_life_stage_source_status  = PARTIAL:episodes_without_exact_act_main_story_evidence=['INNER_WORLD_REVELATION']   # 不变——真实缺口如实保留
main_story_act_coverage_status      = COMPLETE
missing_main_story_acts             = []
main_story_act_coverage             = {I:T, II:T, III:T, IV:T, V:T}
unregistered_evidence_ids           = []
evidence_attribution_conflicts      = []
evidence_registry_duplicates        = []
dangling_source_ids                 = []
sources_used                        = [SRC-001..006, SRC-011, SRC-012]
evidence_registry_entries           = 58
```

未被"洗绿"的证据：`episodes_without_exact_act_main_story_evidence == [INNER_WORLD_REVELATION]`
与 `mandatory_life_stage_source_status = PARTIAL…` 两项在 AFTER 中**逐字保留**
（D1-T7 / R7-T6 / R7-FC-T4 三重锁定）。

## 6. Source Discipline Audit

```text
external locator → official source 的链条：
  Furinelle timeline 仅提供「可能幕名」提示 → 全部弃用其文本，仅以
  官方 Genshin Impact 认证号（uid=1015537, cert_type=1）版本说明为权威工件，
  官方页面/接口全文于 recon 时独立核验；registry 只保留 locator 与有界摘录（不复制整页版权文本）。
证明 community/locator 未成为权威：
  - D1-T6：扫描全部 USED 来源 access_source/access_locator，禁止 fandom/gamersky/
    bilibili 视频/9game/reddit/AI-summary 等 marker 出现；断言 FUR-057/058 仅被
    OFFICIAL_WEB 类 USED 源持有；registry 存储文本不含 Furinelle repo 引用。
  - 无 invent URL：SRC-011/012 的每个 URL 都是本次 recon 实际访问/抓取过的地址。
  - 无 guessed act：act 编号直接来自公告原文枚举（非版本号换算）；两页互证链序。
  - tier 未削弱：新增源 Tier 1（页面类最高可用层）；Tier 0 游戏文本层未被降格或冒充。
```

## 7. Tests

| Gate | Scope | Result |
|---|---|---|
| A（新 D1 测试） | `tests/cognition/test_phase15_d1_canon_evidence.py` T1-T10 | **10 passed** in 0.42s |
| B（Phase 14 reviewer preservation） | `test_phase14_final_reviewer_r6_r12.py`（30，含 2 处披露迁移）+ `failclosed/closure/residual`（48） | **30 passed** / **48 passed** |
| C（Phase 15 canon cognition） | `phase15a + phase151_truth_closure`（R12 迁移披露）+ `cognitive_stores` | **45 passed** |
| D（persona/manifest/canon 校准） | `tests/persona` + `test_manifest.py` + `test_canon_calibration.py` | **153 passed** |
| E（FULL SUITE） | 全仓库 | **1242 passed / 0 failed / 0 skipped**，161.15s（基线 1232 + 新增 10 = 1242；无 skip/xfail/删除断言） |

## 8. Static Audit（brief §8 逐项）

```text
no new unregistered evidence IDs   PASS（T1：unregistered=[]，entries=58）
no unregistered source IDs         PASS（T2：SRC-011/012 注册且 USED；dangling_source_ids=[]）
no community source promoted       PASS（D1-T6 扫描器 + registry 无 locator 来源 USED）
no source tier weakened            PASS（Tier 层级无变动；新增源为 Tier 1 页面层合法上限）
no exact-act mismatch              PASS（conflicts==[]；T5 证错幕必报冲突+gap）
no duplicate evidence IDs          PASS（duplicates==[]）
no runtime mutation path into C2   PASS（D1-T9：加载/查询前后三文件 SHA256 不变；
                                        store 公开方法无写动词）
no unrelated production files changed PASS（git diff 范围 = §4 清单；C1-C7 生产代码零 diff）
```

## 9. Git State

```text
git status --short：commit 后仅剩历史遗留 untracked `nul` 与后续任务书文档（06-15/_INDEX，
                    按规程不随 D1 提交）
local SHA : （见 push 输出，任务分支 tip）
remote SHA: git ls-remote origin feature/phase15-d1-canon-act2-act3-evidence == local
```

## 10. Remaining Gaps

```text
C2 剩余真实缺口（如实保留，未被 D1 掩盖）：
  INNER_WORLD_REVELATION (act=V) 缺少同 act MAIN_STORY 场景级证据支撑
  → mandatory_life_stage_source_status 维持 PARTIAL。
后续阶段提示（非本任务范围）：Scene-level Act II/III 细节（具体审判庭场景/米凯刑场段等）
  若未来需要进 C2，须另行取证并在 episode 层做语义兼容挂接。
```

## 10b. External Reviewer Residual Closure（NEEDS_NARROW_PATCH → 已闭合）

reviewer verdict：`PHASE15_D1_REVIEW = NEEDS_NARROW_PATCH`（针对 391bed8）。

**Blocker**：`_main_story_act_coverage()` / `_act_support_gaps()` 只校验 evidence 元数据
（MAIN_STORY / Chapter IV / 同 act），未证明该 evidence_id 由合格权威 USED 来源持有
—— 孤立单元可产生覆盖，违背 D1 权威链与 D1-T6 精神。

**Patch**（`furina/cognition/stores/canon_history.py`，唯一生产文件改动）：
- 新增中央判定 `_evidence_source_backed(evidence_id)`：扫描 source registry 中登记了该
  evidence_id 的来源，要求 `status == USED` 且 `canon_tier ∈ (0,1)`（当前冻结层级下的
  合格权威层；Tier 2 镜像 / Tier 3 / NOT_USED / FORBIDDEN / locator / 无主全部不合格）；
- `_main_story_act_coverage()`：act 覆盖需同时满足元数据精确 **且** 持有链合格；
- `_act_support_gaps()`：精确幕支撑判定同样加持有链门；episode 的其它有效 source_ids
  不能为不相关 evidence 作保。
- 未硬编码任意 source_type 字符串；未 weaken R7/R7-FC；SRC-011/012 数据主张未被改动。

**Counterexamples（新增 6 个 reviewer-locked 测试，同文件）**：

| ID | 场景 | 结果 |
|---|---|---|
| R1 (d1_r1) | 精确 II 单元无任何持有者 | coverage[II]=False；missing 含 II |
| R2 (d1_r2) | 持有者 status=NOT_USED | 不覆盖 |
| R3 (d1_r3) | Tier3/FORBIDDEN 持有 与 Tier2-USED 镜像持有 两变体 | 均不覆盖 |
| R4 (d1_r4) | episode 引无主 II 单元但自带有效 SRC-001 类来源 | episode 仍在 gaps；life-stage=PARTIAL≠COMPLETE；coverage[II]=False |
| R5 (d1_r5) | 生产链 SRC-011→FUR-057 / SRC-012→FUR-058 | II/III=True、missing=[]、COMPLETE |
| R6 (d1_r6) | INNER_WORLD_REVELATION 仍为唯一生产缺口 + 把 FUR-057 持有者降级 NOT_USED → Act II 即刻失绿 | 方向性 fail-closed 验证通过 |

R7/R8 以 Gate B/C 整套执行（D1 T1-T10 全部保持绿；Phase14 R7/R7-FC 全绿）。

**Gates**：
```text
Gate A  tests/cognition/test_phase15_d1_canon_evidence.py   16 passed（T10+R6）
Gate B/C Phase14 reviewer 四件套                              78 passed
Gate D  canon/persona/manifest 定向                          198 passed
Gate E  FULL SUITE ×2                                       1248 passed / 0 failed（88s, 93s）
```
（1242 = D1 前值 + 本补丁新增 6 个测试。）

**Doc precision cleanup（按 reviewer 指令同步落地）**："抓取全文存档"类措辞已在
closeout §3、source map、SRC-011/012 notes 三处改为 —— 官方页面/API 全文于 recon 时
独立核验；registry 仅保留 locator 与有界主张摘录（无版本化整页存档，不提交版权全文）。

**Git**：同一任务分支 feature/phase15-d1-canon-act2-act3-evidence 追加本 residual commit，
push 后 local SHA == remote SHA。

## 11. Final Line

```text
READY_FOR_REVIEW
```
