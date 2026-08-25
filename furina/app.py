"""应用总装（App Wiring）。

骨架阶段：
- 组装各子系统与 EventBus，注册最小行为集。
- Director 作为唯一动作仲裁（legacy-plan/8 §3）；Agent 与行为共享 BehaviorEngine。
- 无真实素材时用占位图渲染，保证可运行、可看生命循环。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from furina.config import AppConfig, load_config
from furina.core import EventBus, EventType, setup_logging, get_logger
from furina.state import StateEngine, MacroState, AttentionTarget
from furina.behavior import BehaviorEngine, BehaviorDefinition
from furina.interaction import InteractionEngine
from furina.assets.asset_manifest import AssetEntry, AssetManifest, AssetQuery
from furina.memory import MemoryEngine, MemoryStore, MemoryLevel, MemorySource
from furina.director import Director
from furina.agent import ToolRegistry, PermissionManager, AgentRuntime
from furina.agent.tools import ALL_TOOLS
from furina.life_brain import LifeBrain
from furina.dialogue_brain import DialogueBrain
from furina.llm import get_adapter
from furina.runtime import (
    DesktopWorld,
    AssetManager,
    FurinaWindow,
    WindowAwareness,
)
from furina.runtime.scheduler import Scheduler

log = get_logger("app")

# R2.2.1 FINAL §2：recent activity 可视为"刚才"的最大秒数（明确常量，随快照冻结）。
# 超过此秒数的 recent activity 不得用"刚才"表述（stale → 不冒充）。
RECENT_ACTIVITY_FRESHNESS_SECONDS = 120.0


class Furina:
    """聚合根：持有所有子系统。"""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.bus = EventBus()

        # 记忆
        self.mem_store = MemoryStore(cfg.db_path)
        self.memory = MemoryEngine(self.bus, self.mem_store)

        # 关系引擎（Phase 04：关系演化 + 恢复 + 反哺 Motivation）
        from furina.relationship import RelationshipEngine
        self.relationship = RelationshipEngine(self.memory.relationship)

        # 状态 / 行为 / 互动
        self.state = StateEngine(self.bus)
        self.behavior = BehaviorEngine(self.bus)
        self.interaction = InteractionEngine(self.bus)
        self._register_behaviors()

        # 情感引擎（Life Simulation P2：确定性，不用 LLM）—— 事件 → 情绪 → 行为倾向
        from furina.emotion import EmotionEngine, EVENT_PET, EVENT_POKE, EVENT_CLICK, EVENT_DRAG
        from furina.behavior import BehaviorMotivation, Personality
        self.emotion = EmotionEngine(self.state.state.emotion)
        # 人格（来自 persona 配置，确定性，不用 LLM）→ 真正进入 Motivation（Personality→Motivation→候选→Brain）
        import furina.persona.furina_persona as _fp
        _pp = getattr(_fp, "FURINA_BEHAVIOR_PERSONALITY", None) or {}
        self.personality = Personality(
            self_activity_preference=_pp.get("self_activity_preference", 0.5),
            social_activity_preference=_pp.get("social_activity_preference", 0.5),
            exploration_preference=_pp.get("exploration_preference", 0.5),
            play_preference=_pp.get("play_preference", 0.5),
            helpfulness=_pp.get("helpfulness", 0.5),
            curiosity=_pp.get("curiosity", 0.5),
            attention_seeking=_pp.get("attention_seeking", 0.4),
            independence=_pp.get("independence", 0.5),
        )
        # Character Identity（Phase 05：结构化身份，≠ Behavioral Personality / Emotion / Relationship）
        from furina.persona.character_identity import FURINA_IDENTITY as furina_character_identity
        self.motivation = BehaviorMotivation(personality=self.personality,
                                             identity=furina_character_identity,
                                             memory_engine=self.memory)

        # 具身表达（Phase 09：语义身体层，确定性，0 LLM）—— 消费 Frozen 的 Dialogue Persona 与状态，
        # 只输出 semantic body intents，不生成素材 / 不实现 Walk / 不碰 renderer。
        from furina.embodiment import EmbodiedExpressionEngine, BodyValidator, FURINA_EMBODIMENT
        self.embodiment = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
        self.body_validator = BodyValidator()

        # 互动事件 → 情绪（确定性映射，不用 LLM）。
        # H1-FINAL §1：**唯一 owner = InteractionEngine.on_emotion_semantic 预广播钩子**
        # （在 _apply() 里于 INTERACTION_INPUT 广播前调用，见 interaction_engine._apply）。
        # **不再**注册 EventBus INTERACTION_INPUT → _on_interaction_emotion 订阅 —— 否则一次语义事件
        # 会经钩子 + 广播订阅各 apply 一次（双重情绪）。
        # （订阅在下方「纵向集成」区：self.interaction.on_emotion_semantic = self._on_interaction_emotion）

        # Director（唯一仲裁）
        self.director = Director(self.bus)

        # Agent
        self.tools = ToolRegistry()
        for tool_cls in ALL_TOOLS:
            self.tools.register(tool_cls())  # type: ignore[arg-type]
        self.permission = PermissionManager()
        # 用户主动在右键菜单里点的“随手帮忙”任务 → 视为用户已授权（legacy-plan/5 §20），
        # 角色化确认由 confirm 回调表现（弹台词），并放行 L2/L3。
        self.permission.on_confirm = self._confirm_agent_permission
        self.agent = AgentRuntime(self.bus, self.tools, self.permission)
        # Phase 14K：认知层总装（CognitionHub；连接现有 Memory/Relationship + Canon adapters +
        # UserModel/EventTimeline/AgentTaskHistory + ContextAssembler）。
        self.cognition = None
        try:
            from furina.cognition import CognitionHub
            self.cognition = CognitionHub(cfg.db_path, memory_engine=self.memory,
                                          relationship_engine=self.relationship)
            # Phase 14I：Agent worker 产出结构化 task_record → dispatcher 回 owner → C7 persist
            self.agent.on_task_finished = lambda rec: self._rt_dispatcher().submit(
                lambda: self._persist_agent_task(rec))
        except Exception as e:
            log.warning("cognition 初始化失败（不影响既有运行）: %s", e)
            self.cognition = None

        # 三脑架构（legacy-plan/8 修正）：LifeBrain 状态决策 + DialogueBrain 语言 + ToolAgent 双手。
        # 用配置的 provider（默认 zhipu glm-4v-flash；.env 可切 openai_compat 更快模型）。
        self.life_brain = None
        self.dialogue_brain = None
        try:
            llm = get_adapter(cfg.llm.provider)(cfg.llm)
            self.life_brain = LifeBrain(llm, self.memory, identity=furina_character_identity)
            self.dialogue_brain = DialogueBrain(llm, identity=furina_character_identity)
        except Exception as e:
            log.warning("大脑初始化失败，对话/状态决策不可用: %s", e)
            self.life_brain = None
            self.dialogue_brain = None

        # 世界 / 素材
        self.world = DesktopWorld(1920, 1080)   # 启动后用真实屏幕重设
        self.assets = AssetManager(AssetManifest(), cfg.assets_dir)
        self._load_assets()

        # 窗口感知
        self.wa = WindowAwareness(lambda info: self.bus.emit(
            EventType.ACTIVE_WINDOW_UPDATED, payload=info, source="runtime"))

        # Director executor：把仲裁动作路由到表现/状态（仅 Director 能调用）
        self.director.set_executor(self._on_execute)
        # H1 §8：实际抢占回调 —— 高优先级请求接管当前动作时，立即 finalize 被抢占的 mind 实例
        self.director.on_before_replace = self._on_director_replace

        # 纵向集成：互动→记忆/关系；Agent→角色身体同步（保持模块边界）。
        # H1 §9：Emotion 语义钩子（先于广播完成情绪效果）；H1-FINAL §4：用户抢占钩子
        self.interaction.on_emotion_semantic = self._on_interaction_emotion
        self.interaction.on_user_takeover = self._on_user_takeover_interaction
        self.interaction.on_meaningful_interaction = self._on_meaningful_interaction
        self.agent.on_body_sync = self._on_agent_body
        # 互动 hitbox：由素材锚点定义（legacy-plan/4 §5），否则摸头/拖拽/点击都无法识别
        self.interaction.set_hitboxes_from_anchor(
            {"head": [0.5, 0.18], "body": [0.5, 0.52], "hand": [0.72, 0.45],
             "foot": [0.5, 0.9], "item": [0.5, 0.7]},
            (0.5, 0.5, 0.42, 0.46))

    # -------------------------------------------------- FINAL-R1 §2.2/§2.4：互动 → 情绪语义
    def _on_interaction_emotion(self, ev) -> None:
        """INTERACTION_INPUT → 显式语义情绪事件（无映射 → 不调用 EmotionEngine）。

        接受两种输入：bus 包装（ev.payload=InteractionEvent）或 InteractionEngine 钩子直传的
        原始 InteractionEvent（H1 §9：on_emotion_semantic 在广播前调用）。
        """
        payload = getattr(ev, "payload", None)
        event = payload if payload is not None else ev
        if event is None:
            return None
        from furina.emotion import EVENT_PET, EVENT_POKE, EVENT_CLICK, EVENT_DRAG
        _map = {"petting": EVENT_PET, "poke": EVENT_POKE,
                "click": EVENT_CLICK, "drag": EVENT_DRAG}
        kind = getattr(getattr(event, "type", None), "value", "")
        mapped = _map.get(kind, None)
        if mapped is None:
            return None   # 未映射 → 不进入 emotion._recent（§2.4）
        # §2.2：apply + 立即派生权威 label（owner 线程语义事件边界）
        self.emotion.apply_event(mapped, tired_hint=self._tired_hint())
        return None

    def _load_assets(self) -> None:
        """若 data/assets/manifest.json 存在则加载，并把一个真实资产设为 fallback。"""
        from furina.assets.asset_manifest import AssetManifest
        mpath = self.cfg.model_manifest_path
        if mpath.exists():
            try:
                manifest = AssetManifest.load(mpath)
                self.assets.set_manifest(manifest)
                log.info("载入素材 manifest: %d 条", len(self.assets.manifest.entries))
            except Exception as e:
                log.warning("manifest 载入失败: %s", e)
        # fallback：站姿/中性 front，保证任何状态都能有一张真实图
        fallback = self.assets.resolver.resolve(
            AssetQuery("standing", "neutral", "front", "front", "idle"))
        if fallback:
            img = self.assets.load(fallback)
            if img is not None:
                self.assets.fallback = img

    # -------------------------------------------------- 行为注册（骨架小集合）
    def _register_behaviors(self) -> None:
        def util_idle(s):
            return 5.0
        def util_wander(s):
            return s.get("needs", {}).get("boredom", 0) * 0.5
        def util_observe(s):
            return 30.0 if s.get("user_working") else 10.0
        def util_rest(s):
            n = s.get("needs", {})
            return (n.get("fatigue", 0) + n.get("sleepiness", 0)) * 0.5
        def util_talk(s):
            n = s.get("needs", {})
            base = n.get("social_need", 0) * 0.6
            if s.get("user_working"):
                base -= 40        # 打扰成本
            return base
        def util_eat(s):
            return (s.get("needs", {}).get("hunger", 0) - 60) * 2 if s.get("needs", {}).get("hunger", 0) > 60 else -10
        def util_sleep(s):
            n = s.get("needs", {})
            hour = s.get("clock_hour", 0)
            late = (hour >= 23 or hour < 6)
            return (n.get("sleepiness", 0) + n.get("fatigue", 0)) * 0.7 + (30 if late else 0)
        def util_drink(s):
            return (s.get("needs", {}).get("hunger", 0) - 55) * 1.5 if s.get("needs", {}).get("hunger", 0) > 55 else -20
        def util_play(s):
            n = s.get("needs", {})
            u = n.get("playfulness", 0) * 0.6 + n.get("boredom", 0) * 0.3
            if s.get("user_working"):
                u -= 45     # 打扰成本
            return u

        for d in [
            BehaviorDefinition("idle", base_utility=5, priority=5, interruptible=True, tags=["micro"]),
            BehaviorDefinition("wander", utility_fn=util_wander, priority=4, cooldown=60, duration=12),
            BehaviorDefinition("observe_user", utility_fn=util_observe, priority=3, cooldown=45,
                               tags=["social"], chain_to="approach_user",
                               chain_if=lambda s: s.get("user_working") and s.get("user_idle", 0) < 5),
            BehaviorDefinition("rest", utility_fn=util_rest, priority=4, duration=30, cooldown=90),
            BehaviorDefinition("talk_to_user", utility_fn=util_talk, priority=3, cooldown=300, interruptible=True, tags=["social"]),
            BehaviorDefinition("eat", utility_fn=util_eat, priority=3, duration=10, cooldown=300,
                               chain_to="rest", chain_if=lambda s: s.get("needs", {}).get("hunger", 0) < 40),
            BehaviorDefinition("drink", utility_fn=util_drink, priority=3, duration=8, cooldown=240),
            BehaviorDefinition("play", utility_fn=util_play, priority=3, duration=12, cooldown=300, interruptible=True, tags=["social"]),
            BehaviorDefinition("sleep", utility_fn=util_sleep, priority=0, duration=240, cooldown=480, interruptible=True),
            BehaviorDefinition("approach_user", utility_fn=lambda s: 40 if s.get("user_working") else 0,
                               priority=2, duration=8, interruptible=True, tags=["social"]),
        ]:
            self.behavior.register(d)

    # -------------------------------------------------- Director executor
    def _on_execute(self, req) -> None:
        # Director 唯一执行体：把“被仲裁通过的请求”映射到 State/Runtime 表现。
        try:
            from furina.runtime.scheduler import _macro_for
            macro = _macro_for(req.action)
        except Exception:
            macro_map = {"sleep": "sleeping", "eat": "living", "drink": "living", "play": "living",
                         "wander": "living", "rest": "resting", "talk_to_user": "engaged",
                         "observe_user": "working"}
            macro = st_macro(macro_map.get(req.action, "idle"))
        st = self.state.state
        # Phase 13 终审 §10.5：Agent 动作（source=agent）只表达"我在做事"，
        # 不写情绪真相、不覆盖 LifeBrain 的活动语义 —— 保持 WORKING 宏状态。
        if getattr(req, "source", "") == "agent":
            st.life.macro = MacroState.WORKING
            st.life.activity = req.action
            st.attention.target = AttentionTarget.ACTIVE_WINDOW
            st.intent.action = req.action
            return
        # FINAL-R1 §5：**mind 动作真正执行（Director executor 落地）时才启动活动生命周期**。
        # 被更高优先级请求阻塞、从未执行的 mind 动作不创建实例、不 mark_done。
        # H1-FINAL §3：自主台词也在**同一执行边界**启动（阻塞请求无台词、无 social bid）。
        if getattr(req, "source", "") == "mind":
            try:
                sched = getattr(self, "_sched", None)
                payload = getattr(req, "payload", {}) or {}
                if sched is not None and hasattr(sched, "on_mind_action_started"):
                    sched.on_mind_action_started(
                        req.action, float(payload.get("planned_duration", 0.0) or 0.0))
                    if hasattr(sched, "start_autonomous_dialogue"):
                        sched.start_autonomous_dialogue(
                            activity=req.action,
                            speech_level=int(payload.get("speech_level", 0) or 0),
                            speech_intent=payload.get("speech_intent", "") or "",
                            dialogue_needed=bool(payload.get("dialogue_needed", False)),
                            emotion=payload.get("emotion", ""),
                            duration=float(payload.get("planned_duration", 0.0) or 0.0),
                            intent=payload.get("speech_intent", "") or req.action)
            except Exception:
                pass
        st.life.macro = macro
        st.life.activity = req.action
        st.intent.action = req.action
        st.life.reason = req.reason
        # R2.2.1 §8：recent activity truth —— activity 变化时把上一 current 记入 recent（确定性事实）。
        # current_activity=req.action；recent_activity=上一个 current；recent_activity_finished_at=此刻。
        # Phase 13 Final Residual 0.1（clock domain）：recent freshness 统一使用 **monotonic** 时钟
        # （与 `_grounded_fact_recovery` 的 `now = time.monotonic()` 同一 clock domain）。
        # 绝不拿 epoch wall time 与 monotonic 做差；如需持久化 wall-clock，另行存 `_recent_activity_finished_wall`。
        try:
            prev = getattr(self, "_current_activity_truth", "") or ""
            if prev and prev != req.action:
                self._recent_activity = prev
                self._recent_activity_finished_at = time.monotonic()
                self._recent_activity_finished_wall = time.time()
            self._current_activity_truth = req.action
        except Exception:
            pass
        # Phase 13 终审 §4.5：**EmotionEngine 是情绪真相的唯一所有者**。
        # LifeDecision 的 emotion 只是 LifeBrain 的表达/行为提示（非权威），
        # 落到 Intent.emotion（结构化输出槽），**不得覆盖 EmotionState.label**。
        payload = getattr(req, "payload", {}) or {}
        if payload.get("emotion"):
            st.intent.emotion = payload["emotion"]
        st.intent.priority = 1.0 if req.action != "idle" else 0.2
        log.debug("director execute: %s -> %s", req.action, macro.value)

    # -------------------------------------------------- H1 §8：Director 实际替换 → finalize 被抢占 mind
    def _on_director_replace(self, old, new) -> None:
        """高优先级请求（Agent/用户）实际接管当前动作时，立即 finalize 运行中的 mind 实例。

        owner 线程（Director.drain 在运行时主线程调用）。
        """
        try:
            if old is None or getattr(old, "source", "") != "mind":
                return
            new_src = getattr(new, "source", "")
            if new_src == "agent":
                reason = "preempted_by_agent"
            elif new_src == "interaction":
                reason = "preempted_by_user"
            else:
                reason = "interrupted"
            sched = getattr(self, "_sched", None)
            if sched is not None and hasattr(sched, "on_mind_preempted"):
                sched.on_mind_preempted(reason=reason)
        except Exception:
            pass

    # -------------------------------------------------- H1-FINAL §4：定型互动 → 用户抢占
    def _on_user_takeover_interaction(self, ev) -> None:
        """真实定型互动（click/petting/poke/drag）→ finalize 运行中的 mind 活动（owner 线程）。"""
        try:
            sched = getattr(self, "_sched", None)
            if sched is not None and hasattr(sched, "on_user_takeover"):
                sched.on_user_takeover()
        except Exception:
            pass

    # -------------------------------------------------- 互动 → 记忆/关系（legacy-plan/4 §27）
    def _on_meaningful_interaction(self, ev) -> None:
        kind = ev.type.value
        # 关系：唯一写入口 = RelationshipEngine.apply(event)（§12：Relationship → RelationshipEngine owns）。
        # 事件同一份，关系引擎与记忆各自消费，**不做 Memory → Relationship**。
        if kind in ("petting", "poke", "drag"):
            try:
                from furina.relationship import (EV_POSITIVE_TOUCH, EV_NEGATIVE_RESPONSE, EV_REJECT)
                # H1 §9：drag 也是定型语义互动 → 关系事件（拖拽通常逗趣 → 正面触碰）
                rel_ev = EV_POSITIVE_TOUCH if kind in ("petting", "drag") else EV_NEGATIVE_RESPONSE
                if kind == "poke" and ev.count > 5:
                    # 重复戳 → 按拒绝级（更明显负面）；仍走 RelationshipEngine 的正式规则。
                    rel_ev = EV_REJECT
                self.relationship.apply(rel_ev, strength=(
                    0.5 if (kind == "poke" and 1 < ev.count <= 5) else 1.0))
                # 让内存/状态引用同一关系（scheduler 每 tick 也会同步，这里即时刷新）
                self.memory.store.save_relationship(self.relationship.state)
            except Exception:
                pass
        # 形成生活记忆（重要互动才记，legacy-plan/6 §9）—— 记忆引擎只负责记忆，不写关系
        if ev.count == 1 and kind in ("petting", "drag", "poke"):
            self.memory.observe(
                f"用户对我{({'petting':'摸头','drag':'拖拽','poke':'戳'}.get(kind,'互动'))}",
                level=MemoryLevel.EPISODIC, source=MemorySource.INTERACTION,
                importance=0.45, context=f"互动类型={kind}")

    # -------------------------------------------------- Agent → 角色身体同步（legacy-plan/5 §15）
    def _on_agent_body(self, phase: str) -> None:
        # Phase 13 终审 §10.5 + FINAL-R1 §3：Agent 身体/动作所有权必须经 Director
        # （source=agent, P_AGENT_TASK）。**Director 队列变更只能在 owner 线程** ——
        # 回调来自 Agent worker，先经 dispatcher 排队，由 owner 线程执行 submit。
        def _submit_body():
            try:
                from furina.director import ActionRequest
                from furina.director.director import P_AGENT_TASK
                self.director.submit(ActionRequest(
                    source="agent", action=f"agent_{phase}",
                    priority=P_AGENT_TASK, reason=f"agent body: {phase}"))
            except Exception:
                pass
        d = self._rt_dispatcher()
        if d.is_owner():
            _submit_body()
        else:
            d.submit(_submit_body)

    # -------------------------------------------------- 用户命令（右键菜单触发）
    AGENT_TASKS = {
        "整理下载文件夹": "整理下载文件夹",
        "打开记事本": "打开记事本",
        "打开计算器": "打开计算器",
    }

    def _on_user_command(self, text: str) -> None:
        """从窗口进入的命令：喂食 / Agent 任务 / 对话（统一生产入口，FINAL-R1 §3）。"""
        import threading
        if text.startswith("喂："):
            self.submit_feed(text.split("：", 1)[1])
        elif text in self.AGENT_TASKS:
            self.submit_agent_task(text)   # 唯一正式 Agent 请求入口（§7）
        else:
            self.submit_user_message(text)   # FINAL-R1 §3：唯一用户对话生产入口（owner 语义 + worker LLM）

    def _feed(self, food_name: str) -> None:
        """给芙宁娜喂食（M3）。喂食是一个“事件”，由 LifeBrain 决定她做什么（三脑原则）。

        H1 §11 owner 顺序（全部域效果**先于** dialogue worker）：
          食物效应 → 情绪 apply+derive → 记忆 → life/activity/intent → interrupt → 取消 social bid
          → **冻结 DialogueContextSnapshot** → 再启动 worker（只读快照，不读 live 状态）。
        """
        from furina.feeding import apply_food, default_food
        food = default_food(food_name)
        res = apply_food(self.state.state, food)
        # §4.4/FINAL-R1 §2.2：喂食 → EVENT_FEED，apply + 立即派生 label（owner 线程语义边界）
        try:
            from furina.emotion import EVENT_FEED
            self.emotion.apply_event(EVENT_FEED, tired_hint=self._tired_hint())
        except Exception:
            pass
        # 生活记忆（legacy-plan/6）
        self.memory.observe(f"用户喂了我{food.name}", level=MemoryLevel.EPISODIC,
                            source=MemorySource.INTERACTION, importance=0.4,
                            outcome=f"饥饿={res['hunger']} 满足={res['satisfaction']}")
        # 关键：喂食作为“重要事件”触发 LifeBrain 立即重决策，并短暂进入 eat 状态
        # （有 duration + next_think_in，吃完后 LifeBrain 会看到 hunger 已降，自然退出 eat）。
        self.state.state.intent.action = "eat"
        self.state.state.life.activity = "eat"
        self.state.state.life.macro = MacroState.LIVING
        self.state.state._activity_started_at = __import__("time").time()
        if hasattr(self, "_sched"):
            self._sched.interrupt_life("user_fed")
        # H1 §7：喂食 = 用户回应 → 取消 pending social bid
        try:
            sched = getattr(self, "_sched", None)
            if sched is not None and hasattr(sched, "on_user_response"):
                sched.on_user_response()
        except Exception:
            pass
        # H1 §11：**全部域效果完成后**，owner 冻结快照，再启动 dialogue worker
        if self.dialogue_brain:
            snap = self._freeze_feed_snapshot(food.name)
            import threading
            threading.Thread(target=self._feed_dialogue_worker, args=(snap,), daemon=True).start()
        log.info("feed %s -> %s", food.name, res)

    # -------------------------------------------------- H1 §10/§11：Feed 冻结快照 + worker
    def _freeze_feed_snapshot(self, food_name: str):
        from furina.runtime.dialogue_snapshot import DialogueContextSnapshot, freeze_flat
        mem_objs = []
        try:
            mem_objs = self.memory.retrieve(query=food_name, limit=3)
        except Exception:
            mem_objs = []
        mems = [m.content for m in mem_objs]
        wf = self._runtime_world_factors()
        rel = {}
        try:
            rel = self.relationship.factors() if self.relationship else {}
        except Exception:
            pass
        minterp = {}
        try:
            if self.memory is not None:
                minterp = self.memory.interpret(mem_objs, context=food_name)
        except Exception:
            pass
        agent_state, agent_task = self._agent_facts()   # R2.1 P1-1
        return DialogueContextSnapshot(
            intent="eat",
            emotion_label=self.state.state.emotion.label,
            context=f"用户喂了我{food_name}",
            activity="eat",
            user_initiated=True,
            # Pre-Manual §9：显式用户事件 = 在场证据
            presence_known=True,
            user_present=True,
            solitude=False,
            channel="FEED_REACTION",   # FINAL-R1 §4.2：喂食台词不进直接对话历史
            agent_state=agent_state, agent_task=agent_task,   # R2.1 P1-1
            memories=tuple(mems),
            world=freeze_flat(wf),
            relationship=freeze_flat(rel),
            memory_interp=freeze_flat(minterp),
        )

    def _feed_dialogue_worker(self, snap) -> None:
        """worker：只读冻结快照调 DialogueBrain；结果经 BRAIN_SPOKE → dispatcher 回 owner。"""
        try:
            speech = self.dialogue_brain.say(**snap.say_kwargs())
            if speech:
                self.bus.emit(EventType.BRAIN_SPOKE,
                              payload=type("_O", (), {"speech": speech,
                                                      "emotion": snap.emotion_label,
                                                      "channel": "FEED_REACTION"})(),
                              source="app")
        except Exception:
            pass

    # -------------------------------------------------- FINAL-R1 §3：生产入口（GUI + Harness 共用）
    def _rt_dispatcher(self):
        """运行时 owner 分发器：优先 Scheduler 的（同一实例），否则本地兜底。"""
        sched = getattr(self, "_sched", None)
        if sched is not None and hasattr(sched, "dispatcher"):
            return sched.dispatcher
        disp = getattr(self, "_fallback_dispatcher", None)
        if disp is None:
            from furina.runtime.dispatcher import RuntimeDispatcher
            disp = RuntimeDispatcher()
            self._fallback_dispatcher = disp
        return disp

    def submit_feed(self, food: str) -> None:
        """FINAL-R1 §3：**唯一喂食生产入口**（GUI 右键菜单 + Harness 共用）。

        owner（调用线程）：确定性食物效应 + 语义情绪 + 记忆 + Life 打断，**恰好一次**；
        worker：慢 Dialogue LLM；最终 speech 经 dispatcher 回 owner 应用。
        Harness **不得**再包一层 worker 线程（否则两路径线程 owner 不同）。
        """
        self._rt_dispatcher().require_owner("submit_feed")
        # FINAL-R1 §7：喂食 = 用户回应 → 取消 pending social bid
        try:
            sched = getattr(self, "_sched", None)
            if sched is not None and hasattr(sched, "on_user_response"):
                sched.on_user_response()
        except Exception:
            pass
        self._feed(food)

    def submit_user_message(self, text: str) -> None:
        """FINAL-R1 §3：**唯一用户直接对话生产入口**（GUI 输入框 + Harness 共用）。

        owner（调用线程）：高置信语义事件 / 关系 / 情绪（恰好一次）+ 预留 direct 序号
        + 冻结快照 + **入队 DirectDialogueQueue**（立即返回；单 worker 串行 FIFO 消费）；
        worker：DialogueBrain LLM（有界）；owner（dispatcher）：最终 speech 应用 + 记忆提交。
        B1（评审基线 0402e7f）：不再每个消息 spawn 独立线程 —— 专用 direct lane 保证
        每个回合必达终态、ingress FIFO 保序、ambient 不堵 direct。
        """
        d = self._rt_dispatcher()
        d.require_owner("submit_user_message")
        # 1. owner：文本高置信语义因果（reject/praise/talk → 关系/情绪）恰好一次
        fx = self._apply_user_text_fx(text)
        if not fx:
            try:
                from furina.emotion import EVENT_TALK
                self.emotion.apply_event(EVENT_TALK, tired_hint=self._tired_hint())
            except Exception:
                pass
        # Phase 14J：明确高置信 self-statements → UserModel candidate（deterministic conservative
        # extraction，owner persist；不覆盖 current explicit user turn —— 只新增/升级 item）。
        cog = getattr(self, "cognition", None)
        if cog is not None:
            try:
                cand = cog.extract_user_model(text)
                if cand:
                    cog.user_model.upsert_item(
                        category=cand["category"], key=cand["key"], value=cand["value"],
                        confidence=cand["confidence"], source_text_excerpt=cand["excerpt"])
                    ev_type = ("USER_PLAN_DECLARED" if cand["category"] == "PLAN"
                               else "USER_PREFERENCE_DECLARED")
                    cog.record_event(ev_type, source="dialogue", channel="DIRECT_USER_TURN",
                                     payload={"key": cand["key"], "value": cand["value"],
                                              "excerpt": cand["excerpt"],
                                              "confidence": cand["confidence"]},
                                     importance=0.5, consolidate=False)
            except Exception:
                pass
        # 2. R1.2-2：**不再在入队前 reserve DialogueBrain seq** —— DirectDialogueQueue
        #    是 DIRECT_USER_TURN 的唯一串行 authority（turn_id = 用户 ingress identity）；
        #    brain seq 只在 worker 真正执行 DialogueBrain 时由 say() 内部分配
        #    （_next_seq()），与执行顺序天然一致；提前 reserve 会在 job 失败时制造
        #    seq hole（N 永远没人 release → N+1 永久等待）。
        # 3. H1 §10：owner 冻结对话上下文快照（只读事实副本，不引用 live 可变对象）
        snap = self._freeze_direct_snapshot(text)   # ingress_seq=None
        # 4. R1.1-1：无论 dialogue_brain 是否为 None，都必须产生 DirectTurn + 可观察终态。
        #    db=None → worker 立即 FAILED(reason=dialogue_brain_unavailable) + SYSTEM_STATUS，
        #    绝不让用户消息静默消失；db 恢复后下一条消息正常回复。
        self._direct_dialogue_queue().submit(snap, user_text=text)

    # -------------------------------------------------- B1：DirectDialogueQueue（专用直接 lane）
    def _direct_dialogue_queue(self):
        """B1：专用直接对话串行队列（懒创建；owner 提交，单 worker 串行消费，终态可观测）。"""
        q = getattr(self, "_direct_dq", None)
        if q is None:
            from furina.runtime.dialogue_queue import DirectDialogueQueue
            q = DirectDialogueQueue(bus=getattr(self, "bus", None),
                                    timeout=self._direct_turn_timeout())
            q.set_processor(lambda turn, snap: self._direct_job(turn, snap))
            self._direct_dq = q
        return q

    def _direct_turn_timeout(self) -> float:
        """R1.1-3：直接对话回合的总体验预算（独立配置 direct_turn_timeout，默认 30s）。

        这是**用户可见**的总上限（attempt+retry 共享 deadline），不再是 transport
        timeout + 余量；LLM transport 有界性由 adapter 的 profile.timeout 负责，
        LifeBrain/Agent 的 timeout 语义不变。
        """
        try:
            cfg = getattr(self, "cfg", None)
            v = float(getattr(cfg, "direct_turn_timeout", 0.0) or 0.0)
            if v > 0:
                return v
        except Exception:
            pass
        return 30.0

    def _direct_job(self, turn, snapshot) -> dict:
        """DirectDialogueQueue 处理器（worker 线程）：真实生产链 → 终态信息（speech/failure_reason）。

        R1.1-3：传 `deadline=turn.deadline`（本 turn 总预算，attempt+retry 共享）。
        R2.1.1 P0-4/P2：BRAIN_SPOKE 载荷携带 channel/turn_id（speech 事件绑定 DirectTurn）。
        """
        return self._brain_worker(snapshot.user_text, snapshot, deadline=turn.deadline,
                                  turn_id=turn.turn_id)

    def _grounded_fact_recovery(self, snapshot, res: dict, turn_id=None) -> str:
        """R2.2 FINAL §17 + R2.2.1 FINAL §2：LLM 两次因 ungrounded_activity 失败 → authoritative facts 恢复。

        只有 hard_issues 明确含 ungrounded_activity（且无其它 HARD）时才恢复：
        - **只读 snapshot**（owner ingress 冻结的 current/recent activity truth），**不读 live runtime state**；
        - "现在/正在/你在干嘛" → current activity，文案表达"现在"（如"嗯，我现在在看书。"）；
        - "刚才/刚刚" → ingress 冻结的 recent activity，文案表达"刚才"；
        - **Phase 13 Final Residual 0.2**：不存在 authoritative recent truth（recent 缺失或超过 freshness）
          → **不得**把 current 冒充为过去事实（禁止"刚才我在看书"）。允许：明确说明没有可靠 recent 记录，
          再补 current（"刚才那段我没有可靠记录；我现在在看书。"）；或返回 ""（走其它诚实 fallback）。
        返回恢复文本或 ""（不恢复）。
        """
        try:
            hard = list(res.get("hard_issues") or [])
            if "ungrounded_activity" not in hard:
                return ""
            if any(h for h in hard if h != "ungrounded_activity"):
                return ""          # 其它 HARD 仍失败（不绕过）
            activity = str(getattr(snapshot, "activity", "") or "")
            if not activity:
                return ""
            user_text = str(getattr(snapshot, "user_text", "") or "")
            # R2.2.1 FINAL：问"刚才…"优先 snapshot.recent_activity；问"现在…"优先 current。
            asks_recent = any(k in user_text for k in ("刚才", "刚刚", "刚才有", "刚才在做"))
            asks_current = any(k in user_text for k in ("现在", "正在", "你现在", "在干嘛", "在做", "现在在"))
            now = time.monotonic()
            recent_act = str(getattr(snapshot, "recent_activity", "") or "")
            recent_fin = float(getattr(snapshot, "recent_activity_finished_at", 0.0) or 0.0)
            freshness = float(getattr(snapshot, "recent_activity_freshness", 0.0) or 0.0)
            recent_fresh = bool(recent_act and recent_fin > 0 and (now - recent_fin) <= freshness)
            picked = activity
            temporal = "现在"
            if asks_recent and recent_act and recent_act != activity and recent_fresh:
                picked = recent_act
                temporal = "刚才"
            elif asks_recent:
                # 0.2：recent 缺失/过期 → **不得**声称"刚才我在 current"（那是伪造过去事实）。
                # 允许 A：明确说明没有可靠 recent 记录，再补 current；不允许把 current 说成"刚才"。
                desc_now = self._activity_fact_line(activity)
                if desc_now:
                    return f"嗯，刚才那段我没有可靠记录；我现在在{desc_now}。"
                return ""
            # authoritative activity → 事实描述（确定性，不依赖 LLM）
            desc = self._activity_fact_line(picked)
            if not desc:
                return ""
            if asks_recent and temporal == "刚才":
                return f"嗯，刚才我在{desc}。怎么，你好奇呀？"
            if asks_current:
                return f"嗯，我现在在{desc}。怎么，你好奇呀？"
            return f"嗯，我现在在{desc}。怎么，你好奇呀？"
        except Exception:
            return ""

    @staticmethod
    def _activity_fact_line(activity: str) -> str:
        """权威 activity → 简短事实描述（确定性；只覆盖真实 production activities）。"""
        _MAP = {
            "read": "看书",
            "study": "看书",
            "eat": "吃点东西",
            "drink": "喝点什么",
            "rest": "歇着",
            "nap": "打个盹",
            "sleep": "睡觉",
            "explore": "四处走走看看",
            "wander": "随便逛逛",
            "look_around": "看看周围",
            "play": "自己玩一会儿",
            "play_with_object": "玩玩小东西",
            "think": "想点事情",
            "daydream": "发呆想事情",
            "idle": "在这儿待着",
            "talk": "和你说话",
            "approach_user": "走过来看看你",
            "greet": "和你打个招呼",
            "observe_user": "看看你在忙什么",
            "observe_work": "看着你工作",
            "watch_user": "看着你",
            "invite_user": "想叫你一起玩",
            "seek_attention": "想吸引你注意",
            "offer_help": "想看看你要不要帮忙",
            "assist_user": "想着帮帮你",
            "agent_planning": "琢磨怎么帮你办事",
            "agent_work": "帮你处理事情",
            "agent_report": "准备告诉你结果",
            "agent_fail": "想办法把事情办好",
            "tidy": "收拾一下",
            "stretch": "伸个懒腰",
            "yawn": "打个哈欠",
            "groom": "整理一下自己",
            "celebrate": "小小庆祝一下",
            "comfort": "想安慰安慰你",
            "comment": "随便说点什么",
            "ask_user": "想问问你",
            "continue": "继续刚才的事",
        }
        return _MAP.get(activity or "", "")

    def _system_status_failure(self, turn_id=None) -> None:
        """B1/R2.1.1：直接回合无法产生角色回复 → 可观察 SYSTEM_STATUS（非 Furina 台词，不进 Persona history）。

        P0-4/P2：_say 绑定 turn_id + DIRECT_USER_TURN channel（SPEECH_SURFACED 事件），
        使 FAILED 的 SYSTEM_STATUS 与对应 DirectTurn 关联。
        """
        try:
            sched = getattr(self, "_sched", None)
            if sched is not None and hasattr(sched, "_say"):
                # §3：SYSTEM_STATUS 也是域变更 → 经 dispatcher 回 owner 应用
                self._rt_dispatcher().submit(
                    lambda: sched._say("（系统状态：刚才的回复生成失败。）", dur=4.0,
                                       channel="DIRECT_USER_TURN", turn_id=turn_id))
        except Exception:
            pass

    def _confirm_agent_permission(self, description: str, level) -> bool:
        """角色化权限确认（legacy-plan/5 §20）：用户主动点的菜单任务直接放行，给出认可台词。"""
        log.info("agent 授权: %s (level=%s)", description, getattr(level, "name", level))
        return True

    def submit_agent_task(self, user_request: str, extra_context: dict | None = None) -> None:
        """§7：唯一正式 Agent 请求入口（右键菜单 + Harness 共用）。

        通过 App._agent_worker → AgentRuntime.execute；AgentRuntime 是 AGENT_COMPLETED/FAILED
        的**唯一** production owner（App 不再重复 emit）。
        """
        import threading
        threading.Thread(target=self._agent_worker, args=(user_request, extra_context), daemon=True).start()

    def _set_agent_planning(self) -> None:
        """owner 线程：Agent 进入 planning 域状态（FINAL-R1 §3）。"""
        self.state.state.life.macro = MacroState.WORKING
        self.state.state.life.activity = "agent_planning"

    def _agent_worker(self, text: str, extra_context: dict | None = None) -> None:
        # FINAL-R1 §3：worker 线程**不得直接写 CharacterState** —— 进入 agent_planning 状态
        # 是域变更，经 dispatcher 由 owner 线程落地。
        self._rt_dispatcher().submit(self._set_agent_planning)
        log.info("avatar command -> agent: %s", text)
        try:
            req = self.AGENT_TASKS.get(text, text)   # 未登记任务也可作为直接请求（Harness 安全目录）
            if text == "整理下载文件夹":
                d = Path.home() / "Downloads"
                res = self.agent.execute(req, {"path": str(d)})
            elif extra_context and "path" in extra_context:
                res = self.agent.execute(req, {"path": str(extra_context["path"])})
            else:
                res = self.agent.execute(req, dict(extra_context or {}))
            # §7：AgentRuntime.execute 已发出 AGENT_STARTED/COMPLETED/FAILED（唯一 owner）；
            # App 层**不重复 emit**，只做记忆整合。
            # H1 §4.1：**记忆写入是域变更** → 经 dispatcher 回 owner 线程执行（worker 不直写 DB）。
            if res.get("status") == "completed" and res.get("goal"):
                goal = str(res.get("goal"))
                self._rt_dispatcher().submit(
                    lambda: self.memory.observe(f"我帮用户{text}", level=MemoryLevel.EPISODIC,
                                                source=MemorySource.AGENT_TASK, importance=0.55,
                                                outcome=goal))
        except Exception as e:
            log.warning("agent worker err: %s", e)

    def _persist_agent_task(self, record: dict) -> None:
        """owner 线程（Phase 14I）：Agent 结构化 task_record → C7 persist + C6 事件。

        worker 不直接写 Cognition authoritative DB：AgentRuntime 返回 task_record →
        dispatcher 回 owner → 本方法持久化（owner contract）。
        """
        cog = getattr(self, "cognition", None)
        if cog is None:
            return
        try:
            cog.persist_agent_result(
                str(record.get("task_id", "") or ""),
                status=str(record.get("status", "FAILED") or "FAILED"),
                goal=str(record.get("goal", "") or ""),
                original_request=str(record.get("original_request", "") or ""),
                verified=bool(record.get("verified", False)),
                result_summary=str(record.get("result_summary", "") or ""),
                error=str(record.get("error", "") or ""),
                steps=record.get("steps") or [],
                artifacts=record.get("artifacts") or [],
                plan_json=str(record.get("plan_json", "{}") or "{}"),
                permission_summary=str(record.get("permission_summary", "") or ""))
            status = str(record.get("status", "") or "")
            tid = str(record.get("task_id", "") or "")
            if status == "COMPLETED_VERIFIED":
                cog.record_event("AGENT_COMPLETED",
                                 payload={"goal": record.get("goal", ""), "task_id": tid},
                                 source="agent", task_id=tid, importance=0.6)
            elif status == "FAILED":
                cog.record_event("AGENT_FAILED",
                                 payload={"task_id": tid, "error": record.get("error", "")},
                                 source="agent", task_id=tid, importance=0.4)
            elif status == "UNVERIFIED":
                cog.record_event("AGENT_FAILED",
                                 payload={"task_id": tid, "reason": "unverified"},
                                 source="agent", task_id=tid, importance=0.4)
        except Exception as e:
            log.warning("persist agent task failed: %s", e)

    def _agent_facts(self) -> tuple:
        """R2.1 P1-1：CURRENT_FACTS 权威 —— 当前 Agent 生命周期状态 + 活跃任务（只读真相）。"""
        try:
            agent = getattr(self, "agent", None)
            if agent is None:
                return "", ""
            state = str(getattr(agent, "status", "IDLE") or "IDLE")
            task = str(getattr(agent, "current_task", "") or "")
            return state, task
        except Exception:
            return "", ""

    def _freeze_direct_snapshot(self, text: str, ingress_seq=None):
        """H1 §10：owner 线程冻结直接对话上下文（只读事实副本，不引用 live 可变运行时对象）。"""
        from furina.runtime.dialogue_snapshot import DialogueContextSnapshot, freeze_flat
        mem_objs = []
        try:
            mem_objs = self.memory.retrieve(query=text, limit=3)
        except Exception:
            mem_objs = []
        mems = [m.content for m in mem_objs]
        wf = self._runtime_world_factors()   # §4：真实 Scheduler world context（非 {}）
        rel = {}
        try:
            rel = self.relationship.factors() if self.relationship else {}   # §37 归一化 0..1 契约
        except Exception:
            pass
        minterp = {}
        try:
            if self.memory is not None:
                minterp = self.memory.interpret(mem_objs, context=text)   # §5：传 List[Memory] 而非 List[str]
        except Exception:
            pass
        idle = float(getattr(self.state.state, "user_idle_seconds", 0.0))
        agent_state, agent_task = self._agent_facts()   # R2.1 P1-1
        # R2.2.1 FINAL §2：owner ingress 冻结 current/recent activity truth（worker 只读快照，不读 live）。
        # recent_activity / recent_activity_finished_at 来自 owner 在 activity 变化时维护的确定性事实；
        # recent_activity_freshness 是本轮冻结的"刚才"语义最大秒数（常量，随快照携带）。
        recent_act = str(getattr(self, "_recent_activity", "") or "")
        recent_fin = float(getattr(self, "_recent_activity_finished_at", 0.0) or 0.0)
        from furina.app import RECENT_ACTIVITY_FRESHNESS_SECONDS
        # Phase 14K：owner ingress 用 CognitionHub 组装有界 cognitive context（plain immutable）。
        cog_ctx = ()
        cog = getattr(self, "cognition", None)
        if cog is not None:
            try:
                ctx = cog.assemble(query=text, current_facts={"activity": str(
                    getattr(self.state.state.life, "activity", "")), "agent_state": agent_state})
                cog_ctx = freeze_flat({
                    "user_model_items": [{"category": i.category, "value": i.value,
                                          "confidence": i.confidence, "key": i.key}
                                         for i in ctx.user_model_items],
                    "recent_events": [{"event_type": e.event_type, "importance": e.importance}
                                      for e in ctx.recent_events],
                    "relevant_agent_tasks": [{"goal": t.goal, "status": t.status}
                                             for t in ctx.relevant_agent_tasks],
                    "canon_activation": ctx.canon_activation,
                })
            except Exception:
                cog_ctx = ()
        return DialogueContextSnapshot(
            intent="talk",
            emotion_label=self.state.state.emotion.label,
            user_text=text,
            activity=str(getattr(self.state.state.life, "activity", "")),
            user_initiated=True,
            # Pre-Manual §9：**显式用户事件 = 在场证据**（该事件快照 known/present，不伪造 OS idle）
            presence_known=True,
            user_present=True,
            solitude=False,
            channel="DIRECT_USER_TURN",
            # R1.2-2：生产路径不再预留（queue turn_id 是 ingress identity）；显式 seq 仅测试/外部直调
            ingress_seq=ingress_seq,
            agent_state=agent_state, agent_task=agent_task,   # R2.1 P1-1
            memories=tuple(mems),
            world=freeze_flat(wf),
            relationship=freeze_flat(rel),
            memory_interp=freeze_flat(minterp),
            recent_activity=recent_act,
            recent_activity_finished_at=recent_fin,
            recent_activity_freshness=RECENT_ACTIVITY_FRESHNESS_SECONDS,
            cognitive_context=cog_ctx,
        )

    def _brain_worker(self, text: str, snapshot=None, deadline: float | None = None,
                      turn_id: int | None = None) -> dict:
        """用户直接对话 → DialogueBrain（worker 线程：只读**冻结快照**，不读 live 状态）。

        FINAL-R1 §3 + H1 §10：域变更（文本语义/关系/情绪）由 owner 在 submit_user_message 完成；
        owner 冻结 DialogueContextSnapshot；本 worker 只调 say(快照)。对话后记忆提交经 dispatcher 回 owner。
        B1/R1.1：返回 {"speech": ..., "failure_reason": ...} 供 DirectDialogueQueue 记录终态；
        **任何**无法产生角色回复的情况（dialogue_brain=None / LLM 不可用 / 异常 / 超时 /
        空输出 / 双重校验失败 / god gate 抑制 / worker 异常）→ 可观察 SYSTEM_STATUS
        （不是 Furina 台词，不进 Persona history）。
        R1.1-6：failure_reason 来自 **本调用** 的 say_with_result（per-call result），
        不依赖可能被并发 ambient 改写的共享 last_failure_reason。
        R1.1-3：deadline = 本 turn 总预算（attempt+retry 共享）。
        """
        out = {"speech": None, "failure_reason": ""}
        db = getattr(self, "dialogue_brain", None)
        if not db:
            # R1.1-1：dialogue_brain=None 也必须产生可观察终态 + SYSTEM_STATUS（不静默丢消息）
            out["failure_reason"] = "dialogue_brain_unavailable"
            self._system_status_failure(turn_id=turn_id)
            return out
        log.info("avatar conversation: %s", text)
        if snapshot is None:
            # 兼容旧直调（非生产路径）：worker 内冻结（生产一律经 submit_user_message 在 owner 冻结）
            snapshot = self._freeze_direct_snapshot(text)
        try:
            res = db.say_with_result(**snapshot.say_kwargs(), deadline=deadline)
            speech = res.get("speech")
            reason = str(res.get("failure_reason") or "")
            # R2.1 P0-3：validation telemetry（为什么被拦/被放行）
            out["validation_issues"] = list(res.get("validation_issues") or [])
            out["hard_issues"] = list(res.get("hard_issues") or [])
            out["soft_issues"] = list(res.get("soft_issues") or [])
        except Exception as e:
            # worker 异常兜底：回合不得遗留 pending（终态 FAILED/CANCELLED + SYSTEM_STATUS）
            try:
                if db is not None:
                    db.last_failure_reason = f"worker_exception:{type(e).__name__}"
            except Exception:
                pass
            out["failure_reason"] = f"worker_exception:{type(e).__name__}"
            self._system_status_failure(turn_id=turn_id)
            return out
        if speech:
            self.bus.emit(EventType.BRAIN_SPOKE,
                          payload=type("_O", (), {"speech": speech, "intent": "talk",
                                                  "emotion": snapshot.emotion_label,
                                                  "channel": "DIRECT_USER_TURN",
                                                  "turn_id": turn_id})(),
                          source="app")
            out["speech"] = speech
            out["failure_reason"] = ""
        else:
            # R2.2 FINAL §17：Grounded Fact Recovery —— 若因 ungrounded_activity 双重失败，
            # 用权威 current/recent activity 事实恢复（persona wrapping），而不是 SYSTEM_STATUS。
            recovered = self._grounded_fact_recovery(snapshot, res, turn_id=turn_id)
            if recovered:
                out["speech"] = recovered
                out["failure_reason"] = ""
                # 事实恢复也作为 user-visible speech 落地（同 BRAIN_SPOKE 通道）
                self.bus.emit(EventType.BRAIN_SPOKE,
                              payload=type("_O", (), {"speech": recovered, "intent": "talk",
                                                      "emotion": snapshot.emotion_label,
                                                      "channel": "DIRECT_USER_TURN",
                                                      "turn_id": turn_id})(),
                              source="app")
            else:
                # R1.1-1/B1：所有失败模式 → 可观察 SYSTEM_STATUS + 明确 failure_reason
                out["failure_reason"] = reason or "generation_empty"
                self._system_status_failure(turn_id=turn_id)
        # C-R1.3.2：记忆候选观察放对话后；**记忆写入是域变更** → dispatcher 回 owner 执行
        self._rt_dispatcher().submit(lambda: self._maybe_observe_conversation(text))
        return out

    def _recent_memories(self, query: str = ""):
        try:
            return [m.content for m in self.memory.retrieve(query=query, limit=3)]
        except Exception:
            return []

    def _runtime_world_factors(self) -> dict:
        """唯一只读 world context（§4）：实际来自 Scheduler.world_perc，而非复制第二个 WorldPerception。"""
        try:
            sched = getattr(self, "_sched", None)
            wp = getattr(sched, "world_perc", None) if sched is not None else None
            if wp is not None and hasattr(wp, "factors"):
                return dict(wp.factors())
        except Exception:
            pass
        return {}

    def _tired_hint(self) -> float:
        """真实困倦信号 0..1（sleepiness+fatigue），供情绪派生（sleepy 只允许真实困倦触发）。"""
        try:
            n = self.state.state.needs
            return max(0.0, min(1.0, (float(n.sleepiness) + float(n.fatigue)) / 200.0))
        except Exception:
            return 0.0

    # -------------------------------------------------- Phase 13C §32-36：高置信文本 → 互动因果（conservative）
    def _apply_user_text_fx(self, text: str) -> str:
        """用户**对芙宁娜**的高置信语言意义 → 统一语义执行入口（不做第二套 Interaction System）。

        C-R1.5：拒绝 = 与 Reject 按钮**共享同一 route**（on_user_reject → RelationshipEngine.apply +
        persistence + rejection stats + LifeBrain tolerance + life interrupt）。
        Praise/gratitude 用正确语义事件（EV_POSITIVE_RESPONSE），**不得伪装成 EV_POSITIVE_TOUCH**。
        保守阈值：只有强匹配"直接对象是芙宁娜"才触发；不确定 → 不触发（§34）。
        返回语义分类："reject" / "praise" / ""（供调用方决定 EVENT_TALK 是否叠加）。
        """
        import re
        t = (text or "").strip()
        if not t:
            return
        # FINAL-R1 §7：文本回应也取消 pending social bid（用户回应了）
        try:
            sched = getattr(self, "_sched", None)
            if sched is not None and hasattr(sched, "on_user_response"):
                sched.on_user_response()
        except Exception:
            pass
        # 1. 高置信拒绝（对芙宁娜的明确指令）→ 与 Reject 按钮同一 route
        if re.search(r"别烦我|别吵我|走开|离我远点|不要烦我|先别理我|我要忙|我要专心|没空理你们|别打扰我", t):
            sched = getattr(self, "_sched", None)
            if sched is not None and hasattr(sched, "on_user_reject"):
                sched.on_user_reject()   # 唯一 reject 语义执行入口（含 §4.4 EVENT_REJECT 恰好一次）
            else:
                try:
                    from furina.relationship.engine import EV_REJECT
                    self.relationship.apply(EV_REJECT)
                except Exception:
                    pass
                # 无 Scheduler 兜底：情绪语义事件（EmotionEngine 唯一 owner，§2.2 立即派生）
                try:
                    from furina.emotion import EVENT_REJECT
                    self.emotion.apply_event(EVENT_REJECT, tired_hint=self._tired_hint())
                except Exception:
                    pass
            return "reject"
        # 2. 高置信称赞/谢意（对芙宁娜）→ 正确语义事件（非 POSITIVE_TOUCH）+ 持久化一次（C-R2 §10）
        if re.search(r"(你真|你挺|你好|你).*(可爱|好看|喜欢|棒|厉害|贴心)|我喜欢你|谢谢你|感谢|多谢", t):
            try:
                from furina.relationship.engine import EV_POSITIVE_RESPONSE
                if self.relationship is not None:
                    self.relationship.apply(EV_POSITIVE_RESPONSE)
                    self.state.state.relationship = self.relationship.state
                    # 与其它 meaningful interaction 相同的持久化契约（一次）
                    try:
                        store = getattr(getattr(self.memory, "store", None), "save_relationship", None)
                        if store:
                            store(self.relationship.state)
                    except Exception:
                        pass
            except Exception:
                pass
            # §4.4/FINAL-R1 §2.2：夸奖 → EVENT_PRAISE，apply + 立即派生（恰好一次）
            try:
                from furina.emotion import EVENT_PRAISE
                self.emotion.apply_event(EVENT_PRAISE, tired_hint=self._tired_hint())
            except Exception:
                pass
            return "praise"

    # -------------------------------------------------- Phase 13C §28-31：对话→记忆（conservative）
    def _maybe_observe_conversation(self, text: str) -> None:
        """只对高置信"用户信息/计划/偏好/承诺"做记忆候选（不盲存所有闲聊；无新 LLM）。

        R2.1 P1-3：plan 确定性提取扩展（我今天准备/我今天打算/我明天准备/我今晚打算/
        我这周计划…）+ follow-up（做完以后…）挂到最近一条 user plan 记忆（context 联动），
        让"今天准备做什么？/做完以后会怎么样？"能被检索到事实。
        """
        import re
        t = (text or "").strip()
        if not t or len(t) < 8:
            return
        try:
            # 1) 计划（高置信）：我今天准备… / 我明天打算… / 我这周计划…
            plan_m = re.search(r"我(今天|明天|今晚|这周|这两天|这个月)?(准备|打算|计划)", t)
            if plan_m:
                self._last_user_plan = t
                self.memory.observe(t, level=MemoryLevel.EPISODIC,
                                    source=MemorySource.CONVERSATION,
                                    importance=0.5, context="user_plan")
                return
            # 2) 计划 follow-up（做完以后应该…）→ 联动最近一条 user plan
            follow_m = re.search(r"(做完|弄完|搞定|完成后|忙完)(以后|之后|了)?(应该|就会|可以|大概)?", t)
            if follow_m and getattr(self, "_last_user_plan", None):
                self.memory.observe(
                    f"{t}（关于：{self._last_user_plan}）",
                    level=MemoryLevel.EPISODIC, source=MemorySource.CONVERSATION,
                    importance=0.45, context="user_plan_followup",
                    outcome=self._last_user_plan)
                return
            # 3) 一般用户信息/偏好/承诺（保守，保持原语义）
            if re.search(r"我(今晚|明天|这周|准备|打算|计划|要|想|正在)|我(喜欢|不喜欢|最怕|讨厌|最爱|习惯)|我(最近|这两天|这几|从今天起)", t):
                self.memory.observe(t, level=MemoryLevel.EPISODIC,
                                    source=MemorySource.CONVERSATION,
                                    importance=0.4, context="user_speech")
        except Exception:
            pass

    # -------------------------------------------------- 启动
    def spawn(self, screen_w: int, screen_h: int, win: "FurinaWindow") -> None:
        self.world.screen.w, self.world.screen.h = screen_w, screen_h
        self.world.bounds[0].w, self.world.bounds[0].h = screen_w, screen_h
        # 参考角色尺寸：屏幕高度的 ~15%（whale-girl 式小尺寸桌面角色，不占屏不截脚），带 DPI 缩放
        ref_h = int(screen_h * 0.15)
        self.assets.set_reference_size(int(ref_h * 0.62), ref_h)
        win.apply_reference_size()
        win.set_position(screen_w * 0.55, screen_h - ref_h - 40)


def st_macro(value: str):
    from furina.state import MacroState
    return MacroState(value)


def _render_tick(win, frame_runtime, micro_sched, consumer, spatial=None, resolver=None) -> None:
    """动画时钟 tick：推进 AnimationRuntime 生命周期 + micro/呼吸/眨眼 + Gaze/Expression hold
    + 空间移动（DesktopSpatialRuntime），把最终视觉状态交给 Window.present()。

    present 是唯一动画 owner；paintEvent 只画。Spatial 是自主移动唯一 owner。
    """
    import time as _t
    now = _t.monotonic()
    vs = getattr(consumer, "visual", None)
    if vs is None:
        return
    # 0) 空间意图 → SpatialRuntime（Phase 12，先于动画；只消费 Frame 语义）
    if spatial is not None and resolver is not None:
        try:
            frame = getattr(consumer, "last_frame", None)
            if frame is not None:
                decision = resolver.resolve(frame)
                spatial.accept(decision, now=now)
            spatial.tick(now=now)
            frame_runtime.set_movement(*_movement_args(spatial))
        except Exception:
            pass
    # 从 last_frame 取 body 节奏（tempo）供 MicroScheduler 频率调节
    try:
        tempo = getattr(getattr(consumer, "last_frame", None), "body", None).movement_tempo
    except Exception:
        tempo = "normal"
    # 1) 用最新 visual 喂 AnimationRuntime（若有新语义变化）
    frame_runtime.accept(vs, prev_pose=frame_runtime.current_pose, prev_activity=frame_runtime.current_plan.get("activity", "idle"))
    # 2) 推进生命周期（ENTRY→LOOP→EXIT→...）
    frame_runtime.tick(now=now)
    # 3) Gaze：semantic gaze（Frame）→ hold/cooldown 后的实际 visual gaze
    visual_gaze = frame_runtime.gaze_runtime.update(getattr(vs, "gaze", "NONE"), now=now)
    # 4) Expression hold
    try:
        from furina.runtime.frontend import P_INTERACTION_REACTION
        high_prio = frame_runtime.priority >= P_INTERACTION_REACTION
    except Exception:
        high_prio = False
    visual_expression = frame_runtime.expression_hold.update(getattr(vs, "expression", "neutral"), high_prio=high_prio, now=now)
    # 5) Micro（呼吸/眨眼/微动作）
    try:
        ms = micro_sched.step(dt=1.0 / frame_runtime.fps, now=now,
                              micro_pref=getattr(vs, "micro", None) or [],
                              tempo=tempo)
    except Exception:
        ms = None
    # 6) 喂给 Window（只画，不决定演什么）
    degraded = dict(frame_runtime.current_plan.get("degraded", {}) or {})
    if spatial is not None:
        try:
            if frame_runtime.movement_degraded:
                degraded["DEGRADED_WALK_VISUAL"] = {
                    "reason": "missing_walk_asset", "moving": spatial.is_moving}
        except Exception:
            pass
    # §19 debug instrumentation（仅 debug）：让人工直接看到"为什么是这张/这句"
    dbg = ""
    if getattr(win, "show_debug", False):
        try:
            lf = getattr(consumer, "last_frame", None)
            mapped = getattr(vs, "asset_action", "idle")
            dbg = (f"act={getattr(vs,'activity','')}\n"
                   f"sem={getattr(vs,'raw_posture','')}/{getattr(vs,'raw_expression','')}/{getattr(vs,'raw_gaze','')}\n"
                   f"map={getattr(vs,'target_pose','')}/{getattr(vs,'expression','')}/{getattr(vs,'gaze','')}/{mapped}\n"
                   f"clip={frame_runtime.current_plan.get('clip','')} phase={frame_runtime.phase}\n"
                   f"owner={'AnimationRuntime' if frame_runtime.current_plan else 'window-legacy'}\n"
                   f"dialog_src={getattr(frame_runtime, '_dialog_source', 'DialogueBrain')}")
        except Exception:
            dbg = ""
    win.present(
        visual_phase=frame_runtime.phase,
        current_pose=frame_runtime.current_pose,
        target_pose=getattr(vs, "target_pose", "standing"),
        expression=visual_expression,
        gaze=visual_gaze,
        clip_name=frame_runtime.current_plan.get("clip", vs.activity),
        breath=(ms.breath if ms else 0.5),
        blink=(ms.blink if ms else 0.0),
        micro=(list(ms.active_micro) if ms else []),
        bubble_text=getattr(vs, "bubble_text", "") or "",
        degraded=degraded,
        micro_gaze=(ms.gaze if ms else "front"),
        debug=dbg or getattr(win, "_debug", "") or "",
    )


def _movement_args(spatial):
    mv = spatial.movement_visual()
    return (bool(mv.get("moving", False)), str(mv.get("facing", "FRONT")))


def launch(cfg: AppConfig | None = None) -> Furina:
    cfg = cfg or load_config()
    setup_logging(logging.DEBUG if cfg.debug else logging.INFO)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(True)

    furina = Furina(cfg)
    screen = app.primaryScreen()
    sw, sh = screen.size().width(), screen.size().height()

    # 窗口（透明 overlay）
    win = FurinaWindow(furina.world, furina.assets, furina.interaction)
    win.on_command = furina._on_user_command     # 右键菜单命令
    win.show_debug = cfg.debug                   # 默认隐藏状态调试叠层
    # 透传：将 InteractionEngine 的互动事件交由调度器反应
    win.show()

    # 调度器 + 窗口感知（三脑：LifeBrain 驱动生命态，DialogueBrain 负责语言）
    sched = Scheduler(furina.bus, furina.state, furina.behavior, furina.director,
                      furina.memory, furina.world, furina.wa,
                      life_brain=furina.life_brain, dialogue_brain=furina.dialogue_brain,
                      emotion_engine=furina.emotion, motivation=furina.motivation,
                      relationship_engine=furina.relationship, embodiment=furina.embodiment)
    sched.start(win)
    # H1 §12：启动时在 Qt/runtime 线程**显式绑定 owner**（先于任何 worker 请求守卫变更）
    sched.dispatcher.bind_owner()
    furina.spawn(sw, sh, win)

    # Phase 11：前端唯一动画时钟（30 FPS）+ Frame Consumer（Window 由 Consumer 驱动，Scheduler 不再直写）。
    from furina.runtime.frontend import FrontendFrameConsumer, AnimationRuntime
    from furina.runtime.micro import MicroScheduler
    frame_runtime = AnimationRuntime(win.anim, furina.assets, fps=30.0, bus=furina.bus)   # FIX L：接 EventBus
    micro_sched = MicroScheduler(fps=30.0)
    consumer = FrontendFrameConsumer(furina.bus)   # 只消费 frame → 更新 visual；渲染由 _render_tick 读 visual
    furina._frame_consumer = consumer
    furina._frame_runtime = frame_runtime

    # FIX E1：拖拽姿态 override 请求 → AnimationRuntime 决定视觉（Window 只报告）
    win.on_drag_pose = lambda active: frame_runtime.set_drag_override(active)

    # Phase 12：桌面空间生命层（自主移动唯一 owner）。只消费 Frame 语义，不读后端内部。
    from furina.runtime.spatial import DesktopSpatialRuntime, SpatialIntentResolver
    spatial_resolver = SpatialIntentResolver()
    spatial = DesktopSpatialRuntime(furina.world, window=win)
    spatial.sync_from_window()
    furina._spatial = spatial
    furina._spatial_resolver = spatial_resolver
    # 拖拽 → SpatialRuntime 接管（View 只报告事件）
    import time as _t
    win.on_drag_start = lambda: spatial.on_drag_start(_t.monotonic())
    win.on_drag_release = lambda: spatial.on_drag_release(_t.monotonic(), commit=True)

    # 主循环：Qt 定时器驱动 Fast tick（步进动画时钟 + 空间移动 + 重绘）。
    timer = QTimer()
    timer.timeout.connect(lambda: (sched.step(),
                                   _render_tick(win, frame_runtime, micro_sched, consumer, spatial, spatial_resolver),
                                   win.update()))
    timer.start(16)

    log.info("芙宁娜启动：@ %sx%s, LLM=%s, 素材=%d 条",
             sw, sh, cfg.llm.model, len(furina.assets.manifest.entries))
    furina._app = app
    furina._win = win
    furina._sched = sched
    furina._timer = timer
    return furina


def run() -> None:
    furina = launch()
    furina._app.exec()


def launch_harness(cfg: AppConfig | None = None) -> Furina:
    """Phase 13 Harness：不渲染角色素材，证明数字生命（真实 Runtime）成立。

    复用同一套真实子系统（Furina/Scheduler/LifeBrain/DialogueBrain/Emotion/Relationship/
    Memory/Spatial/Agent），仅用 Harness（TruthPanel+Proxy）呈现。
    """
    import time as _t
    from PySide6.QtCore import QTimer
    from furina.runtime.frontend import FrontendFrameConsumer
    from furina.runtime.harness import RuntimeHarness, RuntimeTruthPanel

    cfg = cfg or load_config()
    setup_logging(logging.DEBUG if cfg.debug else logging.INFO)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(True)
    furina = Furina(cfg)

    screen = app.primaryScreen()
    sw, sh = screen.size().width(), screen.size().height()
    furina.world.screen.w, furina.world.screen.h = sw, sh
    furina.world.bounds[0].w, furina.world.bounds[0].h = sw, sh

    # 真实 Scheduler（需要 window 位置作 legacy；这里用 proxy）
    sched = Scheduler(furina.bus, furina.state, furina.behavior, furina.director,
                      furina.memory, furina.world, furina.wa,
                      life_brain=furina.life_brain, dialogue_brain=furina.dialogue_brain,
                      emotion_engine=furina.emotion, motivation=furina.motivation,
                      relationship_engine=furina.relationship, embodiment=furina.embodiment)
    furina._sched = sched

    # consumer（Frame→mapped），空间由 harness 驱动 proxy
    consumer = FrontendFrameConsumer(furina.bus)
    furina._frame_consumer = consumer

    # §2：唯一 SpatialRuntime（launch_harness 创建并注入；proxy 由它驱动）
    from furina.runtime.spatial import DesktopSpatialRuntime
    from furina.runtime.harness import RuntimeHarness, RuntimeTruthPanel, SpatialProxyWindow
    proxy = SpatialProxyWindow(world=furina.world)
    proxy.set_position(sw * 0.5, sh - 100)
    spatial = DesktopSpatialRuntime(furina.world, window=proxy)
    spatial.sync_from_window()        # foot 从 proxy pos 对齐（§2：同一 truth）
    furina._spatial = spatial
    h = RuntimeHarness(furina, spatial=spatial, proxy=proxy)
    furina._harness = h
    h.proxy.set_position(sw * 0.5, sh - 100)
    h.proxy.show()
    panel = RuntimeTruthPanel(h.vm, h)
    h.panel = panel
    panel.move(40, 40)
    panel.show()
    sched.start(h.proxy)

    # 主循环：生产 cadence + harness 只读刷新（不阻塞生命循环）
    timer = QTimer()
    timer.timeout.connect(lambda: (sched.step(), h.tick_spatial()))
    timer.start(1000 // 20)   # 20Hz 生产节流不逼 60；LifeBrain 仍走其内部 cadence

    furina._app = app
    furina._win = h.proxy
    furina._timer = timer
    log.info("Harness 启动：%sx%s, LLM=%s, 素材=%d 条 (harness 模式，不渲染 PNG)",
             sw, sh, cfg.llm.model, len(furina.assets.manifest.entries))
    return furina


def run_harness() -> None:
    furina = launch_harness()
    furina._app.exec()
