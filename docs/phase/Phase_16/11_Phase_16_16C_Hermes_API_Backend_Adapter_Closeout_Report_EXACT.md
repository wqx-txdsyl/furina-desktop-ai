# Phase 16 — 16C Hermes API Backend Adapter
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED（实现 + 全量测试通过，等待外部验收；
                                 不声明 16C_PASS）
BASE_SHA                       = 90c3a14a5cb44e17189b47761b876d0c5980a00e
                                 （feature/phase16-work-sovereignty ff-only 集成
                                 ACCEPTED_16E_SHA 之后的集成基线 = 16C_BASE_SHA）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，
                                 沿用 16A/16B/16D/16E 惯例）
BRANCH                         = feature/phase16-16c-hermes-api-adapter
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

HERMES_VERSION_PROBED          = 0.20.6（2026.8.27，upstream 4e7eb399，
                                 Python 3.11.16，install=git；任务中途由 0.20.5
                                 升级，Recon 全部按更新后源码 + localhost 实测重做）
API_SERVER_PRIMARY             = hermes-agent/gateway/platforms/api_server.py
                                 （aiohttp；默认 loopback 127.0.0.1:8642；
                                 API_SERVER_KEY Bearer；API_SERVER_ENABLED 由
                                 ≥16 字符 key 自动使能）
RUNS_SURFACE_AVAILABLE         = true（POST /v1/runs → 202 {"run_id","status":
                                 "started"}；GET /v1/runs/{id} → hermes.run 状态
                                 记录；GET /v1/runs/{id}/events → SSE data 帧 +
                                 : keepalive 心跳 + : stream closed 哨兵；
                                 POST …/approval；POST …/stop → stopping ——
                                 全部本机实测 + 源码双重确认）
CAPABILITIES_ADVERTISED        = true（features.run_submission / run_status /
                                 run_events_sse / run_stop / run_approval_response
                                 实测全 True）
ACTIVE_HANDSHAKE_VERIFIED      = true（probe = /health + /v1/capabilities（Bearer）
                                 + runs 面 404 run_not_found 三段主动握手；
                                 正/负结果同 TTL 缓存（≤600s 有界）；认证失败/
                                 坏载荷/矛盾广告/超时/不可达全部 fail-closed
                                 typed reason）
AUTH_FAILS_CLOSED              = true（401 → auth_rejected；submit/SSE/approval/
                                 stop 各路径 401 一律类型化失败，零降级）
SSE_RECONNECT_RECONCILES       = true（SSE 断线/404 → 权威 status 轮询 reconcile
                                 至终态；reconcile 预算有界；终态记录被清扫
                                 （404）→ transport.disconnected → 16E UNKNOWN，
                                 绝不臆造终态；全程零重复 submit —— POST /v1/runs
                                 仅发生在 submit()，且按 contract_id 幂等账本去重）
APPROVAL_FORWARDED_TO_16D      = true（SSE approval.request → broker.
                                 get_or_create_request（producer 公开面），
                                 approval_id 绑定进 16E 事件 payload；决议只消费
                                 broker.wait_for_resolution 的真实 Furina 决议；
                                 APPROVE_ONCE/APPROVE_SESSION 一律收窄转发 "once"，
                                 DENY/TIMEOUT/REVOKED/未决一律 "deny"；
                                 绝不发送 always/session；不伪造 USER evidence/
                                 grant/permit，不触碰 broker private 字段；
                                 decision 面锁定的 broker 永远等不到决议 → deny）
STOP_WAITS_FOR_TERMINAL        = true（stop() 200 {"status":"stopping"} ≠ CANCELLED；
                                 CANCELLED 只能来自 Hermes 权威 run.cancelled/
                                 status=cancelled；stop 404 类型化失败并显式声明
                                 "本方法不声明 CANCELLED"）
COMPLETED_MAPS_UNVERIFIED      = true（run.completed → 16E BACKEND_DONE_UNVERIFIED；
                                 测试断言 VERIFIED 全流不可达；16E reducer 对
                                 VB(verified) 的 fail-closed 语义未被触碰）
CLI_EXECUTION_FALLBACK         = false（无 hermes chat/CLI 执行路径）
PROXY_REGISTERED               = false（无 hermes proxy 注册代码路径）
WEBHOOK_RESULT_CHANNEL         = false（webhook 非结果通道）
DIRECT_DIALOGUE_BYPASS         = false（submit 只发送 canonical_user_request 文本；
                                 Persona/SOUL/Memory/预算/验证判据一概不出域；
                                 final text/streamed text 仅为事件 payload 证据，
                                 经 16E 信封，绝不直达对话）
SECRETS_LOGGED                 = false（API key 只进 Authorization 头；错误文本过
                                 本地脱敏；16E 信封 payload 秘密键值/凭证形态
                                 [REDACTED] 实测断言）

PRODUCTION_FILES_CHANGED       = furina/agent/backend/hermes.py（新增，
                                 HermesExecutionBackend + HermesEndpoint + 3 个
                                 typed 错误）；furina/agent/backend/__init__.py
                                 （仅必要导出 +4；frozen 16A/16B/16D/16E 零改动）
TEST_FILES_CHANGED             = tests/agent/integration/test_phase16c_hermes_api_
                                 adapter.py（新增，23 项；确定性 fake HTTP/SSE
                                 server 按实测协议形状承载全部行为锁定）
TARGETED_TESTS                 = 16C 专项 23 passed（probe 握手/TTL、fail-closed
                                 矩阵、202 协议形态、幂等 correlation、SSE 分片/
                                 心跳/坏帧/超限/重复终态、断线 reconcile 与 UNKNOWN
                                 边界、stop 权威终态、approval resolve/deny/timeout/
                                 不可自批、秘密零泄漏、端点封闭集、身份精确绑定、
                                 loopback/URL 纪律、registry/router interop、
                                 资源清理、C1–C7 零依赖）
BACKEND_PERMISSION_REGRESSION  = 16A/16B/16D/16E 四套件 251 passed + tests/agent
                                 全量回归 355 passed
COGNITION_SUITE                = 279 passed
FULL_SUITE                     = 1637 passed（0 failed；一次完整运行）
OPTIONAL_LIVE_SMOKE            = NOT_RUN/NOT_REQUIRED（Recon 阶段已对本机
                                 0.20.6 做只读 loopback 实测：/health、
                                 /v1/capabilities、submit 202、status、SSE 全帧
                                 词表、stop→stopping→cancelled、approval 409/400
                                 错误形状；临时 gateway 以临时随机凭证启动、探测
                                 后关闭，凭证未入任何报告/提交）
REMAINING_GAPS                 = (1) 实机 approval.request SSE 帧未 live 触发——本机
                                 Hermes 终端工具对良性命令自动放行、危险命令不可
                                 用于探测；帧形状取自 Hermes 源码（_approval_notify/
                                 _handle_run_approval），适配器解析/16D 转发行为由
                                 fake server 按实测协议锁定；(2) 适配器诚实声明
                                 workspace_scoped=False：携带路径 scope 的契约由
                                 router 机制性拒绝（hermes:workspace_incompatible），
                                 Hermes 侧工具集 ↔ Furina capability 映射仅由构造方
                                 显式声明，无自动发现；(3) 超过 reconcile 预算的
                                 超长断线按 UNKNOWN 收口，durable 恢复/幂等语义
                                 归 16H；(4) 远端（非 loopback）端点 + TLS 策略在
                                 本 brief 默认面之外，未实现。
READY_FOR_REVIEW               = YES
```

## Recon 证据摘要（本机实测 + 源码，2026-08-28）

- 安装：`C:\Users\wqx_0\AppData\Local\hermes`（bin/hermes.exe + hermes-agent 源码树，
  install method=git）。
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
- 源码确认（gateway/platforms/api_server.py @4e7eb399）：路由封闭集、_check_auth
  Bearer hmac.compare_digest、approval choice 词表 once/session/always/deny（适配器
  只转发 once/deny）、_sweep_orphaned_runs TTL。
- Hermes 更新产生的 config 警告（teams/google_chat 未知 toolset）不属本任务，未修改。

## 冻结边界确认

- C1–C7：零写入、零 schema 依赖（16C 模块无 cognition/persona/memory/db/sqlite/
  subprocess import，测试 #22 源级锁定）。
- 16A/16B/16D/16E frozen contracts：零改动（diff 仅 16C 自有新文件 + backend 包
  __init__ 导出 4 行）。
- 16C 不合并 integration、不开始 16F、不声明 16C_PASS。
