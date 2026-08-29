# Phase 16 — 16F Independent Verification & Bounded Repair
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED — 16F 独立验证 + 有界修复已实现并全量
                                 测试通过（新增 Furina-owned 独立任务级 verifier、
                                 bounded immutable EvidenceBundle、
                                 VerificationCheck/VerificationReport、
                                 VERIFIED/FAILED/INCONCLUSIVE 三值裁定、
                                 artifact hash/MIME/大小/数量/workspace
                                 containment（realpath，覆盖 symlink 与"目标
                                 尚不存在时最近现存祖先"逃逸）验证、严格有界
                                 repair loop、VERIFIED 唯一授权入口 = 密封
                                 HMAC 复核）；backend completed/exit 0/成功
                                 文本/backend 自报 verified 一律不是证明；
                                 不写 C7/C6/C3、不实现 16G/16H、不修改
                                 C1–C7/schema/migration、16A/16B/16C/16D/16E
                                 frozen contracts 零改动（git status 仅新增
                                 16F 自有 5 源文件 + 1 测试文件，既有文件零
                                 修改）；不合并 integration、不开始 16H、
                                 不声明 16F_PASS；停在 READY_FOR_REVIEW
BASE_SHA                       = 6441083a7e864d603a29a5152812a2631c9aaba9
                                 （ACCEPTED_16C_SHA；feature/phase16-work-sovereignty
                                 经 git merge --ff-only 快进至该 SHA 并 push，
                                 local == remote == 6441083 后切出本分支）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，
                                 沿用 16A/16B/16C/16D/16E 惯例）
BRANCH                         = feature/phase16-16f-independent-verification
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

VERIFIER_MODULE                = furina/agent/verification/verifier.py
                                 （IndependentVerifier——绑定单个不可变
                                 WorkContract；verify(exact-schema 提交) 是
                                 VERIFIED 唯一授权入口）
EVIDENCE_MODEL_MODULE          = furina/agent/verification/models.py
                                 （EvidenceBundle/ArtifactObservation/
                                 TerminalObservation/VerificationCheck/
                                 VerificationReport/VerificationVerdict +
                                 精确 schema 键集与有界常量；checks.py 为
                                 5 种 16A 判据的确定性检查器；repair.py 为
                                 BoundedRepairLoop）
DETERMINISTIC_CHECKS_FIRST     = true（16A VERIFICATION_CRITERION_KINDS 白名单
                                 五判据全部本地确定性执行：文件存在/realpath
                                 归属/SHA-256/有界文本窗口/正则/进程退出码
                                 本地重跑；无任何 LLM 组件，无 summary/proposal
                                 通道——deterministic-only 是本实现的显式选择）
BACKEND_SELF_REPORT_TRUSTED    = false（证据提交 exact-schema 中不存在
                                 verified/exit_code/status/final_text/success
                                 等自报字段——未知键 VerificationInputError
                                 fail-closed；终态事件仅是绑定"验证哪次 run"
                                 的 claim，不构成证明；测试 §7.2/§7.6 源级+
                                 行为双锁定）
ARTIFACTS_HASHED_BOUNDED       = true（verifier 本地流式 SHA-256，>8 MiB
                                 oversize 拒绝绝不哈希；MIME 白名单 + 扩展名
                                 观察映射；终态事件 ≤64、声明产物 ≤32、检查
                                 ≤128、诊断 ≤32、解释 ≤512 字符、报告 JSON
                                 ≤64 KiB；秘密形态在进入报告/检查文本前
                                 [REDACTED]，秘密从不被存储/哈希/导出）
INCONCLUSIVE_CAN_VERIFY        = false（INCONCLUSIVE 永不映射 VERIFIED——无
                                 绑定终态 claim/歧义终态/未授权 backend/未
                                 支持 verifier_ref/检查不可执行一律
                                 NOT_EVALUABLE → INCONCLUSIVE 且零 seal；
                                 repair 亦绝不升级其 verdict）
REPAIR_MAX_ATTEMPTS            = contract.budget.max_attempts（16A 硬界 [1,99]；
                                 每次尝试新 attempt_id/run_id 绑定同一
                                 content_hash；重复相同 failure signature 于
                                 第 2 次出现即断路，不烧剩余 attempts）
REPAIR_TIME_COST_BOUNDED       = true（deadline = 进入循环时刻 +
                                 budget.max_duration_seconds；deadline 前不
                                 启动任何新 attempt——精确停止；cost_used
                                 注入计量器超 budget.cost_limit.amount 即停；
                                 cancellation 在每次预检最先判定，取消后零
                                 新 attempt；hard failure/approval deny·
                                 timeout·pending·未知值 立停）
CONTRACT_MUTATED_DURING_REPAIR = false（frozen 16A 契约 + 循环守卫
                                 content_hash 逐 attempt 记录与校验；repair
                                 结构上无改约通道：collect_evidence 只收
                                 (attempt_id, run_id)，verifier 绑定构造期
                                 契约；不扩大 workspace/capabilities/backends/
                                 permission/预算）
VERIFIER_WRITES_C7_C6_C3       = false（verification 包零 cognition/事件
                                 总线/sqlite/持久化 import——源级扫描 + 运行时
                                 monkeypatch spy 双否证；工作域状态机晋级
                                 VERIFIED 的消费方属 16G）

PRODUCTION_FILES_CHANGED       = furina/agent/verification/__init__.py,
                                 furina/agent/verification/models.py,
                                 furina/agent/verification/checks.py,
                                 furina/agent/verification/verifier.py,
                                 furina/agent/verification/repair.py（全部
                                 新增；既有生产文件零改动）
TEST_FILES_CHANGED             = tests/agent/integration/
                                 test_phase16f_independent_verification.py
                                 （新增，70 项）
TARGETED_TESTS                 = 70 passed（16F 专项）
VERIFICATION_REGRESSION        = 477 passed（tests/agent 全目录：16A/16B/
                                 16C/16D/16E + agent C7 integration + 14.x/
                                 15.x 回归）
COGNITION_SUITE                = 279 passed（tests/cognition 全目录一次；
                                 与 16C closeout 精确基线一致）
FULL_SUITE                     = 1759 passed / 0 failed（仅一次；= 16C 基线
                                 1689 + 本 Delta 新增 70）
REMAINING_GAPS                 = 见下方"剩余缺口"节（6 项，均不阻塞
                                 READY_FOR_REVIEW）
READY_FOR_REVIEW               = YES
```

## 1. 权威模型（关键锁定 1/2/3）

- **VERIFIED 只能由 16F 独立验证成功产生**：`IndependentVerifier.verify()` 在
  真实执行全部确定性检查且全部 required PASS 后，用验证器构造期随机密钥对
  `report_digest`（canonical JSON SHA-256）做 HMAC-SHA256 签发 64-hex
  `authority_seal`。报告构造面只锁格式（无 seal/非 16F 身份的 VERIFIED →
  `VerificationAuthorityError`；非 VERIFIED 带 seal → 拒绝）；真实性只能经
  `seal_is_authentic(report)` 用签发方密钥复核——伪造 seal / 换验证器实例
  复核均 False。与 16D broker 密钥 HMAC、16C operation_digest 现场重算同一
  模式；不依赖 `_private`/对象身份/调用方自报字段冒充 authority。
- **16E 公开 reducer 的 `VERIFICATION_BOUNDARY(verified)` 保持 fail-closed**
  （frozen 契约零改动）；16F 的权威面是自身 VerificationReport，16G（C7
  晋升）为既定消费方。16E 模块注释预留的"组合根注入权威通道"不在本 Delta
  范围（开放它必须改 16E frozen 转移引擎，触发 frozen-contract 纪律 → 不做）。
- **backend 自报零信任**：证据提交 exact-schema（`VERIFICATION_INPUT_KEYS` /
  `TERMINAL_CLAIM_KEYS` / `ARTIFACT_CLAIM_KEYS`）中不存在任何 backend 自报
  成功语义字段；未知键/缺键/非 str 键/NaN/Inf/bool 冒充数值/相对路径/重复
  id/非 16E 规范化词表 kind 全部 `VerificationInputError`。终态 claim 必须与
  提交的 run_id/contract_id/backend_id 四元绑定（未绑定 claim 不参与裁定，
  全部未绑定 → INCONCLUSIVE）。

## 2. 证据与 containment（关键锁定 4/5/6/8）

- 输入解析后立即 defensive-copy 并冻结（`MappingProxyType` 树 + flat 严格
  类型化）；报告 frozen dataclass + tuple，`to_dict()`/`to_json()` 每次构造
  全新对象图——测试断言导出篡改不回流、两次导出零共享嵌套引用、输入原地
  篡改不影响既有报告且新评估如实反映新值。
- **containment 先于存在性**：`os.path.realpath` 解析后做
  `WorkspaceScope.contains_path`（产物按 write_roots，判据路径按
  read∪write）；逃逸路径即使目标不存在也报 `path_escape`（绝不降级
  missing）。symlink 与"最近现存祖先"两类逃逸在无特权 Windows 宿主经
  junction（`_winapi.CreateJunction`）等价覆盖——realpath 对两者解析一致，
  测试实证：链接内现存文件与"链接/subdir/new.md（不存在）"均被判
  path_escape。
- 本地哈希流式执行、8 MiB 硬界（超界 oversize 拒绝且零哈希零内容存储）；
  文本判据 1 MiB 有界窗口；进程重跑有界超时（默认 60s、上限 600s）且输出
  内容零存储（仅 exit code/超时事实）。秘密值形态（password/token/api_key/
  authorization/bearer 等）在进入检查文本/诊断前 `[REDACTED]`——脱敏顺序
  授权头先于键值对（否则 `authorization: Bearer xyz` 尾值泄漏，测试锁定）。

## 3. 有界修复循环（关键锁定 9/10/11/12）

- 每次尝试：新 `att_NN_<hex>` + 工厂产出唯一 run_id（重复/词法非法 →
  `VerificationError`，绝不虚构 attempt）；失败后从 BACKEND_DONE_UNVERIFIED
  语义重入——重新收集证据并**再次独立验证**，绝不修补 verdict。
- failure signature = 失败/不可判检查（check_id+result+explanation）的
  canonical SHA-256——不含时间戳/run_id，同因再失败可识别；第 2 次相同
  签名 → `REPEATED_FAILURE` 断路（携带最后一次报告，verdict 原样）。不同
  原因不误断（专项测试：3 次三异签名 → 恰好 3 attempts 耗尽）。
- 停止条件全覆盖并精确停止：VERIFIED / `HARD_FAILURE`（collect 显式信号，
  记录后立即停）/ `APPROVAL_DENIED`（deny/timeout/pending/未知/空一律
  fail-closed，含首次尝试前 0 attempt）/ `CANCELLED` / `TIMEOUT`（deadline
  前不启动新 attempt）/ `BUDGET_EXHAUSTED` / `ATTEMPTS_EXHAUSTED` /
  `REPEATED_FAILURE` / 守卫性 `CONTRACT_MUTATED`。
- approval-gated 契约（approval_required_each_step / on_risk_level）构造期
  强制要求 approval_authority，缺失即拒绝构造（fail-closed）。

## 4. 测试覆盖（tests/agent/integration/test_phase16f_…py，70 项）

- §7.1 有效确定性证据 VERIFIED + seal 可认证 + standard_hash 绑定验收标准；
- §7.2 伪造 completed/exit-zero/self-report 字段（verified/final_text/
  exit_code/status 未知键）一律拒绝；exit zero 由本地重跑裁定（同一命令
  退出 0/3 → VERIFIED/FAILED）；伪造 VERIFIED 报告无法通过真实性复核；
- §7.3 篡改（声明 hash 矛盾）/相对与绝对路径逃逸/symlink 逃逸/最近现存祖先
  逃逸/oversize/未知 MIME/声明 MIME 矛盾/声明产物缺失/声明路径偏离期望路径
  全部 FAILED 且 typed explanation；
- §7.4 混合检查一败即 FAILED（通过的检查仍在报告中）；§7.5 四类 INCONCLUSIVE
  （无终态/未绑定/歧义/非终态 kind）+ 未支持 verifier_ref + 未授权 backend +
  非法正则 + cwd 缺失，全部零 seal、repair 不升级；
- §7.6 schema 无自报字段源级断言 + verifier 强类型入口；
- §7.7 新证据才可 VERIFIED（stale 证据断路）；§7.8 attempts/time/cost 恰好
  停止（FakeClock：deadline 后零新 attempt、started_at 全部 < deadline）；
- §7.9 重复同签名 2 次断路、异签名不误断、INCONCLUSIVE 不升级；
- §7.10 取消/审批拒绝/超时/未知值/硬失败各停点 + approval-gated 契约无
  authority 拒绝构造；§7.11 跨 attempt 契约 hash 不变 + frozen 不可变 +
  verifier 契约绑定强制；§7.12 零 C7/C6/C3 写入（源级 9 token 扫描 +
  monkeypatch spy：`CognitionHub.persist_agent_result`/`EventBus.emit`
  运行时零调用）；
- 否证补充：exact-schema 全型（缺键/NaN/Inf/bool/相对路径/重复 id/非法
  kind/超量/非 Mapping）、defensive-copy 冻结、导出零共享引用、长输入限界、
  脱敏顺序、超时判据、可选 artifact 缺席仍可 VERIFIED。

## 5. 冻结边界确认

- C1–C7：零写入、零 schema 依赖、零 sqlite/持久化（源级 + 运行时双否证）。
- 16A/16B/16C/16D/16E frozen contracts：零改动（git status 仅新增 16F 自有
  5 源文件 + 1 测试文件 + 本 closeout；既有文件 diff 为空）。
- 16F 不合并 integration、不开始 16H/16G、不声明 16F_PASS。

## 6. 剩余缺口（均不阻塞 READY_FOR_REVIEW）

1. **evidence 组合根接线**：`collect_evidence(attempt_id, run_id)` 为组合根
   注入点——把 16C Hermes 事件流（SSE/状态 reconcile）+ 契约期望组装成
   exact-schema 提交属组合根职责，16F 只拥有接口契约与权威验证；16G/16I
   落地接线。
2. **16E reducer 权威通道未开放**：`VERIFICATION_BOUNDARY(verified)` 在公开
   reducer 保持 fail-closed（frozen）；工作域状态机的 VERIFIED 晋级消费在
   16G 以 `VerificationReport`（经 `seal_is_authentic` 复核）为唯一输入接入。
3. **symlink 本体测试宿主依赖**：本宿主无 symlink 特权（WinError 1314），
   逃逸测试以 junction 等价执行并通过；`os.symlink` 专属语义（如跨盘符号
   链接差异）需在 Dev Mode/POSIX 宿主复跑方可覆盖（测试在链接机制完全
   不可用的宿主自动 skip）。
4. **成本口径**：`cost_used` 为注入计量器，16F 不发明成本语义；未注入时
   成本维度不参与停止判定（attempts/time 仍硬界）——真实 token/费用计量
   属组合根/16G 侧。
5. **文本判据有界窗口语义**：`text_contains`/`regex_matches` 仅在文件前
   1 MiB 窗口内判定（有界评估的显式取舍；窗口截断在 explanation 中如实
   标注 `window_truncated`）。needle/pattern 落在窗口外的极端契约将被判
   FAIL/INCONCLUSIVE——这是 bounded evidence 的代价，不是缺陷。
6. **verifier 密钥生命周期**：seal 密钥随验证器实例存活（内存）；跨进程
   复核（16G 持久化后重验）需要组合根持有同一实例或引入可持久化密钥——
   留给 16G/16I 的装配决策，16F 不擅自引入密钥存储。
