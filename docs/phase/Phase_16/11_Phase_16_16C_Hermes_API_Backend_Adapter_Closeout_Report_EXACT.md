# Phase 16 — 16C Hermes API Backend Adapter
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED — Reviewer Patch 1（6 组 blocker 修复完成 +
                                 全量测试通过，等待外部验收；不声明 16C_PASS）
BASE_SHA                       = 82d594dd7f647484597f702b45723a81adea35e2
                                 （16C 首版 READY_FOR_REVIEW 提交；本 patch 唯一父提交）
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
HERMES_CAPABILITY_ISOLATION    = AVAILABLE（0.20.6 可证明 dedicated profile/toolset
                                 边界：/v1/capabilities.model 绑定 profile 身份 +
                                 /v1/toolsets 广告 run agent 实际工具面（服务器端
                                 权威证据）+ envelope 封闭相等 + 审批面工具级封闭
                                 映射/自动 deny；未触发
                                 HERMES_CAPABILITY_ISOLATION_UNAVAILABLE 停机条件。
                                 已知边界如实登记：POST /v1/runs 无 per-run toolset
                                 参数，run 侧工具面由服务器 profile 配置决定——
                                 适配器以 probe 快照 + 审批面双向封闭，不做自然语言
                                 instructions 假装隔离（submit 只发送
                                 canonical_user_request，无 instructions 字段））
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
SIGNED_CONTRACT_REQUIRED       = true（Reviewer Patch 1：submit 唯一输入权威入口 =
                                 16A WorkContract.from_dict exact-schema +
                                 content_hash 复核（缺字段/未知字段/schema marker
                                 不符/篡改 hash/自签扩权 submit 前一律
                                 BackendScopeViolation 拒绝，零 HTTP）；测试合法
                                 主路径一律使用真实 WorkContract.to_backend_projection，
                                 手写不完整 dict 仅作负例）
APPROVAL_OPERATION_EXACT       = true（Reviewer Patch 1：(tool, preview) 有损身份
                                 缓存废除；审批身份唯一权威 = 16D broker 完整身份
                                 原子 get-or-create（contract/hash/run/tool/
                                 capability/scope/risk/policy/operation_digest，
                                 operation digest 由 broker 对**原始完整 args**（帧
                                 全量减传输层字段）现场计算——同 tool 同 preview
                                 不同 command 必然不同 approval_id；相同操作帧幂等
                                 复用；零 str() coercion、零截断参与授权身份）
APPROVAL_FORWARD_EXACTLY_ONCE  = true（Reviewer Patch 1：同一 approval 顺序重复/
                                 并发 resolve 只有首个调用 POST（先占位守卫）；
                                 其余 typed no-op（forwarded=False）绝不二次 POST；
                                 APPROVE_ONCE/APPROVE_SESSION 收窄转发 "once"，
                                 DENY/TIMEOUT/REVOKED/未决 "deny"，绝不 always/
                                 session；once 转发成功后真实消费 16D approval
                                 （broker.consume）；200 成功必须 resolved==1 精确
                                 （否则 HermesProtocolError，绝不虚报）；409 仅当
                                 错误码精确 approval_not_pending 才视为 typed no-op）
SUBMIT_ATOMIC_IDEMPOTENT       = true（Reviewer Patch 1：contract_id 在 POST 前建立
                                 原子 reservation；两线程并发提交同契约 → 服务器只收
                                 一个 POST、两者获同一 handle；非 202 = 服务器明确
                                 拒绝 → reservation 释放；POST 已发出而结果不确定
                                 （传输异常/202 形状损坏/账本满）→ reservation 中毒，
                                 同 contract 后续 submit 一律类型化拒绝，绝不自动重提）
MAX_CONCURRENCY_ENFORCED       = true（Reviewer Patch 1：max_concurrent_runs 由
                                 BoundedSemaphore 真实执行——submit 占槽，权威终态
                                 交付时恰一次释放；断线/UNKNOWN 诚实保留槽位；
                                 满槽 fail-closed（reservation 同步释放，不占账本））
LEDGER_CARDINALITY_BOUNDED     = true（Reviewer Patch 1：contract/run/approval
                                 三个账本全部硬容量（构造期 1..上限校验）；满容量
                                 fail-closed 拒绝，绝不淘汰——重放同契约仍返回既有
                                 handle 且零新 POST（不诱导旧 contract 重新执行）；
                                 approval 满容量新请求自动 deny 且不建立 16D 请求）
STATUS_RUN_ID_BOUND            = true（Reviewer Patch 1：lifecycle/reconcile 的
                                 status 响应严格封闭——object==hermes.run + run_id
                                 精确相等 + 状态词表校验；缺失/冲突/词表外 →
                                 protocol.error 可观察且**绝不产生终态**，轮询至
                                 预算耗尽按 UNKNOWN 收口；404 特殊语义仅在错误码
                                 精确 run_not_found 时成立，其余 404/409 形状按
                                 协议矛盾处理不吞掉）
JSON_CONTENT_TYPE_BOUNDED      = true（Reviewer Patch 1：JSON endpoint 校验
                                 application/json content-type + body 硬上限
                                 （4 MiB）+ JSON object + 2xx 精确 status +
                                 object/run_id/状态词表；text/plain 承载 JSON 拒绝；
                                 invalid port 等 URL 输入统一折为
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
                                 重写：contract 权威解析 + reservation 幂等账本 +
                                 并发槽位 + 三账本硬容量 + profile/toolsets 双证据
                                 probe + 审批精确身份与 exactly-once + HTTP/SSE
                                 身份封闭 + 新增 HermesConfigurationError 使用面；
                                 furina/agent/backend/__init__.py 零改动）；
                                 frozen 16A/16B/16D/16E 零改动
TEST_FILES_CHANGED             = tests/agent/integration/test_phase16c_hermes_api_
                                 adapter.py（Reviewer Patch 1：36 项 = 既有 23 项按
                                 更严格契约准确升级 + 13 项新增 reviewer 专项；
                                 fake server 扩展 /v1/toolsets、route_override、
                                 submit_delay/drop/raw 面板）
TARGETED_TESTS                 = 16C 专项 36 passed（probe 四端点握手/TTL/profile
                                 绑定/toolsets 快照、fail-closed 矩阵、真实
                                 WorkContract projection 篡改/不完整/越权拒绝、
                                 202 协议形态与幂等 correlation、并发同契约单 POST、
                                 结果不确定零重提、max_concurrent_runs 与三账本硬
                                 容量、SSE 分片/心跳/坏帧/行超限/事件超限
                                 discard-until-blank/非法 UTF-8/重复终态、status
                                 身份封闭零终态、content-type 与精确错误码、裸 key
                                 零泄漏、approval 精确身份/同 preview 异 command
                                 分离/exactly-once/409 精确/resolved==1/自动 deny
                                 扩权拒绝、lying capabilities probe unhealthy、
                                 stop 权威终态、身份精确绑定、loopback/非法端口、
                                 registry/router interop、资源清理、C1–C7 零依赖）
BACKEND_PERMISSION_REGRESSION  = 16A/16B/16D/16E 四套件 251 passed + tests/agent
                                 全量回归 368 passed（16C 专项新增 13 项计入）
COGNITION_SUITE                = 279 passed
FULL_SUITE                     = 1650 passed（0 failed；一次完整运行；15 条
                                 warning 全部来自既有 tests/test_agent_tools.py
                                 子进程 reader 编码问题，与本 patch 无关）
GIT_DIFF_CHECK                 = clean（git diff --check 零输出）
OPTIONAL_LIVE_SMOKE            = NOT_RUN/NOT_REQUIRED（Recon 阶段已对本机
                                 0.20.6 做只读 loopback 实测；本 patch 全部行为由
                                 fake server 按实测协议锁定）
REMAINING_GAPS                 = (1) 实机 approval.request SSE 帧未 live 触发——帧
                                 形状取自 Hermes 源码，适配器解析/16D 转发行为由
                                 fake server 锁定；(2) run 侧工具面由服务器 profile
                                 配置决定（POST /v1/runs 无 per-run toolset 参数），
                                 适配器以 profile 身份绑定 + /v1/toolsets 快照 +
                                 envelope 封闭相等 + 审批面工具级封闭映射双向封闭；
                                 服务器 profile 本身的 toolset 收敛属部署配置责任，
                                 已在 closeout 登记边界；(3) 非 202 明确拒绝可由
                                 操作方重新尝试，而结果不确定的 submit 永久中毒——
                                 durable 恢复/对账语义归 16H；(4) 断线/UNKNOWN 的
                                 run 诚实保留并发槽位（不淘汰不重复执行），槽位
                                 生命周期终局归 16H；(5) 远端（非 loopback）端点 +
                                 TLS 策略在本 brief 默认面之外，未实现。
READY_FOR_REVIEW               = YES（不声明 16C_PASS）
```

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
