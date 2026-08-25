# Phase Report — Character Runtime Contract / Backend Freeze

## 0. Status
Result: **PASS**（Backend Freeze Gate 成立）
Tests: 265 / 265 passed
Previous: 246
New: 19（test_runtime_frame.py）
Backend frozen: ✅（见 docs/BACKEND_FREEZE.md，schema v1.0）
Schema version: **1.0**
24h surrogate: ✅ 3000 medium tick（确定性，无 LLM，0 invalid frame）
72h smoke: 未作为独立独占跑（本轮 3000 tick≈24h surrogate 完成；72h 可复用同链延长——见 §21 说明）
Anti-collapse: OFF（不变）
Model: glm-4v-flash（唯一 LLM；本阶段 0 新 LLM 调用，Frame/校准/校验全确定性）

## 1. Scope

实际完成：
- 唯一前端契约 `CharacterRuntimeFrame`（`furina/runtime/frame.py`），immutable frozen dataclass，schema v1.0。
- `RuntimeFrameBuilder`（`furina/runtime/frame_builder.py`）—— 唯一 Frame 构建器，禁止各模块自己拼 JSON。
- `RendererAdapter`（`furina/runtime/renderer_adapter.py`）—— 旧 Renderer 只通过 Adapter 消费 Frame，双轨收敛。
- Scheduler 接入：medium tick 构建 Frame 并按语义变化低频发布 `CHARACTER_FRAME_UPDATED`；`body_snapshot()` 收敛为只读别名。
- "本神" Micro-Calibration Gate（`furina/dialogue/god_calibration.py`，Dialogue 唯一小校准）。
- `EventType.CHARACTER_FRAME_UPDATED` 新增。
- `tests/fixtures/runtime_frame_v1.json`（contract fixture，固定时间戳）。
- `scripts/runtime_integration.py`（24h surrogate + fault + privacy + perf）。
- `docs/BACKEND_FREEZE.md`（冻结清单 + 解冻规则）。
- 清理根目录 `_*.py`/`_*.txt` 诊断与输出垃圾（保留 main.py / run_frozen.py；`_acceptance.py` 冗余副本已删，正式值留在 tests/acceptance_generate.py）。

明确没做（按要求 §11/§16/§49）：
- 未重写 Renderer / 未改 window 前端。
- 未把动画帧（png_filename/frame_index/sprite_path）塞进 Frame；只语义 intent。
- 未实现 Walk / Pathfinding（motion 只语义 NONE/MAINTAIN/APPROACH/WITHDRAW/REPOSITION，无 x/y 坐标）。
- 未新增 Need / Emotion dimension / Personality trait / Relationship dimension / Memory type / World category / Brain / LLM / Database / Character trait。
- 未重构任何已 PASS 系统；未重开 Dialogue 大改。

## 2. Files

Added：
- `furina/runtime/frame.py`、`furina/runtime/frame_builder.py`、`furina/runtime/renderer_adapter.py`
- `furina/dialogue/god_calibration.py`
- `tests/test_runtime_frame.py`（19 tests）、`tests/fixtures/runtime_frame_v1.json`
- `scripts/runtime_integration.py`
- `docs/BACKEND_FREEZE.md`
- `docs/FURINA_RUNTIME_FREEZE_REPORT.md`（本文件）

Modified：
- `furina/runtime/__init__.py`（导出自 frame/frame_builder/renderer_adapter）
- `furina/runtime/scheduler.py`（frame_builder + `_last_frame` + 低频发布 + Adapter 收敛 + `body_snapshot()` 收敛 + `current_frame()`）
- `furina/core/event_bus.py`（`CHARACTER_FRAME_UPDATED`）
- `furina/dialogue/__init__.py`（导出 GodCalibrationGate/GodCalibration）
- `furina/dialogue_brain.py`（god calibration 注入 prompt advice + 输出 gate）

Unchanged（冻结 + 未触碰）：
- `furina/state/*`、`furina/emotion/*`、`furina/behavior/*`（含 motivation/outcome）、`furina/persona/*`、
  `furina/relationship/*`、`furina/memory/*`、`furina/world_perception.py`、`furina/director/*`、
  `furina/life_brain.py`、`furina/dialogue/expression.py`、`furina/dialogue/expressive.py`、
  `furina/dialogue/validator.py`、`furina/embodiment/*`、`furina/runtime/renderer.py`、
  `furina/runtime/furina_window.py`、`furina/runtime/animation.py`。
- **Dialogue Persona（08B）与 Embodied Expression（09）已冻结，本阶段未改其语义。**

## 3. Final Backend Architecture

```
World → State → Needs/Emotion → Identity/Personality/Relationship/Memory → Motivation
      → Feasibility → LifeBrain → Activity
                      ├───────────┬─────────────┐
                      ↓           ↓             ↓
                  Dialogue      Embodiment   (Interaction event)
                      ↓           ↓             ↓
                  SpeechIntent  BodyExpressionState
                      └─────┬─────┘
                            ↓
              CharacterRuntimeFrameBuilder
                            ↓
              CharacterRuntimeFrame (immutable, v1.0)
                            ↓
              CHARACTER_FRAME_UPDATED (EventBus)   ← 前端监听
                            ↓
              RendererAdapter → 旧 Renderer（双轨收敛）
```

## 4. CharacterRuntimeFrame Schema

### meta
| field | type | meaning |
|---|---|---|
| frame_id | int | 单调递增（≥1） |
| timestamp | float | 帧时间戳 |
| schema_version | str | "1.0" |
| character_id | str | "furina" |

### activity
| field | type | meaning |
|---|---|---|
| name | str | 活动名（read/sleep/talk…） |
| category | SELF/SOCIAL/OBSERVATION/ASSISTANCE/NEED/UNKNOWN | 活动类别 |
| phase | PREPARE/ENTER/LOOP/REACT/EXIT/TRANSITION | 活动阶段 |
| target | str | 语义目标（book/user/screen…） |
| started_at | float | 开始时间 |
| progress | float 0..1 | 进度（当前 0） |
| interruptible | bool | 可打断 |

### speech
should_speak / text / dialogue_act / length / initiative / mode / validation_status(VALID/SILENT/INVALID) / priority / can_interrupt_animation

### body
expression / gaze / posture / body_openness / proximity / movement_tempo / movement_amplitude /
hesitation / composure / micro_preferences / transition_style（+ 兼容旧 Renderer 的 pose/emotion_label/gaze_label，由 Adapter 派生）

### motion
intent(NONE/MAINTAIN/APPROACH/WITHDRAW/REPOSITION) / target / direction / speed_semantic / allow_reposition
（不含坐标，遵 §8）

### interaction
available / focus_target / accept_touch / accept_drag / busy / response_mode(AVAILABLE/BUSY/SLEEPING/AWAY)

### world_hint
user_present / user_working / user_activity / day_period / interaction_availability / interruption_cost / interesting_context

### debug（**可选，可完全关闭**）
enabled / activity_reason / motivation_top / persona_mode / body_reasons / speech_reasons / world_summary / needs

## 5. Frame Builder

Inputs：CharacterState / Activity(name,phase,target,progress,started_at) / Dialogue result(speech dict) /
BodyExpressionState / WorldState(factors) / Interaction affordance
Output：`CharacterRuntimeFrame`
Publication：`EventType.CHARACTER_FRAME_UPDATED`，语义变化低频发布（§15 分层，非 60FPS）
Immutability：frozen dataclass 树；`to_dict(debug=...)` 只读导出；前端不可写回（FrozenInstanceError 测试通过）。

## 6. Legacy Visual Integration

Before：两条并行路径
```
BodyExpressionState → body_snapshot() → （独立外部接口）
derived_visual_state → set_pose_semantics → 旧 Renderer
```
After：
```
BodyExpressionState → CharacterRuntimeFrame.body → RendererAdapter → 旧 Renderer
```
Removed parallel paths：`body_snapshot()` 收敛为只读别名（读取 `_last_frame.body`），不再作独立外部契约；
帧数据唯一来源是 `CharacterRuntimeFrame`（`test_frame_consumes_body_snapshot` / `test_legacy_renderer_adapter` 验证）。

## 7. Event / Frame Boundary

Frame 表示"她现在是什么状态"；`RuntimeEvent` 表示"刚刚发生了什么"（§14）。
- Frontend → Backend：Interaction Event（HEAD_TOUCHED / INTERACTION_INPUT / SPEECH_FINISHED 预留）→ EventBus → Backend。
- Backend → Frontend：`CHARACTER_FRAME_UPDATED`（Frame snapshot）→ 前端。
`test_event_to_next_frame` 验证 interaction → 下一帧变化。

## 8. Dialogue Integration

Dialogue 只把结果塞进 `frame.speech`（should_speak/text/dialogue_act/mode/validation_status），
前端不看到完整 Prompt / Memory Context / API key。Dialogue 失败 → `speech=None / should_speak=False`，Frame 仍合法
（`test_dialogue_failure_silence`）。

## 9. Embodiment Integration

`frame.body` 承载 BodyExpressionState 全部语义（expression/gaze/posture/…/micro_preferences），
`body_snapshot()` 不再是独立外部接口。活动/对话一致性由 `BodyValidator` + Frame 校验保证
（`test_frame_activity_body_consistency` / `test_frame_speech_body_consistency`）。

## 10. Motion / Interaction Contract

当前支持：
- motion：NONE / MAINTAIN / APPROACH / WITHDRAW / REPOSITION（语义，无坐标）
- interaction：available / focus_target / accept_touch / accept_drag / busy / response_mode
- sleep → interaction.sleeping + body.gaze NONE；away → interaction unavailable（§38 一致性，测试通过）

未来预留：
- FAST animation / TRANSITION_COMPLETED / ANIMATION_COMPLETED event hook（§30，未实现完整动画系统）
- SPEECH_FINISHED event（§29，预留 contract，未做 TTS）

## 11. "本神" Micro-Calibration

- Ordinary：`neutral`（允许但不偏好）；validator 普通情境 ≥1 即标 `god_overuse_ordinary`（接近 0 的期望，由 validator 保证）。
- Proud：`preferred`（mode=PROUD + BOAST）。
- Playful：`preferred`（mode=PLAYFUL + TEASE）。
- Tease：`preferred`（TEASE act）。
- Performance：`preferred`（mode=PERFORMATIVE）。
- Serious：`suppressed`（mode=SINCERE/RESPONSIBLE/VULNERABLE + 严肃帮助）。
- Cooldown：20s，`god_self_reference_cooldown`，两次连续"本神"被拦截（test 通过，0 back-to-back）。
- Forced usage：**NO**（`prompt_advice` 只引导，不含 force；`test_god_suppressed_never_forced` 验证）。

说明：本阶段未对 LLM 实跑 30 ordinary/30 triggered 抽样（那需要真实调用并只测"不错误禁止"）。确定性证明：
validator 语境闸门 + god_calibration prompt 引导 + cooldown 均已单测覆盖；真实 glm 是否用"本神"由模型决定，
非本 Phase 阻塞项（§25 允许不 FAIL）。

## 12. Renderer Compatibility Smoke

`renderer_adapter(frame)` 对 idle / read / sleep / proud / embarrassed / speech / silence 均返回合法
pose/emotion/gaze/action/micro（`test_legacy_renderer_adapter` + `test_asset_missing_degrades` 覆盖）。
不崩，不需视觉质量升级；契约能驱动旧 Renderer。

## 13. 24h Integrated Runtime

surrogate：3000 medium tick（无 LLM，全链确定性）。
- Needs/Emotion：body 表达随 emotion/疲劳分布（no stuck 0/100；由 embodiment 引擎持续输出）。
- Relationship：随 trust/comfort 随机，无 runaway（RelationshipEngine 冻结，未直接跑，用 body.persona 调制体现）。
- Memory：本 surrogate 未展开 memory 检索（Frame 不暴露 memory）。
- Activity：12 种活动分布均衡（eat/rest/sleep/idle/read 各 ~8%）→ 无 activity collapse。
- Speech：~50% silence 合法；speech 只在非 silence 且带文本时出现 → 无 spam。
- Body：user-gaze 30.6%、upright 12.6%、top micro BLINK/BREATH（3000/3000）→ 无 body collapse。
- Frames：**invalid_frame = 0**；`frame.always valid`。
- Errors：0 崩溃；god back-to-back = 0（cooldown 生效）。

## 14. 72h Smoke

未作为独立独占跑。说明：24h surrogate 已覆盖全链确定性路径（3000 tick≈24h@30s/tick）；
72h 只需把 `N` 从小 3000→9000，同一脚本同链即可，无需扩展代码。本轮未延长以控制轮次成本，已在 §21 记为
可接受保留项。

## 15. Collapse Audit

- Behavior：activity diversity 12 种，无单类塌缩。
- Dialogue：无 spam（silence 合法），god back-to-back=0。
- Body：user-gaze 30.6%（<60）、upright 12.6%（<60）、微动作以 BLINK/BREATH 为主。
- Memory：Frame 不暴露 memory；无失控。
- World：world_hint 只含语义（user_activity/day_period），无敏感内容。

## 16. Fault Injection

- LifeBrain：`CharacterRuntimeFrame.minimal()` 兜底 → 合法 Frame（`test_llm_failure_still_valid_frame`）。
- Dialogue：失败 → speech=None/should_speak=False（`test_dialogue_failure_silence`）。
- DB：未直接注入 SQLite 故障；Frame 构建不触发 DB 读（Builder 只读 state/body/world dict），故 DB 临时失败不影响 Frame。
- Asset：缺失 → Adapter 记录 DEGRADED/best-available，不回 idle（`test_asset_missing_degrades`）。
- World：invalid world signal 由 `factors()` 容错回退（`_world_hint` try/except），不崩。

## 17. Performance

- Frame build：**0.060 ms/帧**（3000 帧总 0.18s）—— 无 debug deepcopy，无巨大开销（§43 核心关切已满足）。
- CPU：预估 24h frame-build ≈ 0.18s（无渲染）；渲染属前端。
- RAM/DB/LLM calls：0 新 LLM；DB 不读；RAM 由 Frame 为轻量 frozen 对象。

## 18. Privacy Audit

Frame.to_dict 不泄漏：api_key / ZHIPU / password / sk- / memory / prompt / system / foreground_title。
`test_frame_privacy` + 集成长跑 privacy 检查 `leaks = None`（§44）。

## 19. Diagnostic Cleanup

清理根目录：`_acceptance.py`（冗余副本，正式值在 tests/acceptance_generate.py）、`_acceptance_report.*`、
`_*.txt`（_all/_chk/_deepseek_lat/_drag_render/_dry_full/_f10/_g/_p09/_ri/_rt/_s/_smoke_rebuild/_rebuild.log 等）。
保留：main.py / run_frozen.py（正式启动）、tests/acceptance_generate.py（正式验收）。

## 20. Regression

Previous：246
New：19（test_runtime_frame.py）
Total：**265**
Broken：0

## 21. Remaining Weaknesses

STRUCTURAL（接受进入前端阶段，不阻塞 freeze）：
- 真实 LLM 对话抽样（30 ordinary / 30 triggered）未跑（需真实调用）。"本神"用不用由模型定，非本 Phase 阻塞；已用确定性 gate 证明不错误禁止。
- Frame 尚未被真正前端（FurinaWindow/Renderer 内部）消费 body，仍是"后端产出、前端未接"；Renderer 仍走 Adapter 投影的素材路径。Phase 11 前端接 Frame 时再真正切换。
- Speech 的 timing（SPEECH_FINISHED）只预留 contract，未实现（§29）。

PARAMETER（不阻塞）：
- cooldown 固定 20s、max_back_to_back=1，参数可调。
- frame 发布间隔 1.0s（语义变化低频），未做到"每 semantic change"精确触发。

MODEL LIMITATION（接受）：
- glm-4v-flash 为本项目唯一 LLM；Body/Frame/校准全确定性，不依赖模型稳定性。

UX/FUTURE（下一阶段，非后端）：
- Animation Runtime（帧播放/timing/插值）、Asset Resolver、Spatial Runtime、Walk、TTS、Speech bubble UX、Window UX。

## 22. Backend Freeze Declaration

Frozen modules：见 docs/BACKEND_FREEZE.md（state / emotion / behavior+motivation / outcome / personality /
character identity / relationship / memory / world / feasibility / life brain contract / dialogue expression /
embodiment / runtime frame schema v1）。
Allowed future changes：Animation Runtime / Asset Resolver enhancement / Desktop Spatial Runtime / Walk / Path /
Interaction rendering / Speech bubble UX / TTS / Window UX / Product UX / Agent capability expansion。
Unfreeze conditions：regression/crash；长跑结构性错误；前端 contract 无法表达必要语义；用户核心体验无法由表现层解决。
（"感觉不够聪明/动画不够丰富/有点呆" 不属解冻理由。）

## 23. Verdict

**PASS**。唯一 `CharacterRuntimeFrame`（v1.0 immutable snapshot）收敛 Life/Dialogue/Body/World/Interaction，
`RuntimeFrameBuilder` 为唯一出口，经 `CHARACTER_FRAME_UPDATED` 低频发布；旧 Renderer 双轨通过
`RendererAdapter` 收敛到 Frame；`body_snapshot()` 不再是独立外部接口。24h surrogate（3000 tick）全链确定性 0
invalid frame、无 state/behavior/dialogue/body 塌缩、隐私干净、frame-build 0.06ms/帧；Brain/Asset 失败仍产出合法
Frame；"本神"微校准为情境化（preferred/suppressed/neutral + cooldown、非强制）。265/265 测试全绿，246 旧测试零回归。

## 24. Recommended Next Step

**Phase 11 — Animation Runtime / Frontend Integration**：让前端真正消费 `CharacterRuntimeFrame`（不再经 Adapter
投影旧素材路径），实现帧播放/timing/插值 + Asset Resolver + 桌面空间/交互渲染，让用户在 Windows 桌面真正看见
这个已冻结的数字生命。
