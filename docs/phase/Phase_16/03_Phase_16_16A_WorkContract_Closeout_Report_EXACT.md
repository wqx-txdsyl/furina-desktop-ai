# Phase 16 — 16A WorkContract
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED（等待外部 reviewer 验收；不声明 16A_PASS）
BASE_SHA                       = b107edf33a459a5b7080f1b0b575dd8a93cac06c
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，沿用 Phase 15 惯例）
BRANCH                         = feature/phase16-16a-work-contract
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

WORK_CONTRACT_MODULE           = furina/agent/work_contract.py（新增）
IMMUTABLE                      = true（WorkContract 及全部嵌套结构 @dataclass(frozen=True)；
                                  集合字段一律 tuple；setattr 抛 FrozenInstanceError 有测试锁定）
CONTRACT_ID_RULE               = 调用方提供稳定幂等键 ^wc_[0-9a-zA-Z][0-9a-zA-Z._:-]{2,63}$；
                                  同 contract_id + 不同 content_hash ⇒ ContractIdConflictError
                                  （ensure_no_conflict），是冲突不是更新；完全一致 = 幂等重放放行
VERSION_HASH_RULE              = contract_version 强制 semver 三段式且计入 hash 载荷；
                                  content_hash = SHA-256( canonical JSON )，canonical =
                                  json.dumps(sort_keys=True, separators=(",",":"),
                                  ensure_ascii=True)，envelope {hash_version:1, algorithm,
                                  fields}；排除运行时状态 created_at_epoch 与 content_hash 自身
CANONICAL_SOURCE_EVENT_REQUIRED= true（强制 C6 canonical USER 事件 id 格式 lev_<ms>_<hex>，
                                  regex ^lev_\d{10,17}_[0-9a-f]{4,32}$）
WORKSPACE_SCOPE_BOUNDED        = true（显式 read_roots/write_roots；拒绝文件系统根/盘根/
                                  用户主目录整体/空与相对当前目录根（abspath 前拦截）；
                                  规范化后重复根拒绝）
BUDGETS_BOUNDED                = true（max_duration_seconds / cost_limit.amount /
                                  max_attempts 三项必填；NaN/Inf/≤0 拒绝；事实上无界上限
                                  MAX_BUDGET_DURATION_SECONDS=86400*365、MAX_COST_AMOUNT=1e9、
                                  MAX_ATTEMPTS=99）
VERIFICATION_STANDARD_REQUIRED = true（≥1 条机器可查 criterion——kind 白名单
                                  process_exit_zero/artifact_file_exists/artifact_sha256/
                                  text_contains/regex_matches 且参数键恰配——和/或类型化
                                  verifier_refs（小写命名空间 token）；空标准拒绝；
                                  自由散文判据结构性不可表达）
PERMANENT_BOOL_PRESENT         = false（ApprovalPolicyRef 无任何 bool 字段；policy_kind 白名单
                                  approval_required_each_step / approval_required_on_risk_level /
                                  pre_approved_scoped，always/permanent/forever 语义直接拒绝）
WILLINGNESS_FIELDS_PRESENT     = false（全部 dataclass 字段名与序列化键不含 willingness/
                                  emotion/intimacy/relationship/affection/mood；
                                  无人格 backend 偏好；allowed_backends 仅用户选定的技术约束）

C1_C7_SCHEMA_CHANGED           = false
C1_C7_WRITERS_CHANGED          = false
DATABASE_MIGRATION_ADDED       = false
PRODUCTION_FILES_CHANGED       = 仅新增 furina/agent/work_contract.py（独立工作域新模块，
                                   未触碰任何既有生产文件）
TEST_FILES_CHANGED             = 仅新增 tests/agent/integration/test_phase16a_work_contract.py

TARGETED_TESTS                 = tests/agent/integration/test_phase16a_work_contract.py：
                                 30 passed（任务书 §6 十项最低锁定全覆盖：最小/完整构造、
                                 确定性 hash+往返、篡改检测、同 id 改约冲突、非法预算×11、
                                 空验收标准、散文判据拒绝、过宽工作区×5、重复根、产物越界
                                 write root、只读 projection、主观字段缺失、永久布尔缺失、
                                 C6/C7 四表 schema+行元组 RO 快照前后相等、重启往返真实+
                                 无隐藏持久化静态断言）
AGENT_COGNITION_REGRESSION     = pytest tests/agent tests/cognition tests/test_c2_contract.py
                                 tests/test_agent_tools.py：421 passed（15 warnings 均为既有
                                 线程 ResourceWarning 类告警，与本阶段无关）
FULL_SUITE                     = .venv/Scripts/python.exe -m pytest tests -q（仅一次）：
                                 1393 passed, 0 failed（156.69s，exit 0）
SKIP_XFAIL_ADDED               = false

REMAINING_GAPS                 = 1) 本阶段按 brief 不实现 ExecutionBackend/Hermes/approval
                                   runtime/execution ledger/verifier（16B–16F 范围），契约尚无
                                   消费方接线；2) workspace 校验为路径规范化 containment 级，
                                   不做 symlink/实存探测（属执行层职责）；3) capability/backend
                                   token 格式校验但无注册表白名单（16B registry 定义后接入）；
                                   4) artifact_expectations 允许为空（由 verification_standard
                                   保证可验收性）；5) 根目录 data/assets_v2/、scripts/assets_v2/、
                                   _night_* 与 nul 为基线已有 untracked，保持未触碰
READY_FOR_REVIEW               = YES
```

Do not replace `NOT_EXECUTED` or `NO` until real evidence exists. Do not declare `16A_PASS`.
