# Phase 15 Recovery / Work Manifest

## 性质声明

Phase 15 文档是**当前进行中项目的原生文档**，不是历史恢复产物：
不使用 `EXACT_RECOVERED` / `RECONSTRUCTED` 状态标签，不虚构恢复史。

## Recovery rule

- Phase 15 无恢复需求；本文档只登记任务书、主计划与产出报告。

## Baseline terminology（03 主计划 §1 固化——两个 SHA 不可混用）

- `PHASE14_CODE_FROZEN_SHA = f8e84ecc7be67fbfa9d78f00b056bce4dd420095`
  （Phase 14 生产实现 + 测试 + reviewer closure = FROZEN）
- `PHASE15_WORKING_DOC_BASELINE = 4442fac4de1deabaf967d2f029032f0076512ab7`
  （= Phase 14 frozen code + 仅 Phase 15 文档 00/01/02）
- Phase 15 集成分支：`feature/phase15-cognitive-life-finalization`（自 `4442fac` 切出，
  §2.1）；禁止在 `fix/phase14-*` 命名分支上继续任何 Phase 15 生产工作。

## External audit verdict（03 §3）

```text
PHASE15_EXTERNAL_AUDIT_REVIEW = PASS_WITH_RECLASSIFICATION
```

02 报告的原始 T1-T5 分类**不再是实施授权**，被 03 主计划 §4/§6 的裁决取代
（修正 A-F 为永久性结论，后续文档必须保留）：
T1→D2 提级 / T3 外部实现措辞降级→D4 只采纳产品语义 / T4→P17-D1 延后 /
T5 拆分为 T5-A(→D5 ACCEPT) 与 T5-B(→P17-D2 延后) / RP-Skill 测试宣称的表述
精确化为 "not reproducibly substantiated by repository test artifacts at the audited SHA" /
Furinelle memory 权威模型 REJECT、persona 维度仅作参考。

## Accepted delta set（实施顺序固定：D1 → D4 → D2 → D3 → D5 → Integrated Final Gate）

```text
D1  C2 Act II/III Official Evidence Acquisition   (15A/C2, HIGH)
D4  Deterministic Temporal Semantics for C4       (15B/15D, HIGH)
D2  Real Hybrid Retrieval on Derived Index        (15E, VERY HIGH)
D3  Retrieval Injection Cooldown / Exposure Control (15E, MEDIUM-HIGH)
D5  Relationship Anti-Spam / Anti-Runaway Hardening (C5, MEDIUM)
```

永久延后（不得经实施便利回流 Phase 15）：P17-D1 计划主动跟进、P17-D2 关系气候→行为政策
（Phase 17 Character Agency）。详见 `03_...EXACT.md` §12/§23 决策表。

## Documents

| 类型 | File | 说明 |
|---|---|---|
| task brief | `01_Phase_15_External_Reference_Code_Audit_Task_Brief_EXACT.md` | Phase 15 首个正式任务：外部参考代码审计（READ-ONLY） |
| audit report | `02_Phase_15_External_Reference_Code_Audit_Report_EXACT.md` | 审计交付物（SHA 固定 + C1-C7 对照 + delta 判定）；其 T1-T5 分类已被 03 取代 |
| master plan | `03_Phase_15_Cognitive_Life_Finalization_Master_Plan_and_External_Delta_Decision_EXACT.md` | 权威执行计划：reviewer 裁决 + delta 终版集合 + 分支/文档协议 + 最终验收条件 |
| task brief (future) | `04_Phase_15_D1_Canon_Act_II_III_Official_Evidence_Task_Brief_EXACT.md` | D1 EXACT 任务书（待独立撰写，One bounded task at a time） |
| implementation report (future) | `05_..Closeout`、`06/07_D4`、…、`14/15_Integrated_Final_Gate` | 编号预留见 03 §15；被否决任务保留编号并在本清单记录取消 |

## Status

```text
Phase 14                = FINAL REVIEWER PASS / CODE FROZEN @ f8e84ec
Phase 15 External Audit = REVIEWED (PASS_WITH_RECLASSIFICATION)
Phase 15                = READY FOR BOUNDED FINALIZATION TASKS（等待 04 号 D1 任务书）
下一份文档              = 04_Phase_15_D1_Canon_Act_II_III_Official_Evidence_Task_Brief_EXACT.md
                          （须独立、狭窄地撰写；禁止 D1+D4+D2 合并为一个巨型编码任务）
```
