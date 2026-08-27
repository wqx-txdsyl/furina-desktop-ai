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
**rolling-window 时间戳账本**（`_family_hits: Dict[family, List[ts]]`）。事件到达时：

```text
k = 最近 WINDOW 秒内该族已发生的事件数（旧事件逐出后）
本次影响乘数 mult = DIMINISH_BASE ** k   （首次 k=0 → mult=1.0，与 D5 前完全一致）
实际 delta = 基础 delta × (trust×0.5 / LONG_TERM×0.7 既有规则) × strength × mult
```

选择理由：最小、可解释（"短窗口内同族每多一次，影响 ×0.5"）、可测试（纯函数 +
可注入时钟）、满足全部约束——总影响有界（几何级数 ≤ 1/(1-0.5) = 2× 单次）、
时间感知（事件随窗口滚动逐出 → 逐步恢复正常影响）、族隔离（每族独立账本）。

**Event-family 定义**（`EVENT_FAMILIES`）：

```text
positive_social : positive_response / user_initiated / accepted_invitation / long_positive_session
positive_touch  : positive_touch（pet-like 独立族：猛摸不压制 help/social）
help            : successful_help / failed_help（"帮忙互动"族，成功/失败共享饱和）
negative        : reject / ignore / cancel / negative_response
未知事件        : 自身 event 名成独立族（delta 为空 → 天然 no-op，不污染账本）
```

**参数**（均可注入，构造 kwargs）：`window_seconds=120.0`、`diminish_base=0.5`、
`time_fn`（默认 `time.monotonic`；测试用 `_FakeClock`，禁 sleep）。`window_seconds=0`
= 关闭饱和（仅测试对照用，等于旧线性行为）。

## 4. Before / After Behavior（确定性 traces）

```text
① positive burst：100 × positive_response
   linear: familiarity → 3.5×0.7×100 = 245（clamp 100）   familiarity=100
   D5    : familiarity → 3.5×0.7×2 ≈ 4.9                  （2× 单次，几何有界）

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

- `apply()` 不触碰 C6 event store；C6 事件写路径零改动。
- Milestones：`test_d5_milestone_provenance_preserved_no_fake_milestones` ——
  record_milestone("first_positive", source_event_id="lev_abc_123") 后经 50×touch +
  50×reject burst，milestones 仍为 1 条且 `source_event_id == "lev_abc_123"` 精确保留，
  **anti-spam 不创建任何虚假 milestone**。
- C5 current truth owner 未改变：仍是 `RelationshipEngine`（`RelationshipStore.truth_owner`
  属性不变；store 仍仅为 adapter，无第二个 current-state owner）。

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

## 7. Tests

| Gate | Scope | Result |
|---|---|---|
| A（new D5 tests） | tests/test_phase15_d5_relationship_antispam.py | **12 passed** |
| B（既有 relationship） | tests/test_relationship.py | **8 passed** |
| C（C5 store / milestone / provenance） | test_cognitive_stores.py + test_phase151_truth_closure.py | **38 passed** |
| D（Phase 14 relationship normalization / consumer） | phase14 四件套 | **78 passed** |
| E（D1/D4/D2/D3 regression） | d1_canon_evidence + d4_temporal + d2×2 + d3_exposure | **112 passed** |
| F（cognition 全目录） | tests/cognition | **279 passed** |
| G（FULL SUITE） | 全仓库 | **1356 passed / 0 failed / 0 skipped** |

断言纪律：NO skip / NO xfail / NO deleted test / NO weakened assertion / NO fabricated
result。唯一既有测试调整：`tests/test_rc1_freeze.py::test_relationship_event_applied_once`
原断言"两次 apply 增量相等"编码**旧线性契约**，与 D5 强制的新契约（边际递减）直接冲突；
按"修根因"升级为**更强**断言（首次增量=完整单次 delta 4.2、第二次=×0.5=2.1，精确值锁定
"恰好一次路由"——若事件被重复路由，首次增量会是 8.4）。`tests/test_relationship.py` 全数
通过且断言未弱化（Gate B）。

## 8. Static Audit

- 生产改动仅 `furina/relationship/engine.py`：新增 `EVENT_FAMILIES` / `event_family()` /
  `DEFAULT_ANTISPAM_WINDOW_SECONDS` / `DEFAULT_DIMINISH_BASE` / `_now()` /
  `_family_multiplier()`；`__init__` 增 3 个注入参数；`apply()` 增 early-return + 乘数。
- 账本纯内存（`_family_hits`），零 DB 访问、零 schema、零 migration；`decay()` /
  `relationship_factors()` / `_bump` clamp / `RelationshipState` / `RelationshipStore` /
  C5 milestones 表全部原样。
- `relationship_factors()` 仍是唯一 canonical 0..1 consumer contract（未改）。
- 无关 untracked（data/assets_v2/, scripts/assets_v2/, Phase_16/_night_*, 其余
  _night_*/14-15 文档, nul）一律未 add/commit/move。

## 9. Remaining Gaps

- window/base 为模块常量 + 构造注入，未暴露到 AppConfig（如需运营调参另行任务）；
- `failed_help` 与 `successful_help` 共享 help 族饱和（有意的设计选择：同属"帮忙互动"；
  如需按结果拆族需重定义 family 映射）；
- 饱和账本不持久化：restart 后清空（**有意的**——C5 truth 由 `RelationshipState` 经
  MemoryStore `save/load_relationship` 持久化，账本只是 operational 防刷状态）；
- 事件族映射为白名单式；新增事件类型需显式登记族（fail-safe：未登记 → 独立族 no-op）。

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
```

## 11. Final Line

```text
READY_FOR_REVIEW
```
