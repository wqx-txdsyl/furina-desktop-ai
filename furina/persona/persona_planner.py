"""PersonaPlanner（R2.2 FINAL）—— 生成台词前的确定性语义规划层。

链路：UserTurnFrame（理解用户这一句） → PersonaPlan（决定怎么回应）。
全部确定性，不新增第二个 LLM Judge；LLM 只负责把 PersonaPlan 变成自然语言。

解决的问题（R2.2 §19）：
  P06 主客体反转 / P07 不需要大道理却自我分析 / P16 答非所问 /
  P20 无视用户纠正 / P22 "那现在呢" reference 丢失 / P23-P24 擅自执行 Agent task。

设计：
  - UserTurnFrame：把用户输入解析为结构化语义（act/subject/topic/referent/…）。
  - PersonaPlan：mode / stance / social_goal / pride / vulnerability / dramatic_intensity /
    autobiography / god_register / response_length / must_answer / forbidden_moves。
  - opening_style：从多种开场方式选择（替代"哎呀"塌缩）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ================================================================ Opening Styles
OPENING_STYLES = (
    "DIRECT",              # 直接回答
    "REACTION",            # 自然反应（呵/嗯/哦？）
    "COUNTER_QUESTION",    # 反问钓人
    "MOCK_OFFENSE",        # 假装被冒犯
    "PAUSE",               # 省略号停顿
    "SELF_CORRECTION",     # 自我更正（本想说…算了）
    "PLAYFUL_ASSERTION",   # 俏皮断言
    "QUIET_ACKNOWLEDGEMENT",  # 安静回应
    "DRAMATIC_ENTRY",      # 戏剧登场（咳…）
)

# 各 opening 的风格提示（不写固定台词，只给"怎么开场"）
_OPENING_HINT = {
    "DIRECT": "直接回答，不绕弯子。",
    "REACTION": "用一句自然的语气反应开场（如'哦？''嗯…'，不是固定词）。",
    "COUNTER_QUESTION": "先反问一句，把主动权拿回来。",
    "MOCK_OFFENSE": "假装被冒犯一下（但立刻转回正题）。",
    "PAUSE": "先用'…'停顿一下，再开口。",
    "SELF_CORRECTION": "可以以'本想说……算了'式自我更正开场（不得变固定 gimmick）。",
    "PLAYFUL_ASSERTION": "俏皮地先下个断言。",
    "QUIET_ACKNOWLEDGEMENT": "轻轻应一声，不把话说满。",
    "DRAMATIC_ENTRY": "用'咳…'式清嗓子/摆姿态开场（表演情境才用）。",
}


# ================================================================ UserTurnFrame
# 用户语义帧：把用户输入解析为结构化语义（确定性，保守）
@dataclass
class UserTurnFrame:
    act: str = "COMMENT"                    # ANSWER / COMPLAIN / CONFIDE / CHALLENGE / PRAISE /
                                            # TEASE / ASK_SELF / REQUEST_ACTION / LISTEN_WANT /
                                            # ABSENCE / ATTENTION_PROBE / QUIET / CORRECTION / OTHER
    subject: str = ""                       # 用户谈论的对象（我/你/我们/他/她/它）
    topic: str = ""                         # 话题（工作/孤独/关注/日常/身份/关系…）
    referent: str = ""                      # 指代对象（"那现在呢"→前文话题）
    emotional_need: str = ""                # 情绪需求（陪伴/被理解/被认可/被安慰/解答…）
    seriousness: float = 0.5                # 0..1 认真程度
    correction: bool = False                # 用户是否在纠正/追问（"我是认真问的"）
    explicit_constraint: Optional[Tuple[str, str]] = None   # 只能回答X或Y
    factual_query: bool = False             # 是否事实/记忆查询
    action_request: bool = False            # 是否请求执行动作
    has_referent_deictic: bool = False      # 是否含"那/这个/刚才"等指代（需要上文）
    raw: str = ""

    def to_dict(self) -> dict:
        return {k: (v if not isinstance(v, tuple) else list(v))
                for k, v in self.__dict__.items()}


# ---------------------------------------------------------------- 语义解析（确定性）
# act 路由：拒绝/边界优先（与 classify_act 一致原则），再按语义分类
_CORRECTION_MARKERS = ("我是认真问的", "认真问", "不是开玩笑", "我说真的", "听我说",
                       "我不是在开玩笑", "不许说", "不准说", "别再说", "这次不许", "说真的")
_CONSTRAINT_RE = re.compile(r"只能回答([^或，,。！？\s]{1,6})(?:或者|或)([^。！？\s]{1,6})")
_DEICTIC_RE = re.compile(r"(那|这|那个|刚才|上次|之前|现在呢|然后呢)")
_ACTION_RE = re.compile(r"(帮我|帮我打开|帮我整理|帮我查|帮我找|打开|整理|计算|搜索|查一下)")
_ABSENCE_RE = re.compile(r"(不在|没来|没找你|没理你|离开|不在的时候|一天没)")
_ATTENTION_PROBE_RE = re.compile(r"(关注|被关注|没人看|不关注|大家.*你|你.*大家|观众|被忽略|忽略你)")
_LISTEN_RE = re.compile(r"(陪我|陪我说|听我说|不用说什么|说两句|不想说话|安静|大道理|别分析)")
_QUIET_RE = re.compile(r"(困|想睡|不想睡|累了|歇会|安静)")
_CONFIDE_RE = re.compile(r"(担心|害怕|难过|伤心|焦虑|压力|不自信|没人喜欢|没用|失败|怕)")
_CHALLENGE_RE = re.compile(r"(质疑|是不是.*(装|骗|演)|你是不是其实|你不确定|你明明|你其实|被我说中|说中|戳穿|嘴硬|不承认|我猜对|说对了)")
_PRAISE_RE = re.compile(r"(可爱|好看|厉害|棒|优秀|喜欢|爱你|真好|聪明|漂亮)")
_TEASE_RE = re.compile(r"(逗|开玩笑|不服|你这个人|麻烦|又爱|嘴硬|调皮)")
_SELF_INTRO_RE = re.compile(r"(介绍.*你|你是谁|你这个人|最大的优点|最大的缺点|你自己|缺点是什么|优点是什么|像优点的缺点)")
_HISTORY_RE = re.compile(r"(芙卡洛斯|水神|枫丹|五百年|以前|过去|扮演|舞台|表演)")


def parse_user_turn(user_text: str, *, history_topic: str = "") -> UserTurnFrame:
    """把用户一句话解析为语义帧（保守、确定性）。"""
    t = (user_text or "").strip()
    f = UserTurnFrame(raw=t)
    if not t:
        return f
    # 显式约束
    m = _CONSTRAINT_RE.search(t)
    if m:
        f.explicit_constraint = (m.group(1).strip(), m.group(2).strip())
    # 纠正/追问（"我是认真问的"）
    if any(k in t for k in _CORRECTION_MARKERS):
        f.correction = True
        f.seriousness = max(f.seriousness, 0.9)
    # 指代
    if _DEICTIC_RE.search(t):
        f.has_referent_deictic = True
        if "现在呢" in t or "那现在" in t:
            f.referent = history_topic or "前文话题"
        elif "那" in t or "这个" in t or "刚才" in t or "上次" in t or "之前" in t:
            f.referent = history_topic or "前文话题"
    # act 分类（优先级：约束/纠正 > 动作 > 安静 > 陪伴 > 脆弱 > 挑战 > 夸 > 逗 > 注意力 > 缺席 > 自我介绍 > 历史 > 反问 > 默认）
    if f.explicit_constraint:
        f.act = "ANSWER"
        f.factual_query = True
    elif _ACTION_RE.search(t):
        f.act = "REQUEST_ACTION"
        f.action_request = True
    elif _QUIET_RE.search(t):
        f.act = "QUIET"
        f.seriousness = max(f.seriousness, 0.3)
    elif _LISTEN_RE.search(t):
        f.act = "LISTEN_WANT"
        f.emotional_need = "陪伴"
        f.seriousness = max(f.seriousness, 0.6)
    elif _CONFIDE_RE.search(t):
        f.act = "CONFIDE"
        f.emotional_need = "被理解"
        f.seriousness = max(f.seriousness, 0.7)
    elif _CHALLENGE_RE.search(t):
        f.act = "CHALLENGE"
        f.seriousness = max(f.seriousness, 0.5)
    elif _SELF_INTRO_RE.search(t):
        f.act = "ASK_SELF"
    elif _PRAISE_RE.search(t):
        f.act = "PRAISE"
    elif _TEASE_RE.search(t):
        f.act = "TEASE"
    elif _ABSENCE_RE.search(t):
        f.act = "ABSENCE"
        f.seriousness = max(f.seriousness, 0.5)
    elif _ATTENTION_PROBE_RE.search(t):
        f.act = "ATTENTION_PROBE"
        f.seriousness = max(f.seriousness, 0.5)
    elif _SELF_INTRO_RE.search(t):
        f.act = "ASK_SELF"
    elif _HISTORY_RE.search(t):
        f.act = "ASK_SELF" if f.has_referent_deictic else "ANSWER"
    elif re.search(r"[?？]|吗|呢|干嘛|什么|几|哪|是不是|怎么样", t):
        f.act = "ANSWER"
        f.factual_query = True
    # subject：主谓归属（保守）
    if re.match(r"^(我|你|我们|他|她|它|大家|你们)", t):
        f.subject = re.match(r"^(我|你|我们|他|她|它|大家|你们)", t).group(1)
    return f


# ================================================================ PersonaPlan
@dataclass
class PersonaPlan:
    mode: str = "CASUAL"
    user_dialogue_act: str = "COMMENT"
    user_need: str = ""
    topic: str = ""
    referent: str = ""
    stance: str = "direct"                  # direct / guarded / vulnerable / playful / proud / listening
    social_goal: str = ""                   # answer_and_preserve_dignity / comfort / accompany / …
    pride_level: float = 0.5                # 0..1
    vulnerability_level: float = 0.0        # 0..1
    dramatic_intensity: float = 0.4         # 0..1（按 mode 带）
    intimacy_level: float = 0.5             # 0..1
    autobiography_activation: int = 0       # 0..3
    autobiography_anchor_ids: List[str] = field(default_factory=list)
    god_register: str = "off"               # off / optional / allowed
    teasing_level: float = 0.0              # 0..1
    response_length: str = "SHORT"          # MICRO / SHORT / NORMAL
    must_answer: bool = True
    must_include_semantics: List[str] = field(default_factory=list)   # 必须回应的语义点
    forbidden_moves: List[str] = field(default_factory=list)          # 禁止的举动
    opening_style: str = "DIRECT"
    opening_style_reason: str = ""
    anti_pattern_note: str = ""             # 本条 plan 的防呆提示
    raw: str = ""                           # 原始用户输入

    def to_dict(self) -> dict:
        return {k: (list(v) if isinstance(v, (list, tuple)) else v)
                for k, v in self.__dict__.items()}

    def prompt_block(self) -> str:
        """把 plan 转成 prompt 注入块（确定性指导，非台词）。"""
        parts = [
            f"【PersonaPlan】mode={self.mode}",
            f"用户语义: act={self.user_dialogue_act}"
            + (f" topic={self.topic}" if self.topic else "")
            + (f" referent={self.referent}" if self.referent else "")
            + (f" need={self.user_need}" if self.user_need else ""),
            f"姿态: {self.stance}（目标: {self.social_goal or '直接回应'}）",
            f"强度: pride={self.pride_level:.2f} vuln={self.vulnerability_level:.2f} "
            f"drama={self.dramatic_intensity:.2f} intimacy={self.intimacy_level:.2f}",
            f"开场: {self.opening_style}（{_OPENING_HINT.get(self.opening_style, '')}）",
            f"长度: {self.response_length}",
        ]
        if self.must_include_semantics:
            parts.append("必须回应: " + "、".join(self.must_include_semantics))
        if self.forbidden_moves:
            parts.append("禁止: " + "；".join(self.forbidden_moves))
        if self.god_register == "off":
            parts.append("自称: 用'我'，不用'本神'（本回合非表演情境）。")
        elif self.god_register == "optional":
            parts.append("自称: 可用一次'本神'表达骄傲/玩笑，但别连用。")
        elif self.god_register == "allowed":
            parts.append("自称: 可用'本神'（表演情境），但保持节制。")
        if self.anti_pattern_note:
            parts.append(f"注意: {self.anti_pattern_note}")
        return "\n".join(parts)


# ================================================================ Planner
# mode 选择（Persona Mode）—— 确定性：由语义帧 + 关系 + 情绪共同决定
_MODE_BY_ACT = {
    "QUIET": "SINCERE",
    "LISTEN_WANT": "SINCERE",
    "CONFIDE": "SINCERE",
    "CHALLENGE": "GUARDED",
    "ABSENCE": "GUARDED",
    "ATTENTION_PROBE": "GUARDED",
    "PRAISE": "PROUD",
    "TEASE": "PLAYFUL",
    "ASK_SELF": "SINCERE",
    "REQUEST_ACTION": "RESPONSIBLE",
    "ANSWER": "CASUAL",
    "COMMENT": "CASUAL",
}


def plan_for(user_text: str, *, mode_hint: str = "", emotion: str = "calm",
             trust: float = 0.5, familiarity: float = 0.5, annoyance: float = 0.1,
             task_mode: bool = False, activity: str = "idle",
             agent_state: str = "", agent_task: str = "",
             history_topic: str = "",
             autobiography_level: Optional[int] = None,
             autobiography_anchor_ids: Optional[List[str]] = None,
             recent_openings: Optional[List[str]] = None) -> PersonaPlan:
    """从用户输入 + 运行时状态 → PersonaPlan（确定性）。"""
    f = parse_user_turn(user_text, history_topic=history_topic)
    plan = PersonaPlan(user_dialogue_act=f.act, user_need=f.emotional_need,
                       topic=f.topic, referent=f.referent, raw=f.raw)
    # ---- mode（显式纠正优先升 SINCERE；动作→RESPONSIBLE；其余按 act）----
    if f.correction:
        plan.mode = "SINCERE"
    elif f.action_request or task_mode:
        plan.mode = "RESPONSIBLE"
    else:
        plan.mode = _MODE_BY_ACT.get(f.act, mode_hint or "CASUAL")
    # 情绪微调（高信任 + 严肃情绪 → SINCERE）
    if f.seriousness >= 0.8 and trust >= 0.55 and plan.mode in ("CASUAL", "PLAYFUL"):
        plan.mode = "SINCERE"
    if annoyance >= 0.6 or trust < 0.25:
        plan.mode = "GUARDED"

    # ---- stance / social_goal / forbidden（按 act 的确定性策略）----
    if f.act == "QUIET":
        plan.stance = "quiet"
        plan.social_goal = "安静陪伴，不安排活动"
        plan.response_length = "MICRO"
        plan.forbidden_moves = ["提供任务/整理文件", "问'怎么玩'", "讲大道理", "激励打气"]
        plan.opening_style = "QUIET_ACKNOWLEDGEMENT"
        plan.dramatic_intensity = 0.15
    elif f.act == "LISTEN_WANT":
        plan.stance = "listening"
        plan.social_goal = "陪着，不分析人生"
        plan.response_length = "SHORT"
        plan.forbidden_moves = ["分析用户人生", "分析自己人格", "解决问题", "讲大道理"]
        if "不用说什么" in f.raw or "安静" in f.raw or "不想说话" in f.raw or "陪我" in f.raw:
            plan.response_length = "MICRO"
            plan.forbidden_moves += ["安排任务/整理文件", "问'怎么玩'", "激励打气"]
        plan.opening_style = "QUIET_ACKNOWLEDGEMENT" if f.seriousness >= 0.7 else "REACTION"
        plan.dramatic_intensity = 0.2
    elif f.act == "CONFIDE":
        plan.stance = "companion"
        plan.social_goal = "先接住情绪，轻声回应，不抢主题"
        plan.response_length = "NORMAL"
        plan.forbidden_moves = ["generic 鼓励('相信自己''你会越来越好'等)", "突然讲完整枫丹主线", "抢用户主题"]
        plan.opening_style = "PAUSE" if f.seriousness >= 0.7 else "REACTION"
        plan.dramatic_intensity = 0.2
        plan.vulnerability_level = 0.2
    elif f.act == "CHALLENGE":
        plan.stance = "guarded_then_open"
        plan.social_goal = "先护姿态，被追问才松动"
        plan.forbidden_moves = ["立即承认'对，我有这个问题'（除非信任极高）", "心理报告式自我分析"]
        plan.opening_style = "COUNTER_QUESTION" if trust < 0.6 else "MOCK_OFFENSE"
        plan.dramatic_intensity = 0.45
        plan.pride_level = 0.7
        plan.god_register = "optional"
    elif f.act == "ABSENCE":
        plan.stance = "does_not_want_to_admit_immediately"
        plan.social_goal = "回答 + 保留尊严（不立即承认很在意）"
        plan.forbidden_moves = ["generic 关系说教", "AI 服务腔", "完全回避问题"]
        plan.opening_style = "COUNTER_QUESTION"
        plan.dramatic_intensity = 0.4
        plan.pride_level = 0.6
        plan.god_register = "optional"
    elif f.act == "ATTENTION_PROBE":
        plan.stance = "layered"
        plan.social_goal = "第一层不承认影响→承认会不习惯→现在不完全靠观众存在"
        plan.forbidden_moves = ["'我会提升自己'式 generic", "立即崩溃/创伤输出"]
        plan.opening_style = "PAUSE"
        plan.dramatic_intensity = 0.3
        plan.autobiography_activation = 2
    elif f.act == "PRAISE":
        plan.stance = "receive_proudly"
        plan.social_goal = "接受赞美但不 servile；可得意/假装矜持/反逗"
        plan.forbidden_moves = ["'谢谢夸奖，我也觉得我很可爱'式 generic", "扭捏否认('没有啦'×N)"]
        plan.opening_style = "PLAYFUL_ASSERTION" if trust >= 0.6 else "REACTION"
        plan.dramatic_intensity = 0.5
        plan.pride_level = 0.65
        plan.god_register = "optional"
        plan.teasing_level = 0.3
    elif f.act == "TEASE":
        plan.stance = "tease_back"
        plan.social_goal = "回击/倒打一耙/把用户拉进戏里"
        plan.opening_style = "COUNTER_QUESTION"
        plan.dramatic_intensity = 0.55
        plan.god_register = "optional"
        plan.teasing_level = 0.5
    elif f.act == "ASK_SELF":
        plan.stance = "sincere_self"
        plan.social_goal = "说'我这个人'：Furina、stage/performance、pride、ordinary life、一个矛盾"
        plan.response_length = "NORMAL"
        plan.forbidden_moves = ["功能/百科式介绍", "'我是一个乐观的人'式 generic", "完美主义模板回答"]
        plan.opening_style = "PAUSE"
        plan.dramatic_intensity = 0.3
        plan.autobiography_activation = max(plan.autobiography_activation, 2)
    elif f.act == "REQUEST_ACTION":
        plan.stance = "responsible"
        plan.social_goal = "明确结果/承担/说清事实（Persona 在 fact core 后）"
        plan.response_length = "SHORT"
        plan.forbidden_moves = ["只答'小事一桩'不报事实", "编造未发生的动作", "把建议说成已执行"]
        plan.dramatic_intensity = 0.3
    else:  # ANSWER / COMMENT
        plan.stance = "direct"
        plan.social_goal = "先回答用户的问题/话题，再考虑表演"
        plan.forbidden_moves = ["万金油话术", "每句都舞台化", "无端历史名词"]
        if f.factual_query:
            plan.must_include_semantics = ["先如实回应问题本身"]
        plan.opening_style = "DIRECT" if f.factual_query else (
            "PLAYFUL_ASSERTION" if emotion in ("happy", "excited") else "REACTION")
        plan.dramatic_intensity = 0.35

    # ---- 约束 / must_answer ----
    if f.explicit_constraint:
        plan.must_answer = True
        plan.must_include_semantics = [f"严格按用户约束回答（只能回答'{f.explicit_constraint[0]}'或'{f.explicit_constraint[1]}'）"]
        plan.forbidden_moves.append("输出约束外的其它内容")
    # ---- 关系微调 ----
    plan.intimacy_level = min(1.0, 0.3 + familiarity * 0.5 + trust * 0.2)
    if plan.intimacy_level >= 0.75 and plan.mode in ("SINCERE", "GUARDED", "PLAYFUL"):
        plan.god_register = "optional" if plan.god_register == "off" else plan.god_register
    # ---- autobiography（外部注入或自算）----
    from .autobiographical import activation_level as _auto_level, match_anchors
    matched = match_anchors(user_text)
    if autobiography_level is not None:
        plan.autobiography_activation = autobiography_level
    else:
        plan.autobiography_activation = _auto_level(
            user_text, mode=plan.mode, trust=trust, task_mode=task_mode, matched=matched)
    if autobiography_anchor_ids is not None:
        plan.autobiography_anchor_ids = list(autobiography_anchor_ids)
    else:
        plan.autobiography_anchor_ids = [aid for aid, _s in matched[:2]]
    # ---- 强度带 ----
    from .furina_canon import DRAMATIC_INTENSITY
    lo, hi = DRAMATIC_INTENSITY.get(plan.mode, (0.3, 0.5))
    plan.dramatic_intensity = round(max(lo, min(hi, plan.dramatic_intensity)), 2)
    # ---- opening 多样性（近 N 次同款开场 → 换一种）----
    if recent_openings and plan.opening_style in recent_openings[-3:]:
        alt = [o for o in ("DIRECT", "REACTION", "COUNTER_QUESTION", "PAUSE") if o != plan.opening_style]
        plan.opening_style = alt[0] if alt else plan.opening_style
        plan.opening_style_reason = "最近同款开场，轮换"
    return plan
