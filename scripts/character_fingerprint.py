"""Phase 05 长期 Character Fingerprint（mock, Furina vs Neutral 同人格）+ Identity Influence Rate。"""
import sys, math, random
sys.path.insert(0, r"F:\program\Python\furina-work - 副本 (2)")
from collections import Counter
from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality
from furina.behavior.motivation import CATEGORY
from furina.persona.character_identity import FURINA_IDENTITY, NEUTRAL_CHARACTER_IDENTITY

P = Personality(0.6, 0.7, 0.55, 0.6, 0.7, 0.6, 0.65, 0.55)

# 角色相关场景轮换（识别/被忽略/被夸/被拒/失败/需要帮忙/安静）
CYCLE = ["user_return", "praise", "long_ignored", "reject", "fail", "user_needs_help", "quiet", "praise", "long_ignored"]

def set_scene(st, scene):
    st.user_present = scene != "quiet"
    st.user_working = scene in ("user_needs_help",)
    if scene == "long_ignored": st.user_idle_seconds = 1500
    else: st.user_idle_seconds = 60
    events = {"user_return": ["return", "welcome"], "praise": ["praise", "compliment"],
              "long_ignored": ["ignored", "silence"], "reject": ["reject", "拒绝"],
              "fail": ["failed", "失败"], "user_needs_help": ["help", "need"],
              "quiet": []}.get(scene, [])
    st._last_recent_events = events

def run(identity, steps=300, seed=13):
    rng = random.Random(seed)
    st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 65
    ee = EmotionEngine(st.emotion)
    m = BehaviorMotivation(personality=P, identity=identity)
    acts = []; cats = []; infl = []
    for i in range(steps):
        scene = CYCLE[i % len(CYCLE)]
        set_scene(st, scene)
        m._last_done.clear(); m._activity_history = []; m._category_history = []
        cands = [c.as_dict() for c in m.candidates(st, ee, ctx={"recent_events": st._last_recent_events})]
        pick = rng.choices(cands[:4], weights=[max(0.04, c["motivation"]) for c in cands[:4]], k=1)[0]
        m.mark_done(pick["activity"], 0)
        acts.append(pick["activity"]); cats.append(CATEGORY.get(pick["activity"]))
        # identity influence rate: 该候选 identity_fit>0.2 说明 Identity 参与
        infl.append(1 if pick.get("identity_fit", 0) > 0.2 else 0)
    return acts, cats, infl

def fp(name, acts, cats, infl):
    n = len(acts); c = Counter(acts); cc = Counter(cats)
    ent = -sum(v/n*math.log2(v/n) for v in c.values() if v)
    irr = sum(infl)/len(infl)
    print(f"\n[{name}] {n} steps")
    print(f"  SELF={cc.get('SELF',0)/n*100:.0f}% SOCIAL={cc.get('SOCIAL',0)/n*100:.0f}% OBSERVE={cc.get('OBSERVATION',0)/n*100:.0f}% ASSIST={cc.get('ASSISTANCE',0)/n*100:.0f}%")
    print(f"  talk={c.get('talk',0)/n*100:.0f}% approach={c.get('approach_user',0)/n*100:.0f}% invite={c.get('invite_user',0)/n*100:.0f}% celebrate={c.get('celebrate',0)/n*100:.0f}% help={c.get('offer_help',0)/n*100:.0f}%")
    print(f"  entropy={ent:.2f} 识别相关(talk+approach+celebrate)占比={ (c.get('talk',0)+c.get('approach_user',0)+c.get('celebrate',0))/n*100:.0f}%")
    print(f"  identity_influence_rate={irr*100:.0f}%")
    return {"c": c, "ent": ent, "irr": irr}

if __name__ == "__main__":
    print("="*78)
    print("Furina vs Neutral 长期 Character Fingerprint（同一 Behavioral Personality, mock 300st）")
    print("="*78)
    fa, fc, fi = run(FURINA_IDENTITY, steps=300)
    fp_f = fp("Furina", fa, fc, fi)
    na, nc, ni = run(NEUTRAL_CHARACTER_IDENTITY, steps=300)
    fp_n = fp("Neutral", na, nc, ni)
    # 两指纹距离
    keys = set(fp_f["c"]) | set(fp_n["c"])
    dist = round(sum(abs(fp_f["c"].get(k,0)/300 - fp_n["c"].get(k,0)/300) for k in keys), 3)
    print(f"\n  Furina vs Neutral fingerprint 距离: {dist}")
    print(f"  Furina identity_influence_rate: {fp_f['irr']*100:.0f}%  Neutral: {fp_n['irr']*100:.0f}%")
