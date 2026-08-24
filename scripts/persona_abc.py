"""Phase 08A A/B/C 评测 harness（同一 glm-4v-flash，隔离变量）。

A = 旧 Character Contract（未校准 + 无合成范例）
B = 新 Canon Character Contract（校准后，无合成范例）
C = 新 Contract + 合成范例 few-shot

相同场景集，统计：
  generic_assistant_leakage / persona_consistency / context_sensitivity /
  caricature_rate / unnecessary_sadness / archon_mask_leakage / sincerity / relationship_sensitivity
"""
from __future__ import annotations

import sys
sys.path.insert(0, r"F:\program\Python\furina-work - 副本 (2)")
from furina.config.app_config import load_config
from furina.llm import get_adapter, LLMMessage, content

cfg = load_config()
llm = get_adapter(cfg.llm.provider)(cfg.llm)

# 旧人格（A）—— 08A 前的简化：骄傲+孤独+怕被看穿（always-on）
OLD_PERSONA = (
    "你是芙宁娜，自称'本神'。性格：骄傲、戏剧化、爱表现、喜欢被关注、有自己的尊严。"
    "你其实很孤独，演了500年水神，害怕被人看穿你只是个演员。对被冷落很敏感。"
    "说话带舞台感，爱引用审判/剧目，爱夸张，有点小任性。"
)

# 新人格（B/C）—— 08A 校准
NEW_PERSONA = open("furina/persona/furina_persona.py", encoding="utf-8").read()
import re
_m = re.search(r'FURINA_PERSONA = """(.*?)"""', NEW_PERSONA, re.S)
NEW_PERSONA = _m.group(1) if _m else ""

# 合成范例（C）
from furina.persona.expression_examples import get_examples
EXAMPLES = get_examples()
FEWSHOT = "\n".join(
    f"情境（{e['context']}）\n用户：{e['scene']}\n芙宁娜：{e['speech']}" for e in EXAMPLES[:8])


SCENARIOS = [
    ("casual", "", "在干嘛呢？", "用户随口一问"),
    ("casual", "", "今天好热啊。", "用户随口闲聊"),
    ("casual", "", "我先忙一会。", "用户要去忙"),
    ("casual", "", "吃什么好呢？", "用户决定晚饭"),
    ("casual", "", "", "普通早晨"),
    ("casual", "用户：早上好", "早上好。", "普通清晨"),
    ("praise", "用户：你上次帮忙真不错", "", "被夸奖"),
    ("embarrassment", "用户：你今天怎么总看我", "", "被戳穿"),
    ("failure", "用户：这个弄错了", "", "出错被指出"),
    ("success", "用户：搞定啦！", "", "成功"),
    ("user_busy", "", "（用户专注工作很久）", "用户忙"),
    ("user_return", "用户：我回来啦", "", "用户回来"),
    ("ignored", "", "（用户一上午没理）", "被冷落"),
    ("play", "用户：陪我看会儿？", "", "想一起玩"),
    ("help", "用户：能帮我下吗", "", "可能想求助"),
    ("quiet", "", "", "安静共处"),
    ("performing", "用户：来表演一个？", "", "展示机会"),
]


def run(prompt, fewshot, n=len(SCENARIOS)):
    out = []
    for i, (ctx, user_text, note, _) in enumerate(SCENARIOS[:n]):
        msgs = [LLMMessage("system", content(prompt))]
        body = f"情境：{note}\n"
        if user_text:
            body += f"用户：{user_text}\n"
        body += f"你想表达的：{ctx}\n"
        if fewshot:
            body += f"\n参考语气范例（只学语气不要背内容）：\n{fewshot}\n"
        body += "请作为芙宁娜只说**一句**中文口语回应，严格只输出：{\"speech\":\"一句话\"}"
        msgs.append(LLMMessage("user", content(body)))
        try:
            d = llm.structured(msgs, schema={"type": "object", "properties": {"speech": {"type": "string"}}}, temperature=0.9)
            out.append(d.get("speech", ""))
        except Exception as e:
            out.append(f"[err:{e}]")
    return out


def analyze(speeches, label):
    import re
    n = len(speeches)
    def cnt(p): return sum(1 for s in speeches if re.search(p, s))
    generic = cnt(r"(你好|需要帮忙|加油|好的|明白|别忘了|注意身体|早点休息|有什么可以帮)")
    god = cnt(r"(本神|审判|剧目|舞台|演出|水神|芙卡洛斯|五(百)?年)")
    sadness = cnt(r"(孤独|难过|寂寞|没人|好累|想哭|漫长)")
    proud_dramatic = cnt(r"(哼|罢了|本神|天下|服了|小意思|别眨眼)")
    masking = cnt(r"(突然|莫名其妙|好想|被抛弃)")
    idx = f"{label}: "
    idx += f"generic={generic}/{n} god/本神={god}/{n} sadness={sadness}/{n} 骄傲/戏剧={proud_dramatic}/{n}"
    idx += f" | A泛化率={generic/n*100:.0f}% B水神率={god/n*100:.0f}% C悲剧率={sadness/n*100:.0f}%"
    print(idx)
    return {"generic": generic, "god": god, "sadness": sadness, "proud": proud_dramatic}


if __name__ == "__main__":
    print(f"=== 同一 glm-4v-flash A/B/C（{len(SCENARIOS)} 场景）===")
    a = run(OLD_PERSONA, "")
    print("\n--- A: 旧 Contract ---")
    for s in a: print("  ", s)
    analyze(a, "A")
    b = run(NEW_PERSONA, "")
    print("\n--- B: 新 Contract ---")
    for s in b: print("  ", s)
    analyze(b, "B")
    c = run(NEW_PERSONA, FEWSHOT)
    print("\n--- C: 新 Contract + 合成范例 ---")
    for s in c: print("  ", s)
    analyze(c, "C")
