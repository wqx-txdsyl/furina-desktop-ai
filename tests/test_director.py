"""Director 仲裁测试（FINAL_TEST_V1 (docs/archive/legacy) A-8 / legacy-plan/8）。"""
from __future__ import annotations

from furina.core import EventBus
from furina.director import Director, ActionRequest


def _drain_one(d: Director, executed: list):
    d.drain()


def test_case1_touch_wins_over_walk():
    """Walking + User Touch → Touch 优先（更高优先级）。"""
    bus = EventBus()
    d = Director(bus)
    execu = []
    d.set_executor(lambda req: execu.append(req.action))
    # 互动(高优先, 小数字) vs 自主行为(低优先)
    d.submit(ActionRequest("behavior", "walk", priority=4))
    d.submit(ActionRequest("interaction", "head_touch", priority=1))
    d.drain()
    assert execu and execu[0] == "head_touch"


def test_case2_agent_wins_over_idle():
    """Idle + Agent Task → Agent 优先。"""
    bus = EventBus()
    d = Director(bus)
    execu = []
    d.set_executor(lambda req: execu.append(req.action))
    d.submit(ActionRequest("behavior", "idle", priority=6))
    d.submit(ActionRequest("agent", "work", priority=2))
    d.drain()
    assert execu and execu[0] == "work"


def test_case3_user_request_interrupts_play():
    """Playing + User Request → 用户请求中断（更高优先）。"""
    bus = EventBus()
    d = Director(bus)
    execu = []
    d.set_executor(lambda req: execu.append(req.action))
    d.submit(ActionRequest("behavior", "play", priority=3))
    d.drain()
    assert execu and execu[-1] == "play"
    d.submit(ActionRequest("user", "user_request", priority=1, interruptible=True))
    d.drain()
    assert execu[-1] == "user_request"


def test_case4_agent_not_interrupted_by_autonomous():
    """Agent Task + 自主行为 → Agent 不被无意义行为打断（interruptible=False）。"""
    bus = EventBus()
    d = Director(bus)
    execu = []
    d.set_executor(lambda req: execu.append(req.action))
    d.submit(ActionRequest("agent", "work", priority=2, interruptible=False))
    d.drain()
    assert execu == ["work"]
    # 更低优先级且不可中断当前 → 放回，当前仍是 agent
    d.submit(ActionRequest("behavior", "wander", priority=4, interruptible=True))
    d.drain()
    assert execu == ["work"]


def test_case5_sleep_woken_by_interaction():
    """Sleeping + User Interaction → 互动唤醒（高优先）。"""
    bus = EventBus()
    d = Director(bus)
    execu = []
    d.set_executor(lambda req: execu.append(req.action))
    d.submit(ActionRequest("behavior", "sleep", priority=3))
    d.drain()
    assert execu == ["sleep"]
    d.submit(ActionRequest("interaction", "pet", priority=1))
    d.drain()
    assert execu == ["sleep", "pet"]


def test_director_is_only_resolver():
    """各系统只能发 ActionRequest，由 Director 单一仲裁（legacy-plan/8 §3）。"""
    bus = EventBus()
    d = Director(bus)
    d.set_executor(lambda req: None)
    from furina.core.event_bus import Event, EventType
    bus.publish(Event(EventType.ACTION_REQUEST,
                      payload={"source": "behavior", "action": "walk", "priority": 4}))
    d.drain()
    assert d.current() is not None and d.current().action == "walk"


def test_director_clear_current_releases_block():
    """_current 释放后，下一轮能再仲裁——避免不可中断当前动作永久压制后续请求（死锁隐患）。"""
    bus = EventBus()
    d = Director(bus)
    execu = []
    d.set_executor(lambda req: execu.append(req.action))
    d.submit(ActionRequest("agent", "work", priority=2, interruptible=False))
    d.drain()
    assert execu == ["work"]
    # 一个更低优先级请求到达，但当前不可中断 → 放回
    d.submit(ActionRequest("behavior", "wander", priority=4, interruptible=True))
    d.drain()
    assert execu == ["work"]      # 仍是 work
    # 当前动作完成 → 释放接管权
    d.finish()
    d.drain()                      # 现在可重新仲裁
    assert d.current() is not None and d.current().action == "wander"


def test_director_finish_by_source():
    bus = EventBus()
    d = Director(bus)
    d.set_executor(lambda req: None)
    d.submit(ActionRequest("agent", "work", priority=2))
    d.drain()
    assert d.current().source == "agent"
    d.finish(source="behavior")   # 不是同 source → 不释放
    assert d.current() is not None
    d.finish(source="agent")      # 同 source → 释放
    assert d.current() is None
