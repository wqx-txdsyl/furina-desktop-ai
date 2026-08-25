# Furina Desktop AI — Phase 13 Runtime Evidence Blocker Repair R2.1 报告

**冻结基线：** `9b075a61ca8f4b0fd4058dbe769f009d93286d9b`（804 tests）
**分支：** `fix/phase13-runtime-evidence-r2-1`（本补丁提交见文末）
**来源：** 真实 Windows R2 Runtime Evidence（前一轮 evidence.jsonl：A10/E04/G03/P10/P12/P26 等 <NO RESPONSE>、P 段 15/26 validation_twice_invalid、A14/P22/P24 事实错误、C04 互动事实错位、notepad 无报告、只能回答会或不会 违规等）。
**范围：** 只修被真实 runtime 证据证明的 blocker；未重设计 LifeBrain/Motivation/Spatial/Agent Planner/Tools/Relationship/Emotion/Feeding。原 804 全保留（0 delete/skip/xfail/放宽），新增 28 项真实边界测试。

---

## A. 每个 runtime blocker 的 root cause / fix

### P0-1 USER-VISIBLE DIRECT TERMINAL（speech event identity）
- 根因：`RuntimeHarness._on_frame` 按 **text equality** 去重（`sp.text != self._last_speech_key`）；`_system_status_failure` 每次发完全相同文本 → 连续不同 turn 的相同 SYSTEM_STATUS 被当"同一 frame 重复"吞掉（A10/E04/G03/P10/P12/P26 的 <NO RESPONSE> 一部分即此）。
- fix：`scheduler._say()` 每次新 utterance 递增 `_speech_seq`（speech event identity）；`FrameSpeech` 增加 `speech_id`（frame + to_dict）；harness `_on_frame` 按 **speech_id** 去重（同一 utterance 重复 tick 才 dedupe；不同 DirectTurn 即使文本相同也各显示一次；无 id 的旧帧退回按文本）。

### P0-2 HARNESS DIRECT TELEMETRY
- 根因：`_wrap_dialogue()` 只包 `db.say`，而生产 DirectQueue 走 `db.say_with_result` → direct dialogue 的 badge stale/false-green、LLM_REQUEST/LLM_RESULT trace 缺失。
- fix：harness 订阅 `DIRECT_TURN_TRACE`（+ 保留 BRAIN_SPOKE/ambient 诊断）；`dialogue_badge()` 的"最近一次 direct outcome"来自真实 DirectTurn lifecycle（REPLIED→LAST_OK / FAILED→LAST_FAILED / CANCELLED→LAST_FAILED/CANCELLED / GENERATING|QUEUED→RUNNING/PENDING），ambient（旧路径 `_dialog_last.outcome`）只作 fallback、不得覆盖 direct；每个 direct turn 的 ingress/generation start/result/terminal 都记入 trace。

### P0-3 VALIDATOR SEVERITY（soft 不失败）
- 根因：全部 issue 一律 invalid → real-LLM 的 15/26 Persona turn 死在 `validation_twice_invalid`（大量为 repetitive_opening/over_exclamation/generic_assistant_voice 等**风格**缺陷）→ availability blocker。
- fix：`ValidationResult` 增加 `hard_issues`/`soft_issues`（HARD：empty/AI identity/nonhuman framing/当前活动矛盾/interaction 矛盾/结构不可用；SOFT：generic voice/repetitive_opening/over_exclamation/god 过度/example_copy/recent_repetition/generic_self_analysis 等）。`_say_impl` 按 severity：attempt→retry→retry 仍 HARD → `validation_twice_invalid`（显式 outcome）；仅 SOFT 残留 → **surface 较优候选** + 记录 `soft_issues`（不失败）；retry 生成失败但 attempt 仅 SOFT → surface attempt。`DirectTurn` 与 `say_with_result` 增加 validation_issues/hard_issues/soft_issues 遥测。

### P1-1 CURRENT FACTS > MEMORY
- 根因：prompt 把过去记忆与当前活动并列，LLM 把"帮用户整理下载文件夹"（过去）说成"我正在…"（A14/P22/P24 事实错误）。
- fix：prompt 显式分层 `[CURRENT_FACTS - AUTHORITATIVE]`（current_activity/Agent 状态/活跃任务/世界）vs `[RECENT_EVENT]` vs `[PAST_MEMORY - 过去的事，不代表现在正在发生]`（明确"不得说成我现在正在…"除非 agent 任务活跃）；快照携带 `agent_state/agent_task`（scheduler 经 AGENT_STARTED/COMPLETED/FAILED 镜像 + `_agent_facts_sched`）；activity grounding ontology 覆盖 production activities（talk/idle/approach_user/agent_planning/agent_work/agent_report/explore）；HARD TEST：activity=talk + "我现在正在整理测试目录" → `ungrounded_activity`（HARD）。

### P1-2 INTERACTION FACT GROUNDING
- 根因：C04 输入=摸头（relationship 走 positive-touch），speech 却"你竟然敢偷袭我！" —— 互动事实 kind 未传进 Dialogue。
- fix：`DialogueContextSnapshot` 增加 `interaction`；`_freeze_reaction_snapshot` 携带 kind；prompt FACT 块列出"用户刚才的互动: petting"；validator `interaction` 参数：petting + 戳/偷袭/袭击类声称 → HARD `interaction_contradiction`（poke 可表达被戳）。

### P1-3 MEMORY PLAN + FOLLOW-UP LINKING
- 根因：`_maybe_observe_conversation` 正则漏"我今天准备…"（只支持 我今晚/我明天/我准备）；"做完以后应该能轻松一点"未存、无关联。
- fix：plan 提取扩展（我今天准备/我今天打算/我明天准备/我今晚打算/我这周计划…，importance 0.5, context=user_plan）；follow-up（做完/弄完/搞定/完成后/忙完…应该/就会/可以/大概）联动最近 plan（context=user_plan_followup, outcome=plan）；`MemoryEngine.retrieve` 对 CJK 无空格查询补 2-gram（去重）→ "今天准备做什么？/做完以后会怎么样？"可检索到事实。

### P1-4 AGENT TERMINAL RESULT-BOUND REPORT
- 根因：notepad COMPLETED_VERIFIED 无台词；calc/organize 报告只"举手之劳/越来越依赖我"，事实层缺失。
- fix：scheduler 订阅 AGENT_STARTED 记录原始请求；`_on_agent_done` 构建结果绑定 context（original_request + 验证通过 + goal + summary + concrete evidence）；`_speak_via_dialogue` 增加 `fallback` 参数 → **exactly-once 用户可见报告**（角色台词出话，否则确定性 SYSTEM_STATUS 事实回退，worker 内完成不丢报告）；prompt 对 `activity=="agent_report"`/`COMPLETED` 状态强制"先报告任务结果事实"。

### P1-5 BASIC USER CONSTRAINT FOLLOWING
- 根因：用户"只能回答会或者不会。" → 模型输出长段文本（无约束执行）。
- fix：Phase A 保守确定性提取 `只能回答X(或者|或)Y` → 约束进 prompt（优先级高于 persona）+ 传给 validator（`explicit_user_constraint_violation` HARD）；生成后/retry 后确定性提取选项词（长词优先，绝不编造）→ 输出 ∈ {会, 不会}。

### P1-6 PERSONA SURFACE — FIX MECHANISM
- 根因：recent surfaced 只跟踪 direct；P21 逐字重复 P19；generic interview 自我描述（乐观/倾听/完美主义）；"哎呀"塌缩。
- fix：`_recent_surfaced` 跨**所有 user-visible 通道**（direct/interaction/feed/agent）跟踪；新增 `recent_repetition`（近期逐字重复，soft → retry）；`generic_self_analysis`（模板化自我描述，soft）；prompt 增加具体芙宁娜 trait anchors（尊严/被看穿找回/卸任后普通生活/注意力敏感/认真收舞台腔，明确不用"乐观/倾听/完美主义"通用模板）；serious/comfort 场景 soft 不杀回复（P0-3 语义）。

### P2 HARNESS CONVERSATION EVENT IDENTITY
- 根因：conversation 只有 `("Furina", text)` 元组，无法把 turn→status 对应。
- fix：`RuntimeHarness.utterances` 结构化存储（role/turn_id/channel/speech_id/text/terminal_status/recorded_at，bounded 200）；DIRECT_INGRESS 记录 user utterance（turn_id/channel），终态 trace 更新 terminal_status，frame speech 记录 Furina utterance（speech_id）。

## B. FILES CHANGED
`furina/runtime/scheduler.py`（P0-1 speech_seq；P1-1 agent 镜像+快照事实；P1-4 报告 context+fallback） · `furina/runtime/frame.py`（FrameSpeech.speech_id + to_dict） · `furina/runtime/harness/controller.py`（P0-1 id 去重；P0-2 DIRECT_TURN_TRACE telemetry+badge；P2 utterances） · `furina/runtime/harness/window.py`（direct_turns 诊断行，上一轮已有） · `furina/dialogue/validator.py`（P0-3 severity；P1-1 activity 组扩展；P1-2 interaction；P1-5 constraint；P1-6 recent_repetition/generic_self_analysis） · `furina/dialogue_brain.py`（P0-3 severity 流；P1-1/P1-2 prompt 分层+interaction/agent 参数；P1-5 约束；P1-6 全通道 surface） · `furina/runtime/dialogue_snapshot.py`（interaction/agent_state/agent_task） · `furina/runtime/dialogue_queue.py`（P0-3 validation telemetry 字段） · `furina/app.py`（P1-1 快照 agent 事实；P1-3 plan+follow-up；P0-3 out 遥测） · `furina/memory/memory_engine.py`（P1-3 CJK bigram 检索） · `tests/test_phase13b.py`（1 处源断言按 P1-4 新 fallback 语义更新） · `tests/test_phase13_r21_runtime_evidence.py`（新增 28 项）。

## C. TESTS ADDED（28 项）
P0-1（4）：say 递增 speech_id 同文本异事件 / frame 按 id 去重（同 id 去重、异 id 同文本各显示）/ 5 个同 SYSTEM_STATUS FAILED turn 全可观察（pending=0、5×turn_id 独立、hard_issues=stage_direction）。
P0-2（2）：badge LAST_OK→LAST_FAILED→LAST_OK（真实 DIRECT_TURN_TRACE 驱动 + ambient 不覆盖 + trace 含 ingress/generation/result/terminal）；生产 queue 终态驱动 badge。
P0-3（4）：仅 SOFT surface 不失败（+soft_issues 记录）/ SOFT retry 到 valid surface retry / HARD 双失败 FAILED+hard_issues / severity 分类。
P1-1（4）：talk+工作声称 HARD invalid / agent_work+工作声称 valid / prompt CURRENT_FACTS vs PAST_MEMORY 分层 / direct 快照携带 agent 事实。
P1-2（3）：petting+偷袭 HARD / poke+被戳 valid / petting 正面回复 valid / reaction 快照携带 interaction。
P1-3（1）：今天准备…+做完以后… → 检索分别含"完成桌宠的功能测试"/"应该能轻松一点"。
P1-4（2）：_on_agent_done context 含 request/完成/验证/具体证据（notepad 语义）；无 DialogueBrain → fallback 系统事实（exactly-once）。
P1-5（3）：约束确定性提取（输出∈{会,不会}）/ 无选项输出 retry 后提取 / validator constraint HARD。
P1-6（4）：全通道 surface 跟踪 / 近期逐字重复 soft / generic self-analysis soft / serious/comfort soft 不杀回复。
P2（1）：utterances 结构化（turn_id/channel/speech_id/text/terminal_status）。

## D. FULL SUITE ×3
```
run 1：832 passed / 0 failed（26.9s）
run 2：832 passed / 0 failed
run 3：832 passed / 0 failed
专项：28 passed；原 804 全保留（0 delete/skip/xfail/放宽；1 处源断言按 P1-4 语义升级）
Selfcheck：SELFCHECK OK
Smoke：SMOKE OK
```

## E. GIT
```
branch: fix/phase13-runtime-evidence-r2-1
commit SHA: （见提交结果）
commit message: Phase 13 Runtime Evidence Blocker Repair R2.1: speech event identity (P0-1), harness direct telemetry (P0-2), validator severity soft-surface (P0-3), current-facts>memory + agent facts (P1-1), interaction grounding (P1-2), plan memory + follow-up (P1-3), agent result-bound report (P1-4), user constraint (P1-5), persona surface mechanism (P1-6), harness utterance identity (P2) (832 tests)
```

## F. UNRESOLVED
NONE

---

未声称 Phase 13 PASS / Persona PASS / R2 PASS / R3 ready / Phase 14 ready。下一阶段 Persona 真实质量由 Runtime Evidence transcript 判定（本补丁只修机制，不静态调参）。验收权不属 Coding Agent。
