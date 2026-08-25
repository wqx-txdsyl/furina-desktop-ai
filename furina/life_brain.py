"""LifeBrain —— 「大脑」：芙宁娜生命行为唯一的高层决策者（三脑架构）。

职责（严格边界）：
- 只回答：我现在是谁 / 我现在怎么样 / 我想干什么 / 下一步做什么。
- 输出结构化 LifeDecision（activity/emotion/intent/duration/interruptible/exit_conditions/next_think_in/dialogue_needed/tool_needed）。
- **绝不**直接控制渲染/动画/输入/每帧（legacy-plan/8 §5）；这些交给 Runtime 身体。
- **绝不**决定“怎么说”（DialogueBrain）；**绝不**决定“怎么操作”（Tool Agent）。

关键设计（修正“睡死/状态切换模糊”）：
- 可返回 ``activity="continue"``：当前行为仍合适就继续，避免每 3 秒翻车。
- 每个决策带 ``next_think_in``：睡眠/读书等长行为也定期重新观察，避免变成永久状态。
- 带 ``exit_conditions`` / ``interrupt_conditions``：行为有退出条件，用户/重要事件可打断。
- LLM 不可用时回退本地规则（A-13：无 LLM 仍能生活），但本地规则只是 fallback，不是主逻辑。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from furina.core import get_logger
from furina.llm import LLMAdapter, LLMMessage, content
from furina.persona import FURINA_PERSONA

log = get_logger("life_brain")

# Life State（她“在干什么”，legacy-plan/2 §四 —— Brain 管的是 Life）
# 任务书 §3：自主生活行为池（日常/娱乐/社交/工作辅助）—— 给 Brain 足够的自主空间。
LIFE_ACTIVITIES = [
    # 日常
    "idle", "walk", "read", "drink", "eat", "stretch", "rest", "tidy", "think", "daydream",
    # 娱乐
    "play", "explore", "look_around", "play_with_object",
    # 社交
    "observe_user", "approach_user", "watch_user", "greet", "ask_user", "comment",
    "seek_attention", "invite_user", "talk",
    # 工作辅助
    "observe_work", "offer_help", "assist_user", "celebrate", "comfort",
    # 生存
    "sleep",
    # 持续
    "continue",
]
# 自主生活（不打扰用户）活动集合：用户不互动时她“做自己的事”
SELF_ACTIVITIES = ["read", "drink", "stretch", "tidy", "think", "daydream", "play",
                   "explore", "look_around", "play_with_object", "walk", "rest"]
# 主动社交/接近用户的活动集合
SOCIAL_ACTIVITIES = ["observe_user", "approach_user", "watch_user", "greet", "talk",
                     "seek_attention", "invite_user", "comment"]
# 需要说话的场合
SPEAKABLE = {"greet", "ask_user", "comment", "invite_user", "seek_attention", "talk",
             "offer_help", "celebrate", "comfort", "approach_user"}
# 允许的情绪标签
LIFE_EMOTIONS = ["neutral", "happy", "proud", "calm", "concerned", "playful", "sleepy",
                 "annoyed", "curious", "satisfied", "surprised", "sad", "embarrassed",
                 "angry", "thoughtful"]
# 允许的打断条件
INTERRUPT_CONDITIONS = ["user_touch", "user_request", "agent_done", "important_event",
                        "user_woke", "hunger_high", "user_idle_long"]

_LIFE_SCHEMA = {
    "type": "object",
    "properties": {
        "activity": {"type": "string", "enum": LIFE_ACTIVITIES},
        "emotion": {"type": "string", "enum": LIFE_EMOTIONS},
        "intent": {"type": "string"},
        "duration": {"type": "number", "minimum": 0},
        "interruptible": {"type": "boolean"},
        "exit_conditions": {"type": "array", "items": {"type": "string"}},
        "next_think_in": {"type": "number", "minimum": 5},
        "dialogue_needed": {"type": "boolean"},
        "tool_needed": {"type": "boolean"},
        "reason": {"type": "string"},
        "speech_intent": {"type": "string"},   # 想说什么（给 DialogueBrain 自然化）
        "speech_level": {"type": "integer", "minimum": 0, "maximum": 5},  # 0不说..5深度
        "speech_decision": {"type": "string", "enum": ["say", "silent"]},  # §9：可说话但选择不说
        "alternative_rejected": {"type": "array", "items": {
            "type": "object",
            "properties": {"activity": {"type": "string"}, "reason": {"type": "string"}}}},  # §16 解释
    },
    "required": ["activity", "emotion", "intent", "duration", "interruptible",
                 "exit_conditions", "next_think_in", "dialogue_needed", "tool_needed", "reason"],
}


@dataclass
class LifeDecision:
    activity: str = "continue"
    emotion: str = "calm"
    intent: str = ""
    duration: float = 60.0
    interruptible: bool = True
    exit_conditions: List[str] = field(default_factory=list)
    next_think_in: float = 90.0
    dialogue_needed: bool = False
    tool_needed: bool = False
    reason: str = ""
    speech_intent: str = ""       # 想说什么（natural 化用）
    speech_level: int = 0         # 0不说..5深度
    speech_decision: str = "say"  # "say" / "silent"（§9：可说话但选择不说）
    alternative_rejected: List[Dict[str, str]] = field(default_factory=list)  # §16 解释
    # P0 Brain 候选空间约束：compliance 指标（§11）
    brain_raw_selection: str = ""       # LLM 原始选择
    validated_selection: str = ""       # 硬约束后的最终选择
    brain_invalid: bool = False         # LLM 是否跳出 allowed 空间
    allowed_space: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_continue(self) -> bool:
        return self.activity == "continue"


class LifeBrain:
    """世界感知 → 生命决策。只在 Thought Loop 周期/重要事件时被调用（低频、高价值）。"""

    def __init__(self, llm: LLMAdapter, memory_engine=None, persona: str = FURINA_PERSONA,
                 identity=None) -> None:
        self.llm = llm
        self.memory = memory_engine
        self.persona = persona
        self.identity = identity   # Character Identity（Phase 05）
        self._last_decision_time = 0.0
        self._repeat = 0   # 同活动连续出现次数（主动生活感护栏用）
        self._recent_activities: List[str] = []   # 最近活动（供 Brain 判断多样性，§3-4）
        self._budget = 12.0   # 注意力预算（任务书 §22：主动行为消耗，随时间恢复）
        self._tolerance = 50.0   # 用户对主动行为的接纳度（任务书 §23：随用户反馈自适应 0~100）
        self._relationships_memory = getattr(memory_engine, "relationship", None)

    # -------------------------------------------------- 关系驱动 + 用户自适应（任务书 §18, §23）
    def relationship_traits(self) -> dict:
        """读取长期关系（familiarity/trust/comfort/annoyance），给出对主动性的驱动。"""
        rel = self._relationships_memory
        if rel is None:
            return {"familiarity": 0, "trust": 0, "comfort": 0, "annoyance": 0}
        return {
            "familiarity": getattr(rel, "familiarity", 0),
            "trust": getattr(rel, "trust", 0),
            "comfort": getattr(rel, "comfort", 0),
            "annoyance": getattr(rel, "annoyance", 0),
        }

    def adapt_tolerance(self, user_responded: bool, was_interactive: bool) -> None:
        """按用户对最近一次主动行为的反应，调整主动接纳度（任务书 §23）。

        用户积极回应（互动/聊天）→ 接纳度↑；用户忽略/拒绝 → 接纳度↓。
        """
        if user_responded:
            self._tolerance = min(100.0, self._tolerance + 4.0)
        elif was_interactive:
            self._tolerance = max(10.0, self._tolerance - 3.0)   # 她主动但用户没理 → 降
        self._tolerance = max(10.0, min(100.0, self._tolerance))

    @property
    def tolerance(self) -> float:
        return self._tolerance

    # -------------------------------------------------- 注意力预算（任务书 §22）
    def regen_budget(self, per_sec: float = 0.02, cap: float = 12.0) -> None:
        """随时间恢复预算（被她主动行为消耗后）。"""
        self._budget = min(cap, self._budget + per_sec)

    def spend_budget(self, amount: float = 2.0) -> None:
        self._budget = max(0.0, self._budget - amount)

    @property
    def budget(self) -> float:
        return self._budget

    # -------------------------------------------------- 世界快照
    def build_snapshot(self, state, memory_engine=None, recent_events: Optional[List[str]] = None) -> dict:
        """把“世界”压缩成 Brain 能消费的快照（legacy-plan/2 §七 + 任务书 §21 互动机会评分）。"""
        snapshot = {
            "time": f"{state.clock_hour:02d}:{state.clock_minute:02d}",
            "day_phase": _day_phase(state.clock_hour),
            "self": {
                "energy": round(state.needs.energy, 1),
                "fatigue": round(state.needs.fatigue, 1),
                "hunger": round(state.needs.hunger, 1),
                "sleepiness": round(state.needs.sleepiness, 1),
                "mood": round(state.emotion.mood, 1),
                "boredom": round(state.needs.boredom, 1),
                "social_need": round(state.needs.social_need, 1),
            },
            "current_activity": {
                "name": state.life.activity or state.intent.action or "idle",
                "duration": max(0, int(time.time() - _last_change(state))),
            },
            "user": self._user_snapshot(state),
            "relationship": self.relationship_traits(),
            "environment": {"screen": True, "desktop": True},
            # 任务书 §21：互动机会评分（0~100）——Brain 判断“现在适不适合主动”
            "interaction_opportunity": self.interaction_opportunity(state, memory_engine),
        }
        # 结构化世界感知（Pre-Manual §1：canonical 快照接口 = WorldPerception.to_dict()）
        wp = getattr(state, "world", None)
        if wp is not None and hasattr(wp, "to_dict"):
            try:
                snapshot["world"] = wp.to_dict()
            except Exception:
                pass
        # 记忆上下文（Phase 07 §18：只看相关记忆 + 解释，不看整个 DB）
        if self.memory is not None and hasattr(self.memory, "retrieve"):
            try:
                context = snapshot.get("world", {}).get("user_activity", "") or ""
                mems = self.memory.retrieve(query="", limit=3, context=context or None)
                interp = self.memory.interpret(mems, context=context or "")
                snapshot["memory_context"] = {
                    "interpretation": {k: round(v, 2) for k, v in interp.items()},
                    "memories": [{"summary": m.summary or m.content, "relevance": round(m.importance, 2),
                                  "importance": round(m.importance, 2)}
                                 for m in mems[:3]],
                }
            except Exception:
                pass
        if memory_engine:
            try:
                mems = memory_engine.retrieve(query=state.life.activity or "", limit=4)
                snapshot["memories"] = [m.content for m in mems]
            except Exception:
                snapshot["memories"] = []
        if recent_events:
            snapshot["recent_events"] = recent_events[-8:]
        # 近期活动（供 Brain 判断类别多样性，抗 observe 塌缩，§3-4）
        if getattr(self, "_recent_activities", None):
            snapshot["recent_activities"] = self._recent_activities[-8:]
        # Character Identity 处境解读（Phase 05 §12：Brain 看到 appraisal，但身份已通过候选进入）
        if getattr(self, "identity", None) is not None:
            try:
                from furina.persona.character_identity import appraise
                from furina.world_perception import presence_facts
                pf = presence_facts(getattr(state, "world", None))
                ap = appraise(self.identity,
                              user_present=pf["present"],   # Pre-Manual §3：canonical 在场（unknown→False，非默认 True）
                              user_working=bool(state.user_working),
                              recent_events=list(recent_events or []),
                              user_idle=float(pf["idle_seconds"] or 0),
                              relationship_factors=_relationship_factors(state),
                              emotion_label=getattr(state.emotion, "label", "calm"))
                snapshot["character_appraisal"] = ap.as_dict()
                snapshot["character_identity"] = self.identity.name
            except Exception:
                pass
        return snapshot

    def _user_snapshot(self, state) -> dict:
        """Pre-Manual §3：用户真相块 —— 消费 canonical PresenceFacts，不再从 raw idle 占位推断。"""
        from furina.world_perception import presence_facts
        pf = presence_facts(getattr(state, "world", None))
        return {
            "presence_known": pf["known"],
            "present": pf["present"],
            "active": pf["active"],
            "idle_available": pf["known"],   # 有效 OS 空闲样本即可用（presence_facts 的 known 来源）
            "idle_seconds": None if pf["idle_seconds"] is None else int(pf["idle_seconds"]),
            "application": state.active_window_app,
            "working": bool(state.user_working),
            # 任务书 §23：用户对主动的接纳度 & 关系
            "interaction_tolerance": int(getattr(self, "_tolerance", 50)),
        }

    def _record_activity(self, activity: str) -> None:
        """记录一次被选中的活动（供多样性判断）。"""
        self._recent_activities.append(activity)
        self._recent_activities = self._recent_activities[-8:]

    def interaction_opportunity(self, state, memory_engine=None) -> int:
        """0~100：现在是不是好时机去主动接近/说话（任务书 §21）。

        用户忙+高强度→低；用户空闲→中；用户刚完成/看向她→高；加上关系亲密度与时间。
        Pre-Manual §4：**在场未知（presence_known=False）→ 0**（宁可 unknown，不要假装知道）；
        显式用户事件由上层即时反应路径处理（不依赖此机会分）。
        """
        if state is None:
            return 50
        from furina.world_perception import presence_facts
        pf = presence_facts(getattr(state, "world", None))
        if not pf["known"]:
            return 0   # 无有效 OS 空闲样本：不主动互动（未知 ≠ 可用）
        score = 50
        idle = float(pf["idle_seconds"] or 0.0)
        # 用户忙碌强度
        if state.user_working:
            score -= 28          # 工作时不主动打扰
        else:
            score += 18          # 不忙 → 可以互动
        # 用户空闲时间：刚闲下来(1-5min)是问候好时机；很久没互动则出现感下降
        if 60 <= idle <= 300:
            score += 15
        elif idle > 900:
            score -= 10          # 用户离开很久 → 与其自己待着，别刷存在感
        # 深夜 → 收敛
        if state.clock_hour >= 23 or state.clock_hour < 6:
            score -= 20
        # 关系：亲密度高更愿意、也更能接纳（任务书 §18）
        rel = self._relationships_memory or getattr(memory_engine, "relationship", None)
        if rel is not None and getattr(rel, "comfort", 0) > 60:
            score += 10
        if rel is not None and getattr(rel, "annoyance", 0) > 60:
            score -= 25          # 用户烦了 → 少打扰
        # 用户自适应（任务书 §23）：接纳度低 → 主动向少
        tol = getattr(self, "_tolerance", 50.0)
        score += int((tol - 50) * 0.4)   # 接纳度±50 → 机会±20
        # 预算（任务书 §22 注意力预算）：预算不足降主动
        budget = getattr(self, "_budget", 10.0)
        if budget <= 0:
            score -= 30
        return max(0, min(100, int(score)))

    # -------------------------------------------------- 决策
    def decide(self, *, state=None, recent_events: Optional[List[str]] = None,
               force: bool = False, candidates: Optional[list] = None) -> LifeDecision:
        """一次生命决策。LLM 不可用或出错时回退本地规则（A-13 韧性）。

        ``force=True`` 用于重要事件（用户触摸/请求/Agent 完成）时立即重决策。
        高频/节流由外层调度器 `_life_think_interval` 控制；本方法**总是**给出实质决策，
        不因“未到时间”就返回裸 continue（否则大量决策被吞掉，行为只剩 continue）。

        ``candidates``：Behavior Motivation 提供的候选行为冲动分（0..1），Brain 据此人格化选择。
        """
        snap = self.build_snapshot(state, self.memory, recent_events)
        # P0 Brain 人格吞噬修复：把 Brain 限制在**人格化 Top-N 候选空间**内。
        # Brain 负责"选择"，不负责重新创造候选 —— 只从 allowed 里选。
        allowed = self._candidate_space(candidates, top_n=getattr(self, "_brain_top_n", 4))
        if candidates:
            snap["candidates"] = candidates                 # 全部候选（Debug：Motivation 全局）
            snap["decision_candidates"] = allowed           # Brain 只能从这里选（决策空间）
        try:
            if not self.llm.is_available():
                raise RuntimeError("LLM 未配置")
            msgs = [
                LLMMessage("system", content(self.persona)),
                LLMMessage("user", content(_life_prompt(snap))),
            ]
            res = self.llm.structured(msgs, schema=_LIFE_SCHEMA, temperature=0.6)
            decision = self._coerce(res)
            # 硬约束（§6）：selected_activity 必须在 allowed 内；否则记录 invalid 并回退到 top1。
            decision = self._constrain_to_space(decision, allowed)
            # 关键：LLM 只有在“已有明确正在做的事”时才可 continue。
            if decision.is_continue:
                cur = state.life.activity if state else ""
                if not cur or cur in ("idle", ""):
                    decision = self._force_real_decision(state, snap)
                else:
                    # 有一个真实活动在持续 → 允许 continue，但把其语义转成“重复当前活动”，
                    # 好让 variety 护栏能识别 continue 造成的“卡同一种活动”并打破。
                    decision = LifeDecision(
                        activity=cur, emotion=decision.emotion, intent=decision.intent or f"继续{cur}",
                        duration=decision.duration, interruptible=decision.interruptible,
                        exit_conditions=decision.exit_conditions,
                        next_think_in=decision.next_think_in,
                        dialogue_needed=decision.dialogue_needed, tool_needed=decision.tool_needed,
                        reason=decision.reason or "继续当前", raw=decision.raw)
            # 生物需求护栏（关键）：强需求必须被回应，LLM 可选“怎么做”，但不能忽略需求。
            decision = self._apply_need_guard(state, decision)
            # Phase 13C C-R1.1：**no forced variety**。不再调用 _apply_variety 等强制多样机制。
            # 行为多样必须来自 Needs/Emotion/Motivation/Personality/Identity/Relationship/World/Memory，
            # 而非“连续 2 次就换”。重复合理行为（如 read→read）允许保留。
        except Exception as e:  # pragma: no cover - 安全回退
            log.warning("LifeBrain 决策失败，回退本地: %s", e)
            decision = self._local_decision(state)
        self._apply_schedule(decision)
        # 记录本次选中的活动（供多样性判断，§3-4）
        if getattr(decision, "activity", ""):
            self._record_activity(decision.activity)
        return decision

    # -------------------------------------------------- P0 Brain 候选空间约束（§2-§6）
    @staticmethod
    def _candidate_space(candidates: Optional[list], top_n: int = 4) -> List[dict]:
        """取**可行**候选的人格化排序 Top-N 作为 Brain 的决策空间（仅允许从这里选）。

        Feasibility 必须在 Top-N 之前（§10）：Brain 只看到可执行候选。
        保留 all_candidates（Debug）；feasible_candidates 才进入 Brain。
        """
        if not candidates:
            return []
        feasible = [c for c in candidates if c.get("feasible", True)]
        if not feasible:
            feasible = candidates   # 全部不可行时兜底（极端）
        return sorted(feasible, key=lambda c: c.get("motivation", 0), reverse=True)[:top_n]

    def _constrain_to_space(self, d: LifeDecision, allowed: List[dict]) -> LifeDecision:
        """硬约束：Brain 的 selected_activity 必须在 allowed 里；否则记录 invalid 并回退到 top1。

        绝不静默接受非法选择 —— 记录 `brain_invalid` 供 compliance 统计（§7）。
        """
        d.allowed_space = [c.get("activity") for c in allowed]
        d.brain_raw_selection = d.activity
        ok = any(c.get("activity") == d.activity for c in allowed)
        d.brain_invalid = not ok
        d.validated_selection = d.activity
        if not ok and allowed:
            # 回退到 allowed 里 motivation 最高者（不以"改 explore 为 play"掩盖问题，而是如实回退 top1）
            d.activity = allowed[0].get("activity", d.activity)
            d.validated_selection = d.activity
            log.debug("brain candidate constraint: raw=%s 不在空间, fallback=%s",
                      d.brain_raw_selection, d.activity)
        return d

    @staticmethod
    def _force_real_decision(state, snap) -> LifeDecision:
        """LLM 在该做真实决策时却只回 continue → 按世界快照本地强制给出一个合理选择。"""
        if state is None:
            return LifeDecision(activity="idle")
        n = state.needs
        late = (state.clock_hour >= 23 or state.clock_hour < 6)
        if n.hunger > 68:
            return LifeDecision(activity="eat", emotion="happy", intent="进食", duration=20, next_think_in=60)
        if (late and n.sleepiness > 60) or n.sleepiness + n.fatigue * 0.4 > 90:
            return LifeDecision(activity="sleep", emotion="sleepy", intent="恢复精力",
                                duration=480, next_think_in=240,
                                exit_conditions=["sleepiness<30", "morning", "user_touch"])
        if n.boredom > 70 and n.energy > 30:
            return LifeDecision(activity="play", emotion="playful", intent="玩耍", duration=30, next_think_in=90)
        if state.user_working:
            return LifeDecision(activity="observe_user", emotion="curious", intent="陪伴用户工作",
                                duration=180, next_think_in=120)
        if state.life.macro.value in ("resting",) or state.life.activity in ("rest",):
            return LifeDecision(activity="rest", emotion="calm", intent="休息", duration=90, next_think_in=120)
        return LifeDecision(activity="idle", emotion="calm", intent="自在修养", duration=60, next_think_in=90)

    @staticmethod
    def _apply_need_guard(state, d: LifeDecision) -> LifeDecision:
        """生物需求护栏：强需求必须被回应，**优先级高于 LLM 的普通选择**。

        LLM 可以选“怎么吃/怎么睡”，但不能在饿到 80、困到 95 时还选 observe_user/rest。
        排名：饿 > 深夜睡眠 > 疲劳休息 > 无聊玩耍；同需求时保留 LLM 的具体装态选择。
        """
        if state is None:
            return d
        n = state.needs
        late = (state.clock_hour >= 23 or state.clock_hour < 6)
        # 饿（最高优先）→ 必须吃/喝，即便 LLM 选了 rest/observe
        if n.hunger > 68:
            return LifeDecision(activity="eat", emotion="happy", intent="进食", duration=20,
                                next_think_in=60, exit_conditions=["hunger<50"])
        # 深夜且困 → 必须睡
        if late and n.sleepiness > 55:
            return LifeDecision(activity="sleep", emotion="sleepy", intent="恢复精力",
                                duration=480, next_think_in=240,
                                exit_conditions=["sleepiness<30", "morning", "user_touch"])
        # 疲劳很高 → 休息
        if n.sleepiness + n.fatigue * 0.4 > 82 and d.activity in ("idle", "observe_user", "play"):
            return LifeDecision(activity="rest", emotion="sleepy", intent="休息一下", duration=120,
                                next_think_in=150, exit_conditions=["sleepiness<40"])
        # 极无聊且精力够 → 玩/读
        if n.boredom > 78 and n.energy > 30 and d.activity in ("idle", "observe_user"):
            return LifeDecision(activity="play", emotion="playful", intent="找点乐子", duration=30,
                                next_think_in=90)
        return d

    # -------------------------------------------------- 执行计划调度
    def _apply_schedule(self, d: LifeDecision) -> None:
        """记录下次重决策时间，**不做 8..45 clamp**（Phase 13C C-R1.1）。

        next_think 的安全 clamp 归属**唯一 owner = Scheduler._life_think_interval**；
        LifeBrain 只记录真实值、透传给调用方，不再私自压到 45s。
        （LLM 给的 60000/1800 等极端值由 Scheduler 的统一安全界处理，避免“睡死”也避免“节拍器”。）
        """
        self._next_think_at = time.monotonic() + float(d.next_think_in)
        self._last_decision_time = time.monotonic()
        # 不再回写 d.next_think_in（保留真实语义，让 Scheduler 做唯一安全 clamp）

    def next_think_in(self) -> float:
        return max(5.0, getattr(self, "_next_think_at", 0) - time.monotonic())

    # -------------------------------------------------- 结构化校验
    @staticmethod
    def _coerce(raw: Dict[str, Any]) -> LifeDecision:
        activity = raw.get("activity", "idle")
        if activity not in LIFE_ACTIVITIES:
            activity = "idle"
        emotion = raw.get("emotion", "calm")
        if emotion not in LIFE_EMOTIONS:
            emotion = "calm"
        return LifeDecision(
            activity=activity,
            emotion=emotion,
            intent=str(raw.get("intent", "")),
            duration=max(0.0, float(raw.get("duration", 60))),
            interruptible=bool(raw.get("interruptible", True)),
            exit_conditions=list(raw.get("exit_conditions", []) or []),
            next_think_in=max(5.0, float(raw.get("next_think_in", 90))),
            dialogue_needed=bool(raw.get("dialogue_needed", False)),
            tool_needed=bool(raw.get("tool_needed", False)),
            reason=str(raw.get("reason", "")),
            speech_intent=str(raw.get("speech_intent", "")),
            speech_level=int(raw.get("speech_level", 0) or 0),
            speech_decision=str(raw.get("speech_decision", "say") or "say"),
            alternative_rejected=list(raw.get("alternative_rejected", []) or []),
            raw=raw,
        )

    # -------------------------------------------------- 本地规则 fallback（A-13：无 LLM 仍生活，但只是保底）
    def _apply_variety(self, state, d: LifeDecision) -> LifeDecision:
        """主动生活感：避免连续重复同一活动（任何非生存活动都适用）。

        维护“同活动连续出现次数”，连续 2 次同一非生存活动（或发呆型）就切换到另一个**有生气的活动**，
        让芙宁娜“会自己找事情做、会主动找人聊天”，而不是卡在某个动作上。
        强需求（eat/sleep/drink）不受影响。
        """
        # 只有「生存级」长行为（eat/sleep）不受 variety 打断；drink/play/观察等都应打破重复。
        if state is None or d.activity in ("eat", "sleep"):
            self._repeat = 0
            return d
        cur = (state.life.activity or state.intent.action or "idle")
        if d.activity == cur:
            self._repeat = getattr(self, "_repeat", 0) + 1
        else:
            self._repeat = 1
        # 连续 2 次同一活动 → 打破，更快“自己找事做”；发呆型(observe)也要出现 2 次才打破
        stuck = self._repeat >= 2
        dazy = d.activity in ("idle", "observe_user", "observe_work", "watch_user") and self._repeat >= 2
        if not (stuck or dazy):
            return d
        # 切换到主动/社交/自己的事（任务书 §22 预算 + §18 关系 + §23 自适应）
        import random
        budget = getattr(self, "_budget", 12.0)
        rel = self.relationship_traits()
        annoy = rel.get("annoyance", 0)
        comfort = rel.get("comfort", 0)
        tol = getattr(self, "_tolerance", 50.0)
        # 用户烦了 / 接纳度低 / 信任低 → 倾向自主、少打扰
        social_ok = budget >= 3 and tol >= 30 and annoy < 60
        if state.user_working:
            cand = ["approach_user", "observe_user", "watch_user", "offer_help", "comment"]
            if getattr(state, "_user_working_seconds", 0) > 600:
                cand = ["offer_help", "comment", "approach_user"]
            if not social_ok:
                cand = ["observe_user", "watch_user"]   # 少打扰，只看
        else:
            if not social_ok:
                cand = SELF_ACTIVITIES
            else:
                # 关系好 → 更多社交；一般 → 半自主半社交
                if comfort > 60:
                    cand = SOCIAL_ACTIVITIES + SELF_ACTIVITIES
                else:
                    cand = SELF_ACTIVITIES + SOCIAL_ACTIVITIES
                    if random.random() < 0.5:
                        cand = SOCIAL_ACTIVITIES
        cand = [x for x in cand if x != d.activity] or cand
        pick = random.choice(cand)
        self._repeat = 1
        # 主动社交/接近用户 → 消耗预算
        if pick in SOCIAL_ACTIVITIES:
            self._budget = max(0.0, self._budget - (3 if pick in ("talk", "invite_user", "offer_help") else 2))
        emo = {"talk": "playful", "approach_user": "happy", "play": "playful", "greet": "happy",
               "walk": "curious", "observe_user": "curious", "read": "thoughtful", "drink": "calm",
               "tidy": "proud", "think": "thoughtful", "daydream": "calm", "stretch": "sleepy",
               "explore": "curious", "look_around": "curious", "play_with_object": "playful",
               "watch_user": "curious", "offer_help": "concerned", "comment": "curious"}.get(pick, "calm")
        cn = {"talk": "去搭话", "approach_user": "过去陪", "play": "找乐子", "greet": "打个招呼",
              "walk": "溜达", "observe_user": "看看", "read": "看书", "drink": "喝点茶",
              "tidy": "整理一下", "think": "想点事", "daydream": "发会儿呆", "stretch": "伸个懒腰",
              "explore": "探索桌面", "look_around": "四处看看", "play_with_object": "玩会儿小东西",
              "watch_user": "看你一眼", "offer_help": "想帮帮忙", "comment": "说点什么"}.get(pick, "活动")
        return LifeDecision(activity=pick, emotion=emo, intent=f"主动{cn}", duration=30,
                            next_think_in=12, dialogue_needed=(pick in SPEAKABLE))

    # -------------------------------------------------- 本地规则 fallback（A-13：无 LLM 仍生活，但只是保底）
    @staticmethod
    def _local_decision(state) -> LifeDecision:
        if state is None:
            return LifeDecision(activity="idle")
        n = state.needs
        hour = state.clock_hour
        late = (hour >= 23 or hour < 6)
        sleepy = n.sleepiness + n.fatigue * 0.4
        if (late and sleepy > 70) or sleepy > 110:
            return LifeDecision(activity="sleep", emotion="sleepy", intent="恢复精力",
                                duration=600, next_think_in=300,
                                exit_conditions=["sleepiness<30", "morning", "user_touch"])
        if n.hunger > 68:
            return LifeDecision(activity="eat", emotion="happy", intent="进食",
                                duration=20, next_think_in=60)
        if n.boredom > 70 and n.energy > 30:
            return LifeDecision(activity="play", emotion="playful", intent="玩耍",
                                duration=30, next_think_in=90)
        if state.user_working:
            return LifeDecision(activity="observe_user", emotion="curious", intent="陪伴用户工作",
                                duration=180, next_think_in=120)
        return LifeDecision(activity="idle", emotion="calm", intent="自在修养",
                            duration=60, next_think_in=90)


def _last_change(state) -> float:
    """最近一次活动开始时间（简化：用 Brain 未维护时回退到 0）。"""
    return getattr(state, "_activity_started_at", time.time())


def _relationship_factors(state) -> dict:
    """从 state.relationship 取归一化 0..1 因子（C-R2 §8：只经 canonical relationship_factors()，不假设已归一化）。"""
    rel = getattr(state, "relationship", None)
    from furina.relationship.engine import relationship_factors
    return relationship_factors(rel)


def _day_phase(hour: int) -> str:
    if 5 <= hour < 9:
        return "morning"
    if 9 <= hour < 12:
        return "morning"
    if 12 <= hour < 14:
        return "noon"
    if 14 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def _life_prompt(snap: dict) -> str:
    """把世界快照变成 Brain 的一次性提问（紧凑；legacy-plan/8 §10 拆 prompt，不塞巨型提示词）。

    任务书 §3/§9/§10：给 Brain 足够自主行为空间 + 主动语言机会 + 语言必须有理由（非 AI 套话）。
    """
    import json
    s = json.dumps(snap, ensure_ascii=False)
    avail = ", ".join(LIFE_ACTIVITIES)
    # 候选冲动分（Behavior Motivation）：Brain 应据此人格化选择，而非随意挑
    cand_text = ""
    # P0：只用 Top-N 决策空间（decision_candidates），不让 Brain 看到大量低分候选而重新排序
    cands = snap.get("decision_candidates") or snap.get("candidates")
    if cands:
        cand_text = "\n**允许的行为候选（你只能从这些里选一个，已按人格化动机排序）**：\n" + \
                    "\n".join(f"  {c['activity']:16} mot={c['motivation']:.2f} "
                              f"fit={c.get('personality_fit',0):.2f} [{c.get('category','')}] "
                              f"why={','.join(c.get('why',[]))}" for c in cands) + "\n"
    debug_cands = snap.get("candidates")
    if debug_cands and len(debug_cands) > len(cands or []):
        cand_text += f"\n（其它候选仅供参考：{', '.join(c['activity'] for c in debug_cands[len(cands or []):8])}）\n"
    # 人格契约束（§18）：由候选的 personality_fit 自动推导"你这性格更偏好哪类行为"，供 Brain 遵守。
    if cands:
        fit_rank = sorted(cands, key=lambda c: c.get("personality_fit", 0), reverse=True)
        top_fit = [c["activity"] for c in fit_rank[:3] if c.get("personality_fit", 0) >= 0.5]
        if top_fit:
            cand_text += (f"\n**人格契约**：你的性格最契合的行为是 {', '.join(top_fit)}"
                          f"（personality_fit 最高）。在动机相当的候选间，优先选契合度更高的。\n")
    # 近期行为（供 Brain 判断多样性，避免同一类连续）
    recent = snap.get("recent_activities", [])
    recent_text = f"\n近期行为：{', '.join(recent[-6:]) if recent else '（无，刚从休息醒来）'}\n"
    return (
        "你是住在用户电脑里的芙宁娜，一个骄傲、爱表现、小任性但有陪伴欲、有自己的小日子的桌面精灵。\n"
        "根据世界快照，决定**你自己此刻最想做的下一件事**。你是一个有生活的人，不是监视器、不是回话机器人。\n"
        f"世界快照：{s}\n{cand_text}{recent_text}\n"
        f"可选的活动(activity)：{avail}\n\n"
        "决策原则（务必遵守）：\n"
        "⑪ **必须采用候选的动机与人格契合度排名**：候选已按 motivation 排序，**第一个就是你人格+需求最想做的**。"
        "请**优先选排名靠前**的候选（尤其 ranked #1 的人格契合候选）。若排名第一的是 play 而你的人格偏玩，就选 play，"
        "不要因为它不如 explore 看起来有诗意就跳过它。personality_fit 高 = 这正是你这性格会做的。\n"
        "① **你不是在找“最安全的行为”，而是在选“此刻最有意义的下一件事”**。\n"
        "② **observe_user / observe_work 是一种具体行为，不是默认/兜底**。它只在“你确实想看看用户在干嘛”"
        "（用户刚工作/有变化）时才选。若它就是此刻你最想做的，选它也没关系。\n"
        "③ **用户没操作 ≠ 什么都不做**。若用户不在/不忙，优先做**自己的事**：read 看书、"
        "drink 喝茶、tidy 整理、think 想事情、daydream 发呆、stretch 伸懒腰、explore 探索、play 玩耍、wander 溜达。\n"
        "④ **不要为了“看起来多样”而换行为**。每个决策只依**此刻你的状态（需求/情绪/动机/关系/记忆/世界）**"
        "选那个**真正想做/该做**的。连续做同一件事若符合此时状态，是允许的（例如你正读得入迷就继续读）。\n"
        "⑤ 用户在工作：可 observe_work(看他在忙什么) 或 offer_help(想帮忙)，也可以继续做自己的事，取决于你此刻想怎样。\n"
        "⑥ 饿(hunger>68)就 eat；深夜/很困就 sleep/rest；无聊(boredom>70)就 play/explore/read；精力低就 rest/stretch。\n"
        "⑦ **主动说话要看机会**：候选里 talk 的 motivation 反映机会。若它有真实原因(用户完成某事/兴趣点/"
        "想搭话/时机合适)，可 dialogue_needed=true 并把 speech_intent 写一句**自然、有具体所指**的话"
        "（别用“你好呀/需要帮忙吗”套话）。若只是没话可说，就 speech_decision=\"silent\"（有想法但觉得现在不说更合适）。\n"
        "⑧ 睡眠/长行为给较大 duration 和合理 next_think_in，**必须写 exit_conditions**（morning/user_touch/"
        "sleepiness<30），这样她会醒而不是永远睡。\n"
        "⑨ 保持人格稳定但允许情绪/状态自然变化。\n"
        "⑩ 需要操作电脑时 tool_needed=true。\n"
        "只输出一个 JSON 对象："
        '{"activity":"...","emotion":"...","intent":"一句话中文","duration":秒,"interruptible":true,'
        '"exit_conditions":["..."],"next_think_in":秒,"dialogue_needed":false,"tool_needed":false,'
        '"reason":"简短理由","speech_intent":"想说什么事","speech_level":0,'
        '"speech_decision":"say或silent","alternative_rejected":[{"activity":"...","reason":"..."}]}. '
        "除 JSON 外不要任何文字。"
    )
