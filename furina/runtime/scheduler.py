"""调度器（plan/7 §40-42）：驱动三档 Tick 的生命循环。

Fast ~60fps：渲染/动画（由 Qt 主循环驱动）
Medium ~3s：状态更新 / 需求 / 意图 / 行为选择 / 窗口感知
Slow ~120s：记忆巩固 / 关系 / 长期行为
"""
from __future__ import annotations

import time
import random
from typing import Optional

from furina.core import Clock, EventBus, EventType, get_logger
from furina import state as st
from furina import behavior as bh
from furina import memory as mem
from furina.director import Director
from . import window_awareness as wa
from .world import DesktopWorld

log = get_logger("runtime.scheduler")

# 会说话/会发声的活动（生命决策后据此触发 DialogueBrain）
SPEAKABLE_ACTIVITIES = {"talk", "greet", "approach_user", "play", "ask_user", "comment",
                        "invite_user", "seek_attention", "offer_help", "celebrate", "comfort"}


def pose_for_activity(activity: str, emotion: str = "") -> tuple:
    """Life 活动 → 具体身体姿态 (posture, emotion, gaze, action)。

    让 80 个素材真正被用到：不同活动选不同 posture/emotion/gaze/action，
    而不是永远 standing/neutral/front。emotion 参数（来自 LifeBrain 决策）优先，
    否则按活动给默认情绪。
    """
    emo = emotion or "neutral"
    # 任务书 §3 / 用户反馈「action在变但前端没变化」：每个 Life 活动映射到**真实且不重复**的素材。
    # 用确认存在的 24 个动作素材 + 14 种情绪 idle，保证 activity 变 → sprite 真的变。
    base = {
        # 生存/生活（有专属动作素材）
        "eat": ("standing", "happy", "front", "eat"),
        "drink": ("standing", "neutral", "front", "drink"),
        "read": ("standing", "focus", "front", "read"),
        "stretch": ("standing", "sleepy", "front", "stretch"),
        "play": ("standing", "playful", "front", "play"),
        "play_with_object": ("standing", "playful", "front", "play"),
        "sleep": ("sleeping", "sleepy", "front", "idle"),
        "rest": ("sitting", "calm", "down", "idle"),
        "nap": ("standing", "sleepy", "front", "nap"),
        "yawn": ("standing", "sleepy", "front", "yawn"),
        "sigh": ("standing", "sad", "front", "sigh"),
        "dance": ("standing", "happy", "front", "dance"),
        "giggle": ("standing", "happy", "front", "giggle"),
        "groom": ("standing", "proud", "front", "groom"),
        "excited": ("standing", "happy", "front", "excited"),
        # 社交（情绪区分，避免共用同一张）
        "observe_user": ("standing", "curious", "screen", "idle"),
        "observe_work": ("standing", "focused", "screen", "idle"),
        "watch_user": ("standing", "curious", "user", "idle"),
        "approach_user": ("standing", "happy", "user", "idle"),
        "talk": ("standing", "grateful", "user", "idle"),
        "greet": ("standing", "happy", "front", "wave"),
        "ask_user": ("standing", "confused", "user", "idle"),
        "comment": ("standing", "determined", "user", "idle"),
        "invite_user": ("standing", "playful", "user", "idle"),
        "seek_attention": ("standing", "embarrassed", "user", "idle"),
        "offer_help": ("standing", "proud", "user", "idle"),
        "assist_user": ("standing", "focus", "screen", "idle"),
        "celebrate": ("standing", "happy", "front", "excited"),
        "comfort": ("standing", "sad", "user", "idle"),
        # 自主生活（情绪区分）
        "think": ("standing", "thoughtful", "front", "think"),
        "daydream": ("standing", "grateful", "up", "idle"),
        "tidy": ("standing", "proud", "front", "idle"),
        "explore": ("standing", "curious", "left", "idle"),
        "look_around": ("standing", "curious", "right", "idle"),
        "walk": ("standing", "neutral", "left", "idle"),
        "wander": ("standing", "neutral", "right", "idle"),
        "idle": ("standing", "neutral", "front", "idle"),
        "continue": ("standing", "neutral", "front", "idle"),
    }
    posture, base_emo, gaze, action = base.get(activity, ("standing", "neutral", "front", "idle"))
    # LifeBrain 给的情绪优先（若在素材情绪集里可用则用它）
    return posture, (emo if emotion else base_emo), gaze, action


def _macro_for(activity: str) -> "st.MacroState":
    """Life 活动 → 宏观状态（plan/2 §四 Body State 由 Runtime 决定；这里是 Life→Macro）。"""
    mapping = {
        "sleep": "sleeping", "rest": "resting",
        "eat": "living", "drink": "living", "play": "living", "play_with_object": "living",
        "walk": "living", "stretch": "living", "tidy": "living", "explore": "living",
        "look_around": "living", "daydream": "living", "think": "living", "read": "living",
        "idle": "idle", "observe_user": "working", "observe_work": "working",
        "assist_user": "working", "offer_help": "working",
        "approach_user": "living", "talk": "engaged", "greet": "engaged", "ask_user": "engaged",
        "comment": "engaged", "invite_user": "engaged", "seek_attention": "engaged",
        "watch_user": "engaged", "celebrate": "engaged", "comfort": "engaged",
        "continue": "idle",
    }
    return st.MacroState(mapping.get(activity, "idle"))


class Scheduler:
    def __init__(self, bus: EventBus, state_engine: st.StateEngine,
                 behavior_engine: bh.BehaviorEngine, director: Director,
                 memory_engine: mem.MemoryEngine, world: DesktopWorld,
                 window_awareness: wa.WindowAwareness,
                 life_brain=None, dialogue_brain=None, emotion_engine=None, motivation=None,
                 relationship_engine=None, embodiment=None) -> None:
        self.bus = bus
        self.se = state_engine
        self.be = behavior_engine
        self.director = director
        self.me = memory_engine
        self.world = world
        self.wa = window_awareness
        self.life_brain = life_brain          # 三脑：生命决策
        self.dialogue_brain = dialogue_brain  # 三脑：语言
        self.emotion = emotion_engine          # 情感引擎（确定性）
        self.motivation = motivation           # 行为动机评分器
        self.relationship = relationship_engine  # 关系引擎（Phase 04）
        # 具身表达引擎（Phase 09：语义身体层，确定性，0 LLM）
        self.embodiment = embodiment
        self._last_body = None                 # 最近一帧 BodyExpressionState（供 FrameBuilder 消费）
        # 唯一 Frame 契约（Phase 10）：Builder + 最近发布的 Frame
        from .frame_builder import RuntimeFrameBuilder
        from .frame import CharacterRuntimeFrame
        self.frame_builder = RuntimeFrameBuilder(character_id="furina")
        self._last_frame: Optional[CharacterRuntimeFrame] = None
        self._last_frame_built_at = 0.0
        self._frame_publish_interval = 1.0     # 语义变化低频发布（§15 分层，不随 60FPS）
        # 结构化世界感知（Phase 06）：raw signals → WorldState/Events/Salience
        from furina.world_perception import WorldPerception
        self.world_perc = WorldPerception()
        self.clock = Clock(fast=1 / 60, medium=3.0, slow=120.0)

        # 订阅事件
        # Phase 13 终审 §8 / FINAL-R1 §3：**运行时单 apply 线程** —— 后台线程（Dialogue/Agent worker）
        # emit 的 BRAIN_SPOKE / AGENT_COMPLETED / AGENT_FAILED 不得在 worker 线程同步改运行时状态，
        # 一律经 RuntimeDispatcher（显式队列）由 owner 线程统一落地。
        from furina.runtime.dispatcher import RuntimeDispatcher
        self.dispatcher = RuntimeDispatcher()
        bus.on(EventType.ACTIVE_WINDOW_UPDATED, self._on_window)
        bus.on(EventType.INTERACTION_INPUT, self._on_interaction)   # GUI/owner 线程来源，直接处理
        bus.on(EventType.BRAIN_SPOKE, lambda ev: self.dispatcher.submit(lambda: self._on_brain(ev)))
        bus.on(EventType.AGENT_COMPLETED, lambda ev: self.dispatcher.submit(lambda: self._on_agent_done(ev)))
        bus.on(EventType.AGENT_FAILED, lambda ev: self.dispatcher.submit(lambda: self._on_agent_fail(ev)))

        self._last_window_poll = 0.0
        self._debug_text = ""
        self._speech = ""           # 当前要显示的一句台词
        self._speech_until = 0.0    # 该台词显示到何时
        # Phase 12：像素空间移动已由 DesktopSpatialRuntime 接管。
        # Scheduler 不再保存/操作 _move_target / _walk_visible / 窗口坐标。
        self._life_decision_at = 0.0   # 上次 LifeBrain 重决策时间
        self._life_interrupt_pending = False   # 有重要事件要立即重决策
        self._life_next_think = 90.0    # LifeBrain 下次重决策间隔
        # FINAL-R1 §7：社交响应窗口 —— 芙宁娜主动发起社交尝试后，用户在窗口内无回应 → USER_IGNORE 一次。
        # 窗口时长是**交互语义**（不是多样调参）；用户缺席从起点就不开窗口。
        self._pending_social_bid: Optional[dict] = None
        self._social_bid_window = 60.0
        self._current_life_activity = "idle"   # 当前执行中的生活活动（闭环：结束时结算经历）
        self._current_activity_duration = 0.0  # 当前活动已执行时长
        # KPI 监控（任务书 §24-27）
        self._kpi_activity = []                    # 近 N 次活动（覆盖率）
        self._last_speech_at = time.monotonic()    # 上次自主发言
        self._idle_streak = 0                      # 连续 idle 段数
        self._recent_events: list = []
        self._pending_life_decision = None   # 后台线程产出的待应用决策
        self._life_running = False           # 后台决策是否进行中（防并发）

    # -------------------------------------------------- 启动注册三档 tick
    def start(self, window) -> None:
        self.window = window
        # H1-FINAL §6：**统一启动边界绑定 owner** —— launch 与 launch_harness 都经 start()，
        # 早于首个 timer/事件的消息/喂食也拿到已绑定 owner（不依赖"第一个 timer 先于第一次点击"）。
        self.dispatcher.bind_owner()
        # Medium：状态 + 行为
        self.clock.schedule("medium", self.clock.medium_interval, self._tick_medium)
        # Slow：记忆/关系
        self.clock.schedule("slow", self.clock.slow_interval, self._tick_slow)

    # -------------------------------------------------- Fast 由 Qt 循环调用
    def step(self, dt: Optional[float] = None) -> None:
        # §8：先落地后台线程排队的运行时变更（owner 线程 = 本调用线程），再推进时钟
        self.drain_apply()
        self.clock.step(dt)
        # Phase 12：像素空间移动已由 SpatialRuntime 接管。
        # Scheduler 不再拥有 / 操作 自主移动状态（legacy _move_step 已收敛为 no-op）。

    # -------------------------------------------------- §8/§3：运行时 apply 队列（单 owner 线程落地）
    def _enqueue_apply(self, fn) -> None:
        """提交一段"owner 线程执行"的运行时变更（worker 线程调用）。"""
        self.dispatcher.submit(fn)

    def drain_apply(self) -> None:
        """把排队的运行时变更在**当前线程**（owner）逐条落地。Harness/测试在 GUI/主线程调用。"""
        self.dispatcher.drain()

    def require_owner(self, what: str) -> None:
        """域变更守卫：非 owner 线程调用将抛错（FINAL-R1 §3 生产契约）。"""
        self.dispatcher.require_owner(what)

    def _move_step(self) -> None:
        """⚠️ DEPRECATED（Phase 12 Spatial Ownership Migration）。

        像素空间移动已由 ``DesktopSpatialRuntime`` 接管；Scheduler 不再保存/操作
        ``_move_target`` / ``_walk_visible`` / 窗口坐标，也不调用 ``window.set_position``。
        生产调用计数 = 0。
        """
        import warnings
        warnings.warn("Scheduler._move_step is deprecated; spatial movement owned by "
                      "DesktopSpatialRuntime.", DeprecationWarning, stacklevel=2)
        return None

    # -------------------------------------------------- events
    def _on_window(self, ev) -> None:
        info = ev.payload
        if info:
            # Phase 13 FINAL-R1 §1.2：这里**只缓存原始窗口事实**（供 _tick_medium 做唯一一次 World 更新）。
            # 不再独立调用 world_perc.update —— 否则同一 medium 采样内 class/process 两次喂入，
            # 会与 30s 稳定性窗口互相重置 pending 候选（UNKNOWN↔CODING 抖动，转换永不提交）。
            self._last_info = info
            self.se.on_active_window(info.process or info.app, info.title)
            if getattr(info, "rect", None) is not None:
                self.world.update_active_window(info.rect)

    def _on_brain(self, ev) -> None:
        out = ev.payload
        if out and getattr(out, "speech", ""):
            self._say(out.speech)
            # 让大脑意图进入行为（表现层 plan/8 §5：LLM 只产出结构化意图/状态）
            intent = getattr(out, "intent", "")
            if intent:
                self.se.state.intent.action = intent
                # 意图 → 宏观状态（睡眠→SLEEPING；其余维持）
                macro_map = {"sleep": "sleeping", "eat": "living", "drink": "living",
                             "play": "living", "rest": "resting", "approach_user": "living",
                             "observe_user": "working"}
                self.se.state.life.macro = st.MacroState(macro_map.get(intent, self.se.state.life.macro.value))
            # Phase 13 FINAL-R1 §2.1：**EmotionEngine 是情绪真相唯一所有者**。
            # BRAIN_SPOKE 的 emotion 只是表达提示（可能来自 stale worker 快照），
            # 落入非权威槽 Intent.emotion，**绝不写 EmotionState.label**。
            payload_emotion = getattr(out, "emotion", "")
            if payload_emotion:
                self.se.state.intent.emotion = payload_emotion

    def _on_agent_done(self, ev) -> None:
        # FIX G：Agent 完成 → 角色台词走 DialogueBrain（非固定 summary 冒充人格）
        summary = (ev.payload or {}).get("summary", "完成啦。")
        self.se.state.life.macro = st.MacroState.IDLE
        # §4.4/FINAL-R1 §2.2：Agent 验证成功 → EVENT_AGENT_DONE，apply + 立即派生（owner 线程）
        try:
            from furina.emotion import EVENT_AGENT_DONE
            self.emotion.apply_event(EVENT_AGENT_DONE, tired_hint=self._tired_hint())
        except Exception:
            pass
        # §6：**已验证**的 Agent 帮助 → 真实关系证据 EV_SUCCESSFUL_HELP（恰好一次，
        # 经 RelationshipEngine 唯一写入口；未验证成功不得发放）。
        try:
            verified = bool((ev.payload or {}).get("verified", False))
            if verified and self.relationship is not None:
                from furina.relationship.engine import EV_SUCCESSFUL_HELP
                self.relationship.apply(EV_SUCCESSFUL_HELP)
                self.se.state.relationship = self.relationship.state
                if self.me is not None:
                    self.me.store.save_relationship(self.relationship.state)
        except Exception:
            pass
        self._speak_via_dialogue(intent="assist_user", emotion=self.se.state.emotion.label,
                                 user_initiated=True, context=summary, activity="agent_report")

    def _on_agent_fail(self, ev) -> None:
        # §7：Agent 失败的用户可见反馈 = DialogueBrain(task_mode) 角色化；仅当对话失败才允许 SYSTEM_STATUS 事实。
        self.se.state.life.macro = st.MacroState.IDLE
        err = (ev.payload or {}).get("error", "") or (ev.payload or {}).get("reason", "")
        self._speak_via_dialogue(intent="agent", emotion=self.se.state.emotion.label,
                                 user_initiated=True, context=f"任务失败了：{err}",
                                 activity="agent_fail", interaction="agent")
        # DialogueBrain 失败 → 确定性系统事实（非角色化），放在独立状态区，不冒充 Furina 台词
        if not self._speech:
            self._say(f"（系统状态：Agent 任务未完成。{err}）" if err else "（系统状态：Agent 任务失败。）", dur=4.0)

    def _on_interaction(self, ev) -> None:
        # 即时层（plan/4 §27）：互动改变情绪/社交需求，→ 表现层选对应表情素材
        e = ev.payload
        if e is None:
            return
        kind = e.type.value
        # Phase 13 终审 §7：**指针控制阶段 ≠ 有意义互动**。
        # GRAB / 原始 RELEASE / HOVER / LEAVE 只是指针移动，不进入生命因果（不扣社交、不加接纳度、
        # 不触发关系/情绪/记忆/打断）。只有定型的语义互动才允许：CLICK / PETTING / POKE / DRAG。
        _POINTER_CONTROL = ("grab", "release", "hover", "leave", "approach", "double_click")
        if kind in _POINTER_CONTROL:
            return
        # FINAL-R1 §7：真实用户回应（定型语义互动）→ 取消 pending social bid（不产生 ignore）
        self._pending_social_bid = None
        # 互动台词（FIX G）→ 走 DialogueBrain（非固定句池）。
        # Phase 13A §6：**Emotion state = EmotionEngine only；Relationship = RelationshipEngine.apply only**。
        # Scheduler._on_interaction **不再直接写 emotion/relationship**（App 的 EmotionEngine/Harness 路由负责），
        # 只负责：intent / dialogue / memory / life interrupt / 读取已更新后的 state。
        if kind == "petting":
            self.se.state.intent.action = "head_touch"   # 触发摸头反应姿态
            self._speak_via_dialogue(intent="head_touch",
                                     emotion=self.se.state.emotion.label,
                                     user_initiated=True, context="你轻轻摸了摸我的头",
                                     activity="head_touch", interaction="petting")
        elif kind == "poke":
            self._speak_via_dialogue(intent="poke", emotion=self.se.state.emotion.label,
                                     user_initiated=True, context="你戳了我一下",
                                     activity="poke", interaction="poke")
        elif kind == "drag":
            self._speak_via_dialogue(intent="drag", emotion=self.se.state.emotion.label,
                                     user_initiated=True, context="你把我拎起来移动",
                                     activity="drag", interaction="drag")
        elif kind == "click":
            self._speak_via_dialogue(intent="click", emotion=self.se.state.emotion.label,
                                     user_initiated=True, context="你点了我一下",
                                     activity="click", interaction="click")
        # 允许 EmotionEngine 更新后的 label 落到 intent (head_touch 等) —— 不在此再写 emotion。
        self.se.state.needs.social_need = max(0, self.se.state.needs.social_need - 5)
        # 用户主动互动 → 提高对主动的接纳度（任务书 §23 自适应）
        if self.life_brain is not None and hasattr(self.life_brain, "adapt_tolerance"):
            try:
                self.life_brain.adapt_tolerance(user_responded=True, was_interactive=True)
            except Exception:
                pass
        # §6：关系只由 App._on_meaningful_interaction（RelationshipEngine.apply 唯一入口）写入；
        # 这里不重复 apply。仅同步状态引用（只读引用，不改关系值）。
        if self.relationship is not None:
            try:
                self.se.state.relationship = self.relationship.state
            except Exception:
                pass
        # H1-FINAL §8：**长期记忆唯一 owner = App 语义互动处理器**（_on_meaningful_interaction 的
        # memory.observe）。这里**不再** _consolidate_episode —— 否则一次定型语义事件写两条长期记忆。
        # 重要互动 → 触发 LifeBrain 重决策（摸头/戳/拖拽会唤醒睡眠，进入互动而非继续睡）
        self._interrupt_life(f"user_{kind}")
        if self.se.state.life.macro == st.MacroState.SLEEPING:
            self.se.state.life.macro = st.MacroState.ENGAGED

    # -------------------------------------------------- 经历→记忆（Phase 07 §4）
    def _consolidate_episode(self, event_type: str, activity: str = "", outcome: str = "") -> None:
        """把一次值得记的经历写入长期记忆（经 Importance 过滤，低重要不落库）。"""
        if self.me is None or not hasattr(self.me, "consolidate"):
            return
        try:
            from furina.memory.experience import Experience, template_summary
            wctx = ""
            wp = getattr(self, "world_perc", None)
            if wp is not None:
                ua = getattr(wp.state, "user_activity", None)
                wctx = ua.value if hasattr(ua, "value") else (ua or "")
            # 情绪强度（emotional_intensity）近似来自情绪 arousal
            emo = self.se.state.emotion
            e = Experience(
                token=f"{event_type}|{wctx}|{activity}", event_type=event_type,
                summary=template_summary(event_type, wctx, activity, outcome),
                world_context=wctx, activity=activity, outcome=outcome,
                emotional_intensity=getattr(emo, "arousal", 0.4) or 0.4,
                relationship_relevance=0.7 if event_type.startswith("user") else 0.3,
                user_relevance=0.7 if event_type.startswith("user") else 0.3,
            )
            self.me.consolidate(e)
        except Exception:
            pass

    # -------------------------------------------------- medium tick
    def _tick_medium(self, dt: float) -> None:
        # 窗口 / 时钟
        if time.monotonic() - self._last_window_poll >= self.clock.medium_interval:
            self.wa.poll()
            self._last_window_poll = time.monotonic()
        # Phase 13 终审 §2.1：localtime()[:2] 是 (year, month)，必须传 (hour, minute)。
        lt = time.localtime()
        self.se.update_clock(lt.tm_hour, lt.tm_min)
        # §2.2/FINAL-R1 §1.1：**真实输入空闲秒**来自 WindowAwareness（GetLastInputInfo+GetTickCount64）。
        # 空闲真相不可用时（idle_available=False）保留上一有效值，**不假装 0**（那不是"用户一直活跃"）。
        # H1-FINAL §7：availability 位跨运行时边界 —— 首样本不可用时，world 不得从默认 0 制造活跃转换。
        idle_avail = bool(getattr(self.wa, "idle_available", True))
        self.se.state.idle_available = idle_avail
        if idle_avail:
            self.se.state.user_idle_seconds = float(getattr(self.wa, "last_idle", 0.0) or 0.0)
        # 世界感知：**每 medium 采样恰好一次 update**（§1.2）。
        # 原始事实（class/process/title/rect/idle/hour/minute）由 wa.poll() 缓存，这里统一消费；
        # _on_window 不再独立推进 WorldPerception。
        try:
            info = getattr(self, "_last_info", None)
            self.world_perc.update(app=getattr(info, "app", "") or self.se.state.active_window_app,
                                   title=getattr(info, "title", "") or self.se.state.active_window_title,
                                   process=getattr(info, "process", "") or self.se.state.active_window_app,
                                   idle_seconds=self.se.state.user_idle_seconds,
                                   hour=self.se.state.clock_hour,
                                   minute=self.se.state.clock_minute,
                                   typing=bool(getattr(self, "_last_typing", False)), dt=dt,
                                   idle_available=idle_avail)   # H1-FINAL §7：availability 位
            self.se.state.world = self.world_perc
            # §2.3：user_working 来自 World 感知（进程分类），不再用上一帧值自喂
            self.se.state.user_working = bool(
                self.world_perc.factors().get("user_working", False))
            # H1 §3：**稳定**的 WORK_STARTED/WORK_ENDED → 情绪语义事件，恰好一次。
            # 消费 `world_perc.last_events`（本次 update 新发出的事件实例，全局单调 seq），
            # **绝不从 recent_world_events 历史串推断**（旧串残留在列表里会反复重触发）。
            # World 事件本身有 20s debounce + 30s 稳定性窗口；每个实例在此恰好 apply 一次。
            try:
                w = self.world_perc.state
                for ev_key, emo_ev in (("WORK_STARTED", "user_work_start"),
                                       ("WORK_ENDED", "user_work_end")):
                    n = getattr(self.world_perc, "last_events", []).count(ev_key)
                    for _ in range(n):
                        from furina.emotion import EVENT_WORK_START, EVENT_WORK_END
                        self.emotion.apply_event(emo_ev, tired_hint=self._tired_hint())
                        self._recent_events.append(ev_key)
            except Exception:
                pass
        except Exception:
            pass
        # 需求（本地规则，无需 LLM）
        self.se.update_needs(dt, self.se.state.user_working,
                             self.se.state.user_idle_seconds)
        # 注入关系状态（Life Simulation P2：Motivation 读真实的 relationship）
        if self.me is not None:
            try:
                self.se.state.relationship = self.me.relationship
            except Exception:
                pass
        # 注意力预算恢复（任务书 §22）：随时间缓慢回升
        if self.life_brain is not None:
            try:
                if hasattr(self.life_brain, "regen_budget"):
                    self.life_brain.regen_budget(per_sec=0.02 * dt)
            except Exception:
                pass
        # 情绪自然衰减（Life Simulation P2：确定性情感随事件+时间演化）
        if self.emotion is not None:
            try:
                self.emotion.decay(dt=dt)
                # §4.1：sleepy 只允许由真实困倦信号派生（Needs），绝不把"平静"误判为困倦
                _n = getattr(self.se.state, "needs", None)
                tired = (float(getattr(_n, "sleepiness", 0.0)) + float(getattr(_n, "fatigue", 0.0))) / 200.0 \
                    if _n is not None else 0.0
                self.emotion.derive_label(tired_hint=max(0.0, min(1.0, tired)))
            except Exception:
                pass
        # §4.4/FINAL-R1 §2.2：用户返回（idle → active 边界）→ EVENT_RETURN，apply + 立即派生
        try:
            idle = float(getattr(self.se.state, "user_idle_seconds", 0.0))
            was_idle = bool(getattr(self, "_was_user_absent", False))
            if idle < 300 and was_idle and self.emotion is not None:
                from furina.emotion import EVENT_RETURN
                self.emotion.apply_event(EVENT_RETURN, tired_hint=self._tired_hint())
                self._recent_events.append("user_return")
            self._was_user_absent = idle >= 300
        except Exception:
            pass
        # FINAL-R1 §7：社交响应窗口到期检查（owner 线程，medium tick）
        try:
            self._tick_social_bid()
        except Exception:
            pass
        # 关系自然恢复（Phase 04：无负向事件时 annoyance/tolerance/confidence 回落）
        if self.relationship is not None:
            try:
                self.relationship.decay(dt=dt)
                self.se.state.relationship = self.relationship.state
            except Exception:
                pass
        # 三脑生命决策：LifeBrain 决定“她下一步做什么”（低频，后台线程，不阻塞 UI）
        if self.life_brain is not None:
            self._tick_life_apply()            # 先落地上一轮后台结果（主线程，安全）
            self._drive_life()                 # 安排本轮/下轮后台决策
        else:
            # 无 LifeBrain（异常/未配置）→ 回退本地 Utility 意图
            self.se.generate_intent(self.se.state)
            self.be.step(self.se.state.snapshot())
        # 记忆 → 行为偏置（plan/6 §28：记忆真实参与行为选择，而非只喂 LLM）
        snap = self.se.state.snapshot()
        if self.me is not None:
            snap["memory_bias"] = self.me.behavior_hint(
                context=snap.get("activity", ""),
                user_context={"working": snap.get("user_working", False)})
        # M4 靠近：Phase 12 已由 SpatialRuntime 消费 Frame.motion/proximity 决定；
        # Scheduler 不再直接设 _move_target / 改窗口位置（legacy 收敛为 no-op）。
        # Director 仲裁唯一当前动作（用户互动/Agent 任务可打断自主行为）
        self.director.drain()
        # 决策轨迹日志（final test.md A-17：能回答“为什么做这个动作”）
        try:
            log.info("decision=%s | state=mood:%.0f,needs:%s | intent=%s(pri%.2f) | action=%s",
                     self.se.state.life.activity,
                     self.se.state.emotion.mood,
                     ",".join(f"{k}:{round(getattr(self.se.state.needs, k))}"
                              for k in ("energy", "fatigue", "hunger", "boredom", "social_need")),
                     self.se.state.intent.action, self.se.state.intent.priority,
                     getattr(self.director.current(), "action", "idle"))
        except Exception:
            pass
        # 更新窗口表现
        self._update_scene()
        # KPI 监控（任务书 §24-27：安静/卡死/覆盖率）
        self._monitor_kpi()

    def _monitor_kpi(self) -> None:
        """开发监控：检测过度安静/过度 idle/行为覆盖，输出警告（不强制干预，只诊断）。"""
        try:
            st = self.se.state
            # 连续 idle/发呆检测 —— Phase 13 终审 §5：**安静共处是合法的**，不再因 idle ~18s 强制唤醒
            # LifeBrain（那是人工多样性）。只保留 KPI 日志（诊断），不再 _interrupt_life。
            self._kpi_activity.append(st.life.activity)
            self._kpi_activity = self._kpi_activity[-20:]
            if st.life.macro == st.MacroState.IDLE and st.life.activity == "idle":
                self._idle_streak += 1
            else:
                self._idle_streak = 0
            if self._idle_streak >= 6:   # ~6 次 medium tick ≈ 18s 仍 idle（仅日志，不唤醒）
                log.info("KPI: quiet idle 持续 %d 段（合法，不强制唤醒）", self._idle_streak)
                self._idle_streak = 0
            # 沉默检测（任务书 §26）
            if time.monotonic() - self._last_speech_at > 900:   # 15min 无自主发言
                log.warning("KPI: Furina 已沉默 >=15 分钟 — 是否 Busy/预算耗尽/Brain 失败？")
                self._last_speech_at = time.monotonic()   # 重置避免刷日志
            # 覆盖率统计（开发期）：每小时输出一次
            per = getattr(self, "_kpi_last_report", 0.0)
            if time.monotonic() - per >= 3600 and self._kpi_activity:
                from collections import Counter
                c = Counter(self._kpi_activity)
                n = sum(c.values())
                stats = ", ".join(f"{a}:{100*cc//n}%" for a, cc in c.most_common(6))
                log.info("KPI 覆盖率(近20次): %s | idle%%=%d", stats, 100*c.get("idle", 0)//n)
                self._kpi_last_report = time.monotonic()
        except Exception:
            pass

    # -------------------------------------------------- 三脑：LifeBrain 驱动生命态
    def _drive_life(self) -> None:
        """在 LifeBrain 的决策节奏上运行；重要事件可强制立即重决策。

        LLM 调用（structured）可能耗时 1~2s，**绝不能阻塞 Qt 主线程**（否则窗口卡死/不灵敏）。
        这里把决策放到后台线程，结果在下一 tick 应用到状态。
        """
        now = time.monotonic()
        due = (now - self._life_decision_at) >= self._life_think_interval()
        if not (due or self._life_interrupt_pending):
            return
        # 避免并发决策 / 重复触发
        if getattr(self, "_life_running", False):
            return
        self._life_running = True
        self._life_failure_count = getattr(self, "_life_failure_count", 0)
        self._life_fallback_count = getattr(self, "_life_fallback_count", 0)
        self._life_brain_success_count = getattr(self, "_life_brain_success_count", 0)
        snap_recent = list(self._recent_events)
        self._recent_events.clear()
        self._life_interrupt_pending = False
        self._life_decision_at = now
        import threading
        def _decide():
            try:
                # Behavior Motivation：先算候选冲动分（确定性），喂给 Brain 人格化选择
                cands = []
                if self.motivation is not None and self.emotion is not None:
                    try:
                        # 上下文：有趣事件 / 长时间沉默 / 用户回归 → 给 talk/互动 事实依据（§6-8）
                        ctx = {}
                        if snap_recent:
                            ctx["interesting_event"] = snap_recent[0]
                        if time.monotonic() - self._last_speech_at > 240:
                            ctx["long_silence"] = True
                        if self.se.state.user_working:
                            ctx["talk_boost"] = 0.0   # 用户忙不主动说话
                        else:
                            ctx["talk_boost"] = 0.12
                        # 注入世界感知（Phase 06：World → Motivation 因果）
                        try:
                            wf = self.world_perc.factors()
                            ctx["world"] = wf
                            ctx["recent_events"] = list(self.world_perc.event_tags())
                        except Exception:
                            pass
                        cands = [c.as_dict() for c in
                                 self.motivation.candidates(self.se.state, self.emotion, ctx=ctx)]
                    except Exception:
                        cands = []
                d = self.life_brain.decide(state=self.se.state,
                                           recent_events=snap_recent, force=True,
                                           candidates=cands)
                self._pending_life_decision = d
                self._life_brain_success_count += 1
            except Exception as e:  # pragma: no cover
                # RC1：失败不再静默吞掉 —— 结构化日志 + 计数（fallback 仍是合法容错）。
                self._life_failure_count += 1
                self._life_fallback_count += 1
                log.warning("LIFEBRAIN_DECISION_FAILED exception_type=%s fallback=local "
                            "lifeBrain_failures=%d lifeBrain_fallbacks=%d",
                            type(e).__name__, self._life_failure_count, self._life_fallback_count)
                self._pending_life_decision = None
            finally:
                self._life_running = False
        threading.Thread(target=_decide, daemon=True).start()

    def _tick_life_apply(self) -> None:
        """在 medium tick 末尾应用后台线程完成的 LifeBrain 决策（同一主线程，安全）。"""
        d = getattr(self, "_pending_life_decision", None)
        if d is None:
            return
        self._pending_life_decision = None
        try:
            self._apply_life_decision(d)
        except Exception as e:  # pragma: no cover
            log.warning("apply life decision err: %s", e)

    def _life_think_interval(self) -> float:
        """LifeBrain 的重决策间隔（Phase 13C §16）—— **尊重真实决策的 next-think/activity 时长语义**，
        只在安全界内 clamp，不再强制压到 5~9s（那是"行为节拍器"，会掩盖自主生命感）。
        §17：重要事件（interrupt）仍可提前重决策；正常安静共存不因"为了展示多样"频繁唤醒。
        """
        raw = float(getattr(self, "_life_next_think", 90.0))
        raw = max(5.0, min(raw, 120.0))   # 安全界限：不早于 5s，不迟于 120s
        cur_activity = getattr(self.se.state.life, "activity", "") if hasattr(self, "se") else ""
        if cur_activity in ("sleep", "rest"):
            return max(15.0, min(raw, 180.0))   # 睡眠/休息可更长，但仍会定期醒
        return raw

    def _apply_life_decision(self, d) -> None:
        """LifeBrain 决策 → 交给 Director 仲裁/执行（plan/8 §3：Director 是唯一 resolver）。

        LifeBrain 只产出 LifeDecision，**不直接写状态**；而是提交 ACTION_REQUEST，
        由 Director 决定谁执行（用户互动/Agent 任务可打断），再由 executor(app._on_execute) 落地。
        这样 action 反映真实决策，且用户互动/Agent 真正能打断自主行为。
        """
        st = self.se.state
        if d.is_continue:
            # 当前行为仍合适：仅延长下次重决策时间，不改变状态（避免翻车/“睡死”外的抖动）
            self._life_next_think = max(15.0, d.next_think_in)
            return
        # 经历→状态反馈（Life Simulation 闭环）：上一个**真正执行过的**活动结束 → 因果结算。
        # FINAL-R1 §5：实例只在 Director 实际执行（on_mind_action_started）时创建。
        # 若 mind 请求被更高优先级（用户/Agent）阻塞、从未执行 → 无实例 → 无结算、无 outcome。
        prev = getattr(self, "_current_life_activity", "idle")
        inst = getattr(self, "_activity_instance", None)
        if prev != d.activity and inst is not None and inst.get("status") == "RUNNING":
            try:
                now_t = time.time()
                started = float(inst.get("started_at", now_t))
                planned = float(inst.get("planned_duration", 0.0))
                elapsed = max(0.0, now_t - started)
                progress = min(1.0, elapsed / planned) if planned > 0 else 1.0
                pending = inst.get("pending_finish")   # 用户打断等外部原因
                if pending in ("aborted", "failed"):
                    reason, success = pending, False
                elif progress >= 1.0:
                    reason, success = "completed", True
                else:
                    reason, success = "interrupted", False
                inst.update({"status": self._canonical_status(reason),
                             "elapsed": round(elapsed, 1), "progress": round(progress, 2),
                             "finish_reason": reason})
                self._last_activity_finish = {
                    "activity": prev, "reason": reason,
                    "elapsed": round(elapsed, 1), "planned_duration": round(planned, 1),
                    "progress": round(progress, 2),
                }
                self._apply_activity_outcome(prev, success=success, reason=reason, progress=progress)
            except Exception:
                pass
        # 旧的生命行为（mind）已结束 → 释放 Director 接管权，让新决策能被仲裁
        try:
            self.director.finish(source="mind")
        except Exception:
            pass
        # 硬性反塌缩（任务 §18）—— Phase 13A：anti-collapse = OFF（与项目声明一致）。
        # 生产路径**不再**调用；由 personality/needs/homeostasis 产生自然多样性。
        # 旧 `_anti_collapse` 保留为未启用 debt（见 docs）。不要为"补分布"调任何参数。
        # d = self._anti_collapse(d)
        # 交给 Director（唯一 resolver）：source=mind（LifeBrain），priority 用内部需求。
        # FINAL-R1 §5：**这里不创建实例、不 mark_done** —— 只有 Director 真正执行该动作
        # （executor 回调 on_mind_action_started）才开始活动生命周期。
        try:
            from furina.director import ActionRequest
            from furina.director.director import P_INTERNAL_NEED
            req = ActionRequest(source="mind", action=d.activity, priority=P_INTERNAL_NEED,
                                interruptible=bool(getattr(d, "interruptible", True)),
                                reason=d.reason or f"{d.intent or d.activity}",
                                payload={"emotion": d.emotion,
                                         "planned_duration": float(getattr(d, "duration", 0.0) or 0.0),
                                         "speech_intent": getattr(d, "speech_intent", ""),
                                         "speech_level": getattr(d, "speech_level", 0),
                                         "dialogue_needed": getattr(d, "dialogue_needed", False),
                                         "exit_conditions": getattr(d, "exit_conditions", [])})
            self.director.submit(req)
        except Exception as e:  # pragma: no cover
            log.warning("submit life decision to director err: %s", e)
            # 兜底：直接写状态（避免角色卡死）—— 但**不**创建活动实例（未真正执行）
            st.life.activity = d.activity
            st.life.macro = _macro_for(d.activity)
        # 计划时长（供 Frame/显示诊断；实例状态由 on_mind_action_started 负责）
        self._current_activity_duration = max(float(getattr(d, "duration", 0.0) or 0.0), 1.0)
        self._life_next_think = max(15.0, d.next_think_in)

        # H1-FINAL §3：自主台词**不在决策提交时启动** —— 移到 Director 实际执行边界
        # （app._on_execute → sched.start_autonomous_dialogue）。被阻塞/未执行的 mind 请求
        # 不得产出台词、不得开 social bid。
        # 需要操作电脑 → 交给 Tool Agent（三脑：手）
        if d.tool_needed:
            log.info("life decision requested tool, but tool task needs explicit user goal; 交给用户或在 Agent 菜单触发")

    def start_autonomous_dialogue(self, *, activity: str, speech_level: int = 0,
                                  speech_intent: str = "", dialogue_needed: bool = False,
                                  emotion: str = "", duration: float = 0.0,
                                  intent: str = "") -> None:
        """H1-FINAL §3：**Director 实际执行 mind 动作后**才启动自主台词（owner 线程）。

        owner：节流检查 + 冻结快照 → worker：DialogueBrain.say → owner：应用台词/开 social bid。
        被阻塞/从未执行的 mind 请求不会走到这里（无台词、无 bid）。
        """
        if self.dialogue_brain is None:
            return
        try:
            last = getattr(self, "_llm_speech_at", 0.0)
            now = time.monotonic()
            speech_level = int(speech_level or 0)
            # 节流：自主/状态触发的说话必须 >= 35s 一次，否则会刷屏（每次决策都说同一句）。
            # 只有高 speech_level(>=3 深聊) 或明确 dialogue_needed 且过了 15s 才放行。
            min_gap = 15.0 if (speech_level >= 3 or (dialogue_needed and speech_level >= 2)) else 35.0
            if (now - last) < min_gap:
                return
            voiced = activity in SPEAKABLE_ACTIVITIES
            if not (dialogue_needed or speech_level >= 1 or voiced):
                return
            snap = self._freeze_ambient_snapshot(activity=activity, speech_intent=speech_intent,
                                                 emotion=emotion, intent=intent or activity)
            dur = min(6.0, duration) if duration else 4.0
            social = activity in self._SOCIAL_BID_KINDS
            def _ambient_work(snapshot, _dur, _social):
                try:
                    speech = self.dialogue_brain.say(**snapshot.say_kwargs())
                    if speech:
                        # 结果经 dispatcher 在 owner 线程应用（worker 不直改 _speech）
                        self._enqueue_apply(lambda sp=speech, dd=_dur: (
                            self._say(sp, dur=dd),
                            setattr(self, "_llm_speech_at", time.monotonic()),
                            setattr(self, "_last_speech_at", time.monotonic())))
                        # H1 §7：社交类**可见台词成功出话**后才开响应窗口（owner 线程）
                        if _social:
                            self._enqueue_apply(lambda: self.begin_social_bid(
                                reason=f"spoken:{snapshot.activity}"))
                except Exception:
                    pass
            import threading
            threading.Thread(target=_ambient_work, args=(snap, dur, social), daemon=True).start()
        except Exception as e:  # pragma: no cover
            log.warning("autonomous dialogue err: %s", e)

    def _freeze_ambient_snapshot(self, *, activity: str, speech_intent: str = "",
                                 emotion: str = "", intent: str = ""):
        """H1 §10：owner 冻结自主环境台词快照（只读事实副本，不引用 live 对象）。"""
        from furina.runtime.dialogue_snapshot import DialogueContextSnapshot, freeze_flat
        st = self.se.state
        mems = [m.content for m in self.me.retrieve(query=intent or activity, limit=3)] if self.me else []
        wf = {}
        try:
            wf = self.world_perc.factors()
        except Exception:
            pass
        wctx = ""
        try:
            ua = getattr(self.world_perc.state, "user_activity", None)
            wctx = ua.value if hasattr(ua, "value") else (ua or "")
        except Exception:
            pass
        minterp = {}
        try:
            mems_ctx = self.me.retrieve(query="", limit=3, context=wctx or None) if self.me else []
            minterp = self.me.interpret(mems_ctx, context=wctx or "")
        except Exception:
            pass
        return DialogueContextSnapshot(
            intent=intent or activity,
            emotion_label=emotion,
            context=speech_intent or intent or activity,
            activity=activity,
            channel="AMBIENT_AUTONOMOUS",   # FINAL-R1 §4.2：自主台词不进直接对话历史
            memories=tuple(mems),
            world=freeze_flat({**wf, "user_activity": wctx, "recent_events": list(self._recent_events)}),
            relationship=freeze_flat(self._rel_factors()),
            memory_interp=freeze_flat(minterp),
            solitude=bool(st.user_idle_seconds > 300),
            user_present=bool(st.user_idle_seconds < 300),
        )

    # -------------------------------------------------- FINAL-R1 §5：Director 实际执行时才启动实例
    def on_mind_action_started(self, activity: str, planned_duration: float = 0.0) -> None:
        """Director 执行器确认 `source=mind` 动作**真正开始**时调用（owner 线程）。

        此刻才：创建 ActivityInstance（RUNNING）、更新 _current_life_activity、
        记录 recency（mark_done）—— 被阻塞/从未执行的 mind 请求不会走到这里。
        """
        self.require_owner("mind_action_started")
        self._activity_instance = {
            "activity": activity,
            "started_at": time.time(),
            "planned_duration": max(float(planned_duration or 0.0), 1.0),
            "instance_id": f"{activity}-{time.time_ns() % 10 ** 8}",
            "status": "RUNNING", "elapsed": 0.0, "progress": 0.0,
            "finish_reason": None, "source": "mind",
        }
        self._current_life_activity = activity
        # 只有实际开始的活动才更新 recency/history（§5 mark_done 时机）
        if self.motivation is not None:
            try:
                self.motivation.mark_done(activity, time.monotonic())
            except Exception:
                pass
        # H1 §7：社交响应窗口只在**可见执行**时开启。
        # - approach_user：走过去本身可见 → 执行即开 bid；
        # - 其它社交类（talk/greet/invite/…）：等**可见台词成功出话**后再开（ambient worker 提交），
        #   无效/被抑制的台词不开启；被阻塞的决策根本不会到这里。
        if activity == "approach_user":
            try:
                self.begin_social_bid(reason=f"executed:{activity}")
            except Exception:
                pass

    def on_user_takeover(self) -> None:
        """H1-FINAL §4：真实定型互动（click/petting/poke/drag）→ 用户抢占：
        finalize 运行中的 mind 实例（elapsed 停在互动时刻、部分奖励一次）+ 释放 Director mind 所有权。
        指针控制阶段（grab/release/hover/leave）**不**经此路径（不抢占）。
        """
        self.require_owner("user_takeover")
        self.on_mind_preempted(reason="preempted_by_user")
        try:
            self.director.finish(source="mind")
        except Exception:
            pass

    def on_mind_preempted(self, reason: str = "interrupted") -> None:
        """H1 §8：**实际抢占发生时**立即 finalize 运行中的 mind 实例（owner 线程）。

        Director 通过 on_before_replace 在接管瞬间调用：
          - elapsed 停在抢占时刻（之后 Agent/用户时间**不计入** mind 活动）；
          - progress 按当时计算；status → INTERRUPTED/ABORTED；
          - 部分奖励恰好一次（success=False + progress 感知）；
          - 之后的 Life 决策结算会跳过（实例已非 RUNNING），不会把抢占后时间算作 mind 时间。
        """
        self.require_owner("mind_preempt")
        inst = getattr(self, "_activity_instance", None)
        if inst is None or inst.get("source") != "mind" or inst.get("status") != "RUNNING":
            return   # 无运行中的 mind 实例 → 无操作
        now = time.time()
        elapsed = max(0.0, now - float(inst.get("started_at", now)))
        planned = float(inst.get("planned_duration", 0.0) or 1.0)
        progress = min(1.0, elapsed / planned) if planned > 0 else 1.0
        # H1-FINAL §5：**status 必须是规范集** {RUNNING,COMPLETED,INTERRUPTED,ABORTED,FAILED}；
        # preempted_by_* / user_cancel / shutdown 等是 finish_reason，绝不写进 status。
        status = self._canonical_status(reason)
        inst.update({"status": status, "elapsed": round(elapsed, 1),
                     "progress": round(progress, 2), "finish_reason": reason})
        self._last_activity_finish = {
            "activity": inst["activity"], "reason": reason, "status": status,
            "elapsed": round(elapsed, 1), "planned_duration": round(planned, 1),
            "progress": round(progress, 2),
        }
        self._apply_activity_outcome(inst["activity"], success=False, reason=reason, progress=progress)

    @staticmethod
    def _canonical_status(reason: str) -> str:
        """H1-FINAL §5：finish reason → 规范生命周期状态（任意 reason 不得直接进 status）。"""
        if reason == "completed":
            return "COMPLETED"
        if reason in ("aborted", "user_cancel") or reason.startswith("user_cancel") or reason == "shutdown":
            return "ABORTED"
        if reason == "failed" or reason.startswith("tool") or reason.startswith("runtime"):
            return "FAILED"
        return "INTERRUPTED"   # interrupted / preempted_by_agent / preempted_by_user / ...

    # -------------------------------------------------- 经历→状态反馈（Life Simulation 闭环）
    def _apply_activity_outcome(self, activity: str, success: bool = True,
                                reason: str = "completed", progress: float = 1.0) -> None:
        """上一个生活行为结束 → 因果结算其"后果"（needs/emotion）。

        用 Activity Outcome 模型（`furina.behavior.outcome`）做**因果反馈**，
        不是行为选择规则 —— 反馈后状态变了，下一行为仍由 Motivation 决定。
        FINAL-R1 §5：**进度感知奖励** —— interrupted 收益随真实进度缩放（10% < 70% < 完成），
        不再固定减半（0.5）。
        """
        try:
            from furina.behavior.outcome import apply_outcome
            # 连续做同一种活动的次数（diminishing returns 用）：从 motivation.activity_history 数
            recent_counts = {}
            if self.motivation is not None:
                for a in getattr(self.motivation, "_activity_history", []):
                    recent_counts[a] = recent_counts.get(a, 0) + 1
            o = apply_outcome(self.se.state, activity, self.emotion,
                              success=success, progress=progress,
                              relationship=getattr(self.me, "relationship", None),
                              recent_counts=recent_counts)
            # 结局（reason/elapsed/planned/progress/status）已由结算点记录到 _last_activity_finish；
            # 这里兜底记录 reason（活动被外部直接结算时也有迹可循），并保留 status 键（H1-FINAL §5）
            fin = getattr(self, "_last_activity_finish", None)
            self._last_activity_finish = {
                "activity": activity, "reason": reason,
                "status": fin.get("status", self._canonical_status(reason)) if isinstance(fin, dict) else self._canonical_status(reason),
                "progress": round(progress, 2),
                "elapsed": fin.get("elapsed", 0.0) if isinstance(fin, dict) else 0.0,
                "planned_duration": fin.get("planned_duration", 0.0) if isinstance(fin, dict) else 0.0,
            }
            log.debug("outcome '%s' success=%s reason=%s progress=%.2f: needs=%s emotion=%s",
                      activity, success, reason, progress, o.needs, o.emotion)
        except Exception as e:  # pragma: no cover
            log.warning("apply activity outcome err: %s", e)

    # -------------------------------------------------- 硬性反塌缩（任务 §18）
    def _anti_collapse(self, d) -> "LifeDecision":
        """确定性保证行为多样：同一类别连续 ≥3 次时，强制换成其它类别的候选。

        Brain 即使塌缩成 explore/observe 之类单点，这里也保证 SELF/SOCIAL/OBSERVATION/
        ASSISTANCE 不会一枝独秀。这是**硬约束**（任务 §18 允许 read/sleep/rest 合理持续除外）。
        """
        try:
            from furina.behavior.motivation import CATEGORY
            st = self.se.state
            cat = CATEGORY.get(d.activity, "SELF")
            if cat in ("NEED",):
                return d   # 生存行为（sleep/eat）不受多样性打断
            # 最近类别序列（从 motivation 里取）
            hist = getattr(self.motivation, "_category_history", []) or []
            run = 0
            for c in reversed(hist):
                if c == cat:
                    run += 1
                else:
                    break
            if run + 1 < 3:   # 这次是第 2 次连续同一类 → 还没到硬限制
                return d
            # 达到硬限制 → 从其它类别里挑一个候选回退
            if self.motivation is not None:
                cands = self.motivation.candidates(st, self.emotion)
                other = [c for c in cands if CATEGORY.get(c.activity, "SELF") != cat and c.activity != "idle"]
                if other:
                    from furina.life_brain import LifeDecision
                    pick = other[0]
                    log.info("anti-collapse: 同名类别 %s 连击 %d -> 换 %s", cat, run + 1, pick.activity)
                    return LifeDecision(activity=pick.activity, emotion=d.emotion,
                                        intent=d.intent or pick.activity,
                                        duration=d.duration, interruptible=d.interruptible,
                                        exit_conditions=d.exit_conditions,
                                        next_think_in=d.next_think_in,
                                        dialogue_needed=d.dialogue_needed, tool_needed=d.tool_needed,
                                        reason=f"反塌缩:{cat}→{pick.activity}",
                                        raw=getattr(d, "raw", {}))
        except Exception:
            pass
        return d

    # -------------------------------------------------- 唤醒监听：重要事件 → 立即重决策
    def _interrupt_life(self, reason: str) -> None:
        self._recent_events.append(reason)
        self._life_interrupt_pending = True

    def interrupt_life(self, reason: str) -> None:
        """供 app 等外部调用的公开唤醒入口（喂食/用户请求等 → LifeBrain 立即重决策）。"""
        self._interrupt_life(reason)

    def on_user_reject(self) -> None:
        """用户明确拒绝互动（“别烦我”）→ 真实状态变化：
        接纳度↓、拒绝统计↑、未来一段时间收敛主动行为（§13）。"""
        if self.relationship is not None:
            try:
                from furina.relationship.engine import EV_REJECT, EV_IGNORE
                # C-R2 §6：EV_REJECT 已同步更新 rejection_count + user_rejection_rate + annoyance；
                # Scheduler **不再**手动 bump 同一批字段（避免双写）+ 只持久化一次。
                self.relationship.apply(EV_REJECT)
                self.se.state.relationship = self.relationship.state
                if self.me is not None:
                    self.me.store.save_relationship(self.relationship.state)
            except Exception:
                pass
        # §4.4/FINAL-R1 §2.2：拒绝 → EVENT_REJECT，apply + 立即派生（owner 线程）
        try:
            from furina.emotion import EVENT_REJECT
            self.emotion.apply_event(EVENT_REJECT, tired_hint=self._tired_hint())
        except Exception:
            pass
        if self.life_brain is not None and hasattr(self.life_brain, "adapt_tolerance"):
            try:
                self.life_brain.adapt_tolerance(user_responded=False, was_interactive=True)
            except Exception:
                pass
        self._interrupt_life("user_rejected")

    def on_user_ignore(self) -> None:
        """语义忽略（Phase 13 终审 §7）：**不是指针离开**。
        对应"芙宁娜主动发起了互动/存在，用户在一段响应窗口内没有回应"。
        恰好一次路由到：Emotion EVENT_IGNORE + Relationship EV_IGNORE + Life 容忍度 + 记忆。
        """
        # 关系（EV_IGNORE 经 RelationshipEngine 唯一写入口）
        if self.relationship is not None:
            try:
                from furina.relationship.engine import EV_IGNORE
                self.relationship.apply(EV_IGNORE)
                self.se.state.relationship = self.relationship.state
                if self.me is not None:
                    self.me.store.save_relationship(self.relationship.state)
            except Exception:
                pass
        # 情绪（EmotionEngine 唯一 owner，§2.2 立即派生）
        try:
            from furina.emotion import EVENT_IGNORE
            self.emotion.apply_event(EVENT_IGNORE, tired_hint=self._tired_hint())
        except Exception:
            pass
        # Life：用户没回应 → 主动社交收敛
        if self.life_brain is not None and hasattr(self.life_brain, "adapt_tolerance"):
            try:
                self.life_brain.adapt_tolerance(user_responded=False, was_interactive=False)
            except Exception:
                pass
        # 记忆（有意义才记）
        try:
            self._consolidate_episode(event_type="user_ignore", activity="")
        except Exception:
            pass
        self._interrupt_life("user_ignored")

    # -------------------------------------------------- FINAL-R1 §7：社交响应窗口（真实 ignore 探测器）
    _SOCIAL_BID_KINDS = ("talk", "approach_user", "greet", "invite_user", "seek_attention",
                         "ask_user", "comfort")

    def begin_social_bid(self, reason: str = "initiated") -> None:
        """芙宁娜发起**合格的直接社交尝试** → 开启响应窗口（pending token + deadline）。

        不合格（不开启）：自主自说自话（AMBIENT）、非社交环境台词、指针离开、
        用户从一开始就缺席、Agent/系统状态台词。
        """
        if getattr(self, "_pending_social_bid", None) is not None:
            return   # 已有 pending，不重复
        if self.se.state.user_idle_seconds >= 300:
            return   # 用户缺席从起点就不开窗口（不制造假 ignore）
        self._pending_social_bid = {
            "token": f"bid-{time.time_ns() % 10 ** 8}",
            "deadline": time.time() + self._social_bid_window,
            "reason": reason,
        }

    def on_user_response(self) -> None:
        """真实用户回应（点击/摸头/对话/喂食/拒绝等）→ 取消 pending（不产生 ignore）。"""
        self._pending_social_bid = None

    def _tick_social_bid(self, now: Optional[float] = None) -> None:
        """响应窗口到期且无回应 → 语义 USER_IGNORE **恰好一次**（owner 线程，medium tick 调用）。"""
        bid = getattr(self, "_pending_social_bid", None)
        if bid is None:
            return
        if (now if now is not None else time.time()) >= bid["deadline"]:
            self._pending_social_bid = None
            self.on_user_ignore()

    # -------------------------------------------------- M4：走向活动窗口（陪伴）—— DEPRECATED
    def _maybe_walk_to_window(self) -> None:
        """⚠️ DEPRECATED（Phase 12 Spatial Ownership Migration）。

        像素空间移动已由 ``DesktopSpatialRuntime`` 接管；Scheduler 不再自行决定目标坐标、
        不调用 ``window.set_position``、也不再直接 ``life.macro = RESTING``。
        到达位置≠决定休息（那是 LifeBrain 职责）。生产调用计数 = 0。
        """
        import warnings
        warnings.warn("Scheduler._maybe_walk_to_window is deprecated; spatial movement owned by "
                      "DesktopSpatialRuntime.", DeprecationWarning, stacklevel=2)
        return None

    # -------------------------------------------------- slow tick
    def _tick_slow(self, dt: float) -> None:
        # 骨架：偷懒的“夜间巩固”心跳，仅记录
        log.debug("slow tick: relationship=%s", self.me.relationship.as_dict())

    # -------------------------------------------------- 场景驱动（骨架：简单姿态）
    def _rel_factors(self) -> dict:
        """C-R1.2：关系归一化 0..1 consumer 契约（Dialogue/Embodiment 一律用 factors()，不混 0-100/0-1）。"""
        try:
            if self.relationship is not None and hasattr(self.relationship, "factors"):
                return self.relationship.factors()
            mrel = getattr(getattr(self, "me", None), "relationship", None)
            if mrel is not None:
                from furina.relationship.engine import RelationshipEngine
                return RelationshipEngine(mrel).factors()
        except Exception:
            pass
        return {}

    def _tired_hint(self) -> float:
        """真实困倦信号 0..1（sleepiness+fatigue），供情绪派生（sleepy 只允许真实困倦触发）。"""
        try:
            n = self.se.state.needs
            return max(0.0, min(1.0, (float(n.sleepiness) + float(n.fatigue)) / 200.0))
        except Exception:
            return 0.0

    def _say(self, text: str, dur: float = 4.0) -> None:
        """立即显示一句台词（带显示时长，不刷屏）。"""
        if text:
            self._speech = text
            self._speech_until = time.monotonic() + dur

    def _speak_via_dialogue(self, *, intent: str, emotion: str, user_initiated: bool,
                            context: str, activity: str, interaction: str = "") -> None:
        """FIX G：把高频互动/系统事件台词交给 DialogueBrain（背景线程，不阻塞 UI）。

        唯一语言源 = DialogueBrain → Frame.speech。DialogueBrain 失败/无 LLM → 沉默（§9），
        不回退固定句池。仅 Agent fail 的确定性错误事实显示为 SYSTEM_STATUS（非角色人格化）。
        H1 §10：**owner 线程冻结 DialogueContextSnapshot**（互动/Agent 报告通道），worker 只读快照。
        """
        if self.dialogue_brain is None:
            return
        snap = self._freeze_reaction_snapshot(intent=intent, emotion=emotion,
                                              user_initiated=user_initiated, context=context,
                                              activity=activity, interaction=interaction)
        def _work(snapshot):
            try:
                speech = self.dialogue_brain.say(**snapshot.say_kwargs())
                if speech:
                    # §8：对话结果经 apply 队列在 owner 线程落地（worker 线程不直接改 _speech）
                    self._enqueue_apply(lambda sp=speech: (self._say(sp, dur=3.0),
                                                           setattr(self, "_last_speech_at", time.monotonic())))
            except Exception:
                pass
        import threading
        threading.Thread(target=_work, args=(snap,), daemon=True).start()

    def _freeze_reaction_snapshot(self, *, intent: str, emotion: str, user_initiated: bool,
                                  context: str, activity: str, interaction: str = ""):
        """H1 §10：owner 冻结互动/Agent 报告通道的对话快照（只读事实副本）。"""
        from furina.runtime.dialogue_snapshot import DialogueContextSnapshot, freeze_flat
        wf = {}
        try:
            wf = self.world_perc.factors() if self.world_perc is not None else {}
        except Exception:
            pass
        mem_objs = self.me.retrieve(query=activity, limit=3) if self.me else []
        mems = [m.content for m in mem_objs]
        rel = {}
        try:
            rel = self.relationship.factors() if self.relationship is not None else {}
        except Exception:
            rel = {}
        minterp = {}
        try:
            if mem_objs:
                minterp = self.me.interpret(mem_objs, context=context)
        except Exception:
            pass
        idle = float(getattr(self.se.state, "user_idle_seconds", 0))
        return DialogueContextSnapshot(
            intent=intent,
            emotion_label=emotion,
            context=context,
            activity=activity,
            user_initiated=user_initiated,
            task_mode=bool(interaction == "agent"),
            user_present=idle < 300,
            solitude=idle > 300,
            channel="AGENT_REPORT" if interaction == "agent" else "INTERACTION_REACTION",
            memories=tuple(mems),
            world=freeze_flat(wf),
            relationship=freeze_flat(rel),
            memory_interp=freeze_flat(minterp),
        )

    def body_snapshot(self) -> Optional[dict]:
        """⚠️ DEPRECATED（Phase 10.5 S4）—— 已收敛到 CharacterRuntimeFrame.body。

        现在只是 `current_frame().body` 的只读别名；Phase 11 前端**禁止**使用。
        正式唯一前端接口 = `current_frame()`。
        """
        import warnings
        warnings.warn(
            "Scheduler.body_snapshot is deprecated; use current_frame()['body'] "
            "as the single runtime contract.", DeprecationWarning, stacklevel=2)
        frame = getattr(self, "_last_frame", None)
        if frame is not None:
            b = frame.body
            return {"expression": b.expression, "gaze": b.gaze, "posture": b.posture,
                    "body_openness": b.body_openness, "movement_tempo": b.movement_tempo,
                    "movement_amplitude": b.movement_amplitude, "hesitation": b.hesitation,
                    "composure": b.composure, "micro_motion": list(b.micro_preferences),
                    "transition_style": b.transition_style}
        body = getattr(self, "_last_body", None)
        return body.to_dict() if body is not None else None

    def current_frame(self) -> Optional[dict]:
        """最近发布的 CharacterRuntimeFrame（唯一前端契约）。"""
        f = getattr(self, "_last_frame", None)
        return f.to_dict(debug=bool(getattr(self, "wa", None) and getattr(self.wa, "show_debug", False))) if f else None

    def _update_scene(self) -> None:
        state = self.se.state
        activity = state.life.activity or state.intent.action or "idle"

        # 台词：过期的清除；否则显示当前（行为/互动触发）
        if time.monotonic() >= self._speech_until:
            self._speech = ""
        # 注意：无 DialogueBrain 就不产生自主台词（不覆盖 DialogueBrain）；彻底无硬编码台词池。
        speech = self._speech
        silence = not speech

        # ------- BodyExpressionState（Phase 09）：语义身体层 -------
        body = None
        body_snap = {}
        if self.embodiment is not None:
            try:
                rel = {}
                if self.relationship is not None and hasattr(self.relationship, "state"):
                    rel = self._rel_factors()   # C-R1.2 归一化（Embodiment 关系消费者）
                elif self.me is not None and getattr(self.me, "relationship", None) is not None:
                    rel = getattr(self.me.relationship, "as_dict", lambda: {})()
                mode = "CASUAL"
                dialogue_act = "COMMENT"
                try:
                    if self.dialogue_brain is not None and hasattr(self.dialogue_brain, "expression"):
                        app = self.dialogue_brain.expression.appraise(
                            emotion=state.emotion.label or "calm", intent=state.intent.action or "",
                            relationship=rel,
                            world=self.world_perc.factors(),
                            activity=activity,
                            solitude=bool(state.user_idle_seconds > 300),
                            user_present=bool(state.user_idle_seconds < 300),
                            user_working=bool(state.user_working))
                        mode = getattr(app, "mode", "CASUAL")
                        dialogue_act = getattr(app, "dialogue_act", "COMMENT")
                except Exception:
                    pass
                body = self.embodiment.express(
                    emotion=state.emotion.label or "calm",
                    mode=mode, dialogue_act=dialogue_act,
                    relationship=rel, activity=activity,
                    world=self.world_perc.factors(),
                    fatigue=getattr(state.needs, "fatigue", 20.0),
                    needs={k: getattr(state.needs, k) for k in state.needs.__dataclass_fields__},
                    user_present=bool(state.user_idle_seconds < 300),
                    user_working=bool(state.user_working),
                    silence=silence,
                )
                from furina.embodiment import BodyValidator
                body = BodyValidator().validate(body, activity=activity,
                                                fatigue=float(getattr(state.needs, "fatigue", 20.0)),
                                                silence=silence)
                self._last_body = body
                body_snap = body.to_dict()
            except Exception:  # pragma: no cover — 具身失败绝不拖垮主循环
                self._last_body = None

        # ------- 唯一 CharacterRuntimeFrame（Phase 10）-------
        f = self.frame_builder.build(
            state=state,
            activity_name=activity,
            activity_started_at=self._current_activity_started_at if hasattr(self, "_current_activity_started_at") else 0.0,
            activity_phase="LOOP",
            activity_target=state.intent.action or "",
            activity_interruptible=True,
            speech={
                "should_speak": not silence, "text": speech,
                "dialogue_act": (self.dialogue_brain.expression.appraise(
                    emotion=state.emotion.label or "calm", intent=state.intent.action or "",
                    relationship=self._rel_factors(),   # C-R1.2 归一化
                    world=self.world_perc.factors(), activity=activity,
                    solitude=bool(state.user_idle_seconds > 300),
                    user_present=bool(state.user_idle_seconds < 300),
                    user_working=bool(state.user_working)).dialogue_act
                    if self.dialogue_brain is not None and hasattr(self.dialogue_brain, "expression") else "COMMENT"),
                "mode": (self.dialogue_brain.expression.appraise(
                    emotion=state.emotion.label or "calm",
                    activity=activity, relationship=self._rel_factors(),   # C-R1.2 归一化
                    world=self.world_perc.factors(),
                    solitude=bool(state.user_idle_seconds > 300),
                    user_present=bool(state.user_idle_seconds < 300),
                    user_working=bool(state.user_working)).mode
                    if self.dialogue_brain is not None and hasattr(self.dialogue_brain, "expression") else "CASUAL"),
                "initiative": 0.5 if not silence else 0.0,
                "validation_status": "valid" if (speech and self.dialogue_brain is not None
                                                 and hasattr(self.dialogue_brain, "validator")
                                                 and self.dialogue_brain.validator.validate(speech, should_speak=True).valid) else ("silent" if silence else "invalid"),
            },
            body=body,
            world=self.world_perc,
            debug={
                "activity_reason": state.life.reason or "",
                "persona_mode": getattr(body, "posture", ""),
                "body_reasons": list(getattr(body, "reasons", []) or []),
                "needs": {k: getattr(state.needs, k) for k in state.needs.__dataclass_fields__},
                "world_summary": f"{getattr(self.world_perc.state, 'user_activity', '')}@{getattr(self.world_perc.state, 'day_period', '')}",
            },
            debug_enabled=self.wa.show_debug if hasattr(self.wa, "show_debug") else False,
        )
        # 语义变化才发布（§15 分层），低频节流
        now = time.monotonic()
        if now - self._last_frame_built_at >= self._frame_publish_interval:
            self._last_frame = f
            self._last_frame_built_at = now
            try:
                from furina.core import EventType
                self.bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=f, source="runtime")
            except Exception:
                pass

        # ------- 旧 Renderer 只通过 Adapter 消费 Frame（收敛双轨）-------
        # Phase 11 Step 0.3：Scheduler 不再拥有 set_pose_semantics / set_render_state /
        # renderer_adapter->window 直写。只发布 CHARACTER_FRAME_UPDATED，
        # 由 FrontendFrameConsumer 做 visual diff → 驱动 Window。
        # 此处仅保留 debug 字符串（供 consumer 从 frame 派生 debug 显示）：
        debug = (f"Life:{state.life.activity}({state.life.macro.value})\n"
                 f"Body:{getattr(body,'expression','')}/{getattr(body,'gaze','')}/{getattr(body,'posture','')}\n"
                 f"  hes:{getattr(body,'hesitation',0):.2f} comp:{getattr(body,'composure',0):.2f} "
                 f"amp:{getattr(body,'movement_amplitude',0):.2f} {getattr(body,'movement_tempo','')} "
                 f"micro:{'/'.join(getattr(body,'micro_motion',[]))}\n"
                 f"Mood:{state.emotion.mood:.0f}")
        self._last_debug = debug
