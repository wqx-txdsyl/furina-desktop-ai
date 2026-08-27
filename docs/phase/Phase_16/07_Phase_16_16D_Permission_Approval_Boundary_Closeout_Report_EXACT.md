# Phase 16 — 16D Permission & Approval Boundary
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED（Reviewer Patch 已落地，等待外部验收；不声明 16D_PASS）
BASE_SHA                       = 2706cd1bbefc4b68f841b2f278e1f7e8815e6880
                                 （16D 初版 commit；本 Reviewer Patch 以其为基线，不得合并
                                 master、不得开始 16E）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，沿用 16A/16B 惯例）
BRANCH                         = feature/phase16-16d-permission-approval
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

APPROVAL_MODEL_MODULE          = furina/agent/approval/models.py（ApprovalRequest——审批身份
                                 完整绑定 contract_id+contract_hash+run_id+tool/capability/
                                 requested_scope+risk_level+policy_kind+args_digest（规范化
                                 参数摘要 SHA-256），**不同操作不得复用**；args_redacted
                                 存储递归冻结（MappingProxyType/tuple）、to_audit_dict 导出
                                 深拷贝防御复制；ApprovalDecisionKind / ResolutionStatus 不变；
                                 AuthorizationGrant——matches 区分 write_paths（**read_roots
                                 不授予写权限**）+ 有效窗口 issued_at<=now<expiry；
                                 VerifiedUserEvidence——canonical USER 证据只由 broker 经
                                 可信入口验证器铸造（格式正则仅为必要条件）；ToolPermit/
                                 PermitOutcome——工具边界原子消费凭证（有界 TTL，上限
                                 MAX_PERMIT_TTL_SECONDS=300s）；sanitize_text/sanitize_tree/
                                 redact_args/deep_freeze/thaw_tree——可见文本统一限长+脱敏、
                                 载荷递归不可变与防御复制导出）
APPROVAL_BROKER_MODULE         = furina/agent/approval/broker.py（ApprovalBroker 状态所有者：
                                 create_request/get_or_create_request（**单锁原子
                                 get-or-create**，并发同一步只产生一个请求）/wait_for_resolution
                                 /state_of/consume + resolve/cancel/revoke（decision 面）+
                                 create_grant/revoke_grant/covering_grant/matching_grants +
                                 sweep_timeouts + issue_permit/consume_permit（**单锁原子**
                                 复核+消费：approve_once 恰好一次、session 未撤销、grant
                                 未撤销且在窗、permit 未消费且在 TTL 内、可选身份复核）+
                                 redacted+sanitized+冻结域事件日志（可选外部 emit 防御复制）；
                                 四层交集判定器在 furina/agent/approval/gate.py）
OWNER_THREAD                   = **构造期唯一绑定**（owner_thread_id 构造参数，由可信组合根
                                 传入；bind_owner first-come-first-served 抢占向量已删除，
                                 backend/executor 拿到 broker 引用后无法抢占或改绑 owner）；
                                 decision 面（resolve/cancel/revoke/create_grant/revoke_grant）
                                 只允许 owner 线程（未绑定/非 owner → ApprovalStateError）；
                                 producer 面（create/get_or_create/wait/consume/permit/只读）
                                 任意线程（RLock + Condition 保护）
PERMISSION_INTERSECTION_LOCKED = true（effective permission = WorkContract scope ∩
                                 PermissionManager L0–L3 ∩ explicit approval decision/grant
                                 ∩ backend capability；判定顺序固定：契约 scope → backend
                                 能力 → PM → 审批；任何一层拒绝即零 tool call；**risk 以可信
                                 PM 结果为下界**——effective=max(caller,PM.level) 调用方不可
                                 降级，L2/L3 硬性必须审批（不受 risk_threshold/policy 豁免），
                                 无风险信号 fail-closed 拒绝；契约与 grant 双层 **write_roots
                                 强制**——classify_step_paths 保守把非只读白名单工具的全部
                                 路径按写目标校验，read_roots 不授予写权限；session grant
                                 必须严格窄于契约否则 DENY_GRANT_SCOPE fail-closed）
APPROVE_ONCE_EXACTLY_ONCE      = true（ALLOW 不再即时消费；gate 签发 ToolPermit，
                                 consume_permit 在真实工具边界**单锁原子**标记消费（恰好
                                 一次）；同一步重检 → 复用同一请求 → 第二个 permit 消费
                                 失败 → 零 tool call；is_consumed 可观测）
TIMEOUT_FAIL_CLOSED            = true（PENDING 且 now ≥ expires_at → TIMED_OUT，只从
                                 PENDING 转移 → 每请求**恰好一个** approval.timed_out 终态
                                 事件；gate 超时 → DENY_TIMEOUT 零 tool call；wait_for_
                                 resolution 窗口耗尽无决议 → LATE fail-closed）
REVOCATION_ENFORCED            = true（revoke(审批)/revoke_grant 记 revoked_at；**ALLOW 到
                                 tool.run 之间的撤销 TOCTOU 已封闭**：permit 消费时原子复核
                                 approval/grant 状态，撤销/过期/未生效 → PermitOutcome.ok=False
                                 → 零 tool call，有测试锁定撤销窗口内消费失败）
USER_PROVENANCE_REQUIRED       = true（**approve_session 与 create_grant 必须携带经可信入口
                                 验证的 canonical USER 证据**：user_evidence_verifier 构造注入
                                 （模拟生产 C6 台账查询），VerifiedUserEvidence 只由
                                 broker.verify_user_evidence 铸造；格式正则只是必要条件不是
                                 真实性证明（凑出 lev_<ms>_<hex> 但台账不存在 → 拒绝）；
                                 未配置验证器一律 fail-closed；跨 broker 证据（verified_by
                                 不匹配）拒绝；create_grant 另要求 owner 线程）
BACKEND_CAN_CREATE_GRANT       = false（gate 审批路径绝不产生 grant（list_grants 为空有
                                 测试）；模型层无 permanent/always_allow/approved_forever
                                 字段；grant 时长有界且**拒绝未来签发（issued_at>now）与
                                 已过期新 grant（expiry<=now）**，有效窗口
                                 issued_at<=now<expiry 全路径一致执行）
ALWAYS_APPROVE_DEFAULT         = false（无任何全局布尔永久开关；是否审批按契约
                                 approval_policy.policy_kind 判定 + risk 下界/L2-L3 硬性）
PERMISSION_MANAGER_WEAKENED    = false（PermissionManager 未修改；gate 只要求
                                 pm_decision.granted=True 且绝不以审批覆盖 PM 拒绝）
GATE_CONTRACT_TRUST            = gate 只接受**经 16A 完整 content_hash 校验**的
                                 WorkContract/transport：WorkContract 实例（构造即验签）或
                                 Mapping 投影强制过 WorkContract.from_dict（exact-mapping +
                                 schema marker + content_hash 存在且与内容一致，从不重新
                                 签名）；篡改投影（改 write_roots/删 hash/自由字段）一律
                                 DENY_CONTRACT_SCOPE 零请求零 tool call，有否证测试

C1_C7_SCHEMA_CHANGED           = false
PRODUCTION_FILES_CHANGED       = 仅 furina/agent/approval/ 包内四个文件（models.py /
                                 broker.py / gate.py / __init__.py）按 Reviewer Patch 重写
                                 收紧；未修改任何其它生产文件（permission.py /
                                 agent_runtime.py / work_contract.py / backend / app.py 等
                                 零改动）
TEST_FILES_CHANGED             = 仅 tests/agent/integration/test_phase16d_permission_approval.py
                                 （16 个既有测试适配新 API + 9 项否证测试）
TARGETED_TESTS                 = tests/agent/integration/test_phase16d_permission_approval.py：
                                 25 passed（16 既有全量适配 + Reviewer Patch 9 项否证
                                 test_patch1…test_patch9，逐项锁定实测反例：
                                 P1 调用方 risk 降级无效（L2 硬性审批/阈值 L3 也拦 L2/
                                 无信号 fail-closed）；P2 read root 写入拒绝 + grant
                                 read_roots 不授予写权限 + 只读白名单外工具按写校验；
                                 P3 同 tool 同路径不同参数摘要不得复用审批 + 不同契约
                                 hash 不复用 + 相同操作身份稳定复用；P4 无验证器/
                                 形态合法但台账不存在/跨 broker 证据全部拒绝 + 无
                                 bind_owner（不可抢占）+ 决议事件记录 user_event_id；
                                 P5 8 线程 barrier 并发同一步恰好一个请求一个事件；
                                 P6 未来签发与已过期新 grant 拒绝 + now<issued_at 不激活
                                 + 过期不激活；P7 载荷嵌套冻结（含 list→tuple）+ 导出
                                 防御复制 + reason/detail 限长脱敏；P8 grant/session/
                                 approve_once 三路径撤销 TOCTOU 封闭 + 伪造 permit 拒绝 +
                                 身份复核（args_digest 不匹配拒绝）+ TTL 超窗拒绝；
                                 P9 篡改投影/删 content_hash/自由字段/非契约类型全部
                                 DENY_CONTRACT_SCOPE）
PERMISSION_REGRESSION          = pytest tests/agent tests/test_agent_tools.py
                                 tests/test_skeleton.py：304 passed
                                 （15 warnings 为既有线程 ResourceWarning 类告警，与本
                                 阶段无关）；另跑 16B/16A 专项
                                 tests/agent/integration/test_phase16b_execution_backend.py
                                 test_phase16a_work_contract.py：161 passed
COGNITION_REGRESSION           = pytest tests/cognition：279 passed（Phase 15
                                 cognition/store 契约不变；approval 包零 cognition/sqlite
                                 依赖有专项断言）
FULL_SUITE                     = .venv/Scripts/python.exe -m pytest -q（本轮仅一次）：
                                 1549 passed, 0 failed（202.79s，exit 0）
                                 较 16D 初版 1540 恰 +9（Reviewer Patch 否证测试新增）

REMAINING_GAPS                 = 1) 按 brief 无 UI 模态/Hermes(16C)/事件状态机(16E)/
                                   verifier(16F)/持久化 ledger(16H)/C7 commit(16G)/MCP——
                                   全部留待对应子阶段；2) ApprovalGate 尚未接入
                                   NativeAgentRuntimeBackend.submit / App 生产 wiring
                                   （本阶段仅模块 + conformance 测试；消费接线属后续
                                   子阶段；生产接线时 user_evidence_verifier 应指向 C6
                                   USER 事件台账查询、owner_thread_id 指向 canonical
                                   USER 决策入口线程）；3) 事件面为 broker 内建 redacted
                                   域事件日志 + 可选外部 emit 回调，未绑定全局 EventBus
                                   枚举（生产接线时再映射）；4) 会话 grant/permit 为
                                   进程内状态，无持久化（16H 拥有 ledger）；5) 基线已有
                                   untracked（data/assets_v2/、scripts/assets_v2/、
                                   _night_*、nul）保持未触碰
READY_FOR_REVIEW               = YES
```

No fabricated PASS or test totals. External reviewer owns `16D_PASS`.
