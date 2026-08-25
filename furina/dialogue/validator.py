"""Dialogue Validator（Phase 08B §38）—— 生成后的确定性校验，不新增第二个 LLM Judge。

检查：empty_when_should_speak / too_long / generic_assistant_voice /
      stage_direction / example_copy / activity_contradiction / forbidden_lore_leak /
      archon_mask_overuse / god_reference。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# 通用助手腔（检测完整 pattern，非机械禁掉单字）
# 只拘"服务注册"，避免把真诚关心/情绪（如"希望你能告诉我发生了什么"）误判为助手腔。
# "有什么...帮你/为您"服务模板一律拘（含"有什么我可以帮忙"这类变体）。
_CSONIC_PATTERNS = [
    r"有什么(我)?(可以|能|需要)(帮|为)(你|您|忙)",
    r"需要我(帮忙|帮助)",
    r"随时(为您|为你)",
    r"如果您需要(任何|什么|帮助)",
    r"很高兴(为|能)为您(服务|效劳|解答|提供|帮忙)",
    r"作为(一个|一名|你的|专)",
    r"以下是",
    r"(当然|好的)可以帮你",
    r"请随时(告诉我|联系我)",
    r"很乐意(帮助|协助)",
    # Phase 13C §48 通用泄漏扩展：泛化鼓励 / "谢谢夸奖"式通用模板 / 客服开场
    r"谢谢你的(夸奖|夸奖|支持|反馈|信任)",
    r"没关系，我会(继续|一直)(努力|加油|帮你)",
    r"有什么(问题|事情)都可以(随时)?问我",
    r"(很高兴|非常荣幸)(认识你|和你聊天|遇见你)",
]
# B3（评审基线 0402e7f）：通用 AI / 数字助手身份泄漏 —— 把自己当作"AI/助手/模型"服务者
# （"作为AI…"、"我的功能是…"、"我可以帮助你…"、"我无法真正感受…"）。
# 只拘"身份自居"框架；不机械禁"AI"字样（她确实住在桌面里，但**不这样自称**）。
_GENERIC_AI_IDENTITY = [
    r"作为(一个|一名|你的|我们)?(AI|人工智能|助手|数字助手|智能助手|程序|模型|虚拟助手)",
    r"我是(一个|一款|你(的|们)的)?(AI|人工智能|助手|数字助手|智能助手|程序|模型|虚拟)",
    r"我的功能是",
    r"我可以帮助你(完成|处理|做)|我能帮你(完成|处理|做|实现)",
    r"我无法(真正|真实)(感受|体验|理解|体会)",
    r"很高兴(为你|为您)服务",
]
# B3：把自己放在"非人类 AI vs 你们人类"的观察者位置（不是简单禁"人类"二字）
_NONHUMAN_USER_FRAMING = [
    r"你们人类",
    r"你们(这些|那些)?人类",
]
# R1.1-5：通用 activity-claim ontology —— 确定性行为语义组 + 互斥当前行为声称检测。
# 不要求回复出现活动名（PERSONA-L6）；但如果回复**明确声称**了与真实 activity 互斥的
# **当前**行为 → ungrounded_activity。只拘"正在/在/边"式的现在时声称，不误伤愿望/回忆。
_ACTIVITY_GROUP = {
    "read": "READ", "study": "READ", "book": "READ",
    "eat": "EAT", "food": "EAT",
    "drink": "DRINK", "tea": "DRINK",
    "rest": "REST", "nap": "REST",
    "sleep": "SLEEP",
    "explore": "EXPLORE", "wander": "EXPLORE", "walk": "EXPLORE",
    "look_around": "EXPLORE", "stroll": "EXPLORE",
    "play": "PLAY", "play_with_object": "PLAY",
    "work": "WORK", "assist_user": "WORK", "offer_help": "WORK",
    "help": "WORK", "agent": "WORK",
    "think": "THINK", "daydream": "THINK",
    "idle": "IDLE",
}
_CLAIM_PATTERNS = {
    "READ": [re.compile(r"正?在看书|正?在读(书|文|小说|论文)|在看(书|小说|文档|论文)")],
    "EAT": [re.compile(r"正?在吃(饭|蛋糕|东西|零食|苹果)|在吃东西|边吃")],
    "DRINK": [re.compile(r"正?在喝(茶|水|咖啡|饮料)|在喝茶")],
    "REST": [re.compile(r"正(在|躺)着(休息|发呆)|在休息|躺(着|下)|打个盹|发会儿呆|休息一下")],
    "SLEEP": [re.compile(r"正?在睡(觉)?|睡着了|在睡觉|闭目养神")],
    "EXPLORE": [re.compile(r"正?在探索|探索新事物|四处(看看|逛逛|走动|溜达)|到处(逛逛|走走|溜达|看看)|闲逛|在散步|出门走走")],
    "PLAY": [re.compile(r"正?在玩|在玩(游戏|玩具)?|玩(一下|会儿)")],
    "WORK": [re.compile(r"正?在(帮|处理|整理|写|干活)|在帮|在整理|在写(代码|报告|文档|东西)|处理(文件|任务)")],
    "THINK": [re.compile(r"正?在想(事情|什么)?|在想|思考")],
    "IDLE": [re.compile(r"什么也没做|无所事事")],
}
# 与"当前在做 X"**互斥**的其它行为声称（保守：只列明显互斥的现在时组合）
_CONFLICTS = {
    "READ": {"EXPLORE", "EAT", "DRINK", "SLEEP", "PLAY", "WORK"},
    "EAT": {"READ", "EXPLORE", "REST", "SLEEP", "WORK", "THINK"},
    "DRINK": {"READ", "EXPLORE", "SLEEP", "PLAY", "WORK"},
    "REST": {"EXPLORE", "EAT", "DRINK", "WORK", "PLAY"},
    "SLEEP": {"READ", "EAT", "DRINK", "EXPLORE", "PLAY", "WORK", "THINK", "REST"},
    "EXPLORE": {"READ", "REST", "SLEEP", "EAT", "DRINK", "THINK", "WORK", "IDLE"},
    "PLAY": {"READ", "SLEEP", "REST", "EAT", "DRINK", "WORK"},
    "WORK": {"READ", "EXPLORE", "REST", "SLEEP", "PLAY", "THINK", "IDLE"},
    "THINK": {"EXPLORE", "SLEEP", "WORK", "EAT", "DRINK"},
    "IDLE": {"EXPLORE", "WORK"},
}
# 舞台动作描写（§35 禁止）
_STAGE_DIRECTION = [r"\*.*?\*", r"（.*?(叹气|笑|移|叉腰|眨眼|低头|沉默|看)）", r"\[.*?\]"]
# 历史 lore 泄漏（§19 普通场景禁）
_LORE_LEAK = ["五百年", "500年", "扮演神", "水神", "芙卡洛斯", "审判庭", "神座", "被看穿", "漫长等待"]
# 戏剧/神性自指（§11 有节制）
_GOD_REF = ["本神", "本小姐", "神明", "枫丹"]

# B3：issue → retry 可理解的中文反馈（validator 要告诉 retry 哪里错了，不是 invalid=True 无信息）
_ISSUE_FEEDBACK = {
    "empty_when_should_speak": "不能为空，需要说点什么",
    "too_long": "太长，压缩成一句",
    "generic_assistant_voice": "去掉客服/万金油话术，像真人一样说话",
    "generic_assistant_identity": "不要以 AI/助手/模型/程序自居，你就是芙宁娜本人",
    "nonhuman_user_framing": "不要说'你们人类'——你和对方是同一个小世界里的两个人，不是观察者",
    "repetitive_opening": "连续多轮以同一开场词开头（如'哎呀'），换一种自然开场",
    "ungrounded_activity": "你说的活动与真实状态不符，先如实回答现在正在做什么",
    "stage_direction": "不要写舞台动作描写（如*叹气*）",
    "overuse_god_catchphrase": "'本神'连用过多，日常少用旧舞台自称",
    "over_exclamation": "感叹号过多，语气自然一些",
    "example_copy": "不要照抄语气范例的句子",
    "activity_contradiction": "行为与活动不符",
    "interaction_contradiction": "互动事实不符（对方是正面触碰，不得说成被戳/被袭击）",
    "explicit_user_constraint_violation": "用户明确要求了回答格式/选项，必须严格照做（如'只能回答会或者不会'）",
    "recent_repetition": "与刚才说过的内容几乎一样，换一种说法",
    "generic_self_analysis": "不要用'乐观/爱交流/完美主义'这类模板化自我描述，说具体、属于你的东西",
    "possible_lore_leak": "普通闲聊不要自动提五百年/水神往事",
    "god_overuse": "'本神'用得太多，收着点",
    "god_overuse_ordinary": "普通情境不要端'本神'架子",
}


# R2.1 P0-3：issue severity —— HARD（不可展示：身份/事实/结构）vs SOFT（仅风格质量）。
# “一句话不够漂亮”不得变成系统错误/沉默；HARD 才会失败 DirectTurn。
_HARD_ISSUES = frozenset({
    "empty_when_should_speak", "too_long", "generic_assistant_identity",
    "nonhuman_user_framing", "ungrounded_activity", "activity_contradiction",
    "stage_direction", "example_copy", "interaction_contradiction",
    "explicit_user_constraint_violation",
})

# R2.1 P1-2：interaction 事实 grounding —— petting（正面触碰）回复不得声称被戳/被袭
_ATTACK_CLAIM = re.compile(r"偷袭|袭击|戳我|掐我|抓我|咬我|打我|捅我")
# R2.1 P1-6：generic interview self-analysis（模板化自我描述，非具体芙宁娜）
_GENERIC_SELF_ANALYSIS = [
    r"最大的优点就是(能够)?(保持)?(一颗)?乐观(的)?心态",
    r"善于(与人)?(交流|倾听|沟通)",
    r"最大的缺点(就)?是(有时候|总是|确实)?太(过于)?(追求)?完美",
    r"追求完美主义",
]

# R2.1 P1-1：production activities 覆盖（talk/idle/approach/agent_* 等）
_ACTIVITY_GROUP.update({
    "talk": "TALK", "chat": "TALK", "conversation": "TALK",
    "approach_user": "SOCIAL", "greet": "SOCIAL", "invite_user": "SOCIAL",
    "agent_planning": "WORK", "agent_work": "WORK", "agent_report": "WORK",
    "assist": "WORK", "helping": "WORK",
})
_CONFLICTS["TALK"] = {"WORK", "EXPLORE", "SLEEP", "EAT", "DRINK"}
_CONFLICTS["SOCIAL"] = {"WORK", "SLEEP", "EXPLORE", "EAT", "DRINK"}


@dataclass
class ValidationResult:
    valid: bool = True
    issues: List[str] = field(default_factory=list)
    god_reference_count: int = 0
    god_overuse_ordinary: bool = False   # 普通情境 god 自指过度（§6-7）
    # R2.1 P0-3：severity 分类（HARD 失败 DirectTurn；SOFT 只记录/retry 质量）
    hard_issues: List[str] = field(default_factory=list)
    soft_issues: List[str] = field(default_factory=list)

    def _classify(self) -> None:
        self.hard_issues = [i for i in self.issues if i in _HARD_ISSUES]
        self.soft_issues = [i for i in self.issues if i not in _HARD_ISSUES]

    def as_dict(self) -> dict:
        return {"valid": self.valid, "issues": self.issues,
                "hard_issues": self.hard_issues, "soft_issues": self.soft_issues,
                "god_reference_count": self.god_reference_count,
                "god_overuse_ordinary": self.god_overuse_ordinary}

    def describe(self) -> str:
        """B3/R2.1：可解释反馈（retry 生成器知道**哪里错了**，而非只有 invalid=True）。"""
        return "；".join(_ISSUE_FEEDBACK.get(i, i) for i in self.issues[:3])


class DialogueValidator:
    # 允许旧舞台腔的情境（§7）：performance/celebration/playful boasting/dramatic joke/high-pride
    GOD_ALLOWED_CONTEXTS = {"performing", "celebration", "playful", "boast", "dramatic", "high_pride"}
    # 普通情境（§7）：接近 0
    ORDINARY_CONTEXTS = {"casual", "quiet", "user_busy", "eating", "sleepy", "help", "sad",
                         "vulnerable", "questioned", "failure", "ignored"}

    def __init__(self) -> None:
        self._csn = [re.compile(p) for p in _CSONIC_PATTERNS]
        self._generic_ai = [re.compile(p) for p in _GENERIC_AI_IDENTITY]
        self._nonhuman = [re.compile(p) for p in _NONHUMAN_USER_FRAMING]
        self._stage = [re.compile(p) for p in _STAGE_DIRECTION]
        self._lore = [re.compile(p) for p in _LORE_LEAK]
        self._god = [re.compile(p) for p in _GOD_REF]
        self._generic_self = [re.compile(p) for p in _GENERIC_SELF_ANALYSIS]
        # R1.1-5：activity-claim ontology（每个语义组一组现在时声称 pattern）
        self._claims = {g: [re.compile(p) for p in pats] for g, pats in _CLAIM_PATTERNS.items()}

    @staticmethod
    def _opening_marker(s: str) -> str:
        """表面语言开场标记：句子开头的第一个短词（≤5 字，截断标点）。"""
        m = re.match(r"^[^\s，。！？,.!?～~、：:；;]{1,5}", (s or "").strip())
        return m.group(0) if m else ""

    def validate(self, speech: str, *, should_speak: bool = True,
                 length_cap: int = 120, example_phrases: Optional[List[str]] = None,
                 activity: str = "", context: str = "casual",
                 recent_surface: Optional[List[str]] = None,
                 interaction: str = "",
                 constraint: Optional[tuple] = None) -> ValidationResult:
        r = ValidationResult()
        s = (speech or "").strip()
        if should_speak and not s:
            r.valid = False; r.issues.append("empty_when_should_speak")
        if not s or not should_speak:
            r._classify()
            return r
        if len(s) > length_cap:
            r.valid = False; r.issues.append("too_long")
        for p in self._csn:
            if p.search(s):
                r.valid = False; r.issues.append("generic_assistant_voice"); break
        # B3：通用 AI / 数字助手身份泄漏（"作为AI""我的功能是"…）
        for p in self._generic_ai:
            if p.search(s):
                r.valid = False; r.issues.append("generic_assistant_identity"); break
        # B3：非人类观察者框架（"你们人类…"）
        for p in self._nonhuman:
            if p.search(s):
                r.valid = False; r.issues.append("nonhuman_user_framing"); break
        # B3/R1.1-5：activity grounding 通用矛盾检查（语义组 ontology，非单一特例）
        # 不要求出现活动名；只拘"明确声称了与真实 activity 互斥的当前行为"。
        grp = _ACTIVITY_GROUP.get(activity or "")
        if grp is not None and grp in _CONFLICTS:
            for claimed_group, pats in self._claims.items():
                if claimed_group == grp:
                    continue          # 声称与自己同组 → 一致，合法
                if claimed_group not in _CONFLICTS[grp]:
                    continue          # 非互斥 → 不误伤
                if any(p.search(s) for p in pats):
                    r.valid = False
                    r.issues.append("ungrounded_activity")
                    break
        # R2.1 P1-2：interaction 事实 grounding（petting=正面触碰；不得声称被戳/被袭）
        if interaction == "petting" and _ATTACK_CLAIM.search(s):
            r.valid = False; r.issues.append("interaction_contradiction")
        # R2.1 P1-5：用户显式格式/回答约束（优先级高于 persona style）
        if constraint:
            norm = re.sub(r"[\s，。！？,.!?～~、：:；;\"'“”‘’]", "", s)
            if norm not in constraint:
                r.valid = False; r.issues.append("explicit_user_constraint_violation")
        # B3：同一显著开场词连续塌缩（"哎呀"×3）—— 允许一次，禁止模板化
        if recent_surface:
            cur = self._opening_marker(s)
            prev = [self._opening_marker(x) for x in recent_surface[-3:]]
            if len(cur) >= 2 and prev.count(cur) >= 2:
                r.valid = False; r.issues.append("repetitive_opening")
            # R2.1 P1-6：近期逐字重复（P21 逐字重复 P19 属 context failure）
            if any(self._normalize(s) and self._normalize(s) == self._normalize(x)
                   for x in recent_surface[-4:]):
                r.valid = False; r.issues.append("recent_repetition")
        for p in self._stage:
            if p.search(s):
                r.valid = False; r.issues.append("stage_direction"); break
        # Phase 13C §48：角色塌陷（靠口头禅/感叹撑，不靠内容）—— 非模板机，只标明显塌陷
        if s.count("本神") > 2:
            r.valid = False; r.issues.append("overuse_god_catchphrase")
        if s.count("！") + s.count("!") >= 4 and len(s) < 40:
            r.valid = False; r.issues.append("over_exclamation")
        # 例子复读（§30）
        if example_phrases:
            for ex in example_phrases:
                if ex and ex.strip() and len(ex) >= 7 and ex.strip() in s:
                    r.valid = False; r.issues.append("example_copy"); break
        # 活动矛盾（§26）
        if activity == "offer_help" and not any(w in s for w in ("帮", "我来", "搭把", "交给")):
            r.issues.append("activity_contradiction")
        # R2.1 P1-6：generic interview self-analysis（模板化自我描述）
        if any(p.search(s) for p in self._generic_self):
            r.valid = False; r.issues.append("generic_self_analysis")
        # lore 泄漏（§19）
        if any(p.search(s) for p in self._lore):
            r.issues.append("possible_lore_leak")
        # god 自指：**contextual allowance**（§6-7）——普通情境接近 0，表演情境允许偶发
        gc = sum(1 for p in self._god for _ in p.findall(s))
        r.god_reference_count = gc
        if context in self.GOD_ALLOWED_CONTEXTS:
            # 表演情境：允许偶发旧舞台腔，但不过度（≤2）
            if gc > 2:
                r.valid = False; r.issues.append("god_overuse")
        else:
            # 普通情境：1 次即标记过度（除非恰好一次略带俏皮）
            if gc >= 1:
                r.god_overuse_ordinary = True
                if gc >= 2:
                    r.valid = False; r.issues.append("god_overuse_ordinary")
        r._classify()
        return r

    @staticmethod
    def _normalize(s: str) -> str:
        return re.sub(r"[\s，。！？,.!?～~、：:；;\"'“”‘’]", "", (s or ""))
