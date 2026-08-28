# Phase 16 — 16E Backend Event Normalization
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED（Reviewer Patch 2 修复完成 + 全量测试通过，
                                 等待外部验收；不声明 16E_PASS）
BASE_SHA                       = a691b59505022af814a07dad3dda9c3d5c91d334
                                 （Reviewer Patch 1 FINAL_SHA；Patch 2 以此为基；
                                 16E 初版基线 7658ab30… 见 REVIEWER_PATCH_1 记录）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，沿用 16A/16B/16D 惯例）
BRANCH                         = feature/phase16-16e-event-normalization
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

REVIEWER_PATCH_2               = 5 项 blocker 全部修复并逐一否证锁定（test_patch2a–2e）：
                                 1) Mapping 别名无歧义（身份字段 backend_id/backendId、
                                    contract_id/contractId、run_id/runId 所有已出现
                                    别名逐一校验等于绑定值，不得检查第一个后 break；
                                    event_id/eventId/id、sequence/seq/number、时间、
                                    kind/status 多别名同时出现等值允许、冲突值拒绝；
                                    显式出现但类型/范围非法的 event_id/sequence/
                                    timestamp/payload 不得当作缺失自动补值）；
                                 2) fallback event_id 每次到达唯一（独立 arrival
                                    ordinal 递增，派生 id 纳入 arrival——显式 sequence
                                    后接缺 sequence、重复显式 sequence、混合流均不得
                                    碰撞；fresh normalizer 重放同一输入流确定性一致；
                                    只有上游稳定 event_id 才声明强重投幂等）；
                                 3) max_payload_bytes 是真实 UTF-8 byte 上限
                                    （len(encoded.encode("utf-8"))；truncation marker
                                    自身也不超预算——最小预算 128B fail-closed，不允许
                                    声称允许 1 byte 却返回超预算 JSON；original_bytes
                                    记录真实 UTF-8 bytes）；
                                 4) approval_id 精确绑定（禁止 [:128] 静默截断，非法/
                                    超长/control-char/别名冲突 ID 直接 approval_id_
                                    invalid 拒绝；WAITING_PERMISSION 中同 approval_id
                                    重投为幂等观察、不同 approval_id 请求为 typed
                                    approval_id_conflict 零状态变更不覆盖 pending；
                                    BLOCKED_APPROVAL 仍允许新合法请求；长 ID 第 129
                                    字符不同不得互相批准）；
                                 5) tool lifecycle 身份配对（TOOL_STARTED 必须建立
                                    非空 active_tool；TOOL_PROGRESS/TOOL_COMPLETED
                                    的工具身份必须与 active_tool 一致，缺失或不同均
                                    typed diagnostic 零状态变化；fs.read active 时
                                    fs.delete completed 不得关闭子相位；工具名不再
                                    [:128] 截断配对）
                                 适配：既有 28 项测试全数保留并适配更严格语义
                                 （WAITING 自环重投须带同 approval_id；tool.progress/
                                 completed 事件携带工具身份；max_payload_bytes 最小
                                 预算 128），新增 5 项 reviewer-locked 否证，专项 33

REVIEWER_PATCH_1               = 8 项 blocker 全部修复并逐一否证锁定：
                                 1) VERIFIED 在 16E 阶段 fail-closed（VB(verified)
                                    一律 unauthorized_verification；provenance/
                                    _private 不得冒充 authority；全状态全事件扫描
                                    VERIFIED 不可达）；
                                 2) normalizer/reducer 精确身份绑定（BackendEvent
                                    backend_id/run_id、Mapping 携带身份字段不一致
                                    一律拒绝；reducer 实际检查 backend_id 且构造
                                    要求非空 backend_id）；
                                 3) _seen 改为 event_id→canonical fingerprint
                                    （同 id 同内容 duplicate / 同 id 不同内容
                                    event_id_conflict / 非法事件不烧毁 id 可重放）；
                                 4) fallback event_id 纳入 sequence（同内容两次
                                    tool.started/completed 是两次事件；只有上游
                                    稳定 event_id 才声明强重投幂等）；
                                 5) payload 秘密值形态脱敏（message/stdout/error/
                                    list 内 Bearer/authorization/password/token/
                                    secret/api_key 形态）+ max_payload_bytes
                                    type-is-int 严格校验；
                                 6) approval.requested/resolved 绑定 approval_id
                                    （deny/timeout 后同 id approve 不得恢复
                                    RUNNING；不相关 id 不得改变状态）；
                                 7) TOOL_STARTED/TOOL_COMPLETED 不可丢、不可合并
                                    （critical）；只有 TOOL_PROGRESS/token delta
                                    可 drop/coalesce；
                                 8) 新增 7 项 reviewer-locked 否证测试
                                    （test_patch1a–1g）、删除重复 _drive 定义、
                                    GUI flake 措辞改为"未稳定复现，不声明已证伪"

EVENT_ENVELOPE_MODULE          = furina/agent/events/models.py（NormalizedEvent ——
                                 backend-neutral 不可变信封，字段至少含 event_id /
                                 backend_id / contract_id / run_id / sequence /
                                 occurred_at / received_at / kind / sanitized payload /
                                 terminal / critical / provenance；**terminal/critical
                                 为派生字段**（由 kind 决定，来源方不得自报，防止
                                 "完成/成功"自证）；payload 构造时自动脱敏（秘密键
                                 精确词表 + **秘密值形态脱敏**（message/stdout/error/
                                 list 内 Bearer/authorization/password/token/secret/
                                 api_key 键值/头/凭证形态 → [REDACTED]）+ 控制字符
                                 清除 + 字符串限长 256 + 深度 8 + 总序列化
                                 **UTF-8 字节** <=4096B（len(encoded.encode("utf-8"))，
                                 多字节字符不得以字符数绕过预算）超限 _truncated
                                 （original_bytes 记录真实 UTF-8 bytes；truncation
                                 marker 自身也落在预算内）；**max_payload_bytes 严格
                                 校验**：type-is-int、非 bool、**最小预算 128B** <= n
                                 <= 1MiB，bool/float/低于最小预算/超上限构造即拒绝
                                 （不允许"声称允许 1 byte 却返回超预算 JSON"）+
                                 递归冻结 + 防御复制导出
                                 to_dict；EventKind 17 类 canonical 枚举 +
                                 UNKNOWN_EVENT；EventPriority 三态 + classify_priority +
                                 EventBackpressurePolicy（纯策略，无队列））
STATE_REDUCER_MODULE           = furina/agent/events/reducer.py（WorkExecutionReducer
                                 —— 每 run 一个，构造绑定 backend_id+run_id+
                                 contract_id 身份，**事件任一身份不匹配 raise**
                                 （含 backend_id——此前只查 run/contract）；
                                 WorkExecutionView 不可变快照 + ReduceResult(applied/
                                 diagnostic/kind)；LEGAL_TRANSITIONS 只读导出）+
                                 normalizer.py（BackendEventNormalizer —— 16B
                                 BackendEvent / Mapping 形状 → canonical 信封；
                                 **身份不一致直接拒绝**：BackendEvent 的 backend_id/
                                 run_id、Mapping 携带的身份字段（backend_id/
                                 contract_id/run_id 及别名键）必须与构造绑定一致，
                                 非 str 或值不一致一律 EventNormalizationError，
                                 不静默改绑；词表对齐 Hermes _set_run_status 真实
                                 词表 queued/running/waiting_for_approval/stopping/
                                 completed/cancelled/failed + SSE 事件面 approval
                                 .request/tool.*/message.delta/reasoning*；**SSE
                                 done 哨兵按非权威帧标记 → UNKNOWN_EVENT**（绝不
                                 自造 completed）；**别名无歧义**（身份字段所有已出现
                                 别名逐一校验等于绑定值；event_id/sequence/时间戳/
                                 kind/payload 多别名同时出现等值允许、冲突值拒绝；
                                 显式出现但类型/范围非法不得当作缺失补值——有否证
                                 测试）；缺 event_id 时**按到达顺序内容寻址派生
                                 （fallback id 纳入独立递增的 arrival ordinal——每次
                                 到达唯一：显式 sequence 后接缺 sequence、重复显式
                                 sequence、混合流均不得碰撞；同内容两次事件 = 两次
                                 不同事件，不得被误去重）**、缺 sequence 按到达
                                 补序——同一输入流（fresh normalizer）重复归一结果
                                 完全一致）
LEGAL_TRANSITIONS_LOCKED       = true（全部 14 个 WorkExecutionState 的合法转移表
                                 逐行锁定：IDLE/STARTING/RUNNING/WAITING_PERMISSION/
                                 BLOCKED_APPROVAL/CANCELLING/BACKEND_DONE_UNVERIFIED/
                                 VERIFYING/REPAIRING/终态；outcome 依赖的
                                 APPROVAL_RESOLVED（approve/deny/timeout，**必须
                                 绑定 approval_id**）与 VERIFICATION_BOUNDARY
                                 （start/failed/repair；verified 见下）单独分支；
                                 **approval.requested 绑定 approval_id 并进入挂起
                                 态，BLOCKED_APPROVAL 收到新请求 → 重新挂起
                                 （WAITING_PERMISSION）**；自环语义显式：
                                 RUNNING--run.started、WAITING--approval.requested、
                                 CANCELLING--stopping/stop、BDU--completed 确认）
COMPLETED_MAPS_UNVERIFIED      = true（backend completed **只**折算为
                                 BACKEND_DONE_UNVERIFIED；**VERIFIED 在 16E 阶段
                                 不可由公开事件抵达**：公开 reducer 对
                                 VERIFICATION_BOUNDARY(verified) 一律 fail-closed
                                 （unauthorized_verification typed diagnostic、
                                 零状态变更）——16E 无 verifier authority，provenance
                                 字符串/Python _private 属性均不得冒充 authority；
                                 16F 建立真实 verifier 后由注入权威通道开放。
                                 backend 词表含 "verified"/"verification.boundary"/
                                 done 哨兵一律归一 UNKNOWN_EVENT 非权威；有全状态
                                 全事件扫描否证：任何可达状态喂任何 EventKind，
                                 primary 永不成为 VERIFIED）
BACKEND_CAN_EMIT_VERIFIED      = false
DUPLICATE_IDEMPOTENT           = true 且精确化（**event_id→canonical fingerprint**
                                 去重：同 id 同内容（身份+kind+清洗后 payload）=
                                 duplicate_event；同 id 不同内容 =
                                 event_id_conflict（typed diagnostic、零变更）；
                                 **被拒绝的事件不烧毁 id**——先非法后满足前置条件
                                 的同一事件可重放（有否证测试）；**只有上游显式
                                 提供的稳定 event_id 才声明强重投幂等**——内容寻址
                                 fallback id 已纳入 sequence，仅在同一归一化流位置
                                 稳定，同内容两次事件是两次不同事件，不得被误去重）
OUT_OF_ORDER_FAIL_SAFE         = true（终态 CANCELLED/FAILED/VERIFIED/UNKNOWN 吸收：
                                 任何事件（除精确重复 id 与 UNKNOWN/PROTOCOL 纯观察）
                                 → terminal_absorbing:<state>:<kind> typed diagnostic
                                 且零状态变更；reconnect/progress 不得复活终态；
                                 乱序非终态事件按表裁决（非法 → illegal_transition）
                                 不静默改状态）
TOOL_RUNNING_SUBPHASE          = true 且精确化（TOOL_RUNNING 是子相位，不是
                                 primary：WorkExecutionView 分离 primary +
                                 tool_subphase + active_tool——tool.started 激活
                                 子相位（primary 保持 RUNNING）、tool.progress 为
                                 tick 不改变状态、tool.completed 退出子相位；primary
                                 变化自动清空子相位（completed 结束工具）；state
                                 属性在子相位激活时呈现 TOOL_RUNNING，其余呈现
                                 primary；**工具身份配对（Reviewer Patch 2）**：
                                 TOOL_STARTED 必须建立非空 active_tool（缺工具名/
                                 空名 → tool_identity_invalid 零变更）；TOOL_PROGRESS/
                                 TOOL_COMPLETED 的工具身份必须与 active_tool 一致
                                 （缺失 → tool_identity_invalid、不同 →
                                 tool_identity_mismatch，均 typed diagnostic 零变更；
                                 **fs.read active 时 fs.delete completed 不得关闭
                                 子相位**；工具名不做 [:128] 截断配对，超长拒绝）；
                                 子相位非法序列（未开始即完成 / 已激活再开始）→
                                 typed diagnostic 零变更）
CRITICAL_EVENTS_DEFINED        = true 且精确化（16E 只做分类，durable queue/ledger
                                 属 16H：CRITICAL ⊇ terminal/approval/cancellation/
                                 disconnect/verification-boundary + run 生命周期 +
                                 protocol.error + **TOOL_STARTED/TOOL_COMPLETED
                                 （不可丢、不可合并的工具生命周期边界——丢/合并会
                                 破坏子相位成对语义）**；DROPPABLE = TOOL_PROGRESS
                                 （唯一可丢弃的 token delta）；COALESCIBLE 仅
                                 reconnect/unknown 观察；EventBackpressurePolicy
                                 .never_droppable/drop_allowed(under_pressure)/
                                 coalesce_allowed 有测试；token/progress 流不写成
                                 cognition truth——本包零 cognition 依赖）
PAYLOAD_BOUNDED_REDACTED       = true 且精确化（秘密**键**（password/api_key/
                                 authorization/access_token/client_secret/token/
                                 x-api-key/x-authorization 等精确词表 + 紧凑形）→
                                 [REDACTED]；**秘密值形态**（message/stdout/error/
                                 list 内 "Authorization: Bearer xyz" /
                                 "password=hunter2" / "api_key: sk-…" / JSON
                                 '{"access_token":"…"}' 等键值/头/凭证形态）→
                                 标签保留、秘密部分 [REDACTED]；token_count/author
                                 等含子串合法键与自然语言不误伤；控制字符清除；
                                 字符串限长 256；超预算载荷 → 确定性 _truncated
                                 标记；非 JSON-safe 对象整键丢弃；payload 递归
                                 冻结不可变；max_payload_bytes type-is-int 严格
                                 校验（bool/float/低于最小预算 128B/0/负/超 1MiB
                                 构造即拒绝；**超限判据是真实 UTF-8 字节
                                 len(encoded.encode("utf-8"))**——字符数 <= 预算但
                                 字节数超预算的载荷必须截断，original_bytes 记录
                                 真实 UTF-8 bytes；truncation marker 自身也不超
                                 预算——有否证测试））
APPROVAL_ID_BOUND              = true 且精确化（Reviewer Patch 2：approval.
                                 requested/resolved **必须精确绑定 approval_id**——
                                 **禁止 [:128] 静默截断**，显式非法/超长（>128）/
                                 control-char/多别名冲突 ID 直接 approval_id_invalid
                                 typed diagnostic 零变更（长 ID 第 129 字符不同不得
                                 互相批准，有否证测试）；payload 显式或回退请求事件
                                 自身 canonical event_id——确定性绑定、不虚构）；
                                 resolved 只能作用于当前挂起的 approval_id，不相关/
                                 缺失 → approval_id_mismatch typed diagnostic 零变更；
                                 **WAITING_PERMISSION 中同 approval_id 重投为幂等
                                 观察（applied 无诊断）、不同 approval_id 请求为
                                 approval_id_conflict（零变更，**绝不覆盖 pending**，
                                 以原 id 仍可 approve）**；**BLOCKED_APPROVAL 仍允许
                                 新合法 approval 请求（新 id → 重新挂起）**；
                                 approve/deny/timeout 消费即销毁（一次性）；
                                 deny/timeout 后同 approval_id 的 approve 不得
                                 恢复 RUNNING；恢复必须经新的 approval.requested
                                 （新 approval_id）；畸形 outcome 拒绝但不消费挂起
                                 请求——有否证测试）
WORK_STATE_WRITTEN_TO_C7       = false（工作域状态绝不写 C7；仅 16G 六态终态折算）
C6_EVENTS_APPENDED             = false（backend 运行事件非 C6 真值；16E 只定义
                                 投影接口语义，C6 append 归 16G；不引入重复 C6 词表）
HERMES_SHAPED_INPUT_ONLY       = true（Hermes-shaped fixture 只作为输入映射测试；
                                 NormalizedEvent/WorkExecutionState 生产类型零
                                 Hermes 专属字段——无 _run_statuses/
                                 _stopping_run_ids/chatToolEventFromRunEvent 等，
                                 有断言锁定）
DETERMINISTIC_REPLAY           = true 且精确化（同一事件流在全新 reducer 上重复
                                 重放结果完全一致——fallback id 确定性（arrival
                                 ordinal 独立递增：fresh normalizer 重放同一完整
                                 输入流 → 同一 id 序列；显式 sequence 后接缺
                                 sequence、重复显式 sequence、混合流均不碰撞——
                                 有否证测试）+ fingerprint 去重 + 纯转移表 + 注入
                                 时钟；同 reducer 重投整流（上游稳定 id）→ 全部
                                 duplicate 且状态与计数不变；processed_count/
                                 max_sequence 确定性观测）

C1_C7_SCHEMA_CHANGED           = false
PRODUCTION_FILES_CHANGED       = 仅新增 furina/agent/events/ 包（models.py /
                                 normalizer.py / reducer.py / __init__.py），
                                 Reviewer Patch 1 只修改这三个生产模块；
                                 未修改任何其它生产文件（16A work_contract.py /
                                 16B backend/ / 16D approval/ / agent_runtime.py /
                                 permission.py / app.py 等零改动；16A/16B/16D
                                 frozen contracts 未触碰）
TEST_FILES_CHANGED             = 仅新增 tests/agent/integration/test_phase16e_event_normalization.py
                                 （33 个测试函数 = 任务书 §7 十二项 + 额外锁定 4 项
                                 + Reviewer Patch 1 否证 7 项 + Reviewer Patch 2
                                 否证 5 项；既有 28 项全数保留并适配更严格语义）
TARGETED_TESTS                 = tests/agent/integration/test_phase16e_event_normalization.py：
                                 33 passed（Reviewer Patch 2 否证 5 项 test_patch2a–2e
                                 覆盖 5 个 blocker；既有 28 项适配后全过）。任务书
                                 §7 十二项逐项锁定：
                                 1) 完整合法转移表（LEGAL_TRANSITIONS 逐行 + approval
                                    outcome 分支（approval_id 绑定）+ verification
                                    .boundary 分支 + TOOL_RUNNING 子相位转移）；
                                 2) 非法转移 fail-safe（17 组 (state,kind) 反例 +
                                    子相位非法序列：illegal_transition: typed
                                    diagnostic + 快照/计数/sequence 全零变更）；
                                 3) completed → BACKEND_DONE_UNVERIFIED 且全路径
                                    永不 VERIFIED（backend 词表 token 含 verified/
                                    verification.boundary/done 全部归一 UNKNOWN 且
                                    零转移；VB(verified) fail-closed 拒绝）；
                                 4) duplicate/conflict/乱序（event_id→fingerprint：
                                    同 id 同内容 duplicate、同 id 不同内容
                                    event_id_conflict、非法事件不烧毁 id 可重放；
                                    乱序不得回退终态）；
                                 5) 未知外部事件 typed UNKNOWN_EVENT 可观察
                                    （processed_count 计数）但非权威（零转移，
                                    任意状态含终态均为纯观察）；
                                 6) approval 全路径（requested→resolved approve /
                                    deny→blocked→新请求→approve）与 cancellation
                                    全路径（stop→CANCELLING→cancelled/failed）；
                                 7) disconnect→UNKNOWN 策略边界（五状态出发 +
                                    UNKNOWN 吸收 + reconnect 不复活终态）；
                                 8) critical 事件分类（17 类逐一断言 + 工具生命周期
                                    边界 critical + 信封派生字段 + 背压策略纯声明）；
                                 9) payload 脱敏与大小上限（秘密键 + 秘密值形态 +
                                    误伤豁免 + 控制字符 + 限长 256 + 超预算
                                    _truncated + 递归冻结不可变 + 非 JSON-safe
                                    丢弃 + max_payload_bytes 严格校验）；
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
                                 reducer backend_id+run_id+contract_id 身份绑定
                                 （不匹配 raise + 未归一 dict 拒绝 + 构造要求非空
                                 backend_id）/ sequence+processed_count 观测 /
                                 信封 to_dict 防御复制（工具边界 critical 派生）。
                                 Reviewer Patch 1 否证（7 项，见 REVIEWER_PATCH_1
                                 逐条对应 test_patch1a–1g）
                                 Reviewer Patch 2 否证（5 项，见 REVIEWER_PATCH_2
                                 逐条对应 test_patch2a–2e；另含既有 28 项对
                                 更严格语义的适配说明）
AGENT_EVENT_REGRESSION         = pytest tests/agent tests/test_agent_tools.py
                                 tests/test_skeleton.py：349 passed
                                 （15 warnings 为既有线程 ResourceWarning 类告警，
                                 与本阶段无关；16D 的 316 + 16E 专项 33 = 349）；
                                 另跑 16A/16B/16D 专项
                                 tests/agent/integration/test_phase16b_execution_backend.py
                                 test_phase16a_work_contract.py
                                 test_phase16d_permission_approval.py：198 passed
                                 （161 + 37；与 16E 专项合并跑 231 passed）
COGNITION_SUITE                = pytest tests/cognition：279 passed（Phase 15
                                 cognition/store 契约不变；events 包零 cognition
                                 依赖有专项断言）
FULL_SUITE                     = .venv/Scripts/python.exe -m pytest -q：1594 passed,
                                 0 failed（326.18s，exit 0），较 Patch 1 的 1589 恰
                                 +5（16E Patch 2 新增否证；初版 1589 较 16D 的 1561
                                 恰 +28）。
                                 GUI flake 说明：16E 初版曾出现一次
                                 tests/test_gui_integration.py::
                                 test_gui_timer_advances_runtime 失败（Qt 定时器在
                                 满载 full suite CPU 争用下未在 drive 窗口内推进
                                 生命周期）；该测试隔离运行通过、Patch 1 全量亦
                                 通过，**未稳定复现，不声明已证伪**——16E 零改动
                                 GUI/AnimationRuntime/EventBus 路径，但相关性判定
                                 留给外部验收

REMAINING_GAPS                 = 1) 按 brief 无 Hermes(16C)/verifier+repair(16F)/
                                   durable queue+ledger+recovery(16H)/C7 commit
                                   (16G)/MCP——全部留待对应子阶段；2) 事件面仍为
                                   进程内状态机，未接入 NativeAgentRuntimeBackend
                                   submit/events 生产 wiring 与全局 EventBus 枚举
                                   （16E 只定义 envelope+reducer 契约；消费接线属
                                   后续子阶段）；3) VERIFYING/REPAIRING 的转移规则
                                   已定义（16F 将消费 VERIFICATION_BOUNDARY kind
                                   并注入真实 verifier authority 开放 VERIFIED 通道），
                                   16E 不实现 verifier 本身且 verified fail-closed；
                                   4) 背压只做分类声明，有界队列/丢弃策略实现在
                                   16H；5) 基线已有 untracked（data/assets_v2/、
                                   scripts/assets_v2/、_night_*、nul）保持未触碰；
                                   6) 说明：payload 内 approval_id 的 control-char
                                   在信封层已被确定性清洗（\x00→空格，有测试断言），
                                   reducer 侧的 _CTRL_RE 防御性检查保留（fail-closed
                                   for 任何绕过清洗的直接构造路径），不声明 control-
                                   char 在 reducer 层"显式拒绝"
READY_FOR_REVIEW               = YES
```

No fabricated PASS or test totals. External reviewer owns `16E_PASS`.
