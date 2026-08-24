"""Phase 12 空间模型 —— 语义/几何/状态的纯数据定义。

坐标模型（写在文档 §7）：
  - screen coordinate：Qt logical pixel 虚拟桌面坐标系，原点 = 主屏左上，+x 右 / +y 下。
  - window coordinate：传给 ``FurinaWindow.set_position(x, y)`` 的 ``pos``：
      窗口左上角 = (x - side, y - top)；角色在窗口水平居中、顶部 = 气泡区下缘。
  - character anchor：**foot anchor（脚底中点）**，即角色中心-x 与脚底-y 的屏幕点，
      是本层空间逻辑的"位置真相"。standing/sitting/lying 的画布不同，
      但脚底锚点稳定，Adapter 负责 foot ↔ set_position(pos) 互转。

本模块**不 import Qt**，全部可 headless 测试。
后端冻结：本层只消费 CharacterRuntimeFrame 语义（motion/body/activity/world_hint），
不重算动机、不读 Needs、不写 State/Emotion/Relationship/Memory。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class SpatialIntent(str, enum.Enum):
    """空间意图 —— 由 Frame 语义解析而来，**不是**前端自造。"""
    NONE = "NONE"
    APPROACH = "APPROACH"
    WITHDRAW = "WITHDRAW"
    MAINTAIN = "MAINTAIN"
    NEAR = "NEAR"
    FAR = "FAR"
    REPOSITION = "REPOSITION"


class SpatialState(str, enum.Enum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    STARTING = "STARTING"
    MOVING = "MOVING"
    ARRIVING = "ARRIVING"
    ARRIVED = "ARRIVED"
    INTERRUPTED = "INTERRUPTED"
    DRAGGED = "DRAGGED"


class TargetType(str, enum.Enum):
    CURRENT = "CURRENT"                      # 保持当前位置（主用于 maintain/无目标）
    USER_WINDOW_EDGE = "USER_WINDOW_EDGE"    # 活动窗口下方边缘
    USER_WINDOW_SIDE = "USER_WINDOW_SIDE"    # 活动窗口侧边
    NEAR_USER_SAFE = "NEAR_USER_SAFE"        # 用户附近安全区（不遮挡正文/按钮）
    QUIET_CORNER = "QUIET_CORNER"            # 安静角落（远离用户）
    LEFT_OPEN_AREA = "LEFT_OPEN_AREA"        # 桌面左侧开阔区
    RIGHT_OPEN_AREA = "RIGHT_OPEN_AREA"      # 桌面右侧开阔区
    CURRENT_NEIGHBORHOOD = "CURRENT_NEIGHBORHOOD"  # 当前附近（微小游走）
    OPEN_DESKTOP_AREA = "OPEN_DESKTOP_AREA"  # 桌面开阔随机安全区
    DRAG_RELEASE = "DRAG_RELEASE"            # 用户拖拽释放处
    SAFE_FALLBACK = "SAFE_FALLBACK"          # 非法几何/无目标时的安全兜底


class Facing(str, enum.Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    FRONT = "FRONT"


class SpeedSemantic(str, enum.Enum):
    VERY_SLOW = "very_slow"
    SLOW = "slow"
    NORMAL = "normal"
    LIVELY = "lively"
    ENERGETIC = "energetic"


# ---------------------------------------------------------------- 点 / 矩形
@dataclass
class SpatialPoint:
    x: float = 0.0
    y: float = 0.0

    def to_tuple(self) -> tuple:
        return (self.x, self.y)

    def distance(self, other: "SpatialPoint") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        return (dx * dx + dy * dy) ** 0.5


# ---------------------------------------------------------------- ResolvedIntent（Frame→意图）
@dataclass
class ResolvedIntent:
    """Resolver 输出：一段"她想要的空间意图 + 表现参数"。只做解释，不做决策。"""
    intent: str = SpatialIntent.NONE.value
    speed_semantic: str = SpeedSemantic.NORMAL.value   # very_slow..energetic
    tempo: str = "normal"
    hesitation: float = 0.4
    transition_style: str = "SMOOTH"
    amplitude: float = 0.5
    allow_reposition: bool = False
    wander_allowed: bool = False
    source_frame_id: int = 0
    reason: str = ""
    activity: str = "idle"
    user_present: bool = True
    user_working: bool = False


# ---------------------------------------------------------------- SpatialState（§18）
@dataclass
class FrontendSpatialState:
    """前端空间当前演到哪里（≠Frame 想做什么）。position/目标全部为 foot anchor。"""
    state: str = SpatialState.IDLE.value
    position: SpatialPoint = field(default_factory=SpatialPoint)      # foot anchor 当前位置
    anchor_position: Optional[SpatialPoint] = None                     # 脚底锚点（=position 别名，语义明确）
    current_screen: int = 0                                            # 当前所在屏幕 index
    current_zone: str = "open"                                         # 所在区域（open/corner/near_user/edge...）
    target_type: str = TargetType.CURRENT.value
    target_position: Optional[SpatialPoint] = None                     # foot anchor 目标
    target_zone: str = ""
    facing: str = Facing.FRONT.value
    velocity: float = 0.0                                              # 当前速度 px/s
    speed: float = 0.0                                                 # 计划速度 px/s
    moving: bool = False
    arrived: bool = False
    movement_started_at: float = 0.0
    arrival_time: Optional[float] = None
    distance_remaining: float = 0.0
    source_frame_id: int = 0
    movement_reason: str = ""
    degraded: bool = False                                             # 缺 walk 素材时的 DEGRADED_WALK_VISUAL
    drag_active: bool = False

    @property
    def anchor(self) -> SpatialPoint:
        return self.position

    def to_dict(self) -> dict:
        tp = self.target_position.to_tuple() if self.target_position else None
        return {
            "state": self.state,
            "position": self.position.to_tuple(),
            "current_screen": self.current_screen,
            "target_type": self.target_type,
            "target_position": tp,
            "target_zone": self.target_zone,
            "facing": self.facing,
            "velocity": round(self.velocity, 3),
            "speed": round(self.speed, 3),
            "moving": self.moving,
            "arrived": self.arrived,
            "distance_remaining": round(self.distance_remaining, 2),
            "source_frame_id": self.source_frame_id,
            "movement_reason": self.movement_reason,
            "degraded": self.degraded,
        }


# ---------------------------------------------------------------- MovementPlan（§20）
@dataclass
class MovementPlan:
    """一段可执行的移动计划。只含空间参数，**不含任何后端内部状态**。"""
    intent: str = SpatialIntent.NONE.value
    start: SpatialPoint = field(default_factory=SpatialPoint)
    target: SpatialPoint = field(default_factory=SpatialPoint)
    target_type: str = TargetType.CURRENT.value
    target_zone: str = ""
    speed_semantic: str = SpeedSemantic.NORMAL.value
    speed_px_sec: float = 60.0
    arrival_radius: float = 20.0
    facing_policy: str = "HORIZONTAL"     # HORIZONTAL / FACE_USER / FACE_SCREEN
    pre_move_delay: float = 0.0           # 起步犹豫（秒）
    interruptible: bool = True
    source_frame_id: int = 0
    reason: str = ""
    activity: str = "idle"
    # ---- Phase 13C：Path semantics（不同意图 → 不同几何，而非直击目标）----
    path_style: str = "DIRECT_SOFT"       # DIRECT_SOFT/CURVED_APPROACH/ARC_WITHDRAW/WANDER_MEANDER/EXPLORE_MULTI_POINT/REPOSITION_SHORT
    waypoints: list = field(default_factory=list)   # list[SpatialPoint] 中间点（不含起点/终点）

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "start": self.start.to_tuple(),
            "target": self.target.to_tuple(),
            "target_type": self.target_type,
            "target_zone": self.target_zone,
            "speed_semantic": self.speed_semantic,
            "speed_px_sec": round(self.speed_px_sec, 3),
            "arrival_radius": self.arrival_radius,
            "facing_policy": self.facing_policy,
            "pre_move_delay": round(self.pre_move_delay, 3),
            "interruptible": self.interruptible,
            "source_frame_id": self.source_frame_id,
            "reason": self.reason,
            "path_style": self.path_style,
            "waypoints": [w.to_tuple() for w in self.waypoints],
        }


# ---------------------------------------------------------------- 集中参数（§46/§48/§65/§72/§75/§85）
@dataclass
class SpatialConfig:
    """所有空间参数集中在此（不做魔法数字散落）。"""
    # --- 速度映射（px/s）：motion.speed_semantic / body.movement_tempo → 实际速度 ---
    speed_px: Dict[str, float] = field(default_factory=lambda: {
        "very_slow": 12.0, "slow": 28.0, "normal": 60.0, "lively": 95.0, "energetic": 140.0,
    })
    # --- 到达 / 过头 ---
    arrival_radius: float = 20.0            # foot 距目标 <= threshold → arrived
    # --- NEAR / FAR hysteresis（§28：距离偏好，不是命令）---
    near_radius: float = 260.0              # 距用户 <= 此 → 已足够近，不重复靠近
    far_radius: float = 640.0               # 距用户 >= 此 → 已足够远，不重复远离
    # --- 加速（ease-in / cruise / ease-out，非物理）---
    ease_in_accel: float = 240.0            # px/s^2 起步加速
    ease_out_decel: float = 200.0           # px/s^2 到站减速
    # --- 起步犹豫 / 过渡风格 ---
    hes_age_scale: float = 0.45             # hesitation(0..1) → 起步延迟（秒）尺度
    max_pre_move_delay: float = 2.0
    # --- 目标滞后（§75/§76）---
    target_change_threshold: float = 40.0   # < 此距离变化 → 不重规划
    significant_target_change: float = 200.0  # >= 此距离变化 → 明确重规划
    # --- 用户安全区（§43：不遮挡正文/按钮/窗口中心）---
    user_safe_gap: float = 70.0             # 距活动窗口边缘的安全间隔
    user_safe_side_offset: float = 50.0     # 侧边贴靠时的外侧偏移
    # --- 安静共存 / 停顿（§72/§105）---
    minimum_dwell: float = 12.0             # 到站后最小停留
    movement_cooldown: float = 24.0         # 再次自主移动冷却
    # --- 手动拖拽 grace（§85）---
    manual_position_grace: float = 15.0
    # --- 屏幕 / 边界（§39）---
    edge_margin: float = 24.0               # 离屏幕边缘的最小间距
    # --- 长跑保护 ---
    max_dt: float = 0.25                    # 每 tick 最大 dt（防大跳/瞬移）
    stuck_epsilon: float = 1.0              # 速度低且距目标变化 < 此 → 记 stuck
    stuck_tick_limit: int = 600             # 连续 stuck tick 上限（> 判卡死并兜底）

    @classmethod
    def default(cls) -> "SpatialConfig":
        return cls()
