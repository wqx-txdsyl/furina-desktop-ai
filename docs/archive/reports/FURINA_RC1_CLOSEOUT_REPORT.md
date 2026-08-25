# Phase Report — Backend RC1 Closeout

## 0. Status
Result: **PASS**（RC1）
Tests: 273 / 273 passed
Previous: 265
New: 8（test_rc1_freeze.py；另 acceptance_generate 改用 RelationshipEngine）
Backend frozen: ✅ → **BACKEND RC1 — FINAL FREEZE**
Freeze version: RC1（schema v1.0）
Anti-collapse: OFF（未开启）
Model: glm-4v-flash（唯一 LLM，1 次真实冒烟）

## 1. Scope

允许修改（已完成）：
- MemoryStore 线程处理（B1）
- Scheduler LifeBrain 失败可观察性（B1 伴生）
- Relationship ownership 路由（S1）
- body_snapshot 弃用（S4）
- tests / audit/freeze docs / integration & smoke script

明确禁止、未触碰：Memory scoring / Memory interpretation / Relationship parameters /
BehaviorMotivation scoring / LifeBrain candidate logic / Personality / Identity / Emotion / Needs /
World / Feasibility / Dialogue persona / Embodiment / RuntimeFrame schema / Renderer / Assets /
Agent / LLM model / anti-collapse。

## 2. B1 Root Cause

- Connection creation thread：主线程（`MemoryStore.__init__` 调用 `sqlite3.connect`，默认 `check_same_thread=True`）。
- LifeBrain execution thread：后台线程（`Scheduler._drive_life` → `threading.Thread(target=_decide)`）。
- Failure path：`LifeBrain.decide` → `build_snapshot` → `memory.retrieve` → 同一连接 → `ProgrammingError`，
  被 `_decide` 的 `except Exception` 吞掉 → `_pending_life_decision = None` → local utility fallback。
- Why tests missed it：所有 `test_three_brain` 在主线程 + 假 LLM + 不建真实 MemoryStore；
  workspace `furina.db` 为空（memory=0）。"空 DB + 单线程测试"系统性掩蔽多线程路径。

## 3. MemoryStore Thread Fix

- check_same_thread：`sqlite3.connect(str(db_path), check_same_thread=False)`。
- Lock type：**`threading.RLock()`**（防"读中写"嵌套如 retrieve→reinforce 自死锁）。
- Locked operations：insert / query / delete / save_relationship / load_relationship / close / 迁移（__init__）。
- Transaction behavior：写操作用 `with self._lock: with self._conn:`（自动 commit），读操作 `with self._lock:`。

## 4. Non-empty Background Thread Test

- Rows：≥2（先 `me.observe` 两条，再断言 `store.query(limit=10) >= 1`，防"空 DB 假安全"）。
- Thread：`threading.Thread(target=worker)` 从与建连不同线程调用 `retrieve`。
- Retrieve：命中（`len(ms) >= 1`）。
- Reinforcement：retrieve 内 write（strength 提升 + store.insert）执行。
- Exceptions：0。
- Result：`test_memory_store_background_thread_retrieve_nonempty` → PASS。

## 5. Concurrent Read / Write Test

- Threads：reader（retrieve/query）×200 + writer（observe/insert/reinforce）×150 并发。
- Iterations：多轮。
- Reads：retrieve + 读 content。
- Writes：observe + reinforce + insert。
- SQLite errors：**0**（`errors` 空，无 ProgrammingError/OperationalError/InterfaceError）。
- Integrity：DB 仍可读且非空（`store.query(limit=100) >= 1`）。
- Result：`test_memory_store_concurrent_read_write` → PASS。

## 6. Real Scheduler → LifeBrain → Memory Test

- Memory rows：非空（≥2）。
- Background decisions：`_drive_life` 触发 ≥1。
- LifeBrain successes：`_life_brain_success_count >= 1`。
- Local fallbacks：0（`_life_failure_count == 0`）。
- Thread errors：0。
- Result：`_pending_life_decision.activity == "read"`（决策真实到达），`test_scheduler_lifebrain_nonempty_memory_thread_path` → PASS。

## 7. Real glm Smoke

- Model：glm-4v-flash（zhipu，真实 key，非 mock）。
- Decisions：5 次 Life decisions（后台线程 + 真实 LifeBrain）。
- Memory retrievals：非空（4 rows），后台检索成功。
- LifeBrain results delivered：`life_brain_success_count >= 1`（5 次都成功）。
- Fallbacks：0。
- Errors：**sqlite/thread errors = 0**。
- 注：5 次决策都返回 "think"（smoke 环境上下文极简，模型保守；非代码问题。smoke 目的=证明管线通 + 无线程错误，非决策质量）。

## 8. Failure Observability

- Injected failure：`_FakeLifeBrain(me, fail=True)` raise RuntimeError。
- Fallback：成功（`_pending_life_decision is None` 合法）。
- Log/metric：`life_failure_count >= 1`、`life_fallback_count >= 1`（结构化 `LIFEBRAIN_DECISION_FAILED` log）。
- Result：`test_lifebrain_failure_is_observable` → PASS（fallback 保留，但不再静默）。

## 9. Relationship Single Ownership

- Before：`RelationshipEngine.apply()`（正式）+ `MemoryEngine.apply_relationship()`（旁路，绕开 trust-slow/事件语义）两个入口写同一 RelationshipState。
- After：唯一写入口 = `RelationshipEngine.apply(event)`；`app._on_meaningful_interaction` 改为 `relationship.apply(rel_ev)`；
  `MemoryEngine.apply_relationship` 标记 deprecated（`DeprecationWarning`），正式 Runtime 零调用。
- Removed runtime bypass：app 生产路径不再调用 `apply_relationship`（`test_relationship_no_memory_bypass` 读源码断言）。

## 10. Relationship Once-only Verification

| Event | Expected Delta | Runtime Delta | Apply Count |
|---|---:|---:|---:|
| EV_POSITIVE_TOUCH | comfort ↑ | comfort ↑ | 1 |
| EV_NEGATIVE_RESPONSE | annoy ↑ / comfort ↓ | annoy ↑ | 1 |

`test_relationship_event_applied_once`：一次 apply 增量 == 一次性精确增量（重复 apply 增量恒定），
正向事件 comfort 上升，无重复 apply。

## 11. Relationship Counterfactual Regression

- Positive：`EV_POSITIVE_TOUCH` → comfort ↑（verif）。
- Reject：`EV_REJECT` → annoy ↑（事件表）。
- Recovery：`decay` 使 annoy 回落（沿用 Phase 04，未改参数）。
- 结论：所有权清理未改变关系 Dynamics（未动 trust-slow / 事件增量 / decay 参数）。

## 12. body_snapshot Deprecation

- Public recommended API：**`current_frame()`**（唯一）。
- Compatibility：`body_snapshot()` 保留为只读别名 + `DeprecationWarning`。
- Warning：`test_body_snapshot_deprecated_alias` 验证产生 DeprecationWarning，且 `snap == current_frame().body`。
- Phase 11 前端禁用 body_snapshot。

## 13. Explicitly NOT Changed

S2：四层行为防重复重叠 —— **未动**（行为分布敏感，改动会重开已冻结因果实验，记为 accepted debt）。
S3：identity 双重确定性 appraise —— **未动**（只读冗余，无行为影响）。
Behavior scoring / Memory scoring / Relationship parameters / RuntimeFrame schema —— 全部未动。

## 14. 24h Post-fix Runtime

`scripts/runtime_integration.py`（3000 tick，确定性 + RC1 真实线程段）：
- Life decisions：1（后台）+ 3000 确定性 frame。
- Brain successes：`life_brain_success = 1`（非空 memory 后台路径）。
- Fallbacks：0。
- Memory retrievals：非空（2 rows）后台命中。
- SQLite/thread errors：**0**。
- Frames：invalid_frame = 0。
- Health：user-gaze 30.6%（<60）、upright 12.6%（<60）、activity diversity 12、top micro BLINK/BREATH、隐私 leak=None、frame-build 0.06ms。

## 15. Regression

Previous：265
New：8（test_rc1_freeze.py）
Total：**273**
Broken：0

## 16. Accepted Tech Debt

- S2 四层行为防重复重叠（行为分布敏感，不改）。
- S3 identity 双重确定性 appraise（只读冗余，不改）。
- 72h 独立 smoke（未扩范围；24h surrogate + RC1 真实线程路径覆盖）。
- memory relevance 精化。
- glm 对话略平（前端/模型表现）。

## 17. BACKEND RC1 Declaration

- Frozen modules：见 `docs/BACKEND_FREEZE.md`（RC1 修订记录）。
- Resolved blocker：**B1 MemoryStore thread safety**（check_same_thread=False + RLock + 后台/并发/真实 scheduler 测试 + 真实 glm 冒烟全绿）。
- Resolved ownership：**S1 Relationship single writer**、**S4 body_snapshot deprecated**。
- Accepted debt：S2 / S3 / 72h / memory relevance / glm flatness。
- Unfreeze rules：crash / causal bug / ownership violation / runtime contract insufficiency / long-run structural failure。

## 18. Verdict

**PASS（RC1）**。B1 的 SQLite 线程 BLOCKER 已解：真实 Scheduler 后台线程 + 非空 Memory 下，
LifeBrain 决策不再被静默降级（后台 retrieve/并发读写/真实 scheduler 路径/真实 glm 冒烟全部 0 线程错误，
`_pending_life_decision` 真实到达）。S1 关系改为单一写入口、S4 弃用 body_snapshot。S2/S3 按要求**未动**，
记为 accepted debt。273/273 测试全绿，265 旧测试零回归。

## 19. Recommended Next Step

**Phase 11 — Animation Runtime / Frontend Integration**（让前端真正消费 `CharacterRuntimeFrame`，
实现帧播放/timing/插值 + Asset Resolver + 桌面空间/交互渲染）。
