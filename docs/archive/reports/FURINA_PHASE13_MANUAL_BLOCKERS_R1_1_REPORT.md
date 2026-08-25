# Furina Desktop AI — Phase 13 Pre-Manual Blocker Repair R1.1 (Reviewer Residual Gate) 报告

**冻结基线：** `250aa748bba5a1aac095914eed0f9fe7569f0db9`（774 tests）
**分支：** `fix/phase13-manual-blockers-r1-1`（本补丁提交见文末）
**范围：** 仅评审列出的 6 个 R1.1 residual（R1.1-1..R1.1-6）。未改任何测试来掩盖问题；新增 residual 测试 24 项，原 774 全部保留。

---

## A. ROOT CAUSE / FIX（逐 residual）

### R1.1-1（P0）dialogue_brain=None 静默丢消息
- 根因：`submit_user_message` 里 `if db is not None: queue.submit(...)` —— db=None 时无 DirectTurn、无终态、无 SYSTEM_STATUS、无 trace，用户消息静默消失。
- 修复：**无条件入队**（owner 恒产生 DirectTurn + DIRECT_INGRESS/QUEUED trace）；worker 处理器 `_brain_worker` 在 `db is None` 时返回 `FAILED(reason=dialogue_brain_unavailable)` 并 `_system_status_failure()`（SYSTEM_STATUS 不进 Persona history）；db 恢复后下一条消息正常走真实链路。

### R1.1-2（P0）_trim 删除活跃 turn
- 根因：`_trim()` 按 `len(_order) > keep` 从最旧弹掉 **QUEUED/GENERATING** turn → worker 之后 `turn is None → continue`，消息永久不执行 + DialogueBrain direct seq 缺口，后续回合全堵。
- 修复：`_trim_locked()` 只清理 **terminal** 前缀观测（单 worker 串行 → 终态成前缀），遇到活跃 turn 立即停止；`keep_outcomes` 只限制 terminal history 条数，活跃 turn 永远保留。

### R1.1-3（P1）timeout 不是总预算
- 根因：`say(timeout=)` 按**单次生成**计算 → attempt1 超时后 retry 又拿全新 timeout，一回合可接近 2×timeout；queue.timeout 只是装饰品。
- 修复：新增独立配置 `AppConfig.direct_turn_timeout`（默认 30s，用户可见总预算；不改 LifeBrain/Agent/transport 语义）。`DirectDialogueQueue.timeout` = **整回合总生命周期预算**：worker 开工时为 turn 设 `deadline = now + timeout`，processor 经 `say_with_result(..., deadline=turn.deadline)` 传入；`_generate_bounded` 每次取 `remaining = deadline - now`，`remaining<=0` 立即 `generation_timeout`，**attempt+retry 共享同一 deadline，validator/retry 不重置预算**。代码与注释一致。

### R1.1-4（P1）Persona 身份 AI/游戏元叙事污染
- 根因：`FURINA_PERSONA` 首行"一个住在用户电脑桌面里的 AI 数字生命 / 来自《原神》枫丹"与"不是 AI 助手"自相矛盾（上游身份污染，validator 拦输出救不了上游）。
- 修复：改为 **in-world identity**："你是芙宁娜本人——一个来自枫丹、如今生活在用户电脑桌面这个小世界里的普通人"，移除 "AI 数字生命/AI助手/来自《原神》/游戏角色"，保留 芙宁娜/枫丹 与角色历史人格。工程侧仍是 AI（技术文档/代码注释不动）。

### R1.1-5（P1）activity grounding 单一特例
- 根因：只覆盖 stationary vs explore 声称（单特例）。
- 修复：确定性 **activity-claim ontology**：10 个语义组（READ/EAT/DRINK/REST/SLEEP/EXPLORE/WANDER/WALK/PLAY/WORK/THINK/IDLE）+ 每组现在时声称 pattern（`正?在X` 类，非 exact-string）+ 互斥矩阵 `_CONFLICTS`。回复明确声称与真实 activity **互斥的当前行为** → `ungrounded_activity`；同组自声称 / 无互斥声称 / 自然描述（不出现活动名）→ 合法。

### R1.1-6（P2）重复定义 + 共享诊断值竞争
- 根因1：`_gate_wait/_gate_release` 存在重复定义（上一轮编辑残留）。
- 根因2：`_brain_worker` 在 say() 后读共享 `last_failure_reason` —— direct 与 ambient 并发时可能读到对方改写的值。
- 修复1：删除重复定义，保持唯一实现（含 `_ambient_gate_*`）。
- 修复2：新增内部 result API `say_with_result()` → `{"speech","failure_reason","validation_issues"}`（**per-call result**，随本调用返回）；`_brain_worker`/queue processor 改用 per-call result；共享 `last_failure_reason/last_validation_failure` 仅保留为诊断/兼容（`say()` 公开 API 不变）。

## B. FILES CHANGED
`furina/dialogue_brain.py`（R1.1-3 deadline+say_with_result/_say_dispatch 重构；R1.1-6 去重+per-call） · `furina/runtime/dialogue_queue.py`（R1.1-2 trim 修复+deadline 总预算） · `furina/app.py`（R1.1-1 无条件入队+db=None 终态；R1.1-3 direct_turn_timeout 接线） · `furina/config/app_config.py`（direct_turn_timeout） · `furina/dialogue/validator.py`（R1.1-5 ontology+矩阵） · `furina/persona/furina_persona.py`（R1.1-4 in-world identity） · `tests/test_dialogue_liveness.py`（processor 改 say_with_result+deadline，语义一致） · `tests/test_phase13_r11_residuals.py`（新增 24 项）。

## C. TESTS ADDED（24 项，全部真实越过边界）
- R1.1-1（4）：`test_direct_message_brain_none_has_failed_terminal` / `_has_system_status` / `_does_not_create_orphan_history` / `_next_message_after_recovery_can_reply`。
- R1.1-2（2）：keep_outcomes=5 + 30 条（首条 slow）→ 30 条全部进 processor + 全部终态 + pending=0 + worker alive；keep_outcomes=10 + 150 条 → 150 个 processor call 全部发生。
- R1.1-3（2）：attempt1 消耗 85% 预算 → retry 只拿剩余 → 超时；总 wall ≤ 预算×1.7+容差（重置预算会到 ~1.85×）；remaining<=0 立即超时。
- R1.1-4（1）：`test_persona_identity_no_ai_meta_framing`（含 芙宁娜/枫丹；不含 AI 数字生命/AI助手/来自《原神》/游戏角色）。
- R1.1-5（1 parametrize 12 case）：8 个组 × conflict/compatible 矩阵。
- R1.1-6（3）：`_gate_wait/_gate_release` 唯一定义；per-call result 不被共享值污染；direct 与 ambient 失败并发 → DirectTurn.failure_reason 是 direct 自己的（validation_twice_invalid）。

## D. TEST RESULTS
```
专项（test_phase13_r11_residuals.py）：24 passed
完整 suite run 1：798 passed / 0 failed（26.2s）
完整 suite run 2：798 passed / 0 failed
完整 suite run 3：798 passed / 0 failed
Selfcheck：SELFCHECK OK
Smoke：SMOKE OK
原 774 全部保留（0 删除/skip/xfail；仅 4 个旧契约测试按上一轮 B3/B4 要求升级，本轮未再改）
```

## E. GIT
```
branch: fix/phase13-manual-blockers-r1-1
commit SHA: （见提交结果）
commit message: Phase 13 Pre-Manual Blocker Repair R1.1: db=None direct terminal (R1.1-1), no-active-turn trim (R1.1-2), total turn budget deadline (R1.1-3), persona in-world identity (R1.1-4), activity-claim ontology (R1.1-5), per-call failure reason + dedup (R1.1-6) (798 tests)
```

## F. UNRESOLVED
NONE

---

未声称 Phase 13 PASS / Manual PASS / Phase 14 ready；不代跑 Manual、不自评 Windows CI green（本机即 Windows，结果供评审参考）。验收权不属 Coding Agent。
