"""芙宁娜桌面伙伴入口。

用法：
    python main.py                 # 启动桌面窗口（骨架）
    python main.py --selfcheck     # 不启动 GUI，跑模块导入/自检
"""
from __future__ import annotations

import sys


def selfcheck() -> int:
    """不启动 GUI 的骨架自检：验证各模块可导入、配置可加载、事件总线可用。"""
    from furina.config import load_config
    from furina.core import EventBus, EventType
    from furina.state import StateEngine
    from furina.behavior import BehaviorEngine, BehaviorDefinition
    from furina.interaction import InteractionEngine
    from furina.assets.asset_manifest import AssetResolver, AssetManifest, AssetQuery
    from furina.memory import MemoryEngine, MemoryStore
    from furina.director import Director
    from furina.agent import ToolRegistry, PermissionManager, AgentRuntime
    from furina.agent.tools import ALL_TOOLS

    cfg = load_config()
    bus = EventBus()
    # 事件广播冒烟
    got = []
    bus.on(EventType.STATE_CHANGED, lambda e: got.append(e.payload))
    bus.emit(EventType.STATE_CHANGED, payload="ok")
    assert got == ["ok"], "事件总线异常"

    # 各模块 instantiate
    se = StateEngine(bus)
    be = BehaviorEngine(bus)
    be.register(BehaviorDefinition("idle", base_utility=5))
    inter = InteractionEngine(bus)
    manifest = AssetManifest()
    resolver = AssetResolver(manifest)
    store = MemoryStore(cfg.db_path)
    mem = MemoryEngine(bus, store)
    director = Director(bus)
    tools = ToolRegistry()
    for t in ALL_TOOLS:
        tools.register(t())
    perm = PermissionManager()
    agent = AgentRuntime(bus, tools, perm)

    # 一段人工状态流
    se.state.user_working = True
    state = se.state
    state.needs.fatigue = 80
    cand = se.generate_intent(state)
    action = be.choose(state.snapshot())
    print(f"[selfcheck] intent={cand.intent.action} (utility={cand.utility:.1f})  behavior={action}")
    print(f"[selfcheck] LLM provider={cfg.llm.provider} model={cfg.llm.model} vision={cfg.llm.supports_vision}")
    print(f"[selfcheck] DB={cfg.db_path}")
    print("SELFCHECK OK")
    return 0


def smoke() -> int:
    """启动真实 GUI，1.5s 后自动退出（验证窗口/渲染不崩溃）。"""
    from PySide6.QtCore import QTimer
    from furina.app import launch
    furina = launch()
    QTimer.singleShot(1500, furina._app.quit)
    furina._app.exec()
    print("SMOKE OK")
    return 0


def main() -> int:
    if "--harness" in sys.argv:
        from furina.app import run_harness
        run_harness()
        return 0
    if "--selfcheck" in sys.argv:
        return selfcheck()
    if "--smoke" in sys.argv:
        return smoke()
    from furina.app import run
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
