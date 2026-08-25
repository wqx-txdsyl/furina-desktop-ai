# Phase 13B — §7 / §9 / §10 / §11 / §13 闭合

## 0. Verdict

```
Technical:            PASS
Manual readiness:     READY（等待用户亲手使用 Harness）
Previous tests:       405
New tests:            7 (test_phase13b.py)
Total:                412
Backend semantic params changed: 0
Assets changed:       NONE
```

## 1. REAL ROUTE EVIDENCE（tests 真实 route，非伪造）

### §7 Agent lifecycle exactly-once
- `AgentRuntime.execute` 是 AGENT_STARTED/COMPLETED/FAILED **唯一 owner**；`App._agent_worker` **不再重复 emit**。
- `test_agent_lifecycle_single_owner`：App worker 源码无 `self.bus.emit(EventType.AGENT_COMPLETED/FAILED`。
- 统一入口 `Furina.submit_agent_task(request, extra_context)`（右键 + Harness 共用）；notepad/calc/organize-test 全走它，Harness 不再特判直接 `agent.execute`。
- Agent fail 反馈 → `_on_agent_fail` 经 `DialogueBrain`（`_speak_via_dialogue`, task_mode）；仅当对话失败才显示 `SYSTEM_STATUS` 事实（不冒充 Furina 台词）。`test_agent_failure_routes_dialoguebrain`。

### §9 Feed 非阻塞
- `harness.on_feed` 立即返回（效果 + Dialogue 放后台），GUI 不等待 LLM。`test_feed_does_not_block_gui`（<0.2s 返回）。
- Feed 因果 trace（NEEDS before/after）由后台线程读真实需求快照记录。

### §10 最小可信因果 Trace（不伪造不存在的 stage）
- Interaction：`on_interact` 记录 EMOTION_BEFORE_AFTER + RELATIONSHIP_BEFORE_AFTER（真实只读快照）。`test_interaction_trace_has_real_before_after`。
- Feed：NEEDS before/after trace。`test_feed_trace_has_needs`。
- Dialogue：LLM_REQUEST / LLM_RESULT（真实 wrapper）。Frame：FRAME_SPEECH（真实 Frame.speech）。
- Agent：订阅真实 AGENT_STARTED/COMPLETED/FAILED → REQUEST/RESULT trace（无伪造 plan/permission 子步；只记真实发生的生命周期阶段）。
- **未伪造** `VALIDATOR` 等不存在的 stage。

### §11 跨线程 root correlation
- 显式 `contextvars.ContextVar("harness_root")`（线程安全，非"当前全局 trace"）。
- 后台 Dialogue request/result 经 `child_to_root(root_trace_id)` 关联到用户 root。`test_cross_root_no_contamination`：A/B 快发 + 让 B 先完成 → 两个独立 root，无跨根污染（每 root 只含自己 reply）。

### §13 Memory badge
- `runtime_health()["memory"]` 只显示 `AVAILABLE / EMPTY / UNAVAILABLE`（不展示假精确行数）。`test_memory_badge_honest`。

### §1/§2/§3/§8 复核（P13A 已闭合，本节复核）
- 不假绿（health 真实）；单一 SpatialRuntime；Qt 线程安全（drain_chat 在 GUI 线程）；Frame.speech=对话真相 + 去重。

## 2. 修改文件
- `furina/app.py`：`submit_agent_task`（统一入口）、`_agent_worker` 移除重复 emit + extra_context path、`AGENT_TASKS` 加"打开计算器"、`_feed`/`_brain_worker` 世界上下文 + memory 对象。
- `furina/runtime/scheduler.py`：`_on_agent_fail` → DialogueBrain；`_speak_via_dialogue` memory 对象。
- `furina/runtime/observability/trace.py`：`child_to_root`。
- `furina/runtime/harness/controller.py`：feed 后台、agent 事件 trace、contextvar root、interaction before/after、memory 状态。
- `furina/runtime/harness/window.py`：drain_chat（GUI 线程）、health badge。

## 3. Regression
```
Previous: 405
New:      7 → total 412
Broken:   0
```

## 4. Known minor debt（非 P13B blocker）
- Agent plan/permission/tool 子步未逐条打点（只按真实生命周期阶段记录，按 §10 不伪造）。
- FRAME_SPEECH 与 dialogue root 的关联为 best-effort（"最近 root"）；对话 request/result 关联是严格的（contextvar）。

## 5. Conformance（P13B PASS 条件）
```
Agent duplicate lifecycle events = 0        ✅
Agent failure fixed-text Furina bypass = 0  ✅
Feed GUI blocking = 0                        ✅
Cross-root contamination = 0                 ✅
Truth badge known-false values = 0           ✅
Required causal trace gaps = 0（无伪造 stage）✅
Existing tests (405) all PASS                ✅（total 412）
Backend semantic parameter changes = 0       ✅
```

## 6. Final
```
Phase 13 Technical = PASS
Manual Functional = READY
```

**停止开发**。请用户运行 `python main.py --harness` 亲手验收（docs/PHASE13_MANUAL_ACCEPTANCE.md 的 Scenario A-J + Persona）。只有用户确认"即使只有方框，她已有'在电脑里生活'的感觉"才 = Functional Digital Life PASS。**不开始 Phase 14，不补素材，不调任何参数。**
