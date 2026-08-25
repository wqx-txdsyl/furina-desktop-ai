# Runtime Asset Coverage（Phase 12V）

> 用生产同一套选择器：VisualSemanticMapper.map() + AssetResolver.resolve()。
> **`resolve 非 None` 不等于 exact**；以下为真实匹配质量。

| Scenario | Requested semantic | Mapped visual semantic | Asset | Match Quality |
|---|---|---|---|---|
| idle standing | relaxed/neutral/NONE/idle | standing/neutral/front/idle | furina_standing_neutral_front_idle_01 | **EXACT** |
| idle sitting | seated/neutral/NONE/rest | sitting/neutral/front/idle | furina_sitting_neutral_front_idle_01 | **EXACT** |
| read | upright/focus/DOWN/read | standing/focus/down/read | furina_standing_focus_front_read_01 | COMPATIBLE_DEGRADED |
| think | relaxed/thoughtful/NONE/think | standing/thoughtful/front/think | furina_standing_thoughtful_front_think_01 | **EXACT** |
| eat | upright/happy/DOWN/eat | standing/happy/down/eat | furina_standing_happy_front_eat_01 | COMPATIBLE_DEGRADED |
| drink | upright/neutral/DOWN/drink | standing/neutral/down/drink | furina_standing_neutral_front_drink_01 | COMPATIBLE_DEGRADED |
| play | upright/playful/DOWN/play | standing/playful/down/play | furina_standing_playful_front_play_01 | COMPATIBLE_DEGRADED |
| proud | upright/proud/USER/idle | standing/proud/user/idle | furina_standing_proud_front_idle_01 | COMPATIBLE_DEGRADED |
| embarrassed | upright/embarrassed/SIDE/seek_attention | standing/embarrassed/left/idle | furina_standing_embarrassed_front_idle_01 | COMPATIBLE_DEGRADED |
| sad | relaxed/sad/DOWN/idle | standing/sad/down/idle | furina_standing_sad_front_idle_01 | COMPATIBLE_DEGRADED |
| USER gaze | relaxed/neutral/USER/idle | standing/neutral/user/idle | furina_standing_neutral_user_idle_01 | **EXACT** |
| SCREEN gaze | upright/focus/SCREEN/observe_work | standing/focus/screen/idle | furina_standing_neutral_front_idle_01 | COMPATIBLE_DEGRADED |
| SIDE gaze | relaxed/embarrassed/SIDE/idle | standing/embarrassed/left/idle | furina_standing_embarrassed_front_idle_01 | COMPATIBLE_DEGRADED |
| head_touch | upright/happy/USER/head_touch | standing/happy/user/head_touch | furina_standing_happy_user_head_touch_01 | **EXACT** |
| poke | upright/surprised/USER/poke | standing/surprised/user/poke | furina_standing_surprised_user_poke_01 | **EXACT** |
| drag | upright/surprised/USER/drag | standing/surprised/user/idle | furina_standing_surprised_front_idle_01 | COMPATIBLE_DEGRADED |
| walk | upright/neutral/front/walk | standing/neutral/front/idle | furina_standing_neutral_front_idle_01 | **EXACT** |
| sleep | sleeping/sleepy/NONE/sleep | sleeping/sleepy/front/idle | furina_sleeping_neutral_front_idle_01 | COMPATIBLE_DEGRADED |
| wake | upright/neutral/NONE/idle | standing/neutral/front/idle | furina_standing_neutral_front_idle_01 | **EXACT** |

## Quality breakdown
- EXACT: 8
- COMPATIBLE_DEGRADED: 11
- SEMANTIC_LOSS: 0
- MISSING: 0
- **total**: 19

## Notes
- idle standing: degraded → posture:relaxed->standing;gaze:NONE->front
- idle sitting: degraded → posture:seated->sitting;gaze:NONE->front
- read: degraded → posture:upright->standing
- think: degraded → posture:relaxed->standing;gaze:NONE->front
- eat: degraded → posture:upright->standing
- drink: degraded → posture:upright->standing
- play: degraded → posture:upright->standing
- proud: degraded → posture:upright->standing
- embarrassed: degraded → posture:upright->standing;gaze:SIDE->left
- sad: degraded → posture:relaxed->standing
- USER gaze: degraded → posture:relaxed->standing
- SCREEN gaze: degraded → posture:upright->standing
- SIDE gaze: degraded → posture:relaxed->standing;gaze:SIDE->left
- head_touch: degraded → posture:upright->standing
- poke: degraded → posture:upright->standing
- drag: degraded → posture:upright->standing;action:drag->MISSING
- walk: degraded → posture:upright->standing
- sleep: degraded → gaze:NONE->front
- wake: degraded → posture:upright->standing;gaze:NONE->front