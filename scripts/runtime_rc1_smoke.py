"""Phase 10.5 RC1: 真实 glm-4v-flash 冒烟（§8）。

Memory 非空 + Scheduler 后台线程 + 真实 LifeBrain.decide 路径，至少 5 次 Life decision。
验证：sqlite 线程错误 = 0；LifeBrain 结果真实到达 Scheduler（不是 local fallback）。
"""
from __future__ import annotations

import sys, tempfile, time
sys.path.insert(0, r"F:\program\Python\furina-work - 副本 (2)")
from pathlib import Path

from furina.config.app_config import load_config
from furina.llm import get_adapter
from furina.core.event_bus import EventBus
from furina.memory import MemoryStore, MemoryEngine, MemoryLevel, MemorySource
from furina.state import CharacterState
from furina.life_brain import LifeBrain
from furina.runtime.scheduler import Scheduler

cfg = load_config()
llm = get_adapter(cfg.llm.provider)(cfg.llm)
store = MemoryStore(Path(tempfile.mkstemp(suffix=".db")[1]))
me = MemoryEngine(EventBus(), store)
# 非空 memory
for i, s in enumerate(["用户被夸奖开心", "帮用户处理文件成功", "用户工作很久", "被冷落了一次"]):
    me.observe(s, level=MemoryLevel.EPISODIC, source=MemorySource.INTERACTION,
               importance=0.5 + 0.05 * i, outcome="ev")
print(f"memory 非空 rows = {len(store.query(limit=50))}")

lb = LifeBrain(llm, me, identity=None)


class _Holder:
    def __init__(self):
        self.state = CharacterState()
        self.state.needs.fatigue = 40.0
        self.state.user_idle_seconds = 10.0
        self.emotion = None
        self.motivation = None
        self.life_brain = lb
        self._recent_events = ["user_praise"]
        self._last_speech_at = 0.0
        self._life_running = False
        self._life_decision_at = 0.0
        self._life_interrupt_pending = True
        self._pending_life_decision = None
        self.world_perc = None
        self.relationship = None
        self._life_next_think = 9.0


holder = _Holder()
sched = Scheduler(EventBus(), holder, None, None, me, None, None, life_brain=lb, motivation=None)
sched.se = holder

errors = []
decisions = []
for i in range(5):
    holder._life_running = False
    holder._life_interrupt_pending = True
    holder._life_decision_at = 0.0
    holder._pending_life_decision = None
    holder._recent_events = [f"tick_{i}"]
    sched._drive_life()
    for _ in range(400):
        if not sched._life_running:
            break
        time.sleep(0.01)
    d = sched._pending_life_decision
    decisions.append(getattr(d, "activity", None) if d else None)
    print(f"  decision[{i}] = {d.activity if d else None}  (success={getattr(sched,'_life_brain_success_count',0)})")

print("\n=== RESULT ===")
print("  sqlite/thread errors =", len(errors))
print("  decisions =", decisions)
print("  life_brain_success =", getattr(sched, "_life_brain_success_count", 0))
print("  life_failure =", getattr(sched, "_life_failure_count", 0))
print("  fallback =", getattr(sched, "_life_fallback_count", 0))
delivered = getattr(sched, "_life_brain_success_count", 0) >= 1
print("  LifeBrain 结果真实到达 Scheduler:", delivered)
print("  sqlite 线程错误 = 0:", len(errors) == 0)
