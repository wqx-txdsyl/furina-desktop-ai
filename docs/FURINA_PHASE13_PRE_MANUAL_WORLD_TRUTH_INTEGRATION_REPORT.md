# Furina Desktop AI — Phase 13 Pre-Manual World Truth Integration 报告

**Review baseline:** `32bc11be795484e82449dc776624a29eac49dd1f`（672 tests）
**范围**：仅关闭「WorldPerception 真相 → CharacterState/LifeBrain/Motivation/Dialogue/Embodiment/social 语义」集成簇。
其余 Phase 13 契约全部 FROZEN，未触碰（Director/Activity/Outcome/Emotion/Relationship/Needs/Dialogue FIFO/Validator/Memory/Agent/Spatial/Harness）。

---

## 1. 根缺陷复现

World 层已正确区分 `idle_available=False / UNKNOWN / user_active=False / availability=0`，但多个下游消费者仍从**旧数字占位** `user_idle_seconds=0.0` 重建在场：
- `LifeBrain.build_snapshot`：`active = user_working or idle<300` → 不可用时报 `active=True`；且 `to_dict()` 在 WorldState 上、`WorldPerception` 上没有 → world 块被静默省略（Motivation 却用 factors() 正确消费 → 双真相）。
- `interaction_opportunity`：不可用 + 0 → `if not working: score += 18`（反而鼓励主动）。
- Motivation `_feasible`：不可用分支里 `user_present` 仍 True → user-directed 候选可行。
- Scheduler raw-idle return 检测器：0 占位伪造 EVENT_RETURN；`begin_social_bid` 只挡 `idle>=300`（0 通过 → 60s 后假 USER_IGNORE）；自主 Dialogue/Embodiment/Frame 用 `idle<300` 重建 present。

## 2. 全部 legacy raw-idle 消费路径

```
life_brain.build_snapshot（user.active / idle_seconds / appraisal user_present 默认 True）
life_brain.interaction_opportunity
scheduler._tick_medium（raw-idle return 检测器）
scheduler.begin_social_bid（idle>=300 门）
scheduler._freeze_ambient/_reaction_snapshot、_update_scene（expression appraisal + embodiment）
scheduler._update_scene Frame speech（dialogue_act/mode 的 solitude/user_present）
state_engine.evaluate_attention / generate_intent（本地回退）
```

## 3. Canonical presence/world 边界

- `WorldPerception.to_dict()` = `WorldState.to_dict()`（**规范世界快照接口**，LifeBrain 等统一消费）。
- `presence_facts(world, explicit_user_event=False)` → `{known, present, active, idle_seconds, source}`：
  - 显式用户事件 → known/present/active=True（不伪造 OS idle）；
  - 有效 OS world（idle_available=True）→ 用 user_present/user_active/user_idle_seconds；
  - 其余 → known=False, present=False, active=False, idle_seconds=None（**unknown ≠ away**）。
- `WorldPerception.factors()` 增加 `idle_available` / `presence_known`。

## 4. 生产修复（按 §）

| § | 修复 |
|---|---|
| §1 | LifeBrain world 块走 `WorldPerception.to_dict()`（不再静默省略；含 user_activity/idle_available/foreground_app） |
| §3 | LifeBrain `_user_snapshot` 消费 presence_facts：`presence_known/present/active/idle_available/idle_seconds(可 null)/working`；CharacterAppraisal 用 canonical `pf["present"]`（未知→False，不再 `getattr(..., True)`） |
| §4 | `interaction_opportunity`：`presence_known=False → 0`（不主动；显式用户事件走即时反应路径） |
| §5 | `_feasible`：`presence_known<0.5` → 用户定向候选 infeasible（reason=user_presence_unknown/world_idle_unavailable），SELF 保持可行 |
| §6 | 删除 raw-idle return 检测器；`USER_RETURNED` 按**事件实例**（last_events）消费 → EVENT_RETURN 恰好一次；顺带修复 World `_prev_present` 在场真值翻转跟踪（否则 pending 稳定期会每 20s 重发） |
| §7 | `begin_social_bid` 要求 `known and present`（否则 60s 后假 USER_IGNORE） |
| §8 | 自主 Dialogue 快照/expression/embodiment/Frame 全用 canonical presence：unknown → present=False, solitude=False, presence_known=False；`DialogueContextSnapshot` 加 `presence_known`（向后兼容默认 True）；`DialogueBrain.say` 接受该字段 |
| §9 | submit_user_message/submit_feed/互动反应快照：presence_known=True/present=True/solitude=False（显式事件证据；不伪造 OS idle，持久 World 保持不可用） |
| §10 | 本地回退 `generate_intent`：在场未知不产生 proactive approach_user；`evaluate_attention`：不可用+占位 0 → SELF |

## 5. 跨模块场景 A–E（确定性）

```
A 启动/idle 不可用：World UNKNOWN+user_active=False；LifeBrain presence_known=False/active=False/world 在快照中；
   interaction_opportunity==0；Motivation 过滤 talk/approach；approach_user 执行不开 bid；无 ignore/return；SELF 可行
B 有效在场(10s, code)：presence_known/present=True；world coding；working=True；opportunity>0；talk 可行
C 有效 away(600s)：snapshot presence_known=True/present=False/solitude=True；talk infeasible；approach_user 不开 bid
D OS 不可用但显式对话：该快照 known/present=True/solitude=False；持久 World 仍 idle_available=False+UNKNOWN
E 真实 return：away→active → EVENT_RETURN 恰好一次；历史串残留不重触发；第二次真实 return → 第二个
```

## 6. 回归

| 基线（32bc11b） | 本 patch |
|---|---|
| 672 passed / 0 failed | **708 passed / 0 failed**（+36：test_phase13_premanual.py） |

既有测试适配（机械兼容）：three_brain 互动机会测试附加有效 World；社交 bid 测试桩提供有效在场；
`test_user_absent_does_not_create_fake_ignore` 同步 canonical World away。其余 672 全绿未动。

## 7. STOP

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

未声称 Manual PASS。评审只复核本 World Truth 集成簇；通过则 **PHASE 13 TECHNICAL = PASS / BACKEND FUNCTIONAL CONTRACT = FROZEN / PRE-MANUAL AUDIT = PASS** → Manual Experience Acceptance（A. 评审可执行模拟测试 / B. 用户真实 Windows·真实 API·主观体验测试；Manual 通过后 → Phase 14）。
