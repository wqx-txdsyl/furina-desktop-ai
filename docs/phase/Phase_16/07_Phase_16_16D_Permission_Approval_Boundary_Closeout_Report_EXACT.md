# Phase 16 — 16D Permission & Approval Boundary
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED（Reviewer Patch 2 已落地，等待外部验收；不声明 16D_PASS）
BASE_SHA                       = 541108a3edc1b67b5484bba56410389a58d73d23
                                 （16D Reviewer Patch 1 commit；本轮 Patch 2 以其为基线，
                                 不得集成 master、不得开始 16E）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，沿用 16A/16B 惯例）
BRANCH                         = feature/phase16-16d-permission-approval
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

APPROVAL_MODEL_MODULE          = furina/agent/approval/models.py（ApprovalRequest——审批身份
                                 完整绑定 contract_id+contract_hash+run_id+tool/capability/
                                 requested_scope+risk_level+policy_kind+**operation_digest**
                                 （Patch 2：每 broker 随机密钥 HMAC-SHA256 over 严格 canonical
                                 **原始** args，不保存原文；audit_args_digest 为 redacted
                                 SHA-256 可导出审计摘要，脱敏碰撞故不作操作身份；default=repr
                                 已删除，非 JSON 类型 fail-closed）；args_redacted 递归冻结、
                                 to_audit_dict 防御复制；ApprovalDecisionKind/ResolutionStatus；
                                 AuthorizationGrant——matches 区分 write_paths（read_roots 不
                                 授予写权限）+ 有效窗口 issued_at<=now<expiry；ToolPermit——
                                 绑定 gate_id+contract_id+content_hash+run_id+operation_digest，
                                 有效窗口有界（valid_until-not_before<=MAX_PERMIT_TTL_SECONDS，
                                 超长构造拒绝）；GateSeal——permit 签发凭证（不透明，对象身份
                                 校验）；VerifiedUserEvidence——不再公开自铸（仅文档/测试引用）；
                                 sanitize_text/sanitize_tree/redact_args/deep_freeze/thaw_tree）
APPROVAL_BROKER_MODULE         = furina/agent/approval/broker.py（ApprovalBroker 状态所有者：
                                 create_request/get_or_create_request（单锁原子，身份含
                                 operation_digest）/wait_for_resolution/state_of/consume +
                                 resolve/cancel/revoke + create_grant/revoke_grant/
                                 covering_grant/matching_grants/is_grant_active + sweep_timeouts
                                 + **issue_permit（Patch 2：seal 门控——必须持有构造期注入的
                                 GateSeal，任意 producer 无此凭证；公开 issue 路径删除）+
                                 consume_permit（Patch 2：tool/capability/原始 args 必填、
                                 内部重算 operation digest、单锁原子复核：approve_once 恰好
                                 一次/session 未撤销/grant 在窗/permit 未消费在 TTL）+
                                 permit_state + request_user_evidence（opaque uev_* nonce，
                                 消费时刻**重新查询可信记录**并绑定操作上下文）+
                                 redacted+sanitized+冻结域事件日志（外部 emit 防御复制）；
                                 四层交集判定器在 furina/agent/approval/gate.py）
OWNER_THREAD                   = 构造期唯一绑定（owner_thread_id 构造参数，可信组合根传入；
                                 bind_owner 抢占向量已删除，backend 无法抢占/改绑）；
                                 decision 面（resolve/cancel/revoke/create_grant/revoke_grant/
                                 request_user_evidence）只允许 owner 线程（未绑定/非 owner →
                                 ApprovalStateError）；producer 面（create/get_or_create/wait/
                                 consume/operation_digest/issue_permit(需 seal)/只读）任意线程
PERMISSION_INTERSECTION_LOCKED = true（effective permission = WorkContract scope ∩ PM L0–L3 ∩
                                 explicit approval ∩ backend capability；判定顺序固定：契约 scope
                                 → backend 能力 → PM → 审批；任何层拒绝即零 tool call；risk 以
                                 可信 PM 结果为下界（effective=max(caller,PM.level) 不可降级，
                                 L2/L3 硬性必须审批、无信号 fail-closed）；契约与 grant 双层
                                 write_roots 强制（classify_step_paths 保守，read_roots 不授予
                                 写权限）；session grant 必须严格窄于契约否则 DENY_GRANT_SCOPE）
GATE_CONTRACT_BINDING          = **Patch 2 fix 5**：Gate 构造时绑定可信组合根提供的
                                 expected_contract_id + expected_content_hash；check_step 收到
                                 的契约必须二者一致——**自签但范围更宽的新 WorkContract
                                 （同 id 不同 hash）一律 DENY_CONTRACT_SCOPE**；content_hash
                                 只作 16A 完整性校验（from_dict 全量 exact-mapping+验签，从不
                                 重新签名），**授权真实性来自 expected 绑定**（有否证测试锁定）
PERMIT_MINTING_GATED           = **Patch 2 fix 1**：可消费 permit 只能由持 GateSeal 的四层 Gate
                                 在 ALLOW 后经 broker.issue_permit 签发（对象身份校验，任意
                                 producer 直接调用一律 ApprovalStateError）；无 approval/grant
                                 来源的 permit（免审批路径）同样绑定 gate_id + contract_id +
                                 content_hash + run_id + operation_digest；消费方不得凭 permit
                                 自证（consume_permit 只接受真实 tool/capability/原始 args）
APPROVE_ONCE_EXACTLY_ONCE      = true（approve_once 的消费在工具边界 consume_permit 单锁内
                                 原子标记；同一步重检 → 复用同一请求 → 第二个 permit 消费失败
                                 → 零 tool call；is_consumed 可观测）
TIMEOUT_FAIL_CLOSED            = true（PENDING 且 now ≥ expires_at → TIMED_OUT，每请求恰好一个
                                 终态事件；gate 超时 → DENY_TIMEOUT；观察窗口耗尽 → LATE）
REVOCATION_ENFORCED            = true（revoke/revoke_grant 记 revoked_at；permit 消费在 broker
                                 单锁内与 approval/grant 状态同锁原子复核，撤销/过期/未生效/
                                 消费失败 → 零 tool call，有测试锁定窗口内撤销消费失败）
USER_PROVENANCE_REQUIRED       = true（**Patch 2 fix 4**：approve_session 与 create_grant 必须
                                 携带 canonical USER 证据——本 broker opaque nonce（uev_*）或
                                 原始 event id；**消费时刻重新查询可信记录**并绑定具体操作
                                 上下文（approval_id/contract_id/contract_hash/tool/scope/
                                 decision）；公开 verify_user_evidence 已删除（不得公开自铸）；
                                 手工 VerifiedUserEvidence / 跨 broker nonce / 无关真实事件
                                 （事件真实但属于其它操作）一律拒绝；未配置验证器 fail-closed）
BACKEND_CAN_CREATE_GRANT       = false（gate 审批路径绝不产生 grant；模型层无永久语义字段；
                                 grant 时长有界且拒绝未来签发（issued_at>now）与已过期新 grant
                                 （expiry<=now），有效窗口全路径一致）
ALWAYS_APPROVE_DEFAULT         = false（无全局布尔永久开关；按 approval_policy + risk 下界）
PERMISSION_MANAGER_WEAKENED    = false（PermissionManager 未修改；gate 只要求 granted=True
                                 且绝不以审批覆盖 PM 拒绝）
OPERATION_DIGEST               = **Patch 2 fix 3**：operation digest = 每 broker 随机密钥
                                 HMAC-SHA256 over 严格 canonical 原始 args（不保存原文、不可逆、
                                 不可导出）；不同敏感值（password/token 不同值）产生不同操作
                                 身份，approve_once 不得跨秘密复用（有否证测试）；audit digest
                                 （redacted SHA-256）可导出但脱敏碰撞不作身份；default=repr 删除
AUDIT_IMMUTABLE_AND_SANITIZED  = true（request/event 载荷递归冻结 + 导出防御复制；sanitize_text
                                 统一限长/控制字符清除/秘密脱敏覆盖 reason/detail/scope_note/
                                 事件载荷）

C1_C7_SCHEMA_CHANGED           = false
PRODUCTION_FILES_CHANGED       = 仅 furina/agent/approval/ 包内四个文件（models.py /
                                 broker.py / gate.py / __init__.py）按 Reviewer Patch 2 收紧；
                                 未修改任何其它生产文件（permission.py / agent_runtime.py /
                                 work_contract.py / backend / app.py 等零改动）
TEST_FILES_CHANGED             = 仅 tests/agent/integration/test_phase16d_permission_approval.py
                                 （Patch 1 的 25 项全量适配新 API + Patch 2 新增 3 项否证）
TARGETED_TESTS                 = tests/agent/integration/test_phase16d_permission_approval.py：
                                 28 passed（Patch 1 的 25 项适配 + Patch 2 否证 3 项：
                                 test_patch3b 敏感值不同 → operation digest 不同且 audit 碰撞
                                 属预期 / 非 JSON 类型 fail-closed；test_patch8b 任意 producer
                                 无 seal/错 seal 直接 issue 一律 ApprovalStateError、免审批
                                 permit 绑定 gate+contract+run_id、手工 permit 消费必拒；
                                 test_patch8c consume 缺真实身份 TypeError、换 tool/args/
                                 capability 拒绝、内部重算与 permit 摘要一致；patch8 扩展：
                                 短窗口伪造 / 已知 ID 篡改字段 / 篡改时间窗 / 超长窗口构造
                                 拒绝；patch9 扩展：自签扩权新 WorkContract（同 id 新 hash）
                                 拒绝——锁定 Patch 2 全部 5 项实测反例）
PERMISSION_REGRESSION          = pytest tests/agent tests/test_agent_tools.py
                                 tests/test_skeleton.py：307 passed
                                 （15 warnings 为既有线程 ResourceWarning 类告警，与本阶段
                                 无关）；另跑 16B/16A 专项
                                 tests/agent/integration/test_phase16b_execution_backend.py
                                 test_phase16a_work_contract.py：161 passed
COGNITION_REGRESSION           = pytest tests/cognition：279 passed（Phase 15 cognition/store
                                 契约不变；approval 包零 cognition/sqlite 依赖有专项断言）
FULL_SUITE                     = .venv/Scripts/python.exe -m pytest -q（本轮仅一次）：
                                 1552 passed, 0 failed（230.73s，exit 0）
                                 较 Patch 1 的 1549 恰 +3（Patch 2 否证测试新增）

REMAINING_GAPS                 = 1) 按 brief 无 UI 模态/Hermes(16C)/事件状态机(16E)/
                                   verifier(16F)/持久化 ledger(16H)/C7 commit(16G)/MCP——
                                   全部留待对应子阶段；2) ApprovalGate 尚未接入
                                   NativeAgentRuntimeBackend.submit / App 生产 wiring
                                   （本阶段仅模块 + conformance 测试；生产接线时
                                   user_evidence_verifier 应指向 C6 USER 事件台账查询并绑定
                                   操作上下文、owner_thread_id 指向 canonical USER 决策入口、
                                   GateSeal 由可信组合根创建并分发给 Gate）；3) 事件面为 broker
                                   内建 redacted 域事件日志 + 可选外部 emit 回调，未绑定全局
                                   EventBus 枚举；4) 会话 grant/permit/证据 nonce 为进程内状态，
                                   无持久化（16H 拥有 ledger）；5) 基线已有 untracked
                                   （data/assets_v2/、scripts/assets_v2/、_night_*、nul）
                                   保持未触碰
READY_FOR_REVIEW               = YES
```

No fabricated PASS or test totals. External reviewer owns `16D_PASS`.
