# Phase 15 — D5 Relationship Anti-Spam Hardening
# CLOSEOUT REPORT — EXACT

## 1. Result

```text
READY_FOR_REVIEW
```

（不宣告 D5_PASS / PHASE15_PASS；判定权在外部 reviewer。）

## 2. Baseline / Branch / SHAs

```text
D3_ACCEPTED_SHA        = b42ed4a69e012c3a533a5232b80319d30b9ed538
integration BEFORE ff  = 55c5959780883b0d0504653dfab9a4e6958e4c8b（accepted D2）
integration AFTER  ff  = b42ed4a69e012c3a533a5232b80319d30b9ed538（--ff-only，无未知提交）
integration local == remote = YES（push 后校验）
D5_BASELINE_SHA        = b42ed4a69e012c3a533a5232b80319d30b9ed538（从 integration 切出）
D5_BRANCH              = feature/phase15-d5-relationship-antispam
D5_FINAL_SHA           = 见外部 handoff（closeout 不包含自身 commit SHA）
```

## 3. Chosen Saturation Model

对比过的备选：

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| rolling-window cap（硬计数上限） | 简单 | 阈值突兀、无渐进感、窗口边界行为粗糙 | 不选 |
| diminishing returns（无窗口） | 有界、渐进 | 无时间恢复；与"窗口过后恢复"要求冲突 | 不选 |
| event-family saturation（无时间窗） | 族隔离清晰 | 饱和后永久削弱，无法恢复 | 不选 |
| **bounded hybrid（选定）** | 确定性、有界、time-aware、族隔离 | 实现最"重"（仍仅 ~30 行） | **采用** |

**选定机制**：`RelationshipEngine` 唯一写入口 `apply()` 内，按**事件族**维护一个
**rolling-window 时间戳账本**（per-family `deque(maxlen=max_hits_per_family)`——
硬容量：持续 spam 也不会线性增长，总 ledger 长度 ≤ distinct_families × capacity）。
事件到达时：

```text
k = 最近 WINDOW 秒内该族已发生的事件数（队首过期逐出；deque 满则 append 自动淘汰最旧，
    绝不在满容量后停止更新时间戳）
本次影响乘数 mult = DIMINISH_BASE ** k   （首次 k=0 → mult=1.0，与 D5 前完全一致；
                                         持续 spam 封底 ≈ DIMINISH_BASE ** capacity）
实际 delta = 基础 delta × (trust×0.5 / LONG_TERM×0.7 既有规则) × strength × mult
```

选择理由：最小、可解释（"短窗口内同族每多一次，影响 ×0.5"）、可测试（纯函数 +
可注入时钟）、满足全部约束——**有限 N 次攻击**总影响有界：同一窗口内瞬时爆发几何
级数 ≤ 1/(1-0.5) = 2× 单次；对任意有限 N 次（含跨窗口）攻击，封闭形式上界 =
`single×(2 + N×0.5^cap)`（事件在窗口内连续到达时）。**不做**无限时域总影响 ≤2×single
的声明——窗口滚动逐出后同类事件恢复全额，长时间跨度下关系本应继续积累
（long-term building），这是有意的语义而非漏洞。

**Event-family 定义**（`EVENT_FAMILIES`）：

```text
positive_social : positive_response / user_initiated / accepted_invitation / long_positive_session
positive_touch  : positive_touch（pet-like 独立族：猛摸不压制 help/social）
help_success    : successful_help（正向）
help_failure    : failed_help（负向；**相反语义拆分独立族** —— 成功饱和绝不压制真实
                  失败的首个负向影响，反之亦然）
negative        : reject / ignore / cancel / negative_response
未知事件        : 自身 event 名成独立族（delta 为空 → early-return，不创建账本条目）
```

**参数**（均可注入，构造 kwargs）：`window_seconds=120.0`、`diminish_base=0.5`、
`max_hits_per_family=64`（安全默认）、`time_fn`（默认 `time.monotonic`；测试用
`_FakeClock`，禁 sleep）。`window_seconds=0` = 关闭饱和（仅测试对照用，等于旧线性行为）。

## 4. Before / After Behavior（确定性 traces）

```text
① positive burst（100 次同一窗口内瞬时爆发）：100 × positive_response
   linear: familiarity → 3.5×0.7×100 = 245（clamp 100）   familiarity=100
   D5    : familiarity → ≈ 4.9（同窗口几何有界 ≤ 2× 单次；有限 N 封闭上界见 §3）

② spaced positive events（窗口过后恢复）
   t=1000 touch → mult 1.0（+1.75 familiarity）
   t=1001 touch → mult 0.5（+0.875）
   t=1061 touch → mult 0.25（半窗内仍递减）
   t=1182 touch → 旧事件全部逐出 → mult 1.0（全额恢复）

③ negative burst：100 × reject
   linear: annoyance → 7×100 = 700（clamp 100）
   D5    : annoyance → 7×2 ≈ 14；tolerance/confidence 未归零，trust/comfort 未被波及

④ trust farming attempt：20 × positive_response
   D5 前 trust=0（该事件无 trust delta）；反复 successful_help：
   trust 每窗 ≤ 2.0×0.5×2 = 2.0 上限（几何有界），无法快速刷满
```

## 5. C6 / Provenance Preservation

- C6 客观真值**直接验证**（`test_d5_c6_events_preserved_during_c5_saturation`）：
  真实 CognitionHub/EventTimelineStore，连续记录 40 条客观 interaction C6 events
  （USER_PET/USER_MESSAGE），同时让对应 C5 delta 进入 saturation —— 40 条 event_id
  全部保留、数量不变；anti-spam 只影响 C5 delta，不吞 C6 truth。
- Milestones：`test_d5_milestone_provenance_preserved_no_fake_milestones` ——
  record_milestone("first_positive", source_event_id="lev_abc_123") 后经 50×touch +
  50×reject burst，milestones 仍为 1 条且 `source_event_id == "lev_abc_123"` 精确保留，
  **anti-spam 不创建任何虚假 milestone**。
- C5 current truth owner 未改变：仍是 `RelationshipEngine`（`RelationshipStore.truth_owner`
  属性不变；store 仍仅为 adapter，无第二个 current-state owner）。
- Restart：`test_d5_real_db_restart_roundtrip` —— MemoryStore save → close → 同一 DB
  重开 → load → 新 engine：C5 raw truth 按既有 2 位小数持久化契约（
  `RelationshipState.as_dict()` round 2，Phase 04 起）精确保留；新 engine operational
  ledger 为空；restart 后首事件恢复全额；无新 schema（同一 DB 直接重开）。

## 6. Product Boundary Audit

D5 变更仅收敛于 `RelationshipEngine.apply()` 内的乘法系数（+ 事件族账本）：

```text
无 visible affection number / heart meter      ✓（未新增任何字段）
无 intimacy level / affection stage / unlock   ✓
无 工作换好感                                  ✓
无 LLM 决定关系 delta                          ✓（纯确定性）
C4/C6/C7 权威语义未改                          ✓
Motivation/Dialogue/Persona/Agency 行为策略未改 ✓（仅 engine.apply 系数）
relationship climate 不驱动靠近/沉默/拒绝      ✓
Phase 17 Character Agency 未引入               ✓
milestone provenance 未删除/伪造               ✓
```

```text
PRODUCTION_BEHAVIOR_POLICY_CHANGED = true     （anti-spam 本身即生产行为策略变更）
POLICY_CHANGE_AUTHORIZED_BY_D5       = true     （由 D5 任务书显式授权）
DATABASE_SCHEMA_CHANGED             = false    （无 schema / migration / DB 修改）
```

## 7. Tests

| Gate | Scope | Result |
|---|---|---|
| A（new D5 tests） | tests/test_phase15_d5_relationship_antispam.py | **19 passed** |
| B（既有 relationship） | tests/test_relationship.py | **8 passed** |
| B2（rc1_freeze 回归） | tests/test_rc1_freeze.py | **8 passed** |
| C（C5 store / milestone / C6 provenance） | test_cognitive_stores.py + test_phase151_truth_closure.py | **38 passed** |
| D（Phase 14 relationship normalization / consumer） | phase14 四件套 | **78 passed** |
| E（D1/D4/D2/D3 regression） | d1_canon_evidence + d4_temporal + d2×2 + d3_exposure | **112 passed** |
| F（cognition 全目录） | tests/cognition | **279 passed** |
| G（FULL SUITE ×2） | 全仓库 | **1362 passed / 0 failed / 0 skipped** |

断言纪律：NO skip / NO xfail / NO deleted test / NO weakened assertion / NO fabricated
result。`tests/test_rc1_freeze.py::test_relationship_event_applied_once` 数值断言保持
4.2/2.1 精确值（未弱化），注释改为准确表述：该断言锁定 **engine 单次调用的数学契约**
（确定性 delta），不声称独立证明生产 routing exactly-once（routing 由既有集成/freeze
断言覆盖）。`tests/test_relationship.py` 全数通过且断言未弱化（Gate B）。
注：Gate G 首轮全量有 1 例 `test_gui_integration.py::test_gui_timer_advances_runtime`
失败，**未稳定复现**（隔离重跑通过、第二轮全量 1362 passed / 0 failed；本轮改动
零 GUI/timer 文件）。

## 8. Static Audit

- 生产改动仅 `furina/relationship/engine.py`：新增 `EVENT_FAMILIES` / `event_family()` /
  `DEFAULT_ANTISPAM_WINDOW_SECONDS` / `DEFAULT_DIMINISH_BASE` /
  `DEFAULT_MAX_HITS_PER_FAMILY` / `_now()` / `_family_multiplier()` /
  `saturation_snapshot()`；`__init__` 增 4 个注入参数（含 `max_hits_per_family`）；
  `apply()` 增 early-return + 乘数；`_family_hits` 为 per-family `deque(maxlen)`。
- 账本纯内存（`_family_hits: Dict[str, deque]`），零 DB 访问、零 schema、零 migration；
  `decay()` / `relationship_factors()` / `_bump` clamp / `RelationshipState` /
  `RelationshipStore` / C5 milestones 表全部原样。
- `apply()` 返回值语义已在 docstring 准确表述：**base delta × 饱和乘数（round 3），
  不含 strength / LONG_TERM / trust 乘数与 clamp 后的 state 差值**；既有公开返回结构
  未改变（recon 未发现依赖返回值的调用方需要修复——app/scheduler/store 均忽略返回值）。
- `relationship_factors()` 仍是唯一 canonical 0..1 consumer contract（未改；
  `test_d5_canonical_factors_0_1_after_burst` 验证 engine.factors() 委托关系）。
- 无关 untracked（data/assets_v2/, scripts/assets_v2/, Phase_16/_night_*, 其余
  _night_*/14-15 文档, nul）一律未 add/commit/move。

## 9. Remaining Gaps

- window/base/max_hits 为模块常量 + 构造注入，未暴露到 AppConfig（如需运营调参另行任务）；
- 饱和账本不持久化：restart 后清空（**有意的**——C5 truth 由 `RelationshipState` 经
  MemoryStore `save/load_relationship` 按既有 2 位小数契约持久化，账本只是 operational
  防刷状态）；
- 事件族映射为白名单式；新增事件类型需显式登记族（fail-safe：未登记 → 独立族 no-op）；
- `apply()` 返回值为 base delta × 饱和乘数（round 3），不含 strength/LONG_TERM/trust
  乘数与 clamp —— 已按 reviewer 要求准确表述，未改变既有公开返回结构（无调用方依赖）。

## 10. Git State

```text
commit 仅含 D5-scoped 文件：
  furina/relationship/engine.py（anti-spam 唯一生产改动）
  tests/test_phase15_d5_relationship_antispam.py（新增 12 测试）
  tests/test_rc1_freeze.py（旧线性契约断言 → 新契约精确断言，根因修复）
  docs/phase/Phase_15/12_..._Task_Brief_EXACT.md + 13_..._Closeout_Report_EXACT.md
unrelated untracked 一律未 add/commit/move
final local SHA == final remote SHA 于 push 后校验；未 merge D5 → integration；
未开始 Integrated Final Gate；未开始 Phase 16
reviewer narrow patch 轮：ledger deque 硬容量 + help 族拆分 + C6/真实 restart/
canonical 测试 + 文档措辞修正（仍在同一 D5 分支、同一 D5 文件范围）
```

## 11. Final Line

```text
READY_FOR_REVIEW
```
