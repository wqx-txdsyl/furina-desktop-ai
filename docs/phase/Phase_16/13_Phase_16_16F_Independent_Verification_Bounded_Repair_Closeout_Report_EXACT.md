# Phase 16 — 16F Independent Verification & Bounded Repair
# Closeout Report — EXACT TEMPLATE（Reviewer Patch 3 后状态）

```text
STATUS                         = EXECUTED — 16F 独立验证 + 有界修复已实现并全量
                                 测试通过；Reviewer Patch 1 修复 8 组 blocker
                                 （substantive gate/内容 MIME/artifact_type/
                                 optional 语义/边界复核/进程输出有界/秘密边界/
                                 稳定快照/canonical identity）；Reviewer
                                 Patch 2 在**洁净重放分支**上修复 7 组 blocker：
                                 (B1) 内容真实性完整化——MIME 与有效性判定基于
                                 同一稳定完整有界快照（JSON 完整严格解析/PDF
                                 偏移 0 + 封闭结构/PNG·JPEG Pillow 结构验证/
                                 text 完整严格解码/空·畸形·截断·不可读 required
                                 FAIL）；(B2) artifact_type 策略 API 层不可变
                                 （MappingProxyType + tuple，修改/删除/追加
                                 全部失败且不影响验证事实）；(B3) 句柄锚定
                                 containment——先受约束取得句柄，再依据该句柄
                                 的 OS 级真实目标（GetFinalPathNameByHandle /
                                 /proc/self/fd / F_GETPATH）证明归属，读取只来自
                                 已证明句柄/同一不可变快照，symlink/junction
                                 交换（declared 与 criterion-only 双路径）不能
                                 逃逸；(B4) RepairLoop 只接受**当前验证器**的
                                 真实报告——seal 真实性 + contract_id/run_id/
                                 contract_hash/standard_hash 精确一致，外来
                                 签发/陈旧 run/异契约报告 → REPORT_REJECTED/
                                 final_report=None；(B5) 全部外部回调
                                 （run_id_factory/approval/collect/verifier/
                                 cost meter）之后用**新鲜状态**复核边界——
                                 factory 期间取消/超时/成本耗尽阻止 collect，
                                 cost 回调推进时钟后重新读取当前时间，越界
                                 VERIFIED 丢弃；(B6) run_id_factory 输出直接
                                 经公开 canonical validate_identity（非 str
                                 拒绝、绝不 str() 强转），秘密形态覆盖
                                 `_`/`.`/`-`/`:` 分隔前缀，异常回显一律脱敏；
                                 (B7) 任意调用方 regex 在可强制终止的隔离
                                 worker 中执行（硬超时 + 零输出聚合），Windows
                                 进程树改用 Job Object 硬约束（KILL_ON_JOB_
                                 CLOSE + CREATE_SUSPENDED 挂起态收编 + 拒绝
                                 breakaway，正常退出/超时/异常路径全部终止仍
                                 受管辖后代），POSIX 无等价保证 → process
                                 判据 fail-closed 拒绝评估；Reviewer Patch 3
                                 在同一洁净分支上修复 6 组 blocker：(B1) PDF
                                 真实封闭结构——不再只查 `%PDF-`/`%%EOF`，验证
                                 header/对象/xref/startxref/trailer/EOF 及偏移
                                 关系，伪 PDF/截断 xref/错误 startxref/条目偏移
                                 造假一律 fail-closed，合法最小 PDF（真实 xref
                                 表 + startxref 偏移）PASS；(B2) 单路径单快照
                                 ——每次 verify() 建立 canonical-path snapshot
                                 cache，expectation/declared/exists/sha/text/
                                 regex 复用同一不可变完整快照（只打开一次），
                                 criterion-only 文件完整读取（≤8MiB）且先证明
                                 整体为合法文本，空/超界 artifact_file_exists
                                 与 NUL 尾/JSON 快照拼接攻击全部 FAIL；(B3)
                                 接受 VERIFIED 前的最终稳定边界复核——
                                 _accept_verified_report 完成后 ≥2 轮完整安全
                                 扫描（hash→cost→cancel→新鲜时间，硬上限 3
                                 轮），cancellation 改 cost/cost 推时钟/seal
                                 认证翻取消/standard_hash 推 deadline/回调
                                 异常 → final_report=None（BUDGET_EXHAUSTED/
                                 TIMEOUT/CANCELLED/UNSTABLE_BOUNDARY）；(B4)
                                 POSIX regex worker 以 start_new_session 自建
                                 进程组，timeout 终止仅当 pgid 归属 worker
                                 自身才 killpg——绝不触碰宿主进程组（worker
                                 必死、宿主必活）；(B5) 公开模型身份验证——
                                 TerminalObservation/ArtifactObservation/
                                 EvidenceBundle/VerificationReport 的
                                 artifact_id/event_id/run_id/backend_id/
                                 contract_id 在 __post_init__ 统一经
                                 validate_identity，秘密形态直接拒绝，秘密
                                 路径异常回显脱敏（禁止 {path!r} 原文）；
                                 (B6) 安全测试禁止 skip——PowerShell 枚举不可
                                 用 → FAIL（P2-T/进程树终止测试），P3 新增
                                 安全否证零 skip/xfail；backend completed/
                                 exit 0/成功文本/自报 verified 一律不是证明；
                                 不写 C7/C6/C3、不实现 16G/16H、不修改
                                 C1–C7/schema/migration、16A/16B/16C/16D/16E
                                 frozen contracts 零改动（git diff 仅 16F 自有
                                 5 源文件 + 1 测试文件 + 本 closeout）；
                                 不合并 integration、不开始 16H、不声明
                                 16F_PASS；停在 READY_FOR_REVIEW
PATCH2_BASE_SHA                 = 1f988fa（= PATCH1_REPLAY_SHA；Patch 2 唯一
                                 BASE_SHA，洁净分支 tip）
PATCH1_REPLAY_SHA               = 1f988fa（d7a35c4 上的洁净重放提交；
                                 git diff d7a35c4..1f988fa 与
                                 a1586f7..544d1d1 字节级完全一致——
                                 PATCH1_DIFF_REPLAY_EXACT）
FINAL_SHA                       = 见外部 handoff（closeout 不包含自身 commit
                                 SHA，沿用 16A–16E 与 Patch 1 惯例；最终提交
                                 SHA 记录于 commit message 与本回执交付说明）
BRANCH                          = feature/phase16-16f-independent-verification-
                                 patch2-clean（自 d7a35c4 新建；仅含 16F 洁净
                                 重放 1f988fa + Patch 2 自有提交）
CHANGED_FILES                   = furina/agent/verification/__init__.py,
                                 models.py, checks.py, verifier.py, repair.py
                                 + tests/agent/integration/
                                 test_phase16f_independent_verification.py
                                 + 本 closeout（Patch 2 无新增私有测试辅助
                                 文件——P2 全部测试内联于既有测试文件）
CLEAN_ANCESTRY                  = true（d7a35c4 → 1f988fa → Patch 2 提交；
                                 不含 a1586f7 及任何 NIGHT-03 文件）
POLLUTING_ASSET_SHA_PRESENT     = false（d7a35c4..FINAL_SHA 无
                                 data/assets_v2/ 文件——git diff --name-only
                                 核验）
PATCH1_DIFF_REPLAY_EXACT        = true（git diff d7a35c4 1f988fa 与
                                 git diff a1586f7 544d1d1 逐字节一致：
                                 diff -q 输出 PATCH_DIFF_EXACT_MATCH）
FULL_CONTENT_VALIDATION         = true（full_content_verdict：MIME 识别与
                                 artifact 有效性基于同一稳定完整有界快照——
                                 JSON 完整严格 UTF-8 + 完整 json.loads、PDF
                                 偏移 0 + 版本 + 尾部 %%EOF 封闭结构、PNG/
                                 JPEG Pillow verify+load、text 完整无 NUL +
                                 严格解码；绝不只检查文件头/前 1 KiB 后默认
                                 剩余可信）
EMPTY_UNREADABLE_FAIL_CLOSED    = true（空/不可读/畸形/截断/oversize/mutated/
                                 逃逸/句柄目标不可证明 → required FAIL；
                                 unreadable 绝不跳过 MIME/hash/size 后放行）
OPTIONAL_PRESENT_FAIL_CLOSED    = true（optional 只豁免"不存在"；一旦存在，
                                 empty/unreadable/malformed/逃逸/oversize/
                                 声明矛盾全部 required FAIL）
ARTIFACT_POLICY_IMMUTABLE       = true（ARTIFACT_TYPE_CONTENT_RULES 为
                                 MappingProxyType，键/值/嵌套全部不可原地修改
                                 ——append/pop/setdefault/clear/赋值/删除均抛
                                 异常且不影响后续验证事实）
HANDLE_ANCHORED_CONTAINMENT     = true（open_contained：先受约束取得句柄，
                                 再依该句柄 OS 级真实目标证明归属；hash/size/
                                 MIME/文本/判据读取全部来自同一已证明句柄或
                                 同一不可变快照；平台无法证明句柄目标 →
                                 handle_target_unprovable 拒绝检查；验证期间
                                 路径替换/inode 变化/截断/增长 → mutated；
                                 pre-open realpath 仅作 missing/逃逸预筛，
                                 绝不作为安全判断依据）
CURRENT_VERIFIER_SEAL_REQUIRED  = true（RepairLoop 接受 VERIFIED 前必须
                                 self._verifier.seal_is_authentic(report)
                                 True——foreign-signer 子类/代理签发的有效
                                 格式报告一律 REPORT_REJECTED）
REPORT_IDENTITY_BOUND           = true（接受前复核 report.contract_id ==
                                 当前契约、report.run_id == 本次 attempt
                                 分配的 run_id、contract_hash/standard_hash
                                 与当前 verifier/契约预期精确一致——旧 attempt
                                 报告/异契约报告被精确身份拒绝，绝不修补或
                                 重新签署）
POST_CALLBACK_BUDGET_RECHECK    = true（run_id_factory 之后、approval 之后、
                                 collect/verify 之后、接受 VERIFIED 前全部
                                 重新读取 cancellation/contract hash/cost/
                                 当前时间——cost meter 回调推进时钟后再次
                                 读取**新鲜当前时间**，绝不缓存回调前旧时间；
                                 factory 期间取消/超时/成本耗尽/契约变异阻止
                                 collect）
FACTORY_IDENTITY_VALIDATED      = true（run_id_factory 输出直接经公开统一
                                 validate_identity——非字符串拒绝（绝不
                                 str() 强转）、词法 contract + 秘密形态拒绝；
                                 attempt_id 同走同一 canonical contract）
EMBEDDED_SECRET_BLOCKED         = true（秘密形态检测覆盖字符串内部及
                                 `_`/`.`/`-`/`:` 合法身份分隔位置：
                                 token:supersecret / run_password:hunter2 /
                                 x.api_key=abc / prefix-client_secret:value /
                                 authorization:BearerValue 全部拒绝；
                                 scrubber 与 identity rejector 共享同一秘密
                                 边界，异常回显先脱敏限长——raw secret 不
                                 进入异常）
RAW_SECRET_STORED_OR_EXPORTED   = false（原始秘密不进入 AttemptRecord/report/
                                 诊断/异常/failure signature/closeout）
REGEX_EXECUTION_BOUNDED         = true（任意调用方 pattern 绝不在主验证线程
                                 执行回溯——可强制终止的隔离 worker 子进程 +
                                 硬超时 + 输入上限 + 零输出聚合（stdout/
                                 stderr DEVNULL，唯一通道 exit code）；
                                 timeout/invalid/worker error → NOT_EVALUABLE
                                 → 最终绝不 VERIFIED；灾难性回溯否证锁定）
PROCESS_TREE_HARD_CONTAINED     = true（Windows：Job Object 硬约束——KILL_ON_
                                 JOB_CLOSE + CREATE_SUSPENDED 挂起态收编 +
                                 拒绝 breakaway，子进程从启动起即受约束；
                                 正常退出/超时/异常路径关闭句柄即终止一切仍
                                 受管辖后代（含 detached/新会话/新进程组），
                                 timeout 另 TerminateJobObject；P2-T detached
                                 后代否证 + 有界轮询零存活）
UNSUPPORTED_PROCESS_MODE_FAILS_CLOSED = true（POSIX 无 unprivileged 树级
                                 containment 证明 → process_exit_zero 判据
                                 NOT_EVALUABLE process_containment_unavailable
                                 → INCONCLUSIVE，绝不 best-effort 后 PASS；
                                 run_process_bounded 保留有界低层执行供直接
                                 调用，但 checker 拒绝评估）
TARGETED                        = 148 passed / 0 failed / 0 skipped（16F 专项：
                                 原 136 全保留 + Patch 3 新增 P3-A..P3-L 共
                                 12 项 reviewer-locked 否证/正例——P3 安全
                                 否证零 skip/xfail）
TESTS_AGENT                     = 555 passed（tests/agent 全目录一次；
                                 = Patch 2 基线 543 + Patch 3 新增 12）
COGNITION                       = 279 passed（tests/cognition 全目录一次）
FULL_SUITE                      = 1837 passed / 0 failed / 15 warnings（仅
                                 一次；= Patch 2 基线 1825 + Patch 3 新增
                                 12；15 warnings 全部来自非 16F 既有套件——
                                 16F 包零外部导入方，16F targeted 运行零
                                 warnings 零 skipped）
C1_C7_UNCHANGED                 = true（零写入/零 schema 依赖/零持久化；
                                 git diff 仅 16F 自有文件）
GIT_DIFF_CHECK                  = clean（git diff --check 零输出）
LOCAL_REMOTE_MATCH              = push 后核验，结论记录于外部 handoff
READY_FOR_REVIEW                = YES
```

## 0.0 Patch 3 回执（Reviewer Patch 3 专用）

```text
BASE_SHA                         = 841936c（PATCH2_FINAL_SHA；Patch 3 唯一 BASE_SHA）
FINAL_SHA                        = 见外部 handoff（closeout 不包含自身 commit SHA，
                                    沿用 16A–16E 与 Patch 1/2 惯例）
CHANGED_FILES                    = furina/agent/verification/__init__.py, models.py,
                                   checks.py, verifier.py, repair.py
                                   + tests/agent/integration/
                                   test_phase16f_independent_verification.py
                                   + 本 closeout（Patch 3 无新增私有辅助文件——
                                   P3 全部测试内联于既有测试文件）
PDF_STRUCTURAL_VALIDATION        = true（full_content_verdict 的 PDF 分支不再只查
                                   %PDF-/%%EOF：验证 header（偏移 0 + 版本号）、
                                   对象（n 条目偏移精确指向 <num> 0 obj）、
                                   xref 表（经典子段 + 定长 20 字节条目）、
                                   startxref（十进制偏移 + 指向真实 xref）、
                                   trailer（/Size+/Root + 覆盖关系）、EOF（尾部
                                   1KiB 且其后仅空白）及全部偏移关系；伪 PDF/
                                   截断 xref/错误 startxref/条目偏移造假/缺 Root
                                   一律 malformed_content:* fail-closed；合法
                                   最小 PDF（真实 xref 表）PASS；P3-A/P3-B 否证
                                   + P2-G/P2-F 正反例全保留）
SINGLE_PATH_SINGLE_SNAPSHOT      = true（每次 verify() 建立 _PathSnapshotCache
                                   （canonical normcase+normpath+expanduser 键）
                                   ——expectation/declared/exists/sha/text/regex
                                   对同一路径复用同一不可变 FileSnapshot（一次
                                   open、同一句柄、完整有界内容 + SHA-256 +
                                   full_content_verdict + 全文文本合法性 + 1 MiB
                                   解码窗口），任何检查不得重新按路径打开已缓存
                                   文件；P3-E 断言 expectation+declared+exists+
                                   text 四路同路径只打开 1 次）
CRITERION_FULL_CONTENT_CHECKED   = true（criterion-only 文件同样完整读取且 ≤
                                   MAX_ARTIFACT_BYTES：empty/unreadable/oversize/
                                   mutated/path escape 一律 required FAIL（unreadable
                                   不再 NOT_EVALUABLE），全文先证明合法文本
                                   （无 NUL + 严格 UTF-8）后搜索才限 1 MiB 窗口；
                                   P3-C/P3-D 否证锁定）
EMPTY_OVERSIZE_EXISTS_BLOCKED    = true（artifact_file_exists 对空文件 → FAIL
                                   artifact_empty、>8MiB → FAIL artifact_oversize
                                   ——存在本身不是有效证据；P3-C 否证）
FINAL_STABLE_BOUNDARY            = true（接受 VERIFIED 前、_accept_verified_report
                                   完成后执行最终稳定边界复核：≥2 轮完整安全扫描
                                   （contract hash → cost → cancellation → 新鲜
                                   当前时间），扫描次数硬上限 3 轮，回调异常 →
                                   UNSTABLE_BOUNDARY fail-closed；任一轮越界即
                                   final_report=None/VERIFIED=false；P3-G 三种
                                   变体 + P3-H 两种变体否证）
POST_AUTH_BUDGET_RECHECK         = true（seal 认证回调翻转 cancellation →
                                   CANCELLED；standard_hash 属性回调推进时钟越过
                                   deadline → TIMEOUT；cancellation 回调把 cost
                                   0→6（limit=5）→ 第二轮扫描 BUDGET_EXHAUSTED；
                                   cost 回调在最终复核内推进时钟 → TIMEOUT——
                                   全部 final_report=None，绝不接受越界 VERIFIED）
POSIX_REGEX_PARENT_SAFE          = true（POSIX regex worker start_new_session=True
                                   自建 session/进程组；_terminate_process_tree
                                   仅当 worker_pgid == worker_pid 才 killpg，否则
                                   只终止 worker 本身——绝不触碰宿主进程组；
                                   timeout 后 worker 必死、测试进程必活；Windows
                                   保持有界终止（taskkill /F /T）；stdout/stderr
                                   继续 DEVNULL、输入继续有界（P3-I 断言））
PUBLIC_MODEL_IDENTITY_VALIDATED  = true（TerminalObservation.event_id /
                                   ArtifactObservation.artifact_id /
                                   EvidenceBundle.contract_id·run_id·backend_id /
                                   VerificationReport.contract_id·run_id·backend_id
                                   在 __post_init__ 统一经 validate_identity——
                                   秘密形态直接拒绝（绝不清洗后继续作为身份），
                                   to_dict()/to_json() 因此不可能导出 raw secret
                                   身份；P3-J 直接构造否证）
SECRET_PATH_EXCEPTION_REDACTED   = true（verifier.py 秘密路径异常回显一律先
                                   scrub_secrets 并限长——禁止 {path!r} 原文；
                                   秘密形态路径/相对路径异常均不回显 raw secret
                                   （P3-K 断言 [REDACTED] 且 secret 不在消息））
SECURITY_TEST_SKIP               = false（P2-T 与进程树终止测试的 PowerShell 枚举
                                   skip 已移除——枚举/证明能力不可用时必须 FAIL
                                   不得 SKIP；P3 新增安全否证零 skip/xfail；16F
                                   targeted 运行 148 passed / 0 skipped）
TARGETED                         = 148 passed / 0 failed / 0 skipped（原 136 全保留
                                   + Patch 3 新增 12：P3-A fake PDF rejected /
                                   P3-B broken xref·startxref rejected /
                                   P3-C oversize·empty exists rejected /
                                   P3-D binary tail after text window rejected /
                                   P3-E one canonical snapshot per path /
                                   P3-F cross-snapshot JSON/text attack rejected /
                                   P3-G cancellation mutates cost before accept /
                                   P3-H authentication mutates deadline·cancel /
                                   P3-I POSIX regex timeout preserves parent group /
                                   P3-J public model secret identities rejected /
                                   P3-K secret path exception redacted /
                                   P3-L process proof cannot skip）
TESTS_AGENT                      = 555 passed（tests/agent 全目录一次）
COGNITION                        = 279 passed（tests/cognition 全目录一次）
FULL_SUITE                       = 1837 passed / 0 failed / 15 warnings（仅一次；
                                   15 warnings 全部来自非 16F 既有套件——16F 包
                                   零外部导入方，16F targeted 零 warnings 零
                                   skipped）
C1_C7_UNCHANGED                  = true（零写入/零 schema 依赖/零持久化；
                                   git diff 仅 16F 自有五源文件 + 1 测试文件
                                   + 本 closeout）
LOCAL_REMOTE_MATCH               = push 后核验，结论记录于外部 handoff
READY_FOR_REVIEW                 = YES
```

## 0. Reviewer Patch 2 — 洁净重放与 7 组 blocker 修复摘要

### 0.0 洁净祖先链

- `a1586f7`（NIGHT-03 资产提交）在 `544d1d1` 的祖先链上，即使与 16F 源码零
  重叠也不得随 16F 进入 integration → 从 `ORIGINAL_16F_BASE_SHA=d7a35c4`
  新建 `feature/phase16-16f-independent-verification-patch2-clean`，仅重放
  `544d1d1` 自身的提交差异（cherry-pick），得到 `PATCH1_REPLAY_SHA=1f988fa`；
  `git diff d7a35c4..1f988fa` 与 `git diff a1586f7..544d1d1` **字节级一致**
  （`diff -q` 判定 PATCH_DIFF_EXACT_MATCH），且 `d7a35c4..FINAL_SHA` 无任何
  `data/assets_v2/` 文件。Patch 2 全部改动以 `1f988fa` 为唯一 BASE_SHA。

### B1 — 内容真实性完整、确定且 fail-closed

- **完整内容验证器 `full_content_verdict(full)`**（models.py）：MIME 识别与
  artifact 有效性判定基于**同一稳定、完整、有界快照**（≤ MAX_ARTIFACT_BYTES
  的全部字节，单句柄读取，句柄前后 fstat + close 前 stat 一致性证明）：
  - JSON：BOM 容忍 + **完整**严格 UTF-8 解码 + **完整** `json.loads`——
    前导 `{`/`[` 正确但语法错误、截断、尾随垃圾全部 `malformed_content:
    json_*`（P2-A 否证）；
  - PDF：`%PDF-` 必须位于**偏移 0** 的合法起始位置（任意窗口出现 marker 不
    构成 PDF）+ 封闭受支持结构（版本号 `%PDF-\d+\.\d+` + 尾部 1 KiB 内
    `%%EOF`）——前导垃圾后嵌 marker 判为 text/plain → 命名/类型/声明通道
    矛盾 FAIL（P2-B）；截断缺 `%%EOF` → `malformed_content:pdf_structure`
    （P2-F）；
  - PNG/JPEG：魔数偏移 0 + **Pillow 确定性结构验证**（`verify()` + 重新
    打开 `load()`——截断 PNG 被 verify 捕获、截断 JPEG 被 load 捕获；
    异常/缺少 decoder/无法确认一律 `malformed_content:image_*` fail-closed，
    绝不接受截断/畸形文件（P2-F）；
  - text：**完整**内容无 NUL 且严格 UTF-8 可解码——前 1 KiB 文本后接
    NUL/二进制尾 → octet-stream → 命名/声明矛盾 FAIL（P2-C），前缀绝不掩盖
    尾部；
  - 空内容 → `("", "empty_artifact")`——空文件绝不是有效 artifact（含
    binary_blob，P2-D）。
- **required/unreadable/empty 分支**：`_expectation_checks`/`_declared_checks`
  中 `unreadable`/`handle_target_unprovable` → required FAIL `artifact_
  unreadable`/`handle_target_unprovable`（绝不跳过 MIME/hash/size 后让剩余
  检查通过，P2-E）；`empty_artifact` → required FAIL `artifact_empty`
  （P2-D）；`content_rejection`（malformed）→ required FAIL（P2-A/P2-F）。
- **optional 只豁免"不存在"**：存在即执行与 required 相同的完整检查
  （P2-H：malformed/unreadable → required FAIL；真正不存在仍 VERIFIED）。
- **criterion-only 文件**：同受 MAX_ARTIFACT_BYTES 硬上限 + 同一句柄快照 +
  可读性规则；不可读 → NOT_EVALUABLE、NUL/非法 UTF-8 窗口 → `content_not_
  text` FAIL（绝不靠窗口命中 PASS）。
- 六类合法内容（JSON/text/markdown/PDF/PNG/JPEG）正例 VERIFIED（P2-G +
  Patch 1 正例，夹具升级为结构合法字节：Pillow 生成的 1×1 PNG/JPEG +
  含 `%%EOF` 的最小 PDF）。

### B2 — artifact type 策略不可变

- `ARTIFACT_TYPE_CONTENT_RULES` 由可变 dict 改为 **MappingProxyType**（键不
  可增删改），值为 **tuple**（嵌套不可原地修改），类型标注 `Mapping[str,
  Tuple[str, ...]]`；验证器只读引用，进程内不存在可放宽策略的可变引用。
- P2-I：append/pop/setdefault/clear/赋值/删除全部抛异常，且修改尝试后验证
  事实不变（json_data 仍只收 JSON、未知类型仍 fail-closed）；P2-J：未知/
  变体 artifact_type（含大小写/空格变体）始终 required FAIL。

### B3 — 文件 containment 绑定已打开句柄

- 安全判断绝不只依赖 open 前的 `realpath`：`open_contained(path, contains,
  writable)` 先以只读方式取得句柄，再依据**该句柄**的 OS 级真实目标
  （Windows `GetFinalPathNameByHandleW` / Linux `/proc/self/fd/<fd>` /
  macOS `fcntl(F_GETPATH)`）证明其位于 workspace root 内；证明失败 →
  `handle_target_unprovable` 拒绝检查，绝不退回"先解析路径、后按路径打开"
  的不安全模式。
- `snapshot_file_contained`：hash/size/完整内容 MIME/文本窗口全部来自同一
  已证明句柄的同一不可变快照（≤ 8 MiB 完整读入内存后哈希+验证，有界）；
  句柄前后 fstat 一致且 close 前 stat(句柄派生最终路径) 一致——验证期间
  路径替换/inode 变化/截断/增长 → `mutated` → FAIL。
- 预筛 realpath 仅用于 missing/最近现存祖先逃逸分类（目标不存在时句柄无法
  打开），**不是**安全判断依据。
- P2-M（declared/expectation 路径）/P2-N（criterion-only 路径）用确定性
  同步点（monkeypatch open 时把父目录替换为指向 workspace 外的 junction/
  symlink——"containment 检查后、读取前替换"）否证：句柄目标证明拦截
  path_escape，外部内容 hash 一致/needle 命中也绝不放行。

### B4 — RepairLoop 只接受当前验证器的真实报告

- 新增 `_accept_verified_report(report, run_id)` 完整接受条件：
  ① `verdict == VERIFIED`；② `self._verifier.seal_is_authentic(report)`
  True（**当前实例密钥**——另一实例/子类代理签发的有效格式报告一律拒绝）；
  ③ `report.contract_id` 与当前契约精确一致；④ `report.run_id` 与本 attempt
  分配的 run_id 精确一致；⑤ `contract_hash`/`standard_hash` 与当前
  verifier/契约预期精确一致。任一不满足 → 新停止原因 `REPORT_REJECTED`，
  `final_report=None`，立即停止，绝不修补或重新签署外来报告；诊断有界
  （≤256 字符原因串）且脱敏。
- P2-K：foreign-signer 子类代理 → `seal_not_authentic_for_current_verifier`
  → REPORT_REJECTED；P2-L：seal 真实但 run_id 属旧 attempt（本实例密钥
  自签、run_id 不匹配）→ `run_id_mismatch` 拒绝；异契约验证器签发 →
  `contract_id_mismatch`/`standard_hash_mismatch` 等全身份拒绝。

### B5 — 所有外部回调后必须用当前状态复核边界

- 边界复核读取次序改为 **hash → cost meter → cancellation → 当前时间**：
  每个回调的副作用都被其后的读取捕获。`run_id_factory` 回调之后新增一次
  复核（factory 期间取消/超时/成本耗尽/契约变异必须阻止 collect，零
  collect 零 attempt——P2-Q 三种变体）；approval 回调之后复核（既有）；
  collect/verify 之后、接受 VERIFIED 之前复核（既有位置）。
- **post 边界使用回调全部结束后的新鲜时间**：`finished = max(attempt_
  finished, self._now_fn())`——cost meter 自身推进时钟后必须再次读取当前
  时间，绝不缓存 attempt 完成前的旧时间。任务书复现用例（attempt_finished
  =10、cost 回调把时钟推至 20、deadline=15 → 仍 VERIFIED）已否证锁定：
  P2-R → TIMEOUT、final_report=None、时钟 20.0。

### B6 — 所有生成身份统一使用 canonical validator

- `_allocate_ids`：`run_id_factory` 输出**直接**经公开统一 `validate_identity`
  ——非字符串返回值拒绝（绝不 `str()` 强转）、词法 contract + 秘密形态拒绝、
  拒绝先于存储（AttemptRecord 不可能携带原始秘密）；attempt_id 同走同一
  contract。
- `_SECRET_KV_RE` lookbehind 由 `(?<![a-z0-9_])` 收窄为 `(?<![a-z0-9])`——
  **合法身份分隔符 `_`/`.`/`-`/`:` 前缀的秘密键**（`run_password:hunter2` /
  `x.api_key=abc` / `prefix-client_secret:value` / `authorization:BearerValue`）
  全部命中；scrubber 与 identity rejector 共享同一秘密边界。
- `validate_identity` 异常消息**不再回显 raw value**（先脱敏限长）——原始
  秘密不进入异常/诊断（P2-O/P2-P 断言 secret 不在异常文本中）。
- §8.6 五类秘密形态（token:supersecret / run_password:hunter2 / x.api_key=abc
  / prefix-client_secret:value / authorization:BearerValue）全部拒绝（P2-O）。

### B7 — regex 与子进程的真实资源边界

- **regex**：`regex_match_bounded` 把任意调用方 pattern 交给**可强制终止的
  隔离 worker 子进程**（`python -c` + argv 传 pattern + stdin 传有界文本，
  stdout/stderr 一律 DEVNULL——零输出聚合，唯一通道是 exit code
  0=match/1=no-match/2=invalid/3=error）；硬超时（`communicate(timeout)` +
  超时终止进程树）；pattern 超长（>2048）→ NOT_EVALUABLE。主验证线程零
  回溯。P2-S：经典灾难性回溯 `(a+)+$` + 30k 近似输入 → worker 超时 →
  `regex_timeout` NOT_EVALUABLE → INCONCLUSIVE/零 seal；同报告普通 pattern
  仍 PASS（不是全面禁用）；测试自身硬耗时断言（<60s）。
- **进程树**：Windows 用 **Job Object** 提供 OS 级、"从启动起"的树级硬约束
  ——`CREATE_SUSPENDED` 创建子进程 → 挂起态 `AssignProcessToJobObject` 收编
  （`KILL_ON_JOB_CLOSE`，默认拒绝 breakaway）→ `NtResumeProcess`/逐线程
  ResumeThread 恢复；超时 → `TerminateJobObject`；正常退出/异常路径 → 关闭
  job 句柄即终止一切仍受管辖的后代（含 detached/新进程组/新会话）；job 创建
  失败 → 拒绝启动（fail-closed）。P2-T：父进程尝试以 DETACHED_PROCESS |
  CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB 启动孙进程（breakaway
  失败则退化为 detached）后 exit 0 → 验证 VERIFIED 后**有界轮询证明零存活
  后代**。
- **POSIX**：killpg 无法约束自行 `setsid` 的后代且无 unprivileged 容器
  保证 → `process_containment_guaranteed()` 返回 False，`process_exit_zero`
  判据在该平台 **fail-closed 拒绝评估**（NOT_EVALUABLE
  `process_containment_unavailable` → INCONCLUSIVE，绝不 best-effort 后
  PASS）；`run_process_bounded` 保留为有界低层执行工具（进程组 best-effort
  终止），但 checker 层不据此报告 PASS。P2-T POSIX 分支断言 fail-closed。

## 0.9 Reviewer Patch 3 — 6 组 blocker 修复摘要

### B1 — PDF 必须真实有效（封闭结构 + 偏移关系）

- `_validate_pdf_structure` 不再只检查 `%PDF-` 与 `%%EOF` 两个 marker，改为
  验证**封闭受支持的 PDF 子集**：① header（`%PDF-<major>.<minor>` 位于偏移 0，
  版本号后不得紧跟数字）；② EOF（`%%EOF` 位于尾部 1 KiB 内且其后仅允许空白）；
  ③ startxref（必须存在且携带十进制字节偏移，指向 xref 表）；④ xref 表
  （经典格式：子段 start/count + 定长 20 字节条目 `nnnnnnnnnn ggggg n|f`，
  每条 `n` 条目记录的字节偏移必须**精确指向**文件中对应 `<num> 0 obj` 的
  位置——偏移关系，非仅对象存在）；⑤ trailer（`/Size` + `/Root` 必须存在，
  Root 对象号必须落在 xref 覆盖范围内且真实定义于文件中）。伪 PDF（marker+
  EOF 无结构）、随机内容、截断 xref、错误 startxref、条目偏移造假、缺 Root
  全部 `malformed_content:*` fail-closed；交叉引用流（/XRef stream）不在
  封闭子集 → 同样 fail-closed。条目总数硬上限（8192）防超界。任务书复现用例
  `b"%PDF-1.7\nnot a PDF\n%%EOF"` → `malformed_content:pdf_startxref_missing`。
- 测试夹具升级：`PDF_BYTES` 改为含**真实 xref 表 + startxref 偏移**的
  程序化自洽最小 PDF（偏移关系由 `_minimal_pdf()` 计算，杜绝手算漂移）；
  P3-A（伪 PDF）/P3-B（错误 startxref/截断 xref/缺 Root/条目偏移造假/count
  不符五种变体）否证 + 正对照（合法最小 PDF 必须 PASS），P2-F（截断缺
  `%%EOF`）/P2-G（六类合法内容正例）全保留。

### B2 — 同一路径只能使用一个完整快照

- 新增 `capture_file_contained(path, contains_path, writable) -> FileSnapshot`
  ——**唯一读取入口**：prefilter（realpath，仅 missing/逃逸分类，不读取内容）
  → `open_contained` 句柄级 containment 证明 → 同一句柄**完整有界读取**
  （≤ 8 MiB，前后 fstat + close 前 stat 一致性）→ SHA-256 +
  `full_content_verdict` + **全文文本合法性**（无 NUL + 严格 UTF-8）+ 1 MiB
  解码窗口。`snapshot_file_contained` 变为其兼容包装。
- `IndependentVerifier.verify()` 每次建立 `_PathSnapshotCache`
  （canonical normcase+normpath+expanduser 键）——expectation/declared/
  exists/sha/text/regex 对同一路径复用同一不可变快照（**只打开一次**）；
  `check_criterion` 接受 `snapshot_cache`，文件判据一律经快照判定，任何
  检查不得重新按路径打开已缓存文件。
- criterion-only 文件与 artifact 同规则：完整读取且 ≤ 8 MiB；
  empty/unreadable/oversize/mutated/path escape 一律 required FAIL
  （unreadable 由 NOT_EVALUABLE 改为 FAIL——"criterion 文件不可读必须失败"）；
  NUL/二进制尾（1 MiB 窗口之后）→ `content_not_text` FAIL——文件整体先证明
  是合法文本，搜索才限 1 MiB 窗口；`artifact_file_exists` 对空文件 →
  `artifact_empty`、>8 MiB → `artifact_oversize`（存在本身不是有效证据）。
- P3-E（expectation+declared+exists+text 同路径只打开 1 次）/P3-C（空/超界
  exists FAIL）/P3-D（文本窗口后 NUL 尾 FAIL）/P3-F（JSON 快照后换纯文本
  拼接攻击——第二次打开被缓存阻断，只打开 1 次、criterion 用同一 JSON
  快照、needle 未命中 FAIL）否证；P2-M/P2-N（句柄锚定交换逃逸）全保留。

### B3 — VERIFIED 前必须有最终稳定边界

- `run()` 在 `_accept_verified_report`（seal 认证 + standard/hash 属性访问，
  都可能携带调用方回调副作用）**完成后**新增最终边界复核
  `_final_stable_boundary(attempt_finished)`：至多 `_FINAL_BOUNDARY_SCAN_LIMIT`
  （=3，至少 2 轮 + 1 次余量）轮**完整安全扫描**（contract hash → cost →
  cancellation → **新鲜当前时间**）；任一轮出现超限/取消/超时/异常/契约漂移
  → 立即停止且 `final_report=None`（VERIFIED 绝不成为成功结果）；仅当全部
  扫描安全才接受。回调异常（无法取得稳定安全结果）→ 新停止原因
  `UNSTABLE_BOUNDARY` fail-closed。
- 任务书复现用例（最终 cancellation 回调把 cost 从 0 改成 6、limit=5）→
  第一轮 cost 先读（0）后 cancel 改写，**第二轮 cost 读到 6 → BUDGET_
  EXHAUSTED**；P3-G 三种变体（cancel 改 cost / cost 推时钟越过 deadline /
  cancel 回调抛异常）+ P3-H 两种变体（seal_is_authentic 翻转取消 →
  CANCELLED；standard_hash 属性推进时钟越过 deadline → TIMEOUT）全部
  final_report=None。既有 P2-Q/P2-R 与 B4 边界测试全保留（post-attempt
  单轮扫描在先、最终稳定复核在后，语义不冲突）。

### B4 — POSIX regex worker 不得杀宿主

- `regex_match_bounded` 的 POSIX worker 改以 `start_new_session=True` 创建
  （自建 session/进程组，不再与宿主共享进程组）；`_terminate_process_tree`
  的 POSIX 分支加 **pgid 归属守卫**：仅当 `os.getpgid(worker.pid) ==
  worker.pid`（目标自建组 leader）才 `killpg`，否则只 `proc.kill()` 终止
  worker 本身——**绝不触碰宿主进程组**（旧实现直接对共享 pgid killpg 会把
  测试宿主一并杀死）。Windows 保持有界终止（taskkill /F /T）；stdout/stderr
  继续 DEVNULL、输入继续有界（上游 ≤1 MiB 窗口）。P3-I 否证：spy 断言
  POSIX `start_new_session is True`、宿主 pgid 不变、worker 已死、输入 PIPE/
  输出 DEVNULL。

### B5 — 公开模型也必须守秘密边界

- `TerminalObservation.event_id`、`ArtifactObservation.artifact_id`、
  `EvidenceBundle.contract_id/run_id/backend_id`、
  `VerificationReport.contract_id/run_id/backend_id` 在 `__post_init__` 统一
  经公开 canonical `validate_identity`——秘密形态（`password:`/`token:`/
  `run_password:` 等）直接拒绝，**绝不清洗秘密后继续作为身份**；
  `VerificationReport.to_dict()/to_json()` 因构造面身份验证而**不可能导出
  raw secret**。P3-J 直接构造四类模型 + 报告三身份字段全部拒绝。
- `verifier.py` 秘密路径异常回显一律先 `scrub_secrets` 并限长——禁止
  `{path!r}` 原文（秘密形态路径、相对路径、mime、未知键等未验证调用方
  字符串面同样脱敏）；P3-K 断言异常消息含 `[REDACTED]` 且不含 raw secret。

### B6 — 安全测试禁止 skip

- 移除 P2-T 与进程树终止测试中的 `pytest.skip("PowerShell 进程枚举不可用")`
  ——枚举/证明能力不可用时测试必须 **FAIL**（断言 `count is not None`），
  不得 SKIP；P3 新增安全否证（P3-A..P3-L）全部无 skip/xfail。P3-L 否证
  process 证明能力被剥除（模拟 POSIX 无树级硬约束）→ `process_exit_zero`
  判据 fail-closed NOT_EVALUABLE → INCONCLUSIVE/零 seal，绝不 best-effort
  PASS、绝不 skip；证明可用（win32 Job Object）时真实评估 exit 0 → VERIFIED。

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

## 2. 证据与 containment（关键锁定 4/5/6/8 + Patch 2 B1/B3）

- 输入解析后立即 defensive-copy 并冻结（`MappingProxyType` 树 + flat 严格
  类型化）；报告 frozen dataclass + tuple，`to_dict()`/`to_json()` 每次构造
  全新对象图——测试断言导出篡改不回流、两次导出零共享嵌套引用、输入原地
  篡改不影响既有报告且新评估如实反映新值。
- **句柄锚定 containment（Patch 2 B3）**：先受约束取得句柄，再依据该句柄的
  OS 级真实目标证明其位于 workspace 内（Windows `GetFinalPathNameByHandleW` /
  Linux `/proc/self/fd` / macOS `F_GETPATH`）；读取只来自已证明句柄或同一
  不可变快照；句柄目标不可证明 → 拒绝检查（`handle_target_unprovable`）。
  预筛 realpath 仅作 missing/最近现存祖先逃逸分类（逃逸路径即使目标不存在
  也报 `path_escape`，绝不降级 missing；symlink/junction 双路 + 确定性交换
  同步点否证锁定——Patch 1 的 junction 逃逸测试与 Patch 2 的 P2-M/P2-N
  交换测试全部经句柄证明拦截）。
- **完整内容验证（Patch 2 B1）**：`full_content_verdict` 基于同一完整有界
  快照（见 §0 B1）；artifact 有效性不再依赖 1 KiB sniff 窗口——observed_mime
  即完整内容识别真值，`content_rejection`（empty/malformed）进入 required
  FAIL 通道。
- 本地哈希流式执行、8 MiB 硬界（超界 oversize 拒绝且零哈希零内容存储）；
  文本判据 1 MiB 有界窗口且同受 8 MiB 文件硬上限；进程重跑有界超时（默认
  60s、上限 600s）且 stdout/stderr/stdin 全 DEVNULL——输出内容零读取、零
  聚合、零存储（仅 exit code/超时事实），Windows 超时/退出路径由 Job Object
  硬约束终止整棵进程树（Patch 2 B7）。
- **秘密边界**：raw secret text 不进入报告、诊断、身份载荷与**异常**——
  检查解释/输入、evidence 路径记录面、evidence 诊断、repair 诊断
  （HardBackendFailure/approval/cost/collector）、failure signature 前置载荷
  一律 `[REDACTED]`；`validate_identity` 异常回显先脱敏限长；秘密形态身份/
  路径 fail-closed 拒绝（`_`/`.`/`-`/`:` 分隔前缀全覆盖，脱敏顺序授权头先于
  键值对，测试锁定）。
- **稳定快照**：产物观察与判据评估全部经单句柄快照（`snapshot_file_contained`
  / `_text_window_from_handle`），句柄前后 fstat + close 前 stat 一致性证明；
  验证期间替换/截断/增长/inode 变化 → `artifact_mutated_during_verification`
  FAIL（确定性变异注入器否证锁定）。

## 3. 有界修复循环（关键锁定 9/10/11/12 + blocker 4 + Patch 2 B4/B5/B6）

- 每次尝试：新 `att_NN_<hex>` + 工厂产出唯一 run_id（**直接经 canonical
  validate_identity**：非 str/词法非法/秘密形态 → VerificationError，绝不
  `str()` 强转、拒绝先于存储）；失败后从 BACKEND_DONE_UNVERIFIED 语义重入——
  重新收集证据并**再次独立验证**，绝不修补 verdict。
- **边界复核（blocker 4 + Patch 2 B5）**：hash→cost→cancel→时间 的读取次序
  保证每个回调副作用被其后读取捕获；复核点覆盖 attempt 前、**run_id_factory
  之后（新增）**、approval 回调后、collect/verify 后、接受 VERIFIED 前；
  post 边界使用**回调全部结束后的新鲜当前时间**（cost meter 推进时钟后重新
  读取，绝不缓存旧时间）；越界后的 VERIFIED report 不得成为成功结果
  （final_report=None）。cost meter 严格数值类型/finite/>=0/异常 fail-closed；
  启动前 `used>=limit` 零 collect。
- **VERIFIED 接受门（Patch 2 B4）**：`_accept_verified_report`——当前验证器
  seal 真实性 + contract_id/run_id/contract_hash/standard_hash 精确身份全部
  通过才接受；foreign-signer/旧 attempt/异契约报告 → `REPORT_REJECTED` 立即
  停止，final_report=None，绝不修补或重签。
- failure signature = 失败/不可判检查（check_id+result+explanation，脱敏后）
  的 canonical SHA-256——不含时间戳/run_id，同因再失败可识别；第 2 次相同
  签名 → `REPEATED_FAILURE` 断路（携带最后一次报告，verdict 原样）。不同
  原因不误断（专项测试：3 次三异签名 → 恰好 3 attempts 耗尽）。
- 停止条件全覆盖并精确停止：VERIFIED / `REPORT_REJECTED`（Patch 2 新增）/
  `HARD_FAILURE` / `APPROVAL_DENIED` / `CANCELLED`（含 attempt 中途出现）/
  `TIMEOUT` / `BUDGET_EXHAUSTED` / `ATTEMPTS_EXHAUSTED` / `REPEATED_FAILURE` /
  守卫性 `CONTRACT_MUTATED`。
- approval-gated 契约（approval_required_each_step / on_risk_level）构造期
  强制要求 approval_authority，缺失即拒绝构造（fail-closed）。

## 4. 测试覆盖（tests/agent/integration/test_phase16f_…py，136 项）

- 原 109 项（§7.1–§7.12 + exact-schema/冻结/导出/身份 + Patch 1 的
  B1–B8 否证正例）全部保留并通过；Patch 2 仅做语义保持的夹具适配：
  (a) PNG/JPEG/PDF 正例夹具升级为结构合法字节（Pillow 生成的 1×1 图像 +
  含 `%%EOF` 的最小 PDF）——否则正例本身不满足新的完整结构验证；(b)
  cost/cancel 计数适配 factory 后新增复核点（断言语义不变：meter 超限即停
  零 further collect、取消阻止下一次 attempt）。
- **Patch 2 新增 27 项 reviewer-locked（P2-A..P2-T，含参数化）**：
  P2-A malformed JSON（合法前导+截断/尾随垃圾）FAIL；P2-B PDF marker 前导
  垃圾后 FAIL；P2-C sniff 窗口后 NUL/二进制尾 FAIL；P2-D 空 required
  artifact（text+binary_blob）FAIL；P2-E unreadable required artifact FAIL
  （win32 真实 msvcrt 区域锁 / POSIX 确定性 PermissionError）；P2-F 截断
  PNG/JPEG/PDF FAIL；P2-G 六类合法内容正例 VERIFIED；P2-H optional 存在但
  malformed/unreadable FAIL、真正不存在 VERIFIED；P2-I 策略 mutation 不可
  能且事后事实不变；P2-J 未知 artifact_type 变体 fail-closed；P2-K
  foreign-signer 报告 REPORT_REJECTED；P2-L 陈旧 run/异契约报告精确身份拒绝；
  P2-M 句柄锚定 junction 交换（declared/expectation）不能逃逸；P2-N
  criterion-only 路径交换不能逃逸；P2-O 嵌入下划线秘密身份拒绝（§8.6 五
  形态 + terminal claim 身份字段）；P2-P 秘密/非字符串 run_id_factory 输出
  绝不存储；P2-Q factory 期间取消/超时/成本耗尽阻止 collect；P2-R cost
  回调推进时钟阻止 VERIFIED；P2-S 灾难性 regex 隔离有界（NOT_EVALUABLE +
  普通 pattern 仍 PASS + 硬耗时断言）；P2-T detached 后代无法存活
  （win32 Job 硬约束 + 有界轮询）/ checker fail-closed（POSIX）。
- 竞态测试全部使用确定性同步点（monkeypatch open 注入交换/变异/拒绝），
  不依赖随机 sleep；timeout 测试自带硬上限断言。

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
3. **POSIX 进程判据 fail-closed 不可用**：killpg 无法约束自行 `setsid` 的
   后代且无 unprivileged 容器保证 → `process_exit_zero` 在非 Windows 平台
   NOT_EVALUABLE（INCONCLUSIVE，绝不 PASS）。这是平台能力缺口的有意取舍
   （§9.2.3），等待容器级 containment（cgroup/容器 runtime）后在组合根层
   提供；Windows 路径为 Job Object 硬约束全量可用。
4. **图像结构验证依赖 Pillow**：PNG/JPEG 结构验证使用现有 Pillow
   （verify+load）；decoder 缺失/无法确认 → fail-closed（`malformed_content:
   image_verifier_unavailable`），绝不误通过。
5. **symlink 本体测试宿主依赖**：本宿主无 symlink 特权（WinError 1314），
   逃逸/交换测试以 junction 等价执行并通过；`os.symlink` 专属语义需在 Dev
   Mode/POSIX 宿主复跑（测试在链接机制完全不可用的宿主自动 skip）。
6. **成本口径**：`cost_used` 为注入计量器，16F 不发明成本语义；未注入时
   成本维度不参与停止判定（attempts/time 仍硬界）——真实 token/费用计量
   属组合根/16G 侧。计量器值本身受严格类型/finite/>=0 校验，异常即
   fail-closed 停止。
7. **文本判据有界窗口语义**：`text_contains`/`regex_matches` 仅在文件前
   1 MiB 窗口内判定（有界评估的显式取舍；窗口截断在 explanation 中如实
   标注 `window_truncated`），且文件整体受 8 MiB 硬上限——needle/pattern
   落在窗口外、或文件超上限的契约将被判 FAIL——这是 bounded evidence 的
   代价，不是缺陷。窗口内容经严格文本验证（NUL/非法 UTF-8 → content_not_
   text FAIL，绝不窗口内命中即 PASS）。
8. **verifier 密钥生命周期**：seal 密钥随验证器实例存活（内存）；跨进程
   复核（16G 持久化后重验）需要组合根持有同一实例或引入可持久化密钥——
   留给 16G/16I 的装配决策，16F 不擅自引入密钥存储。
9. **受支持 PDF 结构为封闭确定性子集**：偏移 0 header + 版本号 + 尾部
   `%%EOF`——满足该封闭结构的 PDF 通过，其余 fail-closed（不做任意 PDF
   语法完整解析；这是显式的、确定的受支持结构声明）。
```
