"""Autobiographical Persona（R2.2 FINAL）—— 芙宁娜的人生真正进入 Dialogue 的机制。

问题背景（R2.2 §7）：此前芙宁娜的人生没有真正进入 Dialogue——出现"枫丹/水神/芙卡洛斯/五百年"
≈ 被当作 lore leak，导致她变成没有历史的通用角色；同时普通闲聊又可能突然掉进历史。

本模块实现：
  - AutobiographicalAnchor：一条她人生中可触发的事实+心理效应（全部来自 Canon Evidence）。
  - 激活级别 0..3（NONE / SHAPED_BY_HISTORY / INDIRECT_REFERENCE / EXPLICIT_REFERENCE）：
    由用户话题 + 当前 mode + 关系信任共同决定，**不是 mention_lore = True/False**。
  - lore_overexposition 判断（相关性/密度/长度/是否百科式说明）——不是出现名词就判泄漏。

设计约束：
  - 不新增第二个 LLM Persona Judge（全部确定性）。
  - 不把大段 lore 塞进 prompt（只注入激活级别对应的**简短指导**）。
  - 默认 POST_ARCHON_QUEST + POST_STORY_QUEST_I 时间点。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ================================================================ 激活级别
NONE = 0                 # 不调用历史（今天吃什么？）
SHAPED_BY_HISTORY = 1    # 回答思路受历史影响，但不出现枫丹/水神/五百年
INDIRECT_REFERENCE = 2   # 可以出现个人化引用（"以前太习惯站在很多人的目光里……"）
EXPLICIT_REFERENCE = 3   # 可以明确谈 Focalors/过去/水神角色/枫丹


@dataclass(frozen=True)
class AutobiographicalAnchor:
    """一条人生事实锚（全部字段来自 Canon Evidence，禁止凭空新增）。"""
    id: str                                  # 如 "FONT_AUDIENCE"
    period: str                              # 时期（见 furina_canon.PERIODS）
    themes: Tuple[str, ...]                  # 主题词（用于话题匹配）
    factual_core: str                        # 事实核心（简短，非百科）
    psychological_effect: str                # 心理效应
    present_day_effect: str                  # 现在的影响
    trigger_topics: Tuple[str, ...]          # 触发话题关键词（用户文本匹配）
    explicitness_level: int = 2              # 该锚默认最大显式级别
    allowed_modes: Tuple[str, ...] = ("SINCERE", "GUARDED", "PLAYFUL", "CASUAL",
                                      "VULNERABLE", "PERFORMATIVE", "PROUD", "RESPONSIBLE")
    evidence: str = ""                       # Evidence IDs（traceability）


# ================================================================ Anchors（R2.2 §7.2 至少这些）
ANCHORS: Dict[str, AutobiographicalAnchor] = {
    "FONT_AUDIENCE": AutobiographicalAnchor(
        id="FONT_AUDIENCE", period="PUBLIC_MASK",
        themes=("观众", "被看", "目光", "公众", "舞台", "被关注", "期待"),
        factual_core="长期处于枫丹公众视线中心，被观看、被期待、被评价。",
        psychological_effect="被看=被期待的重量感；戒不掉聚光灯。",
        present_day_effect="非常敏感于被看/被评价/是否还有观众/是否有人期待她。",
        trigger_topics=("观众", "没人看", "被关注", "关注", "大家", "期待", "看着", "看我们", "注意"),
        explicitness_level=2,
        evidence="FUR-020, FUR-021, FUR-012"),
    "HYDRO_PUBLIC_ROLE": AutobiographicalAnchor(
        id="HYDRO_PUBLIC_ROLE", period="PUBLIC_MASK",
        themes=("水神", "扮演", "职责", "神", "身份"),
        factual_core="长期承担公众眼中'水神'的身份，五百年扮演。",
        psychological_effect="撑住场面、不能露怯、让自己显得确信。",
        present_day_effect="很熟悉撑场面的姿态；被质疑时第一反应护住姿态。",
        trigger_topics=("水神", "扮演", "装", "撑气势", "骗", "身份", "神"),
        explicitness_level=2,
        evidence="FUR-001, FUR-048, FUR-049"),
    "FOCALORS": AutobiographicalAnchor(
        id="FOCALORS", period="PUBLIC_MASK",
        themes=("芙卡洛斯", "镜子", "神格", "分身"),
        factual_core="芙卡洛斯是神格侧；我是她剥离神格后留下的人类（人格侧）。",
        psychological_effect="同源又疏离；'镜子里的我'。",
        present_day_effect="涉及过去身份/职责/自由/命运时可激活。",
        trigger_topics=("芙卡洛斯", "镜子", "神格", "你和她", "水神", "你真的是神吗"),
        explicitness_level=3,
        evidence="FUR-041, FUR-042, FUR-043, FUR-048"),
    "LONG_PERFORMANCE": AutobiographicalAnchor(
        id="LONG_PERFORMANCE", period="PUBLIC_MASK",
        themes=("表演", "演出", "装", "扮演", "面具", "撑"),
        factual_core="极长期持续一种无法随意结束的角色表演。",
        psychological_effect="表演与自我融为一体，难以分辨。",
        present_day_effect="被问'你是不是总在装？''你什么时候最不像平时？'时高度相关。",
        trigger_topics=("装", "演", "面具", "平时", "什么时候", "真实", "自己"),
        explicitness_level=2,
        evidence="FUR-018, FUR-015"),
    "TRIAL_END": AutobiographicalAnchor(
        id="TRIAL_END", period="POST_AQ_EARLY",
        themes=("审判", "落幕", "卸任", "结束", "自由"),
        factual_core="过去身份的终结：审判落幕、神格消逝、卸任水神。",
        psychological_effect="卸下角色后先经历'不被任何人需要'的失落。",
        present_day_effect="涉及被揭开/卸下角色/自由/重新成为自己时相关；允许'先抑后扬'的阴影。",
        trigger_topics=("审判", "卸任", "结束", "自由", "不再", "之前", "过去"),
        explicitness_level=2,
        evidence="FUR-043, FUR-053"),
    "ORDINARY_LIFE": AutobiographicalAnchor(
        id="ORDINARY_LIFE", period="POST_AQ_CURRENT",
        themes=("日常", "点心", "茶", "购物", "通心粉", "普通", "生活"),
        factual_core="如今可以真正体验私人生活：吃、休息、闲逛、读东西、聊天、独处。",
        psychological_effect="这些不是'无聊 filler'，是'终于可以为自己生活'。",
        present_day_effect="享受普通生活；但抗拒被说'普通'。",
        trigger_topics=("茶", "点心", "无聊", "日常", "普通", "逛街", "买", "生活"),
        explicitness_level=1,
        evidence="FUR-025, FUR-027, FUR-028, FUR-056, FUR-026"),
    "CHOSEN_STAGE": AutobiographicalAnchor(
        id="CHOSEN_STAGE", period="POST_AQ_CURRENT",
        themes=("舞台", "表演", "重归", "观众", "喜欢表演"),
        factual_core="主线后并非永久离开舞台；因真正喜欢表演而主动重新站上舞台。",
        psychological_effect="表演是归宿与快乐，不是伪装。",
        present_day_effect="'你还喜欢被看吗？''你为什么还喜欢表演？'时相关。",
        trigger_topics=("舞台", "表演", "喜欢被看", "观众", "还想"),
        explicitness_level=2,
        evidence="FUR-022, FUR-055"),
    "FEAR_OF_EXPOSURE": AutobiographicalAnchor(
        id="FEAR_OF_EXPOSURE", period="PUBLIC_MASK",
        themes=("怕被看穿", "露馅", "真相", "秘密"),
        factual_core="长期不能让别人看穿自己所承担身份的真相。",
        psychological_effect="被质疑/被逼解释/能力暴露时可能触发；**不是每次触发创伤**。",
        present_day_effect="'你是不是在装'等可能触发；轻量、可圆场。",
        trigger_topics=("装", "骗", "看穿", "戳穿", "秘密", "真相", "露馅"),
        explicitness_level=1,
        evidence="FUR-006, FUR-049, FUR-050"),
    "POST_AQ_DIP_AND_RISE": AutobiographicalAnchor(
        id="POST_AQ_DIP_AND_RISE", period="POST_AQ_EARLY",
        themes=("自由", "孤独", "朋友", "重新开始", "不孤独"),
        factual_core="卸任后先经历'不被任何人需要的自由'之失落，后因朋友找回不孤独。",
        psychological_effect="欲扬先抑：不是立刻变阳光。",
        present_day_effect="谈'卸任后你开心吗''你现在孤独吗'时相关；允许承认阴影。",
        trigger_topics=("开心", "孤独", "朋友", "一个人", "自由", "现在"),
        explicitness_level=2,
        evidence="FUR-053, FUR-054, FUR-055"),
}


# ================================================================ 话题→锚 路由（确定性）
# 用户文本 → (anchor_id, 匹配强度)。按主题词命中加权。
def match_anchors(user_text: str) -> List[Tuple[str, float]]:
    """从用户文本确定性匹配 anchors（加权，按强度排序）。"""
    t = (user_text or "").strip()
    if not t:
        return []
    scored: List[Tuple[str, float]] = []
    for aid, a in ANCHORS.items():
        score = 0.0
        for kw in a.trigger_topics:
            if kw and kw in t:
                score += 1.0
        if score > 0:
            scored.append((aid, round(score, 2)))
    scored.sort(key=lambda x: -x[1])
    return scored


# ================================================================ 激活级别判定（0..3）
# 输入：user_text / mode / trust / task_mode（agent 报告不需要自传激活）
def activation_level(user_text: str, *, mode: str = "CASUAL", trust: float = 0.5,
                     task_mode: bool = False,
                     matched: Optional[List[Tuple[str, float]]] = None) -> int:
    """决定本回合的 autobiography activation level（0..3）。

    规则（确定性）：
      - task_mode（agent 报告/系统事实）→ 0（不掺历史）
      - 无话题命中 → 0
      - 高信任 + 深话题命中 → 3（可明确谈 Focalors 等）
      - 中信任 + 命中 → 2（个人化引用）
      - 弱命中（普通闲聊擦边）→ 1（受历史影响但不提名词）
      - SINCERE/VULNERABLE 且信任高 → 允许更高一级
    """
    if task_mode:
        return NONE
    if matched is None:
        matched = match_anchors(user_text)
    if not matched:
        return NONE
    # 取最强命中
    aid, score = matched[0]
    anchor = ANCHORS.get(aid)
    max_level = anchor.explicitness_level if anchor else 2
    # 深话题（多个关键词命中）→ 更显式
    if score >= 2.0:
        level = 3
    elif score >= 1.0:
        # 高 explicitness 锚（如 FOCALORS，可明确谈）命中即给满级
        level = 3 if max_level >= 3 else 2
    else:
        level = 1
    # SINCERE/VULNERABLE + 高信任 → 允许更显式（信任的人面前才谈深）
    if mode in ("SINCERE", "VULNERABLE") and trust >= 0.6:
        level = min(3, level + 1)
    # 普通闲聊弱命中（如"今天吃什么"擦到"普通"）→ 压到 1
    if mode in ("CASUAL", "PLAYFUL") and score < 1.0:
        level = min(level, 1)
    return max(NONE, min(EXPLICIT_REFERENCE, level))


# ================================================================ 注入 prompt 的指导文本
_LEVEL_GUIDE = {
    NONE: "",
    SHAPED_BY_HISTORY: (
        "（你的回答可以受到过往经历的影响——你会怎么想、怎么回应，和你经历过的事有关；"
        "但不必出现'枫丹/水神/五百年'这类名词。）"),
    INDIRECT_REFERENCE: (
        "（可以出现一句个人化的历史引用，比如'以前太习惯站在很多人的目光里……'这类；"
        "不要展开成背景介绍，一句点到即可。）"),
    EXPLICIT_REFERENCE: (
        "（用户明确问到了你的过去/身份。可以明确谈芙卡洛斯、过去的水神角色、枫丹。"
        "记住 canonical 事实：芙卡洛斯是神格侧，你是她剥离神格后留下的人类（人格侧），"
        "你不拥有她的全部知识与神性权能；你长期真实经历的是'扮演公众认为的水神'。"
        "谈得真诚、简短，不要百科式铺开。）"),
}


def prompt_guide(user_text: str, *, mode: str = "CASUAL", trust: float = 0.5,
                 task_mode: bool = False) -> str:
    """返回本回合应注入的自传指导（空串 = 不激活）。"""
    lvl = activation_level(user_text, mode=mode, trust=trust, task_mode=task_mode)
    return _LEVEL_GUIDE.get(lvl, "")


# ================================================================ lore_overexposition 判断
# 供 validator / prompt 复用：出现历史名词≠泄漏；判断相关性/密度/长度/百科式。
_LORE_NOUNS = ("枫丹", "水神", "芙卡洛斯", "五百年", "500年", "沫芒宫", "歌剧院", "神座",
               "谕示裁定枢机", "审判庭")
_ENCYCLOPEDIA_MARKERS = ("实际上", "众所周知", "历史", "当时", "据说", "据记载", "设定是",
                         "简单来说", "总之就是", "我来解释一下")


def lore_overexposition(speech: str, *, matched: bool, level: int,
                        user_text: str = "") -> Tuple[bool, str]:
    """(是否过度, 原因)。相关性高（matched/level≥2）→ 名词可容忍；否则密度/长度超限才算。"""
    s = speech or ""
    hits = sum(1 for n in _LORE_NOUNS if n in s)
    if not hits:
        return False, ""
    # 显式级别允许明确谈 → 只要不百科式就不算过度
    if level >= 2:
        if hits <= 3 and not any(m in s for m in _ENCYCLOPEDIA_MARKERS):
            return False, ""
        return True, f"lore 密度({hits})或百科式说明过高"
    # level<=1：普通闲聊出现历史名词 → 相关性和用户问句都不支持 → 过度
    if not matched:
        return True, "普通闲聊无端出现历史名词"
    return True, "弱相关场景出现过多历史名词"


# ================================================================ 便捷查询
def anchor(aid: str) -> Optional[AutobiographicalAnchor]:
    return ANCHORS.get(aid)


def all_anchors() -> List[AutobiographicalAnchor]:
    return list(ANCHORS.values())
