"""骨架逻辑单元测试（无 GUI、无网络）。

覆盖：事件总线 / 状态意图 / 行为 Utility / Director 仲裁 / 互动手势 /
素材 Resolver / 记忆形成与检索 / Agent 文件系统计划执行。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from furina.core import EventBus, EventType
from furina.state import StateEngine, IntentCategory
from furina.behavior import BehaviorEngine, BehaviorDefinition
from furina.interaction import GestureRecognizer, InteractionEngine, InteractionZone
from furina.assets.asset_manifest import AssetEntry, AssetManifest, AssetResolver, AssetQuery
from furina.memory import MemoryEngine, MemoryStore, MemoryLevel, MemorySource, RelationshipState
from furina.director import ActionRequest, Director
from furina.agent import ToolRegistry, PermissionManager, AgentRuntime, Permission
from furina.agent.tools.filesystem import ListDirTool, MakeDirsTool, OrganizeTool


# ---------------------------------------------------------------- 事件总线
def test_event_bus():
    bus = EventBus()
    got = []
    bus.on(EventType.STATE_CHANGED, lambda e: got.append(e.payload))
    bus.emit(EventType.STATE_CHANGED, payload="hi")
    assert got == ["hi"]
    # 通配
    any_calls = []
    bus2 = EventBus()
    bus2.on_any(lambda e: any_calls.append(e.type))
    bus2.emit(EventType.WAKE_UP)
    assert EventType.WAKE_UP in any_calls


# ---------------------------------------------------------------- 状态意图
def test_state_intent_fatigue_leads_to_wander():
    bus = EventBus()
    se = StateEngine(bus)
    se.state.user_working = False
    se.state.needs.boredom = 90
    se.state.needs.energy = 80
    cand = se.generate_intent(se.state)
    assert cand.intent.category == IntentCategory.SELF
    assert cand.intent.action == "wander"


def test_state_intent_working_observes():
    bus = EventBus()
    se = StateEngine(bus)
    se.state.user_working = True
    cand = se.generate_intent(se.state)
    assert cand.intent.action == "observe_user"


# ---------------------------------------------------------------- 行为 Utility
def test_behavior_choose_respects_interruption_cost():
    bus = EventBus()
    be = BehaviorEngine(bus)
    be.register(BehaviorDefinition("talk_to_user", utility_fn=lambda s: 70, priority=3))
    be.register(BehaviorDefinition("observe_user", utility_fn=lambda s: 20, priority=3))
    # 用户忙 → talk 被打扰成本降权
    state = {"user_working": True}
    picked = be.choose(state)
    assert picked == "observe_user"


def test_behavior_allowed_intents_enum():
    from furina.behavior import ALLOWED_INTENTS
    assert "talk" in ALLOWED_INTENTS[IntentCategory.INTERACT]


def test_behavior_chain():
    """行为链：行为完成后按 chain_to 衔接，而不是重新 utility 选。"""
    from furina.behavior import BehaviorEngine, BehaviorDefinition
    bus = EventBus()
    be = BehaviorEngine(bus)
    be.register(BehaviorDefinition("eat", utility_fn=lambda s: 90, priority=3, duration=5,
                                   chain_to="rest", chain_if=lambda s: s.get("hunger_done", True)))
    be.register(BehaviorDefinition("rest", utility_fn=lambda s: 1, priority=4, duration=20))
    be.register(BehaviorDefinition("idle", base_utility=0, priority=5))
    now = 1000.0
    first = be.step({"user_working": False}, now=now)       # 选 eat
    assert first == "eat"
    # duration(5s) 后 → 链到 rest（chain_if True），不是 utility 选 idle
    nxt = be.step({"user_working": False, "hunger_done": True}, now=now + 6.0)
    assert nxt == "rest"


def test_behavior_step_hysteresis():
    """行为生命周期：选中后未到 duration 不换，避免每 tick 翻车。"""
    from furina.behavior import BehaviorEngine, BehaviorDefinition
    bus = EventBus()
    be = BehaviorEngine(bus)
    be.register(BehaviorDefinition("observe_user", utility_fn=lambda s: 70, priority=3, duration=20))
    be.register(BehaviorDefinition("idle", base_utility=5, priority=5))
    now = 1000.0
    a1 = be.step({"user_working": True}, now=now)
    assert a1 == "observe_user"
    # 时长未到 → 保持（滞回）
    assert be.step({"user_working": True}, now=now + 2.0) == "observe_user"
    # 时长(20s)超过，但 observe 分数仍最高 → 继续 observe
    assert be.step({"user_working": True}, now=now + 30.0) == "observe_user"


# ---------------------------------------------------------------- Director 仲裁
def test_director_picks_highest_priority():
    bus = EventBus()
    d = Director(bus)
    executed = []
    d.set_executor(lambda req: executed.append(req.action))
    d.submit(ActionRequest("behavior", "wander", priority=4))
    d.submit(ActionRequest("interaction", "head_touch", priority=1))
    d.drain()   # 仲裁一次
    # 高优先(数字小)先执行
    assert executed[0] == "head_touch"


def test_director_only_resolver():
    bus = EventBus()
    d = Director(bus)
    d.set_executor(lambda req: None)
    # 模拟行为引擎发 ActionRequest 事件
    from furina.core.event_bus import Event
    bus.publish(Event(EventType.ACTION_REQUEST,
                      payload={"source": "behavior", "action": "walk", "priority": 4}))
    # submit 只入队；drain 执行
    d.drain()
    assert d.current() is not None
    assert d.current().action == "walk"


# ---------------------------------------------------------------- 互动手势
def test_gesture_petting_detection():
    g = GestureRecognizer(pet_amplitude=5.0)
    # 构造一次鼠标按下 + 上下往复 → 识别为 petting
    g.feed(0.0, 100, 100, True, InteractionZone.HEAD)
    ev = None
    for i, dy in enumerate([3, 6, 3, 6, 3, 6]):
        ev = g.feed(0.1 * (i + 1), 100, 100 + dy, True, InteractionZone.HEAD) or ev
    assert ev is not None and ev.type.value == "petting"


def test_interaction_saturation():
    bus = EventBus()
    ie = InteractionEngine(bus)
    ie.set_hitboxes_from_anchor({"head": [0.5, 0.2], "body": [0.5, 0.5]}, (0.5, 0.5, 0.4, 0.4))
    # 命中 head（归一化 0.5,0.2）
    for i in range(6):
        ie.on_pointer(0.1 * i, 50, 20, True, (0, 0, 100, 100))
        ie.on_pointer(0.1 * i, 50, 20, False, (0, 0, 100, 100))
    assert ie._saturation > 0.5


# ---------------------------------------------------------------- 素材 Resolver
def _mk_manifest():
    entries = [
        AssetEntry(asset_id="a1", posture="sitting", emotion="happy", gaze="user", action="idle"),
        AssetEntry(asset_id="a2", posture="sitting", emotion="neutral", gaze="front", action="idle"),
        AssetEntry(asset_id="a3", posture="standing", emotion="neutral", gaze="front", action="idle"),
    ]
    return AssetManifest(entries=entries)


def test_asset_resolver_fallback():
    m = _mk_manifest()
    r = AssetResolver(m)
    # 无精确匹配 → same posture(sitting) 取第一个 happy
    e = r.resolve(AssetQuery(posture="sitting", emotion="angry", gaze="user", action="idle"))
    assert e.posture == "sitting"
    # 完全 fallback → standing/neutral
    e2 = r.resolve(AssetQuery(posture="lying", emotion="sad", gaze="user", action="eat"))
    assert e2.posture == "standing"


def test_asset_resolver_exact():
    m = _mk_manifest()
    r = AssetResolver(m)
    e = r.resolve(AssetQuery(posture="sitting", emotion="happy", gaze="user", action="idle"))
    assert e.asset_id == "a1"


# ---------------------------------------------------------------- 记忆
def test_memory_formation_and_retrieval(tmp_path):
    bus = EventBus()
    store = MemoryStore(tmp_path / "m.db")
    me = MemoryEngine(bus, store)
    # 低重要性不过阈值 → 不形成
    low = me.observe("鼠标移动很多次", importance=0.1)
    assert low is None
    # 高重要性 → 形成
    high = me.observe("用户第一次让我整理下载文件", importance=0.9, outcome="成功")
    assert high is not None
    got = me.retrieve(query="下载文件", limit=5)
    assert any("下载" in m.content or "整理" in m.content for m in got)


def test_relationship_multi_dim():
    rel = RelationshipState()
    rel.apply({"trust": 10, "annoyance": 5})
    assert rel.trust == 10 and rel.annoyance == 5
    d = rel.as_dict()
    # 基础维度 + Life Simulation P2 动态互动统计（§12）
    assert {"familiarity", "trust", "comfort", "attachment", "respect",
            "dependency", "annoyance"}.issubset(set(d))
    # 动态字段随互动演化（非静态）
    assert "interaction_count_24h" in d and "user_rejection_rate" in d


# ---------------------------------------------------------------- Agent 文件系统
def test_agent_fs_plan(tmp_path):
    bus = EventBus()
    tools = ToolRegistry()
    tools.register(ListDirTool())
    tools.register(MakeDirsTool())
    tools.register(OrganizeTool())
    perm = PermissionManager()
    perm.on_confirm = lambda desc, lvl: True   # 授权 L2 让流程走完
    agent = AgentRuntime(bus, tools, perm)
    # 建一个含 pdf / png 的临时目录
    d = tmp_path / "Downloads"
    d.mkdir()
    (d / "a.pdf").write_text("x")
    (d / "b.png").write_text("y")
    (d / "c.txt").write_text("z")
    res = agent.execute("整理下载文件夹", {"path": str(d)})
    # planner 需要 path；流程完成（含真实 organize 步骤）后文件应落地到对应子目录
    assert res["status"] == "completed", res
    assert (d / "PDF" / "a.pdf").exists(), "pdf 应移入 PDF/"
    assert (d / "Images" / "b.png").exists(), "png 应移入 Images/"
    assert (d / "Docs" / "c.txt").exists(), "txt 应移入 Docs/"


def test_permission_gating():
    perm = PermissionManager()
    assert perm.check("读窗口", Permission.L0_READ).granted
    assert perm.check("创建文件", Permission.L1_LOW_WRITE).granted
    # L2/L3 默认无确认 handler → 拒绝
    assert not perm.check("删除文件", Permission.L2_HIGH_RISK).granted
    # 提供角色化确认 → 放行
    perm.on_confirm = lambda desc, lvl: True
    assert perm.check("删除文件", Permission.L2_HIGH_RISK).granted
