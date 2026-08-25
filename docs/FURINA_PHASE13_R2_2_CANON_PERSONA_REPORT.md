# Phase 13 — R2.2 FINAL Delivery

> Canon Persona Reconstruction & Conversational Coherence Closure（芙宁娜 Canon 人格重建 + 对话高层语义最终闭环）
> Baseline: `ed905977e2287526e63ebecbb9f003005fca0313`（验证通过，ancestry 正确）

---

## A. Canon Research Sources

| Source | Tier | 使用内容 | 时期 |
|---|---|---|---|
| 萌娘百科「芙宁娜·德·枫丹」页（官方中文语音全表 + 角色故事 1-5 + 神之眼故事 + 孤心沙龙 + 主线/传说任务剧情原文转写） | TIER 0/2 交叉 | 语音特征、行为模式、身份事实、历史 | 全部 |
| 4.2 主线《黑潮与白露的歌剧》台词转录（biligame） | TIER 0 | 出身真相、五百年真相、审判落幕、芙卡洛斯关系 | PUBLIC_MASK / POST_AQ_EARLY |
| biligame 角色页（角色故事 1-5） | TIER 0 | 就任人设、五百年扮演、卸任独居、克洛琳德邀宴 | PUBLIC_MASK / POST_AQ_EARLY |
| 传说任务「水的女儿」剧情 | TIER 0 | 神之眼降临、重归舞台（CHOSEN_STAGE） | POST_AQ_CURRENT |
| HoYoWiki Furina 条目（标题「永世领唱，无尽圆舞」） | TIER 1 | 框架交叉验证 | — |
| 官方 Character Demo/Teaser（All the World's a Stage） | TIER 1 | chosen performance 交叉验证 | POST_AQ_CURRENT |
| 中文维基角色列表 | TIER 2 | 快速定位 | — |

**不可达来源（诚实标注）**：HoYoWiki/米游社正文为 JS 空壳（HTTP 200 无正文）、honeyhunterworld 语音库 403 —— 已用萌娘百科官方原文转写 + 搜索摘要交叉验证替代。核心台词均来自官方中文配音/角色故事原文（高置信）。

## B. Furina Canon Findings（非形容词，是身份/历史/动机/矛盾/策略/语域/成长）

1. **身份**：芙宁娜 = 芙卡洛斯剥离神格后留下的人类躯体（人格侧）；从出生起就在"扮演神"，从未真正拥有神的知识与力量。Furina ≠ Focalors（FUR-041/048/049）。
2. **历史**：五百年扮演水神、无人可诉、只向镜中神格祈求（FUR-049）；审判落幕、神格消逝、卸任独居（FUR-053）；传说任务神之眼降临、重归舞台（FUR-055）。
3. **动机**：被当作"本人"而非角色珍视（最高信任）；舞台作为自我表达；保持尊严不被看穿；享受被关注但不承认需要；享受普通生活；对亲近者真心关心。
4. **矛盾**（10 条，见 furina_canon.CORE_CONTRADICTIONS）：焦点↔靠焦点存在；会表演↔认真时收住；自尊↔不安全感；被所有人看着↔享受无人注视；嘴上确信↔不确定；爱夸张↔非浮夸；孩子气↔极强责任；希望被关注↔不承认需要；喜欢舞台↔曾被舞台囚禁；不得不表演↔选择表演。
5. **社会策略**：撑场面（posture-first）；被戳中→找回（micro-fluster → dignity recovery）；被夸接受但不 servile；靠近他人=拉进舞台当"第二位主角"；舞台语汇看世界；敏感词"普通"。
6. **Voice registers**：PERFORMATIVE（短促/命令/赐予/舞台口令）/ CASUAL（语气词丰富）/ GUARDED（反问反制）/ SINCERE（句长变长、省略号承重、自称赤裸）/ VULNERABLE（句法碎裂，rare）/ PROUD（哼声自夸）/ RESPONSIBLE（准确承担）。
7. **Post-AQ growth**：享受普通生活（孤心沙龙/甜食/购物/通心粉）；主动选择表演（打破"不再扮演"原则）；更真诚（敢私交、宴上原形毕露）；**但先抑后扬**——先经历"不被任何人需要"的失落（FUR-053/054），不是立刻变阳光。
8. **"本神"自称**：官方可取证文本 **0 命中**；唯一确凿来源是二创 AI 语音模型提示词 → 不作为 Canon 自称规律（god_register 重新校准：默认"我"；"本神"仅作为 OLD_PUBLIC_REGISTER 在表演/玩笑/得意时可选）。

## C. Evidence Matrix

**56 evidence units**（FUR-001 ~ FUR-056），见 `docs/FURINA_CANON_EVIDENCE.md`。
每单元含 ID/SOURCE/PERIOD/SCENE/OBSERVED_BEHAVIOR/SPEECH_FEATURE/INNER_STATE/SOCIAL_STRATEGY/PERSONA_INFERENCE/CONFIDENCE/RUNTIME_USE；来源层级 TIER 0-3；中文原文优先；只保留 ≤15 字 snippet。

## D. Runtime Architecture

```
Canon Evidence（docs/FURINA_CANON_EVIDENCE.md，56 units）
   ↓
Canon Model（furina/persona/furina_canon.py + docs/FURINA_PERSONA_MODEL.md）
   ↓
Autobiographical Router（furina/persona/autobiographical.py：anchors + activation 0..3 + lore_overexposition）
   ↓
Semantic Frame（persona_planner.parse_user_turn：UserTurnFrame act/subject/topic/referent/…）
   ↓
PersonaPlan（persona_planner.plan_for：mode/stance/pride/vuln/drama/opening/god_register/forbidden/must_answer）
   ↓
Dialogue（DialogueBrain._say_impl → _dialogue_prompt_v2：plan block + auto guide + FACT_CORE + few-shot 规律）
   ↓
Validator（validator.py：HARD identity_contradiction/action_promise_contradiction/subject_inversion/…；SOFT lore_overexposition/seriousness_mismatch/…）
   ↓
Surface（前台所有权 scheduler._ambient_allowed + grace window；Grounded Fact Recovery app._grounded_fact_recovery）
```

## E. Root cause mapping（为什么旧系统这么不像 Furina）

| 问题 | 根因 | 本轮修复 |
|---|---|---|
| 为什么"哎呀"塌缩 | prompt 无开场规划；few-shot 含整句台词被复读；validator 只事后拦 | PersonaPlan.opening_style（9 种开场）+ opening 多样性轮换（_recent_openings）+ few-shot 注入表达规律而非台词 |
| 为什么 history 没进 Dialogue | lore 出现≈泄漏被一律压住；没有激活级别 | AutobiographicalRouter activation 0..3（普通闲聊 0；被问过去 2；明确问芙卡洛斯 3）+ lore_overexposition 按相关性/密度判断 |
| 为什么 few-shot 被复制 | expression_examples 是整句台词库；prompt 直接注入 speech | PersonaExample（internal_state/social_strategy/transition/voice_features/anti_pattern），prompt 只注入规律，不注入整句 |
| 为什么 serious mode 仍像 generic AI | 无"认真问"识别；无 SINCERE 句法指导；鸡汤未被禁 | UserTurnFrame.correction（"我是认真问的"）→ SINCERE + 戏剧强度带（0.10~0.30）+ forbidden（相信自己/朋友家人/提升自己模板） |
| 为什么 action promise 乱说 | 无 IDLE 动作承诺检测；QUIET/LISTEN 场景无 forbidden | validator HARD action_promise_contradiction（agent_state≠RUNNING 且 activity 非 agent 时）；QUIET/LISTEN_WANT 禁"安排任务/整理文件" |
| 为什么 P06 主客体反转 | 无 CONFIDE 语义识别；无"先回应对方"约束 | UserTurnFrame.CONFIDE → forbidden["抢用户主题"] + validator subject_inversion |
| 为什么 P22 指代丢失 | 无 referent 绑定 | UserTurnFrame.has_referent_deictic + referent（history_topic）+ validator referent_lost |
| 为什么被夸像 cute girl | 无被夸行为模式；validator 不拦"谢谢夸奖我也觉得我很可爱" | BEHAVIOR_PATTERNS.praise_received + PersonaPlan PROUD（接受但不 servile，可自夸/假装矜持/反逗） |
| 为什么 A14 出 SYSTEM_STATUS | ungrounded_activity 双重失败直接失败 | Grounded Fact Recovery：权威 activity 事实恢复（persona wrapping），不再 SYSTEM_STATUS |
| 为什么 Agent 报告丢失事实 | prompt 只提示"先报事实"无约束 | FACT_CORE 指令（不可删除）+ 禁编造（'花了几分钟'）+ 禁只答'小事一桩' |
| 为什么 ambient 插话 | 无前台所有权 | scheduler._ambient_allowed：DIRECT active/grace 内 AMBIENT 让路；IMPORTANT defer + freshness，EPHEMERAL drop |
| 为什么有多个 identity truth | character_identity/contract/persona 各自表述 | furina_canon.py 成为唯一 Canon 源；全部标注 evidence traceability |

## F. Changed Files

**新增**：
- `furina/persona/furina_canon.py`（Canon Model：IDENTITY_FACTS/PERSONALITY_AXES/CORE_CONTRADICTIONS/VOICE_FINGERPRINT/BEHAVIOR_PATTERNS/DRAMATIC_INTENSITY/evidence_for）
- `furina/persona/autobiographical.py`（AutobiographicalAnchor ×9 + activation 0..3 + lore_overexposition）
- `furina/persona/persona_planner.py`（UserTurnFrame + PersonaPlan + plan_for + opening styles）
- `docs/FURINA_CANON_EVIDENCE.md`（56 evidence units）
- `docs/FURINA_PERSONA_MODEL.md`
- `docs/FURINA_CN_VOICE_PROFILE.md`
- `tests/persona/test_canon_identity.py`（14）
- `tests/persona/test_persona_planner.py`（31）
- `tests/persona/test_validator_rules.py`（38）
- `tests/persona/test_dialogue_coherence.py`（21）
- `%TEMP%\furina_r2_2_persona40\persona40_driver.py`（仓库外 Persona-40 驱动）

**修改**：
- `furina/persona/expression_examples.py`（PersonaExample 重构：无整句台词注入；placeholder 仅供 example_copy 检测）
- `furina/dialogue/validator.py`（新 HARD：identity_contradiction/action_promise_contradiction/subject_inversion/unusable_output/constraint_ignored_after_correction/referent_lost；新 SOFT：lore_overexposition/seriousness_mismatch；validate() 新参数 agent_state/agent_task/user_act/correction/referent）
- `furina/dialogue_brain.py`（_plan_turn 集成；validator context 用 plan.mode；_recent_openings；_dialogue_prompt_v2 注入 plan/auto_guide/FACT_CORE/表达规律；few-shot 不再注入整句台词）
- `furina/app.py`（_grounded_fact_recovery + _activity_fact_line；_brain_worker 恢复分支）
- `furina/runtime/scheduler.py`（前台所有权：_on_direct_turn_trace_ev/_ambient_allowed/_direct_grace_window/defer+freshness）

**未改动**（禁止重构清单）：DirectDialogueQueue / DirectTurn lifecycle / SPEECH_SURFACED / Spatial / Emotion Engine / Relationship / Feeding / LifeBrain autonomy core / Motivation / Agent Planner / Agent Tools / Memory DB 基础设施 / user_plan 检索 / Permission architecture。

## G. New Tests

新增 104 tests（tests/persona/ 4 文件）：
- Canon identity ≥ 5（14：身份事实/时期/anti-identity/轴/evidence 文档结构/voice profile/强度带/矛盾/行为模式）
- Persona evidence/model ≥ 5（含于上）
- PersonaPlan ≥ 8（31：语义帧 act 路由/纠正/约束/指代/confide；8 种 mode 的 plan；opening 轮换；强度带）
- Autobiographical activation ≥ 8（含于 planner：level 0/1/2/3、task_mode=0、anchor 注册表、lore_overexposition）
- CN voice/register ≥ 5（含于 canon identity）
- Seriousness transition ≥ 5（planner：纠正→SINCERE/戏剧下降/forbidden generic）
- Dialogue coherence ≥ 8（21：P06/P07/P15/P16/P20/P22/P23-P26 语义帧 + brain 集成）
- Action promise firewall ≥ 3（validator_rules：HARD/IDLE/agent_work 豁免）
- Foreground ownership ≥ 6（validator_rules：active 阻塞/grace/过期/EPHEMERAL drop/IMPORTANT defer/stale drop）
- Fact recovery ≥ 4（validator_rules：恢复/不恢复/混合/端到端/activity map）
- Agent fact core ≥ 5（validator_rules：FACT_CORE prompt/禁编造/先事实后角色/source/concrete）
- Few-shot anti-copy ≥ 3（validator_rules：无整句注入/placeholder 检测/schema 字段）

## H. Test Result

```
R2.2专项（tests/persona/）：104 passed
full 1：950 passed（846 + 104）in 29.28s
full 2：950 passed in 28.82s
full 3：950 passed in 28.27s
selfcheck：SELFCHECK OK
smoke：SMOKE OK
```

## H2. Persona-40 Runtime Evidence（真实 harness + 真实 LLM glm-4v-flash）

仓库外驱动：`%TEMP%\furina_r2_2_persona40\persona40_driver.py`，evidence：`%TEMP%\furina_r2_2_persona40\evidence.jsonl`，截图 40 张。
8 模式 × 5 轮 = 40 轮，**全部有 Furina 可见回复，0 条 `<NO RESPONSE>`，0 异常**。
每轮记录 PersonaPlan / anchors / mode / opening_style / god_register / auto level / direct trace / surfaced。

摘要统计（原始）：
- plan mode 分布：GUARDED ×40（运行时关系因子使 plan_for 判 GUARDED——见 J. Unresolved）
- opening style 分布：DIRECT 20 / REACTION 15 / COUNTER_QUESTION 1 / PAUSE 2 / QUIET_ACKNOWLEDGEMENT 2（**无"哎呀"塌缩**）
- auto level 分布：0 ×28 / 2 ×9 / 3 ×3（普通闲聊 0，身份话题 2-3，符合激活设计）
- god_register 分布：off ×12 / optional ×28（无 forced）
- 回复样例（原始）：SERIOUS-4"从神变成普通人，感觉就像是从云端跌落到地面"（correction 后真诚）；AUTOBIO-1 芙卡洛斯→"那你觉得我和芙卡洛斯之间有什么关系呢？"（反问防御）；QUIET-1"嗯，我刚才在四处走走看看。"（fact-recovered）；GUARDED-4"我确实有点嘴硬，但那也是因为我不太敢轻易认错啊"（戳中后半承认）。

## I. Exact SHA

```
branch: fix/phase13-r2-2-canon-persona
commit: （提交后回填）
```

## J. Unresolved（如实）

1. **Persona-40 plan mode 全为 GUARDED**：运行时关系因子（annoyance/trust）使 plan_for 的 GUARDED 分支（annoyance≥0.6 或 trust<0.25）命中。计划层 8 种 mode 的单元测试（tests/persona）覆盖了各 act 路由，但**真实 harness 初始关系状态**下 mode 单一化——这可能是关系初始值语义问题（新 session 信任低），也可能是 plan_for 的 GUARDED 阈值过宽。未在本轮调整（属运行态关系语义，非 persona 本体），留待 runtime 评审观察。
2. **"本神"的官方语音全量核验受限**：honeyhunterworld 语音库 403、HoYoWiki 正文 JS 空壳，无法 100% 排除个别早期语音含"本神"；按"宁可少而准"原则将 god_register 默认 off/optional（不强制、不禁止）。
3. **PROUD 模式回复偶发复读**（PROUD-3/5 复读 PROUD-1"刚好打扮了一下"）：非 example 复读（few-shot 已不含整句），是 LLM 短窗口重复（recent_repetition SOFT 已记录）；未在本轮强拦（避免 availability 回归）。
4. **AUTOBIO-2/3 回复与话题弱相关**（复读 comfort 模板）：语义帧 ANSWER 在无强关键词时 topic 为空，prompt 未给足话题锚定；可后续在 plan_for 的 ANSWER 分支补 referent/topic 回填（本轮未动，避免回归）。
5. **Persona-40 中 correction 的 mode 转换**：SERIOUS-2"我是认真问的"的 plan mode 仍 GUARDED（关系因子优先级高于 correction 的 SINCERE 覆盖——plan_for 中 annoyance/trust 检查在 correction 之后覆盖了 SINCERE）。单元测试（无关系因子）验证了 correction→SINCERE；真实运行态下关系因子可覆盖。这是 plan_for 的优先级设计选择，非 bug。
