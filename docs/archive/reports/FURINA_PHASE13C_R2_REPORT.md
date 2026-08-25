# Phase 13C — C-R2 Final Contract Closeout

## 0. Verdict
```
Technical:  READY_FOR_REVIEW
Manual:     NOT STARTED
Persona:    PENDING
Overall:    REVIEW_REQUIRED
```

> 不写 Phase 13 PASS。仅修正已证实的 production contract bugs。

---

## 1. BEFORE（复现 reviewer 证据）

```
RelationshipState{ familiarity=50, trust=50, comfort=60, annoyance=20,
                   user_response_rate=.5, user_rejection_rate=.2 }

RelationshipEngine.factors():        trust=.5 comfort=.6 annoyance=.2 response_rate=.5 confidence=.8
BehaviorMotivation._rel():           response_rate=.005 confidence=.998   ← WRONG（/100 了 0..1 字段）
LifeBrain._relationship_factors():   trust=1.0 comfort=1.0 annoyance=1.0 familiar=1.0  ← WRONG（0..1 clamp 到饱和）

EV_POSITIVE_RESPONSE → user_response_rate=1.3   ← _bump 仍对所有字段 clamp 0..100（0..1 字段可越界）
```

## 2. AFTER（精确数值）

```
RelationshipEngine.factors():        trust=0.500 comfort=0.600 annoyance=0.200 response_rate=0.500 confidence=0.800
BehaviorMotivation._rel():           response_rate=0.500 confidence=0.800
LifeBrain._relationship_factors():   trust=0.500 comfort=0.600 annoyance=0.200 familiar=0.500
EV_POSITIVE_RESPONSE → user_response_rate=0.550  （≤1，无 1.3）
```

## 3. 修改（按 reviewer 逐项）

- **一个 canonical 归一化**：`furina/relationship/engine.py` 新增模块函数 **`relationship_factors(rel)`**（唯一实现）；`RelationshipEngine.factors()` 委托它。`BehaviorMotivation._rel`、`LifeBrain._relationship_factors`、Dialogue/Embodiment 全部改为调用它，**不再各自 /100 或 /1**。
- **canonical 单位**：0-100 raw（familiarity/trust/comfort/attachment/respect/dependency/annoyance/interaction_tolerance/social_confidence）→ `/100`；0..1 raw（user_response_rate/user_rejection_rate）→ 原样；派生 response_rate/confidence/interaction_freq（0..1）。`None`/缺失字段用**中性默认**（rate .5、confidence .5、接纳度 .5），避免"无关系"饱和。
- **写侧 unit**：`_bump` 按字段单位夹紧 —— rate 字段 0..1、0-100 字段 0..100、计数 ≥0、时间戳原样。
- **事件 delta 单位迁移**：rate 字段增量从 0.8/0.6 迁移为 0..1 的**小增量**（+0.05 / +0.04），保证 `0<=rate<=1`，不出现瞬时 1.3。
- **Reject 双写**：`Scheduler.on_user_reject` **不再手动 bump** `rejection_count/user_rejection_rate/user_response_rate`（这些由 `RelationshipEngine.apply(EV_REJECT)` 唯一拥有）；一次 reject = apply 一次 + 持久化一次 + tolerance 一次 + life interrupt 一次。
- **BehaviorMotivation / LifeBrain canonical**：`_rel(state)`、`_relationship_factors(state)` 只经 `relationship_factors()`（执行真实生产路径，非源码 grep）；精确数值吻合。
- **Dialogue normalized**：`furina_character_contract.mode_for` 归一化阈值（.6/.25/.55）；`expressive.mode()` 不再 ×100 传给 contract（Dialogue 收到 0..1）。
- **Positive text 持久化**：`_apply_user_text_fx` 高置信称赞/谢意 apply 后**持久化一次**，state 引用保持共享。
- **Persona 路由**：`_route_example_context` 修复 `agent_fail → agent_failure`（成功/报告 → agent_success）；删除全部舞台动作括号例子（user_busy/user_return/ignored/quiet 重写）。

## 4. 行为级验证（tests/test_c2_contract.py，10 条）
```
test_relationship_canonical_normalizer_exact        （.5/.6/.2/.5/.8 精确）
test_relationship_rate_write_clamps_01              （response_rate 0.55 ≤1）
test_positive_response_rate_never_exceeds_one       （30 次连加仍 ≤1）
test_reject_stats_increment_once_real_route         （rejection_count=1，rate<0.5）
test_behavior_motivation_relationship_scale_exact   （response_rate=.5 confidence=.8）
test_lifebrain_appraisal_relationship_scale_exact   （.5/.5/.6/.2 非饱和）
test_dialogue_annoyance_normalized_branch           （.7→GUARDED，.2 不触发）
test_text_positive_response_persists_once           （保存一次 + 共享引用）
test_agent_failure_selects_agent_failure_example    （agent_fail→agent_failure）
test_no_stage_direction_in_any_example              （无任何动作括号）
```

## 5. Regression
```
Previous: 441
New:      10 (test_c2_contract.py)
Total:    451
Broken:   0
```

## 6. 剩余（诚实）
- Persona 盲评 / 真实 15-turn / 空间天然性人工确认（属 reviewer/用户）。
- Harness trace 新字段（§55）未本轮新增（诊断增强，非功能性阻断）。

## 7. STOP
停止开发。请 reviewer 复核报告+代码（工作区为最新完整代码；本环境无法打 ZIP，库中即最终版）。
若上述显式不变量全部确认：进入 **Manual Experience Test**（无 C-R3 常规优化）。不开始 Phase 14、不补素材、不调参。
