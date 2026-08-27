# Phase 16 — 16D Permission & Approval Boundary
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED（等待外部验收；不声明 16D_PASS）
BASE_SHA                       = 088f3b3d87e9a235c22bc01f09df177847411341
                                 （DOC_FIX_SHA：修正 16B closeout 两处过时说法后的
                                 integration SHA，16D 分支起点）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，沿用 16A/16B 惯例）
BRANCH                         = feature/phase16-16d-permission-approval
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

APPROVAL_MODEL_MODULE          = furina/agent/approval/models.py（ApprovalRequest——
                                 approval_id/contract_id/run_id/tool/capability/
                                 redacted args/requested scope/reason/risk level/
                                 created+expires/provenance；ApprovalDecisionKind——
                                 approve_once/approve_session/deny/timeout/revoked；
                                 ResolutionStatus——resolved/duplicate/conflict/late/
                                 unknown；AuthorizationGrant——强制 canonical USER
                                 provenance（USER_EVENT_ID_PATTERN=lev_<ms>_<hex>）、
                                 精确 capability/规范化 tool pattern、workspace 至少
                                 一根、expiry 有限可撤销；ApprovalEvent + redact_args）
APPROVAL_BROKER_MODULE         = furina/agent/approval/broker.py（ApprovalBroker 状态
                                 所有者：create_request（producer 面）/wait_for_resolution
                                 /state_of/consume + resolve/cancel/revoke（decision 面）+
                                 create_grant/revoke_grant/covering_grant/matching_grants +
                                 sweep_timeouts + redacted 域事件日志（可选外部 emit）；
                                 四层交集判定器在 furina/agent/approval/gate.py
                                 （ApprovalGate/GateVerdict/GateResult））
OWNER_THREAD                   = 显式 bind_owner；decision 面（resolve/cancel/revoke/
                                 create_grant/revoke_grant）只允许 owner 线程（canonical
                                 USER 决策入口，未绑定/非 owner → ApprovalStateError）；
                                 producer 面（create_request/wait_for_resolution/consume/
                                 各只读）任意线程（RLock + Condition 保护）
PERMISSION_INTERSECTION_LOCKED = true（effective permission = WorkContract scope ∩
                                 PermissionManager L0–L3 ∩ explicit approval decision/grant
                                 ∩ backend capability；判定顺序固定：契约 scope → backend
                                 能力 → PM → 审批；任何一层拒绝即零 tool call；审批放行
                                 无法覆盖 PM 拒绝/契约 scope/backend 能力——有测试锁定；
                                 session grant 必须严格窄于契约，否则 DENY_GRANT_SCOPE
                                 fail-closed）
APPROVE_ONCE_EXACTLY_ONCE      = true（resolve(APPROVE_ONCE) 后 gate 消费一次
                                 （consume 标记 consumed_at）；同一步重检 → 复用同一请求
                                 → DENY_ALREADY_CONSUMED，不新建请求、不重复执行；
                                 consume 后 covering 面不再返回该请求）
TIMEOUT_FAIL_CLOSED            = true（PENDING 且 now ≥ expires_at → TIMED_OUT，只从
                                 PENDING 转移 → 每请求**恰好一个** approval.timed_out
                                 终态事件（sweep 不重复）；gate 超时 → DENY_TIMEOUT 零
                                 tool call；wait_for_resolution 窗口耗尽无决议 → LATE
                                 fail-closed；请求窗口有界（default/max approval timeout））
REVOCATION_ENFORCED            = true（revoke(审批)/revoke_grant 记 revoked_at；下一工具
                                 边界前不覆盖：匹配 grant 已撤销/过期 → DENY_GRANT_INACTIVE、
                                 已批准请求被撤销 → DENY_REVOKED；撤销后零新 tool call 有测试）
USER_PROVENANCE_REQUIRED       = true（AuthorizationGrant.user_event_id 必须匹配 canonical
                                 C6 USER 事件 id（lev_<ms>_<hex>）；backend 文本/adapter
                                 默认/inferred intent/LLM 输出一律模型层 ApprovalStateError；
                                 create_grant 另要求 owner 线程）
BACKEND_CAN_CREATE_GRANT       = false（gate 的审批路径（approve_once/session）绝不产生
                                 grant（list_grants 为空有测试）；模型层无 permanent/
                                 always_allow/approved_forever 字段；grant 时长有界
                                 （max_grant_duration_seconds，无永久授权））
ALWAYS_APPROVE_DEFAULT         = false（无任何全局布尔永久开关；是否审批按契约
                                 approval_policy.policy_kind 判定：each_step /
                                 on_risk_level（默认阈值 L2）/ pre_approved_scoped）
PERMISSION_MANAGER_WEAKENED    = false（PermissionManager 未修改；gate 只要求
                                 pm_decision.granted=True 且绝不以审批覆盖 PM 拒绝）

C1_C7_SCHEMA_CHANGED           = false
PRODUCTION_FILES_CHANGED       = 仅新增 furina/agent/approval/ 包（models.py/broker.py/
                                 gate.py/__init__.py）；未修改任何既有生产文件
                                 （permission.py/agent_runtime.py/work_contract.py/
                                 backend/app.py 等零改动）
TEST_FILES_CHANGED             = 仅新增 tests/agent/integration/test_phase16d_permission_approval.py
TARGETED_TESTS                 = tests/agent/integration/test_phase16d_permission_approval.py：
                                 16 passed。任务书 §7 全部 12 项 + 4 项额外锁定：
                                 two-layer invariant 无层扩权 / owner 线程变更守卫 /
                                 approve_session 多次放行+撤销 / wait_for_resolution
                                 类型化返回。要点：L0/L1 语义保留；L2/L3 需既有授权 +
                                 新审批；越契约 inner request 工具执行前拒绝且零请求；
                                 approve_once 恰好消费一次；duplicate/conflict/late 类型化；
                                 超时一个终态事件；grant 必须 canonical USER provenance；
                                 grant scope/expiry/revocation 强制；backend 无法合成
                                 permanent grant；等待中取消解阻且零 tool call；秘密参数
                                 在审计/事件载荷中全部 [REDACTED]
PERMISSION_REGRESSION          = pytest tests/agent tests/test_agent_tools.py
                                 tests/test_skeleton.py：295 passed
                                 （15 warnings 为既有线程 ResourceWarning 类告警，与本
                                 阶段无关）；另跑 16B/16A 专项
                                 tests/agent/integration/test_phase16b_execution_backend.py
                                 test_phase16a_work_contract.py：161 passed
COGNITION_REGRESSION           = pytest tests/cognition：279 passed（Phase 15
                                 cognition/store 契约不变——任务书 §7.12；approval 包
                                 零 cognition/sqlite 依赖有专项断言）
FULL_SUITE                     = .venv/Scripts/python.exe -m pytest -q（本轮仅一次）：
                                 1540 passed, 0 failed（209.52s，exit 0）
                                 较 16B 1524 恰 +16（16D 专项新增）

REMAINING_GAPS                 = 1) 按 brief 无 UI 模态/Hermes(16C)/事件状态机(16E)/
                                   verifier(16F)/持久化 ledger(16H)/C7 commit(16G)/MCP——
                                   全部留待对应子阶段；2) ApprovalGate 尚未接入
                                   NativeAgentRuntimeBackend.submit / App 生产 wiring
                                   （本阶段仅模块 + conformance 测试；消费接线属后续
                                   子阶段）；3) 事件面为 broker 内建 redacted 域事件
                                   日志 + 可选外部 emit 回调，未绑定全局 EventBus 枚举
                                   （生产接线时再映射）；4) 会话 grant 为进程内状态，
                                   无持久化（16H 拥有 ledger）；5) 基线已有 untracked
                                   （data/assets_v2/、scripts/assets_v2/、_night_*、
                                   nul）保持未触碰
READY_FOR_REVIEW               = YES
```

No fabricated PASS or test totals. External reviewer owns `16D_PASS`.
