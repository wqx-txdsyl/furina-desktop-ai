# Furina Desktop AI — Phase 13 Pre-Manual Blocker Repair R1.2 (FINAL Dialogue Liveness Closure) 报告

**冻结基线：** `9b90b5fbda822c0811bef3470b7ca11c9e32e091`（798 tests）
**分支：** `fix/phase13-manual-blockers-r1-2`（本补丁提交见文末）
**范围：** 仅关闭 4 个 Dialogue residual；未改 Persona / Motivation / Spatial / Relationship / Emotion / Memory / Agent；未扩 scope；未用 delete/skip/xfail/放宽旧断言掩盖问题（原 798 全保留，新增 6 项）。

---

## A. 4 个 residual 的实际 fix

### R1.2-1（P0）direct_turn_timeout 必须真正 ingress→terminal
- 根因：`DirectDialogueQueue._loop()` 在 **dequeue 时** 才设 `turn.deadline = monotonic() + timeout` → queue wait 不计入预算，与 `AppConfig.direct_turn_timeout = 从入队到 terminal 的整回合上限` 的声明不符。
- 修复：`submit()`（ingress 时刻）设 `turn.created_monotonic = time.monotonic(); turn.deadline = created + timeout`；worker **绝不重置** deadline；processor/brain 用 `turn.deadline` 的 remaining（`_generate_bounded` 每次 `remaining = deadline - now`，≤0 立即 `generation_timeout`）→ 已过 deadline 的回合快速 FAILED，不给新预算。生命周期 DIRECT_INGRESS→QUEUED→queue wait→GENERATING→attempt/retry→terminal 共享同一 deadline。

### R1.2-2（P0）移除生产路径双 FIFO / 双 sequence authority
- 根因：`submit_user_message` 在入队前 `db.reserve_turn()` 预占 brain seq → job 在真正执行前失败（db=None/排队超时等）时该 seq 永远没人 release → 后续 `_gate_wait` 永久等待（seq hole）。
- 修复：生产路径**不再 reserve**：`submit_user_message` 只 freeze snapshot + `queue.submit(...)`（`ingress_seq=None`）；`DirectDialogueQueue`（turn_id = 完整用户 ingress identity，未显式给 ingress_seq 时以 turn_id 充当）是唯一串行 authority；brain seq 只在 worker 真正执行 `say_with_result` 时由 `_next_seq()` 分配（串行消费 → 与执行顺序天然一致）。`reserve_turn()` 保留为 brain 级 API（测试/外部直调可用），`say(ingress_seq=...)` 仍受 direct gate 保序。

### R1.2-3（P1）per-call result 彻底禁止回读共享诊断字段
- 根因：`_say_impl` 仍有 `return (None, self.last_failure_reason, ...)` —— per-call result 读共享字段，direct/ambient 并发时可能返回对方改写的值。
- 修复：全部分支改用**局部变量**（`reason`/`issues`），`self.last_failure_reason`/`last_validation_failure` 仅作兼容诊断 mirror（先算局部 → mirror → return 局部）。静态契约测试确认 `_say_impl` 无任何 `return self.last_*` / `return (None, self.last_*)`。

### R1.2-4（P2）keep_outcomes 必须真的 bounded
- 根因：trim 只在 `submit()` 调用 —— burst 150 条全部 terminal 后不再 submit → 150 条 terminal history 全保留，`keep_outcomes=10` 失效。
- 修复：`_finish()`（终态转换后，锁内）也调用 `_trim_locked()` —— retained terminal ≤ keep_outcomes；永不 trim QUEUED/GENERATING（活跃 turn 全保留）；trim 只移除 registry（本 turn 局部引用仍可发 terminal trace）。

## B. FILES CHANGED
`furina/runtime/dialogue_queue.py`（R1.2-1 deadline@submit + 不重置；R1.2-4 _finish 后 trim；R1.2-2 ingress_seq 缺省= turn_id） · `furina/app.py`（R1.2-2 submit_user_message 移除 reserve_turn） · `furina/dialogue_brain.py`（R1.2-3 per-call 局部变量；注释契约更新） · `tests/test_phase13_r12_final_dialogue.py`（新增 6 项） · `tests/test_phase13_r11_residuals.py`（1 处断言按 R1.2-2 新契约更新：ingress_seq=turn_id）。

## C. TESTS ADDED（6 项）
- `test_r12_1_five_rapid_with_hang_total_wall_about_one_budget`：timeout=0.25 + 5 条快速（首条 hang）→ 5 个 DirectTurn 全 terminal（全 FAILED/generation_timeout）、pending=0、无丢失、worker alive；总 wall ≈ 一次 budget（< 2.5×budget，非 5×）。
- `test_r12_2_middle_db_unavailable_same_brain_recovers`：同 brain：msg1 REPLIED → db=None msg2 FAILED(dialogue_brain_unavailable) → 恢复同一实例 msg3 REPLIED（不永久等待；history 无 seq hole：msg1/回复1+msg3/回复2）。
- `test_r12_2_queue_timeout_then_normal_message_still_works`：3 条排队超时 FAILED 后，正常消息 REPLIED；history 成对无 hole。
- `test_r12_3_direct_generation_empty_ambient_another_failure`：direct=generation_empty 与 ambient=validation_twice_invalid 并发 → DirectTurn.failure_reason 稳定等于 direct 自己的（generation_empty）。
- `test_r12_3_say_impl_never_reads_shared_field_for_result`：静态契约（无 `return self.last_*` / `return (None, self.last_*)`）。
- `test_r12_4_keep10_150_jobs_terminal_history_bounded`：keep=10 + 150 jobs 全完成后不再 submit → processor calls=150、terminal trace=150、pending=0、retained observable terminal ≤ 10、worker alive。

## D. TEST RESULTS
```
专项（test_phase13_r12_final_dialogue.py）：6 passed
完整 suite run 1：804 passed / 0 failed（29.2s）
完整 suite run 2：804 passed / 0 failed
完整 suite run 3：804 passed / 0 failed
Selfcheck：SELFCHECK OK
Smoke：SMOKE OK
原 798 全部保留（0 delete/skip/xfail/放宽；1 处断言按 R1.2-2 新契约（ingress_seq=turn_id）更新）
```

## E. GIT
```
branch: fix/phase13-manual-blockers-r1-2
commit SHA: （见提交结果）
commit message: Phase 13 Pre-Manual Blocker Repair R1.2 FINAL Dialogue Liveness: ingress->terminal deadline (R1.2-1), single FIFO authority no pre-reserve (R1.2-2), per-call result local-only (R1.2-3), terminal-history bounded trim (R1.2-4) (804 tests)
```

## F. UNRESOLVED
NONE

---

未声称 Phase 13 PASS / Manual PASS / Phase 14 ready；不跑完整 Manual，不自评 Windows CI green（本机即 Windows，结果供评审参考）。验收权不属 Coding Agent。
