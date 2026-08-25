# Character Body / Rendering — Architecture Reservation

> STATUS = PLANNED
> NO IMPLEMENTATION YET
> 本任务不实现 Renderer。本文件只冻结未来表现层架构方向。

## 明确：不使用 Live2D

项目**不使用 Live2D**。最终表现层：

```
PNG / 状态图 / 多帧动画
+
程序驱动
```

## 接口方向（冻结）

```
Life / Emotion / Behavior
        ↓
Embodiment
        ↓
CharacterBodyFrame
        ↓
Asset Resolver
        ↓
Animation / Rendering
        ↓
Windows Desktop
```

## CharacterBodyFrame（未来至少包含）

```
posture
locomotion
expression
gaze
facing
action
micro_action
speech
transition
interruptibility
target
visual_energy
dramatic_intensity
asset_key
```

> 当前版本的 Embodiment（`furina/embodiment/`）与 Frame（`furina/runtime/frame.py`）
> 是这一方向的早期形态；此处为未来完整 Character Body 的命名预留。
