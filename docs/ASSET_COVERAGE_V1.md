# ASSET_COVERAGE_V1

> 真实 manifest：77 条（kind: Counter({'frame': 67, 'sequence': 10}))
> role: {'base_pose': 12, 'expression': 21, 'gaze': 12, 'micro': 10, 'action': 9, 'interaction': 2, 'prop': 5, 'transition': 6}

## Transition 序列

- `anim_sit_down`: standing → sitting (entry=8 loop=10 exit=8)
- `anim_stand_up`: sitting → standing (entry=8 loop=10 exit=8)
- `anim_lie_down`: sitting → lying (entry=8 loop=10 exit=8)
- `anim_lie_up`: lying → sitting (entry=8 loop=10 exit=8)
- `anim_wake_up`: sleeping → sitting (entry=8 loop=10 exit=8)
- `anim_go_sleep`: sitting → sleeping (entry=8 loop=10 exit=8)

## Resolver 命中率（语义 posture/expression/gaze → asset）

- 请求 520，命中 520（100%），缺失 0（best-available 回落遵循 Resolver 优先级）

### 缺失样本（前 12）
