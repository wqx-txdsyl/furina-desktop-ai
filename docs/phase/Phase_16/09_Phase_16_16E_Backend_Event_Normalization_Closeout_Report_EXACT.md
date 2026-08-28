# Phase 16 — 16E Backend Event Normalization
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED（实现 + 测试完成，等待外部验收；不声明 16E_PASS）
BASE_SHA                       = 20c269a6951d8d9ea85a268a579ec93c22e0c1b2
                                 （16E_BASE_SHA：ACCEPTED_16D_SHA f2f323a 经 ff-only
                                 集成 + 16D docs-only closeout 修正后的集成 HEAD；
                                 本阶段以其为分支起点）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，沿用 16A/16B/16D 惯例）
BRANCH                         = feature/phase16-16e-event-normalization
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

EVENT_ENVELOPE_MODULE          = furina/agent/events/models.py（NormalizedEvent ——
                                 backend-neutral 不可变信封，字段至少含 event_id /
                                 backend_id / contract_id / run_id / sequence /
                                 occurred_at / received_at / kind / sanitized payload /
                                 terminal / critical / provenance；**terminal/critical
                                 为派生字段**（由 kind 决定，来源方不得自报，防止
                                 "完成/成功"自证）；payload 构造时自动脱敏（秘密键
                                 精确词表 + 控制字符清除 + 字符串限长 256 + 深度 8 +
                                 总序列化 <=4096B 超限 _truncated）+ 递归冻结 +
                                 防御复制导出 to_dict；EventKind 17 类 canonical 枚举 +
                                 UNKNOWN_EVENT；EventPriority 三态 + classify_priority +
                                 EventBackpressurePolicy（纯策略，无队列））
STATE_REDUCER_MODULE           = furina/agent/events/reducer.py（WorkExecutionReducer
                                 —— 每 run 一个，构造绑定 run_id+contract_id 身份，
                                 身份不匹配 raise；WorkExecutionView 不可变快照 +
                                 ReduceResult(applied/diagnostic/kind)；LEGAL_TRANSITIONS
                                 只读导出）+ normalizer.py（BackendEventNormalizer ——
                                 16B BackendEvent / Mapping 形状 → canonical 信封；
                                 词表对齐 Hermes _set_run_status 真实词表
                                 queued/running/waiting_for_approval/stopping/
                                 completed/cancelled/failed + SSE 事件面
                                 approval.request/tool.*/message.delta/reasoning*；
                                 **SSE done 哨兵按非权威帧标记 → UNKNOWN_EVENT**
                                 （绝不自造 completed）；缺 event_id 时内容寻址派生
                                 （同逻辑事件重复投递同 id）、缺 sequence 按到达补序
                                 —— 同一输入流重复归一结果完全一致）
LEGAL_TRANSITIONS_LOCKED       = true（全部 14 个 WorkExecutionState 的合法转移表
                                 逐行锁定：IDLE/STARTING/RUNNING/WAITING_PERMISSION/
                                 BLOCKED_APPROVAL/CANCELLING/BACKEND_DONE_UNVERIFIED/
                                 VERIFYING/REPAIRING/终态；outcome 依赖的
                                 APPROVAL_RESOLVED（approve/deny/timeout）与
                                 VERIFICATION_BOUNDARY（start/verified/failed/repair）
                                 单独分支；自环语义显式：RUNNING--run.started、
                                 WAITING--approval.requested、BLOCKED--再 deny、
                                 CANCELLING--stopping/stop、BDU--completed 确认）
COMPLETED_MAPS_UNVERIFIED      = true（backend completed **只**折算为
                                 BACKEND_DONE_UNVERIFIED；VERIFIED 唯一入口 =
                                 VERIFYING 经 verification.boundary(verified)，
                                 而该 kind **normalizer 永不产出**——backend 词表
                                 无法自造验证，有否证测试锁定任何 backend token
                                 （含 "verified"/"verification.boundary"/done 哨兵）
                                 归一为 UNKNOWN_EVENT 且状态零转移）
BACKEND_CAN_EMIT_VERIFIED      = false
DUPLICATE_IDEMPOTENT           = true（event_id 精确去重：重复投递 → applied=False +
                                 duplicate_event:<id>，零状态变更；内容寻址派生 id
                                 保证重投稳定）
OUT_OF_ORDER_FAIL_SAFE         = true（终态 CANCELLED/FAILED/VERIFIED/UNKNOWN 吸收：
                                 任何事件（除精确重复 id 与 UNKNOWN/PROTOCOL 纯观察）
                                 → terminal_absorbing:<state>:<kind> typed diagnostic
                                 且零状态变更；reconnect/progress 不得复活终态；
                                 乱序非终态事件按表裁决（非法 → illegal_transition）
                                 不静默改状态）
TOOL_RUNNING_SUBPHASE          = true（TOOL_RUNNING 是子相位，不是 primary：
                                 WorkExecutionView 分离 primary + tool_subphase +
                                 active_tool——tool.started 激活子相位（primary 保持
                                 RUNNING）、tool.progress 为 tick 不改变状态、
                                 tool.completed 退出子相位；primary 变化自动清空
                                 子相位（completed 结束工具）；state 属性在子相位
                                 激活时呈现 TOOL_RUNNING，其余呈现 primary；
                                 子相位非法序列（未开始即完成 / 已激活再开始）→
                                 typed diagnostic 零变更）
CRITICAL_EVENTS_DEFINED        = true（16E 只做分类，durable queue/ledger 属 16H：
                                 CRITICAL ⊇ terminal/approval/cancellation/disconnect/
                                 verification-boundary + run 生命周期 + protocol.error；
                                 DROPPABLE = TOOL_PROGRESS（token/tick 可丢）；
                                 COALESCIBLE = TOOL_STARTED/COMPLETED/reconnect/
                                 UNKNOWN_EVENT；EventBackpressurePolicy.never_droppable
                                 /drop_allowed(under_pressure)/coalesce_allowed 有测试；
                                 token/progress 流不写成 cognition truth——本包零
                                 cognition 依赖）
PAYLOAD_BOUNDED_REDACTED       = true（password/api_key/authorization/access_token/
                                 client_secret 等秘密键 → [REDACTED]；token_count/
                                 author 等含子串合法键不误伤；控制字符清除；字符串
                                 限长 256；超预算载荷 → 确定性 _truncated 标记；
                                 非 JSON-safe 对象整键丢弃；payload 递归冻结不可变）
WORK_STATE_WRITTEN_TO_C7       = false（工作域状态绝不写 C7；仅 16G 六态终态折算）
C6_EVENTS_APPENDED             = false（backend 运行事件非 C6 真值；16E 只定义
                                 投影接口语义，C6 append 归 16G；不引入重复 C6 词表）
HERMES_SHAPED_INPUT_ONLY       = true（Hermes-shaped fixture 只作为输入映射测试；
                                 NormalizedEvent/WorkExecutionState 生产类型零
                                 Hermes 专属字段——无 _run_statuses/
                                 _stopping_run_ids/chatToolEventFromRunEvent 等，
                                 有断言锁定）
DETERMINISTIC_REPLAY           = true（同一事件流在全新 reducer 上重复重放结果
                                 完全一致——内容寻址 id + 纯转移表 + 注入时钟；
                                 同 reducer 重投整流 → 全部 duplicate 且状态与计数
                                 不变；processed_count/max_sequence 确定性观测）

C1_C7_SCHEMA_CHANGED           = false
PRODUCTION_FILES_CHANGED       = 仅新增 furina/agent/events/ 包（models.py /
                                 normalizer.py / reducer.py / __init__.py）；
                                 未修改任何其它生产文件（16A work_contract.py /
                                 16B backend/ / 16D approval/ / agent_runtime.py /
                                 permission.py / app.py 等零改动；16A/16B/16D
                                 frozen contracts 未触碰）
TEST_FILES_CHANGED             = 仅新增 tests/agent/integration/test_phase16e_event_normalization.py
                                 （16 个测试函数 = 21 项断言场景，任务书 §7 全部
                                 12 项 + 额外锁定 4 项）
TARGETED_TESTS                 = tests/agent/integration/test_phase16e_event_normalization.py：
                                 21 passed。任务书 §7 十二项逐项锁定：
                                 1) 完整合法转移表（LEGAL_TRANSITIONS 逐行 + approval
                                    outcome 分支 + verification.boundary 分支 +
                                    TOOL_RUNNING 子相位转移）；
                                 2) 非法转移 fail-safe（17 组 (state,kind) 反例 +
                                    子相位非法序列：illegal_transition: typed
                                    diagnostic + 快照/计数/sequence 全零变更）；
                                 3) completed → BACKEND_DONE_UNVERIFIED 且全路径
                                    永不 VERIFIED（backend 词表 token 含 verified/
                                    verification.boundary/done 全部归一 UNKNOWN 且
                                    零转移；VERIFIED 只经 16F 校验边界可达）；
                                 4) duplicate event_id 幂等 + 乱序不得回退终态
                                    （终态后 reconnect/progress/completed/cancelled
                                    一律 terminal_absorbing 零变更）；
                                 5) 未知外部事件 typed UNKNOWN_EVENT 可观察
                                    （processed_count 计数）但非权威（零转移，
                                    任意状态含终态均为纯观察）；
                                 6) approval 全路径（requested→resolved approve /
                                    deny→blocked→approve）与 cancellation 全路径
                                    （stop→CANCELLING→cancelled/failed）；
                                 7) disconnect→UNKNOWN 策略边界（五状态出发 +
                                    UNKNOWN 吸收 + reconnect 不复活终态）；
                                 8) critical 事件分类（17 类逐一断言 + 信封派生
                                    terminal/critical 字段 + 背压策略纯声明）；
                                 9) payload 脱敏与大小上限（5 类秘密键脱敏 +
                                    误伤豁免 + 控制字符 + 限长 256 + 超预算
                                    _truncated + 递归冻结不可变 + 非 JSON-safe
                                    丢弃）；
                                 10) WorkExecutionState 零写入 C7/C6（子进程导入
                                     守卫：events 包不拉入 furina.cognition；真实
                                     CognitionHub store 跑完完整会话后
                                     life_events/agent_tasks/agent_task_steps 零行）；
                                 11) Native 词表与 Hermes-shaped fixture 归一为
                                     相同语义（状态序列完全一致；SSE done 哨兵
                                     非权威不推进；生产类型无 Hermes 字段）；
                                 12) 同一事件流重复重放确定性（3 次 fresh replay
                                     结果逐项一致；同 reducer 重投幂等）。
                                 额外锁定：信封字段校验 fail-closed（11 组非法值）/
                                 reducer run_id+contract_id 身份绑定（不匹配 raise +
                                 未归一 dict 拒绝）/ sequence+processed_count 观测 /
                                 信封 to_dict 防御复制
AGENT_EVENT_REGRESSION         = pytest tests/agent tests/test_agent_tools.py
                                 tests/test_skeleton.py：337 passed
                                 （15 warnings 为既有线程 ResourceWarning 类告警，
                                 与本阶段无关；较 16D 的 316 +21 = 16E 新增专项）；
                                 另跑 16A/16B/16D 专项
                                 tests/agent/integration/test_phase16b_execution_backend.py
                                 test_phase16a_work_contract.py
                                 test_phase16d_permission_approval.py：198 passed
                                 （161 + 37）
COGNITION_SUITE                = pytest tests/cognition：279 passed（Phase 15
                                 cognition/store 契约不变；events 包零 cognition
                                 依赖有专项断言）
FULL_SUITE                     = .venv/Scripts/python.exe -m pytest -q：第二次
                                 1582 passed, 0 failed（328.73s，exit 0），
                                 较 16D 的 1561 恰 +21（16E 专项）。
                                 首次运行 1581 passed + 1 failed
                                 （tests/test_gui_integration.py::
                                 test_gui_timer_advances_runtime —— Qt 定时器在
                                 满载 full suite CPU 争用下未在 drive 窗口内推进
                                 生命周期；该测试隔离运行 2.31s 通过、第二次全量
                                 1582 全过，判定为环境性时序 flake，与 16E 无关
                                 —— 16E 零改动 GUI/AnimationRuntime/EventBus 路径）

REMAINING_GAPS                 = 1) 按 brief 无 Hermes(16C)/verifier+repair(16F)/
                                   durable queue+ledger+recovery(16H)/C7 commit
                                   (16G)/MCP——全部留待对应子阶段；2) 事件面仍为
                                   进程内状态机，未接入 NativeAgentRuntimeBackend
                                   submit/events 生产 wiring 与全局 EventBus 枚举
                                   （16E 只定义 envelope+reducer 契约；消费接线属
                                   后续子阶段）；3) VERIFYING/REPAIRING/VERIFIED
                                   的转移规则已定义（16F 将消费 VERIFICATION_BOUNDARY
                                   kind），16E 不实现 verifier 本身；4) 背压只做
                                   分类声明，有界队列/丢弃策略实现在 16H；5) 基线
                                   已有 untracked（data/assets_v2/、scripts/
                                   assets_v2/、_night_*、nul）保持未触碰
READY_FOR_REVIEW               = YES
```

No fabricated PASS or test totals. External reviewer owns `16E_PASS`.
