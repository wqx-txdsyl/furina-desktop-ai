"""Phase 12 SpatialPlanner —— 空间意图 → MovementPlan（语义目标 → 几何坐标）。

**边界**：只做空间规划（去哪 / 怎么走 / 什么时候到）。**不做**：
  - 是否想接近用户 / 是否孤独 / 是否该陪用户（→ 冻结后端）
  - 读 Needs / Emotion / Relationship / Memory / Identity

本层消费：ResolvedIntent + 当前位置(foot anchor) + DesktopWorld 几何。
输出：MovementPlan（含语义 target_type + foot anchor 目标坐标），或 None（不移动）。

geometry 说明（§37/§38）：本层所有"位置"都是 **foot anchor（脚底中点）**；
与 FurinaWindow.set_position(pos) 的互转由 PositionAdapter 完成（runtime.py）。
"""
from __future__ import annotations

import random
from typing import List, Optional

from ..world import DesktopWorld
from .model import (Facing, MovementPlan, ResolvedIntent, SpatialIntent,
                    SpatialPoint, SpeedSemantic, SpatialConfig, TargetType)

RNG = random.Random()


class SpatialPlanner:
    """把已解析的空间意图翻译为可执行的 MovementPlan（含 safe 几何目标）。"""

    def __init__(self, world: DesktopWorld, config: Optional[SpatialConfig] = None,
                 rng: Optional[random.Random] = None) -> None:
        self.world = world
        self.config = config or SpatialConfig.default()
        self.rng = rng or RNG
        self._wander_multi = True   # Phase 13C：长距离 wander 用多中间点（EXPLORE_MULTI_POINT）

    # ========================================================== 入口
    def plan(self, decision: ResolvedIntent, current: SpatialPoint,
             char_w: float, char_h: float) -> Optional[MovementPlan]:
        """给定空间意图 + 当前位置 → 移动计划（或 None=不移动）。"""
        intent = decision.intent
        speed = self.config.speed_px.get(decision.speed_semantic, self.config.speed_px["normal"])
        arrival = self.config.arrival_radius

        # NONE：默认不自主移动（§30）。仅当我后端 activity 明确"走动/探索"时，才允许踱步。
        if intent == SpatialIntent.NONE.value:
            if not decision.wander_allowed:
                return None
            target = self._open_area_target(current, char_w, char_h)
            if target is None:
                return None
            return self._plan(target=target, decision=decision, current=current,
                              target_type=TargetType.OPEN_DESKTOP_AREA,
                              target_zone="open", speed=speed, arrival=arrival, char_w=char_w, char_h=char_h)

        # MAINTAIN：保持现状，除非当前位置非法（§26）。
        if intent == SpatialIntent.MAINTAIN.value:
            if self._foot_valid(current.x, current.y, char_w, char_h):
                return None
            # 位置非法 → 就近修复
            target = self._nearest_valid(current, char_w, char_h)
            return self._plan(target=target, decision=decision, current=current,
                              target_type=TargetType.SAFE_FALLBACK, target_zone="safe",
                              speed=self.config.speed_px["slow"], arrival=arrival, char_w=char_w, char_h=char_h)

        # NEAR：hysteresis —— 已足够近 → 保持（§28）。
        if intent == SpatialIntent.NEAR.value:
            if self._already_near(current, char_w, char_h):
                return None
            return self._plan_near(decision, current, char_w, char_h, speed, arrival)

        # FAR：hysteresis —— 已足够远 → 保持（§28）。
        if intent == SpatialIntent.FAR.value:
            if self._already_far(current, char_w, char_h):
                return None
            return self._plan_far(decision, current, char_w, char_h, speed, arrival)

        # APPROACH：走向用户附近安全区（§25/§43），不是用户中心。
        if intent == SpatialIntent.APPROACH.value:
            return self._plan_near(decision, current, char_w, char_h, speed, arrival)

        # WITHDRAW：去更远的 safe 区（§27/§70）。
        if intent == SpatialIntent.WITHDRAW.value:
            return self._plan_far(decision, current, char_w, char_h, speed, arrival)

        # REPOSITION：小修正（§29）。
        if intent == SpatialIntent.REPOSITION.value:
            target = self._nearest_valid(current, char_w, char_h)
            return self._plan(target=target, decision=decision, current=current,
                              target_type=TargetType.CURRENT_NEIGHBORHOOD, target_zone="repair",
                              speed=speed, arrival=arrival, char_w=char_w, char_h=char_h)

        return None

    # ========================================================== 各意图目标
    def _plan_near(self, decision, current, char_w, char_h, speed, arrival) -> Optional[MovementPlan]:
        target = self._near_target(current, char_w, char_h)
        if target is None:
            return None
        return self._plan(target=target, decision=decision, current=current,
                          target_type=TargetType.NEAR_USER_SAFE, target_zone="near_user",
                          speed=speed, arrival=arrival, char_w=char_w, char_h=char_h)

    def _plan_far(self, decision, current, char_w, char_h, speed, arrival) -> Optional[MovementPlan]:
        target = self._far_target(current, char_w, char_h)
        if target is None:
            return None
        return self._plan(target=target, decision=decision, current=current,
                          target_type=TargetType.QUIET_CORNER, target_zone="far",
                          speed=speed, arrival=arrival, char_w=char_w, char_h=char_h)

    def _plan(self, *, target: SpatialPoint, decision: ResolvedIntent, current: SpatialPoint,
              target_type: str, target_zone: str, speed: float, arrival: float,
              char_w: float, char_h: float) -> MovementPlan:
        facing_policy, pre_delay = self._facing_and_delay(decision, target, current)
        path_style, waypoints = self._build_path(decision.intent, current, target, char_w, char_h)
        return MovementPlan(
            intent=decision.intent,
            start=current,
            target=target,
            target_type=target_type,
            target_zone=target_zone,
            speed_semantic=decision.speed_semantic,
            speed_px_sec=speed,
            arrival_radius=arrival,
            facing_policy=facing_policy,
            pre_move_delay=pre_delay,
            interruptible=True,
            source_frame_id=decision.source_frame_id,
            reason=decision.reason,
            activity=decision.activity,
            path_style=path_style,
            waypoints=waypoints,
        )

    # ============================================================ Phase 13C：Path semantics（§4-§9）
    def _build_path(self, intent: str, start: SpatialPoint, target: SpatialPoint,
                    char_w: float, char_h: float) -> tuple:
        """不同空间意图 → 不同**几何**（非直击目标），但保证安全、不抖动、不每帧重规划。"""
        style = "DIRECT_SOFT"
        waypoints: list = []
        dx = target.x - start.x
        dy = target.y - start.y
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < 1e-6:
            return style, waypoints
        # 垂直方向（画弧用）
        nlen = max(1e-6, dist)
        px, py = -dy / nlen, dx / nlen   # 垂直单位向量
        if intent == SpatialIntent.APPROACH.value or intent == SpatialIntent.NEAR.value:
            # CURVED_APPROACH：轻微侧向弯曲靠近（不 orbit、不 zigzag）。C-R1.7：Catmull-Rom 平滑，方向连续变化。
            style = "CURVED_APPROACH"
            lat = min(60.0, dist * 0.18) * self._lat_sign(start, target)
            mid = SpatialPoint((start.x + target.x) / 2 + px * lat,
                               (start.y + target.y) / 2 + py * lat)
            waypoints = self._smooth_curve([start, mid, target], n=10)
        elif intent == SpatialIntent.WITHDRAW.value or intent == SpatialIntent.FAR.value:
            # ARC_WITHDRAW：先横向转身一点点再拉开距离（C-R1.7 平滑）。
            style = "ARC_WITHDRAW"
            lat = min(45.0, dist * 0.14) * self._lat_sign(start, target)
            turn = SpatialPoint(start.x + px * lat, start.y + py * lat)
            mid = SpatialPoint((turn.x + target.x) / 2, (turn.y + target.y) / 2)
            waypoints = self._smooth_curve([SpatialPoint(start.x, start.y), turn, mid, target], n=10)
        elif intent == SpatialIntent.REPOSITION.value:
            # REPOSITION_SHORT：小幅修正，直接
            style = "REPOSITION_SHORT"
        else:
            # NONE + wander_allowed / 其它自主 → WANDER_MEANDER 或 EXPLORE_MULTI_POINT
            if getattr(self, "_wander_multi", False) and dist > 260:
                style = "EXPLORE_MULTI_POINT"
                waypoints = self._explore_waypoints(start, target, char_w, char_h)
            else:
                style = "WANDER_MEANDER"
                mid = SpatialPoint((start.x + target.x) / 2 + self.rng.uniform(-40, 40),
                                   (start.y + target.y) / 2 + self.rng.uniform(-40, 40))
                waypoints = [self._clamp_point(mid, char_w, char_h)]
        return style, waypoints

    def _smooth_curve(self, pts: list, n: int = 10) -> list:
        """C-R1.7：Catmull-Rom 把稀疏控制点平滑为密集采样点（方向连续，无尖锐折角）。"""
        if len(pts) < 3:
            return [self._clamp_point(p, 256, 360) for p in pts[1:-1]]
        import math
        out = []
        # 简化：分段二次 Catmull-Rom，pts[0] 与 pts[-1] 为端点，中间为控制点
        for i in range(len(pts) - 1):
            p0 = pts[max(0, i - 1)]
            p1 = pts[i]
            p2 = pts[i + 1]
            p3 = pts[min(len(pts) - 1, i + 2)]
            for s in range(n):
                t = s / n
                t2, t3 = t * t, t * t * t
                x = 0.5 * ((2 * p1.x) + (-p0.x + p2.x) * t +
                           (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2 +
                           (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * t3)
                y = 0.5 * ((2 * p1.y) + (-p0.y + p2.y) * t +
                           (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t2 +
                           (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * t3)
                out.append(SpatialPoint(x, y))
        # 去重紧邻点，避免零步长
        dedup = []
        for p in out:
            if not dedup or dedup[-1].distance(p) > 3.0:
                dedup.append(p)
        return dedup

    def _lat_sign(self, start: SpatialPoint, target: SpatialPoint) -> float:
        # 确定性侧向（避免每次同一个方向）—— 用起点/目标相对位置决定
        return 1.0 if ((start.x + start.y) % 2) < 1.0 else -1.0

    def _explore_waypoints(self, start: SpatialPoint, target: SpatialPoint,
                           char_w: float, char_h: float) -> list:
        cands = self._open_area_targets(start, char_w, char_h, n=20)
        if not cands:
            return []
        # 取 2-3 个在"起点与目标之间走廊"附近的点，制造有头有尾的探索感
        mid_x = (start.x + target.x) / 2
        mid_y = (start.y + target.y) / 2
        near = [p for p in cands if abs(p.x - mid_x) < 320 and abs(p.y - mid_y) < 320]
        pool = near or cands
        picks = []
        for _ in range(min(3, len(pool))):
            p = pool.pop(self.rng.randrange(len(pool)))
            # C-R1.7：有界抖动 + 安全校验（explore 非固定网格点）
            jit = SpatialPoint(p.x + self.rng.uniform(-60, 60), p.y + self.rng.uniform(-60, 60))
            picks.append(self._clamp_point(jit, char_w, char_h))
        return picks

    def _clamp_point(self, p: SpatialPoint, char_w: float, char_h: float) -> SpatialPoint:
        if self._foot_valid(p.x, p.y, char_w, char_h):
            return p
        fix = self._nearest_valid(p, char_w, char_h)
        return fix if fix is not None else p

    # ========================================================== geometry helpers
    def _user_point(self) -> Optional[SpatialPoint]:
        """用户位置（活动窗口中心）用于 NEAR/FAR hysteresis。无窗口 → None。"""
        r = self.world.active_window_rect
        if r is None or r.w <= 0:
            return None
        return SpatialPoint(r.cx, r.cy)

    def _near_target(self, current: SpatialPoint, char_w: float, char_h: float) -> Optional[SpatialPoint]:
        """用户附近安全区（foot anchor）。优先 bottom-edge / 侧边，不贴窗口中心。"""
        cands = self.world.window_edge_candidates(char_w, char_h)
        foot_cands = [SpatialPoint(c.x + char_w / 2, c.y + char_h) for c in cands]
        foot_cands = [p for p in foot_cands if self._foot_valid(p.x, p.y, char_w, char_h)]
        if not foot_cands:
            up = self._user_point()
            if up is None:
                return None
            # 兜底：用户窗口下方一点
            screen = self.world.current_screen_for_point(up.x, up.y)
            fx = max(screen.x + self.config.edge_margin + char_w / 2,
                     min(up.x, screen.x + screen.w - self.config.edge_margin - char_w / 2))
            fy = max(screen.y + self.config.edge_margin + char_h,
                     min(screen.y + screen.h - self.world.taskbar_height - self.config.edge_margin - char_h,
                         up.y + char_h))
            return SpatialPoint(fx, fy)
        return min(foot_cands, key=lambda p: p.distance(current))

    def _far_target(self, current: SpatialPoint, char_w: float, char_h: float) -> Optional[SpatialPoint]:
        """更远的安全区（增大与用户的距离）。按"距用户"远近来选最远的若干等价候选。"""
        up = self._user_point()
        candidates = self._open_area_targets(current, char_w, char_h, n=16)
        if not candidates:
            return self._quiet_corner(char_w, char_h)
        if up is not None:
            # 按距用户距离从大到小排，取最远的一档（等价候选内随机）
            candidates.sort(key=lambda p: p.distance(up), reverse=True)
            top = [p for p in candidates[:4]]
            return self.rng.choice(top)
        # 无用户窗口 → 安静角
        return self._quiet_corner(char_w, char_h)

    def _open_area_target(self, current: SpatialPoint, char_w: float, char_h: float) -> Optional[SpatialPoint]:
        cands = self._open_area_targets(current, char_w, char_h, n=12)
        if not cands:
            return None
        pick = self.rng.choice(cands)
        # C-R1.7：有界位置抖动 + 重新校验 safe zone（避免 wander/explore 只落在固定网格点）
        jit = SpatialPoint(pick.x + self.rng.uniform(-46, 46), pick.y + self.rng.uniform(-46, 46))
        return self._clamp_point(jit, char_w, char_h)

    def _open_area_targets(self, current: SpatialPoint, char_w: float, char_h: float,
                           n: int = 12) -> List[SpatialPoint]:
        """可用区域内的安全候选点（foot anchor），回避边缘与当前位置的极小邻域。"""
        screen = self.world.current_screen_for_point(current.x, current.y)
        avail = self.world.available_bounds(screen)
        cfg = self.config
        out: List[SpatialPoint] = []
        # 用确定性网格采样（避免每帧 random 抖动；等价候选最后才 random）
        cols = 4
        rows = 3
        for i in range(cols):
            for j in range(rows):
                fx = avail.x + (avail.w - char_w) * (0.12 + 0.76 * (i + 0.5) / cols)
                fy = avail.y + char_h + (avail.h - char_h * 2) * (0.08 + 0.84 * (j + 0.5) / rows)
                fx = max(avail.x + cfg.edge_margin + char_w / 2,
                         min(fx, avail.x + avail.w - cfg.edge_margin - char_w / 2))
                fy = max(avail.y + cfg.edge_margin + char_h,
                         min(fy, avail.y + avail.h - cfg.edge_margin - char_h))
                p = SpatialPoint(fx, fy)
                if not self._foot_valid(p.x, p.y, char_w, char_h):
                    continue
                # 回避当前极小邻域（避免原地打转）
                if current.distance(p) < cfg.stuck_epsilon + 40:
                    continue
                out.append(p)
        if not out:
            near = self._nearest_valid(current, char_w, char_h)
            if near is not None:
                out.append(near)
        # Phase 13C：Wander 应是**中等距离hop + 停留**（§8）——偏好 120..420px 的候选，
        # 并加有界随机抖动（§10 不抖动目标本身，只在等价候选中挑）。避免"巡逻机器人"也避免原地。
        band = [p for p in out if 120.0 <= current.distance(p) <= 420.0]
        if band:
            out = band
        return out[:n]

    def _quiet_corner(self, char_w: float, char_h: float) -> SpatialPoint:
        """远离用户的安静角（foot anchor）。"""
        world = self.world
        avail = world.available_bounds()
        corners = [
            SpatialPoint(avail.x + self.config.edge_margin + char_w / 2,
                         avail.y + self.config.edge_margin + char_h),
            SpatialPoint(avail.x + avail.w - self.config.edge_margin - char_w / 2,
                         avail.y + self.config.edge_margin + char_h),
            SpatialPoint(avail.x + self.config.edge_margin + char_w / 2,
                         avail.y + avail.h - self.config.edge_margin - char_h),
            SpatialPoint(avail.x + avail.w - self.config.edge_margin - char_w / 2,
                         avail.y + avail.h - self.config.edge_margin - char_h),
        ]
        up = self._user_point()
        if up is None:
            return corners[3]
        return max(corners, key=lambda p: p.distance(up))

    def _nearest_valid(self, current: SpatialPoint, char_w: float, char_h: float) -> Optional[SpatialPoint]:
        """就近安全修复（foot anchor）。"""
        screen = self.world.current_screen_for_point(current.x, current.y)
        if self._foot_valid(current.x, current.y, char_w, char_h):
            return current
        sz = self.world.safe_zone(char_w, char_h, screen)
        topleft_x = max(sz.x, min(current.x - char_w / 2, sz.x + sz.w))
        topleft_y = max(sz.y, min(current.y - char_h, sz.y + sz.h))
        return SpatialPoint(topleft_x + char_w / 2, topleft_y + char_h)

    # ========================================================== validity / hysteresis
    def _foot_valid(self, fx: float, fy: float, char_w: float, char_h: float) -> bool:
        screen = self.world.current_screen_for_point(fx, fy)
        return self.world.is_valid_position(fx - char_w / 2, fy - char_h, char_w, char_h, screen)

    def _already_near(self, current: SpatialPoint, char_w: float, char_h: float) -> bool:
        up = self._user_point()
        if up is None:
            return True   # 无用户窗口 → 无需"靠近"
        # 已足够近（距用户 <= near_radius）→ 保持
        return current.distance(up) <= self.config.near_radius

    def _already_far(self, current: SpatialPoint, char_w: float, char_h: float) -> bool:
        up = self._user_point()
        if up is None:
            return False
        return current.distance(up) >= self.config.far_radius

    # ========================================================== facing / delay
    @staticmethod
    def _facing_and_delay(decision: ResolvedIntent, target: SpatialPoint, current: SpatialPoint) -> tuple:
        dx = target.x - current.x
        if abs(dx) < 2.0:
            facing = Facing.FRONT.value
            policy = "HORIZONTAL"
        else:
            facing = Facing.RIGHT.value if dx > 0 else Facing.LEFT.value
            policy = "HORIZONTAL"
        # 犹豫 → 起步延迟（§65）；过渡风格调制（§66）
        delay = decision.hesitation * 1.6
        style = (decision.transition_style or "SMOOTH").upper()
        if style == "HESITANT":
            delay = max(delay, decision.hesitation * 2.0)
        elif style == "RELUCTANT":
            delay = max(delay, 0.35 + decision.hesitation * 1.2)
        elif style == "ENERGETIC":
            delay = min(delay, 0.08)
        elif style == "GENTLE":
            delay *= 0.8
        elif style == "SMOOTH":
            delay *= 0.6
        return policy, round(min(2.0, max(0.0, delay)), 3)
