"""Frontend Character Runtime（Phase 11）—— Frame → VisualState → Window（驱动层）。

控制权迁移目标（用户明确）：
    Frame owns semantic truth
    AnimationRuntime owns presentation timing
    Window only draws

`FurinaWindow` 是实际 View（paintEvent）；`Renderer` 只是轻量独立 compositor，保留兼容/测试，
本阶段**不围绕它重建主路径**。

本模块：
    - FrontendVisualState：前端目前"演到哪里"（与 Frame 的"想表现成什么"分离）。
    - FrontendFrameConsumer：订阅 CHARACTER_FRAME_UPDATED，做 semantic diff → 产出/更新 VisualState。
    - AnimationRuntime：拥有播放时钟（QTimer），推进 transition/micro/gaze/bubble timing。

不做：Walk/Pathfinding、TTS、Asset 生成、Renderer overhaul。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from furina.core import EventBus, EventType, get_logger

log = get_logger("runtime.frontend")

# 引用底层 ClipPlayer（此处只转交 spec；实际帧选择由 ClipPlayer 完成）
from .animation import AnimationSpec

FRAME_ANIM_FPS = 4.0   # 与 furina_window 的帧动画帧率一致（慢速逐帧）

# 语义 visual phase（AnimationRuntime 据此推进）
class VisualPhase(str):
    ENTRY = "ENTRY"
    LOOP = "LOOP"
    EXIT = "EXIT"
    HOLD = "HOLD"
    TRANSITION = "TRANSITION"

# 优先级（§14）：数字越小越重要
P_CRITICAL_TRANSITION = 100
P_INTERACTION_REACTION = 80
P_ACTIVITY_ACTION = 60
P_SPEECH_REACTION = 50
P_MICRO = 20
P_IDLE_VARIATION = 10


@dataclass
class FrontendVisualState:
    """前端当前演到哪里（≠Frame 想表现成什么）。"""
    source_frame_id: int = 0
    activity: str = "idle"
    visual_phase: str = VisualPhase.LOOP

    current_pose: str = "standing"
    target_pose: str = "standing"

    expression: str = "neutral"
    gaze: str = "NONE"

    current_clip: str = ""          # 当前 clip 名（asset_id / action / transition）
    clip_phase: str = VisualPhase.LOOP
    clip_progress: float = 0.0      # 0..1

    micro: List[str] = field(default_factory=list)
    transition: str = "SMOOTH"

    bubble_text: str = ""

    degraded: Dict[str, Any] = field(default_factory=dict)
    hesitation: float = 0.0
    body_openness: float = 0.5

    # ---- 空间移动 overlay（Phase 12）：AnimationRuntime 只据此决定 walk 视觉 ----
    movement_moving: bool = False
    movement_facing: str = "FRONT"
    movement_degraded: bool = False

    # ---- FIX B/C：映射后的素材词汇 + FIX K：语义 revision ----
    asset_action: str = "idle"              # 映射后的素材 action（read/eat/play/think/...）
    raw_posture: str = ""                   # 后端原始语义（debug）
    raw_expression: str = ""
    raw_gaze: str = ""
    semantic_revision: int = 0              # 只在可见语义变化时 +1（FIX K）

    def to_dict(self) -> dict:
        return {
            "source_frame_id": self.source_frame_id,
            "activity": self.activity,
            "visual_phase": self.visual_phase,
            "current_pose": self.current_pose,
            "target_pose": self.target_pose,
            "expression": self.expression,
            "gaze": self.gaze,
            "current_clip": self.current_clip,
            "clip_phase": self.clip_phase,
            "clip_progress": round(self.clip_progress, 3),
            "micro": list(self.micro),
            "transition": self.transition,
            "bubble_text": self.bubble_text,
            "degraded": dict(self.degraded),
        }


# ---------------------------------------------------------------- 语义 diff（§15）
class FrontendFrameConsumer:
    """订阅 CHARACTER_FRAME_UPDATED → semantic diff → 生成/更新 FrontendVisualState。

    只比较"会重启动画"的语义字段；frame_id/timestamp/debug/world_hint-only 变化不重启动画。
    """
    ANIM_TRIGGERS = ("activity_name", "body_expression", "body_gaze", "body_posture",
                     "body_transition_style", "body_is_openness", "speech_text")
    IGNORED = ("meta", "debug", "world_hint")

    def __init__(self, bus: EventBus, *,
                 on_frame: Optional[Any] = None) -> None:
        self.bus = bus
        self._on_frame = on_frame
        self.last_frame: Optional["Any"] = None
        self.visual: FrontendVisualState = FrontendVisualState()
        self.frame_count = 0
        self.last_semantic_change: List[str] = []
        # FIX B：唯一语义→素材词汇映射点（production 与 coverage 共用）
        from furina.runtime.visual_semantics import VisualSemanticMapper
        self.mapper = VisualSemanticMapper()
        bus.on(EventType.CHARACTER_FRAME_UPDATED, self._handle)

    def _handle(self, ev) -> None:
        frame = ev.payload
        self.frame_count += 1
        changed = self._diff(frame)
        if changed or self.last_frame is None:
            self._apply_tokens(frame, changed)
        self.last_frame = frame
        if self._on_frame is not None:
            self._on_frame(self.visual, changed)

    # -------------------------------------------------- diff
    def _diff(self, frame) -> List[str]:
        prev = self.last_frame
        if prev is None:
            return ["initial"]
        changed: List[str] = []
        # activity
        if frame.activity.name != prev.activity.name:
            changed.append("activity_name")
        # body
        if frame.body.expression != prev.body.expression:
            changed.append("body_expression")
        if frame.body.gaze != prev.body.gaze:
            changed.append("body_gaze")
        if frame.body.posture != prev.body.posture:
            changed.append("body_posture")
        if frame.body.transition_style != prev.body.transition_style:
            changed.append("body_transition_style")
        if abs(frame.body.hesitation - prev.body.hesitation) > 0.15:
            changed.append("body_hesitation")
        # speech
        if frame.speech.text != prev.speech.text:
            changed.append("speech_text")
        elif frame.speech.should_speak != prev.speech.should_speak:
            changed.append("speech_state")
        # motion / interaction
        if frame.motion.intent != prev.motion.intent:
            changed.append("motion_intent")
        if frame.interaction.response_mode != prev.interaction.response_mode:
            changed.append("interaction_mode")
        return changed

    # -------------------------------------------------- token → visual state
    def _apply_tokens(self, frame, changed: List[str]) -> None:
        vs = self.visual
        vs.source_frame_id = frame.meta.frame_id
        vs.activity = frame.activity.name
        vs.raw_posture = frame.body.posture
        vs.raw_expression = frame.body.expression
        vs.raw_gaze = frame.body.gaze
        # FIX B：后端语义 → 素材词汇（posture/expression/gaze/action）
        mapped = self.mapper.map(posture=frame.body.posture,
                                 expression=frame.body.expression,
                                 gaze=frame.body.gaze,
                                 activity=frame.activity.name)
        vs.target_pose = mapped.posture
        vs.expression = mapped.expression
        vs.gaze = mapped.gaze
        vs.asset_action = mapped.action
        vs.transition = frame.body.transition_style
        vs.hesitation = frame.body.hesitation
        vs.body_openness = frame.body.body_openness
        vs.micro = list(frame.body.micro_preferences)
        vs.bubble_text = frame.speech.text
        vs.degraded["semantic"] = mapped.degraded
        # FIX K：只有可见语义变化才 +1（由 _diff 已判定 changed）
        vs.semantic_revision += 1
        # 由 AnimationPlanner 决定 phase / current_clip；此处先标记"需重新规划"
        vs.visual_phase = VisualPhase.TRANSITION   # 触发 planner 重算 entry/loop


# ---------------------------------------------------------------- Transition graph（§13）
# 姿态过渡：真实 manifest 已确认这些 transition 序列存在（asset_manifest 扫描）。
TRANSITION_GRAPH = {
    ("standing", "sitting"): "sit_down",
    ("sitting", "standing"): "stand_up",
    ("lying", "sitting"): "lie_up",
    ("lying", "standing"): "lie_up",
    ("sitting", "lying"): "lie_down",
    ("standing", "lying"): "lie_down",
    ("sitting", "sleeping"): "go_sleep",
    ("standing", "sleeping"): "go_sleep",
    ("sleeping", "standing"): "wake_up",
    ("sleeping", "sitting"): "wake_up",
}


class AnimationPlanner:
    """Frame semantic 变化 → 视觉动作计划（entr/loop/exit/transition/hold）。

    不依赖后端 activity.phase（后端固定 LOOP）；用 previous_frame vs current_frame 推导。
    """

    def __init__(self, assets) -> None:
        self.assets = assets

    def plan(self, vs: FrontendVisualState, prev_pose: str = "standing",
             prev_activity: str = "idle") -> Dict[str, Any]:
        """给出一份（语义）计划：transition / clip / phase / pre_hold_ms。"""
        target = vs.target_pose or "standing"
        plan: Dict[str, Any] = {
            "transition": None,
            "clip": "",
            "phase": VisualPhase.LOOP,
            "pre_hold_ms": 0,
            "post_hold_ms": 0,
        }
        # 姿态变化 → 走 transition 序列（若素材支持）；否则 best-available。
        # 允许 target 为 standing 的过渡（stand_up / wake_up 也合法），只要姿态确实改变且素材存在。
        if prev_pose != target:
            seq_name = TRANSITION_GRAPH.get((prev_pose, target))
            if seq_name and self.assets.sequence_for(seq_name) is not None:
                plan["transition"] = seq_name
                plan["phase"] = VisualPhase.TRANSITION
        # hesitation（§11）：高犹豫 + HESITANT → 先 hold 再动（与 embodied `_transition` >0.65 一致）
        if vs.hesitation >= 0.6 and vs.transition == "HESITANT":
            plan["pre_hold_ms"] = int(250 + vs.hesitation * 400)  # 250~530ms
        # 表演/兴奋 tempo → 更轻快（此处只记录 clip 语义，播放由 Runtime 决定）
        plan["clip"] = vs.activity
        return plan


# ---------------------------------------------------------------- Animation Phase（生命周期）
class AnimationPhase(str):
    PRE_HOLD = "PRE_HOLD"
    ENTRY = "ENTRY"
    LOOP = "LOOP"
    REACT = "REACT"
    EXIT = "EXIT"
    TRANSITION = "TRANSITION"


# 有生命周期的 action（真实 manifest 有 entry/loop/exit 帧的才走三段；只有 frames 的降级共享 clip）
LIFECYCLE_ACTIONS = {"eat", "read", "play", "drink", "stretch", "think", "sleep", "walk"}


class AnimationRuntime:
    """前端唯一动画时钟 + 生命周期状态机（ClipPlayer 之上的 owner）。

    拥有：current_plan / pending_plan / phase / priority / transition_lock / hold /
    completion latch / pose commitment。
    关键：**ENTRY→LOOP→EXIT 自动推进**（消费 ClipPlayer.is_finished()），
    不等下一次 CharacterRuntimeFrame；Frame 只提供语义变化（由 consumer diff 触发 accept）。
    ClipPlayer（现 AnimationController）只做 frames/fps/loop/当前帧/crossfade。
    """

    def __init__(self, clip_player, assets, fps: float = 30.0,
                 bus: Optional[EventBus] = None) -> None:
        self.clip = clip_player
        self.assets = assets
        self.fps = fps
        self.planner = AnimationPlanner(assets)
        self.bus = bus
        # ---- 生命周期状态 ----
        self.phase = AnimationPhase.LOOP
        self.current_plan: Dict[str, Any] = {"clip": "idle", "phase": VisualPhase.LOOP,
                                             "activity": "idle"}
        self.pending_plan: Optional[Dict[str, Any]] = None
        self.priority = P_IDLE_VARIATION
        self.phase_started_at = 0.0
        self.transition_lock = False
        # pose commitment
        self.current_pose = "standing"
        self.commit_lock = False
        # completion latch（exactly-once）
        self._completed_phase = None
        # gaze
        self.gaze_runtime = GazeRuntime()
        self.expression_hold = ExpressionHold()
        self.micro = None
        # 统计
        self.stats = {"entries": 0, "loops": 0, "exits": 0, "transitions": 0,
                      "completions": 0, "interruptions": 0, "pending_replacements": 0,
                      "degraded": 0, "restarts": 0, "stuck": 0}
        self._terminated = False
        self._now = _now()   # 由 tick(now=...) 更新；内部所有时间都用它
        # ---- 空间移动 overlay（Phase 12）----
        self.movement_moving = False
        self.movement_facing = "FRONT"
        self.movement_degraded = False
        # ---- FIX K：语义签名（同一语义不重复 accept）----
        self._last_sig = None
        # ---- FIX E1：拖拽 override（高优先，经 Runtime 决策视觉）----
        self._drag_override = False
        self._drag_override_active = False

    # -------------------------------------------------- 空间移动 → walk 视觉（Phase 12）
    def set_movement(self, moving: bool, facing: str = "FRONT") -> None:
        """SpatialRuntime 通知"她在移动/停下" → 显示 walk（有素材）或 DEGRADED（无素材）。

        - moving=True & 有 walk 序列 → 播 walk loop（作为 LOOP 阶段 overlay）。
        - moving=True & 无 walk 序列 → movement_degraded=True（移动继续，视觉不强行走 idle）。
        - moving=False → 回 activity clip。
        - 关键 transition（sit_down/stand_up/...）仍优先（§62），不被打断。
        """
        changed = (moving != self.movement_moving) or (self.movement_facing != facing)
        self.movement_moving = moving
        self.movement_facing = facing
        if moving:
            # 仅当确实有 walk 序列才声明"walk 生效"（§54 flip 用 facing）
            self.movement_degraded = not bool(self._walk_sequence())
        else:
            self.movement_degraded = False
        if changed and self.clip is not None and self.assets is not None:
            try:
                self._play_clip_for_phase(self.current_plan, loop=(self.phase == AnimationPhase.LOOP))
            except Exception:
                pass

    def _walk_sequence(self):
        if self.assets is None:
            return None
        try:
            return self.assets.sequence_for("walk")
        except Exception:
            return None

    def _resolve_action_asset(self, asset_action: str, target_pose: str,
                              expression: str, gaze: str):
        """FIX C：action 优先的素材选择 —— 找"能表达这个动作"的 frame 资产，
        尽量贴近 target_pose/expression/gaze，但**保证动作可见**（不静默落到 idle pose）。

        返回 None 时表示无该 action 资产。
        """
        if self.assets is None:
            return None
        manifest = getattr(self.assets, "manifest", None)
        try:
            if manifest is not None and getattr(manifest, "entries", None):
                best = None
                best_score = -1
                for e in manifest.entries:
                    if getattr(e, "kind", "") != "frame":
                        continue
                    if getattr(e, "action", "") != asset_action:
                        continue
                    score = 0
                    if getattr(e, "posture", "") == target_pose:
                        score += 4
                    if getattr(e, "emotion", "") == expression:
                        score += 3
                    if getattr(e, "gaze", "") == gaze:
                        score += 1
                    if score > best_score:
                        best, best_score = e, score
                if best is not None:
                    return best
        except Exception:
            pass
        # 无该 action 资产 → 退回 resolver（可能是 idle pose）
        try:
            return self.assets.entry_for_state(target_pose, expression, gaze, asset_action)
        except Exception:
            return None

    # -------------------------------------------------- 事件发射（exactly-once）
    def _emit(self, ev_type: str, *, plan: str, clip: str, phase: str, source_frame_id: int) -> None:
        if self.bus is None:
            return
        try:
            self.bus.emit(EventType(ev_type), payload={
                "plan": plan, "clip": clip, "phase": phase, "source_frame_id": source_frame_id,
            }, source="animation")
        except Exception:
            pass

    # -------------------------------------------------- 由 consumer/planner 喂（新 Frame 语义）
    def accept(self, vs: FrontendVisualState, prev_pose: str, prev_activity: str,
               now: float | None = None) -> None:
        if now is not None:
            self._now = now
        # FIX K：语义签名去重 —— 同一可见语义（activity/pose/expression/gaze/style/micro）不重复 accept。
        # 关键：TRANSITION/ENTRY 期间 1000 个 render tick（同 visual）不再重写 pending / 重播。
        sig = self._signature(vs)
        if sig == self._last_sig and self.pending_plan is None:
            return
        self._last_sig = sig
        plan = self.planner.plan(vs, prev_pose=prev_pose, prev_activity=prev_activity)
        plan["activity"] = vs.activity
        plan["asset_action"] = getattr(vs, "asset_action", "idle") or "idle"
        plan["source_frame_id"] = vs.source_frame_id
        plan["target_pose"] = vs.target_pose or vs.current_pose or "standing"
        plan["expression"] = vs.expression
        plan["gaze"] = vs.gaze
        # 若是"完全相同"计划且当前正在 LOOP 稳定 → 不重启（anti-restart）
        if (plan.get("clip") == self.current_plan.get("clip")
                and plan.get("transition") == self.current_plan.get("transition")
                and self.phase in (AnimationPhase.LOOP, AnimationPhase.PRE_HOLD)):
            return
        # FIX J：当前在 LOOP/ENTRY/TRANSITION，当前 clip 有 exit_frames，且这是新 activity →
        # 先走当前 clip 的 EXIT，再执行 new plan（真实 LOOP→EXIT→pending）。
        if (self.phase in (AnimationPhase.LOOP, AnimationPhase.ENTRY, AnimationPhase.TRANSITION)
                and self._has_exit_frames(self.current_plan)
                and plan.get("activity") != self.current_plan.get("activity")):
            self.pending_plan = plan
            stats_exit = self._enter_exit(self.current_plan)
            if not stats_exit:
                # 无 exit 帧可播 → 直接切到新计划
                self._start_plan(plan, self._plan_priority(plan))
            return
        # priority 判定：higher priority 或空闲 → 立即可用；否则 pending（+++ 保留最新）
        new_pri = self._plan_priority(plan)
        if self._can_interrupt_now(new_pri):
            self._start_plan(plan, new_pri)
            self.stats["interruptions"] += 0
        else:
            # transition_lock 或高优先级不可打断 → 存为 pending（替换旧 pending，不堆队列）
            if self.pending_plan is not None:
                self.stats["pending_replacements"] += 1
            self.pending_plan = plan

    def _signature(self, vs: FrontendVisualState) -> tuple:
        """语义签名：只含会改变动画计划的语义字段（FIX K）。"""
        return (str(getattr(vs, "activity", "")),
                str(getattr(vs, "target_pose", "")),
                str(getattr(vs, "expression", "")),
                str(getattr(vs, "gaze", "")),
                str(getattr(vs, "transition", "")),
                tuple(getattr(vs, "micro", []) or []),
                str(getattr(vs, "asset_action", "")))

    def _enter_exit(self, plan: Dict[str, Any]) -> bool:
        """播当前 clip 的 exit_frames（FIX J）。返回是否成功进入 EXIT。"""
        seq = self._sequence_for_plan(plan)
        if seq is None or not getattr(seq, "exit_frames", None):
            return False
        self.phase = AnimationPhase.EXIT
        self.phase_started_at = self._now
        self.stats["exits"] += 1
        fr = self._frames_for(seq, "exit") or getattr(seq, "frames", None) or []
        if fr and self.clip is not None:
            self.clip.play(AnimationSpec(fr, fps=FRAME_ANIM_FPS, loop=False), now=self._now)
        return True

    def _sequence_for_plan(self, plan: Dict[str, Any]):
        clip = plan.get("clip", "") or plan.get("asset_action", "") or ""
        if self.assets is None:
            return None
        try:
            return self.assets.sequence_for(clip) or self.assets.sequence_for(plan.get("activity", ""))
        except Exception:
            return None

    def _has_exit_frames(self, plan: Dict[str, Any]) -> bool:
        seq = self._sequence_for_plan(plan)
        return seq is not None and bool(getattr(seq, "exit_frames", None))

    # -------------------------------------------------- drag override（FIX E1）
    def set_drag_override(self, active: bool) -> None:
        """用户拖拽：高优先 override → Runtime 决定拖拽视觉（有 drag 资产→用；否则 DEGRADED_Drag）。"""
        if active == self._drag_override_active:
            return
        self._drag_override_active = active
        if active and self.clip is not None and self.assets is not None:
            self._play_drag_override()
        elif not active and self.clip is not None and self.assets is not None:
            # 释放：恢复当前 Frame 视觉计划
            try:
                self._play_clip_for_phase(self.current_plan, loop=(self.phase == AnimationPhase.LOOP))
            except Exception:
                pass

    def _play_drag_override(self) -> None:
        entry = None
        try:
            entry = self.assets.entry_for_state("standing", "surprised", "user", "drag")
        except Exception:
            entry = None
        if entry is not None:
            fr = self._frames_for(entry, "loop") or entry.frames or [entry.path]
            self.clip.play(AnimationSpec(fr, fps=entry.fps or 12, loop=entry.loop), now=self._now)
            self._drag_override = False
            return
        # 无 drag 资产 → 显式 DEGRADED_DRAG_VISUAL，不用 standing-neutral 冒充（FIX E2/§7）
        self._drag_override = True
        self.current_plan["degraded"] = dict(self.current_plan.get("degraded", {}) or {})
        self.current_plan["degraded"]["DEGRADED_DRAG_VISUAL"] = {"reason": "missing_drag_asset"}
        try:  # 仍显示一张可辨识的"被拎起"（surprised），但不冒充 drag 完整 CG
            entry = self.assets.entry_for_state("standing", "surprised", "user", "idle")
            fr = (self._frames_for(entry, "loop") or entry.frames or [entry.path]) if entry else []
            if fr:
                self.clip.play(AnimationSpec(fr, fps=entry.fps or 12, loop=entry.loop), now=self._now)
        except Exception:
            pass

    def _can_interrupt_now(self, new_pri: int) -> bool:
        if self.phase == AnimationPhase.PRE_HOLD or self.phase == AnimationPhase.LOOP:
            return True
        # 正在 ENTRY/EXIT/TRANSITION：新的更高优先级可打断；否则等 clip 完成
        if self.transition_lock:
            return new_pri > self.priority
        return True

    def _plan_priority(self, plan: Dict[str, Any]) -> int:
        act = plan.get("activity", "idle")
        if plan.get("transition"):
            return P_CRITICAL_TRANSITION
        if act in ("approach_user", "greet", "comfort", "celebrate", "offer_help"):
            return P_INTERACTION_REACTION
        if act in ("eat", "read", "play", "drink", "stretch", "think", "sleep"):
            return P_ACTIVITY_ACTION
        if act in ("talk", "comment", "ask_user"):
            return P_SPEECH_REACTION
        return P_IDLE_VARIATION

    def _start_plan(self, plan: Dict[str, Any], pri: int) -> None:
        self.current_plan = plan
        self.priority = pri
        self._completed_phase = None
        self.phase_started_at = self._now
        trans = plan.get("transition")
        if trans:
            self.transition_lock = True
            self.phase = AnimationPhase.TRANSITION
            self.stats["transitions"] += 1
        elif plan.get("pre_hold_ms", 0) > 0:
            self.phase = AnimationPhase.PRE_HOLD
        elif self._has_entry_frames(plan):
            self.phase = AnimationPhase.ENTRY
            self.stats["entries"] += 1
        else:
            self.phase = AnimationPhase.LOOP
            self.stats["loops"] += 1
        self._play_clip_for_phase(plan)

    # -------------------------------------------------- 每帧驱动（QTimer）
    def tick(self, now: float | None = None) -> None:
        now = self._now = (now or self._now)
        # 1. PRE_HOLD → 播 ENTRY/LOOP
        if self.phase == AnimationPhase.PRE_HOLD:
            if now - self.phase_started_at >= self.current_plan.get("pre_hold_ms", 0) / 1000.0:
                self._advance_from_hold()
            return
        # 2. 若当前 clip 完成 → 推进 next phase
        if self.phase in (AnimationPhase.ENTRY, AnimationPhase.TRANSITION):
            if self._clip_done(now):
                self._on_clip_complete(now)
                return
        if self.phase == AnimationPhase.EXIT:
            if self._clip_done(now):
                self._on_exit_complete(now)
                return
        # 3. pending 可执行（当前 LOOP/完成后）
        if self.phase == AnimationPhase.LOOP and self.pending_plan is not None:
            self._flush_pending()

    # -------------------------------------------------- clip 完成（ENTRY→LOOP；EXIT→next）
    def _clip_done(self, now: float | None = None) -> bool:
        # 单帧/lifecycle 空数组 → 视为立即完成（§5 static 生命周期）
        if self._frame_count() <= 1:
            return True
        return self.clip.is_finished(now or self._now)

    def _frame_count(self) -> int:
        try:
            return self.clip.frame_count()
        except Exception:
            return 0

    def _on_clip_complete(self, now: float) -> None:
        # exactly-once latch（用 self.phase 判定当前已完成阶段）
        if self._completed_phase == self.phase:
            return
        self._completed_phase = self.phase
        self._emit("runtime.animation_completed", plan=self.current_plan.get("activity", ""),
                   clip=self.current_plan.get("clip", ""), phase=self.phase,
                   source_frame_id=self.current_plan.get("source_frame_id", 0))
        self.stats["completions"] += 1
        if self.phase == AnimationPhase.TRANSITION:
            self._emit("runtime.transition_completed", plan=self.current_plan.get("activity", ""),
                       clip=self.current_plan.get("transition", ""), phase="TRANSITION",
                       source_frame_id=self.current_plan.get("source_frame_id", 0))
            # pose commit：transition 完成才 commit target pose（§9）
            self.current_pose = self.current_plan.get("target_pose", self.current_pose)
            self.transition_lock = False
            self.commit_lock = False
            # FIX J: 过渡已完成 → 清掉 transition，避免 _play_clip_for_phase 重复播过渡帧
            self.current_plan["transition"] = None
            # transition 播完 → 进入目标姿态的 LOOP（播 action/pose 资产）
            self.phase = AnimationPhase.LOOP
            self.phase_started_at = now
            self.stats["loops"] += 1
            self._play_clip_for_phase(self.current_plan, loop=True)
        elif self.phase == AnimationPhase.ENTRY:
            self.phase = AnimationPhase.LOOP
            self.phase_started_at = now
            self.stats["loops"] += 1
            self._play_clip_for_phase(self.current_plan, loop=True)
        # 继续推进
        self._maybe_next()

    def _maybe_next(self) -> None:
        # 当前 LOOP 稳定时：若有 pending 且可打断 → 执行；否则保持 LOOP
        if self.phase == AnimationPhase.LOOP and self.pending_plan is not None:
            self._flush_pending()

    def _flush_pending(self) -> None:
        if self.pending_plan is None:
            return
        plan = self.pending_plan
        self.pending_plan = None
        self._start_plan(plan, self._plan_priority(plan))

    def _advance_from_hold(self) -> None:
        if self._has_entry_frames(self.current_plan):
            self.phase = AnimationPhase.ENTRY
            self.phase_started_at = self._now
            self.stats["entries"] += 1
        else:
            self.phase = AnimationPhase.LOOP
            self.phase_started_at = self._now
            self.stats["loops"] += 1
        self._play_clip_for_phase(self.current_plan)

    def _on_exit_complete(self, now: float) -> None:
        # exactly-once latch（EXIT 阶段只发一次）
        if self._completed_phase == AnimationPhase.EXIT:
            return
        self._completed_phase = AnimationPhase.EXIT
        self._emit("runtime.animation_completed", plan=self.current_plan.get("activity", ""),
                   clip=self.current_plan.get("clip", ""), phase="EXIT",
                   source_frame_id=self.current_plan.get("source_frame_id", 0))
        self.stats["completions"] += 1
        # 执行 pending（新计划）或回 LOOP
        self._flush_pending()
        if self.phase == AnimationPhase.EXIT:
            self.phase = AnimationPhase.LOOP
            self.phase_started_at = now

    # -------------------------------------------------- pose commit / play
    def _play_clip_for_phase(self, plan: Dict[str, Any], loop: bool = False) -> None:
        clip = plan.get("clip", "")
        if self.clip is None:
            return
        now = self._now
        # 0. EXIT：当前 clip 的 exit_frames（FIX J）
        if self.phase == AnimationPhase.EXIT:
            seq = self._sequence_for_plan(plan)
            if seq is not None and getattr(seq, "exit_frames", None):
                fr = self._frames_for(seq, "exit") or getattr(seq, "frames", None) or []
                if fr:
                    self.clip.play(AnimationSpec(fr, fps=FRAME_ANIM_FPS, loop=False), now=now)
                    return
            self.phase = AnimationPhase.LOOP
        # 1. transition 优先
        trans = plan.get("transition")
        if trans:
            seq = self.assets.sequence_for(trans) if self.assets else None
            if seq is not None:
                fr = self._frames_for(seq, "entry") or self._frames_for(seq, "loop") or seq.frames
                spec = AnimationSpec(fr, fps=FRAME_ANIM_FPS, loop=False)
                self.clip.play(spec, now=now)
                self.stats["degraded"] += 0
                return
            self.stats["degraded"] += 1
        # 1b. 拖拽 override（FIX E1）：高优先，有 drag 资产→用；无→DEGRADED_DRAG_VISUAL
        if self._drag_override_active and plan.get("activity") != "idle":
            entry = self.assets.entry_for_state("standing", "surprised", "user", "drag") if self.assets else None
            if entry is not None:
                fr = self._frames_for(entry, "loop") or entry.frames or [entry.path]
                self.clip.play(AnimationSpec(fr, fps=entry.fps or 12, loop=entry.loop), now=now)
                self._drag_override = False
                return
            self._drag_override = True
            plan["degraded"] = dict(plan.get("degraded", {}) or {})
            plan["degraded"]["DEGRADED_DRAG_VISUAL"] = {"reason": "missing_drag_asset"}
        # 2. 空间移动 overlay（Phase 12 §56-§61）：她正在走 → 用 walk 视觉。
        if self.movement_moving and not trans and self.phase in (AnimationPhase.LOOP, AnimationPhase.REACT):
            walk = self._walk_sequence()
            if walk is not None:
                fr = self._frames_for(walk, "loop") or getattr(walk, "frames", None) or []
                if fr:
                    self.clip.play(AnimationSpec(fr, fps=FRAME_ANIM_FPS, loop=True), now=now)
                    return
            self.movement_degraded = True
        asset_action = plan.get("asset_action") or "idle"
        target_pose = plan.get("target_pose") or "standing"
        expression = plan.get("expression") or "neutral"
        gaze = plan.get("gaze") or "front"
        # 3. action sequence（若素材 action 本身是 sequence，如 walk/read）
        seq = self.assets.sequence_for(asset_action) if self.assets else None
        if seq is not None and (seq.entry_frames or seq.loop_frames or seq.exit_frames):
            section = "loop" if (self.phase in (AnimationPhase.LOOP, AnimationPhase.REACT)) else "entry"
            fr = self._frames_for(seq, section) or self._frames_for(seq, "loop") or seq.frames
            self.clip.play(AnimationSpec(fr, fps=FRAME_ANIM_FPS, loop=(self.phase == AnimationPhase.LOOP)), now=now)
            return
        # 4. 非 idle action 的 action frame（read/eat/play/think/... 静态资产）→ FIX C。
        #    关键：优先表达"她正在做什么"（action asset 存在），而非退成 target-pose 的 idle
        #    （manifest 无 sitting/read，但存在 standing/read；不能静默坐到 idle）。
        if asset_action != "idle":
            entry = self._resolve_action_asset(asset_action, target_pose, expression, gaze)
            if entry is not None:
                fr = self._frames_for(entry, "loop") or entry.frames or [entry.path]
                self.clip.play(AnimationSpec(fr, fps=entry.fps or FRAME_ANIM_FPS, loop=entry.loop), now=now)
                plan["resolved_asset"] = entry.asset_id
                if entry.posture and entry.posture != target_pose:
                    plan["degraded"] = dict(plan.get("degraded", {}) or {})
                    plan["degraded"]["DEGRADED_POSTURE_FOR_ACTION"] = {
                        "action": asset_action, "requested": target_pose, "actual": entry.posture}
                return
        # 4b. idle 时优先 pose loop（standing_loop/sitting_loop/...）→ FIX C
        loop_seq = self.assets.sequence_for(f"{target_pose}_loop") if self.assets else None
        if loop_seq is not None and (loop_seq.frames or loop_seq.loop_frames):
            fr = self._frames_for(loop_seq, "loop") or loop_seq.frames
            self.clip.play(AnimationSpec(fr, fps=loop_seq.fps or FRAME_ANIM_FPS, loop=True), now=now)
            return
        # 5. base pose / 单帧静态（最后兜底）
        entry = self.assets.entry_for_state(target_pose, expression, gaze, "idle") if self.assets else None
        if entry is not None:
            fr = self._frames_for(entry, "loop") or entry.frames or [entry.path]
            self.clip.play(AnimationSpec(fr, fps=entry.fps or FRAME_ANIM_FPS, loop=entry.loop), now=now)

    @staticmethod
    def _frames_for(seq, section: str) -> list:
        if section == "entry" and getattr(seq, "entry_frames", None):
            return list(seq.entry_frames)
        if section == "loop" and getattr(seq, "loop_frames", None):
            return list(seq.loop_frames)
        if section == "exit" and getattr(seq, "exit_frames", None):
            return list(seq.exit_frames)
        return list(getattr(seq, "frames", []) or [])

    def _has_entry_frames(self, plan: Dict[str, Any]) -> bool:
        clip = plan.get("clip", "")
        if not self.assets:
            return False
        seq = self.assets.sequence_for(clip)
        return seq is not None and bool(getattr(seq, "entry_frames", None))


def _now() -> float:
    try:
        import time
        return time.monotonic()
    except Exception:
        return 0.0


# ---------------------------------------------------------------- GazeRuntime（§14-§18）
class GazeRuntime:
    """Gaze hold/cooldown/return。semantic_gaze 来自 Frame；visual_gaze 经 hold+cooldown 平滑。"""
    GAZE_DIRS = {"USER": "user", "SCREEN": "screen", "SIDE": "side",
                 "DOWN": "down", "AROUND": "around", "AWAY": "away", "NONE": "front"}
    def __init__(self, min_hold: float = 1.2, cooldown: float = 1.5) -> None:
        self.min_hold = min_hold
        self.cooldown = cooldown
        self.semantic_gaze = "NONE"
        self.visual_gaze = "front"
        self.gaze_started_at = _now()
        self.cooldown_until = 0.0
        self._side_last = "right"
        self._initialized = False

    def update(self, semantic_gaze: str, now: float | None = None) -> str:
        now = now or _now()
        target = self.GAZE_DIRS.get(semantic_gaze, "front")
        # 首次或首变化：无条件提交（避免注入时间 < 内部 _now 导致 hold 永不通过）
        if not self._initialized:
            self.semantic_gaze = semantic_gaze
            self.visual_gaze = target
            self.gaze_started_at = now
            self.cooldown_until = now + self.cooldown
            self._initialized = True
            return self.visual_gaze
        # 同 semantic → 保持（min_hold），不每次 Frame 重开 user gaze（§15）
        if semantic_gaze == self.semantic_gaze:
            return self.visual_gaze
        # 有新 semantic → 只有过 min_hold/cooldown 才换
        if now - self.gaze_started_at >= self.min_hold and now >= self.cooldown_until:
            self.semantic_gaze = semantic_gaze
            self.visual_gaze = target
            self.gaze_started_at = now
            self.cooldown_until = now + self.cooldown
        return self.visual_gaze


# ---------------------------------------------------------------- ExpressionHold（§20-§21）
class ExpressionHold:
    """Expression min hold，避免 neutral→soft→neutral 3 秒乱跳；高优先级 reaction 可覆盖。"""
    def __init__(self, min_hold: float = 1.5) -> None:
        self.min_hold = min_hold
        self.current_expression = "neutral"
        self.expression_started_at = _now()
        self._high_prio_override = False
        self._initialized = False

    def update(self, semantic_expression: str, high_prio: bool = False,
               now: float | None = None) -> str:
        now = now or _now()
        if not self._initialized:
            self.current_expression = semantic_expression
            self.expression_started_at = now
            self._initialized = True
            return self.current_expression
        if semantic_expression == self.current_expression:
            return self.current_expression
        # 高优先级 reaction 可覆盖普通 hold（§21）
        if high_prio or (now - self.expression_started_at >= self.min_hold):
            self.current_expression = semantic_expression
            self.expression_started_at = now
        return self.current_expression

