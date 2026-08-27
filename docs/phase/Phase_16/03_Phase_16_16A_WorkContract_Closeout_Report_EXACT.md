# Phase 16 — 16A WorkContract
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED + Reviewer Patch 1/2 已落实（等待外部验收；不声明 16A_PASS）
BASE_SHA                       = b107edf33a459a5b7080f1b0b575dd8a93cac06c（初版）
                                 b23d8fee51956efccab358be8520a96c05ec10ec（Patch 1 起点）
                                 6902a805339bcd782d79028e45c36235c984399e（Patch 2 起点）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，沿用 Phase 15 惯例）
BRANCH                         = feature/phase16-16a-work-contract
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

WORK_CONTRACT_MODULE           = furina/agent/work_contract.py（新增；仅此一个生产文件）
IMMUTABLE                      = true（全部 @dataclass(frozen=True)；集合字段一律 tuple 且在
                                  __post_init__ 内 defensive-copy 固化——含 VerificationStandard
                                  .criteria：传入 list 即刻转 tuple，外部后续修改不影响契约、
                                  重算 hash 恒一致；setattr 抛 FrozenInstanceError 有测试锁定）
CONTRACT_ID_RULE               = 调用方提供稳定幂等键 ^wc_[0-9a-zA-Z][0-9a-zA-Z._:-]{2,63}$；
                                  同 contract_id + 不同 content_hash ⇒ ContractIdConflictError
                                  （ensure_no_conflict），是冲突不是更新；完全一致 = 幂等重放放行；
                                  直接构造时显式传入的 content_hash 同样强制 64 位小写 hex
                                  （格式非法先拒，值不符走篡改拒绝路径；缺省由内部计算）
NESTED_FROM_DICT_STRICT        = true（Patch 2 #1：全部嵌套 from_dict 无任何 float()/int()/
                                  str() 有损转换——serialized scalar 按原类型进入
                                  __post_init__ 严格校验；bool→int、float→int、
                                  numeric-string→float、number→str 一律拒绝；
                                  嵌套载荷缺键/形状损坏统一折为
                                  WorkContractValidationError，不泄漏 KeyError/TypeError）
VERSION_HASH_RULE              = contract_version 强制 semver 三段式并计入 hash 载荷；
                                  content_hash = SHA-256(canonical JSON)；canonical =
                                  json.dumps(sort_keys=True, separators=(",",":"),
                                  ensure_ascii=True, allow_nan=False)——严格 JSON 域，
                                  无 default 兜底，NaN/Inf/不可 JSON 化对象直接拒绝；
                                  envelope {hash_version:1, algorithm:"sha256", fields}；
                                  排除运行时状态 created_at_epoch 与 content_hash 自身
CANONICAL_SOURCE_EVENT_REQUIRED= true（强制 C6 canonical USER 事件 id 格式 lev_<ms>_<hex>，
                                  regex ^lev_\d{10,17}_[0-9a-f]{4,32}$）
WORKSPACE_SCOPE_BOUNDED        = true（read_roots/write_roots 显式；在任何 abspath **之前**
                                  拒绝非绝对根（相对路径 / ../x / ./x）；拒绝文件系统根/
                                  POSIX 根/盘根/UNC share 根/用户主目录整体；规范化后重复
                                  根拒绝；contains_path 采用 root+sep 前缀匹配，sibling
                                  前缀（work vs work_secret）不命中）
BUDGETS_BOUNDED                = true（max_duration_seconds / cost_limit.amount /
                                  max_attempts 必填且非 bool 数值；NaN/Inf/≤0 拒绝；
                                  上限 86400*365 秒 / MAX_COST_AMOUNT=1e9 / MAX_ATTEMPTS=99；
                                  CostBudget.currency 强制 ISO-4217 三字母大写规范化
                                  （'cny'→'CNY' 后参与 hash，同内容同 hash）；
                                  created_at_epoch 同样校验为非 bool 有限数值）
VERIFICATION_STANDARD_REQUIRED = true（≥1 条机器可查 criterion 或类型化 verifier_ref；
                                  kind 白名单 process_exit_zero/artifact_file_exists/
                                  artifact_sha256/text_contains/regex_matches 且参数键恰配、
                                  参数值必须 str 非空；空标准与散文判据结构性拒绝；
                                  所有 path 类判据参数必须在 workspace read/write 范围内，
                                  越界即拒）
PERMANENT_BOOL_PRESENT         = false（ApprovalPolicyRef 无任何 bool 字段；policy_kind 白名单
                                  approval_required_each_step / approval_required_on_risk_level /
                                  pre_approved_scoped；always/permanent/forever 语义直接拒绝）
WILLINGNESS_FIELDS_PRESENT     = false（全部 dataclass 字段名与序列化键不含 willingness/
                                  emotion/intimacy/relationship/affection/mood；
                                  无人格 backend 偏好；allowed_backends 仅用户选定的技术约束）

C1_C7_SCHEMA_CHANGED           = false
C1_C7_WRITERS_CHANGED          = false
DATABASE_MIGRATION_ADDED       = false
PRODUCTION_FILES_CHANGED       = 仅新增 furina/agent/work_contract.py（独立工作域新模块）
TEST_FILES_CHANGED             = 仅新增 tests/agent/integration/test_phase16a_work_contract.py

TARGETED_TESTS                 = tests/agent/integration/test_phase16a_work_contract.py：
                                 94 passed。覆盖任务书 §6 十项 + Patch 1 全部 blocker
                                 （B1–B8、B10：criteria 防御拷贝、required 严格 bool、
                                 CostBudget/created_at 严格校验与 currency 规范化、
                                 from_dict fail-closed 矩阵、严格 JSON 域、非 abs 根前置拒绝
                                 +UNC+sibling 否证、transport 往返稳定、path 判据 scope 内）
                                 + Patch 2 全部 blocker：
                                 P2-1 嵌套 scalar 拒绝矩阵——max_attempts True/1.9/"3"、
                                 duration "60.0"、cost amount "5.0"/True 与 currency 数值、
                                 criterion_id/kind/policy_id/policy_kind/scope_note/
                                 grant_record_ref 合法字符串改数值全部拒绝（原 payload 未触
                                 碰时重算 hash 保持一致）；缺键/坏形载荷统一
                                 WorkContractValidationError 无 KeyError/TypeError 泄漏；
                                 直接构造显式 content_hash 格式前置校验；P2-2 C5 快照修复见
                                 C1_C7_PROOF。
AGENT_COGNITION_REGRESSION     = pytest tests/agent tests/cognition tests/test_c2_contract.py
                                 tests/test_agent_tools.py：485 passed（15 warnings 为既有
                                 线程 ResourceWarning 类告警，与本阶段无关）
FULL_SUITE                     = .venv/Scripts/python.exe -m pytest tests -q（本轮仅一次）：
                                 1457 passed, 0 failed（209.01s，exit 0）
SKIP_XFAIL_ADDED               = false

C1_C7_PROOF                    = 重写后的
                                 test_c1_to_c7_real_store_truth_unchanged_by_workcontract_
                                 lifecycle：复用 Phase15 真实模式（tests/cognition/
                                 test_phase151_truth_closure._hub 的 MemoryStore/MemoryEngine/
                                 RelationshipEngine/CognitionHub 组装），对七类 cognition
                                 truth 分别取原生快照前后比对：C1 canon_identity（identity_facts/
                                 axes/voice/periods/persona 等原生 API 元组）、C2 canon_history
                                 （all_episodes/episode_count/sources/evidence_units/tier_counts
                                 只读注册面）、C3 memory 底层库全表快照、C4 user_model
                                 （query_active 原生行 + user_model_items 表）、C5 relationship
                                 ——Patch 2 #2 修复 false-green：禁用 getattr(rel,"engine")
                                 兜底，改用 RelationshipStore 公共只读面
                                 state_dict()/factors()/truth_owner/milestones()，并在快照内
                                 断言真实引擎数据存在（truth_owner=="RelationshipEngine"、
                                 state_dict ≥5 个数值键、factors 非空），前后完整相等；
                                 不再引用不存在的 cog.db "memories" 表（memories 属 mem.db，
                                 归 C3）；finally 同时关闭 hub 与 MemoryStore；
                                 C6 life_events（count/query_recent 原生行 + 表快照 +
                                 event_processing）、C7 agent_task 三表冻结 schema+行；
                                 另以 cog.db 全表兜底。WorkContract 构造/重放/冲突检测/
                                 from_dict/from_transport_json/projection 全生命周期前后
                                 逐项相等 ⇒ unchanged。

READONLY_VIEWS                 = 两类只读视图并存，措辞澄清（Patch1 #7）：
                                 (a) to_backend_projection()：递归 MappingProxyType 深度只读
                                 视图（进程内就地防改面），**不是** serialized payload；
                                 (b) 标准 JSON transport 面：to_transport_json()/
                                 to_transport_dict()/from_transport_json()——纯 JSON 域
                                 plain dict/str，可 json.loads/json.dumps 确定性往返，承载
                                 schema_marker+content_hash 的 fail-closed 校验，修改传输面
                                 不能反向改变 canonical。canonical 持久语义只有 to_dict/
                                 from_dict 校验往返一种，模块无任何隐藏存储行为。

REMAINING_GAPS                 = 1) 按 brief 无 ExecutionBackend/Hermes/approval runtime/
                                   ledger/verifier 及消费接线（16B–16F）；2) workspace 为
                                   规范化 containment 级（symlink/实存探测属执行层）；
                                   3) capability/backend token 格式校验但无注册表白名单
                                   （待 16B registry）；4) artifact_expectations 允许为空
                                   （verification_standard 保证可验收性）；5) 根目录
                                   data/assets_v2/、scripts/assets_v2/、_night_* 与 nul 为
                                   基线已有 untracked，保持未触碰
READY_FOR_REVIEW               = YES
```

Do not replace `NOT_EXECUTED` or `NO` until real evidence exists. Do not declare `16A_PASS`.
