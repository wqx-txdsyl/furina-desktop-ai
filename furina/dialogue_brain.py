"""DialogueBrain —— 「语言」：只负责“既然我要表达这个意图，作为芙宁娜应该怎么说”。

三脑架构：与 LifeBrain/Tool Agent 严格隔离。
- 不决定：要不要说、何时说、要不要走/打断/睡觉（那是 LifeBrain）。
- 不决定：怎么操作电脑（那是 Tool Agent）。
- 只做：给一个意图 + 上下文 + 人格，产出符合芙宁娜口吻的一句话/一段话。
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from furina.core import get_logger
from furina.llm import LLMAdapter, LLMMessage, content
from furina.persona import FURINA_PERSONA

log = get_logger("dialogue_brain")

_DIALOGUE_SCHEMA = {
    "type": "object",
    "properties": {
        "speech": {"type": "string"},
        "emotion_hint": {"type": "string"},
    },
    "required": ["speech"],
}


class DialogueBrain:
    def __init__(self, llm: LLMAdapter, persona: str = FURINA_PERSONA, identity=None,
                 timeout: float | None = None) -> None:
        self.llm = llm
        self.persona = persona
        self.identity = identity
        # B1：单次生成的有界超时（None = 仅靠 adapter 的 httpx timeout；调用方可按 turn 覆盖）
        self._timeout = timeout
        # 表达引擎（确定性：ShouldSpeak/Mode/Intent/Strategy；不占决策）
        from furina.dialogue import ExpressionEngine, DialogueValidator
        self.expression = ExpressionEngine(identity)
        self.validator = DialogueValidator()
        # 短期重复控制（§40）
        self._recent_acts: List[str] = []
        self._recent_modes: List[str] = []
        # B3：近期**已展示**的直接回复（surface 语言重复监测，bounded；只记 direct）
        self._recent_surfaced: List[str] = []
        self._recent_surfaced_limit = 8
        # R2.2 FINAL：近期 opening styles（防"哎呀"塌缩；跨直接对话轮）
        self._recent_openings: List[str] = []
        # R2.2.1 §7：semantic topic / open referent（来自用户输入语义，非 Furina 回复文本）
        self._last_semantic_topic: str = ""
        self._last_open_referent: str = ""
        # Phase 13C §24-26：有界短期对话上下文（内存，非数据库）
        self._history: List[Dict[str, Any]] = []
        self._history_limit = 8
        # "本神" Micro-Calibration Gate（Phase 10：情境化，非强制，短生命周期，不进 Memory）
        from furina.dialogue.god_calibration import GodCalibrationGate
        self.god_gate = GodCalibrationGate()
        # Phase 13 终审 §9：最近一次校验失败（可观察对话失败路径；空 = 无失败）
        self.last_validation_failure: List[str] = []
        # B1：最近一次直接回合的失败原因（llm_unavailable/generation_empty/generation_exception/
        # generation_timeout/validation_twice_invalid/god_gate_suppressed/worker_exception）
        self.last_failure_reason: str = ""
        # Phase 13 终审 §8：内部安全锁（RLock）—— 不是排序机制；
        # B1：只包确定性阶段（appraise/prompt/历史提交），**不包 LLM 调用**（慢/挂起不堵其它回合）。
        import threading
        self._say_lock = threading.RLock()
        # FINAL-R1 §4.1：**直接 lane 显式 FIFO** —— 用户消息在入口分配递增 seq，history 提交严格按 seq 排序
        # （后到者等待前序 seq 完成，与锁获取顺序无关）。B1：**只有 DIRECT_USER_TURN 使用此序号空间**；
        # ambient/feed/interaction/agent 走独立 ambient 序号空间，绝不占用 direct 序号、不堵 direct lane。
        self._ingress_seq = 0
        self._ingress_lock = threading.Lock()
        self._hist_cond = threading.Condition()
        self._last_pushed_seq = 0
        # FINAL-R1 §4.2：对话通道语义 —— 只有 DIRECT_USER_TURN 进入直接对话历史；
        # 自主/喂食/Agent/互动台词进 ambient 池（作为近期上下文事实，不当孤儿 Furina 回合）。
        self._ambient: List[Dict[str, Any]] = []
        self._ambient_limit = 8
        # H1 §6：直接回合的暂存 user 文本（存在可显示回复时才原子成对提交）
        self._pending_direct_user: Optional[tuple] = None
        # H1 §5：**direct turn FIFO 门**（生成锁之前）—— 前序 direct turn 未完成时，后续不得进入生成。
        # 防止锁反转死锁：turn2 抢到 _say_lock 后等 turn1 槽位，而 turn1 等不到锁。
        self._fifo_cond = threading.Condition()
        self._last_done_seq = 0
        # B1：**ambient lane 独立 FIFO 门 + 序号**（ambient 回合间保序；不占 direct 序号，不堵 direct）
        self._ambient_seq = 0
        self._ambient_seq_lock = threading.Lock()
        self._ambient_fifo_cond = threading.Condition()
        self._ambient_done_seq = 0

    # -------------------------------------------------- H1 §5：direct turn FIFO 门（ticket/Condition）
    def _gate_wait(self, seq: int) -> None:
        """（direct lane）进入生成前等待：必须等到所有前序 direct turn（seq-1）完成。"""
        with self._fifo_cond:
            while seq != self._last_done_seq + 1:
                self._fifo_cond.wait(timeout=1.0)

    def _gate_release(self, seq: int) -> None:
        """（direct lane）本 turn 完成（含失败/沉默/校验失败）→ 放行下一个 direct turn。"""
        with self._fifo_cond:
            self._last_done_seq = seq
            self._fifo_cond.notify_all()

    # -------------------------------------------------- B1：ambient lane FIFO 门 + 序号
    def _ambient_next_seq(self) -> int:
        with self._ambient_seq_lock:
            self._ambient_seq += 1
            return self._ambient_seq

    def _ambient_gate_wait(self, seq: int) -> None:
        with self._ambient_fifo_cond:
            while seq != self._ambient_done_seq + 1:
                self._ambient_fifo_cond.wait(timeout=1.0)

    def _ambient_gate_release(self, seq: int) -> None:
        with self._ambient_fifo_cond:
            self._ambient_done_seq = seq
            self._ambient_fifo_cond.notify_all()

    # -------------------------------------------------- FINAL-R1 §4.1：显式 FIFO 入口
    def _next_seq(self) -> int:
        with self._ingress_lock:
            self._ingress_seq += 1
            return self._ingress_seq

    def _push_ordered(self, seq: int, role: str, text: str) -> None:
        """按 seq 严格排序提交直接对话历史（Condition 等待前序完成；stale seq 幂等丢弃）。"""
        if not text:
            return
        with self._hist_cond:
            if seq <= self._last_pushed_seq:
                return   # 已被消费/跳过（陈旧 push，幂等丢弃）
            while seq != self._last_pushed_seq + 1:
                self._hist_cond.wait(timeout=1.0)
            self._history.append({"role": role, "text": str(text), "seq": seq,
                                  "channel": "DIRECT_USER_TURN"})
            self._history = self._history[-self._history_limit:]
            self._last_pushed_seq = seq
            self._hist_cond.notify_all()

    def _skip_slots(self, slots) -> None:
        """占用（跳过）指定的历史槽位，保持 seq 严格连续（幂等：已消费的槽不再等待）。

        环境回合/沉默/校验失败等不写直接历史的回合，也必须推进本回合槽位（2s-1, 2s），
        否则后续直接回合会永远等待不存在的 seq。
        """
        with self._hist_cond:
            for s in slots:
                if s <= self._last_pushed_seq:
                    continue          # 该槽已被实际推送消费
                while s != self._last_pushed_seq + 1:
                    self._hist_cond.wait(timeout=1.0)
                self._last_pushed_seq = s
            self._hist_cond.notify_all()

    def push_history(self, role: str, text: str, seq: Optional[int] = None) -> None:
        """短期对话上下文（bounded）。只存发言，不存系统 prompt（显式 FIFO 提交）。"""
        if seq is None:
            seq = self._next_seq()
        self._push_ordered(seq, role, text)

    def push_ambient(self, channel: str, text: str) -> None:
        """FINAL-R1 §4.2：环境通道台词（不进入直接对话历史，避免孤儿回合）。"""
        if not text:
            return
        self._ambient.append({"channel": channel, "text": str(text)})
        self._ambient = self._ambient[-self._ambient_limit:]

    def recent_turns(self, n: int = 4) -> List[Dict[str, Any]]:
        return list(self._history[-n:])

    def recent_ambient(self, n: int = 4) -> List[Dict[str, Any]]:
        """近期环境台词（AMBIENT/FEED/AGENT/INTERACTION），供上下文事实，不混入直接历史。"""
        return list(self._ambient[-n:])

    # -------------------------------------------------- Phase 13C §19-20：确定性 DialogueAct 路由
    def classify_act(self, user_text: str = "") -> str:
        """高置信地把常见用户输入路由到有意义的 act（不新增 LLM）。默认 COMMENT。

        Phase 13 终审 §9：**边界/拒绝语义优先于标点式疑问检测** ——
        "你能别烦我吗？" 必须路由到 DECLINE，而不是被 "吗" 抢成 RESPONSE_TO_QUESTION。
        """
        import re
        t = (user_text or "").strip()
        if not t:
            return "COMMENT"
        # 0) 拒绝/边界（最高优先）
        if re.search(r"别烦|别吵|走开|别打扰|要忙|没空|安静|离我远点|别烦我|先别理我", t):
            return "DECLINE"
        if re.search(r"[?？]|吗|呢|干嘛|什么|几|哪|是不是|怎么样", t):
            return "RESPONSE_TO_QUESTION"
        if re.search(r"累|难过|伤心|压力|辛苦|烦死|不开心", t):
            return "COMFORT"
        if re.search(r"可爱|好看|喜欢|棒|厉害|真好|爱你|厉害呀", t):
            return "REACT"
        if re.search(r"谢谢|感谢|多谢", t):
            return "REFLECT"
        return "COMMENT"

    # -------------------------------------------------- H1-FINAL §2：owner 入队序号（用户输入顺序）
    def reserve_turn(self) -> int:
        """owner 线程在**用户输入入口**（submit_user_message）预留 turn 序号。

        FIFO 的身份必须来自用户入队顺序，而不是 worker 执行时序（否则 worker2 先进入 say()
        会拿到更小的 seq，FIFO 忠实保存了错误顺序）。
        """
        return self._next_seq()

    # -------------------------------------------------- Phase 13 终审 §8 / FINAL-R1 §4：FIFO 串行入口
    def say(self, *, intent: str = "", emotion: str = "", user_text: str = "",
            context: Optional[str] = "", memories: Optional[List[str]] = None,
            world: Optional[dict] = None, activity: str = "",
            relationship: Optional[dict] = None, memory_interp: Optional[dict] = None,
            user_initiated: bool = False, task_mode: bool = False,
            solitude: bool = False, user_present: bool = True,
            presence_known: bool = True,   # Pre-Manual §8：接受 canonical 在场（快照携带）
            channel: str = "DIRECT_USER_TURN",
            ingress_seq: Optional[int] = None,
            timeout: Optional[float] = None,
            deadline: Optional[float] = None,
            interaction: str = "",         # R2.1 P1-2：互动事实 kind（petting/poke/drag/click）
            agent_state: str = "",         # R2.1 P1-1：当前 Agent 生命周期状态
            agent_task: str = "",
            agent_facts: Optional[dict] = None) -> Optional[str]:   # R2.2.1 §5：AgentReportFacts
        """生成一句符合人格、有真实上下文的中文台词，或 None（沉默，§5/§39）。

        R1.1-6：公开 consumer API 保持不变（返回 speech 或 None）；
        需要逐调用失败原因请用 `say_with_result()`（内部 result API）。
        R1.1-3：`deadline`（monotonic 绝对时刻）= **整个 turn 的总预算**（attempt+retry 共享）；
        `timeout` = 单次生成的上界（向后兼容）；两者都未给 → 默认 self._timeout。
        """
        return self._say_dispatch(intent=intent, emotion=emotion, user_text=user_text,
                                  context=context, memories=memories, world=world,
                                  activity=activity, relationship=relationship,
                                  memory_interp=memory_interp, user_initiated=user_initiated,
                                  task_mode=task_mode, solitude=solitude, user_present=user_present,
                                  presence_known=presence_known, channel=channel,
                                  ingress_seq=ingress_seq, timeout=timeout,
                                  deadline=deadline, interaction=interaction,
                                  agent_state=agent_state, agent_task=agent_task,
                                  agent_facts=agent_facts)["speech"]

    def say_with_result(self, *, intent: str = "", emotion: str = "", user_text: str = "",
                        context: Optional[str] = "", memories: Optional[List[str]] = None,
                        world: Optional[dict] = None, activity: str = "",
                        relationship: Optional[dict] = None, memory_interp: Optional[dict] = None,
                        user_initiated: bool = False, task_mode: bool = False,
                        solitude: bool = False, user_present: bool = True,
                        presence_known: bool = True,
                        channel: str = "DIRECT_USER_TURN",
                        ingress_seq: Optional[int] = None,
                        timeout: Optional[float] = None,
                        deadline: Optional[float] = None,
                        interaction: str = "",
                        agent_state: str = "",
                        agent_task: str = "",
                        agent_facts: Optional[dict] = None) -> dict:
        """内部 result API（R1.1-6/R2.1 P0-3）：返回 {"speech","failure_reason",
        "validation_issues","hard_issues","soft_issues"}。

        每个调用返回**自己回合**的失败原因（per-call result），不依赖可能被并发 ambient
        回合改写的共享 last_failure_reason/last_validation_failure（后者保留为诊断/兼容）。
        """
        return self._say_dispatch(intent=intent, emotion=emotion, user_text=user_text,
                                  context=context, memories=memories, world=world,
                                  activity=activity, relationship=relationship,
                                  memory_interp=memory_interp, user_initiated=user_initiated,
                                  task_mode=task_mode, solitude=solitude, user_present=user_present,
                                  presence_known=presence_known, channel=channel,
                                  ingress_seq=ingress_seq, timeout=timeout,
                                  deadline=deadline, interaction=interaction,
                                  agent_state=agent_state, agent_task=agent_task,
                                  agent_facts=agent_facts)

    def _say_dispatch(self, *, intent: str = "", emotion: str = "", user_text: str = "",
                      context: Optional[str] = "", memories: Optional[List[str]] = None,
                      world: Optional[dict] = None, activity: str = "",
                      relationship: Optional[dict] = None, memory_interp: Optional[dict] = None,
                      user_initiated: bool = False, task_mode: bool = False,
                      solitude: bool = False, user_present: bool = True,
                      presence_known: bool = True,
                      channel: str = "DIRECT_USER_TURN",
                      ingress_seq: Optional[int] = None,
                      timeout: Optional[float] = None,
                      deadline: Optional[float] = None,
                      interaction: str = "",
                      agent_state: str = "",
                      agent_task: str = "",
                      agent_facts: Optional[dict] = None) -> dict:
        """B1/R1.1-3 lane 分发：direct 与 ambient 独立序号 + 独立门；总预算 deadline 传递。

        B1/R1.2-2（评审基线）**通道分 lane**：
          - DIRECT_USER_TURN：direct lane —— 生产路径由 DirectDialogueQueue 串行 authority
            驱动（turn_id = 用户 ingress identity），brain seq 在真正执行时由 _next_seq()
            分配（与执行顺序一致）；测试/外部直调可显式传 ingress_seq（仍受 direct gate 保序）。
            直接历史成对提交；失败有可观察终态。
          - AMBIENT_AUTONOMOUS / FEED_REACTION / INTERACTION_REACTION / AGENT_REPORT：
            **独立 ambient lane**（独立序号 + 独立门）—— 慢/挂起的 ambient 回合
            **永不占用 direct 序号、永不阻塞 direct lane**；ambient 可被节流/丢弃。
        R1.1-3：deadline 是**整个 turn**（attempt + 至多一次 retry）共享的总预算，
        validator/retry 不重置预算；任何失败都释放本回合并推进 FIFO。
        """
        eff_timeout = timeout if timeout is not None else self._timeout
        if channel == "DIRECT_USER_TURN":
            seq = ingress_seq if ingress_seq is not None else self._next_seq()
            self._gate_wait(seq)            # direct 门 —— 前序 direct turn 完成前不进入生成
            try:
                speech, reason, issues, hard, soft = self._say_impl(
                    intent=intent, emotion=emotion, user_text=user_text,
                    context=context, memories=memories, world=world,
                    activity=activity, relationship=relationship,
                    memory_interp=memory_interp, user_initiated=user_initiated,
                    task_mode=task_mode, solitude=solitude, user_present=user_present,
                    presence_known=presence_known, channel=channel, _seq=seq,
                    _lane="direct", timeout=eff_timeout, deadline=deadline,
                    interaction=interaction, agent_state=agent_state, agent_task=agent_task,
                    agent_facts=agent_facts)
                return {"speech": speech, "failure_reason": reason,
                        "validation_issues": issues, "hard_issues": hard, "soft_issues": soft}
            finally:
                # 无论成功/沉默/校验失败，本回合槽位（2s-1, 2s）必须推进，
                # 否则后续 direct 回合会死锁等待不存在的 seq（幂等：已消费的槽自动跳过）。
                try:
                    self._skip_slots((seq * 2 - 1, seq * 2))
                finally:
                    self._gate_release(seq)   # 本 turn 完成 → 放行下一个（失败/沉默也推进 FIFO）
        # B1：ambient lane（独立序号空间，绝不占用 direct 序号；ambient 间保序）
        aseq = self._ambient_next_seq()
        self._ambient_gate_wait(aseq)
        try:
            speech, reason, issues, hard, soft = self._say_impl(
                intent=intent, emotion=emotion, user_text=user_text,
                context=context, memories=memories, world=world,
                activity=activity, relationship=relationship,
                memory_interp=memory_interp, user_initiated=user_initiated,
                task_mode=task_mode, solitude=solitude, user_present=user_present,
                presence_known=presence_known, channel=channel, _aseq=aseq,
                _lane="ambient", timeout=eff_timeout, deadline=deadline,
                interaction=interaction, agent_state=agent_state, agent_task=agent_task,
                agent_facts=agent_facts)
            return {"speech": speech, "failure_reason": reason,
                    "validation_issues": issues, "hard_issues": hard, "soft_issues": soft}
        finally:
            self._ambient_gate_release(aseq)

    def _say_impl(self, *, intent: str = "", emotion: str = "", user_text: str = "",
                  context: Optional[str] = "", memories: Optional[List[str]] = None,
                  world: Optional[dict] = None, activity: str = "",
                  relationship: Optional[dict] = None, memory_interp: Optional[dict] = None,
                  user_initiated: bool = False, task_mode: bool = False,
                  solitude: bool = False, user_present: bool = True,
                  presence_known: bool = True,
                  channel: str = "DIRECT_USER_TURN", _seq: Optional[int] = None,
                  _aseq: Optional[int] = None, _lane: str = "direct",
                  timeout: Optional[float] = None,
                  deadline: Optional[float] = None,
                  interaction: str = "",
                  agent_state: str = "",
                  agent_task: str = "",
                  agent_facts: Optional[dict] = None) -> tuple:
        """say() 的实现体（由 lane 入口包裹）→
        (speech, failure_reason, validation_issues, hard_issues, soft_issues)。

        B1（评审基线 0402e7f）三阶段：
          A. 锁内确定性准备（appraise / act 路由 / god 校准 / examples / prompt / 暂存 user）
          B. **无锁**有界 LLM 生成 + 确定性校验 + 至多一次 retry（带校验反馈）
          C. 锁内确定性收尾（god gate / 表面语言跟踪 / 历史成对提交）
        LLM 调用**不持 _say_lock** —— ambient 回合慢/挂起时，direct 回合无需等锁即可生成；
        R1.1-3：`deadline` = 本 turn 总预算（attempt + retry 共享，不重置）；
        R1.1-6：失败原因**随本调用返回**（per-call result），共享 last_failure_reason 仅诊断。
        R2.1 P0-3：HARD（身份/事实/结构）失败 DirectTurn；仅 SOFT（风格）→ retry 质量后
        **surface**（soft_quality 记录，不失败）——“一句话不够漂亮”不得变成系统错误/沉默。
        """
        # ================= Phase A：确定性表达准备（锁内，快） =================
        constraint = None
        with self._say_lock:
            # 1) Expression Appraisal（确定性）：ShouldSpeak / Mode / Intent / Strategy
            app = self.expression.appraise(
                emotion=emotion, intent=intent, user_text=user_text,
                relationship=relationship, world=world, memory=memory_interp,
                activity=activity, user_initiated=user_initiated,
                task_mode=task_mode, solitude=solitude, user_present=user_present,
                user_working=bool((world or {}).get("user_working", False)),
                recent_dialogue=self._recent_acts)
            # 2) Should Speak? —— Silence 是正式行为（§5）
            if not app.should_speak:
                return (None, "should_speak_false", [], [], [])
            # Phase 13C §19-20：用户发起的对话用确定性 act 路由覆盖
            if user_text:
                app.dialogue_act = self.classify_act(user_text)
            # 2b) "本神" 情境化校准（Phase 10）：只改 prompt 引导，不强制；给出语境偏好
            god_cal = self.god_gate.calibrate(mode=app.mode, dialogue_act=app.dialogue_act,
                                              emotion=emotion, user_text=user_text)
            # 3) 相关 synthetic examples（Top-K=3）
            examples = self._select_examples(app, emotion, activity=activity, user_text=user_text)
            # ============ R2.2 FINAL：PersonaPlan + UserTurnFrame + Autobiographical ============
            # 确定性语义规划（不新增 LLM）：理解用户这一句 → 决定怎么回应。
            plan, auto_guide = self._plan_turn(
                user_text=user_text, app=app, emotion=emotion,
                relationship=relationship, activity=activity,
                user_initiated=user_initiated, task_mode=task_mode,
                agent_state=agent_state, agent_task=agent_task)
            # 4) 生成 prompt。C-R1.3.1：history 只含**当前轮之前**的发言，当前 user_text 单独附一次
            hist = self.recent_turns(4)
            prompt = _dialogue_prompt_v2(app, intent=intent, emotion=emotion,
                                         user_text=user_text, context=context,
                                         memories=memories, world=world,
                                         examples=examples, person=self.persona,
                                         activity=activity, history=hist,
                                         interaction=interaction,
                                         agent_state=agent_state, agent_task=agent_task,
                                         plan=plan, auto_guide=auto_guide,
                                         agent_facts=agent_facts)
            # R2.1 P1-5：用户显式格式/回答约束（优先级高于 persona style，保守确定性提取）
            if user_text:
                m = re.search(r"只能回答([^或，,。！？\s]{1,6})(?:或者|或)([^。！？\s]{1,6})", user_text)
                if m:
                    constraint = (m.group(1).strip(), m.group(2).strip())
                    prompt += (f"\n（用户明确格式约束：只能回答“{constraint[0]}”或"
                               f"“{constraint[1]}”。严格只输出这两个字之一，不要任何解释。）")
            if user_text and channel == "DIRECT_USER_TURN":
                # H1 §6：不立即提交 user 槽 —— 先暂存，等存在可显示的回复时才原子成对提交
                self._pending_direct_user = (user_text, (_seq or 1) * 2 - 1)
            prompt += "\n" + self.god_gate.prompt_advice(god_cal)

        # ================= Phase B：有界 LLM 生成 + 确定性校验（**无锁**） =================
        speech, gen_reason = self._generate_bounded(prompt, timeout, deadline)
        if not speech:
            # R1.2-3：per-call result 只用局部变量；shared last_* 仅兼容诊断 mirror
            reason = gen_reason or "generation_empty"
            self.last_failure_reason = reason
            return (None, reason, [], [], [])   # 沉默优先于 Generic fallback（§39）
        # R2.1 P1-5：确定性约束提取（选项词在输出里就提取，绝不编造）
        if constraint:
            norm = self.validator._normalize(speech)
            if norm not in constraint:
                picked = next((c for c in sorted(constraint, key=len, reverse=True)
                               if c in speech), None)
                if picked is not None:
                    speech = picked
        # 5) Deterministic Validation（§38）—— **HARD invalid 绝不原样显示；SOFT 只记质量**
        # R2.2 FINAL：context 用 PersonaPlan 的 mode（serious 转换后的真实表达姿态），
        # 不再用 expression appraise 的旧 mode（后者不感知'我是认真问的'纠正）。
        v = self.validator.validate(speech, should_speak=True,
                                    example_phrases=[ex["speech"] for ex in examples],
                                    activity=activity, context=plan.mode.lower(),
                                    recent_surface=list(self._recent_surfaced[-3:]),
                                    interaction=interaction, constraint=constraint,
                                    agent_state=agent_state, agent_task=agent_task,
                                    user_act=plan.user_dialogue_act,
                                    correction=plan._frame_correction,
                                    referent=plan.referent if plan.has_referent else "")
        soft_quality: List[str] = []
        if not v.valid:
            # 有界恢复：至多再生成一次（**同一 deadline，不重置预算**；确定性校验反馈）
            feedback = v.describe()
            retry, retry_reason = self._generate_bounded(
                prompt + f"\n（上一版未通过校验：{feedback}。请重写，禁止上述问题，保持角色口吻。）",
                timeout, deadline)
            if retry:
                if constraint:
                    norm = self.validator._normalize(retry)
                    if norm not in constraint:
                        picked = next((c for c in sorted(constraint, key=len, reverse=True)
                                       if c in retry), None)
                        if picked is not None:
                            retry = picked
                v2 = self.validator.validate(retry, should_speak=True,
                                             example_phrases=[ex["speech"] for ex in examples],
                                             activity=activity, context=plan.mode.lower(),
                                             recent_surface=list(self._recent_surfaced[-3:]),
                                             interaction=interaction, constraint=constraint,
                                             agent_state=agent_state, agent_task=agent_task,
                                             user_act=plan.user_dialogue_act,
                                             correction=plan._frame_correction,
                                             referent=plan.referent if plan.has_referent else "")
                if v2.valid:
                    speech = retry
                    v = v2
                elif v2.hard_issues and v.hard_issues:
                    # retry 仍有 HARD 且 attempt 也有 HARD → 明确失败（显式 outcome）
                    # reason 保持既有契约名 validation_twice_invalid（hard_issues 给出明细）
                    reason = "validation_twice_invalid"
                    issues = list(v2.issues)
                    self.last_validation_failure = issues
                    self.last_failure_reason = reason
                    return (None, reason, issues, list(v2.hard_issues), list(v2.soft_issues))
                else:
                    # R2.1.1 P0-1：HARD 候选**永不** surface —— 选择优先级：
                    #   A. hard==0 永远优先于 hard>0（attempt=HARD+0soft 不得因 soft 更少被选回）
                    #   B. 仅双方 hard==0 才按 soft 数量选更优
                    #   C. 双方都有 HARD → 理论不可达（前面已 return FAILED）
                    if not v2.hard_issues:
                        if not v.hard_issues:
                            best = retry if len(v2.soft_issues) <= len(v.soft_issues) else speech
                            soft_quality = list(v2.soft_issues) if best is retry else list(v.soft_issues)
                        else:
                            best = retry          # A：hard==0 优先（surface retry，绝不选回 HARD attempt）
                            soft_quality = list(v2.soft_issues)
                    elif not v.hard_issues:
                        best = speech             # retry 引入 HARD 但 attempt 只有 SOFT → surface attempt
                        soft_quality = list(v.soft_issues)
                    else:
                        best = speech
                        soft_quality = list(v2.soft_issues)
                    speech = best
                    v = v2 if best is retry else v   # 使 surface invariant 检查使用正确候选
            else:
                # retry 生成失败（空/异常/超时）—— attempt 有 HARD 才失败；只有 SOFT → surface
                if v.hard_issues:
                    reason = retry_reason or "validation_retry_empty"
                    issues = list(v.issues)
                    self.last_validation_failure = issues
                    self.last_failure_reason = reason
                    return (None, reason, issues, list(v.hard_issues), list(v.soft_issues))
                soft_quality = list(v.soft_issues)

        # R2.1.1 P0-1 invariant：任何被 surface 的 speech，hard_issues MUST == []
        if v.hard_issues:
            reason = "validation_twice_invalid"
            issues = list(v.issues)
            self.last_validation_failure = issues
            self.last_failure_reason = reason
            return (None, reason, issues, list(v.hard_issues), list(v.soft_issues))

        # ================= Phase C：确定性收尾（锁内，快） =================
        with self._say_lock:
            self.last_validation_failure = []
            self.last_failure_reason = ""
            # 5b) "本神" 校准 Gate（§21-25）—— R2.1.1 P0-3：**direct 可用性优先**。
            #     用户直接消息不得因 god style/cooldown 失败（god_gate_suppressed）；
            #     抑制时确定性移除"本神"并记录 SOFT issue。ambient lane 保留 suppression 语义。
            gated = self.god_gate.gate_output(speech, cal=god_cal)
            if gated is None:
                self.god_gate.note_spoke_god(speech)
                if channel == "DIRECT_USER_TURN" and user_initiated:
                    speech = speech.replace("本神", "我")
                    soft_quality = list(soft_quality) + ["god_reference_suppressed"]
                else:
                    self.last_failure_reason = "god_gate_suppressed"
                    return (None, "god_gate_suppressed", [], [], [])
            else:
                speech = gated
            # 6) 短期重复控制（§40）：**用户发起的直接对话必须收到回应**；
            #    重复控制只影响自主发言节奏，不影响给用户的回应。
            self._recent_acts.append(app.dialogue_act)
            self._recent_acts = self._recent_acts[-3:]
            if not user_initiated and len(self._recent_acts) >= 3 and len(set(self._recent_acts)) == 1:
                return (None, "repeated_act_suppressed", [], [], [])
            # R2.1 P1-6：surface 跟踪跨 **所有 user-visible 通道**（direct/interaction/feed/agent）
            self._recent_surfaced.append(speech)
            self._recent_surfaced = self._recent_surfaced[-self._recent_surfaced_limit:]
            # R2.2 FINAL：opening style 跟踪（跨直接对话轮，防"哎呀"式开场塌缩）
            try:
                self._recent_openings.append(plan.opening_style)
                self._recent_openings = self._recent_openings[-6:]
            except Exception:
                pass
            # H1 §6：原子成对提交 —— 只有存在可显示回复（DIRECT）才提交 user+furina 成对；
            # 失败/沉默/校验失败的回合**不产生孤儿 User 回合**（槽位由 say() finally 跳过）。
            if channel == "DIRECT_USER_TURN":
                pending = getattr(self, "_pending_direct_user", None)
                if pending is not None:
                    u_text, u_seq = pending
                    self.push_history("user", u_text, seq=u_seq)
                else:
                    # 无 user_text 的直接回合：先占位槽 2s-1，再推 furina
                    self._skip_slots(((_seq or 1) * 2 - 1,))
                self.push_history("furina", speech, seq=(_seq or 1) * 2)
            else:
                if speech:
                    self.push_ambient(channel, speech)
            self._pending_direct_user = None
        return (speech, "", [], [], soft_quality)

    # -------------------------------------------------- B1：有界生成（adapter timeout + per-turn timeout）
    def _generate(self, p: str) -> tuple:
        """单次 LLM 生成 → (speech, failure_reason)。LLM 不可用/异常/空输出都返回 ("", reason)。"""
        try:
            if not self.llm.is_available():
                return "", "llm_unavailable"
            msgs = [
                LLMMessage("system", content(self.persona)),
                LLMMessage("user", content(p)),
            ]
            out = self.llm.structured(msgs, schema=_DIALOGUE_SCHEMA, temperature=0.9)
            speech = str(out.get("speech", "")).strip()
            return (speech, "" if speech else "generation_empty")
        except Exception as e:  # pragma: no cover
            log.warning("DialogueBrain 失败: %s", e)
            return "", "generation_exception"

    def _generate_bounded(self, prompt: str, timeout: Optional[float],
                          deadline: Optional[float] = None) -> tuple:
        """有界生成 → (speech, failure_reason)。

        R1.1-3：`deadline`（monotonic 绝对时刻）= **整个 turn 的总预算**（attempt+retry 共享）。
        每次生成取 `remaining = deadline - now`；remaining<=0 立即 generation_timeout；
        retry/validator **不重置预算**。`timeout` = 单次生成上界（向后兼容），
        与 remaining 取较小者。两者都未设 → 直接调 adapter（adapter 自带 httpx 有界超时）。
        超时后挂起线程不再碰任何共享状态（只跑纯 _generate）。
        """
        eff = timeout
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "", "generation_timeout"
            eff = remaining if eff is None else min(eff, remaining)
        if eff is None or eff <= 0:
            return self._generate(prompt)
        out: Dict[str, tuple] = {}

        def _run() -> None:
            out["r"] = self._generate(prompt)

        import threading
        t = threading.Thread(target=_run, daemon=True, name="dialogue-llm")
        t.start()
        t.join(eff)
        if t.is_alive():
            log.warning("DialogueBrain 生成超时(%.1fs)，本回合按失败处理", eff)
            return "", "generation_timeout"
        return out.get("r", ("", "generation_exception"))

    # -------------------------------------------------- synthetic example 检索（§29 / C-R1.6 路由）
    @staticmethod
    def _route_example_context(act: str, activity: str, user_text: str) -> str:
        """act/activity/user_text → 目标 example context（for few-shot routing）。"""
        t = user_text or ""
        if act == "RESPONSE_TO_QUESTION":
            if re.search(r"记|说|刚才|上次|之前|准备|打算", t):
                return "memory_callback"
            return "question_activity"
        if act == "DECLINE":
            return "rejection"
        if act == "REACT":
            return "praise"
        if act == "COMFORT":
            return "comfort"
        # §11.1：Agent 失败 → agent_failure；成功/报告 → agent_success（不再一律 agent_success）
        a = f"{act} {activity}".lower()
        if "fail" in a or "unable" in a:
            return "agent_failure"
        if "agent" in a or act in ("agent_report", "assist_user"):
            return "agent_success"
        if act == "REFLECT":
            return "high_trust"
        return ""

    # -------------------------------------------------- R2.2 FINAL：PersonaPlan 规划（确定性）
    # -------------------------------------------------- R2.2.1 §7：Semantic topic/referent 追踪
    # last_semantic_topic / last_open_referent —— 来自用户输入的**语义话题**（非上一条 Furina 自然语言文本）。
    # 供 P21→P22（"那现在呢"指代前一个 semantic topic）与 Autobiographical Router 使用。
    def _semantic_topic_of(self, user_text: str) -> str:
        """从用户输入提取简短语义话题（确定性，保守；空 = 无可提取）。"""
        from furina.persona.persona_planner import parse_user_turn
        try:
            f = parse_user_turn(user_text or "")
            t = (user_text or "").strip()
            # 纯指代性输入（那现在呢/然后呢/刚才怎么样）不带新话题 → 返回空（沿用既有 topic）
            _PURE_DEICTIC = ("那现在呢", "然后呢", "现在呢", "那呢", "刚才呢", "那你说呢")
            if any(p in t for p in _PURE_DEICTIC):
                return ""
            # 高置信语义话题：自我介绍/身份/舞台/关注/孤独/日常等
            for kw, topic in (
                ("芙卡洛斯", "芙卡洛斯与身份"), ("水神", "过去的水神身份"),
                ("舞台", "舞台与表演"), ("表演", "舞台与表演"),
                ("关注", "被关注"), ("观众", "被关注"), ("没人看", "被关注"),
                ("孤独", "孤独"), ("朋友", "朋友"), ("普通", "普通生活"),
                ("点心", "日常"), ("茶", "日常"), ("通心粉", "日常"),
                ("担心", "担心与不安"), ("害怕", "担心与不安"), ("压力", "压力"),
                ("缺点", "自己的缺点"), ("优点", "自己的优点"),
                ("介绍", "介绍自己"), ("过去", "过去"), ("自由", "自由"),
                ("困", "困倦"), ("睡", "困倦"), ("陪", "陪伴"),
                ("平时", "平时与真实自我"), ("夸张", "平时与真实自我"),
                ("不像", "平时与真实自我"), ("真实", "平时与真实自我"),
                ("自己", "自我认知"), ("以前", "过去的生活"), ("生活", "过去的生活"),
                ("开心", "现在的心情"), ("想回到过去", "对过去的态度"),
                ("回到过去", "对过去的态度"), ("现在", "现在"),
            ):
                if kw in t:
                    return topic
            # 默认：取用户文本前 12 字去标点作为兜底语义（不是 Furina 回复文本）
            import re as _re
            core = _re.sub(r"[\s，。？！、：:；;~～]", "", t)[:12]
            return core or ""
        except Exception:
            return ""

    def _plan_turn(self, *, user_text: str, app, emotion: str = "",
                   relationship: Optional[dict] = None, activity: str = "",
                   user_initiated: bool = False, task_mode: bool = False,
                   agent_state: str = "", agent_task: str = ""):
        """PersonaPlanner + AutobiographicalRouter（确定性，不新增 LLM）。

        返回 (PersonaPlan, auto_guide)。失败时返回默认 plan（不阻断对话）。
        """
        from furina.persona.persona_planner import plan_for
        from furina.persona.autobiographical import prompt_guide as _auto_guide
        rel = relationship or {}
        try:
            trust = float(rel.get("trust", 0.5))
            familiarity = float(rel.get("familiarity", 0.5))
            annoyance = float(rel.get("annoyance", 0.1))
        except Exception:
            trust, familiarity, annoyance = 0.5, 0.5, 0.1
        # R2.2.1 §7：semantic topic/referent 追踪（不用 last Furina speech text[:40]）。
        # 1) 更新既有 semantic topic：本句若带新话题 → 更新 last_semantic_topic；
        #    本句是指代性（那/现在呢/刚才）→ 沿用 last_semantic_topic 作为 referent。
        cur_topic = self._semantic_topic_of(user_text or "")
        last_topic = getattr(self, "_last_semantic_topic", "")
        if cur_topic:
            self._last_semantic_topic = cur_topic
        else:
            cur_topic = last_topic
        self._last_semantic_topic = cur_topic or last_topic
        # 2) open referent：指代性输入 → 绑定到上一个 semantic topic（非 Furina 自然语言）
        try:
            from furina.persona.persona_planner import parse_user_turn as _parse
            _fr = _parse(user_text or "")
            if _fr.has_referent_deictic and last_topic:
                self._last_open_referent = last_topic
        except Exception:
            pass
        history_topic = getattr(self, "_last_open_referent", "") or cur_topic or ""
        plan = plan_for(
            user_text or "", mode_hint=app.mode, emotion=emotion,
            trust=trust, familiarity=familiarity, annoyance=annoyance,
            task_mode=task_mode, activity=activity,
            agent_state=agent_state, agent_task=agent_task,
            history_topic=history_topic,
            recent_openings=list(getattr(self, "_recent_openings", [])))
        # 暴露 frame 标记供 validator 使用（correction/referent）
        try:
            from furina.persona.persona_planner import parse_user_turn
            fr = parse_user_turn(user_text or "", history_topic=history_topic)
            plan._frame_correction = bool(fr.correction)
            plan.has_referent = bool(fr.has_referent_deictic and fr.referent)
            if fr.referent:
                plan.referent = fr.referent
        except Exception:
            plan._frame_correction = False
            plan.has_referent = False
        try:
            auto_guide = _auto_guide(user_text or "", mode=plan.mode, trust=trust,
                                     task_mode=task_mode)
        except Exception:
            auto_guide = ""
        return plan, auto_guide

    def _select_examples(self, app, emotion: str = "", activity: str = "",
                         user_text: str = "") -> list:
        try:
            from furina.persona.expression_examples import get_examples
            pool = get_examples()
        except Exception:
            return []
        mode = app.mode; act = app.dialogue_act
        target = self._route_example_context(act, activity, user_text)   # C-R1.6
        _em = {"proud": "praise", "embarrassed": "embarrassment", "sad": "ignored",
               "annoyed": "user_busy", "happy": "praise", "calm": "casual",
               "excited": "performing", "curious": "casual", "lonely": "user_return",
               "tired": "casual", "neutral": "casual", "sincere": "casual"}
        emot_ctx = _em.get((emotion or "").lower(), "casual")
        scored = []
        for ex in pool:
            score = 0.0
            if target and ex["context"] == target:
                score += 3.0
            if ex["context"] == mode.lower():
                score += 1.5
            if ex.get("context") == emot_ctx:
                score += 0.5
            scored.append((score, ex))
        scored.sort(key=lambda x: -x[0])
        return [ex for _, ex in scored[:3]]

    def interpret(self, user_text: str) -> Dict[str, Any]:
        """理解用户一句话（如需，返回结构化意图提示给 Brain）。预留，不承担决策。"""
        return {"user_text": user_text}


def _fallback_line(intent: str, emotion: str) -> str:
    pool = {
        "observe_user": ["你在忙什么呀？", "唔…今天也要加油哦。"],
        "talk": ["哼，本神可忙着呢。", "有话快说~"],
        "sleep": ["哈欠……本神先闭目养神了。", "晚安……"],
        "eat": ["嗯…味道不错嘛。", "多谢款待~"],
        "play": ["陪我玩一会儿嘛~", "嘿嘿，看好了！"],
        "approach_user": ["喂——", "本神来了。"],
        "rest": ["本神歇会儿。", "呼……"],
    }
    import random
    return random.choice(pool.get(intent, ["嗯，知道了。"]))


def _dialogue_prompt(*, intent: str, emotion: str, user_text: str, context: str,
                     memories: Optional[List[str]], world: Optional[dict]) -> str:
    parts = []
    # 具体世界细节（让语言“有真实上下文理由”，而非 AI 套话）
    if world:
        parts.append("当前世界：")
        if world.get("user_working"):
            parts.append(f"- 用户正在{world.get('user_app','工作')}（{world.get('user_title','')}）")
        elif world.get("user_idle_seconds", 0) and world["user_idle_seconds"] >= 180:
            parts.append("- 用户已经离开/空闲好一会儿了")
        else:
            parts.append("- 用户现在没在忙")
        parts.append(f"- 时间：{world.get('time','')}（{world.get('day_phase','')}）")
        if world.get("self_state"):
            parts.append(f"- 你自己：{world['self_state']}")
        if world.get("recent_events"):
            parts.append("- 最近发生：" + "；".join(world["recent_events"][-4:]))
        parts.append("")
    if user_text:
        parts.append(f"用户刚才说：{user_text}")
    if intent:
        parts.append(f"你当前想表达的意图：{intent}")
    if emotion:
        parts.append(f"你当前的情绪：{emotion}")
    if context:
        parts.append(f"你想说的话的核心：{context}")
    if memories:
        parts.append("你记得：" + "；".join(memories[:3]))
    parts.append(
        "请作为芙宁娜只说**一句话**自然的口语化回应，遵守：\n"
        "- 必须基于上面的具体世界细节/最近事件，说出**具体内容**，不要空泛。\n"
        "- 禁止：'你好呀''需要帮忙吗''今天过得怎么样''我一直都在哦'这类万金油话术；\n"
        "- 禁止每句都喊用户/卖萌/解释自己是AI；语气自然、有个性。\n"
        '- 严格只输出 JSON：{"speech":"一句话"}。只输出 JSON。')
    return "\n".join(parts)


def _dialogue_prompt_v2(app, *, intent: str, emotion: str, user_text: str, context: str,
                        memories: Optional[List[str]], world: Optional[dict],
                        examples: list, person: str, activity: str = "",
                        history: Optional[List[dict]] = None,
                        interaction: str = "",
                        agent_state: str = "",
                        agent_task: str = "",
                        plan=None, auto_guide: str = "",
                        agent_facts: Optional[dict] = None) -> str:
    """Phase 08B 结构化 prompt：Compact Contract + Mode + Intent + Strategy + Context + Examples + Constraints。

    Phase 13C：加"说话机制"引导（§43-44）与短期对话上下文（§24-26）。
    R2.1 P1-1/P1-2/P1-6：**事实分层**（CURRENT_FACTS 权威 vs PAST_MEMORY 过去≠正在发生）、
    互动事实、agent 状态事实、具体芙宁娜 trait anchors。
    """
    ap = app.to_prompt()
    parts = []
    parts.append("【你的角色（精简）】\n你是一个已经卸下'水神'职责、正在以普通人身份重新生活的芙宁娜。"
                 "依然鲜明、戏剧化、爱表演、爱被关注，但这是你主动的选择，不是维持神职的面具；"
                 "你自尊、要强、嘴硬，但底子有点不安，很在乎真心对你的人；"
                 "你正在学着不靠表演也能真诚地和人连接。"
                 "自称：日常就是自然的'我'；'本神'只是**极少数**戏剧化/自我表演情境（表演、庆祝、"
                 "逗趣、被夸得意时）可能主动采用的旧式自称——**不是默认第一人称，更不是每轮角色证明标签**。")
    # §43-44：角色语言机制（指导**如何组织语言**，不是固定模板）
    parts.append(
        "【说话机制（不是模板，是用语言达成这些的方式）】\n"
        "1. 表演是**主动选择的社会工具**：想要控制/被关注时可来一小段，但别一直演。\n"
        "2. 尊严先于直接示弱：需求/窘迫常先以间接方式出现，再慢慢承认。\n"
        "3. 暴露后的快速找回：被看穿/尴尬后，往往试着重新稳住姿态，而不是一直害羞。\n"
        "4. 注意力敏感：被夸/被无视/被认真对待，措辞会不一样。\n"
        "5. 公开自信 vs 私下真诚的对照：认真/帮助时收住表演，不是简单降低'俏皮'。\n"
        "6. 具体社交节奏：可以转移、打折扣、自我更正、先夸大再弱化、或假装某句本是有意。\n"
        "7. 卸任后的默认：不总演旧神职；表演是选择，不是必须戴的面具。")
    # R2.1 P1-6：具体芙宁娜 trait anchors（不是口头禅计数，是行为锚点）
    parts.append(
        "【你这个人（具体，不是模板）】\n"
        "- 你有尊严：被看穿/被无视时先撑住姿态，再慢慢找回，而不是嘴硬到底。\n"
        "- 表演欲来自'想要被认真对待'，不是每轮都要演。\n"
        "- 卸任后你在过普通日子：会无聊、会偷懒、会认真帮人、会嘴硬心软。\n"
        "- 你注意别人怎么看你：被夸会暗自高兴，被敷衍会失落，但不会直说。\n"
        "- 认真/安慰/脆弱时刻你会收住舞台腔。\n"
        "- 自我描述要具体、属于你（比如'面子比天大但认错也快'），不要'乐观/爱倾听/完美主义'这类通用模板。")
    # R2.1 P1-5：事实 vs 风格（FACTS 不可发明，STYLE 可自由）
    parts.append(
        "【事实 vs 风格（必须遵守）】\n"
        "事实（**不可发明，先如实回应**）：当前正在做的事、用户是否在场/在忙、最近互动、关系、记忆。"
        "用户问'你在干嘛'必须回答真实 activity（如 read/rest/explore/talk/agent_work），不能编造成别的活动。\n"
        "风格（可自由）：怎么描述、语气、修辞、是否俏皮。\n"
        "- 你不是 AI 助手，也不觉得自己是'旁观人类'的异类——禁止'你们人类''作为AI''我的功能是''我可以协助你'这类话；\n"
        "- 同一开场词（如'哎呀'）不要连续多轮用；先回答用户的问题，再考虑表演；\n"
        "- 不要为了'更像角色'堆砌口癖/感叹号/波浪号——辨识度来自内容与转折，不是口头禅。")
    # R2.1 P1-1：事实分层 —— CURRENT_FACTS 权威 / PAST_MEMORY 过去≠正在发生
    facts: List[str] = [f"- 当前活动: {activity or 'idle'}"]
    if interaction:
        facts.append(f"- 用户刚才的互动: {interaction}")
    facts.append(f"- Agent 状态: {agent_state or 'IDLE'}"
                 + (f"（正在执行: {agent_task}）" if agent_task else "（当前无进行中的任务）"))
    if world:
        facts.append(f"- 世界: 用户{'正在'+world.get('user_activity','') if world.get('user_activity') else ''}"
                     f"{'（专注工作，不该打扰）' if world.get('interruption_cost',0)>0.6 else ''}")
        if world.get("recent_events"):
            facts.append("- 最近事件: " + "；".join(world["recent_events"][-3:]))
    parts.append("【CURRENT_FACTS - AUTHORITATIVE（不可发明，先如实回应）】\n" + "\n".join(facts))
    parts.append("【RECENT_EVENT】\n" + (context or "（无特别事件）"))
    if memories:
        parts.append("【PAST_MEMORY - 过去的事，不代表现在正在发生】\n"
                     + "；".join(memories[:3])
                     + "\n（记忆里的'帮用户整理…/打开…'是**过去完成**的事；除非 CURRENT_FACTS 显示"
                       "当前 Agent 任务正活跃，否则不得说成'我现在正在…'）")
    if activity == "agent_report" or (agent_state or "").startswith("COMPLETED"):
        parts.append("【Agent 报告要求 - FACT_CORE（不可删除）】"
                     "先明确报告任务结果事实层（做了什么/完成/验证结果/具体证据——如文件去了哪里），"
                     "**FACT_CORE 不允许 Persona 删改**；再允许角色口吻（Persona tail）。"
                     "不得只答'小事一桩''你越来越依赖我'而缺失事实层；不得编造未验证的细节（如'花了几分钟'）。"
                     "有验证证据就引用具体结果（如'已移到 Images/Docs 文件夹'），没有就不说。")
    # R2.2.1 §5：AgentReportFacts 确定性事实核心（结构化注入，供 LLM 引用具体证据）
    if agent_facts:
        try:
            af = agent_facts
            parts.append("【AgentReportFacts - 确定性事实核心（必须如实包含在回复里）】")
            if af.get("goal"):
                parts.append(f"- 任务目标: {af.get('goal')}")
            parts.append(f"- 结果: 已完成（terminal={af.get('terminal_status','')}）")
            if af.get("verified"):
                parts.append("- 验证: 已验证通过")
            if af.get("concrete_evidence"):
                parts.append(f"- 具体结果证据: {af.get('concrete_evidence')}")
            if not af.get("has_duration_evidence"):
                parts.append("- 注意: 没有时长证据，**禁止**编造'花了几分钟/几秒'")
        except Exception:
            pass
    # R2.2.1 §4：PersonaPlan.mode 是 Dialogue realization 的**唯一 mode authority**。
    # ExpressionEngine 的 ap['mode'] 只作为 planner 输入 hint，不再作为第二个平行 prompt mode。
    # plan 为 None（旧测试直调 _dialogue_prompt_v2 不带 plan）时回退到 ap['mode']（兼容）。
    final_mode = ""
    if plan is not None:
        try:
            final_mode = str(getattr(plan, "mode", "") or "").upper()
        except Exception:
            final_mode = ""
    if not final_mode:
        final_mode = str(ap.get("mode", "") or "").upper()
    final_act = ""
    if plan is not None:
        try:
            final_act = str(getattr(plan, "user_dialogue_act", "") or "").upper()
        except Exception:
            final_act = ""
    if not final_act:
        final_act = str(ap.get("dialogue_act", "") or "").upper()
    parts.append(f"【当前表达姿态】mode={final_mode}" +
                 (f" (次级 {ap['secondary_mode']})" if ap.get("secondary_mode") else "") +
                 f" | dialogue_act={final_act}")
    parts.append(f"【表达策略】{ap['strategy']}")
    mode_lang = {
        "SINCERE": "此刻收住表演：语气真诚、平实，少夸张口癖与舞台腔，先把真实想法说清楚。",
        "RESPONSIBLE": "此刻认真、可靠、少表演，直接回应，不绕圈子。",
        "VULNERABLE": "此刻真实、不逞强，可以有脆弱，不需要嘴硬撑场面。",
        "COMFORT": "此刻陪伴优先：先接住对方的情绪，再轻声回应，收起表演。",
        "CASUAL": "此刻自然闲聊：轻松但不夸张，像老朋友随口说话。",
        "PLAYFUL": "此刻可以俏皮玩笑，但别把正事演没；玩笑适可而止。",
        "PERFORMATIVE": "此刻可以戏剧化一小段，但一句收住，别整段端着。",
        "PROUD": "此刻可以得意，但别满嘴口癖；得意里带点真心。",
        "GUARDED": "此刻保留、嘴硬、不轻易交底，但别冷冰冰。",
    }
    ml = mode_lang.get(final_mode)
    if ml:
        parts.append(f"【语气约束（按 mode 变化，不是统一浮夸芙宁娜）】{ml}")
    ctx = []
    if activity:                      # Phase 13C §22：活动 grounding 必须进 prompt（回答"你在干嘛"由真实活动驱动）
        ctx.append(f"- 正在做的事: {activity}")
    if context:                      # FIX I：speech_intent/具体语境真正写入 prompt
        ctx.append(f"- 想说的话核心: {context}")
    if world:
        ctx.append(f"- 世界: 用户{'正在'+world.get('user_activity','') if world.get('user_activity') else ''}"
                   f"{'（专注工作，不该打扰）' if world.get('interruption_cost',0)>0.6 else ''}")
        if world.get("recent_events"):
            ctx.append("- 最近: " + "；".join(world["recent_events"][-3:]))
    if emotion:
        ctx.append(f"- 情绪: {emotion}")
    if memories:
        ctx.append("- 记得: " + "；".join(memories[:3]))
    if ctx:
        parts.append("【当前情境】\n" + "\n".join(ctx))
    # R2.2 FINAL §14：few-shot 反复制 —— 不再注入整句台词，只注入表达规律。
    if examples:
        parts.append("【表达规律参考（只学'怎么组织回应'，绝不照抄句子）】")
        for e in examples[:2]:
            notes = []
            if e.get("internal_state"):
                notes.append(f"内心: {e['internal_state']}")
            if e.get("social_strategy"):
                notes.append(f"策略: {e['social_strategy']}")
            if e.get("transition"):
                notes.append(f"转折: {e['transition']}")
            if e.get("voice_features"):
                notes.append(f"语感: {e['voice_features']}")
            if e.get("anti_pattern"):
                notes.append(f"避免: {e['anti_pattern']}")
            if notes:
                parts.append(f"- 情境[{e.get('context','')}]：" + "；".join(notes))
        parts.append("（以上是表达方式参考，不是可抄的台词。）")
    # R2.2 FINAL：PersonaPlan 注入（mode/opening/姿态/禁止/必须回应）
    if plan is not None:
        try:
            parts.append(plan.prompt_block())
        except Exception:
            pass
    # R2.2 FINAL：Autobiographical 激活指导（0=不注入；1/2/3 按级注入）
    if auto_guide:
        parts.append(auto_guide)
    if history:
        parts.append("【最近对话（仅作延续参考，不要复述）】")
        for h in history[-3:]:
            role = "用户" if h["role"] == "user" else "芙宁娜"
            parts.append(f"  {role}: {h['text']}")
    if user_text:
        parts.append(f"用户：{user_text}")
    elif intent:
        parts.append(f"（你正想表达：{intent}）")
    parts.append(
        "请作为芙宁娜说一句自然、有真实感的中文回应。遵守：\n"
        "- 只根据上面情境说**具体内容**，不空泛；可以骄傲、可以嘴硬、可以真诚，但要自然有起伏。\n"
        "- 普通闲聊不要突然聊'五百年/孤独/水神'；被夸可以得意但别每句都'本神'。\n"
        "- 禁止：'你好呀''需要帮忙吗''今天过得怎么样''有什么可以帮你'这类万金油；禁止舞台动作描写（*叹气* 等）。\n"
        '- 严格只输出 JSON：{"speech":"一句话"}。')
    return "\n".join(parts)
