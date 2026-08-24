"""Phase 12 DesktopSpatialRuntime —— 空间层唯一移动所有者（state machine + dt 移动）。

**所有权**：Spatial Runtime 是自主移动的唯一 owner（§120）：
  - 决定"去哪 / 怎么走 / 什么时候到 / 是否被拖拽打断"。
  - Scheduler / Window 不再拥有自主移动状态（Phase 12 迁移）。
  - AnimationRuntime 只据此决定**视觉**（walk / facing / 生命周期）；
    SpatialRuntime 不操作 Speech / Relationship / Memory / Emotion（§123-§126）。

**坐标系**：位置一律为 foot anchor（脚底中点，屏幕 logical pixel），与
FurinaWindow.set_position(pos) 的互转走 PositionAdapter。

**可 headless 测试**：时钟由 tick(now=...) 注入；window 可为 duck-typed fake
（有 set_position / pos / width / _side / _char_h / _char_w / dragging）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from furina.core import EventBus, EventType, get_logger

from ..world import DesktopWorld
from .model import (Facing, FrontendSpatialState, MovementPlan, ResolvedIntent,
                    SpatialPoint, SpatialConfig, SpatialIntent, SpatialState, TargetType)
from .planner import SpatialPlanner

log = get_logger("runtime.spatial")

# 空间优先级（§86：交互/生命高优先可打断 grace；普通自主等待）
SP_CRITICAL = 100      # drag / 强制覆盖
SP_LIFE = 80           # APPROACH/WITHDRAW（明确生命意图）
SP_ACTIVITY = 60       # NEAR/FAR/REPOSITION
SP_AUTONOMY = 30       # wander / MAINTAIN（低优先自主）


# ---------------------------------------------------------------- foot ↔ set_position(pos)
class PositionAdapter:
    """foot anchor ↔ FurinaWindow.set_position(pos) 坐标互转（§37/§38）。

    - 角色在窗口水平居中：char center-x = pos.x - side + window_w/2
        → pos.x = foot.x - window_w/2 + side
    - 角色脚底 = 窗口内容区顶部 + char_h（无气泡下移时）: char on-screen top = pos.y
        → pos.y = foot.y - char_h
    """

    def __init__(self, char_w: float, char_h: float, side: float, top: float,
                 window_w: float) -> None:
        self.char_w = char_w
        self.char_h = char_h
        self.side = side
        self.top = top
        self.window_w = window_w

    @classmethod
    def from_window(cls, win) -> "PositionAdapter":
        return cls(
            char_w=float(getattr(win, "_char_w", 256)),
            char_h=float(getattr(win, "_char_h", 360)),
            side=float(getattr(win, "_side", 24)),
            top=float(getattr(win, "_top", 120)),
            window_w=float(_safe_width(win)),
        )

    def foot_to_pos(self, fx: float, fy: float) -> tuple:
        return (fx - self.window_w / 2 + self.side, fy - self.char_h)

    def pos_to_foot(self, x: float, y: float) -> SpatialPoint:
        return SpatialPoint(x + self.window_w / 2 - self.side, y + self.char_h)


def _safe_width(win) -> float:
    try:
        return float(win.width())
    except Exception:
        return float(getattr(win, "_char_w", 256) + 2 * getattr(win, "_side", 24))


# ================================================================ Runtime
class DesktopSpatialRuntime:
    def __init__(self, world: DesktopWorld, config: Optional[SpatialConfig] = None,
                 bus: Optional[EventBus] = None, char_w: float = 256.0,
                 char_h: float = 360.0, window=None, rng=None) -> None:
        self.world = world
        self.config = config or SpatialConfig.default()
        self.bus = bus
        self.window = window
        self.adapter = PositionAdapter.from_window(window) if window is not None else PositionAdapter(
            char_w, char_h, 24.0, 120.0, char_w + 48.0)
        self.planner = SpatialPlanner(world, self.config, rng=rng)

        self.state = FrontendSpatialState()
        self._current_plan: Optional[MovementPlan] = None
        self._pending_plan: Optional[MovementPlan] = None
        self._priority = SP_AUTONOMY
        self._now = 0.0
        self._last_now = 0.0
        self._dt = 0.0
        # gate / timers
        self._dwell_since = 0.0
        self._cooldown_until = 0.0
        self._grace_until = 0.0
        self._prepare_started_at = 0.0
        self._waypoints = []        # Phase 13C：当前路径中间点
        self._last_target_for_hyst: Optional[SpatialPoint] = None
        self._arrived_emitted_for: Optional[SpatialPoint] = None
        self._last_pos_for_stuck = SpatialPoint()
        self._stuck_ticks = 0
        self._sleep_block = False
        # stats
        self.stats = {
            "plans": 0, "starts": 0, "arrivals": 0, "interruptions": 0,
            "replans": 0, "pending_replacements": 0, "distance_traveled": 0.0,
            "out_of_bounds": 0, "overshoots": 0, "stuck": 0, "duplicate_arrivals": 0,
            "drag_grabs": 0, "drag_releases": 0,
        }

    # ================================================== 事件发射（exactly-once）
    def _emit(self, ev_type: str, payload: dict) -> None:
        if self.bus is None:
            return
        try:
            self.bus.emit(EventType(ev_type), payload=payload, source="spatial")
        except Exception:
            pass

    # ================================================== 位置初始化
    def set_initial_foot(self, fx: float, fy: float) -> None:
        self.state.position = SpatialPoint(fx, fy)
        self.state.anchor_position = self.state.position
        self._last_pos_for_stuck = SpatialPoint(fx, fy)

    def sync_from_window(self) -> None:
        """从 window.pos 读回 foot（启动/拖拽后用；窗口是坐标真相来源之一）。"""
        if self.window is None:
            return
        pos = getattr(self.window, "pos", None)
        if pos is None:
            return
        foot = self.adapter.pos_to_foot(pos.x, pos.y)
        self.state.position = foot
        self.state.anchor_position = foot
        self._last_pos_for_stuck = SpatialPoint(foot.x, foot.y)
        self.state.current_screen = self.world.screen_index_for_point(foot.x, foot.y)

    # ================================================== 输入：新空间意图
    def accept(self, decision: ResolvedIntent, now: float | None = None,
               char_w: float | None = None, char_h: float | None = None) -> None:
        if now is not None:
            self._now = now
        cw = char_w or self.adapter.char_w
        ch = char_h or self.adapter.char_h

        # sleep → 禁止自主移动（§63）；wake(非 sleeping posture) → 允许（§64）。
        activity = decision.activity or ""
        if activity in ("sleep", "nap"):
            self._sleep_block = True
            self._discard_plan()
            return
        if activity not in ("sleep", "nap"):
            self._sleep_block = False

        plan = self.planner.plan(decision, self.state.position, cw, ch)
        if plan is None:
            return

        plan_pri = self._plan_priority(plan)
        plan = self._apply_dwell_cooldown(plan, plan_pri)
        if plan is None:
            return

        # 目标滞后（§75/§76）：target 仅小幅移动且当前含该计划 → 不重新规划
        if self._should_skip_replan(plan):
            return

        can_interrupt = self._can_interrupt_now(plan_pri)
        if can_interrupt:
            if self._current_plan is not None and self.state.moving:
                # 已在移动 → 重规划/打断（§77：调整路径，不 restart walk 入口）
                self.stats["interruptions"] += 1
                self._emit("runtime.movement_interrupted", self._payload("replan"))
            self._start_plan(plan, plan_pri, now)
        else:
            # 存 pending（单槽，替换旧 pending；§62：普通自主在 critical transition 期间等待）
            if self._pending_plan is not None:
                self.stats["pending_replacements"] += 1
            self._pending_plan = plan

    def _payload(self, reason: str) -> dict:
        p = self._current_plan
        return {
            "reason": reason,
            "intent": (p.intent if p else ""),
            "target_type": (p.target_type if p else ""),
            "source_frame_id": (p.source_frame_id if p else 0),
        }

    # ================================================== 优先级 / 打断
    def _plan_priority(self, plan: MovementPlan) -> int:
        intent = plan.intent
        if plan.target_type == TargetType.DRAG_RELEASE.value:
            return SP_CRITICAL
        if intent in (SpatialIntent.APPROACH.value, SpatialIntent.WITHDRAW.value):
            return SP_LIFE
        if intent in (SpatialIntent.NEAR.value, SpatialIntent.FAR.value, SpatialIntent.REPOSITION.value):
            return SP_ACTIVITY
        return SP_AUTONOMY

    def _can_interrupt_now(self, new_pri: int) -> bool:
        if self.state.state in (SpatialState.DRAGGED.value,):
            return False   # 拖拽优先（§80）；能否覆盖 grace 由 grace 后决定
        return new_pri >= self._priority

    def _should_skip_replan(self, plan: MovementPlan) -> bool:
        """目标滞后：当前已向某目标移动，且新目标与旧目标仅小幅变化 → 不重规划。"""
        if self.state.state in (SpatialState.MOVING.value, SpatialState.ARRIVING.value,
                                SpatialState.PREPARING.value, SpatialState.STARTING.value):
            old = self._current_plan
            if old is not None:
                delta = old.target.distance(plan.target)
                if delta <= self.config.target_change_threshold:
                    self.stats["replans"] += 0
                    return True
                if delta > self.config.significant_target_change:
                    self.stats["replans"] += 1
        return False

    def _apply_dwell_cooldown(self, plan: MovementPlan, pri: int) -> Optional[MovementPlan]:
        """wander / 低优先自主：受 minimum_dwell + movement_cooldown 约束（§72/§73）。

        高优先生命意图(APPROACH/WITHDRAW) 不受普通 cooldown 限制——仍可立即走。
        """
        if pri < SP_LIFE:
            if self._now < self._cooldown_until:
                # 仍在 cooldown → 不发起新自主移动（不变成巡逻机器人）
                self._discard(plan)
                return None
            if self.state.arrived and (self._now - self._dwell_since) < self.config.minimum_dwell:
                self._discard(plan)
                return None
        return plan

    # ================================================== 主循环（QTimer 驱动）
    def tick(self, now: float | None = None, char_w: float | None = None,
             char_h: float | None = None) -> None:
        prev = self._now
        self._now = now if now is not None else self._now
        self._dt = min(self.config.max_dt, max(0.0, self._now - prev))
        cw = char_w or self.adapter.char_w
        ch = char_h or self.adapter.char_h

        # 拖拽中：不自主移动（§82），不推进计划
        if self.state.drag_active:
            return

        # 目标改变后需重校验（§91 screen 变化/窗口外）——尽量早做
        self._revalidate(now, cw, ch)

        st = self.state.state
        if st == SpatialState.ARRIVED.value:
            # 到站停留；grace / cooldown 过后由 accept 决定是否再动
            self._dwell_heartbeat(now)
            self._apply_position(cw, ch)
            return
        if st == SpatialState.IDLE.value:
            self._flush_pending(cw, ch)
            self._apply_position(cw, ch)
            return

        # PREPARING → STARTING → MOVING → ARRIVING
        if st == SpatialState.PREPARING.value:
            if self._now - self._prepare_started_at >= (self._current_plan.pre_move_delay if self._current_plan else 0):
                self._enter_starting(now)
            self._apply_position(cw, ch)
            return

        if st == SpatialState.STARTING.value:
            self._ensure_started(now)   # 起步加速 -> MOVING
            return

        if st == SpatialState.MOVING.value:
            self._move(now, cw, ch)
            return

        if st == SpatialState.ARRIVING.value:
            self._move(now, cw, ch)
            return

    # ================================================== 状态推进
    def _start_plan(self, plan: MovementPlan, pri: int, now: float) -> None:
        if self.state.moving and self.state.state in (SpatialState.MOVING.value, SpatialState.ARRIVING.value):
            self.stats["interruptions"] += 1
            self._emit("runtime.movement_interrupted", self._payload("interrupt"))
        self._current_plan = plan
        self._priority = pri
        self.state.target_type = plan.target_type
        self.state.target_zone = plan.target_zone
        self.state.target_position = plan.target
        self.state.movement_reason = plan.reason
        self.state.source_frame_id = plan.source_frame_id
        self.state.speed = plan.speed_px_sec
        self.state.moving = True
        self.state.arrived = False
        self.state.velocity = 0.0
        self._arrived_emitted_for = None
        self._last_target_for_hyst = SpatialPoint(plan.target.x, plan.target.y)
        self._prepare_started_at = now
        self.stats["plans"] += 1
        self._waypoints = list(plan.waypoints or [])   # Phase 13C：路径中间点
        if plan.pre_move_delay > 0.01:
            self.state.state = SpatialState.PREPARING.value
        else:
            self.state.state = SpatialState.STARTING.value
        self._emit("runtime.movement_started", self._payload("start"))

    def _enter_starting(self, now: float) -> None:
        self.state.state = SpatialState.STARTING.value
        self._ensure_started(now)

    def _ensure_started(self, now: float) -> None:
        p = self._current_plan
        if p is None:
            return
        self.stats["starts"] += 1
        self.state.state = SpatialState.MOVING.value
        self.state.movement_started_at = now
        self.state.velocity = self.state.velocity or min(self.config.speed_px.get("slow", 28.0), p.speed_px_sec)
        self._move_now(now)

    def _delta_remaining(self) -> float:
        p = self._current_plan
        if p is None:
            return 0.0
        return self.state.position.distance(p.target)

    def _move(self, now: float, cw: float, ch: float) -> None:
        p = self._current_plan
        if p is None:
            self.state.state = SpatialState.IDLE.value
            return
        self._move_now(now)   # Phase 13C：沿路径（_move_now 内处理 waypoint 推进与最终到达）
        self._update_stuck()

    def _move_now(self, now: float) -> None:
        p = self._current_plan
        if p is None:
            return
        dt = self._dt
        cur = self.state.position
        # Phase 13C：沿路径（中间点 → 目标），而非每帧直击最终目标
        goal, final = self._goal()
        dist = cur.distance(goal)
        # 到达一个中间点 → 前进到下一个（不 arrive，不重复重规划）
        if not final and dist <= max(p.arrival_radius, 8.0):
            if self._waypoints:
                self._waypoints.pop(0)
            return
        if final and dist <= p.arrival_radius:
            self._arrive(now)
            return
        if dist <= 1e-6:
            return
        dirx = (goal.x - cur.x) / dist
        diry = (goal.y - cur.y) / dist
        # ease-in：起步加速（§50）
        target_speed = p.speed_px_sec
        self.state.velocity = min(target_speed, self.state.velocity + self.config.ease_in_accel * dt)
        # ease-out：接近目标时减速（避免冲过头）
        remaining = dist
        decel_zone = (self.state.velocity * self.state.velocity) / (2 * self.config.ease_out_decel)
        if remaining <= decel_zone:
            self.state.velocity = max(10.0, (2 * self.config.ease_out_decel * remaining) ** 0.5)
        # 步长 = speed*dt，切到剩余距离（§52 禁止过头）
        step = min(self.state.velocity * dt, remaining)
        nx = cur.x + dirx * step
        ny = cur.y + diry * step
        # 夹到安全区（最后保险 §40；正常计划不应触发）
        if not self._foot_valid(nx, ny):
            self.stats["out_of_bounds"] += 1
            clipped = self.planner._nearest_valid(SpatialPoint(nx, ny), self.adapter.char_w, self.adapter.char_h)
            if clipped is not None:
                nx, ny = clipped.x, clipped.y
        self.stats["distance_traveled"] += step
        self.state.position = SpatialPoint(nx, ny)
        self.state.anchor_position = self.state.position
        self.state.distance_remaining = max(0.0, self.state.position.distance(p.target))
        self.state.facing = self._facing_for_move(dirx)
        self.state.current_screen = self.world.screen_index_for_point(nx, ny)
        self._apply_position()

    def _goal(self) -> tuple:
        """当前应前往的目标点 + 是否最终目标（Phase 13C 路径跟随）。"""
        if getattr(self, "_waypoints", None):
            return self._waypoints[0], False
        p = self._current_plan
        return (p.target if p is not None else self.state.position), True

    def _arrive(self, now: float) -> None:
        p = self._current_plan
        self.state.position = SpatialPoint(p.target.x, p.target.y)
        self.state.anchor_position = self.state.position
        self.state.moving = False
        self.state.velocity = 0.0
        self.state.distance_remaining = 0.0
        self.state.state = SpatialState.ARRIVED.value
        self.state.arrived = True
        self.state.arrival_time = now
        self._waypoints = []
        self._dwell_since = now
        self._cooldown_until = now + self.config.movement_cooldown
        self.stats["arrivals"] += 1
        # exactly-once arrival（§94）
        key = (p.target.x, p.target.y)
        if self._arrived_emitted_for != key:
            self._arrived_emitted_for = key
            self._emit("runtime.target_reached", self._payload("arrive"))
        else:
            self.stats["duplicate_arrivals"] += 1
        self._apply_position()

    def _dwell_heartbeat(self, now: float) -> None:
        # grace 检查：手动挪过后，普通自主移动 waits（§85）；高优先 life intent 由 accept 判断
        if self._now >= self._grace_until:
            self._flush_pending()

    def _flush_pending(self, cw: float | None = None, ch: float | None = None) -> None:
        if self._pending_plan is None:
            return
        plan = self._pending_plan
        self._pending_plan = None
        self._start_plan(plan, self._plan_priority(plan), self._now)

    # ================================================== drag（§80-§87）
    def on_drag_start(self, now: float) -> None:
        self.stats["drag_grabs"] += 1
        # 中断自主移动（walk 视觉停），交给拖拽视觉（§82）
        if self.state.moving:
            self._emit("runtime.movement_interrupted", self._payload("drag"))
            self.stats["interruptions"] += 1
        self.state.drag_active = True
        self.state.state = SpatialState.DRAGGED.value
        self.state.moving = False
        self.state.velocity = 0.0
        self._current_plan = None    # 位置由鼠标接管（§83）；不在此重写窗口位置（抓取点在用户手里）

    def on_drag_move(self, now: float) -> None:
        # 不争坐标（§83）：window 自己跟随鼠标
        self._now = now

    def on_drag_release(self, now: float, commit: bool = True) -> None:
        self.stats["drag_releases"] += 1
        self.state.drag_active = False
        self.state.state = SpatialState.IDLE.value if commit else SpatialState.DRAGGED.value
        if commit:
            # 释放位置 = 新的空间真相（§84：不 snap 回自主目标）
            self.state.position = self._read_foot_from_window()
            self.state.anchor_position = self.state.position
            self.state.current_screen = self.world.screen_index_for_point(
                self.state.position.x, self.state.position.y)
            self._grace_until = now + self.config.manual_position_grace   # §85 grace
            self._cooldown_until = now + self.config.manual_position_grace
            self.state.arrived = True
            self._dwell_since = now
            self.state.state = SpatialState.ARRIVED.value
            self._emit("runtime.target_reached", {
                "reason": "drag_release", "target_type": TargetType.DRAG_RELEASE.value,
                "source_frame_id": self.state.source_frame_id})
        self._apply_position()

    def _read_foot_from_window(self) -> SpatialPoint:
        if self.window is None:
            return self.state.position
        pos = getattr(self.window, "pos", None)
        if pos is None:
            return self.state.position
        return self.adapter.pos_to_foot(pos.x, pos.y)

    # ================================================== 位置应用 / 校验
    def _apply_position(self, cw: float | None = None, ch: float | None = None) -> None:
        if self.window is None:
            return
        foot = self.state.position
        x, y = self.adapter.foot_to_pos(foot.x, foot.y)
        self.window.set_position(x, y)

    def _foot_valid(self, fx: float, fy: float) -> bool:
        return self.planner._foot_valid(fx, fy, self.adapter.char_w, self.adapter.char_h)

    def _revalidate(self, now: float, cw: float, ch: float) -> None:
        """屏幕几何/窗口外 → 就近修复（§91）。"""
        pos = self.state.position
        if not self._foot_valid(pos.x, pos.y):
            fix = self.planner._nearest_valid(pos, cw, ch)
            if fix is not None:
                self.state.position = SpatialPoint(fix.x, fix.y)
                self.state.anchor_position = self.state.position
                self._last_pos_for_stuck = SpatialPoint(fix.x, fix.y)

    def _update_stuck(self) -> None:
        pos = self.state.position
        moved = pos.distance(self._last_pos_for_stuck)
        p = self._current_plan
        low_speed = self.state.velocity < self.config.stuck_epsilon
        near_target = (p is not None and pos.distance(p.target) <= p.arrival_radius)
        if moved < self.config.stuck_epsilon and low_speed and not near_target:
            self._stuck_ticks += 1
            if self._stuck_ticks > self.config.stuck_tick_limit:
                self.stats["stuck"] += 1
                self._discard_plan()
                self.state.state = SpatialState.IDLE.value
                self._stuck_ticks = 0
        else:
            self._stuck_ticks = 0
        self._last_pos_for_stuck = SpatialPoint(pos.x, pos.y)

    def _discard_plan(self) -> None:
        self._current_plan = None
        self._pending_plan = None
        self.state.moving = False
        self.state.state = SpatialState.IDLE.value

    def _discard(self, plan: MovementPlan) -> None:
        pass

    # ================================================== facing
    @staticmethod
    def _facing_for_move(dirx: float) -> str:
        if dirx > 0.02:
            return Facing.RIGHT.value
        if dirx < -0.02:
            return Facing.LEFT.value
        return Facing.FRONT.value

    # ================================================== 输出（供 AnimationRuntime 消费）
    @property
    def is_moving(self) -> bool:
        return self.state.moving and self.state.state in (SpatialState.MOVING.value,
                                                          SpatialState.ARRIVING.value,
                                                          SpatialState.STARTING.value)

    def movement_visual(self) -> dict:
        moving = self.is_moving
        return {
            "moving": moving,
            "facing": self.state.facing if moving else Facing.FRONT.value,
            "degraded": getattr(self.state, "degraded", False),
            "state": self.state.state,
        }
