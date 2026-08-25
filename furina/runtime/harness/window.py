"""Phase 13 RuntimeTruthPanel —— 固定主窗口（清楚优先，不追求美术 §135）。

显示：状态徽章 / CURRENT LIFE / CONVERSATION / INTERACT / AGENT / LAST TRACE。
更新 5-10Hz，由 controller 从**真实 Runtime** 只读取数。按钮全部走真实生产链。
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QLineEdit, QGroupBox, QGridLayout, QScrollArea,
)


class RuntimeTruthPanel(QWidget):
    def __init__(self, view_model, controller) -> None:
        super().__init__()
        self.vm = view_model
        self.controller = controller
        self.setWindowTitle("FURINA RUNTIME — Harness")
        self.resize(640, 760)
        self._build_ui()
        # 5Hz 刷新（§89）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(200)

    # -------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # 顶栏徽章
        self.badges = QLabel("")
        self.badges.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        root.addWidget(self.badges)

        root.addWidget(self._life_group())
        root.addWidget(self._conversation_group())
        root.addWidget(self._interact_group())
        root.addWidget(self._agent_group())
        root.addWidget(self._trace_group())

        self._refresh()

    def _life_group(self) -> QGroupBox:
        g = QGroupBox("CURRENT LIFE")
        lay = QGridLayout(g)
        self.life = QLabel("")
        self.life.setWordWrap(True)
        self.life.setFont(QFont("Consolas", 9))
        lay.addWidget(self.life, 0, 0)
        return g

    def _conversation_group(self) -> QGroupBox:
        g = QGroupBox("CONVERSATION")
        lay = QVBoxLayout(g)
        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setFont(QFont("Microsoft YaHei", 9))
        lay.addWidget(self.chat)
        h = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("对芙宁娜说…")
        self.entry.returnPressed.connect(self._on_send)
        h.addWidget(self.entry, 1)
        b = QPushButton("发送")
        b.clicked.connect(self._on_send)
        h.addWidget(b)
        lay.addLayout(h)
        return g

    def _interact_group(self) -> QGroupBox:
        g = QGroupBox("INTERACT")
        lay = QHBoxLayout(g)
        for label, fn in [("摸头", lambda: self.controller.on_interact("petting", "head")),
                          ("戳一下", lambda: self.controller.on_interact("poke", "body")),
                          ("呼唤", lambda: self.controller.on_interact("click", "whole")),
                          ("拒绝", lambda: self.controller.on_reject()),
                          ("忽略", lambda: self.controller.on_ignore()),
                          ("蛋糕", lambda: self.controller.on_feed("cake")),
                          ("茶", lambda: self.controller.on_feed("tea")),
                          ("面包", lambda: self.controller.on_feed("bread"))]:
            btn = QPushButton(label)
            btn.clicked.connect(fn)
            lay.addWidget(btn)
        lay.addStretch(1)
        return g

    def _agent_group(self) -> QGroupBox:
        g = QGroupBox("AGENT")
        lay = QHBoxLayout(g)
        for label, task in [("打开记事本", "notepad"), ("打开计算器", "calc"),
                            ("整理测试目录", "organize-test")]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, t=task: self.controller.on_agent(t))
            lay.addWidget(btn)
        lay.addStretch(1)
        return g

    def _trace_group(self) -> QGroupBox:
        g = QGroupBox("LAST TRACE")
        lay = QVBoxLayout(g)
        self.trace = QPlainTextEdit()
        self.trace.setReadOnly(True)
        self.trace.setFont(QFont("Consolas", 8))
        self.trace.setMaximumHeight(240)
        lay.addWidget(self.trace)
        toggle = QPushButton("展开 Trace")
        toggle.clicked.connect(self._toggle_trace)
        lay.addWidget(toggle)
        self._trace_expanded = False
        return g

    # -------------------------------------------------- refresh
    def _refresh(self) -> None:
        try:
            # §3：在 GUI 线程 drain 背景事件队列（QWidget mutation 只在此线程）
            for role, text in self.controller.drain_chat():
                self.append_chat(role, text)
            # §1/§14：徽章来自真实运行时事实（不许假绿）：AVAILABLE/UNAVAILABLE/LAST_OK/LAST_FAILED/FALLBACK
            health = self.controller.runtime_health()
            life_h = health["life"]; dia = health["dialogue"]; agent = health["agent"]
            mem = health.get("memory", {})
            life_badge = self.controller.life_badge()
            dlg_badge = self.controller.dialogue_badge()
            mem_badge = f"{mem.get('status','?')} COUNT={mem.get('count',-1)}"
            self.badges.setText(
                f"BACKEND RC1  |  Life:{life_badge}  |  Dialogue:{dlg_badge}  |  Agent:{agent}  |  Memory:{mem_badge}  |  ● LIVE")
            life = self.vm.current_life()
            # §14：诊断字段（真实只读）
            diag = health.get("diagnostics", {})
            d_lines = []
            for k in ("clock", "idle_seconds", "user_working", "world", "emotion_recent_events",
                      "life_next_think", "activity_finish", "activity_instance", "spatial"):
                if k in diag:
                    d_lines.append(f"{k} {diag[k]}")
            self.life.setText(
                f"Activity     {life['activity']}\n"
                f"Brain        {life['brain']}   Fallback {life['fallback']}\n"
                f"Emotion      {life['emotion']}\n"
                f"Relationship {life['relationship']}\n"
                f"Body         {life['body']}\n"
                f"Spatial      {life['spatial']}\n"
                + ("\n".join(f"Diag: {x}" for x in d_lines) if d_lines else ""))
            if self._trace_expanded:
                self.trace.setPlainText(self.controller.render_trace(expanded=True))
            else:
                self.trace.setPlainText(self.controller.render_trace(expanded=False))
        except Exception:
            pass

    def append_chat(self, role: str, text: str) -> None:
        self.chat.appendPlainText(f"{role}: {text}")

    def _toggle_trace(self) -> None:
        self._trace_expanded = not self._trace_expanded
        self._refresh()

    def _on_send(self) -> None:
        text = self.entry.text().strip()
        if text:
            self.entry.clear()
            # 只由 controller.on_user_message 入队；drain 在 GUI 线程统一显示（避免重复）
            self.controller.on_user_message(text)

    def closeEvent(self, ev) -> None:
        self._timer.stop()
        ev.accept()
