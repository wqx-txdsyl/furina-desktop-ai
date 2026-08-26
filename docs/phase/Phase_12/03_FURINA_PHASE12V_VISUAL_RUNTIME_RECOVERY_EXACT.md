# Phase 12V — Visible Runtime Recovery / Manual Blocker Closeout

> 目标：不是继续“打磨”，而是修复人工验收已经证明的可见链路断裂。
>
> 当前状态：`349/349` 自动测试不能支持完整 PASS。人工结果已证明 Phase 12 = `PARTIAL — VISUAL CLOSEOUT REQUIRED`。
>
> 本轮结束后必须由用户重新人工验收；未人工确认不得进入 Phase 13。

## 0. 已确认根因

### V1 — 呼吸只作用在影子，角色本体不呼吸【P0】

`furina/runtime/furina_window.py` 的 `paintEvent()` 计算 `bob`，但：
- shadow 使用 `fit.y() + bob + 4`；
- character body 使用 `draw_rect`，没有 bob；
- `self.anim.frame(breath=0.0)` 还明确关闭了 ClipPlayer 已有的 breath transform。

因此人工看到“影子呼吸、人不呼吸”是确定性代码结果。

### V2 — Phase09 body semantic 没有进入真实 asset vocabulary【P0】

Backend Frame 输出的是语义 posture/expression/gaze，例如：
- posture: `relaxed/upright/seated/engaged/...`
- expression: `soft/pleased/concerned/tired/sincere/...`
- gaze: `USER/SCREEN/SIDE/...`

Manifest 使用的是素材词汇：
- posture: `standing/sitting/lying/sleeping/crouching/leaning`
- emotion: `neutral/happy/proud/embarrassed/...`
- gaze: `front/user/screen/left/right/up/down`

`FrontendFrameConsumer._apply_tokens()` 当前直接：
`vs.target_pose = frame.body.posture`。

真实生产代码没有使用 `scripts/asset_coverage.py` 里的 `map_posture/map_expression/map_gaze`。

结果：`seated` 请求不会匹配 `sitting`，`relaxed/upright` 等大量请求退回 standing；表达/视线同样大量降级。

### V3 — Action 素材在新主路径里基本没被使用【P0】

`AnimationRuntime._play_clip_for_phase()`：
1. 先 `sequence_for(activity)`；
2. manifest 没有 read/eat/play/drink/think 等 action sequence；
3. 然后 fallback 固定调用 `entry_for_state(..., action="idle")`。

因此 manifest 里已有的 read/eat/play/drink/think 等静态 action asset 被绕过。

此外 4 个真实 posture loop：
- `standing_loop`
- `sitting_loop`
- `lying_loop`
- `sleeping_loop`

也没有按 current visual pose 自动作为基础 LOOP 使用。

### V4 — Animation owner 实际仍有两个【P0】

Phase 11 声称 `AnimationRuntime owns presentation timing`，但真实代码：
- `AnimationRuntime._play_clip_for_phase()` 会 `clip.play()`；
- `FurinaWindow.present()` 每个 render tick 又调用 `_apply_clip()`；
- `_apply_clip()` 也会 `self.anim.play()`。

同一个 `win.anim` 同时被 Runtime 与 Window 控制。

Transition 刚被 Runtime 播放，就可能被 `present()` 的 base-pose clip 覆盖。

### V5 — Drag CG 当前不可能成功【P0 / ASSET + OWNERSHIP】

Manifest 的 2 个 interaction asset 只有：
- head_touch
- poke

**没有任何 `action=drag` asset。**

`set_drag_pose(True)` 请求 drag 时 resolver 会降级到普通 standing asset。

同时 `set_drag_pose()` 直接 `anim.play()`，下一次 16ms render tick 又会被主 Runtime / `present()` 覆盖。

所以“拖拽无 CG”同时包含：
1. 资产不存在；
2. animation ownership 冲突。

### V6 — “520/520 = 100% coverage” 指标无效【P0 TEST/AUDIT】

`asset_coverage.py` 把：
`resolver.resolve(...) is not None`
当作“命中”。

但 `AssetResolver.resolve()` 在 manifest 非空时几乎总会返回 fallback entry，因此“100%”不代表 exact semantic coverage。

实测静态分析：
- 脚本自身 intended mapping 后，520 请求中 exact 约 172（约 33%）；其余都是不同级别 fallback；
- 当前生产 semantic 直接进入 resolver 时，exact coverage 更低。

以后必须报告：
`EXACT / COMPATIBLE_DEGRADED / SEMANTIC_LOSS / MISSING`，不能只报 non-None。

### V7 — “单一 DialogueBrain 语言源”并未真正成立【P0】

生产路径仍存在固定用户可见台词：
- Scheduler interaction：petting / poke / drag / click 直接 `_say(fixed text)`；
- Agent complete/fail 直接 `_say(summary/fixed text)`；
- Feeding `apply_food()` 生成固定 reaction，App 把它包装成 `BRAIN_SPOKE`，实际上没有经过 DialogueBrain。

因此用户大量高频互动根本不会看到 DialogueBrain 的人格生成。

另外直接用户对话 `_brain_worker()` 调 DialogueBrain 时没有传：
- `user_initiated=True`
- current world
- relationship
- activity
- memory interpretation

会削弱真实 runtime persona context。

### V8 — DialogueBrain 还有 3 个确定性 wiring bug【P0 targeted bugfix】

1. God calibration 调用把 `emotion=app.mode` 传入，而不是实际 emotion。
2. Scheduler 传了 `context=speech_intent`，但 `_dialogue_prompt_v2()` 接收 context 后没有实际写入 prompt；LifeBrain 的具体 speech intent 被丢掉。
3. `_select_examples()` 计算了 `emot_ctx` 但从未使用；大量 mode/act 对不上 example context 时，排序退化成列表前 3 条，few-shot 相关性失真。

本轮允许作为 RC1 的**窄 bugfix exception**修复；禁止重写 Persona/Identity/Dialogue strategy。

### V9 — Phase 11B 的 EXIT 实际是 dead code【P0】

`AnimationRuntime.tick()` 会处理 `AnimationPhase.EXIT`，但生产代码中没有任何路径把 `self.phase` 设置为 `AnimationPhase.EXIT`。

现有两个“exit”测试也没有断言真正进入 EXIT：它们只验证新 plan 最终能继续。

所以此前“ENTRY→LOOP→EXIT 完整成立”的报告不成立。

### V10 — render tick 每 16ms 重复 accept 同一 visual【P1】

`_render_tick()` 每次都调用 `frame_runtime.accept(vs, ...)`。

在 TRANSITION/ENTRY 阶段，现有 anti-restart 只保护 LOOP/PRE_HOLD；同一 plan 可能反复写 pending，导致 transition 完成后再次执行旧 pending。

必须改为：只有 semantic revision/signature 真变化才 accept 新 plan。

### V11 — Production AnimationRuntime 没传 EventBus【P1】

主程序 `launch()` 创建：
`AnimationRuntime(win.anim, furina.assets, fps=30.0)`
没有 `bus=furina.bus`。

因此真实 App 的 ANIMATION_COMPLETED / TRANSITION_COMPLETED 事件不会发出，虽然测试/脚本可能传了 bus。

### V12 — 部分自动测试是空验收【P0 TEST QUALITY】

必须修：
- `test_asset_resolver_prefers_semantics` 当前核心断言是 `assert True`；
- `test_single_animation_owner` 只检查函数存在，不证明只有一个 `anim.play` owner；
- `test_gui_timer_advances_runtime` 含 `entries + loops >= 0` 这种永真断言；
- hardcoded speech 测试只查 `SPEECH_LINES/_behavior_speech`，没有查生产 `_say(fixed text)`；
- exit tests 没断言 `phase == EXIT`；
- GUI tests 只数 present/paint 调用，不验证 actual asset/pixel 是否真的改变。

---

# 1. 本轮状态

```text
Backend RC1                 targeted bugfix exception only
Frame schema                v1.0 unchanged
LifeBrain                   frozen
Identity                    frozen
Personality                 frozen
Emotion / Relationship      frozen
Memory                      frozen
World / Feasibility         frozen
Embodiment semantics        frozen
Dialogue persona/strategy   frozen

Allowed:
frontend semantic adapter
animation ownership/lifecycle
asset selection
critical drag/walk asset gap
Dialogue delivery wiring bugfix
real GUI/manual validation
```

# 2. 核心目标

真正建立：

```text
CharacterRuntimeFrame
        ↓
Frontend semantic mapper
        ↓
AnimationPlanner
        ↓
AnimationRuntime  ← 唯一 ClipPlayer owner
        ↓
FrontendVisualState/current QImage
        ↓
FurinaWindow.present()  ← 只接收并绘制
        ↓
paintEvent
```

语言：

```text
Interaction / Feed / Agent / User Talk / Life Decision
        ↓
Dialogue request context
        ↓
DialogueBrain
        ↓
BRAIN_SPOKE / Frame.speech
        ↓
Bubble
```

除明确 fallback/error message 外，禁止高频角色台词绕过 DialogueBrain。

# 3. FIX A — Window 彻底退出 ClipPlayer ownership

`FurinaWindow.present()`：
- 禁止调用 `_apply_clip()`；
- 禁止 `anim.play()`；
- 只写 presentation fields + `update()`。

`FurinaWindow.set_drag_pose()`：
- 禁止直接 `anim.play()`；
- 改成只报告 local interaction override request，或 deprecated/no-op presentation helper。

生产代码中 `AnimationController.play()` 的 owner 必须只有 `AnimationRuntime`。

测试必须源码+运行时双验证：
- Window main path 0 次 `anim.play()`；
- drag 不直接操作 clip；
- transition 播放后 500ms 内不会被 Window base-pose 覆盖。

# 4. FIX B — Production VisualSemanticMapper

新增例如：
`furina/runtime/visual_semantics.py`

提供：
- `map_posture(frame_posture, activity) -> asset_pose`
- `map_expression(expression) -> asset_emotion`
- `map_gaze(gaze, side_history) -> asset_gaze`
- `map_action(activity, interaction_override) -> asset_action`

不要把 mapping 只放 scripts。

最低 posture mapping：
- seated -> sitting
- sleeping -> sleeping
- lying -> lying
- leaning -> leaning（若有效）
- resting -> lying/compatible
- upright/relaxed/contained/guarded/engaged -> standing 或 activity-aware compatible pose

expression mapping至少覆盖 Phase09 全枚举。

gaze mapping至少覆盖 USER/SCREEN/ACTIVITY_TARGET/AWAY/SIDE/DOWN/AROUND/NONE。

# 5. FIX C — Asset Selection Policy

选择优先级不能再固定 `action="idle"`。

对于高可见 activity：
`read/eat/play/drink/think/nap/wave/...`
优先尝试对应 action asset。

如果 action asset 与 target posture 冲突：
- 明确记录 `DEGRADED_POSTURE_FOR_ACTION`；
- 当前资产不足时，优先“用户能看出正在做什么”，而不是退成完全 idle；
- 不允许静默说“100% exact”。

Idle/base activity：
- standing -> `standing_loop`（若有）
- sitting -> `sitting_loop`
- lying -> `lying_loop`
- sleeping -> `sleeping_loop`

使已有 4 个 pose loop 真正参与主 Runtime。

# 6. FIX D — Character Breath

必须保证：
- character body visibly receives breath transform；
- shadow 与 body 同步，不是只有 shadow 移动；
- 不双重叠加造成夸张浮动。

可复用 `AnimationController.frame(breath=...)`，或统一在 draw rect 上应用 body transform；选择一种 owner。

新增自动验证：
给 breath=0.0 / 0.5 / 1.0，最终 body draw transform/geometry 必须不同；shadow-only change 不算 PASS。

# 7. FIX E — Drag interaction

## E1 ownership

拖拽：
`mousePress -> local interaction override -> AnimationRuntime`
而不是 Window 自己 play。

拖拽 override priority 高于 autonomous activity/micro。

release 后 clear override，恢复当前 Frame 的视觉计划。

## E2 asset

当前 manifest 无 drag asset，因此完整拖拽 CG 不可能 PASS。

必须：
- 如果现有 Agnes/pipeline 可用：仅补一个明确 `role=interaction, action=drag` 的 drag asset/sequence，基于 identity anchor，经 QC 后入 manifest；
- 如果生成不可用：使用显式 `DEGRADED_DRAG_VISUAL`，但 Phase Manual 仍保持 FAIL/PENDING，禁止声称“被拎起 CG 已支持”。

不要用 resolver 静默回落到 standing neutral 冒充 drag。

# 8. FIX F — Walk visual gap

当前 manifest 无 walk asset。

如果目标仍要求“移动不是滑行”，则完整 Manual PASS 必须有可辨识 walk visual。

优先：
- 新增一个最小 walk loop（可带 entry/exit，至少 loop）；
- 或已有 pipeline 生成；
- manifest 明确 `action=walk, kind=sequence`。

若没有 walk asset：Technical spatial movement 可以工作，但 Manual Checklist 的“无滑行”不能 PASS。

# 9. FIX G — Dialogue single-source recovery

不得再把“没有 SPEECH_LINES”当成 single-source 证明。

以下生产路径改为 DialogueBrain request：
- petting
- poke
- drag
- click
- feed reaction
- Agent completed
- Agent failed（允许 deterministic error facts，但措辞交给 DialogueBrain）

交互事件先更新 deterministic Emotion/Relationship/Memory，再把结构化 context 喂 DialogueBrain。

DialogueBrain 失败：
- 可以沉默；
- 对 Agent 任务的必要错误事实可显示非角色化系统状态，但不能伪装成“芙宁娜人格台词”。

# 10. FIX H — Direct user dialogue context

`_brain_worker()` 必须传：
- `user_initiated=True`
- current activity
- world factors
- relationship snapshot
- memory interpretation
- user_present / solitude

不得只传 intent/emotion/user_text/memories。

# 11. FIX I — DialogueBrain narrow bugfixes

只修 wiring，不重写人格：

1. god calibration 使用真实 `emotion`，不能传 `app.mode`。
2. `_dialogue_prompt_v2()` 必须实际包含 `context/speech_intent`。
3. example retrieval 使用真实 emotion/dialogue_act/context；删除 unused `emot_ctx` 或真正使用它。
4. 不增加原作 quote bank。
5. 不修改 POST_ARCHON_QUEST identity core。

# 12. FIX J — Animation lifecycle 真闭环

必须真正存在：
`LOOP -> EXIT -> pending/new plan`

当 current action sequence 有 exit_frames 且 activity/plan 改变：
1. 保存 new plan 为 pending；
2. phase=EXIT；
3. 播 current clip exit_frames；
4. exactly-once completion；
5. 执行 pending plan。

如果 current asset 无 exit_frames：直接切 pending，但标 compatible immediate transition。

测试必须明确 assert 曾进入 `AnimationPhase.EXIT`。

# 13. FIX K — semantic revision，禁止每 tick accept 同一 plan

FrontendConsumer 增加 `semantic_revision`，只在可见语义变化时 +1。

`_render_tick`：
- 每 tick 只 `AnimationRuntime.tick()`；
- 只有 semantic_revision 变化时才 `AnimationRuntime.accept()`。

或 AnimationRuntime 内维护完整 semantic signature 去重。

要求：
- transition 期间 1000 个 render tick 不产生 duplicate pending；
- same-plan pending replacement = 0；
- transition 不会因重复 accept 自己再播一遍。

# 14. FIX L — Production EventBus wiring

主程序创建：
`AnimationRuntime(..., bus=furina.bus)`。

真实 App 必须能收到：
- ANIMATION_COMPLETED
- TRANSITION_COMPLETED

exactly-once。

# 15. FIX M — Gaze / micro dead path

当前 MicroScheduler 产出的 `state.gaze` 没进入 Window `_micro_gaze`。

统一决定：
- semantic gaze 由 GazeRuntime 控制 asset gaze；
- micro gaze 仅作为细微 overlay，若保留则由 Runtime 明确传入 View；
- 删除死字段 `_micro_gaze_next` 等 legacy 残留。

禁止两个 gaze owner 相互覆盖。

# 16. 重写 Asset Coverage

新报告必须按真实 runtime 选择器跑，不允许 scripts 自己使用一套 mapping、production 又不用。

输出：

| Scenario | Requested semantic | Mapped visual semantic | Asset | Match Quality |
|---|---|---|---|---|

Quality 只能：
- EXACT
- COMPATIBLE_DEGRADED
- SEMANTIC_LOSS
- MISSING

重点场景：
- idle standing
- idle sitting
- read
- think
- eat
- drink
- play
- proud
- embarrassed
- sad
- USER gaze
- SCREEN gaze
- SIDE gaze
- head_touch
- poke
- drag
- walk
- sleep
- wake

“resolver 返回非 None”不等于 exact。

# 17. 修测试，禁止空 PASS

必须删除/替换：
- `assert True` asset semantic test；
- `entries + loops >= 0`；
- 只看函数名存在的 single-owner test；
- 只搜索 SPEECH_LINES 名字的 single-speech-source test；
- 没 assert EXIT 的 exit test。

# 18. 新测试最低集合

```text
body_breath_changes_character_transform
shadow_and_body_breath_sync

visual_posture_seated_maps_sitting
visual_posture_relaxed_maps_valid_pose
visual_expression_soft_maps_asset_vocab
visual_expression_tired_maps_sleepy
visual_gaze_user_maps_user
visual_gaze_side_resolves_left_or_right

read_uses_read_asset_not_idle
think_uses_think_asset_not_idle
eat_uses_eat_asset_not_idle
idle_uses_pose_loop
sleep_uses_sleeping_loop

animation_runtime_is_only_clip_owner
window_present_never_calls_clip_play
transition_not_overwritten_by_present
same_visual_tick_does_not_reaccept_plan
same_transition_does_not_duplicate_pending

loop_enters_exit_before_new_plan
exit_completion_exactly_once
production_animation_runtime_has_bus

drag_override_reaches_animation_runtime
drag_missing_asset_is_explicit_degraded
drag_asset_exact_when_present

walk_missing_is_explicit_degraded
walk_asset_exact_when_present

interaction_speech_routes_dialogue_brain
feeding_speech_routes_dialogue_brain
agent_result_speech_routes_dialogue_brain
direct_user_dialogue_user_initiated
runtime_has_no_character_fixed_speech_bypass

dialogue_context_reaches_prompt
god_calibration_uses_real_emotion
example_selection_is_contextual
```

所有旧测试继续跑，但旧测试数量不能作为主要成功指标。

# 19. 真实 GUI 观测必须记录“实际 asset id”

新增 debug instrumentation（仅 debug）：

```text
Frame activity
Frame body semantic
Mapped visual pose/expression/gaze/action
Current asset_id
Current sequence
Animation phase
Clip owner
Dialogue source (DialogueBrain / SYSTEM_STATUS / SILENT)
LifeBrain selected activity
```

这样人工看到 standing 时能直接知道为什么。

# 20. Deterministic Manual Script

重写 `scripts/manual_gui_phase12.py`。

每个 scene 进入时打印：

```text
EXPECTED:
activity=read
visual_pose=sitting
asset_action=read (or documented degraded read)

ACTUAL:
frame=...
mapped=...
asset_id=...
phase=...
```

顺序控制在 2~4 分钟内：
1. idle + body breath
2. standing loop
3. sitting/read
4. proud
5. embarrassed + side gaze
6. eat/play/think 三个动作快速展示
7. sleep → wake
8. drag
9. walk left/right
10. direct user dialogue test

不要让用户等 60~90 秒才看到关键状态。

# 21. 人工验收 Checklist

用户重新运行后确认：

```text
[ ] 角色本体有呼吸，不是只有影子动
[ ] standing idle 有持续生命感
[ ] read 明显不是 standing-neutral-idle
[ ] sitting / lying / sleeping 能真实切换
[ ] proud / embarrassed / sad 可肉眼区分
[ ] USER / SCREEN / SIDE gaze 至少能看出变化
[ ] eat / play / think 能看出动作差异
[ ] transition 不被瞬间覆盖
[ ] drag 有真实专用视觉；若无资产则明确 FAIL，不冒充
[ ] autonomous move 有 walk visual，不滑行
[ ] LifeBrain activity 改变能导致用户可见行为改变
[ ] pet/poke/drag/feed 等高频台词来自 DialogueBrain，而不是固定句池
[ ] 直接对话明显携带 Furina persona，而不是 generic assistant
[ ] 无连续重复 transition / animation reset
```

# 22. PASS 规则

自动测试全部通过但未人工检查：
`PASS-AUTO / MANUAL_VISUAL_PENDING`

如果 drag/walk asset 仍缺：
`PARTIAL — CRITICAL ASSET GAP`

只有用户人工确认所有 blocker 消失：
`PASS`

# 23. 本轮禁止

禁止：
- Phase 13 新 Interaction feature expansion
- 新 Need / Emotion / Personality / Relationship / Memory
- 改 LifeBrain scoring
- 改 Identity core
- 大改 Dialogue persona
- 新 LLM
- 新 DB
- “为了测试绿”降低 manual criteria

# 24. 最终报告格式

```md
# Phase Report — Visible Runtime Recovery

## 0. Status
Technical:
Manual:
Overall:
Tests:
Backend exception scope:
Schema:

## 1. Root Causes Fixed
V1..V12 每项：root cause / code change / proof

## 2. Animation Ownership
ClipPlayer owners before:
After:

## 3. Semantic → Asset Mapping
完整 mapping 表。

## 4. Runtime Asset Coverage
EXACT:
COMPATIBLE_DEGRADED:
SEMANTIC_LOSS:
MISSING:

## 5. Action Visibility
read:
eat:
play:
think:
sleep:

## 6. Pose Loops
standing:
sitting:
lying:
sleeping:

## 7. Breath
Body transform:
Shadow transform:
Evidence:

## 8. Drag
Dedicated asset:
Override owner:
Overwrite count:
Result:

## 9. Walk
Dedicated sequence:
Movement visual sync:
Result:

## 10. Animation Lifecycle
ENTRY:
LOOP:
EXIT:
TRANSITION:
Duplicate pending:

## 11. Dialogue Ownership
Interaction speech:
Feed:
Agent result:
Direct user dialogue:
Fixed character speech bypass count:

## 12. Dialogue Runtime Context
user_initiated:
world:
relationship:
activity:
context/speech_intent:
examples:
god calibration:

## 13. LifeBrain Visibility
Decision → Frame.activity → asset/action evidence

## 14. Real GUI Debug Trace
逐场景 expected vs actual asset id。

## 15. Test Quality Cleanup
列出删除的 vacuous assertions。

## 16. Regression

## 17. Manual Visual Check
Status=PENDING/PASS/FAIL
Checklist 不得 Agent 自行勾选（无 vision 时）。

## 18. Verdict

## 19. Recommended Next Step
只有 Manual PASS 后：Phase 13 — User Interaction Integration
否则：继续本 Visual Recovery，只修明确 blocker。
```
