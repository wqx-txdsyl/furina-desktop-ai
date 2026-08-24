"""Phase 08B-Closeout: 同 glm-4v-flash 三对照，≥120 matched 生成 + 文本register 分离 + 硬盲测。

Current Furina / Natural Neutral（自然真人伙伴，非助手）/ Former-Mask（grandiosity/certainty，
performative-distance，非关键词堆砌）。唯一变量 = Dialogue Persona；其余全同。
Grounded 于 identity + state + scenario（same model/states/validator/config）。

关键：Current Furina 与 Former-Mask 共用 FURINA_IDENTITY（表达式策略确定性结果相同），
故两者的 persona 差异体现在 **文本 register** 层（由 system prompt 驱动），用非身份词 markers 度量。
"""
from __future__ import annotations

import sys
sys.path.insert(0, r"F:\program\Python\furina-work - 副本 (2)")
import re, random
from collections import Counter
from furina.config.app_config import load_config
from furina.llm import get_adapter, LLMMessage, content
from furina.dialogue import ExpressionEngine, DialogueValidator
from furina.persona.character_identity import FURINA_IDENTITY, NEUTRAL_CHARACTER_IDENTITY
from furina.persona.furina_character_contract import (
    NEUTRAL_DIALOGUE_PERSONA, FORMER_MASK_PERSONA)
from furina.persona.furina_persona import FURINA_PERSONA

cfg = load_config()
llm = get_adapter(cfg.llm.provider)(cfg.llm)
valid = DialogueValidator()


def _schema():
    return {"type": "object", "properties": {"speech": {"type": "string"}}}


PERSONAS = {
    "furina": FURINA_PERSONA,
    "neutral": NEUTRAL_DIALOGUE_PERSONA,
    "mask": FORMER_MASK_PERSONA,
}
IDENT = {"furina": FURINA_IDENTITY, "neutral": NEUTRAL_CHARACTER_IDENTITY, "mask": FURINA_IDENTITY}

# 40 matched scenarios（弱触发 + 强触发混合，不依赖容易表现 Persona 的收集）
# (context, user_text, note, emotion, cost, trust, task_mode)
def build_scenarios():
    S = []
    ordinary = [
        ("casual", "在干嘛呢？", "普通闲聊", "calm", 0.1, 0.5, False),
        ("casual", "今天好热啊。", "闲聊", "calm", 0.1, 0.5, False),
        ("casual", "我去吃饭了。", "去吃饭", "calm", 0.1, 0.5, False),
        ("casual", "我先忙一回。", "去忙", "calm", 0.3, 0.5, False),
        ("casual", "晚安。", "晚安", "sleepy", 0.1, 0.5, False),
        ("quiet", "", "安静共处", "calm", 0.1, 0.5, False),
        ("casual", "一起待会儿？", "一起待着", "happy", 0.1, 0.6, False),
        ("user_return", "我回来啦。", "用户回来", "happy", 0.1, 0.5, False),
    ]
    positive = [
        ("performing", "来，给我们表演一个", "表演机会", "excited", 0.1, 0.5, False),
        ("praise", "", "被夸奖", "proud", 0.1, 0.6, False),
        ("praise", "你做得真好", "被夸", "proud", 0.1, 0.7, False),
        ("success", "搞定啦！", "成功", "proud", 0.1, 0.5, False),
        ("play", "陪我玩会儿？", "玩邀请", "happy", 0.1, 0.6, False),
        ("casual", "你挺有意思的", "被欣赏", "happy", 0.1, 0.6, False),
        ("celebration", "生日快乐！", "庆祝", "happy", 0.1, 0.7, False),
    ]
    neg = [
        ("failure", "这个弄错了。", "出错", "embarrassed", 0.2, 0.4, False),
        ("questioned", "(用户质疑你的能力)", "被质疑", "embarrassed", 0.2, 0.4, False),
        ("ignored", "(一上午没理你)", "被冷落", "sad", 0.2, 0.5, False),
        ("rejection", "别理我。", "被拒", "sad", 0.3, 0.3, False),
        ("high_trust_vuln", "(深夜，你们很亲近)", "信任袒露", "lonely", 0.1, 0.9, False),
        ("lonely", "(你一个人待很久)", "孤独", "lonely", 0.2, 0.5, False),
    ]
    resp = [
        ("help", "能帮我下吗？", "求助", "calm", 0.2, 0.7, False),
        ("help", "(用户很焦虑)", "用户焦虑求助", "calm", 0.2, 0.8, False),
        ("task", "帮我列个清单", "任务", "calm", 0.1, 0.5, True),
        ("task", "这个文件你处理下", "任务", "calm", 0.2, 0.5, True),
    ]
    # praise × emotion 抽查
    praise_variants = [
        ("praise", "", "被夸(embarrassed)", "embarrassed", 0.1, 0.5, False),
        ("praise", "你真的很棒", "被夸(低熟悉)", "proud", 0.1, 0.2, False),
        ("praise", "你很厉害", "被夸(高信任)", "proud", 0.1, 0.9, False),
    ]
    # failure × relationship
    fail_variants = [
        ("failure", "搞砸了。", "失败(低熟悉)", "embarrassed", 0.2, 0.2, False),
        ("failure", "对不起弄错了", "失败(高信任)", "embarrassed", 0.2, 0.9, False),
        ("failure", "唉，失误", "失败(proud)", "proud", 0.2, 0.6, False),
    ]
    deep = [
        ("quiet", "", "深度专注(该沉默)", "calm", 0.8, 0.6, True),
        ("casual", "你累不累？", "被关心", "calm", 0.1, 0.9, False),
        ("quiet", "", "安静(用户忙碌)", "calm", 0.9, 0.5, True),
    ]
    extra = [
        ("casual", "今天吃到了一碗超赞的面", "分享美食", "happy", 0.1, 0.6, False),
        ("casual", "你最近在看什么？", "聊剧", "curious", 0.1, 0.6, False),
        ("success", "我把案子做完了！", "完成", "proud", 0.1, 0.7, False),
        ("praise", "你厨艺可以啊", "被夸", "proud", 0.1, 0.6, False),
        ("casual", "下雨了记得带伞", "被叮嘱", "calm", 0.1, 0.7, False),
        ("failure", "唉，又没抢到票", "抢票失败", "sad", 0.2, 0.6, False),
        ("casual", "周末来我家玩吗？", "邀请", "happy", 0.1, 0.6, False),
        ("casual", "帮我看看这个怎么弄", "小求助", "calm", 0.2, 0.6, False),
    ]
    for grp in (ordinary, positive, neg, resp, praise_variants, fail_variants, deep, extra):
        S.extend(grp)
    # 补齐到 44（各不相同），保证真实生成 ≥120（44×3 减少量 silence）
    fillers = [
        ("casual", "下班啦", "下班", "happy", 0.1, 0.6, False),
        ("casual", "你在听什么歌？", "聊音乐", "calm", 0.1, 0.5, False),
        ("casual", "楼下的猫好胖", "聊猫", "happy", 0.1, 0.5, False),
        ("casual", "刚淋了点雨", "淋雨", "calm", 0.1, 0.5, False),
        ("casual", "周末去哪？", "聊周末", "happy", 0.1, 0.5, False),
        ("casual", "今天好累啊", "喊累", "tired", 0.2, 0.6, False),
    ]
    for f in fillers:
        if len(S) >= 44:
            break
        S.append(f)
    while len(S) < 44:
        S.append(("casual", "随便聊聊", "闲聊", "calm", 0.1, 0.5, False))
    return S[:44]


# ---------------------------------------------------------------- 文本 register 度量（不含身份词）
# 预先声明的语域词典（只保留有区分度的词，剔除"我/你/一起/当然/谢谢"等通用词，避免噪声）。
#   grand/authority/certainty/performative-distance —— Former-Mask 主体：
#     敬语"您"、权威断言、公众仪式、文学化疏离、掌控感（**非**"水神/审判/伟大"身份词）
_GRAND = [
    "您", "众望", "不负", "一切尽在掌握", "自当", "必然", "毫无疑问", "不在话下",
    "游刃有余", "宁静", "祥和", "从容", "献上", "登场", "诸位", "敬请", "信手拈来",
    "理所当然", "掌控", "盛名", "威严", "气度", "相信我的", "理解您的", "寻常",
    "令人振奋", "想当年", "大驾", "稳操胜券", "运筹帷幄", "纵观", "如我所料", "尽在掌握",
]
# warm/expressive/theatrical/亲昵 —— Current Furina 主体：情绪粒子、剧场意象、俏皮、爱表现
# （含观众/舞台/掌声等**表演意象**，这是她主动选择的表达，不是身份词）
_WARM = [
    "哇", "呀", "哎呀", "哦", "精彩", "超棒", "咱们", "舞台", "观众", "掌声",
    "剧本", "演出", "观众们", "好戏", "天作之合", "小丑", "剧", "好玩", "喜欢",
    "表演", "亮相", "谢幕", "惊艳", "粉丝", "戏", "夸", "闪耀",
]
# plain/daily/conversational —— Natural Neutral 主体：生活化、平淡、随口（不含语气粒子，粒子归 warm）
_NATURAL = [
    "今天", "吃饭", "睡", "天气", "工作", "电影", "电视剧", "回来了", "还不错",
    "挺好", "嗯", "改天", "你呢", "最近", "忙", "走走", "凉快", "加油",
    "去吧", "慢慢", "吃", "看", "听", "洗澡", "外卖", "开会", "刷",
]
# identity/filler（God 等单独计）
_IDENT = ["本神", "神明", "审判", "水神", "枫丹", "芙卡洛斯", "伟大", "五百年"]


def strip_identity(s: str) -> str:
    """Hard-Blind：去掉强身份词（本神/神明/审判/水神/枫丹/芙卡洛斯/五百年/伟大）。"""
    for w in _IDENT:
        s = s.replace(w, "________")
    return s


def register(s: str) -> dict:
    s = s or ""
    # 长词优先匹配（避免"您"之类的子串噪声——用词长度>=2 先匹配）
    def hits(words): return sum(1 for w in words if w in s)
    return {"grand": hits(_GRAND), "warm": hits(_WARM), "natural": hits(_NATURAL)}


# 场景分组：trivial（普通闲聊，正确行为应"松弛一致"） vs engaged（情感/表演场，register 应分化）
_TRIVIAL_CTX = {"casual", "quiet", "user_busy", "eating", "sleepy", "user_return"}
def is_engaged(o): return o["ctx"] not in _TRIVIAL_CTX or o["mode"] == "PERFORMATIVE"


def generate(persona_key, scenarios, seed=1):
    rng = random.Random(seed)
    prompt = PERSONAS[persona_key]
    ident = IDENT[persona_key]
    ee = ExpressionEngine(ident)
    out = []
    for (ctx, user_text, note, emo, cost, trust, task) in scenarios:
        world = {"interruption_cost": cost, "availability": 1.0 - cost,
                 "user_working": cost > 0.6}
        ap = ee.appraise(emotion=emo, intent="talk", user_text=user_text,
                         relationship={"trust": trust, "comfort": 0.5, "annoyance": 0.1,
                                       "familiarity": min(1.0, trust + 0.2)},
                         world=world, user_present=cost < 0.6,
                         task_mode=task, solitude=emo in ("lonely", "sad"))
        if not ap.should_speak:
            out.append({"ctx": ctx, "note": note, "mode": ap.mode, "act": ap.dialogue_act,
                        "strategy": ap.strategy.to_dict(), "speech": None,
                        "god": 0, "generic": 0, "scar": 0, "valid": True, "silence": True})
            continue
        body = (f"mode={ap.mode} act={ap.dialogue_act} strategy={ap.strategy.to_dict()}\n"
                f"情境：{note}\n" + (f"用户：{user_text}\n" if user_text else "") +
                "作为这个角色说一句自然、具体、有真实感的话，严格只输出 {\"speech\":\"一句话\"}")
        msgs = [LLMMessage("system", content(prompt)), LLMMessage("user", content(body))]
        try:
            s = llm.structured(msgs, schema=_schema(), temperature=0.9).get("speech", "")
        except Exception:
            s = ""
        v = valid.validate(s, should_speak=True, context=ap.mode.lower())
        out.append({
            "ctx": ctx, "note": note, "mode": ap.mode, "act": ap.dialogue_act,
            "strategy": ap.strategy.to_dict(), "speech": s or None,
            "strategy_dramatic": 1 if ap.strategy.dramatic_intensity > 0.6 else 0,
            "god": v.god_reference_count,
            "generic": 1 if "generic_assistant_voice" in v.issues else 0,
            "scar": 1 if re.search(r"(孤独|漫长|寂寞|被看穿|五百年)", s) else 0,
            "valid": v.valid, "silence": False, "god_overuse": v.god_overuse_ordinary,
            "register": register(s),
        })
    return out


def metrics(outs):
    spoken = [o for o in outs if not o["silence"]]
    n = len(spoken)
    if n == 0:
        return {}
    def r(k): return sum(1 for o in spoken if o.get(k, 0)) / n * 100
    # 只对"发言"行统计（silence 行 valid=True 必须排除，否则 valid>100%）
    def rv(k, subset): return sum(1 for o in subset if o.get(k, 0)) / max(1, len(subset)) * 100
    def mean_rg(f, subset=None):
        ss = [o for o in spoken if (subset is None or o in subset)]
        return round(sum(o["register"][f] for o in ss) / max(1, len(ss)), 2)
    engaged = [o for o in spoken if is_engaged(o)]
    trivial = [o for o in spoken if not is_engaged(o)]
    return {
        "god": r("god"), "generic": r("generic"), "scar": r("scar"),
        "silence": sum(1 for o in outs if o["silence"]) / len(outs) * 100,
        "god_overuse_ordinary": r("god_overuse"),
        "valid": rv("valid", spoken),
        "dramatic": rv("strategy_dramatic", spoken),
        "sincere": sum(1 for o in spoken if o["mode"].lower() in ("sincere", "casual")) / n * 100,
        "reg_grand": mean_rg("grand"), "reg_warm": mean_rg("warm"), "reg_natural": mean_rg("natural"),
        "n_engaged": len(engaged), "n_trivial": len(trivial),
        "engaged_grand": mean_rg("grand", engaged), "engaged_warm": mean_rg("warm", engaged),
        "trivial_grand": mean_rg("grand", trivial), "trivial_warm": mean_rg("warm", trivial),
    }


def register_signature(outs, key):
    """含身份词 vs 去身份词 的 register 平均（证明 Hard-Blind 仍可分）。"""
    scored = [o for o in outs if o["speech"]]
    raw = [register(o["speech"]) for o in scored]
    stripped = [register(strip_identity(o["speech"])) for o in scored]
    def mean(rs, f):
        return round(sum(x[f] for x in rs) / max(1, len(rs)), 3)
    return {
        "n_words_scored": len(scored),
        "raw": {f: mean(raw, f) for f in ("grand", "warm", "natural")},
        "stripped": {f: mean(stripped, f) for f in ("grand", "warm", "natural")},
    }


def blind_judge_calls(outs, keys, sample=999):
    """用同一 LLM 做 register 分类器（去身份词），返回 (persona, ctx, note, label) 列表。
    默认跑满全部发言行（Closeout 需完整交叉，而非前 12 个 trivial 场景）。"""
    rubric = ("判断下面这句被 AI 数字生命对用户说的话，语气更像哪一类？"
              "A=普通伙伴(平淡自然、生活化、像普通人闲聊)；"
              "B=暖谦逊/亲昵(温柔、克制、有人味、会示弱或带深情)；"
              "C=神性/权威/表演性强(笃定、端着、仪式感、公共权威感)。只输出 A 或 B 或 C。")
    result = []
    for key in keys:
        sc = [o for o in outs[key] if o["speech"]][:sample]
        for o in sc:
            txt = strip_identity(o["speech"])
            msgs = [LLMMessage("system", content(rubric)),
                    LLMMessage("user", content(f"台词：{txt}\n分类："))]
            try:
                label = llm.structured(msgs, schema={"type": "object",
                    "properties": {"label": {"type": "string", "enum": ["A", "B", "C"]}}},
                    temperature=0.0).get("label", "?")
            except Exception:
                label = "?"
            result.append((key, o["ctx"], o["note"], label))
    return result


if __name__ == "__main__":
    import json
    scenarios = build_scenarios()
    print(f"matched scenarios = {len(scenarios)}")
    outputs = {}
    for key in ["furina", "neutral", "mask"]:
        outs = generate(key, scenarios, seed=1)
        outputs[key] = outs
        print(f"\n--- {key} ({len(outs)} 生成) ---")
        print(f"  {metrics(outs)}")
    with open(r"F:\program\Python\furina-work - 副本 (2)\_dp_rows.json", "w", encoding="utf-8") as f:
        json.dump(outputs, f, ensure_ascii=False, indent=1)
    # register signature（raw vs stripped）
    print("\n=== Register signature (HARD-BLIND: raw vs 去身份词) ===")
    for key in ["furina", "neutral", "mask"]:
        print(f"  {key}: {register_signature(outputs[key], key)}")
    # blind judge confusion（全部发言行）
    print("\n=== Blind register judge (去身份词, 全部发言行) ===")
    jr = blind_judge_calls(outputs, ["furina", "neutral", "mask"])
    from collections import defaultdict
    dist = defaultdict(Counter)
    engaged_dist = defaultdict(Counter)
    by_key = defaultdict(list)
    for (k, ctx, note, lab) in jr:
        dist[k][lab] += 1
        by_key[k].append(lab)
    for k in ["furina", "neutral", "mask"]:
        print(f"  {k}: {dict(dist[k])}")
    print("  --- matched-pairs（每行 f/n/m 同场景，去身份词后 judge 标签）---")
    order = ["A", "B", "C"]
    for i in range(len(by_key["furina"])):
        labs = [by_key[k][i] for k in ["furina", "neutral", "mask"]]
        print(f"    {i:02d}  f={labs[0]}  n={labs[1]}  m={labs[2]}")
    print("\n=== 人工抽检：Natural Neutral 真实输出 ===")
    for o in outputs["neutral"]:
        if o["speech"]:
            print(f"  [{o['ctx']}/{o['mode']}] {o['speech']}")
    print("\n=== 人工抽检：Furina 真实输出 ===")
    for o in outputs["furina"]:
        if o["speech"]:
            print(f"  [{o['ctx']}/{o['mode']}] {o['speech']}")
    print("\n=== 人工抽检：Former-Mask 真实输出 ===")
    for o in outputs["mask"]:
        if o["speech"]:
            print(f"  [{o['ctx']}/{o['mode']}] {o['speech']}")
    print("\n=== 泄漏定位：generic 行 ===")
    for k in ["furina", "neutral", "mask"]:
        for o in outputs[k]:
            if o.get("generic"):
                print(f"  {k} [{o['ctx']}/{o['mode']}] {o['speech']}")
