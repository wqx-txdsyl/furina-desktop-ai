# Night Preflight B4 — D5 Relationship Anti-Spam（READ-ONLY，未实施；含真实引擎数值模拟）

任务书：`docs/phase/Phase_15/12_Phase_15_D5_Relationship_AntiSpam_Hardening_Task_Brief_EXACT.md`
基线：`391bed8`。模拟器：真实 `RelationshipEngine.apply()/decay()`，无任何代码改动。

## 1. 当前引擎线性累积问题——实测数据

初始 state：familiarity/trust/comfort/annoyance=0，interaction_tolerance=50，
social_confidence=40。

| 场景 | 结果（delta） | 判定 |
|---|---|---|
| 1 次 pet | fam +1.8, comf +4.2, soc_conf +3.0 | D5-T1 已满足：单次有感知 |
| 10 rapid pet | fam +17.5, comf +42.0, soc_conf +30 | 尚可接受但已偏高 |
| **100 rapid pet** | **fam 0→100(满)，comf 0→100(满)，soc_conf +60** | **runaway 实锤**：`apply()` 每次全量 delta（touch: fam2.5/comf6/soc3），仅靠 clamp 封顶 |
| 10 spaced pet（每次间 decay(3600s)） | fam +17.5, trust +0.5 —— **与 rapid 完全同值** | 长期维度无时间权重 → "一年慢慢摸" 与 "连点器" 无差别 |
| 5 次 reject（负样本族） | annoyance +35, tolerance −30, soc_conf −20 | 单场意外即可重挫 |
| 20 次 reject | annoyance 满格 100, tolerance −50(触底), soc_conf −40 | spam 下限攻击可行 |
| successful_help ×10 | trust +10, respect +30, soc_conf +40 | 唯一 trust 来源，单次 ~1.0 |
| failed_help ×20 | annoyance +90, soc_conf −40 | 同样线性 |

关键结构事实：
- `apply()` 对重复事件**无任何递减**；clamp 只防越界不防速度；
- `decay()` 仅回落短期维（annoyance/tolerance 等），长期维永不回归 →
  正负两向的"短窗爆发"都成立；
- touch 族给不了 trust（trust 仅 help 族、且 ×0.5 慢速）→ D5-T4"快速刷 trust"
  现状部分免疫，但 familiarity/comfort 可被秒满。

## 2. A–E 机制对照（brief §4 四选一+混合，按产品语义评估）

| 方案 | 连续/平滑 | restart 安全 | 可测性 | 防游戏化 | 不抹历史 | 结论 |
|---|---|---|---|---|---|---|
| A daily absolute cap | ✗ 突断感 | 需持久计数 | 易 | 差（跨日刷新可再来一轮） | ✓ | 不推荐单独用 |
| B rolling-window cap | 半平滑 | 同上 | 中 | 中 | ✓ | 备选 |
| C diminishing returns per repetition | ✓ 连续曲线 | 见下 | 强（纯函数好锁） | 良 | ✓ 只压增量 | **主机制** |
| D hybrid saturation（C+窗口/家族分离） | ✓ | ✓ 若窗口由 C6 派生 | 中强 | 良 | ✓ | **推荐** |
| （E 不存在于 brief，视为 D 的具体参数化） | — | — | — | — | — | — |

## 3. 推荐方案（供 reviewer/任务书裁定，未实施）

**D = 家族饱和递减 + C6 派生窗口，不新建任何 store：**

```text
impact(event_i, family) = base_delta(family) * s(n)
  n   := 该 event-family 在滚动窗 W 内的历史事件数
         n 的真源 = C6 event_timeline 按类型查询（客观真相本来就都在！）
  s(n) = 1 / (n ** alpha)，alpha≈0.5~0.7（family 可调）
  同时保留既有 clamp/慢速规则不变；
  负族与正族分别饱和参数（negative family 允许更高下界系数，保 D5-T6"严重
  事件仍要疼"）。
```

理由：
- **restart-safe 天然成立**：n 从 C6 时间线现查（或小缓存），重启无损、无需新表；
- provenance 契约零接触：只改 engine._bump 前的增量计算输入，里程碑/C6 记录不动
  （D5-T8/T9 天然绿）；
- 连续可微、确定性、易做表驱动测试（把 100-pet 场景直接数值锁定）；
- "spaced 积累有意义"：W 过去后 n 归零重新计满衰减 —— 与 rapid 在数学上分道
  （修复实测中 spaced==rapid 的缺陷）。
- 反对纯 A（daily cap）：突断 + 跨日 exploit，且与"连续平滑"偏好冲突；
  C 单独用的 restart 语义比"从 C6 重放"弱，故并入 D。

风险提示：C6 查询需 limit-bounded（window 内 count 上限封顶 512 条即够）；
engine 目前拿不到 timeline 引用 → 接线是构造期依赖注入（n provider 回调），
不改写 truth 本身。

## 4. 必测场景映射验证（全部可由本模拟脚本复现）

```text
D5-T1/T2/T3/T4/T5/T7 均已有量化前后对照（§1 表）；T12 无新增 UI/intimacy 字段
（本 preflight 未加任何字段）。
```

（poke 在生产侧经 consolidator 映射为 annoyance 类关系事件，模拟中以 reject/
negative_response 代表负族路径。）

## Night Long-Run 增补（第二轮只读，未实施）

- **从 C6 派生饱和计数无需新真值仓**：家系→事件类型映射生产已就位
  （petting→USER_PET / poke→USER_POKE / drag→USER_DRAG，Phase14 R11 锁定；
  ignore/reject/help 族各有类型或 consolidator 折算事件落 timeline）。
  n(family,W) = event_timeline 按 type IN family AND created_at ≥ now−W 计数
  （LIMIT 封顶即可）；C6 本身就是客观真相 → 天然 restart-safe 且 provenance 零接触。
- **引擎注入点唯一性确认**：三处生产 producer（app 文本 fx、scheduler 反馈、
  memory_engine 内部交互风险）全部汇聚于 `RelationshipEngine.apply()` →
  只需在 apply 前对 base_delta 乘 s(n)，改一个函数收口全局，无第二套计数真相。
- 补充模拟（便宜项）：poke 家族（USER_POKE consolidated annoyance 类）与 reject 族
  行为方向一致性已在首轮表内验证（负族单调同形），不需要更多样本；数值表可直接
  变成 D5-T2/T4/T5/T7 的黄金基线断言。
- 参数基线建议：alpha_positive≈0.7（touch/conversation 家族）、alpha_negative≈0.55
  （负族衰减更慢以保严重性）、W 默认 30min——最终由任务书拍板，本报告只给起点。
