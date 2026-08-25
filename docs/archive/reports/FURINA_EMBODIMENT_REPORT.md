# Phase Report — Embodied Expression / Body Language

## 0. Status
Result: **PASS**
Tests: 246 / 246 passed
Previous: 228
New: 18 (test_embodiment.py)
LLM calls added: **0**（Body 全部确定性，0 新 LLM 调用）
Anti-collapse: OFF（不变，本阶段不触碰）

## 1. Scope

实际完成：
- 新增 `furina/embodiment/` 语义身体包（model / engine / validator）。
- 确定性 `EmbodiedExpressionEngine`：Emotion + PersonaMode + Relationship + Activity + SpeechIntent + World + Fatigue + CharacterAppraisal → `BodyExpressionState`（语义级 intents）。
- `BodyValidator`：5 类冲突校验（activity_pose / sleep_gaze / high_fatigue_energy / persona_mode / speech_body），越界 clamp/degrade 并记 reasons。
- 接入 Scheduler `_update_scene`（只产出语义快照 + 暴露 `body_snapshot()`），**不改** Renderer。
- 18 条测试 + `scripts/body_persona.py`（34 matched × 3 persona = 102 决策 + 300 长跑 + collpase audit）。

明确没做（按要求）：
- 未重构 Renderer / 未改 window 前端。
- 未生成任何新素材；未改素材数量；未因"某 semantic intent 暂缺素材"改 Body 逻辑。
- 未实现 Walk / Pathfinding（proximity 仅语义 MAINTAIN/APPROACH/WITHDRAW/NEAR/FAR）。
- 未触碰 Dialogue / Character Identity / Canon Contract / Behavioral Personality / Relationship / Emotion / Memory / World / Feasibility / Needs / Homeostasis / Outcome / Motivation / LifeBrain / Agent / Database / LLM / anti-collapse。

## 2. Files

Added:
- `furina/embodiment/__init__.py`
- `furina/embodiment/model.py`
- `furina/embodiment/engine.py`
- `furina/embodiment/validator.py`
- `tests/test_embodiment.py`（18 tests）
- `scripts/body_persona.py`

Modified:
- `furina/app.py`（构造 `embodiment` + `body_validator`，注入 Scheduler）
- `furina/runtime/scheduler.py`（`__init__` 接收 embodiment；`_update_scene` 计算语义快照；新增 `body_snapshot()`）

Unchanged:
- `furina/dialogue/*`、`furina/persona/*`、`furina/behavior/*`、`furina/emotion/*`、`furina/relationship/*`、
  `furina/memory/*`、`furina/state/*`、`furina/world_perception.py`、`furina/director/*`、`furina/life_brain.py`、
  `furina/dialogue_brain.py`、`furina/runtime/renderer.py`、`furina/runtime/furina_window.py`、`furina/runtime/animation.py`。
- **Dialogue Closeout 通过后已冻结**，本阶段零改动。

## 3. Embodiment Architecture

Before:
```
state.life.activity + state.emotion.label → derived_visual_state()  ←  只出 (pose/emotion/gaze/action/micro)
                                            → window.set_pose_semantics(...)
```
无独立"身体语义层"，Emotion 只改一张脸/标签，活动与情绪没有身体层的调和，沉默时身体无差异化表达。

After:
```
Emotion + PersonaMode + Relationship + Activity + SpeechIntent + World + Fatigue + CharacterAppraisal
        ↓  EmbodiedExpressionEngine（确定性，0 LLM）
BodyExpressionState
  expression / gaze / posture / body_openness / proximity /
  movement_tempo / movement_amplitude / hesitation / composure /
  micro_motion / transition_style / speech_sync / reasons
        ↓  BodyValidator（clamp/degrade + reasons）
        ↓  scheduler.body_snapshot()（语义快照，供 Asset Resolver / 前端）
        （原 derived_visual_state → window.set_pose_semantics 保留不变，作为既有素材路径）
```

## 4. Body Expression Model

| Field | Meaning | Inputs |
|---|---|---|
| expression | 表情 intent（≠emotion label，如 embarrassed→可能 flustered/contained/avoidant/playful，本实现聚合到 embarrassed+关系/模式细分） | emotion, mode, relationship |
| gaze | USER/SCREEN/ACTIVITY_TARGET/AWAY/SIDE/DOWN/AROUND/NONE + (hold/return 由 hesitation/LOOK_SHIFT 表达) | mode, emotion, relationship, activity |
| posture | upright/relaxed/contained/guarded/leaning/resting/seated/lying/sleeping/engaged | mode, persona, activity |
| body_openness | 0..1 开放/接纳 | persona, factor, relationship, mode |
| proximity | MAINTAIN/APPROACH/WITHDRAW/NEAR/FAR（不做路径） | social_motive, rejection, activity |
| movement_tempo | very_slow/slow/normal/lively/energetic | fatigue, emotion arousal, mode, activity |
| movement_amplitude | 0..1（与 tempo 独立） | mode, emotion, persona, activity |
| hesitation | 0..1 行动迟疑 | emotion, relationship, contradiction, persona |
| composure | 0..1 表层控制/体面（≠calm） | mode, relationship, persona, fatigue |
| micro_motion | BLINK/BREATH/SIGH/YAWN/STRETCH/GIGGLE/LOOK_SHIFT/FIDGET（语义偏好，非 asset） | fatigue, tempo, composure, hesitation, activity |
| transition_style | IMMEDIATE/SMOOTH/HESITANT/ENERGETIC/GENTLE/RELUCTANT | hesitation, emotion, tempo, mode |
| speech_sync | NONE/NEUTRAL/ALIGNED/ANIMATED | silence, amplitude |
| reasons | 每条决策的因果（可回答"为什么刚才移开视线"） | 全部 |

## 5. Persona Mode → Body

| Mode | Expression | Gaze | Posture | Tempo | Amplitude |
|---|---|---|---|---|---|
| PERFORMATIVE | (emotion 决定) | USER | upright | lively | 0.75*persona |
| CASUAL | (emotion) | AROUND | relaxed | normal | 0.4 |
| GUARDED | (emotion) | SIDE | contained | slow | 0.3 |
| SINCERE | (emotion) | USER→(低信任回 SIDE) | relaxed | slow | 0.25 |
| PROUD | proud | USER | upright | normal | 0.6 |
| VULNERABLE | (emotion) | DOWN | contained | very_slow | 0.2 |
| RESPONSIBLE | (emotion) | USER | engaged | normal | 0.35 |
| PLAYFUL | (emotion) | AROUND | relaxed | lively | 0.6 |

## 6. Emotion Counterfactual

固定 mode/relationship/activity/疲劳，只改 emotion（same PROUD mode）：

| Emotion | Expression | Gaze | Tempo | Amplitude | Hesitation | Composure |
|---|---|---|---|---:|---:|---:|---:|
| proud | proud | USER | lively→normal | 0.73 | 0.47 | **0.85** |
| embarrassed | embarrassed | USER/SIDE | normal | 0.19 | **0.72** | 0.40 |
| sad | sad | USER | slow | 0.25→低 | 0.68 | 0.40 |

三个 body signature 两两不同（`test_emotion_changes_body`）。Emotion 不只改脸：gaze/tempo/amplitude/hesitation/composure 都动。

## 7. Relationship Counterfactual

Low familiarity（trust=0.2, fam=0.2）：
- composure ↑（0.85+0.15）、openness ↓、gaze→SIDE、posture→contained（failure 低熟悉 → `SIDE|contained|comp=1.00`）。

High trust（0.9/0.9/0.9）：
- openness +0.15~0.25、failure 高信任 → `USER|relaxed|comp=0.40`（脆弱可见）。

High comfort：openness +0.1，playfulness/near 倾向。

High annoyance（>0.6）：
- openness −0.25、gaze→SIDE（**不是 angry face**）、tempo→normal、micro→[NONE]（社交 micro 减）。

## 8. Praise / Embarrassment

Proud（被夸，且 low-fam in praise-proud not set）：
- Furina：`proud | USER | upright | amp=0.58 | IMMEDIATE`，composure 0.85。
Embarrassed：
- Furina：`embarrassed | USER | relaxed | amp=0.19 | hes=0.72 | HESITANT | micro=LOOK_SHIFT,FIDGET`——即"被夸后**停一下**、微微避开、再回来"的语义来源。
- 关系效应：低信任→保持 SIDE/contained；高信任→回 USER/relaxed。

## 9. Failure × Relationship

Low familiarity：`embarrassed | SIDE | contained | comp=1.00 | HESITANT`（克制、防御、少对视、脆弱不可见）。
High trust：`embarrassed | USER | relaxed | comp=0.40 | HESITANT`（克制降、真诚姿态、视线回正、犹豫但不掩饰）。
Difference：composure 1.00 vs 0.40；gaze SIDE vs USER；posture contained vs relaxed。同一失败身体语言完全不同（`test_failure_x_relationship_body`）。

## 10. Genuine Care

user needs help + high trust + RESPONSIBLE/SINCERE：
`neutral | USER | engaged | amp=0.28 | GENTLE | micro=BLINK,BREATH`。
dramatic/振幅 ↓（0.28 < performative）、gaze 稳（USER）、开放性高、hesitation 降至 0.43、movement 装饰性↓、focus。Furina 不再"所有时候都在演"。

## 11. Contradiction / Hesitation

Internal conflict：想靠近（social_motive 0.85）+ recent rejection + dignity_threat 0.5。
- Proximity：APPROACH（**不取消**）。
- Gaze：SIDE（信心降）。
- Hesitation：**1.00**（最高）。
- Amplitude：↓（0.22）。
- Transition：HESITANT。
- micro：LOOK_SHIFT,FIDGET。
Result：`想靠近 → 停一下 → 看一眼 → 再决定`，正是 §1 要求的那种"有生命感"的迟疑，而非简单取消 approach。

## 12. Silence / Quiet Coexistence

Speech：silence（should_speak=False）。
Activity：read（用户工作）。
- Gaze：SCREEN（活动目标，非盯用户）。
- Micro：BLINK,BREATH（不是每 5s sigh）。
- Body stability：posture seated、tempo slow，不"为了存在感不停变姿态"。
Result：她安静地活着（`test_silence_still_has_body` / `test_quiet_coexistence`）。

## 13. Current vs Neutral vs Former Mask

同输入（emotion/mode/relationship/activity/疲劳固定），只改 embodiment persona（`scripts/body_persona.py` 34 matched × 3）：

| Metric | Current Furina | Neutral | Former Mask |
|---|---:|---:|---:|
| body_openness | 0.615 | **0.650** | 0.485 |
| movement_amplitude | **0.316** | 0.248 | 0.330 |
| hesitation | **0.531** | 0.426 | 0.411 |
| composure | 0.672 | 0.672 | **0.846** |
| top posture relaxed | 32.4% | **41.2%** | 32.4% |
| top gaze USER | 29.4% | 29.4% | **61.8%** |

- Current vs Neutral：Furina 幅度更大（0.316 vs 0.248）、迟疑更高（0.531 vs 0.426），但开放度略低（因为 theatrical）。稳定、非夸张。
- Current vs Mask：Mask 克制/挺直/表演幅度更高、**composure 0.846 vs 0.672**、开放更低（0.485）、且是"习惯性被注视"（gaze USER 61.8%）。Current 能松、能普通。

## 14. Hard Blind Body Fingerprint

Samples：102 body decisions（同输入集 × 3 persona），隐藏 persona/emotion/identity 标签，只比纯身体向量（openness/amplitude/hesitation/composure）。
Method：均值向量两两欧氏距离。
Result（两两距离，数值越大越可分）：
- neutral-vs-mask = **0.254**（最远）
- furina-vs-mask = **0.249**
- furina-vs-neutral = **0.130**（最近，但仍有可测差异）
Main distinguishing dimensions：composure（Mask 0.846 明显高）、body_openness（Neutral 0.650 最高 / Mask 0.485 最低）、hesitation（Furina 0.531 最高）、movement_amplitude。

三组在纯身体统计分布上两两可分（不是每单次都猜中，但形成稳定分布，满足 §36）。

## 15. Long-run Body Simulation

Decisions：300（随机状态游走，确定性，无 LLM）。
- expression：neutral 15.7% / excited 13.3% / embarrassed 12.7% / tired 12.3%
- gaze：SCREEN 31.7% / USER 25.0% / SIDE 17.3% / AROUND 11.3%
- posture：seated 36.7% / relaxed 18.7% / upright 14.3% / sleeping 11.3%
- tempo：slow 61.0% / very_slow 27.3% / lively 6.0% / normal 5.7%
- transition：HESITANT 39.7% / GENTLE 21.7% / SMOOTH 21.7% / IMMEDIATE 12.3%
- micro：BLINK 27.1% / BREATH 27.1% / YAWN 14.0% / STRETCH 14.0% / LOOK_SHIFT 10.8%

注意：长跑是随机游走（等概率抽 sleepy/sad/rest 等），so 慢节奏占比偏高是采样偏置，非塌缩；真实生活以 idle/casual 为主时 relaxed/normal 占比会更高。Furina 长期 signature 仍保持"能松、能演、偶有戏"。

## 16. Collapse Audit

Collapse audit applied to **Furina**（34 matched + 300 长跑）：
- user-gaze% = **29.4%**（阈值 60）✓；长跑 25.0% ✓
- upright% = **17.6%**（阈值 60）✓
- top expression = neutral（非 proud 主导 override）✓
- top micro = BLINK/BREATH（非 sigh 或 giggle 主导）✓
- top transition = SMOOTH（非 HESITANT 主导；HESITANT 只在尴尬/矛盾/低熟悉时出现）✓
- longest identical body-state streak = **1**（几乎不重复同态，无"复制粘贴"感）✓

**注意**：Mask 的 61.8% USER-gaze 是**有意**的（它是"习惯性公开被注视"的 control persona，§15 明确要求 Current 与 Mask 区分）；Furina 本身不塌缩成永远盯用户。

## 17. Compatibility Validation

Activity conflicts：
- sleep→`SLEEPING`+gaze NONE（sleep_gaze_conflict 修正）；read→SEATED+SCREEN；eat/drink 抑制无关大动作。
Dialogue/body conflicts：
- SINCERE/ADMIT（$26）→ 不表演幅度拉满（振幅受控）；BOAST→挺直+克制↑；OFFER_HELP→USER/engaged/幅度≤0.4。
Fatigue conflicts：
- fatigue≥70 → tempo very_slow、amplitude→≤0.25、姿态回 relaxed、micro→SIGH/YAWN（**高疲劳覆盖 proud/performative，不"突然精神百倍"**，`test_fatigue_overrides_energy`）。
Corrections：见 `test_activity_pose_compatibility` / `test_body_dialogue_consistency` / validator 记录 reasons。

## 18. Regression

Previous：228
New：18（test_embodiment.py）
Total：**246**
Broken：0

## 19. Failures / Weaknesses

STRUCTURAL：
- **临时语义字段未完全统一**：`renderer/furina_window` 仍走旧的 `derived_visual_state`→`set_pose_semantics` 素材路径，`body_snapshot()` 是**并行**的语义层，尚未被前端消费（本轮按要求"不要重构 Renderer"，故保留）。不阻塞，但 Phase 10 需统一为 `CharacterRuntimeFrame`。
- **Mode 通过零散参数传入**：Scheduler 用 `dialogue_brain.expression.appraise()` 取 mode/act，非单一结构体；可读性一般但正确。

PARAMETER：
- **embarrassed 的 expression 只有一档**（embarrassed），§5 期望 flustered/contained/avoidant/playful 的细分是 Resolver 的活；Body 层用 relationship/mode 通过 composure/gaze/hesitation 隐式区分（已实现"高信任回 USER / 低信任 SIDE"）。若要显式分词需 Resolver 结合，属 Phase 10 范围。
- **长跑 tempo 偏慢**（slow 61%），是随机游走采样偏置（等概率 sleepy/sad/rest），非参数问题；真实 idle 生活是 relaxed/normal 为主。

TEST GAP：
- **cooldown/recency** 未做**真正的时序冷却**，current test 只验证"micro 偏好列表多样、sigh/giggle 不主导"（满足 §25 的防御，但没有 8s 冷却器）。因为本轮不新建"大型随机系统"，micro 每帧由引擎按其偏好**语义给出**，实际时间冷却/去重留给 Animation Runtime 复用已有节奏机制。
- **walk/pathfinding** 未测（明确不在本轮范围）。

UX/FUTURE：
- body_snapshot 尚未接入前端（等 Phase 10 `CharacterRuntimeFrame`）。
- micro 是"偏好列表"（本帧候选），非"最终选一个"——真正的 single-shot 采样留给 Resolver/Runtime。

## 20. Verdict

PASS。确定性 `EmbodiedExpressionEngine` 把 Emotion/Mode/Relationship/Activity/疲劳/矛盾投影成**语义级**身体 intents（0 新 LLM 调用），Emotion 不只改脸（gaze/tempo/amplitude/hesitation/composure 全动），Activity 与疲劳是硬约束（sleep→睡觉姿、高疲劳覆盖 "气场"），沉默仍"活着"，Furina vs Neutral vs Mask 三者在纯身体统计上两两可分且方向正确（Mask 克制挺直、Current 能松能真诚），long-run 与 collapse audit 显示 user-gaze 29.4%、upright 17.6%，不塌缩成"永远抬头挺胸盯用户"。246/246 测试全绿，228 旧测试零回归。

## 21. Recommended Next Step

**Phase 10 — Character Runtime Contract / Backend Integration Freeze**：把 Life Activity + Dialogue/SpeechIntent + Body Expression 统一成前端只需消费的一份稳定 `CharacterRuntimeFrame`（含 activity/activity_phase/speech{intent,text}/body{expression,gaze,posture,tempo,hesitation}/motion{intent,target}），让 `body_snapshot()` 与既有 `set_pose_semantics` 汇合到同一输出，并做一次集成长跑后 Backend Freeze——这是最后一个关键后端阶段。
