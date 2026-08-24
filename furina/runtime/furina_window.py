"""透明桌面窗口（plan/7 §12-16）。

whale-girl 式**小窗模型**：窗口 = 角色 + 边距（顶部留气泡、四周留阴影），
角色动 = 整窗 move()，**不用 setMask**、不用全屏大窗 → 高速拖拽稳定、无拖影/无不同步。
透明区域由 InteractionEngine 做分区 hitbox（头/身/脚/手/物）。
"""
from __future__ import annotations

import math
from typing import Callable, Optional

from PySide6.QtCore import QRectF, Qt, QPointF
from PySide6.QtGui import QImage, QPainter, QMouseEvent, QColor, QPen, QFont, QPolygonF, QAction
from PySide6.QtWidgets import QWidget, QMenu

from furina.core import get_logger
from . import input_router as _ir
from .asset_manager import AssetManager
from .renderer import RenderState
from .animation import AnimationController, AnimationSpec
from .world import DesktopWorld, Vec2

log = get_logger("runtime.window")

# 窗口边距（顶部留气泡、四周留阴影）
TOP = 120.0     # 头顶气泡区起点（角色动态下移以避开气泡；此为其最小下边界）
SIDE = 24.0     # 左右留白
BOTTOM = 28.0   # 脚下阴影留白
BUBBLE_AREA = 170.0   # 顶部为最长台词预留的高度（动态下移角色，避免气泡/角色被窗口顶边或底边截断）
# 气泡最小可用宽度：避免窗口过窄导致气泡溢出被裁成方形框
MIN_BUBBLE_W = 300.0
# 帧动画帧率：每帧固定停留 ~250ms（慢速逐帧切换，不连续平滑）—— 多帧图片切换而非“动画”
FRAME_ANIM_FPS = 4.0


class FurinaWindow(QWidget):
    def __init__(self, world: DesktopWorld, asset_mgr: AssetManager,
                 interaction_engine) -> None:
        super().__init__()
        self.world = world
        self.assets = asset_mgr
        char_w, char_h = self.assets.reference_size
        self._char_w = char_w
        self._char_h = char_h
        self._compute_margins()
        # 世界坐标（角色左上角）；窗口移动由 move() 完成
        self.pos = Vec2(world.screen.w / 2 + 200, world.screen.h - char_h - 60)
        self.dragging = False
        self.state = RenderState()
        self._posture = "standing"
        self._emotion = "neutral"
        self._gaze = "front"
        self._drag_offset = QPointF(0.0, 0.0)
        self.on_command: Optional[Callable[[str], None]] = None
        # Phase 12：拖拽开始/释放回调（由 SpatialRuntime 接管；View 只报告事件）
        self.on_drag_start: Optional[Callable[[], None]] = None
        self.on_drag_release: Optional[Callable[[], None]] = None
        # FIX E1：拖拽姿态 override 请求（由 AnimationRuntime 决定视觉；Window 只报告）
        self.on_drag_pose: Optional[Callable[[bool], None]] = None
        # 动画控制器
        self.anim = AnimationController(self.assets.load_path)
        self._scene_key = None
        self._breath_t = 0.0
        self._char_y = self._top    # 角色顶边（动态下移以避开气泡）
        self.show_debug = False   # 状态调试叠层（默认隐藏，FURINA_DEBUG=1 时显示）
        self._debug = ""
        # Phase 11：pure-view 状态（由 AnimationRuntime/MicroScheduler 喂，paintEvent 只读）
        self._visual_phase = "LOOP"
        self._target_pose = "standing"
        self._clip_name = ""
        self._breath = 0.5
        self._blink = 0.0
        self._micro: list = []
        self._degraded: dict = {}
        self._present_bubble = None
        # 微生命循环（任务书 §30）：现由 MicroScheduler 统一驱动（呼吸/眨眼/微视线），
        # paintEvent 只读本帧值；仅保留 _micro_gaze 作为细微 overlay 方向（FIX M 清理 legacy 残段）。
        self._micro_gaze = "front"        # 当前微视线（front/left/right/up/down/user）
        # 输入路由：角色包围盒为窗口局部坐标（水平居中）
        self.router = _ir.InputRouter(
            interaction_engine,
            char_rect_provider=lambda: (self._local_char_rect().x(), self._top, self._char_w, self._char_h),
        )

        # 小窗：无边框 / 置顶 / 工具窗 / 透明
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        # 用窗口几何自适应字体/DPI（骨架）
        self.set_size_hint()

    def _compute_margins(self) -> None:
        """随角色尺寸缩放的窗口边距（whale-girl 式小窗：气泡/留白随角色等比，不占屏）。

        参考：角色高 char_h；顶部气泡区 ~0.55*char_h、边距 ~0.12*char_h、
        底部阴影 ~0.13*char_h、最小可用气泡宽 ~1.5*char_h。
        """
        ch = max(1.0, self._char_h)
        self._top = max(40.0, ch * 0.55)          # 顶部气泡区
        self._side = max(12.0, ch * 0.10)         # 左右留白
        self._bottom = max(14.0, ch * 0.12)       # 底部阴影
        self._bubble_area = max(60.0, ch * 0.75)  # 最长台词预留高度
        self._min_bubble_w = max(200.0, ch * 1.5)

    def set_size_hint(self) -> None:
        cw = max(1, int(self._char_w))
        ch = max(1, int(self._char_h))
        self._compute_margins()
        # 窗口宽度要能容纳气泡（否则气泡溢出被窗口裁成“方形框”）。
        # 高度 = 顶部气泡区 + 角色 + 底部阴影（随角色缩放）。
        bubble_w = max(cw, self._min_bubble_w)
        self.setFixedSize(int(bubble_w + 2 * self._side), int(self._bubble_area + ch + self._bottom))

    def apply_reference_size(self) -> None:
        """在外部设置好参考角色尺寸后调用，同步窗口实际大小。"""
        self._char_w, self._char_h = self.assets.reference_size
        self._compute_margins()
        self._char_y = self._top
        self.set_size_hint()

    # -------------------------------------------------- 状态 / 外观
    def set_render_state(self, state: RenderState) -> None:
        self.state = state
        self._debug = state.debug if self.show_debug else ""
        self.update()

    # -------------------------------------------------- Phase 11：纯 View 入口
    def present(self, *, visual_phase: str, current_pose: str, target_pose: str,
                expression: str, gaze: str, clip_name: str = "",
                breath: float = 0.5, blink: float = 0.0, micro: list | None = None,
                bubble_text: str = "", degraded: dict | None = None,
                micro_gaze: str = "front", debug: str = "") -> None:
        """由 AnimationRuntime 驱动：Window 只绘制当前 QImage/气泡/debug，不决定"演什么"。

        - clip_name：生命周期演出的（activity 或 transition 序列名，由 Runtime 解析为具体帧）。
        - breath/blink/micro：由 MicroScheduler 算好传入（paintEvent 不再自己推进）。
        - 这是主路径；set_pose_semantics 保留仅作 legacy 兼容（deprecated）。
        """
        self._visual_phase = visual_phase
        self._target_pose = target_pose
        self._clip_name = clip_name
        self._breath = breath
        self._blink = blink
        self._micro = list(micro or [])
        self._degraded = dict(degraded or {})
        self._micro_gaze = micro_gaze or "front"    # FIX M：micro gaze 作为细微 overlay 由 Runtime 显式传入
        self._present_bubble: dict | None = None
        self._posture = current_pose or self._posture
        self._emotion = expression or self._emotion
        self._gaze = gaze or self._gaze
        # 气泡文本
        if bubble_text:
            self._present_bubble = bubble_text
        if debug:
            self._debug = debug if self.show_debug else ""
        # FIX A：Window 不再调用 ClipPlayer (anim.play)。Clip 由 AnimationRuntime 唯一驱动。
        # present() 只写 presentation fields + 请求重绘；paintEvent 读 anim.frame 绘制。
        self.update()

    def _apply_clip(self, clip_name: str, current_pose: str, target_pose: str,
                    expression: str, gaze: str) -> None:
        """把语义 clip 解析为具体帧（走真实 asset: transition 或 action 或 base pose）。"""
        # 1. 过渡序列：target_pose 变化且 pose 不同 → 从 TRANSITION_GRAPH 找（由 planner 已给 clip_name=transition）
        if clip_name and self.assets.sequence_for(clip_name):
            seq = self.assets.sequence_for(clip_name)
            fr = self._frames_for(seq, "entry") or self._frames_for(seq, "loop") or seq.frames
            if fr:
                spec = AnimationSpec(fr, fps=FRAME_ANIM_FPS, loop=False)
                self._play_if_new(("transition", clip_name, "entry"), spec)
                return
        # 2. 动作序列（read/eat/play/...）
        if clip_name and self.assets.sequence_for(clip_name) is None:
            seq = self.assets.sequence_for(clip_name)
        # 3. base pose：source pose 直接 resolve
        entry = self.assets.entry_for_state(target_pose or current_pose, expression, gaze, "idle")
        if entry is not None:
            fr = self._frames_for(entry, "loop") or entry.frames or [entry.path]
            spec = AnimationSpec(fr, fps=entry.fps or FRAME_ANIM_FPS, loop=entry.loop)
            self._play_if_new((entry.asset_id, "loop"), spec)

    def _play_if_new(self, key: tuple, spec: AnimationSpec) -> None:
        if key != self._scene_key:
            self.anim.play(spec)
            self._scene_key = key

    # -------------------------------------------------- 旧 set_pose_semantics（deprecated，非主路径）
    def set_pose_semantics(self, posture: str, emotion: str, gaze: str, action: str = "idle") -> None:
        import warnings
        warnings.warn("FurinaWindow.set_pose_semantics is deprecated; use present().",
                      DeprecationWarning, stacklevel=2)
        prev = self._posture
        self._posture, self._emotion, self._gaze = posture, emotion, gaze
        # 动作类多帧序列：eat / play / drink / walk 等 → 逐帧慢速切换（帧动画，whale-girl 式）。
        # 每帧固定停留 ~250ms，不插值、不连续平滑 → 是“多帧图片切换”而非“动画”。
        # walk 循环持续（走路是连续性行为）；其余一次性（做完即停在末帧）。
        if action in ("eat", "play", "drink", "wave", "stretch", "read", "think", "nap", "walk"):
            seq = self.assets.sequence_for(action)
            if seq is not None and seq.frames:
                key = ("anim", action)
                if key != self._scene_key:
                    self.anim.play(AnimationSpec(self._frames_for(seq, "entry") or seq.frames,
                                                 fps=FRAME_ANIM_FPS, loop=(action == "walk")))
                    self._scene_key = key
                    self.update()
                    return
        # 姿态切换：站↔坐（过渡序列）→ 播放 Entry(进入)后停到 LOOP；不硬切、不连续平滑
        if prev != posture:
            seq_name = ("sit_down" if (prev, posture) == ("standing", "sitting")
                        else "stand_up" if (prev, posture) == ("sitting", "standing")
                        else "lie_down" if (prev, posture) in (("sitting", "lying"), ("standing", "lying"))
                        else "lie_up" if (prev, posture) in (("lying", "sitting"), ("lying", "standing"))
                        else "go_sleep" if posture == "sleeping" else None)
            if seq_name:
                seq = self.assets.sequence_for(seq_name)
                if seq is not None and (seq.entry_frames or seq.frames):
                    self.anim.play(AnimationSpec(self._frames_for(seq, "entry") or seq.frames,
                                                 fps=FRAME_ANIM_FPS, loop=False))
                    self._scene_key = ("anim", seq_name)
                    self.update()
                    return
        entry = self.assets.entry_for_state(posture, emotion, gaze, action)
        if entry is not None:
            key = (entry.asset_id, action)
            if key != self._scene_key:
                # 若有 loop 帧，用 LOOP；否则静态单帧
                fr = self._frames_for(entry, "loop") or entry.frames or [entry.path]
                self.anim.play(AnimationSpec(fr, fps=entry.fps or FRAME_ANIM_FPS, loop=entry.loop))
                self._scene_key = key
        self.update()

    @staticmethod
    def _frames_for(seq, section: str) -> list:
        """取序列的某段帧：section=entry/loop/exit；没有则回退 frames。"""
        if section == "entry" and getattr(seq, "entry_frames", None):
            return list(seq.entry_frames)
        if section == "loop" and getattr(seq, "loop_frames", None):
            return list(seq.loop_frames)
        if section == "exit" and getattr(seq, "exit_frames", None):
            return list(seq.exit_frames)
        return list(getattr(seq, "frames", []) or [])

    def _local_char_rect(self) -> QRectF:
        """角色在窗口局部坐标的位置（水平居中，垂直在气泡区下方、动态避开气泡）。"""
        left = (self.width() - self._char_w) / 2
        return QRectF(left, self._char_y, self._char_w, self._char_h)

    @staticmethod
    def _bubble_font() -> QFont:
        return QFont("Microsoft YaHei", 10)

    @staticmethod
    def _wrap_by_width(text: str, font: QFont, max_w: float) -> list[str]:
        """按实际测量宽度贪心换行，确保每行不超 max_w（避免溢出）。"""
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(font)
        lines: list[str] = []
        cur = ""
        for ch in text:
            cand = cur + ch
            if ch == "\n":
                lines.append(cur)
                cur = ""
            elif fm.horizontalAdvance(cand) > max_w and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = cand
        if cur:
            lines.append(cur)
        return lines or [""]

    @staticmethod
    def _bubble_rect(r: QRectF, text: str, max_w: float = 300.0, win_w: float = 348.0) -> QRectF:
        """角色头顶气泡：按实测宽度换行、自适应大小，完整显示不裁剪，并夹在窗口内。

        宽度被限制在 max_w 内，且气泡左右不超出窗口（避免溢出被裁成方形框/文本截断）。
        """
        from PySide6.QtGui import QFontMetrics
        font = FurinaWindow._bubble_font()
        lines = FurinaWindow._wrap_by_width(text, font, max_w)
        fm = QFontMetrics(font)
        line_w = max((fm.horizontalAdvance(l) for l in lines), default=60)
        w = min(max_w, max(150.0, line_w + 28))
        h = len(lines) * (fm.height() + 3) + 18
        x = r.center().x() - w / 2
        # 夹住：不超出窗口左右边界
        x = max(2.0, min(x, win_w - w - 2.0))
        top = r.top() - h - 6
        top = max(2.0, top)   # 不超出窗口顶边（避免长气泡被顶部截断）
        return QRectF(x, top, w, h)

    def set_position(self, x: float, y: float) -> None:
        """设置角色世界位置；把窗口移动到相应位置（整窗 move，稳定）。

        **关键**：窗口包含头部气泡区(TOP)与底部阴影(BOTTOM)，不能再按“角色高”夹取，
        否则窗口底部会伸出屏幕（动画姿态脚被截断）。
        """
        # 角色世界坐标夹取：保证「整窗」都在屏幕内（含顶部气泡区 + 底部阴影）。
        win_w = self.width()
        win_h = self.height()
        world = self.world
        margin = world.safe_margin
        # 角色左上角即窗口内角色区；窗口左上角 = pos - (self._side, self._top)
        max_x = world.screen.w - win_w + self._side - margin
        max_y = world.screen.h - world.taskbar_height - win_h + self._top - margin
        cx = max(margin + self._side, min(x, max_x))
        cy = max(margin + self._top, min(y, max_y))
        self.pos = Vec2(cx, cy)
        self.move(int(cx - self._side), int(cy - self._top))
        self.update()

    def set_drag_pose(self, active: bool) -> None:
        """FIX A/E1：Window 不再直接 anim.play()。只**报告本地 interaction override request**，
        由 AnimationRuntime 决定拖拽视觉（有 drag asset 则用，否则 DEGRADED_DRAG_VISUAL）。

        active=True  请求进入"被拎起"姿态 override；
        active=False 请求清除 override、恢复当前 Frame 视觉计划。
        """
        if self.on_drag_pose:
            try:
                self.on_drag_pose(active)
            except Exception:
                pass
        self.update()

    # -------------------------------------------------- 绘制（纯 View：只读 Runtime 喂的视觉状态）
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        # Phase 11：不再假设 paint==16ms 也不推进任何生命状态。视觉状态由 AnimationRuntime/MicroScheduler 喂。
        breath = getattr(self, "_breath", 0.5)
        blink = getattr(self, "_blink", 0.0)
        gaze_dir = getattr(self, "_micro", None)
        # 兼容旧字段：present 前用 state.speech 作为气泡，否则用 _present_bubble
        bubble_text = getattr(self, "_present_bubble", None) or (self.state.speech if hasattr(self.state, "speech") else "")
        # 动态把角色下移，避开气泡（角色顶边 = max(top, 气泡底 + 间隙)），并夹在窗口内
        self._char_y = self._top
        if bubble_text:
            from PySide6.QtGui import QFontMetrics
            font = FurinaWindow._bubble_font()
            avail_w = max(120.0, self.width() - 2 * self._side)
            b = FurinaWindow._bubble_rect(
                QRectF((self.width() - self._char_w) / 2, self._top, self._char_w, self._char_h),
                bubble_text, max_w=min(360.0, avail_w), win_w=self.width())
            self._char_y = max(self._top, b.bottom() + 8)
        # 夹住：角色底边不超出窗口（预留底部阴影边距）
        self._char_y = min(self._char_y, self.height() - self._bottom - self._char_h)
        # FIX D：本体与影子**同步**呼吸（单一 owner=手动 bob，ClipPlayer breath 关闭避免叠加）。
        base = self.anim.frame(breath=0.0)
        lr = self._local_char_rect()
        fit = self._fitted_rect(base, lr) if base is not None else lr
        breath_rect = FurinaWindow._breath_rect(fit, breath)
        # 微视线偏移：左右上下轻微移动（活人感；不破坏 hitbox）—— 由 MicroScheduler 提供方向
        micro_gaze = self._micro_gaze  # Runtime 已算好的方向
        mshift = {"left": (-3, 0), "right": (3, 0), "up": (0, -2), "down": (0, 2)}.get(micro_gaze, (0, 0))
        draw_rect = QRectF(breath_rect.x() + mshift[0], breath_rect.y() + mshift[1],
                           breath_rect.width(), breath_rect.height())
        # 淡 drop-shadow（whale-girl 式；与本体同步呼吸）
        entry = self.assets.entry_for_state(self._posture, self._emotion, self._gaze, "idle")
        shadow = self.assets.shadow_for(entry)
        if shadow is not None:
            p.drawImage(QRectF(breath_rect.x(), breath_rect.y() + 4,
                               breath_rect.width(), breath_rect.height()), shadow, shadow.rect())
        if base is not None:
            p.drawImage(draw_rect, base, base.rect())
            # 眨眼：在头部区域盖一层肤色横条（模拟闭眼，任务书 §30）
            if blink > 0.05:
                self._draw_blink(p, draw_rect, blink)
        else:
            p.setPen(QColor(80, 120, 220, 160))
            p.setBrush(QColor(80, 120, 220, 60))
            p.drawRoundedRect(lr, 24, 24)
            p.setPen(QColor(255, 255, 255, 220))
            p.drawText(lr, Qt.AlignCenter, "Furina")
        if bubble_text:
            self._draw_bubble(p, lr, bubble_text)
        # 状态调试叠层（仅在 show_debug=True 时显示）
        if self.show_debug and self._debug:
            p.setPen(QColor(255, 255, 255, 190))
            p.setFont(QFont("Microsoft YaHei", 9))
            p.drawText(6, 14, self._debug)
        p.end()

    @staticmethod
    def _draw_blink(p: QPainter, r: QRectF, blink: float) -> None:
        """眨眼：在角色头部区域盖一条肤色横条，强度随 blink(0..1)。"""
        # 头部在角色矩形上部 ~0.15h 处，眼位 ~0.22h
        eye_y = r.y() + r.height() * 0.22
        eye_w = r.width() * 0.30
        eye_x = r.x() + (r.width() - eye_w) / 2
        lid_h = max(1.0, r.height() * 0.04 * blink)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(238, 205, 190, int(235 * min(1.0, blink))))
        p.drawRoundedRect(QRectF(eye_x, eye_y - lid_h / 2, eye_w, lid_h), lid_h / 2, lid_h / 2)

    @staticmethod
    def _fitted_rect(img: Optional[QImage], target: QRectF) -> QRectF:
        """在 target 内按比例绘制 img，保持纵横比并居中（**内容感知**）。
        FIX：动画帧/静态姿态的**画布宽高不一致**（eat W 446~518、stand_up W~1088 都高 832；
        静态 443x959）。若按 min(宽,高) 适配：宽帧会被缩得极小（stand_up 小人），
        且内容高占画布~100%，满贴 box 加呼吸 bob 会上下截断。

        改法：优先按**内容高度**适配（站立 Q 版主体高度是主导维度），
        让所有帧呈现一致大小、不缩小、不上下截断；宽度超出的部分对称居中，
        若超出目标宽度则回退到按宽适配（保证不超出左右）。
        """
        if img is None or img.width() <= 0 or img.height() <= 0:
            return target
        # 目标区域留 ~6% 安全边距，避免内容贴边/呼吸 bob 顶界
        avail_h = target.height() * 0.94
        avail_w = target.width() * 0.94
        # 按高度适配（角色主体）
        scale = avail_h / img.height()
        w = img.width() * scale
        h = img.height() * scale
        # 若宽度超限，则回退按宽度适配（保证不超出左右）
        if w > avail_w:
            scale = avail_w / img.width()
            w = img.width() * scale
            h = img.height() * scale
        return QRectF(target.x() + (target.width() - w) / 2, target.y() + (target.height() - h) / 2, w, h)

    @staticmethod
    def _breath_rect(r: QRectF, breath: float) -> QRectF:
        """FIX D：角色呼吸本体变换（单一 owner）。body 与 shadow 共用此矩形，同步缩放+升降。

        breath=0..1 → 轻微 ±1.2% 缩放 + ±7px 垂直升降（可测：不同 breath 几何必不同）。
        """
        b = max(0.0, min(1.0, breath))
        amp = 0.012
        scale = 1.0 + (b - 0.5) * amp
        bob = (b - 0.5) * 14.0
        w = r.width() * scale
        h = r.height() * scale
        return QRectF(r.x() + (r.width() - w) / 2, r.y() + bob, w, h)

    @staticmethod
    def _draw_bubble(p: QPainter, r: QRectF, text: str) -> None:
        from PySide6.QtGui import QFontMetrics
        font = FurinaWindow._bubble_font()
        # 气泡可用宽 = 窗口宽 - 两侧留白；避免气泡溢出窗口被裁成方形框
        win_w = float(p.device().width())
        side = max(8.0, win_w * 0.04)
        avail_w = max(120.0, win_w - 2 * side)
        b = FurinaWindow._bubble_rect(r, text, max_w=min(360.0, avail_w), win_w=win_w)
        # 自适应圆角：无论气泡多高都保持圆润（避免方形）
        radius = max(10.0, min(26.0, min(b.width(), b.height()) / 3.0))
        p.setPen(QPen(QColor(255, 255, 255, 230), 1))
        p.setBrush(QColor(28, 28, 38, 235))
        p.drawRoundedRect(b, radius, radius)
        tail = QRectF(r.center().x() - 6, b.bottom(), 12, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(28, 28, 38, 235))
        p.drawPolygon([tail.bottomLeft(), tail.bottomRight(), QPointF(r.center().x(), b.bottom() + 10)])
        # 完整多行显示（按实测宽度换行，不溢出）
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        fm = QFontMetrics(font)
        lines = FurinaWindow._wrap_by_width(text, font, b.width() - 28)
        lh = fm.height() + 3
        total_h = len(lines) * lh
        y = b.top() + (b.height() - total_h) / 2 + fm.ascent()
        for ln in lines:
            p.drawText(QRectF(b.left() + 14, y - fm.ascent(), b.width() - 28, fm.height()),
                       Qt.AlignCenter, ln)
            y += lh

    # -------------------------------------------------- 右键菜单
    def contextMenuEvent(self, ev) -> None:
        ev.accept()
        menu = QMenu(self)
        m = menu.addMenu("对话框")
        for label, cmd in self._diag_commands():
            act = QAction(label, menu)
            act.triggered.connect(lambda _=False, c=cmd: self._dispatch(c))
            m.addAction(act)
        a = menu.addMenu("随手帮忙")
        for label, cmd in self._agent_commands():
            act = QAction(label, menu)
            act.triggered.connect(lambda _=False, c=cmd: self._dispatch(c))
            a.addAction(act)
        f = menu.addMenu("喂她")
        for label, cmd in self._feed_commands():
            act = QAction(label, menu)
            act.triggered.connect(lambda _=False, c=cmd: self._dispatch(c))
            f.addAction(act)
        menu.addSeparator()
        quit_act = menu.addAction("退出")
        quit_act.triggered.connect(self.close)
        menu.exec(ev.globalPos())

    @staticmethod
    def _diag_commands():
        return [("今天过得怎么样？", "今天过得怎么样？"),
                ("你在干什么？", "你在干什么？"),
                ("我写代码好累", "我写代码好累，想休息")]

    @staticmethod
    def _agent_commands():
        return [("帮我整理下载文件夹", "整理下载文件夹"),
                ("帮我打开记事本", "打开记事本")]

    @staticmethod
    def _feed_commands():
        return [("一块蛋糕 🍰", "喂：cake"),
                ("一杯茶 🍵", "喂：tea"),
                ("一块面包 🍞", "喂：bread")]

    def _dispatch(self, cmd: str) -> None:
        if self.on_command:
            self.on_command(cmd)

    # -------------------------------------------------- 鼠标
    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.LeftButton:
            handled = self.router.on_button(pressed=True, x=ev.position().x(), y=ev.position().y())
            self.dragging = handled
            if self.dragging:
                # 拖拽体感：立即切到“被拎起”姿态（表现层，快于状态系统）
                self.set_drag_pose(True)
                # 记录“抓取点”相对窗口左上角的偏移（全局坐标），拖动时让该点始终贴住光标
                g = ev.globalPosition()
                self._drag_offset = QPointF(g.x() - self.x(), g.y() - self.y())
                if self.on_drag_start:
                    self.on_drag_start()
            ev.accept()

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:
        if self.dragging:
            # 全局坐标：窗口左上角 = 光标 - 抓取偏移（无局部坐标反馈，稳定不闪跳）
            g = ev.globalPosition()
            wx = g.x() - self._drag_offset.x()
            wy = g.y() - self._drag_offset.y()
            self.set_position(wx + self._side, wy + self._top)
        self.router.on_move(x=ev.position().x(), y=ev.position().y(), pressed=self.dragging)
        ev.accept()

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.LeftButton:
            self.router.on_button(pressed=False, x=ev.position().x(), y=ev.position().y())
            self.dragging = False
            self.set_drag_pose(False)
            if self.on_drag_release:
                self.on_drag_release()
            ev.accept()
