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
        # GUI 线程安全的聊天队列（背景事件 → 队列 → panel 定时器在 GUI 线程 drain）
        self._chat_queue: List[Tuple[str, str]] = []
        self._chat_lock = threading.Lock()
        # last Frame.speech（去重）
        self._last_speech_key = None
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
                self.recorder.child(root, subsystem="life", stage="DECISION",
                                    output_summary=f"selected={getattr(d,'activity','')}",
                                    model="glm-4v-flash", success=True,
                                    latency_ms=(time.perf_counter()-t0)*1000)
                return d
            except Exception as e:
                self._life_last["fallback"] += 1
                self._life_last["failure"] += 1
                self.recorder.child(root, subsystem="life", stage="DECISION",
                                    output_summary=f"fallback:{type(e).__name__}", model="local-fallback",
                                    success=False, fallback=True, latency_ms=(time.perf_counter()-t0)*1000)
                raise
        lb.decide = decide_wrap

    # ================================================== 真实用户事件入口
    def on_user_message(self, text: str) -> None:
        self.conversation.append(("You", text))
        self.queue_chat("You", text)
        root = self.recorder.start_root(trigger_type="USER_MESSAGE", trigger_source="harness",
                                        subsystem="dialogue", stage="USER_INPUT", input_summary=text)
        # §11：后台线程显式承载 root_trace_id（contextvar，线程安全；两条消息不串）
        def _work():
            tok = _ROOT_VAR.set(root.root_trace_id)
            try:
                self.app._brain_worker(text)
            finally:
                _ROOT_VAR.reset(tok)
        threading.Thread(target=_work, daemon=True).start()

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
        # §9：食物 deterministic effect 立即执行，但 DialogueBrain 调用（_feed 内含）放后台，不阻塞 GUI。
        root = self.recorder.start_root(trigger_type="FEED", trigger_source="harness",
                                        subsystem="feeding", stage="USER_ACTION", input_summary=food)
        threading.Thread(target=self._apply_feed, args=(food, root.trace_id), daemon=True).start()

    def _apply_feed(self, food: str, root_id: str) -> None:
        before = self._need_snapshot()
        try:
            self.app._feed(food)     # 真实喂食链（effect + memory + life interrupt + 背景 Dialogue 交给 _feed 内部）
        except Exception:
            pass
        after = self._need_snapshot()
        self.recorder.child_to_root(root_id, subsystem="feeding", stage="NEEDS",
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
        # 映射到既有 interaction 语义（不新建后端体系 §41）
        self.app.interaction.emit_event("leave", "whole")

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
        # §8：Conversation 的最终语言真相 = CharacterRuntimeFrame.speech（去重）
        try:
            sp = getattr(frame, "speech", None)
            if sp is not None and getattr(sp, "should_speak", False) and getattr(sp, "text", ""):
                if sp.text != self._last_speech_key:
                    self._last_speech_key = sp.text
                    self.queue_chat("Furina", sp.text)
                    # §11：FRAME_SPEECH 关联到最近 root（best-effort，frame 紧随 dialogue）
                    if self._last_root_id:
                        self.recorder.child_to_root(self._last_root_id, subsystem="dialogue",
                                                    stage="FRAME_SPEECH", output_summary=sp.text,
                                                    trigger_type="USER_MESSAGE")
            else:
                self._last_speech_key = None
        except Exception:
            pass

    # ---- 真实健康指标（§1：不许假绿）----
    def runtime_health(self) -> dict:
        self._agent_state = self._read_agent_state()
        return {
            "life": dict(self._life_last),
            "dialogue": dict(self._dialog_last),
            "agent": self._agent_state,
            "memory": self._memory_status(),   # §13：不展示假精确数字
        }

    def _memory_status(self) -> str:
        try:
            store = getattr(getattr(self.app, "memory", None), "store", None)
            if store is None:
                return "UNAVAILABLE"
            # 只判 AVAILABLE / EMPTY（不展示假精确行数）
            has = len(store.query(limit=1, status=None)) > 0
            return "AVAILABLE" if has else "EMPTY"
        except Exception:
            return "UNAVAILABLE"

    def _read_agent_state(self) -> str:
        try:
            agent = getattr(self.app, "agent", None)
            if agent is None:
                return "IDLE"
            if getattr(agent, "_busy", False):
                return "RUNNING"
            if getattr(agent, "_last_err", None):
                return "FAILED"
            if getattr(agent, "_last_success", False):
                return "SUCCESS"
            return "IDLE"
        except Exception:
            return "IDLE"

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
        self._agent_state = "SUCCESS"
        self._trace_agent("RESULT", f"goal={(ev.payload or {}).get('goal','')}", success=True)

    def _on_agent_failed(self, ev) -> None:
        self._agent_state = "FAILED"
        err = (ev.payload or {}).get("error") or (ev.payload or {}).get("reason", "")
        self._trace_agent("RESULT", f"error={err}", success=False)

    def _trace_agent(self, stage: str, summary: str, success: bool) -> None:
        rid = getattr(self, "_agent_root_id", "")
        if rid:
            self.recorder.child_to_root(rid, subsystem="agent", stage=stage,
                                        output_summary=summary, success=success, trigger_type="AGENT")
        else:
            self.recorder.start_root(trigger_type="AGENT", trigger_source="agent",
                                     subsystem="agent", stage=stage, output_summary=summary,
                                     success=success)

    # ================================================== 空间 tick（由外部 timer 驱动）
    def tick_spatial(self) -> None:
        try:
            self.spatial.tick(now=time.monotonic())
        except Exception:
            pass
