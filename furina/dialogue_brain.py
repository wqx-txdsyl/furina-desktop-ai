"""DialogueBrain —— 「语言」：只负责“既然我要表达这个意图，作为芙宁娜应该怎么说”。

三脑架构：与 LifeBrain/Tool Agent 严格隔离。
- 不决定：要不要说、何时说、要不要走/打断/睡觉（那是 LifeBrain）。
- 不决定：怎么操作电脑（那是 Tool Agent）。
- 只做：给一个意图 + 上下文 + 人格，产出符合芙宁娜口吻的一句话/一段话。
"""
from __future__ import annotations

import re
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

    # -------------------------------------------------- H1 §5：turn FIFO 门（ticket/Condition）
    def _gate_wait(self, seq: int) -> None:
        """进入生成前等待：必须等到所有前序 turn（seq-1）完成。"""
        with self._fifo_cond:
            while seq != self._last_done_seq + 1:
                self._fifo_cond.wait(timeout=1.0)

    def _gate_release(self, seq: int) -> None:
        """本 turn 完成（含失败/沉默/校验失败）→ 放行下一个 turn。"""
        with self._fifo_cond:
            self._last_done_seq = seq
            self._fifo_cond.notify_all()

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
            timeout: Optional[float] = None) -> Optional[str]:
        """生成一句符合人格、有真实上下文的中文台词，或 None（沉默，§5/§39）。

        B1（评审基线 0402e7f）**通道分 lane**：
          - DIRECT_USER_TURN：direct lane（owner 入口 reserve_turn → 严格 ingress FIFO；
            直接历史成对提交；失败有可观察终态）。由 DirectDialogueQueue 串行 worker 调用，
            也可由测试直接调用（仍受 direct gate 保序）。
          - AMBIENT_AUTONOMOUS / FEED_REACTION / INTERACTION_REACTION / AGENT_REPORT：
            **独立 ambient lane**（独立序号 + 独立门）—— 慢/挂起的 ambient 回合
            **永不占用 direct 序号、永不阻塞 direct lane**；ambient 可被节流/丢弃。
        B1 有界生命周期：timeout（默认 self._timeout，测试可注入小值）内完成生成；
        任何失败（LLM 不可用/异常/超时/空输出/双重校验失败/god gate 抑制）都释放本回合并推进 FIFO。
        """
        eff_timeout = timeout if timeout is not None else self._timeout
        if channel == "DIRECT_USER_TURN":
            seq = ingress_seq if ingress_seq is not None else self._next_seq()
            self._gate_wait(seq)            # direct 门 —— 前序 direct turn 完成前不进入生成
            try:
                return self._say_impl(intent=intent, emotion=emotion, user_text=user_text,
                                      context=context, memories=memories, world=world,
                                      activity=activity, relationship=relationship,
                                      memory_interp=memory_interp, user_initiated=user_initiated,
                                      task_mode=task_mode, solitude=solitude, user_present=user_present,
                                      presence_known=presence_known, channel=channel, _seq=seq,
                                      _lane="direct", timeout=eff_timeout)
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
            return self._say_impl(intent=intent, emotion=emotion, user_text=user_text,
                                  context=context, memories=memories, world=world,
                                  activity=activity, relationship=relationship,
                                  memory_interp=memory_interp, user_initiated=user_initiated,
                                  task_mode=task_mode, solitude=solitude, user_present=user_present,
                                  presence_known=presence_known, channel=channel, _aseq=aseq,
                                  _lane="ambient", timeout=eff_timeout)
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
                  timeout: Optional[float] = None) -> Optional[str]:
        """say() 的实现体（由 lane 入口包裹；_seq/_aseq 为 lane 序号）。

        B1（评审基线 0402e7f）三阶段：
          A. 锁内确定性准备（appraise / act 路由 / god 校准 / examples / prompt / 暂存 user）
          B. **无锁**有界 LLM 生成 + 确定性校验 + 至多一次 retry（带校验反馈）
          C. 锁内确定性收尾（god gate / 表面语言跟踪 / 历史成对提交）
        LLM 调用**不持 _say_lock** —— ambient 回合慢/挂起时，direct 回合无需等锁即可生成；
        每个回合的生成都有界（adapter timeout + 可选 per-turn timeout），失败必释放本回合。
        """
        # ================= Phase A：确定性表达准备（锁内，快） =================
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
                return None
            # Phase 13C §19-20：用户发起的对话用确定性 act 路由覆盖
            if user_text:
                app.dialogue_act = self.classify_act(user_text)
            # 2b) "本神" 情境化校准（Phase 10）：只改 prompt 引导，不强制；给出语境偏好
            god_cal = self.god_gate.calibrate(mode=app.mode, dialogue_act=app.dialogue_act,
                                              emotion=emotion, user_text=user_text)
            # 3) 相关 synthetic examples（Top-K=3）
            examples = self._select_examples(app, emotion, activity=activity, user_text=user_text)
            # 4) 生成 prompt。C-R1.3.1：history 只含**当前轮之前**的发言，当前 user_text 单独附一次
            hist = self.recent_turns(4)
            prompt = _dialogue_prompt_v2(app, intent=intent, emotion=emotion,
                                         user_text=user_text, context=context,
                                         memories=memories, world=world,
                                         examples=examples, person=self.persona,
                                         activity=activity, history=hist)
            if user_text and channel == "DIRECT_USER_TURN":
                # H1 §6：不立即提交 user 槽 —— 先暂存，等存在可显示的回复时才原子成对提交
                self._pending_direct_user = (user_text, (_seq or 1) * 2 - 1)
            prompt += "\n" + self.god_gate.prompt_advice(god_cal)

        # ================= Phase B：有界 LLM 生成 + 确定性校验（**无锁**） =================
        speech, gen_reason = self._generate_bounded(prompt, timeout)
        if not speech:
            self.last_failure_reason = gen_reason or "generation_empty"
            return None   # 沉默优先于 Generic fallback（§39）
        # 5) Deterministic Validation（§38）—— **invalid 绝不原样显示**
        v = self.validator.validate(speech, should_speak=True,
                                    example_phrases=[ex["speech"] for ex in examples],
                                    activity=activity, context=app.mode.lower(),
                                    recent_surface=list(self._recent_surfaced[-3:]))
        if not v.valid:
            # 有界恢复：至多再生成一次（确定性校验反馈 → retry 知道哪里错了）
            feedback = v.describe()
            retry, retry_reason = self._generate_bounded(
                prompt + f"\n（上一版未通过人格校验：{feedback}。请重写，禁止上述问题，保持角色口吻。）",
                timeout)
            if retry:
                v2 = self.validator.validate(retry, should_speak=True,
                                             example_phrases=[ex["speech"] for ex in examples],
                                             activity=activity, context=app.mode.lower(),
                                             recent_surface=list(self._recent_surfaced[-3:]))
                if v2.valid:
                    speech = retry
                    v = v2
                else:
                    # 仍 invalid → 不泄漏 invalid 角色输出；暴露可观察失败路径（调用方转 SYSTEM_STATUS）
                    self.last_validation_failure = list(v2.issues)
                    self.last_failure_reason = "validation_twice_invalid"
                    return None
            else:
                self.last_validation_failure = list(v.issues)
                self.last_failure_reason = retry_reason or "validation_retry_empty"
                return None

        # ================= Phase C：确定性收尾（锁内，快） =================
        with self._say_lock:
            self.last_validation_failure = []
            self.last_failure_reason = ""
            # 5b) "本神" 校准 Gate（§21-25）：抑制语境出现"本神"或触发 cooldown → 软拦截
            gated = self.god_gate.gate_output(speech, cal=god_cal)
            if gated is None:
                self.god_gate.note_spoke_god(speech)
                self.last_failure_reason = "god_gate_suppressed"
                return None
            speech = gated
            # 6) 短期重复控制（§40）：**用户发起的直接对话必须收到回应**；
            #    重复控制只影响自主发言节奏，不影响给用户的回应。
            self._recent_acts.append(app.dialogue_act)
            self._recent_acts = self._recent_acts[-3:]
            if not user_initiated and len(self._recent_acts) >= 3 and len(set(self._recent_acts)) == 1:
                return None
            # B3：direct **已展示**回复 → 表面语言跟踪（repetitive-opening guard 用）
            if channel == "DIRECT_USER_TURN":
                self._recent_surfaced.append(speech)
                self._recent_surfaced = self._recent_surfaced[-self._recent_surfaced_limit:]
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
        return speech

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

    def _generate_bounded(self, prompt: str, timeout: Optional[float]) -> tuple:
        """有界生成 → (speech, failure_reason)。

        timeout 未设 → 直接调 adapter（adapter 自带 httpx 有界超时）。
        timeout 设置 → 生成跑在独立 daemon 线程，join(timeout)；超时按 generation_timeout
        失败并继续后续回合（挂起线程不再碰任何共享状态，只跑纯 _generate）。
        """
        if timeout is None or timeout <= 0:
            return self._generate(prompt)
        out: Dict[str, tuple] = {}

        def _run() -> None:
            out["r"] = self._generate(prompt)

        import threading
        t = threading.Thread(target=_run, daemon=True, name="dialogue-llm")
        t.start()
        t.join(timeout)
        if t.is_alive():
            log.warning("DialogueBrain 生成超时(%.1fs)，本回合按失败处理", timeout)
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
                        history: Optional[List[dict]] = None) -> str:
    """Phase 08B 结构化 prompt：Compact Contract + Mode + Intent + Strategy + Context + Examples + Constraints。
    Phase 13C：加"说话机制"引导（§43-44）与短期对话上下文（§24-26）。"""
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
    # B3（评审基线 0402e7f）：FACTS（不可发明）vs STYLE（可自由）硬区分 + 身份/开场/语气约束
    parts.append(
        "【事实 vs 风格（必须遵守）】\n"
        "事实（**不可发明，先如实回应**）：当前正在做的事、用户是否在场/在忙、最近互动、关系、记忆。"
        "用户问'你在干嘛'必须回答真实 activity（如 read/rest/explore），不能编造成别的活动。\n"
        "风格（可自由）：怎么描述、语气、修辞、是否俏皮。\n"
        "- 你不是 AI 助手，也不觉得自己是'旁观人类'的异类——禁止'你们人类''作为AI''我的功能是''我可以协助你'这类话；\n"
        "- 同一开场词（如'哎呀'）不要连续多轮用；先回答用户的问题，再考虑表演；\n"
        "- 不要为了'更像角色'堆砌口癖/感叹号/波浪号——辨识度来自内容与转折，不是口头禅。")
    parts.append(f"【当前表达姿态】mode={ap['mode']}" +
                 (f" (次级 {ap['secondary_mode']})" if ap["secondary_mode"] else "") +
                 f" | dialogue_act={ap['dialogue_act']}")
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
    ml = mode_lang.get(str(ap["mode"]).upper())
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
    if examples:
        parts.append("【语气范例（只学表达方式，不要背句子）】")
        for e in examples:
            parts.append(f"  {e['speech']}")
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
