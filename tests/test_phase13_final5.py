"""Phase 13 终审 Batch D：§14 Harness 真值徽章（不许假绿）。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from furina.runtime.harness.controller import RuntimeHarness
from furina.runtime.world import DesktopWorld


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _fake_app():
    app = SimpleNamespace()
    app.state = SimpleNamespace(state=SimpleNamespace(
        life=SimpleNamespace(activity="read", macro=SimpleNamespace(value="living"), reason=""),
        emotion=SimpleNamespace(label="calm"), needs=SimpleNamespace(),
        user_working=False, user_idle_seconds=10.0,
        clock_hour=14, clock_minute=5))
    app.relationship = SimpleNamespace(state=None)
    app.memory = SimpleNamespace(store=SimpleNamespace(count=lambda: 5))
    app._sched = SimpleNamespace(
        current_frame=lambda: None,
        se=SimpleNamespace(state=SimpleNamespace(
            clock_hour=14, clock_minute=5, user_idle_seconds=10.0, user_working=False,
            emotion=SimpleNamespace(label="calm"), life=SimpleNamespace(activity="read"))))
    app.life_brain = None
    app.dialogue_brain = SimpleNamespace(llm=SimpleNamespace(is_available=lambda: True))
    app.world = DesktopWorld(1920, 1080)
    app.bus = SimpleNamespace(on=lambda *a, **k: None)
    app.agent = SimpleNamespace(_busy=False, _last_err=None, _last_success=False)
    app.emotion = SimpleNamespace(_recent={})
    return app


def _harness():
    return RuntimeHarness(_fake_app())


def test_harness_badges_never_green_by_import(qapp):
    """没有真实尝试/成功前：Life/Dialogue 不得是 LAST_OK，Agent 是 IDLE（不许 import 即绿）。"""
    h = _harness()
    assert h.life_badge() == "UNAVAILABLE", "无任何 Life 尝试不得显示 glm ✓"
    assert h.dialogue_badge() in ("AVAILABLE", "UNAVAILABLE"), "无真实成功调用不得是 LAST_OK"
    assert h._read_agent_state() == "IDLE", "Agent 未运行不得显示 ✓"


def test_harness_last_failure_not_green(qapp):
    h = _harness()
    h._dialog_last["attempt"] = 1
    h._dialog_last["outcome"] = "MODEL_FAILURE"
    assert h.dialogue_badge() == "LAST_FAILED", "最近失败不得是绿"
    h._life_last["attempt"] = 1
    h._life_last["failure"] = 1
    assert h.life_badge() == "LAST_FAILED"


def test_harness_fallback_not_green(qapp):
    h = _harness()
    h._life_last["attempt"] = 2
    h._life_last["fallback"] = 2
    assert h.life_badge() == "FALLBACK"


def test_harness_agent_unverified_not_green(qapp):
    h = _harness()
    h._on_agent_failed(SimpleNamespace(payload={"reason": "unverified_step:0:app.launch"}))
    assert h._agent_state == "UNVERIFIED", "未验证失败必须是 UNVERIFIED"
    h._on_agent_completed(SimpleNamespace(payload={"goal": "x"}))
    assert h._agent_state == "COMPLETED_VERIFIED"


def test_harness_memory_count_truthful(qapp):
    h = _harness()
    mem = h._memory_status()
    assert mem["count"] == 5, "COUNT 必须来自真实 count()"
    assert mem["status"] == "AVAILABLE"


def test_harness_diagnostics_present(qapp):
    h = _harness()
    d = h._diagnostics()
    assert "clock" in d and d["clock"]["hour"] == 14
    assert "idle_seconds" in d
    assert "emotion_label" in d


def test_harness_feed_same_production_path(qapp):
    """§14（评审契约名）：Harness Feed 与 GUI 同一生产路径（app._feed）。"""
    import furina.runtime.harness.controller as C
    src = open(C.__file__, encoding="utf-8").read()
    assert "self.app._feed(food)" in src


def test_harness_ignore_uses_semantic_ignore(qapp):
    """§14（评审契约名）：Harness Ignore 走语义忽略路由（非指针 leave）。"""
    import furina.runtime.harness.controller as C
    src = open(C.__file__, encoding="utf-8").read()
    assert "on_user_ignore" in src
    assert 'emit_event("leave", "whole")' not in src
