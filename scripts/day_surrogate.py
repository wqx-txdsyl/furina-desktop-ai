import sys, random
sys.path.insert(0, r"F:\program\Python\furina-work - 副本 (2)")
from collections import Counter
from furina.state import CharacterState
from furina.state.state_engine import StateEngine
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality
from furina.behavior.motivation import CATEGORY
from furina.persona.character_identity import FURINA_IDENTITY
from furina.world_perception import WorldPerception
from furina.core import EventBus
from furina.memory import MemoryStore
from furina.config.app_config import load_config

P = Personality(0.6,0.7,0.55,0.6,0.7,0.6,0.65,0.55)
random.seed(3)
cfg = load_config()

DAY = [
    ("morning_idle","chrome","news",False,8,30),
    ("focused_work","Code.exe","work.py",True,1,120),
    ("break","chrome","break",False,4,15),
    ("browsing","chrome","browse",False,5,30),
    ("writing","winword","doc.docx",True,2,60),
    ("away","chrome","tab",False,900,30),
    ("returned","Code.exe","app.py",True,0,1),
    ("focused_work2","Code.exe","app.py",True,2,60),
    ("casual","chrome","browse",False,5,60),
]

se = StateEngine(EventBus()); st = se.state; st.clock_hour = 9
ee = EmotionEngine(st.emotion); m = BehaviorMotivation(personality=P, identity=FURINA_IDENTITY)
wp = WorldPerception(); st.world = wp
mc = MemoryStore(cfg.db_path)

acts=[]; cats=[]; phase_acts={}
# 生产环境 tick：6s medium。1 分钟 = 10 个 6s tick。
TICK = 6.0
def advance(minutes, app, title, typing, idle):
    for _ in range(int(minutes * 60 / TICK)):
        st.clock_second = getattr(st, 'clock_second', 0) + TICK
        st.clock_minute = (st.clock_minute + (TICK // 60)) % 60 if TICK >= 60 else (st.clock_minute + 0) % 60
        # 精确时钟推进
        st.clock_minute = (st.clock_minute + int(TICK // 60)) % 60
        st.clock_hour = (st.clock_hour + 1 if st.clock_minute == 0 else st.clock_hour) % 24
        se.update_needs(TICK, user_working=(app in ("Code.exe","winword")), user_idle=idle)
        wp.update(app=app, title=title, idle_seconds=idle, hour=st.clock_hour, minute=st.clock_minute, typing=typing, dt=TICK)
        m._last_done.clear(); m._activity_history=[]; m._category_history=[]
        cands=[c.as_dict() for c in m.candidates(st,ee,ctx={"world":wp.factors(),"recent_events":wp.event_tags()})]
        # feasibility 过滤（away 时用户定向不可行）
        feasible=[c for c in cands if c.get("feasible",True)]
        pick=random.choices((feasible or cands)[:4], weights=[max(0.04,c["motivation"]) for c in (feasible or cands)[:4]], k=1)[0]
        m.mark_done(pick["activity"],0)
        acts.append(pick["activity"]); cats.append(CATEGORY.get(pick["activity"]))

for (phase,app,title,typing,idle,minutes) in DAY:
    before = len(acts)
    advance(minutes, app, title, typing, idle)
    phase_acts[phase] = acts[before:]

cc=Counter(cats); ac=Counter(acts); n=len(acts)
print(f"=== 8h surrogate（生产等价 tick=6s）===")
print(f"  总体: SELF={cc.get('SELF',0)/n*100:.0f}% SOCIAL={cc.get('SOCIAL',0)/n*100:.0f}% OBS={cc.get('OBSERVATION',0)/n*100:.0f}% ASSIST={cc.get('ASSISTANCE',0)/n*100:.0f}%")
print(f"  top8: {dict(ac.most_common(8))}")
print(f"  观察塌缩: OBS={cc.get('OBSERVATION',0)/n*100:.0f}% (应<50)")

print("\n=== 按世界阶段拆分（行为是否随 World 变化）===")
for phase, seg in phase_acts.items():
    if not seg: continue
    c2=Counter(seg); cats2=Counter(CATEGORY.get(a) for a in seg)
    print(f"  {phase:14}: SELF={cats2.get('SELF',0)/len(seg)*100:.0f}% SOC={cats2.get('SOCIAL',0)/len(seg)*100:.0f}% top={c2.most_common(2)}")

# 熵 + streak
import math
ent=-sum(v/n*math.log2(v/n) for v in ac.values() if v)
def longest(seq):
    mx=cur=1
    for i in range(1,len(seq)):
        cur=cur+1 if seq[i]==seq[i-1] else 1
        mx=max(mx,cur)
    return mx
print(f"\n  entropy={ent:.2f} top活动占比={ac.most_common(1)[0][1]/n*100:.0f}% 最长同活动={longest(acts)} 最长同类别={longest(cats)}")
