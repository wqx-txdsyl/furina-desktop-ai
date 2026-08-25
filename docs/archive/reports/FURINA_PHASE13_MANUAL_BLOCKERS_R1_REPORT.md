# Furina Desktop AI — Phase 13 Pre-Manual Blocker Repair R1 报告

**冻结基线：** `0402e7f1236cbc681e92c7ed7feca19ce5826618`（734 tests）
**分支：** `fix/phase13-manual-blockers-r1`（本补丁提交见文末）
**范围：** 仅评审列出的 4 个 Manual blocker（B1 直接对话 liveness / B2 Harness 拖拽 / B3 Persona 塌缩 / B4 Motivation 强制多样残留）。
**冻结：** 其余一切（Director/Emotion/Relationship/Memory/Agent/World/Frame/Spatial 单所有权/Activity 生命周期等）未动；交叉回归 18 项全部保持。

---

## A. ROOT CAUSE（具体根因）

### B1 Dialogue（直接对话永久失声）
- **单一全局 turn FIFO + 共享序号空间**：`DialogueBrain.say()` 的所有通道（DIRECT/AMBIENT/FEED/INTERACTION/AGENT）共用 `_ingress_seq` 与同一 gate。Scheduler 的自主台词（每 ~3s 一次 LifeBrain 决策）会抢走用户消息之间的序号；一个慢/挂起的 ambient 回合（现场出现 Zhipu TLS 抖动）会让之后所有直接消息在 `_gate_wait` 上无限等待 → "连续对话数轮后永久不回复"。
- **无 per-turn 有界生命周期**：`_generate` 的 LLM 调用只靠 httpx 120s 超时；`_gate_wait` 无上限等待；worker 异常/挂起无终态兜底。
- **不可观测**：失败只有静默 None，Manual 无法区分"没生成/生成失败/校验失败/仍在等待"。
- 附带：每个 `submit_user_message` spawn 一个独立线程，快速连发时线程堆积。

### B2 Harness Proxy 拖拽
- `launch_harness` 先 `SpatialProxyWindow(world=...)`（**无回调**）再注入 `RuntimeHarness`；`RuntimeHarness.__init__` 的 `proxy is not None` 分支只设 `spatial.window/adapter`，**没补 on_drag_start/on_drag_move/on_drag_release**（自建分支才接线）→ 鼠标事件走到 None 回调，SpatialRuntime 永不进入 drag_active/DRAGGED，spatial tick 继续拥有坐标 → 无法拖动/立即被覆盖。

### B3 Persona 通用 AI 塌缩（多个根因）
1. **无通用助手身份/非人类框架防线**：validator 的 `_CSONIC_PATTERNS` 抓不到"作为AI/我的功能是/你们人类"（`作为(一个|一名|你的|专)` 不含 "AI"）。
2. **无表面语言重复监测**：连续"哎呀"开头无 bounded guard（只有 act 标签级 `_recent_acts`，不检测 opener）。
3. **活动 grounding 弱**：validator 只有 offer_help 的关键词矛盾；"read 时声称在探索"无拦截；prompt 虽有 activity 但无"事实 vs 风格"硬区分。
4. **Prompt/人格指令自相矛盾**：`FURINA_PERSONA` 与 `_dialogue_prompt_v2` 写"自称'本神'"——模型容易理解成"每轮都要自称本神"（"本神"默认自称语义）。
5. **无 mode 级语气变化**：CASUAL/SINCERE/COMFORT/TASK 等 mode 只进 prompt 头部一行，无具体语言约束 → 全成一种"浮夸芙宁娜"。
6. **retry 反馈不可解释**：`feedback = "；".join(v.issues[:3])` 给的是英文标识符，生成器不知道错在哪。

### B4 Motivation 回归（Windows: expected read, actual explore）
- `_score` 里残留 **30s/90s recency 乘子**（`_last_done` 近因）：`mark_done(a, t)` 存的是测试假时钟 t（100~340），而 `candidates(now=None)` 用**真实** `time.monotonic()` 计算 `since` —— 环境相关：Windows Server 2025 全新启动机 monotonic 较小 → `since<90` → read×0.7 → explore(1.37) 超过 read(0.75)。开发机长时间开机 monotonic 巨大 → 无惩罚 → read 胜。同一代码两个环境结果不同 = 真实 regression 根因。
- 且该乘子本质就是"刚做过所以换一个"的纯重复惩罚（非因果），与 production anti-collapse=OFF 契约冲突；`_category_penalty/_activity_penalty/_observation_crush_guard` 已注释但方法/文档残留。

---

## B. FILES CHANGED（逐文件）

| 文件 | 修改原因 |
|---|---|
| `furina/runtime/dialogue_queue.py`（新增） | B1：`DirectDialogueQueue` 专用直接 lane —— 单 worker 串行 FIFO、终态必达（REPLIED/FAILED/CANCELLED）、bounded 生成、DIRECT_TURN_TRACE 可观测、outcome 注册表 |
| `furina/dialogue_brain.py` | B1：direct/ambient **独立 lane**（独立序号 + 独立门，ambient 不占 direct 序号、不堵 direct）；`say(timeout=)` + `_generate_bounded`（线程 join 有界）；`_say_impl` 三阶段重构（LLM 阶段**不持锁**）；`last_failure_reason`；B3：`_recent_surfaced` 表面语言跟踪；prompt FACTS vs STYLE + 本神语义 + mode 语气约束 |
| `furina/app.py` | B1：`submit_user_message` 改入队 DirectDialogueQueue（owner 立即返回）；`_brain_worker` 返回终态信息 + 全失败模式 SYSTEM_STATUS；`_direct_turn_timeout`/`_system_status_failure` |
| `furina/config/app_config.py` | B1：`LLMProfile.timeout`（有界超时配置） |
| `furina/llm/zhipu.py`、`furina/llm/openai_compat.py` | B1：httpx client 用 `profile.timeout`（不再硬编码 120/90） |
| `furina/core/event_bus.py` | B1：新增 `DIRECT_TURN_TRACE` 事件类型 |
| `furina/runtime/harness/controller.py` | B2：注入 proxy 补齐三条 drag 回调（生产 SpatialRuntime 链）；B1：`_diagnostics` 暴露 dialogue_turns（pending/outcomes/recent） |
| `furina/runtime/harness/window.py` | B1：Truth 面板显示 direct 回合终态/失败原因/延迟 |
| `furina/dialogue/validator.py` | B3：`_GENERIC_AI_IDENTITY`/`_NONHUMAN_USER_FRAMING`/`_STATIONARY_ACTIVITIES`+`_EXPLORE_CLAIM`/repetitive-opening（`_opening_marker`+`recent_surface`）；`ValidationResult.describe()` 中文可解释反馈 |
| `furina/behavior/motivation.py` | B4：删除 30/90s recency 乘子 + 整体移除三类纯多样性惩罚方法 + docstring 契约更新 |
| `furina/persona/furina_persona.py` | B3：本神"极少数情境自称"语义 + 身份底线（禁"你们人类/作为AI/我的功能是"） |
| `tests/test_phase13c.py`、`tests/test_phase13_final.py`、`tests/test_behavior_diversity.py`、`tests/test_life_sim.py` | 旧契约测试升级为新契约（B3/B4）：fake LLM 换开场词、惩罚断言改为"移除/不参与打分"断言（非放宽，是 B4 明确要求整体移除） |
| `tests/test_dialogue_liveness.py`（新增） | DIALOGUE-L1..L10 |
| `tests/test_harness_drag.py`（新增） | DRAG-L1..L9 |
| `tests/test_persona_surface_guard.py`（新增） | PERSONA-L1..L9 |
| `tests/test_motivation_no_forced_diversity.py`（新增） | MOT-L1..L7 |

## C. TESTS ADDED（测试名 + 验证的不变量）

- `test_dialogue_liveness.py`（12）：L1 5 条快速连发全终态保序；L2/L3 turn1 失败/空不堵 turn2；L4 双重校验失败不堵；L5 ambient 挂起不堵 direct（独立 lane+无锁 LLM 阶段）；L6 到达反转仍按 ingress；L7 失败无孤儿 user 历史；L8 历史严格成对；L9 SYSTEM_STATUS 不进 Persona 历史；L10 20 条 stress 全终态无 pending；ambient 不占 direct 序号；trace 相位可观测。
- `test_harness_drag.py`（9）：L1 press→drag_active/DRAGGED；L2 press+move→proxy 位置变化；L3 拖动中 tick 不覆盖鼠标坐标；L4 release→drag_releases+1；L5 release 提交新 foot truth；L6 release 后 tick 不 snap-back；L7 grace 内 wander 不抢控制；L8 高优先 APPROACH 可打断 grace；L9 **真实 launch_harness wiring**（press→DRAGGED→release→commit→无 snap-back）。
- `test_persona_surface_guard.py`（10）：L1 通用 AI 身份识别；L2 非人类框架识别（"人类"单字不禁）；L3 "哎呀"×3 触发 repetitive_opening（validator + DialogueBrain retry 集成）；L4 单次"哎呀"合法；L5 read 声称探索→ungrounded_activity（validator + say 双重失败）；L6 rest 自然描述通过（semantic 非 substring）；L7 SYSTEM_STATUS 不校验；L8 retry 保持原始 user_text/activity 事实；L9 无 hardcoded 问答映射（正则查 if/==/dict 特判）。
- `test_motivation_no_forced_diversity.py`（7）：L1 repeated-read 保持 top（原 Windows regression 点）；L2 仅历史不同分数完全相同；L3 需求条件变化自然换行为；L4 极高 hunger→eat>read；L5 拒绝后 talk 因果下降（保留）；L6 user absent→user-directed infeasible（保留）；L7 确定性（两次逐候选同分）。

## D. TEST RESULTS

```
专项（4 新文件）：        38 passed（12+9+10+7）
完整 suite run 1：        774 passed / 0 failed（25.5s）
完整 suite run 2：        774 passed / 0 failed（26.1s）
完整 suite run 3：        774 passed / 0 failed（25.5s）
Windows（本机 3.13.9，真 runner 同因已消除）：774 passed
Selfcheck：               SELFCHECK OK
Smoke：                   SMOKE OK（真实窗口启动→1.5s 自动退出）
重点 regression：         test_repeated_read_can_remain_top_candidate PASS（含 MOT-L1）
```

## E. BLOCKER REPRODUCTION

- **Dialogue**：DIALOGUE-L1/L2/L3/L5 证明 —— 5 条连发全 REPLIED 且顺序 1..5；turn1 失败→FAILED(终态) 且 turn2 REPLIED；ambient 挂起（`_HangLLM` 永不放行）期间 direct <1s 出话。SYSTEM_STATUS 失败路径可观察（`（系统状态：刚才的回复生成失败。）`，不进 Persona history）。
- **Drag**：DRAG-L9 真实 launch_harness —— press→`spatial.state.drag_active=True/DRAGGED`→move→release→`drag_releases=1`→commit foot truth→tick 后 proxy 不回到拖前位置（无 snap-back）。
- **Persona**：PERSONA-L1/L2/L3/L5 机制证据 —— "作为AI…"→generic_assistant_identity；"你们人类…"→nonhuman_user_framing；"哎呀"×3→retry 换开场；read+“我在探索新事物”→双重失败不泄漏。5 轮原始 transcript 由 Manual 阶段另行采集（本补丁不代跑完整 Manual、不自评 Persona PASS）。
- **Motivation**：MOT-L1 恢复（expected read = actual read）；MOT-L2 证明分数与历史完全无关（recency 乘子已删，混时钟环境相关根因消除）。

## F. GIT

```
branch:       fix/phase13-manual-blockers-r1
commit SHA:   （见提交结果）
commit msg:   Phase 13 Pre-Manual Blocker Repair R1: direct-dialogue liveness lanes+queue (B1), harness proxy drag wiring (B2), persona surface guard+grounding (B3), forced-diversity residue removal (B4) (774 tests)
```

## G. UNRESOLVED

NONE（4 个 blocker 均已修复并有行为/生产路径证据；完整 suite 连续 3 次 green；交叉回归 18 项保持）。

---

**判定说明（按评审 §13 输出格式交付，验收权不属 Coding Agent）：** 未声称 Phase 13 PASS / Manual PASS / Persona PASS；Manual Experience Acceptance 由 Runtime Evidence Agent 另行执行（A. 评审可执行模拟测试 / B. 用户真实 Windows·真实 API·主观体验测试）。
