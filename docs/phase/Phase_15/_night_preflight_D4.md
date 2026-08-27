# Night Preflight B1 — D4 Deterministic Temporal Semantics（READ-ONLY，未实施）

任务书：`docs/phase/Phase_15/06_Phase_15_D4_Deterministic_Temporal_Semantics_Task_Brief_EXACT.md`
夜审分支基线：`feature/phase15-d1-canon-act2-act3-evidence @ 391bed8`（只读检查）

## 1. 最小 schema delta

**推荐单列方案**：

```sql
ALTER TABLE user_model_items ADD COLUMN temporal_json TEXT NOT NULL DEFAULT ''
```

payload 结构（仅在有消费者/测试的字段才落）：

```json
{"kind": "POINT|RANGE|RECUR|MONTH|YEAR",
 "start_at": 1789000000.0, "due_at": ..., "end_at": ...,
 "date_precision": "day|month|year",
 "recurrence": {"weekly_dow": 5},
 "tz": "Asia/Shanghai"}
```

理由：
- brief §5 要求 "prefer a single coherent model"；散列多列违背且迁移面大；
- **`temporal_uncertain` 列已存在**（base.py:171 Phase 15D 迁移），模糊时间直接复用，
  不需要新列；
- 现有列 `valid_from/valid_to/declared_at` 是**记录时刻**语义，不得复用为"语义时刻"
  （两者混用会破坏 R12/R10-era 时效语义）。

## 2. 是否真的需要 schema migration

需要。user_model_items 表无任何 JSON 扩展位；`value_json` 被 value 语义占用，
向其塞 time 会污染全部既有消费者（interpreter dedupe 的 `str(i.value)==str(cand.value)`
比较、upsert 显示层）。项目已有幂等 forward-migration 机制（stores/base.py MIGRATIONS
列表，ADD COLUMN-if-absent），加一列成本低、可回放。

零迁移替代方案（塞 value_json）被否决，理由如上——列为决策记录。

## 3. 当前 timezone authority 在哪里

**不存在**。现状：
- 全仓 grep 无 zoneinfo/tzinfo 用法；唯一定点时区消费 =
  `furina/runtime/scheduler.py:554-555`（Phase 13 终审 §2.1）用 `time.localtime()`
  取本地 (hour,minute) 驱动作息——服务器本地时区即事实时区；
- U（canonical USER_MESSAGE）带 `created_at`（epoch 秒），无 tz 元数据；
- AppConfig 无 timezone 字段。

结论：D4 必须**新建** authority：推荐 `AppConfig.user_tz: str`（IANA 名，缺省
`time.tzname`/系统本地）。解析在 owner ingress 完成：
`(U.created_at, user_tz)` → 本地墙钟 → 相对词解析 → 绝对 epoch + precision +
iana 名一起落库。之后任何读取都**不再重解释**（brief §3 restart 不变量）。

## 4. 可 deterministic 的中文表达（第一版白名单，与 brief §4 对齐）

```text
可靠：今天 / 明天 / 后天 / 大后天（可含）
     YYYY-MM-DD、YYYY年M月D日、M月D日（歧义年→当期就近并置 temporal_uncertain=0 且
       date_precision=day）、今年/明年/去年+月份
     2026年9月 / 九月 / 下个月 → MONTH 粒度
     每周一~每周日（周X→weekly_dow）、每周（无 dow → uncertain=true）
策略型（须先定义明确语义再启用）：这周内 / 下周内 / 这周末 / 下周末
拒绝（→temporal_uncertain=1 保留原文）：过几天 / 最近 / 有空 / 以后 / 尽快 /
     下个月左右 / 九月可能 / 月底前？（无明确锚）
```

注意：九月的中文数字映射只需 一~十二 的固定表即可确定性完成，无需 NLU。
周期性习惯（每周六陪我看电影）应保留原文于 excerpt 并存 structured recurrence。

## 5. midnight / timezone 最大风险

1. **相对词基准必须是用户本地日历**：resolve 使用 `datetime.fromtimestamp(
   U.created_at, ZoneInfo(tz))` 后再加减天数；若误用 UTC 基准，中国区凌晨 0-8 点的
   "明天"会算错一天。T10 锁：本地 23:59 与 00:01 双边界。
2. **落库内容**：绝对 epoch 是 timezone-stable 的；但 DATE 类事件必须同时落
   `date_precision + tz`，否则夏令时地区再次转换可能漂一天。China 无 DST，但实现
   不得假设（T11 DST-safe 用 ZoneInfo 现成规则即可测）。
3. **persisted-then-replayed 场景**：重启后 process_pending 幂等重跑旧候选时，
   解析函数若以"当前时间"为参会把同一句重解为新日期 —— resolve 必须吃
   U.created_at 而非 now()（对应 D4-T2/T3）。

## 6. 受影响的现有测试（评估口径：会断言行为变化的文件）

```text
tests/cognition/test_phase15d_user_model_evolution.py   # declared_at/temporal_uncertain 语义
tests/cognition/test_phase15b_interpretation.py         # PLAN/IMPORTANT_DATE 候选与 temporal_scope
tests/cognition/test_phase14_final_reviewer_r6_r12.py    # R10 row→T→U 身份链（新增字段不得扰动）
tests/cognition/test_phase151_truth_closure.py           # lifecycle 幂等/restart
```

预计全部是**兼容性通过**（新列为可选载荷），不期望出现类似 D1 的硬编码期望迁移。

## 7. 发现的任务书遗漏 / 决策点（blocker 候选，供 reviewer 裁定）

1. **ROUTINE 缺口**：models.py 文档注释与 brief 都点名 ROUTINE，但
   `hub._apply_c4_candidate` 的 kind 白名单不含 `"ROUTINE"`（只有 FACT/HABIT/
   INTEREST/GOAL/PLAN/IMPORTANT_DATE 等）。D4 若覆盖 ROUTINE 必须先扩白名单——
   这是行为面变化，属任务书未写明的必要步骤，建议在实施任务书中显式列入。
2. **候选去重的 value 相等比较**（hub dedupe `str(i.value)==str(cand.value)`）
   与 temporal 载荷的组合：同 key 同 value 但 due 不同的 correction 应走 supersede
   还是 dedupe？建议实施时规定"temporal 不同不构成 dedupe 命中"，否则第二天重复
   说同一计划会被吞掉（T3 相关场景）。
3. EXPIRED 状态枚举存在但无写入方（§7 正确指出不做 auto-expire）；确认 D4 只读
   不碰它即可，无需额外工作。
4. 无其它发现阻塞项；未发现 brief 与代码冲突的其他点。

## Night Long-Run 增补（第二轮只读，未实施）

- **ROUTINE 白名单决策选项**：A) hub kind 元组加入 "ROUTINE" 并在落库时映射到
  HABIT 存储（key 前缀 routine:*），兼容现有消费者零改动；B) D4-v1 不覆盖 ROUTINE
  （任务书 §1 提及但非 REQUIRED），把词条留档推迟。**倾向 A**：改动面一行 +
  归一化存储，避免"文档有类别、系统不识别"的既有错位。
- **temporal dedupe key 风险**（原报告第 2 点的选项化）：hub 现按
  `(category,key,value_json 相等)` 判同。选项：
  a) dedupe 比较串加 temporal 指纹（kind+due 粒度归一）→ 同话不同期自动 supersede；
  b) value 相等但 temporal 不同 → 显式走 supersede 而非去重；
  c) 保持现状并把限制写进任务书。
  **倾向 b**（语义最诚实：新时间=新主张；复用既有 transition_event_id 链路，无 schema 改动）。
- **timezone owner 候选排序**：1) AppConfig.user_tz(IANA 名，显式可测)；
  2) time.tzname/系统本地(免配置但测试难固定)；3) 全 UTC+永不相对解析(退化保底)。
  推荐 1 为 authority、2 仅作缺省推导值、3 不作为任何持久路径。
- 外部参考复核：hermes/desktop/clawd 对 C4 写侧时间语义均无机制可借（审计见
  Phase_16 recon）→ D4 维持 FURINA-NATIVE 设计，避免无谓 scope 引入。
