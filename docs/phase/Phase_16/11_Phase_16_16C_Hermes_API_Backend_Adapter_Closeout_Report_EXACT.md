# Phase 16 — 16C Hermes API Backend Adapter
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED — Reviewer Patch 6（permit 最终消费收归
                                 主 broker：两个真实远端副作用边界——新操作
                                 grant-covered once 与 resolve 后 once——的 permit
                                 一律由构造期注入主 broker 公开 producer API
                                 consume_permit（真实 tool/capability/帧时刻冻结
                                 args）原子消费，绝不 gate.consume_permit（Gate 恒
                                 委托其自身 broker——foreign Gate 会把 permit 消费
                                 到 foreign broker 台账的跨 broker TOCTOU 封闭）；
                                 foreign permit 即使 grant_id/approval_id/契约/
                                 tool/capability/scope 全同且主 broker 存在同名
                                 有效授权，也因 permit 不在主 broker 台账被拒绝
                                 零 once；主 broker 撤销/超时/消费状态在唯一消费锁
                                 内重查 + 4 项 reviewer 专项否证新增，全量测试通过，
                                 等待外部验收；Final Documentation/Test Hygiene
                                 Micro-Patch（测试私有字段访问收归 16D 公开 API +
                                 cognition 精确计数，零生产代码改动）后状态不变；
                                 不声明 16C_PASS）
BASE_SHA                       = fad0a0723e515a2f893465d7a3fa32de9fec40a9
                                 （16C Reviewer Patch 6 提交；本 Final
                                 Documentation/Test Hygiene Micro-Patch 唯一父
                                 提交；Patch 6 自身 base = 0684753e7e0e…，
                                 见下方 Patch 6 摘要节）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，
                                 沿用 16A/16B/16D/16E 惯例）
BRANCH                         = feature/phase16-16c-hermes-api-adapter
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

HERMES_VERSION_PROBED          = 0.20.6（2026.8.27，upstream 4e7eb399；本 patch 补充
                                 源码取证：_resolve_model_name（api_server.py:1786）——
                                 非 default/custom profile 名进入 /v1/capabilities 的
                                 model 广告（"each profile advertises a distinct
                                 model"）；_handle_toolsets（api_server.py:4092）——
                                 GET /v1/toolsets 返回 api_server 平台实际暴露给 run
                                 agent 的工具面（enabled + 解析后具体工具名）；不存在
                                 run_id 上 status/events/approval/stop 四端点全部
                                 404 run_not_found 且零副作用）
RUNS_SURFACE_AVAILABLE         = true（POST /v1/runs → 202 {"run_id","status":
                                 "started"}；GET /v1/runs/{id} → hermes.run 状态
                                 记录；GET /v1/runs/{id}/events → SSE data 帧 +
                                 : keepalive 心跳 + : stream closed 哨兵；
                                 POST …/approval；POST …/stop → stopping ——
                                 全部本机实测 + 源码双重确认）
CAPABILITIES_ADVERTISED        = true（features.run_submission / run_status /
                                 run_events_sse / run_stop / run_approval_response
                                 实测全 True）
PROFILE_IDENTITY_BOUND         = true（Reviewer Patch 1：expected_profile_identity
                                 为构造期必填；probe 把 /v1/capabilities.model 与其
                                 **精确比对**——缺失 → profile_identity_missing、
                                 不一致 → profile_identity_mismatch，均 unhealthy；
                                 无缺省、不可关闭）
CAPABILITY_ENVELOPE_CLOSED     = true（Reviewer Patch 1：capability envelope 构造期
                                 冻结（capability_envelope 只读快照）；契约
                                 allowed_capabilities 必须与本 envelope **封闭相等**
                                 （子集/超集/未知能力一律 submit 前拒绝，不只证明
                                 "contract 是 backend 声明的子套"）；approval 工具必
                                 须命中构造期封闭 tool→capability 映射（值 ∉ envelope
                                 构造期拒绝）且 capability ∈ 契约 allowed_capabilities，
                                 否则自动 deny——不向用户制造 16D 可扩权审批）
HERMES_CAPABILITY_ISOLATION    = AVAILABLE（Reviewer Patch 2 收紧为**精确封闭** +
                                 Patch 3 **全等闭合**：构造期冻结不可变
                                 expected_profile_tools——**set(tool_capability_map.keys())
                                 == set(expected_profile_tools)**（多映射/少映射/未知
                                 映射/空白/未规范化名字一律构造期拒绝），每个
                                 expected tool 必须有 tool→capability 归属、归属
                                 capability 集与 backend envelope 封闭一致；成功 probe
                                 必须同时满足 capabilities.model ==
                                 expected_profile_identity、toolsets.platform ==
                                 api_server、enabled 工具全部合法非空 str、实际
                                 enabled 集 == expected 集**精确相等**（多/少/未知/
                                 坏类型一律 unhealthy）。源码证据（0.20.6 @4e7eb399）：
                                 run agent 的 enabled_toolsets（api_server.py:3094→
                                 3136 AIAgent kwargs）与 GET /v1/toolsets（:4092-4147，
                                 _get_platform_tools(config,"api_server") +
                                 resolve_toolset 展开具体工具名 + platform:"api_server"
                                 恒定）**同源**读 config.yaml platform_toolsets.
                                 api_server——服务器端权威工具面证据。已知边界如实
                                 登记：POST /v1/runs 无 per-run toolset 参数，run 侧
                                 工具面由服务器 profile 决定——适配器以 probe 精确
                                 快照 + submit 前置新鲜 probe 门 + 审批面**三重封闭**
                                 （tool ∈ probe 快照 ∩ expected ∩ 映射，任一不满足即
                                 fail-closed deny、零 16D 请求）双向封闭，不用自然
                                 语言 instructions 假装隔离）
ACTIVE_HANDSHAKE_VERIFIED      = true（Reviewer Patch 1 扩展：probe = /health +
                                 /v1/capabilities（Bearer + profile 绑定）+
                                 /v1/toolsets（Bearer + 工具面快照）+ 不存在 probe
                                 run 上 status/events GET + approval/stop POST
                                 **四端点无副作用主动握手**（全部必须 404 + 精确
                                 run_not_found）；正/负结果同 TTL 缓存（≤600s 有界）；
                                 认证失败/坏载荷/矛盾广告/端点缺失/形状矛盾/超时/
                                 不可达全部 fail-closed typed reason；probe 全程
                                 零 POST /v1/runs、零真实 run）
AUTH_FAILS_CLOSED              = true（401 → auth_rejected；submit/SSE/approval/
                                 stop/probe 各路径 401 一律类型化失败，零降级）
SIGNED_CONTRACT_REQUIRED       = true（Reviewer Patch 2 重述：submit 唯一输入权威入口 =
                                 16A WorkContract.from_dict exact-schema +
                                 content_hash **完整性摘要**复核——content_hash 只称
                                 integrity hash，绝不称 signature，from_dict 从不重新
                                 计算或背书摘要；缺字段/未知字段/schema marker 不符/
                                 摘要与内容不符 submit 前一律 BackendScopeViolation
                                 拒绝（零 HTTP）；测试合法主路径一律使用真实
                                 WorkContract.to_backend_projection，手写不完整 dict
                                 仅作负例）
AUTHORIZED_CONTRACT_BOUND      = true（Reviewer Patch 2：构造期注入可信 contract
                                 authorizer（callable（contract_id, content_hash）→
                                 bool，缺失/非 callable 构造期拒绝）——submit 前按
                                 id+integrity hash **精确确认**该契约已由组合根授权；
                                 未知 id、hash 不同、authorizer 异常或返回非 True →
                                 submit 前拒绝、零 HTTP；授权真实性不来自 hash 本身）
APPROVAL_OPERATION_EXACT       = true（Reviewer Patch 1：(tool, preview) 有损身份
                                 缓存废除；审批身份唯一权威 = 16D broker 完整身份
                                 原子 get-or-create（contract/hash/run/tool/
                                 capability/scope/risk/policy/operation_digest，
                                 operation digest 由 broker 对**原始完整 args**（帧
                                 全量减传输层字段）现场计算——同 tool 同 preview
                                 不同 command 必然不同 approval_id；相同操作帧幂等
                                 复用；零 str() coercion、零截断参与授权身份；帧时刻
                                 冻结完整操作身份入账本，resolve 边界以此复核；
                                 Patch 3：请求创建收拢到 ApprovalGate 内部——provenance
                                 = "executor"（16D frozen），适配器不再直接调用
                                 broker.get_or_create_request）
APPROVAL_GATE_FOUR_LAYER       = true（Reviewer Patch 3：approval.request 一律经
                                 对应契约 ApprovalGate.check_step 四层判定——完整
                                 WorkContract（submit 账本冻结）∩ 实时
                                 permission_decider 的 PermissionDecision ∩ explicit
                                 approval/grant ∩ backend capability（冻结 envelope）；
                                 risk 下界 L2、wait_for_approval=false；**仅
                                 APPROVAL_PENDING 建立待审批记录**；resolve 时重新
                                 取得实时 PermissionDecision 并再次调用同一
                                 Gate.check_step——GateResult=ALLOW 且携带 permit、
                                 随后**主 broker** 公开 producer API
                                 consume_permit 原子消费成功才 POST once
                                 （Patch 6：最终消费收归主 broker，见
                                 PERMIT_CONSUMED_BY_CONFIGURED_BROKER）；
                                 Gate 任何 DENY/撤销/超时/PM 拒绝或降级/契约 hash
                                 不匹配/permit 消费失败 → deny 绝不 once；
                                 APPROVE_SESSION 仍只收窄转发 once）
PERMISSION_MANAGER_REAL        = true（Reviewer Patch 3：构造期注入 permission_decider
                                 （(tool, capability, raw_args, contract_id, run_id) →
                                 PermissionDecision）——decider 缺失/异常/非
                                 PermissionDecision/granted=false 一律 fail-closed deny，
                                 **绝不手造 PermissionDecision 冒充 PM 结果**（要求 9）；
                                 risk 下界 L2 只作审批必须性的下界，PM 结果仍为
                                 effective 上限（Gate 内 max 语义，调用方不得降级））
PM_RECHECK_AT_REMOTE_BOUNDARY  = true（Reviewer Patch 3：resolve 边界**重新取得实时
                                 PermissionDecision** 并再次调用同一 Gate.check_step
                                 ——approval 后、POST 前 PM 由 allow 变 deny → Gate
                                 DENY_PERMISSION → 零 once；PM 降级同判 deny）
DIRECT_PERMIT_ISSUER_USE       = false（Reviewer Patch 3：Hermes **不再直接持有/
                                 注册/调用 PermitIssuer**——构造参数 permit_issuers、
                                 register_permit_issuer、_permit_at_boundary 全部删除；
                                 permit 签发只存在于 16D ApprovalGate 内部（四层判定
                                 ALLOW 后经内部 issuer 签发）；源码结构 AST 断言锁定
                                 （无 PermitIssuer 名称/issue 调用/create_permit_issuer/
                                 register 路径），零绕过 Gate 直接使用 issuer 的代码路径）
PERMIT_CONSUMED_BY_CONFIGURED_BROKER = true（Reviewer Patch 6：permit **最终消费**
                                 收归构造期注入主 broker——两个真实远端副作用边界
                                 （新操作 grant-covered once / resolve 后 once）
                                 一律经 ``self._broker.consume_permit``（真实
                                 tool/capability/帧时刻冻结 args，仅消费成功才
                                 POST once）；**绝不 ``gate.consume_permit``**——
                                 Gate 恒委托其自身 broker，foreign Gate 会把
                                 permit 消费到 foreign broker 台账（跨 broker
                                 TOCTOU）；foreign permit 即使 grant_id/
                                 approval_id/契约/tool/capability/scope 全同且
                                 主 broker 在证明时刻存在同名有效授权，也因
                                 permit 不在主 broker permit registry 被拒绝、
                                 零 once；授权来源（approval/grant）状态复核与
                                 唯一提交点全部在主 broker 单一消费锁内——绑定
                                 证明与消费之间撤销/超时/已消费均在锁内重查拦截；
                                 不直接使用 PermitIssuer、不触碰任何 16D 私有
                                 字段）
APPROVAL_CAPACITY_ATOMIC       = true（Reviewer Patch 2 + Patch 3：approval 容量检查、
                                 预留、Gate 内请求创建、approval_id 入账构成单锁协调
                                 封闭状态机——len(账本)+在途预留 ≤ cap 恒成立；并发
                                 cap=1 攻击最终索引 ≤1；容量失败**先于** Gate 调用
                                 deny，绝不遗留第二个可用 16D request；每条失败路径
                                 精确归还预留恰一次；Hermes 只收到 fail-closed deny）
APPROVAL_FORWARD_EXACTLY_ONCE  = true（Reviewer Patch 1：同一 approval 顺序重复/
                                 并发 resolve 只有首个调用 POST（先占位守卫）；
                                 其余 typed no-op（forwarded=False）绝不二次 POST；
                                 APPROVE_ONCE/APPROVE_SESSION 收窄转发 "once"，
                                 DENY/TIMEOUT/REVOKED/未决 "deny"，绝不 always/
                                 session；200 成功必须 resolved==1 精确（否则
                                 HermesProtocolError，绝不虚报）；409 仅当错误码精确
                                 approval_not_pending 才视为 typed no-op）
SUBMIT_ATOMIC_IDEMPOTENT       = true（Reviewer Patch 1：contract_id 在 POST 前建立
                                 原子 reservation；两线程并发提交同契约 → 服务器只收
                                 一个 POST、两者获同一 handle；非 202 = 服务器明确
                                 拒绝 → reservation 释放；POST 已发出而结果不确定
                                 （传输异常/202 形状损坏/run_id 冲突 typed conflict）
                                 → reservation 中毒，同 contract 后续 submit 一律
                                 类型化拒绝，绝不自动重提）
RUN_CAPACITY_RESERVED_PRE_POST = true（Reviewer Patch 2：run 账本容量在 POST **前**
                                 原子预留（预留计数与账本同锁，超容窗口不存在）；
                                 容量满 → 零 POST（确定性 pre-POST 拒绝，非中毒）；
                                 预留归还 exactly-once：失败/不确定路径外层统一
                                 归还，成功路径账本锁内归还并保留并发信号量）
RUN_ID_COLLISION_BLOCKED       = true（Reviewer Patch 2：202 返回的 run_id 已属另一
                                 契约 → **不覆盖**（原 owner、槽位计数、事件归属
                                 不变）；本契约 reservation 中毒 + typed conflict
                                 （HermesProtocolError），绝不自动重提）
HANDLE_CORRELATION_BOUND       = true（Reviewer Patch 2：events/stop 校验
                                 handle.correlation == run 账本契约 id——伪造
                                 correlation 的 handle 类型化拒绝且零 HTTP）
FRESH_PROBE_REQUIRED           = true（Reviewer Patch 2：submit 要求最近一次 probe
                                 healthy、未过期且 profile/tool 快照与构造期
                                 expected 精确匹配；未 probe / probe 失败 / probe
                                 过期 → 类型化拒绝、零 POST——submit **不自动补
                                 probe**，新鲜事实由调用方主动建立）
PROFILE_TOOLSET_EXACT          = true（Reviewer Patch 2：见 HERMES_CAPABILITY_
                                 ISOLATION——expected_profile_tools 构造期封闭 +
                                 probe 精确相等比对 + submit 快照复核三层）
MAX_CONCURRENCY_ENFORCED       = true（Reviewer Patch 1：max_concurrent_runs 由
                                 BoundedSemaphore 真实执行——submit 占槽，权威终态
                                 交付时恰一次释放；断线/UNKNOWN 诚实保留槽位；
                                 满槽 fail-closed（reservation 同步释放，不占账本））
LEDGER_CARDINALITY_BOUNDED     = true（Reviewer Patch 1 + Patch 2：contract/run/
                                 approval 三个账本全部硬容量（构造期 1..上限校验）；
                                 满容量 fail-closed 拒绝，绝不淘汰——重放同契约仍
                                 返回既有 handle 且零新 POST（不诱导旧 contract
                                 重新执行）；approval 满容量新请求自动 deny 且不
                                 建立 16D 请求；run 满容量 POST 前预留失败零 POST）
STRICT_MEDIA_TYPE              = true（Reviewer Patch 2 + Patch 3：只接受精确媒体类型
                                 application/json（type/subtype 精确相等，大小写
                                 不敏感；参数仅容 charset=<token>）；
                                 application/jsonp、text/application/json-evil、
                                 非 charset/无值参数一律类型化拒绝；**错误码/诊断
                                 片段 JSON 同样要求精确 application/json**——
                                 text/plain 承载的 run_not_found / approval_not_pending
                                 **绝不**当作已知错误码）
BOUNDED_ERROR_BODY             = true（Reviewer Patch 2 + Patch 3 收紧：全部普通 JSON
                                 响应**流式/有界读取**（> 4 MiB 立即拒绝，超限内容
                                 不入异常）；_error_code_of 复用有界严格 JSON 读取
                                 （错误体 ≤ 64 KiB，超限只留 [error body over limit]
                                 标记；JSON 严格解析，形状损坏 → code=None 不吞掉）；
                                 绝不在检查上限前读取 response.text/json；**读取
                                 中断绝不返回已读前缀**（即使前缀恰好是合法 JSON 也
                                 一律类型化拒绝——TRUNCATED_JSON_REJECTED）；
                                 **单 chunk 在 extend 前检查余量**（绝不先分配超限
                                 内存——CHUNK_PREALLOCATION_BOUNDED）；
                                 超限/中断内容绝不进入异常文本、日志或保留缓冲）
STATUS_RUN_ID_BOUND            = true（Reviewer Patch 1：lifecycle/reconcile 的
                                 status 响应严格封闭——object==hermes.run + run_id
                                 精确相等 + 状态词表校验；缺失/冲突/词表外 →
                                 protocol.error 可观察且**绝不产生终态**，轮询至
                                 预算耗尽按 UNKNOWN 收口；404 特殊语义仅在错误码
                                 精确 run_not_found 时成立，其余 404/409 形状按
                                 协议矛盾处理不吞掉）
JSON_CONTENT_TYPE_BOUNDED      = true（Reviewer Patch 1 + Patch 2 收紧：JSON endpoint
                                 **精确媒体类型** application/json（仅容 charset 参数）
                                 + **流式/有界** body 读取（4 MiB 立即拒绝、超限内容
                                 不入异常）+ JSON object + 2xx 精确 status +
                                 object/run_id/状态词表；text/plain、application/jsonp、
                                 text/application/json-evil、非 charset 参数承载 JSON
                                 一律拒绝；invalid port 等 URL 输入统一折为
                                 HermesConfigurationError；错误文本**先按精确
                                 API key 值脱敏、再做秘密形态脱敏**——服务端裸回显
                                 key 也不得进入异常（实测断言））
SSE_INVALID_UTF8_REJECTED      = true（Reviewer Patch 1：UTF-8 严格解码，非法字节 →
                                 protocol.error sse_invalid_utf8 + fail-closed 断流，
                                 绝不形成业务/终态事件；合法多字节 UTF-8 正路径保留）
SSE_OVERSIZE_SUFFIX_DISCARDED  = true（Reviewer Patch 1：事件 payload 按**原始
                                 UTF-8 bytes** 计数；超限 → protocol.error
                                 sse_event_over_limit + **discard-until-blank**——
                                 同一超限事件后续 data 行绝不重新解释/复活为
                                 terminal，空行后流继续；chunk 内先按行**增量**消费
                                 （一个 chunk 多条合法短行绝不误判单行超限），行
                                 上限只作用于残余不完整 buffer 与完整单行；
                                 line/event/buffer 三级硬上限保持）
SECRETS_LOGGED                 = false（API key 只进 Authorization 头；错误文本
                                 先按值后按形态双重脱敏；16E 信封 payload 秘密键值/
                                 凭证形态 [REDACTED] 实测断言）

STOP_WAITS_FOR_TERMINAL        = true（stop() 200 {"status":"stopping"} ≠ CANCELLED；
                                 CANCELLED 只能来自 Hermes 权威 run.cancelled/
                                 status=cancelled；stop 404 仅在错误码精确
                                 run_not_found 时类型化失败并显式声明"本方法不声明
                                 CANCELLED"，错误码不符 = 协议矛盾）
COMPLETED_MAPS_UNVERIFIED      = true（run.completed → 16E BACKEND_DONE_UNVERIFIED；
                                 测试断言 VERIFIED 全流不可达；16E reducer 对
                                 VB(verified) 的 fail-closed 语义未被触碰）
CLI_EXECUTION_FALLBACK         = false（无 hermes chat/CLI 执行路径）
PROXY_REGISTERED               = false（无 hermes proxy 注册代码路径）
WEBHOOK_RESULT_CHANNEL         = false（webhook 非结果通道）
DIRECT_DIALOGUE_BYPASS         = false（submit 只发送 canonical_user_request 文本；
                                 Persona/SOUL/Memory/预算/验证判据/instructions
                                 一概不出域；final text/streamed text 仅为事件
                                 payload 证据，经 16E 信封，绝不直达对话）

PRODUCTION_FILES_CHANGED       = furina/agent/backend/hermes.py（Reviewer Patch 1
                                 重写 + Patch 2 六组收紧 + Patch 3 三组收紧 +
                                 Patch 5 两组收紧 + Patch 6 一组收紧：permit 最终
                                 消费收归主 broker——新操作 grant-covered once 与
                                 resolve 后 once 两处消费点由 ``gate.consume_permit``
                                 改为 ``self._broker.consume_permit``（构造期注入
                                 主 broker 公开 producer API），跨 broker TOCTOU
                                 封闭）、Gate→ApprovalBroker 绑定证明
                                 完整身份化（approval: claimed 字段独立重算 +
                                 matching_request 全身份查询 + 命中 approval_id
                                 精确相等；grant: covering_grant 全匹配 + 有效
                                 grant_id 精确相等；同名 ID 不同身份 fail-closed、
                                 resolve 边界 once 前补证明；仅公开 API 零 _private
                                 触碰）、_deep_freeze_json 收紧为真正 JSON 值域
                                 （tuple 拒绝不静默转 list）；
                                 16D 四层 Gate 恢复（approval_gates + permission_decider
                                 构造注入；PermitIssuer 直接持有/注册/issue 全部删除；
                                 approval.request 与 resolve 一律经 ApprovalGate.
                                 check_step + 主 broker consume_permit 立即边界
                                 原子消费）、
                                 工具面全等闭合（set(映射键)==set(expected_profile_tools)，
                                 审批面三重封闭）、HTTP 真正有界（读异常抛类型化错误
                                 零前缀、单 chunk extend 前检查余量、错误码 JSON 严格
                                 媒体类型、text/plain 错误码不认）；保留 Patch 1/2
                                 全部边界（expected_profile_tools/contract_authorizer
                                 构造期封闭、submit 新鲜 probe 门、run 账本 POST 前
                                 预留 + run_id 冲突不覆盖、approval 容量封闭状态机、
                                 events/stop correlation 校验、精确媒体类型 + 全端点
                                 流式有界读取）；furina/agent/backend/__init__.py 零
                                 改动）；frozen C1–C7/16A/16B/16D/16E 零改动
TEST_FILES_CHANGED             = tests/agent/integration/test_phase16c_hermes_api_
                                 adapter.py（Reviewer Patch 1 36 项 + Patch 2 12 项
                                 + Patch 3 12 项 + Patch 4 6 项 + Patch 5 5 项
                                 + Patch 6 4 项
                                 = 75 项；Patch 3 既有用例按新构造面
                                 （approval_gates/permission_decider 注入取代
                                 permit_issuers）与 Gate 流程准确升级——approval 专项
                                 全部走 16D Gate 四层判定）+ Final Test Hygiene
                                 Micro-Patch（2026-08-29）：test_74 approve_session
                                 决议证据的审批请求取回由白盒 ``broker._requests``
                                 改为 16D 公开 API（公开 ``operation_digest`` 现场
                                 重算 broker 密钥 HMAC + ``matching_request`` 全身份
                                 查询，断言返回非 None 且 approval_id 精确等于 a2）；
                                 全文件零 ``_requests``/``_grants``/``_known_gate_ids``
                                 或其他私有字段触碰；测试总数不变（75 项）
TARGETED_TESTS                 = 16C 专项 75 passed（本 micro-patch 复跑
                                 75 passed / 0 failed，测试总数不变；Patch 1–5
                                 全量 71 项保持通过 +
                                 Patch 6 新增 4 项：foreign permit 主 broker
                                 permit registry 拒绝（主/foreign broker 完全相同
                                 契约/tool/capability/workspace + UUID 桩同名
                                 grant_id 的有效 grant，foreign Gate 返回 ALLOW +
                                 foreign permit，绑定证明经主 broker 公开查询面
                                 **通过**后仍在主 broker 台账处拒绝，零 once；前置
                                 对照同一 permit 在签发 broker 真实可消费）、证明
                                 与消费之间撤销主 broker grant（主 broker Gate
                                 合法路径，revoke_grant 注入消费入口与真实消费
                                 之间 → 主 broker 锁内状态复核拒绝零 once，
                                 foreign 同名 grant 全程有效不影响结果）、resolve
                                 路径 foreign permit（claimed approval 与主 broker
                                 请求身份完全一致 + 提交 foreign Gate 签发 permit
                                 → 主 broker permit registry 拒绝 boundary_
                                 permit_denied，主 approval 零消费零 once）、
                                 approve_once/approve_session/grant 三条正例恰好
                                 消费一次（主 broker consume_permit 恰一次且
                                 ok=True，Hermes 恰好一个 once））
BACKEND_PERMISSION_REGRESSION  = 16A/16B/16D/16E 四套件 251 passed + tests/agent
                                 全量回归（含 agent tools）407 passed（16C 专项
                                 Patch 5–6 新增 9 项计入；
                                 frozen 16D 公开 API 零改动即完成完整身份绑定证明
                                 （matching_request / covering_grant 公开查询面）
                                 与主 broker 最终消费（consume_permit 公开 producer
                                 API）——未触发 BLOCKED_BY_16D_GATE_BROKER_BINDING_GAP）
COGNITION_SUITE                = 279 passed（0 failed；本 micro-patch 在 BASE
                                 fad0a07 精确一次运行 ``pytest tests/cognition -q``
                                 的真实数量；运行前 ``git status --short
                                 tests/cognition`` 零输出——零未提交修改、零
                                 untracked 测试，数量为 canonical 值；取代本
                                 closeout 早前 patch 基线记录的 285 passed——
                                 tests/cognition 自 Phase 15 D3（b42ed4a）后零
                                 改动，285 为更早基线的过时记录）
FULL_SUITE                     = 1689 passed（0 failed；**该数字来自 Reviewer
                                 Patch 6 生产代码最终全量运行**——本 micro-patch
                                 零生产代码改动，未重跑 full suite，按指令复用
                                 该数字；Patch 6 运行历史：首跑 1688 passed +
                                 1 failed——tests/test_gui_integration.py::
                                 test_gui_timer_advances_runtime 计时型偶发，该
                                 测试与 furina.agent.backend 零导入耦合、隔离运行
                                 通过、复跑全量 0 failed，与 Patch 6 无关；15 条
                                 warning 全部来自既有 tests/test_agent_tools.py
                                 子进程 reader 编码问题，与 Patch 6 无关）
GIT_DIFF_CHECK                 = clean（git diff --check 零输出）
OPTIONAL_LIVE_SMOKE            = NOT_RUN/NOT_REQUIRED（Recon 阶段已对本机
                                 0.20.6 做只读 loopback 实测；本 patch 全部行为由
                                 fake server 按实测协议锁定）
REMAINING_GAPS                 = (1) 实机 approval.request SSE 帧未 live 触发——帧
                                 形状取自 Hermes 源码，适配器解析/16D Gate 转发行为
                                 由 fake server 锁定；(2) run 侧工具面由服务器 profile
                                 配置决定（POST /v1/runs 无 per-run toolset 参数），
                                 适配器以 profile 身份绑定 + /v1/toolsets 快照 +
                                 envelope 封闭相等 + 审批面工具级三重封闭双向封闭；
                                 服务器 profile 本身的 toolset 收敛属部署配置责任，
                                 已在 closeout 登记边界；(3) 非 202 明确拒绝可由
                                 操作方重新尝试，而结果不确定的 submit 永久中毒——
                                 durable 恢复/对账语义归 16H；(4) 断线/UNKNOWN 的
                                 run 诚实保留并发槽位（不淘汰不重复执行），槽位
                                 生命周期终局归 16H；(5) 远端（非 loopback）端点 +
                                 TLS 策略在本 brief 默认面之外，未实现；(6) 契约
                                 Gate 由组合根构造期注入（contract_id → ApprovalGate），
                                 动态新增契约需组合根同步注入对应 Gate，未注入契约
                                 审批一律 fail-closed deny（如实登记的部署边界）。
READY_FOR_REVIEW               = YES（不声明 16C_PASS）
```

## 16C Final Documentation/Test Hygiene Micro-Patch 摘要（BASE fad0a07，2026-08-29）

1. **测试私有字段访问收归 16D 公开 API（唯一代码改动）**：`test_74…positive_paths_
   consume_exactly_once` 中 approve_session 决议证据所需的审批请求对象，由白盒
   `broker._requests[a2].request` 改为 16D 公开查询面取得——帧同源原始 args
   （frame 减 `_NON_OPERATION_FRAME_FIELDS`，与 backend 冻结规则一致）经公开
   `broker.operation_digest(...)` 现场重算 broker 密钥 HMAC，`broker.matching_
   request(...)` 全身份查询（contract_id / contract_hash / run_id / tool /
   capability / requested_scope 经 `AgentRuntime._step_paths` 独立重算 /
   risk_level = max(PM, L2) / policy_kind 取契约公开面），断言返回**非 None** 且
   **approval_id 精确等于 a2**；全测试文件零 `_requests` / `_grants` /
   `_known_gate_ids` 或其他私有字段触碰（grep 断言）。生产代码（hermes.py）零
   改动；测试总数不变（75 项）。
2. **cognition 精确计数入 closeout**：`git status --short tests/cognition` 零输出
   （零未提交修改、零 untracked 测试——状态门通过）；`pytest tests/cognition -q`
   精确一次运行 = **279 passed / 0 failed**（154.66s），写入 COGNITION_SUITE 取代
   早前 patch 基线的 285 记录（tests/cognition 自 Phase 15 D3 后零改动）。
3. **full suite 复用**：未重跑；FULL_SUITE 保留 Patch 6 生产代码最终全量运行
   1689 passed / 0 failed 并注明来源。
4. **范围与边界**：仅改动 tests/agent/integration/test_phase16c_hermes_api_
   adapter.py 与本 closeout 两个文件；`git diff --check` 零输出；不开始 16F、
   不合并 integration、不声明 16C_PASS。

## Reviewer Patch 6 修复摘要（BASE 0684753，2026-08-29）

1. **permit 最终消费收归主 broker（跨 broker TOCTOU 封闭，blocker 一）**：Patch 5
   之后仍存在一个缺口——Gate 绑定证明用主 broker 公开查询面，但最终 permit 消费走
   `gate.consume_permit`，而 Gate 恒把消费委托给**其自身持有的 broker**（16D
   `ApprovalGate.consume_permit` → `self._broker.consume_permit`）：当
   `approval_gates` 中注入的 Gate 绑定 foreign broker 时，permit 会被消费到
   foreign broker 的台账上——绑定证明（主 broker）与最终消费（foreign broker）
   不属于同一 authority，构成跨 broker TOCTOU。本 patch 收紧为：
   - **两个真实远端副作用边界全部改由主 broker 原子消费**：新操作 grant-covered
     once（`_approval_new_operation` grant 路径）与 resolve 后 once
     （`resolve_approval` 边界）的 `gate.consume_permit(...)` 一律改为
     `self._broker.consume_permit(permit, tool=真实 tool, capability=真实
     capability, args=帧时刻冻结 args)`（frozen 16D 公开 producer API）；
   - **职责分界不变**：Gate 仍负责四层 `check_step`、决策、permit mint；主 broker
     负责最终 authority registry（permit 必须在其台账 + gate_id 属其决策面注册
     issuer）、授权来源（approval/grant）状态复核与唯一提交点原子消费——全部在
     主 broker 单一消费锁内完成，"先查询证明、后由另一 broker 消费"的窗口不存在；
   - **foreign permit 一律拒绝**：即使 grant_id/approval_id/契约/tool/capability/
     scope 全同且主 broker 在证明时刻存在同名有效授权，permit 不在主 broker
     台账 → `PermitOutcome(False)` → fail-closed deny 零 once（16D broker 自身
     "permit 非本 broker 签发或字段已被篡改" 判定承担该拒绝）；
   - **不直接使用 PermitIssuer、不触碰任何 16D 私有字段**（消费面 = 主 broker
     公开 `consume_permit`；AST 结构断言保持——无 PermitIssuer 名称/issue/
     create_permit_issuer/register 路径）。
2. **Reviewer-locked 否证（P6 A–D，4 项新增）**：
   - **A（foreign permit 主 broker registry 拒绝）**：主/foreign broker 创建
     完全相同 contract/tool/capability/workspace、UUID 桩同名 grant_id 的有效
     grant；foreign Gate 返回 ALLOW + foreign permit——绑定证明经主 broker
     `covering_grant` **通过**（同名有效授权存在），消费边界真实到达（white-box
     记录 presented permit），仍在主 broker 台账处拒绝（`approval_grant_permit_
     denied`）零 once；前置对照：同一 permit 在其签发 broker 上真实可消费——
     拒绝的唯一原因是 permit 不属于主 broker 台账；主 broker grant 状态零污染；
   - **B（证明与消费之间撤销主 grant）**：主 broker Gate 合法路径 + foreign broker
     同名 grant 全程有效；`revoke_grant` 注入在绑定证明（已通过）与真实消费之间
     → 主 broker 唯一消费锁内 grant 状态复核拒绝，零 once、mint 的 permit 零
     消费；foreign 同名 grant 的有效性不影响结果；
   - **C（resolve 路径 foreign permit）**：claimed approval 与主 broker 请求身份
     完全一致（真实主 broker approval，绑定证明通过），提交的 permit 却是
     foreign Gate 为同一操作经完整决议链签发 → 主 broker permit registry 拒绝
     （`boundary_permit_denied`），主 approval 零消费、零 once；前置对照同一
     foreign permit 在签发 broker 真实可消费；
   - **D（三条正例保持通过）**：主 broker Gate 的 approve_once / approve_session /
     grant 三条路径每条 permit 恰好经主 broker `consume_permit` 消费恰一次且
     ok=True，Hermes 恰好一个 once（approve_session 决议经 canonical USER 证据
     nonce 真实决议链路，决议本身不因转发而改变）。

## Reviewer Patch 5 修复摘要（BASE 7f5dbc8，2026-08-29）

1. **Gate→ApprovalBroker 绑定证明完整身份化（blocker 一）**：Patch 4 的
   `state_of` / `is_grant_active` 只能证明"主 broker 中存在同名 ID 的记录"，不能
   证明 Gate 返回的记录来自主 broker，也不能证明其完整操作身份一致——本 patch
   收紧为：
   - **approval 路径**（`_prove_approval_binding`）：Gate 返回的
     ApprovalRequest 自身字段必须与真实操作完整身份逐维一致
     （contract_id / content_hash / run_id / tool / capability / requested_scope /
     risk / policy——其中 requested_scope 由 `AgentRuntime._step_paths` + broker
     scope 归一化**独立重算**、risk 由 effective = max(PM level, L2) 镜像独立重算、
     policy 取自冻结契约，均不信任 Gate 自报）；随后经主 broker **公开全身份查询
     面** `ApprovalBroker.matching_request`（contract_id / contract_hash / run_id /
     tool / capability / requested_scope / risk_level / policy_kind /
     operation_digest 全部精确过滤）检索，**命中的 approval_id 必须精确等于 Gate
     返回值**。`operation_digest` 是主 broker 随机密钥 HMAC over 原始 args——外部
     broker 的 Gate 无法伪造出能在主 broker 台账命中的 digest，"同名 ID 不同身份"
     （UUID 碰撞 / 换 args / 换 run_id / 换契约 hash）一律不命中 → fail-closed；
   - **grant 路径**（`_prove_grant_binding`）：claimed AuthorizationGrant 的
     contract_id / contract_hash / capability 必须与真实操作一致；随后经主 broker
     **公开查询面** `ApprovalBroker.covering_grant`（激活窗口 + 契约 id/hash 精确
     过滤 + capability 精确 + tool_pattern glob + 全部路径入 workspace + 写目标入
     write_roots）检索，**返回的有效 grant_id 必须精确等于 Gate 返回值**——证明
     失败在 `gate.consume_permit` **之前**拦截（零 permit 消费、零 once）；
   - **fail-closed 后果**：仅 ID 相同但身份不同 → 不进入 adapter approval ledger、
     不消费 permit、不发送 once、原记录不覆盖不串用（账本写入保持 setdefault）；
   - **resolve 边界补同一证明**：`resolve_approval` 的 Gate 重判 ALLOW 后、
     `consume_permit` / POST once 之前，对 `result.approval` / `result.grant`
     再做一次完整身份绑定证明（外部 Gate 在 resolve 时刻的 UUID 碰撞同样在
     consume 之前拦截）；
   - **仅使用 16D 公开 API**（matching_request / covering_grant / ApprovalRequest
     / AuthorizationGrant 公开字段），不触碰任何 `_broker` / `_requests` /
     `_grants` / `_known_gate_ids` 等私有字段——frozen 16D 公开 API 足以表达完整
     证明，**未触发 BLOCKED_BY_16D_GATE_BROKER_BINDING_GAP**。Reviewer-locked
     否证：A（monkeypatch UUID 使主/外部 broker 生成相同 approval_id、操作身份
     不同 → foreign Gate 拒绝零 once，对照完整身份正例通过）；B（相同
     approval_id、相同 tool 但不同 args / run_id / contract hash 逐维均不得通过）；
     C（monkeypatch 相同 grant_id、主 broker 为有效但不同 tool / 绑定另一契约的
     grant → 拒绝，零 permit 消费零 once，对照合法覆盖 grant → once）；D（主
     broker 合法 approval PENDING 建立 + APPROVE_ONCE resolve → 恰好一个 once、
     合法 grant → once 正例保持）。
2. **strict JSON 声明收紧**：`_deep_freeze_json` 只接受真正 JSON 值域（dict /
   list / str / int / float / bool / None）——**tuple 一律 fail-closed 拒绝**
   （JSON 文档不存在 tuple，不得静默转换为 list；帧路径折为
   `approval_args_not_canonical`），顶层 / 嵌套 / dict 键值内出现均拒绝；既有
   dict/list 递归 defensive copy 与零共享嵌套引用保持（JSON 正例不回归）。新增
   tuple 否证（单元级 + 帧路径级零 16D 请求 / 仅 deny 转发 / 等价 list 帧正常
   建立审批）。

## Reviewer Patch 4 修复摘要（BASE 78ab09f，2026-08-28）

1. **决议不得被后出现的 grant 升级（blocker 一）**：`resolve_approval` 先检查原
   approval 的真实 resolution——仅真实 APPROVE_ONCE / APPROVE_SESSION 有资格继续
   执行（实时 PM → 同一 ApprovalGate.check_step → permit consume → once）；
   DENY / TIMEOUT / REVOKED / CANCELLED / LATE / UNKNOWN / CONFLICT / decision=None
   → 固定 choice=deny 且**完全不触碰 Gate**（不签发、不消费 permit、零 once），
   绝不因 resolve 时新出现的 matching session grant 重新变成 ALLOW。否证：DENY /
   TIMEOUT / REVOKED 后创建覆盖同操作的合法 session grant，resolve 仍只能 deny
   （对照组证明 grant 真实激活且对新操作真实放行 grant-covered once）。
2. **approval.request 重投纳入 exactly-once（blocker 二）**：新增完整操作身份
   digest 账本（run_id + tool + capability + 完整原始 args 的严格 canonical JSON
   SHA-256；传输层字段 event/run_id/timestamp 不参与）；相同操作重投复用原
   approval_id——PENDING 复用、APPROVED 未 forward 交唯一 resolve 路径、已 forward
   后零再次 POST once/deny（`_approval_forwarded` 权威不旁路）；Gate 返回 ALLOW 时
   区分来源——`result.approval` 非空属于已有 approval，必须进入统一 exactly-once
   路径（绝不立即 POST），仅 `result.grant` 非空才允许作为新的 grant-covered
   action 立即边界消费。否证：APPROVE_ONCE 后 resolve 前重投最终恰好一个 once；
   resolve 后重投 Hermes POST 数不增加；并发相同操作 in-flight 单飞只产生一个
   approval_id 且零转发 POST。
3. **容量检查保留幂等重投（blocker 三）**：digest 索引查询先于容量检查——账本满时
   已存在的完全相同操作重投复用原 approval_id（不增加账本、不新建 broker request、
   不向 Hermes 发 deny）；只有新的不同操作才 approval_ledger_full + deny；cap=1
   下并发相同操作（账本为空起跑）也只产生一个 approval_id、零容量 deny。
4. **操作身份深度冻结（blocker 四）**：新增 `_deep_freeze_json`（严格递归
   defensive copy，仅 JSON 值域，非 JSON 值/非有限浮点 fail-closed
   `approval_args_not_canonical`；无 repr/default=str 兜底，异常只含路径与类型名）；
   帧进入审批域即冻结，账本快照与交付 BackendEvent 的 payload /
   permission_decider / Gate / permit 消费各持独立副本（零共享嵌套引用）；
   resolve/Gate/permit 始终使用帧时刻冻结的原始操作，替换后的操作是新 approval
   不借用许可；`_ApprovalOpRecord` 恰好一个 `__slots__` 声明（含 digest 字段）。
5. **Gate 绑定构造期 approval_broker（blocker 五）**：16D frozen 公开 API 无构造期
   gate→broker 绑定查询面（`_known_gate_ids` 为 broker 私有，无公开访问器），采用
   **公开 API 行为绑定证明**——Gate 判定结果进入 adapter 审批账本前必须
   `broker.state_of(approval_id)` 可查询（外部 broker 的 approval_id 在本 broker
   不可查询 → ApprovalStateError → fail-closed deny `approval_gate_broker_binding`）；
   grant 路径必须 `broker.is_grant_active(grant_id)` 激活（外部 broker 的 grant →
   fail-closed deny `approval_gate_broker_binding_grant`）；不进账本、不产生 once、
   不触碰任何 Python `_private` 属性；对照组证明本 broker 合法路径不被误伤。
   **未触发 BLOCKED_BY_16D_GATE_BROKER_BINDING_GAP**（公开 API 足以完成 fail-closed
   绑定证明）。
6. **词法与媒体类型收尾（blocker 六）**：approval frame 的 tool 精确匹配（删除
   `strip()` 规范化——`" terminal "` ≠ `"terminal"`，三重封闭用原始词形）；content-
   type charset 参数真正 token 校验（RFC 9110 token 词法；拒绝重复 charset、空值、
   引号、空白、非法参数；且声明值必须是本 adapter 实际践行的 UTF-8——声明其它
   charset 与严格 UTF-8 解码矛盾；`application/json` 与
   `application/json; charset=utf-8`（任意大小写）保持通过）。

## Reviewer Patch 3 修复摘要（BASE 667ffab，2026-08-28）

1. **恢复 16D 四层 Gate（三组 blocker 之首）**：删除 Hermes 对 PermitIssuer 的直接
   持有、注册（`register_permit_issuer`）与 `issue` 调用（构造参数 permit_issuers
   移除；源码结构 AST 断言锁定）；改由构造期注入 `approval_gates: contract_id →
   ApprovalGate` 与 `permission_decider: (tool, capability, raw_args, contract_id,
   run_id) → PermissionDecision`。approval.request 到达时经对应契约
   `ApprovalGate.check_step` 四层判定（完整 WorkContract（submit 账本冻结）+ 真实
   原始 args + **实时** PermissionDecision + 冻结 capability envelope；risk 下界 L2
   ——PM 结果仍为 effective 上限，调用方不得降级；wait_for_approval=false）；
   **仅 APPROVAL_PENDING 建立待审批记录**（approval 账本容量/预留/入账封闭状态机
   保持）。resolve 时**重新取得实时 PermissionDecision 并再次调用同一
   Gate.check_step**——GateResult=ALLOW 且携带 permit、随后 `gate.consume_permit`
   在发送 once 的立即边界原子复核+单点提交成功，才 POST once；Gate 任何 DENY
   （PM 拒绝/降级、契约/hash 不匹配、撤销、超时、已消费）、permit 消费失败 →
   fail-closed deny 绝不 once；APPROVE_SESSION 仍只收窄转发 once。16D
   ApprovalGate/ApprovalBroker/PermitIssuer 及全部 16D 文件**零改动**——未触发
   `BLOCKED_BY_16D_EXTERNAL_GATE_API_GAP`（Gate 公开 API check_step/GateResult/
   consume_permit 完整表达四层流程）。
2. **工具面全等闭合**：构造期强制 `set(tool_capability_map.keys()) ==
   set(expected_profile_tools)`——多映射/少映射/未知映射/空白或未规范化名字全部
   构造期拒绝（Patch 2 的无归属/归属集≠envelope 检查保持）；approval.request 处理
   时再次要求 tool ∈ probe 快照 ∩ expected_profile_tools ∩ tool→capability 映射，
   任一不满足 → 自动 deny、零 16D 请求。
3. **HTTP 真正有界**：`_bounded_body` 读取过程任何异常一律抛类型化 transport 错误
   （**绝不返回已读前缀**——即使前缀恰好是合法 JSON 也不得接受，202 前缀+断流用例
   锁定）；单 chunk 在 `extend` **前**检查余量（`len(chunk) > remaining` 立即拒绝，
   白盒记录 extend 长度断言不先分配超限内存）；普通 JSON 与错误码 JSON **均**要求
   精确 application/json 媒体类型——text/plain 承载的 run_not_found /
   approval_not_pending 绝不当作已知错误码（probe 握手 unhealthy + approval 409
   协议错误用例锁定）；超限/中断内容绝不进入异常文本、日志或保留缓冲。

## Reviewer Patch 2 修复摘要（BASE 9e79fc3，2026-08-28）

0. **审批接口 Recon Gate（先行判定）**：frozen 16D 公开 API 足以表达外部 Hermes
   执行边界——决策面 `broker.create_permit_issuer`（owner 线程）创建的
   `PermitIssuer` 由可信组合根注入本 backend（与 Gate 注入模式同构），producer 面
   `broker.consume_permit` 在发送 once 的立即边界单锁原子复核 + 单点提交。
   **未触发** `BLOCKED_BY_16D_EXTERNAL_ACTION_PERMIT_GAP`；16D/WorkContract/
   C1–C7 零改动。
1. **审批远端边界 permit 化**：`resolve_approval` 顺序由 decision → POST →
   broker.consume（POST 后消费无法封住 ALLOW→远端执行边界之间的撤销窗口）重构为
   decision → **issue + consume_permit 立即边界原子消费** → POST。复核维度 =
   contract_id/content_hash（issuer 内部绑定 + approval 记录双重复核）+ run_id +
   tool + capability + 原始 args（broker HMAC operation digest 对帧时刻冻结的
   op_args 重算）+ approval/grant 状态；消费成功才 POST once，任何失败（含撤销、
   issuer 缺失、hash 绑定不符）→ fail-closed deny 绝不 once；帧时刻冻结完整操作
   身份入 approval 账本，转发时刻零重新解释。
2. **Hermes 工具面封闭**：构造期不可变 `expected_profile_tools`（每个 expected
   tool 必须有 tool→capability 归属、归属 capability 集与 envelope 封闭一致）；
   成功 probe 必须 platform==api_server、enabled 工具全部合法非空 str、实际
   enabled 集 == expected 集**精确相等**（多/少/未知/坏类型 unhealthy）；submit
   要求最近一次 probe healthy、未过期、快照精确匹配——未 probe/失败/过期 →
   零 POST（不自动补 probe）。0.20.6 源码确认 run agent 工具面与 /v1/toolsets
   同源 → 未触发 `HERMES_CAPABILITY_ISOLATION_UNAVAILABLE`。
3. **WorkContract authority**：content_hash 全文只称 integrity hash（完整性
   摘要），绝不称 signature；构造期注入可信 `contract_authorizer`
   （（contract_id, content_hash）→ bool）——未知 id、hash 不同、异常、返回非
   True → submit 前拒绝、零 HTTP。
4. **run 账本原子容量**：容量 POST 前原子预留（预留计数与账本同锁）；满 →
   零 POST；202 返回 run_id 属另一契约 → 不覆盖（原 owner/槽位/事件归属不变），
   本契约 reservation 中毒 + typed conflict；events/stop 校验
   handle.correlation == 契约 id。
5. **approval 账本原子容量**：容量检查→预留→broker 创建→入账封闭状态机
   （len+reserved ≤ cap 恒成立；每条失败路径精确归还预留恰一次）；并发 cap=1
   最终索引 ≤1；容量失败先于 broker 创建 deny，不遗留第二个可用 16D request。
6. **HTTP 严格边界**：精确媒体类型 application/json（仅容 charset=<token>；
   jsonp/json-evil/非 charset 参数拒绝）；全部普通 JSON 响应流式/有界读取
   （4 MiB 立即拒绝、超限内容不入异常）；`_error_code_of` 复用有界严格读取
   （错误体 64 KiB、超限只留标记）。

## Reviewer Patch 1 修复摘要（BASE 82d594d，2026-08-28）

1. **WorkContract 与 profile capability authority**：submit 唯一权威入口 =
   `WorkContract.from_dict`（exact-schema + content_hash 复核，缺字段/未知字段/篡改
   hash/自签扩权 submit 前拒绝）；`expected_profile_identity` 构造期必填并与
   `/v1/capabilities.model` 精确绑定；capability envelope 冻结且与契约
   allowed_capabilities **封闭相等**；`/v1/toolsets` 为 dedicated profile/toolset
   边界的权威服务器端证据（0.20.6 可证明 → 未触发
   `HERMES_CAPABILITY_ISOLATION_UNAVAILABLE`）；审批工具封闭映射 + 自动 deny。
2. **Approval exact operation + exactly once**：有损 `(tool, preview)` 缓存废除；
   完整 canonical 操作身份（broker HMAC operation_digest over 原始全量 args）；同一
   approval 恰好一次转发（顺序/并发均单 POST）；once 成功后真实消费；resolved==1
   精确；409 仅精确 approval_not_pending 为 no-op。
3. **Submit 原子幂等与容量**：POST 前原子 reservation；并发同契约单 POST 同结果；
   结果不确定 → 中毒零重提；max_concurrent_runs 信号量真实执行（终态交付恰一次
   释放）；contract/run/approval 三账本硬容量 fail-closed 不淘汰。
4. **HTTP/status 身份封闭**：content-type/有限 body/精确 status/object/run_id/
   状态词表全封闭；404/409 特殊路径验证真实错误码；invalid port 折为
   HermesConfigurationError；裸 key 值先行脱敏。
5. **SSE parser**：UTF-8 严格解码；max_event_bytes 按原始 bytes；超限
   discard-until-blank（后半段绝不复活为 terminal）；chunk 内按行增量消费；
   line/event/buffer 三级硬上限；身份冲突零业务状态。
6. **Active probe**：不存在 probe run 上 status/events/approval/stop 四端点
   无副作用握手（404 + 精确 run_not_found）；required feature 广告与实际 endpoint
   缺失/认证异常/形状矛盾 → unhealthy；probe 零真实 run。

## Recon 证据摘要（本机实测 + 源码，2026-08-28）

- 安装：`C:\Users\wqx_0\AppData\Local\hermes`（bin/hermes.exe + hermes-agent 源码树，
  install method=git；0.20.6 @4e7eb399）。
- 实测（临时 loopback gateway，临时随机凭证，探测后关闭）：
  - `GET /health`（无认证）→ `{"status":"ok","platform":"hermes-agent","version":"0.20.6"}`；
  - `GET /v1/capabilities` 无认证 401；Bearer 后 object=hermes.api_server.capabilities，
    features.run_submission/run_status/run_events_sse/run_stop/run_steer/
    run_approval_response 全 True；
  - `POST /v1/runs` → 202 `{"run_id":"run_<hex>","status":"started"}`（实测 run.completed
    全流程：output/usage/last_event，SSE message.delta/reasoning.available/
    tool.started/tool.completed 帧 + `: stream closed` 哨兵）；
  - `GET /v1/runs/{id}` 状态记录 queued→running→completed/failed；错误形状
    run_not_found(404)/invalid_approval_choice(400)/approval_not_pending(409) 实测；
  - `POST /v1/runs/{id}/stop` → `{"run_id","status":"stopping"}`，~1s 后权威
    run.cancelled（status + SSE 双确认）——stop ≠ CANCELLED 的直接证据；
  - SSE 传输缓冲单订户/瞬时：断线或终态后再订阅 404 run_not_found → status 轮询是
    唯一 reconcile 路径（_RUN_STREAM_TTL=300s/_RUN_STATUS_TTL=3600s，源码常量）。
- 源码确认（gateway/platforms/api_server.py @4e7eb399；Reviewer Patch 1 补充）：
  - `_resolve_model_name`（:1786）：非 default/custom profile 名进入广告 model——
    "Active profile name (so each profile advertises a distinct model)"，即
    `/v1/capabilities.model` 是 active profile 的身份广告面；
  - `_handle_toolsets`（:4092）：`GET /v1/toolsets` → `{"object":"list",
    "platform":"api_server","data":[{name,label,description,enabled,configured,
    tools:[…]}]}`，docstring 原文 "Returns the toolset surface the api_server
    platform actually exposes to its agent"——run agent 工具面的服务器端权威证据；
  - `_handle_runs`（:7594）：POST /v1/runs 请求体仅 input/instructions/
    previous_response_id/conversation_history/session_id/model——**无 per-run
    toolset/profile 限定参数**（如实登记为部署配置边界）；
  - `_handle_run_events`（:8037）/`_handle_run_approval`（:8089）/
    `_handle_stop_run`（:8238）：不存在 run_id 上分别于状态查索后、任何副作用前
    返回 404 `run_not_found`——probe 四端点无副作用握手依据；
  - 路由封闭集、_check_auth Bearer hmac.compare_digest、approval choice 词表
    once/session/always/deny（适配器只转发 once/deny）、_sweep_orphaned_runs TTL。
- Hermes 更新产生的 config 警告（teams/google_chat 未知 toolset）不属本任务，未修改。

## 冻结边界确认

- C1–C7：零写入、零 schema 依赖（16C 模块无 cognition/persona/memory/db/sqlite/
  subprocess import，测试 #22 源级锁定）。
- 16A/16B/16D/16E frozen contracts：零改动（diff 仅 16C 自有 hermes.py + 16C 测试 +
  本 closeout）。
- 16C 不合并 integration、不开始 16F、不声明 16C_PASS。
