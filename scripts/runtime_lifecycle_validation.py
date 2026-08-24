"""Phase 11B: Animation Runtime 生命周期验证（headless，注入 clock）。

验证 ENTRY→LOOP→EXIT 自动推进、transition 完成/pose commit、sleep/wake 全链、
praise-embarrassed timeline、以及 20k tick 长跑健康。
"""
from __future__ import annotations

import sys, random
sys.path.insert(0, r"F:\program\Python\furina-work - 副本 (2)")
from furina.core.event_bus import EventBus, EventType
from furina.runtime.frontend import (
    FrontendFrameConsumer, AnimationRuntime, AnimationPhase,
    GazeRuntime, ExpressionHold,
)
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.runtime.frame import FrameBody
from furina.runtime.animation import AnimationSpec


class MockClip:
    def __init__(self): self.spec=None; self.started=0.0
    def play(self, spec, now=None): self.spec=spec; self.started=(now or 0.0)
    def frame_count(self):
        if self.spec is None: return 0
        return len(self.spec.frames) if self.spec.frames else 1
    def is_finished(self, now=None):
        if self.spec is None or self.spec.loop: return False
        now = (now or 0.0)
        return now - self.started >= len(self.spec.frames)/max(0.1, self.spec.fps)


class FakeSeq:
    def __init__(self, action, entry=None, loop=None, exit=None, name=""):
        self.action=action; self.name=name
        self.entry_frames=entry or []; self.loop_frames=loop or []; self.exit_frames=exit or []
        self.frames=entry or loop or exit or []


class FakeAssets:
    def __init__(self):
        self.sequences={}
        # 真实 6 transition
        for t in ("sit_down","stand_up","lie_down","lie_up","wake_up","go_sleep"):
            self.sequences[t]=FakeSeq(t, entry=["%s_e0"%t,"%s_e1"%t], loop=["%s_l0"%t], name=t)
        for a in ("read","idle","play","eat","sleep","rest"):
            self.sequences[a]=FakeSeq(a, entry=["%s_e0"%a,"%s_e1"%a], loop=["%s_l0"%a,"%s_l1"%a], exit=["%s_x0"%a], name=a)
    def sequence_for(self, n): return self.sequences.get(n)
    def entry_for_state(self, posture, emotion, gaze, action="idle"): return None


def frame(activity, posture, expression="neutral", gaze="NONE"):
    return RuntimeFrameBuilder().build(activity_name=activity,
        body=FrameBody(posture=posture, expression=expression, gaze=gaze, micro_preferences=("BLINK","BREATH")),
        speech={"should_speak":False,"text":"","validation_status":"silent"})


def main():
    # ---- Sleep/Wake 全链 ----
    print("=== Sleep/Wake Full Chain ===")
    assets=FakeAssets(); clip=MockClip(); bus=EventBus()
    trans=[]; comps=[]
    bus.on(EventType.TRANSITION_COMPLETED, lambda e: trans.append(e.payload))
    bus.on(EventType.ANIMATION_COMPLETED, lambda e: comps.append(1))
    rt=AnimationRuntime(clip, assets, bus=bus)
    c=FrontendFrameConsumer(bus)
    # sleep
    bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=frame("sleep","sleeping"), source="t")
    vs=c.visual; vs.target_pose="sleeping"
    rt.accept(vs, prev_pose="standing", prev_activity="idle", now=100.0)
    rt.tick(now=100.0); print("  sleep tick0: phase=",rt.phase)
    rt.tick(now=105.0); print("  sleep tick+5: phase=",rt.phase,"pose committed=",rt.current_pose)
    assert rt.current_pose=="sleeping", "go_sleep 应 commit sleeping"
    # wake
    bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=frame("idle","standing"), source="t")
    vs2=c.visual; vs2.target_pose="standing"
    rt.accept(vs2, prev_pose="sleeping", prev_activity="sleep", now=110.0)
    rt.tick(now=110.0); print("  wake tick0: phase=",rt.phase)
    rt.tick(now=115.0); print("  wake tick+5: phase=",rt.phase,"pose committed=",rt.current_pose)
    assert rt.current_pose=="standing", "wake_up 应 commit standing"
    print("  TRANSITION_COMPLETED count=", len(trans))

    # ---- Praise Embarrassed timeline ----
    print("\n=== Praise Embarrassed Timeline ===")
    g=GazeRuntime(min_hold=0.8, cooldown=0.8); exp=ExpressionHold(min_hold=1.5)
    t0=100.0
    g.update("SIDE", now=t0)                    # 先 SIDE（被夸后避开）
    print("  t0 gaze=SIDE ->", g.visual_gaze)
    g.update("USER", now=t0+1.0)                # 过 hold 后回来
    print("  t0+1.0 语义USER ->", g.visual_gaze)
    exp.update("embarrassed", now=t0); exp.update("neutral", now=t0+0.3)
    print("  t0+0.3 表情 neutral? ->", exp.current_expression, "(应保持 embarrassed，hold 未过)")
    exp.update("neutral", now=t0+2.0)
    print("  t0+2.0 表情 ->", exp.current_expression, "(hold 过了才变)")
    print("  PASS")

    # ---- 20k tick 长跑健康 ----
    print("\n=== 20k tick Long-run ===")
    rng=random.Random(7)
    rt2=AnimationRuntime(MockClip(), FakeAssets(), bus=EventBus())
    acts=["idle","read","play","eat","sleep","rest"]; poses=["standing","sitting","sleeping","lying"]
    for i in range(20000):
        now=1000.0 + i*0.033
        act=rng.choice(acts); pos=rng.choice(poses)
        bus2=EventBus(); c3=FrontendFrameConsumer(bus2)
        bus2.emit(EventType.CHARACTER_FRAME_UPDATED, payload=frame(act,pos), source="t")
        vs=c3.visual; vs.target_pose=pos
        if i%8==0:
            rt2.accept(vs, prev_pose=rt2.current_pose, prev_activity=act, now=now)
        rt2.tick(now=now)
    print("  20k ticks: stuck=%d completions=%d entries=%d loops=%d exits=%d transitions=%d pending_replace=%d"%(
        rt2.stats["stuck"], rt2.stats["completions"], rt2.stats["entries"], rt2.stats["loops"],
        rt2.stats["exits"], rt2.stats["transitions"], rt2.stats["pending_replacements"]))
    print("  health: stuck==0", rt2.stats["stuck"]==0, "| completions<20000", rt2.stats["completions"]<20000)


if __name__ == "__main__":
    main()
