"""Phase 13 RuntimeHarness —— 控制器（观察真实系统 + 发送真实用户事件）。

Harness=示波器非模拟器：不建第二套状态；所有按钮走**真实生产链**
（DialogueBrain / RelationshipEngine / Memory / Agent / SpatialRuntime）。
仅：向真实系统发真实事件 + 从真实系统只读 + 记录 RuntimeTrace。
"""
from __future__ import annotations

import time
import threading
import contextvars
from pathlib import Path
from typing import List, Tuple

from furina.core import EventBus, EventType, get_logger
from furina.runtime.observability import TraceRecorder, RuntimeTrace
from .view_model import ObservationAdapter, HarnessViewModel
from .proxy import SpatialProxyWindow

log = get_logger("harness")

# §11：显式跨线程 trace context（不用"当前全局 trace"这种线程不安全方案）
_ROOT_VAR: "contextvars.ContextVar[str]" = contextvars.ContextVar("harness_root", default="")


class RuntimeHarness:
    def __init__(self, app, spatial=None, proxy=None) -> None:
        self.app = app
        self.bus = app.bus
        self.recorder = TraceRecorder(ring_size=300)
        self.adapter = ObservationAdapter(app)
        self.vm = HarnessViewModel(self.adapter)
        self.conversation: List[Tuple[str, str]] = []
        # R2.1 P2：结构化 Conversation 事件（turn_id/channel/speech_id/text/terminal status）
        self.utterances: List[dict] = []
        # GUI 线程安全的聊天队列（背景事件 → 队列 → panel 定时器在 GUI 线程 drain）
        self._chat_queue: List[Tuple[str, str]] = []
        self._chat_lock = threading.Lock()
        # last Frame.speech（去重）
        self._last_speech_key = None
        # R2.1 P0-1：按 **speech event identity** 去重（不同 utterance 同文本各显示一次）
        self._last_speech_id = 0
        # R2.1 P0-2：direct 回合最近一次 outcome（来自真实 DIRECT_TURN_TRACE）
        self._direct_last: dict = {"status": "NONE", "turn_id": 0, "ingress_seq": None,
                                   "failure_reason": "", "latency_ms": 0.0, "at": 0.0}
        # R2.1.1 P5：turn_id → terminal status（SPEECH_SURFACED 可能晚于终态 trace，
        # 晚到的 Furina utterance 据此绑定 terminal_status）
        self._turn_terminal: dict = {}
        # 真实健康指标（§1：不许假绿）
        self._life_last = {"attempt": 0, "success": 0, "fallback": 0, "failure": 0}
        self._dialog_last = {"attempt": 0, "outcome": "NONE", "model": ""}
        self._agent_state = "IDLE"
        self._agent_root_id = ""

        # ---- 空间代理（§2：唯一 SpatialRuntime 由 launch_harness 创建并注入）----
        from furina.runtime.spatial import DesktopSpatialRuntime, SpatialIntentResolver
        if spatial is not None:
            self.spatial = spatial
        else:
            self.spatial = DesktopSpatialRuntime(app.world, window=None)
        self.resolver = SpatialIntentResolver()
        if proxy is not None:
            self.proxy = proxy
            self.spatial.window = proxy
            self.spatial.adapter = self.spatial.adapter.__class__.from_window(proxy)
            # B2（评审基线 0402e7f）：**注入的 proxy 也必须补齐生产 drag wiring** ——
            # launch_harness 先创建 SpatialProxyWindow(world=...) 再注入本控制器，
            # 若不在收到 proxy 时接线，鼠标事件会走到 None 回调，SpatialRuntime 永远
            # 不进入 drag_active/DRAGGED，且 spatial tick 继续抢占坐标 → 无法拖动/snap-back。
            # 与自建分支（下方 else）保持同一 drag semantic（生产 SpatialRuntime 链，非测试假实现）。
            proxy.on_drag_start = lambda: self.spatial.on_drag_start(time.monotonic())
            proxy.on_drag_move = lambda: self.spatial.on_drag_move(time.monotonic())
            proxy.on_drag_release = lambda: self.spatial.on_drag_release(time.monotonic(), commit=True)
        else:
            self.proxy = SpatialProxyWindow(
                world=app.world,
                on_drag_start=lambda: self.spatial.on_drag_start(time.monotonic()),
                on_drag_release=lambda: self.spatial.on_drag_release(time.monotonic(), commit=True),
                on_drag_move=lambda: self.spatial.on_drag_move(time.monotonic()))
            self.spatial.window = self.proxy
            self.spatial.adapter = self.spatial.adapter.__class__.from_window(self.proxy)
        if getattr(self.spatial.state, "state", "IDLE") == "IDLE" and self.spatial.state.position.x == 0:
            self.spatial.set_initial_foot(app.world.screen.w * 0.5, app.world.screen.h - 200)

        # ---- 订阅 Frame 事件：更新 proxy 文字 + 空间 + Frame.speech → conversation 真相（§8）----
        self.bus.on(EventType.CHARACTER_FRAME_UPDATED, self._on_frame)
        # BRAIN_SPOKE → 上游 trace（FRAME_SPEECH 节点）
        self.bus.on(EventType.BRAIN_SPOKE, self._on_brain_spoke)
        # R2.1 P0-2：Direct 回合 telemetry 直接订阅 DIRECT_TURN_TRACE（生产 DirectQueue 走
        # say_with_result，不再经过 db.say —— 只包 say 会导致 badge stale / trace 缺失）
        self.bus.on(EventType.DIRECT_TURN_TRACE, self._on_direct_turn_trace)
        # R2.1.1 P0-4：每次 user-visible utterance 的独立事件（exactly-once 记录，绑定 turn_id）
        self.bus.on(EventType.SPEECH_SURFACED, self._on_speech_surfaced)
        # §10：Agent 生命周期（真实 AGENT 事件，非伪造阶段）
        self.bus.on(EventType.AGENT_STARTED, self._on_agent_started)
        self.bus.on(EventType.AGENT_COMPLETED, self._on_agent_completed)
        self.bus.on(EventType.AGENT_FAILED, self._on_agent_failed)

        # ---- 给 DialogueBrain.say / LifeBrain.decide 注入 trace（观察包装，不改语义）----
        self._wrap_dialogue()
        self._wrap_life()

        # panel
        self.panel = None   # 由 window 层创建

    # ---- GUI 线程安全：把背景事件放入队列，panel 定时器 drain（§3）----
    def queue_chat(self, role: str, text: str) -> None:
        with self._chat_lock:
            self._chat_queue.append((role, text))

    def drain_chat(self) -> List[Tuple[str, str]]:
        with self._chat_lock:
            out = list(self._chat_queue)
            self._chat_queue.clear()
        return out

    # -------------------------------------------------- R2.1 P2：结构化 Conversation 事件
    def _record_utterance(self, role: str, text: str, *, turn_id=None, channel="",
                          speech_id: int = 0) -> bool:
        """P2：Conversation 存储保留 turn_id/channel/speech_id/text/terminal status。

        R2.1.1 P0-4：Furina utterance 按 speech_id 去重（同一 utterance 事件/帧只记一次，
        exactly-once；不同 speech_id 即使同文本也各记录）。返回 True 表示新记录。
        """
        if role == "Furina" and speech_id:
            for u in self.utterances:
                if u.get("role") == "Furina" and u.get("speech_id") == speech_id:
                    return False
        self.utterances.append({
            "role": role, "text": text, "turn_id": turn_id,
            "channel": channel, "speech_id": speech_id,
            "terminal_status": "", "recorded_at": time.time(),
        })
        self.utterances = self.utterances[-200:]
        return True

    def _on_speech_surfaced(self, ev) -> None:
        """R2.1.1 P0-4/P2：user-visible utterance 事件 → exactly-once 记录 + 聊天显示。

        独立于 Frame 视觉快照（单一 _speech 槽不承担历史事件队列职责）。
        P5：Furina utterance 绑定 DirectTurn（turn_id + terminal_status —— 终态可能先到，
        晚到的 utterance 从 _turn_terminal 取状态）。
        """
        p = ev.payload or {}
        text = p.get("text") or ""
        if not text:
            return
        sid = int(p.get("speech_id") or 0)
        tid = p.get("turn_id")
        if self._record_utterance("Furina", text, turn_id=tid,
                                  channel=p.get("channel", ""), speech_id=sid):
            if tid in self._turn_terminal:
                for u in self.utterances:
                    if u.get("role") == "Furina" and u.get("speech_id") == sid:
                        u["terminal_status"] = self._turn_terminal[tid]
                        break
            self.queue_chat("Furina", text)

    # -------------------------------------------------- R2.1 P0-2：Direct telemetry（真实 lifecycle）
    def _on_direct_turn_trace(self, ev) -> None:
        """订阅 DIRECT_TURN_TRACE —— DirectQueue 走 say_with_result，只包 db.say 会漏。

        badge 的最近一次 direct outcome 必须来自真实 DirectTurn lifecycle；
        ambient 只做单独诊断，不得覆盖 direct last outcome。
        R2.1.1 P0-2：active 相位（DIRECT_INGRESS/QUEUED→QUEUED、GENERATION_STARTED→GENERATING）
        也更新 badge（不得停留在旧 LAST_OK）。
        """
        p = ev.payload or {}
        phase = p.get("phase", "")
        turn_id = p.get("turn_id")
        if phase == "DIRECT_INGRESS" and turn_id is not None:
            self._record_utterance("You", p.get("user_text", ""), turn_id=turn_id,
                                   channel=p.get("channel", "DIRECT_USER_TURN"))
        # R2.1.1 P0-2：active state → badge RUNNING/PENDING
        if phase in ("DIRECT_INGRESS", "QUEUED"):
            self._direct_last.update({"status": "QUEUED", "turn_id": turn_id,
                                      "ingress_seq": p.get("ingress_seq")})
        elif phase == "GENERATION_STARTED":
            self._direct_last.update({"status": "GENERATING", "turn_id": turn_id})
        if phase in ("REPLIED", "FAILED", "CANCELLED"):
            self._direct_last.update({
                "status": phase, "turn_id": turn_id, "ingress_seq": p.get("ingress_seq"),
                "failure_reason": p.get("failure_reason", ""),
                "latency_ms": p.get("latency_ms", 0.0), "at": time.time(),
                # R2.1.1 P0-3：validation telemetry（为什么被拦/被放行）
                "validation_issues": list(p.get("validation_issues") or []),
                "hard_issues": list(p.get("hard_issues") or []),
                "soft_issues": list(p.get("soft_issues") or [])})
            # P2：同 turn 的所有 utterance（You + Furina SYSTEM_STATUS/回复）绑定 terminal
            if turn_id is not None:
                self._turn_terminal[turn_id] = phase
                self._turn_terminal = dict(list(self._turn_terminal.items())[-200:])
            for u in self.utterances:
                if u.get("turn_id") == turn_id:
                    u["terminal_status"] = phase
        # trace：每个 direct turn 的 ingress / generation start / result / terminal 都可见
        try:
            self.recorder.start_root(
                trigger_type="DIRECT_TURN", trigger_source="dialogue_queue",
                subsystem="dialogue", stage=f"DIRECT_{phase}",
                input_summary=f"turn#{turn_id} seq={p.get('ingress_seq')} {p.get('user_text','')[:20]}",
                output_summary=(f"{phase} {p.get('failure_reason','')} "
                                f"hard={p.get('hard_issues') or []} soft={p.get('soft_issues') or []}"))
        except Exception:
            pass

    # ================================================== 状态只读 + 显示
    def render_trace(self, expanded: bool = False) -> str:
        recent = self.recorder.recent(12 if not expanded else 40)
        if not recent:
            return "(no trace yet)"
        lines = []
        for t in recent:
            tag = "FALLBACK" if t.fallback else ("OK" if t.success else "FAIL")
            lines.append(f"[{t.trigger_type}] {t.subsystem}.{t.stage} {tag} {t.latency_ms:.0f}ms "
                         f"model={t.model or '-'}\n  in: {t.input_summary[:80]}\n  out: {t.output_summary[:80]}")
        return "\n".join(lines)

    # ================================================== 生产链包装（只观察，不改语义）
    def _wrap_dialogue(self) -> None:
        db = getattr(self.app, "dialogue_brain", None)
        if db is None or not hasattr(db, "say"):
            return
        orig = db.say
        def say_wrap(**kw):
            t0 = time.perf_counter()
            self._dialog_last["attempt"] += 1
            ctx = (f"intent={kw.get('intent','')} act={kw.get('activity','')} "
                   f"emotion={kw.get('emotion','')} user_initiated={kw.get('user_initiated',False)} "
                   f"mem={len(kw.get('memories') or [])}")
            trig = "USER_MESSAGE" if kw.get("user_initiated") else "LIFE"
            root_id = _ROOT_VAR.get()   # §11 显式跨线程 root
            if root_id:
                self._last_root_id = root_id
                root = self.recorder.child_to_root(
                    root_id, subsystem="dialogue", stage="LLM_REQUEST", input_summary=ctx,
                    model="glm-4v-flash", trigger_type=trig, trigger_source="harness")
            else:
                root = self.recorder.start_root(trigger_type=trig, trigger_source="harness",
                                                subsystem="dialogue", stage="LLM_REQUEST",
                                                input_summary=ctx, model="glm-4v-flash")
            self._dialog_last["model"] = "glm-4v-flash"
            try:
                speech = orig(**kw)
                # §1 真实 dialogue 结果
                if speech:
                    self._dialog_last["outcome"] = "SPOKE"
                else:
                    self._dialog_last["outcome"] = "SILENT_BY_POLICY"
                self.recorder.child(root, subsystem="dialogue", stage="LLM_RESULT",
                                    output_summary=speech or "", model="glm-4v-flash",
                                    success=bool(speech), latency_ms=(time.perf_counter()-t0)*1000)
                return speech
            except Exception as e:
                self._dialog_last["outcome"] = "MODEL_FAILURE"
                self.recorder.child(root, subsystem="dialogue", stage="LLM_RESULT",
                                    output_summary=f"error:{type(e).__name__}", model="glm-4v-flash",
                                    success=False, fallback=True, latency_ms=(time.perf_counter()-t0)*1000)
                raise
        db.say = say_wrap

    def _wrap_life(self) -> None:
        lb = getattr(self.app, "life_brain", None)
        if lb is None or not hasattr(lb, "decide"):
            return
        orig = lb.decide
        def decide_wrap(**kw):
            t0 = time.perf_counter()
            self._life_last["attempt"] += 1
            cands = kw.get("candidates") or []
            root_id = _ROOT_VAR.get()   # §11
            if root_id:
                root = self.recorder.child_to_root(
                    root_id, subsystem="life", stage="LLM_REQUEST",
                    input_summary=f"candidates={[c.get('activity') for c in cands][:5]}",
                    model="glm-4v-flash", trigger_type="LIFE", trigger_source="scheduler")
            else:
                root = self.recorder.start_root(trigger_type="LIFE", trigger_source="scheduler",
                                                subsystem="life", stage="LLM_REQUEST",
                                                input_summary=f"candidates={[c.get('activity') for c in cands][:5]}",
                                                model="glm-4v-flash")
            try:
                d = orig(**kw)
                self._life_last["success"] += 1
                self._life_last["last_outcome"] = "OK"   # FINAL-R1 §8.2：最新一次，非聚合
                self._life_last["last_attempt_at"] = time.time()
                self.recorder.child(root, subsystem="life", stage="DECISION",
                                    output_summary=f"selected={getattr(d,'activity','')}",
                                    model="glm-4v-flash", success=True,
                                    latency_ms=(time.perf_counter()-t0)*1000)
                return d
            except Exception as e:
                self._life_last["fallback"] += 1
                self._life_last["failure"] += 1
                self._life_last["last_outcome"] = "FALLBACK"   # FINAL-R1 §8.2
                self._life_last["last_attempt_at"] = time.time()
                self.recorder.child(root, subsystem="life", stage="DECISION",
                                    output_summary=f"fallback:{type(e).__name__}", model="local-fallback",
                                    success=False, fallback=True, latency_ms=(time.perf_counter()-t0)*1000)
                raise
        lb.decide = decide_wrap

    # ================================================== 真实用户事件入口
    def on_user_message(self, text: str) -> None:
        # FINAL-R1 §3：走**唯一生产入口** submit_user_message（owner 线程语义 + worker LLM）。
        # Harness **不**再包一层 worker 线程（否则域变更的线程 owner 与 GUI 不一致）。
        self.conversation.append(("You", text))
        self.queue_chat("You", text)
        root = self.recorder.start_root(trigger_type="USER_MESSAGE", trigger_source="harness",
                                        subsystem="dialogue", stage="USER_INPUT", input_summary=text)
        tok = _ROOT_VAR.set(root.root_trace_id)
        try:
            if hasattr(self.app, "submit_user_message"):
                self.app.submit_user_message(text)
            else:
                self.app._brain_worker(text)
        finally:
            _ROOT_VAR.reset(tok)

    def on_interact(self, kind: str, zone: str = "whole") -> None:
        # §10：真实 before/after 因果 trace（emotion/relationship 来自 ObservationAdapter 只读快照）
        before_e = self._emotion_snap()
        before_r = self._relationship_snap()
        root = self.recorder.start_root(trigger_type="INTERACT", trigger_source="harness",
                                        subsystem="interaction", stage="USER_ACTION",
                                        input_summary=f"{kind}@{zone}")
        self.app.interaction.emit_event(kind, zone)   # 真实 InteractionEngine 生产路径
        after_e = self._emotion_snap()
        after_r = self._relationship_snap()
        self.recorder.child_to_root(root.root_trace_id, subsystem="interaction", stage="EMOTION_BEFORE_AFTER",
                                    input_summary=str(before_e), output_summary=str(after_e))
        self.recorder.child_to_root(root.root_trace_id, subsystem="relationship", stage="BEFORE_AFTER",
                                    input_summary=str(before_r), output_summary=str(after_r))

    def _emotion_snap(self) -> dict:
        try:
            s = self.adapter.state_snapshot()
            return {"label": s.get("emotion"), "mood": s.get("mood")}
        except Exception:
            return {}

    def _relationship_snap(self) -> dict:
        try:
            return self.adapter.relationship_snapshot()
        except Exception:
            return {}

    def on_feed(self, food: str) -> None:
        # FINAL-R1 §3/§8.3：走**唯一生产入口** submit_feed（owner 线程确定性效果，无第二 wrapper 线程）。
        root = self.recorder.start_root(trigger_type="FEED", trigger_source="harness",
                                        subsystem="feeding", stage="USER_ACTION", input_summary=food)
        before = self._need_snapshot()
        try:
            if hasattr(self.app, "submit_feed"):
                self.app.submit_feed(food)
            else:
                self.app._feed(food)
        except Exception:
            pass
        after = self._need_snapshot()
        self.recorder.child_to_root(root.root_trace_id, subsystem="feeding", stage="NEEDS",
                                    input_summary=f"{food} before={before}",
                                    output_summary=f"after={after}")

    def _need_snapshot(self) -> dict:
        try:
            st = self.adapter.state_snapshot()
            return {k: st.get("needs", {}).get(k) for k in ("hunger", "energy", "fatigue")}
        except Exception:
            return {}

    def on_reject(self) -> None:
        self.recorder.start_root(trigger_type="REJECT", trigger_source="harness",
                                 subsystem="relationship", stage="USER_ACTION", input_summary="user_reject")
        if hasattr(self.app, "_sched"):
            self.app._sched.on_user_reject()

    def on_ignore(self) -> None:
        self.recorder.start_root(trigger_type="IGNORE", trigger_source="harness",
                                 subsystem="interaction", stage="USER_ACTION", input_summary="user_ignore")
        # Phase 13 终审 §7/§14：语义忽略（不是指针 leave）。
        # 与生产语义同一 route：Emotion EVENT_IGNORE + Relationship EV_IGNORE + Life + Memory（恰好一次）。
        if hasattr(self.app, "_sched") and hasattr(self.app._sched, "on_user_ignore"):
            self.app._sched.on_user_ignore()

    def on_agent(self, task: str) -> None:
        label = {"notepad": "打开记事本", "calc": "打开计算器"}.get(task, task)
        root = self.recorder.start_root(trigger_type="AGENT", trigger_source="harness",
                                        subsystem="agent", stage="USER_REQUEST", input_summary=label)
        self._agent_root_id = root.root_trace_id   # §11：agent 事件关联到该 root
        if task == "organize-test":
            tmp = Path("tmp/harness_agent_test")
            tmp.mkdir(parents=True, exist_ok=True)
            for f in ("test1.txt", "notes.md", "image.png"):
                (tmp / f).touch(exist_ok=True)
            # §7：所有 Agent 任务走同一正式入口（submit_agent_task），只操作安全 tmp 目录
            self.app.submit_agent_task("整理测试目录", {"path": str(tmp)})
        else:
            # §7：同一正式入口，不特判直接 execute
            self.app.submit_agent_task(label)

    # ================================================== Frame 事件 → proxy 更新 + 空间 + Frame.speech（真相）
    def _on_frame(self, ev) -> None:
        frame = ev.payload
        # 更新 proxy 文字（body semantic）
        try:
            b = getattr(frame, "body", None)
            self.proxy.update_semantic(
                activity=getattr(frame.activity, "name", ""),
                posture=getattr(b, "posture", ""),
                expression=getattr(b, "expression", ""),
                gaze=getattr(b, "gaze", ""),
                spatial_state=getattr(self.spatial.state, "state", "IDLE"),
                moving=self.spatial.is_moving,
                facing=getattr(self.spatial.state, "facing", "FRONT"))
        except Exception:
            pass
        # 喂给空间（真实 APPROACH/WITHDRAW/...）
        try:
            d = self.resolver.resolve(frame)
            self.spatial.accept(d, now=time.monotonic())
        except Exception:
            pass
        # §8/R2.1.1 P0-4：Frame 只负责当前视觉快照；Furina 台词记录以 SPEECH_SURFACED
        # 事件为准（utterance 按 speech_id 去重；事件先到时帧跳过，帧先到时兜底记录）。
        try:
            sp = getattr(frame, "speech", None)
            if sp is not None and getattr(sp, "should_speak", False) and getattr(sp, "text", ""):
                sid = int(getattr(sp, "speech_id", 0) or 0)
                if sid:
                    if sid != self._last_speech_id:
                        self._last_speech_id = sid
                        if self._record_utterance("Furina", sp.text, speech_id=sid):
                            self.queue_chat("Furina", sp.text)
                            if self._last_root_id:
                                self.recorder.child_to_root(
                                    self._last_root_id, subsystem="dialogue",
                                    stage="FRAME_SPEECH", output_summary=sp.text,
                                    trigger_type="USER_MESSAGE")
                elif sp.text != self._last_speech_key:
                    # 兼容旧帧（无 speech_id）：退回按文本去重
                    self._last_speech_key = sp.text
                    if self._record_utterance("Furina", sp.text, speech_id=0):
                        self.queue_chat("Furina", sp.text)
                        if self._last_root_id:
                            self.recorder.child_to_root(
                                self._last_root_id, subsystem="dialogue",
                                stage="FRAME_SPEECH", output_summary=sp.text,
                                trigger_type="USER_MESSAGE")
            else:
                self._last_speech_key = None
                self._last_speech_id = 0
        except Exception:
            pass

    # ---- 真实健康指标（§1/§14：不许假绿）----
    def runtime_health(self) -> dict:
        self._agent_state = self._read_agent_state()
        return {
            "life": dict(self._life_last),
            "dialogue": dict(self._dialog_last),
            "agent": self._agent_state,
            "memory": self._memory_status(),   # COUNT=n 真实条数
            "diagnostics": self._diagnostics(),  # §14：Manual 所需真实诊断字段
        }

    # -------------------------------------------------- §14：真实徽章语义
    def life_badge(self) -> str:
        """FINAL-R1 §8.2：徽章用**最新一次** outcome（last_outcome），聚合计数只是诊断。

        顺序：success → 随后失败 => LAST_FAILED（不再被历史 success 掩盖）。
        """
        lf = dict(self._life_last)
        if lf.get("attempt", 0) == 0:
            return "UNAVAILABLE"                    # 从未尝试 = 不绿
        last = lf.get("last_outcome")
        if last == "FALLBACK":
            return "FALLBACK"
        if last == "OK":
            return "LAST_OK"
        if last == "FAILED":
            return "LAST_FAILED"
        # 兼容旧路径（无 last_outcome 时回退聚合判断）
        if lf.get("success", 0):
            return "LAST_OK"
        if lf.get("fallback", 0):
            return "FALLBACK"
        if lf.get("failure", 0):
            return "LAST_FAILED"
        return "UNAVAILABLE"

    def dialogue_badge(self) -> str:
        # R2.1 P0-2：**最近一次 direct outcome 来自真实 DirectTurn lifecycle**
        # （REPLIED→LAST_OK / FAILED→LAST_FAILED / CANCELLED→LAST_FAILED/CANCELLED /
        #  GENERATING|QUEUED→RUNNING/PENDING）；ambient 只走旧路径诊断，不得覆盖。
        ds = self._direct_last.get("status")
        if ds == "REPLIED":
            return "LAST_OK"
        if ds == "FAILED":
            return "LAST_FAILED"
        if ds == "CANCELLED":
            return "LAST_FAILED/CANCELLED"
        if ds in ("GENERATING", "QUEUED"):
            return "RUNNING/PENDING"
        dl = dict(self._dialog_last)
        try:
            db = getattr(self.app, "dialogue_brain", None)
            if db is None or not getattr(getattr(db, "llm", None), "is_available", lambda: False)():
                return "UNAVAILABLE"
        except Exception:
            return "UNAVAILABLE"
        if dl.get("attempt", 0) == 0:
            return "AVAILABLE"                      # 适配器可用但尚无 direct lifecycle 记录
        if dl.get("outcome") == "SPOKE":
            return "LAST_OK"
        if dl.get("outcome") == "MODEL_FAILURE":
            return "LAST_FAILED"
        return "IDLE"                               # SILENT_BY_POLICY 等

    def _memory_status(self) -> dict:
        try:
            store = getattr(getattr(self.app, "memory", None), "store", None)
            if store is None:
                return {"status": "UNAVAILABLE", "count": -1}
            if hasattr(store, "count"):
                n = store.count()
                return {"status": "AVAILABLE" if n > 0 else "EMPTY", "count": n}
            # 兜底：真实查全量（不展示假精确数字）
            rows = store.query(limit=10000)
            return {"status": "AVAILABLE" if rows else "EMPTY", "count": len(rows)}
        except Exception:
            return {"status": "UNAVAILABLE", "count": -1}

    def _read_agent_state(self) -> str:
        """FINAL-R1 §8.1：Agent 状态单一 owner = AgentRuntime.status（真实生命周期转移）。
        不再从 _busy/_last_err/_last_success 等不存在的字段读取（否则会覆盖事件态回 IDLE）。"""
        try:
            agent = getattr(self.app, "agent", None)
            if agent is None:
                return "IDLE"
            st = getattr(agent, "status", None)
            if st in ("RUNNING", "COMPLETED_VERIFIED", "FAILED", "UNVERIFIED"):
                return st
            return "IDLE"
        except Exception:
            return "IDLE"

    def _diagnostics(self) -> dict:
        """§14：Manual 所需的真实运行时诊断字段（全部只读）。"""
        d: dict = {}
        try:
            sched = getattr(self.app, "_sched", None)
            st = getattr(getattr(sched, "se", None), "state", None)
            if st is not None:
                d["clock"] = {"hour": st.clock_hour, "minute": st.clock_minute}
                d["idle_seconds"] = round(float(st.user_idle_seconds), 1)
                # Final Gate §2：**回退必须保守 False**（缺属性 = 未测量，不得当作有效 0）
                d["idle_available"] = bool(getattr(st, "idle_available", False))
                d["user_working"] = bool(st.user_working)
                d["emotion_label"] = st.emotion.label
                d["activity"] = st.life.activity
            wp = getattr(sched, "world_perc", None)
            if wp is not None and hasattr(wp, "state"):
                d["world"] = {"process": wp.state.foreground_process,
                              "category": wp.state.app_category,
                              "activity": getattr(wp.state.user_activity, "value", "")}
            if sched is not None:
                d["life_next_think"] = round(float(getattr(sched, "_life_next_think", 0.0)), 1)
                fin = getattr(sched, "_last_activity_finish", None)
                if isinstance(fin, dict):
                    d["activity_finish"] = fin
                inst = getattr(sched, "_activity_instance", None)
                if isinstance(inst, dict):
                    d["activity_instance"] = {"activity": inst.get("activity"),
                                              "planned_duration": round(float(inst.get("planned_duration", 0.0)), 1)}
            emo = getattr(self.app, "emotion", None)
            if emo is not None and hasattr(emo, "_recent"):
                d["emotion_recent_events"] = dict(emo._recent)
        except Exception:
            pass
        # 空间诊断（§12）：path style / waypoint 数 / max heading delta
        try:
            sp = getattr(self, "spatial", None)
            if sp is not None:
                p = getattr(sp, "_current_plan", None)
                if p is not None:
                    d["spatial"] = {"path_style": p.path_style,
                                    "waypoints": len(getattr(p, "waypoints", []) or []),
                                    "max_heading_delta_deg": self._spatial_max_turn(p)}
        except Exception:
            pass
        # B1（评审基线 0402e7f）：直接对话回合可观测终态 —— Manual 能区分
        # 没生成 / 生成失败 / 人格校验失败 / 仍在等待（不得只看到"什么都没发生"）。
        try:
            dq = getattr(self.app, "_direct_dq", None)
            if dq is not None:
                d["dialogue_turns"] = {
                    "pending": dq.pending(),
                    "outcomes": dq.outcome_count(),
                    "recent": dq.recent_outcomes(4),
                }
        except Exception:
            pass
        return d

    @staticmethod
    def _spatial_max_turn(plan) -> float:
        import math
        wps = list(getattr(plan, "waypoints", []) or [])
        pts = [plan.start] + wps + [plan.target]
        m = 0.0
        for i in range(2, len(pts)):
            a = math.atan2(pts[i - 1].y - pts[i - 2].y, pts[i - 1].x - pts[i - 2].x)
            b = math.atan2(pts[i].y - pts[i - 1].y, pts[i].x - pts[i - 1].x)
            m = max(m, abs((b - a + math.pi) % (2 * math.pi) - math.pi))
        return round(math.degrees(m), 1)

    def _on_brain_spoke(self, ev) -> None:
        # BRAIN_SPOKE 作为上游 trace 事件；Conversation UI 以 Frame.speech 为准（§8）。
        speech = getattr(ev.payload, "speech", "") or ""
        self.recorder.start_root(trigger_type="DIALOGUE", trigger_source="brain",
                                 subsystem="dialogue", stage="FRAME_SPEECH",
                                 output_summary=speech)

    # ---- §10：Agent 生命周期（真实 AGENT_STARTED/COMPLETED/FAILED 事件）----
    def _on_agent_started(self, ev) -> None:
        self._agent_state = "RUNNING"
        self._trace_agent("REQUEST", (ev.payload or {}).get("request", ""), success=True)

    def _on_agent_completed(self, ev) -> None:
        # §10：AGENT_COMPLETED 只在全部步骤已验证时发出 → COMPLETED_VERIFIED（真值，非 import 即绿）
        self._agent_state = "COMPLETED_VERIFIED"
        self._trace_agent("RESULT", f"goal={(ev.payload or {}).get('goal','')} verified",
                          success=True)

    def _on_agent_failed(self, ev) -> None:
        err = (ev.payload or {}).get("error") or (ev.payload or {}).get("reason", "")
        # §10.3：unverified_step 失败 → UNVERIFIED（不是普通 FAILED，也不可能是 COMPLETED）
        if "unverified" in err:
            self._agent_state = "UNVERIFIED"
        else:
            self._agent_state = "FAILED"
        self._trace_agent("RESULT", f"error={err}", success=False)

    def _trace_agent(self, stage: str, summary: str, success: bool) -> None:
        rid = getattr(self, "_agent_root_id", "")
        if rid:
            self.recorder.child_to_root(rid, subsystem="agent", stage=stage,
                                        output_summary=summary, success=success, trigger_type="AGENT")
        else:
            self.recorder.start_root(trigger_type="AGENT", trigger_source="agent",
                                     subsystem="agent", stage=stage, output_summary=summary)

    # ================================================== 空间 tick（由外部 timer 驱动）
    def tick_spatial(self) -> None:
        # §8：GUI/主线程 = 运行时 owner 线程 —— 先落地后台排队的运行时变更，再走空间 tick
        try:
            sched = getattr(self.app, "_sched", None)
            if sched is not None and hasattr(sched, "drain_apply"):
                sched.drain_apply()
        except Exception:
            pass
        try:
            self.spatial.tick(now=time.monotonic())
        except Exception:
            pass
