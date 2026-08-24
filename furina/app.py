"""应用总装（App Wiring）。

骨架阶段：
- 组装各子系统与 EventBus，注册最小行为集。
- Director 作为唯一动作仲裁（plan/8 §3）；Agent 与行为共享 BehaviorEngine。
- 无真实素材时用占位图渲染，保证可运行、可看生命循环。
"""
from __future__ import annotations

import logging
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

        # 互动事件 → 情绪（确定性映射，不用 LLM）
        emotion_event = {"petting": EVENT_PET, "poke": EVENT_POKE,
                         "click": EVENT_CLICK, "drag": EVENT_DRAG}
        self.bus.on(EventType.INTERACTION_INPUT,
                    lambda ev: self.emotion.apply(emotion_event.get(
                        getattr(ev.payload.type, "value", ""), EVENT_CLICK)))

        # Director（唯一仲裁）
        self.director = Director(self.bus)

        # Agent
        self.tools = ToolRegistry()
        for tool_cls in ALL_TOOLS:
            self.tools.register(tool_cls())  # type: ignore[arg-type]
        self.permission = PermissionManager()
        # 用户主动在右键菜单里点的“随手帮忙”任务 → 视为用户已授权（plan/5 §20），
        # 角色化确认由 confirm 回调表现（弹台词），并放行 L2/L3。
        self.permission.on_confirm = self._confirm_agent_permission
        self.agent = AgentRuntime(self.bus, self.tools, self.permission)

        # 三脑架构（plan/8 修正）：LifeBrain 状态决策 + DialogueBrain 语言 + ToolAgent 双手。
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

        # 纵向集成：互动→记忆/关系；Agent→角色身体同步（保持模块边界）
        self.interaction.on_meaningful_interaction = self._on_meaningful_interaction
        self.agent.on_body_sync = self._on_agent_body
        # 互动 hitbox：由素材锚点定义（plan/4 §5），否则摸头/拖拽/点击都无法识别
        self.interaction.set_hitboxes_from_anchor(
            {"head": [0.5, 0.18], "body": [0.5, 0.52], "hand": [0.72, 0.45],
             "foot": [0.5, 0.9], "item": [0.5, 0.7]},
            (0.5, 0.5, 0.42, 0.46))

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
        st.life.macro = macro
        st.life.activity = req.action
        st.intent.action = req.action
        st.life.reason = req.reason
        # 从请求载荷补齐情绪/意图优先（LifeBrain 决策给的）
        payload = getattr(req, "payload", {}) or {}
        if payload.get("emotion"):
            st.emotion.label = payload["emotion"]
        st.intent.priority = 1.0 if req.action != "idle" else 0.2
        log.debug("director execute: %s -> %s", req.action, macro.value)

    # -------------------------------------------------- 互动 → 记忆/关系（plan/4 §27）
    def _on_meaningful_interaction(self, ev) -> None:
        kind = ev.type.value
        # 关系：唯一写入口 = RelationshipEngine.apply(event)（§12：Relationship → RelationshipEngine owns）。
        # 事件同一份，关系引擎与记忆各自消费，**不做 Memory → Relationship**。
        if kind in ("petting", "poke"):
            try:
                from furina.relationship import (EV_POSITIVE_TOUCH, EV_NEGATIVE_RESPONSE, EV_REJECT)
                rel_ev = EV_POSITIVE_TOUCH if kind == "petting" else EV_NEGATIVE_RESPONSE
                if kind == "poke" and ev.count > 5:
                    # 重复戳 → 按拒绝级（更明显负面）；仍走 RelationshipEngine 的正式规则。
                    rel_ev = EV_REJECT
                self.relationship.apply(rel_ev, strength=(
                    0.5 if (kind == "poke" and 1 < ev.count <= 5) else 1.0))
                # 让内存/状态引用同一关系（scheduler 每 tick 也会同步，这里即时刷新）
                self.memory.store.save_relationship(self.relationship.state)
            except Exception:
                pass
        # 形成生活记忆（重要互动才记，plan/6 §9）—— 记忆引擎只负责记忆，不写关系
        if ev.count == 1 and kind in ("petting", "drag", "poke"):
            self.memory.observe(
                f"用户对我{({'petting':'摸头','drag':'拖拽','poke':'戳'}.get(kind,'互动'))}",
                level=MemoryLevel.EPISODIC, source=MemorySource.INTERACTION,
                importance=0.45, context=f"互动类型={kind}")

    # -------------------------------------------------- Agent → 角色身体同步（plan/5 §15）
    def _on_agent_body(self, phase: str) -> None:
        # phase: approach / work / report / confused
        self.state.state.life.macro = MacroState.WORKING
        self.state.state.life.activity = f"agent_{phase}"
        self.state.state.attention.target = AttentionTarget.ACTIVE_WINDOW

    # -------------------------------------------------- 用户命令（右键菜单触发）
    AGENT_TASKS = {
        "整理下载文件夹": "整理下载文件夹",
        "打开记事本": "打开记事本",
        "打开计算器": "打开计算器",
    }

    def _on_user_command(self, text: str) -> None:
        """从窗口进入的命令：喂食 / Agent 任务 / 对话（后台线程，避免卡 UI）。"""
        import threading
        if text.startswith("喂："):
            self._feed(text.split("：", 1)[1])
        elif text in self.AGENT_TASKS:
            self.submit_agent_task(text)   # 唯一正式 Agent 请求入口（§7）
        else:
            threading.Thread(target=self._brain_worker, args=(text,), daemon=True).start()

    def _feed(self, food_name: str) -> None:
        """给芙宁娜喂食（M3）。喂食是一个“事件”，由 LifeBrain 决定她做什么（三脑原则）。

        不硬锁状态：只应用食物效应 + 触发一次性吃东西的表现 + 记记忆，
        并让 LifeBrain 立即重决策（饥饿已下降 → 她吃完会自然退出 eat，而不是永远吃）。
        """
        from furina.feeding import apply_food, default_food
        food = default_food(food_name)
        res = apply_food(self.state.state, food)
        # FIX G：喂食台词交给 DialogueBrain（三脑：语言只负责怎么说），不直接锁状态/用固定 reaction
        if self.dialogue_brain:
            try:
                mem_objs = []
                try:
                    mem_objs = self.memory.retrieve(query=food.name, limit=3)
                except Exception:
                    mem_objs = []
                mems = [m.content for m in mem_objs]
                wf = self._runtime_world_factors()   # §4 真实 Scheduler world
                rel = {}
                try:
                    rel = self.relationship.factors() if self.relationship else {}   # C-R1.2 归一化
                except Exception:
                    pass
                minterp = {}
                try:
                    if self.memory is not None:
                        minterp = self.memory.interpret(mem_objs, context=food.name)   # §5 real objects
                except Exception:
                    pass
                speech = self.dialogue_brain.say(
                    intent="eat", emotion=self.state.state.emotion.label,
                    user_initiated=True, context=f"用户喂了我{food.name}",
                    activity="eat", memories=mems, world=wf, relationship=rel,
                    memory_interp=minterp, user_present=True)
                if speech:
                    self.bus.emit(EventType.BRAIN_SPOKE,
                                  payload=type("_O", (), {"speech": speech,
                                                          "emotion": self.state.state.emotion.label})(),
                                  source="app")
            except Exception:
                pass
        # 生活记忆（plan/6）
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
        log.info("feed %s -> %s", food.name, res)

    def _confirm_agent_permission(self, description: str, level) -> bool:
        """角色化权限确认（plan/5 §20）：用户主动点的菜单任务直接放行，给出认可台词。"""
        log.info("agent 授权: %s (level=%s)", description, getattr(level, "name", level))
        return True

    def submit_agent_task(self, user_request: str, extra_context: dict | None = None) -> None:
        """§7：唯一正式 Agent 请求入口（右键菜单 + Harness 共用）。

        通过 App._agent_worker → AgentRuntime.execute；AgentRuntime 是 AGENT_COMPLETED/FAILED
        的**唯一** production owner（App 不再重复 emit）。
        """
        import threading
        threading.Thread(target=self._agent_worker, args=(user_request, extra_context), daemon=True).start()

    def _agent_worker(self, text: str, extra_context: dict | None = None) -> None:
        self.state.state.life.macro = MacroState.WORKING
        self.state.state.life.activity = "agent_planning"
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
            if res.get("status") == "completed" and res.get("goal"):
                self.memory.observe(f"我帮用户{text}", level=MemoryLevel.EPISODIC,
                                    source=MemorySource.AGENT_TASK, importance=0.55,
                                    outcome=str(res.get("goal")))
        except Exception as e:
            log.warning("agent worker err: %s", e)

    def _brain_worker(self, text: str) -> None:
        """用户直接对话 → DialogueBrain（三脑架构：语言只负责“怎么说”）。"""
        if not self.dialogue_brain:
            return
        log.info("avatar conversation: %s", text)
        # Phase 13C §32-36：文本→互动因果（exactly-once per message；无新 LLM）。§28-31 观察放**对话后**，
        # 避免"本轮刚存的记忆立即被同一 prompt 检索回显"（C-R1.3.2）。
        self._apply_user_text_fx(text)
        # FIX H：完整 runtime context（user_initiated / activity / world / relationship / memory interp / 在场）
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
        # 对话前建立 root trace（§11 由 harness trace context 关联）
        speech = self.dialogue_brain.say(
            intent="talk", emotion=self.state.state.emotion.label,
            user_text=text, memories=mems, user_initiated=True,
            activity=str(getattr(self.state.state.life, "activity", "")),
            world=wf, relationship=rel, memory_interp=minterp,
            user_present=bool(self.state.state.user_idle_seconds < 300),
            solitude=bool(self.state.state.user_idle_seconds > 300))
        if speech:
            self.bus.emit(EventType.BRAIN_SPOKE,
                          payload=type("_O", (), {"speech": speech, "intent": "talk",
                                                  "emotion": self.state.state.emotion.label})(),
                          source="app")
        # C-R1.3.2：记忆候选观察放在**对话回复完成之后**，避免当前轮记忆被同一 prompt 检索回显。
        self._maybe_observe_conversation(text)

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

    # -------------------------------------------------- Phase 13C §32-36：高置信文本 → 互动因果（conservative）
    def _apply_user_text_fx(self, text: str) -> None:
        """用户**对芙宁娜**的高置信语言意义 → 统一语义执行入口（不做第二套 Interaction System）。

        C-R1.5：拒绝 = 与 Reject 按钮**共享同一 route**（on_user_reject → RelationshipEngine.apply +
        persistence + rejection stats + LifeBrain tolerance + life interrupt）。
        Praise/gratitude 用正确语义事件（EV_POSITIVE_RESPONSE），**不得伪装成 EV_POSITIVE_TOUCH**。
        保守阈值：只有强匹配"直接对象是芙宁娜"才触发；不确定 → 不触发（§34）。
        """
        import re
        t = (text or "").strip()
        if not t:
            return
        # 1. 高置信拒绝（对芙宁娜的明确指令）→ 与 Reject 按钮同一 route
        if re.search(r"别烦我|别吵我|走开|离我远点|不要烦我|先别理我|我要忙|我要专心|没空理你们|别打扰我", t):
            sched = getattr(self, "_sched", None)
            if sched is not None and hasattr(sched, "on_user_reject"):
                sched.on_user_reject()   # 唯一 reject 语义执行入口
            elif self.relationship is not None:
                try:
                    from furina.relationship.engine import EV_REJECT
                    self.relationship.apply(EV_REJECT)
                except Exception:
                    pass
            return
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

    # -------------------------------------------------- Phase 13C §28-31：对话→记忆（conservative）
    def _maybe_observe_conversation(self, text: str) -> None:
        """只对高置信"用户信息/计划/偏好/承诺"做记忆候选（不盲存所有闲聊；无新 LLM）。"""
        import re
        t = (text or "").strip()
        if not t or len(t) < 8:
            return
        if re.search(r"我(今晚|明天|这周|准备|打算|计划|要|想|正在)|我(喜欢|不喜欢|最怕|讨厌|最爱|习惯)|我(最近|这两天|这几|从今天起)", t):
            try:
                self.memory.observe(t, level=MemoryLevel.EPISODIC, source=MemorySource.CONVERSATION,
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
