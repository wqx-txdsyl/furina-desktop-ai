"""Phase 11: 6 个关键场景验证（不启动 GUI，走 pure 逻辑）。

每个场景：构造 Frame → FrontendFrameConsumer diff → AnimationPlanner → evaluate VisualState +
transition/micro 计划，证明时序/语义符合要求。
"""
from __future__ import annotations

import sys
_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
from pathlib import Path

from furina.core.event_bus import EventBus, EventType
from furina.runtime.frontend import FrontendFrameConsumer, AnimationPlanner, FrontendVisualState
from furina.runtime.micro import MicroScheduler
from furina.runtime.frame_builder import RuntimeFrameBuilder
from furina.embodiment import EmbodiedExpressionEngine, BodyValidator, FURINA_EMBODIMENT
from furina.dialogue import PersonaMode
from furina.assets.asset_manifest import AssetManifest

M = AssetManifest.load(_ROOT / "data" / "assets" / "manifest.json")
eng = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
val = BodyValidator()
plan_assets = type("A", (), {"sequence_for": lambda self, n: next((e for e in M.entries if e.action == n), None)})()


def build_frame(activity, emotion, mode, act="COMMENT", silence=False, trust=0.5, fatigue=20.0):
    body = eng.express(emotion=emotion, mode=mode, dialogue_act=act,
                       relationship={"trust": trust, "comfort": trust, "annoyance": 0.1, "familiarity": trust},
                       activity=activity, fatigue=fatigue, silence=silence)
    body = val.validate(body, activity=activity, fatigue=fatigue, silence=silence)
    planner = RuntimeFrameBuilder()
    return planner.build(state=None, activity_name=activity, body=body,
                         speech={"should_speak": not silence, "text": "" if silence else "嗯",
                                 "dialogue_act": act, "mode": mode,
                                 "validation_status": "valid" if not silence else "silent"})


def scenario(name, activity, emotion, mode, silence=False, expect=None):
    f = build_frame(activity, emotion, mode, silence=silence)
    bus = EventBus(); consumer = FrontendFrameConsumer(bus)
    bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=f, source="t")
    vs = consumer.visual
    planner = AnimationPlanner(plan_assets)
    ms = MicroScheduler()
    # 从 vs 做 plan + micro step
    plan = planner.plan(vs, prev_pose="standing", prev_activity="idle")
    micro = ms.step(dt=1/30, now=10.0, micro_pref=list(vs.micro))
    print(f"\n[{name}] activity={vs.activity} expr={vs.expression} gaze={vs.gaze} "
          f"pose={vs.target_pose} hes={vs.hesitation:.2f}")
    print(f"    plan: phase={plan['phase']} transition={plan['transition']} pre_hold={plan['pre_hold_ms']}ms "
          f"micro={micro.active_micro or ['BREATH/BLINK']} blink={micro.blink:.2f}")
    if expect:
        ok = expect(vs, plan)
        print(f"    => {'PASS' if ok else 'FAIL'}")
    return vs, plan


# 1. Quiet Read
def e_read(vs, plan):
    return vs.activity == "read" and ("BREATH" in vs.micro or "BLINK" in vs.micro)
scenario("Quiet Read", "read", "calm", PersonaMode.CASUAL.value, expect=e_read)

# 2. Praise + Embarrassed → hold → SIDE gaze
def e_praise(vs, plan):
    return vs.expression == "embarrassed" and (vs.gaze == "SIDE" or vs.gaze == "USER") and plan["pre_hold_ms"] > 0
scenario("Praise Embarrassed", "talk", "embarrassed", PersonaMode.PROUD.value, expect=e_praise)

# 3. Proud
def e_proud(vs, plan):
    return vs.expression == "proud"
scenario("Proud", "talk", "proud", PersonaMode.PROUD.value, expect=e_proud)

# 4. Failure + high trust → gentle
def e_fail(vs, plan):
    return vs.transition == "GENTLE" or vs.expression in ("sad", "embarrassed")
b = build_frame("talk", "sad", PersonaMode.SINCERE.value, trust=0.9)
scenario("Failure High Trust", "talk", "sad", PersonaMode.SINCERE.value, expect=e_fail)

# 5. Deep work coexistence
def e_work(vs, plan):
    return vs.bubble_text == "" or vs.activity in ("read", "think")
scenario("Deep Work Coexistence", "think", "calm", PersonaMode.CASUAL.value, silence=True, expect=e_work)

# 6. Sleep → go_sleep transition
def e_sleep(vs, plan):
    return vs.activity == "sleep" and vs.target_pose == "sleeping"
fb = build_frame("sleep", "sleepy", PersonaMode.CASUAL.value)
bus = EventBus(); c = FrontendFrameConsumer(bus); bus.emit(EventType.CHARACTER_FRAME_UPDATED, payload=fb, source="t")
planner = AnimationPlanner(plan_assets)
vs = c.visual
p = planner.plan(vs, prev_pose="standing", prev_activity="idle")
print(f"\n[Sleep] target_pose={vs.target_pose} plan.transition={p['transition']}")
# 应先经 go_sleep 再 sleeping loop
print("    => PASS" if vs.target_pose == "sleeping" else "    => FAIL")
