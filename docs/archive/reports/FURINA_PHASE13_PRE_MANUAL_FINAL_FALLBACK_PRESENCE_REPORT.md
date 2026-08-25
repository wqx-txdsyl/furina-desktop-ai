# Furina Desktop AI — Phase 13 Pre-Manual FINAL Fallback Presence Patch 报告

**评审基线：** `e5ce9fbad0d2d6d9eefd523dff5b02338976fbc5`（708 tests）
**本补丁提交：** 见文末 SHA（单个 coherent 提交）
**范围：** 仅评审列出的 fallback 模式两个生产消费者（A. StateEngine 陈旧数值 idle 重建在场；B. BehaviorEngine 无 LifeBrain 回退绕过在场真相）+ 三条生命周期路径守卫 + F1–F4 集成。
**冻结：** `e5ce9fb` 其余一切（WorldPerception/PresenceFacts/LifeBrain/Motivation/Dialogue/Embodiment/Frame/Director/Activity/Emotion/Relationship/Needs/Memory/Agent/Spatial/Harness/Persona/assets）未动，仅机械兼容性测试快照补 `idle_available` 位。

---

## 1. 复现 A —— StateEngine 用陈旧数值 idle 重建"已知在场"

**基线真实运行轨迹**（`git worktree` 检出 e5ce9fb 原样执行，`repro_before.py`）：

```
REPRO1 idle_available=False, retained idle=42 -> intent=approach_user
REPRO1 idle_available=False, retained idle=600 -> intent=approach_user
REPRO3 idle_available=False, retained idle=42 -> attention=active_window
```

t0 有效样本 idle=42 → t1 GetLastInputInfo 临时失效（idle_available=False），CharacterState 保留最后有效值 42/600。
基线 `generate_intent` 的 `presence_known = getattr(state,"idle_available",True) or bool(idle!=0 or state.user_working)` 把"保留数值 ≠ 0"当成已知在场 → 仅凭 social_need=90 产出 proactive `approach_user`；`evaluate_attention` 只在 `unavailable and idle==0` 时回落 SELF，42/600 时停在 `active_window`。

## 2. 复现 B —— BehaviorEngine 是真实的无-LifeBrain 执行者，绕过在场真相

**基线真实运行轨迹**：

```
REPRO2 idle_available=False, social_need=90 -> BehaviorEngine 选中=talk_to_user -> ACTION_REQUEST=['talk_to_user']
```

Scheduler `life_brain is None` 时走 `se.generate_intent(se.state)` + `be.step(se.state.snapshot())`。基线 `utility_of`/`choose` 完全不消费 `idle_available` → `talk_to_user = social_need×0.6 = 46.8` 压过 idle(5) 等 SELF → 发出 `BEHAVIOR_STARTED + ACTION_REQUEST(source="behavior", action="talk_to_user")`，即使运行时明确不知道用户是否在场。`user_working=True` 时 `approach_user(40)` 同样会赢。

## 3. 根因

- A：StateEngine 本地回退的 `presence_known` 由"可用性位 **或** 数值 idle/working"推导 —— 临时失效后保留数值被误当测量；Window 上下文（working/进程）与在场真相是不同的事实。
- B：BehaviorEngine（App 注册了 `observe_user`/`talk_to_user`/`approach_user` fallback）的选择/延续/链转场均无在场可行性检查 —— Pre-Manual 补丁只覆盖了 LifeBrain/Motivation 主链，本地回退链是漏网。

## 4. 最小修复（不调 utility、不改分数、不引入第二套 World）

| 文件 | 修复 |
|---|---|
| `furina/state/state_engine.py` | §1 `presence_known = bool(getattr(state,"idle_available",False))`（缺失=未知=False，不再 `or bool(idle!=0 or user_working)`）；`evaluate_attention`：`not idle_available` → `AttentionTarget.SELF`（不再要求 `idle==0`）；`observe_user`（长期目标偏置，USER 类）同样加 `presence_known` 门 |
| `furina/behavior/behavior_engine.py` | §2 `_FALLBACK_USER_DEPENDENT = {observe_user, talk_to_user, approach_user}`（匹配生产注册名，不扩大范围）+ `_fallback_presence_known(state) = state.get("idle_available") is True`（缺失=未知，不默认 True） |
| 同上 | §3.1 `choose()`：unknown 时 user-dependent 不进入选择空间 |
| 同上 | §3.2 `step()` 顶部：已有 user-dependent 行为 + 在场变未知 → 立即 `interrupt(action, reason="user_presence_unknown")` + `current=None`（不等 duration/min-stay），随后 choose 转入 SELF |
| 同上 | §3.3 链转场重查：`chain_to` 是 user-dependent 且 unknown → 不链（防御性，§3.2 已在常规流程先拦截） |
| `tests/test_skeleton.py`、`tests/test_resilience.py` | 机械兼容：手搭快照补 `idle_available: True`（生产 `CharacterState.snapshot()` 恒携带该位；缺失=未知，语义按评审） |

## 5. F1–F4 Scheduler 真实 fallback 拓扑集成证据

拓扑：`Scheduler + StateEngine + BehaviorEngine(生产等价注册) + Director(真实) + EventBus + WorldPerception + WindowAwareness fake`，`life_brain=None` 走生产回退分支，确定性假时钟（monotonic/localtime），捕获 `BEHAVIOR_STARTED/ACTION_REQUEST/BEHAVIOR_INTERRUPTED/BEHAVIOR_COMPLETED`。

| 场景 | 构造 | 断言 |
|---|---|---|
| **F1 启动未知** | idle 恒 None（占位 0）、social_need=90、6 medium tick | `presence_facts known=False`；`world.user_activity=UNKNOWN`；无任何 user-directed ACTION_REQUEST；SELF 请求存在（`play`）；`attention=SELF`；StateEngine intent≠approach/observe |
| **F2 临时失效·保留活跃值** | 有效 idle=42 → 失效（保留 42） | canonical unknown；`user_idle_seconds==42`（仅连续性/debug）；`attention=SELF`；失效后 StateEngine/BehaviorEngine 均无 proactive social；运行中的 user-dependent 行为被 `BEHAVIOR_INTERRUPTED` |
| **F3 临时失效·保留 away 值** | 有效 idle=600 → 失效（保留 600） | `known=False`（unknown ≠ measured-away）；同 F2 无 social；SELF 生命继续 |
| **F4 有效在场恢复** | 未知 → idle=42 有效 | `known=True, present=True`；talk_to_user 重新可选（既有 utility 规则），证明非一刀切禁社交 |

**修复后对照真实运行轨迹**（工作树 `after_verify.py`，与基线同输入）：

```
AFTER1 idle_available=False, retained idle=42 -> intent=idle
AFTER1 idle_available=False, retained idle=600 -> intent=idle
AFTER2 idle_available=False, social_need=90 -> BehaviorEngine 选中=wander -> ACTION_REQUEST=['wander']
AFTER3 idle_available=False, retained idle=42 -> attention=self
```

## 6. 全量回归

| 基线（e5ce9fb） | 本补丁 |
|---|---|
| 708 passed / 0 failed | **734 passed / 0 failed**（+26：`tests/test_phase13_fallback_presence.py`；23.9s） |

新增 26 项覆盖评审 §4/§5 全部要求名单：
- StateEngine：`test_state_fallback_unknown_retained_idle_42_no_social` / `_600_no_social` / `test_state_fallback_unknown_working_true_no_social` / `test_attention_unknown_retained_idle_42_is_self` / `_600_is_self`（另附 0/10/300 全覆盖）/ `test_state_fallback_valid_present_still_can_socialize`。
- BehaviorEngine（事件捕获型，`idle=42` 与 `idle=600` 两组）：`test_behavior_fallback_unknown_no_talk_action_request` / `_no_observe_user_action_request` / `_no_approach_action_request` / `test_behavior_fallback_unknown_keeps_self_behavior_available` / `test_behavior_fallback_existing_social_stops_when_presence_becomes_unknown` / `test_behavior_fallback_unknown_does_not_chain_observe_to_approach` / `test_behavior_fallback_valid_present_social_still_works`。
- Scheduler 集成：`test_scheduler_f1_startup_unknown_no_proactive_social` / `test_scheduler_f2_sensor_failure_retained_active_idle_no_social` / `test_scheduler_f3_sensor_failure_retained_away_idle_unknown_not_away` / `test_scheduler_f4_valid_present_restored_social_eligible`。

既有 708 全绿未动（机械兼容仅补 `idle_available` 位：`test_skeleton.py` 3 处、`test_resilience.py` 1 处；这些测试手搭快照未携带生产恒有的可用性位）。

## 7. STOP

```text
Technical = READY_FOR_REVIEW
Manual = NOT STARTED
Persona = NOT REVIEWED
Overall = REVIEW_REQUIRED
```

未声称 Manual PASS。评审只复核三项：A. StateEngine 不能从陈旧保留 idle 重建已知在场；B. BehaviorEngine 无-LifeBrain fallback 不能绕过在场真相；C. 有效在场恢复既有 fallback 行为。三项通过后 → `PHASE 13 TECHNICAL = PASS / PRE-MANUAL AUDIT = PASS / BACKEND FUNCTIONAL CONTRACT = FROZEN` → 立即进入 **Manual Experience Acceptance**（A. 评审可执行模拟测试 / B. 用户真实 Windows·真实 API·主观体验测试），Manual 通过后才进入 Phase 14。此后不再做 Manual 前的源码评审轮。
