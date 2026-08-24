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
# 舞台动作描写（§35 禁止）
_STAGE_DIRECTION = [r"\*.*?\*", r"（.*?(叹气|笑|移|叉腰|眨眼|低头|沉默|看)）", r"\[.*?\]"]
# 历史 lore 泄漏（§19 普通场景禁）
_LORE_LEAK = ["五百年", "500年", "扮演神", "水神", "芙卡洛斯", "审判庭", "神座", "被看穿", "漫长等待"]
# 戏剧/神性自指（§11 有节制）
_GOD_REF = ["本神", "本小姐", "神明", "枫丹"]


@dataclass
class ValidationResult:
    valid: bool = True
    issues: List[str] = field(default_factory=list)
    god_reference_count: int = 0
    god_overuse_ordinary: bool = False   # 普通情境 god 自指过度（§6-7）

    def as_dict(self) -> dict:
        return {"valid": self.valid, "issues": self.issues,
                "god_reference_count": self.god_reference_count,
                "god_overuse_ordinary": self.god_overuse_ordinary}


class DialogueValidator:
    # 允许旧舞台腔的情境（§7）：performance/celebration/playful boasting/dramatic joke/high-pride
    GOD_ALLOWED_CONTEXTS = {"performing", "celebration", "playful", "boast", "dramatic", "high_pride"}
    # 普通情境（§7）：接近 0
    ORDINARY_CONTEXTS = {"casual", "quiet", "user_busy", "eating", "sleepy", "help", "sad",
                         "vulnerable", "questioned", "failure", "ignored"}

    def __init__(self) -> None:
        self._csn = [re.compile(p) for p in _CSONIC_PATTERNS]
        self._stage = [re.compile(p) for p in _STAGE_DIRECTION]
        self._lore = [re.compile(p) for p in _LORE_LEAK]
        self._god = [re.compile(p) for p in _GOD_REF]

    def validate(self, speech: str, *, should_speak: bool = True,
                 length_cap: int = 120, example_phrases: Optional[List[str]] = None,
                 activity: str = "", context: str = "casual") -> ValidationResult:
        r = ValidationResult()
        s = (speech or "").strip()
        if should_speak and not s:
            r.valid = False; r.issues.append("empty_when_should_speak")
        if not s or not should_speak:
            return r
        if len(s) > length_cap:
            r.valid = False; r.issues.append("too_long")
        for p in self._csn:
            if p.search(s):
                r.valid = False; r.issues.append("generic_assistant_voice"); break
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
        return r
