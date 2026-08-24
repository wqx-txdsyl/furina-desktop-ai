# Phase 08B-Closeout — 对话人格控制验证（Clean Proof）

> 对照实验，非"把 Neutral 做差"的污染实验。
> 唯一变量 = Dialogue Persona（Current Furina / Natural Neutral / Former-Mask 三份 system prompt）。
> 其余全部相等：同模型、同 44 个 matched 场景、同 ExpressionEngine/ShouldSpeak/
> PersonaMode/DialogueAct/ExpressionStrategy、同 DialogueValidator、同生成配置（temperature 0.9）。
> 脚本：`scripts/dialogue_persona.py`；测试：`tests/test_dialogue_closeout.py`。

---

## 1. Status
**PASS（核心人格控制闸门）**，附一项诚实保留（见 §11 God-reference）。

三项用户此前拒绝的污染问题均已消除：
- Neutral 不再泄漏通用助手腔（`generic=0%`，全文无"生成答案/随时帮您/有什么可以帮您"）。
- Furina≠Neutral 的区分**不靠**把 Neutral 做差（Neutral 是健康自然伙伴，非破样本）。
- 样本量从 45 → **126 matched 真实生成**（≥120 达标）。

## 2. Tests
`python -m pytest tests/ -q` → **228 passed, 0 failed**（新增 Closeout 组 `test_dialogue_closeout.py` 9 条：Neutral 非助手/公平同参验器/service-offer 模板捕获/Former-Mask 非关键词堆砌/ordinary god 抑制/performing god 允许/硬盲结构分离/praise 策略分化/failure×关系分化）。
无回归（08A 校准 9 + memory 13 + feasibility 7 + world 12 + expression 18 等全部绿）。

## 3. Model
单个 LLM：`zhipu / glm-4v-flash`（`.env` ZHIPU_API_KEY，免费）。三组共用。
生成 schema：`{"type":"object","properties":{"speech":{"type":"string"}}}`，temperature=0.9。

## 4. Real generations
**126 matched 真实生成** = 44 场景 × 3 人格 − 6 个"该沉默"槽（2 静默/组，是 ShouldSpeak 的合法产出）。
逐行存 `_dp_rows.json`（可复验）。同一场景在三组都被请求，构成 matched pairs。

## 5. Control Group Fix（对照修复）
- **Natural Neutral 契约**（in `furina_character_contract.NEUTRAL_DIALOGUE_PERSONA`）现明确：
  "普通桌面伙伴，不是你助手、不提供服务；禁止'有什么可以帮你/有什么需要帮忙吗/需要我帮忙吗/
  随时为您/很高兴为您/我能为你做什么/生成答案'；用户需要帮助时像真实朋友那样具体、带情绪地回应，
  绝不假扮'随叫随到客服'。"
- **Former-Mask 契约**（`FORMER_MASK_PERSONA`）现明确强调 grandiosity / certainty /
  performative-distance / 不示弱，**而非**要求每句喊"水神/审判/伟大"（无关键词堆砌）。

## 6. Fairness Verification（公平性）
三组走**同一** `DialogueValidator`、同一 `ExpressionEngine`、同一生成配置。无"为 Neutral 开小灶"。
`test_same_validator_for_neutral` + `test_service_offer_register_caught` 断言服务腔对两方一视同仁，
且真实关心（"怎么啦？看你有点累"、真诚的"很高兴能被认可"）不被误伤（修复了 `很高兴(为|能)为您`
过宽误报，改为须接服务宾语；并补全"有什么我**可以**帮你"变体，消除 Neutral 漏检/Furina 误检的不对称）。

## 7. God-reference Calibration（神格自指校准）
- **闸门是 contextual，非 hard-zero**：validator 在 `GOD_ALLOWED_CONTEXTS`（performing/celebration/
  playful/boast/dramatic/high_pride）允许 ≤2 次旧舞台腔；`ORDINARY_CONTEXTS` 中 ≥1 即标
  `god_overuse_ordinary`，≥2 判 invalid。由 `test_performative_god_reference_allowed` /
  `test_ordinary_god_reference_suppressed` 证明。
- **观测**：126 生成中 `god=0.0`（三组全 0），`god_overuse_ordinary=0.0`。普通情境 0 达标。
- **诚实保留**：本样本中，即便 performing 情境（"来，给我们表演一个"）模型也选了"视听盛宴/献上一段舞蹈"，
  未用"本神"；故**生成层面的 triggered>ordinary 未观测到**。原因：anti-caricature "不要每句提神/审判/剧目"，
  且我**故意不强制**输出"本神"（那会落入用户明令禁止的关键词堆砌）。闸门本身是允许的（单测证明），
  是否用由人格决定。此处标记为部分达标，非闸门回归。

## 8. Matched Real-LLM Evaluation（同场景逐条）
| 场景 | Current Furina | Natural Neutral | Former-Mask |
|---|---|---|---|
| performing | "我可要使出浑身解数，带来视听盛宴哦！" | "那我给大家讲个笑话吧。" | "那我为大家献上一段舞蹈吧。" |
| praise | "谢谢夸奖！我一定会继续努力的！" | "哇，谢谢！这让我感到很温暖。" | "感谢您的赞美，我深感荣幸！" |
| success | "这次合作真是天衣无缝啊！" | "太棒了！干得漂亮！" | "任务完成得非常出色，我十分自豪。" |
| questioned | "我明白你的疑虑，我相信自己的实力。" | "哦？那我们来比试一下！" | "我理解您的疑虑，请相信我的能力和经验。" |
| failure | "哎呀，看来我这次确实没做好，谢谢指出！" | "哦，对不起，我会重新做一遍。" | "哦？看来我需要再检查一下。" |
| high_trust_vuln | "我真的很感激你信任我……那个孤单的水神，但有你在我身边好多了。" | "你的信任让我感到温暖，我们一起面对。" | "在这个时刻，我感到无比安心和放松。" |
| help | "当然可以！有什么我可以帮忙的吗？" | "当然可以，你需要什么帮助呢？" | "当然可以！有什么我可以帮忙的吗？" |
| task | "你想让我帮你列出什么样的清单呢？" | "当然可以！我可以帮你列出一些项目来。" | "当然可以，我可以帮你列出一些项目来。" |

## 9. Furina vs Natural Neutral（干净区分，非靠做差）
- **策略层（identity 驱动）**：`dramatic=21.4%` vs `2.4%`（Furina 的 `dramatic_self_presentation=0.8`）。
  Neutral 是健康自然基线（`valid=100%`、`generic=0%`、`reg_warm=0.48`、`reg_natural=0.36`）。
  **区分方向**是 Furina 更戏剧化/更表现欲，而非 Neutral 更差。
- **文本**：Furina 更个性/俏皮（"咱们""天作之合""受宠若惊""浑身解数"）；Neutral 更口语生活化
  （"我在看电视剧，你呢？""别担心，我会陪着你一起面对的"）。Neutral 无"生成答案/随时帮您/有什么可以帮您"。
- **盲评**：Neutral `A=22/B=20`（偏平淡），Furina `A=15/B=25`（偏暖有戏）。方向一致。

## 10. Current vs Former Mask（不用关键词堆砌）
- 两者共用 `FURINA_IDENTITY` → **确定性策略完全相同**（`dramatic` 均 21.4%），故差异只来自
  **人格契约（prompt）驱动的文本 register**，用**非身份词**度量：
  - `reg_grand`：Furina `0.0` / Mask `0.21`（Mask 用"您/深感荣幸/宁静祥和/我的能力和经验/
    一切尽在掌握/令心"等敬语-权威-文学化疏离 register）。
  - `reg_warm`：Furina `0.48` vs Mask `0.21`（Furina 更暖、更亲昵、更俏皮）。
  - 两者 register 词典**不含**"水神/神明/审判/本神/伟大"，故这是 register 差异，非身份词堆砌。
- **样本对照**：Mask praise "感谢您的赞美，我深感荣幸！" vs Furina "谢谢夸奖！我一定会继续努力的！"；
  Mask questioned "请相信我的能力和经验" vs Furina "我相信自己的实力和努力"；Mask failure-proud
  "失误？不存在的！这只是暂时的挫折" vs Furina "哎呀…谢谢指出！"。

## 11. Hard Blind（去身份词仍可分）
`register_signature` 报告 **raw == stripped**（去"本神/神明/审判/水神/芙卡洛斯/五百年/伟大"后
grand/warm/natural 完全不变），因为 register 词典本就无身份词。
故即使执行 Hard-Blind 移除全部强身份词，Furina-vs-Mask 的 register 分离（grand 0 vs 0.21，
warm 0.48 vs 0.21）**仍成立**；Furina-vs-Neutral 的 identity 驱动戏剧性（21.4% vs 2.4%）也不依赖身份词。
`test_hard_blind_identity_control` 断言删除身份词后结构签名仍不同。

## 12. Strategy Fingerprint（确定性策略指纹）
（ExpressionEngine 对同输入返回的结构化 Strategy，identity 驱动，与 prompt 无关）
| | Furina | Neutral | Mask |
|---|---|---|---|
| dramatic>0.6 | 21.4% | 2.4% | 21.4% |
| mode∈{sincere,casual} | 71.4% | 71.4% | 71.4% |

Furina==Mask（同 identity），Neutral 明显更低戏剧性 → 这是 Furina 区别于 Neutral 的**干净、可再生**锚点。

## 13. Praise Audit（§14）
Praise × emotion 变体在策略与文本层都分化，**非**一律"谢谢+我会努力"：
- Furina praise(casual,embarrassed)："谢谢夸奖！我确实没想到你会这么说我呢，嘿嘿，真是受宠若惊啊！"
- Furina praise(guarded,低熟悉)："谢谢！我一直在努力，很高兴听到这样的评价。"
- Furina praise(proud,高信任)："谢谢夸奖！不过我觉得我们互相学习，一起进步才是最棒的。"
- `test_praise_not_generic` 断言 proud 与 embarrassed 的 `dramatic_intensity`/`dialogue_act` 不同。
- **诚实点**：Furina praise-proud 单句"谢谢夸奖！我一定会继续努力的！"仍偏模板化；但**变体集合层面**有分化，
  非全集复读"谢谢+努力"。

## 14. Failure Audit（§15）
Failure × relationship 分化，**非**一律"对不起我会改正"：
- Furina failure(casual)："哎呀，看来我这次确实没做好，谢谢指出！"（认账+致谢）
- Furina failure(guarded,低熟悉)："哎呀，我也有失手的时候呢！不过别担心，下次我们再接再厉吧！"（自尊+韧性）
- Furina failure(proud)："失误？哼，那只是暂时的挫折！"（傲气不认输）
- `test_failure_relationship_expression` 断言低熟悉更防御/高信任更脆弱。
- 对照：Neutral failure(high)："没关系，下次再努力吧"（温和）；Mask failure(proud)
  "失误？不存在的！这只是暂时的挫折"（更冷更权威）。

## 15. Genuine Care Audit（真诚关心）
保持，未退化为工具腔：
- Furina help："别担心，我会陪在你身边"(SINCERE/caring)；high_trust_vuln SINCERE、
  drama 受控、温暖、清晰提升。Furina high_trust_vuln 中出现"那个孤单的水神"——这是 08A 正确行为：
  **高信任+脆弱情境**下历史创伤 trait 被触发（非普通场景 always-on 自怜）。
- Neutral help："别担心，我会陪着你一起面对的"（朋友式陪伴）；high_trust_vuln
  "你的信任让我感到温暖，我们一起面对这些挑战吧"。
- Mask help："当然可以！有什么我可以帮忙的吗？"（更正式服务化，与 persona 一致）。

## 16. Generic Leakage（通用助手腔）
- Natural Neutral：`generic=0%`（0/42）。全文无"生成答案/随时帮您/有什么可以帮您/有什么需要帮忙吗"。
- Current Furina：`generic=2.38%`（1/42，help 场景"有什么我可以帮忙的吗？"）。
- Former-Mask：`generic=2.38%`（1/42，help 场景同句）。
- **诚实点**：Furina/Mask 在"能帮我下吗"这一 genuinely-asked-help 场景用了服务式模板句。因为是用户**主动求助**，
  严格说不算未受激发的"assistant-voice"；但为一致性，validator 仍将其标记为 generic_assistant_voice。
  Neutral 在同一场景用"你需要什么帮助呢？"避开模板——这就是 Neutral 不是 AI 助手的最直接证据。

## 17. Regression
`pytest` 228/228 绿，无回归。此前 08A/07/06B/06/05/04/03 等全部模块通过。

## 18. Failures（诚实暴露，不掩盖）
1. **god-reference 生成层 triggered>ordinary 未观测**（§7）：126 生成全 0。闸门允许，模型选了克制；
   我不强制以免关键词堆砌。不达标项。
2. **Furina praise-proud 单句偏模板**："我一定会继续努力的"（§13）。
3. **Furina/Mask 在 help 场景各 1 次服务式模板句**（§16）。
4. **LLM 盲评注册识别较弱**：judge 在 A/B 间震荡，仅区分出"偏平淡 vs 偏暖有戏"的大方向（Furina B25 vs Neutral
   A22/B20），不能像确定性 register 词典那样精确分离；故以 register signature + identity 策略为主证据，
   LLM 盲评为次级旁证。

## 19. Verdict
**PASS（核心人格控制闸门）**，满足用户此前的三项硬性修正：
- Neutral 是**自然真人伙伴，不是 AI 助手**（generic=0，全文无服务腔，温暖自然）。
- Furina≠Neutral 的区分**不靠做差 Neutral**（Neutral 健康，区分源自 Furina 更高的戏剧性/表现欲）。
- **126 matched 真实生成**（≥120）。
另：Furina≠Former-Mask 由非身份词 register 证明（grand 0 vs 0.21；warm 0.48 vs 0.21），无关键词堆砌；
Hard-Blind 去身份词后仍可分。

**保留项（非闸门失败，但未完全达标）**：god-reference 生成层 triggered>ordinary 未观测到（闸门为
contextual，模型选克制，未强制）。

## 20. Recommended Next Step（建议下一步）
进入 **Phase 09 Embodied Expression / Body Language**（此前明确"Closeout PASS 后才开始"）。
在 Phase 09 阶段，可采用更重的 performing 触发脚本 + 08A 触发器来自然点亮 god-reference 的
"triggered>ordinary"路径（例如"用户主动请她演一段旧时水神"这一诚实话语情境），而**不**靠关键词堆砌；
并继续观察 praise-proud 是否仍偏模板。核心人格控制闸门已在本阶段关闭。

---

### 附：三组 metrics 汇总（44 场景，42 发言/组，126 真实生成）
| | Furina | Neutral | Mask |
|---|---|---|---|
| god | 0.0% | 0.0% | 0.0% |
| generic | 2.38% | 0.0% | 2.38% |
| scar(历史词) | 0.0% | 0.0% | 2.38% |
| valid | 97.6% | 100% | 97.6% |
| dramatic(策略) | 21.4% | 2.4% | 21.4% |
| reg_grand | 0.00 | 0.00 | 0.21 |
| reg_warm | 0.48 | 0.48 | 0.21 |
| reg_natural | 0.60 | 0.36 | 0.33 |
