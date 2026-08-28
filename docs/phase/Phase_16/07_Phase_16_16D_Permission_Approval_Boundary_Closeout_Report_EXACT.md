# Phase 16 — 16D Permission & Approval Boundary
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED（Reviewer Patch 4 已落地，等待外部验收；不声明 16D_PASS）
BASE_SHA                       = 2b1270ba7bca4719ad12633b7daff815d0b97558
                                 （16D Reviewer Patch 3 commit；本轮 Patch 4 以其为基线，
                                 不得集成 master、不得开始 16E）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，沿用 16A/16B 惯例）
BRANCH                         = feature/phase16-16d-permission-approval
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

APPROVAL_MODEL_MODULE          = furina/agent/approval/models.py（ApprovalRequest——审批身份
                                 完整绑定 contract_id+contract_hash+run_id+tool/capability/
                                 requested_scope+risk_level+policy_kind+**operation_digest**
                                 （每 broker 随机密钥 HMAC-SHA256 over 严格 canonical
                                 **原始** args，不保存原文；audit_args_digest 为 redacted
                                 SHA-256 可导出审计摘要，脱敏碰撞故不作操作身份）；
                                 args_redacted 递归冻结、to_audit_dict 防御复制；
                                 ApprovalDecisionKind/ResolutionStatus；
                                 AuthorizationGrant——**Patch 3：必填绑定 contract_id+
                                 contract_hash**（create/list/match/cover/permit 全链携带，
                                 Contract A 的 grant 绝不覆盖 Contract B，同 id 不同
                                 hash 换约同样不覆盖）+ matches 区分 write_paths
                                 （read_roots 不授予写权限）+ 有效窗口
                                 issued_at<=now<expiry；ToolPermit——绑定 gate_id+
                                 contract_id+content_hash+run_id+operation_digest，有效
                                 窗口有界，**授权来源互斥（Patch 3：免审批/approval/
                                 grant 三者之一，approval_id+grant_id 同时非空构造拒绝）**；
                                 **EvidenceContext（Patch 3）——严格不可变 typed USER
                                 证据上下文（exact-equality 身份）**：grant 侧绑定
                                 decision/contract_id/hash/capability/tool_pattern/
                                 workspace/issued_at/expiry/scope_note，approve_session
                                 侧绑定完整 ApprovalRequest 身份；VerifiedUserEvidence
                                 ——不再公开自铸（仅文档/测试引用）；
                                 sanitize_text/sanitize_tree/redact_args/deep_freeze/
                                 thaw_tree。**GateSeal 已删除（Patch 3）**
APPROVAL_BROKER_MODULE         = furina/agent/approval/broker.py（ApprovalBroker 状态所有者：
                                 create_request/get_or_create_request（单锁原子，身份含
                                 operation_digest）/wait_for_resolution/state_of/consume +
                                 resolve/cancel/revoke + create_grant（必填 contract 绑定）/
                                 revoke_grant/covering_grant/matching_grants（契约精确
                                 过滤）/is_grant_active + sweep_timeouts +
                                 **consume_permit（Patch 3：单锁内先完成全部校验——
                                 台账+gate_id 注册表+窗口+身份+来源互斥+approval/grant
                                 状态——最后单点提交 consumed 状态，任何失败零状态变更；
                                 **Patch 4：来源精确绑定**——仅"存在且有效"不足以免责：
                                 approval 来源要求 contract_id/hash、run_id、tool、
                                 capability、operation_digest 全部相等且由**真实
                                 tool+args** 确定的 requested_scope 与审批放行 scope
                                 相等；grant 来源要求 contract 绑定一致且
                                 ``grant.matches``（capability 精确/tool_pattern glob/
                                 workspace/写目标必须落入 grant.write_roots）对真实操作
                                 成立——issuer 把不匹配操作绑定到合法 approval_id/
                                 grant_id 时消费必拒且 approval/grant/permit 零状态变更）**
                                 + permit_state + request_user_evidence（typed
                                 EvidenceContext；**Patch 4：event→context→nonce 原子
                                 状态**——同 event+同 context 未消费重复请求幂等复用
                                 nonce、同 event+不同 context 拒绝、已消费/超窗/验证
                                 失败后事件锁定；nonce 取出即销毁+有界生命周期）+
                                 **create_permit_issuer（Patch 3：decision 面/owner 线程
                                 专属）** + redacted+sanitized+冻结域事件日志（外部 emit
                                 防御复制）；**PermitIssuer（Patch 3）——permit 签发器：
                                 内部绑定唯一 gate_id + expected contract_id/content_hash，
                                 只能经 create_permit_issuer（owner 线程）创建并注入
                                 Gate；公开 issue_permit/GateSeal 已删除**；四层交集
                                 判定器在 furina/agent/approval/gate.py（Patch 4 零改动——
                                 Blocker 1 的消费侧复核在 broker.consume_permit，Blocker 2
                                 的 nonce 生命周期在 broker））
OWNER_THREAD                   = 构造期唯一绑定（owner_thread_id 构造参数，可信组合根传入；
                                 bind_owner 抢占向量已删除，backend 无法抢占/改绑）；
                                 decision 面（resolve/cancel/revoke/create_grant/revoke_grant/
                                 request_user_evidence/**create_permit_issuer**）只允许
                                 owner 线程（未绑定/非 owner → ApprovalStateError）；
                                 producer 面（create/get_or_create/wait/consume/
                                 operation_digest/consume_permit/只读）任意线程，
                                 **零 permit 签发能力**
PERMISSION_INTERSECTION_LOCKED = true（effective permission = WorkContract scope ∩ PM L0–L3 ∩
                                 explicit approval ∩ backend capability；判定顺序固定：契约 scope
                                 → backend 能力 → PM → 审批；任何层拒绝即零 tool call；risk 以
                                 可信 PM 结果为下界（effective=max(caller,PM.level) 不可降级，
                                 L2/L3 硬性必须审批、无信号 fail-closed）；契约与 grant 双层
                                 write_roots 强制（classify_step_paths 保守，read_roots 不授予
                                 写权限）；session grant 必须严格窄于契约否则 DENY_GRANT_SCOPE）
GATE_CONTRACT_BINDING          = Gate 的 expected_contract_id + expected_content_hash 来自
                                 其持有的 PermitIssuer（Patch 3：issuer 内部绑定唯一
                                 gate_id + expected 契约，单一事实来源；broker 决策面
                                 create_permit_issuer 创建）；check_step 收到的契约必须
                                 二者一致——**自签但范围更宽的新 WorkContract（同 id 不同
                                 hash）一律 DENY_CONTRACT_SCOPE**；content_hash 只作 16A
                                 完整性校验（from_dict 全量 exact-mapping+验签，从不重新
                                 签名），**授权真实性来自 expected 绑定**（有否证测试锁定）
PERMIT_MINTING_GATED           = **Patch 3 fix 1（issuer/consumer API 重拆）**：公开
                                 GateSeal 与 broker.issue_permit **已删除**——不再以
                                 broker/gate 普通属性中的 seal 对象作为权限边界，
                                 亦不声明 Python _private 属性是安全隔离。permit 签发
                                 能力只存在于 PermitIssuer 对象：内部绑定唯一 gate_id +
                                 expected contract_id/content_hash（issue() 不接受调用方
                                 自报 gate/契约字段），只能由 broker 决策面
                                 create_permit_issuer（owner 线程）创建并由可信组合根
                                 注入 Gate；producer/runtime 可见对象（broker/gate 公开
                                 API）零签发能力（producer 线程调用 create_permit_issuer
                                 → ApprovalStateError，有否证测试）。可消费 permit 只能
                                 由四层 Gate 在 ALLOW 后经内部 issuer 签发（免审批路径
                                 同样绑定 gate_id+contract_id+content_hash+run_id+
                                 operation_digest）；消费侧三重复核：broker 台账 +
                                 gate_id 决策面注册表 + 字段/身份校验——伪造/篡改/
                                 跨 broker/绕过 Gate 的 permit 消费必拒（有否证测试）；
                                 **Patch 4（来源精确绑定）**：消费侧第四重——授权来源
                                 与真实操作逐维比对（approval 全身份维度 + grant.matches
                                 覆盖真实 tool/路径），不匹配即拒绝（有否证测试
                                 test_patch4a 锁定）
APPROVE_ONCE_EXACTLY_ONCE      = true（approve_once 的消费标记只在 consume_permit 单锁内
                                 **全部校验通过后的唯一提交点**原子写入；同一步重检 →
                                 复用同一请求 → 第二个 permit 消费失败 → 零 tool call；
                                 任何校验失败（含最后一步）不改变 approval/grant/permit
                                 任何状态，有否证测试锁定）
TIMEOUT_FAIL_CLOSED            = true（PENDING 且 now ≥ expires_at → TIMED_OUT，每请求恰好一个
                                 终态事件；gate 超时 → DENY_TIMEOUT；观察窗口耗尽 → LATE）
REVOCATION_ENFORCED            = true（revoke/revoke_grant 记 revoked_at；permit 消费在 broker
                                 单锁内与 approval/grant 状态同锁原子复核，撤销/过期/未生效/
                                 消费失败 → 零 tool call 且零状态变更，有测试锁定窗口内撤销
                                 消费失败）
USER_PROVENANCE_REQUIRED       = true（**Patch 3 fix 3：typed EvidenceContext exact-equality**：
                                 approve_session 与 create_grant 必须携带 canonical USER
                                 证据；**Patch 4：只接受本 broker 签发的 opaque nonce
                                 （uev_*）——原始 lev_* 事件 id 不得绕过 nonce 生命周期
                                 直接消费**；消费时刻从**真实操作记录**派生 expected typed
                                 context（grant：decision/contract_id/hash/capability/
                                 tool_pattern/workspace/issued_at/expiry/scope_note；
                                 approve_session：完整 ApprovalRequest 身份含
                                 operation_digest），要求 stored context 与 expected
                                 **完全相等**（禁止忽略 stored context；capability/expiry/
                                 workspace/scope_note/操作身份任一变化即拒绝）并**重新查询
                                 可信记录**；nonce **取出即销毁（一次性）+
                                 MAX_EVIDENCE_NONCE_TTL_SECONDS 有界生命周期**，跨
                                 context/重复/超窗重放一律拒绝；**Patch 4：event→context→
                                 nonce 原子状态**——每个 canonical USER decision event 只能
                                 绑定一个 EvidenceContext 与一次授权结果：同 event+同 context
                                 未消费重复请求幂等（复用 nonce）、同 event+不同 context 拒绝、
                                 已消费/超窗/验证失败后事件锁定（不得再次创建新 nonce 或新
                                 grant，grant 撤销后同一旧 event 亦不得重建替代授权，有否证
                                 测试 test_patch4b/4c 锁定）；**事件锁定语义（精确）**：
                                 成功预绑定后，消费重查失败、超时或完成消费会锁定 event；
                                 首次预验证拒绝不建立 binding，因此不声明其已被锁定；公开
                                 verify_user_evidence 已
                                 删除；手工 VerifiedUserEvidence / 跨 broker nonce / 无关
                                 真实事件一律拒绝；未配置验证器 fail-closed；**测试 verifier
                                 逐字段比较完整 EvidenceContext payload（不得只检查
                                 contract_id/tool/capability）**；**不同 approval operation
                                 使用不同 canonical event id**
BACKEND_CAN_CREATE_GRANT       = false（gate 审批路径绝不产生 grant；模型层无永久语义字段；
                                 grant 时长有界且拒绝未来签发（issued_at>now）与已过期新 grant
                                 （expiry<=now），有效窗口全路径一致）
ALWAYS_APPROVE_DEFAULT         = false（无全局布尔永久开关；按 approval_policy + risk 下界）
PERMISSION_MANAGER_WEAKENED    = false（PermissionManager 未修改；gate 只要求 granted=True
                                 且绝不以审批覆盖 PM 拒绝）
OPERATION_DIGEST               = operation digest = 每 broker 随机密钥 HMAC-SHA256 over
                                 严格 canonical 原始 args（不保存原文、不可逆、不可导出）；
                                 不同敏感值（password/token 不同值）产生不同操作身份，
                                 approve_once 不得跨秘密复用（有否证测试）；audit digest
                                 （redacted SHA-256）可导出但脱敏碰撞不作身份；default=repr
                                 已删除
AUDIT_IMMUTABLE_AND_SANITIZED  = true（request/event 载荷递归冻结 + 导出防御复制；sanitize_text
                                 统一限长/控制字符清除/秘密脱敏覆盖 reason/detail/scope_note/
                                 事件载荷）

C1_C7_SCHEMA_CHANGED           = false
PRODUCTION_FILES_CHANGED       = 仅 furina/agent/approval/ 包内三个文件（broker.py /
                                 models.py / __init__.py）按 Reviewer Patch 4 收紧；
                                 gate.py 零改动（Blocker 1 的消费侧来源复核在
                                 broker.consume_permit、Blocker 2 的 nonce 生命周期在
                                 broker）；未修改任何其它生产文件（permission.py /
                                 agent_runtime.py / work_contract.py / backend / app.py
                                 等零改动）
TEST_FILES_CHANGED             = 仅 tests/agent/integration/test_phase16d_permission_approval.py
                                 （既有测试适配 Patch 4 nonce-only + 全 payload verifier +
                                 Patch 4 新增否证测试）
TARGETED_TESTS                 = tests/agent/integration/test_phase16d_permission_approval.py：
                                 37 passed（较 Patch 3 的 34 +3 = Patch 4 否证测试新增；
                                 既有 34 项全部适配 nonce-only 流程与完整 payload verifier）。
                                 Patch 4 reviewer-locked 否证：
                                 test_patch4a——permit 来源精确绑定：issuer 把不匹配操作
                                 绑定到合法 approval_id/grant_id 时消费必拒且零状态变更
                                 （write 审批不得授权不同 tool；approval 不得跨 run_id/
                                 args/scope；grant 不得授权 pattern 外 tool / workspace
                                 外路径 / capability 外操作；失败后 approve_once/permit
                                 均未消费；合法来源消费成功）；
                                 test_patch4b——canonical USER 事件生命周期：原始 lev_*
                                 event id 不得绕过 nonce 直接消费；同 event+同 context
                                 未消费重复请求幂等（复用 nonce）、同 event+不同 context
                                 拒绝；同 event 创建 grant 后再次创建拒绝；grant 撤销后
                                 同 event 重建拒绝；验证失败/超窗后事件锁定（不得再次
                                 创建新 nonce 或新 grant）；
                                 test_patch4c——同 event 为两个不同 approve_session
                                 request 授权拒绝；不同 approval operation 使用不同
                                 canonical event id（合法双会话各自独立事件通过）。
                                 既有否证（Patch 1/2/3）全数保留：risk 不可降级 / 双层
                                 write_roots / 审批身份完整绑定 / get-or-create 原子 /
                                 grant 时间窗 / 载荷不可变 / permit 封闭撤销 TOCTOU /
                                 16A hash 校验契约 / producer 无法签发 permit /
                                 consume 必填真实身份 / 双摘要分离 / 证据不可自铸 /
                                 Gate 绑定 expected contract / Contract A grant 不覆盖
                                 Contract B / evidence 上下文任一变化拒绝 / nonce 一次性/
                                 跨 context/超窗 / 双来源拒绝+原子消费 / 合法四路径通过
PERMISSION_REGRESSION          = pytest tests/agent tests/test_agent_tools.py
                                 tests/test_skeleton.py：316 passed
                                 （15 warnings 为既有线程 ResourceWarning 类告警，与本阶段
                                 无关；较 Patch 3 的 313 +3 = Patch 4 否证测试新增）；另跑
                                 16B/16A 专项
                                 tests/agent/integration/test_phase16b_execution_backend.py
                                 test_phase16a_work_contract.py：161 passed
COGNITION_REGRESSION           = pytest tests/cognition：279 passed（Phase 15 cognition/store
                                 契约不变；approval 包零 cognition/sqlite 依赖有专项断言）
FULL_SUITE                     = .venv/Scripts/python.exe -m pytest -q（本轮仅一次）：
                                 1561 passed, 0 failed（exit 0）
                                 较 Patch 3 的 1558 恰 +3（Patch 4 否证测试新增）

REMAINING_GAPS                 = 1) 按 brief 无 UI 模态/Hermes(16C)/事件状态机(16E)/
                                   verifier(16F)/持久化 ledger(16H)/C7 commit(16G)/MCP——
                                   全部留待对应子阶段；2) ApprovalGate 尚未接入
                                   NativeAgentRuntimeBackend.submit / App 生产 wiring
                                   （本阶段仅模块 + conformance 测试；生产接线时
                                   user_evidence_verifier 应指向 C6 USER 事件台账查询并绑定
                                   操作上下文、owner_thread_id 指向 canonical USER 决策入口、
                                   PermitIssuer 由可信组合根在决策面 create_permit_issuer
                                   创建并注入 Gate）；3) 事件面为 broker 内建 redacted 域
                                   事件日志 + 可选外部 emit 回调，未绑定全局 EventBus 枚举；
                                   4) 会话 grant/permit/证据 nonce 为进程内状态，无持久化
                                   （16H 拥有 ledger）；5) Python 进程内不存在硬隔离：
                                   Patch 3/4 的 issuer/consumer 拆分与 event 生命周期约束
                                   的是**公开 API 面**（producer 只使用 broker/gate 公开
                                   API 的威胁模型），不声称 _private 属性/seal 对象是安全
                                   隔离；6) 基线已有 untracked（data/assets_v2/、
                                   scripts/assets_v2/、_night_*、nul）保持未触碰
READY_FOR_REVIEW               = YES
```

No fabricated PASS or test totals. External reviewer owns `16D_PASS`.
