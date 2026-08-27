# Phase 15 — D4 Deterministic Temporal Semantics
# CLOSEOUT REPORT — EXACT

## 1. Result

```text
READY_FOR_REVIEW
```

（不宣告 D4_PASS / PHASE15_PASS；判定权在外部 reviewer。）

## 2. Baseline / Branch / SHA

```text
integration baseline（PART 0 已 --ff-only 快进并推送）: fd27f014935bb7e7167ad6217358e7cc7354a916
task branch: feature/phase15-d4-temporal-semantics（自 fd27f01 切出）
final local SHA : 见 §10 git 状态（本任务最后 commit）
final remote SHA: == final local SHA（push 后校验）
```

## 3. Temporal Contract Implemented

- **支持（确定性白名单，全部有测试）**：
  - 相对日：今天/明天/后天/大后天 → 本地日历 POINT；
  - 绝对日期：`YYYY年M月D日`；缺年 `M月D日(号)` 取 basis 起最近将来（规则显式，T4）；
  - 有界跨度：本周/下周（周一~周日含端点）、这个周末|本周末、下个周末|下周末
    （周六~周日）、本月、下个月|下月、今年X月|明年X月（RANGE）；
  - 周重复：每周X / 每个星期X / 每星期X / 每礼拜X（RECUR dow；不带伪装 start）；
  - ANNUAL：生日是M月D日（IMPORTANT_DATE 窄生产者；年度重复为该语义自带）。
- **不支持/uncertain（一律 temporal_uncertain=1 且 temporal_json=''）**：
  过几天/最近/有空(的时候)/晚点/以后/月底前后/这阵子/改天 等；非法日期
  （2026年2月30日）；时区不可用。**绝不臆造精确日期**。
- **timezone source**：唯一 authority = resolver 显式 `tz_name` 参数（IANA 名，
  缺省常量 `temporal.DEFAULT_USER_TZ="Asia/Shanghai"`），由调用链顶 App 在 canonical
  ingress 与 basis_ts 一并注入。解析器内 `datetime.now()/date.today()/time.time()`
  零使用。
- **persisted representation**：`user_model_items.temporal_json` 单列 JSON
  `{v,kind,tz,basis,start?,end?,dow?,md?,year?,month?,precision?,matched?}`；
  uncertainty 走既有 `temporal_uncertain` 列（不进 JSON）。
- **restart semantics**：解析值以本地 ISO 字符串持久化；重放路径
  （USER_PLAN_DECLARED payload 内嵌 temporal）直接复用载荷，绝不以新的“当前时间”
  重解释。

## 4. Schema / Files Changed

| File | Change | Consumers |
|---|---|---|
| `pyproject.toml` | + `tzdata>=2024.1`（IANA 数据官方提供方；Windows 下 zoneinfo 依赖它解析 "Asia/Shanghai" 等 key —— D4 日历语义前提，非重型解析包） | zoneinfo |
| `furina/cognition/temporal.py` | **新增** 纯函数 resolver：resolve_temporal/detect_vague/local_datetime + DEFAULT_USER_TZ | interpreter/hub/tests |
| `furina/cognition/stores/base.py` | MIGRATIONS += `ADD COLUMN temporal_json TEXT NOT NULL DEFAULT ''`（幂等 forward） | CognitionDB 启动迁移 |
| `furina/cognition/models.py` | UserModelItem += `temporal_json:str=""` 字段；`temporal_payload` property（损坏→{} fail-closed）；from_row guard | 全部读取方 |
| `furina/cognition/stores/user_model.py` | upsert_item += `temporal_json` 参数与 INSERT 列（≤1000 字符截断） | hub 两处 upsert 位点 |
| `furina/cognition/interpretation/interpreter.py` | Candidate += `temporal:Optional[dict]`；interpret_text += `basis_epoch/tz_name`（None=完全不解析）；USER_PLAN_DECLARED 重放复用内嵌载荷 | hub |
| `furina/cognition/hub.py` | extractor：+大后天 marker、+生日 IMPORTANT_DATE 生产者、_plan_target 剥离日期/意愿词残渣（key 与具体日期无关→同实体异日期走 supersede 而非散行）；apply_user_message += `basis_ts/tz_name`，dev 事件 payload 嵌入 temporal；dedupe 分支升级为「value∧temporal 都同才算同一事实」 | App/process_pending |
| `furina/app.py` | submit_user_message 取一次性 `ingress_ts=time.time()`（与记录 canonical U 同一同步段）传入 apply_user_message(basis_ts=…) | 时间基准唯一入口 |
| `tests/cognition/test_phase15_d4_temporal.py` | **新增** T1–T16 + bounded-calendar 补充用例（17 个） | Gate A |

未触碰：C1/C2/C3/C5/C6/C7 authority 规则、relationship、retrieval 架构、Hermes、Agency、GUI、Voice。

## 5. Provenance

```text
canonical USER_MESSAGE U (ingress_ts=basis)
→ interpretation.interpret_text(basis_epoch=basis) → PLAN 候选(temporal=POINT 2026-08-28 …)
→ declaration 事件 USER_PLAN_DECLARED.payload.temporal = 同载荷（幂等重放锚）
→ user_model_items 行 temporal_json = 同载荷（source_event_id=dev.event_id）
→ （日期更正场景）旧行 status='superseded' + transition_event_id=新 dev.event_id
全链 event-id 可回溯（D4-T9 / R10-T1..T4 继续锁定）。
```

## 6. Counterexamples（实测）

```text
vague："过几天我打算整理房间"(basis 2026-08-27)
        → active 行 temporal_uncertain=1、temporal_json=''（无任何日期被编造）
midnight/timezone：basis=UTC 2026-08-27T23:30 时
        上海本地已是 08-28 早 07:30 → “明天”=08-29
        纽约本地仍是 08-27 晚   → “明天”=08-28（同一 epoch，两个合法答案，
        全由显式 tz 决定 —— T12）
U persistence failure（App 级强制 USER_MESSAGE append 抛错 → correction 回合）：
        user_model_items 总数不变、temporal_json 非空行为 0 条、
        USER_PLAN_DECLARED 事件为空（R10-FC fail-closed 保持，T10）
```

## 7. Tests

| Gate | Scope | Result |
|---|---|---|
| A（new D4 tests） | tests/cognition/test_phase15_d4_temporal.py（T1–T16+补充日历形） | **17 passed** in ~4s |
| B（既有 C4/Phase15.1 lifecycle） | phase151_truth_closure / 15c_memory_lifecycle / 15d_user_model_evolution | 合 Gate C 计 |
| C（Phase14 R10/R10-FC reviewer） | test_phase14_final_reviewer_r6_r12.py + r7_r10_failclosed.py | 合计 **79 passed**（B+C 合跑）|
| D（full cognition suite） | tests/cognition 全目录 | **208 passed** |
| E（FULL SUITE） | 全仓库 | **1273 passed / 0 failed / 0 skipped**（127s；1256+17） |

零 skip / 零 xfail / 零弱化断言。既有 two-plan coexistence / targeted completion /
ambiguous completion 用例全部原样保持通过。

## 8. Static Audit

`grep datetime.now(|date.today(|time.time()` 于时间解释/lifecycle 路径逐条分类：

```text
interpretation/interpreter.py:276 time.time()   → 仅 interpretation_id 毫秒戳（唯一性），非时间权威
stores/user_model.py ×4 now=time.time()          → 行簿记时刻（created/updated/valid_to），与语义日期正交
temporal.py                                      → 命中仅 docstring 否定句；实现零使用
C4 写入位点                                       → hub 三处 upsert_item（两条声明路径已统一参数面）；无第二写入方
未修改                                            → C1-C7 权威规则 / relationship / retrieval / Hermes / Agency / GUI / Voice
```

## 9. Remaining Temporal Gaps

- 模糊短语的原词证据保留于 excerpt/reason，未结构化存 matched token（低价值推迟）；
- IMPORTANT_DATE 当前仅覆盖生日窄模式（其它显式纪念日待后续模式）;
- GOAL 无生产候选来源（resolver 层已支持，未来出现生产者即生效）；
- ROUTINE/HABIT **DEFERRED**（执行令 PART 11）：hub kind 元组不含 ROUTINE、recurrence
  的查询/消费者缺失；resolver 已具备 RECUR 形态，启用只需扩白名单+消费者，无需再动 schema。

## 10. Git State

```text
commit 只包含 D4-scoped 文件（§4 表 + 本报告 + 06 任务书入库）
unrelated untracked（data/assets_v2/, scripts/assets_v2/, Phase_16/_night_*.md,
Phase_15 其余 _night_*/06-15 文档, nul）一律未 add/commit/move（工作区纪律遵守）
local SHA == remote SHA 于 push 后校验（分支 feature/phase15-d4-temporal-semantics）
未 merge 进 integration 分支；未开始 D2/D3/D5/Phase16
```

## 12. External Reviewer Residual Closure（Review = NEEDS_NARROW_PATCH → 已闭合）

针对 9727d6b 的六项残余全部闭合（同分支追加 commit，未动 D2/D3/D5/Phase16）：

| ID | 内容 | 实现 / 证据 |
|---|---|---|
| R1 | 生产用户本地时区权威 | `AppConfig.timezone`（IANA 名，空=未配置）→ `Furina._resolve_user_tz` 校验 → `Furina._user_tz`（None=fail-closed）→ `apply_user_message(tz_name=…)`。hub/interpreter 移除一切生产默认日历猜测：tz 缺失 ⇒ 整句时间解析跳过（无 UTC 冒充、无 Asia/Shanghai 冒充）。R1-T1 用真实 `submit_user_message` + 注入午夜附近固定时钟 + 配置 America/New_York → 行内 tz==配置值、start==NY 本地“明天”08-28；R1-T2 空 tz → 行存在但零日期零 uncertain 标记 |
| R2 | 周末优先级 | resolver 重排：周末别名块前置于整周块，且周块加 `"周末" not in t` 排他；四别名逐一锁定端点（本周末/这个周末→周六~周日当周；下周末/下个周末→次周），plain 本周/下周语义不变 |
| R3 | 近似/或者 fail-closed | 守卫三规则：近似量词(左右/大概/可能/也许/差不多/前后)∧有锚、或者|或是|还是连接∧有锚、≥2 个相对日并存 → uncertain=True 且 payload=None；“九月可能…”经月份锚触发；精确保留样例全部通过（明天写报告/下个月出差改型句/2026年9月3日提交） |
| R4 | 非法日历 | ANNUAL md 闰年安全校验（2月29合法/2月30拒）、MONTH-only 去 clamp（13月/0月→uncertain），不修复用户日期；R3b 锁定 |
| R5 | 精确 T→U 溯源测试 | T9 强化为逐环身份链：C4 row.source_event_id → USER_PLAN_DECLARED(by id) → declaration.turn_id → 该 turn_id 下**唯一** canonical USER_MESSAGE 且 payload.text 含原句；另断言 declaration.payload 内嵌 temporal.start |
| R6 | 真 overdue 测试 | T14 重写：历史 basis(2020-06-01) 声明 “我今天要完成发布清单” → 行内 POINT start=2020-06-01 → 重启 + 多批 process_pending 后仍 active（时钟流逝不产生 ACTIVE→COMPLETED）|

静态复审（新增）：DEFAULT_USER_TZ 仅存于 temporal.py 自身（函数签名默认值与 `_zone`
库层兜底），hub/app 等生产调用面零引用；resolve_temporal 生产调用唯一=
interpreter(传入 App 链路的 tz)；apply_user_message 生产调用唯一=App.submit_user_message；
读侧 temporal_payload 损坏即 {} fail-closed；无 read-time 重解释、无 auto-complete。

**Gates**：
```text
Gate A  tests/cognition/test_phase15_d4_temporal.py   22 passed（T17 + 新增 R 系列）
Gate B  全部既有 D4 测试                                同套件内含（原 17 例不变全绿）
Gate C  Phase14 R10/R10-FC                              20 passed
Gate D  tests/cognition 全目录                          213 passed
Gate E  FULL SUITE ×2                                1278 passed / 0 failed（185s, 167s）
```
（1273 = 前值 + 本补丁新增 5 个测试。）

## 11. Final Line

```text
READY_FOR_REVIEW
```
