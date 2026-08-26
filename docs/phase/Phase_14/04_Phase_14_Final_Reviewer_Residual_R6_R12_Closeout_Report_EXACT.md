# Phase 14 Final Reviewer Residual R6–R12 — Closeout Report

## 1. Result

```text
READY_FOR_FINAL_REVIEW
```

Final PASS 由独立 reviewer（GPT-5.6 Sol）判定，本报告不自行输出。

## 2. Baseline

- baseline_sha: `41bec530f80dd7925b359dc2434d7f00754636cc`
- branch: `fix/phase14-final-reviewer-r6-r12`
- final_sha: 见 §14（本任务最后一个 commit 的完整 SHA）

## 3. Commit list

见 §14（commit 列表 + 推送结果；均位于 `fix/phase14-final-reviewer-r6-r12`，不合并、不推 master）。

## 4. Modified files

| file | reason | contract affected |
|---|---|---|
| `furina/app.py` | R6 fail-closed：`_observe_with_provenance` C6 失败 → return None 不落库；R10 两阶段 ingress 重排（reserve → USER_MESSAGE → apply C4 → freeze → enqueue → 幂等 consume）；R11 pet/poke/drag 独立 event_type | `_observe_with_provenance` 行为 fail-closed；`submit_user_message` 内部顺序（可观察事件顺序变化：USER_MESSAGE 先于 C4 效果；turn 终态保证不变） |
| `furina/runtime/scheduler.py` | R8：`begin_social_bid` E1 持久化失败 fail-closed（不开窗口）；新增 `_cancel_social_bid`（幂等）；`on_mind_preempted` 对执行型 bid 失效 | `begin_social_bid`/`on_user_ignore` 行为硬化（可选参数向后兼容） |
| `furina/runtime/dialogue_queue.py` | R10：两阶段 ingress —— `reserve_turn`/`submit_reserved`/`cancel_reserved`；DirectTurn 新增 RESERVED 状态 | 新增公开 API；`submit` 保持原语义 |
| `furina/cognition/bridge.py` | R10：`record` 返回 event_id（原 bool）；新增 `process=False` 延迟批处理 | `record` 返回值类型变化（无既有调用者依赖 bool） |
| `furina/cognition/hub.py` | R10：`apply_user_message` 接受 `source_event_id`/`turn_id`；`_ensure_transition_event` 创建精确引用 U 的 derived T（含 dedupe 复用） | `apply_user_message` 新增可选参数；transition 事件 payload 新增 `source_event_id` |
| `furina/cognition/consolidation/consolidator.py` | R11：USER_PET/USER_POKE/USER_DRAG 各自确定性语义；USER_DRAG 移出 EVENT_ONLY（重要 drag 可形成 C3） | 无 |
| `furina/cognition/interpretation/interpreter.py` | R11：USER_POKE/USER_DRAG 分支；USER_PET 仅 petting | 无 |
| `furina/cognition/stores/canon_history.py` | R7：语义 validator（duplicates/unregistered/act support）+ 两类完整性分离 metrics（`mandatory_life_stage_source_status` / `main_story_act_coverage_status` / `missing_main_story_acts` 等） | metrics 输出扩展（只增不改） |
| `pyproject.toml` | R12：声明 `python-docx>=0.8.11` / `python-pptx>=0.6.18` / `openpyxl>=3.0.7`（production Office 能力实际 import 的运行时依赖） | 运行时依赖声明（版本下限保守） |
| `tests/cognition/test_phase14_final_reviewer_r6_r12.py` | **新增** 30 个 reviewer-locked 测试（含 counterexample A–F） | 新测试 |
| `tests/test_phase13_h1final.py` | R11 取代 USER_PET 伞型：poke→USER_POKE、drag→USER_DRAG 断言更新（3 处，已报告） | 断言更新（语义被 R11 正确取代） |
| `tests/cognition/test_phase14_final_closure.py` | R11 取代：C3-T8/T8b 改用 USER_POKE/USER_DRAG 客观类型（2 处，已报告） | 断言更新 |
| `docs/persona/FURINA_CANON_LIFE_SOURCE_MAP.md` | R7：两类完整性分离表述；Act II/III 缺失与 INNER_WORLD_REVELATION 缺口如实报告 | 文档 |
| `docs/phase/Phase_14/04_...Closeout_Report_EXACT.md` / `00_MANIFEST.md` / `RECOVERY_LEDGER.md` | 本任务文档协议 | 文档 |

## 5. R6 — C3 fail-closed proof

BEFORE counterexample：`_observe_with_provenance` 在 `record_event` 异常时 `except: pass` 后仍以
`source_event_ids=[]` 调用 `memory.observe` —— C6 失败仍可能形成 provenance-less C3。

AFTER production path（`furina/app.py`）：

```text
cognition 装配（production）
  ├─ record_event(USER_STATEMENT_OBSERVED) 成功 → [ev.event_id] → memory.observe（正常）
  └─ record_event 异常 / 无有效 event_id → log.warning + return None
       → 不调用 memory.observe → 无新 C3 行（FAIL CLOSED）
cognition=None（legacy 兼容外壳，非生产路径）→ 保持旧行为（仅旧隔离单测可达）
```

- R6-T1（COUNTEREXAMPLE A）：强制 record_event 抛异常 → 记忆数不变、无新 C3、无
  USER_STATEMENT_OBSERVED 事件。BEFORE 版本此测试失败（会形成无 provenance 记忆）。
- R6-T2：成功路径 C3 带 provenance 且解析到真实事件。
- R6-T3：静态锁定 —— 方法体内必须 FAIL CLOSED + return None，禁止旧 swallow-and-continue 模式。
- R6-T4：USER_FEED / USER_POKE / USER_IGNORED / verified AGENT_COMPLETED 全部保持可解析 provenance。

## 6. R7 — Canon completeness proof

| 指标 | 值 |
|---|---|
| `canon_span_status`（结构，兼容锁定） | `MANDATORY_SPAN_SOURCE_COMPLETE` |
| `mandatory_life_stage_source_status`（语义） | `PARTIAL:episodes_without_exact_act_main_story_evidence=['INNER_WORLD_REVELATION']` |
| `main_story_act_coverage_status` | `PARTIAL` |
| `missing_main_story_acts` | `["II", "III"]` |
| `main_story_act_coverage` | `{"I": True, "II": False, "III": False, "IV": True, "V": True}` |
| `evidence_attribution_conflicts` | `[]` |
| `evidence_registry_duplicates` | `[]` |
| `unregistered_evidence_ids` | `[]` |
| FUR-006 | MAIN_STORY / Chapter IV / Act I（保持） |
| FUR-052 | CHARACTER_STORY / act=null（保持；R7-T5 证明其无法满足任何精确主线 act） |

为何“官方但语义不符的来源”无法再让 completeness 变绿：完整性计算现在区分两类概念 ——
结构 provenance（dangling/冲突/注册表有效性）与语义 act 支撑（exact-act episode 必须由
`MAIN_STORY + quest=Chapter IV + 同一 act` 的证据支撑）。CHARACTER_STORY/VOICE_LINE/PROFILE
且 act=null 的 evidence 无论多官方都不计入 act 支撑（R7-T1 fixture 证明）；act 错配产生
冲突并使语义状态脱离 SOURCE_COMPLETE（R7-T2）。Act II/III 无 curated 主线单元 → 如实
`PARTIAL + missing ["II","III"]`（R7-T6/T7）；INNER_WORLD_REVELATION 的 act=V 主张缺乏
同 act MAIN_STORY 证据 → 如实列出缺口，未伪造支撑（R7-T6）。全部断言读取 production
reader（CanonHistoryStore），fixture 反例使用临时文件、不修改生产数据。

## 7. R8 — Social bid lifecycle

| 场景 | SOCIAL_BID_STARTED | USER_IGNORED | ignore C3 |
|---|---|---|---|
| 正常开启（on_mind_action_started） | 1 | — | — |
| 正常超时（R8-T4） | 1 | 1 | 1（source=[E2, E1]） |
| 用户回应（R8-T3） | 1（客观事实保留） | 0 | 0 |
| E1 持久化失败（R8-T1） | 0（fail-closed，不开窗口） | 0 | 0 |
| Agent 抢占（R8-T2） | 1（bid 客观开启过） | 0 | 0 |
| 重复取消/tick（R8-T5） | 1 | 0 | 0 |

- E1 失败：`begin_social_bid` 在 cognition 装配下 record_event 失败/无有效 id → **不创建
  pending 窗口**（无 canonical bid 事件 = 无 canonical ignore 计时器）。
- Furina 侧中断：`on_mind_preempted`（Director on_before_replace 统一入口，覆盖
  preempted_by_agent / preempted_by_user / interrupted）对执行型 bid
  （reason=`executed:<activity>`，如 approach_user）调用 `_cancel_social_bid`（幂等）——
  被抢占的 bid 到期不再产生 USER_IGNORED。spoken 型 bid（可见台词已出话）不受后续活动
  抢占影响（用户确实看到了那次尝试）。shutdown：进程终止后无 tick 可触发（无假 ignore）。

## 8. R9 — Real Director E2E

真实运行链（`test_r9_real_director_e2e_production_wiring`）：

```text
Director.submit(ActionRequest(source=mind, action=approach_user, pri=P_INTERNAL_NEED))
    ↓ real director.drain()
App._on_execute（真实 executor 回调）
    ↓
Scheduler.on_mind_action_started("approach_user")
    ↓
SOCIAL_BID_STARTED lev_1787755045108_a1de0417
    ↓ deadline 到期（测试按规则拨快）
USER_IGNORED      lev_1787755045160_7de2b779  source=lev_1787755045108_a1de0417
    ↓ CognitionHub consolidation
MEMORY mem_1787755045168_447236 source_event_ids=['lev_...7de2b779', 'lev_...a1de0417']
```

测试**不直接调用** `sched.on_mind_action_started` —— 若删除 `App._on_execute → Scheduler`
生产 wiring，drain 后无 SOCIAL_BID_STARTED → 测试失败（COUNTEREXAMPLE D 成立）。
同一测试断言 exactly-once；`test_r9_agent_preemption_invalidates_bid_real_director` 用真实
Director 仲裁（agent pri=2 < mind pri=3 → on_before_replace → preempted_by_agent）证明
被抢占 bid 不产生 USER_IGNORED（COUNTEREXAMPLE C，real Director 版）。

## 9. R10 — Exact utterance provenance

真实 trace（`test_r10_t1` 路径，同一 turn）：

```text
DirectTurn.turn_id            = 2
USER_MESSAGE.event_id         = lev_1787755045273_8f69b4ba   turn_id=2  text='我现在不喝咖啡了'
USER_PREFERENCE_CHANGED T.id  = lev_1787755045288_6fe2ccaf   turn_id=2
T.payload = {'key': 'preference:咖啡', 'statement': '我现在不喝咖啡了',
             'source_event_id': 'lev_1787755045273_8f69b4ba'}
C4 row.transition_event_id    = lev_1787755045288_6fe2ccaf
turn identity matches         = True（U.turn_id == T.turn_id == DirectTurn.turn_id）
```

- 实现：`submit_user_message` 改为两阶段 ingress —— `reserve_turn`（ingress 即起算
  deadline，DirectDialogueQueue 保持唯一 turn_id authority）→ `bridge.record(USER_MESSAGE,
  process=False)`（返回精确 event_id）→ `apply_user_message(source_event_id=U, turn_id)`
  → freeze → `submit_reserved` → 幂等 `process_pending`（dedupe 复用同一 T）。
- R10-T3（COUNTEREXAMPLE E）：两回合说相同文本"我现在不喝咖啡了" → 各自的 transition
  按 event id / turn id 精确绑定到各自 USER_MESSAGE（文本相等不足以区分）。
- R10-T5：无循环 —— T.payload.source_event_id ≠ T.event_id；row → T → U 一跳解析到
  verbatim 文本。
- R10-T7：reserve 后 owner 准备失败 → `cancel_reserved` → turn 到达可观察 CANCELLED
  终态；后续 turn 正常分配/终态（无 sequence hole / 永久 pending）。
- R10-T6：DirectDialogueQueue FIFO / deadline 既有测试保持绿（Gate D 覆盖）。

## 10. R11 — physical event truth

| 互动 | C6 event_type | C3 内容 | event_type（memory） |
|---|---|---|---|
| petting | `USER_PET`（恰好 1，无 POKE/DRAG） | 用户轻轻摸了摸我的头 | user_positive_touch |
| poke（普通） | `USER_POKE`（恰好 1，无 PET） | 用户戳了我一下 | user_poke |
| poke（count>5） | `USER_POKE` | 用户反复戳了我N下（拒绝语义，非摸头） | user_annoying_poke |
| drag | `USER_DRAG`（恰好 1，无 PET） | 用户把我拎起来移动 | user_drag |

R11-T1..T3 经真实生产互动路径（`InteractionEngine.emit_event` → App 回调）驱动；
T4/T5 验证 C3 内容与真实互动一致；T6 验证全部 provenance 精确解析。
`USER_DRAG` 已从 Consolidator 的 EVENT_ONLY 集合移除（重要 drag 互动按产品语义可形成 C3）。

## 11. R12 — Office / dependency truth

四个原始失败（基线 1184 passed / 4 failed）：

| 失败测试 | root cause 分类 | fix |
|---|---|---|
| `test_docx_create_reopen_verify` | **B**：production 能力（docx.create）实际 import `python-docx`，但依赖未声明在 pyproject | `pyproject.toml` 运行时依赖 += `python-docx>=0.8.11` |
| `test_pptx_create_reopen_verify` | **B**：production import `python-pptx` | += `python-pptx>=0.6.18` |
| `test_xlsx_create_reopen_verify` | **B**：production import `openpyxl` | += `openpyxl>=3.0.7` |
| `test_3_production_nl_docx_plan` | **B**：PlannerV2 → docx.create 同源缺依赖 | 同上（依赖安装后通过） |

import 证据：`furina/agent/capabilities/documents/__init__.py`（`from docx import Document` /
`from pptx import Presentation` / `from openpyxl import Workbook, load_workbook`）。
依赖安装后四个测试全部通过（4 passed）。**无 skip / xfail / 断言弱化 / 删除**。

## 12. Static sink / authority audit

```text
observe callers       : app._observe_with_provenance（C6-first, fail-closed）/
                        hub._form_memory（canonical）/ autobiography.observe（delegate）
consolidate callers   : autobiography.consolidate（delegate；生产零调用）
MemoryStore.insert    : memory_engine（engine 内部）/ autobiography.insert（delegate）/
                        hub._form_memory（reinforce 写回）
raw memories SQL      : 仅 furina/memory/memory_store.py
C6 physical emitters  : app._on_meaningful_interaction（USER_PET/USER_POKE/USER_DRAG 各自客观类型）
USER_MESSAGE creation : app.submit_user_message（bridge.record, process=False 两阶段）
social bid sites      : begin（on_mind_action_started/_ambient_work）/ cancel（on_mind_preempted）/
                        tick（_tick_medium → _tick_social_bid）
USER_PREFERENCE_CHANGED / USER_PLAN_COMPLETED：hub._ensure_transition_event（exact U linkage）
Canon completeness    : canon_history.metrics（结构 + 语义分层）
Office imports        : documents/__init__.py ↔ pyproject 三包已声明
```

## 13. Test results

- New reviewer tests（R6–R12）: **30 passed**（Gate A）
- Previous final closure: **19 passed**（Gate B；2 处断言因 R11 取代 USER_PET 伞型而更新，
  已在上文报告）
- Previous residual closure: **15 passed**（Gate C，零修改）
- Phase 15 preservation: **18 + 6 = 24 passed**（Gate E）
- Agent integration: **81 passed**（Gate F，含此前 4 个 Office 失败修复后全绿）
- Targeted cognition/memory/scheduler/queue/director: **262 passed**（Gate D）

```text
Full run #1: passed=1218  failed=0  skipped=0  duration≈137s
Full run #2: passed=1218  failed=0  skipped=0  duration≈156s
Full run #3: passed=1218  failed=0  skipped=0  duration≈157s
```

## 14. Git state

- git status --short before commit：见 commit 前状态（修改文件 = §4 列表 + 既有未跟踪
  `docs/phase/` 与 `nul` 未触碰）。
- commit：本任务实现以 1 个 commit 提交于 `fix/phase14-final-reviewer-r6-r12`。
- push result：`git push origin fix/phase14-final-reviewer-r6-r12` 成功。
- remote branch: `fix/phase14-final-reviewer-r6-r12`
- final remote SHA: 见 git log（任务最后 commit 完整 SHA）

## 15. Remaining gaps

```text
No known R6–R12 implementation blockers remain.
Final PASS is intentionally deferred to the independent reviewer.
```

如实说明（非 blocker）：Chapter IV Act II/III 与 INNER_WORLD_REVELATION 的 act=V 精确
主线证据在 curated evidence 集中确实不存在 —— 已按 R7 要求以 `PARTIAL` + 明确缺口列表
暴露，未伪造来源；文档与 metrics 一致。
