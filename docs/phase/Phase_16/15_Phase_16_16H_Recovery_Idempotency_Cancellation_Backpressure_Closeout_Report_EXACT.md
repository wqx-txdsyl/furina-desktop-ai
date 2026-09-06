# Phase 16 — 16H Recovery, Idempotency, Cancellation & Backpressure
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED — 16H 工作域持久化/幂等/恢复/取消/
                                 背压已实现并全量测试通过；停在 READY_FOR_REVIEW
BASE_SHA                       = 0c4ddc08ed9ee425a374c2e8ca20ae8d06fae9ed
                                 （ACCEPTED_16F_SHA；16F 已 PASS 并 ff-only
                                 集成到 feature/phase16-work-sovereignty）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit
                                 SHA，沿用 16A–16F 惯例）
BRANCH                         = feature/phase16-16h-recovery-idempotency
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

WORK_LEDGER_MODULE             = furina/agent/work_ledger.py（新增；独立
                                 work-domain SQLite 持久化——独立文件/独立
                                 连接/独立 schema versioning，与 Phase 15
                                 furina.db（C1–C7 归属 CognitionDB/
                                 MemoryStore）零表接触、零 writer 共享）
WORK_TABLES_ADDED              = work_schema_meta / work_contracts /
                                 work_executions / work_events /
                                 work_counters（全部为新增工作域表，位于
                                 独立 ledger DB；C1–C7 表零新增零修改）
MIGRATION_VERSION              = schema_version=16H.1 + PRAGMA user_version
                                 单调推进（0→1）；additive
                                 （CREATE TABLE/INDEX IF NOT EXISTS）；
                                 幂等（重复 reopen 零副作用，测试覆盖两次
                                 reopen 数据/版本保留）
LEDGER_OWNER                   = WorkLedger（独立连接，RLock 串行化，
                                 check_same_thread=False + busy_timeout=30s；
                                 全部 CAS/claim/计数更新在 `with self._conn`
                                 事务内原子完成；owner/UI tick 路径零 DB
                                 I/O——WorkEventBuffer.offer/snapshot 纯内存，
                                 结构化测试锁定）
CONTRACT_HASH_IMMUTABLE        = true（同 contract_id 不同 contract_hash →
                                 ContractIdentityConflict 类型化冲突；同 id
                                 同 hash 重复注册幂等零副作用）
ONE_ACTIVE_RUN_PER_CONTRACT    = true（partial UNIQUE INDEX
                                 idx_work_one_active(contract_id) WHERE
                                 is_active=1 硬约束 + 应用层前置检查；32
                                 并发 submit 恰 1 成功/31 DuplicateActive
                                 Execution；CANCELLING/UNKNOWN 等 active
                                 状态期间二次 submit 被阻止——reconciliation
                                 结束前禁止同 contract 二次 submit）
STATE_CAS_ENFORCED             = true（全部迁移/绑定/证据/验证标记带
                                 expected_version CAS——stale version →
                                 StaleStateVersion 零状态修改；终态吸收：
                                 CANCELLED/VERIFIED/FAILED 后零迁移（终态
                                 检查先于 CAS，stale worker 绝不能覆盖终态）；
                                 attempt 账本身份唯一/时间轴非递减/时间窗
                                 封闭）
UNKNOWN_VERIFY_ON_RECOVERY     = true（启动恢复 load_non_terminal →
                                 begin_reconciliation 持久化 UNKNOWN（不写
                                 C7）；有 backend status/reconcile 能力时由
                                 Hermes 内部 status 轮询查询原 run（SSE 断线
                                 绝不重复 submit——16C 已有）；terminal
                                 evidence 持久化后进入 16F 验证；16F 结果
                                 只有经 IndependentVerifier.outcome_is_
                                 authentic（类拥有入口）通过才标记 VERIFIED
                                 并持久化 verification_marker（report_digest，
                                 同事务原子）；证据不足保持 UNKNOWN）
CANCEL_WAITS_FOR_TERMINAL      = true（cancel intent 先落盘；RUNNING/
                                 WAITING/REPAIRING/VERIFYING → CANCELLING
                                 并等待真实 terminal evidence 或 timeout
                                 policy，绝不立即伪造 CANCELLED；pre-submit
                                 cancel（run 未绑定）→ 直接 CANCELLED 零
                                 backend run 零 stop；重复 cancel 幂等；
                                 CANCELLING 期间禁止迁移回
                                 RUNNING/WAITING/BLOCKED/TOOL/VERIFYING/
                                 REPAIRING（迟到 approve/事件不得复活执行）；
                                 stop 每活动 run 恰好派发一次
                                 （dispatch_stop_once），run 未绑定 → 零
                                 stop）
LATE_APPROVAL_BLOCKED          = true（approval wait 被取消 →
                                 approval_invalidated 持久化；迟到 approve
                                 试图迁移回 RUNNING/WAITING/BLOCKED →
                                 类型化拒绝）
EVENT_BUFFER_HARD_BOUNDED      = true（WorkEventBuffer 纯内存有界：
                                 per_run_cap/global_cap 硬上限；100k
                                 progress flood 后 buffer ≤128、dropped_ticks
                                 精确计数；ledger 侧 per-run/global 事件行
                                 双层硬上限；单 payload canonical JSON 字节
                                 有界（16E sanitize_payload + allow_nan=
                                 False））
CRITICAL_EVENT_LOSS            = false（critical（terminal/approval/
                                 cancel/disconnect/verification boundary/
                                 工具生命周期边界）永不丢弃——容量耗尽
                                 fail-closed 抛 CriticalBufferOverflow +
                                 critical_overflow 计数独立事务持久化（不随
                                 异常回滚），调用方停止摄取进入 UNKNOWN/
                                 reconcile；restart 后 terminal/critical
                                 evidence 保留，仅 operational buffer 清空）
PROGRESS_DROP_COUNTER_EXPOSED  = true（progress_dropped/coalescible_dropped/
                                 critical_overflow/duplicates 计数持久化于
                                 work_counters 且可查询）
TRUTH_COMMIT_CLAIM_AVAILABLE   = true（claim_truth_commit CAS：16 并发恰一
                                 owner 胜出、stale claim 拒绝、resolve 仅
                                 owner；本阶段只提供 claim/marker API，零
                                 C7/C6 写入）

C1_C7_SCHEMA_CHANGED           = false
C1_C7_WRITERS_CHANGED          = false
C7_C6_C3_WRITES_ADDED          = false
FPS_LOOP_DB_NETWORK_IO_ADDED   = false
PRODUCTION_FILES_CHANGED       = 1（furina/agent/work_ledger.py 新增；
                                 16A–16F frozen 契约与既有生产文件零改动）
TEST_FILES_CHANGED             = 1（tests/agent/work/
                                 test_phase16h_work_ledger.py 新增 14 项；
                                 既有测试零弱化零 skip 零 xfail）
TARGETED_TESTS                 = 14 passed / 0 failed / 0 skipped（16H 专项；
                                 覆盖任务书 PART 7：migration/reopen、
                                 C1–C7 schema/rows 相等、32 并发单 active
                                 claim、同 id 异 hash 冲突、stale CAS+终态
                                 吸收、六 crash window 逐点 reopen、UNKNOWN
                                 recovery 零重复 run、16F outcome 正负路径、
                                 cancellation 全路径、stop-once、critical
                                 flood fail-closed、100k progress flood 有界、
                                 restart evidence 保留、truth-commit 并发
                                 唯一、C7/C6 零写入、tick 路径纯内存、敌意
                                 payload/NaN/非 dict/非 str 键 fail-closed、
                                 防御性快照）
MIGRATION_RESTART_REGRESSION   = 包含于专项（crash_windows/restart 保留
                                 测试即 migration/reopen/recovery 专项）
PHASE15_FROZEN_GATES           = Phase 15 相关测试（memory/cognition）在
                                 tests/agent、tests/cognition 与 full suite
                                 中全部通过（frozen DB schema/rows 前后相等
                                 由专项测试逐值锁定）
FULL_SUITE                     = 1980 passed / 0 failed / 15 warnings（仅
                                 一次；15 warnings 全部来自非 16H 既有套件
                                 ——16H 专项 14 passed 零 warnings 零
                                 skipped）
REMAINING_GAPS                 = 4 项（closeout §REMAINING_GAPS 详表）：
                                 ①人工 takeover 未实现（任务书 §4 明确登记
                                 gap，不自行扩展）；②16F recovery 验证的
                                 timeout policy 目前为"保持 UNKNOWN"常量
                                 策略，可配置超时收口留待接线期；③Hermes
                                 crash-safe exactly-once stop 未声明——如实
                                 声明 durable at-most-once dispatch +
                                 ambiguous reconciliation（stop 结果不确定
                                 时 reconcile，绝不盲目重发）；④16G 接线时
                                 truth-commit claim → C7 投影的原子消费
                                 属 16G 任务
READY_FOR_REVIEW               = YES
```

## 1. Recon Gate 记录（任务书 PART 1）

```text
work ledger 数据库归属        = 独立 work-domain DB（默认
                                data/work_ledger.db，构造参数可配置）；
                                归属 16H WorkLedger；与 Phase 15 furina.db
                                零接触（测试逐值锁定 C1–C7 schema/rows
                                前后相等）
schema owner                  = WorkLedger（_WORK_SCHEMA + PRAGMA
                                user_version=1 + work_schema_meta
                                schema_version=16H.1）；C1–C7 schema owner
                                仍为 CognitionDB（frozen，零改动）
writer/thread model           = WorkLedger 独立连接（RLock 串行化 +
                                check_same_thread=False + busy_timeout=30s）；
                                写入全部经 `with self._conn` 事务；后台无
                                常驻线程；tick 路径（WorkEventBuffer）纯
                                内存零 I/O
migration 方案                = additive（CREATE TABLE/INDEX IF NOT
                                EXISTS）+ versioned（PRAGMA user_version
                                单调 + work_schema_meta.schema_version）+
                                幂等（重复 reopen 零副作用，测试两次
                                reopen 锁定）
crash-window 状态模型         = 六窗口显式封闭：w1 submit-intent 落盘前
                                （零行零副作用）→ w2 intent 落盘/run 未绑
                                （active STARTING，recovery UNKNOWN，二次
                                submit 阻止）→ w3 run 绑定持久（SSE 中断
                                不丢 run）→ w4 terminal evidence 持久
                                （BACKEND_DONE_UNVERIFIED + evidence JSON）
                                → w5 VERIFIED/truth-commit 未执行（marker
                                持久、claim 可认领）→ w6 pre-submit cancel
                                （CANCELLED 零 backend run 零 stop）。
                                submit intent 持久化严格先于远端副作用；
                                结果不确定 → UNKNOWN/reconcile，绝不自动
                                重复 POST
内存与数据库背压上限           = per-run events ≤256（默认）/global ≤4096
                                （默认，构造可配）；单 payload ≤4096 字节
                                （canonical JSON 后截断前拒绝越界源）；内存
                                buffer per_run_cap=128/global_cap=1024
                                （默认）；critical 满即 fail-closed（不淘汰
                                旧 critical）；progress 满确定性丢弃+计数
```

## 2. 与 16A–16F/16E 的集成点

```text
16A WorkContract              = immutable (contract_id, contract_hash) 注册
                                进 ledger；同 id 异 hash 类型化冲突
16E WorkExecutionState        = ledger 状态列直接复用 16E 规范状态枚举
                                （零第二状态词表）；UNKNOWN/VERIFYING/
                                REPAIRING/BACKEND_DONE_UNVERIFIED 等只进
                                工作域表，禁止写 C7 的约束由本模块结构保证
                                （独立 DB，零 C7 接触）
16E EventKind/priority        = record_event 经 classify_priority 自动分级
                                （critical 永不丢/droppable 确定性丢/
                                coalescible 合并）；payload 经 16E
                                sanitize_payload 有界脱敏后 canonical JSON
                                落库
16F IndependentVerifier       = mark_verified_by_outcome 经类拥有的
                                outcome_is_authentic 入口复核后才标记
                                VERIFIED（伪 seal/跨契约/非 authentic →
                                类型化拒绝零状态修改）；verification_marker
                                = report_digest 持久化
16G 接口                      = claim_truth_commit/resolve_truth_commit
                                CAS claim/marker（并发恰一 owner；stale
                                拒绝）——本阶段零 C7/C6 写入；16G 只能经
                                此 claim API 消费，且须先通过 16F
                                outcome_is_authentic
C7/C6/C3                      = 零写入（独立 DB 结构保证 + 测试
                                rows-before/after 逐值锁定）
GUI/60fps tick                = WorkEventBuffer.offer/snapshot 纯内存零
                                DB/vector/network I/O（结构化测试锁定）；
                                flush 到 ledger 由 owner 线程显式调用
```

## 3. 测试覆盖（tests/agent/work/test_phase16h_work_ledger.py，14 项）

对应任务书 PART 7 十七类最低锁定：①additive migration+幂等 reopen；②C1–C7
schema/rows 前后相等；③32 并发单 active claim；④同 id 异 hash 冲突；⑤stale
CAS 拒绝+终态吸收；⑥六 crash window 逐点 reopen；⑦UNKNOWN recovery 零重复
run；⑧真实 16F outcome 正负路径；⑨cancellation pre-submit/RUNNING/approval
wait/迟到 approve；⑩stop-once/不确定结果不重发；⑪critical flood fail-closed
+溢出计数；⑫10 万 progress flood 内存/DB 行/payload 有界；⑬restart 保留
terminal/critical evidence、仅清 operational buffer；⑭truth-commit 并发唯一/
stale 拒绝/C7 零写入；⑮tick 路径纯内存；⑯敌意 payload/NaN/非 dict/非 str 键
类型化 fail-closed；⑰查询防御性快照。全部无 weak assertion、无 skip、无
xfail。

## 4. 剩余缺口（均不阻塞 READY_FOR_REVIEW；已按任务书如实登记）

1. 人工 takeover 未实现（任务书 §4 第 7 点明确登记 gap，不自行扩展）。
2. UNKNOWN 的 timeout policy 当前为"保持 UNKNOWN"常量策略；可配置超时收口
   在 16G/接线期按 owner 需求参数化。
3. Hermes stop 的 exactly-once 语义：16C 无法证明 crash-safe exactly-once，
   如实声明 durable at-most-once dispatch + ambiguous reconciliation（stop
   结果不确定 → reconcile，绝不盲目重发）。
4. truth-commit claim → C7 投影的原子消费属 16G；本阶段仅提供 claim/CAS
   marker API。
