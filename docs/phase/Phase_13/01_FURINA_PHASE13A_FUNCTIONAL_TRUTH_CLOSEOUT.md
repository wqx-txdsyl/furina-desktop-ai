# Phase 13A — Functional Truth Closeout

> 这是 Phase 13 的一次性 Closeout，不是新功能 Phase。
> 目标：在人工作用验收前，让 Runtime Truth Harness **真的可信**。
> 禁止素材工作、禁止扩 Agent 能力、禁止重写 Persona、禁止调 Needs/Relationship/Personality 参数。

## 0. 当前判定

```text
Phase 13 architecture direction      PASS
Harness exists                       PASS
Real production subsystems reused    PARTIAL
Truthfulness / causal observability  FAIL
Manual Functional                    BLOCKED
Overall                              PARTIAL — FUNCTIONAL TRUTH CLOSEOUT REQUIRED
```

本轮完成后才让用户进行 Phase 13 Manual Functional / Persona 验收。

---

## 1. P0 — Truth Panel 禁止假绿

当前问题：
- `ObservationAdapter.model_status()` 仅凭 `life_brain/dialogue_brain` 对象存在就显示 `glm`。
- Agent status 导入 `furina.agent.runtime`，真实模块为 `furina.agent.agent_runtime`，badge 会错误。
- `HarnessViewModel.current_life()['fallback']` 写死 `NO`。
- `status_badges()` 在 life object 存在时忽略真实 failure/fallback。

### 必须修

建立只读 `RuntimeHealthSnapshot`（名字可不同），只从真实运行指标得出：

```text
Life:
  last_attempt
  last_success
  last_fallback
  success_count
  fallback_count
  failure_count

Dialogue:
  last_attempt
  last_outcome = SPOKE / SILENT_BY_POLICY / MODEL_FAILURE / VALIDATOR_REJECT / GATE_SUPPRESS
  model_used

Agent:
  IDLE / RUNNING / SUCCESS / FAILED / WAITING_PERMISSION
```

UI badge 必须反映**最后真实状态**，不是“对象存在”。

禁止：
```text
Fallback: NO   # hard-coded
Dialogue: glm ✓  # 只因为对象存在
```

### PASS
- 注入 LifeBrain failure → badge 显示 FALLBACK/FAILED。
- Dialogue model unavailable → 不显示 `glm ✓`。
- Agent 实际运行时 RUNNING，完成后 SUCCESS，失败后 FAILED。
- `current_life.fallback` 来自真实指标。

---

## 2. P0 — Spatial Runtime 必须唯一，Panel 与 Proxy 必须看同一个 truth

当前：
- `RuntimeHarness.__init__()` 自己 new `DesktopSpatialRuntime`。
- Proxy 使用 `h.spatial`。
- `HarnessViewModel._spatial()` 却读 `app._spatial`。
- `launch_harness()` 未设置 `furina._spatial`。

结果：Proxy 在移动，但 Truth Panel 的 Spatial 可能为空/不是同一对象。

### 必须修

由 `launch_harness()` 创建**唯一** SpatialRuntime：

```text
launch_harness
  → proxy
  → DesktopSpatialRuntime(world, proxy)
  → furina._spatial = spatial
  → RuntimeHarness(app, spatial=spatial, proxy=proxy)
```

或等价依赖注入。

`RuntimeHarness` 不得再自行创建第二个 SpatialRuntime。

### PASS
```python
assert harness.spatial is furina._spatial
```

Panel 显示的 position/state 与 Proxy 实际位置完全一致。

---

## 3. P0 — Qt GUI Thread Safety

当前真实链：

```text
Harness on_user_message
→ background _brain_worker
→ EventBus.emit(BRAIN_SPOKE)  # 同步 bus
→ RuntimeHarness._on_brain_spoke
→ panel.append_chat()         # QWidget
```

这会从后台线程直接改 QWidget。

### 必须修

所有 Harness QWidget mutation：

```text
background EventBus callback
→ Qt queued Signal / invokeMethod
→ GUI thread
→ panel/proxy update
```

禁止 EventBus worker thread 直接调用：
- `QPlainTextEdit.appendPlainText`
- `QLabel.setText`
- QWidget position/update

### PASS
记录 thread id：
```text
worker emit thread != GUI thread
append_chat thread == GUI thread
```

0 Qt cross-thread warning/crash。

---

## 4. P0 — Direct User Dialogue 的 World Context 实际为空

当前 `app._brain_worker()` / `_feed()` 读取：

```python
self.world_perc
```

但 `WorldPerception` 实际属于 `Scheduler.world_perc`，`Furina` 没有该字段。
因此 direct user dialogue/feed 的 `world={}`。

### 必须修

建立唯一只读 helper，例如：

```python
def _runtime_world_factors(self):
    sched = getattr(self, "_sched", None)
    wp = getattr(sched, "world_perc", None)
    return wp.factors() if wp else {}
```

`_brain_worker`、`_feed`、Agent result dialogue 等统一使用。

不要复制第二个 WorldPerception。

### PASS
真实对话 trace 中必须出现来自当前 Scheduler world 的：
```text
user_activity
focus / interruption_cost（存在时）
interaction availability（存在时）
```

而不是永远 `{}`。

---

## 5. P0 — Memory Interpretation 类型传错

`MemoryEngine.interpret()` 要求 `List[Memory]`。
当前 `_brain_worker` 和 Scheduler `_speak_via_dialogue()` 把：

```text
[m.content, ...]  # List[str]
```

传进去。

字符串没有 importance/event_type/world_context，导致 interpretation 基本退化为全 0。

### 必须修

统一：

```python
mem_objs = memory.retrieve(...)
mem_texts = [m.content for m in mem_objs]
mem_interp = memory.interpret(mem_objs, context=...)

DialogueBrain.say(
    memories=mem_texts,
    memory_interp=mem_interp,
)
```

至少修：
- `Furina._brain_worker`
- `Furina._feed` 若需要 interpretation
- `Scheduler._speak_via_dialogue`

### PASS
构造一条 rejection/positive memory：
- `memory_interp` 非零且方向正确。
- Dialogue trace 同时显示 `mem_count` + interpretation summary。

---

## 6. P0 — Interaction 的 Relationship / Emotion 双写必须收敛

### Relationship 当前双写
一次 `petting`：

```text
InteractionEngine._apply
→ bus.emit(INTERACTION_INPUT)
   → Scheduler._on_interaction
      → RelationshipEngine.apply(EV_POSITIVE_TOUCH)
→ app._on_meaningful_interaction
   → RelationshipEngine.apply(EV_POSITIVE_TOUCH)
```

一次摸头实际 apply 两次。

`poke` 更严重：Scheduler 与 App 使用的 relationship event 方向不同。

### Emotion 当前也有双 owner
- App 在 `INTERACTION_INPUT` 上调用 `EmotionEngine.apply(...)`。
- Scheduler `_on_interaction()` 又直接写 `emotion.label/valence/arousal/mood`。

这绕过 EmotionEngine 的单一情绪动力学。

### 必须修

必须明确：

```text
Emotion state mutation        → EmotionEngine only
Relationship mutation         → RelationshipEngine.apply only, exactly once per interaction
Memory observation            → MemoryEngine only
Scheduler interaction handler → 读取已经更新后的 state，负责 intent/dialogue/life interrupt；不再直接写 Emotion/Relationship
```

具体模块位置可调整，但 ownership 必须唯一。

### PASS
真实 `emit_event("petting","head")`：
```text
EmotionEngine apply count       = 1
RelationshipEngine.apply count  = 1
Memory meaningful observe       = 1（若满足记忆规则）
Dialogue trigger                = 1
```

Poke 重复次数 1 / 4 / 6 分别验证方向，不允许两个 handler 互相覆盖。

删除旧 `test_relationship_event_applied_once` 的“手工调用 RelationshipEngine 两次”伪验收，改测**真实 InteractionEngine → App/Scheduler runtime route**。

---

## 7. P0 — Agent Routing / Event Ownership

### 7.1 计算器按钮当前根本不进 Agent
Harness `on_agent("calc")` 发送 `打开计算器` 给 `_on_user_command()`，但 `AGENT_TASKS` 没有该项。
结果：走 `_brain_worker()`，被当聊天。

### 7.2 organize-test 绕过 App Agent production worker
Harness 直接：
```python
app.agent.execute(...)
```
导致 App 层的 memory/result integration 不一致。

### 7.3 Agent success/failure 当前重复发事件
`AgentRuntime.execute()` 自己 emit `AGENT_COMPLETED/FAILED`；
`Furina._agent_worker()` 收到结果后又 emit 一次。
Scheduler 会处理两次 → 重复 dialogue/status。

### 必须修

建立一个生产公共入口，例如：

```python
Furina.submit_agent_task(user_request, extra_context=None)
```

右键菜单和 Harness 都调用它。

- Notepad / Calculator / organize-test 全走同一入口。
- organize-test 只传安全 tmp path。
- Agent lifecycle event **一个 owner**。建议 `AgentRuntime` emit lifecycle；App worker 不重复 emit，只做 memory/辅助 integration。
- 完成/失败恰好一次。

### Agent failure 用户反馈
当前 `_on_agent_fail()` 只 `_say("系统状态...")`，没有 DialogueBrain。
Phase 13 要求：

```text
确定性 failure fact
→ DialogueBrain(task_mode=True) 生成角色化反馈
```

若 DialogueBrain 不可用：
- 可以在 Harness 独立 SYSTEM STATUS 区显示事实；
- 不得把固定 system string 冒充 Furina 对话。

### PASS
- 打开记事本 → Agent planner/tool。
- 打开计算器 → Agent planner/tool，不进入普通聊天。
- organize-test → production Agent entry + safe tmp only。
- success event count = 1。
- failure event count = 1。
- Agent result → DialogueBrain exactly once。

---

## 8. P0 — Harness Conversation 必须显示真实 Frame.speech，而不是只看 BRAIN_SPOKE

当前 Interaction / autonomous / Agent dialogue 常通过 Scheduler `_speak_via_dialogue()` → `_say()`，并不 emit `BRAIN_SPOKE`。
Harness Conversation 只订阅 `BRAIN_SPOKE`，因此摸头/Agent/autonomous speech 可能已经进入 Frame，却不出现在聊天框。

### 必须修

以 `CharacterRuntimeFrame.speech` 作为 Harness 最终可见语言 truth。

```text
CHARACTER_FRAME_UPDATED
→ if speech.should_speak and speech.text/new speech identity
→ queued GUI append
```

要求去重，不能每个 1s Frame 重复 append 同一句。

`BRAIN_SPOKE` 可以保留为上游 trace 事件，但**Conversation UI 最终以 Frame.speech 为准**。

### PASS
- 用户聊天 response 显示 1 次。
- 摸头 Dialogue 显示 1 次。
- autonomous Dialogue 显示 1 次。
- Agent 完成反馈显示 1 次。
- Frame 重发同一 speech 不重复。

---

## 9. P1 — Feed 不得阻塞 GUI 线程

Harness `on_feed()` 直接调用 `app._feed()`；而 `_feed()` 同步 `DialogueBrain.say()`。
真实模型延迟时会冻结 Qt UI。

### 必须修

食物 deterministic state effect 可以同步；LLM speech 必须背景执行：

```text
feed effect + memory + life interrupt
→ return UI
→ background DialogueBrain
→ Frame.speech
```

### PASS
- fake Dialogue latency 2s 时，Harness UI timer 仍持续刷新。
- feed effect 立即可见。
- 2s 后 dialogue 到达。

---

## 10. P0 — Trace 不能宣称不存在的阶段

当前 Trace 实际主要只有：
- USER_ACTION roots
- wrapped Dialogue `LLM_REQUEST/LLM_RESULT`
- wrapped Life `LLM_REQUEST/DECISION`
- organize-test 单个 TOOL_RESULT

但 Phase 13 Report 宣称存在：
- Validator trace
- Interaction emotion/relationship before→after
- Memory store/retrieve/use
- Frame speech
- Agent planner/permission/tool/result 完整链

这些目前代码并未完整记录。

### 必须修：最小真实 Trace

至少实现以下可观察链，不要求把每个内部函数都打点：

### USER MESSAGE
```text
USER_INPUT
→ DIALOGUE_REQUEST
→ DIALOGUE_RESULT(reason/status)
→ FRAME_SPEECH
```

### INTERACTION
```text
USER_ACTION
→ EMOTION before/after
→ RELATIONSHIP before/after
→ MEMORY stored/dedup/none
→ DIALOGUE_RESULT
→ FRAME_SPEECH
```

### FEED
```text
USER_ACTION
→ NEEDS before/after
→ MEMORY
→ LIFE_INTERRUPT
→ DIALOGUE_RESULT
→ FRAME
```

### AGENT
```text
USER_REQUEST
→ PLAN summary
→ PERMISSION result
→ TOOL result
→ AGENT final
→ DIALOGUE_RESULT
→ FRAME_SPEECH
```

### LIFE
```text
CANDIDATES
→ LLM RAW selection
→ validated selection
→ actual APPLIED activity
→ fallback/invalid
```

只显示真实存在的 stage；不要预先写 `VALIDATOR` 字样却没有 instrumentation。

---

## 11. P1 — Trace Root Correlation

当前：
- `on_user_message()` 创建 USER_INPUT root。
- `_wrap_dialogue()` 又创建新的 root。

所以一次用户输入与其 LLM response 没有真正 root 关联。

### 必须修

后台线程也要继承/传入 `root_trace_id`。
可用显式 trace context / request id / task wrapper，禁止靠“时间靠得近”猜。

至少：
```text
USER_MESSAGE root
  ├─ DIALOGUE_REQUEST
  ├─ DIALOGUE_RESULT
  └─ FRAME_SPEECH
```
共享一个 root。

快速连续发送两条消息时，不得串 response trace。

---

## 12. P0 — anti-collapse 必须与冻结声明一致：OFF

当前生产 Scheduler `_apply_life_decision()` 无条件：

```python
d = self._anti_collapse(d)
```

第三个同类行为会被机械替换。
这与项目一直声明的：

```text
anti-collapse = OFF
personality/needs/homeostasis 产生自然多样性
```

冲突，并会污染 Phase 13 的“方框是否真的有自主生命感”人工验收。

### 必须修

这是 **Freeze Regression Exception**，不是新调参。

正式 Runtime / Harness：
```text
anti-collapse OFF
```

可以保留 `_anti_collapse()` 旧实现作为未启用 debt，但生产路径不得调用。

禁止同时去改 personality/needs/motivation 参数补分布。

### PASS
真实 scheduler 连续三次同类合法 LifeDecision：
- actual applied 与 Brain validated selection 一致；
- 不被 `_anti_collapse` 改写。

Trace 显示：
```text
raw_selection
validated_selection
applied_selection
```
三者可核对。

---

## 13. P1 — Memory Count / Badge 小修

`memory_info()` 当前 `query(limit=1)` 后 `len()` 只能得到 0/1，不是真实 rows。

如果 UI 标成 “Memory rows”，必须真实 count；
否则改名为：
```text
Memory available: YES/NO
```

不要显示假精度。

---

## 14. 本轮禁止扩范围

禁止：
```text
PNG / walk / drag / read assets
Animation polish
Phase 14
新 LLM
新 DB
Vision / OCR
Agent 新工具大扩展
UI 自动化框架
Persona 重写
Relationship 参数调整
Emotion 参数调整
Need 参数调整
Behavior score 调整
Memory importance 调参
Harness 美术
```

---

## 15. 必须新增的真实回归测试

至少：

```text
truth_badge_reflects_real_fallback
current_life_fallback_not_hardcoded
agent_badge_uses_real_agent

harness_and_panel_share_single_spatial_runtime
panel_spatial_matches_proxy

brain_spoke_ui_marshalled_to_qt_thread

user_dialogue_receives_scheduler_world_context
memory_interpret_receives_memory_objects

petting_relationship_applied_once_real_route
petting_emotion_engine_single_writer
poke_real_route_no_conflicting_double_apply

calculator_button_reaches_agent
organize_test_uses_production_agent_entry
agent_success_event_exactly_once
agent_failure_event_exactly_once
agent_result_dialogue_exactly_once

frame_speech_is_harness_conversation_truth
frame_speech_dedup
interaction_speech_visible_in_harness
agent_speech_visible_in_harness

feed_dialogue_does_not_block_gui

user_message_trace_single_root
rapid_two_messages_do_not_cross_trace
interaction_trace_has_real_before_after
agent_trace_has_plan_permission_tool_result
life_trace_records_actual_applied_selection

production_anti_collapse_is_off
```

旧 394 tests 全部回归。

注意：测试必须测**真实 route**；禁止再写“手工调用一次函数所以 exactly-once”的伪验收。

---

## 16. 自动真实 Smoke（完成后再给用户人测）

运行：

```text
python main.py --harness
```

用真实 glm 至少得到：

### Dialogue
```text
USER_INPUT root=A
→ DIALOGUE_REQUEST root=A
→ DIALOGUE_RESULT root=A
→ FRAME_SPEECH root=A
```

### Interaction
```text
PETTING
Emotion apply=1
Relationship apply=1
Dialogue=1
Frame speech=1
```

### Agent
```text
打开记事本
Agent started=1
Agent completed=1
Dialogue result=1
Frame speech=1
```

### Spatial
```text
harness.spatial is app._spatial
Panel coordinates == Proxy spatial truth
```

### Health
```text
No false glm badge
No hard-coded fallback NO
No Qt cross-thread QWidget mutation
No duplicate Agent event
No duplicate Relationship apply
```

---

## 17. Phase 13A PASS 条件

只有全部满足：

```text
Truth Panel tells truth                PASS
Single Spatial Runtime                PASS
Qt thread safety                      PASS
World context reaches direct dialogue PASS
Memory interpretation real            PASS
Emotion ownership single              PASS
Relationship apply exactly-once       PASS
Agent routing unified                 PASS
Agent events exactly-once             PASS
Frame.speech visible in Harness       PASS
Feed nonblocking                      PASS
Trace causal chain truthful           PASS
Trace root correlation                PASS
anti-collapse OFF in production       PASS
394 old tests                         PASS
```

才允许：

```text
Phase 13 Technical = PASS
Manual Functional = READY
```

然后停止代码开发，等待用户亲手验收。

---

## 18. 报告格式

```markdown
# Phase 13A — Functional Truth Closeout

## 0. Verdict
Technical:
Manual readiness:
Previous tests:
New tests:
Total:
Backend semantic params changed:
Assets changed:

## 1. REAL ROUTE EVIDENCE
### Dialogue root chain
### Interaction exactly-once
### Agent exactly-once
### Spatial single truth
### Feed nonblocking
### anti-collapse OFF proof

## 2. Truth Panel fixes

## 3. Qt thread proof

## 4. World + Memory context proof

## 5. Interaction ownership
Emotion writer:
Relationship writer:
Memory writer:

## 6. Agent ownership
Entry:
Lifecycle event owner:
Success count:
Failure count:
Dialogue count:

## 7. Frame Speech as UI truth

## 8. Trace correlation

## 9. Regression

## 10. Narrow Freeze Exceptions
逐项列出。

## 11. Remaining Debt
只允许：
- cross-session trace export（若没做）
- Harness visual polish
- known ASSET_DEBT
- Agent capability limitations

## 12. Verdict
只能： PASS / PARTIAL / FAIL

## 13. Next Step
PASS 时只能：
USER MANUAL FUNCTIONAL ACCEPTANCE

禁止开始 Phase 14。
```

---

# 最终原则

这轮不是继续“优化 Harness”。

只做一件事：

> **让用户接下来看到的每一个 badge、数值、trace、对话和方框位置，都确实对应同一个正式 Runtime 中真实发生的事情。**

完成后停止开发，让用户亲自使用。
