# Phase 16 — 16F Independent Verification & Bounded Repair
# Closeout Report — EXACT TEMPLATE（Reviewer Patch 1 后状态）

```text
STATUS                         = EXECUTED — 16F 独立验证 + 有界修复已实现并全量
                                 测试通过；Reviewer Patch 1 修复 8 组 blocker：
                                 (1) substantive gate——terminal claim/allowlist/
                                 verifier_ref 全 PASS 但零 substantive
                                 deterministic check（契约判据本地 PASS 或
                                 required artifact 真实本地检查 PASS）→ 强制
                                 INCONCLUSIVE/零 seal；(2) MIME 以有界内容识别
                                 为真值（PNG/JPEG/PDF 魔数 + JSON/text 明确
                                 有界规则）+ suffix 交叉核对 + 16F 封闭
                                 artifact_type→MIME 规则 + binary 仅显式接受 +
                                 unknown/unobservable fail-closed；(3) optional
                                 artifact 只豁免"不存在"，存在即任何问题
                                 required FAIL；(4) repair 在 attempt/approval/
                                 collect/verify 副作用边界前后复核
                                 cancellation/deadline/cost/contract hash，
                                 越界后 VERIFIED report 不成为成功结果
                                 （final_report=None），cost meter 严格类型/
                                 finite/>=0/异常 fail-closed、启动前 >=limit
                                 零 collect；(5) process 输出 DEVNULL 零聚合 +
                                 超时 taskkill /T 可靠终止整棵进程树；(6)
                                 全字符串面（含 HardBackendFailure/approval/
                                 cost/collector 诊断、failure signature 前置
                                 载荷、evidence 路径记录面）脱敏，秘密形态
                                 身份/路径 fail-closed 拒绝；(7) 单句柄稳定
                                 快照 + 前后 fstat/stat 一致性证明，验证期间
                                 变异 → artifact_mutated_during_verification
                                 FAIL，criterion-only 文件同受 8 MiB 上限；
                                 (8) canonical identity 显式 lexical contract
                                 （控制字符/首尾空白/静默 trim/秘密形态全部
                                 拒绝，绝不 normalize 后重新绑定）；backend
                                 completed/exit 0/成功文本/自报 verified 一律
                                 不是证明；不写 C7/C6/C3、不实现 16G/16H、
                                 不修改 C1–C7/schema/migration、16A/16B/16C/
                                 16D/16E frozen contracts 零改动（git diff 仅
                                 16F 自有 5 源文件 + 1 测试文件 + 本 closeout）；
                                 不合并 integration、不开始 16H、不声明
                                 16F_PASS；停在 READY_FOR_REVIEW
BASE_SHA                       = d7a35c4e1d61954f77b288bd7e9c64955d260bcc
                                 （16F 首次交付 commit；Reviewer Patch 1 自该
                                 基线出发，git rev-parse HEAD 核验一致）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，
                                 沿用 16A–16E 惯例）
BRANCH                         = feature/phase16-16f-independent-verification
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

VERIFIER_MODULE                = furina/agent/verification/verifier.py
                                 （IndependentVerifier——绑定单个不可变
                                 WorkContract；verify(exact-schema 提交) 是
                                 VERIFIED 唯一授权入口；substantive gate/
                                 内容 MIME/artifact_type 封闭规则/optional
                                 语义/稳定快照观察/身份 lexical contract）
EVIDENCE_MODEL_MODULE          = furina/agent/verification/models.py
                                 （EvidenceBundle/ArtifactObservation/
                                 TerminalObservation/VerificationCheck/
                                 VerificationReport/VerificationVerdict +
                                 精确 schema 键集/有界常量/有界内容识别
                                 sniff_content_mime/declared_mime_consistent/
                                 ARTIFACT_TYPE_CONTENT_RULES/validate_identity；
                                 checks.py 为 5 种 16A 判据的确定性检查器 +
                                 observe_file 稳定快照 + run_process_bounded；
                                 repair.py 为 BoundedRepairLoop）
DETERMINISTIC_CHECKS_FIRST     = true（16A VERIFICATION_CRITERION_KINDS 白名单
                                 五判据全部本地确定性执行：文件存在/realpath
                                 归属/SHA-256/有界文本窗口/正则/进程退出码
                                 本地重跑；无任何 LLM 组件，无 summary/proposal
                                 通道——deterministic-only 是本实现的显式选择）
SUBSTANTIVE_CHECK_REQUIRED     = true（Reviewer Patch 1 blocker 1：verifier_ref
                                 只表示"选择/支持哪个 verifier"，terminal
                                 claim/allowlist/verifier_ref 全 PASS 不构成
                                 成功证据——无至少一项 substantive
                                 deterministic check PASS（契约判据本地 PASS
                                 或 required artifact 真实本地检查 PASS）→
                                 强制 INCONCLUSIVE/零 seal；否证：criteria=()
                                 + artifact_expectations=() + verifier_refs=
                                 (VERIFIER_ID,) + backend.completed →
                                 INCONCLUSIVE/seal=""）
BACKEND_SELF_REPORT_TRUSTED    = false（证据提交 exact-schema 中不存在
                                 verified/exit_code/status/final_text/success
                                 等自报字段——未知键 VerificationInputError
                                 fail-closed；终态事件仅是绑定"验证哪次 run"
                                 的 claim，不构成证明；测试 §7.2/§7.6 源级+
                                 行为双锁定）
ARTIFACTS_HASHED_BOUNDED       = true（verifier 本地流式 SHA-256，>8 MiB
                                 oversize 拒绝绝不哈希；MIME 以有界内容识别为
                                 真值（magic/JSON/text 明确有界规则），扩展名
                                 只是命名层交叉核对，unknown suffix/命名与内容
                                 矛盾 fail-closed；artifact_type 经 16F 封闭
                                 ARTIFACT_TYPE_CONTENT_RULES 进入验证策略，
                                 binary/octet-stream 内容仅显式接受；终态事件
                                 ≤64、声明产物 ≤32、检查 ≤128、诊断 ≤32、解释
                                 ≤512 字符、报告 JSON ≤64 KiB。秘密边界准确
                                 表述：**raw secret text 不进入报告、诊断与
                                 身份载荷**——秘密形态（password/token/api_key/
                                 authorization/bearer 等）在进入报告/检查文本/
                                 诊断/failure signature 前置载荷前 [REDACTED]
                                 或直接 fail-closed 拒绝（身份/路径带秘密形态
                                 → VerificationInputError，绝不清洗后继续）；
                                 artifact 内容按判据要求正常哈希——"artifact
                                 内容从未被 hash"不是本实现的声明）
CONTENT_MIME_CHECKED           = true（PNG/JPEG/PDF 魔数；JSON 首非空白字符
                                 ∈{,[；text=无 NUL+严格 UTF-8；其余
                                 application/octet-stream 仅显式接受；声明
                                 MIME 与内容 exact 一致 + 文本族窄例外——
                                 文本 bytes+.png+声明 image/png → FAIL；
                                 PNG bytes+.jpg+声明 image/jpeg → FAIL）
ARTIFACT_TYPE_ENFORCED         = true（16F 显式封闭 artifact_type→内容 MIME
                                 允许集；未知 artifact_type → required FAIL
                                 unknown_artifact_type，绝不静默通过；
                                 artifact_type=png_image + 非 PNG 内容 → FAIL）
OPTIONAL_ESCAPE_BLOCKED        = true（optional artifact 只豁免"真正不存在"；
                                 一旦存在，path escape/symlink·junction 逃逸/
                                 oversize/unsupported MIME/non-regular/声明
                                 hash·size·MIME 矛盾任一发生都是 required
                                 FAIL，最终不得 VERIFIED）
PROCESS_OUTPUT_BOUNDED         = true（stdout/stderr/stdin 一律 DEVNULL——输出
                                 内容零读取/零聚合/零存储，禁止 PIPE+
                                 communicate 无界聚合；exit code 判定不变；
                                 超时后 taskkill /F /T（Windows）或进程组
                                 （POSIX）可靠终止整棵进程树；输出内容绝不
                                 进入 report/诊断——测试以拼接构造输出 marker
                                 锁定）
STABLE_ARTIFACT_SNAPSHOT       = true（同一次 verify 内 size/hash/MIME 判据
                                 来自同一打开句柄的单次有界读取；句柄前后
                                 fstat 一致且 close 后 stat(path) 一致——
                                 验证期间替换/截断/增长/inode 变化 →
                                 artifact_mutated_during_verification → FAIL
                                 绝不 VERIFIED；criterion-only 文件同样受
                                 MAX_ARTIFACT_BYTES 硬上限——大文件不能靠
                                 前 1 MiB 命中 needle 而 PASS）
IDENTITY_NORMALIZATION_USED    = false（canonical identity 显式 lexical
                                 contract：^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$
                                 + 秘密形态 scrub 差异检测——控制字符/首尾
                                 空白/静默 trim/非法字符/秘密形态一律
                                 VerificationInputError；身份比较一律 exact，
                                 无 trim/case-fold/normalize 后重新绑定）
INCONCLUSIVE_CAN_VERIFY        = false（INCONCLUSIVE 永不映射 VERIFIED——无
                                 绑定终态 claim/歧义终态/未授权 backend/未
                                 支持 verifier_ref/检查不可执行/**零
                                 substantive check** 一律 NOT_EVALUABLE →
                                 INCONCLUSIVE 且零 seal；repair 亦绝不升级其
                                 verdict）
POST_ATTEMPT_BUDGET_RECHECK    = true（accept VERIFIED 前再次复核
                                 cancellation/deadline/cost/contract hash——
                                 attempt 完成后 used>limit → BUDGET_EXHAUSTED、
                                 完成时间>deadline → TIMEOUT、attempt 中
                                 cancellation → CANCELLED、hash 漂移 →
                                 CONTRACT_MUTATED；越界后的 VERIFIED report
                                 不得成为成功结果（final_report=None）；
                                 cost_used 严格数值类型（bool/str 拒绝）/
                                 finite/>=0，meter 异常/NaN/Inf/负数 fail-
                                 closed；启动前 used>=limit → 零 collect；
                                 FakeClock/计量器否证锁定零误判）
MID_ATTEMPT_CANCELLATION_BLOCKED = true（collect/verify 期间翻转取消标志 →
                                 CANCELLED，VERIFIED report 不作为成功结果）
REPAIR_MAX_ATTEMPTS            = contract.budget.max_attempts（16A 硬界 [1,99]；
                                 每次尝试新 attempt_id/run_id 绑定同一
                                 content_hash；重复相同 failure signature 于
                                 第 2 次出现即断路，不烧剩余 attempts）
REPAIR_TIME_COST_BOUNDED       = true（deadline = 进入循环时刻 +
                                 budget.max_duration_seconds；deadline 前不
                                 启动任何新 attempt——精确停止；cost_used
                                 注入计量器严格校验后超 budget.cost_limit.amount
                                 即停；cancellation 在每次预检最先判定，取消后
                                 零新 attempt；hard failure/approval deny·
                                 timeout·pending·未知值 立停）
CONTRACT_MUTATED_DURING_REPAIR = false（frozen 16A 契约 + 边界复核
                                 content_hash 逐 attempt 校验；repair
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
                                 furina/agent/verification/repair.py
                                 （Reviewer Patch 1 仅改 16F 自有五源文件；
                                 既有其它生产文件零改动）
TEST_FILES_CHANGED             = tests/agent/integration/
                                 test_phase16f_independent_verification.py
                                 （保留原 70 项 + Reviewer Patch 1 新增 39 项
                                 reviewer-locked 否证/正例）
TARGETED_TESTS                 = 109 passed（16F 专项；70 原有 + 39 新增）
VERIFICATION_REGRESSION        = 516 passed（tests/agent 全目录：16A/16B/
                                 16C/16D/16E + agent C7 integration + 14.x/
                                 15.x 回归）
COGNITION_SUITE                = 279 passed（tests/cognition 全目录一次）
FULL_SUITE                     = 1798 passed / 0 failed（仅一次；= 16F 首交付
                                 1759 + Reviewer Patch 1 新增 39）
REMAINING_GAPS                 = 见下方"剩余缺口"节（不阻塞 READY_FOR_REVIEW）
READY_FOR_REVIEW               = YES
```

## 0. Reviewer Patch 1 — 8 组 blocker 修复摘要

1. **substantive verification gate**：`verify()` 在聚合前强制要求至少一项
   substantive deterministic check PASS——来源封闭为 ① WorkContract 判据
   （`criterion:*`）本地确定性 PASS；② required artifact（契约期望
   `required=True`）的真实本地检查 PASS。verifier_ref/terminal claim/backend
   allowlist 属资格检查，绝不计为成功证据；declared-only artifact 核对全 PASS
   也不构成 substantive（backend 可任意声明，不是契约锚点）。缺失时追加
   `evidence:substantive_check` NOT_EVALUABLE 检查 → INCONCLUSIVE、零 seal。
   否证：空 criteria + 空期望 + 合法 verifier_ref + bound backend.completed →
   INCONCLUSIVE；declared artifact hash 全核对 PASS 亦 INCONCLUSIVE。
2. **MIME/content/artifact_type**：`observed_mime` 来自 `sniff_content_mime`
   有界内容识别（PNG/JPEG/PDF 魔数；JSON=BOM/空白后首字符 ∈ `{[`；text=窗口
   无 NUL 且严格 UTF-8；其余 octet-stream）；`mime_for_suffix` 未知后缀返回
   `""`（后缀不再是 MIME）。三通道强制：命名通道（未知后缀 → FAIL；命名与
   内容不一致 → suffix_mime_mismatch）、声明通道（exact 一致 + 文本族窄例外，
   同族冒充 image/jpeg≠image/png 被精确相等拦截）、类型通道
   （`ARTIFACT_TYPE_CONTENT_RULES` 封闭表，未知类型 required FAIL，内容 MIME
   必须命中允许集）。binary/octets-tream 内容仅 `binary_blob` 类型或显式
   `declared_mime=application/octet-stream` 接受。全部 unknown/unobservable
   fail-closed。
3. **optional artifact 语义**：optional 只豁免"真正不存在"（返回空检查集）；
   一旦存在，containment/present/size/mime/hash/type/命名通道全部按
   required=True 产出——escape/symlink·junction 逃逸（16A 契约层禁止期望路径
   逃逸，逃逸只能经运行期链接发生）/oversize/unsupported MIME/non-regular/
   声明矛盾任一 → required FAIL → 不得 VERIFIED。present-optional 的检查
   同时**不计入 substantive**（防"空契约 + 摸一下 optional 文件"绕门）。
4. **repair 边界复核**：`_boundary_violation(pre=...)` 在每次 attempt 副作用
   边界前（cancellation 最先、contract hash、cost `>=limit` 零 collect、
   `now>=deadline`）、approval 回调之后、以及**接受 VERIFIED 前**（完成后
   `used>limit` → BUDGET_EXHAUSTED、`finished>deadline` → TIMEOUT、attempt 中
   cancellation → CANCELLED、hash 漂移 → CONTRACT_MUTATED）复核；越界后的
   VERIFIED report 不得成为成功结果（`final_report=None`，stop reason 如实）。
   cost meter 严格校验：严格数值类型（bool/str 拒绝）、finite、`>=0`、异常 →
   视同 +inf → BUDGET_EXHAUSTED，零误判（FakeClock/计量器否证锁定）。
5. **process output 真正有界**：`run_process_bounded` 一律 DEVNULL（stdin/
   stdout/stderr）——零读取/零聚合/零存储，exit code 判定保持正确；超时路径
   **先** `taskkill /F /T /PID`（Windows，树完整时枚举——先 kill 会断根导致
   孙进程存活）或 POSIX 进程组 SIGKILL，再 kill 兜底 + 有界 wait。输出内容
   绝不进入 report/诊断（测试用拼接构造 marker 锁定）。
6. **secret boundary**：全部字符串面统一脱敏——`VerificationCheck` 解释/输入
   （既有）、`ArtifactObservation` claimed/resolved 路径记录面（新增）、
   `EvidenceBundle` 诊断（新增）、`AttemptRecord`/`RepairOutcome` 诊断
   （__post_init__ 脱敏限长）、HardBackendFailure/approval/cost/collector
   diagnostic（新增）、failure signature 前置载荷（新增）。秘密形态身份字段
   与 artifact 路径（含契约期望路径，构造期拒绝）一律 `VerificationInputError`
   /`VerificationError` fail-closed——两个不同秘密值清洗成同一身份的歧义路径
   被结构排除，绝不清洗后继续 VERIFIED。closeout 措辞修正：**raw secret text
   不进入报告、诊断与身份载荷**（evidence digest payload/failure signature
   前置载荷均脱敏或拒绝）；artifact 内容按判据要求正常哈希。
7. **stable artifact snapshot**：`observe_file` 单句柄有界观察——size/hash/
   head（MIME 识别窗口）来自同一次打开；句柄前后 `fstat` 一致且 close 后
   `stat(path)` 一致（dev/ino/size/mtime_ns）；任一漂移 → rejection="mutated"
   → required FAIL `artifact_mutated_during_verification`，绝不 VERIFIED。
   `read_text_window` 同样快照化且先按 `MAX_ARTIFACT_BYTES` 硬上限拒绝——
   criterion-only 文件不允许大文件靠前 1 MiB 窗口命中 needle 而 PASS。
8. **canonical identity**：`validate_identity` 显式 lexical contract
   （`^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$` + 秘密形态 scrub 差异检测）作用于
   run_id/backend_id/event_id/contract_id/artifact_id（含 terminal claim 内
   四元身份与 declared artifact_id）；静默 trim 全部移除（` run_x ` /
   ` backend ` / 控制字符 / `password:hunter2` / `api_key:sk-…` →
   VerificationInputError，零报告零 seal）；身份比较一律 exact，不 normalize
   后重新绑定。

## 1. 权威模型（关键锁定 1/2/3）

- **VERIFIED 只能由 16F 独立验证成功产生**：`IndependentVerifier.verify()` 在
  真实执行全部确定性检查、全部 required PASS **且至少一项 substantive
  deterministic check PASS** 后，用验证器构造期随机密钥对 `report_digest`
  （canonical JSON SHA-256）做 HMAC-SHA256 签发 64-hex `authority_seal`。报告
  构造面只锁格式（无 seal/非 16F 身份的 VERIFIED → `VerificationAuthorityError`；
  非 VERIFIED 带 seal → 拒绝）；真实性只能经 `seal_is_authentic(report)` 用签发
  方密钥复核——伪造 seal / 换验证器实例复核均 False。与 16D broker 密钥 HMAC、
  16C operation_digest 现场重算同一模式；不依赖 `_private`/对象身份/调用方自报
  字段冒充 authority。
- **16E 公开 reducer 的 `VERIFICATION_BOUNDARY(verified)` 保持 fail-closed**
  （frozen 契约零改动）；16F 的权威面是自身 VerificationReport，16G（C7
  晋级）为既定消费方。16E 模块注释预留的"组合根注入权威通道"不在本 Delta
  范围（开放它必须改 16E frozen 转移引擎，触发 frozen-contract 纪律 → 不做）。
- **backend 自报零信任**：证据提交 exact-schema（`VERIFICATION_INPUT_KEYS` /
  `TERMINAL_CLAIM_KEYS` / `ARTIFACT_CLAIM_KEYS`）中不存在任何 backend 自报
  成功语义字段；未知键/缺键/非 str 键/NaN/Inf/bool 冒充数值/相对路径/重复
  id/非 16E 规范化词表 kind/身份或路径带秘密形态/身份含首尾空白或控制字符
  全部 `VerificationInputError`。终态 claim 必须与提交的 run_id/contract_id/
  backend_id 四元绑定（未绑定 claim 不参与裁定，全部未绑定 → INCONCLUSIVE）。

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
  path_escape；optional 期望经运行期 junction 逃逸同样 required FAIL。
- 本地哈希流式执行、8 MiB 硬界（超界 oversize 拒绝且零哈希零内容存储）；
  文本判据 1 MiB 有界窗口且同受 8 MiB 文件硬上限；进程重跑有界超时（默认
  60s、上限 600s）且 stdout/stderr/stdin 全 DEVNULL——输出内容零读取、零
  聚合、零存储（仅 exit code/超时事实），超时可靠终止整棵进程树。
- **秘密边界**：raw secret text 不进入报告、诊断与身份载荷——检查解释/输入、
  evidence 路径记录面、evidence 诊断、repair 诊断（HardBackendFailure/
  approval/cost/collector）、failure signature 前置载荷一律 `[REDACTED]`；
  秘密形态身份/路径 fail-closed 拒绝（脱敏顺序授权头先于键值对，测试锁定）。
- **稳定快照**：产物观察与判据评估全部经 `observe_file`/`read_text_window`
  单句柄快照，前后 fstat/stat 一致性证明；验证期间替换/截断/增长/inode
  变化 → `artifact_mutated_during_verification` FAIL（否证测试以确定性
  变异注入器锁定）。

## 3. 有界修复循环（关键锁定 9/10/11/12 + blocker 4）

- 每次尝试：新 `att_NN_<hex>` + 工厂产出唯一 run_id（重复/词法非法 →
  `VerificationError`，绝不虚构 attempt）；失败后从 BACKEND_DONE_UNVERIFIED
  语义重入——重新收集证据并**再次独立验证**，绝不修补 verdict。
- **边界复核（blocker 4）**：cancellation/deadline/cost/contract hash 在
  attempt 副作用边界前、approval 回调后、接受 VERIFIED 前全部复核；越界后
  的 VERIFIED report 不得成为成功结果（final_report=None）。cost meter 严格
  数值类型/finite/>=0/异常 fail-closed；启动前 `used>=limit` 零 collect。
- failure signature = 失败/不可判检查（check_id+result+explanation，脱敏后）
  的 canonical SHA-256——不含时间戳/run_id，同因再失败可识别；第 2 次相同
  签名 → `REPEATED_FAILURE` 断路（携带最后一次报告，verdict 原样）。不同
  原因不误断（专项测试：3 次三异签名 → 恰好 3 attempts 耗尽）。
- 停止条件全覆盖并精确停止：VERIFIED / `HARD_FAILURE`（collect 显式信号，
  记录后立即停）/ `APPROVAL_DENIED`（deny/timeout/pending/未知/空一律
  fail-closed，含首次尝试前 0 attempt）/ `CANCELLED`（含 attempt 中途出现）
  / `TIMEOUT`（deadline 前不启动新 attempt；完成后越过 deadline → TIMEOUT）/
  `BUDGET_EXHAUSTED`（启动前 `>=limit` 零 collect；完成后 `>limit` 即停）/
  `ATTEMPTS_EXHAUSTED` / `REPEATED_FAILURE` / 守卫性 `CONTRACT_MUTATED`。
- approval-gated 契约（approval_required_each_step / on_risk_level）构造期
  强制要求 approval_authority，缺失即拒绝构造（fail-closed）。

## 4. 测试覆盖（tests/agent/integration/test_phase16f_…py，109 项）

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
- 否证补充（首交付）：exact-schema 全型（缺键/NaN/Inf/bool/相对路径/重复 id/
  非法 kind/超量/非 Mapping）、defensive-copy 冻结、导出零共享引用、长输入
  限界、脱敏顺序、超时判据、可选 artifact 缺席仍可 VERIFIED；
- **Reviewer Patch 1 否证/正例（39 项）**：B1 空 criteria+空期望+合法 ref+
  bound completed → INCONCLUSIVE/零 seal、declared-only 不 substantive；
  B2 文本+.png+声明 image/png FAIL、PNG bytes+.jpg+声明 image/jpeg FAIL、
  未知后缀 FAIL、artifact_type=png_image+非 PNG 内容 FAIL、未知 artifact_type
  FAIL、binary 无显式接受 FAIL、binary+显式 octet-stream 正例、六类合法内容
  正例（PNG/JPEG/PDF/JSON/text/markdown）VERIFIED；B3 optional
  junction 逃逸/oversize/声明 hash 矛盾/unsupported MIME 全部 required FAIL；
  B4 attempt 中 cancellation/完成后 cost 超限/完成后越 deadline 时 VERIFIED
  report 不成为成功结果、meter bool/str/NaN/Inf/负数/异常 fail-closed、
  启动前 ==limit 零 collect；B5 DEVNULL 源面锁定 + 8MB 输出零聚合 + 输出
  marker 不入报告 + 超时进程树可靠终止（PowerShell CIM 轮询否证）；B6
  HardBackendFailure/approval 诊断脱敏、秘密形态路径拒绝；B7 确定性变异注入
  → artifact_mutated_during_verification FAIL、criterion-only 大文件
  oversize；B8 首尾空白/控制字符/秘密形态身份 → VerificationInputError。

## 5. 冻结边界确认

- C1–C7：零写入、零 schema 依赖、零 sqlite/持久化（源级 + 运行时双否证）。
- 16A/16B/16C/16D/16E frozen contracts：零改动（git diff 仅 16F 自有 5 源
  文件 + 1 测试文件 + 本 closeout）。
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
   属组合根/16G 侧。Reviewer Patch 1 后计量器值本身受严格类型/finite/>=0
   校验，异常即 fail-closed 停止。
5. **文本判据有界窗口语义**：`text_contains`/`regex_matches` 仅在文件前
   1 MiB 窗口内判定（有界评估的显式取舍；窗口截断在 explanation 中如实
   标注 `window_truncated`），且文件整体受 8 MiB 硬上限——needle/pattern
   落在窗口外、或文件超上限的契约将被判 FAIL——这是 bounded evidence 的
   代价，不是缺陷。
6. **verifier 密钥生命周期**：seal 密钥随验证器实例存活（内存）；跨进程
   复核（16G 持久化后重验）需要组合根持有同一实例或引入可持久化密钥——
   留给 16G/16I 的装配决策，16F 不擅自引入密钥存储。
7. **内容识别规则的有界性取舍**：JSON 识别为"首非空白字符 ∈ `{[`"的明确
   有界规则（不做完整解析）——以 `{` 开头的纯文本文档在 .md 命名下会被判
   命名/内容矛盾（fail-closed 方向，绝不误通过）；MIME 识别窗口 1 KiB。
